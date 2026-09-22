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
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

import tuning
import vlog

_LOG = vlog.get("vigent.alert_queue")
_ROOT = Path(__file__).resolve().parent.parent
# [4단계 ④, 2026-09-06] 큐 DB 경로를 env 로 바꿀 수 있게 — 테스트·격리 실행이 운영 DB 를 건드리지
#   않도록(실측: 테스트 스위트가 운영 큐에 시험 행을 남겼다, CODE_REVIEW.md §4-0). 기본값 불변.
_DB_PATH = Path(os.environ.get("VIGENT_ALERT_DB") or (_ROOT / "data" / "alert_queue.db"))

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
            # [M4-2] dead 시각 — "최근 1시간 데드레터" 집계(/health degraded 판정)용. 구 DB 는 열을 추가한다.
            cols = {r[1] for r in _conn.execute("PRAGMA table_info(alerts)")}
            if "dead_at" not in cols:
                _conn.execute("ALTER TABLE alerts ADD COLUMN dead_at REAL")
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
    _auto_pin_sent(row_id)


# [CODE_REVIEW M6-10, 대표 결정 2026-09-06] 자동 보존: critical/high 경보가 **실제 발송(sent)** 된 사건의 증거 JPEG 와
#   그날 인식 로그(events_YYYYMMDD.jsonl)를 자동 pin(사유 "alert:<id>") — 사람이 unpin 하기 전까지 30일 스윕 제외.
#   발송된 경보는 "사건"이므로 증거가 정책 일수에 지워지면 안 된다. tuning retention.auto_pin_sent_alerts(기본 true).
_AUTO_PIN_LEVELS = ("critical", "high")


def _auto_pin_sent(row_id: int) -> None:
    try:
        if not bool(tuning.val("retention", "auto_pin_sent_alerts", True)):
            return
        db = _db()
        with _lock:
            row = db.execute("SELECT level, meta, created_at FROM alerts WHERE id=?", (row_id,)).fetchone()
        if not row or str(row[0]).lower() not in _AUTO_PIN_LEVELS:
            return
        meta = json.loads(row[1] or "{}")
        import datetime as _dt

        import data_engine
        reason = f"alert:{row_id}"
        ev = meta.get("evidence")
        if ev:
            data_engine.pin_evidence(str(ev), reason=reason)
        ts = float(meta.get("ts") or row[2] or time.time())
        day = _dt.datetime.fromtimestamp(ts, data_engine.KST).strftime("%Y%m%d")
        data_engine.pin_evidence(f"data/recognition/events_{day}.jsonl", reason=reason)
    except Exception:  # noqa: BLE001  자동 pin 실패가 전송 기록을 막으면 안 된다
        _LOG.warning("발송 경보 자동 pin 실패 id=%s", row_id, exc_info=True)


def mark_failed(row_id: int, err: str, delay: float | None = None) -> None:
    """실패 기록 + 다음 시도 시각 예약. 최대 횟수 초과면 dead.

    delay ([M4-3]): 서버가 준 Retry-After(초). 없으면 기존 지수 백오프(1,2,4,…상한).
    """
    db = _db()
    with _lock:
        row = db.execute("SELECT attempts FROM alerts WHERE id=?", (row_id,)).fetchone()
        attempts = (row[0] if row else 0) + 1
        if attempts >= max_attempts():
            db.execute("UPDATE alerts SET status=?, attempts=?, last_error=?, dead_at=? WHERE id=?",
                       (DEAD, attempts, err[:500], time.time(), row_id))
            _LOG.error("경보 데드레터(재시도 %d회 초과) id=%s: %s", attempts, row_id, err[:200])
            dead = True
        else:
            if delay is None:
                delay = min(2.0 ** (attempts - 1), backoff_cap_s())
            db.execute("UPDATE alerts SET attempts=?, next_attempt_at=?, last_error=? WHERE id=?",
                       (attempts, time.time() + float(delay), err[:500], row_id))
            dead = False
        db.commit()
    if dead:
        _on_dead(row_id)


def mark_dead(row_id: int, err: str) -> None:
    """[M4-3] 설정 오류(4xx) 등 재시도가 무의미한 실패 → 즉시 dead(시도 횟수는 +1 기록)."""
    db = _db()
    with _lock:
        row = db.execute("SELECT attempts FROM alerts WHERE id=?", (row_id,)).fetchone()
        attempts = (row[0] if row else 0) + 1
        db.execute("UPDATE alerts SET status=?, attempts=?, last_error=?, dead_at=? WHERE id=?",
                   (DEAD, attempts, err[:500], time.time(), row_id))
        db.commit()
    _LOG.error("경보 데드레터(설정 오류 — 재시도 안 함) id=%s: %s", row_id, err[:200])
    _on_dead(row_id)


# [M4-2] 데드레터 요약 통보 — 1시간 1회, 살아 있는 채널로(alert_notify → 게이트 → dispatcher). 요약 자신은 재귀 금지.
_DEAD_NOTIFY_EVERY_S = 3600.0
_last_dead_notify = 0.0


def _reset_dead_notify_for_test() -> None:
    global _last_dead_notify
    _last_dead_notify = 0.0


