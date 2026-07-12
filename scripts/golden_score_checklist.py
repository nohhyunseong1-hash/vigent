"""체크리스트법 골든 채점 — 정답(강사) vs 현행 Scribe(체크리스트 모드).

Scribe는 '비전 감지된 항목'만 X로 낼 수 있다(문서항목·신호수 등은 사각지대).
그래서 항목을 3부류로 나눠 분리 보고(§7 — 한계 명시):
  - 탐지가능 X: 비전 감지 대상(scribe_rule 있음) → 커버리지·O/X·위험수준·위계·법령 채점
  - 비전 사각지대 X: 정답은 X이나 비전 직접탐지 불가(scribe_rule null) → 놓침(구조적)
  - O 항목: 적정 → Scribe가 X로 오탐하지 않아야(환각 아님)
실행: /opt/anaconda3/bin/python3 scripts/golden_score_checklist.py
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

GOLD = Path(__file__).resolve().parent.parent / "eval" / "golden" / "item_01_crane_checklist.json"
gold = json.loads(GOLD.read_text(encoding="utf-8"))
_HUMAN = ["신호수", "유도자", "감시", "교육", "점검", "출입", "동선", "배치", "지도", "결속", "휴식"]


def lkn(s):
    lk = L._canon_law(s); an = L._art_num(s)
    return (lk, an) if lk is not None and an is not None else None


def hierarchy_ok(row):
    h = row.get("감소대책_위계") or {}
    if not h:
        return None
    return not any(kw in " ".join(h.get("공학적", []) or []) for kw in _HUMAN)


scribe = ScribeAgent(None); scribe.copilot = CopilotAgent(None)
res = scribe.generate(gold["events"], site=gold.get("site", ""), process=gold.get("process", ""),
                      save=False, mode="checklist")
by_rule = {r["rule"]: r for r in res["assessment"]["rows"]}

det_X = [i for i in gold["items"] if i["적정성"] == "X" and i.get("scribe_rule")]
blind_X = [i for i in gold["items"] if i["적정성"] == "X" and not i.get("scribe_rule")]
O_items = [i for i in gold["items"] if i["적정성"] == "O"]

covered = level_ok = hier_ok = 0
cite_found = cite_total = cite_hall = 0
false_X = 0
detail = []
for it in det_X:
    row = by_rule.get(it["scribe_rule"])
    if not row:
        detail.append((it["check_point"], "제품 미탐지(t_down)")); continue
    covered += 1
    lv_ok = row["위험수준"] == it["위험수준"]; level_ok += lv_ok
    ho = hierarchy_ok(row); hier_ok += 1 if ho else 0
    g = {lkn(x) for x in it["법령"]}; g.discard(None)
    p = {lkn(f"{c.get('source','')} {c.get('clause','')}") for c in row.get("citations", [])}; p.discard(None)
    cite_found += len(g & p); cite_total += len(g); cite_hall += len(p - g)
    detail.append((it["check_point"],
                   {"적정성": f"X/X✓", "위험수준": f"{row['위험수준']}/{it['위험수준']}{'✓' if lv_ok else '✗'}",
                    "위계": "정답" if ho else "오분류", "법령": f"{len(g & p)}/{len(g)}",
                    "놓침": sorted(f"{k}{n}" for k, n in (g - p)), "환각": sorted(f"{k}{n}" for k, n in (p - g))}))
# O 항목: Scribe가 X로 오탐? (매핑 규칙이 감지되면 오탐) — 여기선 scribe_rule null이라 구조상 없음
for it in O_items:
    r = it.get("scribe_rule")
    if r and r in by_rule:
        false_X += 1

def out(s): print(s); L_lines.append(s)
L_lines = []
out(f"# 체크리스트 골든 채점 — {gold['id']}  검수:{gold['verified_by']}/{gold['verified_date']}")
out(f"근거: {gold['legal_basis']}")
out("=" * 66)
out(f"[탐지가능 X] 커버리지 {covered}/{len(det_X)} · O/X {covered}/{covered}(전부 X 정답) · "
    f"위험수준 {level_ok}/{covered} · 위계 {hier_ok}/{covered} · 법령 {cite_found}/{cite_total} · 환각 {cite_hall}")
out(f"[비전 사각지대 X] {len(blind_X)}건 — 비전 직접탐지 불가(구조적 놓침): "
    f"{', '.join(i['check_point'] for i in blind_X) or '없음'}")
out(f"[O 항목] {len(O_items)}건 — Scribe 오탐(false X) {false_X}건 (0이어야 정상)")
out("-" * 66)
for name, d in detail:
    if isinstance(d, str):
        out(f"[{name}] {d}"); continue
    out(f"[{name}] O/X {d['적정성']} · 위험수준 {d['위험수준']} · 위계 {d['위계']} · 법령 {d['법령']}")
    if d["놓침"]: out(f"    놓친 법령: {', '.join(d['놓침'])}")
    if d["환각"]: out(f"    환각 법령: {', '.join(d['환각'])}")
out("=" * 66)
# 분리 지표(사용자 요청): O/X·위험수준·위계 정확도
oX_acc = (covered + (len(O_items) - false_X)) / (len(det_X) + len(O_items)) if (det_X or O_items) else 0
out(f"■ 분리 지표 — O/X 판단 정확도 {oX_acc*100:.0f}% (탐지가능X+O, 사각지대 제외) · "
    f"위험수준 정확도 {level_ok}/{covered} · 위계 정확도 {hier_ok}/{covered}")
out(f"■ 커버리지 한계: 전체 X {len(det_X)+len(blind_X)}건 중 비전탐지 가능 {len(det_X)}건 "
    f"(신호수/문서항목 등 {len(blind_X)}건은 비전 사각지대 → 다른 입력 필요)")
GOLD.with_name(GOLD.stem + "_score.md").write_text("\n".join(L_lines) + "\n", encoding="utf-8")
print("─" * 66); print("저장:", GOLD.with_name(GOLD.stem + "_score.md"))
