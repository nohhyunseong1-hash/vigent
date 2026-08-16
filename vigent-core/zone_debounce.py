"""zone_debounce.py — [B6] 위험구역 침입 판정 디바운스(시간 기반).

배경(audit/site_readiness_2026-08-16.md 🔴B6): PPE(3프레임)·화재(2프레임)에는 히스테리시스가
있는데(`GuardAgent.HYSTERESIS_FRAMES`) **위험구역 침입에는 없었다**. 검출 1건이 곧 경보라
단일 프레임 오검출이 그대로 경보가 됐다. 파일럿의 **유일한 판매 기능**이 이것인데 말이다.

프레임 수가 아니라 **시간(T초)** 기준으로 만든 이유: 검출 캐던스가 고정이 아니다.
실측 2.3fps(평시) ~ 5fps(확대뷰 focus)로 변하므로 "연속 3프레임"이 어떤 때는 1.3초,
어떤 때는 0.6초가 된다 — 안전 판정의 기준이 화면 조작에 따라 흔들리면 안 된다.
(백로그 PN 저프레임률 항목과 같은 문제의식.)

동작:
  - 밖→안: raw 가 `enter_s`(기본 1.0초) 연속 유지돼야 침입 확정
  - 안→밖: raw 가 `exit_s`(기본 1.0초) 연속 유지돼야 이탈 확정
  - 경계에서 왔다갔다 하면 exit 유예 덕에 확정 상태가 유지 → **재발화 없음**

판정 기준점(reference)은 config 로 고를 수 있다:
  foot   (기본) 박스 하단 중앙 = 발이 닿는 지점. 지면 기준 구역에 맞다.
  center        박스 중심. 카메라가 거의 수직으로 내려다보면 하단이 발이 아니라 머리·어깨쪽
                이므로(직하방 문제, docs/camera_requirements.md) 중심이 더 안정적일 수 있다.
"""
from __future__ import annotations

import time
from typing import Any

import tuning


def enter_s() -> float:
    return float(tuning.val("zone", "enter_s", 1.0))


def exit_s() -> float:
    return float(tuning.val("zone", "exit_s", 1.0))


def reference() -> str:
    return str(tuning.val("zone", "reference", "foot")).strip().lower()


def ref_point(bbox: list[float], ref: str | None = None) -> tuple[float, float]:
    """정규화 bbox → 구역 판정에 쓸 대표점(정규화 좌표).

    foot(기본): 하단 중앙 — 사람이 서 있는 지면 위치. 기존 동작과 동일.
    center    : 박스 중심 — 직하방·고각 카메라에서 하단이 지면 접점이 아닐 때.
    """
    x1, y1, x2, y2 = (list(bbox) + [0, 0, 0, 0])[:4]
    r = (ref or reference())
    if r == "center":
        return ((x1 + x2) / 2, (y1 + y2) / 2)
    return ((x1 + x2) / 2, y2)          # foot(기본)


class ZoneDebouncer:
    """카메라별 침입 확정 상태 기계. worker 가 카메라 1대당 1개를 들고 매 프레임 update() 한다."""

    def __init__(self) -> None:
        # cid → {"confirmed": bool, "raw": bool, "since": float}
        self._st: dict[str, dict[str, Any]] = {}

    def update(self, cid: str, raw_inside: bool, now: float | None = None) -> bool:
        """raw_inside(이 프레임에 구역 안 사람이 있나) → 확정 침입 여부.

        반환값은 '확정 상태'다. 발화(경보)는 호출부가 False→True 전이에서만 하면 된다.
        """
        now = time.time() if now is None else now
        s = self._st.get(cid)
        if s is None:
            # 첫 관측: 확정 상태를 raw 로 초기화하지 않는다 — 기동 순간 구역 안에 사람이 있으면
            #   유예 없이 발화해버린다. 항상 '밖'에서 시작해 정상 유예를 거치게 한다.
            s = {"confirmed": False, "raw": raw_inside, "since": now}
            self._st[cid] = s
            return False

        if raw_inside != s["raw"]:          # raw 가 바뀌면 유지 타이머 재시작
            s["raw"] = raw_inside
            s["since"] = now
            return bool(s["confirmed"])

        held = now - s["since"]
        if raw_inside and not s["confirmed"] and held >= enter_s():
            s["confirmed"] = True
        elif (not raw_inside) and s["confirmed"] and held >= exit_s():
            s["confirmed"] = False
        return bool(s["confirmed"])

    def state(self, cid: str) -> dict[str, Any]:
        s = self._st.get(cid)
        if not s:
            return {"confirmed": False, "raw": False, "held_s": None}
        return {"confirmed": bool(s["confirmed"]), "raw": bool(s["raw"]),
                "held_s": round(time.time() - s["since"], 2)}

    def reset(self, cid: str | None = None) -> None:
        if cid is None:
            self._st.clear()
        else:
            self._st.pop(cid, None)
