"""evaluator.py — 자체 정확도 측정 도구 (정밀도·재현율)

테스트 사진을 '위험 상황(경보가 맞음)' / '정상 상황(경보 울리면 오탐)' 두 묶음으로 넣으면,
VIGENT가 각 사진에서 경보를 울렸는지 보고 실제 성능을 계산한다.

  · 재현율(Recall)   = 진짜 위험을 안 놓친 비율  = TP / (TP+FN)
  · 정밀도(Precision)= 경보가 진짜였던 비율      = TP / (TP+FP)
  · 둘 다 90% 이상이면 KOSHA 스마트 안전장치 인증 기준 후보

⚠ 통제된 자체 측정이며 공인시험을 대체하지 않는다(공인기관 KOLAS 등이 정본).
"""
from __future__ import annotations

from typing import Any

# 평가 대상(무엇을 '경보'로 볼지)
METRICS: dict[str, dict[str, str]] = {
    "proximity": {"label": "협착(차량 근접)", "desc": "지게차·차량 작업반경 안에 사람 — KOSHA 충돌방지 기준"},
    "person": {"label": "사람 감지", "desc": "사람이 보이면 감지(인체감지 기본 성능)"},
    "ppe": {"label": "보호구 미착용", "desc": "안전모·조끼·마스크 미착용"},
    "fire": {"label": "화재·연기", "desc": "불·연기"},
}


def predict(detections: list[dict], metric: str) -> bool:
    """detections 로 해당 지표의 '경보 여부'(True/False) 판정."""
    labels = [str(d.get("label") or d.get("class") or "").lower() for d in detections]
    if metric == "person":
        return any(l == "person" for l in labels)
    if metric == "ppe":
        return any(l.startswith("no-") for l in labels)
    if metric == "fire":
        return any(l in ("fire", "smoke") for l in labels)
    if metric == "proximity":
        import proximity
        return len(proximity.detect(detections)) > 0
    return False


def summarize(results: list[dict]) -> dict[str, Any]:
    """results=[{truth, pred}] → 혼동행렬 + 정밀도·재현율·F1·정확도."""
    tp = sum(1 for r in results if r["truth"] and r["pred"])
    fp = sum(1 for r in results if not r["truth"] and r["pred"])
    fn = sum(1 for r in results if r["truth"] and not r["pred"])
    tn = sum(1 for r in results if not r["truth"] and not r["pred"])
    n = len(results)
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec and rec) else None
    acc = (tp + tn) / n if n else None
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(prec * 100, 1) if prec is not None else None,
        "recall": round(rec * 100, 1) if rec is not None else None,
        "f1": round(f1 * 100, 1) if f1 is not None else None,
        "accuracy": round(acc * 100, 1) if acc is not None else None,
        "pass_90": bool(prec is not None and rec is not None and prec >= 0.9 and rec >= 0.9),
    }


