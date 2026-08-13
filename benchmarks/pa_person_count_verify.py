#!/usr/bin/env python3
"""benchmarks/pa_person_count_verify.py — [PA] 인원수 회귀 가설 검증(측정 전용).

배경: track_ab_bytetrack.md 에서 bytetrack 채택 시 평균 person_count 가 2.20→1.97(-10.3%)로
감소했다. "진짜 사람을 놓친 것"인지 "iou 가 중복 트랙으로 부풀리던 것을 걸러낸 것"인지 미확정이라
PA 항목이 사용자 결정 대기로 남아 있었다. 이 스크립트는 그 판정을 위한 3종 증거를 수집한다.

  1. 검출 단계 동일성 — 트래커 진입 직전(_track 입력) person 수를 두 런에서 비교.
     ★중요: bytetrack 모드는 person 슬롯 추론 임계를 BYTETRACK_LOW_CONF(0.28)로 낮춘다
     (guard.py:718) → 원시 검출 수는 설계상 같지 않다. 그래서 conf≥0.40(iou 운용임계) 부분집합을
     따로 집계해 "같은 임계에서 디텍터가 같은 것을 보는가"를 비교한다.
  2. 사라진 트랙의 정체 — iou 런에만 있고 bytetrack 런에 대응 트랙이 없는 tid 의 생존 프레임 분포.
  3. 중복 트랙 직접 증거 — iou 가 더 많이 센 프레임에서 iou 런 박스들의 pairwise IoU.
     겹치는 여분 트랙이 있으면 "한 사람에 트랙 2개".

측정 전용 — guard.py 등 제품 코드는 수정하지 않는다(_track 은 런타임 래핑으로 관찰만).
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

import track_quality_baseline as tqb  # noqa: E402  (SEGMENTS 재사용 — 재구현 아님)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

VIDEO = _ROOT / "runs" / "rfdetr" / "multi_scene.mp4"
OUT_DIR = _HERE / "results" / "pa_verify"
IOU_CONF = 0.40          # iou 런의 person 운용 임계(비교 기준선)
MATCH_IOU = 0.5          # 트랙 대응·중복 판정 임계


def _iou(a: list[float], b: list[float]) -> float:
    """xyxy 정규화 좌표 IoU."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def replay(algo: str) -> list[dict[str, Any]]:
    """한 알고리즘으로 전 프레임 재생하며 _track 입력/출력을 프레임별로 기록."""
    import cv2
    import vision_loader
    from agents import build_agents

    cfg = vision_loader.load_vision("safety")
    guard = build_agents(cfg)["Guard"]
    guard.TRACK_ALGO = algo

    cap = cv2.VideoCapture(str(VIDEO))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    if algo == "bytetrack":
        # 재생은 매 비디오프레임마다 detect() 호출 → lost_buffer 환산 기준을 영상 fps 로
        # (track_ab_bytetrack.py 와 동일 조건 유지)
        guard.BYTETRACK_FRAME_RATE = float(fps)

    captured: dict[str, Any] = {"pre": []}
    orig_track = guard._track

    def _wrapped(fresh: list[dict[str, Any]], track_key: str) -> list[dict[str, Any]]:
        persons = [d for d in fresh if str(d.get("label", "")).lower() == "person"]
        captured["pre"] = [{"conf": float(p.get("conf", 0.0)),
                            "box": [float(v) for v in p.get("bbox", [0, 0, 0, 0])]}
                           for p in persons]
        return orig_track(fresh, track_key)

    guard._track = _wrapped  # 관찰용 래핑(측정 전용, 원본 호출 그대로 위임)

    frames: list[dict[str, Any]] = []
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        captured["pre"] = []
        out = guard.detect(img, detectors=["person"], track_key=f"pa:{algo}")
        pre = captured["pre"]
        tracks = [{"tid": int(d.get("tid", -1)),
                   "conf": float(d.get("conf", 0.0)),
                   "box": [float(v) for v in d.get("bbox", [0, 0, 0, 0])]}
                  for d in out.get("detections", [])
                  if str(d.get("label", "")).lower() == "person"]
        frames.append({
            "idx": idx,
            "t": idx / fps,
            "pre_all": len(pre),                                        # 트래커 진입 person 수(전체)
            "pre_ge": sum(1 for p in pre if p["conf"] >= IOU_CONF),      # 같은 임계(≥0.40) 부분집합
            "pre_boxes_ge": [p["box"] for p in pre if p["conf"] >= IOU_CONF],
            "person_count": len(tracks),                                # 트래커 통과 후(=guard person_count)
            "tracks": tracks,
        })
        idx += 1
    cap.release()
    guard._track = orig_track
    return frames


