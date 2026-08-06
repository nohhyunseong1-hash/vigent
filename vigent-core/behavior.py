"""behavior.py — VLM 기반 행동 분석 (신뢰도 보강 + 신규 행동)

규칙 감지(무동작·협착·근골격계)는 카메라 각도·임계값에 따라 오탐이 생겨 '중간' 신뢰도였다.
여기에 VLM(언어모델) 이중확인을 붙이면 오탐이 걸러져 실효 신뢰도가 '높음'이 된다(가산식).
또 VLM은 open-vocabulary 라 class 목록에 없던 행동(흡연·졸음·통화·폭력·절차위반)도 질문으로 판단한다.

⚠ VLM은 확률적이라 보조 신호다. 규칙 신호와 결합(확인)될 때 가장 신뢰할 수 있다.
"""
from __future__ import annotations

from typing import Any

# group: confirm(기존 규칙 재확인 → 신뢰도↑) / new(VLM이라 가능해진 신규 행동)
# kw: VLM 응답에서 이 키워드가 보이면 해당 행동으로 판정
BEHAVIORS: list[dict[str, Any]] = [
    {"id": "immobility", "label": "무동작/실신", "group": "confirm",
     "kw": ["무동작", "실신", "움직이지", "쓰러져 있"]},
    {"id": "proximity", "label": "차량 작업반경 침입", "group": "confirm",
     "kw": ["근접", "가까이", "작업반경", "지게차", "차량 가까"]},
    {"id": "ergonomic", "label": "위험 자세(근골격계)", "group": "confirm",
     "kw": ["허리", "굽혀", "중량물", "무거운", "들기", "자세"]},
    {"id": "smoking", "label": "흡연", "group": "new", "kw": ["흡연", "담배", "smok"]},
    {"id": "drowsy", "label": "졸음/주의산만", "group": "new",
     "kw": ["졸", "엎드", "주의산만", "조는"]},
    {"id": "phone", "label": "작업 중 휴대폰/통화", "group": "new",
     "kw": ["휴대폰", "핸드폰", "통화", "스마트폰", "phone"]},
    {"id": "fight", "label": "폭력/이상행동", "group": "new",
     "kw": ["폭력", "싸움", "다툼", "거친", "이상행동"]},
    {"id": "no_loto", "label": "절차 위반(잠금·표지 없음)", "group": "new",
     "kw": ["잠금장치 없", "loto 없", "표지 없", "경고표지 없", "절차 위반"]},
    # ── 확장: 한국 주요 재해유형별 불안전행동 (2026-07 보강, 전부 VLM 판단) ──
    {"id": "fall_height", "label": "고소작업 추락위험(안전대·난간 미비)", "group": "new",
     "kw": ["고소", "높은 곳", "안전대 미", "안전대 없", "안전난간 없", "난간 없", "개구부", "단부", "비계 끝", "추락 위험"]},
    {"id": "ladder", "label": "사다리 불안전 사용(3점지지 미흡)", "group": "new",
     "kw": ["사다리", "사다리 위", "3점", "삼점지지", "말비계", "a형 사다리"]},
    {"id": "pinch", "label": "끼임 위험(회전체·기계 접근)", "group": "new",
     "kw": ["끼임", "협착", "회전체", "회전 부", "기계에 손", "방호덮개 열", "방호덮개 없", "롤러", "컨베이어"]},
    {"id": "electric", "label": "감전 위험(활선·젖은 손·문어발)", "group": "new",
     "kw": ["감전", "활선", "젖은 손", "누전", "문어발", "임시배선", "전선 피복", "정전작업 미"]},
    {"id": "fire_work", "label": "화기작업 화재위험(가연물·감시자 미비)", "group": "new",
     "kw": ["불티", "용접 불", "가연물", "인화물", "소화기 없", "화기감시자 없", "화재 위험"]},
    {"id": "confined", "label": "밀폐공간 위험(환기·가스측정 미비)", "group": "new",
     "kw": ["밀폐공간", "밀폐 공간", "환기 없", "환기 미", "가스 측정 없", "산소 측정", "질식"]},
    {"id": "struck", "label": "부딪힘·충돌(중장비 사각지대·신호수 없음)", "group": "new",
     "kw": ["부딪", "충돌", "사각지대", "신호수 없", "유도자 없", "후진 중"]},
    {"id": "falling_obj", "label": "낙하물 위험(상하 동시작업·적재불량)", "group": "new",
     "kw": ["낙하물", "떨어지는 물", "상하 동시", "자재 던", "적재 불량", "머리 위 자재"]},
    {"id": "trip", "label": "전도 위험(정리정돈 불량·미끄럼)", "group": "new",
     "kw": ["전도", "걸려 넘", "통로 적치", "정리정돈 불", "미끄러", "젖은 바닥", "장애물"]},
    {"id": "running", "label": "작업장 뛰기·무리한 이동", "group": "new",
     "kw": ["뛰어", "뛰고", "달리", "급하게 이동", "계단 뛰"]},
    {"id": "unstable_platform", "label": "불안정 발판·적재물 위 작업", "group": "new",
     "kw": ["불안정한 발판", "발판 위", "적재물 위", "박스 위", "의자 위", "위태롭게 올라"]},
]

