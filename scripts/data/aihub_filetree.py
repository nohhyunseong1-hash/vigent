#!/usr/bin/env python3
"""scripts/data/aihub_filetree.py — aihubshell `-mode l` 트리 출력(filetree_<ds>.txt)을 경로 있는 표로 만들고, 라벨/원천을 **경로·이름으로 추정**해 가장 작은 라벨 zip 을 고른다. [2026-09-27]

왜: 507/510 은 파일명이 TL_/VL_/VS_ 로 시작해 이름만으로 라벨/원천을 알 수 있었지만, 163 같은 구형 데이터셋은 파일명이 '1.공동주택.zip' 식이고
    **상위 폴더명**('라벨링데이터_241008_add', '원천데이터(zip)')에만 구분이 있다. 그래서 들여쓰기(트리 문자)로 경로를 복원해 조상 폴더명까지 본다.
판정(추정 표시): 경로에 라벨|label|annotation|json|TL_|VL_ → 라벨 · 원천|source|raw|VS_|TS_|image|img → 원천 · 그 외 미상.
사용: python scripts/data/aihub_filetree.py D:/vigent_private_data/aihub/filetree_163.txt [--max-gb 2] [--md out.md] [--pick]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UNIT = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4, "B": 1}
LABEL_PAT = re.compile(r"라벨|label|annotation|json|(^|[/_])TL_|(^|[/_])VL_", re.I)
SOURCE_PAT = re.compile(r"원천|source|raw|(^|[/_])VS_|(^|[/_])TS_|image|img", re.I)
_TREE = re.compile(r"^([\s│├└─]*)(.*)$")


def parse_tree(text: str) -> list[dict]:
    """트리 텍스트 → [{path, name, size_bytes, size_str, key}] (파일 줄만). 들여쓰기 폭으로 깊이를 잡고 폴더 스택을 유지한다."""
    stack: list[tuple[int, str]] = []
    out: list[dict] = []
    for raw in text.splitlines():
        m = _TREE.match(raw.rstrip())
        prefix, body = m.group(1), m.group(2).strip()
        if not body or " | " not in body and not re.search(r"[│├└─]", raw):
            continue                                            # 머리말(버전·공지·안내) — 트리 글자 없는 줄은 폴더가 아니다
        depth = len(prefix)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if " | " in body and body.count("|") >= 2:            # 파일 줄: 이름 | 크기 | 파일키
            name, size, key = [p.strip() for p in body.split("|")[:3]]
            num, unit = size.split()[0], (size.split()[1] if len(size.split()) > 1 else "B")
            try:
                size_bytes = int(float(num) * UNIT.get(unit.upper(), 1))
            except ValueError:
                size_bytes = -1
            out.append({"path": "/".join(s for _, s in stack), "name": name, "size_bytes": size_bytes, "size_str": size, "key": key})
        else:
            stack.append((depth, body))
    return out


def classify(item: dict) -> str:
    full = f"{item['path']}/{item['name']}"
    if LABEL_PAT.search(full):
        return "라벨(추정)"
    if SOURCE_PAT.search(full):
        return "원천(추정)"
    return "미상"


def pick_smallest_label(items: list[dict], max_gb: float | None) -> dict | None:
    labels = [i for i in items if classify(i) == "라벨(추정)" and i["size_bytes"] >= 0 and i["name"].lower().endswith(".zip")]
    if max_gb is not None:
        within = [i for i in labels if i["size_bytes"] <= max_gb * UNIT["GB"]]
        labels = within or labels           # 조건 안이 없으면 가장 작은 것
    return min(labels, key=lambda i: i["size_bytes"]) if labels else None


def to_markdown(items: list[dict], title: str) -> str:
    lines = [f"# {title}", "", "| # | 구분 | 경로 | 파일명 | 크기 | 파일키 |", "|---|---|---|---|---|---|"]
    for n, i in enumerate(items, 1):
        lines.append(f"| {n} | {classify(i)} | {i['path']} | {i['name']} | {i['size_str']} | {i['key']} |")
    n_l = sum(1 for i in items if classify(i).startswith("라벨")); n_s = sum(1 for i in items if classify(i).startswith("원천"))
    tot = sum(i["size_bytes"] for i in items if i["size_bytes"] > 0) / UNIT["GB"]
    lines += ["", f"파일 {len(items)}개 · 라벨(추정) {n_l} · 원천(추정) {n_s} · 미상 {len(items) - n_l - n_s} · 표기 용량 합 ≈ {tot:.1f} GB. 구분은 경로·이름의 낱말(라벨/원천/label/source/TL_/VS_ …)로 **추정**한 것이다."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree"); ap.add_argument("--max-gb", type=float, default=2.0); ap.add_argument("--md", default=""); ap.add_argument("--pick", action="store_true")
    ap.add_argument("--ds", default="")
    a = ap.parse_args()
    items = parse_tree(Path(a.tree).read_text(encoding="utf-8", errors="replace"))
    if a.md:
        Path(a.md).write_text(to_markdown(items, f"AI Hub {a.ds or Path(a.tree).stem} 파일 목록(aihubshell -mode l, {Path(a.tree).name})"), encoding="utf-8")
        print(f"표 저장 → {a.md} ({len(items)} 파일)")
    if a.pick:
        best = pick_smallest_label(items, a.max_gb)
        if not best:
            print("★라벨로 볼 zip 이 없다 — 목록을 눈으로 확인"); return 4
        print(f"선택: 파일키 {best['key']}  {best['path']}/{best['name']}  {best['size_str']}")
        print(f"KEY={best['key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
