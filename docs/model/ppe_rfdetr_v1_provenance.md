# PPE 모델 출처 감사 — `ppe_rfdetr_v1` (T-0, 2026-09-25)

> **성격**: AI Hub 재학습의 **"전(前)" 기록**이다. 저장소 기록·가중치 파일 메타·로컬 데이터셋에서 찾을 수 있는 것만 적고,
> 못 찾은 것은 **출처 불명**으로 둔다. 학습은 실행하지 않았다.

## 0. 결론 먼저

1. **"ppe_rfdetr_v1"과 "PPE 슬롯 모델"은 같은 파일이다.** PPE 슬롯은 `backend: rfdetr` → `rfdetr_weights.ppe = vigent-core/weights/ppe_rfdetr_v1.pth`
   (SHA256 `3380fa7d…bf570`, 120,910,843 B). `ppe_rfdetr_v1.onnx` 는 같은 pth 를 변환한 것(메타에 원본 SHA 기록). YOLO `ppe_css_v1.pt` 는
   **롤백용**으로만 남아 있고(`backend` 를 yolo 로 바꿔야 쓰임) 현재 추론 경로에 없다. 단, **둘 다 같은 데이터셋**으로 학습됐다.
2. **학습 데이터 결함의 영향은 PPE 판정(Hardhat/NO-Hardhat/Safety-Vest/NO-Safety-Vest)에만 미친다.** 사람 검출은 별도 슬롯이고
   **COCO 사전학습 `rf-detr-nano.pth`**(파인튜닝 없음)로 돈다 — CSS 데이터를 본 적이 없다.
3. 데이터셋은 **Roboflow Universe "Construction Site Safety" v27**(CC BY 4.0). 겉보기 2,603장이지만 **고유 원본은 514장**(원본당 5배 증강),
   그중 **465장(18%)이 22개 영상에서 잘라낸 프레임**이다. **test 영상 6개 중 5개(83%)·valid 영상 15개 중 14개(93%)가 train 에도 들어 있다**
   → test/valid 는 held-out 이 아니라 **같은 영상의 이웃 프레임**이다. 기존 문서가 "test 82 mAP@50 75.62%" 를 인용해 왔는데, 이 수치는
   **낙관적**이다(`md/VIGENT 정확도 측정 기록.md` §69 의 "누출 가능성(미검증)" 이 이번에 검증됐다).
   → ★**T-0c 실측 정정(2026-09-25, §7 — 재검토 후 유지)**: 영상 단위로 누출을 제거한 held-out **91장**에서 다시 재니 10클래스
   mAP@50 **76.8%**(1차 stem 단위 156장은 76.3%) 로 75.62% 와 사실상 같았다. **분할 누출은 구조적으로 사실이지만, 이 데이터셋
   안에서는 점수를 눈에 띄게 부풀리지 않았다.** 단 91장·클래스별 박스 9~232개의 작은 표본이라 Wilson 95% 구간이 넓다(§7-2) —
   "부풀리지 않았다"는 mAP 점추정끼리의 비교이지 통계적 동등성 검정은 아니다. 현장 재현율과의 간극(§7-3)은 누출이 아니라
   **데이터셋↔현장 도메인 차이**로 봐야 한다(추정). "실성능 미확인" 단서는 그대로 유효하다(현장 정답지 없음).

## 1. 슬롯 ↔ 모델 매핑 (코드 실측)

| 슬롯 | 백엔드 | 가중치 | 학습 여부 | 출처 |
|---|---|---|---|---|
| **person** | rfdetr | `rf-detr-nano.pth` (COCO, `nano_coco_best_regular`, Apache-2.0) | **파인튜닝 없음** | `weights_manifest.json` · `vision.yaml:37` |
| **ppe** | rfdetr | **`ppe_rfdetr_v1.pth`** | CSS v27 파인튜닝 | `vision.yaml:31` · `MANIFEST.md` |
| ppe(롤백) | yolo | `ppe_css_v1.pt` | CSS 파인튜닝(같은 데이터) | `vision.yaml:58` · `weights_manifest.json` |
| fire_smoke / forklift | rfdetr | 별도(D-Fire / LOCO) | 이 감사 범위 밖 | — |

## 2. `ppe_rfdetr_v1.pth` — 체크포인트 메타 실측

