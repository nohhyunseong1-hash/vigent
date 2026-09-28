"""data_paths — 저장소 밖 미디어(영상·스틸) 위치를 한 곳에서 정한다.

★[감사 C5, 2026-09-06] 사고 영상·얼굴이 찍힌 이미지·고객사 설비 사진은 저장소에서 빼서
`../vigent_private_data/`(저장소 옆 폴더) 또는 환경변수 `VIGENT_DATA_DIR` 가 가리키는 곳으로 옮겼다.
벤치·측정 스크립트는 **이 모듈로만** 그 위치를 얻는다(각자 절대경로를 박지 않는다).

  from data_paths import media
  vids = sorted(media("runs/rfdetr/accident").glob("*.mp4"))

존재 여부는 여기서 검사하지 않는다 — 호출측이 `require()` 나 `exists()` 로 확인하고, 없으면
"어디에 무엇을 놓아야 하는지"를 안내한 뒤 종료한다(규칙 11: 0건 처리는 실패로 의심).
런타임(vigent-core 서버)에서는 retention(보존 그룹 field_eval)·privacy(보호 폴더)만 이 모듈로 위치를 얻는다
([CODE_REVIEW M6-6]) — 그 외는 측정 전용.
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


FIELD_ENV = "VIGENT_FIELD_ROOT"


def field_root() -> Path:
    """[CODE_AUDIT_20260928 B-4] 현장 원본(녹화·프레임 = 개인영상정보, 저장소·OneDrive 밖) 루트.
    `VIGENT_FIELD_ROOT` 우선, 없으면 미디어 루트 **옆** `vigent_field/`(개발기: D:\vigent_private_data 옆 D:\vigent_field).
    스크립트가 `D:\vigent_field\20260827\\...` 를 직접 적지 않고 여기서 받는다(방문 날짜는 인자)."""
    v = os.environ.get(FIELD_ENV)
    return Path(v).expanduser().resolve() if v else (data_dir().parent / "vigent_field")


# ── [CODE_REVIEW M6-6 정정, 2026-09-06 대표 지시] 현장 평가 자료(field_eval)는 두 곳에 나뉜다 ──
#   · 이미지(jpg 등, 얼굴이 찍힌 현장 프레임 = 개인영상정보) → 저장소 밖 VIGENT_DATA_DIR/field_eval
#   · 라벨·정답지·매니페스트(txt/json/md — PII 아님, 평가 정답지로 버전 관리) → 저장소 data/field_eval (git 추적, 정본)
#   스크립트는 field_eval("labels") / field_eval("frames") 처럼 상대경로만 말하고, 어느 쪽인지는 여기서 정한다.
_FE_REPO = _REPO / "data" / "field_eval"
_FE_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_FE_IMAGE_DIRS = {"frames", "images", "hints", "montages", "labels_draft_preview", "review_000633827",
                  "s1_miss_montage", "v1_augmentation_preview"}


class _FieldEvalRouter:
    """아직 이미지/라벨이 갈리지 않은 디렉터리(예: '', 'pilot20', 'rest89') — `/` 로 내려가면서 결정한다."""
    __slots__ = ("rel",)

    def __init__(self, rel: str) -> None:
        self.rel = rel

    def __truediv__(self, part: object) -> "Path | _FieldEvalRouter":
        return field_eval(f"{self.rel}/{part}" if self.rel else str(part))

    def __fspath__(self) -> str:                 # 문자열로 쓰이면 라벨 쪽(저장소) 경로
        return str(_FE_REPO / self.rel) if self.rel else str(_FE_REPO)

    def __str__(self) -> str:
        return self.__fspath__()

    def __repr__(self) -> str:
        return f"field_eval({self.rel!r}: 라벨={_FE_REPO / self.rel} · 이미지={media('field_eval') / self.rel})"


def field_eval(rel: str = "") -> "Path | _FieldEvalRouter":
    """field_eval 상대경로 → 실제 위치. 이미지 확장자/이미지 디렉터리(frames·images·hints·montages·preview…)는
    저장소 밖(VIGENT_DATA_DIR), 그 외 파일과 labels* 디렉터리는 저장소 data/field_eval. 미확정 디렉터리는 라우터."""
    r = str(rel).replace("\\", "/").strip("/")
    parts = [p for p in r.split("/") if p]
    if parts and Path(parts[-1]).suffix.lower() in _FE_IMAGE_EXT:
        return media("field_eval") / r
    if parts and Path(parts[-1]).suffix:            # 이미지 아닌 파일(txt/json/md/csv …) — 이미지 폴더 안이라도 저장소
        return _FE_REPO / r
    if any(p in _FE_IMAGE_DIRS for p in parts):
        return media("field_eval") / r
    if any(p.startswith("labels") for p in parts):  # labels · labels_draft · labels_backup_* (preview 는 위에서 이미지)
        return _FE_REPO / r
    return _FieldEvalRouter(r)


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
