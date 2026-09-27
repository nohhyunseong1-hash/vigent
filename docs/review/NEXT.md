# 다음에 할 것 (2026-09-28 세션 마감 기준)

> 이 문서는 **결정이 필요한 것**과 **결정 뒤 이어지는 작업**만 담는다.
> 측정 결과·근거는 각 항목이 가리키는 파일에 있다. (이전판: 2026-09-22 — 아래 "완료" 로 흡수)

## 2026-09-26 ~ 09-28 마감 요약 — 다음 세션은 여기서 시작

**완료 [실측, 커밋]**
| 항목 | 결과 | 커밋 |
|---|---|---|
| forklift fk510_smoke 로 학원 프로파일 교체 | 510 held-out AP50 **94.3 [93.6, 95.0]** · VS_02 음성 오탐 **0.1 %** [0.0, 0.3](n=2,568) · 4ch 벤치 **30분×3 통과** · AGPL YOLO(boda_ax) 의존 해소 | `fd67d6e` `694c5af` `7287bb8` `286e499` |
| PPE 재학습(507) 정지 규칙 발동 → v1 유지 | A/B/D 무효(슬롯 결함) → 유효 A′·E 모두 v1 구간 안. 슬롯 가드 추가 | `cfe83de` `1eedb97` `85775da` |
| 공개 데이터 경로 종결 | AI Hub 163(1인칭 액션캠 174/174, 코드 사진 확정)·507·510 · SHWD(MIT 표기이나 웹 수집+SCUT 연구전용, 안전모 프레임 감시 시점 0 %) · Roboflow 10종(감시 시점 최고 17 %) → 통과 0건. **CSS 자체도 감시 시점 0/30** | `328350e` `f529b7f` |
| PPE v2 현장 경로 도구 7건 | `field_prelabel.py`(2fps·v1 초벌·CVAT 1.1·negatives) · `field_split.py`(held-out 300 클립 단위 층화 "학습 금지" + 카메라 분할 누출 exit 3) · 조립기 held-out 가드 · `finetune_field_v2{,_cont}.yaml` dry-run 통과 · 하네스 3번째 집합(현장 held-out+음성 오탐, 합격선 R≥85/≥90·오탐≤1 %) · 촬영 체크리스트 · 테스트 +10(808) | `41e36b2` |

**보류**: E50(507 최종 판정 보류 — 현장 GT 로 대체) · pseudo_hardhat 판정(**불필요해짐** — 공개 데이터 경로 종결) · 163 1.공동주택 [0,0] 223장 정체(종결에 영향 없음).

**사용자 대기(결정·행동)**: ① AI Hub 510 상업 활용 문의 회신 ② 학원 DVR 녹화본(내보내기 포맷·기간·카메라 수) ③ 촬영 날짜(`docs/data/field_capture_checklist.md`) ④ 노트북 GTX 1650 Ti 4 GB 실측(fk510_smoke 학원 프로파일) ⑤ Gmail smtp_pass(이메일 2번째 채널) ⑥ 사업자 등록.

