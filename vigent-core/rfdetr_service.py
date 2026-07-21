"""rf-detr 백엔드 서비스 — 웹 화면이 호출하는 탐지·추적·위험구역·VLM (permissive).

- 모델은 1회 로드해 재사용(서버 수명 동안).
- detect(): 프레임 → rf-detr 사람탐지 → ByteTrack 추적 → 위험구역 침입 판정.
- summarize(): 이벤트 프레임 → mlx-vlm 위험요약 JSON(무겁고 느림, 프론트가 드물게 호출).
전부 로컬·permissive(rfdetr/trackers Apache-2.0, supervision/mlx-vlm MIT).
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Any

import numpy as np
import runtime_config
from app_state import DETECT_LOCK  # F-14: 네이티브 추론 직렬화(RLock) — MPS 다모델 동시추론 크래시 차단
from web_util import zone_points

ROOT = Path(__file__).resolve().parent.parent


def _load_zone_and_threshold(theme: str = "safety"):
    """vision.yaml + danger_zone.json 에서 위험구역(정규화 폴리곤)·임계값.
    ※ worker._load_zone(config/danger_zone.json 직접·튜플만)과 이름·계약이 달라 P2-11에서
      명확히 rename(동명이인 혼동 제거). 공통 점추출만 web_util.zone_points 로 공유."""
    import yaml
    vy = yaml.safe_load(open(ROOT / "themes" / theme / "vision.yaml", encoding="utf-8"))
    jud = vy.get("judgment", {}) or {}
    thr = float(jud.get("detect_threshold", 0.4))
    zpath = (jud.get("zones", {}) or {}).get("danger_zones")
    pts = []
    if zpath:
        zp = runtime_config.read_path(zpath)   # B2: 런타임(data/) 우선 → config/ 시드 폴백
        if zp.exists():
            z = json.load(open(zp, encoding="utf-8"))
            pts = zone_points(z)
    return pts, thr


def _point_in_poly(x, y, poly) -> bool:
    """점(x,y)이 폴리곤(픽셀좌표 Nx2) 내부인지 — ray casting."""
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


class RFDetrService:
    """rf-detr 탐지 + 추적 + 위험구역. 지연 로드 싱글톤."""

    def __init__(self):
        self._model = None
        self._tracker = None

    def _ensure(self):
        if self._model is not None:
            return
        import device as _device
        from rfdetr import RFDETRNano
        from trackers import ByteTrackTracker
        dev = _device.pick_device(prefer_mps=True)   # 감사 C-1: CUDA→MPS→CPU (리눅스서 GPU 사용)
        self._model = RFDETRNano(device=dev)
        try:
            self._model.optimize_for_inference()
        except Exception:  # noqa: BLE001
            pass
        # F-8(item4, 2026-07-21): SORTTracker→ByteTrackTracker. 크레인 다중작업자 A/B 실측상 SORT 는
        #   실 ~5명을 39 ID 로 단편화(단편화 3.9·ID스위치 13), ByteTrack 은 5 ID·0 스위치로 안정
        #   (tools/track_quality.py). zone_intrusion 침입자 식별 정확도 직결. 파라미터는 기본값 유지
        #   (lost_track_buffer=30·frame_rate=30·track_activation_threshold=0.7·minimum_iou_threshold=0.1
        #    ·high_conf_det_threshold=0.6·minimum_consecutive_frames=2) — 현장 튜닝은 P3 백로그.
        self._tracker = ByteTrackTracker()
        self.device = dev

    def detect(self, image_bgr: np.ndarray) -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 bbox·라벨·id 목록 + 위험구역 침입."""
        with DETECT_LOCK:   # F-14: 네이티브 추론 직렬화
            self._ensure()
            import cv2
            import supervision as sv
            from PIL import Image
            from rfdetr.util.coco_classes import COCO_CLASSES

            h, w = image_bgr.shape[:2]
            pts, thr = _load_zone_and_threshold("safety")   # 매 프레임 설정 반영(화면서 구역 바꾸면 즉시)
            det = self._model.predict(
                Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)), threshold=thr)
            # 추적: ByteTrack 으로 프레임 간 track id 부여(침입자 식별). 감사 A: 과거엔 생성만 하고
            # 호출하지 않아 id 가 항상 -1이었음 → 실제 update 로 배선. 실패/빈 결과면 raw 탐지 유지(폴백).
            try:
                tracked = self._tracker.update(det)
                if tracked is not None and len(tracked) > 0:
                    det = tracked
            except Exception:  # noqa: BLE001  추적 실패해도 탐지는 유지(절대 저하 없음)
                pass
            tids = getattr(det, "tracker_id", None)
            names = [COCO_CLASSES[c] for c in det.class_id]   # 80종 전부 유지(사람만 거르지 않음)

            # 위험구역 침입은 '사람'에만 적용 → 좌표가 구역 안인지 판정
            zone = None
            if len(pts) >= 3:
                zone = sv.PolygonZone(polygon=(np.array(pts) * [w, h]).astype(int))
                zone.trigger(det)            # 내부 카운트 갱신(개별 마스크는 아래서 직접 계산)
            poly = (np.array(pts) * [w, h]) if len(pts) >= 3 else None

            def _in_zone(box):
                if poly is None:
                    return False
                cx, cy = (box[0] + box[2]) / 2, box[3]          # 발 위치(하단 중앙)
                return bool(_point_in_poly(cx, cy, poly))

            out, n_in, ids_in = [], 0, []
            for i in range(len(det)):
                label = names[i]
                x1, y1, x2, y2 = (float(v) for v in det.xyxy[i])
                tid = int(tids[i]) if tids is not None and tids[i] is not None else -1
                inz = (label == "person") and _in_zone((x1, y1, x2, y2))
                if inz:
                    n_in += 1
                    if tid >= 0:
                        ids_in.append(tid)
                out.append({
                    "label": label,
                    "conf": round(float(det.confidence[i]), 2),
                    "id": tid,
                    "in_zone": inz,
                    "bbox": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                })
            person_count = sum(1 for d in out if d["label"] == "person")
            return {"detections": out, "person_count": person_count,
                    "intrusion": {"count": n_in, "ids": ids_in},
                    "device": getattr(self, "device", "?")}

    def detect_persons(self, image_bgr: np.ndarray, thr: float = 0.1) -> list[dict[str, Any]]:
        """저임계 person 검출(정규화 bbox·무추적) — B9 위험구역 타일 재검출 전용 가산 경로.
        ★지연 로드: 호출 시에만 _ensure()(모델 로드). 안 부르면 로드·메모리 영향 0.
        ★이종 검출기 주의: 일반 detect()/guard 검출기와 별개인 RF-DETR 저임계 경로다.
          반환 conf 는 RF-DETR 척도이므로 guard(YOLO 등) conf 와 직접 비교 불가."""
        with DETECT_LOCK:   # F-14: 네이티브 추론 직렬화
            self._ensure()
            import cv2
            from PIL import Image
            from rfdetr.util.coco_classes import COCO_CLASSES
            h, w = image_bgr.shape[:2]
            det = self._model.predict(
                Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)), threshold=thr)
            out = []
            for i in range(len(det)):
                if COCO_CLASSES[det.class_id[i]] != "person":
                    continue
                x1, y1, x2, y2 = (float(v) for v in det.xyxy[i])
                out.append({"label": "person", "conf": round(float(det.confidence[i]), 3),
                            "bbox": [x1 / w, y1 / h, x2 / w, y2 / h]})
            return out


