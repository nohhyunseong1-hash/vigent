"""routers/office.py — 오피스(근골격 코칭·로그·리포트·웹훅) 라우트 (P1-7 분할). main 미import."""
from pathlib import Path

from app_state import STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import HTMLResponse
from web_util import _ROOT, _decode_data_url, _webhook_allowed

_HERE = Path(__file__).resolve().parent.parent   # vigent-core/ (main._HERE 와 동일)

router = APIRouter()


@router.post("/office/coach")
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

@router.post("/office/log")
def office_log(payload: dict = Body(default={})):
    """익명 자세 통계 1주기 저장(데이터 영속). 토큰은 브라우저 로컬 랜덤값(개인식별 아님)."""
    import office_data
    return office_data.log_posture(
        token=payload.get("token", "anon"),
        good_sec=payload.get("good_sec", 0), bad_sec=payload.get("bad_sec", 0),
        avg_score=payload.get("avg_score", 0), joints=payload.get("joints"))

@router.get("/office/trend")
def office_trend(token: str = "anon", days: int = 7):
    """익명 토큰의 자세 추세(일자별 평균점수·바른자세 비율)."""
    import office_data
    return office_data.trend(token, days)

@router.post("/office/webhook")
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
    if not _webhook_allowed(url):   # C-S0 목적지 화이트리스트
        raise HTTPException(status_code=403,
                            detail="웹훅 목적지 미허용 — config/security.json allowed_webhook_hosts 에 호스트 등록 필요")
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

@router.get("/office/report", response_class=HTMLResponse)
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
