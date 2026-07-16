"""routers/tbm.py — 작업 전 안전점검회의(TBM) (P1-7 분할). main 미import.

/safety/tbm(목록·작성·생성·제안·위험성평가 전환·열람). 공유 CSS 는 web_util._TBM_CSS.
"""
from pathlib import Path

import tbm_store
from app_state import DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse
from web_util import _TBM_CSS, _tpl

router = APIRouter()


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


@router.get("/safety/tbm", response_class=HTMLResponse)
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

@router.get("/safety/tbm/new", response_class=HTMLResponse)
def tbm_new():
    """TBM 회의록 작성 화면(작성 후 저장 → 열기로 이동)."""
    checklist_html = "".join(
        '<label class="chk"><input type="checkbox" checked data-item="ITEM"><span>ITEM</span></label>'
        .replace("ITEM", item) for item in tbm_store.DEFAULT_CHECKLIST)
    process_html = "".join(f'<option value="{j["name"]}">' for j in tbm_store.jsa_catalog())
    page = (_tpl("tbm_new.html").replace("/*CSS*/", _TBM_CSS)
            .replace("<!--CHECKLIST-->", checklist_html)
            .replace("<!--PROCESSLIST-->", process_html))
    return page

@router.post("/safety/tbm")
def tbm_create(payload: dict = Body(...)):
    """회의록 1건 저장. payload={site,process,work_desc,supervisor,hazards[],checklist[],workers[],notes}."""
    rec = tbm_store.create(payload)
    return {"id": rec["id"], "saved_path": rec["saved_path"]}

@router.get("/safety/tbm/suggest")
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

@router.post("/safety/tbm/{tid}/risk-assessment")
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

@router.get("/safety/tbm/{tid}", response_class=HTMLResponse)
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
