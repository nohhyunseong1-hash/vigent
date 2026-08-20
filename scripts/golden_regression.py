"""AI 판단 채점 회귀 러너 (item5) — 골든 전 항목 일괄 채점 + 베이스라인 대비 회귀 감지.

★★ 베이스라인의 의미(중요): 여기 저장되는 점수는 **'회귀 감지 기준선'**(에이전트 코드 변경이
   점수를 떨어뜨렸는지)이지 **'품질 합격선'이 아니다.** 현재 점수가 '정답'이라는 검증은 없다 —
   법령재현 4/6·환각 4 같은 값이 타당한지는 별도 과제(강사 재검수·근거 확정). 이 러너는
   '무언가 나빠졌는가'만 본다. 절대 점수의 타당성 판단에 쓰지 말 것.
★ 결정성: 채점 대상 Scribe.build_checklist 는 규칙기반(RULE_KB)·Copilot 은 결정적 RAG — **VLM 미사용**.
   그래도 '가정' 대신 --variance 로 동일입력 N회 분산을 실측해 노이즈 마진을 정한다(결정적이면 0).

사용:
  python3 scripts/golden_regression.py                    # 베이스라인 대비 회귀 검사(종료코드 0/1)
  python3 scripts/golden_regression.py --variance 5       # 동일입력 5회 분산 측정(비결정성 점검)
  python3 scripts/golden_regression.py --update-baseline  # 현재 점수를 기준선으로 저장(신중히)
종료코드: 회귀 없음 0 · 회귀 감지 1 · 베이스라인 없음 2.
"""
import argparse
import json
import sys
from pathlib import Path

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden_score_checklist import _GOLD_DIR, score_checklist  # noqa: E402

ITEMS = ["item_01_crane_checklist.json", "item_02_confined_checklist.json",
         "item_03_press_checklist.json"]
BASELINE = _GOLD_DIR / "regression_baseline.json"

# 지표 방향: higher=클수록 좋음(줄면 회귀) · lower=작을수록 좋음(늘면 회귀) · 나머지=골든고정(참고)
HIGHER = ["covered", "level_ok", "hier_ok", "cite_found", "manual_shown", "blind_surfaced", "rows"]
LOWER = ["cite_hall", "false_X"]


def _score_all(verbose=False):
    return {it: score_checklist(it, verbose=False, write_md=False) for it in ITEMS}


def _variance(n):
    """동일입력 n회 → 지표별 (min,max) 범위. 결정적이면 전부 0."""
    runs = [_score_all() for _ in range(n)]
    print(f"■ 분산 측정({n}회 동일입력) — 비결정성 점검")
    max_range = {}
    for it in ITEMS:
        keys = HIGHER + LOWER
        ranges = {}
        for k in keys:
            vals = [r[it][k] for r in runs]
            rng = max(vals) - min(vals)
            if rng:
                ranges[k] = rng
            max_range[k] = max(max_range.get(k, 0), rng)
        tag = "결정적(변동 0)" if not ranges else f"변동 {ranges}"
        print(f"  {runs[0][it]['id']}: {tag}")
    noisy = {k: v for k, v in max_range.items() if v}
    print(f"■ 결론: {'전 지표 결정적 → 노이즈 마진 0' if not noisy else '변동 지표 '+str(noisy)+' → 마진 반영 필요'}")
    return max_range


def _load_baseline():
    if BASELINE.exists():
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    return None


def _check(cur, base, margin):
    """cur vs base → 회귀 목록. margin: 지표별 노이즈 마진(dict)."""
    regs = []
    for it in ITEMS:
        c, b = cur[it], base.get(cur[it]["id"]) or base.get(it)
        if not b:
            regs.append((cur[it]["id"], "베이스라인에 없음(신규 항목)"))
            continue
        for k in HIGHER:
            m = margin.get(k, 0)
            if c[k] < b[k] - m:
                regs.append((cur[it]["id"], f"{k} 하락 {b[k]}→{c[k]} (마진 {m})"))
        for k in LOWER:
            m = margin.get(k, 0)
            if c[k] > b[k] + m:
                regs.append((cur[it]["id"], f"{k} 증가 {b[k]}→{c[k]} (마진 {m}) — 악화"))
    return regs


def main():
    ap = argparse.ArgumentParser(description="골든 AI 판단 채점 회귀 러너")
    ap.add_argument("--variance", type=int, default=0, help="동일입력 N회 분산 측정(비결정성 점검)")
    ap.add_argument("--update-baseline", action="store_true", help="현재 점수를 기준선으로 저장")
    ap.add_argument("--margin", type=int, default=0, help="전 지표 공통 추가 마진(변동 대비, 기본 0)")
    a = ap.parse_args()

    print("=" * 70)
    print("골든 AI 판단 채점 회귀 러너 (item5) — 베이스라인=회귀기준선, 품질합격선 아님")
    print("=" * 70)

    margin = {}
    if a.variance:
        margin = _variance(a.variance)
        print("-" * 70)

    cur = _score_all()
    print("■ 현재 점수(전 항목)  ※ 자동판정(det_X) 0 인 항목은 O/X·법령 칸이 0/0 — 전량 수동확인 도메인")
    print(f"{'항목':<26}{'커버(rows)':>11}{'위험수준':>9}{'위계':>8}{'법령재현':>9}{'환각':>6}{'O오탐':>7}")
    for it in ITEMS:
        m = cur[it]
        cov = f"{m['rows']}/{m['items']}"
        lvl = f"{m['level_ok']}/{m['covered']}"
        hie = f"{m['hier_ok']}/{m['covered']}"
        cit = f"{m['cite_found']}/{m['cite_total']}"
        print(f"{m['id']:<26}{cov:>11}{lvl:>9}{hie:>8}{cit:>9}{m['cite_hall']:>6}{m['false_X']:>7}")

    if a.update_baseline:
        BASELINE.write_text(json.dumps({cur[it]["id"]: cur[it] for it in ITEMS},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        print("-" * 70)
        print(f"✅ 베이스라인 저장: {BASELINE}")
        print("   (주의: 이 값은 '현재 상태 고정'일 뿐 '정답 확정'이 아님 — 절대점수 타당성은 별도 과제)")
        return 0

    base = _load_baseline()
    if base is None:
        print("-" * 70)
        print("⚠ 베이스라인 없음 → --update-baseline 로 먼저 기준선을 저장하라.")
        return 2

    # 공통 마진 반영
    if a.margin:
        for k in HIGHER + LOWER:
            margin[k] = max(margin.get(k, 0), a.margin)
    regs = _check(cur, base, margin)
    print("-" * 70)
    if not regs:
        print("✅ 회귀 없음 — 전 항목 지표가 베이스라인 이상(악화 지표 증가 없음).")
        print("   (합격이 아니라 '나빠지지 않음'. 절대 품질은 강사 재검수 대상.)")
        return 0
    print(f"❌ 회귀 감지 {len(regs)}건:")
    for iid, msg in regs:
        print(f"  [{iid}] {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
