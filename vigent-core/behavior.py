"""behavior.py — VLM 기반 행동 분석 (신뢰도 보강 + 신규 행동)

규칙 감지(낙상·무동작·협착·근골격계)는 카메라 각도·임계값에 따라 오탐이 생겨 '중간' 신뢰도였다.
여기에 VLM(언어모델) 이중확인을 붙이면 오탐이 걸러져 실효 신뢰도가 '높음'이 된다(가산식).
또 VLM은 open-vocabulary 라 class 목록에 없던 행동(흡연·졸음·통화·폭력·절차위반)도 질문으로 판단한다.

⚠ VLM은 확률적이라 보조 신호다. 규칙 신호와 결합(확인)될 때 가장 신뢰할 수 있다.
"""
from __future__ import annotations

from typing import Any

# group: confirm(기존 규칙 재확인 → 신뢰도↑) / new(VLM이라 가능해진 신규 행동)
# kw: VLM 응답에서 이 키워드가 보이면 해당 행동으로 판정
BEHAVIORS: list[dict[str, Any]] = [
    {"id": "fall", "label": "쓰러짐(낙상)", "group": "confirm",
     "kw": ["쓰러", "넘어", "낙상", "추락"]},
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
]

_PROMPT = (
    "너는 산업안전 행동분석 AI다. 아래 사진에서 '명확히 보이는' 위험행동만 한국어로 "
    "쉼표로 나열하라. 추측·과장 금지. 해당 없으면 정확히 '없음'이라고만 답하라.\n"
    "후보 행동: " + ", ".join(b["label"] for b in BEHAVIORS)
)


def analyze(image_bgr, use_vlm: bool = True, rule_hits: list[str] | None = None) -> dict[str, Any]:
    """사진의 위험행동을 VLM으로 분석. rule_hits: 동시에 감지된 규칙 id(있으면 '확인'으로 신뢰도↑).
    반환: {ok, behaviors:[{id,label,group,confirmed,confidence}], vlm_used}."""
    rule_set = set(rule_hits or [])
    if not use_vlm or image_bgr is None:
        # VLM 없으면 규칙 신호만 통과(신규 행동은 판단 불가)
        out = [{"id": b["id"], "label": b["label"], "group": "confirm",
                "confirmed": False, "confidence": "중간(규칙)"}
               for b in BEHAVIORS if b["id"] in rule_set]
        return {"ok": True, "behaviors": out, "vlm_used": False,
                "note": "신규 행동(흡연·졸음 등)은 VLM을 켜야 판단됩니다"}
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=_PROMPT)
        txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                               if not str(k).startswith("_"))).lower()
    except Exception:  # noqa: BLE001
        return {"ok": True, "behaviors": [], "vlm_used": False, "note": "VLM 미가용/실패"}
    found = []
    for b in BEHAVIORS:
        vlm_yes = any(k.lower() in txt for k in b["kw"])
        rule_yes = b["id"] in rule_set
        if not (vlm_yes or rule_yes):
            continue
        # 규칙+VLM 둘 다 → 높음 / VLM만 → 신규는 '중상' / 규칙만 → 중간
        if vlm_yes and rule_yes:
            conf = "높음(규칙+VLM)"
        elif vlm_yes:
            conf = "중상(VLM)"
        else:
            conf = "중간(규칙)"
        found.append({"id": b["id"], "label": b["label"], "group": b["group"],
                      "confirmed": bool(vlm_yes and rule_yes), "confidence": conf})
    return {"ok": True, "behaviors": found, "vlm_used": True}
