#!/usr/bin/env python3
"""scripts/data/field_split.py — 현장 초벌 라벨(field_prelabel 산출)에서 ① held-out 300장 자동 선정(카메라×주야 층화, **클립 단위**) ② 카메라 단위 train/valid 분할 + 누출 검사. [PPE v2 현장 경로 ②③, 2026-09-27]

  heldout : manifest.json 을 읽어 양성 프레임을 (카메라, 주야) 층으로 나누고, 층마다 프레임 수 비례 할당량만큼 **클립(영상 파일/사진 시간대) 통째로** 뽑는다
            (같은 클립의 이웃 프레임이 train 에 남으면 held-out 이 아니다). 뽑힌 클립의 음성 프레임도 held-out 음성으로 묶는다.
            → heldout.json {policy:"학습 금지", frames, negatives, clips, strata} + manifest 의 해당 프레임에 heldout=true·no_train=true 표시.
            finetune_rfdetr 는 vigent 소스 옆의 heldout.json 을 자동으로 읽어 train/valid 에서 빼고, 그래도 남으면 조립을 중단한다(heldout_guard).
  split   : held-out 을 뺀 양성 프레임을 **카메라 단위**로 train/val 로 나눈다(aihub_to_vigent.split_by_key/leak_check 재사용). 같은 카메라·같은 클립(시간대)이
            양쪽에 있으면 exit 3. → split.json {train:[stem], val:[stem], train_keys, val_keys}
사용:
    python scripts/data/field_split.py heldout --dir D:/vigent_private_data/field/prelabel [--n 300] [--seed 0]
    python scripts/data/field_split.py split   --dir D:/vigent_private_data/field/prelabel [--val-ratio 0.25] [--val-cameras cam3]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aihub_to_vigent import leak_check, split_by_key  # noqa: E402

POLICY = "학습 금지 — 이 목록의 stem 은 어떤 조립기도 train/valid 에 넣지 않는다(finetune_rfdetr.heldout_guard 가 강제)"


def load_manifest(d: Path) -> dict[str, Any]:
    p = d / "manifest.json"
    if not p.exists():
        raise SystemExit(f"★manifest.json 없음: {d} (field_prelabel 을 먼저)")
    return json.loads(p.read_text(encoding="utf-8"))


def select_heldout(frames: list[dict[str, Any]], n: int = 300, seed: int = 0) -> dict[str, Any]:
    """양성 프레임을 (camera, daynight) 층으로 나눠 프레임 수 비례로 n 을 배분하고, 층 안에서 클립을 통째로 뽑아 할당량을 채운다.
    반환: {frames(양성 stem), negatives(뽑힌 클립의 음성 stem), clips, strata:{층: {quota, taken, clips}}}"""
    pos = [f for f in frames if not f.get("negative")]
    if not pos:
        raise SystemExit("★양성 프레임 0 — held-out 을 뽑을 수 없다")
    strata: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))   # 층 → clip → [stem]
    for f in pos:
        strata[(f["camera"], f["daynight"])][f["clip"]].append(f["stem"])
    total = len(pos); rnd = random.Random(seed)
    chosen_clips: set[str] = set(); report: dict[str, Any] = {}
    for key in sorted(strata):
        clips = strata[key]; size = sum(len(v) for v in clips.values())
        quota = max(1, int(round(n * size / total))) if n < total else size
        order = sorted(clips); rnd.shuffle(order)
        taken = 0; picked = []
        for c in order:
            if taken >= quota:
                break
            picked.append(c); taken += len(clips[c])
        chosen_clips.update(picked)
        report[f"{key[0]}|{key[1]}"] = {"frames": size, "clips": len(clips), "quota": quota, "taken": taken, "clips_taken": picked}
    hf = sorted(f["stem"] for f in pos if f["clip"] in chosen_clips)
    hn = sorted(f["stem"] for f in frames if f.get("negative") and f["clip"] in chosen_clips)
    return {"policy": POLICY, "n_target": n, "seed": seed, "n_positive": len(hf), "n_negative": len(hn), "frames": hf, "negatives": hn,
            "clips": sorted(chosen_clips), "strata": report,
            "note": "클립 단위 선정이라 n_positive 는 목표와 다를 수 있다(층별 quota 를 클립 통째로 채움). 이웃 프레임 누출 방지가 우선"}


def split_cameras(frames: list[dict[str, Any]], heldout_stems: set[str], val_ratio: float = 0.25, seed: int = 0,
                  val_cameras: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """held-out 을 뺀 양성 프레임을 카메라 단위로 나눈다. 반환 (split, problems). problems 가 비어야 통과."""
    pool = [{"stem": f["stem"], "camera": f["camera"], "video": f["clip"]} for f in frames if not f.get("negative") and f["stem"] not in heldout_stems]
    if not pool:
        return {}, ["분할할 양성 프레임 0"]
    if val_cameras:
        vc = set(val_cameras); cams = sorted({f["camera"] for f in pool})
        missing = vc - set(cams)
        if missing:
            return {}, [f"--val-cameras 에 없는 카메라: {sorted(missing)} (있는 것: {cams})"]
        split = {"key": "camera", "train_keys": sorted(c for c in cams if c not in vc), "val_keys": sorted(vc),
                 "train": sorted(f["stem"] for f in pool if f["camera"] not in vc), "val": sorted(f["stem"] for f in pool if f["camera"] in vc)}
    else:
        split = split_by_key(pool, "camera", val_ratio, seed)
    problems = leak_check(split, pool)
    if not split["val"] or not split["train"]:
        problems.append(f"한쪽이 비었다: train {len(split['train'])} / val {len(split['val'])} (카메라 수 {len({f['camera'] for f in pool})})")
    both = set(split["train"]) & heldout_stems | set(split["val"]) & heldout_stems
    if both:
        problems.append(f"held-out stem 이 분할에 들어감: {sorted(both)[:3]}")
    return split, problems


def cmd_heldout(d: Path, n: int, seed: int) -> int:
    m = load_manifest(d); h = select_heldout(m["frames"], n, seed)
    hs = set(h["frames"]) | set(h["negatives"])
    for f in m["frames"]:
        f["heldout"] = f["stem"] in hs; f["no_train"] = f["stem"] in hs
    (d / "heldout.json").write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads((d / "heldout.json").read_text(encoding="utf-8"))
    print(f"[heldout] 양성 {h['n_positive']}(목표 {n}) · 음성 {h['n_negative']} · 클립 {len(h['clips'])} · 층 {len(h['strata'])} → {d / 'heldout.json'}")
    for k, v in h["strata"].items():
        print(f"   {k:20s} 프레임 {v['frames']:5d} 클립 {v['clips']:3d} quota {v['quota']:4d} → {v['taken']:4d}")
    ok = len(back["frames"]) == h["n_positive"] and sum(1 for f in m["frames"] if f.get("no_train")) == len(hs)
    print("   manifest no_train 표시:", sum(1 for f in m["frames"] if f.get("no_train")), "✓" if ok else "★불일치")
    return 0 if ok else 1


def cmd_split(d: Path, val_ratio: float, seed: int, val_cameras: list[str] | None) -> int:
    m = load_manifest(d)
    hs: set[str] = set()
    if (d / "heldout.json").exists():
        h = json.loads((d / "heldout.json").read_text(encoding="utf-8")); hs = set(h["frames"]) | set(h["negatives"])
    else:
        print("★heldout.json 없음 — held-out 을 먼저 뽑는 것이 원칙(계속하면 held-out 없이 분할)")
    split, problems = split_cameras(m["frames"], hs, val_ratio, seed, val_cameras)
    if problems:
        print("★누출/분할 검사 실패:", problems); return 3
    print(f"[split] 카메라 train {split['train_keys']} / val {split['val_keys']} · 프레임 {len(split['train'])}/{len(split['val'])} · held-out 제외 {len(hs)} · 누출 검사 통과")
    split["heldout_excluded"] = len(hs); split["seed"] = seed
    (d / "split.json").write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")
    back = json.loads((d / "split.json").read_text(encoding="utf-8"))
    return 0 if len(back["train"]) == len(split["train"]) else 1


def main() -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("heldout"); h.add_argument("--dir", required=True); h.add_argument("--n", type=int, default=300); h.add_argument("--seed", type=int, default=0)
    s = sub.add_parser("split"); s.add_argument("--dir", required=True); s.add_argument("--val-ratio", type=float, default=0.25); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--val-cameras", default="", help="쉼표로 valid 카메라 지정(비우면 비율로 자동)")
    a = ap.parse_args()
    if a.cmd == "heldout":
        return cmd_heldout(Path(a.dir), a.n, a.seed)
    return cmd_split(Path(a.dir), a.val_ratio, a.seed, [c for c in a.val_cameras.split(",") if c] or None)


if __name__ == "__main__":
    sys.exit(main())
