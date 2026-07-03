"""ergonomics.py — 근골격계 자세평가 '각도 계산 레이어'(스크리닝용).

포즈(yolov8n-pose)의 COCO-17 키포인트 → 목/허리/어깨 굽힘 각도 → 등급(good/warn/bad).
순수 가산: 기존 낙상·탐지와 독립적으로 동작한다. 키포인트가 없거나 저신뢰면 해당 관절을
조용히 skip 하고, 판정할 수 없으면 빈 dict 를 반환한다(무중단·폴백).

⚠ 이 값은 '2D 근사'다. 단일 카메라 영상에서 추정한 2D 각도라, 카메라 각도·원근·자기가림
   (self-occlusion)에 따라 실제 3차원 관절 각도와 차이가 난다. 따라서 REBA/RULA 같은 정밀
   인간공학 평가의 '공식 측정값'이 아니라 '위험 자세 스크리닝(선별)' 신호다.
   확정 진단·법적 근거로 단독 사용하지 말 것 — 현장 관찰·전문가 평가의 보조로만 쓴다.

임계값(good/warn)은 하드코딩하지 않고 vision.yaml(judgment.ergonomics.joints)에서 주입받는다.
"""
from __future__ import annotations

import math
from typing import Any

# COCO-17 키포인트 인덱스
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SH, R_SH, L_EL, R_EL = 5, 6, 7, 8
L_HIP, R_HIP = 11, 12

_MIN_CONF = 0.3                                  # 이 신뢰도 미만 관절은 제외
_GRADE_W = {"good": 0, "warn": 1, "bad": 2}      # 등급 가중(간이 위험지수·최악등급 비교용)
_LEVEL_BY_GRADE = {"good": "낮음", "warn": "중간", "bad": "높음"}
_KNAME = {"neck": "목", "trunk": "허리", "shoulder": "어깨"}


def _mid(xy, cf, idxs, min_conf):
    """주어진 키포인트들 중 신뢰도 통과분의 평균 좌표. 없으면 None."""
    pts = [xy[i] for i in idxs if i < len(cf) and cf[i] >= min_conf]
    if not pts:
        return None
    return (sum(float(p[0]) for p in pts) / len(pts),
            sum(float(p[1]) for p in pts) / len(pts))


def _vert_angle(dx, dy):
    """수직(세로)축 대비 벡터 각도(도). 0=수직, 90=수평. (낙상 코드와 동일 방식)"""
    return math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))


def _grade(angle, good, warn):
    if angle <= good:
        return "good"
    if angle <= warn:
        return "warn"
    return "bad"


def assess(keypoints_xy, conf, thresholds, min_conf: float = _MIN_CONF) -> dict[str, Any]:
    """사람 1명의 COCO-17 키포인트 → 각도·등급·요약(2D 근사·스크리닝).

    keypoints_xy: [[x,y], ...] 길이 17 · conf: [c, ...] 길이 17
    thresholds:   vision.yaml 의 joints dict {neck:{good,warn}, trunk:{...}, shoulder:{...}}
    필요한 키포인트가 없거나 저신뢰면 해당 관절 skip. 하나도 판정 못 하면 {} 반환.
    반환: {angles, grades, level(낮음/중간/높음), note, reba_hint(간이 0~6), worst}
    """
    xy, cf = keypoints_xy, conf
    joints = thresholds if isinstance(thresholds, dict) else {}
    angles: dict[str, float] = {}
    grades: dict[str, str] = {}

    sh_c = _mid(xy, cf, [L_SH, R_SH], min_conf)          # 어깨중점
    hip_c = _mid(xy, cf, [L_HIP, R_HIP], min_conf)       # 골반중점
    head = _mid(xy, cf, [NOSE, L_EAR, R_EAR], min_conf)  # 머리(코·귀)

    # trunk(허리): 골반중점→어깨중점 벡터의 수직 대비 각(0수직~90수평). 곧게 서면 0°에 가깝다.
    if sh_c and hip_c and "trunk" in joints:
        a = _vert_angle(hip_c[0] - sh_c[0], hip_c[1] - sh_c[1])
        angles["trunk"] = round(a, 1)
        grades["trunk"] = _grade(a, joints["trunk"].get("good", 20), joints["trunk"].get("warn", 45))

    # neck(목): 어깨중점→머리 벡터의 수직 대비 각. 목을 앞으로 숙일수록 커진다.
    if sh_c and head and "neck" in joints:
        a = _vert_angle(head[0] - sh_c[0], head[1] - sh_c[1])
        angles["neck"] = round(a, 1)
        grades["neck"] = _grade(a, joints["neck"].get("good", 15), joints["neck"].get("warn", 25))

    # shoulder(어깨): 좌우 어깨 높이차 / 어깨너비 → 비대칭각(도). 한쪽을 들면 커진다.
    lsh = xy[L_SH] if len(cf) > L_SH and cf[L_SH] >= min_conf else None
    rsh = xy[R_SH] if len(cf) > R_SH and cf[R_SH] >= min_conf else None
    if lsh is not None and rsh is not None and "shoulder" in joints:
        dyv = abs(float(lsh[1]) - float(rsh[1]))
        bw = abs(float(lsh[0]) - float(rsh[0])) + 1e-6
        a = math.degrees(math.atan2(dyv, bw))
        angles["shoulder"] = round(a, 1)
        grades["shoulder"] = _grade(a, joints["shoulder"].get("good", 12), joints["shoulder"].get("warn", 25))

    if not grades:                                        # 판정 가능한 관절 없음 → 폴백(skip)
        return {}

    worst = max(grades.values(), key=lambda g: _GRADE_W[g])
    level = _LEVEL_BY_GRADE[worst]

    bad_parts = [f"{_KNAME[k]} {angles[k]:.0f}°" for k, g in grades.items() if g in ("warn", "bad")]
    if bad_parts:
        note = "근골격계 부담 자세 — " + ", ".join(bad_parts) + " 굽힘/비대칭(2D 근사·스크리닝)"
    else:
        ok = ", ".join(f"{_KNAME[k]} {angles[k]:.0f}°" for k in angles)
        note = f"자세 양호 — {ok}(2D 근사)"

    reba_hint = sum(_GRADE_W[g] for g in grades.values())   # 간이 위험지수(0~6). 공식 REBA 점수 아님.

    return {"angles": angles, "grades": grades, "level": level,
            "note": note, "reba_hint": reba_hint, "worst": worst}


def load_ergonomics(theme: str = "safety") -> dict[str, Any]:
    """vision.yaml(judgment.ergonomics) 블록 로드 — joints·hold_sec 등. 실패 시 {}(호출부 폴백)."""
    try:
        import vision_loader
        erg = vision_loader.load_vision(theme).raw.get("judgment", {}).get("ergonomics", {})
        return erg if isinstance(erg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}
