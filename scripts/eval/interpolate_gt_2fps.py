#!/usr/bin/env python3
"""scripts/eval/interpolate_gt_2fps.py — 1fps 정답지에서 2fps 정답지 **초안**을 만든다.

★목적(2026-09-22 재정의): **사고 상황 검출기 재현율 + 2fps IDSW.**
  ★**현장 파이프라인 재현율의 근거로 쓰지 않는다.** 사고영상은 현장 카메라가 아니며,
  현장 지표는 재방문 수집(docs/refield_plan_addendum_20260922.md)으로 따로 만든다.

배경(2026-09-21): 현 정답지는 1fps(1,000ms 간격) 표본인데 운용은 2fps(500ms)다.
  추적기 파라미터(match_thresh·lost_buffer·activation)는 **프레임 간격에 직접 민감**하므로
  1fps 정답지로 고른 값을 2fps 운용에 가져가면 틀린 값을 고를 수 있다.
  또한 기존 라벨에 **track ID 가 없어** ID 교체(IDSW)를 잴 수 없다 — 원인 2 검증이 불가능하다.

이 스크립트가 하는 일:
  1. 기존 1fps 라벨의 박스를 프레임 간 짝지어 **track ID 를 부여**한다(클래스별 독립).
  2. 1,000ms 간격 구간의 **중간(+500ms)** 박스를 선형 보간해 초안을 만든다.
  3. 그 시각의 **실제 프레임을 24fps 원본에서 추출**한다(보간 박스를 그릴 바탕).
  4. 사람이 검수할 지점을 **불확실로 표시**한다 — 자동으로 채우지 않는다.

★이 스크립트의 출력은 **초안이다. 정답지가 아니다.** 사람이 뷰어로 검수해 확정한다(규칙 7·11).
★기본은 모의 실행(dry-run). 파일을 쓰려면 --write 를 준다.

사용:
  python scripts/eval/interpolate_gt_2fps.py                 # 모의 실행 — 무엇을 할지 보고만
  python scripts/eval/interpolate_gt_2fps.py --write         # 실제로 프레임·초안 라벨 생성
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

# 짝짓기 판정 상수 — 값을 바꾸면 초안이 달라지므로 리포트에 함께 적는다.
IOU_OK = 0.25          # 이 이상이면 같은 사람으로 자동 채택(2026-09-22: 0.30→0.25)
IOU_MAYBE = 0.05       # 이 미만이면 짝짓기 시도조차 하지 않는다(완전 별개)
CENTER_OK = 0.20       # 중심 거리 — IoU 가 낮아도 이 안이면 후보(2026-09-22: 0.15→0.20)
SIZE_RATIO_OK = 2.5    # ★**변 길이비**(폭·높이 각각 계산해 큰 쪽) 상한. 2026-09-22 정정:
                       #   예전엔 '면적비 1.8' 이라 사람이 다가오면(면적은 제곱으로 변함)
                       #   0.5초에도 후보에서 빠졌다. 변 길이비 2.5 로 바꾼다.
# ★영상 역할(2026-09-22): 긴 간격이 많아 연속 구간이 사실상 없는 영상은 추적/IDSW 집계에서 뺀다.
#   721865 는 8프레임 중 6구간이 긴 간격이라 연속 쌍이 1개뿐 — 검출기 재현율에만 쓴다.
DETECTOR_ONLY_VIDEOS = {"KakaoTalk_20260807_000721865"}
PERSON_ONLY = True     # ★보간 대상은 person 만. 실측상 안전모·마스크는 1fps 에서 IoU 중앙값
                       #   0.000~0.17 로 자동 연결이 불가능하고, 이번 목적(재현율·IDSW)과도 무관.


def _xyxy(b: list[float]) -> tuple[float, float, float, float]:
    """정규화 cx,cy,w,h → x1,y1,x2,y2."""
    cx, cy, w, h = b
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = _xyxy(a)
    bx1, by1, bx2, by2 = _xyxy(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _center_dist(a: list[float], b: list[float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _size_ratio(a: list[float], b: list[float]) -> float:
    """★**변 길이비**(폭·높이 각각의 비 중 큰 쪽). 면적비가 아니다 — 면적은 제곱으로 변해
    0.5초 접근에도 1.8 을 쉽게 넘었다(2026-09-22 정정)."""
    ratios = []
    for i in (2, 3):                       # w, h
        x, y = a[i], b[i]
        if x <= 0 or y <= 0:
            return 99.0
        ratios.append(max(x, y) / min(x, y))
    return max(ratios)


def match_boxes(prev: list[dict], cur: list[dict]) -> list[tuple[int, int, float, str]]:
    """앞 프레임 박스 ↔ 현재 프레임 박스 짝짓기(같은 클래스끼리만, 탐욕적 1:1).

    ★1fps 에서는 사람이 1.5m 움직여 IoU 가 0 인 경우가 흔하다. 그래서 IoU 만으로는 못 짝짓는다.
      중심거리·크기비를 함께 본다. **확신이 낮은 짝은 'maybe' 로 표시해 사람에게 넘긴다.**
    반환: [(prev_idx, cur_idx, score, 확신도('ok'|'maybe'))]
    """
    cands: list[tuple[float, int, int, str]] = []
    for i, p in enumerate(prev):
        for j, c in enumerate(cur):
            if p["cls"] != c["cls"]:
                continue
            iou = _iou(p["box"], c["box"])
            dist = _center_dist(p["box"], c["box"])
            ratio = _size_ratio(p["box"], c["box"])
            # ★후보 = (IoU >= IOU_OK) **OR** (중심거리 <= CENTER_OK **AND** 변길이비 <= SIZE_RATIO_OK)
            #   2026-09-22: 예전엔 크기비를 먼저 AND 로 걸러 IoU 가 충분해도 탈락했다.
            by_iou = iou >= IOU_OK
            by_pos = dist <= CENTER_OK and ratio <= SIZE_RATIO_OK
            if not (by_iou or by_pos):
                continue
            cands.append((iou + (1.0 if by_iou else 0.0), i, j, "cand"))
    # ★후보가 **정확히 1개**면 자동 연결, 0개 또는 2개 이상이면 검수 대상(2026-09-22 지시).
    by_cur: dict[int, list[tuple[float, int]]] = {}
    for score, i, j, _k in cands:
        by_cur.setdefault(j, []).append((score, i))
    cands.sort(reverse=True)
    used_p: set[int] = set()
    used_c: set[int] = set()
    out: list[tuple[int, int, float, str]] = []
    for score, i, j, _k in cands:
        if i in used_p or j in used_c:
            continue
        used_p.add(i)
        used_c.add(j)
        out.append((i, j, score, "ok" if len(by_cur.get(j, [])) == 1 else "maybe"))
    return out


def assign_track_ids(frames: list[dict]) -> dict[str, Any]:
    """영상 한 편의 프레임들에 track ID 를 부여한다(시간순). 기존 라벨은 건드리지 않고 ID 만 붙인다."""
    next_id = 1
    stats = {"ok": 0, "maybe": 0, "new": 0, "ended": 0}
    for k, fr in enumerate(frames):
        if k == 0:
            for b in fr["boxes"]:
                b["tid"] = next_id
                b["link"] = "new"
                next_id += 1
                stats["new"] += 1
            continue
        prev, cur = frames[k - 1]["boxes"], fr["boxes"]
        gap = fr["t_ms"] - frames[k - 1]["t_ms"]
        matches = match_boxes(prev, cur) if gap <= 1000 else []   # 긴 간격은 짝짓지 않는다
        m_cur = {j: (i, conf) for i, j, _s, conf in matches}
        for j, b in enumerate(cur):
            if j in m_cur:
                i, conf = m_cur[j]
                b["tid"] = prev[i]["tid"]
                b["link"] = conf
                stats[conf] += 1
            else:
                b["tid"] = next_id
                b["link"] = "new"
                next_id += 1
                stats["new"] += 1
        stats["ended"] += sum(1 for i in range(len(prev)) if i not in {i for i, _j, _s, _c in matches})
    return {"next_id": next_id, **stats}


def interpolate_midpoints(frames: list[dict]) -> list[dict]:
    """1,000ms 간격 구간의 중간(+500ms) 박스를 선형 보간한다.

    · 앞뒤 프레임에 **같은 tid 가 모두 있을 때만** 보간한다(0.5초는 거의 직선 이동).
    · 한쪽에만 있는 tid(등장·퇴장·가림)는 **보간하지 않고 'needs_review' 로 남긴다** — 사람이 그린다.
    · 간격이 1,000ms 가 아닌 구간은 건너뛴다(원본 확인 대상).
    """
    mids: list[dict] = []
    for a, b in zip(frames, frames[1:]):
        gap = b["t_ms"] - a["t_ms"]
        if gap != 1000:
            # ★[결정 2026-09-22] 긴 간격 구간은 **이번 2fps 정답지에서 제외한다.**
            #   IDSW 평가는 연속 구간에서만 성립하고, 2초 이상 벌어지면 추적 연속성을 잴 수 없다.
            #   단 "사람이 없어서" 가 아님이 확인됐으므로(check_long_gaps.py: 17/17 구간에서
            #   person 검출) 제외 사실과 사유를 메타에 남긴다.
            mids.append({"t_ms": a["t_ms"] + gap / 2, "boxes": [], "gap_ms": gap,
                         "status": "excluded_long_gap", "from": a["t_ms"], "to": b["t_ms"]})
            continue
        pa = {x["tid"]: x for x in a["boxes"]}
        pb = {x["tid"]: x for x in b["boxes"]}
        both = sorted(set(pa) & set(pb))
        only = sorted(set(pa) ^ set(pb))
        boxes = []
        for tid in both:
            x, y = pa[tid], pb[tid]
            boxes.append({"cls": x["cls"], "tid": tid,
                          "box": [(u + v) / 2 for u, v in zip(x["box"], y["box"])],
                          "src": "interp", "link": x.get("link", "ok")})
        mids.append({"t_ms": a["t_ms"] + 500, "boxes": boxes, "gap_ms": gap,
                     "status": "needs_review" if only else "interp",
                     "unmatched_tids": only, "from": a["t_ms"], "to": b["t_ms"]})
    return mids


def load_video_frames(manifest: list[dict], labels_dir: Path) -> dict[str, list[dict]]:
    """매니페스트 + 라벨 파일 → 영상별 시간순 프레임 목록."""
    byv: dict[str, list[dict]] = {}
    for r in manifest:
        stem = Path(r["file"]).stem
        lf = labels_dir / f"{stem}.txt"
        boxes = []
        if lf.exists():
            for line in lf.read_text(encoding="utf-8").splitlines():
                p = line.split()
                if len(p) < 5:
                    continue
                try:
                    cls = int(p[0])
                except ValueError:
                    continue                      # classes.txt 가 labels/ 안에 섞여 있다(1필드 7줄)
                if PERSON_ONLY and cls != 0:
                    continue                      # ★person(0) 만 — PPE 는 기존 1fps 정답지 그대로 둔다
                boxes.append({"cls": cls, "box": [float(v) for v in p[1:5]]})
        byv.setdefault(r["video"], []).append(
            {"t_ms": float(r["t_ms"]), "frame_idx": int(r["frame_idx"]), "file": r["file"], "boxes": boxes})
    for v in byv:
        byv[v].sort(key=lambda x: x["t_ms"])
    return byv


def extract_frame(video: Path, t_ms: float, out: Path) -> tuple[bool, str]:
    """24fps 원본에서 t_ms 시점 프레임 1장을 뽑는다. (성공여부, 사유)"""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return False, "영상 열기 실패"
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        idx = int(round(t_ms / 1000.0 * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, img = cap.read()
        if not ok or img is None:
            return False, f"프레임 {idx} 읽기 실패"
        out.parent.mkdir(parents=True, exist_ok=True)
        # cv2.imwrite 는 실패해도 예외를 안 던진다(규칙 11) — 반환값과 파일 존재를 모두 본다.
        if not cv2.imwrite(str(out), img) or not out.exists() or out.stat().st_size == 0:
            return False, "imwrite 실패(파일 없음/0바이트)"
        return True, f"frame {idx} @ {fps:g}fps"
    finally:
        cap.release()


def main() -> int:
    ap = argparse.ArgumentParser(description="1fps 정답지 → 2fps 정답지 초안(보간 + track ID)")
    ap.add_argument("--write", action="store_true", help="실제로 프레임·초안 라벨을 쓴다(없으면 모의 실행)")
    ap.add_argument("--videos", default="", help="원본 mp4 폴더(기본: VIGENT_DATA_DIR/runs/rfdetr/accident)")
    a = ap.parse_args()

    from data_paths import media
    fe_repo = _ROOT / "data" / "field_eval"
    manifest = json.loads((fe_repo / "frames_manifest.json").read_text(encoding="utf-8"))
    videos_dir = Path(a.videos) if a.videos else media("") / "runs" / "rfdetr" / "accident"
    out_frames = media("field_eval") / "frames_2fps_draft"
    out_labels = fe_repo / "labels_2fps_draft"

    byv = load_video_frames(manifest, fe_repo / "labels")
    print(f"입력: 영상 {len(byv)}종 · 라벨된 프레임 {sum(len(v) for v in byv.values())}장")
    print(f"원본 영상 폴더: {videos_dir}  (존재: {videos_dir.exists()})")
    print(f"출력 프레임: {out_frames}\n출력 라벨: {out_labels}")
    print(f"모드: {'실제 기록(--write)' if a.write else '모의 실행(파일 안 씀)'}\n")

    report: dict[str, Any] = {"generated_at": None, "params": {
        "IOU_OK": IOU_OK, "IOU_MAYBE": IOU_MAYBE, "CENTER_OK": CENTER_OK, "SIZE_RATIO_OK": SIZE_RATIO_OK},
        "videos": {}, "totals": {}}
    tot = {"interp_frames": 0, "interp_boxes": 0, "needs_review": 0, "excluded_long_gap": 0,
           "maybe_links": 0, "extracted": 0, "extract_failed": 0}
    gaps_excluded: list[dict[str, Any]] = []
    try:                                  # 긴 간격 확인 결과가 있으면 최대 conf 를 실어 준다
        _lg = json.loads((_ROOT / "audit" / "long_gaps_20260922.json").read_text(encoding="utf-8"))
        _lgmax = {(g["video"], g["from_ms"], g["to_ms"]):
                  max((f.get("max_conf", 0) for f in g.get("frames", [])), default=0) for g in _lg["gaps"]}
    except Exception:  # noqa: BLE001
        _lgmax = {}
    new_manifest: list[dict] = []

    for v, frames in byv.items():
        ids = assign_track_ids(frames)
        mids = interpolate_midpoints(frames)
        vid = videos_dir / f"{v}.mp4"
        vrep: dict[str, Any] = {"labeled_frames": len(frames), "track_ids": ids["next_id"] - 1,
                                "links_ok": ids["ok"], "links_maybe": ids["maybe"], "new_tracks": ids["new"],
                                "midpoints": len(mids), "items": []}
        for m in mids:
            t = int(m["t_ms"])
            name = f"{v}_{t}ms.jpg"
            item = {"t_ms": t, "status": m["status"], "gap_ms": m["gap_ms"],
                    "boxes": len(m["boxes"]), "unmatched_tids": m.get("unmatched_tids", []), "file": name}
            if m["status"] == "excluded_long_gap":
                tot["excluded_long_gap"] += 1
                gaps_excluded.append({
                    "video": v, "from_ms": m["from"], "to_ms": m["to"], "gap_ms": m["gap_ms"],
                    "probe_max_conf": _lgmax.get((v, m["from"], m["to"])),
                    "reason": "IDSW 평가는 연속 구간만 필요. 구간 내 사람 존재 확인됨(검출기 기준, 미라벨)"})
            else:
                tot["interp_frames"] += 1
                tot["interp_boxes"] += len(m["boxes"])
                if m["status"] == "needs_review":
                    tot["needs_review"] += 1
            if a.write and vid.exists() and m["status"] != "excluded_long_gap":
                ok, why = extract_frame(vid, m["t_ms"], out_frames / name)
                item["extract"] = why
                tot["extracted" if ok else "extract_failed"] += 1
                if ok and m["status"] != "excluded_long_gap":
                    out_labels.mkdir(parents=True, exist_ok=True)
                    lines = [f"{b['cls']} {b['box'][0]:.6f} {b['box'][1]:.6f} "
                             f"{b['box'][2]:.6f} {b['box'][3]:.6f} {b['tid']}" for b in m["boxes"]]
                    # 스키마 확장분은 YOLO txt 형식을 깨지 않게 **사이드카 JSON** 으로 둔다.
                    (out_labels / f"{Path(name).stem}.json").write_text(json.dumps(
                        {"file": name, "video": v, "t_ms": t,
                         "video_role": "detector_only" if v in DETECTOR_ONLY_VIDEOS else "full",
                         "boxes": [{"cls": b["cls"], "box": b["box"], "track_id": b["tid"],
                                    "source": "interp", "parent_track_id": None,
                                    "link": b.get("link", "ok")} for b in m["boxes"]]},
                        ensure_ascii=False, indent=1), encoding="utf-8")
                    (out_labels / f"{Path(name).stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""),
                                                                      encoding="utf-8")
            vrep["items"].append(item)
            if m["status"] == "excluded_long_gap":
                continue                       # 제외 구간은 정답지 매니페스트에 넣지 않는다
            new_manifest.append({"video": v, "t_ms": t, "file": name, "status": m["status"],
                                 "video_role": "detector_only" if v in DETECTOR_ONLY_VIDEOS else "full",
                                 "gap_ms": m["gap_ms"], "boxes": len(m["boxes"]),
                                 "unmatched_tids": m.get("unmatched_tids", [])})
        tot["maybe_links"] += ids["maybe"]
        report["videos"][v] = vrep
        print(f"  {v[:34]:36} 라벨{len(frames):3}장 tid{ids['next_id']-1:3}개 "
              f"(확실{ids['ok']:3}/불확실{ids['maybe']:3}/신규{ids['new']:3}) "
              f"보간{sum(1 for m in mids if m['status']!='excluded_long_gap'):3} "
              f"검수필요{sum(1 for m in mids if m['status']=='needs_review'):2} "
              f"제외{sum(1 for m in mids if m['status']=='excluded_long_gap'):2}")

    report["totals"] = tot
    report["gaps_excluded"] = gaps_excluded
    print("\n" + "=" * 78)
    print(f"보간 대상 프레임 {tot['interp_frames']}장 · 보간 박스 {tot['interp_boxes']}개")
    print(f"★사람 검수 필요: {tot['needs_review']}장(등장·퇴장·가림) + 불확실 짝짓기 {tot['maybe_links']}건")
    print(f"★긴 간격 {tot['excluded_long_gap']}구간 — **이번 정답지에서 제외**(결정 2026-09-22). "
          f"구간 내 사람 존재는 확인됨 — audit/long_gaps_20260922.json")
    if a.write:
        print(f"프레임 추출: 성공 {tot['extracted']} · 실패 {tot['extract_failed']}")
        if tot["extract_failed"]:
            print("★실패가 있다 — 성공으로 보고하지 않는다(규칙 11)")
        rp = fe_repo / "frames_manifest_2fps_draft.json"
        rp.write_text(json.dumps({
            "schema": {"track_id": "int", "source": "human|interp|human_verified",
                       "parent_track_id": "int|null(지금은 비움)",
                       "video_role": "full|detector_only"},
            "detector_only_videos": sorted(DETECTOR_ONLY_VIDEOS),
            "gaps_excluded": gaps_excluded,
            "frames": new_manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
        (fe_repo / "interpolate_2fps_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"매니페스트: {rp}\n리포트: {fe_repo / 'interpolate_2fps_report.json'}")
    else:
        print("\n모의 실행이라 아무것도 쓰지 않았다. 실제로 만들려면 --write 를 준다.")
    return 1 if (a.write and tot["extract_failed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
