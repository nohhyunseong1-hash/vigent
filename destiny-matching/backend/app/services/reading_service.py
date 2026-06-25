from __future__ import annotations

from backend.app.models import (
    DatingProfile,
    ProfileImpression,
    ReadingRequest,
    ReadingResponse,
    RuleEvidence,
)
from backend.app.rulebooks import load_rulebook
from backend.app.services.saju_engine import SajuEngine


DISCLAIMER = "이 결과는 전통 명리 기반 엔터테인먼트 해석이며 과학적·의학적 판단이 아닙니다."


def build_profile_summary(request: ReadingRequest) -> list[str]:
    profile = request.profile
    summary: list[str] = []
    if profile.first_impression_tags:
        summary.append(f"사용자 선택 인상 태그: {', '.join(profile.first_impression_tags)}")
    if profile.appearance_note:
        summary.append(f"외형 메모: {profile.appearance_note}")
    if profile.self_intro:
        summary.append(f"자기소개 요약: {profile.self_intro}")
    if profile.interests:
        summary.append(f"관심사: {', '.join(profile.interests)}")
    return summary


def build_dating_profile(request: ReadingRequest) -> DatingProfile:
    profile = request.profile
    tags = profile.first_impression_tags

    if {"차분함", "단정함"} & set(tags):
        intro_style = "안정적이고 신뢰감 있는 톤"
    elif {"밝음", "활발함"} & set(tags):
        intro_style = "가볍고 대화 진입이 쉬운 톤"
    else:
        intro_style = "과장 없이 또렷한 자기소개 톤"

    hooks = profile.interests[:3]
    strengths = []
    if tags:
        strengths.append(f"사용자가 스스로 선택한 인상은 {', '.join(tags)} 쪽입니다.")
    if profile.self_intro:
        strengths.append("자기소개를 기반으로 대화 소재를 이어가기 좋습니다.")
    if profile.interests:
        strengths.append("관심사를 중심으로 아이스브레이커를 만들 수 있습니다.")

    return DatingProfile(
        intro_style=intro_style,
        conversation_hooks=hooks,
        strengths=strengths,
    )


def create_reading(request: ReadingRequest) -> ReadingResponse:
    saju = SajuEngine().compute(request.birth)
    sample_rules = load_rulebook("saju_rules.sample.json")
    profile_rules = load_rulebook("profile_tone.sample.json")
    evidence = [
        RuleEvidence(
            rule_id=rule["id"],
            summary=rule["summary"],
            source=rule["source"],
        )
        for rule in [*sample_rules[:2], *profile_rules[:2]]
    ]
    return ReadingResponse(
        disclaimer=DISCLAIMER,
        image_quality=request.image_quality_hint,
        saju=saju,
        profile_impression=ProfileImpression(
            selected_tags=request.profile.first_impression_tags,
            appearance_note=request.profile.appearance_note,
            self_intro=request.profile.self_intro,
        ),
        dating_profile=build_dating_profile(request),
        profile_summary=build_profile_summary(request),
        evidence=evidence,
    )
