"""[M1] 엔드투엔드 경보 지연 실측 — 캡처→검출→판정→기록→전송.

★안전장치: 기록·전송 단계는 **임시 폴더/임시 DB** 로 격리해 실서비스 데이터
(data/evidence·data/recognition·alert_queue.db)를 건드리지 않는다.
라이브 단계(A)는 /health 를 읽기만 한다 — 실카메라 무간섭.

실행: python benchmarks/m1_alert_latency.py [--samples 60]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import numpy as np  # noqa: E402
import requests  # noqa: E402

HEALTH = "http://127.0.0.1:8010/health"


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    i = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[i]


# ---------------------------------------------------------------- A. 라이브
def stage_a(samples: int, interval: float = 1.0) -> dict:
    """실카메라 /health 폴링 — 캡처 신선도 · 검출 지연 · 검출 주기."""
    frame_age, infer, lock_wait, detect_age = [], [], [], []
    got = 0
    for _ in range(samples):
        try:
            r = requests.get(HEALTH, timeout=5)
            cams = (r.json() or {}).get("cameras") or {}
        except Exception:  # noqa: BLE001
            time.sleep(interval)
            continue
        for name, c in cams.items():
            if c.get("status") != "ok" or c.get("last_detect_latency_ms") is None:
                continue
            got += 1
            frame_age.append(float(c.get("last_frame_age_s") or 0) * 1000.0)
            detect_age.append(float(c.get("last_detect_age_s") or 0) * 1000.0)
            infer.append(float(c.get("infer_ms") or 0))
            lock_wait.append(float(c.get("lock_wait_ms") or 0))
            break
        time.sleep(interval)
    return {"samples": got, "frame_age_ms": frame_age, "infer_ms": infer,
            "lock_wait_ms": lock_wait, "detect_age_ms": detect_age}


# ---------------------------------------------------------------- B. 판정
def stage_b(cadence_s: float) -> dict:
    """실제 ZoneDebouncer 를 측정된 검출 주기로 구동 — raw True 시작 → 확정까지."""
    import zone_debounce

    enter = zone_debounce.enter_s()
    exit_ = zone_debounce.exit_s()

    # 가상시계로 구동하되 상태기계는 실제 코드다. 위상(offset)을 미세 스윕해
    # 최선·최악을 실제로 찾는다 — 표본 몇 개만 보면 최악을 놓친다.
    def judge(offset: float) -> float | None:
        db = zone_debounce.ZoneDebouncer()
        base = 1_000_000.0                      # 고정 기준시각(재현성)
        t_event = base + offset
        for k in range(400):
            t_detect = base + k * cadence_s
            if t_detect < t_event:
                db.update("m1", False, now=t_detect)
                continue
            if db.update("m1", True, now=t_detect):
                return (t_detect - t_event) * 1000.0
        return None

    steps = 200
    sweep = [(round(i * cadence_s / steps, 4), judge(i * cadence_s / steps))
             for i in range(steps + 1)]
    vals = [v for _, v in sweep if v is not None]
    best = min(sweep, key=lambda x: (x[1] is None, x[1]))
    worst = max(sweep, key=lambda x: (x[1] is None, x[1] or -1))
    return {"enter_s": enter, "exit_s": exit_, "cadence_s": cadence_s,
            "sweep_points": steps + 1,
            "best": {"offset_s": best[0], "judge_ms": round(best[1], 1)},
            "worst": {"offset_s": worst[0], "judge_ms": round(worst[1], 1)},
            "median_ms": round(st.median(vals), 1),
            "theory_worst_ms": round((enter + cadence_s) * 1000.0, 1)}


# ---------------------------------------------------------------- C. 기록
def stage_c(reps: int = 12) -> dict:
    """증거 인코딩(비식별화+JPEG) + 이벤트 로그 디스크 기록 — 임시 폴더로 격리."""
    import data_engine
    import worker as W

    tmp = Path(tempfile.mkdtemp(prefix="m1_rec_"))
    data_engine._ROOT = tmp                       # noqa: SLF001  상대경로 계산 기준도 함께 옮긴다
    data_engine._EVIDENCE = tmp / "evidence"      # noqa: SLF001  측정 격리
    data_engine._RECOG = tmp / "recognition"      # noqa: SLF001
    data_engine._PINNED = tmp / "evidence" / "pinned.json"  # noqa: SLF001

    rng = np.random.default_rng(20260820)
    frame = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
    pboxes = [[0.30, 0.20, 0.50, 0.80]]

    enc, log = [], []
    for _ in range(reps):
        t = time.perf_counter()
        url = W._frame_to_dataurl(frame, pboxes)   # noqa: SLF001
        enc.append((time.perf_counter() - t) * 1000.0)
        t = time.perf_counter()
        data_engine.log_event(rule="zone_intrusion", level="high", site="m1",
                              note="M1 측정", image_data_url=url)
        log.append((time.perf_counter() - t) * 1000.0)
    return {"encode_ms": enc, "logwrite_ms": log, "tmpdir": str(tmp)}


# ---------------------------------------------------------------- D. 전송
class _Mock(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):  # 조용히
        return


def stage_d(reps: int = 12) -> dict:
    """dispatcher.dispatch() 실측 — mock 웹훅 + 임시 큐 DB. 실채널 전송시간은 미측정."""
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    import alert_queue
    tmpdb = Path(tempfile.mkdtemp(prefix="m1_q_")) / "alert_queue.db"
    alert_queue._DB_PATH = tmpdb      # noqa: SLF001  측정 격리(실 큐 미사용)
    alert_queue._conn = None          # noqa: SLF001

    import agents.dispatcher as D
    from agents.dispatcher import DispatcherAgent

    orig = D.notify_cfg
    D.notify_cfg = lambda: {"telegram_token": "", "telegram_chat": "", "smtp_host": "",
                            "smtp_port": 0, "smtp_user": "", "smtp_pass": "", "email_to": "",
                            "webhook_url": f"http://127.0.0.1:{port}/hook"}
    try:
        class _Cfg:                       # 배포 기본값과 같은 등급 배선(high = alarm+manager_call)
            raw = {"dispatch": {"on_severity": {
                "critical": ["alarm", "manager_call", "safety_relay_signal"],
                "high": ["alarm", "manager_call"], "medium": ["log"]}}}

        agent = DispatcherAgent(_Cfg())
        queue_ms, total_ms, delivered = [], [], 0
        for i in range(reps):
            t = time.perf_counter()
            rid = alert_queue.enqueue("high", f"m1-{i}", None)
            queue_ms.append((time.perf_counter() - t) * 1000.0)
            alert_queue.mark_sent(rid)
            t = time.perf_counter()
            res = agent.dispatch("high", f"M1 지연 측정 {i}")
            total_ms.append((time.perf_counter() - t) * 1000.0)
            delivered += 1 if res.get("delivered") else 0
        return {"enqueue_ms": queue_ms, "dispatch_ms": total_ms,
                "delivered": delivered, "reps": reps, "port": port}
    finally:
        D.notify_cfg = orig
        srv.shutdown()


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=60)
    a = ap.parse_args()

    print(f"[A] 라이브 실카메라 {a.samples}회 폴링 …", flush=True)
    A = stage_a(a.samples)
    if A["samples"] < 5:
        print("★실카메라 표본 부족 — 서비스/카메라 상태 확인 필요", flush=True)
    # 검출 주기 추정: detect_age(마지막 검출 후 경과)를 무작위 시점에 재면 U(0,T) 이므로
    # 관측 최대값이 주기 T 의 하한 추정치다. 설정값(worker.fullset_fps)과 교차 확인한다.
    import tuning as _t
    cfg_cad = 1.0 / max(0.2, float(_t.val("worker", "fullset_fps", 2)))
    obs_cad = (max(A["detect_age_ms"]) / 1000.0) if A["detect_age_ms"] else cfg_cad
    cad = max(obs_cad, cfg_cad)

    print(f"[B] 판정 디바운스 (검출주기 {cad:.2f}s 가정) …", flush=True)
    B = stage_b(cad)
    print("[C] 증거 인코딩·기록 (임시 폴더) …", flush=True)
    C = stage_c()
    print("[D] 경보 큐·전송 (mock 웹훅, 임시 DB) …", flush=True)
    D = stage_d()

    out = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "A": A, "B": B, "C": C, "D": D,
           "cadence_s": cad, "cadence_observed_s": obs_cad, "cadence_config_s": cfg_cad}
    p = ROOT / "benchmarks" / "m1_alert_latency_result.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n===== 요약 =====")
    for k, lbl in (("frame_age_ms", "캡처 신선도"), ("infer_ms", "검출(추론)"),
                   ("lock_wait_ms", "락 대기"), ("detect_age_ms", "검출 경과")):
        v = A[k]
        if v:
            print(f"A {lbl:12} p50 {st.median(v):7.1f}ms  p95 {pct(v,95):7.1f}ms  n={len(v)}")
    print(f"B 판정 디바운스 enter_s={B['enter_s']}s · 검출주기 {cad:.2f}s "
          f"(관측 {obs_cad:.2f}s / 설정 {cfg_cad:.2f}s)")
    print(f"    최선 {B['best']['judge_ms']}ms (위상 +{B['best']['offset_s']}s) · "
          f"중앙 {B['median_ms']}ms · 최악 {B['worst']['judge_ms']}ms "
          f"(위상 +{B['worst']['offset_s']}s) · 이론 최악 {B['theory_worst_ms']}ms")
    print(f"C 증거 인코딩  p50 {st.median(C['encode_ms']):7.1f}ms  p95 {pct(C['encode_ms'],95):7.1f}ms")
    print(f"C 로그 기록    p50 {st.median(C['logwrite_ms']):7.1f}ms  p95 {pct(C['logwrite_ms'],95):7.1f}ms")
    print(f"D 큐 등록      p50 {st.median(D['enqueue_ms']):7.1f}ms")
    print(f"D 전송(mock)   p50 {st.median(D['dispatch_ms']):7.1f}ms  p95 {pct(D['dispatch_ms'],95):7.1f}ms "
          f"· delivered {D['delivered']}/{D['reps']}")
    print(f"\n원자료: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
