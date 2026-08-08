#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────
# VIGENT COCO mAP 벤치마크 — person / PPE, 이중 트랙(raw / pipeline)
#
# ★ 실행은 반드시 아나콘다 파이썬으로(ultralytics·pycocotools 설치 환경):
#     /opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode raw      --dataset person --weights vigent-core/weights/yolo11m.pt
#     /opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode pipeline --dataset person
#     /opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode raw      --dataset ppe    --weights vigent-core/weights/ppe_css_v1.pt
#     /opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode pipeline --dataset ppe
#
# 두 트랙(같은 GT·같은 COCOeval, 무엇을 재는지가 다름):
#   --mode raw      : 원시 model.predict(conf=0.001) → '표준 COCO baseline'(모델 능력, 모델간 비교용)
#   --mode pipeline : 배포 guard.detect 경유       → '배포 운용점'(운용 임계·후처리 반영)
#
# 산출: benchmarks/results/baseline_yolo.json  (구조: {dataset: {mode: record}})
#   - mAP@50, mAP@50:95(COCOeval 101-point), 클래스별 AP@50 / AP@50:95
#   - latency(ms, warmup 10프레임 제외 평균), seed 고정, conf/iou/imgsz 기록
# GT/예측 클래스는 '이름 정규화'로 매칭. 모델·원본 데이터 불변(읽기만).
# ─────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import env_guard
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "benchmarks" / "results" / "baseline_yolo.json"

# 현장 평가셋 클래스 스킴(docs/labeling_guide.md §0). 순서가 라벨 txt 의 class id(0~6)를 정의한다.
# data/field_eval/classes.txt 와 일치해야 하며, _load_gt 에서 실제 파일과 대조 검증한다.
_FIELD_EVAL_CLASSES = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest", "Mask", "NO-Mask"]

_DATASETS = {
    "person": {
        "images": _ROOT / "data" / "eval" / "clean" / "images",
        "labels": _ROOT / "data" / "eval" / "clean" / "labels",
        "gt_names": ["person"],                       # 단일 클래스(라벨 class 0 = person)
        "data_yaml": None,
        "slot": "person",                             # pipeline 모드에서 guard 검출기 슬롯
    },
    "ppe": {
        "images": _ROOT / "data" / "datasets" / "css_safety" / "test" / "images",
        "labels": _ROOT / "data" / "datasets" / "css_safety" / "test" / "labels",
        "gt_names": None,                             # data.yaml 의 names 사용
        "data_yaml": _ROOT / "data" / "datasets" / "css_safety" / "data.yaml",
        "slot": "ppe",
    },
    # T13: D-Fire(CC0) test 서브셋. YOLO id 0=smoke,1=fire → data.yaml names ['smoke','fire'].
    "fire_smoke": {
        "images": _ROOT / "benchmarks" / "data" / "fire_smoke" / "images",
        "labels": _ROOT / "benchmarks" / "data" / "fire_smoke" / "labels",
        "gt_names": None,
        "data_yaml": _ROOT / "benchmarks" / "data" / "fire_smoke" / "data.yaml",
        "slot": "fire_smoke",
    },
    "forklift": {
        "images": _ROOT / "benchmarks" / "data" / "forklift" / "images",
        "labels": _ROOT / "benchmarks" / "data" / "forklift" / "labels",
        "gt_names": None,
        "data_yaml": _ROOT / "benchmarks" / "data" / "forklift" / "data.yaml",
        "slot": "forklift",
    },
    # ── 현장 평가셋(109장, 2026-08-08 사람 전수 검수 완료 — benchmarks/field_eval_gt_summary.md) ──
    # 정답지 한 파일에 person(1) + PPE(6) 이 섞여 있는데 모델은 person/ppe 검출기가 따로다.
    # 그래서 같은 이미지·같은 라벨을 쓰되 gt_filter 로 클래스를 갈라 두 데이터셋으로 등록한다
    # (섞어서 재면 어느 모델의 성능인지 구분되지 않는다).
    "field_eval_person": {
        "images": _ROOT / "data" / "field_eval" / "frames",
        "labels": _ROOT / "data" / "field_eval" / "labels",
        "gt_names": None,
        "data_yaml": None,
        "slot": "person",
        "gt_all_names": _FIELD_EVAL_CLASSES,   # 라벨 파일의 class id 해석용(0~6)
        "gt_filter": ["person"],               # 채점 대상 — 정답 201건
    },
    "field_eval_ppe": {
        "images": _ROOT / "data" / "field_eval" / "frames",
        "labels": _ROOT / "data" / "field_eval" / "labels",
        "gt_names": None,
        "data_yaml": None,
        "slot": "ppe",
        "gt_all_names": _FIELD_EVAL_CLASSES,
        # 채점 대상 — 정답 324건. ★Safety-Vest 는 109장 전체에서 2건뿐이라 이 클래스 수치는
        #   통계적으로 무의미하다(보고 시 표본 수를 반드시 함께 표기할 것).
        "gt_filter": ["Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest", "Mask", "NO-Mask"],
    },
}

