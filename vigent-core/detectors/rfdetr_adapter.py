"""detectors.rfdetr_adapter — RF-DETR(Apache-2.0) 검출 백엔드. ultralytics(AGPL) 대체(T10a person).

RFDETRNano: COCO 80종 사전학습(person 포함). weights 지정 시 커스텀 체크포인트(.pth) 로드.
장치는 스스로 선택(prefer_mps=True) — RF-DETR 은 macOS MPS 다회추론 크래시 이슈가 없어(YOLO 와 달리)
MPS 를 써 빠르다(probe: person 33.8ms/frame). 박스 표준화는 base.finalize_box 공용 → YOLO 와 동일 규칙.

절대 저하 없음(§2): 로딩·추론 실패는 예외로 올려 guard 가 해당 슬롯만 비활성(나머지 정상).

[Q-3, 2026-08-10] 해상도(imgsz)는 **로드 시점에 고정된다** — RF-DETR 은 `optimize_for_inference()`
로 모델을 그 시점 해상도로 컴파일해버려서, 그 뒤엔 다른 해상도를 주면 `ValueError: Resolution
mismatch`가 난다(실측 확인, `benchmarks/p3_1_resolution_ab_BLOCKED.md`). 그래서 `__init__`이
`resolution` 을 받아 로드 시점에 적용하고(호출자는 `config/tuning.yaml` `detect.imgsz`), 매 호출의
`detect(..., imgsz=)` 는 **참고용 검증만** 한다 — 로드된 해상도와 다르면 조용히 무시하지 않고
경고를 낸다(예전엔 매개변수를 받고 그냥 버렸다 — dead parameter, 재발 방지).

[C-3, 2026-08-12] 저가 CPU 박스 배포용 ONNX 백엔드 — `config/tuning.yaml` `detect.backend:
onnx-cpu` + 슬롯 가중치와 같은 이름의 `.onnx` 파일(`vigent-core/weights/<이름>.onnx`)이
있으면 `_OnnxRfdetrModel`(onnxruntime CPU)을 쓴다. `RFDETRNano.predict()`와 같은 인터페이스
(`.predict(pil, threshold)` → `.xyxy/.confidence/.class_id`, `.class_names`)로 감싸서
`detect()` 본문(letterbox·finalize_box·클래스 매핑)은 백엔드 무관하게 1글자도 안 바뀐다 —
실측(`benchmarks/onnx_cpu_bench.md`)으로 torch 대비 CPU 1.85배·정확도 손실 0 확인된 조합만
그대로 서빙 경로에 옮긴 것. `.onnx` 파일이 없거나 로드 실패하면 자동으로 torch 로 폴백한다
(규칙6 — onnx-cpu 설정해도 슬롯별로 부분 적용이 안전하게 동작).
"""
from __future__ import annotations

import logging
from typing import Any

from .base import BaseDetector, finalize_box

try:
    import defaults as _defaults  # [CODE_AUDIT #6] 해상도 폴백 단일 출처
except ModuleNotFoundError:
    import sys as _sys
    from pathlib import Path as _P
    _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    import defaults as _defaults

_LOG_PRELOAD = logging.getLogger("vigent.rfdetr_adapter")


def _preload_supervision() -> None:
    """★[2026-08-28] `supervision` 을 **미리** 올려 동시 import 경합을 없앤다.

    rfdetr 의 `predict()` 는 호출 시점에 `from supervision import Detections, KeyPoints` 를
    **런타임에** 한다(rfdetr/detr.py). 두 스레드가 **첫 검출에 동시에 진입**하면 한쪽이
    아직 초기화 중인 supervision 모듈을 보고 다음처럼 터진다:

        ImportError: cannot import name 'BackgroundOverlayAnnotator'
                     from 'supervision.annotators.core'

    (그 클래스는 실제로 존재한다 — **부분 초기화된 모듈**을 본 것이다. Python 3.3+ 의
     import 락은 모듈 단위라 동시 import 시 이런 창이 생긴다.)

    실측: 전체 테스트 스위트에서 간헐 발생(누적 18회 중 4회, [F30]). 3회에 걸쳐
    "GPU 메모리 압박"으로 추정했으나 **traceback 확보 결과 반증**됐다 — 메모리와 무관하다.

    ★운영에서도 같은 일이 난다: 여러 카메라 워커가 첫 검출에 동시 진입하면 슬롯 로드가
    실패하고, [F31] 배선을 타 DEGRADED 로 뜬다. 모듈 적재 시 한 번 올려두면 창 자체가 사라진다.
    실패해도 조용히 넘어간다 — 여기서 죽으면 검출 자체가 못 뜬다.
    """
    # ★같은 계열이 하나가 아니다(2026-08-28 셔플 검증에서 2번째 사례 확인):
    #     supervision — rfdetr.predict() 가 런타임 import
    #     sympy       — torch.fx/onnx 경로가 런타임 import
    #                   (관측: "AttributeError: module 'sympy' has no attribute 'printing'"
    #                    — 그 속성은 실제로 존재한다. 부분 초기화된 모듈을 본 것이다.)
    #   ★목록이 완전하다고 단정하지 않는다 — 무거운 지연 import 는 더 있을 수 있다.
    #     재발하면 그 모듈명을 여기에 추가한다.
    for _mod in ("supervision", "sympy", "sympy.printing"):
        try:
            __import__(_mod)
        except Exception as ex:  # noqa: BLE001
            _LOG_PRELOAD.debug("%s 선적재 건너뜀(%s) — 사용 시점에 재시도된다",
                               _mod, type(ex).__name__)


