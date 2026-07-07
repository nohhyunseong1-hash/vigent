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

### F-7. forklift 배포 저recall·고오탐 (제품 리스크, F-6 유형)
- 실측(LOCO 318장): 배포 운용점(conf 0.68) **forklift recall 35.71%(64% 놓침) + FAR 28.7%**(네거 80장 중 23장 오탐).
- FAR 의 실체 = **pallet_truck 혼동**(hard negative 40장 중 다수 오탐). 도메인갭+저신뢰로 recall·precision 양쪽 약함.
- → T10b 재학습에서 **pallet_truck 을 hard negative 로 포함** 필수(연기 유사 비연기 = fire_smoke 와 동일 원리). presence recall 1순위.

### 백로그 — pallet_truck 별도 검출 클래스 후보
- LOCO 에 pallet_truck(2,827inst/1,502img) 어노테이션 존재. 동력 지게차와 **협착 위험군이 상이**(수동·소형)해 forklift 로 병합 안 함.
- 향후 **별도 검출 클래스**로 추가 시 협착 위험 판정 세분화 가능(현행 `vehicle_ref_m`에 pallet_truck 폭 기준자 추가 필요). 지금은 백로그.

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
