#!/usr/bin/env python3
"""scripts/report/status_graphs_20260928.py — STATUS_REPORT_20260928.md 의 그래프 6장(a~f)을 추적 파일에서 재생성한다. [2026-09-28]

입력(전부 저장소 추적 파일): benchmarks/results/{v1_heldout_eval.json, ppe_compare_*.json, ppe_smoke_*/dev74_fair_noMask.json,
  forklift_v1_baseline.json, forklift_fk_510_smoke_20260926/harness.json, status_20260928/data/{bench4ch_*.csv, person_box_sizes.json}}
  + 공개 데이터 시점 비율(docs/data/public_ppe_candidates_20260927.md 의 표를 그대로 옮긴 상수 VIEWPOINT).
출력: benchmarks/results/status_20260928/{a_forklift_before_after,b_ppe_v1_recall,c_ppe_history,d_bench_4ch,e_viewpoint_ratio,f_person_box_sizes}.png
사용: python scripts/report/status_graphs_20260928.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent.parent
R = _ROOT / "benchmarks" / "results"; OUT = R / "status_20260928"; OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "Malgun Gothic", "axes.unicode_minus": False, "figure.dpi": 130, "savefig.dpi": 160,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#9a9891", "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "font.size": 9})
BLUE, ORANGE, AQUA, YELLOW, RED, GRAY, INK = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e34948", "#b9b7ae", "#0b0b0b"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round((c - h) * 100, 1), round((c + h) * 100, 1))


def err(v, ci):
    return [[v - ci[0]], [ci[1] - v]]


def bars_ci(ax, x, vals, cis, color, label=None, width=0.36):
    ax.bar(x, vals, width=width, color=color, label=label, edgecolor="#fcfcfb", linewidth=0.8, zorder=3)
    lo = [v - c[0] for v, c in zip(vals, cis)]; hi = [c[1] - v for v, c in zip(vals, cis)]
    ax.errorbar(x, vals, yerr=[lo, hi], fmt="none", ecolor=INK, elinewidth=1, capsize=3, zorder=4)


def row(d, cls):
    return next(r for r in d["rows"] if r["class"] == cls)


# ── a. forklift 전/후 ─────────────────────────────────────────────────────────────────────────────────────────────
def fig_a():
    v1 = json.loads((R / "forklift_v1_baseline.json").read_text(encoding="utf-8"))["s510"]
    fk = json.loads((R / "forklift_fk_510_smoke_20260926" / "harness.json").read_text(encoding="utf-8"))["s510"]
    keys = [("ap50", "AP50"), ("recall", "재현율 @0.5"), ("precision", "정밀도 @0.5"), ("neg_fp_rate", "음성 오탐률\n(지게차 없는 101장)")]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    x = list(range(len(keys)))
    bars_ci(ax, [i - 0.2 for i in x], [v1[k] for k, _ in keys], [v1[k + "_ci95"] for k, _ in keys], GRAY, "전: forklift_rfdetr_v1")
    bars_ci(ax, [i + 0.2 for i in x], [fk[k] for k, _ in keys], [fk[k + "_ci95"] for k, _ in keys], BLUE, "후: fk510_smoke")
    for i, (k, _) in enumerate(keys):
        ax.text(i - 0.2, v1[k] + 2.5, f"{v1[k]}", ha="center", fontsize=8, color=INK); ax.text(i + 0.2, fk[k] + 2.5, f"{fk[k]}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x); ax.set_xticklabels([n for _, n in keys]); ax.set_ylim(0, 108); ax.set_ylabel("%")
    ax.set_title(f"a. forklift 전/후 — AI Hub 510 held-out {fk['images']:,}장(GT {fk['gt']:,}) · 오차막대 95%(AP50 부트스트랩, 나머지 Wilson)", fontsize=9, loc="left")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2); fig.tight_layout(); fig.savefig(OUT / "a_forklift_before_after.png"); plt.close(fig)


# ── b. PPE v1 클래스별 재현율 + 합격선 ────────────────────────────────────────────────────────────────────────────
def fig_b():
    d = json.loads((R / "v1_heldout_eval.json").read_text(encoding="utf-8"))
    order = ["Person", "Hardhat", "NO-Hardhat", "Safety Vest", "NO-Safety Vest", "Mask", "NO-Mask", "Safety Cone", "machinery", "vehicle"]
    goals = {"NO-Hardhat": 85, "NO-Safety Vest": 90}
    fig, ax = plt.subplots(figsize=(8.4, 3.9)); x = list(range(len(order)))
    vals = [row(d, c)["recall"] for c in order]; cis = [row(d, c)["recall_ci95"] for c in order]
    cols = [ORANGE if c in goals else (BLUE if c in ("Person", "Hardhat", "Safety Vest") else GRAY) for c in order]
    ax.bar(x, vals, width=0.62, color=cols, zorder=3, edgecolor="#fcfcfb")
    ax.errorbar(x, vals, yerr=[[v - c[0] for v, c in zip(vals, cis)], [c[1] - v for v, c in zip(vals, cis)]], fmt="none", ecolor=INK, elinewidth=1, capsize=3, zorder=4)
    for i, c in enumerate(order):
        ax.text(i, 2, f"n={row(d, c)['gt']}", ha="center", fontsize=7, color="#52514e")
        if c in goals:
            ax.hlines(goals[c], i - 0.42, i + 0.42, colors=RED, linestyles="--", linewidth=1.6, zorder=5)
            ax.text(i, goals[c] + 1.5, f"합격선 {goals[c]}", ha="center", fontsize=7.5, color=RED)
    ax.set_xticks(x); ax.set_xticklabels(order, rotation=20, ha="right"); ax.set_ylim(0, 105); ax.set_ylabel("재현율 % @conf 0.35")
    ax.set_title(f"b. PPE v1 클래스별 재현율 — CSS held-out {d['heldout']['heldout_images']}장({d['date'][:10]}), 오차막대 = Wilson 95%", fontsize=9.5, loc="left")
    ax.legend(handles=[Patch(color=BLUE, label="착용·사람"), Patch(color=ORANGE, label="미착용(합격선 대상)"), Patch(color=GRAY, label="우리 정책 밖 클래스"),
                       plt.Line2D([], [], color=RED, ls="--", label="합격선(NO-Hardhat 85 · NO-SV 90)")], frameon=False, fontsize=7.5, loc="upper right")
    fig.tight_layout(); fig.savefig(OUT / "b_ppe_v1_recall.png"); plt.close(fig)


# ── c. PPE 실험 이력 ──────────────────────────────────────────────────────────────────────────────────────────────
def fig_c():
    runs = [("v1", "ppe_rfdetr_v1", None, False), ("A", "ppe_507_v2", "ppe_smoke_A_20260927", True), ("B", "ppe_507_v2B", "ppe_smoke_B_20260927", True),
            ("D", "ppe_D_css_only", "ppe_smoke_D_20260927", True), ("A'", "ppe_A2_slot", "ppe_smoke_A2_20260927", False), ("E", "ppe_E_coco", "ppe_smoke_E_20260927", False)]
    held = []; dev = []
    for tag, f, sm, bad in runs:
        d = json.loads((R / f"ppe_compare_{f}.json").read_text(encoding="utf-8"))["candidate"]; r = row(d, "NO-Hardhat"); held.append((r["recall"], r["recall_ci95"]))
        if sm is None:
            dev.append((144, 231))          # v1 dev74 Mask 제외 = 144/231 (ppe_smoke_*/dev74_fair_noMask.json 의 v1_noMask 공통값)
        else:
            j = json.loads((R / sm / "dev74_fair_noMask.json").read_text(encoding="utf-8")); k = [k for k in j if k.endswith("_noMask") and not k.startswith("v1")][0]
            dev.append((j[k]["ppe_tp"], j[k]["ppe_gt"]))
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.8)); x = list(range(len(runs)))
    panels = ((axes[0], "held-out 91 NO-Hardhat 재현율 % (n=64, Wilson 95%)", [h[0] for h in held], [h[1] for h in held]),
              (axes[1], "사고영상 dev74 PPE 재현율 % (Mask 제외, GT 231, Wilson 95%)", [round(t / n * 100, 1) for t, n in dev], [wilson(t, n) for t, n in dev]))
    for ax, title, vals, cis in panels:
        for i, (tag, _, _, bad) in enumerate(runs):
            ax.bar(i, vals[i], width=0.62, color=GRAY if bad else (BLUE if tag == "v1" else AQUA), hatch="///" if bad else None, edgecolor=GRAY if bad else "#fcfcfb", zorder=3)
            ax.errorbar(i, vals[i], yerr=err(vals[i], cis[i]), fmt="none", ecolor=INK, elinewidth=1, capsize=3, zorder=4)
            ax.text(i, cis[i][1] + 1.5, f"{vals[i]}", ha="center", fontsize=8, color=INK)
        ax.set_xticks(x); ax.set_xticklabels([r[0] for r in runs]); ax.set_ylim(0, 100); ax.set_ylabel("재현율 %"); ax.set_title(title, fontsize=9, loc="left")
    axes[0].hlines(85, -0.5, 5.5, colors=RED, ls="--", lw=1.4); axes[0].text(5.5, 86, "합격선 85", ha="right", fontsize=7.5, color=RED)
    axes[1].hlines(80, -0.5, 5.5, colors=RED, ls="--", lw=1.4); axes[1].text(5.5, 81, "목표 80", ha="right", fontsize=7.5, color=RED)
    fig.legend(handles=[Patch(color=BLUE, label="v1(현행)"), Patch(color=AQUA, label="유효 실험(A' 슬롯 정렬 · E COCO 새로)"), Patch(facecolor=GRAY, hatch="///", edgecolor=GRAY, label="결함 run(A·B·D 슬롯 어긋남 → 무효)")],
               frameon=False, loc="lower center", ncol=3, fontsize=8, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("c. PPE 재학습 실험 이력(2026-09-27) — 유효 실험 2회 모두 v1 구간 안 → 정지 규칙, v1 유지", fontsize=9.5, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.07, 1, 0.95)); fig.savefig(OUT / "c_ppe_history.png"); plt.close(fig)


# ── d. 4ch 벤치 3회 시계열 ────────────────────────────────────────────────────────────────────────────────────────
def fig_d():
    files = sorted((OUT / "data").glob("bench4ch_fk2_academy_torch_r_r*.csv")); cols = [BLUE, ORANGE, AQUA]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.4))
    for f, col in zip(files, cols):
        rows = [r for r in csv.DictReader(f.open(encoding="utf-8-sig")) if r.get("phase") == "soak"]
        t = [float(r["elapsed_s"]) / 60 for r in rows]; cpu = [float(r["sys_cpu_pct"]) for r in rows]
        age = [max(float(r[f"pilot0{i}.age_p95"]) for i in range(1, 5)) for r in rows]; vram = [float(r["vram_used_mb"]) / 1024 for r in rows]
        lab = f.stem.split("_r_")[1].split("_")[0]
        for ax, y in zip(axes, (cpu, age, vram)):
            ax.plot(t, y, color=col, lw=2, marker="o", ms=4, label=lab)
    for ax, title, ylab, ylim in zip(axes, ("시스템 CPU %", "검출 age p95 (4카메라 최악, s)", "GPU VRAM nvidia-smi (GB)"), ("%", "s", "GB"), ((0, 60), (0, 1.2), (0, 4.5))):
        ax.set_title(title, fontsize=9, loc="left"); ax.set_xlabel("경과 분"); ax.set_ylabel(ylab); ax.set_ylim(*ylim)
    axes[1].hlines(1.0, 0, 30, colors=RED, ls="--", lw=1.2); axes[1].text(29.5, 1.03, "합격선 ≤1.0 s", ha="right", fontsize=7.5, color=RED)
    axes[2].hlines(4.0, 0, 30, colors=RED, ls="--", lw=1.2); axes[2].text(29.5, 4.05, "노트북 GTX 1650 Ti 4 GB", ha="right", fontsize=7.5, color=RED)
    axes[0].legend(frameon=False, title="회차", fontsize=8)
    fig.suptitle("d. 4채널 2fps 30분 벤치 3회(2026-09-27, RTX 5070 Ti, 학원 프로파일 fk510_smoke) — 창 5분, 각 회 n=7 창", fontsize=9.5, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.94)); fig.savefig(OUT / "d_bench_4ch.png"); plt.close(fig)


# ── e. 데이터 시점 분포 ───────────────────────────────────────────────────────────────────────────────────────────
VIEWPOINT = [  # (이름, 감시 시점 장수, 표본 장수, 비고) — docs/data/public_ppe_candidates_20260927.md · aihub_data_review_163_20260927.md [육안]
    ("CSS v27 held-out(우리 학습셋)", 0, 30, ""), ("AI Hub 163 원천", 0, 174, "1인칭 액션캠"), ("SHWD 200장 전체", 48, 200, "전부 교실 CCTV, 안전모 0"), ("SHWD 안전모 프레임", 0, 89, ""),
    ("RF hardhat-safetyvest", 4, 30, "전부 SCUT 교실"), ("RF hard-hat-workers", 0, 30, ""), ("RF no-hard-hat", 4, 30, ""), ("RF ppe-construction-v2", 5, 30, ""),
    ("RF helmet-detection-v3", 0, 30, "CSS 사본"), ("RF ppe-v1.1", 0, 30, ""), ("RF helmet-0xjjk", 0, 30, "오토바이"), ("RF new-ppe", 0, 30, ""), ("RF safety-vests", 2, 30, ""),
]
UNMEASURED = ["AI Hub 507(근접 3인칭, 시점 비율 미측정)", "AI Hub 510(근접, 미측정)", "RF ppe-detection-q897z(export 불가)"]


def fig_e():
    fig, ax = plt.subplots(figsize=(8.6, 4.6)); names = [v[0] for v in VIEWPOINT]; vals = [round(k / n * 100, 1) for _, k, n, _ in VIEWPOINT]
    y = list(range(len(names)))[::-1]
    ax.barh(y, vals, color=[BLUE if n.startswith("CSS") else ORANGE for n in names], height=0.62, zorder=3, edgecolor="#fcfcfb")
    for yi, (nm, k, n, note), v in zip(y, VIEWPOINT, vals):
        ax.text(v + 0.8, yi, f"{v}%  ({k}/{n})" + (f"  {note}" if note else ""), va="center", fontsize=7.5, color=INK)
    ax.axvline(50, color=RED, ls="--", lw=1.4); ax.text(50.5, len(names) - 0.6, "판정 기준 ≥50%", color=RED, fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8); ax.set_xlim(0, 100); ax.set_xlabel("고정 감시카메라 시점 프레임 비율 % [육안, 표본]")
    ax.set_title("e. 학습 후보 데이터의 감시 시점 비율 — 최고 24%(SHWD 전체, 그마저 안전모 없는 교실), 기준 50% 미달 전부", fontsize=9.5, loc="left")
    fig.text(0.01, 0.01, "미측정(표본 시점 분류 안 함): " + " · ".join(UNMEASURED), ha="left", fontsize=7, color="#52514e")
    fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(OUT / "e_viewpoint_ratio.png"); plt.close(fig)


# ── f. 사람 박스 크기 분포 ────────────────────────────────────────────────────────────────────────────────────────
def _stats(v, label):
    v = sorted(v); n = len(v)

    def pick(p):
        return v[min(n - 1, int(n * p))]
    return {"label": f"{label}\n(n={n:,})", "whislo": pick(.1), "q1": pick(.25), "med": pick(.5), "q3": pick(.75), "whishi": pick(.9), "fliers": []}


def fig_f():
    d = json.loads((OUT / "data" / "person_box_sizes.json").read_text(encoding="utf-8"))
    q = d["aihub507_WO01_person_px_quantiles_1080"]
    s507 = {"label": f"AI Hub 507 WO-01\n(n={q['n']:,}, 분위수)", "whislo": q["p10"] / 1080, "q1": q["p25"] / 1080, "med": q["median"] / 1080, "q3": q["p75"] / 1080, "whishi": q["p90"] / 1080, "fliers": []}
    boxes = [s507, _stats(d["css_train_person"], "CSS v27 train Person"), _stats(d["css_heldout91_person"], "CSS held-out 91 Person"), _stats(d["dev_person"], f"사고영상 dev {d['dev_images']}장 person")]
    fig, ax = plt.subplots(figsize=(8.2, 4.2))
    ax.axhspan(26 / 720, 64 / 720, color=AQUA, alpha=0.18, zorder=1); ax.text(0.55, 64 / 720 + 0.012, "현장 CCTV 작업자 26~64 px @720p(학원 2026-08-27)", ha="left", fontsize=7.5, color="#0f7a55")
    bp = ax.bxp(boxes, showfliers=False, widths=0.5, patch_artist=True, zorder=3)
    for b, c in zip(bp["boxes"], [ORANGE, BLUE, BLUE, YELLOW]):
        b.set(facecolor=c, edgecolor=INK, linewidth=0.8)
    for m in bp["medians"]:
        m.set(color=INK, linewidth=1.4)
    ax.set_ylabel("사람 박스 높이 / 이미지 높이"); ax.set_ylim(0, 0.8); ax.set_yticks([0, .1, .2, .3, .4, .5, .6, .7, .8])
    ax.set_title("f. 사람 박스 크기 분포 — 상자 = p25~p75, 선 = 중앙값, 수염 = p10~p90 (507 은 저장된 분위수)", fontsize=9.5, loc="left")
    fig.tight_layout(); fig.savefig(OUT / "f_person_box_sizes.png"); plt.close(fig)


def main() -> int:
    for f in (fig_a, fig_b, fig_c, fig_d, fig_e, fig_f):
        f(); print("saved", f.__name__)
    pngs = sorted(OUT.glob("*.png")); bad = [p.name for p in pngs if p.stat().st_size < 10000]
    print(f"{len(pngs)} png · 10KB 미만 {bad}"); return 1 if len(pngs) != 6 or bad else 0


if __name__ == "__main__":
    sys.exit(main())
