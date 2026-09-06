# CLEANUP_PLAN — 2단계 정리 계획서

> 작성 2026-09-06 · 브랜치 `audit/cleanup-20260906` · 기준 HEAD `e1ba0ab`
> **이 문서는 계획이다. 대표가 "진행해"라고 하기 전까지 아무 파일도 이동·삭제·수정하지 않는다.**
> 원칙: ① 삭제보다 격리(`_archive/`) ② 한 묶음 = 한 커밋 ③ 매 커밋 뒤 `ruff`·481 테스트·OpenAPI 무변경 확인 ④ 이력 재작성 없음.

---

## 1. 한눈에 보기

| 묶음 | 동작 | 파일 수 | 위험 | 커밋 |
|---|---|---:|---|---|
| ① 삭제 테마 잔재 격리 | `git mv` → `_archive/themes/` | 15 (+5 제안) | 낮음 — 코어 import 0건 실측 | C1 |
| ② 초기 프로토타입·낙상 벤치 삭제 | `git rm` | 3 + 10 | 낮음 — 이력 복구 가능 | C2 |
| ③ 학습 도구 `training/` 집결 | `git mv` | 약 12 | 중간 — 상대경로·sys.path 수정 동반 | C3 |
| ④ mac 런처 처리 + Windows 스크립트 신규 | `git mv` + 신규 3 | 8 + 3 | 낮음 | C4 |
| ⑤ 미디어·개인정보 저장소 밖 이동 | 파일 이동 + `VIGENT_DATA_DIR` + `.gitignore` | 103 (jpg 82·mp4 21) − fixtures | **중간** — 벤치 스크립트 22곳 경로 수정 | C5 |
| ⑥ requirements 분리 | `requirements-agents.txt`·`-train.txt` 신설 | 3 편집 + 2 신규 | 낮음 | C6 |
| ⑦ 루트·untracked 정리 | 이동·gitignore | 4 | 낮음 | C7 |
| ⑧ `.gitattributes` + CRLF 정규화 | 신규 1 + 재정규화 | 전체 텍스트 | 중간 — diff가 커 보임(내용 무변) | C8(별도 커밋, 마지막) |

---

## 2. 사전 안전장치 (0단계 재확인)

```
git branch --show-current            # audit/cleanup-20260906 이어야 함(규칙 8)
git status --short | grep -v '^??'  # 추적 변경 0이어야 함
python -m unittest discover -s tests # 481 OK 기준선
git tag audit-before-cleanup e1ba0ab # 되돌림 지점 태그
```

---

## 3. 격리·삭제·이동 상세

### 3-1. `_archive/` 격리 (C1) — 대표 B 결정

`_archive/README.md`를 함께 만들어 "왜·언제·복구법"을 적는다. `pyproject.toml`의 ruff/mypy 대상에서 `_archive`를 제외한다(`extend-exclude`).

| 원위치 → 새 위치 | 근거 |
|---|---|
| `vigent-core/ml/boda/`(9) → `_archive/themes/boda/` | Z-3 삭제 테마 BODA 분류기·rPPG·fitness. 코어 import 0 |
| `vigent-core/ml/{train_yoga,ingest_aihub_fitness,form_model,posture_model,train_form_classifier,train_posture_classifier}.py`(6) → `_archive/themes/fitness/` | 요가·피트니스 자세 분류 |
| ★제안(대표 승인 필요) `ml/{pose_features,bootstrap_labels,retrain,ingest_coco_keypoints}.py`(4) → `_archive/themes/fitness/` | `pose_features`의 사용처가 위 fitness 파일들뿐(AUDIT §4). 남기면 import 끊긴 고아가 됨 |
| ★제안 `config/settings.yaml` → `_archive/config/` | 읽는 코드 0건, `device: mps`·구 YOLO 경로 |

**보류(4단계 후)**: `ml/{eval_ergonomics,calibrate_angles,merge_retrain_data,train_retrain}.py`.

