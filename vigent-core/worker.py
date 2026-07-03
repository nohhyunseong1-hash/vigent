"""worker.py — 서버사이드 추론 워커(브라우저 없이 서버가 영상을 감시)

카메라 스트림(RTSP/비디오/이미지)에서 프레임을 저fps로 읽어 guard.detect 로 검사하고,
위험(위험구역 침입·보호구 미착용·화재)을 data_engine 에 기록한다 → 자동처리 콘솔에 자동 노출.
다현장의 기본 단위: 카메라 1대 = 워커 1개(이 모듈은 1대용 — N대는 이걸 복제).

설계 원칙(절대 저하 없음):
  - guard 추론은 코어 락으로 직렬화(브라우저 /detect/frame 과 충돌 방지).
  - 같은 위험은 쿨다운(기본 15초)으로 한 번만 기록(스팸 방지).
  - 어떤 예외도 워커 스레드 안에서 잡아 상태에 남기고, 서버 본체는 안 죽는다.
"""
from __future__ import annotations

import base64
import json
import math
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import data_engine
import proximity
import tuning

_ROOT = Path(__file__).resolve().parent.parent
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_COOLDOWN_S = float(tuning.val("detect", "cooldown_s", 15.0))
_FALL_ANGLE = float(tuning.val("fall", "angle_deg", 55))   # 쓰러짐 몸통각 임계


def _point_in_poly(x: float, y: float, poly) -> bool:
    """정규화 좌표(0~1) 점이 폴리곤 내부인지 — ray casting."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _load_zone() -> list[tuple[float, float]]:
    """config/danger_zone.json 의 정규화 폴리곤(없으면 빈 목록)."""
    p = _ROOT / "config" / "danger_zone.json"
    if not p.exists():
        return []
    try:
        z = json.loads(p.read_text(encoding="utf-8"))
        return [(pt["x"], pt["y"]) for pt in z.get("points", [])]
    except (ValueError, OSError, KeyError):
        return []


def _frame_to_dataurl(frame) -> str | None:
    """BGR 프레임 → JPEG data URL(증거 저장용)."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return ("data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()) if ok else None


def _derive(out: dict, zone: list, aspect_hw: float | None = None) -> list[tuple[str, str, str]]:
    """guard.detect 출력 → 발화한 위험 [(rule, level, note)]."""
    fired: list[tuple[str, str, str]] = []
    sig = out.get("signals", {}) or {}
    if zone and len(zone) >= 3:                       # 위험구역 침입(사람 발 위치)
        for d in out.get("detections", []):
            if str(d.get("label", "")).lower() != "person":
                continue
            x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
            if _point_in_poly((x1 + x2) / 2, y2, zone):
                fired.append(("zone_intrusion", "high", "위험구역 내 작업자 감지"))
                break
    if sig.get("ppe_missing"):
        fired.append(("ppe_missing", "high", "보호구 미착용 감지"))
    if sig.get("fire_smoke"):
        fired.append(("fire_smoke", "critical", "화재/연기 감지"))
    # 동적 작업반경(협착) — 지게차·차량 근처에 사람 진입(거리 자동추정)
    import os
    radius = float(tuning.val("proximity", "radius_m", 3.0, env="VIGENT_RADIUS_M"))
    for hz in proximity.detect(out.get("detections", []), radius, aspect_hw=aspect_hw):  # 감사 E-1
        fired.append(("proximity_hazard", "high",
                      f"{hz['vehicle']} 작업반경 침입 — 사람 약 {hz['distance_m']}m"))
        break
    # 군집 밀집 — 인원이 임계 이상 몰림(혼잡·압사·동선 위험)
    pc = out.get("person_count", 0)
    if pc >= int(tuning.val("crowd", "threshold", 6, env="VIGENT_CROWD")):
        fired.append(("crowd_density", "mid", f"인원 밀집 — {pc}명 감지"))
    return fired


