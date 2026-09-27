# VIGENT 알고리즘 실체 문서 (멘토링용, 2026-09-26)

> **성격**: 멘토가 읽고 질문할 자료. 코드·설정·저장소 안 측정 파일에서 **확인되는 것만** 적었고, 확인 안 되는 것은 "미확인"으로 뒀다.
> 이 문서를 만들며 **새 코드를 쓰거나 실행하지 않았다** — 읽기와 기존 측정 파일 인용만.
> 대상: 브랜치 `audit/cleanup-20260906` HEAD `98ce283`(2026-09-25). 이전 감사(`docs/review/00~08`, 2026-09-08)의 `파일:줄` 근거를 다시 열어 확인한 것은 그대로 인용했고, 그 뒤 바뀐 것은 이번에 코드를 다시 읽어 적었다.
>
> **수치 꼬리표**: **[실측]** 저장소에 측정 파일·날짜·구성이 있다 · **[추정]** 실측에서 유도했으나 직접 재지 않았다 · **[미검증]** 코드·설정은 있으나 측정이 없다 · **[문서상 주장, 코드 미확인]** 문서에만 있고 코드·측정 파일로 확인하지 못했다.
> **능력 서술 규칙**: "지원한다"는 코드 경로 + 테스트 또는 실측이 있을 때만. 코드는 있으나 한 번도 실행 안 된 것은 **구현됨·미실행**.

---

## 1. 한 장 요약

### 1-1. 입력 → 출력 처리 단계

카메라 RTSP N대(파일럿 전제 4대 · 카메라당 2fps) → 텔레그램/이메일/웹훅/HTTP 릴레이. 각 단계의 모델·라이선스·실행 위치:

| # | 단계 | 무엇을 하나 | 모델/알고리즘 | 라이선스 | 실행 위치 | 근거 |
|---|---|---|---|---|---|---|
| 1 | 캡처·디코드 | RTSP(H.264) → 카메라별 스레드가 최신 1프레임만 슬롯에 보관, 워커가 0.5초마다 1장 소비 | OpenCV FFmpeg 백엔드, 소프트웨어 디코드(HW 디코드 없음) | — | CPU | `vigent-core/worker.py:68-69,85-87,628-737,781-783,1312-1313` · `docs/review/03-video-input.md:21-36` |
| 2 | 사람 검출 | 프레임 → person 박스 | **RF-DETR Nano, COCO 사전학습 그대로**(파인튜닝 없음), 입력 384, conf 0.40 | Apache-2.0 | GPU(torch, cu130) — 전 카메라가 락 하나(`app_state.DETECT_LOCK`)로 **직렬** | `themes/safety/vision.yaml:16,33-38` · `config/tuning.yaml:80,88,102` · `weights_manifest.json:10-16` · `app_state.py:35` · `main.py:522` · `worker.py:801,907` |
| 3 | 보호구 판정 | 프레임 → Hardhat/NO-Hardhat/Safety Vest/NO-Safety Vest/Mask/NO-Mask(+Person 앙상블) | **RF-DETR Nano 파인튜닝 `ppe_rfdetr_v1.pth`**(Roboflow CSS v27 학습), conf 0.35 | 모델 Apache-2.0 · 데이터 CC BY 4.0 | GPU | `vision.yaml:21-32` · `tuning.yaml:103` · `docs/model/ppe_rfdetr_v1_provenance.md` |
| 4 | 자세 추정 | person 박스 → COCO-17 키포인트 → REBA 근골격 지표 | RTMPose-m(body7) + YOLOX-m(rtmlib) | Apache-2.0 | **CPU(onnxruntime)**, 별도 스레드 2fps | `vigent-core/pose/rtmpose_adapter.py:10,22` · `worker.py:364-403` · `tuning.yaml:181` · `weights_manifest.json:142-164` |
| 5 | 추적 | person 박스에 track id 부여 | **ByteTrack**(`trackers` 2.4.0, person 슬롯만) · 그 외 클래스는 자체 IoU+중심점 그리디 | Apache-2.0 | CPU | `agents/guard.py:304-350,744-778` · `tuning.yaml:193,207` |
| 6 | 규칙 엔진 | 박스·트랙·구역 → 위험 이벤트(규칙 7종 + 기록전용 1종) | 결정적 규칙(딥러닝 아님) | — | CPU | `worker.py:224-346,503-509` |
| 7 | 디바운스·억제 | 단일 프레임 오검출 차단, 반복 통보 억제 | 시간 디바운스(구역 1.0s/근접 0.4s)·프레임 히스테리시스(PPE 3/화재 2)·쿨다운 15s·적응형 백오프 300→3600s·시간당 6건 | — | CPU | `tuning.yaml:7-21,38-44,87,239-240` · `guard.py:290` |
| 8 | 경보 전송 | 이벤트 → sqlite 선기록 → 텔레그램→이메일→웹훅→릴레이 **순차** | 자체 큐·재시도·데드레터 | — | CPU | `docs/review/01-architecture.md:27-30,76-77` · `agents/dispatcher.py` |
| 9 | 화재·연기 | 프레임 → fire/smoke 박스 | RF-DETR Nano 파인튜닝 `fire_smoke_rfdetr_v1_e17.pth`(D-Fire), conf fire 0.30/smoke 0.50 | 모델 Apache-2.0 · 데이터 라이선스 **미확인** | GPU | `vision.yaml:19-20,31` · `tuning.yaml:116-118` |
| L2 | 에이전트 층 | **L1 내장**: 인식 로그 빈도 → 위험성평가서 초안·법령 인용·권장 행동(사람 승인, HTTP 라우트에서만). **별도 L2 저장소 2곳**(`D:\agent\vigent-l2` LangGraph 6노드 — 실모델 미실행 · `D:\agent\vigent-vlm` VLM — 실행 기록 있음)은 **L1 과 미연결** | L1 내장: 규칙 기반 + (키 있을 때만) OpenAI/Anthropic. vigent-l2: Qwen3-8B Q5_K_M GGUF(미실행). vigent-vlm: OpenRouter qwen3-vl-8b(기본) / Qwen3.6-27B 4bit 로컬 | Apache-2.0(Qwen) | CPU / 외부 API / (로컬 27B 실측 0.5~0.7 tok/s) | `vigent-core/llm_provider.py:1-19` · §3 |

### 1-2. 확정된 성능 수치 (5개)

| 수치 | 조건 | 꼬리표 | 근거(측정일) |
|---|---|---|---|
| **PPE 모델 held-out 91장 10클래스 mAP@50 76.8% · NO-Hardhat 재현율 64.1% [Wilson95 51.8, 74.7] @0.35** | CSS v27 valid/test 중 train 과 영상·stem 이 겹치지 않는 91장, 640² export, res 384, GPU. **공개 데이터셋이지 현장 CCTV 가 아니다** | [실측] | `docs/model/ppe_rfdetr_v1_provenance.md` §7-2 · `benchmarks/results/v1_heldout_eval.json`(2026-09-25) |
| **person 재현율: 검출 직전 71.3% → 추적 후 42.0%(원거리 83%→8%)** | 사고영상 9종 정지프레임 dev 74장, **1fps 표본**, IoU≥0.5, ByteTrack 운영 구성. 현장 2fps 를 대표하지 않는다는 단서가 붙어 있다 | [실측] | `benchmarks/v1_field_baseline_report.md:72-73`(2026-08-25) · `benchmarks/b_passthru_results.md:3-8` |
| **현장 2fps 추적 고신뢰 손실 3.9%(conf≥0.5)** · 전체 손실 11.7%(생존율 88.3%) | 학원 현장 34.0분·3,843프레임·실효 1.88fps·카메라 1대·대상 1명·주간. **정답지 없음**(생존율이지 재현율 아님) | [실측] | `benchmarks/b_passthru_results.md:6-7` · `reports/현장테스트_보고서_20260827_v1.2.md:300-311`(2026-08-27, 재분석 2026-09-22) |
| **4채널 2fps: GPU 직렬 점유 ≈18.6%, torch VRAM allocated 604MB / reserved 862MB, 시스템 CPU 29~31%, 검출 age p95 0.5s** | **개발기 RTX 5070 Ti**(Ryzen 9 9900X), 모의 카메라(파일), 30분×3회 + 8GB 상한 모사 2회. 파일럿기(RTX 5060)·노트북 값이 아니다 | [실측](5070 Ti) / 5060 [미검증] | `docs/deploy/bench_4ch_repeat_2026-09-23.md:95-127` · `docs/deploy/infer_breakdown_2026-09-23.md:49-55`(2026-09-23) |
| **경보 억제 89.1%(무동작 오경보 221→24건/24h) · 현장 전송 19/19건, 지연 중앙값 1.8s(최소 1.2·최대 3.7)** | 억제는 24h 소크 실데이터 재생, 전송은 학원 현장 n=19 | [실측] | `config/tuning.yaml:12-18` · `docs/review/01-architecture.md:76` · `benchmarks/field_academy_2026-08-27.md §6`(2026-08-27) |

### 1-3. 알려진 한계 (5개)

1. **현장 정답지가 없다.** 현장 카메라 기준 재현율·정밀도는 한 번도 재지 못했다(학원 929프레임은 원본 미보존, 정답=장면 대본). 사고영상 109장 정답지는 휴대폰 전달본·1fps·검수 1인이며, 그 추적 후 재현율(42%)은 2026-09-22 **폐기**됐다(§4-2). → `docs/labeling_plan.md:27-38` · `docs/review/FINAL-REPORT.md:41-99`
2. **L2(문서 자동화)는 L1 과 연결돼 있지 않다.** 별도 저장소 `vigent-l2`(LangGraph 6노드)는 실모델 실행 기록 0·브리지 0 바이트·2026-08-05 이후 미커밋 정지, `vigent-vlm` 은 문서를 만들어 봤으나 기본이 클라우드 API 이고 L1 이벤트를 읽지 않는다. L1 내장 Scribe 는 이벤트 **빈도만** 재사용한다. "감지 → 서류 자동 반영"은 아직 없다. → §3
3. **원거리 소인물·야간·역광.** 박스 높이가 화면의 10% 미만이면 dev 재현율 0~8%(1fps, 폐기 전 값이나 방향은 유효). 야간 유인·역광·우천·분진은 데이터 자체가 없다. → `benchmarks/x5_recall_knobs_interim.md:59-60` · `docs/review/02-model-inference.md:95-110`
4. **감시 중단을 원격으로 알리는 코드 경로가 0건 + 실운영 통보 채널 1개.** `alert_notify.submit` 호출부 7종에 health 전이·카메라 stale·슬롯 사망 통보 없음(2026-09-26 grep). 텔레그램 1개가 실운영(이메일 코드 완료·앱 비밀번호 대기). 2026-08-21~09-10 20일간 213건 미전달 사고가 실제로 있었다. → `docs/review/FINAL-REPORT.md:30` · `docs/review/NEXT.md:22` · §2-8
5. **배포 하드웨어 미실측·재학습 미실행·두 계보 미통합.** RTX 5060 실기 값 없음, 현장 노트북은 램프 1회(N=4 검출 p95 675ms)·4h 소크 없음. PPE 재학습은 목표만 선언(AI Hub 표본 대기). 노트북 클론(`laptop/20260917`)과 개발기 저장소가 통합 전이라 USB 는 개발기 계보만 담는다. → `docs/review/NEXT.md:25-28` · `docs/model/ppe_rfdetr_v1_provenance.md` §8

---

## 2. L1 파이프라인 단계별 실체

### 2-1. 캡처·디코드

