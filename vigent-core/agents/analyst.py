"""Analyst — [판단] 규칙 + 딥러닝 가산 점수·위험등급 산정

핵심 원칙(§2-1, 절대 저하 없음):
  - 점수는 '가산식'. 먼저 규칙(휴리스틱)으로 항상 점수를 낸다.
  - 딥러닝 신호가 들어오면 그 위에 *가산*만 한다.
  - 딥러닝 신호가 없으면(모델 부재/실패) 규칙 점수만으로 동작한다 — 기능은 죽지 않는다.

이 단계(§15-3)에서 safety 의 3대 규칙을 실제로 연결한다:
  - zone_intrusion (위험구역 침입)
  - ppe_missing    (보호구 미착용)
  - guard_bypass   (프레스/전단기 — §8, 참고로 함께 처리)
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent

# severity → 기본 규칙 점수(가산식의 '바닥')
_SEVERITY_WEIGHT = {"critical": 100, "high": 60, "medium": 30, "low": 10}

# 종합 점수 → 위험등급
def _score_to_level(score: float) -> str:
    if score >= 100:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    if score >= 10:
        return "low"
    return "safe"


class AnalystAgent(BaseAgent):
    name = "Analyst"
    role = "판단: 규칙+딥러닝 가산 점수, severity·위반 항목 산정"

    def __init__(self, config: Any):
        super().__init__(config)
        # vision.yaml 의 judgment.rules 에서 규칙별 severity 를 읽어둔다(설정 주도).
        self.rule_severity: dict[str, str] = {}
        for rule in (config.raw.get("judgment", {}) or {}).get("rules", []) or []:
            rid = rule.get("id")
            if rid:
                self.rule_severity[rid] = rule.get("severity", "low")
        # dispatch.on_severity: 등급별로 보낼 신호(설정 주도, office·sports 도 재사용)
        self.dispatch_map: dict[str, Any] = \
            (config.raw.get("dispatch", {}) or {}).get("on_severity", {}) or {}

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "rules": self.rule_severity}

    def _weight(self, rule_id: str) -> int:
        return _SEVERITY_WEIGHT.get(self.rule_severity.get(rule_id, "low"), 10)

    def judge(self, signals: dict[str, Any], dl: dict[str, float] | None = None) -> dict[str, Any]:
        """규칙+딥러닝 가산 판단.

        signals: 프론트/Guard 가 보내는 관측값
          - zone_intrusion: bool        (사람 발/중심이 위험구역 폴리곤 안)
          - ppe_missing: bool           (NO-Hardhat or NO-Safety-Vest)
          - hand_in_machine_zone: bool  (프레스/전단기 위험구역에 손)
        dl: 딥러닝 신호(있으면 가산). 예: {"ppe_conf":0.82}
            None 이면 휴리스틱 폴백(규칙 점수만).
        """
        dl = dl or {}
        used_dl = False
        fired: list[dict[str, Any]] = []
        score = 0.0

        def fire(rule_id: str, base: int, dl_key: str | None = None) -> None:
            nonlocal score, used_dl
            gain = base
            via = "rule"
            if dl_key and dl_key in dl:
                # 딥러닝 신호 가산: 신뢰도에 비례해 최대 +50% 보너스
                bonus = base * 0.5 * float(dl[dl_key])
                gain += bonus
                via = "rule+dl"
                used_dl = True
            score += gain
            fired.append({
                "rule": rule_id,
                "severity": self.rule_severity.get(rule_id, "low"),
                "gain": round(gain, 1),
                "via": via,
            })

        # ── 규칙 평가(휴리스틱은 항상, 딥러닝은 있으면 가산) ──
        if signals.get("zone_intrusion"):
            fire("zone_intrusion", self._weight("zone_intrusion"), dl_key="zone_conf")

        if signals.get("ppe_missing"):
            fire("ppe_missing", self._weight("ppe_missing"), dl_key="ppe_conf")

        if signals.get("hand_in_machine_zone"):
            fire("guard_bypass", self._weight("guard_bypass"), dl_key="bypass_conf")

        level = _score_to_level(score)
        return {
            "score": round(score, 1),
            "level": level,
            "fired": fired,
            "used_dl": used_dl,                 # 딥러닝이 실제로 가산됐는가
            "fallback": (not used_dl),          # 폴백(규칙만)으로 동작했는가
        }

    # ── 종합 통합(3단계): 규칙 + VLM + 법령을 한자리에서 ────────────────
    _VLM_LEVEL = {"높음": "high", "중간": "medium", "낮음": "low"}

    def integrate(self, signals: dict[str, Any], vlm: dict[str, Any] | None = None,
                  dl: dict[str, float] | None = None, copilot: Any = None) -> dict[str, Any]:
        """규칙(judge) + VLM 위험분석 + Copilot 법령을 가산식으로 종합한 '최종 판단'.

        - 규칙 점수(휴리스틱+딥러닝 가산)는 그대로 바닥을 깐다.
        - VLM 위험등급은 보조 신호로 *가산*만 한다(0.4 가중) — 절대 점수를 낮추지 않는다(규칙 6).
        - 각 발화 규칙에 Copilot 법령 인용을 붙인다(§9 근거 인용).
        - 최종 등급으로 Dispatcher 가 보낼 신호를 권고한다(vision.yaml dispatch).
        """
        verdict = self.judge(signals, dl)

        # VLM 가산(보조). VLM 이 없거나 실패해도 규칙 판단은 그대로(폴백).
        if isinstance(vlm, dict) and not vlm.get("_error"):
            lvl = self._VLM_LEVEL.get(str(vlm.get("위험등급", "")).strip())
            if lvl:
                gain = _SEVERITY_WEIGHT[lvl] * 0.4   # VLM 은 보조라 40% 가중
                verdict["score"] = round(verdict["score"] + gain, 1)
                verdict["level"] = _score_to_level(verdict["score"])
                verdict["fired"].append({"rule": "vlm_risk", "severity": lvl,
                                         "gain": round(gain, 1), "via": "vlm"})
            verdict["vlm"] = {k: vlm.get(k) for k in
                              ("위험요인", "위험등급", "근거", "권고조치", "관련법령")}
            if vlm.get("_citations"):
                verdict["vlm"]["citations"] = vlm["_citations"]

        # 각 규칙에 법령 인용 부착(Copilot 가 있으면). 없으면 생략(저하 없음).
        if copilot is not None:
            for f in verdict["fired"]:
                if f["rule"] == "vlm_risk":
                    continue
                try:
                    f["citations"] = copilot.cite(f["rule"]).get("citations", [])
                except Exception:   # noqa: BLE001
                    pass

        # 최종 등급 → 보낼 신호 권고(Dispatcher 입력)
        verdict["dispatch"] = self.dispatch_map.get(verdict["level"], [])
        return verdict

    # run() 은 judge 의 얇은 래퍼(공통 인터페이스 유지)
    def run(self, signals: dict[str, Any] | None = None,
            dl: dict[str, float] | None = None) -> dict[str, Any]:
        return self.judge(signals or {}, dl)