def _person_metrics(xy, cf, H, min_kp=0.3):
    """사람 1명의 키포인트 → 자세 지표. None 이면 판단 불가(어깨·엉덩이 미검출)."""
    def gp(idxs):
        pts = [xy[j] for j in idxs if cf[j] >= min_kp]
        return np.mean(pts, axis=0) if pts else None
    sc = gp([5, 6])          # 어깨중심
    hc = gp([11, 12])        # 엉덩이중심
    head = gp([0, 1, 2, 3, 4])  # 머리(코·눈·귀)
    if sc is None or hc is None:
        return None
    angle = math.degrees(math.atan2(abs(hc[0] - sc[0]), abs(hc[1] - sc[1]) + 1e-6))  # 0수직~90수평
    valid = [xy[j] for j in range(len(xy)) if cf[j] >= min_kp]
    xs = [p[0] for p in valid]
    ys = [p[1] for p in valid]
    bw, bh = (max(xs) - min(xs)), (max(ys) - min(ys))
    aspect = bw / (bh + 1e-6)
    head_y = head[1] if head is not None else sc[1]
    head_below_hip = head_y > hc[1]                  # 머리가 엉덩이보다 아래(주저앉음/거꾸로)
    pose_fallen = (angle > _FALL_ANGLE) or (aspect > 1.3) or head_below_hip
    return {"centroid": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
            "ref_y": sc[1] / H, "angle": angle, "aspect": aspect,
            "head_below_hip": head_below_hip, "pose_fallen": pose_fallen}


class _PoseModel:
    """yolov8n-pose 1회 로드(공유). 프레임 → 사람별 자세 지표. 실패 시 [](무중단)."""

    def __init__(self):
        self._m = None
        self._failed = False
        self._device = "cpu"

    def persons(self, frame, min_kp=0.3):
        if self._m is None and not self._failed:
            try:
                from ultralytics import YOLO
                self._m = YOLO(str(_ROOT / "vigent-core" / "weights" / "yolov8n-pose.pt"))
                import sys
                sys.path.insert(0, str(_ROOT / "vigent-core"))
                import device as _device
                self._device = _device.pick_device(prefer_mps=False)  # 감사 C-2: YOLO 맥=CPU/리눅스=CUDA
            except Exception:  # noqa: BLE001
                self._failed = True
        if self._m is None:
            return []
        try:
            H = frame.shape[0]
            res = self._m.predict(frame, verbose=False, conf=0.4, device=self._device)[0]
            kp = getattr(res, "keypoints", None)
            if kp is None or kp.xy is None or len(kp.xy) == 0:
                return []
            xys = kp.xy.cpu().numpy()
            cfs = kp.conf.cpu().numpy() if kp.conf is not None else None
            out = []
            for i in range(len(xys)):
                cf_i = cfs[i] if cfs is not None else np.ones(len(xys[i]))
                m = _person_metrics(xys[i], cf_i, H, min_kp)
                if m:
                    m["kp_xy"] = xys[i]      # 원시 키포인트 가산(근골격계 레이어용). 낙상은 미사용 — 불변.
                    m["kp_cf"] = cf_i
                    out.append(m)
            return out
        except Exception:  # noqa: BLE001
            return []


_posemodel = _PoseModel()


