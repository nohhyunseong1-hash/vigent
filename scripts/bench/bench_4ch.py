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


def assert_no_real_channels(app_root: Path) -> dict[str, Any]:
    """★통보 안전 확인 — 로컬 싱크 외의 채널이 하나라도 있으면 벤치를 시작하지 않는다.

    규칙 11: 확인이 필요하면 확인하는 **코드**를 만든다. 절차서에 적는 것으로는 부족하다.
    app_root: 서버가 읽는 config/notify.yaml 이 있는 뿌리(저장소면 _ROOT, 포터블이면 <패키지>\\app).
    """
    p = app_root / "config" / "notify.yaml"
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


# [I-2 검증 완료, 2026-09-23] H-3 때 만든 우회 샘플러(sample_server_proc.ps1)는 제거했다.
#   서버 프로세스 자원은 이제 scripts/pilot_load_test.py 의 proc_stats(포트 점유 PID → 서버
#   명령줄과 맞는 부모까지 트리 합산)가 잰다. 제거 근거 — 고친 도구 vs 샘플러 대조:
#   RSS +0.96% · 환산코어 +0.53%(8GB 상한 회차), 판정 기준 ±5% 이내.
#   상세: docs/deploy/bench_4ch_repeat_2026-09-23.md §4.


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


GPU_CONTENTION_MB = 500.0     # [승인 항목 5] 시작 전 다른 프로세스의 VRAM 합계가 이 이상이면 벤치를 시작하지 않는다


def parse_gpu_contention(mem_used_csv: str, apps_csv: str) -> tuple[float, list[str]]:
    """nvidia-smi 두 출력(총 사용 MiB, 프로세스 목록)에서 (사용 MB, 프로세스명 목록)을 뽑는다.

    ★왜 총 사용량인가: Windows(WDDM)에서는 `--query-compute-apps=used_memory` 가 프로세스별로 [N/A] 를 준다.
      벤치 서버를 띄우기 **전**에 재면 memory.used 전부가 '다른 프로세스' 몫이므로 합계로 충분하다.
    ★왜 필요한가: 2026-09-23 G-2 재확인·추론 분해 측정이 PUBG(TslGame.exe, GPU 67%·6.1GB) 실행 중에 이뤄져
      기동 67.9s(깨끗할 땐 10~14s)·ppe_fwd 23.8ms(깨끗할 땐 12.2ms) 로 **오염**됐다. 사람이 매번 기억할 수 없으니 코드가 막는다.
    """
    used = 0.0
    for ln in (mem_used_csv or "").splitlines():
        ln = ln.strip().replace("MiB", "").strip()
        if ln and ln.replace(".", "", 1).isdigit():
            used = max(used, float(ln))
    names: list[str] = []
    for ln in (apps_csv or "").splitlines():
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            nm = parts[1].rsplit("\\", 1)[-1]
            if nm and nm not in names:
                names.append(nm)
    return used, names


