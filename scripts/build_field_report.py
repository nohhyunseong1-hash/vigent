#!/usr/bin/env python3
"""[보고서] 현장 시험 HTML 템플릿에 증거 사진을 심고 PDF 로 출력한다.

2026-08-27 학원 방문 산출물용. 사진은 base64 로 파일 안에 넣어 **단일 파일**로 만든다
(외부 참조가 있으면 PDF 변환 시 이미지가 빠진다).
PDF 변환은 Windows 기본 Edge 의 headless 인쇄를 쓴다 — 추가 설치가 필요 없다.

사용: python scripts/build_field_report.py
"""
from __future__ import annotations

import base64
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
F = ROOT / "runs" / "field_20260827"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# 사진은 scripts/pick_report_frames.py 가 **캡션 조건을 좌표로 검증해** 뽑은 것만 쓴다.
#   (2026-08-27: 스틸을 어림잡아 골랐다가 캡션과 다른 순간의 사진이 실렸다 — 재발 방지)
P = F / "report_frames"

FIGS = {
    "BASE": (P / "base.jpg",
             "장면 1 — 정지 지게차. 70프레임 전부 검출(score 0.938~0.945)했고, "
             "사람이 없는 화면에서 사람 오검출은 0건이었다."),
    "BOARD": (P / "board.jpg",
              "장면 2 — 운전석 탑승(포함률 1.00). 초록 박스(사람)가 파란 박스(지게차) 안에 "
              "완전히 들어가 있다. 이 상태에서 근접경보는 발생하지 않았다 — 운전자 제외가 의도대로 작동."),
    "NOP": (P / "nop.jpg",
            "장면 5 — 보호구 미착용 상태로 운전석 탑승. NO-Hardhat·NO-Safety-Vest 검출(빨강)."),
    "MISFIRE": (P / "misfire.jpg",
                "오인 사례 — 사람이 지게차 앞 지면에 서 있는데(발끝이 지게차 바닥보다 아래) "
                "박스 겹침이 커서 포함률 0.65를 넘었다. 운전자로 간주돼 근접 판정에서 제외된다."),
    "FULL": (P / "full.jpg",
             "장면 7 — 보호구 착용 + 위험구역. Hardhat·Safety-Vest 인식, "
             "얼굴은 자동 비식별화(모자이크)된다."),
    "ZONE": (P / "zone.jpg",
             "재작도한 위험구역(v2)과 그 안에 선 작업자. 판정 기준점은 사람 박스 하단 중앙"
             "(노란 점 FOOT)이며, 이 점이 구역 안에 1초 이상 있어야 침입으로 확정된다. "
             "따라서 구역은 '실제로 밟을 수 있는 땅'에 그려야 한다."),
}


def main() -> int:
    tpl = ROOT / "reports" / "_template.html"
    if not tpl.exists():
        print(f"❌ 템플릿 없음: {tpl}")
        return 1
    html = tpl.read_text(encoding="utf-8")

    for key, (path, cap) in FIGS.items():
        if not path.exists():
            print(f"⚠ 사진 없음(건너뜀): {path.name}")
            html = html.replace(f"__{key}__", "")
            continue
        b64 = base64.b64encode(path.read_bytes()).decode()
        html = html.replace(
            f"__{key}__",
            f'<figure><img src="data:image/jpeg;base64,{b64}"/>'
            f"<figcaption>{cap}</figcaption></figure>")

    out_html = ROOT / "reports" / "현장테스트_보고서_20260827.html"
    out_html.write_text(html, encoding="utf-8")
    print(f"[HTML] {out_html.name} — {out_html.stat().st_size / 1048576:.1f} MB")

    if not EDGE.exists():
        print("⚠ Edge 없음 — HTML 만 생성했다. 브라우저에서 열어 '인쇄 → PDF 저장' 하면 된다.")
        return 0

    out_pdf = ROOT / "reports" / "현장테스트_보고서_20260827.pdf"
    if out_pdf.exists():
        out_pdf.unlink()
    subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out_pdf}", out_html.as_uri()],
                   capture_output=True, timeout=180)
    for _ in range(30):                      # headless 인쇄는 비동기라 파일 생성을 기다린다
        if out_pdf.exists() and out_pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    if not out_pdf.exists():
        print("❌ PDF 생성 실패 — HTML 을 브라우저에서 인쇄해 저장할 것")
        return 1
    print(f"[PDF ] {out_pdf.name} — {out_pdf.stat().st_size / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
