#!/usr/bin/env python3
"""[V-1 마저] copy-paste 가림 증강 — css v27 기계·자재·구조물 오브젝트 오려붙이기.

[V-1]에서 random erasing(무작위 사각형 지우기)은 구현했으나, copy-paste 가림(실제 기계·자재
오브젝트를 사람 위에 겹쳐 붙이는 것 — random erasing보다 사실적인 가림)은 css v27 데이터셋
부재로 미구현이었다. [W-1]에서 css v27을 재확보(data/datasets/css_safety, MANIFEST.md 검증
완료)했으므로 마저 구현한다.

오브젝트 오브젝트 은행: css v27 train 라벨에서 machinery(5,238건)/vehicle(1,534건)/
Safety Cone(3,170건) 박스를 크롭해 은행으로 쓴다(둘 다 "기계·자재·구조물" 범주 — person·PPE
자체를 오려붙이면 라벨 오염이므로 제외). 가림 비율은 random_erase와 동일 근거·범위
(ERASE_AREA_FRAC, [U-0/S-1] 몽타주 육안 관찰 기반 추정 — 정밀 측정 아님, 규칙7)를 그대로 쓴다.

미리보기 30장은 dev person 인스턴스에 시연(★학습 데이터 아님, dev는 학습셋에 안 들어감).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)
sys.path.insert(0, str(_HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from v1_augmentation_preview import _side_by_side  # noqa: E402

FRAMES_DIR = media("field_eval") / "frames"
LABELS_DIR = media("field_eval") / "labels"
CLASSES = [c.strip() for c in (media("field_eval") / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((media("field_eval") / "dev_test_split.json").read_text(encoding="utf-8"))
OUT_DIR = media("field_eval") / "v1_augmentation_preview"

CSS_ROOT = _ROOT / "data" / "datasets" / "css_safety" / "train"
# data.yaml 클래스 순서: 0 Hardhat,1 Mask,2 NO-Hardhat,3 NO-Mask,4 NO-Safety Vest,5 Person,
# 6 Safety Cone,7 Safety Vest,8 machinery,9 vehicle — 사람/PPE 자체는 제외, 물체 3종만 은행 대상.
BANK_CLASS_IDS = {8, 9, 6}
BANK_SIZE = 200          # 은행에 담을 크롭 상한(전부 쓸 필요 없음, 다양성 확보 수준이면 충분)
ERASE_AREA_FRAC = (0.20, 0.55)   # v1_augmentation_preview.ERASE_AREA_FRAC 과 동일 근거
RNG = random.Random(1)


def _load_gt(stem: str, cls: str) -> list[list[float]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if CLASSES[int(parts[0])] != cls:
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def build_crop_bank(rng: random.Random, bank_size: int) -> list[np.ndarray]:
    """css v27 train 라벨에서 machinery/vehicle/Safety Cone 박스를 크롭해 은행을 만든다."""
    lbl_dir = CSS_ROOT / "labels"
    img_dir = CSS_ROOT / "images"
    candidates = list(lbl_dir.glob("*.txt"))
    rng.shuffle(candidates)

    bank: list[np.ndarray] = []
    for lbl_path in candidates:
        if len(bank) >= bank_size:
            break
        img_path = img_dir / f"{lbl_path.stem}.jpg"
        if not img_path.exists():
            continue
        img = None
        for ln in lbl_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            cid = int(parts[0])
            if cid not in BANK_CLASS_IDS:
                continue
            cx, cy, bw, bh = (float(x) for x in parts[1:5])
            if bw < 0.03 or bh < 0.03:   # 너무 작은 크롭은 가림에 못 씀
                continue
            if img is None:
                img = cv2.imread(str(img_path))
                if img is None:
                    break
            h, w = img.shape[:2]
            x1, y1 = int((cx - bw / 2) * w), int((cy - bh / 2) * h)
            x2, y2 = int((cx + bw / 2) * w), int((cy + bh / 2) * h)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            bank.append(img[y1:y2, x1:x2].copy())
            if len(bank) >= bank_size:
                break
    return bank


def copy_paste_occlude(img: np.ndarray, person_box: list[float], bank: list[np.ndarray],
                        area_frac_range: tuple[float, float], rng: random.Random) -> np.ndarray:
    """person_box 내부에 은행에서 뽑은 오브젝트 크롭을 겹쳐 붙인다(실제 가림 시뮬레이션)."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = person_box
    px1, py1, px2, py2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
    bw, bh = max(1, px2 - px1), max(1, py2 - py1)
    box_area = bw * bh
    frac = rng.uniform(*area_frac_range)
    target_area = box_area * frac

    obj = bank[rng.randrange(len(bank))]
    oh, ow = obj.shape[:2]
    aspect = ow / oh if oh > 0 else 1.0
    new_w = int((target_area * aspect) ** 0.5)
    new_h = int((target_area / aspect) ** 0.5) if aspect > 0 else new_w
    new_w = max(4, min(new_w, bw))
    new_h = max(4, min(new_h, bh))
    obj_resized = cv2.resize(obj, (new_w, new_h), interpolation=cv2.INTER_AREA)

    ex = px1 + rng.randint(0, max(0, bw - new_w))
    ey = py1 + rng.randint(0, max(0, bh - new_h))
    out = img.copy()
    out[ey:ey + new_h, ex:ex + new_w] = obj_resized
    return out


def main() -> None:
    print("css v27 오브젝트 은행 구축 중(machinery/vehicle/Safety Cone)...")
    bank = build_crop_bank(RNG, BANK_SIZE)
    print(f"은행 크기: {len(bank)}개 크롭")
    if not bank:
        raise SystemExit("오브젝트 은행이 비었다 — css_safety 경로/라벨을 확인하라.")

    person_candidates: list[tuple[str, list[float], np.ndarray]] = []
    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        h, w = img.shape[:2]
        for bx in _load_gt(stem, "person"):
            if (bx[2] - bx[0]) * w >= 40 and (bx[3] - bx[1]) * h >= 60:
                person_candidates.append((fname, bx, img))
    RNG.shuffle(person_candidates)
    n = min(30, len(person_candidates))
    print(f"copy-paste 시연 후보: {len(person_candidates)}개 중 {n}개 사용")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for idx, (fname, bx, img) in enumerate(person_candidates[:n], start=1):
        aug_img = copy_paste_occlude(img, bx, bank, ERASE_AREA_FRAC, RNG)
        h, w = img.shape[:2]
        orig_vis = img.copy()
        cv2.rectangle(orig_vis, (int(bx[0] * w), int(bx[1] * h)), (int(bx[2] * w), int(bx[3] * h)), (0, 200, 0), 2)
        aug_vis = aug_img.copy()
        cv2.rectangle(aug_vis, (int(bx[0] * w), int(bx[1] * h)), (int(bx[2] * w), int(bx[3] * h)), (0, 200, 0), 2)
        panel = _side_by_side(orig_vis, aug_vis, f"[{idx}] copy-paste 가림(css v27 오브젝트)  ({fname})")
        cv2.imwrite(str(OUT_DIR / f"copypaste_{idx:02d}.jpg"), panel)

    print(f"\ncopy-paste 미리보기 {n}장 저장: {OUT_DIR}")
    print("★시연용 — dev 이미지는 학습셋에 들어가지 않는다.")


if __name__ == "__main__":
    main()
