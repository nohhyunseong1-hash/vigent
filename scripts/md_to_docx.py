#!/usr/bin/env python3
"""[문서] md → docx 변환 — 외부 라이브러리 없이(표준 라이브러리만).

★왜 이렇게 하나
  python-docx 가 설치돼 있지 않고, 외부 설치는 승인 절차가 필요하다(CLAUDE.md).
  docx 는 zip + XML 이므로 표준 라이브러리로 만들 수 있다.
  ★양식 docx 를 통째로 복사한 뒤 본문(word/document.xml)만 갈아끼우고
  하이퍼링크 관계(document.xml.rels)를 덧붙인다 — 양식의 스타일·글꼴·설정을 물려받는다.

지원 문법(이 저장소 md 가 쓰는 부분집합만 — 범위 밖 문법은 ★일반 문단으로 떨어진다):
  # ~ ### 제목 · GFM 표 · '- ' 목록(2칸 들여쓰기 1단계) · '> ' 인용 ·
  **굵게** · `코드` · [글](링크) · '---' 구분선 · [공란 …] 노란 형광펜

사용:
  python scripts/md_to_docx.py --md <입력.md> --template <양식.docx> --out <출력.docx>
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FONT = '<w:rFonts w:ascii="Malgun Gothic" w:eastAsia="맑은 고딕" w:hAnsi="Malgun Gothic"/>'
HL_RE = re.compile(r"(\[공란[^\]]*\])")            # 대표가 채울 칸 — 노란 형광펜
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
CODE_RE = re.compile(r"`([^`]+)`")


class Doc:
    def __init__(self) -> None:
        self.body: list[str] = []
        self.links: list[str] = []                  # rId 순서 = 목록 순서

    # ── 런(글자 조각) ────────────────────────────────────────────
    def _runs(self, text: str, sz: int, bold: bool, color: str | None) -> str:
        """인라인 문법(**굵게**·`코드`·[링크]·[공란 형광펜])을 w:r 나열로 바꾼다."""
        out: list[str] = []

        def rpr(b: bool, hl: bool = False, link: bool = False, code: bool = False) -> str:
            p = [FONT, f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>']
            if b:
                p.append("<w:b/>")
            if hl:
                p.append('<w:highlight w:val="yellow"/>')
            if link:
                p.append('<w:color w:val="0563C1"/><w:u w:val="single"/>')
            elif color:
                p.append(f'<w:color w:val="{color}"/>')
            if code:
                p.insert(0, '<w:rFonts w:ascii="Consolas" w:eastAsia="맑은 고딕" w:hAnsi="Consolas"/>')
                p.pop(1) if False else None
            return "<w:rPr>" + "".join(p) + "</w:rPr>"

        def run(t: str, b: bool, hl: bool = False, code: bool = False) -> str:
            return f'<w:r>{rpr(b, hl, code=code)}<w:t xml:space="preserve">{escape(t)}</w:t></w:r>'

        # 1) 링크 분리
        pos = 0
        for m in LINK_RE.finditer(text):
            before, label, url = text[pos:m.start()], m.group(1), m.group(2)
            out.append(self._plain(before, sz, bold, rpr, run))
            self.links.append(url)
            rid = f"rIdVG{len(self.links)}"
            out.append(f'<w:hyperlink r:id="{rid}"><w:r>{rpr(bold, link=True)}'
                       f'<w:t xml:space="preserve">{escape(label)}</w:t></w:r></w:hyperlink>')
            pos = m.end()
        out.append(self._plain(text[pos:], sz, bold, rpr, run))
        return "".join(out)

    @staticmethod
    def _plain(text: str, sz: int, bold: bool, rpr, run) -> str:
        """링크가 없는 조각 — 굵게·코드·형광펜만 처리."""
        parts: list[str] = []
        # [공란] 형광펜 우선 분리
        for i, seg in enumerate(HL_RE.split(text)):
            hl = bool(i % 2)
            pos = 0
            for m in BOLD_RE.finditer(seg):
                pre = seg[pos:m.start()]
                if pre:
                    parts.append(Doc._code_runs(pre, bold, hl, run))
                parts.append(Doc._code_runs(m.group(1), True, hl, run))
                pos = m.end()
            rest = seg[pos:]
            if rest:
                parts.append(Doc._code_runs(rest, bold, hl, run))
        return "".join(parts)

    @staticmethod
    def _code_runs(text: str, bold: bool, hl: bool, run) -> str:
        parts: list[str] = []
        pos = 0
        for m in CODE_RE.finditer(text):
            if text[pos:m.start()]:
                parts.append(run(text[pos:m.start()], bold, hl))
            parts.append(run(m.group(1), bold, hl, code=True))
            pos = m.end()
        if text[pos:]:
            parts.append(run(text[pos:], bold, hl))
        return "".join(parts)

    # ── 블록 ────────────────────────────────────────────────────
    def para(self, text: str, sz: int = 20, bold: bool = False, indent: int = 0,
             color: str | None = None, before: int = 40, after: int = 40,
             page_break: bool = False, border_bottom: bool = False) -> None:
        ppr = [f'<w:spacing w:before="{before}" w:after="{after}" w:line="276" w:lineRule="auto"/>']
        if indent:
            ppr.append(f'<w:ind w:left="{indent}"/>')
        if border_bottom:
            ppr.append('<w:pBdr><w:bottom w:val="single" w:sz="12" w:space="1" w:color="333333"/></w:pBdr>')
        pb = '<w:r><w:br w:type="page"/></w:r>' if page_break else ""
        self.body.append(f'<w:p><w:pPr>{"".join(ppr)}</w:pPr>{pb}'
                         f'{self._runs(text, sz, bold, color)}</w:p>')

    def table(self, rows: list[list[str]]) -> None:
        ncol = max(len(r) for r in rows)
        b = '<w:top w:val="single" w:sz="4" w:color="8C8C8C"/><w:left w:val="single" w:sz="4" w:color="8C8C8C"/>' \
            '<w:bottom w:val="single" w:sz="4" w:color="8C8C8C"/><w:right w:val="single" w:sz="4" w:color="8C8C8C"/>' \
            '<w:insideH w:val="single" w:sz="4" w:color="8C8C8C"/><w:insideV w:val="single" w:sz="4" w:color="8C8C8C"/>'
        out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/>'
               f'<w:tblBorders>{b}</w:tblBorders>'
               f'<w:tblCellMar><w:left w:w="85" w:type="dxa"/><w:right w:w="85" w:type="dxa"/></w:tblCellMar>'
               f'<w:tblLayout w:type="autofit"/></w:tblPr>']
        for ri, row in enumerate(rows):
            out.append("<w:tr>")
            for ci in range(ncol):
                cell = row[ci] if ci < len(row) else ""
                shd = '<w:shd w:val="clear" w:fill="E8EAED"/>' if ri == 0 else ""
                out.append(f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/>{shd}'
                           f'<w:vAlign w:val="center"/></w:tcPr>'
                           f'<w:p><w:pPr><w:spacing w:before="20" w:after="20"/></w:pPr>'
                           f'{self._runs(cell, 18, ri == 0, None)}</w:p></w:tc>')
            out.append("</w:tr>")
        out.append("</w:tbl>")
        # 표 뒤 빈 문단(Word 규칙: 표가 연달아 붙거나 문서 끝이면 깨질 수 있다)
        out.append('<w:p><w:pPr><w:spacing w:before="0" w:after="60"/></w:pPr></w:p>')
        self.body.append("".join(out))


def convert(md: str) -> Doc:
    d = Doc()
    lines = md.split("\n")
    i, n = 0, len(lines)
    first_h1 = True
    cells = lambda ln: [c.strip() for c in ln.strip().strip("|").split("|")]  # noqa: E731
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("---") and set(ln.strip()) == {"-"}:
            i += 1
            continue
        if ln.startswith("#"):
            lv = len(ln) - len(ln.lstrip("#"))
            txt = ln[lv:].strip()
            if lv == 1:
                d.para(txt, sz=30, bold=True, before=200, after=120,
                       page_break=not first_h1, border_bottom=True)
                first_h1 = False
            elif lv == 2:
                d.para(txt, sz=24, bold=True, before=200, after=80, border_bottom=True)
            else:
                d.para(txt, sz=22, bold=True, before=160, after=60)
            i += 1
            continue
        if ln.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            rows = [cells(ln)]
            i += 2
            while i < n and lines[i].startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            d.table(rows)
            continue
        if ln.startswith(">"):
            buf = []
            while i < n and lines[i].startswith(">"):
                t = lines[i].lstrip(">").strip()
                if t:
                    buf.append(t)
                i += 1
            for t in buf:
                d.para(t, sz=18, color="595959", indent=340, before=10, after=10)
            continue
        m = re.match(r"^(\s*)- (.*)$", ln)
        if m:
            depth = len(m.group(1)) // 2
            # 이어지는 들여쓴 연속줄을 같은 항목으로 붙인다
            item = [m.group(2).strip()]
            i += 1
            while i < n and lines[i].strip() and not re.match(r"^(\s*)- ", lines[i]) \
                    and not lines[i].startswith(("#", "|", ">", "**◦")) \
                    and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                item.append(lines[i].strip())
                i += 1
            d.para(("· " if depth == 0 else "‐ ") + " ".join(item),
                   sz=20, indent=340 + depth * 340, before=20, after=20)
            continue
        # 일반 문단(이어지는 줄 합침)
        buf = [ln.strip()]
        i += 1
        while i < n and lines[i].strip() and not lines[i].startswith(("#", "|", ">", "-", " ")):
            buf.append(lines[i].strip())
            i += 1
        d.para(" ".join(buf), sz=20, before=60, after=60)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--template", required=True, help="★양식 docx — 복사본의 본문만 교체한다")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    md_p, tpl, out = Path(args.md), Path(args.template), Path(args.out)
    for p in (md_p, tpl):
        if not p.exists():
            print(f"❌ 없음: {p}")
            return 1

    doc = convert(md_p.read_text(encoding="utf-8"))

    with zipfile.ZipFile(tpl) as z:
        old_doc = z.read("word/document.xml").decode("utf-8")
        old_rels = z.read("word/_rels/document.xml.rels").decode("utf-8")

    # 양식의 루트 태그(네임스페이스 선언)를 그대로 재사용한다 — 호환성 문제 회피
    root_open = re.search(r"<w:document[^>]*>", old_doc).group(0)
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"'
            ' w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    new_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
               + root_open + "<w:body>" + "".join(doc.body) + sect + "</w:body></w:document>")

    # 하이퍼링크 관계를 기존 rels 에 덧붙인다(기존 rId 는 건드리지 않는다)
    hl = "".join(
        f'<Relationship Id="rIdVG{k + 1}" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        f'Target="{escape(u)}" TargetMode="External"/>'
        for k, u in enumerate(doc.links))
    new_rels = old_rels.replace("</Relationships>", hl + "</Relationships>")

    shutil.copy(tpl, out)
    # zip 안 파일 교체: 표준 라이브러리엔 in-place 교체가 없어 새로 싼다
    with zipfile.ZipFile(tpl) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename == "word/document.xml":
                zout.writestr(item, new_doc)
            elif item.filename == "word/_rels/document.xml.rels":
                zout.writestr(item, new_rels)
            else:
                zout.writestr(item, zin.read(item.filename))

    # ★규칙 11 — 결과물을 다시 열어 확인한다
    import xml.dom.minidom as MD
    with zipfile.ZipFile(out) as z:
        dx = z.read("word/document.xml").decode("utf-8")
        MD.parseString(dx)                                   # XML 정형성
        MD.parseString(z.read("word/_rels/document.xml.rels").decode("utf-8"))
        n_p = dx.count("<w:p>") + dx.count("<w:p ")
        n_t = dx.count("<w:tbl>")
        n_h = dx.count("<w:hyperlink")
    if out.stat().st_size == 0 or n_p == 0:
        print("❌ 산출물이 비었다")
        return 1
    print(f"✅ {out} — {out.stat().st_size / 1024:.0f}KB · 문단 {n_p} · 표 {n_t} · "
          f"하이퍼링크 {n_h}(rels {len(doc.links)}) — 재개봉·XML 검증 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
