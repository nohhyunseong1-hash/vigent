#!/usr/bin/env python3
"""[C-2] CPU 추론 최적화 — torch fp32 vs ONNX Runtime fp32/INT8, dev 74장 지연+정확도 재채점.

방법론(규칙7 — 기존 방법론 그대로 재사용, 새로 발명하지 않음):
  - guard._get_model("ppe")로 실제 배포 RfdetrDetector(letterbox·finalize_box·class_names
    매핑 전부 포함)를 로드한 뒤, ONNX 백엔드에서는 `.model.predict`만 onnxruntime 기반
    함수로 교체한다(나머지 파이프라인은 torch 백엔드와 완전히 동일한 코드 경로 — 후처리
    로직 차이로 인한 결과 왜곡을 원천 차단).
  - 정확도 재채점은 `benchmarks/y2_test_baseline.py`의 채점 로직(person/PPE IoU≥0.5 매칭·
    NO-Hardhat 구간+Clopper-Pearson CI)을 그대로 재사용한다(그 파일의 순수 헬퍼 함수를
    import) — v1_field_baseline_report.md의 dev 수치와 직접 비교 가능하게.
  - 지연은 CPU 강제(VIGENT_DETECT_DEVICE=cpu) + Docker/WSL2 측정위생 절차
    (docs/benchmark_measurement_hygiene.md) 준수 시도 후 측정.

★test 35장은 쓰지 않는다(dev 74장만, 사용자 지시+ [P-0] 원칙 — test는 이미 소진됨).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
import env_guard  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import y2_test_baseline as y2  # noqa: E402  순수 헬퍼(_iou/_match/_prf/_load_gt/_bbox_key) + 상수 재사용
from PIL import Image  # noqa: E402
from rfdetr.models.postprocess import PostProcess  # noqa: E402

MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]
RESOLUTION = 384
NUM_SELECT = 300
PPE_CONF = 0.35   # v1_field_baseline_report.md §0 — PPE 신뢰도 임계(운용점)
WARMUP = 10       # run_eval.py 관례와 동일


class _OnnxDet:
    """supervision.Detections 의 부분 호환 컨테이너(.xyxy/.confidence/.class_id 만 필요)."""

    def __init__(self, xyxy: np.ndarray, confidence: np.ndarray, class_id: np.ndarray) -> None:
        self.xyxy = xyxy
        self.confidence = confidence
        self.class_id = class_id

    def __len__(self) -> int:
        return len(self.xyxy)


_postprocess = PostProcess(num_select=NUM_SELECT)


def make_onnx_predict(session):
    """RFDETRNano.predict(pil, threshold=) 와 호환되는 함수를 onnxruntime 세션으로 생성.
    전처리(리사이즈 384·ImageNet 정규화)·후처리(rfdetr 공식 PostProcess) 전부 원본 라이브러리
    로직을 그대로 따른다(rfdetr/detr.py predict()·rfdetr/models/postprocess.py 확인 완료).

    ★[C-2] 첫 시도에서 PIL.resize()(기본 보간=BICUBIC)를 썼다가 NO-Hardhat 재현율이 torch
    대비 크게 떨어지는 걸 발견 — 원인 조사 결과 rfdetr/detr.py predict()는 실제로
    `F.to_tensor(img)` → `torchvision.transforms.functional.resize`(기본 보간=BILINEAR+
    antialias) → `F.normalize` 순서였다(보간법 불일치). 아래는 그 순서를 정확히 재현한다."""
    import torchvision.transforms.functional as TF
    input_name = session.get_inputs()[0].name

    def _predict(pil_image: Image.Image, threshold: float = 0.5, **_kwargs: Any) -> _OnnxDet:
        w, h = pil_image.size
        img_tensor = TF.to_tensor(pil_image)                       # PIL → [0,1] float CHW
        img_tensor = TF.resize(img_tensor, [RESOLUTION, RESOLUTION])  # bilinear+antialias(rfdetr 기본과 동일)
        img_tensor = TF.normalize(img_tensor, MEAN, STD)
        arr = img_tensor.unsqueeze(0).numpy().astype(np.float32)
        dets, labels = session.run(None, {input_name: arr})
        outputs = {"pred_logits": torch.from_numpy(labels), "pred_boxes": torch.from_numpy(dets)}
        target_sizes = torch.tensor([[h, w]])
        result = _postprocess(outputs, target_sizes)[0]
        scores, lbls, boxes = result["scores"], result["labels"], result["boxes"]
        mask = scores >= threshold
        return _OnnxDet(boxes[mask].numpy(), scores[mask].numpy(), lbls[mask].numpy())

    return _predict


def build_detector(backend: str, onnx_path: str = ""):
    """guard 를 만들고 ppe 슬롯 detector 를 로드(torch 파이프라인은 항상 이 실제 인스턴스를
    쓴다). backend!="torch" 면 .model.predict 만 onnxruntime 함수로 교체."""
    guard = bq._build_guard()
    detector = guard._get_model("ppe")   # 실제 RfdetrDetector(letterbox·finalize_box 포함)
    if backend == "torch":
        return guard, detector
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    detector.model.predict = make_onnx_predict(sess)   # 후처리·finalize_box 는 손대지 않음
    return guard, detector


def bench_latency(detector, images: list, warmup: int = WARMUP) -> dict:
    lat = []
    for i, img_bgr in enumerate(images):
        t0 = time.perf_counter()
        detector.detect(img_bgr, conf=PPE_CONF)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if i >= warmup:
            lat.append(dt_ms)
    lat_sorted = sorted(lat)

    def pct(p: float) -> float | None:
        if not lat_sorted:
            return None
        idx = min(len(lat_sorted) - 1, int(len(lat_sorted) * p))
        return round(lat_sorted[idx], 1)

    return {"p50_ms": pct(0.50), "p95_ms": pct(0.95), "max_ms": round(max(lat), 1) if lat else None,
            "mean_ms": round(sum(lat) / len(lat), 1) if lat else None, "n": len(lat)}


def score_dev(guard) -> dict:
    """y2_test_baseline.score_split("dev", ...) 와 동일 로직, guard 를 인자로 받는 버전
    (원본은 함수 내부에서 자체적으로 bq._build_guard() 를 새로 만들어 모델 교체본을 주입할
    방법이 없어 이 얇은 복제가 필요했다 — 채점 로직 자체는 1글자도 안 바꿈)."""
    from scipy.stats import beta

    ambiguous_keys_dev = {y2._bbox_key(e["file"], e["bbox"]) for e in y2.AMBIGUOUS_DEV["items"]}

    person_tp = person_fp = person_gt = 0
    nh_gt_total = nh_tp_total = nh_ambiguous_seen = nh_tp_clear = 0
    ppe_tp = {c: 0 for c in y2.PPE_CLASSES}
    ppe_fp = {c: 0 for c in y2.PPE_CLASSES}
    ppe_gt = {c: 0 for c in y2.PPE_CLASSES}

    from isolated_detect import detect_isolated
    for fname in y2.SPLIT["dev"]:
        stem = Path(fname).stem
        gt_all = y2._load_gt(stem)
        if not gt_all:
            continue
        img = cv2.imread(str(y2.FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds_all = out.get("detections", [])

        person_gts = [b for c, b in gt_all if c == "person"]
        person_preds = [d["bbox"] for d in preds_all if d.get("label") == "person"]
        hit = y2._match(person_gts, person_preds)
        person_gt += len(person_gts)
        person_tp += len(hit)
        person_fp += len(person_preds) - len(hit)

        for cls in y2.PPE_CLASSES:
            cls_gts = [b for c, b in gt_all if c == cls]
            cls_preds = [d["bbox"] for d in preds_all if d.get("label") == cls]
            cls_hit = y2._match(cls_gts, cls_preds)
            ppe_gt[cls] += len(cls_gts)
            ppe_tp[cls] += len(cls_hit)
            ppe_fp[cls] += len(cls_preds) - len(cls_hit)
            if cls == "NO-Hardhat":
                nh_gt_total += len(cls_gts)
                nh_tp_total += len(cls_hit)
                for gi, g in enumerate(cls_gts):
                    is_ambiguous = y2._bbox_key(fname, g) in ambiguous_keys_dev
                    if is_ambiguous:
                        nh_ambiguous_seen += 1
                    elif gi in cls_hit:
                        nh_tp_clear += 1

    p_prec, p_rec, p_f1 = y2._prf(person_tp, person_fp, person_gt)
    tp_all, fp_all, gt_all_n = sum(ppe_tp.values()), sum(ppe_fp.values()), sum(ppe_gt.values())
    ppe_prec, ppe_rec, ppe_f1 = y2._prf(tp_all, fp_all, gt_all_n)

    nh_lower = nh_tp_total / nh_gt_total if nh_gt_total else 0.0
    clear_n = nh_gt_total - nh_ambiguous_seen
    nh_upper = nh_tp_clear / clear_n if clear_n else 0.0
    alpha = 0.05
    if not clear_n:
        ci = (float("nan"), float("nan"))
    else:
        lo = 0.0 if nh_tp_clear == 0 else beta.ppf(alpha / 2, nh_tp_clear, clear_n - nh_tp_clear + 1)
        hi = 1.0 if nh_tp_clear == clear_n else beta.ppf(1 - alpha / 2, nh_tp_clear + 1, clear_n - nh_tp_clear)
        ci = (lo, hi)

    return {
        "n_images": len(y2.SPLIT["dev"]),
        "person_precision": round(p_prec * 100, 1), "person_recall": round(p_rec * 100, 1),
        "person_f1": round(p_f1 * 100, 1),
        "person_tp": person_tp, "person_fp": person_fp, "person_gt": person_gt,
        "ppe_precision": round(ppe_prec * 100, 1), "ppe_recall": round(ppe_rec * 100, 1),
        "ppe_f1": round(ppe_f1 * 100, 1),
        "ppe_tp": tp_all, "ppe_fp": fp_all, "ppe_gt": gt_all_n,
        "nh_recall_lower_pct": round(nh_lower * 100, 1), "nh_recall_upper_pct": round(nh_upper * 100, 1),
        "nh_ci_pct": [round(ci[0] * 100, 1), round(ci[1] * 100, 1)],
        "nh_gt_total": nh_gt_total, "nh_tp_total": nh_tp_total,
        "nh_clear_n": clear_n, "nh_tp_clear": nh_tp_clear, "nh_ambiguous_n": nh_ambiguous_seen,
    }


def main() -> None:
    env_guard.warn_if_docker_running("c2_onnx_cpu_bench")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", required=True, choices=["torch", "onnx_fp32", "onnx_int8"])
    ap.add_argument("--onnx-path", default="")
    ap.add_argument("--skip-accuracy", action="store_true", help="지연만 측정(빠른 확인용)")
    ap.add_argument("--out", default=str(_ROOT / "benchmarks" / "results" / "c2_onnx_cpu_bench.json"))
    args = ap.parse_args()

    if args.backend != "torch" and not args.onnx_path:
        ap.error("--backend onnx_* 에는 --onnx-path 필요")

    guard, detector = build_detector(args.backend, args.onnx_path)

    print(f"[c2] backend={args.backend} — 지연 측정(dev 74장, warmup {WARMUP})...")
    images = []
    for fname in y2.SPLIT["dev"]:
        img = cv2.imread(str(y2.FRAMES_DIR / fname))
        if img is not None:
            images.append(img)
    lat = bench_latency(detector, images)
    print(f"[c2] {args.backend} 지연: p50={lat['p50_ms']}ms p95={lat['p95_ms']}ms "
          f"mean={lat['mean_ms']}ms (n={lat['n']})")

    result: dict[str, Any] = {"backend": args.backend, "onnx_path": args.onnx_path, "latency": lat}

    if not args.skip_accuracy:
        print(f"[c2] backend={args.backend} — dev 74장 정확도 재채점...")
        acc = score_dev(guard)
        print(f"[c2] {args.backend} person R={acc['person_recall']}% F1={acc['person_f1']}% | "
              f"PPE F1={acc['ppe_f1']}% | NO-Hardhat [{acc['nh_recall_lower_pct']}%, "
              f"{acc['nh_recall_upper_pct']}%]")
        result["accuracy"] = acc

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    allres: dict = {}
    if out_path.exists():
        try:
            allres = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            allres = {}
    allres[args.backend] = result
    out_path.write_text(json.dumps(allres, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[c2] 저장: {out_path}")


if __name__ == "__main__":
    main()
