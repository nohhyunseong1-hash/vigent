#!/usr/bin/env python3
"""[B3] 재연결 내성 재현·검증 — 카메라 끊김 후 검출이 자동으로 살아나는가.

합격 기준(지시서): 카메라 전원 30초 차단 → **복구 후 60초 안에** last_detect_age 가 다시
5초 미만이면 PASS.

두 가지 모드:
  --simulate : 카메라 전원을 못 건드릴 때. go2rtc 로 슬롯을 선점해 **기아 상황 자체를 재현**한다
               (원인분석 audit/b3_root_cause_2026-08-16.md §2 — 여유 0 상태에서 슬롯 경쟁).
  --live     : 실카메라 전원 차단. 안내 문구를 출력하고 사람이 끄고 켜는 동안 계속 측정한다.

두 모드 모두 /health(B2) 의 카메라 상태를 신뢰의 근거로 쓴다 — stale_detect 가 잡히는지,
그리고 복구되는지.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"
PASS_DETECT_AGE = 5.0        # 이 값 미만이면 검출 정상
RECOVER_LIMIT_S = 60.0       # 복구 제한시간


def health() -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)
    except Exception:  # noqa: BLE001  서버 재기동 중일 수 있다
        return 0, {}


def cam(h: dict, cid: str) -> dict:
    return (h.get("cameras") or {}).get(cid) or {}


def line(t: float, code: int, h: dict, cid: str) -> str:
    c = cam(h, cid)
    return (f"  t={t:6.1f}s HTTP {code or '---'} {str(h.get('status')):<10} "
            f"cam={str(c.get('status')):<13} frame={c.get('last_frame_age_s')} "
            f"detect={c.get('last_detect_age_s')}")


def camera_sessions(host: str) -> int:
    try:
        out = subprocess.check_output(["netstat", "-ano"]).decode(errors="replace")
        return len([x for x in out.splitlines() if f"{host}:554" in x and "ESTABLISHED" in x])
    except Exception:  # noqa: BLE001
        return -1


def wait_recover(cid: str, t0: float, limit: float, host: str | None = None) -> tuple[bool, float]:
    """검출이 다시 살아날 때까지 폴링. (성공여부, 소요초)"""
    while time.time() - t0 < limit:
        code, h = health()
        c = cam(h, cid)
        da = c.get("last_detect_age_s")
        extra = f" 세션={camera_sessions(host)}" if host else ""
        print(line(time.time() - t0, code, h, cid) + extra, flush=True)
        if da is not None and da < PASS_DETECT_AGE:
            return True, round(time.time() - t0, 1)
        time.sleep(3)
    return False, round(time.time() - t0, 1)


def run_live(cid: str, rounds: int, host: str) -> int:
    results = []
    for i in range(1, rounds + 1):
        print(f"\n=== {i}/{rounds} 회차 ===", flush=True)
        code, h = health()
        print("[사전]", line(0, code, h, cid), flush=True)
        print(f"\n>>> 지금 카메라 전원을 끄고 30초 후 켜 주세요. (회차 {i}/{rounds})", flush=True)
        input(">>> 다시 켰으면 Enter: ")
        t0 = time.time()
        ok, secs = wait_recover(cid, t0, RECOVER_LIMIT_S, host)
        results.append((i, ok, secs))
        print(f"--- {i}회차: {'PASS' if ok else 'FAIL'} (복구 {secs}s)", flush=True)
    print("\n=== 결과 ===")
    for i, ok, secs in results:
        print(f"  {i}회차: {'PASS' if ok else 'FAIL'} · 복구 {secs}s")
    npass = sum(1 for _, ok, _ in results if ok)
    print(f"\n종합: {npass}/{len(results)} PASS")
    return 0 if npass == len(results) else 1


def run_simulate(cid: str, host: str) -> int:
    """go2rtc 로 슬롯을 선점해 기아를 재현하고, 2차 방어가 회수하는지 본다."""
    print("[시뮬] go2rtc 소비자를 붙여 카메라 슬롯을 점유한다(여유 0 상태 재현)", flush=True)
    import threading
    stop = threading.Event()

    def consumer():
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:1984/api/stream.mp4?src={cid}", timeout=30)
            while not stop.is_set():
                if not r.read(8192):
                    break
            r.close()
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=consumer, daemon=True).start()
    time.sleep(5)
    print(f"  현재 카메라 세션: {camera_sessions(host)} (한도 2)", flush=True)
    t0 = time.time()
    ok, secs = wait_recover(cid, t0, RECOVER_LIMIT_S, host)
    stop.set()
    print(f"\n시뮬 결과: {'PASS' if ok else 'FAIL'} — 검출 {'유지/복구' if ok else '정지'} ({secs}s)")
    print("  ※ 시뮬은 '슬롯 경쟁 중에도 검출이 살아있는가'만 본다. 전원차단 시나리오는 --live 로.")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cid", default="test", help="카메라 id")
    ap.add_argument("--host", default="192.168.0.4", help="카메라 IP(세션 카운트용)")
    ap.add_argument("--live", action="store_true", help="실카메라 전원차단 시험")
    ap.add_argument("--rounds", type=int, default=3, help="live 반복 횟수")
    ap.add_argument("--simulate", action="store_true", help="슬롯 선점 시뮬레이션")
    a = ap.parse_args()

    code, h = health()
    if not h:
        print("서버 응답 없음 — 먼저 서버를 기동하세요")
        return 2
    print("[현재]", line(0, code, h, a.cid))

    if a.live:
        return run_live(a.cid, a.rounds, a.host)
    if a.simulate:
        return run_simulate(a.cid, a.host)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
