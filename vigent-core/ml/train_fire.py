#!/usr/bin/env python3
"""화재/연기 탐지 모델 파인튜닝 (Roboflow fire-wrpgm, CC BY 4.0).

- 데이터: datasets/safety/fire (classes: Fire, default, smoke)
  · 'default'는 Roboflow 잡음 클래스 — 추론 시 무시(hazard_detector가 fire/smoke만 매핑).
- yolov8n 전이학습. 결과: runs/detect/fire_boda_ax/weights/best.pt
  좋으면 config/settings.yaml 의 fire_model_path 를 이 경로로 교체.

사용:  python backend/ml/train_fire.py [epochs imgsz device]
"""
import sys
from pathlib import Path

import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets" / "safety" / "fire"


def make_abs_yaml():
    cfg = yaml.safe_load((DATA / "data.yaml").read_text(encoding="utf-8"))
    names = cfg.get("names")
    out = {
        "path": str(DATA),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "names": names,
        "nc": cfg.get("nc", len(names) if names else 3),
    }
    p = DATA / "data_abs.yaml"
    p.write_text(yaml.safe_dump(out, allow_unicode=True), encoding="utf-8")
    return p


def main():
    epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    device = sys.argv[3] if len(sys.argv) > 3 else "mps"
    data_yaml = make_abs_yaml()
    print(f"[train_fire] data={data_yaml} epochs={epochs} imgsz={imgsz} device={device}")
    model = YOLO("yolov8n.pt")
    model.train(
        data=str(data_yaml), epochs=epochs, imgsz=imgsz, batch=16, device=device,
        patience=15, project=str(ROOT / "runs" / "detect"), name="fire_boda_ax",
        exist_ok=True, verbose=True,
    )
    best = ROOT / "runs" / "detect" / "fire_boda_ax" / "weights" / "best.pt"
    print(f"[train_fire] ✅ 완료 → {best}")


if __name__ == "__main__":
    main()
