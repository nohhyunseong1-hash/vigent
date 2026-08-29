#!/usr/bin/env python3
"""[보고서 v1.2] 마크다운 → 단일 HTML(사진 base64 내장) → PDF.

★왜 LaTeX(pandoc) 경로를 쓰지 않는가
  pandoc → pdf 는 XeLaTeX 한글 폰트 설정이 까다롭고, 폰트가 없으면 한글이 통째로
  빠지거나 두부(□)로 나온다. 브라우저는 시스템 폰트(맑은 고딕)를 그냥 쓰므로
  **md → HTML → Edge 헤드리스 인쇄**가 한글에 가장 안전하다. 추가 설치도 없다.

★출력은 저장소 밖에 쓴다
  완성 PDF/HTML 에는 현장 사진이 들어간다. 저장소에는 **생성 스크립트만** 두고
  산출물은 `D:\\vigent_field\\20260827\\build\\` 에 만든다(개인정보 반출 규칙).

★사진은 조건을 좌표로 검증해서 뽑는다
  2026-08-27 교훈: 스틸을 어림잡아 골랐더니 캡션과 다른 순간의 사진이 실렸다.
  그래서 `pick_report_frames.py` 의 조건식을 그대로 재사용하고,
  조건을 만족하지 않으면 **그 사진을 넣지 않고 실패로 보고**한다.

사용: python scripts/build_report_v12.py
"""
from __future__ import annotations

import base64
import hashlib
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MD = ROOT / "reports" / "현장테스트_보고서_20260827_v1.2.md"
OUT_DIR = Path(r"D:\vigent_field\20260827\build")
VID_ROOT = Path(r"D:\vigent_field\20260827\field_20260827")
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

# v1.1 사진 6장(base·nop·full·board·misfire·zone) + v1.2 신규 1장(maskonly).
# zone 은 자동 선정기가 없어 v1.1 PDF 에서 추출한 것을 그대로 쓴다.
CAPTIONS = {
    "base": "장면 1 — 정지 지게차(forklift 0.94). 70프레임 전부 검출했고, "
            "사람이 없는 화면에서 사람 오검출은 0건이었다.",
    "nop": "장면 5 — 보호구 미착용 상태로 운전석 탑승. NO-Hardhat·NO-Safety-Vest·NO-Mask 검출. "
           "설계대로 발화한 <b>정탐</b> 사례다.",
    "full": "장면 7 — 보호구 착용 + 위험구역. Hardhat·Safety-Vest 를 정상 인식했다. "
            "얼굴은 자동 비식별화(모자이크)된다.",
    "board": "장면 2 — 운전석 탑승. 초록 박스(사람)가 파란 박스(지게차) 안에 들어가 있다. "
             "이 상태에서 근접경보는 발생하지 않았다 — 운전자 제외가 의도대로 작동(§4).",
    "misfire": "★<b>오인 사례(§4-1)</b> — 사람이 지게차 앞 <b>지면</b>에 서 있는데(발끝이 지게차 "
               "바닥보다 아래) 박스 겹침이 커서 포함률 0.65를 넘었다. 운전자로 간주돼 "
               "근접 판정에서 제외된다. 오류 방향이 <b>위험한 쪽</b>이다.",
    "maskonly": "★<b>v1.2 신규 — 마스크 단독 오탐(§4-4)</b>. 장면 4에서 <b>안전모(Hardhat)와 "
                "조끼(Safety-Vest)를 모두 착용</b>했는데도 왼쪽 위에 "
                "<b>FIRED: ppe_missing</b> 이 떠 있다(Hardhat 0.89). 방아쇠는 <b>NO-Mask 하나</b>였다. "
                "이 표본에서 490건 중 87건이 이 경우였다.",
    "zone": "재작도한 위험구역(v2)과 그 안에 선 작업자. 판정 기준점은 사람 박스 하단 중앙"
            "(노란 점 FOOT)이며, 이 점이 구역 안에 1초 이상 있어야 침입으로 확정된다. "
            "따라서 구역은 '실제로 밟을 수 있는 땅'에 그려야 한다(§5).",
}

# (이름, 장면, 고정 프레임 번호 or None) — None 이면 pick_report_frames 의 점수식으로 고른다.
EXTRA_PICK = ("maskonly", "04_안전모조끼운전", 118)

