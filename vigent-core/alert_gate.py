"""alert_gate.py — [W1] 경보 통보 게이트(폭주 방지).

배경: [M1](benchmarks/m1_alert_latency.md) 에서 **워커 검출 경로에 알림 전송 배선이 없다**는
것이 확인됐고, 같은 날 [M2/M3] 에서 **정지한 오검출 하나가 무동작 경보를 24시간에 221건
낳는다**는 것이 실측됐다. 배선만 하고 억제가 없으면 켜는 순간 현장에서 경보 폭탄이 된다 —
그래서 배선과 억제는 **한 묶음**이다.

★**기록은 절대 억제하지 않는다.** 이 게이트는 **통보(알림 전송)만** 거른다.
증거 프레임·이벤트 로그는 기존 경로 그대로 전부 남는다 — 사후 조사와 오탐률 측정
(M3 §4)의 근거이기 때문이다. "안 보낸 것"과 "없던 일"은 다르다.

정책 (카메라 + 규칙 단위):
  1) **반복 억제**  통보 후 쿨다운 동안 같은 규칙 통보 억제(기본 300초에서 시작)
  2) ★**적응형 백오프**  반복될수록 쿨다운을 2배씩 늘린다(300→600→1200→…→상한 3600초).
     조용해지면 기본값으로 되돌린다.
  3) **시간당 상한** `max_per_hour`(기본 6) 초과분 억제 — 등급 상승 예외도 이 상한은 못 넘는다
  4) **등급 상승 예외** 직전 통보보다 등급이 오르면(high→critical) 쿨다운을 무시하고 통보
     — 상황이 악화된 것은 늦게 알면 안 된다
  5) **억제 요약**  억제된 건수를 다음 통보에 실어 보낸다(정보 손실 방지)

★**왜 고정 쿨다운으로는 부족한가**(설계 중 실측으로 확인): [M3] 의 무동작 오경보는
24시간에 221건 = **평균 391초 간격**이다. 고정 300초 쿨다운은 391초 간격을 그대로
통과시키고 시간당 9.2건이라 상한(10)에도 안 걸린다 — **221건이 전부 나간다.**
그래서 "반복되면 점점 뜸해지는" 백오프가 필요하다. 백오프가 상한(3600초)에 도달하면
같은 원인은 **시간당 1건**으로 수렴한다(완전 침묵이 아니라 — 카메라가 계속 이상하다는
사실 자체는 알아야 한다).

이 모듈은 **순수 정책**이다 — 스레드·네트워크·디스크를 쓰지 않아 그대로 단위 테스트된다.
실제 비동기 전송은 `alert_notify.py` 가 담당한다.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import tuning

# 등급 순위 — 저장소에 한글·영문 표기가 섞여 있어 둘 다 받는다(모르는 값은 0).
LEVEL_RANK: dict[str, int] = {
    "low": 0, "낮음": 0, "info": 0,
    "medium": 1, "mid": 1, "중간": 1,
    "high": 2, "높음": 2,
    "critical": 3, "심각": 3,
}

_lock = threading.RLock()
# (cam, rule) → {"last_notify": float, "last_rank": int, "suppressed": int, "hist": [float, ...]}
_state: dict[tuple[str, str], dict[str, Any]] = {}


def enabled() -> bool:
    """워커 검출 → 알림 전송 배선 자체의 on/off. 롤백 경로(false = 구 동작: 통보 안 함)."""
    return bool(tuning.val("alerts", "notify", True, env="VIGENT_ALERT_NOTIFY"))


def cooldown_s() -> float:
    return float(tuning.val("alerts", "notify_cooldown_s", 300.0))


def max_per_hour() -> int:
    return int(tuning.val("alerts", "max_per_hour", 6))


def backoff_factor() -> float:
    """반복될 때 쿨다운을 늘리는 배수. 1.0 이면 백오프 없음(고정 쿨다운)."""
    return max(1.0, float(tuning.val("alerts", "backoff_factor", 2.0)))


def backoff_max_s() -> float:
    return float(tuning.val("alerts", "backoff_max_s", 3600.0))


def quiet_reset_s() -> float:
    """이 시간 동안 발화가 한 건도 없으면 백오프를 기본값으로 되돌린다."""
    return float(tuning.val("alerts", "quiet_reset_s", 1800.0))


def rank(level: str) -> int:
    return LEVEL_RANK.get(str(level or "").strip().lower(), 0)


def decide(cam: str, rule: str, level: str, now: float | None = None,
           edge: bool = False) -> dict[str, Any]:
    """이 발화를 통보할 것인가.

    반환: {"notify": bool, "suppressed": int, "reason": str}
      suppressed = 직전 통보 이후 억제된 건수(통보할 때만 의미 있음 — 메시지에 싣는다)
    edge: [CODE_REVIEW M3-2] "상태 전이" 발화(센서 임계 진입 등 — 호출측이 이미 전이에서만 1회 부른다).
      쿨다운·백오프는 건너뛰되 **시간당 상한은 그대로** 적용한다(최종 방어선은 우회 불가).
    """
    now = time.time() if now is None else now
    key = (str(cam), str(rule))
    r = rank(level)
    base = cooldown_s()
    with _lock:
        s = _state.get(key)
        if s is None:
            s = {"last_notify": 0.0, "last_rank": -1, "suppressed": 0,
                 "hist": [], "cd": base, "last_seen": 0.0}
            _state[key] = s

        # ── 백오프 리셋: 발화 자체가 한동안 없었으면 "새 상황"으로 보고 기본값 복귀
        if s["last_seen"] and now - s["last_seen"] >= quiet_reset_s():
            s["cd"] = base
            s["suppressed"] = 0
        s["last_seen"] = now

        # ── 시간당 상한: 최근 1시간 통보 이력만 남기고 센다(최종 방어선)
        s["hist"] = [t for t in s["hist"] if now - t < 3600.0]
        if len(s["hist"]) >= max_per_hour():
            s["suppressed"] += 1
            return {"notify": False, "suppressed": s["suppressed"], "reason": "hourly_cap"}

        # ── 등급 상승이면 쿨다운을 건너뛴다(상황 악화는 늦으면 안 된다)
        escalated = r > s["last_rank"] and s["last_rank"] >= 0
        held = now - s["last_notify"]
        cd = min(float(s["cd"]), backoff_max_s())
        if s["last_notify"] > 0 and held < cd and not escalated and not edge:
            s["suppressed"] += 1
            return {"notify": False, "suppressed": s["suppressed"], "reason": "cooldown"}

        sup = int(s["suppressed"])
        s["last_notify"] = now
        s["last_rank"] = r
        s["suppressed"] = 0
        s["hist"].append(now)
        # ★통보할 때마다 다음 쿨다운을 늘린다 — 반복되는 원인일수록 점점 뜸해진다.
        s["cd"] = min(cd * backoff_factor(), backoff_max_s())
        return {"notify": True, "suppressed": sup, "next_cooldown_s": round(s["cd"], 1),
                "reason": "escalated" if escalated else ("edge" if edge else "ok")}


def annotate(message: str, suppressed: int) -> str:
    """억제 요약을 통보 메시지에 덧붙인다 — 억제된 사실이 사라지지 않게."""
    if suppressed <= 0:
        return message
    return f"{message} · 직전 통보 이후 동일 경보 {suppressed}건 억제됨"


def snapshot() -> dict[str, dict[str, Any]]:
    """관측용 요약(운영 점검). 상태를 바꾸지 않는다."""
    now = time.time()
    with _lock:
        return {f"{c}/{r}": {
            "last_notify_ago_s": round(now - s["last_notify"], 1) if s["last_notify"] else None,
            "suppressed_pending": s["suppressed"],
            "notified_last_hour": len([t for t in s["hist"] if now - t < 3600.0]),
            "cooldown_s": round(float(s.get("cd", 0)), 1),
        } for (c, r), s in _state.items()}


def reset() -> None:
    """테스트·재기동용 상태 초기화."""
    with _lock:
        _state.clear()
