# VIGENT 벤치마크 (EVAL) — person / PPE COCO baseline

> COCO mAP 기준선. 측정일 2026-07-04. 도구 `benchmarks/run_eval.py`(pycocotools COCOeval, 101-point).
> 규칙7: 아래 수치는 실제 실행 결과. 모델·원본 데이터 불변(읽기만).

## 0. 실행 환경 (중요)

- **반드시 아나콘다 파이썬으로 실행**(ultralytics·pycocotools 설치 환경):
  `/opt/anaconda3/bin/python3`
- 설치: `/opt/anaconda3/bin/python3 -m pip install pycocotools pip-licenses`
- ultralytics 8.3.253 · pycocotools 2.0.11 · torch 2.12.0.

## 1. 이중 트랙 — 무엇을 재는가 (게이트 정의)

같은 GT·같은 COCOeval, **예측 소스만 다름**:

| 트랙 | 예측 소스 | 임계/후처리 | 의미 |
|---|---|---|---|
| **raw** (기본) | 원시 `model.predict` | conf=0.001, NMS 0.7 | **표준 COCO baseline = 모델 능력**. 모델간 비교(T10 RF-DETR 이관 판정)는 raw로만. |
| **pipeline** | 배포 `guard.detect` | vision.yaml 운용 임계·후처리 | **배포 운용점**. 실제 서비스가 내는 값. |

> 왜 나눴나: person 최초 측정에서 raw 90.82%가 기존 기록 69.0%와 21.8%p 벌어짐 → 원인 규명 결과
> **방법론 차이(예측 소스 + 보간법)**로 판명(버그 아님, GT 87박스 정확 일치). 수치를 고치지 않고 두 트랙을 병기한다.

## 2. 평가셋 구성

| 셋 | 경로 | 이미지 | GT박스 | 클래스 | 출처 |
|---|---|---|---|---|---|
| person | `data/eval/clean` | 74 | 87 | person(단일) | 공개/일반 이미지(거리·실내). **현장 CCTV 아님** |
| ppe | `data/datasets/css_safety/test` | 82 | 760 | 10종(data.yaml) | Roboflow "Construction Site Safety" v27 (CC BY 4.0). **현장 CCTV 아님** |

## 3. 실행 명령 (재현)

```bash
# person
/opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode raw      --dataset person --weights vigent-core/weights/yolo11m.pt
/opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode pipeline --dataset person
# ppe
/opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode raw      --dataset ppe    --weights vigent-core/weights/ppe_css_v1.pt
/opt/anaconda3/bin/python3 benchmarks/run_eval.py --mode pipeline --dataset ppe
```
- 결과 누적: `benchmarks/results/baseline_yolo.json` (구조 `{dataset: {mode: record}}`).
- seed 고정(0), latency는 warmup 10프레임 제외 평균.

## 4. Baseline 수치 (실측)

### person
| 트랙 | 백엔드 | mAP@50 | mAP@50:95 | 예측수 | latency(ms/frame) | 비고 |
|---|---|---|---|---|---|---|
| raw | YOLO(yolo11m) | 90.82% | 77.58% | 1090 | 141.2 | 표준 COCO baseline |
| pipeline | YOLO(guard) | 70.95% | 45.85% | 84 | 294.8 | YOLO 배포 운용점 |
| **raw_rfdetr** | **RF-DETR(Nano, COCO)** | **93.92%** | **85.59%** | 3311 | **33.8** | ★ T10a — YOLO raw 대비 **+3.1%p** |
| **pipeline_rfdetr** | **RF-DETR(guard)** | **92.94%** | **84.26%** | 114 | **35.5** | ★ T10a 배포 운용점 |

