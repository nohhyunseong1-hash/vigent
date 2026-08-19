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


def driver_containment() -> float:
    """[G5] 운전자 판정 포함률 임계 — person 박스가 장비 박스에 이 비율 이상 포함되면 '탑승'.

    근거(학원 유사 영상 320프레임 실측, benchmarks/forklift_duel_2026-08-19.md G5 절):
    포함률 분포가 완전 이봉이다 — 보행자 0.0 vs 탑승 운전자 1.0, 중간(0.2~0.6)은 2프레임뿐.
    0.65 는 운전자를 확실히 제외하면서, 하차 시 박스가 분리되기 시작하면 **즉시** 보행자로
    복귀시킨다(하차 직후가 협착 최고 위험 — 제외가 과하면 안 된다). 1.0 초과로 설정하면
    사실상 비활성(구 동작 복원 = 롤백 경로).
    """
    return float(tuning.val("proximity", "driver_containment", 0.65))


def _containment(p: list[float], f: list[float]) -> float:
    """person 박스가 장비 박스에 포함된 비율 = 교집합 면적 / person 면적 (0~1)."""
    ix = max(0.0, min(p[2], f[2]) - max(p[0], f[0]))
    iy = max(0.0, min(p[3], f[3]) - max(p[1], f[1]))
    pa = max(1e-9, (p[2] - p[0]) * (p[3] - p[1]))
    return ix * iy / pa


def onboard_vehicle(pbox: list[float], detections: list[dict]) -> bool:
    """[G5] 이 person 이 어느 장비에든 '탑승' 상태인가 — zone_intrusion 등 외부 판정 공유용.

    detections 전체에서 장비 클래스 박스를 뽑아 포함률을 검사한다. 장비 검출이 없으면 False
    (제외 없음 — 기존 동작). 판정은 프레임 단위라 하차로 박스가 분리되면 그 즉시 False."""
    thr = driver_containment()
    if thr > 1.0:
        return False
    for d in detections:
        cls = str(d.get("label") or d.get("class") or "").lower()
        if cls not in VEHICLE_REF_M:
            continue
        vb = d.get("bbox", [0, 0, 0, 0])
        if len(vb) == 4 and _containment(pbox, vb) >= thr:
            return True
    return False


def _gap(a: list[float], b: list[float], aspect_hw: float = 1.0) -> float:
    """두 박스([x1,y1,x2,y2])의 최단 거리(겹치면 0). 입력 단위 그대로 반환.
    ⚠ bbox는 x=폭(w)·y=높이(h)로 각각 정규화되어 x·y 스케일이 다르다(감사 E-1).
    거리계산은 x(폭) 기준이므로, y는 종횡비 h/w(aspect_hw)로 스케일을 맞춰야 정확하다.
    aspect_hw=1.0(기본)이면 무보정(정사각 가정) — 종횡비를 모르는 호출부의 안전 폴백."""
    dx = max(a[0] - b[2], b[0] - a[2], 0.0)
    dy = max(a[1] - b[3], b[1] - a[3], 0.0) * aspect_hw   # y를 x(폭) 스케일로 환산
    return (dx * dx + dy * dy) ** 0.5


def detect(detections, radius_m: float = DEFAULT_RADIUS_M,
           aspect_hw: float | None = None) -> list[dict]:
    """detections: [{label|class, bbox:[x1,y1,x2,y2] 정규화 0~1}]
    aspect_hw: 프레임 세로/가로 비(h/w). 주면 세로거리 과대추정을 바로잡는다(감사 E-1).
      없으면 1.0(무보정) — 회귀 없음(기존과 동일). 안전상 세로거리 과대→미탐이므로 넣는 게 좋다.
    반환: 반경 내 (장비-사람) 쌍 [{vehicle, distance_m, person_bbox}], 가까운 순."""
    ar = 1.0 if aspect_hw is None else max(1e-3, float(aspect_hw))
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
    thr = driver_containment()
    for vcls, vbox in vehicles:
        vw = max(1e-4, vbox[2] - vbox[0])        # 장비 가로폭(정규화)
        m_per_unit = VEHICLE_REF_M[vcls] / vw    # 단위(정규화)당 미터
        for pbox in persons:
            # [G5] 운전자 제외: 이 장비 박스에 크게 포함된 person = 탑승자 → 이 장비와의
            #   쌍만 제외한다(다른 장비와의 근접은 유지 — 보수적). 실측 근거는
            #   driver_containment() docstring. 하차로 박스가 분리되면 즉시 다시 센다.
            if thr <= 1.0 and _containment(pbox, vbox) >= thr:
                continue
            dist_m = _gap(vbox, pbox, ar) * m_per_unit
            if dist_m <= radius_m:
                out.append({"vehicle": vcls, "distance_m": round(dist_m, 1), "person_bbox": pbox})
    out.sort(key=lambda x: x["distance_m"])
    return out