def _submit_dead_summary(dead_1h: int, dead_total: int, sample: str) -> None:
    """요약 통보 제출(별도 함수 — 테스트에서 대역으로 바꾼다)."""
    import alert_notify
    alert_notify.submit(cam="system", rule="alert_dead", level="high",
                        message=f"[시스템] 경보 전송 실패로 폐기(데드레터) 최근 1시간 {dead_1h}건(누적 {dead_total}건) — "
                                f"채널 설정·네트워크 확인 필요. 예: {sample[:80]}",
                        meta={"dead_1h": dead_1h, "dead_total": dead_total})


def _on_dead(row_id: int) -> None:
    """dead 발생 시: 자기 자신(alert_dead)이 아니고 마지막 통보 후 1시간 지났으면 요약 통보."""
    global _last_dead_notify
    try:
        db = _db()
        with _lock:
            row = db.execute("SELECT message, meta FROM alerts WHERE id=?", (row_id,)).fetchone()
        meta = json.loads((row[1] if row else None) or "{}")
        if meta.get("rule") == "alert_dead":
            return                                   # 요약 통보가 죽어도 또 요약하지 않는다(재귀 차단)
        now = time.time()
        if now - _last_dead_notify < _DEAD_NOTIFY_EVERY_S:
            return
        _last_dead_notify = now
        c = counts()
        _submit_dead_summary(int(c.get("dead_1h", 0)), int(c.get("dead", 0)), str(row[0] if row else ""))
    except Exception:  # noqa: BLE001  통보 실패가 큐 처리를 막으면 안 된다
        _LOG.exception("데드레터 요약 통보 실패")


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
    with _lock:   # [M4-2] 최근 1시간 데드레터 — /health degraded 판정 입력
        c["dead_1h"] = int(db.execute("SELECT COUNT(*) FROM alerts WHERE status=? AND dead_at>?",
                                      (DEAD, time.time() - 3600.0)).fetchone()[0])
    # ★[F-35] 마지막 성공 전송 시각 — "언제부터 안 가고 있나" 를 한 눈에 본다.
    #   실제 사고: 2026-08-21 22:04 이후 20일간 한 건도 못 갔는데 이 값이 없어 아무도 몰랐다.
    with _lock:
        row = db.execute("SELECT MAX(sent_at) FROM alerts WHERE status=?", (SENT,)).fetchone()
    c["last_success_ts"] = float(row[0]) if row and row[0] else None
    return c


def pending_count() -> int:
    return counts().get(PENDING, 0)


def prune(days: int = 30, execute: bool = True) -> dict[str, Any]:
    """[CODE_REVIEW M6-4] sent/dead 행을 days 지나면 지운다(pending 은 절대 안 지움). 예전엔 삭제 경로가 없어 영구 누적.
    last_error 가 config_error 인 **최신 1건**은 진단 근거로 남긴다. execute=False 면 후보만 센다."""
    db = _db()
    cutoff = time.time() - float(days) * 86400.0
    with _lock:
        keep_row = db.execute(
            "SELECT id FROM alerts WHERE status=? AND last_error LIKE 'config_error%' ORDER BY id DESC LIMIT 1",
            (DEAD,)).fetchone()
        keep_id = int(keep_row[0]) if keep_row else -1
        cands = db.execute(
            "SELECT COUNT(*) FROM alerts WHERE status IN (?, ?) AND created_at < ? AND id != ?",
            (SENT, DEAD, cutoff, keep_id)).fetchone()[0]
        deleted = 0
        if execute and cands:
            deleted = db.execute(
                "DELETE FROM alerts WHERE status IN (?, ?) AND created_at < ? AND id != ?",
                (SENT, DEAD, cutoff, keep_id)).rowcount
            db.commit()
    return {"days": int(days), "candidates": int(cands), "deleted": int(deleted),
            "kept_config_error": keep_id if keep_id >= 0 else None}


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
        if res.get("config_error"):                  # [M4-3] 4xx 설정 오류 — 재시도해도 영원히 실패 → 즉시 dead
            mark_dead(row["id"], "config_error: " + str(res.get("results"))[:280])
            return False
        ra = res.get("retry_after")                  # [M4-3] 429 — 서버가 준 Retry-After 존중
        mark_failed(row["id"], str(res.get("results"))[:300],
                    delay=float(ra) if ra is not None else None)
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


def stop(join_s: float = 3.0) -> None:
    """재시도 스레드 정지. ★플래그만 세우지 말고 **실제로 끝날 때까지 기다린다.**

    예전에는 `_stop.set()` 만 했다. 그러면 루프가 다음 주기(기본 5초)까지 계속 돌면서
    `drain()` 으로 **그 시점의 전역 sender** 에 전송한다. 테스트에서는 다른 테스트가
    설치한 채널로 경보가 새어 들어가 **타이밍에 따라 실패**했다(셔플 10회 중 4회 —
    test_dead_is_not_retried 등). 운영에서도 종료 중 전송이 이어지는 것은 바람직하지 않다.
    """
    global _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=join_s)
        if t.is_alive():
            _LOG.warning("재시도 스레드가 %.0f초 안에 끝나지 않았다 — 참조를 유지한다"
                         "(중복 기동 방지)", join_s)
            return
    _thread = None


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
