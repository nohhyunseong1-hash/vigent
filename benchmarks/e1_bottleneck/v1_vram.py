#!/usr/bin/env python3
"""[V1-보완] 슬롯 구성별 VRAM 실측.

Windows WDDM 은 nvidia-smi 의 per-PID 메모리를 지원하지 않는다(전부 N/A) — 그래서
①torch 자체 계정(모델 가중치+활성값)과 ②프로세스 기동 전후 GPU 총량 델타(=CUDA 컨텍스트 포함)
두 가지로 잰다. 구매 판단에 필요한 값은 ②(실제 카드 점유)다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "D:/vigent_original/vigent-core")

CONFIGS = {
    "full": ["person", "ppe", "fire_smoke", "forklift"],
    "ppf":  ["person", "ppe", "fire_smoke"],
    "pp":   ["person", "ppe"],
    "p":    ["person"],
}


def gpu_total_mib() -> float | None:
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=8)
        return float(o.stdout.strip().splitlines()[0])
    except Exception:
        return None


def main() -> int:
    cfg = sys.argv[1]
    slots = CONFIGS[cfg]
    base = float(sys.argv[2])          # 부모가 잰 기동 전 GPU 총량

    import numpy as np
    import torch
    import vision_loader
    from agents import build_agents

    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.detect(np.zeros((720, 1280, 3), dtype=np.uint8), detectors=slots, track_key="warm")
    # 실제 프레임으로 한 번 더 — 활성값(activation) 최대치를 반영
    guard.detect(np.zeros((1080, 1920, 3), dtype=np.uint8), detectors=slots, track_key="warm2")
    time.sleep(3.0)

    torch_alloc = round(torch.cuda.memory_allocated() / 1024 ** 2, 1)
    torch_reserved = round(torch.cuda.memory_reserved() / 1024 ** 2, 1)
    total_now = gpu_total_mib()
    delta = round(total_now - base, 1) if (total_now is not None) else None

    out = {"config": cfg, "slots": slots, "n_slots": len(slots),
           "torch_allocated_mib": torch_alloc, "torch_reserved_mib": torch_reserved,
           "gpu_total_before_mib": base, "gpu_total_after_mib": total_now,
           "process_vram_mib": delta}
    print(f"  [{cfg}] {len(slots)}슬롯 · torch 할당 {torch_alloc}MiB / 예약 {torch_reserved}MiB · "
          f"★프로세스 실점유 {delta}MiB (CUDA 컨텍스트 포함)", flush=True)
    Path(f"v1_vram_{cfg}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
