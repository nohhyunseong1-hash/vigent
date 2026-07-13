"""labels.py — 클래스 영문라벨 → 한국어 '표시명' 단일 소스 (감사 C-3)

과거엔 같은 영문→한국어 표시 맵이 화면 JS 3곳(incident·evaluator·safety_brain)과
Python 에 흩어져, 클래스 추가/표기 변경 시 일부만 고쳐 불일치가 났다. 여기로 모은다.
- Python: labels.ko("NO-Hardhat") → "안전모 미착용"
- JS(프론트): render()가 labels.js_snippet() 을 주입 → 페이지들이 공용 ko() 사용.
대소문자 무시(모델은 'NO-Hardhat', 일부 코드는 소문자라 둘 다 조회되게 소문자 인덱스 사용).
"""
from __future__ import annotations

import json

# 표준 표시명(모델 출력 라벨 기준). 새 클래스는 '여기만' 추가.
CLS_KO: dict[str, str] = {
    # PPE 표준
    "Hardhat": "안전모", "NO-Hardhat": "안전모 미착용",
    "Safety-Vest": "안전조끼", "NO-Safety-Vest": "안전조끼 미착용",
    "Mask": "마스크", "NO-Mask": "마스크 미착용",
    "Gloves": "장갑", "NO-Gloves": "장갑 미착용",
    "Goggles": "보안경", "NO-Goggles": "보안경 미착용",
    "Boots": "안전화", "NO-Boots": "안전화 미착용",
    "Person": "사람",
    # PPE 모델(건설안전 10클래스 데이터셋) 출력이나 표시맵에 없어 영문 노출되던 것 보완
    #   모델 원문 표기 그대로 매칭(finalize_box 는 미매칭 시 원문 통과 → ko() 소문자조회):
    #   'machinery', 'vehicle', 'Safety Cone'
    "machinery": "기계·설비", "vehicle": "차량", "Safety Cone": "안전콘",
    # 차량·장비·기타
    "forklift": "지게차", "truck": "트럭", "car": "차량", "bus": "버스",
    "train": "차량", "boat": "차량", "motorcycle": "오토바이", "bicycle": "자전거",
    "fire": "화재", "smoke": "연기", "knife": "칼", "scissors": "가위",
}

# 대소문자 무시 조회용 소문자 인덱스
_LC: dict[str, str] = {k.lower(): v for k, v in CLS_KO.items()}


def ko(c: str) -> str:
    """영문 클래스 → 한국어 표시명(대소문자 무시). 없으면 원문 그대로."""
    return _LC.get(str(c or "").lower(), c)


def js_snippet() -> str:
    """프론트 주입용: 공용 ko() 정의. 각 페이지 템플릿의 {{LABELS_KO}} 자리에 넣는다."""
    return ("const _KO=" + json.dumps(_LC, ensure_ascii=False) + ";"
            "function ko(c){return _KO[String(c||'').toLowerCase()]||c;}")
