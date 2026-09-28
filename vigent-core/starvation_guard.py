"""starvation_guard.py — [B3] 검출 기아 2차 방어(슬롯 회수 → 파이프라인 재시작 → 승격).

원인(audit/b3_root_cause_2026-08-16.md): 카메라 동시 RTSP 세션 한도가 **2**(실측)인데
워커 1 + go2rtc 1 로 **여유가 0**이다. 카메라 재부팅처럼 슬롯이 잠깐 부족해지는 순간
재시도가 공격적인 go2rtc 가 슬롯을 선점하고, 지수 백오프로 쉬던 워커는 영구히 밀린다
→ **영상은 살고 검출만 죽는다**(실측 7분).

1차 방어는 백오프 상한 축소(worker._RECONNECT_MAX 30→5초)다. 이 모듈은 그래도 못 붙었을 때의
2차 방어로, 우선순위를 명시적으로 적용한다: **안전 검출 > 라이브 영상**.

  단계 1: stale_detect 가 `starve_grab_s`(기본 60초) 지속 → 해당 카메라의 go2rtc 스트림을
          내려 슬롯을 비운다(확대뷰는 끊기지만 검출이 산다)
  단계 2: 그래도 `starve_restart_s`(기본 120초) 지속 → 해당 카메라 워커만 재시작
  단계 3: `starve_max_fails`(기본 3)회 실패 → 프로세스 재기동 명령 실행
          (STABILITY.md 가 문서로만 설명하던 VIGENT_RESTART_CMD 를 여기서 **실제로 소비**한다)

감시 주기는 10초. 어떤 단계도 실패하면 로그만 남기고 다음 주기에 재시도한다(무중단 원칙).
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

import tuning
import vlog

_LOG = vlog.get("vigent.starvation")

# STABILITY.md:101-103 이 문서로만 설명하던 2차 워치독 설정 — 이제 실제 소비처가 있다.
_GRAB_S = float(os.environ.get("VIGENT_STARVE_GRAB_S") or tuning.val("stability", "starve_grab_s", 60.0))
_RESTART_S = float(os.environ.get("VIGENT_HANG_RESTART_S") or tuning.val("stability", "starve_restart_s", 120.0))
_MAX_FAILS = int(os.environ.get("VIGENT_HEALTH_FAILS") or tuning.val("stability", "starve_max_fails", 3))
_RESTART_CMD = os.environ.get("VIGENT_RESTART_CMD") or str(tuning.val("stability", "restart_cmd", "") or "")
_INTERVAL = 10.0

_state: dict[str, dict[str, Any]] = {}   # cid → {since, grabbed, restarts}
_stop = threading.Event()
_thread: threading.Thread | None = None


def _release_go2rtc_slot(cid: str) -> bool:
    """해당 카메라의 go2rtc 스트림을 삭제해 카메라 슬롯을 비운다.

    확대뷰는 끊긴다 — 의도된 트레이드오프다(안전 검출 우선). 다음 확대뷰 요청 때
    routers/cameras 가 스트림을 다시 등록하므로 영구 손실이 아니다.
    """
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:1984/api/streams?name={urllib.parse.quote(cid)}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            ok = 200 <= r.status < 300
        _LOG.warning("[기아 1단계] go2rtc 스트림 '%s' 해제 → 카메라 슬롯 회수 (ok=%s)", cid, ok)
        return ok
    except Exception as ex:  # noqa: BLE001  go2rtc 미기동 등 — 다음 주기에 재시도
        _LOG.info("[기아 1단계] go2rtc 스트림 해제 실패(무시): %s", ex)
        return False


def _restart_worker(cid: str) -> bool:
    """해당 카메라 워커만 재시작(다른 카메라 무영향).

    ★[2026-08-26] **등록부에 없는 카메라는 되살리지 않고 거둔다.**
    삭제된 카메라를 여기서 재생성하면 "등록부에 없는데 돌고 있는 워커"가 되어
    죽은 주소로 계속 재접속하고 /health 를 영구 unhealthy 로 만든다. 삭제 라우트의
    순서를 고쳐 경합 창을 닫았지만, **여기서도 막는다** — 워커를 되살리는 입구가
    두 곳이면 한 곳만 막아도 세 번째가 나온다(2026-08-21 remove() 수정을 우회한 전례).
    """
    try:
        import camera_registry as _reg
        import worker as _w
        from routers.cameras import _start as _cam_start  # 등록 정보(자격증명 포함)로 기동하는 정규 경로
        if _reg.get(cid) is None:
            _w.manager.remove(cid)                # 유령 워커 회수
            _state.pop(cid, None)
            _LOG.warning("[기아] 등록부에 없는 카메라 '%s' — 되살리지 않고 제거", cid)
            return False
        r = _w.manager.stop(cid)
        if not r.get("ok", True):                          # [CODE_AUDIT #8] 정지 미완료 → 재시작 대신 오류(이중 RTSP 세션 방지)
            _LOG.error("[기아 2단계] 워커 '%s' 정지 미완료 — 재시작 보류: %s", cid, r.get("error"))
            return False
        time.sleep(1.0)
        _cam_start(cid)
        _LOG.error("[기아 2단계] 워커 '%s' 재시작", cid)
        return True
    except Exception as ex:  # noqa: BLE001
        _LOG.error("[기아 2단계] 워커 재시작 실패: %s: %s", type(ex).__name__, ex)
        return False


def _escalate() -> None:
    """3단계: 프로세스 재기동. VIGENT_RESTART_CMD 미설정이면 경고만 남긴다."""
    if not _RESTART_CMD:
        _LOG.error("[기아 3단계] 프로세스 재기동 필요하나 VIGENT_RESTART_CMD 미설정 — 경고만 남김. "
                   "Windows 서비스 배포는 deploy/windows/install_service.ps1 참고")
        return
    if _RESTART_CMD.lower().startswith("exit:"):
        # ★[CODE_AUDIT_20260928 #4] 서비스(NSSM) 배포의 정규 경로 — 예전 'sc stop X & sc start X' 는 서비스 자신의 자식이
        #   실행해 NSSM 이 프로세스 트리를 죽이면 sc start 가 안 돌 수 있었다. 이제 지정 코드로 **스스로 종료**하고
        #   NSSM AppExit Default Restart(60 s 지연)가 다시 띄운다. 종료 전에 릴레이 OFF·큐 이월을 위해 graceful 경로를 먼저 밟는다.
        try:
            code = int(_RESTART_CMD.split(":", 1)[1] or 3)
        except ValueError:
            code = 3
        _LOG.error("[기아 3단계] 프로세스 자가 종료(exit %d) → 서비스 관리자(NSSM) 재기동에 위임", code)
        try:
            import main as _main  # graceful: 릴레이 OFF → 워커 → 큐 이월(실패해도 종료는 진행)
            _main._shutdown()
        except Exception as ex:  # noqa: BLE001
            _LOG.error("[기아 3단계] graceful 정리 중 예외(종료는 진행): %s: %s", type(ex).__name__, ex)
        _process_exit(code)
        return
    _LOG.error("[기아 3단계] 프로세스 재기동 실행: %s", _RESTART_CMD)
    try:
        proc = subprocess.Popen(_RESTART_CMD, shell=True)   # noqa: S602  운영자가 명시 설정한 명령
        _LOG.error("[기아 3단계] 재기동 명령 시작(pid %s) — 결과는 서비스 관리자 로그에서 확인", proc.pid)
    except Exception as ex:  # noqa: BLE001
        _LOG.error("[기아 3단계] 재기동 명령 실패: %s", ex)


def _process_exit(code: int) -> None:
    """os._exit 래퍼(테스트에서 바꿔 끼운다). 로그 핸들러를 먼저 비운다."""
    import logging
    logging.shutdown()
    os._exit(code)


def _tick() -> None:
    import health_status
    import worker as _w

    try:
        ws = _w.manager.status()
    except Exception:  # noqa: BLE001
        return
    now = time.time()
    for cid, st in (ws.get("cameras") or {}).items():
        cam = health_status.camera_status(st)
        if cam["status"] != health_status.STALE_DETECT:
            _state.pop(cid, None)                    # 회복 → 카운터 초기화
            continue
        s = _state.setdefault(cid, {"since": now, "grabbed": False, "restarts": 0})
        dur = now - s["since"]
        if not s["grabbed"] and dur >= _GRAB_S:
            s["grabbed"] = True
            _release_go2rtc_slot(cid)                # 1단계: 슬롯 회수
        elif s["grabbed"] and dur >= _RESTART_S:
            s["restarts"] += 1
            s["since"] = now                         # 재시작 후 다시 관찰
            s["grabbed"] = False
            if s["restarts"] >= _MAX_FAILS:
                _escalate()                          # 3단계
            else:
                _restart_worker(cid)                 # 2단계


def _loop() -> None:
    while not _stop.is_set():
        _stop.wait(_INTERVAL)
        if _stop.is_set():
            break
        try:
            _tick()
        except Exception:  # noqa: BLE001  감시자가 죽으면 안 된다
            _LOG.exception("기아 감시 주기 예외")


def start() -> threading.Thread:
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="vigent-starvation", daemon=True)
    _thread.start()
    _LOG.info("기아 감시 시작 — 1단계 %.0fs(슬롯 회수) / 2단계 %.0fs(워커 재시작) / 3단계 %d회 후 프로세스 재기동",
              _GRAB_S, _RESTART_S, _MAX_FAILS)
    return _thread


def stop() -> None:
    _stop.set()


def snapshot() -> dict[str, Any]:
    """/health 노출용 — 현재 기아 감시 상태."""
    return {cid: {"stale_s": round(time.time() - s["since"], 1),
                  "slot_grabbed": s["grabbed"], "restarts": s["restarts"]}
            for cid, s in _state.items()}
