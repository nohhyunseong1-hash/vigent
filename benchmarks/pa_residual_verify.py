#!/usr/bin/env python3
"""benchmarks/pa_residual_verify.py — [PA 후속] 활성화 임계 연동 검증 + 잔여 손실의 정체(측정 전용).

검증 1: 연동 빌드(_activation_threshold → DETECTOR_CONF['person']=0.40)의 A/B 결과가
        이전 수동 bt(activation=0.40) 결과(평균 인원 2.09 / 고유 tid 17 / 미대응 15)와 일치하는지.
검증 2: 남은 미대응 iou 트랙 각각을 3단계로 분류한다.
        a. 생존 프레임 수 + conf 최댓값
        b. 소멸 시점(미대응 프레임)에 그 자리에 **raw detection 이 실제로 있었는지**
           - 있었다 → bt 가 검출을 받고도 트랙을 못 만든 것(= bt 손실)
           - 없었다 → iou 가 검출 없이 트랙을 관성 유지하며 센 것(= iou 코스팅/유령 과대카운트)
        c. 대표 프레임 확대 이미지(사람/유령 육안 판정용)

raw detection 은 _track 진입 직전(NMS·containment 통과분)을 런타임 래핑으로 관찰한다 — 제품 코드 무수정.
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

VIDEO = _ROOT / "runs" / "rfdetr" / "multi_scene.mp4"
OUT_DIR = _HERE / "results" / "pa_verify"
MATCH_IOU = 0.5
RAW_HIT_IOU = 0.5      # "그 자리에 raw 검출이 있었나" 판정 IoU


def _iou(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def replay(algo: str) -> list[dict[str, Any]]:
    """전 프레임 재생. _track 입력(raw)과 출력(tracks)을 프레임별로 기록."""
    import cv2
    import vision_loader
    from agents import build_agents

    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.TRACK_ALGO = algo
    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    if algo == "bytetrack":
        guard.BYTETRACK_FRAME_RATE = float(fps)
        print(f"      실효 스폰 임계 = {guard._activation_threshold():.2f}"
              f" (person 운용 임계 {guard.DETECTOR_CONF.get('person')})", flush=True)

    cap_state: dict[str, Any] = {"pre": []}
    orig = guard._track

    def _wrapped(fresh: list[dict[str, Any]], track_key: str) -> list[dict[str, Any]]:
        cap_state["pre"] = [{"conf": float(p.get("conf", 0.0)),
                             "box": [float(v) for v in p.get("bbox", [0, 0, 0, 0])]}
                            for p in fresh if str(p.get("label", "")).lower() == "person"]
        return orig(fresh, track_key)

    guard._track = _wrapped
    frames: list[dict[str, Any]] = []
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        cap_state["pre"] = []
        out = guard.detect(img, detectors=["person"], track_key=f"res:{algo}")
        frames.append({
            "idx": idx, "t": idx / fps,
            "raw": list(cap_state["pre"]),
            "tracks": [{"tid": int(d.get("tid", -1)), "conf": float(d.get("conf", 0.0)),
                        "box": [float(v) for v in d.get("bbox", [0, 0, 0, 0])]}
                       for d in out.get("detections", [])
                       if str(d.get("label", "")).lower() == "person"],
        })
        idx += 1
    cap.release()
    guard._track = orig
    return frames


def seg_of(t: float) -> str:
    for s in tqb.SEGMENTS:
        lo, hi = s["range"]
        if lo <= t < hi:
            return str(s["name"])
    return str(tqb.SEGMENTS[-1]["name"])


def classify(iou_f: list[dict], bt_f: list[dict]) -> list[dict[str, Any]]:
    """미대응 iou 트랙을 'bt 손실' / 'iou 코스팅' / '판정 불가'로 분류."""
    n = min(len(iou_f), len(bt_f))
    life: dict[int, list[int]] = {}
    for f in iou_f[:n]:
        for tr in f["tracks"]:
            life.setdefault(tr["tid"], []).append(f["idx"])

    rows = []
    for tid, idxs in life.items():
        cov = 0
        confs, raw_hit, raw_miss, miss_frames = [], 0, 0, []
        for i in idxs:
            mybox = next((t["box"] for t in iou_f[i]["tracks"] if t["tid"] == tid), None)
            myconf = next((t["conf"] for t in iou_f[i]["tracks"] if t["tid"] == tid), None)
            if mybox is None:
                continue
            if myconf is not None:
                confs.append(myconf)
            if any(_iou(mybox, b["box"]) >= MATCH_IOU for b in bt_f[i]["tracks"]):
                cov += 1
                continue
            # 미대응 프레임 — 그 자리에 bt 런의 raw 검출이 있었는가?
            miss_frames.append(i)
            if any(_iou(mybox, r["box"]) >= RAW_HIT_IOU for r in bt_f[i]["raw"]):
                raw_hit += 1
            else:
                raw_miss += 1
        if not idxs or cov / len(idxs) >= 0.5:
            continue                                  # 대응됨 — 분석 대상 아님
        miss_n = raw_hit + raw_miss
        ratio_hit = raw_hit / miss_n if miss_n else 0.0
        if miss_n == 0:
            verdict = "판정 불가"
        elif ratio_hit >= 0.7:
            verdict = "bt 손실"          # 검출은 있었는데 트랙이 안 생김
        elif ratio_hit <= 0.3:
            verdict = "iou 코스팅"       # 검출이 없는데 iou 가 세고 있었음
        else:
            verdict = "판정 불가"
        rows.append({
            "tid": tid, "seg": seg_of(iou_f[idxs[0]]["t"]), "frames": len(idxs),
            "cover": round(cov / len(idxs), 2),
            "conf_max": round(max(confs), 3) if confs else None,
            "conf_avg": round(sum(confs) / len(confs), 3) if confs else None,
            "miss_frames_n": miss_n, "raw_hit": raw_hit, "raw_miss": raw_miss,
            "raw_hit_ratio": round(ratio_hit, 2),
            "verdict": verdict,
            "sample_frame": miss_frames[len(miss_frames) // 2] if miss_frames else None,
        })
    rows.sort(key=lambda r: -r["frames"])
    return rows


def avg_pc(frames: list[dict], seg: str | None = None) -> float:
    sel = [f for f in frames if seg is None or seg_of(f["t"]) == seg]
    return sum(len(f["tracks"]) for f in sel) / len(sel) if sel else 0.0


def avg_raw(frames: list[dict], seg: str | None = None) -> float:
    sel = [f for f in frames if seg is None or seg_of(f["t"]) == seg]
    return sum(len(f["raw"]) for f in sel) / len(sel) if sel else 0.0


def save_zooms(iou_f: list[dict], rows: list[dict]) -> None:
    """대표 프레임 확대 이미지 — 순차 재생으로 tid 재현(트래커 상태 의존)."""
    import cv2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    want = {r["sample_frame"]: r for r in rows if r["sample_frame"] is not None}
    if not want:
        return
    cap = cv2.VideoCapture(str(VIDEO))
    idx = 0
    while idx <= max(want):
        ok, img = cap.read()
        if not ok:
            break
        if idx in want:
            r = want[idx]
            box = next((t["box"] for t in iou_f[idx]["tracks"] if t["tid"] == r["tid"]), None)
            if box:
                h, w = img.shape[:2]
                px1, py1, px2, py2 = int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)
                m = int(max(px2-px1, py2-py1) * 1.8) + 25
                cx, cy = (px1+px2)//2, (py1+py2)//2
                a, b = max(0, cx-m), max(0, cy-m)
                c, d = min(w, cx+m), min(h, cy+m)
                crop = img[b:d, a:c].copy()
                if crop.size:
                    sc = max(2, 380 // max(1, crop.shape[0]))
                    crop = cv2.resize(crop, (crop.shape[1]*sc, crop.shape[0]*sc),
                                      interpolation=cv2.INTER_CUBIC)
                    cv2.rectangle(crop, ((px1-a)*sc, (py1-b)*sc), ((px2-a)*sc, (py2-b)*sc), (0, 0, 255), 2)
                    p = OUT_DIR / f"res_tid{r['tid']}_{r['verdict'].replace(' ', '')}_f{idx}.jpg"
                    cv2.imwrite(str(p), crop)
                    print(f"  이미지: {p.name}  (tid{r['tid']} {r['verdict']}, conf max {r['conf_max']})")
        idx += 1
    cap.release()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/2] iou 재생...", flush=True)
    iou_f = replay("iou")
    print("[2/2] bytetrack(연동 빌드) 재생...", flush=True)
    bt_f = replay("bytetrack")

    iou_tids = len({t["tid"] for f in iou_f for t in f["tracks"]})
    bt_tids = len({t["tid"] for f in bt_f for t in f["tracks"]})
    rows = classify(iou_f, bt_f)

    print("\n=== 검증 1: 연동 빌드 = 이전 수동 activation 0.40 인가 ===")
    print(f"{'지표':<24} {'이전 bt(0.40)':>14} {'연동 빌드':>12} {'일치':>6}")
    exp = {"pc": 2.09, "tid": 17, "unmatched": 15}
    got = {"pc": round(avg_pc(bt_f), 2), "tid": bt_tids, "unmatched": len(rows)}
    for k, name in [("pc", "평균 인원수"), ("tid", "person 고유 tid"), ("unmatched", "미대응 iou 트랙")]:
        ok = "✅" if abs(float(got[k]) - float(exp[k])) < (0.02 if k == "pc" else 0.5) else "❌"
        print(f"{name:<22} {exp[k]:>14} {got[k]:>12} {ok:>6}")
    print(f"(참고) iou 평균 인원수 {avg_pc(iou_f):.2f} / 고유 tid {iou_tids}")

    print("\n=== 검증 2: 잔여 미대응 트랙 분류 ===")
    print(f"{'tid':>5} {'구간':>4} {'프레임':>5} {'conf max':>9} {'미대응F':>7} "
          f"{'raw있음':>7} {'raw없음':>7} {'판정':>10}")
    for r in rows:
        print(f"{r['tid']:>5} {r['seg']:>4} {r['frames']:>5} {str(r['conf_max']):>9} "
              f"{r['miss_frames_n']:>7} {r['raw_hit']:>7} {r['raw_miss']:>7} {r['verdict']:>10}")

    from collections import Counter
    cnt = Counter(r["verdict"] for r in rows)
    print(f"\n분류 집계: {dict(cnt)}  (총 {len(rows)})")

    print("\n=== 구간별 인원수 vs raw 검출 수 (코스팅 과대카운트 단서) ===")
    print(f"{'구간':<4} {'iou raw':>8} {'iou 인원':>9} {'차이':>7} {'bt raw':>8} {'bt 인원':>8} {'차이':>7}")
    seg_rows = []
    for s in tqb.SEGMENTS:
        nm = str(s["name"])
        ir, ip = avg_raw(iou_f, nm), avg_pc(iou_f, nm)
        br, bp = avg_raw(bt_f, nm), avg_pc(bt_f, nm)
        if ir == 0 and ip == 0:
            continue
        print(f"{nm:<4} {ir:>8.2f} {ip:>9.2f} {ip-ir:>+7.2f} {br:>8.2f} {bp:>8.2f} {bp-br:>+7.2f}")
        seg_rows.append({"seg": nm, "iou_raw": round(ir, 2), "iou_pc": round(ip, 2),
                         "bt_raw": round(br, 2), "bt_pc": round(bp, 2)})

    save_zooms(iou_f, rows)
    (OUT_DIR / "pa_residual.json").write_text(
        json.dumps({"verify1": {"expected": exp, "got": got},
                    "rows": rows, "counts": dict(cnt), "segments": seg_rows},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {OUT_DIR / 'pa_residual.json'}")


if __name__ == "__main__":
    main()
