"""routers/safety_core.py — safety 도메인 나머지 전부 (P1-7 분할 마지막). main 미import.

홈·리포트·워커·브레인·이벤트·자동처리·음성·데모·설정·테마페이지 등 safety 핵심 라우트.
※ `/` 루트는 app.version(FastAPI 인스턴스)을 참조하므로 순환 방지 위해 main.py 에 잔류.
"""
import time as _time
from pathlib import Path

import audit_store
import data_engine
import tbm_store
from app_state import _START_TS, DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from web_util import (
    _ROOT,
    _TBM_CSS,
    _decode_data_url,
    _evidence_url,
    _img_from_b64,
    _incident_boxes,
    _tpl,
)

router = APIRouter()


class RiskAssessmentIn(BaseModel):
    """위험성평가 POST 입력(하위호환·관대):
    events 는 반드시 list[dict](각 이벤트는 dict) — 문자열/누락/비-dict 항목이면 422.
    site/process 는 선택. events 항목의 키(rule/count/levels/notes 등)는 자유(추가검증 없음)."""
    events: list[dict]
    site: str | None = ""
    process: str | None = ""
    mode: str | None = "checklist"   # 'checklist'(기본·현장 실무형) | 'quantitative'(빈도×강도 3×3 보존)


_ADVISORY = {
    "fall_suspected": "작업자 상태 즉시 확인 · 추락방지(안전대·안전난간·작업발판) 점검 · 필요시 작업 일시중지 검토",
    "ppe_missing": "보호구 착용 지도 · 미착용자 작업 제한 검토 · 보호구 비치 상태 확인",
    "zone_intrusion": "출입통제 상태 확인 · 작업자 위험구역 이탈 안내 · 경고표지 점검",
    "guard_bypass": "위험기계 정지상태 확인(1차 책임=인증 방호장치) · 작업자 신체 이탈 · 방호장치 점검",
    "fire_smoke": "초기대응·대피 절차 확인 · 소화설비 점검 · 화기작업 허가 여부 확인",
    "trip_hazard": "통로·바닥 정리정돈 · 전선·자재 제거 · 미끄럼 방지 조치",
    "ergonomic_risk": "작업자세 개선 안내 · 중량물 보조기구 · 주기적 휴식 권고",
}


@router.get("/home", response_class=HTMLResponse)
@router.get("/hub", response_class=HTMLResponse)
def hub_home():
    """VIGENT 홈(허브) — 가장 좋은 기능들을 타일로 한눈에."""
    import hub
    return hub.render()

@router.get("/favicon.ico")
def favicon():
    """브라우저 자동요청 favicon — 없어서 나던 404 콘솔 노이즈 제거(내용은 비움)."""
    return Response(status_code=204)

@router.post("/safety/judge")
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

