"""Scribe — [보고서] 위험성평가서·증거 리포트·피드백 PDF 생성 (스텁)"""
from __future__ import annotations

from .base import BaseAgent


class ScribeAgent(BaseAgent):
    name = "Scribe"
    role = "보고서: 위험성평가서·증거 리포트·피드백 문서 생성(PDF/웹)"
