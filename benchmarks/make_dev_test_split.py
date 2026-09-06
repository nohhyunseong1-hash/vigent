#!/usr/bin/env python3
"""[P-0] dev/test 분할 고정 스크립트 (2026-08-10 확정, 이후 재실행 금지).

109장을 **영상(비디오) 단위**로 dev/test에 배정한다(프레임 단위 무작위 분할 금지 — 같은 영상의
프레임들은 1000ms 간격이라 배경·조명·인물이 거의 동일해 근접중복이고, 프레임 단위로 섞으면 dev/test
간 누출이 생겨 test 성능이 실제보다 부풀려진다).

TEST_VIDEOS 는 사용자 승인을 받은 고정값이다(docs/perf_improvement_plan.md 최상단 원칙 참고) —
class 분포 근거는 benchmarks/dev_test_split.md 에 기록. **이 스크립트를 재실행해 TEST_VIDEOS 를
바꾸지 않는다** — 분할을 바꾸려면 새 사용자 승인이 필요하다(그 경우도 새 파일명으로 남기고
이 파일은 보존).

출력: data/field_eval/dev_test_split.json (git 추적 — data/ 전체가 gitignore 대상이라 -f 필요)
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
from data_paths import media  # noqa: E402  [M6-6] field_eval 은 저장소 밖(VIGENT_DATA_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

MANIFEST = media("field_eval") / "frames_manifest.json"
OUT = media("field_eval") / "dev_test_split.json"

# 사용자 승인(2026-08-10, [P-0]) — person/NO-Hardhat/NO-Safety-Vest/사람없음 비율이 전체 test
# 비율(32%)에 가장 고르게 맞는 조합으로 선정(benchmarks/dev_test_split.md 비교표 근거).
TEST_VIDEOS = {
    "KakaoTalk_20260807_000601541",
    "KakaoTalk_20260807_000632301",
    "KakaoTalk_20260807_000721865",
    "KakaoTalk_20260807_000442974",
}


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    videos = sorted({m["video"] for m in manifest})
    unknown = TEST_VIDEOS - set(videos)
    if unknown:
        raise SystemExit(f"[make_dev_test_split] TEST_VIDEOS 에 존재하지 않는 영상: {unknown}")

    dev_files = sorted(m["file"] for m in manifest if m["video"] not in TEST_VIDEOS)
    test_files = sorted(m["file"] for m in manifest if m["video"] in TEST_VIDEOS)
    if len(dev_files) + len(test_files) != len(manifest):
        raise SystemExit("[make_dev_test_split] 분할 후 프레임 수 불일치")

    out = {
        "created": str(date.today()),
        "method": "video-level(비디오 단위), 프레임 무작위 분할 아님 — 근접중복 누출 방지",
        "frozen": True,
        "note": "이 파일은 [P-0] 승인 후 고정됨. 재생성·변경 금지(docs/perf_improvement_plan.md 최상단 원칙).",
        "test_videos": sorted(TEST_VIDEOS),
        "dev_videos": sorted(set(videos) - TEST_VIDEOS),
        "dev": dev_files,
        "test": test_files,
        "n_dev": len(dev_files),
        "n_test": len(test_files),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"dev {len(dev_files)}장 / test {len(test_files)}장 → {OUT}")
    print("★git add -f 로 추적할 것(data/ 는 기본 gitignore 대상)")


if __name__ == "__main__":
    main()
