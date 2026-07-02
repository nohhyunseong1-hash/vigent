"""scene_vlm.py — '장면 통합 이해' 1회 VLM 호출 (감사 D-1 대응)

문제(감사 D-1): 재해원인분석 1장에 VLM 생성이 7~9회 순차 실행 → 수십 초 지연.
  (장면설명·재해분석·환경분류·작업분류·행동분석 + 조치별 예/아니오 2~4회)

해결: 위 항목을 '하나의 통합 프롬프트 1회'로 받아 공유(understand). 각 모듈은 이 공유결과를
  쓰되, 없으면 기존 개별 호출로 폴백한다(가산식 + 폴백 — 규칙 6: 절대 저하 없음).
  조치 예/아니오는 남을 때만 1회로 묶어 처리(answer_questions).

⚠ VLM은 확률적 보조 신호다. 실패/누락 시 전부 폴백하므로 기능은 죽지 않는다.
"""
from __future__ import annotations

import json
import re
from typing import Any

# 통합 이해 프롬프트 — 한 장에서 장면·환경·작업·재해·행동·확인장구를 한 번에 JSON으로.
_UNDERSTAND_PROMPT = (
    "너는 한국 산업안전 관제 분석 AI다. 답은 반드시 한국어(Korean)로만. "
    "이 현장/CCTV 사진 1장을 보고 아래 JSON 하나만 출력하라(설명·코드블록 금지). "
    "반드시 '보이는 것'에만 근거하고, 모르면 빈 문자열/빈 배열로 둬라. 지어내지 마라.\n"
    '{"scene":"장면을 한두 문장으로 설명",'
    '"environment":"작업환경(예: 건설현장/공장/창고/사무실/도로/기타)",'
    '"activity":"진행 중인 작업을 짧게(예: 용접, 지게차 운반, 고소작업). 불명확하면 빈 문자열",'
    '"accident_type":"재해유형을 다음 중 하나로(끼임/추락/부딪힘/감전/화재/질식/전도/낙하물/무너짐/없음)",'
    '"what_happened":"무슨 일이 일어났는지(사고 없으면 현재 상황)",'
    '"cause":"사고·위험의 추정 원인",'
    '"evidence":"그렇게 판단한 시각적 근거",'
    '"behaviors":[{"behavior":"명확히 보이는 위험행동","evidence":"근거","confidence":"높음"}],'
    '"visible_safety_items":["사진에서 확인되는 안전장구·조치만(예: 안전모, 안전화, 안전대, 방호덮개, 소화기, 안전난간)"]}\n'
    "위험행동이 안 보이면 behaviors는 [], 안전장구가 안 보이면 visible_safety_items는 [] 로 둬라."
)

_KEYS = ("scene", "environment", "activity", "accident_type",
         "what_happened", "cause", "evidence", "behaviors", "visible_safety_items")


def understand(image_bgr) -> dict[str, Any] | None:
    """장면을 1회 VLM 호출로 통합 이해. 반환 dict 또는 실패 시 None(→ 각 모듈 개별 폴백).
    반환 키: scene/environment/activity/accident_type/what_happened/cause/evidence/
             behaviors(list)/visible_safety_items(list)."""
    if image_bgr is None:
        return None
    try:
        import rfdetr_service
        # 통합 JSON은 길다 → max_tokens 넉넉히, 법령보강은 생략(여기선 원본 JSON만 필요)
        data = rfdetr_service.vlm.summarize_bgr(
            image_bgr, prompt=_UNDERSTAND_PROMPT, max_tokens=420, enrich=False)
    except Exception:  # noqa: BLE001  VLM 미가용/실패 → None(전부 폴백)
        return None
    if not isinstance(data, dict) or data.get("_error"):
        return None
    # summarize_bgr 가 JSON을 파싱해 dict로 준다. 파싱 실패면 {"raw": 원문} → 여기서 한번 더 시도.
    if not any(k in data for k in _KEYS) and "raw" in data:
        m = re.search(r"\{.*\}", str(data.get("raw", "")), re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                return None
    if not any(k in data for k in _KEYS):
        return None
    out: dict[str, Any] = {}
    for k in _KEYS:
        v = data.get(k)
        if k in ("behaviors", "visible_safety_items"):
            out[k] = v if isinstance(v, list) else []
        else:
            out[k] = str(v or "").strip()
    return out


def answer_questions(image_bgr, questions: list[str]) -> list[bool | None]:
    """여러 예/아니오 질문을 1회 VLM 호출로 묶어 처리(조치 점검 배치).
    반환: 질문 순서대로 True(있음)/False(없음)/None(불확실). 실패 시 전부 None(폴백).
    이렇게 묶으면 조치 2~4개를 개별 호출(2~4회) 대신 1회로 줄인다."""
    if image_bgr is None or not questions:
        return [None] * len(questions)
    lines = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
    prompt = (
        "너는 산업안전 점검 보조 AI다. 아래 각 질문에 대해 사진을 보고 "
        "'예'(그렇다/있다) / '아니오'(아니다/없다) / '불확실' 중 하나로만 판단하라.\n"
        "반드시 아래 JSON 배열 하나로만 답하라(설명 없이):\n"
        '[{"n":1,"a":"예|아니오|불확실"}, ...]\n\n질문:\n' + lines
    )
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(
            image_bgr, prompt=prompt, max_tokens=200, enrich=False)
    except Exception:  # noqa: BLE001
        return [None] * len(questions)
    raw = ""
    if isinstance(data, dict):
        raw = str(data.get("raw") or json.dumps(data, ensure_ascii=False))
    else:
        raw = str(data)
    m = re.search(r"\[.*\]", raw, re.S)
    ans: list[bool | None] = [None] * len(questions)
    if not m:
        return ans
    try:
        arr = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return ans
    for item in arr:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("n", 0)) - 1
        except Exception:  # noqa: BLE001
            continue
        if not (0 <= idx < len(questions)):
            continue
        a = str(item.get("a", "")).strip()
        if a.startswith("예") or "있" in a or a.lower().startswith("yes"):
            ans[idx] = True
        elif a.startswith("아니") or "없" in a or a.lower().startswith("no"):
            ans[idx] = False
        else:
            ans[idx] = None
    return ans


def match_visible(item_name: str, visible: list[str]) -> bool:
    """조치/장구 이름이 통합결과의 visible_safety_items 에 나타나는지 소프트 매칭."""
    n = str(item_name)
    for v in visible:
        v = str(v)
        if v and (v in n or n in v):
            return True
    return False
