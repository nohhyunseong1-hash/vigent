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
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import cv2
import data_engine
import numpy as np
import proximity
import runtime_config
import tuning
import vlog
import zone_tile
from camera_registry import mask_source as _mask_src  # 3.0: 로그에 RTSP 자격증명 노출 방지(마스킹)
from web_util import zone_points

_ROOT = Path(__file__).resolve().parent.parent
_WLOG = vlog.get("vigent.worker")   # 워커 예외·재시작 구조화 로깅(1단계 안정성)
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 2단계 안정성 설정(하드코딩 금지 — env 우선, 없으면 tuning.yaml, 없으면 기본값)
#   hang: 정상 fps 2.0=0.5s 간격 → 15s 기본은 오탐 없이 진짜 멈춤만 잡는 여유값.
_HANG_TIMEOUT = float(os.environ.get("VIGENT_HANG_TIMEOUT") or tuning.val("stability", "hang_timeout_s", 15.0))
_RECONNECT_MAX = float(os.environ.get("VIGENT_RECONNECT_MAX") or tuning.val("stability", "reconnect_max_s", 30.0))
_READ_FAIL_MAX = int(os.environ.get("VIGENT_READ_FAIL_MAX") or tuning.val("stability", "read_fail_max", 5))
# 프레임 신선도(지연): 스트림은 내부 버퍼를 최소화해 '최신 프레임'을 처리(과거 프레임 지연 누적 방지).
#   파일 소스는 순차 처리라 이 설정을 적용하지 않는다(모든 프레임을 봐야 하므로).
_CAP_BUFFERSIZE = int(os.environ.get("VIGENT_CAP_BUFFERSIZE") or tuning.val("stability", "cap_buffersize", 1))
_COOLDOWN_S = float(tuning.val("detect", "cooldown_s", 15.0))
_FALL_ANGLE = float(tuning.val("fall", "angle_deg", 55))   # 쓰러짐 몸통각 임계


def _point_in_poly(x: float, y: float, poly: list) -> bool:
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
    """danger_zone 의 정규화 폴리곤(없으면 빈 목록). B2: 런타임(data/) 우선 → config/ 시드 폴백."""
    p = runtime_config.read_path("config/danger_zone.json")
    if not p.exists():
        return []
    try:
        z = json.loads(p.read_text(encoding="utf-8"))
        return zone_points(z)
    except (ValueError, OSError, KeyError):
        return []


def _frame_to_dataurl(frame: "np.ndarray") -> str | None:
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


