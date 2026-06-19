"""Coach — [코칭 특화] office/sports 실시간 교정·음성 코칭 (스텁)

safety 테마에서는 비활성. office(텍스트)·sports(음성)에서 활성화된다.
"""
from __future__ import annotations

from .base import BaseAgent


class CoachAgent(BaseAgent):
    name = "Coach"
    role = "코칭: office/sports 실시간 교정·음성 피드백(safety 미사용)"
