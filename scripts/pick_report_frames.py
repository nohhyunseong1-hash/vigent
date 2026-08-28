#!/usr/bin/env python3
"""[보고서] 캡션 조건을 **좌표로 검증한** 프레임만 골라 사진으로 뽑는다.

2026-08-27 실수 교훈: 스틸(5초 간격)을 "경과시간÷5"로 어림잡아 골랐더니 캡션과
다른 순간의 사진이 붙었다("탑승"이라 썼는데 사람이 지게차 옆에 서 있는 사진).
보고서 사진은 **설명과 같은 순간**이어야 한다 — 아니면 문서 전체 신뢰가 무너진다.

해결: overlay.mp4 의 N번째 프레임은 dets.jsonl 의 N번째 줄과 1:1 대응한다(같은 루프에서
쓴다). 그래서 조건을 만족하는 줄 번호를 찾아 그 프레임을 직접 뽑는다.

사용: python scripts/pick_report_frames.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
F = ROOT / "runs" / "field_20260827"
OUT = F / "report_frames"
ONBOARD = 0.65        # proximity.driver_containment — 탑승 판정 임계
# 사람 발끝이 지게차 바닥보다 이만큼 아래면 '지면에 선 사람'으로 본다.
#   2026-08-27 육안 대조로 정한 값 — 0.03 은 발판에 올라선 '승차 중'까지 잡아 과대계상됐다.
#   0.10 이상인 프레임은 16장 중 11장이었고, 전부 지면에 선 사람으로 확인됐다.
GROUND_MARGIN = 0.10


def rows(scene: str) -> list[dict]:
    p = F / scene / "dets.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def boxes(r: dict, cls: str) -> list[list[float]]:
    return [d["bbox"] for d in (r.get("detections") or []) if d.get("class") == cls]


def has(r: dict, cls: str) -> bool:
    return bool(boxes(r, cls))


def containment(p: list[float], f: list[float]) -> float:
    ix1, iy1 = max(p[0], f[0]), max(p[1], f[1])
    ix2, iy2 = min(p[2], f[2]), min(p[3], f[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    return inter / max(1e-9, (p[2] - p[0]) * (p[3] - p[1]))


def best_onboard(r: dict) -> float:
    """가장 확실히 '탑승'한 사람의 포함률(사람·지게차 둘 다 있어야 의미)."""
    ppl, fks = boxes(r, "person"), boxes(r, "forklift")
    if not ppl or not fks:
        return -1.0
    return max(containment(p, f) for p in ppl for f in fks)


def stands_in_front(r: dict) -> bool:
    """포함률은 높지만 **지면에 선 사람**인가 — 발끝이 지게차 바닥보다 아래면 카메라에 더 가깝다.

    2026-08-27 발견: 포함률(2D 박스 겹침)만으로는 '운전석의 운전자'와 '지게차 앞에 선 사람'을
    가르지 못한다. 실측 210프레임 중 16프레임이 후자였고, 이들은 운전자로 간주돼 근접 판정에서
    제외됐다 — 정확히 위험한 쪽의 오류다. 눈으로 확인한 6프레임과 이 판별자가 6/6 일치했다.
    """
    ppl, fks = boxes(r, "person"), boxes(r, "forklift")
    if not ppl or not fks:
        return False
    _, p, f = max(((containment(p, f), p, f) for p in ppl for f in fks), key=lambda x: x[0])
    return p[3] > f[3] + GROUND_MARGIN


def true_onboard(r: dict) -> float:
    """진짜 탑승(포함률 높고 + 지면에 선 것이 아님)일 때만 포함률, 아니면 -1."""
    c = best_onboard(r)
    return -1.0 if (c < ONBOARD or stands_in_front(r)) else c


def person_area(r: dict) -> float:
    ppl = boxes(r, "person")
    if not ppl:
        return -1.0
    return max((b[2] - b[0]) * (b[3] - b[1]) for b in ppl)


# (출력이름, 장면, 점수함수, 조건설명) — 점수 최대 프레임을 고르되 조건 미달이면 실패로 보고
PICKS = [
    ("base", "01_지게차정지",
     lambda r: len(boxes(r, "forklift")) - 10 * len(boxes(r, "person")),
     "지게차 있고 사람 없음",
     lambda r: has(r, "forklift") and not has(r, "person")),

    ("board", "02_지게차탑승",
     true_onboard,
     f"운전석 탑승(포함률 {ONBOARD}↑ · 지면에 선 것 아님)",
     lambda r: true_onboard(r) >= ONBOARD),

    # ★"미착용 운전"이므로 **탑승 상태**까지 확인한다 — 옆에서 걷는 사진을 쓰면 캡션이 거짓이 된다
    ("nop", "05_보호구미착용운전",
     lambda r: true_onboard(r) if (has(r, "NO-Hardhat") and has(r, "NO-Safety-Vest")) else -1,
     "운전석 탑승 + NO-Hardhat + NO-Safety-Vest",
     lambda r: true_onboard(r) >= ONBOARD and has(r, "NO-Hardhat") and has(r, "NO-Safety-Vest")),

    # ★§4 정정의 근거 사진 — 지면에 선 사람이 운전자로 오인된 순간
    ("misfire", "04_안전모조끼운전",
     lambda r: best_onboard(r) if stands_in_front(r) else -1,
     "지면에 선 사람인데 포함률 0.65↑ (운전자로 오인)",
     lambda r: stands_in_front(r) and best_onboard(r) >= ONBOARD),

    ("full", "07_착용_위험구역",
     lambda r: person_area(r) if (has(r, "Hardhat") and has(r, "Safety-Vest")) else -1,
     "Hardhat 과 Safety-Vest 동시 검출",
     lambda r: has(r, "Hardhat") and has(r, "Safety-Vest")),
]


# 눈으로 확인해 고정한 프레임 — 조건은 자동 선정도 만족하지만, 그림이 더 명확한 쪽을 쓴다.
#   (조건 검증은 그대로 통과해야 한다. 고정이 조건을 우회하지는 않는다.)
PINNED = {"nop": 8, "misfire": 119}


def main() -> int:
    import cv2

    OUT.mkdir(parents=True, exist_ok=True)
    fail = 0
    for name, scene, score, desc, ok_fn in PICKS:
        rs = rows(scene)
        idx = PINNED.get(name)
        if idx is None:
            idx = max(range(len(rs)), key=lambda i: score(rs[i]))
        if not ok_fn(rs[idx]):
            print(f"❌ {name}: 조건({desc})을 만족하는 프레임이 {scene} 에 없다")
            fail += 1
            continue
        cap = cv2.VideoCapture(str(F / scene / "overlay.mp4"))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        cap.release()
        if not ok or fr is None:
            print(f"❌ {name}: overlay.mp4 {idx}번 프레임을 못 읽었다")
            fail += 1
            continue
        okj, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        (OUT / f"{name}.jpg").write_bytes(buf.tobytes())
        labels = sorted({d.get("class") for d in (rs[idx].get("detections") or [])})
        extra = ""
        if name == "board":
            extra = f" · 포함률 {best_onboard(rs[idx]):.2f}"
        print(f"✅ {name}: {scene} {idx}번 프레임 — {desc}{extra}")
        print(f"     라벨 {labels}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