**다음 세션 첫 순서**: 현장 데이터 도착 → `field_prelabel.py`(초벌, 저장소 밖 `D:\vigent_private_data\field\`) → `field_split.py heldout`(300, 학습 금지) → `split`(카메라 단위) → CVAT 검수 → 학습 2종(`finetune_field_v2` / `_cont`, 10 epoch 마다 held-out 중간 평가) → `eval_v1_heldout.py --field-heldout` 3행 표 판정. 데이터가 없으면 ②·④ 부터.

**개발기 상태(마감 시)**: 미커밋 변경 0 · VIGENT 학습/벤치/서버/싱크 프로세스 0(GPU 점유는 데스크톱 앱뿐) · `config/notify.yaml` 원본 그대로(싱크 미적용) · `runs/finetune/` 6 run 전부 완주(best 체크포인트 있음, 정체·NaN 마커 없음) **57.5 GB** 보존(fk_510_smoke 18.1 · ppe_507_v2 8.8 · ppe_A2_slot 8.8 · ppe_E_coco 8.8 · ppe_507_v2B 7.9 · ppe_D_css_only 5.1) — 삭제는 대표 결정 · D: 여유 231 GB · **C: 여유 9.1 GB(96 %)** — 테스트·pip 캐시 주의.

## 완료 (2026-09-22 ~ 09-23)

| 항목 | 결과 | 근거 |
|---|---|---|
| **푸시 복구** | 원인 = 로그인 계정 불일치. `nohhyunseong1-hash` 로 재로그인 → `audit/cleanup-20260906` **47+ 커밋 푸시**. 이후 커밋마다 즉시 푸시(강제 금지). `main`·`fix/review-bugs` 는 원격과 동일 | `git ls-remote` 원격=로컬 확인 |
| **F-35 경보 복구** | 토큰 교체 → `getMe ok`(@VGT97_bot) → 실전송 2건 200 → 데드레터 **190건 보관 이동**(213→190 차이는 prune 추정) → `/health notify ok`, 붉은 배너 해소. 자가시험(10분 재시도·30분 노란 배너)·heartbeat 전 채널·이메일 채널 코드 완료 | `archive/deadletter_20260821_0910/` · `docs/ops/email_notify_setup.md` |
| **USB 설치기 1차** | 계획 1~6 + 승인 항목 1~5 전부 구현·커밋. 개발기 `C:\VIGENT` 임시 실설치 3회(제거 완료)로 결함 9건 잡아 수정 | `docs/deploy/usb_installer_design.md` §8-1 · `usb_install_guide.md` |
| **8GB 상한 벤치** | 4채널 30분×3회 재현성(CPU 29~31% · age p95 0.5 · ok 1.000) + 상한 모사 2회(torch 604/862MB, OOM 0). 컨텍스트 ~2.3GB 포함 **약 3.2GB 추정** — **5060 실기 미검증** | `docs/deploy/bench_4ch_repeat_2026-09-23.md` §4 |
| **cu130 결함 발견** | RTX 50(sm_120)은 cu126 미지원 → 기본값 cu130. 드라이버 하한 580. GPU 포터블 실증(1.80×). PPE onnx-cpu 는 4채널 인수시험 미달(ok 0.467) → GPU 빌드는 torch(B안) 확정 | `docs/deploy/ppe_gpu_path_2026-09-23.md` · `infer_breakdown_2026-09-23.md` |

---

## 2026-09-26 재학습 1순위 forklift(510) — 진행 기록 [실측]

| 단계 | 결과 | 근거 |
|---|---|---|
| AI Hub 수신 | VS_07_지게차 10GB(9,905장)·VS_03_공통 15GB(18,598장) — 서버 Range 미지원이라 전체 재시도 모드로 받고 `finish` 로 풀기·CRC 통과 | `D:\vigent_private_data\aihub\download_510_507.sh` v4 · `done_510.txt`·`done_507.txt` |
| 변환 | 510: 이미지 있는 프레임 12,350 · 장소 16/8 · train 8,789 / val 3,561(지게차 없음 101) · 507: 2,942 · train 2,200 / val 742 | `docs/model/aihub_A2_A5_20260926.md` A-4 재실행 절 |
| A-4 재실행 | forklift v1 R 5.8 [5.4, 6.3]·AP50 0.0(GT 10,131) · NO-Hardhat 첫 실측 R 70.4 [68.7, 72.0]·AP50 56.6 | `audit/aihub_smoke_20260926_full.json` |
| v1 "전" 행 | 510 val 3,561: AP50 0.6 [0.5, 0.7] · 음성 오탐 96.0 [90.3, 98.4](n=101) · 507 음성 96.6(n=2,000) · 학원 일치 0.0/0.5 | `benchmarks/results/forklift_v1_baseline.json` |
| **정체 사고** | 1차 학습이 18:29 부터 2시간 무진행. py-spy 3회: `torchmetrics …_get_coco_format`(검증 3,561장×500 검출 파이썬 변환). 데이터로더·디스크·OOM 아님 | `runs/finetune/fk_510_smoke/ckpt_stall_20260926_1829/fk_510_smoke_pyspy.txt`(미추적) · ALGORITHM_TRUTH §7-1 |
| 조치(승인) | 검증 층화 표본 800·2 epoch 마다·max_dets 100·workers 0·진행바 off·**정체 감시 15분 → STALL_ABORT.json+스택+exit 9**·epoch 소요/ETA 기록. 2차 실행 중 | `scripts/train/finetune_rfdetr.py` · `tests/test_finetune_guards.py` 9건 |
| **2차 학습 결과** | 10 epoch 0.78h(epoch당 4.1~4.9분, 정체 0, NaN 0, 체크포인트 검증 통과). 하네스(전체 val 3,561): **AP50 94.3 [93.6, 95.0]** · R@0.5 88.1 [87.0, 89.1] · P 97.7 · 510 음성 오탐 0.0 [0.0, 3.7](n=101, 구간 걸침) · 507 음성 1.4 [0.9, 2.0](n=2,000, 참고) · 학원 956 IoU 일치 96.4 @0.5(v1 0.0). 목표 AP50 달성, 오탐 ≤1% 는 "달성(구간 걸침)" | `docs/model/forklift_finetune_smoke_20260926.md` · `benchmarks/results/forklift_fk_510_smoke_20260926/` |
| **결정 ① 실행** | 운용 경로 대본 기준 95.7 %(boda_ax 97.7, −2.0 %p) · 4ch 벤치 합격선 통과(7.5분 2창, 30분 프로토콜 미완) → **학원 프로파일 `backend.forklift` rfdetr 교체·boda_ax 제거(AGPL 의존 해소)**. 주행 장면 04/05 86~87 % 는 §7-2 개선 항목 | `docs/model/forklift_finetune_smoke_20260926.md` §3-1 · `deploy/academy/vision.academy.yaml` · ALGORITHM_TRUTH #42 |
| ②(b) 완료 | VS_02 음성 2,568장 오탐 2장 = 0.1 % [0.0, 0.3] → 목표 ≤1 % 확정, v2(음성 혼입) 불필요 | `docs/model/forklift_finetune_smoke_20260926.md` §3-3 |
| ③ PPE 스모크 A **완료** | 00:01~01:01(10 epoch 0.99 h, NaN·정체 0). **준라벨 681장 미검수**(2026-09-26 "기각 3·17·42" 는 예시 번호 오입력). held-out 91: NO-Hardhat R 65.6 [53.4, 76.1](전 64.1) · NO-Safety Vest R 82.2(전 83.7) · 4클래스 AP50 80.5(전 81.3) — **목표(≥85/≥90) 미달, 변화는 신뢰구간 안**. dev74 PPE R 49.4(전 64.8, Mask 클래스 부재 영향 포함). 배포 없음 | `docs/model/ppe_finetune_smoke_A_20260927.md` · `benchmarks/results/ppe_smoke_A_20260927/` |
| PPE A 후속 실측(01:35) | dev74 Mask 제외 공정 비교: v1 62.3 [55.9, 68.3] → A **52.8 [46.4, 59.2]**(실제 −9.5 %p, NO-Safety-Vest 74→60/112·NO-Hardhat 14→10/54) · Safety Vest 오탐 19 중 12 는 군중 중복 박스 · 머리 박스 입력 기준 507 22.1 / held-out 20.4 / dev74 15.1 px(3배 이탈 아님, scale-aug 미적용 확인) → **축소 증강 실험 안 함**, "준라벨 제외 대조군" 제안(승인 대기) | `docs/model/ppe_finetune_smoke_A_20260927.md` §5 |
| forklift 30분×3 벤치 완료(03:15) | CPU 34.7~36.8 % · age p95 0.5 ×3 · 경보 p95 0.15~0.27 · 추론 p95 92~158 ms · VRAM torch 1,067/1,330 MB·smi 3,425 MB — 합격선 3회 통과. 노트북 4 GB 미측정 | `docs/deploy/bench_4ch_fk2_academy_2026-09-27.md` |
| 507 스캔(03:20) → 스모크 B(03:29~04:05) | 507 train 2,200장 중 v1 조끼 박스 있는 이미지 **89.8 %**(NO-SV 81.0) · 라벨 0 → 가설 채택, 조끼 준라벨 1,975장 병합해 B. 결과: held-out NO-Hardhat R **62.5 [50.3, 73.3]**(A 65.6·v1 64.1) · dev74 Mask 제외 **51.5 [45.1, 57.9]**(A 52.8·v1 62.3) — **A/B 차이 전부 구간 안**, 준라벨 채움은 결과를 바꾸지 않음. 목표 미달, 배포 없음 | `docs/model/ppe_finetune_smoke_B_20260927.md` · `benchmarks/results/ppe_smoke_B_20260927/` |
| A/B 레시피 결함 확정(14:00) | v1 10클래스 헤드는 재초기화 없이 유지됐지만(로그·헤드 텐서 동일·코사인 0.995), 데이터셋 5클래스가 슬롯 0~4 에 순서대로 들어가 person→v1 Hardhat 슬롯·Hardhat→v1 Mask 슬롯·Safety-Vest→v1 NO-Mask 슬롯 위에서 이어 학습됨(predict class_id 0~4 실측). A·B 문서 첫 줄 단서 | `docs/model/ppe_finetune_smoke_A_20260927.md` |
| 대조군 D 진행 중(14:04) | CSS v27 만(train 2,603·valid 63, held-out 제외)·v1 이어 학습·A/B 와 같은 레시피(슬롯 어긋남 포함) → 변수 = "이어 학습 자체" | `configs/finetune_aihub_v2D.yaml` · `runs/finetune/ppe_D_css_only` |
| D 완료(14:19) → **정정** | D(CSS 만, v1 이어 학습): held-out NO-Hardhat R 64.1 [51.8, 74.7](= v1)·AP50 81.2 · dev74 Mask 제외 54.5(v1 62.3, −7.8 %p). ★대표 정정: A·B·D 는 **슬롯 어긋남 결함 레시피**라 무효 → **507 효과는 미검증, 하락의 원인은 레시피 [실측 D]**. 정지 규칙은 결함 없는 실험에만 | `docs/model/ppe_finetune_ABD_summary_20260927.md` |
| **A′ 승인·진행** | 첫 유효 실험: A 와 같은 데이터(CSS+507+Hardhat 준라벨 681 미검수), `classes` = v1 10슬롯 순서 + `drop_classes`(Mask·NO-Mask·Cone·machinery·vehicle), 사전 가드(체크포인트 순서 ≠ 데이터셋 순서면 거부, 슬롯 매핑표 로그). 판정: A′>v1 구간 밖 → B′(조끼 준라벨) / A′≈v1 → E(COCO 새로 학습) 1회 / E 까지 구간 안 → 정지·v1 유지 | `configs/finetune_aihub_v2A2.yaml` |
| **A′ 완료(15:12)** | 슬롯 정렬(가드 ✓)·데이터 A 와 동일: held-out NO-Hardhat R **64.1 [51.8, 74.7]**(= v1)·NO-SV 77.0·4클래스 AP50 80.1 · dev74 Mask 제외 **51.1 [44.7, 57.5]**(v1 62.3, −11.3 %p, NO-Hardhat 9/54). **A′ ≈ v1 → 이어 학습 한계 → E 착수**(승인 경로). dev74 하락은 슬롯 충돌 때문이 아님 | `docs/model/ppe_finetune_A2_slot_20260927.md` |
| **E 완료(16:22) → 정지 규칙 발동** | COCO nano 에서 CSS+507 새로 10 ep: held-out NO-Hardhat R **62.5 [50.3, 73.3]**·NO-SV 66.7·4클래스 AP50 76.7 · dev74 Mask 제외 50.2(−12.1 %p). 유효 실험 2회(A′·E) 모두 v1 구간 안 → **PPE 재학습 중단, v1 유지.** 507 효과는 미검증(E 는 10 ep vs v1 50 ep 단서). 레시피 대조: lr·증강·해상도·EMA 전부 v1 과 동일, 다른 것은 epochs 50→10·seed — 원인 후보 기록만 | `docs/model/ppe_finetune_final_20260927.md` |
| E50 보류(대표, 16:3x) | **E 는 10 epoch 비교라 507 효과는 최종 판정하지 않음 — 보류.** PPE 는 v1 유지 | `docs/model/ppe_finetune_final_20260927.md` §2 |
| **AI Hub 163 실측 → PPE 경로 종결(20:40)** | 라벨 2 zip + 원천 1 zip 표본: 코드→이름을 **사진으로 확정**(07/08 안전모 착용/미착용 · 01/02 안전벨트 · 05/06 안전화 · 03/04 안전고리 폴리곤). 조끼·사람 클래스 없음. **촬영 시점 1인칭 액션캠 174/174 [육안]**(어안·근접) → CCTV 제품 관점 **부적합**. 조사한 후보 163·71770·71407 중 4클래스를 CCTV 도메인으로 채우는 것 없음 → **AI Hub PPE 경로 종결, v1 유지.** 다음 판정은 재방문 현장 GT 로만 | `docs/model/aihub_data_review_163_20260927.md` |
| **공개 PPE 후보 검증 → 0건(21:15)** | SHWD(MIT 표기, 이미지는 웹 수집+SCUT-HEAD 연구전용, 안전모 프레임의 감시 시점 0%) + Roboflow 10종(CC BY/PD/MIT): 감시 시점 최고 **17%**(기준 50%), 사람 p50 >0.5 또는 사람 클래스 없음, 일부는 표기 라이선스와 출처 실체 불일치 → **보조 후보 없음.** 공개 데이터 경로(AI Hub·SHWD·Roboflow) 전부 종결 | `docs/data/public_ppe_candidates_20260927.md` |
| **PPE v2 현장 경로 준비 완료(22:xx)** | 데이터 도착 전 도구 일체: `field_prelabel.py`(영상 2fps/사진 → v1 초벌 conf≥0.4 → CVAT 1.1 XML + YOLO, 사람 없는 프레임 negatives/, 저장소 안 출력 거부) · `field_split.py heldout`(카메라×주야 층화, **클립 단위** 300장, "학습 금지" heldout.json + manifest no_train) / `split`(카메라 단위, 누출 exit 3) · finetune 가드(heldout.json 자동 제외 + heldout_guard SystemExit, `${VIGENT_FIELD_DIR}`, valid_only_from, config train: 기본값, 10 epoch 마다 현장 held-out 중간 평가) · `configs/finetune_field_v2.yaml`(COCO 새로 50ep) / `_cont.yaml`(v1 이어 lr 1e-5) **둘 다 dry-run 통과**(합성 fixture: train 2,667 = CSS 2,603 + field 64 · valid = field 64 · 슬롯 가드 ✓) · `eval_v1_heldout.py --field-heldout`(세 번째 집합: 클래스별 R/P/AP50 + Wilson, 음성 오탐률; 합격선 NO-Hardhat R≥85 · NO-SV R≥90 · 음성 오탐 ≤1%) · 촬영 체크리스트. 테스트 +10(808) | `docs/data/field_capture_checklist.md` · `tests/test_field_{prelabel,split,eval}.py` |
| **다음(순서)** | **① 학원 DVR 녹화본 확인**(내보내기 포맷·기간·카메라 수 — 있으면 촬영 전 `field_prelabel.py --dry-run` 으로 프레임 수 확인) → **② 촬영**(체크리스트: 4곳·4~6명·주야 1h·조합표·동의서) → **③ 초벌 라벨·held-out 분리**(`field_prelabel` → `field_split heldout/split`) → **④ CVAT 검수**(초벌 `source="auto"` 박스 확정/수정, 특히 미착용) → **⑤ 학습 2종**(`finetune_field_v2` / `_cont`, 10 epoch 마다 held-out 중간 평가) → **⑥ 3행 표 판정**(`eval_v1_heldout.py --field-heldout`, 합격선 R≥85/≥90·오탐≤1%). **병행**: 학원 노트북(GTX 1650 Ti 4 GB) 실측: fk510_smoke 학원 프로파일로 overlay 대본 검출률 + VRAM·지연(노트북 켤 때) → USB 재빌드(fk510_smoke Release 업로드) | `docs/model/aihub_ppe_dataset_candidates_20260927.md` · `docs/deploy/bench_4ch_fk2_academy_2026-09-27.md` |
| 보류 | pseudo_hardhat 실제 판정 · E50 · 163 1.공동주택 [0,0] 223장 정체(원천 11 GB 미수신, 종결 판정에 영향 없음) | — |

---

## 남은 결정 (순서대로)

| # | 결정 | 무엇이 걸려 있나 | 근거·준비물 |
|---|---|---|---|
| 1 | **Gmail 앱 비밀번호** | 이메일 두 번째 채널 활성 — 채널이 하나뿐이면 죽는 순간 경보가 아무에게도 안 간다 | `docs/ops/email_notify_setup.md`. 코드·자가시험은 끝나 있다 |
| 2 | **촬영(재방문) 날짜** | 현장 파이프라인 재현율·PPE v2 학습 데이터 — 공개 데이터 경로가 전부 종결돼 **유일한 경로**(2026-09-27) | `docs/data/field_capture_checklist.md`(4곳·4~6명·주야 1h·조합표·동의서) · `docs/refield_plan_addendum_20260922.md` |
| 3 | **CVAT 설치일** | 초벌 라벨(`cvat/<카메라>.xml`, source=auto) 검수. 촬영 **전에** 10초 왕복 시험 권고 | `docs/labeling/cvat_setup.md` · 변환기 테스트 10건 OK |
| 2-1 | **AI Hub 510 상업 활용 문의** | fk510_smoke(510 학습) 배포 가능 여부 — 회신 전까지 학원 프로파일은 실증 용도 | 문의 발송 여부·회신 기록 |
| 2-2 | **사업자 등록** | 데이터 활용 동의서·AI Hub 문의 주체 | — |
| 4 | **노트북 push(`laptop/20260917`) → 두 계보 통합 → 실USB 빌드 → 노트북·파일럿기 재설치** | 노트북은 지금도 F-34 미반영으로 경보를 버린다. USB 는 통합 전엔 개발기 계보만 담는다 | 통합 절차 `docs/deploy/laptop_update_20260922.md`. 실USB 는 `build_usb.ps1`(**-SkipBuild 없이** 새 빌드 4.23GB) |
| 5 | **NSSM 서비스 등록 실기 1회(관리자 셸)** | 인수시험 A1·설계 §5 검증. 비관리자 셸이라 아직 못 했다 | `D:\vigent_usb_stage\설치.bat` 관리자 실행 → A1~A8 |
| 6 | **사양 판정** | 파일럿기 GPU/CPU 확정 | 근거: **4ch 2fps GPU 점유 18.6 % @5070 Ti**, **torch 604 MB**(+컨텍스트 ≈3.2GB 추정). 5060 배수는 추정하지 않았다 |
| 7 | **RTX 5060 실기 확보** | 6번의 추정을 실측으로 바꾼다. 위 수치는 전부 5070 Ti 다 | 확보 즉시 `bench_4ch.py --pkg-root … --repeat 3` |
| 8 | ~~벤치 GPU 가드 제외 목록~~ | ✅ **결정(2026-09-24)**: `NVIDIA Overlay.exe` 를 제외 목록에 추가. 게임·브라우저는 계속 차단 | `scripts/bench/bench_4ch.py` `GPU_EXCLUDE` — 개발기 재확인 결과는 커밋 메시지 |

## 결정 없이도 남아 있는 숙제

| 항목 | 상태 |
|---|---|
| 마법사 실카메라·실토큰 검증 | 미실시(개발기에 RTSP 없음). 파일럿기 설치 때 자연히 검증 |
| vcruntime 동봉본 14.38 vs 요구 14.44 | 권고 (a) 동봉본 교체 — 결정 후 구현 (`docs/deploy/vcruntime_load_2026-09-23.md`) |
| `B-alerts-test-channels` | `/alerts/test` 첫 건 `channels_sent` 미기록 — 기록 결함, 소형 |
| 검수 잔여 28장 | 보류 유지(삭제 금지). 재방문 정답지가 정본 |

## 기록만 해 둔 것 (착수 금지 — 유지)

| 항목 | 착수 조건 |
|---|---|
| `B-imgsz` 입력 해상도 실험 | 재방문 정답지 확보 후 |
| `B-finetune` 검출기 파인튜닝 | → **PPE v2 현장 경로로 대체(2026-09-27)**: 도구·설정·하네스 준비 완료(`41e36b2`), 실행은 현장 데이터 도착 후. 목표치(NO-Hardhat R≥85·NO-Safety Vest R≥90·음성 오탐 ≤1 %)는 현장 held-out 300 에서 판정 — `docs/model/ppe_rfdetr_v1_provenance.md` §8 |
| AI Hub 학습 | **종결(2026-09-27)** — forklift 는 510 으로 완료, PPE 는 507·163 부적합(`docs/model/aihub_data_review_163_20260927.md`) |
| `B-required-ppe` 필수 보호구 프로필화 | — (마법사가 `ppe.required` 를 기록하는 것으로 1차 대응) |
| `B-page-hits` `/health` 페이지 카운터 | — |
| boda_ax ONNX 변환 | 대표 AGPL 결정 후 |
| NVDEC 전환 | 인수시험 CPU 초과 시에만 |
