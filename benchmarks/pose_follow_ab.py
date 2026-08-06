"""pose_follow_ab.py — Phase 3 A/B: person을 BoxTracker anchor에 태울 때(구) vs 안 태울 때(신규).

배경: index_local.html의 BoxTracker(anchor:true)가 PPE 박스를 MediaPipe 머리/몸통
랜드마크(단일 인물 추정치)에 태워 30fps로 매끄럽게 만든다. 만약 person 도 이 anchor에
태우면(=단순히 excludeClass:'person' 만 제거), 다인 상황에서 anchor가 화면상 가장 큰
사람(=MediaPipe가 실제로 고정하는 대상과 유사한 '가장 눈에 띄는 사람')에게 쏠려 있다가
다른 사람으로 튈 때 그 사람이 아닌 박스까지 anchor 위치로 끌려간다.

이 스크립트는 실측 검출 캐시(benchmarks/_sweep_cache/multi_scene.json, 497프레임 IoU baseline)
를 사용해 anchor 신호를 만들고(각 프레임 '화면상 가장 큰 person 박스'의 중심 — MediaPipe가
고정하는 대상의 대리 신호, 실측 기반·조작 없음), 두 BoxTracker 설정을 실제로 실행해
person 표시 박스가 자기 자신의 실측 위치에서 얼마나 벗어나는지(px, 정규화)를 비교한다.

실행: python3 benchmarks/pose_follow_ab.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE = _ROOT / "benchmarks" / "_sweep_cache" / "multi_scene.json"
_DISPLAY_JS = _ROOT / "benchmarks" / "box_quality_display.js"
_NODE = r"C:\Program Files\nodejs\node.exe"
_OUT_MD = _ROOT / "benchmarks" / "pose_follow_ab.md"


def _load_cache() -> dict:
    return json.loads(_CACHE.read_text(encoding="utf-8"))


def _build_anchors(cache: dict) -> list[dict]:
    """프레임별 anchor = '화면상 가장 큰 person 박스'의 중심(실측 검출 기반).
    MediaPipe 가 실제로 어느 사람을 고정하는지는 이 저장소에 기록이 없어 대리 신호를 쓴다 —
    '가장 큰(=화면에서 가장 가까운/눈에 띄는) 사람'은 단일 인물 추정기가 흔히 고정하는 대상과
    같은 방향의 편향이라 방어 가능한 근사다(과장 없이 '대리 신호'로 명시)."""
    anchors = []
    for f in cache["frames"]:
        persons = [d for d in f["dets"] if d["cls"] == "person"]
        if not persons:
            anchors.append({"t_ms": f["t_cap_ms"], "ok": False})
            continue
        big = max(persons, key=lambda d: d["box"][2] * d["box"][3])
        x, y, w, h = big["box"]
        cx, cy = x + w / 2, y + h / 2
        sw = max(8.0, w * 0.35)  # 어깨폭 근사(스케일) — 박스폭의 일부로 근사
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


def _run(tracker_opts: dict, frames: list, anchors: list) -> list:
    cfg = {"render_fps": 60, "delay_ms": 0, "jitter_ms": 0, "seed": 1,
           "tracker_opts": tracker_opts, "frames": frames, "anchors": anchors}
    inp = _ROOT / "benchmarks" / "_pf_ab_input.json"
    inp.write_text(json.dumps(cfg), encoding="utf-8")
    r = subprocess.run([_NODE, str(_DISPLAY_JS), str(inp)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _gt_by_tid(cache: dict) -> dict:
    """tid -> [(t_ms, cx, cy), ...] 실측 검출 원본(정답)."""
    gt: dict[int, list] = {}
    for f in cache["frames"]:
        for d in f["dets"]:
            if d["cls"] != "person":
                continue
            x, y, w, h = d["box"]
            gt.setdefault(d["tid"], []).append((f["t_cap_ms"], x + w / 2, y + h / 2))
    return gt


def _nearest(series: list, t: float):
    if not series:
        return None
    best, bd = None, 1e18
    for (tt, cx, cy) in series:
        d = abs(tt - t)
        if d < bd:
            bd, best = d, (cx, cy)
    return best


def _freeze_pct(vis_frames: list) -> dict:
    """box_quality.py 와 동일 정의: 같은 tid가 연속 틱에서 박스가 byte-동일하면 '정지프레임'.
    person 클래스만 집계(다른 클래스는 이번 A/B와 무관)."""
    prev: dict[int, list] = {}
    num, den = 0, 0
    for fr in vis_frames:
        cur: dict[int, list] = {}
        for v in fr["vis"]:
            if v["cls"] != "person":
                continue
            cur[v["tid"]] = v["box"]
            if v["tid"] in prev:
                den += 1
                if all(abs(v["box"][k] - prev[v["tid"]][k]) < 1e-6 for k in range(4)):
                    num += 1
        prev = cur
    return {"freeze_pct": round(num / den * 100.0, 2) if den else None, "n": den}


def _score(vis_frames: list, gt: dict, diag: float) -> dict:
    """표시된 person 박스가 '자기 tid의 실측 위치'에서 얼마나 벗어나는지(정규화 오차, diag=대각선 기준)."""
    errs = []
    for fr in vis_frames:
        for v in fr["vis"]:
            if v["cls"] != "person" or v["tid"] is None or v["tid"] < 0:
                continue
            gtpos = _nearest(gt.get(v["tid"], []), fr["t_ms"])
            if gtpos is None:
                continue
            bx, by, bw, bh = v["box"]
            dcx, dcy = bx + bw / 2, by + bh / 2
            err = ((dcx - gtpos[0]) ** 2 + (dcy - gtpos[1]) ** 2) ** 0.5 / diag
            errs.append(err)
    if not errs:
        return {"n": 0, "mean": None, "p95": None, "max": None}
    errs.sort()
    return {"n": len(errs), "mean": round(sum(errs) / len(errs), 4),
            "p95": round(errs[int(len(errs) * 0.95)], 4), "max": round(errs[-1], 4)}


def main() -> None:
    cache = _load_cache()
    w, h = cache["frames"][0]["w"], cache["frames"][0]["h"]
    diag = (w * w + h * h) ** 0.5
    frames = _build_frames(cache)
    anchors = _build_anchors(cache)
    gt = _gt_by_tid(cache)

    old_vis = _run({"anchor": True}, frames, anchors)                          # 구: person 도 anchor(단순 제외 해제)
    new_vis = _run({"anchor": True, "noAnchorClass": "person"}, frames, anchors)  # 신규: person 은 anchor 금지

    old_score = _score(old_vis, gt, diag)
    new_score = _score(new_vis, gt, diag)
    old_freeze = _freeze_pct(old_vis)
    new_freeze = _freeze_pct(new_vis)

    lines = [
        "# Phase 3 A/B — person을 BoxTracker anchor에 태울 때(구) vs 금지(신규)",
        "",
        f"입력: `_sweep_cache/multi_scene.json`(497프레임 실측 IoU baseline, {w}x{h}).",
        "anchor 신호: 프레임별 '화면상 가장 큰 person 박스' 중심(실측 검출 기반 대리 신호 — MediaPipe 실측 아님, 명시).",
        "",
        "## 1) 다인 끌림 — 표시 박스가 '자기 tid 실측 위치'에서 벗어난 거리(대각선 정규화)",
        "| 설정 | n | 평균오차 | p95오차 | 최대오차 |",
        "|---|---|---|---|---|",
        f"| 구(anchor:true, person 포함) | {old_score['n']} | {old_score['mean']} | {old_score['p95']} | {old_score['max']} |",
        f"| 신규(noAnchorClass:'person') | {new_score['n']} | {new_score['mean']} | {new_score['p95']} | {new_score['max']} |",
        "",
        "## 2) 부드러움 회귀 — person 정지프레임%(연속 틱 박스 byte-동일 비율, box_quality.py와 동일 정의)",
        "| 설정 | n | 정지프레임% |",
        "|---|---|---|",
        f"| 구(anchor:true, person 포함) | {old_freeze['n']} | {old_freeze['freeze_pct']} |",
        f"| 신규(noAnchorClass:'person') | {new_freeze['n']} | {new_freeze['freeze_pct']} |",
        "",
    ]
    if old_score["mean"] is not None and new_score["mean"] is not None:
        improve = (old_score["mean"] - new_score["mean"]) / old_score["mean"] * 100 if old_score["mean"] else 0
        lines.append(f"**끌림 평균오차 개선: {improve:.1f}%** (구 대비, 신규가 낮을수록 자기 위치를 더 정확히 따라감)")
    _OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
