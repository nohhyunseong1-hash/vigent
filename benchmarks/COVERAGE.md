# VIGENT 라이브 4클래스 벤치마크 커버리지

> 라이브 감지 파이프라인(guard)이 소비하는 4개 검출기 슬롯의 평가셋 커버리지.
> 수치는 `benchmarks/run_eval.py`(COCOeval 101-pt) 실측(2026-07-04). 규칙7: 측정한 것만 기록, 미측정은 '미측정'.

## 커버리지 표

| 슬롯 | 배포 모델(vision.yaml) | 평가셋 | 이미지/GT | raw mAP@50 | pipeline mAP@50 | 상태 |
|---|---|---|---|---|---|---|
| **person** | `weights/yolo11m.pt` | `data/eval/clean` | 74장 / 87 | **90.82%** | **70.95%** | 측정됨(공개/일반 이미지) |
| **ppe** | `weights/ppe_css_v1.pt` | `data/datasets/css_safety/test` | 82장 / 760 | **75.20%** | **58.62%** | 측정됨(공개셋 CC BY 4.0) |
| **fire_smoke** | `weights/fire_smoke_boda.pt` | — | — | — | — | **미측정 · 평가셋 조달 필요** |
| **forklift** | `weights/forklift_boda_ax.pt` | — | — | — | — | **미측정 · 평가셋 조달 필요** |

- raw = 원시 `model.predict`(conf 0.001, 모델 능력) · pipeline = 배포 `guard.detect`(운용 임계·후처리).
- person/ppe 평가셋은 **공개/일반 이미지**로 VIGENT 현장 고정 CCTV가 아님 → 현장 정확도는 별도 재측정 필요(기존 정확도 문서와 동일 단서).
- fire_smoke/forklift는 배포 모델은 있으나 **라벨된 평가셋이 없어 mAP 측정 불가**(아래 조달 스펙).

## fire_smoke / forklift 평가셋 조달 스펙

> 목표: 각 슬롯에 대해 person/ppe와 동일 절차(YOLO txt 라벨 + `run_eval.py`)로 raw/pipeline mAP를 측정 가능하게 함.
> 아래 수량은 **권장 추정치**(측정값 아님) — 통계적으로 안정된 클래스별 AP를 위한 최소선.

### 공통 요건
- 형식: 이미지 + YOLO txt 라벨(`class cx cy w h` 정규화). `data/datasets/<name>/{images,labels}` + `data.yaml(names)`.
- 최소 규모(권장): **이미지 ≥ 150장 / 대상 클래스 인스턴스 ≥ 300개**. (harness는 30장 미만 경고 — 소표본은 신뢰구간이 넓음)
- 분포: 원거리·역광·야간·부분가림 등 **현장 유사 조건** 포함. 가능하면 **현장 고정 CCTV 프레임**을 우선(공개셋은 대리지표).
- 네거티브(대상 없음) 프레임 일부 포함 → 오탐(FP) 측정.

### fire_smoke (2클래스: fire, smoke)
- 필요: 이미지 ≥ 150장, fire 인스턴스 ≥ 150 · smoke 인스턴스 ≥ 200(연기가 더 다양).
- 후보 공개 소스(라이선스 개별 확인 필요):
  - **D-Fire** (fire/smoke bbox, 다수) · **FASDD**(Flame And Smoke Detection Dataset) · **FireNet/Furg-Fire**.
  - Roboflow Universe "fire smoke detection" 계열(bbox·YOLO 내보내기 지원).
- 주의: 산업 현장 연기(용접·분진)와 화재 연기 혼동 → 현장 프레임으로 보정 권장.

### forklift (1클래스: forklift, 필요시 +load)
- 필요: 이미지 ≥ 150장, forklift 인스턴스 ≥ 300(주행/정지/적재 다양 각도).
- 후보 공개 소스(라이선스 개별 확인 필요):
  - **LOCO**(Logistics Objects in Context — 창고/지게차 포함) · **ACID**(건설장비) · Roboflow "forklift" 계열.
  - 산업물 자동라벨은 과거 실패 이력(공개모델·GDINO 미전이) → 소량 수동 씨앗 + 자가학습 병행 필요.
- 참고: 현재 forklift 슬롯은 `fallback: none`(모델 없으면 해당 기능만 비활성).

### 조달 후 절차
1. `data/datasets/<name>/{images,labels}` + `data.yaml` 배치.
2. `run_eval.py`의 `_DATASETS`에 항목 추가(images/labels/slot/gt_names).
3. `--mode raw`(모델 능력) · `--mode pipeline`(배포) 각각 실행 → `baseline_yolo.json` 누적.
