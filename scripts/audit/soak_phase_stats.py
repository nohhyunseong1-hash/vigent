"""부하 키트(pilot_load_test.py) jsonl 두 개를 phase 별로 집계해 나란히 놓는다(읽기 전용).

사용: python scripts/audit/soak_phase_stats.py <1차.jsonl> <2차.jsonl> [--until-s N]
  --until-s N : 각 phase 에서 elapsed_s ≤ N 인 표본만 쓴다(끊긴 소크와 같은 구간 비교용).
출력: 마크다운 표(stdout). p95 는 최근접 순위법(nearest-rank: 정렬 후 ceil(0.95·n) 번째) — 보간 없음.
주의: 0.5초~10분 간격 표본은 서로 독립이 아니므로 신뢰구간은 내지 않는다(관측값만).
"""
import argparse
import json
import math
from collections import OrderedDict


def p95(v):
    s = sorted(v)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def fmt(v):
    if not v:
        return "표본 0"
    return f"n={len(v)} · 평균 {sum(v) / len(v):.2f} · p95 {p95(v):g} · 최대 {max(v):g}"


def load(path, until_s):
    phases = OrderedDict()
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if "sys_cpu_pct" not in r:  # header·cleanup 등 표본이 아닌 줄
            continue
        phases.setdefault(r["phase"], []).append(r)
    out = OrderedDict()
    for ph, rows in phases.items():
        t0 = rows[0]["elapsed_s"]
        if until_s is not None:
            rows = [r for r in rows if r["elapsed_s"] - t0 <= until_s]
        cams = [c for r in rows for c in r["health"]["cams"].values()]
        aw = [r["alerts_window"] for r in rows]
        # srv(서버 환산코어) = 이웃 표본 사이 proc.cpu_s 증가 ÷ 경과초. 키트가 .venv 실행기 PID 를 잡은 값이라 무효.
        srv = [(b["proc"]["cpu_s"] - a["proc"]["cpu_s"]) / (b["elapsed_s"] - a["elapsed_s"])
               for a, b in zip(rows, rows[1:]) if b["elapsed_s"] > a["elapsed_s"]]
        m = OrderedDict()
        m["구간(ts)"] = f"{rows[0]['ts'][11:]}~{rows[-1]['ts'][11:]} · 카메라 {sorted({r['n_cams'] for r in rows})}"
        m["sysCPU %"] = fmt([r["sys_cpu_pct"] for r in rows])
        m["CPU perf %"] = fmt([r["cpu_perf_pct"] for r in rows if r.get("cpu_perf_pct") is not None])
        m["srv 환산코어(★실행기 PID — 무효)"] = fmt(srv)
        m["RSS MB(★실행기 PID — 무효)"] = fmt([r["proc"]["rss_mb"] for r in rows])
        m["GPU util %"] = fmt([r["gpu"]["util"] for r in rows])
        m["GPU 메모리 MB"] = fmt([r["gpu"]["mem_used_mb"] for r in rows])
        m["GPU 온도 °C"] = fmt([r["gpu"]["temp_c"] for r in rows])
        m["GPU SM clk MHz"] = fmt([r["gpu"]["clock_sm"] for r in rows]) + f" · 최소 {min(r['gpu']['clock_sm'] for r in rows):g}"
        m["age_p95 s (카메라×표본)"] = fmt([c["age_p95"] for c in cams]) + f" · >1.0s {sum(1 for c in cams if c['age_p95'] > 1.0)}개"
        ok = [c["age_ok_ratio"] for c in cams]
        m["age≤0.55s 비율 (카메라×표본)"] = f"n={len(ok)} · 평균 {sum(ok) / len(ok):.3f} · 최소 {min(ok):g} · 0.9 미만 {sum(1 for o in ok if o < 0.9)}개"
        m["detect ms p95 (카메라×표본)"] = fmt([c["detect_ms_p95"] for c in cams])
        m["dropped/재연결/hang 합"] = "{}/{}/{}".format(*(sum(c[k] for c in cams) for k in ("dropped", "reconnects", "hangs")))
        lat = [a["latency_p95"] for a in aw if a.get("latency_p95") is not None]
        m["alerts 생성/전송 합"] = f"{sum(a.get('created', 0) for a in aw)}/{sum(a.get('sent', 0) for a in aw)} (경보 있는 표본 {len(lat)}/{len(aw)})"
        m["alerts 표본별 지연 p95 s"] = fmt(lat)
        m["deg 표본 합 cam/alert"] = f"{sum(r['health']['degraded_camera_samples'] for r in rows)}/{sum(r['health']['degraded_alert_samples'] for r in rows)}"
        m["가용 메모리 MB 최소"] = f"{min(r['proc']['sys_avail_mb'] for r in rows):g}"
        out[ph] = m
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("first")
    ap.add_argument("second")
    ap.add_argument("--until-s", type=float, default=None)
    a = ap.parse_args()
    A, B = load(a.first, a.until_s), load(a.second, a.until_s)
    for ph in list(OrderedDict.fromkeys(list(A) + list(B))):
        print(f"\n### phase = {ph}" + (f" (각 phase 시작 후 {a.until_s:g}s 이내 표본만)" if a.until_s is not None else ""))
        print("| 지표 | 1차 | 2차 |\n|---|---|---|")
        keys = list((A.get(ph) or B.get(ph)).keys())
        for k in keys:
            print(f"| {k} | {(A.get(ph) or {}).get(k, '구간 없음')} | {(B.get(ph) or {}).get(k, '구간 없음')} |")


if __name__ == "__main__":
    main()
