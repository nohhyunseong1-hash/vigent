"""Dispatcher — [피드백·연동] 텔레그램/이메일/웹훅 경보, 관리자 통보 (§15-4)

- 알림 설정은 config/notify.yaml(UI 작성) 또는 .env 에서 읽는다(매번 신선하게 → 무재시작 반영).
    텔레그램: telegram_token/telegram_chat (env: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)
    이메일:   smtp_host/smtp_port/smtp_user/smtp_pass/email_to
    웹훅:     webhook_url (env: WEBHOOK_URL)
- 비밀키는 코드/채팅에 두지 않는다(규칙 5). notify.yaml 은 gitignore.
- 폴백: 미설정/전송 실패해도 예외로 죽지 않고 로그만 남긴다(절대 저하 없음).

⚠ §8 기능안전 경계: critical 의 'safety_relay_signal' 은 인증 안전회로에 '보조 신호'를
   남기는 로그/훅일 뿐, 비전이 1차 비상정지를 대체하지 않는다.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # requests 없으면 전송은 폴백(로그)만
    requests = None

import tuning

from .base import BaseAgent

_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG = logging.getLogger("vigent.dispatcher")   # [M4-1·M4-3] 전달 실패는 로그로도 드러낸다(토큰 미포함)


def notify_cfg() -> dict[str, Any]:
    """알림 설정 — config/notify.yaml(UI 작성) + .env 폴백. 매번 신선히 읽어 무재시작 반영."""
    cfg: dict[str, Any] = {}
    p = _ROOT / "config" / "notify.yaml"
    if p.exists():
        try:
            import yaml
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise TypeError(f"최상위가 매핑이 아님({type(loaded).__name__})")
            cfg = loaded
            if _PARSE_ERROR["sig"] is not None:          # 고쳐졌으면 상태 해제
                _PARSE_ERROR.update(sig=None, reason=None)
                if _SELFTEST.get("state") == "config_error" and str(_SELFTEST.get("reason", "")).startswith("notify.yaml"):
                    _SELFTEST.update(state="unknown", checked_at=None, reason=None)
        except Exception as ex:  # noqa: BLE001
            # ★[CODE_AUDIT_20260928 #7] 예전엔 cfg={} 로 삼켜 "미설정" 으로만 보였다 — 원인(문법 오류)이 숨는다.
            #   같은 오류는 ERROR 1회만 남기고(매 호출 스팸 방지), 자가시험 상태를 config_error 로 확정해 붉은 배너가 뜨게 한다.
            cfg = {}
            sig = f"{type(ex).__name__}: {str(ex).splitlines()[0][:120]}"
            if _PARSE_ERROR["sig"] != sig:
                _PARSE_ERROR.update(sig=sig, reason=f"notify.yaml 파싱 실패 — {sig}")
                _LOG.error("★config/notify.yaml 파싱 실패 — 알림 설정이 전부 무시된다: %s", sig)
                _SELFTEST.update(state="config_error", checked_at=time.time(), unknown_since=None, reason=_PARSE_ERROR["reason"])

    def pick(key: str, env: str | None = None):
        v = cfg.get(key)
        if v not in (None, ""):
            return str(v).strip()
        if env and os.environ.get(env):
            return os.environ[env].strip()
        return None

    return {
        "telegram_token": pick("telegram_token", "TELEGRAM_BOT_TOKEN"),
        "telegram_chat": pick("telegram_chat", "TELEGRAM_CHAT_ID"),
        "webhook_url": pick("webhook_url", "WEBHOOK_URL"),
        "smtp_host": pick("smtp_host", "SMTP_HOST"),
        "smtp_port": int(pick("smtp_port", "SMTP_PORT") or 587),
        "smtp_user": pick("smtp_user", "SMTP_USER"),
        "smtp_pass": pick("smtp_pass", "SMTP_PASS"),
        "email_to": pick("email_to", "EMAIL_TO"),
    }


_SECRET_PATTERNS = (
    # 텔레그램 봇 토큰: URL **경로**에 토큰이 들어간다(https://api.telegram.org/bot<토큰>/sendMessage).
    #   requests 예외 메시지는 URL 을 통째로 담으므로 그대로 두면 로그·DB(last_error)·
    #   API 응답까지 평문 토큰이 흐른다(2026-08-21 현장 노트북 로그에서 실제 관측).
    (re.compile(r"bot\d+:[A-Za-z0-9_\-]{10,}"), lambda m: "bot<REDACTED>"),
    # Slack/Discord 계열 웹훅: 경로 뒷부분이 곧 비밀값이다. 호스트·경로 앞부분은 남겨
    #   "어느 채널이 실패했는지"는 여전히 진단 가능하게 한다.
    (re.compile(r"(hooks\.slack\.com/services)/[A-Za-z0-9/_\-]+"),
     lambda m: m.group(1) + "/<REDACTED>"),
    (re.compile(r"(discord(?:app)?\.com/api/webhooks)/[A-Za-z0-9/_\-]+"),
     lambda m: m.group(1) + "/<REDACTED>"),
    # 흔한 쿼리스트링 비밀(token=·key=·api_key=·access_token=)
    (re.compile(r"([?&](?:token|key|api_key|access_token)=)[^&\s'\"]+", re.I),
     lambda m: m.group(1) + "<REDACTED>"),
)


def redact_secrets(s: str) -> str:
    """예외 메시지에서 비밀값을 지운다.

    통보 채널의 자격증명은 **URL 안에** 들어가는 경우가 많고, requests 등의 예외 메시지는
    URL 을 그대로 포함한다. 그 문자열이 로그(`logs/vigent.err.log`)·경보 DB(`last_error`)·
    API 응답으로 흘러나가면 토큰이 평문으로 퍼진다. 카메라 자격증명을
    `data/camera_secrets.json` 에만 두고 로그엔 마스킹하는 기존 원칙과 동일하게 맞춘다.
    """
    out = s
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


# [CODE_REVIEW M4-1·M4-3, 2026-09-06] 전달 실패 통계(프로세스 전역) — /health 가 dispatcher.status() 로 읽는다.
#   undeliverable: critical/high 가 발생했는데 원격 채널이 하나도 설정돼 있지 않아 **큐에 넣지 않고 폐기**한 건수
#   last_config_error: 4xx(토큰·chat_id·URL 오류) — 재시도해도 영원히 실패하는 설정 오류. 토큰 값은 절대 담지 않는다.
_PARSE_ERROR: dict[str, Any] = {"sig": None, "reason": None}   # [CODE_AUDIT #7] notify.yaml 파싱 오류(같은 오류는 1회만 로그)
_DELIVERY: dict[str, Any] = {"undeliverable_count": 0, "undeliverable_last_ts": None, "last_config_error": None,
                             "config_error_count": 0, "config_error_first_ts": None,
                             "enqueue_fail": 0, "enqueue_fail_last_ts": None}   # [CODE_AUDIT #1-②] 선기록 실패(재시도 불가) 건수

# ★[F-35, 2026-09-22] 채널 자가시험 상태 — "조용한 실패" 를 없애기 위한 것.
#   실제 사고: 2026-08-21 22:04 을 마지막으로 텔레그램이 401 이 됐는데 **아무도 몰랐다.**
#   09-10 까지 20일간 경보 213건이 사람에게 닿지 않았다(F-35).
#   ★망 오류와 설정 오류를 **구분**한다(2026-09-22 결정):
#     · HTTP 4xx 확정  → state="config_error"  → 붉은 배너(경보가 전달되지 않음)
#     · 망 오류·타임아웃 → state="unknown"      → 10분마다 재시도, 30분 넘게 미확인이면 노란 배너
#     현장 노트북은 Wi-Fi 가 불안정해 기동 직후 실패하는 일이 잦다 — 그걸 '불능' 으로 단정하면 오탐이다.
_SELFTEST: dict[str, Any] = {"state": "unknown", "checked_at": None, "unknown_since": None,
                             "reason": None, "bot": None, "attempts": 0}
SELFTEST_RETRY_SEC = 600.0        # 미확인 상태에서 재시도 간격(10분)
SELFTEST_UNKNOWN_WARN_SEC = 1800.0  # 이 시간을 넘게 미확인이면 노란 배너(30분)
# HTTP 코드 분류: 설정 오류(즉시 dead) vs 재시도(429 는 Retry-After 존중, 5xx·타임아웃·네트워크는 기존 백오프)
_CONFIG_ERROR_CODES = (400, 401, 403, 404)
_TELEGRAM_MAX_TEXT = 4000        # [M4-7] 텔레그램 sendMessage 본문 상한 4096 — 여유 두고 절단


def reset_delivery_stats_for_test() -> None:
    _DELIVERY.update(undeliverable_count=0, undeliverable_last_ts=None, last_config_error=None,
                     config_error_count=0, config_error_first_ts=None, enqueue_fail=0, enqueue_fail_last_ts=None)
    _SELFTEST.update(state="unknown", checked_at=None, unknown_since=None,
                     reason=None, bot=None, attempts=0)
    _PARSE_ERROR.update(sig=None, reason=None)


def note_config_error(channel: str, status: int | None) -> None:
    """[F-35] 설정 오류(4xx)를 기록하고 **첫 발생만** CRITICAL 로 남긴다.

    반복까지 CRITICAL 이면 로그가 폭주해 오히려 묻힌다 — 첫 건만 크게 울리고 이후는 카운트만.
    ★토큰 값은 담지 않는다(채널명·HTTP 코드만).
    """
    first = _DELIVERY.get("config_error_first_ts") is None
    _DELIVERY["last_config_error"] = f"{channel} HTTP {status}"
    _DELIVERY["config_error_count"] = int(_DELIVERY.get("config_error_count", 0)) + 1
    if first:
        _DELIVERY["config_error_first_ts"] = time.time()
        _LOG.critical("★알림 채널 설정 오류(%s HTTP %s) — 경보가 전달되지 않는다. 토큰·chat_id 를 확인하라.",
                      channel, status)
    _SELFTEST.update(state="config_error", checked_at=time.time(),
                     reason=f"{channel} HTTP {status}", unknown_since=None)


def selftest_channels(force: bool = False) -> dict[str, Any]:
    """[F-35] 텔레그램 getMe 로 토큰이 살아 있는지 확인한다. **기동을 막지 않는다.**

    감시는 계속하되 "경보가 안 간다" 를 사람에게 보이게 하는 것이 목적이다.
    반환 state: ok | config_error | unknown | not_configured
      · unknown 은 **망 문제일 수 있다** — 단정하지 않고 10분 뒤 다시 본다.
    """
    now = time.time()
    if not force and _SELFTEST["checked_at"] and _SELFTEST["state"] in ("ok", "config_error"):
        return dict(_SELFTEST)                     # 확정된 상태는 다시 묻지 않는다
    if not force and _SELFTEST["checked_at"] and now - _SELFTEST["checked_at"] < SELFTEST_RETRY_SEC:
        return dict(_SELFTEST)                     # 미확인 재시도 간격 이내
    c = notify_cfg()
    _SELFTEST["attempts"] = int(_SELFTEST.get("attempts", 0)) + 1
    if _PARSE_ERROR["sig"] is not None:                    # [CODE_AUDIT #7] 문법 오류 = 설정 오류(망 문제가 아니다)
        _SELFTEST.update(state="config_error", checked_at=now, unknown_since=None, reason=_PARSE_ERROR["reason"])
        return dict(_SELFTEST)
    if not (c["telegram_token"] and c["telegram_chat"]):
        _SELFTEST.update(state="not_configured", checked_at=now, reason="telegram 미설정", unknown_since=None)
        return dict(_SELFTEST)
    if requests is None:
        _SELFTEST.update(state="unknown", checked_at=now, reason="requests 미설치",
                         unknown_since=_SELFTEST["unknown_since"] or now)
        return dict(_SELFTEST)
    try:
        r = requests.get(f"https://api.telegram.org/bot{c['telegram_token']}/getMe", timeout=8)
        if r.status_code == 200 and (r.json() or {}).get("ok"):
            _SELFTEST.update(state="ok", checked_at=now, unknown_since=None, reason=None,
                             bot=((r.json().get("result") or {}).get("username")))
            _LOG.info("알림 채널 자가시험 통과 — 봇 @%s", _SELFTEST["bot"])
            return dict(_SELFTEST)
        if r.status_code in _CONFIG_ERROR_CODES:
            note_config_error("telegram", r.status_code)      # ★확정 — 붉은 배너
            return dict(_SELFTEST)
        _SELFTEST.update(state="unknown", checked_at=now, reason=f"getMe HTTP {r.status_code}",
                         unknown_since=_SELFTEST["unknown_since"] or now)
    except Exception as ex:  # noqa: BLE001
        # ★망 오류다 — 설정 오류로 단정하지 않는다. 배너도 30분 뒤에야 노란색으로 뜬다.
        _SELFTEST.update(state="unknown", checked_at=now, reason=f"{type(ex).__name__}",
                         unknown_since=_SELFTEST["unknown_since"] or now)
    return dict(_SELFTEST)


def start_selftest_loop() -> None:
    """[F-35] 기동 시 자가시험을 **배경 스레드**로 돌린다. 확정될 때까지 10분마다 재시도.

    ★배경으로 도는 이유(2026-09-22):
      · 기동 경로에서 동기로 부르면 getMe 타임아웃(8초)만큼 **기동이 늦어진다.**
        현장 노트북은 Wi-Fi 가 불안정해 이 지연이 매 부팅마다 생긴다.
      · 기동을 막지 않는다는 원칙과도 맞는다 — 감시가 먼저다.
    결과는 `_SELFTEST` 에 남고 `/health notify` 와 허브 배너가 읽는다.
    ok 또는 config_error 로 **확정되면 루프를 끝낸다.**
    """
    import threading

    # ★테스트·오프라인에서 망을 타지 않게 끌 수 있다(VIGENT_NOTIFY_SELFTEST=0).
    #   2026-09-22: 이 스위치가 없어 전체 테스트가 실제 텔레그램에 접속했다.
    if os.environ.get("VIGENT_NOTIFY_SELFTEST", "1").strip() in ("0", "false", "off"):
        _LOG.info("알림 자가시험 비활성(VIGENT_NOTIFY_SELFTEST=0)")
        _SELFTEST.update(state="disabled", checked_at=time.time(), reason="비활성", unknown_since=None)
        return

    def _loop() -> None:
        while True:
            try:
                st = selftest_channels(force=True)
            except Exception as ex:  # noqa: BLE001  자가시험이 서버를 죽이면 안 된다
                _LOG.warning("알림 자가시험 예외(%s) — 계속한다", type(ex).__name__)
                st = {"state": "unknown"}
            if st.get("state") in ("ok", "config_error", "not_configured"):
                return                                     # 확정 — 더 물을 필요 없다
            time.sleep(SELFTEST_RETRY_SEC)                  # 미확인이면 10분 뒤 다시

    threading.Thread(target=_loop, name="notify-selftest", daemon=True).start()


def selftest_smtp() -> dict[str, Any]:
    """[F-35] SMTP **연결만** 확인한다. ★로그인은 하지 않는다.

    왜 로그인을 안 하나: 기동마다 인증을 시도하면 Gmail 이 반복 실패를 **계정 잠금**으로 볼 수
    있다. 연결·STARTTLS 까지만 보고, 자격증명 오류는 실제 전송 때 `note_config_error("email", …)`
    로 드러난다(붉은 배너·CRITICAL).
    반환 state: ok | unknown | not_configured
    """
    c = notify_cfg()
    if not (c["smtp_host"] and c["smtp_user"] and c["email_to"]):
        return {"state": "not_configured", "reason": "SMTP 미설정"}
    try:
        import smtplib
        with smtplib.SMTP(c["smtp_host"], c["smtp_port"], timeout=8) as s:
            s.ehlo()
            s.starttls()
        return {"state": "ok", "reason": None}
    except Exception as ex:  # noqa: BLE001  망·서버 문제일 수 있다 — 설정 오류로 단정하지 않는다
        return {"state": "unknown", "reason": type(ex).__name__}


def selftest_status() -> dict[str, Any]:
    """/health·배너가 읽는 형태. unknown 이 30분을 넘었는지 여기서 판정한다."""
    s = dict(_SELFTEST)
    s["unknown_too_long"] = bool(
        s["state"] == "unknown" and s.get("unknown_since")
        and time.time() - float(s["unknown_since"]) >= SELFTEST_UNKNOWN_WARN_SEC)
    return s


def _classify_http(channel: str, r: Any) -> dict[str, Any]:
    """requests 응답 → 결과 dict(sent/status + config_error/retry_after)."""
    out: dict[str, Any] = {"channel": channel, "sent": bool(r.ok), "fallback": not r.ok, "status": r.status_code}
    if r.status_code in _CONFIG_ERROR_CODES:
        out["config_error"] = True
        # ★[F-35] 여기까지 오면 **확정된 설정 오류**다 — 첫 건은 CRITICAL, 배너는 붉은색.
        #   예전에는 조용히 dead 로만 쌓여 20일간 아무도 몰랐다.
        note_config_error(channel, r.status_code)
    elif r.status_code == 429:
        ra = (getattr(r, "headers", None) or {}).get("Retry-After")
        try:
            if ra is not None:
                out["retry_after"] = max(0.0, float(ra))
        except (TypeError, ValueError):
            pass
    return out


class DispatcherAgent(BaseAgent):
    name = "Dispatcher"
    role = "연동: 텔레그램/이메일/웹훅 알림, 관리자 통보, (보조)방호 신호 — §8 경계 준수"

    def __init__(self, config: Any):
        super().__init__(config)
        d = (config.raw.get("dispatch", {}) or {})
        self.on_severity = d.get("on_severity", {}) or {
            "critical": ["alarm", "manager_call", "safety_relay_signal"],
            "high": ["alarm", "manager_call"], "medium": ["log"],
        }

    @staticmethod
    def channels_configured(c: dict[str, Any] | None = None) -> bool:
        """[M4-1] 원격 채널(텔레그램·이메일·웹훅) 중 하나라도 설정돼 있는가."""
        c = c or notify_cfg()
        return bool((c["telegram_token"] and c["telegram_chat"])
                    or (c["smtp_host"] and c["smtp_user"] and c["email_to"])
                    or c["webhook_url"])

    def status(self) -> dict[str, Any]:
        c = notify_cfg()
        return {"name": self.name, "role": self.role, "implemented": True,
                "telegram": bool(c["telegram_token"] and c["telegram_chat"]),
                "email": bool(c["smtp_host"] and c["smtp_user"] and c["email_to"]),
                "webhook": bool(c["webhook_url"]),
                "on_severity": self.on_severity,
                # [M4-1·M4-3] 전달 상태 — 값에 토큰·URL 은 없다(채널명·HTTP 코드·시각만)
                "channels_configured": self.channels_configured(c),
                "undeliverable_count": _DELIVERY["undeliverable_count"],
                "undeliverable_last_ts": _DELIVERY["undeliverable_last_ts"],
                "last_config_error": _DELIVERY["last_config_error"],
                # [F-35] 조용한 실패 방지 — 자가시험 상태·설정오류 누계
                "config_error_count": _DELIVERY.get("config_error_count", 0),
                "enqueue_fail": _DELIVERY.get("enqueue_fail", 0),                 # [CODE_AUDIT #1-②]
                "enqueue_fail_last_ts": _DELIVERY.get("enqueue_fail_last_ts"),
                "selftest": selftest_status()}

    def _send_telegram(self, text: str) -> dict[str, Any]:
        c = notify_cfg()
        if not (c["telegram_token"] and c["telegram_chat"]):
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "미설정"}
        if requests is None:
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "requests 미설치"}
        if len(text) > _TELEGRAM_MAX_TEXT:                          # [M4-7] 4096자 초과는 400 → dead 로 흐르던 것
            text = text[:_TELEGRAM_MAX_TEXT - 1] + "…"
        try:
            r = requests.post(f"https://api.telegram.org/bot{c['telegram_token']}/sendMessage",
                              json={"chat_id": c["telegram_chat"], "text": text}, timeout=6)
            return _classify_http("telegram", r)
        except Exception as ex:  # noqa: BLE001
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": redact_secrets(str(ex))}

    def _send_email(self, subject: str, text: str) -> dict[str, Any]:
        c = notify_cfg()
        if not (c["smtp_host"] and c["smtp_user"] and c["email_to"]):
            return {"channel": "email", "sent": False, "fallback": True, "reason": "SMTP 미설정"}
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(text, _charset="utf-8")
            msg["Subject"], msg["From"], msg["To"] = subject, c["smtp_user"], c["email_to"]
            with smtplib.SMTP(c["smtp_host"], c["smtp_port"], timeout=8) as s:
                s.starttls()
                if c["smtp_pass"]:
                    s.login(c["smtp_user"], c["smtp_pass"])
                s.send_message(msg)
            return {"channel": "email", "sent": True, "fallback": False}
        except Exception as ex:  # noqa: BLE001
            out = {"channel": "email", "sent": False, "fallback": True, "reason": redact_secrets(str(ex))}
            if type(ex).__name__ in ("SMTPAuthenticationError", "SMTPRecipientsRefused", "SMTPSenderRefused"):
                out["config_error"] = True                            # [M4-3] 인증·수신자 오류 = 설정 오류
                out["status"] = getattr(ex, "smtp_code", None)
                # ★[F-35] 이메일 설정 오류도 붉은 배너·CRITICAL 경로를 탄다.
                #   예전엔 dict 에 표시만 하고 아무도 보지 않았다 — 텔레그램과 같은 실수를
                #   이메일에서 반복하지 않는다.
                note_config_error("email", out["status"])
            return out

    def _send_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        c = notify_cfg()
        if not c["webhook_url"]:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "미설정"}
        if requests is None:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "requests 미설치"}
        try:
            r = requests.post(c["webhook_url"], json=payload, timeout=6)
            return _classify_http("webhook", r)
        except Exception as ex:  # noqa: BLE001
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": redact_secrets(str(ex))}

    def dispatch(self, level: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """severity 등급에 맞는 채널로 경보. 항상 결과 반환(예외로 죽지 않음).

        [B5] **선기록 후전송**: 보내기 전에 alert_queue 에 pending 으로 남긴다. 전송 직전에
        프로세스가 죽어도 경보가 사라지지 않고, 실패하면 재시도 스레드가 지수 백오프로 이어받는다.
        (이전에는 1회 시도 후 실패하면 그대로 소실됐다 — 순단 중 위험 경보가 영구 유실.)
        """
        row_id = None
        if self._remote_level(level) and not self.channels_configured():
            # ★[M4-1] 원격 채널이 하나도 없으면 큐에 넣지 않는다(재시도해도 영원히 실패 → pending→dead 로 /health 만
            #   degraded 시키던 경로). 대신 **폐기 사실을 센다** — critical/high 가 있었는데 아무 데도 못 갔다는 것은
            #   /health 가 degraded 로 드러내야 한다(개발 PC 의 "미설정 자체"는 경고만).
            import time as _t
            _DELIVERY["undeliverable_count"] += 1
            _DELIVERY["undeliverable_last_ts"] = _t.time()
            _LOG.error("★원격 채널 미설정 — %s 경보를 보낼 곳이 없다(폐기 %d건): %s",
                       level, _DELIVERY["undeliverable_count"], str(message)[:80])
        elif self._queue_enabled(level):
            try:
                import alert_queue
                row_id = alert_queue.enqueue(level, message, meta)
            except Exception as ex:  # noqa: BLE001  큐 실패가 전송 자체를 막으면 안 된다 — 단 **조용히** 는 아니다
                # ★[CODE_AUDIT_20260928 #1-②] 예전엔 row_id=None 으로만 넘어가 즉시 전송까지 실패하면 재시도·데드레터 없이
                #   영구 소실됐고 /health 도 몰랐다. 이제 ERROR 로그 + enqueue_fail 카운터(status()/health notify.enqueue_fail).
                import time as _t
                row_id = None
                _DELIVERY["enqueue_fail"] = int(_DELIVERY.get("enqueue_fail", 0)) + 1
                _DELIVERY["enqueue_fail_last_ts"] = _t.time()
                _LOG.error("★경보 선기록(alert_queue.enqueue) 실패 — 즉시 전송만 시도, 실패하면 재시도 없음(누적 %d): %s: %s",
                           _DELIVERY["enqueue_fail"], type(ex).__name__, redact_secrets(str(ex))[:160])
        res = self._dispatch_now(level, message, meta)
        if row_id is not None:
            try:
                import alert_queue
                if res.get("delivered"):
                    alert_queue.mark_sent(row_id)
                else:
                    alert_queue.mark_failed(row_id, str(res.get("results"))[:300])
            except Exception as ex:  # noqa: BLE001
                _LOG.warning("경보 큐 상태 표시 실패(row %s) — pending 잔류로 재시도 스레드가 중복 발송할 수 있다: %s: %s",
                             row_id, type(ex).__name__, redact_secrets(str(ex))[:120])
        return res

    def _queue_enabled(self, level: str) -> bool:
        """원격 채널을 실제로 쓰는 등급만 큐에 남긴다(log 전용 등급은 재전송 대상이 아니다).

        ★[2026-08-21 수정] 의도는 처음부터 위 문장이었으나 구현이 `("critical","high","mid")`
        하드코딩이었다. 기본 배선의 `on_severity` 에는 **"mid" 가 없어** log 전용으로
        폴백하는데(있는 것은 "medium"), 큐에는 들어가므로 원격 전송이 없는 채 영원히
        `delivered=False` → 10회 재시도 → **데드레터**가 됐다. `/health` 가 pending 때문에
        **degraded** 로 떨어지는 원인이기도 했다(실측: rapid_motion 이 #19 dead·#24 pending).
        → 하드코딩을 버리고 **실제 배선(on_severity)에 원격 동작이 있는지**로 판단한다.
        """
        return self._remote_level(level) and self.channels_configured()   # [M4-1] 채널이 있어야 큐 의미가 있다

    def _remote_level(self, level: str) -> bool:
        """이 등급의 배선(on_severity)에 원격 동작(alarm/manager_call)이 있는가."""
        actions = self.on_severity.get(level, ["log"])
        return any(a in actions for a in ("alarm", "manager_call"))

    def _dispatch_now(self, level: str, message: str, meta: dict[str, Any] | None = None,
                      remote_only: bool = False) -> dict[str, Any]:
        """실제 채널 전송(재시도 없음). 큐가 이 함수를 재시도 때 다시 부른다.

        remote_only ([CODE_REVIEW M4-4], 2026-09-06): **재시도 경로 전용** — 텔레그램·이메일·웹훅만 다시 보내고
        relay(사이렌)·log 는 건드리지 않는다. 예전엔 재시도마다 relay.turn_on 이 다시 불려 채널 장애 시
        critical 1건이 사이렌을 최대 10회 재트리거(ON 연장)했다. 물리 출력은 최초 dispatch 1회로 충분하다.
        """
        actions = self.on_severity.get(level, ["log"])
        results: list[dict[str, Any]] = []
        text = f"[VIGENT-SAFETY] {level.upper()} · {message}"
        if any(a in actions for a in ("alarm", "manager_call")):
            results.append(self._send_telegram(text))
            results.append(self._send_email(f"[VIGENT 안전경보] {level.upper()}", text))
            results.append(self._send_webhook({"level": level, "message": message, "meta": meta or {}}))
        remote = ("telegram", "email", "webhook")
        any_remote = any(r.get("sent") and r["channel"] in remote for r in results)
        # [M4-3] 분류: 원격이 하나도 안 갔고 설정 오류(4xx)가 있으면 config_error(큐는 즉시 dead) · 429 는 retry_after
        extra: dict[str, Any] = {}
        if not any_remote:
            bad = [r for r in results if r.get("config_error")]
            if bad:
                extra["config_error"] = True
                # ★[F-35, 2026-09-22] 여기서 직접 쓰지 않고 note_config_error 를 쓴다.
                #   ① 예전엔 dict 를, note_config_error 는 문자열을 넣어 **타입이 엇갈렸다**
                #      (/health notify.config_error 가 경로에 따라 모양이 달라짐 — 2026-09-22 결함).
                #   ② 그리고 이 경로는 CRITICAL·배너를 타지 않아 **조용히 dead 로만 쌓였다.**
                #      20일간 213건이 그렇게 사라졌다.
                note_config_error(bad[0]["channel"], bad[0].get("status"))
            ras = [float(r["retry_after"]) for r in results if r.get("retry_after") is not None]
            if ras:
                extra["retry_after"] = max(ras)
        if remote_only:
            return {"level": level, "actions": actions, "results": results,
                    "delivered": any_remote, "fallback": not any_remote, "remote_only": True, **extra}
        if "safety_relay_signal" in actions:
            # [P3a] 실제 물리 출력(네트워크 릴레이) — 이전에는 로그 항목만 추가하고 sent:True 를
            #   반환해 "경보가 울렸다"고 표시되는데 아무 소리도 안 나는 상태였다(감사 🟠C7).
            #   relay.enabled=false(기본)면 기존처럼 로그 신호만 남긴다.
            try:
                import relay
                if relay.enabled():
                    results.append(relay.turn_on(message))
                else:
                    results.append({"channel": "safety_relay_signal", "sent": True,
                                    "note": "§8 보조 신호 로그(릴레이 비활성 — 물리 출력 없음)"})
            except Exception as ex:  # noqa: BLE001  릴레이 실패가 다른 채널을 막지 않는다
                results.append({"channel": "relay", "sent": False, "reason": str(ex)[:120]})
        results.append({"channel": "log", "sent": True, "text": text})
        return {"level": level, "actions": actions, "results": results,
                "delivered": any_remote, "fallback": not any_remote, **extra}

    def relay(self, event: str = "guard_bypass", meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """§8 '보조 방호신호'. 인증 안전회로에 추가 신호만. 1차 비상정지 대체 아님(§8.1).

        ★[2026-08-21] 경보 문구를 **현장별로 바꿀 수 있게** 설정으로 뺐다. 기본값도
        "프레스/전단기" 를 빼고 **위험기계**로 일반화했다 — 지게차 실습장 같은 다른 현장에서
        프레스 문구가 폰에 뜨면 담당자가 혼란스럽고 시연 설득력도 떨어진다(학원 준비 중 발견).
        현장 문구는 `config/tuning.yaml` 의 `alerts.guard_bypass_text` 로 지정한다.
        """
        text = str(tuning.val("alerts", "guard_bypass_text",
                              "위험기계 방호구역 신체 진입 감지")).strip()
        alert = self.dispatch("critical", f"{event}: {text}", meta)
        return {"relay": "auxiliary_signal", "event": event, "is_primary_safety": False,
                "boundary": "§8.1 — 비전은 보조·감시 계층. 1차 정지는 인증 하드웨어 책임.",
                "delivered": alert["delivered"], "alert": alert}

    def run(self, level: str = "medium", message: str = "", **kw) -> dict[str, Any]:
        return self.dispatch(level, message, kw.get("meta"))
