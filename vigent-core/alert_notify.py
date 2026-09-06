"""alert_notify.py — [W1] 워커 검출 → 알림 전송 배선(비동기).

★**왜 비동기인가**: `dispatcher._dispatch_now()` 는 텔레그램·이메일·웹훅을 **동기 호출**하고
타임아웃이 6~8초다. 이것을 워커 루프에서 직접 부르면 채널 한 개가 느려질 때 **검출이 수 초간
멈춘다** — 안전 기능이 알림 때문에 죽는 최악의 구조다(CLAUDE.md 규칙6: 저하 금지).
그래서 워커는 **큐에 넣기만** 하고(마이크로초), 전용 스레드가 전송을 맡는다.

기존 내구 큐 경로는 그대로 탄다: 이 스레드가 부르는 것은 `dispatcher.dispatch()` 이고,
그 안에서 **선기록(alert_queue.enqueue) → 즉시 전송 → 성공/실패 표시**가 이뤄진다.
전송이 실패하면 [B5] 재시도 스레드가 지수 백오프로 이어받는다 — 경보는 유실되지 않는다.

★**전송 실패가 검출을 막지 않는다**: submit() 은 예외를 올리지 않고, 큐가 가득 차면
버리는 대신 **가장 오래된 항목을 버리고 새 것을 넣는다**(최신 위험 우선). 전송 스레드의
예외는 로그만 남기고 루프를 유지한다.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Any, Callable

import alert_gate
import tuning
import vlog

_LOG = vlog.get("vigent.alert_notify")

_sender: Callable[[str, str, dict], dict] | None = None
_q: queue.Queue | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.RLock()

_stats: dict[str, int] = {"submitted": 0, "queued": 0, "suppressed": 0,
                          "dropped": 0, "sent": 0, "failed": 0}


def queue_max() -> int:
    return max(16, int(tuning.val("alerts", "queue_max", 200)))


def set_sender(fn: Callable[[str, str, dict], dict]) -> None:
    """실제 전송 함수 주입(보통 dispatcher.dispatch). main 예열 배선에서 부른다."""
    global _sender
    _sender = fn


def _loop() -> None:
    assert _q is not None
    while not _stop.is_set():
        try:
            item = _q.get(timeout=1.0)
        except queue.Empty:
            continue
        level, message, meta = item
        try:
            if _sender is None:
                _stats["failed"] += 1
                _LOG.warning("경보 전송기 미주입 — 통보 건너뜀(기록은 유지됨): %s", message[:120])
                continue
            res = _sender(level, message, meta) or {}
            if res.get("delivered"):
                _stats["sent"] += 1
            else:
                # 미도달이어도 dispatcher 가 alert_queue 에 pending 으로 남겨 재시도 스레드가 이어받는다.
                _stats["failed"] += 1
                _LOG.info("경보 즉시 전송 미도달 — 재시도 큐로 이월: %s", message[:120])
        except Exception:  # noqa: BLE001  전송 실패가 스레드를 죽이면 이후 경보가 전부 막힌다
            _stats["failed"] += 1
            _LOG.error("경보 전송 예외 — 루프 유지", exc_info=True)


def start() -> threading.Thread | None:
    """전송 스레드 기동(중복 호출 안전)."""
    global _thread, _q
    with _lock:
        if _q is None:                      # ★큐가 없으면 스레드 생존 여부와 무관하게 만든다
            _q = queue.Queue(maxsize=queue_max())
        if _thread is not None and _thread.is_alive():
            _stop.clear()
            return _thread
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="vigent-alert-notify", daemon=True)
        _thread.start()
        _LOG.info("경보 통보 스레드 시작 — 큐 %d · 반복억제 %.0fs · 시간당 상한 %d건",
                  queue_max(), alert_gate.cooldown_s(), alert_gate.max_per_hour())
        return _thread


def stop(join_s: float = 2.0) -> None:
    """전송 스레드 정지(테스트·종료용). 스레드 참조를 비워 다음 start() 가 새로 띄운다."""
    global _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=join_s)
        if t.is_alive():
            # ★[2026-08-28] 예전에는 join 실패해도 참조를 지웠다. 그러면 다음 start() 가
            #   **두 번째 스레드**를 띄우고, 고아 스레드는 그때그때의 전역 sender 로 계속
            #   전송한다(느린 채널이면 join 2초를 넘기기 쉽다 — 실측으로 확인).
            #   참조를 유지하면 start() 가 그 스레드를 재사용해 중복이 생기지 않는다.
            _LOG.warning("통보 스레드가 %.1f초 안에 끝나지 않았다 — 참조를 유지한다"
                         "(중복 기동 방지)", join_s)
            return
    _thread = None


def submit(cam: str, rule: str, level: str, message: str,
           meta: dict[str, Any] | None = None, *, edge: bool = False) -> dict[str, Any]:
    """위험 발화 1건을 통보 대기열에 넣는다. **절대 블로킹하지 않고 예외도 올리지 않는다.**

    반환: {"queued": bool, "suppressed": int, "reason": str}
    cam 은 **출처 키**다 — 워커는 카메라명, 우회 경로는 `sensor:<종류>`·`browser_zone:<cam>`·`brain`·`manual`
    ([CODE_REVIEW M3-2·M3-3]: 출처별로 게이트 예산(시간당 상한·백오프)을 나눠 영상 경보와 섞이지 않게).
    edge=True 는 상태 전이 발화(쿨다운 건너뜀, 시간당 상한은 유지) — alert_gate.decide 참조.
    """
    _stats["submitted"] += 1
    try:
        if not alert_gate.enabled():
            return {"queued": False, "suppressed": 0, "reason": "disabled"}
        d = alert_gate.decide(cam, rule, level, edge=edge)
        if not d["notify"]:
            _stats["suppressed"] += 1
            return {"queued": False, "suppressed": d["suppressed"], "reason": d["reason"]}

        text = alert_gate.annotate(message, d["suppressed"])
        m = dict(meta or {})
        m.update({"camera": cam, "rule": rule, "ts": time.time()})
        if _q is None:
            start()
        assert _q is not None
        try:
            _q.put_nowait((level, text, m))
        except queue.Full:
            # ★가득 차면 **가장 오래된 것을 버리고** 새 것을 넣는다 — 최신 위험이 우선이다.
            try:
                _q.get_nowait()
                _stats["dropped"] += 1
            except queue.Empty:
                pass
            try:
                _q.put_nowait((level, text, m))
            except queue.Full:
                _stats["dropped"] += 1
                return {"queued": False, "suppressed": d["suppressed"], "reason": "queue_full"}
        _stats["queued"] += 1
        return {"queued": True, "suppressed": d["suppressed"], "reason": d["reason"]}
    except Exception:  # noqa: BLE001  ★통보 실패가 검출 루프를 죽이면 안 된다
        _LOG.error("경보 통보 제출 예외 — 검출은 계속", exc_info=True)
        return {"queued": False, "suppressed": 0, "reason": "exception"}


def stats() -> dict[str, Any]:
    d = dict(_stats)
    d["queue_depth"] = _q.qsize() if _q is not None else 0
    d["thread_alive"] = bool(_thread is not None and _thread.is_alive())
    d["sender_wired"] = _sender is not None
    return d


def reset_for_test() -> None:
    """테스트 격리용 — 스레드를 쓰지 않는 경로만 초기화."""
    global _q, _sender
    for k in _stats:
        _stats[k] = 0
    _q = None
    _sender = None
    alert_gate.reset()
