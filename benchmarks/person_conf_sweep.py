#!/usr/bin/env python3
"""[S] person 검출 임계 스윕 — 현장 평가셋 109장에서 정밀도·재현율 곡선을 잰다.

## 왜
`benchmarks/field_eval_results.md` 실측: person 재현율 56.7%(놓침 87건). 그중 **48건(55.2%)이
conf=0.10 초안에는 존재**했다 — 즉 절반은 "모델이 못 본 것"이 아니라 "운용 임계(0.40)를 못 넘은 것"이다.
임계를 낮추면 얼마나 회수되고 오탐이 얼마나 느는지를 재서, 채택 여부를 사람이 판단할 근거를 만든다.

## 원칙
- **측정만 한다.** `config/tuning.yaml`·`vision.yaml` 을 수정하지 않는다(규칙6 — 운용값 변경은
  이 표를 보고 사람이 결정한다).
- 임계마다 실제로 추론을 다시 돌린다(점수 사후 필터링으로 근사하지 않는다 — NMS·후처리가
  임계에 따라 달라질 수 있어서).
- 모델은 한 번만 로드하고 임계만 바꿔 반복한다.

사용법:
  $env:VIGENT_ALLOW_FALLBACK="1"
  python benchmarks/person_conf_sweep.py
  python benchmarks/person_conf_sweep.py --confs 0.40,0.30,0.20
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cv2  # noqa: E402
import env_guard  # noqa: E402
import tuning  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

_FE = media("field_eval")
_FRAMES = _FE / "frames"
_LABELS = _FE / "labels"
_OUT_MD = _HERE / "person_conf_sweep.md"
IOU_MATCH = 0.50
DEFAULT_CONFS = [0.40, 0.35, 0.30, 0.25, 0.20]


def _iou(a: list[float], b: list[float]) -> float:
    """a,b = [x1,y1,x2,y2] 픽셀."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _gt_person(stem: str, w: int, h: int) -> list[list[float]]:
    p = _LABELS / f"{stem}.txt"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        a = ln.split()
        if int(a[0]) != 0:          # 0 = person (classes.txt 순서)
            continue
        cx, cy, bw, bh = (float(x) for x in a[1:5])
        out.append([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
    return out


def main() -> None:
    env_guard.warn_if_docker_running("person_conf_sweep")
    ap = argparse.ArgumentParser(description="person 임계 스윕(측정 전용 — 설정 파일 미수정)")
    ap.add_argument("--confs", default=",".join(str(c) for c in DEFAULT_CONFS))
    args = ap.parse_args()
    confs = [float(c) for c in args.confs.split(",") if c.strip()]

    cur = float((tuning.section("detect").get("conf") or {}).get("person", 0.40))
    imgsz = int(tuning.val("detect", "imgsz", 960))
    print(f"현재 운용 임계 person={cur} · imgsz={imgsz} (config/tuning.yaml — 이 스크립트는 수정하지 않음)")

    import main as M  # noqa: N813
    bundle = M.STATE.get(M.DEFAULT_THEME) or M._load_theme(M.DEFAULT_THEME)
    guard = bundle["agents"].get("Guard")

    frames = sorted(_FRAMES.glob("*.jpg"))
    print(f"프레임 {len(frames)}장 · 임계 {confs}\n")

    cache = [(p.stem, cv2.imread(str(p))) for p in frames]
    rows = []
    for conf in confs:
        tp = fp = fn = 0
        n_gt = n_dt = 0
        lat: list[float] = []
        for i, (stem, img) in enumerate(cache):
            if img is None:
                continue
            h, w = img.shape[:2]
            gts = _gt_person(stem, w, h)
            n_gt += len(gts)
            t0 = time.perf_counter()
            out = detect_isolated(guard, img, detectors=["person"], conf=conf)
            if i >= 10:
                lat.append((time.perf_counter() - t0) * 1000.0)
            dts = []
            for d in out.get("detections", []):
                if str(d.get("label", "")).lower() != "person":
                    continue
                x1, y1, x2, y2 = d["bbox"]
                if max(x1, y1, x2, y2) <= 1.5:
                    x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
                dts.append(([x1, y1, x2, y2], float(d.get("conf", 0.0))))
            dts.sort(key=lambda x: -x[1])
            n_dt += len(dts)
            used: set[int] = set()
            for g in gts:
                best, best_v = -1, IOU_MATCH
                for j, (bb, _) in enumerate(dts):
                    if j in used:
                        continue
                    v = _iou(g, bb)
                    if v >= best_v:
                        best, best_v = j, v
                if best >= 0:
                    used.add(best)
                    tp += 1
                else:
                    fn += 1
            fp += len(dts) - len(used)
        prec = tp / n_dt * 100 if n_dt else 0.0
        rec = tp / n_gt * 100 if n_gt else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        lat_mean = sum(lat) / len(lat) if lat else 0.0
        rows.append((conf, n_dt, tp, fp, fn, prec, rec, f1, lat_mean))
        mark = "  ← 현재 운용값" if abs(conf - cur) < 1e-9 else ""
        print(f"conf={conf:.2f}  예측{n_dt:>4}  TP{tp:>4} FP{fp:>4} FN{fn:>4}  "
              f"정밀도 {prec:5.1f}%  재현율 {rec:5.1f}%  F1 {f1:5.1f}%  {lat_mean:6.1f}ms{mark}")

    base = next((r for r in rows if abs(r[0] - cur) < 1e-9), None)
    lines = [
        "# person 검출 임계 스윕 — 현장 평가셋 109장",
        "",
        f"측정일 자동기록. imgsz={imgsz}(config/tuning.yaml) · IoU≥{IOU_MATCH} · GT=person {rows[0][2] + rows[0][4]}건.",
        "**측정 전용 — 이 스크립트는 tuning.yaml/vision.yaml 을 수정하지 않는다.**",
        "",
        "| conf | 예측 | TP | FP | FN | 정밀도 | 재현율 | F1 | 지연(ms) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c, nd, tp, fp, fn, p, r, f, lm in rows:
        mk = " ★현재" if abs(c - cur) < 1e-9 else ""
        lines.append(f"| {c:.2f}{mk} | {nd} | {tp} | {fp} | {fn} | {p:.1f}% | {r:.1f}% | {f:.1f}% | {lm:.1f} |")
    if base:
        lines += ["", f"현재 운용값({cur}) 대비 변화:", "",
                  "| conf | 재현율 변화 | 정밀도 변화 | 추가로 잡은 정답 | 늘어난 오탐 |", "|---|---|---|---|---|"]
        for c, nd, tp, fp, fn, p, r, f, lm in rows:
            if abs(c - cur) < 1e-9:
                continue
            lines.append(f"| {c:.2f} | {r - base[6]:+.1f}%p | {p - base[5]:+.1f}%p | "
                         f"{tp - base[2]:+d}건 | {fp - base[3]:+d}건 |")
    lines += ["", "## 해석 시 주의(규칙6·7)",
              "- 임계를 내리면 재현율↑·정밀도↓ 가 동반된다. **안전 용도상 허용 가능한 정밀도 하한을 먼저 정하고**",
              "  이 표에서 고른다. 이 문서는 판단 근거일 뿐 운용값을 바꾸지 않는다.",
              "- 이 표는 현장 평가셋 109장(9개 사고영상) 기준이다. 다른 현장·조명에서 같은 곡선이 나온다는",
              "  보장은 없다(도메인 일반화는 측정되지 않았다).",
              "- 정답지 자체 오차는 미측정(1인 1회 검수) — 모든 수치의 상한을 정답지 품질이 정한다.",
              ]
    _OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n저장: {_OUT_MD}")


if __name__ == "__main__":
    main()
