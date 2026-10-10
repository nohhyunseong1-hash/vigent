"""notify_heartbeat.py — [F-35] 하루 1회 "알림 채널 살아 있음" 통보.

★왜 있는가
  조용한 실패의 반대다 — **정상일 때도 말을 하게 한다.**
  2026-08-21~09-10 실제 사고: 텔레그램이 401 이 된 뒤 20일간 경보 213건이 못 갔는데
  **아무 신호도 없어서 아무도 몰랐다.** 배너·CRITICAL 은 사람이 화면·로그를 볼 때만 보인다.
  하루 한 번 오는 메시지가 **안 오면** 사람이 알아차린다 — 그것이 이 기능의 전부다.

설정: `config/tuning.yaml`
    notify:
      heartbeat_at: "09:00"      # ★미설정이면 **끈다**(기본 동작 무변경)

★이 통보는 경보 큐를 타지 않는다(경보가 아니다). 채널로 직접 보낸다.
★실패해도 서버를 죽이지 않는다 — 폴백은 로그.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import threading
import time
from typing import Any

import tuning

_LOG = logging.getLogger("vigent.heartbeat")
_STATE: dict[str, Any] = {"last_sent_date": None, "last_result": None, "enabled": None,
                          "last_sent_ts": None, "last_ok": None, "last_attempt_ts": None}
_CHECK_INTERVAL_SEC = 30.0        # 분 단위 시각을 놓치지 않을 만큼만 자주 본다


def _retry_sec() -> float:
    """[2단계 A-1] 실패 시 재시도 간격(기본 600초). 예전엔 성공·실패 무관하게 날짜 도장을
    찍어 그날 재시도가 없었다 — 이제 도장은 **성공한 날만** 찍고, 실패는 이 간격으로
    재시도한다(30초 폭주 방지와 그날 포기 사이의 절충)."""
    return max(60.0, float(tuning.val("notify", "heartbeat_retry_s", 600)))


def configured_at() -> str | None:
    """설정된 발송 시각("HH:MM") 또는 None(=끔)."""
    v = tuning.val("notify", "heartbeat_at", None, env="VIGENT_HEARTBEAT_AT")
    if v in (None, "", False):
        return None
    s = str(v).strip()
    try:
        h, m = s.split(":")
        if 0 <= int(h) <= 23 and 0 <= int(m) <= 59:
            return f"{int(h):02d}:{int(m):02d}"
    except (ValueError, AttributeError):
        pass
    _LOG.warning("heartbeat_at 형식이 잘못됐다(%r) — 끈 것으로 본다. 'HH:MM' 이어야 한다.", v)
    return None


def compose_message() -> str:
    """메시지 본문. 오늘 경보 수와 데드레터 누계를 담는다."""
    sent_today = dead = 0
    try:
        import alert_queue
        c = alert_queue.counts()
        dead = int(c.get("dead", 0) or 0)
        sent_today = _sent_today()
    except Exception as ex:  # noqa: BLE001  집계 실패가 통보를 막으면 안 된다
        _LOG.warning("heartbeat 집계 실패(%s) — 0 으로 보낸다", type(ex).__name__)
    return f"VIGENT 알림 채널 정상 · 오늘 경보 {sent_today}건 · 데드레터 {dead}건"


def _sent_today() -> int:
    import sqlite3
    from pathlib import Path
    db = Path(os.environ.get("VIGENT_ALERT_DB") or
              (Path(__file__).resolve().parent.parent / "data" / "alert_queue.db"))
    if not db.exists():
        return 0
    start = _dt.datetime.combine(_dt.date.today(), _dt.time.min).timestamp()
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT COUNT(*) FROM alerts WHERE status='sent' AND sent_at>=?", (start,)).fetchone()
        return int(row[0]) if row else 0
    finally:
        con.close()


def _send_all_channels(text: str) -> dict[str, Any]:
    """[F-35] 설정된 **원격 채널 전부**로 보낸다(텔레그램 + 이메일).

    ★왜 전부인가: heartbeat 의 목적은 "채널이 살아 있음" 을 확인하는 것이다.
      텔레그램만 보내면 **이메일이 죽어도 모른다** — 정작 텔레그램이 죽었을 때 쓰려고
      만든 두 번째 채널인데 그 상태를 확인할 길이 없어진다.
    ★이메일 실패도 note_config_error 경로를 탄다(_send_email 안에서 처리).
    반환: {"sent": 하나라도 성공, "channels": {...}} — 성공 판정은 경보와 같은 규칙.
    """
    # [2단계 A-1] STATE 는 **테마명으로 키**된다(app_state.load_theme: STATE[theme]=bundle).
    #   예전 코드는 존재하지 않는 "bundle" 키를 읽어 agent 가 항상 None → heartbeat 가
    #   한 번도 발송된 적이 없었다(테스트도 같은 오가정을 공유해 못 잡음). health_watch 와
    #   동일하게 기본 테마로 찾는다.
    from app_state import DEFAULT_THEME, STATE
    agent = ((STATE.get(DEFAULT_THEME) or {}).get("agents") or {}).get("Dispatcher")
    if agent is None:
        return {"sent": False, "reason": "에이전트 없음"}
    out: dict[str, Any] = {}
    cfg = {}
    try:
        from agents.dispatcher import notify_cfg
        cfg = notify_cfg()
    except Exception:  # noqa: BLE001
        pass
    if cfg.get("telegram_token") and cfg.get("telegram_chat"):
        out["telegram"] = agent._send_telegram(text)
    if cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("email_to"):
        out["email"] = agent._send_email("[VIGENT] 알림 채널 점검", text)
    if not out:
        return {"sent": False, "reason": "설정된 원격 채널 없음"}
    ok = [k for k, v in out.items() if v.get("sent")]
    bad = [f"{k}:{v.get('status') or v.get('reason') or '실패'}" for k, v in out.items() if not v.get("sent")]
    return {"sent": bool(ok), "channels": out, "sent_channels": ok, "failed_channels": bad,
            "reason": ("; ".join(bad) if bad else None)}


def maybe_send(now: _dt.datetime | None = None, sender: Any = None) -> dict[str, Any]:
    """지정 시각이 됐고 **오늘 아직 안 보냈으면** 1회 보낸다.

    반환: {"sent": bool, "reason": str}
    ★하루 1회를 `last_sent_date` 로 보장한다 — 30초마다 깨어나도 중복 발송하지 않는다.
    """
    at = configured_at()
    if at is None:
        return {"sent": False, "reason": "미설정(끔)"}
    now = now or _dt.datetime.now()
    today = now.date().isoformat()
    if _STATE["last_sent_date"] == today:
        return {"sent": False, "reason": "오늘 이미 보냄"}
    hh, mm = (int(x) for x in at.split(":"))
    if (now.hour, now.minute) < (hh, mm):
        return {"sent": False, "reason": f"아직 {at} 전"}
    # [2단계 A-1] 직전 시도가 실패였으면 재시도 간격만큼 기다렸다 다시 시도(폭주 방지)
    la = _STATE.get("last_attempt_ts")
    if la is not None and (now.timestamp() - float(la)) < _retry_sec():
        return {"sent": False, "reason": f"실패 재시도 대기({int(_retry_sec())}초 간격)"}
    text = compose_message()
    try:
        if sender is None:
            res = _send_all_channels(text)
        else:
            res = sender(text)
    except Exception as ex:  # noqa: BLE001  통보 실패가 서버를 죽이면 안 된다
        res = {"sent": False, "reason": type(ex).__name__}
    _STATE["last_attempt_ts"] = now.timestamp()
    if res.get("sent"):
        _STATE["last_sent_date"] = today      # ★[A-1] 도장은 **성공한 날만** — 실패는 그날 안에 재시도된다
    _STATE["last_result"] = res
    # ★[F-35] 전송 시각·성공 여부를 남긴다 — /health 가 "heartbeat 도 실패했다" 를 말할 수 있게.
    #   heartbeat 가 조용히 실패하면 '침묵이 신호' 라는 설계 자체가 무너진다.
    _STATE["last_sent_ts"] = time.time()
    _STATE["last_ok"] = bool(res.get("sent"))
    if res.get("sent"):
        _LOG.info("알림 채널 heartbeat 전송: %s", text)
    else:
        _LOG.warning("알림 채널 heartbeat 전송 실패(%s) — 채널을 확인하라", res.get("reason") or res.get("status"))
    return {"sent": bool(res.get("sent")), "reason": str(res.get("reason") or res.get("status") or "")}


def start() -> None:
    """배경 스레드로 발송 시각을 지켜본다. 미설정이면 스레드를 띄우지 않는다."""
    at = configured_at()
    _STATE["enabled"] = at is not None
    if at is None:
        _LOG.info("알림 heartbeat 비활성(notify.heartbeat_at 미설정)")
        return

    def _loop() -> None:
        while True:
            try:
                maybe_send()
            except Exception as ex:  # noqa: BLE001
                _LOG.warning("heartbeat 루프 예외(%s) — 계속한다", type(ex).__name__)
            time.sleep(_CHECK_INTERVAL_SEC)

    threading.Thread(target=_loop, name="notify-heartbeat", daemon=True).start()
    _LOG.info("알림 heartbeat 활성 — 매일 %s 에 전송", at)


def status() -> dict[str, Any]:
    return {"enabled": bool(_STATE["enabled"]), "at": configured_at(),
            "last_sent_date": _STATE["last_sent_date"], "last_result": _STATE["last_result"],
            "last_sent_ts": _STATE["last_sent_ts"], "last_ok": _STATE["last_ok"]}


def reset_for_test() -> None:
    _STATE.update(last_sent_date=None, last_result=None, enabled=None,
                  last_sent_ts=None, last_ok=None, last_attempt_ts=None)
