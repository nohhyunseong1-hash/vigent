# VIGENT 벤치마크·이관 FINDINGS (리스크·후속 태스크)

> 측정·이관 과정에서 드러난 리스크와 후속 검증 항목. 규칙7: 측정/관찰된 사실만.

## T10c — 포즈 RTMPose 이관 관련

### F-1. top-down 포즈는 부분/중복 인물 박스에 취약 (다인 현장 리스크)
- 관찰: `ergo_06`(카페 다인 프레임, 배제분 `data/pose_frames_ergo_excluded/multi_00_intrusion_174827.jpg`)에서
  **raw RF-DETR 박스**(NMS/track 미적용)를 RTMPose에 주면 좌↔우로 뻗친 왜곡 스켈레톤 → trunk 각도 76° 발산 → ergo 등급 오판.
  증거 오버레이: `benchmarks/results/pose_overlays_s2/cmp_ergo_06_intrusion_174827.jpg`.
- 완화(검증됨): 박스 소스를 **guard.detect(person)**(`_nms`+`_suppress_vehicle_dupes`+`_track` 적용)로 하면 위 발산이 사라짐(hard 1→0).
  production worker 도 guard.detect person 박스를 재사용하도록 배선함(동일 방어).
- ⚠️ **잔존 리스크**: worker/guard 에 **최소 박스 면적·종횡비·conf 품질 게이트는 없음**(현재 없음을 확인).
  다인·부분가림 현장에서 부분 인물 박스가 나오면 top-down 포즈가 왜곡될 수 있음.
  → **T14(운용점 튜닝)에서 포즈 입력 박스 품질 게이트(min area/aspect/conf) 도입 여부 검토** 권고.

### F-2. ergo 등급의 임계 경계 민감성
- 관찰: 두 포즈 백엔드가 대체로 일치(mean OKS 0.78~0.85)해도, 관절 각도가 good/warn/bad **임계 경계**에 걸린 프레임은
  작은 키포인트 차이로 1단계 등급이 뒤집힘(soft flip). 정밀 ergo셋에서 실질차이(>7°) 3~4건 관찰(2단계 점프=hard 는 0).
- 함의: ergo 등급 자체가 임계 분류라 **어떤 포즈 모델 교체든 경계값에서 민감**. 판정 로직 문제 아님.
- → **사용자 촬영 낙상/부담자세 클립 도착 후 판정층(b) 검증 시, 경계 케이스(각도가 임계 부근인 자세)를 의도적으로 포함**할 것 권고.

### F-3. yolov8n-pose vs RTMPose+YOLOX 검출집합 차이
- 관찰: 초기 하네스(중심점 매칭)에서 두 백엔드가 **서로 다른 인물집합**(전경/배경)을 검출 → 다인 프레임서 매칭 아티팩트(허위 불일치).
  IoU 매칭 + 검출집합 차이 별도 카운트로 분리(기존셋 rtmpose만 35·yolo만 13).
- 소멸 확인: **Stage 2에서 포즈 입력 박스를 RF-DETR(guard) 로 통일하면 이 변수는 소멸**(포즈 검출기 자체를 안 씀 = top-down).

### F-4. 낙상/부담자세 클립 회귀셋 — 사용자 촬영 대기
- 현재 회귀는 **정지 프레임**(evidence JPG + runs 영상 프레임) 기반 = 판정 '입력층' 패리티(pose_fallen·ergo 등급).
- **낙상/부담자세 동영상 클립 회귀셋은 부재** → 판정 '출력층'(이벤트 발생 여부, 시간 지속) 검증 불가.
- → 사용자 촬영 클립(낙상/부담자세/정상 각 3~5) 도착 시 **판정층(b) 검증 태스크 추가**. 경계 케이스(F-2) 포함 권고.

### ✅ F-6. 배포 화재/연기 경보 recall 매우 낮음 — T10b RF-DETR 재학습으로 해소 (D-Fire 기준, 현장 재검증 대기)
- **✅ 해소(2026-07-07, T10b)**: fire_smoke 를 boda(YOLO) → **RF-DETR(D-Fire 학습, Colab e17 best_ema)** 이관.
  배포 presence recall **fire 53.64→95.91 / smoke 24.85→87.88**(pipeline fire0.30/smoke0.50), FAR fire 1.1%·smoke 15.4%.
  box mAP@50 **80.13%**(게이트 B ≥60 통과), 게이트 A(presence)도 통과. **T14-F 임계천장(~recall 54%)을 모델 능력으로 돌파**
  (임계 튜닝이 아니라 재학습으로 해결). 회귀 person/ppe/forklift Δ0.00. ⚠️ **in-domain(D-Fire) 기준 — 현장 재검증 대기**(T10c-V). 상세 `EVAL.md`.
  아래는 해소 이전(T14-F 완화) 기록 — 근거·경위 보존용.
- **정정**: 최초 F-6은 배포 임계를 "0.70"으로 기술했으나, 실제는 tuning.yaml **fire_smoke=0.55**였음(실측 재확인).
  단일 0.55 운용점(완화 전): **fire presence recall 10.45%·smoke 7.58%**(precision fire 95.8·smoke 92.6)
  → 화재/연기 프레임의 **약 90%를 놓침**. raw presence AP 는 fire 83.1·smoke 89.9(모델 순위능력은 높음 = 임계 문제).
- **완화 조치(T14-F, 2026-07-04)**: guard 에 fire_smoke **클래스별 후필터 임계** 추가(ppe 패턴 준용, 판정·모델 무수정).
  tuning.yaml `fire_smoke_per_class: {fire: 0.03, smoke: 0.20}`. pipeline 재측정 결과:

  | 클래스 | recall(전→후) | precision(후) | presence AP(후) |
  |---|---|---|---|
  | fire | 10.45% → **53.64%** | 89.39% | 80.67% |
  | smoke | 7.58% → **24.85%** | 93.18% | 81.78% |

  회귀: person(rfdetr) 92.94·ppe 58.62 pipeline **Δ0.00**(타 경로 무영향 증명).
- ⚠️ **임계 튜닝의 천장 확인**(conf 스윕 실측): 사용가능 FAR 내 **최대 recall ≈ fire 54%(FAR 8.6%)·smoke 55%(FAR 27.7%)**.
  recall 0.80은 conf≈0.001에서만 나오나 그때 FAR fire 78%·smoke 95%(전 프레임 오경보 = 사용 불가).
  → **본 완화는 D-Fire 기준 잠정 조치. 근본 해결은 T10b 재학습.** 현장 CCTV 확보 시 정식 재튜닝(T14).
