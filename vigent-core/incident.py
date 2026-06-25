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
  .wrap{max-width:780px;margin:0 auto;padding:24px 20px 60px}
  h1{font-size:20px;color:#ffb000;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:18px}
  .card{background:#0c0c0e;border:1px solid #1c1c20;padding:16px;margin-bottom:14px;border-radius:4px}
  .card h3{font-size:13px;color:#d4a017;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px}
  input[type=file]{background:#0a0a0c;border:1px solid #2a2a2e;color:#e8e8e8;padding:9px;border-radius:6px;width:100%;font-family:inherit}
  .btn{padding:10px 18px;border:1px solid #8a6817;background:#8a6817;color:#fff;border-radius:6px;font-size:14px;cursor:pointer;font-weight:700;font-family:inherit}
  label.ck{font-size:13px;color:#9aa0a6;display:inline-block;margin:8px 0}
  img.pv,video.pv{max-width:100%;max-height:340px;border-radius:6px;margin-top:8px;border:1px solid #1c1c20;background:#000;width:100%}
  ul{margin:4px 0;padding-left:18px;font-size:13.5px;line-height:1.8;color:#cfd3d8}
  .miss{color:#fca5a5;font-weight:700} .dim{color:#6b7280;font-size:12px}
  .scene{color:#e8e8e8;font-size:14px;line-height:1.6}
  /* 위험도 타임라인 */
  .tl{display:flex;gap:1px;height:38px;margin-top:8px;cursor:pointer;align-items:flex-end}
  .tl .b{flex:1;background:#1c1c20;min-height:3px;border-radius:1px 1px 0 0}
  .tlx{display:flex;justify-content:space-between;color:#6b7280;font-size:10px;margin-top:2px}
  .peak{background:#3a1414;border:1px solid #8f2820;padding:8px 12px;border-radius:6px;margin-top:8px}
  .peak b{color:#ff6b6b}
  #prog{color:#d4a017;font-size:12px;margin-top:6px}
</style></head><body><div class="wrap">
  <h1>🔍 재해 원인분석 (보조)</h1>
  <div class="sub">사고 영상을 넣으면 <b>전체를 훑어 '위험이 발생한 시점'</b>을 찾아 그 순간으로 점프하고, 원인·빠진조치·법령·예방을 정리합니다. ※ 책임 비율 판정 아님.</div>

  <div class="card">
    <input type="file" id="file" accept="image/*,video/*" onchange="preview()">
    <label class="ck"><input type="checkbox" id="vlm" checked> VLM 분석(장면 설명·없는 조치 추론, 권장)</label>
    <button class="btn" onclick="run()" style="float:right">분석</button>
    <div style="clear:both"></div>
    <img id="pv" class="pv" style="display:none">
    <video id="vid" class="pv" style="display:none" controls muted playsinline></video>
    <div id="tlwrap" style="display:none">
      <div class="dim" style="margin-top:10px">위험도 타임라인(클릭하면 그 시점으로 이동):</div>
      <div class="tl" id="tl"></div>
      <div class="tlx"><span>0s</span><span id="tlend"></span></div>
    </div>
    <div id="prog"></div>
  </div>
  <div id="out"></div>
</div>
<script>
  let _b64=null, _isVideo=false;
  function capFrame(vid){ const c=document.createElement('canvas'); c.width=vid.videoWidth; c.height=vid.videoHeight;
    c.getContext('2d').drawImage(vid,0,0); return c.toDataURL('image/jpeg',0.8).split(',')[1]; }
  function seekTo(vid,t){ return new Promise(res=>{ const h=()=>{ vid.removeEventListener('seeked',h); res(); }; vid.addEventListener('seeked',h); vid.currentTime=t; }); }
  function ko(c){ const m={person:'사람',forklift:'지게차',truck:'트럭',car:'차량',bus:'버스',fire:'화재',smoke:'연기','NO-Hardhat':'안전모 미착용','NO-Mask':'마스크 미착용','NO-Safety-Vest':'안전조끼 미착용',Hardhat:'안전모'}; return m[c]||c; }
  // 위험요인에 박스 그리기(위험=빨강, 일반=앰버)
  function drawAnnotated(b64, boxes){
    return new Promise(res=>{
      const img=new Image();
      img.onload=()=>{
        const c=document.createElement('canvas'); c.width=img.naturalWidth||640; c.height=img.naturalHeight||480;
        const x=c.getContext('2d'); x.drawImage(img,0,0);
        x.lineWidth=Math.max(2,c.width/280); x.font='bold '+Math.max(13,Math.round(c.width/42))+'px sans-serif';
        (boxes||[]).forEach(b=>{
          const bb=b.bbox; const px=bb[0]*c.width, py=bb[1]*c.height, pw=(bb[2]-bb[0])*c.width, ph=(bb[3]-bb[1])*c.height;
          const col=b.hazard?'#ff3b3b':'#ffb000';
          x.strokeStyle=col; x.strokeRect(px,py,pw,ph);
          const lbl=(b.hazard?'⚠ ':'')+ko(b.class); const tw=x.measureText(lbl).width+8;
          x.fillStyle=col; x.fillRect(px, Math.max(0,py-22), tw, 22);
          x.fillStyle=b.hazard?'#fff':'#000'; x.fillText(lbl, px+4, Math.max(15,py-6));
        });
        res(c.toDataURL('image/jpeg',0.85));
      };
      img.onerror=()=>res(null);
      img.src='data:image/jpeg;base64,'+b64;
    });
  }
  function preview(){
    const f=document.getElementById('file').files[0]; if(!f)return;
    const pv=document.getElementById('pv'), vid=document.getElementById('vid');
    document.getElementById('tlwrap').style.display='none'; document.getElementById('out').innerHTML='';
    if(f.type.startsWith('video')){
      _isVideo=true; vid.style.display='block'; pv.style.display='none'; vid.src=URL.createObjectURL(f);
    }else{
      _isVideo=false; pv.style.display='block'; vid.style.display='none';
      const r=new FileReader(); r.onload=()=>{ pv.src=r.result; _b64=String(r.result).split(',')[1]; }; r.readAsDataURL(f);
    }
  }
  async function run(){
    const vlm=document.getElementById('vlm').checked;
    if(_isVideo){ await runVideo(vlm); } else { if(!_b64){alert('파일을 넣으세요');return;} await analyzeFrame(_b64, vlm, null); }
  }
  async function runVideo(vlm){
    const vid=document.getElementById('vid'); const dur=vid.duration||0;
    if(!dur){ alert('영상 로딩 중입니다. 잠시 후 다시'); return; }
    const N=Math.min(16, Math.max(6, Math.round(dur))); // 1초당 1프레임(최대16)
    document.getElementById('tlwrap').style.display='block';
    document.getElementById('tlend').textContent=dur.toFixed(0)+'s';
    const tl=document.getElementById('tl'); tl.innerHTML='';
    const bars=[]; for(let i=0;i<N;i++){ const b=document.createElement('div'); b.className='b'; tl.appendChild(b); bars.push(b); }
    const frames=[];
    for(let i=0;i<N;i++){
      const t=dur*i/(N-1); await seekTo(vid,t); const b64=capFrame(vid);
      document.getElementById('prog').textContent='위험요인 탐색 중… '+(i+1)+'/'+N;
      let risk={score:0,hazards:[]};
      try{ risk=await (await fetch('/safety/incident/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:b64})})).json(); }catch(e){}
      frames.push({t,b64,risk});
      const h=Math.min(38, 4+risk.score*0.6);
      bars[i].style.height=h+'px';
      bars[i].style.background= risk.score>=55?'#ff3b3b': risk.score>=25?'#ffb000':'#2a4a2a';
      bars[i].title=t.toFixed(1)+'s · 위험도 '+risk.score+(risk.hazards.length?' ('+risk.hazards.join(',')+')':'');
      bars[i].onclick=()=>{ vid.currentTime=t; vid.play(); };
    }
    document.getElementById('prog').textContent='';
    const peak=frames.reduce((a,b)=> b.risk.score>a.risk.score?b:a, frames[0]);
    vid.currentTime=peak.t;  // 위험 발생 시점으로 점프
    const peakHtml = peak.risk.score>0
      ? '<div class="peak">⚠ 위험요인 발생 추정 시점: <b>'+peak.t.toFixed(1)+'초</b> · '+(peak.risk.hazards.join(', ')||'위험 신호')+' (위험도 '+peak.risk.score+')<br><span class="dim">위 영상이 그 시점으로 이동했습니다. 재생해 확인하세요.</span></div>'
      : '<div class="peak dim">뚜렷한 위험요인 시점을 못 찾음(영상 화질·각도 또는 위험 신호 미검출)</div>';
    document.getElementById('out').innerHTML='<div class="card"><h3>⏱ 위험 발생 시점</h3>'+peakHtml+'</div>';
    await analyzeFrame(peak.b64, vlm, peak.t);  // 그 시점 정밀 원인분석
  }
  async function analyzeFrame(b64, vlm, t){
    const pre=document.getElementById('out').innerHTML;
    document.getElementById('out').innerHTML=pre+'<div class="card dim">원인 분석 중…'+(vlm?' (VLM 수 초)':'')+'</div>';
    const j=await (await fetch('/safety/incident/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:b64, use_vlm:vlm})})).json();
    if(!j.ok){ document.getElementById('out').innerHTML=pre+'<div class="card">분석 실패</div>'; return; }
    const sec=(tt,html)=> html?`<div class="card"><h3>${tt}</h3>${html}</div>`:'';
    const regs=(j.regulations||[]).map(x=>`<li><b>${x.law||x}</b>${x.desc?' — '+x.desc:''}</li>`).join('');
    const pat=(j.accident_patterns||[]).map(x=>`<li><b>${x.accident}</b>: ${x.situation} <span class="dim">→ ${x.prevention}</span></li>`).join('');
    const annotated=await drawAnnotated(b64, j.boxes||[]);  // 위험요인 박스 표시
    const imgHtml=annotated?'<img src="'+annotated+'" style="max-width:100%;width:100%;border-radius:6px;border:1px solid #1c1c20;margin-bottom:8px"><div class="dim" style="margin-bottom:6px">🔴 빨강=위험요인 · 🟡 앰버=감지객체</div>':'';
    document.getElementById('out').innerHTML=pre+
      sec('🔍 위험요인 표시 + 장면 분석'+(t!=null?' ('+t.toFixed(1)+'초)':''), imgHtml+(j.scene?'<div class="scene">'+j.scene+'</div>':'<span class="dim">VLM 미사용/미인식</span>')
          +'<div class="dim" style="margin-top:6px">감지: '+((j.detected||[]).join(', ')||'-')+' · 환경: '+(j.environment||'-')+' · 작업: '+(j.activity||'-')+'</div>')
      +sec('⚠ 재해 원인(빠진 안전조치)', (j.missing_measures&&j.missing_measures.length)?'<ul>'+j.missing_measures.map(m=>'<li class="miss">'+m+' 미확인/없음</li>').join('')+'</ul>':'<span class="dim">VLM 켜면 \'없는 조치\'까지 추론</span>')
      +sec('📖 관련 법령', regs?'<ul>'+regs+'</ul>':'')
      +sec('🔁 유사 중대재해 패턴', pat?'<ul>'+pat+'</ul>':'')
      +sec('✅ 예방 방법', (j.actions&&j.actions.length)?'<ul>'+j.actions.map(a=>'<li>'+a+'</li>').join('')+'</ul>':'')
      +'<div class="card dim">'+j.disclaimer+(j.vlm_used?' · VLM 사용':' · VLM 미사용')+'</div>';
  }
</script></body></html>"""
