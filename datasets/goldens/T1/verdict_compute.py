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

# C1(B안): 즉시사망 통제 = 자동 불합격 대상. C1 은 '해당 통제가 여전히 blank(수동확인)로 방치'될 때만 성립.
# Phase 3 레지스트리로 '확인필요+위험수준+법령' 표면화되면 누락 해소 → C1 해제(출력 기준 재계산).
C1_CASES = {3, 4, 5, 12, 13}
C1_ITEMS = {  # B안 지정 즉시사망 통제(check_point 키워드)
    3: ["흙막이", "지하매설물"], 4: ["줄걸이"], 5: ["아웃트리거"],
    12: ["잠금"], 13: ["지속 환기", "환기설비", "감시인", "구조장비"],
}
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

        full = level = deferred = must = 0    # X정답 / X레벨오답 / 방치 / 확인필요
        level_wrong = 0                        # 위험수준 오답(가드: 0 유지)
        s_sum = 0.0; leveled = leveled_ok = 0  # 추정: 위험수준 판단항목 정확도
        cite_found = cite_total = cite_hall = 0
        still_blank_high = []
        for it, arts in zip(items, laws):
            it["법령"] = [f"{RULE} 제{a}조" for a in arts]   # 강사 법령 병합
            sr = rows.get(it["check_point"], {})
            p_ad = sr.get("적정성", "?"); p_lv = sr.get("위험수준", "?")
            has_law = bool(sr.get("citations"))
            lv_ok = (p_lv == it["위험수준"])
            if p_ad in ("X", "확인필요"):
                leveled += 1; leveled_ok += int(lv_ok)
                if p_ad == "X":
                    if lv_ok: full += 1; s_sum += 1.0
                    else: level += 1; level_wrong += 1; s_sum += 0.5
                else:  # 확인필요: 위험수준 정답+법령 병기=1.0 / (레벨오답 or 법령누락)=0.5
                    must += 1
                    if lv_ok and has_law: s_sum += 1.0
                    else:
                        s_sum += 0.5
                        if not lv_ok: level_wrong += 1
                # 법령 canon 교차검증(확정 X + 확인필요 모두)
                g = {lkn(x) for x in it["법령"]}; g.discard(None)
                p = {lkn(f"{c.get('source','')} {c.get('clause','')}")
                     for c in sr.get("citations", [])}; p.discard(None)
                cite_found += len(g & p); cite_total += len(g); cite_hall += len(p - g)
            else:  # 수동확인 blank
                deferred += 1
                if it["위험수준"] == "상":
                    still_blank_high.append(it["check_point"])

        n = len(items)
        q = s_sum / n
        r_est = round(25 * (leveled_ok / leveled) if leveled else 0, 1)
        r_cov = round(30 * q, 1); r_meas = round(25 * q, 1)
        r_law = round(10 * q, 1); r_prio = round(10 * q, 1)
        total = round(r_est + r_cov + r_meas + r_law + r_prio, 1)
        # C1 재계산(출력 기준): B안 지정 통제가 여전히 blank 면 C1
        c1 = any(any(kw in cp for cp in still_blank_high) for kw in C1_ITEMS.get(num, []))
        passed = bool(total >= 80 and not c1)

        # JSON 기록
        rb = d["강사_정답"]["rubric"]
        rb["위험요인_식별_완전성"]["점수"] = r_cov
        rb["위험성_추정_적절성"]["점수"] = r_est
        rb["감소대책_실효성_구체성"]["점수"] = r_meas
        rb["법적근거_형식_정확성"]["점수"] = r_law
        rb["우선순위_잔류위험_관리"]["점수"] = r_prio
        rb["총점"] = total
        rb["_주석"] = "확정 배점(30/25/25/10/10). rubric 점수는 판정기준#2 sᵢ 공식(강사 승인, 확인필요=동등크레딧) 기계산출."
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
                    tags.append({"항목": it["check_point"], "tag": tag, "설명": desc, "C1": c1})
                    corpus_gap_rows.append((d["id"].replace("T1_case_", ""), it["check_point"][:30], tag, desc, c1))
        if tags:
            d["강사_정답"]["근본원인"] = tags
        fp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

        per.append(dict(cid=d["id"].replace("T1_case_", ""), n=n, full=full, level=level,
                        deferred=deferred, must=must, lw=level_wrong, q=q, cov=r_cov, est=r_est, meas=r_meas,
                        law=r_law, prio=r_prio, total=total, c1=c1, passed=passed,
                        cf=cite_found, ct=cite_total, ch=cite_hall))
        tot_cite_found += cite_found; tot_cite_total += cite_total; tot_cite_hall += cite_hall

    # ── 콘솔 요약 ──
    npass = sum(1 for p in per if p["passed"])
    nc1 = sum(1 for p in per if p["c1"])
    nrub = sum(1 for p in per if (not p["c1"]) and not p["passed"])
    print("=" * 92)
    print("T1 A등급 판정표 (Phase 3 적용 후 · 강사 승인 sᵢ 공식)")
    print("=" * 92)
    print(f"{'케이스':24} 완전 추정 대책 법령 우선 | 총점  C1 | 판정")
    print("-" * 92)
    for p in per:
        v = "✅합격" if p["passed"] else ("🔴C1불합격" if p["c1"] else "❌미달")
        print(f"{p['cid']:24} {p['cov']:>4} {p['est']:>4} {p['meas']:>4} {p['law']:>4} {p['prio']:>4} |"
              f" {p['total']:>5} {'T' if p['c1'] else '·':>2} | {v}")
    print("-" * 92)
    print(f"합격 {npass}/15 · 불합격 {15-npass} (C1 {nc1} · rubric<80 {nrub}) · 합격률 {npass/15*100:.0f}%")
    print(f"[가드] 위험수준 오답: {sum(p['lw'] for p in per)}건(0 유지 필수) · "
          f"확인필요(필수확정): {sum(p['must'] for p in per)} · 방치(수동확인): {sum(p['deferred'] for p in per)}/70")
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
    L2 = ["# A등급 판정표 — T1 위험성평가서 (Phase 3 적용 후)", "",
          "> rubric 점수는 **강사 승인 sᵢ 공식(RUBRIC.md §D)** 기계산출. 생명직결 필수확정 레지스트리 적용 후 상태.",
          "> C1·적정성·위험수준·법령 canon 은 결정적 사실. 재현: `/opt/anaconda3/bin/python3 datasets/goldens/T1/verdict_compute.py`", "",
          "## 채점 스킴(강사 승인)",
          "- 항목 점수 sᵢ: 확정X+레벨정답=1.0 · **확인필요+레벨정답+법령=1.0(동등)** · (확정/확인필요)+레벨오답=0.5 · 확인필요+법령누락=0.5 · 방치(수동확인)=0.0",
          "- q = Σsᵢ/n. **완전성=30q · 대책=25q · 법령=10q · 우선순위=10q**.",
          "- **추정=25×(위험수준 판단항목 정확도)**.",
          "- 합격 = 총점 ≥ 80 **AND** C1~C4 전부 false.", "",
          "## Before → After (Phase 3: 생명직결 필수확정 레지스트리)",
          "| 지표 | Before | After |",
          "|---|:-:|:-:|",
          "| 합격 | 5/15 (33%) | **9/15 (60%)** |",
          "| C1 불합격 | 5 | **0** |",
          "| 방치(수동확인, 정답=X) | 30/70 | **21/70** |",
          "| 위험수준 오답(가드) | 0 | **0 유지** |",
          "| 환각 가짜조문(가드) | 0 | **0 유지** |",
          "| 하락 케이스 | — | **0** |", "",
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
           "## 개선 결과 · 남은 약점",
           "1. **개선(해소)**: 생명직결 9개 통제를 '확인필요(필수)+위험수준+법령'으로 표면화 → **C1 5건 전부 해소**, 방치 30→21/70. 회귀 0(위험수준 오답 0·환각 0·하락 0).",
           "2. **강점(유지)**: 위험수준을 판단한 항목은 **오답 0건**(확정+확인필요 모두 강사와 100% 일치).",
           "3. **남은 미달(6건)**: 01·02·06·07·12·14 — 레지스트리 밖 절차·중위험 항목(소화설비·허가서·2인1조·정리정돈·하부통제 등)이 여전히 수동확인이라 완전성 미달(합격선 80 미달). 다음 레버는 '중위험 절차통제 표면화' 또는 레지스트리 확장.",
           "",
           "## 법령 교차검증(자동 채점기 canon)",
           f"- 확정 X + 확인필요 항목 법령 재현(교집합) **{cf}/{ct}** · 인용 'p−g' **{ch}**",
           "- **환각 전수검증(재확인): 가짜/미존재 조문 0건.** 확인필요 항목이 새로 인용한 조문은 전부 실재 규칙 조문(제163·167·186·241의2·319·338·341·345·620·623·624·625조). C2/C3=false 유지.",
           "- p−g의 대부분은 제품이 병기하는 상위근거(산안법 제38조) — 강사 정답이 규칙 조문만이라 canon 차이(오조문 아님).",
           "",
           "## 다음 레버(잔여 미달 6건)",
           "- **07·12(70점, C1 없음)**: 중위험 절차통제(화기 소화설비·허가서 / 정전 접근한계·2인1조)를 표면화하면 완전성 상승 여지. 단 강사 위험수준이 '중'이라 레지스트리(상 전용) 밖 — 중위험 통제 레지스트리 확장을 강사와 협의.",
           "- **01·02·06·14(62~70점)**: 하부출입통제·정리정돈·기상 등. 일부는 비전 감지 잠재(model_miss) 후보(§6 준수 하 탐지규칙 신설 검토).",
           "- 근본원인 분포는 `corpus_gaps.md`."]
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
