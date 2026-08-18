"""health_status.py — [B2] 검출 생존 3단계 판정(healthy/degraded/unhealthy).

배경(audit/site_readiness_2026-08-16.md B2): 기존 /health 는 모델·버전·LLM 만 보고 **워커 상태를
전혀 보지 않았다**. 그래서 P0(go2rtc 가 카메라 세션을 선점해 검출 워커가 기아 → 영상은 살고
검출만 죽음)가 발생해도 /health 는 계속 200 OK 를 반환했다 — 외부 감시로는 영원히 정상.

이 모듈은 워커 하트비트를 읽어 3단계로 판정한다. 핵심은 **stale_detect** 상태다:
`last_frame_age` 는 작은데 `last_detect_age` 만 큰 경우 — 즉 "프레임은 들어오는데 추론이 멈춤".
이게 P0 의 지문이라 별도 상태로 구분해 워치독(B3)이 재시작 조건으로 쓸 수 있게 한다.

임계는 config/tuning.yaml `health:` 섹션에서 조정한다(하드코딩 아님 — 재부팅해도 유지).
"""
from __future__ import annotations

from typing import Any

import tuning

# 카메라 단위 상태
OK = "ok"
STALE_DETECT = "stale_detect"      # 프레임은 신선한데 검출만 늙음 = P0 지문
STALE_FRAME = "stale_frame"        # 프레임 자체가 안 들어옴(카메라·네트워크)
STOPPED = "stopped"                # 워커가 running=False
STARTING = "starting"              # 아직 첫 검출 전(기동/재연결 직후)

# 전체 상태
HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"


def thresholds() -> dict[str, float]:
    """판정 임계(초). config/tuning.yaml `health:` 로 조정."""
    return {
        # 이 시간 넘게 추론 완료가 없으면 검출 정지로 본다(기본 30s).
        "detect_stale_s": float(tuning.val("health", "detect_stale_s", 30.0)),
        # 프레임 자체가 이 시간 넘게 없으면 입력 끊김(기본 30s).
        "frame_stale_s": float(tuning.val("health", "frame_stale_s", 30.0)),
        # 기동/재연결 직후 첫 검출을 기다려주는 유예(기본 90s) — B4 의 startup grace 와 같은 취지.
        "startup_grace_s": float(tuning.val("health", "startup_grace_s", 90.0)),
    }


def camera_status(st: dict[str, Any], thr: dict[str, float] | None = None) -> dict[str, Any]:
    """워커 status() 1개 → 카메라 단위 판정.

    st 는 worker.Worker.status() 반환(마스킹된 값). 자격증명 등 민감 필드는 넣지 않는다.
    """
    thr = thr or thresholds()
    frame_age = st.get("last_frame_secs_ago")
    detect_age = st.get("last_detect_secs_ago")
    running = bool(st.get("running"))

    if not running:
        state = STOPPED
    elif detect_age is None:
        # 아직 한 번도 추론이 끝나지 않았다. 유예 기준은 **워커 가동시간**이다 —
        #   frame_age 를 기준으로 쓰면 "프레임은 계속 오는데 추론이 한 번도 안 되는" 상태에서
        #   frame_age 가 늘 작아 영원히 starting 에 머문다(실서버 확인 중 발견한 구멍).
        uptime = st.get("uptime_s")
        if uptime is not None and uptime <= thr["startup_grace_s"]:
            state = STARTING
        elif frame_age is not None and frame_age > thr["frame_stale_s"]:
            # 유예를 넘겼는데 프레임 자체가 안 들어온다 → 원인은 입력(카메라·네트워크)이지 추론이 아니다.
            state = STALE_FRAME
        elif uptime is None:
            state = STARTING          # 가동시간을 모르면 판정 보류(구버전 status 호환)
        else:
            state = STALE_DETECT
    elif detect_age > thr["detect_stale_s"]:
        # ★핵심 분기: 프레임은 신선한데 검출만 늙었나(P0 지문) / 프레임 자체가 끊겼나
        if frame_age is not None and frame_age <= thr["frame_stale_s"]:
            state = STALE_DETECT
        else:
            state = STALE_FRAME
    elif frame_age is not None and frame_age > thr["frame_stale_s"]:
        state = STALE_FRAME
    else:
        state = OK

    return {
        "status": state,
        "last_frame_age_s": frame_age,
        "last_detect_age_s": detect_age,
        "last_detect_latency_ms": st.get("last_detect_ms"),
        # [E1] 병목 특정용 단계 분해 — 락 대기 / 추론 실행 / 프레임 획득
        "lock_wait_ms": st.get("lock_wait_ms"),
        "infer_ms": st.get("infer_ms"),
        "read_ms": st.get("read_ms"),
        "decode_ms": st.get("decode_ms"),
        "session_generation": st.get("session_generation"),
        "dropped_frames": st.get("dropped_frames"),
        "reconnects": st.get("reconnects"),
        "hangs": st.get("hangs"),
    }


def overall(cameras: dict[str, dict[str, Any]], model_loaded: bool,
            alert_backlog: int = 0) -> str:
    """카메라별 판정 + 모델 로드 여부 → 전체 3단계.

    - unhealthy: 모델 미로드, 또는 **활성 카메라가 있는데 전부 검출 정지**
    - degraded : 일부 카메라 정지, 또는 미전송 경보가 남아 있음(B5 에서 채움)
    - healthy  : 나머지
    카메라가 0대면 '아직 아무것도 감시하지 않는 상태'라 healthy 로 본다(설치 직후 정상).
    """
    if not model_loaded:
        return UNHEALTHY
    active = {cid: c for cid, c in cameras.items() if c["status"] != STOPPED}
    if active:
        bad = [c for c in active.values() if c["status"] in (STALE_DETECT, STALE_FRAME)]
        if len(bad) == len(active):
            return UNHEALTHY
        if bad:
            return DEGRADED
    if alert_backlog > 0:
        return DEGRADED
    return HEALTHY


def build(worker_status: dict[str, Any], model_loaded: bool,
          alert_backlog: int = 0) -> tuple[str, dict[str, Any]]:
    """WorkerManager.status() → (전체상태, 카메라별 요약). /health 가 그대로 실어 보낸다."""
    thr = thresholds()
    cams = {cid: camera_status(st, thr)
            for cid, st in (worker_status.get("cameras") or {}).items()}
    return overall(cams, model_loaded, alert_backlog), cams