def _person_metrics(xy: "np.ndarray", cf: "np.ndarray", H: int, min_kp: float = 0.3) -> "dict[str, Any] | None":
    """사람 1명의 키포인트 → 자세 지표. None 이면 판단 불가(어깨·엉덩이 미검출)."""
    def gp(idxs: list) -> "np.ndarray | None":
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
    """RTMPose(rtmlib, Apache-2.0) 1회 로드(공유). person 박스(RF-DETR/guard) 주입 → 사람별 자세 지표.
    실패/박스없음 시 [](무중단). YOLOX 내장 검출은 기본 off — 박스는 guard.detect(person) 가 제공한다
    (T10c: ultralytics/AGPL 제거, top-down 입력은 RF-DETR person 박스).

    출력 계약은 기존과 동일(사람별 metrics dict + kp_xy/kp_cf) → FallTracker/ErgonomicsTracker 무변경."""

    def __init__(self) -> None:
        self._m: Any = None            # RtmPoseDetector(지연 import) → Any
        self._failed = False

    def persons(self, frame: "np.ndarray", boxes: list | None = None, min_kp: float = 0.3) -> "list[dict[str, Any]]":
        """boxes: 사람 픽셀 박스 [[x1,y1,x2,y2],..](guard.detect person 유래). None/[] → []."""
        if self._m is None and not self._failed:
            try:
                import sys
                sys.path.insert(0, str(_ROOT / "vigent-core"))
                from pose.rtmpose_adapter import RtmPoseDetector
                self._m = RtmPoseDetector()
            except Exception:  # noqa: BLE001  로드 실패 → 포즈 기능만 비활성(탐지/낙상 무중단)
                self._failed = True
        if self._m is None or not boxes:
            return []
        try:
            H = frame.shape[0]
            ppl = self._m.persons(frame, bboxes=list(boxes))   # [(kp_xy[17,2] px, kp_cf[17])] · COCO-17
            out = []
            for xy, cf in ppl:
                m = _person_metrics(xy, cf, H, min_kp)   # 판정 로직 재사용(무수정)
                if m:
                    m["kp_xy"] = xy      # 원시 키포인트 가산(근골격계 레이어용). 낙상은 미사용 — 불변.
                    m["kp_cf"] = cf
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

    def __init__(self, vlm=False) -> None:
        self._tracks: list = []
        self._vlm = vlm

    def update(self, frame, ts, boxes=None) -> "tuple[bool, str]":
        """프레임 처리 → (낙상여부, 사유). 모델/키포인트 없으면 (False,'').
        boxes: guard.detect person 박스(픽셀) — RTMPose top-down 입력."""
        H, W = frame.shape[:2]
        diag = (W * W + H * H) ** 0.5
        persons = _posemodel.persons(frame, boxes)
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
                    except Exception as _we:  # noqa: BLE001
                        _WLOG.debug("worker 무시 예외 [프레임 캡처/처리]: %s", _we)
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

    def __init__(self, theme: str = "safety") -> None:
        import ergonomics as _erg
        self._erg = _erg
        cfg = _erg.load_ergonomics(theme)
        self._joints = cfg.get("joints", {}) if isinstance(cfg, dict) else {}
        try:
            self._hold_sec = float(cfg.get("hold_sec", 3)) if isinstance(cfg, dict) else 3.0
        except Exception:  # noqa: BLE001
            self._hold_sec = 3.0
        self._corrob = bool(cfg.get("neck_requires_corroboration", False)) if isinstance(cfg, dict) else False
        self._enabled = bool(self._joints)       # 설정 없으면 조용히 비활성(저하 0)
        self._tracks: list[dict] = []
        self._last_ts = 0.0

    def update(self, frame, ts, boxes=None) -> "list[tuple[str, str, str]]":
        """반환: [(rule, level, note), ...] — hold 지속이 확정된 사람만. 없으면 [].
        boxes: guard.detect person 박스(픽셀) — RTMPose top-down 입력."""
        if not self._enabled:
            return []
        if ts - self._last_ts < self._MIN_INTERVAL:      # 저빈도 스로틀
            return []
        self._last_ts = ts
        try:
            persons = _posemodel.persons(frame, boxes)
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
            # 발화용 유효등급(목 보조조건 적용) — 허리·어깨 판정은 그대로, 목 단독 warn만 억제
            eff = self._erg.effective_worst(a.get("grades", {}), self._corrob)
            bad = eff in ("warn", "bad")
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
                    level = {"warn": "중간", "bad": "높음"}.get(eff, a.get("level", "낮음"))
                    note = f"{a['note']} · {held:.0f}초 지속"
                    out.append(("ergonomic_risk", level, note))
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

    def __init__(self) -> None:
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