class _PinnedRunner:
    """단일 전용 데몬 스레드에서만 작업을 실행한다(호출 스레드는 결과를 기다림).

    ★F-14 근본 해소(2026-07-20, benchmarks/FINDINGS.md 참조): mlx-vlm(Apple MLX) 추론을
    FastAPI 의 '수명 짧은' 워커 스레드(anyio threadpool)에서 돌리면, 그 스레드가 teardown 될 때
    네이티브 MLX 스레드가 GIL 없이 파이썬을 호출해 프로세스가 즉사한다(`PyThreadState_Get`, exit 133).
    격리 실험으로 확정: 검출(PyTorch-MPS) 단독=생존 · VLM(MLX) 단독=크래시 · 고정스레드 경유=생존.
    → 모든 VLM 추론을 '수명=프로세스 전체'인 이 스레드에서만 실행해 스레드 teardown 자체를 없앤다.
    DETECT_LOCK 직렬화(검출과 상호배제)는 호출 스레드가 그대로 잡으므로(RLock 재진입 유지) 이 스레드는
    락을 건드리지 않는다(교차 데드락 없음)."""

    def __init__(self, name: str):
        self._q: queue.Queue = queue.Queue()
        self._t = threading.Thread(target=self._loop, name=name, daemon=True)
        self._t.start()

    def _loop(self):
        while True:
            fn, args, kw, ev, box = self._q.get()
            try:
                box[0] = fn(*args, **kw)
            except BaseException as e:  # noqa: BLE001  호출 스레드로 그대로 전파
                box[1] = e
            ev.set()

    def run(self, fn, *args, **kw):
        ev = threading.Event()
        box: list = [None, None]
        self._q.put((fn, args, kw, ev, box))
        ev.wait()
        if box[1] is not None:
            raise box[1]
        return box[0]


