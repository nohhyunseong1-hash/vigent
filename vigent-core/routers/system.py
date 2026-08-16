"""routers/system.py — 헬스체크·시스템 상태 (P1-7 분할). main 미import."""
import json
import time as _time

from app_state import _START_TS, DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from web_util import _ROOT, product_version

router = APIRouter()


@router.get("/health")
def health(theme: str = DEFAULT_THEME):
    """확장 헬스체크(C-S1): 제품 버전·모델별 버전/SHA·uptime·backend 구성.
    워치독·모니터링용(무인증 허용). SHA 는 weights_manifest.json 기준(앞 16자)."""
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
    if bundle:
        _g = bundle["agents"].get("Guard")
        if _g is not None:
            try:
                rfdetr_slots = _g.status().get("rfdetr_slots", [])
            except Exception:  # noqa: BLE001
                pass
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
    try:
        import health_status
        import readiness
        import worker as _w
        phase = readiness.phase()
        warm = readiness.snapshot()
        model_loaded = bool(bundle) and bool(rfdetr_slots)
        # [B5] 미전송 경보가 남아 있으면 degraded — "경보가 안 나갔는데 정상"은 있을 수 없다.
        try:
            import alert_queue
            alerts = alert_queue.counts()
        except Exception:  # noqa: BLE001
            alerts = {}
        overall, cameras = health_status.build(_w.manager.status(), model_loaded,
                                               alert_backlog=int(alerts.get("pending", 0)))
        # [B4] 예열 중에는 워커가 아직 없는 게 정상 — 카메라 판정으로 unhealthy 를 내지 않는다.
        #   대신 phase 로 "아직 준비 중"임을 알리고 503 을 준다(로드밸런서·워치독이 대기하도록).
        if phase == readiness.STARTING:
            overall = "starting"
        elif phase == readiness.FAILED:
            overall = "unhealthy"
    except Exception:  # noqa: BLE001  판정 실패가 헬스체크 자체를 죽이면 안 된다
        overall = "degraded"
        cameras = {}

    body = {
        "status": overall,
        "phase": phase,               # [B4] starting|ready|failed — 예열 완료 여부
        "warmup": warm,               # [B4] {phase, warmup_s, elapsed_s, error} — 예열 실측
        "alerts": alerts,             # [B5] {pending, sent, dead} — 미전송 경보(pending≥1 이면 degraded)
        "cameras": cameras,           # [B2] 카메라별 검출 생존
        "version": product_version(),
        "uptime_s": round(_time.time() - _START_TS, 1),
        "theme": theme,
        "loaded": bool(bundle),
        "backend": backend,
        "models": models,
        "rfdetr_slots": rfdetr_slots,
        "llm": llm,                   # {provider, available, model, note} — UI·운영이 실제 설정을 보게 함
        "disk_retention": disk_retention,   # [Z-2] {enabled, last_run, warnings}
        # F-8 로드 가시화 원칙과 일관: 모델은 LOADED 이나 소비 경로에서 명시적으로 끈 슬롯을 노출(은폐형 off 방지).
        "disabled_detectors": {
            "forklift": "F-7 과소학습(정탐 conf p50 0.002 ≈ 오탐 수준, 2026-07-11 실측). "
                        "라이브·safety-local·재해분석(incident)·음성안내(voice) 소비 경로 제외(강재를 지게차로 오탐→협착 오염·오경보). "
                        "T10b full 재학습 후 복원 예정. 측정은 detectors 명시 지정 시 가능.",
        },
    }
    # [B2] unhealthy 는 HTTP 503 — 외부 워치독이 본문 파싱 없이 상태코드만으로 장애를 잡게 한다.
    #   degraded 는 200(운영은 계속되지만 일부 카메라 정지) + 본문으로 구분.
    # [B4] starting 도 503 — 예열 전에는 아직 감시가 성립하지 않으므로 "준비됨"이라고 답하지 않는다.
    return JSONResponse(body, status_code=503 if overall in ("unhealthy", "starting") else 200)


@router.get("/system/capabilities")
def capabilities(theme: str = DEFAULT_THEME):
    """파이프라인 상태표 + 에이전트 등록 현황(절대 저하 없음 가시화)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    return JSONResponse({
        "pipeline": cfg.summary(),
        "agents": [a.status() for a in bundle["agents"].values()],
    })
