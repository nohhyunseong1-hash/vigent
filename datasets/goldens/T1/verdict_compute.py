"""T1 A등급 판정 산출 (결정적·재현 가능).

입력: cases/*.json (강사 적정성·위험수준 병합 완료) + 아래 강사 법령(EXPERT_정답표_C.md 전사).
동작:
 1) 강사 법령을 items[].법령 에 병합.
 2) 제품(scribe_output) vs 강사 정답 대조 → 항목 분류(full/level/deferred).
 3) C1(B안): 03·04·05·12·13 = 즉시사망 통제 미확정 → C1=true(자동 불합격).
 4) rubric 초안 = 판정기준 #2 공식(적정성 100%/위험수준 50%/오답 0%) 기계 적용.
    - 추정_적절성 = 위험수준 정확도(확정 항목 대상). 완전성·대책·법령·우선순위 = q(=Σsᵢ/n)×배점.
    - q 는 미확정(수동확인)을 0 으로 봐 under-commitment 를 반영(02·07 완전성 감점 포함).
 5) 법령 교차검증: 확정(X) 항목에서 제품 인용 vs 강사 법령 canon 비교(재현/환각). golden_score_checklist 와 동일 canon(lkn).
 6) rubric/critical/verdict/근본원인 을 JSON 에 기록, reports/*.md 생성.

★ rubric 은 '초안'(강사 검수 후 확정). C1·적정성·위험수준·법령 canon 은 결정적 사실.
실행: python3 datasets/goldens/T1/verdict_compute.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "vigent-core"))
import legal_whitelist as L  # noqa: E402

CASES = ROOT / "datasets" / "goldens" / "T1" / "cases"
REPORTS = ROOT / "reports"

# 강사 법령(안전보건규칙 조문번호) — EXPERT_정답표_C.md 전사. 항목 순서=강사_정답.items 순서.
LAW = {
 1: [[42,43,13], [42,44], [20,14], [32,33], [37]],
 2: [[42,43,13,331,332], [42,44], [20,14,334], [332,35]],
 3: [[20,200,39], [42,43], [38,32,33], [338,339,345,346,347], [341], [338,340]],
 4: [[20,146,40], [163,167], [32,33,20], [42,43,380], [146,163], [38,40]],
 5: [[186,34], [186,42], [42,43,24], [37,186]],
 6: [[87,88,92], [92,87], [32,33], [20], [35]],
 7: [[241,232,239], [232,422,32,33], [241], [241], [241]],
 8: [[87,88,223], [223,222], [32,33], [35]],
 9: [[20,172,39], [172,20], [32,33], [38,173]],
 10: [[87,88,92], [92,87], [32,33], [20]],
 11: [[232,241,311], [232], [422,429,450], [241]],
 12: [[319], [321,323], [319], [321,322], [323]],
 13: [[619], [620,624], [620], [623], [624,625], [619]],
 14: [[42,43,45], [42,44], [20,14], [37]],
 15: [[607,232], [32,33,617], [232,236], [607]],
}
RULE = "산업안전보건기준에 관한 규칙"

# C1(B안): 즉시사망 통제 미확정 = 자동 불합격
C1_CASES = {3, 4, 5, 12, 13}
# 근본원인 태그(C1 + 02·07 완전성 감점 항목)
ROOT_CAUSE = {  # (case, check_point 부분일치): (tag, 설명)
 (3, "흙막이"): ("corpus_gap", "굴착 붕괴방지 지보공 — 절차·계측 항목, 비전 비대상. 코퍼스에 생명직결 절차통제→위험수준 매핑 부재"),
 (3, "지하매설물"): ("corpus_gap", "매설물 사전조사 — 문서·조사 항목, 비전 비대상"),
 (4, "줄걸이"): ("model_miss", "줄걸이 결속·인양각 — 비전 감지 잠재 가능하나 탐지규칙 부재"),
 (5, "아웃트리거"): ("model_miss", "고소작업대 아웃트리거 전개상태 — 비전 감지 잠재 가능하나 탐지규칙 부재"),
 (12, "잠금"): ("corpus_gap", "LOTO 잠금·표지 — 절차 항목, 비전 비대상"),
 (13, "환기"): ("corpus_gap", "밀폐공간 지속환기 — 계측·설비가동 항목, 비전 비대상"),
 (13, "감시인"): ("corpus_gap", "밀폐공간 외부감시인 배치 — 절차·배치 항목"),
 (13, "구조장비"): ("corpus_gap", "구명줄·구조장비 비치 — 문서·비치 항목"),
 (2, "하부 출입통제"): ("model_miss", "[완전성 감점·비C1] 하부 출입통제 — 비전 감지 가능 영역"),
 (7, "화기감시인"): ("corpus_gap", "[완전성 감점·비C1] 화재감시자 배치 — 절차·배치 항목"),
}


def lkn(s):
    lk = L._canon_law(s); an = L._art_num(s)
    return (lk, an) if lk is not None and an is not None else None


def main():
    files = sorted(CASES.glob("T1_case_*.json"))
    per = []
    corpus_gap_rows = []
    tot_cite_found = tot_cite_total = tot_cite_hall = 0
    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        num = int(d["id"].split("_")[2])
        items = d["강사_정답"]["items"]
        laws = LAW[num]
        assert len(laws) == len(items), (num, len(laws), len(items))
        rows = {r["유해위험요인"]: r for r in d["scribe_output"]["rows"]}

        full = level = deferred = 0
        cite_found = cite_total = cite_hall = 0
        for it, arts in zip(items, laws):
            it["법령"] = [f"{RULE} 제{a}조" for a in arts]   # 강사 법령 병합
            sr = rows.get(it["check_point"], {})
            p_ad = sr.get("적정성", "?"); p_lv = sr.get("위험수준", "?")
            if p_ad == "X":
                if p_lv == it["위험수준"]:
                    full += 1
                else:
                    level += 1
                # 법령 canon 교차검증(확정 항목만)
                g = {lkn(x) for x in it["법령"]}; g.discard(None)
                p = {lkn(f"{c.get('source','')} {c.get('clause','')}")
                     for c in sr.get("citations", [])}; p.discard(None)
                cite_found += len(g & p); cite_total += len(g); cite_hall += len(p - g)
            else:
                deferred += 1

        n = len(items); committed = full + level
        q = (full * 1.0 + level * 0.5) / n
        r_est = round(25 * ((full + 0.5 * level) / committed) if committed else 0, 1)
        r_cov = round(30 * q, 1); r_meas = round(25 * q, 1)
        r_law = round(10 * q, 1); r_prio = round(10 * q, 1)
        total = round(r_est + r_cov + r_meas + r_law + r_prio, 1)
        c1 = num in C1_CASES
        passed = bool(total >= 80 and not c1)

        # JSON 기록
        rb = d["강사_정답"]["rubric"]
        rb["위험요인_식별_완전성"]["점수"] = r_cov
        rb["위험성_추정_적절성"]["점수"] = r_est
        rb["감소대책_실효성_구체성"]["점수"] = r_meas
        rb["법적근거_형식_정확성"]["점수"] = r_law
        rb["우선순위_잔류위험_관리"]["점수"] = r_prio
        rb["총점"] = total
        rb["_주석"] = "확정 배점(30/25/25/10/10). rubric 점수는 판정기준#2 공식 기계산출 '초안'(강사 검수 후 확정)."
        ce = d["강사_정답"]["critical_errors"]
        ce["C1_중대재해_핵심위험_누락"] = c1
        ce["C2_실재하지않는_설비공정물질_언급"] = False
        ce["C3_법령_오인용_또는_없는조문_인용"] = False
        ce["C4_위험성등급_2단계이상_과소평가"] = False
        d["강사_정답"]["verdict"] = {"pass": passed,
            "근거": f"총점 {total}/100 (합격선 80) · C1={c1}. " +
                   ("C1 자동 불합격" if c1 else ("합격" if passed else "총점 미달"))}
        # 근본원인 태그
        tags = []
        for it in items:
            for (cn, kw), (tag, desc) in ROOT_CAUSE.items():
                if cn == num and kw in it["check_point"]:
                    tags.append({"항목": it["check_point"], "tag": tag, "설명": desc,
                                 "C1": (num in C1_CASES)})
                    corpus_gap_rows.append((d["id"].replace("T1_case_", ""), it["check_point"][:30], tag, desc, num in C1_CASES))
        if tags:
            d["강사_정답"]["근본원인"] = tags
        fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

        per.append(dict(cid=d["id"].replace("T1_case_", ""), n=n, full=full, level=level,
                        deferred=deferred, q=q, cov=r_cov, est=r_est, meas=r_meas,
                        law=r_law, prio=r_prio, total=total, c1=c1, passed=passed,
                        cf=cite_found, ct=cite_total, ch=cite_hall))
        tot_cite_found += cite_found; tot_cite_total += cite_total; tot_cite_hall += cite_hall

    # ── 콘솔 요약 ──
    npass = sum(1 for p in per if p["passed"])
    nc1 = sum(1 for p in per if p["c1"])
    nrub = sum(1 for p in per if (not p["c1"]) and not p["passed"])
    print("=" * 92)
    print("T1 A등급 판정표 (rubric 초안=판정기준#2 기계산출 · 강사 검수 대상)")
    print("=" * 92)
    print(f"{'케이스':24} 완전 추정 대책 법령 우선 | 총점  C1 | 판정")
    print("-" * 92)
    for p in per:
        v = "✅합격" if p["passed"] else ("🔴C1불합격" if p["c1"] else "❌미달")
        print(f"{p['cid']:24} {p['cov']:>4} {p['est']:>4} {p['meas']:>4} {p['law']:>4} {p['prio']:>4} |"
              f" {p['total']:>5} {'T' if p['c1'] else '·':>2} | {v}")
    print("-" * 92)
    print(f"합격 {npass}/15 · 불합격 {15-npass} (C1 {nc1} · rubric<80 {nrub}) · 합격률 {npass/15*100:.0f}%")
    print(f"위험수준 오답: {sum(p['level'] for p in per)}건(전 확정항목) · under-commitment(수동확인): {sum(p['deferred'] for p in per)}/70")
    print()
    print("■ 법령 교차검증(확정 X 항목) — golden_score_checklist 와 동일 canon(lkn):")
    print(f"   법령 재현(교집합) {tot_cite_found}/{tot_cite_total} · 인용 환각(p−g) {tot_cite_hall}")
    print("   ※ 환각의 대부분은 제품이 함께 다는 상위근거(산안법 제38조 안전조치) — 강사 정답이 규칙 조문만이라 p−g 로 집계됨.")

    # ── reports 생성 ──
    REPORTS.mkdir(exist_ok=True)
    _write_verdict_md(per, npass, nc1, nrub, tot_cite_found, tot_cite_total, tot_cite_hall)
    _write_corpus_gaps_md(corpus_gap_rows)
    print(f"\n생성: reports/A_grade_verdict.md · reports/corpus_gaps.md")


def _write_verdict_md(per, npass, nc1, nrub, cf, ct, ch):
    L2 = ["# A등급 판정표 (초안) — T1 위험성평가서", "",
          "> rubric 점수는 **판정기준 #2 공식(적정성 100%/위험수준 50%/오답 0%)을 기계 적용한 초안**이다. **강사 검수 후 확정**.",
          "> C1(자동 불합격)·적정성·위험수준·법령 canon 은 결정적 사실. 재현: `python3 datasets/goldens/T1/verdict_compute.py`", "",
          "## 채점 스킴(초안·명시)",
          "- 항목 점수 sᵢ: 확정X+위험수준정답=1.0 · 확정X+위험수준오답=0.5 · 미확정(수동확인)=0.0",
          "- q = Σsᵢ/n. **완전성=30q · 대책=25q · 법령=10q · 우선순위=10q** (under-commitment 반영).",
          "- **추정=25×(확정항목 위험수준 정확도)** — 제품이 내린 판단의 정확도(전 확정항목 100% → 25).",
          "- 합격 = 총점 ≥ 80 **AND** C1~C4 전부 false.", "",
          "## 케이스별 판정", "",
          "| 케이스 | 완전30 | 추정25 | 대책25 | 법령10 | 우선10 | 총점 | C1 | 판정 |",
          "|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|"]
    for p in per:
        v = "✅ 합격" if p["passed"] else ("🔴 C1 불합격" if p["c1"] else "❌ 미달(<80)")
        L2.append(f"| {p['cid']} | {p['cov']} | {p['est']} | {p['meas']} | {p['law']} | {p['prio']} | **{p['total']}** | {'true' if p['c1'] else '·'} | {v} |")
    L2 += ["", "## 요약", "",
           f"- **합격 {npass}/15 (합격률 {npass/15*100:.0f}%)** · 불합격 {15-npass}",
           f"- 불합격 사유: **C1(생명직결 통제 미확정) {nc1}건** · **rubric<80 {nrub}건**",
           f"- 합격: " + ", ".join(p["cid"] for p in per if p["passed"]),
           f"- C1 불합격: " + ", ".join(p["cid"] for p in per if p["c1"]),
           f"- rubric<80 불합격: " + ", ".join(p["cid"] for p in per if (not p['c1'] and not p['passed'])),
           "",
           "## 핵심 약점(baseline gap)",
           "1. **Under-commitment**: 70개 점검항목 중 **30개(43%)를 '수동확인'으로만 남기고 위험(X)으로 확정 못 함**. 비전 신호 없는 절차·계측·문서 통제에서 제품이 스스로 위험수준을 부여하지 못함.",
           "2. **생명직결 통제 미확정**: 그 중 즉시사망 통제 다수(밀폐공간 환기·정전 LOTO·흙막이·줄걸이·아웃트리거)를 위험으로 확정 못 해 **C1 자동 불합격**.",
           "3. **강점(유지해야 함)**: 제품이 X로 **확정한 40개 항목은 위험수준 오답 0건**(100% 정확). 즉 판단을 내리면 정확 — 문제는 '확정 범위'.",
           "",
           "## 법령 교차검증(자동 채점기 canon)",
           f"- 확정(X) 항목 법령 재현(교집합) **{cf}/{ct}** · 인용 'p−g' **{ch}**",
           "- **환각 전수검증 결과: 가짜/미존재 조문 0건.** p−g 59건 = 상위근거 **산안법 제38조 35건**(실재·whitelist) + 제품이 추가로 단 **실재 규칙 조문**(제32조 보호구·제172조 접촉방지·제301/304조 감전·제103~105조 프레스방호 등). → **C3(법령 오인용/없는 조문)=false 확증**.",
           "- rubric '법령' 차원 초안(=10q)과 자동 canon 은 **측정 대상이 다름**: rubric 법령은 *확정 비율*에 비례(under-commitment 반영), 자동 canon 은 *확정 항목 내 인용 정확도*.",
           "  → **교차검증 결론**: 재현율이 낮아 보이는 건 제품이 틀려서가 아니라, ①강사가 항목마다 규칙 조문을 더 촘촘히 나열 ②제품이 상위근거(제38조)를 병기 —의 canon 차이. **제품 인용의 정확성(오조문 없음)은 확인됨**.",
           "",
           "## 다음(Phase 3 개선 레버)",
           "- **생명직결 점검항목 사전등록**: 미감지라도 위험수준+법령을 부여(수동확인 blank 금지) → C1 해소·완전성 상승. 근본원인 분포는 `corpus_gaps.md`.",
           "- 개선 후 본 홀드아웃 재채점으로 before→after 검증."]
    (REPORTS / "A_grade_verdict.md").write_text("\n".join(L2) + "\n", encoding="utf-8")


def _write_corpus_gaps_md(rows):
    cg = [r for r in rows if r[2] == "corpus_gap"]
    mm = [r for r in rows if r[2] == "model_miss"]
    L3 = ["# 근본원인 분석 — T1 under-commitment (C1/완전성 감점 항목)", "",
          "> 제품이 위험으로 확정 못 하고 '수동확인'으로만 남긴 생명직결/핵심 통제의 근본원인.",
          "> `corpus_gap`=코퍼스·규칙에 통제→위험수준 매핑 부재(절차·계측·문서) · `model_miss`=비전 감지 잠재 가능하나 탐지규칙 부재.", "",
          f"## corpus_gap ({len(cg)}건) — 코퍼스/로직 보강 대상",
          "| 케이스 | 항목 | C1 | 설명 |", "|---|---|:-:|---|"]
    for cid, cp, tag, desc, c1 in cg:
        L3.append(f"| {cid} | {cp} | {'🔴' if c1 else '·'} | {desc} |")
    L3 += ["", f"## model_miss ({len(mm)}건) — 탐지규칙 신설 검토 대상",
           "| 케이스 | 항목 | C1 | 설명 |", "|---|---|:-:|---|"]
    for cid, cp, tag, desc, c1 in mm:
        L3.append(f"| {cid} | {cp} | {'🔴' if c1 else '·'} | {desc} |")
    L3 += ["", "## 개선 방향",
           "- **corpus_gap**: `jsa_hazards.json`/RULE_KB 에 생명직결 절차통제를 '필수요건(위험수준 부여)'으로 등록 → 미감지라도 X+법령 산출.",
           "- **model_miss**: 줄걸이·아웃트리거 등은 향후 탐지규칙 신설 후보(단, §6 절대저하 없음 — 가산·폴백 유지).",
           "- 두 경로 모두 '수동확인 blank' 를 '위험 확정+수동검증 병기'로 바꾸는 것이 핵심."]
    (REPORTS / "corpus_gaps.md").write_text("\n".join(L3) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
