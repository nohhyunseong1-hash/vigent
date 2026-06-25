from backend.app.models import BirthInput, ProfileInput, ReadingRequest
from backend.app.services.profile_image import evaluate_image_quality
from backend.app.services.reading_service import create_reading


def test_reading_response_contains_profile_impression_and_hooks():
    request = ReadingRequest(
        birth=BirthInput(
            name="테스터",
            gender="여성",
            birth_date="1995-07-03",
            calendar_type="양력",
            birth_time="09:10",
        ),
        profile=ProfileInput(
            first_impression_tags=["차분함", "단정함"],
            appearance_note="정리된 인상",
            self_intro="전시와 책을 좋아합니다.",
            interests=["전시", "독서", "영화"],
        ),
        image_quality_hint=evaluate_image_quality(
            brightness_score=0.8,
            sharpness_score=0.8,
            face_count=1,
            frontal_score=0.9,
        ),
    )

    result = create_reading(request)

    assert result.profile_impression.selected_tags == ["차분함", "단정함"]
    assert result.dating_profile.intro_style == "안정적이고 신뢰감 있는 톤"
    assert result.dating_profile.conversation_hooks == ["전시", "독서", "영화"]
    assert len(result.evidence) >= 4
