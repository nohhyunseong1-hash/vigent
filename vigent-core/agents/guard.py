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

import os
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

# ByteTrack(Phase2) tid 네임스페이스 오프셋 — GuardAgent._track_bytetrack 참조.
_BYTETRACK_TID_OFFSET = 10_000_000


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


def _ensure_core_on_path() -> None:
    """`vigent-core/` 를 sys.path 에 **1회·멱등**으로 올린다(CODE_REVIEW M1-1).

    guard.py 는 서버(cwd=vigent-core) 외에 저장소 루트의 unittest·tools/ 스크립트·NSSM 서비스
    (cwd·env 상이)에서도 import 된다 — cwd 가정을 하지 않고 경로를 보장하되, 예전처럼 호출마다
    `sys.path.insert` 를 반복하면 경로가 무한 증가한다(실측: 100회 호출 → 7→107 항목).
    """
    import sys
    core = str(_PROJECT_ROOT / "vigent-core")
    if core not in sys.path:
        sys.path.insert(0, core)


_LOG = None              # 1회 해석 후 캐시(M1-1) — 호출마다 import·경로 삽입을 반복하지 않는다
_LOG_BACKEND = ""        # "vlog" | "logging" — 어느 쪽이 잡혔는지 진단용(테스트·status)


def _guard_logger():
    """vlog 우선(없으면 표준 logging). 슬롯 로드 상태 가시화(F-8).

    폴백은 **조용히 하지 않는다**: vlog 를 못 올리면 표준 logging 으로 WARNING 1줄을 남긴다 —
    그래야 파일 로테이션(vlog) 없이 도는 상태가 로그에 드러난다.
    """
    global _LOG, _LOG_BACKEND
    if _LOG is not None:
        return _LOG
    import logging
    try:
        _ensure_core_on_path()
        import vlog
        _LOG = vlog.get("vigent.guard")
        _LOG_BACKEND = "vlog"
    except Exception as ex:  # noqa: BLE001
        _LOG = logging.getLogger("vigent.guard")
        _LOG_BACKEND = "logging"
        _LOG.warning("vlog 미사용, 표준 logging 폴백(%s: %s) — 파일 로테이션 로그가 안 남는다",
                     type(ex).__name__, ex)
    return _LOG

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


