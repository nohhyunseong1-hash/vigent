#!/bin/bash
# T10b 클라우드 학습 오케스트레이션 (CUDA). ppe → fire_smoke 연속 학습 + SHA256.
# 게이트 평가는 로컬 회수 후 실행(MPS/CPU 추론은 정상 — 버그는 학습에만). 인스턴스는 학습+해시만.
# 사전: setup_env.sh 완료 · /workspace/data/ppe_rfdetr_ds 업로드됨 · D-Fire 는 $DFIRE_DIR 에 존재.
set -eu
WS=/workspace
DFIRE_DIR="${DFIRE_DIR:-$WS/data/dfire}"
OUT="$WS/out"; mkdir -p "$OUT"
cd "$WS"

finite_check() {  # $1=metrics.csv → loss 유한이면 0, nan 이면 1
  python - "$1" <<'PY'
import csv,sys,math
rows=list(csv.DictReader(open(sys.argv[1])))
vals=[r.get('train/loss','').strip() for r in rows if r.get('train/loss','').strip()]
bad=any(v.lower() in ('nan','inf','-inf') for v in vals) or not vals
print("LOSS_FINITE" if not bad else "LOSS_NAN", "| 첫값", vals[0] if vals else "없음")
sys.exit(1 if bad else 0)
PY
}

echo "########## 1. fire_smoke 데이터셋 빌드(대안D) ##########"
[ -d "$DFIRE_DIR/train/images" ] || { echo "❌ D-Fire 없음: $DFIRE_DIR (업로드 또는 다운로드 필요)"; exit 1; }
python build_fire_smoke_train_ds.py --dfire "$DFIRE_DIR" --out "$WS/data/fire_rfdetr_ds" --neg 2000

echo "########## 2. ppe 1-epoch 스모크(CUDA loss 유한 확인) ##########"
python rfdetr_train.py --dataset_dir "$WS/data/ppe_rfdetr_ds" --output_dir "$OUT/ppe_smoke" \
  --epochs 1 --batch 8 --grad_accum 2 --device cuda >/dev/null 2>&1 || true
finite_check "$OUT/ppe_smoke/metrics.csv" || { echo "❌ ppe CUDA 스모크 NaN — 중단(예상 밖, 보고 필요)"; exit 1; }
echo "  ✅ ppe CUDA 스모크 loss 유한"

echo "########## 3. ppe 본학습(50ep) ##########"
python rfdetr_train.py --dataset_dir "$WS/data/ppe_rfdetr_ds" --output_dir "$OUT/ppe_full" \
  --epochs 50 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 10
cp "$OUT/ppe_full/checkpoint_best_total.pth" "$OUT/ppe_rfdetr_v1.pth"

echo "########## 4. fire_smoke 1-epoch 스모크 ##########"
python rfdetr_train.py --dataset_dir "$WS/data/fire_rfdetr_ds" --output_dir "$OUT/fire_smoke" \
  --epochs 1 --batch 8 --grad_accum 2 --device cuda >/dev/null 2>&1 || true
finite_check "$OUT/fire_smoke/metrics.csv" || { echo "❌ fire CUDA 스모크 NaN — 중단"; exit 1; }
echo "  ✅ fire CUDA 스모크 loss 유한"

echo "########## 5. fire_smoke 본학습(대안D: 15ep→resume 30ep) ##########"
python rfdetr_train.py --dataset_dir "$WS/data/fire_rfdetr_ds" --output_dir "$OUT/fire_full" \
  --epochs 15 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 5
python rfdetr_train.py --dataset_dir "$WS/data/fire_rfdetr_ds" --output_dir "$OUT/fire_full" \
  --epochs 30 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 5   # resume(같은 dir 자동재개)
cp "$OUT/fire_full/checkpoint_best_total.pth" "$OUT/fire_smoke_rfdetr_v1.pth"

echo "########## 6. SHA256(회수 후 로컬 대조용) ##########"
cd "$OUT"
for w in ppe_rfdetr_v1.pth fire_smoke_rfdetr_v1.pth; do
  sha256sum "$w" | tee "$w.sha256"
done
echo "########## 완료 — /workspace/out/*.pth 회수 후 로컬 게이트 평가 ##########"
