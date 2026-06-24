"""setup_console.py — 현장 운영 설정 콘솔(파일럿을 화면에서 세팅·운영)

site.yaml(현장·카메라)·notify.yaml(알림)을 화면에서 읽고 쓰고, 워커를 제어한다.
비개발자도 site.yaml 손편집 없이 현장을 구성하고, 알림(텔레그램/이메일/웹훅)을
설정·테스트할 수 있게 한다. 비밀(토큰·비번)은 마스킹해서 내보내고, 빈 값이면 보존한다.
"""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SITE = _ROOT / "config" / "site.yaml"
_NOTIFY = _ROOT / "config" / "notify.yaml"


def _yaml_load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _yaml_write(p: Path, data: dict) -> None:
    import yaml
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ── 현장(site.yaml) ──
def read_site() -> dict:
    c = _yaml_load(_SITE)
    return {"site": c.get("site", ""), "central_url": c.get("central_url", ""),
            "cameras": c.get("cameras", []) or []}


def write_site(data: dict) -> dict:
    cams = []
    for cam in data.get("cameras", []) or []:
        src = str(cam.get("source", "")).strip()
        if not src:
            continue
        c = {"id": str(cam.get("id") or f"cam{len(cams)+1}").strip(),
             "name": str(cam.get("name", "")).strip() or f"카메라{len(cams)+1}",
             "source": src, "fps": float(cam.get("fps", 2) or 2)}
        if cam.get("zone"):
            c["zone"] = cam["zone"]
        cams.append(c)
    out = {"site": str(data.get("site", "")).strip(),
           "central_url": str(data.get("central_url", "")).strip(),
           "cameras": cams}
    _yaml_write(_SITE, out)
    return {"ok": True, "cameras": len(cams)}


# ── 알림(notify.yaml) — 비밀은 마스킹/보존 ──
_SECRET = {"telegram_token", "smtp_pass"}


def read_notify_masked() -> dict:
    c = _yaml_load(_NOTIFY)
    out = {}
    for k in ("telegram_chat", "webhook_url", "smtp_host", "smtp_port", "smtp_user", "email_to"):
        out[k] = c.get(k, "")
    for k in _SECRET:                       # 비밀은 값 대신 '설정됨' 여부만
        out[k] = ""
        out[k + "_set"] = bool(c.get(k))
    return out


def write_notify(data: dict) -> dict:
    cur = _yaml_load(_NOTIFY)
    for k in ("telegram_chat", "webhook_url", "smtp_host", "smtp_port", "smtp_user", "email_to"):
        cur[k] = str(data.get(k, "")).strip()
    for k in _SECRET:                       # 비밀은 새 값 있을 때만 갱신(빈 값=보존)
        v = str(data.get(k, "")).strip()
        if v:
            cur[k] = v
    _yaml_write(_NOTIFY, cur)
    return {"ok": True}


