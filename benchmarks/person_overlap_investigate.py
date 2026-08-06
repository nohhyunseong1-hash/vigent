"""person_overlap_investigate.py — Phase 1: person 박스 2~3개 겹침 원인 조사(수정 없음).

배경: safety-local 에서 움직이는 person 박스가 2~3개(다른 색=다른 tid)로 겹쳐 뜬다는 보고.
직전 커밋(b653f6b)에서 person 을 MediaPipe pose-follow → BoxTracker(noAnchorClass:'person',
anchor:true)로 이관한 것의 부작용 여부를 실측으로 확인한다.

측정 데이터: benchmarks/_sweep_cache/multi_scene.json(497프레임, 실제 서버 guard.detect() 결과,
ByteTrack tid 포함) — 조작 없음, 실측 그대로 사용.

이 스크립트는 조사 전용이다. 소스 코드(vigent-box-display.js/index_local.html/realtime_core.js)는
일절 수정하지 않는다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE = _ROOT / "benchmarks" / "_sweep_cache" / "multi_scene.json"
_DISPLAY_JS = _ROOT / "benchmarks" / "box_quality_display.js"
_NODE = r"C:\Program Files\nodejs\node.exe"
_OUT_MD = _ROOT / "benchmarks" / "person_overlap_investigate.md"


def _iou(a: list, b: list) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    uni = a[2] * a[3] + b[2] * b[3] - inter
    return inter / uni if uni > 0 else 0.0


def _load_cache() -> dict:
    return json.loads(_CACHE.read_text(encoding="utf-8"))


def _build_anchors(cache: dict) -> list[dict]:
    """pose_follow_ab.py 와 동일한 대리 anchor 신호(화면상 가장 큰 person 중심) — 실측 검출 기반."""
    anchors = []
    for f in cache["frames"]:
        persons = [d for d in f["dets"] if d["cls"] == "person"]
        if not persons:
            anchors.append({"t_ms": f["t_cap_ms"], "ok": False})
            continue
        big = max(persons, key=lambda d: d["box"][2] * d["box"][3])
        x, y, w, h = big["box"]
        cx, cy = x + w / 2, y + h / 2
        sw = max(8.0, w * 0.35)
        anchors.append({
            "t_ms": f["t_cap_ms"], "ok": True, "scale": sw,
            "head": [cx, y + h * 0.15], "torso": [cx, cy],
        })
    return anchors


def _build_frames(cache: dict) -> list[dict]:
    out = []
    for f in cache["frames"]:
        dets = [{"cls": d["cls"], "score": d["score"], "id": d["tid"], "box": d["box"]} for d in f["dets"]]
        out.append({"t_cap_ms": f["t_cap_ms"], "dets": dets})
    return out


def _run(tracker_opts: dict, frames: list, anchors: list | None) -> list:
    cfg = {"render_fps": 60, "delay_ms": 0, "jitter_ms": 0, "seed": 1,
           "tracker_opts": tracker_opts, "frames": frames}
    if anchors is not None:
        cfg["anchors"] = anchors
    inp = _ROOT / "benchmarks" / "_po_investigate_input.json"
    inp.write_text(json.dumps(cfg), encoding="utf-8")
    r = subprocess.run([_NODE, str(_DISPLAY_JS), str(inp)], capture_output=True, text=True, check=True)
    inp.unlink(missing_ok=True)
    return json.loads(r.stdout)


def _raw_overlap_stats(cache: dict) -> dict:
    """A 후보: 서버가 이미 같은 프레임에 겹치는(다른 tid) person 박스를 내는지."""
    multi = 0
    ov010 = 0
    ov040 = 0
    for f in cache["frames"]:
        persons = [d for d in f["dets"] if d["cls"] == "person"]
        if len(persons) < 2:
            continue
        multi += 1
        h10 = h40 = False
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                if persons[i]["tid"] == persons[j]["tid"]:
                    continue
                v = _iou(persons[i]["box"], persons[j]["box"])
                if v > 0.10:
                    h10 = True
                if v > 0.40:
                    h40 = True
        if h10:
            ov010 += 1
        if h40:
            ov040 += 1
    n = len(cache["frames"])
    return {"n_frames": n, "multi_person_frames": multi,
            "overlap010_frames": ov010, "overlap010_pct": round(ov010 / n * 100, 1),
            "overlap040_frames": ov040, "overlap040_pct": round(ov040 / n * 100, 1)}


def _fragmentation_birth_stats(cache: dict) -> dict:
    """A 후보: 신규 tid 탄생이 최근(6프레임=250ms@24fps) 인접 tid 박스와 공간적으로 겹치는 비율."""
    last_seen: dict[int, dict] = {}
    births = 0
    frag = 0
    for fi, f in enumerate(cache["frames"]):
        persons = [d for d in f["dets"] if d["cls"] == "person"]
        for d in persons:
            if d["tid"] not in last_seen:
                births += 1
                near = False
                for otid, info in last_seen.items():
                    if otid == d["tid"] or fi - info["fi"] > 6:
                        continue
                    if _iou(d["box"], info["box"]) > 0.15:
                        near = True
                        break
                if near:
                    frag += 1
        for d in persons:
            last_seen[d["tid"]] = {"fi": fi, "box": d["box"]}
    return {"births": births, "frag_births": frag,
            "frag_pct": round(frag / births * 100, 1) if births else None}


def _output_overlap_stats(vis_frames: list) -> dict:
    """B/C 검증: 실제 BoxTracker(프로덕션 설정) 출력에서 person 겹침이 남아있는지 + 잔존 쌍의 IoU 분포."""
    n = len(vis_frames)
    ov_frames = 0
    neg_tid = 0
    pair_ious = []
    for fr in vis_frames:
        persons = [v for v in fr["vis"] if v["cls"] == "person"]
        for p in persons:
            if p["tid"] is None or p["tid"] < 0:
                neg_tid += 1
        has_ov = False
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                if persons[i]["tid"] == persons[j]["tid"]:
                    continue
                v = _iou(persons[i]["box"], persons[j]["box"])
                if v > 0.10:
                    has_ov = True
                    pair_ious.append(v)
        if has_ov:
            ov_frames += 1
    pair_ious.sort()
    return {
        "n_ticks": n, "overlap_ticks": ov_frames, "overlap_pct": round(ov_frames / n * 100, 1) if n else None,
        "neg_tid_person_entries": neg_tid,
        "overlap_pair_n": len(pair_ious),
        "overlap_pair_iou_mean": round(sum(pair_ious) / len(pair_ious), 3) if pair_ious else None,
        "overlap_pair_iou_over040": sum(1 for v in pair_ious if v >= 0.40),
    }


def main() -> None:
    cache = _load_cache()
    frames = _build_frames(cache)
    anchors = _build_anchors(cache)

    raw = _raw_overlap_stats(cache)
    frag = _fragmentation_birth_stats(cache)

    # 프로덕션 설정 그대로 재생(현재 배포 상태를 그대로 재현)
    prod_vis = _run({"anchor": True, "noAnchorClass": "person"}, frames, anchors)
    prod_out = _output_overlap_stats(prod_vis)

    # anchor 영향 분리용 대조군(참고): anchor 없이 순수 id매칭+One-Euro+dedup만
    noanchor_vis = _run({"anchor": False}, frames, None)
    noanchor_out = _output_overlap_stats(noanchor_vis)

    lines = [
        "# Phase 1 조사 — person 박스 겹침 원인 (수정 없음)",
        "",
        "입력: `_sweep_cache/multi_scene.json`(497프레임 실측, ByteTrack tid 포함).",
        "",
        "## A) 서버 원본(raw) — 같은 프레임에 다른 tid person 박스가 이미 겹치는가",
        f"- 멀티person 프레임: {raw['multi_person_frames']}/{raw['n_frames']}",
        f"- IoU>0.10 겹침 프레임: {raw['overlap010_frames']} ({raw['overlap010_pct']}%)",
        f"- IoU>0.40 겹침 프레임: {raw['overlap040_frames']} ({raw['overlap040_pct']}%)",
        "",
        "## A) 신규 tid 탄생이 파편화(최근 6프레임 내 인접 tid와 공간중첩)로 보이는 비율",
        f"- 신규 tid 탄생 수: {frag['births']}",
        f"- 이 중 공간중첩(IoU>0.15): {frag['frag_births']} ({frag['frag_pct']}%)",
        "",
        "## B/C) 클라 표시단(BoxTracker, 프로덕션 설정 anchor:true+noAnchorClass:'person') 출력 겹침",
        f"- 렌더틱: {prod_out['n_ticks']}, 겹침틱(IoU>0.10): {prod_out['overlap_ticks']} ({prod_out['overlap_pct']}%)",
        f"- 겹친 쌍 수: {prod_out['overlap_pair_n']}, 평균IoU: {prod_out['overlap_pair_iou_mean']}, "
        f"이 중 IoU≥0.40(=dedup 임계 이상인데도 안 잡힘): {prod_out['overlap_pair_iou_over040']}",
        f"- tid<0(fallback) person 표시 항목 수: {prod_out['neg_tid_person_entries']} (0이면 C=페이드잔존 구조적으로 불가)",
        "",
        "## 참고: anchor 끄면(순수 id매칭+One-Euro+dedup만) 겹침이 달라지는가",
        f"- 렌더틱: {noanchor_out['n_ticks']}, 겹침틱(IoU>0.10): {noanchor_out['overlap_ticks']} ({noanchor_out['overlap_pct']}%)",
        f"- 겹친 쌍 평균IoU: {noanchor_out['overlap_pair_iou_mean']}, IoU≥0.40: {noanchor_out['overlap_pair_iou_over040']}",
        "",
    ]
    _OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
