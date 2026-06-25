"""incident.py — 재해 영상/사진 원인분석(보조 초안)

사고 장면을 넣으면: 탐지 + VLM 장면설명 + 지식엔진으로
  ① 무슨 상황 ② 빠진 안전조치 ③ 관련 법령 ④ 유사 중대재해 패턴 ⑤ 예방대책
을 정리한다.

⚠ 책임회피 설계: '누가 몇 % 잘못'(법적 책임 비율)은 판정하지 않는다. 원인분석 보조이며
   사실관계·법적 판단은 안전관리자·조사관·전문가가 한다.
"""
from __future__ import annotations

from typing import Any


def analyze(image_bgr, present_classes: list[str] | None = None, use_vlm: bool = False) -> dict[str, Any]:
    import safety_brain
    present = present_classes or []
    scene = ""
    if use_vlm and image_bgr is not None:
        try:
            import vlm_confirm
            scene = vlm_confirm.describe_scene(image_bgr)
        except Exception:  # noqa: BLE001
            scene = ""
    env = safety_brain.detect_environment(image_bgr, present, use_vlm)
    env_id = env["id"] if env else None
    act_id = safety_brain.detect_activity(image_bgr, present, use_vlm)
    assessment = (safety_brain.assess(act_id, present, image_bgr=image_bgr, use_vlm=use_vlm)
                  if act_id else None)
    warnings = safety_brain.accident_warnings(env_id, act_id, present)
    missing = assessment.get("missing", []) if assessment else []
    return {
        "ok": True,
        "scene": scene,
        "detected": present,
        "environment": (env["name"] if env else None),
        "activity": (assessment["activity"] if assessment else act_id),
        "missing_measures": [m["name"] for m in missing],
        "regulations": (assessment.get("regulations", []) if assessment else []),
        "accident_patterns": warnings,
        "actions": (assessment.get("actions", []) if assessment else []),
        "vlm_used": bool(use_vlm),
        "disclaimer": ("원인분석 보조 초안입니다. 비전·VLM은 확률적이라 틀릴 수 있습니다. "
                       "사실관계·법적 책임 판단은 안전관리자·조사관·전문가가 합니다. (책임 비율 판정 아님)"),
    }


def render() -> str:
    return _PAGE


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 재해 원인분석</title><style>
  body{margin:0;background:#000;color:#e8e8e8;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo",monospace}
  .wrap{max-width:760px;margin:0 auto;padding:24px 20px 60px}
  h1{font-size:20px;color:#ffb000;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:18px}
  .card{background:#0c0c0e;border:1px solid #1c1c20;padding:16px;margin-bottom:14px;border-radius:4px}
  .card h3{font-size:13px;color:#d4a017;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px}
  input[type=file]{background:#0a0a0c;border:1px solid #2a2a2e;color:#e8e8e8;padding:9px;border-radius:6px;width:100%;font-family:inherit}
  .btn{padding:10px 18px;border:1px solid #8a6817;background:#8a6817;color:#fff;border-radius:6px;font-size:14px;cursor:pointer;font-weight:700;font-family:inherit}
  label.ck{font-size:13px;color:#9aa0a6;display:inline-block;margin:8px 0}
  img.pv{max-width:100%;max-height:280px;border-radius:6px;margin-top:8px;border:1px solid #1c1c20}
  ul{margin:4px 0;padding-left:18px;font-size:13.5px;line-height:1.8;color:#cfd3d8}
  .miss{color:#fca5a5;font-weight:700} .dim{color:#6b7280;font-size:12px}
  .scene{color:#e8e8e8;font-size:14px;line-height:1.6}
</style></head><body><div class="wrap">
  <h1>🔍 재해 원인분석 (보조)</h1>
  <div class="sub">사고 사진/영상을 넣으면 상황·빠진 안전조치·법령·유사재해·예방을 정리합니다. ※ 책임 비율 판정 아님.</div>

  <div class="card">
    <input type="file" id="file" accept="image/*,video/*" onchange="preview()">
    <label class="ck"><input type="checkbox" id="vlm" checked> VLM 분석(장면 설명·없는 조치 추론, 권장)</label>
    <button class="btn" onclick="run()" style="float:right">분석</button>
    <div style="clear:both"></div>
    <img id="pv" class="pv" style="display:none">
    <video id="vid" class="pv" style="display:none" muted></video>
  </div>
  <div id="out"></div>
</div>
<script>
  let _b64=null;
  function preview(){
    const f=document.getElementById('file').files[0]; if(!f)return;
    const pv=document.getElementById('pv'), vid=document.getElementById('vid');
    if(f.type.startsWith('video')){
      vid.style.display='block'; pv.style.display='none'; vid.src=URL.createObjectURL(f);
      vid.onloadeddata=()=>{ vid.currentTime=Math.min(1, vid.duration/2); };
      vid.onseeked=()=>{ const c=document.createElement('canvas'); c.width=vid.videoWidth; c.height=vid.videoHeight;
        c.getContext('2d').drawImage(vid,0,0); _b64=c.toDataURL('image/jpeg',0.85).split(',')[1]; };
    }else{
      pv.style.display='block'; vid.style.display='none';
      const r=new FileReader(); r.onload=()=>{ pv.src=r.result; _b64=String(r.result).split(',')[1]; }; r.readAsDataURL(f);
    }
  }
  async function run(){
    if(!_b64){ alert('사진/영상을 먼저 넣으세요'); return; }
    document.getElementById('out').innerHTML='<div class="card dim">분석 중… (VLM은 수 초 걸립니다)</div>';
    const r=await fetch('/safety/incident/analyze',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({image_base64:_b64, use_vlm:document.getElementById('vlm').checked})});
    const j=await r.json();
    if(!j.ok){ document.getElementById('out').innerHTML='<div class="card">분석 실패</div>'; return; }
    const sec=(t,html)=> html?`<div class="card"><h3>${t}</h3>${html}</div>`:'';
    const regs=(j.regulations||[]).map(x=>`<li><b>${x.law||x}</b>${x.desc?' — '+x.desc:''}</li>`).join('');
    const pat=(j.accident_patterns||[]).map(x=>`<li><b>${x.accident}</b>: ${x.situation} <span class="dim">→ ${x.prevention}</span></li>`).join('');
    document.getElementById('out').innerHTML=
      sec('장면 분석', (j.scene?'<div class="scene">'+j.scene+'</div>':'<span class="dim">VLM 미사용/미인식</span>')
          +'<div class="dim" style="margin-top:6px">감지: '+((j.detected||[]).join(', ')||'-')+' · 환경: '+(j.environment||'-')+' · 작업: '+(j.activity||'-')+'</div>')
      +sec('⚠ 식별된 안전조치 미흡', (j.missing_measures&&j.missing_measures.length)?'<ul>'+j.missing_measures.map(m=>'<li class="miss">'+m+' 미확인/없음</li>').join('')+'</ul>':'<span class="dim">VLM 켜면 \'없는 조치\'까지 추론</span>')
      +sec('📖 관련 법령', regs?'<ul>'+regs+'</ul>':'')
      +sec('🔁 유사 중대재해 패턴', pat?'<ul>'+pat+'</ul>':'')
      +sec('✅ 예방대책', (j.actions&&j.actions.length)?'<ul>'+j.actions.map(a=>'<li>'+a+'</li>').join('')+'</ul>':'')
      +'<div class="card dim">'+j.disclaimer+(j.vlm_used?' · VLM 사용':' · VLM 미사용')+'</div>';
  }
</script></body></html>"""