_preload_supervision()

_LOG = logging.getLogger("vigent.rfdetr_adapter")

# [C-3] ONNX 전처리 상수 — rfdetr/detr.py predict() 내부 값과 동일(F.to_tensor→F.resize
#   [bilinear+antialias 기본값]→F.normalize 순서, benchmarks/onnx_cpu_bench.md 에서 검증:
#   이 순서·값이 아니면(예: PIL 기본 보간 BICUBIC) torch 대비 정확도가 떨어진다 — 절대 임의로
#   바꾸지 말 것, 바꾸려면 [C-3] 회귀 테스트(tests/test_rfdetr_onnx_parity.py)로 재검증).
_ONNX_MEAN = [0.485, 0.456, 0.406]
_ONNX_STD = [0.229, 0.224, 0.225]
_ONNX_NUM_SELECT = 300


class _OnnxDet:
    """RFDETRNano.predict() 반환값(supervision.Detections)과 부분 호환 — .xyxy/.confidence/
    .class_id 만 필요(rfdetr_adapter.detect() 가 쓰는 필드 전부)."""

    def __init__(self, xyxy: Any, confidence: Any, class_id: Any) -> None:
        self.xyxy = xyxy
        self.confidence = confidence
        self.class_id = class_id

    def __len__(self) -> int:
        return len(self.xyxy)