_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp"}
WARMUP = 10          # latency 평균에서 제외할 초기 프레임 수
CONF = 0.001         # raw 모드 mAP 계산용 낮은 임계(전체 PR 곡선 — COCO 표준)
IOU_NMS = 0.7        # raw 모드 NMS IoU
IMGSZ = 640
SEED = 0


def _norm(s: str) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


def _set_seed(s: int = SEED) -> None:
    random.seed(s)
    np.random.seed(s)
    try:
        import torch
        torch.manual_seed(s)
    except Exception:  # noqa: BLE001
        pass


def _gt_names(cfg: dict) -> list[str]:
    if cfg.get("gt_filter"):
        return list(cfg["gt_filter"])
    if cfg["gt_names"]:
        return list(cfg["gt_names"])
    import yaml
    y = yaml.safe_load(cfg["data_yaml"].read_text(encoding="utf-8"))
    names = y.get("names")
    if isinstance(names, dict):
        names = [names[k] for k in sorted(names)]
    return list(names)


def _imgs(cfg: dict) -> list[Path]:
    return sorted(p for p in cfg["images"].iterdir() if p.suffix.lower() in _IMG_EXT)


def _load_gt(cfg: dict, gt_names: list[str]):
    """YOLO txt 라벨 → COCO GT dict + 이미지 목록(경로·id·크기)."""
    import cv2
    images, annotations, id_map = [], [], {}
    ann_id, img_id = 1, 0

    # gt_filter 를 쓰는 데이터셋은 '라벨 파일의 class id → 이름' 해석에 전체 클래스 목록이 필요하다.
    # 목록이 어긋나면 클래스가 통째로 뒤바뀌므로, 실제 classes.txt 와 대조해 검증한다(규칙7).
    keep = cfg.get("gt_filter")
    all_names: list[str] = list(cfg.get("gt_all_names") or [])
    if keep:
        cpath = cfg["labels"] / "classes.txt"
        if cpath.exists():
            on_disk = [c.strip() for c in cpath.read_text(encoding="utf-8").splitlines() if c.strip()]
            if on_disk != all_names:
                raise SystemExit(
                    f"★클래스 스킴 불일치 — 코드={all_names} / {cpath}={on_disk}. "
                    "라벨 파일의 class id 해석이 달라지므로 중단한다."
                )
        missing = [k for k in keep if k not in all_names]
        if missing:
            raise SystemExit(f"★gt_filter 에 전체 목록에 없는 클래스: {missing}")

    for p in _imgs(cfg):
        im = cv2.imread(str(p))
        if im is None:
            continue
        h, w = im.shape[:2]
        img_id += 1
        id_map[p.stem] = (img_id, w, h, str(p))
        images.append({"id": img_id, "file_name": p.name, "width": w, "height": h})
        lp = cfg["labels"] / f"{p.stem}.txt"
        if not lp.exists():
            continue
        for line in lp.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            ci = int(float(parts[0]))
            if keep:
                if not (0 <= ci < len(all_names)):
                    raise SystemExit(f"★class id 범위 벗어남: {lp.name} cid={ci}")
                nm = all_names[ci]
                if nm not in keep:
                    continue          # 이 데이터셋의 채점 대상이 아님(다른 슬롯의 클래스)
                ci = keep.index(nm)   # 필터된 목록 기준으로 재번호
            cx, cy, bw, bh = map(float, parts[1:5])
            x, y, ww, hh = (cx - bw / 2) * w, (cy - bh / 2) * h, bw * w, bh * h
            annotations.append({
                "id": ann_id, "image_id": img_id, "category_id": ci + 1,
                "bbox": [x, y, ww, hh], "area": ww * hh, "iscrowd": 0,
            })
            ann_id += 1
    categories = [{"id": i + 1, "name": n} for i, n in enumerate(gt_names)]
    gt = {"images": images, "annotations": annotations, "categories": categories}
    return gt, id_map, [im["id"] for im in images]