| 항목 | 값 | 근거 |
|---|---|---|
| 아키텍처 | `RFDETRNano`, rfdetr 1.8.0, PyTorch-Lightning 2.6.5 | 체크포인트 `model_name`·`rfdetr_version` |
| 기반 가중치 | `rf-detr-nano.pth`(COCO) 위 파인튜닝 — `args.pretrain_weights` 필드는 체크포인트에 **없음**(rfdetr 기본 동작으로 추정) | `args` 79키 중 부재 |
| 데이터셋 경로 | `args.dataset_dir=/content/data/ppe_rfdetr_ds`, `dataset_file=roboflow` (Colab) | `args` |
| 에폭 | `epochs=50`, `early_stopping=False`, `warmup_epochs=0` | `args` |
| 스텝 | `global_step=8150` → 8150 ÷ 50 = **163 스텝/에폭** = 2,603장 ÷ (batch 8 × accum 2) ⇒ **2,603장 v27 로 50에폭 완주**(4,408장 `css_safety_aug` 아님 — 그쪽이면 275 스텝/에폭) | 계산 |
| 해상도 | `multi_scale=True`, `expanded_scales=True`, `square_resize_div_64=True`; 배포 추론 384 | `args`·adapter |
| 학습률 | lr 1e-4 · encoder 1.5e-4 · wd 1e-4 | `args` |
| EMA | `use_ema=True` 였으나 `early_stopping_use_ema=False`, EMA 전용 키 **없음** → 배포본은 `best_total`(기존 "best_ema" 표기는 오기, `MANIFEST.md` §정정) | 체크포인트 키 |
| 클래스(10) | `Hardhat, Mask, NO-Hardhat, NO-Mask, NO-Safety Vest, Person, Safety Cone, Safety Vest, machinery, vehicle` | `args.class_names`·ONNX `rfdetr_notes` |
| 학습 시점 | **정확한 일자 기록 없음.** 2026-07-05 MPS 시도는 NaN 발산으로 실패(`FINDINGS.md:91`) → 이후 Colab 재학습 → **2026-08-07 Drive 에서 내려받아 배치**. 즉 **07-05 ~ 08-07 사이** | `FINDINGS.md`·`MANIFEST.md` |
| 학습 노트북·Drive 링크 | **출처 불명**(미기록) | `MANIFEST.md:19-20` |
| 학습 로그(metrics.csv) | **없음**(Colab 산출물 미회수) → 어느 에폭이 best 였는지 **미확인** | `weights_manifest.json` note |
| 보고된 성능 | "test 82 box mAP@50 75.62%"(Colab) — **로컬 재현 없음**, 위 §3 누출로 **낙관적** | `vision.yaml:23-26` |

## 3. 학습 데이터셋 — CSS v27 실측 (`data/datasets/css_safety`, [W-1] 재확보본)

**출처**: `https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety/dataset/27` · workspace `roboflow-universe-projects` · CC BY 4.0
(`data.yaml` `roboflow` 필드 실측). **VIGENT 현장 CCTV 가 아니다.**

| 분할 | 파일 | 고유 원본 | 증강 배수 | 해상도 | 박스 |
|---|---|---|---|---|---|
| train | 2,603 | **514** | 원본당 5장(505개) · 10장(7개) · 4장(2개) | **640×640 전부** | 37,378 |
| valid | 114 | 113 | 1장 | 640×640 | 697 |
| test | 82 | 81 | 1장 | 640×640 | 760 |
| 합계 | 2,799 | 700(원본 stem 기준; `MANIFEST.md` 는 "원본 521장" 기록 — 차이 원인 미확인) | | | 38,835 |

★**해상도 분포는 640×640 단일**이다 — Roboflow export 가 리사이즈했다. 원본 화소 정보는 없다. 현장 CCTV(1280×720 이상, 원거리 소인물)와 다르다.

**클래스별 박스 수(전체 38,835)**

| 클래스 | train | valid | test | 전체 | VIGENT 사용 |
|---|---|---|---|---|---|
| Person | 9,691 | 166 | 174 | 10,031 | ✗ (사람은 COCO 모델이 맡음) |
| machinery | 5,238 | 55 | 44 | 5,337 | ✗ |
| NO-Safety Vest | 3,957 | 106 | 90 | 4,153 | ✓ |
| Hardhat | 3,362 | 79 | 110 | 3,551 | ✓ |
| NO-Mask | 3,209 | 74 | 79 | 3,362 | (학원 프로필 제외) |
| Safety Cone | 3,170 | 44 | 92 | 3,306 | ✗ |
| Safety Vest | 3,156 | 41 | 61 | 3,258 | ✓ |
| NO-Hardhat | 2,318 | 69 | 41 | 2,428 | ✓ |
| Mask | 1,743 | 21 | 28 | 1,792 | (학원 프로필 제외) |
| vehicle | 1,534 | 42 | 41 | 1,617 | ✗ |

→ 우리가 쓰는 4클래스는 전체 박스의 **35%**뿐이고, 증강 5배를 걷어내면 **원본 기준 약 2,700 박스**다.

### 3-1. 누출 검사 (이번 감사에서 새로 잰 것)

| 검사 | 결과 |
|---|---|
| 같은 원본(stem)이 분할을 넘나드는가 | train∩test **2/81(2%)** · train∩valid **6/113(5%)** — 소폭 |
| **같은 영상의 프레임이 분할을 넘나드는가** | 영상 유래 파일: train 465(22개 영상) · valid 22(15개) · test 12(6개). **train∩test 영상 5/6(83%)**, **train∩valid 14/15(93%)**. 예: `IMG_0871_mp4`(train 55프레임, test 2프레임), `construction-2-_mp4`, `autox3_mp4` |

**해석**: test 의 영상 유래 12장 중 대부분이 train 에 이웃 프레임을 두고 있다. 나머지 70장(사진)은 stem 이 다르지만 같은 현장·같은 사람일 수 있어
**stem 검사로는 못 본다**(미검증). 어느 쪽이든 "test 82 mAP 75.62%" 는 **일반화 성능이 아니다**.

★**보정(2026-09-25 T-0c 재검토)**: 위 표의 "22개 영상"은 `_mp4` 소문자 접미만 센 값이다. 확장자를 떼고(`_mov`·`_MP4`·`_MOV` 포함,
`IMG_0871_mp4`=`IMG_0871_MOV`) 다시 세면 **train 영상은 29개**, valid/test 에서 train 영상과 겹치는 프레임은 30장이 아니라 **40장**이다.
또 `youtube-N`(전체 180장, train 125·valid 35·test 24)은 확장자 표기가 없지만 **번호 인접 쌍이 연속 프레임**(§7-1)이라 영상 묶음으로 본다.

### 3-2. 이것이 왜 "결함"인가 (현장 실측과의 연결)