| 항목 | 실체 | 근거 |
|---|---|---|
| 입력 | RTSP(H.264) — FFmpeg 백엔드, TCP 강제, `nobuffer/low_delay/max_delay 0.5s`. 로컬 파일·정지 이미지·USB 인덱스도 코드 경로 있음 | `worker.py:68-69,85-87,1181-1184` |
| 프레임 간격 | 카메라 등록 fps(기본 2) → 워커 루프 0.5s(`_interval`·`_full_interval`). thread 모드 캡처 스레드는 스트림의 **모든 프레임을 `grab()`** 하고(최대 60회 드레인) 마지막만 `retrieve` → 슬롯 1장 덮어쓰기 | `worker.py:679-691,717-731,781-783,1312-1313` · `tuning.yaml:182` |
| 프레임 드롭 처리 | 최신 우선(슬롯 덮어쓰기). 읽기 실패 연속 5회 → release → 재연결 백오프 1→2→4→5s(상한). 열기/읽기 타임아웃 5s(죽은 IP 123.4s→5.05s [실측]) | `worker.py:55,74,693-711` · `tuning.yaml:216,218` · `benchmarks/rtsp_capture_probe.py:19-25` |
| 지표 | 드레인으로 버린 프레임 수는 노출 안 됨(`dropped` 는 읽기 실패 수). 이벤트 시각은 캡처 시각이 아니라 기록 시각(카메라 자체 지연 ≈1.4s 미반영) | `docs/review/03-video-input.md:107-111,136-139` |
| 실측 | Tapo C200 1080p h264 15fps 1대: 검출 p50 184ms [실측]. 실카메라 24h 소크 1대 합격 [실측]. **4대 동시 실 RTSP 는 미실측**, H.265 는 현 cv2 4.13 빌드에서 **미재검증** | `docs/academy_visit_day.md:669` · `docs/review/03-video-input.md:76-81,95-99,169-178` |
| 카메라 헬스 | stale_frame/stale_detect 판정 있음. 단 카메라 사망이 hang 재기동의 `last_frame_ts` 리셋 때문에 **stale_detect 로 오분류**되는 결함이 코드에 남아 있는지 이번에 재확인하지 않았다(**미확인**, 2026-09-08 기준 P0-6) | `docs/review/03-video-input.md:63-68` |
| 하드웨어 디코드 | 없음(`CAP_PROP_HW_ACCELERATION` 미사용). NVDEC 전환은 "인수시험 CPU 초과 시에만"으로 기록 | `docs/review/03-video-input.md:23` · `docs/review/NEXT.md:50` |

### 2-2. 사람 검출

| 항목 | 실체 | 근거 |
|---|---|---|
| 모델 | **RF-DETR Nano COCO 사전학습 그대로**(`rf-detr-nano.pth`, 366,287,238B, sha `d8d6…`). 커스텀 가중치 없음. COCO 80종 중 `person` 만 통과 | `vision.yaml:16,33-38` · `weights_manifest.json:10-16` · `docs/review/02-model-inference.md:33-34` |
| 입력 해상도 | **384**(로드 시 컴파일 고정, 호출별 변경 불가). 960/640/1280 은 dev 실측 전부 악화(원인 미검증) | `tuning.yaml:88-95` · `benchmarks/p3_1_resolution_ab_v2.md` |
| 임계 | person 0.40. ByteTrack 모드에서는 저신뢰 후보 확보용으로 0.28 까지 추론 후 트래커가 고/저신뢰 분리(0.50) | `tuning.yaml:102` · `guard.py:315-316` |
| 앙상블 | `person_ensemble: true` — ppe 슬롯의 Person 클래스도 person 으로 인정. dev 74장: 재현율 55.4→70.7%(+15.3%p)·정밀도 89.7→79.9%(−9.8%p) [실측] | `tuning.yaml:97-99` · `guard.py:283-289` · `benchmarks/p2_person_ensemble.md` |
| 공개셋 성능 | raw mAP@50 **93.92%**, 배포 파이프라인 92.94%(`data/eval/clean` 74장/87인스턴스) [실측, 2026-07] | `benchmarks/EVAL.md:69-70` · `benchmarks/COVERAGE.md:10` |
| 현장 유사 성능 | dev 74장(1fps): 검출 직전 71.3% → 추적 후 42.0%(정밀도 82.5) · test 35장 59.1%/100.0 [실측 2026-08-25] · 원거리 8% | `v1_field_baseline_report.md:72-73,101-103` |
| 야간 | 사람 없는 야간 장면 오탐 86.4%(110회 중 95회) → 화각 변경 후 100% [실측]. **유인 야간 재현율 0회 측정** | `benchmarks/m2_night_person.md:15,67-69,110-116` |
| 실행 | torch cu130 GPU, fp32, 배치 없음, 전 카메라 `DETECT_LOCK`(RLock) 직렬. TensorRT/fp16 0건 | `tuning.yaml:80` · `app_state.py:35` · `main.py:522` · `worker.py:801,907` · `docs/review/02-model-inference.md:151-161` |
| 알려진 문제 | 원거리·야간·역광 미측정, 추적 후 재현율 손실(§2-5), CUDA 미가용 시 조용한 CPU 폴백은 **USB 계보에서 CRITICAL+배너로 막았음**(`device.py` `VIGENT_EXPECT_GPU`) — 기존 서비스 설치 경로에서는 미적용(**미확인**) | `docs/deploy/usb_installer_design.md:342` |

### 2-3. 보호구 판정

| 항목 | 실체 | 근거 |
|---|---|---|
| 모델 | RF-DETR Nano 파인튜닝 `ppe_rfdetr_v1.pth`(120,910,843B, sha `3380fa7d…`). best_total 체크포인트(구 주석 "best_ema" 는 오기). Colab 학습, 50 epoch, **metrics.csv·Colab·Drive 링크 미회수** | `vision.yaml:21-27` · `docs/model/ppe_rfdetr_v1_provenance.md` §2·§5 |
| 학습 데이터 | Roboflow Universe "Construction Site Safety" **v27**(CC BY 4.0): 겉보기 2,603장 = **고유 원본 514장 × 5 증강**(cutout/blur/rotate), 640² 리사이즈, 10클래스 38,835 박스. 출처 표기는 `attribution/SOURCES.md:29-40` | `docs/model/ppe_rfdetr_v1_provenance.md` §3 · `attribution/SOURCES.md:29-40` |
| **분할 누출** | 영상 단위: train∩test 5/6 영상(83%)·train∩valid 14/15(93%). 이미지 단위: valid/test 196장 중 38장(19%)이 train 과 같은 stem 또는 영상. `youtube-N` 묶음은 인접 번호 쌍이 연속 프레임(NCC 0.997)임을 화소로 확인 [실측] | `provenance.md` §3-1·§7-0 · `scripts/eval/heldout_leak_check.py` |
| 기존 인용 "test 82 mAP@50 75.62%" | 누출 분할 값. 8곳 인용에 단서 부착(원문 유지) | `benchmarks/EVAL.md:92` 외 7곳 |
| **정직한 기준선(held-out 91장, 2026-09-25)** | 10클래스 mAP@50 **76.8** · 우리 4클래스 AP50 81.3 / P 81.3 / R 78.8 @0.35 · Hardhat R 87.0 [80.6, 91.5] · **NO-Hardhat R 64.1 [51.8, 74.7]·P 69.5 [56.9, 79.7]** · Safety Vest R 80.6 [69.1, 88.6] · NO-Safety Vest R 83.7 [76.6, 89.0]. 표본 91장(원본의 13.0%, 20% 요구 미충족 — 이것이 v1 미노출 이미지 전부) [실측] | `provenance.md` §7-1·§7-2 · `benchmarks/results/v1_heldout_eval.json` |
| 누출의 효과 | held-out 76.8 ≈ stem 단위 76.3 ≈ 누출 분할 75.62 — **누출이 점수를 부풀린 증거는 없다**(소표본 점추정 비교). 현장과의 간극은 도메인 차이로 **[추정]** | `provenance.md` §0·§7-4 |
| 현장 유사(사고영상 dev 74장, 2026-08-10) | PPE 전체 정밀도 93.6%(160/171)·재현율 64.8%(160/247) · NO-Hardhat 재현율 관측 구간 [25.9%, 100%](n=14). 앱 파이프라인(1fps·ByteTrack) 경유, 클래스별 표 미기록 — held-out 과 **직접 비교 불가** [실측] | `benchmarks/v1_field_baseline_report.md:91-94` |
| 클래스 운용 | 10클래스 중 7종 사용(Person 은 앙상블용). **필수 보호구 기본 3종** `NO-Hardhat, NO-Safety-Vest, NO-Mask`(전역, 대표 지시로 고정). 학원 프로파일은 `ppe.required=[NO-Hardhat, NO-Safety-Vest]`(마스크 제외 — 490건 중 87건 마스크 단독 오탐). 정답지 변환기 `EXCLUDED_CLASSES=["Mask","NO-Mask"]` 는 학원 한정 임시 | `tuning.yaml:278-279` · `guard.py:294,427-460` · `docs/P3_BACKLOG.md:798-811` · `scripts/eval/cvat_to_gt.py:50` |
| 히스테리시스 | 연속 3프레임(≈1.0~1.5s) | `guard.py:290` |
| 알려진 문제 | 워커 필수 목록(tuning)과 브라우저 필수 목록(`ppe_rules.yaml`)이 **두 출처**(P2-2) · 하네스·장갑 클래스 없음 · **재학습 목표 선언됨(NO-Hardhat R≥85 / NO-Safety Vest R≥90, 정밀도 유지), 실행은 AI Hub 표본 대기** | `docs/review/01-architecture.md:97` · `provenance.md` §8 |

### 2-4. 자세 추정

| 항목 | 실체 | 근거 |
|---|---|---|
| 모델 | rtmlib `Body`(mode balanced): YOLOX-m humanart + RTMPose-m body7 256×192 ONNX, **onnxruntime CPU 고정**. person 박스는 RF-DETR 에서 주입(top-down) | `pose/rtmpose_adapter.py:10,22-25` · `worker.py:364-367,393` · `weights_manifest.json:142-164` |
| 주기·비용 | 포즈 스레드 2fps(검출과 분리). ORT 세션 튜닝 후 0.82→0.09코어(지연 7.3→12.3ms) [실측 2026-08-19] | `tuning.yaml:181,248-259` |
| **규칙 연결** | 산출물은 `ergonomic_risk` **하나뿐**이며 `level="low"` **기록 전용·통보 없음**(REBA 목/허리/어깨 임계, 3초 지속 시 1회). 무동작·급이동(`MotionTracker`)은 **박스 중심점 이력 기반이라 포즈와 무관**. 낙상 감지는 2026-08-06 제거. → **현 제품의 안전 판정 중 포즈에 의존하는 것은 없다** | `worker.py:483-495,503-509` · `vision.yaml:87-95` · `docs/review/FINAL-REPORT.md:207-209,258` |
| 성능 | 정확도 실측 없음 [미검증]. 참고: 광역 CCTV(작업자 26~64px)에서 키포인트 산출률 3.9%(사고 5/128) [실측] — 이 3.9% 는 §2-5 의 추적 손실 3.9% 와 **다른 값**이다 | `docs/review/02-model-inference.md:43` · `docs/P3_BACKLOG.md:115` |
| 브라우저 경로 | 라이브뷰는 MediaPipe Holistic(CDN) — 서버 경로와 별개 | `vision.yaml:69` |

### 2-5. 추적

| 항목 | 실체 | 근거 |
|---|---|---|
| 알고리즘 | person 슬롯만 ByteTrack(`trackers` 2.4.0, 칼만+2단계 매칭+전역 할당). 나머지 클래스는 자체 IoU+중심점 그리디(`_track_iou`). 웹 `/rfdetr/*` 경로는 **별도** 라이브러리 기본 ByteTrack 인스턴스(파라미터 다름) | `guard.py:304-311,636-655,744-778` · `docs/review/02-model-inference.md:118-121` |
| 파라미터 | 저신뢰 추론 임계 0.28 · 고/저신뢰 분리 0.50 · `frame_rate=10, lost_track_buffer=30` → 내부 **10프레임**(2.3fps 에서 ≈4.3s) · 최소 IoU 0.10 · 활성화 임계 = person 0.40 자동 연동 · **`bytetrack_min_frames: 0`**(첫 프레임부터 통과; 기본 1 이면 한 프레임만 스치는 사람은 영영 안 보임) | `guard.py:315-350` · `tuning.yaml:200-207` |
| 알려진 결함 | person 0건 프레임에서 `bt.update()` 미호출 → **부재 중 트래커 시간이 멈춰** 11.55초 부재 뒤에도 같은 id 복원 [실측 2026-08-13]. 구조 개선은 백로그 PQ | `guard.py:322-331` · `benchmarks/pa_live_camera_verify.md:36-52` |
| 손실률 | dev 1fps: 검출 71.3→추적후 42.0(**29.3%p**, 원거리 83→8) [실측]. **현장 1.88fps: 전체 손실 11.7%(생존율 88.3%), 고신뢰(conf≥0.5) 손실 3.9%, 그중 48.3% 가 확정 지연** [실측 2026-08-27 수집·2026-09-22 분류, GT 없음] | `b_passthru_results.md:3-8` · `docs/review/FINAL-REPORT.md:84-85` · `audit/passthru_field_20260922.json` |
| 확정 지연 | `min_frames 0` 이라 트랙 확정 자체는 즉시. 경보는 구역 디바운스 1.0s(= 2fps 에서 2~3프레임)를 넘어야 한다 | `tuning.yaml:207,239` |
| id 교체 | 학원 이동 중 20초에 4회, 단독 보행 30초 0회, 고유 id 분당 1.53개 [실측] | `benchmarks/field_academy_2026-08-27.md:122` · `reports/…v1.2.md:305` |
| 검출통과(passthrough) | **구현됨·기본 off**(`track.passthrough_conf: 0`, `zone.grid_cells: 0`). off 유지 사유: 현장 2fps 에서 디바운스를 넘는 3프레임 이상 손실 구간이 **0개** → 켜도 경보가 달라지지 않는다 | `guard.py:344-347` · `worker.py:273-283` · `b_passthru_results.md:12-13` · `reports/…v1.2.md:307` |
| 다중 카메라 동일인 연결 | **없음**(re-id/cross-camera grep 0건, 2026-09-26) | 이 문서 작성 시 grep |

