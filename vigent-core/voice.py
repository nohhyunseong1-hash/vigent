"""voice.py — 음성 안전 비서(현장 키오스크)

근로자가 마이크 버튼을 누르고 안전을 물으면, 안전 지식 엔진이 답을 만들고
스피커로 읽어준다. 브라우저 Web Speech API 사용(STT: ko-KR, TTS: speechSynthesis).
프로토타입: 인터넷+Chrome 권장. 오프라인/정확도는 Whisper+로컬TTS로 교체 가능(같은 구조).
"""
from __future__ import annotations


def render() -> str:
    return _PAGE


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT 음성 안전 비서</title><style>
  body{margin:0;background:#000;color:#e8e8e8;
    font-family:"SF Mono","D2Coding","Apple SD Gothic Neo","Malgun Gothic",monospace;
    min-height:100vh;display:flex;flex-direction:column;align-items:center}
  .hdr{width:100%;text-align:center;padding:18px 0 6px;border-bottom:1px solid #5a4a18}
  .hdr .l{color:#ffb000;font-weight:800;letter-spacing:2px;font-size:20px}
  .hdr .s{color:#6b7280;font-size:12px;margin-top:4px}
  .wrap{max-width:640px;width:100%;padding:24px 20px 40px;flex:1}
  .mic{display:block;margin:18px auto;width:160px;height:160px;border-radius:50%;
    background:#0c0c0e;border:2px solid #8a6817;color:#ffb000;font-size:17px;font-weight:800;cursor:pointer;
    transition:.15s;font-family:inherit}
  .mic:hover{border-color:#ffb000}
  .mic.on{border-color:#ff3b3b;color:#ff3b3b;animation:pulse 1.1s infinite}
  @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(255,59,59,.4)}50%{box-shadow:0 0 0 18px rgba(255,59,59,0)}}
  .state{text-align:center;color:#9aa0a6;font-size:13px;min-height:18px;margin-bottom:10px}
  .pnl{background:#0c0c0e;border:1px solid #1c1c20;padding:16px;margin-top:14px;border-radius:4px}
  .pnl .t{color:#6b7280;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
  .q{color:#d4a017;font-size:15px}
  .a{color:#e8e8e8;font-size:17px;line-height:1.6}
  .src{color:#6b7280;font-size:12px;margin-top:8px;border-top:1px solid #1c1c20;padding-top:8px}
  .dis{color:#5a5042;font-size:11px;margin-top:18px;text-align:center;line-height:1.6}
  .ex{color:#6b7280;font-size:12px;text-align:center;margin-top:8px}
  .ex b{color:#8a6817}
  .warn{color:#ff9e1b;font-size:12px;text-align:center;margin-top:10px;display:none}
</style></head><body>
  <div class="hdr"><div class="l">🎤 VIGENT 음성 안전 비서</div>
    <div class="s">마이크를 누르고 안전에 대해 물어보세요</div></div>
  <div class="wrap">
    <button class="mic" id="mic" onclick="toggle()">🎤<br>누르고<br>질문</button>
    <div class="state" id="state">대기 중 — 버튼을 누르세요</div>
    <div class="ex">예: <b>"용접 작업 안전하게 하려면?"</b> · <b>"밀폐공간 들어갈 때 뭐 확인해?"</b> · <b>"추락 방지 어떻게 해?"</b></div>
    <div class="warn" id="warn">⚠ 이 브라우저는 음성인식을 지원하지 않습니다. Chrome 을 사용하세요.</div>
    <div class="pnl" id="qp" style="display:none"><div class="t">질문</div><div class="q" id="q"></div></div>
    <div class="pnl" id="ap" style="display:none"><div class="t">안전 안내</div><div class="a" id="a"></div><div class="src" id="src"></div></div>
    <div class="dis">※ 보조 안내입니다. 비전·음성 AI는 확률적이며 인증 안전장치를 대체하지 않습니다.<br>최종 판단·조치는 안전관리자 확인 하에 이뤄집니다.</div>
  </div>
<script>
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec=null, listening=false;
  const $=id=>document.getElementById(id);
  if(!SR){ $('warn').style.display='block'; $('mic').disabled=true; }
  else{
    rec=new SR(); rec.lang='ko-KR'; rec.interimResults=false; rec.maxAlternatives=1;
    rec.onresult=e=>{ const t=e.results[0][0].transcript; ask(t); };
    rec.onerror=e=>{ setState('인식 오류: '+e.error+' — 다시 시도하세요'); stop(); };
    rec.onend=()=>{ stop(); };
  }
  function setState(s){ $('state').textContent=s; }
  function toggle(){ if(!rec)return; if(listening){ rec.stop(); } else { try{ window.speechSynthesis.cancel(); rec.start(); listening=true; $('mic').classList.add('on'); setState('듣는 중… 질문하세요'); }catch(e){} } }
  function stop(){ listening=false; $('mic').classList.remove('on'); }
  async function ask(q){
    stop(); $('qp').style.display='block'; $('q').textContent=q; setState('답변 준비 중…');
    try{
      const r=await fetch('/safety/voice/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
      const j=await r.json();
      $('ap').style.display='block'; $('a').textContent=j.answer||'';
      $('src').textContent=(j.sources&&j.sources.length)?('근거: '+j.sources.map(s=>s.title+(s.source?'('+s.source+')':'')).join(' · ')):'';
      setState('답변 완료 — 다시 누르면 또 물어요');
      speak(j.answer||'');
    }catch(e){ setState('서버 오류'); }
  }
  function speak(text){
    if(!('speechSynthesis' in window)||!text)return;
    const u=new SpeechSynthesisUtterance(text); u.lang='ko-KR'; u.rate=1.0; u.pitch=1.0;
    const vs=window.speechSynthesis.getVoices(); const ko=vs.find(v=>v.lang&&v.lang.startsWith('ko'));
    if(ko)u.voice=ko;
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
  }
  if('speechSynthesis' in window){ window.speechSynthesis.onvoiceschanged=()=>{}; }
</script></body></html>"""