def _predict_raw(weights: str, cfg: dict, gt_names: list[str], id_map: dict):
    """raw: 원시 model.predict(conf=0.001) → COCO detections + latency(warmup 제외)."""
    from ultralytics import YOLO
    model = YOLO(weights)
    model_names = model.names
    gt_cat = {_norm(n): i + 1 for i, n in enumerate(gt_names)}
    detections, latencies = [], []
    for i, p in enumerate(_imgs(cfg)):
        if p.stem not in id_map:
            continue
        img_id = id_map[p.stem][0]
        t0 = time.perf_counter()
        r = model.predict(str(p), conf=CONF, iou=IOU_NMS, imgsz=IMGSZ, verbose=False)[0]
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if i >= WARMUP:
            latencies.append(dt_ms)
        for b in r.boxes:
            catid = gt_cat.get(_norm(model_names[int(b.cls)]))
            if catid is None:
                continue
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            detections.append({
                "image_id": img_id, "category_id": catid,
                "bbox": [x1, y1, x2 - x1, y2 - y1], "score": float(b.conf),
            })
    return detections, latencies, {"model_source": str(Path(weights))}


def _predict_pipeline(cfg: dict, gt_names: list[str], id_map: dict):
    """pipeline: 배포 guard.detect 경유 → COCO detections + latency. 모델은 vision.yaml 설정본."""
    import sys
    sys.path.insert(0, str(_ROOT / "vigent-core"))
    import cv2
    import main as M
    from isolated_detect import detect_isolated
    bundle = M.STATE.get(M.DEFAULT_THEME) or M._load_theme(M.DEFAULT_THEME)
    guard = bundle["agents"].get("Guard")
    slot = cfg["slot"]
    gt_cat = {_norm(n): i + 1 for i, n in enumerate(gt_names)}
    detections, latencies = [], []
    for i, p in enumerate(_imgs(cfg)):
        if p.stem not in id_map:
            continue
        img_id, w, h, _ = id_map[p.stem]
        img = cv2.imread(str(p))
        if img is None:
            continue
        # 2026-08: 구 `guard._tracks = []`는 존재하지 않는 속성이라 죽은 코드였다(진짜 상태는
        #   `_tracks_by_key`) — 서로 무관한 GT 이미지 사이에 트랙이 안 비워진 채 새던 버그(실측 확인).
        #   detect_isolated()로 교체(매 호출 고유 track_key 발급+전후 reset).
        t0 = time.perf_counter()
        out = detect_isolated(guard, img, detectors=[slot])
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if i >= WARMUP:
            latencies.append(dt_ms)
        for d in out.get("detections", []):
            bb = d.get("bbox")
            if not bb:
                continue
            x1, y1, x2, y2 = bb
            if max(x1, y1, x2, y2) <= 1.5:       # 정규화 좌표면 픽셀로
                x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
            catid = gt_cat.get(_norm(d.get("label", "")))
            if catid is None:
                continue
            detections.append({
                "image_id": img_id, "category_id": catid,
                "bbox": [x1, y1, x2 - x1, y2 - y1], "score": float(d.get("conf", 0.5)),
            })

    # ★기록 정정(2026-08-08): pipeline 은 guard 기본값(= config/tuning.yaml)을 쓰는데, 기존에는
    #   결과 JSON 에 모듈 상수 IMGSZ(640)와 "guard 운용 임계(vision.yaml)"라는 문자열이 그대로
    #   기록돼 실제 사용값과 달랐다(실측: tuning.yaml detect.imgsz=960). 실제 값을 읽어 덮어쓴다.
    #   raw 모드는 이 함수를 안 타므로 기존 기록(IMGSZ/CONF)이 그대로 맞다.
    import tuning
    conf_cfg = tuning.section("detect").get("conf") or {}
    conf_used: Any = conf_cfg.get(slot)
    per_class = conf_cfg.get(f"{slot}_per_class")
    if per_class:
        conf_used = {"base": conf_used, "per_class": dict(per_class)}
    return detections, latencies, {
        "model_source": f"vision.yaml 배포 설정(guard slot={slot})",
        "imgsz": int(tuning.val("detect", "imgsz", IMGSZ)),
        "conf": conf_used if conf_used is not None else "guard 내부 기본값(tuning.yaml 미지정)",
        "config_source": "config/tuning.yaml detect.{imgsz,conf} 실측 — 모듈 상수 아님",
    }


