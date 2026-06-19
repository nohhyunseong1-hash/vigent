"""Dispatcher — [피드백·연동] 텔레그램/웹훅 경보, 관리자 통보 (§15-4)

- 비밀키는 코드/채팅에 두지 않는다. .env 에서 환경변수로 읽는다(규칙 5).
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_URL
- vision.yaml 의 dispatch.on_severity 에 따라 채널을 고른다.
- 폴백: 키가 없거나 전송 실패해도 예외로 죽지 않고 로그만 남긴다(절대 저하 없음).

⚠ §8 기능안전 경계: severity=critical 의 'safety_relay_signal' 은 인증 안전회로에
   '보조 신호'를 남기는 로그/훅일 뿐, 비전이 1차 비상정지를 대체하지 않는다.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import requests
except ImportError:  # requests 없으면 전송은 폴백(로그)만
    requests = None

from .base import BaseAgent


class DispatcherAgent(BaseAgent):
    name = "Dispatcher"
    role = "연동: 텔레그램/웹훅 알림, 관리자 통보, (보조)방호 신호 — §8 경계 준수"

    def __init__(self, config: Any):
        super().__init__(config)
        # vision.yaml dispatch.on_severity (없으면 안전한 기본값)
        d = (config.raw.get("dispatch", {}) or {})
        self.on_severity = d.get("on_severity", {}) or {
            "critical": ["alarm", "manager_call", "safety_relay_signal"],
            "high": ["alarm", "manager_call"], "medium": ["log"],
        }

    # ── 비밀키는 호출 시점에 환경변수에서 읽는다(코드에 박지 않음) ──
    @staticmethod
    def _env(key: str) -> str | None:
        v = os.environ.get(key)
        return v.strip() if v else None

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "telegram": bool(self._env("TELEGRAM_BOT_TOKEN") and self._env("TELEGRAM_CHAT_ID")),
                "webhook": bool(self._env("WEBHOOK_URL")),
                "on_severity": self.on_severity}

    def _send_telegram(self, text: str) -> dict[str, Any]:
        token, chat = self._env("TELEGRAM_BOT_TOKEN"), self._env("TELEGRAM_CHAT_ID")
        if not (token and chat):
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "키 없음(.env 미설정)"}
        if requests is None:
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": "requests 미설치"}
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": text}, timeout=5)
            return {"channel": "telegram", "sent": r.ok, "fallback": not r.ok, "status": r.status_code}
        except Exception as ex:  # noqa: BLE001  전송 실패해도 죽지 않는다
            return {"channel": "telegram", "sent": False, "fallback": True, "reason": str(ex)}

    def _send_webhook(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._env("WEBHOOK_URL")
        if not url:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "URL 없음(.env 미설정)"}
        if requests is None:
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": "requests 미설치"}
        try:
            r = requests.post(url, json=payload, timeout=5)
            return {"channel": "webhook", "sent": r.ok, "fallback": not r.ok, "status": r.status_code}
        except Exception as ex:  # noqa: BLE001
            return {"channel": "webhook", "sent": False, "fallback": True, "reason": str(ex)}

    def dispatch(self, level: str, message: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """severity 등급에 맞는 채널로 경보. 항상 결과를 반환(예외로 죽지 않음)."""
        actions = self.on_severity.get(level, ["log"])
        results: list[dict[str, Any]] = []
        text = f"[VIGENT-SAFETY] {level.upper()} · {message}"

        # alarm/manager_call → 텔레그램 + 웹훅으로 통보
        if any(a in actions for a in ("alarm", "manager_call")):
            results.append(self._send_telegram(text))
            results.append(self._send_webhook({"level": level, "message": message, "meta": meta or {}}))
        # safety_relay_signal → §8 보조 신호(로그/플래그만; 실제 비상정지 아님)
        if "safety_relay_signal" in actions:
            results.append({"channel": "safety_relay_signal", "sent": True, "note": "§8 보조 신호 로그(인증 회로 대체 아님)"})
        # log(medium 등) 는 항상 기록
        results.append({"channel": "log", "sent": True, "text": text})

        any_remote = any(r.get("sent") and r["channel"] in ("telegram", "webhook") for r in results)
        return {"level": level, "actions": actions, "results": results,
                "delivered": any_remote, "fallback": not any_remote}

    def run(self, level: str = "medium", message: str = "", **kw) -> dict[str, Any]:
        return self.dispatch(level, message, kw.get("meta"))
