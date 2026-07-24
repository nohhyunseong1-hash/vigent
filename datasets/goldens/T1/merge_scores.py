"""강사가 채운 수집표(CSV) → 각 cases/*.json 의 강사_정답 블록으로 병합(결정적).

입력: datasets/goldens/T1/scoring_items.csv, scoring_cases.csv (강사가 채운 것)
동작:
 - items: ans_적정성/ans_위험수준/ans_법령/감소대책(위계) 을 각 item 에 병합(빈 셀은 건너뜀=부분 채움 허용).
 - cases: rubric 5항목 점수 → 총점(합) 계산, C1~C4 bool, verdict.pass = (총점≥80 AND 치명오류 전부 false).
 - 검증: 적정성∈{O,X,−}, 위험수준∈{상,중,하,−,수동확인}, 점수 0..배점, C∈{true,false}. 위반 시 해당 셀 건너뛰고 경고.
 - 원본 scribe_output·input 은 건드리지 않는다. 시범_예시 필드가 있으면 보존.

실행: python3 datasets/goldens/T1/merge_scores.py            # 병합 적용
      python3 datasets/goldens/T1/merge_scores.py --check     # 병합 없이 검증·완성도만 리포트
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
ITEMS_CSV = HERE / "scoring_items.csv"
CASES_CSV = HERE / "scoring_cases.csv"

_OK_ADEQ = {"O", "X", "−", "-"}
_OK_LEVEL = {"상", "중", "하", "−", "-", "수동확인"}
_RUBRIC_KEYS = [("r1_완전성_30", "위험요인_식별_완전성", 30),
                ("r2_추정_25", "위험성_추정_적절성", 25),
                ("r3_대책_25", "감소대책_실효성_구체성", 25),
                ("r4_법령형식_10", "법적근거_형식_정확성", 10),
                ("r5_우선순위_10", "우선순위_잔류위험_관리", 10)]
_CRIT = [("C1", "C1_중대재해_핵심위험_누락"), ("C2", "C2_실재하지않는_설비공정물질_언급"),
         ("C3", "C3_법령_오인용_또는_없는조문_인용"), ("C4", "C4_위험성등급_2단계이상_과소평가")]


def _tiers(rowdict):
    m = {"제거대체": rowdict.get("감소_제거대체(;)", ""), "공학적": rowdict.get("감소_공학적(;)", ""),
         "관리적": rowdict.get("감소_관리적(;)", ""), "보호구": rowdict.get("감소_보호구(;)", "")}
    return {k: [x.strip() for x in v.split(";") if x.strip()] for k, v in m.items()}


def _split(s):
    return [x.strip() for x in (s or "").split(";") if x.strip()]


def _bool(s, warns, ctx):
    s = (s or "").strip().lower()
    if s in ("true", "1", "y", "yes"):
        return True
    if s in ("false", "0", "n", "no"):
        return False
    if s:
        warns.append(f"{ctx}: 불리언 아님 '{s}' — 건너뜀")
    return None


def _find_col(fieldnames, prefix):
    for c in fieldnames:
        if c.startswith(prefix):
            return c
    return None


def main(check_only=False):
    if not ITEMS_CSV.exists() or not CASES_CSV.exists():
        print("수집표 CSV가 없다. 먼저 make_sheets.py 실행 후 강사가 채운다.")
        return 2
    warns: list[str] = []

    # 케이스 JSON 로드
    objs = {}
    for p in sorted(CASES.glob("T1_case_*.json")):
        objs[json.loads(p.read_text(encoding="utf-8"))["id"]] = p

    # --- items ---
    items_by_case: dict[str, list[dict]] = {}
    with ITEMS_CSV.open(encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        fn = rd.fieldnames or []
        c_adeq = _find_col(fn, "ans_적정성"); c_lvl = _find_col(fn, "ans_위험수준")
        c_law = _find_col(fn, "ans_법령")
        for row in rd:
            items_by_case.setdefault(row["case_id"], []).append(
                {**row, "_adeq": c_adeq, "_lvl": c_lvl, "_law": c_law})

    # --- cases(rubric/critical) ---
    cases_meta: dict[str, dict] = {}
    with CASES_CSV.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cases_meta[row["case_id"]] = row

    filled = 0
    for cid, path in objs.items():
        obj = json.loads(path.read_text(encoding="utf-8"))
        ans = obj["강사_정답"]

        # 항목 병합
        for row in items_by_case.get(cid, []):
            idx = int(row["item_no"]) - 1
            if idx >= len(ans["items"]):
                warns.append(f"{cid} item_no {row['item_no']} 범위초과 — 건너뜀"); continue
            it = ans["items"][idx]
            ad = (row.get(row["_adeq"]) or "").strip()
            if ad:
                if ad in _OK_ADEQ:
                    it["적정성"] = "−" if ad == "-" else ad
                else:
                    warns.append(f"{cid} #{row['item_no']} 적정성 '{ad}' 부적합 — 건너뜀")
            lv = (row.get(row["_lvl"]) or "").strip()
            if lv:
                if lv in _OK_LEVEL:
                    it["위험수준"] = "−" if lv == "-" else lv
                else:
                    warns.append(f"{cid} #{row['item_no']} 위험수준 '{lv}' 부적합 — 건너뜀")
            laws = _split(row.get(row["_law"]))
            if laws:
                it["법령"] = laws
            tiers = _tiers(row)
            if any(tiers.values()):
                it["감소대책"] = tiers

        # rubric/critical 병합
        meta = cases_meta.get(cid)
        if meta:
            total = 0; have_all = True
            for col, key, maxpt in _RUBRIC_KEYS:
                v = (meta.get(col) or "").strip()
                if v == "":
                    have_all = False; continue
                try:
                    pt = int(float(v))
                except ValueError:
                    warns.append(f"{cid} {col} 숫자아님 '{v}' — 건너뜀"); have_all = False; continue
                if not (0 <= pt <= maxpt):
                    warns.append(f"{cid} {col} {pt} 범위(0~{maxpt}) 초과 — 건너뜀"); have_all = False; continue
                ans["rubric"][key]["점수"] = pt; total += pt
            if have_all:
                ans["rubric"]["총점"] = total
            crit_vals = {}
            for ccol, ckey in _CRIT:
                col = _find_col(list(meta.keys()), ccol)
                b = _bool(meta.get(col), warns, f"{cid} {ccol}")
                if b is not None:
                    ans["critical_errors"][ckey] = b
                crit_vals[ckey] = ans["critical_errors"].get(ckey)
            # verdict
            if ans["rubric"]["총점"] is not None and all(isinstance(v, bool) for v in crit_vals.values()):
                ans["verdict"]["pass"] = bool(ans["rubric"]["총점"] >= 80 and not any(crit_vals.values()))
                filled += 1

        if not check_only:
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    # 리포트
    print(f"{'적용' if not check_only else '검증(미적용)'} 완료 — verdict 확정 케이스: {filled}/{len(objs)}")
    if warns:
        print(f"⚠ 경고 {len(warns)}건:")
        for w in warns[:40]:
            print("  -", w)
    else:
        print("경고 없음(형식 적합).")
    return 0


if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv))
