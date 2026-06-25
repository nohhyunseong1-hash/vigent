from __future__ import annotations

from backend.app.models import CompatibilityResponse, CompatibilityScore, ReadingRequest


def _tag_overlap_score(left: ReadingRequest, right: ReadingRequest) -> CompatibilityScore:
    overlap = set(left.profile.first_impression_tags) & set(right.profile.first_impression_tags)
    score = min(100, len(overlap) * 20 + 40) if overlap else 38
    reason = "공통 인상 태그가 있어 대화 진입 장벽이 낮습니다." if overlap else "직접 겹치는 인상 태그는 적지만 보완형 대화가 가능합니다."
    return CompatibilityScore(
        category="프로필 태그 합",
        score=score,
        reason=reason,
        evidence_rule_ids=["profile-tone-001"],
    )


def _interest_score(left: ReadingRequest, right: ReadingRequest) -> CompatibilityScore:
    overlap = set(left.profile.interests) & set(right.profile.interests)
    score = min(100, len(overlap) * 18 + 35) if overlap else 32
    reason = "겹치는 관심사가 있어 실제 만남 전 대화 소재가 분명합니다." if overlap else "관심사는 겹치지 않지만 새로운 조합으로 연결될 수 있습니다."
    return CompatibilityScore(
        category="관심사 보완성",
        score=score,
        reason=reason,
        evidence_rule_ids=["profile-tone-002"],
    )


def _saju_placeholder_score() -> CompatibilityScore:
    return CompatibilityScore(
        category="사주 궁합",
        score=50,
        reason="실제 만세력 어댑터 연결 전이라 궁합 계산은 중립 점수로 고정했습니다.",
        evidence_rule_ids=["compat-demo-000"],
    )


def score_compatibility(left: ReadingRequest, right: ReadingRequest) -> CompatibilityResponse:
    items = [
        _saju_placeholder_score(),
        _tag_overlap_score(left, right),
        _interest_score(left, right),
    ]
    total = round(sum(item.score for item in items) / len(items))
    summary = "사주 어댑터 연동 전 단계입니다. 현재 점수는 프로필 기반 보조 지표와 중립 사주 점수를 합산한 데모 결과입니다."
    return CompatibilityResponse(total_score=total, summary=summary, items=items)
