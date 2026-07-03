"""hazard_rules.py — 결정적 위험목록층(규칙 기반, 모델 무관).

YOLO 탐지 → 위험 '정답' 목록. 등급·법령은 기존 RULE_KB(agents.scribe)에서 재사용한다(새로 지어내지 않음).
VLM이 서술에서 빠뜨려도 이 목록이 커버리지 100%를 보장한다(가산식·폴백 — 규칙 6).
"""
from __future__ import annotations

from typing import Any

# YOLO NO-* 클래스(소문자) → 항목명. 등급/법령은 모두 RULE_KB "ppe_missing" 에서 재사용.
_PPE_MAP = {
    "no-hardhat": "안전모 미착용",
    "no-mask": "마스크 미착용",
    "no-safety-vest": "안전조끼 미착용",
    "no-gloves": "장갑 미착용",
    "no-goggles": "보안경 미착용",
    "no-boots": "안전화 미착용",
}
# RULE_KB 의 중대성(sev 1~3) → 등급 라벨. sev 값을 그대로 읽어 라벨링(새 수치 안 만듦).
_SEV_TIER = {3: "높음", 2: "중간", 1: "낮음"}


def _rule_kb() -> dict:
    """등급·법령 정답 소스 = 기존 RULE_KB(중복 로직 안 만듦). 못 읽으면 빈 dict(폴백)."""
    try:
        from agents.scribe import RULE_KB
        return RULE_KB
    except Exception:  # noqa: BLE001
        return {}


def _label(d: dict) -> str:
    return str(d.get("label") or d.get("cls") or d.get("class") or "").strip()


def _conf(d: dict) -> Any:
    return d.get("conf", d.get("confidence"))


def build_hazard_list(detections, in_danger_zone: bool = False) -> list[dict[str, Any]]:
    """탐지 → [{항목, 등급, 근거탐지, 법령, 규칙코드, 출처}] (100% 탐지 기반).
    등급=RULE_KB 중대성(sev) 재사용, 법령=RULE_KB law 재사용(없으면 생략).
    같은 항목(예: NO-Hardhat 중복 검출)은 최고 신뢰도 1개로 합친다. 없으면 빈 리스트."""
    kb = _rule_kb()

    def _item(rule: str, 항목: str, 클래스: str, conf: Any) -> dict[str, Any]:
        r = kb.get(rule, {})
        sev = int(r.get("sev", 2))
        return {"항목": 항목, "등급": _SEV_TIER.get(sev, "중간"),
                "근거탐지": {"클래스": 클래스, "신뢰도": conf},
                "법령": r.get("law", ""), "규칙코드": rule,
                "출처": "규칙층(YOLO 탐지 기반)"}

    items: list[dict[str, Any]] = []
    # 위험구역 침입(사람 신뢰도를 근거로)
    person_conf = None
    for d in detections or []:
        if isinstance(d, dict) and _label(d).lower() in ("person", "사람"):
            person_conf = _conf(d)
            break
    if in_danger_zone:
        items.append(_item("zone_intrusion", "위험구역 침입", "사람(위험구역 내부)", person_conf))

    # NO-* 보호구(같은 항목 중복 제거, 최고 신뢰도 유지)
    best: dict[str, dict[str, Any]] = {}
    for d in detections or []:
        if not isinstance(d, dict):
            continue
        low = _label(d).lower()
        if low not in _PPE_MAP:
            continue
        항목 = _PPE_MAP[low]
        conf = _conf(d)
        prev = best.get(항목)
        try:
            better = prev is None or (conf is not None
                                      and float(conf) > float(prev["근거탐지"]["신뢰도"] or 0))
        except (TypeError, ValueError):
            better = prev is None
        if better:
            best[항목] = _item("ppe_missing", 항목, _label(d), conf)
    items.extend(best.values())
    return items
