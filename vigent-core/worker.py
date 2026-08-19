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
import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import cv2
import data_engine
import numpy as np
import privacy
import proximity
import runtime_config
import tuning
import vlog
import zone_debounce
import zone_tile
from camera_registry import mask_source as _mask_src  # 3.0: 로그에 RTSP 자격증명 노출 방지(마스킹)
from camera_registry import scrub_credentials as _scrub  # [S2-수정] state["error"](→/worker/status) 노출 방지
from web_util import zone_points

_ROOT = Path(__file__).resolve().parent.parent
_WLOG = vlog.get("vigent.worker")   # 워커 예외·재시작 구조화 로깅(1단계 안정성)
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# 2단계 안정성 설정(하드코딩 금지 — env 우선, 없으면 tuning.yaml, 없으면 기본값)
#   hang: 정상 fps 2.0=0.5s 간격 → 15s 기본은 오탐 없이 진짜 멈춤만 잡는 여유값.
_HANG_TIMEOUT = float(os.environ.get("VIGENT_HANG_TIMEOUT") or tuning.val("stability", "hang_timeout_s", 15.0))
# [B4] 워커 기동 직후 유예 — 이 시간 안에는 hang 판정을 하지 않는다. 콜드 로드(실측 12.5s)가
#   15s 워치독을 넘겨 무한 재시작에 빠지던 문제의 근본 해법은 "임계를 늘리기"가 아니라
#   "예열이 끝난 뒤에 판정 시작"이다(readiness.py 참조). 값은 config/tuning.yaml `health:` 공유.
_STARTUP_GRACE = float(os.environ.get("VIGENT_STARTUP_GRACE")
                       or tuning.val("health", "startup_grace_s", 90.0))
# [B3] 재연결 백오프 상한. 30→5초로 낮춘다(2026-08-16 원인분석 audit/b3_root_cause_2026-08-16.md).
#   카메라 동시 세션 한도가 2(실측)인데 워커 1 + go2rtc 1 로 여유가 0이라, 슬롯이 열리는 순간을
#   누가 먼저 잡느냐의 경쟁이 된다. 워커가 30초씩 쉬면 그동안 슬롯이 열려도 못 잡고, 다음 시도엔
#   이미 없어 백오프가 더 길어진다 — **한 번 밀리면 영구히 밀리는** 구조(실측 7분 검출 사망).
#   상한을 5초로 낮춰 그 구조를 깬다. 카메라 부하는 재시도 간격 5초라 무시할 수준.
_RECONNECT_MAX = float(os.environ.get("VIGENT_RECONNECT_MAX") or tuning.val("stability", "reconnect_max_s", 5.0))
_READ_FAIL_MAX = int(os.environ.get("VIGENT_READ_FAIL_MAX") or tuning.val("stability", "read_fail_max", 5))
# 프레임 신선도(지연): 스트림은 내부 버퍼를 최소화해 '최신 프레임'을 처리(과거 프레임 지연 누적 방지).
#   파일 소스는 순차 처리라 이 설정을 적용하지 않는다(모든 프레임을 봐야 하므로).
_CAP_BUFFERSIZE = int(os.environ.get("VIGENT_CAP_BUFFERSIZE") or tuning.val("stability", "cap_buffersize", 1))
# RTSP 전송방식 강제 TCP: FFmpeg 기본(UDP)은 손실 많은 WiFi 에서 프레임 드랍·재연결 폭주 →
#   워커가 프레임을 못 받아 guard.detect(RF-DETR) 자체가 안 돌아 검출 0 (2026-08 실측: Tapo UDP 재연결 7회,
#   프레임나이 3~27s). go2rtc(TCP)는 같은 스트림 16fps·멈춤0 로 안정 → 워커도 TCP 로 맞춘다.
#   파일·웹캠(int) 소스엔 무영향(옵션 무시). env 로 override 가능. cv2 VideoCapture(FFMPEG) 열기 전에 설정.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|max_delay;500000")
_COOLDOWN_S = float(tuning.val("detect", "cooldown_s", 15.0))
# ②: 증거 JPEG(무거운 후속) 전용 쿨다운 — 이벤트 '기록'은 _COOLDOWN_S 주기로 유지하되,
#   증거 저장(인코딩+디스크)만 rule별로 이 주기까지 스로틀. 어떤 오발화도 서버를 포화 못 시킴.
_EVIDENCE_COOLDOWN_S = float(tuning.val("detect", "evidence_cooldown_s", 30.0))
# 3.9 ①: 포즈(근골격) 추론은 검출(guard)과 주기 분리 — 고정 pose_fps 로만 실행.
#   프레임당 포즈(CPU ~수백ms)가 focus 5fps 검출을 막던 문제(3.8). 기존 자세 캐던스(2fps)와 동일해 회귀 0.
_POSE_MIN_INTERVAL = 1.0 / max(0.2, float(tuning.val("worker", "pose_fps", 2.0)))


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


