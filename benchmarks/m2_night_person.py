"""[M2] 야간·저조도 person 검출 측정 — 실카메라, 실서비스 파이프라인.

설계: 한 구간(window) 동안 **사람이 화면에 계속 있다**고 사람이 선언하면(`--person`),
그 구간의 정답은 "매 검출마다 person 1명 이상"이 된다 → 검출된 검출회차 비율 = 재현율.
`--no-person` 구간은 정답이 "사람 없음"이므로 person 검출은 전부 오탐이다.

조도계가 없으므로 **화면 밝기 통계(대체 지표)** 를 함께 남긴다 — 조건 간 비교는 가능하다.

실행 예:
  python benchmarks/m2_night_person.py --label "야간_조명on" --person --seconds 120
  python benchmarks/m2_night_person.py --label "야간_소등"  --person --seconds 120
  python benchmarks/m2_night_person.py --label "야간_무인"  --no-person --seconds 120

★실카메라를 건드리지 않는다 — `/cameras/{cid}/detections` 와 `/snapshot` 을 읽기만 한다.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "benchmarks" / "m2_night_result.json"


def token() -> str:
    p = ROOT / ".env"
    if not p.exists():
        return ""
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("VIGENT_API_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def brightness(jpg: bytes) -> dict | None:
    """스냅샷 밝기 통계 — 조도계 대체 지표(0~255)."""
    import cv2
    arr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        return None
    v = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)[:, :, 2]
    hist = np.histogram(v, bins=8, range=(0, 256))[0]
    return {"mean": round(float(v.mean()), 1), "median": float(np.median(v)),
            "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
            "std": round(float(v.std()), 1),
            "dark_ratio": round(float((v < 40).mean()), 3),   # 거의 검은 픽셀 비율
            "hist8": [int(x) for x in hist]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="조건 이름(예: 야간_조명on)")
    ap.add_argument("--cid", default="test")
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--interval", type=float, default=1.0)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--person", action="store_true", help="구간 내내 사람이 화면에 있다")
    g.add_argument("--no-person", dest="noperson", action="store_true", help="사람 없음")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    h = {"Authorization": f"Bearer {token()}"}
    det_url = f"{BASE}/cameras/{a.cid}/detections"
    snap_url = f"{BASE}/cameras/{a.cid}/snapshot"

    rounds, confs, bright = [], [], []
    seen_det_ts: set = set()
    t_end = time.time() + a.seconds
    print(f"[{a.label}] {a.seconds}초 관찰 시작 — 정답: "
          f"{'사람 있음' if a.person else '사람 없음'}", flush=True)

    while time.time() < t_end:
        try:
            r = requests.get(det_url, headers=h, timeout=8)
            d = r.json() if r.ok else {}
        except Exception:  # noqa: BLE001
            time.sleep(a.interval)
            continue
        ts = d.get("ts") or d.get("t") or time.time()
        dets = d.get("detections") or []
        if ts not in seen_det_ts:                 # 같은 검출 회차 중복 집계 방지
            seen_det_ts.add(ts)
            persons = [x for x in dets
                       if str(x.get("label") or x.get("class") or "").lower() == "person"]
            sc = [float(x.get("score") if x.get("score") is not None else x.get("conf") or 0)
                  for x in persons]
            rounds.append({"ts": ts, "n_person": len(persons),
                           "max_conf": max(sc) if sc else 0.0})
            confs += sc
        if len(bright) < 12 and len(rounds) % 5 == 1:
            try:
                s = requests.get(snap_url, headers=h, timeout=15)
                if s.ok and s.content[:2] == b"\xff\xd8":
                    b = brightness(s.content)
                    if b:
                        bright.append(b)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(a.interval)

    n = len(rounds)
    hit = sum(1 for r in rounds if r["n_person"] > 0)
    res = {
        "label": a.label, "note": a.note,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gt_person_present": bool(a.person),
        "seconds": a.seconds, "detect_rounds": n,
        "rounds_with_person": hit,
        "rate": round(hit / n, 4) if n else None,
        "conf_n": len(confs),
        "conf_p50": round(st.median(confs), 3) if confs else None,
        "conf_mean": round(st.fmean(confs), 3) if confs else None,
        "conf_min": round(min(confs), 3) if confs else None,
        "conf_max": round(max(confs), 3) if confs else None,
        "brightness_samples": bright,
        "brightness_mean": round(st.fmean([b["mean"] for b in bright]), 1) if bright else None,
        "dark_ratio_mean": round(st.fmean([b["dark_ratio"] for b in bright]), 3) if bright else None,
    }

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    old.append(res)
    OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")

    kind = "재현율(사람 있음)" if a.person else "오탐률(사람 없음)"
    print(f"\n=== {a.label} ===")
    print(f"  검출 회차 {n}회 · person 잡힌 회차 {hit}회 → {kind} "
          f"{res['rate']*100 if res['rate'] is not None else float('nan'):.1f}%")
    if confs:
        print(f"  conf  p50 {res['conf_p50']}  평균 {res['conf_mean']}  "
              f"범위 {res['conf_min']}~{res['conf_max']}  (n={len(confs)})")
    else:
        print("  conf  — (person 검출 0)")
    if bright:
        print(f"  화면밝기 평균 {res['brightness_mean']}/255 · "
              f"어두운픽셀 비율 {res['dark_ratio_mean']}")
    print(f"\n누적 원자료: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