CSS = """
@page { size: A4; margin: 15mm 13mm; }
* { box-sizing: border-box; }
body { font-family: "Malgun Gothic","맑은 고딕","Apple SD Gothic Neo",sans-serif;
       color:#1a1a1a; font-size:10.2pt; line-height:1.62; margin:0; }
h1 { font-size:17pt; margin:0 0 12px; padding-bottom:7px; border-bottom:2.5px solid #1a1a1a;
     letter-spacing:-.5px; page-break-after:avoid; }
h1.doc { font-size:23pt; border:0; margin-bottom:4px; padding:0; }
h2 { font-size:12.5pt; margin:20px 0 8px; color:#111; page-break-after:avoid; }
h3 { font-size:11pt; margin:15px 0 6px; color:#333; page-break-after:avoid; }
p { margin:8px 0; }
table { width:100%; border-collapse:collapse; margin:10px 0 15px; font-size:9.3pt;
        page-break-inside:avoid; }
th { background:#eceef0; text-align:left; padding:6px 8px; border:1px solid #c8ccd0; font-weight:600; }
td { padding:6px 8px; border:1px solid #d8dcdf; vertical-align:top; }
tr:nth-child(even) td { background:#fafbfc; }
blockquote { margin:11px 0; padding:9px 13px; background:#f6f7f9;
             border-left:4px solid #8a9099; font-size:9.5pt; page-break-inside:avoid; }
blockquote.warn { background:#fff8e6; border-left-color:#d9a520; }
blockquote.star { background:#fdf2f2; border-left-color:#c0392b; }
ul,ol { margin:7px 0 13px; padding-left:21px; }
li { margin:4px 0; }
code { background:#eef0f2; padding:1px 4px; border-radius:2px;
       font-family:Consolas,"D2Coding",monospace; font-size:9pt; }
hr { border:0; border-top:1px solid #d0d4d8; margin:18px 0; }
figure { margin:13px 0 17px; page-break-inside:avoid; }
figure img { width:100%; border:1px solid #b8bcc0; display:block; }
figcaption { font-size:8.7pt; color:#4a4a4a; margin-top:5px; line-height:1.5;
             padding-left:2px; border-left:3px solid #d0d4d8; padding-left:8px; }
strong { font-weight:700; }
.sub { color:#555; font-size:10pt; margin:0 0 14px; }
.pb { page-break-before:always; }
footer { margin-top:22px; padding-top:9px; border-top:1px solid #ccc; font-size:8.4pt; color:#666; }
"""