class FallTracker:
    """카메라 1대용 낙상 추적(상태 유지). 낙상을 '모양'이 아니라 '사건'으로 본다:
       ① 다중 단서(몸통각·머리위치·박스비율)로 '쓰러진 자세' 판정
       ② 모션: 머리/어깨가 갑자기 뚝 내려가고(급강하) → 그 뒤 정지
       ③ (선택) VLM 확정 — 애매하면 '쓰러진 거 맞나?' 재판정.
    자세 무관(기댐·걸침·주저앉음)하게 잡으려면 ②급강하가 핵심."""
    DROP = float(tuning.val("fall", "drop", 0.12))   # 급강하: 화면높이 비율(설정)
    MATCH = 0.18         # 사람 프레임간 매칭 거리(대각선 정규화)
    HIST_S = 3.0

    def __init__(self, vlm=False):
        self._tracks = []
        self._vlm = vlm

    def update(self, frame, ts):
        """프레임 처리 → (낙상여부, 사유). 모델/키포인트 없으면 (False,'')."""
        H, W = frame.shape[:2]
        diag = (W * W + H * H) ** 0.5
        persons = _posemodel.persons(frame)
        used = set()
        for p in persons:
            cx, cy = p["centroid"]
            best, bd = None, 1e9
            for k, tr in enumerate(self._tracks):
                if k in used:
                    continue
                d = ((cx - tr["cx"]) ** 2 + (cy - tr["cy"]) ** 2) ** 0.5 / diag
                if d < bd:
                    bd, best = d, k
            if best is not None and bd < self.MATCH:
                tr = self._tracks[best]
                used.add(best)
            else:
                tr = {"hist": []}
                self._tracks.append(tr)
                used.add(len(self._tracks) - 1)
            tr["cx"], tr["cy"] = cx, cy
            tr["hist"].append((ts, p["ref_y"], p["pose_fallen"]))
            tr["hist"] = [h for h in tr["hist"] if ts - h[0] <= self.HIST_S]
        self._tracks = [tr for tr in self._tracks if tr.get("hist") and ts - tr["hist"][-1][0] < 2.0]

        for tr in self._tracks:
            hist = tr["hist"]
            if not hist:
                continue
            cur_ref, pose_fallen = hist[-1][1], hist[-1][2]
            past = [h[1] for h in hist if 0.5 <= ts - h[0] <= 2.0]
            drop = bool(past) and (cur_ref - min(past) > self.DROP) and pose_fallen     # ② 급강하
            recent = [h for h in hist if ts - h[0] <= 2.0]
            allfall = len(recent) >= 3 and all(h[2] for h in recent[-3:])
            still = len(recent) >= 3 and (max(h[1] for h in recent[-3:]) - min(h[1] for h in recent[-3:]) < 0.05)
            static_fall = allfall and still                                            # ① 자세 지속+정지
            if drop or static_fall:
                reason = "급강하 후 쓰러짐" if drop else "쓰러진 자세 지속"
                if self._vlm:                                                          # ③ VLM 확정(옵션)
                    try:
                        import vlm_confirm as _vc
                        v = _vc.confirm(frame, "fall_suspected", reason=reason)
                        if v.get("available") and v.get("suppress"):
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                return True, reason
        return False, ""


class ErgonomicsTracker:
    """근골격계 부담 자세 '지속' 추적(카메라별 상태). 순수 가산 — 낙상·탐지와 독립·불변.

    나쁜 자세(warn/bad)가 hold_sec(설정) 이상 '지속'될 때만 위험으로 본다(순간 자세는 무시 → 오탐 억제).
    포즈 추론 비용 억제: 최소 간격(_MIN_INTERVAL)으로만 평가한다(3초 지속 판정엔 충분). 트랙 id 가
    없으므로 낙상과 동일한 중심점 매칭으로 사람별 상태를 잇는다(독립 트랙 — 낙상 트랙 미공유).
    임계값은 vision.yaml 에서 읽는다(하드코딩 금지). 키포인트 없음/에러 → [] 반환(무중단)."""

    MATCH = 0.18            # 사람 프레임간 매칭 거리(대각선 정규화) — 낙상과 동일
    _MIN_INTERVAL = 0.5    # 평가 최소 간격(초): 저빈도 스로틀로 추가 포즈추론 비용 최소화

    def __init__(self, theme: str = "safety"):
        import ergonomics as _erg
        self._erg = _erg
        cfg = _erg.load_ergonomics(theme)
        self._joints = cfg.get("joints", {}) if isinstance(cfg, dict) else {}
        try:
            self._hold_sec = float(cfg.get("hold_sec", 3)) if isinstance(cfg, dict) else 3.0
        except Exception:  # noqa: BLE001
            self._hold_sec = 3.0
        self._enabled = bool(self._joints)       # 설정 없으면 조용히 비활성(저하 0)
        self._tracks: list[dict] = []
        self._last_ts = 0.0

    def update(self, frame, ts):
        """반환: [(rule, level, note), ...] — hold 지속이 확정된 사람만. 없으면 []."""
        if not self._enabled:
            return []
        if ts - self._last_ts < self._MIN_INTERVAL:      # 저빈도 스로틀
            return []
        self._last_ts = ts
        try:
            persons = _posemodel.persons(frame)
        except Exception:  # noqa: BLE001
            return []
        H, W = frame.shape[0], frame.shape[1]
        diag = (W * W + H * H) ** 0.5
        used: set[int] = set()
        out: list[tuple] = []
        for p in persons:
            xy, cf = p.get("kp_xy"), p.get("kp_cf")
            if xy is None or cf is None:
                continue
            try:
                a = self._erg.assess(xy, cf, self._joints)
            except Exception:  # noqa: BLE001
                continue
            if not a:
                continue
            bad = a.get("worst") in ("warn", "bad")
            cx, cy = p["centroid"]
            best, bd = None, 1e9                          # 중심점 매칭(독립 트랙)
            for k, tr in enumerate(self._tracks):
                if k in used:
                    continue
                d = ((cx - tr["cx"]) ** 2 + (cy - tr["cy"]) ** 2) ** 0.5 / diag
                if d < bd:
                    bd, best = d, k
            if best is not None and bd < self.MATCH:
                tr = self._tracks[best]
                used.add(best)
            else:
                tr = {"bad_since": None, "fired": False}
                self._tracks.append(tr)
                used.add(len(self._tracks) - 1)
            tr["cx"], tr["cy"], tr["ts"] = cx, cy, ts
            if bad:
                if tr.get("bad_since") is None:
                    tr["bad_since"] = ts
                held = ts - tr["bad_since"]
                if held >= self._hold_sec and not tr.get("fired"):   # 지속 확정 시 1회만
                    tr["fired"] = True
                    note = f"{a['note']} · {held:.0f}초 지속"
                    out.append(("ergonomic_risk", a["level"], note))
            else:                                        # 자세 회복 → 상태 리셋
                tr["bad_since"] = None
                tr["fired"] = False
        self._tracks = [tr for tr in self._tracks if ts - tr.get("ts", 0) < 3.0]
        return out


