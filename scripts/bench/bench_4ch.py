#!/usr/bin/env python3
"""bench_4ch.py — 4채널 동시 구동 벤치 드라이버. [H-3]

무엇을 하는가 (한 번 실행 = 한 조건)
  1. 안전 확인: 통보 채널이 **로컬 싱크뿐**인지 검사한다. 아니면 **시작하지 않는다.**
  2. 서버를 띄우고 **기동 → ready(예열 완료) → 첫 정상 추론**까지 시간을 잰다.
  3. scripts/pilot_load_test.py 로 카메라 4대를 붙이고 --hours 동안 소크한다(기존 도구 재사용).
  4. JSONL 원시 결과를 CSV 로도 남긴다.
  5. 카메라를 정리하고 서버를 내린다.

★예열은 이미 서버에 있다(vigent-core/readiness.py — 더미 프레임 1회 추론 후 워커 기동,
  그 전에는 /health 가 phase=starting 과 503 을 낸다). 이 스크립트는 **재지 않고 만들지도 않는다** —
  이미 있는 것을 **측정만** 한다.

사용:
    python scripts/bench/bench_4ch.py --tag ppe_cpu  --minutes 35
    python scripts/bench/bench_4ch.py --tag ppe_gpu  --minutes 35 --detect-backend torch

★첫 창(예열 직후)은 판정에서 빼되 원시 결과에는 남긴다 — 지시사항.
  판정 제외는 리포트 단계에서 하고, JSONL/CSV 에는 전부 들어간다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
BASE = os.environ.get("VIGENT_BASE_URL", "http://127.0.0.1:8010")
SINK_PORT = 9911

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _get(path: str, timeout: float = 10) -> tuple[int, Any]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception:  # noqa: BLE001
        return 0, None


def assert_no_real_channels() -> dict[str, Any]:
    """★통보 안전 확인 — 로컬 싱크 외의 채널이 하나라도 있으면 벤치를 시작하지 않는다.

    규칙 11: 확인이 필요하면 확인하는 **코드**를 만든다. 절차서에 적는 것으로는 부족하다.
    """
    p = _ROOT / "config" / "notify.yaml"
    cfg: dict[str, Any] = {}
    if p.exists():
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    bad = []
    for k in ("telegram_token", "telegram_chat", "smtp_host", "smtp_user", "email_to"):
        if str(cfg.get(k) or "").strip():
            bad.append(k)
    hook = str(cfg.get("webhook_url") or "").strip()
    if hook and not hook.startswith(("http://127.0.0.1", "http://localhost")):
        bad.append(f"webhook_url={hook}")
    if bad:
        raise SystemExit(
            "중단: 실제 통보 채널이 설정돼 있다 -> " + ", ".join(bad) +
            "\n  벤치 경보가 밖으로 나간다. scripts/bench/bench_4ch.ps1 의 notify 교체 단계를 확인하라.")
    if not hook:
        print("경고: 웹훅도 없다 -> 경보가 큐에 안 들어가 '경보 p95' 는 미측정으로 남는다")
    return {"webhook": hook, "real_channels": []}


def wait_ready(proc: subprocess.Popen, t0: float, timeout: float = 900) -> dict[str, Any]:
    """기동 → phase=ready 까지. 그 사이 상태 전이를 기록한다."""
    seen: list[dict[str, Any]] = []
    first_response = None
    while time.time() - t0 < timeout:
        if proc.poll() is not None:
            raise SystemExit(f"중단: 서버가 죽었다(exit {proc.returncode})")
        code, body = _get("/health", timeout=5)
        if code and first_response is None:
            first_response = round(time.time() - t0, 2)
        ph = (body or {}).get("phase")
        if ph and (not seen or seen[-1]["phase"] != ph):
            seen.append({"phase": ph, "t": round(time.time() - t0, 2), "http": code})
            print(f"  [{time.time() - t0:6.1f}s] phase={ph} http={code}")
        if ph == "ready":
            warm = (body or {}).get("warmup") or {}
            return {"ready_s": round(time.time() - t0, 2), "first_http_s": first_response,
                    "warmup_s_reported": warm.get("warmup_s"), "transitions": seen}
        time.sleep(1.0)
    raise SystemExit("중단: 예열이 timeout 안에 안 끝났다")


def first_real_inference(t0: float, timeout: float = 300) -> dict[str, Any]:
    """카메라가 붙은 뒤 **실제 프레임** 검출이 처음 성사된 시점(기동 기준 경과초)."""
    while time.time() - t0 < timeout:
        _c, body = _get("/health", timeout=5)
        cams = ((body or {}).get("cameras") or {})
        for cid, v in cams.items():
            age = v.get("last_detect_age_s")
            if isinstance(age, (int, float)) and age >= 0 and v.get("status") == "ok":
                return {"first_inference_s": round(time.time() - t0, 2), "camera": cid}
        time.sleep(1.0)
    return {"first_inference_s": None, "camera": None}


def start_proc_sampler(pid: int, out_csv: Path, minutes: float) -> subprocess.Popen | None:
    """서버 프로세스 자원 샘플러(별도 PowerShell 프로세스)를 띄운다.

    ★왜 따로 재는가 (실측): scripts/pilot_load_test.py 의 proc_stats 가 이 환경에서
      RSS 5.0MB · cpu_s 0.0156 을 **상수로** 뱉는다. 원인을 확인했다 —
      `*uvicorn*main:app*` 에 python.exe 가 **두 개** 걸리는데(스텁 5MB / 진짜 서버 3,175MB)
      find_server_pid() 가 `-First 1` 로 **스텁**을 고른다. 그 스크립트는 이번 범위가
      아니라 고치지 않고, 우리가 spawn 한 PID 를 우리가 잰다.
    ★psutil 은 이 저장소 .venv 에 **없다**(2026-09-23 확인). 그래서 PowerShell 로 잰다 —
      파이썬 의존성을 늘리지 않는다.
    """
    ps1 = _ROOT / "scripts" / "bench" / "sample_server_proc.ps1"
    if not ps1.exists():
        print(f"  경고: 샘플러 없음({ps1.name}) — 서버 프로세스 자원은 미측정")
        return None
    # ★-Pid0 를 주지 않는다. `python -m uvicorn` 으로 띄우면 우리가 Popen 한 PID 는
    #   RSS 5MB 짜리 **스텁**이고 진짜 서버는 그 자식이다(2026-09-23 실측: 스텁 15348 /
    #   진짜 42448 RSS 3.3GB). 우리가 spawn 한 PID 를 그대로 재면 pilot_load_test 와
    #   똑같은 실수를 반복한다 — 샘플러가 **RSS 최대** 후보를 고르게 둔다.
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
         "-Out", str(out_csv), "-Minutes", str(round(minutes + 3, 2)), "-PeriodSec", "15"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def jsonl_to_csv(jsonl: Path, csv_path: Path) -> int:
    """소크 JSONL → 평평한 CSV. 카메라별 값은 열로 편다."""
    rows: list[dict[str, Any]] = []
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        # ★pilot_load_test.py 의 실제 스키마: 구분 키는 'phase'(kind 아님)이고 지표는
        #   최상위 + gpu/proc/alerts_window/health 하위에 나뉘어 있다.
        #   (처음 'kind' 로 짰다가 CSV 0행이 나와 실제 파일을 보고 맞췄다)
        if r.get("phase") not in ("soak", "overload"):
            continue
        h = r.get("health") or {}
        a = r.get("alerts_window") or {}
        g = r.get("gpu") or {}
        pr = r.get("proc") or {}
        base = {
            "phase": r.get("phase"), "ts": r.get("ts"), "elapsed_s": r.get("elapsed_s"),
            "n_cams": r.get("n_cams"), "sys_cpu_pct": r.get("sys_cpu_pct"),
            "cpu_perf_pct": r.get("cpu_perf_pct"), "cpu_temp_c": r.get("cpu_temp_c"),
            "gpu_util": g.get("util"), "vram_used_mb": g.get("mem_used_mb"),
            "vram_total_mb": g.get("mem_total_mb"), "gpu_temp_c": g.get("temp_c"),
            "gpu_clock_sm": g.get("clock_sm"), "gpu_power_w": g.get("power_w"),
            "proc_rss_mb": pr.get("rss_mb"), "proc_cpu_s": pr.get("cpu_s"),
            "sys_avail_mb": pr.get("sys_avail_mb"), "logical_cpus": pr.get("logical_cpus"),
            "degraded_cam": h.get("degraded_camera_samples"),
            "degraded_alert": h.get("degraded_alert_samples"),
            "alerts_created": a.get("created"), "alerts_sent": a.get("sent"),
            "alerts_latency_p50": a.get("latency_p50"), "alerts_latency_p95": a.get("latency_p95"),
            "alerts_latency_max": a.get("latency_max"),
        }
        cams = h.get("cams")
        if isinstance(cams, dict):
            for cid, c in cams.items():
                base[f"{cid}.age_p50"] = c.get("age_p50")
                base[f"{cid}.age_p95"] = c.get("age_p95")
                base[f"{cid}.age_ok_ratio"] = c.get("age_ok_ratio")
                base[f"{cid}.detect_ms_p95"] = c.get("detect_ms_p95")
                base[f"{cid}.dropped"] = c.get("dropped")
        rows.append(base)
    if not rows:
        return 0
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--minutes", type=float, default=35.0)
    ap.add_argument("--interval", type=float, default=300.0, help="집계 창(초). 기본 5분")
    ap.add_argument("--cams", type=int, default=4)
    ap.add_argument("--detect-backend", default="", help="비우면 설정 그대로. torch 면 PPE 도 GPU")
    ap.add_argument("--python", default=str(_ROOT / ".venv" / "Scripts" / "python.exe"))
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M")
    audit = _ROOT / "audit"
    audit.mkdir(exist_ok=True)
    jsonl = audit / f"bench4ch_{a.tag}_{stamp}.jsonl"
    meta_path = audit / f"bench4ch_{a.tag}_{stamp}_meta.json"
    csv_path = audit / f"bench4ch_{a.tag}_{stamp}.csv"
    srv_log = audit / f"bench4ch_{a.tag}_{stamp}_server.log"

    print("=== 0. 통보 안전 확인 ===")
    safety = assert_no_real_channels()
    print(f"  채널: 웹훅={safety['webhook'] or '(없음)'} · 실채널 0개")

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["VIGENT_NOTIFY_SELFTEST"] = "0"          # 기동 시 외부 getMe 호출 금지
    if a.detect_backend:
        env["VIGENT_DETECT_BACKEND"] = a.detect_backend
    backend_note = a.detect_backend or "(설정 그대로)"
    print(f"=== 1. 서버 기동 (VIGENT_DETECT_BACKEND={backend_note}) ===")

    t0 = time.time()
    logf = srv_log.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [a.python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8010"],
        cwd=str(_ROOT / "vigent-core"), env=env, stdout=logf, stderr=subprocess.STDOUT)
    proc_csv = audit / f"bench4ch_{a.tag}_{stamp}_serverproc.csv"
    sampler = start_proc_sampler(proc.pid, proc_csv, a.minutes)
    try:
        warm = wait_ready(proc, t0)
        print(f"  ready {warm['ready_s']}s (서버 보고 warmup_s={warm['warmup_s_reported']})")

        print(f"=== 2. 소크 {a.minutes}분 · 카메라 {a.cams}대 ===")
        lt = subprocess.Popen(
            [a.python, str(_ROOT / "scripts" / "pilot_load_test.py"),
             "--cams", str(a.cams), "--hours", str(round(a.minutes / 60.0, 4)),
             "--interval", str(a.interval), "--overload-cams", "0",
             "--jsonl", str(jsonl), "--tag", a.tag],
            cwd=str(_ROOT), env=env)
        fi = first_real_inference(t0)
        print(f"  첫 정상 추론: 기동 후 {fi['first_inference_s']}s (카메라 {fi['camera']})")
        lt.wait()
        print(f"  부하 도구 종료 exit={lt.returncode}")
    finally:
        print("=== 3. 서버 종료 ===")
        if sampler is not None:
            sampler.terminate()
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        logf.close()

    n = jsonl_to_csv(jsonl, csv_path) if jsonl.exists() else 0
    meta = {"tag": a.tag, "stamp": stamp, "minutes": a.minutes, "interval_s": a.interval,
            "cams": a.cams, "detect_backend": backend_note, "startup": warm,
            "first_inference": fi, "jsonl": str(jsonl), "csv": str(csv_path),
            "csv_rows": n, "server_log": str(srv_log), "safety": safety,
            "server_proc_csv": str(proc_csv), "server_pid": proc.pid}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ★규칙 11 — 결과물이 실제로 있는지 같은 실행 안에서 확인한다.
    ok = jsonl.exists() and jsonl.stat().st_size > 0 and n > 0
    print("=== 4. 산출물 ===")
    print(f"  JSONL {jsonl.name}: {'있음 ' + str(jsonl.stat().st_size) + 'B' if jsonl.exists() else '없음'}")
    print(f"  CSV   {csv_path.name}: {n}행")
    print(f"  meta  {meta_path.name}")
    if not ok:
        print("실패: 소크 결과가 비었다. 0건 처리는 성공이 아니다.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
