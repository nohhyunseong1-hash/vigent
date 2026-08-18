# [E1] H2(추론 직렬화)·H3(GIL) 판정 — 서비스와 무관한 별도 프로세스에서 동일 구조 재현
#   워커 N개를 스레드로 띄워 각자 디코드→(공유 락)→검출 을 돌리고,
#   락 대기 / 락 안 추론 / 디코드 시간을 분리 계측한다.
import json, sys, threading, time
from pathlib import Path
sys.path.insert(0, "D:/vigent_original/vigent-core")
import cv2, psutil, vision_loader
from agents import build_agents

import contextlib, os
_NOLOCK = os.environ.get("E1_NOLOCK") == "1"
# ★H2 인과 검정용 대조군: 락을 없앤 것 외 모든 조건 동일. 이 프로세스 안에서만 유효하며
#   서비스(DETECT_LOCK)는 그대로다 — 동작 변경 아님, 측정 전용.
LOCK = contextlib.nullcontext() if _NOLOCK else threading.RLock()   # app_state.DETECT_LOCK 과 같은 구조
STOP = threading.Event()
stats = {}
slock = threading.Lock()

def worker(name, video, guard, fps):
    cap = cv2.VideoCapture(video)
    interval = 1.0 / fps
    rec = {"decode": [], "wait": [], "infer": []}
    nxt = time.time()
    while not STOP.is_set():
        now = time.time()
        if now < nxt:
            time.sleep(min(0.02, nxt - now)); continue
        nxt = now + interval
        t0 = time.time()
        ok, img = cap.read()
        if not ok:
            cap.release(); cap = cv2.VideoCapture(video); continue
        t1 = time.time()
        with LOCK:
            t2 = time.time()
            guard.detect(img, detectors=["person", "ppe", "fire_smoke"], track_key=f"e1:{name}")
            t3 = time.time()
        rec["decode"].append((t1-t0)*1000)
        rec["wait"].append((t2-t1)*1000)
        rec["infer"].append((t3-t2)*1000)
    with slock:
        stats[name] = rec

def pct(v, q):
    v = sorted(v)
    return round(v[min(len(v)-1, int(len(v)*q))], 1) if v else None

def run(n, videos, secs, fps=2.0):
    global stats
    stats = {}; STOP.clear()
    guard = build_agents(vision_loader.load_vision("safety"))["Guard"]
    import numpy as np
    guard.detect(np.zeros((720,1280,3), dtype=np.uint8), detectors=["person","ppe","fire_smoke"], track_key="warm")
    ths = [threading.Thread(target=worker, args=(f"w{i}", videos[i % len(videos)], guard, fps), daemon=True)
           for i in range(n)]
    psutil.cpu_percent(percpu=True)
    proc = psutil.Process(); proc.cpu_percent()
    for t in ths: t.start()
    time.sleep(secs)
    cores_end = psutil.cpu_percent(percpu=True)
    pcpu = proc.cpu_percent()
    STOP.set()
    for t in ths: t.join(timeout=10)
    dec = [x for r in stats.values() for x in r["decode"]]
    wai = [x for r in stats.values() for x in r["wait"]]
    inf = [x for r in stats.values() for x in r["infer"]]
    cs = sorted(cores_end, reverse=True)
    return {"n": n, "frames": len(inf),
            "decode_p50": pct(dec,0.5), "decode_p95": pct(dec,0.95),
            "wait_p50": pct(wai,0.5), "wait_p95": pct(wai,0.95), "wait_max": round(max(wai),1) if wai else None,
            "infer_p50": pct(inf,0.5), "infer_p95": pct(inf,0.95),
            "core_max": round(cs[0],1), "core_top3": [round(x,1) for x in cs[:3]],
            "cores_over50": sum(1 for x in cores_end if x > 50),
            "proc_cpu": round(pcpu,1),
            "throughput_fps": round(len(inf)/secs, 2)}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "hi"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    d = Path("D:/vigent_original/runs/rfdetr") / ("accident" if mode=="hi" else "lowres")
    # ★hi/lo 가 같은 장면을 쓰도록 앞 7편만 사용(low1..low7 == accident[0:7], 1/9 픽셀)
    vids = sorted(str(p) for p in d.glob("*.mp4"))[:7]
    out = []
    for n in (1, 4, 7):
        r = run(n, vids, secs)
        out.append(r)
        print(f"N={r['n']}: 디코드p95 {r['decode_p95']}ms · 락대기p50 {r['wait_p50']} p95 {r['wait_p95']}ms · "
              f"추론p50 {r['infer_p50']} p95 {r['infer_p95']}ms · 최대코어 {r['core_max']}% · "
              f">50%코어 {r['cores_over50']} · 프로세스 {r['proc_cpu']}% · 처리량 {r['throughput_fps']}fps", flush=True)
    Path(f"e1_standalone_{mode}{'_nolock' if _NOLOCK else ''}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
