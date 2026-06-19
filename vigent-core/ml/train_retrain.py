"""병합 데이터셋으로 yolo11 파인튜닝(맥 MPS). 사무실 사람↔모니터 혼동 교정 목적.

사용:
  python3 vigent-core/ml/train_retrain.py --epochs 30
  python3 vigent-core/ml/train_retrain.py --epochs 1   # 빠른 점검(시간 측정)
출력: runs/retrain/office_person_v1/weights/best.pt
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data" / "retrain" / "merged" / "data.yaml"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--base", default=str(ROOT / "vigent-core" / "weights" / "yolo11m.pt"))
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--name", default="office_person_v1")
    args = ap.parse_args()

    from ultralytics import YOLO
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[VIGENT 재학습] base={Path(args.base).name} device={device} "
          f"epochs={args.epochs} imgsz={args.imgsz} batch={args.batch}")

    model = YOLO(args.base)
    model.train(
        data=str(DATA),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        patience=8,                 # 개선 없으면 조기 종료
        project=str(ROOT / "runs" / "retrain"),
        name=args.name,
        exist_ok=True,
        verbose=True,
    )
    best = ROOT / "runs" / "retrain" / args.name / "weights" / "best.pt"
    print(f"✅ 학습 완료. best: {best}")


if __name__ == "__main__":
    main()
