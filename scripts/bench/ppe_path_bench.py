"""H-2 비교 — PPE 슬롯을 세 경로로 돌려 지연과 **CPU 시간**을 잰다.

★핵심 지표는 지연이 아니라 CPU 시간이다. 파일럿기 병목이 CPU 이므로,
  "빨라졌지만 CPU 를 더 먹는" 경로는 4채널에서 오히려 나쁘다.
  (portable_overrides.yaml 이 이미 경고: onnx-cpu 는 지연 1.85배 빠르지만
   CPU 사용량이 1.7~2.2배 늘 수 있다 - 스핀 서명)

사용: python ppe_path_bench.py <mode> <weights_dir> <video>
  mode: onnx-cpu | ort-cuda | torch-cuda
"""
import os
import sys
import time
from pathlib import Path

import numpy as np

MODE = sys.argv[1]
WDIR = Path(sys.argv[2])
VIDEO = Path(sys.argv[3])
N_WARM, N_RUN = 5, 20

import cv2  # noqa: E402

cap = cv2.VideoCapture(str(VIDEO))
cap.set(cv2.CAP_PROP_POS_FRAMES, 30)
ok, frame = cap.read()
cap.release()
if not ok:
    print("프레임 읽기 실패")
    sys.exit(1)
print(f"프레임 {frame.shape} from {VIDEO.name}")

RES = 384


def preprocess(img):
    x = cv2.resize(img, (RES, RES), interpolation=cv2.INTER_LINEAR)
    x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], np.float32)
    std = np.array([0.229, 0.224, 0.225], np.float32)
    x = (x - mean) / std
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


inp = preprocess(frame)
vram = None

if MODE.startswith("onnx-cpu") or MODE.startswith("ort-cuda"):
    if MODE.startswith("ort-cuda"):
        import torch  # ★먼저 import 해야 ORT 가 CUDA DLL 을 찾는다(R-9)
        torch.zeros(8, device="cuda")
    import onnxruntime as ort
    so = ort.SessionOptions()
    if MODE.endswith("-tuned"):
        # ★앱과 동일한 설정: config/tuning.yaml onnxruntime.tune_sessions(기본 true)
        #   intra_op_threads 4 · inter_op 1 · allow_spinning false (vigent-core/ort_tune.py)
        so.intra_op_num_threads = 4
        so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        print("SessionOptions: intra_op=4 inter_op=1 spin=off (앱 기본값과 동일)")
    else:
        print("SessionOptions: ORT 기본값(intra_op=코어수·스핀 on)")
    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"] if MODE.startswith("ort-cuda") else ["CPUExecutionProvider"]
    sess = ort.InferenceSession(str(WDIR / "ppe_rfdetr_v1.onnx"), so, providers=prov)
    got = sess.get_providers()
    print("providers:", got)
    if MODE.startswith("ort-cuda") and got[0] != "CUDAExecutionProvider":
        print("CUDA EP 로 안 붙었다 - 측정 무효")
        sys.exit(2)
    name = sess.get_inputs()[0].name

    def run():
        sess.run(None, {name: inp})
else:
    import torch
    sys.path.insert(0, str(Path(__file__).parent))
    from rfdetr import RFDETRNano
    m = RFDETRNano(pretrain_weights=str(WDIR / "ppe_rfdetr_v1.pth"), device="cuda", resolution=RES)
    try:
        m.optimize_for_inference()
    except Exception:
        pass
    t_in = torch.from_numpy(inp).cuda()

    def run():
        with torch.inference_mode():
            m.model.model(t_in)

for _ in range(N_WARM):
    run()
if not MODE.startswith("onnx-cpu"):
    import torch
    torch.cuda.synchronize()

t_wall0 = time.perf_counter()
t_cpu0 = time.process_time()
lat = []
for _ in range(N_RUN):
    t = time.perf_counter()
    run()
    lat.append((time.perf_counter() - t) * 1000)
if not MODE.startswith("onnx-cpu"):
    import torch
    torch.cuda.synchronize()
wall = time.perf_counter() - t_wall0
cpu = time.process_time() - t_cpu0

lat.sort()
if not MODE.startswith("onnx-cpu"):
    import torch
    vram = round(torch.cuda.memory_allocated() / 1024**2)

print(f"MODE={MODE}")
print(f"  지연 평균 {sum(lat)/len(lat):7.1f} ms | p50 {lat[len(lat)//2]:7.1f} | p95 {lat[int(len(lat)*0.95)-1]:7.1f}")
print(f"  ★CPU 시간/추론 {cpu/N_RUN*1000:7.1f} ms  (벽시계 {wall/N_RUN*1000:.1f} ms, CPU/벽시계 = {cpu/wall:.2f} 코어)")
print(f"  torch VRAM allocated: {vram} MB" if vram is not None else "  VRAM(torch): 해당 없음(CPU)")

# ★VRAM 은 torch 기준이 아니라 nvidia-smi 의 **프로세스 점유**로 잰다.
#   ORT 가 쓰는 VRAM 은 torch.memory_allocated 에 안 잡힌다(다른 할당자).
import subprocess
try:
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
    mine = [ln for ln in out.splitlines() if ln.strip().startswith(str(os.getpid()))]
    print(f"  ★nvidia-smi 프로세스 VRAM: {mine[0].split(',')[1].strip()} MB" if mine
          else "  ★nvidia-smi 프로세스 VRAM: 이 PID 없음(GPU 미사용)")
except Exception as ex:
    print("  nvidia-smi 조회 실패:", type(ex).__name__)