| 데이터 특성 | 현장에서 나타난 증상(실측) |
|---|---|
| 원본 514장(5배 증강으로 부풀림) · 640² 리사이즈 · 근접 촬영 위주 | 현장 재현율 person 38~59%(`bench` 09-13 이후) — 단 person 은 COCO 모델이라 **이 데이터 탓이 아니다** |
| 마스크 라벨이 필수 클래스로 학습됨 | 08-27 학원 490건 중 87건 "마스크 미착용 단독" 오탐 → 프로필에서 마스크 제외 |
| valid/test 가 train 과 같은 영상 | Colab mAP 75.62% ↔ 현장 PPE 성능 **미측정**(현장 정답지 없음) — 수치 간 간극이 설명된다 |

## 4. 롤백 모델 `ppe_css_v1.pt` (YOLO) — 메타 실측

| 항목 | 값 |
|---|---|
| 학습 | ultralytics **8.3.253**, **2026-06-29 23:33**, `imgsz=640`, `epochs=80`, `batch=8`, `pretrained=True`(`last.pt` 이어학습) |
| 데이터 | `…/data/datasets/css_safety/data.yaml` — **같은 CSS v27** |
| 클래스 | 위 10개 동일 |
| 체크포인트 | `epoch=-1`(최종본), 학습 결과 곡선 `train_results` 포함 |
| 라이선스 주의 | ultralytics(AGPL) — 배포에서 제거됨(A-4). 롤백 시 재검토 |

## 5. 못 찾은 것 (출처 불명 — 정직하게)

- Colab 노트북 링크 · Google Drive 파일 ID · 학습 실행 일자 · metrics.csv(에폭별 곡선) · "best" 선정 에폭.
- 원본 이미지의 실제 화소·촬영 장비·국가(Roboflow 공개셋 메타에 없음).
- `MANIFEST.md` 의 "원본 521장" 과 이번 stem 계수 700 의 차이 원인.
- `pretrain_weights` 필드 부재 — COCO nano 위 파인튜닝은 **추정**(rfdetr 기본값).

## 6. 재학습(T-1) 설계에 넘기는 요구사항

1. **분할은 영상·촬영 세션 단위**로(프레임·사진 단위 금지) — 이번 누출의 직접 교훈.
2. 검증분은 **학습 미사용**을 파일 목록으로 고정하고 이 문서처럼 stem·영상 교차 검사를 자동화(A-3 변환기에 포함).
3. 해상도는 원본 유지(리사이즈 export 금지) — 현장 원거리 소인물 대응.
4. 클래스 매핑표(A-2)에서 `Mask/NO-Mask` 는 프로필 의존으로 표기, `Safety Cone/machinery/vehicle` 은 제외 근거 기록.
5. 평가 3곳(AI Hub 검증분 / 사고영상 dev 74장 / 재방문 현장 정답지) — 앞의 둘은 "가망 확인", **배포 판단은 현장 정답지에서만**(T-2 원칙, 학습 스크립트 상단 자동 표기).

## 7. 정직한 기준선 (T-0c, 2026-09-25 · 재검토 20:14) — 재학습 비교표의 **"전" 행**

> **이 절 7-2 의 수치(영상 단위 held-out 91장)가 AI Hub 재학습 전후 비교표의 "전(v1)" 행이다.** "후" 모델은 **같은 파일 목록**
> (`benchmarks/results/v1_heldout_eval.json` 의 `heldout_files` 91장)으로 같은 스크립트(`scripts/eval/eval_v1_heldout.py --weights <새 가중치>`)를
> 돌려 나란히 적는다. 학습은 하지 않았다 — 기존 v1 가중치를 새 분할로 **평가만** 했다.
> ★**표본이 작다**: 91장, 우리 4클래스 GT 박스 407개(클래스별 62~146). 클래스별 값은 Wilson 95% 구간과 함께만 인용한다.

### 7-0. 재검토 경위 — 1차(156장)는 왜 기준선이 아닌가

1차(19:50)는 "원본 stem 이 train 에 없고, `_mp4` 소문자 접미 영상이 train 에 없는 것"만 걸렀다(156장). 재검토에서 전수 분류한 결과:

| 156장의 출처 | 장수 | train 에 같은 출처 | 판정 근거(측정) |
|---|---|---|---|
| 확장자 접미 영상 프레임(`_mp4/_mov/_MP4/_MOV-N`) | 12장 / 7영상 | **10장 / 5영상**이 train 과 같은 영상 | 확장자 뗀 영상 id 비교(`img_0871_mov` = train `IMG_0871_mp4`) — 1차 정규식이 `_mov`·대문자를 놓침 |
| `youtube-N`(확장자 표기 없음) | 55장 | train 125장 | 번호차 ≤3 인 쌍 129개 중 화소 NCC ≥0.8 인 쌍 2개(최대 **0.997** = 사실상 같은 프레임), 번호차 >20 쌍 1,417개 중 0개 → **연속 프레임 묶음**. held-out 후보 55장 중 **39장**이 train 에 번호차 ≤3 인 장을 둠. 파일명으로 영상을 나눌 수 없어 **묶음째 제외** |
| 그 밖의 사진 묶음(`construction-N-` 19, 숫자만 20, VOC `2009_` 7, `ppe_` 6, `class1_` 4 …) | 89장 | 묶음 단위로는 train 에도 있음 | 같은 인접 번호 검사에서 NCC ≥0.8 인접 쌍 **0개**(construction 17쌍·image 14쌍·img 8쌍 등) → 연속 프레임 증거 없음 → 남김. 단 "같은 현장·같은 사람" 수준 중복은 이 검사로 못 본다(**미검증 잔존 위험**) |

