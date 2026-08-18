#!/usr/bin/env python3
"""[측정 위생] 외부 고부하 프로세스 감시 — 측정 오염을 자동 탐지한다.

배경: 2026-08-18 V2/V3 측정 도중 같은 PC 에서 게임(TslGame.exe)이 실행돼 수치가 무효가 됐다.
사후에 프로세스 시작 시각과 산출물 시각을 대조해서야 발견했다. 이번엔 **측정과 동시에** 감시한다.

★측정 프로세스 안에서 감시하지 않는 이유: psutil 전체 프로세스 열거 자체가 CPU 를 쓴다.
  측정 대상에 관측자 부하를 섞지 않으려고 **별도 프로세스**로 분리했다(샘플 간격도 길게).

출력: JSONL 한 줄 = 한 샘플. 측정 산출물의 t_start/t_end 와 대조해 구간별 오염 여부를 판정한다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import psutil

# 감시 대상에서 뺄 것: 나 자신 · 파이썬(측정 프로세스와 VIGENT 서비스) · 시스템 유휴
_SELF = os.getpid()
_IGNORE_NAMES = {"System Idle Process", "System", "Idle"}
THRESHOLD = 80.0          # 이 % 를 넘는 외부 프로세스를 '고부하'로 본다(코어 0.8개분)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "meas_watchdog.jsonl")
    interval = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    procs = {}
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent()
            procs[p.pid] = p
        except Exception:
            pass
    time.sleep(1.0)
    with out.open("w", encoding="utf-8") as f:
        while True:
            # 새로 뜬 프로세스도 잡는다(게임은 측정 도중 시작될 수 있다)
            for p in psutil.process_iter(["pid", "name"]):
                if p.pid not in procs:
                    try:
                        p.cpu_percent()
                        procs[p.pid] = p
                    except Exception:
                        pass
            hot = []
            dead = []
            for pid, p in procs.items():
                if pid == _SELF:
                    continue
                try:
                    name = p.name()
                    if name in _IGNORE_NAMES:
                        continue
                    c = p.cpu_percent()
                    if c >= THRESHOLD:
                        hot.append({"pid": pid, "name": name, "cpu": round(c, 1)})
                except Exception:
                    dead.append(pid)
            for pid in dead:
                procs.pop(pid, None)
            rec = {"t": time.time(), "sys_cpu": psutil.cpu_percent(),
                   "hot": sorted(hot, key=lambda x: -x["cpu"])[:6]}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