# VLM이 '직접' 구조화 판단(행동+근거+신뢰도)하게 하는 프롬프트. 키워드 매칭은 폴백으로만 사용.
_PROMPT = (
    "너는 산업안전 행동분석 AI다. 사진에서 '명확히 보이는' 위험행동만 판단하라. 추측·과장 금지.\n"
    "아래 JSON 배열 형식으로만 답하라(다른 설명 문장 없이):\n"
    '[{"behavior":"위험행동 이름","evidence":"사진에서 그렇게 판단한 근거","confidence":"높음|중간|낮음"}]\n'
    "위험행동이 없으면 정확히 [] 라고만 답하라.\n"
    "가능하면 다음 표준 이름 중에서 고르되, 해당 없으면 새로 서술해도 된다: "
    + ", ".join(b["label"] for b in BEHAVIORS)
)


def _parse_json_behaviors(txt: str):
    """VLM 응답에서 JSON 배열 추출. 실패 시 None(→키워드 폴백)."""
    import json
    import re
    m = re.search(r"\[.*\]", txt, re.S)
    if not m:
        return [] if "[]" in txt else None
    try:
        data = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else None


def _match_known(name: str):
    """VLM이 낸 행동명을 표준 목록과 소프트 매칭(법령·규칙 연결용). 없으면 None."""
    n = str(name).lower()
    for b in BEHAVIORS:
        lab = b["label"].lower()
        if lab in n or n in lab or any(k.lower() in n for k in b["kw"]):
            return b
    return None


def _keyword_fallback(txt_low: str, rule_set: set) -> list[dict[str, Any]]:
    """폴백: 기존 키워드 매칭(VLM이 JSON을 못 줄 때만)."""
    found = []
    for b in BEHAVIORS:
        vlm_yes = any(k.lower() in txt_low for k in b["kw"])
        rule_yes = b["id"] in rule_set
        if not (vlm_yes or rule_yes):
            continue
        conf = ("높음(규칙+VLM)" if vlm_yes and rule_yes
                else "중상(VLM)" if vlm_yes else "중간(규칙)")
        found.append({"id": b["id"], "label": b["label"], "group": b["group"],
                      "confirmed": bool(vlm_yes and rule_yes), "confidence": conf,
                      "evidence": ""})
    return found


def _build_from_items(items: list, rule_set: set) -> list[dict[str, Any]]:
    """VLM이 낸 행동 리스트(behavior/evidence/confidence)를 표준 출력형으로 변환.
    통합호출·개별호출 공통. 규칙과 교차확인되면 '높음(규칙+VLM)'."""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("behavior", "")).strip()
        if not name:
            continue
        known = _match_known(name)
        bid = known["id"] if known else None
        rule_yes = bool(bid and bid in rule_set)
        conf = str(it.get("confidence", "중간")).strip() or "중간"
        out.append({
            "id": bid,
            "label": known["label"] if known else name,
            "group": known["group"] if known else "new",
            "confirmed": rule_yes,
            "confidence": "높음(규칙+VLM)" if rule_yes else conf + "(VLM)",
            "evidence": str(it.get("evidence", "")).strip(),
        })
    return out


def analyze(image_bgr, use_vlm: bool = True, rule_hits: list[str] | None = None,
            shared: dict[str, Any] | None = None) -> dict[str, Any]:
    """위험행동을 VLM(딥러닝)이 직접 판단·근거·신뢰도로 분석. 폴백: 키워드 매칭.
    rule_hits: 동시에 감지된 규칙 id(있으면 교차확인으로 '높음').
    shared: 통합 장면이해 결과(있으면 behaviors 재사용 → VLM 재호출 없음, 감사 D-1).
    반환: {ok, behaviors:[{id,label,group,confirmed,confidence,evidence}], vlm_used, mode}."""
    rule_set = set(rule_hits or [])
    if not use_vlm or image_bgr is None:
        out = [{"id": b["id"], "label": b["label"], "group": "confirm",
                "confirmed": False, "confidence": "중간(규칙)", "evidence": ""}
               for b in BEHAVIORS if b["id"] in rule_set]
        return {"ok": True, "behaviors": out, "vlm_used": False,
                "note": "VLM을 켜야 위험행동을 딥러닝으로 분석합니다", "mode": "rule_only"}
    # ⓪ 통합 장면이해 결과 재사용(있으면 VLM 개별호출 생략)
    if shared is not None:
        items = shared.get("behaviors", []) if isinstance(shared, dict) else []
        return {"ok": True, "behaviors": _build_from_items(items, rule_set),
                "vlm_used": True, "mode": "vlm_shared"}
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=_PROMPT)
        txt = (str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                                if not str(k).startswith("_")))
               if isinstance(data, dict) else str(data))
    except Exception:  # noqa: BLE001
        return {"ok": True, "behaviors": [], "vlm_used": False,
                "note": "VLM 미가용/실패", "mode": "error"}
    # ① VLM 구조화(JSON) — 딥러닝이 직접 판단(행동+근거+신뢰도)
    items = _parse_json_behaviors(txt)
    if items is not None:
        return {"ok": True, "behaviors": _build_from_items(items, rule_set),
                "vlm_used": True, "mode": "vlm_json"}
    # ② JSON 파싱 실패 → 키워드 폴백(기존 방식)
    return {"ok": True, "behaviors": _keyword_fallback(txt.lower(), rule_set),
            "vlm_used": True, "mode": "keyword_fallback"}
