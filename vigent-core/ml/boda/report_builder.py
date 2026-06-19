"""안전관리 증빙 리포트 생성 (중대재해처벌법/산업안전보건법 대응 보조).

데이터 엔진에 쌓인 위험 이벤트·인식 기록·증거 프레임을 모아, 인쇄/ PDF 저장이
가능한 자체 HTML 리포트를 만든다(외부 PDF 라이브러리 불필요). 기업의 '안전보건
확보의무 이행' 증빙 보조 자료로 활용.

⚠️ 법적 자문/인증이 아니라 안전관리 활동 기록 보조 도구다(리포트에도 명시).
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List


# 위험요인 → 국내 위험성평가 양식 컬럼 자동 채움.
# (세부작업, 위험분류, 위험발생 상황·결과, 관련근거(법적기준), 현재 안전보건조치, 중대성(강도), 감소대책)
RISK_ASSESS = {
    "안전모 미착용": {
        "work": "작업장 내 보호구 착용 작업", "cat": "추락·낙하물(머리)",
        "harm": "안전모 미착용 상태에서 낙하물·추락 시 머리 중상",
        "law": "산업안전보건법 제38조(안전조치)·안전보건규칙(보호구 착용)",
        "now": "AI 영상으로 안전모 미착용 자동 감지·실시간 경보·기록", "sev": 2,
        "act": "안전모 착용 지도, 출입 시 PPE 점검, 미착용자 작업 제한"},
    "안전조끼 미착용": {
        "work": "차량·중장비 인접 작업", "cat": "충돌·협착(시인성)",
        "harm": "시인성 저하로 차량·장비에 충돌·협착",
        "law": "산업안전보건법 제38조·안전보건규칙(보호구·신호수)",
        "now": "AI 영상으로 안전조끼 미착용 감지·경보", "sev": 2,
        "act": "안전조끼 착용 의무화, 정기 점검, 야간 반사조끼"},
    "위험구역 접근": {
        "work": "위험구역 인접 작업", "cat": "협착·충돌·추락",
        "harm": "위험구역 진입으로 협착·충돌·추락 등 중대재해",
        "law": "산업안전보건법 제38조·안전보건규칙(출입금지·방호)",
        "now": "AI 영상으로 위험구역 진입 감지·실시간 경보", "sev": 3,
        "act": "출입통제, 경고표지, 물리적 방호울, 접근 경보"},
    "전도/쓰러짐 의심": {
        "work": "이동·운반 작업", "cat": "전도",
        "harm": "바닥 미끄럼·장애물로 전도하여 부상",
        "law": "산업안전보건법 제38조·안전보건규칙(전도 방지·정리정돈)",
        "now": "AI 영상으로 전도·쓰러짐 감지·경보", "sev": 3,
        "act": "바닥 정리정돈, 미끄럼 방지, 즉시 확인 체계"},
    "낙상(AI)": {
        "work": "고소·작업발판 작업", "cat": "추락·낙상",
        "harm": "작업 중 낙상·추락으로 중상",
        "law": "산업안전보건법 제38조·안전보건규칙(추락 방지)",
        "now": "AI 영상으로 낙상 감지·즉시 경보", "sev": 3,
        "act": "안전난간·안전대 설치, 작업발판 점검, 추락방지망"},
    "차량/중장비 근접": {
        "work": "차량계 건설기계 작업", "cat": "충돌·협착",
        "harm": "작업자-중장비 근접으로 충돌·협착",
        "law": "산업안전보건법 제38조·안전보건규칙(차량계 운반·유도)",
        "now": "AI 영상으로 사람-중장비 근접 감지·경보", "sev": 3,
        "act": "유도자 배치, 접근 경보, 작업동선 분리, 제한속도"},
    "위험 자세(AI)": {
        "work": "중량물 취급·반복 작업", "cat": "근골격계",
        "harm": "부적절 자세로 근골격계 질환·작업 중 부상",
        "law": "산업안전보건법 제39조(보건조치)·안전보건규칙(근골격계부담작업)",
        "now": "AI 영상으로 위험 자세 감지·피드백", "sev": 2,
        "act": "올바른 작업자세 교육, 인간공학적 개선, 휴식 부여"},
    "fire": {
        "work": "화기·발화원 인접 작업", "cat": "화재·폭발",
        "harm": "화재 발생으로 화상·질식·연소 확대",
        "law": "산업안전보건법 제38조·안전보건규칙(화재·폭발 예방)",
        "now": "AI 영상으로 불꽃 감지·실시간 경보", "sev": 3,
        "act": "소화설비 점검, 화기작업 허가제, 가연물 관리, 대피로 확보"},
    "smoke": {
        "work": "밀폐·실내 작업", "cat": "화재·질식",
        "harm": "연기 발생·흡입으로 질식·시야 저하",
        "law": "산업안전보건법 제38조·안전보건규칙(환기·화재)",
        "now": "AI 영상으로 연기 감지·경보", "sev": 3,
        "act": "환기, 발화원 점검, 대피로·경보 확보"},
    "smoking": {
        "work": "작업장 내 흡연 행위", "cat": "화기 관리",
        "harm": "작업장 흡연·화기로 화재 발생",
        "law": "산업안전보건법 제38조·안전보건규칙(화기 관리)",
        "now": "AI 영상으로 흡연·화기 감지", "sev": 2,
        "act": "지정 흡연구역 운영, 작업장 화기 금지"},
    "fall_from_height": {
        "work": "고소작업", "cat": "추락",
        "harm": "고소작업 중 추락으로 중상·사망",
        "law": "산업안전보건법 제38조·안전보건규칙(추락 방지)",
        "now": "AI 영상으로 고소작업 추락 감지·경보", "sev": 3,
        "act": "안전대·안전난간·추락방지망 설치, 개구부 덮개"},
}
_HZ_KO = {"fire": "화재(불꽃)", "smoke": "연기", "smoking": "흡연/화기", "fall_from_height": "고소작업 추락"}


def _likelihood(count: int) -> int:
    return 1 if count <= 2 else (2 if count <= 8 else 3)


def _level(score: int):
    if score >= 6:
        return "상", "#ef4444"
    if score >= 3:
        return "중", "#f59e0b"
    return "하", "#10b981"


def _risk_assessment_rows(insights: dict) -> str:
    """국내 위험성평가 양식(13열)에 맞춰 자동 채움. 개선예정일/완료일/담당자는 입력칸."""
    items = [(r, c) for r, c in insights.get("top_reasons", [])]
    items += [(h, c) for h, c in insights.get("top_hazards", [])]
    rows = []
    for key, count in items:
        info = RISK_ASSESS.get(key)
        if info is None:
            continue
        likely = _likelihood(int(count))
        sev = info["sev"]
        score = likely * sev
        lvl, color = _level(score)
        imp_likely = max(1, likely - 1)          # 대책 적용 후 가능성 1단계 감소 가정
        imp_score = imp_likely * sev
        imp_lvl, imp_color = _level(imp_score)
        ed = '<td contenteditable="true" class="fill"></td>'  # 개선예정일/완료일/담당자(수기)
        c = "text-align:center"
        rows.append(
            f"<tr><td>{info['work']}</td><td style='{c}'>{info['cat']}</td><td>{info['harm']}</td>"
            f"<td style='font-size:11px'>{info['law']}</td><td style='font-size:11px'>{info['now']}</td>"
            f"<td style='{c}'>{likely}</td><td style='{c}'>{sev}</td>"
            f"<td style='{c};font-weight:800;color:{color}'>{score}<br><span style='font-size:10px'>({lvl})</span></td>"
            f"<td>{info['act']}</td>"
            f"<td style='{c};font-weight:800;color:{imp_color}'>{imp_score}<br><span style='font-size:10px'>({imp_lvl})</span></td>"
            f"{ed}{ed}{ed}</tr>")
    if not rows:
        return '<tr><td colspan="13" class="muted">감지된 유해·위험요인이 없습니다.</td></tr>'
    return "".join(rows)


def _b64_image(path: Path) -> str | None:
    try:
        return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()
    except Exception:
        return None


_KST = timezone(timedelta(hours=9))


def _fmt_ts(ts: str) -> str:
    """ISO 또는 압축형(YYYYMMDDTHHMMSS_micro) UTC 시각 → 한국시간(KST) 문자열."""
    ts = ts or ""
    dt = None
    try:
        if "-" in ts:                       # ISO (위험이벤트/인식기록)
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif "T" in ts:                     # 압축형 (증거 프레임 manifest)
            dt = datetime.strptime(ts.split("_")[0], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        dt = None
    if dt is None:
        return ts[:19].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M:%S")


def _within(ts: str, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) >= since
    except Exception:
        return True


def build_safety_report_html(de, site_name: str = "현장", hours: int = 24, max_images: int = 8) -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    insights = de.insights()
    timeline = [e for e in de.timeline(500) if _within(e.get("ts", ""), since)]
    recog = [r for r in de.recognition_log(300) if _within(r.get("ts", ""), since)]

    # 증거 프레임 (manifest 최근 항목 → base64 임베드, 자체완결 파일)
    evid_html = ""
    try:
        lines = de.manifest_path.read_text(encoding="utf-8").splitlines()[-max_images:]
        cards = []
        for ln in lines:
            if not ln.strip():
                continue
            rec = json.loads(ln)
            img = _b64_image(de.root / rec.get("image", ""))
            if not img:
                continue
            is_intr = rec.get("event") == "zone_intrusion"
            badge = ('<span style="background:#ef4444;color:#fff;padding:1px 6px;border-radius:6px;'
                     'font-size:10px;font-weight:800">🚨 위험구역 침입</span><br>') if is_intr else ''
            border = ' style="border:2px solid #ef4444"' if is_intr else ''
            cards.append(
                f'<div class="ev"{border}><img src="{img}"/>'
                f'<div class="cap">{badge}{_fmt_ts(rec.get("ts",""))} (KST)<br>'
                f'사유: {rec.get("reason","")}</div></div>')
        evid_html = "".join(cards) or '<p class="muted">수집된 증거 프레임이 없습니다.</p>'
    except Exception:
        evid_html = '<p class="muted">증거 프레임 없음.</p>'

    def rows(items):
        return "".join(
            f'<tr><td>{_fmt_ts(e.get("ts",""))}</td><td>{e.get("risk_score","")}</td>'
            f'<td>{", ".join(e.get("reasons",[]))}</td>'
            f'<td>{", ".join(x for x in e.get("hazards",[]) if x) or "-"}</td></tr>'
            for e in items[-50:][::-1])

    reason_rows = "".join(f"<tr><td>{r}</td><td>{c}회</td></tr>" for r, c in insights.get("top_reasons", []))
    hazard_rows = "".join(f"<tr><td>{r}</td><td>{c}회</td></tr>" for r, c in insights.get("top_hazards", []))
    recog_rows = "".join(f'<tr><td>{_fmt_ts(r.get("ts",""))}</td><td>{r.get("text","")}</td></tr>'
                         for r in recog[-40:][::-1])
    risk_rows = _risk_assessment_rows(insights)

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>BODA TECH 안전관리 증빙 리포트 - {site_name}</title>
<style>
  @media print {{ .noprint{{display:none}} body{{margin:0}} }}
  body{{font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#1a2330;line-height:1.55;max-width:980px;margin:0 auto;padding:28px}}
  h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:17px;border-left:4px solid #ef4444;padding-left:10px;margin:26px 0 10px}}
  .sub{{color:#5b6b7d;font-size:13px}} .box{{border:1px solid #d7e0ea;border-radius:10px;padding:14px 16px;margin:10px 0;background:#f8fafc}}
  table{{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0}} th,td{{border:1px solid #d7e0ea;padding:7px 9px;text-align:left}} th{{background:#eef3f8}}
  .kpis{{display:flex;gap:12px;flex-wrap:wrap}} .kpi{{flex:1;min-width:150px;border:1px solid #d7e0ea;border-radius:10px;padding:12px;text-align:center}}
  .kpi .n{{font-size:26px;font-weight:800;color:#ef4444}} .kpi .l{{font-size:12px;color:#5b6b7d}}
  .ev-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .ev img{{width:100%;border-radius:6px;border:1px solid #d7e0ea}} .ev .cap{{font-size:11px;color:#5b6b7d;margin-top:3px}}
  .muted{{color:#8aa0b6}} .disc{{font-size:12px;color:#8090a0;border-top:1px solid #e3e9f0;margin-top:24px;padding-top:12px}}
  .btn{{background:#ef4444;color:#fff;border:0;border-radius:8px;padding:10px 16px;font-weight:800;cursor:pointer;font-size:14px}}
  .ra{{font-size:12px}} .ra th{{text-align:center;font-size:11.5px;background:#eef3f8;vertical-align:middle}} .ra td{{vertical-align:middle}}
  .fill{{background:#fffbe6;min-width:50px}}
</style></head><body>
<div class="noprint" style="text-align:right;margin-bottom:10px"><button class="btn" onclick="window.print()">🖨 인쇄 / PDF로 저장</button></div>
<h1>BODA TECH 안전관리 증빙 리포트</h1>
<div class="sub">현장: <b>{site_name}</b> · 기간: 최근 {hours}시간 · 생성: {_fmt_ts(now.isoformat())} (KST)</div>

<h2>1. 개요</h2>
<div class="box">본 리포트는 BODA TECH 영상 안전 시스템이 자동 기록한 위험 감지 이벤트·상시 인식 활동·
증거 프레임을 종합한 <b>안전보건 관리활동 증빙 보조 자료</b>입니다.
(중대재해처벌법 제4조 안전보건 확보의무 및 산업안전보건법상 안전관리 활동의 이행 기록 목적)</div>

<h2>2. 요약</h2>
<div class="kpis">
  <div class="kpi"><div class="n">{insights.get('total_events',0)}</div><div class="l">위험 이벤트(누적)</div></div>
  <div class="kpi"><div class="n">{insights.get('avg_risk_score',0)}</div><div class="l">평균 위험도</div></div>
  <div class="kpi"><div class="n">{len(recog)}</div><div class="l">기간 내 인식 기록</div></div>
</div>
<table><tr><th>주요 위험 원인</th><th>발생</th></tr>{reason_rows or '<tr><td colspan=2 class=muted>해당 없음</td></tr>'}</table>
<table><tr><th>위험요소(화재/연기 등)</th><th>발생</th></tr>{hazard_rows or '<tr><td colspan=2 class=muted>해당 없음</td></tr>'}</table>

<h2 id="riskassess">3. 위험성 평가</h2>
<div class="box" style="font-size:12px">국내 위험성평가표(산업안전보건법) 양식으로 자동 작성했습니다. <b>위험성 = 가능성(빈도) × 중대성(강도)</b>
(1~3 척도, 위험성 1~2 하·3~4 중·6~9 상). 시스템 자동 초안이며 <b>안전관리자 검토·확정 및 개선예정일/완료일/담당자 기입이 필요</b>합니다.
개선후 위험성은 감소대책 적용 시 가능성 1단계 하향을 가정한 추정치입니다.</div>
<table class="ra">
  <tr>
    <td colspan="3" style="text-align:left;font-weight:700">작업공정명: {site_name}</td>
    <td colspan="5" style="text-align:center;font-size:17px;font-weight:800;letter-spacing:3px">위 험 성 평 가</td>
    <td colspan="5" style="text-align:right;font-weight:700">평가일시: {_fmt_ts(now.isoformat())} (KST)</td>
  </tr>
  <tr>
    <th rowspan="2">세부작업<br>내용</th>
    <th colspan="2">유해 위험요인 파악</th>
    <th rowspan="2">관련근거<br>(법적기준)</th>
    <th rowspan="2">현재의<br>안전보건조치</th>
    <th colspan="3">위 험 성</th>
    <th rowspan="2">위험성 감소대책</th>
    <th rowspan="2">개선후<br>위험성</th>
    <th rowspan="2">개선<br>예정일</th>
    <th rowspan="2">완료일</th>
    <th rowspan="2">담당자</th>
  </tr>
  <tr>
    <th>위험분류</th><th>위험발생<br>상황 및 결과</th>
    <th>가능성<br>(빈도)</th><th>중대성<br>(강도)</th><th>위험성</th>
  </tr>
  {risk_rows}
</table>

<h2>4. 위험 이벤트 기록</h2>
<table><tr><th>시각(KST)</th><th>위험도</th><th>사유</th><th>위험요소</th></tr>{rows(timeline) or '<tr><td colspan=4 class=muted>기간 내 위험 이벤트 없음</td></tr>'}</table>

<h2>5. 상시 인식 활동 기록 (모니터링 증빙)</h2>
<table><tr><th>시각(KST)</th><th>인식 내용</th></tr>{recog_rows or '<tr><td colspan=2 class=muted>기록 없음</td></tr>'}</table>

<h2>6. 증거 프레임</h2>
<div class="ev-grid">{evid_html}</div>

<div class="disc">본 자료는 안전관리 활동 기록을 돕는 <b>보조 도구</b>의 자동 생성물이며, 법적 자문·인증·
감정 결과가 아닙니다. 영상/개인정보는 관련 법령에 따라 보관·파기되어야 합니다.
생성 시스템: BODA TECH 영상 분석 시스템.</div>
</body></html>"""