# VLM(MLX) 전용 고정 스레드 — F-14. 모든 mlx-vlm 실행은 반드시 이 스레드에서만.
_VLM_RUNNER = _PinnedRunner("vigent-vlm")


class VLMService:
    """mlx-vlm 위험요약. 지연 로드 싱글톤(무겁다). 실제 MLX 실행은 _VLM_RUNNER(고정 스레드)에서만(F-14)."""

    def __init__(self):
        self._vlm = None

    def _ensure(self):
        """RiskVLM(MLX 모델) 로드 — _VLM_RUNNER 스레드에서만 호출되어야 한다(F-14)."""
        if self._vlm is None:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent / "ml"))
            from vlm_risk_summary import RiskVLM
            self._vlm = RiskVLM()

    def _summarize_impl(self, image_bgr, prompt, max_tokens, enrich, facts):
        import os

        import cv2
        self._ensure()
        # 고유 파일명(PID) — 동시요청이 서로의 프레임을 덮어써 오분석하는 레이스 방지(감사 E-3/C-4)
        tmp = Path("/tmp") / f"vigent_vlm_event_{os.getpid()}.jpg"
        cv2.imwrite(str(tmp), image_bgr)
        return self._vlm.summarize(str(tmp), prompt=prompt, max_tokens=max_tokens,
                                   enrich=enrich, facts=facts)

    def summarize_bgr(self, image_bgr: np.ndarray, prompt: str | None = None,
                      max_tokens: int = 260, enrich: bool = True,
                      facts: str | None = None) -> dict[str, Any]:
        # DETECT_LOCK 은 호출 스레드가 잡아 검출(PyTorch-MPS)과 상호배제 + worker RLock 재진입 유지.
        # 실제 MLX 추론은 _VLM_RUNNER(고정 데몬 스레드)에서만 — 워커스레드 teardown 크래시 제거(F-14).
        with DETECT_LOCK:
            return _VLM_RUNNER.run(self._summarize_impl, image_bgr, prompt, max_tokens, enrich, facts)

    def _quick_impl(self, image_bgr, prompt, max_tokens, max_side):
        import os

        import cv2
        self._ensure()
        tmp = Path("/tmp") / f"vigent_vlm_quick_{os.getpid()}.jpg"
        cv2.imwrite(str(tmp), image_bgr)
        return self._vlm.quick(str(tmp), prompt, max_tokens=max_tokens, max_side=max_side)

    def quick_bgr(self, image_bgr: np.ndarray, prompt: str,
                  max_tokens: int = 64, max_side: int = 640) -> dict[str, Any]:
        """빠른 단발 질의(PPE 등 단답) — 작은 이미지·짧은 토큰·재시도 없음."""
        with DETECT_LOCK:
            return _VLM_RUNNER.run(self._quick_impl, image_bgr, prompt, max_tokens, max_side)


# 서버 전역 싱글톤
rfdetr = RFDetrService()
vlm = VLMService()


def vlm_text(image_bgr, prompt: str, **kwargs) -> str | None:
    """VLM 텍스트 추론 → 원문 텍스트(str) 또는 None (P1-6 공통 헬퍼).

    14개 호출부에 흩어져 반복되던 3요소를 흡수한다:
      ① 지역 import·호출  ② _error/dict-아님 가드  ③ raw 추출('raw' 우선, 없으면 비-'_' 값 join).
    실패·미가용·빈 결과는 전부 None → 호출자가 규칙 기반으로 폴백(절대 저하 없음).
    kwargs 는 summarize_bgr 로 전달(max_tokens·enrich·facts 등). 구조화 JSON 이 필요한 호출부는
    이 텍스트를 받아 각자 파싱한다(요약: dict 파싱은 호출부 책임)."""
    if image_bgr is None:
        return None
    try:
        data = vlm.summarize_bgr(image_bgr, prompt=prompt, **kwargs)
    except Exception:  # noqa: BLE001  VLM 미가용/실패 → None(폴백)
        return None
    if not isinstance(data, dict) or data.get("_error"):
        return None
    txt = str(data.get("raw") or " ".join(str(v) for k, v in data.items()
                                          if not str(k).startswith("_"))).strip()
    return txt or None
