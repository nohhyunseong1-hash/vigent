from backend.app.services.profile_image import evaluate_image_quality


def test_quality_passes_when_all_signals_are_good():
    result = evaluate_image_quality(
        brightness_score=0.8,
        sharpness_score=0.72,
        face_count=1,
        frontal_score=0.91,
    )
    assert result.accepted is True
    assert "프로필 품질 기준을 통과했습니다." in result.feedback


def test_quality_fails_when_multiple_issues_exist():
    result = evaluate_image_quality(
        brightness_score=0.2,
        sharpness_score=0.1,
        face_count=2,
        frontal_score=0.3,
    )
    assert result.accepted is False
    assert len(result.feedback) == 4
