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
        elif disk_retention["enabled"]:
            disk_retention["warnings"] = ["보존 정책이 활성화됐으나 스위퍼가 아직 실행된 기록이 없음"]
    except Exception:  # noqa: BLE001  조회 실패해도 헬스체크는 죽지 않는다
        pass
    return {
        "status": "ok",
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

@router.get("/system/capabilities")
def capabilities(theme: str = DEFAULT_THEME):
    """파이프라인 상태표 + 에이전트 등록 현황(절대 저하 없음 가시화)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    return JSONResponse({
        "pipeline": cfg.summary(),
        "agents": [a.status() for a in bundle["agents"].values()],
    })
