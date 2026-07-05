"""T10b Phase 1 트레이너 — RFDETRNano 클래스별 학습(MPS, 야간 무인).

안전장치: 자동 resume(최신 체크포인트에서 이어달리기), 주기 체크포인트, 완료/실패 마커.
호출(caffeinate로 감싸 실행):
  caffeinate -i /opt/anaconda3/bin/python3 training/rfdetr_train.py \
    --dataset_dir ~/Downloads/loco_forklift_ds --output_dir ~/Downloads/rfdetr_forklift \
    --epochs 50 --batch 4 --grad_accum 4
resume: --output_dir 에 checkpoint*.pth 있으면 최신에서 자동 이어달리기(에폭 연장도 동일).
"""
import argparse
import glob
import os
import sys
import time

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")   # 미지원 연산 CPU 폴백


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_dir", required=True)
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad_accum", type=int, default=4)      # 유효 배치 16(Roboflow 권장)
    ap.add_argument("--checkpoint_interval", type=int, default=5)
    args = ap.parse_args()

    from rfdetr import RFDETRNano

    os.makedirs(args.output_dir, exist_ok=True)
    ckpts = sorted(glob.glob(os.path.join(args.output_dir, "checkpoint*.pth")), key=os.path.getmtime)
    resume = ckpts[-1] if ckpts else None
    print(f"[trainer] start dataset={args.dataset_dir} epochs={args.epochs} batch={args.batch}"
          f" grad_accum={args.grad_accum} resume={resume}", flush=True)

    t0 = time.time()
    m = RFDETRNano()
    try:
        m.train(dataset_dir=args.dataset_dir, epochs=args.epochs, batch_size=args.batch,
                grad_accum_steps=args.grad_accum, device="mps", num_workers=0,
                tensorboard=False, output_dir=args.output_dir,
                checkpoint_interval=args.checkpoint_interval, early_stopping=False,
                resume=resume)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"[trainer] TRAIN_FAILED: {type(e).__name__}: {e}", flush=True)
        sys.exit(2)
    print(f"[trainer] TRAIN_DONE elapsed_h={(time.time()-t0)/3600:.2f} output={args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