def assert_gpu_free(threshold_mb: float = GPU_CONTENTION_MB) -> dict[str, Any]:
    """서버 기동 전 GPU 가 비어 있는지. 아니면 프로세스명을 찍고 **시작하지 않는다**."""
    def _q(args: list[str]) -> str:
        try:
            return subprocess.run(["nvidia-smi", *args], capture_output=True, text=True, timeout=20).stdout
        except Exception as ex:  # noqa: BLE001  nvidia-smi 자체가 없으면 판정 불가 — 그것도 알린다
            return f"__ERR__ {type(ex).__name__}"
    mem = _q(["--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    apps = _q(["--query-compute-apps=pid,process_name", "--format=csv,noheader"])
    if mem.startswith("__ERR__"):
        raise SystemExit(f"중단: nvidia-smi 를 실행할 수 없다({mem}) — GPU 오염 여부를 판정할 수 없다")
    used, names = parse_gpu_contention(mem, apps)
    if used >= threshold_mb:
        raise SystemExit("중단: 다른 프로세스가 GPU 를 쓰고 있다 — 사용 중 VRAM "
                         f"{used:.0f} MB ≥ {threshold_mb:.0f} MB\n  프로세스: {', '.join(names) or '(목록 없음)'}"
                         "\n  게임·브라우저 GPU 가속 등을 닫고 다시 시작하라. 오염된 측정은 측정이 아니다.")
    return {"gpu_used_mb_before": used, "gpu_procs_before": names}


def port_free(port: int = 8010) -> bool:
    import socket
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def leftover_pilot_cams(app_root: Path) -> list[str]:
    """설정 파일에 남은 pilot* 카메라 — 다음 반복을 오염시키므로 0 이어야 한다."""
    import re
    hits: list[str] = []
    cfg = app_root / "config"
    if cfg.exists():
        for p in cfg.glob("*.yaml"):
            try:
                for m in re.findall(r"\bpilot\d+\b", p.read_text(encoding="utf-8")):
                    hits.append(f"{p.name}:{m}")
            except OSError:
                pass
    return sorted(set(hits))


def run_once(a: Any, run_idx: int, env: dict[str, str], app_root: Path, safety: dict[str, Any]) -> dict[str, Any]:
    """한 조건을 한 번 돈다. 반환 = meta(산출물 경로·기동 시간·행 수)."""
    stamp = time.strftime("%Y%m%d_%H%M")
    tag = f"{a.tag}_r{run_idx}" if a.repeat > 1 else a.tag
    audit = _ROOT / "audit"
    audit.mkdir(exist_ok=True)
    jsonl = audit / f"bench4ch_{tag}_{stamp}.jsonl"
    meta_path = audit / f"bench4ch_{tag}_{stamp}_meta.json"
    csv_path = audit / f"bench4ch_{tag}_{stamp}.csv"
    srv_log = audit / f"bench4ch_{tag}_{stamp}_server.log"

    if not port_free():
        raise SystemExit("중단: 8010 포트가 이미 점유돼 있다 — 이전 서버가 안 내려갔다")
    left = leftover_pilot_cams(app_root)
    if left:
        raise SystemExit(f"중단: 시작 전 pilot* 잔류 카메라가 있다 {left}")

    backend_note = env.get("VIGENT_DETECT_BACKEND") or "(설정 그대로)"
    print(f"=== [{run_idx}/{a.repeat}] 1. 서버 기동 (VIGENT_DETECT_BACKEND={backend_note}) ===")
    print(f"  python={a.server_python}\n  cwd={a.server_cwd}")
    t0 = time.time()
    logf = srv_log.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [a.server_python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8010"],
        cwd=str(a.server_cwd), env=env, stdout=logf, stderr=subprocess.STDOUT)
    warm: dict[str, Any] = {}
    fi: dict[str, Any] = {}
    lt_rc = None
    try:
        warm = wait_ready(proc, t0)
        print(f"  ready {warm['ready_s']}s (서버 보고 warmup_s={warm['warmup_s_reported']})")

        print(f"=== [{run_idx}/{a.repeat}] 2. 소크 {a.minutes}분 · 카메라 {a.cams}대 ===")
        lt = subprocess.Popen(
            [a.python, str(_ROOT / "scripts" / "pilot_load_test.py"),
             "--cams", str(a.cams), "--hours", str(round(a.minutes / 60.0, 4)),
             "--interval", str(a.interval), "--overload-cams", "0",
             "--jsonl", str(jsonl), "--tag", tag],
            cwd=str(_ROOT), env=env)
        fi = first_real_inference(t0)
        print(f"  첫 정상 추론: 기동 후 {fi['first_inference_s']}s (카메라 {fi['camera']})")
        lt.wait()
        lt_rc = lt.returncode
        print(f"  부하 도구 종료 exit={lt_rc}")
    finally:
        print(f"=== [{run_idx}/{a.repeat}] 3. 서버 종료 ===")
        proc.terminate()
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
        logf.close()
        # 자식(진짜 서버)이 남아 포트를 쥐고 있으면 다음 반복이 죽는다 — 확인하고 기다린다
        for _ in range(30):
            if port_free():
                break
            time.sleep(1)

    # ★백엔드는 태그·설정이 아니라 **서버 로그**로 확인한다(H-3 사고의 재발 방지).
    log_txt = srv_log.read_text(encoding="utf-8", errors="replace") if srv_log.exists() else ""
    backend_lines = [ln.strip() for ln in log_txt.splitlines() if "백엔드 사용" in ln]
    n = jsonl_to_csv(jsonl, csv_path) if jsonl.exists() else 0
    raw_csv = jsonl.with_name(jsonl.stem + "_raw.csv")
    raw_rows = (sum(1 for _ in raw_csv.open(encoding="utf-8-sig")) - 1) if raw_csv.exists() else 0
    left_after = leftover_pilot_cams(app_root)
    meta = {"tag": tag, "run_idx": run_idx, "repeat": a.repeat, "stamp": stamp, "minutes": a.minutes,
            "interval_s": a.interval, "cams": a.cams, "detect_backend_env": backend_note,
            "backend_from_log": backend_lines, "startup": warm, "first_inference": fi,
            "load_tool_exit": lt_rc, "jsonl": str(jsonl), "csv": str(csv_path), "csv_rows": n,
            "raw_csv": str(raw_csv), "raw_rows": raw_rows, "server_log": str(srv_log),
            "safety": safety, "server_python": a.server_python,
            "server_cwd": str(a.server_cwd), "app_root": str(app_root),
            "leftover_pilot_after": left_after,
            "note_disk_metric": ("pilot_load_test 의 disk(data/logs MB)는 저장소 _ROOT 기준이라 "
                                 "포터블 서버에는 해당 없음(미측정)" if app_root != _ROOT else "")}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ★규칙 11 — 결과물이 실제로 있는지 같은 실행 안에서 확인한다.
    ok = jsonl.exists() and jsonl.stat().st_size > 0 and n > 0 and raw_rows > 0
    print(f"=== [{run_idx}/{a.repeat}] 4. 산출물 ===")
    print(f"  JSONL {jsonl.name}: {'있음 ' + str(jsonl.stat().st_size) + 'B' if jsonl.exists() else '없음'}")
    print(f"  CSV   {csv_path.name}: {n}행 · 원시 {raw_csv.name}: {raw_rows}행")
    print(f"  백엔드(로그): {backend_lines[:3] if backend_lines else '★로그에 백엔드 줄이 없다'}")
    print(f"  meta  {meta_path.name}")
    if left_after:
        print(f"  ★pilot* 잔류: {left_after}")
    meta["ok"] = bool(ok and not left_after)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--minutes", type=float, default=35.0)
    ap.add_argument("--interval", type=float, default=300.0, help="집계 창(초). 기본 5분")
    ap.add_argument("--cams", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=1, help="같은 조건 반복 횟수(태그에 _r1.. 붙임)")
    ap.add_argument("--detect-backend", default="", help="비우면 설정 그대로. torch 면 PPE 도 GPU")
    ap.add_argument("--python", default=str(_ROOT / ".venv" / "Scripts" / "python.exe"),
                    help="부하 도구(pilot_load_test.py)를 돌릴 파이썬 — 저장소 .venv")
    # [I-3] 포터블 서버를 띄울 때: --pkg-root D:\vigent_portable_gpu2 하나면 나머지는 그 아래로 잡는다.
    ap.add_argument("--pkg-root", default="", help="포터블 패키지 뿌리(있으면 서버를 여기서 띄운다)")
    ap.add_argument("--server-python", default="", help="서버 파이썬(기본: pkg-root\\python\\python.exe 또는 .venv)")
    ap.add_argument("--server-cwd", default="", help="서버 cwd(기본: <app>\\vigent-core)")
    a = ap.parse_args()

    if a.pkg_root:
        pkg = Path(a.pkg_root)
        app_root = pkg / "app"
        a.server_python = a.server_python or str(pkg / "python" / "python.exe")
        a.server_cwd = Path(a.server_cwd or (app_root / "vigent-core"))
    else:
        app_root = _ROOT
        a.server_python = a.server_python or a.python
        a.server_cwd = Path(a.server_cwd or (_ROOT / "vigent-core"))
    for p in (Path(a.server_python), a.server_cwd / "main.py"):
        if not p.exists():
            raise SystemExit(f"중단: 없음 — {p}")

    print("=== 0. 통보 안전 확인 ===")
    safety = assert_no_real_channels(app_root)
    print(f"  채널: 웹훅={safety['webhook'] or '(없음)'} · 실채널 0개 · notify.yaml={app_root / 'config' / 'notify.yaml'}")
    print("=== 0b. GPU 오염 확인 (다른 프로세스 VRAM) ===")
    gpu_free = assert_gpu_free()          # [승인 항목 5] ≥500MB 면 여기서 멈춘다(프로세스명 출력)
    safety.update(gpu_free)
    print(f"  사용 중 VRAM {gpu_free['gpu_used_mb_before']:.0f} MB < {GPU_CONTENTION_MB:.0f} MB · "
          f"프로세스 {gpu_free['gpu_procs_before'] or '없음'}")

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["VIGENT_NOTIFY_SELFTEST"] = "0"          # 기동 시 외부 getMe 호출 금지
    if a.detect_backend:
        env["VIGENT_DETECT_BACKEND"] = a.detect_backend
    if a.pkg_root:
        # 런처(VIGENT_시작.bat)와 같은 환경 — 다르게 띄우면 다른 것을 재는 것이다
        pkg = Path(a.pkg_root)
        env["VIGENT_PORTABLE"] = "1"
        env["VIGENT_CAPTURE_MODE"] = "thread"
        env["VIGENT_LOG_DIR"] = str(pkg / "state" / "logs")
        env["VIGENT_ALLOW_PRETRAIN_DOWNLOAD"] = ""
        env["PYTHONNOUSERSITE"] = "1"
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        # 경보 지연은 **서버의** 큐 DB 로 잰다 — 저장소 DB 를 읽으면 엉뚱한 숫자다
        env["VIGENT_ALERT_DB"] = str(app_root / "data" / "alert_queue.db")

    results = []
    for i in range(1, a.repeat + 1):
        m = run_once(a, i, env, app_root, safety)
        results.append(m)
        if not m.get("ok"):
            print(f"실패: 반복 {i} 의 결과물이 비었거나 잔류가 있다. 여기서 멈춘다.")
            return 1
    if a.repeat > 1:
        summ = _ROOT / "audit" / f"bench4ch_{a.tag}_{time.strftime('%Y%m%d_%H%M')}_runs.json"
        summ.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"=== 반복 {a.repeat}회 완료 → {summ.name} ===")
    ok = all(r.get("ok") for r in results)
    if not ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
