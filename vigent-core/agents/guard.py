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
from pathlib import Path as _Path
from typing import Any

import numpy as np

from .base import BaseAgent

# 프로젝트 루트(VIGENT) — guard.py = <root>/vigent-core/agents/guard.py → 세 단계 위.
#   vision.yaml 의 rfdetr_weights 는 이 루트 기준 상대경로(예: vigent-core/weights/ppe_rfdetr_v1.pth).
#   서버는 cwd=vigent-core 로 기동되므로, 상대경로를 그대로 쓰면 cwd 기준 이중경로로 깨진다(F-8).
#   → 반드시 이 상수 기준으로 절대경로화한다.
_PROJECT_ROOT = _Path(__file__).resolve().parent.parent.parent


def _sha16(path) -> str:
    """가중치 파일 SHA256 앞 16자(로드 로그·매니페스트 대조용). 실패해도 죽지 않는다."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return "??"


def _guard_logger():
    """vlog 우선(없으면 표준 logging). 슬롯 로드 상태 가시화(F-8)."""
    try:
        import sys
        sys.path.insert(0, str(_PROJECT_ROOT / "vigent-core"))
        import vlog
        return vlog.get("vigent.guard")
    except Exception:  # noqa: BLE001
        import logging
        return logging.getLogger("vigent.guard")

# 모델이 내보내는 원시 라벨 → VIGENT 표준 라벨(규칙이 비교하는 문자열)
LABEL_NORMALIZE = {
    "NO-Safety Vest": "NO-Safety-Vest",
    "Safety Vest": "Safety-Vest",
    "NO-Safety-Vest": "NO-Safety-Vest",
    "Safety-Vest": "Safety-Vest",
    "Hardhat": "Hardhat", "NO-Hardhat": "NO-Hardhat",
    "Fire": "fire",   # 화재 모델 대문자 → 표준 소문자
    "Person": "person", "PERSON": "person",   # PPE모델 'Person' ↔ COCO 'person' 통일(중복 박스 방지)
    "Forklift": "forklift", "Smoke": "smoke",
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


def _center_near(a: list[float], b: list[float], frac: float) -> bool:
    """두 bbox 중심 거리가 (평균 대각선 × frac) 이하인가 — 빠른 이동으로 IoU 가 낮아도 동일 객체 판정용(1.9)."""
    acx, acy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    bcx, bcy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    dist = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
    diag = (((a[2] - a[0]) ** 2 + (a[3] - a[1]) ** 2) ** 0.5
            + ((b[2] - b[0]) ** 2 + (b[3] - b[1]) ** 2) ** 0.5) / 2
    return diag > 0 and dist <= frac * diag


def _nms(dets: list[dict[str, Any]], iou_thr: float = 0.55) -> list[dict[str, Any]]:
    """같은 라벨(대소문자 무시) 끼리 IoU 중복 제거 — 멀티모델/멀티스케일 중복 박스 정리."""
    out: list[dict[str, Any]] = []
    for d in sorted(dets, key=lambda x: x["conf"], reverse=True):
        key = d["label"].lower()
        if any(o["label"].lower() == key and _iou(o["bbox"], d["bbox"]) > iou_thr for o in out):
            continue
        out.append(d)
    return out


_COCO_VEHICLES = {"bus", "truck", "car", "train", "boat"}


def _suppress_vehicle_dupes(dets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """지게차로 더 정확히 잡힌 물체를 COCO가 '버스/트럭'으로 오인한 중복 박스 제거."""
    forks = [d for d in dets if d["label"].lower() == "forklift"]
    if not forks:
        return dets
    return [d for d in dets if not (
        d["label"].lower() in _COCO_VEHICLES
        and any(_iou(d["bbox"], f["bbox"]) > 0.45 for f in forks))]


# 교차소스 person 병합 임계(item: box-overlay 안 B). _nms 기본 IoU 0.55 와 TRACK_IOU 0.45 의
#   불일치로 IoU 0.45~0.55 구간이 새어, 같은 사람이 person 슬롯 + ppe 슬롯('Person')에 각각 잡히면
#   박스가 2개로 남는다. 이 값(0.45)은 추적 매칭 기준(TRACK_IOU)과 일치시켜 그 누수 구간을 덮는다.
MERGE_PERSON_IOU = 0.45


def _merge_cross_source_person(dets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """추적 이후 후처리(안 B): **서로 다른 모델 소스(detector)**가 같은 사람을 각각 잡아 생긴
    person 중복 박스만 병합. 검출·_nms·추적은 건드리지 않는다(미탐 위험 최소).

    병합 조건(모두 충족해야):
      ① 라벨이 person 인 박스끼리만  ② detector(모델 슬롯)가 **서로 다를 때만**
      ③ IoU ≥ MERGE_PERSON_IOU(0.45)
    → **같은 소스(같은 detector)는 절대 병합하지 않는다** — 진짜 두 사람일 수 있으므로(안전).
    남길 박스: **confidence 높은 쪽**(conf 내림차순으로 먼저 확정한 박스를 유지, 이후 교차소스 중복은 드롭).
    person 외 클래스(ppe·fire 등)는 그대로 통과."""
    persons = [d for d in dets if str(d.get("label", "")).lower() == "person"]
    others = [d for d in dets if str(d.get("label", "")).lower() != "person"]
    keep: list[dict[str, Any]] = []
    for d in sorted(persons, key=lambda x: x.get("conf", 0.0), reverse=True):
        # 이미 확정(keep)한 박스 중 '다른 소스 + 충분히 겹침'이 있으면 이 박스는 그 중복 → 드롭
        if any(k.get("detector") != d.get("detector")
               and _iou(k["bbox"], d["bbox"]) >= MERGE_PERSON_IOU for k in keep):
            continue
        keep.append(d)
    return others + keep


class GuardAgent(BaseAgent):
    name = "Guard"
    role = "감지: 실시간 탐지·추적·이벤트 스트림 생성"

    # ── 인식 강화 튜닝(한 곳에서 조정) ──
    DEFAULT_CONF = 0.30      # 임계값(낮을수록 많이 잡음)
    # 검출기별 임계값 — 사람은 낮게(잘 잡되), 건설모델(PPE·지게차·화재)은 높게(실내 오탐 컷).
    # 화재는 오경보가 치명적이라 가장 높게. 명시 conf 가 오면 그걸 우선.
    DETECTOR_CONF = {"person": 0.35, "ppe": 0.55, "forklift": 0.55, "fire_smoke": 0.70}
    IMGSZ = 960              # 추론 해상도(클수록 작은 객체↑). 워밍업 후 ~250ms/회로 빠름
    TRACK_TTL = 1.2          # 서버 추적 유지시간(초). 프론트 간격보다 길게 → 깜빡임 제거
    TRACK_IOU = 0.45         # 같은 객체로 볼 겹침 기준
    EMA = 0.75               # 박스 위치 스무딩(0~1, 클수록 새 위치 빨리 반영). 0.5→0.75: 움직임 추종↑(현장 반응성)
    MIN_HITS = 1             # 1=즉시 표시(움직이는 객체도 바로 보임). 헛것은 임계값으로 거름
    # 잔상 제거(옵션 B): 이번 프레임에 새 탐지가 없는(미매칭) 트랙이 이 프레임 수를 넘기면 즉시 폐기.
    #   1 = 1프레임 놓침은 브리지(깜빡임 방지), 2번째 연속 미매칭에 삭제 → 사람 이탈 후 옛 박스 ~2프레임 내 소멸.
    #   (기존엔 TRACK_TTL=1.2s 동안 미매칭 트랙을 계속 진짜 박스로 반환 → 잔상·빈 벽 PPE 오탐.
    #    이제 TTL 은 '프레임이 뜸할 때'를 위한 절대 백스톱으로만 유지.)
    # ✅ 스트림별 트랙 격리(5단계): _tracks 를 track_key 별 dict(self._tracks_by_key)로 분리.
    #    worker=카메라명(cam:<name>) · /detect/frame=요청 track_key(기본 browser) · 기타=default.
    #    → 다중 카메라/브라우저/오프라인 분석이 서로 트랙을 오염(잔상·유령·타카메라 명의 오발화)하지 않음.
    STALE_MAX_MISSES = 1
    # 보호구 클래스별 임계(후필터) — ppe 모델을 맵 최저 conf로 추론한 뒤 클래스별 임계로 거른다.
    #   최약체(NO-Hardhat)만 낮춰 재현율↑, 나머지는 유지. tuning.yaml detect.conf.ppe_per_class 로 조정.
    #   비어 있으면(기본) 기존 동작(단일 ppe conf) 그대로 → 저하 없음.
    PPE_PER_CLASS: dict[str, float] = {}
    # 화재/연기 클래스별 후필터 임계(T14-F, F-6 완화) — fire·smoke 는 confidence 분포가 달라
    #   단일 임계로 둘 다 만족 불가(smoke 는 낮추면 오검출 급증). tuning.yaml detect.conf.fire_smoke_per_class.
    #   비어 있으면(기본) 단일 fire_smoke 임계 그대로 → 저하 없음.
    FIRE_SMOKE_PER_CLASS: dict[str, float] = {}

    def __init__(self, config: Any):
        super().__init__(config)
        # 현장 튜닝값(config/tuning.yaml)으로 conf·해상도 덮기(없으면 클래스 기본값)
        try:
            import tuning
            conf_cfg = tuning.section("detect").get("conf") or {}
            # *_per_class 는 검출기 임계가 아니라 클래스별 후필터 맵(dict) → DETECTOR_CONF 병합에서 제외
            _per_class_keys = ("ppe_per_class", "fire_smoke_per_class")
            self.DETECTOR_CONF = {**self.DETECTOR_CONF,
                                  **{k: v for k, v in conf_cfg.items() if k not in _per_class_keys}}
            # 클래스별 후필터 맵(라벨 표준화해서 저장) — 예: {"NO-Hardhat":0.30, "NO-Mask":0.50, ...}
            self.PPE_PER_CLASS = {LABEL_NORMALIZE.get(str(k), str(k)): float(v)
                                  for k, v in (conf_cfg.get("ppe_per_class") or {}).items()}
            # 화재/연기 클래스별 후필터 맵(T14-F) — 예: {"fire":0.03, "smoke":0.20}
            self.FIRE_SMOKE_PER_CLASS = {LABEL_NORMALIZE.get(str(k), str(k)): float(v)
                                         for k, v in (conf_cfg.get("fire_smoke_per_class") or {}).items()}
            self.IMGSZ = int(tuning.val("detect", "imgsz", self.IMGSZ))
            self.STALE_MAX_MISSES = int(tuning.val("detect", "stale_max_misses", self.STALE_MAX_MISSES))
            self.EMA = float(tuning.val("detect", "ema", self.EMA))   # 위치 평활 주입 가능(기본 0.75 불변 · 1.8b B-2 측정용)
        except Exception:  # noqa: BLE001
            pass
        self._models: dict[str, Any] = {}      # id → YOLO (지연 로드 캐시)
        self._load_errors: dict[str, str] = {}
        self._tracks_by_key: dict[str, list[dict[str, Any]]] = {}  # 서버측 추적 박스(track_key 별 격리 · 5단계)
        self._tid_seq: int = 0                    # 트랙 안정 id 시퀀스(클라 id 매칭용 · 1.8b)
        self.device = self._pick_device()        # GPU(MPS) 있으면 사용 → 추론 4배↑
        # config.slots 에서 실제 .pt 파일로 해석된 detector 슬롯만 추린다
        self._slot_path: dict[str, str] = {}
        for s in config.slots:
            if s.slot in ("person", "ppe", "forklift", "fire_smoke") and s.source == "model" and s.active:
                self._slot_path[s.slot] = s.active
        # 슬롯별 검출 백엔드(vision.yaml perception.backend). 기본 'yolo'(기존 동작 = 저하0).
        #   'yolo'=ultralytics(.pt, AGPL) / 'rfdetr'=RF-DETR(Apache). T10a: person→rfdetr 이관.
        self._backend: dict[str, str] = {}
        try:
            self._backend = dict((getattr(config, "raw", {}) or {})
                                 .get("perception", {}).get("backend", {}) or {})
        except Exception:  # noqa: BLE001  설정 없으면 전부 yolo 폴백
            pass
        # rfdetr 백엔드용 커스텀 파인튜닝 가중치(T10b). 없는 슬롯(person 등)은 COCO 사전학습 사용.
        #   vision.yaml perception.rfdetr_weights: {forklift: vigent-core/weights/forklift_rfdetr_v1.pth}
        #   → F-8: 상대경로를 프로젝트루트 기준 절대경로화하고, '지정됐는데 파일 부재'면 기동 거부.
        self._rfdetr_weights: dict[str, str] = {}
        try:
            _raw_rfw = dict((getattr(config, "raw", {}) or {})
                            .get("perception", {}).get("rfdetr_weights", {}) or {})
        except Exception:  # noqa: BLE001  설정 없음 → 빈 맵(person 등 COCO 사전학습 경로)
            _raw_rfw = {}
        # 절대경로화 + 실파일 검증 + 로드 로그. 커스텀 부재 시 예외를 그대로 올려 기동을 거부(silent 폴백 차단).
        self._rfdetr_weights = self._resolve_rfdetr_weights(_raw_rfw)

    @staticmethod
    def _pick_device() -> str:
        """추론 장치 선택(단일 소스 device.pick_device 사용, 감사 C-2).
        YOLO는 macOS MPS 다회추론 크래시가 관찰돼 prefer_mps=False(맥=CPU). CUDA는 사용.
        속도가 필요하고 위험 감수 시 VIGENT_DETECT_DEVICE=mps 로 강제."""
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import device as _device
        return _device.pick_device(prefer_mps=False)

    def _resolve_rfdetr_weights(self, raw: dict) -> dict[str, str]:
        """rfdetr 커스텀 가중치 경로를 절대경로화 + 실파일 검증 + 로드 로그(F-8).

        - 경로 지정 + 파일 존재  → 절대경로로 반환(LOADED 로그, SHA 대조).
        - 경로 지정 + 파일 부재  → 기본은 FileNotFoundError(기동 거부, silent 폴백 차단).
              VIGENT_ALLOW_FALLBACK=1 opt-in 시에만 COCO 사전학습으로 폴백(검출저하 경고).
        - 경로 미지정(person 등) → 반환 맵에 없음 → _get_model 이 rf_w='' 로 COCO 사용(정상·저하0).
        """
        import os
        log = _guard_logger()
        allow_fb = os.environ.get("VIGENT_ALLOW_FALLBACK") == "1"
        out: dict[str, str] = {}
        self._rfdetr_status: list[dict[str, Any]] = []
        for slot, ref in (raw or {}).items():
            if not ref:
                continue
            backend = self._backend.get(slot, "yolo")
            p = _Path(ref)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p                    # ← 핵심 수정(F-8): 프로젝트루트 기준 절대화
            if p.exists():
                sha = _sha16(p)
                out[slot] = str(p)
                self._rfdetr_status.append({"slot": slot, "backend": backend,
                                            "weights": str(p), "sha16": sha, "state": "LOADED"})
                log.info("검출 슬롯: slot=%s backend=%s weights=%s sha=%s → LOADED",
                         slot, backend, p.name, sha)
            elif allow_fb:
                self._rfdetr_status.append({"slot": slot, "backend": backend,
                                            "weights": str(p), "sha16": None, "state": "MISSING_FALLBACK"})
                log.warning("검출 슬롯 MISSING(opt-in 폴백): slot=%s weights=%s → COCO 사전학습 폴백"
                            "(커스텀 검출을 COCO로 대체 → 검출 저하 가능)", slot, p)
                # out 에 넣지 않음 → rf_w='' → COCO 사전학습
            else:
                self._rfdetr_status.append({"slot": slot, "backend": backend,
                                            "weights": str(p), "sha16": None, "state": "MISSING"})
                log.error("검출 슬롯 MISSING(기동 거부): slot=%s weights=%s", slot, p)
                raise FileNotFoundError(
                    f"[기동거부·F-8] rfdetr 커스텀 가중치 부재: slot={slot} path={p}. "
                    f"파일을 배치하거나 VIGENT_ALLOW_FALLBACK=1 로 COCO 폴백을 명시 허용하라"
                    f"(폴백은 커스텀 검출을 COCO로 대체 → 검출 저하). silent 폴백은 차단됨.")
        return out

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "detectors_available": list(self._slot_path.keys()),
                "loaded": list(self._models.keys()),
                "load_errors": self._load_errors,
                "rfdetr_slots": getattr(self, "_rfdetr_status", [])}   # F-8: 커스텀 가중치 실검사 결과

    def _track(self, fresh: list[dict[str, Any]], track_key: str = "default") -> list[dict[str, Any]]:
        """서버측 추적/스무딩: 새 탐지를 기존 트랙과 IoU 매칭해 갱신(위치 EMA 평활),
        새것은 추가, TTL 지난 트랙은 제거. 잠깐 놓친 프레임에도 박스를 유지해 깜빡임 제거.

        track_key(카메라 id 등)별로 트랙 상태를 분리 — 여러 카메라/브라우저/오프라인 분석이 한
        _tracks 를 공유하면 A 카메라 박스가 B 결과에 섞이고(잔상·유령), fire/ppe 신호가 다른
        카메라 명의로 오발화된다(F-리뷰 5단계). 키를 안 주면 'default' 로 기존 동작 유지."""
        now = time.time()
        tracks = self._tracks_by_key.setdefault(track_key, [])   # 키별 격리 상태
        used: set[int] = set()   # 감사 E-2: 한 트랙에 복수 검출이 중복 매칭돼 인원 과소집계되던 문제 → 1:1 강제
        for f in fresh:
            best, best_iou = None, self.TRACK_IOU
            for t in tracks:
                if id(t) in used:
                    continue                       # 이번 프레임에 이미 매칭된 트랙은 제외
                if t["label"].lower() == f["label"].lower():
                    i = _iou(t["bbox"], f["bbox"])
                    if i >= best_iou:
                        best, best_iou = t, i
            if best is None:
                # 2차 완화 매칭(1.9 수정1): 1차 IoU(TRACK_IOU=0.45) 탈락 검출을, 같은 라벨 미매칭 트랙과
                #   IoU≥0.25 또는 중심거리≤대각선40% 면 이어붙임(새 트랙 금지) → 빠른 이동 분열 원천 감소.
                #   TRACK_IOU 자체는 안 낮춤(전 소비자 영향). used 1:1 강제 유지.
                cand, cand_iou = None, -1.0
                for t in tracks:
                    if id(t) in used or t["label"].lower() != f["label"].lower():
                        continue
                    i2 = _iou(t["bbox"], f["bbox"])
                    if (i2 >= 0.25 or _center_near(t["bbox"], f["bbox"], 0.40)) and i2 > cand_iou:
                        cand, cand_iou = t, i2
                best = cand
            if best is not None:
                used.add(id(best))
                # 위치 EMA 평활(떨림 완화) — 새 bbox 를 일부만 반영
                a = self.EMA
                best["bbox"] = [round(best["bbox"][k] * (1 - a) + f["bbox"][k] * a, 4)
                                for k in range(4)]
                best["conf"] = f["conf"]
                best["detector"] = f["detector"]
                best["raw_label"] = f.get("raw_label", best.get("raw_label"))
                best["seen"] = now
                best["hits"] = best.get("hits", 1) + 1   # 연속 확인 횟수 증가
                best["misses"] = 0                        # 이번 프레임에 매칭됨 → 미매칭 카운터 리셋
            else:
                f = dict(f); f["seen"] = now; f["hits"] = 1; f["misses"] = 0
                f["tid"] = self._tid_seq; self._tid_seq += 1   # 안정 id 부여(매칭 시 EMA 갱신돼도 불변)
                tracks.append(f)
                used.add(id(f))          # 새 트랙도 같은 프레임 내 재매칭 방지
        # 이번 프레임에 매칭/신규가 아닌(미매칭) 트랙은 연속 미매칭 횟수 증가
        for t in tracks:
            if id(t) not in used:
                t["misses"] = t.get("misses", 0) + 1
        # 잔상 제거(옵션 B): 연속 미매칭이 STALE_MAX_MISSES 초과면 즉시 폐기(사람 이탈→옛 박스 ~2프레임 내 소멸).
        #   + TRACK_TTL 은 프레임이 뜸할 때를 위한 절대 백스톱으로 병행 유지.
        tracks = [t for t in tracks
                  if t.get("misses", 0) <= self.STALE_MAX_MISSES and now - t["seen"] <= self.TRACK_TTL]
        self._tracks_by_key[track_key] = tracks   # 필터 결과 반영(키별)
        # MIN_HITS 이상 '확인된' 트랙만 표시(한 프레임 헛것 제거). 내부필드(seen·hits·misses)는 빼고 반환
        return [{k: v for k, v in t.items() if k not in ("seen", "hits", "misses")}
                for t in tracks if t["hits"] >= self.MIN_HITS]

    def _get_model(self, slot: str):
        """슬롯 검출기(어댑터)를 1회 로드해 캐시. 실패하면 None(해당 검출기만 비활성).

        백엔드는 self._backend[slot]('yolo' 기본 / 'rfdetr'):
          · yolo   — ultralytics YOLO(.pt). _slot_path 의 경로 필요.
          · rfdetr — RF-DETR(Apache). COCO 사전학습으로 충분한 클래스(person)는 경로 불필요.
        반환 어댑터는 detect(image_bgr, conf, imgsz, augment) → 표준 박스 목록(base 계약)."""
        if slot in self._models:
            return self._models[slot]
        backend = self._backend.get(slot, "yolo")
        path = self._slot_path.get(slot)
        if backend == "yolo" and not path:
            return None
        try:
            if backend == "rfdetr":
                from detectors.rfdetr_adapter import RfdetrDetector
                # person 등 COCO 클래스는 사전학습(rf_w="")으로 충분. forklift 등 T10b 파인튜닝은
                #   perception.rfdetr_weights 의 커스텀 .pth 를 주입(자체 클래스 공간 → 어댑터가 class_names 로 매핑).
                rf_w = self._rfdetr_weights.get(slot, "")
                self._models[slot] = RfdetrDetector(rf_w, LABEL_NORMALIZE, JUNK_LABELS)
            else:
                from detectors.yolo_adapter import YoloDetector
                self._models[slot] = YoloDetector(path, self.device, self.IMGSZ,
                                                  LABEL_NORMALIZE, JUNK_LABELS)
            return self._models[slot]
        except Exception as ex:  # noqa: BLE001  로드 실패해도 죽지 않는다
            self._load_errors[slot] = f"{type(ex).__name__}: {ex}"
            self._models[slot] = None
            return None

    def detect(self, image_bgr: np.ndarray, detectors: list[str] | None = None,
               conf: float | None = None, imgsz: int | None = None,
               augment: bool = False, track_key: str = "default") -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 라벨·confidence·정규화 bbox(0~1) 목록 + 파생 신호.

        image_bgr: cv2 BGR numpy 배열
        detectors: 돌릴 검출기 id 목록(기본 person·ppe·forklift; fire 는 명시 시)
        imgsz: 추론 해상도 override(None=기본 self.IMGSZ). 오프라인 정밀분석은 높게(예 1280).
        augment: TTA(다중스케일·좌우반전 추론). 오프라인에서 True → 정확도↑·느림(실시간 금지).
        """
        conf_override = conf      # None 이면 검출기별 임계(DETECTOR_CONF) 사용
        # 기본은 '범용' 검출기(person=yolo11s, COCO 80종)만 — 어디서든 일상 사물 정확 인식.
        # 건설 전용(ppe·forklift·fire_smoke)은 사무실/실내에서 오탐을 일으키므로 기본 off.
        #   → 건설현장에서 쓸 때만 detectors=["person","ppe","forklift","fire_smoke"] 로 명시 호출.
        want = detectors or ["person"]
        h, w = image_bgr.shape[:2]
        detections: list[dict[str, Any]] = []
        used: list[str] = []

        for slot in want:
            model = self._get_model(slot)
            if model is None:
                continue
            slot_conf = conf_override if conf_override is not None else self.DETECTOR_CONF.get(slot, self.DEFAULT_CONF)
            # 클래스별 후필터 맵(ppe·fire_smoke): 맵의 최저 임계로 추론해 후보 확보 → 아래 박스 루프에서 클래스별로 거른다.
            per_class = (self.PPE_PER_CLASS if slot == "ppe"
                         else self.FIRE_SMOKE_PER_CLASS if slot == "fire_smoke" else {})
            run_conf = slot_conf
            if per_class:
                run_conf = min([slot_conf, *per_class.values()])
            try:
                # 어댑터가 모델추론 + 라벨정규화 + bbox정규화까지 → 표준 박스 반환(백엔드 불가지).
                #   해상도 ↑(imgsz) + (오프라인) TTA + 검출기별 임계(건설모델은 높게 → 오탐 컷).
                boxes = model.detect(image_bgr, conf=run_conf,
                                     imgsz=imgsz or self.IMGSZ, augment=augment)
            except Exception as ex:  # noqa: BLE001  추론 실패해도 나머지 진행
                self._load_errors[slot] = f"predict: {type(ex).__name__}: {ex}"
                continue
            used.append(slot)
            for d in boxes:
                # 클래스별 임계 후필터(ppe·fire_smoke): 맵에 있으면 그 임계, 없으면 slot_conf 로 거른다.
                #   ppe: 착용 클래스는 slot_conf 유지, NO-* 만 개별 임계. fire_smoke: fire·smoke 각각(T14-F).
                #   ※ 라벨정규화·JUNK 버림·bbox정규화는 어댑터(finalize_box)에서 이미 수행 → 기존과 동일.
                if per_class and d["conf"] < per_class.get(d["label"], slot_conf):
                    continue
                d["detector"] = slot
                detections.append(d)

        # 여러 모델/클래스 간 중복 박스 정리 → 서버측 추적으로 안정화(깜빡임 제거)
        detections = _nms(detections)
        detections = _suppress_vehicle_dupes(detections)   # 지게차↔버스 오인 중복 제거
        detections = self._track(detections, track_key)
        # 안 B(box-overlay): 추적 이후, 교차소스(person 슬롯↔ppe 슬롯) person 중복만 병합.
        #   _nms(0.55)↔TRACK_IOU(0.45) 임계 불일치가 남긴 IoU 0.45~0.55 person 이중박스 해소.
        #   같은 소스는 병합 안 함(진짜 두 사람 보호). 검출·nms·추적 로직은 불변.
        detections = _merge_cross_source_person(detections)

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
