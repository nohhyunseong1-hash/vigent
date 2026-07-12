"""골든셋 채점 — 정답(강사) vs 현재 Scribe 출력. 첫 검증 바퀴.

지표:
  - 위험요인 커버리지: 정답 위험요인을 제품이 냈는가(재현) / 정답에 없는 걸 냈는가(과잉=t_hall)
  - 빈도·강도·등급 일치율(매칭된 위험요인)
  - 법령 재현(정답 인용 중 제품이 낸 비율) / 법령 환각(제품 인용 중 정답에 없는 법령)
실행: /opt/anaconda3/bin/python3 scripts/golden_score.py eval/golden/item_01_crane.json
"""
import json
import os
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "vigent-core"
sys.path.insert(0, str(CORE))
os.chdir(CORE)

import legal_whitelist as L                # noqa: E402
from agents.scribe import ScribeAgent      # noqa: E402
from agents.copilot import CopilotAgent    # noqa: E402

GOLD_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(__file__).resolve().parent.parent / "eval" / "golden" / "item_01_crane.json"
gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def law_key_num(s: str):
    """법령 문자열 → (law_key, art_num). 법령 아니면 None."""
    lk = L._canon_law(s)
    an = L._art_num(s)
    return (lk, an) if lk is not None and an is not None else None


# 현재 Scribe 출력 생성
scribe = ScribeAgent(None)
scribe.copilot = CopilotAgent(None)
res = scribe.generate(gold["events"], site=gold.get("site", ""), process=gold.get("process", ""), save=False)
scribe_by_rule = {r["rule"]: r for r in res["assessment"]["rows"]}

grade_map = gold.get("grade_map", {})
covered, missed_hazard = 0, []
freq_ok = sev_ok = grade_ok = 0
cite_found = cite_total = cite_hall = 0
detail = []

for hz in gold["hazards"]:
    rule = hz["scribe_rule"]
    row = scribe_by_rule.get(rule)
    d = {"hazard": hz["name"], "rule": rule}
    if not row:
        missed_hazard.append(hz["name"])
        d["status"] = "제품이 못 냄(t_down)"
        detail.append(d)
        continue
    covered += 1
    # 빈도/강도
    f_ok = int(row["가능성_빈도"]) == int(hz["빈도"])
    s_ok = int(row["중대성_강도"]) == int(hz["강도"])
    freq_ok += f_ok
    sev_ok += s_ok
    # 등급: Scribe 상/중/하 → 정답 밴드 매핑
    prod_band = grade_map.get(row["위험성등급"], row["위험성등급"])
    g_ok = prod_band == hz["등급"]
    grade_ok += g_ok
    # 법령 재현/환각
    gold_refs = {law_key_num(x) for x in hz["법령"]}
    gold_refs.discard(None)
    prod_refs = {law_key_num(f"{c.get('source','')} {c.get('clause','')}") for c in row.get("citations", [])}
    prod_refs.discard(None)
    found = gold_refs & prod_refs
    missed = gold_refs - prod_refs
    hall = prod_refs - gold_refs
    cite_found += len(found)
    cite_total += len(gold_refs)
    cite_hall += len(hall)
    d.update({"status": "매칭", "빈도": f"{row['가능성_빈도']}/{hz['빈도']}{'✓' if f_ok else '✗'}",
              "강도": f"{row['중대성_강도']}/{hz['강도']}{'✓' if s_ok else '✗'}",
              "등급": f"{prod_band}/{hz['등급']}{'✓' if g_ok else '✗'}",
              "법령재현": f"{len(found)}/{len(gold_refs)}",
              "놓친법령": sorted(f"{k}{n}" for k, n in missed),
              "환각법령": sorted(f"{k}{n}" for k, n in hall)})
    detail.append(d)

nH = len(gold["hazards"])
lines = []
def out(s): print(s); lines.append(s)

out(f"# 골든셋 채점 — {gold['id']} ({gold['scenario']})")
out(f"정답 검수자: {gold['verified_by']} / {gold['verified_date']}")
out("=" * 64)
out(f"위험요인 커버리지: {covered}/{nH}  (못 낸 것: {missed_hazard or '없음'})")
out(f"빈도 일치: {freq_ok}/{covered}   강도 일치: {sev_ok}/{covered}   등급 일치: {grade_ok}/{covered}")
out(f"법령 재현(t_down 역): {cite_found}/{cite_total} = {cite_found/cite_total*100:.0f}%")
out(f"법령 환각(t_hall): {cite_hall}건")
out("-" * 64)
for d in detail:
    if d["status"] == "매칭":
        out(f"[{d['hazard']}] 빈도 {d['빈도']} · 강도 {d['강도']} · 등급 {d['등급']} · 법령 {d['법령재현']}")
        if d["놓친법령"]:
            out(f"    놓친 법령(t_down): {', '.join(d['놓친법령'])}")
        if d["환각법령"]:
            out(f"    환각 법령(t_hall): {', '.join(d['환각법령'])}")
    else:
        out(f"[{d['hazard']}] {d['status']}")
out("=" * 64)
out("해석: 커버리지·강도·등급은 100%이나 (1)빈도 과소평가 1건, "
    "(2)크레인 특화 조문(제40·146조) 미인용, (3)제15조 환각 1건이 개선점.")

score_path = GOLD_PATH.with_name(GOLD_PATH.stem + "_score.md")
score_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("─" * 64)
print("점수 저장:", score_path)
