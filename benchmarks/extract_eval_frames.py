#!/usr/bin/env python3
"""benchmarks/extract_eval_frames.py — 재해 영상에서 PPE/person 정확도 평가용 프레임 추출(측정 전용).

목적: 학습용이 아니라 **평가용 정답지 제작**의 재료 — "다양한 장면을 골라 뽑기"(중복 최소화),
전부 뽑지 않는다. 라벨링은 사람이 한다(이 스크립트는 후보 선별만). 정확도 수치는 만들지 않는다(규칙7).

알고리즘:
  1) 영상마다 기본 1fps 후보를 순회.
  2) 직전 "선택된" 프레임과 너무 비슷하면(다운샘플 그레이스케일 평균절대차 < DEDUP_THRESHOLD) 건너뛴다.
  3) 남은 후보를 밝기(주간/야간/역광후보)·화면 내 최대 person 박스 높이비(원거리/근거리/사람없음)로
     분류 — person 크기는 guard.detect(person only)를 실제로 돌려 얻는다(추측 아님).
  4) 영상당 상한(기본 30)을 넘으면 (밝기,크기) 버킷별로 균등 배분해 시간순 등간격 서브샘플.
  5) 전체 상한(기본 300)을 넘으면 영상별 배분량을 비례 축소.

주의(정직 고지): '역광' 판정은 밝기 히스토그램 양극단 비율 기반 **휴리스틱 후보**이지 확정 판별이
아니다. 'PPE/person 정확도' 자체는 이 스크립트가 재지 않는다 — 이건 Phase2(사람이 라벨링) 이후
별도 평가 스크립트의 몫이다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import box_quality as bq  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CANDIDATE_FPS = 1.0
DEDUP_THRESHOLD = 10.0       # 다운샘플(64x64) 그레이스케일 평균절대차 임계 — 이 미만이면 "너무 비슷함"
DEDUP_SMALL = 64
DARK_PIXEL = 40
BRIGHT_PIXEL = 220
DARK_FRAC_BACKLIGHT = 0.15
BRIGHT_FRAC_BACKLIGHT = 0.05
NIGHT_MEAN = 70.0
NEAR_HEIGHT_FRAC = 0.25      # person 박스 높이/프레임 높이 ≥ 이 값이면 "근거리"

DEFAULT_PER_VIDEO_CAP = 30
DEFAULT_GLOBAL_CAP = 300


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="재해 영상 평가용 프레임 스마트 추출(측정 전용)")
    p.add_argument("--input-dir", default=str(_ROOT / "runs" / "rfdetr" / "accident"))
    p.add_argument("--out-dir", default=str(_ROOT / "data" / "field_eval" / "frames"))
    p.add_argument("--per-video-cap", type=int, default=DEFAULT_PER_VIDEO_CAP)
    p.add_argument("--global-cap", type=int, default=DEFAULT_GLOBAL_CAP)
    p.add_argument("--montage-out", default=str(_ROOT / "data" / "field_eval" / "sample_montage.jpg"))
    p.add_argument("--summary-out", default=str(_HERE / "extract_eval_frames_summary.md"))
    return p.parse_args()


def _brightness_bucket(gray) -> str:
    import numpy as np
    total = gray.size
    dark_frac = float(np.count_nonzero(gray < DARK_PIXEL)) / total
    bright_frac = float(np.count_nonzero(gray > BRIGHT_PIXEL)) / total
    mean = float(gray.mean())
    if dark_frac > DARK_FRAC_BACKLIGHT and bright_frac > BRIGHT_FRAC_BACKLIGHT:
        return "역광후보"
    if mean < NIGHT_MEAN:
        return "야간"
    return "주간"


def _person_size_bucket(guard: Any, img, h: int) -> tuple[str, float]:
    # 2026-08: track_key="eval_extract" 고정 재사용 버그 수정 — 서로 무관한 정지 이미지(9개 비디오·
    #   109장)에 같은 키를 재사용해 이전 이미지의 트랙이 이어붙던 문제(실측 확인, 소수점까지 conf 일치)를
    #   detect_isolated()(매 호출 고유 track_key 발급+전후 reset)로 원천 차단.
    out = detect_isolated(guard, img, detectors=["person"], imgsz=None, conf=None)
    best_h = 0.0
    for d in out.get("detections", []):
        if d.get("label") != "person":
            continue
        y1, y2 = d["bbox"][1], d["bbox"][3]
        best_h = max(best_h, (y2 - y1))   # 정규화 좌표(0~1) 기준 높이비
    if best_h <= 0:
        return "사람없음", 0.0
    return ("근거리" if best_h >= NEAR_HEIGHT_FRAC else "원거리"), best_h


def _downsample_gray(img):
    import cv2
    small = cv2.resize(img, (DEDUP_SMALL, DEDUP_SMALL))
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def extract_candidates(video_path: Path, guard: Any) -> list[dict[str, Any]]:
    """1fps 후보를 순회, 직전 '선택'과 비교해 중복 제거하며 메타(밝기·person크기) 부여."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, round(fps / CANDIDATE_FPS))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    selected: list[dict[str, Any]] = []
    last_gray = None
    idx = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if idx % step == 0:
            gray = _downsample_gray(img)
            if last_gray is not None:
                diff = float(np.mean(np.abs(gray.astype("int16") - last_gray.astype("int16"))))
                if diff < DEDUP_THRESHOLD:
                    idx += 1
                    continue
            bright = _brightness_bucket(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
            size_bucket, height_frac = _person_size_bucket(guard, img, h)
            t_ms = (idx / fps) * 1000.0
            selected.append({
                "video": video_path.stem, "frame_idx": idx, "t_ms": round(t_ms, 1),
                "bright": bright, "size_bucket": size_bucket, "height_frac": round(height_frac, 3),
                "img": img,
            })
            last_gray = gray
        idx += 1
    cap.release()
    return selected


def stratified_cap(items: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    """(밝기,크기) 버킷별로 등간격 서브샘플해 cap 개로 축소(시간순 유지, 버킷 균등 배분)."""
    if len(items) <= cap:
        return items
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for it in items:
        buckets.setdefault((it["bright"], it["size_bucket"]), []).append(it)
    n_buckets = len(buckets)
    base = max(1, cap // n_buckets)
    picked: list[dict[str, Any]] = []
    remaining_cap = cap
    bucket_list = list(buckets.values())
    for i, bucket in enumerate(bucket_list):
        slots = min(len(bucket), base)
        buckets_left = n_buckets - i
        slots = min(slots, remaining_cap - (buckets_left - 1))   # 뒤 버킷 최소 1개씩 남기기
        slots = max(0, slots)
        if slots >= len(bucket):
            chosen = bucket
        else:
            step = len(bucket) / slots if slots else 0
            chosen = [bucket[int(j * step)] for j in range(slots)]
        picked.extend(chosen)
        remaining_cap -= len(chosen)
    picked.sort(key=lambda x: x["t_ms"])
    return picked[:cap]


def build_montage(samples: list[dict[str, Any]], out_path: Path) -> None:
    import cv2
    import numpy as np
    cell = 240
    grid = 3
    canvas = np.zeros((cell * grid, cell * grid, 3), dtype=np.uint8)
    for i, s in enumerate(samples[: grid * grid]):
        img = cv2.resize(s["img"], (cell, cell))
        r, c = divmod(i, grid)
        canvas[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = img
        label = f"{s['video'][:14]} {s['t_ms']/1000:.1f}s"
        cv2.putText(canvas, label, (c * cell + 4, r * cell + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, (0, 255, 0), 1, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas)


def main() -> None:
    import cv2

    a = _args()
    in_dir = Path(a.input_dir)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    videos = sorted(in_dir.glob("*.mp4"))
    if not videos:
        raise SystemExit(f"[extract_eval_frames] 영상 없음: {in_dir}")

    guard = bq._build_guard()

    per_video: dict[str, list[dict[str, Any]]] = {}
    for v in videos:
        cands = extract_candidates(v, guard)
        capped = stratified_cap(cands, a.per_video_cap)
        per_video[v.stem] = capped
        print(f"{v.name}: 후보 {len(cands)} → 상한적용 {len(capped)}")

    total = sum(len(v) for v in per_video.values())
    if total > a.global_cap:
        scale = a.global_cap / total
        for name, items in per_video.items():
            new_n = max(1, round(len(items) * scale))
            if new_n < len(items):
                step = len(items) / new_n
                per_video[name] = [items[int(j * step)] for j in range(new_n)]
        total_after = sum(len(v) for v in per_video.values())
        print(f"[전체상한] {total} → {total_after}(영상별 비례축소, global_cap={a.global_cap})")

    all_saved: list[dict[str, Any]] = []
    for name, items in per_video.items():
        for it in items:
            fname = f"{name}_{int(it['t_ms'])}ms.jpg"
            out_path = out_dir / fname
            cv2.imwrite(str(out_path), it["img"])
            saved = {k: v for k, v in it.items() if k != "img"}
            saved["file"] = fname
            all_saved.append(saved)

    # 요약
    lines = [
        "# 평가용 프레임 추출 요약 (측정 전용 — 정확도 수치 없음)",
        "",
        f"입력: `{in_dir}`({len(videos)}개 영상) · 출력: `{out_dir}`(gitignore) · 총 **{len(all_saved)}장**",
        "",
        "| 영상 | 추출 수 | 밝기 분포 | 사람크기 분포 |",
        "|---|---|---|---|",
    ]
    for name, items in per_video.items():
        b_dist: dict[str, int] = {}
        s_dist: dict[str, int] = {}
        for it in items:
            b_dist[it["bright"]] = b_dist.get(it["bright"], 0) + 1
            s_dist[it["size_bucket"]] = s_dist.get(it["size_bucket"], 0) + 1
        b_txt = ", ".join(f"{k}:{v}" for k, v in sorted(b_dist.items()))
        s_txt = ", ".join(f"{k}:{v}" for k, v in sorted(s_dist.items()))
        lines.append(f"| {name} | {len(items)} | {b_txt} | {s_txt} |")

    b_all: dict[str, int] = {}
    s_all: dict[str, int] = {}
    for it in all_saved:
        b_all[it["bright"]] = b_all.get(it["bright"], 0) + 1
        s_all[it["size_bucket"]] = s_all.get(it["size_bucket"], 0) + 1
    lines += [
        "",
        "## 전체 조건 분포",
        f"- 밝기: {', '.join(f'{k} {v}장' for k, v in sorted(b_all.items()))}",
        f"- 사람크기: {', '.join(f'{k} {v}장' for k, v in sorted(s_all.items()))}",
        "",
        "## 정직 고지",
        "- '역광' 은 밝기 히스토그램 양극단 비율 기반 휴리스틱 후보 판정이지 확정이 아니다.",
        "- 이 스크립트는 라벨링용 후보를 고를 뿐, PPE/person 검출 정확도를 측정하지 않는다"
        "(정확도는 Phase2 라벨링 완료 후 별도 스크립트로 잰다).",
        f"- 중복제거 임계(다운샘플 64x64 그레이스케일 평균절대차) = {DEDUP_THRESHOLD} — 이 값 미만이면 "
        "'너무 비슷한 장면'으로 건너뛴다.",
    ]
    summary_path = Path(a.summary_out)
    summary_path.write_text("\n".join(lines), encoding="utf-8")

    manifest_path = out_dir.parent / "frames_manifest.json"
    manifest_path.write_text(json.dumps(all_saved, ensure_ascii=False, indent=1), encoding="utf-8")

    montage_samples = [per_video[v.stem][len(per_video[v.stem]) // 2] for v in videos if per_video[v.stem]]
    build_montage(montage_samples, Path(a.montage_out))

    print("\n".join(lines))
    print(f"\n저장: {summary_path}")
    print(f"매니페스트: {manifest_path}")
    print(f"몽타주: {a.montage_out}")


if __name__ == "__main__":
    main()
