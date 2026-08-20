# 맥 salvage 회수·검증·편입 (D1~D4, 2026-08-20)

> 맥 포맷 전 살려둔 자료를 구글 드라이브 경유로 데스크탑에 회수했다.
> 원자료 위치는 §4, 클라우드 뒷정리는 §5(사람 확인 대기).

## D1. 다운로드 — 방법 판정과 실적

**판정: 별도 도구 설치 불요.** 확인 결과 이 PC 에 Google Drive 데스크톱 앱·rclone 모두
없었으나, 사용자가 **브라우저로 폴더별 zip 을 D:\ 에 직접 내려받아** 두었다(파일 17.8만
개를 한 덩어리로 받지 않고 폴더 단위로 나눠 받은 형태라 zip 다운로드 배제 원칙과 충돌
없음). 따라서 **수동 수령분을 조립·검증하는 경로**를 택했다 — 도구 설치·재다운로드 없이
가장 빠르다. OneDrive 경유는 없었다(전부 D:\ 직행).

## D2. 무결성 검증 — SHA256 전수 대조

MANIFEST 2종(1차 5,700항목 / 2차 192,445항목·14.46GB)으로 전수 대조했다.

| 대상 | 항목 | 결과 |
|---|---|---|
| 1차 `vigent_salvage` | 5,700 | ✅ **5,700 일치** · 불일치 0 · 누락 0 |
| `AX안전_MVP`(.venv 제외) | 106,320 | ✅ **106,296 일치** · 불일치 0 · **누락 24** |
| `AX안전_MVP/data` (data-001/002) | 37,225 | ✅ 전수 일치(위 수치에 포함) |
| `forklift_merge` (-002 보유분) | 6,839 | ✅ 전수 일치 |
| `loco_dataset.zip` | 1 | ✅ SHA·크기 일치 |
| `BODA_상업용`·`AX_상용화_핵심`·`archive_deleted_features`·`VIGENT_transfer` | 37+21+3+3 | ✅ 전수 일치 |
| `runs_logs` | 16 | ✅ 전수 일치 |

**★불일치(손상) 0건.** 잘린 파일 없음.

### 미수령분 (재다운로드 대상)

| 대상 | 부족 | 비고 |
|---|---|---|
| `forklift_merge` **-001 파트** | **27,962개 · 4.5GB** | 재학습 재료. -002 만 수령됨 |
| `AX안전_MVP/label_studio_pose_pipeline` | **24개** | 포즈 라벨링 파이프라인(소량) |
| `AX안전_MVP/.venv` | 51,243개·2.7GB | **의도적 제외**(사용자 결정 — pip 재생성 가능) |

## D3. 편입

### 3-1. ★LOCO 교차 검증 — G1 판정의 꼬리표는 "해소"가 아니라 **정당성이 확인**됐다

회수한 `loco_dataset.zip`(원본 5,593장) + `loco-all-v1.json` 으로
`benchmarks/build_forklift_eval.py` 를 재실행해 평가셋을 재구성했다 —
**커밋된 매니페스트와 완전 재현**(test 238img/316inst, ratio 0.55, **파일 목록 238장 전부 일치**).

판정 축은 G1 과 같되, LOCO 는 정지 이미지 + GT 박스라 **이미지 단위 재현율**(GT 하나라도
IoU≥0.5 매칭)과 **네거티브 80장 오탐률**로 본다. C2(최장 연속 미검출)는 영상 전용이라 미적용.

| 모델 | 최적 운용점 | 이미지 재현율 | 인스턴스 재현율 | 네거티브 오탐 | C1(≥80%) |
|---|---|---|---|---|---|
| **boda_ax(YOLO)** | 0.15 | **21.4%** | 16.8% | **58.8%** | ❌ |
| boda_ax | 0.50(학원 운용점) | **13.0%** | 9.8% | 38.8% | ❌ |
| COCO 대용 | 0.15 | **27.7%** | 26.3% | 36.2% | ❌ |

> ### ★둘 다 LOCO 에서 처참하다. 그러나 이것은 G1 판정을 뒤집지 않는다.
>
> 미검출 프레임을 눈으로 확인한 결과 **LOCO 의 "forklift" 는 창고형 전동 리치트럭·
> 스태커·오더피커**다(`runs/forklift_duel/loco/miss_*.jpg`) — 서서 타는 좁은 실내 장비로,
> 학원·현장의 **카운터밸런스 지게차**(CLARK GTS30H 류: 좌식·전방 마스트·야외)와 **형태가
> 다른 장비**다. 촬영 화각도 바닥 근접 로봇 시점이다.
>
> **결론**: LOCO 는 boda_ax 의 적용 범위를 재는 시험이 됐고, 답은 **"카운터밸런스 지게차
> 전용, 창고형 전동장비에는 못 쓴다"** 이다. G1 의 "학원 유사 영상 기준" 꼬리표는
> 제거 대상이 아니라 **반드시 유지해야 할 정확한 표기**임이 확인됐다 — 도메인이 바뀌면
> 성능이 21%로 무너진다는 것을 실측으로 보였기 때문이다.
> 학원 프로파일 채택(conf 0.50)은 **유효하며 변경 없음**(학원=카운터밸런스 도메인).

