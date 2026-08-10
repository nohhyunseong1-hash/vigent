#!/usr/bin/env python3
"""[X-1] NO-Hardhat 재현율 — 구간 보고(단일 수치 대신).

[V-0] 판정에서 놓친 NO-Hardhat 40건 중 대부분이 크롭만으로 안전모/맨머리 구분 불가로
판정됐다(`benchmarks/s1_miss_montage.md` §[X-0]) — 이 GT 들은 정답 자체가 불확실하므로
단일 재현율이 성립하지 않는다. 두 값을 함께 낸다:
  - 하한: 전체 GT 기준 재현율(현행, ambiguous 포함)
  - 상한: ambiguous 40건을 채점에서 제외(ignore)했을 때 재현율

GT 라벨 파일은 건드리지 않는다 — ambiguous 목록은 별도 플래그 파일로만 추적한다
(`data/field_eval/ambiguous_no_hardhat.json`).
"""
from __future__ import annotations

import json
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

import box_quality as bq  # noqa: E402
import cv2  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

FRAMES_DIR = _ROOT / "data" / "field_eval" / "frames"
LABELS_DIR = _ROOT / "data" / "field_eval" / "labels"
CLASSES = [c.strip() for c in (_ROOT / "data" / "field_eval" / "classes.txt").read_text(encoding="utf-8").splitlines() if c.strip()]
SPLIT = json.loads((_ROOT / "data" / "field_eval" / "dev_test_split.json").read_text(encoding="utf-8"))
JUDGE_SHEET = _ROOT / "data" / "field_eval" / "s1_miss_montage" / "no_hardhat_judge_sheet.json"
AMBIGUOUS_OUT = _ROOT / "data" / "field_eval" / "ambiguous_no_hardhat.json"
IOU_MATCH = 0.50


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_gt(stem: str) -> list[list[float]]:
    txt = LABELS_DIR / f"{stem}.txt"
    if not txt.exists():
        return []
    out = []
    for ln in txt.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if CLASSES[int(parts[0])] != "NO-Hardhat":
            continue
        cx, cy, w, h = (float(x) for x in parts[1:5])
        out.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])
    return out


def _bbox_key(file: str, bbox: list[float]) -> tuple[str, int, int, int, int]:
    # 부동소수 비교 대신 소수6자리 반올림 정수화로 안정적 매칭
    return (file, round(bbox[0] * 1e6), round(bbox[1] * 1e6), round(bbox[2] * 1e6), round(bbox[3] * 1e6))


def main() -> None:
    judge_entries = json.loads(JUDGE_SHEET.read_text(encoding="utf-8"))
    ambiguous_keys = {_bbox_key(e["file"], e["bbox"]) for e in judge_entries}
    print(f"ambiguous 후보(judge sheet): {len(ambiguous_keys)}건")

    guard = bq._build_guard()
    total_gt = 0
    total_tp = 0
    ambiguous_matched = 0
    ambiguous_flagged: list[dict] = []

    for fname in SPLIT["dev"]:
        stem = Path(fname).stem
        gts = _load_gt(stem)
        if not gts:
            continue
        img = cv2.imread(str(FRAMES_DIR / fname))
        if img is None:
            continue
        out = detect_isolated(guard, img, detectors=["person", "ppe"])
        preds = [d for d in out.get("detections", []) if d.get("label") == "NO-Hardhat"]

        pairs = []
        for gi, g in enumerate(gts):
            for pi, p in enumerate(preds):
                v = _iou(g, p["bbox"])
                if v >= IOU_MATCH:
                    pairs.append((v, gi, pi))
        pairs.sort(key=lambda x: -x[0])
        gt_hit: set[int] = set()
        pred_used: set[int] = set()
        for _v, gi, pi in pairs:
            if gi in gt_hit or pi in pred_used:
                continue
            gt_hit.add(gi)
            pred_used.add(pi)

        for gi, g in enumerate(gts):
            total_gt += 1
            is_ambiguous = _bbox_key(fname, g) in ambiguous_keys
            if is_ambiguous:
                ambiguous_matched += 1
                ambiguous_flagged.append({
                    "file": fname, "bbox": g, "reason": "V-0 검수자 판정: 크롭만으로 안전모/맨머리 구분 불가(대부분)",
                })
            if gi in gt_hit:
                total_tp += 1

    print(f"\ndev NO-Hardhat 전체 GT: {total_gt}건, TP(적중): {total_tp}건, FN(놓침): {total_gt - total_tp}건")
    print(f"judge sheet 40건 중 실제 매칭된 GT: {ambiguous_matched}건 (좌표 매칭 검증)")

    recall_lower = total_tp / total_gt if total_gt else 0.0
    denom_upper = total_gt - ambiguous_matched
    recall_upper = total_tp / denom_upper if denom_upper else 0.0

    print("\n=== [X-1] NO-Hardhat 재현율 구간 ===")
    print(f"하한(전체 GT 기준, ambiguous 포함): {recall_lower*100:.1f}% ({total_tp}/{total_gt})")
    print(f"상한(ambiguous {ambiguous_matched}건 채점 제외): {recall_upper*100:.1f}% ({total_tp}/{denom_upper})")
    print(f"참값은 [{recall_lower*100:.1f}%, {recall_upper*100:.1f}%] 사이로 추정(★두 값 다 실측, 사이의 특정 지점은 미검증)")

    AMBIGUOUS_OUT.write_text(json.dumps({
        "created": "2026-08-10",
        "source": "[X-0] 검수자 정성 판정 — benchmarks/s1_miss_montage.md 참고",
        "note": "GT 라벨 파일 자체는 미수정. 이 목록은 채점 시 ignore 후보 플래그일 뿐.",
        "count": len(ambiguous_flagged),
        "items": ambiguous_flagged,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nambiguous 플래그 파일: {AMBIGUOUS_OUT}")


if __name__ == "__main__":
    main()
