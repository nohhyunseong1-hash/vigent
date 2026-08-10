#!/usr/bin/env python3
"""[S3] 엣지박스 리허설 24h 소크 — tools/soak_monitor.py 가 담지 않는 항목 보완.

soak_monitor.py는 프로세스 메모리·워커 프레임/hang/재연결·경보이력·크래시를 다룬다.
이 스크립트는 그 외 4가지를 추가로 기록한다:
  1. GPU 사용률·VRAM(nvidia-smi 폴링, --gpu-interval 초마다)
  2. 검출 지연 능동 프로브(/rfdetr/frame 에 소형 이미지, --probe-interval 초마다) — p50/p95는
     사후 집계 스크립트에서 이 로그로 계산한다(여기선 원시값만 기록).
  3. data/ 그룹별 디스크 크기 스냅샷(--disk-interval 초마다, 기본 4시간)
  4. retention dry-run 실행(디스크 스냅샷과 같은 주기) — 삭제 후보가 올바르게 잡히는지
     감사 로그(retention.py의 STATUS_PATH)로 사후 확인 가능하게 매번 새로 기록.

전부 소스 무수정·순수 관측(+ retention dry-run 자체는 원래도 부작용 없음, config 그대로).
출력: JSONL 1줄 = 이벤트 1건(type 필드로 구분) — 사후 집계는 별도 스크립트에서.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

KST = timezone(timedelta(hours=9))


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _append(log_path: Path, rec: dict) -> None:
    rec = {"ts": _now(), **rec}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def sample_gpu() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return None
        util_gpu, util_mem, mem_used, mem_total = [x.strip() for x in out.stdout.strip().split(",")]
        return {"util_gpu_pct": float(util_gpu), "util_mem_pct": float(util_mem),
                "vram_used_mb": float(mem_used), "vram_total_mb": float(mem_total)}
    except Exception as ex:  # noqa: BLE001  GPU 조회 실패해도 소크는 계속
        return {"error": f"{type(ex).__name__}: {ex}"}


def probe_detect_latency(base_url: str, token: str | None) -> dict:
    """1x1 검정 PNG로 /rfdetr/frame 왕복시간 측정(순수 오버헤드+추론, 실사용 근사는 아님 —
    현재 라이브 카메라 부하와 경합하는 상태의 지연이라 오히려 실사용에 더 가까움)."""
    png_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
               "42YAAAAASUVORK5CYII=")
    payload = json.dumps({"image": "data:image/png;base64," + png_b64}).encode()
    req = urllib.request.Request(f"{base_url}/rfdetr/frame", data=payload, method="POST",
                                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
            ok = resp.status == 200
    except Exception as ex:  # noqa: BLE001
        return {"latency_ms": None, "ok": False, "error": f"{type(ex).__name__}: {ex}"}
    return {"latency_ms": round((time.time() - t0) * 1000, 1), "ok": ok}


def disk_snapshot() -> dict:
    """data/ 하위 그룹별 크기(retention.py의 정의를 재사용해 일관성 유지) + 전체 data/ 크기."""
    try:
        import retention
        groups = {}
        for name, root in retention.GROUP_DIRS.items():
            if root.exists():
                total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                count = sum(1 for f in root.rglob("*") if f.is_file())
                groups[name] = {"bytes": total, "files": count}
            else:
                groups[name] = {"bytes": 0, "files": 0}
        data_dir = _ROOT / "data"
        data_total = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file()) if data_dir.exists() else 0
        return {"groups": groups, "data_total_bytes": data_total}
    except Exception as ex:  # noqa: BLE001
        return {"error": f"{type(ex).__name__}: {ex}"}


def run_retention_dry_run() -> dict:
    try:
        import retention
        result = retention.sweep()   # config(enabled=true,dry_run=true) 그대로 따름 — 삭제 없음
        cand_counts = {name: len(g.get("candidates", [])) for name, g in result.get("groups", {}).items()}
        return {"dry_run": result.get("dry_run"), "enabled": result.get("enabled"),
                "candidates_by_group": cand_counts, "warnings": result.get("warnings", [])}
    except Exception as ex:  # noqa: BLE001
        return {"error": f"{type(ex).__name__}: {ex}"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8020")
    ap.add_argument("--token", default="")
    ap.add_argument("--duration-hours", type=float, default=24.0)
    ap.add_argument("--gpu-interval", type=float, default=60.0, help="초")
    ap.add_argument("--probe-interval", type=float, default=300.0, help="초(기본 5분)")
    ap.add_argument("--disk-interval", type=float, default=4 * 3600.0, help="초(기본 4시간)")
    ap.add_argument("--out", default=str(_ROOT / "benchmarks" / "results" / "s3_soak_extra.jsonl"))
    args = ap.parse_args()

    log_path = Path(args.out)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    t_end = t_start + args.duration_hours * 3600
    next_gpu = t_start
    next_probe = t_start
    next_disk = t_start   # 시작 시점 스냅샷 포함

    _append(log_path, {"type": "start", "duration_hours": args.duration_hours,
                       "gpu_interval": args.gpu_interval, "probe_interval": args.probe_interval,
                       "disk_interval": args.disk_interval})

    while time.time() < t_end:
        now = time.time()
        if now >= next_gpu:
            g = sample_gpu()
            if g is not None:
                _append(log_path, {"type": "gpu", **g})
            next_gpu = now + args.gpu_interval
        if now >= next_probe:
            p = probe_detect_latency(args.url, args.token or None)
            _append(log_path, {"type": "latency_probe", **p})
            next_probe = now + args.probe_interval
        if now >= next_disk:
            d = disk_snapshot()
            _append(log_path, {"type": "disk_snapshot", "elapsed_hours": round((now - t_start) / 3600, 2), **d})
            r = run_retention_dry_run()
            _append(log_path, {"type": "retention_dry_run", **r})
            next_disk = now + args.disk_interval
        time.sleep(min(5.0, max(0.5, min(next_gpu, next_probe, next_disk) - time.time())))

    # 종료 스냅샷(정확히 duration 끝 시점 값 — 마지막 주기 스냅샷과 별개로 항상 기록)
    _append(log_path, {"type": "disk_snapshot", "elapsed_hours": round((time.time() - t_start) / 3600, 2),
                       "final": True, **disk_snapshot()})
    _append(log_path, {"type": "retention_dry_run", "final": True, **run_retention_dry_run()})
    _append(log_path, {"type": "end", "elapsed_hours": round((time.time() - t_start) / 3600, 2)})


if __name__ == "__main__":
    main()
