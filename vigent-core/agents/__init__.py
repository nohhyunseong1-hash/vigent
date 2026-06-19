"""
agents 패키지 — §3 의 6-에이전트(스텁) 묶음.

build_agents(config) 로 6개를 한 번에 인스턴스화한다.
"""
from __future__ import annotations

from typing import Any

from .analyst import AnalystAgent
from .base import BaseAgent
from .coach import CoachAgent
from .copilot import CopilotAgent
from .dispatcher import DispatcherAgent
from .guard import GuardAgent
from .scribe import ScribeAgent

# 5단계 루프 순서대로
AGENT_CLASSES = [
    GuardAgent,       # 감지
    AnalystAgent,     # 판단
    ScribeAgent,      # 보고서
    CopilotAgent,     # 논문/근거 써치
    DispatcherAgent,  # 피드백·연동
    CoachAgent,       # 코칭(office/sports)
]


def build_agents(config: Any) -> dict[str, BaseAgent]:
    """6-에이전트를 인스턴스화해 {이름: 에이전트} 로 반환."""
    agents = {cls.name: cls(config) for cls in AGENT_CLASSES}
    # Scribe 가 Copilot 근거(법령 인용)를 보고서에 삽입하도록 연결
    if "Scribe" in agents and "Copilot" in agents:
        agents["Scribe"].copilot = agents["Copilot"]
    return agents


__all__ = [
    "BaseAgent", "GuardAgent", "AnalystAgent", "ScribeAgent",
    "CopilotAgent", "DispatcherAgent", "CoachAgent",
    "AGENT_CLASSES", "build_agents",
]
