"""runtime_config.py — 런타임 가변 config 격리 (B2).

문제: `config/*.json|yaml` 중 UI/엔드포인트가 런타임에 덮어쓰는 파일(위험구역·PPE 규칙)이
git 추적 대상이라, 현장이 값을 바꿀 때마다 워킹트리가 더러워지고 실수로 커밋에 섞였다.

해결: **config/ 는 커밋된 읽기전용 '시드'**, **실제 런타임 write 는 data/config/(gitignore)** 로.
- 읽기(read_path): 런타임(data/<cfg_rel>) 우선 → 없으면 시드(<cfg_rel>) 폴백.
  → fresh clone·CI 는 시드 기본값을, 기존 배포는 자신이 그린 config/ 값을 투명하게 읽는다.
- 쓰기(runtime_path): 항상 data/ 하위 → config/ 는 다시는 런타임에 오염되지 않는다.

★ 의존 없음(pathlib 만). 어느 모듈이든 순환 걱정 없이 import 한다.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def runtime_path(cfg_rel: str, root: Path = _ROOT) -> Path:
    """쓰기용 경로: config/ 시드 상대경로 → data/ 하위 런타임 경로(gitignore).
    예: 'config/danger_zone.json' → <root>/data/config/danger_zone.json."""
    return root / "data" / cfg_rel


def read_path(cfg_rel: str, root: Path = _ROOT) -> Path:
    """읽기용 경로: 런타임(data/<cfg_rel>) 이 있으면 그것, 없으면 시드(<cfg_rel>)."""
    rt = runtime_path(cfg_rel, root)
    return rt if rt.exists() else (root / cfg_rel)
