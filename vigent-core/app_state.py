"""app_state.py — 라우터들이 공유하는 런타임 상태 (P1-7 main.py 분할).

★ main 을 import 하지 않는다(순환 import 방지). agents·vision_loader 만 의존한다.
분할된 도메인 라우터들은 여기서 STATE·DETECT_LOCK·load_theme 를 가져다 쓴다
(라우터 → main → 라우터 구조가 되지 않게).
"""
from __future__ import annotations

import os
import threading
import time

import vision_loader
from agents import build_agents

DEFAULT_THEME = os.environ.get("VIGENT_THEME", "safety")

# 코어가 들고 있는 런타임 상태(테마별 파이프라인 + 에이전트)
STATE: dict[str, dict] = {}

# 추론 직렬화 락 — 모든 MPS 추론엔진(guard.detect·rfdetr_service.detect·VLM summarize/quick)을
#   '한 번에 하나만' 실행시켜 검출(PyTorch-MPS)과 VLM(MLX)이 Metal 을 동시에 만지지 않게 한다.
#   ★F-14 본질은 이 락으로 못 막는다: mlx-vlm 을 '수명 짧은' 워커 스레드에서 돌리면 그 스레드
#     teardown 시 네이티브 MLX 스레드가 GIL 없이 파이썬을 호출해 프로세스가 즉사한다(exit 133).
#     실제 해소는 rfdetr_service._VLM_RUNNER(VLM 전용 고정 데몬 스레드)다 — 이 락은 '동시 Metal 접근
#     배제'라는 보조 역할. 상세·실증: benchmarks/FINDINGS.md F-14(2026-07-20).
#   ★ RLock: 락 보유 중(`with lock:`) 하위 호출이 같은 락을 재획득하는 경로(예: VLM 확정 체인)가
#     있어 재진입 필요 — 일반 Lock 이면 자기 데드락.
#     (VLM 실행은 고정 스레드로 위임되나 락은 여전히 호출 스레드가 잡으므로 재진입 계약 유지.)
DETECT_LOCK = threading.RLock()


def load_theme(theme: str) -> dict:
    """테마 1개를 로드해 STATE 에 캐시."""
    cfg = vision_loader.load_vision(theme)
    agents = build_agents(cfg)
    bundle = {"config": cfg, "agents": agents}
    STATE[theme] = bundle
    return bundle

# uptime 기준 시각(모듈 로드 시각) — main 에서 re-import(P1-7)
_START_TS = time.time()
