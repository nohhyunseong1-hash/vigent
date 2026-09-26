#!/usr/bin/env python3
"""scripts/eval/dev74_fair_compare.py — dev74(앱 파이프라인) PPE 재현율을 Mask/NO-Mask GT 를 **양쪽에서 제외**하고 v1 ↔ 후보를 같은 잣대로 비교. [2026-09-27 결정 ①]

5클래스 재학습본(Mask 제외 원칙)은 Mask 류를 설계상 검출하지 않으므로, 그 GT 를 포함한 재현율은 v1 에 유리하다. 제외한 값이 "실제 하락분"이다.
사용: python scripts/eval/dev74_fair_compare.py --cand runs/finetune/ppe_507_v2/ckpt/checkpoint_best_total.pth --label A [--out audit/dev74_fair_A.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "benchmarks")); sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from eval_v1_heldout import wilson  # noqa: E402

EXCL = frozenset({"Mask", "NO-Mask"})


def _row(label: str, r: dict) -> str:
    ci = wilson(r["ppe_tp"], r["ppe_gt"]) if r["ppe_gt"] else None
    nh = r["ppe_per_class"].get("NO-Hardhat", {})
    nhci = wilson(nh.get("tp", 0), nh.get("gt", 0)) if nh.get("gt") else None
    return (f"| {label} | {r['ppe_recall'] * 100:.1f} [{ci[0]}, {ci[1]}] ({r['ppe_tp']}/{r['ppe_gt']}) | {r['ppe_precision'] * 100:.1f} ({r['ppe_tp']}/{r['ppe_tp'] + r['ppe_fp']}) | "
            f"{(nh.get('tp', 0) / nh['gt'] * 100) if nh.get('gt') else 0:.1f} [{nhci[0]}, {nhci[1]}] ({nh.get('tp', 0)}/{nh.get('gt', 0)}) |") if nhci else f"| {label} | - |"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", required=True); ap.add_argument("--label", default="cand"); ap.add_argument("--out", default="")
    a = ap.parse_args()
    import x4b_score_candidates as x4b
    res = {"date": time.strftime("%Y-%m-%d %H:%M"), "excluded": sorted(EXCL), "cand": a.cand, "label": a.label}
    for key, w in (("v1_all", None), ("v1_noMask", None), (f"{a.label}_all", a.cand), (f"{a.label}_noMask", a.cand)):
        t0 = time.time(); r = x4b.score_one(w, EXCL if key.endswith("noMask") else frozenset()); r["elapsed_s"] = round(time.time() - t0, 1)
        res[key] = r; print(f"  {key}: R {r['ppe_recall'] * 100:.1f} ({r['ppe_tp']}/{r['ppe_gt']}) P {r['ppe_precision'] * 100:.1f} · {r['elapsed_s']}s", flush=True)
    print("\n| 행(dev74, 앱 파이프라인) | PPE 재현율 [W95] (tp/gt) | PPE 정밀도 (tp/pred) | NO-Hardhat 재현율 [W95] (tp/gt) |")
    print("|---|---|---|---|")
    for key in ("v1_all", f"{a.label}_all", "v1_noMask", f"{a.label}_noMask"):
        print(_row(key.replace("_all", " (Mask 포함)").replace("_noMask", " (Mask 제외)"), res[key]))
    d_all = (res[f"{a.label}_all"]["ppe_recall"] - res["v1_all"]["ppe_recall"]) * 100
    d_nm = (res[f"{a.label}_noMask"]["ppe_recall"] - res["v1_noMask"]["ppe_recall"]) * 100
    res["delta_recall_pp"] = {"with_mask": round(d_all, 1), "no_mask": round(d_nm, 1)}
    print(f"\nΔ재현율 {a.label}−v1: Mask 포함 {d_all:+.1f} %p → Mask 제외 **{d_nm:+.1f} %p** (실제 하락분)")
    print("클래스별(Mask 제외):")
    for c in res[f"{a.label}_noMask"]["ppe_per_class"]:
        v = res["v1_noMask"]["ppe_per_class"][c]; k = res[f"{a.label}_noMask"]["ppe_per_class"][c]
        print(f"  {c}: v1 {v['tp']}/{v['gt']} (fp {v['fp']}) → {a.label} {k['tp']}/{k['gt']} (fp {k['fp']})")
    out = Path(a.out) if a.out else _ROOT / "audit" / f"dev74_fair_{a.label}_{time.strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"); print(f"→ {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
