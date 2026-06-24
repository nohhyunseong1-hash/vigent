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


# 안전 도메인 동의어 — 질의를 확장해 '의미스러운' 매칭(임베딩 없이도 동의어/약어 포착)
_SYN = {
    "추락": ["떨어짐", "낙하", "고소"], "협착": ["끼임", "말림", "충돌"],
    "질식": ["산소결핍", "유해가스", "밀폐공간"], "감전": ["전격", "활선", "전기"],
    "화재": ["불", "화기", "용접", "불티"], "붕괴": ["무너짐", "매몰", "굴착"],
    "보호구": ["ppe", "안전장구"], "안전모": ["헬멧", "hardhat"],
    "소화기": ["소화설비"], "환기": ["송풍", "배기"],
    "안전대": ["안전벨트", "죔줄", "하네스"], "지게차": ["포크리프트", "차량계"],
    "크레인": ["양중", "타워크레인", "인양", "줄걸이"], "굴착": ["터파기", "토공", "흙막이"],
    "분진": ["먼지", "방진"], "소음": ["귀마개"], "교육": ["안전보건교육"],
}


def _expand(query: str) -> str:
    q = query or ""
    extra = []
    for key, syns in _SYN.items():
        if key in query:
            extra += syns
        for s in syns:
            if s in query:
                extra.append(key)
                extra += [x for x in syns if x != s]
    return q + " " + " ".join(dict.fromkeys(extra))   # 중복 제거 후 부착


def _bigram_search(query: str, k: int) -> list[dict[str, Any]]:
    q = _shingles(_expand(query))
    if not q:
        return []
    out = []
    for d in _corpus():
        weighted = (d["title"] + " ") * 3 + (" ".join(d.get("refs", [])) + " ") * 3 + d["text"]
        overlap = len(q & _shingles(weighted)) / len(q)
        boost = sum(0.25 for r in d.get("refs", []) if r and r in query)
        score = overlap + boost
        if score > 0:
            out.append({**d, "score": round(score, 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


class _Embed:
    """opt-in 의미검색 — sentence-transformers 가 설치돼 있으면 임베딩 코사인 사용.
    미설치면 None 반환(자동으로 bigram 폴백). 설치: pip install sentence-transformers
    (모델 다운로드 필요 → 폐쇄망에선 bigram 유지)."""
    def __init__(self):
        self.model = None
        self.vecs = None
        self.failed = False

    def search(self, query: str, k: int):
        if self.failed:
            return None
        try:
            if self.model is None:
                from sentence_transformers import SentenceTransformer
                import numpy as np
                self.model = SentenceTransformer("jhgan/ko-sroberta-multitask")
                docs = _corpus()
                texts = [d["title"] + " " + d["text"] + " " + " ".join(d.get("refs", [])) for d in docs]
                self.vecs = np.asarray(self.model.encode(texts))
            import numpy as np
            qv = np.asarray(self.model.encode([query])[0])
            sims = (self.vecs @ qv) / (np.linalg.norm(self.vecs, axis=1) * np.linalg.norm(qv) + 1e-9)
            docs = _corpus()
            idx = sims.argsort()[::-1][:k]
            return [{**docs[i], "score": round(float(sims[i]), 3)} for i in idx]
        except Exception:  # noqa: BLE001  미설치/실패 → bigram 폴백
            self.failed = True
            return None


_EMBED = _Embed()


def retrieve(query: str, k: int = 5) -> list[dict[str, Any]]:
    """질의 → 관련 스니펫 top-k. 임베딩(있으면) → bigram+동의어(폴백). 코퍼스 비면 []."""
    hits = _EMBED.search(query, k)          # opt-in 의미검색(설치 시)
    if hits is not None:
        return hits
    return _bigram_search(query, k)         # 기본: 동의어 확장 + bigram(의존성 0)
