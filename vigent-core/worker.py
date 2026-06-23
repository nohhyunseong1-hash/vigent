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
import threading
import time
from pathlib import Path
from typing import Any

import cv2

import data_engine

_ROOT = Path(__file__).resolve().parent.parent
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_COOLDOWN_S = 15.0


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


def _derive(out: dict, zone: list) -> list[tuple[str, str, str]]:
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
    return fired


class Worker:
    """1대용 추론 워커(지연 시작·정지·상태). 서버 전역 싱글톤으로 사용."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state: dict[str, Any] = {
            "running": False, "source": "", "name": "", "fps": 0,
            "frames": 0, "events": 0, "last_event": "", "error": ""}

    def start(self, guard, lock, source: str, name: str = "CAM",
              fps: float = 2.0, detectors: list | None = None) -> dict:
        if self.state["running"]:
            return {"ok": False, "error": "이미 실행 중 — 먼저 중지하세요."}
        self._stop.clear()
        self.state.update({"running": True, "source": source, "name": name, "fps": fps,
                           "frames": 0, "events": 0, "last_event": "", "error": ""})
        self._thread = threading.Thread(
            target=self._loop,
            args=(guard, lock, source, name, fps,
                  detectors or ["person", "ppe", "forklift", "fire_smoke"]),
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

    def _loop(self, guard, lock, source, name, fps, detectors):
        interval = 1.0 / max(0.2, fps)
        cooldown: dict[str, float] = {}
        zone = _load_zone()
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
                with lock:                            # 코어 추론 직렬화(브라우저와 충돌 방지)
                    out = guard.detect(frame, detectors=detectors)
                now = time.time()
                for rule, level, note in _derive(out, zone):
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


worker = Worker()