def render() -> str:
    return _PAGE


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 현장 운영 설정</title><style>
  body{margin:0;background:#0b0f17;color:#e5e7eb;font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
  .wrap{max-width:860px;margin:0 auto;padding:26px 20px 70px}
  h1{font-size:21px;margin:0 0 4px} .sub{color:#94a3b8;font-size:13px;margin-bottom:18px}
  .card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:18px;margin-bottom:16px}
  .card h2{font-size:15px;margin:0 0 12px;color:#93c5fd}
  label{display:block;font-size:12.5px;color:#cbd5e1;margin:9px 0 4px}
  input{width:100%;box-sizing:border-box;background:#0b1220;border:1px solid #334155;border-radius:8px;color:#e5e7eb;padding:9px 11px;font-size:13.5px}
  .row{display:flex;gap:8px;align-items:flex-end} .row>div{flex:1}
  .cam{display:grid;grid-template-columns:1fr 1.4fr 2.4fr 0.7fr auto;gap:8px;align-items:center;margin-bottom:8px}
  .btn{padding:9px 15px;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#e5e7eb;font-size:13.5px;cursor:pointer}
  .btn.p{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:700}
  .btn.x{border-color:#7f1d1d;color:#fca5a5;padding:9px 11px}
  .st{font-size:12.5px;margin-top:8px} .ok{color:#86efac} .dim{color:#64748b}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .toast{position:fixed;right:16px;bottom:16px;background:#0f2a18;border:1px solid #15803d;color:#bbf7d0;padding:10px 14px;border-radius:8px;display:none}
</style></head><body><div class="wrap">
  <h1>⚙️ 현장 운영 설정</h1>
  <div class="sub">파일럿을 화면에서 구성·운영 — 현장·카메라·워커·알림. (site.yaml 손편집 불필요)</div>

  <div class="card">
    <h2>① 현장 · 카메라</h2>
    <label>현장명</label><input id="site" placeholder="예: ○○제조 1공장">
    <label>본사 수집 URL(선택)</label><input id="central" placeholder="비우면 로컬에만 기록">
    <label style="margin-top:12px">카메라 (source = RTSP 주소 / 비디오·이미지 경로 / 웹캠번호 0)</label>
    <div id="cams"></div>
    <button class="btn" onclick="addCam()">＋ 카메라 추가</button>
    <button class="btn p" onclick="saveSite()" style="float:right">현장 저장</button>
    <div class="st dim" id="siteSt"></div>
  </div>

  <div class="card">
    <h2>② 워커(무인 감시) 운영</h2>
    <div class="dim st">저장한 카메라로 서버가 감시를 시작합니다(브라우저 없이도 동작).</div>
    <div style="margin-top:10px">
      <button class="btn p" onclick="workers('start-all')">▶ 전체 시작</button>
      <button class="btn" onclick="workers('stop-all')">■ 전체 중지</button>
      <button class="btn" onclick="refreshWorkers()">↻ 상태</button>
    </div>
    <div class="st" id="wkSt"></div>
  </div>

  <div class="card">
    <h2>③ 알림 (위험 발생 시 담당자 통보)</h2>
    <div class="grid2">
      <div><label>텔레그램 Chat ID</label><input id="telegram_chat" placeholder="예: 123456789"></div>
      <div><label>텔레그램 Bot Token</label><input id="telegram_token" placeholder="비우면 기존 유지"></div>
    </div>
    <div class="grid2">
      <div><label>이메일 받는 주소</label><input id="email_to" placeholder="manager@site.com"></div>
      <div><label>SMTP 서버</label><input id="smtp_host" placeholder="smtp.gmail.com"></div>
    </div>
    <div class="grid2">
      <div><label>SMTP 사용자(보내는 주소)</label><input id="smtp_user" placeholder="alert@site.com"></div>
      <div><label>SMTP 비밀번호/앱비번</label><input id="smtp_pass" type="password" placeholder="비우면 기존 유지"></div>
    </div>
    <label>웹훅 URL(선택 — 경광등·슬랙 등)</label><input id="webhook_url" placeholder="https://...">
    <div style="margin-top:12px">
      <button class="btn p" onclick="saveNotify()">알림 저장</button>
      <button class="btn" onclick="testAlert()">🔔 테스트 발송</button>
      <span class="st" id="alertSt"></span>
    </div>
    <div class="dim st">※ 비밀(토큰·비번)은 화면에 표시되지 않습니다. 설정돼 있으면 'OK'로만 보여요.</div>
  </div>
  <div class="dim st" style="font-size:12px">알림 설정·현장 설정은 이 PC(config/)에만 저장됩니다. 보조·기록 도구이며 인증 안전장치를 대체하지 않습니다.</div>
</div>
<div class="toast" id="toast"></div>
<script>
  const $=id=>document.getElementById(id);
  function toast(m){const t=$('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',2200);}
  // 현장
  function camRow(c={}){
    const d=document.createElement('div');d.className='cam';
    d.innerHTML=`<input placeholder="id" value="${c.id||''}">
      <input placeholder="이름" value="${c.name||''}">
      <input placeholder="RTSP/경로/0" value="${(c.source||'').replace(/"/g,'&quot;')}">
      <input placeholder="fps" value="${c.fps||2}">
      <button class="btn x" onclick="this.parentElement.remove()">✕</button>`;
    $('cams').appendChild(d);
  }
  function addCam(){camRow();}
  async function loadSite(){
    const s=await (await fetch('/site/config')).json();
    $('site').value=s.site||'';$('central').value=s.central_url||'';
    $('cams').innerHTML='';(s.cameras||[]).forEach(camRow); if(!(s.cameras||[]).length)camRow();
  }
  async function saveSite(){
    const cams=[...$('cams').children].map(r=>{const i=r.querySelectorAll('input');
      return {id:i[0].value,name:i[1].value,source:i[2].value,fps:parseFloat(i[3].value)||2};});
    const r=await fetch('/site/config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({site:$('site').value,central_url:$('central').value,cameras:cams})});
    const j=await r.json();toast('현장 저장됨 (카메라 '+(j.cameras||0)+'대)');$('siteSt').textContent='✅ 저장됨';
  }
  // 워커
  async function workers(act){
    await fetch('/workers/'+act,{method:'POST'});toast(act==='start-all'?'워커 시작':'워커 중지');refreshWorkers();
  }
  async function refreshWorkers(){
    const d=await (await fetch('/workers')).json();const c=d.cameras||{};
    const ks=Object.keys(c);
    $('wkSt').innerHTML = ks.length? ks.map(k=>`<div class="ok">● ${c[k].name} — frames ${c[k].frames}, events ${c[k].events}${c[k].error?' ⚠ '+c[k].error:''}</div>`).join('')
      : '<span class="dim">실행 중 워커 없음</span>';
  }
  // 알림
  async function loadNotify(){
    const n=await (await fetch('/notify/config')).json();
    ['telegram_chat','email_to','smtp_host','smtp_user','webhook_url'].forEach(k=>$(k).value=n[k]||'');
    $('smtp_host').value=n.smtp_host||'';
    if(n.telegram_token_set)$('telegram_token').placeholder='설정됨(OK) — 바꿀 때만 입력';
    if(n.smtp_pass_set)$('smtp_pass').placeholder='설정됨(OK) — 바꿀 때만 입력';
  }
  async function saveNotify(){
    const b={};['telegram_chat','telegram_token','email_to','smtp_host','smtp_user','smtp_pass','webhook_url'].forEach(k=>b[k]=$(k).value);
    b.smtp_port=587;
    await fetch('/notify/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
    toast('알림 설정 저장됨');$('telegram_token').value='';$('smtp_pass').value='';loadNotify();
  }
  async function testAlert(){
    $('alertSt').textContent='발송 중…';
    const r=await fetch('/alerts/test',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({level:'high',message:'VIGENT 알림 테스트입니다'})});
    const j=await r.json();
    const ch=(j.results||[]).filter(x=>['telegram','email','webhook'].includes(x.channel));
    $('alertSt').textContent = j.delivered? '✅ 발송 성공: '+ch.filter(x=>x.sent).map(x=>x.channel).join(', ')
      : '⚠ 미발송(설정 확인): '+ch.map(x=>x.channel+(x.reason?'('+x.reason+')':'')).join(', ');
  }
  loadSite();loadNotify();refreshWorkers();
</script></body></html>"""
