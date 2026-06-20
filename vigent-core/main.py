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

from fastapi import Body, FastAPI, HTTPException, Response
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
import data_engine                       # noqa: E402
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


@app.post("/detect/frame")
def detect_frame(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """Guard 딥러닝 정밀 탐지. payload={image: data URL, detectors?:[...], conf?:float}.
    반환: 정규화 bbox·라벨·confidence 목록 + 파생 신호(ppe_missing 등).
    모델 없으면 해당 검출기만 비활성(무중단)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    img = _decode_data_url(payload.get("image", ""))
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    return guard.detect(img, detectors=payload.get("detectors"), conf=payload.get("conf"))


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
def report_safety(theme: str = DEFAULT_THEME, hours: float = 24):
    """최근 N시간 누적 이벤트(데이터엔진 집계) 기반 위험성평가서 HTML(인쇄→PDF).
    누적 이벤트가 없으면 데모 샘플로 렌더(빈 화면 방지)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    events = data_engine.aggregate(hours=hours)
    site = f"최근 {int(hours)}시간 누적"
    if not events:                              # 아직 쌓인 이벤트 없음 → 데모
        events = [{"rule": "zone_intrusion", "count": 5}, {"rule": "ppe_missing", "count": 9},
                  {"rule": "fall_suspected", "count": 1}]
        site = "데모 현장(누적 이벤트 없음)"
    return scribe.generate(events, site=site, process="-", save=False)["html"]


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
  body{{font-family:"Apple SD Gothic Neo",sans-serif;margin:32px;color:#0f172a}}
  h1{{font-size:20px}} a{{color:#2563eb}}
  table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
  th,td{{border:1px solid #cbd5e1;padding:8px 10px;text-align:left}} th{{background:#f1f5f9}}
  .btn{{display:inline-block;margin-top:16px;padding:10px 18px;background:#0f172a;color:#fff;
        border-radius:8px;text-decoration:none}}
</style></head><body>
  <h1>📁 위험성평가서 목록</h1>
  <div style="color:#64748b;font-size:13px">저장 위치: data/risk_assessments/ · 최신순</div>
  <table><thead><tr><th>생성일시</th><th>현장</th><th>총항목</th><th>높음(상)</th><th>열기</th></tr></thead>
  <tbody>{rows}</tbody></table>
  <a class="btn" href="/report/safety" target="_blank">＋ 지금 평가서 생성(누적 이벤트 기반)</a>
</body></html>"""


@app.post("/alerts/test")
def alerts_test(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """Dispatcher 경보 테스트. payload={level, message}. 키 없으면 폴백(로그)로 동작."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    return dispatcher.dispatch(payload.get("level", "high"),
                               payload.get("message", "VIGENT 경보 테스트"))


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

    # 증거 이미지 저장(있으면)
    saved = None
    img = payload.get("image_base64")
    if img:
        try:
            decoded = _decode_data_url(img if img.startswith("data:") else "data:image/jpeg;base64," + img)
            if decoded is not None:
                import cv2
                from datetime import datetime
                d = _ROOT / "data" / "evidence" / datetime.now().strftime("%Y%m%d")
                d.mkdir(parents=True, exist_ok=True)
                fn = d / f"intrusion_{datetime.now().strftime('%H%M%S')}.jpg"
                cv2.imwrite(str(fn), decoded)
                saved = str(fn.relative_to(_ROOT))
        except Exception:  # noqa: BLE001
            pass

    result = dispatcher.dispatch("high", msg) if dispatcher else {"delivered": False, "fallback": True}
    return {"ok": True, "message": msg,
            "phone_sent": bool(result.get("delivered")),      # 텔레그램/웹훅 실제 발송 여부
            "fallback": result.get("fallback", True),         # 키 없으면 True(로그만)
            "evidence": saved}


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
