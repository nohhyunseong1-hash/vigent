"""proximity.py — 동적 작업반경(협착) 감지 + 자동 거리 추정

지게차·차량·중장비가 감지되면, 그 주변 '작업반경'에 사람이 들어왔는지 스스로 판단한다.
고정 위험구역과 달리 장비를 따라다니는 동적 감지다.

거리 추정(B): 카메라 1대로는 정확한 미터를 못 재므로, '장비의 실제 크기'를 기준자로 써서
근사한다. 예) 지게차 가로 약 2.5m → 화면 속 지게차 폭(픽셀/정규화) 으로 '단위당 미터'를 구하고,
사람-장비 간격에 곱해 거리(m)를 추정한다. 보정값(VEHICLE_REF_M)·반경은 조정 가능.
정확도가 더 필요하면 바닥 기준점 보정(호모그래피)으로 확장.
"""
from __future__ import annotations

import tuning

# 작업장비 실제 가로 길이(m) 근사 — 거리 추정 기준자. config/tuning.yaml 로 현장 조정.
_DEFAULT_REF = {"forklift": 2.5, "truck": 6.0, "car": 4.5, "bus": 11.0,
                "motorcycle": 2.0, "crane": 8.0, "excavator": 6.0}
VEHICLE_REF_M = {**_DEFAULT_REF, **(tuning.section("proximity").get("vehicle_ref_m") or {})}
DEFAULT_RADIUS_M = float(tuning.val("proximity", "radius_m", 3.0))


def _gap(a: list[float], b: list[float]) -> float:
    """두 박스([x1,y1,x2,y2])의 최단 거리(겹치면 0). 입력 단위 그대로 반환."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def detect(detections, radius_m: float = DEFAULT_RADIUS_M) -> list[dict]:
    """detections: [{label|class, bbox:[x1,y1,x2,y2] 정규화 0~1}]
    반환: 반경 내 (장비-사람) 쌍 [{vehicle, distance_m, person_bbox}], 가까운 순."""
    vehicles, persons = [], []
    for d in detections:
        cls = str(d.get("label") or d.get("class") or "").lower()
        bb = d.get("bbox", [0, 0, 0, 0])
        if len(bb) != 4:
            continue
        if cls in VEHICLE_REF_M:
            vw, vh = bb[2] - bb[0], bb[3] - bb[1]
            # 명백한 오탐(화면 거의 전체)만 제외. 가까운 장비는 박스가 커도 정상이므로 살린다
            # (안전상 '놓침'이 '헛알람'보다 위험 → 보수적으로 살리는 쪽).
            if vw > 0.9 or vw * vh > 0.7:
                continue
            vehicles.append((cls, bb))
        elif cls == "person":
            persons.append(bb)
    out = []
    for vcls, vbox in vehicles:
        vw = max(1e-4, vbox[2] - vbox[0])        # 장비 가로폭(정규화)
        m_per_unit = VEHICLE_REF_M[vcls] / vw    # 단위(정규화)당 미터
        for pbox in persons:
            dist_m = _gap(vbox, pbox) * m_per_unit
            if dist_m <= radius_m:
                out.append({"vehicle": vcls, "distance_m": round(dist_m, 1), "person_bbox": pbox})
    out.sort(key=lambda x: x["distance_m"])
    return out
