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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .base import BaseAgent

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent.parent
_SAVE_DIR = _ROOT / "data" / "risk_assessments"

# vision.yaml 규칙 id → 위험성평가 KB (BODA RISK_ASSESS 이식)
RULE_KB: dict[str, dict[str, Any]] = {
    "falling_object": {
        "hazard": "낙하물(물체에 맞음)", "work": "고소작업 하부·자재 양중·적재", "cat": "물체에 맞음",
        "harm": "상부 자재·공구 낙하로 하부 작업자 충격·중대재해",
        "law": "산업안전보건기준에 관한 규칙 제14·15조(낙하물 방지)", "sev": 3,
        "act": "낙하물 방지망·방호선반 설치, 하부 출입통제, 자재 결속, 안전모 착용"},
    "height_fall_risk": {
        "hazard": "고소작업 추락위험(가장자리·개구부)", "work": "고소작업·비계·지붕·개구부", "cat": "떨어짐(추락)",
        "harm": "가장자리·개구부에서 추락해 사망·중상(사망재해 1위)",
        "law": "산업안전보건기준에 관한 규칙 제42·43조(추락·개구부)", "sev": 3,
        "act": "안전대 체결·안전난간·개구부 덮개·추락방호망, 작업발판 확보"},
    "machine_entanglement": {
        "hazard": "기계 끼임(롤러·컨베이어·회전부)", "work": "기계 운전·정비·청소", "cat": "끼임",
        "harm": "회전·가동부에 신체·옷 말려들어 절단·사망",
        "law": "산업안전보건기준에 관한 규칙 제87조 등(원동기·회전축 방호)", "sev": 3,
        "act": "방호덮개·비상정지, 정비 시 전원차단(LOTO), 헐렁한 옷·장갑 금지"},
    "asphyxiation": {
        "hazard": "질식(밀폐공간 산소결핍·유해가스)", "work": "맨홀·탱크·정화조·지하", "cat": "질식",
        "harm": "산소결핍·유해가스로 의식소실·사망(구조자 동반사고 多)",
        "law": "산업안전보건기준에 관한 규칙 제619~625조(밀폐공간)", "sev": 3,
        "act": "출입 전·중 가스측정·환기, 감시인 배치, 송기마스크, 구조장비"},
    "gas_alarm": {
        "hazard": "유해·가연성 가스 경보", "work": "화학·가스 취급, 밀폐공간", "cat": "질식·화재폭발",
        "harm": "유해가스 중독 또는 가연성 가스 누출로 화재·폭발",
        "law": "산업안전보건기준에 관한 규칙 제232·241조 등", "sev": 3,
        "act": "가스검지·경보, 환기·누출원 차단, 화기금지, 대피"},
    "heat_stress": {
        "hazard": "온열질환(폭염)", "work": "옥외·고온 작업", "cat": "온열질환",
        "harm": "고온·고습 환경에서 열사병 등으로 쓰러짐·사망",
        "law": "산업안전보건기준에 관한 규칙 제566조 등·폭염대책", "sev": 2,
        "act": "그늘·휴식·물·소금, 작업시간 조정(무더위 휴식), 건강상태 확인"},
    "electrical_hazard": {
        "hazard": "감전(전기위험)", "work": "전기작업·활선 인접·누전", "cat": "감전",
        "harm": "활선 접촉·누전으로 감전 사망·화상",
        "law": "산업안전보건기준에 관한 규칙 제301~310조(전기작업)", "sev": 3,
        "act": "정전작업·잠금(LOTO), 절연보호구, 누전차단기, 활선 이격거리"},
    "immobility": {
        "hazard": "장시간 무동작(45초 이상 정지 — 확인 필요)", "work": "작업장 전반", "cat": "무동작·고립",
        "harm": "작업자가 쓰러져 장시간 방치 시 응급대응 지연으로 중대재해",
        "law": "산업안전보건기준에 관한 규칙 제82조(구급용구)·비상대응", "sev": 3,
        "act": "즉시 현장 확인·응급조치, 비상연락·후송, 단독작업 관리, 감시 강화"},
    "rapid_motion": {
        "hazard": "급격한 이동(돌진·이상행동)", "work": "차량·기계 인접, 통로", "cat": "충돌·전도·이상상황",
        "harm": "갑작스러운 돌진·이상행동으로 충돌·전도 또는 위급상황 신호",
        "law": "산업안전보건기준에 관한 규칙 제3·20조", "sev": 2,
        "act": "현장 확인, 동선·속도 관리, 위급 시 대응, 출입통제"},
    "crowd_density": {
        "hazard": "인원 밀집(혼잡)", "work": "다중 작업·통로·집결 구역", "cat": "압사·전도·동선충돌",
        "harm": "좁은 공간 인원 밀집으로 전도·압사·대피 지연",
        "law": "산업안전보건기준에 관한 규칙 제22조(통로의 설치)", "sev": 2,
        "act": "인원 분산·통로 확보, 출입 제한, 비상대피로 확보, 혼잡 관리"},
    "lone_worker": {
        "hazard": "단독작업(2인1조 위반)", "work": "밀폐공간·전기·수중·화기 등 고위험 작업", "cat": "구조지연·질식·감전",
        "harm": "감시인 없는 단독작업으로 사고 시 구조 지연·2차 재해",
        "law": "산업안전보건기준에 관한 규칙 제619조·제623조(밀폐공간 작업·감시인 배치)", "sev": 3,
        "act": "2인1조·감시인 배치, 비상연락 체계, 단독작업 금지"},
    "proximity_hazard": {
        "hazard": "작업반경 침입(협착·충돌)", "work": "지게차·차량계·크레인 작업 인접", "cat": "협착·충돌·깔림",
        "harm": "지게차·중장비 작업반경에 근로자 진입으로 협착·충돌·깔림 중대재해",
        "law": "산업안전보건법 제38조·안전보건규칙 제20·172~200조(차량계·출입금지)", "sev": 3,
        "act": "작업반경 출입통제, 보행자-차량 동선 분리, 유도자 배치, 후방경보·접근경보"},
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
    "guard_bypass": {
        "hazard": "프레스/전단기 방호장치 우회", "work": "프레스·전단기 작업", "cat": "협착·절단",
        "harm": "방호구역에 신체 진입으로 협착·절단 중대재해",
        "law": "산업안전보건법 제80조·안전보건규칙 제103~105조(방호장치)", "sev": 3,
        "act": "광전자식 방호장치 점검, 양수조작식 조작부, 인증 안전회로 연동(§8: 비전은 보조신호)"},
    # ── 공종별 TBM 연동을 위한 추가 매핑(근거는 safety_citations.json 동일 규칙 인용) ──
    "fire_smoke": {
        "hazard": "화재·폭발(화기·인화물)", "work": "화기작업·인화물 취급", "cat": "화재·폭발·화상",
        "harm": "불티·인화물로 화재·폭발 및 화상",
        "law": "산업안전보건법 제38조·안전보건규칙 제241조 등(화재위험작업)", "sev": 3,
        "act": "가연물 제거·차단, 소화설비 비치, 화기감시인 배치, 화기작업 허가서, 불티비산방지"},
    "trip_hazard": {
        "hazard": "전도·미끄러짐(통로·바닥)", "work": "이동·통행·정리정돈 작업", "cat": "전도·전락",
        "harm": "통로·바닥 위험요인에 걸려 넘어짐·미끄러짐",
        "law": "산업안전보건법 제38조·안전보건규칙 제3조(전도의 방지)", "sev": 1,
        "act": "통로 확보·정리정돈, 케이블 정리, 미끄럼 방지 조치"},
    "ergonomic_risk": {
        "hazard": "근골격계 부담(자세·반복)", "work": "반복·부적절 자세 작업", "cat": "근골격계질환",
        "harm": "부적절한 자세·반복작업으로 근골격계 질환",
        "law": "안전보건규칙 제656~662조(근골격계부담작업)", "sev": 1,
        "act": "작업자세 개선, 중량물 보조기구, 주기적 휴식·스트레칭"},
}


