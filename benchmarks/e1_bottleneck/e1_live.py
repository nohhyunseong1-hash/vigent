#!/usr/bin/env python3
"""[E1 본판정] 실서비스 직접 계측 — /health 의 lock_wait_ms·infer_ms·decode_ms 를 부하 단계별 수집.

★C5 실패 재발 방지: 등록은 enabled:true 로 하고, **워커가 /health 에 실제로 나타난 뒤**에만
  측정을 시작한다(등록만 되고 부하가 0인 채로 '합격'하는 사고 방지).
★판정은 모의 카메라 집계와 실카메라 단독을 **분리**해 낸다.
"""
import json, subprocess, sys, time, urllib.request
from pathlib import Path
import psutil

ROOT = Path("D:/vigent_original")
BASE = "http://127.0.0.1:8010"
TOK = ""
for line in (ROOT/".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("VIGENT_API_TOKEN="):
        TOK = line.split("=", 1)[1].strip()

def api(path, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}

def gpu():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        u, m = o.stdout.strip().splitlines()[0].split(",")
        return float(u), float(m)
    except Exception:
        return None, None

def svc_pid():
    """VIGENT 서버 프로세스 = 8010 을 LISTEN 중인 파이썬."""
    for c in psutil.net_connections(kind="inet"):
        if c.laddr and c.laddr.port == 8010 and c.status == "LISTEN" and c.pid:
            return c.pid
    return None

def pct(v, q):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v)-1, int(len(v)*q))], 1) if v else None

MOCK_PREFIX = "lv"

def add_mocks(n, vids):
    for i in range(n):
        api("/cameras", "POST", {"id": f"{MOCK_PREFIX}{i}", "name": f"모의{i}",
                                 "source": str(vids[i % len(vids)]), "fps": 2, "enabled": True})

def del_mocks():
    removed = 0
    for i in range(16):
        try:
            api(f"/cameras/{MOCK_PREFIX}{i}", "DELETE"); removed += 1
        except Exception:
            pass
    return removed

