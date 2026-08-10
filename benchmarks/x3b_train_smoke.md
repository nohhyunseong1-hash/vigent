# [X-3b] RF-DETR 재학습 1 epoch 스모크 — 결과 (2026-08-10, RTX 5070 Ti, cu130)

## 설치 절차(torch 보호)

1. 설치 전 기록: `torch==2.12.0+cu130`, `cuda_available=True`
2. `pip install "rfdetr[train]" -c constraints.txt`(constraints: `torch==2.12.0+cu130`,
   `torchvision==0.27.0+cu130`, `numpy==2.4.6` 고정) — `--dry-run`으로 먼저 계획 확인, torch·
   torchvision·numpy가 "Would install" 목록에 없음을 확인 후 실제 설치.
3. 설치 후 재확인: `torch==2.12.0+cu130`, `cuda_available=True`, `numpy==2.4.6` — **불변 확인.**
4. loggers extra(tensorboard/wandb/mlflow/clearml) 미설치(승인 범위 밖) — 학습 시
   `tensorboard=False, wandb=False, mlflow=False, clearml=False`로 명시 비활성화.

**★부수 발견·조치**: `albumentations`가 `opencv-python-headless`를 함께 설치하면서 기존
`opencv-python`(비-headless)의 `cv2` 네임스페이스를 덮어썼다(같은 `cv2` 패키지 이름을 두
배포판이 공유하는 Python 생태계의 알려진 충돌 — `cv2.__version__`이 5.0.0→4.10.0으로 바뀐 것을
실측 발견). `pip install --force-reinstall --no-deps opencv-python==5.0.0.93`으로 복원,
테스트 116개 재통과 확인. `requirements.txt`에 재발 방지 메모 추가.

## 스모크 실행

- 베이스 체크포인트: `vigent-core/weights/ppe_rfdetr_v1.pth`(이어서 파인튜닝)
- 데이터셋: `data/datasets/css_safety_aug`(train **4408장** = 원본 2603 + person 가림 1193 +
  NO-Hardhat/Hardhat 축소 612), valid 114, test 82(미채점)
- 해상도: 384([Q-2] 실측 근거, 운영 기본값과 동일)
- epochs=1, checkpoint_interval=1, num_workers=0(Windows), device=cuda
- 출력: `data/runs/x3b_smoke_ppe/`(운영 가중치 `vigent-core/weights/` 미변경)

## 결과

| 항목 | 값 |
|---|---|
| 1 epoch 소요시간 | **166.5초**(2분 46초) |
| 피크 VRAM | **3,164.5 MB**(GPU 총 16,303 MB 중 — 여유 충분) |
| 체크포인트 저장 | `checkpoint_best_ema.pth`·`checkpoint_best_regular.pth`·`checkpoint_best_total.pth` 3종, 각 ~120.9MB, 정상 저장 확인 |
| GPU 메모리 누수 | 없음(학습 전후 `nvidia-smi` 사용량 동일, 1640~1646MB 배경값으로 복귀) |
| 학습 파이프라인 | 정상 동작 확인(val mAP@50 0.79, epoch 0 — 파인튜닝이 실제로 진행됨을 보여주는 참고값이지, 이 스모크의 목적인 채점값은 아님) |

경고 1건(무해, 참고): "Dataset has 11 classes but model was initialized with num_classes=10" —
COCO json의 카테고리 0번("construction")은 Roboflow가 자동으로 넣는 상위 카테고리 placeholder로
실제 어떤 annotation도 이 id를 쓰지 않는다(라벨 10종만 실사용). 모델이 기존 10-클래스 그대로
로드된 것은 의도된 동작.

## 전체 학습 예상 소요시간(선형 추정)

★1 epoch 실측값(166.5초)을 그대로 곱한 값이다 — 실제로는 첫 epoch에 데이터로더 워밍업 등
일회성 오버헤드가 섞여 있을 수 있어(미검증), 이 추정은 다소 보수적(길게 잡힌)일 가능성이 있다.
epoch당 시간이 일정하다는 가정(데이터셋 크기·배치 크기 고정이므로 근거 있음)하의 선형 추정.

| epochs | 예상 소요시간 |
|---|---|
| 10 | 약 28분 |
| 20 | 약 56분 |
| 30 | 약 1시간 23분 |
| 50 | 약 2시간 19분 |
| 100(라이브러리 기본값) | 약 4시간 37분 |

**epochs 수는 아직 정하지 않았다** — 몇 epoch을 돌릴지, `early_stopping`(라이브러리 기본
False, patience=10으로 켜면 수렴 시 자동 조기종료 가능)을 켤지는 사용자 결정 사항이다.

## 다음 단계(승인 대기)

전체 학습은 이 보고 후 별도 승인 후 실행한다. 승인 시 확인이 필요한 것: ①epochs 수(또는
early_stopping 사용 여부) ②출력 위치(스모크와 별도 디렉터리 권장) ③완료 후 채점은 dev
74장만(§[X-3] 원 지시대로 person 재현율 1차, NO-Hardhat 구간·전체 정밀도 2차, test 35장은
계속 봉인).
