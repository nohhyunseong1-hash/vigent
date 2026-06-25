from backend.app.models import BirthInput, ProfileInput, ReadingRequest
from backend.app.services.matching_engine import score_compatibility


def _reading(name: str, tags: list[str], interests: list[str]) -> ReadingRequest:
    return ReadingRequest(
        birth=BirthInput(
            name=name,
            gender="여성",
            birth_date="1994-06-02",
            birth_time="07:20",
            calendar_type="양력",
        ),
        profile=ProfileInput(
            first_impression_tags=tags,
            interests=interests,
        ),
    )


def test_matching_engine_returns_explainable_items():
    result = score_compatibility(
        _reading("가", ["차분함", "단정함"], ["영화", "전시"]),
        _reading("나", ["차분함"], ["영화", "러닝"]),
    )
    assert result.total_score > 0
    assert len(result.items) == 3
    assert all(item.evidence_rule_ids for item in result.items)
