#!/usr/bin/env python3
"""scripts/eval/analyze_fn_origin.py — person 누락(FN)이 **검출 실패인가 추적 실패인가**를 가른다.

배경(2026-09-22): 경보 경로 person 재현율 38~42%(P0-3)의 원인이 둘 중 무엇인지 확정되지 않았다.
  · 검출 실패  = 검출기가 애초에 못 봤다 → 데이터·모델 보강이 답. 트래커 튜닝은 헛수고.
  · 추적 실패  = 낮은 conf 로라도 봤는데 임계/추적기가 버렸다 → 설정 A/B 로 회수 가능.
이 스크립트는 **판정하지 않는다.** 표만 만든다 — 결론은 사람이 낸다(규칙 7).

★측정만 한다. config/tuning.yaml·vision.yaml 을 수정하지 않는다(규칙 6).
★기존 기준선 수치(benchmarks/x5_recall_knobs_interim.md 등)를 고치지 않는다(규칙 9).

두 부분:
  A (0단계)  — 1fps 정답지의 IoU=0 인접쌍 분류 + 기존 FN 목록과의 프레임 겹침. 검출기 불필요.
  B (0-B)    — 현재 운영 구성으로 FN 을 **재생성**하고, 그 FN 자리에서 검출기를 conf 0.05 로
               돌려 "얼마나 낮은 conf 로 보였는지"를 구간별로 집계한다. 검출기 필요(GPU 권장).

재현:
    python scripts/eval/analyze_fn_origin.py --part a            # 0단계만(빠름, 모델 없이)
    python scripts/eval/analyze_fn_origin.py --part b            # 0-B만(검출기 로드)
    python scripts/eval/analyze_fn_origin.py --part all --json audit/fn_origin_<날짜>.json

판정 기준(이 스크립트가 정한 값 — 표에 함께 싣는다):
    GT 매칭 IoU 0.50(재현율 집계) · 저신뢰 탐색 IoU 0.30 · 등장·퇴장 중심거리 0.25
    작은 박스 = 화면 높이 대비 0.10 미만(기존 x5_recall_knobs.py SMALL_BOX_H 와 동일)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

GT_IOU = 0.50          # 재현율 매칭(기존 평가와 동일)
PROBE_IOU = 0.30       # 저신뢰 검출 탐색 — 지시받은 값
NEAR_DIST = 0.25       # 등장·퇴장 후보 판정 중심거리
SMALL_BOX_H = 0.10     # 작은 박스(원거리 대리지표)
PROBE_CONF = 0.05      # 저신뢰 탐색 추론 임계
BUCKETS = [(0.0, 0.05, "검출 없음"), (0.05, 0.10, "0.05~0.10"), (0.10, 0.28, "0.10~0.28"),
           (0.28, 0.40, "0.28~0.40"), (0.40, 1.01, "0.40 이상(추적기가 버림)")]

_FE_REPO = _ROOT / "data" / "field_eval"


def _xyxy(b: list[float]) -> tuple[float, float, float, float]:
    cx, cy, w, h = b[:4]
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = _xyxy(a)
    bx1, by1, bx2, by2 = _xyxy(b)
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def iou_xyxy(a: list[float], b: list[float]) -> float:
    """[x1,y1,x2,y2] 끼리의 IoU — benchmarks/x5_recall_knobs.py `_iou` 와 동일 식."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def center_dist(a: list[float], b: list[float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def to_xyxy(b: list[float]) -> list[float]:
    """YOLO 정규화 [cx,cy,w,h] → [x1,y1,x2,y2]. 검출기 출력이 xyxy 라 GT 도 맞춰야 한다.

    ★2026-09-22 결함: 이 변환을 빠뜨려 0-B 1차 실행이 TP 0 · 재현율 0.0% 를 냈다(기준선 38.2%).
      규칙 11 "0건 처리는 실패로 의심" 에 걸려 바로 잡았다. part_a 는 GT끼리만 비교하므로 무관.
    """
    cx, cy, w, h = b[:4]
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def load_gt() -> tuple[list[dict], dict[str, list[tuple[int, list[float]]]], list[str]]:
    """매니페스트 · 프레임별 GT 박스 · 클래스명."""
    manifest = json.loads((_FE_REPO / "frames_manifest.json").read_text(encoding="utf-8"))
    names = (_FE_REPO / "classes.txt").read_text(encoding="utf-8").split()
    gt: dict[str, list[tuple[int, list[float]]]] = {}
    for r in manifest:
        stem = Path(r["file"]).stem
        f = _FE_REPO / "labels" / f"{stem}.txt"
        boxes: list[tuple[int, list[float]]] = []
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                p = line.split()
                if len(p) < 5:
                    continue
                try:
                    boxes.append((int(p[0]), [float(v) for v in p[1:5]]))
                except ValueError:
                    continue                    # labels/ 안에 섞인 classes.txt(1필드) 무시
        gt[stem] = boxes
    return manifest, gt, names


