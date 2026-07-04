"""pose.rtmpose_adapter — RTMPose(rtmlib, Apache-2.0) 포즈 어댑터 (T10c).

출력 형식은 기존 yolov8n-pose 소비층과 동일:
    persons(frame) → [(kp_xy[17,2] 픽셀좌표 float, kp_cf[17] float), ...]  · COCO-17 순서.

Stage 1: rtmlib 내장 검출기(RTMDet)로 사람 박스 확보(top-down). bboxes=None.
Stage 2: 외부 사람 박스(RF-DETR person) 주입 → 내장 검출 생략(bboxes 인자).
COCO-17 순서 보존을 assert 로 강제(하류가 인덱스 5,6=어깨 / 11,12=엉덩이 등에 하드코딩됨).

절대 저하 없음(§2): 로딩·추론 실패는 예외를 올려 호출자가 폴백/비활성. rtmlib 는 onnxruntime(CPU) 사용.
"""
from __future__ import annotations

from typing import Any

import numpy as np

_COCO17 = 17


class RtmPoseDetector:
    def __init__(self, mode: str = "balanced", device: str = "cpu", backend: str = "onnxruntime"):
        from rtmlib import Body   # lazy import — 사용 시에만 로드(모델 onnx 최초 1회 다운로드)
        # Body = RTMDet(사람검출) + RTMPose(포즈), to_openpose=False → COCO-17 출력.
        self._body = Body(mode=mode, backend=backend, device=device)
        self._mode, self._device = mode, device

    def persons(self, frame, bboxes: Any = None) -> list[tuple[np.ndarray, np.ndarray]]:
        """프레임 → 사람별 (kp_xy[17,2] px, kp_cf[17]). 사람 없으면 [].

        bboxes=None  → Stage 1: rtmlib Body 내장 검출기(RTMDet/YOLOX)로 사람 박스 확보.
        bboxes=[[x1,y1,x2,y2],..](픽셀) → Stage 2: 외부 사람 박스(RF-DETR person) 주입 → 포즈만 추정.
        """
        if bboxes is not None:
            if len(bboxes) == 0:
                return []
            keypoints, scores = self._body.pose_model(frame, bboxes=list(bboxes))   # top-down pose-only
        else:
            keypoints, scores = self._body(frame)
        out: list[tuple[np.ndarray, np.ndarray]] = []
        for i in range(len(keypoints)):
            kp = np.asarray(keypoints[i], dtype=float)     # [17,2]
            cf = np.asarray(scores[i], dtype=float)         # [17]
            assert kp.shape[0] == _COCO17, f"COCO-17 아님(순서 보존 위반): keypoints shape={kp.shape}"
            assert cf.shape[0] == _COCO17, f"COCO-17 아님: scores shape={cf.shape}"
            out.append((kp, cf))
        return out
