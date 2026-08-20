#!/usr/bin/env python3
"""[S0] 실카메라 24시간 소크 기록기 — /health 를 60초마다 남긴다.

배경(audit/site_readiness_2026-08-16.md 🟠C4): 지금까지 24h 소크는 **파일 소스**로만 통과했고
(`audit/soakmon_2026-08-11_s3edge24h`), 실카메라 최장 기록은 30분이었다. 무인 24시간 운영을
파는 제품이 정작 실카메라로 24시간을 돌아본 적이 없다.

★소크 대상(서비스)에 영향을 주지 않기 위해 **별개 프로세스**로 돌고, /health 를 읽기만 한다.
  소크 중에는 서비스를 재시작하지 말 것 — 재시작하면 그 시점까지의 결과가 무효가 된다.

기록 항목(1행 = 1샘플, JSONL):
  status·phase / 카메라별 frame·detect age·재연결·hang / 미전송 경보 / 서버 RSS / GPU 메모리

사용:
    python scripts/soak_realcam.py                # 24시간(기본)
    python scripts/soak_realcam.py --hours 1      # 짧게 시험
결과 분석:
    python scripts/soak_report.py audit/soak_realcam_<시작일시>.jsonl
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
import sys

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"


def health() -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception:  # noqa: BLE001  서버 무응답도 기록 대상(장애 신호)
        return 0, {}


def server_pid() -> int | None:
    try:
        out = subprocess.check_output(["netstat", "-ano"]).decode(errors="replace")
        for line in out.splitlines():
            if "0.0.0.0:8010" in line and "LISTENING" in line:
                return int(line.split()[-1])
    except Exception:  # noqa: BLE001
        pass
    return None


def rss_mb(pid: int | None) -> float | None:
    if pid is None:
        return None
    try:
        import psutil
        return round(psutil.Process(pid).memory_info().rss / 1048576, 1)
    except Exception:  # noqa: BLE001
        return None


def gpu_mb() -> int | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL).decode().strip().splitlines()
        return int(out[0])
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--interval", type=float, default=60.0)
    a = ap.parse_args()

    start = datetime.now()
    out = _ROOT / "audit" / f"soak_realcam_{start:%Y-%m-%d_%H%M}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    code0, h0 = health()
    pid = server_pid()
    base_rss = rss_mb(pid)
    header = {
        "_type": "header",
        "started_at": start.isoformat(timespec="seconds"),
        "ends_at": (start + timedelta(hours=a.hours)).isoformat(timespec="seconds"),
        "hours": a.hours,
        "interval_s": a.interval,
        "server_pid": pid,
        "baseline_rss_mb": base_rss,
        "baseline_gpu_mb": gpu_mb(),
        "start_health": {"code": code0, "status": h0.get("status"), "phase": h0.get("phase")},
        # ── 합격 기준(사전 선언) ─────────────────────────────────────────────
        "pass_criteria": {
            "unhealthy_samples": "0회 (status=unhealthy 가 한 번도 없어야 한다)",
            "degraded_minutes_max": 5,
            "auto_recovery_failures": "0 (stale 상태가 60초 넘게 지속된 뒤 스스로 회복하지 못한 경우)",
            "rss_growth_mb_per_hour_max": 30,
            "alerts_pending_at_end": 0,
        },
        "criteria_rationale": (
            "메모리 증가율 상한 30MB/h 근거: 기준선 RSS 약 3,179MB(모델 3종 상주). "
            "24시간에 720MB(기준선의 22%) 증가까지 허용하는 값으로, 파일 소스 24h 소크 실측 "
            "+0.46MB/h(audit/soakmon_2026-08-11_s3edge24h)보다 65배 여유가 있다. "
            "실카메라는 디코드·재연결 경로가 추가되므로 여유를 크게 뒀고, 이 값을 넘으면 "
            "'누수 의심'으로 판정해 조사 대상으로 삼는다. degraded 5분 상한은 카메라 순단 "
            "1~2회(복구 실측 6~50초)를 허용하되 만성적 저하는 불합격으로 보는 기준이다."
        ),
    }
    with out.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        f.flush()
        print(f"[소크 시작] {start:%Y-%m-%d %H:%M:%S}  →  종료 예정 {header['ends_at']}")
        print(f"  기록: {out}")
        print(f"  기준선 RSS {base_rss} MB / GPU {header['baseline_gpu_mb']} MiB / 서버 PID {pid}")

        t0 = time.time()
        n = 0
        while time.time() - t0 < a.hours * 3600:
            code, h = health()
            cams = {cid: {"s": c.get("status"), "f": c.get("last_frame_age_s"),
                          "d": c.get("last_detect_age_s"), "rc": c.get("reconnects"),
                          "hg": c.get("hangs"), "gen": c.get("session_generation")}
                    for cid, c in (h.get("cameras") or {}).items()}
            rec = {
                "t": round(time.time() - t0, 1),
                "ts": datetime.now().isoformat(timespec="seconds"),
                "code": code,
                "status": h.get("status"),
                "phase": h.get("phase"),
                "cams": cams,
                "alerts": h.get("alerts") or {},
                "rss_mb": rss_mb(server_pid()),
                "gpu_mb": gpu_mb(),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            n += 1
            time.sleep(a.interval)

    print(f"[소크 종료] 샘플 {n}개 — 분석: python scripts/soak_report.py {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
