"""ort_tune.py — [Q9] onnxruntime 세션 옵션 튜닝(스핀 비활성·intra_op 스레드 제한).

배경(실측, `benchmarks/v1_slot_config_report.md` §5-2): onnxruntime 은 `SessionOptions` 를
주지 않으면 **intra_op 스레드 = 코어 수 + 스핀(busy-wait) 켜짐** 이 기본이다. 그 결과
pose(RTMPose) 는 실연산이 호출당 7.3ms 뿐인데 **CPU 를 0.82코어** 태웠다. 세션 옵션만
바꿔 재측정하니 **0.09코어(−89%)** 로 떨어지고 지연은 7.3 → 12.3ms 만 늘었다.

★[Q10, 2026-08-19] **기본 on** — 도입 시엔 규칙6에 따라 기본 off 였으나, 실서비스
짝지은 비교(카메라당 CPU 2.10→1.55코어 · 실카 검출 p95 162.9→85.8ms, 부작용 없음)로
검증한 뒤 기본값을 전환했다. `config/tuning.yaml` `onnxruntime.tune_sessions: false`
(또는 환경변수 `VIGENT_ORT_TUNE=0`)로 끄면 구 동작과 100% 동일하다(즉시 롤백 경로).

두 가지 적용 경로:
  1) `session_options()` — 세션을 우리가 직접 만드는 곳(detectors/rfdetr_adapter.py)에서
     `sess_options=` 로 넘긴다.
  2) `retune(obj)` — `rtmlib` 처럼 **옵션 주입 경로가 없는 라이브러리**용. 이미 만들어진
     세션을 같은 모델 파일로 다시 만들어 교체한다(가중치·그래프 동일 — 실행 옵션만 변경).
"""
from __future__ import annotations

from typing import Any

import tuning
import vlog

_LOG = vlog.get("vigent.ort_tune")


def enabled() -> bool:
    """[Q10, 2026-08-19] 기본 True — 서비스 실측으로 검증 후 기본 on 으로 전환했다.

    근거: 실서비스 짝지은 비교(N=1/4/7, 같은 날·같은 조건)에서 카메라당 CPU
    2.10 → 1.55코어(회복 0.55코어/카메라), 실카메라 검출 p95 162.9 → 85.8ms 로
    부작용 없음(오히려 개선). 상세: benchmarks/e1_bottleneck_report.md.
    끄려면 config/tuning.yaml `onnxruntime.tune_sessions: false`(즉시 롤백 경로)."""
    return bool(tuning.val("onnxruntime", "tune_sessions", True, env="VIGENT_ORT_TUNE"))


def intra_threads() -> int:
    """intra_op 스레드 수. 실측상 4 가 CPU·지연 균형점(1 은 CPU 최소지만 지연 +3ms)."""
    try:
        return max(1, int(tuning.val("onnxruntime", "intra_op_threads", 4)))
    except Exception:  # noqa: BLE001
        return 4


def allow_spinning() -> bool:
    """스핀 허용 여부. 기본 False(=끄는 것이 이 기능의 목적)."""
    return bool(tuning.val("onnxruntime", "allow_spinning", False))


def session_options() -> Any:
    """튜닝된 SessionOptions. 비활성이거나 onnxruntime 이 없으면 None."""
    if not enabled():
        return None
    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001  onnxruntime 미설치 → 조용히 미적용
        return None
    so = ort.SessionOptions()
    so.intra_op_num_threads = intra_threads()
    so.inter_op_num_threads = 1
    so.add_session_config_entry("session.intra_op.allow_spinning",
                                "1" if allow_spinning() else "0")
    return so


def _find_tools(obj: Any, seen: set[int] | None = None, depth: int = 0) -> list[Any]:
    """`.session` + `.onnx_model` 을 가진 객체를 재귀로 찾는다(rtmlib BaseTool 계열).

    ★`callable(v)` 로 거르면 안 된다 — rtmlib 의 YOLOX·RTMPose 는 `__call__` 을 정의한다.
    """
    if seen is None:
        seen = set()
    if depth > 4 or id(obj) in seen:
        return []
    seen.add(id(obj))
    found: list[Any] = []
    if hasattr(obj, "session") and hasattr(obj, "onnx_model"):
        found.append(obj)
    for name in dir(obj):
        if name.startswith("__"):
            continue
        try:
            v = getattr(obj, name)
        except Exception:  # noqa: BLE001
            continue
        if hasattr(v, "__dict__"):
            found += _find_tools(v, seen, depth + 1)
    return found


def retune(obj: Any) -> int:
    """옵션 주입 경로가 없는 라이브러리의 세션을 교체한다. 반환: 교체한 세션 수.

    비활성이면 0 을 반환하고 **아무것도 건드리지 않는다**. 실패해도 예외를 올리지 않는다
    (기존 세션이 그대로 남아 기능은 죽지 않는다 — 절대 저하 없음).
    """
    so = session_options()
    if so is None:
        return 0
    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for t in _find_tools(obj):
        try:
            t.session = ort.InferenceSession(path_or_bytes=t.onnx_model, sess_options=so,
                                             providers=["CPUExecutionProvider"])
            n += 1
        except Exception:  # noqa: BLE001  교체 실패 → 기존 세션 유지(무중단)
            _LOG.warning("ORT 세션 재구성 실패(기존 세션 유지): %s", t.onnx_model, exc_info=True)
    if n:
        _LOG.info("ORT 세션 %d개 튜닝 적용(intra_op=%d · spin=%s)",
                  n, intra_threads(), "on" if allow_spinning() else "off")
    return n
