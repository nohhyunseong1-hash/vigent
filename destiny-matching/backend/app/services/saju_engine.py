from __future__ import annotations

from dataclasses import dataclass

from backend.app.models import BirthInput, SajuComputationResult


@dataclass(slots=True)
class SajuEngine:
    """Placeholder adapter boundary for a real manse calendar engine."""

    engine_name: str = "adapter-required"

    def compute(self, birth: BirthInput) -> SajuComputationResult:
        # This demo path exists only to keep the scaffold executable.
        # Production must replace this with a verified calendar adapter.
        note = (
            "실서비스에서는 sajupy 또는 manseryeok-js 같은 검증된 만세력 어댑터로 "
            "절기, 진태양시, 조자시, 대운을 계산해야 합니다."
        )
        return SajuComputationResult(
            engine_name=self.engine_name,
            status="ready_for_adapter",
            pillars={
                "year": "미연동",
                "month": "미연동",
                "day": "미연동",
                "hour": birth.birth_time or "미입력",
            },
            elements={"목": 0.0, "화": 0.0, "토": 0.0, "금": 0.0, "수": 0.0},
            notes=[note],
        )
