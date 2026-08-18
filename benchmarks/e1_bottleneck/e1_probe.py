# [E1] 가설별 실험 — 부하 단계마다 per-core CPU·단계별 소요시간·GPU 를 기록
import json, subprocess, sys, time, urllib.request
from pathlib import Path
ROOT = Path("D:/vigent_original")
TOK = ""
for line in (ROOT/".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("VIGENT_API_TOKEN="): TOK = line.split("=",1)[1].strip()

def api(p, m="GET", b=None):
    d = json.dumps(b).encode() if b else None
    r = urllib.request.Request("http://127.0.0.1:8010"+p, method=m, data=d,
        headers={"Authorization":"Bearer "+TOK, "Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=30) as x:
        raw = x.read(); return json.loads(raw) if raw else {}

def gpu():
    try:
        o = subprocess.check_output(["nvidia-smi","--query-gpu=memory.used,utilization.gpu",
            "--format=csv,noheader,nounits"], stderr=subprocess.DEVNULL).decode().strip()
        u,p = (int(x) for x in o.splitlines()[0].split(",")); return u,p
    except Exception: return None,None

import psutil
def snap(label, secs, srv_pid):
    """secs 초 동안 per-core CPU·단계지표 수집"""
    proc = psutil.Process(srv_pid)
    psutil.cpu_percent(percpu=True); proc.cpu_percent()
    cores=[]; procs=[]; stages=[]; gpus=[]
    t0=time.time()
    while time.time()-t0 < secs:
        time.sleep(2)
        cores.append(psutil.cpu_percent(percpu=True))
        procs.append(proc.cpu_percent())
        h = api("/health")
        for cid,c in (h.get("cameras") or {}).items():
            if c.get("infer_ms") is not None:
                stages.append((cid, c.get("lock_wait_ms"), c.get("infer_ms"),
                               c.get("read_ms"), c.get("last_detect_latency_ms")))
        gpus.append(gpu())
    return {"label":label, "cores":cores, "proc_cpu":procs, "stages":stages, "gpu":gpus}

def pct(v,q):
    v=sorted(x for x in v if x is not None)
    return v[min(len(v)-1,int(len(v)*q))] if v else None

def report(s):
    cores=s["cores"]
    ncore=len(cores[0]) if cores else 0
    # 코어별 평균, 그중 최대/중앙
    avg=[sum(c[i] for c in cores)/len(cores) for i in range(ncore)]
    avg_sorted=sorted(avg, reverse=True)
    lw=[x[1] for x in s["stages"]]; im=[x[2] for x in s["stages"]]
    rd=[x[3] for x in s["stages"]]; tot=[x[4] for x in s["stages"]]
    gm=[g[0] for g in s["gpu"] if g[0]]; gu=[g[1] for g in s["gpu"] if g[1] is not None]
    return {
      "label": s["label"],
      "cores": ncore,
      "core_max_avg": round(avg_sorted[0],1) if avg else None,
      "core_top3": [round(x,1) for x in avg_sorted[:3]],
      "core_mean": round(sum(avg)/len(avg),1) if avg else None,
      "busy_cores_over50": sum(1 for x in avg if x>50),
      "proc_cpu_mean": round(sum(s["proc_cpu"])/len(s["proc_cpu"]),1) if s["proc_cpu"] else None,
      "lock_wait_p50": pct(lw,0.5), "lock_wait_p95": pct(lw,0.95), "lock_wait_max": max(lw) if lw else None,
      "infer_p50": pct(im,0.5), "infer_p95": pct(im,0.95),
      "read_p50": pct(rd,0.5), "read_p95": pct(rd,0.95),
      "total_p95": pct(tot,0.95),
      "gpu_mem": max(gm) if gm else None, "gpu_util_p95": pct([float(x) for x in gu],0.95),
      "samples": len(s["stages"]),
    }

def srv_pid():
    out = subprocess.check_output(["netstat","-ano"]).decode(errors="replace")
    for l in out.splitlines():
        if "0.0.0.0:8010" in l and "LISTENING" in l: return int(l.split()[-1])
    return None

def add(i, src):
    api("/cameras","POST",{"id":f"e1{i}","name":f"e1_{i}","source":src,"fps":2,"enabled":True})
    for _ in range(30):
        time.sleep(1)
        if f"e1{i}" in (api("/health").get("cameras") or {}): return True
    return False

def cleanup():
    n=0
    for c in api("/cameras").get("cameras",[]):
        cid=str(c.get("id") or "")
        if cid.startswith("e1"):
            api(f"/cameras/{cid}","DELETE"); n+=1
    return n

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv)>1 else "hi"
    hold = float(sys.argv[2]) if len(sys.argv)>2 else 120.0
    src_dir = ROOT/"runs"/"rfdetr"/("accident" if mode=="hi" else "lowres")
    vids = sorted(str(p) for p in src_dir.glob("*.mp4"))
    pid = srv_pid()
    out=[]
    try:
        out.append(report(snap("N=1(기준)", 40, pid)))
        for i,n in enumerate([4,7], start=0):
            while len([c for c in api("/cameras").get("cameras",[]) if str(c.get('id','')).startswith('e1')]) < n-1:
                k = len([c for c in api("/cameras").get("cameras",[]) if str(c.get('id','')).startswith('e1')])+1
                if not add(k, vids[(k-1)%len(vids)]):
                    print(f"  경고: e1{k} 워커 미기동"); break
            time.sleep(20)
            out.append(report(snap(f"N={n}", hold, pid)))
    finally:
        print(f"[정리] {cleanup()}대 제거")
    Path(sys.argv[3] if len(sys.argv)>3 else "e1_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'구간':<12} {'최대코어%':>8} {'평균코어%':>8} {'>50%코어':>8} {'프로세스%':>9} "
          f"{'락대기p95':>9} {'추론p95':>8} {'읽기p95':>8} {'GPUutil':>8}")
    for r in out:
        print(f"{r['label']:<12} {r['core_max_avg']:>8} {r['core_mean']:>8} {r['busy_cores_over50']:>8} "
              f"{r['proc_cpu_mean']:>9} {str(r['lock_wait_p95']):>9} {str(r['infer_p95']):>8} "
              f"{str(r['read_p95']):>8} {str(r['gpu_util_p95']):>8}")
