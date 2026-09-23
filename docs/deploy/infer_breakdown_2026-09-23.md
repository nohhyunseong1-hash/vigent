# 정적 영상 추론 구간 분해 — CPU vs GPU (USB 1차 승인 항목 1, 2026-09-23)

> **측정 기계**: 개발기 Ryzen 9 9900X · **RTX 5070 Ti 16GB**. ★RTX 5060·노트북 값이 아니다.
> **대상**: GPU 포터블 재빌드본 `D:\vigent_portable_gpu2`(cu130, PPE torch). 사고영상 `KakaoTalk_20260807_000438282.mp4`
> 30번째 프레임(720×406), 384px, 예열 5회 후 **20회**. 도구: [`scripts/bench/infer_breakdown.py`](../../scripts/bench/infer_breakdown.py).
> **조건**: GPU 유휴(다른 프로세스 1.58GB·9~18%, PUBG 없음). ★첫 시도는 PUBG 실행 중이라 폐기했다(§4).

## 1. GPU 열 (cuda)

| 구간 | 평균 ms | p50 | p95 | 비고 |
|---|---|---|---|---|
| decode(mp4) | 0.1 | 0.1 | 0.2 | 앱 `last_detect_ms` 에 **미포함**(캡처 스레드가 미리 디코드) |
| preprocess(+H2D) | 2.6 | 2.5 | 3.0 | cv2 리사이즈·정규화·H2D |
| **person_fwd** | **5.2** | 5.2 | 5.7 | `inference_model`(export+jit.trace) — 앱과 같은 객체 |
| **ppe_fwd(torch)** | **5.0** | 4.9 | 5.7 | 〃 |
| postproc(+D2H) | 1.1 | 1.0 | 1.5 | rfdetr PostProcess |
| 합계(pre+person+ppe+post) | **13.9** | | | |
| predict_e2e person(참고) | **11.6** | 11.6 | 12.8 | 앱이 실제로 부르는 `predict(pil)` 슬롯당 |
| predict_e2e ppe(참고) | **11.7** | 11.5 | 13.3 | 〃 |

torch VRAM allocated 503 MB · reserved 766 MB.

## 2. CPU 열 (cpu, 같은 cu130 포터블의 torch CPU 경로)

| 구간 | 평균 ms | p50 | p95 | 비고 |
|---|---|---|---|---|
| decode(mp4) | 0.2 | 0.1 | 0.3 | |
| preprocess | 2.7 | 2.8 | 2.8 | |
| **person_fwd** | **137.0** | 138.4 | 141.7 | |
| ppe_fwd(torch) | 138.2 | 138.0 | 141.0 | CPU 빌드는 이 경로를 쓰지 않는다 |
| **ppe_fwd(onnx-cpu)** | **80.6** | 80.5 | 82.0 | **CPU 빌드의 실제 PPE 경로**(앱 튜닝 intra 4·spin off) |
| postproc | 0.7 | 0.7 | 0.8 | |
| 합계(torch 경로) | 278.6 | | | |
| predict_e2e person / ppe(참고) | 139.5 / 137.5 | | | |

→ **CPU 빌드 프레임당 ≈ person 137 + ppe(onnx) 81 + 전후처리 3 ≈ 221 ms**. 이전 G-2 의 CPU 포터블 231.6 ms(guard 경로, 추적 포함)와 맞는다.

## 3. 왜 앱 내 p95(41~77 ms)와 옛 정적 시험(128.6 ms)이 다른가

| 값 | 무엇을 쟀나 | 설명 |
|---|---|---|
| **128.6 ms** (G-2, 09-23 새벽) | guard 경로 person+ppe, **I-1 이전 포터블** | 그때 PPE 는 **onnx-cpu**(위 표 80.6 ms) 였다. person GPU ≈ 12 + ppe onnx ≈ 81 + guard·추적 ≈ 30 → 128. **조건이 달랐지, 모순이 아니다.** |
| **p50 27~37 ms** (앱, 4채널 3회) | `t0(프레임 시각) → 추론 완료`, 락 대기 포함 | GPU 슬롯당 `predict` 11.6 ms × 2(person+ppe) ≈ 23 + 추적·락 ≈ 27~37 ✔ |
| **p95 41~77 ms** (앱) | 〃 | 4채널이 **한 DETECT_LOCK 을 직렬로** 탄다 — 다른 카메라 추론을 기다린 주기가 p95 를 만든다(최대 4대 × 23 ≈ 92 ms 상한과 부합). 순수 추론이 느린 게 아니다. |
| **13.9 ms** (이 표 합계) | 순전파+전후처리만, 락·추적 없음 | 앱 p50 의 절반 — 나머지는 `predict` 내부 PIL 전처리(2.6 → ≈8 ms 차이)·추적·락 |

★`predict_e2e`(11.6) 가 구간 합계 슬롯당(≈6.9) 보다 큰 것은 rfdetr `predict` 가 PIL 경로로 전처리하기 때문이다. **앱 예산 계산에는 11.6 ms/슬롯을 쓴다**(앱이 그걸 부른다).

## 4. 5060 4채널 2fps 여유 계산에 쓸 값

- 프레임당 GPU 시간(앱 경로, person+ppe): **≈ 23.3 ms** (`predict` 11.6 × 2). fire_smoke 는 포터블 프로필에서 꺼져 있다.
- 4채널 × 2 fps = **8 프레임/s** → **≈ 186 ms/s = GPU 직렬 점유 18.6 %** (5070 Ti 실측 기준).
- 락 직렬화 상한: 4대가 동시에 몰려도 4 × 23.3 ≈ 93 ms < 주기 500 ms — 여유 5.4배.
- ★**RTX 5060 값은 없다.** 5070 Ti 대비 배수를 **추정하지 않는다.** 위 18.6 % 가 5060 에서 3배(≈56 %)가 돼도 주기 안이라는 것까지만 말할 수 있고, 그 3배도 근거 없는 가정이다. 실기 측정이 필요하다.
- VRAM: torch reserved 766~862 MB + 컨텍스트 몫 ≈ 3.2 GB 추정(bench_4ch_repeat §4-1).

## 5. 폐기한 측정 (기록)

첫 실행은 PUBG(`TslGame.exe`) 가 GPU 67 %·6.1 GB 를 쓰는 중이었다: person_fwd 23.2 / ppe 23.8 ms(깨끗한 값의 4.5배), CPU person 277 ms. 또 초기 스크립트는 `model.model`(optimize 전)을 불러 CPU 열이 `predict` 보다 2.3배 느리게 나왔다 — 앱은 `model.inference_model` 을 쓴다(detr.py:1593). 둘 다 고친 뒤 위 표를 쟀다. **bench_4ch 의 GPU 오염 가드(≥500 MB 중단)는 이 사고에서 나왔다** — 단 이 개발기의 유휴 VRAM 이 이미 **1.5 GB**(Edge·Chrome·Discord·Claude 앱·NVIDIA 오버레이)라 임계 500 MB 로는 벤치가 항상 막힌다. 임계는 사용자 결정 사항이라 그대로 두고 여기 적는다.
