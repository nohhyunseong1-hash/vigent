"""ppe_check.py — 현장별 맞춤 보호구(PPE) 착용 점검

각 현장이 "필요한 보호구"를 직접 설정(config/ppe_rules.yaml)하면, 감지된 작업자의
보호구 착용 여부를 점검해 미착용을 경고한다. 다양한 현장 배포를 위해 설정 기반.

감지 2단계:
  · YOLO 모델: 안전모·안전조끼·마스크 (모델 직접) — 빠름
  · VLM 질문: 안전화·보호장갑·보안경·방독마스크·용접면·안전대 등 — class 없이도 판단

⚠ 보조 알림이며 인증 안전장치를 대체하지 않는다. VLM·모델은 확률적이라 틀릴 수 있다.
"""
from __future__ import annotations

from typing import Any

import runtime_config

_RULES_REL = "config/ppe_rules.yaml"   # B2: 시드 경로. 실제 read/write 는 runtime_config 로(런타임=data/, 시드=config/)

# 보호구 카탈로그 — 현장이 이 중에서 '필수'를 고른다
PPE_CATALOG: list[dict[str, Any]] = [
    {"id": "hardhat", "label": "안전모", "method": "yolo",
     "miss": "no-hardhat", "have": "hardhat",
     "q": "작업자가 안전모(헬멧)를 착용했는가?"},
    {"id": "safety_vest", "label": "안전조끼", "method": "yolo",
     "miss": "no-safety-vest", "have": "safety-vest",
     "q": "작업자가 안전조끼(반사 조끼)를 착용했는가?"},
    {"id": "mask", "label": "마스크", "method": "yolo",
     "miss": "no-mask", "have": "mask",
     "q": "작업자가 마스크를 착용했는가?"},
    {"id": "safety_shoes", "label": "안전화", "method": "vlm",
     "q": "작업자가 안전화(작업용 보호 신발)를 신고 있는가?"},
    {"id": "gloves", "label": "보호장갑", "method": "vlm",
     "q": "작업자가 보호장갑을 끼고 있는가?"},
    {"id": "goggles", "label": "보안경", "method": "vlm",
     "q": "작업자가 보안경 또는 눈 보호구를 착용했는가?"},
    {"id": "respirator", "label": "방독마스크", "method": "vlm",
     "q": "작업자가 방독마스크 또는 호흡보호구를 착용했는가?"},
    {"id": "welding_mask", "label": "용접면", "method": "vlm",
     "q": "용접 작업자가 용접면(용접 보호면)을 착용했는가?"},
    {"id": "harness", "label": "안전대(하네스)", "method": "vlm",
     "q": "고소작업자가 추락방지 안전대(하네스)를 착용했는가?"},
    {"id": "ear_protection", "label": "귀마개", "method": "vlm",
     "q": "작업자가 귀마개 또는 청력보호구를 착용했는가?"},
    {"id": "face_shield", "label": "안면보호구", "method": "vlm",
     "q": "작업자가 안면보호구를 착용했는가?"},
]
_BY_ID = {p["id"]: p for p in PPE_CATALOG}
_DEFAULT_REQUIRED = ["hardhat", "safety_vest"]


def get_rules() -> dict[str, Any]:
    """현장 설정(필수 보호구 id 목록). 없으면 기본값."""
    _rules = runtime_config.read_path(_RULES_REL)   # B2: 런타임(data/) 우선 → config/ 시드 폴백
    if _rules.exists():
        try:
            import yaml
            d = yaml.safe_load(_rules.read_text(encoding="utf-8")) or {}
            req = d.get("required")
            if isinstance(req, list):
                return {"required": [r for r in req if r in _BY_ID], "site": d.get("site", "")}
        except Exception:  # noqa: BLE001
            pass
    return {"required": list(_DEFAULT_REQUIRED), "site": ""}


def save_rules(required: list[str], site: str = "") -> dict[str, Any]:
    req = [r for r in (required or []) if r in _BY_ID]
    _rules = runtime_config.runtime_path(_RULES_REL)   # B2: 런타임 write 는 항상 data/ 하위
    _rules.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        _rules.write_text(yaml.safe_dump({"site": site, "required": req}, allow_unicode=True),
                          encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "required": req, "site": site}