# ── A: 0단계 — IoU=0 인접쌍 분류 + 기존 FN 겹침 ──────────────────────────────────────────
def part_a() -> dict[str, Any]:
    manifest, gt, names = load_gt()
    split = json.loads((_FE_REPO / "dev_test_split.json").read_text(encoding="utf-8"))
    dev = set(split["dev"])
    byv: dict[str, list[dict]] = {}
    for r in manifest:
        byv.setdefault(r["video"], []).append(r)
    for v in byv:
        byv[v].sort(key=lambda x: x["t_ms"])

    person_areas = sorted(b[2] * b[3] for bs in gt.values() for c, b in bs if c == 0)
    q75 = person_areas[int(len(person_areas) * 0.75)] if person_areas else 0.0

    rows: list[dict] = []
    total_pairs = 0
    for _v, frs in byv.items():
        for a, b in zip(frs, frs[1:]):
            if b["t_ms"] - a["t_ms"] != 1000:
                continue
            ga, gb = gt[Path(a["file"]).stem], gt[Path(b["file"]).stem]
            for cls, box in gb:
                cand = [bb for cc, bb in ga if cc == cls]
                if not cand:
                    continue
                total_pairs += 1
                best = max(iou(c, box) for c in cand)
                if best > 0:
                    continue
                d = min(center_dist(c, box) for c in cand)
                area = box[2] * box[3]
                kind = ("등장·퇴장 후보" if d > NEAR_DIST
                        else "카메라 근접(면적 상위25%)" if area >= q75 else "그 외")
                rows.append({"file": b["file"], "cls": names[cls] if cls < len(names) else str(cls),
                             "kind": kind, "dist": round(d, 4), "area": round(area, 5),
                             "dev": b["file"] in dev})

    occ = json.loads((_FE_REPO / "person_occlusion_subset.json").read_text(encoding="utf-8"))
    fn_old = {it["file"] for it in occ["items"]} & dev
    out: dict[str, Any] = {"total_pairs_1000ms": total_pairs, "iou0": len(rows),
                           "person_area_q75": round(q75, 5),
                           "old_fn_source": occ.get("source"), "old_fn_created": occ.get("created"),
                           "old_fn_frames_dev": len(fn_old), "scopes": {}}
    for scope, sel in (("전체 클래스", rows), ("person만", [r for r in rows if r["cls"] == "person"])):
        frames = {r["file"] for r in sel if r["dev"]}
        inter = frames & fn_old
        out["scopes"][scope] = {
            "n": len(sel), "kinds": dict(Counter(r["kind"] for r in sel)),
            "dev_frames": len(frames), "overlap_with_old_fn": len(inter),
            "pct_of_iou0": round(len(inter) / len(frames) * 100, 1) if frames else None,
            "pct_of_fn": round(len(inter) / len(fn_old) * 100, 1) if fn_old else None}
    return out