→ 156장 중 **65장(10 + 55)** 이 train 과 같은 영상 출처였다. 1차 결과(76.3%)는 **"stem 단위 제외(영상 누출 잔존)"** 로만 남기고
(`benchmarks/results/v1_heldout_stem_only_156.json`, `--split-rule stem` 으로 재현) **기준선으로 쓰지 않는다**.
화소 근접중복 검사(held-out 각 장 ↔ train 2,603장 최근접, dHash·NCC)도 했으나 train 이 증강본(회전·cutout·blur)이라 **같은 영상 프레임도
무작위 쌍과 구분되지 않아**(파일명상 같은 영상 10장의 최근접 NCC 0.43~0.77 vs 무작위 최대 0.61) 판정 근거로 쓰지 않았다.

### 7-1. held-out 구성 (영상 단위 제외, `--split-rule video`)

| 항목 | 값 | 근거 |
|---|---|---|
| 출발 집합 | CSS v27 valid+test **196장**(증강 없음, 640×640 export 그대로 — v1 학습 조건과 동일) | `data/datasets/css_safety/{valid,test}/images` |
| 제외 | 유래 영상(확장자 무시)이 train 에 있음 **40** · 원본 stem 이 train 에 있음 **8** · `youtube-N` 묶음 **57** | 스크립트 `build_heldout("video")` |
| **held-out** | **91장**(valid 51 · test 40) = 고유 원본 91 / 전체 원본 700 = **13.0%** · 영상 유래는 `autox`·`img_3093` 각 1장(둘 다 train 에 없음, 스크립트가 자동 검증) | JSON `heldout` |
| ★요구 "원본의 20% 이상" | **미충족(13.0%)** — 이것이 v1 이 안 본 이미지의 전부다. 더 늘리려면 train 원본을 섞어야 하므로 늘리지 않는다 | 스크립트 경고 |
| GT 박스 | 10클래스 **903개**, 우리 4클래스 **407개** | JSON `rows.gt` |
| 화소 근접중복 | held-out↔train 근접중복(NCC ≥0.8) **0쌍**(숫자만·construction 묶음 134장 전수 비교). 단 held-out 안의 `518`·`644`·`972`(valid) 세 장은 서로 NCC 0.97~0.98 로 사실상 같은 장면 — 유효 표본은 91보다 2장 적게 봐야 한다(제외하지 않고 단서만 둔다) | 2026-09-25 20:2x 검사 |
| 추론 조건 | rfdetr `predict`, 해상도 **384**(배포 조건), device cuda, 임계 0.05 로 전부 받아 AP 계산 | JSON `resolution/device` |
| 매칭 | IoU ≥ 0.5 · 클래스 일치 · 신뢰도순 1:1 그리디 · AP@50 전점 보간 | 스크립트 `match()/ap50()` |
| 운용점 P/R | 앱 임계 `detect.conf.ppe` = **0.35** 이상만. Wilson 95% 는 박스를 독립 시행으로 본 근사(한 장 안 박스는 완전 독립이 아님) | `config/tuning.yaml` · `wilson()` |
| 소요 | 91장 2.2초 | JSON `elapsed_s` |

### 7-2. 결과 — v1 held-out 91장 (측정 2026-09-25 20:14, 개발기 RTX 5070 Ti) ★재학습 비교표 "전" 행

| 클래스 | GT박스 | TP | FP | FN | P% | P Wilson95 | R% | R Wilson95 | AP50% |
|---|---|---|---|---|---|---|---|---|---|
| **Hardhat** | 146 | 127 | 15 | 19 | 89.4 | [83.3, 93.5] | 87.0 | [80.6, 91.5] | 90.2 |
| **NO-Hardhat** | 64 | 41 | 18 | 23 | 69.5 | [56.9, 79.7] | 64.1 | [51.8, 74.7] | **65.8** |
| **Safety Vest** | 62 | 50 | 13 | 12 | 79.4 | [67.8, 87.5] | 80.6 | [69.1, 88.6] | 82.8 |
| **NO-Safety Vest** | 135 | 113 | 17 | 22 | 86.9 | [80.1, 91.7] | 83.7 | [76.6, 89.0] | 86.3 |
| Mask | 22 | 12 | 4 | 10 | 75.0 | [50.5, 89.8] | 54.5 | [34.7, 73.1] | 57.8 |
| NO-Mask | 109 | 83 | 36 | 26 | 69.7 | [61.0, 77.3] | 76.1 | [67.3, 83.2] | 74.0 |
| Person(앙상블용) | 232 | 196 | 46 | 36 | 81.0 | [75.6, 85.4] | 84.5 | [79.3, 88.6] | 86.4 |
| Safety Cone | 82 | 40 | 11 | 42 | 78.4 | [65.4, 87.5] | 48.8 | [38.3, 59.4] | 52.1 |
| machinery | 42 | 37 | 15 | 5 | 71.2 | [57.7, 81.7] | 88.1 | [75.0, 94.8] | 90.3 |
| vehicle | 9 | 7 | 2 | 2 | 77.8 | [45.3, 93.7] | 77.8 | [45.3, 93.7] | 82.0 |
| **우리 4클래스 평균** | | | | | **81.3** | | **78.8** | | **81.3** |
| 10클래스 mAP@50 | | | | | | | | | **76.8** |

### 7-3. 나란히 — 네 숫자는 **서로 다른 것을 잰다**

