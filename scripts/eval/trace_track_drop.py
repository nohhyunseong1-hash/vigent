#!/usr/bin/env python3
"""scripts/eval/trace_track_drop.py — 검출기가 본 사람이 파이프라인 **어디서** 버려지는지 건별 계측(0-D).

배경(0-B, 2026-09-22): dev person FN 91건 중 **72건(79.1%)** 은 검출 단계에서 어떤 형태로든 보였고,
  그중 46건은 conf>=0.40·위치까지 맞았다(41건이 IoU>=0.5). "못 보는 것"이 아니라 "보고도 버리는 것"이다.
  이 스크립트는 그 46건이 **어느 지점에서** 사라지는지 프레임 단위로 추적해 분류한다.

★운영 코드는 한 줄도 고치지 않는다(규칙 6). 전부 래퍼·훅이며 끝나면 원복한다.
★판정하지 않는다. 표만 만든다(규칙 7).

분류(지시받은 정의):
  (a) 첫 프레임 드롭  — 영상의 첫 GT 프레임에서 추적기가 전부 버림
  (b) 미확정 트랙     — 새 트랙이 생성됐으나 tracker_id=-1 이라 출력에서 제외
  (c) 매칭 실패       — 기존 트랙이 있었으나 칼만 예측 박스와 IoU < 임계로 연결 실패
                        (예측 박스 IoU·이동량 함께 기록)
  (d) 트랙 소멸       — maximum_frames_without_update 초과로 제거된 직후
  (e) 추적기 이후 필터 — _merge_cross_source_person 등 후처리에서 제거
  (f) 기타

★라이브러리 사실(trackers ByteTrackTracker, 코드 확인 2026-09-22):
  · `_spawn_new_tracks` 는 새 트랙에 **항상 tracker_id=-1** 을 넣는다. minimum_consecutive_frames=1
    이어도 그 프레임에서는 tid 를 못 받는다 → guard `if tid < 0: continue` 로 버려진다.
  · 스폰 후보는 `unmatched_high`(conf >= high_conf_det_threshold=BYTETRACK_HIGH_CONF 0.50)뿐이다.
    즉 **실질 스폰 하한은 activation(0.40)이 아니라 0.50** 이다.
  · maximum_frames_without_update = int(frame_rate/30 * lost_track_buffer) = int(10/30*30) = 10.

재현:
    python scripts/eval/trace_track_drop.py --json audit/track_drop_<날짜>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# [2026-10-08 새 환경 점검] cp949 콘솔(PYTHONUTF8 미설정 Windows)에서 한글·기호 print 가 UnicodeEncodeError 로 죽던 것 —
#   실측: setup_env.py 가 새 clone 의 첫 print 에서 종료돼 pip 설치가 시작도 안 됐다. stdout/stderr 를 UTF-8 로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

SAME_BOX_IOU = 0.70     # 0-D-1: 기본 추론 박스와 "동일 박스" 판정
GT_IOU = 0.50           # FN 판정과 동일
HI_BAND = 0.40          # 고신뢰 대역 하한(0-D-2 대상)
LO_BAND = 0.10          # 저신뢰 대역 하한(0-D-3 대상)


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


class Trace:
    """한 번의 detect 호출에서 추적 전/후와 ByteTrack 내부를 기록한다."""

    def __init__(self) -> None:
        self.pre: list[dict] = []          # _track 입력 person
        self.post: list[dict] = []         # _track 출력 person
        self.final: list[dict] = []        # detect 최종 반환 person
        self.bt_in: list[dict] = []        # ByteTrack 입력(박스·conf)
        self.bt_out: list[dict] = []       # ByteTrack 출력(박스·tid)
        self.tracks_before: list[dict] = []   # update 직전 트랙(예측 전 박스·tid·미갱신프레임)
        self.pred_boxes: list[dict] = []      # predict() 직후 예측 박스(매칭에 실제로 쓰인 것)
        self.n_tracks_after = 0


def install_hooks(store: dict[str, Trace]) -> tuple[Any, ...]:
    """운영 코드 무수정 — 래퍼만 설치한다. 반환값으로 원복한다."""
    import agents.guard as GM
    from trackers import ByteTrackTracker as BT
    from trackers.core.bytetrack.tracker import ByteTrackTracklet as TL

    orig_track = GM.GuardAgent._track
    orig_update = BT.update
    orig_predict = TL.predict
    cur: dict[str, Trace | None] = {"t": None}

    def track_wrap(self, fresh, track_key):
        t = cur["t"]
        if t is not None:
            t.pre = [dict(d) for d in fresh if str(d.get("label", "")).lower() == "person"]
        out = orig_track(self, fresh, track_key)
        if t is not None:
            t.post = [dict(d) for d in out if str(d.get("label", "")).lower() == "person"]
        return out

    def update_wrap(self, detections, frame=None):
        t = cur["t"]
        if t is not None:
            t.tracks_before = [{"tid": int(getattr(tr, "tracker_id", -1)),
                                "bbox": [float(v) for v in tr.get_state_bbox()],
                                "since_update": int(getattr(tr, "time_since_update", 0)),
                                "consec": int(getattr(tr, "number_of_successful_consecutive_updates", 0))}
                               for tr in self.tracks]
            t.bt_in = [{"bbox": [float(v) for v in detections.xyxy[i]],
                        "conf": float(detections.confidence[i]) if detections.confidence is not None else 0.0}
                       for i in range(len(detections))]
            t.pred_boxes = []
        res = orig_update(self, detections, frame)
        if t is not None:
            t.bt_out = [{"bbox": [float(v) for v in res.xyxy[i]], "tid": int(res.tracker_id[i])}
                        for i in range(len(res))]
            t.n_tracks_after = len(self.tracks)
        return res

    def predict_wrap(self):
        box = orig_predict(self)
        t = cur["t"]
        if t is not None:
            t.pred_boxes.append({"tid": int(getattr(self, "tracker_id", -1)),
                                 "bbox": [float(v) for v in box]})
        return box

    GM.GuardAgent._track = track_wrap
    BT.update = update_wrap
    TL.predict = predict_wrap
    return (GM, BT, TL, orig_track, orig_update, orig_predict, cur)


def classify(t: Trace, gt_box: list[float], is_first_frame: bool) -> dict[str, Any]:
    """FN 한 건이 어디서 버려졌는지 분류한다."""
    # 검출 단계에서 이 GT 를 맞춘 박스(추적 전)
    pre_hit = max(((_iou(d.get("bbox") or [0] * 4, gt_box), d) for d in t.pre),
                  key=lambda x: x[0], default=(0.0, None))
    if pre_hit[0] < GT_IOU or pre_hit[1] is None:
        return {"class": "(f) 기타", "why": "추적 전에도 IoU>=0.5 박스 없음(기본 임계 추론 기준)"}
    box = pre_hit[1].get("bbox") or [0] * 4
    conf = float(pre_hit[1].get("conf", 0.0))

    # 추적 출력에 살아남았는가
    post_hit = max((_iou(d.get("bbox") or [0] * 4, box) for d in t.post), default=0.0)
    if post_hit >= SAME_BOX_IOU:
        final_hit = max((_iou(d.get("bbox") or [0] * 4, box) for d in t.final), default=0.0)
        if final_hit >= SAME_BOX_IOU:
            return {"class": "(f) 기타", "why": "최종 출력에 있음 — FN 판정과 불일치(확인 필요)"}
        return {"class": "(e) 추적기 이후 필터", "why": "_merge_cross_source_person 등 후처리에서 제거",
                "conf": conf}

    # ByteTrack 출력에서 이 박스의 tid 확인
    bt_hit = max(((_iou(d["bbox"], box), d) for d in t.bt_out), key=lambda x: x[0], default=(0.0, None))
    tid = int(bt_hit[1]["tid"]) if bt_hit[1] and bt_hit[0] >= SAME_BOX_IOU else None

    live_tracks = [tr for tr in t.tracks_before if tr["tid"] >= 0]
    if tid is not None and tid < 0:
        # 트랙은 생겼으나 tid 미부여 = 신규 스폰(-1) 또는 low 미매칭(-1)
        if not t.tracks_before:
            return {"class": "(a) 첫 프레임 드롭" if is_first_frame else "(b) 미확정 트랙",
                    "why": "update 직전 트랙 0개 — 신규 스폰은 항상 tid=-1", "conf": conf}
        # 기존 트랙이 있었는데도 붙지 못했다 → 예측 박스와의 IoU 를 본다
        best = max(((_iou(p["bbox"], box), p) for p in t.pred_boxes), key=lambda x: x[0], default=(0.0, None))
        prev = next((tr for tr in t.tracks_before if best[1] and tr["tid"] == best[1]["tid"]), None)
        move = _iou(prev["bbox"], best[1]["bbox"]) if (prev and best[1]) else None
        if conf >= HI_BAND and best[0] > 0:
            return {"class": "(c) 매칭 실패", "why": "기존 트랙 있음·예측 박스와 연결 실패",
                    "conf": conf, "pred_iou": round(best[0], 3),
                    "pred_vs_prev_iou": round(move, 3) if move is not None else None,
                    "n_tracks_before": len(t.tracks_before), "n_live_tid": len(live_tracks)}
        return {"class": "(b) 미확정 트랙", "why": "신규 스폰(tid=-1) — 겹치는 기존 트랙 없음",
                "conf": conf, "n_tracks_before": len(t.tracks_before)}
    if tid is None:
        return {"class": "(d) 트랙 소멸" if t.tracks_before and not live_tracks else "(f) 기타",
                "why": "ByteTrack 출력에 해당 박스 없음", "conf": conf,
                "n_tracks_before": len(t.tracks_before)}
    return {"class": "(f) 기타", "why": f"tid={tid} 인데 추적 출력에 없음", "conf": conf}


def main() -> int:
    ap = argparse.ArgumentParser(description="고신뢰 FN 의 파이프라인 탈락 경로 계측(0-D)")
    ap.add_argument("--fn-json", default="audit/fn_origin_20260922.json", help="0-B 결과")
    ap.add_argument("--json", default="", help="결과 저장 경로")
    a = ap.parse_args()

    import cv2
    import vision_loader
    from agents.guard import GuardAgent
    from analyze_fn_origin import load_gt
    from data_paths import media

    fn_res = json.loads(Path(a.fn_json).read_text(encoding="utf-8"))["b"]
    items = fn_res["items"]
    manifest, gt, _names = load_gt()
    frames_dir = media("field_eval") / "frames"
    t_of = {r["file"]: r["t_ms"] for r in manifest}
    vid_of = {r["file"]: r["video"] for r in manifest}

    # 0-B 에서 쓴 dev 프레임을 영상별 시간순으로 (FN 재생성과 동일 순서여야 상태가 같다)
    split = json.loads((_ROOT / "data" / "field_eval" / "dev_test_split.json").read_text(encoding="utf-8"))
    devset = set(split["dev"])
    byv: dict[str, list[str]] = {}
    for r in manifest:
        if r["file"] in devset:
            byv.setdefault(r["video"], []).append(r["file"])
    for v in byv:
        byv[v].sort(key=lambda f: t_of[f])
    first_frame = {v: fns[0] for v, fns in byv.items()}

    # ── 0-D-1: 기본 임계 추론에서도 같은 박스가 나오는가 ────────────────────────────
    hi = [it for it in items if (it.get("max_conf") or 0) >= HI_BAND]
    lo = [it for it in items if LO_BAND <= (it.get("max_conf") or 0) < HI_BAND]
    print(f"0-B 결과: FN {len(items)}건 · 고신뢰(>={HI_BAND}) {len(hi)}건 · 저신뢰({LO_BAND}~{HI_BAND}) {len(lo)}건\n")

    store: dict[str, Trace] = {}
    hooks = install_hooks(store)
    GM, BT, TL, o_track, o_update, o_predict, cur = hooks
    try:
        guard = GuardAgent(vision_loader.load_vision("safety"))
        traces: dict[str, Trace] = {}
        for vid, fns in byv.items():
            for fn in fns:
                img = cv2.imread(str(frames_dir / fn))
                if img is None:
                    continue
                t = Trace()
                cur["t"] = t
                out = guard.detect(img, detectors=["person", "ppe"], track_key=f"trace:{vid}")
                t.final = [dict(d) for d in out.get("detections", [])
                           if str(d.get("label", "")).lower() == "person"]
                cur["t"] = None
                traces[fn] = t
    finally:
        GM.GuardAgent._track = o_track
        BT.update = o_update
        TL.predict = o_predict
    print(f"운영 동작 원복 확인: _track={GM.GuardAgent._track is o_track} "
          f"update={BT.update is o_update} predict={TL.predict is o_predict}\n")

    # 0-D-1 집계 — 저신뢰 재추론 박스가 기본 추론에도 있는가
    d1 = {"동일 박스": 0, "다른 박스": 0}
    for it in hi:
        t = traces.get(it["file"])
        gtb = it["bbox"]
        ok = t is not None and max(((_iou(d.get("bbox") or [0] * 4, gtb)) for d in t.pre), default=0.0) >= GT_IOU
        d1["동일 박스" if ok else "다른 박스"] += 1
        it["_same_box"] = ok
    print(f"[0-D-1] 고신뢰 {len(hi)}건 중 기본 임계 추론에도 나온 것(IoU>={GT_IOU} 기준): "
          f"동일 {d1['동일 박스']} · 아님 {d1['다른 박스']}")

    # ── 0-D-2: 탈락 경로 분류(동일 박스 확인분만) ──────────────────────────────────
    rows2 = []
    for it in hi:
        if not it.get("_same_box"):
            continue
        t = traces[it["file"]]
        r = classify(t, it["bbox"], is_first_frame=(it["file"] == first_frame.get(vid_of[it["file"]])))
        r.update({"file": it["file"], "t_ms": t_of[it["file"]]})
        rows2.append(r)
    c2 = Counter(r["class"] for r in rows2)
    print(f"\n[0-D-2] 고신뢰 동일박스 {len(rows2)}건 탈락 경로")
    for k, n in sorted(c2.items()):
        print(f"   {k:22} {n:3}건 ({n/max(1,len(rows2))*100:5.1f}%)")
    ab = c2.get("(a) 첫 프레임 드롭", 0) + c2.get("(b) 미확정 트랙", 0)
    cc = c2.get("(c) 매칭 실패", 0)
    print(f"   ── (a)+(b) 출력 지연 문제 {ab}건 · (c) 연결 문제 {cc}건")
    print(f"   ※(a) {c2.get('(a) 첫 프레임 드롭', 0)}건 vs 영상 수 {len(byv)}개")
    pred_ious = [r["pred_iou"] for r in rows2 if r.get("pred_iou") is not None]
    if pred_ious:
        s = sorted(pred_ious)
        print(f"   ※(c) 예측 박스 IoU: 중앙값 {s[len(s)//2]:.3f} · 최소 {s[0]:.3f} · 최대 {s[-1]:.3f}")

    # ── 0-D-3: 저신뢰 대역 ─────────────────────────────────────────────────────────
    rows3 = []
    for it in lo:
        t = traces.get(it["file"])
        if t is None:
            continue
        if max(((_iou(d.get("bbox") or [0] * 4, it["bbox"])) for d in t.pre), default=0.0) < GT_IOU:
            rows3.append({"file": it["file"], "class": "트랙 없음", "why": "기본 임계 추론에 박스 없음"})
            continue
        if not [tr for tr in t.tracks_before if tr["tid"] >= 0]:
            rows3.append({"file": it["file"], "class": "트랙 없음", "why": "update 직전 살아있는 트랙 0개"})
            continue
        r = classify(t, it["bbox"], is_first_frame=(it["file"] == first_frame.get(vid_of[it["file"]])))
        r["file"] = it["file"]
        rows3.append(r)
    c3 = Counter(r["class"] for r in rows3)
    print(f"\n[0-D-3] 저신뢰({LO_BAND}~{HI_BAND}) {len(rows3)}건")
    for k, n in sorted(c3.items()):
        print(f"   {k:22} {n:3}건")

    if ab and len(rows2) and ab > len(rows2) / 2:
        print(f"\n★(a)+(b) 가 {ab}/{len(rows2)} 로 과반이다.")
    print("\n※이 표는 판정이 아니다 — 분기 결정은 사람이 한다(규칙 7).")

    if a.json:
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"d1": d1, "d2": rows2, "d3": rows3,
                                 "params": {"SAME_BOX_IOU": SAME_BOX_IOU, "GT_IOU": GT_IOU,
                                            "HI_BAND": HI_BAND, "LO_BAND": LO_BAND}},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
