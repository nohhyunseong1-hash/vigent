"""SafetyManager — 반자동 오케스트레이터(사람 최종승인)

기존 조각(safety_brain·safety_rag·data_engine)을 '호출만' 해서 얇게 얹는 가산식 계층.
코어 로직(Guard/Analyst/Scribe/Dispatcher/safety_brain)은 수정하지 않는다.

핵심 원칙 — 무엇도 자동 실행하지 않는다:
  decide() 는 등급별 '권장 행동'만 반환하고, 각 항목에 requires_approval=True 를 단다.
  위험성평가 생성·알림 발송·정지신호는 전부 '권장'일 뿐 실제 실행 연결은 스텁(사람 승인 뒤 별도).

⚠ 기능안전 경계(§8): 프레스·전단기 등 장비 정지의 1차 책임은 인증 하드웨어
  (Type 4 광전자식 방호장치·안전 PLC)에 있다. VIGENT의 '정지신호'는 보조·감시 신호 권장일 뿐,
  인증 안전기능을 대체하지 않는다.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent


class SafetyManagerAgent(BaseAgent):
    name = "SafetyManager"
    role = "반자동 오케스트레이션: 등급 판정 → 권장 행동(사람 최종승인)"

    # 위험도 표준화 맵(다양한 입력 → high/mid/low)
    _RISK_MAP = {
        "high": "high", "critical": "high", "높음": "high", "위험": "high",
        "mid": "mid", "medium": "mid", "중간": "mid",
        "low": "low", "낮음": "low", "정보": "low",
    }
    _RISK_LABEL = {"high": "높음", "mid": "중간", "low": "낮음", "unknown": "판정불가"}
    # RAG 관련성 최소 점수 — 무관 질문에 저점수 매치를 근거로 삼지 않기 위한 컷.
    #   실측(safety_rag): 관련 질문 0.72+, 무관 질문 0.45↓ → 그 사이 0.5 를 임계로.
    _RAG_MIN_SCORE = 0.5

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True, "mode": "semi_auto"}

    # ── 등급 판정(기존 safety_brain 재사용, 폴백 안전) ──
    def _norm_risk(self, v: Any) -> str:
        return self._RISK_MAP.get(str(v or "").strip().lower(), self._RISK_MAP.get(str(v or "").strip(), "unknown"))

    def _grade(self, event: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """event → (표준 위험도, 근거 assessment|None). 지식 조회는 전부 safety_brain 호출."""
        act = event.get("activity") or event.get("activity_key")
        pc = event.get("present_classes") or event.get("classes")
        try:
            import safety_brain as sb
            if act:
                a = sb.assess(act, pc)
                if a.get("ok"):
                    return self._norm_risk(a.get("risk")), a
            if pc:
                a = (sb.assess_context(pc) or {}).get("assessment")
                if a and a.get("ok"):
                    return self._norm_risk(a.get("risk")), a
        except Exception:  # noqa: BLE001  지식 조회 실패해도 죽지 않는다(폴백)
            pass
        # 직접 위험도가 온 경우(감지 신호 등)
        direct = event.get("risk") or event.get("severity") or event.get("grade")
        if direct:
            return self._norm_risk(direct), None
        return "unknown", None

    def _recommend(self, risk: str) -> list[dict[str, Any]]:
        """등급별 '권장 행동'(전부 requires_approval=True, 실행은 스텁)."""
        REC = {
            "low": [
                {"action": "이벤트 기록 권장", "detail": "데이터엔진에 기록만 남기기",
                 "executor_stub": "data_engine.record", "requires_approval": True},
            ],
            "mid": [
                {"action": "관리자 알림 권장", "detail": "텔레그램/이메일 통보",
                 "executor_stub": "Dispatcher.notify", "requires_approval": True},
                {"action": "증거사진 저장 권장", "detail": "감지 프레임 증거 보존",
                 "executor_stub": "data_engine.save_evidence", "requires_approval": True},
            ],
            "high": [
                {"action": "관리자 알림 권장", "detail": "즉시 통보(고위험)",
                 "executor_stub": "Dispatcher.notify", "requires_approval": True},
                {"action": "위험성평가 초안 생성 권장", "detail": "KOSHA 서식 초안(증거·법령 포함)",
                 "executor_stub": "Scribe.risk_assessment", "requires_approval": True},
                # ⚠ 기능안전 경계: '정지신호'는 보조 신호 권장일 뿐. 1차 책임은 인증HW(Type4 광전자식·안전PLC).
                {"action": "장비 정지신호 권장(보조)", "detail": "인증 안전HW가 1차 — 이는 보조 신호일 뿐",
                 "executor_stub": "Dispatcher.relay(safety_relay_signal)", "requires_approval": True},
            ],
            "unknown": [
                {"action": "사람 확인 필요", "detail": "등급 판정 근거 부족 — 안전관리자 직접 점검",
                 "executor_stub": None, "requires_approval": True},
            ],
        }
        return REC.get(risk, REC["unknown"])

    def decide(self, event: dict[str, Any] | None = None) -> dict[str, Any]:
        """event(감지/작업) → 등급 판정 → '권장 행동'만 반환. 무엇도 자동 실행하지 않는다."""
        event = event or {}
        risk, basis = self._grade(event)
        return {
            "agent": self.name,
            "mode": "semi_auto",
            "risk": risk,
            "risk_label": self._RISK_LABEL.get(risk, risk),
            "summary": (basis or {}).get("summary") or event.get("summary", ""),
            "recommendations": self._recommend(risk),
            "requires_approval": True,      # 반자동 — 전부 사람 승인 필요
            "auto_executed": False,         # 아무것도 실행하지 않음(스텁)
            "assessment": basis,            # 재사용된 safety_brain 결과(있으면 근거로 첨부)
            "safety_boundary": ("장비 정지는 '신호' 권장만 — 1차 책임은 인증 안전HW"
                                "(Type 4 광전자식 방호장치·안전 PLC). VIGENT는 보조·감시 계층."),
            "disclaimer": "권장만 제공 — 실제 실행(서류 생성·알림·정지신호)은 안전관리자 승인 후에만.",
        }

    # ── 질의응답(로컬 지식 우선, 근거 없으면 '확인 필요') ──
    def ask(self, question: str) -> dict[str, Any]:
        """기존 safety_brain 지식 + 최근 이벤트로 텍스트 답변. 지어내지 않는다."""
        q = (question or "").strip()
        if not q:
            return {"agent": self.name, "answer": "질문이 비어 있습니다(확인 필요).",
                    "grounded": False, "requires_approval": False}
        refs: list[dict[str, Any]] = []
        acts: list[dict[str, Any]] = []
        recent = 0
        try:
            import safety_rag
            refs = safety_rag.retrieve(q, k=3) or []
            # 무관 질문의 저점수 매치를 근거로 쓰지 않는다(지어내지 않음 원칙)
            refs = [r for r in refs if r.get("score", 0) >= self._RAG_MIN_SCORE]
        except Exception:  # noqa: BLE001
            refs = []
        try:
            import safety_brain as sb
            words = [w for w in q.replace(",", " ").split() if len(w) >= 2]
            for a in sb.list_activities():
                hay = f"{a.get('name', '')}{a.get('id', '')}"
                if any(w in hay for w in words):
                    acts.append(a)
        except Exception:  # noqa: BLE001
            acts = []
        try:
            import data_engine
            recent = len(data_engine.list_events(limit=5, hours=24) or [])
        except Exception:  # noqa: BLE001
            recent = 0

        # 근거가 전혀 없으면 지어내지 말고 '확인 필요'
        if not refs and not acts:
            return {"agent": self.name,
                    "answer": "관련 근거를 찾지 못했습니다. 안전관리자에게 확인이 필요합니다(확인 필요).",
                    "grounded": False, "sources": [], "recent_events": recent,
                    "requires_approval": False}

        lines: list[str] = []
        if acts:
            try:
                import safety_brain as sb
                a = sb.get_activity(acts[0]["id"]) or acts[0]
            except Exception:  # noqa: BLE001
                a = acts[0]
            ms = [m.get("name", "") for m in a.get("required_measures", [])][:6]
            if ms:
                lines.append(f"[{a.get('name')}] 필수 안전조치: " + ", ".join(ms))
            regs = a.get("regulations", [])[:3]
            if regs:
                def _reg_str(r: Any) -> str:  # 법령 항목이 문자열/딕셔너리 어느 쪽이든 안전 문자열화
                    if isinstance(r, str):
                        return r
                    if isinstance(r, dict):
                        return str(r.get("article") or r.get("title") or r.get("name") or r.get("law") or r)
                    return str(r)
                lines.append("관련 법령: " + ", ".join(_reg_str(r) for r in regs))
        for r in refs[:3]:
            lines.append(f"· {r.get('title')} ({r.get('source')})")
        return {"agent": self.name,
                "answer": "\n".join(lines) if lines else "확인 필요.",
                "grounded": True,
                "sources": [{"title": r.get("title"), "source": r.get("source")} for r in refs[:3]],
                "recent_events": recent,
                "requires_approval": False,
                "disclaimer": "로컬 지식 기반 초안 — 최종 판단은 안전관리자."}