| 측정 | 값 | 무엇을 재는가 | 비교 가능성 |
|---|---|---|---|
| Colab test 82장(누출 분할) | mAP@50 **75.62%** | 같은 데이터셋, train 과 겹치는 영상 포함 | 로컬 재현 기록 없음(§5) |
| 1차 held-out 156장 — **stem 단위 제외(영상 누출 잔존)** | 10클래스 mAP@50 **76.3%** · 우리 4클래스 AP50 81.7 · P 82.4 / R 79.4 | 같은 데이터셋, stem 은 다르지만 65장이 train 과 같은 영상 출처 | **기준선 아님**(§7-0). 기록용 |
| **held-out 91장(7-2, 영상 단위 제외)** | 10클래스 mAP@50 **76.8%** · 우리 4클래스 AP50 **81.3%** · P 81.3 / R 78.8 @0.35 | 같은 데이터셋, **train 과 영상·stem 이 겹치지 않는 원본** | ★재학습 "전" 행 — 후 모델과 **직접 비교 가능**. 표본 91장(작다) |
| 사고영상 dev 74장(2026-08-10 현장 기준선) | PPE 전체 정밀도 **93.6%**(TP160/FP11) · 재현율 **64.8%**(160/247) · NO-Hardhat 재현율 관측 구간 **[25.9%, 100%]**(n=14) | **현장 영상**, 앱 파이프라인(1fps·ByteTrack) 통과 후, 클래스별 표는 미기록 | 프로토콜이 달라 **위 줄들과 직접 비교 불가**. 재학습 후 같은 74장·같은 파이프라인으로 다시 재서 이 줄끼리 비교 |

출처: `benchmarks/v1_field_baseline_report.md:91-94`(dev 74장 수치) · `benchmarks/results/v1_heldout_eval.json`(91장 원자료) ·
`benchmarks/results/v1_heldout_stem_only_156.json`(1차 원자료).

### 7-4. 해석 (측정한 것만)

1. **누출이 점수를 부풀렸다는 가설은 이 측정으로도 지지되지 않는다.** 영상 단위 held-out 76.8% ≈ stem 단위 76.3% ≈ 누출 분할 75.62%.
   §0 의 "낙관적 표현은 과했다" 정정은 **유지**한다. 단 이는 mAP 점추정끼리의 비교이고 표본이 작다 — 클래스별 Wilson 구간(7-2)이
   ±10%p 안팎이므로 "같다"를 통계적으로 입증한 것은 아니다. 분할 결함 자체는 사실이며 재학습의 영상 단위 분할(§6-1)은 그대로 요구한다.
2. **NO-Hardhat 이 우리 4클래스 중 가장 약하다**(AP50 65.8, 재현율 64.1 [51.8, 74.7]). 현장 dev 에서 NO-Hardhat 재현율 하한 25.9% 였던
   것과 방향이 같다. 재학습의 1차 개선 목표를 여기 둔다.
3. **held-out 재현율 78.8 ↔ 현장 64.8 의 간극**은 같은 분포 안 검증으로는 설명되지 않으므로 **도메인 차이**(근접 촬영 640² 리사이즈
   ↔ 현장 CCTV 원거리·소인물)로 본다 — 단 이것은 **추론**이다. 현장 정답지가 생겨야 확정된다(§6-5).
4. 이 절은 "가망 확인" 용도다. **배포 판단은 현장 정답지에서만**(T-2 원칙) — 변함없다.

## 8. 재학습 목표 선언 (2026-09-25 확정 — T-1 착수 전에 선언한다, `P3_BACKLOG.md` B-finetune 과 동일)

**근거**: 안전상 가장 위험한 오류는 **미착용(NO-*)을 놓치는 것**이다 — 착용자를 미착용으로 오인하면 확인 한 번으로 끝나지만,
미착용자를 놓치면 경보가 아예 없다. 현재 v1 은 NO-Hardhat 재현율 **64.1 [51.8, 74.7]**(§7-2)로 우리 4클래스 중 가장 낮다.

| 순위 | 평가 집합 | 목표 | 현재(v1, "전") | 성격 |
|---|---|---|---|---|
| **1차** | held-out 91장(§7-2, @0.35, res 384) | **NO-Hardhat 재현율 ≥ 85%** · **NO-Safety Vest 재현율 ≥ 90%** · 정밀도는 각각 **≥ 69.5 / ≥ 86.9**(현재 수준 이상 유지) | R 64.1 / 83.7 · P 69.5 / 86.9 | 가망 확인 |
| **2차** | 사고영상 dev 74장(앱 파이프라인, `x4b_score_candidates.score_one`) | **PPE 전체 재현율 64.8 → ≥ 80%** | R 64.8 (160/247) · P 93.6 | 가망 확인 |
| **최종** | **재방문 현장 정답지**(미확보) | 클래스별 재현율 — 목표치는 정답지 확보 후 B-finetune 착수 조건(40px 이상 박스)과 함께 정한다 | 미확보 | **배포 판단은 여기서만** |

- 1차·2차는 "가망 확인"이다 — 둘 다 통과해도 배포하지 않고, 둘 중 하나가 미달이면 **재학습 설정을 다시 본다**(현장 정답지를 소비하지 않는다).
- 판정 도구: `scripts/eval/eval_v1_heldout.py --weights <새 가중치> [--dev74]` — "전(v1)" 행을 항상 나란히 찍고 위 목표 대비
  달성/미달/미측정을 표로 낸다(`GOALS` 상수 = 이 표). 현장 정답지가 없는 동안은 표에 **"미확보"** 로 남는다.