def _predict_rfdetr(cfg: dict, gt_names: list[str], id_map: dict, weights: str = ""):
    """RF-DETR(permissive) 예측 → COCO detections + latency(warmup 제외).
    ★ raw 모드와 동일 조건: threshold=CONF(0.001). GT/COCOeval 세팅은 손대지 않는다(측정 로직 불변).
    weights 없으면 RFDETRNano COCO 사전학습, 있으면 커스텀 체크포인트(.pth) 로드."""
    import sys
    sys.path.insert(0, str(_ROOT / "vigent-core"))
    import cv2
    from PIL import Image
    from rfdetr import RFDETRNano
    from rfdetr.util.coco_classes import COCO_CLASSES
    import device as _device
    dev = _device.pick_device(prefer_mps=True)
    kwargs = {"device": dev}
    if weights:
        kwargs["pretrain_weights"] = str(weights)     # 커스텀 파인튜닝 체크포인트(있으면)
    model = RFDETRNano(**kwargs)
    with contextlib.suppress(Exception):
        model.optimize_for_inference()
    gt_cat = {_norm(n): i + 1 for i, n in enumerate(gt_names)}
    detections, latencies = [], []
    for i, p in enumerate(_imgs(cfg)):
        if p.stem not in id_map:
            continue
        img_id = id_map[p.stem][0]
        img = cv2.imread(str(p))
        if img is None:
            continue
        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        t0 = time.perf_counter()
        det = model.predict(pil, threshold=CONF)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if i >= WARMUP:
            latencies.append(dt_ms)
        xyxy = getattr(det, "xyxy", [])
        for j in range(len(xyxy)):
            name = COCO_CLASSES[int(det.class_id[j])]
            catid = gt_cat.get(_norm(name))
            if catid is None:
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy[j])
            detections.append({
                "image_id": img_id, "category_id": catid,
                "bbox": [x1, y1, x2 - x1, y2 - y1], "score": float(det.confidence[j]),
            })
    return detections, latencies, {"model_source": weights or "RFDETRNano COCO-pretrained (Apache-2.0)"}


def _evaluate(gt: dict, detections: list, img_ids: list, gt_names: list[str]) -> dict:
    """COCOeval(bbox) → 전체/클래스별 AP. 출력은 % 스케일."""
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval
    with contextlib.redirect_stdout(io.StringIO()):
        cocoGt = COCO()
        cocoGt.dataset = gt
        cocoGt.createIndex()
        if detections:
            cocoDt = cocoGt.loadRes(detections)
        else:
            cocoDt = COCO()
            cocoDt.dataset = {"images": gt["images"], "annotations": [],
                              "categories": gt["categories"]}
            cocoDt.createIndex()
        E = COCOeval(cocoGt, cocoDt, "bbox")
        E.params.imgIds = img_ids
        E.evaluate()
        E.accumulate()
        E.summarize()
    mAP5095 = float(E.stats[0]) * 100
    mAP50 = float(E.stats[1]) * 100
    prec = E.eval["precision"]      # [T=10, R=101, K, A=4, M=3]
    per50, per5095 = {}, {}
    for k, name in enumerate(gt_names):
        p_all = prec[:, :, k, 0, -1]
        v = p_all[p_all > -1]
        per5095[name] = round(float(v.mean()) * 100, 2) if v.size else None
        p50 = prec[0, :, k, 0, -1]
        v50 = p50[p50 > -1]
        per50[name] = round(float(v50.mean()) * 100, 2) if v50.size else None
    return {"mAP@50": round(mAP50, 2), "mAP@50:95": round(mAP5095, 2),
            "per_class_AP50": per50, "per_class_AP5095": per5095}