### 2-6. 규칙 엔진

워커(`worker._derive` + `MotionTracker` + `ErgonomicsTracker`)가 내는 이벤트 전부:

| 규칙 id | 등급(워커 코드) | 쓰는 신호 | 발화 조건 | 근거 |
|---|---|---|---|---|
| `zone_intrusion` | high | person 박스 **발끝점**(하단 중앙) + 카메라별 폴리곤 + track id(없으면 격자 키, 기본 off) | 트랙별 시간 디바운스 enter 1.0s 확정 시 1회. 장비 탑승자(포함비 ≥0.65)는 제외 | `worker.py:245-317` · `tuning.yaml:239-246` |
| `ppe_missing` | **high** | guard `signals.ppe_missing`(필수 3종 중 미착용 라벨) | 연속 3프레임 | `worker.py:318-322` · `guard.py:290` |
| `fire_smoke` | critical | fire_smoke 슬롯 | 연속 2프레임 | `worker.py:323-324` |
| `proximity_hazard` | high | person↔장비(forklift/truck/…) 박스 최단 간격 × (장비 실제폭/박스폭) → m 환산, 반경 3.0m | 디바운스 enter 0.4s(연속 2회). **캘리브레이션 없음**, 운전자 제외 포함비 0.65 | `worker.py:325-341` · `tuning.yaml:36-61` · `proximity.py:103-112` |
| `crowd_density` | mid | person_count ≥ 6 | 프레임 즉시 | `worker.py:343-345` |
| `immobility` | high | person 박스 중심점 이력(45s, 표본≥5, 이동 <3%) | 45초 정지. **낙상 감지가 아니다** | `worker.py:503-509,627` · `tuning.yaml:63-74` · `FINAL-REPORT.md:209` |
| `rapid_motion` | mid | 1.0s 창 이동 ≥0.15 | 즉시(카메라 자체 이동 프레임은 억제) | `tuning.yaml:67-69` |
| `ergonomic_risk` | low(기록 전용) | RTMPose 키포인트 REBA | 3초 지속 | `worker.py:483-495` |
| `guard_bypass` | critical | 손 키포인트 in `machine_zone.json` | **브라우저 `/detect/frame` 경로에만** 존재, 서버 워커 경로 0건 | `docs/review/01-architecture.md:91,248-250` |

- **구역 정의**: 카메라 등록부 `data/cameras.json` 의 정규화 폴리곤(허브에서 편집, 저장 시 워커 재시작). 카메라별 구역이 없으면 **판정하지 않는다**(`zone.global_fallback: false`). 기준점 foot/center 선택 가능. 시간대·요일 규칙 없음. → `tuning.yaml:229-246` · `docs/review/01-architecture.md:88-109`
- **등급→동작**: `vision.yaml:121-126` — critical: alarm+manager_call+safety_relay_signal / high: alarm+manager_call / medium: log. 지게차 검출은 전역 모델 불용(mAP@50 8.83%)으로 기본 슬롯 제외 → **safety 프로파일에서 `proximity_hazard` 는 사실상 무동작**(학원 프로파일만 AGPL YOLO `forklift_boda_ax` 로 동작). → `vision.yaml:18` · `tuning.yaml:109-114` · `FINAL-REPORT.md:34,111`
- **설정 불일치**: `vision.yaml:85` 는 `ppe_missing` severity **medium** 이라 선언하고(Analyst 가 이 값을 읽는다 `agents/analyst.py:41-43`), 워커는 **high** 로 발화한다(`worker.py:322`). 운영 통보 경로는 워커 값을 쓴다(현장 133건 통보 발생 `reports/…v1.2.md:293`).

### 2-7. 디바운스·오탐 억제

| 장치 | 있음/없음 | 값 | 근거 |
|---|---|---|---|
| 시간 디바운스(구역) | **있음** | enter 1.0s / exit 1.0s(비대칭 아님, 둘 다 1.0). 첫 관측은 항상 '밖'. 시간 기준인 이유: 캐던스가 2.3~5fps 로 변함 | `tuning.yaml:239-242` · `zone_debounce.py:30-52,75-99` |
| 시간 디바운스(근접) | **있음** | enter 0.4s / exit 1.0s(**비대칭** — 해제를 늦게) | `tuning.yaml:38-45` |
| 히스테리시스(PPE·화재) | **있음(프레임 기준)** | PPE 연속 3, 화재 연속 2. 현장 검출 기록 분석으로 "3→2 완화 가능·1 금지" 판정 | `guard.py:290` · `audit/hysteresis_2026-08-29.md` |
| **N-of-M 시계열 투표** | **없음** — 전부 "연속 N" 또는 "시간 유지". 한 프레임 끊기면 리셋 | `zone_debounce.py` 상태기계 |
| 사람 단위 쿨다운 | 있음 | 15s, 키 `rule|t<tid>`(증거 JPEG 는 별도 30s) | `worker.py:92,95,1104-1112` · `tuning.yaml:87` |
| 통보 게이트 | 있음 | 카메라+규칙 단위 300s → ×2 → 3600s 상한, 시간당 6건, 등급 상승 예외, 억제 건수 부기. 재생 검증 89.1% 억제 [실측] | `tuning.yaml:7-21` · `alert_gate.py` |
| VLM 오탐 확인 | **브라우저 경로만** | `vlm_confirm` 은 `routers/zone.py:110`·`safety_core.py:286` 에서만 호출. **워커 경로에 VLM/LLM 호출 0건**(grep 2026-09-26) | 이 문서 작성 시 grep |
| 카메라별 마스크(제외 영역) | **없음** — 카메라별 폴리곤은 "감시 구역"이지 제외 마스크가 아니다 | grep `ignore_zone|exclude_zone|mask_zone` 0건 |
| 시간대 프로파일 | **없음** | grep `time_window|work_hours|weekday` 0건 |
| 야간·역광 대응 | **없음**(코드·데이터 모두) | `docs/review/02-model-inference.md:99-101` |

### 2-8. 경보 전송

| 항목 | 실체 | 근거 |
|---|---|---|
| 채널(코드) | 텔레그램(텍스트, 사진 미첨부) · 이메일(SMTP) · 웹훅(POST) · HTTP 릴레이(GET/POST, 기본 off, 실물 미보유) | `agents/dispatcher.py:157-204` · `relay.py:70-82` · `tuning.yaml:281-292` |
| 채널(운영) | `config/notify.yaml` 에 텔레그램 토큰·chat + smtp 키 4개 존재(값 미열람). **이메일 활성은 Gmail 앱 비밀번호 대기** → 실운영 원격 채널 1개 | `docs/review/NEXT.md:22` |
| 동시 전송 | **없음 — 통보 스레드 1개가 텔레그램(6s)→이메일(8s)→웹훅(6s)→릴레이 순차**. 최악 건당 ≈20s, 릴레이는 원격 3채널 뒤 | `docs/review/01-architecture.md:76-77,202-205` |
| 선기록·재시도 | sqlite 선기록 → 5s 드레인, 백오프 1..60s, **10회 후 dead, dead 는 재전송 안 함**(≈4.5~5.5분 단절이면 영구 소실). 4xx 는 즉시 dead | `tuning.yaml:33-34` · `docs/review/01-architecture.md:45,197-200` |
| 자가시험 | 기동 시 배경 스레드에서 텔레그램 `getMe`(8s 타임아웃) — ok/config_error 확정까지 10분마다 재시도, 망 오류는 단정하지 않음(30분 뒤 노란 배너). `VIGENT_NOTIFY_SELFTEST=0` 으로 끔 | `agents/dispatcher.py:143-209` · `main.py:493` |
| heartbeat | 하루 1회 "채널 정상" 메시지 — `notify.heartbeat_at` 설정 시만(기본 **끔**). 경보 큐를 타지 않는다 | `notify_heartbeat.py:1-15` · `tuning.yaml:294-298` |
| 데드레터 | dead 요약 통보 1h/1회(같은 채널 → 채널이 죽으면 같이 죽음). **2026-08-21~09-10 토큰 401 로 20일간 경보 213건 미전달**(발견 2026-09-22) → 2026-09-23 토큰 교체, dead 190건 `archive/deadletter_20260821_0910/deadletters.jsonl` 로 **이동**(23건은 보존 prune 으로 사라진 것으로 추정) | `notify_heartbeat.py:5-6` · `archive/deadletter_20260821_0910/README.md` |
| 시험 발송 | `POST /alerts/test`(토큰 필요). 2026-09-23 실전송 2건 200 [실측] | `routers/safety_core.py:748` · `NEXT.md:11` |
| 현장 실측 | 판정 270건 → 폰 19건(14.2:1), 전송 19/19, 지연 중앙 1.8s [실측 2026-08-27]. ★단 그 노트북은 F-34 미반영 버전이라 유실분이 있을 수 있음 | `reports/…v1.2.md:290-295` |
| 감시 중단 통보 | **없음** — health 전이·카메라 stale·슬롯 사망·예열 실패를 원격으로 알리는 `submit` 호출 0건(2026-09-26 grep: 호출부는 alert_dead·privacy·manual·sensor·brain·browser_zone·worker 7종) | 이 문서 작성 시 grep · `FINAL-REPORT.md:30` |

### 2-9. 화재·연기

| 항목 | 실체 | 근거 |
|---|---|---|
| 모델 | RF-DETR Nano 파인튜닝 `fire_smoke_rfdetr_v1_e17.pth` — D-Fire 데이터로 Colab 학습, 30 epoch 중 17 epoch(val 피크) 체크포인트. **별도 모델**(PPE 와 다른 가중치, 같은 아키텍처) | `vision.yaml:19-20,31` · `vigent-core/weights/MANIFEST.md:93,97` |
| 클래스·임계 | `smoke`, `fire`. 클래스별 conf fire 0.30 / smoke 0.50(단일 폴백 0.55) | `tuning.yaml:115-120` |
| 성능(공개셋) | D-Fire test 395장 box mAP@50 **80.13%**(fire 75.28 / smoke 84.98) · 운용점 presence recall **fire 95.91% / smoke 87.88%**, FAR fire 1.1% / **smoke 15.4%** [실측, in-domain] | `benchmarks/EVAL.md:132-139` · `benchmarks/FINDINGS.md:35-36` |
| 현장 | **현장 재검증 대기**(0회). 학원 프로파일에서는 슬롯 off | `vision.yaml:20` · `FINAL-REPORT.md:259` |
| 히스테리시스 | 연속 2프레임 → critical → 릴레이 대상 | `guard.py:290` · `vision.yaml:124` |
| 데이터 라이선스 | D-Fire 라이선스 표기가 `attribution/SOURCES.md`·`MANIFEST.md` 에 **없다 → 미확인** | grep 결과 |

---

## 3. L2 에이전트 층 (2026-09-26 재작성 — L2 별도 저장소 3곳을 열어 확인)