class _OnnxRfdetrModel:
    """RFDETRNano 와 같은 `.predict(pil, threshold)`·`.class_names` 인터페이스를 제공하는
    onnxruntime CPU 래퍼([C-3]). 클래스 이름은 export 시 ONNX 메타데이터에 심어둔
    `rfdetr_notes`(JSON)에서 읽는다(torch 모델을 아예 안 띄워도 되게 — 저가 박스에서 torch
    GPU 빌드 없이도 동작). 후처리는 rfdetr 공식 `PostProcess`를 그대로 재사용(재구현 안 함 —
    회귀 위험 최소화)."""

    def __init__(self, onnx_path: Any, requested_resolution: int) -> None:
        import json

        import onnx
        import onnxruntime as ort
        from rfdetr.models.postprocess import PostProcess

        # [Q9] SessionOptions 미지정 시 ORT 기본값(intra_op=코어수·스핀 켜짐)이라 CPU 를
        #   과하게 쓴다. 기본 off — onnxruntime.tune_sessions 를 켰을 때만 튜닝값을 넘긴다.
        _so = None
        try:
            import ort_tune
            _so = ort_tune.session_options()
        except Exception:  # noqa: BLE001
            _so = None
        self._session = (ort.InferenceSession(str(onnx_path), sess_options=_so,
                                              providers=["CPUExecutionProvider"])
                         if _so is not None else
                         ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"]))
        self._input_name = self._session.get_inputs()[0].name
        self._postprocess = PostProcess(num_select=_ONNX_NUM_SELECT)

        notes: dict[str, Any] = {}
        m = onnx.load(str(onnx_path))
        for p in m.metadata_props:
            if p.key == "rfdetr_notes":
                notes = json.loads(p.value)
                break
        self.class_names: list[str] = list(notes.get("class_names") or [])
        if not self.class_names:
            raise ValueError(f"ONNX 메타데이터에 class_names 없음(재변환 필요): {onnx_path}")
        meta_res = int(notes.get("resolution") or requested_resolution)
        if meta_res != requested_resolution:
            _LOG.warning(
                "ONNX(%s) 는 해상도 %d로 export됐는데 요청 해상도는 %d — ONNX 그래프는 고정 입력"
                "shape라 요청값을 무시하고 %d를 쓴다(config/tuning.yaml detect.imgsz 를 바꾸려면 "
                "이 .onnx도 그 해상도로 재변환해야 함).", onnx_path, meta_res, requested_resolution, meta_res)
        self.resolution = meta_res

    def predict(self, pil_image: Any, threshold: float = 0.5, **_kwargs: Any) -> _OnnxDet:
        import numpy as np
        import torch
        import torchvision.transforms.functional as TF

        w, h = pil_image.size
        img_tensor = TF.to_tensor(pil_image)                              # PIL → [0,1] float CHW
        img_tensor = TF.resize(img_tensor, [self.resolution, self.resolution])  # bilinear+antialias(rfdetr 기본)
        img_tensor = TF.normalize(img_tensor, _ONNX_MEAN, _ONNX_STD)
        arr = img_tensor.unsqueeze(0).numpy().astype(np.float32)
        dets, labels = self._session.run(None, {self._input_name: arr})
        outputs = {"pred_logits": torch.from_numpy(labels), "pred_boxes": torch.from_numpy(dets)}
        target_sizes = torch.tensor([[h, w]])
        result = self._postprocess(outputs, target_sizes)[0]
        scores, lbls, boxes = result["scores"], result["labels"], result["boxes"]
        mask = scores >= threshold
        return _OnnxDet(boxes[mask].numpy(), scores[mask].numpy(), lbls[mask].numpy())

# 세로형 입력에서만 정사각 패딩(coord-letterbox). H/W(세로/가로 비)가 이 값을 넘으면 패딩한다.
#   근거(실측 scratchpad/coord_onset.py): 가로형(H/W<1)·정사각(1.0)은 좌표오차 ≤2px 로 정상이나,
#   세로형(H/W>1)은 5:4(1.25)에서도 15~23px 로 불안정(RF-DETR 내부 리사이즈가 세로를 왜곡).
#   → 세로형 전체를 패딩 대상으로. 1.05 여유는 '정확한 정사각'(패딩 무의미)과 '모든 가로형'을 확실히 제외해,
#     가로형은 기존 경로 그대로(유효해상도 보존 → 작은 사람 검출 저하 방지, B8) 타게 한다.
PAD_ASPECT_TALL = 1.05

# [Q-3] RFDETRNano 는 해상도가 patch_size(16)*num_windows(2)=32 의 배수여야 한다(실측 확인:
#   32 배수가 아닌 값을 resolution 에 주면 optimize_for_inference() 가 AssertionError 로 죽는다 —
#   "Backbone requires input shape to be divisible by 32"). 아래 32는 RFDETRNanoConfig 기본값에서
#   읽은 상수(다른 크기 모델로 백엔드를 바꾸면 이 값도 같이 확인해야 함).
_RESOLUTION_BLOCK = 32


def _round_resolution(requested: int) -> int:
    """requested 를 _RESOLUTION_BLOCK 배수로 반올림(최소 그 값 1개는 보장)."""
    if requested % _RESOLUTION_BLOCK == 0:
        return requested
    rounded = max(_RESOLUTION_BLOCK, round(requested / _RESOLUTION_BLOCK) * _RESOLUTION_BLOCK)
    _LOG.warning("resolution=%d 는 %d의 배수가 아니라 %d로 반올림됨(RFDETRNano 백본 제약).",
                 requested, _RESOLUTION_BLOCK, rounded)
    return rounded


def verify_slot_classes(class_names: list[str] | None, required: list[str] | set[str] | None, label_normalize: dict) -> list[str]:
    """[CODE_AUDIT_20260928 #9] 체크포인트 class_names 가 슬롯이 요구하는 라벨을 전부 갖는지. 반환: 없는 라벨 목록(빈 목록 = 통과).
    비교는 표준 라벨(label_normalize 적용 후)로 한다 — 'Safety Vest'(CSS) 와 'Safety-Vest'(표준) 는 같은 것으로 본다.
    class_names 가 None(COCO 사전학습 등 메타 없음)이면 검사하지 않는다(빈 목록)."""
    if not required or class_names is None:
        return []
    have = {label_normalize.get(str(n), str(n)) for n in class_names}
    return [r for r in required if label_normalize.get(str(r), str(r)) not in have]


class RfdetrDetector(BaseDetector):
    backend = "rfdetr"

    def __init__(self, weights: str, label_normalize: dict, junk: set, resolution: int | None = None,
                 allowed_labels: list[str] | set[str] | None = None):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # device·tuning 모듈 경로
        import device as _device
        import tuning
        res_req = _round_resolution(int(resolution)) if resolution else None

        # [C-3] onnx-cpu 배선 — 슬롯 가중치와 이름이 같은 .onnx 가 있을 때만 적용, 없거나 로드
        #   실패하면 조용히 torch 로 폴백(규칙6 — onnx-cpu 설정해도 슬롯별 부분 적용이 안전).
        infer_backend = str(tuning.val("detect", "backend", "torch", env="VIGENT_DETECT_BACKEND")).strip().lower()
        onnx_path = Path(weights).with_suffix(".onnx") if weights else None
        use_onnx = infer_backend == "onnx-cpu" and onnx_path is not None and onnx_path.exists()
        if use_onnx:
            try:
                self.model = _OnnxRfdetrModel(onnx_path, res_req or _defaults.RES)
                self.resolution = self.model.resolution
                self.device = "cpu"
                _LOG.info("RF-DETR ONNX 백엔드 사용(저가 CPU 배포): %s", onnx_path.name)
            except Exception:  # noqa: BLE001  ONNX 로드 실패 → torch 로 폴백(무중단)
                _LOG.warning("ONNX 백엔드 로드 실패(%s) — torch 로 폴백", onnx_path, exc_info=True)
                use_onnx = False

        if not use_onnx:
            from rfdetr import RFDETRNano  # lazy import
            dev = _device.pick_device(prefer_mps=True)   # RF-DETR 은 MPS 안전
            kwargs: dict[str, Any] = {"device": dev}
            if weights:
                kwargs["pretrain_weights"] = weights   # 커스텀 파인튜닝(있으면), 없으면 COCO 사전학습
            if res_req:
                kwargs["resolution"] = res_req   # [Q-3] 로드 시점 해상도(없으면 기본 384)
            self.model = RFDETRNano(**kwargs)
            # [Q-3] 실제로 적용된 해상도를 모델 설정에서 그대로 읽는다(요청값이 block_size 배수가 아니면
            #   라이브러리가 조정할 수 있어, "요청값"이 아니라 "실제 로드값"을 신뢰한다).
            self.resolution = int(getattr(self.model.model_config, "resolution", resolution or _defaults.RES))
            try:
                self.model.optimize_for_inference()
            except Exception:  # noqa: BLE001  최적화 실패해도 추론은 가능
                pass
            self.device = dev
            # ★[I-1] torch 경로도 로그를 남긴다. 예전엔 onnx 일 때만 로그가 있어,
            #   로그만 보고는 "torch 를 쓰는지" 와 "서버가 조용히 CPU 로 돌고 있는지" 를
            #   구분할 수 없었다(H-3 에서 태그만 믿고 같은 조건을 두 번 잰 사고의 원인).
            _LOG.info("RF-DETR torch 백엔드 사용: device=%s weights=%s",
                      dev, Path(weights).name if weights else "COCO(사전학습)")
        self._ln = label_normalize
        self._junk = junk
        self._imgsz_warned: set[int] = set()   # [Q-3] 같은 불일치값으로 매 프레임 로그 스팸 방지(1회만)
        # 클래스 매핑: COCO 사전학습(weights="")은 COCO_CLASSES. 커스텀 파인튜닝(weights 지정)은
        #   모델 자체 class_names(0-indexed, 예: ['forklift']). class_id ≥ 클래스수 = DETR 배경/no-object → 무시.
        #   (COCO_CLASSES 하드코딩은 커스텀 모델을 오매핑 → 실측 근거로 분기: T10b eval_rfdetr_custom.py 참조)
        self._custom_names = list(getattr(self.model, "class_names", []) or []) if weights else None
        # ★[CODE_AUDIT_20260928 #9] 슬롯별 허용 라벨(표준형). None 이면 전부 통과(예전 동작). 실측: fk510_smoke(['person','forklift'])의
        #   person 이 forklift 슬롯에서 최종 검출에 섞였다(109프레임 중 27프레임) — 허용 목록 밖 라벨은 여기서 버린다.
        self.allowed: set[str] | None = ({label_normalize.get(str(a), str(a)) for a in allowed_labels}
                                         if allowed_labels is not None else None)
        self.dropped_by_allowlist = 0

    @property
    def class_names(self) -> list[str] | None:
        """체크포인트 class_names(커스텀 가중치) — COCO 사전학습이면 None."""
        return list(self._custom_names) if self._custom_names is not None else None

    def detect(self, image_bgr, conf: float, imgsz: int | None = None,
               augment: bool = False) -> list[dict[str, Any]]:
        import cv2
        import numpy as np
        from PIL import Image
        from rfdetr.assets.coco_classes import COCO_CLASSES  # [M1-10] rfdetr.util.* 은 1.9.0 제거 예정
        # [Q-3] imgsz 는 로드 시점에 이미 고정됐다(RF-DETR optimize_for_inference() 제약, 클래스
        #   docstring 참고) — 호출별로 다시 바꿀 수 없다. 요청값이 로드된 해상도와 다르면(죽은
        #   매개변수로 조용히 버리지 않고) 경고를 낸다. 같은 값으로 반복 호출되는 게 보통이라(예:
        #   focus_active 5fps 루프) 값별로 1회만 경고해 로그 폭주를 막는다.
        if imgsz and imgsz != self.resolution and imgsz not in self._imgsz_warned:
            self._imgsz_warned.add(imgsz)
            _LOG.warning(
                "imgsz=%d 요청됐지만 이 모델은 해상도 %d로 이미 로드·최적화됨 — 호출별 변경 불가"
                "(RF-DETR optimize_for_inference() 제약). config/tuning.yaml detect.imgsz 를 바꾸고 "
                "재기동해야 실제로 적용된다. 이번 호출은 %d로 진행.",
                imgsz, self.resolution, self.resolution,
            )
        h, w = image_bgr.shape[:2]
        # ★세로형 좌표 정확도(coord-letterbox): 세로형(H/W>PAD_ASPECT_TALL)이면 입력을 정사각으로 회색패딩해
        #   종횡비 1:1 로 만든 뒤 추론 → RF-DETR 내부 리사이즈 왜곡 제거. 반환 박스는 아래서 un-pad 로 원좌표 복원.
        #   가로형·정사각은 pad=False(기존 경로 그대로). finalize_box 정규화 기준은 항상 '원본 w,h'.
        pad = h > w * PAD_ASPECT_TALL
        if pad:
            side = max(h, w)
            proc = np.full((side, side, 3), 114, dtype=np.uint8)   # 회색(114) 정사각 캔버스
            ox, oy = (side - w) // 2, (side - h) // 2
            proc[oy:oy + h, ox:ox + w] = image_bgr                 # 원본을 가운데 배치
        else:
            proc, ox, oy = image_bgr, 0, 0
        pil = Image.fromarray(cv2.cvtColor(proc, cv2.COLOR_BGR2RGB))
        det = self.model.predict(pil, threshold=conf)   # 검출기 임계를 그대로 사용(운용점 일치)
        out: list[dict[str, Any]] = []
        xyxy = getattr(det, "xyxy", [])
        for j in range(len(xyxy)):
            cid = int(det.class_id[j])
            if self._custom_names is not None:                 # 커스텀 파인튜닝: 자체 class_names(0-indexed)
                if not (0 <= cid < len(self._custom_names)):
                    continue                                   # 범위 밖 = 배경/no-object → 버림
                raw = self._custom_names[cid]
            else:                                              # COCO 사전학습(person 등): 기존 경로 불변
                raw = COCO_CLASSES[cid]
            x1, y1, x2, y2 = (float(v) for v in xyxy[j])
            if pad:                                            # 정사각 좌표 → 원본 픽셀로 복원(un-pad)
                x1 -= ox; x2 -= ox; y1 -= oy; y2 -= oy
            d = finalize_box(raw, float(det.confidence[j]), x1, y1, x2, y2, w, h, self._ln, self._junk)
            if d is None:
                continue
            if self.allowed is not None and d["label"] not in self.allowed:   # [#9] 슬롯 역할 밖 라벨(예: forklift 슬롯의 person)
                self.dropped_by_allowlist += 1
                continue
            out.append(d)
        return out
