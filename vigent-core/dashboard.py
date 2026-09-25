"""dashboard.py — 테마별 경영 대시보드(이벤트 통계 집계 + 다크 HTML 렌더)

data_engine(이벤트 로그)·tbm_store·audit_store·Scribe 의 실제 데이터를 집계해
관제용 대시보드 카드(발생건수·유형별·현장별·등급별·이력·처리현황)를 그린다.
외부 CDN 없이 순수 CSS/SVG(폐쇄망·USB 안전).
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

import data_engine

KST = timezone(timedelta(hours=9))

# 규칙 → 한국어 라벨(테마 공통)
RULE_KO = {
    "zone_intrusion": "위험구역 침입", "ppe_missing": "보호구 미착용",
    "guard_bypass": "방호구역 침입",
    "fire_smoke": "화재/연기", "ergonomic_risk": "근골격계 부담",
    "trip_hazard": "전도/미끄러짐", "forklift": "지게차 접근",
    "proximity_hazard": "작업반경 침입(협착)", "safety_measure_missing": "안전조치 미흡",
    "crowd_density": "인원 밀집(혼잡)", "lone_worker": "단독작업(2인1조 위반)",
    "immobility": "장시간 무동작(45초 이상 정지)", "rapid_motion": "급격한 이동(돌진)",   # ★2026-09-26: 낙상 감지 아님 — "쓰러짐" 표기 제거
}
LEVEL_KO = {"low": ("주의", "#22c55e"), "mid": ("경계", "#f59e0b"),
            "medium": ("경계", "#f59e0b"), "high": ("경계", "#f59e0b"),
            "critical": ("심각", "#ef4444")}


def _bar(label, n, mx, color="#b8841a"):
    w = int(round((n / mx) * 100)) if mx else 0
    e = html.escape
    return (f'<div class="bar"><span class="bl">{e(str(label))}</span>'
            f'<span class="bt"><span class="bf" style="width:{w}%;background:{color}"></span></span>'
            f'<span class="bn">{n}</span></div>')


def aggregate(theme: str, scribe=None, tbm_count: int = 0, audit_count: int = 0) -> dict:
    events = data_engine.list_events(limit=200000)
    now = datetime.now(KST)
    ym_now = now.strftime("%Y-%m")
    ym_last = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    by_rule: dict[str, int] = {}
    by_site: dict[str, int] = {}
    by_level: dict[str, int] = {}
    rule_month: dict[str, dict[str, int]] = {}
    by_day: dict[str, int] = {}
    tot = tot_now = tot_last = 0
    for e in events:
        rule = e.get("rule", "") or "기타"
        site = (e.get("site") or "미지정").strip() or "미지정"
        lvl = (e.get("level") or "low").lower()
        ym = (e.get("ts", "") or "")[:7]
        day = e.get("date", "")
        by_rule[rule] = by_rule.get(rule, 0) + 1
        by_site[site] = by_site.get(site, 0) + 1
        by_level[lvl] = by_level.get(lvl, 0) + 1
        rm = rule_month.setdefault(rule, {"now": 0, "last": 0})
        if ym == ym_now:
            rm["now"] += 1
            tot_now += 1
        elif ym == ym_last:
            rm["last"] += 1
            tot_last += 1
        if day:
            by_day[day] = by_day.get(day, 0) + 1
        tot += 1

    recent = events[:8]
    days14 = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]
    trend = [(d[5:], by_day.get(d, 0)) for d in days14]
    saved = scribe.list_saved() if scribe else []
    return {
        "theme": theme, "generated": now.strftime("%Y-%m-%d %H:%M KST"),
        "total": tot, "total_now": tot_now, "total_last": tot_last,
        "by_rule": sorted(by_rule.items(), key=lambda x: x[1], reverse=True),
        "by_site": sorted(by_site.items(), key=lambda x: x[1], reverse=True)[:8],
        "by_level": by_level, "rule_month": rule_month,
        "recent": recent, "trend": trend,
        "ra_count": len(saved), "tbm_count": tbm_count, "audit_count": audit_count,
    }


def render_terminal(theme: str, scribe=None, tbm_count: int = 0, audit_count: int = 0) -> str:
    """모던 터미널 스킨(블룸버그 단말 감성 — 검정·앰버/초록/빨강·모노스페이스·고밀도)."""
    d = aggregate(theme, scribe, tbm_count, audit_count)
    e = html.escape
    title_map = {"safety": "SAFETY", "office": "OFFICE", "sports": "SPORTS"}
    code = title_map.get(theme, theme.upper())

    def lvl_color(lv):
        lv = (lv or "low").lower()
        if lv == "critical":
            return "#ff3b3b", "심각"
        if lv in ("high", "mid", "medium"):
            return "#ffb000", "경계"
        return "#00d26a", "주의"

    # 좌측 모노 리드아웃
    lv = d["by_level"]
    lv_low = lv.get("low", 0)
    lv_mid = lv.get("mid", 0) + lv.get("medium", 0) + lv.get("high", 0)
    lv_hi = lv.get("critical", 0)
    delta = d["total_now"] - d["total_last"]
    dcol = "#ff3b3b" if delta > 0 else "#00d26a"
    dsign = "▲" if delta > 0 else ("▼" if delta < 0 else "·")

    def ro(label, val, color="#ffb000"):
        return (f'<div class="ro"><span class="rl">{e(str(label))}</span>'
                f'<span class="rv" style="color:{color}">{e(str(val))}</span></div>')

    readout = (
        ro("총 누적", f"{d['total']:,}", "#e8e8e8")
        + ro("당월", f"{d['total_now']:,}")
        + ro("전월", f"{d['total_last']:,}", "#6b7280")
        + ro("전월대비", f"{dsign} {abs(delta):,}", dcol)
        + '<div class="rsep"></div>'
        + ro("심각", lv_hi, "#ff3b3b")
        + ro("경계", lv_mid, "#ffb000")
        + ro("주의", lv_low, "#00d26a")
        + '<div class="rsep"></div>'
        + ro("TBM 회의록", d["tbm_count"], "#d4a017")
        + ro("위험성평가서", d["ra_count"], "#d4a017")
        + ro("승인·감사추적", d["audit_count"], "#d4a017")
    )

    # 위험 유형별(bar)
    mx_r = max([n for _, n in d["by_rule"]], default=1)
    rule_rows = ""
    for r, n in d["by_rule"][:8]:
        w = int(n / mx_r * 100)
        rule_rows += (f'<div class="tb"><span class="tbl">{e(RULE_KO.get(r, r))}</span>'
                      f'<span class="tbar"><i style="width:{w}%;background:#ffb000"></i></span>'
                      f'<span class="tbn">{n}</span></div>')
    rule_rows = rule_rows or '<div class="dim">DATA 없음</div>'

    # 현장별
    site_rows = ""
    for s, n in d["by_site"]:
        site_rows += f'<tr><td>{e(s)}</td><td class="num amber">{n}</td></tr>'
    site_rows = site_rows or '<tr><td colspan="2" class="dim">DATA 없음</td></tr>'

    # 최근 이력
    hist = ""
    for ev in d["recent"]:
        c, k = lvl_color(ev.get("level"))
        hist += (f'<tr><td class="dim">{e((ev.get("ts","") or "")[:16].replace("T"," "))}</td>'
                 f'<td>{e(ev.get("site") or "미지정")}</td>'
                 f'<td style="color:{c};font-weight:700">{k}</td>'
                 f'<td>{e(RULE_KO.get(ev.get("rule",""), ev.get("rule","")))}</td></tr>')
    hist = hist or '<tr><td colspan="4" class="dim">발생 이력 없음</td></tr>'

    # 14일 추이
    tmx = max([n for _, n in d["trend"]], default=1)
    tcols = "".join(
        f'<div class="tc"><i style="height:{int((n/tmx)*70) if tmx else 0}px"></i>'
        f'<span>{e(lbl)}</span></div>' for lbl, n in d["trend"])

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT {code} TERMINAL</title><style>
  :root{{--amber:#ffb000;--grn:#00d26a;--red:#ff3b3b;--ink:#e8e8e8;--dim:#6b7280;--pnl:#0c0c0e;--ln:#1c1c20}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:#000;color:var(--ink);
    font-family:"SF Mono","Roboto Mono",Menlo,Consolas,"D2Coding",monospace;font-size:13px}}
  .hdr{{display:flex;justify-content:space-between;align-items:center;padding:8px 14px;background:#000;border-bottom:1px solid #5a4a18}}
  .hdr .l{{color:#7bbf8a;font-weight:700;letter-spacing:1px}}
  .hdr .r{{color:var(--amber);font-weight:800;letter-spacing:2px;font-size:15px}}
  .fbar{{display:flex;gap:1px;background:#000}}
  .fbar a{{flex:1;text-align:center;padding:6px 4px;text-decoration:none;font-weight:700;font-size:12px;color:#e9dfc8;border-right:1px solid #000}}
  .fbar a.g{{background:#235e34}} .fbar a.r{{background:#8f2820}} .fbar a.a{{background:#8a6817}}
  .fbar a:hover{{filter:brightness(1.4)}}
  .wrap{{display:grid;grid-template-columns:260px 1fr;gap:10px;padding:10px}}
  @media(max-width:900px){{.wrap{{grid-template-columns:1fr}}}}
  .pnl{{background:var(--pnl);border:1px solid var(--ln);padding:12px}}
  .pnl h3{{margin:0 0 10px;font-size:11px;color:var(--dim);letter-spacing:1px;text-transform:uppercase;border-bottom:1px solid var(--ln);padding-bottom:6px}}
  .ro{{display:flex;justify-content:space-between;padding:5px 0;font-size:13px}}
  .ro .rl{{color:#9aa0a6}} .ro .rv{{font-weight:700;font-variant-numeric:tabular-nums}}
  .rsep{{height:1px;background:var(--ln);margin:8px 0}}
  .right{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
  @media(max-width:900px){{.right{{grid-template-columns:1fr}}}}
  .span2{{grid-column:1 / -1}}
  .tb{{display:flex;align-items:center;gap:8px;margin:6px 0}}
  .tbl{{width:120px;color:#cfd3d8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:none}}
  .tbar{{flex:1;height:12px;background:#17171a;border:1px solid var(--ln)}}
  .tbar i{{display:block;height:100%}} .tbn{{width:30px;text-align:right;color:var(--amber);font-weight:700}}
  table{{width:100%;border-collapse:collapse;font-size:12.5px}}
  th,td{{padding:5px 6px;border-bottom:1px solid var(--ln);text-align:left}}
  th{{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}} .amber{{color:var(--amber)}}
  .dim{{color:var(--dim)}}
  .trend{{display:flex;align-items:flex-end;gap:3px;height:88px;margin-top:4px}}
  .tc{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}}
  .tc i{{width:70%;min-height:2px;background:var(--grn);box-shadow:0 0 6px rgba(0,210,106,.4)}}
  .tc span{{font-size:8px;color:var(--dim);margin-top:3px;transform:rotate(-35deg);white-space:nowrap}}
  .stat{{padding:6px 14px;background:#000;border-top:1px solid var(--ln);color:var(--dim);font-size:11px;
    display:flex;justify-content:space-between;letter-spacing:.5px}}
  .blink{{color:var(--grn)}} .blink b{{animation:bk 1.4s steps(1) infinite}} @keyframes bk{{50%{{opacity:.25}}}}
</style></head><body>
  <div class="hdr"><div class="l">&lt;VIGENT&gt; 산업안전 관제 터미널</div><div class="r">Equity {code}</div></div>
  <div class="fbar">
    <a class="a" href="/{e(theme)}">01) 실시간 관제</a>
    <a class="r" href="/safety/auto">02) 자동처리 콘솔</a>
    <a class="g" href="/safety/brain">03) 안전 추론 엔진</a>
    <a class="a" href="/safety/reports">04) 위험성평가</a>
    <a class="g" href="/home">99) 홈</a>
  </div>
  <div class="wrap">
    <div class="pnl"><h3>위험 현황 요약</h3>{readout}</div>
    <div class="right">
      <div class="pnl"><h3>위험 유형별 발생</h3>{rule_rows}</div>
      <div class="pnl"><h3>현장별 발생</h3><table><thead><tr><th>현장</th><th style="text-align:right">건수</th></tr></thead><tbody>{site_rows}</tbody></table></div>
      <div class="pnl span2"><h3>최근 발생 이력</h3><table><thead><tr><th>시각</th><th>현장</th><th>등급</th><th>유형</th></tr></thead><tbody>{hist}</tbody></table></div>
      <div class="pnl span2"><h3>최근 14일 발생 추이</h3><div class="trend">{tcols}</div></div>
    </div>
  </div>
  <div class="stat"><span class="blink"><b>●</b> LIVE · 실제 누적 이벤트 기반</span><span>생성 {e(d['generated'])} · GMT+9</span><span>VIGENT © 산업안전 AI</span></div>
</body></html>"""