**★ T10a — person 검출 RF-DETR 이관 (ultralytics AGPL → RF-DETR Apache-2.0):**
- **raw 게이트(≥88.8%): 통과** — RF-DETR **93.92%** ≥ 90.82(YOLO baseline)−2%p. 오히려 baseline **초과**.
- **배포 운용점 급상승**: pipeline **70.95 → 92.94%**(**+21.99%p**). YOLO는 raw→pipeline에서 −19.9%p 손실(저신뢰 TP 탈락)이었으나, **RF-DETR은 raw→pipeline 손실이 −0.98%p뿐** — 운용 임계(0.35)에서도 재현율을 거의 잃지 않음(잘 보정된 confidence).
- **latency 대폭 개선**: raw 141→**33.8ms**(0.24×), pipeline 295→**35.5ms**(**0.12× = ~8배 빠름**). RK3588 6 TOPS 예산 검토에 유리(단 실측은 macOS MPS 기준 — RK3588 재측정 필요).
- 재현: `--mode raw --backend rfdetr --dataset person`(raw) / `--mode pipeline --backend rfdetr --dataset person`(pipeline, vision.yaml `perception.backend.person=rfdetr` 기준).
- **금지 준수**: guard.detect의 임계·필터·후처리 무수정(움직인 변수 = 모델뿐). 어댑터 계층(`detectors/`)만 추가.

**★ person 3수치 병기(수정 금지):**
- **raw COCO = 90.82%** (모델 능력, 표준)
- **pipeline COCO = 70.95%** (배포 guard, 101-pt)
- **기존 harness = 69.0%** (배포 guard, 11-pt · `tools/ml/eval_harness.py`)
→ pipeline(70.95, 101-pt)와 harness(69.0, 11-pt)는 ~2%p 차이 = **보간법 차이로 정합**(같은 guard 예측).
→ raw가 +20%p 높은 것은 운용 임계·후처리로 저신뢰 TP가 탈락하기 때문(버그 아님).

### PPE — T10b RF-DETR 이관 (css_safety 학습, Colab best_ema)

**이관 완료**: ppe_css_v1(YOLO, AGPL) → **RF-DETR(Apache, css_safety 학습)**. 게이트 raw mAP@50 ≥ 73.2 통과.

| 트랙 | mAP@50 | mAP@50:95 | 의미 |
|---|---|---|---|
| **RF-DETR raw** | **75.62%** | 44.1% | ★ 게이트 통과(≥73.2). 구 YOLO raw 75.20 대비 +0.42 |
| **RF-DETR pipeline** | **71.46%** | 42.41% | ★ 배포 운용점(ppe 0.35). 구 YOLO pipeline 58.62 대비 **+12.84%p** |

- raw 클래스별 AP@50: Hardhat 89.24·Mask 80.18·NO-Hardhat 64.42·NO-Mask 66.81·NO-SafetyVest 81.39·Person 85.49·SafetyCone 41.27·SafetyVest 78.85·machinery 91.23·vehicle 77.32.
- pipeline 클래스별 AP@50: Hardhat 84.86·Mask 75.25·NO-Hardhat 57.87·NO-Mask 63.79·NO-SafetyVest 79.37·Person 80.79·SafetyCone 37.18·SafetyVest 75.09·machinery 87.63·vehicle 72.82.
- **운용점**: 단일 base **0.35**(구 YOLO 0.62 + per-class override 제거). RF-DETR은 미착용류도 강함(raw recall @0.35 NO-Hardhat 88·NO-Mask 80·NO-SafetyVest 97) → 단일 임계로 구 YOLO 상회, override 불요(0.30 비교서 이득 미미/역효과 실측).
- **⚠️ 동일출처 누출 한계**: css_safety train→test(공식 Roboflow 분할, 동일 출처). in-domain — 현장 CCTV 일반화 별도 검증 필요.
- 회귀: person 92.94·forklift 8.5·fire_smoke(fire95.91/smoke87.88) **Δ0.00**. 측정 로직 무수정.
- 구 YOLO(참고·롤백): raw 75.20/pipeline 58.62. **롤백**: backend.ppe=yolo + ppe 0.62 + override(NO-Hardhat0.30/NO-Mask0.50/NO-Safety-Vest0.50) 복원.

--- 아래는 구 YOLO ppe_css_v1 상세 기록(근거 보존) ---

| 트랙 | mAP@50 | mAP@50:95 | 예측수 | latency(ms/frame) |
|---|---|---|---|---|
| raw | **75.20%** | 50.24% | 4802 | 61.1 |
| pipeline | **58.62%** | 37.85% | 477 | 131.8 |

**클래스별 AP@50 — raw vs pipeline vs 기존 ppe_eval 기록(guard·11-pt):**