def _likelihood(count: int) -> int:
    return 1 if count <= 2 else (2 if count <= 8 else 3)


def _severity_from_levels(levels: dict[str, int], default: int) -> int:
    """실제 이벤트 등급 분포 → 중대성(1~3). 위험유형 고유 중대성(default)과 max 로 결합
    → '이 유형은 원래 위험' + '실제로도 심각했나' 둘 다 반영(고정값 아님)."""
    if not levels:
        return default
    crit = levels.get("critical", 0)
    high = levels.get("high", 0)
    mid = levels.get("mid", 0) + levels.get("medium", 0)
    if crit > 0 or high > 0:
        observed = 3
    elif mid > 0:
        observed = 2
    else:
        observed = 1
    return max(int(default), observed)


def _level(score: int) -> tuple[str, str]:
    if score >= 6:
        return "상", "#ef4444"
    if score >= 3:
        return "중", "#f59e0b"
    return "하", "#10b981"


# ── 감소대책 위계 분류(고시 제12조 순서) ────────────────────────────────
# 일반 규칙(특정 시나리오 과적합 금지): 인적 대책(신호수·유도자·감시·교육)=관리적,
# 설비·구조 대책(센서·펜스·방호·경보·방지망)=공학적으로 더 상위.
# 동일 위험에 설비 대책이 있으면 그것을 최상위로 제시한다(사람 개입은 보조).
_TIER_KW: list[tuple[str, list[str]]] = [
    ("제거·대체", ["폐지", "대체", "설계단계", "제거", "무인화", "자동화 대체", "공정변경"]),
    ("공학적",   ["방지망", "방호선반", "방호덮개", "방호장치", "덮개", "펜스", "울타리", "난간",
                 "센서", "자동정지", "인터록", "연동", "비상정지", "차단기", "경보", "국소배기",
                 "환기장치", "방호", "격리", "설비"]),
    ("관리적",   ["신호수", "유도자", "감시", "감시인", "교육", "점검", "출입통제", "출입금지",
                 "동선", "절차", "작업계획", "작업발판", "지도", "배치", "결속", "loto",
                 "전원차단", "휴식", "순환", "표지", "게시", "제한"]),
    ("보호구",   ["보호구", "안전모", "안전대", "안전화", "마스크", "조끼", "착용",
                 "송기마스크", "공기호흡기", "장갑"]),
]


def _classify_measures(act: str) -> dict[str, list[str]]:
    """감소대책 평문 → 고시 12조 위계별 분류(정렬: 제거>공학>관리>PPE). 원본 항목 보존(누락 없음).
    설비>인적 원칙: 각 항목을 상위 위계부터 키워드 매칭해 최초 매칭 위계에 배치."""
    tiers: dict[str, list[str]] = {"제거·대체": [], "공학적": [], "관리적": [], "보호구": []}
    for raw in str(act or "").split(","):
        item = raw.strip()
        if not item:
            continue
        low = item.lower()
        for tier, kws in _TIER_KW:
            if any(kw.lower() in low for kw in kws):
                tiers[tier].append(item)
                break
        else:
            tiers["관리적"].append(item)   # 미분류 → 보수적으로 관리적(인적/절차)로 취급
    return {k: v for k, v in tiers.items() if v}


_LAW_ART = re.compile(r"제\s*\d+조.*$")


def _split_law(s: str) -> tuple[str, str]:
    """'산업안전보건기준에 관한 규칙 제40조' → ('산업안전보건기준에 관한 규칙','제40조')."""
    s = str(s or "").strip()
    m = _LAW_ART.search(s)
    if m:
        return s[:m.start()].strip(), m.group(0).strip()
    return s, ""


_EVIDENCE_DIR = (_ROOT / "data" / "evidence").resolve()


def _safe_evidence_path(relpath: str) -> Path | None:
    """evidence 상대경로를 data/evidence 하위로 '격리'한다(P0-1 path traversal 차단).
    '../../etc/passwd'·절대경로·심링크 탈출 등 evidence 디렉토리 밖을 가리키면 None(+경고 로그).
    경로만 로깅하고 파일 내용은 절대 노출하지 않는다."""
    if not relpath:
        return None
    try:
        p = (_ROOT / relpath).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not p.is_relative_to(_EVIDENCE_DIR):
        try:
            import logging
            logging.getLogger("vigent.scribe").warning(
                "evidence 경로 격리 위반 차단(path traversal 의심): %r", relpath)
        except Exception:  # noqa: BLE001  로깅 실패해도 차단은 유지
            pass
        return None
    return p


