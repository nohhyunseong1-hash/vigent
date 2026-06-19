"""Guard — [감지] 실시간 탐지·추적·이벤트 발생 (§15 2번: 딥러닝 탐지 계층)

vision.yaml 의 detector 슬롯(person/ppe/forklift/fire_smoke)에서 실제 .pt 모델을
1회 로드해 캐시하고, 프레임 추론 → 박스·클래스·confidence 를 반환한다.

절대 저하 없음(§2-1):
  - 모델 로드/추론이 실패하면 해당 검출기만 비활성, 나머지는 정상 동작.
  - 모델이 아예 없으면(폴백 슬롯) 그 검출기는 건너뛴다. 프론트 휴리스틱이 보완.

라벨 정규화(D층 이슈):
  PPE 모델 실제 라벨은 'Safety Vest'/'NO-Safety Vest'(공백)인데, vision.yaml·판단 규칙은
  'Safety-Vest'/'NO-Safety-Vest'(하이픈)를 기대한다 → 여기서 표준 라벨로 통일한다.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from .base import BaseAgent

# 모델이 내보내는 원시 라벨 → VIGENT 표준 라벨(규칙이 비교하는 문자열)
LABEL_NORMALIZE = {
    "NO-Safety Vest": "NO-Safety-Vest",
    "Safety Vest": "Safety-Vest",
    "NO-Safety-Vest": "NO-Safety-Vest",
    "Safety-Vest": "Safety-Vest",
    "Hardhat": "Hardhat", "NO-Hardhat": "NO-Hardhat",
    "Fire": "fire",   # 화재 모델 대문자 → 표준 소문자
}
# PPE 미착용 판정에 쓰는 표준 라벨(안전모·조끼·마스크)
PPE_MISSING_LABELS = {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"}
# 잡음/무의미 클래스 — 그리지 않고 버림(예: fire 모델의 'default')
JUNK_LABELS = {"default"}


def _iou(a: list[float], b: list[float]) -> float:
    """두 bbox([x1,y1,x2,y2])의 IoU."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _nms(dets: list[dict[str, Any]], iou_thr: float = 0.55) -> list[dict[str, Any]]:
    """같은 라벨(대소문자 무시) 끼리 IoU 중복 제거 — 멀티모델/멀티스케일 중복 박스 정리."""
    out: list[dict[str, Any]] = []
    for d in sorted(dets, key=lambda x: x["conf"], reverse=True):
        key = d["label"].lower()
        if any(o["label"].lower() == key and _iou(o["bbox"], d["bbox"]) > iou_thr for o in out):
            continue
        out.append(d)
    return out