def render(theme: str, scribe=None, tbm_count: int = 0, audit_count: int = 0) -> str:
    d = aggregate(theme, scribe, tbm_count, audit_count)
    e = html.escape
    title_map = {"safety": "안전 관제", "office": "오피스 관제", "sports": "스포츠 관제"}
    title = title_map.get(theme, theme)

    # 카드1: 발생건수(유형별 당월/전월)
    rows = ""
    for rule, _n in d["by_rule"][:6]:
        rm = d["rule_month"].get(rule, {"now": 0, "last": 0})
        rows += (f'<tr><td>{e(RULE_KO.get(rule, rule))}</td>'
                 f'<td class="num">{rm["now"]}</td><td class="num dim">{rm["last"]}</td></tr>')
    rows = rows or '<tr><td colspan="3" class="dim">데이터 없음</td></tr>'

    # 카드2: 유형별 현황(bar)
    mx_r = max([n for _, n in d["by_rule"]], default=1)
    rule_bars = "".join(_bar(RULE_KO.get(r, r), n, mx_r, "#b8841a") for r, n in d["by_rule"][:7]) \
        or '<div class="dim">데이터 없음</div>'

    # 카드3: 현장별 현황(bar)
    mx_s = max([n for _, n in d["by_site"]], default=1)
    site_bars = "".join(_bar(s, n, mx_s, "#d4a017") for s, n in d["by_site"]) \
        or '<div class="dim">데이터 없음</div>'

    # 카드4: 최근 이력
    hist = ""
    for ev in d["recent"]:
        lk, lc = LEVEL_KO.get((ev.get("level") or "low").lower(), ("주의", "#22c55e"))
        hist += (f'<tr><td class="dim">{e((ev.get("ts","") or "")[:16].replace("T"," "))}</td>'
                 f'<td>{e(ev.get("site") or "미지정")}</td>'
                 f'<td><span class="lvl" style="background:{lc}">{lk}</span></td>'
                 f'<td>{e(RULE_KO.get(ev.get("rule",""), ev.get("rule","")))}</td></tr>')
    hist = hist or '<tr><td colspan="4" class="dim">발생 이력 없음</td></tr>'

    # 카드5: 등급별 분포
    lv = d["by_level"]
    lv_low = lv.get("low", 0)
    lv_mid = lv.get("mid", 0) + lv.get("medium", 0) + lv.get("high", 0)
    lv_hi = lv.get("critical", 0)
    lv_mx = max(lv_low, lv_mid, lv_hi, 1)
    lvl_bars = (_bar("심각", lv_hi, lv_mx, "#ef4444")
                + _bar("경계", lv_mid, lv_mx, "#f59e0b")
                + _bar("주의", lv_low, lv_mx, "#22c55e"))

    # 카드6: 추이(14일)
    tmx = max([n for _, n in d["trend"]], default=1)
    tcols = "".join(
        f'<div class="tcol"><div class="tb" style="height:{int((n/tmx)*72) if tmx else 0}px"></div>'
        f'<div class="tx">{e(lbl)}</div></div>' for lbl, n in d["trend"])

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT {e(title)} 대시보드</title><style>
  body{{margin:0;background:#000000;color:#e5e7eb;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo","Malgun Gothic",monospace}}
  .top{{display:flex;justify-content:space-between;align-items:center;padding:14px 22px;border-bottom:1px solid #1c1c20}}
  .top .lg{{font-weight:800;letter-spacing:1px;color:#fff}} .top .lg b{{color:#ffb000}}
  .top a{{color:#d4a017;text-decoration:none;font-size:13px;margin-left:14px}}
  .grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;padding:16px 22px}}
  @media(max-width:1000px){{.grid{{grid-template-columns:1fr}}}}
  .card{{background:#0c0c0e;border:1px solid #1c1c20;border-radius:12px;padding:16px;min-height:210px}}
  .card h3{{margin:0 0 12px;font-size:14px;color:#cbd5e1;display:flex;align-items:center;gap:7px}}
  .card h3 .m{{font-size:10px;background:#17150e;color:#d4a017;border-radius:4px;padding:1px 5px}}
  .big{{text-align:right;font-size:13px;color:#94a3b8;margin-bottom:6px}} .big b{{font-size:34px;color:#f87171;margin-left:8px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{padding:7px 6px;border-bottom:1px solid #1c1c20;text-align:left}} th{{color:#64748b;font-weight:600;font-size:12px}}
  td.num{{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}} .dim{{color:#64748b}}
  .bar{{display:flex;align-items:center;gap:8px;margin:7px 0;font-size:12.5px}}
  .bar .bl{{width:96px;color:#cbd5e1;flex:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .bar .bt{{flex:1;height:9px;background:#1c1c20;border-radius:6px;overflow:hidden}}
  .bar .bf{{display:block;height:100%;border-radius:6px}} .bar .bn{{width:34px;text-align:right;font-weight:700}}
  .lvl{{color:#000000;font-weight:800;font-size:11px;border-radius:5px;padding:1px 7px}}
  .trend{{display:flex;align-items:flex-end;gap:4px;height:96px;margin-top:6px}}
  .tcol{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end}}
  .tcol .tb{{width:62%;min-height:2px;background:linear-gradient(#ffb000,#c8941a);border-radius:3px}}
  .tcol .tx{{font-size:9px;color:#64748b;margin-top:4px;transform:rotate(-30deg)}}
  .stat{{display:flex;gap:10px;margin-top:8px}} .stat .s{{flex:1;background:#0a0a0c;border:1px solid #1c1c20;border-radius:10px;padding:14px;text-align:center}}
  .stat .s b{{display:block;font-size:26px;color:#d4a017}} .stat .s span{{font-size:12px;color:#94a3b8}}
  .foot{{padding:0 22px 22px;color:#475569;font-size:11px}}
</style></head><body>
  <div class="top">
    <div class="lg">🛡 VIGENT <b>{e(title)}</b> 대시보드</div>
    <div><a href="/{e(theme)}">실시간 관제</a><a href="/safety/auto">자동처리 콘솔</a><a href="/safety/reports">평가서</a></div>
  </div>
  <div class="grid">
    <div class="card">
      <h3><span class="m">통계</span> 위험 이벤트 발생건수</h3>
      <div class="big">총 누적<b>{d['total']}건</b></div>
      <table><thead><tr><th>유형</th><th class="num">당월</th><th class="num">전월</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>
    <div class="card"><h3><span class="m">분석</span> 위험 유형별 현황</h3>{rule_bars}</div>
    <div class="card"><h3><span class="m">분석</span> 현장별 발생 현황</h3>{site_bars}</div>
    <div class="card"><h3><span class="m">이력</span> 최근 발생 이력</h3>
      <table><thead><tr><th>발생</th><th>현장</th><th>등급</th><th>유형</th></tr></thead><tbody>{hist}</tbody></table></div>
    <div class="card"><h3><span class="m">분포</span> 위험등급별 분포</h3>{lvl_bars}
      <div class="stat">
        <div class="s"><b>{lv_hi}</b><span>심각</span></div>
        <div class="s"><b>{lv_mid}</b><span>경계</span></div>
        <div class="s"><b>{lv_low}</b><span>주의</span></div>
      </div></div>
    <div class="card"><h3><span class="m">추이</span> 최근 14일 발생 추이</h3>
      <div class="trend">{tcols}</div>
      <div class="stat">
        <div class="s"><b>{d['tbm_count']}</b><span>TBM 회의록</span></div>
        <div class="s"><b>{d['ra_count']}</b><span>위험성평가서</span></div>
        <div class="s"><b>{d['audit_count']}</b><span>승인(감사추적)</span></div>
      </div></div>
  </div>
  <div class="foot">생성 {e(d['generated'])} · 실제 누적 이벤트 기반 · 데이터 없으면 0으로 표시</div>
</body></html>"""
