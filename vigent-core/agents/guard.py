"""Guard — [감지] 실시간 탐지·추적·이벤트 발생 (스텁)"""
from __future__ import annotations

from .base import BaseAgent


class GuardAgent(BaseAgent):
    name = "Guard"
    role = "감지: 실시간 탐지·추적·이벤트 스트림 생성"