def _area(b: list[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a: list[float], b: list[float]) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return iw * ih


def _containment_suppress(dets: list[dict[str, Any]], min_ratio: float = 0.70) -> list[dict[str, Any]]:
    """같은 라벨 박스 쌍에서 '작은 박스가 큰 박스에 min_ratio 이상 포함(교집합/작은면적)'되고
    작은 박스 conf ≤ 큰 박스 conf 면 작은 쪽 제거 — 모션블러/근접이 만든 중첩 유령 정리(1.9d).
    NMS 는 IoU(교집합/합집합) 기준이라 큰 박스 안에 든 작은 박스(IoU 낮음)를 못 지운다 → 포함비로 보완.
    ※트레이드오프: 앞사람이 뒷사람 박스에 포함되는 실제 2인 겹침에서 앞(작은)사람은 통상 conf 가 높아
      살아남지만, 뒷사람 conf 가 더 높은 드문 경우 앞사람이 지워질 수 있다. conf 조건이 유일 안전장치."""
    n = len(dets)
    if n < 2:
        return dets
    drop = [False] * n
    for i in range(n):
        ai = _area(dets[i]["bbox"])
        for j in range(n):
            if i == j or drop[i] or drop[j]:
                continue
            if dets[i]["label"].lower() != dets[j]["label"].lower():
                continue
            aj = _area(dets[j]["bbox"])
            if not (ai < aj):            # i 가 '엄격히 더 작은' 박스일 때만(동률은 skip → 이중제거 방지)
                continue
            if ai <= 0 or (_inter(dets[i]["bbox"], dets[j]["bbox"]) / ai >= min_ratio
                           and dets[i]["conf"] <= dets[j]["conf"]):
                drop[i] = True
    return [d for k, d in enumerate(dets) if not drop[k]]


def _cross_validate_ppe(dets: list[dict[str, Any]], expand: float = 0.15) -> list[dict[str, Any]]:
    """교차 검증 게이트(Phase C): PPE(detector=='ppe', NO-* 포함) 박스는 사람과 결부될 때만 유지.
    유지 조건 = person 박스와 IoU>0(겹침) 또는 PPE 중심이 person 박스를 expand(15%) 확장한 영역 안.
    사람이 아예 없으면 PPE 전부 폐기 → 벽·의자·모니터에 뜨는 PPE 오탐 제거(라이브·워커·이벤트 공통 혜택).
    ※미착용(NO-*) 재현율 불변: 진짜 미착용은 그 사람 몸에 겹쳐 잡히므로 person 과 결부돼 살아남는다."""
    ppe = [d for d in dets if d.get("detector") == "ppe"]
    if not ppe:
        return dets
    persons = [d for d in dets if str(d.get("label", "")).lower() == "person"]
    non_ppe = [d for d in dets if d.get("detector") != "ppe"]
    if not persons:
        return non_ppe            # 사람 없음 → PPE 전부 폐기
    kept: list[dict[str, Any]] = []
    for d in ppe:
        b = d["bbox"]; cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        for p in persons:
            pb = p["bbox"]; ew = (pb[2] - pb[0]) * expand; eh = (pb[3] - pb[1]) * expand
            if (_inter(b, pb) > 0
                    or (pb[0] - ew <= cx <= pb[2] + ew and pb[1] - eh <= cy <= pb[3] + eh)):
                kept.append(d)
                break
    return non_ppe + kept


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


def _drop_ppe_origin_person(dets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """[P-2] person 이중 신호 앙상블 off(PERSON_ENSEMBLE=False) 전용 필터. ppe 슬롯 유래
    person 라벨 후보(detector=='ppe' and label=='person')를 제거해 person 슬롯 자체 검출만
    남긴다. cross_validate_ppe 이후·_track 이전에 호출(다른 PPE 항목 결부 판정엔 영향 없고,
    추적 상태가 ppe 유래 박스로 오염되기 전에 걸러냄)."""
    return [d for d in dets
            if not (str(d.get("label", "")).lower() == "person" and d.get("detector") == "ppe")]


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
    # 속도 적응형 EMA(2.2 ①): 중심 이동량 d 가 클수록 a→EMA_MAX(고속=raw 즉각추종), 작으면 EMA_MIN(강한 평활).
    #   D_REF = 새 박스 대각선 × EMA_DREF. 저속·정지는 EMA_MIN(=현행 0.75)이라 저하 0.
    EMA_MIN = 0.75
    EMA_MAX = 1.0
    EMA_DREF = 0.25
    MIN_HITS = 1             # 1=즉시 표시(움직이는 객체도 바로 보임). 헛것은 임계값으로 거름
    # 잔상 제거(옵션 B): 이번 프레임에 새 탐지가 없는(미매칭) 트랙이 이 프레임 수를 넘기면 즉시 폐기.
    #   1 = 1프레임 놓침은 브리지(깜빡임 방지), 2번째 연속 미매칭에 삭제 → 사람 이탈 후 옛 박스 ~2프레임 내 소멸.
    #   (기존엔 TRACK_TTL=1.2s 동안 미매칭 트랙을 계속 진짜 박스로 반환 → 잔상·빈 벽 PPE 오탐.
    #    이제 TTL 은 '프레임이 뜸할 때'를 위한 절대 백스톱으로만 유지.)
    # ✅ 스트림별 트랙 격리(5단계): _tracks 를 track_key 별 dict(self._tracks_by_key)로 분리.
    #    worker=카메라명(cam:<name>) · /detect/frame=요청 track_key(기본 browser) · 기타=default.
    #    → 다중 카메라/브라우저/오프라인 분석이 서로 트랙을 오염(잔상·유령·타카메라 명의 오발화)하지 않음.
    STALE_MAX_MISSES = 1
    CONTAIN_RATIO = 0.70     # 포함비 억제 문턱(1.9d): 작은 박스가 큰 박스에 이 비율 이상 포함+conf 낮으면 제거
    PPE_PERSON_EXPAND = 0.15  # 교차게이트 문턱(Phase C): PPE 는 person 박스 이 비율 확장 영역과 결부돼야 유지
    # [Q-3, 2026-08-10] 검출 실패(백엔드 예외) 침묵 방지: 슬롯이 연속 이 횟수 이상 실패하면
    #   DEGRADED로 표시(/health 노출). "멀쩡해 보이는데 아무것도 안 보는" 상태가 안전 제품에서
    #   최악의 고장 모드라 — 1회 일시적 예외로 과민반응하지 않게 N=3(연속 3프레임)으로 잡았다.
    PREDICT_FAIL_DEGRADE_THRESHOLD = 3
    # [F31] 로드 실패는 재시도가 없어 매 프레임 반복된다 — 임계 초과 후 로그 주기(프레임 수).
    #   2fps 기준 1200프레임 ≈ 10분마다 1줄(디스크 보호).
    LOAD_FAIL_LOG_EVERY = 1200

    # [P-2, 2026-08] person 이중 신호 앙상블: ppe 슬롯 자체의 Person 클래스를 person 검출에 포함할지.
    #   True(기본) = 오늘까지의 실제 동작 그대로(person+ppe 슬롯을 함께 부르면 ppe 의 Person 검출도
    #   이미 무조건 섞여 들어왔다 — 이 플래그는 새 동작을 추가하는 게 아니라 그 기존 동작에
    #   이름을 붙이고 끌 수 있게 한 것). dev 74장 실측(benchmarks/p2_person_ensemble.md):
    #   재현율 55.4%→70.7%(+15.3%p) 정밀도 89.7%→79.9%(-9.8%p) F1 68.5%→75.0%(+6.5%p) → 채택 권고.
    #   False = person 슬롯 자체 검출만 person 으로 인정(교차검증/실험용 — 예: run_eval.py 로 "person
    #   모델 단독 성능"을 다시 재고 싶을 때). config/tuning.yaml detect.person_ensemble 로 조정.
    PERSON_ENSEMBLE = True
    HYSTERESIS_FRAMES = {"ppe_missing": 3, "fire_smoke": 2}  # 신호 히스테리시스(Phase C item2): 연속 N프레임 확인 후 발화(N=1=끔)
    # 보호구 클래스별 임계(후필터) — ppe 모델을 맵 최저 conf로 추론한 뒤 클래스별 임계로 거른다.
    #   최약체(NO-Hardhat)만 낮춰 재현율↑, 나머지는 유지. tuning.yaml detect.conf.ppe_per_class 로 조정.
    #   비어 있으면(기본) 기존 동작(단일 ppe conf) 그대로 → 저하 없음.
    # 보호구 경보로 볼 '미착용' 라벨. 기본은 기존 3종(회귀 0). tuning `ppe.required` 로 바꾼다.
    #   예: 마스크를 빼려면  ppe: { required: ["NO-Hardhat", "NO-Safety-Vest"] }
    PPE_REQUIRED: set = set(PPE_MISSING_LABELS)
    PPE_CONFIG_WARN = ""      # 설정이 무시·부분무시됐을 때 사유(빈 문자열 = 정상)
    PPE_PER_CLASS: dict[str, float] = {}
    # 화재/연기 클래스별 후필터 임계(T14-F, F-6 완화) — fire·smoke 는 confidence 분포가 달라
    #   단일 임계로 둘 다 만족 불가(smoke 는 낮추면 오검출 급증). tuning.yaml detect.conf.fire_smoke_per_class.
    #   비어 있으면(기본) 단일 fire_smoke 임계 그대로 → 저하 없음.
    FIRE_SMOKE_PER_CLASS: dict[str, float] = {}

    # ── 추적 알고리즘 선택(Phase2, 다인·가림·빠른이동 A/B) — 기본 iou(회귀 0 보장), opt-in bytetrack ──
    #   tuning.yaml track.algo: "iou"(기본, 위 IoU+중심점 그리디매칭 그대로) | "bytetrack"(trackers 패키지의
    #   ByteTrackTracker, Apache-2.0 — 칼만필터 모션예측 + 고신뢰/저신뢰 2단계 매칭 + 전역최적할당).
    #   bytetrack 은 person 슬롯에만 적용(ByteTrackTracker 는 클래스 비구분이라 다른 클래스와 섞으면
    #   오매칭 위험 — person 외 클래스는 algo 무관하게 항상 기존 _track_iou). 근거: benchmarks/
    #   track_fragmentation_causes.md(Phase1.5) — 파편화 원인 중 매칭경합·IoU붕괴가 칼만+전역할당으로
    #   개선될 가능성 확인.
    TRACK_ALGO = "iou"
    # 0.10 은 multi_scene.mp4 실측에서 노이즈 폭증(프레임당 confirmed tid 20개+, 실인원 4~6명 대비)이
    #   확인돼 기각. 실측 conf 분포(같은 클립): 진짜 사람 0.54~0.92 vs 배경노이즈 0.29 이하로 자연스러운
    #   갭 존재 → 0.28 채택(DETECTOR_CONF['person']=0.35 바로 아래, 노이즈 범람 없이 저신뢰 후보만 추가 확보).
    BYTETRACK_LOW_CONF = 0.28        # bytetrack 모드에서 person 슬롯 추론 임계(저신뢰 후보 확보용, 1회 추론 그대로)
    BYTETRACK_HIGH_CONF = 0.50       # ByteTrackTracker 고신뢰/저신뢰 분리 기준(1차매칭 대상)
    # ★[P2a, 2026-08-18] 환산식 확정(라이브러리 소스 직접 확인 —
    #   trackers/core/bytetrack/tracker.py:88):
    #       maximum_frames_without_update = int(frame_rate / 30.0 * lost_track_buffer)
    #   현재 값(frame_rate=10, buffer=30) → **10프레임** 유지. 실측 캐던스 2.3fps 에서 약 4.3초.
    #
    #   ★그런데 실카메라 시험(2026-08-13)에서 11.55초 부재 후에도 같은 id 가 복원됐다 — 모순이다.
    #   원인을 코드로 확인했다: `_track_bytetrack` 은 person 검출이 0건이면 **bt.update() 를
    #   호출하지 않고 early return** 한다. 즉 사람이 화면에 없는 동안 **트래커의 시간이 멈춘다**.
    #   버퍼가 만료되지 않으므로 부재 시간이 아무리 길어도 id 가 유지된다(실증:
    #   update(empty) 20회 → 새 id / update 미호출 → 동일 id).
    #
    #   ⇒ 따라서 이 값은 "부재 후 id 유지 시간"을 좌우하지 못한다. 실제로 유지 시간을 정하는 것은
    #     '사람이 보이는 동안의 순간적 미검출'에만 적용되는 프레임 수다. 값 자체는 바꾸지 않는다
    #     (바꿔도 부재 시나리오 동작이 달라지지 않고, 순간 미검출 허용치만 흔들려 회귀 위험).
    #     구조적 개선(빈 프레임에도 update 호출)은 백로그 PQ 로 분리 — 동작이 바뀌므로 별도 검증 필요.
    BYTETRACK_FRAME_RATE = 10.0
    BYTETRACK_LOST_BUFFER = 30       # 트랙 유지 프레임 수(위 frame_rate 기준 환산됨 — 라이브러리 기본값)
    BYTETRACK_MIN_IOU = 0.10         # ByteTrack 자체 매칭 IoU 최저선(라이브러리 기본값)
    # 신규 트랙 스폰에 필요한 최소 confidence. **None = person 운용 임계(DETECTOR_CONF['person'])에 자동 연동**
    #   (tuning track.bytetrack_activation 로 명시하면 그 값이 우선).
    #   ★[PA, 2026-08-13] 하드코딩 0.70(라이브러리 기본값)이었을 때 실제 회귀가 발생했다: person 운용
    #   임계는 0.40인데 스폰 자격만 0.70이라, conf 0.40~0.70 구간의 **실제 작업자**가 트랙을 못 얻어
    #   person_count 가 2.20→1.97(-10.3%)로 떨어졌다(검출 단계는 conf≥0.40 497/497 프레임 완전 동일 —
    #   순수 트래커 정책 손실). 육안 확인: benchmarks/results/pa_verify/zoom_tid27_f89.jpg(배후 작업자),
    #   zoom_tid44_f321.jpg(철근 아래 다리). 분석: benchmarks/pa_person_count_{verify,cause}.py.
    #   두 임계가 따로 노는 것이 원인이었으므로 값을 바꾸는 대신 **참조를 연결**한다 — 이후 운용 임계를
    #   튜닝하면 스폰 자격이 자동으로 따라온다.
    # ★[B-passthru] 추적이 버린 고신뢰 person 을 되살리는 임계. **0 = 비활성(기존 동작)**.
    #   tuning `track.passthrough_conf` 로 주입. 되살린 박스는 tid 가 없으므로
    #   zone.grid_cells(위치 기반 대체 키)와 **함께** 켜야 경보까지 닿는다.
    PASSTHROUGH_CONF = 0.0
    BYTETRACK_ACTIVATION: float | None = None
    BYTETRACK_MIN_FRAMES = 1         # 트랙 확정(tid 부여)까지 필요한 연속매칭 수. guard MIN_HITS=1 과 동일하게
                                      # 맞춰 "확정까지 프레임 수" 자체는 회귀 없게(라이브러리 기본 2 아님).

    # ── track_key 정리(F-2, 2026-08) — 클라이언트가 주는 값이 그대로 _tracks_by_key 키가 되는 경로
    #   (예: /safety/voice/scene 의 session_id)의 무한 증식 방지. cam:<name> 처럼 유한한 키는 이 청소의
    #   영향을 사실상 안 받는다(계속 쓰이는 키는 매번 last_used 가 갱신돼 TTL 에 안 걸림 — 아래 _track 참고).
    KEY_TTL_SEC = 300.0        # 유휴 5분 → 정리. TRACK_TTL(개별 트랙 만료)=1.2s 이므로 5분 유휴 키 안의
                               #   트랙은 이미 전부 만료된 상태 — 되살아날 정보가 없다. 재생성 비용은
                               #   _track_iou 의 setdefault 1회(≈0)라 짧게 잡아도 손해가 없다(사용자 지시,
                               #   "왜 5분인가"는 이 주석이 답).
    MAX_TRACKED_KEYS = 10_000   # 하드 백스톱 — TTL 정리로도 못 막는 폭증(비정상 트래픽) 대비. 정상 배포
                               #   에서는 절대 안 닿는 값. 초과 시 가장 오래된 키부터 축출 + WARNING 로그
                               #   (평상시엔 발동 안 하므로 "살아있는 세션 축출" 실패모드는 없음).
    SWEEP_INTERVAL_SEC = 60.0   # 이 간격보다 자주는 스윕 안 함(매 detect() 마다 dict 전수스캔 방지 —
                               #   호출은 O(1)이고, 실제 스캔은 이 간격 또는 키 수 초과 시에만 발동).

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
            self.EMA_MIN = float(tuning.val("track", "ema_min", self.EMA_MIN))     # 속도 적응형 EMA(2.2)
            self.EMA_MAX = float(tuning.val("track", "ema_max", self.EMA_MAX))
            self.EMA_DREF = float(tuning.val("track", "ema_dref", self.EMA_DREF))
            self.CONTAIN_RATIO = float(tuning.val("detect", "contain_ratio", self.CONTAIN_RATIO))   # 포함비 억제 문턱(1.9d)
            self.PPE_PERSON_EXPAND = float(tuning.val("detect", "ppe_person_expand", self.PPE_PERSON_EXPAND))   # 교차게이트(Phase C)
            self.PERSON_ENSEMBLE = bool(tuning.val("detect", "person_ensemble", self.PERSON_ENSEMBLE))   # [P-2] 이중신호 앙상블 on/off
            hf = int(tuning.val("detect", "hysteresis_frames", 0))   # >0 이면 전 신호를 이 N 으로 통일(1=끔). 0=기본(ppe3·fire2)
            if hf > 0:
                self.HYSTERESIS = {k: hf for k in self.HYSTERESIS}
            self.TRACK_ALGO = str(tuning.val("track", "algo", self.TRACK_ALGO)).strip().lower()
            self.BYTETRACK_LOW_CONF = float(tuning.val("track", "bytetrack_low_conf", self.BYTETRACK_LOW_CONF))
            self.BYTETRACK_HIGH_CONF = float(tuning.val("track", "bytetrack_high_conf", self.BYTETRACK_HIGH_CONF))
            self.BYTETRACK_FRAME_RATE = float(tuning.val("track", "bytetrack_frame_rate", self.BYTETRACK_FRAME_RATE))
            self.BYTETRACK_LOST_BUFFER = int(tuning.val("track", "bytetrack_lost_buffer", self.BYTETRACK_LOST_BUFFER))
            self.BYTETRACK_MIN_IOU = float(tuning.val("track", "bytetrack_min_iou", self.BYTETRACK_MIN_IOU))
            _act = tuning.val("track", "bytetrack_activation", None)   # None = person 임계 자동 연동(위 주석)
            self.BYTETRACK_ACTIVATION = float(_act) if _act is not None else None
            self.BYTETRACK_MIN_FRAMES = int(tuning.val("track", "bytetrack_min_frames", self.BYTETRACK_MIN_FRAMES))
            self.PASSTHROUGH_CONF = float(tuning.val("track", "passthrough_conf", self.PASSTHROUGH_CONF))
            self.PPE_CONFIG_WARN = ""
            _req = tuning.section("ppe").get("required")
            if _req is not None:
                # ★[2026-08-28] 예전에는 오타·빈 목록이 **로그 한 줄 없이** 기본 3종으로
                #   복귀했다. 그러면 운영자는 "마스크를 껐다"고 믿는데 오탐은 그대로 나고,
                #   원인은 보이지 않는다 — 조용한 폴백이 오탐보다 나쁘다.
                #   이제 **반드시 드러낸다**: WARN 로그 + guard.status() 노출(/health).
                #   ★기동을 실패시키지는 않는다 — 설정 오타로 안전 시스템 전체가 안 뜨는 것이
                #     더 위험하다. 대신 "적용되지 않았다"는 사실을 크게 남긴다.
                raw = [str(x) for x in (_req if isinstance(_req, (list, tuple, set)) else [_req])]
                norm = {LABEL_NORMALIZE.get(x, x) for x in raw}
                unknown = sorted(norm - set(PPE_MISSING_LABELS))
                # ★[2026-08-28 재수정] 알 수 없는 라벨이 **하나라도** 섞이면 설정 **전체를 무효**로
                #   본다. 예전에는 "유효한 것만 골라 쓰기"를 했는데, 그게 **가장 위험한 경우에
                #   신호가 가장 약한** 구조였다:
                #     ['helemt']                 → 기본 3종(커버리지 ↑)  + ERROR
                #     []                         → 기본 3종(커버리지 ↑)  + ERROR
                #     ['helemt','NO-Safety-Vest'] → 조끼만(커버리지 ↓)   + WARN 뿐  ← ★미탐 방향
                #   안전모+조끼를 의도했는데 오타 하나로 **안전모 미착용 경보가 조용히 사라진다.**
                #   앞의 둘은 과탐 쪽으로 틀리지만 이건 **미탐 쪽으로** 틀린다 — 심각도가 거꾸로였다.
                #   → 세 경우를 통일한다: 기본값 폴백 + ERROR + /health 노출.
                #   ★기동은 실패시키지 않는다(F1·F31 원칙) — 심각도만 고친다.
                if unknown or not norm:
                    self.PPE_CONFIG_WARN = (
                        f"ppe.required={raw} 무효 — "
                        + (f"알 수 없는 라벨 {unknown} 포함. " if unknown else "빈 목록. ")
                        + f"**설정 전체를 적용하지 않고 기본 {sorted(PPE_MISSING_LABELS)} 로 동작한다.** "
                        f"(일부만 골라 쓰면 의도한 감시 항목이 조용히 빠질 수 있다.) "
                        f"가능한 값: {sorted(PPE_MISSING_LABELS)}")
                    _guard_logger().error("★설정 무효: %s", self.PPE_CONFIG_WARN)
                else:
                    self.PPE_REQUIRED = norm
        except Exception:  # noqa: BLE001
            pass
        self._models: dict[str, Any] = {}      # id → YOLO (지연 로드 캐시)
        self._load_errors: dict[str, str] = {}
        self._predict_fail_streak: dict[str, int] = {}   # [Q-3] 슬롯별 연속 추론 실패 횟수
        self._slot_degraded: dict[str, bool] = {}        # [Q-3] PREDICT_FAIL_DEGRADE_THRESHOLD 도달 시 True
        self._tracks_by_key: dict[str, list[dict[str, Any]]] = {}  # 서버측 추적 박스(track_key 별 격리 · 5단계)
        self._bytetrack_by_key: dict[str, Any] = {}  # track_key 별 ByteTrackTracker 인스턴스(Phase2, algo=bytetrack 전용)
        self._key_last_used: dict[str, float] = {}  # track_key 별 마지막 사용 시각(F-2 TTL 청소용)
        self._last_sweep_at: float = 0.0          # 마지막 스윕 시각(F-2 — 이 간격보다 자주 스윕 안 함)
        self._tid_seq: int = 0                    # 트랙 안정 id 시퀀스(클라 id 매칭용 · 1.8b)
        self.HYSTERESIS = dict(self.HYSTERESIS_FRAMES)             # 신호 발화 히스테리시스(track_key 별 스트릭)
        self._sig_streak: dict[str, dict[str, int]] = {}          # track_key → {signal: 연속 True 프레임수}
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
        _ensure_core_on_path()          # M1-1: 멱등 삽입(예전엔 인스턴스마다 insert)
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
        self._require_rfdetr_pretrain(bool(out) or "rfdetr" in self._backend.values())
        return out

    # RF-DETR 베이스 사전학습 체크포인트(rfdetr 패키지가 받아 캐시하는 파일).
    #   커스텀 .pth 는 이 베이스 위에 얹히므로, 베이스가 없으면 rfdetr 이 **런타임에 인터넷으로
    #   349MB 를 받으러 간다**. 인터넷이 없는 현장(학원 등)에서는 그대로 기동 실패다.
    PRETRAIN_FILE = "rf-detr-nano.pth"          # detectors/rfdetr_adapter.py 가 RFDETRNano 사용
    PRETRAIN_SIZE = 366287238

    @staticmethod
    def rfdetr_cache_dir() -> "_Path":
        """rfdetr 이 사전학습 체크포인트를 찾는 디렉터리(RF_HOME 우선, 기본 ~/.roboflow/models).

        ★배포에서는 RF_HOME 을 vigent-core/weights 로 고정한다 — 그래야
        ①수동 실행과 LocalSystem 서비스가 **같은 캐시 하나**를 보고
        ②scripts/fetch_weights.py 가 받는 위치와 정확히 겹쳐 매니페스트로 조달된다.
        (2026-08-20 실측: 고정 전에는 사용자 프로필과 SYSTEM 프로필에 캐시가 따로 생겨
         서비스 첫 기동에서 349MB 를 새로 받았다.)
        """
        import os
        return _Path(os.path.expanduser(os.environ.get("RF_HOME", "~/.roboflow/models")))

    def _require_rfdetr_pretrain(self, needed: bool) -> None:
        """베이스 체크포인트 부재를 **기동 시점에 명시적으로** 실패시킨다(F-8 과 같은 원칙).

        조용히 인터넷에 의존하다 현장에서 죽는 것을 막는다. 우회는 명시적 opt-in 만 허용.
        """
        import os
        if not needed or os.environ.get("VIGENT_ALLOW_PRETRAIN_DOWNLOAD") == "1":
            return
        log = _guard_logger()
        p = self.rfdetr_cache_dir() / self.PRETRAIN_FILE
        if p.exists() and p.stat().st_size == self.PRETRAIN_SIZE:
            log.info("RF-DETR 사전학습 캐시 확인: %s", p)
            return
        why = "파일 없음" if not p.exists() else f"크기 불일치({p.stat().st_size:,} != {self.PRETRAIN_SIZE:,})"
        log.error("RF-DETR 사전학습 캐시 부재: %s (%s)", p, why)
        raise FileNotFoundError(
            f"[기동거부] RF-DETR 사전학습 체크포인트 부재: {p} ({why}). "
            f"이대로 두면 rfdetr 이 런타임에 인터넷에서 349MB 를 받으려 하고, "
            f"인터넷이 없는 현장에서는 기동이 실패한다. 조치: "
            f"`python scripts/fetch_weights.py --all` 로 조달하고 RF_HOME 이 "
            f"vigent-core/weights 를 가리키는지 확인하라(deploy/windows/install_service.ps1 이 주입). "
            f"다운로드를 허용하려면 VIGENT_ALLOW_PRETRAIN_DOWNLOAD=1 을 명시하라.")

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "role": self.role, "implemented": True,
                "detectors_available": list(self._slot_path.keys()),
                "loaded": list(self._models.keys()),
                "load_errors": self._load_errors,
                "rfdetr_slots": getattr(self, "_rfdetr_status", []),   # F-8: 커스텀 가중치 실검사 결과
                # [Q-3, 2026-08-10] 런타임 추론 실패 가시화 — 로드는 됐지만 매 프레임 예외로 실질
                #   무응답인 슬롯을 여기서 잡는다(로드 성공 여부만 보는 rfdetr_slots 로는 못 잡음).
                # ★[2026-08-28] 설정이 조용히 무시되는 상태를 밖에서 보이게 한다.
                "ppe_required": sorted(self.PPE_REQUIRED),
                "ppe_config_warn": self.PPE_CONFIG_WARN,
                "slot_degraded": {k: v for k, v in self._slot_degraded.items() if v},
                "predict_fail_streak": {k: v for k, v in self._predict_fail_streak.items() if v}}

    def _adaptive_ema(self, old: list[float], new: list[float]) -> float:
        """속도 적응형 EMA 계수(2.2 ①): 중심 이동량 d(정규화)가 클수록 a→EMA_MAX(고속=raw 즉각추종),
        작으면 EMA_MIN(강한 평활). D_REF = 새 박스 대각선 × EMA_DREF. 저속·정지는 EMA_MIN(현행)이라 저하 0."""
        ocx, ocy = (old[0] + old[2]) / 2, (old[1] + old[3]) / 2
        ncx, ncy = (new[0] + new[2]) / 2, (new[1] + new[3]) / 2
        d = ((ocx - ncx) ** 2 + (ocy - ncy) ** 2) ** 0.5
        diag = ((new[2] - new[0]) ** 2 + (new[3] - new[1]) ** 2) ** 0.5
        dref = self.EMA_DREF * diag
        if dref <= 0:
            return self.EMA_MAX
        a = self.EMA_MIN + (d / dref) * (self.EMA_MAX - self.EMA_MIN)
        return max(self.EMA_MIN, min(self.EMA_MAX, a))

    def _track(self, fresh: list[dict[str, Any]], track_key: str) -> list[dict[str, Any]]:
        """추적 알고리즘 디스패처(Phase2). TRACK_ALGO='iou'(기본)면 기존 _track_iou 그대로(회귀 0).
        'bytetrack'이면 person 만 ByteTrack, 나머지 클래스는 여전히 _track_iou(클래스 비구분 트래커에
        섞으면 오매칭 위험 — Phase2 범위를 person 으로 한정).
        모든 track_key 사용은 이 함수를 거친다 — F-2 TTL 청소용 last_used 갱신·스윕 트리거를 여기 한
        곳에서만 한다(호출마다 O(1), 실제 dict 스캔은 SWEEP_INTERVAL_SEC 마다 또는 키 수 초과 시만)."""
        now = time.time()
        self._key_last_used[track_key] = now   # 사용 중인 키는 계속 갱신 → TTL 청소 대상에서 제외(F-2④)
        self._maybe_sweep_stale_keys(now)
        # [T-E2E 유령박스 계측 · 2026-08-26 수정] 계측은 **여기(디스패처)** 에서 한다.
        #   예전엔 `_track_iou` 안에 있었는데, algo="bytetrack" 이면 `_track_bytetrack` 이
        #   person 을 먼저 떼어내고 나머지만 `_track_iou` 로 넘기므로(아래 _track_bytetrack 참조)
        #   **person 이 기록에서 통째로 빠졌다** — 정작 계측의 주 대상인데. 실제로 2026-08-26
        #   리허설에서 Hardhat 624건이 잡힌 영상인데 person 0건이 기록됐다. 디스패처로 올리면
        #   algo 와 무관하게 fresh 원본 전체가 잡힌다. env 게이트(기본 꺼짐) 밖 동작은 불변.
        _dbg = os.environ.get("VIGENT_TRACK_DEBUG") == "1"
        if self.TRACK_ALGO == "bytetrack":
            out = self._track_bytetrack(fresh, track_key)
        else:
            out = self._track_iou(fresh, track_key)
        if _dbg:
            self._dbg_write(now, track_key, fresh, out)
        return out

    def _dbg_write(self, now: float, track_key: str,
                   fresh: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
        """[T-E2E 유령박스 계측] VIGENT_TRACK_DEBUG=1 일 때만 프레임마다 JSONL 1줄 기록.

        추적 전(fresh, 원본 검출)과 추적 후(out, 실제 반환 트랙)를 함께 남긴다 —
        benchmarks/b_passthru_2fps_check.py 가 이 둘을 대조해 '추적이 버린 고신뢰 검출'을 센다.
        기본 꺼짐 = 비용·동작 변화 0. 자격증명·프레임 픽셀은 기록하지 않는다.

        hits/misses/age_ms 는 `_track_iou` 내부 트랙 상태에서 tid 로 이어 붙인다. ByteTrack 이
        모는 person 트랙은 내부 상태가 트래커 안에 있어 이 값들이 None 이다(분석기는 label·bbox
        만 쓰므로 무영향). 기록 대상이 '내부 트랙 전체'에서 '실제 반환분'으로 바뀌었는데,
        "버려진 검출" 판정에는 오히려 이쪽이 정확하다(출력에 없으면 소비자에게 안 간 것).
        """
        try:
            import json as _json
            from pathlib import Path as _P
            internal = {tr.get("tid"): tr for tr in self._tracks_by_key.get(track_key, [])}
            tracks = []
            for tr in out:
                it = internal.get(tr.get("tid"))
                tracks.append({
                    "tid": tr.get("tid"), "label": tr.get("label"),
                    "bbox": [round(v, 4) for v in tr.get("bbox", [])],
                    "hits": it.get("hits") if it else None,
                    "misses": it.get("misses") if it else None,
                    "age_ms": round((now - it["seen"]) * 1000) if it else None})
            rec = {"t": round(now * 1000), "key": track_key,
                   "algo": self.TRACK_ALGO,   # 분석기가 되묻는 '수집 당시 추적기'를 기록에 남긴다
                   "fresh": [{"label": f.get("label"), "conf": round(f.get("conf", 0), 3),
                              "bbox": [round(v, 4) for v in f.get("bbox", [])]} for f in fresh],
                   "tracks": tracks}
            with open(_P(__file__).resolve().parent.parent.parent / "data" / "track_debug.jsonl",
                      "a", encoding="utf-8") as _f:
                _f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001  계측 실패가 검출을 막으면 안 됨
            pass

    def _maybe_sweep_stale_keys(self, now: float) -> None:
        """F-2: KEY_TTL_SEC 넘게 안 쓰인 track_key 정리 + MAX_TRACKED_KEYS 하드 백스톱.
        SWEEP_INTERVAL_SEC 간격(또는 키 수 초과) 조건을 먼저 본 뒤에만 dict 를 스캔 — 매 프레임 detect()
        마다 전수스캔하지 않는다(카메라 N대×30fps 라이브 경로 지연 방지, 사용자 지시 ③)."""
        due = now - self._last_sweep_at >= self.SWEEP_INTERVAL_SEC
        over = len(self._tracks_by_key) > self.MAX_TRACKED_KEYS
        if not due and not over:
            return
        self._last_sweep_at = now
        stale = [k for k, t in self._key_last_used.items() if now - t > self.KEY_TTL_SEC]
        for k in stale:
            self._tracks_by_key.pop(k, None)
            self._bytetrack_by_key.pop(k, None)
            self._key_last_used.pop(k, None)
        overflow = len(self._tracks_by_key) - self.MAX_TRACKED_KEYS
        if overflow > 0:
            # 백스톱 발동: TTL 정리로도 안 줄어듦 — 비정상 트래픽 의심, 반드시 로그로 남긴다(사용자 지시).
            oldest = sorted(self._key_last_used.items(), key=lambda kv: kv[1])[:overflow]
            for k, _t in oldest:
                self._tracks_by_key.pop(k, None)
                self._bytetrack_by_key.pop(k, None)
                self._key_last_used.pop(k, None)
            _guard_logger().warning(
                "track_key 백스톱 발동: MAX_TRACKED_KEYS(%d) 초과 → 가장 오래된 %d개 강제축출"
                "(TTL 정리 후에도 초과 — 비정상 트래픽 의심, 원인 확인 필요)",
                self.MAX_TRACKED_KEYS, overflow)

    def reset_tracks(self, track_key: str) -> None:
        """track_key 하나의 추적 상태 초기화(IoU·ByteTrack 공통 — 오프라인 측정 reset_tracks 요청용).
        2026-08: `[]`로 비우기만 하면 dict 엔트리 자체는 안 지워져 매 호출 track_key 를 새로 발급하는
        패턴(isolated_detect.detect_isolated)에서 무한 증식한다(실측 확인: 200회 호출 → 200개 잔존).
        키 자체를 pop 한다 — `_track_iou`(setdefault)·`_track_bytetrack`이 없는 키를 자연히 재생성하므로
        완전 삭제해도 연속영상 track_key(예: "cam:<name>")의 정상 동작에는 영향 없다."""
        self._tracks_by_key.pop(track_key, None)
        self._bytetrack_by_key.pop(track_key, None)
        self._key_last_used.pop(track_key, None)

    def _activation_threshold(self) -> float:
        """ByteTrack 신규 트랙 스폰 임계 — 명시 설정이 없으면 **person 운용 임계에 자동 연동**.

        ★[PA, 2026-08-13] 이 연동이 없던 시절(하드코딩 0.70) conf 0.40~0.70 구간의 실제 작업자가
        트랙을 못 얻어 person_count 가 -10.3% 회귀했다(BYTETRACK_ACTIVATION 주석 참조). 스폰 자격은
        "이 검출을 사람으로 인정하는가"의 문제라 검출 채택 임계와 같은 값이어야 일관된다."""
        if self.BYTETRACK_ACTIVATION is not None:
            return float(self.BYTETRACK_ACTIVATION)
        return float(self.DETECTOR_CONF.get("person", self.DEFAULT_CONF))

    def _track_bytetrack(self, fresh: list[dict[str, Any]], track_key: str) -> list[dict[str, Any]]:
        """ByteTrack(trackers.ByteTrackTracker, Apache-2.0)로 person 만 추적(Phase2, benchmarks/
        track_fragmentation_causes.md 근거) — 칼만필터 모션예측 + 고신뢰/저신뢰 2단계 매칭 + 전역최적할당
        (그리디 1:1 이 아님 → guard._track_iou 의 '매칭경합' 실패모드 완화 기대).
        person 외 클래스는 기존 _track_iou 그대로(트랙 상태 공유 track_key 동일 — 클래스별 라벨매칭이라
        섞여도 안전, ByteTrack 은 클래스 비구분이라 별도 처리).
        tid<0(미확정 저신뢰 후보, BYTETRACK_MIN_FRAMES 미달)은 반환에서 제외 — 기존 MIN_HITS 필터와 동일 취지."""
        person = [d for d in fresh if str(d.get("label", "")).lower() == "person"]
        other = [d for d in fresh if str(d.get("label", "")).lower() != "person"]
        tracked_other = self._track_iou(other, track_key) if other else []
        if not person:
            return tracked_other

        import numpy as np
        import supervision as sv
        from trackers import ByteTrackTracker

        bt = self._bytetrack_by_key.get(track_key)
        if bt is None:
            bt = ByteTrackTracker(
                lost_track_buffer=self.BYTETRACK_LOST_BUFFER,
                frame_rate=self.BYTETRACK_FRAME_RATE,
                track_activation_threshold=self._activation_threshold(),
                minimum_consecutive_frames=self.BYTETRACK_MIN_FRAMES,
                minimum_iou_threshold=self.BYTETRACK_MIN_IOU,
                high_conf_det_threshold=self.BYTETRACK_HIGH_CONF,
            )
            self._bytetrack_by_key[track_key] = bt

        xyxy = np.array([d["bbox"] for d in person], dtype=float)
        conf = np.array([float(d.get("conf", 0.0)) for d in person], dtype=float)
        idx = np.arange(len(person))
        det = sv.Detections(xyxy=xyxy, confidence=conf, class_id=idx)
        result = bt.update(det)

        # tid 네임스페이스 충돌 방지: ByteTrackTracklet.get_next_tracker_id() 는 프로세스 전역 카운터라
        #   _track_iou 의 인스턴스별 _tid_seq(0부터 증가, other 클래스용)와 값이 겹칠 수 있다. 클라이언트
        #   표시(BoxTracker.js)는 클래스 무관하게 tid 값만으로 매칭하므로, 겹치면 person↔차량 등 트랙이
        #   잘못 병합될 위험이 있다 — 큰 오프셋으로 값 자체가 절대 겹치지 않게 분리(실측으로 발견·수정).
        out: list[dict[str, Any]] = []
        for i in range(len(result)):
            tid = int(result.tracker_id[i])
            if tid < 0:
                continue
            src = person[int(result.class_id[i])]
            out.append({**src, "bbox": [float(v) for v in result.xyxy[i]], "tid": tid + _BYTETRACK_TID_OFFSET})
        return out + tracked_other

    def _track_iou(self, fresh: list[dict[str, Any]], track_key: str) -> list[dict[str, Any]]:
        """서버측 추적/스무딩: 새 탐지를 기존 트랙과 IoU 매칭해 갱신(위치 EMA 평활),
        새것은 추가, TTL 지난 트랙은 제거. 잠깐 놓친 프레임에도 박스를 유지해 깜빡임 제거.

        track_key(카메라 id 등)별로 트랙 상태를 분리 — 여러 카메라/브라우저/오프라인 분석이 한
        _tracks 를 공유하면 A 카메라 박스가 B 결과에 섞이고(잔상·유령), fire/ppe 신호가 다른
        카메라 명의로 오발화된다(F-리뷰 5단계). 키를 안 주면 'default' 로 기존 동작 유지."""
        now = time.time()
        tracks = self._tracks_by_key.setdefault(track_key, [])   # 키별 격리 상태
        # [T-E2E 유령박스 계측] 기록은 디스패처 `_track` 의 `_dbg_write` 로 옮겼다(2026-08-26).
        #   여기 두면 algo="bytetrack" 에서 person 이 빠진다 — `_track` 주석 참조.
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
                a = self._adaptive_ema(best["bbox"], f["bbox"])   # 속도 적응형(2.2): 고속=raw, 저속=현행 평활
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
        # MIN_HITS 이상 '확인된' 트랙만 표시(한 프레임 헛것 제거). 내부필드(seen·hits·misses)는 빼고 반환.
        # [T-E2E 유령박스] stale=이번 프레임 미매칭(코스팅 중) 플래그를 가산 — 계측(2026-08-12,
        #   data/track_debug.jsonl)으로 확정한 유령 기전: 작은 PPE 박스는 보행 속도에서 프레임당
        #   이동량이 박스 크기를 초과해 매칭이 끊기고(20초에 신규 트랙 221개), 미매칭 트랙이
        #   TTL(1.2s)까지 마지막 위치에 동결된 채 응답에 실렸다. 트랙 집합 자체는 불변(신호·판정
        #   입력 무영향) — 표시 경계(/cameras/{cid}/detections)가 이 플래그로 숨긴다.
        return [{**{k: v for k, v in t.items() if k not in ("seen", "hits", "misses")},
                 "stale": t.get("misses", 0) > 0}
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
                # [Q-3] 해상도는 RF-DETR 이 로드 시점에 컴파일 고정(optimize_for_inference() 제약,
                #   detectors/rfdetr_adapter.py 클래스 docstring 참고) — self.IMGSZ(tuning.yaml
                #   detect.imgsz)를 여기서 넘겨야 실제로 적용된다. 예전엔 이 인자가 없어 항상
                #   라이브러리 기본값(384)으로 돌았다(dead parameter, benchmarks/
                #   p3_1_resolution_ab_BLOCKED.md).
                self._models[slot] = RfdetrDetector(rf_w, LABEL_NORMALIZE, JUNK_LABELS, resolution=self.IMGSZ)
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
               augment: bool = False, *, track_key: str) -> dict[str, Any]:
        """프레임 추론. 반환: 정규화 라벨·confidence·정규화 bbox(0~1) 목록 + 파생 신호.

        image_bgr: cv2 BGR numpy 배열
        detectors: 돌릴 검출기 id 목록(기본 person·ppe·forklift; fire 는 명시 시)
        imgsz: 추론 해상도 override(None=기본 self.IMGSZ). 오프라인 정밀분석은 높게(예 1280).
        augment: TTA(다중스케일·좌우반전 추론). 오프라인에서 True → 정확도↑·느림(실시간 금지).
        track_key: 필수(2026-08, 암묵적 기본값 폐지 — 호출자가 반드시 의도를 명시하게 강제).
            같은 카메라의 연속 프레임이면 그 카메라 고유값을 계속 재사용(예: "cam:<name>").
            서로 무관한 정지 이미지(배치 평가 등)면 매 호출 새 값을 쓰거나
            isolated_detect.detect_isolated()를 쓸 것 — "default" 같은 고정 문자열을
            정지 이미지에 재사용하면 트랙이 이어붙는 버그가 재발한다(2026-08 실측 확인).
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
                # ★[F31, 2026-08-24] 예전엔 여기서 **조용히 continue** 했다 — 로드 실패(가중치 손상·
                #   GPU OOM·라이브러리 오류)로 슬롯이 통째로 죽어도 스트릭도 DEGRADED 도 서지 않아
                #   /health 가 healthy 를 유지했다. person 이면 침입 경보가 영구 무력화되는데 초록불
                #   이다 — [Q-3] 가 "가장 위험한 고장 모드"라 부른 그 상태이며, [F1] 은 **추론 실패**
                #   경로만 덮어 이 **로드 실패** 경로가 남아 있었다. 아래 추론 실패 핸들러와 같은
                #   등급으로 취급해 F1 배선(핵심 슬롯 저하 → unhealthy)을 그대로 탄다.
                #   ★재시도는 넣지 않는다(범위 밖) — _get_model 이 실패를 캐시하므로 복구하려면
                #     재시작이 필요하다. 재시도·간격제한 설계는 docs/P3_BACKLOG.md 로 이월.
                streak = self._predict_fail_streak.get(slot, 0) + 1
                self._predict_fail_streak[slot] = streak
                why = self._load_errors.get(slot) or "모델 미로드(가중치 경로·backend 설정 확인)"
                # ★로그 폭주 방지: 로드 실패는 재시도가 없어 **매 프레임 영구 발생**한다(2fps면
                #   하루 17만 줄). 그대로 두면 이 수정이 디스크를 채워 [F2] 를 되살린다.
                #   임계까지는 매번 남기고(진단에 필요), 그 뒤로는 주기적으로만 남긴다.
                if streak <= self.PREDICT_FAIL_DEGRADE_THRESHOLD or streak % self.LOAD_FAIL_LOG_EVERY == 0:
                    _guard_logger().error(
                        "검출 슬롯 미가동(slot=%s, 연속 %d회): %s — 이 프레임은 해당 슬롯 결과 없이 진행",
                        slot, streak, why)
                if streak >= self.PREDICT_FAIL_DEGRADE_THRESHOLD and not self._slot_degraded.get(slot):
                    self._slot_degraded[slot] = True
                    _guard_logger().error(
                        "★검출 슬롯 DEGRADED(로드 실패): slot=%s 연속 %d회(임계 %d) — /health 확인. "
                        "로드 실패는 자동 복구되지 않는다(재시작 필요).",
                        slot, streak, self.PREDICT_FAIL_DEGRADE_THRESHOLD)
                continue
            slot_conf = conf_override if conf_override is not None else self.DETECTOR_CONF.get(slot, self.DEFAULT_CONF)
            # 클래스별 후필터 맵(ppe·fire_smoke): 맵의 최저 임계로 추론해 후보 확보 → 아래 박스 루프에서 클래스별로 거른다.
            per_class = (self.PPE_PER_CLASS if slot == "ppe"
                         else self.FIRE_SMOKE_PER_CLASS if slot == "fire_smoke" else {})
            run_conf = slot_conf
            if per_class:
                run_conf = min([slot_conf, *per_class.values()])
            # Phase2(bytetrack): person 슬롯만 저신뢰로 받아 ByteTrack 2단계매칭 후보 확보.
            #   호출자가 conf 를 명시(override)했으면 그 결정을 존중(자동 하향 미적용).
            #   RF-DETR/DETR 계열은 고정 쿼리수 1회 순전파 후 임계로 후보를 거르는 구조라
            #   임계값을 낮춰도 추론 자체는 1회 그대로(비용 무증가) — detectors/rfdetr_adapter.py 참조.
            if slot == "person" and self.TRACK_ALGO == "bytetrack" and conf_override is None:
                run_conf = min(run_conf, self.BYTETRACK_LOW_CONF)
            try:
                # 어댑터가 모델추론 + 라벨정규화 + bbox정규화까지 → 표준 박스 반환(백엔드 불가지).
                #   해상도 ↑(imgsz) + (오프라인) TTA + 검출기별 임계(건설모델은 높게 → 오탐 컷).
                boxes = model.detect(image_bgr, conf=run_conf,
                                     imgsz=imgsz or self.IMGSZ, augment=augment)
            except Exception as ex:  # noqa: BLE001  추론 실패해도 나머지 슬롯은 계속(저하 없음 원칙)
                # [Q-3, 2026-08-10] 예전엔 이 예외가 _load_errors 에만 조용히 쌓이고 조용히 continue
                #   해서, 겉으로는 정상 응답(200)인데 검출이 계속 0건인 "멀쩡해 보이는데 아무것도
                #   안 보는" 상태가 됐다 — 안전 제품에서 가장 위험한 고장 모드. 이제 ERROR 로그를
                #   반드시 남기고, 연속 실패가 임계 이상이면 DEGRADED로 표시해 /health 에 노출한다.
                streak = self._predict_fail_streak.get(slot, 0) + 1
                self._predict_fail_streak[slot] = streak
                self._load_errors[slot] = f"predict: {type(ex).__name__}: {ex}"
                _guard_logger().error(
                    "검출 실패(slot=%s, 연속 %d회): %s: %s — 이 프레임은 해당 슬롯 결과 없이 진행",
                    slot, streak, type(ex).__name__, ex)
                if streak >= self.PREDICT_FAIL_DEGRADE_THRESHOLD and not self._slot_degraded.get(slot):
                    self._slot_degraded[slot] = True
                    _guard_logger().error(
                        "★검출 슬롯 DEGRADED: slot=%s 연속 %d회 실패(임계 %d) — /health 에서 확인할 것",
                        slot, streak, self.PREDICT_FAIL_DEGRADE_THRESHOLD)
                continue
            if self._predict_fail_streak.get(slot):     # 실패 스트릭 있었으면 복구 로그
                if self._slot_degraded.get(slot):
                    _guard_logger().info("검출 슬롯 복구: slot=%s (연속 %d회 실패 후 정상 복귀)",
                                          slot, self._predict_fail_streak[slot])
                self._predict_fail_streak[slot] = 0
                self._slot_degraded[slot] = False
            used.append(slot)
            for d in boxes:
                # 클래스별 임계 후필터(ppe·fire_smoke): 맵에 있으면 그 임계, 없으면 slot_conf 로 거른다.
                #   ppe: 착용 클래스는 slot_conf 유지, NO-* 만 개별 임계. fire_smoke: fire·smoke 각각(T14-F).
                #   ※ 라벨정규화·JUNK 버림·bbox정규화는 어댑터(finalize_box)에서 이미 수행 → 기존과 동일.
                if per_class and d["conf"] < per_class.get(d["label"], slot_conf):
                    continue
                d["detector"] = slot
                detections.append(d)

        # ── 서버 검출 정리 파이프라인(Phase C 순서 확정) ──────────────────────────
        #   검출(멀티모델) → NMS(같은라벨 IoU 중복) → 차량오인 제거 → containment(중첩 유령)
        #     → 교차게이트(PPE↔person 결부) → 추적(_track) → 교차소스 person 병합
        #   ※오탐/유령을 '추적 이전'에 모두 걸러 트랙·person_count·이벤트 오염을 원천 차단.
        detections = _nms(detections)
        detections = _suppress_vehicle_dupes(detections)   # 지게차↔버스 오인 중복 제거
        # 포함비 억제(1.9d): IoU-NMS 가 못 잡는 '큰 박스 안 작은 박스'를 포함비+conf 조건으로 정리.
        detections = _containment_suppress(detections, self.CONTAIN_RATIO)
        # 교차게이트(Phase C): PPE 는 사람과 결부(겹침/확장영역 내)될 때만 유지 — 사람 없는 PPE 오탐 제거.
        #   ※person_ensemble 플래그와 무관하게 항상 전체 person(person 슬롯+ppe 슬롯 Person 클래스)을
        #   근거로 판단한다 — "이 PPE 항목 근처에 누군가 있는가"는 person 재현율 실험과 별개 관심사.
        detections = _cross_validate_ppe(detections, self.PPE_PERSON_EXPAND)
        if not self.PERSON_ENSEMBLE:
            detections = _drop_ppe_origin_person(detections)
        _pre_track = detections
        detections = self._track(detections, track_key)
        # ★[B-passthru] 추적이 버린 **고신뢰 person** 을 되살린다(기본 off — PASSTHROUGH_CONF=0).
        #   실측(dev 74장): 추적이 검출의 29.3%p 를 버리고 원거리는 83%→8% 로 전멸한다.
        #   "못 보는 것"이 아니라 "보고도 버리는 것"이라, 경보 재현율을 추적기 성능에서
        #   분리하려면 이 경로가 필요하다. 되살린 박스는 **tid 가 없다** — 하위 판정은
        #   worker._derive 의 위치 기반 격자 키가 받는다(zone.grid_cells).
        #   ※NMS·억제·교차검증은 이미 위에서 통과한 목록이므로 품질이 보장된다
        #     (추적 '이후'에 덧붙이던 실험 분기와 달리 파이프라인을 건너뛰지 않는다).
        if self.PASSTHROUGH_CONF > 0:
            kept = {id(d) for d in detections}
            # ★중복 제거가 필수다 — 되살린 박스가 **이미 추적된 같은 사람**과 겹치면
            #   그 사람 GT 는 하나뿐이라 둘째 박스가 곧바로 오탐이 된다.
            #   중복 제거 없이 쟀을 때 정밀도가 82.5→54.2% 로 무너졌다(TP +18 인데 FP +57).
            live = [d.get("bbox") or [0, 0, 0, 0] for d in detections
                    if str(d.get("label", "")).lower() == "person"]
            for d in _pre_track:
                if id(d) in kept or str(d.get("label", "")).lower() != "person":
                    continue
                if float(d.get("conf", 0)) < self.PASSTHROUGH_CONF:
                    continue
                bb = d.get("bbox") or [0, 0, 0, 0]
                if any(_iou(bb, e) >= self.TRACK_IOU for e in live):
                    continue                      # 이미 추적된 사람과 같은 자리 → 버린다
                live.append(bb)
                detections.append({**d, "tid": None, "passthrough": True})
        # 안 B(box-overlay): 추적 이후, 교차소스(person 슬롯↔ppe 슬롯) person 중복만 병합.
        #   _nms(0.55)↔TRACK_IOU(0.45) 임계 불일치가 남긴 IoU 0.45~0.55 person 이중박스 해소.
        #   같은 소스는 병합 안 함(진짜 두 사람 보호). 검출·nms·추적 로직은 불변.
        detections = _merge_cross_source_person(detections)

        # 파생 신호(딥러닝 → 규칙 가산용)
        person_count = sum(1 for d in detections if d["label"].lower() == "person")
        # ★[현장 2026-08-27] 어떤 미착용을 '보호구 경보'로 볼지는 **현장마다 다르다**.
        #   실측: 학원 야외 실습장에서 보호구 경보 490건 중 **87건(17.8%)이 "마스크 미착용"만**이
        #   방아쇠였고, 완전 착용 장면에서는 **81건 중 72건(88.9%)** 이 그랬다
        #   (안전모 0.83~0.91 · 조끼 0.87~0.93 정상 착용 상태 — 육안 확인).
        #   마스크는 그 현장의 필수 보호구가 아니어서 **운영상 무의미한 경보**였다.
        #   → tuning `ppe.required` 로 대상을 고른다. 미지정이면 **기존 3종 그대로**(회귀 0).
        ppe_missing_hits = [d for d in detections if d["label"] in self.PPE_REQUIRED]
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
                # 히스테리시스(Phase C item2): 연속 N프레임 확인 후에만 True → 고립된 1프레임 오검출 경보 차단.
                #   N=1(tuning)이면 현행과 동일. conf 게이지(ppe_conf·fire_conf)는 원값 유지(Analyst 가산용).
                "ppe_missing": self._hysteresis(track_key, "ppe_missing", bool(ppe_missing_hits)),
                "ppe_conf": ppe_conf,
                "forklift_present": any(d["label"].lower() == "forklift" for d in detections),
                "fire_smoke": self._hysteresis(track_key, "fire_smoke", bool(fire_hits)),
                "fire_conf": fire_conf,
            },
        }

    def _hysteresis(self, track_key: str, name: str, raw: bool) -> bool:
        """신호 발화 히스테리시스: raw 가 연속 N(HYSTERESIS[name])프레임 True 여야 True 반환.
        track_key 별 스트릭 유지 → 카메라 간 독립. raw=False 면 즉시 0 리셋(하강은 즉각)."""
        n = self.HYSTERESIS.get(name, 1)
        st = self._sig_streak.setdefault(track_key, {})
        st[name] = min(st.get(name, 0) + 1, n) if raw else 0
        return st[name] >= n
