"""COCO-17 키포인트 → 학습용 특징 벡터 (numpy만 사용).

관절 각도 + 몸통/목 기울기로 구성된 view에 비교적 강건한 특징을 만든다.
모든 값은 0~1로 정규화되어 신경망 입력에 적합하다. TensorFlow가 없어도
동작하므로 단독 테스트가 가능하다.
"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np

# COCO-17 키포인트 인덱스
NOSE, LEYE, REYE, LEAR, REAR = 0, 1, 2, 3, 4
LSH, RSH, LEL, REL, LWR, RWR = 5, 6, 7, 8, 9, 10
LHIP, RHIP, LKNEE, RKNEE, LANK, RANK = 11, 12, 13, 14, 15, 16

# 특징 이름(순서 = 벡터 순서). 학습/추론/내보내기에서 동일하게 사용한다.
FEATURE_NAMES: List[str] = [
    "left_elbow", "right_elbow",
    "left_knee", "right_knee",
    "left_hip", "right_hip",
    "left_shoulder", "right_shoulder",
    "torso_incline",   # 몸통이 수직에서 벗어난 각 (허리 굽힘)
    "neck_forward",    # 목이 앞으로 빠진 각 (거북목)
]
NUM_FEATURES = len(FEATURE_NAMES)


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """점 b를 꼭짓점으로 하는 ∠ABC (도). 좌표가 비면 180(편 상태) 반환."""
    if a is None or b is None or c is None:
        return 180.0
    ba = a - b
    bc = c - b
    na = float(np.linalg.norm(ba))
    nc = float(np.linalg.norm(bc))
    if na < 1e-6 or nc < 1e-6:
        return 180.0
    cosang = float(np.dot(ba, bc) / (na * nc))
    cosang = max(-1.0, min(1.0, cosang))
    return float(np.degrees(np.arccos(cosang)))


def _incline_from_vertical(p_low: np.ndarray, p_high: np.ndarray) -> float:
    """두 점을 잇는 선분이 수직축에서 벗어난 각(도, 0=완전 수직)."""
    v = p_high - p_low
    n = float(np.linalg.norm(v))
    if n < 1e-6:
        return 0.0
    # 이미지 좌표는 y가 아래로 증가 → 수직 위 방향은 (0,-1)
    vertical = np.array([0.0, -1.0])
    cosang = float(np.dot(v / n, vertical))
    cosang = max(-1.0, min(1.0, cosang))
    return float(np.degrees(np.arccos(cosang)))


def _mid(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a + b) / 2.0


def extract_features(keypoints: Sequence[Sequence[float]]) -> np.ndarray:
    """COCO-17 [x,y] 17개 → 정규화된 특징 벡터(shape=[NUM_FEATURES])."""
    kp = np.asarray(keypoints, dtype=np.float32)
    if kp.shape[0] < 17:
        # 부족하면 0패딩 (편 상태 기본값으로 처리)
        pad = np.zeros((17 - kp.shape[0], 2), dtype=np.float32)
        kp = np.vstack([kp[:, :2], pad]) if kp.size else np.zeros((17, 2), np.float32)
    kp = kp[:, :2]

    shoulder_mid = _mid(kp[LSH], kp[RSH])
    hip_mid = _mid(kp[LHIP], kp[RHIP])

    angles = [
        _angle(kp[LSH], kp[LEL], kp[LWR]),    # left_elbow
        _angle(kp[RSH], kp[REL], kp[RWR]),    # right_elbow
        _angle(kp[LHIP], kp[LKNEE], kp[LANK]),  # left_knee
        _angle(kp[RHIP], kp[RKNEE], kp[RANK]),  # right_knee
        _angle(kp[LSH], kp[LHIP], kp[LKNEE]),   # left_hip
        _angle(kp[RSH], kp[RHIP], kp[RKNEE]),   # right_hip
        _angle(kp[LEL], kp[LSH], kp[LHIP]),     # left_shoulder
        _angle(kp[REL], kp[RSH], kp[RHIP]),     # right_shoulder
    ]
    torso_incline = _incline_from_vertical(hip_mid, shoulder_mid)
    neck_forward = _incline_from_vertical(shoulder_mid, kp[NOSE])

    feats = np.array(angles + [torso_incline, neck_forward], dtype=np.float32)
    # 정규화: 관절각/180, 기울기/90 (모두 0~1로 클램프)
    norm = np.empty(NUM_FEATURES, dtype=np.float32)
    norm[:8] = np.clip(feats[:8] / 180.0, 0.0, 1.0)
    norm[8:] = np.clip(feats[8:] / 90.0, 0.0, 1.0)
    return norm
