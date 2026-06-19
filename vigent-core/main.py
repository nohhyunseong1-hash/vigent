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

import os
import sys
from pathlib import Path

import json

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
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

from agents import build_agents          # noqa: E402
import vision_loader                     # noqa: E402

# ─────────────────────────────────────────────────────────────
# 앱 + 시작 시 1회 로드
# ─────────────────────────────────────────────────────────────
DEFAULT_THEME = os.environ.get("VIGENT_THEME", "safety")

app = FastAPI(title="VIGENT Core", version="0.2.0")

# 코어가 들고 있는 런타임 상태(테마별 파이프라인 + 에이전트)
STATE: dict[str, dict] = {}


def _load_theme(theme: str) -> dict:
    """테마 1개를 로드해 STATE 에 캐시."""
    cfg = vision_loader.load_vision(theme)
    agents = build_agents(cfg)
    bundle = {"config": cfg, "agents": agents}
    STATE[theme] = bundle
    return bundle


@app.on_event("startup")
def _startup() -> None:
    bundle = _load_theme(DEFAULT_THEME)
    cfg = bundle["config"]
    s = cfg.summary()
    print(f"[VIGENT] '{cfg.display_name}' 로드 완료 "
          f"(폴백 {s['fallback_count']}개 / 비활성 {s['disabled_count']}개)")


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/system/capabilities")
def capabilities(theme: str = DEFAULT_THEME):
    """파이프라인 상태표 + 에이전트 등록 현황(절대 저하 없음 가시화)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    return JSONResponse({
        "pipeline": cfg.summary(),
        "agents": [a.status() for a in bundle["agents"].values()],
    })


@app.get("/zone/danger")
def zone_danger(theme: str = DEFAULT_THEME):
    """테마 vision.yaml 이 가리키는 위험구역 폴리곤(정규화 좌표)을 반환."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    zone_path = (cfg.raw.get("judgment", {}) or {}).get("zones", {}).get("danger_zones")
    if not zone_path:
        return {"points": []}
    p = _ROOT / zone_path
    if not p.exists():
        return {"points": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


@app.post("/zone/danger")
def set_zone_danger(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """사용자가 화면에서 그린 위험구역 폴리곤(정규화 좌표 0~1)을 저장.
    payload = {"points": [{"x":..,"y":..}, ...]}"""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    zone_path = (cfg.raw.get("judgment", {}) or {}).get("zones", {}).get("danger_zones")
    if not zone_path:
        raise HTTPException(status_code=400, detail="vision.yaml 에 danger_zones 경로가 없음")

    pts_in = payload.get("points", []) or []
    # 검증: 0~1 범위의 {x,y} 만 통과
    points = []
    for pt in pts_in:
        try:
            x, y = float(pt["x"]), float(pt["y"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="points 형식 오류({x,y} 필요)")
        points.append({"x": max(0.0, min(1.0, x)), "y": max(0.0, min(1.0, y))})

    p = _ROOT / zone_path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"points": points}, f, ensure_ascii=False)
    return {"ok": True, "count": len(points), "saved_to": str(zone_path)}


@app.post("/safety/judge")
def safety_judge(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """Analyst 가산식 판단. 프론트가 관측 신호(signals)와 (선택)딥러닝 신호(dl)를 보낸다.
    모델 신호가 없으면 규칙만으로 폴백 동작(절대 저하 없음)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    analyst = bundle["agents"].get("Analyst")
    if analyst is None:
        raise HTTPException(status_code=500, detail="Analyst 미등록")
    signals = payload.get("signals", {}) or {}
    dl = payload.get("dl")  # None 이면 폴백
    return analyst.judge(signals, dl)


@app.get("/evidence/search")
def evidence_search(rule: str, theme: str = DEFAULT_THEME):
    """Copilot 근거 검색 — 규칙 id 의 법령·가이드 인용(출처 포함)을 반환(§9)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    copilot = bundle["agents"].get("Copilot")
    return copilot.cite(rule)


@app.post("/safety/risk-assessment")
def safety_risk_assessment(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """Scribe 위험성평가서 생성. payload={events:[{rule,count}], site, process}.
    근거 인용 자동 삽입 + data/risk_assessments/ 저장. 반환은 평가표 JSON(+저장경로)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    out = scribe.generate(payload.get("events", []) or [],
                          site=payload.get("site", ""), process=payload.get("process", ""))
    return {"assessment": out["assessment"], "saved_path": out["saved_path"]}


@app.get("/report/safety", response_class=HTMLResponse)
def report_safety(theme: str = DEFAULT_THEME):
    """최근 위험 이벤트 기반 위험성평가서 HTML(인쇄→PDF). 데모용 샘플 이벤트로 렌더.
    실제 운영에서는 데이터엔진의 누적 이벤트를 넘긴다(6단계)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    sample = [{"rule": "zone_intrusion", "count": 5}, {"rule": "ppe_missing", "count": 9},
              {"rule": "fall_suspected", "count": 1}]
    return scribe.generate(sample, site="데모 현장", process="데모 공정", save=False)["html"]


@app.post("/alerts/test")
def alerts_test(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """Dispatcher 경보 테스트. payload={level, message}. 키 없으면 폴백(로그)로 동작."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    return dispatcher.dispatch(payload.get("level", "high"),
                               payload.get("message", "VIGENT 경보 테스트"))


@app.get("/{theme}")
def theme_page(theme: str):
    """테마 정적 페이지(index.html) 서빙. 없으면 404."""
    index = _ROOT / "themes" / theme / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail=f"테마 페이지 없음: {theme}")
    # 테마가 아직 로드 안 됐으면 로드 시도
    if theme not in STATE:
        try:
            _load_theme(theme)
        except FileNotFoundError:
            pass
    return FileResponse(index)


# 공유 정적 자원(realtime_core.js 등)
_STATIC_DIR = _HERE / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