@router.post("/safety/manager/decide")
def safety_manager_decide(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """SafetyManager 반자동 — event 로 등급 판정 → '권장 행동'만 반환(무엇도 자동 실행 안 함)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    mgr = bundle["agents"].get("SafetyManager")
    if mgr is None:
        raise HTTPException(status_code=503, detail="SafetyManager 미로드")
    return mgr.decide(payload or {})

@router.post("/safety/manager/ask")
def safety_manager_ask(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """SafetyManager 질의응답 — 로컬 지식 우선, 근거 없으면 '확인 필요'."""
    bundle = STATE.get(theme) or _load_theme(theme)
    mgr = bundle["agents"].get("SafetyManager")
    if mgr is None:
        raise HTTPException(status_code=503, detail="SafetyManager 미로드")
    return mgr.ask((payload or {}).get("question", ""))

@router.get("/evidence/search")
def evidence_search(rule: str, theme: str = DEFAULT_THEME):
    """Copilot 근거 검색 — 규칙 id 의 법령·가이드 인용(출처 포함)을 반환(§9)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    copilot = bundle["agents"].get("Copilot")
    return copilot.cite(rule)

@router.post("/safety/risk-assessment")
def safety_risk_assessment(body: RiskAssessmentIn, theme: str = DEFAULT_THEME,
                           narrative: bool = False):
    """Scribe 위험성평가서 생성. body={events:[{rule,count}], site, process}.
    근거 인용 자동 삽입 + data/risk_assessments/ 저장. 반환은 평가표 JSON(+저장경로).
    잘못된 events(문자열·누락·비-dict 항목)는 422. narrative=true 일 때만 종합의견을 LLM 으로(느림)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    out = scribe.generate(body.events or [],
                          site=body.site or "", process=body.process or "",
                          use_llm=narrative, mode=(body.mode or "checklist"))
    return {"assessment": out["assessment"], "saved_path": out["saved_path"],
            "saved": out.get("saved", out["saved_path"] is not None),
            "dropped_rules": out.get("dropped_rules", [])}

@router.post("/safety/live/analyze")
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

@router.get("/report/safety", response_class=HTMLResponse)
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

@router.get("/safety/risk-assessment/list")
def risk_assessment_list(theme: str = DEFAULT_THEME):
    """저장된 위험성평가서 목록(최신순)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    return {"items": bundle["agents"]["Scribe"].list_saved()}

@router.get("/safety/risk-assessment/{aid}", response_class=HTMLResponse)
def risk_assessment_open(aid: str, theme: str = DEFAULT_THEME):
    """저장된 위험성평가서 다시열기(HTML)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    page = bundle["agents"]["Scribe"].load_html(aid)
    if page is None:
        raise HTTPException(status_code=404, detail="평가서 없음")
    return page

@router.get("/safety/reports", response_class=HTMLResponse)
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

@router.get("/safety/auto/feed")
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

@router.post("/safety/auto/approve")
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

@router.get("/safety/auto/audit", response_class=HTMLResponse)
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

@router.get("/safety/auto", response_class=HTMLResponse)
def safety_auto_console():
    """안전 자동처리 콘솔(읽기 + 승인). 비전이 잡은 위험 → 서류·조치 자동 정리."""
    return _tpl("auto.html").replace("/*CSS*/", _TBM_CSS)

@router.post("/worker/start")
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

@router.post("/worker/stop")
def worker_stop(payload: dict = Body(default={})):
    """워커 중지. payload={id} 면 그 카메라만, 없으면 전체."""
    import worker as _w
    cid = payload.get("id")
    return _w.manager.stop(cid) if cid else _w.manager.stop_all()

@router.get("/status")
@router.get("/worker/status")
@router.get("/workers")
def worker_status():
    """워커 단위 세부 상태(2단계) — 카메라별 running·last_frame_secs_ago·hang·frames·fps·restarts·reconnects·error.
    /health(프로세스 생존)와 분리. 워치독의 2차 감시(hang 판정)와 대시보드가 이 엔드포인트를 쓴다."""
    import worker as _w
    st = _w.manager.status()
    cams = st.get("cameras", {})
    st["worker_count"] = len(cams)
    st["any_hang"] = any(c.get("hang") for c in cams.values())      # 하나라도 hang → 워치독 2차 트리거 근거
    st["running_count"] = sum(1 for c in cams.values() if c.get("running"))
    st["uptime_s"] = round(_time.time() - _START_TS, 1)
    return st

@router.post("/workers/start-all")
def workers_start_all(theme: str = DEFAULT_THEME):
    """config/site.yaml 의 모든 카메라로 워커 일괄 시작(헤드리스/USB 부팅용)."""
    import worker as _w
    bundle = STATE.get(theme) or _load_theme(theme)
    return _w.manager.autostart(bundle["agents"].get("Guard"), _DETECT_LOCK)

@router.post("/workers/stop-all")
def workers_stop_all():
    """모든 워커 중지."""
    import worker as _w
    return _w.manager.stop_all()

@router.get("/safety/brain", response_class=HTMLResponse)
def safety_brain_page():
    """안전 지식 추론 엔진 UI — 작업별 필수조치/법령/조치 + VLM '없는 조치' 추론."""
    import safety_brain
    return safety_brain.render()

@router.get("/safety/brain/activities")
def safety_brain_activities():
    import safety_brain
    return {"activities": safety_brain.list_activities()}

@router.get("/safety/brain/search")
def safety_brain_search(q: str, k: int = 5):
    """안전 지식 RAG 검색 — 법령·KOSHA 가이드·작업지식에서 관련 스니펫 top-k."""
    import safety_rag
    return {"query": q, "results": safety_rag.retrieve(q, k=k)}

@router.post("/safety/brain/assess")
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

@router.get("/safety/eval", response_class=HTMLResponse)
def safety_eval_page():
    """정확도 측정 도구 — 위험/정상 사진으로 재현율·정밀도 자체 측정."""
    import evaluator
    return evaluator.render()

@router.post("/safety/eval/run")
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

@router.get("/safety/guide", response_class=HTMLResponse)
def safety_guide_page():
    """현장 음성 안전 안내 — 카메라 화면을 분석해 위험·작업을 음성으로."""
    import liveguide
    return liveguide.render()

@router.post("/safety/voice/scene")
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
            # forklift 제외(F-7) — 유령 지게차 음성경보는 없는 위험을 소리로 알림 → 반복되면 경보 피로로
            #   진짜 경보까지 무시하게 됨(화면 오탐보다 나쁜 실패). 측정은 payload.detectors 명시로 가능.
            out = guard.detect(img, detectors=payload.get("detectors") or ["person", "ppe", "fire_smoke"])
        dets = out.get("detections", [])
    except Exception:  # noqa: BLE001
        dets = []
    return liveguide.build_guidance(dets, bool(payload.get("use_vlm")), image_bgr=img)

@router.post("/safety/sensor")
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

@router.post("/safety/behavior/analyze")
def safety_behavior_analyze(payload: dict = Body(...)):
    """VLM 행동분석 — 흡연·졸음·통화·폭력·절차위반 + 규칙행동 재확인. use_vlm 권장."""
    import behavior
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    return behavior.analyze(img, use_vlm=bool(payload.get("use_vlm", True)),
                            rule_hits=payload.get("rule_hits"))

@router.get("/safety/voice", response_class=HTMLResponse)
def safety_voice_page():
    """음성 안전 비서 — 근로자가 음성으로 묻고 스피커로 답을 듣는다."""
    import voice
    return voice.render()

@router.post("/safety/voice/ask")
def safety_voice_ask(payload: dict = Body(...)):
    """음성 질문(텍스트) → 안전 지식 엔진 답변(음성 읽기용·근거 포함)."""
    import safety_brain
    import safety_rag
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

@router.post("/safety/context")
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

@router.post("/safety/brain/inspect")
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

@router.get("/safety/quote", response_class=HTMLResponse)
def safety_quote():
    """VIGENT 견적서(1장, 인쇄/PDF) — 현장명·카메라 수 입력 시 자동 계산."""
    import quote
    return quote.render()

@router.get("/safety/demo", response_class=HTMLResponse)
def safety_demo():
    """영업용 데모 — 카메라 없이 '감지→서류·조치 자동완성' 닫힌 루프 시연."""
    import demo as _demo
    return _demo.render()

@router.post("/safety/demo/seed")
def safety_demo_seed():
    """데모 이벤트 주입(증거·법령·평가서가 자동처리 콘솔에 채워짐)."""
    import demo as _demo
    return _demo.seed()

@router.post("/safety/demo/reset")
def safety_demo_reset():
    """데모 이벤트만 정리(실제 데이터 보존)."""
    import demo as _demo
    return _demo.reset()

@router.get("/safety-local", response_class=HTMLResponse)
def safety_local():
    """로컬 번들판 — CDN 없이 /static/vendor 에서 MediaPipe·TF 로드(폐쇄망·USB). CDN판(/safety)과 비교용."""
    p = _ROOT / "themes" / "safety" / "index_local.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="index_local.html 없음(생성 필요)")
    return FileResponse(p)

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(theme: str = DEFAULT_THEME, style: str = "default"):
    """테마별 경영 대시보드 — 실제 이벤트 통계. style=terminal 이면 모던 터미널 스킨."""
    import dashboard as _dash
    bundle = STATE.get(theme) or _load_theme(theme)
    scribe = bundle["agents"].get("Scribe")
    fn = _dash.render_terminal if style == "terminal" else _dash.render
    return fn(theme, scribe=scribe,
              tbm_count=len(tbm_store.list_recent(limit=100000)),
              audit_count=len(audit_store.list_recent(limit=100000)))

@router.get("/safety/setup", response_class=HTMLResponse)
def safety_setup():
    """현장 운영 설정 페이지 — site.yaml·notify.yaml 손편집 없이 화면에서 구성·운영."""
    import setup_console
    return setup_console.render()

@router.get("/site/config")
def site_config_get():
    import setup_console
    return setup_console.read_site()

@router.post("/site/config")
def site_config_post(payload: dict = Body(...)):
    import setup_console
    return setup_console.write_site(payload)

@router.get("/notify/config")
def notify_config_get():
    import setup_console
    return setup_console.read_notify_masked()

@router.post("/notify/config")
def notify_config_post(payload: dict = Body(...)):
    import setup_console
    return setup_console.write_notify(payload)

@router.post("/alerts/test")
def alerts_test(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """Dispatcher 경보 테스트. payload={level, message}. 키 없으면 폴백(로그)로 동작."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    return dispatcher.dispatch(payload.get("level", "high"),
                               payload.get("message", "VIGENT 경보 테스트"))

