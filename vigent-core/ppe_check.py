"""ppe_check.py — 현장별 맞춤 보호구(PPE) 착용 점검

각 현장이 "필요한 보호구"를 직접 설정(config/ppe_rules.yaml)하면, 감지된 작업자의
보호구 착용 여부를 점검해 미착용을 경고한다. 다양한 현장 배포를 위해 설정 기반.

감지 2단계:
  · YOLO 모델: 안전모·안전조끼·마스크 (모델 직접) — 빠름
  · VLM 질문: 안전화·보호장갑·보안경·방독마스크·용접면·안전대 등 — class 없이도 판단

⚠ 보조 알림이며 인증 안전장치를 대체하지 않는다. VLM·모델은 확률적이라 틀릴 수 있다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_RULES = _ROOT / "config" / "ppe_rules.yaml"

# 보호구 카탈로그 — 현장이 이 중에서 '필수'를 고른다
PPE_CATALOG: list[dict[str, Any]] = [
    {"id": "hardhat", "label": "안전모", "method": "yolo",
     "miss": "no-hardhat", "have": "hardhat"},
    {"id": "safety_vest", "label": "안전조끼", "method": "yolo",
     "miss": "no-safety-vest", "have": "safety-vest"},
    {"id": "mask", "label": "마스크", "method": "yolo",
     "miss": "no-mask", "have": "mask"},
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
    if _RULES.exists():
        try:
            import yaml
            d = yaml.safe_load(_RULES.read_text(encoding="utf-8")) or {}
            req = d.get("required")
            if isinstance(req, list):
                return {"required": [r for r in req if r in _BY_ID], "site": d.get("site", "")}
        except Exception:  # noqa: BLE001
            pass
    return {"required": list(_DEFAULT_REQUIRED), "site": ""}


def save_rules(required: list[str], site: str = "") -> dict[str, Any]:
    req = [r for r in (required or []) if r in _BY_ID]
    _RULES.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        _RULES.write_text(yaml.safe_dump({"site": site, "required": req}, allow_unicode=True),
                          encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "required": req, "site": site}


def check(detections: list[dict], image_bgr=None, required: list[str] | None = None,
          use_vlm: bool = True) -> dict[str, Any]:
    """필수 보호구별 착용 상태 점검. 반환: {results:[{id,label,status}], missing:[...]}.
    status: present(착용)/missing(미착용)/unknown(판단불가)."""
    req = required if required is not None else get_rules()["required"]
    low = [str(d.get("label") or "").lower() for d in detections]
    results = []
    for pid in req:
        item = _BY_ID.get(pid)
        if not item:
            continue
        status = "unknown"
        if item["method"] == "yolo":
            if item["miss"] in low:
                status = "missing"
            elif item["have"] in low:
                status = "present"
        else:  # vlm
            if use_vlm and image_bgr is not None:
                try:
                    import safety_brain
                    v = safety_brain._vlm_present(image_bgr, item["q"])
                    status = "present" if v is True else "missing" if v is False else "unknown"
                except Exception:  # noqa: BLE001
                    status = "unknown"
        results.append({"id": pid, "label": item["label"], "method": item["method"], "status": status})
    missing = [r for r in results if r["status"] == "missing"]
    return {"ok": True, "results": results, "missing": missing,
            "warn": ("보호구 미착용: " + ", ".join(r["label"] for r in missing)) if missing else ""}


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
