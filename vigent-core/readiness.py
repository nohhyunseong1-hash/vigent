"""readiness.py — [B4] 콜드 스타트 예열과 워치독 분리.

배경(audit/site_readiness_2026-08-16.md B4): 모델 콜드 로드가 실측 **12.5초**
(person 8.4 + ppe 2.0 + fire_smoke 2.1)인데 hang 워치독은 15초라 여유가 2.5초뿐이었다.
카메라 디코드 부하가 겹치면 넘어가고, 넘으면 워커를 죽여 로드를 처음부터 다시 시작해
**영영 못 끝내는 무한 재시작**에 빠진다(2026-08-13 실측: 워커 재시작 45회).
당시 회피는 `VIGENT_HANG_TIMEOUT=60` 환경변수였는데, 이건 **커밋에 없어서 재부팅하면
사라지는 값**이었다 — 존재하지 않는 설정과 같다.

해법은 임계를 늘리는 게 아니라 **단계를 나누는 것**이다:
  starting: 모델 로드 + 더미 추론 1회가 끝나기 전. 워커를 아직 붙이지 않는다.
  ready   : 예열 완료. 이때부터 워커를 기동하고 워치독 15초가 정상 적용된다.

즉 워커는 **이미 따뜻한 모델**에 붙으므로 첫 검출이 느릴 이유가 없고, 워치독을 느슨하게
할 필요도 없다.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import vlog

_LOG = vlog.get("vigent.readiness")
_ROOT = Path(__file__).resolve().parent.parent

STARTING = "starting"
READY = "ready"
FAILED = "failed"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "phase": STARTING,
    "started_at": time.time(),
    "ready_at": None,
    "warmup_s": None,       # 기동→ready 소요(초) — 실측 기록용
    "error": "",
}


def phase() -> str:
    with _lock:
        return str(_state["phase"])


def is_ready() -> bool:
    return phase() == READY


def snapshot() -> dict[str, Any]:
    """/health 노출용 요약(민감정보 없음)."""
    with _lock:
        s = dict(_state)
    s["elapsed_s"] = round(time.time() - s["started_at"], 1)
    return {"phase": s["phase"], "warmup_s": s["warmup_s"],
            "elapsed_s": s["elapsed_s"], "error": s["error"]}


def _mark(ph: str, err: str = "") -> None:
    with _lock:
        _state["phase"] = ph
        _state["error"] = err
        if ph == READY:
            now = time.time()
            _state["ready_at"] = now
            _state["warmup_s"] = round(now - _state["started_at"], 2)


def required_weights_missing() -> list[str]:
    """[B8] weights_manifest.json 의 required 가중치 중 없는 파일 목록.

    조용한 폴백 금지: 필수 커스텀 가중치가 없으면 RF-DETR 이 COCO 로 폴백해 **검출이 무력화된
    상태로 정상처럼 동작**한다(F-8 사고). 기동 시 이걸 잡아 명시적으로 멈춘다.
    """
    import json

    man_path = _ROOT / "weights_manifest.json"
    wdir = _ROOT / "vigent-core" / "weights"
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  매니페스트가 없으면 검사 자체를 건너뛴다(구배포 호환)
        return []
    return [w["file"] for w in man.get("weights", [])
            if w.get("required") and not (wdir / w["file"]).exists()]


def warmup(guard: Any, detectors: list[str] | None = None) -> dict[str, Any]:
    """모델 로드 + 더미 추론 1회. 완료되면 phase=ready.

    더미 추론까지 하는 이유: RF-DETR 은 첫 순전파에서 컴파일·커널 캐시가 만들어져
    '로드 성공'만으로는 첫 프레임 지연이 사라지지 않는다. 실제 추론을 한 번 돌려야
    워커의 첫 검출이 정상 속도로 끝난다.
    """
    import numpy as np

    # [B8] 필수 가중치 없으면 예열 자체를 실패로 확정한다 — COCO 로 조용히 폴백해
    #   "정상처럼 보이는데 아무것도 못 잡는" 상태(F-8)로 운영되는 것을 막는다.
    missing = required_weights_missing()
    if missing:
        msg = ("필수 가중치 없음: " + ", ".join(missing)
               + " — `python scripts/fetch_weights.py` 를 실행해 조달하세요")
        _mark(FAILED, msg)
        _LOG.error("★기동 중단 수준 오류 — %s", msg)
        return {"ok": False, "error": msg, "slots": []}

    t0 = time.time()
    dets = detectors or ["person", "ppe", "fire_smoke"]
    img = np.zeros((720, 1280, 3), dtype=np.uint8)   # 더미 1프레임(실입력 없이 커널만 예열)
    done: list[str] = []
    try:
        for slot in dets:
            st = time.time()
            guard.detect(img, detectors=[slot], track_key="warmup")
            done.append(slot)
            _LOG.info("예열 slot=%s %.1fs", slot, time.time() - st)
        _mark(READY)
        el = round(time.time() - t0, 2)
        _LOG.info("★예열 완료 %.2fs (slots=%s) — 이제 워커 기동, 워치독 정상 적용", el, ",".join(done))
        return {"ok": True, "warmup_s": el, "slots": done}
    except Exception as ex:  # noqa: BLE001  예열 실패해도 서버는 살리고 상태로 드러낸다
        _mark(FAILED, f"{type(ex).__name__}: {ex}")
        _LOG.error("예열 실패(%.1fs): %s — /health phase=failed 로 노출", time.time() - t0, ex)
        return {"ok": False, "error": str(ex), "slots": done}


def start_background(guard: Any, on_ready: Any = None,
                     detectors: list[str] | None = None) -> threading.Thread:
    """예열을 백그라운드로 돌린다 — 서버는 즉시 응답하되 /health 는 starting(503).

    on_ready: 예열 성공 후 호출할 콜백(워커 자동기동을 여기 붙인다 — 따뜻한 모델에만 붙도록).
    """
    def _run() -> None:
        r = warmup(guard, detectors)
        if r.get("ok") and on_ready is not None:
            try:
                on_ready()
            except Exception:  # noqa: BLE001
                _LOG.exception("예열 후 콜백 실패")

    th = threading.Thread(target=_run, name="vigent-warmup", daemon=True)
    th.start()
    return th