> **L2 저장소 위치**: `git filter-repo` 로 분리된 L2 는 개발기 `D:\agent\` 아래에 **세 갈래**로 있다. 셋 다 이번에 직접 열어 코드·커밋·파일 시각을 확인했다(테스트 실행·모델 기동은 하지 않았다). L1 저장소(`D:\vigent_original`) 안의 `vigent-core/agents/` 는 네 번째 계보다.
>
> | 저장소 | 성격 | git | 마지막 활동 | 근거 |
> |---|---|---|---|---|
> | **`D:\agent\vigent-l2`** | "VIGENT L2 Scribe" — 문서 3종(작업계획서·위험성평가서·TBM) 자동 생성 **LangGraph 파이프라인**, 에어갭·로컬 LLM 전제 | `master`, 커밋 4건(P0~P3, 2026-08-04) + **미커밋 Phase 4a 작업**(7파일 수정·15파일 신규, 2026-08-05 01:52) | 2026-08-05 | `git log`·`git status`(2026-09-26) · `MASTER_SPEC.md` |
> | **`D:\agent\vigent-vlm`** | "위험성평가 작성 Agent (VLM)" — 사진/영상 → VLM → xlsx/pdf 3종. LangGraph 아님(단일 오케스트레이터) | `main`, 커밋 3건(2026-08-19 ×2, 08-31) | 2026-08-31 | `git log` · `README.md` |
> | `D:\agent\vigent` | **L1 의 구 클론**(`fix/review-bugs`, 2026-08-08) — L2 아님 | — | 2026-08-08 | `git log` |
> | `D:\vigent_original/vigent-core/agents/` | L1 안의 경량 에이전트 7클래스(§3-3) | L1 저장소 | 진행 중 | Glob |
>
> `D:\agent\vigent_subsidy`(2026-09-25, 보조금 매칭 웹앱)는 안전 문서 에이전트가 아니라 제외했다.

### 3-1. `D:\agent\vigent-l2` — "6-agent LangGraph 구조"의 실체

| 질문 | 답 | 근거 |
|---|---|---|
| LangGraph 그래프가 코드로 존재하는가 | **있다(미커밋).** `build_graph()` 가 `StateGraph(PipelineState)` 에 **노드 6개**(`planner → hazard_mapper → law_retriever → work_plan → generator_validator → tbm`)를 순차 연결한다. 단 **본체는 순수 함수 `run_pipeline`** 이고 LangGraph 는 같은 함수를 감싼 얇은 래퍼다 | `src/vigent/pipeline/graph.py:165-205`(미커밋, 2026-08-05) · `pyproject.toml:29`(`langgraph>=0.2`, optional `pipeline` 그룹) |
| 스펙의 "6-agent"와 코드의 대응 | MASTER_SPEC §6: Planner · HazardMapper · LawRetriever · Generator · Validator · Renderer(+개발용 Evaluator). 코드: **Planner ✅ · HazardMapper ✅ · LawRetriever ✅ · Generator ✅ · Validator ✅**(`pipeline/agents/{planner,hazard_mapper,law_retriever,generator,validator}.py`, 미커밋) · **Renderer ❌**(`src/vigent/render/__init__.py` 0 바이트, Phase 5 미착수) · Evaluator ✅(`evalx/`, P3 커밋) · Transcribe(TBM 음성)는 **fixture 스텁만**(`agents/transcribe.py` `FixtureTranscriber` — 사이드카 txt 읽기, Whisper 없음) | `MASTER_SPEC.md:208-226` · Glob(2026-09-26) · `tests/test_pipeline.py:222-231` |
| 테스트 | `tests/` 14파일, `def test_` **107개**(이번에 실행하지 않음 — 마지막 실행 기록은 P3 커밋 시점). 파이프라인 테스트 16개는 **`ScriptedLLMClient`(결정적 스텁)** 로 배관·재시도·hard fail 을 검증한다 — **실제 LLM 은 어떤 테스트도 호출하지 않는다.** `build_graph`(LangGraph 래퍼) 를 부르는 테스트는 **0개**(grep) | `tests/test_pipeline.py:1,94-101` · `src/vigent/llm/client.py:116-142` |
| 원칙 준수(코드로 확인) | LLM 은 산수 금지(위험성=빈도×강도 코드 계산, `to_risk_entry`) · 법적 근거는 후보 인덱스 선택만·화이트리스트 밖 hard fail · 구조화 출력은 `response_format=json_schema` 제약 디코딩 · 로컬호스트 외 엔드포인트는 생성 시점 거부 | `pipeline/agents/generator.py:1-4` · `llm/client.py:7-9,62-67,101-110` · `tests/test_llm_client.py:65-70` |
| **Qwen3-8B-NVFP4 가 실제 로드·실행된 기록이 있는가** | **NVFP4 표기·파일은 세 저장소 어디에도 없다**(`nvfp4` grep: 코드·설정 0건). 있는 것은 **`models/Qwen3-8B-Q5_K_M.gguf`(5.85GB, 2026-08-05 00:46 다운로드)** 와 `tools/llamacpp/`(llama-server.exe 등 CUDA 빌드 바이너리). 서빙 계획은 개발 = llama-server(`http://127.0.0.1:8080/v1`), 납품 = vLLM guided decoding. **실행 기록은 없다**: `vigent generate`(실모델 파이프라인) 의 산출물 `out/candidates/run_summary.json` 이 **존재하지 않고**, `out/` 에는 P3 채점 결과 2파일(2026-08-04 23:27, 합성 케이스 자가 채점, `"judge 미가용 (로컬 LLM 서빙 전)"`, `"warning": "합성 케이스만 포함 — 이 결과로 모델 선정 불가"`)뿐. 로그·벤치 파일 0건 | `configs/models.yaml:21,39-51` · `models/` 목록 · `out/eval_results.json:57,207-208` · `src/vigent/pipeline/runner.py:117` |
| 모델 후보·라이선스 | `configs/models.yaml`(미커밋): 후보 qwen3-14b(Q4_K_M 9.0GB) · **qwen3-8b(Q5_K_M 5.85GB)** · A.X-4.0-Light(Apache-2.0, GGUF 자체 변환 필요), 예비 kanana-1.5-8b, 배제 EXAONE-4.0(NC). 라이선스는 HF 모델 카드 확인(2026-08-05). **최종 선정은 "골든셋 채점으로" — 아직 안 됨** | `configs/models.yaml:1-7,23-86` |
| 골든셋·평가 | 케이스 3건(`goldenset/cases/case_001~003`)은 **합성(synthetic)** — 원본 pptx 3건(`goldenset/raw/`, 제조·물류·건설)의 Docling 변환은 미완. 채점 하네스는 expected 자가 채점에서 만점(스키마·산수 게이트 통과, 법적근거 F1 1.0) — 즉 **채점기 검증**이지 생성 품질 측정이 아니다 | `out/eval_results.json` · `goldenset/` 목록 |
| L1↔L2 인터페이스 | **없다(스텁 계약만).** `src/vigent/bridge_l1/__init__.py` **0 바이트**, `src/vigent/api/__init__.py` **0 바이트**(FastAPI Phase 6 미착수). 있는 것은 Pydantic 계약 `L1Event{camera_id, timestamp, event_type, zone, confidence, sop_rule_ref}` 하나 — 어느 코드도 이를 채우거나 읽지 않는다(Phase 7 "fixture 기반 브리지" 계획). L1 저장소 쪽에도 `vigent-l2`·`bridge_l1` 참조 0건 | `src/vigent/schemas/l1_event.py:1-16` · `MASTER_SPEC.md:293-297` · L1 grep(2026-09-26) |
| 상태 한 줄 | **구현됨·미실행**: 배관(스키마·검증·화이트리스트·제약 디코딩 클라이언트·LangGraph 래퍼)은 코드와 스텁 테스트로 존재하나, **실제 LLM 으로 문서를 한 번도 생성하지 않았고**(기록 기준), 렌더러·API·L1 브리지는 빈 패키지, Phase 4a 작업은 미커밋 상태로 2026-08-05 이후 멈춰 있다 | 위 표 |

### 3-2. `D:\agent\vigent-vlm` — 실제로 문서를 만든 쪽

| 항목 | 실체 | 근거 |
|---|---|---|
| 구조 | LangGraph 아님. `risk_assessment_agent/agent.py` 단일 오케스트레이션: 사진/영상(대표 프레임 N장) → VLM → 구조화 JSON → 국가법령정보센터 API 로 조문 대조·정정 → xlsx/pdf(위험성평가서·TBM 일지·작업계획서). 위험성=빈도×강도는 코드 계산 | `README.md:7-55,248-264` |
| 모델 | **기본 = 클라우드 OpenRouter `qwen/qwen3-vl-8b-instruct`**(외부 API — L2 스펙의 "에어갭·외부 API 금지" 원칙과 반대 방향). 로컬 옵션 = `tools/local_vlm_server.py`(transformers + bitsandbytes **4bit nf4**, OpenAI 호환 `127.0.0.1:8000/v1`)로 **`D:\models\Qwen3.6-27B`**(55.6GB bf16, 2026-08-21 보유). 구조화 출력은 프롬프트 JSON 요청 + 정규식 추출(제약 디코딩 아님) | `.env.example:6-14` · `tools/local_vlm_server.py:1-11,29-37` · `vlm_client.py:46-60` · `D:\models` 목록 |
| ★**영상 불유출 원칙과 상충** | `.env.example:14` 기본 `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1` + 키만 넣으면 **현장 사진·영상 프레임이 외부 사업자로 나간다**. L1 은 `VIGENT_CLOUD_VLM=1` **and** 키의 이중 opt-in(기본 off, `llm_provider.py:115`)인데 vigent-vlm 은 게이트가 없다(루프백이면 키 검사만 건너뜀 `config.py:34`). **변경안(코드 미수정, 기록만)**: ① 기본 `OPENROUTER_BASE_URL` 을 `http://127.0.0.1:8000/v1`(로컬 서버)로 바꾸고 ② 외부 호스트는 `VIGENT_CLOUD_VLM=1` 이 명시돼 있을 때만 허용(`config.py` 로드 시 호스트가 루프백/사설 대역이 아니고 플래그가 없으면 거부) ③ 전송 전 얼굴 비식별화(L1 `privacy.anonymize_faces` 재사용) ④ README 의 기본 경로를 로컬로 서술 — L1 게이트(F-12)와 동일한 규칙으로 통일 | `vigent-vlm/.env.example:14` · `config.py:34,54-64` · L1 `llm_provider.py:111-116` |
| **실행 기록** | 있다. `output/` 에 위험성평가서 1~12 + `로컬테스트*` 6종(2026-08-31 19:46~21:51, xlsx/pdf/json 50파일). README 에 로컬 실측: **RTX 5070 Ti 16GB + 64GB RAM, Qwen3.6-27B 4bit, 53/64 레이어 GPU, 로딩 약 6분, 0.5~0.7 tok/s, 사진 1장 → 6종 문서 45분(1,422토큰)**. 단 출력 JSON 에 모델명 필드가 없어 **어느 파일이 클라우드/로컬 산출인지 파일만으로는 구분 못 한다**(README 수치는 [문서상 주장]) | `README.md:102-111` · `output/` 목록(2026-09-26) |
| 테스트 | **0개**(`tests/` 없음) | Glob |
| L1↔L2 인터페이스 | `tools/watch_server.py` 가 **HTTP 디렉터리 목록/JSON 목록/공유 폴더를 폴링해 새 영상 파일**을 처리한다 — L1 의 이벤트·`/recognition` API·증거 JPEG 를 읽는 코드는 없다. 즉 "서버 연동"은 **영상 파일 감시**이지 L1 이벤트 연동이 아니다. 현재 L1 서버는 영상 파일을 어디에도 올리지 않으므로 **연결돼 있지 않다** | `tools/watch_server.py:1-17` · `README.md:207-228` |

### 3-3. L1 저장소 안의 에이전트(`vigent-core/agents/`) — 운용 경로에 붙어 있는 것

| 질문 | 답 | 근거 |
|---|---|---|
| 구조 | `base, guard, analyst, scribe, copilot, safety_manager, dispatcher` 7파일 — 일반 Python 클래스(`BaseAgent`), LangGraph 없음. `md/AGENT_STATUS.md` 의 `coach.py` 는 제거됨(2026-09-26 정정) | Glob · `agents/analyst.py:35` |
| 실제 LLM | 텍스트: **OpenAI API(기본 gpt-4o-mini) 또는 Anthropic API** — 키가 있을 때만, 실패·오프라인이면 `(None, None)` 을 돌려 **규칙 기반 폴백**. Ollama 로컬은 2026-07-14 제거. 비전: 로컬 VLM 설정은 `mlx-community/Qwen2.5-VL-7B-Instruct-4bit`(**Apple MLX 전용 — Windows 에서 미동작**), 클라우드 비전은 `VIGENT_CLOUD_VLM=1` **and** `OPENAI_API_KEY` 둘 다 있을 때만 | `llm_provider.py:1-19,107-116,147-164` · `vision.yaml:98-101` · `README.md:30` |
| `VIGENT_CLOUD_VLM` 게이트 | 기본 off. off 상태에서 `incident.analyze(use_vlm=True)` 실행 시 외부 호스트 해석 0건 [실측 2026-07-13]. 전송 전 얼굴 비식별화. 현재 `.env` 에 키·플래그 없음(2026-09-08 확인) | `llm_provider.py:111-116` · `benchmarks/FINDINGS.md:278-279` · `docs/review/05-security-privacy.md:167` |
| 어느 이벤트에서 호출되는가 | **워커(카메라 루프)에서는 호출되지 않는다**(`worker.py` grep `llm|vlm|analyst|scribe|copilot` 0건 — L1 저장소 사실, 유지). 호출부는 전부 **HTTP 라우트**: `/report/safety`·`/safety/auto/approve risk_assessment`(Scribe), `/safety/live/analyze`·brain 계열(`routers/safety_core.py:133,386-404,581-637`), `/safety/incident`(`incident.py:56,117,145,164`), 구역 브라우저 경로 VLM 확인(`routers/zone.py:110`). 즉 **사람이 버튼을 누르거나 브라우저 시연 경로를 쓸 때만** 돈다 | grep(2026-09-26) |
| L1 이벤트 → 문서 연동 | Scribe 는 인식 로그 이벤트의 **빈도(count)만** `_likelihood` 로 재사용하고, 감지 규칙→체크리스트 항목 자동 O/X 는 없다("빈도 통계 재사용 수준", 팀 문서가 🔴로 표시) | `agents/scribe.py:124,254-268,580-591` · `docs/team/01_현황_숫자로_보기.md:63` · `docs/team/20_에이전트트랙_기획안.md:34,41-53` |
| 각 에이전트의 실체 | Guard = 검출·추적(§2). Analyst = 규칙 severity 가산 점수(`_SEVERITY_WEIGHT` critical 100/high 60/medium 30/low 10 → 등급). Scribe = KOSHA KRAS 서식 위험성평가서 HTML 생성(규칙→KB 매핑, LLM 은 '종합의견' 한 문단만 opt-in). Copilot = 법령 인용(`safety_citations.json`, 화이트리스트 게이트로 가짜 조문 차단 실증). SafetyManager = 등급별 **권장 행동만** 반환, `requires_approval=True`, 자동 실행 0. Dispatcher = 채널 전송(§2-8) | `agents/analyst.py:1-32` · `agents/scribe.py:1-12` · `agents/safety_manager.py:1-13` |
| 검증 상태 | 골든셋 정답 30건 미작성(사용자 몫) → 판단 품질은 **채점된 적 없다**(T1 홀드아웃 15케이스 11/15 는 체크리스트 채점). Copilot 법령 게이트만 실동작 실증 | `md/AGENT_STATUS.md:41-49` · `docs/team/01_현황_숫자로_보기.md:57` |

