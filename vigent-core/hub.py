"""hub.py — VIGENT 홈(허브) 화면

바탕화면 런처 1개 → 이 허브 → 가장 좋은 기능들을 타일로 한눈에 클릭.
새 도구가 생기면 TILES 에 한 줄 추가하면 된다.
"""
from __future__ import annotations

# (그룹, 아이콘, 제목, 설명, 경로)
TILES = [
    ("운영", "🎥", "실시간 안전 관제", "카메라로 위험 실시간 감지·표시", "/safety"),
    ("운영", "🧠", "안전 지식 추론 엔진", "작업별 '없는 안전조치'를 추론(지식+VLM)", "/safety/brain"),
    ("운영", "🛡", "자동처리 콘솔", "감지→증거·법령·평가서·조치 자동", "/safety/auto"),
    ("운영", "📊", "경영 대시보드", "현장 위험 통계 한눈에", "/dashboard"),
    ("문서", "📄", "위험성평가·리포트", "KOSHA 서식 자동 생성", "/safety/reports"),
    ("문서", "📋", "TBM 회의록", "작업 전 안전점검회의 작성", "/safety/tbm"),
    ("영업", "🎬", "영업 데모", "감지→서류 자동완성 시연", "/safety/demo"),
    ("영업", "🧾", "견적서", "현장 견적 1장(인쇄·PDF)", "/safety/quote"),
    ("도구", "⚙️", "현장 운영 설정", "카메라·워커·알림 설정", "/safety/setup"),
    ("도구", "🔁", "로컬 번들판", "CDN 없이 폐쇄망 구동", "/safety-local"),
]


def render() -> str:
    groups: dict[str, list] = {}
    for g, icon, title, desc, path in TILES:
        groups.setdefault(g, []).append((icon, title, desc, path))
    sections = ""
    for g, items in groups.items():
        cards = "".join(
            f'<a class="tile" href="{p}"><div class="ic">{ic}</div>'
            f'<div class="tt">{t}</div><div class="ds">{d}</div></a>'
            for ic, t, d, p in items)
        sections += f'<div class="grp"><div class="gh">{g}</div><div class="grid">{cards}</div></div>'
    return _PAGE.replace("{{SECTIONS}}", sections)


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT — 산업안전 AI</title><style>
  body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#13243f,#0b0f17 60%);color:#e5e7eb;
       font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;min-height:100vh}
  .wrap{max-width:980px;margin:0 auto;padding:38px 22px 70px}
  .hero{text-align:center;margin-bottom:26px}
  .logo{font-size:34px;font-weight:900;color:#38bdf8;letter-spacing:2px}
  .logo small{display:block;font-size:13px;color:#94a3b8;font-weight:600;letter-spacing:1px;margin-top:4px}
  .stat{color:#64748b;font-size:12.5px;margin-top:10px}
  .grp{margin-bottom:22px}
  .gh{font-size:13px;color:#7dd3fc;font-weight:800;margin:0 0 10px;letter-spacing:1px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px}
  .tile{display:block;background:#111827;border:1px solid #1f2937;border-radius:14px;padding:18px;
        text-decoration:none;color:#e5e7eb;transition:.15s;position:relative}
  .tile:hover{border-color:#2563eb;background:#15203a;transform:translateY(-2px)}
  .ic{font-size:28px;margin-bottom:8px}
  .tt{font-size:15px;font-weight:800}
  .ds{font-size:12.5px;color:#94a3b8;margin-top:3px;line-height:1.5}
  .foot{text-align:center;color:#475569;font-size:11.5px;margin-top:26px;line-height:1.7}
</style></head><body><div class="wrap">
  <div class="hero">
    <div class="logo">VIGENT<small>Vision + AI Agent · 산업안전</small></div>
    <div class="stat" id="stat">서버 연결 확인 중…</div>
  </div>
  {{SECTIONS}}
  <div class="foot">보조·기록 도구이며 인증 안전장치를 대체하지 않습니다. 최종 판단·조치는 안전관리자 승인하에 이뤄집니다.<br>
    © VIGENT — 감지에서 서류·조치까지 닫는 산업안전 AI</div>
</div>
<script>
  fetch('/safety/auto/feed?hours=100000').then(r=>r.json()).then(d=>{
    const n=(d.events||[]).length;
    document.getElementById('stat').textContent='누적 감지 이벤트 '+n+'건 · 서버 정상';
  }).catch(()=>{document.getElementById('stat').textContent='서버 정상';});
</script></body></html>"""
