"""Fitness 에이전트 v1.

비전이 산출한 동작 지표(관절각도·깊이·좌우대칭·반복수 등) → 생체역학 기반 폼 평가 + 체형 맞춤 피드백.
- v1은 결정론적(표준 폼 기준 KB) → 환각 없음, 항상 동작.
- 비전 모델·실시간 경로와 완전 분리된 '추가 전용' 모듈(기존 기능 무영향).
- 폼 '측정' 정확도는 비전의 몫(시계열 모델은 별개 R&D). 에이전트는 측정 지표를 해석·피드백.
- LLM/RAG(논문 인용) 보강은 enrich 훅(기본 OFF, provider·문서 준비 후).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

KST = timezone(timedelta(hours=9))

# 운동별 폼 기준(표준 근력운동 가이드 기반). 각 기준: metric=지표키, good/warn=경계(작을수록 좋음),
# unit, fault=문제, cue=교정 큐, risk=부상위험, weight=점수 가중.
EXERCISE_KB: Dict[str, Dict[str, Any]] = {
    "squat": {
        "label": "스쿼트",
        "criteria": [
            {"name": "깊이(무릎각)", "metric": "knee_angle", "good": 100, "warn": 130, "unit": "°",
             "fault": "충분히 앉지 않음(가동범위 부족)", "cue": "엉덩이를 더 낮춰 허벅지가 바닥과 평행까지",
             "risk": "운동효과 저하·가동범위 제한", "weight": 1.0},
            {"name": "체간 기울기", "metric": "trunk_angle", "good": 22, "warn": 35, "unit": "°",
             "fault": "상체가 과도하게 앞으로 숙여짐", "cue": "가슴 들고 코어 조여 상체를 더 세우기",
             "risk": "요추 부담·허리 부상", "weight": 1.2},
            {"name": "좌우 대칭", "metric": "knee_diff", "good": 10, "warn": 18, "unit": "°",
             "fault": "좌우 무릎 높이/각도 불균형", "cue": "체중을 양발에 고르게, 거울로 좌우 확인",
             "risk": "편측 과부하·불균형성 부상", "weight": 1.0},
        ],
    },
    "pushup": {
        "label": "푸쉬업",
        "criteria": [
            {"name": "팔꿈치 각(깊이)", "metric": "elbow_angle", "good": 90, "warn": 110, "unit": "°",
             "fault": "충분히 내려가지 않음", "cue": "가슴이 바닥 가까이 오도록 더 내리기",
             "risk": "운동효과 저하", "weight": 1.0},
            {"name": "몸통 정렬(엉덩이 처짐)", "metric": "hip_sag", "good": 10, "warn": 20, "unit": "°",
             "fault": "엉덩이가 처지거나 솟음", "cue": "코어·둔근 조여 머리-엉덩이-발 일직선",
             "risk": "요추 부담", "weight": 1.2},
        ],
    },
    "deadlift": {
        "label": "데드리프트",
        "criteria": [
            {"name": "허리 굽힘(척추 중립)", "metric": "spine_round", "good": 10, "warn": 20, "unit": "°",
             "fault": "허리가 둥글게 말림", "cue": "가슴 들고 척추 중립 유지, 바를 몸 가까이",
             "risk": "추간판·요추 부상(고위험)", "weight": 1.5},
            {"name": "좌우 대칭", "metric": "knee_diff", "good": 10, "warn": 18, "unit": "°",
             "fault": "좌우 불균형", "cue": "바를 수평으로, 양발 균등 압력", "risk": "편측 과부하", "weight": 1.0},
        ],
    },
}

_GRADE = {"good": (100, "좋음"), "warn": (60, "주의"), "danger": (20, "위험")}


def _grade(val: float, good: float, warn: float):
    """작을수록 좋음(low-is-better) 지표 채점."""
    if val <= good:
        return "good"
    if val <= warn:
        return "warn"
    return "danger"


def build_feedback(exercise: str, metrics: Dict[str, Any], body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """동작 지표 → 생체역학 기반 폼 피드백(구조화).

    metrics: {"knee_angle":95, "trunk_angle":28, "knee_diff":12, "rep_count":10, "tempo":..} 등(있는 것만 평가)
    body: {"height_cm":..., "femur_ratio":...} (선택) — 체형 기반 해석에 사용
    """
    ex = EXERCISE_KB.get((exercise or "").lower())
    items: List[Dict[str, Any]] = []
    score_sum = 0.0
    weight_sum = 0.0
    if ex:
        for c in ex["criteria"]:
            if c["metric"] not in metrics or metrics[c["metric"]] is None:
                continue  # 측정 안 된 지표는 건너뜀(저하 없음)
            val = float(metrics[c["metric"]])
            g = _grade(val, c["good"], c["warn"])
            pts, label = _GRADE[g]
            w = float(c.get("weight", 1.0))
            score_sum += pts * w
            weight_sum += w
            items.append({
                "기준": c["name"],
                "측정값": f"{val:g}{c['unit']}",
                "평가": label,                 # 좋음/주의/위험
                "문제": c["fault"] if g != "good" else "",
                "교정큐": c["cue"] if g != "good" else "양호 — 현재 폼 유지",
                "부상위험": c["risk"] if g != "good" else "",
                "_grade": g,
            })
    form_score = round(score_sum / weight_sum) if weight_sum else None

    # 체형 기반 해석(생체역학) — v1 간단 휴리스틱, v2에서 논문 RAG로 심화
    body_note = ""
    if body:
        fr = body.get("femur_ratio")
        if fr is not None and float(fr) >= 0.55:
            body_note = ("대퇴(허벅지)가 상대적으로 길어, 스쿼트 시 체간 전방 기울기가 더 큰 것이 "
                         "생체역학적으로 정상입니다 — 과도한 '상체 숙임' 경고는 체형을 감안해 완화 해석하세요.")
        elif fr is not None and float(fr) <= 0.45:
            body_note = "대퇴가 짧은 편 — 비교적 곧은 상체로 깊은 스쿼트가 수월한 체형입니다."
    return {
        "exercise": ex["label"] if ex else exercise,
        "body": body or {},
        "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "status": "auto",
        "rep_count": metrics.get("rep_count"),
        "form_score": form_score,             # 0~100
        "items": items,
        "body_note": body_note,
        "summary": {
            "평가항목": len(items),
            "주의": sum(1 for i in items if i["_grade"] == "warn"),
            "위험": sum(1 for i in items if i["_grade"] == "danger"),
        },
        "source": "kb_biomech",
        "review_note": "AI 폼 분석 — 정확도는 비전 측정 지표 품질에 의존(시계열 측정 권장).",
    }


def enrich_with_llm(feedback: Dict[str, Any]) -> Dict[str, Any]:
    """[v2 훅] LLM으로 교정 큐를 개인 맥락에 맞게 구체화 — 제공된 기준/지표 범위 내에서만.

    AX_VLM_PROVIDER=anthropic + ANTHROPIC_API_KEY 설정 시에만 동작. 미설정/실패 시 원본 그대로(무영향).
    원본 교정큐 보존 + '교정큐_AI보강' 별도 추가(사람/코치 검토 원칙).
    """
    provider = (os.getenv("AX_VLM_PROVIDER", "") or "").strip().lower()
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    items = feedback.get("items", [])
    if provider != "anthropic" or not api_key or not items:
        return feedback
    model = os.getenv("AX_VLM_MODEL", "") or "claude-sonnet-4-6"
    payload = [{"no": i + 1, "기준": it["기준"], "측정값": it["측정값"], "평가": it["평가"],
                "기본교정큐": it["교정큐"]} for i, it in enumerate(items)]
    prompt = (
        "너는 운동역학(biomechanics) 기반 피트니스 코치다. 아래 각 항목의 '교정큐'를 "
        f"운동={feedback.get('exercise')} 맥락에 맞게 더 구체적이고 실행 가능하게 다듬어라. "
        "제공된 평가/측정값 범위 내에서만 작성하고, 의학적 단정이나 없는 수치를 지어내지 마라. 한국어, 간결.\n"
        f"체형: {json.dumps(feedback.get('body', {}), ensure_ascii=False)}\n"
        f"항목: {json.dumps(payload, ensure_ascii=False)}\n"
        '오직 JSON만: {"cues":[{"no":1,"교정큐":"..."}]}'
    )
    try:
        body = json.dumps({"model": model, "max_tokens": 1200,
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
            headers={"Content-Type": "application/json", "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"}, method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < 0:
            return feedback
        parsed = json.loads(text[a:b + 1])
        cues = {int(x["no"]): str(x["교정큐"]).strip() for x in parsed.get("cues", []) if x.get("교정큐")}
        for i, it in enumerate(items):
            if cues.get(i + 1):
                it["교정큐_AI보강"] = cues[i + 1]
        feedback["source"] = "kb_biomech+llm"
        feedback["llm_model"] = model
    except Exception:
        return feedback
    return feedback