| 클래스 | raw | pipeline | ppe_eval 기록 | pipeline vs 기록 |
|---|---|---|---|---|
| Hardhat | 86.95 | 76.13 | 72.7 | +3.4 |
| NO-Hardhat | 59.59 | 48.07 | 46.5 | +1.6 |
| Mask | 78.09 | 75.25 | 72.7 | +2.6 |
| NO-Mask | 81.24 | 69.55 | 71.8 | -2.3 |
| Safety Vest | 86.58 | 67.28 | 63.6 | +3.7 |
| NO-Safety Vest | 77.22 | 67.04 | 63.5 | +3.5 |

→ **pipeline은 기존 ppe_eval 기록과 ±~4%p로 정합**(둘 다 guard 기반, 차이는 11↔101-pt). **raw는 체계적으로 +10~20%p 높음**(person과 동일 경향).
→ raw 전체 10클래스 AP@50: Hardhat 86.95 · Mask 78.09 · NO-Hardhat 59.59 · NO-Mask 81.24 · NO-Safety Vest 77.22 · Person 83.21 · Safety Cone 42.05 · Safety Vest 86.58 · machinery 86.91 · vehicle 70.19.

### fire_smoke (T13→T10b RF-DETR 이관 · D-Fire CC0 · 395장) — ★ e17 best_ema

**T10b 이관 완료**: boda(YOLO, AGPL) → **RF-DETR(Apache, D-Fire 학습)**. RF-DETR 는 D-Fire 스키마로 학습돼
**box mAP 가 유효한 능력 지표**가 됨(구 boda 는 스키마 비호환 참고치였음). Colab 30ep 중 **e17 best_ema**
(val 피크·잔여 13ep 미실행 — val 하락 확인). 게이트 A(presence)·B(box mAP) 모두 통과.

**배포 지표(RF-DETR e17, pipeline fire 0.30 / smoke 0.50):**
| 지표 | 트랙 | fire | smoke | 의미 |
|---|---|---|---|---|
| **box mAP@50** | raw(395 test) | **75.28%** | **84.98%** | ★ 능력 지표(D-Fire 학습→test). 전체 **80.13%**(게이트 B ≥60 통과). 구 boda 0.16/8.45 대비 세대차 |
| box mAP@50:95 | raw | 37.23% | 53.20% | 전체 45.21% |
| **presence AP** | raw | **98.37%** | **95.50%** | 이미지수준 존재 감지(구 boda 83.13/89.89 대비↑) |
| **presence recall@운용점** | pipeline(fire0.30/smoke0.50) | **95.91%** | **87.88%** | ★ 구 T14-F(53.64/24.85) 대비 fire 1.8배·smoke 3.5배 |
| presence precision@운용점 | pipeline | 99.06% | 96.67% | — |
| **presence FAR@운용점** | pipeline | **1.1%**(2/175) | **15.4%**(10/65) | fire 오탐 거의 0. smoke 조건(≤18%) 충족 → 0.50 확정 |

- **게이트 판정(e17)**: B(box mAP@50 80.13 ≥ 60) 통과 · A(presence recall fire 95.9/smoke 87.9 > 기준 53.6/24.9, FAR 개선 동반) 통과.
- **운용점**: RF-DETR conf 스케일 재튜닝 → fire 0.30 / smoke 0.50. smoke 는 조건부(pipeline FAR>18%면 0.60 후퇴)였으나 실측 **15.4% → 0.50 확정**.
- **smoke FP 유형(현장 FAR 예측 근거)**: smoke 오탐 10건 중 **8건은 fire_only 버킷 = 화재 장면의 실제 연기(GT 미주석) → 사실상 정탐**(주석 공백). **진짜 오탐 2건은 둘 다 야외 대기 연무/흐린 하늘**(WEB10316 항공 헤이즈·WEB09728 흐린 지평선). → 실내 공장 배포 시 야외성 연무 소스 희소 → **현장 smoke FAR 는 15.4%보다 낮을 것으로 기대**(T10c-V 현장 검증 시 대조).
- ⚠️ **in-domain 한계**: RF-DETR 는 D-Fire 학습→D-Fire test 평가(동일 출처). 정당한 홀드아웃이나 **현장 영상 일반화는 별도 검증 필요**.
- 회귀: person 92.94·ppe 58.62·forklift 8.5 **Δ0.00**(이관 타 슬롯 무영향). 측정 로직 무수정 — `presence_eval.py`·`gate_eval_e17.py`로 산출.
- 구 boda(참고·폐기): box mAP raw fire0.16/smoke8.45, presence recall 53.64/24.85. **롤백**: backend.fire_smoke=yolo + 임계 fire0.03/smoke0.20.

