"""alert_queue.py — [B5] 경보 전송 내구 큐(sqlite) + 지수 백오프 재시도 + 데드레터.

배경(audit/site_readiness_2026-08-16.md 🔴B5): 경보 전송이 **1회성**이었다
(dispatcher._send_webhook/_send_email — timeout 6~8초, 실패하면 `sent:False` 반환하고 끝).
재시도·큐·데드레터가 저장소 전체에 0건이라, **인터넷 순단 중 발생한 위험 경보는 영구 소실**됐다.
안전 제품에서 "경보를 보냈는데 안 갔고 아무도 모른다"는 최악에 가깝다.

설계:
  - **선기록 후전송(write-ahead)**: 보내기 전에 먼저 sqlite 에 pending 으로 남긴다.
    전송 직전에 프로세스가 죽어도 경보가 사라지지 않는다.
  - 즉시 1회 전송 시도 → 성공하면 sent, 실패하면 pending 으로 남아 재시도 스레드가 이어받는다.
  - 재시도 간격은 지수 백오프(1,2,4,…최대 60초), 최대 10회. 초과 시 **dead** 표시.
  - `pending_count()` 를 /health 가 읽어 degraded 판정에 쓴다(미전송이 있으면 정상이 아니다).

기존 쿨다운과 충돌하지 않는다: 쿨다운(worker.py `_COOLDOWN_S`)은 **같은 규칙의 재발화를
억제**하는 상류 필터고, 이 큐는 **발화가 확정된 경보의 전달을 보장**하는 하류 장치다.
쿨다운이 걸러낸 것은 애초에 큐에 들어오지 않는다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

import tuning
import vlog

_LOG = vlog.get("vigent.alert_queue")
_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "alert_queue.db"

PENDING, SENT, DEAD = "pending", "sent", "dead"

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_stop = threading.Event()
_thread: threading.Thread | None = None
_sender: Callable[[str, str, dict], dict] | None = None


def max_attempts() -> int:
    return int(tuning.val("alerts", "max_attempts", 10))


def backoff_cap_s() -> float:
    return float(tuning.val("alerts", "backoff_cap_s", 60.0))


def _db() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
            _conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at REAL NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    meta TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    sent_at REAL
                )""")
            _conn.execute("CREATE INDEX IF NOT EXISTS ix_status_next ON alerts(status, next_attempt_at)")
            _conn.commit()
        return _conn


def enqueue(level: str, message: str, meta: dict[str, Any] | None = None) -> int:
    """경보를 큐에 먼저 기록한다(전송 전). 반환: row id."""
    db = _db()
    with _lock:
        cur = db.execute(
            "INSERT INTO alerts(created_at, level, message, meta, status, next_attempt_at) "
            "VALUES(?,?,?,?,?,?)",
            (time.time(), level, message, json.dumps(meta or {}, ensure_ascii=False), PENDING, 0.0))
        db.commit()
        return int(cur.lastrowid or 0)


def mark_sent(row_id: int) -> None:
    db = _db()
    with _lock:
        db.execute("UPDATE alerts SET status=?, sent_at=? WHERE id=?", (SENT, time.time(), row_id))
        db.commit()


def mark_failed(row_id: int, err: str) -> None:
    """실패 기록 + 다음 시도 시각 예약. 최대 횟수 초과면 dead."""
    db = _db()
    with _lock:
        row = db.execute("SELECT attempts FROM alerts WHERE id=?", (row_id,)).fetchone()
        attempts = (row[0] if row else 0) + 1
        if attempts >= max_attempts():
            db.execute("UPDATE alerts SET status=?, attempts=?, last_error=? WHERE id=?",
                       (DEAD, attempts, err[:500], row_id))
            _LOG.error("경보 데드레터(재시도 %d회 초과) id=%s: %s", attempts, row_id, err[:200])
        else:
            delay = min(2.0 ** (attempts - 1), backoff_cap_s())
            db.execute("UPDATE alerts SET attempts=?, next_attempt_at=?, last_error=? WHERE id=?",
                       (attempts, time.time() + delay, err[:500], row_id))
        db.commit()


