#!/usr/bin/env python3
"""VIGENT 24시간 소크 모니터 — 실행 중 서버를 '외부에서 관측만' 하며 장시간 안정성을 실증.

soak_test.py(인프로세스 워커 누수관측)와 상보:
  - soak_test.py = 이 스크립트가 직접 worker 를 구동(합성). 파이프라인 누수·hang/kill 복구 관측.
  - soak_monitor.py = **이미 떠 있는 서버**(실 RTSP 카메라 포함)를 HTTP 로 폴링해 프로세스/시스템
    메모리·재연결·프레임처리율·경보이력·에러를 주기 스냅샷으로 기록. 소스 무수정, 순수 관측.
  - 부하결합: --load 로 tools/stress_concurrent.py 를 부하생성 서브프로세스로 띄워 동시부하 하 관측.

기록 항목(주기 스냅샷 → CSV + 종료 시 MD 리포트):
  · 메모리: 프로세스 RSS/FD/스레드(--pid) + 시스템 가용/사용%(psutil.virtual_memory)
  · 워커: 카메라별 frames·fps·running·hang·restarts·reconnects·error 집계(/workers)
  · 프레임 처리율: frames 증분/interval → fps 추정
  · 경보 이력: /recognition/log 누적 이벤트 수 → 증분(구간 경보 건수)
  · 에러/예외: probe 실패 + 워커 error 보고 카운트
  · 크래시: --pid 사망 또는 /health 실패

합격 판정(임계 전부 CLI 조정 가능):
  1) 크래시 0(필수)   2) RSS 기울기 < --rss-max-mb-per-hour(기본10)
  3) 워커 생존율(running==등록)   4) 재연결 후 복구율 100%
  5) 후반 fps ≥ 전반 × --fps-degrade-floor(기본0.8)   6) 에러율 < --err-rate-max(기본0.01)
  7) hang 미복구 0

사용 예:
  # 실카메라 서버 24h 관측(+동시 HTTP 부하)
  python3 tools/soak_monitor.py --url http://127.0.0.1:8010 --pid $(pgrep -f 'main:app.*8010') \
      --duration 24h --interval 60 --load --tag prod24h
  # 도구 자체 단축 검증(합성 워커로 서버 구동 후)
  python3 tools/soak_monitor.py --url http://127.0.0.1:8012 --pid <PID> --duration 90m --interval 30 --tag selftest

종료코드: 합격 0 · 불합격 1.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
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
except ImportError:
    _HAVE_PSUTIL = False


def _parse_duration(s: str) -> float:
    s = str(s).strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def _args():
    p = argparse.ArgumentParser(description="VIGENT 24h 소크 모니터(외부 관측)")
    p.add_argument("--url", required=True, help="실행 중 서버(예: http://127.0.0.1:8010)")
    p.add_argument("--pid", type=int, default=0, help="서버 PID(프로세스 메모리·사망감지). 없으면 /health 만")
    p.add_argument("--duration", default="24h", help="총 관측시간(예: 24h, 90m, 3600). 기본 24h")
    p.add_argument("--interval", type=float, default=60.0, help="샘플링 주기(초). 기본 60")
    p.add_argument("--warmup", type=float, default=300.0,
                   help="워밍업(초) — 초기 로딩 스파이크를 누수 회귀에서 제외. 기본 300")
    p.add_argument("--load", action="store_true", help="stress_concurrent.py 를 부하생성 서브프로세스로 병행")
    p.add_argument("--load-concurrency", type=int, default=4, help="--load 시 동시 클라이언트. 기본 4")
    p.add_argument("--load-vlm-ratio", type=float, default=0.05, help="--load 시 VLM 비율. 기본 0.05")
    p.add_argument("--load-delay", type=float, default=1.0,
                   help="--load 요청 간 대기(초/스레드) — 워커 락기아 방지 완만부하. 기본 1.0. 0=최대속도(워커 굶김)")
    # 판정 임계
    p.add_argument("--rss-max-mb-per-hour", type=float, default=10.0, help="RSS 누수 상한(MB/시간). 기본 10")
    p.add_argument("--fps-degrade-floor", type=float, default=0.8, help="후반/전반 fps 최소비. 기본 0.8")
    p.add_argument("--err-rate-max", type=float, default=0.01, help="에러율 상한(0~1). 기본 0.01")
    p.add_argument("--running-miss-max", type=float, default=0.05,
                   help="running<등록 허용 샘플비율. 기본 0.05")
    p.add_argument("--report-dir", default=str(_ROOT / "audit"), help="리포트 출력 디렉토리")
    p.add_argument("--tag", default="", help="리포트 파일명 접미(예: prod24h)")
    p.add_argument("--token", default="", help="VIGENT_API_TOKEN(토큰 모드 서버 관측용). "
                   "[S3] 미지원이었던 게 발견돼 추가 — 없으면 /workers·/recognition/log 가 "
                   "전부 401나서 워커·경보 통계가 무효화된다(에러율 100%로 오판정).")
    return p.parse_args()


def _get_json(url: str, path: str, token: str = "", timeout: float = 8.0):
    """(ok, 본문dict|None). 실패해도 예외 대신 (False, None)."""
    try:
        req = urllib.request.Request(url.rstrip("/") + path)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if r.status != 200:
                return False, None
            try:
                return True, json.loads(body)
            except Exception:  # noqa: BLE001
                return True, None
    except Exception:  # noqa: BLE001
        return False, None


def _proc_pick(pid: int):
    if _HAVE_PSUTIL and pid:
        try:
            return psutil.Process(pid)
        except Exception:  # noqa: BLE001
            return None
    return None


def _proc_sample(proc):
    out = {"rss_mb": None, "fds": None, "threads": None}
    if proc is not None:
        try:
            out["rss_mb"] = round(proc.memory_info().rss / 1e6, 2)
            out["threads"] = proc.num_threads()
            try:
                out["fds"] = proc.num_fds()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    return out


def _sys_mem():
    out = {"sys_used_pct": None, "sys_used_mb": None, "sys_avail_mb": None}
    if _HAVE_PSUTIL:
        try:
            vm = psutil.virtual_memory()
            out["sys_used_pct"] = vm.percent
            out["sys_used_mb"] = round(vm.used / 1e6, 1)
            out["sys_avail_mb"] = round(vm.available / 1e6, 1)
        except Exception:  # noqa: BLE001
            pass
    return out


def _proc_alive(proc, pid: int) -> bool:
    if proc is not None:
        try:
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except Exception:  # noqa: BLE001
            return False
    if pid:
        try:
            import os
            os.kill(pid, 0)
            return True
        except Exception:  # noqa: BLE001
            return False
    return True   # pid 미지정 → /health 로만 판단


def _median(xs):
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _slope_per_min(ts, ys):
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
    b = sum((x - mx) * (y - my) for x, y in zip(xs, yv)) / den
    return b * 60.0


def _start_load(a):
    """stress_concurrent.py 를 부하생성 서브프로세스로. (proc, logfile) 반환 or (None, None)."""
    dur = _parse_duration(a.duration)
    log = Path(a.report_dir) / f"soak_load_{datetime.now().strftime('%Y-%m-%d')}{('_'+a.tag) if a.tag else ''}.log"
    Path(a.report_dir).mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", str(_HERE / "stress_concurrent.py"),
           "--url", a.url, "--duration", str(int(dur)), "--concurrency", str(a.load_concurrency),
           "--vlm-ratio", str(a.load_vlm_ratio), "--delay", str(a.load_delay),
           "--endpoints", "detect,rfdetr,incident_frame", "--tag", (a.tag + "_load") if a.tag else "load"]
    if a.pid:
        cmd += ["--pid", str(a.pid)]
    f = open(log, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
    print(f"[soak] 부하생성 시작(stress_concurrent): {log.name}")
    return proc, f


def main():
    a = _args()
    duration = _parse_duration(a.duration)
    proc = _proc_pick(a.pid)

    ok0, _ = _get_json(a.url, "/health", a.token)
    if not ok0:
        print(f"[soak] ❌ 사전 /health 실패 — 서버({a.url}) 미기동. 먼저 띄워라.")
        return 2

    load_proc = load_f = None
    if a.load:
        load_proc, load_f = _start_load(a)

    print(f"[soak] 시작: url={a.url} pid={a.pid or '없음'} duration={a.duration}({duration:.0f}s) "
          f"interval={a.interval}s load={a.load} psutil={_HAVE_PSUTIL}")

    samples = []
    server_died = False
    died_at = None
    reconnect_events = []   # (t, cam, from_frames) — 복구 확인 대기
    recovered_ok = 0
    recovered_fail = 0
    hang_events = []
    hang_recovered = 0
    hang_fail = 0
    prev = {"frames": 0, "reconnects": 0, "restarts": 0, "hangs": 0, "alarms": 0}
    prev_errs: dict = {}     # 카메라별 마지막 error 문자열(지속됨) → 변경 시에만 '새 에러 이벤트'로 카운트
    error_events = 0
    workers_total = 0

    t_start = time.time()
    next_sample = t_start
    try:
        while True:
            now = time.time()
            elapsed = now - t_start
            if elapsed >= duration:
                break
            if now < next_sample:
                time.sleep(0.5)
                continue
            next_sample += a.interval

            alive = _proc_alive(proc, a.pid)
            h_ok, _hd = _get_json(a.url, "/health", a.token)
            w_ok, wd = _get_json(a.url, "/workers", a.token)
            ps = _proc_sample(proc)
            sm = _sys_mem()

            # 워커 집계
            cams = (wd or {}).get("cameras", {}) if w_ok else {}
            wcount = (wd or {}).get("worker_count", len(cams)) if w_ok else None
            if wcount:
                workers_total = max(workers_total, wcount)
            running = sum(1 for c in cams.values() if c.get("running"))
            frames = sum(c.get("frames", 0) for c in cams.values())
            reconnects = sum(c.get("reconnects", 0) for c in cams.values())
            restarts = sum(c.get("restarts", 0) for c in cams.values())
            hangs = sum(1 for c in cams.values() if c.get("hang"))
            hangs_cum = sum(c.get("hangs", 0) for c in cams.values())
            werrors = sum(1 for c in cams.values() if c.get("error"))   # 현재 error 필드 보유 카메라 수(참고)
            # 새 에러 이벤트: error 문자열이 이전과 달라진(비어있지 않은) 카메라 = 실제 새 에러 발생
            new_errors = 0
            for cid, c in cams.items():
                e = c.get("error") or ""
                if e and e != prev_errs.get(cid, ""):
                    new_errors += 1
                prev_errs[cid] = e
            error_events += new_errors

            # 경보 누적(events)
            e_ok, ed = _get_json(a.url, "/recognition/log?limit=100000", a.token)
            alarms = len((ed or {}).get("events", [])) if e_ok else None

            fps_est = None
            if frames is not None and prev["frames"] is not None and len(samples) > 0:
                fps_est = round(max(0, frames - prev["frames"]) / a.interval, 3)
            alarms_delta = (alarms - prev["alarms"]) if (alarms is not None and prev["alarms"] is not None) else None

            probe_fail = 0 if (h_ok and w_ok) else 1

            # 크래시 감지
            if not alive or (a.pid and not alive):
                server_died = True
                died_at = round(elapsed, 1)
                print(f"[soak] 🔴 서버 프로세스(PID {a.pid}) 사망 @ {died_at}s")
            row = {
                "t": round(elapsed, 1),
                "proc_rss_mb": ps["rss_mb"], "proc_fds": ps["fds"], "proc_threads": ps["threads"],
                "sys_used_pct": sm["sys_used_pct"], "sys_used_mb": sm["sys_used_mb"],
                "sys_avail_mb": sm["sys_avail_mb"],
                "health_ok": int(h_ok), "alive": int(alive),
                "workers_running": running, "workers_total": wcount, "any_hang": int(hangs > 0),
                "frames_total": frames, "fps_est": fps_est,
                "reconnects_total": reconnects, "restarts_total": restarts, "hangs_cum": hangs_cum,
                "alarms_total": alarms, "alarms_delta": alarms_delta,
                "worker_errors": werrors, "new_errors": new_errors, "probe_fail": probe_fail,
            }
            samples.append(row)

            # 재연결/재시작 증가 → 복구 감시 큐(다음 샘플에 frames 증가했는지)
            if len(samples) > 1:
                if reconnects > prev["reconnects"] or restarts > prev["restarts"]:
                    reconnect_events.append((elapsed, frames))
                if hangs_cum > prev["hangs"]:
                    hang_events.append((elapsed, frames))
            # 이전 이벤트 복구 확인
            for ev in list(reconnect_events):
                ev_t, ev_frames = ev
                if elapsed - ev_t >= a.interval:   # 한 주기 뒤
                    reconnect_events.remove(ev)
                    if frames > ev_frames:
                        recovered_ok += 1
                    else:
                        recovered_fail += 1
            for ev in list(hang_events):
                ev_t, ev_frames = ev
                if elapsed - ev_t >= a.interval * 2:
                    hang_events.remove(ev)
                    if running >= (workers_total or 1) and frames > ev_frames:
                        hang_recovered += 1
                    else:
                        hang_fail += 1

            prev = {"frames": frames, "reconnects": reconnects, "restarts": restarts,
                    "hangs": hangs_cum, "alarms": alarms if alarms is not None else prev["alarms"]}

            print(f"[soak] t={elapsed:7.0f}s rss={ps['rss_mb']}MB sys={sm['sys_used_pct']}% "
                  f"run={running}/{workers_total} frames={frames} fps={fps_est} "
                  f"recon={reconnects} restart={restarts} hang={hangs} alarms={alarms} "
                  f"err={werrors} probe_fail={probe_fail}{'  ⚠️CRASH' if server_died else ''}")
            if server_died:
                break
    except KeyboardInterrupt:
        print("[soak] 중단(Ctrl-C) — 리포트 생성 후 종료")

    # 부하 서브프로세스 정리
    if load_proc is not None:
        try:
            load_proc.terminate()
            load_proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        if load_f is not None:
            load_f.close()

    final_h_ok, _ = _get_json(a.url, "/health", a.token)
    return _report(a, duration, samples, server_died, died_at, final_h_ok,
                   workers_total, recovered_ok, recovered_fail, hang_recovered, hang_fail)


def _report(a, duration, samples, server_died, died_at, final_h_ok,
            workers_total, recovered_ok, recovered_fail, hang_recovered, hang_fail):
    Path(a.report_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_{a.tag}" if a.tag else ""
    base = Path(a.report_dir) / f"soakmon_{stamp}{suffix}"
    md_path, csv_path = base.with_suffix(".md"), base.with_suffix(".csv")

    ts = [s["t"] for s in samples]
    rss = [s["proc_rss_mb"] for s in samples]
    warm = a.warmup
    ts_w = [t for t in ts if t >= warm]
    rss_w = [r for t, r in zip(ts, rss) if t >= warm]
    # 누수 판정은 '노이즈에 강한' 앞 1/4 vs 뒤 1/4 median 비교(MLX/Metal RSS 는 통합메모리라 스윙이 큼 →
    #   짧은 창의 선형회귀 기울기는 왜곡됨). median 차 / 창 중점 시간차 = MB/시간.
    rss_per_hour = 0.0
    rss_slope_info = _slope_per_min(ts_w, rss_w) * 60.0   # 참고용 원 회귀 기울기(MB/시간)
    if len(rss_w) >= 4:
        q = max(1, len(rss_w) // 4)
        first_med, last_med = _median(rss_w[:q]), _median(rss_w[-q:])
        t_first = sum(ts_w[:q]) / q
        t_last = sum(ts_w[-q:]) / q
        dt_h = max(1e-6, (t_last - t_first) / 3600.0)
        if first_med is not None and last_med is not None:
            rss_per_hour = (last_med - first_med) / dt_h
    rss_vals = [r for r in rss if r is not None]
    rss_start = next((r for r in rss_w if r is not None), next((r for r in rss if r is not None), None))
    rss_end = next((r for r in reversed(rss) if r is not None), None)

    n = len(samples)
    # fps 전/후반
    fps = [s["fps_est"] for s in samples if s["fps_est"] is not None]
    half = len(fps) // 2
    fps_first = sum(fps[:half]) / half if half >= 1 else None
    fps_second = sum(fps[half:]) / (len(fps) - half) if (len(fps) - half) >= 1 else None
    fps_ratio = (fps_second / fps_first) if (fps_first and fps_second and fps_first > 0) else None

    # 판정 카운트는 워밍업 이후 샘플로만(초기 모델로드 스파이크·콜드 hang 을 오탐하지 않게).
    pw = [s for s in samples if s["t"] >= a.warmup]
    n_pw = len(pw) or 1
    running_miss = sum(1 for s in pw if s["workers_total"] and s["workers_running"] < s["workers_total"])
    running_miss_rate = running_miss / n_pw
    min_running = min((s["workers_running"] for s in samples if s["workers_total"]), default=None)

    probe_fails = sum(s["probe_fail"] for s in pw)
    error_events = sum(s.get("new_errors", 0) for s in pw)   # 새 에러 이벤트(지속 문자열 아님)
    err_rate = (probe_fails + error_events) / n_pw

    reconnects_total = samples[-1]["reconnects_total"] if samples else 0
    restarts_total = samples[-1]["restarts_total"] if samples else 0
    alarms_total = next((s["alarms_total"] for s in reversed(samples) if s["alarms_total"] is not None), 0)
    recover_total = recovered_ok + recovered_fail
    recover_rate = (recovered_ok / recover_total * 100) if recover_total else None
    hang_total = hang_recovered + hang_fail
    hang_rate = (hang_recovered / hang_total * 100) if hang_total else None

    sys_pct = [s["sys_used_pct"] for s in samples if s["sys_used_pct"] is not None]
    sys_pct_max = max(sys_pct) if sys_pct else None

    # ── 판정 ──
    p_crash = (not server_died) and final_h_ok
    p_rss = rss_per_hour < a.rss_max_mb_per_hour
    p_running = running_miss_rate <= a.running_miss_max
    p_recover = (recover_rate is None) or (recover_rate >= 100.0 - 1e-9)
    p_fps = (fps_ratio is None) or (fps_ratio >= a.fps_degrade_floor)
    p_err = err_rate < a.err_rate_max
    p_hang = (hang_rate is None) or (hang_rate >= 100.0 - 1e-9)
    passed = all([p_crash, p_rss, p_running, p_recover, p_fps, p_err, p_hang])

    def yn(b): return "✅" if b else "❌"

    L = []
    L.append(f"# VIGENT 소크 모니터 리포트 — {stamp}{(' / ' + a.tag) if a.tag else ''}")
    L.append("")
    L.append(f"> 외부 관측. url={a.url} · pid={a.pid or '없음'} · {a.duration}({duration:.0f}s) · "
             f"샘플 {a.interval}s · 부하 {'ON' if a.load else 'OFF'} · warmup={a.warmup:.0f}s · "
             f"샘플수 {n} · psutil={_HAVE_PSUTIL}")
    L.append("")
    L.append(f"## 판정: {'✅ 합격' if passed else '❌ 불합격'}")
    L.append("")
    L.append("| # | 기준 | 결과 | 판정 |")
    L.append("|---|---|---|---|")
    L.append(f"| 1 | 크래시 0 | 사망 {'예@'+str(died_at)+'s' if server_died else '없음'} · 종료후 /health {'200' if final_h_ok else '실패'} | {yn(p_crash)} |")
    L.append(f"| 2 | 메모리 누수 | RSS {rss_per_hour:+.2f} MB/시간(median 앞1/4↔뒤1/4, 임계 {a.rss_max_mb_per_hour}) | {yn(p_rss)} |")
    L.append(f"| 3 | 워커 생존율 | running 미달 샘플 {running_miss}/{n}={running_miss_rate*100:.1f}% (최저 {min_running}/{workers_total}) | {yn(p_running)} |")
    L.append(f"| 4 | 재연결 복구율 | {('%.0f%%' % recover_rate) if recover_rate is not None else 'N/A(재연결 0)'} (성공 {recovered_ok}/{recover_total}) | {yn(p_recover)} |")
    L.append(f"| 5 | 처리율 안정 | 후반/전반 fps {('%.2f' % fps_ratio) if fps_ratio is not None else 'N/A'} (임계 {a.fps_degrade_floor}) | {yn(p_fps)} |")
    L.append(f"| 6 | 에러율 | {err_rate*100:.2f}% (probe실패 {probe_fails}+에러이벤트 {error_events})/{n_pw}후반 (임계 {a.err_rate_max*100:.0f}%) | {yn(p_err)} |")
    L.append(f"| 7 | hang 복구 | {('%.0f%%' % hang_rate) if hang_rate is not None else 'N/A(hang 0)'} (복구 {hang_recovered}/{hang_total}) | {yn(p_hang)} |")
    L.append("")
    L.append("## 메모리")
    L.append(f"- 프로세스 RSS: 시작 {rss_start} → 끝 {rss_end} MB · 최소 {min(rss_vals) if rss_vals else None} · 최대 {max(rss_vals) if rss_vals else None}")
    L.append(f"- 누수율(median 기반, 판정): **{rss_per_hour:+.2f} MB/시간** · 참고 원회귀: {rss_slope_info:+.2f} MB/시간 (워밍업 {warm:.0f}s 이후. MLX/Metal RSS 스윙 큼 → median 채택)")
    L.append(f"- 시스템 메모리 사용률 최대: {sys_pct_max}%")
    L.append("")
    L.append("## 워커·처리율·경보")
    L.append(f"- 등록 워커: {workers_total} · running 최저 {min_running} · running 미달률 {running_miss_rate*100:.1f}%")
    L.append(f"- 프레임 처리율(fps 추정): 전반 {('%.2f' % fps_first) if fps_first else 'n/a'} → 후반 {('%.2f' % fps_second) if fps_second else 'n/a'}")
    L.append(f"- 재연결 {reconnects_total} · 재시작 {restarts_total} · 경보 누적 {alarms_total}건")
    L.append(f"- 에러율 {err_rate*100:.2f}% (probe실패 {probe_fails} · 새 에러이벤트 {error_events}, 워밍업 이후 {n_pw}샘플 기준)")
    L.append("")
    L.append("## 비고")
    L.append("- 순수 외부 관측(소스 무수정). 실 RTSP 카메라가 없으면 재연결=0 → 기준4는 N/A(합성).")
    L.append(f"- 부하: {'stress_concurrent 병행(soak_load_*.log)' if a.load else '없음(관측만)'}.")
    L.append(f"- 원자료: `{csv_path.name}`")
    md_path.write_text("\n".join(L), encoding="utf-8")

    cols = ["t", "proc_rss_mb", "proc_fds", "proc_threads", "sys_used_pct", "sys_used_mb",
            "sys_avail_mb", "health_ok", "alive", "workers_running", "workers_total", "any_hang",
            "frames_total", "fps_est", "reconnects_total", "restarts_total", "hangs_cum",
            "alarms_total", "alarms_delta", "worker_errors", "new_errors", "probe_fail"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for s in samples:
            w.writerow({k: s.get(k) for k in cols})

    print("")
    print(f"[soak] 판정: {'✅ 합격' if passed else '❌ 불합격'}  |  RSS {rss_per_hour:+.2f}MB/h · "
          f"크래시 {'예' if server_died else '0'} · 에러율 {err_rate*100:.2f}% · 경보 {alarms_total}")
    print(f"[soak] 리포트: {md_path}")
    print(f"[soak] 원자료: {csv_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
