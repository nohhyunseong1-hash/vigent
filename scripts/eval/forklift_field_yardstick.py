#!/usr/bin/env python3
"""scripts/eval/forklift_field_yardstick.py — 8/27 학원 9장면 929프레임 "대본 기준 검출률"을 **운용 경로(guard.detect → signals.forklift_present)** 로 잰다. [2026-09-26 결정 ①]

같은 잣대: 현장 당시 97.7 %(908/929) 는 학원 프로파일 워커가 프레임마다 남긴 dets.jsonl 의 `signals.forklift_present` 를 장면 대본(지게차 상시 존재)에 대비한 값.
이 스크립트는 같은 overlay 프레임(dets 행 수만큼 균등 추림)을 지정 테마의 Guard 에 넣어 같은 신호를 센다. 테마만 바꾸면 boda_ax(YOLO) vs fk2(RF-DETR) 가 같은 잣대가 된다.
★단서: overlay.mp4 는 박스가 그려진 640×360 표시용 영상(원본 미보존). 00_스모크 2장면(27프레임)은 929 집계에서 제외(현장 보고서와 동일).

사용:
    python scripts/eval/forklift_field_yardstick.py --theme academy_boda_tmp --label boda_ax --conf-forklift 0.5
    python scripts/eval/forklift_field_yardstick.py --theme academy_fk2_tmp  --label fk_510_smoke --conf-forklift 0.5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import data_paths as _dp  # noqa: E402
import defaults as _defaults  # noqa: E402

FIELD_ROOT = str(_dp.field_root() / "20260827" / "field_20260827")    # [B-4] 방문 날짜는 --root 로
SMOKE_PREFIX = "00_"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", required=True); ap.add_argument("--label", required=True)
    ap.add_argument("--root", default=FIELD_ROOT); ap.add_argument("--conf-forklift", type=float, default=_defaults.FORKLIFT_OP_CONF)
    ap.add_argument("--out", default=""); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    import cv2
    os.environ.setdefault("VIGENT_INCLUDE_FORKLIFT", "1")
    import app_state
    guard = app_state.load_theme(a.theme)["agents"]["Guard"]
    guard.DETECTOR_CONF["forklift"] = a.conf_forklift          # 두 모델을 같은 운용점(0.50)으로
    st = guard.status()
    print(f"[yardstick] theme={a.theme} · 검출기 {st.get('detectors_available')} · forklift conf {a.conf_forklift}")
    print(f"  슬롯: {json.dumps({k: v for k, v in (st.get('slots') or {}).items() if 'forklift' in str(k)}, ensure_ascii=False)[:300]}")
    scenes = {}; tot = {"frames": 0, "present": 0, "boda_present": 0}; lat = []
    for sc in sorted(os.listdir(a.root)):
        d = Path(a.root) / sc
        if not (d / "dets.jsonl").exists() or not (d / "overlay.mp4").exists():
            continue
        rows = [json.loads(ln) for ln in (d / "dets.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        cap = cv2.VideoCapture(str(d / "overlay.mp4")); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        k = len(rows); idx = [int(i * n / k) for i in range(k)] if n and k else []
        if a.limit:
            idx = idx[: a.limit]
        present = 0; boda = sum(1 for r in rows[: len(idx)] if (r.get("signals") or {}).get("forklift_present"))
        for fi in idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, fr = cap.read()
            if not ok:
                continue
            t0 = time.perf_counter()
            res = guard.detect(fr, detectors=["person", "ppe", "forklift"], track_key=f"yard:{a.label}:{sc}")
            lat.append((time.perf_counter() - t0) * 1000)
            sig = res.get("signals") or {}
            present += int(bool(sig.get("forklift_present")))
        cap.release()
        scenes[sc] = {"frames": len(idx), "present": present, "rate": round(present / len(idx) * 100, 1) if idx else None,
                      "boda_dets_jsonl": boda, "boda_rate": round(boda / len(idx) * 100, 1) if idx else None, "smoke": sc.startswith(SMOKE_PREFIX)}
        print(f"  {sc}: {present}/{len(idx)} ({scenes[sc]['rate']}%) · 현장 dets.jsonl {boda}/{len(idx)}")
        if not sc.startswith(SMOKE_PREFIX):
            tot["frames"] += len(idx); tot["present"] += present; tot["boda_present"] += boda
    lat.sort()
    res = {"date": time.strftime("%Y-%m-%d %H:%M"), "theme": a.theme, "label": a.label, "conf_forklift": a.conf_forklift,
           "yardstick": "장면 대본(지게차 상시 존재) 대비 signals.forklift_present 프레임 비율 · 00_스모크 제외 · overlay.mp4(박스 그려진 표시용)",
           "scenes": scenes, "total_9scenes": {**tot, "rate": round(tot["present"] / tot["frames"] * 100, 1) if tot["frames"] else None,
                                                "boda_rate_from_dets": round(tot["boda_present"] / tot["frames"] * 100, 1) if tot["frames"] else None},
           "detect_ms": {"p50": round(lat[len(lat) // 2], 1), "p95": round(lat[int(len(lat) * 0.95)], 1), "n": len(lat)} if lat else None}
    out = Path(a.out) if a.out else _ROOT / "audit" / f"forklift_yardstick_{a.label}_{time.strftime('%Y%m%d_%H%M')}.json"
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"== 9장면 합계: {tot['present']}/{tot['frames']} = {res['total_9scenes']['rate']}% (현장 dets.jsonl 기준 {res['total_9scenes']['boda_rate_from_dets']}%) · detect p50 {res['detect_ms']['p50'] if lat else '-'} ms → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