검증: 격리 후 `grep -rn "boda\|form_model\|posture_model\|pose_features" vigent-core tests scripts` → 0건, 테스트 481.

### 3-2. 삭제 (C2) — 대표 C 결정

| 파일 | 커밋 메시지에 남길 문구 |
|---|---|
| `vigent-core/ml/safety_pipeline.py` · `rfdetr_detect.py` · `rfdetr_zone_track.py` | "초기 RF-DETR 프로토타입(§5 MVP), 커밋 `<삭제 직전 HEAD>`에서 복구 가능 — `git checkout <hash> -- vigent-core/ml/safety_pipeline.py`" |
| `benchmarks/rig_fall/`(10) | "낙상(B8) 측정 자산 — 낙상 기능은 `ddbbb6d`(2026-08-06)에서 제거됨. 커밋 `<삭제 직전 HEAD>`에서 복구 가능" |

사전 확인(✅ 완료): 셋 다 코어·테스트 import 0건. `zone_geom.py` docstring이 `rfdetr_zone_track`을 언급하나 import는 아님(문구만 손봄).

### 3-3. 학습 도구 `training/` 집결 (C3) — 대표 A③

| 이동 | 비고 |
|---|---|
| `vigent-core/ml/{train_fire,train_forklift,train_ppe}.py` → `training/` | ultralytics(AGPL) 의존 — `requirements-train.txt` |
| `vigent-core/ml/{eval_accuracy,compare_models}.py` → `training/eval/` | RF-DETR 정확도 측정 |
| `tools/{train_merged,train_safety,train_monitor,prelabel}.py` → `training/` | YOLO 학습·사전라벨 |
| `tools/ml/{eval_harness,ppe_eval,tiled_detect,yolo_to_coco}.py` | **유지**(`tools/ml/`) — §7 병합 결과가 여기 |
| `cloud/`(6) · `colab/`(1) | **유지**(폴더 그대로) — 노트북·Colab 빌더는 이미 독립 폴더. `training/README.md`에서 링크 |
| `vigent-core/ml/{rtsp_test,make_test_video}.py` → `tools/` | 학습 아님(유틸) |

이동 후 `vigent-core/ml/`에 남는 것: `vlm_risk_summary.py`(런타임) + 보류 4파일. 각 스크립트의 `ROOT = Path(__file__).resolve().parent.parent...` 깊이가 바뀌므로 **이동 파일마다 ROOT 계산 1줄 수정** 필요(수정 목록은 실행 시 diff로 제시). 기술 부채 기록: "학습 도구 별도 저장소 분리" → FINAL_SUMMARY.

### 3-4. macOS 런처·plist (C4) — 대표 B ★미기입 항목

| 대상 | 기본안(격리) | 대안(재배포 가능 시) |
|---|---|---|
| `VIGENT Safety 시작.command` · `VIGENT 웹캠수집.command`(루트) · `실행/Safety/VIGENT_{Safety,Tapo}.command` · `bin/vigent-edge.command` | → `_archive/macos/launchers/` | → `deploy/macos/launchers/` |
| `deploy/launchd/*.plist`(2) | → `_archive/macos/launchd/` | → `deploy/macos/launchd/` |
| `training/mps_bench.py` | → `_archive/macos/` | 유지 |
| `실행/` 폴더 | **제거**(내용 mac 런처 2개뿐 ✅) | 동일 |

**신규 Windows 스크립트(어느 안이든)**:
- `run.ps1`(루트) — `run.sh`와 1:1: `VIGENT_HOST`/`VIGENT_PORT`/`VIGENT_API_TOKEN` env, uvicorn 설치된 python 탐색(`py -3.11`, `python`), `cd vigent-core`, `python -m uvicorn main:app`
- `run.bat` — `run.ps1` 호출 래퍼(더블클릭용, `-ExecutionPolicy Bypass`)
- `VIGENT Safety 시작.bat` — 서버 기동 후 `start http://127.0.0.1:8010/safety-local`(mac `.command` 대응)
- README "실행" 절을 Windows 우선 + mac/Linux `run.sh`로 재작성(C4에 포함, 문서만)

