"""track_debug 1분 샘플 점검 — person 이 실제로 기록되는지 현장에서 즉시 확인한다.

왜 필요한가: 2026-08-26 리허설에서 `data/track_debug.jsonl` 에 Hardhat 624건이 쌓였는데
person 은 0건이었다. 계측이 `_track_iou` 안에 있어 algo="bytetrack" 의 person 경로를
못 봤기 때문이다(guard._track 로 이동해 수정). 원인은 고쳤지만 **현장에서는 카메라 각도·
조명·거리 때문에도 같은 결과(person 0건)가 날 수 있다.** 20분을 붓기 전에 1분으로 거른다.

    python benchmarks/dbg_person_check.py [--data data/track_debug.jsonl] [--conf 0.6]

종료 코드: 0=수집 계속해도 좋음 / 1=중단하고 원인 확인.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/track_debug.jsonl")
    ap.add_argument("--conf", type=float, default=0.6,
                    help="고신뢰 기준 — 분석기(b_passthru_2fps_check.py)와 맞출 것")
    a = ap.parse_args()

    p = Path(a.data)
    if not p.exists():
        print(f"❌ 파일이 없다: {p}")
        print("   → VIGENT_TRACK_DEBUG=1 로 서비스가 재기동됐는지, 카메라가 돌고 있는지 확인.")
        return 1

    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not rows:
        print(f"❌ 기록이 비었다: {p}  → 카메라가 프레임을 못 받고 있다.")
        return 1

    span_s = (rows[-1]["t"] - rows[0]["t"]) / 1000.0
    n_person = n_high = 0
    labels: dict[str, int] = {}
    for r in rows:
        for f in r.get("fresh") or []:
            lb = str(f.get("label", ""))
            labels[lb] = labels.get(lb, 0) + 1
            if lb.lower() == "person":
                n_person += 1
                if float(f.get("conf", 0)) >= a.conf:
                    n_high += 1

    algo = rows[0].get("algo", "(미기록 — 구버전 데이터)")
    print(f"입력: {p}")
    print(f"  프레임 {len(rows)} · 구간 {span_s / 60:.1f}분 · 추적기 {algo}")
    print(f"  person 검출 {n_person}건 (그중 conf≥{a.conf} 고신뢰 {n_high}건)")
    top = sorted(labels.items(), key=lambda kv: -kv[1])[:5]
    print("  상위 라벨: " + ", ".join(f"{k} {v}" for k, v in top))

    if n_person == 0:
        print("\n❌ **중단하라** — person 이 0건이다. 20분을 부어도 판정 재료가 안 남는다.")
        print("   ① 카메라 화면에 사람이 실제로 보이는가")
        print("   ② /health 의 active_detectors 에 person 이 있는가")
        print("   ③ 스냅샷에 사람 박스가 그려지는가")
        print("   해결 안 되면 track_debug 는 포기하고 **녹화본 반출**로 대체한다.")
        return 1

    print("\n✅ **계속 수집하라** — person 이 담기고 있다.")
    if n_high == 0:
        print(f"   ⚠ 다만 conf≥{a.conf} 고신뢰가 0건이다 — 사람이 너무 작거나 어둡다.")
        print("     화각을 낮추거나 조명을 확인하면 판정 품질이 올라간다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
