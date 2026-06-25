"""demo.py — 영업용 "감지→서류·조치 자동완성" 데모

카메라·실시간 이벤트 없이도, 버튼 하나로 닫힌 루프 전체를 시연한다:
  위험 감지(시뮬) → 증거 사진 → 법령 인용 → 위험성평가서 자동생성 → 조치 권고 → 승인·감사추적
영업사원이 노트북에서 2분 안에 "수작업 지옥 → 자동으로 닫힘"을 보여주는 무기.
data_engine 에 큐레이션된 데모 이벤트를 주입하면 기존 자동처리 콘솔·평가서가 그대로 채워진다.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

import data_engine

_ROOT = Path(__file__).resolve().parent.parent
_ASSETS = Path(__file__).resolve().parent / "demo_assets"

# 큐레이션 데모 이벤트(현장명은 데모용 가상). reset 은 이 현장명으로 정리한다.
DEMO_SITES = ["○○제조 1공장", "○○건설 A동 3층", "○○제조 2공장", "○○제조 도장공장"]
DEMO_EVENTS = [
    {"rule": "zone_intrusion", "level": "high", "site": "○○제조 1공장",
     "note": "프레스 중량물 작업구역에 작업자 진입", "img": "demo1.jpg"},
    {"rule": "ppe_missing", "level": "high", "site": "○○건설 A동 3층",
     "note": "고소작업 중 안전모 미착용 감지", "img": "demo2.jpg"},
    {"rule": "fall_suspected", "level": "critical", "site": "○○제조 2공장",
     "note": "적재구역에서 작업자 낙상 의심", "img": "demo3.jpg"},
    {"rule": "fire_smoke", "level": "critical", "site": "○○제조 도장공장",
     "note": "도장공장 화재·연기 의심 감지", "img": "demo4.jpg"},
    {"rule": "ergonomic_risk", "level": "low", "site": "○○제조 1공장",
     "note": "조립라인 근골격계 부담 자세 지속", "img": "demo1.jpg"},
]


def _img_data_url(name: str) -> str | None:
    p = _ASSETS / name
    if not p.exists():
        return None
    try:
        return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()
    except OSError:
        return None


def seed() -> dict:
    """데모 이벤트를 data_engine 에 주입(증거 사진 포함). 반환: 주입 수."""
    n = 0
    for ev in DEMO_EVENTS:
        data_engine.log_event(rule=ev["rule"], level=ev["level"], site=ev["site"],
                              note=ev["note"], image_data_url=_img_data_url(ev["img"]))
        n += 1
    return {"ok": True, "seeded": n}


def reset() -> dict:
    """데모 이벤트만 정리(데모 현장명 기준). 실제 이벤트는 건드리지 않는다."""
    import json
    removed = 0
    recog = _ROOT / "data" / "recognition"
    if recog.exists():
        for fp in recog.glob("events_*.jsonl"):
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            keep = []
            for ln in lines:
                try:
                    r = json.loads(ln)
                except ValueError:
                    keep.append(ln)
                    continue
                if r.get("site") in DEMO_SITES:
                    removed += 1
                    ev = r.get("evidence")
                    if ev:
                        try:
                            (_ROOT / ev).unlink(missing_ok=True)
                        except OSError:
                            pass
                else:
                    keep.append(ln)
            fp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    return {"ok": True, "removed": removed}


def render() -> str:
    e = html.escape
    rows = "".join(
        f'<tr><td>{e(x["site"])}</td><td>{e(x["note"])}</td></tr>' for x in DEMO_EVENTS)
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT 데모 — 감지에서 서류·조치까지 자동</title><style>
  body{{margin:0;background:#000000;color:#e5e7eb;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo","Malgun Gothic",monospace}}
  .wrap{{max-width:920px;margin:0 auto;padding:28px 20px 70px}}
  .hero h1{{font-size:26px;margin:0 0 6px;line-height:1.35}} .hero h1 b{{color:#ffb000}}
  .hero p{{color:#94a3b8;font-size:15px;margin:0 0 18px}}
  .cmp{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}}
  @media(max-width:720px){{.cmp{{grid-template-columns:1fr}}}}
  .cmp .b{{border-radius:12px;padding:16px;border:1px solid #2a2a2e}}
  .cmp .before{{background:#1a1212;border-color:#7f1d1d}} .cmp .after{{background:#0f1f17;border-color:#15803d}}
  .cmp h3{{margin:0 0 8px;font-size:14px}} .cmp ul{{margin:0;padding-left:18px;font-size:13px;line-height:1.7;color:#cbd5e1}}
  .flow{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:18px 0;font-size:12.5px}}
  .flow .s{{background:#17150e;border:1px solid #2a2a2e;border-radius:999px;padding:6px 12px}}
  .flow .ar{{color:#64748b}}
  .card{{background:#0c0c0e;border:1px solid #1c1c20;border-radius:12px;padding:18px;margin:16px 0}}
  .btn{{display:inline-block;padding:12px 20px;border-radius:10px;border:1px solid #2a2a2e;background:#0e0c08;color:#e5e7eb;font-size:15px;cursor:pointer;text-decoration:none}}
  .btn.primary{{background:#8a6817;border-color:#8a6817;color:#fff;font-weight:800;font-size:16px}}
  table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}}
  td{{border-bottom:1px solid #1c1c20;padding:7px 6px}} .dim{{color:#64748b}}
  #result{{display:none;margin-top:14px}} .links a{{margin-right:10px}}
  .ok{{color:#86efac;font-weight:700}}
</style></head><body><div class="wrap">
  <div class="hero">
    <h1>중대재해처벌법, 결국 <b>서류로 증명</b>해야 합니다.<br>VIGENT는 위험을 잡는 데서 끝나지 않고 <b>서류·조치까지 자동으로 닫습니다.</b></h1>
    <p>카메라가 없어도 됩니다 — 아래 버튼으로 "위험 감지 → 법적 서류·조치 자동완성" 전 과정을 2분 안에 시연하세요.</p>
  </div>

  <div class="cmp">
    <div class="b before"><h3>❌ 지금(수작업)</h3><ul>
      <li>사람이 CCTV를 종일 들여다봄</li>
      <li>위험성평가·TBM을 엑셀·한글로 일일이 작성</li>
      <li>같은 위험요인을 서류마다 다시 입력(이중작업)</li>
      <li>사고 나면 "조치했다"는 <b>증거가 없음</b></li>
    </ul></div>
    <div class="b after"><h3>✅ VIGENT(자동)</h3><ul>
      <li>위험을 감지하면 <b>증거 사진</b> 자동 저장</li>
      <li><b>관련 법령</b> 자동 인용</li>
      <li><b>위험성평가서</b> 자동 생성(KOSHA 서식)</li>
      <li>안전관리자 <b>승인 → 감사추적</b>으로 입증</li>
    </ul></div>
  </div>

  <div class="flow">
    <span class="s">위험 감지</span><span class="ar">→</span>
    <span class="s">증거 사진</span><span class="ar">→</span>
    <span class="s">법령 인용</span><span class="ar">→</span>
    <span class="s">위험성평가서</span><span class="ar">→</span>
    <span class="s">조치 권고</span><span class="ar">→</span>
    <span class="s">승인·감사추적</span>
  </div>

  <div class="card">
    <h3 style="margin-top:0">🎬 데모 시나리오</h3>
    <div class="dim" style="font-size:13px;margin-bottom:8px">아래 5건의 위험을 감지한 상황을 주입합니다(현장명은 데모용):</div>
    <table><tbody>{rows}</tbody></table>
    <div style="margin-top:16px">
      <button class="btn primary" id="runBtn" onclick="runDemo()">🎬 데모 시나리오 실행</button>
      <button class="btn" onclick="resetDemo()">초기화</button>
    </div>
    <div id="result">
      <div class="ok" id="resultMsg"></div>
      <div class="links" style="margin-top:10px">
        <a class="btn" href="/safety/auto" target="_blank">🛡 자동처리 콘솔 보기</a>
        <a class="btn" href="/dashboard" target="_blank">📊 경영 대시보드</a>
        <a class="btn" href="/report/safety?hours=100000" target="_blank">📄 위험성평가서 자동생성</a>
      </div>
      <div class="dim" style="font-size:12.5px;margin-top:8px">→ 콘솔에서 각 위험의 <b>증거·법령·권고</b>를 보고, "위험성평가 승인·생성"을 누르면 <b>사진 박힌 평가서</b>가 나옵니다.</div>
    </div>
  </div>
  <div class="dim" style="font-size:12px">※ 데모 이벤트는 '초기화'로 깨끗이 지워집니다(실제 데이터는 보존). 보조·기록 도구이며 인증 안전장치를 대체하지 않습니다.</div>
</div>
<script>
  async function runDemo(){{
    const b=document.getElementById('runBtn'); b.disabled=true; b.textContent='주입 중…';
    try{{
      const r=await fetch('/safety/demo/seed',{{method:'POST'}}); const j=await r.json();
      document.getElementById('resultMsg').textContent='✅ '+(j.seeded||0)+'건 감지 시나리오가 주입됐습니다. 아래에서 자동 처리된 결과를 확인하세요.';
      document.getElementById('result').style.display='block';
    }}catch(e){{ alert('오류: '+e); }}
    b.disabled=false; b.textContent='🎬 데모 시나리오 실행';
  }}
  async function resetDemo(){{
    try{{ const r=await fetch('/safety/demo/reset',{{method:'POST'}}); const j=await r.json();
      document.getElementById('result').style.display='none';
      alert('초기화 완료: 데모 이벤트 '+(j.removed||0)+'건 정리');
    }}catch(e){{ alert('오류: '+e); }}
  }}
</script></body></html>"""