### 3-5. 루트 정리 (C7)

| 파일 | 동작 |
|---|---|
| `VIGENT 상용화 준비 체크리스트.md` | → `docs/COMMERCIALIZATION_CHECKLIST.md`(대표 결정 "유지, docs 이동"). 링크 참조 grep 후 갱신 |
| `.gitignore`의 `/VIGENT *.command`·`/VIGENT *.md` 규칙 | 이동 후 규칙 정리 |

### 3-6. untracked 3개 (C7) — 대표 E

| 항목 | 정체(한 줄) | 권고 |
|---|---|---|
| `docs/복구_폴라리스캐시/` | 사업계획서 편집본 복구용 Polaris Office 캐시 3개(암호화 .dat) — 개인 문서 | **커밋 금지**, `.gitignore`에 `docs/복구_폴라리스캐시/` 추가. 원본은 `D:\vigent_field\polaris_recover_20260903\`에 있으므로 복구 끝나면 이 사본은 삭제 권고 |
| `docs/review/`(15 md) | 사람이 직접 코드 검토할 때 쓰는 준비 자료(현황·읽는 순서·파일별·계열사냥·문서불일치·자신없는곳·기록표). 대표 지시로 커밋 안 한 상태 | **유지·커밋 권고** — 감사 3·4단계가 이 자료(특히 04·05·06)를 근거로 쓴다. 커밋해야 브랜치 간 공유됨 |
| `docs/사업계획서 양식.docx` | 정부 지원사업 사업계획서 원본 양식 — `scripts/fill_business_plan.py`의 **입력 파일** | **유지·커밋 권고**(스크립트가 없으면 못 돎). 위치는 `docs/templates/사업계획서_양식.docx`로(공백 제거). 개인정보 없음(빈 양식) |

---

## 4. requirements 분리 (C6) — 대표 A②·A③

| 파일 | 내용 | 출처 |
|---|---|---|
| `requirements.txt` | 변경 없음(감시 서버 코어) | — |
| **신규 `requirements-agents.txt`** | `-r requirements.txt` + `openai==2.44.0` · `anthropic==0.115.1` · `sentence-transformers==5.6.0` | `requirements-optional.txt`에서 분리 |
| **신규 `requirements-train.txt`** | `-r requirements.txt` + `rfdetr[train]`(constraints 동반) · `pycocotools==2.0.11` · `faster-coco-eval==1.7.2` · `ultralytics==8.3.253`(AGPL, 학습·baseline 전용) | `requirements-eval.txt` 흡수 |
| `requirements-optional.txt` | 남는 것: `mlx*`(Apple 전용, 주석 강화) · `mediapipe` · `scipy`·`scikit-learn` · `python-docx`(문서 도구) | 정리 |
| `requirements-eval.txt` | → `requirements-train.txt`로 통합 후 삭제(README·CI 참조 갱신) | |

의존 방향 확인(✅ 현재 상태): 코어 `app_state.py:14`가 `agents`를 import하지만, `agents/*`의 LLM·RAG import는 전부 함수 내부 지연 import → `requirements.txt`만으로 기동·481 테스트 통과(이 PC 실측). **코어가 `agents/`를 import하지 않게 하는 구조 변경은 3단계**(라우터 분리 필요, 이번 범위 아님).

---

## 5. 미디어·개인정보 파일 (C5) — 대표 D

### 5-1. 이동 대상 (✅ 실측 103파일, 약 33MB)

| 원위치 | 파일 | 새 위치 `../vigent_private_data/` 아래 | 성격 |
|---|---|---|---|
| `runs/rfdetr/accident/` | mp4 9 | `runs/rfdetr/accident/` | 카카오톡 사고 영상(출처·동의 미확인) |
| `runs/rfdetr/refset/` | mp4 4 | `runs/rfdetr/refset/` | 얼굴 식별 가능(규칙10) |
| `runs/rfdetr/lowres/` mp4 7 · `multi_scene.mp4` | 8 | `runs/rfdetr/...` | 벤치 영상 |
| `runs/site01_eval/` | jpg 24 | `runs/site01_eval/` | 고객사 프레스 설비(규칙10) |
| `runs/forklift_duel/` | jpg 24 | `runs/forklift_duel/` | 학원 유사 영상 스틸 |
| `runs/tapo_test_eval/` | jpg 24 | `runs/tapo_test_eval/` | 카메라 테스트 |
| `benchmarks/results/webcam_coord/` | jpg 5 | `benchmarks/results/webcam_coord/` | **얼굴 식별 가능**(규칙10) |
| `benchmarks/results/fire_smoke_diag/` | jpg 2 | 동일 | 공개 데이터셋 표본(AoF) |
| `docs/team/*.png`(6) | png 6 | **유지** | UI 목업 화면(개인정보 없음) |
| `vigent-core/demo_assets/`(3) | jpg 3 | **유지 → `tests/fixtures/`로 복사** | 아래 5-3 |

이동 방식: `../vigent_private_data/`는 **저장소 밖**(`D:\vigent_private_data\`). 이동은 `git rm --cached` + 파일시스템 이동(트리에서 제거, 이력엔 잔존). `README.md`를 그 폴더에 두어 원위치 매핑을 적는다.

### 5-2. 경로 참조 코드 → `VIGENT_DATA_DIR` (✅ grep 22곳)

| 파일 | 현재 | 변경 |
|---|---|---|
| `benchmarks/academy_prep/{g1_forklift_eval,g1_coco_proxy,g1_duel,g5_driver}.py` · `benchmarks/e1_bottleneck/{e1_standalone,e1_saturate,v1_pose,v1_pose_spin,v1_slots,v3_fps}.py` · `benchmarks/site01_precheck/{s1_analyze,s1_zones}.py` | `Path("D:/vigent_original/runs/...")` **절대경로** | `Path(os.environ.get("VIGENT_DATA_DIR", ROOT.parent/"vigent_private_data")) / "runs/..."` |
| `benchmarks/e1_bottleneck/{v2_cpuonly,v2_parity}.py` · `benchmarks/{capacity_ramp,track_fragmentation_causes,person_overlap_mac_vs_multi}.py` · `benchmarks/tapo_test_eval/tp_eval.py` · `benchmarks/site01_precheck/s1_eval.py` | `ROOT / "runs/..."` 상대 | 동일 헬퍼 |
| `scripts/eval_tracking.py:42-44` · `scripts/capacity_probe.py` | `runs/rfdetr/...` 기본값 | 동일 헬퍼 + 파일 없으면 명확한 안내 후 종료 |
| 공통 헬퍼 | 신규 `vigent-core/data_paths.py` 또는 `benchmarks/_paths.py`: `data_dir()` 1함수 | 22곳이 이것만 import |

### 5-3. `tests/fixtures/` (얼굴 미식별 최소 표본)

| 후보 | 판단(✅ 육안 확인) | 처리 |
|---|---|---|
| `vigent-core/demo_assets/demo1.jpg`·`demo2.jpg` | 승마장 인물 1명, 원거리·저해상(80KB)·얼굴 식별 불가. `tests/test_rfdetr_onnx_parity.py:33`이 demo1 사용 | `tests/fixtures/person_far.jpg`로 **복사**(demo_assets는 `demo.py`가 쓰므로 유지) |
| `vigent-core/demo_assets/demo4.jpg` | 실내 배선·물건만, 사람 없음(Tapo 캡처) | `tests/fixtures/no_person.jpg` 복사 |
| 사고·현장 영상 | 전부 사람·설비 포함 | fixtures에 **넣지 않음**. 영상이 필요한 테스트는 `make_test_video.py`(합성 이동 영상)로 생성 — 합성안 채택 |

### 5-4. `.gitignore` 추가

```
# 미디어는 저장소 밖(VIGENT_DATA_DIR). fixtures·docs 목업·demo_assets만 예외
*.mp4
*.avi
*.mov
*.jpg
*.jpeg
*.png
!tests/fixtures/**
!docs/team/*.png
!vigent-core/demo_assets/*.jpg
!reports/**/*.png      # (현재 reports/*.png 는 무시 중 — 유지)
docs/복구_폴라리스캐시/
```
⚠ 기존 `runs/field_*/**/*.jpg` 규칙과 중복되나 충돌 없음. `git check-ignore -v`로 예외가 살아 있는지 확인.

### 5-5. 이력에 남는 민감 파일 (FINAL_SUMMARY 별도 섹션용 · 이번엔 재작성 안 함)

| 최초 커밋 | 날짜 | 파일 | 용량 | 원격 |
|---|---|---|---|---|
| `2a98fa9` | 2026-07-12 | `benchmarks/results/webcam_coord/*.jpg` 5(얼굴) | 245KB | ✅ origin/main·fix/review-bugs |
| `b9e8289` | 2026-08-28 | `runs/**` jpg 72 + mp4 21(얼굴 4·고객사 24·사고 9) | ~33MB | ✅ 동일 |
| `1ecbd80`→`ddbbb6d` 삭제 | 2026-06-24 / 08-06 | `demo_assets/demo3.jpg`(이력에만) | — | ✅ |

→ 원격에 push된 상태이므로 **이력 재작성은 별도 작업**(로컬 filter-repo + force-push + 협업자 재클론). 저장소가 비공개인 동안은 규칙10 체크리스트 ⛔ 항목으로 유지.

---

## 6. `agents/safety_manager.py` 비교표 — 대표 결정용

**파일 요약**(180줄): `decide(event)` = event → `safety_brain.assess`로 등급(high/mid/low/unknown) → 등급별 **"권장 행동" 목록만 반환**(`requires_approval=True`, `auto_executed=False`, executor는 문자열 스텁 `"Dispatcher.notify"` 등 — 실제 호출 없음). `ask(question)` = `safety_rag.retrieve` + `safety_brain.list_activities` + `data_engine.list_events`로 근거 있는 답만, 없으면 "확인 필요". 라우트: `POST /safety/manager/decide`·`/ask`(`routers/safety_core.py:77·86`). 프론트 호출부: **0건**(`static`·`themes` grep) → API로만 존재.

| 기능 | SafetyManager | 현행 worker 파이프라인 | 관계 |
|---|---|---|---|
| 위험 등급 판정 | `safety_brain.assess(activity, classes)` — **작업 종류 기반**(사람이 activity를 넣어야 함) | `worker._derive` → 규칙(ppe_missing·zone·proximity…) — **프레임 검출 기반** | **다른 입력, 다른 축**. 중복 아님 |
| 알림 | "관리자 알림 권장" 문자열만 | `alert_notify → alert_gate → dispatcher` 실제 발송 | 기능 중복 없음(스텁) |
| 위험성평가 초안 | "Scribe 권장" 문자열만 | `Scribe.build_assessment` 실제 생성 | 스텁 |
| 정지 신호 | "보조 신호 권장" 문자열 | `relay.py` 실제 신호 | 스텁 |
| 질의응답 | `ask()` — RAG+지식 | `routers/safety_core.py:373-391·553-554`가 `safety_brain`·`safety_rag`를 **직접** 호출하는 별도 엔드포인트 존재 | **부분 중복** — 같은 두 모듈을 다른 포장으로 두 번 노출 |
| 사람 승인 루프 | 설계 의도(반자동) | 없음(자동 발송) | SafetyManager만 가진 개념이나 **실행 연결 없음** |

**판단 재료**: 살아 있는 API 2개이나 프론트가 안 쓰고, 실행 연결이 전부 스텁이다. 선택지 — (a) **유지**: "사람 승인 루프" 설계를 앞으로 구현할 씨앗으로 두고 4단계에서 `ask`의 중복만 정리. (b) **격리** `_archive/agents/`: 라우트 2개 제거(OpenAPI baseline 갱신 필요). (c) 삭제. → **권고 (a)**: 삭제해도 얻는 게 180줄뿐이고, 반자동 승인 개념은 산업안전 제품에서 필요한 방향이다. 대표 결정 대기.

---

## 7. `tools/ppe_eval.py` ↔ `tools/ml/ppe_eval.py` 병합안 (✅ diff 완료)

| | `tools/ppe_eval.py`(38줄, 2026-06-30) | `tools/ml/ppe_eval.py`(149줄, 2026-08-07 최신) |
|---|---|---|
| 방식 | `ultralytics.YOLO(best.pt).val()` — **AGPL**, 모델 직접 | `guard.detect(detectors=["ppe"])` → **배포 파이프라인 그대로**(가드 임계 반영), IoU≥0.5 클래스별 P/R/AP50 |
| 경로 | `~/Desktop/VIGENT/runs/ppe_train/merged_v1/weights/best.pt` **mac 절대경로**, 존재 안 함 | `--set data/datasets/css_safety/test` 인자 |
| 현행 모델 참조 | ✗ (구 YOLO merged_v1) | ✓ (vision.yaml 슬롯 = 현 RF-DETR ppe) |
| 고유 기능 | mAP50-95(ultralytics 내장) | 클래스별 TP/FP/FN 표, `detect_isolated`로 추적기 오염 차단 |

**병합안**: `tools/ml/ppe_eval.py`를 **단일본**으로 하고 `tools/ppe_eval.py`는 **삭제**(C3에 포함). 옛 파일에서 가져올 것은 없다 — mAP50-95는 ultralytics(AGPL) 의존이며 배포 모델이 RF-DETR로 바뀌어 적용 불가. 대신 `tools/ml/ppe_eval.py` docstring에 "구 `tools/ppe_eval.py`(YOLO val) 흡수, 커밋 `<hash>`" 한 줄과 `TARGETS` 주석의 "ppe_css_v1.pt" 표기를 현행 슬롯명으로 고친다(4단계 문서 정합에서).

---

## 8. 실행 순서·검증

| 커밋 | 내용 | 검증(각 커밋 직후) |
|---|---|---|
| C0 | `git tag audit-before-cleanup` | — |
| C1 | `_archive/` 격리 + README + ruff exclude | ruff 0 · mypy 0 · 481 OK · grep 잔존 0 |
| C2 | 삭제 3+10(복구 hash 명시) | 481 OK · OpenAPI 무변경 |
| C3 | `training/` 집결 + `tools/ppe_eval.py` 삭제 + ROOT 수정 | 이동 스크립트 각 `--help` 실행 · 481 OK |
| C4 | mac 런처 처리 + `run.ps1`/`run.bat`/`시작.bat` + README 실행절 | **`run.ps1`로 실제 기동 → `/health` 200 확인**(승인 필요: 서버 기동) |
| C5 | 미디어 이동 + `VIGENT_DATA_DIR` 헬퍼 + 22곳 수정 + fixtures + gitignore | `git ls-files '*.jpg' '*.mp4'` = fixtures·docs·demo만 · `tests/test_rfdetr_onnx_parity` 통과 · 벤치 1개 실행 확인 |
| C6 | requirements 분리 + CI 참조 갱신 | CI yaml 문법 · `pip install -r requirements-agents.txt --dry-run` |
| C7 | 루트 md 이동 · untracked 처리 · gitignore | `git status` 깨끗 |
| C8 | `.gitattributes`(`* text=auto eol=lf`, `*.ps1/*.bat eol=crlf`, 바이너리 지정) + `git add --renormalize .` | 커밋 diff가 **줄바꿈만**인지 `git diff --ignore-all-space --stat` = 0 확인 |

각 커밋 메시지 한국어, 말미 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## 9. 대표 결정 필요 (이 계획을 "진행해"라고 하기 전에)

| # | 결정 | 기본안 |
|---|---|---|
| 1 | mac 런처·plist: `deploy/macos/` vs `_archive/macos/` | `_archive/macos/` |
| 2 | pose 군집 4파일 fitness와 함께 격리 | 격리 |
| 3 | `config/settings.yaml` 격리 | 격리 |
| 4 | `safety_manager.py` (a)유지/(b)격리/(c)삭제 | (a) 유지 |
| 5 | `docs/review/`·양식 docx 커밋 | 커밋 |
| 6 | C4 검증을 위한 **서버 기동 1회** 허용 | 허용 요청 |
| 7 | C8 CRLF 재정규화를 이번에 할지(diff 큼) | 이번에, 마지막 커밋으로 |

---

## 10. ★범위 결정 2차 (2026-09-06, C7 이후 대표 지시)

**이번 작업은 비전(감시 서버 코어)에 집중. 에이전트는 범위 제외.**

| 항목 | 결정 | 반영 |
|---|---|---|
| `agents/` 및 자산(`legal_whitelist`·`config/corpus`·`eval/golden`·`datasets/goldens`) | **현 상태 유지** — 격리·삭제·리팩터링 금지 | C1~C7 어느 것도 이들을 건드리지 않았음(✅). C6의 `requirements-agents.txt`는 의존성 파일 분리일 뿐 코드 불변 |
| 코어가 `agents/` 없이 import·기동되는가 | 확인 → 안 되면 **그 의존만** 끊기 | ✅ 실험: `agents/__init__.py`가 Analyst·Scribe·Copilot·SafetyManager를 즉시 import → 4모듈 차단 시 `app_state`·`worker`·`main` **전부 ImportError**. ★단 `agents/` 패키지에는 코어인 **Guard(검출)·Dispatcher(통보)** 도 들어 있어 "agents/ 통째로 없이"는 성립하지 않는다 → LLM 에이전트 4종만 **선택 import**로 완화(C9) |
| 4단계 CODE_REVIEW에서 `agents/` | 정밀 리뷰 제외. 치명(비밀정보 노출·코어를 깨뜨리는 import 오류)만 | `safety_manager.py` "UI 연결 여부" → 보류 항목 |
| 정밀 리뷰 대상(한정) | 카메라 입력·go2rtc 연동 / 감지 파이프라인(RF-DETR·nano·yunet, 초당 2회 스케줄링) / 5개 감지 규칙(보호구 미착용·위험구역·중장비 협착·급격동작·무동작) / 오경보 억제 / 텔레그램 dispatcher / 보존 스윕 / `realtime_core.js` 중 감시 화면 / 설정·경로·기동 스크립트 | 4단계 |
| Qwen3.6 | 별도 프로젝트(외부 에이전트) — 이 저장소엔 없음(정정 유지) | AUDIT §1-1 |

### FINAL_SUMMARY "다음 단계"에 기록할 2항목(대표 지정)
1. **Windows용 로컬 VLM 대체 구현** — RTX 5070 Ti 16GB / CUDA 13 기준, transformers 또는 vLLM. **비전 후속 1순위.** (현 코드의 로컬 VLM은 mlx-vlm/Apple 전용 → Windows에선 조용히 꺼짐, AUDIT §9-a)
2. **에이전트 통합 설계** — 별도 프로세스·별도 requirements(`requirements-agents.txt`)로 두고 감시 서버와 **HTTP API로만** 연결(현장 PC 사양 분리 목적). 기존 `agents/`를 외부 Qwen3.6 에이전트로 대체할지는 그때 결정.
