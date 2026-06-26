"""liveguide.py — 현장 음성 안전 안내

카메라가 보는 실시간 화면을 주기적으로 분석해서, 위험·작업을 음성으로 안내한다.
  · 위험(협착·화재·보호구미착용) → 즉시 경고 음성
  · 작업 인식(용접·고소 등) → 해당 작업 안전수칙 음성

⚠ 보조 안내이며 인증 안전장치를 대체하지 않는다. 최종 판단은 작업자·관리자.
"""
from __future__ import annotations

from typing import Any

_VEH_KO = {"forklift": "지게차", "truck": "트럭", "bus": "차량", "car": "차량",
           "crane": "크레인", "excavator": "굴착기", "motorcycle": "오토바이"}


def build_guidance(detections: list[dict], use_vlm: bool, image_bgr=None) -> dict[str, Any]:
    """탐지·작업인식 → 음성 안내 메시지(speak) + 등급(urgent/info/none)."""
    import proximity
    import safety_brain
    present = [str(d.get("label") or "") for d in detections]
    low = [p.lower() for p in present]
    prox = proximity.detect(detections)
    urgent = []
    if prox:
        v = _VEH_KO.get(prox[0]["vehicle"], "차량")
        urgent.append(f"주의. {v} 작업 반경에 작업자가 접근했습니다. 거리를 유지하세요.")
    if any(l in ("fire", "smoke") for l in low):
        urgent.append("화재 또는 연기가 감지되었습니다. 즉시 확인하세요.")
    if any(l.startswith("no-") for l in low):
        urgent.append("보호구 미착용이 감지되었습니다. 안전모와 보호구를 착용하세요.")

    info = ""
    act_id = safety_brain.detect_activity(image_bgr, present, use_vlm)
    if act_id and not urgent:
        a = safety_brain.get_activity(act_id) or {}
        name = a.get("name", act_id)
        actions = a.get("actions") or []
        tip = actions[0] if actions else "안전 수칙을 지키세요."
        info = f"{name} 작업입니다. {tip}"

    speak = " ".join(urgent) if urgent else info
    level = "urgent" if urgent else ("info" if info else "none")
    npeople = sum(1 for l in low if l == "person")
    return {"ok": True, "speak": speak, "level": level,
            "activity": act_id, "person_count": npeople,
            "hazards": [u for u in urgent]}


def render() -> str:
    return _PAGE


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 현장 음성 안전 안내</title><style>
  body{margin:0;background:#000;color:#e8e8e8;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo",monospace}
  .wrap{max-width:760px;margin:0 auto;padding:22px 18px 50px}
  h1{font-size:19px;color:#ffb000;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:14px}
  video{width:100%;border-radius:8px;background:#000;border:1px solid #1c1c20}
  .row{display:flex;gap:10px;margin:12px 0}
  .btn{flex:1;padding:13px;border-radius:8px;border:1px solid #2a2a2e;background:#0e0c08;color:#e8e8e8;font-size:15px;cursor:pointer;font-weight:700;font-family:inherit}
  .btn.on{background:#235e34;border-color:#235e34;color:#fff}
  .btn.start{background:#8a6817;border-color:#8a6817;color:#fff}
  .status{padding:16px;border-radius:8px;border:1px solid #1c1c20;background:#0c0c0e;margin-top:6px;min-height:48px}
  .status .lv{font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:1px}
  .status .msg{font-size:17px;margin-top:6px;line-height:1.5}
  .urgent{color:#ff6b6b;font-weight:800} .info{color:#9fe0b0} .none{color:#6b7280}
  .dim{color:#6b7280;font-size:12px;margin-top:10px;line-height:1.6}
</style></head><body><div class="wrap">
  <h1>🔊 현장 음성 안전 안내</h1>
  <div class="sub">카메라가 보는 화면을 분석해 위험·작업 안전수칙을 <b>음성으로</b> 안내합니다.</div>
  <video id="vid" autoplay playsinline muted></video>
  <div class="row">
    <button class="btn start" id="cam" onclick="toggleCam()">● 카메라 켜기</button>
    <button class="btn" id="voice" onclick="toggleVoice()">🔊 음성 안내 끔</button>
  </div>
  <div class="status"><div class="lv" id="lv">대기</div><div class="msg none" id="msg">카메라를 켜세요</div></div>
  <div class="dim">· 위험(협착·화재·보호구) 감지 시 즉시 경고 · 작업 인식 시 안전수칙 안내<br>· 보조 안내이며 인증 안전장치를 대체하지 않습니다. (브라우저는 Chrome 권장)</div>
</div>
<script>
  let stream=null, timer=null, voiceOn=false, lastSpoke='', lastTime=0;
  const vid=document.getElementById('vid');
  async function toggleCam(){
    if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; clearInterval(timer); timer=null;
      document.getElementById('cam').textContent='● 카메라 켜기'; document.getElementById('cam').classList.add('start');
      setMsg('none','대기','카메라 꺼짐'); return; }
    try{ stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}}); }
    catch(e){ try{ stream=await navigator.mediaDevices.getUserMedia({video:true}); }catch(e2){ alert('카메라 접근 실패'); return; } }
    vid.srcObject=stream; document.getElementById('cam').textContent='■ 카메라 끄기'; document.getElementById('cam').classList.remove('start');
    setMsg('none','분석 중','화면 분석을 시작합니다…');
    timer=setInterval(analyze, 4000); analyze();
  }
  function toggleVoice(){
    voiceOn=!voiceOn; const b=document.getElementById('voice');
    b.textContent=voiceOn?'🔊 음성 안내 켬':'🔊 음성 안내 끔'; b.classList.toggle('on',voiceOn);
    if(voiceOn) speak('음성 안내를 시작합니다.', 'info', true);
  }
  function capture(){ const c=document.createElement('canvas'); c.width=vid.videoWidth||640; c.height=vid.videoHeight||480;
    if(!c.width) return null; c.getContext('2d').drawImage(vid,0,0); return c.toDataURL('image/jpeg',0.7).split(',')[1]; }
  function setMsg(cls,lv,msg){ document.getElementById('lv').textContent=lv;
    const m=document.getElementById('msg'); m.className='msg '+cls; m.textContent=msg; }
  function speak(text,level,force){
    if(!voiceOn||!text) return; const now=Date.now();
    if(!force && text===lastSpoke && now-lastTime<12000) return;       // 같은 말 12초 쿨다운
    if(!force && level!=='urgent' && now-lastTime<8000) return;        // 정보는 최소 8초 간격
    lastSpoke=text; lastTime=now;
    try{ speechSynthesis.cancel(); const u=new SpeechSynthesisUtterance(text); u.lang='ko-KR'; u.rate=1.05; speechSynthesis.speak(u); }catch(e){}
  }
  async function analyze(){
    const b64=capture(); if(!b64) return;
    let j; try{ j=await (await fetch('/safety/voice/scene',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:b64})})).json(); }catch(e){ return; }
    if(!j.ok) return;
    if(j.level==='urgent'){ setMsg('urgent','⚠ 위험 경고', j.speak); speak(j.speak,'urgent'); }
    else if(j.level==='info'){ setMsg('info','안내', j.speak); speak(j.speak,'info'); }
    else{ setMsg('none','정상', '특이 위험 없음 (사람 '+(j.person_count||0)+'명)'); }
  }
</script></body></html>"""