### forklift (T13b, LOCO CC0 · 318장=positive 238+네거 80) — 이중 지표

LOCO forklift 희소(598inst/449img) → SHA256 결정적 **test 0.55 상향 분할**(test 238img/316inst). 네거티브 80장(hard/pallet_truck 40+일반 40)으로 FAR 측정.

| 지표 | raw | pipeline | 의미 |
|---|---|---|---|
| **box mAP@50** | **7.61%** | 3.15% | ⚠️ 도메인갭+저신뢰(스키마 아님 — 검출 시 IoU≥0.5가 31%) |
| **presence AP** | 76.87% | 76.60% | 존재 감지는 상대적 양호(저conf) |
| presence recall@운용점 | 58.4% | **35.71%**(conf 0.68) | ⚠️ 배포서 forklift 64% 놓침 |
| presence precision@운용점 | 77.65% | 78.70% | — |
| **presence FAR@운용점** | 50.0% | **28.7%** | ⚠️ 네거 80장 중 23장 오탐 = **pallet_truck 혼동** |

- 현행 forklift 모델은 LOCO 도메인에서 **저recall(36%)·고오탐(FAR 29%)** 양쪽 약함 → box mAP 저조의 실체.
- box mAP(raw 7.61)는 T10b '저하없음' 게이트 기준선, presence recall/FAR 은 배포 안전 지표(FINDINGS). 근본 해결 = T10b(LOCO 재학습 + pallet_truck hard negative).
- pallet_truck 은 병합 안 함(다른 위험군) → FINDINGS 백로그(별도 검출 클래스 후보).

## 5. ★ 신규 발견 — raw↔pipeline 체계적 격차

- 배포 파이프라인(`guard.detect`)이 원시 모델 대비 mAP@50을 **일관되게 크게 떨어뜨림**: person **90.82 → 70.95**(−19.9%p), ppe **75.20 → 58.62**(−16.6%p).
- 원인: (a) 운용 confidence 임계(vision.yaml `detect_threshold` 등)로 **저신뢰 TP 탈락 → 재현율 손실**, (b) guard 후처리(정규화/필터).
- 함의: **모델을 바꾸지 않아도** 운용 임계·후처리 튜닝으로 배포 재현율에 회복 여지가 있을 수 있음(별도 실험 대상). 단 임계를 낮추면 오탐↑ 트레이드오프 → 현장 데이터로 운용점 재탐색 필요.
- latency도 pipeline이 raw의 ~2배(guard 후처리 포함): person 141→295ms, ppe 61→132ms.

## 6. 한계 (규칙7)

- 평가셋이 **공개/일반 이미지**(현장 고정 CCTV 아님) → 현장 정확도는 재측정 필요.
- 표본 작음(person 74장, ppe 82장) → 신뢰구간 넓음. 소클래스(Safety Cone 등) 불안정.
- PPE 셋은 배포모델 학습셋과 동일 출처(css_safety)의 test 분할 → **누출 가능성 미검증**(낙관적일 수 있음).
- fire_smoke/forklift는 평가셋 없어 **미측정**(`COVERAGE.md` 조달 스펙 참조).
- pipeline latency는 단일 이미지 순차 처리 기준(배치·GPU 아님, Apple Silicon CPU/MPS).

## 7. 라이선스

- 상세: `benchmarks/results/licenses.md`. T12-B 신규 도입분(pycocotools/pip-licenses/prettytable/wcwidth) **copyleft 0**.
- ⚠ 기존 `ultralytics`(YOLO 런타임) = **AGPLv3+** — CLAUDE.md §6에 명시된 알려진 이슈(T12-B 도입 아님).