# ── 인라인 마크다운 ───────────────────────────────────────────────
def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", t)   # PDF 라 링크는 글자만 남긴다
    return t


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def render(md: str, figs: dict[str, str]) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    first_h1 = True
    while i < n:
        ln = lines[i]

        if ln.startswith("<!--"):                       # 머리 주석 통째로 건너뛴다
            while i < n and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        if not ln.strip():
            i += 1
            continue

        # 사진 자리 표시  "> 📷 사진 — key"
        m = re.match(r"^>\s*📷\s*사진\s*[—-]\s*(\S+)", ln)
        if m:
            out.append(figs.get(m.group(1), ""))
            i += 1
            continue

        if ln.startswith("---") and set(ln.strip()) == {"-"}:
            out.append("<hr/>")
            i += 1
            continue

        if ln.startswith("#"):
            lv = len(ln) - len(ln.lstrip("#"))
            txt = inline(ln[lv:].strip())
            if lv == 1 and first_h1:
                out.append(f'<h1 class="doc">{txt}</h1>')
                first_h1 = False
            elif lv == 1:
                out.append(f'<h1 class="pb">{txt}</h1>')
            else:
                out.append(f"<h{min(lv, 3)}>{txt}</h{min(lv, 3)}>")
            i += 1
            continue

        # 표 — 헤더 + 구분줄 + 본문
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            head = cells(ln)
            i += 2
            body = []
            while i < n and lines[i].startswith("|"):
                body.append(cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            rows = ""
            for r in body:
                rows += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
            out.append(f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>")
            continue

        # 인용 — 연속된 '>' 줄을 하나로
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            body = inline(" ".join(x for x in buf if x))
            cls = "warn" if body.startswith(("⚠", "※")) else ("star" if "★" in body[:6] else "")
            out.append(f'<blockquote class="{cls}">{body}</blockquote>')
            continue

        # 목록 — 이어지는 들여쓴 줄은 같은 항목으로 붙인다
        if ln.lstrip().startswith("- "):
            items: list[str] = []
            while i < n and (lines[i].lstrip().startswith("- ") or
                             (items and lines[i].startswith("  ") and lines[i].strip())):
                if lines[i].lstrip().startswith("- "):
                    items.append(lines[i].lstrip()[2:].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue

        # 문단 — 빈 줄까지 이어 붙인다
        buf = []
        while i < n and lines[i].strip() and not lines[i].startswith(("#", ">", "|", "-")):
            buf.append(lines[i].strip())
            i += 1
        if buf:
            out.append(f"<p>{inline(' '.join(buf))}</p>")
        else:
            out.append(f"<p>{inline(ln.strip())}</p>")
            i += 1
    return "\n".join(out)


# ── 사진 추출 ────────────────────────────────────────────────────
def grab_frames(tmp: Path) -> dict[str, Path]:
    """조건을 좌표로 검증한 프레임만 overlay.mp4 에서 뽑는다."""
    import cv2
    import pick_report_frames as pk

    real = {unicodedata.normalize("NFC", x): x for x in os.listdir(VID_ROOT)}
    jobs = []
    for name, scene, score, desc, ok in pk.PICKS:
        rs = pk.rows(scene)
        idx = pk.PINNED.get(name)
        if idx is None:
            idx = max(range(len(rs)), key=lambda k: score(rs[k]))
        jobs.append((name, scene, idx, desc, ok, rs))

    name, scene, idx = EXTRA_PICK
    rs = pk.rows(scene)

    def mask_only(r: dict) -> bool:
        """안전모·조끼를 착용했는데 NO-Mask 로 발화한 프레임.

        ★캡션이 "안전모를 쓰고 있다"고 주장하므로 **안전모가 화면에서 잘리지 않았는지**까지
        본다. 처음 고른 120번 프레임은 사람이 화면 위쪽 끝에 걸려 안전모가 잘려 있었다 —
        조건은 만족하지만 **사진으로는 캡션을 확인할 수 없다.** 그런 사진은 쓰지 않는다.
        """
        if not (pk.has(r, "Hardhat") and pk.has(r, "Safety-Vest") and pk.has(r, "NO-Mask")):
            return False
        if pk.has(r, "NO-Hardhat") or pk.has(r, "NO-Safety-Vest"):
            return False
        if "ppe_missing" not in (r.get("fired") or []):
            return False
        return min(b[1] for b in pk.boxes(r, "Hardhat")) > 0.02   # 안전모 상단이 화면 안

    jobs.append((name, scene, idx, "안전모·조끼 착용인데 NO-Mask 로 발화", mask_only, rs))

    got: dict[str, Path] = {}
    vids: dict[str, Path] = {}
    for name, scene, idx, desc, ok, rs in jobs:
        if not ok(rs[idx]):
            print(f"  ❌ {name}: 조건({desc}) 불만족 — 사진을 넣지 않는다")
            continue
        if scene not in vids:                       # OpenCV 는 한글 경로를 못 연다
            a = tmp / (hashlib.md5(scene.encode()).hexdigest()[:10] + ".mp4")
            shutil.copy(VID_ROOT / real[unicodedata.normalize("NFC", scene)] / "overlay.mp4", a)
            vids[scene] = a
        cap = cv2.VideoCapture(str(vids[scene]))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        good, fr = cap.read()
        cap.release()
        if not good:
            print(f"  ❌ {name}: 프레임 {idx} 를 못 읽었다")
            continue
        p = tmp / f"{name}.jpg"
        cv2.imwrite(str(p), fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        got[name] = p
        labels = sorted({d["class"] for d in (rs[idx].get("detections") or [])})
        print(f"  ✅ {name:<9} {scene} #{idx} · {labels}")

    zone = OUT_DIR / "img" / "p6_X23.jpg"           # v1.1 PDF 에서 뽑아 둔 구역 사진
    if zone.exists():
        got["zone"] = zone
        print("  ✅ zone      v1.1 사진 재사용(자동 선정기 없음)")
    else:
        print(f"  ❌ zone: {zone} 없음")
    return got


def main() -> int:
    if not MD.exists():
        print(f"❌ 원고 없음: {MD}")
        return 1
    if not VID_ROOT.exists():
        print(f"❌ 현장 영상 없음: {VID_ROOT}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("■ 사진 추출(조건 검증)")
    with tempfile.TemporaryDirectory() as td:
        got = grab_frames(Path(td))
        figs = {}
        for k, p in got.items():
            b64 = base64.b64encode(p.read_bytes()).decode()
            figs[k] = (f'<figure><img src="data:image/jpeg;base64,{b64}"/>'
                       f"<figcaption>{CAPTIONS.get(k, '')}</figcaption></figure>")

    missing = [k for k in CAPTIONS if k not in figs]
    if missing:
        print(f"  ⚠ 빠진 사진: {missing}")

    body = render(MD.read_text(encoding="utf-8"), figs)
    doc = (f'<meta charset="utf-8"><title>VIGENT 현장 테스트 보고서 v1.2</title>'
           f"<style>{CSS}</style>\n{body}")
    out_html = OUT_DIR / "현장테스트_보고서_20260827_v1.2.html"
    out_html.write_text(doc, encoding="utf-8")
    print(f"\n[HTML] {out_html}  ({out_html.stat().st_size / 1048576:.1f} MB · 사진 {len(figs)}장)")

    if not EDGE.exists():
        print("⚠ Edge 없음 — HTML 을 브라우저에서 열어 '인쇄 → PDF 저장' 하면 된다.")
        return 0
    out_pdf = OUT_DIR / "현장테스트_보고서_20260827_v1.2.pdf"
    if out_pdf.exists():
        out_pdf.unlink()
    subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out_pdf}", out_html.as_uri()],
                   check=False, capture_output=True, timeout=180)
    if out_pdf.exists():
        print(f"[PDF ] {out_pdf}  ({out_pdf.stat().st_size / 1048576:.1f} MB)")
        return 0
    print("⚠ PDF 생성 실패 — HTML 을 브라우저에서 인쇄하면 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
