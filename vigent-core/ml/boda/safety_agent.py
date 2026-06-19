"""Safety 위험성평가 에이전트 v1.

비전 탐지 이벤트(보호구 미착용·위험구역 침입·화재 등) → 국내 위험성평가표(초안).
- report_builder의 규정 기반 지식(RISK_ASSESS, 산업안전보건법 근거)을 재사용(중복 방지).
- v1은 결정론적(규정 기반) 구조화 출력 → 환각 없음, 항상 동작.
- 비전 모델·실시간 경로와 완전 분리된 '추가 전용' 모듈(기존 기능 무영향).
- LLM/RAG 보강은 v2 확장점(enrich 훅)으로 둠 — 현재는 비활성(provider·문서 준비 후).
- 산출물은 '초안(draft)'이며 안전관리자 검토·승인 필요(review_required=True).
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

try:
    from backend.report_builder import RISK_ASSESS, _likelihood, _level, _HZ_KO
except ImportError:  # 서버 실행 위치에 따른 폴백
    from report_builder import RISK_ASSESS, _likelihood, _level, _HZ_KO

KST = timezone(timedelta(hours=9))


def build_assessment(events: List[Dict[str, Any]], site: str = "", process: str = "") -> Dict[str, Any]:
    """탐지 이벤트 목록 → 국내 위험성평가표(초안).

    events: [{"type": <RISK_ASSESS 키 또는 화재유형>, "count": int}, ...]
    위험성 = 빈도(가능성) × 강도(중대성). 규정 근거·현재조치·감소대책은 KB에서 채움.
    """
    rows: List[Dict[str, Any]] = []
    for ev in (events or []):
        key = ev.get("type") or ev.get("key")
        count = int(ev.get("count", 1) or 1)
        info = RISK_ASSESS.get(key)
        if not info:
            continue
        likely = _likelihood(count)
        sev = int(info["sev"])
        score = likely * sev
        lvl, color = _level(score)
        rows.append({
            "유해위험요인": _HZ_KO.get(key, key),
            "공정작업": info["work"],
            "위험분류": info["cat"],
            "위험상황및결과": info["harm"],
            "관련근거": info["law"],            # 산업안전보건법 등 법적 근거
            "현재안전보건조치": info["now"],
            "빈도_가능성": likely,
            "강도_중대성": sev,
            "위험성": score,
            "위험성등급": lvl,                   # 상/중/하
            "감소대책": info["act"],
            "AI감지근거": f"AI {count}회 감지",
            "개선예정일": "",                    # 사람 입력칸
            "담당자": "",                        # 사람 입력칸
            "_color": color,
        })
    # 위험성 높은 순 정렬
    rows.sort(key=lambda r: r["위험성"], reverse=True)
    high = [r for r in rows if r["위험성등급"] == "상"]
    return {
        "site": site,
        "process": process,
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "method": "위험성 = 빈도(가능성) × 강도(중대성)",
        "status": "draft",                      # 초안 — 사람 검토 전
        "review_required": True,                # 안전관리자 검토·승인 필수
        "source": "kb_regulation",              # 규정 기반(결정론적)
        "summary": {
            "총항목": len(rows),
            "상_높음": len(high),
            "주요위험": [r["유해위험요인"] for r in high],
        },
        "rows": rows,
    }


def enrich_with_llm(assessment: Dict[str, Any]) -> Dict[str, Any]:
    """LLM으로 각 항목의 '감소대책'을 현장 맥락에 맞게 구체화 — 제공된 법적근거 범위 내에서만.

    - 동작 조건: AX_VLM_PROVIDER=anthropic 이고 ANTHROPIC_API_KEY 설정된 경우에만(기본 OFF).
    - 환각 방지: 새 법조항·사실·수치 생성 금지. 원본 '감소대책'은 보존하고 '감소대책_AI보강'을 별도 추가
      → 검토자가 규정 기반 baseline과 AI 제안을 비교·선택(사람 검토 원칙 유지).
    - 미설정/실패/파싱오류 등 어떤 경우에도 규정 기반 원본을 그대로 반환(무영향).
    """
    provider = (os.getenv("AX_VLM_PROVIDER", "") or "").strip().lower()
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    rows = assessment.get("rows", [])
    if provider != "anthropic" or not api_key or not rows:
        return assessment
    model = os.getenv("AX_VLM_MODEL", "") or "claude-sonnet-4-6"
    items = [{
        "no": i + 1, "위험요인": r["유해위험요인"], "공정": r["공정작업"],
        "법적근거": r["관련근거"], "현재조치": r["현재안전보건조치"], "기본대책": r["감소대책"],
    } for i, r in enumerate(rows)]
    prompt = (
        "너는 한국 산업안전 위험성평가 전문가다. 아래 각 항목의 '감소대책'을 현장 맥락에 맞게 "
        "더 구체적이고 실행 가능하게 다듬어라. 반드시 제공된 '법적근거' 범위 내에서만 작성하고, "
        "새로운 법조항·사실·수치를 지어내지 마라. 한국어로 항목당 2~3개 조치, 간결하게.\n"
        f"현장: 사업장={assessment.get('site','')} 공정={assessment.get('process','')}\n"
        f"항목: {json.dumps(items, ensure_ascii=False)}\n"
        '오직 JSON만 출력: {"improvements":[{"no":1,"감소대책":"..."}]}'
    )
    try:
        body = json.dumps({
            "model": model, "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"Content-Type": "application/json", "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < 0:
            return assessment
        parsed = json.loads(text[a:b + 1])
        imp = {int(x["no"]): str(x["감소대책"]).strip()
               for x in parsed.get("improvements", []) if x.get("감소대책")}
        for i, r in enumerate(rows):
            if imp.get(i + 1):
                r["감소대책_AI보강"] = imp[i + 1]   # 원본 보존 + 보강본 별도
        assessment["source"] = "kb_regulation+llm"
        assessment["llm_model"] = model
    except Exception:
        return assessment  # 어떤 실패든 규정 기반 원본 유지(무영향)
    return assessment


# ---------- 승인본 저장·이력 (법적 증빙 감사추적) ----------
_STORE = pathlib.Path(__file__).resolve().parent.parent / "data" / "risk_assessments"


def save_assessment(assessment: Dict[str, Any], approver: str = "") -> Dict[str, Any]:
    """위험성평가표(검토·수정본)를 디스크에 저장. 승인자 있으면 'approved'로 기록(이력관리)."""
    _STORE.mkdir(parents=True, exist_ok=True)
    aid = datetime.now(KST).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    rec = dict(assessment)
    rec["id"] = aid
    rec["approver"] = approver
    rec["status"] = "approved" if approver else rec.get("status", "draft")
    rec["approved_at"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST") if approver else ""
    (_STORE / f"{aid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def list_assessments(limit: int = 100) -> List[Dict[str, Any]]:
    if not _STORE.exists():
        return []
    out: List[Dict[str, Any]] = []
    for f in sorted(_STORE.glob("*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            out.append({k: r.get(k) for k in
                        ("id", "site", "process", "status", "approver", "approved_at", "generated_at", "summary")})
        except Exception:
            pass
    return out


def load_assessment(aid: str) -> Dict[str, Any] | None:
    f = _STORE / f"{aid}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
