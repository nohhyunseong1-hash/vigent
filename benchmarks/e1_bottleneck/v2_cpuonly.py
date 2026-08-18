#!/usr/bin/env python3
"""[V2] GPU-less 성립 판정 — CPU 단독에서 슬롯 구성 × fps 별 카메라당 자원 실측.

핵심 질문: "ONNX-CPU 로 GPU 없이 카메라 1대가 성립하는가"를 이분법이 아니라 수치로.

조건:
  - `VIGENT_DETECT_DEVICE=cpu` 강제(GPU 있어도 안 씀) + `VIGENT_DETECT_BACKEND` 지정
  - 슬롯 구성 4종 × fps 3종 = 12조합. 모델은 한 프로세스에서 지연 로드·캐시되므로 1회 로드로 끝낸다
  - 카메라 1대 기준. 카메라당 환산코어 = 프로세스 CPU% / 100

★person 슬롯은 vision.yaml 에 weights 항목이 없어 현재 배선으로는 ONNX 가 적용되지 않는다
  (rfdetr_adapter.py:147). 이 스크립트도 그 배선을 그대로 따른다 — 즉 backend=onnx-cpu 라도
  person 은 torch-CPU 로 돈다. 이 사실이 결과 해석의 전제다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("VIGENT_DETECT_DEVICE", "cpu")
os.environ.setdefault("VIGENT_ALLOW_FALLBACK", "1")

ROOT = Path("D:/vigent_original")
sys.path.insert(0, str(ROOT / "vigent-core"))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402

CONFIGS = {
    "full": ["person", "ppe", "fire_smoke", "forklift"],
    "ppf":  ["person", "ppe", "fire_smoke"],
    "pp":   ["person", "ppe"],
    "p":    ["person"],
}


def pct(v: list[float], q: float) -> float | None:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * q))], 1) if v else None


def main() -> int:
    backend = sys.argv[1] if len(sys.argv) > 1 else "onnx-cpu"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
    cfgs = (sys.argv[3].split(",") if len(sys.argv) > 3 else ["ppf", "pp", "p", "full"])
    rates = [float(x) for x in (sys.argv[4].split(",") if len(sys.argv) > 4 else ["2", "1.5", "1"])]
    os.environ["VIGENT_DETECT_BACKEND"] = backend

    import vision_loader
    from agents import build_agents
    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]

    # 모든 슬롯 미리 로드(조합마다 로드 시간이 섞이지 않게)
    guard.detect(np.zeros((720, 1280, 3), dtype=np.uint8),
                 detectors=CONFIGS["full"], track_key="warm")
    # 어느 슬롯이 실제로 ONNX 로 갔는지 기록 — "폴백해서 사실은 torch였다"를 막는다
    wiring = {}
    for slot in CONFIGS["full"]:
        m = guard._get_model(slot)
        wiring[slot] = type(getattr(m, "model", m)).__name__ if m else "NONE"
    print(f"[{backend}] 슬롯 배선: {wiring}", flush=True)

    vids = sorted(str(p) for p in (ROOT / "runs/rfdetr/accident").glob("*.mp4"))[:3]
    caps = [cv2.VideoCapture(v) for v in vids]
    fi = 0

    def next_frame():
        nonlocal fi
        for _ in range(len(caps) + 1):
            c = caps[fi % len(caps)]
            fi += 1
            ok, f = c.read()
            if ok:
                return f
            c.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return None

    out = []
    for cfg in cfgs:
        slots = CONFIGS[cfg]
        for rate in rates:
            proc = psutil.Process()
            psutil.cpu_percent(percpu=True)
            proc.cpu_percent()
            lat: list[float] = []
            t_end = time.time() + secs
            nxt = time.time()
            while time.time() < t_end:
                now = time.time()
                if now < nxt:
                    time.sleep(min(0.02, nxt - now))
                    continue
                nxt = now + 1.0 / rate
                img = next_frame()
                if img is None:
                    continue
                t0 = time.time()
                guard.detect(img, detectors=slots, track_key=f"cpu:{cfg}")
                lat.append((time.time() - t0) * 1000)
            cores = psutil.cpu_percent(percpu=True)
            pcpu = round(proc.cpu_percent(), 1)
            r = {"backend": backend, "config": cfg, "n_slots": len(slots), "fps": rate,
                 "calls": len(lat), "lat_p50": pct(lat, .5), "lat_p95": pct(lat, .95),
                 "proc_cpu_pct": pcpu, "cores_detect": round(pcpu / 100.0, 2),
                 "core_mean": round(sum(cores) / len(cores), 1)}
            out.append(r)
            print(f"  [{backend}/{cfg}({len(slots)}슬롯)/{rate}fps] 검출 p50 {r['lat_p50']} "
                  f"p95 {r['lat_p95']}ms · CPU {pcpu}% ({r['cores_detect']}코어)", flush=True)

    Path(f"v2_cpuonly_{backend.replace('-', '_')}.json").write_text(
        json.dumps({"wiring": wiring, "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
