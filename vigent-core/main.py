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
import data_engine                       # noqa: E402
import tbm_store                          # noqa: E402
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


# ─────────────────────────────────────────────────────────────
# 작업 전 TBM(안전점검 회의) — 작성·저장·열기 (한전 스마트TBM '작업 전' 단계)
# ─────────────────────────────────────────────────────────────
_TBM_CSS = """
  body{font-family:"Apple SD Gothic Neo",sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
  .wrap{max-width:760px;margin:0 auto;padding:28px 20px 80px}
  h1{font-size:21px;margin:4px 0 2px} .sub{color:#94a3b8;font-size:13px;margin-bottom:20px}
  a{color:#60a5fa;text-decoration:none}
  .card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;margin-bottom:14px}
  .card h2{font-size:15px;margin:0 0 12px;color:#93c5fd}
  label.fld{display:block;font-size:13px;color:#cbd5e1;margin:10px 0 4px}
  input[type=text],textarea{width:100%;box-sizing:border-box;background:#0f172a;border:1px solid #334155;
    border-radius:8px;color:#e2e8f0;padding:9px 11px;font-size:14px;font-family:inherit}
  textarea{min-height:64px;resize:vertical}
  .row{display:flex;gap:8px} .row input{flex:1}
  .chk{display:flex;align-items:center;gap:8px;font-size:13.5px;padding:7px 0;border-bottom:1px solid #29374a}
  .chk:last-child{border-bottom:none}
  .chk input{width:17px;height:17px;accent-color:#22c55e}
  .tag{display:inline-flex;align-items:center;gap:6px;background:#0b2545;border:1px solid #1d4ed8;
    color:#bfdbfe;border-radius:999px;padding:5px 10px;font-size:13px;margin:4px 6px 0 0}
  .tag b{cursor:pointer;color:#93c5fd}
  .wk{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #29374a}
  .wk .nm{flex:1} .wk small{color:#94a3b8}
  .btn{display:inline-block;padding:10px 16px;border-radius:8px;border:1px solid #334155;
    background:#0f172a;color:#e2e8f0;font-size:14px;cursor:pointer}
  .btn.add{padding:9px 14px}
  .btn.primary{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:700}
  .bar{position:fixed;left:0;right:0;bottom:0;background:#0b1220;border-top:1px solid #334155;
    padding:14px 20px;display:flex;justify-content:center;gap:10px}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th,td{border:1px solid #334155;padding:8px 10px;text-align:left} th{background:#162133;color:#93c5fd}
"""

# 작성 화면(plain 문자열 — JS 중괄호 보존). /*CSS*/ 와 <!--CHECKLIST--> 만 치환된다.
_TBM_NEW_HTML = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 새 TBM 회의록</title><style>/*CSS*/</style></head><body><div class="wrap">
  <h1>📋 새 TBM 회의록 작성</h1>
  <div class="sub">작업 전 안전점검 회의(툴박스미팅) · 작성 후 저장하면 인쇄/PDF 가능</div>

  <div class="card"><h2>작업 정보</h2>
    <label class="fld">현장</label><input id="site" type="text" placeholder="예: ○○변전소 22.9kV 개폐기 교체 현장">
    <label class="fld">작업공종</label><input id="process" type="text" placeholder="예: 활선작업 / 고소작업 / 굴착작업">
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
    page = _TBM_NEW_HTML.replace("/*CSS*/", _TBM_CSS).replace("<!--CHECKLIST-->", checklist_html)
    return page


@app.post("/safety/tbm")
def tbm_create(payload: dict = Body(...)):
    """회의록 1건 저장. payload={site,process,work_desc,supervisor,hazards[],checklist[],workers[],notes}."""
    rec = tbm_store.create(payload)
    return {"id": rec["id"], "saved_path": rec["saved_path"]}


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
    <button class="btn primary" onclick="window.print()">🖨 인쇄 / PDF 저장</button>
  </div>
</div></body></html>"""


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
                fn = d / f"fall_{datetime.now().strftime('%H%M%S')}.jpg"
                cv2.imwrite(str(fn), decoded)
                saved = str(fn.relative_to(_ROOT))
        except Exception:  # noqa: BLE001
            pass

    # 메시지에 법령 근거 한 줄(§9)
    laws = []
    for f in verdict.get("fired", []):
        for c in (f.get("citations") or [])[:1]:
            laws.append(f"{c['source']} {c['clause']}")
    msg = f"[낙상] 낙상 감지 — 등급 {verdict.get('level', 'high').upper()}"
    if laws:
        msg += " · 근거 " + "; ".join(dict.fromkeys(laws))

    result = dispatcher.dispatch(verdict.get("level", "high"), msg) if dispatcher \
        else {"delivered": False, "fallback": True}
    return {"ok": True, "message": msg, "verdict": verdict,
            "phone_sent": bool(result.get("delivered")),
            "fallback": result.get("fallback", True), "evidence": saved}


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