def _vlm_status_batch(image_bgr, items: list[dict]) -> dict[str, str]:
    """VLM 1회 호출로 보호구별 착용 상태 판정 → {id: present/missing/unknown}.
    안전 우선: 명확하지 않으면 'present'가 아니라 'unknown'(거짓 안심 방지)."""
    out = {it["id"]: "unknown" for it in items}
    if not items or image_bgr is None:
        return out
    lines = "\n".join(f"- {it['label']}:" for it in items)
    prompt = ("작업자 사진을 보고 각 보호구의 착용 여부를 판단하라. "
              "명확히 착용했으면 '착용', 명확히 안 했으면 '미착용', "
              "가려지거나 안 보이거나 확신 없으면 '불확실'. 추측 금지.\n"
              "반드시 아래 각 줄 뒤에 '착용/미착용/불확실' 중 하나만 적어라:\n" + lines)
    try:
        import rfdetr_service
        import tuning
        mt = int(tuning.val("vlm", "ppe_max_tokens", 128))
        ms = int(tuning.val("vlm", "ppe_max_side", 768))
        # PPE 단답 → 빠른 경로(작은 이미지·짧은 토큰·재시도/법령보강 없음). 값은 tuning.yaml.
        data = rfdetr_service.vlm.quick_bgr(image_bgr, prompt, max_tokens=mt, max_side=ms)
        txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                               if not str(k).startswith("_")))
    except Exception:  # noqa: BLE001
        return out
    for ln in txt.splitlines():
        for it in items:
            if it["label"] in ln:
                if "미착용" in ln or "안 착용" in ln or "없" in ln:
                    out[it["id"]] = "missing"
                elif "불확실" in ln or "불명" in ln:
                    out[it["id"]] = "unknown"
                elif "착용" in ln:
                    out[it["id"]] = "present"
                break
    return out


def check(detections: list[dict], image_bgr=None, required: list[str] | None = None,
          use_vlm: bool = True) -> dict[str, Any]:
    """필수 보호구 착용 점검(실시간 최적화: VLM은 1회 호출로 일괄).
    반환: {results:[{id,label,status,method}], missing:[...], warn}.
    status: present(착용)/missing(미착용)/unknown(판단불가)."""
    req = required if required is not None else get_rules()["required"]
    low = [str(d.get("label") or "").lower() for d in detections]
    results = []
    need_vlm = []
    for pid in req:
        item = _BY_ID.get(pid)
        if not item:
            continue
        status, via = "unknown", item["method"]
        if item["method"] == "yolo":
            if item["miss"] in low:
                status = "missing"
            elif item["have"] in low:
                status = "present"
        if status == "unknown" and use_vlm and image_bgr is not None and item.get("q"):
            need_vlm.append(item)        # VLM 일괄 처리 대상
            via = "vlm"
        results.append({"id": pid, "label": item["label"], "method": via, "status": status})
    # VLM 한 번에 — 보호구별 착용 상태 일괄 판정(불확실은 unknown 유지)
    if need_vlm:
        st = _vlm_status_batch(image_bgr, need_vlm)
        for r in results:
            if r["status"] == "unknown" and r["method"] == "vlm":
                r["status"] = st.get(r["id"], "unknown")
    missing = [r for r in results if r["status"] == "missing"]
    return {"ok": True, "results": results, "missing": missing,
            "warn": ("보호구 미착용: " + ", ".join(r["label"] for r in missing)) if missing else ""}


def render_live() -> str:
    rules = get_rules()
    chips = "".join(f'<span class="chip">{_BY_ID[pid]["label"]}</span>'
                    for pid in rules["required"] if pid in _BY_ID) \
        or '<span class="dim">설정된 필수 보호구 없음 — 먼저 설정하세요</span>'
    return _LIVE.replace("{{CHIPS}}", chips).replace("{{SITE}}", rules.get("site") or "현장")


