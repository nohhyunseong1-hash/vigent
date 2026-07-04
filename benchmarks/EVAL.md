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

### PPE
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

### fire_smoke (T13, D-Fire CC0 · 395장) — ★ 이중 지표 체계

현행 boda 모델은 화재를 **대영역 1박스**로 검출하나 D-Fire GT는 **소형 화염 다수+연기 분리**로 주석 →
box mAP는 스키마 불일치로 '능력'을 반영 못 함. **용도(화재 경보)에 맞는 이미지수준 presence를 병행**한다.

| 지표 | 트랙 | fire | smoke | 의미 |
|---|---|---|---|---|
| **box mAP@50** | raw | 0.16% | 8.45% | ⚠️ **능력 지표 아님** — 주석 스키마 비호환 참고치(오버레이 `results/fire_smoke_diag/`) |
| box mAP@50 | pipeline | 0.12% | 2.12% | 〃 |
| **presence AP** | raw | **83.13%** | **89.89%** | ★ 이미지수준 존재 감지 — **모델은 화재/연기 존재를 잘 감지**. box mAP 저조는 순전히 granularity |
| presence AP | pipeline | 62.23% | 75.33% | 배포 경로 |
| **presence recall@운용점** | pipeline(conf 0.70) | **10.45%** | **7.58%** | ⚠️ **안전 리스크** — 배포 임계가 높아 화재 프레임 ~90% 놓침(FINDINGS) |
| presence precision@운용점 | pipeline | 95.83% | 92.59% | 오경보는 적음(정밀↑ recall↓ 트레이드오프) |

- **box mAP(D-Fire)는 검출 품질 지표** — 4.31%(raw)는 스키마 비호환 참고치, 능력 게이트 아님(폐기, FINDINGS).
- **presence F1/recall은 배포 용도(화재 경보) 지표** — T10b '저하 없음' 게이트는 이것으로 판정.
- 지표 추가는 **용도 정합화**(게이트 회피 아님) — COCOeval 측정 로직 무수정, `presence_eval.py`로 별도 산출.

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