def seg_of(t: float) -> str:
    for s in tqb.SEGMENTS:
        lo, hi = s["range"]
        if lo <= t < hi:
            return str(s["name"])
    return str(tqb.SEGMENTS[-1]["name"])


def analyze(iou_f: list[dict], bt_f: list[dict]) -> dict[str, Any]:
    n = min(len(iou_f), len(bt_f))
    res: dict[str, Any] = {"n_frames": n}

    # ── 1. 검출 단계 동일성 ────────────────────────────────────────────────
    same_ge = sum(1 for i in range(n) if iou_f[i]["pre_ge"] == bt_f[i]["pre_ge"])
    res["eq1"] = {
        "frames_ge_equal": same_ge,
        "frames_total": n,
        "iou_pre_all_avg": sum(f["pre_all"] for f in iou_f[:n]) / n,
        "bt_pre_all_avg": sum(f["pre_all"] for f in bt_f[:n]) / n,
        "iou_pre_ge_avg": sum(f["pre_ge"] for f in iou_f[:n]) / n,
        "bt_pre_ge_avg": sum(f["pre_ge"] for f in bt_f[:n]) / n,
        "mismatch_frames": [i for i in range(n) if iou_f[i]["pre_ge"] != bt_f[i]["pre_ge"]][:20],
    }

    # ── 2. 사라진 트랙의 정체 ──────────────────────────────────────────────
    # iou tid 별 생존 프레임 + 그 프레임들에서 bt 트랙과 겹치는 비율
    life: dict[int, list[int]] = {}
    for f in iou_f[:n]:
        for tr in f["tracks"]:
            life.setdefault(tr["tid"], []).append(f["idx"])
    unmatched, matched = [], []
    for tid, idxs in life.items():
        cov = 0
        for i in idxs:
            bt_boxes = [t["box"] for t in bt_f[i]["tracks"]]
            mybox = next((t["box"] for t in iou_f[i]["tracks"] if t["tid"] == tid), None)
            if mybox and any(_iou(mybox, b) >= MATCH_IOU for b in bt_boxes):
                cov += 1
        rec = {"tid": tid, "frames": len(idxs), "bt_cover_ratio": cov / len(idxs)}
        (matched if rec["bt_cover_ratio"] >= 0.5 else unmatched).append(rec)
    unmatched.sort(key=lambda r: -r["frames"])
    res["eq2"] = {
        "iou_tid_total": len(life),
        "unmatched_n": len(unmatched),
        "matched_n": len(matched),
        "unmatched_lifetimes": [r["frames"] for r in unmatched],
        "unmatched_top": unmatched[:12],
        "unmatched_le3_frames": sum(1 for r in unmatched if r["frames"] <= 3),
        "unmatched_ge10_frames": [r for r in unmatched if r["frames"] >= 10],
    }

    # ── 3. 중복 트랙 직접 증거 ─────────────────────────────────────────────
    over_frames = [i for i in range(n) if iou_f[i]["person_count"] > bt_f[i]["person_count"]]
    dup_frames, indep_frames = [], []
    for i in over_frames:
        boxes = [t["box"] for t in iou_f[i]["tracks"]]
        pair_max = 0.0
        dup_pairs = []
        for a in range(len(boxes)):
            for b in range(a + 1, len(boxes)):
                v = _iou(boxes[a], boxes[b])
                pair_max = max(pair_max, v)
                if v >= MATCH_IOU:
                    dup_pairs.append((a, b, round(v, 3)))
        rec = {"idx": i, "seg": seg_of(iou_f[i]["t"]),
               "iou_pc": iou_f[i]["person_count"], "bt_pc": bt_f[i]["person_count"],
               "max_pair_iou": round(pair_max, 3), "dup_pairs": dup_pairs}
        (dup_frames if dup_pairs else indep_frames).append(rec)
    res["eq3"] = {
        "over_frames_n": len(over_frames),
        "with_duplicate_overlap": len(dup_frames),
        "without_overlap": len(indep_frames),
        "dup_examples": dup_frames[:10],
        "indep_examples": indep_frames[:10],
    }

    # ── 구간별 표 ──────────────────────────────────────────────────────────
    seg_rows = []
    for s in tqb.SEGMENTS:
        name = str(s["name"])
        ii = [f for f in iou_f[:n] if seg_of(f["t"]) == name]
        bb = [f for f in bt_f[:n] if seg_of(f["t"]) == name]
        if not ii:
            continue
        ov = [r for r in (dup_frames + indep_frames) if r["seg"] == name]
        seg_rows.append({
            "seg": name, "label": s["label"], "frames": len(ii),
            "iou_pre_ge": round(sum(f["pre_ge"] for f in ii) / len(ii), 2),
            "bt_pre_ge": round(sum(f["pre_ge"] for f in bb) / len(bb), 2) if bb else None,
            "iou_pre_all": round(sum(f["pre_all"] for f in ii) / len(ii), 2),
            "bt_pre_all": round(sum(f["pre_all"] for f in bb) / len(bb), 2) if bb else None,
            "iou_pc": round(sum(f["person_count"] for f in ii) / len(ii), 2),
            "bt_pc": round(sum(f["person_count"] for f in bb) / len(bb), 2) if bb else None,
            "over_frames": len(ov),
            "over_with_dup": sum(1 for r in ov if r["dup_pairs"]),
        })
    res["segments"] = seg_rows
    res["_dup_frames"] = dup_frames
    res["_indep_frames"] = indep_frames
    return res


