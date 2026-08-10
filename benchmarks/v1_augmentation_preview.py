#!/usr/bin/env python3
"""[V-1] 증강 설계 + 30장 원본 대조 미리보기 (학습 미실행 — 미리보기 전용).

★블러/JPEG/대비저하는 전면 폐기(사용자 지시, [U-0/S-1] 실측 근거: 놓친 것과 잡힌 것의 흐림
차이가 없거나 반대였음). 대신:

1. NO-Hardhat 용 크기 축소(유지, [U-0/S-1] 실측 부합 — 놓친 40건 100% 소형): 이미지를 축소해
   원본 크기 캔버스에 다시 배치 — "카메라가 더 멀리서 찍은 것처럼" 만든다. 목표 픽셀 크기는
   놓친 NO-Hardhat 40건의 실측 분포(중앙값 가로 23.9px·세로 16.6px, 범위 14~52px 가로)에 맞춤.

2. person 용 가림 증강(신규, 블러 대신): random erasing — person 박스 내부 일부를 무작위
   사각형으로 지운다. 차폐 비율은 [U-0/S-1] person 미스 몽타주의 육안 관찰(상당수가 절반 안팎
   가려짐)에 근거한 추정치이지 정밀 측정이 아니다(규칙7 — 아래 근거 문단 참고).

3. copy-paste 가림(css v27 오브젝트 오려붙이기)은 **이번엔 구현하지 않는다** — css v27 원본이
   이 데스크탑에 없다(data/datasets/css_safety 부재 확인). [V-2] 데이터 확보 후 별도 구현.

미리보기는 dev 프레임의 person 인스턴스로 시연한다(★실제 학습 데이터 아님 — 실제 학습은 css v27
확보 후 그 데이터에 적용해야 함, 여기 쓰인 dev 이미지는 시연 목적일 뿐 학습셋에 안 들어간다).
test는 건드리지 않는다.

의존성: kornia/albumentations 둘 다 이 환경에 미설치(확인됨) — 이 미리보기는 순수 OpenCV/NumPy로
구현해 새 설치 없이 바로 돈다. 실제 학습(RF-DETR 자체 Affine scale 증강 등)엔 나중에 둘 중 하나가
필요하다(설치는 별도 승인).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cv2  # noqa: E402
import numpy as np  # noqa: E402

FRAMES_DIR = _ROOT / "data" / "field_eval" / "frames"
LABELS_DIR = _ROOT / "data" / "field_eval" / "labels"
OUT_DIR = _ROOT / "data" / "field_eval" / "v1_augmentation_preview"
CLASSES = [c.strip() for c in (_ROOT / "data" / "field_eval" / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((_ROOT / "data" / "field_eval" / "dev_test_split.json").read_text(encoding="utf-8"))

# [U-0/S-1] 실측: 놓친 NO-Hardhat 40건 가로 픽셀 14.2~51.5, 중앙값 23.9 (no_hardhat_judge_sheet.json)
TARGET_HEAD_W_PX = (14, 52)
# 육안 추정(정밀 측정 아님, 규칙7): person 미스 몽타주에서 상당수가 박스 면적의 20~55% 가량
# 가려짐(기계·자재·난간 등)으로 보임 — Random Erasing 원 논문의 기본범위(2~40%)보다 위쪽으로 잡음.
ERASE_AREA_FRAC = (0.20, 0.55)
RNG = random.Random(0)


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


def scale_reduce(img: np.ndarray, boxes: list[list[float]], target_w_px: int) -> tuple[np.ndarray, list[list[float]]]:
    """전체 이미지를 축소해 원본 크기 캔버스 중앙에 배치(카메라가 더 멀리서 찍은 효과).
    boxes 는 [[x1,y1,x2,y2],...] 정규화 좌표(모두 같은 스케일로 이동)."""
    h, w = img.shape[:2]
    if not boxes:
        return img, boxes
    # 기준 박스(첫 번째, 보통 관심 대상)의 현재 가로 픽셀 → 목표 가로 픽셀 비율로 스케일 계산
    ref = boxes[0]
    cur_w_px = (ref[2] - ref[0]) * w
    if cur_w_px <= 0:
        return img, boxes
    scale = target_w_px / cur_w_px
    scale = max(0.05, min(1.0, scale))   # 확대는 안 함(이 증강의 목적이 아님)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    small = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    # 원본 크기 캔버스에 중앙 배치, 나머지는 가장자리 픽셀 반사로 채움(어색한 단색 배경 방지)
    canvas = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)  # 배경(흐릿한 축소본)로 자연스럽게
    ox, oy = (w - new_w) // 2, (h - new_h) // 2
    canvas[oy:oy + new_h, ox:ox + new_w] = small
    new_boxes = []
    for bx in boxes:
        x1, y1, x2, y2 = bx
        nx1 = (ox + x1 * new_w) / w
        ny1 = (oy + y1 * new_h) / h
        nx2 = (ox + x2 * new_w) / w
        ny2 = (oy + y2 * new_h) / h
        new_boxes.append([nx1, ny1, nx2, ny2])
    return canvas, new_boxes


def random_erase(img: np.ndarray, person_box: list[float], area_frac_range: tuple[float, float], rng: random.Random) -> np.ndarray:
    """person_box 내부에 무작위 사각형을 지운다(회색조 잡음 채움 — 표준 Random Erasing 변형)."""
    h, w = img.shape[:2]
    x1, y1, x2, y2 = person_box
    px1, py1, px2, py2 = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
    bw, bh = max(1, px2 - px1), max(1, py2 - py1)
    box_area = bw * bh
    frac = rng.uniform(*area_frac_range)
    erase_area = box_area * frac
    aspect = rng.uniform(0.4, 2.5)
    ew = int((erase_area * aspect) ** 0.5)
    eh = int((erase_area / aspect) ** 0.5)
    ew = max(1, min(ew, bw))
    eh = max(1, min(eh, bh))
    ex = px1 + rng.randint(0, max(0, bw - ew))
    ey = py1 + rng.randint(0, max(0, bh - eh))
    out = img.copy()
    noise = np.random.default_rng(rng.randint(0, 2**31)).integers(60, 180, (eh, ew, 3), dtype=np.uint8)
    out[ey:ey + eh, ex:ex + ew] = noise
    return out


def _label_bar(w: int, text: str) -> np.ndarray:
    bar = np.full((26, w, 3), 40, dtype=np.uint8)
    cv2.putText(bar, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return bar


def _side_by_side(orig: np.ndarray, aug: np.ndarray, title: str) -> np.ndarray:
    o = np.vstack([_label_bar(orig.shape[1], "원본"), orig])
    a = np.vstack([_label_bar(aug.shape[1], "증강 후"), aug])
    div = np.full((o.shape[0], 3, 3), 255, dtype=np.uint8)
    combined = np.hstack([o, div, a])
    return np.vstack([_label_bar(combined.shape[1], title), combined])


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 근거리(큰) NO-Hardhat/Hardhat 인스턴스 15개 수집 → 축소 증강 시연
    hardhat_candidates: list[tuple[str, list[float], np.ndarray]] = []
    person_candidates: list[tuple[str, list[float], np.ndarray]] = []
    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        h, w = img.shape[:2]
        for cls in ("Hardhat", "NO-Hardhat"):
            for bx in _load_gt(stem, cls):
                if (bx[2] - bx[0]) * w >= 60:   # 근거리(큰) 것만 축소 시연 대상
                    hardhat_candidates.append((fname, bx, img))
        for bx in _load_gt(stem, "person"):
            if (bx[2] - bx[0]) * w >= 40 and (bx[3] - bx[1]) * h >= 60:
                person_candidates.append((fname, bx, img))

    RNG.shuffle(hardhat_candidates)
    RNG.shuffle(person_candidates)

    n_scale = min(15, len(hardhat_candidates))
    n_erase = min(15, len(person_candidates))
    print(f"축소 증강 시연 후보: {len(hardhat_candidates)}개 중 {n_scale}개 사용")
    print(f"가림 증강 시연 후보: {len(person_candidates)}개 중 {n_erase}개 사용")

    idx = 0
    for fname, bx, img in hardhat_candidates[:n_scale]:
        idx += 1
        target_w = RNG.randint(*TARGET_HEAD_W_PX)
        aug_img, new_boxes = scale_reduce(img, [bx], target_w)
        nb = new_boxes[0]
        h, w = img.shape[:2]
        orig_vis = img.copy()
        cv2.rectangle(orig_vis, (int(bx[0] * w), int(bx[1] * h)), (int(bx[2] * w), int(bx[3] * h)), (0, 0, 255), 2)
        aug_vis = aug_img.copy()
        cv2.rectangle(aug_vis, (int(nb[0] * w), int(nb[1] * h)), (int(nb[2] * w), int(nb[3] * h)), (0, 0, 255), 2)
        panel = _side_by_side(orig_vis, aug_vis, f"[{idx}] 축소증강 target_w={target_w}px  ({fname})")
        cv2.imwrite(str(OUT_DIR / f"scale_{idx:02d}.jpg"), panel)

    for fname, bx, img in person_candidates[:n_erase]:
        idx += 1
        aug_img = random_erase(img, bx, ERASE_AREA_FRAC, RNG)
        h, w = img.shape[:2]
        orig_vis = img.copy()
        cv2.rectangle(orig_vis, (int(bx[0] * w), int(bx[1] * h)), (int(bx[2] * w), int(bx[3] * h)), (255, 140, 0), 2)
        aug_vis = aug_img.copy()
        cv2.rectangle(aug_vis, (int(bx[0] * w), int(bx[1] * h)), (int(bx[2] * w), int(bx[3] * h)), (255, 140, 0), 2)
        panel = _side_by_side(orig_vis, aug_vis, f"[{idx}] 가림증강(random erasing)  ({fname})")
        cv2.imwrite(str(OUT_DIR / f"erase_{idx:02d}.jpg"), panel)

    print(f"\n미리보기 {idx}장 저장: {OUT_DIR}")
    print("★시연용 — 이 dev 이미지들은 학습셋에 들어가지 않는다. 실제 학습은 css v27 확보 후 그 데이터에 적용.")


if __name__ == "__main__":
    main()
