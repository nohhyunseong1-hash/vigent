"""relay.py — [P3a] 물리 출력(사이렌·경광등) 네트워크 릴레이 채널.

배경(감사 🟠C7): `safety_relay_signal` 은 **로그 항목만 추가**하고 `sent:True` 를 반환했다
(dispatcher.py:163) — 실제 하드웨어 출력 경로가 없었다. 현장에서 "경보가 울렸다"고 표시되는데
아무 소리도 안 나는 상태였다.

★결정된 사항: 파일럿은 **네트워크 릴레이 1채널(HTTP GET/POST 만)**. GPIO·시리얼은 만들지
않는다. 실물 릴레이가 없으므로 mock 서버로 검증한다(`scripts/mock_relay.py`).
★2026-09-26 정정: 이전 문구 "HTTP 또는 Modbus TCP" 에서 Modbus TCP 를 지웠다 — 구현·라이브러리가
없다(docs/review/ALGORITHM_TRUTH_20260926.md §6 #26). Modbus 릴레이를 조달하면 동작하지 않는다.

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
    "off_retry_count": 0,   # [CODE_AUDIT #2] OFF 최종 실패 뒤 백오프 재시도 횟수(성공 시 0)
    "off_retry_due": None,  # 다음 OFF 재시도 예정 시각
}
_timer: threading.Timer | None = None
_off_retry_timer: threading.Timer | None = None   # [CODE_AUDIT #2] OFF 재시도 타이머(자동 해제 타이머와 별개)


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
    # ★[CODE_AUDIT_20260928 #2] HTTP 는 락 **밖**에서 — 예전엔 OFF 재시도(최대 ≈90 s)가 락을 쥔 동안 통보 스레드의 ON 이 통째로 막혔다.
    ok, why = _send("on", int(_cfg("on_attempts", 3)),
                    float(_cfg("backoff_cap_s", 4.0)), float(_cfg("timeout_s", 5.0)))
    with _lock:
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
        _cancel_off_retry()
    ok, why = _send("off", int(_cfg("off_attempts", 8)),      # ★ON(3)보다 많이 — HTTP 는 락 밖(#2)
                    float(_cfg("backoff_cap_s", 4.0)),
                    float(_cfg("off_timeout_s", 8.0)))        # ★ON(5)보다 길게
    with _lock:
        if ok:
            retried = _state["off_retry_count"]
            _state.update(on=False, on_since=None, off_due=None,
                          off_failed=False, last_error="", off_retry_count=0, off_retry_due=None)
            _state["off_count"] += 1
            _LOG.info("릴레이 OFF (%s)%s", reason or "해제", f" — 재시도 {retried}회 만에 성공" if retried else "")
        else:
            # ★사이렌이 안 꺼졌을 수 있다 — 가장 위험한 상태. 상태로 남겨 /health 가 드러내고,
            #   [CODE_AUDIT_20260928 #2] 지수 백오프로 **계속** OFF 를 재시도하며 첫 실패는 통보한다(예전엔 플래그만 남고 끝).
            first = not _state["off_failed"]
            _state["off_failed"] = True
            _state["last_error"] = f"OFF 실패: {why}"
            _LOG.error("★릴레이 OFF 실패(%s) — 물리 출력이 켜진 채로 남았을 수 있다. "
                       "현장 확인 필요", why)
            delay = _schedule_off_retry()
        if not ok and first:
            _notify_off_failed(why, delay)
        return {"channel": "relay", "sent": ok, "action": "off", "reason": why}


def _off_retry_delay(n: int) -> float:
    """n번째(0부터) 재시도까지 대기(초): base·2^n, cap 까지. 기본 5 s → 10 → 20 → … → 300 s."""
    base = float(_cfg("off_retry_base_s", 5.0)); cap = float(_cfg("off_retry_cap_s", 300.0))
    return min(base * (2.0 ** n), cap)


def _cancel_off_retry() -> None:
    global _off_retry_timer
    if _off_retry_timer is not None:
        _off_retry_timer.cancel()
        _off_retry_timer = None


def _schedule_off_retry() -> float:
    """OFF 재시도 예약(락 안에서 호출). 반환: 대기 초."""
    global _off_retry_timer
    _cancel_off_retry()
    n = int(_state["off_retry_count"]); delay = _off_retry_delay(n)
    _state["off_retry_count"] = n + 1
    _state["off_retry_due"] = time.time() + delay
    _off_retry_timer = threading.Timer(delay, lambda: turn_off(f"OFF 재시도 #{n + 1}"))
    _off_retry_timer.daemon = True
    _off_retry_timer.start()
    _LOG.warning("릴레이 OFF 재시도 #%d 를 %.0f초 뒤 예약", n + 1, delay)
    return delay


def _notify_off_failed(why: str, delay: float) -> None:
    """OFF 최종 실패를 통보 경로로 올린다(출처 relay, 게이트가 반복을 억제). 통보 실패가 릴레이 상태를 바꾸지는 않는다."""
    try:
        import alert_notify
        alert_notify.submit(cam="relay", rule="relay_off_failed", level="critical",
                            message=f"★릴레이 OFF 실패({why}) — 사이렌이 켜진 채일 수 있음. {delay:.0f}초 뒤 자동 재시도, 현장 확인 필요",
                            meta={"why": why, "retry_in_s": delay}, edge=True)
    except Exception:  # noqa: BLE001
        _LOG.error("릴레이 OFF 실패 통보 자체가 실패", exc_info=True)


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
        "off_retry_count": s["off_retry_count"],                      # [CODE_AUDIT #2]
        "off_retry_in_s": (round(s["off_retry_due"] - time.time(), 1) if s["off_retry_due"] else None),
        "remaining_s": (round(s["off_due"] - time.time(), 1)
                        if s["off_due"] and s["on"] else None),
        "last_error": s["last_error"],
    }


def _reset_for_test() -> None:
    """★[2026-08-28] 테스트 간 상태 격리 — 실행 **중인** 자동해제 콜백까지 기다린다.

    `Timer.cancel()` 은 **아직 시작하지 않은** 타이머만 막는다. 이미 발화해 `turn_off` 를
    실행 중이면(HTTP 재시도 최대 8회) 그 콜백이 **리셋 이후에** `_state` 를 덮어써서
    다음 테스트의 on_count·retrigger_count 가 어긋난다.
    실제로 전체 스위트에서만 `test_duplicate_alert_extends_not_duplicates` 가 실패했다
    (단독 3/3 통과) — 부하가 클수록 콜백 실행 창이 길어져 확률이 올라간다.
    [F29] 와 같은 계열의 문제다: 간헐 실패는 진짜 회귀와 구분이 안 돼 게이트를 못 믿게 만든다.
    """
    global _timer
    t = _timer
    if t is not None:
        t.cancel()
        if t.is_alive():        # 이미 발화해 콜백이 도는 중이면 끝날 때까지 기다린다
            t.join(timeout=5.0)
    rt = _off_retry_timer
    if rt is not None:
        rt.cancel()
        if rt.is_alive():
            rt.join(timeout=5.0)
    with _lock:
        _cancel_timer()
        _cancel_off_retry()
        _state.update(on=False, on_since=None, off_due=None, off_failed=False,
                      last_error="", on_count=0, off_count=0, retrigger_count=0,
                      off_retry_count=0, off_retry_due=None)
