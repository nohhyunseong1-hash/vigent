from __future__ import annotations

from backend.app.models import ImageQualityResult


def evaluate_image_quality(
    *,
    brightness_score: float,
    sharpness_score: float,
    face_count: int,
    frontal_score: float,
) -> ImageQualityResult:
    feedback: list[str] = []

    if face_count != 1:
        feedback.append("한 사람만 보이도록 다시 촬영하세요.")
    if brightness_score < 0.45:
        feedback.append("조명이 어두워 얼굴 윤곽이 흐립니다.")
    if sharpness_score < 0.4:
        feedback.append("흔들림이 있어 선명도가 부족합니다.")
    if frontal_score < 0.65:
        feedback.append("정면에 가깝게 얼굴을 맞춰주세요.")

    accepted = not feedback
    if accepted:
        feedback.append("프로필 품질 기준을 통과했습니다.")

    return ImageQualityResult(
        accepted=accepted,
        brightness_score=brightness_score,
        sharpness_score=sharpness_score,
        face_count=face_count,
        frontal_score=frontal_score,
        feedback=feedback,
    )
