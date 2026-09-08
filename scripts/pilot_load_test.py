#!/usr/bin/env python3
"""scripts/pilot_load_test.py — 파일럿(카메라 4대 + 노트북 1대) 사양 판정용 실측 키트. [2026-09-08]

★대상 기계에서 돌린다(현장 노트북 i7-10750H / GTX 1650 Ti). 다른 기계의 결과는 판정에 쓰지 않는다.
★합격 기준은 이 파일 머리(PASS)에 **측정 전에** 선언돼 있고 결과 파일에도 그대로 복사된다 — 사후 조정 금지(규칙 7).

한 번의 실행이 아래를 순서대로 한다(각 단계는 --phase 로 따로도 돌릴 수 있다):
  preflight  서버 /health · 기존 카메라 · 유령 카메라(등록에 없는데 /health 에 남은 것, age 비정상) 검사 → 있으면 중단
  ramp       모의(또는 실) 카메라 N대 등록(enabled=true) → /health 에서 running 대수를 세어 N 과 같아야 진행(규칙 11)
  soak       --hours 동안 --interval 초마다 샘플: CPU(시스템·서버 프로세스) · CPU 클럭 성능%(스로틀링) · 온도(있으면) ·
             GPU util/VRAM/온도/클럭 · RSS · 카메라별 검출 age/지연/드롭/재연결 · degraded 사유(카메라/경보 분리) ·
             경보 큐 지연(created→sent) · data/·logs/ 크기(저장 용량 산정) · 네트워크 바이트(실카메라일 때 의미)
  overload   카메라를 --overload-cams 만큼 더 붙여 --overload-min 분씩 유지하며 같은 샘플 → 무슨 일이 벌어지는지 기록
  cleanup    이 키트가 등록한 카메라 전부 제거 → /health 대수가 시작 전과 같은지 확인
  report     JSONL → 마크다운 표 + 기준별 통과/미달(무효 사유가 있으면 지우지 않고 남긴다)

사용(노트북, 관리자 아님·서비스는 떠 있어야 한다):
    python scripts\\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20
    python scripts\\pilot_load_test.py --cams 4 --rtsp-list cams.txt ...      # 실카메라(한 줄에 rtsp:// 1개, 자격증명 포함 — 출력에는 마스킹)
    python scripts\\pilot_load_test.py --record ...                          # 녹화(field_recorder original+overlay) 부하 포함
    python scripts\\pilot_load_test.py --phase cleanup                       # 중단됐을 때 정리만
    python scripts\\pilot_load_test.py --phase report --jsonl audit\\loadtest_<시각>.jsonl
★부하는 실제 파이프라인이다: 모의 영상(사고 장면)이 진짜 경보·증거 JPEG·인식 로그를 data/ 에 만들고, 통보 채널이 살아 있으면
  텔레그램으로 실제 발송된다(alert_notify 시간당 상한 6건·반복 억제 300s). 개발 PC 드라이런(2026-09-08, 12분): 경보 행 26·증거 175장·인식 297행.
  → 노트북에서는 파일럿 개통 전에 돌리고, 통보는 시험용 채팅으로 돌리거나 발송 건수를 감수한다. 잔재는 retention(30일)이 지운다 — 손으로 지우지 않는다.
모의 카메라 = VIGENT_DATA_DIR/runs/rfdetr/accident/*.mp4 (실제 현장 장면 파일, EOF 에서 자동 재오픈 = 루프).
  ★실카메라와 다른 점: 네트워크 지연·패킷 손실·재접속·RTSP 디코드(h264 실스트림)가 없다 → 6단계(네트워크)는 실카메라로만 유효.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)   # 로그 리다이렉트 시에도 줄 단위로 즉시 기록
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402

BASE = os.environ.get("VIGENT_BASE_URL", "http://127.0.0.1:8010")
PREFIX = "pilot"                       # 이 키트가 등록하는 카메라 id 접두 — cleanup 은 이 접두만 지운다

# ── 1단계: 합격 기준(★측정 전 선언, 2026-09-08 대표 지시 기준으로 못박음) ────────────────────────
PASS: dict[str, Any] = {
    "declared_at": "2026-09-08",
    "detect_cycle": {"target_fps": 2.0, "tolerance_pct": 10,
                     "rule": "10분 창마다 카메라별 last_detect_age_s p95 ≤ 1.0s (2fps 주기 0.5s의 2배 이내) 이고 "
                             "샘플 중 age ≤ 0.55s 비율 ≥ 90% (허용 편차 10%)"},
    "alert_latency_s": {"queue_to_sent_p95_max": 5.0, "event_to_queue_max": 1.0,
                        "rule": "경보 큐 적재(created_at) → 텔레그램 전송 완료(sent_at) p95 ≤ 5s. 침입 프레임 → 적재는 검출 주기 "
                                "0.5s + 판정 이내(≤ 1s) → 합계 ≤ 6s. 채널 미설정이면 '미측정'으로 남긴다"},
    "cpu": {"system_avg_max_pct": 70.0, "server_cores_max": 8.0,
            "rule": "10분 창 평균 시스템 CPU ≤ 70% (12스레드의 30% 여유), 서버 프로세스 ≤ 8.0 환산코어"},
    "memory": {"server_rss_max_gb": 6.0, "system_available_min_gb": 2.0, "leak_max_mb_per_h": 100.0,
               "rule": "서버 RSS ≤ 6GB · 시스템 가용 ≥ 2GB · 소크 동안 RSS 기울기 ≤ 100MB/h(누수)"},
    "degraded": {"camera_cause_max": 0, "rule": "카메라 사유 degraded 샘플 0건. 경보 적체 사유는 따로 세고 판정에서 뺀다(채널 문제)"},
    "frame_loss": {"dropped_pct_max": 1.0, "reconnects_file_max": 0,
                   "rule": "창마다 카메라별 dropped_frames 증가 ≤ 창 내 예상 프레임(2fps×600s=1,200)의 1%. 파일 카메라 재연결 0"},
    "thermal": {"cpu_perf_floor_pct_of_initial": 80.0, "gpu_clock_floor_pct_of_initial": 80.0, "gpu_temp_max_c": 87,
                "rule": "3시간 이후 창의 CPU '% Processor Performance' 와 GPU SM 클럭이 첫 30분 평균의 80% 이상. GPU 온도 < 87°C"},
    "gpu_vram": {"used_max_gb": 3.5, "rule": "VRAM 사용 ≤ 3.5GB(4GB 의 87%)"},
    "overload": {"rule": "판정 항목 아님 — 5·6대에서 무엇이 벌어지는지 기록: 드롭/밀림/사망, 경보 지연 증가폭, degraded 표시 여부"},
}


# ── 공용 ────────────────────────────────────────────────────────────────────────────────────
def _token() -> str:
    t = os.environ.get("VIGENT_API_TOKEN", "").strip()
    if t:
        return t
    env = _ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("VIGENT_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


TOK = _token()


def api(path: str, method: str = "GET", body: dict | None = None, timeout: float = 30) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as ex:  # noqa: BLE001
        return 0, {"error": str(ex)}


def mask(s: str) -> str:
    return re.sub(r"(\w+://)([^/@\s]+)@", r"\1***:***@", s)


def _p(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def _run(cmd: list[str], timeout: float = 60) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


# ── 시스템 지표(Windows, 외부 패키지 없이) ──────────────────────────────────────────────────────
def gpu() -> dict[str, Any]:
    out = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,clocks.sm,clocks.max.sm,power.draw",
                "--format=csv,noheader,nounits"])
    if not out.strip():
        return {}
    try:
        u, mu, mt, t, cs, cm, pw = (x.strip() for x in out.splitlines()[0].split(","))
        return {"util": float(u), "mem_used_mb": float(mu), "mem_total_mb": float(mt), "temp_c": float(t),
                "clock_sm": float(cs), "clock_sm_max": float(cm), "power_w": float(pw) if pw not in ("[N/A]", "") else None}
    except Exception:  # noqa: BLE001
        return {}


def typeperf(counter: str, samples: int = 3, interval: int = 1) -> float | None:
    """카운터 평균(samples 회). 없으면 None(미측정)."""
    out = _run(["typeperf", counter, "-sc", str(samples), "-si", str(interval)], timeout=samples * interval + 15)
    vals: list[float] = []
    for line in out.splitlines():
        if line.startswith('"') and "PDH" not in line:
            parts = [p.strip('"') for p in line.split('","')]
            try:
                vals.append(float(parts[-1].strip('"')))
            except Exception:  # noqa: BLE001
                pass
    return round(sum(vals) / len(vals), 2) if vals else None


def thermal_zone_c() -> float | None:
    out = _run(["typeperf", r"\Thermal Zone Information(*)\Temperature", "-sc", "1"], timeout=20)
    vals: list[float] = []
    for line in out.splitlines():
        if line.startswith('"') and "PDH" not in line:
            for p in line.split('","')[1:]:
                try:
                    k = float(p.strip('"'))
                    if k > 200:                      # Kelvin
                        vals.append(k - 273.15)
                except Exception:  # noqa: BLE001
                    pass
    return round(max(vals), 1) if vals else None


def find_server_pid() -> int | None:
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*service_entry.py*' "
          "-or $_.CommandLine -like '*uvicorn*main:app*' } | Select-Object -First 1 -ExpandProperty ProcessId")
    out = _run(["powershell", "-NoProfile", "-Command", ps]).strip()
    return int(out) if out.isdigit() else None


def proc_stats(pid: int) -> dict[str, Any]:
    """서버 프로세스 CPU 누적시간(s)·RSS(MB)·시스템 가용 메모리(MB). CPU% 는 두 샘플의 차로 계산한다."""
    ps = (f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; $os = Get-CimInstance Win32_OperatingSystem; "
          "if ($p) { '' + $p.TotalProcessorTime.TotalSeconds + ',' + [math]::Round($p.WorkingSet64/1MB) + ',' + "
          "[math]::Round($os.FreePhysicalMemory/1024) + ',' + [math]::Round($os.TotalVisibleMemorySize/1024) + ',' + "
          "(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors } else { 'dead' }")
    out = _run(["powershell", "-NoProfile", "-Command", ps]).strip()
    if out.startswith("dead") or not out:
        return {"alive": False}
    c, r, fm, tm, n = out.split(",")
    return {"alive": True, "cpu_s": float(c), "rss_mb": float(r), "sys_avail_mb": float(fm), "sys_total_mb": float(tm),
            "logical_cpus": int(n)}


def net_bytes() -> int | None:
    out = _run(["powershell", "-NoProfile", "-Command",
                "(Get-NetAdapterStatistics | Measure-Object -Sum ReceivedBytes).Sum"]).strip()
    return int(float(out)) if out else None


def dir_size(p: Path) -> int:
    total = 0
    for root, _d, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def alert_stats(since_ts: float) -> dict[str, Any]:
    """alert_queue.db — since 이후 생성 행의 큐→전송 지연(created_at→sent_at)과 상태 분포."""
    db = Path(os.environ.get("VIGENT_ALERT_DB") or (_ROOT / "data" / "alert_queue.db"))
    if not db.exists():
        return {"db": "없음"}
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = c.execute("select created_at, sent_at, status, level from alerts where created_at >= ?", (since_ts,)).fetchall()
        c.close()
    except Exception as ex:  # noqa: BLE001
        return {"db": f"읽기 실패 {type(ex).__name__}"}
    lat = [float(s) - float(cr) for cr, s, st, _l in rows if s]
    st_count: dict[str, int] = {}
    for _cr, _s, st, _l in rows:
        st_count[str(st)] = st_count.get(str(st), 0) + 1
    return {"created": len(rows), "sent": len(lat), "status": st_count,
            "latency_p50": round(_p(lat, 0.5), 2) if lat else None, "latency_p95": round(_p(lat, 0.95), 2) if lat else None,
            "latency_max": round(max(lat), 2) if lat else None}


# ── 카메라 ──────────────────────────────────────────────────────────────────────────────────
def scenes() -> list[Path]:
    d = media("runs/rfdetr/accident")
    return sorted(p for p in Path(d).glob("*.mp4")) if Path(d).exists() else []


def health() -> dict:
    _c, h = api("/health")
    return h if isinstance(h, dict) else {}


def cams_running(h: dict) -> dict[str, dict]:
    return {k: v for k, v in (h.get("cameras") or {}).items() if isinstance(v, dict)}


def preflight(exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    h = health()
    if not h:
        raise SystemExit(f"[중단] 서버 응답 없음: {BASE}/health — 서비스가 떠 있어야 한다")
    _c, reg = api("/cameras")
    reg_ids = {c.get("id") for c in (reg.get("cameras") if isinstance(reg, dict) else reg or []) if isinstance(c, dict)}
    live = cams_running(h)
    ghosts = [k for k in live if k not in reg_ids]
    stale = {k: v.get("last_detect_age_s") for k, v in live.items()
             if k not in exclude and (v.get("status") not in ("ok", "starting") or ((v.get("last_detect_age_s") or 0) > 60))}
    excluded_state = {k: (live.get(k) or {}).get("status") for k in exclude if k in live}   # 제외 카메라도 상태는 기록(집계에는 안 넣는다)
    info = {"status": h.get("status"), "phase": h.get("phase"), "registered": sorted(x for x in reg_ids if x),
            "live": sorted(live), "ghosts": ghosts, "stale": stale, "excluded": excluded_state,
            "alerts": h.get("alerts"), "warnings": h.get("warnings")}
    print("[preflight]", json.dumps(info, ensure_ascii=False))
    if ghosts:
        raise SystemExit(f"[중단] 유령 카메라(/health 에만 있음): {ghosts} — 기준값 오염. 서버 재기동 후 재실행")
    if stale:
        raise SystemExit(f"[중단] age 비정상·비정상 상태 카메라: {stale} — 정지 카메라를 집계에 넣지 않는다. 정리 후 재실행")
    if h.get("phase") not in ("ready", None):
        raise SystemExit(f"[중단] phase={h.get('phase')} — 예열 완료 후 실행")
    return info


def add_cams(n: int, start: int, sources: list[str], fps: float) -> list[str]:
    ids: list[str] = []
    for i in range(start, start + n):
        cid = f"{PREFIX}{i:02d}"
        src = sources[(i - 1) % len(sources)]
        code, r = api("/cameras", "POST", {"id": cid, "name": f"파일럿모의{i}", "source": src, "fps": fps, "enabled": True})
        print(f"  등록 {cid} ← {mask(src)} → HTTP {code} {str(r)[:80]}")
        if code not in (200, 201):
            raise SystemExit(f"[중단] 카메라 등록 실패 {cid}: {code} {r}")
        ids.append(cid)
    return ids


def wait_running(ids: list[str], timeout: float = 120) -> int:
    t0 = time.time()
    while time.time() - t0 < timeout:
        live = cams_running(health())
        n = sum(1 for k in ids if k in live)
        if n == len(ids):
            print(f"  /health running: {n}/{len(ids)} (규칙 11 확인)")
            return n
        time.sleep(3)
    live = cams_running(health())
    n = sum(1 for k in ids if k in live)
    print(f"  ★/health running: {n}/{len(ids)} — 기대와 다르다")
    return n


def cleanup() -> dict[str, Any]:
    _c, reg = api("/cameras")
    items = reg.get("cameras") if isinstance(reg, dict) else reg or []
    removed = []
    for c in items or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if cid and cid.startswith(PREFIX):
            code, _ = api(f"/cameras/{cid}", "DELETE")
            removed.append((cid, code))
    time.sleep(3)
    live = cams_running(health())
    left = [k for k in live if k.startswith(PREFIX)]
    print(f"[cleanup] 제거 {len(removed)}개 {removed} · /health 에 남은 {PREFIX}*: {left}")
    return {"removed": removed, "left_in_health": left}


# ── 샘플러 ──────────────────────────────────────────────────────────────────────────────────
class Sampler:
    def __init__(self, ids: list[str], pid: int | None, jsonl: Path, expect_fps: float):
        self.ids, self.pid, self.jsonl, self.fps = ids, pid, jsonl, expect_fps
        self.prev: dict[str, Any] = {}
        self.t_start = time.time()
        self.net0 = net_bytes()

    def write(self, rec: dict) -> None:
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def health_burst(self, seconds: float = 30.0, every: float = 2.0) -> dict[str, Any]:
        """짧은 폭주 샘플로 카메라별 age 분포(검출 주기 유지 여부)를 본다."""
        ages: dict[str, list[float]] = {k: [] for k in self.ids}
        lat: dict[str, list[float]] = {k: [] for k in self.ids}
        st_bad: dict[str, int] = {k: 0 for k in self.ids}
        overall: list[str] = []
        alert_bad = 0
        t0 = time.time()
        last: dict = {}
        while time.time() - t0 < seconds:
            h = health()
            last = h
            overall.append(str(h.get("status")))
            al = h.get("alerts") or {}
            if int(al.get("pending") or 0) > 0 or int(al.get("dead_1h") or 0) > 0:
                alert_bad += 1
            live = cams_running(h)
            for k in self.ids:
                v = live.get(k)
                if not v:
                    st_bad[k] += 1
                    continue
                if v.get("status") != "ok":
                    st_bad[k] += 1
                a = v.get("last_detect_age_s")
                if a is not None:
                    ages[k].append(float(a))
                lm = v.get("last_detect_latency_ms")
                if lm is not None:
                    lat[k].append(float(lm))
            time.sleep(every)
        per: dict[str, Any] = {}
        thr = 0.55 if self.fps >= 2 else (1.0 / self.fps) * 1.1
        for k in self.ids:
            a = ages[k]
            per[k] = {"age_p50": round(_p(a, 0.5), 3) if a else None, "age_p95": round(_p(a, 0.95), 3) if a else None,
                      "age_ok_ratio": round(sum(1 for x in a if x <= thr) / len(a), 3) if a else None,
                      "detect_ms_p95": round(_p(lat[k], 0.95), 1) if lat[k] else None, "bad_status_samples": st_bad[k],
                      "dropped": (live.get(k) or {}).get("dropped_frames") if (live := cams_running(last)) else None,
                      "reconnects": (live.get(k) or {}).get("reconnects"), "hangs": (live.get(k) or {}).get("hangs")}
        cam_bad = sum(1 for k in self.ids if st_bad[k] > 0)
        return {"overall": overall, "alert_pending_max": int((last.get("alerts") or {}).get("pending") or 0),
                "degraded_samples": sum(1 for s in overall if s not in ("healthy",)),
                "degraded_alert_samples": alert_bad, "degraded_camera_samples": cam_bad, "cams": per,
                "slot_degraded": last.get("slot_degraded"), "alerts": last.get("alerts")}

    def sample(self, phase: str, n_cams: int) -> dict[str, Any]:
        t = time.time()
        rec: dict[str, Any] = {"ts": _dt.datetime.now().isoformat(timespec="seconds"), "elapsed_s": round(t - self.t_start),
                               "phase": phase, "n_cams": n_cams}
        rec["sys_cpu_pct"] = typeperf(r"\Processor(_Total)\% Processor Time", samples=5, interval=1)
        rec["cpu_perf_pct"] = typeperf(r"\Processor Information(_Total)\% Processor Performance", samples=3, interval=1)
        rec["cpu_temp_c"] = thermal_zone_c()
        rec["gpu"] = gpu()
        ps = proc_stats(self.pid) if self.pid else {"alive": None}
        if ps.get("alive") and self.prev.get("cpu_s") is not None:
            dt = t - self.prev["t"]
            ps["server_cores"] = round((ps["cpu_s"] - self.prev["cpu_s"]) / dt, 2) if dt > 0 else None
        rec["proc"] = ps
        rec["health"] = self.health_burst()
        rec["alerts_window"] = alert_stats(self.prev.get("t", self.t_start))
        rec["disk"] = {"data_mb": round(dir_size(_ROOT / "data") / 1048576, 1), "logs_mb": round(dir_size(_ROOT / "logs") / 1048576, 1)}
        nb = net_bytes()
        if nb is not None and self.prev.get("net") is not None and t - self.prev["t"] > 0:
            rec["net_rx_mbps"] = round((nb - self.prev["net"]) * 8 / (t - self.prev["t"]) / 1e6, 2)
        self.prev = {"t": t, "cpu_s": ps.get("cpu_s"), "net": nb}
        self.write(rec)
        h = rec["health"]
        print(f"[{rec['ts']}] {phase} n={n_cams} sysCPU={rec['sys_cpu_pct']}% perf={rec['cpu_perf_pct']}% "
              f"srv={ps.get('server_cores')}코어 RSS={ps.get('rss_mb')}MB GPU={rec['gpu'].get('util')}%/"
              f"{rec['gpu'].get('mem_used_mb')}MB {rec['gpu'].get('temp_c')}°C clk={rec['gpu'].get('clock_sm')} "
              f"deg(cam/alert)={h['degraded_camera_samples']}/{h['degraded_alert_samples']} "
              f"age_p95={[c['age_p95'] for c in h['cams'].values()]} alerts={rec['alerts_window'].get('created')}/"
              f"{rec['alerts_window'].get('latency_p95')}s")
        return rec


# ── 보고서 ──────────────────────────────────────────────────────────────────────────────────
def report(jsonl: Path, out_md: Path) -> int:
    lines = [json.loads(x) for x in jsonl.read_text(encoding="utf-8").splitlines() if x.strip()]
    hdr = next((x for x in lines if x.get("type") == "header"), {})
    samples = [x for x in lines if "health" in x]
    invalid = [x for x in lines if x.get("type") == "invalid"]
    soak = [s for s in samples if s["phase"] == "soak"]
    over = [s for s in samples if s["phase"].startswith("overload")]
    P = hdr.get("pass_criteria") or PASS
    fails: list[str] = []
    notes: list[str] = []

    def col(key, f=lambda s: s):
        return [f(s) for s in soak if f(s) is not None]

    # 검출 주기
    worst_p95 = max((c["age_p95"] for s in soak for c in s["health"]["cams"].values() if c["age_p95"] is not None), default=None)
    min_ok = min((c["age_ok_ratio"] for s in soak for c in s["health"]["cams"].values() if c["age_ok_ratio"] is not None), default=None)
    if worst_p95 is None or worst_p95 > 1.0 or (min_ok is not None and min_ok < 0.9):
        fails.append(f"검출 주기: age p95 최악 {worst_p95}s / ok 비율 최소 {min_ok}")
    # CPU
    cpu = [s["sys_cpu_pct"] for s in soak if s.get("sys_cpu_pct") is not None]
    cores = [s["proc"].get("server_cores") for s in soak if s["proc"].get("server_cores") is not None]
    if not cpu or max(cpu) > P["cpu"]["system_avg_max_pct"]:
        fails.append(f"CPU: 시스템 10분 평균 최대 {max(cpu) if cpu else None}%")
    if cores and max(cores) > P["cpu"]["server_cores_max"]:
        fails.append(f"CPU: 서버 프로세스 최대 {max(cores)}코어")
    # 메모리
    rss = [(s["elapsed_s"], s["proc"].get("rss_mb")) for s in soak if s["proc"].get("rss_mb")]
    if rss:
        if max(r for _t, r in rss) > P["memory"]["server_rss_max_gb"] * 1024:
            fails.append(f"메모리: RSS 최대 {max(r for _t, r in rss)}MB")
        if len(rss) >= 3:
            slope = (rss[-1][1] - rss[0][1]) / max(1, (rss[-1][0] - rss[0][0])) * 3600
            notes.append(f"RSS 기울기 {slope:.0f}MB/h (처음 {rss[0][1]}MB → 끝 {rss[-1][1]}MB)")
            if slope > P["memory"]["leak_max_mb_per_h"]:
                fails.append(f"메모리: 우상향 {slope:.0f}MB/h")
    avail = [s["proc"].get("sys_avail_mb") for s in soak if s["proc"].get("sys_avail_mb")]
    if avail and min(avail) < P["memory"]["system_available_min_gb"] * 1024:
        fails.append(f"메모리: 시스템 가용 최소 {min(avail)}MB")
    # degraded
    dc = sum(s["health"]["degraded_camera_samples"] for s in soak)
    da = sum(s["health"]["degraded_alert_samples"] for s in soak)
    if dc > P["degraded"]["camera_cause_max"]:
        fails.append(f"degraded(카메라 사유) {dc}건")
    notes.append(f"degraded 경보 적체 사유 {da}건(판정 제외)")
    # 프레임 유실·재연결
    for s in soak:
        pass
    drops = {}
    for k in (soak[0]["health"]["cams"].keys() if soak else []):
        seq = [s["health"]["cams"][k].get("dropped") for s in soak if s["health"]["cams"].get(k)]
        seq = [x for x in seq if x is not None]
        if len(seq) >= 2:
            drops[k] = seq[-1] - seq[0]
    interval = hdr.get("interval_s") or 600
    if drops and max(drops.values()) > (hdr.get("fps", 2.0) * interval) * len(soak) * P["frame_loss"]["dropped_pct_max"] / 100:
        fails.append(f"프레임 유실: dropped 증가 {drops}")
    rec_max = max((c.get("reconnects") or 0 for s in soak for c in s["health"]["cams"].values()), default=0)
    if hdr.get("source_kind") == "file" and rec_max > 0:
        fails.append(f"파일 카메라 재연결 {rec_max}회(파일 소스에서 재연결은 비정상)")
    # 열
    perf = [(s["elapsed_s"], s.get("cpu_perf_pct")) for s in soak if s.get("cpu_perf_pct") is not None]
    gclk = [(s["elapsed_s"], s["gpu"].get("clock_sm")) for s in soak if s["gpu"].get("clock_sm") is not None]
    gtemp = [s["gpu"].get("temp_c") for s in soak if s["gpu"].get("temp_c") is not None]

    def floor_check(seq, name, floor_pct):
        first = [v for t_, v in seq if t_ <= 1800]
        late = [v for t_, v in seq if t_ >= 3 * 3600]
        if not first or not late:
            notes.append(f"{name}: 3시간 이후 구간 없음 → 스로틀링 판정 미측정")
            return
        f0, l0 = sum(first) / len(first), sum(late) / len(late)
        notes.append(f"{name}: 첫 30분 평균 {f0:.0f} → 3h 이후 평균 {l0:.0f} ({l0 / f0 * 100:.0f}%)")
        if l0 < f0 * floor_pct / 100:
            fails.append(f"열: {name} 가 초기의 {l0 / f0 * 100:.0f}% 로 하락")
    floor_check(perf, "CPU % Processor Performance", P["thermal"]["cpu_perf_floor_pct_of_initial"])
    floor_check(gclk, "GPU SM clock(MHz)", P["thermal"]["gpu_clock_floor_pct_of_initial"])
    if gtemp and max(gtemp) >= P["thermal"]["gpu_temp_max_c"]:
        fails.append(f"열: GPU 온도 최대 {max(gtemp)}°C")
    # VRAM
    vram = [s["gpu"].get("mem_used_mb") for s in soak if s["gpu"].get("mem_used_mb") is not None]
    if vram and max(vram) > P["gpu_vram"]["used_max_gb"] * 1024:
        fails.append(f"VRAM 최대 {max(vram)}MB")
    # 경보 지연
    lat95 = [s["alerts_window"].get("latency_p95") for s in soak if s["alerts_window"].get("latency_p95") is not None]
    sent = sum(s["alerts_window"].get("sent") or 0 for s in soak)
    if not lat95:
        notes.append(f"경보 지연: 전송 완료 행 {sent}건 → 미측정(채널 미설정 또는 경보 없음)")
    elif max(lat95) > P["alert_latency_s"]["queue_to_sent_p95_max"]:
        fails.append(f"경보 지연: 큐→전송 p95 최대 {max(lat95)}s")
    # 디스크
    disk = [(s["elapsed_s"], s["disk"]["data_mb"] + s["disk"]["logs_mb"]) for s in soak]
    growth = None
    if len(disk) >= 2 and disk[-1][0] > disk[0][0]:
        growth = (disk[-1][1] - disk[0][1]) / (disk[-1][0] - disk[0][0]) * 86400
        notes.append(f"디스크 증가 {growth:.0f}MB/일 (카메라 {hdr.get('cams')}대 합계, 측정 {disk[-1][0] / 3600:.1f}h)")
    hours = (soak[-1]["elapsed_s"] - soak[0]["elapsed_s"]) / 3600 if len(soak) >= 2 else 0
    if hours < 4:
        invalid.append({"type": "invalid", "why": f"소크 {hours:.1f}h < 4h — 지속 부하 판정 불가(초반 성능으로 판단 금지)"})

    md = [f"# 파일럿 부하 실측 — {hdr.get('started')} · {hdr.get('host')} · 카메라 {hdr.get('cams')}대({hdr.get('source_kind')}) · "
          f"간격 {interval}s · 소크 {hours:.1f}h · 녹화 {'포함' if hdr.get('record') else '미포함'}", "",
          f"기준(측정 전 선언 {P.get('declared_at')}): " + " · ".join(f"{k}: {v.get('rule')}" for k, v in P.items() if isinstance(v, dict)), ""]
    if invalid:
        md += ["## ★무효·주의(지우지 않는다)"] + [f"- {x.get('why')}" for x in invalid] + [""]
    md += ["## 판정", "", f"**{'미달' if fails else '통과'}** — " + ("; ".join(fails) if fails else "선언 기준 전부 통과"), ""]
    md += [f"- {n}" for n in notes] + [""]
    md += ["## 소크 샘플(10분 창)", "", "| 시각 | 경과 | n | sysCPU% | CPU perf% | CPU°C | 서버코어 | RSS MB | 가용MB | GPU% | VRAM MB | GPU°C | GPU clk | deg cam/alert | age p95(대별) | detect ms p95 | 경보 n/p95s | data+logs MB |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in samples:
        g, pr, h, a = s["gpu"], s["proc"], s["health"], s["alerts_window"]
        md.append(f"| {s['ts'][11:]} | {s['elapsed_s'] // 60}m | {s['n_cams']} | {s.get('sys_cpu_pct')} | {s.get('cpu_perf_pct')} | {s.get('cpu_temp_c')} | "
                  f"{pr.get('server_cores')} | {pr.get('rss_mb')} | {pr.get('sys_avail_mb')} | {g.get('util')} | {g.get('mem_used_mb')} | {g.get('temp_c')} | {g.get('clock_sm')} | "
                  f"{h['degraded_camera_samples']}/{h['degraded_alert_samples']} | {[c['age_p95'] for c in h['cams'].values()]} | "
                  f"{[c['detect_ms_p95'] for c in h['cams'].values()]} | {a.get('created')}/{a.get('latency_p95')} | {s['disk']['data_mb'] + s['disk']['logs_mb']:.0f} |")
    if over:
        md += ["", "## 과부하(4단계) 관찰", "", "| 시각 | n | sysCPU% | 서버코어 | GPU% | deg cam/alert | age p95 | detect ms p95 | dropped | 경보 p95s | overall |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in over:
            h = s["health"]
            md.append(f"| {s['ts'][11:]} | {s['n_cams']} | {s.get('sys_cpu_pct')} | {s['proc'].get('server_cores')} | {s['gpu'].get('util')} | "
                      f"{h['degraded_camera_samples']}/{h['degraded_alert_samples']} | {[c['age_p95'] for c in h['cams'].values()]} | "
                      f"{[c['detect_ms_p95'] for c in h['cams'].values()]} | {[c['dropped'] for c in h['cams'].values()]} | "
                      f"{s['alerts_window'].get('latency_p95')} | {sorted(set(h['overall']))} |")
    if growth is not None:
        md += ["", "## 저장 용량(5단계 입력)", "", f"- 실측 증가율: {growth:.0f}MB/일 ({hdr.get('cams')}대 합계) → 카메라 1대 {growth / max(1, hdr.get('cams', 1)):.0f}MB/일",
               "- 보존일은 config/tuning.yaml retention.groups 를 읽어 계산한다(report 가 아니라 문서 작성 시 산출 — 그룹별 비율은 data/ 하위 폴더 크기로 분해)"]
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"보고서: {out_md} — {'미달' if fails else '통과'}{' (무효 사유 있음)' if invalid else ''}")
    return 0 if not fails and not invalid else 1


# ── main ────────────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--phase", default="all", choices=["all", "preflight", "cleanup", "report"])
    ap.add_argument("--cams", type=int, default=4)
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--hours", type=float, default=4.0)
    ap.add_argument("--interval", type=float, default=600.0)
    ap.add_argument("--overload-cams", type=int, default=2, help="과부하 단계에서 추가로 붙일 대수(1대씩 누적)")
    ap.add_argument("--overload-min", type=float, default=20.0)
    ap.add_argument("--rtsp-list", default="", help="실카메라 rtsp:// 목록 파일(한 줄 1개)")
    ap.add_argument("--record", action="store_true", help="scripts/field_recorder.py 를 카메라마다 띄워 녹화 부하 포함")
    ap.add_argument("--jsonl", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--exclude", default="", help="사전 등록돼 있으나 집계·유령 검사에서 뺄 카메라 id(콤마) — 예: 오프라인 실카메라")
    a = ap.parse_args()

    if a.phase == "cleanup":
        cleanup()
        return 0
    if a.phase == "report":
        if not a.jsonl:
            raise SystemExit("--jsonl 필요")
        return report(Path(a.jsonl), Path(a.jsonl).with_suffix(".md"))
    if not TOK:
        print("[경고] VIGENT_API_TOKEN 없음(.env) — 서버가 무토큰 로컬 모드일 때만 동작")

    pre = preflight({x.strip() for x in a.exclude.split(",") if x.strip()})
    if a.phase == "preflight":
        return 0

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    audit = _ROOT / "audit"
    audit.mkdir(exist_ok=True)
    jsonl = Path(a.jsonl) if a.jsonl else audit / f"loadtest_{stamp}{('_' + a.tag) if a.tag else ''}.jsonl"
    host = _run(["hostname"]).strip()
    cpu_name = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"]).strip()
    gpu_name = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).strip()
    if a.rtsp_list:
        sources = [ln.strip() for ln in Path(a.rtsp_list).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
        kind = "rtsp"
    else:
        sources = [str(p) for p in scenes()]
        kind = "file"
    if not sources:
        raise SystemExit("[중단] 소스 없음 — VIGENT_DATA_DIR/runs/rfdetr/accident/*.mp4 또는 --rtsp-list")
    pid = find_server_pid()
    header = {"type": "header", "started": _dt.datetime.now().isoformat(timespec="seconds"), "host": host, "cpu": cpu_name, "gpu": gpu_name,
              "cams": a.cams, "fps": a.fps, "hours": a.hours, "interval_s": a.interval, "source_kind": kind,
              "sources": [mask(s) for s in sources], "record": a.record, "server_pid": pid, "preflight": pre, "pass_criteria": PASS,
              "note": "파일 소스는 네트워크 지연·재접속·h264 실스트림 디코드가 없다 — 6단계(네트워크)는 실카메라 전용" if kind == "file" else ""}
    with jsonl.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
    print(f"[header] {host} · {cpu_name} · {gpu_name} · 서버 PID {pid} · 기록 {jsonl}")
    if pid is None:
        print("★서버 PID 를 못 찾음 — 프로세스 CPU/RSS 는 미측정으로 남는다")

    recorders: list[subprocess.Popen] = []
    ids: list[str] = []
    try:
        print(f"[ramp] 카메라 {a.cams}대 등록({kind})")
        ids = add_cams(a.cams, 1, sources, a.fps)
        n = wait_running(ids)
        if n != a.cams:
            with jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "invalid", "why": f"등록 {a.cams}대 중 running {n}대 — 부하가 걸리지 않은 측정(1차 프로브 무효 사유)"}, ensure_ascii=False) + "\n")
            raise SystemExit("[중단] running 대수 불일치")
        if a.record:
            for cid in ids:
                cmd = [sys.executable, str(_ROOT / "scripts" / "field_recorder.py"), "--cam", cid, "--scene", f"pilot_{stamp}_{cid}",
                       "--minutes", str(a.hours * 60 + a.overload_cams * a.overload_min + 5)]
                recorders.append(subprocess.Popen(cmd, cwd=str(_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            print(f"[record] field_recorder {len(recorders)}개 기동(original+overlay → 인코더 {2 * len(recorders)}개)")
        print("[warmup] 120s")
        time.sleep(120)
        smp = Sampler(ids, pid, jsonl, a.fps)
        smp.sample("soak", len(ids))                      # 첫 샘플(CPU 코어 계산 기준점)
        t_end = time.time() + a.hours * 3600
        while time.time() < t_end:
            time.sleep(max(1, a.interval - 35))          # health_burst 30s 포함해 간격 유지
            smp.sample("soak", len(ids))
        for k in range(a.overload_cams):
            extra = add_cams(1, len(ids) + 1, sources, a.fps)
            ids += extra
            smp.ids = ids
            wait_running(ids, 90)
            t_o = time.time() + a.overload_min * 60
            while time.time() < t_o:
                time.sleep(25)
                smp.sample(f"overload{k + 1}", len(ids))
    finally:
        for p in recorders:
            try:
                Path(_ROOT / "runs").mkdir(exist_ok=True)
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        cl = cleanup()
        with jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "cleanup", **cl}, ensure_ascii=False) + "\n")
    return report(jsonl, jsonl.with_suffix(".md"))


if __name__ == "__main__":
    sys.exit(main())
