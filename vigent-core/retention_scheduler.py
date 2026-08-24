"""retention_scheduler.py — [F6] 보존 정책 스윕을 **서버가 스스로** 주기 실행한다.

배경(설치 전 안전 리뷰 F6, 2026-08-21): `retention.sweep()` 은 구현돼 있었지만
**부르는 주체가 어디에도 없었다** — `main.py` 에 주기 스레드 0건, 배포 스크립트에
`schtasks`/`Register-ScheduledTask` 0건, `scripts/retention_sweep.py` 는 존재하나
사람이 손으로 돌려야 했다(라이브 `last_run` 이 3일 전 수동 실행). 즉 문서가 말하던
"자동 파기"는 **사실이 아니었다.**

작업 스케줄러 등록이 아니라 **서버 내 스레드**로 간 이유(사용자 결정): 설치 절차가
하나 늘면 새 현장마다 사람이 빠뜨린다. 무인 운영이 전제인 제품은 서버가 스스로 돌아야 한다.

★설계 원칙 — 이 스레드는 **감시를 절대 막지 않는다**:
  · 별도 데몬 스레드. `DETECT_LOCK` 을 잡지 않고 GPU·모델을 건드리지 않는다.
  · 스윕 실패는 로그만 남기고 다음 주기로 넘어간다(예외로 스레드가 죽지 않는다).
  · 첫 주기 보류·경로 화이트리스트 등 [P1b] 안전장치는 `retention.sweep()` 안에 있으므로
    **그대로 탄다** — 여기서는 아무 안전장치도 우회하지 않는다(execute=None 으로 호출해
    설정(`retention.dry_run`)을 그대로 따른다).
  · 기동 직후에는 돌지 않는다(`initial_delay_s`) — 예열·워커 기동과 디스크 경합 회피.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import tuning
import vlog

_LOG = vlog.get("vigent.retention_sched")

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.RLock()
_state: dict[str, Any] = {"runs": 0, "failures": 0, "next_run_at": None, "last_error": ""}


def interval_s() -> float:
    """스윕 주기(초). 기본 24시간."""
    return max(60.0, float(tuning.val("retention", "sweep_interval_s", 86400.0)))


def initial_delay_s() -> float:
    """기동 후 첫 스윕까지 대기(초). 예열·워커 기동과 겹치지 않게 기본 10분."""
    return max(0.0, float(tuning.val("retention", "sweep_initial_delay_s", 600.0)))


def auto_enabled() -> bool:
    """서버 내 자동 스윕 스레드 자체의 on/off. **롤백 경로**(false = 구 동작: 수동 실행만)."""
    return bool(tuning.val("retention", "auto_sweep", True))


def _run_once() -> None:
    import retention
    if not retention.is_enabled():
        _LOG.info("보존 정책 비활성(retention.enabled=false) — 스윕 건너뜀")
        return
    # execute=None: 설정(retention.dry_run)을 그대로 따른다. 첫 주기 보류([P1b])도 유지된다.
    res = retention.sweep()
    with _lock:
        _state["runs"] += 1
    _LOG.info("보존 스윕 완료 — 삭제 %d건(%.1fMB) · 대기 %d건 · 소요 %.2fs%s",
              int(res.get("deleted_count") or 0),
              float(res.get("deleted_bytes") or 0) / 1024 ** 2,
              int(res.get("pending_count") or 0),
              float(res.get("elapsed_sec") or 0),
              " · ★첫 주기 보류(목록만)" if res.get("first_run_notice") else "")
    for w in (res.get("warnings") or []):
        _LOG.warning("보존 스윕 경고: %s", w)


def _loop() -> None:
    # 기동 직후는 쉬어간다 — 예열·모델 로드·워커 기동과 디스크를 다투지 않게.
    if _stop.wait(initial_delay_s()):
        return
    while not _stop.is_set():
        try:
            _run_once()
            with _lock:
                _state["last_error"] = ""
        except Exception as ex:  # noqa: BLE001  ★스윕 실패가 스레드를 죽이면 이후 영영 안 돈다
            with _lock:
                _state["failures"] += 1
                _state["last_error"] = f"{type(ex).__name__}: {ex}"
            _LOG.error("보존 스윕 실패 — 다음 주기에 재시도(서비스 영향 없음)", exc_info=True)
        iv = interval_s()
        with _lock:
            _state["next_run_at"] = time.time() + iv
        if _stop.wait(iv):
            return


def start() -> threading.Thread | None:
    """스윕 스레드 기동(중복 호출 안전). auto_sweep=false 면 기동하지 않는다."""
    global _thread
    with _lock:
        if not auto_enabled():
            _LOG.info("보존 스윕 자동 실행 꺼짐(retention.auto_sweep=false) — 수동 실행만")
            return None
        if _thread is not None and _thread.is_alive():
            return _thread
        _stop.clear()
        _state["next_run_at"] = time.time() + initial_delay_s()
        _thread = threading.Thread(target=_loop, name="vigent-retention-sweep", daemon=True)
        _thread.start()
        _LOG.info("보존 스윕 스레드 시작 — 주기 %.0f시간 · 첫 실행 %.0f분 뒤",
                  interval_s() / 3600.0, initial_delay_s() / 60.0)
        return _thread


def stop() -> None:
    global _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=2.0)
    _thread = None


def status() -> dict[str, Any]:
    """/health 노출용 — 자동 스윕이 실제로 돌고 있는지와 다음 예정 시각."""
    with _lock:
        s = dict(_state)
    nxt = s.get("next_run_at")
    return {
        "auto_sweep": auto_enabled(),
        "thread_alive": bool(_thread is not None and _thread.is_alive()),
        "interval_h": round(interval_s() / 3600.0, 2),
        "runs": s["runs"],
        "failures": s["failures"],
        "next_run_in_s": round(nxt - time.time(), 1) if nxt else None,
        "last_error": s["last_error"],
    }


def _reset_for_test() -> None:
    global _thread
    _stop.set()
    _thread = None
    _stop.clear()
    _state.update(runs=0, failures=0, next_run_at=None, last_error="")
