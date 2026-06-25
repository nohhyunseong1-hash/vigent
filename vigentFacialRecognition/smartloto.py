"""smartloto.py — 그룹 LOTO 상태머신 + 잠금대장 + 감사

각 기계(LotoStation)마다 여러 작업자가 자기 잠금을 건다(그룹 LOTO). 잠금이 하나라도
있으면 기계는 비활성(서보 LOCKED). 모두 풀려야 기동 가능하다.

핵심 안전 규칙:
  - 잠금 1개라도 있으면 기계 비활성(페일세이프).
  - 본인 잠금은 본인만 해제(타인 잠금 해제 금지). 관리자 강제해제는 별도 감사.
  - energize 는 잠금 0일 때 명시적 호출로만(자동 기동 금지).

상태: LOCKED_OUT(잠금≥1) / SAFE_IDLE(잠금0·비기동) / ENERGIZED(기동허용).
하드웨어 제어는 LotoController(시리얼/시뮬레이션)에 위임.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import privacy


class LotoError(Exception):
    pass


@dataclass
class Lock:
    person_id: str
    name: str = ""
    applied_at: str = field(default_factory=privacy.now_iso)
    evidence: str | None = None      # 증거사진 경로/해시 등


class LotoStation:
    def __init__(self, machine_id: str, controller):
        self.machine_id = machine_id
        self.controller = controller
        self.locks: dict[str, Lock] = {}
        self.energized = False
        self._sync()                  # 시작은 안전(잠금)

    # ── 상태 ─────────────────────────────────────────────────
    @property
    def state(self) -> str:
        if self.locks:
            return "LOCKED_OUT"
        return "ENERGIZED" if self.energized else "SAFE_IDLE"

    def can_energize(self) -> bool:
        return len(self.locks) == 0

    def _sync(self) -> None:
        """잠금이 있거나 미기동이면 하드웨어 잠금(기계 비활성)."""
        machine_disabled = bool(self.locks) or not self.energized
        self.controller.set_locked(machine_disabled)

    # ── 잠금/해제 ────────────────────────────────────────────
    def apply_lock(self, person_id: str, name: str = "", evidence=None) -> dict:
        if person_id in self.locks:
            raise LotoError(f"{person_id} 이미 잠금 적용됨")
        # 잠금이 걸리면 기동 상태는 즉시 해제(안전)
        self.energized = False
        self.locks[person_id] = Lock(person_id, name, evidence=evidence)
        self._sync()
        privacy.audit("loto_apply", machine=self.machine_id, person_id=person_id,
                      locks=len(self.locks))
        return self.snapshot()

    def remove_lock(self, person_id: str, *, by: str | None = None,
                    supervisor: bool = False) -> dict:
        if person_id not in self.locks:
            raise LotoError(f"{person_id} 잠금 없음")
        # LOTO 핵심: 본인 잠금은 본인만(또는 관리자 강제해제)
        if not supervisor and by is not None and by != person_id:
            raise LotoError("본인 잠금만 해제 가능(타인 잠금 해제 금지)")
        del self.locks[person_id]
        self._sync()
        privacy.audit("loto_remove", machine=self.machine_id, person_id=person_id,
                      by=by or person_id, supervisor=supervisor, locks=len(self.locks))
        return self.snapshot()

    def energize(self, by: str) -> dict:
        if self.locks:
            raise LotoError(f"기동 불가: 잠금 {len(self.locks)}개 남음 → 전원 해제 필요")
        self.energized = True
        self._sync()
        privacy.audit("loto_energize", machine=self.machine_id, by=by)
        return self.snapshot()

    def shutdown(self, by: str) -> dict:
        """기동 중지(안전 대기). 잠금과 무관하게 비활성으로."""
        self.energized = False
        self._sync()
        privacy.audit("loto_shutdown", machine=self.machine_id, by=by)
        return self.snapshot()

    # ── 조회 ─────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "state": self.state,
            "can_energize": self.can_energize(),
            "lock_count": len(self.locks),
            "locks": [{"person_id": l.person_id, "name": l.name,
                       "applied_at": l.applied_at} for l in self.locks.values()],
            "hardware": self.controller.status(),
        }
