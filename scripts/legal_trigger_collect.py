"""실전 트리거 수집 — 위험성평가서 5건 생성 → 보류 조문 인용 빈도 집계.

용도 제한(§7): 이 스크립트는 '인용 시도된 보류 조문의 빈도'만 센다.
생성 문서의 내용 정확성은 판단하지 않는다(골든셋 정답 부재 → 채점 불가).
문서는 트리거 수집용 스캐폴드일 뿐이다.

관리체계·TBM·아차사고는 생성기가 없어 위험성평가서로만 수집한다.
실행: /opt/anaconda3/bin/python3 scripts/legal_trigger_collect.py
"""
import json
import os
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "vigent-core"
sys.path.insert(0, str(CORE))
os.chdir(CORE)

import legal_whitelist as L                      # noqa: E402
from agents.scribe import ScribeAgent            # noqa: E402
from agents.copilot import CopilotAgent          # noqa: E402

# 1) 이전(단위테스트 등) 로그 오염 제거 — 깨끗한 수집
if L._BLOCKED_LOG.exists():
    L._BLOCKED_LOG.unlink()

# 트리거엔 Scribe+Copilot 만 필요(Guard 등은 config.slots 요구 → 제외)
scribe = ScribeAgent(None)
scribe.copilot = CopilotAgent(None)

# 5개 샘플 — 서로 다른 시나리오로 다양한 규칙(→다양한 조문)이 인용되게 구성
SAMPLES = [
    ("제1공장 프레스라인", "판재 프레스 가공", [
        {"rule": "ppe_missing",   "count": 5, "levels": {"high": 2, "mid": 3}},
        {"rule": "guard_bypass",  "count": 3, "levels": {"critical": 1, "high": 2}},
        {"rule": "trip_hazard",   "count": 4, "levels": {"mid": 4}},
    ]),
    ("제2공장 기계가공", "회전체 가공·운반", [
        {"rule": "machine_entanglement", "count": 4, "levels": {"high": 3, "low": 1}},
        {"rule": "proximity_hazard",     "count": 6, "levels": {"high": 4, "mid": 2}},
        {"rule": "falling_object",       "count": 2, "levels": {"high": 2}},
    ]),
    ("탱크 정비동", "밀폐공간 정비", [
        {"rule": "asphyxiation", "count": 3, "levels": {"critical": 2, "high": 1}},
        {"rule": "gas_alarm",    "count": 2, "levels": {"high": 2}},
        {"rule": "lone_worker",  "count": 1, "levels": {"high": 1}},
    ]),
    ("건설현장 3층", "고소 조립작업", [
        {"rule": "height_fall_risk", "count": 5, "levels": {"critical": 1, "high": 4}},
        {"rule": "fall_suspected",   "count": 3, "levels": {"high": 3}},
        {"rule": "crowd_density",    "count": 2, "levels": {"mid": 2}},
    ]),
    ("옥외 배전작업장", "전기·옥외 작업", [
        {"rule": "electrical_hazard", "count": 4, "levels": {"critical": 1, "high": 3}},
        {"rule": "heat_stress",       "count": 3, "levels": {"mid": 3}},
        {"rule": "immobility",        "count": 1, "levels": {"high": 1}},
        {"rule": "ergonomic_risk",    "count": 4, "levels": {"mid": 4}},
    ]),
]

for site, proc, events in SAMPLES:
    scribe.generate(events, site=site, process=proc, save=False)

rep = L.frequency_report(top=40)

# 2) 콘솔 출력
print(f"게이트 활성: {rep['whitelist_enabled']} ({rep['whitelist_reason']})")
print(f"총 보류 인용 시도: {rep['total_blocked']}건 / 고유 조문 {rep['distinct']}종")
print("─" * 60)
for i, e in enumerate(rep["ranking"], 1):
    rules = ", ".join(e["rules"][:4])
    print(f"{i:2}. {e['count']:2}회  {e['law']} {e['article']}   [{rules}]")

# 3) 마크다운 리포트 저장(커밋용)
out = Path(__file__).resolve().parent.parent / "data" / "legal" / "trigger_report.md"
lines = [
    "# 법령 트리거 리포트 — 보류 조문 인용 빈도 (필요 기반 우선순위)",
    "",
    "> 위험성평가서 5건 생성 시 '화이트리스트 밖 조문' 인용 시도를 집계.",
    "> 문서 내용 정확성은 판단하지 않음(골든셋 부재). 빈도만.",
    "> 관리체계·TBM·아차사고는 생성기 미구현 → 위험성평가서로만 수집.",
    "",
    f"- 게이트 활성: **{rep['whitelist_enabled']}**",
    f"- 총 보류 인용 시도: **{rep['total_blocked']}건** / 고유 조문 **{rep['distinct']}종**",
    "",
    "## 검수 대기열(빈도 높은 순 — 이 순서로 화이트리스트 추가 검토)",
    "",
    "| 순위 | 빈도 | 법령·조문 | 관련 규칙 |",
    "|---|---|---|---|",
]
for i, e in enumerate(rep["ranking"], 1):
    lines.append(f"| {i} | {e['count']} | {e['law']} {e['article']} | {', '.join(e['rules'])} |")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("─" * 60)
print(f"리포트 저장: {out}")
