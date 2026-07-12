"""골든셋 채점 — 정답(강사) vs 현재 Scribe 출력.

총점 공식(제가 정의, 가중치 명시 — §7 투명성):
  총점 = 0.30·커버리지 + 0.15·빈도 + 0.15·강도 + 0.20·법령재현 + 0.20·감소대책위계
  (환각은 총점에서 빼지 않고 별도 보고)

감소대책 위계(고시 제12조) 원칙: 인적 대책(신호수·유도자·감시·교육)=관리적,
  설비·구조 대책(센서·펜스·방호·경보)=공학적으로 더 상위.
  → row['감소대책_위계']가 있고, 공학적 칸에 인적 대책이 섞이지 않으면 정답.
실행: /opt/anaconda3/bin/python3 scripts/golden_score.py
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

GOLD_PATH = Path(__file__).resolve().parent.parent / "eval" / "golden" / "item_01_crane_quantitative.json"
gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))

_HUMAN_KW = ["신호수", "유도자", "감시", "교육", "점검", "출입", "동선", "배치", "지도", "결속", "휴식"]


def law_key_num(s: str):
    lk = L._canon_law(s); an = L._art_num(s)
    return (lk, an) if lk is not None and an is not None else None


def hierarchy_ok(row):
    """감소대책 위계 원칙 준수 여부. 위계 필드 없으면 None(=미구현)."""
    h = row.get("감소대책_위계")
    if not h:
        return None
    eng = " ".join(h.get("공학적", []) or [])
    if any(kw in eng for kw in _HUMAN_KW):
        return False                       # 인적 대책이 공학적에 오분류
    return True


scribe = ScribeAgent(None)
scribe.copilot = CopilotAgent(None)
res = scribe.generate(gold["events"], site=gold.get("site", ""), process=gold.get("process", ""),
                      save=False, mode="quantitative")   # 정량법(3×3) 채점기
by_rule = {r["rule"]: r for r in res["assessment"]["rows"]}
grade_map = gold.get("grade_map", {})

covered = freq_ok = sev_ok = grade_ok = 0
cite_found = cite_total = cite_hall = 0
hier_ok = 0
hier_impl = 0
missed_hazard = []
detail = []

for hz in gold["hazards"]:
    row = by_rule.get(hz["scribe_rule"])
    if not row:
        missed_hazard.append(hz["name"]); detail.append((hz["name"], "제품이 못 냄(t_down)")); continue
    covered += 1
    f_ok = int(row["가능성_빈도"]) == int(hz["빈도"]); freq_ok += f_ok
    s_ok = int(row["중대성_강도"]) == int(hz["강도"]); sev_ok += s_ok
    prod_band = grade_map.get(row["위험성등급"], row["위험성등급"])
    g_ok = prod_band == hz["등급"]; grade_ok += g_ok
    gold_refs = {law_key_num(x) for x in hz["법령"]}; gold_refs.discard(None)
    prod_refs = {law_key_num(f"{c.get('source','')} {c.get('clause','')}") for c in row.get("citations", [])}
    prod_refs.discard(None)
    found = gold_refs & prod_refs; missed = gold_refs - prod_refs; hall = prod_refs - gold_refs
    cite_found += len(found); cite_total += len(gold_refs); cite_hall += len(hall)
    ho = hierarchy_ok(row)
    if ho is not None:
        hier_impl += 1
        hier_ok += 1 if ho else 0
    detail.append((hz["name"], {
        "빈도": f"{row['가능성_빈도']}/{hz['빈도']}{'✓' if f_ok else '✗'}",
        "강도": f"{row['중대성_강도']}/{hz['강도']}{'✓' if s_ok else '✗'}",
        "등급": f"{prod_band}/{hz['등급']}{'✓' if g_ok else '✗'}",
        "법령": f"{len(found)}/{len(gold_refs)}",
        "위계": "미구현" if ho is None else ("정답" if ho else "오분류"),
        "놓친법령": sorted(f"{k}{n}" for k, n in missed),
        "환각법령": sorted(f"{k}{n}" for k, n in hall)}))

nH = len(gold["hazards"])
cov = covered / nH
freq = freq_ok / covered if covered else 0
sev = sev_ok / covered if covered else 0
lawr = cite_found / cite_total if cite_total else 0
hier = hier_ok / covered if covered else 0     # 미구현 위계는 0점
total = 0.30 * cov + 0.15 * freq + 0.15 * sev + 0.20 * lawr + 0.20 * hier

lines = []
def out(s): print(s); lines.append(s)

out(f"# 골든셋 채점 — {gold['id']} ({gold['scenario']})  검수:{gold['verified_by']}/{gold['verified_date']}")
out("=" * 66)
out(f"■ 총점: {total*100:.0f}점  (0.30커버 +0.15빈도 +0.15강도 +0.20법령 +0.20위계)")
out("-" * 66)
out(f"커버리지 {covered}/{nH}({cov*100:.0f}%) · 빈도 {freq_ok}/{covered} · 강도 {sev_ok}/{covered} · 등급 {grade_ok}/{covered}")
out(f"법령재현 {cite_found}/{cite_total}({lawr*100:.0f}%) · 위계 {hier_ok}/{covered}({'구현' if hier_impl else '미구현'}) · 환각 {cite_hall}건(별도)")
out("-" * 66)
for name, d in detail:
    if isinstance(d, str):
        out(f"[{name}] {d}"); continue
    out(f"[{name}] 빈도 {d['빈도']} · 강도 {d['강도']} · 등급 {d['등급']} · 법령 {d['법령']} · 위계 {d['위계']}")
    if d["놓친법령"]: out(f"    놓친 법령(t_down): {', '.join(d['놓친법령'])}")
    if d["환각법령"]: out(f"    환각 법령(t_hall): {', '.join(d['환각법령'])}")

(GOLD_PATH.with_name(GOLD_PATH.stem + "_score.md")).write_text("\n".join(lines) + "\n", encoding="utf-8")
print("─" * 66); print("총점:", f"{total*100:.0f}")
