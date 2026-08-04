"""press_zone — 프레스 방호구역 '부위별' 침입 판정(2.6).

⚠️ 안전경계(CLAUDE.md): 비전 ML 은 확률적이라 인증 안전기능을 대체하지 못한다. 프레스·전단기의
1차 방호 책임은 인증 하드웨어(Type 4 광전자식 방호장치·안전 PLC)에 있다. 본 판정은 그 보조·예방
계층으로 **경고·기록용 신호만** 제공한다 — E-stop 을 대신하지 않는다.

규칙(사람별, COCO-17 keypoint):
  · 허용 부위: 팔꿈치(7,8)·손목(9,10) + 손 추정점(손목을 팔꿈치→손목 방향으로 팔뚝×0.5 연장)
    → 구역 안이어도 위반 아님(정상 작업).
  · 금지 부위: 그 외 keypoint(머리·어깨·몸통·하체) 중 conf≥kp_conf 가 폴리곤 내부면 위반.
    상완(어깨-팔꿈치) 선분이 폴리곤과 교차해도 위반(머리 숙여 들어가는 자세 대비).
좌표: keypoints=전송이미지 픽셀, zones=정규화(0~1) → keypoint 를 W,H 로 정규화해 비교.
"""
from __future__ import annotations

from typing import Any

ALLOWED_KP = {7, 8, 9, 10}          # 팔꿈치·손목(팔뚝·손 = 정상 작업 부위)
_PART_NAME = {0: "머리", 1: "머리", 2: "머리", 3: "머리", 4: "머리",
              5: "어깨", 6: "어깨", 11: "몸통", 12: "몸통",
              13: "하체", 14: "하체", 15: "하체", 16: "하체"}
_UPPER_ARM = [(5, 7), (6, 8)]       # 상완(어깨-팔꿈치)


def zone_points_to_poly(points: list[dict]) -> list[tuple[float, float]]:
    """zone_get 형식 [{x,y},...] → [(x,y),...] 정규화 폴리곤."""
    return [(float(p["x"]), float(p["y"])) for p in (points or []) if "x" in p and "y" in p]


def _in_poly(x: float, y: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _ccw(a, b, c) -> bool:
    return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])


def _seg_hits_poly(p1, p2, poly: list[tuple[float, float]]) -> bool:
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        if _ccw(p1, a, b) != _ccw(p2, a, b) and _ccw(p1, p2, a) != _ccw(p1, p2, b):
            return True
    return False


def evaluate(poses: list[dict], polys: list[list[tuple[float, float]]],
             W: float, H: float, kp_conf: float = 0.5) -> list[dict[str, Any]]:
    """사람별 방호구역 부위 침입 판정. 반환: 위반자만 [{id, parts:[부위명]}]."""
    polys = [p for p in polys if len(p) >= 3]
    if not poses or not polys or W <= 0 or H <= 0:
        return []
    out: list[dict[str, Any]] = []
    for p in poses:
        kp = p.get("keypoints") or []
        cf = p.get("keypoint_confidence") or []
        if len(kp) < 17:
            continue
        nkp = [(kp[i][0] / W, kp[i][1] / H) for i in range(len(kp))]
        parts: set[str] = set()
        for i, (x, y) in enumerate(nkp):
            if i in ALLOWED_KP or i not in _PART_NAME:
                continue
            if i >= len(cf) or cf[i] < kp_conf:
                continue
            if any(_in_poly(x, y, z) for z in polys):
                parts.add(_PART_NAME[i])
        for a, b in _UPPER_ARM:            # 상완 선분 교차(머리 숙임)
            if a < len(cf) and b < len(cf) and cf[a] >= kp_conf and cf[b] >= kp_conf:
                if any(_seg_hits_poly(nkp[a], nkp[b], z) for z in polys):
                    parts.add("어깨")
        if parts:
            out.append({"id": p.get("id", -1), "parts": sorted(parts)})
    return out