def due(limit: int = 20) -> list[dict[str, Any]]:
    """재시도할 때가 된 pending 행(오래된 것부터 — 순서 보존)."""
    db = _db()
    with _lock:
        rows = db.execute(
            "SELECT id, level, message, meta, attempts FROM alerts "
            "WHERE status=? AND next_attempt_at<=? ORDER BY id ASC LIMIT ?",
            (PENDING, time.time(), limit)).fetchall()
    return [{"id": r[0], "level": r[1], "message": r[2],
             "meta": json.loads(r[3] or "{}"), "attempts": r[4]} for r in rows]


def counts() -> dict[str, int]:
    """/health·대시보드용 집계."""
    db = _db()
    with _lock:
        rows = db.execute("SELECT status, COUNT(*) FROM alerts GROUP BY status").fetchall()
    c = {PENDING: 0, SENT: 0, DEAD: 0}
    for st, n in rows:
        c[st] = n
    return c


def pending_count() -> int:
    return counts().get(PENDING, 0)


def dead_count() -> int:
    return counts().get(DEAD, 0)


def set_sender(fn: Callable[[str, str, dict], dict]) -> None:
    """실제 전송 함수 주입. 반환 dict 에 delivered(bool) 가 있어야 한다."""
    global _sender
    _sender = fn


_REMOTE_CHANNELS = ("telegram", "email", "webhook")


def _attempted_remote(res: dict[str, Any]) -> bool:
    """전송 결과에 **원격 채널이 하나라도 시도된 흔적**이 있는가.

    log·safety_relay_signal 만 있는 결과는 '보낼 곳이 없는 등급' 이므로 재시도 대상이 아니다.
    """
    for r in (res.get("results") or []):
        if isinstance(r, dict) and r.get("channel") in _REMOTE_CHANNELS:
            return True
    return False


def try_send(row: dict[str, Any]) -> bool:
    """1건 전송 시도. 성공하면 sent 표시, 실패하면 백오프 예약."""
    if _sender is None:
        mark_failed(row["id"], "sender 미주입")
        return False
    try:
        res = _sender(row["level"], row["message"], row["meta"])
        if res.get("delivered"):
            mark_sent(row["id"])
            return True
        # ★[2026-08-21] 원격 채널을 **아예 시도조차 안 한** 건은 재시도해도 영원히 실패한다
        #   (log 전용 등급). 이전에는 이런 건이 10회 재시도 후 데드레터로 갔고, 그 사이
        #   pending 때문에 /health 가 degraded 로 떨어졌다. 상류(_queue_enabled)에서 막았지만
        #   **이미 큐에 갇힌 건**도 스스로 풀리도록 여기서 종결 처리한다.
        if not _attempted_remote(res):
            _LOG.info("원격 채널 없는 등급(%s) — 로그 전달로 종결 처리(재시도 중단): %s",
                      row["level"], str(row["message"])[:80])
            mark_sent(row["id"])
            return True
        mark_failed(row["id"], str(res.get("results"))[:300])
        return False
    except Exception as ex:  # noqa: BLE001  전송 예외도 재시도 대상
        mark_failed(row["id"], f"{type(ex).__name__}: {ex}")
        return False


def drain(limit: int = 20) -> dict[str, int]:
    """지금 보낼 수 있는 것들을 순서대로 전송 시도."""
    ok = fail = 0
    for row in due(limit):
        if try_send(row):
            ok += 1
        else:
            fail += 1
    return {"sent": ok, "failed": fail}


def _loop(interval: float) -> None:
    while not _stop.is_set():
        _stop.wait(interval)
        if _stop.is_set():
            break
        try:
            r = drain()
            if r["sent"]:
                _LOG.info("보류 경보 재전송 성공 %d건(남은 pending %d)", r["sent"], pending_count())
        except Exception:  # noqa: BLE001  재시도 스레드는 죽으면 안 된다
            _LOG.exception("경보 재시도 주기 예외")


def start(interval: float = 5.0) -> threading.Thread:
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(interval,), name="vigent-alert-retry", daemon=True)
    _thread.start()
    p = pending_count()
    _LOG.info("경보 재시도 스레드 시작(주기 %.0fs, 최대 %d회, 백오프 상한 %.0fs) — 이월 pending %d건",
              interval, max_attempts(), backoff_cap_s(), p)
    return _thread


def stop() -> None:
    _stop.set()


def _reset_for_test(path: Path | None = None) -> None:
    """테스트 전용 — DB 경로 교체 + 연결 초기화."""
    global _conn, _DB_PATH
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:  # noqa: BLE001
                pass
        _conn = None
        if path is not None:
            _DB_PATH = path
