"""mfa.py — 다중 인증(Multi-Factor Authentication) 모듈

산업 현장(먼지·마스크·보안경)에서 얼굴 단독 인식은 불안정하다. 본 모듈은 여러 인증
요소를 정책으로 결합해, 얼굴이 약해지면 **자동으로 다른 요소를 추가 요구(step-up)** 한다.

요소(factor) 3종 + 확장:
  - face  : 무엇인가(생체) — recognizer 재사용. 마스크/가림이면 '판정불가'.
  - card  : 무엇을 가짐 — 사번/RFID/QR 등 토큰 → 사람 매핑.
  - pin   : 무엇을 앎 — 사람별 PIN(솔트+PBKDF2 해시 저장, 평문 저장 안 함).
  - iris  : (확장 스텁) 근적외선 홍채 — 별도 하드웨어. 기본 비활성.

정책 엔진 원칙(보안 필수):
  1) 기본 거부(fail-safe): 어떤 조합도 충족 못 하면 DENY.
  2) 신원 일치: 얼굴이 A인데 카드가 B면 → 충돌 DENY.
  3) step-up: 일부만 통과하면 부족한 요소를 알려 추가 요구.
  4) 감사추적: 모든 판정을 audit 로 남김.
  5) advisory 경계: 출입 판정용이며, 인식은 보조. 사람 승인/우회 경로를 둔다.

정책 엔진(decide)은 순수 로직이라 단위테스트가 쉽다(실제 카메라/생체 불필요).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from . import config, privacy


# ── 요소 결과 ────────────────────────────────────────────────
@dataclass
class FactorResult:
    name: str                       # face / card / pin / iris
    ok: bool
    subject_id: str | None = None   # 이 요소가 가리키는 사람(식별 요소만)
    confidence: float = 0.0
    reason: str = ""


# ── 정책 ─────────────────────────────────────────────────────
@dataclass
class Policy:
    name: str
    combos: list[list[str]]         # 통과 가능한 요소 조합들(하나라도 모두 충족 시 통과)
    description: str = ""

    def factors_used(self) -> set[str]:
        return {f for c in self.combos for f in c}


# 보안 등급/구역별 기본 정책
DEFAULT_POLICIES: dict[str, Policy] = {
    # 일반: 얼굴 단독 OK, 또는 카드+PIN
    "basic": Policy("보통구역", [["face"], ["card", "pin"]],
                    "저위험. 얼굴 단독 또는 카드+PIN."),
    # 고분진: 얼굴 단독 불가(마스크 위험) → 카드+얼굴확인, 또는 카드+PIN
    "dusty": Policy("고분진구역", [["card", "face"], ["card", "pin"]],
                    "마스크·고글 환경. 2요소 필수. 얼굴 약하면 PIN으로 대체."),
    # 고보안: 3요소(카드+얼굴+PIN)
    "high": Policy("고보안구역", [["card", "face", "pin"]],
                   "최고보안. 카드+얼굴+PIN 모두."),
    # 최고보안(홍채): 홍채+카드, 또는 홍채+PIN. 쌍둥이·노화·마스크에 강함.
    "vault": Policy("최고보안구역", [["iris", "card"], ["iris", "pin"]],
                    "NIR 홍채 기반. 홍채+카드 또는 홍채+PIN. (홍채 하드웨어 필요)"),
}


# ── 결정 ─────────────────────────────────────────────────────
@dataclass
class AuthDecision:
    decision: str                   # GRANT / DENY / STEP_UP
    subject_id: str | None
    policy: str
    satisfied: list[str] = field(default_factory=list)   # 통과한 요소
    needed: list[str] = field(default_factory=list)      # step-up 시 추가로 필요한 요소
    reasons: list[str] = field(default_factory=list)
    factors: list[dict] = field(default_factory=list)    # 각 요소 결과(감사용)

    @property
    def granted(self) -> bool:
        return self.decision == "GRANT"


class PolicyEngine:
    """정책 + 요소결과 → 출입 결정. 기본 거부(fail-safe)."""

    def decide(self, policy: Policy, results: dict[str, FactorResult]) -> AuthDecision:
        ok = {n for n, r in results.items() if r.ok}
        # 식별 요소(사람을 지목하는 것)들의 신원
        ids = {n: r.subject_id for n, r in results.items()
               if r.ok and r.subject_id is not None}
        distinct = set(ids.values())

        base = dict(policy=policy.name,
                    factors=[r.__dict__ for r in results.values()])

        # 2) 신원 충돌 → 거부
        if len(distinct) > 1:
            return AuthDecision("DENY", None, satisfied=sorted(ok),
                                reasons=[f"신원 충돌: {ids}"], **base)
        subject = next(iter(distinct)) if distinct else None

        # 1) 충족된 조합?
        satisfied = [c for c in policy.combos if set(c) <= ok]
        if satisfied:
            best = max(satisfied, key=len)
            if subject is None:
                # 조합은 찼지만 신원 미확정(식별 요소 없음) → 안전상 거부
                return AuthDecision("DENY", None, satisfied=sorted(ok),
                                    reasons=["신원 확정 불가(식별 요소 없음)"], **base)
            return AuthDecision("GRANT", subject, satisfied=sorted(best),
                                reasons=[f"{policy.name}: {'+'.join(best)} 충족"], **base)

        # 3) 일부 통과 → step-up(가장 적게 부족한 조합 안내)
        gaps = [(set(c) - ok) for c in policy.combos]
        gaps = [g for g in gaps if g]                # 빈 건 위에서 처리됨
        if ok and gaps:
            need = min(gaps, key=len)
            return AuthDecision("STEP_UP", subject, satisfied=sorted(ok),
                                needed=sorted(need),
                                reasons=[f"추가 인증 필요: {', '.join(sorted(need))}"], **base)

        # 그 외 → 거부
        return AuthDecision("DENY", None, satisfied=sorted(ok),
                            reasons=["인증 요소 부족"], **base)


# ── 요소 저장소 ──────────────────────────────────────────────
def _chmod600(p):
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


class CardStore:
    """카드/사번/RFID 토큰 → 사람 매핑."""

    PATH = config.DATA_DIR / "mfa_cards.json"

    def __init__(self):
        self._m: dict[str, str] = {}
        if self.PATH.exists():
            self._m = json.loads(self.PATH.read_text(encoding="utf-8"))

    def _save(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.PATH.write_text(json.dumps(self._m, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        _chmod600(self.PATH)

    def register(self, card_id: str, person_id: str):
        self._m[card_id] = person_id
        self._save()
        privacy.audit("mfa_card_register", card=card_id, person_id=person_id)

    def resolve(self, card_id: str) -> str | None:
        return self._m.get(card_id)


class PinStore:
    """사람별 PIN — 솔트+PBKDF2 해시 저장(평문 저장 안 함)."""

    PATH = config.DATA_DIR / "mfa_pins.json"

    def __init__(self):
        self._m: dict[str, dict] = {}
        if self.PATH.exists():
            self._m = json.loads(self.PATH.read_text(encoding="utf-8"))

    def _save(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.PATH.write_text(json.dumps(self._m, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        _chmod600(self.PATH)

    @staticmethod
    def _hash(pin: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000).hex()

    def set_pin(self, person_id: str, pin: str):
        salt = os.urandom(8)
        self._m[person_id] = {"salt": salt.hex(), "hash": self._hash(pin, salt)}
        self._save()
        privacy.audit("mfa_pin_set", person_id=person_id)

    def verify(self, person_id: str, pin: str) -> bool:
        rec = self._m.get(person_id)
        if not rec:
            return False
        return self._hash(pin, bytes.fromhex(rec["salt"])) == rec["hash"]


# ── 요소 체크 ────────────────────────────────────────────────
class CardFactor:
    def __init__(self, store: CardStore | None = None):
        self.store = store or CardStore()

    def check(self, card_id: str | None) -> FactorResult:
        if not card_id:
            return FactorResult("card", False, reason="카드 미제시")
        pid = self.store.resolve(card_id)
        if pid is None:
            return FactorResult("card", False, reason="미등록 카드")
        return FactorResult("card", True, subject_id=pid, confidence=1.0,
                            reason="카드 확인")


class PinFactor:
    def __init__(self, store: PinStore | None = None):
        self.store = store or PinStore()

    def check(self, subject_id: str | None, pin: str | None) -> FactorResult:
        if subject_id is None:
            return FactorResult("pin", False, reason="신원 먼저 제시(카드/얼굴)")
        if not pin:
            return FactorResult("pin", False, reason="PIN 미입력")
        if self.store.verify(subject_id, pin):
            return FactorResult("pin", True, subject_id=subject_id, confidence=1.0,
                                reason="PIN 일치")
        return FactorResult("pin", False, subject_id=subject_id, reason="PIN 불일치")


class FaceFactor:
    """recognizer 재사용. 마스크/가림이면 '판정불가'(거부 아님 → step-up 유도)."""

    def check(self, frames) -> FactorResult:
        from .recognizer import identify_fused
        try:
            m = identify_fused(frames if isinstance(frames, list) else [frames])
        except Exception as e:
            return FactorResult("face", False, reason=f"얼굴 처리 오류: {e}")
        if m is None:
            return FactorResult("face", False, reason="얼굴 판정불가(가림/품질)")
        if m.person_id is None:
            return FactorResult("face", False, confidence=m.similarity,
                                reason="등록되지 않은 얼굴")
        return FactorResult("face", True, subject_id=m.person_id,
                            confidence=m.similarity, reason="얼굴 일치")


class IrisFactor:
    """근적외선 홍채. iris.IrisRecognizer 사용. 하드웨어 미연결/비활성이면 판정불가."""

    def __init__(self, recognizer=None):
        self._rec = recognizer

    def check(self, iris_capture) -> FactorResult:
        if iris_capture is None:
            return FactorResult("iris", False, reason="홍채 미제시")
        from .iris import IrisRecognizer
        rec = self._rec or IrisRecognizer()
        try:
            pid, hd, reason = rec.identify(iris_capture)
        except Exception as e:
            return FactorResult("iris", False, reason=f"홍채 처리 오류: {e}")
        if pid is None:
            return FactorResult("iris", False, confidence=1.0 - hd, reason=reason)
        return FactorResult("iris", True, subject_id=pid, confidence=1.0 - hd,
                            reason=f"{reason}(HD {hd:.3f})")


# ── 오케스트레이션 ───────────────────────────────────────────
class Authenticator:
    """요소를 실행하고 정책으로 판정하는 상위 진입점."""

    def __init__(self, policy: Policy | str = "dusty"):
        self.policy = DEFAULT_POLICIES[policy] if isinstance(policy, str) else policy
        self.card = CardFactor()
        self.pin = PinFactor()
        self.face = FaceFactor()
        self.iris = IrisFactor()
        self.engine = PolicyEngine()

    def authenticate(self, *, face_frames=None, card_id=None, pin=None,
                     iris=None, audit: bool = True) -> AuthDecision:
        results: dict[str, FactorResult] = {}
        # 식별 요소(카드/홍채/얼굴) 먼저 → 신원 확정 후 PIN 검증
        if card_id is not None:
            results["card"] = self.card.check(card_id)
        if iris is not None:
            results["iris"] = self.iris.check(iris)
        if face_frames is not None:
            results["face"] = self.face.check(face_frames)

        subject = None
        for n in ("card", "iris", "face"):
            r = results.get(n)
            if r and r.ok and r.subject_id:
                subject = r.subject_id
                break
        if pin is not None:
            results["pin"] = self.pin.check(subject, pin)

        decision = self.engine.decide(self.policy, results)
        if audit:
            privacy.audit("mfa_decide", policy=self.policy.name,
                          decision=decision.decision, subject=decision.subject_id,
                          satisfied=decision.satisfied, needed=decision.needed)
        return decision