class _StreamCapture:
    """프레임 신선도(지연) — 스트림 전용 백그라운드 캡처 스레드.

    RTSP 등 스트림을 계속 읽어 **최신 1프레임만 슬롯에 덮어쓰기**로 보관한다. worker._loop 은
    이 슬롯에서 가장 최신 프레임을 가져가 처리한다 → FFmpeg 백엔드가 CAP_PROP_BUFFERSIZE 를
    무시해도(RTSP 대부분 무시) 과거 프레임 지연 누적을 원천 차단. RTSP 재연결(지수 백오프)·
    BUFFERSIZE 설정을 내장한다. 파일 소스에는 쓰지 않는다(순차 처리·되감기 유지).
    """
    def __init__(self, source: str, name: str):
        self.source = source
        self.name = name
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._ts = 0.0                 # 슬롯 마지막 갱신 시각(신선도 기준)
        self.reconnects = 0
        self.read_ms = 0.0
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self):
        cap = cv2.VideoCapture(int(self.source) if self.source.isdigit() else self.source)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)   # 보조(웹캠/V4L2 등 일부만 존중; FFmpeg/RTSP 는 무시될 수 있음)
        except Exception as _we:  # noqa: BLE001
            _WLOG.debug("worker 무시 예외 [cap 버퍼설정]: %s", _we)
        return cap

    def _run(self):
        cap = self._open()
        rbackoff = 1.0
        read_fails = 0
        while not self._stop.is_set():
            _rt = time.time()
            ok, frame = cap.read()
            self.read_ms = round((time.time() - _rt) * 1000, 1)
            if not ok:
                read_fails += 1
                if read_fails >= _READ_FAIL_MAX:      # 스트림 끊김 → 지수 백오프 재연결(캡처 스레드 내부)
                    self.reconnects += 1
                    _WLOG.warning("캡처 '%s'(%s) 스트림 끊김 → 재연결 #%d (백오프 %.0fs)",
                                  self.name, _mask_src(self.source), self.reconnects, rbackoff)
                    try:
                        cap.release()
                    except Exception as _we:  # noqa: BLE001
                        _WLOG.debug("worker 무시 예외 [cap release]: %s", _we)
                    slept = 0.0
                    while slept < rbackoff and not self._stop.is_set():
                        time.sleep(0.2)
                        slept += 0.2
                    cap = self._open()
                    rbackoff = min(rbackoff * 2, _RECONNECT_MAX)
                    read_fails = 0
                else:
                    time.sleep(0.05)
                continue
            read_fails = 0
            rbackoff = 1.0
            with self._lock:                          # 최신 프레임 슬롯을 원자적으로 덮어쓰기
                self._frame = frame
                self._ts = time.time()
        try:
            cap.release()
        except Exception as _we:  # noqa: BLE001
            _WLOG.debug("worker 무시 예외 [cap release]: %s", _we)

    def read_latest(self) -> "tuple[np.ndarray | None, float]":
        """(frame, slot_ts) 반환. 아직 첫 프레임 없으면 (None, 0.0).
        캡처가 매 프레임 새 배열을 슬롯에 넣으므로 반환 참조는 이후 덮어써도 안전(불변)."""
        with self._lock:
            return self._frame, self._ts

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


class _FrameCtx:
    """_loop 프레임 처리 컨텍스트(P2-13에서 _loop 분해 시 추출).
    _process_frame 가 읽고 갱신하는 설정·상태를 한 묶음으로 전달·유지한다
    (cooldown·last_collect 는 프레임 간 유지되는 가변 상태)."""

    def __init__(self, detectors, zone, ftrack, mtrack, etrack,
                 collect_on, collect_every, dataset_dir, name, source):
        self.detectors = detectors
        self.zone = zone
        self.ftrack = ftrack          # 낙상 추적(상태 유지)
        self.mtrack = mtrack          # 무동작·급이동 추적
        self.etrack = etrack          # 근골격계 부담자세 지속(가산)
        self.collect_on = collect_on
        self.collect_every = collect_every
        self.dataset_dir = dataset_dir
        self.name = name
        self.source = source
        self.cooldown: dict[str, float] = {}
        self.last_collect = 0.0


