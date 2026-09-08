# Phase 2 — 모델·추론 품질 + 하드웨어 사양 산정 검토

> 작성 2026-09-08 · 대상 브랜치 `audit/cleanup-20260906`(HEAD d4517fc) · 검토자: 수석 아키텍트/ML 감사 관점
> 방법: 코드·설정·저장소 내 실측 문서를 **읽고 재대조**한 것만 근거로 적었다(`파일:줄`). 서버·벤치는 새로 띄우지 않았다.
> 수치는 전부 저장소 안 실측 문서에서 **측정 날짜·구성**과 함께 인용했다. 읽지 못한 것은 "확인 필요"로 남겼다.
> ※ 병렬 보조 조사 3건(용량 문서 / 평가 문서 / 최적화·이식성·버전·drift)의 발췌를 반영했고, 판단에 쓰인 핵심 근거(노트북 2026-08-22 실측표·현장 v1.2 생존율·피드백 스텁·Dockerfile COPY 경로)는 내가 원문을 다시 열어 확인했다.
>
> **★검토 지시문과 다른 사실 1건**: 지시문은 "현장 노트북 용량 실측 없음"이라 했으나, `docs/academy_visit_day.md:718-741` 에 **2026-08-22 노트북(i7-10750H/GTX 1650 Ti) capacity_probe 램프 실측**(한계 6대·권장 4대)이 있다. 다만 `docs/LAPTOP_SIZING_PILOT4.md` 가 요구하는 **4h 소크·10항목 판정은 전부 미측정**이 맞다. 두 사실을 §0·§7 에 나눠 적었다.

---

## 0. 먼저 — 이 검토가 선 하드웨어 사실

| 항목 | 사실 | 근거 |
|---|---|---|
| 저장소가 지금 돌아가는 기계 | **데스크톱** `DESKTOP-STLQ1LM` · AMD Ryzen 9 9900X(12C/24T) · **RTX 5070 Ti 16,303 MiB** · 드라이버 610.74 · torch 2.12+cu130 | 이 세션 `hostname`·`nvidia-smi` 출력(2026-09-08) · `benchmarks/capacity_report.md:30` · `docs/edgebox_purchase_guide.md:43` · `requirements.txt:38` |
| 대표가 부르는 이름 | "개발용 노트북" — 그러나 사양은 위와 같다. 저장소 문서도 스스로 이를 경고한다 | `docs/ops_capacity_sizing.md:22-25` "개발기 사양: Ryzen 9 9900X·RTX 5070 Ti … 절대 대수를 그대로 배포 사양으로 쓰지 말 것" |
| 현장 후보 노트북 | i7-10750H / GTX 1650 Ti 4GB / 16GB / 1TB(Win10 Pro, torch cu126). **램프 실측 1회 있음(2026-08-22: 한계 6대·권장 4대, N=4 검출 p95 675ms, 한계 시 CPU 94.9%·VRAM ≈1.47GB)** — 그러나 **4h 소크·PILOT4 10항목 판정은 전부 "미측정"** | `docs/academy_visit_day.md:718-741` · `md/DEPLOYMENT.md:22` · `docs/LAPTOP_SIZING_PILOT4.md:3,6-8,112-123` |
| 오늘(2026-09-08) 드라이런 | 데스크톱에서 카메라 4대(파일) 7분 — **판정 무효**(소크 0.1h<4h)이나 수치는 실측 | `audit/loadtest_20260908_2122_devpc_dryrun.md:1,5-6,21-34` |

**결론**: 이 문서의 하드웨어 산정은 **데스크톱 실측에서 뽑은 카메라당 단가 → 4대 환산**이 주축이며, 환산 가정은 §7에 전부 적었다. 노트북은 램프 1회(2026-08-22)만 있고 소크는 없다. **Jetson·산업용 PC 실측은 0건**이다.

★**역할 정정(2026-09-09, 대표 지시)**: **배포기 = 현장 노트북**(i7-10750H / GTX 1650 Ti 4GB / 16GB / 1TB / Win10 Pro, `md/DEPLOYMENT.md:22`), **개발기 = 이 데스크톱**(현장에 가지 않음). 이 문서 §6-2·§7 의 데스크톱 행은 **개발기 값**이며 노트북 판정에는 카메라당 단가 환산을 거쳐서만 참고한다. 배포기의 성능 근거는 **2026-08-22 램프 실측이 유일**(`docs/academy_visit_day.md:718-741`: 한계 6·권장 4, N=4 p95 675ms, CPU 94.9%·GPU 40%·VRAM 1.47GB) — 벤치마크 결론(병목 CPU·GPU 는 논다·VRAM 4GB 충분)은 노트북 램프에서도 같은 방향으로 확인됐으므로 **유효**하고, 4대 상시 여부는 노트북 4h 소크로만 확정한다. 2026-09-09 개발기 1h 소크(`audit/loadtest_20260908_2356_desktop_1h.md`)는 **현장 판정에 사용 불가**(다른 기계·1h)이며, 유일한 소득은 오늘 드라이런의 VRAM 4.0GB·util 89% 신호가 **개발기의 다른 앱(게임·브라우저 등) 몫**이고 서버 몫은 ≈1.1~1.2GB 라는 확정이다(§6-2 이상 신호 절 참조). 하드웨어 교체 전 소프트웨어 부하 감축 선택지와 노트북 벤치마크 절차는 FINAL-REPORT §5-3.

---

## 1. 모델별 아키텍처·입력·클래스·학습 데이터 근거표

운영 슬롯(`themes/safety/vision.yaml:16` `backend: {person: rfdetr, ppe: rfdetr, fire_smoke: rfdetr, forklift: rfdetr}`), 워커 기본 슬롯은 `person+ppe(+fire_smoke)`, forklift 기본 제외(`vigent-core/worker.py:118-131`).

