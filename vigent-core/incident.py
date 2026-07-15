"""incident.py — 재해 영상/사진 원인분석(보조 초안)

사고 장면을 넣으면: 탐지 + VLM 장면설명 + 지식엔진으로
  ① 무슨 상황 ② 빠진 안전조치 ③ 관련 법령 ④ 유사 중대재해 패턴 ⑤ 예방대책
을 정리한다.

⚠ 책임회피 설계: '누가 몇 % 잘못'(법적 책임 비율)은 판정하지 않는다. 원인분석 보조이며
   사실관계·법적 판단은 안전관리자·조사관·전문가가 한다.
"""
from __future__ import annotations

from typing import Any

_ACCIDENT_PROMPT = (
    "너는 산업재해 조사관 AI다. 이 현장/CCTV 사진을 보고 아래 JSON으로만 답하라.\n"
    '{"work":"무슨 작업을 하는 장면인지 한국어로","accident_type":"재해유형(끼임/추락/부딪힘/감전/화재/질식/전도/낙하물/무너짐/없음 중 하나)",'
    '"what_happened":"벌어지는(또는 임박한) 상황을 한 문장으로","cause":"추정 원인","evidence":"그렇게 판단한 근거"}\n'
    "불확실한 값은 '불명확'이라고 쓰라. 다른 설명 문장 없이 JSON만 출력."
)
_ACCIDENT_KEYS = ("work", "accident_type", "what_happened", "cause", "evidence")