- 표본이 작다(§7 머리말). 1차 목표 판정은 점추정으로 하되 Wilson 구간을 같이 적고, 구간이 목표를 걸치면 "달성(구간 걸침)"으로 따로 표기한다.

## 9. `forklift_rfdetr_v1.pth` 출처 감사 (2026-09-26, T-0 와 같은 형식)

> 결론 먼저. ① 이 파일은 **LOCO(CC0) 지게차 211장(train)·맥 MPS·50 epoch** 으로 2026-07 초에 만든 RF-DETR Nano 단일 클래스 모델이다.
> ② 자기 검증 **mAP@50 8.83%** 는 LOCO test 238장+네거 80장, `predict` conf 0.001, 2026-07-04 조건의 값이다.
> ③ **"학원에서는 되고 510에서는 안 되는가" → 아니다. 학원에서도 안 된다.** 오늘 8/27 학원 영상 956프레임 재측정: 현장 YOLO 박스와
> IoU≥0.5 로 겹치는 RF-DETR 박스는 **conf 0.1 이상에서 0.5%**(5/935), 0.3 이상 **0%**. 지게차가 없는 507 이미지 720장에서도 **99.4%** 가
> conf 0.5 이상 박스를 낸다 — 신뢰도가 지게차 유무와 무관하다. ④ 대외에 인용된 **97.7% 는 이 모델의 값이 아니다.** 학원 프로파일의
> YOLO `forklift_boda_ax` 가 장면 대본 대비 낸 값이다(`benchmarks/field_academy_2026-08-27.md:32`).

### 9-1. 슬롯 ↔ 파일 매핑 [실측]

| 프로파일 | 지게차 슬롯 모델 | 근거 |
|---|---|---|
| 기본(safety) | `vigent-core/weights/forklift_rfdetr_v1.pth`(RF-DETR Nano, 클래스 `['forklift']`) — 단 `include_forklift: 0` 으로 **검출기 목록에서 제외**(2026-07-11) | `themes/safety/vision.yaml:16,30` · `config/tuning.yaml:109-124` |
| 학원(academy) | `vigent-core/weights/forklift_boda_ax.pt`(YOLO, AGPL) conf 0.50 | `themes/safety/vision.yaml:65` · `benchmarks/forklift_duel_2026-08-19.md` §0 |

### 9-2. 체크포인트 메타 [실측 — `torch.load(..., weights_only=False)['args']`]

| 항목 | 값 | 비고 |
|---|---|---|
| 파일 | 120,781,691 B · SHA256 `cd76eb56…` · mtime 2026-08-17 02:04 | 2026-08-17 Release `weights-v1` 복원본(`weights/MANIFEST.md:115,137`) — **학습 시점이 아니라 복원 시점** |
| `dataset_dir` | `/Users/nohyeonseong/Downloads/loco_forklift_ds`(맥, 저장소 밖) | `training/build_forklift_train_ds.py` 가 만든 폴더 |
| `class_names` / `num_classes` | `['forklift']` / 1 | 정상 대조군 poc 는 2(§9-5) |
| epochs / batch / grad_accum | 50 / 4 / 4(유효 16) | `training/rfdetr_train.py` 도크스트링과 일치 |
| lr / lr_encoder / weight_decay / clip | 1e-4 / 1.5e-4 / 1e-4 / 0.1 | rfdetr 기본값과 같음 |
| warmup / use_ema / multi_scale / expanded_scales / seed | 0 / True / True / True / **None** | seed 없음 → 재현 불가 |
| 해상도 | **기록 없음**(`args` 에 `resolution` 키 없음) | RF-DETR Nano 기본 384 로 **추정**. 오늘 384/512 로 돌려도 거동 동일(§9-4) |
| 장치 | MPS(Apple GPU) | `rfdetr_train.py` 도크스트링 "MPS, 야간 무인". 학습 로그(`metrics.csv`)는 **이 PC 에 없음**(Glob 미발견) — 회수본 분석은 `audit/salvage_recovery_2026-08-20.md` §3-2 인용 |
| 저장 가중치의 NaN | **0 / 466 텐서** | ★salvage 문서의 "NaN 가중치가 저장됐다" 는 표현과 **다르다**(§9-5) |

### 9-3. 학습 데이터 [실측: `training/build_forklift_train_ds.py` · `benchmarks/EVAL.md:146-160`]

| 항목 | 값 | 꼬리표 |
|---|---|---|
| 원천 | **LOCO**(Logistics Objects in Context, CC0) `loco-all-v1.json` category 5 = forklift. 지게차 인스턴스 598 / 449장 | [문서상 주장, EVAL.md] |
| 분할 | SHA256 결정적 — **test 238장/316 인스턴스(0.55 상향)** + 네거 80장(pallet_truck 40·일반 40) 격리, 나머지 **train 211장** → valid 10%(`score("v_"+name)<0.10`) | [실측, 스크립트] |
| 학습에 들어간 수량 | 211장 중 valid 약 21 → train **약 190장**(정확 수는 매니페스트 `forklift_eval_manifest.json` 재계산 필요 — 이 PC 에 데이터 없음) | [추정] |
| 이미지 특성 | 창고형 **전동 리치트럭·팔레트트럭** 중심(LOCO). 학원의 카운터밸런스 지게차와 다른 도메인 — YOLO boda_ax 도 LOCO 교차 검증에서 재현율 21.4%(`audit/salvage_recovery_2026-08-20.md` §3-1) | [실측, 타 모델] |
| 라이선스 | CC0 (`attribution/SOURCES.md`). ★같은 파일의 `forklift_merge`(Roboflow 6종) 는 **재학습용 후보**이지 v1 학습 재료가 아니다 | [실측] |

