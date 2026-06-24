"""safety_rag.py — 안전 지식 경량 검색(RAG)

법령·KOSHA 가이드(safety_guidance.json) + 작업지식(safety_knowledge.json)을 하나의 코퍼스로
묶어, 질의에 가장 관련된 스니펫을 찾아 '근거'로 돌려준다.

설계:
- 외부 의존성 0 (LangChain·임베딩 불필요) → 폐쇄망·USB·저사양에서 그대로 동작.
- 한국어 친화: 글자 2-gram(shingle) 겹침으로 점수화(형태소 분석기 없이도 키워드 매칭).
- 업그레이드 경로: 나중에 _shingles 를 sentence-transformers 임베딩+코사인으로 교체하면
  같은 인터페이스로 의미검색까지 확장(절대 저하 없음).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CORPUS_DIR = _ROOT / "config" / "corpus"
_CACHE: list[dict[str, Any]] | None = None


def _load(name: str) -> dict[str, Any]:
    try:
        return json.loads((_CORPUS_DIR / name).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _corpus() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    docs: list[dict[str, Any]] = []
    for d in _load("safety_guidance.json").get("docs", []):
        docs.append({"id": d["id"], "title": d.get("title", ""), "text": d.get("text", ""),
                     "source": d.get("source", ""), "refs": d.get("refs", []),
                     "topic": d.get("topic", ""), "type": "가이드"})
    for a in _load("safety_knowledge.json").get("activities", []):
        measures = [m["name"] for m in a.get("required_measures", [])]
        text = ("필수 안전조치: " + ", ".join(measures)
                + ". 위험요인: " + ", ".join(a.get("hazards", []))
                + ". 권장조치: " + ", ".join(a.get("actions", [])))
        docs.append({"id": "act_" + a["id"], "title": a["name"], "text": text,
                     "source": "; ".join(r.get("law", "") for r in a.get("regulations", [])),
                     "refs": a.get("aliases", []) + measures,
                     "topic": a["name"], "type": "작업지식"})
    _CACHE = docs
    return docs


def _shingles(s: str) -> set[str]:
    s = re.sub(r"\s+", "", (s or "").lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def retrieve(query: str, k: int = 5) -> list[dict[str, Any]]:
    """질의 → 관련 스니펫 top-k (점수·근거 포함). 코퍼스 비면 []."""
    q = _shingles(query)
    if not q:
        return []
    out = []
    for d in _corpus():
        weighted = (d["title"] + " ") * 3 + (" ".join(d.get("refs", [])) + " ") * 3 + d["text"]
        dset = _shingles(weighted)
        overlap = len(q & dset) / len(q)                        # 0~1 겹침 비율
        boost = sum(0.25 for r in d.get("refs", []) if r and r in query)  # 정확 키워드 가산
        score = overlap + boost
        if score > 0:
            out.append({**d, "score": round(score, 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:k]
