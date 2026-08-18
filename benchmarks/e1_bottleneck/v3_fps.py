#!/usr/bin/env python3
"""[V3] fps 손잡이 실측 — 같은 슬롯 구성에서 카메라당 fps 만 바꿔 잰다.

E1 방법론 재사용: 워커 N 스레드 + 공유 RLock + 같은 guard.detect, 카메라당 2fps 고정.
구성마다 **새 프로세스**로 돌려야 VRAM 이 섞이지 않는다(모델은 지연 로드된다).

측정:
  - VRAM: 이 프로세스가 실제로 점유한 GPU 메모리(nvidia-smi compute-apps, 내 PID)
  - 검출 시간: p50/p95
  - 카메라당 CPU: N=1·N=4 프로세스 CPU 의 기울기 (E1 §7 과 같은 방식)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "D:/vigent_original/vigent-core")
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psutil  # noqa: E402
import vision_loader  # noqa: E402
from agents import build_agents  # noqa: E402

CONFIGS: dict[str, list[str]] = {
    "full":  ["person", "ppe", "fire_smoke", "forklift"],   # ① 4슬롯(코드상 최대)
    "ppf":   ["person", "ppe", "fire_smoke"],               # ③ ★현행 런타임 기본값
    "pp":    ["person", "ppe"],                             # ②
    "p":     ["person"],                                    # ④
}

LOCK = threading.RLock()
STOP = threading.Event()
_lat: dict[str, list[float]] = {}
_slock = threading.Lock()


def my_vram_mib() -> float | None:
    """이 프로세스가 점유한 GPU 메모리(MiB). 서비스 등 다른 프로세스와 섞이지 않는다."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8).stdout
        me = os.getpid()
        for line in out.strip().splitlines():
            pid, mem = (x.strip() for x in line.split(","))
            if int(pid) == me:
                return float(mem)
    except Exception:
        pass
    return None


def worker(name: str, video: str, guard, slots: list[str], fps: float) -> None:
    cap = cv2.VideoCapture(video)
    interval = 1.0 / fps
    lat: list[float] = []
    nxt = time.time()
    while not STOP.is_set():
        now = time.time()
        if now < nxt:
            time.sleep(min(0.02, nxt - now))
            continue
        nxt = now + interval
        ok, img = cap.read()
        if not ok:
            cap.release()
            cap = cv2.VideoCapture(video)
            continue
        t0 = time.time()
        with LOCK:
            guard.detect(img, detectors=slots, track_key=f"v1:{name}")
        lat.append((time.time() - t0) * 1000)
    with _slock:
        _lat[name] = lat


def pct(v: list[float], q: float) -> float | None:
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * q))], 1) if v else None


def run(n: int, vids: list[str], guard, slots: list[str], secs: float, fps: float = 2.0) -> dict:
    _lat.clear()
    STOP.clear()
    ths = [threading.Thread(target=worker, args=(f"w{i}", vids[i % len(vids)], guard, slots, fps),
                            daemon=True) for i in range(n)]
    proc = psutil.Process()
    psutil.cpu_percent(percpu=True)
    proc.cpu_percent()
    for t in ths:
        t.start()
    time.sleep(secs)
    cores = psutil.cpu_percent(percpu=True)
    pcpu = proc.cpu_percent()
    STOP.set()
    for t in ths:
        t.join(timeout=15)
    allv = [x for r in _lat.values() for x in r]
    return {"n": n, "frames": len(allv),
            "lat_p50": pct(allv, .5), "lat_p95": pct(allv, .95),
            "proc_cpu": round(pcpu, 1),
            "core_mean": round(sum(cores) / len(cores), 1),
            "vram_mib": my_vram_mib()}


def main() -> int:
    cfg = sys.argv[1] if len(sys.argv) > 1 else "ppf"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    fps = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    slots = CONFIGS[cfg]
    vids = sorted(str(p) for p in Path("D:/vigent_original/runs/rfdetr/accident").glob("*.mp4"))[:7]

    vram_before = my_vram_mib()
    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    # 예열 — 이 구성이 쓰는 슬롯만 실제로 로드된다(guard._get_model 은 지연 로드)
    guard.detect(np.zeros((720, 1280, 3), dtype=np.uint8), detectors=slots, track_key="warm")
    time.sleep(2.0)
    vram_after = my_vram_mib()

    out = {"config": cfg, "fps": fps, "slots": slots, "n_slots": len(slots),
           "vram_idle_mib": vram_before, "vram_loaded_mib": vram_after, "steps": []}
    for n in (1, 4):
        r = run(n, vids, guard, slots, secs, fps=fps)
        out["steps"].append(r)
        print(f"  [{cfg}@{fps}fps] N={n}: 검출 p50 {r['lat_p50']} p95 {r['lat_p95']}ms · "
              f"프로세스 CPU {r['proc_cpu']}% · 코어평균 {r['core_mean']}% · VRAM {r['vram_mib']}MiB",
              flush=True)

    s1, s4 = out["steps"]
    per_cam = round((s4["proc_cpu"] - s1["proc_cpu"]) / 3.0, 1)      # 카메라 1대 추가당 CPU
    out["cpu_per_camera_pct"] = per_cam
    out["cores_per_camera_detect"] = round(per_cam / 100.0, 2)
    # E1 §7: 검출 밖 파이프라인(인코딩·추적·존·익명화·WS)은 슬롯 구성과 무관하게 약 0.65 코어
    out["cores_per_camera_total_est"] = round(per_cam / 100.0 + 0.65, 2)
    print(f"  [{cfg}@{fps}fps] ★카메라당 검출 CPU {per_cam}% ({out['cores_per_camera_detect']}코어) · "
          f"총 추정 {out['cores_per_camera_total_est']}코어 · "
          f"VRAM {out['vram_loaded_mib']}MiB", flush=True)
    Path(f"v3_{cfg}_{fps}fps.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
