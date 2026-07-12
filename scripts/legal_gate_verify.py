"""Part 3 실동작 검증 — 위험성평가서 1건 + 화이트리스트 판정 + VLM 게이트 차단 실증.

검증 항목:
  A. 위험성평가서가 정상 생성되는가(저하 없음 — 인용 그대로 유지, §6)
  B. 각 인용 조문의 화이트리스트 내/외 판정이 맞는가(감사)
  C. VLM 자유생성 경로에서 화이트리스트 밖/가짜 조문이 '차단'되는가(환각 게이트)
실행: /opt/anaconda3/bin/python3 scripts/legal_gate_verify.py
"""
import os
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "vigent-core"
sys.path.insert(0, str(CORE))
os.chdir(CORE)

import legal_whitelist as L                # noqa: E402
from agents.scribe import ScribeAgent      # noqa: E402
from agents.copilot import CopilotAgent    # noqa: E402

copilot = CopilotAgent(None)
scribe = ScribeAgent(None)
scribe.copilot = copilot

print("=" * 64)
print("A. 위험성평가서 생성(저하 없음 확인)")
events = [
    {"rule": "ppe_missing",      "count": 4, "levels": {"high": 2, "mid": 2}},   # 38·32 (WL내)
    {"rule": "fall_suspected",   "count": 2, "levels": {"high": 2}},             # 38·42·43 (WL내)
    {"rule": "proximity_hazard", "count": 5, "levels": {"high": 3, "mid": 2}},   # 38·172·20 (WL내)
    {"rule": "asphyxiation",     "count": 2, "levels": {"critical": 2}},         # 39·619·620 (보류 포함)
]
res = scribe.generate(events, site="검증공장", process="혼합작업", save=True)
ok_gen = bool(res.get("html")) and res.get("saved")
n_rows = len(res.get("assessment", {}).get("rows", []))
print(f"   생성 OK: {ok_gen} | 행 수: {n_rows} | 저장: {res.get('saved_path')}")

print("=" * 64)
print("B. 인용 조문 화이트리스트 판정(감사)")
wl_in, wl_out, non_law = 0, 0, 0
for row in res["assessment"]["rows"]:
    for c in row.get("citations", []):
        lk = L._canon_law(c.get("source", ""))
        if lk is None:
            non_law += 1
            continue
        an = L._art_num(c.get("clause", ""))
        if L.is_whitelisted(lk, an):
            wl_in += 1
        else:
            wl_out += 1
            print(f"   [보류] {c.get('source')} {c.get('clause')}  → 문서엔 유지, 로그 기록(§6 비파괴)")
print(f"   화이트리스트 내 {wl_in} · 보류 {wl_out} · 법령아님(가이드/IEC) {non_law}")

print("=" * 64)
print("C. VLM 자유생성 경로 환각 게이트(차단 실증)")
# VLM 이 '관련법령'을 직접 채운 상황을 모사: 진짜 38조 + 가짜 999조 + 보류 14조
fake_vlm = {"위험요인": "테스트", "근거": "테스트",
            "관련법령": "산업안전보건법 제38조(안전조치); 산업안전보건기준에 관한 규칙 제999조(가짜); 산업안전보건기준에 관한 규칙 제14조(낙하물)"}
before = fake_vlm["관련법령"]
after = copilot.enrich_vlm(dict(fake_vlm))["관련법령"]
blocked_999 = "제999조" not in after
blocked_14 = "제14조" not in after
kept_38 = "제38조" in after
print(f"   입력: {before}")
print(f"   출력: {after}")
print(f"   가짜 999조 차단: {blocked_999} | 보류 14조 차단: {blocked_14} | 진짜 38조 유지: {kept_38}")

print("=" * 64)
passed = ok_gen and n_rows > 0 and wl_in > 0 and wl_out > 0 and blocked_999 and blocked_14 and kept_38
print("판정:", "✅ PASS" if passed else "❌ FAIL")
print("  - 위험성평가서 저하 없음(인용 유지):", ok_gen)
print("  - 보류 조문 감사 기록됨:", wl_out > 0)
print("  - VLM 환각(999조)·보류(14조) 차단, 진짜(38조) 유지:", blocked_999 and blocked_14 and kept_38)
print("  ※ 고시 시각 구분: 고시 미등재(14개에 고시 없음) → 이번 검증 대상 아님")
sys.exit(0 if passed else 1)
