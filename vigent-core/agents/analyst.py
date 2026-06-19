"""Analyst — [판단] 규칙+딥러닝 가산 점수·위험등급 (스텁)"""
from __future__ import annotations

from .base import BaseAgent


class AnalystAgent(BaseAgent):
    name = "Analyst"
    role = "판단: 규칙+딥러닝 가산 점수, severity·위반 항목 산정"
