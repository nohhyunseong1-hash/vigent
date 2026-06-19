"""Dispatcher — [피드백·연동] 알림·관리자 통보·(보조)방호 신호 (스텁)

⚠ §8 기능안전 경계: 비상정지 연동은 인증 안전회로에 '보조 신호'만 제공한다.
   비전 단독으로 SIL/PL 안전기능을 대체하지 않는다.
"""
from __future__ import annotations

from .base import BaseAgent


class DispatcherAgent(BaseAgent):
    name = "Dispatcher"
    role = "연동: 텔레그램/웹훅 알림, 관리자 통보, (보조)방호 신호 — §8 경계 준수"
