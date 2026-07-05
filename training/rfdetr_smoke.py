"""RF-DETR 발산 진단 스모크 러너 (T10b ppe NaN). 1-epoch 소형 학습 후 train/loss NaN 여부 판정.
사용:
  python training/rfdetr_smoke.py --tag amp_off  --amp false            # 진단1: AMP off
  python training/rfdetr_smoke.py --tag lr_low    --amp true  --lr 1e-5 # 진단2: lr 1/10
  python training/rfdetr_smoke.py --tag cpu       --amp true  --device cpu  # 진단4: CPU 대조
기본 데이터셋 = ~/Downloads/ppe_subset(build_ppe_subset.py). 출력 = ~/Downloads/rfdetr_smoke_<tag>.
판정: metrics.csv 의 train/loss 가 전부 유한 → PASS(원인 아님/해결), 하나라도 nan → FAIL(발산 재현).
"""
import argparse
import csv
import math
import shutil
from pathlib import Path


def _read_losses(out_dir: Path):
    m = out_dir / "metrics.csv"
    if not m.exists():
        return None
    vals = []
    for r in csv.DictReader(open(m)):
        v = (r.get("train/loss") or "").strip()
        if v != "":
            vals.append(v)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--amp", default="true")
    ap.add_argument("--lr", default=None)
    ap.add_argument("--device", default="mps")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--dataset_dir", default=str(Path.home() / "Downloads" / "ppe_subset"))
    a = ap.parse_args()

    amp = a.amp.lower() in ("1", "true", "yes", "on")
    out_dir = Path.home() / "Downloads" / f"rfdetr_smoke_{a.tag}"
    if out_dir.exists():
        shutil.rmtree(out_dir)   # 항상 fresh(누적 resume 방지)

    kw = dict(dataset_dir=a.dataset_dir, epochs=a.epochs, batch_size=4, grad_accum_steps=4,
              device=a.device, num_workers=0, tensorboard=False, output_dir=str(out_dir),
              early_stopping=False, amp=amp)
    if a.lr is not None:
        kw["lr"] = float(a.lr)

    print(f"[smoke:{a.tag}] amp={amp} lr={a.lr or 'default'} device={a.device} epochs={a.epochs}", flush=True)
    from rfdetr import RFDETRNano
    try:
        RFDETRNano().train(**kw)
    except Exception as ex:  # noqa: BLE001
        print(f"[smoke:{a.tag}] TRAIN_EXCEPTION {type(ex).__name__}: {ex}", flush=True)

    vals = _read_losses(out_dir)
    if not vals:
        print(f"[smoke:{a.tag}] RESULT=NO_METRICS (loss 기록 없음 — 확인 필요)", flush=True)
        return
    nan_n = sum(1 for v in vals if v.lower() in ("nan", "inf", "-inf") or
                (lambda f: f is None or math.isnan(f) or math.isinf(f))(_f(v)))
    verdict = "FAIL_DIVERGED" if nan_n else "PASS_FINITE"
    print(f"[smoke:{a.tag}] RESULT={verdict}  loss행={len(vals)} nan/inf={nan_n} 첫값={vals[0]} 끝값={vals[-1]}", flush=True)


def _f(v):
    try:
        return float(v)
    except Exception:  # noqa: BLE001
        return None


if __name__ == "__main__":
    main()
