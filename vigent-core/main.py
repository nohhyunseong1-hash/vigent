"""
main.py — VIGENT 공유 코어 FastAPI 골격 (§15-2)

이 단계의 목표:
  - vision.yaml 을 읽어 파이프라인을 '구성'하고(폴백 포함),
  - 6-에이전트(스텁)를 연결하고,
  - 테마 페이지와 시스템 상태를 보여주는 최소 엔드포인트를 띄운다.

실제 추론·판단·보고서 생성은 다음 단계에서 채운다.

실행:
  cd ~/Desktop/VIGENT
  uvicorn vigent-core.main:app --reload      # 폴더명에 '-' 가 있어 패키지 임포트가 까다로움 → 아래 참고
  # 권장: cd vigent-core && uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import hmac
import os
import sys
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# .env 의 비밀키(텔레그램·웹훅 등)를 환경변수로 로드(있으면). 없어도 무해.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# 이 파일이 단독(uvicorn main:app)으로 실행돼도 패키지 임포트가 되도록 경로 보정
_HERE = Path(__file__).resolve().parent          # vigent-core/
_ROOT = _HERE.parent                              # 프로젝트 루트
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


import vlog  # noqa: E402  로깅 인프라(C-S1)

# 공유 런타임 상태는 app_state.py 로 분리(P1-7) — 라우터들이 main 을 import 하지 않고 공유.
from app_state import (  # noqa: E402
    DEFAULT_THEME,
    STATE,
)
from app_state import DETECT_LOCK as _DETECT_LOCK  # noqa: E402
from app_state import load_theme as _load_theme  # noqa: E402
from routers import detect as _detect_router  # noqa: E402
from routers import dispatch as _dispatch_router  # noqa: E402
from routers import incident as _incident_router  # noqa: E402
from routers import office as _office_router  # noqa: E402
from routers import ppe as _ppe_router  # noqa: E402
from routers import recognition as _recognition_router  # noqa: E402
from routers import safety_core as _safety_core_router  # noqa: E402
from routers import sports as _sports_router  # noqa: E402
from routers import system as _system_router  # noqa: E402
from routers import tapo as _tapo_router  # noqa: E402
from routers import tbm as _tbm_router  # noqa: E402
from routers import vitals as _vitals_router  # noqa: E402
from routers import zone as _zone_router  # noqa: E402

# 공유 웹 헬퍼는 web_util.py 로 분리(P1-7) — 동일 이름 re-import(사용부 무변경)
from web_util import (  # noqa: E402  # noqa: E402
    product_version,
)

_log = vlog.get("vigent")               # print 대체 — 콘솔+파일 로테이션


# ─────────────────────────────────────────────────────────────
# 앱 + 시작 시 1회 로드
# ─────────────────────────────────────────────────────────────
# DEFAULT_THEME 는 app_state.py 로 분리(P1-7) — 위 import 에서 가져온다.

app = FastAPI(title="VIGENT Core", version=product_version())
app.include_router(_tapo_router.router)   # /tapo/* (P1-7)
app.include_router(_vitals_router.router)   # /vitals/* (P1-7)
app.include_router(_zone_router.router)   # /zone/* (P1-7)
app.include_router(_sports_router.router)   # /sports/* (P1-7)
app.include_router(_office_router.router)   # /office/* (P1-7)
app.include_router(_system_router.router)   # /health·/system/* (P1-7)
app.include_router(_detect_router.router)   # /detect·/rfdetr·/segment (P1-7)
app.include_router(_incident_router.router)   # /safety/incident/* (P1-7)
app.include_router(_tbm_router.router)   # /safety/tbm/* (P1-7)
app.include_router(_ppe_router.router)   # /safety/ppe·/ppe/* (P1-7)
app.include_router(_recognition_router.router)   # /recognition/* (P1-7)
app.include_router(_dispatch_router.router)   # /dispatch/relay (P1-7)
app.include_router(_safety_core_router.router)   # safety 나머지 전부 — 맨 마지막(/{theme} 캐치올 순서 보존) (P1-7)

# ── 보안(C-S0): 바인딩·토큰 인증·웹훅 화이트리스트 ─────────────────────────
#   기본은 로컬 전용(127.0.0.1)·무토큰(개발 편의). 외부 노출은 명시적 opt-in.
_API_TOKEN = os.environ.get("VIGENT_API_TOKEN", "").strip()
_BIND_HOST = os.environ.get("VIGENT_HOST", "127.0.0.1").strip()
_IS_LOOPBACK = _BIND_HOST in ("127.0.0.1", "localhost", "::1", "")
# 외부 바인딩 + 무토큰 = 무인증 노출 → 기동 거부(명확한 안내와 함께 종료)
if not _IS_LOOPBACK and not _API_TOKEN:
    sys.stderr.write(
        "\n[VIGENT 보안 오류] 외부 바인딩(VIGENT_HOST=%s)에는 VIGENT_API_TOKEN 이 필수입니다.\n"
        "  · 로컬 개발  : VIGENT_HOST 미설정(기본 127.0.0.1) → 무토큰 허용\n"
        "  · 외부 노출  : VIGENT_API_TOKEN=<비밀토큰> 설정 후 기동(전 라우트 Bearer 인증)\n\n"
        % _BIND_HOST)
    raise SystemExit(1)
# 로컬 바인딩 + 무토큰(개발 편의로 허용)이라도, 공유 네트워크에서는 위험 → 기동 시 1줄 경고(P0-3).
if _IS_LOOPBACK and not _API_TOKEN:
    sys.stderr.write(
        "[VIGENT 경고] VIGENT_API_TOKEN 미설정(로컬 무인증 모드). "
        "공유 네트워크·파일럿 환경에서는 VIGENT_API_TOKEN 설정이 필수입니다.\n")
# 토큰 미설정(로컬)이면 인증 생략. 설정 시 아래 경로만 예외(모니터링·파비콘).
_AUTH_EXEMPT = {"/health", "/favicon.ico"}

# ── 제품 분리(C-S3): VIGENT_THEMES 로 타 제품(office/sports) 라우트 게이트 ──
#   기본 'safety' → safety 배포에는 office/sports 라우트가 404(타 제품 미노출). 다중 제품이면 콤마로: "safety,office,sports"
_THEMES = {t.strip() for t in os.environ.get("VIGENT_THEMES", "safety").split(",") if t.strip()} or {"safety"}
_GATED_PREFIXES = {"/office": "office", "/sports": "sports"}  # safety 는 코어(항상 활성)


@app.middleware("http")
async def _auth_guard(request, call_next):
    """VIGENT_API_TOKEN 설정 시 전 라우트 Bearer 검증(미설정=로컬 개발 무인증)."""
    if _API_TOKEN and request.method != "OPTIONS":
        path = request.url.path
        if path not in _AUTH_EXEMPT:
            # 상수시간 비교(P0-3/P1-8): 타이밍 사이드채널로 토큰 추측 방지. compare_digest 는 길이 불일치도 안전.
            if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {_API_TOKEN}"):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def _theme_gate(request, call_next):
    """VIGENT_THEMES 에 없는 제품(office/sports)의 라우트는 404(safety 배포에 타 제품 미노출, C-S3)."""
    path = request.url.path
    for prefix, theme in _GATED_PREFIXES.items():
        if (path == prefix or path.startswith(prefix + "/")) and theme not in _THEMES:
            return JSONResponse({"detail": "not found"}, status_code=404)
    return await call_next(request)


@app.middleware("http")
async def _no_cache_dynamic(request, call_next):
    """HTML·JS 는 캐시 금지 → 코드 수정이 새로고침 즉시 반영(브라우저가 옛 인식코드 물고 있는 문제 차단)."""
    resp = await call_next(request)
    p = request.url.path
    if p.endswith(".js") or p.endswith(".css") or p.endswith(".html") or resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# 안전 모드에서 '그릴' 객체 화이트리스트(서버단 강제) — 프론트 캐시와 무관하게 잡동사니 제거.
# 일상 사물(노트북·TV·의자 등)은 빼고, 사람·위험물·차량/중장비·화재·보호구(PPE)만 남긴다.


# STATE · _DETECT_LOCK · _load_theme 는 app_state.py 로 분리(P1-7) — 위 import 에서 가져온다
# (STATE/DETECT_LOCK/load_theme). 라우터가 main 을 import 하지 않고 공유하기 위함.


# ── 1단계 안정성: 전역 예외 안전망(무증상 실패 차단) ──
@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 '요청' 예외 → 500 크래시 대신 구조화 로그 + 안전 응답.
    (백그라운드 워커 스레드 예외는 요청 경로가 아니므로 이걸로 안 잡힘 → worker 감독자·threading.excepthook 담당.)"""
    _log.error("미처리 요청 예외: %s %s\n%s",
               request.method, request.url.path, traceback.format_exc())
    return JSONResponse(status_code=500,
                        content={"error": "internal_error", "detail": type(exc).__name__})