### 3-4. 종합 — 멘토가 "L2 는 뭐가 있나"라고 물으면

- **네 계보가 있고 서로 연결돼 있지 않다.** ① `vigent-l2`: LangGraph 6노드·제약 디코딩·화이트리스트 설계는 코드로 있으나 **실모델 실행 기록 0, 렌더러·API·L1 브리지 빈 패키지, 2026-08-05 이후 미커밋 정지**. ② `vigent-vlm`: 실제 문서 xlsx/pdf 를 만들어 봤고 로컬 27B 4bit 실측(45분/장)이 있으나 **기본이 클라우드 API 이고 테스트 0, L1 이벤트 연동 없음**. ③ L1 내장 agents: 운용 경로(`/report/safety` 등)에 붙어 있고 키 없이도 규칙으로 도나 **빈도 재사용 수준**. ④ 구 L1 클론.
- **"Qwen3-8B-NVFP4"** 라는 이름의 모델·설정은 세 저장소·`D:\models` 어디에도 없다. 가장 가까운 것은 `vigent-l2` 의 **Qwen3-8B Q5_K_M GGUF(내려받음, 미실행)** 와 `vigent-vlm` 의 **Qwen3.6-27B 4bit(nf4, 실행 기록 있음)** 이다. **NVFP4 양자화본이 다른 경로에 있다면 그 위치를 알려 달라 — "없다"고 단정하지 않는다.**
- **L1→L2 연결 상태: 없음.** L2 쪽 브리지는 0 바이트 패키지, L1 쪽에는 L2 를 부르는 코드 0건. 유일한 연결은 L1 내장 Scribe 가 인식 로그의 이벤트 빈도를 읽는 것뿐이다.

### 3-5. "LLM 이 안전 판단에 개입하나" — 개입 지점과 하지 않는 지점

| 지점 | LLM/VLM 개입 | 근거 |
|---|---|---|
| 카메라 프레임 → 검출·추적·규칙·디바운스·경보 전송(§2 전체) | **개입 없음.** 결정적 모델(RF-DETR)+규칙만. 워커에 LLM 호출 0건 | grep |
| 경보 등급(critical/high/mid) | **개입 없음** — 워커 코드 상수 | `worker.py:245-346` |
| 위험구역 침입의 브라우저 경로 오탐 억제 | VLM `vlm_confirm` 이 REJECT/SUPPRESS 확률을 계산 — **브라우저 시연 경로만**, 판정 미영속화 | `routers/zone.py:110` · `docs/review/02-model-inference.md:232` |
| 위험성평가서 '종합의견' 문단 | 텍스트 LLM opt-in(`use_llm=True`). 점검항목·법령 인용·위계 분류는 규칙. 한자 누출 시 규칙 폴백 | `llm_provider.py:12-13,161-163` |
| 사고 사진 원인분석(`/safety/incident`) | VLM(로컬 MLX 또는 클라우드 opt-in) — Windows 에서는 클라우드 opt-in 없으면 규칙·지식베이스만 | `incident.py:160-190` |
| 법령 조문 | VLM 이 낸 `관련법령` 은 화이트리스트(`statutes.yaml` 14개 active)로 **차단/보류** — 가짜 999조 차단 실증 | `md/AGENT_STATUS.md:15,33` |
| 설비 정지 | **어떤 층도 정지시키지 않는다.** 릴레이 신호는 §8.1 보조 신호, `is_primary_safety: False` 고정 | `routers/dispatch.py:40-41` · `docs/review/04-alerting-integration.md:65-70` |

→ 한 줄 답: **"실시간 안전 경보에는 LLM 이 개입하지 않는다(L1 저장소 사실). LLM 은 사람이 요청한 문서·분석의 서술 문단에만, 키가 있을 때만, 규칙 폴백을 두고 쓴다. 별도 L2 저장소(`vigent-l2`·`vigent-vlm`)는 L1 과 연결돼 있지 않으므로 현재 어떤 경보에도 영향을 주지 않는다."**

---

## 4. 데이터·평가 실체

### 4-1. 정답지 목록

| 정답지 | 규모·출처 | 잴 수 있는 것 | 못 재는 것 | 근거 |
|---|---|---|---|---|
| **사고영상 1fps 109장** (dev 74 / test 35, 영상 단위 분할·동결) | 사고 재현 영상 9종(KakaoTalk 전달본, 360~720p 재인코딩, 0.21~2.04Mbps), 1초 간격 정지프레임. 자체 모델 conf 0.10 초안 → 로컬 CVAT 에서 **1인 1회 검수**. person 박스 201개. **사람이 있는 17구간(≈83프레임)이 라벨되지 않음** | person·PPE 정밀도/재현율(IoU≥0.5), 검출 직전 vs 추적 후 분리, 원거리(박스 높이<10%) 대리지표 | 현장 고정 CCTV 조건(앵글·해상도·2fps), 야간·역광, 교차검수된 품질, mAP@50:95(초안 박스와 IoU=1.0 순환 오염이라 인용 금지) | `FINAL-REPORT.md:45-99` · `data/field_eval/README.md:16-23` · `benchmarks/field_eval_results.md` |
| **held-out 91장** (CSS v27) | 공개 데이터셋 valid/test 중 train 과 영상·stem 미겹침 91장(valid 51/test 40), 640² export | PPE 10클래스 AP50·P/R·Wilson 구간, **재학습 전후 비교(같은 파일 목록)** | 현장 성능(공개셋 도메인), 소표본(클래스별 박스 9~232) | `provenance.md` §7 · `benchmarks/results/v1_heldout_eval.json` |
| **현장 데이터(학원 2026-08-27)** | 카메라 1대·대상 1명·주간·54분 세션, `track_debug` 34.0분·3,843프레임, 장면별 929프레임 dets. **원본 영상 미보존(오버레이만)** → 정답지 제작 불가 | 추적 생존율·id 교체·경보 전송 지연·억제비·장면 대본 대비 검출률 | **재현율·정밀도(GT 없음)**, 재학습 데이터 | `reports/…v1.2.md:297-311` · `docs/labeling_plan.md:27-38` · `benchmarks/field_academy_2026-08-27.md:23,127` |
| **재방문 현장 정답지** | **미확보**(재방문 날짜 미정, CVAT 준비됨) | — | — | `NEXT.md:23-24` |
| 학습 데이터 | CSS v27(CC BY 4.0, 원본 514장) · D-Fire · LOCO(CC0)+Roboflow forklift 3종(CC BY 4.0/CC0) | — | 현장 원본 0장 | `attribution/SOURCES.md` |

### 4-2. 기준선 수치의 이력

| 수치 | 무엇 | 조건 | 상태 |
|---|---|---|---|
| **68.2% / 77.3%** | person 재현율 dev/test | 2026-08-10, **IoU 트래커 시절** | 2026-08-13 ByteTrack 도입 후 12일간 재측정 없이 인용됨 → 규칙 9 사고. 정정됨 (`v1_field_baseline_report.md:88-90`, `CLAUDE.md` 규칙 9) |
| **38.2% / 42.0%** | person 재현율 dev(ByteTrack 기본 / `min_frames 0`) — 파이프라인(추적 후) 재현율 | 2026-08-25, 1fps 정지프레임 | **2026-09-22 폐기**(대표 결정) — 1fps 정지프레임 평가는 추적기 이후 지표를 대표하지 않는다(현장 1.88fps 실측 손실 11.7%/고신뢰 3.9%). **검출 71.3% 는 유지.** 현장 파이프라인 재현율은 **재방문 정답지로 재측정 예정.** 원문 수치는 기록으로 보존하고 `FINAL-REPORT.md` §2-1 머리말·P0-3 행에 같은 단서를 달았다(README 에는 42% 인용 없음). 2fps 정답지 검수는 중단 | `b_passthru_results.md:3-8` · `FINAL-REPORT.md:41-43,85` · `docs/refield_plan_addendum_20260922.md` |
| **71.3%** | person 검출 직전 재현율(추적 전) | 2026-08-25 dev 74, 1fps | [실측]. "병목은 모델이 아니라 추적"의 근거 | `v1_field_baseline_report.md:72` |
| **75.62%** | PPE test 82 mAP@50(Colab) | 누출 분할, 체크포인트 미확인 | 원문 유지 + 단서 8곳 | `benchmarks/EVAL.md:92` 외 |
| **76.8%** | PPE held-out 91 mAP@50 | 2026-09-25, 영상 단위 제외 | [실측]. 재학습 비교표 "전" 행 | `provenance.md` §7-2 |
| **3.9%** | 현장 2fps 추적 고신뢰 손실 | 2026-08-27 수집, 2026-09-22 분류, conf≥0.5, GT 없음 | [실측]. 안전 논거에 쓰는 손실률 | `b_passthru_results.md:7` |
| 92.94 / 93.92 | person 파이프라인/raw mAP@50 | 공개 이미지 74장/87, 2026-07 | [실측] in-domain | `EVAL.md:69-70` |
| 71.46 | PPE 파이프라인 mAP@50 | CSS test 82(누출 분할) | [실측] 단 누출 분할 | `EVAL.md:93` |
| 95.91 / 87.88 | fire/smoke presence recall | D-Fire test 395 | [실측] in-domain | `EVAL.md:135` |
| 8.83% | forklift RF-DETR mAP@50 | LOCO, epoch 1 NaN 발산 | [실측] → 불용, 기본 슬롯 제외 | `vision.yaml:18` · `forklift_duel_2026-08-19.md:6` |
| 99.1% / 21.4% | 지게차 재현율(boda_ax YOLO) | 320프레임 conf 0.50 / LOCO 교차 | [실측]. 카운터밸런스 한정 꼬리표 | `proposal_base_2026-08.md:145-149` |

### 4-3. 평가 하네스와 게이트

| 항목 | 실체 | 근거 |
|---|---|---|
| PPE 비교 하네스 | `scripts/eval/eval_v1_heldout.py --weights <가중치>`: 같은 91장 평가 + "전(v1)" 행 고정 + 목표 판정(달성/미달/미측정/구간 걸침) + 세 집합 표(held-out / dev 74 앱 파이프라인 `--dev74` / 현장 정답지 **"미확보"**). v1 자기 재현 전 == 후 Δ0 [실측]. 재현 테스트 1건(자산 있는 개발기만; 전체 스위트 안에서 NO-Mask FP 35↔36 흔들려 ±1 허용) | `scripts/eval/eval_v1_heldout.py` · `tests/test_ppe_compare_harness.py` |
| dev 74 채점기 | `benchmarks/x4b_score_candidates.score_one(weights)` — 앱 파이프라인(`detect_isolated`) 경유, field_eval 자료(저장소 밖) 필요 | `benchmarks/x4b_score_candidates.py:102-185` |
| 누출 검사 | `scripts/eval/heldout_leak_check.py` — 파일명 묶음 + 인접 번호 쌍 NCC | 동 파일 |
| 게이트(로컬=CI) | ruff(vigent-core·tests 0) · mypy(화이트리스트 0) · **unittest 774건**(2026-09-25 실측; CI 는 자산 없는 1건 skip) · **OpenAPI 110 경로·WS `/tapo/ws` 무변경** · **프로파일 드리프트**(`check_profile_drift.py`: 누락·미선언 변경·미선언 추가·읽히지 않는 키 4종) | `scripts/gate.ps1` · `.github/workflows/ci.yml:39-52` · `scripts/check_profile_drift.py:9-18` |
| 게이트 결함 이력 | `gate.ps1` 변경 파일이 1개일 때 문자열이 글자 단위로 스플랫돼 `ruff --fix` 가 저장소 전체(45개 파일)를 고쳤다(2026-09-25, 원복·수정) | `scripts/gate.ps1:31-41` |
| 기준선 재측정 강제 | **없음** — 규칙 9 는 문서뿐, CI 가 구성 변경 시 재측정을 요구하지 않는다 | `docs/review/02-model-inference.md:238` |
| 회귀 세트(영상 기반) | **없음** | `FINAL-REPORT.md:141` |