@router.post("/safety/fall")
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

@router.post("/safety/posture")
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

@router.post("/safety/confirm")
def safety_confirm(payload: dict = Body(...)):
    """CNN→VLM 하이브리드 확정(오탐 최소화) 단독 호출.
    payload={rule, image|image_base64, reason?}. VLM 미가용이면 available:false 폴백."""
    import vlm_confirm
    raw = payload.get("image") or payload.get("image_base64") or ""
    if raw and not raw.startswith("data:"):
        raw = "data:image/jpeg;base64," + raw
    return vlm_confirm.confirm(_decode_data_url(raw), payload.get("rule", ""),
                               reason=payload.get("reason", ""))

@router.get("/alerts/status")
def stub_alerts_status():
    return {"ok": True, "alerts": []}

@router.get("/safety-pro", response_class=HTMLResponse)
def safety_pro():
    """rf-detr permissive 백엔드를 쓰는 VIGENT 콘솔 화면(탐지·위험구역·VLM)."""
    p = _ROOT / "themes" / "safety" / "index_rfdetr.html"
    return p.read_text(encoding="utf-8")

@router.get("/theme/{theme}/raw")
def theme_raw(theme: str):
    """테마 vision.yaml 원본 반환(프론트가 ergonomics 등 설정을 읽어 설정주도 동작)."""
    from vision_loader import load_vision
    try:
        return load_vision(theme).raw
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"테마 없음: {theme}")

@router.get("/{theme}")
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
