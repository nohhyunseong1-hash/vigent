"""build_webcam_labels.py — 파일명 태그 → labels.json (VIGENT-MAX Phase 0).

파일명 규칙(촬영 가이드):
  neg_<장면>_<num>.jpg          → 사람 없음. person=false, PPE=null.
  pos_<상태>_<거리>_<num>.jpg   → 사람 있음. person=true, distance=<거리>.
    상태: bare(맨몸) / hardhat / vest / mask / combo(안전모+조끼)
    거리: near / mid / far
GT presence(이미지수준, 박스좌표 없음). 상태→착용여부 매핑은 추측 없이 규칙표로.
실행: python3 benchmarks/build_webcam_labels.py [--raw <dir>] [--out <labels.json>]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_RAW = _ROOT / "data/datasets/webcam_bench/raw"

# 상태 태그 → 착용 상태(worn/none). 명시 규칙(추측 금지). combo=안전모+조끼 착용, 마스크는 none 기본.
_STATE = {
    "bare":    {"hardhat": "none", "vest": "none", "mask": "none"},
    "hardhat": {"hardhat": "worn", "vest": "none", "mask": "none"},
    "vest":    {"hardhat": "none", "vest": "worn", "mask": "none"},
    "mask":    {"hardhat": "none", "vest": "none", "mask": "worn"},
    "combo":   {"hardhat": "worn", "vest": "worn", "mask": "none"},
}
_DIST = {"near", "mid", "far"}


def parse(fname: str):
    stem = Path(fname).stem
    parts = stem.split("_")
    if parts[0] == "neg":
        return {"kind": "neg", "person": False, "hardhat": None, "vest": None, "mask": None,
                "distance": None, "scene": parts[1] if len(parts) > 1 else "unknown"}
    if parts[0] == "pos" and len(parts) >= 3:
        state, dist = parts[1], parts[2]
        if state not in _STATE:
            return {"kind": "pos", "person": True, "error": f"unknown state '{state}'"}
        if dist not in _DIST:
            return {"kind": "pos", "person": True, "error": f"unknown distance '{dist}'"}
        rec = {"kind": "pos", "person": True, "distance": dist}
        rec.update(_STATE[state])
        rec["state"] = state
        return rec
    return {"kind": "?", "error": f"파일명 규칙 불일치: {fname}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(_RAW))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    raw = Path(args.raw)
    out = Path(args.out) if args.out else raw.parent / "labels.json"

    labels, errors = {}, []
    kinds, states, dists = Counter(), Counter(), Counter()
    for p in sorted(raw.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        rec = parse(p.name)
        labels[p.name] = rec
        if rec.get("error"):
            errors.append(f"{p.name}: {rec['error']}")
        kinds[rec.get("kind")] += 1
        if rec.get("kind") == "pos":
            states[rec.get("state")] += 1
            dists[rec.get("distance")] += 1

    out.write_text(json.dumps(labels, ensure_ascii=False, indent=2))
    print(f"labels.json: {len(labels)}장 → {out}")
    print(f"  kind: {dict(kinds)}")
    print(f"  positive 상태: {dict(states)}")
    print(f"  positive 거리: {dict(dists)}")
    if errors:
        print(f"  ⚠️ 파일명 오류 {len(errors)}건:")
        for e in errors[:10]:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
