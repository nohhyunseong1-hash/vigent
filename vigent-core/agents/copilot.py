"""Copilot — [논문/근거 써치] 법령·가이드·논문 RAG 검색, 인용 제공 (스텁)"""
from __future__ import annotations

from .base import BaseAgent


class CopilotAgent(BaseAgent):
    name = "Copilot"
    role = "근거: 법령·KOSHA 가이드·논문 RAG 검색, citation 포함 근거 블록"
