"""체크리스트법 골든 채점 — 정답(강사) vs 현행 Scribe(체크리스트 모드, item_pool).

item_pool을 주면 Scribe가 점검항목 '전부'를 나열한다: 비전 감지=부적정(X),
미감지 요건=‘수동확인 필요’(비전 사각지대·문서항목을 조용히 놓치지 않음, §7).

분리 보고:
  - 자동 부적정(X): 비전 감지 항목 → O/X·위험수준·위계·법령 채점
  - 수동확인: 미감지 요건(정답 O 또는 비전 사각지대 X) → 표면화 여부
  - O 오탐(false X): 적정 항목을 X로 몰았는가(0이어야)

★ 채점 대상은 Scribe.build_checklist(규칙기반·RULE_KB) + Copilot 법령(결정적 RAG) — **VLM 미사용 → 결정적**.
실행(단건): /opt/anaconda3/bin/python3 scripts/golden_score_checklist.py [item_XX_checklist.json]
회귀(전항목): scripts/golden_regression.py 가 score_checklist() 를 import 해 반복 호출.
"""
import json
import os
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "vigent-core"
sys.path.insert(0, str(CORE))
os.chdir(CORE)

import legal_whitelist as L  # noqa: E402
from agents.copilot import CopilotAgent  # noqa: E402
from agents.scribe import ScribeAgent  # noqa: E402

_GOLD_DIR = Path(__file__).resolve().parent.parent / "eval" / "golden"
_HUMAN = ["신호수", "유도자", "감시", "교육", "점검", "출입", "동선", "배치", "지도", "결속", "휴식"]


def lkn(s):
    lk = L._canon_law(s); an = L._art_num(s)
    return (lk, an) if lk is not None and an is not None else None


def hierarchy_ok(row):
    h = row.get("감소대책_위계") or {}
    return (not any(kw in " ".join(h.get("공학적", []) or []) for kw in _HUMAN)) if h else None


def score_checklist(name: str = "item_01_crane_checklist.json", verbose: bool = True,
                    write_md: bool = True) -> dict:
    """골든 1건 채점 → 지표 dict 반환(결정적). verbose=콘솔출력, write_md=_score.md 저장."""
    gold_path = _GOLD_DIR / name
    gold = json.loads(gold_path.read_text(encoding="utf-8"))

    scribe = ScribeAgent(None); scribe.copilot = CopilotAgent(None)
    pool = [{"check_point": it["check_point"], "rule": it.get("scribe_rule"),
             "법령": it.get("법령", []), "감소대책": it.get("감소대책", {})} for it in gold["items"]]
    res = scribe.build_checklist(gold["events"], site=gold.get("site", ""),
                                 process=gold.get("process", ""), item_pool=pool)
    rows = res["rows"]
    by_rule = {r["rule"]: r for r in rows if r.get("적정성") == "X"}
    by_cp = {r["유해위험요인"]: r for r in rows}

    det_X = [i for i in gold["items"] if i["적정성"] == "X" and i.get("scribe_rule")]
    blind_X = [i for i in gold["items"] if i["적정성"] == "X" and not i.get("scribe_rule")]
    O_items = [i for i in gold["items"] if i["적정성"] == "O"]

    covered = level_ok = hier_ok = 0
    cite_found = cite_total = cite_hall = 0
    detail = []
    for it in det_X:
        row = by_rule.get(it["scribe_rule"])
        if not row:
            detail.append((it["check_point"], "제품 미탐지(t_down)")); continue
        covered += 1
        lv_ok = row["위험수준"] == it["위험수준"]; level_ok += lv_ok
        ho = hierarchy_ok(row); hier_ok += 1 if ho else 0
        g = {lkn(x) for x in it["법령"]}; g.discard(None)
        p = {lkn(f"{c.get('source', '')} {c.get('clause', '')}") for c in row.get("citations", [])}; p.discard(None)
        cite_found += len(g & p); cite_total += len(g); cite_hall += len(p - g)
        detail.append((it["check_point"],
                       {"위험수준": f"{row['위험수준']}/{it['위험수준']}{'✓' if lv_ok else '✗'}",
                        "위계": "정답" if ho else "오분류", "법령": f"{len(g & p)}/{len(g)}",
                        "환각": sorted(f"{k}{n}" for k, n in (p - g))}))

    manual_needed = O_items + blind_X
    manual_shown = sum(1 for it in manual_needed
                       if by_cp.get(it["check_point"], {}).get("위험수준") == "수동확인")
    false_X = sum(1 for it in O_items if by_cp.get(it["check_point"], {}).get("적정성") == "X")
    blind_surfaced = sum(1 for it in blind_X
                         if by_cp.get(it["check_point"], {}).get("위험수준") == "수동확인")

    lines = []

    def out(s):
        if verbose:
            print(s)
        lines.append(s)
    out(f"# 체크리스트 골든 채점(item_pool) — {gold['id']}  검수:{gold['verified_by']}/{gold['verified_date']}")
    out("=" * 68)
    out(f"■ 항목 노출 커버리지: {len(rows)}/{len(gold['items'])}  (이전 event-only: {len(det_X)}/{len(gold['items'])})")
    out(f"[자동 부적정 X] {covered}/{len(det_X)} · 위험수준 {level_ok}/{covered} · 위계 {hier_ok}/{covered} · "
        f"법령 {cite_found}/{cite_total} · 환각 {cite_hall}(제38조 상위근거 포함)")
    out(f"[수동확인 표기] {manual_shown}/{len(manual_needed)}  (정답 O {len(O_items)} + 비전 사각지대 X {len(blind_X)})")
    out(f"  ★ 비전 사각지대(신호수 등) 표면화: {blind_surfaced}/{len(blind_X)} — 조용한 놓침 해소")
    out(f"[O 오탐] 적정 항목을 X로 몬 건수: {false_X} (0이어야 정상)")
    out("-" * 68)
    for nm, d in detail:
        if isinstance(d, str):
            out(f"[{nm}] {d}"); continue
        out(f"[{nm}] 위험수준 {d['위험수준']} · 위계 {d['위계']} · 법령 {d['법령']}"
            + (f" · 환각 {', '.join(d['환각'])}" if d["환각"] else ""))
    out("=" * 68)
    out(f"■ 분리지표(요청) — (a) O/X: 자동X {covered}/{len(det_X)} 정답 · O오탐 {false_X} (적정을 X로 안 몲) · "
        f"(b) 위험수준 {level_ok}/{covered} · (c) 위계 {hier_ok}/{covered}")
    if len(det_X) == 0:
        out("■ 관전: 이 작업은 비전 자동판정 가능 항목이 0건 — 전 항목이 수동확인으로 표면화됨"
            "(비전 커버리지가 낮은 도메인. 값은 '누락 없는 체크리스트 제시'에 있음).")
    if write_md:
        gold_path.with_name(gold_path.stem + "_score.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if verbose:
            print("─" * 68); print("저장:", gold_path.with_name(gold_path.stem + "_score.md"))

    return {"id": gold["id"], "items": len(gold["items"]), "rows": len(rows),
            "det_X": len(det_X), "covered": covered, "level_ok": level_ok, "hier_ok": hier_ok,
            "cite_found": cite_found, "cite_total": cite_total, "cite_hall": cite_hall,
            "manual_needed": len(manual_needed), "manual_shown": manual_shown,
            "blind_X": len(blind_X), "blind_surfaced": blind_surfaced, "false_X": false_X}


if __name__ == "__main__":
    _NAME = sys.argv[1] if len(sys.argv) > 1 else "item_01_crane_checklist.json"
    score_checklist(_NAME, verbose=True, write_md=True)
