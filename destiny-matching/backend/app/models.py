from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BirthInput(BaseModel):
    name: str = Field(min_length=1)
    gender: Literal["남성", "여성", "기타"]
    birth_date: str
    calendar_type: Literal["양력", "음력"] = "양력"
    birth_time: str | None = None
    birth_place: str | None = None
    manse_note: str | None = None


class ProfileInput(BaseModel):
    first_impression_tags: list[str] = Field(default_factory=list)
    appearance_note: str | None = None
    self_intro: str | None = None
    interests: list[str] = Field(default_factory=list)


class ImageQualityResult(BaseModel):
    accepted: bool
    brightness_score: float
    sharpness_score: float
    face_count: int
    frontal_score: float
    feedback: list[str]


class SajuComputationResult(BaseModel):
    engine_name: str
    status: Literal["demo", "ready_for_adapter"]
    pillars: dict[str, str]
    elements: dict[str, float]
    notes: list[str]


class RuleEvidence(BaseModel):
    rule_id: str
    summary: str
    source: str


class ProfileImpression(BaseModel):
    selected_tags: list[str] = Field(default_factory=list)
    appearance_note: str | None = None
    self_intro: str | None = None


class DatingProfile(BaseModel):
    intro_style: str
    conversation_hooks: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


class ReadingResponse(BaseModel):
    disclaimer: str
    image_quality: ImageQualityResult | None = None
    saju: SajuComputationResult
    profile_impression: ProfileImpression
    dating_profile: DatingProfile
    profile_summary: list[str]
    evidence: list[RuleEvidence]


class CompatibilityScore(BaseModel):
    category: str
    score: int
    reason: str
    evidence_rule_ids: list[str]


class CompatibilityResponse(BaseModel):
    total_score: int
    summary: str
    items: list[CompatibilityScore]


class ReadingRequest(BaseModel):
    birth: BirthInput
    profile: ProfileInput
    image_quality_hint: ImageQualityResult | None = None


class CompatibilityRequest(BaseModel):
    left: ReadingRequest
    right: ReadingRequest
