"""
base.py — 모든 에이전트의 공통 베이스(스텁)

§3 의 6-에이전트는 5단계 루프를 나눠 맡는다.
이 단계(§15-2)에서는 '연결 가능한 빈 껍데기'만 만든다.
각 에이전트는 PipelineConfig 를 주입받고, run() 은 아직 미구현 표식만 반환한다.
"""
from __future__ import annotations

from typing import Any


class BaseAgent:
    name: str = "base"
    role: str = "(설명 없음)"

    def __init__(self, config: Any):
        # config = vision_loader.PipelineConfig (테마 해석 결과)
        self.config = config

    def status(self) -> dict[str, Any]:
        """에이전트 등록 상태(스텁 여부 포함)."""
        return {"name": self.name, "role": self.role, "implemented": False}

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """아직 미구현. 다음 단계에서 채운다."""
        return {
            "agent": self.name,
            "implemented": False,
            "message": f"{self.name} 스텁 — 다음 단계에서 구현 예정",
        }