class MotionTracker:
    """사람 움직임 추적 → ① 장시간 무동작(쓰러짐·실신 의심, SOS) ② 급격한 이동(돌진·이상행동).
    낙상(FallTracker)과 보완: 낙상=급강하 순간, 무동작=쓰러진 뒤 오래 안 움직임."""
    MATCH = 0.32            # 사람 매칭 거리(급이동도 같은 사람으로 추적되게 넉넉히)
    IMMOBILE_S = float(tuning.val("motion", "immobile_s", 45.0))   # 무동작 시간(설정)
    IMMOBILE_SPREAD = 0.03  # 이동 범위(정규화) 이하면 정지로 간주
    RAPID_DIST = float(tuning.val("motion", "rapid_dist", 0.15))   # 급이동 거리(설정)
    RAPID_T = 1.0
    HIST_S = 60.0

    def __init__(self):
        self._tracks: list[dict] = []

    def update(self, detections, ts) -> list[tuple[str, str, str]]:
        persons = []
        for d in detections:
            if str(d.get("label", "")).lower() != "person":
                continue
            bb = d.get("bbox", [0, 0, 0, 0])
            persons.append(((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))
        used = set()
        for cx, cy in persons:
            best, bd = None, 1e9
            for k, tr in enumerate(self._tracks):
                if k in used:
                    continue
                dd = ((cx - tr["cx"]) ** 2 + (cy - tr["cy"]) ** 2) ** 0.5
                if dd < bd:
                    bd, best = dd, k
            if best is not None and bd < self.MATCH:
                tr = self._tracks[best]
                used.add(best)
            else:
                tr = {"hist": []}
                self._tracks.append(tr)
                used.add(len(self._tracks) - 1)
            tr["cx"], tr["cy"] = cx, cy
            tr["hist"].append((ts, cx, cy))
            tr["hist"] = [h for h in tr["hist"] if ts - h[0] <= self.HIST_S]
        self._tracks = [tr for tr in self._tracks if tr.get("hist") and ts - tr["hist"][-1][0] < 3.0]
        out: dict[str, tuple[str, str, str]] = {}
        for tr in self._tracks:
            h = tr["hist"]
            rec = [x for x in h if 0 <= ts - x[0] <= self.RAPID_T]
            if len(rec) >= 2:
                dx, dy = rec[-1][1] - rec[0][1], rec[-1][2] - rec[0][2]
                if (dx * dx + dy * dy) ** 0.5 > self.RAPID_DIST:
                    out["rapid_motion"] = ("rapid_motion", "mid", "급격한 이동 감지 — 돌진·이상행동")
            win = [x for x in h if ts - x[0] <= self.IMMOBILE_S]
            if len(win) >= 5 and (ts - h[0][0]) >= self.IMMOBILE_S:   # 트랙이 충분히 오래 + 최근 정지
                xs = [x[1] for x in win]
                ys = [x[2] for x in win]
                if max(max(xs) - min(xs), max(ys) - min(ys)) < self.IMMOBILE_SPREAD:
                    out["immobility"] = ("immobility", "high", "장시간 무동작 — 쓰러짐·실신 의심")
        return list(out.values())


class Worker:
    """1대용 추론 워커(지연 시작·정지·상태). 서버 전역 싱글톤으로 사용."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state: dict[str, Any] = {
            "running": False, "source": "", "name": "", "fps": 0,
            "frames": 0, "events": 0, "last_event": "", "error": ""}

    def start(self, guard, lock, source: str, name: str = "CAM", fps: float = 2.0,
              detectors: list | None = None, zone: list | None = None) -> dict:
        if self.state["running"]:
            return {"ok": False, "error": "이미 실행 중 — 먼저 중지하세요."}
        self._stop.clear()
        self.state.update({"running": True, "source": source, "name": name, "fps": fps,
                           "frames": 0, "events": 0, "last_event": "", "error": ""})
        self._thread = threading.Thread(
            target=self._loop,
            args=(guard, lock, source, name, fps,
                  detectors or ["person", "ppe", "forklift", "fire_smoke"], zone),
            daemon=True)
        self._thread.start()
        return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.state["running"] = False
        return {"ok": True, "status": self.status()}

    def status(self) -> dict:
        return dict(self.state)

    def _loop(self, guard, lock, source, name, fps, detectors, zone=None):
        import os
        interval = 1.0 / max(0.2, fps)
        cooldown: dict[str, float] = {}
        # 데이터 수집 모드(파일럿 학습용) — VIGENT_COLLECT=1 이면 일정 간격으로 프레임 저장
        collect_on = os.environ.get("VIGENT_COLLECT", "0") == "1"
        collect_every = float(os.environ.get("VIGENT_COLLECT_EVERY", "30"))
        dataset_dir = _ROOT / "data" / "dataset" / "images"
        last_collect = 0.0
        ftrack = FallTracker(vlm=getattr(self, "_vlm_fall", False))   # 카메라별 낙상 추적(상태 유지)
        mtrack = MotionTracker()                                       # 무동작·급이동 추적
        etrack = ErgonomicsTracker()                                   # 근골격계 부담자세 지속(가산·낙상 불변)
        zone = [tuple(p) for p in zone] if zone else _load_zone()   # 카메라별 구역 or 전역
        is_image = Path(source).suffix.lower() in _IMG_EXT and Path(source).exists()
        static = cv2.imread(source) if is_image else None
        cap = None
        if not is_image:
            cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
        try:
            while not self._stop.is_set():
                t0 = time.time()
                if is_image:
                    frame = static.copy() if static is not None else None
                else:
                    ok, frame = cap.read()
                    if not ok:                       # 비디오 끝/끊김 → 처음으로(루프)·재시도
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ok, frame = cap.read()
                        if not ok:
                            time.sleep(0.5)
                            continue
                if frame is None:
                    self.state["error"] = "프레임 읽기 실패(소스 확인)"
                    time.sleep(0.5)
                    continue
                self.state["frames"] += 1
                if collect_on and (t0 - last_collect) >= collect_every:   # 학습용 프레임 수집
                    last_collect = t0
                    try:
                        dataset_dir.mkdir(parents=True, exist_ok=True)
                        safe = "".join(c if c.isalnum() else "_" for c in str(name))[:20]
                        cv2.imwrite(str(dataset_dir / f"{safe}_{int(t0)}.jpg"), frame)
                        self.state["collected"] = self.state.get("collected", 0) + 1
                    except Exception:  # noqa: BLE001
                        pass
                with lock:                            # 코어 추론 직렬화(브라우저와 충돌 방지)
                    out = guard.detect(frame, detectors=detectors)
                    fall, freason = ftrack.update(frame, t0)   # 다중단서+모션 낙상
                    try:
                        ergo_fired = etrack.update(frame, t0)  # 근골격계 부담자세(포즈 각도·저빈도)
                    except Exception:  # noqa: BLE001  가산 레이어 — 실패해도 낙상·탐지 무중단
                        ergo_fired = []
                fired = _derive(out, zone, frame.shape[0] / frame.shape[1])
                if fall:
                    fired.append(("fall_suspected", "critical", f"작업자 낙상 의심 — {freason}"))
                fired += mtrack.update(out.get("detections", []), t0)   # 무동작·급이동
                fired += ergo_fired                                     # 근골격계 부담자세(지속 확정분)
                now = time.time()
                for rule, level, note in fired:
                    if now - cooldown.get(rule, 0) < _COOLDOWN_S:
                        continue
                    cooldown[rule] = now
                    data_engine.log_event(rule=rule, level=level, site=name, note=note,
                                          image_data_url=_frame_to_dataurl(frame))
                    self.state["events"] += 1
                    self.state["last_event"] = f"{rule}({level})"
                dt = time.time() - t0
                if dt < interval and not self._stop.is_set():
                    time.sleep(interval - dt)
        except Exception as ex:                       # noqa: BLE001  워커가 죽어도 서버는 산다
            self.state["error"] = f"{type(ex).__name__}: {ex}"
        finally:
            if cap is not None:
                cap.release()
            self.state["running"] = False


# ── 다중 워커 매니저(현장 N대) + 현장설정(site.yaml) 자동시작 ──
def load_site_config() -> dict | None:
    """config/site.yaml(현장 설정) 로드. 없으면 None."""
    p = _ROOT / "config" / "site.yaml"
    if not p.exists():
        return None
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None


class WorkerManager:
    """카메라 N대 워커를 등록·관리(다현장 엔진). 카메라 1대 = Worker 1개."""

    def __init__(self):
        self._workers: dict[str, Worker] = {}
        self._reg_lock = threading.Lock()
        self.site = ""

    def start(self, guard, infer_lock, cam_id: str, source: str, name: str = "",
              fps: float = 2.0, zone: list | None = None, detectors: list | None = None) -> dict:
        with self._reg_lock:
            cur = self._workers.get(cam_id)
            if cur and cur.state["running"]:
                return {"ok": False, "error": f"{cam_id} 이미 실행 중"}
            w = Worker()
            self._workers[cam_id] = w
        return w.start(guard, infer_lock, source, name=name or cam_id, fps=fps,
                       detectors=detectors, zone=zone)

    def stop(self, cam_id: str) -> dict:
        w = self._workers.get(cam_id)
        if not w:
            return {"ok": False, "error": f"{cam_id} 없음"}
        return w.stop()

    def stop_all(self) -> dict:
        for w in list(self._workers.values()):
            w.stop()
        return {"ok": True, "stopped": len(self._workers)}

    def status(self) -> dict:
        return {"site": self.site,
                "cameras": {cid: w.status() for cid, w in self._workers.items()}}

    def autostart(self, guard, infer_lock) -> dict:
        """site.yaml 의 카메라들로 워커 일괄 시작(헤드리스 — USB/엣지 부팅 시)."""
        cfg = load_site_config()
        if not cfg:
            return {"ok": False, "error": "config/site.yaml 없음", "started": []}
        self.site = str(cfg.get("site", ""))
        started = []
        for cam in cfg.get("cameras", []) or []:
            cid = str(cam.get("id") or f"cam{len(started)+1}")
            r = self.start(guard, infer_lock, cid, str(cam.get("source", "")),
                           name=str(cam.get("name", cid)), fps=float(cam.get("fps", 2)),
                           zone=cam.get("zone"))
            started.append({cid: r.get("ok", False)})
        return {"ok": True, "site": self.site, "started": started}


manager = WorkerManager()
