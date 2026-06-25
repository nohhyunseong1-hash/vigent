"""safety_brain.py — 안전 지식 추론 엔진(지식베이스 + VLM 추론)

목표: 장면을 보고 "이 작업엔 무엇이 있어야 하는데 없다"를 추론 → 위험·법령·조치 제시.
구조(확장 가능): 작업/위험 추가 = 코드가 아니라 config/corpus/safety_knowledge.json 에 항목만 추가.

오탐 설계(핵심): 안전조치는 '확인된 부재(신뢰 감지 또는 VLM 이 '없다'고 확정)'일 때만
  missing(위험)으로 본다. 확인 불가 시 'unknown(사람 확인 필요)'로 분류해 헛알림을 막는다.
폴백: VLM 미가용이어도 지식(필수조치·법령·조치) 조회는 동작한다(절대 저하 없음).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_KB_PATH = _ROOT / "config" / "corpus" / "safety_knowledge.json"
_KB_CACHE: dict[str, Any] | None = None


def _kb() -> dict[str, Any]:
    global _KB_CACHE
    if _KB_CACHE is None:
        try:
            _KB_CACHE = json.loads(_KB_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _KB_CACHE = {"activities": []}
    return _KB_CACHE


def list_activities() -> list[dict[str, Any]]:
    return [{"id": a["id"], "name": a["name"], "aliases": a.get("aliases", [])}
            for a in _kb().get("activities", [])]


def get_activity(key: str) -> dict[str, Any] | None:
    key = (key or "").strip().lower()
    for a in _kb().get("activities", []):
        if a["id"].lower() == key or a["name"].lower() == key:
            return a
        if any(key == al.lower() or key in al.lower() for al in a.get("aliases", [])):
            return a
    return None


def _vlm_present(image_bgr, question: str) -> bool | None:
    """VLM 에 예/아니오 질문 → True(있음)/False(없음)/None(불확실·미가용). 폴백 안전."""
    if image_bgr is None:
        return None
    prompt = ("너는 산업안전 점검 보조 AI다. 아래 질문에 반드시 '예' '아니오' '불확실' 중 "
              "하나의 단어로만 답하라.\n질문: " + question)
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=prompt)
    except Exception:  # noqa: BLE001  VLM 미가용/실패 → 불확실(폴백)
        return None
    if not isinstance(data, dict) or data.get("_error"):
        return None
    txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                           if not str(k).startswith("_")))
    txt = txt.strip()
    if "아니" in txt or "없" in txt or "no" in txt.lower():
        return False
    if txt.startswith("예") or "있" in txt or "yes" in txt.lower():
        return True
    return None


def detect_activity(image_bgr=None, present_classes: list[str] | None = None,
                    use_vlm: bool = False) -> str | None:
    """장면에서 '무슨 작업인지' 스스로 인식 → activity id (불명확하면 None).
    ① VLM 분류(가능 시, 가장 유연) ② 감지신호 휴리스틱(폴백: 화재→화기, 지게차→양중 등)."""
    acts = _kb().get("activities", [])
    if not acts:
        return None
    # ① VLM 으로 작업 분류
    if use_vlm and image_bgr is not None:
        names = [a["name"] for a in acts]
        prompt = ("너는 산업안전 점검 AI다. 이 장면에서 진행 중인 작업을 아래 목록에서 하나만 골라 "
                  "그 이름만 답하라. 해당 없거나 불확실하면 '없음'이라고만 답하라.\n작업 목록: "
                  + ", ".join(names))
        try:
            import rfdetr_service
            data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=prompt)
            txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                                   if not str(k).startswith("_"))) if isinstance(data, dict) else ""
            for a in acts:
                if a["name"] in txt or any(al in txt for al in a.get("aliases", [])):
                    return a["id"]
        except Exception:  # noqa: BLE001  VLM 실패 → 신호 폴백
            pass
    # ② 감지신호 휴리스틱(화재/연기→화기작업, 지게차→양중/차량계 …)
    sig = {str(c).lower() for c in (present_classes or [])}
    for a in acts:
        if any(s.lower() in sig for s in a.get("detect_signals", [])):
            return a["id"]
    return None


def list_environments() -> list[dict[str, Any]]:
    return _kb().get("environments", [])


def detect_environment(image_bgr=None, present_classes: list[str] | None = None,
                       use_vlm: bool = False) -> dict[str, Any] | None:
    """장면에서 '어떤 작업환경인지' 스스로 인식 → 환경 dict(field_mode 포함) 또는 None.
    ① VLM 장면 분류(가능 시) ② 감지신호 휴리스틱(건설 신호 있으면 현장계열) 폴백."""
    envs = _kb().get("environments", [])
    if not envs:
        return None
    if use_vlm and image_bgr is not None:
        names = [e["name"] for e in envs]
        prompt = ("너는 산업안전 점검 AI다. 이 장면의 작업환경을 아래 중 하나로만 골라 그 이름만 답하라. "
                  "불확실하면 '불확실'이라고만 답하라.\n환경 목록: " + ", ".join(names))
        try:
            import rfdetr_service
            data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=prompt)
            txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                                   if not str(k).startswith("_"))) if isinstance(data, dict) else ""
            for e in envs:
                if e["name"] in txt or any(kw in txt for kw in e.get("keywords", [])):
                    return e
        except Exception:  # noqa: BLE001
            pass
    # 폴백: 건설/현장 신호(화재·지게차·보호구)가 보이면 '현장 계열'로 추정(사무실 아님)
    sig = {str(c).lower() for c in (present_classes or [])}
    field_signals = {"fire", "smoke", "forklift", "hardhat", "no-hardhat", "vest", "no-safety-vest"}
    if sig & field_signals:
        return next((e for e in envs if e["id"] == "construction"), None)
    return None


_CASES_CACHE: list[dict[str, Any]] | None = None


def _cases() -> list[dict[str, Any]]:
    global _CASES_CACHE
    if _CASES_CACHE is None:
        try:
            p = _ROOT / "config" / "corpus" / "accident_cases.json"
            _CASES_CACHE = json.loads(p.read_text(encoding="utf-8")).get("cases", [])
        except Exception:  # noqa: BLE001
            _CASES_CACHE = []
    return _CASES_CACHE


def accident_warnings(environment_id=None, activity_id=None, present_classes=None) -> list[dict[str, Any]]:
    """현재 맥락(환경·작업·감지객체)에 해당하는 '반복 중대재해 패턴'을 경고로 반환.
    '이 상황에서 ○○ 재해가 자주 발생 → 예방하세요' 용도. 매칭 안 되면 []."""
    present = {str(c).lower() for c in (present_classes or [])}
    out = []
    for c in _cases():
        match = (
            (environment_id and c.get("industry") == environment_id)
            or (activity_id and activity_id in c.get("activities", []))
            or bool(present & {s.lower() for s in c.get("signals", [])})
        )
        if match:
            out.append({"accident": c.get("accident", ""), "situation": c.get("situation", ""),
                        "cause": c.get("cause", ""), "prevention": c.get("prevention", "")})
    return out[:4]


def assess_context(present_classes=None, image_bgr=None, use_vlm: bool = False) -> dict[str, Any]:
    """완전 자동 — 환경 + 작업 인식 → 안전조치 점검 + 과거 중대재해 패턴 예방경고."""
    env = detect_environment(image_bgr, present_classes, use_vlm)
    act_id = detect_activity(image_bgr, present_classes, use_vlm)
    env_id = env["id"] if env else None
    # 단독작업(2인1조 위반) — 감시인 필요한 고위험 작업에 사람이 1명뿐
    solo_risk = {"confined_space", "sewer", "electrical", "diving", "hot_work"}
    pcount = sum(1 for c in (present_classes or []) if str(c).lower() == "person")
    lone = bool(act_id in solo_risk and pcount == 1)
    out: dict[str, Any] = {
        "ok": True,
        "environment": ({"id": env_id, "name": env["name"], "field_mode": env["field_mode"]} if env else None),
        "activity_detected": act_id,
        "accident_warnings": accident_warnings(env_id, act_id, present_classes),
        "lone_worker": lone,
        "person_count": pcount,
    }
    if act_id:
        out["assessment"] = assess(act_id, present_classes, image_bgr=image_bgr, use_vlm=use_vlm)
    return out


def assess(activity_key: str, present_classes: list[str] | None = None,
           image_bgr=None, use_vlm: bool = False) -> dict[str, Any]:
    """작업 + (감지된 객체 / 이미지) → 필수 안전조치 충족/부재 추론.
    반환: 작업·조치별 상태(present/missing/unknown)·위험등급·위험요인·법령·권장조치."""
    act = get_activity(activity_key)
    if not act:
        return {"ok": False, "error": f"알 수 없는 작업: {activity_key}",
                "activities": [a["id"] for a in _kb().get("activities", [])]}
    present = {str(c).lower() for c in (present_classes or [])}
    measures = []
    for m in act.get("required_measures", []):
        status, via = "unknown", "확인불가(사람 확인 필요)"
        det = [d for d in m.get("detect", []) if d.lower() in present]
        if det:
            status, via = "present", "객체감지"
        elif use_vlm and image_bgr is not None and m.get("vlm_q"):
            v = _vlm_present(image_bgr, m["vlm_q"])
            if v is True:
                status, via = "present", "VLM"
            elif v is False:
                status, via = "missing", "VLM"
            else:
                status, via = "unknown", "VLM 불확실(사람 확인)"
        measures.append({"id": m["id"], "name": m["name"], "critical": m.get("critical", False),
                         "status": status, "via": via})
    missing = [m for m in measures if m["status"] == "missing"]
    missing_crit = [m for m in missing if m["critical"]]
    unknown = [m for m in measures if m["status"] == "unknown"]
    risk = "high" if missing_crit else ("mid" if missing else "low")

    parts = []
    if missing:
        parts.append("필수조치 미흡: " + ", ".join(m["name"] for m in missing))
    if unknown:
        parts.append("확인 필요: " + ", ".join(m["name"] for m in unknown))
    if not missing and not unknown:
        parts.append("필수 안전조치 충족 확인")
    summary = f"[{act['name']}] " + " / ".join(parts)

    # RAG: 작업 + 부족조치로 관련 규정·가이드 검색해 근거 보강(폴백: 빈 목록)
    related = []
    try:
        import safety_rag
        q = act["name"] + " " + " ".join(m["name"] for m in (missing or measures))
        related = [{"title": r["title"], "text": r["text"], "source": r["source"], "type": r["type"]}
                   for r in safety_rag.retrieve(q, k=3)]
    except Exception:  # noqa: BLE001
        related = []

    return {"ok": True, "activity": act["name"], "activity_id": act["id"],
            "risk": risk, "summary": summary,
            "measures": measures, "missing": missing, "unknown": unknown,
            "hazards": act.get("hazards", []),
            "regulations": act.get("regulations", []),
            "actions": act.get("actions", []),
            "related": related,
            "vlm_used": bool(use_vlm and image_bgr is not None),
            "disclaimer": "AI 초안 — 안전관리자 확인 필요. 확인불가 항목은 사람이 직접 점검."}


# ── UI ─────────────────────────────────────────────────────────────
def render() -> str:
    import html
    opts = '<option value="auto">🤖 자동 인식(작업 스스로 판단)</option>' + "".join(
        f'<option value="{html.escape(a["id"])}">{html.escape(a["name"])}</option>'
        for a in list_activities())
    return _PAGE.replace("{{OPTS}}", opts)


_PAGE = r"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGENT · 안전 지식 추론 엔진</title><style>
  body{margin:0;background:#000000;color:#e5e7eb;font-family:"SF Mono","D2Coding","Apple SD Gothic Neo","Malgun Gothic",monospace}
  .wrap{max-width:880px;margin:0 auto;padding:26px 20px 70px}
  h1{font-size:21px;margin:0 0 4px} .sub{color:#94a3b8;font-size:13px;margin-bottom:18px}
  .card{background:#0c0c0e;border:1px solid #1c1c20;border-radius:12px;padding:18px;margin-bottom:16px}
  select,input[type=file]{background:#0a0a0c;border:1px solid #2a2a2e;border-radius:8px;color:#e5e7eb;padding:9px 11px;font-size:14px}
  .btn{padding:10px 18px;border:1px solid #8a6817;background:#8a6817;color:#fff;border-radius:8px;font-size:14px;cursor:pointer;font-weight:700}
  .btn.g{background:#0e0c08;color:#e5e7eb;border-color:#2a2a2e}
  label.ck{font-size:13px;color:#cbd5e1;margin-left:10px}
  .risk{display:inline-block;padding:3px 12px;border-radius:999px;font-weight:800;font-size:13px}
  .high{background:#7f1d1d;color:#fecaca} .mid{background:#78350f;color:#fde68a} .low{background:#14532d;color:#bbf7d0}
  table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:8px}
  td,th{border-bottom:1px solid #1c1c20;padding:8px 6px;text-align:left}
  .st-present{color:#86efac} .st-missing{color:#fca5a5;font-weight:700} .st-unknown{color:#fbbf24}
  .sec h3{font-size:14px;color:#d4a017;margin:16px 0 6px} .sec ul{margin:0;padding-left:18px;font-size:13px;line-height:1.8;color:#cbd5e1}
  .dim{color:#64748b;font-size:12px}
</style></head><body><div class="wrap">
  <h1>🧠 안전 지식 추론 엔진</h1>
  <div class="sub">작업을 고르면 <b>필수 안전조치·법령·조치</b>를 제시하고, 이미지를 넣으면 VLM이 <b>"없는 조치"를 추론</b>합니다. (확장: 지식 JSON에 작업 추가)</div>

  <div class="card">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <select id="act">{{OPTS}}</select>
      <input type="file" id="img" accept="image/*">
      <label class="ck"><input type="checkbox" id="vlm"> VLM 추론 사용(이미지의 '없는 조치' 판단)</label>
      <button class="btn" onclick="run()">점검</button>
    </div>
    <div class="dim" style="margin-top:8px">※ 이미지 없이 작업만 고르면 '필수조치 목록'을 봅니다. 이미지+VLM이면 '무엇이 없는지'까지 추론.</div>
  </div>

  <div id="out"></div>

  <div class="card">
    <h3 style="margin:0 0 8px;font-size:14px;color:#d4a017">📷 카메라 라이브 점검(현장 자동 감시)</h3>
    <div class="dim" style="margin-bottom:8px">위에서 <b>작업을 선택</b>한 뒤 시작하면, 카메라로 ~7초마다 감지→추론하고 <b>위험(부족조치)이면 자동 기록·알림</b>(자동처리 콘솔로 흐름).</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="btn" id="liveBtn" onclick="toggleLive()">▶ 라이브 점검 시작</button>
      <label class="ck"><input type="checkbox" id="liveVlm" checked> VLM 추론</label>
      <label class="ck"><input type="checkbox" id="liveLog" checked> 위험 시 자동 기록·알림</label>
    </div>
    <video id="lv" autoplay muted playsinline style="width:100%;max-width:460px;margin-top:10px;border-radius:8px;background:#000;display:none"></video>
    <div id="lstatus" class="dim" style="margin-top:8px"></div>
  </div>

  <div class="card">
    <h3 style="margin:0 0 8px;font-size:14px;color:#d4a017">🔎 안전 규정·지식 검색(RAG)</h3>
    <div style="display:flex;gap:8px">
      <input id="q" placeholder="예: 밀폐공간 환기, 용접 화재, 추락 안전대…" style="flex:1;background:#0a0a0c;border:1px solid #2a2a2e;border-radius:8px;color:#e5e7eb;padding:9px 11px;font-size:14px" onkeydown="if(event.key==='Enter')search()">
      <button class="btn g" onclick="search()">검색</button>
    </div>
    <div id="sout"></div>
  </div>
</div>
<script>
  const RKO={high:'위험 높음',mid:'주의',low:'양호'};
  const SKO={present:'있음',missing:'없음 ⚠',unknown:'확인 필요'};
  function fileToB64(f){return new Promise(r=>{if(!f)return r(null);const x=new FileReader();x.onload=()=>r(String(x.result).split(',')[1]);x.readAsDataURL(f);});}
  async function run(){
    const act=document.getElementById('act').value;
    const useVlm=document.getElementById('vlm').checked;
    const f=document.getElementById('img').files[0];
    const b64=await fileToB64(f);
    document.getElementById('out').innerHTML='<div class="card dim">분석 중…'+(useVlm&&b64?' (VLM 추론은 수 초 걸릴 수 있어요)':'')+'</div>';
    const r=await fetch('/safety/brain/assess',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({activity:act, image_base64:b64, use_vlm:useVlm})});
    const j=await r.json();
    if(!j.ok){document.getElementById('out').innerHTML='<div class="card">오류: '+(j.error||'')+'</div>';return;}
    const rows=j.measures.map(m=>`<tr><td>${m.name}${m.critical?' <span class="dim">(필수)</span>':''}</td>
      <td class="st-${m.status}">${SKO[m.status]}</td><td class="dim">${m.via}</td></tr>`).join('');
    const regs=j.regulations.map(x=>`<li><b>${x.law}</b> — ${x.desc}</li>`).join('');
    const acts=j.actions.map(x=>`<li>${x}</li>`).join('');
    document.getElementById('out').innerHTML=`<div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div style="font-size:15px;font-weight:700">${j.activity}</div>
        <span class="risk ${j.risk}">${RKO[j.risk]}</span></div>
      <div style="margin:8px 0;color:#e5e7eb">${j.summary}</div>
      <table><thead><tr><th>필수 안전조치</th><th>상태</th><th>판정근거</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="sec"><h3>⚠ 위험요인</h3><ul>${j.hazards.map(h=>'<li>'+h+'</li>').join('')}</ul></div>
      <div class="sec"><h3>📖 관련 법령(근거)</h3><ul>${regs}</ul></div>
      <div class="sec"><h3>✅ 권장 조치</h3><ul>${acts}</ul></div>
      ${(j.related&&j.related.length)?'<div class="sec"><h3>🔎 관련 지식(RAG)</h3><ul>'+j.related.map(x=>`<li><b>${x.title}</b> <span class="dim">[${x.type}]</span> — ${x.text} <span class="dim">(${x.source})</span></li>`).join('')+'</ul></div>':''}
      <div class="dim" style="margin-top:10px">${j.disclaimer}${j.vlm_used?' · VLM 추론 사용됨':' · 지식 조회(이미지/VLM 미사용)'}</div>
    </div>`;
  }
  async function search(){
    const q=document.getElementById('q').value.trim(); if(!q)return;
    document.getElementById('sout').innerHTML='<div class="dim" style="margin-top:8px">검색 중…</div>';
    const r=await fetch('/safety/brain/search?q='+encodeURIComponent(q)+'&k=5');
    const j=await r.json();
    document.getElementById('sout').innerHTML=(j.results&&j.results.length)
      ? '<table style="margin-top:8px"><tbody>'+j.results.map(x=>`<tr><td><b>${x.title}</b> <span class="dim">[${x.type}]</span><br><span style="font-size:12.5px">${x.text}</span><br><span class="dim">${x.source} · 점수 ${x.score}</span></td></tr>`).join('')+'</tbody></table>'
      : '<div class="dim" style="margin-top:8px">결과 없음</div>';
  }
  // 라이브 점검: 카메라 → 감지(/detect/frame) → 추론·기록(/safety/brain/inspect)
  let liveTimer=null, liveStream=null;
  async function toggleLive(){
    const btn=document.getElementById('liveBtn'), vid=document.getElementById('lv'), st=document.getElementById('lstatus');
    if(liveTimer){ clearInterval(liveTimer); liveTimer=null; if(liveStream)liveStream.getTracks().forEach(t=>t.stop());
      vid.style.display='none'; btn.textContent='▶ 라이브 점검 시작'; st.textContent=''; return; }
    try{ liveStream=await navigator.mediaDevices.getUserMedia({video:true}); vid.srcObject=liveStream; vid.style.display='block'; }
    catch(e){ alert('카메라 접근 실패: '+e); return; }
    btn.textContent='■ 라이브 중지'; st.textContent='시작 중…';
    const tick=async()=>{
      try{
        const c=document.createElement('canvas'); c.width=vid.videoWidth||640; c.height=vid.videoHeight||480;
        if(!c.width||!c.height) return;
        c.getContext('2d').drawImage(vid,0,0,c.width,c.height);
        const b64=c.toDataURL('image/jpeg',0.7).split(',')[1];
        const dj=await (await fetch('/detect/frame',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({image_base64:b64,ppe:true,safety_only:true})})).json();
        const present=(dj.detections||[]).map(x=>x.class);
        const ij=await (await fetch('/safety/brain/inspect',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({activity:document.getElementById('act').value, present, image_base64:b64,
            use_vlm:document.getElementById('liveVlm').checked, log:document.getElementById('liveLog').checked,
            alert:document.getElementById('liveLog').checked, site:'라이브 점검'})})).json();
        if(!ij.ok){ st.textContent='오류: '+(ij.error||''); return; }
        const cls=ij.risk==='high'?'st-missing':(ij.risk==='mid'?'st-unknown':'st-present');
        st.innerHTML=`<span class="${cls}">[${RKO[ij.risk]||ij.risk}]</span> ${ij.summary} `
          +(ij.logged?'<span class="st-missing">· 📋 기록됨</span>':'')+(ij.alerted?' · 🔔 알림':'')
          +(ij.vlm_used?'':' <span class="dim">(VLM 미가용→사람확인)</span>');
      }catch(e){ st.textContent='점검 오류'; }
    };
    tick(); liveTimer=setInterval(tick,7000);
  }
  run();
</script></body></html>"""
