"""tests/test_rfdetr_onnx_parity.py — [C-3] torch vs ONNX 백엔드 검출 결과 일치 회귀.

[C-2]에서 벤치마크 스크립트의 전처리 버그(PIL 기본 보간 BICUBIC vs RF-DETR 내부
torchvision.transforms.functional.resize 기본 보간 BILINEAR+antialias 불일치)로 ONNX
쪽 NO-Hardhat 재현율이 크게 떨어지는 걸 발견했다 — 이 회귀가 실제 서빙 경로
(detectors/rfdetr_adapter.py `_OnnxRfdetrModel`)에서 재발하지 않는지 잠근다.

같은 이미지 → torch 백엔드와 ONNX 백엔드가 사실상 같은 검출을 내야 한다(완전히 동일한
숫자는 기대하지 않는다 — onnxruntime과 torch는 연산 순서가 달라 부동소수 오차가 미세하게
남는다, C-2 실측: dev 74장에서 person/PPE/NO-Hardhat 재현율 전부 동일했지만 개별 박스
단위로는 경계값 근처에서 흔들릴 수 있음).

ppe_rfdetr_v1.onnx/.pth 는 둘 다 gitignore 대상(weights/)이라 이 desktop에만 있다 — 없는
환경(CI 등)에서는 스킵한다(회귀는 이 파일이 있는 곳에서만 검증 가능, 규칙7 — 없는 걸
있는 척 통과시키지 않는다).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import cv2  # noqa: E402
from agents.guard import JUNK_LABELS, LABEL_NORMALIZE  # noqa: E402
from detectors.rfdetr_adapter import RfdetrDetector  # noqa: E402

_PPE_PTH = ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"
_PPE_ONNX = ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.onnx"
_TEST_IMAGE = ROOT / "tests" / "fixtures" / "person_far.jpg"   # [C5] 얼굴 미식별 고정 표본(demo1.jpg 사본)
_CONF = 0.35   # v1_field_baseline_report.md §0 — PPE 운용 임계

# 좌표(정규화 0~1 bbox 기준)·신뢰도 오차 허용치 — backend 간 부동소수 연산 순서 차이로 인한
# 미세 흔들림만 허용한다(느슨한 IoU≥0.5 매칭이 아니라 "거의 동일"을 요구 — 회귀 탐지가
# 목적이므로 크게 벌어지면 반드시 잡아야 함).
_IOU_MATCH = 0.90
_CONF_TOL = 0.05
_MAX_UNMATCHED = 2   # 임계값(0.35) 경계에 걸친 검출 1~2개는 backend 차이로 뜨고 질 수 있음(정상)


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@unittest.skipUnless(
    _PPE_ONNX.exists() and _PPE_PTH.exists(),
    "ppe_rfdetr_v1.onnx/.pth 없음(weights/는 gitignore 대상 — 이 desktop에서만 실행 가능)",
)
class TestRfdetrOnnxParity(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_backend = os.environ.get("VIGENT_DETECT_BACKEND")
        img = cv2.imread(str(_TEST_IMAGE))
        self.assertIsNotNone(img, f"테스트 이미지 로드 실패: {_TEST_IMAGE}")
        self.img = img

    def tearDown(self) -> None:
        if self._prev_backend is None:
            os.environ.pop("VIGENT_DETECT_BACKEND", None)
        else:
            os.environ["VIGENT_DETECT_BACKEND"] = self._prev_backend

    def _detect(self, backend: str) -> tuple[list[dict], type]:
        os.environ["VIGENT_DETECT_BACKEND"] = backend
        det = RfdetrDetector(str(_PPE_PTH), LABEL_NORMALIZE, JUNK_LABELS, resolution=384)
        return det.detect(self.img, conf=_CONF), type(det.model)

    def test_torch_onnx_detection_parity(self) -> None:
        torch_dets, torch_model_cls = self._detect("torch")
        onnx_dets, onnx_model_cls = self._detect("onnx-cpu")

        # 백엔드가 실제로 갈렸는지부터 확인(둘 다 torch로 폴백했으면 이 테스트는 무의미해짐).
        self.assertEqual(torch_model_cls.__name__, "RFDETRNano")
        self.assertEqual(onnx_model_cls.__name__, "_OnnxRfdetrModel")
        self.assertGreater(len(torch_dets), 0, "torch 백엔드가 이 이미지에서 아무것도 못 잡음 — 테스트 이미지 부적합 의심")

        unmatched = 0
        matched_bbox_err = []
        matched_conf_err = []
        onnx_remaining = list(onnx_dets)
        for td in torch_dets:
            best_iou, best_j = 0.0, -1
            for j, od in enumerate(onnx_remaining):
                if od["label"] != td["label"]:
                    continue
                v = _iou(td["bbox"], od["bbox"])
                if v > best_iou:
                    best_iou, best_j = v, j
            if best_j == -1 or best_iou < _IOU_MATCH:
                unmatched += 1
                continue
            od = onnx_remaining.pop(best_j)
            matched_bbox_err.append(max(abs(a - b) for a, b in zip(td["bbox"], od["bbox"])))
            matched_conf_err.append(abs(td["conf"] - od["conf"]))
        unmatched += len(onnx_remaining)   # onnx에만 있고 torch에 없는 것도 미매칭

        self.assertLessEqual(
            unmatched, _MAX_UNMATCHED,
            f"backend 간 검출 개수/매칭이 크게 어긋남(torch={len(torch_dets)} onnx={len(onnx_dets)} "
            f"미매칭={unmatched}) — 전처리 불일치([C-2]에서 발견된 BICUBIC/BILINEAR 류) 재발 의심.")
        if matched_bbox_err:
            self.assertLess(max(matched_bbox_err), 0.02,
                             "매칭된 검출의 bbox 오차가 backend 부동소수 차이 수준을 넘음")
        if matched_conf_err:
            self.assertLess(max(matched_conf_err), _CONF_TOL,
                             "매칭된 검출의 신뢰도 오차가 허용치를 넘음")


if __name__ == "__main__":
    unittest.main()