def _default_detectors() -> list[str]:
    """워커 기본 검출기 — 안전 테마 person+ppe+fire_smoke.
    forklift 는 F-7(과소학습 오탐, conf~0.002)로 **기본 제외**. 모델 개선 후
    tuning detect.include_forklift=1(또는 env VIGENT_INCLUDE_FORKLIFT=1)로 명시 재활성 가능.
    [G1, 2026-08-19] fire_smoke 도 현장 프로파일에서 뺄 수 있게 스위치 추가 —
    기본 1(포함, 현행 무변경). 학원 실습장처럼 화재 감시가 계약 범위 밖이고
    배경 오탐 리스크(프레스 현장 실측)가 있는 현장은 0 으로 끈다."""
    base = ["person", "ppe"]
    if tuning.val("detect", "include_fire_smoke", 1, env="VIGENT_INCLUDE_FIRE_SMOKE"):
        base.append("fire_smoke")
    if tuning.val("detect", "include_forklift", 0, env="VIGENT_INCLUDE_FORKLIFT"):
        base.append("forklift")
    return base


def _det_dict(d: dict) -> dict:
    """guard 검출 → 대시보드 표시 dict(정규화 bbox + 트랙 id). 3.12: 풀세트·person고속 공통 포맷.
    stale([T-E2E 유령박스]): 미매칭 코스팅 트랙 표식 — 표시 경로가 숨긴다(판정 경로 무영향)."""
    return {"class": d.get("label"), "score": round(float(d.get("conf", 0)), 3),
            "bbox": [round(float(v), 4) for v in d.get("bbox", [0, 0, 0, 0])],
            "id": d.get("tid", -1), "stale": bool(d.get("stale", False))}


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


