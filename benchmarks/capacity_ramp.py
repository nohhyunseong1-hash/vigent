#!/usr/bin/env python3
"""[C-1] 저비용 하드웨어 경로 1단계 — 카메라 수 증설 처리량 실측(재사용 스크립트).

파일 카메라 N개를 VIGENT API로 동시 등록(누적 증설)해 --steps 리스트대로 단계 확장하며,
각 단계에서 GPU/CPU/메모리·검출 지연(p50/p95)을 측정하고 병목(GPU 포화/CPU 디코딩 포화/
메모리)을 판정한다.

★ 디바이스(GPU/CPU) 전환은 이 스크립트가 하지 않는다 — device.py(VIGENT_DETECT_DEVICE)는
서버 프로세스 시작 시 1회만 읽으므로, GPU 스텝은 일반 기동 서버에, CPU 스텝은
VIGENT_DETECT_DEVICE=cpu 로 별도 기동한 서버에 각각 이 스크립트를 따로 실행해야 한다.

사용 예:
  python benchmarks/capacity_ramp.py --steps 4,8,16,24 --fps 1.0 \
    --url http://127.0.0.1:8010 --token <토큰> --pid <서버PID> \
    --video runs/rfdetr/multi_scene.mp4 --tag gpu \
    --out benchmarks/results/capacity_gpu.jsonl --cleanup

후보 기종 구매 후 동일 스크립트를 그 기종에서 재실행해 최종 확정하는 것이 다음 단계다
(이 desktop 실측은 개발기 기준 — 배포 후보 기종의 절대 성능치가 아니다. 병목 구조 규명과
CPU 모드 근사치 확보가 목적, benchmarks/../docs/ops_capacity_sizing.md §해석 주의 참고).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False

KST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _req(method: str, url: str, token: str, payload: dict | None = None, timeout: float = 10.0):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if body else None)


def register_camera(base_url: str, token: str, cid: str, video: str, fps: float) -> None:
    payload = {"id": cid, "name": cid, "source": video, "fps": fps, "enabled": True}
    status, _ = _req("POST", base_url.rstrip("/") + "/cameras", token, payload)
    if status not in (200, 201):
        raise RuntimeError(f"카메라 등록 실패({cid}): HTTP {status}")


def disable_delete_camera(base_url: str, token: str, cid: str) -> None:
    try:
        _req("POST", base_url.rstrip("/") + f"/cameras/{cid}/disable", token, {})
    except Exception:  # noqa: BLE001  정리 실패해도 계속
        pass
    try:
        r = urllib.request.Request(base_url.rstrip("/") + f"/cameras/{cid}", method="DELETE")
        if token:
            r.add_header("Authorization", f"Bearer {token}")
        urllib.request.urlopen(r, timeout=10.0)
    except Exception:  # noqa: BLE001
        pass


def sample_gpu() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return None
        util_gpu, util_mem, mem_used, mem_total = [x.strip() for x in out.stdout.strip().split(",")]
        return {"util_gpu_pct": float(util_gpu), "vram_used_mb": float(mem_used),
                "vram_total_mb": float(mem_total)}
    except Exception:  # noqa: BLE001  GPU 없는(CPU 전용) 장비/드라이버 미설치 — 무해
        return None


_proc_cache: dict[int, "psutil.Process"] = {}


def sample_proc(pid: int) -> dict | None:
    """psutil.Process.cpu_percent(interval=None)는 '같은 Process 객체'의 직전 호출 이후
    경과분을 누적 계산한다 — 매번 새 Process(pid)를 만들면 항상 0을 반환한다(버그, 최초
    실행에서 발견). 프로세스당 1개 인스턴스를 캐시해 재사용한다."""
    if not _HAVE_PSUTIL or not pid:
        return None
    try:
        p = _proc_cache.get(pid)
        if p is None:
            p = psutil.Process(pid)
            p.cpu_percent(interval=None)   # 기준선 설정(이 첫 호출값은 버림)
            _proc_cache[pid] = p
        cpu_pct = p.cpu_percent(interval=None)
        rss_mb = p.memory_info().rss / (1024 * 1024)
        return {"proc_cpu_pct": cpu_pct, "proc_rss_mb": round(rss_mb, 1)}
    except Exception:  # noqa: BLE001
        return None


def probe_latency(base_url: str, token: str) -> dict:
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
               "42YAAAAASUVORK5CYII=")
    payload = json.dumps({"image": "data:image/png;base64," + png_b64}).encode()
    r = urllib.request.Request(base_url.rstrip("/") + "/rfdetr/frame", data=payload, method="POST",
                                headers={"Content-Type": "application/json"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            resp.read()
            ok = resp.status == 200
    except Exception as ex:  # noqa: BLE001
        return {"latency_ms": None, "ok": False, "error": f"{type(ex).__name__}: {ex}"}
    return {"latency_ms": round((time.time() - t0) * 1000, 1), "ok": ok}


def system_cpu_pct() -> float | None:
    if not _HAVE_PSUTIL:
        return None
    try:
        return psutil.cpu_percent(interval=None)
    except Exception:  # noqa: BLE001
        return None


def judge_bottleneck(gpu_avg: float | None, proc_cpu_avg: float | None, sys_cpu_avg: float | None,
                      n_cores: int | None, p95_ms: float | None, fail_rate: float) -> str:
    """휴리스틱 판정 — 절대 기준 아님, 이 desktop 조건에서의 상대적 신호(규칙7)."""
    reasons = []
    if gpu_avg is not None and gpu_avg >= 90:
        reasons.append("GPU 포화(util≥90%)")
    if sys_cpu_avg is not None and sys_cpu_avg >= 85:
        reasons.append("CPU 포화(시스템 전체≥85%, 디코딩 등)")
    if fail_rate > 0.05:
        reasons.append(f"프로브 실패율 {fail_rate*100:.0f}%(과부하로 응답 불가 추정)")
    if p95_ms is not None and p95_ms > 1000:
        reasons.append(f"p95 지연 {p95_ms:.0f}ms(1초 초과 — 실사용 부적합 수준)")
    return " + ".join(reasons) if reasons else "미포화(여유 있음)"


def run_step(base_url: str, token: str, pid: int, n_target: int, registered: list[str],
             cam_prefix: str, video: str, fps: float, warmup_s: float, measure_s: float,
             sample_interval_s: float, out_f) -> dict:
    # 누적 증설 — 이미 등록된 것 초과분만 새로 추가
    while len(registered) < n_target:
        cid = f"{cam_prefix}{len(registered)+1}"
        register_camera(base_url, token, cid, video, fps)
        registered.append(cid)
        out_f.write(json.dumps({"ts": _now(), "type": "register", "cid": cid, "n": len(registered)},
                                ensure_ascii=False) + "\n")
        out_f.flush()

    print(f"[capacity_ramp] n={n_target} 등록 완료 — 워밍업 {warmup_s}s")
    time.sleep(warmup_s)
    if _HAVE_PSUTIL and pid:
        sample_proc(pid)          # cpu_percent 기준선 리셋(첫 호출은 0 근사이므로 워밍업 뒤 버림)
        system_cpu_pct()

    t_end = time.time() + measure_s
    gpu_samples, proc_samples, sys_cpu_samples, lat_samples, fails = [], [], [], [], 0
    n_probes = 0
    while time.time() < t_end:
        g = sample_gpu()
        if g:
            gpu_samples.append(g["util_gpu_pct"])
            out_f.write(json.dumps({"ts": _now(), "type": "gpu", "n": n_target, **g},
                                    ensure_ascii=False) + "\n")
        ps = sample_proc(pid)
        if ps:
            proc_samples.append(ps)
            out_f.write(json.dumps({"ts": _now(), "type": "proc", "n": n_target, **ps},
                                    ensure_ascii=False) + "\n")
        sc = system_cpu_pct()
        if sc is not None:
            sys_cpu_samples.append(sc)
        lat = probe_latency(base_url, token)
        n_probes += 1
        if lat.get("ok"):
            lat_samples.append(lat["latency_ms"])
        else:
            fails += 1
        out_f.write(json.dumps({"ts": _now(), "type": "latency_probe", "n": n_target, **lat},
                                ensure_ascii=False) + "\n")
        out_f.flush()
        time.sleep(max(0.1, sample_interval_s))

    lat_sorted = sorted(lat_samples)

    def pct(p):
        if not lat_sorted:
            return None
        idx = min(len(lat_sorted) - 1, int(len(lat_sorted) * p))
        return lat_sorted[idx]

    gpu_avg = round(statistics.mean(gpu_samples), 1) if gpu_samples else None
    gpu_max = round(max(gpu_samples), 1) if gpu_samples else None
    proc_cpu_avg = round(statistics.mean([p["proc_cpu_pct"] for p in proc_samples]), 1) if proc_samples else None
    rss_last = proc_samples[-1]["proc_rss_mb"] if proc_samples else None
    sys_cpu_avg = round(statistics.mean(sys_cpu_samples), 1) if sys_cpu_samples else None
    n_cores = psutil.cpu_count() if _HAVE_PSUTIL else None
    fail_rate = fails / n_probes if n_probes else 0.0

    summary = {
        "ts": _now(), "type": "step_summary", "n": n_target,
        "gpu_util_avg_pct": gpu_avg, "gpu_util_max_pct": gpu_max,
        "proc_cpu_avg_pct": proc_cpu_avg, "proc_rss_mb": rss_last,
        "sys_cpu_avg_pct": sys_cpu_avg, "n_cores": n_cores,
        "latency_p50_ms": pct(0.50), "latency_p95_ms": pct(0.95),
        "latency_max_ms": lat_sorted[-1] if lat_sorted else None,
        "n_probes": n_probes, "n_fail": fails, "fail_rate": round(fail_rate, 3),
        "bottleneck": judge_bottleneck(gpu_avg, proc_cpu_avg, sys_cpu_avg, n_cores,
                                        pct(0.95), fail_rate),
    }
    out_f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    out_f.flush()
    print(f"[capacity_ramp] n={n_target} 결과: GPU avg={gpu_avg}% proc_cpu avg={proc_cpu_avg}% "
          f"sys_cpu avg={sys_cpu_avg}% p50={summary['latency_p50_ms']}ms p95={summary['latency_p95_ms']}ms "
          f"실패={fails}/{n_probes} → {summary['bottleneck']}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps", required=True, help="콤마구분 누적 카메라 수, 예: 4,8,16,24")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--token", default="")
    ap.add_argument("--pid", type=int, default=0, help="서버 PID(CPU%%·RSS 측정용, psutil)")
    ap.add_argument("--video", default=str(_ROOT / "runs" / "rfdetr" / "multi_scene.mp4"))
    ap.add_argument("--cam-prefix", default="cap")
    ap.add_argument("--tag", default="")
    ap.add_argument("--warmup-s", type=float, default=15.0)
    ap.add_argument("--measure-s", type=float, default=45.0)
    ap.add_argument("--sample-interval-s", type=float, default=5.0)
    ap.add_argument("--out", default=str(_ROOT / "benchmarks" / "results" / "capacity_ramp.jsonl"))
    ap.add_argument("--cleanup", action="store_true", help="종료 후 등록한 테스트 카메라 전부 제거")
    args = ap.parse_args()

    steps = [int(s.strip()) for s in args.steps.split(",") if s.strip()]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[capacity_ramp] tag={args.tag} steps={steps} fps={args.fps} url={args.url} "
          f"psutil={_HAVE_PSUTIL} pid={args.pid or '(미지정 — proc 측정 생략)'}")

    registered: list[str] = []
    summaries = []
    with open(out_path, "a", encoding="utf-8") as out_f:
        out_f.write(json.dumps({"ts": _now(), "type": "run_start", "tag": args.tag,
                                "steps": steps, "fps": args.fps}, ensure_ascii=False) + "\n")
        try:
            for n in steps:
                s = run_step(args.url, args.token, args.pid, n, registered, args.cam_prefix,
                             args.video, args.fps, args.warmup_s, args.measure_s,
                             args.sample_interval_s, out_f)
                summaries.append(s)
        finally:
            out_f.write(json.dumps({"ts": _now(), "type": "run_end", "tag": args.tag},
                                    ensure_ascii=False) + "\n")
            if args.cleanup:
                print(f"[capacity_ramp] 정리 — 테스트 카메라 {len(registered)}대 제거")
                for cid in registered:
                    disable_delete_camera(args.url, args.token, cid)

    print("\n[capacity_ramp] 요약표")
    print(f"{'n':>4} {'GPU avg%':>9} {'proc_cpu%':>10} {'sys_cpu%':>9} {'p50ms':>8} {'p95ms':>8} "
          f"{'fail':>6}  bottleneck")
    for s in summaries:
        print(f"{s['n']:>4} {str(s['gpu_util_avg_pct']):>9} {str(s['proc_cpu_avg_pct']):>10} "
              f"{str(s['sys_cpu_avg_pct']):>9} {str(s['latency_p50_ms']):>8} "
              f"{str(s['latency_p95_ms']):>8} {s['n_fail']:>3}/{s['n_probes']:<3} {s['bottleneck']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
