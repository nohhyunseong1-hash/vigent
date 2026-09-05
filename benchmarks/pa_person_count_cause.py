#!/usr/bin/env python3
"""benchmarks/pa_person_count_cause.py — [PA] 인원수 감소의 원인 파라미터 특정(측정 전용).

pa_person_count_verify.py 결과: 검출 단계는 완전 동일(conf≥0.40 497/497 일치)인데 bytetrack 이
인원을 덜 센다. 중복 겹침은 0건 — 즉 "중복 트랙 제거" 가설은 기각되고, 독립 위치의 트랙이
사라진다. 후보 원인은 ByteTrack 파라미터:
  - BYTETRACK_ACTIVATION(0.70): 신규 트랙 스폰 최소 conf. iou 경로 임계(0.40)보다 훨씬 높다
    → conf 0.40~0.70 구간 사람은 트랙이 생기지 않는다(가설 H1)
  - BYTETRACK_MIN_FRAMES(1) / MIN_IOU(0.10) / HIGH_CONF(0.50)

이 스크립트는 (a) 사라진 트랙의 conf 분포로 H1 을 확인하고, (b) ACTIVATION 만 0.40 으로 낮춘
런을 추가 실행해 인원수·파편화가 어떻게 변하는지 잰다. 제품 코드는 수정하지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import track_quality_baseline as tqb  # noqa: E402
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

VIDEO = media("runs/rfdetr/multi_scene.mp4")
OUT_DIR = _HERE / "results" / "pa_verify"
IOU_CONF = 0.40
MATCH_IOU = 0.5


def _iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def replay(algo: str, activation: float | None = None) -> list[dict[str, Any]]:
    import cv2
    import vision_loader
    from agents import build_agents

    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.TRACK_ALGO = algo
    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    if algo == "bytetrack":
        guard.BYTETRACK_FRAME_RATE = float(fps)
        if activation is not None:
            guard.BYTETRACK_ACTIVATION = float(activation)

    frames: list[dict[str, Any]] = []
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        out = guard.detect(img, detectors=["person"], track_key=f"cause:{algo}:{activation}")
        tracks = [{"tid": int(d.get("tid", -1)), "conf": float(d.get("conf", 0.0)),
                   "box": [float(v) for v in d.get("bbox", [0, 0, 0, 0])]}
                  for d in out.get("detections", [])
                  if str(d.get("label", "")).lower() == "person"]
        frames.append({"idx": idx, "t": idx / fps, "person_count": len(tracks), "tracks": tracks})
        idx += 1
    cap.release()
    return frames


def seg_of(t: float) -> str:
    for s in tqb.SEGMENTS:
        lo, hi = s["range"]
        if lo <= t < hi:
            return str(s["name"])
    return str(tqb.SEGMENTS[-1]["name"])


def unmatched_tids(base: list[dict], other: list[dict]) -> list[dict[str, Any]]:
    """base(iou) 에만 있고 other 에 대응(IoU≥0.5)이 없는 tid + conf 통계 + 지연매칭 여부."""
    n = min(len(base), len(other))
    life: dict[int, list[int]] = {}
    for f in base[:n]:
        for tr in f["tracks"]:
            life.setdefault(tr["tid"], []).append(f["idx"])
    rows = []
    for tid, idxs in life.items():
        cov = 0
        confs = []
        delayed = 0                      # ±15 프레임 내에 other 가 같은 자리를 잡았는가(확정 지연 판별)
        for i in idxs:
            mybox = next((t["box"] for t in base[i]["tracks"] if t["tid"] == tid), None)
            myconf = next((t["conf"] for t in base[i]["tracks"] if t["tid"] == tid), None)
            if myconf is not None:
                confs.append(myconf)
            if mybox is None:
                continue
            if any(_iou(mybox, b["box"]) >= MATCH_IOU for b in other[i]["tracks"]):
                cov += 1
            else:
                for j in range(max(0, i - 15), min(n, i + 16)):
                    if any(_iou(mybox, b["box"]) >= MATCH_IOU for b in other[j]["tracks"]):
                        delayed += 1
                        break
        rows.append({
            "tid": tid, "frames": len(idxs), "cover": cov / len(idxs),
            "delayed_cover": (cov + delayed) / len(idxs),
            "conf_min": round(min(confs), 3) if confs else None,
            "conf_max": round(max(confs), 3) if confs else None,
            "conf_avg": round(sum(confs) / len(confs), 3) if confs else None,
            "seg": seg_of(base[idxs[0]]["t"]),
        })
    return [r for r in rows if r["cover"] < 0.5]


def uniq_tids(frames: list[dict]) -> int:
    return len({t["tid"] for f in frames for t in f["tracks"]})


def avg_pc(frames: list[dict], seg: str | None = None) -> float:
    sel = [f for f in frames if seg is None or seg_of(f["t"]) == seg]
    return sum(f["person_count"] for f in sel) / len(sel) if sel else 0.0


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/3] iou 재생...", flush=True)
    iou_f = replay("iou")
    print("[2/3] bytetrack(ACTIVATION=0.70 기본) 재생...", flush=True)
    bt70 = replay("bytetrack")
    print("[3/3] bytetrack(ACTIVATION=0.40) 재생...", flush=True)
    bt40 = replay("bytetrack", activation=0.40)

    um70 = unmatched_tids(iou_f, bt70)
    um40 = unmatched_tids(iou_f, bt40)
    um70.sort(key=lambda r: -r["frames"])

    print("\n=== A. 사라진 트랙의 conf 분포 (H1: ACTIVATION 0.70 이 원인인가) ===")
    print(f"{'tid':>5} {'구간':>4} {'프레임':>5} {'커버':>6} {'지연포함':>8} {'conf min/avg/max':>22}")
    for r in um70[:14]:
        print(f"{r['tid']:>5} {r['seg']:>4} {r['frames']:>5} {r['cover']:>6.2f} {r['delayed_cover']:>8.2f} "
              f"{str(r['conf_min']):>7}/{str(r['conf_avg']):>6}/{str(r['conf_max']):<6}")
    below = [r for r in um70 if (r["conf_max"] or 0) < 0.70]
    print(f"\n사라진 트랙 {len(um70)}개 중 conf 최댓값이 0.70 미만: {len(below)}개"
          f" ({100*len(below)/len(um70):.0f}%)  ← 0.70 = BYTETRACK_ACTIVATION")

    print("\n=== B. ACTIVATION 0.70 → 0.40 변경 효과 ===")
    print(f"{'지표':<28} {'iou':>8} {'bt(0.70)':>10} {'bt(0.40)':>10}")
    print(f"{'평균 인원수(클립 전체)':<24} {avg_pc(iou_f):>8.2f} {avg_pc(bt70):>10.2f} {avg_pc(bt40):>10.2f}")
    print(f"{'person 고유 tid 수':<26} {uniq_tids(iou_f):>8} {uniq_tids(bt70):>10} {uniq_tids(bt40):>10}")
    print(f"{'대응없는 iou 트랙 수':<25} {'-':>8} {len(um70):>10} {len(um40):>10}")

    print("\n=== C. 구간별 평균 인원수 ===")
    print(f"{'구간':<4} {'iou':>7} {'bt(0.70)':>10} {'bt(0.40)':>10}  {'라벨'}")
    seg_rows = []
    for s in tqb.SEGMENTS:
        nm = str(s["name"])
        a, b, c = avg_pc(iou_f, nm), avg_pc(bt70, nm), avg_pc(bt40, nm)
        if a == 0 and b == 0:
            continue
        print(f"{nm:<4} {a:>7.2f} {b:>10.2f} {c:>10.2f}  {s['label']}")
        seg_rows.append({"seg": nm, "iou": round(a, 2), "bt70": round(b, 2), "bt40": round(c, 2)})

    out = {
        "unmatched_bt70": um70,
        "unmatched_bt40_n": len(um40),
        "below_activation_n": len(below),
        "avg_person_count": {"iou": round(avg_pc(iou_f), 3), "bt70": round(avg_pc(bt70), 3),
                             "bt40": round(avg_pc(bt40), 3)},
        "uniq_tids": {"iou": uniq_tids(iou_f), "bt70": uniq_tids(bt70), "bt40": uniq_tids(bt40)},
        "segments": seg_rows,
    }
    (OUT_DIR / "pa_cause.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    # 장수 소멸 트랙 이미지(눈으로 사람 확인)
    import cv2
    longest = [r for r in um70 if r["frames"] >= 10][:3]
    if longest:
        cap = cv2.VideoCapture(str(VIDEO))
        want: dict[int, int] = {}
        for r in longest:
            for f in iou_f:
                if any(t["tid"] == r["tid"] for t in f["tracks"]):
                    want[f["idx"]] = r["tid"]
                    break
        idx = 0
        while want:
            ok, img = cap.read()
            if not ok:
                break
            if idx in want:
                tid = want.pop(idx)
                h, w = img.shape[:2]
                for t in iou_f[idx]["tracks"]:
                    x1, y1, x2, y2 = t["box"]
                    hit = t["tid"] == tid
                    col = (0, 0, 255) if hit else (0, 180, 0)
                    cv2.rectangle(img, (int(x1*w), int(y1*h)), (int(x2*w), int(y2*h)), col, 3 if hit else 1)
                    cv2.putText(img, f"tid{t['tid']} {t['conf']:.2f}", (int(x1*w), max(14, int(y1*h)-6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 2)
                cv2.putText(img, f"f{idx} bt(0.70) 미검출 tid{tid}", (8, 26),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 0), 2)
                p = OUT_DIR / f"lost_tid{tid}_f{idx:04d}.jpg"
                cv2.imwrite(str(p), img)
                print("  이미지:", p)
            idx += 1
        cap.release()
    print(f"\n저장: {OUT_DIR / 'pa_cause.json'}")


if __name__ == "__main__":
    main()
