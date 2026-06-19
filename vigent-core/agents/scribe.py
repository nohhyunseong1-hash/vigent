"""Scribe — [보고서] 산안법 기반 위험성평가서 초안 생성 (§7.1, §15-4)

- 입력: Analyst 가 발동한 규칙 이벤트(fired rules + 발생 횟수).
- 처리: 규칙→국내 위험성평가표 항목 매핑(빈도×강도), Copilot 근거(법령 인용) 삽입.
- 출력: 인쇄/PDF 저장 가능한 자체 완결형 HTML (외부 PDF 라이브러리 불필요).
- 저장: data/risk_assessments/ 에 HTML+JSON (감사추적용).

⚠ 본 보고서는 안전관리 활동 '기록 보조'이며 법적 자문/인증이 아니다(보고서에 명시).
   비전 판정은 보조·감시 신호이며 1차 방호 책임이 아니다(§8).

KB(법령 근거·감소대책)는 BODA report_builder.RISK_ASSESS 를 이식해 재사용한다.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .base import BaseAgent

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent.parent
_SAVE_DIR = _ROOT / "data" / "risk_assessments"

# vision.yaml 규칙 id → 위험성평가 KB (BODA RISK_ASSESS 이식)
RULE_KB: dict[str, dict[str, Any]] = {
    "zone_intrusion": {
        "hazard": "위험구역 접근/침입", "work": "위험구역 인접 작업", "cat": "협착·충돌·추락",
        "harm": "위험구역 진입으로 협착·충돌·추락 등 중대재해",
        "law": "산업안전보건법 제38조·안전보건규칙 제20조(출입의 금지)", "sev": 3,
        "act": "출입통제, 경고표지, 물리적 방호울, 접근 경보"},
    "ppe_missing": {
        "hazard": "보호구(안전모/조끼) 미착용", "work": "보호구 착용 작업장", "cat": "추락·낙하물·충돌",
        "harm": "보호구 미착용 상태에서 낙하물·충돌 시 중상",
        "law": "산업안전보건법 제38조·안전보건규칙 제32조(보호구의 지급)", "sev": 2,
        "act": "PPE 착용 지도, 출입 시 점검, 미착용자 작업 제한"},
    "fall_suspected": {
        "hazard": "낙상/추락 의심", "work": "고소·작업발판·이동 작업", "cat": "추락·전도",
        "harm": "작업 중 낙상·추락으로 중상",
        "law": "산업안전보건법 제38조·안전보건규칙 제42조(추락의 방지)", "sev": 3,
        "act": "안전난간·안전대·추락방호망 설치, 작업발판 점검"},
    "guard_bypass": {
        "hazard": "프레스/전단기 방호장치 우회", "work": "프레스·전단기 작업", "cat": "협착·절단",
        "harm": "방호구역에 신체 진입으로 협착·절단 중대재해",
        "law": "산업안전보건법 제80조·안전보건규칙 제103~105조(방호장치)", "sev": 3,
        "act": "광전자식 방호장치 점검, 양수조작식 조작부, 인증 안전회로 연동(§8: 비전은 보조신호)"},
}


def _likelihood(count: int) -> int:
    return 1 if count <= 2 else (2 if count <= 8 else 3)


def _level(score: int) -> tuple[str, str]:
    if score >= 6:
        return "상", "#ef4444"
    if score >= 3:
        return "중", "#f59e0b"
    return "하", "#10b981"


class ScribeAgent(BaseAgent):
    name = "Scribe"
    role = "보고서: 위험성평가서·증거 리포트 생성(HTML/PDF), 근거 인용 포함"

    def __init__(self, config: Any):
        super().__init__(config)
        self.copilot = None  # build_agents 이후 코어가 주입(근거 인용용)

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "templates": ["risk_assessment_kr", "incident_evidence"]}

    def build_assessment(self, events: list[dict[str, Any]],
                         site: str = "", process: str = "") -> dict[str, Any]:
        """이벤트 목록 → 위험성평가표(초안). events=[{rule, count}, ...]"""
        rows: list[dict[str, Any]] = []
        for ev in events or []:
            rule = ev.get("rule") or ev.get("type")
            count = int(ev.get("count", 1) or 1)
            kb = RULE_KB.get(rule)
            if not kb:
                continue
            likely = _likelihood(count)
            sev = int(kb["sev"])
            score = likely * sev
            lvl, color = _level(score)
            # Copilot 근거(법령 인용) 삽입 — 출처 포함(§9)
            citations = []
            if self.copilot is not None:
                citations = self.copilot.cite(rule).get("citations", [])
            rows.append({
                "rule": rule, "유해위험요인": kb["hazard"], "공정작업": kb["work"],
                "위험분류": kb["cat"], "위험상황및결과": kb["harm"], "관련근거": kb["law"],
                "빈도_가능성": likely, "강도_중대성": sev, "위험성": score, "위험성등급": lvl,
                "감소대책": kb["act"], "AI감지근거": f"AI {count}회 감지",
                "citations": citations, "_color": color,
            })
        rows.sort(key=lambda r: r["위험성"], reverse=True)
        high = [r for r in rows if r["위험성등급"] == "상"]
        return {
            "site": site, "process": process,
            "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "method": "위험성 = 빈도(가능성) × 강도(중대성)",
            "status": "draft", "review_required": True,
            "summary": {"총항목": len(rows), "상_높음": len(high),
                        "주요위험": [r["유해위험요인"] for r in high]},
            "rows": rows,
        }

    def render_html(self, assessment: dict[str, Any]) -> str:
        """위험성평가표 → 인쇄/PDF 저장 가능한 자체 완결형 HTML."""
        e = html.escape
        rows_html = ""
        for r in assessment["rows"]:
            cites = "<br>".join(
                f"· {e(c['source'])} {e(c['clause'])}" for c in r.get("citations", [])
            ) or "—"
            rows_html += f"""
      <tr>
        <td>{e(r['유해위험요인'])}</td><td>{e(r['공정작업'])}</td><td>{e(r['위험분류'])}</td>
        <td>{e(r['위험상황및결과'])}</td>
        <td>{e(r['관련근거'])}<div class="cite">{cites}</div></td>
        <td style="text-align:center">{r['빈도_가능성']}</td>
        <td style="text-align:center">{r['강도_중대성']}</td>
        <td style="text-align:center"><b style="color:{r['_color']}">{r['위험성']} ({e(r['위험성등급'])})</b></td>
        <td>{e(r['감소대책'])}</td>
        <td style="text-align:center;color:#64748b">{e(r['AI감지근거'])}</td>
      </tr>"""
        s = assessment["summary"]
        return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>VIGENT 위험성평가서(초안)</title>
<style>
  @page {{ size:A4 landscape; margin:12mm; }}
  body{{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:#0f172a;margin:28px;}}
  h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#64748b;font-size:13px}}
  .notice{{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 12px;margin:14px 0;font-size:12px}}
  .meta{{font-size:13px;margin:10px 0}} .meta b{{display:inline-block;min-width:70px;color:#475569}}
  .flow{{display:flex;gap:8px;margin:14px 0;font-size:12px;flex-wrap:wrap}}
  .flow span{{background:#eef2ff;border:1px solid #c7d2fe;border-radius:999px;padding:5px 12px;color:#3730a3}}
  .flow b{{color:#1e3a8a}}
  table{{width:100%;border-collapse:collapse;font-size:11.5px;margin-top:6px}}
  th,td{{border:1px solid #cbd5e1;padding:6px 8px;vertical-align:top;text-align:left}}
  thead th{{background:#f1f5f9}} thead tr.grp th{{background:#e2e8f0;text-align:center;font-size:11px}}
  .cite{{color:#2563eb;font-size:10.5px;margin-top:4px;line-height:1.5}}
  .btn{{padding:9px 16px;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#fff;cursor:pointer;text-decoration:none}}
  .foot{{margin-top:16px;font-size:11px;color:#64748b;line-height:1.7}}
  tr{{break-inside:avoid;page-break-inside:avoid}}
  @media print{{ .noprint{{display:none}} body{{margin:0}} }}
</style></head><body>
  <div class="noprint" style="text-align:right;margin-bottom:8px">
    <a class="btn" href="/safety/reports">📁 평가서 목록</a>
    <button class="btn" onclick="window.print()">🖨 인쇄 / PDF로 저장</button>
  </div>
  <h1>위험성평가서 <span class="sub">(초안 · 검토 전)</span></h1>
  <div class="sub">VIGENT Safety · 생성 {e(assessment['generated_at'])}</div>
  <div class="notice">⚠ 본 문서는 AI가 자동 생성한 <b>초안</b>입니다. 안전관리자 검토·승인이 필요하며,
     법적 자문·인증이 아닙니다. 비전 판정은 보조·감시 신호이며 프레스·전단기 등의 1차 방호 책임은
     인증 하드웨어(Type 4 광전자식 방호장치·안전 PLC)에 있습니다(§8).</div>
  <div class="meta">
    <div><b>현장</b> {e(assessment['site'] or '—')}</div>
    <div><b>공정</b> {e(assessment['process'] or '—')}</div>
    <div><b>평가방법</b> {e(assessment['method'])}</div>
    <div><b>요약</b> 총 {s['총항목']}건 · 높음(상) {s['상_높음']}건</div>
  </div>
  <div class="flow">
    <span><b>①</b> 위험요인 식별</span><span>→</span>
    <span><b>②</b> 빈도·강도</span><span>→</span>
    <span><b>③</b> 위험성 추정</span><span>→</span>
    <span><b>④</b> 감소대책</span>
  </div>
  <table>
    <thead>
      <tr class="grp">
        <th colspan="5">① 위험요인 식별 (근거 인용 포함)</th>
        <th colspan="2">② 빈도·강도</th>
        <th>③ 위험성 추정</th>
        <th>④ 감소대책</th>
        <th>AI 근거</th>
      </tr>
      <tr>
        <th>유해·위험요인</th><th>공정/작업</th><th>위험분류</th><th>위험상황 및 결과</th>
        <th>관련근거(법령·가이드)</th><th>빈도</th><th>강도</th><th>위험성(등급)</th>
        <th>감소대책</th><th>AI 감지근거</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  <div class="foot">
    · 위험성 = 빈도(가능성) × 강도(중대성). 등급: 6↑ 상 / 3~5 중 / 2↓ 하<br>
    · 근거(법령·조항)는 초안 참고용이며 최신 개정·현장 적용은 안전관리자가 검증해야 합니다(§9 출처 표기 원칙).<br>
    · 개선예정일·담당자·승인란은 검토자가 직접 기입합니다.
  </div>
</body></html>"""

    def generate(self, events: list[dict[str, Any]], site: str = "", process: str = "",
                 save: bool = True) -> dict[str, Any]:
        """이벤트 → 평가표 + HTML 생성(+저장). 반환: {assessment, html, saved_path}"""
        assessment = self.build_assessment(events, site, process)
        page = self.render_html(assessment)
        saved_path = None
        if save:
            _SAVE_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            (_SAVE_DIR / f"ra_{stamp}.html").write_text(page, encoding="utf-8")
            (_SAVE_DIR / f"ra_{stamp}.json").write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_path = str((_SAVE_DIR / f"ra_{stamp}.html").relative_to(_ROOT))
        return {"assessment": assessment, "html": page, "saved_path": saved_path}

    # ── 저장된 평가서 목록·다시열기 (감사추적) ──
    @staticmethod
    def list_saved(limit: int = 100) -> list[dict[str, Any]]:
        """저장된 위험성평가서 목록(최신순). id 로 다시 열 수 있다."""
        if not _SAVE_DIR.exists():
            return []
        out = []
        for jf in sorted(_SAVE_DIR.glob("ra_*.json"), reverse=True)[:limit]:
            try:
                a = json.loads(jf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            out.append({
                "id": jf.stem,                       # 예: ra_20260619_111630
                "generated_at": a.get("generated_at", ""),
                "site": a.get("site", ""), "process": a.get("process", ""),
                "총항목": a.get("summary", {}).get("총항목", 0),
                "상_높음": a.get("summary", {}).get("상_높음", 0),
                "has_html": (_SAVE_DIR / f"{jf.stem}.html").exists(),
            })
        return out

    @staticmethod
    def load_html(aid: str) -> str | None:
        """저장된 평가서 HTML 을 그대로 반환(다시열기). 없으면 None."""
        # 경로 조작 방지: 파일명만 허용
        if "/" in aid or ".." in aid:
            return None
        p = _SAVE_DIR / f"{aid}.html"
        return p.read_text(encoding="utf-8") if p.exists() else None

    def run(self, events: list[dict[str, Any]] | None = None, **kw) -> dict[str, Any]:
        return self.generate(events or [], **kw)