def wait_workers(n, timeout=90):
    """★모의 워커 n 개가 실제로 검출을 돌리기 시작할 때까지 기다린다."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        cams = api("/health").get("cameras") or {}
        live = [k for k, v in cams.items()
                if k.startswith(MOCK_PREFIX) and v.get("status") == "ok"
                and (v.get("last_detect_age_s") or 99) < 5]
        if len(live) >= n:
            return True, len(live)
        time.sleep(2)
    cams = api("/health").get("cameras") or {}
    live = [k for k, v in cams.items() if k.startswith(MOCK_PREFIX) and v.get("status") == "ok"]
    return False, len(live)

def sample(label, secs, pid):
    proc = psutil.Process(pid) if pid else None
    psutil.cpu_percent(percpu=True)
    if proc: proc.cpu_percent()
    mock = {"lock": [], "infer": [], "dec": [], "lat": []}
    real = {"lock": [], "infer": [], "dec": [], "lat": []}
    gus, cores_acc, procs = [], [], []
    t_end = time.time() + secs
    while time.time() < t_end:
        time.sleep(2.0)
        try:
            cams = api("/health").get("cameras") or {}
        except Exception:
            continue
        for cid, v in cams.items():
            if v.get("status") != "ok":
                continue
            tgt = mock if cid.startswith(MOCK_PREFIX) else (real if cid == "test" else None)
            if tgt is None:
                continue
            tgt["lock"].append(v.get("lock_wait_ms"))
            tgt["infer"].append(v.get("infer_ms"))
            tgt["dec"].append(v.get("decode_ms"))
            tgt["lat"].append(v.get("last_detect_latency_ms"))
        cores_acc.append(psutil.cpu_percent(percpu=True))
        if proc:
            try: procs.append(proc.cpu_percent())
            except Exception: pass
        u, m = gpu()
        if u is not None: gus.append((u, m))
    core_mean_per_sample = [sum(c)/len(c) for c in cores_acc] if cores_acc else []
    core_max_per_sample = [max(c) for c in cores_acc] if cores_acc else []
    last = cores_acc[-1] if cores_acc else []
    return {
        "label": label,
        "mock_lock_p50": pct(mock["lock"], .5), "mock_lock_p95": pct(mock["lock"], .95),
        "mock_infer_p50": pct(mock["infer"], .5), "mock_infer_p95": pct(mock["infer"], .95),
        "mock_decode_p50": pct(mock["dec"], .5), "mock_decode_p95": pct(mock["dec"], .95),
        "mock_lat_p95": pct(mock["lat"], .95),
        "real_lock_p50": pct(real["lock"], .5), "real_lock_p95": pct(real["lock"], .95),
        "real_infer_p50": pct(real["infer"], .5), "real_infer_p95": pct(real["infer"], .95),
        "real_lat_p50": pct(real["lat"], .5), "real_lat_p95": pct(real["lat"], .95),
        "core_mean": round(sum(core_mean_per_sample)/len(core_mean_per_sample), 1) if core_mean_per_sample else None,
        "core_max": round(max(core_max_per_sample), 1) if core_max_per_sample else None,
        "cores_over50": sum(1 for c in last if c > 50),
        "cores_over80": sum(1 for c in last if c > 80),
        "proc_cpu": round(sum(procs)/len(procs), 1) if procs else None,
        "gpu_util_p95": pct([g[0] for g in gus], .95),
        "gpu_mem": max(g[1] for g in gus) if gus else None,
        "samples_mock": len(mock["infer"]), "samples_real": len(real["infer"]),
    }

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "hi"
    hold = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
    steps = [int(x) for x in (sys.argv[3].split(",") if len(sys.argv) > 3 else ["1","4","7","8"])]
    d = ROOT/"runs"/"rfdetr"/("accident" if mode == "hi" else "lowres")
    vids = sorted(d.glob("*.mp4"))[:7]
    pid = svc_pid()
    print(f"[{mode}] 서비스 PID={pid} · 소스 {len(vids)}편 · 단계 {steps} · 구간 {hold}초", flush=True)
    del_mocks(); time.sleep(3)
    out = []
    try:
        for n in steps:
            n_mock = max(0, n - 1)          # 실카메라 test 1대 포함해 총 N 대
            del_mocks(); time.sleep(3)
            if n_mock:
                add_mocks(n_mock, vids)
                ok, live = wait_workers(n_mock)
                if not ok:
                    print(f"  ⚠ N={n}: 모의 워커 {live}/{n_mock} 만 기동 — 이 구간 건너뜀", flush=True)
                    continue
                print(f"  N={n}: 모의 워커 {live}/{n_mock} 기동 확인", flush=True)
            r = sample(f"N={n}", hold, pid)
            out.append(r)
            print(f"  N={n}: 락대기 p50 {r['mock_lock_p50']} p95 {r['mock_lock_p95']} · "
                  f"추론 p50 {r['mock_infer_p50']} p95 {r['mock_infer_p95']} · "
                  f"디코드 p95 {r['mock_decode_p95']} · 실카 p95 {r['real_lat_p95']} · "
                  f"코어평균 {r['core_mean']}% 최대 {r['core_max']}% (>80%: {r['cores_over80']}) · "
                  f"프로세스 {r['proc_cpu']}% · GPU {r['gpu_util_p95']}%", flush=True)
    finally:
        rm = del_mocks(); time.sleep(4)
        h = api("/health")
        cams = h.get("cameras") or {}
        left = [k for k in cams if k.startswith(MOCK_PREFIX)]
        t = cams.get("test", {})
        print(f"[복구] 모의 제거 시도 {rm} · 잔여 {left} · status={h.get('status')} · "
              f"실카 {t.get('status')} lat={t.get('last_detect_latency_ms')}ms", flush=True)
    Path(f"e1_live_{mode}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

if __name__ == "__main__":
    main()