def _parse_accident(text_or_dict) -> dict[str, Any] | None:
    """VLM/LLM 응답(텍스트 또는 dict) → 사고분석 dict. 파싱 실패면 None. (OpenAI·로컬 공용)"""
    import json
    import re
    obj = None
    if isinstance(text_or_dict, dict):
        if any(k in text_or_dict for k in _ACCIDENT_KEYS):
            obj = text_or_dict
        else:  # {"raw": 원문텍스트} 형태면 한번 더 파싱
            raw = text_or_dict.get("raw")
            m = re.search(r"\{.*\}", str(raw), re.S) if raw else None
            if m:
                try:
                    obj = json.loads(m.group(0))
                except Exception:  # noqa: BLE001
                    obj = None
    else:
        m = re.search(r"\{.*\}", str(text_or_dict or ""), re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:  # noqa: BLE001
                obj = None
    if not isinstance(obj, dict):
        return None
    return {k: str(obj.get(k, "") or "") for k in _ACCIDENT_KEYS}


def _openai_accident(image_bgr) -> tuple[dict[str, Any] | None, str | None]:
    """OpenAI 비전으로 사고분석(OPENAI_API_KEY 있을 때만) → (dict|None, backend|None). 실패 시 (None,None)."""
    if image_bgr is None:
        return None, None
    try:
        import llm_provider
        text, backend = llm_provider.reason_vision(image_bgr, _ACCIDENT_PROMPT)
        if not text:
            return None, None
        return _parse_accident(text), backend
    except Exception:  # noqa: BLE001
        return None, None


def _vlm_accident(image_bgr) -> dict[str, Any] | None:
    """로컬 MLX VLM 에게 '무슨 작업/어떤 재해/원인'을 직접 물음(폴백 경로)."""
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=_ACCIDENT_PROMPT)
        return _parse_accident(data) if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def infer_cause(hazard_list: list[dict[str, Any]] | None = None, environment: str | None = None,
                activity: str | None = None, missing_measures: list[str] | None = None,
                related: list[dict[str, Any]] | None = None,
                behaviors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """신뢰 가능한 사실(hazard_list·환경·작업·빠진조치·유사사례)에서 직접/근본원인을 유도.
    - 결정적 초안(규칙 기반, 모델 무관·항상 동작) → llm_provider(OpenAI/Claude) 키 있으면 폐쇄형으로 종합, 실패 시 초안 폴백.
    - 숫자·책임비율·법조항 날조 금지(규칙 7). 반환 {direct, root, source}."""
    hazard_list = hazard_list or []
    missing_measures = missing_measures or []
    related = related or []
    behaviors = behaviors or []
    haz = [str(h.get("항목", "")) for h in hazard_list if h.get("항목")]
    act = (activity or "").strip() or "작업"

    # ── 결정적 초안(규칙) ──
    zone = [h for h in haz if ("침입" in h or "위험구역" in h)]
    ppe = [h.replace(" 미착용", "") for h in haz if "미착용" in h]
    dparts: list[str] = []
    if zone:
        dparts.append("위험구역 접근")
    if ppe:
        dparts.append("·".join(ppe) + " 미착용")
    if dparts:
        direct = f"{' 및 '.join(dparts)} 상태에서 {act} 진행."
    elif missing_measures:
        direct = f"{', '.join(missing_measures[:4])} 미확인/미조치 상태에서 {act} 진행."
    else:
        direct = "불명확(탐지된 위험 항목 없음 — 안전관리자 확인 필요)."
    roots: list[str] = []
    if zone:
        roots.append("위험구역 출입통제·방호 미흡")
    if ppe:
        roots.append("보호구 착용 관리·점검 미흡")
    roots.append("작업 전 위험성 인지·안전보건교육 부족")
    root = "관리적 근본원인(추정): " + ", ".join(roots) + "."
    draft = {"direct": direct, "root": root, "source": "규칙"}

    # ── llm_provider(OpenAI/Claude, 키 있을 때) 폐쇄형 종합, 실패·키없음이면 규칙 초안 폴백 ──
    try:
        import json
        import re

        import llm_provider
        facts = (f"확정 위험(CNN 탐지): {', '.join(haz) or '없음'}\n"
                 f"환경: {environment or '불명확'}\n작업: {act}\n"
                 f"빠진 안전조치: {', '.join(missing_measures) or '없음'}\n"
                 f"유사 재해사례: {', '.join(str(r.get('title', '')) for r in related[:3]) or '없음'}\n"
                 f"관찰 행동: {', '.join(str(b.get('label', '')) for b in behaviors[:3]) or '없음'}")
        system = ("너는 한국 산업안전 재해원인 분석가다. 아래 '확인된 사실'만 근거로 "
                  "직접원인과 근본원인을 각각 1~2문장 한국어로 작성하라. "
                  "사실에 없는 것·법조항·책임비율(누가 몇 %)을 지어내지 마라. 불명확하면 불명확이라 하라. "
                  '아래 JSON 하나만 출력: {"direct":"...","root":"..."}')
        # 한국어 오염 가드는 llm_provider 공용층에서 처리(중국어 누출 시 (None,None) 폴백) — 중복 로직 제거
        text, backend = llm_provider.reason_text("확인된 사실:\n" + facts, system)
        if text:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                obj = json.loads(m.group(0))
                d = str(obj.get("direct", "")).strip()
                r = str(obj.get("root", "")).strip()
                if d or r:
                    return {"direct": d or draft["direct"], "root": r or draft["root"],
                            "source": backend or "LLM"}
    except Exception:  # noqa: BLE001  LLM/파싱 실패 → 결정적 초안 폴백(저하 0)
        pass
    return draft


def analyze(image_bgr, present_classes: list[str] | None = None, use_vlm: bool = False,
            detections: list[dict[str, Any]] | None = None, in_danger_zone: bool = False) -> dict[str, Any]:
    import safety_brain
    present = present_classes or []
    # 결정적 위험목록층(규칙 기반, 모델 무관) — VLM 사용여부와 독립. detections 없으면 present 라벨로 구성.
    _dets = detections if detections is not None else [{"label": c} for c in present]
    try:
        import hazard_rules
        hazard_list = hazard_rules.build_hazard_list(_dets, in_danger_zone)
    except Exception:  # noqa: BLE001
        hazard_list = []
    scene = ""
    ai = None
    shared = None
    engine = None
    if use_vlm and image_bgr is not None:
        # ★ 로컬 우선(영상 불유출 원칙): 장면·사고분석을 먼저 로컬 MLX 로 확보한다.
        #   클라우드(OpenAI)는 VIGENT_CLOUD_VLM=1 명시 opt-in 일 때만 시도하고 성공 시 덮어씀(데모/내부개발 전용, 상용 미포함).
        import os as _os
        # 장면·환경·작업 재사용용 통합이해(MLX) — scene/shared 확보(safety_brain 재사용).
        try:
            import scene_vlm
            shared = scene_vlm.understand(image_bgr, detections=_dets, in_danger_zone=in_danger_zone)
        except Exception:  # noqa: BLE001
            shared = None
        if shared:
            scene = shared.get("scene", "")
        else:  # 통합 실패 시 장면설명만 개별 호출
            try:
                import vlm_confirm
                scene = vlm_confirm.describe_scene(image_bgr)
            except Exception:  # noqa: BLE001
                scene = ""
        # ai(사고분석) 로컬 우선(shared 재사용, 없으면 개별 호출)
        if shared and (any(shared.get(k) for k in ("accident_type", "what_happened", "cause", "evidence"))
                       or shared.get("activity")):
            ai = {"work": shared.get("activity", ""),
                  "accident_type": shared.get("accident_type", ""),
                  "what_happened": shared.get("what_happened", ""),
                  "cause": shared.get("cause", ""),
                  "evidence": shared.get("evidence", "")}
            engine = "로컬 MLX"
        else:
            ai = _vlm_accident(image_bgr)
            if ai:
                engine = "로컬 MLX"
        # 클라우드는 opt-in(VIGENT_CLOUD_VLM=1)일 때만 — reason_vision 게이트와 이중 안전. 성공 시 우선 사용.
        if _os.getenv("VIGENT_CLOUD_VLM") == "1":
            cloud_ai, cloud_engine = _openai_accident(image_bgr)
            if cloud_ai is not None:
                ai, engine = cloud_ai, cloud_engine
    env = safety_brain.detect_environment(image_bgr, present, use_vlm, shared=shared)
    env_id = env["id"] if env else None
    act_id = safety_brain.detect_activity(image_bgr, present, use_vlm, shared=shared)
    assessment = (safety_brain.assess(act_id, present, image_bgr=image_bgr, use_vlm=use_vlm, shared=shared)
                  if act_id else None)
    warnings = safety_brain.accident_warnings(env_id, act_id, present)
    missing = assessment.get("missing", []) if assessment else []
    behaviors = []
    try:
        import behavior as _bhv
        behaviors = _bhv.analyze(image_bgr, use_vlm=use_vlm, shared=shared).get("behaviors", [])
    except Exception:  # noqa: BLE001
        behaviors = []
    # 관련 법령·중대재해 사례(RAG 의미검색) — 장면·행동·빠진조치로 근거 보강
    related = []
    try:
        import safety_rag
        # 영어 감지라벨 → 한국어(한국어 임베딩 모델이 이해하도록)
        _cls_ko = {"NO-Hardhat": "안전모 미착용", "Hardhat": "안전모", "NO-Safety-Vest": "안전조끼 미착용",
                   "Safety-Vest": "안전조끼", "NO-Mask": "마스크 미착용", "Mask": "마스크",
                   "NO-Gloves": "장갑 미착용", "Gloves": "장갑", "NO-Goggles": "보안경 미착용",
                   "Goggles": "보안경", "NO-Boots": "안전화 미착용", "Boots": "안전화",
                   "Person": "작업자", "fire": "화재", "smoke": "연기", "forklift": "지게차"}
        present_ko = [_cls_ko.get(c, c) for c in present]
        q_parts = ([scene] + [b.get("label", "") for b in behaviors]
                   + [m["name"] for m in missing] + present_ko)
        if assessment:
            q_parts.append(assessment.get("activity", "") or "")
        query = " ".join(p for p in q_parts if p).strip()
        if query:
            related = safety_rag.retrieve(query, k=4)
    except Exception:  # noqa: BLE001
        related = []
    # 원인 유도(사실 기반, VLM 사용여부와 독립·항상 생성)
    cause_analysis = infer_cause(
        hazard_list, (env["name"] if env else None),
        (assessment["activity"] if assessment else act_id),
        [m["name"] for m in missing], related, behaviors)
    # VLM cause 가 비었거나 '불명확'이면 사실 기반 직접원인으로 대체/보강
    if ai is not None:
        _c = (ai.get("cause") or "").strip()
        if not _c or "불명확" in _c:
            ai["cause"] = cause_analysis["direct"]
    return {
        "ok": True,
        "scene": scene,
        "ai_analysis": ai,
        "engine": engine,             # 실제 사용 비전 엔진(OpenAI-vision:... / 로컬 MLX / None)
        "hazard_list": hazard_list,   # 결정적 위험목록(규칙층, 커버리지 100% — VLM 누락과 무관)
        "cause_analysis": cause_analysis,   # 사실 기반 직접/근본원인(규칙 폴백·항상 존재)
        "behaviors": behaviors,
        "detected": present,
        "environment": (env["name"] if env else None),
        "activity": (assessment["activity"] if assessment else act_id),
        "missing_measures": [m["name"] for m in missing],
        "regulations": (assessment.get("regulations", []) if assessment else []),
        "related": related,
        "accident_patterns": warnings,
        "actions": (assessment.get("actions", []) if assessment else []),
        "vlm_used": bool(use_vlm),
        "disclaimer": ("원인분석 보조 초안입니다. 비전·VLM은 확률적이라 틀릴 수 있습니다. "
                       "사실관계·법적 책임 판단은 안전관리자·조사관·전문가가 합니다. (책임 비율 판정 아님)"),
    }


def render() -> str:
    import labels
    return _PAGE.replace("{{LABELS_KO}}", labels.js_snippet())


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
  // 모션 시그니처(32x32 흑백) — 프레임 간 급변(사고 순간) 감지용
  function frameSig(vid){ const c=document.createElement('canvas'); c.width=32; c.height=32;
    const x=c.getContext('2d'); x.drawImage(vid,0,0,32,32); const d=x.getImageData(0,0,32,32).data;
    const g=new Float32Array(1024); for(let i=0;i<1024;i++) g[i]=(d[i*4]+d[i*4+1]+d[i*4+2])/3; return g; }
  function sigDiff(a,b){ if(!a||!b) return 0; let s=0; for(let i=0;i<a.length;i++) s+=Math.abs(a[i]-b[i]); return s/a.length; }
  function seekTo(vid,t){ return new Promise(res=>{ const h=()=>{ vid.removeEventListener('seeked',h); res(); }; vid.addEventListener('seeked',h); vid.currentTime=t; }); }
  {{LABELS_KO}}   // 라벨 한국어맵 단일 소스(labels.py) 주입 — ko() 정의
  // 위험요인에 박스 그리기(위험=빨강, 일반=앰버) + 라벨 겹침 회피(밀집 현장 가독성)
  function drawAnnotated(b64, boxes){
    return new Promise(res=>{
      const img=new Image();
      img.onload=()=>{
        const c=document.createElement('canvas'); c.width=img.naturalWidth||640; c.height=img.naturalHeight||480;
        const x=c.getContext('2d'); x.drawImage(img,0,0);
        const fpx=Math.max(13,Math.round(c.width/42)), lh=fpx+8;
        x.lineWidth=Math.max(2,c.width/280); x.font='bold '+fpx+'px sans-serif'; x.textBaseline='top';
        const bs=(boxes||[]).map(b=>{ const bb=b.bbox;
          return {b, px:bb[0]*c.width, py:bb[1]*c.height, pw:(bb[2]-bb[0])*c.width, ph:(bb[3]-bb[1])*c.height}; });
        // 1) 박스 외곽선 먼저(라벨이 항상 위에 얹히도록)
        bs.forEach(o=>{ x.strokeStyle=o.b.hazard?'#ff3b3b':'#ffb000'; x.strokeRect(o.px,o.py,o.pw,o.ph); });
        // 2) 라벨 배치 계산 — 후보를 원위치→아래→위 번갈아 탐색(하단 겹침 해소).
        //    배치(자리 선점) 우선순위: hazard(⚠ 미착용) > 사람 > 나머지. ★ 원본 bs 순서와
        //    그리기 z-order 는 보존 — 인덱스 사본만 정렬해 배치하고 결과는 bs 순서 slot 에 되꽂는다.
        const placed=[]; const slot=new Array(bs.length);
        const hit=(r)=>placed.some(p=>!(r.x+r.w<=p.x||p.x+p.w<=r.x||r.y+r.h<=p.y||p.y+p.h<=r.y));
        const prio=(o)=> o.b.hazard?0 : (String(o.b.class||'').toLowerCase()==='person'?1:2);
        const order=bs.map((o,i)=>i).sort((a,b)=> prio(bs[a])-prio(bs[b]) || a-b);  // 안정 정렬
        order.forEach(i=>{
          const o=bs[i];
          const lbl=(o.b.hazard?'⚠ ':'')+ko(o.b.class); const tw=x.measureText(lbl).width+8;
          let lx=o.px; if(lx+tw>c.width) lx=Math.max(0,c.width-tw);   // 우측 이탈 → 화면 안
          const ly0=o.py-lh;                                          // 원위치(박스 바로 위)
          const base=(ly0<0)?o.py+2:ly0;                              // 상단 이탈 → 박스 안쪽에서 시작
          let ly=null;
          for(let k=0; k<60 && ly===null; k++){
            for(const cy of (k===0?[base]:[base+k*lh, base-k*lh])){   // 원위치→아래→위 번갈아
              if(cy<0 || cy+lh>c.height) continue;                    // 화면 밖 후보 제외
              if(!hit({x:lx,y:cy,w:tw,h:lh})){ ly=cy; break; }
            }
          }
          if(ly===null) ly=Math.max(0,Math.min(base,c.height-lh));    // 최후: 원위치 클램프(겹침 감수)
          const r={x:lx,y:ly,w:tw,h:lh}; placed.push(r);
          slot[i]={o, lbl, tw, r, moved:(Math.abs(ly-ly0)>=lh||lx!==o.px)};
        });
        const items=slot;   // 원본 bs 순서 그대로 → leaders/라벨 그리기 z-order 보존
        // 3) 연결선(leader) 먼저 — 밀린 라벨↔박스 상단중앙을 잇는다(라벨에 덮이지 않게 밑에 깐다).
        items.forEach(it=>{ if(!it.moved) return;
          const o=it.o, r=it.r, col=o.b.hazard?'#ff3b3b':'#ffb000';
          const ax=Math.min(Math.max(o.px+o.pw/2,r.x),r.x+r.w), ay=(r.y>o.py)?r.y:r.y+r.h;
          x.save(); x.strokeStyle=col; x.globalAlpha=0.85; x.lineWidth=Math.max(1.5,c.width/620);
          x.beginPath(); x.moveTo(ax,ay); x.lineTo(o.px+o.pw/2,o.py); x.stroke();
          x.fillStyle=col; x.beginPath(); x.arc(o.px+o.pw/2,o.py,Math.max(2,c.width/450),0,7); x.fill();
          x.restore();
        });
        // 4) 라벨 박스+글자(연결선 위에)
        items.forEach(it=>{
          const col=it.o.b.hazard?'#ff3b3b':'#ffb000';
          x.globalAlpha=0.82; x.fillStyle=col; x.fillRect(it.r.x,it.r.y,it.tw,lh); x.globalAlpha=1;
          x.fillStyle=it.o.b.hazard?'#fff':'#000'; x.fillText(it.lbl, it.r.x+4, it.r.y+4);
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
      const t=dur*i/(N-1); await seekTo(vid,t); const b64=capFrame(vid); const sig=frameSig(vid);
      document.getElementById('prog').textContent='위험요인 탐색 중… '+(i+1)+'/'+N;
      let risk={score:0,hazards:[]};
      try{ risk=await (await fetch('/safety/incident/frame',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:b64})})).json(); }catch(e){}
      frames.push({t,b64,risk,sig});
      bars[i].onclick=()=>{ vid.currentTime=t; vid.play(); };
    }
    // 모션 스파이크(급격한 변화=사고 순간) + 하드코딩 위험점수 결합 → 사고 시점 추정
    let maxMotion=0;
    for(let i=1;i<frames.length;i++){ frames[i].motion=sigDiff(frames[i].sig,frames[i-1].sig); if(frames[i].motion>maxMotion)maxMotion=frames[i].motion; }
    if(frames[0]) frames[0].motion=0;
    frames.forEach((f,i)=>{ const mScore=maxMotion>0?(f.motion/maxMotion)*60:0; f.combined=(f.risk.score||0)+mScore;
      if(bars[i]){ bars[i].style.height=Math.min(38,4+f.combined*0.5)+'px';
        bars[i].style.background= f.combined>=60?'#ff3b3b': f.combined>=30?'#ffb000':'#2a4a2a';
        bars[i].title=f.t.toFixed(1)+'s · 종합 '+Math.round(f.combined)+' (위험 '+(f.risk.score||0)+' + 모션 '+Math.round(mScore)+')'; } });
    document.getElementById('prog').textContent='';
    const peak=frames.reduce((a,b)=> b.combined>a.combined?b:a, frames[0]);
    vid.currentTime=peak.t;  // 사고 추정 시점으로 점프
    const motionDriven = maxMotion>0 && peak.motion>=maxMotion*0.6;
    const peakHtml = peak.combined>0
      ? '<div class="peak">⚠ 사고 추정 시점: <b>'+peak.t.toFixed(1)+'초</b> · '+(peak.risk.hazards.join(', ')||(motionDriven?'급격한 움직임(사고 의심)':'위험 신호'))+'<br><span class="dim">위 영상이 그 시점으로 이동했습니다. 재생해 확인하세요.</span></div>'
      : '<div class="peak dim">뚜렷한 사고 시점을 못 찾음(영상 화질·각도)</div>';
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
    const ai=j.ai_analysis;
    const aiHtml = ai ? ('<div style="line-height:1.95">'
        +'<b>🔧 작업:</b> '+(ai.work||'불명확')+'<br>'
        +'<b>🚨 재해유형:</b> <span class="miss">'+(ai.accident_type||'불명확')+'</span><br>'
        +'<b>📌 상황:</b> '+(ai.what_happened||'불명확')+'<br>'
        +'<b>🔎 추정 원인:</b> '+(ai.cause||'불명확')
        +(ai.evidence?'<br><span class="dim">↳ 근거: '+ai.evidence+'</span>':'')+'</div>')
      : (vlm?'<span class="dim">VLM이 장면을 분석하지 못했습니다(재시도 또는 다른 프레임)</span>':'<span class="dim">⚠ VLM 분석 체크를 켜야 작업·재해를 분석합니다</span>');
    const ca=j.cause_analysis;
    const caHtml = ca ? ('<div style="margin-top:10px;padding-top:8px;border-top:1px solid #1c1c20;line-height:1.8">'
        +'<b>🎯 직접원인:</b> '+(ca.direct||'-')+'<br>'
        +'<b>🧩 근본원인:</b> '+(ca.root||'-')
        +'<div class="dim" style="font-size:11px;margin-top:4px">출처: '+(ca.source||'규칙')+' · 사실 기반(책임비율/법적판단 아님)</div></div>') : '';
    const eng = j.engine ? ' <span class="dim" style="font-size:11px">· 엔진: '+j.engine+'</span>' : '';
    document.getElementById('out').innerHTML=pre+
      sec('🧠 AI 사고 분석'+eng, aiHtml+caHtml)
      +sec('🔍 위험요인 표시 + 장면 분석'+(t!=null?' ('+t.toFixed(1)+'초)':''), imgHtml+(j.scene?'<div class="scene">'+j.scene+'</div>':'<span class="dim">VLM 미사용/미인식</span>')
          +'<div class="dim" style="margin-top:6px">감지: '+((j.detected||[]).join(', ')||'-')+' · 환경: '+(j.environment||'-')+' · 작업: '+(j.activity||'-')+'</div>')
      +sec('🎬 감지된 위험 행동 (VLM 판단)', (j.behaviors&&j.behaviors.length)?'<ul>'+j.behaviors.map(b=>'<li'+(b.confirmed?' class="miss"':'')+'>'+b.label+' <span class="dim">['+b.confidence+']</span>'+(b.evidence?'<br><span class="dim" style="font-size:12px">↳ 근거: '+b.evidence+'</span>':'')+'</li>').join('')+'</ul>':'<span class="dim">VLM 켜면 위험행동을 딥러닝(VLM)이 직접 판단·근거와 함께 분석합니다</span>')
      +sec('⚠ 재해 원인(빠진 안전조치)', (j.missing_measures&&j.missing_measures.length)?'<ul>'+j.missing_measures.map(m=>'<li class="miss">'+m+' 미확인/없음</li>').join('')+'</ul>':'<span class="dim">VLM 켜면 \'없는 조치\'까지 추론</span>')
      +sec('📖 관련 법령', regs?'<ul>'+regs+'</ul>':'')
      +sec('🔁 유사 중대재해 패턴', pat?'<ul>'+pat+'</ul>':'')
      +sec('🔎 관련 지식·법령·사례 (의미검색 RAG)', (j.related&&j.related.length)?'<ul>'+j.related.map(r=>`<li><b>${r.title}</b> <span class="dim">[${r.type}]</span><br><span style="font-size:12.5px">${r.text}</span>${r.source?'<br><span class="dim">근거: '+r.source+'</span>':''}</li>`).join('')+'</ul>':'')
      +sec('✅ 예방 방법', (j.actions&&j.actions.length)?'<ul>'+j.actions.map(a=>'<li>'+a+'</li>').join('')+'</ul>':'')
      +'<div class="card dim">'+j.disclaimer+(j.vlm_used?' · VLM 사용':' · VLM 미사용')+'</div>';
  }
</script></body></html>"""
