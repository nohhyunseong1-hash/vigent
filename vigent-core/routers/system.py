"""routers/system.py — 헬스체크·시스템 상태 (P1-7 분할). main 미import."""
import json
import os
import re as _re
import time as _time

from app_state import _START_TS, DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme


def _startup_warnings() -> list:
    """[M7-3] 기동 시 선택 서비스 실패 목록(app_state.STARTUP_WARNINGS) — 지연 import 로 순환 없음."""
    try:
        import app_state as _as
        return list(_as.STARTUP_WARNINGS)
    except Exception:  # noqa: BLE001
        return []
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from web_util import _ROOT, product_version

router = APIRouter()

# ★[F31, 2026-08-24] /health 는 무인증 허용(워치독용)이라 응답에 내부 절대경로를 싣지 않는다.
#   슬롯 로드 실패 원인은 현장 진단에 꼭 필요하지만, 원인 문자열에 가중치 절대경로가 섞여
#   나온다(예: "FileNotFoundError: D:\vigent_original\vigent-core\weights\x.pth").
#   경로처럼 보이는 토큰만 **파일명으로 축약**한다 — 파일명은 진단에 필요하고 노출 가치가 낮다.
_PATH_RE = _re.compile(r"(?:[A-Za-z]:)?(?:[\\/][^\\/\s'\"]+){2,}")


def _strip_paths(msg: str, limit: int = 200) -> str:
    """오류 문자열에서 경로를 파일명으로 축약하고 길이를 제한한다."""
    out = _PATH_RE.sub(lambda m: m.group(0).replace("\\", "/").rsplit("/", 1)[-1], msg)
    return out[:limit]


def _dropped_by_error(mstatus: dict) -> dict:
    """[F-34] 워커별 state["frame_errors"]({frames, alerts, last_error, last_at})를 카메라 합산한다.
    last_error/last_at 은 가장 최근 것 하나. 오류 문자열은 경로 축약(/health 무인증 원칙)."""
    agg: dict = {"frames": 0, "alerts": 0, "last_error": None, "last_at": None, "cameras": {}}
    try:
        for cid, st in (mstatus.get("cameras") or {}).items():
            fe = (st or {}).get("frame_errors") or {}
            if not fe:
                continue
            agg["frames"] += int(fe.get("frames", 0) or 0)
            agg["alerts"] += int(fe.get("alerts", 0) or 0)
            agg["cameras"][str(cid)] = int(fe.get("frames", 0) or 0)
            at = fe.get("last_at")
            if at and (agg["last_at"] is None or str(at) >= str(agg["last_at"])):
                agg["last_at"] = at
                agg["last_error"] = _strip_paths(str(fe.get("last_error") or ""))
    except Exception:  # noqa: BLE001  헬스체크를 죽이지 않는다
        pass
    return agg


