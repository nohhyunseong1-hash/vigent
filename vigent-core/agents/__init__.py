"""
agents 패키지 — §3 의 6-에이전트(스텁) 묶음.

build_agents(config) 로 6개를 한 번에 인스턴스화한다.

★[감사, 2026-09-06 범위 결정] 이 패키지는 두 성격이 섞여 있다:
  · 감시 서버 코어 = Guard(검출·추적) · Dispatcher(통보)  — 없으면 서버가 성립하지 않는다(필수 import).
  · LLM 에이전트  = Analyst · Scribe · Copilot · SafetyManager — 위험성평가·질의응답(선택 모듈).
  코어가 LLM 에이전트 모듈 없이도 import·기동되도록 후자는 **선택 import** 로 둔다: 모듈이 없거나
  깨져 있으면 그 클래스만 빠지고(build_agents 결과에 그 이름이 없음) 서버는 뜬다. 해당 라우트는
  `bundle["agents"].get("Scribe")` 가 None → 503 으로 응답한다. 실증: 4모듈 import 차단 실험에서
  app_state·worker·main import 성공.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent
from .dispatcher import DispatcherAgent
from .guard import GuardAgent

_log = logging.getLogger("vigent.agents")

# 5단계 루프 순서대로. 코어 2종은 필수, LLM 에이전트 4종은 선택(없으면 건너뜀).
AGENT_CLASSES: list[type[BaseAgent]] = [GuardAgent]   # 감지


def _optional(modname: str, clsname: str) -> type[BaseAgent] | None:
    """LLM 에이전트 모듈을 선택 import. 실패해도 코어는 죽지 않는다(경고 1줄)."""
    try:
        mod = __import__(f"{__name__}.{modname}", fromlist=[clsname])
        return getattr(mod, clsname)
    except Exception as ex:  # noqa: BLE001  모듈 부재·의존성 오류 전부 '기능 없음'으로 취급
        _log.warning("LLM 에이전트 %s 미로드(%s: %s) — 코어는 계속 기동", clsname, type(ex).__name__, ex)
        return None


AnalystAgent = _optional("analyst", "AnalystAgent")            # 판단
ScribeAgent = _optional("scribe", "ScribeAgent")               # 보고서
CopilotAgent = _optional("copilot", "CopilotAgent")            # 논문/근거 써치
SafetyManagerAgent = _optional("safety_manager", "SafetyManagerAgent")  # 반자동 오케스트레이터(권장만)

for _cls in (AnalystAgent, ScribeAgent, CopilotAgent):
    if _cls is not None:
        AGENT_CLASSES.append(_cls)
AGENT_CLASSES.append(DispatcherAgent)   # 피드백·연동(코어)
if SafetyManagerAgent is not None:
    AGENT_CLASSES.append(SafetyManagerAgent)
# Coach(코칭 특화, office/sports 전용)는 [Z-3, 2026-08-10] office/sports 삭제로 함께 제거됨


def build_agents(config: Any) -> dict[str, BaseAgent]:
    """에이전트를 인스턴스화해 {이름: 에이전트} 로 반환(로드된 것만)."""
    agents = {cls.name: cls(config) for cls in AGENT_CLASSES}
    # Scribe 가 Copilot 근거(법령 인용)를 보고서에 삽입하도록 연결
    if "Scribe" in agents and "Copilot" in agents:
        agents["Scribe"].copilot = agents["Copilot"]
    return agents


__all__ = [
    "BaseAgent", "GuardAgent", "AnalystAgent", "ScribeAgent",
    "CopilotAgent", "DispatcherAgent", "SafetyManagerAgent",
    "AGENT_CLASSES", "build_agents",
]
