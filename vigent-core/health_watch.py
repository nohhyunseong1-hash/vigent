"""health_watch.py — 감시 중단 **원격 통보**. [OPEN_ISSUES_20261008 #5 · ALGORITHM_TRUTH §7-3 #2]

★왜: 2026-09-26 grep 기준 health 전이·슬롯 사망·카메라 stale 를 사람에게 알리는 코드가 0건이었다. /health 는 503 을 주지만
   그것을 **보는 주체가 현장에 없다** — 20일간 213건 미전달(F-35)과 같은 "조용한 중단" 이 검출 쪽에서도 가능했다.

설계(승인 2026-10-08, 5줄):
  1 이벤트: 배경 스레드가 interval(기본 30 s)마다 /health 와 같은 계산(`health_status.build`)을 돌려
     ① 전체 상태 전이(healthy→degraded/unhealthy, →healthy 복구) ② 카메라별 stale_detect/stale_frame 진입·복구
     ③ 슬롯 DEGRADED 진입·복구 를 본다. 예열 중(`readiness.is_ready()` 전)·기동 후 startup_grace 동안은 판정하지 않는다.
  2 채널: 기존 `alert_notify.submit(cam="system", rule=…, edge=True)` → dispatcher 원격 채널(텔레그램·이메일·웹훅).
     level 은 **high** 까지만 — critical 은 dispatch.on_severity 가 safety_relay_signal(사이렌)을 울린다(§8 경계). 건강 통보가 사이렌을 울리면 안 된다.
  3 억제: 전이 때만 1건. 같은 판정이 confirm(기본 2)회 연속(≥ interval×2) 유지돼야 발화(깜빡임 억제).
     같은 키·같은 상태는 cooldown(기본 1800 s) 안에 재통보 없음. 복구도 1건(같은 규칙).
  4 노출: /health notify.health_watch = {enabled, last_state, last_transition_at, notified, suppressed, last_error}.
  5 테스트: tests/test_health_watch.py — 전이·confirm·cooldown·복구·예열 중 무시·stop.
tuning 키(없으면 코드 기본): health.watch_interval_s 30 · health.watch_confirm 2 · health.watch_cooldown_s 1800 · health.watch_enabled true
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

import tuning
import vlog

_LOG = vlog.get("vigent.health_watch")

BAD_CAM = ("stale_detect", "stale_frame")
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None
_watcher: "Watcher | None" = None
_status: dict[str, Any] = {"enabled": False, "last_state": None, "last_transition_at": None, "notified": 0, "suppressed": 0,
                           "last_error": None, "last_check_at": None}


def _cfg(key: str, default: float) -> float:
    try:
        return float(tuning.val("health", key, default))
    except Exception:  # noqa: BLE001
        return float(default)


def enabled() -> bool:
    try:
        v = tuning.val("health", "watch_enabled", True)
        return str(v).strip().lower() not in ("0", "false", "no", "off")
    except Exception:  # noqa: BLE001
        return True


# ── 순수 판정기(테스트가 시각을 주입한다) ────────────────────────────────────────────────
class Watcher:
    """키별(overall / camera:<cid> / slot:<slot>) 상태 전이 판정 + 억제. I/O 없음."""

    def __init__(self, confirm: int = 2, cooldown_s: float = 1800.0) -> None:
        self.confirm = max(1, int(confirm))
        self.cooldown_s = float(cooldown_s)
        self._confirmed: dict[str, str] = {}      # 키 → 확정 상태
        self._cand: dict[str, tuple[str, int]] = {}   # 키 → (후보 상태, 연속 관측 수)
        self._last_notify: dict[tuple[str, str], float] = {}   # (키, 상태) → 시각
        self.suppressed = 0

    @staticmethod
    def _is_bad(key: str, state: str) -> bool:
        if key == "overall":
            return state in ("degraded", "unhealthy")
        if key.startswith("camera:"):
            return state in BAD_CAM
        return state == "degraded"           # slot:<name> → degraded/ok

    def observe(self, snap: dict[str, Any], now: float) -> list[dict[str, Any]]:
        """snap = {"state": overall, "cams": {cid: status}, "slots": {slot: bool degraded}} → 발화할 이벤트 목록."""
        observed: dict[str, str] = {"overall": str(snap.get("state") or "")}
        for cid, st in (snap.get("cams") or {}).items():
            observed[f"camera:{cid}"] = str(st)
        for slot, bad in (snap.get("slots") or {}).items():
            observed[f"slot:{slot}"] = "degraded" if bad else "ok"
        events: list[dict[str, Any]] = []
        for key, state in observed.items():
            cand, n = self._cand.get(key, (None, 0))
            n = n + 1 if cand == state else 1
            self._cand[key] = (state, n)
            if n < self.confirm:
                continue                      # 깜빡임 — 아직 확정 아님
            prev = self._confirmed.get(key)
            if prev == state:
                continue
            first = prev is None
            self._confirmed[key] = state
            if first and not self._is_bad(key, state):
                continue                      # 기동 직후 정상 확정은 통보 없음
            was_bad = prev is not None and self._is_bad(key, prev)
            is_bad = self._is_bad(key, state)
            if not is_bad and not was_bad:
                continue                      # 정상→정상 변형(starting→ok 등)
            last = self._last_notify.get((key, state), -1e18)
            if now - last < self.cooldown_s:
                self.suppressed += 1
                continue
            self._last_notify[(key, state)] = now
            events.append({"key": key, "state": state, "prev": prev, "bad": is_bad, "recovered": (not is_bad) and was_bad})
        # 사라진 카메라(등록 해제)는 잊는다
        for key in [k for k in self._confirmed if k not in observed and k != "overall"]:
            self._confirmed.pop(key, None); self._cand.pop(key, None)
        return events


def rule_and_message(ev: dict[str, Any]) -> tuple[str, str, str]:
    """이벤트 → (rule, level, message). level 은 high 까지(critical 은 사이렌)."""
    key, state, prev = ev["key"], ev["state"], ev.get("prev")
    if key == "overall":
        if ev["recovered"]:
            return "health_recovered", "high", f"[감시 복구] 서버 상태 {prev} → {state}"
        return f"health_{state}", "high", f"[감시 이상] 서버 상태 {prev or '-'} → {state} — /health 확인(카메라·슬롯·경보 큐)"
    if key.startswith("camera:"):
        cid = key.split(":", 1)[1]
        if ev["recovered"]:
            return "camera_recovered", "high", f"[감시 복구] 카메라 {cid} {prev} → {state}"
        why = "프레임이 안 들어옴(카메라·네트워크)" if state == "stale_frame" else "프레임은 오는데 검출이 멈춤"
        return "camera_stale", "high", f"[감시 중단] 카메라 {cid}: {state} — {why}"
    slot = key.split(":", 1)[1]
    if ev["recovered"]:
        return "slot_recovered", "high", f"[감시 복구] 검출 슬롯 {slot} 정상"
    return "slot_degraded", "high", f"[감시 중단] 검출 슬롯 {slot} 저하(연속 추론 실패) — {'사람을 못 보는 상태' if slot == 'person' else '해당 검출 없음'}"


# ── 스냅샷(/health 와 같은 입력) ──────────────────────────────────────────────────────
def snapshot() -> dict[str, Any]:
    import alert_queue
    import health_status
    import worker
    from app_state import DEFAULT_THEME, STATE
    bundle = STATE.get(DEFAULT_THEME)
    slot_degraded: dict = {}; rfdetr_slots: list = []
    if bundle:
        g = bundle["agents"].get("Guard")
        if g is not None:
            try:
                gs = g.status()
                slot_degraded = gs.get("slot_degraded", {}) or {}
                rfdetr_slots = gs.get("rfdetr_slots", []) or []
            except Exception:  # noqa: BLE001
                pass
    try:
        counts = alert_queue.counts()
    except Exception:  # noqa: BLE001
        counts = {}
    disp_status: dict = {}
    try:
        if bundle:
            d = bundle["agents"].get("Dispatcher")
            disp_status = d.status() if d is not None else {}
    except Exception:  # noqa: BLE001
        pass
    problems, _ = health_status.alert_health(counts, disp_status)
    state, cams = health_status.build(worker.manager.status(), bool(bundle) and bool(rfdetr_slots),
                                      int(counts.get("pending", 0) or 0), slot_degraded, problems)
    return {"state": state, "cams": {cid: c["status"] for cid, c in cams.items()}, "slots": {k: bool(v) for k, v in slot_degraded.items()}}


def _ready() -> bool:
    try:
        import readiness
        return bool(readiness.is_ready())
    except Exception:  # noqa: BLE001
        return True


def check_once(now: float | None = None, snap_fn: Callable[[], dict[str, Any]] = snapshot,
               submit: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """한 번 판정하고 발화를 통보한다. 반환 = 발화 이벤트. 예외는 상태에 남기고 삼킨다(감시 스레드는 죽지 않는다)."""
    global _watcher
    now = time.time() if now is None else now
    try:
        snap = snap_fn()
    except Exception as ex:  # noqa: BLE001
        _status["last_error"] = f"{type(ex).__name__}: {ex}"[:200]
        return []
    with _lock:
        if _watcher is None:
            _watcher = Watcher(int(_cfg("watch_confirm", 2)), _cfg("watch_cooldown_s", 1800.0))
        events = _watcher.observe(snap, now)
        _status["last_state"] = snap.get("state"); _status["last_check_at"] = now; _status["suppressed"] = _watcher.suppressed
    if not events:
        return []
    if submit is None:
        import alert_notify
        submit = alert_notify.submit
    for ev in events:
        rule, level, msg = rule_and_message(ev)
        _LOG.warning("health_watch: %s (%s)", msg, rule)
        try:
            r = submit(cam="system", rule=rule, level=level, message=msg,
                       meta={"key": ev["key"], "state": ev["state"], "prev": ev.get("prev"), "source": "health_watch"}, edge=True)
            if (r or {}).get("queued"):
                _status["notified"] = int(_status.get("notified", 0)) + 1
        except Exception as ex:  # noqa: BLE001
            _status["last_error"] = f"submit: {type(ex).__name__}: {ex}"[:200]
        _status["last_transition_at"] = now
    return events


def _loop(interval: float) -> None:
    grace = _cfg("startup_grace_s", 90.0)
    t0 = time.time()
    while not _stop.wait(interval):
        if not _ready() or (time.time() - t0) < grace:
            continue                          # 예열·기동 유예 중엔 판정 안 함(설계 1)
        check_once()


def start() -> None:
    global _thread
    _status["enabled"] = enabled()
    if not _status["enabled"]:
        _LOG.info("health_watch 비활성(health.watch_enabled=false)")
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(_cfg("watch_interval_s", 30.0),), name="vigent-health-watch", daemon=True)
    _thread.start()
    _LOG.info("health_watch 시작 — interval %.0fs · confirm %d · cooldown %.0fs", _cfg("watch_interval_s", 30.0),
              int(_cfg("watch_confirm", 2)), _cfg("watch_cooldown_s", 1800.0))


def stop() -> None:
    global _thread
    _stop.set()
    t = _thread
    if t is not None and t.is_alive() and t is not threading.current_thread():
        t.join(5)
    _thread = None


def status() -> dict[str, Any]:
    return dict(_status)


def reset_for_test() -> None:
    global _watcher
    stop()
    with _lock:
        _watcher = None
    _status.update({"enabled": False, "last_state": None, "last_transition_at": None, "notified": 0, "suppressed": 0,
                    "last_error": None, "last_check_at": None})
