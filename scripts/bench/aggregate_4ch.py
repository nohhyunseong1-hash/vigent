#!/usr/bin/env python3
"""aggregate_4ch.py — 4채널 벤치 반복 실행(N회)을 한 표로 모은다. [I-3]

입력: audit/bench4ch_<태그>_r<i>_<시각>{.csv,_raw.csv,_meta.json}
  (서버 자원은 pilot_load_test.py 의 proc 값 — I-2 검증 후 별도 샘플러는 제거했다)
출력: 표(stdout) + audit/bench4ch_<태그>_summary.json

★판정 창: 첫 창(예열 직후)·마지막 창(철수)을 뺀다. 원시에는 남아 있다.
★추론 p50/p95/p99 는 **원시 샘플(_raw.csv)** 에서 직접 구한다 — 창별 p95 의 p95 가 아니다.
★"3회 편차" = 회차별 값의 최소~최대와 표준편차. 1회 값으로 결론 내지 않는다.

사용: python scripts/bench/aggregate_4ch.py --tag gpu2_torch
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def fnum(x: Any) -> float | None:
    try:
        return float(x) if x not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def one_run(meta_path: Path) -> dict[str, Any]:
    m = json.loads(meta_path.read_text(encoding="utf-8"))
    out: dict[str, Any] = {"tag": m["tag"], "stamp": m["stamp"], "backend_from_log": m.get("backend_from_log"),
                           "ready_s": (m.get("startup") or {}).get("ready_s"),
                           "warmup_s": (m.get("startup") or {}).get("warmup_s_reported"),
                           "first_inference_s": (m.get("first_inference") or {}).get("first_inference_s")}
    # 창 집계 CSV → 판정 창(첫·마지막 제외)
    rows = list(csv.DictReader(Path(m["csv"]).open(encoding="utf-8-sig")))
    judge = rows[1:-1] if len(rows) >= 3 else rows
    out["windows_total"], out["windows_judged"] = len(rows), len(judge)
    cams = sorted({k.split(".")[0] for r in rows for k in r if k.startswith("pilot")})
    sys_cpu = [fnum(r["sys_cpu_pct"]) for r in judge]
    out["sys_cpu_avg"] = round(st.mean([x for x in sys_cpu if x is not None]), 1) if any(x is not None for x in sys_cpu) else None
    out["sys_cpu_max"] = max([x for x in sys_cpu if x is not None], default=None)
    ages = [fnum(r.get(f"{c}.age_p95")) for r in judge for c in cams]
    oks = [fnum(r.get(f"{c}.age_ok_ratio")) for r in judge for c in cams]
    out["age_p95_worst"] = max([x for x in ages if x is not None], default=None)
    out["age_ok_min"] = min([x for x in oks if x is not None], default=None)
    lat = [fnum(r.get("alerts_latency_p95")) for r in judge]
    out["alert_p95_max"] = max([x for x in lat if x is not None], default=None)
    out["alerts_created"] = sum(int(fnum(r.get("alerts_created")) or 0) for r in judge)
    vram = [fnum(r.get("vram_used_mb")) for r in rows]
    out["vram_smi_max_mb"] = max([x for x in vram if x is not None], default=None)
    # 원시 샘플 → 추론 분위수(판정 창 시간 범위로 자르지 않고 전체; 예열 창은 age 로 걸러진다)
    raw = Path(m["raw_csv"])
    dms: list[float] = []
    if raw.exists():
        for r in csv.DictReader(raw.open(encoding="utf-8-sig")):
            v = fnum(r.get("detect_ms"))
            if v is not None and r.get("status") == "ok":
                dms.append(v)
    out["raw_n"] = len(dms)
    out["detect_p50"], out["detect_p95"], out["detect_p99"] = pct(dms, .5), pct(dms, .95), pct(dms, .99)
    # 서버 프로세스 자원 = pilot_load_test 의 proc 값(포트 점유 PID 기준 트리 합산) — JSONL 에서
    tool_cores, tool_rss, gpu_alloc, gpu_res = [], [], [], []
    jl = Path(m["jsonl"])
    if jl.exists():
        for line in jl.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if rec.get("phase") != "soak":
                continue
            pr = rec.get("proc") or {}
            if fnum(pr.get("server_cores")) is not None:
                tool_cores.append(float(pr["server_cores"]))
            if fnum(pr.get("rss_mb")) is not None:
                tool_rss.append(float(pr["rss_mb"]))
            gm = rec.get("gpu_mem") or {}
            if fnum(gm.get("allocated_mb")) is not None:
                gpu_alloc.append(float(gm["allocated_mb"]))
            if fnum(gm.get("reserved_mb")) is not None:
                gpu_res.append(float(gm["reserved_mb"]))
    out["tool_cores_avg"] = round(st.mean(tool_cores), 2) if tool_cores else None
    out["tool_rss_avg_mb"] = round(st.mean(tool_rss), 0) if tool_rss else None
    out["torch_alloc_max_mb"] = max(gpu_alloc, default=None)
    out["torch_reserved_max_mb"] = max(gpu_res, default=None)
    return out


def spread(vals: list[float | None]) -> str:
    xs = [v for v in vals if v is not None]
    if not xs:
        return "—"
    if len(xs) == 1:
        return f"{xs[0]}"
    return f"{min(xs)} ~ {max(xs)} (sd {st.pstdev(xs):.2f})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    # --repeat 1 이면 태그에 _r<i> 가 안 붙는다 — 둘 다 받는다(0건이면 아래서 실패로 드러난다)
    metas = sorted((_ROOT / "audit").glob(f"bench4ch_{a.tag}_r*_meta.json")) or \
        sorted((_ROOT / "audit").glob(f"bench4ch_{a.tag}_[0-9]*_meta.json"))
    if not metas:
        print("메타 파일이 없다 — 0건은 성공이 아니다"); return 1
    runs = [one_run(p) for p in metas]
    keys = [("sys_cpu_avg", "시스템 CPU 창평균 %"), ("sys_cpu_max", "시스템 CPU 창평균 최대 %"),
            ("age_p95_worst", "검출 age p95 최악 s"), ("age_ok_min", "age ok 비율 최소"),
            ("alert_p95_max", "경보 p95 최대 s"), ("detect_p50", "추론 p50 ms(원시)"),
            ("detect_p95", "추론 p95 ms(원시)"), ("detect_p99", "추론 p99 ms(원시)"),
            ("raw_n", "원시 샘플 수"), ("tool_cores_avg", "서버 환산코어(트리 합산)"),
            ("tool_rss_avg_mb", "서버 RSS MB(트리 합산)"), ("vram_smi_max_mb", "VRAM nvidia-smi 최대 MB"),
            ("torch_alloc_max_mb", "VRAM torch allocated 최대 MB"), ("torch_reserved_max_mb", "VRAM torch reserved 최대 MB"),
            ("ready_s", "기동→ready s"), ("first_inference_s", "기동→첫 정상 추론 s")]
    hdr = "| 지표 | " + " | ".join(r["tag"] for r in runs) + " | 편차(min~max, sd) |"
    print(hdr); print("|" + "---|" * (len(runs) + 2))
    for k, label in keys:
        vals = [r.get(k) for r in runs]
        print(f"| {label} | " + " | ".join("—" if v is None else str(v) for v in vals) + f" | {spread(vals)} |")
    print()
    for r in runs:
        print(f"- {r['tag']}: 백엔드(로그) = {r['backend_from_log']}")
    out = _ROOT / "audit" / f"bench4ch_{a.tag}_summary.json"
    out.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n요약 저장: {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
