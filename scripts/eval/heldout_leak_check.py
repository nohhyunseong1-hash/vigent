#!/usr/bin/env python3
"""heldout_leak_check.py — held-out 목록이 train 과 **같은 영상 출처**를 공유하는지 파일명+화소로 재는 검사. [T-0c 재검토, 2026-09-25]

★왜 있는가
  1차 held-out(156장)은 `_mp4` 소문자 접미만 영상으로 봤다. 재검토에서 `_mov`·`_MP4` 프레임 10장과 확장자 표기가 없는
  `youtube-N` 묶음 55장이 train 과 같은 영상 출처임이 드러났다(provenance.md §7-0). 이 스크립트가 그 근거를 **재현**한다 —
  절차서에 적는 대신 확인하는 코드로 남긴다(CLAUDE.md 규칙 11).

무엇을 재는가
  1. held-out 각 장을 '출처 묶음'으로 분류(확장자 뗀 영상 id / 끝 번호 뗀 어간)하고 train 에 같은 묶음이 몇 장인지 센다.
  2. 묶음별 "번호 인접(≤3) 쌍이 연속 프레임인가": 32×32 그레이 정규화상관(NCC). 인접 쌍에 NCC ≥0.8 이 있으면 영상성.
     (train 은 증강본이라 held-out↔train 직접 화소 비교는 판정에 못 쓴다 — 같은 영상 프레임도 무작위 쌍과 구분되지 않았다.)

사용:
    python scripts/eval/heldout_leak_check.py [--heldout-json benchmarks/results/v1_heldout_stem_only_156.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass
from eval_v1_heldout import DS, stem_of, video_of  # noqa: E402

FAMILY_PATTERNS = {  # 번호 인접 검사 대상 묶음: (정규식, 번호 그룹 1)
    "youtube-N": r"^youtube-(\d+)$",
    "construction-N-": r"^construction-(\d+)-$",
    "<숫자만>": r"^0*(\d+)$",
    "ppe_N": r"^ppe_(\d+)$",
    "class1_N": r"^class1_(\d+)$",
    "class2_N": r"^class2_(\d+)$",
    "image_N": r"^image_(\d+)$",
    "img/IMG_N": r"^(?:img|IMG)_(\d+)$",
    "2008_N(VOC)": r"^2008_(\d+)$",
    "2009_N(VOC)": r"^2009_(\d+)$",
    "airport_inside_N": r"^airport_inside_(\d+)$",
    "mms_N": r"^mms_(\d+)$",
}


def family(stem: str) -> str:
    v = video_of(stem)
    if v:
        return "VIDEO:" + v
    t = re.sub(r"[-_ ]*\(?\d+\)?[-_ ]*$", "", stem)
    t = re.sub(r"_(png|jpg|jpeg)$", "", t, flags=re.I)
    return t.lower() or "<숫자만>"


def vec(p: Path) -> np.ndarray:
    s = np.asarray(Image.open(p).convert("L").resize((32, 32), Image.BILINEAR), dtype=np.float32).flatten()
    return (s - s.mean()) / (s.std() + 1e-6)


def check_families(held: list[str], train: set[str]) -> dict:
    train_fam = Counter(family(s) for s in train)
    hf: dict[str, list[str]] = defaultdict(list)
    for s in held:
        hf[family(s)].append(s)
    print("== 1. held-out 출처 묶음 (train 에 같은 묶음이 몇 장 있는가) ==")
    vid_leak = 0
    for f, ss in sorted(hf.items(), key=lambda kv: -len(kv[1])):
        tr = train_fam.get(f, 0)
        flag = "★영상·train겹침" if f.startswith("VIDEO:") and tr else ("영상" if f.startswith("VIDEO:") else "")
        if f.startswith("VIDEO:") and tr:
            vid_leak += len(ss)
        if len(ss) >= 2 or f.startswith("VIDEO:"):
            print(f"  {f:<45} held-out {len(ss):3d}  train {tr:3d}  {flag}")
    print(f"  (1장짜리 묶음 {sum(1 for ss in hf.values() if len(ss) == 1)}개 생략)")
    print(f"→ 영상 id(확장자 무시)로 train 과 겹치는 프레임: {vid_leak}장")
    return {"video_leak_frames": vid_leak, "families": {f: len(ss) for f, ss in hf.items()}}


def check_adjacency(train: set[str]) -> dict:
    files: dict[str, tuple[str, Path]] = {}
    for sp in ("valid", "test", "train"):
        for p in sorted((DS / sp / "images").glob("*")):
            files.setdefault(stem_of(p), (sp, p))  # stem 당 1장(비증강 valid/test 우선)
    rng = np.random.default_rng(0)
    print("\n== 2. 묶음별 번호 인접(≤3) 쌍 NCC — ≥0.8 이 있으면 연속 프레임 ==")
    print(f"{'묶음':<18} {'장수':>4} {'인접쌍':>6} {'중앙':>6} {'≥0.8':>5} {'최대':>6} | {'먼쌍':>5} {'중앙':>6} {'≥0.8':>5} {'최대':>6}  판정")
    out = {}
    for name, rx in FAMILY_PATTERNS.items():
        mem = {}
        for s, (_sp, p) in files.items():
            m = re.match(rx, s)
            if m:
                mem[int(m.group(1))] = p
        nums = sorted(mem)
        if len(nums) < 2:
            continue
        V = {n: vec(mem[n]) for n in nums}
        near = [float(V[a] @ V[b] / 1024) for a in nums for b in nums if 0 < b - a <= 3]
        far = []
        if len(nums) >= 4:
            for _ in range(1500):
                a, b = rng.choice(nums, 2, replace=False)
                if abs(a - b) > 20:
                    far.append(float(V[a] @ V[b] / 1024))
        n_hi = sum(v >= 0.8 for v in near)
        verdict = "영상성" if n_hi else ("무증거" if near else "인접쌍 없음")
        fn = f"{len(near):>6} {np.median(near):>6.3f} {n_hi:>5} {max(near):>6.3f}" if near else f"{0:>6} {'-':>6} {'-':>5} {'-':>6}"
        ff = f"{len(far):>5} {np.median(far):>6.3f} {sum(v >= 0.8 for v in far):>5} {max(far):>6.3f}" if far else f"{0:>5} {'-':>6} {'-':>5} {'-':>6}"
        print(f"{name:<18} {len(nums):>4} {fn} | {ff}  {verdict}")
        out[name] = {"n": len(nums), "near_pairs": len(near), "near_ge08": n_hi, "verdict": verdict}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heldout-json", default=str(_ROOT / "benchmarks" / "results" / "v1_heldout_stem_only_156.json"))
    a = ap.parse_args()
    j = json.loads(Path(a.heldout_json).read_text(encoding="utf-8"))
    held = [stem_of(_ROOT / f) for f in j["heldout_files"]]
    train = {stem_of(p) for p in (DS / "train" / "images").glob("*")}
    print(f"held-out {len(held)}장 ({a.heldout_json}) · train 고유 원본 {len(train)}")
    r1 = check_families(held, train)
    r2 = check_adjacency(train)
    yt = [s for s in held if re.match(r"^youtube-\d+$", s, re.I)]
    tr_nums = {int(m.group(1)) for s in train for m in [re.match(r"^youtube-(\d+)$", s)] if m}
    adj = [s for s in yt if any(abs(int(s.split("-")[1]) - t) <= 3 for t in tr_nums)]
    print(f"\nheld-out youtube-N {len(yt)}장 중 train 에 번호차 ≤3 인 장이 있는 것: {len(adj)}")
    video_like = [f for f, v in r2.items() if v["verdict"] == "영상성"]
    print(f"결론: 영상 id 겹침 {r1['video_leak_frames']}장 + 영상성 묶음 {video_like} → 영상 단위 held-out 에서 제외해야 한다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