class Worker:
    """1대용 추론 워커(지연 시작·정지·상태). 서버 전역 싱글톤으로 사용."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._hang_thread: threading.Thread | None = None   # 2단계: hang 감시 데몬
        self._stop = threading.Event()
        self._restart_req = threading.Event()                # 2단계: hang 감지 시 현 _loop 재시작 요청
        self._cap = None                                     # 현재 VideoCapture(hang 시 감시 스레드가 release로 언블록)
        self._streamcap = None                               # 프레임신선도: 스트림 캡처 스레드(thread 모드)
        self._last_frame = None                              # 3.0: 최신 프레임(스냅샷/오버레이용, numpy 참조)
        self._last_dets: list = []                           # 3.0: 최신 검출(정규화 bbox) — 대시보드 오버레이
        self._last_pc = 0                                    # 최신 인원수
        self._last_sig: dict = {}                            # 최신 파생신호(ppe_missing·fire 등)
        self._last_fired: list = []                          # 3.1b: 최신 발화 규칙명(zone_intrusion·fall 등) — 대시보드 뱃지·전역경보
        self.state: dict[str, Any] = {
            "running": False, "source": "", "name": "", "fps": 0,
            "frames": 0, "events": 0, "last_event": "", "error": ""}

    def start(self, guard, lock, source: str, name: str = "CAM", fps: float = 2.0,
              detectors: list | None = None, zone: list | None = None) -> dict:
        if self.state["running"]:
            return {"ok": False, "error": "이미 실행 중 — 먼저 중지하세요."}
        self._stop.clear()
        self._restart_req.clear()
        self.state.update({"running": True, "source": source, "name": name, "fps": fps,
                           "frames": 0, "events": 0, "last_event": "", "error": "",
                           "last_frame_ts": 0.0, "restarts": 0,
                           "reconnects": 0, "hangs": 0})   # 1단계 하트비트·재시작 + 2단계 재연결·hang 카운터
        self._thread = threading.Thread(
            target=self._run_supervised,      # 1단계: 감독자 경유(루프가 죽어도 재시작 — 무증상 실패 차단)
            args=(guard, lock, source, name, fps,
                  detectors or ["person", "ppe", "forklift", "fire_smoke"], zone),
            daemon=True)
        self._thread.start()
        self._hang_thread = threading.Thread(   # 2단계: hang 감시(last_frame_ts N초 무진전 → 재기동)
            target=self._hang_watch, args=(name,), daemon=True)
        self._hang_thread.start()
        return {"ok": True, "status": self.status()}

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.state["running"] = False
        return {"ok": True, "status": self.status()}

    def status(self) -> dict:
        s = dict(self.state)
        lft = s.get("last_frame_ts", 0.0)
        if lft and lft > 0:
            idle = time.time() - lft
            s["last_frame_secs_ago"] = round(idle, 1)
            s["hang"] = bool(s.get("running")) and idle > _HANG_TIMEOUT   # 2단계: 멈춤 판정
        else:
            s["last_frame_secs_ago"] = None
            s["hang"] = False
        # 프레임 신선도(캡처 스레드 모드) — 현장 RTSP 지연 계측 훅
        sc = self._streamcap
        if sc is not None:
            s["capture_mode"] = "thread"
            _, slot_ts = sc.read_latest()
            s["slot_age_s"] = round(time.time() - slot_ts, 2) if slot_ts else None   # 슬롯 나이=현재-슬롯시각(작을수록 신선)
            s["capture_alive"] = sc.alive()
        return s

    def _hang_watch(self, name):
        """2단계: last_frame_ts 가 _HANG_TIMEOUT 초 무진전이면 hang 판정 → cap.release() 로 언블록 + 재시작 요청.
        프로세스는 살아있는데 워커만 멈춘 '무증상 hang' 을 앱 내부에서 1차 복구(워치독 프로세스 재기동보다 먼저)."""
        while not self._stop.is_set():
            self._stop.wait(1.0)                      # 1초 간격 감시(정지 신호에 즉시 반응)
            if self._stop.is_set():
                break
            if not self.state.get("running"):
                continue
            lft = self.state.get("last_frame_ts", 0.0)
            if lft <= 0:                              # 첫 프레임 전(초기화·재연결 중) → 판정 보류
                continue
            idle = time.time() - lft
            if idle > _HANG_TIMEOUT and not self._restart_req.is_set():
                _WLOG.error("워커 '%s' HANG 감지(%.1fs 무진전 > %.0fs) → 재기동", name, idle, _HANG_TIMEOUT)
                self.state["error"] = f"hang {int(idle)}s → 재기동"
                self.state["hangs"] = self.state.get("hangs", 0) + 1
                self._restart_req.set()               # _loop while 조건이 이걸 보고 탈출
                try:
                    if self._cap is not None:
                        self._cap.release()           # cap.read() 블로킹을 깨워 즉시 탈출 유도
                except Exception as _we:  # noqa: BLE001
                    _WLOG.debug("worker 무시 예외 [cap release(깨우기)]: %s", _we)

    def _run_supervised(self, guard, lock, source, name, fps, detectors, zone=None):
        """워커 루프 감독자(1단계 안정성 핵심).

        `_loop` 이 예외로 빠져나오거나 조용히 종료돼도, `_stop` 전까지 **지수 백오프로 재시작**한다.
        daemon 스레드가 소리 없이 사라져 '/health 는 200 인데 추론은 죽은' 무증상 실패를 차단한다.
        예외 위치·카메라명·스택트레이스를 구조화 로그로 남긴다.
        """
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.state["running"] = True
                # 재시작 유예: 하트비트를 now 로 리셋해야 hang 감시가 옛 last_frame_ts 로 즉시 재판정하지 않는다.
                #   _loop 첫 정상 프레임이 곧 갱신 → 정상 재개. 진짜 hang 이면 HANG_TIMEOUT 후 다시 감지(무한재시작 방지).
                self.state["last_frame_ts"] = time.time()
                self._loop(guard, lock, source, name, fps, detectors, zone)
            except Exception:  # noqa: BLE001  _loop 밖으로 샌 예외(카메라 초기화 등)
                _WLOG.error("워커 '%s'(%s) _loop 예외 — 재시작 대상\n%s",
                            name, source, traceback.format_exc())
                self.state["error"] = f"_loop crashed: {traceback.format_exc().splitlines()[-1]}"
            if self._stop.is_set():
                break
            # hang 재시작인지(감시 스레드가 요청) crash/종료인지 구분 → 신호 해제
            was_hang = self._restart_req.is_set()
            self._restart_req.clear()
            self.state["restarts"] = self.state.get("restarts", 0) + 1
            if was_hang:
                _WLOG.warning("워커 '%s' HANG 재시작 #%d (즉시)", name, self.state["restarts"])
                wait = 1.0                          # hang 은 즉시 재기동(다운타임 최소), 백오프 리셋
                backoff = 1.0
            else:
                _WLOG.warning("워커 '%s' 재시작 #%d (%.0fs 백오프)", name, self.state["restarts"], backoff)
                wait = backoff
                backoff = min(backoff * 2, 30.0)    # 지수 백오프 상한 30s(재시도 폭주 방지)
            slept = 0.0
            while slept < wait and not self._stop.is_set():
                time.sleep(0.2)
                slept += 0.2
        self.state["running"] = False

    def _process_frame(self, frame, t0, guard, lock, ctx: "_FrameCtx"):
        """단일 프레임 처리 — 수집·추론·트래커·발화·쿨다운·이벤트로깅(P2-13에서 _loop 에서 추출).
        프레임 단위 예외를 여기서 격리(한 프레임 실패가 루프를 죽이지 않음).
        ctx.cooldown/last_collect 와 self.state 를 갱신한다. 동작은 추출 전과 동일."""
        try:                                        # 1단계: 프레임 단위 예외 격리 → 한 프레임 실패가 루프를 죽이지 않음
            if ctx.collect_on and (t0 - ctx.last_collect) >= ctx.collect_every:   # 학습용 프레임 수집
                ctx.last_collect = t0
                try:
                    ctx.dataset_dir.mkdir(parents=True, exist_ok=True)
                    safe = "".join(c if c.isalnum() else "_" for c in str(ctx.name))[:20]
                    cv2.imwrite(str(ctx.dataset_dir / f"{safe}_{int(t0)}.jpg"), frame)
                    self.state["collected"] = self.state.get("collected", 0) + 1
                except Exception as _we:  # noqa: BLE001
                    _WLOG.debug("worker 무시 예외 [수집 카운트 갱신]: %s", _we)
            with lock:                            # 코어 추론 직렬화(브라우저와 충돌 방지)
                # 5단계: 카메라별 추적 격리(track_key) — 다른 카메라/브라우저와 _tracks 안 섞이게.
                out = guard.detect(frame, detectors=ctx.detectors, track_key="cam:" + str(ctx.name))
                # 3.0: 대시보드 스냅샷·오버레이용 최신 상태 보관(정규화 bbox — 프론트가 화면크기로 복원).
                self._last_frame = frame
                self._last_dets = [{"class": d.get("label"), "score": round(float(d.get("conf", 0)), 3),
                                    "bbox": [round(float(v), 4) for v in d.get("bbox", [0, 0, 0, 0])]}
                                   for d in out.get("detections", [])]
                self._last_pc = out.get("person_count", 0)
                self._last_sig = out.get("signals", {})
                # 포즈(낙상·근골격) top-down 입력 = guard.detect person 박스(RF-DETR·_nms/_track 적용, 픽셀).
                #   worker 기본 detectors 에 person 포함 → 박스 항상 제공. person 없으면 포즈만 비활성(무중단).
                _H, _W = frame.shape[:2]
                person_boxes = [[d["bbox"][0] * _W, d["bbox"][1] * _H,
                                 d["bbox"][2] * _W, d["bbox"][3] * _H]
                                for d in out.get("detections", []) if d["label"] == "person"]
                fall, freason = ctx.ftrack.update(frame, t0, person_boxes)   # 다중단서+모션 낙상
                try:
                    ergo_fired = ctx.etrack.update(frame, t0, person_boxes)  # 근골격계 부담자세(포즈 각도·저빈도)
                except Exception:  # noqa: BLE001  가산 레이어 — 실패해도 낙상·탐지 무중단
                    ergo_fired = []
            fired = _derive(out, ctx.zone, frame.shape[0] / frame.shape[1])
            # B9: 위험구역 한정 타일 재검출(가산·기본 off, VIGENT_ZONE_TILE=1). zone 내 놓친 소형 person 회수.
            #   ★확인1(스코프 한정): 타일 박스는 zone_intrusion 발화에만 쓴다 — 공유 out["detections"] 에
            #     병합하지 않음 → proximity/crowd/motion/트래커/PPE 전부 무영향.
            #   ★확인2(이종 검출기): 일반검출=guard(설정 검출기), 타일=rfdetr_service(RF-DETR 저임계) — 다른 모델일 수
            #     있다. 여기선 '박스가 zone 안에 있냐'만 보므로 문제없음. 나중에 conf 비교를 넣으려면 두 모델의
            #     conf 가 비교 불가능한 척도임에 주의(RF-DETR vs guard).
            #   every-N: VIGENT_ZONE_TILE_EVERY(기본 1). N 프레임마다만 타일 → 최악 지연 = N/fps 초(침입은 지속).
            if os.environ.get("VIGENT_ZONE_TILE") == "1" and ctx.zone \
                    and not any(r[0] == "zone_intrusion" for r in fired):
                _every = max(1, int(os.environ.get("VIGENT_ZONE_TILE_EVERY", "1")))
                if self.state["frames"] % _every == 0:
                    try:
                        import rfdetr_service as _rfs  # 지역 import: off 면 로드·import 조차 안 함
                        _extra = zone_tile.zone_tile_detect(
                            frame, ctx.zone, lambda img: _rfs.rfdetr.detect_persons(img, thr=0.1))
                        if any(zone_tile.foot_in_zone(d["bbox"], ctx.zone) for d in _extra):
                            fired.append(("zone_intrusion", "high", "위험구역 내 작업자 감지(구역-타일 회수)"))
                    except Exception as _ze:  # noqa: BLE001  가산 레이어 — 실패해도 기존 검출 무중단
                        _WLOG.debug("worker 무시 예외 [zone-tile]: %s", _ze)
            if fall:
                fired.append(("fall_suspected", "critical", f"작업자 낙상 의심 — {freason}"))
            fired += ctx.mtrack.update(out.get("detections", []), t0)   # 무동작·급이동
            fired += ergo_fired                                     # 근골격계 부담자세(지속 확정분)
            self._last_fired = [r[0] for r in fired]                # 3.1b: 이번 프레임 발화 규칙(뱃지·전역경보 근거)
            now = time.time()
            for rule, level, note in fired:
                if now - ctx.cooldown.get(rule, 0) < _COOLDOWN_S:
                    continue
                ctx.cooldown[rule] = now
                data_engine.log_event(rule=rule, level=level, site=ctx.name, note=note,
                                      image_data_url=_frame_to_dataurl(frame))
                self.state["events"] += 1
                self.state["last_event"] = f"{rule}({level})"
        except Exception as _fe:   # noqa: BLE001  프레임 처리 실패 → 로그 남기고 다음 프레임(루프 유지)
            self.state["error"] = f"frame: {type(_fe).__name__}: {_fe}"
            _WLOG.error("워커 '%s'(%s) 프레임 처리 예외 — 계속 진행\n%s",
                        ctx.name, _mask_src(ctx.source), traceback.format_exc())

    def _setup_run(self, source, name, fps, detectors, zone):
        """_loop 시작 준비 — 트래커·수집설정·zone 컨텍스트(ctx) + 소스판별 + 캡처 초기화(P2-13 분해).
        반환값을 _loop 이 '동일 이름' 지역변수로 언팩하므로 획득 루프 본문은 변경되지 않는다.
        self._cap/_streamcap 부수효과(hang 감시 스레드가 release 로 언블록)는 여기서 설정."""
        import os
        interval = 1.0 / max(0.2, fps)
        # 데이터 수집 모드(파일럿 학습용) — VIGENT_COLLECT=1 이면 일정 간격으로 프레임 저장
        collect_on = os.environ.get("VIGENT_COLLECT", "0") == "1"
        collect_every = float(os.environ.get("VIGENT_COLLECT_EVERY", "30"))
        dataset_dir = _ROOT / "data" / "dataset" / "images"
        ftrack = FallTracker(vlm=getattr(self, "_vlm_fall", False))   # 카메라별 낙상 추적(상태 유지)
        mtrack = MotionTracker()                                       # 무동작·급이동 추적
        etrack = ErgonomicsTracker()                                   # 근골격계 부담자세 지속(가산·낙상 불변)
        zone = [tuple(p) for p in zone] if zone else _load_zone()   # 카메라별 구역 or 전역
        ctx = _FrameCtx(detectors, zone, ftrack, mtrack, etrack,
                        collect_on, collect_every, dataset_dir, name, source)
        is_image = Path(source).suffix.lower() in _IMG_EXT and Path(source).exists()
        is_file_video = (not is_image) and Path(source).exists()   # 로컬 비디오 파일 → 끝나면 되감기(스트림 아님)
        static = cv2.imread(source) if is_image else None
        is_stream = (not is_image) and (not is_file_video)   # RTSP/HTTP/웹캠 = 스트림(최신 프레임 우선)
        # 프레임 신선도: 스트림+thread 모드 → 캡처 스레드가 최신 1프레임만 보관(FFmpeg 무시 대응). 기본 sync(롤백 경로).
        capture_mode = os.environ.get("VIGENT_CAPTURE_MODE", "sync").lower()
        use_capture_thread = is_stream and capture_mode == "thread"
        cap = None
        streamcap = None
        if use_capture_thread:
            streamcap = _StreamCapture(source, name)
            streamcap.start()
            self._streamcap = streamcap
            _WLOG.info("워커 '%s'(%s) 캡처 스레드 모드(최신 프레임 우선)", name, _mask_src(source))
        elif not is_image:
            cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
            if is_stream:
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)   # 보조(FFmpeg/RTSP 는 무시될 수 있음 → thread 모드 권장)
                except Exception as _we:  # noqa: BLE001
                    _WLOG.debug("worker 무시 예외 [cap 버퍼설정]: %s", _we)
            self._cap = cap                          # 감시 스레드가 hang 시 release 로 언블록
        return interval, ctx, static, is_image, is_file_video, is_stream, use_capture_thread, cap, streamcap

    def _loop(self, guard, lock, source, name, fps, detectors, zone=None):
        (interval, ctx, static, is_image, is_file_video, is_stream,
         use_capture_thread, cap, streamcap) = self._setup_run(source, name, fps, detectors, zone)
        read_fails = 0
        rbackoff = 1.0
        slot_frame_ts = 0.0                          # 캡처 스레드 모드의 하트비트 기준(슬롯 갱신 시각)
        try:
            # _restart_req: hang 감시가 세팅 → 루프 탈출 → 감독자가 재시작(2단계)
            while not self._stop.is_set() and not self._restart_req.is_set():
                t0 = time.time()
                if is_image:
                    frame = static.copy() if static is not None else None
                elif use_capture_thread:
                    frame, slot_ts = streamcap.read_latest()   # 캡처 스레드가 보관한 최신 프레임(락 보호)
                    self.state["reconnects"] = streamcap.reconnects
                    self.state["read_ms"] = streamcap.read_ms
                    if frame is None:                          # 아직 첫 프레임 없음(캡처 워밍업/재연결 중)
                        if not streamcap.alive():              # 캡처 스레드 사망 → 감독자 재시작 유도
                            _WLOG.error("워커 '%s'(%s) 캡처 스레드 사망 → _loop 종료(감독자 재시작)", name, _mask_src(source))
                            break
                        time.sleep(0.05)
                        continue
                    slot_frame_ts = slot_ts                    # 하트비트 기준(슬롯 정지=캡처 hang → hang 감시가 잡음)
                    self.state["slot_age_s"] = round(time.time() - slot_ts, 2)   # 슬롯 나이(신선도 지표)
                else:
                    _rt = time.time()
                    ok, frame = cap.read()
                    if is_stream and ok:
                        # read_ms: sync 모드 신선도 프록시. 버퍼가 쌓이면 read 가 즉시 반환(작은 ms=과거 프레임),
                        #   버퍼 최소(BUFFERSIZE=1)면 read 가 다음 프레임을 기다림(간격에 근접=최신 프레임).
                        self.state["read_ms"] = round((time.time() - _rt) * 1000, 1)
                    if not ok:
                        if is_file_video:            # 파일 끝 → 되감기(루프 재생, 기존 동작)
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            ok, frame = cap.read()
                            if not ok:
                                time.sleep(0.5)
                                continue
                        else:                        # 스트림/카메라 끊김 → 지수 백오프 재연결
                            read_fails += 1
                            if read_fails >= _READ_FAIL_MAX:
                                self.state["reconnects"] = self.state.get("reconnects", 0) + 1
                                _WLOG.warning("워커 '%s'(%s) 스트림 끊김 → 재연결 #%d (백오프 %.0fs)",
                                              name, source, self.state["reconnects"], rbackoff)
                                try:
                                    cap.release()
                                except Exception as _we:  # noqa: BLE001
                                    _WLOG.debug("worker 무시 예외 [cap release(재연결)]: %s", _we)
                                slept = 0.0
                                while slept < rbackoff and not self._stop.is_set() and not self._restart_req.is_set():
                                    time.sleep(0.2)
                                    slept += 0.2
                                cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
                                try:
                                    cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)   # 재연결 후에도 버퍼 최소화 유지
                                except Exception as _we:  # noqa: BLE001
                                    _WLOG.debug("worker 무시 예외 [cap 버퍼설정(재연결)]: %s", _we)
                                self._cap = cap
                                rbackoff = min(rbackoff * 2, _RECONNECT_MAX)   # 지수 백오프(상한 _RECONNECT_MAX)
                                read_fails = 0
                            else:
                                time.sleep(0.3)
                            continue
                    else:
                        if read_fails or rbackoff > 1.0:
                            read_fails = 0
                            rbackoff = 1.0            # 재연결 성공 → 백오프 리셋
                if frame is None:
                    self.state["error"] = "프레임 읽기 실패(소스 확인)"
                    time.sleep(0.5)
                    continue
                self.state["frames"] += 1
                # 하트비트: 캡처 스레드 모드는 '슬롯 갱신 시각' 기준 → 캡처가 멈추면 last_frame_ts 도 멈춰
                #   hang 감시가 캡처 스레드 정지를 잡아 재시작한다(캡처 스레드를 감시 대상에 편입). sync 는 처리 시각.
                self.state["last_frame_ts"] = slot_frame_ts if use_capture_thread else time.time()
                self._process_frame(frame, t0, guard, lock, ctx)   # 수집·추론·트래커·발화·로깅(P2-13 추출)
                dt = time.time() - t0
                if dt < interval and not self._stop.is_set():
                    time.sleep(interval - dt)
        except Exception as ex:                       # noqa: BLE001  루프 자체 예외 → supervised 가 재시작
            self.state["error"] = f"{type(ex).__name__}: {ex}"
            _WLOG.error("워커 '%s'(%s) _loop 예외 — 감독자 재시작 위임\n%s",
                        name, source, traceback.format_exc())
        finally:
            if cap is not None:
                cap.release()
            if streamcap is not None:
                streamcap.stop()              # 캡처 스레드 정리(재시작 시 새로 생성)
            self._cap = None                  # 감시 스레드 오참조 방지(다음 라운드에서 재설정)
            self._streamcap = None
            # running 은 감독자(_run_supervised)가 관리 — 여기서 내리지 않는다(재시작 간 깜빡임·hang 오판 방지)


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
        started: list[dict] = []
        for cam in cfg.get("cameras", []) or []:
            cid = str(cam.get("id") or f"cam{len(started)+1}")
            r = self.start(guard, infer_lock, cid, str(cam.get("source", "")),
                           name=str(cam.get("name", cid)), fps=float(cam.get("fps", 2)),
                           zone=cam.get("zone"))
            started.append({cid: r.get("ok", False)})
        return {"ok": True, "site": self.site, "started": started}


manager = WorkerManager()
