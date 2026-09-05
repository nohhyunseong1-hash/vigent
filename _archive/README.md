# _archive/ — 격리 보관소 (삭제 아님)

> 2026-09-06 저장소 감사(브랜치 `audit/cleanup-20260906`, [AUDIT_REPORT.md](../AUDIT_REPORT.md)·[CLEANUP_PLAN.md](../CLEANUP_PLAN.md))에서
> **"현재 제품(산업안전 CCTV, safety 테마 단일)과 무관하다고 대표가 판단한 것"** 을 지우지 않고 이곳으로 옮겼다.
> 여기 있는 파일은 **실행·import·린트·테스트 대상이 아니다**(`pyproject.toml` ruff `extend-exclude`).

## 왜 지우지 않고 격리하는가
- 되돌리기 쉽게(폴더째 `git mv`로 복귀).
- 나중에 "그때 뭐가 있었지"를 git 이력을 뒤지지 않고 볼 수 있게.
- 최종 삭제 여부는 별도 결정(대표).

## 목록

| 폴더 | 원위치 | 내용 | 격리 근거 |
|---|---|---|---|
| `themes/boda/` (9) | `vigent-core/ml/boda/` | BODA 분류기·fitness 에이전트·rPPG 심박·scene 분류·구 safety_agent/report_builder | [Z-3, 2026-08-10] office/sports 테마 영구 삭제. 코어 import 0건(✅ grep). `AX_VLM_*` env·`api.anthropic.com` 직접 호출 코드 포함 |
| `themes/fitness/` (10) | `vigent-core/ml/` | `train_yoga` `ingest_aihub_fitness` `form_model` `posture_model` `train_form_classifier` `train_posture_classifier` `pose_features` `bootstrap_labels` `retrain` `ingest_coco_keypoints` | 요가·피트니스 자세 정/오 분류기(TensorFlow/Keras, TF.js export). `pose_features` 사용처가 이 군집뿐(코어 `ergonomics.py`·`worker.py` 미사용) |
| `config/settings.yaml` | `config/` | 구 YOLO 슬롯 경로·`device: mps` ×3 | 읽는 코드 0건(train_fire/ppe docstring 언급뿐). 현행 모델 경로는 `themes/safety/vision.yaml` |

## 복구
```
git mv _archive/themes/boda vigent-core/ml/boda        # 폴더째
git mv _archive/config/settings.yaml config/settings.yaml
```
격리 직전 상태 태그: `audit-before-cleanup`(= `e1ba0ab`).

## 보류(여기 없음)
`vigent-core/ml/{eval_ergonomics,calibrate_angles,merge_retrain_data,train_retrain}.py` — worker 포즈 스레드가 살아 있어 4단계 확인 후 결정.