def _evidence_data_uri(relpath: str, max_bytes: int = 4_000_000) -> str | None:
    """data/evidence 상대경로 → data URI(base64). 문서에 사진을 내장해 이동·이메일에도 보존.
    없거나 너무 크거나 evidence 디렉토리 밖(traversal)이면 None(저하 없이 사진만 생략)."""
    p = _safe_evidence_path(relpath)   # ★ P0-1: data/evidence 하위로 격리(밖이면 None)
    if p is None or not p.is_file():
        return None
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > max_bytes:
        return None
    import base64
    ext = p.suffix.lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64," + base64.b64encode(raw).decode()


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
                         site: str = "", process: str = "", use_vlm: bool = False,
                         use_llm: bool = False) -> dict[str, Any]:
        """이벤트 목록 → 위험성평가표(초안). events=[{rule, count, levels, evidence_paths, notes}].
        중대성=실제 등급 분포로 산출(고정값 아님), 증거사진·정황·(옵션)VLM 장면설명 반영."""
        rows: list[dict[str, Any]] = []
        dropped: list[str] = []           # RULE_KB 에 없는 미지 rule(표 제외분) 집계
        for ev in events or []:
            rule = ev.get("rule") or ev.get("type")
            count = int(ev.get("count", 1) or 1)
            kb = RULE_KB.get(rule)
            if not kb:
                dropped.append(rule)      # 미지 rule → 표에서 제외(집계해 응답에 보고)
                continue
            likely = _likelihood(count)
            sev = _severity_from_levels(ev.get("levels") or {}, int(kb["sev"]))  # 실제 등급 기반
            score = likely * sev
            lvl, color = _level(score)
            # Copilot 근거(법령 인용) 삽입 — 출처 포함(§9)
            citations = []
            if self.copilot is not None:
                citations = self.copilot.cite(rule).get("citations", [])
                # 법령 화이트리스트 감사(비파괴): 보류 조문은 '로그만'(문서 불변, §6).
                # 자주 인용 시도되는 보류 조문 빈도 데이터를 수집한다(필요 기반 우선순위, §7).
                try:
                    import legal_whitelist
                    legal_whitelist.audit_citations(citations, doc_type="위험성평가", rule_id=rule)
                except Exception:  # noqa: BLE001
                    pass
            # 증거 사진(이벤트 캡쳐) 자동 첨부 — data URI 로 문서에 내장(최대 4장) + VLM 장면설명
            ev_items = ev.get("evidence_items")
            if ev_items:
                pairs = [(it.get("path"), it.get("note", "")) for it in ev_items]
            else:
                _paths = ev.get("evidence_paths") or ([ev["evidence"]] if ev.get("evidence") else [])
                _notes = ev.get("notes") or []
                pairs = [(p, (_notes[i] if i < len(_notes) else "")) for i, p in enumerate(_paths)]
            ev_imgs = []
            for _p, _note in pairs[:4]:
                _uri = _evidence_data_uri(_p)
                if _uri:
                    ev_imgs.append({"uri": _uri, "note": _note})
            # (옵션) VLM 장면설명 — 첫 증거 사진을 보고 정황 한 줄(느림, opt-in)
            if use_vlm and ev_imgs and pairs:
                try:
                    import cv2
                    import vlm_confirm
                    _sp = _safe_evidence_path(pairs[0][0])   # ★ P0-1: evidence 격리(밖이면 None → 건너뜀)
                    _img = cv2.imread(str(_sp)) if _sp is not None else None
                    _desc = vlm_confirm.describe_scene(_img) if _img is not None else ""
                    if _desc:
                        _n = ev_imgs[0]["note"]
                        ev_imgs[0]["note"] = (_n + " · " if _n else "") + "AI 장면분석: " + _desc
                except Exception:  # noqa: BLE001
                    pass
            rows.append({
                # ── KOSHA KRAS 서식 11 컬럼 구조 ──
                "rule": rule,
                "세부작업내용": kb["work"],                 # 1. 세부 작업 내용
                "유해위험요인": kb["hazard"],                # 2. 유해·위험요인(요약 명칭)
                "위험분류": kb["cat"],                       # 2a. 위험 분류
                "위험상황및결과": kb["harm"],                # 2b. 위험발생 상황 및 결과
                "관련근거": kb["law"],                       # 3. 관련근거(법적기준)
                "현재안전보건조치": kb.get("now", "AI 영상 감지·실시간 경보·기록"),  # 4. 현재의 안전보건조치
                "가능성_빈도": likely,                        # 5a. 가능성(빈도)
                "중대성_강도": sev,                          # 5b. 중대성(강도)
                "위험성": score,                             # 5c. 위험성(가능성×중대성)
                "위험성등급": lvl,
                "감소대책": kb["act"],                       # 6. 위험성 감소대책(평문, 보존)
                "감소대책_위계": _classify_measures(kb["act"]),  # 6a. 고시12조 위계별(설비>인적)
                "개선후위험성": "",                          # 7. 개선후 위험성(검토자 기입)
                "개선예정일": "",                            # 8. 개선 예정일(검토자 기입)
                "완료일": "",                                # 9. 완료일(검토자 기입)
                "담당자": "",                                # 10. 담당자(검토자 기입)
                "AI감지근거": (f"AI {count}회 감지" + (
                    " (" + ", ".join(p for p in [
                        f"심각 {(ev.get('levels') or {}).get('critical')}" if (ev.get('levels') or {}).get('critical') else "",
                        f"높음 {(ev.get('levels') or {}).get('high')}" if (ev.get('levels') or {}).get('high') else "",
                        f"경계 {(ev.get('levels') or {}).get('mid', 0) + (ev.get('levels') or {}).get('medium', 0)}" if ((ev.get('levels') or {}).get('mid', 0) + (ev.get('levels') or {}).get('medium', 0)) else "",
                        f"주의 {(ev.get('levels') or {}).get('low')}" if (ev.get('levels') or {}).get('low') else "",
                    ] if p) + ")" if (ev.get('levels')) else "")),
                "citations": citations, "_color": color, "_evidence": ev_imgs,
            })
        rows.sort(key=lambda r: r["위험성"], reverse=True)
        high = [r for r in rows if r["위험성등급"] == "상"]
        _result = {
            "site": site, "process": process,
            "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "method": "위험성 = 가능성(빈도) × 중대성(강도)",
            "form_standard": "kosha_kras",            # 정본 = KOSHA KRAS 서식 11
            "form_label": "KOSHA KRAS 표준 위험성평가 양식(서식 11) 기준",
            "form_source": "한국산업안전보건공단 OSHRI · "
                           "oshri.kosha.or.kr/kosha/data/format (articleNo=297038)",
            "status": "draft", "review_required": True,
            "summary": {"총항목": len(rows), "상_높음": len(high),
                        "주요위험": [r["유해위험요인"] for r in high]},
            "rows": rows,
            "dropped_rules": dropped,      # 미지 rule 목록(있으면 유효항목 0일 때 저장 생략 판단에 사용)
        }
        # 가산식: 종합의견 서술. use_llm=True 면 LLM, 기본은 결정적 폴백(즉시). 표 11칸·법령은 위 그대로 유지.
        _narr, _src = self._narrative(_result, use_llm=use_llm)
        _result["narrative"] = _narr
        _result["narrative_source"] = _src
        return _result

    def _narrative(self, a: dict[str, Any], use_llm: bool = False) -> tuple[str, str]:
        """종합의견 서술 → (text, source).
        use_llm=True 일 때만 LLM(llm_provider) 호출(느림). 기본(False)은 결정적 로컬 폴백으로 즉시 생성.
        표 rows·법령 인용은 이 함수와 무관(항상 결정적) — 여기선 '종합의견 텍스트'만 만든다.
        프롬프트엔 비식별 집계만 사용(실명·사번·연락처 금지 — 구역/공정·위험요인·등급·빈도·법령만)."""
        s = a.get("summary", {}) or {}
        rows = a.get("rows", []) or []
        site = a.get("site") or "현장"
        process = a.get("process") or ""
        total = s.get("총항목", len(rows))
        high_n = s.get("상_높음", 0)
        main = s.get("주요위험", []) or []
        # ── 비식별 집계 텍스트(개인정보 없음) ──
        lines = [f"- {r.get('유해위험요인')}: 등급 {r.get('위험성등급')}"
                 f"(위험성 {r.get('위험성')}), {r.get('AI감지근거', '')}, 근거 {r.get('관련근거', '')}"
                 for r in rows[:12]]
        agg = (f"현장/구역: {site}\n공정: {process or '(미지정)'}\n"
               f"총 위험항목 {total}개 · 상(높음) {high_n}개 · 주요위험: "
               f"{', '.join(main) if main else '없음'}\n" + "\n".join(lines))
        system = ("당신은 한국 산업안전보건 위험성평가 전문가다. 아래 '집계 데이터에만' 근거해 "
                  "위험성평가 종합의견을 한국어로 6~10문장으로 간결·전문적으로 작성한다. "
                  "데이터에 없는 수치·법령·사실을 지어내지 말고, 개인정보(실명·사번)는 언급하지 마라. "
                  "우선순위 개선방향과 관리적 권고를 포함하되, 최종 판단은 안전관리자 확인이 필요함을 명시하라.")
        prompt = "다음 위험성평가 집계로 '종합의견'을 작성하라:\n\n" + agg
        # LLM 종합의견은 use_llm=True 일 때만(기본 off → 즉시 응답, 아래 결정적 폴백 사용).
        if use_llm:
            try:
                import llm_provider
                txt, backend = llm_provider.reason_text(prompt, system)
            except Exception:  # noqa: BLE001  provider 자체 문제도 폴백
                txt, backend = None, None
            if txt:
                return txt, f"AI({backend})"  # 실제 백엔드명 표기(OpenAI:... / Claude:...)
        # ── 로컬 폴백(결정적 템플릿, 항상 동작) ──
        parts = [f"본 위험성평가는 {site}{(' ' + process) if process else ''}에서 "
                 f"AI가 감지·기록한 위험 {total}개 항목을 분석한 결과다."]
        if high_n:
            parts.append(f"이 중 '상(높음)' 등급이 {high_n}개로 우선 개선이 필요하다.")
        if main:
            parts.append(f"주요 위험요인은 {', '.join(main[:5])} 등이다.")
        if rows:
            top = rows[0]
            parts.append(f"가장 위험성이 높은 항목은 '{top.get('유해위험요인')}'"
                         f"(위험성 {top.get('위험성')}, {top.get('관련근거', '')})로, "
                         f"해당 감소대책의 즉시 이행이 권고된다.")
        parts.append("본 종합의견은 AI 초안이며, 최종 위험성 판단과 조치는 안전관리자 확인 하에 이뤄져야 한다.")
        return " ".join(parts), "로컬 규칙 기반"

    def render_html(self, assessment: dict[str, Any]) -> str:
        """위험성평가표 → KOSHA KRAS 서식 11 구조의 인쇄/PDF용 자체 완결형 HTML."""
        e = html.escape
        rows_html = ""
        _TIER_ORDER = ["제거·대체", "공학적", "관리적", "보호구"]
        _TIER_TIP = {"공학적": "설비·구조(상위)", "관리적": "인적·절차(보조)", "보호구": "최후"}
        def _cite_line(c):
            base = f"· {e(c['source'])} {e(c['clause'])}"
            # 보류(화이트리스트 밖) 법령은 시각 플래그만(제거 아님 → §6 저하 없음).
            try:
                import legal_whitelist as _L
                lk = _L._canon_law(c.get("source", "")); an = _L._art_num(c.get("clause", ""))
                if lk is not None and an is not None and not _L.is_whitelisted(lk, an):
                    base += ' <span class="src">⚠화이트리스트 외·검토필요</span>'
            except Exception:  # noqa: BLE001
                pass
            return base
        for r in assessment["rows"]:
            cites = "<br>".join(_cite_line(c) for c in r.get("citations", [])) or "—"
            # 감소대책 위계 렌더 — 고시12조 순서(설비>인적). 위계 없으면 평문 폴백(저하 없음).
            _tiers = r.get("감소대책_위계") or {}
            if _tiers:
                measure_html = "".join(
                    f'<div class="tier"><b>{e(t)}</b>'
                    f'<span class="src">({e(_TIER_TIP.get(t, ""))})</span>: {e(", ".join(_tiers[t]))}</div>'
                    for t in _TIER_ORDER if _tiers.get(t))
            else:
                measure_html = e(r["감소대책"])
            rows_html += f"""
      <tr>
        <td>{e(r['세부작업내용'])}<div class="hz">[{e(r['유해위험요인'])}]</div></td>
        <td>{e(r['위험분류'])}</td>
        <td>{e(r['위험상황및결과'])}</td>
        <td>{e(r['관련근거'])}<div class="cite">{cites}</div></td>
        <td>{e(r['현재안전보건조치'])}<div class="ai">{e(r['AI감지근거'])}</div></td>
        <td style="text-align:center">{r['가능성_빈도']}</td>
        <td style="text-align:center">{r['중대성_강도']}</td>
        <td style="text-align:center"><b style="color:{r['_color']}">{r['위험성']}<br>({e(r['위험성등급'])})</b></td>
        <td>{measure_html}</td>
        <td></td>
        <td></td><td></td><td></td>
      </tr>"""
        s = assessment["summary"]
        # 출처 배지: 공식 서식 기준 vs 임시 양식
        is_official = assessment.get("form_standard") == "kosha_kras"
        badge = (f'<span class="badge ok">표준 서식 기준</span> {e(assessment.get("form_label",""))}'
                 if is_official else
                 '<span class="badge tmp">표준 항목 기반 임시 양식</span> (공식 서식 미확보)')
        source_line = (f'<div class="src">서식 출처: {e(assessment.get("form_source",""))}</div>'
                       if is_official else "")
        # 📷 현장 증거 사진 섹션(이벤트 캡쳐 자동 첨부). 사진 없으면 섹션 자체를 생략.
        ev_cards = ""
        for r in assessment["rows"]:
            for img in r.get("_evidence", []) or []:
                _uri = img.get("uri") if isinstance(img, dict) else img
                _note = img.get("note") if isinstance(img, dict) else ""
                note_html = f'<div class="evnote">🧠 VLM 장면분석(초안): {e(_note)}</div>' if _note else ""
                ev_cards += (f'<div class="evc"><img src="{_uri}" alt="증거">'
                             f'<div class="evcap">[{e(r["유해위험요인"])}] · {e(r.get("AI감지근거",""))}</div>'
                             f'{note_html}</div>')
        ev_section = (f'<div class="evsec"><h3>📷 현장 증거 사진 '
                      f'<span class="src">(이벤트 발생 시 자동 캡쳐 · 안전관리자 확인용)</span></h3>'
                      f'<div class="evgrid">{ev_cards}</div></div>') if ev_cards else ""
        # 종합의견(narrative) — 있을 때만 렌더. 출처(AI/로컬) 배지 표기.
        _narr = assessment.get("narrative")
        narr_section = ""
        if _narr:
            _src = e(assessment.get("narrative_source", ""))
            narr_section = (
                '<div style="margin:16px 0;padding:14px 16px;border:1px solid #d0d7de;'
                'border-left:4px solid #d4a017;border-radius:8px;background:#fbfaf5">'
                f'<h3 style="margin:0 0 8px;font-size:15px">📝 종합의견 '
                f'<span class="src">(AI 초안 · 출처: {_src} · 안전관리자 검토 필요)</span></h3>'
                f'<div style="line-height:1.7;white-space:pre-wrap;font-size:13.5px">{e(_narr)}</div></div>')
        return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>VIGENT 위험성평가서(초안) — KOSHA KRAS 서식</title>