| 슬롯 | 아키텍처 / 가중치 | 입력 해상도 | 출력 클래스(운용) | 학습 데이터 출처 | 저장소 내 정확도 근거(날짜·구성) | 운용 임계 |
|---|---|---|---|---|---|---|
| person | **RF-DETR Nano, COCO 사전학습**(`rf-detr-nano.pth` 366,287,238B, required) — 커스텀 가중치 없음, COCO 80종 중 `person`만 통과 | **384**(로드 시 컴파일 고정, 호출별 변경 불가) | person | Roboflow COCO 체크포인트(외부) | mAP@50 raw 93.9%·33.8ms(주석, 측정 조건 미기재) | 0.40 |
| | `vision.yaml:16,33-38` · `weights_manifest.json` 항목 0 | `config/tuning.yaml:88` · `detectors/rfdetr_adapter.py:9-14,167-171` | `rfdetr_adapter.py:275-276` | `weights_manifest.json` url | `vision.yaml:14` | `tuning.yaml:102` |
| ppe | RF-DETR Nano 파인튜닝 `ppe_rfdetr_v1.pth`(120,910,843B, required, sha 3380fa7d…) | 384 | 10종 중 7종 사용: Hardhat/NO-Hardhat/Safety-Vest/NO-Safety-Vest/Mask/NO-Mask/Person(앙상블) | **Roboflow Universe "Construction Site Safety" v27**(CC BY 4.0, 원본 521장→증강 2,605장, 데이터셋 자체 내장 증강 cutout/blur/rotate) | Colab test 82장 box mAP@50 **75.62%**(게이트 ≥73.2) — 단 **ema/total 어느 체크포인트를 쟀는지 로컬 재현 기록 없음**; v1 현장 기준선(2026-08-10, 109장) PPE 정밀도 dev 93.6/test 95.9, 재현율 64.8/61.0 | 0.35 |
| | `vision.yaml:21-31` · `weights_manifest.json` 항목 4 | `tuning.yaml:88` | `vigent-core/weights/MANIFEST.md:24` | `MANIFEST.md:22,34-43` | `vision.yaml:23-26` · `benchmarks/v1_field_baseline_report.md:91-92` | `tuning.yaml:103` |
| fire_smoke | RF-DETR Nano 파인튜닝 `fire_smoke_rfdetr_v1_e17.pth`(required) | 384 | `smoke`,`fire` | D-Fire(Colab, 30ep 중 17ep val 피크) | D-Fire test 395 box mAP@50 **80.13%**(in-domain) — **현장 재검증 대기** | 클래스별(`fire_smoke_per_class`) |
| | `vision.yaml:19-20,30` | | `MANIFEST.md:97` | `vision.yaml:19` | `vision.yaml:19-20` | `tuning.yaml:116-120` |
| forklift(전역) | RF-DETR Nano 파인튜닝 `forklift_rfdetr_v1.pth`(required — 파일 없으면 기동 거부) | 384 | `forklift` | LOCO | box mAP@50 **8.83%**, 정탐 conf p50 0.002 ≈ 오탐(F-7) → **기본 슬롯 제외** | 0.002(병적) |
| | `vision.yaml:18,29` · `weights_manifest.json` 항목 7 | | `MANIFEST.md:97` | `vision.yaml:18` | `vision.yaml:18` · `tuning.yaml:110-111` · `worker.py:118-131,135-138` | `tuning.yaml:110` |
| forklift(학원 프로파일) | **YOLO(ultralytics, AGPL)** `forklift_boda_ax.pt` 6,274,161B — AX안전 유산 | guard `IMGSZ`(tuning 384) | 2종(Forklift, Load) | BODA(출처 상세 미기록) | 2026-08-19 320프레임: conf 0.50에서 재현율 **99.1%**·최장 공백 0.5s. 단 **LOCO 도메인 재현율 21.4%**(도메인 취약) | 0.50 |
| | `deploy/academy/profile_intent.yaml:36-55` · `config/models_inventory.md:13` | `guard.py:896-898` | `models_inventory.md:13` | `models_inventory.md:3-5` | `benchmarks/forklift_duel_2026-08-19.md:13,17,51` | `profile_intent.yaml:37` |
| pose(근골격) | **RTMPose-m body7 256×192 + YOLOX-m humanart**(rtmlib, ONNX) — onnxruntime **CPU** 고정 | 256×192(모델 고정) | COCO-17 키포인트 → REBA 지표 | OpenMMLab 공개 가중치 | 정확도 실측 없음(패리티 문서 `benchmarks/POSE_PARITY.md` — 확인 필요) | kp conf 0.3 |
| | `worker.py:361-383` · `pose/rtmpose_adapter.py:22-25` · `weights_manifest.json` 항목 11-12 | | `worker.py:386` | manifest url | — | `worker.py:373` |
| privacy | YuNet(`cv2.FaceDetectorYN`, 232,589B, optional) | 동적 | 얼굴 박스 | opencv_zoo | — | 0.6 |
| | `privacy.py:17,50-71` · manifest 항목 10 | | | manifest note | | `privacy.py:71` |
| VLM(보조) | `mlx-community/Qwen2.5-VL-7B-Instruct-4bit` — **MLX(Apple 전용)** 설정이 Windows 데스크톱에 그대로 남아 있음 | — | JSON 5필드 | — | — | — |
| | `vision.yaml:97-103` · `rfdetr_service.py:204-227`(`/tmp` 경로) | | | | **확인 필요**: Windows 에서 VLM 확정(vlm_confirm) 경로가 실제 동작하는지 | |

