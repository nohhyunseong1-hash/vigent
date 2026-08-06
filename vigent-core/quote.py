"""quote.py — VIGENT 견적서(1장, 인쇄/PDF)

현장에서 바로 보여주는 견적서. 현장명·카메라 수만 넣으면 자동 계산되고,
단가도 그 자리에서 조정 가능. 인쇄(⌘P) → PDF 저장.
가격 정책(권고): 초기 설치 1회 + 월 구독(현장당, 카메라 N대) + 중대재해 자동화 패키지(옵션).
"""
from __future__ import annotations


def render() -> str:
    return _PAGE


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT 견적서</title><style>
  :root{--ink:#0e0c08;--line:#cbd5e1;--blue:#8a6817;--muted:#64748b}
  *{box-sizing:border-box}
  body{margin:0;background:#e2e8f0;color:var(--ink);font-family:"SF Mono","D2Coding","Apple SD Gothic Neo","Malgun Gothic",monospace}
  .sheet{max-width:820px;margin:18px auto;background:#fff;padding:36px 40px;border-radius:6px;box-shadow:0 4px 24px rgba(0,0,0,.12)}
  .top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid var(--blue);padding-bottom:14px}
  .brand{font-size:24px;font-weight:900;color:var(--blue);letter-spacing:1px}
  .brand small{display:block;font-size:11.5px;color:var(--muted);font-weight:600;letter-spacing:0}
  .ttl{font-size:26px;font-weight:900;letter-spacing:6px}
  .meta{display:grid;grid-template-columns:1fr 1fr;gap:6px 24px;margin:16px 0 6px;font-size:13px}
  .meta label{color:var(--muted);margin-right:8px}
  .meta input{border:none;border-bottom:1px solid var(--line);font-size:13px;padding:3px 2px;width:62%}
  h3{font-size:13px;color:var(--blue);margin:20px 0 6px;border-left:3px solid var(--blue);padding-left:8px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:center}
  th{background:#f1f5f9;font-weight:700} td.l{text-align:left} td.r{text-align:right}
  input.num{width:78px;text-align:right;border:1px solid var(--line);border-radius:4px;padding:4px 6px;font-size:13px}
  .tot td{font-weight:800;background:#eff6ff;font-size:14px}
  .opt{accent-color:var(--blue);transform:scale(1.15)}
  .inc{font-size:12.5px;color:#2a2a2e;line-height:1.9;margin:6px 0 0;padding-left:18px}
  .note{font-size:11px;color:var(--muted);line-height:1.7;margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
  .bar{max-width:820px;margin:0 auto 24px;display:flex;gap:10px;justify-content:flex-end}
  .btn{padding:9px 18px;border:1px solid var(--blue);background:var(--blue);color:#fff;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700}
  .btn.g{background:#fff;color:var(--blue)}
  @media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:100%}.bar{display:none}
    input{border:none!important} .num{border:none!important}}
</style></head><body>
<div class="bar">
  <button class="btn g" onclick="calc()">↻ 다시 계산</button>
  <button class="btn" onclick="window.print()">🖨 인쇄 / PDF 저장</button>
</div>
<div class="sheet">
  <div class="top">
    <div class="brand">VIGENT<small>Vision + AI Agent 산업안전</small></div>
    <div class="ttl">견　적　서</div>
  </div>

  <div class="meta">
    <div><label>현장명</label><input id="site" placeholder="○○제조 1공장"></div>
    <div><label>견적일</label><input id="date" placeholder="2026-06-24"></div>
    <div><label>담당자</label><input id="manager" placeholder="홍길동 안전관리자"></div>
    <div><label>유효기간</label><input id="valid" value="견적일로부터 30일"></div>
  </div>

  <h3>1. 도입 구성 (수량 입력 시 자동 계산)</h3>
  <table><thead><tr><th>품목</th><th>내용</th><th>수량</th><th>단가(원)</th><th>금액(원)</th></tr></thead>
  <tbody>
    <tr><td class="l">초기 설치·세팅 <small>(1회)</small></td><td class="l">현장 맞춤 설치·위험구역 설정·교육</td>
      <td>1식</td><td><input class="num" id="p_setup" value="800000" oninput="calc()"></td><td class="r" id="m_setup">800,000</td></tr>
    <tr><td class="l">월 구독 — 기본</td><td class="l">실시간 감지·관제(카메라 4대 포함)</td>
      <td>1현장</td><td><input class="num" id="p_base" value="300000" oninput="calc()"></td><td class="r" id="m_base">300,000</td></tr>
    <tr><td class="l">추가 카메라</td><td class="l">4대 초과분(대당/월)</td>
      <td><input class="num" id="cams" value="4" oninput="calc()" style="width:56px;text-align:center"></td>
      <td><input class="num" id="p_cam" value="30000" oninput="calc()"></td><td class="r" id="m_cam">0</td></tr>
    <tr><td class="l"><input type="checkbox" class="opt" id="o_pkg" checked onchange="calc()"> 중대재해 대응 자동화</td>
      <td class="l">위험성평가서·TBM·법령인용·감사추적 자동(월)</td>
      <td>옵션</td><td><input class="num" id="p_pkg" value="200000" oninput="calc()"></td><td class="r" id="m_pkg">200,000</td></tr>
  </tbody></table>

  <h3>2. 비용 요약</h3>
  <table><tbody>
    <tr class="tot"><td class="l">초기 비용 (1회, 설치)</td><td class="r" id="sum_init" style="width:40%">800,000 원</td></tr>
    <tr class="tot"><td class="l">월 비용 (구독)</td><td class="r" id="sum_month">500,000 원</td></tr>
    <tr><td class="l">1년 총비용 <small>(초기 + 월×12)</small></td><td class="r" id="sum_year">6,800,000 원</td></tr>
  </tbody></table>
  <div style="font-size:11px;color:var(--muted);margin-top:4px">* 상기 금액 VAT 별도. 기존 CCTV(RTSP) 활용 시 카메라 하드웨어 비용 없음.</div>

  <h3>3. 포함 내역</h3>
  <div class="inc">
    ✓ 실시간 위험 감지 — 위험구역 침입·보호구 미착용·프레스 부위별 경보·화재/연기·근골격계 부담자세·협착 근접·인원 카운트<br>
    ✓ 감지 → <b>증거 사진 자동 저장</b> → 관련 <b>법령 자동 인용</b><br>
    ✓ <b>위험성평가서·TBM 자동 생성</b>(KOSHA 서식) — 안전관리자 승인 게이트<br>
    ✓ 위험 발생 시 담당자 <b>알림</b>(텔레그램·이메일) + <b>감사추적</b> 기록<br>
    ✓ 경영 대시보드 · 무인 워커(브라우저 없이 24시간 감시)
  </div>

  <div class="note">
    ※ VIGENT는 산업안전 <b>보조·감시 및 기록</b> 도구입니다. 비전 AI는 확률적이므로 인증 안전장치(비상정지·화재경보 등)를
    대체하지 않으며 1차 방호 책임은 인증 하드웨어에 있습니다. 최종 위험 판단·조치는 안전관리자 승인하에 이뤄집니다.<br>
    ※ 본 견적은 표준 구성 기준이며, 현장 규모·카메라 수·연동 범위에 따라 조정될 수 있습니다.
  </div>
</div>
<script>
  const won=n=>Math.round(n).toLocaleString('ko-KR');
  function v(id){return parseFloat(document.getElementById(id).value)||0;}
  function calc(){
    const setup=v('p_setup'), base=v('p_base'), cams=v('cams'), pcam=v('p_cam');
    const extra=Math.max(0,cams-4)*pcam;
    const pkg=document.getElementById('o_pkg').checked? v('p_pkg'):0;
    document.getElementById('m_setup').textContent=won(setup);
    document.getElementById('m_base').textContent=won(base);
    document.getElementById('m_cam').textContent=won(extra);
    document.getElementById('m_pkg').textContent=document.getElementById('o_pkg').checked?won(pkg):'미포함';
    const month=base+extra+pkg;
    document.getElementById('sum_init').textContent=won(setup)+' 원';
    document.getElementById('sum_month').textContent=won(month)+' 원';
    document.getElementById('sum_year').textContent=won(setup+month*12)+' 원';
  }
  calc();
</script></body></html>"""