def _frame_to_dataurl(frame: "np.ndarray", person_boxes: list | None = None) -> str | None:
    """BGR 프레임 → JPEG data URL(증거 저장용).

    [P1a] 저장 직전에 얼굴을 비식별화한다 — 이 경로가 디스크에 남는 증거 이미지다.
    원본 frame 은 수정되지 않는다(privacy.anonymize_faces 가 사본을 만든다) → 검출 무영향.
    """
    safe = privacy.anonymize_faces(frame, person_boxes)
    ok, buf = cv2.imencode(".jpg", safe, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return ("data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()) if ok else None


def _derive(out: dict, zone: list, aspect_hw: float | None = None,
            cid: str | None = None, debouncer: "zone_debounce.ZoneDebouncer | None" = None,
            ) -> list[tuple[str, str, str]]:
    """guard.detect 출력 → 발화한 위험 [(rule, level, note)].

    [B6] 위험구역 침입은 **시간 디바운스**를 거친다(zone_debounce). PPE(3프레임)·화재(2프레임)엔
    히스테리시스가 있는데 침입만 없어서 단일 프레임 오검출이 곧 경보였다 — 파일럿의 유일한
    판매 기능이 이것이라 가장 먼저 막아야 한다. debouncer 가 None 이면 기존 즉시 발화(하위호환).
    """
    fired: list[tuple[str, str, str]] = []
    sig = out.get("signals", {}) or {}
    if zone and len(zone) >= 3:                       # 위험구역 침입
        raw_inside = False
        for d in out.get("detections", []):
            if str(d.get("label", "")).lower() != "person":
                continue
            # 판정 기준점: 기본 foot(박스 하단 중앙 = 지면 접점). config zone.reference 로 center 선택 가능
            #   — 직하방 카메라는 박스 하단이 발이 아닐 수 있다(docs/camera_requirements.md).
            px, py = zone_debounce.ref_point(d.get("bbox", [0, 0, 0, 0]))
            if _point_in_poly(px, py, zone):
                raw_inside = True
                break
        if debouncer is not None and cid is not None:
            was = debouncer.state(cid)["confirmed"]
            now_in = debouncer.update(cid, raw_inside)
            if now_in and not was:                    # 확정 진입 전이에서만 발화(체류 중 재발화는 쿨다운이 담당)
                fired.append(("zone_intrusion", "high", "위험구역 내 작업자 감지(체류 확정)"))
        elif raw_inside:                              # 디바운서 미주입 경로(하위호환)
            fired.append(("zone_intrusion", "high", "위험구역 내 작업자 감지"))
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


def _person_metrics(xy: "np.ndarray", cf: "np.ndarray", min_kp: float = 0.3) -> "dict[str, Any] | None":
    """사람 1명의 키포인트 → 중심점. None 이면 판단 불가(어깨·엉덩이 미검출)."""
    def gp(idxs: list) -> "np.ndarray | None":
        pts = [xy[j] for j in idxs if cf[j] >= min_kp]
        return np.mean(pts, axis=0) if pts else None
    sc = gp([5, 6])          # 어깨중심
    hc = gp([11, 12])        # 엉덩이중심
    if sc is None or hc is None:
        return None
    valid = [xy[j] for j in range(len(xy)) if cf[j] >= min_kp]
    xs = [p[0] for p in valid]
    ys = [p[1] for p in valid]
    return {"centroid": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)}


class _PoseModel:
    """RTMPose(rtmlib, Apache-2.0) 1회 로드(공유). person 박스(RF-DETR/guard) 주입 → 사람별 자세 지표.
    실패/박스없음 시 [](무중단). YOLOX 내장 검출은 기본 off — 박스는 guard.detect(person) 가 제공한다
    (T10c: ultralytics/AGPL 제거, top-down 입력은 RF-DETR person 박스).

    출력 계약은 기존과 동일(사람별 metrics dict + kp_xy/kp_cf) → ErgonomicsTracker 무변경."""

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
            except Exception:  # noqa: BLE001  로드 실패 → 포즈 기능만 비활성(탐지 무중단)
                self._failed = True
        if self._m is None or not boxes:
            return []
        try:
            ppl = self._m.persons(frame, bboxes=list(boxes))   # [(kp_xy[17,2] px, kp_cf[17])] · COCO-17
            out = []
            for xy, cf in ppl:
                m = _person_metrics(xy, cf, min_kp)   # 판정 로직 재사용(무수정)
                if m:
                    m["kp_xy"] = xy      # 원시 키포인트 가산(근골격계 레이어용).
                    m["kp_cf"] = cf
                    out.append(m)
            return out
        except Exception:  # noqa: BLE001
            return []


_posemodel = _PoseModel()


class ErgonomicsTracker:
    """근골격계 부담 자세 '지속' 추적(카메라별 상태). 순수 가산 — 탐지와 독립·불변.

    나쁜 자세(warn/bad)가 hold_sec(설정) 이상 '지속'될 때만 위험으로 본다(순간 자세는 무시 → 오탐 억제).
    포즈 추론 비용 억제: 최소 간격(_MIN_INTERVAL)으로만 평가한다(3초 지속 판정엔 충분). 트랙 id 가
    없으므로 중심점 매칭으로 사람별 상태를 잇는다(독립 트랙).
    임계값은 vision.yaml 에서 읽는다(하드코딩 금지). 키포인트 없음/에러 → [] 반환(무중단)."""

    MATCH = 0.18            # 사람 프레임간 매칭 거리(대각선 정규화)
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
    """사람 움직임 추적 → ① 장시간 무동작(쓰러짐·실신 의심, SOS) ② 급격한 이동(돌진·이상행동)."""
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
        # [B2/B3] 세션 세대 — 캡처를 (재)오픈할 때마다 +1. 검출 루프가 '어느 세션의 프레임인지'
        #   구분하는 기준이자, /health 가 재연결 빈도를 보는 지표.
        self.generation = 1
        self.dropped = 0               # 읽기 실패 누적(드롭) — /health 지표
        self._thread: threading.Thread | None = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open(self):
        # [T-E2E 잔여지연] FFmpeg RTSP 저지연 옵션 — 기본값은 리오더/지터 버퍼로 0.5~1s 고정
        #   지연을 만든다(시계 촬영 실측: grab-드레인 후에도 상수 ~1.35s 잔존의 유력 성분).
        #   nobuffer+low_delay+max_delay 0.5s 상한. setdefault 라 운영자가 환경변수로 덮어쓰기 가능.
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                              "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;500000")
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
            # [T-E2E 잔여지연] read() → grab-드레인 + retrieve. 시계 촬영 실측(2026-08-12)으로
            #   read() 단독은 고해상 H264 디코드(2304×1296)가 CPU 추론과 경합해 프레임 간격(15fps=66ms)을
            #   못 따라갔고, FFmpeg 큐가 자라며 프레임 나이가 1.17→1.64s 로 초당 ~0.09s 씩 증가했다.
            #   grab() 은 디코드 없이 큐에서 프레임을 꺼내므로(수 ms), 5ms 내에 연속 성공하는 동안
            #   = 버퍼 잔량 소진 중으로 보고 계속 비운 뒤 마지막 프레임만 retrieve(디코드 1회).
            #   → 디코드가 느려도 지연 누적 불가 + 디코드 횟수 감소(CPU↓). 라이브 프레임 대기 grab 은
            #   ~66ms 걸려 루프가 자연히 스트림 속도에 페이싱된다.
            ok = cap.grab()
            _drained = 0
            while ok and _drained < 60 and not self._stop.is_set():   # 상한 60(≈4s 분량) — 무한 드레인 방지
                _gt = time.time()
                more = cap.grab()
                if not more or (time.time() - _gt) > 0.020:   # 20ms 초과 = 큐 비었고 라이브 대기였음(5ms 는 TCP 지터에 과민 — 잔량 미소진)
                    ok = more or ok
                    break
                _drained += 1
            if ok:
                ok, frame = cap.retrieve()
            else:
                frame = None
            self.read_ms = round((time.time() - _rt) * 1000, 1)
            if not ok:
                read_fails += 1
                self.dropped += 1                     # [B2] 드롭 누적 — /health 지표
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
                    self.generation += 1              # [B3] 새 세션 — 이전 세대 프레임과 구분
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

    def __init__(self, detectors, zone, mtrack, etrack,
                 collect_on, collect_every, dataset_dir, name, source):
        self.detectors = detectors
        self.zone = zone
        self.mtrack = mtrack          # 무동작·급이동 추적
        self.etrack = etrack          # 근골격계 부담자세 지속(가산)
        self.collect_on = collect_on
        self.collect_every = collect_every
        self.dataset_dir = dataset_dir
        self.name = name
        self.source = source
        self.cooldown: dict[str, float] = {}
        self.evidence_cd: dict[str, float] = {}   # ②: rule별 증거저장(무거운 후속) 별도 쿨다운
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
        self._last_fired: list = []                          # 3.1b: 최신 발화 규칙명(zone_intrusion 등) — 대시보드 뱃지·전역경보
        self._last_det_ts = 0.0                              # 3.8: 최신 검출 갱신 시각(ms) — 확대뷰 ingest 간격 산출
        self._interval = 0.5                                 # 3.8: 가변 루프 간격(초). set_fps 로 포커스 부스트
        self._last_pose_ts = 0.0                             # 3.9: 최신 포즈 실행 시각 — 검출/포즈 주기 분리
        self._full_interval = 0.5                            # 3.12: 풀세트(person+ppe+fire) 검출 주기(초) — 이벤트 캐던스(불변)
        self._last_full_ts = 0.0                             # 3.12: 최신 풀세트 실행 시각
        self._last_nonperson: list = []                      # 3.12: 최신 비-person(ppe/fire) 박스 — person 고속 프레임에 지속
        self._last_nonperson_noppe: list = []                # [T-E2E 후속] PPE 제외 비-person — focus 중 표시용(PPE 는 :pf 고속 담당)
        self._pose_lock = threading.Lock()                   # 3.10: 포즈 스레드↔메인 공유 보호
        self._pose_input: tuple | None = None                # (frame, person_boxes, t0) 최신 — 포즈 스레드가 소비
        self._pose_events: list = []                         # 포즈 스레드가 낸 발화(rule,level,note) — 메인이 드레인
        self._pose_etrack: Any = None                        # 현 run 의 ErgonomicsTracker(포즈 스레드 전용 접근)
        self._pose_thread: threading.Thread | None = None
        # [B6] 위험구역 침입 시간 디바운스(카메라별 상태) — 단일 프레임 오검출 경보 차단
        self._zone_debouncer = zone_debounce.ZoneDebouncer()
        self.state: dict[str, Any] = {
            "running": False, "source": "", "name": "", "fps": 0,
            "frames": 0, "events": 0, "last_event": "", "error": ""}

    def start(self, guard, lock, source: str, name: str = "CAM", fps: float = 2.0,
              detectors: list | None = None, zone: list | None = None) -> dict:
        if self.state["running"]:
            return {"ok": False, "error": "이미 실행 중 — 먼저 중지하세요."}
        self._stop.clear()
        self._restart_req.clear()
        # [S2-수정] state["source"]는 status()/⟶ /worker/status·/workers API로 그대로 노출된다 —
        #   스모크 테스트로 실제 응답에 원본 RTSP 자격증명이 그대로 찍히는 걸 발견(기존엔 마스킹
        #   안 됨). 워커 스레드(연결용)에는 원본 source를 그대로 넘기고, state에는 마스킹만 저장.
        self.state.update({"running": True, "source": _mask_src(source), "name": name, "fps": fps,
                           "frames": 0, "events": 0, "last_event": "", "error": "",
                           "last_frame_ts": 0.0, "restarts": 0,
                           "reconnects": 0, "hangs": 0,   # 1단계 하트비트·재시작 + 2단계 재연결·hang 카운터
                           # [B2] 검출 생존 하트비트 — /health 3단계 판정 입력
                           "started_at": time.time(),     # [B2] 워커 기동 시각 — startup grace 기준
                           "last_detect_ts": 0.0,         # 추론 완료 벽시계(프레임 수신과 별개)
                           "last_detect_ms": None,        # 최근 추론 지연(ms)
                           "session_generation": 0,       # 캡처 세션 세대 — 재연결마다 +1
                           "dropped_frames": 0})          # 읽기 실패 누적
        self._thread = threading.Thread(
            target=self._run_supervised,      # 1단계: 감독자 경유(루프가 죽어도 재시작 — 무증상 실패 차단)
            args=(guard, lock, source, name, fps,
                  detectors or _default_detectors(), zone),
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

    def set_fps(self, fps: float) -> dict:
        """런타임 fps 변경(재시작 없이 루프 간격만) — 확대뷰 포커스 부스트/복원용(3.8)."""
        fps = max(0.2, float(fps))
        self._interval = 1.0 / fps
        self.state["fps"] = fps
        return {"ok": True, "fps": fps}

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
            s["session_generation"] = sc.generation      # [B2/B3]
            s["dropped_frames"] = sc.dropped             # [B2]
        # [B2] 검출 생존 — 프레임 수신(last_frame)과 추론 완료(last_detect)를 **따로** 노출한다.
        #   둘의 나이가 벌어지는 것이 P0(영상 생존·검출 사망)의 지문이다.
        ldt = s.get("last_detect_ts", 0.0)
        s["last_detect_secs_ago"] = round(time.time() - ldt, 1) if ldt else None
        sat = s.get("started_at", 0.0)
        s["uptime_s"] = round(time.time() - sat, 1) if sat else None   # [B2] grace 판정 기준
        # [E1] 단계 분해 계측은 state 에 이미 들어 있다(lock_wait_ms·infer_ms·read_ms) —
        #   status() 가 state 사본을 반환하므로 별도 처리 없이 그대로 노출된다.
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
            # [B4] startup grace — 워커 기동 직후 이 시간 안에는 hang 판정을 하지 않는다.
            #   모델 예열은 main 이 워커보다 먼저 끝내지만(readiness), 재연결·재시작 경로로
            #   들어온 워커는 여전히 초기화 비용을 떠안을 수 있어 유예를 둔다. 유예가 지나면
            #   _HANG_TIMEOUT(기본 15s)이 그대로 적용된다 — 임계를 느슨하게 바꾸지 않는다.
            sat = self.state.get("started_at", 0.0)
            if sat and (time.time() - sat) < _STARTUP_GRACE:
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
                # [S2-수정] source 인자는 이미 마스킹돼 있었으나, traceback.format_exc()는
                #   원본 문자열이라 예외 메시지 자체에 자격증명이 섞여 나올 수 있어(cv2/FFmpeg가
                #   URL을 에러 메시지에 그대로 넣는 경우가 흔함) 별도로 scrub 한다.
                tb = _scrub(traceback.format_exc())
                _WLOG.error("워커 '%s'(%s) _loop 예외 — 재시작 대상\n%s", name, _mask_src(source), tb)
                self.state["error"] = f"_loop crashed: {tb.splitlines()[-1]}"
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

    def _pose_loop(self):
        """포즈(ergo) 전용 스레드 — RTMPose(ONNXRuntime CPU). guard 는 MPS(PyTorch)라 서로 다른
        런타임·장치 → 병렬 안전(FINDINGS MPS 크래시는 PyTorch GPU 공유 문제; 이 스레드는 MPS 미접촉).
        pose_fps 로 최신 프레임을 소비, 결과(fired)는 _pose_lock 으로 안전 공유. 검출(메인 루프)과 독립 →
        검출 간격이 포즈에 안 밀린다(3.9→3.10)."""
        while not self._stop.is_set():
            time.sleep(0.03)
            if not self.state.get("running") or self._pose_etrack is None:
                continue
            now = time.time()
            if now - self._last_pose_ts < _POSE_MIN_INTERVAL:   # 고정 pose_fps(기존 자세 캐던스 유지)
                continue
            with self._pose_lock:
                inp = self._pose_input
            if not inp:
                continue
            frame, person_boxes, t0 = inp
            self._last_pose_ts = now
            fired: list = []
            try:
                fired += self._pose_etrack.update(frame, t0, person_boxes)   # 근골격계 부담자세(지속 확정분)
            except Exception:  # noqa: BLE001  가산 레이어
                pass
            if fired:
                with self._pose_lock:
                    self._pose_events.extend(fired)

    # [B2] 테스트 전용 결함 주입 — 검출만 멈추고 프레임 수신은 유지해 P0(stale_detect)를 재현한다.
    #   기본 False. 운영 기본값이 아니라 **명시 환경변수로만** 켜진다(scripts/test_health_fault_injection.py).
    fault_stop_detect = bool(os.environ.get("VIGENT_FAULT_STOP_DETECT"))

    def _process_frame(self, frame, t0, guard, lock, ctx: "_FrameCtx"):
        if self.fault_stop_detect:      # [B2] 주입된 결함: 추론을 건너뛴다 → last_detect_ts 가 늙는다
            return
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
            # 3.12 ②: 차등 캐던스. focus 중엔 person 전용 고속(표시·일관 tid, :pf 풀) + 풀세트 저속(이벤트·PPE·화재·pose).
            #   풀세트(person+ppe+fire) 캐던스는 fullset_fps(2) 불변 → 이벤트·안전 판정 저하 0(규칙6).
            #   person 전용은 단일 슬롯(~27ms)이라 focus 5fps 라도 GPU 예산이 5fps 풀세트(425ms/s)보다 낮다
            #   (focus 예산 ≈ 2×85[풀세트] + 5×27[person] = 305ms/s). focus 아니면 매 프레임 풀세트(기존과 동일).
            focus_active = self._interval < self._full_interval - 1e-6
            do_full = (not focus_active) or (t0 - self._last_full_ts >= self._full_interval - 0.06)
            _H, _W = frame.shape[:2]
            person_boxes: list = []
            out: dict = {}
            # [E1] 병목 특정용 계측 — 락 대기 시간과 추론 실행 시간을 **분리**해서 잰다.
            #   last_detect_ms(=완료−프레임시각)만으로는 "기다린 것"과 "도는 것"을 구분할 수 없어
            #   H2(추론 직렬화) 가설을 판정할 수 없다. 측정 전용이며 동작은 바꾸지 않는다.
            _wait0 = time.time()
            with lock:                            # 코어 추론 직렬화(브라우저와 충돌 방지)
                _lock_wait_ms = (time.time() - _wait0) * 1000.0
                _infer0 = time.time()
                self._last_frame = frame
                disp_person = None
                disp_ppe = None
                _main_person: list = []
                if focus_active:                  # person+PPE 고속(표시 전용) — :pf 풀로 focus fps 일관 tid
                    # [T-E2E 후속] PPE 도 고속 경로에 포함 — "PPE 박스 무리만 반 박자 늦게 따라오는"
                    #   체감(풀세트 2fps 캐던스, 최대 +500ms)을 해소. 표시 전용 상향이다:
                    #   ① 이 호출의 signals 는 버린다(아래에서 detections 만 사용)
                    #   ② 히스테리시스·트랙 상태는 track_key(:pf)별 격리(guard.py _hysteresis, line 793)
                    #   ③ 이벤트·판정 입력은 여전히 아래 do_full(풀세트 2fps) 결과만 → 판정 캐던스 불변(규칙6)
                    pout = guard.detect(frame, detectors=["person", "ppe"], track_key="cam:" + str(ctx.name) + ":pf")
                    _pd = pout.get("detections", [])
                    disp_person = [_det_dict(d) for d in _pd if d.get("label") == "person"]
                    disp_ppe = [_det_dict(d) for d in _pd if d.get("label") != "person"]
                if do_full:                       # 풀세트 — 2fps: 이벤트·PPE·화재·pose 입력(캐던스 불변)
                    self._last_full_ts = t0
                    out = guard.detect(frame, detectors=ctx.detectors, track_key="cam:" + str(ctx.name))
                    self._last_nonperson = [_det_dict(d) for d in out.get("detections", []) if d.get("label") != "person"]
                    # [T-E2E 후속] PPE 제외 비-person(fire·forklift 등) — focus 중 표시용(PPE 는 고속 경로가 담당)
                    self._last_nonperson_noppe = [_det_dict(d) for d in out.get("detections", [])
                                                  if d.get("label") != "person" and d.get("detector") != "ppe"]
                    _main_person = [_det_dict(d) for d in out.get("detections", []) if d.get("label") == "person"]
                    self._last_pc = out.get("person_count", 0)
                    self._last_sig = out.get("signals", {})
                    person_boxes = [[d["bbox"][0] * _W, d["bbox"][1] * _H, d["bbox"][2] * _W, d["bbox"][3] * _H]
                                    for d in out.get("detections", []) if d["label"] == "person"]
                # 표시 목록: focus 중 = person+PPE(고속 :pf, focus fps) + 나머지(fire 등, 풀세트 2fps)
                #           평시 = 풀세트 그대로(기존 동작 불변)
                if disp_person is not None:
                    self._last_dets = disp_person + (disp_ppe or []) + getattr(self, "_last_nonperson_noppe", [])
                else:
                    self._last_dets = _main_person + self._last_nonperson
                # 3.14 ①(T1): ts 를 '프레임 시각(t0)'으로 스탬프 — 완료시각(time.time)은 person/full 처리시간 차로
                #   불균일(sd↑)했다. t0 는 루프 간격(≈균일)이라 확대뷰 ingest 간격이 고르게 → 앨리어싱·지터↓.
                self._last_det_ts = t0
                # [B2] 검출 생존 하트비트 — '프레임 수신'과 별개로 '추론이 실제로 끝난' 시각을 벽시계로 남긴다.
                #   P0(영상은 살고 검출만 죽음)의 지문이 last_frame 은 신선한데 last_detect 만 늙는 것이라,
                #   두 시각을 따로 기록해야 /health 가 그 상태를 stale_detect 로 구분할 수 있다.
                _now = time.time()
                self.state["last_detect_ts"] = _now
                self.state["last_detect_ms"] = round((_now - t0) * 1000.0, 1)
                # [E1] 단계 분해: 락 대기 / 락 안 실행(추론+트래킹) / 프레임 획득(디코드 프록시)
                self.state["lock_wait_ms"] = round(_lock_wait_ms, 1)
                self.state["infer_ms"] = round((_now - _infer0) * 1000.0, 1)
            if not do_full:                       # person 전용 프레임: 이벤트·포즈 없음(안전 캐던스 불변) — 표시만 갱신
                return
            # 3.10 ①: 포즈(ergo)는 별도 스레드(ONNX-CPU)가 pose_fps 로 비동기 처리(풀세트 프레임에서만 입력 갱신).
            with self._pose_lock:
                self._pose_input = (frame, person_boxes, t0)
                _pose_ev = self._pose_events
                self._pose_events = []
            fired = _derive(out, ctx.zone, frame.shape[0] / frame.shape[1],
                            cid=str(ctx.name), debouncer=self._zone_debouncer)   # [B6] 침입 시간 디바운스
            fired += _pose_ev                                       # ergo(별도 스레드 산출) — 쿨다운은 아래 공통
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
            fired += ctx.mtrack.update(out.get("detections", []), t0)   # 무동작·급이동(포즈 무관 — 메인 유지)
            self._last_fired = [r[0] for r in fired]                # 3.1b: 이번 프레임 발화 규칙(뱃지·전역경보 근거)
            now = time.time()
            for rule, level, note in fired:
                if now - ctx.cooldown.get(rule, 0) < _COOLDOWN_S:
                    continue
                ctx.cooldown[rule] = now
                # ②: 이벤트 기록은 항상 유지. 증거 JPEG(인코딩+디스크)은 rule별 별도 쿨다운으로 스로틀 —
                #   폭주 오발화가 서버를 포화시키지 못하게. 안전 기능(발화·기록·알림)은 그대로.
                evidence = None
                if now - ctx.evidence_cd.get(rule, 0) >= _EVIDENCE_COOLDOWN_S:
                    ctx.evidence_cd[rule] = now
                    evidence = _frame_to_dataurl(frame, [d.get('bbox') for d in self._last_dets
                                                      if d.get('class') == 'person'])
                data_engine.log_event(rule=rule, level=level, site=ctx.name, note=note,
                                      image_data_url=evidence)
                self.state["events"] += 1
                self.state["last_event"] = f"{rule}({level})"
        except Exception as _fe:   # noqa: BLE001  프레임 처리 실패 → 로그 남기고 다음 프레임(루프 유지)
            # [S2-수정] str(_fe)에 자격증명이 섞여 나올 수 있어 scrub — state["error"]는 /worker/status로 그대로 노출됨
            self.state["error"] = _scrub(f"frame: {type(_fe).__name__}: {_fe}")
            _WLOG.error("워커 '%s'(%s) 프레임 처리 예외 — 계속 진행\n%s",
                        ctx.name, _mask_src(ctx.source), _scrub(traceback.format_exc()))

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
        mtrack = MotionTracker()                                       # 무동작·급이동 추적
        etrack = ErgonomicsTracker()                                   # 근골격계 부담자세 지속(가산)
        zone = [tuple(p) for p in zone] if zone else _load_zone()   # 카메라별 구역 or 전역
        ctx = _FrameCtx(detectors, zone, mtrack, etrack,
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
        self._interval = interval          # 3.8: 가변 간격 시드 — set_fps(포커스 부스트)가 런타임에 바꿈
        # 3.12: 풀세트 검출 주기 = fullset_fps(기본2) 또는 시작 fps 중 느린 쪽 → focus 로 루프가 빨라져도 불변.
        self._full_interval = max(interval, 1.0 / max(0.2, float(tuning.val("worker", "fullset_fps", 2.0))))
        self._last_full_ts = 0.0
        self._pose_etrack = ctx.etrack     # 3.10: 포즈 스레드가 쓸 현 run 트래커(ergo)
        if self._pose_thread is None or not self._pose_thread.is_alive():
            self._pose_thread = threading.Thread(target=self._pose_loop, daemon=True)
            self._pose_thread.start()
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
                    if ok:
                        # [E1] decode_ms: read() 실소요(측정 전용). **파일 소스에서는 네트워크가
                        #   없어 순수 디코드 비용에 가깝고**, 스트림 sync 모드에서는 네트워크
                        #   대기가 섞인다. 아래 read_ms 는 '스트림 신선도 프록시'라 의미가 달라
                        #   덮어쓰지 않고 별도 필드로 둔다(H1 판정용).
                        self.state["decode_ms"] = round((time.time() - _rt) * 1000, 1)
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
                                              name, _mask_src(source), self.state["reconnects"], rbackoff)
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
                if dt < self._interval and not self._stop.is_set():   # 3.8: 가변 간격(포커스 부스트)
                    time.sleep(self._interval - dt)
        except Exception as ex:                       # noqa: BLE001  루프 자체 예외 → supervised 가 재시작
            # [S2-수정] str(ex)·source·traceback 전부 자격증명이 섞여 나올 수 있어 scrub
            self.state["error"] = _scrub(f"{type(ex).__name__}: {ex}")
            _WLOG.error("워커 '%s'(%s) _loop 예외 — 감독자 재시작 위임\n%s",
                        name, _mask_src(source), _scrub(traceback.format_exc()))
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

    def set_fps(self, cam_id: str, fps: float) -> dict:
        w = self._workers.get(cam_id)
        if not w:
            return {"ok": False, "error": f"{cam_id} 없음"}
        return w.set_fps(fps)

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