- **smoke 오검출 특성**: negative 프레임 오검출이 fire보다 급증(0.03시 FAR smoke 27.7% vs fire 8.6%) —
  구름·연무·조명 등 연기 유사 배경 혼동. → **T10b 학습셋에 hard negative(연기 유사 비연기) 포함 권고**.
- 단서: D-Fire 도메인(원거리·야간 산업/옥외 화재 포함)이 현장과 다를 수 있음 → 현장 프레임 재측정 병행 권고.
- **⚠️ 운영 리스크(배포 절차)**: 설정(tuning.yaml) 변경은 **재시작 없이는 라이브에 미반영** — `tuning.py`의 `_CACHE`가
  프로세스당 1회만 로드되고 uvicorn 에 `--reload` 없음. 실제로 T14-F 임계가 서버 미재시작으로 ~9시간 라이브 미적용됨.
  → **배포 절차에 "설정 변경 후 서비스 재시작" 명문화 필요.** 백로그: 설정 핫리로드(파일 mtime 감지 재로드) 또는
  기동 시 임계 로그 출력(FIRE_SMOKE_PER_CLASS 등) 개선. (본 항목은 등재만 — 코드 수정 별도 태스크)
- **소형 화염 검출 한계(실측)**: raw(conf 0.001) 화염 박스 크기별 검출률 — 초소형(<1% 프레임, 라이터급) conf≥0.03에서
  25.3%만(≈39%는 conf 0.001 미만=사실상 미검출), 소형(1~4%) 65.2%, 중대형(≥4%) 67.8%. 재시작+0.03으로 소형·중대형은
  크게 개선되나 **라이터급 초소형 불꽃은 모델 한계로 미검출 다수** → T10b 재학습에서 근접·소형 화염 데이터 보강 권고.

### ★ T10b 우선순위 격상 (T14-F 결과)
- fire_smoke 는 **임계 튜닝으로 회복 불가한 능력 한계**가 실측 확인됨(사용가능 FAR 내 recall 천장 ~54%).
  → **T10b에서 fire_smoke 를 1순위 클래스로** 재학습. hard negative(연기 유사) 필수 포함.
- 게이트 A(저하 없음) 기준선 갱신: 완화 후 pipeline presence recall **fire 53.64·smoke 24.85**(P fire 89.4·smoke 93.2).
  RF-DETR 재학습본은 이 recall 이상 + 동일 recall 운용점에서 precision 비교.

### ★ T10b 게이트 재정의 (T13 결과 반영)
- **기존 게이트 폐기**: "RF-DETR raw mAP@50 ≥ YOLO baseline(4.31%) − 2%p" — **무의미**(주석 스키마 불일치로
  YOLO 4.31%가 능력 아님. D-Fire 학습 RF-DETR은 자명하게 초과). 폐기 사유 기록.
- **게이트 A — 저하 없음(배포 용도)**: RF-DETR **presence recall ≥ 현행 YOLO 기준선**(T14-F 후 값, 동일 운용점).
  기준선(확정): **fire recall ≥ 53.6% (P 89.4) / smoke recall ≥ 24.9% (P 93.2)**. precision 은 동일 recall 운용점에서 동반 기록.
  참고 raw presence AP: fire 83.1·smoke 89.9.
- **게이트 B — 신모델 품질(box)**: RF-DETR **D-Fire test mAP@50 ≥ 0.60 (승인 확정, 2026-07-05)**.
  근거: D-Fire에서 **YOLOv8n mAP@50 ≈ 0.625**(개선 0.651) — [MDPI Sensors 24(17):5597]. Nano 급이 문헌 YOLOv8n 수준.
  - **폴백(임계 인하 금지)**: T10b 가 0.60 미달 시 **운용 임계를 낮춰 통과시키지 않는다**(게이트 회피 금지).
    대신 **(a) 모델 크기 상향(RF-DETR Nano→Small) 재학습** 또는 **(b) 학습 데이터 보강(hard negative: 연기 유사 비연기 포함)**
    중 택일을 **보고 후 사용자 결정**. 소형·근접 화염 데이터 보강 병행(F-6).
- **격리 규칙(T10b 학습)**: 학습은 D-Fire **train split만** 사용. 평가셋(test 서브셋 395장)과 이미지 격리 —
  같은 이미지 유입 시 평가 오염. forklift(LOCO)도 결정적 분할의 **train(211장)만** 학습, 매니페스트 `t10b_no_inject`(test+네거) 유입 금지.

### T10b forklift 게이트 (T13b 결과)
- **게이트(저하 없음)**: RF-DETR forklift **raw mAP@50 ≥ YOLO baseline(7.61%) − 2%p = 5.61%** + **presence recall ≥ 배포 기준선**.
  현행 기준선(LOCO test 238img/네거80): box mAP raw 7.61·pipeline 3.15 / presence 배포 recall 35.71·FAR 28.7·AP 76.6.
- ⚠️ **게이트 약함 주의**(fire_smoke 게이트 B와 동일 구조): baseline 7.61%는 **도메인갭**(boda 모델이 LOCO 미학습)으로 낮아,
  LOCO train 학습한 RF-DETR 은 자명하게 초과 가능. 따라서 "−2%p"는 하한선일 뿐 — **실질 목표는 presence recall↑ + FAR↓**(pallet_truck 오탐 감소)로 판정 권장. 필요 시 LOCO forklift 문헌치 조사해 절대 목표 추가.

### ★★ T10b Phase 1 ppe 학습 — MPS 특이 NaN 발산(원인 확정) 2026-07-05
- **증상**: RFDETRNano, css_safety 2603장·10클래스, MPS 50ep → **train/loss 전 에폭(0~22) nan · val mAP 8e-06 고정(학습 전무)**. ~4h 낭비 후 중단.
- **진단(1-epoch 200장 스모크 격리, 변수 하나씩)**:
  | # | 조건 | 결과 | 판정 |
  |---|---|---|---|
  | ① | MPS + amp=off | nan | AMP 무관 |
  | ② | MPS + lr 1e-5(1/10) | nan | lr 무관 |
  | ③ | 데이터 무결성(COCO) | cat_id 1~10·degenerate 0·oob 0 | 라벨 정상 |
  | ③'| 이미지 무결성 | 전부 RGB 640×640·손상 0 | 이미지 정상 |
  | ④ | **CPU + 기본설정** | **loss 7.05 유한** | ★ **MPS 특이 문제 확정** |
