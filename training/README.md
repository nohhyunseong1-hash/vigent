# training/ — 모델 학습·재학습·정확도 측정 도구 (감시 서버 런타임과 무관)

> 2026-09-06 감사(A③)에서 `vigent-core/ml/`·`tools/`에 흩어져 있던 학습 도구를 여기로 모았다.
> **감시 서버(`vigent-core/`)는 이 폴더를 import하지 않는다.** 의존성은 `requirements-train.txt`(C6에서 신설).
> ★기술 부채: 장기적으로 **별도 저장소로 분리** 대상(FINAL_SUMMARY 기록). 이번엔 집결만.

## 구성

| 파일 | 용도 | 검출기·의존 | 비고 |
|---|---|---|---|
| `rfdetr_train.py` · `rfdetr_smoke.py` | RF-DETR 파인튜닝·스모크 | rfdetr[train] | 기본 device `mps` — Windows/CUDA는 `--device cuda` 명시 |
| `build_*_train_ds.py` · `build_ppe_subset.py` · `build_forklift_*.py` · `derive_forklift_optA.py` · `scan_ppe_labels.py` | 데이터셋 구성·라벨 점검 | 표준 라이브러리·yaml | |
| `train_fire.py` · `train_forklift.py` · `train_ppe.py` | YOLOv8 전이학습(구 경로) | **ultralytics(AGPL)** | 2026-09-06 `vigent-core/ml/`에서 이동. 배포 검출기는 RF-DETR로 이관 완료(A-4) — YOLO 학습은 baseline 비교용 |
| `train_safety.py` · `prelabel.py` | 현장 데이터 플라이휠(사전라벨 → 교정 → 재학습) | ultralytics | 2026-09-06 `tools/`에서 이동 |
| `train_merged.py` · `train_monitor.py` | 2026-06 통합 PPE 학습 1회성 스크립트 | ultralytics | ⚠ **mac 절대경로(`/Users/nohyeonseong/…`)·PID 하드코딩** — 그대로는 못 돎. 4단계에서 정리 또는 격리 판단 |
| `mps_bench.py` | Apple MPS 벤치 | torch | Windows 무의미 — C4에서 mac 묶음과 함께 처리 |
| `eval/eval_accuracy.py` · `eval/compare_models.py` | RF-DETR 정확도(P/R/mAP)·모델 크기 비교 | rfdetr·supervision | 2026-09-06 `vigent-core/ml/`에서 이동 |
| `watch_progress.sh` | 학습 진행 감시(bash) | — | |

관련: `cloud/`(Colab 노트북 빌더·클라우드 학습 RUNBOOK) · `colab/`(RF-DETR 파인튜닝 노트북) · `tools/ml/`(배포 파이프라인 기준 평가 하니스 — `ppe_eval.py`·`eval_harness.py`).

## 실행 전 확인
- 가중치·데이터는 gitignore 대상(`vigent-core/weights/`, `data/`, `datasets/`) — 워크트리에 없으면 `vigent-core/weights/MANIFEST.md`·`scripts/fetch_weights.py` 참고.
- ultralytics는 배포 requirements에 없다(AGPL). 학습 머신에만 `requirements-train.txt` 설치.
