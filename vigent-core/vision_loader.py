"""
vision_loader.py — vision.yaml 파서 + 폴백 로더

역할:
  1) 테마의 vision.yaml 을 읽는다.
  2) 각 모델 슬롯의 파일이 실제로 존재하는지 검사한다.
  3) 없으면 fallback 으로 자동 강등한다(절대 저하 없음 = 가산식 + 폴백).
  4) "무엇이 실제 모델이고 무엇이 폴백인지" 상태표를 만들어 코어/프론트가 쓰게 한다.

⚠ 이 단계(§15-2)에서는 '구성(plan)만' 한다. 실제 모델 객체를 메모리에 올리지는 않는다.
   실제 추론 연결은 다음 단계에서 채운다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 프로젝트 루트 = 이 파일(vigent-core/vision_loader.py)의 두 단계 위
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────
# 데이터 구조
# ─────────────────────────────────────────────────────────────
@dataclass
class SlotStatus:
    """모델 슬롯 하나의 해석 결과(주 모델/폴백 중 무엇이 살아있는지)."""
    slot: str                       # 슬롯 이름 (예: person, ppe, pose, temporal)
    requested: str                  # vision.yaml 이 요청한 주 모델
    source: str                     # 'model' | 'fallback' | 'none'
    active: str | None              # 실제로 쓰일 대상(파일 경로 또는 휴리스틱 이름). 없으면 None
    available: bool                 # 이 슬롯이 동작 가능한가
    detail: str = ""                # 사람이 읽을 설명


@dataclass
class PipelineConfig:
    """vision.yaml 한 장을 해석한 결과 전체."""
    theme: str
    brand: str
    display_name: str
    raw: dict[str, Any]                                   # 원본 yaml 그대로
    slots: list[SlotStatus] = field(default_factory=list)  # 모델 슬롯 상태표

    # ── 편의 메서드 ──
    def summary(self) -> dict[str, Any]:
        """프론트 /system/capabilities 등에서 쓰기 좋은 요약 딕셔너리."""
        return {
            "theme": self.theme,
            "display_name": self.display_name,
            "slots": [
                {
                    "slot": s.slot,
                    "source": s.source,
                    "active": s.active,
                    "available": s.available,
                    "detail": s.detail,
                }
                for s in self.slots
            ],
            "fallback_count": sum(1 for s in self.slots if s.source == "fallback"),
            "disabled_count": sum(1 for s in self.slots if not s.available),
        }


# ─────────────────────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────────────────────
_WEIGHT_DIR = PROJECT_ROOT / "vigent-core" / "weights"
_MODEL_EXTS = (".pt", ".keras", ".onnx", ".tflite", ".h5")


def _looks_like_file(ref: str) -> bool:
    """모델 참조가 '파일 경로'인지(가중치 파일) 판단."""
    return isinstance(ref, str) and ref.lower().endswith(_MODEL_EXTS)


def _resolve(ref: str) -> Path:
    """모델 참조를 실제 경로로 해석.
    - 경로 형태(.pt 등)면 프로젝트 루트 기준으로 절대경로화.
    - 바레 이름(예: yolo11s)이면 weights/<name>.pt 후보로 본다.
    """
    if _looks_like_file(ref):
        p = Path(ref)
        return p if p.is_absolute() else (PROJECT_ROOT / p)
    return _WEIGHT_DIR / f"{ref}.pt"


def _file_exists(ref: str) -> bool:
    return _resolve(ref).exists()


def _is_heuristic(ref: Any) -> bool:
    """파일이 아닌 '규칙/휴리스틱' 폴백인지(none/heuristic/hsv_heuristic/torso_angle_rule 등)."""
    return isinstance(ref, str) and not _looks_like_file(ref) and not _file_exists(ref)


def _resolve_one(slot: str, model: Any, fallback: Any) -> SlotStatus:
    """주 모델 → 폴백 순으로 내려가며 실제 가용 대상을 고른다."""
    # 1) 주 모델이 파일이고 존재하면 그걸 쓴다
    if isinstance(model, str) and _looks_like_file(model) and _file_exists(model):
        return SlotStatus(slot, model, "model", str(_resolve(model)), True,
                          f"주 모델 사용: {_resolve(model).name}")
    # 2) 주 모델이 바레 이름인데 weights/ 에 대응 파일이 있으면 사용
    if isinstance(model, str) and not _looks_like_file(model) and _file_exists(model):
        return SlotStatus(slot, model, "model", str(_resolve(model)), True,
                          f"주 모델 사용: {_resolve(model).name}")

    # 3) 폴백으로 강등 — 폴백은 리스트일 수 있다(순서대로 시도)
    candidates = fallback if isinstance(fallback, list) else [fallback]
    for fb in candidates:
        if fb in (None, "none"):
            continue
        if _looks_like_file(fb):
            if _file_exists(fb):
                return SlotStatus(slot, str(model), "fallback", str(_resolve(fb)), True,
                                  f"폴백 가중치 사용: {_resolve(fb).name}")
            continue  # 폴백 파일도 없으면 다음 후보
        # 파일이 아닌 휴리스틱/규칙 폴백 → 항상 사용 가능
        return SlotStatus(slot, str(model), "fallback", str(fb), True,
                          f"폴백 휴리스틱 사용: {fb}")

    # 4) 아무것도 없음 → 이 슬롯만 비활성(나머지 파이프라인은 정상)
    return SlotStatus(slot, str(model), "none", None, False,
                      "모델·폴백 모두 없음 → 이 슬롯 비활성(기능은 무중단)")


# ─────────────────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────────────────
def theme_yaml_path(theme: str) -> Path:
    return PROJECT_ROOT / "themes" / theme / "vision.yaml"


def load_vision(theme: str = "safety") -> PipelineConfig:
    """테마의 vision.yaml 을 읽어 PipelineConfig(상태표 포함)로 반환."""
    path = theme_yaml_path(theme)
    if not path.exists():
        raise FileNotFoundError(f"vision.yaml 없음: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = PipelineConfig(
        theme=raw.get("theme", theme),
        brand=raw.get("brand", "VIGENT"),
        display_name=raw.get("display_name", theme),
        raw=raw,
    )

    perception = raw.get("perception", {}) or {}

    # detectors
    for det in perception.get("detectors", []) or []:
        cfg.slots.append(_resolve_one(det.get("id", "detector"),
                                      det.get("model"), det.get("fallback")))
    # pose
    if "pose" in perception:
        pose = perception["pose"]
        cfg.slots.append(_resolve_one("pose", pose.get("model"), pose.get("fallback")))
    # temporal(시계열 행동인식)
    if "temporal" in perception:
        tmp = perception["temporal"]
        cfg.slots.append(_resolve_one("temporal", tmp.get("model"), tmp.get("fallback")))

    return cfg


if __name__ == "__main__":
    # 단독 실행 시 상태표를 콘솔에 출력(점검용)
    import json

    import vlog
    _log = vlog.get("vigent.vision_loader")
    c = load_vision("safety")
    _log.info("테마 로드: %s (%s)", c.display_name, c.theme)
    _log.info("%s", json.dumps(c.summary(), ensure_ascii=False, indent=2))
