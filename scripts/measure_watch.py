#!/usr/bin/env python3
"""[측정 보조] capacity_probe 가 도는 동안 **오염·스로틀링**을 따로 기록한다.

capacity_probe 는 서비스 지표(검출 지연·GPU 메모리)만 본다. 그런데 노트북 측정은
두 가지가 결과를 조용히 망친다:
  1. **오염** — 브라우저·백신·업데이트가 CPU/GPU 를 훔쳐 한계 N 이 낮게 나온다
  2. **발열 스로틀링** — 데스크탑과 달리 노트북은 온도가 오르면 클럭을 스스로 낮춘다.
     이 경우 "이 기계의 한계"가 아니라 "이 온도에서의 한계"를 잰 것이 된다.
둘 다 기록해야 나중에 숫자를 믿을 수 있다.

사용: python scripts/measure_watch.py --minutes 45
      → audit/measure_watch_<시각>.csv / .md
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
_OUT = _ROOT / "audit"

# nvidia-smi 가 보고하는 클럭 제한 사유 — 스로틀링의 직접 증거
GPU_Q = ("utilization.gpu,memory.used,temperature.gpu,clocks.current.graphics,"
         "clocks_throttle_reasons.hw_thermal_slowdown,"
         "clocks_throttle_reasons.sw_thermal_slowdown,"
         "clocks_throttle_reasons.hw_power_brake_slowdown")


def gpu() -> list[str]:
    try:
        o = subprocess.run(["nvidia-smi", f"--query-gpu={GPU_Q}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15).stdout.strip()
        return [x.strip() for x in o.split(",")]
    except Exception:  # noqa: BLE001
        return ["", "", "", "", "", "", ""]


def cpu_pct() -> str:
    try:
        o = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             r"(Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 1)"
             ".CounterSamples[0].CookedValue"],
            capture_output=True, text=True, timeout=25).stdout.strip()
        return f"{float(o):.1f}"
    except Exception:  # noqa: BLE001
        return ""


def top_procs(n: int = 3) -> str:
    """CPU 를 실제로 쓰는 상위 프로세스(우리 것 제외하면 곧 '오염')."""
    try:
        o = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object {$_.CPU -ne $null} | Sort-Object CPU -Descending | "
             f"Select-Object -First {n} Name | ForEach-Object {{ $_.Name }}"],
            capture_output=True, text=True, timeout=25).stdout.split()
        return "|".join(o[:n])
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--interval", type=float, default=30.0)
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    _OUT.mkdir(exist_ok=True)
    csv = _OUT / f"measure_watch_{stamp}.csv"
    rows: list[dict] = []
    with csv.open("w", encoding="utf-8") as f:
        f.write("t,cpu_pct,gpu_util,gpu_mem_mb,gpu_temp_c,gpu_clock_mhz,"
                "hw_thermal,sw_thermal,power_brake,top_procs\n")
        end = time.time() + a.minutes * 60
        while time.time() < end:
            g = gpu()
            r = {"t": time.strftime("%H:%M:%S"), "cpu": cpu_pct(), "util": g[0], "mem": g[1],
                 "temp": g[2], "clk": g[3], "hwt": g[4], "swt": g[5], "pwr": g[6],
                 "top": top_procs()}
            rows.append(r)
            f.write(",".join([r["t"], r["cpu"], r["util"], r["mem"], r["temp"], r["clk"],
                              r["hwt"], r["swt"], r["pwr"], r["top"]]) + "\n")
            f.flush()
            print(f"  {r['t']}  CPU {r['cpu']}%  GPU {r['util']}%/{r['temp']}C  "
                  f"clk {r['clk']}MHz  thermal={r['hwt']}/{r['swt']}", flush=True)
            time.sleep(a.interval)

    def nums(key: str) -> list[float]:
        out = []
        for r in rows:
            try:
                out.append(float(r[key]))
            except (ValueError, TypeError):
                pass
        return out

    temps, clks, cpus = nums("temp"), nums("clk"), nums("cpu")
    throttled = [r for r in rows if "Active" in (r["hwt"] + r["swt"] + r["pwr"])]
    md = [f"# 측정 중 오염·스로틀링 감시 ({time.strftime('%Y-%m-%d %H:%M')})", "",
          f"- 샘플 {len(rows)}개 · {a.interval:.0f}초 주기",
          f"- **GPU 온도** min {min(temps) if temps else '?'} / max {max(temps) if temps else '?'} ℃",
          f"- **GPU 클럭** min {min(clks) if clks else '?'} / max {max(clks) if clks else '?'} MHz",
          f"- CPU 사용률 max {max(cpus) if cpus else '?'} %",
          f"- **스로틀링 관측: {len(throttled)}샘플**"
          + ("  ← 이 구간의 한계 N 은 '이 기계의 한계'가 아니라 '이 온도에서의 한계'다"
             if throttled else "  ← 없음. 측정 구간에서 클럭 제한 없음"), ""]
    if throttled:
        md += ["| 시각 | 온도 | 클럭 | HW열 | SW열 | 전력 |", "|---|---|---|---|---|---|"]
        md += [f"| {r['t']} | {r['temp']} | {r['clk']} | {r['hwt']} | {r['swt']} | {r['pwr']} |"
               for r in throttled[:20]]
    (_OUT / f"measure_watch_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n기록: audit/measure_watch_{stamp}.md  (csv 동봉)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