class GuardAgent(BaseAgent):
    name = "Guard"
    role = "감지: 실시간 탐지·추적·이벤트 스트림 생성"

    # ── 인식 강화 튜닝(한 곳에서 조정) ──
    DEFAULT_CONF = 0.30      # 임계값(낮을수록 많이 잡음)
    IMGSZ = 960              # 추론 해상도(클수록 작은 객체↑). 워밍업 후 ~250ms/회로 빠름
    TRACK_TTL = 1.2          # 서버 추적 유지시간(초). 프론트 간격(600ms)보다 길게 → 깜빡임 제거
    TRACK_IOU = 0.45         # 같은 객체로 볼 겹침 기준
    EMA = 0.5                # 박스 위치 스무딩(0~1, 클수록 새 위치 빨리 반영). 떨림 완화

    def __init__(self, config: Any):
        super().__init__(config)
        self._models: dict[str, Any] = {}      # id → YOLO (지연 로드 캐시)
        self._load_errors: dict[str, str] = {}
        self._tracks: list[dict[str, Any]] = []  # 서버측 추적 박스(깜빡임 제거)
        # config.slots 에서 실제 .pt 파일로 해석된 detector 슬롯만 추린다
        self._slot_path: dict[str, str] = {}
        for s in config.slots:
            if s.slot in ("person", "ppe", "forklift", "fire_smoke") and s.source == "model" and s.active:
                self._slot_path[s.slot] = s.active

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "detectors_available": list(self._slot_path.keys()),
                "loaded": list(self._models.keys()),
                "load_errors": self._load_errors}

    def _track(self, fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """서버측 추적/스무딩: 새 탐지를 기존 트랙과 IoU 매칭해 갱신(위치 EMA 평활),
        새것은 추가, TTL 지난 트랙은 제거. 잠깐 놓친 프레임에도 박스를 유지해 깜빡임 제거."""
        now = time.time()
        for f in fresh:
            best, best_iou = None, self.TRACK_IOU
            for t in self._tracks:
                if t["label"].lower() == f["label"].lower():
                    i = _iou(t["bbox"], f["bbox"])
                    if i >= best_iou:
                        best, best_iou = t, i
            if best is not None:
                # 위치 EMA 평활(떨림 완화) — 새 bbox 를 일부만 반영
                a = self.EMA
                best["bbox"] = [round(best["bbox"][k] * (1 - a) + f["bbox"][k] * a, 4)
                                for k in range(4)]
                best["conf"] = f["conf"]
                best["detector"] = f["detector"]
                best["raw_label"] = f.get("raw_label", best.get("raw_label"))
                best["seen"] = now
            else:
                f = dict(f); f["seen"] = now
                self._tracks.append(f)
        # TTL 만료 제거(유령 박스 방지)
        self._tracks = [t for t in self._tracks if now - t["seen"] <= self.TRACK_TTL]
        # 반환은 seen 등 내부필드 빼고 깔끔하게
        return [{k: v for k, v in t.items() if k != "seen"} for t in self._tracks]

    def _get_model(self, slot: str):
        """슬롯 모델을 1회 로드해 캐시. 실패하면 None(해당 검출기만 비활성)."""
        if slot in self._models:
            return self._models[slot]
        path = self._slot_path.get(slot)
        if not path:
            return None
        try:
            from ultralytics import YOLO
            self._models[slot] = YOLO(path)
            return self._models[slot]
        except Exception as ex:  # noqa: BLE001  로드 실패해도 죽지 않는다
            self._load_errors[slot] = f"{type(ex).__name__}: {ex}"
            self._models[slot] = None
            return None

    def detect(self, image_bgr: np.ndarray, detectors: list[str] | None = None,
               conf: float | None = None) -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 라벨·confidence·정규화 bbox(0~1) 목록 + 파생 신호.

        image_bgr: cv2 BGR numpy 배열
        detectors: 돌릴 검출기 id 목록(기본 person·ppe·forklift; fire 는 명시 시)
        """
        conf = self.DEFAULT_CONF if conf is None else conf
        want = detectors or ["person", "ppe", "forklift", "fire_smoke"]
        h, w = image_bgr.shape[:2]
        detections: list[dict[str, Any]] = []
        used: list[str] = []

        for slot in want:
            model = self._get_model(slot)
            if model is None:
                continue
            try:
                # 해상도 ↑(imgsz) 단일 추론 — 작은/먼 객체 회복(멀티스케일 crop 대비 가벼움)
                res = model.predict(image_bgr, verbose=False, conf=conf, imgsz=self.IMGSZ)[0]
            except Exception as ex:  # noqa: BLE001  추론 실패해도 나머지 진행
                self._load_errors[slot] = f"predict: {type(ex).__name__}: {ex}"
                continue
            used.append(slot)
            names = model.names
            for b in res.boxes:
                cls_id = int(b.cls[0])
                raw = names.get(cls_id, str(cls_id))
                label = LABEL_NORMALIZE.get(raw, raw)
                if label in JUNK_LABELS:        # 'default' 등 잡음 클래스 버림
                    continue
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                detections.append({
                    "detector": slot,
                    "label": label, "raw_label": raw,
                    "conf": round(float(b.conf[0]), 3),
                    # 정규화 bbox(0~1) — 프론트가 캔버스 크기에 맞춰 그림
                    "bbox": [round(x1 / w, 4), round(y1 / h, 4),
                             round(x2 / w, 4), round(y2 / h, 4)],
                })

        # 여러 모델/클래스 간 중복 박스 정리 → 서버측 추적으로 안정화(깜빡임 제거)
        detections = _nms(detections)
        detections = self._track(detections)

        # 파생 신호(딥러닝 → 규칙 가산용)
        person_count = sum(1 for d in detections if d["label"].lower() == "person")
        ppe_missing_hits = [d for d in detections if d["label"] in PPE_MISSING_LABELS]
        # ppe_conf: 미착용 탐지 최고 confidence(있으면 Analyst 가산용으로 전달)
        ppe_conf = max((d["conf"] for d in ppe_missing_hits), default=0.0)
        # 화재·연기 탐지(보조 신호 — §8: 인증 화재경보 대체 아님)
        fire_hits = [d for d in detections if d["label"].lower() in ("fire", "smoke")]
        fire_conf = max((d["conf"] for d in fire_hits), default=0.0)

        return {
            "detectors_used": used,
            "person_count": person_count,
            "detections": detections,
            "signals": {
                "ppe_missing": bool(ppe_missing_hits),
                "ppe_conf": ppe_conf,
                "forklift_present": any(d["label"].lower() == "forklift" for d in detections),
                "fire_smoke": bool(fire_hits),
                "fire_conf": fire_conf,
            },
        }
