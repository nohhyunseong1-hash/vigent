"""hub.py — VIGENT 홈(허브) 화면

바탕화면 런처 1개 → 이 허브 → 가장 좋은 기능들을 타일로 한눈에 클릭.
새 도구가 생기면 TILES 에 한 줄 추가하면 된다.
겉모습은 공용 디자인시스템 /static/vigent-terminal.css(앰버 터미널)를 따른다.
"""
from __future__ import annotations

# (그룹, 아이콘, 제목, 설명, 경로)  ← 아이콘은 데이터로만 보관(터미널 화면엔 렌더 안 함)
TILES = [
    ("운영", "🎥", "실시간 안전 관제", "카메라로 위험 실시간 감지·표시", "/safety-local"),
    ("운영", "🧠", "안전 지식 추론 엔진", "작업별 '없는 안전조치'를 추론(지식+VLM)", "/safety/brain"),
    ("운영", "🛡", "자동처리 콘솔", "감지→증거·법령·평가서·조치 자동", "/safety/auto"),
    ("운영", "🎤", "음성 안전 비서", "근로자가 음성으로 묻고 스피커로 답", "/safety/voice"),
    ("운영", "🔊", "현장 음성 안내", "카메라 화면 보고 위험·안전수칙 음성 안내", "/safety/guide"),
    ("운영", "📊", "경영 대시보드", "현장 위험 통계 한눈에", "/dashboard"),
    ("문서", "🔍", "재해 원인분석", "사고 영상→상황·빠진조치·법령(보조)", "/safety/incident"),
    ("도구", "📏", "정확도 측정", "재현율·정밀도 자체 측정(인증 준비)", "/safety/eval"),
    ("문서", "📄", "위험성평가·리포트", "KOSHA 서식 자동 생성", "/safety/reports"),
    ("문서", "📋", "TBM 회의록", "작업 전 안전점검회의 작성", "/safety/tbm"),
    ("영업", "🎬", "영업 데모", "감지→서류 자동완성 시연", "/safety/demo"),
    ("영업", "🧾", "견적서", "현장 견적 1장(인쇄·PDF)", "/safety/quote"),
    ("도구", "🦺", "현장 보호구 설정", "현장별 필수 보호구 지정→미착용 경고", "/safety/ppe"),
    ("도구", "⚙️", "현장 운영 설정", "카메라·워커·알림 설정", "/safety/setup"),
    ("도구", "🔁", "CDN판(비교용)", "인터넷 CDN으로 구동 — 로컬판과 비교", "/safety"),
]


def render() -> str:
    groups: dict[str, list] = {}
    for g, _icon, title, desc, path in TILES:   # 아이콘(이모지)은 렌더하지 않는다(터미널 룩)
        groups.setdefault(g, []).append((title, desc, path))
    sections = ""
    for g, items in groups.items():
        cards = "".join(
            f'<a class="vt-tile" href="{p}">'
            f'<div class="cat">{g}</div>'
            f'<div class="tt">{t}</div><div class="td">{d}</div>'
            f'<div class="tp">{p}</div></a>'
            for t, d, p in items)
        sections += f'<div class="vt-sec">{g}</div><div class="vt-tiles">{cards}</div>'
    return _PAGE.replace("{{SECTIONS}}", sections)


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT // 산업안전 AI — 허브</title>
<link rel="stylesheet" href="/static/vigent-terminal.css?v=3">
<style>
  *{box-sizing:border-box} html,body{margin:0}
  body{min-height:100vh;background:var(--vt-bg)}
  .cat{color:var(--vt-dim);font-size:9px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:6px}
  .vt-foot{max-width:1120px;margin:26px auto 0;padding:0 20px 40px;color:var(--vt-dim);
           font-size:11px;line-height:1.7;text-align:center}
</style></head>
<body class="vt-scope vt-page">
<div class="vt-cmdbar">
  <div class="vt-brand">VIGENT<b>//</b>SAFETY</div>
  <div><span class="vt-key">HUB</span><span class="vt-val">산업안전 AI 콘솔</span></div>
  <div class="vt-spacer"></div>
  <div class="vt-conn"><span class="vt-dot"></span><span class="vt-key">LINK</span><span class="vt-ok" id="link">····</span></div>
  <div><span class="vt-key">EVENTS</span><span class="vt-val vt-num" id="evc">--</span></div>
  <div><span class="vt-val vt-num" id="clock">--:--:--</span></div>
</div>
<div class="vt-wrap">
  <h1 class="vt-h1">VIGENT 산업안전 AI 콘솔</h1>
  <p class="vt-sub">Vision + AI Agent · 감지 → 증거 · 법령 · 평가서 · 조치 자동</p>
  {{SECTIONS}}
</div>
<div class="vt-foot">보조·기록 도구이며 인증 안전장치를 대체하지 않습니다. 최종 판단·조치는 안전관리자 승인하에 이뤄집니다.<br>
  © VIGENT — 감지에서 서류·조치까지 닫는 산업안전 AI</div>
<script>
(function(){
  var $=function(id){return document.getElementById(id);};
  function tick(){ $('clock').textContent=new Date().toLocaleTimeString('en-GB'); }
  setInterval(tick,1000); tick();
  fetch('/health').then(function(r){return r.json();}).then(function(j){
    $('link').textContent=(j&&j.status==='ok')?'ONLINE':'DEGRADED';
  }).catch(function(){ $('link').textContent='OFFLINE'; });
  fetch('/safety/auto/feed?hours=100000').then(function(r){return r.json();}).then(function(j){
    var n=((j&&j.events)||[]).length; $('evc').textContent=n;
  }).catch(function(){ $('evc').textContent='0'; });
})();
</script></body></html>"""
