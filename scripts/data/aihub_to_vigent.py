#!/usr/bin/env python3
"""scripts/data/aihub_to_vigent.py — AI Hub 507(고소작업)·510(물류창고) 라벨 → VIGENT 정답지 스키마 변환기. [A-3, 2026-09-26]

무엇을 만드는가 (`docs/data/aihub_class_map.md` 의 매핑표 그대로)
  out/
    classes.txt            person, Hardhat, NO-Hardhat, Safety-Vest, NO-Safety-Vest, forklift
    labels/<stem>.txt      YOLO 정규화 `cls cx cy w h` (기존 data/field_eval/labels 와 동일)
    labels_meta/<stem>.json  사이드카 {file, video, location_id, ..., source:"aihub:507", boxes:[{cls, box, aihub_class, derived}]}
    manifest.json          프레임 목록(장소·영상·device·박스 수·이미지 존재 여부)
    split.json             train/val — 507 은 장소ID 단위 8:2, 510 은 영상(raw_data_ID) 단위 8:2
    aug/                   (선택) --scale-aug 로 만든 축소 사본 이미지 + 라벨(이미지가 있을 때만)

★누출 검사: 분할 키(장소ID/영상ID)가 train·val 양쪽에 있으면 **exit 3**. 이미지 없는 프레임은 라벨만 쓰고 manifest 에 image_present=false 로 남긴다.
★Hardhat 파생(`--hardhat-from-wo01 0.17`)은 기본 OFF — 시나리오 폴더 WO-01 이 "위반 없음"이라는 [추정] 위에서만 켠다(A-1 §3).

사용:
    python scripts/data/aihub_to_vigent.py --dataset 507 --labels-root D:/vigent_private_data/aihub/_inspect/507_all \
        --images-root D:/vigent_private_data/aihub/_inspect/507_src --out D:/vigent_private_data/aihub/vigent_507 \
        --max-per-video 20 [--hardhat-from-wo01 0.17] [--scale-aug 0.1,0.3 --scale-copies 1] [--dry-run]
    python scripts/data/aihub_to_vigent.py --dataset 510 --labels-root .../510_all --images-root .../510_src_VS03 --out .../vigent_510
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CLASSES = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest", "forklift"]
EXCLUDED_CLASSES = ["Mask", "NO-Mask"]          # 원칙 유지(cvat_to_gt 와 동일 사유)

# 매핑표(docs/data/aihub_class_map.md). 값 = 우리 클래스명. 없는 코드는 전부 제외(집계만).
MAP = {
    "507": {"WO-04": "NO-Hardhat", "UA-04": "person", "WO-01": "person"},
    "510": {"WO-01": "person", "WO-02": "person", "WO-04": "forklift"},
}
SPLIT_KEY = {"507": "location_id", "510": "video"}    # 507 장소ID 단위 · 510 영상 단위
# 근접 규칙 검증용으로 사이드카에 남길 510 상황 태그
KEEP_SITUATION_510 = {"SO-15", "UA-10", "UC-10", "UA-14", "UA-01"}
_RID = re.compile(r"^[A-Z]-(\d{6})_([A-Z]\d+)_([A-Z])_(\w+-\d+)_(\d+)$")


def _get(j: dict, *keys: str) -> dict:
    for k in keys:
        if k in j:
            return j[k] or {}
    return {}


def parse_frame(j: dict, dataset: str) -> dict[str, Any]:
    """AI Hub JSON 1장 → 정규화 전 중간 표현. 좌표는 [x, y, w, h] 픽셀, 폴리곤은 외접 박스."""
    rd = _get(j, "Raw Data Info.", "Raw data Info.")
    sd = _get(j, "Source Data Info.", "Source data Info.")
    ld = _get(j, "Learning Data Info.", "Learning data info.")
    rid = str(rd.get("raw_data_ID", ""))
    m = _RID.match(rid)
    res = rd.get("resolution") or [1920, 1080]
    boxes = []
    for a in ld.get("annotation", []) or []:
        c = a.get("class_id")
        b = a.get("box") or a.get("coord")
        if b is None and a.get("type") == "polygon" and isinstance(a.get("coord"), list):
            b = a["coord"]
        if b is None:
            continue                                        # 키포인트 등 박스 없는 주석
        if isinstance(b, list) and b and isinstance(b[0], (list, tuple)):   # 폴리곤 [[x,y],...] → 외접
            xs = [p[0] for p in b]; ys = [p[1] for p in b]
            b = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
        if len(b) != 4:
            continue
        boxes.append({"aihub_class": c, "xywh": [float(v) for v in b]})
    return {
        "stem": str(ld.get("json_data_ID") or sd.get("source_data_ID") or ""),
        "image_file": (str(sd.get("source_data_ID") or ld.get("json_data_ID") or "")) + "." + str(sd.get("file_extension") or "jpg"),
        "video": rid, "location_id": rd.get("location_ID") or (m.group(2) if m else None),
        "process_id": rd.get("process_ID"), "situation_id": rd.get("situation_ID"),
        "situation_description": rd.get("situation_description"),
        "device": rd.get("device"), "frame": sd.get("frame"), "date": m.group(1) if m else rd.get("date"),
        "width": int(res[0]), "height": int(res[1]), "boxes": boxes,
    }


def head_box(xywh: list[float], ratio: float) -> list[float]:
    """사람 박스 상단 ratio 만큼을 머리 박스로(정사각에 가깝게 폭은 높이와 같게, 중앙 정렬)."""
    x, y, w, h = xywh
    hh = h * ratio
    ww = min(w, hh)
    return [x + (w - ww) / 2, y, ww, hh]


def convert_frame(fr: dict[str, Any], dataset: str, hardhat_ratio: float | None, counts: Counter) -> list[dict[str, Any]]:
    """중간 표현 → 우리 박스 목록 [{cls, box(정규화 cx cy w h), aihub_class, derived, derive_rule}]."""
    W, H = fr["width"], fr["height"]
    mp = MAP[dataset]
    out = []

    def norm(xywh: list[float]) -> list[float]:
        x, y, w, h = xywh
        return [round((x + w / 2) / W, 6), round((y + h / 2) / H, 6), round(w / W, 6), round(h / H, 6)]

    for b in fr["boxes"]:
        c = b["aihub_class"]
        name = mp.get(c)
        if name is None:
            counts[f"skip:{c}"] += 1
            continue
        if name in EXCLUDED_CLASSES:
            counts[f"excluded:{name}"] += 1
            continue
        out.append({"cls": CLASSES.index(name), "box": norm(b["xywh"]), "aihub_class": c,
                    "source": "aihub", "derived": False})
        counts[f"map:{c}->{name}"] += 1
        if dataset == "507" and c == "WO-01" and hardhat_ratio:
            # ★[추정] 시나리오 폴더 작업자는 위반 없음 → 상단 ratio 를 Hardhat 으로. 기본 OFF.
            out.append({"cls": CLASSES.index("Hardhat"), "box": norm(head_box(b["xywh"], hardhat_ratio)),
                        "aihub_class": "WO-01", "source": "aihub", "derived": True,
                        "derive_rule": f"top{hardhat_ratio:.2f}_of_WO-01 [추정: 위반 없음 가정]"})
            counts["derived:WO-01->Hardhat"] += 1
    return out


def split_by_key(frames: list[dict[str, Any]], key: str, val_ratio: float, seed: int) -> dict[str, list[str]]:
    """키(장소ID/영상) 단위로 train/val 을 나눈다. 프레임 수 기준으로 val 비율에 가장 가깝게 채운다."""
    groups: dict[str, list[str]] = defaultdict(list)
    for f in frames:
        groups[str(f.get(key))].append(f["stem"])
    keys = sorted(groups)
    rnd = random.Random(seed)
    rnd.shuffle(keys)
    total = sum(len(v) for v in groups.values())
    val_keys, n_val = [], 0
    for k in keys:
        if n_val >= total * val_ratio:
            break
        val_keys.append(k); n_val += len(groups[k])
    val = set(val_keys)
    return {"key": key, "train_keys": sorted(k for k in keys if k not in val), "val_keys": sorted(val),
            "train": sorted(s for k in keys if k not in val for s in groups[k]),
            "val": sorted(s for k in val for s in groups[k])}


def leak_check(split: dict[str, Any], frames: list[dict[str, Any]]) -> list[str]:
    """같은 키가 양쪽에 있거나, 같은 영상이 양쪽에 있으면 문제 목록을 돌려준다(빈 목록 = 통과)."""
    problems = []
    both = set(split["train_keys"]) & set(split["val_keys"])
    if both:
        problems.append(f"분할 키 중복: {sorted(both)[:5]}")
    vid = {f["stem"]: f["video"] for f in frames}
    tv = {vid[s] for s in split["train"]}; vv = {vid[s] for s in split["val"]}
    if tv & vv:
        problems.append(f"같은 영상이 양쪽에: {sorted(tv & vv)[:5]}")
    return problems


def scale_paste(img, boxes_norm: list[list[float]], s: float, canvas_wh: tuple[int, int], rnd: random.Random):
    """이미지를 s배로 줄여 캔버스 임의 위치에 붙이고 정규화 박스를 같이 옮긴다. (PIL)  → (new_img, new_boxes)"""
    from PIL import Image
    W, H = canvas_wh
    w2, h2 = max(1, int(img.width * s)), max(1, int(img.height * s))
    small = img.resize((w2, h2))
    ox, oy = rnd.randint(0, W - w2), rnd.randint(0, H - h2)
    canvas = Image.new("RGB", (W, H), (int(rnd.random() * 60),) * 3)
    canvas.paste(small, (ox, oy))
    nb = []
    for cx, cy, w, h in boxes_norm:
        px, py = cx * img.width, cy * img.height
        nb.append([round((ox + px * s) / W, 6), round((oy + py * s) / H, 6), round(w * img.width * s / W, 6), round(h * img.height * s / H, 6)])
    return canvas, nb


def run(a: argparse.Namespace) -> int:
    dataset = a.dataset
    lroot, out = Path(a.labels_root), Path(a.out)
    iroot = Path(a.images_root) if a.images_root else None
    files = sorted(lroot.rglob("*.json"))
    print(f"[{dataset}] 라벨 JSON {len(files)}개 — {lroot}")
    if not files:
        print("★라벨 파일 0개 — 실패"); return 2

    # 이미지 색인(있을 때만): stem → 경로
    img_index: dict[str, Path] = {}
    if iroot and iroot.exists():
        for p in iroot.rglob("*"):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                img_index[p.stem] = p
        print(f"  이미지 색인 {len(img_index)}개 — {iroot}")

    counts: Counter = Counter()
    frames: list[dict[str, Any]] = []
    per_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in files:
        try:
            fr = parse_frame(json.loads(p.read_text(encoding="utf-8")), dataset)
        except Exception:  # noqa: BLE001
            counts["bad_json"] += 1; continue
        if not fr["stem"]:
            fr["stem"] = p.stem
        fr["folder"] = p.relative_to(lroot).parts[0] if len(p.relative_to(lroot).parts) > 1 else ""
        per_video[fr["video"]].append(fr)
    # 영상당 균등 추림
    for vid, lst in per_video.items():
        lst.sort(key=lambda f: f["stem"])
        if a.max_per_video and len(lst) > a.max_per_video:
            step = len(lst) / a.max_per_video
            lst = [lst[int(i * step)] for i in range(a.max_per_video)]
        frames.extend(lst)
    counts["frames_kept"] = len(frames); counts["videos"] = len(per_video)

    # 변환
    records = []
    for fr in frames:
        boxes = convert_frame(fr, dataset, a.hardhat_from_wo01 if dataset == "507" else None, counts)
        if a.require_boxes and not boxes:
            counts["dropped_empty"] += 1; continue
        records.append((fr, boxes))
    kept_frames = [fr for fr, _ in records]
    split = split_by_key(kept_frames, SPLIT_KEY[dataset], a.val_ratio, a.seed)
    problems = leak_check(split, kept_frames)
    print(f"  프레임 {len(records)}장 · 영상 {counts['videos']}편 · 분할키 {SPLIT_KEY[dataset]}: train {len(split['train_keys'])} / val {len(split['val_keys'])} "
          f"(프레임 {len(split['train'])}/{len(split['val'])})")
    print("  매핑 집계:", {k: v for k, v in sorted(counts.items()) if k.startswith(('map:', 'derived:', 'excluded:'))})
    print("  제외 집계:", {k: v for k, v in sorted(counts.items()) if k.startswith('skip:')})
    if problems:
        print("★누출 검사 실패:", problems); return 3
    print("  누출 검사 통과(분할 키·영상 모두 양쪽에 없음)")
    if a.dry_run:
        print("--dry-run: 파일을 쓰지 않았다"); return 0

    # 쓰기
    (out / "labels").mkdir(parents=True, exist_ok=True); (out / "labels_meta").mkdir(exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    manifest = []
    n_txt = 0
    for fr, boxes in records:
        stem = fr["stem"]
        (out / "labels" / f"{stem}.txt").write_text("".join(f"{b['cls']} {' '.join(f'{v:.6f}' for v in b['box'])}\n" for b in boxes), encoding="utf-8")
        n_txt += 1
        meta = {"file": fr["image_file"], "video": fr["video"], "location_id": fr["location_id"], "process_id": fr["process_id"],
                "situation_id": fr["situation_id"], "situation_description": fr["situation_description"], "device": fr["device"],
                "frame": fr["frame"], "date": fr["date"], "folder": fr["folder"], "width": fr["width"], "height": fr["height"],
                "source": f"aihub:{dataset}", "image_present": stem in img_index, "boxes": boxes}
        if dataset == "510" and fr["situation_id"] in KEEP_SITUATION_510:
            meta["proximity_scenario"] = True
        (out / "labels_meta" / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        manifest.append({"stem": stem, "file": fr["image_file"], "video": fr["video"], SPLIT_KEY[dataset]: fr.get(SPLIT_KEY[dataset]),
                         "device": fr["device"], "n_boxes": len(boxes), "image_present": stem in img_index,
                         "image_path": str(img_index[stem]) if stem in img_index else None})
    (out / "manifest.json").write_text(json.dumps({"dataset": dataset, "source": f"aihub:{dataset}", "classes": CLASSES,
                                                   "counts": dict(counts), "frames": manifest}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "split.json").write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")
    # 규칙 11: 쓴 개수 확인
    n_disk = len(list((out / "labels").glob("*.txt")))
    print(f"  저장: labels {n_disk}개(기대 {n_txt}) · 이미지 있음 {sum(1 for m in manifest if m['image_present'])}/{len(manifest)} · {out}")
    if n_disk != n_txt:
        print("★라벨 개수 불일치 — 실패"); return 1

    # 축소 증강(이미지 있는 프레임만)
    if a.scale_aug:
        lo, hi = (float(x) for x in a.scale_aug.split(","))
        rnd = random.Random(a.seed)
        from PIL import Image
        aug_dir = out / "aug"; (aug_dir / "images").mkdir(parents=True, exist_ok=True); (aug_dir / "labels").mkdir(exist_ok=True)
        n_aug = 0
        for fr, boxes in records:
            if fr["stem"] not in img_index or not boxes:
                continue
            img = Image.open(img_index[fr["stem"]]).convert("RGB")
            for k in range(a.scale_copies):
                s = rnd.uniform(lo, hi)
                cv, nb = scale_paste(img, [b["box"] for b in boxes], s, (fr["width"], fr["height"]), rnd)
                name = f"{fr['stem']}_s{int(s * 100):03d}_{k}"
                cv.save(aug_dir / "images" / f"{name}.jpg", quality=90)
                (aug_dir / "labels" / f"{name}.txt").write_text("".join(f"{b['cls']} {' '.join(f'{v:.6f}' for v in nbx)}\n" for b, nbx in zip(boxes, nb)), encoding="utf-8")
                n_aug += 1
        print(f"  축소 증강: {n_aug}장 (배율 {lo}~{hi}) → {aug_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="AI Hub 507/510 → VIGENT 정답지")
    ap.add_argument("--dataset", choices=("507", "510"), required=True)
    ap.add_argument("--labels-root", required=True, help="압축 해제한 라벨 JSON 루트")
    ap.add_argument("--images-root", default="", help="원천 이미지 루트(없어도 라벨은 만든다)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-per-video", type=int, default=0, help="영상당 최대 프레임(균등 추림, 0=전부)")
    ap.add_argument("--val-ratio", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--hardhat-from-wo01", type=float, default=0.0, help="507: WO-01 상단 비율을 Hardhat 으로 파생(기본 0=끔, [추정])")
    ap.add_argument("--require-boxes", action="store_true", help="매핑 박스 0개 프레임은 버린다")
    ap.add_argument("--scale-aug", default="", help="축소 증강 배율 범위 'lo,hi' 예 0.1,0.3 (이미지 있을 때만)")
    ap.add_argument("--scale-copies", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
