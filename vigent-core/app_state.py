"""app_state.py — 라우터들이 공유하는 런타임 상태 (P1-7 main.py 분할).

★ main 을 import 하지 않는다(순환 import 방지). agents·vision_loader 만 의존한다.
분할된 도메인 라우터들은 여기서 STATE·DETECT_LOCK·load_theme 를 가져다 쓴다
(라우터 → main → 라우터 구조가 되지 않게).
"""
from __future__ import annotations

import os
import threading

import vision_loader
from agents import build_agents

DEFAULT_THEME = os.environ.get("VIGENT_THEME", "safety")

# 코어가 들고 있는 런타임 상태(테마별 파이프라인 + 에이전트)
STATE: dict[str, dict] = {}

# YOLO 추론 직렬화 락 — ultralytics 모델 로딩/추론은 동시성 안전하지 않다.
# 브라우저가 6fps로 동시에 /detect/frame 을 호출하면 같은 모델을 여러 스레드가
# 동시에 로드/추론하다 네이티브 크래시가 난다 → 락으로 한 번에 하나씩만.
DETECT_LOCK = threading.Lock()


def load_theme(theme: str) -> dict:
    """테마 1개를 로드해 STATE 에 캐시."""
    cfg = vision_loader.load_vision(theme)
    agents = build_agents(cfg)
    bundle = {"config": cfg, "agents": agents}
    STATE[theme] = bundle
    return bundle
