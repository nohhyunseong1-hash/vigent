"""data_paths — 저장소 밖 미디어(영상·스틸) 위치를 한 곳에서 정한다.

★[감사 C5, 2026-09-06] 사고 영상·얼굴이 찍힌 이미지·고객사 설비 사진은 저장소에서 빼서
`../vigent_private_data/`(저장소 옆 폴더) 또는 환경변수 `VIGENT_DATA_DIR` 가 가리키는 곳으로 옮겼다.
벤치·측정 스크립트는 **이 모듈로만** 그 위치를 얻는다(각자 절대경로를 박지 않는다).

  from data_paths import media
  vids = sorted(media("runs/rfdetr/accident").glob("*.mp4"))

존재 여부는 여기서 검사하지 않는다 — 호출측이 `require()` 나 `exists()` 로 확인하고, 없으면
"어디에 무엇을 놓아야 하는지"를 안내한 뒤 종료한다(규칙 11: 0건 처리는 실패로 의심).
런타임(vigent-core 서버)은 이 모듈을 쓰지 않는다 — 측정 전용.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV = "VIGENT_DATA_DIR"
_REPO = Path(__file__).resolve().parent.parent
_DEFAULT = _REPO.parent / "vigent_private_data"


def data_dir() -> Path:
    """미디어 루트. `VIGENT_DATA_DIR` 우선, 없으면 저장소 옆 `vigent_private_data/`."""
    return Path(os.environ.get(ENV) or _DEFAULT).resolve()


def media(rel: str) -> Path:
    """저장소 기준 상대경로(예: "runs/rfdetr/multi_scene.mp4") → 미디어 루트 아래 절대경로."""
    return data_dir() / rel


def require(rel: str) -> Path:
    """존재하는 미디어 경로를 반환. 없으면 안내 메시지와 함께 FileNotFoundError."""
    p = media(rel)
    if not p.exists():
        raise FileNotFoundError(
            f"미디어 없음: {p}\n"
            f"  → 저장소 밖 미디어 폴더({data_dir()})에 '{rel}' 를 두거나 {ENV} 로 위치를 지정하세요.\n"
            f"  (2026-09-06 감사 C5: 영상·현장 이미지는 저장소에 두지 않는다 — CLEANUP_PLAN.md §5)"
        )
    return p