# ── B: 0-B — FN 재생성 + 저신뢰 탐색 ────────────────────────────────────────────────────
def part_b(split_name: str = "dev") -> dict[str, Any]:
    import cv2
    import vision_loader
    from agents.guard import GuardAgent
    from data_paths import media
    from isolated_detect import detect_isolated

    manifest, gt, names = load_gt()
    split = json.loads((_FE_REPO / "dev_test_split.json").read_text(encoding="utf-8"))
    frames: list[str] = list(split[split_name])
    frames_dir = media("field_eval") / "frames"
    byv: dict[str, list[str]] = {}
    for r in manifest:
        if r["file"] in set(frames):
            byv.setdefault(r["video"], []).append(r["file"])
    for v in byv:
        byv[v].sort(key=lambda f: next(x["t_ms"] for x in manifest if x["file"] == f))

    # ① 현재 운영 구성으로 FN 재생성 — 영상별 시간순·영상 단위 track_key(운영 근사, run_once 와 동일 방식)
    guard = GuardAgent(vision_loader.load_vision("safety"))
    fn_items: list[dict] = []
    n_gt = n_tp = 0
    for vid, fns in byv.items():
        for fn in fns:
            img = cv2.imread(str(frames_dir / fn))
            if img is None:
                continue
            out = guard.detect(img, detectors=["person", "ppe"], track_key=f"fnorigin:{vid}")
            preds = [(d.get("bbox") or [0, 0, 0, 0]) for d in out.get("detections", [])
                     if str(d.get("label", "")).lower() == "person"]
            used: set[int] = set()
            for _c, gbox in [(c, to_xyxy(b)) for c, b in gt[Path(fn).stem] if c == 0]:
                n_gt += 1
                best_i, best_v = -1, 0.0
                for k, pb in enumerate(preds):
                    if k in used:
                        continue
                    v = iou_xyxy(pb, gbox)
                    if v > best_v:
                        best_i, best_v = k, v
                if best_v >= GT_IOU:
                    used.add(best_i)
                    n_tp += 1
                else:
                    fn_items.append({"file": fn, "video": vid, "bbox": gbox})

    # ② FN 자리에서 conf 0.05 저신뢰 탐색 — **추적기를 통째로 우회**해 원 검출을 본다.
    #   ★2026-09-22 결함 2: 처음엔 detect_isolated + BYTETRACK_ACTIVATION 낮추기로 했는데
    #     person 이 **항상 0건**이었다. 원인은 추적기가 첫 프레임을 통째로 버리는 것
    #     (x5_recall_knobs.py:133 "입력 4건 → 출력 0건, 2프레임째부터 3건" 에 이미 기록돼 있었다).
    #     고립 프레임은 매번 '첫 프레임'이라 무엇을 해도 0건이 된다.
    #   운영 코드는 수정하지 않는다 — _track 을 통과 함수로 감싸고 끝나면 되돌린다(규칙 6).
    import agents.guard as GM
    _orig_track = GM.GuardAgent._track
    GM.GuardAgent._track = lambda self, fresh, track_key: list(fresh)   # 추적 없음 = 원 검출
    probe = GuardAgent(vision_loader.load_vision("safety"))
    for it in fn_items:
        img = cv2.imread(str(frames_dir / it["file"]))
        if img is None:
            it["max_conf"] = None
            continue
        out = detect_isolated(probe, img, detectors=["person", "ppe"], conf=PROBE_CONF)
        best = 0.0
        best_iou = 0.0
        best_at_gtiou = 0.0      # IoU>=GT_IOU(0.5) 로 한정한 최대 conf — 위치 문제와 분리하기 위함
        for d in out.get("detections", []):
            if str(d.get("label", "")).lower() != "person":
                continue
            v = iou_xyxy(d.get("bbox") or [0, 0, 0, 0], it["bbox"])
            c = float(d.get("conf", 0.0))
            if v >= PROBE_IOU and c > best:
                best, best_iou = c, v
            if v >= GT_IOU:
                best_at_gtiou = max(best_at_gtiou, c)
        it["max_conf"] = best
        it["max_iou"] = round(best_iou, 3)
        # ★혼동 분리: FN 판정은 IoU>=0.5, 저신뢰 탐색은 IoU>=0.3 이라 "conf 는 높은데 박스가
        #   어긋난 것"(위치 문제)이 추적기 탓으로 오인될 수 있다. 위치까지 맞는 검출이 있었는지 따로 센다.
        it["conf_at_gt_iou"] = best_at_gtiou
    GM.GuardAgent._track = _orig_track            # 원복 — 이후 코드가 운영 동작을 쓰게 한다

    # ③ 구간 집계 + ④ 등장·퇴장/작은박스 표기
    a_rows = part_a()
    enter_exit_frames = set()
    for _v, frs in {v: sorted([x for x in manifest if x["video"] == v], key=lambda x: x["t_ms"])
                    for v in {r["video"] for r in manifest}}.items():
        for p, c in zip(frs, frs[1:]):
            if c["t_ms"] - p["t_ms"] != 1000:
                continue
            ga = [b for cl, b in gt[Path(p["file"]).stem] if cl == 0]
            for cl, box in gt[Path(c["file"]).stem]:
                if cl != 0 or not ga:
                    continue
                if max(iou(x, box) for x in ga) == 0 and min(center_dist(x, box) for x in ga) > NEAR_DIST:
                    enter_exit_frames.add(c["file"])

    buckets: dict[str, dict[str, int]] = {lbl: {"n": 0, "등장·퇴장 프레임": 0, "작은박스": 0,
                                                "위치도맞음": 0}
                                          for _lo, _hi, lbl in BUCKETS}
    for it in fn_items:
        mc = it.get("max_conf")
        if mc is None:
            continue
        lbl = next(lbl for lo, hi, lbl in BUCKETS if lo <= mc < hi)
        buckets[lbl]["n"] += 1
        if it["file"] in enter_exit_frames:
            buckets[lbl]["등장·퇴장 프레임"] += 1
        if it.get("conf_at_gt_iou", 0.0) > 0:
            buckets[lbl]["위치도맞음"] += 1
        if (it["bbox"][3] - it["bbox"][1]) < SMALL_BOX_H:
            buckets[lbl]["작은박스"] += 1
        it["bucket"] = lbl
    return {"split": split_name, "n_gt_person": n_gt, "n_tp": n_tp, "n_fn": len(fn_items),
            "recall_pct": round(n_tp / n_gt * 100, 1) if n_gt else None,
            "fn_frames": len({it["file"] for it in fn_items}),
            "probe_conf": PROBE_CONF, "probe_iou": PROBE_IOU, "gt_iou": GT_IOU,
            "buckets": buckets, "items": fn_items, "part_a": a_rows}


