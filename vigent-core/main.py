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
import threading
from pathlib import Path

import json

import asyncio

from fastapi import Body, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
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
import audit_store                        # noqa: E402
import data_engine                       # noqa: E402
import tbm_store                          # noqa: E402
import vision_loader                     # noqa: E402

# ─────────────────────────────────────────────────────────────
# 앱 + 시작 시 1회 로드
# ─────────────────────────────────────────────────────────────
DEFAULT_THEME = os.environ.get("VIGENT_THEME", "safety")

app = FastAPI(title="VIGENT Core", version="0.2.0")


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
_SAFETY_KEEP = {"person", "knife", "scissors", "car", "truck", "bus", "motorcycle",
                "bicycle", "forklift", "train", "boat", "fire", "smoke", "cigarette"}


def _incident_boxes(out: dict, prox: list) -> list:
    """탐지 결과 → 박스 목록(정규화 bbox + 위험여부). 협착쌍·화재·보호구미착용을 위험으로 표시."""
    def overlap(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy > 0
    prox_persons = [p.get("person_bbox") for p in (prox or [])]
    has_prox = bool(prox)
    boxes = []
    for d in out.get("detections", []):
        cls = (d.get("label") or "")
        cl = cls.lower()
        bb = d.get("bbox", [0, 0, 0, 0])
        hazard = (cl in ("fire", "smoke") or cl.startswith("no-")
                  or (cl == "forklift" and has_prox)
                  or any(pb and overlap(bb, pb) for pb in prox_persons))
        boxes.append({"class": cls, "bbox": [round(v, 4) for v in bb], "hazard": bool(hazard)})
    return boxes


def _is_safety_label(label: str) -> bool:
    l = (label or "").lower()
    if l in _SAFETY_KEEP:
        return True
    return any(k in l for k in ("hardhat", "helmet", "vest", "mask", "glove", "goggle", "boots"))


# 코어가 들고 있는 런타임 상태(테마별 파이프라인 + 에이전트)
STATE: dict[str, dict] = {}

# YOLO 추론 직렬화 락 — ultralytics 모델 로딩/추론은 동시성 안전하지 않다.
# 브라우저가 6fps로 동시에 /detect/frame 을 호출하면 같은 모델을 여러 스레드가
# 동시에 로드/추론하다 네이티브 크래시가 난다 → 락으로 한 번에 하나씩만.
_DETECT_LOCK = threading.Lock()


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
    # 엣지/USB 설치본: VIGENT_EDGE=1 이면 site.yaml 의 카메라로 워커 자동시작(헤드리스)
    if os.environ.get("VIGENT_EDGE") == "1":
        try:
            import worker as _w
            res = _w.manager.autostart(bundle["agents"].get("Guard"), _DETECT_LOCK)
            print(f"[VIGENT EDGE] 현장 워커 자동시작 → {res}")
        except Exception as ex:  # noqa: BLE001  자동시작 실패해도 서버는 뜬다
            print(f"[VIGENT EDGE] 자동시작 실패: {type(ex).__name__}: {ex}")


# ─────────────────────────────────────────────────────────────
# 엔드포인트 (최소)
# ─────────────────────────────────────────────────────────────
@app.get("/home", response_class=HTMLResponse)
@app.get("/hub", response_class=HTMLResponse)
def hub_home():
    """VIGENT 홈(허브) — 가장 좋은 기능들을 타일로 한눈에."""
    import hub
    return hub.render()


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


@app.get("/favicon.ico")
def favicon():
    """브라우저 자동요청 favicon — 없어서 나던 404 콘솔 노이즈 제거(내용은 비움)."""
    return Response(status_code=204)


@app.get("/system/capabilities")
def capabilities(theme: str = DEFAULT_THEME):
    """파이프라인 상태표 + 에이전트 등록 현황(절대 저하 없음 가시화)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    cfg = bundle["config"]
    return JSONResponse({
        "pipeline": cfg.summary(),
        "agents": [a.status() for a in bundle["agents"].values()],
    })


# vision.yaml judgment.zones 의 키 → 실제 파일 경로
def _zone_cfg_path(theme: str, key: str) -> str | None:
    bundle = STATE.get(theme) or _load_theme(theme)
    return (bundle["config"].raw.get("judgment", {}) or {}).get("zones", {}).get(key)


def _zone_get(theme: str, key: str) -> dict:
    zone_path = _zone_cfg_path(theme, key)
    if not zone_path:
        return {"points": []}
    p = _ROOT / zone_path
    if not p.exists():
        return {"points": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _zone_set(theme: str, key: str, payload: dict) -> dict:
    zone_path = _zone_cfg_path(theme, key)
    if not zone_path:
        raise HTTPException(status_code=400, detail=f"vision.yaml 에 {key} 경로가 없음")
    points = []
    for pt in payload.get("points", []) or []:
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


@app.get("/zone/danger")
def zone_danger(theme: str = DEFAULT_THEME):
    """일반 위험구역 폴리곤(정규화 좌표) 반환."""
    return _zone_get(theme, "danger_zones")


@app.post("/zone/danger")
def set_zone_danger(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """일반 위험구역 폴리곤 저장. payload={"points":[{"x":..,"y":..}, ...]}"""
    return _zone_set(theme, "danger_zones", payload)


@app.get("/zone/machine")
def zone_machine(theme: str = DEFAULT_THEME):
    """프레스/전단기 방호구역 폴리곤(정규화 좌표) 반환(§8)."""
    return _zone_get(theme, "machine_hazard_zones")


@app.post("/zone/machine")
def set_zone_machine(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """프레스/전단기 방호구역 폴리곤 저장(손 진입 시 guard_bypass=critical)."""
    return _zone_set(theme, "machine_hazard_zones", payload)


@app.post("/dispatch/relay")
def dispatch_relay(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """§8 보조 방호신호. guard_bypass(critical) 발생 시 프론트가 호출.
    ⚠ 비전은 보조·감시 계층이며 1차 비상정지를 대체하지 않는다."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    return dispatcher.relay(payload.get("event", "guard_bypass"), payload.get("meta"))


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


@app.post("/safety/manager/decide")
def safety_manager_decide(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """SafetyManager 반자동 — event 로 등급 판정 → '권장 행동'만 반환(무엇도 자동 실행 안 함)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    mgr = bundle["agents"].get("SafetyManager")
    if mgr is None:
        raise HTTPException(status_code=503, detail="SafetyManager 미로드")
    return mgr.decide(payload or {})


@app.post("/safety/manager/ask")
def safety_manager_ask(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """SafetyManager 질의응답 — 로컬 지식 우선, 근거 없으면 '확인 필요'."""
    bundle = STATE.get(theme) or _load_theme(theme)
    mgr = bundle["agents"].get("SafetyManager")
    if mgr is None:
        raise HTTPException(status_code=503, detail="SafetyManager 미로드")
    return mgr.ask((payload or {}).get("question", ""))


@app.get("/evidence/search")
def evidence_search(rule: str, theme: str = DEFAULT_THEME):
    """Copilot 근거 검색 — 규칙 id 의 법령·가이드 인용(출처 포함)을 반환(§9)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    copilot = bundle["agents"].get("Copilot")
    return copilot.cite(rule)


@app.post("/safety/risk-assessment")
def safety_risk_assessment(payload: dict = Body(...), theme: str = DEFAULT_THEME,
                           narrative: bool = False):
    """Scribe 위험성평가서 생성. payload={events:[{rule,count}], site, process}.
    근거 인용 자동 삽입 + data/risk_assessments/ 저장. 반환은 평가표 JSON(+저장경로).
    narrative=true 일 때만 종합의견을 LLM 으로 생성(느림). 기본은 결정적 폴백(즉시 · rows·법령 불변)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    out = scribe.generate(payload.get("events", []) or [],
                          site=payload.get("site", ""), process=payload.get("process", ""),
                          use_llm=narrative)
    return {"assessment": out["assessment"], "saved_path": out["saved_path"]}


def _decode_data_url(image: str):
    """data:image/...;base64,... → cv2 BGR numpy. 실패하면 None."""
    import base64
    import re
    import cv2
    import numpy as np
    m = re.match(r"^data:image/\w+;base64,(.+)$", image or "", re.S)
    if not m:
        return None
    try:
        buf = np.frombuffer(base64.b64decode(m.group(1)), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None


def _img_from_b64(raw):
    """base64 또는 data:URL 문자열 → BGR numpy(없거나 실패 시 None). data: 접두어 자동 보정.
    여러 엔드포인트의 동일 디코드 블록을 한 곳으로 통합."""
    if not raw:
        return None
    rawd = raw if str(raw).startswith("data:") else "data:image/jpeg;base64," + raw
    return _decode_data_url(rawd)


@app.post("/detect/frame")
def detect_frame(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """Guard 딥러닝 정밀 탐지(브라우저 백엔드 보강).
    payload={image_base64(접두사 유무 무관) | image(data URL), ppe?:bool, conf?:float, detectors?:[...]}.
    반환(프론트 계약): {success, detections:[{class,score,bbox:[x,y,w,h]px}], hazards:[...], person_count, signals}.
    모델 없으면 해당 검출기만 비활성(무중단)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    # image_base64(접두사 없는 base64) 우선 + 기존 image(data URL) 호환. 접두사 없으면 보정.
    raw = payload.get("image_base64") or payload.get("image") or ""
    if raw and not raw.startswith("data:"):
        raw = "data:image/jpeg;base64," + raw
    img = _decode_data_url(raw)
    if img is None:
        raise HTTPException(status_code=400, detail="이미지 디코딩 실패(image_base64/image 확인)")
    # 검출기 선택: 안전 모드(ppe=true)면 person+ppe+forklift+fire(보호구·지게차·화재), 아니면 person만.
    # CPU에서 4모델 지속/동시 부하 안정 검증됨(~0.32s/호출). MPS는 다모델 반복추론 시 크래시 →
    # 기본 CPU(guard) 유지. (화재 탐지는 시각 뱃지/신호용 — 실내 오탐 가능, 푸시 알림은 별도 경로)
    detectors = payload.get("detectors")
    if detectors is None:
        detectors = ["person", "ppe", "forklift", "fire_smoke"] if payload.get("ppe") else ["person"]
    # 라이브 반응성: 프론트가 이미 640px로 줄여 보내므로(realtime_core.js) 감지도 640으로 맞춘다.
    # 960으로 upscale하면 없는 디테일 만들려 2배 느려질 뿐(정확도 이득 없음) → 640이 거의 순수 이득.
    # (오프라인 재해분석은 별도로 imgsz=1280 유지). payload.imgsz 로 현장서 조정 가능.
    live_imgsz = int(payload.get("imgsz") or 640)
    with _DETECT_LOCK:                       # 동시 추론 직렬화(로딩/추론 race 방지)
        out = guard.detect(img, detectors=detectors, conf=payload.get("conf"), imgsz=live_imgsz)
    # 정규화 bbox(0~1) → 전송 이미지 픽셀 [x,y,w,h] + 프론트 키(class/score)로 변환
    H, W = img.shape[:2]
    dets = []
    for d in out.get("detections", []):
        x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
        dets.append({"class": d.get("label"), "score": d.get("conf"),
                     "bbox": [round(x1 * W, 1), round(y1 * H, 1),
                              round((x2 - x1) * W, 1), round((y2 - y1) * H, 1)]})
    # 안전 전용: 잡동사니(노트북·TV·의자 등) 서버단에서 제거 → 사람·위험물·차량·화재·보호구만
    if payload.get("safety_only"):
        dets = [d for d in dets if _is_safety_label(d.get("class"))]
    hazards = [{"type": d.get("label", "").lower(), "label": d.get("label"),
                "confidence": d.get("conf", 0),
                "severity": "high" if d.get("conf", 0) >= 0.5 else "mid"}
               for d in out.get("detections", []) if d.get("label", "").lower() in ("fire", "smoke")]
    # 동적 작업반경(협착) — 지게차·차량 근처 사람 진입(거리 자동추정)
    import proximity as _prox
    import tuning as _tun
    radius_m = float(payload.get("radius_m") or _tun.val("proximity", "radius_m", 3.0, env="VIGENT_RADIUS_M"))
    prox = _prox.detect(out.get("detections", []), radius_m, aspect_hw=H / W)   # 감사 E-1: 종횡비 보정
    return {"success": True, "detections": dets, "hazards": hazards,
            "person_count": out.get("person_count", 0), "signals": out.get("signals", {}),
            "proximity": prox}


@app.post("/safety/live/analyze")
def safety_live_analyze(payload: dict = Body(...)):
    """온디맨드 정밀분석 — 버튼 누른 순간 프레임 1장을 OpenAI 비전으로 이해(매 프레임 아님).
    OpenAI 키 있으면 OpenAI, 실패/키없음이면 로컬 MLX 폴백(가산식). 프레임 전처리는 프론트 그대로(블러 등 미개입)."""
    import json as _json
    import re as _re
    img = _img_from_b64(payload.get("image_base64") or payload.get("image"))
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    PROMPT = ('이 산업현장 CCTV 프레임을 보고 아래 JSON 하나로만 답하라(설명·코드블록 없이):\n'
              '{"상황":"무슨 상황인지 한 문장","재해유형":"끼임/추락/부딪힘/감전/화재/질식/전도/낙하물/무너짐/없음 중 하나",'
              '"위험":"어떤 위험이 임박/존재하는지 한 문장","조치":"권고 조치 한 문장"}\n불확실하면 "불명확".')
    KEYS = ("상황", "재해유형", "위험", "조치")
    obj = None
    engine = None
    try:
        import llm_provider
        text, backend = llm_provider.reason_vision(img, PROMPT)   # OpenAI 우선
        if text:
            engine = backend
            m = _re.search(r"\{.*\}", text, _re.S)
            if m:
                try:
                    obj = _json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    obj = None
    except Exception:  # noqa: BLE001
        obj = None
    if not (isinstance(obj, dict) and any(k in obj for k in KEYS)):   # OpenAI 실패 → 로컬 MLX 폴백
        try:
            import rfdetr_service
            data = rfdetr_service.vlm.summarize_bgr(img, prompt=PROMPT)
            engine = "로컬 MLX"
            if isinstance(data, dict):
                if any(k in data for k in KEYS):
                    obj = data
                elif data.get("raw"):
                    m2 = _re.search(r"\{.*\}", str(data["raw"]), _re.S)
                    obj = _json.loads(m2.group(0)) if m2 else None
        except Exception:  # noqa: BLE001
            obj = None
    if not (isinstance(obj, dict) and any(k in obj for k in KEYS)):
        return {"ok": False, "engine": engine, "error": "분석 실패(폴백 포함)"}
    return {"ok": True, "engine": engine, **{k: str(obj.get(k, "") or "") for k in KEYS}}


@app.post("/recognition/log")
def recognition_log(payload: dict = Body(...)):
    """데이터엔진 — 위험 이벤트 1건 기록(+증거 프레임 저장).
    payload={rule, level, score, site, note, image(data URL, 선택)}"""
    return data_engine.log_event(
        rule=payload.get("rule", ""), level=payload.get("level", ""),
        score=payload.get("score", 0), site=payload.get("site", ""),
        note=payload.get("note", ""), image_data_url=payload.get("image"))


@app.get("/recognition/log")
def recognition_log_list(limit: int = 100, hours: float | None = None):
    """저장된 인식 로그 목록(최신순)."""
    return {"events": data_engine.list_events(limit=limit, hours=hours)}


@app.get("/recognition/log/download")
def recognition_log_download():
    """전체 인식 로그를 JSONL 로 다운로드."""
    lines = [json.dumps(r, ensure_ascii=False) for r in data_engine.list_events(limit=100000)]
    return Response("\n".join(lines), media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=vigent_events.jsonl"})


@app.get("/report/safety", response_class=HTMLResponse)
def report_safety(theme: str = DEFAULT_THEME, hours: float = 24, vlm: bool = False,
                  narrative: bool = False):
    """최근 N시간 누적 이벤트(데이터엔진 집계) 기반 위험성평가서 HTML(인쇄→PDF).
    중대성=실제 등급 분포 산출, 증거사진·정황 반영. vlm=true 면 증거 VLM 장면설명 추가.
    narrative=true 일 때만 종합의견을 LLM 으로 생성(느림). 기본은 결정적 폴백(즉시 · rows·법령 불변).
    누적 이벤트가 없으면 데모 샘플로 렌더(빈 화면 방지)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    events = data_engine.aggregate(hours=hours)
    site = f"최근 {int(hours)}시간 누적"
    if not events:                              # 아직 쌓인 이벤트 없음 → 데모
        events = [{"rule": "zone_intrusion", "count": 5}, {"rule": "ppe_missing", "count": 9},
                  {"rule": "fall_suspected", "count": 1}]
        site = "데모 현장(누적 이벤트 없음)"
    return scribe.generate(events, site=site, process="-", save=False, use_vlm=vlm,
                           use_llm=narrative)["html"]


@app.get("/safety/risk-assessment/list")
def risk_assessment_list(theme: str = DEFAULT_THEME):
    """저장된 위험성평가서 목록(최신순)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    return {"items": bundle["agents"]["Scribe"].list_saved()}


@app.get("/safety/risk-assessment/{aid}", response_class=HTMLResponse)
def risk_assessment_open(aid: str, theme: str = DEFAULT_THEME):
    """저장된 위험성평가서 다시열기(HTML)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    page = bundle["agents"]["Scribe"].load_html(aid)
    if page is None:
        raise HTTPException(status_code=404, detail="평가서 없음")
    return page


@app.get("/safety/reports", response_class=HTMLResponse)
def safety_reports(theme: str = DEFAULT_THEME):
    """저장된 평가서 목록 화면 + '지금 생성' 버튼."""
    bundle = STATE.get(theme) or _load_theme(theme)
    items = bundle["agents"]["Scribe"].list_saved()
    rows = "".join(
        f"""<tr><td>{i['generated_at']}</td><td>{i['site']}</td>
        <td style="text-align:center">{i['총항목']}</td>
        <td style="text-align:center;color:#ef4444">{i['상_높음']}</td>
        <td><a href="/safety/risk-assessment/{i['id']}" target="_blank">열기 ↗</a></td></tr>"""
        for i in items) or '<tr><td colspan="5" style="color:#94a3b8">저장된 평가서가 없습니다. 아래 버튼으로 생성하세요.</td></tr>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>VIGENT 위험성평가서 목록</title><style>
  body{{font-family:"Apple SD Gothic Neo",sans-serif;margin:32px;color:#0e0c08}}
  h1{{font-size:20px}} a{{color:#8a6817}}
  table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
  th,td{{border:1px solid #cbd5e1;padding:8px 10px;text-align:left}} th{{background:#f1f5f9}}
  .btn{{display:inline-block;margin-top:16px;padding:10px 18px;background:#0e0c08;color:#fff;
        border-radius:8px;text-decoration:none}}
</style></head><body>
  <h1>📁 위험성평가서 목록</h1>
  <div style="color:#64748b;font-size:13px">저장 위치: data/risk_assessments/ · 최신순</div>
  <table><thead><tr><th>생성일시</th><th>현장</th><th>총항목</th><th>높음(상)</th><th>열기</th></tr></thead>
  <tbody>{rows}</tbody></table>
  <a class="btn" href="/report/safety" target="_blank">＋ 지금 평가서 생성(누적 이벤트 기반)</a>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# 작업 전 TBM(안전점검 회의) — 작성·저장·열기 (한전 스마트TBM '작업 전' 단계)
# ─────────────────────────────────────────────────────────────
_TBM_CSS = """
  body{font-family:"Apple SD Gothic Neo",sans-serif;margin:0;background:#0e0c08;color:#e2e8f0}
  .wrap{max-width:760px;margin:0 auto;padding:28px 20px 80px}
  h1{font-size:21px;margin:4px 0 2px} .sub{color:#94a3b8;font-size:13px;margin-bottom:20px}
  a{color:#d4a017;text-decoration:none}
  .card{background:#17150e;border:1px solid #2a2a2e;border-radius:12px;padding:18px;margin-bottom:14px}
  .card h2{font-size:15px;margin:0 0 12px;color:#d4a017}
  label.fld{display:block;font-size:13px;color:#cbd5e1;margin:10px 0 4px}
  input[type=text],textarea{width:100%;box-sizing:border-box;background:#0e0c08;border:1px solid #2a2a2e;
    border-radius:8px;color:#e2e8f0;padding:9px 11px;font-size:14px;font-family:inherit}
  textarea{min-height:64px;resize:vertical}
  .row{display:flex;gap:8px} .row input{flex:1}
  .chk{display:flex;align-items:center;gap:8px;font-size:13.5px;padding:7px 0;border-bottom:1px solid #29374a}
  .chk:last-child{border-bottom:none}
  .chk input{width:17px;height:17px;accent-color:#22c55e}
  .tag{display:inline-flex;align-items:center;gap:6px;background:#0b2545;border:1px solid #8a6817;
    color:#bfdbfe;border-radius:999px;padding:5px 10px;font-size:13px;margin:4px 6px 0 0}
  .tag b{cursor:pointer;color:#d4a017}
  .wk{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #29374a}
  .wk .nm{flex:1} .wk small{color:#94a3b8}
  .btn{display:inline-block;padding:10px 16px;border-radius:8px;border:1px solid #2a2a2e;
    background:#0e0c08;color:#e2e8f0;font-size:14px;cursor:pointer}
  .btn.add{padding:9px 14px}
  .btn.primary{background:#8a6817;border-color:#8a6817;color:#fff;font-weight:700}
  .bar{position:fixed;left:0;right:0;bottom:0;background:#0a0a0c;border-top:1px solid #2a2a2e;
    padding:14px 20px;display:flex;justify-content:center;gap:10px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th,td{border:1px solid #2a2a2e;padding:8px 10px;text-align:left} th{background:#162133;color:#d4a017}
  .dim{color:#94a3b8;font-size:13px}
  .suggest{margin-top:10px;background:#0b1628;border:1px solid #1d3a5f;border-radius:10px;padding:12px}
  .sg-h{font-size:13px;color:#d4a017;font-weight:700;margin-bottom:6px}
  .sg-sec{font-size:13px;color:#cbd5e1;margin:12px 0 5px;display:flex;align-items:center;gap:8px}
  .tag.sg{cursor:pointer;background:#0f2a18;border-color:#15803d;color:#bbf7d0}
  .tag.sg.added{opacity:.45;cursor:default;background:#17150e;border-color:#2a2a2e;color:#94a3b8}
  .btn.add.sm{padding:3px 9px;font-size:12px}
  details.sg-sec summary{cursor:pointer;color:#d4a017}
  ul.cites{margin:6px 0 0;padding-left:18px;font-size:12.5px;line-height:1.5}
  ul.cites b{color:#cbd5e1}
"""

# 작성 화면(plain 문자열 — JS 중괄호 보존). /*CSS*/ <!--CHECKLIST--> <!--PROCESSLIST--> 가 치환된다.
_TBM_NEW_HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 새 TBM 회의록</title><style>/*CSS*/</style></head><body><div class="wrap">
  <h1>📋 새 TBM 회의록 작성</h1>
  <div class="sub">작업 전 안전점검 회의(툴박스미팅) · 작성 후 저장하면 인쇄/PDF 가능</div>

  <div class="card"><h2>작업 정보</h2>
    <label class="fld">현장</label><input id="site" type="text" placeholder="예: ○○변전소 22.9kV 개폐기 교체 현장">
    <label class="fld">작업공종</label>
    <div class="row"><input id="process" type="text" list="processList" placeholder="예: 활선작업 / 고소작업 / 굴착작업"
      onkeydown="if(event.key==='Enter'){event.preventDefault();getSuggest();}">
      <button class="btn add" onclick="getSuggest()">🔎 위험요인 추천</button></div>
    <datalist id="processList"><!--PROCESSLIST--></datalist>
    <div id="suggestBox" class="suggest" style="display:none"></div>
    <label class="fld">작업내용</label><textarea id="work_desc" placeholder="오늘 수행할 작업 내용을 적습니다"></textarea>
    <label class="fld">감독관</label><input id="supervisor" type="text" placeholder="예: 홍길동 감독관">
  </div>

  <div class="card"><h2>중점 관리 위험요인</h2>
    <div class="row"><input id="hazIn" type="text" placeholder="예: 활선 감전 위험"
      onkeydown="if(event.key==='Enter'){event.preventDefault();addHaz();}">
      <button class="btn add" onclick="addHaz()">추가</button></div>
    <div id="hazList" style="margin-top:6px"></div>
  </div>

  <div class="card"><h2>작업 전 안전점검</h2>
    <div id="chkList"><!--CHECKLIST--></div>
  </div>

  <div class="card"><h2>참석 작업자(서명)</h2>
    <div class="row"><input id="wkIn" type="text" placeholder="작업자 이름"
      onkeydown="if(event.key==='Enter'){event.preventDefault();addWk();}">
      <button class="btn add" onclick="addWk()">추가</button></div>
    <div id="wkList" style="margin-top:6px"></div>
    <small style="color:#94a3b8;display:block;margin-top:6px">※ 회의 내용을 확인한 작업자는 '서명'에 체크합니다.</small>
  </div>

  <div class="card"><h2>전달사항</h2>
    <textarea id="notes" placeholder="추가 전달·공지 사항(선택)"></textarea>
  </div>

  <div class="bar">
    <a class="btn" href="/safety/tbm">취소</a>
    <button class="btn primary" id="saveBtn" onclick="save()">저장하기</button>
  </div>
</div>
<script>
  const hazards = [];
  const workers = [];
  let lastSuggest = null;
  function escHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  async function getSuggest(){
    const process = document.getElementById('process').value.trim();
    const box = document.getElementById('suggestBox');
    box.style.display='block'; box.innerHTML='<div class="dim">추천 불러오는 중…</div>';
    try{
      const res = await fetch('/safety/tbm/suggest?process='+encodeURIComponent(process));
      lastSuggest = await res.json(); renderSuggest(lastSuggest);
    }catch(e){ box.innerHTML='<div class="dim">추천 오류: '+e+'</div>'; }
  }
  function renderSuggest(s){
    const box = document.getElementById('suggestBox');
    const label = s.fallback ? '⚠ 일반작업 기준(공종 미매칭) — 공종을 더 구체적으로 입력하면 정확해집니다' : ('✅ 매칭 공종: '+escHtml(s.matched));
    const chip = (v)=>'<span class="tag sg" data-val="'+escHtml(v)+'" onclick="pickChip(this)">＋ '+escHtml(v)+'</span>';
    const hazChips = (s.hazards||[]).map(chip).join('') || '<span class="dim">없음</span>';
    const chkChips = (s.checklist||[]).map(chip).join('') || '<span class="dim">없음</span>';
    const cites = (s.citations||[]).map(c=>'<li><b>'+escHtml(c.source)+'</b> '+escHtml(c.clause)+'<br><span class="dim">'+escHtml(c.snippet)+'</span></li>').join('') || '<li class="dim">근거 없음</li>';
    box.innerHTML =
      '<div class="sg-h">'+label+'</div>'+
      '<div class="sg-sec">중점 위험요인 <button class="btn add sm" onclick="addAll(\'haz\')">모두 추가</button></div><div data-kind="haz">'+hazChips+'</div>'+
      '<div class="sg-sec">작업 전 점검항목 <button class="btn add sm" onclick="addAll(\'chk\')">모두 추가</button></div><div data-kind="chk">'+chkChips+'</div>'+
      '<details class="sg-sec"><summary>관련 법령 근거 ('+(s.citations||[]).length+')</summary><ul class="cites">'+cites+'</ul></details>';
  }
  function pickChip(el){
    const v = el.dataset.val; const kind = el.parentElement.dataset.kind;
    if(kind==='haz'){ if(!hazards.includes(v)){ hazards.push(v); renderHaz(); } }
    else { addChkItem(v); }
    el.classList.add('added'); el.setAttribute('onclick','');
  }
  function addAll(kind){
    if(!lastSuggest) return;
    document.querySelectorAll('#suggestBox [data-kind="'+kind+'"] .tag.sg:not(.added)').forEach(pickChip);
  }
  function chkExists(v){ return [...document.querySelectorAll('#chkList .chk input')].some(i=>i.dataset.item===v); }
  function addChkItem(v){
    if(chkExists(v)) return;
    const lab=document.createElement('label'); lab.className='chk';
    lab.innerHTML='<input type="checkbox" checked data-item="'+escHtml(v)+'"><span>'+escHtml(v)+'</span>';
    document.getElementById('chkList').appendChild(lab);
  }
  function renderHaz(){
    document.getElementById('hazList').innerHTML = hazards.map((h,idx)=>
      '<span class="tag">'+h+' <b onclick="delHaz('+idx+')">✕</b></span>').join('');
  }
  function addHaz(){
    const el = document.getElementById('hazIn'); const v = el.value.trim();
    if(!v) return; hazards.push(v); el.value=''; el.focus(); renderHaz();
  }
  function delHaz(i){ hazards.splice(i,1); renderHaz(); }
  function renderWk(){
    document.getElementById('wkList').innerHTML = workers.map((w,idx)=>
      '<div class="wk"><span class="nm">'+w.name+'</span>'+
      '<label><input type="checkbox" '+(w.signed?'checked':'')+' onchange="signWk('+idx+',this.checked)"> 서명</label>'+
      '<b style="cursor:pointer;color:#f87171" onclick="delWk('+idx+')">✕</b></div>').join('');
  }
  function addWk(){
    const el = document.getElementById('wkIn'); const v = el.value.trim();
    if(!v) return; workers.push({name:v, signed:false}); el.value=''; el.focus(); renderWk();
  }
  function signWk(i,ok){ workers[i].signed = ok; }
  function delWk(i){ workers.splice(i,1); renderWk(); }
  async function save(){
    const btn = document.getElementById('saveBtn'); btn.disabled = true; btn.textContent='저장 중…';
    const checklist = [...document.querySelectorAll('#chkList .chk input')].map(i=>({item:i.dataset.item, ok:i.checked}));
    const payload = {
      site: document.getElementById('site').value,
      process: document.getElementById('process').value,
      work_desc: document.getElementById('work_desc').value,
      supervisor: document.getElementById('supervisor').value,
      hazards, checklist, workers,
      notes: document.getElementById('notes').value,
    };
    try{
      const res = await fetch('/safety/tbm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const j = await res.json();
      if(j && j.id){ location.href = '/safety/tbm/'+j.id; }
      else { alert('저장 실패'); btn.disabled=false; btn.textContent='저장하기'; }
    }catch(e){ alert('저장 오류: '+e); btn.disabled=false; btn.textContent='저장하기'; }
  }
</script></body></html>"""


# 안전 자동처리 콘솔 화면(plain 문자열 — JS 중괄호 보존). /*CSS*/ 만 치환된다.
_AUTO_HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 안전 자동처리 콘솔</title><style>/*CSS*/
  .top{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}
  .stat{display:flex;gap:10px;margin:10px 0}
  .stat .box{flex:1;background:#17150e;border:1px solid #2a2a2e;border-radius:10px;padding:12px;text-align:center}
  .stat .box b{display:block;font-size:24px;color:#d4a017}
  .disc{background:#3a2a0b;border:1px solid #a16207;color:#fde68a;border-radius:8px;padding:10px 12px;font-size:12.5px;margin:10px 0;line-height:1.6}
  .ev{background:#17150e;border:1px solid #2a2a2e;border-radius:12px;padding:14px;margin-bottom:12px}
  .ev .hd{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
  .ev .rule{font-weight:700;font-size:15px}
  .lv{padding:2px 8px;border-radius:6px;font-size:11px;font-weight:700}
  .lv.high{background:#7f1d1d;color:#fecaca} .lv.mid{background:#78350f;color:#fed7aa} .lv.low{background:#14532d;color:#bbf7d0}
  .pipe{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0;font-size:12px}
  .step{padding:4px 9px;border-radius:999px;border:1px solid #2a2a2e;color:#94a3b8;background:#0e0c08}
  .step.on{border-color:#15803d;color:#bbf7d0;background:#0f2a18}
  .step.wait{border-color:#a16207;color:#fde68a;background:#3a2a0b}
  .ev .meta{font-size:12.5px;color:#cbd5e1;margin:4px 0;line-height:1.6} .ev .meta b{color:#d4a017}
  .ev img{max-width:160px;border-radius:8px;border:1px solid #2a2a2e;margin-top:6px;display:block}
  .acts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
  .ok{color:#86efac;font-size:13px;align-self:center}
</style></head><body><div class="wrap">
  <div class="top">
    <h1>🛡 안전 자동처리 콘솔</h1>
    <div style="display:flex;gap:8px">
      <a class="btn" href="/safety">← 실시간 관제</a>
      <a class="btn" href="/safety/auto/audit">🧾 감사추적</a>
    </div>
  </div>
  <div class="sub">실시간 관제(비전)에서 잡힌 위험이 여기로 모여, 증거·법령·위험성평가·조치로 자동 정리됩니다.</div>
  <div class="disc">⚠ 본 콘솔의 판정·권고는 <b>보조 신호</b>입니다. 위험성평가·조치의 <b>최종 승인은 안전관리자</b>가 수행하며,
    법적 책임은 사용자·사업주에게 있습니다. 인증 안전장치(비상정지 등)를 대체하지 않습니다(§8).</div>
  <div class="stat" id="stat"></div>
  <div id="feed"><div class="dim">불러오는 중…</div></div>
</div>
<script>
  const esc = s => String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const lvClass = l => (l==='high'?'high':((l==='mid'||l==='medium')?'mid':'low'));
  let DATA = {events:[], summary:{}};
  function step(label,on,wait){ return '<span class="step'+(on?' on':(wait?' wait':''))+'">'+esc(label)+'</span>'; }
  function card(e,i){
    const ok = e.approved;
    const pipe = step('감지',true,false)+step('증거',!!e.evidence_url,false)+step('법령',!!e.law,false)+
                 step(ok?'위험성평가 ✓':'위험성평가 승인대기', ok, !ok)+
                 step(ok?'조치 ✓':'조치 권고', ok, !ok);
    const img = e.evidence_url ? '<img src="'+esc(e.evidence_url)+'" alt="증거">' : '';
    const acts = ok
      ? '<span class="ok">✅ '+esc(e.approver||'안전관리자')+' 승인됨'+(e.ra_aid?' · <a href="/safety/risk-assessment/'+esc(e.ra_aid)+'" target="_blank">평가서 열기 ↗</a>':'')+'</span>'
      : '<button class="btn primary" data-i="'+i+'" data-act="risk_assessment">위험성평가 승인·생성</button>'+
        '<button class="btn" data-i="'+i+'" data-act="acknowledge">조치 확인</button>';
    return '<div class="ev" id="ev'+i+'">'+
      '<div class="hd"><span class="rule">'+esc(e.rule||'이벤트')+'</span>'+
        '<span><span class="lv '+lvClass(e.level)+'">'+esc((e.level||'').toUpperCase()||'-')+'</span> '+
        '<span class="dim">'+esc((e.date||'')+' '+(e.time||''))+' · '+esc(e.site||'-')+'</span></span></div>'+
      '<div class="pipe">'+pipe+'</div>'+
      (e.law?'<div class="meta"><b>관련 법령</b> '+esc(e.law)+'</div>':'')+
      '<div class="meta"><b>권고 조치</b> '+esc(e.advisory)+'</div>'+ img +
      '<div class="acts">'+acts+'</div></div>';
  }
  function render(){
    const s = DATA.summary||{};
    document.getElementById('stat').innerHTML =
      '<div class="box"><b>'+(s['감지']||0)+'</b>감지</div>'+
      '<div class="box"><b>'+(s['증거']||0)+'</b>증거</div>'+
      '<div class="box"><b>'+(s['승인']||0)+'</b>승인(서류·조치)</div>';
    const feed = document.getElementById('feed');
    if(!(DATA.events||[]).length){ feed.innerHTML='<div class="dim">표시할 위험 이벤트가 없습니다. 실시간 관제에서 위험이 발생하면 여기에 쌓입니다.</div>'; return; }
    feed.innerHTML = DATA.events.map((e,i)=>card(e,i)).join('');
  }
  async function load(){
    try{ const r = await fetch('/safety/auto/feed'); DATA = await r.json(); render(); }
    catch(e){ document.getElementById('feed').innerHTML = '<div class="dim">불러오기 오류: '+e+'</div>'; }
  }
  async function approve(i, action){
    const e = DATA.events[i]; if(!e) return;
    const btns = document.querySelectorAll('#ev'+i+' .acts button'); btns.forEach(b=>b.disabled=true);
    try{
      const r = await fetch('/safety/auto/approve',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({event_ts:e.ts, rule:e.rule, site:e.site, action:action})});
      const j = await r.json();
      if(j && j.ok){ if(j.ra_aid) window.open('/safety/risk-assessment/'+j.ra_aid,'_blank'); load(); }
      else { alert('승인 실패'); btns.forEach(b=>b.disabled=false); }
    }catch(err){ alert('오류: '+err); btns.forEach(b=>b.disabled=false); }
  }
  document.getElementById('feed').addEventListener('click', ev=>{
    const b = ev.target.closest('button[data-act]'); if(!b) return;
    approve(parseInt(b.dataset.i,10), b.dataset.act);
  });
  load();
</script></body></html>"""


@app.get("/safety/tbm", response_class=HTMLResponse)
def tbm_list():
    """저장된 TBM 회의록 목록 + '새 회의록 작성' 버튼."""
    items = tbm_store.list_recent()
    rows = "".join(
        f"""<tr><td>{i['created_at'][:16].replace('T',' ')}</td><td>{i['site'] or '-'}</td>
        <td>{i['process'] or '-'}</td><td style="text-align:center">{i['signed_count']}/{i['worker_count']}</td>
        <td style="text-align:center">{i['hazard_count']}</td>
        <td><a href="/safety/tbm/{i['id']}" target="_blank">열기 ↗</a></td></tr>"""
        for i in items) or '<tr><td colspan="6" style="color:#64748b">저장된 회의록이 없습니다. 새 회의록을 작성하세요.</td></tr>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 작업 전 TBM 회의록</title><style>{_TBM_CSS}</style></head><body><div class="wrap">
  <h1>📋 작업 전 TBM 회의록</h1>
  <div class="sub">작업 전 안전점검 회의(툴박스미팅) 기록 · 저장 위치 data/tbm/ · 최신순</div>
  <div class="card"><table>
    <thead><tr><th>작성일시</th><th>현장</th><th>작업공종</th><th>서명</th><th>위험요인</th><th>열기</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <a class="btn primary" href="/safety/tbm/new">＋ 새 회의록 작성</a>
</div></body></html>"""


@app.get("/safety/tbm/new", response_class=HTMLResponse)
def tbm_new():
    """TBM 회의록 작성 화면(작성 후 저장 → 열기로 이동)."""
    checklist_html = "".join(
        '<label class="chk"><input type="checkbox" checked data-item="ITEM"><span>ITEM</span></label>'
        .replace("ITEM", item) for item in tbm_store.DEFAULT_CHECKLIST)
    process_html = "".join(f'<option value="{j["name"]}">' for j in tbm_store.jsa_catalog())
    page = (_TBM_NEW_HTML.replace("/*CSS*/", _TBM_CSS)
            .replace("<!--CHECKLIST-->", checklist_html)
            .replace("<!--PROCESSLIST-->", process_html))
    return page


@app.post("/safety/tbm")
def tbm_create(payload: dict = Body(...)):
    """회의록 1건 저장. payload={site,process,work_desc,supervisor,hazards[],checklist[],workers[],notes}."""
    rec = tbm_store.create(payload)
    return {"id": rec["id"], "saved_path": rec["saved_path"]}


@app.get("/safety/tbm/suggest")
def tbm_suggest(process: str = "", theme: str = DEFAULT_THEME):
    """작업공종 → 중점 위험요인·점검항목 추천 + 법령 근거(규칙 인용).
    매칭 실패 시 일반작업으로 폴백(빈손 방지). 근거는 기존 코퍼스에서만 인용한다(§9)."""
    s = tbm_store.suggest(process)
    bundle = STATE.get(theme) or _load_theme(theme)
    copilot = bundle["agents"].get("Copilot")
    citations, seen = [], set()
    if copilot:
        for rid in s.get("rules", []):
            for c in copilot.cite(rid).get("citations", []) or []:
                key = (c.get("source"), c.get("clause"))
                if key in seen:
                    continue
                seen.add(key)
                citations.append(c)
    s["citations"] = citations
    return s


@app.post("/safety/tbm/{tid}/risk-assessment")
def tbm_to_risk_assessment(tid: str, theme: str = DEFAULT_THEME):
    """TBM 회의록 1건 → 위험성평가서 자동 생성(이중입력 제거).
    공종 매칭 규칙 + 작성자가 직접 적은 위험요인(키워드 매칭)을 합쳐 평가 이벤트로 변환한다."""
    rec = tbm_store.get(tid)
    if not rec:
        raise HTTPException(status_code=404, detail=f"회의록 없음: {tid}")
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    copilot = bundle["agents"].get("Copilot")
    # 1) 작업공종 → 추천 규칙
    rules = list(tbm_store.suggest(rec.get("process", "")).get("rules", []))
    # 2) 작성자가 직접 적은 위험요인 텍스트 → 규칙 매칭(추가 반영)
    if copilot is not None:
        for h in rec.get("hazards", []) or []:
            for rid in copilot.match_rules(h):
                if rid not in rules:
                    rules.append(rid)
    events = [{"rule": r, "count": 1} for r in rules]
    out = scribe.generate(events, site=rec.get("site", "") or "TBM 연동",
                          process=rec.get("process", ""), save=True)
    aid = Path(out["saved_path"]).stem if out.get("saved_path") else None
    return {"aid": aid, "saved_path": out.get("saved_path"),
            "rules": rules, "row_count": out["assessment"]["summary"]["총항목"]}


# TBM 열기 화면의 '위험성평가서 만들기' 버튼 스크립트(__TID__ 치환). f-string 중괄호 회피용 별도 상수.
_TBM_VIEW_SCRIPT = """<script>
  async function makeRA(ev){
    const btn = ev.target; btn.disabled = true; btn.textContent = '생성 중…';
    try{
      const res = await fetch('/safety/tbm/__TID__/risk-assessment', {method:'POST'});
      const j = await res.json();
      if(j && j.aid){ window.open('/safety/risk-assessment/'+j.aid, '_blank'); btn.textContent = '✅ 평가서 생성됨('+j.row_count+'건)'; }
      else { alert('생성 실패'); btn.disabled=false; btn.textContent='📋 위험성평가서 만들기'; }
    }catch(e){ alert('오류: '+e); btn.disabled=false; btn.textContent='📋 위험성평가서 만들기'; }
  }
</script>"""


@app.get("/safety/tbm/{tid}", response_class=HTMLResponse)
def tbm_open(tid: str):
    """저장된 회의록 열기(인쇄 가능 HTML)."""
    r = tbm_store.get(tid)
    if not r:
        raise HTTPException(status_code=404, detail=f"회의록 없음: {tid}")
    haz = "".join(f"<li>{h}</li>" for h in r.get("hazards", [])) or '<li style="color:#64748b">등록된 위험요인 없음</li>'
    chk = "".join(
        f"""<tr><td style="text-align:center">{'✅' if c.get('ok') else '⬜'}</td><td>{c.get('item','')}</td></tr>"""
        for c in r.get("checklist", []))
    wks = "".join(
        f"""<tr><td>{w.get('name','')}</td><td style="text-align:center">{'서명함 ✔' if w.get('signed') else '미서명'}</td></tr>"""
        for w in r.get("workers", [])) or '<tr><td colspan="2" style="color:#64748b">참석 작업자 없음</td></tr>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TBM 회의록 · {r.get('site','')}</title><style>{_TBM_CSS}</style></head><body><div class="wrap">
  <h1>📋 작업 전 TBM 회의록</h1>
  <div class="sub">{r.get('created_at','')[:16].replace('T',' ')} · {r.get('id','')}</div>
  <div class="card"><h2>작업 정보</h2>
    <table>
      <tr><th style="width:110px">현장</th><td>{r.get('site','') or '-'}</td></tr>
      <tr><th>작업공종</th><td>{r.get('process','') or '-'}</td></tr>
      <tr><th>작업내용</th><td>{(r.get('work_desc','') or '-').replace(chr(10),'<br>')}</td></tr>
      <tr><th>감독관</th><td>{r.get('supervisor','') or '-'}</td></tr>
    </table></div>
  <div class="card"><h2>중점 관리 위험요인</h2><ul>{haz}</ul></div>
  <div class="card"><h2>작업 전 안전점검</h2><table>
    <thead><tr><th style="width:60px">확인</th><th>점검 항목</th></tr></thead><tbody>{chk}</tbody></table></div>
  <div class="card"><h2>참석 작업자 ({sum(1 for w in r.get('workers',[]) if w.get('signed'))}/{len(r.get('workers',[]))} 서명)</h2>
    <table><thead><tr><th>이름</th><th style="width:120px">서명</th></tr></thead><tbody>{wks}</tbody></table></div>
  <div class="card"><h2>전달사항</h2><div style="white-space:pre-wrap;font-size:14px">{r.get('notes','') or '-'}</div></div>
  <div class="bar">
    <a class="btn" href="/safety/tbm">목록</a>
    <button class="btn" onclick="makeRA(event)">📋 위험성평가서 만들기</button>
    <button class="btn primary" onclick="window.print()">🖨 인쇄 / PDF 저장</button>
  </div>
  {_TBM_VIEW_SCRIPT.replace("__TID__", r.get("id", ""))}
</div></body></html>"""


# ─────────────────────────────────────────────────────────────
# 안전 자동처리 콘솔 — 위험 감지 → 증거·법령·위험성평가·조치 자동 정리(사람 승인)
# 책임 회피 설계: advisory(자동실행 X) + 안전관리자 승인 게이트 + 감사추적 + 면책 문구
# ─────────────────────────────────────────────────────────────
_ADVISORY = {
    "fall_suspected": "작업자 상태 즉시 확인 · 추락방지(안전대·안전난간·작업발판) 점검 · 필요시 작업 일시중지 검토",
    "ppe_missing": "보호구 착용 지도 · 미착용자 작업 제한 검토 · 보호구 비치 상태 확인",
    "zone_intrusion": "출입통제 상태 확인 · 작업자 위험구역 이탈 안내 · 경고표지 점검",
    "guard_bypass": "위험기계 정지상태 확인(1차 책임=인증 방호장치) · 작업자 신체 이탈 · 방호장치 점검",
    "fire_smoke": "초기대응·대피 절차 확인 · 소화설비 점검 · 화기작업 허가 여부 확인",
    "trip_hazard": "통로·바닥 정리정돈 · 전선·자재 제거 · 미끄럼 방지 조치",
    "ergonomic_risk": "작업자세 개선 안내 · 중량물 보조기구 · 주기적 휴식 권고",
}


def _evidence_url(path: str | None) -> str | None:
    """data/evidence/... 저장경로 → /evidence/... 서빙 URL."""
    if path and path.startswith("data/evidence/"):
        return "/evidence/" + path[len("data/evidence/"):]
    return None


@app.get("/safety/auto/feed")
def safety_auto_feed(theme: str = DEFAULT_THEME, hours: float = 24, limit: int = 50):
    """자동처리 피드 — 최근 위험 이벤트 + 증거·법령·승인상태(콘솔이 폴링)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    copilot = bundle["agents"].get("Copilot")
    events = data_engine.list_events(limit=limit, hours=hours)
    audit_map = audit_store.by_event()
    out, approved_n = [], 0
    for e in events:
        rule = e.get("rule", "")
        law = ""
        if copilot and rule:
            cs = copilot.cite(rule).get("citations", []) or []
            if cs:
                law = f"{cs[0].get('source','')} {cs[0].get('clause','')}".strip()
        appr = audit_map.get(audit_store.event_key(e.get("ts", ""), rule))
        if appr:
            approved_n += 1
        out.append({
            "ts": e.get("ts"), "time": e.get("time"), "date": e.get("date"),
            "rule": rule, "level": e.get("level", ""), "site": e.get("site", ""),
            "evidence_url": _evidence_url(e.get("evidence")),
            "law": law,
            "advisory": _ADVISORY.get(rule, "안전관리자 확인 후 현장 상황에 맞는 조치"),
            "approved": bool(appr),
            "ra_aid": (appr or {}).get("ra_aid", ""),
            "approver": (appr or {}).get("approver", ""),
        })
    return {"events": out, "summary": {
        "감지": len(out),
        "증거": sum(1 for o in out if o["evidence_url"]),
        "승인": approved_n}}


@app.post("/safety/auto/approve")
def safety_auto_approve(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """안전관리자 승인 — 위험성평가 자동생성 또는 조치확인을 감사추적에 기록(사람이 최종판단).
    payload={event_ts, rule, site?, approver?, action: 'risk_assessment'|'acknowledge'}"""
    event_ts = payload.get("event_ts", "")
    rule = payload.get("rule", "")
    action = payload.get("action", "acknowledge")
    approver = payload.get("approver") or "안전관리자"
    site = payload.get("site", "")
    ra_aid = ""
    if action == "risk_assessment":
        bundle = STATE.get(theme) or _load_theme(theme)
        scribe = bundle["agents"].get("Scribe")
        # 이 이벤트(같은 ts+rule)의 증거 사진 경로 수집 → 평가서에 자동 첨부(+VLM 장면설명)
        ev_paths = [e.get("evidence") for e in data_engine.list_events(limit=2000)
                    if e.get("ts") == event_ts and e.get("rule") == rule and e.get("evidence")]
        ev_items = []
        if ev_paths:
            import cv2
            import vlm_confirm as _vc
            for i, p in enumerate(ev_paths[:4]):
                note = ""
                fp = _ROOT / p
                if i == 0 and fp.exists():        # 첫 사진만 VLM 장면분석(지연 제한)
                    note = _vc.describe_scene(cv2.imread(str(fp)))
                ev_items.append({"path": p, "note": note})
        out = scribe.generate([{"rule": rule, "count": 1, "evidence_items": ev_items}],
                              site=site or "자동처리 승인", process="-", save=True)
        ra_aid = Path(out["saved_path"]).stem if out.get("saved_path") else ""
    rec = audit_store.record(event_ts, rule, action, approver=approver, site=site, ra_aid=ra_aid)
    return {"ok": True, "audit": rec, "ra_aid": ra_aid}


@app.get("/safety/auto/audit", response_class=HTMLResponse)
def safety_auto_audit():
    """감사추적 — 누가·언제·무엇을 승인했는지(사람 최종판단 입증용)."""
    items = audit_store.list_recent()
    act_ko = {"risk_assessment": "위험성평가 승인·생성", "acknowledge": "조치 확인"}
    rows = "".join(
        f"""<tr><td>{i.get('at','')[:19].replace('T',' ')}</td><td>{i.get('approver','')}</td>
        <td>{i.get('rule','')}</td><td>{act_ko.get(i.get('action',''), i.get('action',''))}</td>
        <td>{i.get('site','') or '-'}</td>
        <td>{('<a href="/safety/risk-assessment/'+i['ra_aid']+'" target="_blank">평가서 ↗</a>') if i.get('ra_aid') else '-'}</td></tr>"""
        for i in items) or '<tr><td colspan="6" style="color:#64748b">아직 승인 이력이 없습니다.</td></tr>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 감사추적</title><style>{_TBM_CSS}</style></head><body><div class="wrap">
  <h1>🧾 감사추적(승인 이력)</h1>
  <div class="sub">위험성평가·조치의 최종 승인은 안전관리자가 수행함을 기록합니다 · 저장 data/audit/ · 최신순</div>
  <div class="card"><table>
    <thead><tr><th>승인 일시</th><th>승인자</th><th>위험</th><th>조치 유형</th><th>현장</th><th>평가서</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <a class="btn" href="/safety/auto">← 자동처리 콘솔</a>
</div></body></html>"""


@app.get("/safety/auto", response_class=HTMLResponse)
def safety_auto_console():
    """안전 자동처리 콘솔(읽기 + 승인). 비전이 잡은 위험 → 서류·조치 자동 정리."""
    return _AUTO_HTML.replace("/*CSS*/", _TBM_CSS)


# ── 서버사이드 추론 워커(브라우저 없이 서버가 영상 감시) — 다현장 N대 관리 ──
@app.post("/worker/start")
def worker_start(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """카메라 1대 워커 시작. payload={id?, source(RTSP/비디오/이미지/웹캠번호), name?, fps?, zone?}.
    위험 감지 시 data_engine 기록 → 자동처리 콘솔 자동 노출."""
    import worker as _w
    bundle = STATE.get(theme) or _load_theme(theme)
    src = str(payload.get("source", "")).strip()
    if not src:
        raise HTTPException(status_code=400, detail="source(RTSP/비디오/이미지 경로 또는 웹캠번호) 필요")
    return _w.manager.start(bundle["agents"].get("Guard"), _DETECT_LOCK,
                            str(payload.get("id", "cam1")), src,
                            name=str(payload.get("name", "")),
                            fps=float(payload.get("fps", 2.0)), zone=payload.get("zone"))


@app.post("/worker/stop")
def worker_stop(payload: dict = Body(default={})):
    """워커 중지. payload={id} 면 그 카메라만, 없으면 전체."""
    import worker as _w
    cid = payload.get("id")
    return _w.manager.stop(cid) if cid else _w.manager.stop_all()


@app.get("/worker/status")
@app.get("/workers")
def worker_status():
    """전체 워커 상태(현장명 + 카메라별 처리프레임·이벤트·오류)."""
    import worker as _w
    return _w.manager.status()


@app.post("/workers/start-all")
def workers_start_all(theme: str = DEFAULT_THEME):
    """config/site.yaml 의 모든 카메라로 워커 일괄 시작(헤드리스/USB 부팅용)."""
    import worker as _w
    bundle = STATE.get(theme) or _load_theme(theme)
    return _w.manager.autostart(bundle["agents"].get("Guard"), _DETECT_LOCK)


@app.post("/workers/stop-all")
def workers_stop_all():
    """모든 워커 중지."""
    import worker as _w
    return _w.manager.stop_all()


@app.get("/safety/brain", response_class=HTMLResponse)
def safety_brain_page():
    """안전 지식 추론 엔진 UI — 작업별 필수조치/법령/조치 + VLM '없는 조치' 추론."""
    import safety_brain
    return safety_brain.render()


@app.get("/safety/brain/activities")
def safety_brain_activities():
    import safety_brain
    return {"activities": safety_brain.list_activities()}


@app.get("/safety/brain/search")
def safety_brain_search(q: str, k: int = 5):
    """안전 지식 RAG 검색 — 법령·KOSHA 가이드·작업지식에서 관련 스니펫 top-k."""
    import safety_rag
    return {"query": q, "results": safety_rag.retrieve(q, k=k)}


@app.post("/safety/brain/assess")
def safety_brain_assess(payload: dict = Body(...)):
    """장면 점검 — payload={activity, present?:[classes], image_base64?, use_vlm?}.
    반환: 필수조치 충족/부재(present/missing/unknown) + 위험·법령·조치."""
    import safety_brain
    img = None
    raw = payload.get("image_base64") or payload.get("image")
    if raw:
        if not str(raw).startswith("data:"):
            raw = "data:image/jpeg;base64," + raw
        img = _decode_data_url(raw)
    return safety_brain.assess(payload.get("activity", ""), payload.get("present"),
                               image_bgr=img, use_vlm=bool(payload.get("use_vlm")))


@app.get("/safety/eval", response_class=HTMLResponse)
def safety_eval_page():
    """정확도 측정 도구 — 위험/정상 사진으로 재현율·정밀도 자체 측정."""
    import evaluator
    return evaluator.render()


@app.post("/safety/eval/run")
def safety_eval_run(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """위험/정상 사진 묶음 → 각 사진 경보여부 판정 → 재현율·정밀도 집계."""
    import evaluator
    metric = payload.get("metric", "proximity")
    items = payload.get("items", [])
    if not items:
        return {"ok": False, "error": "사진 없음"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    import proximity as _prox
    results, details = [], []
    for idx, it in enumerate(items):
        raw = it.get("image_base64") or ""
        img = _img_from_b64(raw)
        if img is None:
            continue
        boxes, dets, hazards = [], [], []
        try:
            with _DETECT_LOCK:
                out = guard.detect(img, detectors=["person", "ppe", "forklift", "fire_smoke"])
            dets = out.get("detections", [])
            boxes = _incident_boxes(out, _prox.detect(dets))
            pred = evaluator.predict(dets, metric) if metric != "auto" else False
            if metric == "auto":
                hazards = evaluator.detected_hazards(dets)
        except Exception:  # noqa: BLE001
            pred = False
        if metric == "auto":
            details.append({"idx": idx, "boxes": boxes, "hazards": hazards})
            continue
        truth = bool(it.get("truth"))
        outcome = ("TP" if truth and pred else "FN" if truth and not pred
                   else "FP" if (not truth) and pred else "TN")
        results.append({"truth": truth, "pred": bool(pred)})
        details.append({"idx": idx, "truth": truth, "pred": bool(pred),
                        "outcome": outcome, "boxes": boxes})
    if metric == "auto":
        return {"ok": True, "metric": "auto", "summary": None, "details": details}
    return {"ok": True, "metric": metric,
            "summary": evaluator.summarize(results), "details": details}


@app.get("/safety/guide", response_class=HTMLResponse)
def safety_guide_page():
    """현장 음성 안전 안내 — 카메라 화면을 분석해 위험·작업을 음성으로."""
    import liveguide
    return liveguide.render()


@app.post("/safety/voice/scene")
def safety_voice_scene(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """실시간 프레임 → 위험·작업 인식 → 음성 안내 메시지(speak)."""
    import liveguide
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    try:
        with _DETECT_LOCK:
            out = guard.detect(img, detectors=["person", "ppe", "forklift", "fire_smoke"])
        dets = out.get("detections", [])
    except Exception:  # noqa: BLE001
        dets = []
    return liveguide.build_guidance(dets, bool(payload.get("use_vlm")), image_bgr=img)


@app.get("/safety/ppe", response_class=HTMLResponse)
def safety_ppe_page():
    """현장 보호구 설정 — 현장별 필수 보호구 선택."""
    import ppe_check
    return ppe_check.render()


@app.get("/safety/ppe/live", response_class=HTMLResponse)
def safety_ppe_live_page():
    """실시간 보호구 감지 — 카메라 + 주기 점검(VLM)."""
    import ppe_check
    return ppe_check.render_live()


@app.get("/safety/ppe/catalog")
def safety_ppe_catalog():
    """보호구 카탈로그(id·라벨·방식) — 메인 화면 메뉴에서 선택용."""
    import ppe_check
    return {"catalog": [{"id": p["id"], "label": p["label"], "method": p["method"]}
                        for p in ppe_check.PPE_CATALOG],
            "rules": ppe_check.get_rules()}


@app.get("/safety/ppe/rules")
def safety_ppe_rules_get():
    import ppe_check
    return ppe_check.get_rules()


@app.post("/safety/ppe/rules")
def safety_ppe_rules_set(payload: dict = Body(...)):
    import ppe_check
    return ppe_check.save_rules(payload.get("required") or [], payload.get("site", ""))


@app.post("/safety/ppe/check")
def safety_ppe_check(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """이미지 → 현장 필수 보호구 착용 점검(미착용 경고). use_vlm 권장."""
    import ppe_check
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    try:
        with _DETECT_LOCK:
            out = guard.detect(img, detectors=["person", "ppe"])
        dets = out.get("detections", [])
    except Exception:  # noqa: BLE001
        dets = []
    return ppe_check.check(dets, image_bgr=img, required=payload.get("required"),
                           use_vlm=bool(payload.get("use_vlm", True)))


@app.post("/safety/sensor")
def safety_sensor(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """IoT 센서 값 수신 → 임계 초과 시 위험 기록 + 알림.
    카메라로 못 보는 영역(질식·가스·온열). 외부 센서가 주기적으로 값을 POST.
    payload: {type:'o2'|'co'|'h2s'|'gas'|'temp', value:float, site?, threshold?}
    """
    stype = str(payload.get("type") or "").lower()
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "value(숫자) 필요"}
    site = payload.get("site") or "현장"
    th = payload.get("threshold")
    spec = {
        "o2":   ("asphyxiation", lambda v: v < (th or 18.0) or v > 23.5, "산소농도 {v}% (안전 18~23.5%)"),
        "co":   ("gas_alarm",    lambda v: v >= (th or 30),  "일산화탄소(CO) {v}ppm"),
        "h2s":  ("asphyxiation", lambda v: v >= (th or 10),  "황화수소(H2S) {v}ppm"),
        "gas":  ("gas_alarm",    lambda v: v >= (th or 10),  "가연성가스 {v}%LEL"),
        "temp": ("heat_stress",  lambda v: v >= (th or 33),  "체감온도/WBGT {v}℃"),
    }
    if stype not in spec:
        return {"ok": False, "error": f"지원 센서: {', '.join(spec)}"}
    rule, danger_fn, msg_t = spec[stype]
    danger = bool(danger_fn(value))
    result = {"ok": True, "type": stype, "value": value, "danger": danger, "rule": rule}
    if danger:
        msg = msg_t.format(v=value) + " — 위험 임계 초과"
        try:
            data_engine.log_event(rule, level="critical", score=value, site=site, note=msg)
        except Exception:  # noqa: BLE001
            pass
        try:
            bundle = STATE.get(theme) or _load_theme(theme)
            disp = bundle["agents"].get("Dispatcher")
            if disp:
                r = disp.dispatch("critical", f"[{site}] {msg}", {"sensor": stype, "value": value})
                result["alert_sent"] = bool(r.get("sent")) if isinstance(r, dict) else None
        except Exception:  # noqa: BLE001
            pass
        result["message"] = msg
    return result


@app.post("/safety/behavior/analyze")
def safety_behavior_analyze(payload: dict = Body(...)):
    """VLM 행동분석 — 흡연·졸음·통화·폭력·절차위반 + 규칙행동 재확인. use_vlm 권장."""
    import behavior
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    return behavior.analyze(img, use_vlm=bool(payload.get("use_vlm", True)),
                            rule_hits=payload.get("rule_hits"))


@app.get("/safety/incident", response_class=HTMLResponse)
def safety_incident_page():
    """재해 원인분석(보조) — 사고 사진/영상 → 상황·빠진 조치·법령·유사재해·예방."""
    import incident
    return incident.render()


@app.post("/safety/incident/frame")
def safety_incident_frame(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """한 프레임의 위험도 채점(빠름, VLM 없음) — 영상 타임라인 분석용.
    반환: {score, person_count, hazards:[유형], detections:[클래스]}."""
    import proximity as _prox
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"score": 0, "hazards": []}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    try:
        with _DETECT_LOCK:
            out = guard.detect(img, detectors=["person", "ppe", "forklift", "fire_smoke"])
    except Exception:  # noqa: BLE001
        return {"score": 0, "hazards": []}
    sig = out.get("signals", {}) or {}
    pc = out.get("person_count", 0)
    prox = _prox.detect(out.get("detections", []), aspect_hw=img.shape[0] / img.shape[1])  # 감사 E-1
    hz = []
    score = pc * 5
    if prox:
        score += 55
        hz.append("작업반경 침입(협착)")
    if sig.get("fire_smoke"):
        score += 45
        hz.append("화재·연기")
    if sig.get("ppe_missing"):
        score += 25
        hz.append("보호구 미착용")
    return {"score": score, "person_count": pc, "hazards": hz,
            "detections": [d.get("label") for d in out.get("detections", [])],
            "boxes": _incident_boxes(out, prox)}


@app.post("/safety/incident/analyze")
def safety_incident_analyze(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """재해 영상/사진 원인분석 — 탐지 + VLM + 지식. 책임 비율 판정은 하지 않음."""
    import incident
    raw = payload.get("image_base64") or payload.get("image")
    if not raw:
        return {"ok": False, "error": "이미지 없음"}
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 디코딩 실패"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    present = []
    try:
        with _DETECT_LOCK:
            # 재해원인분석은 실시간이 아님 → 고해상도(1280)로 인식 정확도↑(느려도 됨).
            # ⚠ TTA(augment)는 약한 커스텀 모델(지게차·PPE)의 오탐을 증폭시켜 제거함(2026-07). 고해상도만 유지.
            out = guard.detect(img, detectors=["person", "ppe", "forklift", "fire_smoke"],
                               imgsz=1280, augment=False)
        present = [d.get("label") for d in out.get("detections", [])]
    except Exception:  # noqa: BLE001
        out, present = {"detections": []}, []
    result = incident.analyze(img, present_classes=present, use_vlm=bool(payload.get("use_vlm")))
    import proximity as _prox
    result["boxes"] = _incident_boxes(out, _prox.detect(
        out.get("detections", []), aspect_hw=img.shape[0] / img.shape[1]))   # 감사 E-1
    return result


@app.get("/safety/voice", response_class=HTMLResponse)
def safety_voice_page():
    """음성 안전 비서 — 근로자가 음성으로 묻고 스피커로 답을 듣는다."""
    import voice
    return voice.render()


@app.post("/safety/voice/ask")
def safety_voice_ask(payload: dict = Body(...)):
    """음성 질문(텍스트) → 안전 지식 엔진 답변(음성 읽기용·근거 포함)."""
    import safety_rag
    import safety_brain
    q = (payload.get("question") or "").strip()
    if not q:
        return {"ok": False, "answer": "질문을 다시 말씀해 주세요."}
    act = safety_brain.get_activity(q)
    if act:                                          # 작업이 매칭되면 필수조치 우선
        measures = [m["name"] for m in act.get("required_measures", [])]
        law = (act.get("regulations") or [{}])[0].get("law", "")
        answer = f"{act['name']}을 안전하게 하려면 {', '.join(measures)}를 확인하세요."
        if law:
            answer += f" 관련 법령은 {law}입니다."
        sources = [{"title": act["name"], "source": law}]
    else:                                            # 아니면 RAG 검색 결과
        hits = safety_rag.retrieve(q, k=2)
        if hits:
            answer = hits[0]["text"]
            sources = [{"title": h["title"], "source": h["source"]} for h in hits]
        else:
            answer = "관련 안전 정보를 찾지 못했습니다. 안전관리자에게 문의하세요."
            sources = []
    return {"ok": True, "question": q, "answer": answer, "sources": sources,
            "disclaimer": "보조 안내입니다. 최종 판단·조치는 안전관리자 확인 하에 이뤄집니다."}


@app.post("/safety/context")
def safety_context(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """완전 자동 — 환경 + 작업을 스스로 인식하고 안전조치 점검 + 위험 시 기록.
    payload={present?:[], image_base64?, use_vlm?, site?, log?}. 반환: 환경·작업·점검결과."""
    import safety_brain
    raw = payload.get("image_base64") or payload.get("image")
    img = None
    if raw:
        img = _img_from_b64(raw)
    ctx = safety_brain.assess_context(payload.get("present"), image_bgr=img,
                                      use_vlm=bool(payload.get("use_vlm")))
    res = ctx.get("assessment")
    ctx["logged"] = False
    if payload.get("log") and res and res.get("missing") and res.get("risk") in ("high", "mid"):
        data_engine.log_event(rule="safety_measure_missing",
                              level="high" if res["risk"] == "high" else "mid",
                              site=payload.get("site", "현장"), note=res["summary"],
                              image_data_url=(raw if raw and str(raw).startswith("data:")
                                              else ("data:image/jpeg;base64," + raw) if raw else None))
        ctx["logged"] = True
    img_url = (raw if raw and str(raw).startswith("data:")
               else ("data:image/jpeg;base64," + raw) if raw else None)
    if payload.get("log") and ctx.get("lone_worker"):     # 단독작업(2인1조 위반) 자율 기록
        data_engine.log_event(rule="lone_worker", level="high", site=payload.get("site", "현장"),
                              note="단독작업 감지 — 감시인 없는 고위험 작업(2인1조 필요)", image_data_url=img_url)
        ctx["logged"] = True
    return ctx


@app.post("/safety/brain/inspect")
def safety_brain_inspect(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """라이브 현장 점검 — 작업+감지객체(+이미지)로 추론 후, 위험 시 기록·알림(조치 연결).
    payload={activity, present?:[], image_base64?, use_vlm?, site?, log?:bool, alert?:bool}."""
    import safety_brain
    raw = payload.get("image_base64") or payload.get("image")
    img = None
    if raw:
        img = _img_from_b64(raw)
    activity = payload.get("activity", "")
    detected = None
    if activity == "auto":                          # 작업을 스스로 인식
        detected = safety_brain.detect_activity(img, payload.get("present"),
                                                use_vlm=bool(payload.get("use_vlm")))
        if not detected:
            return {"ok": True, "activity": None, "detected": None, "risk": "low",
                    "summary": "작업 미인식(대기) — 인식되면 자동 점검", "measures": [],
                    "missing": [], "unknown": [], "logged": False, "alerted": False}
        activity = detected
    res = safety_brain.assess(activity, payload.get("present"),
                              image_bgr=img, use_vlm=bool(payload.get("use_vlm")))
    if not res.get("ok"):
        return res
    res["detected"] = detected                      # 자동 인식된 작업(있으면)
    logged = alerted = False
    # 위험(부족조치 확인)일 때만 기록 → 자동처리 콘솔/대시보드로 흐름(헛알림 방지)
    if payload.get("log") and res["missing"] and res["risk"] in ("high", "mid"):
        data_engine.log_event(rule="safety_measure_missing",
                              level="high" if res["risk"] == "high" else "mid",
                              site=payload.get("site", "현장"), note=res["summary"],
                              image_data_url=(raw if raw and str(raw).startswith("data:")
                                              else ("data:image/jpeg;base64," + raw) if raw else None))
        logged = True
    if payload.get("alert") and res["risk"] == "high":
        bundle = STATE.get(theme) or _load_theme(theme)
        disp = bundle["agents"].get("Dispatcher")
        if disp:
            try:
                disp.dispatch("high", res["summary"])
                alerted = True
            except Exception:  # noqa: BLE001
                pass
    res["logged"], res["alerted"] = logged, alerted
    return res


@app.get("/safety/quote", response_class=HTMLResponse)
def safety_quote():
    """VIGENT 견적서(1장, 인쇄/PDF) — 현장명·카메라 수 입력 시 자동 계산."""
    import quote
    return quote.render()


@app.get("/safety/demo", response_class=HTMLResponse)
def safety_demo():
    """영업용 데모 — 카메라 없이 '감지→서류·조치 자동완성' 닫힌 루프 시연."""
    import demo as _demo
    return _demo.render()


@app.post("/safety/demo/seed")
def safety_demo_seed():
    """데모 이벤트 주입(증거·법령·평가서가 자동처리 콘솔에 채워짐)."""
    import demo as _demo
    return _demo.seed()


@app.post("/safety/demo/reset")
def safety_demo_reset():
    """데모 이벤트만 정리(실제 데이터 보존)."""
    import demo as _demo
    return _demo.reset()


@app.get("/safety-local", response_class=HTMLResponse)
def safety_local():
    """로컬 번들판 — CDN 없이 /static/vendor 에서 MediaPipe·TF 로드(폐쇄망·USB). CDN판(/safety)과 비교용."""
    p = _ROOT / "themes" / "safety" / "index_local.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="index_local.html 없음(생성 필요)")
    return FileResponse(p)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(theme: str = DEFAULT_THEME, style: str = "default"):
    """테마별 경영 대시보드 — 실제 이벤트 통계. style=terminal 이면 모던 터미널 스킨."""
    import dashboard as _dash
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    fn = _dash.render_terminal if style == "terminal" else _dash.render
    return fn(theme, scribe=scribe,
              tbm_count=len(tbm_store.list_recent(limit=100000)),
              audit_count=len(audit_store.list_recent(limit=100000)))


# ── 현장 운영 설정 콘솔(현장·카메라·워커·알림을 화면에서) ──
@app.get("/safety/setup", response_class=HTMLResponse)
def safety_setup():
    """현장 운영 설정 페이지 — site.yaml·notify.yaml 손편집 없이 화면에서 구성·운영."""
    import setup_console
    return setup_console.render()


@app.get("/site/config")
def site_config_get():
    import setup_console
    return setup_console.read_site()


@app.post("/site/config")
def site_config_post(payload: dict = Body(...)):
    import setup_console
    return setup_console.write_site(payload)


@app.get("/notify/config")
def notify_config_get():
    import setup_console
    return setup_console.read_notify_masked()


@app.post("/notify/config")
def notify_config_post(payload: dict = Body(...)):
    import setup_console
    return setup_console.write_notify(payload)


@app.post("/alerts/test")
def alerts_test(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """Dispatcher 경보 테스트. payload={level, message}. 키 없으면 폴백(로그)로 동작."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    return dispatcher.dispatch(payload.get("level", "high"),
                               payload.get("message", "VIGENT 경보 테스트"))


# ── go2rtc 자산·WS 중계(같은 출처 :8010 로 만들어 CORS 회피) ──
@app.get("/tapo/video-rtc.js")
def tapo_videortc_js():
    """go2rtc 의 video-rtc.js(ES모듈)를 VIGENT 서버가 대신 받아 같은 출처로 제공."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:1984/video-rtc.js", timeout=5) as r:
            return Response(r.read(), media_type="application/javascript")
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"go2rtc 미실행: {ex}")


@app.websocket("/tapo/ws")
async def tapo_ws(ws: WebSocket):
    """브라우저 ↔ go2rtc WebSocket(/api/ws?src=tapo) 양방향 중계(같은 출처)."""
    await ws.accept()
    import websockets
    try:
        async with websockets.connect("ws://localhost:1984/api/ws?src=tapo") as up:
            async def c2u():
                while True:
                    data = await ws.receive()
                    if data.get("type") == "websocket.disconnect":
                        break
                    if data.get("text") is not None:
                        await up.send(data["text"])
                    elif data.get("bytes") is not None:
                        await up.send(data["bytes"])

            async def u2c():
                async for msg in up:
                    if isinstance(msg, (bytes, bytearray)):
                        await ws.send_bytes(msg)
                    else:
                        await ws.send_text(msg)

            await asyncio.gather(c2u(), u2c())
    except Exception:  # noqa: BLE001  연결 종료/실패 시 조용히 닫음
        pass


# ── go2rtc WebRTC 신호 중계(같은 출처로 만들어 CORS 회피) ──
@app.post("/tapo/webrtc")
async def tapo_webrtc(request: Request):
    """브라우저 ↔ go2rtc WebRTC 핸드셰이크(SDP)를 VIGENT 서버가 중계.
    영상(미디어)은 WebRTC로 직접 흐르고, 여기선 SDP 신호만 전달 → CORS 문제 없음."""
    import urllib.request
    sdp = await request.body()
    req = urllib.request.Request("http://localhost:1984/api/webrtc?src=tapo",
                                 data=sdp, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return PlainTextResponse(r.read().decode())
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"go2rtc 연결 실패: {ex}")


# ── rf-detr permissive 백엔드(탐지·추적·위험구역·VLM) ──
@app.post("/rfdetr/frame")
def rfdetr_frame(payload: dict = Body(...)):
    """웹캠 프레임 → rf-detr 사람탐지 + 추적 + 위험구역 침입 판정(빠름)."""
    import rfdetr_service
    img = _decode_data_url(payload.get("image", ""))
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    return rfdetr_service.rfdetr.detect(img)


@app.post("/rfdetr/vlm")
def rfdetr_vlm(payload: dict = Body(...)):
    """이벤트 프레임 → mlx-vlm 위험요약 JSON(느림, 프론트가 침입 시 드물게 호출)."""
    import rfdetr_service
    img = _decode_data_url(payload.get("image", ""))
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    return rfdetr_service.vlm.summarize_bgr(img)


# ── AX 프론트(realtime_core.js) 호환 스텁 ──
# AX 엔진이 호출하는 보조 엔드포인트들. 핵심 인식은 브라우저(coco-ssd)에서 돌고,
# 아래는 '없으면 404 콘솔에러'만 막는 안전 스텁(빈 결과). 점진적으로 실제 구현 가능.
@app.post("/ppe/analyze-frame")
def stub_ppe_analyze(payload: dict = Body(default={})):
    return {"ok": True, "ppe": [], "note": "stub"}


@app.post("/segment/frame")
def stub_segment(payload: dict = Body(default={})):
    return {"ok": True, "segments": [], "note": "stub"}


@app.get("/zone/state")
@app.post("/zone/state")
def stub_zone_state(payload: dict = Body(default={})):
    return {"ok": True, "zones": [], "state": "idle"}


@app.post("/zone/intrusion")
def zone_intrusion_alert(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """위험구역 침입(몸통/머리/다리 등 '위험') → 휴대폰 알림(텔레그램/웹훅) + 증거 저장.
    프론트(AX 엔진)는 손/팔만이면 호출하지 않고, '위험' 부위 진입 시에만 호출한다."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    reasons = payload.get("reasons") or ["위험구역 접근"]
    people = payload.get("people", 0)
    zone_name = payload.get("zone", "위험구역")
    msg = f"[{zone_name}] 위험구역 침입 — {', '.join(reasons)} · 구역 내 {people}명"

    # 증거 저장 + 인식로그 기록(데이터엔진) → 자동처리 콘솔에 노출. decoded 는 VLM 확정에 재사용.
    img = payload.get("image_base64")
    img_url = (img if (img or "").startswith("data:") else "data:image/jpeg;base64," + img) if img else None
    decoded = _decode_data_url(img_url) if img_url else None
    rec = data_engine.log_event(rule="zone_intrusion", level="high",
                                site=zone_name, note=", ".join(reasons), image_data_url=img_url)
    saved = rec.get("evidence")

    # CNN→VLM 하이브리드 확정(opt-in: vlm_confirm). 고신뢰 오탐만 푸시 억제(증거·기록은 유지).
    vlm_conf, suppressed = None, False
    if payload.get("vlm_confirm"):
        import vlm_confirm as _vc
        vlm_conf = _vc.confirm(decoded, "zone_intrusion", reason=", ".join(reasons))
        if vlm_conf.get("available"):
            msg += f" · VLM 위험확률 {vlm_conf['risk']}% → {vlm_conf['verdict']}: {vlm_conf['reason']}"
        suppressed = bool(vlm_conf.get("suppress"))

    if suppressed:
        result = {"delivered": False, "suppressed": True, "fallback": False}
    elif dispatcher:
        result = dispatcher.dispatch("high", msg)
    else:
        result = {"delivered": False, "fallback": True}
    return {"ok": True, "message": msg, "vlm_confirm": vlm_conf, "suppressed": suppressed,
            "phone_sent": bool(result.get("delivered")),      # 텔레그램/웹훅 실제 발송 여부
            "fallback": result.get("fallback", True),         # 키 없으면 True(로그만)
            "evidence": saved}


@app.post("/safety/fall")
def safety_fall_alert(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """낙상 확정(브라우저 stats.fall 증가) → 3단계 통합 체인:
    Analyst 종합판단(+VLM 옵션) + Copilot 추락방지 법령 + Dispatcher 알림 + 증거 저장.
    키 없으면 Dispatcher 는 로그 폴백(기능 무중단)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    analyst = bundle["agents"].get("Analyst")
    copilot = bundle["agents"].get("Copilot")
    dispatcher = bundle["agents"].get("Dispatcher")

    signals = {"fall_temporal": True, "torso_angle": float(payload.get("torso_angle") or 0)}
    if analyst:
        verdict = analyst.integrate(signals, vlm=payload.get("vlm"), copilot=copilot)
    else:
        verdict = {"level": "high", "fired": [], "dispatch": []}

    # 증거 저장 + 인식로그 기록(데이터엔진) → 자동처리 콘솔에 노출. decoded 는 VLM 확정에 재사용.
    img = payload.get("image_base64")
    img_url = (img if (img or "").startswith("data:") else "data:image/jpeg;base64," + img) if img else None
    decoded = _decode_data_url(img_url) if img_url else None
    rec = data_engine.log_event(rule="fall_suspected", level=verdict.get("level", "high"),
                                site=payload.get("site", ""), note="낙상 감지", image_data_url=img_url)
    saved = rec.get("evidence")

    # 메시지에 법령 근거 한 줄(§9)
    laws = []
    for f in verdict.get("fired", []):
        for c in (f.get("citations") or [])[:1]:
            laws.append(f"{c['source']} {c['clause']}")
    msg = f"[낙상] 낙상 감지 — 등급 {verdict.get('level', 'high').upper()}"
    if laws:
        msg += " · 근거 " + "; ".join(dict.fromkeys(laws))

    # CNN→VLM 하이브리드 확정(opt-in: vlm_confirm). 고신뢰 오탐만 푸시 억제(증거·기록은 유지).
    vlm_conf, suppressed = None, False
    if payload.get("vlm_confirm"):
        import vlm_confirm as _vc
        vlm_conf = _vc.confirm(decoded, "fall_suspected",
                               reason=f"몸통각 {signals['torso_angle']:.0f}도")
        if vlm_conf.get("available"):
            msg += f" · VLM 위험확률 {vlm_conf['risk']}% → {vlm_conf['verdict']}: {vlm_conf['reason']}"
        suppressed = bool(vlm_conf.get("suppress"))

    if suppressed:
        result = {"delivered": False, "suppressed": True, "fallback": False}
    elif dispatcher:
        result = dispatcher.dispatch(verdict.get("level", "high"), msg)
    else:
        result = {"delivered": False, "fallback": True}
    return {"ok": True, "message": msg, "verdict": verdict, "vlm_confirm": vlm_conf,
            "suppressed": suppressed,
            "phone_sent": bool(result.get("delivered")),
            "fallback": result.get("fallback", True), "evidence": saved}


@app.post("/safety/posture")
def safety_posture_alert(payload: dict = Body(default={})):
    """근골격계 부담 자세 '지속' 감지 → 기록(자동처리 콘솔·위험성평가 반영).
    경보(텔레그램 푸시)는 보내지 않는다 — 근골격계는 누적 건강 이슈라 기록·평가 위주(알림 피로 방지).
    payload={image_base64?, note?, site?}."""
    img = payload.get("image_base64")
    img_url = (img if (img or "").startswith("data:") else "data:image/jpeg;base64," + img) if img else None
    rec = data_engine.log_event(rule="ergonomic_risk", level="low",
                                site=payload.get("site", ""),
                                note=payload.get("note", "근골격계 부담 자세"),
                                image_data_url=img_url)
    return {"ok": True, "message": "근골격계 부담 자세 기록", "rule": "ergonomic_risk",
            "evidence": rec.get("evidence")}


@app.post("/safety/confirm")
def safety_confirm(payload: dict = Body(...)):
    """CNN→VLM 하이브리드 확정(오탐 최소화) 단독 호출.
    payload={rule, image|image_base64, reason?}. VLM 미가용이면 available:false 폴백."""
    import vlm_confirm
    raw = payload.get("image") or payload.get("image_base64") or ""
    if raw and not raw.startswith("data:"):
        raw = "data:image/jpeg;base64," + raw
    return vlm_confirm.confirm(_decode_data_url(raw), payload.get("rule", ""),
                               reason=payload.get("reason", ""))


@app.post("/office/coach")
def office_coach(payload: dict = Body(default={})):
    """사무직 자세 코치(VLM) — office 프롬프트로 프레임 분석 + 근골격계 지침 보강.
    무거우므로 프론트가 쿨다운(기본 30초)으로 드물게 호출한다. 실패해도 죽지 않음."""
    import sys
    sys.path.insert(0, str(_HERE / "ml"))
    import rfdetr_service
    from vlm_risk_summary import prompt_for_theme
    raw_img = payload.get("image", "")
    if not raw_img:
        raise HTTPException(status_code=400, detail="image 필요")
    try:
        img = _decode_data_url(raw_img)
    except Exception:  # noqa: BLE001
        img = None
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    try:
        result = rfdetr_service.vlm.summarize_bgr(img, prompt=prompt_for_theme("office"))
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "error": f"VLM 실패: {type(ex).__name__}"}
    # 관련지침이 비었으면 Copilot 근골격계 지침으로 보강
    bundle = STATE.get("office") or _load_theme("office")
    copilot = bundle["agents"].get("Copilot")
    if copilot and not str(result.get("관련지침", "")).strip():
        text = f"{result.get('자세평가', '')} {result.get('위험부위', '')} {result.get('교정조언', '')}"
        m = copilot.cite_for_hazard(text)
        if m["matched"]:
            result["관련지침"] = m["관련법령"]
    return {"ok": True, "coach": result}


@app.post("/office/log")
def office_log(payload: dict = Body(default={})):
    """익명 자세 통계 1주기 저장(데이터 영속). 토큰은 브라우저 로컬 랜덤값(개인식별 아님)."""
    import office_data
    return office_data.log_posture(
        token=payload.get("token", "anon"),
        good_sec=payload.get("good_sec", 0), bad_sec=payload.get("bad_sec", 0),
        avg_score=payload.get("avg_score", 0), joints=payload.get("joints"))


@app.get("/office/trend")
def office_trend(token: str = "anon", days: int = 7):
    """익명 토큰의 자세 추세(일자별 평균점수·바른자세 비율)."""
    import office_data
    return office_data.trend(token, days)


@app.post("/office/webhook")
def office_webhook(payload: dict = Body(default={})):
    """Slack/Teams Incoming Webhook 으로 메시지 전송(서버 중계 — 브라우저 CORS 회피).
    웹훅 URL 은 .env 의 OFFICE_WEBHOOK_URL(비밀). 미설정이면 폴백(보내지 않음)."""
    import os
    url = os.environ.get("OFFICE_WEBHOOK_URL", "")
    if not url:
        # .env 직접 읽기(서버 환경변수에 없을 때)
        envf = _ROOT / ".env"
        if envf.exists():
            for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("OFFICE_WEBHOOK_URL"):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 필요")
    if not url:
        return {"ok": False, "fallback": True, "note": ".env 에 OFFICE_WEBHOOK_URL 없음(미발송)"}
    import json as _json
    import urllib.request
    # Slack/Teams 둘 다 {"text": ...} 호환
    body = _json.dumps({"text": text}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": True, "status": r.status}
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "error": f"웹훅 전송 실패: {type(ex).__name__}"}


@app.get("/office/report", response_class=HTMLResponse)
def office_report(days: int = 7):
    """관리자용 팀 단위 익명 자세 복지 리포트(개인 식별 없음)."""
    import office_data
    r = office_data.team_report(days)
    bars = ""
    mx = max([s["avg_score"] for s in r["series"]] + [1])
    for s in r["series"]:
        h = int(s["avg_score"] / mx * 90)
        col = "#2ecc71" if s["avg_score"] >= 80 else "#f1c40f" if s["avg_score"] >= 60 else "#e74c3c"
        bars += (f'<div style="flex:1;text-align:center"><div style="height:100px;display:flex;'
                 f'align-items:flex-end"><div style="width:100%;height:{h}px;background:{col};'
                 f'border-radius:4px 4px 0 0"></div></div>'
                 f'<div style="font-size:11px;color:#8aa0b8;margin-top:4px">{s["date"][5:]}<br>'
                 f'{s["avg_score"]}점<br>{s["participants"]}명</div></div>')
    html = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>VIGENT Office · 관리자 리포트</title><style>
body{{background:#0f1620;color:#e8eef5;font-family:-apple-system,"Apple SD Gothic Neo",sans-serif;margin:0;padding:24px}}
.card{{background:#172230;border:1px solid #26384d;border-radius:14px;padding:20px;max-width:880px;margin:0 auto 16px}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap}} .k{{flex:1;min-width:120px;background:#10202f;border-radius:10px;padding:14px;text-align:center}}
.k b{{font-size:28px}} .k span{{font-size:12px;color:#8aa0b8}} h1{{font-size:20px}} .mut{{color:#8aa0b8;font-size:13px}}
</style></head><body>
<div class="card"><h1>VIGENT <span style="color:#4aa3ff">Office</span> · 관리자 리포트</h1>
<p class="mut">최근 {r['days']}일 · 팀 단위 <b>익명 집계</b>(개인 식별 정보 없음) · 자세 교정 복지 프로그램</p>
<div class="kpi">
  <div class="k"><b>{r['participants']}</b><br><span>익명 참여(명)</span></div>
  <div class="k"><b style="color:#4aa3ff">{r['team_avg_score']}</b><br><span>팀 평균 점수</span></div>
  <div class="k"><b style="color:#2ecc71">{r['team_good_ratio']}%</b><br><span>바른자세 비율</span></div>
  <div class="k"><b>{r['good_hours']}h</b><br><span>바른자세 누적</span></div>
  <div class="k"><b style="color:#e74c3c">{r['bad_hours']}h</b><br><span>나쁜자세 누적</span></div>
</div></div>
<div class="card"><h1 style="font-size:15px">일자별 팀 평균 점수</h1>
<div style="display:flex;gap:8px;align-items:flex-end">{bars or '<p class="mut">아직 데이터가 없습니다. office 사용 후 표시됩니다.</p>'}</div></div>
<div class="card mut">※ 본 리포트는 개인을 식별하지 않는 익명 집계입니다. 근로기준법·개인정보보호법상 근로자 동의·노사협의 절차를 준수하여 운영하세요.</div>
</body></html>"""
    return html


@app.post("/vitals/rppg")
def stub_vitals(payload: dict = Body(default={})):
    return {"ok": True, "bpm": None, "note": "stub"}


@app.post("/recognition/note")
def stub_recognition_note(payload: dict = Body(default={})):
    return {"ok": True}


@app.get("/alerts/status")
def stub_alerts_status():
    return {"ok": True, "alerts": []}


@app.get("/safety-pro", response_class=HTMLResponse)
def safety_pro():
    """rf-detr permissive 백엔드를 쓰는 VIGENT 콘솔 화면(탐지·위험구역·VLM)."""
    p = _ROOT / "themes" / "safety" / "index_rfdetr.html"
    return p.read_text(encoding="utf-8")


@app.get("/sports/asanas")
def sports_asanas():
    """요가 동작 라이브러리(Yoga-82 수준). 정답각도(scored)·카테고리 포함."""
    p = _ROOT / "config" / "yoga_asanas.json"
    if not p.exists():
        return {"asanas": []}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/sports/templates")
def sports_templates():
    """학습된 요가 동작 인식 템플릿(브라우저가 등록 없이 자동 인식). 없으면 빈값."""
    p = _ROOT / "config" / "yoga_templates.json"
    if not p.exists():
        return {"templates": {}}
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/sports/calibrate")
def sports_calibrate(payload: dict = Body(default={})):
    """정답 자세 보정 — 시연으로 측정한 각도(중앙값·허용오차)로 해당 동작 정답각도 갱신.
    payload={asana_id, angles:[{name, ideal, tol, n}]}. 데이터 기반 표시(user_calibrated)."""
    aid = payload.get("asana_id")
    measured = {m.get("name"): m for m in (payload.get("angles") or [])}
    if not aid or not measured:
        raise HTTPException(status_code=400, detail="asana_id·angles 필요")
    p = _ROOT / "config" / "yoga_asanas.json"
    lib = json.loads(p.read_text(encoding="utf-8"))
    updated = 0
    for a in lib["asanas"]:
        if a.get("id") != aid:
            continue
        for ang in a.get("angles", []):
            m = measured.get(ang["name"])
            if m and m.get("n", 0) >= 10:
                ang["ideal"] = round(float(m["ideal"]))
                ang["tol"] = max(8, round(float(m["tol"])))
                ang["data_based"] = True
                ang["user_calibrated"] = True
                ang["n"] = int(m["n"])
                updated += 1
        a["scored"] = len(a.get("angles", [])) > 0
    if updated:
        p.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    # B: 정답 자세 키포인트(목표 자세 시연용)도 저장 — reference=[{x,y,z}, ...12점]
    ref = payload.get("reference")
    if isinstance(ref, list) and len(ref) >= 12:
        rp = _ROOT / "config" / "yoga_reference.json"
        refs = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        refs[aid] = ref[:12]
        rp.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "updated": updated, "asana": aid, "reference_saved": bool(ref)}


@app.get("/sports/reference")
def sports_reference():
    """보정으로 저장된 정답 자세 키포인트(목표 자세 시연용). 없으면 빈값."""
    p = _ROOT / "config" / "yoga_reference.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/sports/session")
def sports_session(payload: dict = Body(default={})):
    """연습 1건(동작·점수·유지시간) 익명 기록. 토큰은 브라우저 로컬 랜덤값."""
    import sports_data
    return sports_data.log_session(
        token=payload.get("token", "anon"), asana=payload.get("asana", ""),
        score=payload.get("score", 0), hold_sec=payload.get("hold_sec", 0))


@app.get("/sports/progress")
def sports_progress(token: str = "anon", days: int = 30):
    """익명 토큰의 연습 진행도(추세·연속일·동작별 최고점)."""
    import sports_data
    return sports_data.progress(token, days)


@app.get("/theme/{theme}/raw")
def theme_raw(theme: str):
    """테마 vision.yaml 원본 반환(프론트가 ergonomics 등 설정을 읽어 설정주도 동작)."""
    from vision_loader import load_vision
    try:
        return load_vision(theme).raw
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"테마 없음: {theme}")


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

# 증거 프레임 이미지 서빙(데이터엔진 저장본). 폴더는 첫 이벤트 때 생성됨.
_EVIDENCE_DIR = _ROOT / "data" / "evidence"
_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=str(_EVIDENCE_DIR)), name="evidence")
