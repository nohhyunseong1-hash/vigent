#!/usr/bin/env python3
"""선명도(블러) 비교 — 라플라시안 분산(높을수록 선명·블러 적음)으로 클립 간 비교.
사용: /opt/anaconda3/bin/python3 benchmarks/blur_check.py 클립1.mp4 [클립2.mp4 ...]
근거: 모션블러 프레임은 고주파 성분이 줄어 라플라시안 분산이 낮다(표준 focus measure)."""
import statistics
import sys

import cv2


def sharpness(path: str) -> tuple[float, int]:
    cap = cv2.VideoCapture(path)
    vals = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        vals.append(cv2.Laplacian(g, cv2.CV_64F).var())
    cap.release()
    return (statistics.median(vals) if vals else 0.0), len(vals)


def main() -> None:
    if len(sys.argv) < 2:
        print("사용: blur_check.py 클립1.mp4 [클립2.mp4 ...]")
        return
    print(f"{'클립':<40}{'선명도(중앙값)':>14}{'프레임':>8}")
    print("-" * 62)
    rows = []
    for p in sys.argv[1:]:
        med, n = sharpness(p)
        rows.append((p, med))
        print(f"{p:<40}{med:>14.0f}{n:>8}")
    if len(rows) >= 2:
        base = rows[0][1] or 1
        print("\n기준(첫 클립) 대비:")
        for p, m in rows[1:]:
            print(f"  {p}: {round(100 * (m - base) / base):+d}% "
                  f"({'선명↑·블러↓' if m > base else '블러↑'})")


if __name__ == "__main__":
    main()
