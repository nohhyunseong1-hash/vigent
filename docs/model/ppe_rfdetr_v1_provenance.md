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