<style>
  @page {{ size:A4 landscape; margin:10mm; }}
  body{{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;color:#0f172a;margin:24px;}}
  h1{{font-size:19px;margin:0 0 4px}} .sub{{color:#64748b;font-size:13px}}
  .badge{{display:inline-block;padding:2px 9px;border-radius:6px;font-size:12px;font-weight:700}}
  .badge.ok{{background:#dcfce7;color:#166534;border:1px solid #16a34a}}
  .badge.tmp{{background:#fef3c7;color:#92400e;border:1px solid #f59e0b}}
  .src{{color:#64748b;font-size:11px;margin-top:3px}}
  .notice{{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:10px 12px;margin:12px 0;font-size:12px}}
  .meta{{font-size:13px;margin:8px 0}} .meta b{{display:inline-block;min-width:70px;color:#475569}}
  table{{width:100%;border-collapse:collapse;font-size:11px;margin-top:8px}}
  th,td{{border:1px solid #94a3b8;padding:5px 7px;vertical-align:top;text-align:left}}
  thead th{{background:#e2e8f0;text-align:center}}
  .hz{{color:#b91c1c;font-size:10.5px;margin-top:3px;font-weight:600}}
  .cite{{color:#2563eb;font-size:10px;margin-top:3px;line-height:1.5}}
  .ai{{color:#64748b;font-size:10px;margin-top:3px}}
  .btn{{padding:9px 16px;border:1px solid #334155;border-radius:8px;background:#0f172a;color:#fff;cursor:pointer;text-decoration:none}}
  .foot{{margin-top:14px;font-size:11px;color:#64748b;line-height:1.7}}
  .evsec{{margin-top:18px;break-inside:avoid}} .evsec h3{{font-size:14px;margin:0 0 8px}}
  .evgrid{{display:flex;flex-wrap:wrap;gap:10px}}
  .evc{{border:1px solid #94a3b8;border-radius:6px;padding:6px;width:240px;break-inside:avoid}}
  .evc img{{width:100%;border-radius:4px;display:block}}
  .evcap{{font-size:10.5px;color:#475569;margin-top:4px}}
  .evnote{{font-size:10.5px;color:#1e40af;background:#eff6ff;border:1px solid #bfdbfe;border-radius:4px;padding:4px 6px;margin-top:4px;line-height:1.5}}
  tr{{break-inside:avoid;page-break-inside:avoid}}
  @media print{{ .noprint{{display:none}} body{{margin:0}} }}
</style></head><body>
  <div class="noprint" style="text-align:right;margin-bottom:8px">
    <a class="btn" href="/safety/reports">📁 평가서 목록</a>
    <button class="btn" onclick="window.print()">🖨 인쇄 / PDF로 저장</button>
  </div>
  <h1>위험성평가표 <span class="sub">(초안 · 검토 전)</span></h1>
  <div class="sub">VIGENT Safety · 생성 {e(assessment['generated_at'])}</div>
  <div style="margin:8px 0">{badge}{source_line}</div>
  <div class="notice">⚠ 본 문서는 AI가 자동 생성한 <b>초안</b>입니다. 안전관리자 검토·승인이 필요하며,
     법적 자문·인증이 아닙니다. 비전 판정은 보조·감시 신호이며 프레스·전단기 등의 1차 방호 책임은
     인증 하드웨어(Type 4 광전자식 방호장치·안전 PLC)에 있습니다(§8).</div>
  <div class="meta">
    <div><b>작업공정명</b> {e(assessment['site'] or '—')} / {e(assessment['process'] or '—')}</div>
    <div><b>평가일시</b> {e(assessment['generated_at'])}</div>
    <div><b>평가방법</b> {e(assessment['method'])}</div>
    <div><b>요약</b> 총 {s['총항목']}건 · 높음(상) {s['상_높음']}건</div>
  </div>
  <table>
    <thead>
      <tr>
        <th rowspan="2" style="width:13%">세부 작업 내용<br>(유해·위험요인)</th>
        <th colspan="2">유해·위험요인 파악</th>
        <th rowspan="2" style="width:15%">관련근거<br>(법적기준)</th>
        <th rowspan="2" style="width:13%">현재의<br>안전보건조치</th>
        <th colspan="3">위험성</th>
        <th rowspan="2" style="width:14%">위험성 감소대책</th>
        <th rowspan="2">개선후<br>위험성</th>
        <th rowspan="2">개선<br>예정일</th>
        <th rowspan="2">완료일</th>
        <th rowspan="2">담당자</th>
      </tr>
      <tr>
        <th>위험 분류</th><th>위험발생 상황 및 결과</th>
        <th>가능성<br>(빈도)</th><th>중대성<br>(강도)</th><th>위험성</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  {narr_section}
  {ev_section}
  <div class="foot">
    · 양식: KOSHA KRAS 표준 위험성평가 양식(서식 11) 구조. 위험성 = 가능성(빈도) × 중대성(강도). 등급: 6↑ 상 / 3~5 중 / 2↓ 하<br>
    · 관련근거(법령·조항)는 Copilot 자동 인용이며 초안 참고용입니다. 최신 개정·현장 적용은 안전관리자가 검증해야 합니다(§9 출처 표기 원칙).<br>
    · 개선후 위험성·개선예정일·완료일·담당자는 검토자가 직접 기입합니다.
  </div>
</body></html>"""

    # ── 체크리스트법 모드(현장 실무형) — 정량법과 분리 보존, 가산 ──────────
    def _checklist_detected_row(self, rule, ev, check_point=None):
        """비전 감지 항목 → 부적정(X) 행. 위험수준=강도, 개선대책=위계 재활용."""
        kb = RULE_KB.get(rule)
        if not kb:
            return None
        _LV = {3: "상", 2: "중", 1: "하"}
        sev = _severity_from_levels(ev.get("levels") or {}, int(kb["sev"]))
        count = int(ev.get("count", 1) or 1)
        citations = []
        if self.copilot is not None:
            citations = self.copilot.cite(rule).get("citations", [])
            try:
                import legal_whitelist
                legal_whitelist.audit_citations(citations, doc_type="체크리스트", rule_id=rule)
            except Exception:  # noqa: BLE001
                pass
        return {"rule": rule, "작업공정": kb["work"], "유해위험요인": check_point or kb["hazard"],
                "적정성": "X", "위험수준": _LV.get(sev, "중"),
                "감소대책": kb["act"], "감소대책_위계": _classify_measures(kb["act"]),
                "관련근거": kb["law"], "citations": citations,
                "개선후확인": "", "AI감지근거": f"AI {count}회 감지"}

    def build_checklist(self, events: list[dict[str, Any]], site: str = "",
                        process: str = "", use_vlm: bool = False,
                        item_pool: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """비전 이벤트 → 체크리스트 위험성평가.
        item_pool 없으면: 감지된 유해위험요인만 부적정(X)으로 나열(비전 주도).
        item_pool 있으면: 점검항목 '전부' 나열 — 감지=부적정(X), 미감지 요건=‘수동확인 필요’
          (비전 미감지를 곧 적정으로 단정하지 않는다 §7 — 적정 여부는 사람이 확정).
        개선대책은 고시12조 위계 재활용. 정량법(빈도×강도)과 별개 산출."""
        rows: list[dict[str, Any]] = []
        dropped: list[str] = []
        if item_pool:
            ev_by_rule = {(e.get("rule") or e.get("type")): e for e in events or []}
            for pit in item_pool:
                rule = pit.get("rule")
                ev = ev_by_rule.get(rule) if rule else None
                if ev is not None:                                  # 비전 감지 → 부적정 X
                    row = self._checklist_detected_row(rule, ev, check_point=pit.get("check_point"))
                    if row is None:
                        continue
                else:                                               # 미감지 요건
                    laws = pit.get("법령") or []
                    ctrl = None
                    if not laws:                                    # 법령 미제공 항목만 레지스트리 보강(기존 동작·골든 보존)
                        import critical_controls as _cc
                        ctrl = _cc.match_control(pit.get("check_point", ""), process)
                    if ctrl is not None:                            # 생명직결 필수확정 → '확인필요' + 위험수준 + 법령(§7)
                        clav = ctrl.get("법령") or []
                        _cat = ctrl.get("category", "")
                        row = {"rule": rule, "작업공정": "점검항목(생명직결·필수확정)",
                               "유해위험요인": pit.get("check_point", ""),
                               "적정성": "확인필요", "위험수준": ctrl.get("기본_위험수준", "상"),
                               "감소대책": f"{_cat} 필수통제 이행·현장 확인",
                               "감소대책_위계": {"관리적": [f"{_cat} 필수통제 이행 여부 현장 확인(생명직결)"]},
                               "관련근거": ", ".join(clav),
                               "citations": [{"source": src, "clause": cl} for src, cl in map(_split_law, clav)],
                               "개선후확인": "", "AI감지근거": "생명직결 통제 · 비전 미감지 → 현장 확인 필수(필수확정)"}
                    else:                                           # 일반 미감지 요건 → 수동확인(기존)
                        tiers = pit.get("감소대책")
                        if not isinstance(tiers, dict):
                            tiers = _classify_measures(str(tiers or ""))
                        row = {"rule": rule, "작업공정": "점검항목", "유해위험요인": pit.get("check_point", ""),
                               "적정성": "−", "위험수준": "수동확인",
                               "감소대책": "; ".join(sum(tiers.values(), [])),
                               "감소대책_위계": tiers,
                               "관련근거": ", ".join(laws),
                               "citations": [{"source": src, "clause": cl} for src, cl in map(_split_law, laws)],
                               "개선후확인": "", "AI감지근거": "비전 미감지 · 수동확인 필요"}
                rows.append(row)
            _order = {"상": 0, "중": 1, "하": 2, "수동확인": 8}
        else:
            for ev in events or []:
                rule = ev.get("rule") or ev.get("type")
                if not RULE_KB.get(rule):
                    dropped.append(rule); continue
                rows.append(self._checklist_detected_row(rule, ev))
            _order = {"상": 0, "중": 1, "하": 2}
        rows.sort(key=lambda r: _order.get(r["위험수준"], 9))
        x_rows = [r for r in rows if r["적정성"] == "X"]
        must = [r for r in rows if r["적정성"] == "확인필요"]              # 생명직결 필수확정
        manual = [r for r in rows if r["위험수준"] == "수동확인"]
        high = [r for r in rows if r["위험수준"] == "상"
                and r["적정성"] in ("X", "확인필요")]                      # 부적정·필수확정 상위험
        result = {
            "site": site, "process": process,
            "generated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
            "method": "checklist",
            "method_label": "체크리스트법 (적정성 O/X/− + 상·중·하 병기)",
            "form_standard": "checklist_kr",
            "form_label": "체크리스트법 위험성평가",
            # 번호·시행일 확인분만 표기(§7): 조번호·고시번호는 표기 가능, 원문 '문구'는 미확정→인용문 미출력.
            "legal_basis": "산업안전보건법 제36조 및 사업장 위험성평가에 관한 지침"
                           "(고용노동부고시 제2024-76호) 제7조에 따른 체크리스트법",
            "status": "draft", "review_required": True,
            "summary": {"총항목": len(rows), "부적정_X": len(x_rows), "확인필요": len(must),
                        "수동확인": len(manual), "상_높음": len(high),
                        "주요위험": [r["유해위험요인"] for r in high]},
            "rows": rows,
            "dropped_rules": dropped,
        }
        top = ", ".join(result["summary"]["주요위험"]) or "없음"
        _must_txt = (f" 생명직결 통제 {len(must)}개는 비전 미감지라도 '확인필요(필수)'로 위험수준·법령과 함께 표면화됐다(현장 확인 필수)."
                     if must else "")
        _manual_txt = (f" 아울러 {len(manual)}개 요건은 비전 미감지로 '수동확인 필요'로 표기됐다."
                       if manual else "")
        result["narrative"] = (f"체크리스트 점검 결과 {len(x_rows)}개 항목이 부적정(X)으로 감지되었으며, "
                               f"위험수준 '상' 항목({top})의 개선대책 즉시 이행이 권고된다.{_must_txt}{_manual_txt} "
                               f"본 결과는 AI 초안이며 적정성 판단·최종 조치는 안전관리자 확인 하에 이뤄져야 한다.")
        result["narrative_source"] = "로컬 규칙 기반(체크리스트)"
        return result

    def render_checklist_html(self, a: dict[str, Any]) -> str:
        """체크리스트법 위험성평가 → 자체완결 HTML. 개선대책은 위계별, 보류 법령은 시각 플래그."""
        e = html.escape
        _TIER_ORDER = ["제거·대체", "공학적", "관리적", "보호구"]
        _color = {"상": "#ef4444", "중": "#f59e0b", "하": "#10b981"}

        def _cite(c):
            base = f"· {e(c['source'])} {e(c['clause'])}"
            try:
                import legal_whitelist as _L
                lk = _L._canon_law(c.get("source", "")); an = _L._art_num(c.get("clause", ""))
                if lk is not None and an is not None and not _L.is_whitelisted(lk, an):
                    base += ' <span class="src">⚠화이트리스트 외·검토필요</span>'
            except Exception:  # noqa: BLE001
                pass
            return base

        rows_html = ""
        for r in a["rows"]:
            tiers = r.get("감소대책_위계") or {}
            measures = "".join(
                f'<div><b>{e(t)}</b>: {e(", ".join(tiers[t]))}</div>'
                for t in _TIER_ORDER if tiers.get(t)) or e(r.get("감소대책", ""))
            cites = "<br>".join(_cite(c) for c in r.get("citations", [])) or "—"
            _ax = "#ef4444" if r["적정성"] == "X" else "#6b7280"   # X만 강조, −/수동확인은 회색
            _lx = _color.get(r["위험수준"], "#6b7280")
            rows_html += f"""
      <tr>
        <td>{e(r['작업공정'])}</td>
        <td>{e(r['유해위험요인'])}<div class="ai">{e(r.get('AI감지근거',''))}</div></td>
        <td style="text-align:center;font-weight:700;color:{_ax}">{e(r['적정성'])}</td>
        <td style="text-align:center"><b style="color:{_lx}">{e(r['위험수준'])}</b></td>
        <td>{measures}</td>
        <td>{cites}</td>
        <td></td>
      </tr>"""
        s = a["summary"]
        prov = e(a.get("legal_basis", ""))
        narr = e(a.get("narrative", ""))
        return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>체크리스트 위험성평가 · {e(a.get('site',''))}</title>
<style>
 body{{font-family:-apple-system,'Malgun Gothic',sans-serif;margin:24px;color:#1f2937}}
 h1{{font-size:20px;margin:0 0 4px}} .meta{{color:#6b7280;font-size:13px;margin-bottom:12px}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{border:1px solid #d0d7de;padding:6px 8px;vertical-align:top}}
 th{{background:#f3f4f6}} .ai{{color:#6b7280;font-size:11px;margin-top:3px}}
 .src{{color:#b45309;font-size:11px}} .badge{{background:#e0f2fe;color:#075985;padding:2px 8px;border-radius:10px;font-size:12px}}
 .foot{{margin-top:14px;color:#6b7280;font-size:12px;line-height:1.7}}
 .prov{{background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:6px}}
</style></head><body>
 <h1>위험성평가서 — 체크리스트법</h1>
 <div class="meta"><span class="badge">{e(a.get('method_label',''))}</span>
   현장: {e(a.get('site') or '(미지정)')} · 공정: {e(a.get('process') or '(미지정)')} · {e(a.get('generated_at',''))}</div>
 <div class="meta">점검 {s.get('총항목',0)}건 · 부적정(X) {s.get('부적정_X',0)} · 수동확인 {s.get('수동확인',0)} · 위험수준 상 {s.get('상_높음',0)}</div>
 <table>
  <thead><tr>
   <th style="width:14%">작업/공정</th><th style="width:20%">유해·위험요인</th>
   <th style="width:7%">적정성<br>(O/X/−)</th><th style="width:7%">위험<br>수준</th>
   <th style="width:24%">부적정 시 개선대책(위계순)</th><th style="width:20%">관련 법령</th>
   <th style="width:8%">개선 후<br>확인</th>
  </tr></thead>
  <tbody>{rows_html}
  </tbody>
 </table>
 <div style="margin:14px 0;padding:12px 14px;border:1px solid #d0d7de;border-left:4px solid #d4a017;border-radius:8px;background:#fbfaf5">
   <b>📝 종합의견</b> <span class="src">(AI 초안 · 안전관리자 검토 필요)</span><br>{narr}</div>
 <div class="foot">
   · 방법: 체크리스트법. 적정성 — 적정 O / 부적정 X / 해당없음 −. 위험수준은 부적정(X) 항목의 개선 우선순위(상·중·하).<br>
   · 법적 근거: <span class="prov">{prov}</span> <span class="src">(고시번호·조번호는 확인분 · 원문 문구는 대조 대기 — 인용문 미표기)</span><br>
   · 개선대책은 고시 위계(제거·대체 &gt; 공학 &gt; 관리 &gt; 개인보호구) 순. 관련 법령은 Copilot 자동 인용(초안 참고).<br>
   · 적정성(O/X) 판단과 최종 조치는 <b>안전관리자 검토용 초안</b>이며 사람이 확정해야 합니다.
 </div>
</body></html>"""

    def generate(self, events: list[dict[str, Any]], site: str = "", process: str = "",
                 save: bool = True, use_vlm: bool = False, use_llm: bool = False,
                 mode: str = "checklist", item_pool: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """이벤트 → 평가표 + HTML 생성(+저장). 반환: {assessment, html, saved_path}.
        mode: 'checklist'(체크리스트법, 현장 실무형·기본) | 'quantitative'(빈도×강도, 3×3 보존).
        item_pool(checklist 전용): 점검항목 풀 — 있으면 전 항목 나열(미감지=수동확인).
        use_llm=True 일 때만 종합의견을 LLM 으로(느림). 기본은 결정적 폴백(즉시 · rows·법령 불변)."""
        if mode == "checklist":
            assessment = self.build_checklist(events, site, process, use_vlm=use_vlm, item_pool=item_pool)
            page = self.render_checklist_html(assessment)
        else:
            assessment = self.build_assessment(events, site, process, use_vlm=use_vlm, use_llm=use_llm)
            page = self.render_html(assessment)
        rows = assessment.get("rows") or []
        dropped = assessment.get("dropped_rules") or []
        saved_path = None
        # 유효 위험항목이 0이면 저장 생략(빈 평가서 파일 누적 방지). rows>0 이면 기존대로 저장(법령·구조 불변).
        if save and rows:
            _SAVE_DIR.mkdir(parents=True, exist_ok=True)
            _now = datetime.now(KST)
            base = _now.strftime("%Y%m%d_%H%M%S")
            stamp = base
            # 같은 초 저장 충돌 회피(덮어쓰기 금지): 이미 있으면 마이크로초→카운터 접미사로 고유화
            if (_SAVE_DIR / f"ra_{stamp}.html").exists():
                _mi = _now.strftime("%f")
                stamp = f"{base}_{_mi}"
                _n = 1
                while (_SAVE_DIR / f"ra_{stamp}.html").exists():
                    stamp = f"{base}_{_mi}_{_n}"
                    _n += 1
            (_SAVE_DIR / f"ra_{stamp}.html").write_text(page, encoding="utf-8")
            (_SAVE_DIR / f"ra_{stamp}.json").write_text(
                json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
            saved_path = str((_SAVE_DIR / f"ra_{stamp}.html").relative_to(_ROOT))
        return {"assessment": assessment, "html": page, "saved_path": saved_path,
                "saved": saved_path is not None, "dropped_rules": dropped}

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
        """저장된 평가서 HTML 을 그대로 반환(다시열기). 없으면 None.

        [1단계 L-2] 경로 검증을 금지목록('/'·'..')에서 **격리 확인**(_safe_evidence_path 와 같은
        resolve + is_relative_to)으로 교체 — 예전 방식은 Windows 역슬래시·드라이브 경로(C:\\...)를
        못 막아, 저장 폴더 밖 임의 .html 을 읽을 수 있었다(pathlib 이 드라이브 절대경로를 만나면
        앞부분을 통째로 버린다)."""
        try:
            p = (_SAVE_DIR / f"{aid}.html").resolve()
            if not p.is_relative_to(_SAVE_DIR.resolve()):
                return None
        except (OSError, ValueError):   # NUL 문자·해석 불가 경로 등 — 조용히 없음 처리
            return None
        return p.read_text(encoding="utf-8") if p.exists() else None

    def run(self, events: list[dict[str, Any]] | None = None, **kw) -> dict[str, Any]:
        return self.generate(events or [], **kw)
