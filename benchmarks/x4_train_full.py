#!/usr/bin/env python3
"""[X-3/X-4] 재학습 1라운드 — 전체 학습(사용자 승인 설정).

기존 ppe_rfdetr_v1.pth에서 이어 파인튜닝. 승인된 설정:
  - epochs=50 상한, early_stopping=True(patience=8) — 이어하는 파인튜닝이라 과적합이
    이르게 올 수 있다는 사용자 판단 근거. 모니터 지표는 라이브러리 기본값인 css valid
    split의 val/mAP_50_95(정규, EMA 아님) — RFDETREarlyStopping 소스 확인.
  - EMA 유지(use_ema, TrainConfig 기본값 True — 별도 설정 불필요).
  - 증강 학습셋: data/datasets/css_safety_aug([X-3a], person random erasing + copy-paste
    가림 + NO-Hardhat/Hardhat 축소, 블러 없음. train 4408장).
  - 해상도 384([Q-2] 실측 근거, 운영 기본값과 동일).
  - loggers extra 미설치 상태 유지(tensorboard/wandb/mlflow/clearml 전부 비활성).

출력은 운영 가중치(vigent-core/weights/)가 아니라 별도 디렉터리에 저장 — [X-4b] 채점 후
채택이 확정되면 그때 vigent-core/weights/로 옮기고 MANIFEST.md에 등록한다(아직 아님).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import torch  # noqa: E402
from rfdetr import RFDETRNano  # noqa: E402

DATASET_DIR = _ROOT / "data" / "datasets" / "css_safety_aug"
BASE_WEIGHTS = _ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"
OUT_DIR = _ROOT / "data" / "runs" / "x4_train_full_ppe_v2"
RESOLUTION = 384
EPOCHS = 50
EARLY_STOPPING_PATIENCE = 8


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device}, torch={torch.__version__}, cuda_available={torch.cuda.is_available()}")
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    model = RFDETRNano(pretrain_weights=str(BASE_WEIGHTS), resolution=RESOLUTION, device=device)

    t0 = time.time()
    model.train(
        dataset_dir=str(DATASET_DIR),
        dataset_file="roboflow",
        output_dir=str(OUT_DIR),
        epochs=EPOCHS,
        early_stopping=True,
        early_stopping_patience=EARLY_STOPPING_PATIENCE,
        num_workers=0,
        tensorboard=False,
        wandb=False,
        mlflow=False,
        clearml=False,
        run_test=False,
        device=device,
        notes="X-4 재학습 1라운드: person random erasing + copy-paste 가림 + NO-Hardhat/Hardhat 축소 증강, epochs=50 상한/early_stopping patience=8",
    )
    elapsed = time.time() - t0

    peak_vram_mb = torch.cuda.max_memory_allocated() / (1024 ** 2) if device == "cuda" else None
    print("\n=== [X-4] 전체 학습 완료 ===")
    print(f"총 소요시간: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    print(f"피크 VRAM: {peak_vram_mb}")
    ckpts = sorted(OUT_DIR.glob("*.pth"))
    print(f"저장된 체크포인트: {[p.name for p in ckpts]}")


if __name__ == "__main__":
    main()
