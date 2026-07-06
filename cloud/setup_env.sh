#!/bin/bash
# T10b 클라우드 인스턴스 환경 셋업 (CUDA). RunPod pytorch 이미지(CUDA torch 사전탑재) 가정.
#   rfdetr + 학습/평가 deps 설치. 비밀 미탑재. 로컬과 버전 정합(재현성).
set -eu
echo "=== [setup] python/torch/cuda 확인 ==="
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-CUDA')"

echo "=== [setup] RF-DETR + 학습 deps 설치 ==="
pip install -q -U pip
# rfdetr 1.8.0 extras 메타데이터가 깨져 있어 학습 필수 deps 를 명시 설치(로컬 경험 반영)
pip install -q \
  rfdetr==1.8.0 \
  supervision==0.29.0.post0 \
  pytorch_lightning==2.6.5 torchmetrics lightning-utilities \
  albumentations kornia peft accelerate \
  faster-coco-eval==1.7.2 pycocotools==2.0.11 \
  pyyaml opencv-python-headless

echo "=== [setup] rfdetr import 검증 ==="
python -c "from rfdetr import RFDETRNano; print('rfdetr OK')"
mkdir -p /workspace/data /workspace/out
echo "=== [setup] 완료 ==="