- **원인**: MPS(Apple Silicon) 수치 불안정 — 동일 config/데이터가 CPU에선 정상학습, MPS에선 **forward loss부터 nan**.
  forklift(1클래스·1.4box/img·동일 MPS·동일 기본설정)는 성공했으나, ppe(10클래스·14.4box/img)의 **무거운 다중클래스 손실계산**에서 MPS 연산이 nan 산출. amp/lr 무관 = precision·스텝 문제 아닌 연산 정확성 버그.
- **영향(전략적)**: fire_smoke(D-Fire 대형·다중클래스)도 **동일 MPS NaN에 걸릴 것** → "LOCAL M5 MPS ONLY" 경로가 다중클래스 RF-DETR 학습 전반에 막힘. 단일클래스(forklift)만 MPS 가능.
- **해결 후보**: (a) CPU 학습 = 안정하나 ~수일(2603×50ep, 비현실적) (b) MPS nan 연산 지목→CPU 폴백(불확실) (c) ppe YOLO 유지·이관 보류(forklift만) (d) CUDA(클라우드/학교, 기존 제외) 재고 — CUDA엔 이 버그 없음. **사용자 결정 대기.**
- 도구: `training/rfdetr_smoke.py`(amp/lr/device 스모크 + NaN 판정), `training/scan_ppe_labels.py`(심층 무결성), `training/build_ppe_subset.py`.

### ★★★ MPS RF-DETR 학습 전면 불가 확정 — 모든 학습 CUDA(클라우드) 필수 (2026-07-10, PoC)
> **향후 모든 학습 태스크의 전제.** '맥북(M5 MPS) 온리' 원칙은 **추론·개발·검증에만 적용, 학습은 예외**.
- **두 가지 발현, 같은 뿌리(MPS 수치 불안정)**:
  | 케이스 | device=mps 증상 | 위치 |
  |---|---|---|
  | ppe(10클래스, §위) | forward **loss NaN** | 학습 스텝 |
  | **forklift 2클래스(PoC)** | **matcher cost matrix 메모리 오염** → `torch.AcceleratorError: index <garbage> out of bounds` | epoch 경계 val matcher(`matcher.py:259`) |
- 표면 에러는 `TypeError: iou() incompatible`였으나 최종 프레임은 AcceleratorError = **NaN이 아니라 MPS 텐서 메모리 오염**. 선행 경고 `Non-finite values in matcher cost matrix`가 동일 뿌리.
- **num_workers·resume은 크래시 시점만 바꿈(원인 아님)**, `PYTORCH_ENABLE_MPS_FALLBACK=1`로도 회피 불가(pybind C++ 연산). 단일클래스 forklift가 MPS로 우연히 됐던 것도 첫 epoch만 통과였을 뿐(2클래스는 val matcher에서 확정 크래시).
- **결론**: 다중클래스 RF-DETR 학습은 MPS 전면 불가. **모든 재학습은 CUDA(클라우드)에서**. CPU는 버그 없으나 3k·5ep에 16.6h(절전 포함) → full 9k 비현실.
- 근거: `data/datasets/forklift_merge/POC_REPORT.md` §3, commit 89b0320. `training/rfdetr_train.py`에 `--device`(mps/cpu) 인자 추가됨.