def main() -> None:
    env_guard.warn_if_docker_running("run_eval")
    ap = argparse.ArgumentParser(description="VIGENT COCO mAP benchmark (person/ppe · raw/pipeline)")
    ap.add_argument("--mode", default="raw", choices=["raw", "pipeline"],
                    help="raw=원시 model.predict(표준 COCO) / pipeline=배포 guard.detect(운용점)")
    ap.add_argument("--dataset", required=True, choices=list(_DATASETS),
                    help="person|ppe|fire_smoke|forklift|field_eval_person|field_eval_ppe")
    ap.add_argument("--backend", default="yolo", choices=["yolo", "rfdetr"],
                    help="raw 모드 검출 백엔드. yolo=ultralytics(.pt) / rfdetr=RF-DETR(permissive)")
    ap.add_argument("--weights", default="",
                    help="yolo raw 필수(.pt). rfdetr 는 선택(.pth, 없으면 COCO 사전학습). pipeline 은 vision.yaml")
    ap.add_argument("--dump-preds", default="",
                    help="예측(COCO detections)과 GT 를 이 경로(.json)에 저장 — 사후 분석용(측정 로직 불변)")
    args = ap.parse_args()
    if args.mode == "raw" and args.backend == "yolo" and not args.weights:
        ap.error("--mode raw --backend yolo 에는 --weights 가 필요합니다")

    _set_seed()
    cfg = _DATASETS[args.dataset]
    gt_names = _gt_names(cfg)
    gt, id_map, img_ids = _load_gt(cfg, gt_names)
    n_gt = len(gt["annotations"])

    if args.mode == "raw":
        if args.backend == "rfdetr":
            detections, latencies, extra = _predict_rfdetr(cfg, gt_names, id_map, args.weights)
        else:
            detections, latencies, extra = _predict_raw(args.weights, cfg, gt_names, id_map)
    else:
        detections, latencies, extra = _predict_pipeline(cfg, gt_names, id_map)
    metrics = _evaluate(gt, detections, img_ids, gt_names)

    if args.dump_preds:
        dp = Path(args.dump_preds)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(json.dumps({
            "dataset": args.dataset, "mode": args.mode, "gt_names": gt_names,
            "images": gt["images"], "gt_annotations": gt["annotations"],
            "detections": detections,
        }, ensure_ascii=False), encoding="utf-8")
        print(f"예측·GT 덤프: {dp}")

    lat_mean = round(float(np.mean(latencies)), 2) if latencies else None
    record = {
        "mode": args.mode,
        "backend": args.backend,
        "measures": ("표준 COCO baseline(원시 모델 능력)" if args.mode == "raw"
                     else "배포 운용점(guard.detect 후처리·운용 임계 반영)"),
        "dataset": args.dataset,
        "images_dir": str(cfg["images"].relative_to(_ROOT)),
        "num_images": len(gt["images"]),
        "gt_boxes": n_gt,
        "num_detections": len(detections),
        **metrics,
        "latency_ms_mean": lat_mean,
        "latency_frames_timed": len(latencies),
        "latency_warmup_excluded": WARMUP,
        "conf": (CONF if args.mode == "raw" else "guard 운용 임계(vision.yaml)"),
        "iou_nms": IOU_NMS if args.mode == "raw" else "guard 내부",
        "imgsz": IMGSZ, "seed": SEED,
        "eval_method": "pycocotools COCOeval bbox (101-point interpolation)",
        **extra,
        "run_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    allres = {}
    if _OUT.exists():
        with contextlib.suppress(Exception):
            allres = json.loads(_OUT.read_text(encoding="utf-8"))
    mode_key = args.mode if args.backend == "yolo" else f"{args.mode}_{args.backend}"
    allres.setdefault(args.dataset, {})
    allres[args.dataset][mode_key] = record
    _OUT.write_text(json.dumps(allres, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== {args.dataset} / {mode_key} =====")
    print(f"이미지 {record['num_images']}장 · GT {n_gt}개 · 예측 {len(detections)}개")
    print(f"mAP@50={metrics['mAP@50']}%  mAP@50:95={metrics['mAP@50:95']}%")
    print(f"클래스별 AP@50: {metrics['per_class_AP50']}")
    print(f"latency {lat_mean}ms/frame (warmup {WARMUP} 제외, {len(latencies)}프레임)")
    print(f"저장: {_OUT.relative_to(_ROOT)}  [{args.dataset}][{mode_key}]")


if __name__ == "__main__":
    main()
