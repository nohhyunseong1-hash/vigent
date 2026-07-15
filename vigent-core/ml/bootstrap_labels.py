"""규칙 기반 라벨러(약지도학습의 '선생님') + 합성 데이터 생성.

핵심 아이디어: 지금의 하드코딩 규칙으로 1차 라벨을 자동 생성해 학습을 시작하고,
이후 데이터 엔진이 모은 사람 검수 라벨로 점진 개선한다(규칙을 흉내 → 능가).

라벨: 0=safe(정상), 1=caution(주의), 2=danger(위험)
입력은 pose_features.extract_features 가 만든 정규화 특징 벡터다.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from .pose_features import FEATURE_NAMES, NUM_FEATURES

CLASS_NAMES = ["safe", "caution", "danger"]
NUM_CLASSES = len(CLASS_NAMES)

# 특징 인덱스
_IDX = {name: i for i, name in enumerate(FEATURE_NAMES)}
_TORSO = _IDX["torso_incline"]
_NECK = _IDX["neck_forward"]
_LKNEE = _IDX["left_knee"]
_RKNEE = _IDX["right_knee"]


def rule_label(features: np.ndarray) -> int:
    """규칙 선생님: 정규화 특징 벡터 -> 위험 등급(0/1/2).

    정규화 기준(pose_features): 기울기 = 각/90, 무릎각 = 각/180.
    """
    f = np.asarray(features, dtype=np.float32)
    torso = float(f[_TORSO])          # 0.5 ≈ 45°, 0.28 ≈ 25°
    neck = float(f[_NECK])            # 0.45 ≈ 40°
    knee_min = float(min(f[_LKNEE], f[_RKNEE]))  # 0.5 = 90°, <0.33 ≈ 매우 굽힘

    # 위험: 심한 허리 굽힘 / 심한 거북목 / 굽힌 자세에서 깊은 무릎 굴곡
    if torso >= 0.50 or neck >= 0.45 or (knee_min < 0.33 and torso >= 0.33):
        return 2
    # 주의: 중간 정도
    if torso >= 0.28 or neck >= 0.28 or knee_min <= 0.45:
        return 1
    return 0


def make_dataset(n: int = 6000, seed: int = 42) -> Tuple[np.ndarray, np.ndarray]:
    """규칙으로 라벨링한 합성 학습셋 생성.

    관절각/기울기 특징을 그럴듯한 범위에서 샘플링하고 rule_label로 라벨링한다.
    위험 클래스가 희소해지지 않도록 일부 표본을 굽힘 쪽으로 편향한다.
    """
    rng = np.random.default_rng(seed)
    X = rng.random((n, NUM_FEATURES)).astype(np.float32)

    # 관절각(앞 8개)은 대체로 펴진 쪽(0.5~1.0)에 더 분포
    X[:, :8] = (0.45 + 0.55 * rng.random((n, 8))).astype(np.float32)
    # 표본의 1/3은 굽힘/거북목을 강조해 danger/caution 균형 확보
    bend = rng.random(n) < 0.35
    X[bend, _TORSO] = (0.30 + 0.70 * rng.random(bend.sum())).astype(np.float32)
    X[bend, _NECK] = (0.20 + 0.70 * rng.random(bend.sum())).astype(np.float32)
    deep = rng.random(n) < 0.25
    X[deep, _LKNEE] = (0.15 + 0.35 * rng.random(deep.sum())).astype(np.float32)
    X[deep, _RKNEE] = (0.15 + 0.35 * rng.random(deep.sum())).astype(np.float32)

    y = np.array([rule_label(x) for x in X], dtype=np.int64)
    return X, y
