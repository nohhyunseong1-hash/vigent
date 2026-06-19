"""Copilot — [논문/근거 써치] 법령·가이드 RAG 검색, 인용 제공 (§9)

이 단계(§15-4)에서는 로컬 코퍼스(config/corpus/safety_citations.json)에서
규칙(rule)별 법령·가이드 근거를 찾아 '출처(source)+조항(clause)' 과 함께 반환한다.
임베딩 기반 정식 RAG 는 후속 단계에서 교체 가능(모델 불가지론).

폴백: 코퍼스 파일이 없거나 해당 규칙이 없으면, 빈 결과 대신
      '검토 필요' 안내 근거를 돌려 기능이 죽지 않게 한다(절대 저하 없음).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import BaseAgent

_ROOT = Path(__file__).resolve().parent.parent.parent
_CORPUS = _ROOT / "config" / "corpus" / "safety_citations.json"


class CopilotAgent(BaseAgent):
    name = "Copilot"
    role = "근거: 법령·KOSHA 가이드 RAG 검색, citation 포함 근거 블록"

    def __init__(self, config: Any):
        super().__init__(config)
        self.corpus: dict[str, Any] = {}
        self.available = False
        if _CORPUS.exists():
            try:
                with open(_CORPUS, "r", encoding="utf-8") as f:
                    self.corpus = json.load(f)
                self.available = True
            except (json.JSONDecodeError, OSError):
                self.available = False

    def status(self) -> dict[str, Any]:
        rules = [k for k in self.corpus if not k.startswith("_")]
        return {"name": self.name, "role": self.role, "implemented": True,
                "corpus_loaded": self.available, "rules_covered": rules}

    def cite(self, rule_id: str) -> dict[str, Any]:
        """규칙 1개에 대한 근거(인용) 블록을 반환. 항상 출처를 포함한다(§9)."""
        items = self.corpus.get(rule_id) if self.available else None
        if not items:
            # 폴백: 근거 미확보 — 빈손 대신 검토 안내(기능 무중단)
            return {
                "rule": rule_id,
                "citations": [{
                    "title": "근거 미확보(검토 필요)",
                    "source": "—", "clause": "—",
                    "snippet": "해당 위험에 대한 법령 근거를 코퍼스에서 찾지 못했습니다. 안전관리자 검토가 필요합니다.",
                }],
                "fallback": True,
            }
        return {
            "rule": rule_id,
            "citations": [{
                "title": c.get("title", ""), "source": c.get("source", ""),
                "clause": c.get("clause", ""), "snippet": c.get("snippet", ""),
            } for c in items],
            "fallback": False,
        }

    def search(self, rule_ids: list[str]) -> dict[str, Any]:
        """여러 규칙에 대한 근거를 한 번에. Scribe 가 보고서에 삽입할 때 사용."""
        return {rid: self.cite(rid) for rid in rule_ids}

    def run(self, rule_ids: list[str] | None = None) -> dict[str, Any]:
        return self.search(rule_ids or [])