def _print_a(a: dict[str, Any]) -> None:
    print(f"\n[A/0단계] 1,000ms 인접쌍 {a['total_pairs_1000ms']}개 중 IoU=0 {a['iou0']}개")
    print(f"  person 면적 상위25% 기준 {a['person_area_q75']} · 등장·퇴장 중심거리 기준 {NEAR_DIST}")
    for scope, s in a["scopes"].items():
        print(f"  [{scope}] n={s['n']}  " + " · ".join(f"{k} {v}" for k, v in s["kinds"].items()))
        print(f"      dev 프레임 {s['dev_frames']}장 · 기존FN({a['old_fn_frames_dev']}장)과 교집합 "
              f"{s['overlap_with_old_fn']}장 (IoU=0 중 {s['pct_of_iou0']}% · FN 중 {s['pct_of_fn']}%)")
    print(f"  ※기존 FN 목록 출처: {a['old_fn_created']} 생성 — ByteTrack 전환(08-13) 이전 자료")


def _print_b(b: dict[str, Any]) -> None:
    tot = sum(v["n"] for v in b["buckets"].values())
    none_low = b["buckets"]["검출 없음"]["n"] + b["buckets"]["0.05~0.10"]["n"]
    if tot and none_low > tot / 2:
        print(f"\n★'검출 없음 + 0.05~0.10' 이 {none_low}/{tot} 로 과반이다.")
    print(f"\n[B/0-B] split={b['split']} · person GT {b['n_gt_person']}건 · "
          f"TP {b['n_tp']} · FN {b['n_fn']}건({b['fn_frames']}장) · 재현율 {b['recall_pct']}%")
    print(f"  판정: GT매칭 IoU≥{b['gt_iou']} · 저신뢰탐색 conf {b['probe_conf']}·IoU≥{b['probe_iou']}")
    print(f"\n  {'구간':24} {'건수':>5} {'':>8} {'위치도맞음':>8} {'등장·퇴장':>9} {'작은박스':>8}")
    print("  " + "-" * 64)
    for _lo, _hi, lbl in BUCKETS:
        v = b["buckets"][lbl]
        pct = f"({v['n']/tot*100:.1f}%)" if tot else ""
        print(f"  {lbl:24} {v['n']:>5} {pct:>8} {v.get('위치도맞음', 0):>8} "
              f"{v['등장·퇴장 프레임']:>9} {v['작은박스']:>8}")
    print("  " + "-" * 64)
    print(f"  {'합계':24} {tot:>5}")


def main() -> int:
    ap = argparse.ArgumentParser(description="person FN 이 검출 실패인지 추적 실패인지 가르는 표를 만든다")
    ap.add_argument("--part", choices=["a", "b", "all"], default="all")
    ap.add_argument("--split", default="dev", choices=["dev", "test"],
                    help="0-B 대상 분할. test 는 최종 확인 1회만(x5_recall_knobs.py 규칙)")
    ap.add_argument("--json", default="", help="결과를 이 경로에 JSON 으로 저장")
    a = ap.parse_args()

    res: dict[str, Any] = {"params": {"GT_IOU": GT_IOU, "PROBE_IOU": PROBE_IOU, "NEAR_DIST": NEAR_DIST,
                                      "SMALL_BOX_H": SMALL_BOX_H, "PROBE_CONF": PROBE_CONF}}
    if a.part in ("a", "all"):
        res["a"] = part_a()
        _print_a(res["a"])
    if a.part in ("b", "all"):
        res["b"] = part_b(a.split)
        _print_b(res["b"])
    print("\n※이 표는 판정이 아니다 — 원인 결론은 사람이 낸다(규칙 7).")
    if a.json:
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
