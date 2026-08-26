#!/usr/bin/env python3
"""[D1-C] 채택안 재생 검증 — 현행 vs C안을 같은 실데이터로 나란히 돌린다.

★고정하는 계약 3가지(2026-08-24 사용자 지시):
  1) C 적용 후 **알림 수 = 현행과 동일**   (폭주 위험 0)
  2) **두 번째 사람 진입이 이벤트·증거로 기록**  (미검출 해소)
  3) **증거 쿨다운(30초)이 디스크 폭주를 막는다**

★재생 시 주의: `_derive` 안의 디바운서는 **벽시계**를 쓴다. 907프레임을 1초 만에 처리하면
  유예(기본 1.0초)를 못 넘겨 아무것도 발화하지 않는다 — 반드시 **영상 시각을 주입**해야 한다
  (이 스크립트가 zone_debounce.time.time 을 가상 시계로 바꾼다).

사용:  python benchmarks/d1c_replay_verify.py [--data data/track_debug.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import alert_gate  # noqa: E402
import worker as W  # noqa: E402
import zone_debounce  # noqa: E402

# 실제 사람 동선(x 0.20~0.40 · 하단)에 맞춘 시험 구역 — 양쪽에 **똑같이** 쓴다(공정 비교).
ZONE = [(0.20, 0.90), (0.40, 0.90), (0.40, 1.01), (0.20, 1.01)]
COOLDOWN_S, EVIDENCE_CD_S = 15.0, 30.0


def _run(rows, t0, track_scoped: bool):
    clock = {"t": 0.0}
    alert_gate.reset()
    db = zone_debounce.ZoneDebouncer()
    cd: dict[str, float] = {}
    evcd: dict[str, float] = {}
    fires = notifs = evid = 0
    with mock.patch.object(zone_debounce.time, "time", lambda: clock["t"]):
        for r in rows:
            clock["t"] = vt = r["t"] / 1000.0 - t0
            dets = [{"label": t.get("label"), "conf": 0.9,
                     "bbox": t.get("bbox"), "tid": t.get("tid")} for t in r.get("tracks", [])]
            if not track_scoped:            # 현행 흉내 — tid 를 지워 집계 판정 경로로 보낸다
                for d in dets:
                    d.pop("tid", None)
            out = {"detections": dets, "signals": {},
                   "person_count": sum(1 for d in dets if d["label"] == "person")}
            for rule, lv, _note, subj in W._derive(out, ZONE, None, cid="cam", debouncer=db):
                if rule != "zone_intrusion":
                    continue
                ck = f"{rule}|{subj}" if subj else rule
                if vt - cd.get(ck, -1e9) < COOLDOWN_S:
                    continue
                cd[ck] = vt
                fires += 1
                if vt - evcd.get(rule, -1e9) >= EVIDENCE_CD_S:   # 증거는 **규칙 단위**(디스크 보호)
                    evcd[rule] = vt
                    evid += 1
                if alert_gate.decide("cam", "zone_intrusion", lv, now=vt)["notify"]:
                    notifs += 1
    return fires, evid, notifs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/track_debug.jsonl")
    args = ap.parse_args()
    f = _ROOT / args.data
    if not f.exists():
        print(f"데이터 없음: {args.data}")
        return 2
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    t0 = rows[0]["t"] / 1000.0
    dur = (rows[-1]["t"] - rows[0]["t"]) / 1000.0 / 60.0
    a, c = _run(rows, t0, False), _run(rows, t0, True)

    print(f"\n★재생 검증 — {args.data} ({dur:.1f}분, {len(rows)}프레임)\n")
    print(f"{'':<22}{'이벤트기록':>11}{'증거JPEG':>10}{'폰알림':>8}")
    print(f"{'현행(집계 판정)':<22}{a[0]:>11}{a[1]:>10}{a[2]:>8}")
    print(f"{'C안(사람 단위)':<22}{c[0]:>11}{c[1]:>10}{c[2]:>8}")
    ok1, ok2, ok3 = c[2] == a[2], c[0] > a[0], c[1] < c[0]
    print(f"\n계약1) 알림 = 현행 동일     : {'✅' if ok1 else '❌'}  ({a[2]} → {c[2]})")
    print(f"계약2) 기록 증가(미검출 해소): {'✅' if ok2 else '❌'}  ({a[0]} → {c[0]})")
    print(f"계약3) 증거 스로틀 작동     : {'✅' if ok3 else '❌'}  (기록 {c[0]} 대비 증거 {c[1]})")
    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    raise SystemExit(main())
