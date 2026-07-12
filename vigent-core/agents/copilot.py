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

    # ── VLM 자유텍스트 위험요인 → 법령 매칭(2단계) ────────────────────────
    def match_rules(self, text: str) -> list[str]:
        """위험요인 문장에서 키워드를 찾아 해당 규칙 id 목록을 반환(매칭 많은 순)."""
        kw = self.corpus.get("_keywords", {}) if self.available else {}
        hits = []
        for rid, words in kw.items():
            n = sum(1 for w in words if w in text)
            if n:
                hits.append((n, rid))
        return [rid for _n, rid in sorted(hits, reverse=True)]

    def cite_for_hazard(self, text: str) -> dict[str, Any]:
        """위험요인 텍스트 → 매칭된 법령 인용(중복 조항 제거). 항상 출처 포함(§9)."""
        seen, cites = set(), []
        for rid in self.match_rules(text):
            for c in self.corpus.get(rid, []):
                key = (c.get("source"), c.get("clause"))
                if key in seen:
                    continue
                seen.add(key)
                cites.append({"title": c.get("title", ""), "source": c.get("source", ""),
                              "clause": c.get("clause", ""), "snippet": c.get("snippet", ""),
                              "rule": rid})
        if not cites:
            return {"matched": False, "citations": [], "관련법령": ""}
        법령 = "; ".join(f"{c['source']} {c['clause']}" for c in cites[:3])
        return {"matched": True, "citations": cites, "관련법령": 법령}

    def enrich_vlm(self, vlm: dict[str, Any]) -> dict[str, Any]:
        """VLM 위험요약 dict 의 빈 '관련법령' 을, 위험요인+근거 텍스트로 매칭해 채운다.
        VLM 이 이미 채웠으면 건드리지 않는다(규칙 6: 가산만)."""
        if not isinstance(vlm, dict):
            return vlm
        if str(vlm.get("관련법령", "")).strip():
            # VLM 이 직접 채운 '관련법령' 은 화이트리스트 게이트로 검증(환각 구멍 차단, §7).
            # 화이트리스트 밖/파싱불가 조문은 '안전관리자 확인 필요'로 치환 + 로그.
            try:
                import legal_whitelist
                vlm["관련법령"] = legal_whitelist.gate_vlm_text(
                    str(vlm.get("관련법령", "")), doc_type="VLM위험분석")
            except Exception:  # noqa: BLE001
                pass
            return vlm   # (게이트 적용 후) VLM 자체 값 유지
        text = f"{vlm.get('위험요인', '')} {vlm.get('근거', '')}"
        m = self.cite_for_hazard(text)
        if m["matched"]:
            vlm["관련법령"] = m["관련법령"]
            vlm["_citations"] = m["citations"]   # 보고서/UI 가 출처 표시에 사용
        return vlm

    def run(self, rule_ids: list[str] | None = None) -> dict[str, Any]:
        return self.search(rule_ids or [])
