# PPE A′ — 첫 유효 실험(슬롯 정렬 한 변수) 결과 + v1 / D / A′ 나란히 (2026-09-27 14:31~15:12) [실측]

> 첫 줄 단서: Hardhat 준라벨 681장은 미검수(A 와 동일). 데이터·레시피는 A 와 완전히 같고(클래스별 박스 수 동일: 27,564), **변수는 슬롯 정렬 하나** —
> `classes` 를 v1 10슬롯 순서로 두고 `drop_classes` 로 Mask·NO-Mask·Cone·machinery·vehicle 주석만 비웠다. 사전 가드 `slot_alignment` 통과(10슬롯 전부 ✓, plan.json 기록).
> 원자료: `benchmarks/results/ppe_smoke_A2_20260927/`. 체크포인트 SHA `934d4bbc…`(미추적). **배포 없음.**

## 1. v1 / D / A′ (held-out 91장 @0.35 · dev74 Mask 제외)

| 행 | 데이터 · 레시피 | NO-Hardhat R [W95] | NO-Hardhat P | NO-SV R | Hardhat R | SV R | 4클래스 AP50 | dev74 PPE R [W95] (tp/231) | dev74 NO-Hardhat (tp/54) |
|---|---|---|---|---|---|---|---|---|---|
| **v1** | CSS(누출 분할) · Colab | **64.1 [51.8, 74.7]** | 69.5 | 83.7 | 87.0 | 80.6 | **81.3** | **62.3 [55.9, 68.3]** (144) | 14 |
| D(결함) | CSS 만 · v1 이어 학습(슬롯 어긋남) | 64.1 [51.8, 74.7] | 78.8 | 81.5 | 85.6 | 77.4 | 81.2 | 54.5 [48.1, 60.8] (126) | 11 |
| **A′(유효)** | CSS+507+준라벨 · v1 이어 학습 · **슬롯 정렬** | **64.1 [51.8, 74.7]** | 75.9 | 77.0 [69.3, 83.3] | 85.6 | 75.8 | **80.1** | **51.1 [44.7, 57.5]** (118) | 9 |

- (참고, 결함 레시피) A 65.6 / B 62.5 — A′ 와 구간 안.

## 2. 판정

- **A′ ≈ v1**: held-out NO-Hardhat 재현율이 v1 과 같고(64.1), 4클래스 AP50 −1.2, NO-Safety Vest −6.7(구간 겹침). 슬롯을 맞춰도 held-out 은 오르지 않았다 → 결정 경로상 **"이어 학습 한계" → E(COCO nano 에서 CSS+507 새로 학습) 1회**.
- dev74 는 슬롯 정렬로도 회복되지 않았다(−11.3 %p, NO-Hardhat 9/54·오탐 8). 즉 dev74 하락은 슬롯 충돌 때문이 아니다 — 남는 후보 [추정]: lr 1e-4·10 epoch 이어 학습이 v1 의 현장 일반화를 깎음(D 에서도 −7.8), 또는 507·CSS 재학습 자체가 사고영상 분포와 어긋남. E 가 이 둘을 가르지는 못한다(시작점만 바꿈).
- 학습 중 검증(507 위주 800) EMA mAP50 0.866→0.891 로 A 보다 높았지만 held-out 에는 옮겨지지 않았다 — 검증셋 치우침 재확인.

## 3. 조건

epochs 10 · batch 8×2 · lr 1e-4 · res 384 · seed 20260926 · EMA · eval 2 · 0.66 h(epoch 3.6~4.4분) · NaN·정체 발동 0 · `configs/finetune_aihub_v2A2.yaml` ·
명령 `python scripts/train/finetune_rfdetr.py --config configs/finetune_aihub_v2A2.yaml --out runs/finetune/ppe_A2_slot --epochs 10 --batch 8 --grad-accum 2 --lr 1e-4 --res 384 --seed 20260926 --label ppe_A2_slot --copy-images --val-subsample 800 --eval-interval 2 --num-workers 0 --stall-min 15 --eval-max-dets 100 --dev74`

## 4. 다음

E(`configs/finetune_aihub_v2E.yaml`, COCO 시작·데이터 A′ 와 동일·검증 800 층화) 15:2x 착수. E 까지 held-out NO-Hardhat R 이 v1 구간 [51.8, 74.7] 안이면 **정지 규칙 발동·v1 유지**(결함 없는 실험 2회 근거).