### 3-2. ★F-7 실패 원인 진단 — **학습이 1 epoch 부터 발산했다**

회수한 `rfdetr_forklift/metrics.csv`(112행·49 epoch) 분석:

| 지표 | 값 |
|---|---|
| `train/loss_ce` NaN 최초 등장 | **epoch 1** (총 49 epoch 중) |
| 이후 `train/loss`·`loss_ce`·`loss_ce_0`·`loss_ce_enc` | **끝까지 NaN** |
| `train/loss_bbox`·`loss_giou` | 1.6e-17, −9.5e-18 — **사실상 0/음수(붕괴)** |
| `val/mAP_50` | 첫 기록 0.193 → **마지막(epoch 49) 0.0** |
| 동반 실행 `rfdetr_fk_bench` | 2 epoch 만에 동일 NaN, val mAP 0.0 |
| 대조군 `rfdetr_forklift_poc`(num_classes=2) | **NaN 없음** — loss 정상 수렴(3.80) |
| 대조군 `fire_e17` | **정상** — val mAP50 최고 **0.835 @epoch 17** |

**진단**: forklift 학습은 **1 epoch 에서 분류 손실(loss_ce)이 NaN 으로 발산**했고, 그 상태로
49 epoch 을 완주해 **NaN 가중치가 체크포인트로 저장**됐다. 배포된 `forklift_rfdetr_v1.pth`
가 정탐·오탐 conf 를 모두 0.002~0.005 로 뱉는 것(F-7)이 정확히 이 결과다 — 모델이 아무것도
학습하지 못한 채 균일 저confidence 를 출력한다.

**재학습 계획에 반영할 것**:
1. **NaN 감시를 학습 루프에 필수로** — epoch 1 에서 멈췄어야 했다. 49 epoch 완주가 더 큰
   문제(GPU 시간 낭비 + 못 쓰는 체크포인트가 배포까지 감).
2. `num_classes` 차이 주목 — 실패본 **1**, 정상 대조군(poc) **2**. RF-DETR 에서
   `num_classes=1` + 배경 클래스 처리 조합이 원인일 **가능성**(미확정 — 재현 실험 필요).
3. **학습률·AMP 점검**: 분류 손실만 NaN 이고 bbox/giou 는 0 으로 붕괴 — 전형적인
   발산 패턴. warmup·lr·grad clipping 설정을 `fire_e17`(정상)과 대조할 것.
   ⚠단 `training_config.json` 에 lr·batch 등이 기록돼 있지 않아(`num_classes` 만 있음)
   **정확한 하이퍼파라미터 비교는 불가**하다(규칙7).
4. 재료: `D:\vigent_assets\forklift_merge`(-001 수령 후 34,801개) + 학원 회수 영상.

### 3-3. Colab 학습 기록 연결

`benchmarks/train_logs/` 로 편입(10개 + `_runs_logs` 16개):

| 실행 | epoch | 결과 | 연결 대상 |
|---|---|---|---|
| `fire_e17` | 56행 | **val mAP50 0.835 @e17** ✅ | `fire_smoke_rfdetr_v1_e17.pth` — 문서의 D-Fire 80.13% 와 정합 |
| `rfdetr_forklift` | 112행/49e | **NaN 발산** ❌ | `forklift_rfdetr_v1.pth`(F-7) — §3-2 |
| `rfdetr_forklift_poc` | 28e | 정상 수렴(3.80) | POC — 배포본 아님 |
| `rfdetr_fk_bench` | 2e | NaN | 벤치 시도 |
| `rfdetr_forklift_v2B` | 1e | lr 기록만 | 중단된 실행 |
| **`rfdetr_ppe`** | 126행/23e | ⚠ **val mAP50 최고 8.0e-06(≈0)** | ★아래 주의 |

> ★**`rfdetr_ppe/metrics.csv` 는 배포된 ppe 모델의 로그가 아닌 것으로 보인다.**
> 배포본 `ppe_rfdetr_v1.pth` 는 현장 실측에서 conf 0.8+ 로 정상 동작하는데(tapo/현장 검증),
> 이 로그의 val mAP50 은 사실상 0 이다. 즉 **회수된 것은 실패한 다른 실행**일 가능성이
> 크다. MANIFEST 의 "ppe metrics.csv 미회수" 는 **"회수했으나 배포본과 무관해 보임"**
> 으로 정정한다 — 배포본의 학습 로그는 **여전히 없다**(규칙7).

### 3-4. evidence·recognition 회수분 — ⏸ **편입 보류(결정 대기)**

| 항목 | 규모 | 기간 |
|---|---|---|
| evidence | **4,270개** | 2026-06-19 ~ 08-13 |
| recognition | 41개 | — |
| risk_assessments | 433개 · tbm 5 · audit 2 · legal 3 | — |

