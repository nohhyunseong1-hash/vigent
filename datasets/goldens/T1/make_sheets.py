"""강사 채점 수집표(CSV) 생성 — 저마찰 서식.

cases/*.json 을 읽어 두 개의 Excel 친화 CSV(utf-8-sig)를 만든다:
 - scoring_items.csv : (케이스×항목) 행. 강사는 ans_* 열만 채운다.
 - scoring_cases.csv : (케이스) 행. 강사는 rubric 5점수 + C1~C4 + 코멘트를 채운다.

미리 채워둔 열(참고용): case_id·item_no·check_point·scribe_적정성·scribe_위험수준·domain·process.
강사가 채우는 열은 비어 있다. 채운 뒤 merge_scores.py 로 각 케이스 JSON 에 병합한다.

실행: python3 datasets/goldens/T1/make_sheets.py
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"


def load_cases():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(CASES.glob("T1_case_*.json"))]


def scribe_row_by_cp(assessment, cp):
    for r in assessment.get("rows", []):
        if r.get("유해위험요인") == cp:
            return r
    return None


def main():
    cases = load_cases()

    # 1) 항목 수집표
    items_path = HERE / "scoring_items.csv"
    with items_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "item_no", "check_point",
                    "scribe_적정성", "scribe_위험수준",
                    "ans_적정성(O/X/−)", "ans_위험수준(상/중/하/−)",
                    "ans_법령(;구분)", "감소_제거대체(;)", "감소_공학적(;)",
                    "감소_관리적(;)", "감소_보호구(;)"])
        for c in cases:
            for i, it in enumerate(c["강사_정답"]["items"], 1):
                sr = scribe_row_by_cp(c["scribe_output"], it["check_point"])
                w.writerow([c["id"], i, it["check_point"],
                            (sr or {}).get("적정성", ""), (sr or {}).get("위험수준", ""),
                            "", "", "", "", "", "", ""])

    # 2) 케이스 수집표(rubric + 치명오류)
    cases_path = HERE / "scoring_cases.csv"
    with cases_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "domain", "process",
                    "r1_완전성_30", "r2_추정_25", "r3_대책_25",
                    "r4_법령형식_10", "r5_우선순위_10",
                    "C1_핵심위험누락(true/false)", "C2_환각(true/false)",
                    "C3_법령오인용(true/false)", "C4_2단계과소(true/false)", "코멘트"])
        for c in cases:
            w.writerow([c["id"], c["domain"], c["process"],
                        "", "", "", "", "", "", "", "", "", ""])

    print(f"생성: {items_path.relative_to(HERE.parents[2])}  ({sum(len(c['강사_정답']['items']) for c in cases)} 항목행)")
    print(f"생성: {cases_path.relative_to(HERE.parents[2])}  ({len(cases)} 케이스행)")


if __name__ == "__main__":
    main()
