#!/usr/bin/env python3
"""[X-3b] RF-DETR 재학습 1 epoch 스모크 — VRAM·소요시간 실측, 체크포인트 저장 확인.

전체 학습(수십 epoch)을 돌리기 전, 이 환경(RTX 5070 Ti, cu130)에서 파이프라인이 실제로
도는지 + 1 epoch당 걸리는 시간을 재서 전체 소요시간을 추정한다. **여기서 epochs=1만 돈다 —
전체 학습은 이 스크립트가 아니라 별도 승인 후 실행.**

기존 ppe_rfdetr_v1.pth 에서 이어서 파인튜닝(from-scratch COCO 사전학습이 아님).
데이터셋: data/datasets/css_safety_aug([X-3a] 증강 학습셋, train 4408장).
출력은 vigent-core/weights/ 가 아니라 별도 스모크 전용 디렉터리에 저장(운영 가중치 미변경).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import torch  # noqa: E402
from rfdetr import RFDETRNano  # noqa: E402

DATASET_DIR = _ROOT / "data" / "datasets" / "css_safety_aug"
BASE_WEIGHTS = _ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth"
OUT_DIR = _ROOT / "data" / "runs" / "x3b_smoke_ppe"
RESOLUTION = 384   # [Q-2] 실측 근거로 운영 기본값과 동일


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
        epochs=1,
        checkpoint_interval=1,
        num_workers=0,          # Windows 멀티프로세스 DataLoader 이슈 회피
        tensorboard=False,       # loggers extra 미설치(승인 범위 밖) — 꺼서 의존성 불필요
        wandb=False,
        mlflow=False,
        clearml=False,
        run_test=False,          # css v27 자체 test 82장은 우리 field_eval test 35장과 무관, 채점 대상 아님
        device=device,
    )
    elapsed = time.time() - t0

    peak_vram_mb = None
    if device == "cuda":
        peak_vram_mb = torch.cuda.max_memory_allocated() / (1024 ** 2)

    ckpt_files = sorted(OUT_DIR.glob("*.pth"))
    result = {
        "elapsed_sec_1epoch": elapsed,
        "peak_vram_mb": peak_vram_mb,
        "checkpoints_saved": [str(p.name) for p in ckpt_files],
        "resolution": RESOLUTION,
        "dataset_dir": str(DATASET_DIR),
        "train_images": None,
    }
    coco = json.loads((DATASET_DIR / "train" / "_annotations.coco.json").read_text(encoding="utf-8"))
    result["train_images"] = len(coco["images"])

    print("\n=== [X-3b] 스모크 결과 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    (OUT_DIR / "smoke_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