def save_images(iou_f: list[dict], picks: list[dict], tag: str) -> list[str]:
    """지정 프레임에 iou 런 트랙 박스를 그려 저장(눈으로 중복 확인용)."""
    import cv2
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(VIDEO))
    want = {p["idx"]: p for p in picks}
    saved = []
    idx = 0
    while want:
        ok, img = cap.read()
        if not ok:
            break
        if idx in want:
            rec = want.pop(idx)
            h, w = img.shape[:2]
            dup_ids = {a for a, _b, _v in rec["dup_pairs"]} | {b for _a, b, _v in rec["dup_pairs"]}
            for k, tr in enumerate(iou_f[idx]["tracks"]):
                x1, y1, x2, y2 = tr["box"]
                p1 = (int(x1 * w), int(y1 * h))
                p2 = (int(x2 * w), int(y2 * h))
                dup = k in dup_ids
                color = (0, 0, 255) if dup else (0, 200, 0)
                cv2.rectangle(img, p1, p2, color, 3 if dup else 2)
                cv2.putText(img, f"tid{tr['tid']} {tr['conf']:.2f}{' DUP' if dup else ''}",
                            (p1[0], max(14, p1[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            cv2.putText(img, f"f{idx} {rec['seg']} iou_pc={rec['iou_pc']} bt_pc={rec['bt_pc']}"
                             f" maxIoU={rec['max_pair_iou']}",
                        (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
            p = OUT_DIR / f"{tag}_f{idx:04d}.jpg"
            cv2.imwrite(str(p), img)
            saved.append(str(p))
        idx += 1
    cap.release()
    return saved


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/3] iou 런 재생...", flush=True)
    iou_f = replay("iou")
    print(f"      프레임 {len(iou_f)}", flush=True)
    print("[2/3] bytetrack 런 재생...", flush=True)
    bt_f = replay("bytetrack")
    print(f"      프레임 {len(bt_f)}", flush=True)
    print("[3/3] 분석...", flush=True)
    res = analyze(iou_f, bt_f)

    dup_pick = sorted(res["_dup_frames"], key=lambda r: -r["max_pair_iou"])[:4]
    indep_pick = sorted(res["_indep_frames"], key=lambda r: -(r["iou_pc"] - r["bt_pc"]))[:4]
    res["images_dup"] = save_images(iou_f, dup_pick, "dup") if dup_pick else []
    res["images_indep"] = save_images(iou_f, indep_pick, "indep") if indep_pick else []

    out = {k: v for k, v in res.items() if not k.startswith("_")}
    (OUT_DIR / "pa_verify.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                            encoding="utf-8")

    e1, e2, e3 = res["eq1"], res["eq2"], res["eq3"]
    print("\n=== 1. 검출 단계 동일성(트래커 진입 직전) ===")
    print(f"conf≥{IOU_CONF} person 수 프레임 일치: {e1['frames_ge_equal']}/{e1['frames_total']}")
    print(f"평균 pre_all  iou {e1['iou_pre_all_avg']:.2f} / bt {e1['bt_pre_all_avg']:.2f}  (bt 는 임계 0.28)")
    print(f"평균 pre_≥{IOU_CONF} iou {e1['iou_pre_ge_avg']:.2f} / bt {e1['bt_pre_ge_avg']:.2f}")
    if e1["mismatch_frames"]:
        print(f"불일치 프레임(최대 20): {e1['mismatch_frames']}")

    print("\n=== 2. 사라진 트랙의 정체 ===")
    print(f"iou 고유 tid {e2['iou_tid_total']} → bt 대응 있음 {e2['matched_n']} / 없음 {e2['unmatched_n']}")
    print(f"대응 없는 tid 생존 프레임 분포: {e2['unmatched_lifetimes']}")
    print(f"  그중 ≤3프레임(단명): {e2['unmatched_le3_frames']} / ≥10프레임(장수): {len(e2['unmatched_ge10_frames'])}")
    if e2["unmatched_ge10_frames"]:
        print(f"  ★장수 트랙 소멸: {e2['unmatched_ge10_frames']}")

    print("\n=== 3. 중복 트랙 직접 증거 ===")
    print(f"iou 가 더 많이 센 프레임: {e3['over_frames_n']}")
    print(f"  그중 트랙 겹침(IoU≥{MATCH_IOU}) 있음: {e3['with_duplicate_overlap']} / 없음: {e3['without_overlap']}")
    for r in e3["dup_examples"][:5]:
        print(f"   f{r['idx']}({r['seg']}) iou {r['iou_pc']} vs bt {r['bt_pc']} maxIoU {r['max_pair_iou']}")
    for r in e3["indep_examples"][:5]:
        print(f"   [겹침없음] f{r['idx']}({r['seg']}) iou {r['iou_pc']} vs bt {r['bt_pc']} maxIoU {r['max_pair_iou']}")

    print("\n=== 구간별 표 ===")
    print(f"{'구간':<4} {'프레임':>5} {'pre≥.40 iou/bt':>16} {'pre_all iou/bt':>16} {'인원수 iou/bt':>14} {'초과F':>5} {'중복':>4}")
    for s in res["segments"]:
        print(f"{s['seg']:<4} {s['frames']:>5} {s['iou_pre_ge']:>7.2f}/{s['bt_pre_ge']:<8.2f} "
              f"{s['iou_pre_all']:>7.2f}/{s['bt_pre_all']:<8.2f} "
              f"{s['iou_pc']:>6.2f}/{s['bt_pc']:<7.2f} {s['over_frames']:>5} {s['over_with_dup']:>4}")

    print(f"\n저장: {OUT_DIR / 'pa_verify.json'}")
    for p in res["images_dup"] + res["images_indep"]:
        print("  이미지:", p)


if __name__ == "__main__":
    main()
