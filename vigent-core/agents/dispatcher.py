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

import os
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # requests 없으면 전송은 폴백(로그)만
    requests = None

from .base import BaseAgent

_ROOT = Path(__file__).resolve().parent.parent.parent


def notify_cfg() -> dict[str, Any]:
    """알림 설정 — config/notify.yaml(UI 작성) + .env 폴백. 매번 신선히 읽어 무재시작 반영."""
    cfg: dict[str, Any] = {}
    p = _ROOT / "config" / "notify.yaml"
    if p.exists():
        try:
            import yaml
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            cfg = {}

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

    def status(self) -> dict[str, Any]:
        c = notify_cfg()
        return {"name": self.name, "role": self.role, "implemented": True,
                "telegram": bool(c["telegram_token"] and c["telegram_chat"]),
                "email": bool(c["smtp_host"] and c["smtp_user"] and c["email_to"]),
                "webhook": bool(c["webhook_url"]),
                "on_severity": self.on_severity}

    def _send_telegram(self, text: str) -> dict[str, Any]:
        c = notify_cfg()
        if not (c["telegram_token"] and c["telegram_chat"]):
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "미설정"}
        if requests is None:
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "requests 미설치"}
        try:
            r = requests.post(f"https://api.telegram.org/bot{c['telegram_token']}/sendMessage",
                              json={"chat_id": c["telegram_chat"], "text": text}, timeout=6)
            return {"channel": "telegram", "sent": r.ok, "fallback": not r.ok, "status": r.status_code}
        except Exception as ex:  # noqa: BLE001
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": str(ex)}

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
            return {"channel": "email", "sent": False, "fallback": True, "reason": str(ex)}

    def _send_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        c = notify_cfg()
        if not c["webhook_url"]:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "미설정"}
        if requests is None:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "requests 미설치"}
        try:
            r = requests.post(c["webhook_url"], json=payload, timeout=6)
            return {"channel": "webhook", "sent": r.ok, "fallback": not r.ok, "status": r.status_code}
        except Exception as ex:  # noqa: BLE001
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": str(ex)}

    def dispatch(self, level: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """severity 등급에 맞는 채널로 경보. 항상 결과 반환(예외로 죽지 않음)."""
        actions = self.on_severity.get(level, ["log"])
        results: list[dict[str, Any]] = []
        text = f"[VIGENT-SAFETY] {level.upper()} · {message}"
        if any(a in actions for a in ("alarm", "manager_call")):
            results.append(self._send_telegram(text))
            results.append(self._send_email(f"[VIGENT 안전경보] {level.upper()}", text))
            results.append(self._send_webhook({"level": level, "message": message, "meta": meta or {}}))
        if "safety_relay_signal" in actions:
            results.append({"channel": "safety_relay_signal", "sent": True,
                            "note": "§8 보조 신호 로그(인증 회로 대체 아님)"})
        results.append({"channel": "log", "sent": True, "text": text})
        remote = ("telegram", "email", "webhook")
        any_remote = any(r.get("sent") and r["channel"] in remote for r in results)
        return {"level": level, "actions": actions, "results": results,
                "delivered": any_remote, "fallback": not any_remote}

    def relay(self, event: str = "guard_bypass", meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """프레스/전단기 §8 '보조 방호신호'. 인증 안전회로에 추가 신호만. 1차 비상정지 대체 아님(§8.1)."""
        alert = self.dispatch("critical", f"{event}: 프레스/전단기 위험구역 신체 진입 감지", meta)
        return {"relay": "auxiliary_signal", "event": event, "is_primary_safety": False,
                "boundary": "§8.1 — 비전은 보조·감시 계층. 1차 정지는 인증 하드웨어 책임.",
                "delivered": alert["delivered"], "alert": alert}

    def run(self, level: str = "medium", message: str = "", **kw) -> dict[str, Any]:
        return self.dispatch(level, message, kw.get("meta"))