---

## 5. 배포·운용 실체

| 항목 | 실체 | 꼬리표 | 근거 |
|---|---|---|---|
| 기기 역할 | 개발기 = Ryzen 9 9900X / RTX 5070 Ti 16GB / 64GB / Win11 Home(현장 안 감). 파일럿기 후보 = Ryzen 9700X / RTX 5060 8GB / 16GB(**미확보**). 현장 노트북 = i7-10750H / GTX 1650 Ti 4GB / Win10 Pro | — | `FINAL-REPORT.md:221-223` · `usb_installer_design.md:147` |
| 5070 Ti 4채널 2fps | 시스템 CPU 29.3~30.6% · 서버 5.35코어 · RSS 2.9GB · 검출 age p95 0.5s · 경보 p95 ≤0.25s · 추론 p50 27~37ms/p95 41.6~77.2ms(락 직렬 대기 포함) · torch allocated 597~604MB / reserved 862MB · nvidia-smi 총 2,469~2,913MB. 30분×3회 + 8GB 상한 모사 2회, OOM 0 | [실측] | `bench_4ch_repeat_2026-09-23.md:95-127` |
| GPU 점유 18.6% | 프레임당 person+ppe `predict` 11.6ms×2 ≈ 23.3ms × 8프레임/s = 186ms/s | [실측→계산] | `infer_breakdown_2026-09-23.md:51-53` |
| VRAM 3.2GB | torch reserved 862MB + 컨텍스트·cuDNN·드라이버 몫 ≈2.3GB(5070 Ti nvidia-smi 차분) | **[추정]** — 카드·드라이버별로 다름 | `bench_4ch_repeat_2026-09-23.md:121-127` |
| RTX 5060 | **실측 0건.** sm_120 이라 cu126 휠로는 못 돌고 cu130 필요(드라이버 ≥580). 5070 Ti 대비 배수는 "추정하지 않는다" | [미검증] | `usb_installer_design.md:45-61,317` · `infer_breakdown_2026-09-23.md:54` |
| 노트북 | 램프 1회(2026-08-22): N=3 220ms → **N=4 675ms** → N=6 972ms(한계), CPU 94.9%, VRAM 1.47GB. 4h 소크·실카메라 4대·경보 지연 10항목 **미측정**. 파일 카메라 2대 3h 소크 PASS | [실측 1회] / [미측정] | `FINAL-REPORT.md:225-235` |
| USB 설치기 1차 | 빌드·설치(멱등·업데이트·DryRun)·마법사·인수시험(A1~A8+H1·H2)·문서 구현. **개발기 `C:\VIGENT` 임시 실설치 3회**(제거 완료)로 결함 9건 잡아 수정. **NSSM 서비스 등록은 비관리자 셸이라 실기 미검증**(A1 미통과 상태). 마법사 실카메라·실토큰 미검증 | 구현됨·부분 실행 | `usb_installer_design.md:329-347` · `NEXT.md:12,26,35` |
| 오프라인 기동 | `HTTPS_PROXY=127.0.0.1:9` 차단 상태에서 빌드·휠 교체(0.9분)·GPU 추론·`/health` 200·다운로드 0줄 | [실측 2026-09-23] | `usb_installer_design.md:32,81,88,321` |
| 영상 불유출 | `VIGENT_CLOUD_VLM` 미설정이 기본, 코드 이중 게이트, off 상태 외부 요청 0건 실증(2026-07-13). USB 설치기는 설정하지 않음 | [실측] | `llm_provider.py:115` · `FINDINGS.md:279` · `usb_installer_design.md:226` |
| GPU 폴백 차단 | 런처 기본 `--gpu`, `VIGENT_EXPECT_GPU=1` 에서 device≠cuda 면 CRITICAL + `/health.gpu.fallback` + 허브 붉은 배너 — 실설치에서 `--cpu` 강제로 fallback true 실측 | [실측] | `usb_installer_design.md:342` |
| 현장 실적 | **2026-08-27 학원 1회**: 카메라 1대·대상 1명·주간·54분. 지게차(YOLO boda_ax) 장면 대본 대비 908/929(97.7%) · 안전모 판정 일치 지상 98.4% / **캐빈 67.9%** · 판정 270→폰 19건 · 운전자 오인 26/344(7.6%, 최장 2.1초) · **원본 영상 미보존 사고**(929프레임 찍고 주석 없는 원본 0장 → 정답지 불가 → 녹화기 `scripts/field_recorder.py` 로 수정) | [실측] | `field_academy_2026-08-27.md:23-75,127` · `reports/…v1.2.md:31,143,152` · `labeling_plan.md:7-11,27-38` · `CLAUDE.md` 규칙 11 |
| 유료 고객·파일럿 계약 | 0곳 · 0건 | — | `docs/onboarding/01_이게_무엇인가.md:30` |

---

## 6. 기존 자료 수치 대조표

대상: `README.md` · `md/VIGENT_사업추진계획서_초안.md` · `docs/사업계획서_VIGENT_초안.md` · `docs/PILOT_PROPOSAL.md` · `docs/proposal_base_2026-08.md` · `docs/COMMERCIALIZATION_READINESS.md` · `docs/team/10_비전트랙_기획안.md` · `docs/review/FINAL-REPORT.md` · 설정 주석(`vision.yaml`)·`CLAUDE.md`. (`docs/team/pdf/*.html`·`.docx` 는 위 md 의 변환본이라 별도로 열지 않았다 — **미확인**. `.docx` 는 이번 정정이 반영되지 않았으므로 재생성 전 배포 금지.)

**외부 노출 문서 목록(정정 우선)**: `README.md`(GitHub 첫 화면) · `md/VIGENT_사업추진계획서_초안.md`(IR·사업계획) · `docs/사업계획서_VIGENT_초안.md` + `docs/사업계획서_VIGENT_초안.docx`(제출본) · `docs/PILOT_PROPOSAL.md`(고객 제안) · `docs/proposal_base_2026-08.md`(제안 기초) · `docs/team/pdf/*.pdf,*.html`(팀 배포본). 내부 문서: `docs/COMMERCIALIZATION_READINESS.md` · `docs/team/*.md` · `docs/review/*` · `CLAUDE.md` · 설정 주석.