★**보존정책상 즉시 파기 대상이다.** A그룹 보존 30일 기준으로 오늘(8/20) 기준 **7/21 이전
분은 전부 기한 초과**이고, 회수분 대부분이 여기 해당한다. `data/evidence/` 에 넣으면
retention 첫 주기에 대량 삭제 목록으로 올라간다(그리고 그게 정책상 옳다).

**그래서 넣지 않고 `D:\vigent_assets\vigent_salvage_data\` 에 보류했다** — 넣는 순간
파기 절차가 돌기 시작해 되돌릴 수 없기 때문이다. **사람 결정 필요**:
①정책대로 파기 ②재학습·회귀 자산으로 별도 보존(개인정보 처리 근거 재확인 필요)
③선별 보존(비식별화 후).

### 3-5. 자격증명 목록 (★값은 마스킹 — 폐기·교체는 사람 결정)

`vigent_salvage/repo_leftovers/vigent_secrets/` — **저장소에 넣지 않았다.**

| 파일 | 담긴 자격증명 |
|---|---|
| `.env` | **ROBOFLOW_API_KEY**, **OPENAI_API_KEY**(sk-…), RTSP_URL(계정·암호 포함), LLM 설정 |
| `camera_secrets.json` | 카메라 `test` RTSP 자격증명 |
| `cameras.json` | 카메라 정의 + source(RTSP 자격증명 포함) |
| `notify.yaml` | **telegram_token**, telegram_chat, **smtp_pass**, smtp_user/host, email_to, webhook_url |
| `site.yaml` | 사이트 정의 + 카메라 RTSP source |

> ### 🔴 유출 노출 판단에 필요한 사실
> 1차 MANIFEST 머리말에 **"vigent_secrets·evidence·recognition 은 클라우드 업로드 금지 —
> 외장드라이브로만"** 이라고 명시돼 있었으나, 이번 회수는 **구글 드라이브를 경유**했다.
> 즉 위 자격증명과 개인영상 4,270장이 **클라우드에 업로드된 상태**다(비공개 계정이라도
> 계정 침해·공유링크 사고 시 노출). D4 삭제가 **뒷정리가 아니라 유출 대응**이며,
> **키 폐기·교체 여부는 사장님 결정 사항**이다(권고: OPENAI·ROBOFLOW·telegram_token·
> smtp_pass 는 재발급, RTSP 카메라 암호는 변경).

## 4. 편입 위치 요약

| 위치 | 내용 | 규모 |
|---|---|---|
| **저장소** `benchmarks/train_logs/` | Colab metrics.csv 6종 + training_config + `_runs_logs`(평가 산출 16) | 0.2MB |
| **저장소** `benchmarks/data/forklift/` | LOCO 평가셋 재구성(318장 + 라벨 + data.yaml) | — |
| `D:\vigent_assets\loco\` | LOCO 원본 5,593장 + `loco-all-v1.json` | 0.9GB |
| `D:\vigent_assets\forklift_merge\` | 재학습 재료(-002분 6,839 — **-001 수령 후 34,801**) | 1.2GB |
| `D:\vigent_assets\AX안전_MVP\` | MVP 코드·데이터셋 106,346개 | 5.0GB |
| `D:\vigent_assets\vigent_salvage_datasets\` · `_weights\` · `_docs\` | 데이터셋·YOLO 가중치 6종·문서 | 0.24GB |
| `D:\vigent_assets\vigent_salvage_data\`(보류) | evidence 4,270 · recognition 41 · risk_assessments 433 등 | — |
| **저장소 밖·미편입** | `vigent_secrets`(자격증명 5파일) | ★저장소 반입 금지 유지 |

## 5. D4. 클라우드 뒷정리 — ⏸ **사람 실행 대기 (열린 항목)**

★**우선순위 1: `vigent_secrets`·`evidence`·`recognition`** (평문 자격증명·개인영상정보).

### 절차 (구글 드라이브 웹)

1. **drive.google.com** 접속 → 업로드했던 salvage 폴더들을 찾는다
   (`vigent_salvage`, `vigent_salvage_large` 및 그 하위 — 특히 `repo_leftovers/vigent_secrets`,
   `repo_leftovers/vigent_data/evidence`, `.../recognition`)
2. 폴더 우클릭 → **삭제**(휴지통으로 이동)
3. 좌측 메뉴 **휴지통** → 우측 상단 **"휴지통 비우기"** → 확인
   ★**이 단계까지 해야 실제 삭제**다. 휴지통에 있으면 아직 계정 안에 남아 있다.
4. **공유 상태 점검**: 삭제 전에 해당 폴더가 "링크가 있는 모든 사용자"로 공유된 적이
   있는지 확인(우클릭 → 공유). 공유됐었다면 링크 노출 가능성을 전제로 키 교체 권고.
5. 완료되면 알려주세요 — 이 항목을 닫고 문서를 갱신합니다.

**미수령분(forklift_merge -001 등)을 다 받은 뒤에 삭제**할 것 — 삭제하면 재다운로드가
불가능합니다.
