#!/usr/bin/env python3
"""benchmarks/recompute_frame_metadata.py — [A-3] 109장 person 크기 버킷 격리 재계산(측정 전용).

배경: `frames_manifest.json`의 size_bucket/height_frac은 `extract_eval_frames.py`가
track_key="eval_extract"를 109장 전체에 재사용하며 계산한 값이라, 트랙 잔존(2026-08 확정 버그)으로
일부가 오염됐을 수 있다. **프레임 재추출은 하지 않는다** — 이미 뽑힌 109장 이미지 파일은 그대로 두고,
같은 `_person_size_bucket` 로직(임계·해상도 전부 동일)을 `detect_isolated()`로만 바꿔 재계산한다.

출력:
  data/field_eval/frames_manifest.json          갱신(구 파일은 .pre_isolation_fix_backup.json 로 보존)
  benchmarks/recompute_frame_metadata_diff.md    프레임별 구값 vs 신값 비교 + 변동 요약
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import field_eval  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

import box_quality as bq  # noqa: E402
from extract_eval_frames import NEAR_HEIGHT_FRAC, _person_size_bucket  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

MANIFEST = field_eval("frames_manifest.json")
FRAMES_DIR = field_eval("frames")
BACKUP = field_eval("frames_manifest.pre_isolation_fix_backup.json")


def main() -> None:
    import cv2

    if not MANIFEST.exists():
        raise SystemExit(f"[recompute_frame_metadata] manifest 없음: {MANIFEST}")
    old_records: list[dict[str, Any]] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not BACKUP.exists():
        BACKUP.write_text(json.dumps(old_records, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"백업 저장(최초 1회만): {BACKUP}")
    else:
        print(f"백업 이미 존재(재실행이라 유지): {BACKUP}")

    guard = bq._build_guard()

    changed: list[dict[str, Any]] = []
    new_records: list[dict[str, Any]] = []
    for rec in old_records:
        fp = FRAMES_DIR / rec["file"]
        if not fp.exists():
            print(f"  [경고] 프레임 파일 없음(스킵, 구값 유지): {rec['file']}")
            new_records.append(rec)
            continue
        img = cv2.imread(str(fp))
        h = img.shape[0]
        new_bucket, new_height = _person_size_bucket(guard, img, h)
        old_bucket, old_height = rec["size_bucket"], rec["height_frac"]
        new_rec = {**rec, "size_bucket": new_bucket, "height_frac": round(new_height, 3)}
        new_records.append(new_rec)
        if new_bucket != old_bucket:
            changed.append({
                "file": rec["file"], "old_bucket": old_bucket, "old_height": old_height,
                "new_bucket": new_bucket, "new_height": round(new_height, 3),
            })

    MANIFEST.write_text(json.dumps(new_records, ensure_ascii=False, indent=1), encoding="utf-8")

    def _count(records: list[dict[str, Any]], key: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in records:
            out[r[key]] = out.get(r[key], 0) + 1
        return out

    old_counts = _count(old_records, "size_bucket")
    new_counts = _count(new_records, "size_bucket")

    lines = [
        "# [A-3] person 크기 버킷 격리 재계산 — 구값 vs 신값 (프레임 재추출 없음, 격리만 수정)",
        "",
        f"방법: `extract_eval_frames._person_size_bucket`(동일 로직·임계 NEAR_HEIGHT_FRAC="
        f"{NEAR_HEIGHT_FRAC}, conf=None(→0.35 기본)·imgsz=None(→기본))을 `detect_isolated()`로만 "
        "교체해 기존 109장 이미지 파일에 재실행. 프레임 선정·추출은 무수정.",
        "",
        "## 전체 분포 변화",
        "| 버킷 | 구값(오염 가능) | 신값(격리 재계산) |",
        "|---|---|---|",
    ]
    for k in sorted(set(old_counts) | set(new_counts)):
        lines.append(f"| {k} | {old_counts.get(k, 0)} | {new_counts.get(k, 0)} |")

    lines += [
        "",
        f"## 바뀐 프레임 목록 ({len(changed)}건 / 전체 {len(old_records)}장)",
        "",
        "| 파일 | 구분류 | 구height_frac | 신분류 | 신height_frac |",
        "|---|---|---|---|---|",
    ]
    for c in changed:
        lines.append(f"| {c['file']} | {c['old_bucket']} | {c['old_height']} | "
                     f"{c['new_bucket']} | {c['new_height']} |")

    lines += [
        "",
        "## 규칙7 — 수치 출처 고지",
        "이 표의 '신값'이 현재 `frames_manifest.json`에 반영된 값이다. '구값'은 트랙 오염 버그"
        "(2026-08 확정, `benchmarks/extract_eval_frames.py`의 `track_key=\"eval_extract\"` 재사용) "
        "수정 전 산출값 — 원본은 `frames_manifest.pre_isolation_fix_backup.json`에 보존됨.",
    ]

    out_md = _HERE / "recompute_frame_metadata_diff.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n저장: {out_md}")
    print(f"manifest 갱신됨: {MANIFEST}")


if __name__ == "__main__":
    main()
