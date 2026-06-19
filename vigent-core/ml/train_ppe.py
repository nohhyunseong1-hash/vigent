#!/usr/bin/env python3
"""construction-ppe 데이터셋으로 PPE 탐지 모델 학습.

- 기존 PPE 모델(construction_ppe_v30)과 동일 스택(ultralytics YOLO) 사용.
  ⚠️ ultralytics는 AGPL-3.0 — 상용 배포 시 라이선스 결정 필요(기존과 동일).
- 결과: runs/detect/ppe_construction_ax/weights/best.pt
  좋으면 config/settings.yaml 의 ppe_model_path 를 이 경로로 교체.

사용:
  python backend/ml/train_ppe.py            # 기본 학습(60ep, mps)
  python backend/ml/train_ppe.py 5 416 cpu  # epochs imgsz device
"""
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets" / "safety" / "construction-ppe"


def make_abs_yaml():
    cfg = yaml.safe_load((DATA / "data.yaml").read_text(encoding="utf-8"))
    cfg["path"] = str(DATA)                      # 절대경로로 고정(ultralytics datasets_dir 무관)
    out = DATA / "data_abs.yaml"
    out.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return out


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    device = sys.argv[3] if len(sys.argv) > 3 else "mps"
    data_yaml = make_abs_yaml()
    print(f"[train_ppe] data={data_yaml} epochs={epochs} imgsz={imgsz} device={device}")
    model = YOLO("yolov8n.pt")                   # 경량 베이스(전이학습)
    model.train(
        data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=16, device=device,
        patience=12, project=str(ROOT / "runs" / "detect"), name="ppe_construction_ax",
        exist_ok=True, verbose=True,
    )
    best = ROOT / "runs" / "detect" / "ppe_construction_ax" / "weights" / "best.pt"
    print(f"[train_ppe] ✅ 완료 → {best}")
    print("[train_ppe] config/settings.yaml 의 ppe_model_path 를 위 경로로 교체하면 적용됩니다.")


if __name__ == "__main__":
    main()