def render() -> str:
    rules = get_rules()
    req = set(rules["required"])
    rows = ""
    for p in PPE_CATALOG:
        tag = "YOLO 직접" if p["method"] == "yolo" else "VLM 보조"
        chk = "checked" if p["id"] in req else ""
        rows += (f'<label class="item"><input type="checkbox" value="{p["id"]}" {chk}>'
                 f'<b>{p["label"]}</b><span class="m {p["method"]}">{tag}</span></label>')
    return _PAGE.replace("{{ROWS}}", rows).replace("{{SITE}}", rules.get("site", ""))


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 현장 보호구 설정</title><style>
  body{margin:0;background:#000;color:#e8e8e8;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo",monospace}
  .wrap{max-width:640px;margin:0 auto;padding:24px 20px 60px}
  h1{font-size:20px;color:#ffb000;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:16px;line-height:1.6}
  input[type=text]{background:#0a0a0c;border:1px solid #2a2a2e;color:#e8e8e8;padding:9px;border-radius:6px;width:100%;box-sizing:border-box;font-family:inherit;margin-bottom:14px}
  .item{display:flex;align-items:center;gap:10px;background:#0c0c0e;border:1px solid #1c1c20;border-radius:8px;padding:12px 14px;margin-bottom:8px;cursor:pointer}
  .item b{flex:1;font-size:15px} .item input{width:18px;height:18px}
  .m{font-size:11px;padding:3px 8px;border-radius:10px}
  .m.yolo{background:#0f2a1a;color:#34d399} .m.vlm{background:#2a1f0f;color:#d4a017}
  .btn{width:100%;padding:13px;border:1px solid #8a6817;background:#8a6817;color:#fff;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:8px}
  .dim{color:#6b7280;font-size:12px;margin-top:12px;line-height:1.6}
  #msg{margin-top:10px;font-size:14px}
</style></head><body><div class="wrap">
  <h1>🦺 현장 보호구 설정</h1>
  <div class="sub">이 현장에서 <b>필수 보호구</b>를 고르세요. 작업자가 미착용 시 경고합니다. <br>현장마다 다르게 설정 → 다양한 현장 배포 가능.</div>
  <input type="text" id="site" placeholder="현장명 (예: ○○건설 A동)" value="{{SITE}}">
  <div id="list">{{ROWS}}</div>
  <button class="btn" onclick="save()">저장</button>
  <button class="btn" style="background:#235e34;border-color:#235e34;margin-top:8px" onclick="location.href='/safety/ppe/live'">▶ 실시간 감지 시작</button>
  <div id="msg"></div>
  <div class="dim">🟢 YOLO 직접 = 모델이 바로 감지(빠름) · 🟡 VLM 보조 = AI가 보고 판단(느림·확률적)<br>
    ⚠ 보조 알림이며 인증 안전장치를 대체하지 않습니다.</div>
</div>
<script>
  async function save(){
    const req=[...document.querySelectorAll('#list input:checked')].map(c=>c.value);
    const site=document.getElementById('site').value;
    const r=await fetch('/safety/ppe/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({required:req,site})});
    const j=await r.json();
    document.getElementById('msg').innerHTML='<span style="color:#34d399">✓ 저장됨: '+(j.required||[]).length+'개 필수 보호구</span>';
  }
</script></body></html>"""


_LIVE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 실시간 보호구 감지</title><style>
  body{margin:0;background:#000;color:#e8e8e8;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo",monospace}
  .wrap{max-width:740px;margin:0 auto;padding:20px 16px 50px}
  h1{font-size:18px;color:#ffb000;margin:0 0 2px} .sub{color:#6b7280;font-size:12px;margin-bottom:12px}
  video{width:100%;border-radius:8px;background:#000;border:1px solid #1c1c20}
  .row{display:flex;gap:10px;margin:12px 0}
  .btn{flex:1;padding:13px;border-radius:8px;border:1px solid #2a2a2e;background:#0e0c08;color:#e8e8e8;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
  .btn.start{background:#8a6817;border-color:#8a6817;color:#fff}
  .chip{display:inline-block;background:#1c1c20;color:#9aa0a6;padding:4px 10px;border-radius:12px;font-size:12px;margin:2px}
  .pitem{display:flex;align-items:center;gap:10px;padding:11px 14px;border-radius:8px;margin-bottom:7px;font-size:15px;font-weight:700;border:1px solid #1c1c20}
  .present{background:#0f2a1a;color:#34d399} .missing{background:#2a0f0f;color:#ff6b6b} .unknown{background:#0c0c0e;color:#6b7280}
  .ico{font-size:18px} #banner{padding:14px;border-radius:8px;text-align:center;font-size:17px;font-weight:800;margin-bottom:10px}
  .ok{background:#0f2a1a;color:#34d399} .bad{background:#3a0f0f;color:#ff5252} .wait{background:#0c0c0e;color:#6b7280}
  .dim{color:#6b7280;font-size:12px;margin-top:10px;line-height:1.6}
</style></head><body><div class="wrap">
  <h1>🦺 실시간 보호구 감지 · {{SITE}}</h1>
  <div class="sub">필수: {{CHIPS}}</div>
  <video id="vid" autoplay playsinline muted></video>
  <div class="row">
    <button class="btn start" id="cam" onclick="toggle()">● 감지 시작</button>
    <button class="btn" id="voice" onclick="voiceOn=!voiceOn;this.classList.toggle('start',voiceOn);this.textContent=voiceOn?'🔊 음성 켬':'🔊 음성 끔'">🔊 음성 끔</button>
  </div>
  <div id="banner" class="wait">카메라를 켜세요</div>
  <div class="status" id="status"></div>
  <div class="dim">VLM이 보호구를 확인하는 데 약 5~10초 걸려 그 간격으로 갱신됩니다(근실시간).<br>⚠ 보조 알림 — 인증 안전장치 아님. 최종 확인은 안전관리자.</div>
</div>
<script>
  let stream=null,busy=false,timer=null,voiceOn=false,lastWarn='',lastT=0;
  const vid=document.getElementById('vid');
  async function toggle(){
    if(stream){ stream.getTracks().forEach(t=>t.stop()); stream=null; clearInterval(timer);
      document.getElementById('cam').textContent='● 감지 시작'; document.getElementById('cam').classList.add('start');
      banner('wait','감지 중지'); return; }
    try{ stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}}); }
    catch(e){ try{ stream=await navigator.mediaDevices.getUserMedia({video:true}); }catch(e2){ alert('카메라 실패'); return; } }
    vid.srcObject=stream; document.getElementById('cam').textContent='■ 감지 중지'; document.getElementById('cam').classList.remove('start');
    banner('wait','보호구 확인 중…'); timer=setInterval(tick,3000); tick();
  }
  function banner(c,t){ const b=document.getElementById('banner'); b.className=c; b.textContent=t; }
  function cap(){ const c=document.createElement('canvas'); c.width=vid.videoWidth||640; c.height=vid.videoHeight||480;
    if(!c.width)return null; c.getContext('2d').drawImage(vid,0,0); return c.toDataURL('image/jpeg',0.7).split(',')[1]; }
  function speak(t){ if(!voiceOn)return; const n=Date.now(); if(t===lastWarn&&n-lastT<10000)return; lastWarn=t;lastT=n;
    try{ speechSynthesis.cancel(); const u=new SpeechSynthesisUtterance(t); u.lang='ko-KR'; speechSynthesis.speak(u);}catch(e){} }
  async function tick(){
    if(busy)return; const b64=cap(); if(!b64)return; busy=true;
    try{
      const j=await (await fetch('/safety/ppe/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:b64,use_vlm:true})})).json();
      const ico={present:'✅',missing:'⚠️',unknown:'❔'};
      document.getElementById('status').innerHTML=(j.results||[]).map(r=>
        '<div class="pitem '+r.status+'"><span class="ico">'+ico[r.status]+'</span>'+r.label+
        '<span style="margin-left:auto;font-size:12px;color:#6b7280">'+({present:'착용',missing:'미착용',unknown:'확인불가'}[r.status])+'</span></div>').join('');
      if(j.missing&&j.missing.length){ banner('bad','⚠ '+j.warn); speak(j.warn); }
      else if((j.results||[]).some(r=>r.status==='present')){ banner('ok','✅ 보호구 착용 정상'); }
      else{ banner('wait','작업자·보호구 확인 중…'); }
    }catch(e){} busy=false;
  }
</script></body></html>"""
