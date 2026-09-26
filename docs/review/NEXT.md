# 다음에 할 것 (2026-09-23 기준)

> 이 문서는 **결정이 필요한 것**과 **결정 뒤 이어지는 작업**만 담는다.
> 측정 결과·근거는 각 항목이 가리키는 파일에 있다. (이전판: 2026-09-22 — 아래 "완료" 로 흡수)

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
| 다음 | 2차 학습 완료 → 하네스 표(전/후/참고 boda_ax, 95% 구간, 전체 val 3,561) → PPE 재학습 승인 대기 | — |

---

## 남은 결정 (순서대로)

| # | 결정 | 무엇이 걸려 있나 | 근거·준비물 |
|---|---|---|---|
| 1 | **Gmail 앱 비밀번호** | 이메일 두 번째 채널 활성 — 채널이 하나뿐이면 죽는 순간 경보가 아무에게도 안 간다 | `docs/ops/email_notify_setup.md`. 코드·자가시험은 끝나 있다 |
| 2 | **재방문 날짜** | 현장 파이프라인 재현율을 영영 못 잰다(현재 "미확정") | `docs/refield_plan_addendum_20260922.md` — 45분·T1~T4 |
| 3 | **CVAT 설치일** | 재방문 정답지 제작. 재방문 **전에** 10초 왕복 시험 권고 | `docs/labeling/cvat_setup.md` · 변환기 테스트 10건 OK |
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
| `B-finetune` 검출기 파인튜닝 | 재방문 정답지에서 40px 이상 재현율이 목표 미달일 때. **목표치 선언됨(2026-09-25)**: held-out 91장 NO-Hardhat R≥85·NO-Safety Vest R≥90(정밀도 유지) / dev 74 PPE R≥80 / 최종 판정은 현장 정답지 — `docs/model/ppe_rfdetr_v1_provenance.md` §8 |
| AI Hub 학습 | 재방문 정답지 후 |
| `B-required-ppe` 필수 보호구 프로필화 | — (마법사가 `ppe.required` 를 기록하는 것으로 1차 대응) |
| `B-page-hits` `/health` 페이지 카운터 | — |
| boda_ax ONNX 변환 | 대표 AGPL 결정 후 |
| NVDEC 전환 | 인수시험 CPU 초과 시에만 |