def render() -> str:
    rows = "".join(f'<option value="{k}">{v["label"]} — {v["desc"]}</option>'
                   for k, v in METRICS.items())
    return _PAGE.replace("{{METRICS}}", rows)


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 정확도 측정</title><style>
  body{margin:0;background:#000;color:#e8e8e8;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo",monospace}
  .wrap{max-width:760px;margin:0 auto;padding:24px 20px 60px}
  h1{font-size:20px;color:#ffb000;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:18px;line-height:1.6}
  .card{background:#0c0c0e;border:1px solid #1c1c20;padding:16px;margin-bottom:14px;border-radius:6px}
  .card h3{font-size:13px;color:#d4a017;margin:0 0 8px}
  select,input[type=file]{background:#0a0a0c;border:1px solid #2a2a2e;color:#e8e8e8;padding:9px;border-radius:6px;width:100%;font-family:inherit;box-sizing:border-box}
  .btn{padding:11px 18px;border:1px solid #8a6817;background:#8a6817;color:#fff;border-radius:6px;font-size:14px;cursor:pointer;font-weight:700;font-family:inherit;width:100%}
  label{font-size:13px;color:#9aa0a6;display:block;margin:10px 0 4px}
  .pos{color:#34d399} .neg{color:#9aa0a6}
  .big{display:flex;gap:12px;margin:10px 0}
  .kpi{flex:1;background:#0a0a0c;border:1px solid #1c1c20;border-radius:8px;padding:14px;text-align:center}
  .kpi .v{font-size:30px;font-weight:900} .kpi .l{font-size:11px;color:#6b7280;margin-top:2px}
  .ok{color:#34d399} .bad{color:#f87171} .mid{color:#ffb000}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
  td,th{border:1px solid #1c1c20;padding:6px 8px;text-align:center} th{color:#6b7280}
  .dim{color:#6b7280;font-size:12px} #prog{color:#d4a017;font-size:12px;margin-top:6px}
  .verdict{padding:12px;border-radius:8px;margin-top:10px;font-weight:700;text-align:center}
</style></head><body><div class="wrap">
  <h1>📏 정확도 측정 (재현율·정밀도)</h1>
  <div class="sub">테스트 사진을 <b class="pos">위험 상황</b>(경보가 맞음)과 <b class="neg">정상 상황</b>(경보 울리면 오탐)으로 나눠 넣으면, VIGENT의 실제 <b>재현율·정밀도</b>를 계산합니다. ※ 자체 측정 — 공인시험 아님.</div>

  <div class="card">
    <label>① 평가 대상</label>
    <select id="metric">{{METRICS}}</select>
    <label class="pos">② 위험 상황 사진 (사람이 위험구역/장비 근접 등 — 경보가 맞는 사진)</label>
    <input type="file" id="pos" accept="image/*" multiple>
    <label class="neg">③ 정상 상황 사진 (위험 없음 — 경보 울리면 오탐인 사진)</label>
    <input type="file" id="neg" accept="image/*" multiple>
    <div style="margin-top:14px"><button class="btn" onclick="run()">측정 시작</button></div>
    <div id="prog"></div>
  </div>
  <div id="out"></div>
</div>
<script>
  function readAll(input){ return Promise.all([...input.files].map(f=>new Promise(res=>{
    const r=new FileReader(); r.onload=()=>res(String(r.result).split(',')[1]); r.readAsDataURL(f); }))); }
  async function run(){
    const metric=document.getElementById('metric').value;
    const pos=await readAll(document.getElementById('pos'));
    const neg=await readAll(document.getElementById('neg'));
    if(pos.length+neg.length===0){ alert('테스트 사진을 넣으세요'); return; }
    const items=[...pos.map(b=>({image_base64:b,truth:true})),...neg.map(b=>({image_base64:b,truth:false}))];
    document.getElementById('out').innerHTML=''; document.getElementById('prog').textContent='측정 중… '+items.length+'장';
    const r=await fetch('/safety/eval/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({metric,items})});
    const j=await r.json(); document.getElementById('prog').textContent='';
    if(!j.ok){ document.getElementById('out').innerHTML='<div class="card">측정 실패: '+(j.error||'')+'</div>'; return; }
    const s=j.summary; const cls=v=> v==null?'':(v>=90?'ok':v>=75?'mid':'bad');
    const verdict = s.pass_90
      ? '<div class="verdict ok" style="background:#0f2a1a">✅ 재현율·정밀도 모두 90% 이상 — KOSHA 인증 기준 후보! (공인시험 준비 가능)</div>'
      : '<div class="verdict bad" style="background:#2a0f0f">아직 90% 미만 — 현장 데이터로 재학습·보정 필요</div>';
    document.getElementById('out').innerHTML=
      '<div class="card"><h3>📊 결과 ('+s.n+'장)</h3>'
      +'<div class="big">'
      +'<div class="kpi"><div class="v '+cls(s.recall)+'">'+(s.recall??'-')+'%</div><div class="l">재현율(안 놓침)</div></div>'
      +'<div class="kpi"><div class="v '+cls(s.precision)+'">'+(s.precision??'-')+'%</div><div class="l">정밀도(헛알람↓)</div></div>'
      +'<div class="kpi"><div class="v '+cls(s.f1)+'">'+(s.f1??'-')+'%</div><div class="l">F1(종합)</div></div>'
      +'</div>'+verdict
      +'<table><tr><th></th><th>실제 위험</th><th>실제 정상</th></tr>'
      +'<tr><th>경보함</th><td class="ok">'+s.tp+' (맞음)</td><td class="bad">'+s.fp+' (오탐)</td></tr>'
      +'<tr><th>경보안함</th><td class="bad">'+s.fn+' (놓침)</td><td class="ok">'+s.tn+' (맞음)</td></tr></table>'
      +'<div class="dim" style="margin-top:8px">재현율=맞음/(맞음+놓침) · 정밀도=맞음/(맞음+오탐) · 90%↑가 인증 기준</div></div>'
      +'<div class="card dim">자체 측정값입니다. 공인 인증은 KOLAS 인정 시험소·한국표준협회(AI+)·한국스마트건설안전협회에서 정식 시험으로 받습니다. 사진이 많을수록(각 수십 장+) 신뢰도가 올라갑니다.</div>';
  }
</script></body></html>"""