@router.get("/health")
def health(theme: str = DEFAULT_THEME):
    """확장 헬스체크(C-S1): 제품 버전·모델별 버전/SHA·uptime·backend 구성.
    [1단계 M-2] 토큰 모드에서는 인증 필요(세션 쿠키 또는 Bearer) — 무인증 생존 점검은 /healthz.
    SHA 는 weights_manifest.json 기준(앞 16자)."""
    backend = {}
    bundle = STATE.get(theme)
    if bundle:
        raw = getattr(bundle["config"], "raw", {}) or {}
        backend = (raw.get("perception", {}) or {}).get("backend", {})
    man = {}
    try:
        man = json.loads((_ROOT / "weights_manifest.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    models = [{"file": e.get("file"), "slot": e.get("slot"), "backend": e.get("backend"),
               "version": e.get("version"), "sha256": (e.get("sha256") or "")[:16]}
              for e in man.get("weights", [])]
    # F-8: 매니페스트(선언)와 별개로 '실제 로드된' rfdetr 커스텀 가중치 상태(state·SHA)를 노출.
    #   silent 폴백 탐지용 — state=LOADED 면 커스텀 탑재, MISSING_FALLBACK 이면 COCO 폴백(검출 저하).
    #   매니페스트 SHA 와 rfdetr_slots[].sha16 이 어긋나면 배포 실체가 선언과 다르다는 신호.
    rfdetr_slots = []
    # ★[F1, 2026-08-21] slot_degraded 도 함께 꺼낸다. guard 는 슬롯 추론이 연속 실패하면
    #   이 값을 세우고 "★/health 에서 확인할 것" 이라 로그를 남기는데, 정작 /health 가
    #   읽지 않아 **person 슬롯이 죽어도 healthy** 였다(리뷰 F1). 이제 본문에 노출하고
    #   전체 판정에도 넣는다.
    slot_degraded: dict = {}
    slot_errors: dict = {}          # ★[F31] 슬롯이 왜 못 떴는지 — 원인 문자열(경로는 자름)
    if bundle:
        _g = bundle["agents"].get("Guard")
        if _g is not None:
            try:
                _gs = _g.status()
                rfdetr_slots = _gs.get("rfdetr_slots", [])
                slot_degraded = _gs.get("slot_degraded", {}) or {}
                # ★[F31, 2026-08-24] load_errors 를 /health 로 꺼낸다. 원인 문자열은 guard 가
                #   이미 갖고 있었는데(예: "RuntimeError: ... weights corrupted") 아무도 꺼내지
                #   않아, 현장에서 슬롯이 죽어도 **왜 죽었는지 알 방법이 없었다**.
                #   ★경로는 자르고 파일명만 남긴다 — /health 는 인증 뒤이긴 하나 내부 절대경로를
                #     응답에 싣지 않는다는 원칙(자격증명·경로 비노출).
                slot_errors = {k: _strip_paths(str(v))
                               for k, v in (_gs.get("load_errors", {}) or {}).items() if v}
            except Exception:  # noqa: BLE001
                pass
    # ★[F6] 자동 스윕 스레드 상태 — 조회 실패가 헬스체크를 죽이면 안 된다.
    retention_sweep: dict = {}
    try:
        import retention_scheduler as _rs
        retention_sweep = _rs.status()
    except Exception:  # noqa: BLE001
        retention_sweep = {"error": "retention_scheduler 상태 조회 실패"}
    # LLM provider 실값 노출(추측 금지) — 키 값은 절대 내보내지 않고 존재여부만.
    #   ollama 제거 후 openai 단일화(2026-07-14). 키 없으면 규칙 기반 폴백으로 동작(기능 유지).
    llm = {}
    try:
        import llm_provider as _llm
        llm = _llm.status()
    except Exception:  # noqa: BLE001  provider 상태 조회 실패해도 헬스체크는 죽지 않는다
        llm = {"provider": "unknown", "available": False}
    # [Z-2] 디스크 보존 정책 상태 — 캐시된 status.json만 읽는다(라이브 경로에서 디렉터리
    #   재스캔 없음). 침묵 실패 금지(Q-3 원칙과 동일): 활성화됐는데 실행 기록이 없거나
    #   경고가 쌓여 있으면 여기서 드러난다.
    disk_retention: dict = {"enabled": False, "last_run": None, "warnings": []}
    try:
        import tuning as _tuning
        from retention import read_status as _read_status
        disk_retention["enabled"] = bool(_tuning.section("retention").get("enabled", False))
        status = _read_status()
        if status:
            disk_retention["last_run"] = status.get("last_run")
            disk_retention["warnings"] = status.get("warnings", [])
            # [P1b] 실제로 무엇을 지웠는지 노출 — "정책은 켰는데 아무것도 안 지워지고 있다"를 드러낸다
            disk_retention["dry_run"] = status.get("dry_run")
            disk_retention["deleted_count"] = status.get("deleted_count")
            disk_retention["deleted_bytes"] = status.get("deleted_bytes")
            disk_retention["pending_count"] = status.get("pending_count")
            if status.get("first_run_notice"):
                disk_retention["warnings"] = list(disk_retention["warnings"]) + [
                    "첫 주기 — 삭제 예정 목록만 기록했고 실제 삭제는 다음 주기부터"]
        elif disk_retention["enabled"]:
            disk_retention["warnings"] = ["보존 정책이 활성화됐으나 스위퍼가 아직 실행된 기록이 없음"]
    except Exception:  # noqa: BLE001  조회 실패해도 헬스체크는 죽지 않는다
        pass
    # [B2] 검출 생존 판정 — 워커 하트비트를 읽어 healthy/degraded/unhealthy 로 종합한다.
    #   기존 /health 는 워커를 전혀 보지 않아, P0(영상 생존·검출 사망)에서도 계속 200 OK 였다.
    #   ★status 는 이제 "ok" 고정이 아니라 실제 판정값이다. unhealthy 면 HTTP 503 으로 나간다
    #   (외부 워치독·모니터링이 코드만 보고도 장애를 잡을 수 있게).
    overall = "healthy"
    cameras: dict = {}
    phase = "ready"
    warm: dict = {}
    alerts: dict = {}
    # [P1a/P1c] 개인정보 기술통제 상태 — 비식별화 설정과 저장 폴더 암호화 여부를 사실대로 노출.
    #   법적 충분성 판단은 하지 않는다(사람이 검토). "설정만 있고 실제로는 꺼져 있다"를 드러내는 것이 목적.
    privacy_status: dict = {}
    try:
        import privacy as _pv
        privacy_status = {**_pv.status(), **_pv.storage_status(), **_pv.failure_status()}
    except Exception:  # noqa: BLE001
        privacy_status = {"error": "privacy 상태 조회 실패"}
    # [P3a] 물리 출력 상태. ★off_failed 는 "사이렌이 켜진 채 남았을 수 있다"는 뜻이라
    #   degraded 로 올린다 — 현장에서 가장 시급한 이상이다.
    relay_status: dict = {}
    try:
        import relay as _rl
        relay_status = _rl.status()
    except Exception:  # noqa: BLE001
        relay_status = {"error": "relay 상태 조회 실패"}
    # try 안에서 채우되, 실패해도 body 구성이 NameError 로 죽지 않도록 선초기화한다.
    active_dets: list = []
    disabled_dets: dict = {}
    alert_warnings: list = []
    dropped_by_error: dict = {"frames": 0, "alerts": 0, "last_error": None, "last_at": None, "cameras": {}}
    try:
        import health_status
        import readiness
        import worker as _w
        active_dets = _w.active_detectors()
        disabled_dets = _w.disabled_detectors()
        phase = readiness.phase()
        warm = readiness.snapshot()
        model_loaded = bool(bundle) and bool(rfdetr_slots)
        # [B5] 미전송 경보가 남아 있으면 degraded — "경보가 안 나갔는데 정상"은 있을 수 없다.
        try:
            import alert_queue
            alerts = alert_queue.counts()
        except Exception:  # noqa: BLE001
            alerts = {}
        # [M4-1·M4-2] 전달 상태: 채널 미설정 자체는 경고만, critical/high 폐기·최근 1h 데드레터는 degraded
        disp_status: dict = {}
        try:
            _disp = bundle["agents"].get("Dispatcher") if bundle else None
            disp_status = _disp.status() if _disp is not None else {}
        except Exception:  # noqa: BLE001
            disp_status = {}
        try:                                         # [M4-6] 전송 대기열 폐기·깊이·스레드 생존
            import alert_notify
            _ns = alert_notify.stats()
            disp_status = {**disp_status, "dropped": _ns.get("dropped", 0)}
        except Exception:  # noqa: BLE001
            _ns = {}
        # ★[F-35, 2026-09-22] 조용한 실패 방지 — 채널이 살아 있는지를 /health 가 말하게 한다.
        #   2026-08-21~09-10 20일간 텔레그램 401 로 경보 213건이 못 갔는데 /health 는 조용했다.
        #   selftest 는 캐시를 보므로 여기서 불러도 매번 망을 타지 않는다(확정 상태면 즉시 반환).
        notify_block: dict = {}
        try:
            from agents import dispatcher as _disp_mod
            _st = _disp_mod.selftest_channels()
            notify_block = {
                "last_success": alerts.get("last_success_ts"),
                "dead_count": int(alerts.get("dead", 0) or 0),
                # ★[F-35] 채널별 — "하나라도 성공" 판정이라 이메일만 죽은 상태가 숨는다.
                "email_last_success": alerts.get("email_last_success"),
                "email_dead_count": alerts.get("email_dead_count", 0),
                "config_error": disp_status.get("last_config_error"),
                "config_error_count": disp_status.get("config_error_count", 0),
                "channels_configured": disp_status.get("channels_configured"),
                "selftest_state": _st.get("state"),
                "selftest_reason": _st.get("reason"),
                "selftest_unknown_too_long": _disp_mod.selftest_status().get("unknown_too_long", False),
            }
            # [F-35] SMTP 연결 확인(로그인 안 함) + ★**단일 채널 경고**
            #   2026-08-21~09-10 에 텔레그램 하나뿐이었고 그게 죽자 경보가 아무에게도 안 갔다.
            #   두 번째 채널이 없다는 사실 자체가 위험 신호다 — 조용히 두지 않는다.
            try:
                _sm = _disp_mod.selftest_smtp()
                notify_block["smtp_state"] = _sm.get("state")
                notify_block["smtp_reason"] = _sm.get("reason")
                _remote_n = sum(1 for k in ("telegram", "email", "webhook")
                                if disp_status.get(k))
                notify_block["remote_channel_count"] = _remote_n
                notify_block["single_channel"] = bool(_remote_n == 1)
            except Exception:  # noqa: BLE001
                pass
            # [F-35] heartbeat 도 실패할 수 있다 — 그 실패가 안 보이면 '침묵이 신호' 설계가 무너진다.
            try:
                import notify_heartbeat
                _hb = notify_heartbeat.status()
                notify_block["heartbeat_enabled"] = _hb.get("enabled")
                notify_block["heartbeat_at"] = _hb.get("at")
                notify_block["last_heartbeat_at"] = _hb.get("last_sent_ts")
                notify_block["last_heartbeat_ok"] = _hb.get("last_ok")
            except Exception:  # noqa: BLE001
                pass
            # [OPEN_ISSUES_20261008 #5] 감시 중단 원격 통보 상태 — 꺼져 있거나 죽어 있으면 여기서 보인다
            try:
                import health_watch as _hw
                notify_block["health_watch"] = _hw.status()
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            notify_block = {}
        alert_problems, alert_warnings = health_status.alert_health(alerts, disp_status)
        alerts = {**alerts,
                  "dropped": _ns.get("dropped", 0),
                  "queue_depth": _ns.get("queue_depth", 0),
                  "notify_thread_alive": _ns.get("thread_alive"),
                  "undeliverable": disp_status.get("undeliverable_count", 0),
                  "channels_configured": disp_status.get("channels_configured"),
                  "last_config_error": disp_status.get("last_config_error")}
        _mstatus = _w.manager.status()
        overall, cameras = health_status.build(_mstatus, model_loaded,
                                               alert_backlog=int(alerts.get("pending", 0)),
                                               slot_degraded=slot_degraded,
                                               alert_problems=alert_problems)
        # ★[F-34] 워커가 삼킨 프레임 예외로 기록·통보에 못 간 경보 — 카메라 합산. 0 이 정상. 값이 오르면 "서버는 멀쩡한데 경보가 샌다".
        dropped_by_error = _dropped_by_error(_mstatus)
        # [B4] 예열 중에는 워커가 아직 없는 게 정상 — 카메라 판정으로 unhealthy 를 내지 않는다.
        #   대신 phase 로 "아직 준비 중"임을 알리고 503 을 준다(로드밸런서·워치독이 대기하도록).
        if phase == readiness.STARTING:
            overall = "starting"
        elif phase == readiness.FAILED:
            overall = "unhealthy"
        elif relay_status.get("off_failed") and overall == "healthy":
            overall = "degraded"        # [P3a] 물리 출력이 안 꺼졌을 수 있다 — 정상이 아니다
    except Exception:  # noqa: BLE001  판정 실패가 헬스체크 자체를 죽이면 안 된다
        overall = "degraded"
        cameras = {}

    # [I-3, 2026-09-23] torch 가 보는 VRAM — nvidia-smi 의 "프로세스 점유" 와는 다른 숫자다.
    #   allocated = 텐서가 실제로 쥔 양, reserved = 캐시 할당자가 잡아 둔 양(≥ allocated).
    #   벤치가 "8GB 카드에서 되나" 를 따질 때 필요한데 프로세스 밖에서는 읽을 수 없어 여기서 낸다.
    #   CUDA 가 없으면 None — 조용히 0 으로 꾸미지 않는다.
    gpu_mem: dict = {"allocated_mb": None, "reserved_mb": None, "max_allocated_mb": None}
    try:
        import torch
        if torch.cuda.is_available():
            gpu_mem = {"allocated_mb": round(torch.cuda.memory_allocated() / 1048576, 1),
                       "reserved_mb": round(torch.cuda.memory_reserved() / 1048576, 1),
                       "max_allocated_mb": round(torch.cuda.max_memory_allocated() / 1048576, 1)}
    except Exception:  # noqa: BLE001  torch 없음/초기화 전 — /health 를 죽이면 안 된다
        pass
    try:
        import device as _device
        gpu_mem["cap"] = _device.cuda_mem_cap_status()   # [I-3] 상한 모사가 걸렸는지(벤치 증빙용)
    except Exception:  # noqa: BLE001
        gpu_mem["cap"] = None
    # [USB 1차, 승인 항목 2] GPU 정체 — 인수시험 A4 가 이 블록을 읽는다(nvidia-smi 는 보조).
    #   torch 에서 읽는다: 드라이버가 보는 것이 아니라 **추론이 실제로 쓸 수 있는 것**을 말해야 한다.
    #   torch_cuda=false 면 서버는 CPU 로 돌고 있는 것이다 — 조용한 폴백 금지의 지문(항목 4).
    gpu_info: dict = {"device_name": None, "arch": None, "vram_total_mb": None, "torch_cuda": False,
                      # [항목 4] GPU 빌드인데 CPU 로 도는 상태 — device._note_device 가 기록, 배너·인수시험이 읽는다
                      "expected_gpu": False, "fallback": False, "fallback_reason": None}
    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            gpu_info.update({"device_name": p.name, "arch": f"sm_{p.major}{p.minor}",
                             "vram_total_mb": round(p.total_memory / 1048576), "torch_cuda": True})
    except Exception:  # noqa: BLE001  torch 없음/초기화 실패 — 기본값(false)이 곧 사실이다
        pass
    try:
        import device as _device
        fb = _device.gpu_fallback_status()
        gpu_info.update({k: fb.get(k) for k in ("expected_gpu", "fallback", "fallback_reason")})
        # 기대는 있는데 아직 어떤 슬롯도 장치를 고르지 않았을 수 있다(예열 전) — 그때는 torch 가 직접 답한다
        if os.environ.get("VIGENT_EXPECT_GPU", "").strip() == "1":
            gpu_info["expected_gpu"] = True
            if not gpu_info["torch_cuda"] and not gpu_info["fallback"]:
                gpu_info["fallback"] = True
                gpu_info["fallback_reason"] = gpu_info["fallback_reason"] or "torch.cuda.is_available() == False"
    except Exception:  # noqa: BLE001
        pass

    body = {
        "status": overall,
        "phase": phase,               # [B4] starting|ready|failed — 예열 완료 여부
        "warmup": warm,               # [B4] {phase, warmup_s, elapsed_s, error} — 예열 실측
        "gpu_mem": gpu_mem,           # [I-3] torch 기준 VRAM {allocated_mb, reserved_mb, max_allocated_mb} · CUDA 없으면 None
        "gpu": gpu_info,              # [USB 1차] {device_name, arch(sm_xx), vram_total_mb, torch_cuda} — 인수시험 A4 입력
        "alerts": alerts,             # [B5] {pending, sent, dead, dead_1h, undeliverable, channels_configured, last_config_error}
        # ★[F-35] 알림 채널이 실제로 살아 있는가 — "조용한 실패" 를 표면화한다.
        #   {last_success, dead_count, config_error, selftest_state, selftest_unknown_too_long}
        #   selftest_state: ok | config_error(붉은 배너) | unknown(30분 넘으면 노란 배너) | not_configured
        "notify": notify_block,
        # [M4-1] channels_not_configured · notify_config_error — status 는 바꾸지 않는 경고
        # [M7-3] + 기동 시 선택 서비스 실패("startup:<서비스>: <예외>") — go2rtc·기아 감시·보존 스윕
        "warnings": list(alert_warnings) + list(_startup_warnings()),
        "privacy": privacy_status,    # [P1a/P1c] 비식별화 설정 + 저장 폴더 암호화 검사 결과
        "relay": relay_status,        # [P3a] 물리 출력 — ★off_failed=true 면 사이렌이 안 꺼졌을 수 있다
        "cameras": cameras,           # [B2] 카메라별 검출 생존
        "version": product_version(),
        "uptime_s": round(_time.time() - _START_TS, 1),
        "theme": theme,
        "loaded": bool(bundle),
        "backend": backend,
        "models": models,
        "rfdetr_slots": rfdetr_slots,
        # ★[F1] 런타임 추론이 연속 실패 중인 슬롯. 비어 있어야 정상이며,
        #   "person" 이 들어 있으면 사람을 못 보는 상태 = status 도 unhealthy(503).
        "slot_degraded": slot_degraded,
        "slot_errors": slot_errors,
        "llm": llm,                   # {provider, available, model, note} — UI·운영이 실제 설정을 보게 함
        "disk_retention": disk_retention,   # [Z-2] {enabled, last_run, warnings}
        # ★[F6] 자동 스윕 스레드가 실제로 돌고 있는가 + 다음 예정. thread_alive=false 면
        #   보존 정책이 "설정만 있고 아무도 안 돌리는" 상태다(리뷰 F6 의 원래 결함).
        "retention_sweep": retention_sweep,
        # F-8 로드 가시화 원칙과 일관: 모델은 LOADED 이나 소비 경로에서 빠진 슬롯을 노출(은폐형 off 방지).
        #   ★[2026-08-20] 하드코딩 제거 — worker 의 런타임 설정을 그대로 반영한다.
        #   기존에는 forklift 를 무조건 '제외됨'으로 찍어서, 학원 프로파일이
        #   detect.include_forklift=1 로 켠 뒤에도 /health 가 계속 꺼졌다고 보고했다
        #   ('동작은 맞고 표시만 틀림' = 이 프로젝트가 금지하는 조용한 거짓말 유형).
        "disabled_detectors": disabled_dets,
        "active_detectors": active_dets,
        # ★[F-34] {frames, alerts, last_error, last_at, cameras:{cid: frames}} — 프레임 예외로 버려진 경보(누적, 워커 기동 이후)
        "alerts_dropped_by_error": dropped_by_error,
    }
    # [B2] unhealthy 는 HTTP 503 — 외부 워치독이 본문 파싱 없이 상태코드만으로 장애를 잡게 한다.
    #   degraded 는 200(운영은 계속되지만 일부 카메라 정지) + 본문으로 구분.
    # [B4] starting 도 503 — 예열 전에는 아직 감시가 성립하지 않으므로 "준비됨"이라고 답하지 않는다.
    return JSONResponse(body, status_code=503 if overall in ("unhealthy", "starting") else 200)


