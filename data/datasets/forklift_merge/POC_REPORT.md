# forklift 재학습 PoC 리포트 (Phase 2 — 빠른 실증)

> 목적: full 학습(수십 시간)에 커밋하기 전에, **병합 데이터가 baseline(box mAP@50 8.5%)을 개선하는지**
> 3k 서브샘플·5에폭으로 실증. 결과 = **압도적 개선 확인**.
> 작성 근거: 실제 학습·평가 실행 로그(2026-07-09~10). 모든 수치는 측정값.

## 1. 결론 (측정값, 동일 하네스·동일 고정 test)

평가셋: `benchmarks/data/forklift`(LOCO test 238 pos + 네거 80) — **baseline 8.5% 측정과 동일 셋**.
두 모델을 `benchmarks/eval_rfdetr_custom.py`로 동일 조건 평가:

| 지표 | baseline v1 | **PoC (3k·5ep)** | 개선 |
|---|---|---|---|
| **box mAP@50** | 8.83% | **58.62%** | **+49.8%p (약 6.6배)** |
| box mAP@50:95 | 5.98% | 32.10% | +26.1%p (5.4배) |
| presence AP | 76.32% | 94.12% | +17.8%p |
| forklift recall(op) | ~0.0 * | **54.62%** | **천장 46.6% 돌파** |
| precision(op) | None * | 94.89% | — |
| FAR (80네거) | 0.0% * | 8.8% (FP 7) | * 아래 주석 |

**정직한 해석:**
- baseline 8.5%가 8.83%로 재확인됐고, 병합 데이터 학습으로 box mAP@50이 **6.6배** 상승.
- PoC recall 54.62%는 baseline recall **천장(46.6%)을 돌파** → MERGE_REPORT §8 성공 판정 충족.
- **baseline의 R=0.0·FAR=0.0%는 우수함이 아니라 무의미**: baseline은 op threshold에서 사실상 미검출(FP도 0). PoC는 실제 검출(recall 54.6%, precision 94.9%)하면서 FAR 8.8%로 억제 → 질적으로 우월.
- ⚠️ FAR 8.8%(FP 7/80네거)는 pallet_truck 하드네거 포함 전체 네거 기준. pallet 단독 FAR은 별도 측정 필요(다음 단계).

## 2. PoC 구성 (측정값)

| 항목 | 값 |
|---|---|
| 데이터 | `subsample3k` — merged/train 층화 서브샘플 |
| train | 2,985장 (forklift 1,632 · pallet_truck 715) — 원본 34%, 비율 유지 |
| 층화 기준 | 이미지를 forklift-only/pallet-only/both/네거 4군 분류 후 각 군 동일 비율(sha256 결정적) |
| valid/test | merged 원본 재사용(심링크) — **test 238 불변, leakage 0** |
| 옵션 | **B(2클래스: forklift, pallet_truck)** |
| 에폭 | 5 · batch 4 · grad_accum 4 · num_workers 0 · **device cpu** |
| 학습 시간 | **16.57h** (CPU + 야간 절전 반복 — §4) |

valid mAP_50:95 추이(상승 확인): epoch0 0.376 → 1 0.475 → 2 0.496 → 4 **0.515(regular) / 0.535(EMA)**.

## 3. ★ MPS 학습 불가 규명 (핵심 발견)

RF-DETR을 MPS(Apple GPU)로 학습 시 **반복 크래시**. 원인을 대조실험으로 규명:

| 실행 | device | num_workers | 결과 |
|---|---|---|---|
| 1차 | mps | 0 | epoch0 완주 → epoch 경계에서 크래시 |
| 2·3차 | mps | 6 | **첫 스텝** 크래시 (`ms_deform_attn`) |
| PoC-mps | mps | 0 | epoch0 완주 → **val matcher 크래시** |
| **PoC-cpu** | **cpu** | 0 | **5에폭 완주 ✅** |

- 표면 에러는 `TypeError: iou(): incompatible arguments`였으나, 최종 프레임은
  `matcher.py:259 → torch.AcceleratorError: index 2777923594867515807 is out of bounds` →
  **MPS 텐서 메모리 오염**(garbage index). 선행 경고 `Non-finite values in matcher cost matrix`와 동일 뿌리.
- **근본 원인 = MPS 백엔드의 deformable attention / matcher cost matrix 간헐 메모리 오염.**
  num_workers·resume은 크래시 **시점**만 바꿀 뿐, 원인이 아님. `PYTORCH_ENABLE_MPS_FALLBACK=1`으로도 회피 불가(pybind C++ 연산).
- **첫 실행 epoch0 통과는 우연**(오염이 특정 배치에서 누적).
- **해결 = CPU 또는 CUDA.** CPU는 이 버그가 없어 5에폭 완주.
- NaN(완전): 없음. Non-finite 경고는 초기 1스텝 sentinel 처리 후 안정화(무해).

## 4. 학습 시간 이슈 (정직 기록)

- CPU 학습 3k·5에폭 = **16.57h**. 첫 추정(46분/epoch)보다 훨씬 김.
  - epoch0 18분 → epoch1 ~7h 등 극단적 편차 = **야간 시스템 절전 반복**(caffeinate는 idle sleep만 방지, 덮개/전원 정책엔 무력)으로 추정. 순수 CPU 연산 속도(~3.7s/step)와 절전 정지가 섞임.
- **결론: CPU full 학습(9k·다에폭)은 비현실적.** full은 클라우드 CUDA가 사실상 필수.

## 5. 다음 단계 권고 (실행은 승인 후)

1. **full 학습 확대** — 개선 방향이 실증됐으므로 9k 전체 + 에폭 확대로 최종 모델 제작.
   - **클라우드 CUDA 권장**: MPS 메모리 버그 없음, 수십분~1h. 데이터 업로드(느린 와이파이 = 병목) 시간 별도 산정 필요.
   - 로컬 CPU 대안: 안정하나 9k면 수십 시간(절전 관리 필요).
2. **옵션 A(단일 forklift + pallet_truck 하드네거)** 병행 비교 — FAR 추가 억제 가능성.
3. **pallet_truck 단독 FAR** 측정(`--neg 40` pallet 네거만) — 오탐 원인 직접 확인.
4. **현장 평가셋** — 본 test는 LOCO in-domain. 현장 영상 확보 후 별도 현장 성능 측정(MERGE_REPORT §4 한계).

## 상태
**PoC 성공 — 병합 데이터의 개선 효과 실증 완료(box mAP 8.83%→58.62%).**
full 학습(클라우드 CUDA) 확대의 근거 확보. 커밋은 사용자 승인 후.
