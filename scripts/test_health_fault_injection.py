#!/usr/bin/env python3
"""[B2] 실서버 결함 주입 재현 — 검출만 멈췄을 때 /health 가 실제로 degraded 로 바뀌는가.

단위 테스트(tests/test_health_detect_alive.py)는 판정 로직만 검증한다. 이 스크립트는
**실행 중인 서버**에 결함을 주입해 워커 하트비트 → /health 배선이 실제로 이어져 있는지 본다.

동작:
  1. /health 로 현재 상태 확인(healthy 기대)
  2. 워커의 fault_stop_detect 를 켠다 → 프레임 수신은 유지되고 추론만 멈춤(= P0 재현)
  3. detect_stale_s(기본 30초)를 넘길 때까지 폴링하며 status 변화를 기록
  4. 결함 해제 → healthy 복귀 확인
  5. PASS/FAIL 출력

주의: 결함 주입은 **서버 프로세스 내부 객체**를 건드려야 하므로 이 스크립트는 서버와 같은
머신에서, 서버가 노출한 API 로만은 불가능하다 → 서버를 이 스크립트로 직접 띄우는 대신
`VIGENT_FAULT_STOP_DETECT=1` 환경변수로 기동한 서버를 대상으로 검증하는 방식을 쓴다.
사용법:
  1) 정상 기동한 서버에서:  python scripts/test_health_fault_injection.py --observe
     → 현재 /health 를 30초 관찰(정상 상태 기준선)
  2) 결함 주입 기동:        VIGENT_FAULT_STOP_DETECT=1 (서버 기동) 후
     python scripts/test_health_fault_injection.py --expect-stale
     → detect_stale_s 초과 후 degraded/stale_detect 로 바뀌면 PASS
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"


def _token() -> str:
    env = _ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("VIGENT_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def get_health() -> tuple[int, dict]:
    req = urllib.request.Request(BASE + "/health")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:      # 503(unhealthy)도 정상 응답이다
        return e.code, json.load(e)


def describe(code: int, h: dict) -> str:
    cams = h.get("cameras") or {}
    parts = [f"{cid}={c.get('status')}(f{c.get('last_frame_age_s')}/d{c.get('last_detect_age_s')})"
             for cid, c in cams.items()]
    return f"HTTP {code} status={h.get('status')} phase={h.get('phase')} | " + (", ".join(parts) or "카메라 없음")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--observe", action="store_true", help="현재 상태 30초 관찰(기준선)")
    ap.add_argument("--expect-stale", action="store_true",
                    help="검출 정지가 degraded/unhealthy 로 잡히는지 검증")
    ap.add_argument("--timeout", type=float, default=75.0, help="판정 대기 상한(초)")
    a = ap.parse_args()

    code, h = get_health()
    print("[시작]", describe(code, h), flush=True)

    if a.observe:
        t0 = time.time()
        while time.time() - t0 < 30:
            code, h = get_health()
            print(f"  t={time.time()-t0:5.1f}s", describe(code, h), flush=True)
            time.sleep(5)
        ok = h.get("status") == "healthy"
        print(f"\n결과: {'PASS' if ok else 'FAIL'} — 기준선 상태 {h.get('status')}")
        return 0 if ok else 1

    if a.expect_stale:
        t0 = time.time()
        seen = None
        while time.time() - t0 < a.timeout:
            code, h = get_health()
            cams = h.get("cameras") or {}
            stale = [cid for cid, c in cams.items() if c.get("status") == "stale_detect"]
            print(f"  t={time.time()-t0:5.1f}s", describe(code, h), flush=True)
            if stale and h.get("status") in ("degraded", "unhealthy"):
                seen = (h.get("status"), stale, round(time.time() - t0, 1), code)
                break
            time.sleep(5)
        if seen:
            st, stale, secs, code = seen
            print(f"\n결과: PASS — {secs}초 만에 status={st}, stale_detect={stale}, HTTP {code}")
            return 0
        print(f"\n결과: FAIL — {a.timeout}초 안에 stale_detect/degraded 가 나타나지 않음")
        return 1

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