**설정-실제 불일치(문서 부패)**: `vision.yaml:71-74`는 "ByteTrack 미구현·미사용"이라 적혀 있으나 실제 운영은 `tuning.yaml:193 track.algo: bytetrack` + `guard.py:636-655,744-800`으로 ByteTrack 이 켜져 있다. `vision.yaml:65-70`은 포즈 백엔드를 "worker.py 가 yolov8n-pose.pt 를 직접 로드"라 적었으나 실제는 RTMPose(`worker.py:361-383`). 둘 다 설정 파일 주석이 실제 동작과 반대다(→ 이슈 #14).

---

## 2. 평가 체계 — 무엇이 측정됐고 무엇이 없는가

### 2-1. 존재하는 측정치(날짜·구성 포함)

| 지표 | 값 | 날짜·구성 | 근거 |
|---|---|---|---|
| person 정밀도/재현율 — **IoU 트래커 시절** | dev 84.9/**68.2** · test 77.3/**77.3** | 2026-08-10 · imgsz 384 · person conf 0.40 · 사고영상 9종 109장(dev 74/test 35) · **주간만** | `v1_field_baseline_report.md:88-89,126-130` |
| person 재현율 — **ByteTrack 운영 재측정** | dev **38.2%**(정밀도 84.5) · test **59.1%**(정밀도 100.0) | 2026-08-25 · 같은 dev/test · `track.algo: bytetrack`(2026-08-13 채택) · 1fps 표본 | `v1_field_baseline_report.md:61-64` · `x5_recall_knobs_interim.md:49-53` |
| person **검출 직전 vs 추적 후** | 검출 직전 71.3%(원거리 83%) → 추적 후 **42.0%(원거리 8%)**; ByteTrack 단독 표에선 원거리(화면높이<10%) **0%** | 2026-08-25 dev 74장 GT 157건 | `v1_field_baseline_report.md:66-73` · `x5_recall_knobs_interim.md:52,59-60` |
| PPE 전체 정밀도/재현율 | dev 93.6/64.8 · test 95.9/61.0 | 2026-08-10(추적 무관 — PPE 는 추적 필터 미적용) | `v1_field_baseline_report.md:64,91-92` |
| NO-Hardhat 재현율 구간 | dev [25.9%,100%] n=14 · test [55.2%,80.0%] n=20 | 2026-08-10 | `v1_field_baseline_report.md:94` |
| 학원 현장 시험 — 지게차 검출 | 04 주행 135/137(99%) | 2026-08-27 · boda_ax YOLO conf 0.50 · 929프레임·**정답=장면 대본(프레임 라벨 아님)** | `field_academy_2026-08-27.md:11-17,23,30` |
| 학원 — 안전모 판정 일치율 | 전체 85.6% · **캐빈 67.9%** · 지상 98.4%(박스 높이 중앙값 캐빈 0.24 vs 지상 0.82) | 2026-08-27 | `field_academy_2026-08-27.md:42-46` |
| 학원 — person 검출률(재현율 아님) | 지상 연속 체류 271/273(99%) · 캐빈 258/469(55%, 하한) | 2026-08-27 | `field_academy_2026-08-27.md:54-55` |
| 학원 — person 오검출 | 0/70 프레임(사람 없는 장면) | 2026-08-27 | `field_academy_2026-08-27.md:61` |
| 학원 — G5 운전자 오인(지면 사람을 운전자로) | **10/210(4.8%)**, 최장 약 2.1초 연속 | 2026-08-27 · driver_containment 0.65 | `field_academy_2026-08-27.md:63,69-75` |
| forklift RF-DETR(전역) | 재현율 2.8%·conf 0.003 → 폐기(원인: epoch 1 loss NaN 발산 후 완주, val mAP50 0.193→0.0) | 2026-08-19 | `forklift_duel_2026-08-19.md:6` · `audit/salvage_recovery_2026-08-20.md:99-100` |
| person 재현율 — MIN_FRAMES=0 적용본("대외 인용 기준") | dev **42.0%**[35,50]/정밀도 82.5 · test 59.1%[44,72]/100.0 | 2026-08-25 · 1fps 표본 | `x5_experiments_2_3.md:10,14-15` |
| 클래스별(dev/test, 2026-08-25) | NO-Hardhat dev P30.4/R**25.9**·test 61.5/55.2 · NO-Safety-Vest dev 68.2/67.0·test 71.4/58.8 · Hardhat dev 66.3/87.3(test n=1) · Mask/Safety-Vest 표본 부족 | 동상 | `x5_experiments_2_3.md:12-21` |
| 학원 현장 — **추적 생존율(GT 없음)** | **88.3%**(3,843프레임·실효 1.88fps) → "추적이 버리는 몫" dev 29.3%p → 현장 **11.7%**. 현행 트래커 유지 확정, passthrough 보류 | 2026-08-27 v1.2 | `reports/현장테스트_보고서_20260827_v1.2.md:297-308` |
| 학원 — 운전자 오인 **v1.2 정정** | **26/344 = 7.6%**(최장 2.1초) — 1차 집계 4.8%(10/210)를 개정 | 2026-08-27 v1.2 | `reports/현장테스트_보고서_20260827_v1.2.md:31,143,152` |
| 야간 무인 오탐 — 화각 변경 후 | **14/14 = 100%**(conf 0.508~0.733) — 화각 변경으로도 개선 안 됨 | 2026-08-22 | `m2_night_person.md:110-116` |

### 2-2. 없는 것(저장소 grep·문서 확인 결과)

| 항목 | 상태 | 근거 |
|---|---|---|
| **person 재현율 목표치** | **없음** — 온보딩 문서가 스스로 "★미지수 — 목표치를 정하지 못했다"고 적음. 숫자로 선언된 것은 forklift 학원 C1 ≥80%, 라벨링 계획의 상대 기준(캐빈 67.9→80%, 지상 −2%p 이내, 재현율 +5%p), 트래커 생존율 ≥85% 뿐 | `docs/onboarding/09_앞으로_6개월.md:56` · `forklift_duel_2026-08-19.md:35` · `docs/labeling_plan.md:186-190` · `reports/…v1.2.md:302-303` |
| 혼동행렬(검출 클래스) | **없음** — 저장소 전체 grep 유일 히트 `vigent-core/evaluator.py:65` 는 에이전트 판정용 docstring | 이 세션 grep + 보조 조사 |
| 클래스별 mAP(현 배포 구성) | **없음** — 있는 것은 2026-07-04 구 YOLO 구성(`ppe_css_v1.pt` 6클래스 mAP@0.5 46.5~72.7)과 COVERAGE 슬롯 mAP(person 93.92·ppe 75.20·forklift 8.83)뿐. field_eval 계열 mAP는 순환오염으로 **인용 금지** | `md/VIGENT 정확도 측정 기록.md:44-49` · `benchmarks/COVERAGE.md:10-13` · `field_eval_results.md:47-50` |
| 클래스별 재현율(현장 109장, 분할 전) | NO-Mask 100%(19) · Hardhat 84.4%(64) · NO-Safety-Vest 63.0%(146) · **NO-Hardhat 36.1%(83)** · Safety-Vest 2건 | `field_eval_results.md:56-61` |
| 2fps 정답지 기반 재현율 | **없음** — dev 수치 전부 1fps 표본 | `x5_tracker_comparison.md:123-124` |
| 지게차 정밀도(오검출률) | **측정 불가**(지게차 없는 장면 0개) | `reports/…v1.2.md:66` |
| 현장 유사 조건 테스트셋 | 부분 — 사고영상 9종 109장(주간, 1인 1회 검수, 조끼 양성 2건) + 학원 929프레임(**프레임 GT 없음, 원본 미보존**) | `v1_field_baseline_report.md:126-136` · `docs/labeling_plan.md:27-51` |
| 조끼 단독 성능 | 주장 불가(양성 2건) | `v1_field_baseline_report.md:131-133` |
| 안전대(하네스) | 클래스 자체가 없음 — 재학습으로 불가, 새 모델 필요 | `docs/detection_limits.md:67-80` |

**핵심 판정**: 경보 경로의 person 재현율은 **dev 38.2~42.0%**(2026-08-25 구성, 1fps 표본)다. 규칙 9 사고(68~77% 인용)는 문서상 정정됐고, **재현율 손실이 모델이 아니라 추적기 정책**임이 실측됐다(`v1:66-73`). 현장 1.88fps 에서는 생존율 88.3%로 손실이 11.7%로 줄었으나(`v1.2:306-308`) **그 값은 GT 없는 생존율**이지 재현율이 아니다. 대책(검출통과)은 "1프레임 단발이라 디바운스를 못 넘음 → 기본 off·보류"(`v1:84-87`, `v1.2:304`)로 멈춰 있다. 즉 **정답지가 있는 측정에서는 원거리 0~8%, 정답지가 없는 현장에서는 "괜찮아 보임"** — 이 간극을 메울 2fps 정답지 측정이 없다.

---

## 3. 열악 조건별 테스트 데이터·증강 전략

| 조건 | 테스트 데이터 | 측정치 | 증강 전략 | 근거 |
|---|---|---|---|---|
| 야간/저조도 | 무인(사람 없음) 2회만 | **무인 오탐 86.4%**(2026-08-20, 실내 조명 켜짐) → 화각 변경 후 **100%**(2026-08-22). 원인은 어둠이 아니라 화각(큰 물체 덩어리). **유인 재현율·소등·IR 흑백 전환 전부 미측정**, 조도(lux) 미측정 | 없음 | `benchmarks/m2_night_person.md:15-18,26-36,67-69,110-116` · `v1_field_baseline_report.md:130` · `SAFETY_REVIEW_REPORT.md:276` |
| 역광 | **없음** | 미측정(현장 리포트 명시) | 없음 | `field_academy_2026-08-27.md:128` · `docs/onboarding/04_지금_성능.md:59` |
| 비·안개·분진 | **없음**(분진은 위험성평가 시나리오 JSON 텍스트뿐) | 없음 | 없음 | `datasets/goldens/T1/cases/T1_case_15_dust_work.json` · `detection_limits.md:61` |
| 렌즈 오염 | **없음**(grep 0건) | 없음 | 없음 | 보조 조사 grep |
| 흔들림/모션블러 | 포즈 오발화 측정만(낙상 급강하 30건/387프레임, 원인 블러 키포인트) | 검출 재현율 관점 없음 | **블러/JPEG/대비저하 증강은 전면 폐기**("놓친 것과 잡힌 것의 흐림 차이 없음") | `box_quality_b2_findings.md:40-53` · `benchmarks/v1_augmentation_preview.py:3-4` · `s1_miss_montage.md:51-52` |
| 원거리 소형 | dev 74장 "작은박스(화면높이<10%)" 대리지표(GT 12~14건) | ByteTrack 후 **0~8%**(IoU 83%); 원거리 안전모 66프레임 중 33프레임 임계(0.35) 미달; 크롭 2단계는 원거리 48.3→10.0% 붕괴(기각); 놓친 NO-Hardhat 40건 100%가 소형(<1%) | 축소 증강 데이터셋 구축(`x3_build_augmented_dataset.py`) → 재학습 **기각**(dev 전 지표 하락) | `x5_recall_knobs_interim.md:59-60,125` · `detection_limits.md:37` · `r1_person_crop_ppe.md:7,34-37` · `s1_miss_montage.md:18` · `x4b_score_candidates.md:18-29` |
| 가림 | 실카메라 6c(1인), 학원 캐빈, dev person FN 50건(프록시) | 가림 최장 7.49초 카운트 0(트랙 생존); 캐빈 안전모 67.9%; 가림 재현율 0/50 | random erasing + copy-paste 가림 증강 재학습 → 가림 2/50(4%)이나 전 지표 하락 → **기각** | `pa_live_camera_verify.md:54-70` · `field_academy_2026-08-27.md:42-48` · `x4b_score_candidates.md:5-29` |
| 군집/다인 | multi_scene.mp4(4~6명), tp3 3인 교차 | 고유 tid 42→13/17(iou→bytetrack); tp3 재식별 0%(단절 24회); crowd 임계 6명 영향 **미측정** | 없음 | `track_ab_bytetrack.md:9,47` · `eval_tracking_2026-08-18.md:34-43` · `tapo_test_video_eval_2026-08-19.md:98` · `b_passthru_results.md:167-169` |
| 학습 시 증강 설정 | — | — | `training/rfdetr_train.py:40-46` 은 `RFDETRNano().train(...)` **라이브러리 기본값**(증강·시드 인자 없음). css v27 은 Roboflow 내장 증강(cutout·blur·rotate) | `training/rfdetr_train.py:40-46` · `MANIFEST.md:43` |
| 조달 요건 문서 | "원거리·역광·야간·부분가림 등 현장 유사 조건 포함" — **요건으로만 존재** | — | — | `benchmarks/COVERAGE.md:28` |

→ 8개 열악 조건 중 **측정이 있는 것은 야간(무인만)·원거리·가림·군집 4개**, 역광·비안개분진·렌즈오염은 데이터 자체가 없고, 흔들림은 증강이 폐기됐다. 시도된 증강(가림·축소)은 전부 dev 에서 기각됐다 — 즉 "현재 배포 모델은 증강 없이 공개셋 그대로 학습된 상태"다. 재촬영 계획(`docs/refield_plan.md:35-51`)에도 **야간·역광·우천·분진 항목이 없다**.

---

## 4. 트래킹과 체류·근접·진입/이탈 판정 안정성

| 항목 | 코드 사실 | 실측 | 판정 |
|---|---|---|---|
| 알고리즘 | person 슬롯만 ByteTrack(`trackers` 2.4.0), 나머지 클래스는 자체 IoU+중심점 그리디(`_track_iou`) | — | `guard.py:304-311,636-655,744-800,803-861` · `tuning.yaml:193` |
| ByteTrack 파라미터 | frame_rate=10·lost_buffer=30 → 내부 환산 **10프레임**(2.3fps ≈4.3초); 활성 임계 = person conf 0.40 자동 연동; min_frames=1 | 2026-08-13 실카메라: 11.55초 부재 후 동일 id 복원(모순) — 원인: **person 0건이면 `bt.update()` 미호출 → 트래커 시간 정지** | `guard.py:316-333,335-349` · `pa_live_camera_verify.md:36-52` |
| tid 교체 빈도 | — | 학원 이동 중 **20초에 4회**(2026-08-27); 단독 보행 30초 0회; 1.07초 부재에 새 id, 11.55초 부재는 동일 id(재진입 위치 의존 추정, 미검증) | `field_academy_2026-08-27.md:122` · `pa_live_camera_verify.md:24-52` |
| 별도 트래커 2벌 | `rfdetr_service.py:80`은 라이브러리 기본값 ByteTrackTracker 를 **또 하나** 생성(웹 `/rfdetr/*` 경로) — guard 와 파라미터·tid 공간이 다르다 | — | `rfdetr_service.py:75-80` vs `guard.py:774-782` |
| 구역 진입/이탈 | 발끝(하단 중앙) 기준, 시간 디바운스 enter 1.0s/exit 1.0s; 첫 관측은 항상 '밖' | 학원 06 1차: 9프레임 스침 → **미발화(체류 1초 미달)**; 06b: 구역이 밟을 수 없는 위치 → 미발화; 재작도 후 발화 | `zone_debounce.py:30-52,75-99` · `tuning.yaml:239` · `field_academy_2026-08-27.md:89-92` |
| "멈추지 않고 통과하는 침입자" | enter_s 1.0s + 2fps + tid 교체 4회/20초 조합 | **미측정**(리포트 자체가 명시) | `field_academy_2026-08-27.md:122-123` |
| 체류/카운트 | 가림 시 카운트가 0으로 떨어짐(트랙은 생존) — PM-2 설계 입력 | 카운트 0 7.92초/89.6초=8.8% | `pa_live_camera_verify.md:54-70` |
| 근접(협착) 디바운스 | enter 0.4s / exit 1.0s(구역보다 짧게 — 서행 통과 고려) | — | `tuning.yaml:38-44` |
| 히스테리시스 | PPE 3프레임·화재 2프레임(프레임 기준 — 캐던스 변동 시 시간이 흔들림) | — | `guard.py:290,1092-1095` · `zone_debounce.py:7-10`(같은 문제의식) |

**판정**: 추적은 "정지 체류"에는 안정, "이동·교차·가림"에는 파편화·재식별 실패가 실측됐다. 경보 판정은 **1초 체류**를 요구하므로 통과형 침입은 설계상 놓칠 수 있고, 그 시나리오는 **아직 재지 않았다**.

---

## 5. 캘리브레이션 — 픽셀→실거리

| 항목 | 사실 | 근거 |
|---|---|---|
| 호모그래피/BEV/카메라 캘리브레이션 | **없음**. `homograph|호모그래피|BEV|calibrat` grep: `vigent-core/*.py`·`routers/*.py`·`docs/*.md` 0건(proximity.py 주석의 "확장 가능" 언급뿐) | 이 세션 grep · `proximity.py:9` |
| 거리 추정 방식 | 장비 박스 **가로폭(정규화)**을 실제 폭(forklift 2.5m 등)으로 나눠 m/unit → 사람-장비 박스 최단 간격 × m/unit | `proximity.py:16-19,103-112` |
| 세로 스케일 | aspect_hw 로 x 스케일 환산(정사각 가정 폴백) — 원근·깊이 보정 없음 | `proximity.py:67-74,83` |
| 오탐 필터 | 박스 폭>0.9 또는 면적>0.7 인 장비만 제외 | `proximity.py:22-26,93-96` |
| 운전자 제외 | person 박스가 장비 박스에 ≥0.65 포함되면 탑승자로 보고 **근접 쌍에서 제외** | `proximity.py:29-38,106-110` |
| 실측된 한계 | 지면에 선 사람이 운전자로 오인 — 1차 집계 10/210(4.8%), **v1.2 개정 26/344 = 7.6%, 최장 2.1초 연속** → 그 시간 동안 **협착 경보 대상에서 빠진다**. 리포트 스스로 "운전자 판정에 깊이 정보가 없다 — 안전 관련·최우선". 운전자 제외 적용 시 근접 쌍 발생 94.4%→38.1%(320프레임) | `field_academy_2026-08-27.md:63,69-75,118-121` · `reports/…v1.2.md:31,143,152` · `forklift_duel_2026-08-19.md:129` |

**근접 경고 정확성 한계(명시)**: 장비가 카메라를 향해 비스듬히 서면 가로폭이 줄어 m/unit 이 커져 **거리 과대추정→미탐**, 사람이 장비보다 카메라에 가까우면 픽셀 간격이 실거리보다 커져 역시 **미탐** 방향. 반대 상황은 오탐. 어느 쪽도 정량화된 오차 실측이 없다("거리 실측 안 함", `x5_recall_knobs_interim.md:125`).

---

## 6. 추론 최적화 현황과 4대 동시 처리 실측

### 6-1. 최적화 현황(코드 확인)

| 기법 | 상태 | 근거 |
|---|---|---|
| TensorRT | **없음**(`tensorrt|TensorRT` grep vigent-core/scripts 0건) | 이 세션 grep |
| fp16/half/int8(서빙) | **없음** — torch fp32. int8 은 벤치 스크립트 옵션에만 존재(`c2_onnx_cpu_bench.py:213`); V2 는 fp16 을 "CPU EP 에서 이득 없을 것으로 추정(미검증)"으로 부결 | `v2_onnx_report.md:100` |
| ONNX Runtime | opt-in(`detect.backend: onnx-cpu`, 기본 torch) · **CPUExecutionProvider 고정** — GPU EP 없음. ★**RF-DETR `.onnx` 4종이 `weights_manifest.json` 에 미등재** → 클린 클론에서 `fetch_weights --all` 해도 안 오고, `onnx_path.exists()` False 면 **경고 없이 torch 폴백**(`:199`). export 스크립트 없음(`scripts/export_*` 0건, 수동 절차만 `MANIFEST.md:74-102`) | `rfdetr_adapter.py:16-23,118-121,195-208` · `tuning.yaml:80` · `weights_manifest.json` 14항목 대조 |
| INT8 / OpenVINO / torch.compile / amp | INT8 측정 후 기각(fp32보다 느림·정확도 −1.6~2.4%p); OpenVINO·compile·amp 코드 0건 | `onnx_cpu_bench.md:46,56-63` |
| ORT 세션 튜닝 | 기본 on: intra_op 4·spin off → 카메라당 CPU 2.10→1.55코어(2026-08-19) | `ort_tune.py:8-11,29-36` · `e1_bottleneck_report.md:62-63` |
| 멀티스트림 배치 | **없음** — 카메라별 워커 스레드 → `guard.detect` → 슬롯별 **순차** 단일 프레임(`unsqueeze(0)`) 추론 | `worker.py:1024-1026` · `guard.py:970-976` · `rfdetr_adapter.py:151` |
| 추론 직렬화 | **모든 카메라 워커가 `DETECT_LOCK`(RLock) 하나를 공유** → GPU 추론은 프로세스 전체에서 1개씩 | `worker.py:1007` · `app_state.py:35` · `main.py:502` |
| 해상도 | 384 고정(960/640/1280 모두 dev 실측 악화 — 원인 미검증) | `tuning.yaml:88-105` · `v1_field_baseline_report.md:158` |
| 포즈 | onnxruntime **CPU**(GPU 미사용), pose_fps 2 별도 스레드 | `rtmpose_adapter.py:22` · `worker.py:96-98,946-975` |

### 6-2. 실측(데스크톱, 3슬롯 person+ppe+fire_smoke, 카메라당 2fps)

| 항목 | 값 | 날짜·구성 | 근거 |
|---|---|---|---|
| 1대 검출 지연 | p50 94ms / p95 105ms · 검출주기 p95 0.40s · GPU util 16.9% | 2026-08-18 · Ryzen 9 9900X + RTX 5070 Ti · 실카메라 1 + 모의 | `capacity_report.md:61` |
| 5대 | 전체 p95 82ms · 실카 p95 96ms · GPU mem 18.0% · util p95 37% → PASS(권장 상한) | 동상 | `capacity_report.md:68` |
| 7대(한계) / 8대(붕괴) | 7대 p95 116ms PASS · 8대 p95 **309ms**(2.7배) FAIL, GPU mem 18.8% util 23% | 동상 | `capacity_report.md:13-14,70,76-79` |
| 병목 | **CPU(추론 전후처리)** — 디코드·GIL 기각, 락은 부차(N≈10.7 에서 포화) | 2026-08-18 E1 | `e1_bottleneck_report.md:11-30` |
| 카메라당 CPU | 2.1 논리코어 → ORT 튜닝 후 **1.55**(재현 1.52) | 2026-08-18/19 | `capacity_report.md:92` · `e1_bottleneck_report.md:62` |
| 카메라당 CPU 구조 | 검출 1.07코어(슬롯 무관 고정)+0.106×슬롯 + 검출 밖 0.65 | 2026-08-18 V1 | `v1_slot_config_report.md:45-60` |
| fps 비례성 | 검출 CPU 는 fps 에 정비례(2.0→1.38, 1.0→0.71코어) | 2026-08-19 V3 | `v3_fps_report.md:11-20` |
| VRAM | 4슬롯 1,474MiB · 1슬롯 477MiB(단독), 카메라당 +5MiB | 2026-08-18 V1 | `v1_slot_config_report.md:18` · `INFRA_REQUIREMENTS.md:29` |
| CPU 전용(torch-CPU) | 3슬롯 2fps 검출 3.78코어 + 0.65 = **4.43코어/카메라** → 필요 환산코어 6.33(i7-10700급, 1대) · ONNX-CPU 는 지연 2.2배 빠르나 CPU 1.7배 더 씀 | 2026-08-19 V2 | `v2_onnx_report.md:13-19,127-136,170-176` |
| **오늘 4대 7분 드라이런** | 시스템 CPU 31~57% · 서버 6.3~7.5코어 · **GPU util 1→17→83~89%** · **VRAM 2.56→4.0GB** · 검출 p95 카메라별 40~108ms(0~2분) → **92~202ms(3분 이후)** · age p95 ≤0.5s · dropped 0 | 2026-09-08 · 파일 카메라 4대 · 판정 무효(소크 0.1h) | `audit/loadtest_20260908_2122_devpc_dryrun.md:5-10,21-34` |

**★오늘 드라이런의 이상 신호 — 2026-09-09 해소**: 서버 종료 후에도 `nvidia-smi` 7,660MiB·util 19% 가 남아 있었고 게임·브라우저 등 30여 개 데스크톱 프로세스가 GPU 를 쓰고 있었다(FINAL-REPORT §5-4). 서버 몫은 총사용 차분 ≈1.1~1.2GB 로 2026-08-18 기준선과 부합한다 → "GPU 는 병목 아님·VRAM 1.5GB 충분" 유지. 아래 원문은 기록으로 남긴다. 3분 시점에 GPU util 17→83%, VRAM 2.6→4.0GB, 검출 p95 가 약 2배로 뛰었다. 2026-08-18 기준선(5~7대에서 util 31~37%, VRAM 1.4GB)과 **정면 배치**된다. 같은 GPU 를 다른 프로세스(다른 에이전트 벤치·VLM 등)가 썼는지, 서버 자체가 커졌는지 이 문서만으로 구분할 수 없다(→ 확인 질문 Q1). 만약 서버 자체라면 "GPU 는 병목 아님·4GB 면 충분" 이라는 구매 전제(`edgebox_purchase_guide.md:18-29`)가 흔들린다.

---

## 7. 하드웨어 산정표 — 4대 · 2fps · 3슬롯 기준

**환산 가정(전부 명시)**
- G1. 카메라당 CPU **1.55 논리코어**(Ryzen 9 9900X 기준, GPU 있음, ORT 튜닝 on) — `e1_bottleneck_report.md:62`. 오늘 드라이런은 7.5코어/4대 = **1.9코어/카메라**로 더 높다(`loadtest…:28`) — 두 값 모두 표기.
- G2. 여유율 0.70(한계) × 0.75(권장) — `edgebox_purchase_guide.md:64-65`.
- G3. "환산코어" = 24 × (후보 PassMark Mark ÷ 54,322) — `edgebox_purchase_guide.md:53`. 후보 CPU 의 PassMark 값은 저장소에 i5-8500(3.12)·i5-10400(5.29)·i7-10700(7.06)·N100(1.61)만 있다(`v2_onnx_report.md:170`). **i7-10750H·Jetson·산업용 CPU 값은 저장소에 없음**.
- G4. VRAM = 1.4GB(3슬롯) + 4×5MiB ≈ **1.5GB**(V1). 오늘 관측 **4.0GB** 는 원인 미확정(§6-2).
- G5. CPU 전용은 torch-CPU 4.43코어/카메라(V2, ORT 튜닝 **전** 값 — 튜닝 후 재측정 없음, `INFRA_REQUIREMENTS.md:31`).
- G6. 카메라 fps 1.0 으로 낮추면 검출 CPU 는 절반, 검출 밖 0.65 는 고정/비례 미분해(`v3_fps_report.md:25-27`).

| 플랫폼 | 필요 CPU(4대) | 필요 VRAM | 예상 여유 | 실측 여부 | 비고 |
|---|---|---|---|---|---|
| **데스크톱(현 개발기)** Ryzen 9 9900X + RTX 5070 Ti 16GB | 4×1.55 = 6.2코어(오늘 실측 6.3~7.5코어) / 24 논리 | 1.5GB(실측 오늘 4.0GB) / 16GB | 한계 7대·권장 5대 → **4대 여유 있음** | ✅ 2026-08-18 램프 + 2026-09-08 드라이런 | 유일한 실측 플랫폼. 배포 사양 아님 |
| **CPU 전용(x86, GPU 없음)** | 4×4.43 = **17.7코어** → 필요 환산코어 17.7÷0.70 = **25.3**(> 9900X 의 24) | 0 | **불성립**(2fps). 1fps 로 낮추면 4×2.88=11.5 → 16.5 환산코어(i7-10700 두 개 급) | ⚠ 1대 실측(V2)에서 선형 환산 | `v2_onnx_report.md:170-176`. ORT 튜닝 후 CPU 전용 재측정 없음 |
| **현장 노트북** i7-10750H + GTX 1650 Ti 4GB(6C/12T) | 공식: 6.2코어 ÷ 0.70 = **8.9 환산코어** 필요(i7-10750H 환산값 저장소에 없음). **실측(2026-08-22 램프)**: N=4 검출 p95 **675ms**(N=3 220ms → 3배 급증), N=6 한계(972ms, CPU **94.9%**), N=7 탈락 | 실측 VRAM 36% ≈ **1.47GB**(GPU util 37~40%) — GPU 는 병목 아님. 오늘 데스크톱 4.0GB 현상이 노트북에서 재현되면 초과 | **한계 6 · 권장 4 — 4대는 급증 직후라 "여유 넉넉하지 않음", 상시 4대면 재실측 권고**(리포트 자체 문구). 3h 소크는 파일 카메라 **2대**만(RSS −52MB/h) | ⚠ 램프 1회 + 2대 소크. **4대 4h 소크·스로틀링·경보 지연 10항목은 전부 미측정**. 1차 램프(2026-08-21)는 유령 카메라로 무효였음 | `docs/academy_visit_day.md:718-741` · `audit/soak_after_fixes_2026-08-26.md:6-19` · `audit/measure_watch_20260821_224702.md:7`(76샘플 전부 스로틀링 회차 있음) · `audit/capacity_probe_invalid_2026-08-21.md:10-49` · `LAPTOP_SIZING_PILOT4.md:114-123` |
| **소비자 GPU 박스(RTX 4060급 + i5-12400급)** | 8.9 환산코어(위 동일) | 8GB 중 1.5~4GB | CPU 가 결정 — i5-12400 환산값 저장소에 없음 | ❌ 실측 없음 | GPU 는 "CPU 절약 장치"(`edgebox_purchase_guide.md:18`) |
| **Jetson Orin Nano 8GB / Orin NX 16GB** | ARM 6/8코어 — 카메라당 코어 단가 **실측 없음**. x86 단가를 대입하면 Nano 6코어 < 6.2코어 | 통합 메모리 8/16GB(VRAM 분리 없음) | 판단 불가 | ❌ 실측 없음 · 저장소 문서가 **"❌ 현재 부적합 — ARM 용 torch·RF-DETR 미검증"** 으로 선언 · **이식 리스크 高**(아래) | `docs/INFRA_REQUIREMENTS.md:42` · `edgebox_purchase_guide.md:209` · `ops_capacity_sizing.md:129,139`. TensorRT 없음·배치 없음 → Jetson 의 강점을 못 씀 |
| **산업용 팬리스 PC(i7-1185GRE급 + 선택 dGPU)** | 8.9 환산코어(GPU 있을 때) | 1.5~4GB | CPU 환산값 저장소에 없음 | ❌ 실측 없음 | 팬리스 지속 클럭 저하 미고려 |

**Jetson 이식 리스크(코드 확인)**
- torch 는 `cu130` x86 휠로 고정, "Jetson 은 기기용 휠 별도"(`requirements.txt:29-41`, `Dockerfile:12-13`) — rfdetr 1.8.0 이 torch/torchvision 에 의존하므로 NVIDIA JetPack 휠 조합 검증 필요.
- 서빙 ONNX 경로는 `CPUExecutionProvider` 하드코딩(`rfdetr_adapter.py:119`, `ort_tune.py:110`) → Jetson 에서 ONNX 를 써도 GPU 를 안 쓴다.
- TensorRT·fp16 없음(§6-1) → Jetson 의 실효 성능은 CPU 전용 단가(4.43코어/카메라)에 가깝다고 봐야 하며, ARM 6코어로는 4대 2fps 불성립 가능성이 크다(추정).
- 배포 스크립트·서비스는 Windows 전제(`run.bat`·`run.ps1`·`deploy/windows/`·`go2rtc.exe` win64 고정, `weights_manifest.json` 항목 13). VLM 은 `/tmp` 경로·MLX(`rfdetr_service.py:224,242`).
- `device.py:25-39` 는 cuda→mps→cpu 선택만 있고 Jetson 특유(통합 메모리·전력 모드) 처리 없음. `jetson|orin|aarch64` 언급은 Dockerfile 주석·device.py docstring 뿐.

---

## 8. 모델 버전 관리·재현성·롤백

| 항목 | 상태 | 근거 |
|---|---|---|
| 가중치 매니페스트 | 14항목(가중치 13 + go2rtc): file/slot/backend/version/**sha256/size_bytes**/url/required 전 항목 존재(license 4개·note 5개만). required 6종. `fetch_weights.py` 가 sha256 대조, `readiness.py:71-113` 이 필수 누락 시 기동 중단, `/health` 가 sha16 노출. **결함**: `verified_note` 가 "전 10종"(현재 14) 그대로, rf-detr-nano 는 업스트림 직결(Release 미러 "후속 과제"), RF-DETR `.onnx` 4종 미등재 | `weights_manifest.json:2,188-189` · `scripts/fetch_weights.py:45-46,152-155` · `vigent-core/readiness.py:71-113` · `routers/system.py:45-56` |
| 인벤토리 문서 3중화 | `config/models_inventory.md`(2026-06-19, RF-DETR 0줄, 열거 파일 다수가 weights/·manifest 에 없음) ↔ `weights/MANIFEST.md` ↔ `weights_manifest.json` — "정본"을 자칭하는 문서가 실제와 불일치 | `config/models_inventory.md:3-24` · `AUDIT_REPORT.md:157` |
| Dockerfile | `COPY VERSION weights_manifest.json fetch_weights.py ./` — 실제 파일은 `scripts/fetch_weights.py`(루트에 없음, 이 세션 `ls` 확인) → **컨테이너 빌드 실패 소지**. arm64 는 "torch 별도" 주석만 | `Dockerfile:12-14,38` |
| required 정합 | forklift_rfdetr_v1 은 기본 슬롯 제외인데 required=True(파일 없으면 기동 거부) — 의도적(주석) | manifest 항목 7 note · `md/DEPLOYMENT.md:210` |
| 제품 버전 ↔ 모델 버전 | VERSION 0.2.0 = manifest product_version. RELEASES.md 는 코드 태그 축(`v1.0.1-server-verified`)만 — **모델 세트 버전 태그 없음** | `VERSION` · `md/RELEASES.md:3-10` |
| 체크포인트 출처 | ppe: "best_ema" 주석이 오기였고 실제 best_total(파일 크기로 추정). **Colab mAP 75.62% 가 어느 체크포인트인지 미확인**, metrics.csv 미회수, Drive 출처 미기록 | `vision.yaml:21-26` · manifest 항목 4 purpose · `MANIFEST.md:19` |
| 학습 재현성 | `rfdetr_train.py` 인자: dataset_dir/epochs/batch/grad_accum/device 만. **시드 고정은 저장소 어디에도 없음**, 증강·lr 은 라이브러리 기본. `training/README.md` 는 파일 목록뿐(데이터셋 경로·에폭·하이퍼파라미터 미기록). Colab 노트북은 epochs 15·batch 8·**office-dataset v5**(삭제된 테마 데이터) 기록. `train_merged.py` 는 mac 절대경로 하드코딩 | `training/rfdetr_train.py:19-46` · `training/README.md:9-23` · `colab/VIGENT_finetune_rfdetr.ipynb` · `training/train_merged.py:3-7` |
| 롤백 절차 | 수동: `vision.yaml backend.<slot>=yolo` + detectors 주석 해제 + ultralytics 설치 + 재시작. **순서를 틀리면 `_get_model` 이 None 을 돌려 person 검출이 조용히 죽는다**(F31 로 DEGRADED 는 뜸) | `vision.yaml:27,41-46` · `yolo_adapter.py:11-12` · `guard.py:882-885` |
| 카나리/A-B 배포 | 없음(재기동 전면 교체) | `yolo_adapter.py:12`(F-6) |
| 측정=배포 보증 | `v1.0.1-server-verified` 태그: 서버 검출기 = EVAL 수치 Δ0.00(F-8 COCO 조용한 폴백 차단) | `md/RELEASES.md:6` |

---

## 9. drift 감시·재학습 루프

| 고리 | 상태 | 근거 |
|---|---|---|
| 오탐 피드백 입력(UI/API) | **없음** — `/recognition/log` 페이로드에 정오 라벨 필드 없음(`{rule, level, score, site, note, image, source}`); 유일한 메모 엔드포인트 `/recognition/note` 는 **본문이 `return {"ok": True}` 뿐인 스텁**(이 세션 원문 확인); `/recognition/pin` 은 보존 표시일 뿐 | `routers/recognition.py:32-44,58-60,76-90` · `data_engine.py:9-10,121-122` |
| VLM 자동 오탐 판정 | `vlm_confirm.py` 가 REJECT/SUPPRESS 확률을 계산하지만 **그 판정을 라벨로 영속화하지 않음** | `vlm_confirm.py:46-47,95` · `routers/zone.py:107` |
| 저장된 이벤트의 소비처 | dashboard 집계·scribe 위험성평가서·retention 파기뿐 — **학습·평가 스크립트가 `data/evidence`·`data/recognition` 을 읽는 코드 0건** | `dashboard.py:40` · `agents/scribe.py:257` · 보조 조사 grep |
| 프레임 수집 | 워커 `collect_on` 이면 주기적으로 원본 JPEG 저장(라벨 없음). 재학습 입력 디렉터리 `data/retrain/`·`data/dataset/` 은 **존재하지 않음** | `worker.py:986-993,746-752` · `ls data/` |
| 재학습 스크립트 | `ml/merge_retrain_data.py`·`ml/train_retrain.py` = **office 테마(사람↔모니터 혼동) YOLO11 용 — 테마 삭제(Z-3)로 사실상 사장** · `training/prelabel.py`·`train_safety.py` 플라이휠도 **ultralytics(YOLO)** 기준 → 운영 RF-DETR 과 **모델 계열 불일치** | `ml/merge_retrain_data.py:1-7` · `ml/train_retrain.py:1-20` · `training/README.md:14` |
| 현장 데이터 → GT | 2026-08-27 929프레임 **원본 미보존(오버레이만)** → 재학습·재평가 불가, 재방문 필요. 라벨링 계획(층화 표본)은 있으나 실행 전 | `docs/labeling_plan.md:27-51,96-132` |
| 런타임 검출 통계 감시(클래스별 검출률·conf 분포·경보율) | 슬롯 DEGRADED(로드/추론 연속 실패 3회)·healthy/degraded/unhealthy 는 **생존·고장 감지**뿐. **클래스별 검출률 시계열·conf 분포·Prometheus `/metrics` 전부 0건**. `check_profile_drift.py` 는 설정 파일 드리프트(모델 무관) | `guard.py:277-283,940-960` · `health_status.py:1-28` · `scripts/check_profile_drift.py:1-27` · 보조 조사 grep(`prometheus|/metrics|Counter(` 0건) |
| 기준선 재측정 게이트 | 규칙 9 로 문서화됐으나 **CI/스크립트로 강제되지 않음**(CI 게이트 4종은 ruff/mypy/unittest/OpenAPI) | `CLAUDE.md` 규칙 9 · 코드 품질 게이트 절 |

→ 체인 `운영 검출 → 이벤트/증거 저장 → [사람의 정오 판정: 없음] → [학습이 읽음: 0건] → [재학습 입력 디렉터리: 없음] → 재학습(YOLO/AGPL, 사장된 office 용) → [배포 반영: 수동 복사]` — **7개 고리 중 4개가 끊겨 있고**, 살아 있는 재학습 코드는 **배포 모델(RF-DETR)이 아닌 YOLO** 를 겨냥한다. 라벨링 계획서(`docs/labeling_plan.md`) 자체는 판정 기준 사전 선언 등 품질이 높으나 원본 부재로 착수 불가 상태다.

---

## 10. 이슈 목록

| # | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| 1 | **P0** | 경보 경로 person 재현율 dev 38~42%·원거리 0~8% — 추적기가 검출을 버림. 현장 생존율 88.3%는 GT 없는 값이라 반증이 못 됨 | `x5_recall_knobs_interim.md:49-60` · `x5_experiments_2_3.md:35` · `v1_field_baseline_report.md:61-87` · `reports/…v1.2.md:297-308` · `guard.py:744-800` | 위험구역 침입·협착 **미탐**. 원거리(작은) 작업자는 사실상 안 보임 | ①**2fps 정답지**로 재현율 재측정(현재 전부 1fps) ②검출통과(passthrough)를 디바운스와 맞물리게 재설계 ③ByteTrack 빈 프레임 update 호출(백로그 PQ) ④person 재현율 **목표치 선언**(예: 원거리 포함 ≥80%)과 CI 회귀 게이트 | M |
| 2 | **P0** | 통과형 침입자(멈추지 않고 지나감) 미측정 — enter_s 1.0s + 2fps + tid 교체 4회/20초 | `zone_debounce.py:30-31,95` · `tuning.yaml:239` · `field_academy_2026-08-27.md:89,122-123` | 유일한 판매 기능(구역 침입)이 "빠른 통과"를 놓칠 수 있는데 검증 없음 | 통과 시나리오(1~3m/s) 실카메라 실측 → enter_s 를 시간·속도 기준으로 재정의, 또는 tid 무관 위치 기반 키(grid_cells) 상시 병행 | M |
| 3 | **P0** | 근접(협착) 거리 무캘리브레이션 + 깊이 없는 운전자 제외 → 지면 보행자 **7.6%(26/344, v1.2 개정)**·최장 2.1초 연속이 경보 대상에서 제외 | `proximity.py:103-112` · `reports/…v1.2.md:31,143,152` · `field_academy_2026-08-27.md:118-121` · grep(호모그래피 0건) | 지게차 옆 보행자가 "탑승자"로 분류돼 협착 경보 누락 — 사망 직결 시나리오 | 발끝 높이 비교(리포트 16/16 육안) 추가 → 단기; 바닥 호모그래피(4점 마킹) 도입 → 중기; 거리 오차 실측 리포트 | M / L |
| 4 | P1 | 야간·저조도 유인 재현율 0회 측정, 무인 오탐 86.4% | `m2_night_person.md:15,67-69,139` · `v1_field_baseline_report.md:130` | 야간 교대·옥외 현장에서 성능 미지 — 미탐·오탐 모두 가능 | 절차서(§4)대로 유인 3조건 실측, 조도계 구비, 야간 데이터 라벨링 | S |
| 5 | P1 | forklift 전역 모델 불용(mAP 8.83%·conf 0.002) → 학원은 AGPL YOLO boda_ax(LOCO 21.4%)에 의존 | `vision.yaml:18` · `tuning.yaml:110-111` · `forklift_duel_2026-08-19.md:13,26` · `profile_intent.yaml:36-55` | 현장 종류가 바뀌면 지게차 검출 붕괴; 라이선스(AGPL) 리스크 병존 | RF-DETR forklift 재학습(현장 데이터 + LOCO 혼합), 도메인별 재현율 게이트 | L |
| 6 | P1 | 기준선-운영 불일치 재발 방지 장치 없음 + ppe 체크포인트 출처 불확실 | `CLAUDE.md` 규칙 9 · `vision.yaml:21-26` · `MANIFEST.md:19` | 대외 수치 신뢰 붕괴 재발; 배포 모델의 mAP 근거가 재현 불가 | 구성 해시(vision+tuning+manifest sha) → 기준선 리포트에 스탬프, 불일치 시 CI 실패; best_total 로컬 재평가 1회 | S |
| 7 | P1 | 현장 노트북 4대 — 램프 실측상 **권장 상한(4)에 딱 걸리고 N=4에서 p95 3배 급증(675ms)**, 4h 소크·스로틀링·경보 지연은 미측정 | `docs/academy_visit_day.md:718-741` · `audit/measure_watch_20260821_224702.md:7` · `LAPTOP_SIZING_PILOT4.md:114-123` | 납품 후 발열 시 검출주기 초과·경보 지연 | 노트북에서 `LAPTOP_SIZING_PILOT4.md §2` 4h 소크 1회 실행 전엔 "4대 상시" 계약 금지; 실패 시 3대 또는 1.5fps | S |
| 8 | P1 | 오늘 드라이런 GPU util 83~89%·VRAM 4.0GB — 2026-08-18 기준선(31~37%·1.4GB)과 모순, 원인 미확정 | `audit/loadtest_20260908_2122_devpc_dryrun.md:24-29` · `capacity_report.md:68-70` · `v1_slot_config_report.md:18` | 사실이면 4GB GPU 구매 전제 붕괴 | nvidia-smi 프로세스별 VRAM 로그를 키트에 추가해 재실행(다른 프로세스 배제) | S |
| 9 | P2 | 전 카메라 단일 `DETECT_LOCK` 직렬화 + 배치 없음 + fp32 | `worker.py:1007` · `guard.py:970-976` · `rfdetr_adapter.py:151` | 대수 선형 증가·8대 붕괴; GPU 유휴 | TensorRT/fp16 + 슬롯 3개를 카메라 프레임 배치로 — 단 정확도 Δ 회귀 게이트 필수 | L |
| 10 | P2 | drift 감시·재학습 루프 부재 — 피드백 엔드포인트가 빈 스텁, VLM 오탐 판정 미저장, 학습이 운영 데이터를 읽는 코드 0건, 재학습 코드는 사장된 office/YOLO 용 | `routers/recognition.py:58-60` · `vlm_confirm.py:46-47,95` · §9 | 현장 적응 불가, 시간 경과 성능 저하 미감지 | 오탐/미탐 1-클릭 피드백(스텁 구현) → 라벨 큐 → RF-DETR 재학습(`rfdetr_train.py` 확장, 시드 고정) → 골든 회귀 · 클래스별 검출률/conf 분포 시계열 `/metrics` | L |
| 10b | P2 | ONNX-CPU 최적화가 재현 불가 — `.onnx` 4종 매니페스트 미등재, 부재 시 무경고 torch 폴백 | `weights_manifest.json` 14항목 · `rfdetr_adapter.py:199,206-208` | 저가 CPU 박스 배포 근거(V2)가 클린 설치에서 성립 안 함 | `.onnx` 3종(ppe/fire/forklift) 매니페스트 등재 + 폴백 시 WARNING + `/health` 에 backend 실제값 노출 | S |
| 11 | P2 | Jetson/ARM 이식 리스크(cu130 x86 고정·CPU EP 고정·win64 바이너리) | `requirements.txt:29-41` · `rfdetr_adapter.py:119` · manifest 항목 13 | Jetson 제안 시 성능·일정 미지 | Jetson 후보 1대 확보 후 3슬롯 1대 벤치(TensorRT 변환 포함) | M |
| 12 | P2 | 평가 데이터 규모·품질: 109장·1인 검수·조끼 양성 2건·혼동행렬 없음·클래스별 현장 mAP 없음 | `v1_field_baseline_report.md:126-136` · grep | 수치의 CI 폭 ±7%p, 클래스별 약점 미상 | 라벨링 계획(층화 표본) 실행 + 교차검수 + 혼동행렬 자동 산출 | M |
| 13 | P2 | 롤백 절차 수동·순서 의존(틀리면 person 슬롯 None) | `vision.yaml:41-46` · `guard.py:882-885` | 긴급 롤백 중 검출 사망 | `scripts/rollback_slot.py`(yaml 두 곳 동시 편집 + 기동 전 슬롯 로드 검증) | S |
| 14 | P3 | `vision.yaml` 주석이 실제와 반대(ByteTrack "미구현", 포즈 "yolov8n-pose") | `vision.yaml:65-74` vs `tuning.yaml:193`·`worker.py:361-383` | 신규 인력 오해·감사 신뢰 | 주석 정정 + `check_profile_drift` 류 테스트로 tracker 키 실제값 대조 | S |
| 15 | P3 | VLM 설정이 MLX(Apple)·`/tmp` — Windows 데스크톱에서 동작 여부 불명 | `vision.yaml:99` · `rfdetr_service.py:224,242` | VLM 확정 체인 무동작 시 규칙만으로 폴백(저하 없음 원칙상 치명 아님) | 확인 질문 Q4 | S |
| 16 | P3 | 매니페스트·인벤토리 문서 부패: `verified_note` "10종"(실제 14), `models_inventory.md` 에 RF-DETR 0줄, `Dockerfile:38` 이 없는 경로 COPY | `weights_manifest.json:189` · `config/models_inventory.md` · `Dockerfile:38` | 신규 인력·컨테이너 빌드 혼란 | 인벤토리 단일화(json 을 정본, md 는 생성) + Dockerfile 경로 수정 | S |

---

## 11. 경쟁 상용 제품 대비 격차(정성 — 저장소 밖 수치는 인용하지 않음)

| 축 | 상용 산업안전 영상분석 제품에서 일반적으로 기대되는 것(일반 지식, 미검증) | VIGENT 현재(근거) | 격차 |
|---|---|---|---|
| 채널 밀도 | GPU 1장당 수십 채널(TensorRT·DeepStream 배치) | 데스크톱 GPU 로 한계 7대, 병목 CPU(§6) | 큼 |
| 거리·속도 | 카메라 캘리브레이션(BEV) 기반 m 단위 | 박스 폭 기준자(§5) | 큼 |
| 야간·IR | 야간 평가셋·IR 모드 | 유인 재현율 미측정(§3) | 큼 |
| 재현율 SLA | 클래스별 목표·현장 검수 리포트 | 목표치 없음, dev 38.2%(§2) | 큼 |
| 모델 운영 | 레지스트리·OTA·카나리 | 매니페스트 sha + 수동 yaml 롤백(§8) | 중 |
| 현장 적응 | 오탐 피드백→재학습 루프 | 끊김(§9) | 큼 |
| 강점 | — | 실측 문서화의 정직성(규칙 7·9·11), 슬롯 DEGRADED 노출, 저하 없음 원칙, Apache 모델 스택 | — |

---

## 12. 확인 질문(판단 유보)

1. **Q1 — 오늘 드라이런 GPU 83~89%/VRAM 4.0GB 의 주체는?** 같은 시간대에 다른 에이전트가 GPU 벤치를 돌렸는가, 아니면 서버 프로세스 자체인가(프로세스별 VRAM 로그 필요).
2. **Q2 — person 재현율 목표치**: 안전 제품으로서 "원거리 포함 미탐 허용 한계"를 어느 값으로 선언할 것인가(현재 없음).
3. **Q3 — 학원 프로파일에서 AGPL YOLO(boda_ax) 사용**이 배포·라이선스 방침(copyleft 0)과 어떻게 정합되는가(`yolo_adapter.py:8-10` 는 "배포 requirements 미포함"이라 적었는데 학원은 backend=yolo).
4. **Q4 — Windows 데스크톱에서 VLM(MLX 설정) 경로가 실제로 동작하는가**, 아니면 항상 폴백(None)인가(`docs/NEXT_SESSIONS.md` 의 "Windows 로컬 VLM 대체" 건과 연계).
5. **Q5 — 현장 노트북 4h 소크 실측 일정**: 4대 계약 전 실행 가능한가.
6. **Q6 — 현장 생존율 88.3%(GT 없음)와 dev 원거리 재현율 0~8%(GT 있음, 1fps) 중 어느 쪽을 대외 수치로 쓸 것인가** — 둘 다 아니라면 2fps 정답지 측정 일정은.
7. **Q7 — `.onnx` 3종을 매니페스트에 등재할 것인가, 아니면 ONNX-CPU 경로를 공식 지원 범위에서 뺄 것인가**(V2 결론 "현재 설정 그대로는 손해"와 정합 필요).

---

`D:\vigent_original\docs\review\02-model-inference.md` — **P0 3건 · P1 5건**(P2 6건 · P3 3건).
