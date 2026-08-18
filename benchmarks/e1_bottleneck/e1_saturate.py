# [E1] 포화 자원 특정 — 처리량 상한(inference/s)과 그때의 CPU/GPU 점유를 동시에 측정.
#   fps 제한을 풀고(가능한 한 빨리) N을 늘려, 시스템이 실제로 낼 수 있는 검출 처리량을 잰다.
import json, subprocess, sys, threading, time
from pathlib import Path
sys.path.insert(0, "D:/vigent_original/vigent-core")
import cv2, numpy as np, psutil, vision_loader
from agents import build_agents

import contextlib, os
_NOLOCK = os.environ.get("E1_NOLOCK") == "1"      # ★락 제거 대조군(측정 전용)
LOCK = contextlib.nullcontext() if _NOLOCK else threading.RLock()
STOP = threading.Event()
counts, lat = {}, {}
slock = threading.Lock()

def gpu():
    try:
        o = subprocess.run(["nvidia-smi","--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        u, m = o.stdout.strip().split("\n")[0].split(",")
        return float(u), float(m)
    except Exception:
        return None, None

def worker(name, video, guard):
    cap = cv2.VideoCapture(video)
    n = 0; ls = []
    while not STOP.is_set():
        ok, img = cap.read()
        if not ok:
            cap.release(); cap = cv2.VideoCapture(video); continue
        t0 = time.time()
        with LOCK:
            guard.detect(img, detectors=["person","ppe","fire_smoke"], track_key=f"sat:{name}")
        ls.append((time.time()-t0)*1000); n += 1
    with slock:
        counts[name] = n; lat[name] = ls

def run(n, vids, secs):
    counts.clear(); lat.clear(); STOP.clear()
    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    guard.detect(np.zeros((720,1280,3),dtype=np.uint8), detectors=["person","ppe","fire_smoke"], track_key="warm")
    ths=[threading.Thread(target=worker,args=(f"w{i}",vids[i%len(vids)],guard),daemon=True) for i in range(n)]
    psutil.cpu_percent(percpu=True); proc=psutil.Process(); proc.cpu_percent()
    gu=[]
    for t in ths: t.start()
    t_end=time.time()+secs
    while time.time()<t_end:
        time.sleep(3.0); u,_=gpu()
        if u is not None: gu.append(u)
    cores=psutil.cpu_percent(percpu=True); pc=proc.cpu_percent()
    STOP.set()
    for t in ths: t.join(timeout=15)
    tot=sum(counts.values()); all_l=[x for v in lat.values() for x in v]
    all_l.sort()
    return {"n":n,"throughput_infps":round(tot/secs,2),
            "lat_p50":round(all_l[len(all_l)//2],1) if all_l else None,
            "lat_p95":round(all_l[int(len(all_l)*0.95)],1) if all_l else None,
            "core_max":round(max(cores),1),"core_mean":round(sum(cores)/len(cores),1),
            "cores_over80":sum(1 for c in cores if c>80),"proc_cpu":round(pc,1),
            "gpu_util_mean":round(sum(gu)/len(gu),1) if gu else None,
            "gpu_util_max":max(gu) if gu else None}

if __name__=="__main__":
    secs=float(sys.argv[1]) if len(sys.argv)>1 else 45.0
    vids=sorted(str(p) for p in Path("D:/vigent_original/runs/rfdetr/accident").glob("*.mp4"))[:7]
    out=[]
    for n in (1,2,4,7):
        r=run(n,vids,secs); out.append(r)
        print(f"N={r['n']}: 처리량 {r['throughput_infps']} 검출/초 · 지연p50 {r['lat_p50']} p95 {r['lat_p95']}ms · "
              f"코어최대 {r['core_max']}% 평균 {r['core_mean']}% (>80%: {r['cores_over80']}개) · "
              f"프로세스 {r['proc_cpu']}% · GPU평균 {r['gpu_util_mean']}% 최대 {r['gpu_util_max']}%", flush=True)
    Path(f"e1_saturate{'_nolock' if _NOLOCK else ''}.json").write_text(json.dumps(out,ensure_ascii=False,indent=1),encoding="utf-8")