@router.get("/healthz")
def healthz(theme: str = DEFAULT_THEME):
    """[1단계 M-2] 무인증 생존 점검 — status·phase 만(워치독·기동 대기·폰 LAN 점검용).

    /health 는 GPU·모델 SHA·카메라 id·에러 문자열까지 담아 외부에 공짜 지문이었다 →
    토큰 모드에서 /health 는 인증 뒤로 옮기고(main._AUTH_EXEMPT 에서 제외), 밖에는 이
    최소 응답만 연다. 판정·상태코드는 /health 와 동일(같은 함수를 그대로 거친다):
    unhealthy·starting → 503, ok·degraded → 200. phase 는 워치독의 예열 유예
    (phase=starting 이면 재기동 금지)가 본문에서 읽으므로 함께 남긴다."""
    r = health(theme)
    body = json.loads(bytes(r.body))
    return JSONResponse({"status": body.get("status"), "phase": body.get("phase")},
                        status_code=r.status_code)


@router.get("/system/capabilities")
def capabilities(theme: str = DEFAULT_THEME):
    """파이프라인 상태표 + 에이전트 등록 현황(절대 저하 없음 가시화)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    return JSONResponse({
        "pipeline": cfg.summary(),
        "agents": [a.status() for a in bundle["agents"].values()],
    })