**정정 상태(2026-09-26 적용)**: 1순위 8건(#1·#3·#5·#6·#10·#12 원문 유지+단서, **#21·#26 삭제**) · 2순위 13건(#4·#15·#16·#19·#20·#22·#23·#24·#25·#27·#28·#29·#30 코드에 맞춰 문서 수정) · #2 는 §7-2 "구현됨·미연결"로 이동. 표의 "판정" 열은 정정 **전** 상태를 기록으로 남긴다.

| # | 주장 | 출처 문서 | 코드·측정에서 확인되는가 | 차이 / 판정 |
|---|---|---|---|---|
| 1 | person mAP@50 **92.94%**, PPE **71.46%**, 화재 presence recall **95.91%**, 연기 87.88%(FAR 15.4%) — "핵심 인식 성능 실측 완료" | `md/VIGENT_사업추진계획서_초안.md:17,88-91` | 측정 파일 있음(`EVAL.md:34-35,70,93,135`, 2026-07) | **정정 필요(단서)**: 전부 공개셋 in-domain·현장 CCTV 아님. PPE 71.46 은 **누출 분할 test 82** 값 → "PPE 71.46%(누출 분할; 영상 단위 held-out 91장 76.8%, 2026-09-25)" 로 병기. 제안 문구: "공개 데이터셋 기준·현장 미검증" 을 각 수치에 |
| 2 | "RIG 상태기계 로직 검증 완료(테스트 5/5)" | 〃 `:17` | `rig_monitor.py`·`rig_replay.py` 는 어느 라우트·워커도 부르지 않는다 → **구현됨·미연결** | §7-2 로 이동. 문서에는 "운용 경로 미연결" 단서 부착(적용) |
| 3 | 실내 배경 45장 안전모/조끼 오탐 **0%**, 연기 오탐 62.5→7.5% | 〃 `:101-102` | **출처 확인됨**: `benchmarks/FINDINGS.md:254-262` 웹캠 45장 신구 대결(구 YOLO smoke 62.5% → RF-DETR 7.5%; 같은 표에 person 12.5%·forklift 30% 오탐도 있음) | **정정 필요(단서)**: 개발기 실내 웹캠 1회·현장 오탐률 미측정·같은 표의 불리한 값 병기(적용) |
| 4 | "테스트 481건 자동검증 체계" | `docs/사업계획서_VIGENT_초안.md:45` | 현재 **774건**(2026-09-25) | **정정 필요**(수치 낡음, 축소 방향이라 과장은 아님) |
| 5 | "현장 시험 1회 완료(54분·929프레임) — 지게차 검출 97.7%, 경보 전송 19/19" | 〃 `:45,90,138,142` | 908/929 [실측]. 단 **정답 = 장면 대본(프레임 라벨 아님)**, 지게차는 **AGPL YOLO boda_ax**(safety 프로파일 기본 모델 아님) | **정정 필요(단서)**: "장면 대본 대비, 카운터밸런스 지게차 한정, 학원 프로파일 YOLO" 병기. ★2026-09-26 적용 완료 — 인용처 전부에 단서 병기. 자체 RF-DETR `forklift_rfdetr_v1` 은 같은 학원 영상에서 현장 박스와 IoU≥0.5 일치 0.5%(@0.1) [실측, `ppe_rfdetr_v1_provenance.md` §9] |
| 6 | 안전모 판정 일치(지상 근거리) 98.4% | 〃 `:143` | [실측]. 같은 표에 **캐빈 67.9%** 가 있다 | **정정 필요(누락)**: 캐빈 67.9% 병기 — 좋은 쪽만 뽑았다는 지적을 피한다 |
| 7 | 사람 인식률(추적 후) 38~42% — 최우선 개선 대상 | 〃 `:150,277` | [실측] | 유지. 단서 추가 권고: "1fps 정지프레임 기준, 현장 2fps 고신뢰 손실 3.9%" |
| 8 | 오경보 억제 89.1%(221→24) · 요약비 14.2:1 | 〃 `:115` · `proposal_base:49` | [실측] 재생·현장 | 확인됨 |
| 9 | 타일링으로 소형 작업자 검출 0%→89~95% | `PILOT_PROPOSAL.md:12,58` | 실영상 실측 있음, **기본 off·현장 오탐 미실측·CPU +415ms/프레임** | 확인됨(문서가 이미 단서를 달았다). 유지 |
| 10 | 안전모 미착용 놓침 ≈44%(NO-Hardhat R56.1) | `PILOT_PROPOSAL.md:39,64` · `COMMERCIALIZATION_READINESS.md:24,54` · `docs/team/10_비전트랙_기획안.md:65` | 56.1 은 구 공개셋 측정. 현재: held-out 91 **R 64.1 [51.8, 74.7]**(2026-09-25), dev 74 구간 [25.9, 100] n=14 | **정정 필요(갱신)**: 측정일·집합을 붙여 "held-out 64.1 [51.8, 74.7] / 사고영상 dev [25.9, 100]" 로 |
| 11 | 지게차 99.1%(카운터밸런스 한정, LOCO 21.4%) | `proposal_base_2026-08.md:145-149,579-582` | [실측] | 확인됨(꼬리표 있음) |
| 12 | 권장 5대·한계 7대, VRAM 1,397MiB, GPU util 최대 42% | `proposal_base:170-173` | [실측] **개발기 값**(2026-08-18) | **정정 필요(단서)**: "개발기(RTX 5070 Ti) 기준, 배포기 아님" 병기. 노트북은 한계 6·권장 4 |
| 13 | 카메라당 CPU −26%(2.10→1.55코어) | `proposal_base:182` | [실측] | 확인됨 |
| 14 | 야간 무인 오탐 86.4%(원인 규명) | `proposal_base:318,354,631` | [실측] | 확인됨 |
| 15 | "662 tests OK 가 정상" | `README.md:51` | 774 | **정정 필요** |
| 16 | OpenAPI "106 == baseline" | `CLAUDE.md` 코드 품질 게이트 4 | 체커 출력 **110 / 110** | **정정 필요**(내부 문서) |
| 17 | person "mAP@50 raw 93.9%·33.8ms" | `vision.yaml:14` | `EVAL.md:69` 93.92%·33.8ms(공개 이미지 74장) | 확인됨. 측정 조건을 주석에 병기 권고 |
| 18 | fire_smoke D-Fire test 395 mAP@50 80.13% | `vision.yaml:19` | `EVAL.md:132-139` | 확인됨(in-domain) |
| 19 | "ByteTrack 미구현·미사용", 포즈 = "yolov8n-pose 직접 로드", "rtmpose 미설치·미사용" | `vision.yaml:66-75`(2026-09-26 현재도 그대로) | 실제: ByteTrack 운영 중(`tuning.yaml:193`, `guard.py:744`), 포즈 = RTMPose(`worker.py:386`) | **정정 필요**(주석이 실제와 **반대**) |
| 20 | `ppe_missing` severity **medium** | `vision.yaml:85` | 워커는 **high** 로 발화(`worker.py:322`), 현장 통보 실적도 high | **정정 필요**: 선언과 코드 일치시키기 |
| 21 | "KOSHA 스마트 안전장치 인증 기준 90%" | `evaluator.py:8,172` | 제도·기준 존재 확인 못 함 | **정정 필요**(근거 없는 인증 문구 삭제) |
| 22 | "죽으면 5초 뒤 자동 재시작" | `deploy/windows/README.md:15` · `install_service.ps1:11`(docstring) | `install_service.ps1:149` `AppRestartDelay 60000` = 60s | **정정 필요** |
| 23 | 재연결 상한 30s · "기본 sync" | `docs/STABILITY.md` §4·:75,100 | 코드 5s(`tuning.yaml:216`), 서비스 thread | **정정 필요** |
| 24 | "얼굴 비식별화·보관기간 파기 미구현" | `docs/PRIVACY_POLICY_DRAFT.md` §3·§6·§9 | 구현됨(`privacy.py`, `retention_scheduler.py`) | **정정 필요**(실제보다 나쁘게 서술) |
| 25 | 관제 라벨·통보 문구 "쓰러짐·실신 의심" | `dashboard.py:24` · `worker.py:627` · `agents/scribe.py:66` | 낙상 감지 없음 — 45초 무동작 감지 | **정정 필요**: "장시간 무동작(45초)" 로 |
| 26 | "HTTP 또는 Modbus TCP" | `relay.py:7` · `deploy/SITE_CHECKLIST.md:171` | Modbus 구현·라이브러리 0 | **정정 필요** |
| 27 | `coach.py` 순수 스텁 · Copilot 등 | `md/AGENT_STATUS.md:14`(2026-07-12) | `agents/` 에 `coach.py` **없음** | **정정 필요**(문서 낡음) |
| 28 | B-finetune "목표치 미선언" | `docs/review/NEXT.md:45` | 2026-09-25 선언됨(`provenance.md` §8) | **정정 필요**(내부 문서 갱신) |
| 29 | Docker 빌드 안내 "docker build … 자동 정리" | `deploy/DEPLOYMENT.md:28` | `Dockerfile:24,38` 빌드 불가(`FINAL-REPORT.md:196`) | **정정 필요** |
| 30 | `routers/recognition.py:7` docstring "CSV" | 동 파일 | 구현은 JSONL | **정정 필요** |
| — | **L2 관련 추가(2026-09-26 §3 재작성 후 grep)** — 외부·팀 md 에서 `LangGraph`·`Qwen3-8B`·`NVFP4`·`에어갭`·`로컬 LLM` 문구는 **0건**, 아래는 "6개 에이전트"·"온프렘 LLM"·"문서 자동화/자동 연동" 문구. 전부 **원문 유지 + 단서**("L2는 설계·부분 구현 단계. 그래프 코드는 존재하나 미실행(WIP 커밋 보존), 모델 실행 기록 0, L1 브리지 미구현(2026-09-26 확인). NVFP4 양자화본은 저장소·D:\models에 없음") | | | |
| 31 | "3층 구조 — ② L2 문서 자동화(감지 결과 → 법령 근거 위험성평가서)" | `md/VIGENT_사업추진계획서_초안.md:16` (IR) | L2 미연결, L1 내장 빈도 재사용만 | 단서 부착(적용) |
| 32 | "L2. 문서 자동화 계층 — 감지 결과를 … 자동 초안화한다" | 〃 `:64-65` | 동상 | 단서 부착(적용) |
| 33 | "AI 에이전트가 그 결과로 법령 근거 위험성평가서를 자동 초안화" | `README.md:3` (GitHub 첫 화면) | 동상 | 단서 부착(적용) |
| 34 | "안전서류 자동화(확장 옵션) … 파일럿에서 시연 가능" | `docs/PILOT_PROPOSAL.md:52` (고객 제안) | 시연 가능한 것은 L1 내장 초안뿐 | 단서 부착(적용) |
| 35 | "안전 서류를 AI가 자동 작성 … 비전 감지와 자동 연동합니다" | `docs/team/00_시작하기_전에.md:11,24` (팀 온보딩·pdf 원본) | 자동 연동 미구현 | 단서 부착(적용) |
| 36 | "AI가 안전 서류를 자동 작성 — 감지 이벤트로부터 초안 생성" | `docs/team/20_에이전트트랙_기획안.md:5` | 동상 | 단서 부착(적용) |
| 37 | S5 "온프렘 LLM으로 동일 품질 재현" · A-07 "온프렘 LLM 대안 조사" | `docs/team/20_에이전트트랙_기획안.md:20,101-106` | 후보 조사는 `vigent-l2/configs/models.yaml`(2026-08-05, 라이선스 확인)에 이미 있으나 미실행 | 단서 부착(적용) |
| 38 | "6개 에이전트(Guard/Analyst/Scribe/Coach/Copilot/Dispatcher)" | `md/VIGENT_단계별_지시문.md:60` | Coach 파일 없음(7파일 구성), LangGraph 6노드는 별도 저장소 | 단서 부착(적용) |
| 39 | "6개 에이전트 각각의 파일 경로 + 구현 상태" · S5 "온프렘 LLM" | `docs/team_plan_prompt.md:52,150` | 동상 | 단서 부착(적용) |
| 40 | "에이전트 6개 중 4개는 실동작, Coach는 스텁(12줄)" | `docs/team/01_현황_숫자로_보기.md:65` | 2026-07-27 기준, coach.py 제거됨 | 단서 부착(적용) |
| 41 | `.docx`·`pdf` 변환본(`docs/사업계획서_VIGENT_초안.docx`, `docs/team/pdf/*`) | — | 위 정정·단서 미반영 | **재생성 전 배포 금지**(유지) |
| 42 | "배포 코드에서 ultralytics(AGPL) 제거 완료 — Apache 스택" · 지게차 97.7% | `themes/safety/vision.yaml:15` · §8 Q1 · 현장 보고서 | (2026-09-26 낮) 학원 배포가 AGPL YOLO `forklift_boda_ax` 에 의존했고 Apache 대체 `forklift_rfdetr_v1` 은 어디서도 국소화 0%. → **해소됨 [실측 2026-09-26 밤]**: AI Hub 510 스모크 파인튜닝(`forklift_rfdetr_fk510_smoke.pth`, SHA b409c98d…)이 510 held-out AP50 94.3 [93.6, 95.0], 학원 929프레임 대본 기준 **95.7 %**(boda_ax 97.7, −2.0 %p ≤ 기준 −3), 4ch 벤치 age p95 0.5 s·경보 p95 0.14 s 를 만족해 `vision.academy.yaml` `backend.forklift: rfdetr` 로 교체, boda_ax 항목 제거. 단서: 주행 장면 04/05 86~87 %(§7-2 개선 항목) · 벤치는 2026-09-27 30분×3회로 재측정해 합격선 3회 통과(`docs/deploy/bench_4ch_fk2_academy_2026-09-27.md`, 추론 p95 92~158 ms·VRAM 3.4 GB) · 학원 노트북(GTX 1650 Ti 4 GB) 미측정 | **정정 완료**: 이제 "Apache 스택" 은 학원 프로파일에도 참이다(설정 기준). 97.7 % 인용처 단서는 유지(그 값은 YOLO 의 값) |

**정정 필요 집계: 30건 중 22건**(#1·2·3·4·5·6·10·12·15·16·19·20·21·22·23·24·25·26·27·28·29·30). 확인됨 8건(#7·8·9·11·13·14·17·18 — 이 중 #7·12 류는 단서 병기 권고). **L2 관련 추가 11건(#31~#41, 2026-09-26 §3 재작성 후)** — 10건 단서 부착 적용, #41 은 변환본 배포 금지 유지. **#42(2026-09-26 forklift 출처 감사 후 추가)**: "Apache 스택" 주장에 "지게차 슬롯은 학원 배포 AGPL 의존" 단서.

---

## 7. 부족한 것·추가할 것

### 7-1. 명백한 공백

| 공백 | 상태 | 근거 |
|---|---|---|
| 현장 정답지 부재 | 재방문 날짜 미정. CVAT 로컬 설치·변환기 준비됨(Docker 는 확인 당시 꺼져 있었음) | `NEXT.md:23-24` |
| RTX 5060 미실측 | 실기 미확보 | `NEXT.md:27-28` |
| 재학습 — forklift 스모크 1회 진행 중 | 목표 선언(PPE §8 · forklift §9-7) → VS_07·VS_03_공통 수신 → 학습 의존성 설치(numpy·cv2 불변, `rfdetr[train]` 전체 대신 필수 조합) → **1차 실행 정체 사고 [실측 2026-09-26]**: 18:29 이후 2시간 `metrics.csv` 무갱신, GPU 8~23 %, 메인 프로세스 1.2코어. py-spy 3회 모두 `torchmetrics MeanAveragePrecision.compute → _get_coco_format`(검증 3,561장 × 최대 500 검출을 순수 파이썬으로 COCO 변환)에서 정지. 원인 = **검증 후처리 비용**(데이터로더·디스크·OOM 아님). 조치: 학습 중 검증셋 층화 표본 800장(장소×지게차 유무, 777 지게차 있음)·검증 2 epoch 마다·`eval_max_dets` 500→100·`num_workers 0`·진행바 off·**정체 감시 스레드**(15분 무갱신 → `STALL_ABORT.json` + py-spy 스택 + exit 9)·epoch 소요/남은 예상을 metrics.csv 와 로그에 기록. 증거: `benchmarks/results/forklift_fk_510_smoke_20260926/stall_pyspy_1st_run.txt`. **2차 실행 완료 [실측 21:29]**: 10 epoch 0.78h, 정체·NaN 0 → 510 held-out 3,561장 AP50 **94.3 [93.6, 95.0]** · R 88.1 · P 97.7 · 음성 오탐 0/101(구간 상한 3.7) · 학원 956 IoU 일치 96.4 %(v1 0.0) → 학원 프로파일 교체(§6 #42). **PPE 스모크 A(2026-09-27, 준라벨 681장 미검수)**: held-out 91 NO-Hardhat R 65.6 [53.4, 76.1](전 64.1) · 4클래스 AP50 80.5(전 81.3) · dev74 PPE R 49.4(전 64.8) — **목표 미달·변화는 구간 안, 배포 없음.** **스모크 B**(507 조끼 준라벨 병합, 미검수): NO-Hardhat R 62.5 [50.3, 73.3] · dev74(Mask 제외) 51.5(v1 62.3) — A/B 구간 안, 라벨 누락 채움 무효. A·B 공통: 507 이어 학습 시 dev74 미착용 재현율 ≈10 %p 하락. **대조군 D**(CSS 만, v1 이어 학습): held-out NO-Hardhat R 64.1 = v1 · dev74 54.5(−7.8 %p) → **정지 규칙 발동, PPE 재학습 중단·v1 유지**. "507 은 현장 안전모 미착용 개선에 기여하지 않음 [실측 3회]". 레시피 결함(v1 슬롯 의미 충돌: person·Hardhat·Safety-Vest 가 v1 의 Hardhat·Mask·NO-Mask 슬롯 위에서 학습) 확정, dev74 하락은 507 무관·레시피 기인. 개선은 재방문 현장 GT 후 | `docs/model/ppe_finetune_smoke_A_20260927.md` · `ppe_finetune_smoke_B_20260927.md` | `docs/model/forklift_finetune_smoke_20260926.md` · `provenance.md` §9-7 · `scripts/train/finetune_rfdetr.py` · `tests/test_finetune_guards.py` |
| ~~지게차 검출이 AGPL 에 묶여 있음~~ → **해소됨 [실측 2026-09-26]** | 학원 프로파일 `backend.forklift` 를 yolo(boda_ax, AGPL) → rfdetr(`forklift_rfdetr_fk510_smoke.pth`) 로 교체. 근거: 510 held-out AP50 94.3 · 학원 929프레임 대본 기준 95.7 %(−2.0 %p) · 4ch 벤치 합격선 통과(age p95 0.5 s·경보 0.14 s·CPU 35 %). 남은 것: 주행 장면 04/05 86~87 %(§7-2), 30분×3회 벤치 재실행, 학원 노트북 4 GB 실측, USB 재빌드 | `deploy/academy/vision.academy.yaml` · `docs/model/forklift_finetune_smoke_20260926.md` §3-1 · §6 #42 |
| 카메라 네트워크 표준 미정 | 방향만(자체 PoE 스위치+고정 IP+유선 ONVIF 1종). Tapo C200 은 Wi-Fi, IP 할당 방식 기록 없음 | `usb_installer_design.md:362-371` |
| 두 계보 미통합 | 노트북 `laptop/20260917` push → 비교·통합 → 실USB → 재설치 순. 노트북은 F-34 미반영 | `NEXT.md:25` |
| 감시 중단 원격 통보 | 코드 경로 0건(2026-09-26 grep) | §2-8 |
| 통보 채널 2중화 | 이메일 코드 완료·Gmail 앱 비밀번호 대기 | `NEXT.md:22` |

### 7-2. 알고리즘 관점 공백

| 질문 | 있음/없음/부분 | 근거 |
|---|---|---|
| 오탐 억제에 시계열 투표(N-of-M)가 있는가 | **없음** — 연속 N 프레임(PPE 3·화재 2) 또는 시간 유지(구역 1.0s·근접 0.4s)만. 한 프레임 끊기면 리셋 | `guard.py:290` · `zone_debounce.py` |
| 카메라별 마스크(제외 영역)·시간대 프로파일 | **없음**. 카메라별로 바꿀 수 있는 것은 구역·fps·무동작 임계 3개뿐(override 허용 키 1개), 나머지 임계는 전역·재시작 필요 | `camera_registry.py:66` · `01-architecture.md:109` |
| 자세 추정이 규칙에 쓰이는가 | **부분** — `ergonomic_risk`(기록 전용·통보 없음)에만. 안전 경보 판정에는 미사용 | `worker.py:489-495` |
| 다중 카메라 간 동일인 연결 | **없음** | grep 0 |
| 야간·역광 대응 | **없음**(코드 0·데이터 0). 야간 무인 오탐 86.4→100% 만 측정 | `02-model-inference.md:99-101` |
| 거리 캘리브레이션(호모그래피/BEV) | **없음** — 장비 박스 폭 기준자. 오차 실측 0 | `proximity.py:103-112` · `02-model-inference.md:132-143` |
| 오탐 피드백 → 재학습 루프 | **없음** — `/recognition/note` 빈 스텁, 학습이 운영 데이터를 읽는 코드 0 | `routers/recognition.py:58-60` · `02-model-inference.md:229-240` |
| L1 이벤트 → L2 문서 자동 반영 | **없음** — 별도 L2 저장소는 L1 과 미연결(브리지 0 바이트 / 영상 파일 폴링), L1 내장 Scribe 는 빈도만 재사용. `vigent-l2` Phase 4a 는 2026-09-26 WIP 커밋(`73d2252`)·번들 `D:\vigent_private_data\vigent-l2_wip_20260926.bundle` 로 보존(원격 없음) | §3-1·3-2·3-3 |
| VLM 에이전트(`vigent-vlm`) 기본값이 클라우드 | **영상 불유출 원칙과 상충** — 기본 엔드포인트가 OpenRouter, opt-in 게이트 없음. 기본값 변경(로컬 서버) 또는 `VIGENT_CLOUD_VLM=1` 명시 opt-in 으로 L1 게이트와 통일 필요(변경안은 §3-2, 코드 미수정) | §3-2 · `vigent-vlm/.env.example:14` |
| RIG(줄걸이) 상태기계 | **구현됨·미연결** — `rig_monitor.py`·`rig_replay.py` 는 테스트만 있고 어느 라우트·워커도 호출하지 않는다(외부 CSV 입력 전제). 사업계획서의 "로직 검증 완료(5/5)"는 단위 테스트 통과를 뜻하며 제품 기능이 아니다 | `docs/review/FINAL-REPORT.md:151,207` · §6 #2 |
| 카메라 tamper(가림·초점·과노출) | **없음** | `03-video-input.md:50-52` |
| 지게차 **주행 장면** 검출 저하 (2026-09-26 추가) | fk510_smoke 가 학원 대본 기준 정지·위험구역 장면 100 % 인데 **주행 장면 04 86.1 %·05 87.0 %**(boda_ax 99.3 / 92.5). 원인 미확인 [추정: 화면 가장자리 진입·모션 블러·부분 가림]. 개선 후보: 510 주행 프레임 보강·ByteTrack 유지 프레임 상향·해상도 실험 | `docs/model/forklift_finetune_smoke_20260926.md` §3-1 · `audit/forklift_yardstick_fk_510_smoke_20260926_2217.json` |
| 클래스별 검출률 시계열·`/metrics` | **없음**(슬롯 생존/고장만) | `02-model-inference.md:237` |

### 7-3. 우선순위 제안 (근거 포함, 4개)

1. **재방문 현장 정답지(2fps·고정 CCTV·주야)** — 모든 성능 수치가 공개셋 또는 1fps 재인코딩본 기준이며, 재학습 판정도 여기서만 하기로 돼 있다(`provenance.md` §8 "최종 판정"). 녹화 원본 보존 장치(`scripts/field_recorder.py`)는 준비됨.
2. **감시 중단 원격 통보 + 2번째 채널 활성** — 20일간 213건 미전달 사고가 실제로 있었고(§2-8), health 전이 통보는 아직 코드 0건. 공수 S(기존 큐 재사용).
3. **RTX 5060 실기 1대 확보 후 `bench_4ch.py --repeat 3`** — 사양 판정의 모든 수치가 5070 Ti 다(§5). 설치기·인수시험은 준비돼 있어 즉시 잴 수 있다.
4. **L2 계보 하나로 결정** — `vigent-l2`(설계 우수·미실행) 와 `vigent-vlm`(실행 실적·설계 원칙 위반) 중 하나를 골라 L1 이벤트 브리지(`L1Event` 계약은 이미 있음)를 잇는다. 그 전까지 대외 자료의 "3층 구조·문서 자동화" 는 "L1 내장 초안 생성(빈도 재사용)" 으로만 말한다. (§6 의 문서-코드 불일치 22건은 2026-09-26 에 적용 완료)

---

## 8. 멘토가 물을 법한 질문 10개와 답

1. **"왜 YOLO 안 쓰나?"** — 라이선스. ultralytics 는 AGPL 이라 배포 코드에서 제거했고(T10b, `vision.yaml:13-15`), RF-DETR 은 Apache-2.0 이다. 측정으로도 person raw mAP@50 YOLO 90.82 → RF-DETR 93.92(공개 이미지 74장)로 손해가 없었다(`EVAL.md:73`). 단 지게차는 RF-DETR 재학습이 실패(8.83%)해 학원 프로파일만 **AGPL YOLO boda_ax 를 예외로 쓴다** — 대표의 AGPL 결정 대기(`NEXT.md:49`). → §2-2, §4-2
2. **"42% 는 뭐였나?"** — 사고영상 dev 74장(1fps 정지프레임)에서 추적 후 person 재현율(2026-08-25). 검출 직전은 71.3% 라 손실은 모델이 아니라 추적기 정책이었다. 이후 현장 1.88fps 실측에서 손실이 11.7%(고신뢰 3.9%)로 훨씬 작아 "1fps 표본이 만든 착시"로 확인됐고, **2026-09-22 에 이 42% 는 폐기**했다(검출 71.3% 는 유지, 현장 파이프라인 재현율은 재방문 정답지로 재측정 예정). → §4-2
3. **"LLM 이 왜 필요한가? L2 는 어디 있나?"** — 실시간 경보에는 안 쓴다(§3-5). L1 안에서 쓰는 곳은 위험성평가서 '종합의견' 한 문단과 사고 사진 원인분석 서술뿐이고, 키가 없으면 규칙·지식베이스로 같은 문서를 만든다. 별도 L2 저장소는 둘: `vigent-l2`(LangGraph 6노드·제약 디코딩·법령 화이트리스트 설계 — 실모델 미실행·L1 미연결·2026-08-05 정지)와 `vigent-vlm`(사진→VLM→xlsx/pdf 실제 산출, 로컬 27B 4bit 45분/장 실측 — 기본은 클라우드 API, L1 미연결). "필요"라기보다 "감지 → 서류 자동 갱신" 이라는 약속을 아직 어느 계보도 채우지 못한 상태다. → §3
4. **"경보 3주 누락은 어떻게 재발 방지했나?"** — 2026-08-21~09-10 텔레그램 401 로 213건 미전달. 조치: 기동 시 `getMe` 자가시험(배경, 10분 재시도, 확정 시 붉은 배너), 하루 1회 heartbeat(설정 시), `/health notify`, 데드레터 190건 보관 이동, 이메일 채널 코드. **아직 안 된 것**: heartbeat 는 기본 꺼짐, 이메일은 비밀번호 대기, health 전이 통보 0건. → §2-8
5. **"학습 데이터 권리는?"** — PPE: Roboflow CSS v27 CC BY 4.0(저작자 표시 `attribution/SOURCES.md:29-40`). forklift: LOCO CC0 + Roboflow 3종 CC BY 4.0/CC0. person: RF-DETR COCO 체크포인트(Apache-2.0). **D-Fire 라이선스는 저장소에 표기가 없다 — 미확인.** 현장 원본 학습 데이터는 0장. 얼굴 식별 이미지가 git 이력에 남아 있어 공개 전 이력 재작성이 필요하다(`CLAUDE.md` 규칙 10). → §4-1
6. **"5060 으로 4채널 되나?"** — 모른다. 5070 Ti 에서 4채널 2fps GPU 점유 18.6%·torch 604MB·CPU 30% 는 실측이고, 5060 은 sm_120 이라 cu130 빌드로만 돌 수 있다는 것까지 확인했다. 5060 실기가 없어 배수를 추정하지 않기로 했다. → §5
7. **"현장에서 사람을 몇 %나 잡나?"** — 현장 기준 재현율은 **측정된 적 없다**(정답지 없음). 있는 것은 사고영상 1fps dev 42%(원거리 8%)와 현장 추적 생존율 88.3%(GT 없음)뿐이고, 두 값은 서로 다른 것을 잰다. → §1-3, §4-1
8. **"보호구 미착용을 얼마나 놓치나?"** — 공개셋 held-out 91장에서 NO-Hardhat 재현율 64.1% [51.8, 74.7] @0.35(2026-09-25). 사고영상 dev 74장에서는 관측 구간 [25.9%, 100%](n=14). 재학습 1차 목표는 ≥85%. → §2-3
9. **"넘어지면 잡나?"** — 아니다. 낙상 감지는 2026-08-06 제거됐고, `immobility` 는 45초 동안 박스가 안 움직일 때만 발화한다. 넘어지는 순간·45초 안에 일어남·누운 뒤 추적 끊김은 못 잡고, 누워서 작업하는 것과 구분 못 한다. 대외 문구 "쓰러짐 의심" 은 정정 대상이다. → §2-6, §6 #25
10. **"오탐은 어떻게 막나, 그리고 얼마나 나오나?"** — 장치: 연속 프레임(PPE 3·화재 2), 시간 디바운스(구역 1.0s·근접 0.4s), 사람 단위 쿨다운 15s, 카메라·규칙 단위 적응형 백오프(300→3600s, 6건/h). 재생 검증 억제 89.1%, 현장 270→19건. **오탐률 자체는 현장 정답지가 없어 못 잰다.** 알려진 오탐원: 야간 정지 물체(무인 86.4%), 마스크 단독(학원 87/490), 운전자 오인(7.6%). N-of-M 투표·카메라별 마스크·시간대 규칙은 없다. → §2-7

---

*이 문서는 2026-09-26 에 작성됐다. 수치는 각 근거 파일의 측정일을 따르며, 운영 구성이 바뀌면 다시 재야 한다(`CLAUDE.md` 규칙 9).*