### ★ T10b Phase 1 forklift 결과 — 이관 완료(box 개선 인정, 사용자 결정 c) 2026-07-05
- 학습: RFDETRNano, LOCO train 192장, 50ep, MPS 45분. 산출 `weights/forklift_rfdetr_v1.pth`(class_names=['forklift']).
- **게이트 판정(부분 통과)**:
  | 지표 | YOLO baseline | RF-DETR | 판정 |
  |---|---|---|---|
  | box mAP@50 raw | 7.61% | **8.83%** | ✅ ≥5.61 통과·baseline 초과 |
  | box mAP@50:95 raw | 3.03% | **5.98%** | ✅ ~2× |
  | **box mAP@50 pipeline** | 3.15% | **8.5%** | ✅ **+5.35%p 대폭 개선** |
  | presence AP | 76.87% | 76.32% | ≈동등 |
  | presence recall/FAR(pipeline) | R35.7/FAR28.7 | R34.87/**FAR35** | ⚠️ recall 동등·**FAR 다소↑**(미개선) |
- **한계(F-7 유지)**: 예측 confidence 극저(0.001~0.005) = **train 192장 과소학습/과적합**(내부 valid best가 epoch0에서 정체).
  운용점 tuning.yaml `forklift: 0.002`(잠정, YOLO 0.68에서 변경). recall<60%라 **"추가 개선 필요" 유지 + 데이터 보강 백로그**.
- 회귀: person(rfdetr) 92.94·ppe 58.62·fire_smoke presence(fire 53.64/smoke 24.85) 전부 **Δ0.00**(이관이 타 경로 무영향).
- copyleft: forklift 런타임이 rfdetr(Apache)로 전환 → **ultralytics(AGPL) 잔존은 ppe·fire_smoke 2개 슬롯만**(T10b 나머지).

### F-7. forklift 배포 저recall·고오탐 → PoC로 개선 실증, full은 현장 데이터 대기 (2026-07-10)
- 실측(LOCO 318장): 배포 운용점(conf 0.68) **forklift recall 35.71%(64% 놓침) + FAR 28.7%**(네거 80장 중 23장 오탐).
- FAR 의 실체 = **pallet_truck 혼동**(hard negative 40장 중 다수 오탐). 도메인갭+저신뢰로 recall·precision 양쪽 약함.
- → T10b 재학습에서 **pallet_truck 을 hard negative 로 포함** 필수(연기 유사 비연기 = fire_smoke 와 동일 원리). presence recall 1순위.
- **✅ 개선 실증(PoC 2026-07-10)**: 공개 데이터 확대(598→4,799 inst) + pallet_truck 분리(옵션B 2클래스) 병합 데이터로 재학습.
  동일 하네스·고정 test(LOCO 238+네거80) 직접 비교: **box mAP@50 8.83→58.62%(6.6배)**, **recall 35.71→54.62%(천장 46.6 돌파)**, precision 94.9%.
  FAR은 baseline 0%(사실상 미검출이라 무의미) 대비 **실검출하 8.8%**. → **개선 방향 확정.** 상세 `POC_REPORT.md`. (단 3k·5ep PoC, test는 LOCO in-domain)
- **⏸ full 학습 보류(사유)**: forklift full(9k in-domain)을 **지금 하지 않음** — PPE도 F-9로 현장 재학습 필요 →
  forklift·ppe **둘 다 현장 데이터 파인튜닝이 최종 형태**. in-domain full을 먼저 하면 현장 확보 후 재학습과 **중복**.
  → **현장 데이터 확보 시점에 forklift+ppe 일괄 재학습을 설계**하는 게 효율적(학습은 CUDA/클라우드, ★★★ 참조).
  - ⚠️ **예외 판단**: 파일럿 현장이 '지게차 있는 물류창고'면 LOCO in-domain이 현장과 가까워 full 학습이 바로 값할 수 있음
    → **현장 업종 확정 후 재판단**(현장이 LOCO 유사 도메인이면 in-domain full 즉시 진행 가치).
- **★ 잠정 비활성 처리(2026-07-11, 웹캠 벤치 실측 확정)**: forklift 정탐/오탐 conf가 **완전 겹침** —
  정탐 p50 0.002·max 0.005 = 오탐과 동일(LOCO test 238 + 웹캠 실측). **임계 분리 불가 확정**(0.002=정탐34.9%+오탐폭탄 / 0.01↑=정탐0).
  → **detect_frame 기본 detectors에서 제외**(main.py) + `/health.disabled_detectors` + tuning 주석 3중 명시. **임계 0.30 은폐형 off는 기각**(명시적 비활성).
  측정/게이트 경로는 `payload.detectors` 명시 지정 시 추론 가능. **복원 조건 = T10b full 재학습 게이트 통과**(정탐 conf 정상화 확인).
- **★ 재해분석(incident) 경로도 제외(2026-07-13, 크레인 재해.MP4 18.4s 실측)**: incident/frame·analyze 기본 detectors에서 forklift 제거.
  실측 오탐 확인 = 강재더미를 forklift conf **0.002** 로 오탐(machinery 는 별개로 ppe 모델이 0.755 정탐, 오인 아님). 유령 지게차가
  `hazard=True`(⚠ 지게차) + 협착(proximity) 점수·타임라인 피크를 오염시킴 → 제외. `payload.detectors` override 유지(측정 가능).
  - ⚠️ **알려진 공백(숨기지 않음)**: **incident 경로는 현재 지게차 재해를 탐지·분석할 수 없음 — 지게차 관련 재해 영상 분석 시
    협착·충돌 요인이 누락됨.** 파일럿에서 이 한계를 사전 고지. T10b 현장 재학습 후 복원 시 해소.
  - **음성안내(voice/scene)도 제외(2026-07-13)**: 유령 지게차 **음성경보 = 없는 위험을 소리로** 알림 → 반복 시 **경보 피로**로
    진짜 경보까지 무시하게 됨(화면 오탐보다 나쁜 실패). 별도 커밋. `payload.detectors` override 유지(측정 가능).

### 백로그 — pallet_truck 별도 검출 클래스 후보
- LOCO 에 pallet_truck(2,827inst/1,502img) 어노테이션 존재. 동력 지게차와 **협착 위험군이 상이**(수동·소형)해 forklift 로 병합 안 함.
- 향후 **별도 검출 클래스**로 추가 시 협착 위험 판정 세분화 가능(현행 `vehicle_ref_m`에 pallet_truck 폭 기준자 추가 필요). 지금은 백로그.

### F-10. 라이브 박스 랙 — 검출 fps 한계 + 표시 보간 + 경합 해소 (2026-07-12)
- **측정(서버 8011, pos_bare)**: 서버 추론 person 28.9 / +ppe 56.8 / +fire_smoke **83.1ms**, 왕복 p50 **~110ms**(HTTP+인코딩 ~27ms).
- **중첩/큐 밀림 = 이미 방지됨**: `backendBoostBusy` in-flight 1건(realtime_core). 랙 주범 아님(수정 불필요).
- **지연 3원 분해 + 처방(전 → 후)**:

  | 지연원 | 전 | 후 | 처방 |
  |---|---|---|---|
  | 검출 게이트(최소간격) | 150ms | **100ms** | `DETECT_MIN_INTERVAL_MS` 외부화(CPU 15→27% 여유 실측) |
  | 보간 수렴 — person | 178ms(lerp0.35 90%) | **~0** | person lerp 제외 → pose 재배치(691ec3e) 즉시성 우선(경합 해소) |
  | 보간 수렴 — NO-* 등 | 178ms | **110ms** | lerp 0.35→0.5 + 큰이동(IoU<0.5) 스냅 |
  | **person 총 체감** | **~328ms** | **~100ms** | |

- **검출 실효 fps: ~6.7 → ~9**(게이트 100ms, 추론 83ms라 이론 상한 ~10fps).
- **회귀**: 벤치 person12.5/smoke7.5/forklift0/recall100 **Δ0**(프론트 변경, 서버 무영향) · coord-mismatch **0 유지**(방어).
- 진단 도구: `?diag=1`(원시 vs 보간 동시표시 + raw ms), `_coordMismatchTelemetry`/`_coordEvent`(race telemetry).
- ⚠️ **표시 개선 ≠ 성능 개선(오기 금지)**: 보간·스냅·100ms는 '표시'를 부드럽게/덜 늦게 할 뿐. **안전 판정 주기 = 검출 ~9fps** 기준이며 보간 위치는 마지막 검출의 근사(추정). 표시 부드러움을 검출 성능으로 오기하면 안전 오판. 추론 경량화(검출 fps↑)는 엣지 포팅 트랙 몫.

### F-5. 포즈 latency (macOS CPU, onnxruntime 기준)
- RTMPose pose-only 한계비용 **40.2ms/frame**(박스는 guard.detect 재사용=무료) vs 구 yolov8n-pose 23.8ms(+16ms).
- 워커 기본 2fps(500ms 간격)에선 무시 가능. 단 **RK3588 등 엣지 재측정 필요**(별도 태스크, RKNN 변환은 미시도).
- rtmlib 내장 YOLOX 검출(Stage1)은 226ms로 느림 → **기본 off**, RF-DETR 박스 재사용이 정답.

### 백로그 — yolo_adapter.py 제거 (A-4 후속, 2026-07-07)
- **현황**: A-4 로 배포 경로 ultralytics 0(전 슬롯 RF-DETR). `detectors/yolo_adapter.py` 는 **롤백 안전망으로만 존치**
  (지연 import, 배포 requirements 에 ultralytics 미포함 → copyleft 0 유지). 사용자 결정(2026-07-07): 존치 + 주석 강화.
- **제거 조건(충족 시 삭제 검토)**: ① **현장 검증(T10c-V) 완료** — 이관된 RF-DETR 4종(person/ppe/fire_smoke/forklift)이
  현장 영상에서 in-domain 성능을 유지함을 확인(각 모델의 in-domain 한계가 해소). ② 롤백 필요성 소멸 판단.
  → 두 조건 충족 시 `yolo_adapter.py` + `detectors/__init__.py` YoloDetector + guard 의 yolo 분기 제거, ml/train_*.py(YOLO 학습 스크립트) 정리.
- 제거 전까지: backend=yolo 는 측정/롤백 전용(requirements-eval.txt 설치 필요), 배포물 미포함.

### 백로그 — 병렬 세션 감사 작업 2건 (미완결, 별도 완결·검증 필요, 2026-07-07)
`audit/a4-adversarial` 브랜치에 병렬 세션이 만든 감사 작업 2건이 있음. **main 미포함**(미검증). 각자 완결·검증 후 별도 머지.
- **(a) 적대적 감사** (`eval/adversarial/`, commit 786cd33·efb6ae7): SCOPE.md(공격면·위협모델) + 케이스 19건(t_inj/t_hall/t_down/t_2tier) + 하니스(run_adv.py·detectors.py) **구축됨**. 단 **실행·판정(verdict) 미완** → A-4 후속 보안 검증으로 완결 필요(하니스 실행 → 통과/취약 판정 → 기록).
- **(b) 골든셋** (`eval/golden/scribe/`, commit d4bf072·dc51541·badcfd6·df0a412·a88bbbe): 스키마·채점엔진(gates/judge/rubric/run, fixtures 검증 통과)·아이템 스캐폴드 30건 **완료**. 단 **정답(ground-truth) 30건 미작성** → 작성 주체 **사용자(안전관리자 자격)**. 정답 도착 시 Scribe 평가 가동.
- ※ 지금 이 2건을 진행하지 않음(등재만). T10b/A-4 와 파일 겹침 0(eval/ 국한) — 독립.

### 메모 — audit/a4-adversarial 의 T10b 중복 커밋 (2026-07-07)
main 은 T10b+A-4 10커밋을 **cherry-pick**으로 받음(격리 워크트리, 태그 v1.0-copyleft-zero). 원본 10커밋은 `audit/a4-adversarial`에도 그대로 남아 있어 **커밋이 논리적으로 중복**(해시는 다름). 훗날 audit 브랜치(감사 2건)를 main 에 머지할 때 **그대로 머지하면 중복 diff 충돌 가능** → `git rebase --onto main <T10b마지막> audit/a4-adversarial`(또는 감사 커밋만 cherry-pick)로 **T10b 중복분을 걷어낸 뒤** 머지할 것. 경위: 공유 워킹트리 HEAD 이동으로 T10b 커밋이 audit 위에 얹혔음(CLAUDE.md §8 참조).

### ✅ F-8. rfdetr 커스텀 가중치 경로버그 → 서버 silent COCO 폴백 (실배포 결함, 해소 2026-07-07)
**증상**: `/safety-local` 등 서버 화면에서 안전모·조끼(PPE) 미검출. 창업자 본인 재현.
**근본 원인(3중 결함)**:
1. **경로버그**: `guard._get_model` 이 `perception.rfdetr_weights`(프로젝트루트 기준 **상대경로** `vigent-core/weights/…`)를 절대경로화 없이 `RFDETRNano(pretrain_weights=…)` 에 전달. 서버는 cwd=`vigent-core` 로 기동되므로 `vigent-core/vigent-core/weights/…` 로 **이중경로 깨짐**.
2. **silent 폴백**: RFDETRNano 는 커스텀 가중치를 못 찾으면 **예외 없이 COCO 사전학습으로 폴백** → person 만 검출(COCO 에 Hardhat/Vest 없음). guard 도 미검증.
3. **health 오보고**: `vision_loader` 는 구 `.pt` 경로만 검사하고 `rfdetr_weights` 는 안 봐서 capabilities/health 가 `source=model`(거짓 정상)로 보고 → 은닉.
**소급 영향(정직)**: 서버는 항상 cwd=`vigent-core` 로 기동되므로, **commit f1afc2e~036b42b 기간의 서버 실배포는 커스텀 3종(ppe/fire_smoke/forklift)이 미탑재된 채 COCO 폴백으로 동작**했을 강한 정황(person 만 검출). EVAL 의 pipeline 수치는 **인프로세스(cwd=루트) 측정**이라 유효했으나 **서버 실배포와 괴리**가 있었다. person(COCO) 검출은 정상이었음.
**수정**:
- A. `guard._resolve_rfdetr_weights`: rfdetr_weights 를 `_PROJECT_ROOT` 기준 **절대경로화**(cwd 의존 제거).
- B. **silent 폴백 차단**: 커스텀 경로 지정 + 파일 부재 → `FileNotFoundError`(기동 거부). `VIGENT_ALLOW_FALLBACK=1` opt-in 시에만 COCO 폴백(저하 경고). 경로 미지정(person)=COCO 정상 통과(저하0).
- C. **로드 가시화**: 슬롯별 `slot/backend/weights/SHA/LOADED|MISSING` 로그 + `/health.rfdetr_slots`(실파일 검사·SHA)로 매니페스트 대조 가능.
- 검증: cwd=vigent-core 서버조건에서 PPE 정상 복원(Hardhat/Vest/Mask). 가중치 삭제 시 기동거부 실증.
**측정=배포 보증(핵심)**: 서버 `/detect/frame` 을 **stateless(reset_tracks) 모드**로 4클래스 재측정 → 인프로세스 EVAL 과 **전부 Δ0.00 일치**(person 92.94·ppe 71.46·fire_smoke 69.64·forklift 8.5, imgsz 960). 이로써 **"서버 배포 검출기 = 측정 검출기"가 처음으로 보증**됨. (도구: `benchmarks` 함수 재사용 HTTP 미러.)

### ⚠️ 백로그 — 라이브 추적 계층(_track) 미검증 (F-8 과 같은 급 '측정≠배포' 리스크, 2026-07-07)
F-8 진단 중, 서버 detect_frame 이 **연속 프레임 추적**(`guard._track`: IoU매칭·EMA위치평활·잔상제거)을 유지함을 확인. 이는 **라이브 비디오 안정화 전용 계층**으로, 독립 낱장 벤치마크로는 **검출 능력과 분리 측정 불가**(그래서 측정 시 `reset_tracks` 로 끔). 따라서 **추적 고유의 실패 모드가 미검증**:
- ID 스위치(사람 뒤바뀜), 유령 추적(잔상 박스), 다인 근접 시 트랙 오염(전역 `_tracks` 공유 — guard.py 옵션A 미적용), 프레임 드랍 시 잔상.
- → **연속 프레임 시퀀스 회귀** 필요. **F-1(다인 top-down 박스 품질)·T10c-V(현장 클립)와 묶어** 사용자 촬영 클립 도착 시 함께 검증. 낱장 mAP 로는 안 잡히는 **'측정≠배포' 리스크**로 태깅.

### 메모 — 워크트리 gitignore 자산 누락 반복 사고 (2026-07-07 정리)
하루 동안 **F-8(weights 누락→COCO 폴백)·vendor 404(정적 JS 누락)** 가 전부 **같은 뿌리**였다 — `git worktree add` 는 **추적 파일만** 체크아웃하고 `.gitignore` 자산(`vigent-core/weights/`·`data/`·`benchmarks/data/`·`vigent-core/static/vendor/`)은 빠진다. 파생 여진: 좀비 서버(cwd 소멸), 가중치 COCO 폴백, 정적 JS 404(검출·스켈레톤 미표시).
- **근본 대응**: `scripts/setup_worktree.sh` 가 **weights/data/benchmarks-data/vendor 전부** 심링크·검증 + `main.py` `StaticFiles(follow_symlink=VIGENT_DEV_SYMLINK=="1")` 게이트(배포 기본 차단, 개발 워크트리 opt-in — StaticFiles 는 디렉토리 밖 심링크를 traversal 방지로 거부하므로).
- **운영 지침(§8 보완)**: **단일 세션 개발은 메인 워킹트리에서** 한다(vendor·weights 실재 → 좀비·심링크 여진 없음). 워크트리 격리는 CLAUDE.md §8 대로 **동시 세션이 있을 때만** 필요한 규칙 — 격리 이득이 없는 순수 프론트·단일세션 작업까지 워크트리로 하면 심링크 문제만 유발한다. (2026-07-07 dualfix 검증을 메인 워킹트리로 전환한 근거: 세션 HEAD=main 단일세션 확인됨.)

### F-9. 실내/사무실 환경 오탐 — ★통념 교정(2026-07-11 웹캠 벤치 실측)
당초(2026-07-07) 육안 통념: "모니터·의자를 PPE(Hardhat/Vest/Mask)로 오검출". **웹캠 벤치 실측으로 이 통념을 정량 교정한다.**
- **평가**: webcam_bench 45장(negative 40=빈벽12+물체배경28, pos_bare_near 5), 서버 stateless=배포. `benchmarks/webcam_bench.py`.
- ★ **PPE 착용류 배경 오탐은 미미**: negative에서 Hardhat/Vest 오탐 **0%**, Mask 2.5%(1장). **빈 벽은 전 클래스 0%.** → "사무실 배경을 PPE로 대량 오탐"은 **과장된 통념**. person recall은 100%(정탐 강건).
- **잔존 오탐의 실체(3가지, 분리 확정)**:
  - **(a) forklift 사람 오인**: 사람 몸통을 conf 0.002로 forklift 오탐(pos_bare **100%**, negative 30%). bbox가 person bbox 내부. → **잠정 비활성**(detect_frame 기본 detectors 제외, 2026-07-11). 정탐/오탐 conf 완전 겹침(F-7)이라 임계 분리 불가 → 재학습 대기. [[forklift-poc-and-mps-broken]]
  - **(b) person 오탐 12.5%**: 사무실 물체(의자 등받이·인터폰)를 person으로(conf 0.36~0.69). 빈 벽 0%. 물체 배경 한정.
  - **(c) 박스 좌표 표시(③) — 서버 정상·프론트 race 확정(2026-07-12)**: pos_bare 5장의 서버 반환 bbox를
    640 전송이미지에 직접 그려 검증(`benchmarks/results/webcam_coord/`) → **person·NO-Hardhat(머리)·NO-Mask(얼굴)·
    NO-Vest(몸통) 전부 정확 = 서버 좌표 정상 실증.** 원인은 **프론트 스케일 동기화 race** — 캡처 시점 scX를
    frame에 캐시(realtime_core buildCoreFrameState)한 뒤, 캡처~렌더 사이 창 리사이즈(canvas W 변경)·카메라 전환
    (videoWidth 변경)이 일어나면 캐시 scX가 어긋남. object-fit:contain·mediaRect는 일치(정독 정상), dpr 미적용은
    선명도만. → **계측(mismatch telemetry, 불일치 순간만 로그)+방어(renderCoreFrameOverlays 진입서 현재
    videoWidth/canvas로 scX 재계산, 캐시 금지) 적용.** 재현 로그(`/recognition/log` rule=coord_mismatch) 확보 시
    근본 트리거 추가 기록. 스크린샷 '빈 벽 NO-Hardhat 87%'는 이 좌표 race + 사람 존재로 재해석(순수 빈 벽 실측 NO-* 0%).
- ★ **신구 대결(동일 45장, "이관 후 퇴행" 가설 검증)** — `webcam_rfdetr_A.json`·`webcam_yolo_B.json`:

  | 오탐(negative) | 구 YOLO(0.62/0.68/0.55) | 현행 RF-DETR |
  |---|---|---|
  | smoke | **62.5%** (conf 0.56~0.94) | **7.5%** |
  | person | 0% | 12.5% |
  | forklift | 0% | 30%(→비활성) |
  | PPE worn | 0% | 2.5% |

  → **"이관 후 퇴행" 가설 기각**: smoke는 RF-DETR가 **8배 개선**(구 YOLO가 사무실 배경을 연기로 대량 오경보). person만 RF가 다소↑(도메인). "전에 잘 됐다"의 실체 = 구 YOLO의 forklift/person **침묵**(오탐 0)이지 전면 우월 아님.
  ⚠️ **정직 단서**: 사용자 언급 '구 YOLO negative FAR 25%·vest 92% 오분류'는 **본 실측에서 재현 안 됨**(구 YOLO vest 오탐 0, neg 아무거나 75%는 smoke 주도). 미측정 수치이므로 리포트엔 실측값만 사용.
- **Phase 4(파인튜닝) 범위 축소**: **PPE 파인튜닝 불필요**(배경 오탐 2.5%로 미미). **forklift만** 대상 → T10b full 재학습 계획에 흡수. 오픈데이터 감사도 **forklift hard negative(COCO person)**로 축소(사람 오인이 유일 병목).
- (유지) 근본 해결은 현장 데이터 재학습([[t10-agpl-removal-status]] in-domain 한계). 임계 상향 미봉책은 배제(F-6 교훈).

## F-11 — 법령 화이트리스트 게이트(A-SPRINT Phase 3) 실동작 (2026-07-12)
- **`data/legal/statutes.yaml` 14개 active 생성**(산안법 38·39·80·93, 규칙 20·32·40·42·43·132·146·172·241·656~662). 검수자 노현성(조번호·용도). **원문(text) 정본은 0건** — 이 대화에서 사용자가 원문을 직접 붙여넣은 조문이 없어(웹취득 텍스트를 정본으로 스탬프 금지, §7) 전 조문 `text_status: 사용자 대조 대기`. 게이트는 현재 **번호 기반 통과**, 정본 확보 시 내용 대조로 승격.
- **게이트 2경로**: 결정경로(`safety_citations.json`)=**감사만**(보류 조문 로그, 문서 불변 → §6 저하 없음). VLM 자유생성 `관련법령`=**차단**(화이트리스트 밖/파싱불가 → "안전관리자 확인 필요" 치환+로그).
- **실증(scripts/legal_gate_verify.py, PASS)**: ① 위험성평가서 정상 생성(인용 유지, 저하 0). ② 인용 화이트리스트 내 9·보류 2(제619/620조)·법령아님 1(가이드) 판정. ③ VLM 경로에서 **가짜 제999조·보류 제14조 차단, 진짜 제38조 유지** = t_hall 1차 차단 실증.
- **트리거(scripts/legal_trigger_collect.py)**: 위험성평가서 5건 → 보류 조문 인용 **15건/14종** 집계. 최상위 **제619조(밀폐공간, 2회)**. `data/legal/trigger_report.md`가 검수 대기열(필요 기반 우선순위). 관리체계·TBM·아차사고는 생성기 미구현 → 위험성평가서로만 수집(과대기록 금지).
- ⚠️ **한계**: 고시 tier 미등재(14개에 고시 없음) → "고시 시각 구분"은 미검증. 전면 적대적 감사(19케이스 t_hall/t_down)는 대기. 원문 정본 확보가 내용대조 게이트의 선행조건.

## F-12 — 클라우드 VLM 무동의 활성 = 영상 불유출 원칙의 조용한 붕괴 경로 → opt-in 게이트로 차단 (2026-07-13)
- **문제**: `llm_provider.reason_vision`(재해분석 비전)이 **`OPENAI_API_KEY` 존재만으로 프레임을 외부 전송**했다(별도 opt-in 없음). `incident.analyze`는 로컬보다 **클라우드를 우선** 호출. → 데모/개발용 `.env`에 키 하나만 들어가면 **현장 프레임이 조용히 외부 API로 유출** = "영상 현장 외 불유출"(개인정보 3원칙·B2G 조달·파일럿 신뢰) 원칙의 침묵 붕괴 경로.
- **차단(2026-07-13)**: 클라우드 VLM은 **`VIGENT_CLOUD_VLM=1` 명시 opt-in(기본 off)** 일 때만 동작. 키만으로는 절대 전송 안 함. `incident.analyze` 순서도 **로컬 우선 → opt-in 시에만 클라우드**로 뒤집음(이중 안전: choke point 게이트 + 호출부 분기). **VIGENT_ALLOW_FALLBACK(F-8)과 동일 철학**(위험한 기본동작은 명시 opt-in 뒤로).
- **실증(off 상태 외부요청 0건)**: `OPENAI_API_KEY` 설정 + `VIGENT_CLOUD_VLM` 미설정에서 `incident.analyze(use_vlm=True)` 실행 → `socket.getaddrinfo` 로그에 **openai/api 호스트 해석 0건**, `reason_vision`=`(None,None)`, engine=로컬 MLX. (상세: 커밋 검증 로그)
- **상용 배포 미포함 주석** 명시 — 클라우드 경로는 데모/내부개발 전용.
- 백로그(D 2차): 로컬 VLM(Qwen2.5-VL-3B-4bit MLX) **ALARM 스냅샷 1장 사후 서술** = Apple Silicon **6~8초/건 실측**. Win/Linux 미니PC는 mlx 미동작 → 엣지박스 OS 선택과 연동 결정. 로컬 VLM 중국어 누출 가드(텍스트 경로엔 있음)도 착수 시 백로그.

## F-13 — RIG 줄걸이 상태기계 v2: 로직 검증 완료, 실영상 (a) 검증은 적합 footage 대기 (2026-07-13)
- **구현**: `vigent-core/rig_monitor.py`(신규, 코어 무수정 구독 방식) + `tests/test_rig_monitor.py` **5개 통과**.
  상태 IDLE→WORKING→LIFT_CHECK→CLEAR→HOISTING, 예외 ALARM (a)미이탈+임계높이초과 (b)낙상 (c)인양중 신규진입.
  임계높이 등 **설정 외부화**(RigConfig), 히스테리시스(N초), 2단계 출력(ACK/ALARM). guard/detect_frame 무수정 → 4클래스 벤치 영향 구조적 0.
- **★ 제공 영상 둘 다 핵심 (a) 실검증 불가(실측)**:
  - `크레인_재해.MP4`: 고정 CCTV지만 person 검출 박스 **면적 0.11~0.43%·높이 26~64px**(광역 오버헤드) → **하물/후크 미가시 = load 추적 불가**, 낙상(b)도 신뢰 불가. person 4~7명/프레임 검출은 되나 존 소속 판정 정도만 가능.
  - `줄걸이 재해.mp4`: 근접 인양(하물 가시)이나 **핸드헬드(장면 전환)** → 고정 존·SORTTracker 전제 붕괴.
- **★★ 필요 footage 스펙(답사 촬영 명세)**: **① 고정 카메라(삼각대/거치)** ② **후크·하물이 화면에 크게·연속 가시** ③ **인양 1사이클 전체**(결속→미동권상 10~20cm→작업자 이탈→본인양) ④ 작업자·하물 동시 프레임 내. 이 조건 충족 클립 확보 시 (a) 경보 여유시간 실측 가능.
- **★ 합성 시나리오 경보 여유시간 0.27s = 산출 '방법' 시연일 뿐. 실측 아님.** 사업계획서·데모에 "경보 여유시간" 수치로 **인용 금지**(적합 footage 실측 전까지). §7.
- 시사점(카메라 배치): 광역 CCTV(존 감시)로는 하물 높이·포즈 판정 불가 실측됨 → **광역 CCTV + 근접 카메라(하물/포즈) 2대 구성**이 근골격·인양 판정에 필요. C 부분실행 결과로 근거화.

## F-14 — 동시 부하 시 네이티브 크래시 (PyThreadState_Get: GIL released) (2026-07-14)
- **증상**: 서버가 요청을 정상 처리하다가 **런타임 중 네이티브 크래시**로 프로세스 종료(exit 133 = SIGTRAP).
  ```
  Fatal Python error: PyThreadState_Get: the function must be called with the GIL held,
  after Python initialization and before Python finalization,
  but the GIL is released (the current Python thread state is NULL)
  Python runtime state: initialized
  ```
- **재현 조건(관측)**: 브라우저 **2개 연결(53791·53794)**이 `/safety/incident/frame`(재해분석 영상 타임라인)을 연타하고, 이어 `/safety/incident/analyze` ×2(imgsz=1280 검출 + OpenAI 텍스트 종합의견 200 OK)를 처리하던 중, 사소한 `GET /home` 직후 크래시. → **동시 부하 + 무거운 다중 추론**.
- **로그 시그니처(핵심)**: faulthandler 덤프의 **모든 Python 스레드가 idle**(anyio 워커 `queue.get` 대기 · tqdm 모니터 ×3 `wait` · uvicorn asyncio `run`). 즉 fault 는 **Python 이 관리하지 않는 네이티브(C/C++) 스레드**에서 발생 = GIL 없이 Python 을 호출한 확장 모듈. 종료 시 **`loky` 세마포어 누수 경고**:
  `resource_tracker: There appear to be 1 leaked semaphore objects to clean up at shutdown: {'/loky-...'}`.
- **해석(추정, 미확정)**: torch/MPS 다모델·동시추론 불안정의 전형. CLAUDE.md 기록("MPS 다모델 반복추론 시 크래시", `_DETECT_LOCK` 직렬화, guard `prefer_mps=False`)과 시그니처 일치. **loky(joblib/torch 프로세스풀) 잔재**가 등장하는 점도 네이티브 병렬 경로 관여를 시사. **단 원인 확정은 조사 필요**(§3 태스크: MPS 경로·락 커버리지·재현).
- **LLM 변경(커밋 7382364)과의 관계**: 직접 원인일 가능성 **낮음**(크래시는 네이티브 스레드, Python llm_provider 아님, OpenAI 호출은 크래시 전 전부 200). 단 `reason_text` 가 이제 **네트워크 블로킹 호출**을 요청 스레드풀에서 수행 → 워커 점유 시간↑ → 기존 torch/MPS 레이스 **확률 간접 상승 가능성**은 배제 못 함(§4 완화 대상).
- **관련**: [[CLAUDE.md MPS 다모델 크래시]] · `COMMERCIAL_AUDIT.md`의 **"24h 무인 안정성·라이브 추적 계층·다중 카메라 미검증"** 리스크의 **실제 발현 사례**(1h soak 는 합격했으나 실브라우저 동시부하에서 크래시 — 감사 예측 적중).
- **방어(진행 예정)**: 전역 예외 핸들러(현재 3건)는 **네이티브 크래시를 못 잡음** → watchdog 자동재기동이 실질 방어. `deploy/watchdog.sh` 존재하나 macOS launchd 실증 미완(F-14 §2에서 실증).

## F-15 — P0 보안 조치 라운드 (path traversal · 의존성 · 토큰) (2026-07-15)
검증 파이썬 고정: `/opt/anaconda3/bin/python3` **3.13.9**(`.python-version`). 전 단계 34 tests OK.

- **P0-1 path traversal 차단** (`scribe.py`): evidence 경로를 `_safe_evidence_path()`로 `data/evidence` 하위 격리(`resolve()`+`is_relative_to`). `_evidence_data_uri`·`cv2.imread`(VLM) 두 경로 적용. 회귀 테스트 4종(탈출경로 None·`/etc/passwd` 이중방어·정상경로 보존). 커밋 `e8d590f`.
- **P0-2a 의존성 업그레이드**(pip-audit 실측 before→after):
  | 패키지 | before | after | 취약점 |
  |---|---|---|---|
  | Pillow | 12.0.0 | **12.3.0** | PYSEC-2026-2249~2874 (12건) → **0** |
  | requests | 2.32.5 | **2.33.0** | PYSEC-2026-2275 → **0** |
  | python-dotenv | 1.1.0 | **1.2.2** | PYSEC-2026-2270 → **0** |
  | setuptools | 80.9.0 | **83.0.0** | PYSEC-2026-3447 → **0** |
  - ⚠️ **setuptools 83 ↔ torch 2.12 충돌**: torch 가 `setuptools<82` 선언(83 은 `pkg_resources` 제거). **requirements.txt 엔 setuptools 핀하지 않음**(핀 시 pip 충돌). **런타임 무영향 실증**: torch/rfdetr import OK · `/detect/frame` 정상(person 6, 전체 검출 스택) · 서버 로그 pkg_resources 에러 0. `pkg_resources` 는 rfdetr **학습 loss** 경로에만 관여(추론 서버 미사용). 커밋 `808ab00`.
- **P0-2b torch CVE-2025-3000 — 조사만, 업그레이드 안 함(정당)**:
  - pip-audit: **fix=[] (수정 버전 없음)** → 업그레이드로 해소 불가.
  - 취약 함수 `torch.jit.script`(조작 입력 시 메모리 손상). **VIGENT 코드 미사용**(jit/load/compile 0건). 검출 스택 중 **rfdetr 2파일만** 사용: `criterion.py`·`box_ops.py` 의 **학습용 loss 함수(dice/sigmoid_ce)를 import 시 스크립트** = rfdetr **자체 고정 함수**(사용자 입력 아님). 서버는 **추론 전용**이라 학습 loss 경로 미실행.
  - **판정: 공격면 도달 불가.** `/detect/frame` 입력은 이미지(numpy)뿐 — `torch.jit.script` 에 공격자 제어 입력 0. F-14(MPS 크래시) 이력까지 감안해 **torch 2.12.0 유지**. 업그레이드는 별도 합의 후.
- **P0-3 토큰 정책**(`main.py`): 로컬 바인딩+무토큰 기동 시 경고 1줄("공유 네트워크·파일럿 필수"). 토큰 비교 `hmac.compare_digest`(상수시간, 타이밍 사이드채널 차단). `DEPLOYMENT.md` 규칙 명문화. 커밋 `32c1b34`.
- **범위 준수**: P0 밖 리팩터(main.py 분할·vlm_text 헬퍼 등)는 미착수(다음 라운드).
