from backend.app.models import BirthInput
from backend.app.services.saju_engine import SajuEngine


def test_saju_engine_never_claims_real_calculation_without_adapter():
    engine = SajuEngine()
    result = engine.compute(
        BirthInput(
            name="테스터",
            gender="남성",
            birth_date="1990-01-01",
            calendar_type="양력",
            birth_time="08:30",
        )
    )
    assert result.status == "ready_for_adapter"
    assert result.pillars["year"] == "미연동"
