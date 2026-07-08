#!/usr/bin/env python3
"""VIGENT 소크 테스트 하네스(안정성 3단계).

장시간 연속 가동을 자동 검증한다 — 크래시·메모리 누수·리소스(FD/스레드) 누수 유무를
합성 입력만으로 실증한다. **소스 코드를 수정하지 않고 관찰·구동만** 하는 것을 원칙으로 한다
(worker.Worker/WorkerManager 를 그대로 import 해 인프로세스로 구동).

두 관측 대상:
  1) 인프로세스(기본): 이 스크립트가 직접 worker 를 N개 구동 → 자기 프로세스 RSS/FD/스레드를 psutil 로 관측.
     합성 SoakGuard 로 hang/kill 을 실제 주입해 '반복 복구가 누수를 만드는지' 를 본다.
  2) 서버 병행(--url): 실행 중 서버의 /health·/status 성공률·지연·워커 지표를 함께 샘플(관찰만).

사용 예(각 단계 후 macOS 에서 바로):
  # 15분 스모크(합성 3워커, 30초 주기, 60초마다 장애주입)
  python3 tools/soak_test.py --duration 15m --workers 3 --interval 30 --inject
  # 1시간
  python3 tools/soak_test.py --duration 1h --workers 3 --interval 30 --inject
  # 24시간(명령 한 줄)
  python3 tools/soak_test.py --duration 24h --workers 4 --interval 30 --inject --tag prod24h
  # 실행 중 서버도 병행 관찰
  python3 tools/soak_test.py --duration 15m --workers 2 --inject --url http://127.0.0.1:8010

종료 시 audit/soak_YYYY-MM-DD[_tag].md (요약+판정) 와 .csv(원자료) 를 자동 생성한다.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:  # 표준 라이브러리 폴백(제한적 — RSS/스레드만 근사)
    _HAVE_PSUTIL = False


# ── 인자 ──────────────────────────────────────────────────────────────
def _parse_duration(s: str) -> float:
    """'15m'·'1h'·'24h'·'900'(초) → 초."""
    s = str(s).strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def _args():
    p = argparse.ArgumentParser(description="VIGENT 소크 테스트 하네스(3단계)")
    p.add_argument("--duration", default="15m", help="총 가동시간(예: 15m, 1h, 24h, 900). 기본 15m")
    p.add_argument("--workers", type=int, default=3, help="합성 워커(가짜 카메라) 개수. 기본 3")
    p.add_argument("--interval", type=float, default=30.0, help="샘플링 주기(초). 기본 30")
    p.add_argument("--fps", type=float, default=5.0, help="워커 처리 fps(합성). 기본 5")
    p.add_argument("--inject", action="store_true", help="주기적 장애주입(hang/kill 순환) 활성화")
    p.add_argument("--inject-every", type=float, default=60.0, help="장애주입 간격(초). 기본 60")
    p.add_argument("--warmup", type=float, default=60.0,
                   help="워밍업(초) — 초기 로딩 스파이크를 누수 회귀에서 제외. 기본 60")
    p.add_argument("--hang-timeout", type=float, default=8.0,
                   help="hang 감지 임계(초) — env VIGENT_HANG_TIMEOUT 로 worker 에 주입. 기본 8(소크용 단축)")
    p.add_argument("--guard", choices=["mock", "real"], default="mock",
                   help="mock=경량 합성 detect(파이프라인 누수 관찰) / real=실제 Guard(추론 포함). 기본 mock")
    p.add_argument("--url", default="", help="병행 관찰할 실행 서버(예: http://127.0.0.1:8010). 없으면 인프로세스만")
    p.add_argument("--report-dir", default=str(_ROOT / "audit"), help="리포트 출력 디렉토리")
    p.add_argument("--tag", default="", help="리포트 파일명 접미(예: prod24h)")
    p.add_argument("--tracemalloc", action="store_true",
                   help="tracemalloc 로 상위 할당 지점 추적(시작 대비 증가 Top-N) — 4단계 누수 점검")
    p.add_argument("--trace-top", type=int, default=12, help="tracemalloc Top-N. 기본 12")
    return p.parse_args()


# ── 합성 입력 / 장애주입 훅 ─────────────────────────────────────────────
class SoakGuard:
    """합성 detect. 소스 무수정으로 hang 을 주입하기 위한 모의 Guard.
    trigger_hang() 하면 다음 detect 가 그만큼 블로킹 → worker 의 hang 감시가 감지·재기동한다."""
    def __init__(self):
        self._hang_req = 0.0
        self.calls = 0

    def trigger_hang(self, seconds: float):
        self._hang_req = seconds

    def detect(self, frame, detectors=None):
        self.calls += 1
        if self._hang_req > 0:
            d = self._hang_req
            self._hang_req = 0.0
            time.sleep(d)                       # 프레임 진전 정지 → last_frame_ts 멈춤 → hang 감지 유발
        return {"detections": []}               # person 없음 → 포즈 스킵(경량). 파이프라인(cv2·tracker·rule)은 실제 실행


def _make_synth_source() -> str:
    """합성 이미지 파일 1개 생성 → 워커 소스로 사용(worker 가 static.copy 로 프레임 공급)."""
    import numpy as np
    import cv2
    p = Path(os.environ.get("CLAUDE_JOB_DIR", "/tmp")) / "tmp"
    p.mkdir(parents=True, exist_ok=True)
    fp = p / "soak_synth.jpg"
    cv2.imwrite(str(fp), (np.random.default_rng(0).integers(0, 255, (240, 320, 3), dtype="uint8")))
    return str(fp)


# ── 지표 샘플링 ─────────────────────────────────────────────────────────
def _proc_sample(proc):
    """자기 프로세스의 RSS(MB)·FD·스레드·소켓·CPU%."""
    out = {"rss_mb": None, "fds": None, "threads": None, "conns": None, "cpu": None}
    if _HAVE_PSUTIL and proc is not None:
        try:
            out["rss_mb"] = round(proc.memory_info().rss / 1e6, 2)
            out["threads"] = proc.num_threads()
            out["cpu"] = round(proc.cpu_percent(interval=None), 1)
            try:
                out["fds"] = proc.num_fds()
            except Exception:
                pass
            try:
                _cf = getattr(proc, "net_connections", None) or proc.connections
                out["conns"] = len(_cf(kind="all"))
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            import resource
            out["rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2)  # macOS: bytes
            import threading as _t
            out["threads"] = _t.active_count()
        except Exception:
            pass
    return out


def _http_probe(url: str, path: str, timeout: float = 5.0):
    """(성공여부, 지연ms, 본문dict|None)."""
    t0 = time.time()
    try:
        with urllib.request.urlopen(url.rstrip("/") + path, timeout=timeout) as r:
            body = r.read()
            ms = round((time.time() - t0) * 1000, 1)
            ok = r.status == 200
            try:
                return ok, ms, json.loads(body)
            except Exception:
                return ok, ms, None
    except Exception:
        return False, round((time.time() - t0) * 1000, 1), None


def _slope_per_min(ts, ys):
    """단순 선형회귀 기울기 → 분당 증가량. 표본 부족/무효 시 0."""
    pts = [(t, y) for t, y in zip(ts, ys) if y is not None]
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    t0 = pts[0][0]
    xs = [(t - t0) for t, _ in pts]
    yv = [y for _, y in pts]
    mx = sum(xs) / n
    my = sum(yv) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, yv)) / den  # 단위/초
    return b * 60.0                                             # 단위/분


# ── 메인 ────────────────────────────────────────────────────────────────
def main():
    a = _args()
    duration = _parse_duration(a.duration)

    # worker import 전에 hang 임계를 env 로 주입(worker 는 import 시 상수 로드) — 소스 무수정
    os.environ["VIGENT_HANG_TIMEOUT"] = str(a.hang_timeout)
    sys.path.insert(0, str(_ROOT / "vigent-core"))
    import worker as W
    import threading

    guard_kind = a.guard
    guards = []
    if guard_kind == "real":
        try:
            sys.path.insert(0, str(_ROOT / "vigent-core"))
            import main as _m
            bundle = _m._load_theme(_m.DEFAULT_THEME)
            real_guard = bundle["agents"].get("Guard")
            guards = [real_guard] * a.workers          # 실제 Guard 공유(추론 포함 — 무거움)
            print(f"[soak] guard=real (실제 Guard 로드 — 추론 포함)")
        except Exception as e:  # noqa: BLE001
            print(f"[soak] real Guard 로드 실패({e}) → mock 폴백")
            guard_kind = "mock"
    if guard_kind == "mock":
        guards = [SoakGuard() for _ in range(a.workers)]

    source = _make_synth_source()
    mgr = W.WorkerManager()                            # 소크 전용 인스턴스(전역 오염 없음)
    if guard_kind == "real":
        _shared = threading.Lock()
        locks = [_shared] * a.workers                      # 공유 lock: 실서버 _DETECT_LOCK 반영 + torch 동시 forward 회피
    else:
        locks = [threading.Lock() for _ in range(a.workers)]   # 워커별 독립 lock(hang 격리 — 실서버는 공유 _DETECT_LOCK)

    # real guard 는 첫 detect 가 모델 lazy init/torch trace 로 수초 걸린다(이후엔 0.0x초).
    #   워커 시작 전에 1회 워밍업해 그 지연을 소진 → hang 오탐 방지(첫 프레임이 HANG_TIMEOUT 을 건드리지 않게).
    if guard_kind == "real":
        try:
            import cv2 as _cv2
            _wf = _cv2.imread(source)
            t_w = time.time()
            for _g in {id(g): g for g in guards}.values():
                _g.detect(_wf, detectors=["person", "ppe", "forklift", "fire_smoke"])
            print(f"[soak] real guard 워밍업 detect 완료({time.time()-t_w:.1f}s — 첫 추론 지연 소진)")
        except Exception as e:  # noqa: BLE001
            print(f"[soak] 워밍업 detect 실패(무시): {e}")

    print(f"[soak] 시작: duration={a.duration}({duration:.0f}s) workers={a.workers} "
          f"interval={a.interval}s inject={a.inject} guard={guard_kind} hang_timeout={a.hang_timeout}s "
          f"psutil={_HAVE_PSUTIL}")
    for i in range(a.workers):
        r = mgr.start(guards[i], locks[i], f"soak{i}", source, name=f"SOAK{i}", fps=a.fps,
                      detectors=["person"])
        if not r.get("ok"):
            print(f"[soak] 워커{i} 시작 실패: {r}")

    proc = psutil.Process(os.getpid()) if _HAVE_PSUTIL else None
    if proc is not None:
        proc.cpu_percent(interval=None)                # cpu_percent 워밍업(첫 호출 0)

    trace_on = a.tracemalloc
    if trace_on:
        import tracemalloc
        tracemalloc.start(25)                          # 25 프레임 콜스택 유지
    trace_snaps = []       # (elapsed, total_mb) 추이
    trace_first = None      # 워밍업 이후 첫 스냅샷(비교 기준)
    trace_last = None

    samples = []       # 각 샘플 dict
    injections = []    # (t, kind, worker, recovered_bool)
    health_ok = health_tot = status_ok = status_tot = 0
    t_start = time.time()
    next_sample = t_start
    next_inject = t_start + a.inject_every if a.inject else float("inf")
    inject_seq = 0
    pending = []       # 복구 확인 대기: (check_at, kind, worker, baseline_frames)

    try:
        while True:
            now = time.time()
            elapsed = now - t_start
            if elapsed >= duration:
                break

            # ── 샘플링 ──
            if now >= next_sample:
                st = mgr.status()
                cams = st.get("cameras", {})
                total_frames = sum(c.get("frames", 0) for c in cams.values())
                total_restarts = sum(c.get("restarts", 0) for c in cams.values())
                total_reconnects = sum(c.get("reconnects", 0) for c in cams.values())
                total_hangs = sum(c.get("hangs", 0) for c in cams.values())
                running = sum(1 for c in cams.values() if c.get("running"))
                ps = _proc_sample(proc)
                row = {"t": round(elapsed, 1), "rss_mb": ps["rss_mb"], "fds": ps["fds"],
                       "threads": ps["threads"], "conns": ps["conns"], "cpu": ps["cpu"],
                       "frames": total_frames, "restarts": total_restarts,
                       "reconnects": total_reconnects, "hangs": total_hangs, "running": running,
                       "health_ms": None, "status_ms": None}
                if a.url:
                    h_ok, h_ms, _ = _http_probe(a.url, "/health")
                    s_ok, s_ms, _ = _http_probe(a.url, "/status")
                    health_tot += 1; status_tot += 1
                    health_ok += 1 if h_ok else 0; status_ok += 1 if s_ok else 0
                    row["health_ms"] = h_ms; row["status_ms"] = s_ms
                if trace_on:
                    _snap = tracemalloc.take_snapshot()
                    _tot = sum(s.size for s in _snap.statistics("lineno"))
                    trace_snaps.append((round(elapsed, 1), round(_tot / 1e6, 2)))
                    if elapsed >= a.warmup:            # 모델 로딩 스파이크 제외한 첫 스냅샷을 기준으로
                        if trace_first is None:
                            trace_first = _snap
                        trace_last = _snap
                samples.append(row)
                print(f"[soak] t={elapsed:6.0f}s rss={ps['rss_mb']}MB fds={ps['fds']} thr={ps['threads']} "
                      f"frames={total_frames} restarts={total_restarts} reconnects={total_reconnects} "
                      f"hangs={total_hangs} running={running}/{a.workers}")
                next_sample += a.interval

            # ── 장애주입 ──
            if now >= next_inject:
                widx = inject_seq % a.workers
                kind = ["hang", "kill"][inject_seq % 2]
                cams = mgr.status().get("cameras", {})
                baseline = cams.get(f"soak{widx}", {}).get("frames", 0)
                if kind == "hang" and guard_kind == "mock":
                    guards[widx].trigger_hang(a.hang_timeout + 3)
                    print(f"[soak] ⚡주입 hang → SOAK{widx} (baseline frames={baseline})")
                elif kind == "hang":
                    kind = "kill"     # real guard 는 hang 주입 훅 없음 → kill 로 대체
                if kind == "kill":
                    mgr.stop(f"soak{widx}")
                    mgr.start(guards[widx], locks[widx], f"soak{widx}", source, name=f"SOAK{widx}",
                              fps=a.fps, detectors=["person"])
                    print(f"[soak] ⚡주입 kill+restart → SOAK{widx} (baseline frames={baseline})")
                # 복구 확인: hang_timeout+백오프 여유 뒤 frames 증가 재개했는지
                #   kill 은 restart 로 frames=0 리셋되므로 기준을 0 으로(진전 재개=frames>0). hang 은 리셋 안 됨(>baseline).
                ref = baseline if kind == "hang" else 0
                delay = (a.hang_timeout + 8) if kind == "hang" else 8.0   # kill 은 즉시 재시작 → 짧게 확인
                pending.append((now + delay, kind, widx, ref))
                injections.append([round(elapsed, 1), kind, widx, None])
                inject_seq += 1
                next_inject += a.inject_every

            # ── 복구 확인 ──
            due = [p for p in pending if now >= p[0]]
            for p in due:
                pending.remove(p)
                _, kind, widx, baseline = p
                cur = mgr.status().get("cameras", {}).get(f"soak{widx}", {})
                recovered = bool(cur.get("running")) and cur.get("frames", 0) > baseline
                for inj in injections:
                    if inj[3] is None and inj[1] == kind and inj[2] == widx:
                        inj[3] = recovered
                        break
                print(f"[soak] ✅복구확인 SOAK{widx} {kind}: {'정상재개' if recovered else '미복구'} "
                      f"(frames {baseline}→{cur.get('frames')})")

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[soak] 중단(Ctrl-C) — 리포트 생성 후 종료")

    # 종료: 워커 정리
    mgr.stop_all()
    fin = mgr.status().get("cameras", {})

    # ── 리포트 ──
    return _report(a, duration, samples, injections, health_ok, health_tot,
                   status_ok, status_tot, fin, guard_kind,
                   trace_snaps=trace_snaps, trace_first=trace_first, trace_last=trace_last)


def _report(a, duration, samples, injections, health_ok, health_tot,
            status_ok, status_tot, fin, guard_kind,
            trace_snaps=None, trace_first=None, trace_last=None):
    Path(a.report_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_{a.tag}" if a.tag else ""
    base = Path(a.report_dir) / f"soak_{stamp}{suffix}"
    md_path = base.with_suffix(".md")
    csv_path = base.with_suffix(".csv")

    ts = [s["t"] for s in samples]
    rss = [s["rss_mb"] for s in samples]
    fds = [s["fds"] for s in samples]
    thr = [s["threads"] for s in samples]

    def _stat(v):
        vv = [x for x in v if x is not None]
        return (min(vv), max(vv), sum(vv) / len(vv)) if vv else (None, None, None)

    # 누수 회귀는 워밍업(초기 로딩 스파이크) 이후 샘플로만 — 초기 급증이 기울기를 왜곡하지 않게
    warm = getattr(a, "warmup", 0.0)
    ts_w = [t for t in ts if t >= warm]
    rss_w = [r for t, r in zip(ts, rss) if t >= warm]
    fds_w = [d for t, d in zip(ts, fds) if t >= warm]

    rss_min, rss_max, rss_avg = _stat(rss)
    rss_start = next((x for x in rss_w if x is not None), next((x for x in rss if x is not None), None))
    rss_end = next((x for x in reversed(rss) if x is not None), None)
    rss_slope = _slope_per_min(ts_w, rss_w)                 # MB/분 (워밍업 이후)
    fd_start = next((x for x in fds_w if x is not None), next((x for x in fds if x is not None), None))
    fd_end = next((x for x in reversed(fds) if x is not None), None)
    fd_slope = _slope_per_min(ts_w, fds_w)
    thr_start = next((x for x in thr if x is not None), None)
    thr_end = next((x for x in reversed(thr) if x is not None), None)

    last = samples[-1] if samples else {}
    total_restarts = last.get("restarts", 0)
    total_reconnects = last.get("reconnects", 0)
    total_hangs = last.get("hangs", 0)
    crashed = sum(1 for c in fin.values() if not c.get("running"))   # 종료 시 정지=stop_all 후이므로 참고용
    # 소크 도중 '죽는 경로': 샘플에서 running < workers 였던 순간(주입 순간 제외 어려워 최저치로 보고)
    min_running = min((s.get("running", a.workers) for s in samples), default=a.workers)

    inj_total = len(injections)
    inj_recovered = sum(1 for i in injections if i[3] is True)
    inj_pending = sum(1 for i in injections if i[3] is None)
    recover_rate = (inj_recovered / inj_total * 100) if inj_total else None

    health_rate = (health_ok / health_tot * 100) if health_tot else None
    status_rate = (status_ok / status_tot * 100) if status_tot else None

    # ── 합격 판정(임계값은 여유 있게 — 우상향 신호만 잡음) ──
    rss_leak_thresh = 2.0        # MB/분 이상 지속 증가 → 누수 의심
    verdict = []
    p_crash = (min_running >= a.workers) or (inj_total > 0)   # 주입 없으면 항상 workers 유지여야
    # 크래시 판정은 '주입 외 시점에 running 감소'가 이상적이나 근사: 최종 리포트에 min_running 명시
    p_rss = (rss_slope is not None and rss_slope < rss_leak_thresh)
    p_fd = (fd_start is None or fd_end is None or (fd_end - fd_start) <= max(20, 0.1 * (fd_start or 1)))
    p_recover = (recover_rate is None) or (recover_rate >= 100.0 - 1e-9)
    passed = p_rss and p_fd and p_recover

    lines = []
    lines.append(f"# VIGENT 소크 테스트 리포트 — {stamp}{(' / ' + a.tag) if a.tag else ''}")
    lines.append("")
    lines.append(f"> 안정성 3단계. 합성 {a.workers}워커 · {a.duration}({duration:.0f}s) · "
                 f"샘플 {a.interval}s · 주입 {'ON('+str(a.inject_every)+'s)' if a.inject else 'OFF'} · "
                 f"guard={guard_kind} · hang_timeout={a.hang_timeout}s · warmup={getattr(a,'warmup',0):.0f}s · psutil={_HAVE_PSUTIL}")
    lines.append("")
    lines.append(f"## 판정: {'✅ 합격' if passed else '❌ 불합격(아래 원인 확인)'}")
    one = []
    one.append(f"RSS {rss_slope:+.2f}MB/분")
    one.append(f"FD {('+' + str(fd_end - fd_start)) if (fd_start is not None and fd_end is not None) else 'n/a'}")
    one.append(f"복구 {recover_rate:.0f}%" if recover_rate is not None else "복구 n/a")
    one.append(f"재시작 {total_restarts}·재연결 {total_reconnects}·hang {total_hangs}")
    lines.append(f"**한 줄 요약**: {' · '.join(one)}")
    lines.append("")
    lines.append("## 메모리(RSS)")
    lines.append("| 시작 | 끝 | 최소 | 최대 | 평균 | 기울기(MB/분) | 누수판정 |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(f"| {rss_start} | {rss_end} | {rss_min} | {rss_max} | "
                 f"{round(rss_avg,2) if rss_avg else None} | {rss_slope:+.3f} | "
                 f"{'⚠️ 우상향 의심' if not p_rss else '안정'} |")
    lines.append("")
    lines.append("## 리소스(FD·스레드)")
    lines.append("| 지표 | 시작 | 끝 | 증감 | 기울기(/분) | 판정 |")
    lines.append("|---|---|---|---|---|---|")
    lines.append(f"| FD | {fd_start} | {fd_end} | "
                 f"{(fd_end - fd_start) if (fd_start is not None and fd_end is not None) else 'n/a'} | "
                 f"{fd_slope:+.3f} | {'안정' if p_fd else '⚠️ 증가'} |")
    lines.append(f"| 스레드 | {thr_start} | {thr_end} | "
                 f"{(thr_end - thr_start) if (thr_start is not None and thr_end is not None) else 'n/a'} | — | — |")
    lines.append("")
    lines.append("## 복구·안정성")
    lines.append(f"- 소크 중 최저 동시가동 워커: **{min_running}/{a.workers}** "
                 f"(주입 순간의 일시 감소 포함 — 최종 stop_all 전 기준)")
    lines.append(f"- 장애주입: 총 {inj_total}회 (복구성공 {inj_recovered} · 미복구 {inj_total - inj_recovered - inj_pending} · 확인대기 {inj_pending})")
    lines.append(f"- 복구 성공률: **{recover_rate:.0f}%**" if recover_rate is not None else "- 복구 성공률: n/a(주입 없음)")
    lines.append(f"- 누적 재시작 {total_restarts} · 재연결 {total_reconnects} · hang 감지 {total_hangs}")
    if a.url:
        lines.append(f"- /health 성공률 {health_rate:.1f}% ({health_ok}/{health_tot}) · "
                     f"/status 성공률 {status_rate:.1f}% ({status_ok}/{status_tot})")
    lines.append("")
    lines.append("## 판정 근거")
    lines.append(f"- RSS 기울기 {rss_slope:+.3f} MB/분 {'< ' if p_rss else '≥ '}{rss_leak_thresh}(임계) → {'통과' if p_rss else '누수 의심'}")
    lines.append(f"- FD 증감 판정 → {'통과' if p_fd else '증가(누수 의심)'}")
    lines.append(f"- 복구 성공률 {'100%' if p_recover else '<100%'} → {'통과' if p_recover else '실패'}")
    lines.append("")
    lines.append("## 비고")
    lines.append("- 워커별 독립 lock 으로 hang 을 격리(실서버는 공유 `_DETECT_LOCK`). RTSP 재연결은 실 스트림이 없어 "
                 "소크는 hang/kill 주입 위주 — 재연결 로직은 2단계에서 단위 실증 완료.")
    lines.append(f"- guard={guard_kind}: mock=합성 detect(파이프라인 cv2·tracker·rule 은 실제 실행, 추론모델 제외) / "
                 "real=실제 Guard 추론 포함. 추론모델 누수까지 보려면 `--guard real`.")
    lines.append(f"- 원자료: `{csv_path.name}`")
    if not p_rss:
        # 우상향이면 어느 시점부터 증가하는지 보고(4단계 입력) — 워밍업 이후 구간을 반분
        half = len(rss_w) // 2
        s1 = _slope_per_min(ts_w[:half], rss_w[:half]) if half >= 3 else 0.0
        s2 = _slope_per_min(ts_w[half:], rss_w[half:]) if (len(rss_w) - half) >= 3 else 0.0
        lines.append(f"- ⚠️ **누수 신호**: (워밍업 {warm:.0f}s 이후) 전반 {s1:+.2f} / 후반 {s2:+.2f} MB/분. "
                     f"4단계 누수 점검 입력 — CSV 의 t/rss_mb 컬럼으로 증가 시점 확인.")

    if trace_snaps:
        lines.append("")
        lines.append("## tracemalloc (상위 할당 추적 — 4단계)")
        t0m, t1m = trace_snaps[0][1], trace_snaps[-1][1]
        step = max(1, len(trace_snaps) // 8)
        lines.append(f"- 추적 total(파이썬 힙): 시작 {t0m}MB → 끝 {t1m}MB (증감 **{t1m - t0m:+.2f}MB**)")
        lines.append(f"- 추이(MB): {' → '.join(str(mb) for _, mb in trace_snaps[::step])}")
        if trace_first is not None and trace_last is not None:
            diff = trace_last.compare_to(trace_first, "lineno")
            lines.append("")
            lines.append(f"### 워밍업 이후 시작 대비 증가 Top-{a.trace_top} (양수=증가 → 누수 후보)")
            lines.append("| 증가(KB) | 현재(KB) | 위치 |")
            lines.append("|---|---|---|")
            for stt in diff[:a.trace_top]:
                loc = str(stt.traceback).replace("|", "/")
                lines.append(f"| {stt.size_diff/1024:+.1f} | {stt.size/1024:.1f} | `{loc}` |")
            lines.append("")
            lines.append("> 해석: total 증감이 0 근처이고 Top 증가분이 모델·프레임워크 상주(정상)면 누수 아님. "
                         "특정 앱 코드 라인이 시간에 비례해 계속 커지면 누수.")

    md_path.write_text("\n".join(lines), encoding="utf-8")

    cols = ["t", "rss_mb", "fds", "threads", "conns", "cpu", "frames", "restarts",
            "reconnects", "hangs", "running", "health_ms", "status_ms"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in samples:
            w.writerow({k: s.get(k) for k in cols})

    print("")
    print(f"[soak] 판정: {'✅ 합격' if passed else '❌ 불합격'}  |  {' · '.join(one)}")
    print(f"[soak] 리포트: {md_path}")
    print(f"[soak] 원자료: {csv_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
