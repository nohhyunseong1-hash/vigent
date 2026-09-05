"""Phase 0: RF-DETR Nano forklift 1-epoch MPS 벤치 — 동작여부·epoch시간·피크메모리·배치."""
import os, time, resource, sys
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"   # 미지원 연산 CPU 폴백(사용자 지시)
import torch
print(f"torch {torch.__version__} · MPS {torch.backends.mps.is_available()}", flush=True)
from rfdetr import RFDETRNano

DS = os.path.expanduser("~/Downloads/loco_forklift_ds")
OUT = os.path.expanduser("~/Downloads/rfdetr_fk_bench")
bs = int(sys.argv[1]) if len(sys.argv) > 1 else 4

t0 = time.time()
m = RFDETRNano()
t_init = time.time() - t0
print(f"INIT_S={t_init:.1f}", flush=True)
t1 = time.time()
try:
    m.train(dataset_dir=DS, epochs=1, batch_size=bs, grad_accum_steps=1,
            device="mps", num_workers=0, tensorboard=False, output_dir=OUT,
            early_stopping=False, checkpoint_interval=999)
except Exception as e:
    import traceback; traceback.print_exc()
    print(f"TRAIN_FAILED batch={bs}: {type(e).__name__}: {e}", flush=True)
    sys.exit(2)
dt = time.time() - t1
peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9   # macOS: bytes
mps_gb = (torch.mps.driver_allocated_memory() / 1e9) if hasattr(torch.mps, "driver_allocated_memory") else 0
print(f"RESULT batch={bs} EPOCH_S={dt:.1f} PEAK_RSS_GB={peak_rss:.2f} MPS_DRIVER_GB={mps_gb:.2f}", flush=True)