### 9-4. 자기 검증 8.83% 의 조건과 오늘 재측정

**8.83% 의 조건** [문서상 주장, `benchmarks/COVERAGE.md:13` · `EVAL.md:146-160`]: LOCO test 238장(316 인스턴스)+네거 80장, `run_eval.py` COCOeval, `predict` conf **0.001**, 2026-07-04. 같은 셋에서 pipeline 8.5%. ★같은 EVAL.md 의 forklift 표는 **7.61 / 3.15** 를 적고 있는데 이는 **직전 YOLO 모델**의 값이고(COVERAGE.md 가 "YOLO(7.61/3.15) 초과" 로 구분), RF-DETR v1 의 raw 8.83 은 COVERAGE.md 에만 있다 — 원자료 JSON 은 이 PC 에서 못 찾았다 [미확인]. presence 지표(recall 58.4/35.7, FAR 50/28.7)도 **YOLO 모델 줄**이며 RF-DETR v1 의 presence 값은 문서에 없다.

**오늘 재측정** [실측 2026-09-26, RTX 5070 Ti, rfdetr 1.8.0, res 384, `predict(threshold=0.001)`] — 원자료 `audit/forklift_field_rerun_20260926.json` · `audit/forklift_aihub_imagelevel_20260926.json` · `audit/forklift_box_geom_20260926.json`(git 미추적):

| 집합 | 프레임/장 | 지게차 있음(기준) | ≥1 박스 @conf 0.1 / 0.3 / 0.5 | **기준 박스와 IoU≥0.5 일치** @0.05 / 0.1 / 0.3 | 읽는 법 |
|---|---|---|---|---|---|
| **8/27 학원 9장면(overlay.mp4 640×360)** | 956 | 현장 YOLO `forklift_present` 938(98.1%) · COCO truck/car 945(98.8%) | 81.0 / 56.0 / 48.7% | **1.6 / 0.5 / 0.0%**(기준 박스 있는 935프레임) | 박스는 내지만 **지게차 위에 있지 않다** |
| 510 VS_03 **양성**(GT 지게차 있음) | 144 | 144 | 100 / 99.3 / 97.2% | 23.6 / 0.0 / 0.0% | A-4 의 R 23.6% 와 같은 사실 |
| 510 VS_03 **음성**(GT 없음) | 2,399 | 0 | **99.1 / 94.8 / 91.4%** | — | 지게차 없는 사진에도 conf 0.9 박스 |
| 507 개구부 표본 **음성** | 720 | 0 | **100 / 99.7 / 99.4%** | — | 〃 (top conf 중앙값 0.914) |
| 빈 화면·잡음 6장 | 6 | 0 | 0 / 0 / 0% | — | 질감이 있는 실사진에만 난사 |

- 학원 장면별로는 06b·06c·07(지게차가 크게 잡히는 위험구역 장면)에서 conf 0.5 이상이 86~97% 인데, 그 박스가 현장 YOLO 박스와 IoU≥0.5 로 겹치는 비율은 **0%** 다. 01(정지)·00(스모크)은 top conf 중앙값 0.06~0.07 로 8/19 측정(`audit/academy_g1g2_2026-08-19.md:32`, 최대 0.003)과 크기는 다르지만 "낮다"는 방향은 같다. ★8/19 의 0.003 과 오늘의 0.9 차이는 **원인 미확인**(rfdetr 버전·전처리 차이 가능성 [추측]) — 어느 쪽이든 판정은 같다.
- 단서: overlay.mp4 는 **박스·글자가 그려진 표시용 영상**이며 원본은 미보존(규칙 11 사고). 정답은 장면 대본. 그래도 "기준 YOLO 박스와 겹치는가"는 그림과 무관하게 잴 수 있다.
- **답**: "학원에서는 되고 510에서는 안 된다" 가 **아니라 어디서도 지게차를 국소화하지 못한다.** A-4 의 510 재현율 23.6%(@0.002) 는 이미지당 13개씩 난사한 박스가 우연히 겹친 몫으로 읽어야 한다.

### 9-5. F-7 진단과 오늘 실측의 차이 (정직하게)

`audit/salvage_recovery_2026-08-20.md` §3-2 [문서상 주장, 회수 `metrics.csv` 분석]: `train/loss_ce` 가 **epoch 1 부터 NaN**, bbox/giou 손실 ~0 붕괴, `val/mAP_50` 0.193→0.0, 49 epoch 완주. 대조군 poc(num_classes=2)·fire_e17 은 정상. 원인 가설 `num_classes=1` 은 미확정.
오늘 확인한 것 [실측]: ① 저장된 텐서에 NaN 은 없다(0/466) — "NaN 가중치가 저장됐다" 는 **부정확**하고, "손실이 NaN 이 된 뒤 갱신이 멈춘(또는 무의미해진) 가중치" 가 맞는 표현이다. ② 출력은 "균일 저신뢰"(tuning.yaml:110) 가 아니라 **입력 질감에 반응하는 고신뢰 박스 난사**다. 둘 다 "학습이 안 됐다" 는 결론은 같다.
→ 재학습(510 forklift) 착수 조건: NaN 감시(1 epoch 에서 중단)·seed 고정·`resolution` 기록·num_classes 재현 실험·held-out 은 **영상 단위**(§6-1) — `scripts/train/finetune_rfdetr.py` 가 이미 갖춘 것은 seed·held-out 제외·누출 검사이고, **NaN 감시는 아직 없다**(추가 필요).

