"""rig_monitor.py — 줄걸이(크레인 인양) 작업 절차 기반 실시간 경보 상태기계 (RIG v2).

★ 설계 확정본(크레인 강사·현장 원칙 반영). 기존 incident.py 의 '프레임별 위험점수 타임라인'
   (사후 분석)과는 다른, **실시간 경보 판정 로직**이다.

관심사 분리(코어 무수정·구독 방식):
  - guard/detect_frame·존·추적은 호출자가 계산해 프레임별 '관측(obs)' dict 로 주입한다.
  - 이 모듈은 순수 상태기계 — 탐지 라이브러리를 import 하지 않는다(테스트 용이·코어 영향 0).

상태:  IDLE → WORKING → LIFT_CHECK → CLEAR → HOISTING  (정상 절차)
  - WORKING    : 작업자가 하물/후크 반경 내(결속 중)
  - LIFT_CHECK : 미동권상(지면 10~20cm 소폭 상승). ★ 이 단계 근접은 '정상 절차'—경보 아님
  - CLEAR      : 작업자 반경 밖 이탈 확인 → '본인양 가능'
  - HOISTING   : 본 인양
예외 전이 → ALARM:
  (a) LIFT_CHECK 에서 작업자 미이탈 상태로 하물이 임계높이(기본 0.30m, 설정 외부화) 초과 상승 ← 핵심 사고
  (b) 반경 내 낙상·급격한 자세 이상
  (c) HOISTING 중 신규 인물 반경 진입
출력 2단계(경보 피로 방지): WORKING/LIFT_CHECK=상태인지(황색·저강도) / ALARM=경보(적색·연속).

⚠ 기능안전 경계: 비전 ML 은 확률적 — 인증 안전기능(안전 PLC·방호장치)을 대체하지 않는 보조·감시 계층.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── 상태 상수 ──
IDLE = "IDLE"
WORKING = "WORKING"
LIFT_CHECK = "LIFT_CHECK"
CLEAR = "CLEAR"
HOISTING = "HOISTING"
ALARM = "ALARM"

# 출력 강도(2단계 + 보조): 경보 피로 방지 — 상태인지와 경보를 분리
LEVEL = {
    IDLE: "NORMAL", WORKING: "ACK", LIFT_CHECK: "ACK",
    CLEAR: "INFO", HOISTING: "INFO", ALARM: "ALARM",
}


@dataclass
class RigConfig:
    """설정 외부화 — 임계높이 등 현장별 조정값."""
    lift_check_low_m: float = 0.10      # 미동권상 하한(10cm)
    lift_check_high_m: float = 0.20     # 미동권상 상한(20cm)
    alarm_height_m: float = 0.30        # ★ (a) 임계높이 — 미이탈+이 높이 초과 = 경보
    ground_eps_m: float = 0.05          # 지면(하물 내려놓음) 판정 여유
    hold_s: float = 0.5                 # 일반 전이 히스테리시스(후보가 N초 유지돼야 확정)
    alarm_confirm_s: float = 0.2        # 경보 확정 유지(과민 방지, 짧게 — 안전상 빠르게)
    clear_confirm_s: float = 0.6        # 작업자 '이탈 확인' 유지(반짝 이탈 오인 방지)


@dataclass
class RigStateMachine:
    """프레임별 obs 를 받아 상태를 전이시키는 순수 상태기계.

    obs(관측) 스키마 — 호출자가 채운다:
      t            : float  타임스탬프(초)
      n_in         : int    하물/후크 반경 내 사람 수
      ids_in       : set    반경 내 사람 track id 집합(신규 진입 (c) 판정용)
      load_h       : float|None  하물 하단 높이(m, 지면 기준). 추적 불가면 None → (a)·권상 전이 보류
      fall         : bool    반경 내 낙상/급격한 자세이상 여부(기본 False)
    """
    cfg: RigConfig = field(default_factory=RigConfig)
    state: str = IDLE
    t: float = 0.0
    alarm_reason: str | None = None
    log: list = field(default_factory=list)          # 전이 로그 [(t, from, to, reason)]

    # 내부 히스테리시스/사이클 상태
    _cand: str | None = None
    _cand_reason: str | None = None
    _cand_since: float = 0.0
    _cycle_ids: set = field(default_factory=set)     # 이번 작업 사이클에 반경서 본 id(누적)
    _hoist_ids: set = field(default_factory=set)     # HOISTING 진입 시점의 반경 내 id(기준선)

    # ── 관측 → '희망 상태' 계산(히스테리시스 전, 순간값 기준) ──
    def _desired(self, o: dict) -> tuple[str, str | None]:
        st = self.state
        n_in = int(o.get("n_in", 0))
        load_h = o.get("load_h", None)
        fall = bool(o.get("fall", False))
        ids_in = set(o.get("ids_in") or [])
        cfg = self.cfg

        # ── 예외(ALARM) 우선 판정 ──
        # (b) 반경 내 낙상 — 활성 작업 상태 어디서든
        if fall and st in (WORKING, LIFT_CHECK, CLEAR, HOISTING):
            return ALARM, "(b) 반경 내 낙상·자세이상"
        # (a) LIFT_CHECK 미이탈 + 임계높이 초과 ← 핵심 사고 시나리오
        if st == LIFT_CHECK and n_in >= 1 and load_h is not None and load_h > cfg.alarm_height_m:
            return ALARM, f"(a) 미이탈({n_in}명) 상태 하물 {load_h:.2f}m>{cfg.alarm_height_m:.2f}m 초과 상승"
        # (c) HOISTING 중 신규 인물 반경 진입(진입 기준선 대비)
        if st == HOISTING and (ids_in - self._hoist_ids):
            newp = sorted(ids_in - self._hoist_ids)
            return ALARM, f"(c) 인양 중 신규 진입 id={newp}"

        # ── 정상 절차 전이 ──
        near_ground = (load_h is not None and load_h <= cfg.ground_eps_m)
        if st == IDLE:
            if n_in >= 1:
                return WORKING, None
        elif st == WORKING:
            if load_h is not None and cfg.lift_check_low_m <= load_h <= cfg.lift_check_high_m:
                return LIFT_CHECK, None
            if n_in == 0 and (load_h is None or near_ground):
                return IDLE, None
        elif st == LIFT_CHECK:
            if n_in == 0:
                return CLEAR, None            # 이탈 확인 → 본인양 가능
            if load_h is not None and load_h <= cfg.ground_eps_m:
                return WORKING, None          # 다시 내려놓음
        elif st == CLEAR:
            if load_h is not None and load_h > cfg.lift_check_high_m:
                return HOISTING, None         # 본 인양 시작
            if n_in >= 1:
                return WORKING, None          # 작업자 재진입(재결속)
        elif st == HOISTING:
            if near_ground and n_in == 0:
                return IDLE, None             # 사이클 종료
        elif st == ALARM:
            # 장면이 안전해지면(반경 비고 하물 지면) 복귀
            if n_in == 0 and (load_h is None or near_ground) and not fall:
                return IDLE, None
        return st, self.alarm_reason if st == ALARM else None

    def _hold_needed(self, target: str) -> float:
        if target == ALARM:
            return self.cfg.alarm_confirm_s
        if target in (CLEAR, IDLE):
            return self.cfg.clear_confirm_s
        return self.cfg.hold_s

    def _commit(self, target: str, reason: str | None):
        prev = self.state
        self.state = target
        self.log.append((round(self.t, 3), prev, target, reason))
        if target == WORKING and prev == IDLE:
            self._cycle_ids = set()           # 새 사이클 시작
            self.alarm_reason = None
        if target == HOISTING:
            self._hoist_ids = set(self._last_ids)  # 인양 시작 시점 인원 = 기준선
        if target == ALARM:
            self.alarm_reason = reason
        if target == IDLE:
            self.alarm_reason = None

    def update(self, obs: dict) -> dict:
        """관측 1프레임 처리 → 현재 상태/출력강도/전이여부 반환."""
        self.t = float(obs.get("t", self.t))
        self._last_ids = set(obs.get("ids_in") or [])
        # 사이클 누적 id
        if self.state in (WORKING, LIFT_CHECK, CLEAR, HOISTING):
            self._cycle_ids |= self._last_ids

        target, reason = self._desired(obs)
        changed = False
        if target == self.state:
            self._cand = None                 # 후보 소멸
        else:
            if target == self._cand:
                if self.t - self._cand_since >= self._hold_needed(target):
                    self._commit(target, self._cand_reason)
                    changed = True
                    self._cand = None
            else:
                self._cand = target           # 새 후보 — 유지시간 리셋
                self._cand_reason = reason
                self._cand_since = self.t

        return {
            "t": round(self.t, 3),
            "state": self.state,
            "level": LEVEL.get(self.state, "NORMAL"),
            "changed": changed,
            "alarm": self.state == ALARM,
            "reason": self.alarm_reason if self.state == ALARM else None,
        }