def _install_safety_nets() -> None:
    """프로세스 레벨 안전망: 스레드/메인/asyncio 미처리 예외를 로그로 남긴다(조용한 실패 0).
    특히 threading.excepthook 은 daemon 워커 스레드가 소리 없이 죽는 것을 포착한다(1단계 핵심)."""
    def _thread_hook(args):   # threading.excepthook(3.8+): 워커 스레드 미처리 예외
        _log.error("스레드 '%s' 미처리 예외(워커 소멸 위험 — 감독자가 재시작)\n%s",
                   getattr(args.thread, "name", "?"),
                   "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    threading.excepthook = _thread_hook

    _prev_hook = sys.excepthook
    def _sys_hook(exc_type, exc_value, exc_tb):   # 메인 스레드 미처리 예외
        _log.error("메인 미처리 예외\n%s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        _prev_hook(exc_type, exc_value, exc_tb)
    sys.excepthook = _sys_hook

    try:   # asyncio 루프 미처리 예외
        loop = asyncio.get_event_loop()
        def _aio_hook(_l, context):
            _log.error("asyncio 미처리 예외: %s", context.get("message"))
            exc = context.get("exception")
            if exc is not None:
                _log.error("%s", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        loop.set_exception_handler(_aio_hook)
    except Exception:  # noqa: BLE001
        pass


@app.on_event("shutdown")
def _shutdown() -> None:
    """graceful shutdown(SIGTERM/SIGINT 시 uvicorn 이 트리거) — 워커 정리·리소스 해제."""
    try:
        import worker as _w
        stopped = _w.manager.stop_all() if hasattr(_w.manager, "stop_all") else "(stop_all 없음)"
        _log.info("shutdown: 워커 정리 (%s)", stopped)
    except Exception:  # noqa: BLE001
        _log.warning("shutdown: 워커 정리 중 예외\n%s", traceback.format_exc())


@app.on_event("startup")
def _startup() -> None:
    _install_safety_nets()          # 1단계: 프로세스 레벨 예외 안전망 설치
    bundle = _load_theme(DEFAULT_THEME)
    cfg = bundle["config"]
    s = cfg.summary()
    _log.info("'%s' 로드 완료 (폴백 %s개 / 비활성 %s개)",
              cfg.display_name, s['fallback_count'], s['disabled_count'])
    # 엣지/USB 설치본: VIGENT_EDGE=1 이면 site.yaml 의 카메라로 워커 자동시작(헤드리스)
    if os.environ.get("VIGENT_EDGE") == "1":
        try:
            import worker as _w
            res = _w.manager.autostart(bundle["agents"].get("Guard"), _DETECT_LOCK)
            _log.info("[EDGE] 현장 워커 자동시작 → %s", res)
        except Exception as ex:  # noqa: BLE001  자동시작 실패해도 서버는 뜬다
            _log.error("[EDGE] 자동시작 실패: %s: %s", type(ex).__name__, ex)


# ─────────────────────────────────────────────────────────────
# 엔드포인트 (최소)
# ─────────────────────────────────────────────────────────────


@app.get("/")
def root():
    return {
        "brand": "VIGENT",
        "core": app.version,
        "default_theme": DEFAULT_THEME,
        "themes_loaded": list(STATE.keys()),
        "hint": "GET /system/capabilities 로 파이프라인 상태를, GET /{theme} 로 테마 페이지를 본다.",
    }


# vision.yaml judgment.zones 의 키 → 실제 파일 경로


# ─────────────────────────────────────────────────────────────
# 작업 전 TBM(안전점검 회의) — 작성·저장·열기 (한전 스마트TBM '작업 전' 단계)
# ─────────────────────────────────────────────────────────────

# 작성 화면(plain 문자열 — JS 중괄호 보존). /*CSS*/ <!--CHECKLIST--> <!--PROCESSLIST--> 가 치환된다.

# ── 인라인 HTML 분리(P1-7): templates/ 에서 1회 로드·캐시(바이트 동일) ──


# 안전 자동처리 콘솔 화면(plain 문자열 — JS 중괄호 보존). /*CSS*/ 만 치환된다.


# TBM 열기 화면의 '위험성평가서 만들기' 버튼 스크립트(__TID__ 치환). f-string 중괄호 회피용 별도 상수.


# ─────────────────────────────────────────────────────────────
# 안전 자동처리 콘솔 — 위험 감지 → 증거·법령·위험성평가·조치 자동 정리(사람 승인)
# 책임 회피 설계: advisory(자동실행 X) + 안전관리자 승인 게이트 + 감사추적 + 면책 문구
# ─────────────────────────────────────────────────────────────


# ── 서버사이드 추론 워커(브라우저 없이 서버가 영상 감시) — 다현장 N대 관리 ──


# ── 현장 운영 설정 콘솔(현장·카메라·워커·알림을 화면에서) ──


# ── go2rtc 자산·WS 중계(같은 출처 :8010 로 만들어 CORS 회피) ──
# ── /tapo/* 라우트는 routers/tapo.py 로 분리(P1-7) — 위에서 include_router 등록 ──


# ── rf-detr permissive 백엔드(탐지·추적·위험구역·VLM) ──


# ── AX 프론트(realtime_core.js) 호환 스텁 ──
# AX 엔진이 호출하는 보조 엔드포인트들. 핵심 인식은 브라우저(coco-ssd)에서 돌고,
# 아래는 '없으면 404 콘솔에러'만 막는 안전 스텁(빈 결과). 점진적으로 실제 구현 가능.


# ── /vitals/* 는 routers/vitals.py 로 분리(P1-7) ──


# 공유 정적 자원(realtime_core.js 등)
_STATIC_DIR = _HERE / "static"
if _STATIC_DIR.exists():
    # follow_symlink: 배포 기본 False(디렉토리 밖 심링크 traversal 차단 = 보안 유지).
    #   개발 워크트리는 gitignore 자산(vendor/ 144M 등)이 심링크로만 존재 → VIGENT_DEV_SYMLINK=1 로 opt-in.
    #   (VIGENT_ALLOW_FALLBACK 과 동일 철학: 배포 안전·개발 명시 허용. setup_worktree.sh 참조.)
    _dev_symlink = os.environ.get("VIGENT_DEV_SYMLINK") == "1"
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR), follow_symlink=_dev_symlink), name="static")

# 증거 프레임 이미지 서빙(데이터엔진 저장본). 폴더는 첫 이벤트 때 생성됨.
_EVIDENCE_DIR = _ROOT / "data" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(_EVIDENCE_DIR)), name="evidence")