### 9-6. 대외 인용 정리

| 수치 | 실제 출처 | 단서(인용처마다 병기) |
|---|---|---|
| **97.7%** (908/929) | 학원 프로파일 **YOLO `forklift_boda_ax`** @0.50, 장면 대본 대비, 2026-08-27 단일 세션 | "`forklift_rfdetr_v1` 의 값이 아님 · 장면 대본 기준 · 카운터밸런스 한정" — 단서 적용처: `benchmarks/field_academy_2026-08-27.md` · `reports/현장테스트_보고서_20260827*.md` · `reports/_template.html` · `docs/onboarding/01·04` · `docs/사업계획서_VIGENT_초안.md:45,142,275` · `scripts/fill_business_plan.py` · `docs/review/ALGORITHM_TRUTH_20260926.md` |
| 99.1% | 같은 YOLO, `forklift_test.mp4` 320프레임(학원 유사) | 이미 "카운터밸런스 한정" 표기 있음(`proposal_base` Q4) |
| 8.83% / 8.5% | `forklift_rfdetr_v1` LOCO 자기 검증(2026-07-04) | 오늘 재측정으로 **"국소화 0%"** 를 병기 |

### 9-7. 재학습 우선순위 변경 + forklift 목표 선언 (2026-09-26 대표 결정)

**우선순위**: **1순위 = forklift(510)** · 2순위 = NO-Hardhat(507, §8). 근거: Apache 스택에 작동하는 지게차 검출기가 없다(v1 = NaN 학습·아무 데나 0.9 박스, §9-4). 작동하는 `forklift_boda_ax` 는 **AGPL** 이라 B2G 배포 불가. 근접 규칙(`proximity_hazard`, high)이 이 슬롯에 의존한다.

| 평가 집합 | 목표 | 현재(v1, "전") | 성격 |
|---|---|---|---|
| **510 held-out**(장소 단위 val, `aihub_to_vigent.py --dataset 510`, 판정 집합) | **AP50 ≥ 70%** · **지게차 없는 이미지에서 conf≥0.5 오탐 ≤ 1%/장** | 같은 집합 기준선은 VS_07 수신 후 `forklift_compare_harness.py --write-baseline` 으로 잰다(미기록). 변환 [실측 2026-09-26]: 라벨 520,720 → 영상당 20장 34,247프레임 · 장소 23/7(val 장소 F01·F02·G02·G11·G13·G14·G19, 7,491프레임) · 누출 통과. 지금 이미지 있는 val 은 VS_03 분 **26장(전부 지게차 없음)** 뿐 → v1 오탐 **26/26 = 100% [87.1, 100]**(파이프라인 확인용, 기준선 아님). 스모크(VS_03 2,543장) AP50 0.0 · 음성 91.4% [참고] | 판정 |
| 8/27 학원 overlay 956프레임 | 목표 없음 — 현장 YOLO 박스와 IoU≥0.5 일치율·≥1박스 비율을 나란히 | 일치 0.0% @0.5 / 0.5% @0.1 (§9-4) | **참고**(정답 = 대본·원본 미보존) |
| 참고 열 | `forklift_boda_ax` YOLO 대본 대비 97.7% · present 98.1% | — | **후보 아님**(AGPL) |

- 판정 도구: `scripts/eval/forklift_compare_harness.py --weights <새 가중치> --label <이름>` — 전(v1)/후/참고 세 행 + 목표 달성/미달/미측정. 학습 스크립트가 `harness: forklift` 설정이면 자동 호출.
- 학습 전 필수(구현 완료·테스트 `tests/test_finetune_guards.py`): NaN 감시(손실·지표 NaN/inf 시 즉시 중단, 직전 체크포인트 보존) · seed 고정 · `resolution`·`seed`·args 전부를 체크포인트 `args.notes` 에 기록하고 학습 뒤 검증 · CUDA 강제(MPS 금지).
- 설정: `configs/finetune_aihub_forklift_v2.yaml` — 클래스 `[person, forklift]`(단일 클래스 NaN 가설 회피), 시작점 COCO nano(v1 은 발산 가중치), `max_train: 5000`(스모크 1회 상한, 대표 승인 범위).
- ★의존성: rfdetr 1.8 `train()` 은 pytorch_lightning 이 필요한데 **개발기 .venv 에 없다**(2026-09-26 확인). 설치(`pip install "rfdetr[train,loggers]"`)는 대표 승인 뒤.
- 순서(다운로드 완료 후): A-4 재실행(forklift·NO-Hardhat) → A-5 `--dry-run` → forklift 스모크 파인튜닝 1회(승인) → 결과 표 → 그 다음 PPE.
- ★**결과(2026-09-26 21:29 [실측])**: 스모크 1회(train 5,000·10 epoch·COCO nano 시작·person+forklift) → 510 held-out 3,561장 **AP50 94.3 [93.6, 95.0]** · R@0.5 88.1 [87.0, 89.1] · P 97.7 [97.1, 98.2] · 510 음성 오탐 **0/101 = 0.0 [0.0, 3.7]**(목표 ≤1% 는 구간 걸침) · 507 음성 1.4 [0.9, 2.0](n=2,000, 참고) · 학원 956 IoU≥0.5 일치 **96.4 %**(v1 0.0). 상세·단서: [forklift_finetune_smoke_20260926.md](forklift_finetune_smoke_20260926.md). 1차 실행은 검증 후처리 정체로 중단(§7-1 ALGORITHM_TRUTH·NEXT.md).
