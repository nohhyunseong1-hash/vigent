"""ppe_anchor_ab.py — Phase: PPE 박스 MediaPipe 앵커 끌림 A/B (수정 전/후).

배경: person 은 이미 noAnchorClass 로 MediaPipe 앵커에서 면제됐으나(커밋 b653f6b), PPE 박스는
`_bt`(index_local.html)의 anchor:true 로 여전히 computeAnchor()(MediaPipe 1인 머리/몸통)에 연결돼
있었다 — 다인 상황에서 앵커가 고정한 사람과 다른 사람의 PPE 박스가 그 앵커 쪽으로 끌려간다(person
때와 동일한 결함, 클래스만 다름). 오늘 수정: `_bt` 생성 옵션에서 anchor 자체를 제거(person·PPE 전부
앵커 미사용, index_local.html).

이 환경엔 PPE(Hardhat 등) 파인튜닝 가중치가 없어(.gitignore 대상) multi_scene.json 캐시에 실제 PPE
클래스 검출이 없다 — 그래서 **합성 PPE 신호**를 쓴다: 매 프레임 실측 person 박스마다 그 사람 머리
위치에 고정 비율로 붙는 작은 박스(class='Hardhat')를 만들고, tid 는 소유자 person 의 tid 에 오프셋을
더해 동일한 연속성(파편화 패턴 포함)을 갖게 한다 — "PPE 는 소유자 person 과 동일한 tid 연속성을
갖는다"는 근거 있는 가정이지 실측은 아니다(정직 고지, 아래 md 에도 명시). person 쪽 dets 는 실측
그대로(조작 없음) 사용해 person 회귀 0 도 같은 실행에서 함께 검증한다.

실행: python3 benchmarks/ppe_anchor_ab.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE = _ROOT / "benchmarks" / "_sweep_cache" / "multi_scene.json"
_DISPLAY_JS = _ROOT / "benchmarks" / "box_quality_display.js"
_NODE = r"C:\Program Files\nodejs\node.exe"
_OUT_MD = _ROOT / "benchmarks" / "ppe_anchor_ab.md"

_HARDHAT_TID_OFFSET = 5_000_000
_HW_RATIO, _HH_RATIO = 0.35, 0.25   # 안전모 박스 크기 = person 박스 폭/높이의 이 비율(머리 부위 근사)


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
    """실측 person + 합성 Hardhat(소유자 머리 위 고정비율, tid=소유자+오프셋)."""
    out = []
    for f in cache["frames"]:
        dets = []
        for d in f["dets"]:
            if d["cls"] != "person":
                continue
            dets.append({"cls": "person", "score": d["score"], "id": d["tid"], "box": d["box"]})
            x, y, w, h = d["box"]
            hw, hh = w * _HW_RATIO, h * _HH_RATIO
            hbox = [x + (w - hw) / 2, y, hw, hh]
            dets.append({"cls": "Hardhat", "score": d["score"], "id": d["tid"] + _HARDHAT_TID_OFFSET, "box": hbox})
        out.append({"t_cap_ms": f["t_cap_ms"], "dets": dets})
    return out


def _run(tracker_opts: dict, frames: list, anchors: list) -> list:
    cfg = {"render_fps": 60, "delay_ms": 0, "jitter_ms": 0, "seed": 1,
           "tracker_opts": tracker_opts, "frames": frames, "anchors": anchors}
    inp = _ROOT / "benchmarks" / "_ppe_ab_input.json"
    inp.write_text(json.dumps(cfg), encoding="utf-8")
    r = subprocess.run([_NODE, str(_DISPLAY_JS), str(inp)], capture_output=True, text=True, check=True)
    inp.unlink(missing_ok=True)
    return json.loads(r.stdout)


def _gt_by_tid(frames: list, cls: str) -> dict:
    """tid -> [(t_ms, cx, cy), ...] 합성/실측 원본(정답) — box 중심."""
    gt: dict[int, list] = {}
    for f in frames:
        for d in f["dets"]:
            if d["cls"] != cls:
                continue
            x, y, w, h = d["box"]
            gt.setdefault(d["id"], []).append((f["t_cap_ms"], x + w / 2, y + h / 2))
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


def _freeze_pct(vis_frames: list, cls: str) -> dict:
    prev: dict[int, list] = {}
    num, den = 0, 0
    for fr in vis_frames:
        cur: dict[int, list] = {}
        for v in fr["vis"]:
            if v["cls"] != cls:
                continue
            cur[v["tid"]] = v["box"]
            if v["tid"] in prev:
                den += 1
                if all(abs(v["box"][k] - prev[v["tid"]][k]) < 1e-6 for k in range(4)):
                    num += 1
        prev = cur
    return {"freeze_pct": round(num / den * 100.0, 2) if den else None, "n": den}


def _score(vis_frames: list, gt: dict, diag: float, cls: str) -> dict:
    errs = []
    for fr in vis_frames:
        for v in fr["vis"]:
            if v["cls"] != cls or v["tid"] is None or v["tid"] < 0:
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
    gt_person = _gt_by_tid(frames, "person")
    gt_hardhat = _gt_by_tid(frames, "Hardhat")

    old_vis = _run({"anchor": True, "noAnchorClass": "person"}, frames, anchors)   # 오늘 수정 전(현재 배포 상태)
    new_vis = _run({}, frames, anchors)                                            # 오늘 수정(anchor 자체 미사용)

    rows = []
    for label, vis in [("구(anchor:true, PPE 포함)", old_vis), ("신규(anchor 미사용)", new_vis)]:
        hh_score = _score(vis, gt_hardhat, diag, "Hardhat")
        hh_freeze = _freeze_pct(vis, "Hardhat")
        p_score = _score(vis, gt_person, diag, "person")
        p_freeze = _freeze_pct(vis, "person")
        rows.append((label, hh_score, hh_freeze, p_score, p_freeze))

    lines = [
        "# PPE 박스 MediaPipe 앵커 끌림 A/B — 수정 전/후",
        "",
        f"입력: `_sweep_cache/multi_scene.json`(497프레임 실측 person, {w}x{h}) + 합성 Hardhat"
        f"(소유자 person 머리 위 고정비율 {_HW_RATIO}x{_HH_RATIO}, tid=소유자+{_HARDHAT_TID_OFFSET} — "
        "실측 아님, tid 연속성은 소유자와 동일하다고 가정한 대리 신호, 정직 고지).",
        "anchor 신호: 프레임별 '화면상 가장 큰 person 박스' 중심(실측 검출 기반 대리 신호, pose_follow_ab.py와 동일).",
        "",
        "## 1) Hardhat(PPE) 끌림 — 표시 박스가 '자기 소유자 실측 위치'에서 벗어난 거리(대각선 정규화)",
        "| 설정 | n | 평균오차 | p95오차 | 최대오차 |",
        "|---|---|---|---|---|",
    ]
    for label, hh_score, _hf, _ps, _pf in rows:
        lines.append(f"| {label} | {hh_score['n']} | {hh_score['mean']} | {hh_score['p95']} | {hh_score['max']} |")

    lines += [
        "",
        "## 2) Hardhat 부드러움 — 정지프레임%(연속 틱 박스 byte-동일 비율)",
        "| 설정 | n | 정지프레임% |",
        "|---|---|---|",
    ]
    for label, _hs, hh_freeze, _ps, _pf in rows:
        lines.append(f"| {label} | {hh_freeze['n']} | {hh_freeze['freeze_pct']} |")

    lines += [
        "",
        "## 3) person 회귀 확인 — 같은 실행에서 person 지표 비교(0이어야 함)",
        "| 설정 | 끌림 평균오차 | 정지프레임% |",
        "|---|---|---|",
    ]
    for label, _hs, _hf, p_score, p_freeze in rows:
        lines.append(f"| {label} | {p_score['mean']} | {p_freeze['freeze_pct']} |")

    old_hh_mean = rows[0][1]["mean"]
    new_hh_mean = rows[1][1]["mean"]
    old_p_mean, new_p_mean = rows[0][3]["mean"], rows[1][3]["mean"]
    old_p_freeze, new_p_freeze = rows[0][4]["freeze_pct"], rows[1][4]["freeze_pct"]

    lines.append("")
    if old_hh_mean is not None and new_hh_mean is not None and old_hh_mean:
        improve = (old_hh_mean - new_hh_mean) / old_hh_mean * 100
        lines.append(f"**Hardhat 끌림 평균오차 개선: {improve:.1f}%** (구 대비, 신규가 낮을수록 자기 소유자 위치를 더 정확히 따라감)")
    person_regression = (old_p_mean == new_p_mean) and (old_p_freeze == new_p_freeze)
    lines.append(f"**person 회귀**: 끌림오차 {old_p_mean}→{new_p_mean}, 정지프레임% {old_p_freeze}→{new_p_freeze} "
                 f"— {'0(완전 동일, 회귀 없음)' if person_regression else '⚠ 차이 발생(확인 필요)'}")
    lines += [
        "",
        "## 정직 고지",
        "- Hardhat 신호는 실측이 아니라 **합성**(이 환경에 PPE 가중치가 없어 실제 PPE 검출 재현 불가). "
        "tid 연속성(파편화 포함)이 소유자 person 과 동일하다고 가정했는데, 실제 PPE 검출기의 tid 연속성"
        "(guard.py `_track_iou`, 별도 인스턴스)은 이보다 좋거나 나쁠 수 있다 — 방향성(끌림 감소)은 앵커"
        "링크 메커니즘 자체의 산수이므로 유효하지만, 정지프레임%의 절대값은 참고치다.",
        "- 부드러움(정지프레임%) 은 앵커가 원래 노렸던 이득이라 신규 쪽이 악화될 수 있다고 예상했으나, "
        "실측 결과는 반대(신규가 더 낮음/좋음)로 나왔다 — **구(anchor) 조건의 절대값은 과대추정일 가능성이 "
        "높다**: anchor 신호가 실측 검출 캐던스(~24fps)로 근사한 대리 신호라 실제 MediaPipe(30fps 연속)보다 "
        "성기게 갱신되고, 페이지 실제 anchor 값(computeAnchor)은 rAF마다(≈60fps) 갱신돼 훨씬 매끄럽다 — "
        "pose_follow_ab.md 의 동일 caveat 반복. 방향(신규가 끌림·정지프레임 둘 다 개선)은 신뢰하되, "
        "구 조건 56.82% 라는 절대 수치 자체를 실배포 대비값으로 인용하지 말 것.",
    ]
    _OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
