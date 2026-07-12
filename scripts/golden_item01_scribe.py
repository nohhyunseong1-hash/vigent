"""골든셋 아이템 1(크레인 양중) — 현재 Scribe 출력을 뽑아 정답 대조용으로 덤프.

※ 정답은 AI가 작성하지 않는다(§ 골든셋 정답 대신작성 금지). 이 스크립트는
   '현재 제품이 내는 값'만 보여준다 → 노현성(강사)이 정답을 확정할 재료.
실행: /opt/anaconda3/bin/python3 scripts/golden_item01_scribe.py
"""
import json
import os
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "vigent-core"
sys.path.insert(0, str(CORE))
os.chdir(CORE)

from agents.scribe import ScribeAgent      # noqa: E402
from agents.copilot import CopilotAgent    # noqa: E402

scribe = ScribeAgent(None)
scribe.copilot = CopilotAgent(None)

# 골든 아이템 1 — 크레인 양중 작업 시나리오
SITE = "제3공장 옥외 야적장"
PROC = "20톤 크레인 철골 부재 양중"
EVENTS = [
    {"rule": "proximity_hazard", "count": 6, "levels": {"high": 4, "mid": 2}},   # 작업반경 내 진입(신호수 부재)
    {"rule": "ppe_missing",      "count": 3, "levels": {"high": 2, "mid": 1}},   # 안전모 미착용
    {"rule": "falling_object",   "count": 4, "levels": {"high": 3, "low": 1}},   # 양중 하물 흔들림·낙하 위험
]

res = scribe.generate(EVENTS, site=SITE, process=PROC, save=False)
rows = res["assessment"]["rows"]

print(f"SITE={SITE} | PROC={PROC} | rows={len(rows)}")
print("=" * 70)
for r in rows:
    cites = " / ".join(f"{c.get('source','')} {c.get('clause','')}" for c in r.get("citations", []))
    print(f"[{r['rule']}]")
    print(f"  위험요인   : {r['유해위험요인']} ({r['위험분류']})")
    print(f"  위험상황   : {r['위험상황및결과']}")
    print(f"  빈도(가능성): {r['가능성_빈도']}  강도(중대성): {r['중대성_강도']}  "
          f"위험성: {r['위험성']}  등급: {r['위험성등급']}")
    print(f"  감소대책   : {r['감소대책']}")
    print(f"  인용근거   : {cites}")
    print("-" * 70)

# 대조용 JSON도 덤프(정답 대조 스크립트가 읽을 수 있게)
dump = {"site": SITE, "process": PROC, "events": EVENTS,
        "scribe_rows": [{"rule": r["rule"], "위험요인": r["유해위험요인"],
                          "빈도": r["가능성_빈도"], "강도": r["중대성_강도"],
                          "위험성": r["위험성"], "등급": r["위험성등급"],
                          "감소대책": r["감소대책"],
                          "citations": [f"{c.get('source','')} {c.get('clause','')}" for c in r.get("citations", [])]}
                         for r in rows]}
outp = Path(__file__).resolve().parent.parent / "eval" / "golden" / "item_01_crane_scribe.json"
outp.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
print("덤프:", outp)
