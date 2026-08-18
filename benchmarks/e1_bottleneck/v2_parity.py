#!/usr/bin/env python3
"""[V2] ONNX 동일성 검증 — 같은 입력 프레임 배치에서 torch 대비 박스·클래스·점수 일치 확인.

★채택 조건이다. tests/test_rfdetr_onnx_parity.py 의 판정 기준을 그대로 재사용한다:
    - 같은 라벨끼리 IoU ≥ 0.90 으로 매칭
    - 매칭된 검출: bbox 최대 오차 < 0.02(정규화), 점수 오차 < 0.05
    - 미매칭: 프레임당 2개까지 허용(운용 임계 경계에 걸친 검출은 backend 부동소수 차이로 뜨고 짐)
단일 데모 이미지가 아니라 **실제 현장 프레임 배치**로 돌려 불일치율을 수치로 낸다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("D:/vigent_original")
sys.path.insert(0, str(ROOT / "vigent-core"))
import cv2  # noqa: E402
from agents.guard import JUNK_LABELS, LABEL_NORMALIZE  # noqa: E402
from detectors.rfdetr_adapter import RfdetrDetector  # noqa: E402

IOU_MATCH = 0.90
BBOX_TOL = 0.02
CONF_TOL = 0.05
MAX_UNMATCHED_PER_FRAME = 2

SLOTS: dict[str, tuple[Path, float]] = {
    # 슬롯 → (원본 pth, 운용 임계)
    "ppe":        (ROOT / "vigent-core/weights/ppe_rfdetr_v1.pth", 0.35),
    # fire_smoke 운용점: 클래스별 맵의 최저값(fire 0.30)을 쓴다 — guard 가 추론 시 쓰는 값과 동일
    "fire_smoke": (ROOT / "vigent-core/weights/fire_smoke_rfdetr_v1_e17.pth", 0.30),
    # forklift 운용점: tuning.yaml 0.002 (F-7 과소학습 상태 그대로 — 자원/동일성만 본다)
    "forklift":   (ROOT / "vigent-core/weights/forklift_rfdetr_v1.pth", 0.002),
}


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ub = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    u = ua + ub - inter
    return inter / u if u > 0 else 0.0


def frames(n: int = 24) -> list:
    out = []
    vids = sorted((ROOT / "runs/rfdetr/accident").glob("*.mp4"))[:6]
    per = max(1, n // max(1, len(vids)))
    for v in vids:
        cap = cv2.VideoCapture(str(v))
        got = 0
        idx = 0
        while got < per:
            ok, f = cap.read()
            if not ok:
                break
            if idx % 15 == 0:          # 15프레임 간격으로 뽑아 장면 다양성 확보
                out.append(f)
                got += 1
            idx += 1
        cap.release()
    return out


def detect_all(backend: str, pth: Path, imgs: list, conf: float):
    os.environ["VIGENT_DETECT_BACKEND"] = backend
    det = RfdetrDetector(str(pth), LABEL_NORMALIZE, JUNK_LABELS, resolution=384)
    cls = type(det.model).__name__
    return [det.detect(im, conf=conf) for im in imgs], cls


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    conf_override = float(sys.argv[2]) if len(sys.argv) > 2 else None   # 진단 전용(판정 아님)
    imgs = frames()
    print(f"검증 프레임 {len(imgs)}장", flush=True)
    report = []

    for slot, (pth, conf) in SLOTS.items():
        if only and slot != only:
            continue
        if conf_override is not None:
            conf = conf_override
        onnx_p = pth.with_suffix(".onnx")
        if not onnx_p.exists():
            print(f"  [{slot}] .onnx 없음 — 건너뜀", flush=True)
            continue
        t_dets, t_cls = detect_all("torch", pth, imgs, conf)
        o_dets, o_cls = detect_all("onnx-cpu", pth, imgs, conf)
        if o_cls != "_OnnxRfdetrModel":
            print(f"  [{slot}] ★ONNX 로 안 갈렸다(torch 폴백) — 검증 무의미", flush=True)
            report.append({"slot": slot, "verdict": "INVALID", "onnx_model_cls": o_cls})
            continue

        n_t = n_o = n_match = n_unmatched = 0
        worst_bbox = worst_conf = 0.0
        bad_frames = 0
        for td, od in zip(t_dets, o_dets):
            n_t += len(td)
            n_o += len(od)
            rem = list(od)
            un = 0
            for t in td:
                bi, bj = 0.0, -1
                for j, o in enumerate(rem):
                    if o["label"] != t["label"]:
                        continue
                    v = iou(t["bbox"], o["bbox"])
                    if v > bi:
                        bi, bj = v, j
                if bj == -1 or bi < IOU_MATCH:
                    un += 1
                    continue
                o = rem.pop(bj)
                n_match += 1
                worst_bbox = max(worst_bbox, max(abs(a - b) for a, b in zip(t["bbox"], o["bbox"])))
                worst_conf = max(worst_conf, abs(t["conf"] - o["conf"]))
            un += len(rem)
            n_unmatched += un
            if un > MAX_UNMATCHED_PER_FRAME:
                bad_frames += 1

        total = max(1, n_t + n_o)
        mismatch_rate = round(100.0 * n_unmatched / total, 2)
        ok = (bad_frames == 0 and worst_bbox < BBOX_TOL and worst_conf < CONF_TOL)
        rec = {"slot": slot, "frames": len(imgs), "torch_dets": n_t, "onnx_dets": n_o,
               "matched": n_match, "unmatched": n_unmatched,
               "mismatch_rate_pct": mismatch_rate,
               "max_bbox_err": round(worst_bbox, 5), "max_conf_err": round(worst_conf, 5),
               "frames_over_tolerance": bad_frames,
               "verdict": "PASS" if ok else "FAIL"}
        report.append(rec)
        print(f"  [{slot}] {rec['verdict']} · torch {n_t}건 / onnx {n_o}건 · 매칭 {n_match} · "
              f"불일치율 {mismatch_rate}% · 최대 bbox오차 {rec['max_bbox_err']} · "
              f"최대 점수차 {rec['max_conf_err']} · 허용초과 프레임 {bad_frames}장", flush=True)

    Path("v2_parity.json" if conf_override is None else f"v2_parity_diag_{conf_override}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if all(r.get("verdict") == "PASS" for r in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
