"""relay.py — [P3a] 물리 출력(사이렌·경광등) 네트워크 릴레이 채널.

배경(감사 🟠C7): `safety_relay_signal` 은 **로그 항목만 추가**하고 `sent:True` 를 반환했다
(dispatcher.py:163) — 실제 하드웨어 출력 경로가 없었다. 현장에서 "경보가 울렸다"고 표시되는데
아무 소리도 안 나는 상태였다.

★결정된 사항: 파일럿은 **네트워크 릴레이 1채널**(HTTP 또는 Modbus TCP). GPIO·시리얼은 만들지
않는다. 실물 릴레이가 없으므로 mock 서버로 검증한다(`scripts/mock_relay.py`).

★설계의 중심은 **OFF 보장**이다. 사이렌이 안 켜지는 것보다 **안 꺼지는 것이 최악**이다
(현장 소음 민원·경보 무시 유발·작업 중단). 그래서:
  - OFF 는 ON 보다 **강하게 재시도**한다(재시도 횟수·시간 상한을 따로 둔다).
  - OFF 최종 실패는 **로그 + /health 에 반드시 드러낸다**(`relay.off_failed`).
  - ON 은 `on_duration_s` 뒤 자동 OFF(타이머). 재트리거되면 타이머를 **연장**한다.

⚠ §8 기능안전 경계: 이 릴레이는 **보조 신호**다. 인증 안전회로(안전 PLC·Type4 방호장치)를
대체하지 않는다.
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from typing import Any

import tuning
import vlog

_LOG = vlog.get("vigent.relay")

_lock = threading.RLock()
_state: dict[str, Any] = {
    "on": False,
    "on_since": None,      # ON 시각
    "off_due": None,       # 자동 OFF 예정 시각
    "off_failed": False,   # ★OFF 최종 실패(사이렌이 안 꺼졌을 수 있음) — /health 노출
    "last_error": "",
    "on_count": 0,
    "off_count": 0,
    "retrigger_count": 0,
}
_timer: threading.Timer | None = None


def enabled() -> bool:
    return bool(tuning.val("relay", "enabled", False))


def _cfg(key: str, default: Any) -> Any:
    return tuning.val("relay", key, default)


def on_duration_s() -> float:
    return float(_cfg("on_duration_s", 30.0))


def _url(action: str) -> str:
    """ON/OFF URL. on_url·off_url 이 있으면 그것을, 없으면 url 에 ?state= 를 붙인다."""
    u = str(_cfg(f"{action}_url", "") or "")
    if u:
        return u
    base = str(_cfg("url", "") or "")
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}state={action}"


def _http(action: str, timeout: float) -> tuple[bool, str]:
    url = _url(action)
    if not url:
        return False, "url 미설정"
    try:
        req = urllib.request.Request(url, method=str(_cfg("method", "GET")).upper())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ok = 200 <= r.status < 300
            return ok, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as ex:  # noqa: BLE001
        return False, f"{type(ex).__name__}: {ex}"


def _send(action: str, attempts: int, backoff_cap: float, timeout: float) -> tuple[bool, str]:
    """지수 백오프 재시도. attempts 회 시도 후에도 실패면 (False, 사유)."""
    last = ""
    for i in range(max(1, attempts)):
        ok, why = _http(action, timeout)
        if ok:
            return True, why
        last = why
        if i < attempts - 1:
            time.sleep(min(2.0 ** i, backoff_cap))
    return False, last


def _cancel_timer() -> None:
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None


def turn_on(reason: str = "") -> dict[str, Any]:
    """릴레이 ON + on_duration_s 뒤 자동 OFF 예약. 이미 ON 이면 타이머만 연장(재트리거)."""
    if not enabled():
        return {"channel": "relay", "sent": False, "reason": "relay 비활성"}
    with _lock:
        already = _state["on"]
        if already:
            _state["retrigger_count"] += 1
        ok, why = _send("on", int(_cfg("on_attempts", 3)),
                        float(_cfg("backoff_cap_s", 4.0)), float(_cfg("timeout_s", 5.0)))
        now = time.time()
        if ok:
            _state.update(on=True, on_since=_state["on_since"] or now,
                          off_due=now + on_duration_s(), last_error="")
            _state["on_count"] += 1 if not already else 0
            _schedule_off()
            _LOG.warning("릴레이 ON%s (%s) — %.0f초 뒤 자동 OFF",
                         "(연장)" if already else "", reason or "경보", on_duration_s())
        else:
            _state["last_error"] = f"ON 실패: {why}"
            _LOG.error("릴레이 ON 실패: %s", why)
        return {"channel": "relay", "sent": ok, "action": "on",
                "retrigger": already, "reason": why}


def turn_off(reason: str = "") -> dict[str, Any]:
    """릴레이 OFF. ★ON 보다 강하게 재시도하고, 최종 실패는 상태로 드러낸다."""
    if not enabled():
        return {"channel": "relay", "sent": False, "reason": "relay 비활성"}
    with _lock:
        _cancel_timer()
        ok, why = _send("off", int(_cfg("off_attempts", 8)),      # ★ON(3)보다 많이
                        float(_cfg("backoff_cap_s", 4.0)),
                        float(_cfg("off_timeout_s", 8.0)))        # ★ON(5)보다 길게
        if ok:
            _state.update(on=False, on_since=None, off_due=None,
                          off_failed=False, last_error="")
            _state["off_count"] += 1
            _LOG.info("릴레이 OFF (%s)", reason or "해제")
        else:
            # ★사이렌이 안 꺼졌을 수 있다 — 가장 위험한 상태. 상태로 남겨 /health 가 드러낸다.
            _state["off_failed"] = True
            _state["last_error"] = f"OFF 실패: {why}"
            _LOG.error("★릴레이 OFF 실패(%s) — 물리 출력이 켜진 채로 남았을 수 있다. "
                       "현장 확인 필요", why)
        return {"channel": "relay", "sent": ok, "action": "off", "reason": why}


def _schedule_off() -> None:
    global _timer
    _cancel_timer()
    _timer = threading.Timer(on_duration_s(), lambda: turn_off("자동 해제(시간 만료)"))
    _timer.daemon = True
    _timer.start()


def status() -> dict[str, Any]:
    """/health 노출용. ★off_failed 가 true 면 물리 출력이 켜진 채 남았을 수 있다."""
    with _lock:
        s = dict(_state)
    return {
        "enabled": enabled(),
        "on": s["on"],
        "off_failed": s["off_failed"],
        "on_count": s["on_count"],
        "off_count": s["off_count"],
        "retrigger_count": s["retrigger_count"],
        "remaining_s": (round(s["off_due"] - time.time(), 1)
                        if s["off_due"] and s["on"] else None),
        "last_error": s["last_error"],
    }


def _reset_for_test() -> None:
    global _timer
    with _lock:
        _cancel_timer()
        _state.update(on=False, on_since=None, off_due=None, off_failed=False,
                      last_error="", on_count=0, off_count=0, retrigger_count=0)
