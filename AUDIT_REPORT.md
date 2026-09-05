# AUDIT_REPORT — VIGENT 저장소 감사 1단계(탐색) 보고서

> 작성 2026-09-06 · 브랜치 `audit/cleanup-20260906`(기준 커밋 `e1ba0ab`) · **이 단계에서 수정·삭제한 파일 없음.**
> 표기: ✅확인됨(실측) · 🟡추정(근거 병기) · ❓불확실(질문 필요) · ★즉시 판단 요청
>
> ★**이 보고서의 "관련 없음 추정"은 삭제 제안이 아니다.** 2단계에서 `_archive/` 격리를 기본안으로 내고, 최종 삭제는 대표가 정한다.

---

## 0. 안전장치 결과 (0단계)

| 항목 | 결과 |
|---|---|
| Git | ✅ 있음. 작업 브랜치는 `fix/review-bugs`였고, 감사 브랜치 `audit/cleanup-20260906`를 만들어 체크아웃함(파일 변경 없음) |
| 미커밋 변경 | ★**untracked 3개** — `docs/review/`(코드 검토 준비 md 15편), `docs/복구_폴라리스캐시/`(★사업계획서 편집본 복구용 폴라리스 캐시 — 개인 문서, 커밋 금지 권장), `docs/사업계획서 양식.docx` |
| 추적 중인 쓰레기 | ✅ 0건 — `.DS_Store`·`__pycache__`·`*.pyc`·`node_modules`·`.venv`·`.idea` 모두 미추적 |
| `.gitignore` | ✅ 있음(94줄, 잘 정비됨 — 가중치·데이터·현장 영상·비밀키 차단, 예외 규칙까지) |
| `.gitattributes` | ❌ **없음** — 줄바꿈 정책 미고정(§5) |
| pre-commit | ✅ `.pre-commit-config.yaml`(ruff 0.12.0 핀) |

---

## 1. 프로젝트 정의 요약 — ★대표 확인 요청

> **VIGENT(Vision + AI Agent)는 산업현장에 이미 있는 CCTV·IP카메라 영상을 초당 2회 AI로 분석해
> 보호구 미착용·위험구역 침입·중장비 협착·급격동작·무동작을 감지하고, 오경보를 억제한 뒤
> 관리자 휴대폰(텔레그램)으로 통보하는 산업안전 감시 서버다.** 부가로 AI 에이전트(Scribe·Copilot)가
> 판정 결과를 법령 근거 위험성평가서 초안으로 만든다. 테마는 **safety 단일**(office·sports 테마는
> 2026-08-10 [Z-3]로 영구 삭제). 배포 형태는 노트북 1대의 FastAPI 서버 + 웹 대시보드.

근거: `README.md:3`, `CLAUDE.md` "프로젝트"·Z-3, `vigent-core/main.py:82`(FastAPI 앱), `themes/`에 `safety/`만 존재.

### 1-1. ★대표 확정(2026-09-06 답변 반영)

| 질문 | 대표 답 | 감사 반영 |
|---|---|---|
| ① "VIgent Vision" = VIGENT? | **같다.** 위 정의 그대로 확정 | 이후 관련 있음/없음 판단 기준 = 위 정의 |
| ② AI 에이전트(Scribe/Copilot/Analyst) | **의도된 기능**(실험 잔재 아님). 핵심/부가는 "LLM 없이 감시 서버가 단독 실행되는가"로 판정 | ✅ **부가(선택 모듈)** 로 판정 — 근거: 이 PC에 `openai`·`anthropic` 패키지 **미설치** 상태에서 481 테스트 통과, `llm_provider.py`는 전부 지연 import + 키 없으면 `(None, None)` 폴백(§9-a). `legal_whitelist`·`config/corpus`·`eval/golden`·`datasets/goldens`는 **에이전트 정식 자산 — 삭제·격리 금지** |
| ③ 학습·재학습 도구 | 장기 **별도 저장소 분리** 대상. 이번엔 `training/` 한 곳으로 격리만 | 2단계에 `training/` 집결 + `requirements-train.txt` 분리 반영. "학습 도구 별도 repo 분리"는 FINAL_SUMMARY 기술 부채로 |

> ⚠ **대표 답변과 코드가 다른 점 1건(규칙 7)** — ★대표 정정(2026-09-06 2차): "Qwen3.6은 **별도 프로젝트**(외부 에이전트)이며 기억 오류". 이 저장소 기준으로 진행. 답변은 에이전트를 "**Qwen3.6 기반 LLM**"이라 했으나, 저장소에 Qwen3.6은 **어디에도 없다.** 실제는 ⓐ 텍스트 LLM = **OpenAI API(기본)/Anthropic API** 클라우드 호출, ⓑ 비전 = **Qwen2.5-VL(mlx-vlm, Apple Silicon 전용)** 로컬 + OpenAI 비전 opt-in. Ollama 경로는 2026-07-14 제거. 상세 §9.

---

## 2. 기술 스택 및 버전

### 2-1. 확인된 스택 (✅ 파일 근거)

| 구분 | 내용 | 근거 |
|---|---|---|
| 언어 | Python (추적 .py 341파일 · 52,148줄) | `git ls-files` |
| 웹 | FastAPI 0.137.2 · uvicorn 0.23.2 · websockets 16.0 | `requirements.txt` |
| 비전·모델 | OpenCV(contrib-headless 4.13) · torch 2.12.0 / torchvision 0.27.0 · **RF-DETR 1.8.0**(Apache) · supervision · trackers(ByteTrack) · rtmlib(RTMPose) · onnx/onnxruntime · numpy 2.4 · Pillow | `requirements.txt` |
| 저장 | SQLite(alert_queue·tbm_store·audit_store) · JSONL | `vigent-core/alert_queue.py` 등 |
| 프론트 | 순수 HTML/JS(15 html · 7 js · 5 css, CDN) | `vigent-core/static`, `themes/safety` |
| 품질 도구 | ruff 0.12.0 · mypy 1.17.1(화이트리스트 19파일) · unittest 481건 · OpenAPI 차분 · 프로파일 드리프트 검사 · GitHub Actions CI | `pyproject.toml`, `.github/workflows/ci.yml` |
| 배포 | Dockerfile(python slim) · Windows 서비스 ps1(NSSM) · systemd unit · **macOS launchd plist** | `deploy/` |

### 2-2. ★설정 충돌·불일치 (반드시 보고하라고 한 항목)

| # | 충돌 | 상세 |
|---|---|---|
| 1 | **Python 버전 3중 불일치** | `.python-version` = **3.11.9**(로컬 실제 3.11.9) · `README.md:12` = **3.13.9** · `.github/workflows/ci.yml:24` = **3.13**("(.python-version 정합)"이라 주석돼 있으나 불일치) · `pyproject.toml` ruff/mypy = **py311**. → 개발(3.11)과 CI(3.13)가 **다른 인터프리터로 테스트**한다 |
| 2 | **README 실행 절차가 macOS 전용** | `/opt/anaconda3/bin/python3`(README 15·22·37행), `./run.sh`(30행) — Windows에서 그대로 실행 불가. Windows용 절차는 README에 **없음**(deploy/windows/*.ps1은 서비스 설치용) |
| 3 | requirements 파일 3개 | `requirements.txt`(런타임) · `requirements-optional.txt`(학습·문서도구) · `requirements-eval.txt`(평가) — 역할 분리는 명확하나 **어느 것이 Windows에서 설치 검증됐는지 기록 없음**. torch==2.12.0 핀은 플랫폼별 휠이 달라 README 주석으로만 안내 |
| 4 | CLAUDE.md 낡은 수치 | 테스트 게이트 "**55 tests**"(실제 481) · main.py "302줄"(실제 464) · 작업 폴더 "`~/Desktop/VIGENT`"(실제 `D:\vigent_original`) · 기술 스택에 "ultralytics·mmaction2·TensorFlow(BODA)" 명시 — 현재 런타임 검출은 RF-DETR이고 TensorFlow는 `requirements-optional.txt`에서 "미설치·미사용"으로 주석 처리됨 |

---

## 3. 폴더 구조와 역할 (깊이 2, 추적 파일 수)

```
D:\vigent_original\                     추적 1,054파일 · .git 49MB
├─ vigent-core/        (136)  ★제품 코드. main.py(464줄)·app_state·web_util·worker(1,258)·alert_*·privacy·retention·health
│  ├─ routers/  (12)   도메인별 API 라우터(P1-7 분할)
│  ├─ agents/    (8)   Guard(검출·추적)·Dispatcher(통보)·Analyst·Scribe·Copilot·SafetyManager·base
│  ├─ detectors/ (4)   RF-DETR 어댑터·백엔드 인터페이스
│  ├─ ml/       (34)   ★학습·평가 스크립트 + 구테마 잔재(boda/·yoga·fitness·posture)  → §4 분류 참조
│  ├─ static/   (16)   프론트 정적파일   ├─ templates/(3)   ├─ demo_assets/(3 이미지)
│  └─ weights/         가중치(gitignore, MANIFEST.md만 추적)
├─ tests/         (62)  unittest 481건
├─ scripts/       (33)  운영·측정·문서 도구(게이트 체커·현장 녹화기·보고서 생성기 등)
├─ benchmarks/   (149+) 측정 기록 md/json/py + e1_bottleneck(46)·train_logs(26)·results(19)·rig_fall(10)…
├─ docs/          (41+) 설계·절차·온보딩(12)·team(21: md+png+html/pdf)  ★+미추적 review/(15)·복구캐시
├─ audit/         (48)  소크·재연결·현장 재분석 등 감사 기록
├─ data/field_eval(116) 현장 평가 라벨(txt 110 — 텍스트만)
├─ runs/          (~120) 평가 산출물. ★jpg/mp4 미디어 다수 추적(§3-2)
├─ config/ (13) · themes/safety/ (8) · deploy/ (academy 4·windows 4·systemd 2·launchd 2·watchdog.sh)
├─ tools/(11+4) 소크·스트레스·추적품질·PPE 평가 하니스 │ training/(11)·cloud/(6)·colab/(1) 학습 파이프라인
├─ eval/golden(27) · datasets/goldens(26)  에이전트 골든 채점셋(텍스트)
├─ md/(5) 메타프롬프트·배포·릴리스 │ reports/(4) 현장 보고서 │ attribution/ 출처 │ bin/(4) mac 셸
├─ 실행/Safety/    ★macOS .command 런처 2개(한글 폴더)
└─ 루트: CLAUDE.md · README.md · SAFETY_REVIEW_REPORT.md · Dockerfile · pyproject · requirements×3 · run.sh
         · VERSION · baseline_openapi.json · weights_manifest.json · ★VIGENT Safety 시작.command · VIGENT 웹캠수집.command
         · VIGENT 상용화 준비 체크리스트.md
```

### 3-2. 저장소에 직접 들어 있는 바이너리·미디어 (✅ 실측)

| 종류 | 수 | 위치 | 비고 |
|---|---:|---|---|
| jpg | 82 | `runs/site01_eval/site1`(21) · `runs/forklift_duel`(24) · `runs/tapo_test_eval`(24) · `benchmarks/results/webcam_coord`(5) · `vigent-core/demo_assets`(3) 등 | ★규칙10 보류분 포함: 얼굴 식별 가능 이미지(webcam_coord 5), 고객사 설비(site01 24) |
| mp4 | 21 | `runs/rfdetr/accident`(KakaoTalk 사고 영상 9, 1~5MB) · `runs/rfdetr/refset`(4, 얼굴) · `lowres`(7) · `multi_scene` | 총 ~30MB. **git 이력에 영구 잔존** |
| pdf/html | 8 | `docs/team/pdf/`(기획안·트랙별 v0.9, 5.1MB) | md 원본에서 생성된 **파생물** |
| 1MB 초과 파일 | 16 | 위 mp4 13 + pdf 3 + `runs/field_20260827/track_debug.jsonl`(4.7MB) | 모델 가중치(.pt/.pth/.onnx)는 ✅ 전부 gitignore |
| 노트북 | 2 | `cloud/VIGENT_T10b_train.ipynb` · `colab/VIGENT_finetune_rfdetr.ipynb` | Colab 학습용 |

---

## 4. 파일 분류표

분류 방법: ①`main.py`→routers→모듈 import 그래프(✅ 실측) ②"어디서도 import되지 않음" 텍스트 탐색(🟡 근사 — `getattr`·문자열 참조·데코레이터 경유는 못 잡는다) ③docstring·이름·CLAUDE.md Z-3 기록 대조.

### [핵심] — 런타임에 실제로 로드·실행되는 것 (✅)

| 범위 | 파일 |
|---|---|
| 앱 조립 | `vigent-core/main.py` · `app_state.py` · `web_util.py` · `auth_session.py` · `ws_auth.py` · `vlog.py` · `runtime_config.py` · `tuning.py` · `device.py` |
| 라우터 12 | `routers/{cameras,detect,dispatch,incident,ppe,recognition,safety_core,system,tapo,tbm,zone,__init__}.py` |
| 판정 사슬 | `worker.py` · `agents/guard.py` · `detectors/rfdetr_adapter.py`(+base) · `isolated_detect.py` · `proximity.py` · `zone_debounce.py` · `starvation_guard.py` · `health_status.py` |
| 경보 사슬 | `alert_gate.py` · `alert_notify.py` · `alert_queue.py` · `agents/dispatcher.py` · `relay.py` |
| 개인정보·보존 | `privacy.py` · `retention.py` · `retention_scheduler.py` · `data_engine.py` |
| 저장·기록 | `tbm_store.py` · `audit_store.py` · `camera_registry.py` · `incident.py` · `legal_whitelist.py`(❓②) |
| 에이전트 | `agents/{analyst,scribe,copilot,base}.py`(❓질문② — 코어에서 `build_agents`로 로드됨은 ✅) |
| 설정·테마 | `config/*.yaml`(13) · `themes/safety/*`(8) · `deploy/academy/*`(4) · `vigent-core/weights/MANIFEST.md` · `weights_manifest.json` |
| 프론트 | `vigent-core/static/*` · `templates/*` |

### [지원] — 설정·문서·테스트·측정·배포 (✅)

`tests/`(62) · `scripts/`(33 — 게이트 체커 5종·현장 녹화/검증기·보고서/문서 생성기) · `.github/workflows/ci.yml` · `pyproject.toml` · `requirements*.txt` · `Dockerfile` · `deploy/windows/*.ps1` · `deploy/systemd/*` · `docs/`(온보딩 12편 포함) · `md/` · `audit/` · `benchmarks/*.md·json`(측정 기록) · `reports/` · `data/field_eval/`(라벨 txt) · `eval/golden` · `datasets/goldens`(❓②) · `attribution/` · `tools/{soak_monitor,soak_test,stress_concurrent,track_quality,collect_tapo_eval}.py` · `training/`·`cloud/`·`colab/`(❓③)

### [관련 없음 추정] — ★대표 판단 요청 (🟡 근거 병기)

| 파일 | 근거 |
|---|---|
| `vigent-core/ml/boda/` **9파일** (`fitness_agent`·`vitals`(rPPG 심박)·`scene_classifier`·`safety_agent`·`hazard_detector`·`report_builder`·`tracker`·`zones`·`evaluator`) | 코어 import **0건**(✅ grep) · "Fitness 에이전트 v1"·"rPPG 심박 추정" 등 **삭제된 sports/office 테마의 BODA 분류기** · `requirements-optional.txt`에 TensorFlow "미설치·미사용" 명시 |
| `vigent-core/ml/train_yoga.py` · `ingest_aihub_fitness.py` · `form_model.py` · `posture_model.py` · `train_form_classifier.py` · `train_posture_classifier.py` | docstring이 "요가 동작 인식"·"AI Hub 피트니스 자세"·"자세 정/오 분류" — **sports/office 테마 잔재**(CLAUDE.md Z-3 영구 삭제) · 코어 import 0 |
| `vigent-core/ml/eval_ergonomics.py` · `calibrate_angles.py` | docstring "office 에르고노믹스"·"정답 각도 데이터 보정" — office 테마 잔재. ✅**포즈 스레드는 살아 있다**: `worker.py:1069-1071`이 모든 run에서 `_pose_loop` 스레드를 무조건 기동하고 `_PoseModel`(worker.py:316)이 `pose/rtmpose_adapter`(rtmlib, requirements.txt 포함)를 로드한다. 다만 그 결과(`ergonomics.py` 각도 등급)가 **경보·저장까지 이어지는지**는 4단계 확인 대상 — 대표 지시대로 **보류** |
| `vigent-core/ml/merge_retrain_data.py` · `train_retrain.py` | "office + person 데이터셋 병합"·"사무실 사람↔모니터 혼동 교정" — office 테마 잔재 · `os.symlink` 사용(Windows 권한 필요) |
| macOS 런처 5개: `VIGENT Safety 시작.command` · `VIGENT 웹캠수집.command`(루트) · `실행/Safety/VIGENT_{Safety,Tapo}.command` · `bin/vigent-edge.command` | Windows 실행 불가. ★루트 2개는 `.gitignore`의 `/VIGENT *.command` 규칙과 **모순**(규칙 이전에 추적됨) |
| `deploy/launchd/*.plist` 2개 | macOS 전용 서비스 등록 |
| `training/mps_bench.py` | Apple MPS 벤치(Windows에 MPS 없음) |
| `benchmarks/results/webcam_coord/*.jpg`(5) · `runs/rfdetr/refset/*.mp4`(4) | 얼굴 식별 가능 — 규칙10 보류분. 제품과 무관하진 않으나 **저장소에 있으면 안 되는 것** |

### [중복·구버전 추정] (🟡)

| 항목 | 근거 |
|---|---|
| `tools/ppe_eval.py` ↔ `tools/ml/ppe_eval.py` | 같은 이름·같은 목적("PPE 평가")의 파일 2벌 |
| `scripts/build_field_report.py` ↔ `scripts/build_report_v12.py` | v1.1용 → v1.2용. 앞엣것은 v1.2 이후 미사용 추정 |
| 한글경로 저장 함수 3벌 | `scripts/extract_rule_frames.py:38` `_imwrite` · `scripts/make_prelabels.py:38` `_imwrite` · `scripts/field_recorder.py` `_save_jpg` (docs/review/06 기록) |
| `COLORS` 색표 3벌 | `field_recorder.py:37` · `video_offline_recorder.py:43` · guard 오버레이 |
| Wilson CI 함수 2벌 | `benchmarks/field_v12_reanalysis.py:44` · `benchmarks/ppe_mask_share_ci.py:49` |
| 히스테리시스 재구현 | `benchmarks/hysteresis_sweep.py:28`이 `guard._hysteresis`를 import 대신 **복제** — 원본 바뀌면 판정 근거가 조용히 무효 |
| `docs/team/pdf/*.html+pdf`(8, 5MB) | md 원본의 생성 파생물이 추적됨 |
| `benchmarks/train_logs/metrics (1).csv` | "(1)" 다운로드 중복 이름 |
| `weights_manifest.json`(루트) ↔ `vigent-core/weights/MANIFEST.md` | 가중치 매니페스트 2곳 — 역할 차이 미확인 ❓ |
| `vigent-core/templates/tbm_new.html` | `_new` 접미 — 구/신 공존 여부 ❓ |

### [불확실 — 질문 필요] (❓)

| 파일 | 왜 불확실한가 |
|---|---|
| `vigent-core/agents/safety_manager.py` | ★**정정(재확인 결과 살아 있음)**: `agents/__init__.py:25` `AGENT_CLASSES`로 항상 인스턴스화되고, `routers/safety_core.py:77·86`이 **`POST /safety/manager/decide`·`/safety/manager/ask`** 로 노출함. 1차 "import 0건"은 문자열 탐색 한계였다. worker 파이프라인과의 중복 비교표는 CLEANUP_PLAN §6 |
| `vigent-core/ml/safety_pipeline.py` · `rfdetr_detect.py` · `rfdetr_zone_track.py` | "§5 통합 MVP"·"최소 동작" — **초기 프로토타입**으로 보이며 현 `worker.py`가 대체. 참고용 보존인지 삭제 대상인지 |
| `vigent-core/ml/vlm_risk_summary.py` | ★**정정 → [핵심-선택]**: 런타임이 직접 import한다(`rfdetr_service.py:215`, `scene_vlm.py:82`, `tests/test_vlm_format_facts.py`). **격리·이동 금지**(3단계에서 `ml/` 밖 코어로 옮기는 안만 검토) |
| `ml/pose_features.py` · `posture_model.py` · `bootstrap_labels.py` · `retrain.py` · `ingest_coco_keypoints.py` | ★**추가 발견 — fitness 군집과 한 덩어리**: `pose_features`를 import하는 곳은 `ml/` 안의 이 8파일뿐(✅ grep, 코어 `ergonomics.py`·`worker.py`는 **미사용**). 자세-위험 분류기(TensorFlow/Keras, TF.js export) 계열 = office/sports 잔재. → B의 fitness 6파일과 **함께 격리** 제안(대표 추가 승인 필요) |
| `ml/train_{fire,forklift,ppe}.py` · `eval_accuracy.py` · `compare_models.py` | 학습·평가 도구 → ③에 따라 `training/` 집결 대상(3단계). `train_fire·forklift`는 ultralytics(AGPL) 의존 |
| `ml/rtsp_test.py` · `make_test_video.py` | 유틸 — `tools/` 이동 후보(3단계) |
| `tools/train_merged.py` · `tools/train_safety.py` · `tools/train_monitor.py` · `tools/prelabel.py` · `tools/ml/*` | 학습 도구(질문③) |
| `benchmarks/e1_bottleneck/`(46파일) · `rig_fall/`(10) | rig_fall은 **삭제된 낙상 기능**의 벤치로 보임(CLAUDE.md "낙상 기능 제거") — 기록 보존인지 |
| `runs/rfdetr/accident/KakaoTalk_*.mp4`(9) | "사고 영상" — 출처·촬영 동의·활용 계획 미확인. 사람이 찍혔을 가능성 |
| `runs/site01_eval/site1/*.jpg`(21+3) | 고객사 프레스 공장 — 규칙10 "고객사 설비 24장". 계약상 보관 가능 여부 |
| `business_assets/` · `footage/` · `logs/` · `datasets/`(일부) | 작업트리에 있으나 gitignore — 내용 미확인, 저장소 밖 관리 대상인지 |
| `legal_whitelist.py` · `config/corpus/`(5) · `eval/golden`(27) · `datasets/goldens`(26) | 에이전트(위험성평가) 범위 — 질문② |
| `실행/` 폴더(한글 이름) | macOS 런처만 들어 있음 — 폴더째 정리 대상? |
| `VIGENT 상용화 준비 체크리스트.md`(루트) | `.gitignore` `/VIGENT *.md` 규칙 대상인데 추적됨(추적 후 규칙 추가) — 유지 여부 |

---

## 5. Mac → Windows 이전 이슈 표 (항목별 전수 점검)

| # | 항목 | 발견 | 위치·상세 |
|---|---|---|---|
| 1 | `.DS_Store` / `__MACOSX` / `._*` / `Icon\r` | ✅ **없음** | 추적·작업트리 모두 0건 |
| 2 | 하드코딩 mac 경로 | ⚠ **있음(11+)** | ★실행 영향: `scripts/setup_worktree.sh:13` `/Users/nohyeonseong/Desktop/VIGENT` 기본값 · `README.md` `/opt/anaconda3/bin/python3`(4곳) · `CLAUDE.md:80` `~/Desktop/VIGENT` · `vigent-core/main.py:12` docstring `cd ~/Desktop/VIGENT`. 기록물(실행 안 함): `benchmarks/train_logs/**/training_config.json·args.yaml`(`/Users/nohyeonseong/…` 8곳) |
| 2′ | ★**Windows 개인 경로 하드코딩**(역방향 문제) | ⚠ 있음 | `benchmarks/tapo_test_eval/tp_eval.py:32`·`tp_classes.py:13` `C:/Users/shgus/OneDrive/바탕 화면/tapo_test` · `benchmarks/results/c2_onnx_cpu_bench.json` 스크래치패드 경로 |
| 3 | 경로 `/` 문자열 결합 | ✅ **실질 0건** | 코어·스크립트 `Path(` 사용 89파일, `os.path.join` 0. grep 적중은 URL·출력문·dict 키뿐 |
| 4 | 대소문자 불일치 import | 🟡 **미검사** | Windows도 대소문자 무시 FS라 **Windows에선 안 깨짐**. Docker(Linux)·systemd 배포 시 문제될 수 있어 3단계에서 검사 권장 |
| 5 | 줄바꿈 CRLF/LF | ⚠ **혼재** | 추적 텍스트 701 중 **CRLF 517 · LF 170 · 혼재 2**. `core.autocrlf=true` · `.gitattributes` **없음** → 커밋마다 "LF will be replaced by CRLF" 경고 발생 중(실제 관측) |
| 6 | 셸 스크립트 | ⚠ **9개 + .command 5개** | `run.sh`(★README 공식 실행법) · `bin/*.sh`(3) · `cloud/*.sh`(2) · `deploy/watchdog.sh` · `scripts/setup_worktree.sh` · `training/watch_progress.sh`. Windows 대응은 `deploy/windows/*.ps1`(서비스 설치)뿐 — **개발용 실행 스크립트(.ps1/.bat) 없음** |
| 7 | 가상환경 커밋 | ✅ 없음 | `.venv/`·`venv/` 미추적 |
| 8 | mac 전용 휠·패키지 | ✅ 없음 | `tensorflow-macos`·`tensorflow-metal`·`pyobjc` 0건. torch==2.12.0은 플랫폼 휠 별도(README 주석) |
| 9 | `open()` encoding 미지정 | 🟡 **실질 1건** | `vigent-core/agents/guard.py:625`(track_debug 기록 열기 — 바이너리/텍스트 여부 확인 필요). 나머지 4건은 PIL `Image.open`·JS 오탐. ★별도로 **cv2.imwrite 한글경로 무언 실패**는 이미 실측·대응됨(`_imwrite` 3벌 — §4 중복 참조) |
| 10 | 한글 경로·파일명 | ⚠ 상존 | OpenCV가 한글 경로 영상을 못 열어 ASCII 임시 복사로 우회 중 · NFC/NFD 정규화 불일치 실측(docs/review/06). `실행/` 한글 폴더명 |
| 11 | 심볼릭 링크 / chmod | ⚠ 1건 | `vigent-core/ml/merge_retrain_data.py:79` `os.symlink`(Windows 관리자 권한/개발자 모드 필요) — 관련없음 후보 파일 |
| 12 | 카메라 백엔드 | ✅ 문제 없음 | `CAP_AVFOUNDATION`·`CAP_DSHOW` 하드코딩 0건(OpenCV 기본 백엔드). 현장(Windows) 실측 정상 |
| 13 | 추론 디바이스 | ⚠ **학습 스크립트 6곳** | `vigent-core/device.py`는 cuda→mps→cpu 자동 선택 ✅. 그러나 `ml/train_{fire,forklift,ppe}.py` 기본 인자 `"mps"`, `ml/{eval_accuracy,rfdetr_detect,rfdetr_zone_track,train_retrain}.py` `mps if available else cpu` — Windows에서 CUDA를 **못 쓰고 cpu로 떨어짐** |
| 14 | mac 명령(`open`·`say`·`pbcopy`·`osascript`) | ✅ 없음 | 0건 |
| 15 | 환경변수 `$HOME` | ✅ 실질 없음 | docstring 1곳 |
| 16 | 폰트 | ⚠ | 문서 생성기가 "맑은 고딕"(Windows 전용)을 하드코딩 — 역방향(Linux/Mac에서 깨짐) |

---

## 6. 실행·테스트 결과 (✅ 이번 감사에서 실제 실행)

| 항목 | 결과 |
|---|---|
| 의존성 설치 | **미시도** — 현재 환경에 이미 설치돼 있어 "깨끗한 환경 설치"는 5단계 몫. 새 venv 설치 시도는 승인 후 |
| 서버 기동 | **미시도(승인 필요)** — 카메라·가중치 필요. 단 `/health` 게이트·소크 기록은 `audit/`에 다수 존재 |
| 단위 테스트 | ✅ **`Ran 481 tests in 104.588s — OK`** (Python 3.11.9, Windows) |
| 정적 게이트 | ✅ 직전 커밋 시점 ruff 0 / mypy 0 / OpenAPI 무변경 / 프로파일 드리프트 0 (2026-09-03 실행 기록) |
| 커버리지 | ❌ **미측정** — coverage 도구 없음(전수 검색) |

---

## 7. 발견된 즉각적 오류·문제 목록

| # | 심각도 | 문제 | 근거 |
|---|---|---|---|
| 1 | 높음 | **Python 버전 3중 불일치**(3.11.9 / 3.13.9 / 3.13) — 개발과 CI가 다른 버전 | §2-2 #1 |
| 2 | 높음 | **README가 macOS 전용** — Windows 개발자가 그대로 따라 할 수 없다 | `README.md` 12~37행 |
| 3 | 높음 | **개인정보·고객사 이미지가 git 이력에 있음**(얼굴 9 · 설비 24 · 사고 영상 9) — 비공개라 노출은 없으나 규칙10 보류 상태 | §3-2 · `docs/public_release_checklist.md` |
| 4 | 중간 | `.gitattributes` 부재 + CRLF/LF 혼재 517/170 | §5 #5 |
| 5 | 중간 | 삭제된 테마(office/sports) 잔재 코드 **≥14파일**이 `vigent-core/ml/`에 남아 코어처럼 보임 | §4 관련없음 |
| 6 | 중간 | CLAUDE.md·SAFETY_REVIEW의 낡은 사실(55 tests·302줄·mac 경로·F6 "미조치") | `docs/review/05_문서불일치.md` 6건 |
| 7 | 중간 | `.gitignore` 규칙과 모순되게 추적된 파일(루트 `.command` 2개, `VIGENT *.md` 1개) | §4 |
| 8 | 중간 | 동명 파일 `tools/ppe_eval.py` / `tools/ml/ppe_eval.py` | §4 중복 |
| 9 | 낮음 | 측정 코드가 제품 로직을 복제(`hysteresis_sweep`)·유틸 3벌 복붙 | §4 중복 |
| 10 | 낮음 | 학습 스크립트 `"mps"` 기본값 6곳 | §5 #13 |
| 11 | 중간 | **프론트 LLM 버튼이 존재하지 않는 엔드포인트를 호출** — `static/realtime_core.js:3122` → `POST /llm/vision`. 서버 라우터·`baseline_openapi.json` 어디에도 `/llm/vision` 없음(✅ grep 0건) → 버튼 누르면 404 | §9-d |
| 12 | 낮음 | `realtime_core.js:3065·3088·3106` 브라우저→api.anthropic.com/openai/gemini **직접 호출 함수 3개**(구모델명 `claude-3-5-sonnet-20241022`·`gpt-4o` 하드코딩). 호출부 0건 = 죽은 코드. 키는 UI 입력(`llmApiKey`)이며 **하드코딩 키 없음** | §9-a |
| 13 | 낮음 | `scripts/golden_score_checklist.py`·`golden_score.py`가 인자를 무시하고 `--help`에도 채점을 실행·파일을 씀(부작용) | §9-e |
| — | (참고) | 코드 결함 원장은 별도: `SAFETY_REVIEW_REPORT.md`(F3·F9·F13 미해결) · `docs/review/04_계열사냥.md` | 4단계에서 다룸 |

---

## 8. 대표 판단 반영표 (2026-09-06 답변 → 처리 방침)

| 구분 | 항목 | 대표 결정 | 반영 위치 |
|---|---|---|---|
| A① | 프로젝트 정의 | 확정 | §1-1 |
| A② | 에이전트 | 의도된 기능 · 부가(선택 모듈) 판정 · 자산 보존 | §1-1 · §9 · CLEANUP_PLAN §4(requirements 분리) |
| A③ | 학습 도구 | `training/` 격리, 별도 repo는 기술 부채 | CLEANUP_PLAN §3-3 |
| B | `ml/boda/` 9 | 격리 → `_archive/themes/boda/` | CLEANUP_PLAN §3-1 |
| B | fitness 6(+제안 5) | 격리 → `_archive/themes/fitness/` | CLEANUP_PLAN §3-1 |
| B | ergo 4 | **보류**(4단계 포즈 스레드 확인 후) | §4 · 4단계 |
| B | mac 런처 5 + launchd 2 + mps_bench | ❓**대표 미기입**(`deploy/macos/` 이동 vs `_archive/macos/`) — 어느 쪽이든 Windows 스크립트 신규 | CLEANUP_PLAN §3-4 · §9(결정 대기) |
| C | `safety_manager.py` | 비교표 먼저 → 대표 결정 | CLEANUP_PLAN §6 |
| C | `ml/safety_pipeline·rfdetr_detect·rfdetr_zone_track` | **삭제**(커밋 메시지에 복구 hash) | CLEANUP_PLAN §3-2 |
| C | `benchmarks/rig_fall/` 10 | **삭제**(동일) | CLEANUP_PLAN §3-2 |
| C | `tools/ppe_eval.py` vs `tools/ml/ppe_eval.py` | diff 후 병합안 → `tools/ml/` | CLEANUP_PLAN §7 |
| C | `실행/` | mac 런처만 확인됨(✅ 2파일) → B와 함께, 폴더 제거 | CLEANUP_PLAN §3-4 |
| C | `VIGENT 상용화 준비 체크리스트.md` | 유지, `docs/` 이동 | CLEANUP_PLAN §3-5 |
| D | 미디어·개인정보 | `../vigent_private_data/` 이동 + `VIGENT_DATA_DIR` + `.gitignore` · **이력 재작성 안 함** · fixtures 최소 | CLEANUP_PLAN §5 |
| D | 원격 push 여부 | ✅ **push된 적 있음** — `origin`=github.com/nohhyunseong1-hash/vigent, 민감 커밋 `2a98fa9`·`b9e8289` 모두 `origin/main`·`origin/fix/review-bugs`에 포함(비공개 저장소) | FINAL_SUMMARY 별도 섹션 예정 |
| E | `docs/복구_폴라리스캐시/` | 커밋 금지 · `.gitignore` | CLEANUP_PLAN §3-6 |
| E | `docs/review/` · `docs/사업계획서 양식.docx` | 설명·권고 보고 | CLEANUP_PLAN §3-6 |

---

## 9. 추가 점검 — AI 에이전트(LLM) 실행 방식 (A②(a)~(e))

### 9-a. LLM 실행 방식 판별 (✅ 코드 근거)

**결론: "여러 방식 혼재". Qwen3.6·Ollama·로컬 transformers 직접 로드는 없다.**

| 경로 | 방식 | 근거(파일:줄) | 모델·엔드포인트·키 |
|---|---|---|---|
| ⓐ 텍스트 추론(종합의견·사고분석 종합) | **외부 API 호출** | `vigent-core/llm_provider.py:24` `_DEFAULT_PROVIDER="openai"` · `:86-104` `openai.OpenAI()` · `:62-83` `anthropic.Anthropic()` | 모델 env `OPENAI_MODEL`(기본 gpt-4o-mini) / `VIGENT_LLM_MODEL`(기본 claude-opus-4-8). 키 = `.env`의 `OPENAI_API_KEY`·`ANTHROPIC_API_KEY`(✅ `.env`는 gitignore, 추적 0건, `.env.example`엔 이름만). **코드 내 하드코딩 키 0건** |
| ⓑ 비전(프레임 1장) 클라우드 | 외부 API, **이중 opt-in** | `llm_provider.py:107-144` `reason_vision` — `VIGENT_CLOUD_VLM=1` **and** 키 있을 때만, 전송 전 `privacy.anonymize_faces` | `OPENAI_VISION_MODEL`→gpt-4o-mini |
| ⓒ 비전 로컬 | **로컬 직접 로드(Apple 전용)** | `ml/vlm_risk_summary.py:154-160` `from mlx_vlm import load` · `rfdetr_service.py:204-255` `VLMService`(전용 고정 스레드, F-14) · `vlm_confirm.py` · `incident.py:66` | 모델 `themes/safety/vision.yaml:99` **`mlx-community/Qwen2.5-VL-7B-Instruct-4bit`**(코드 기본 3B). 가중치 = HF 캐시(경로 미고정, `~/.cache/huggingface` 기본). device = MLX(Apple Metal) 고정, 양자화 4bit. **Windows 불가**(`requirements-optional.txt:6-9` "Apple Silicon 전용" 명시, `mlx` 미설치 시 `available=False` 조용히 폴백) |
| ⓓ 프론트 직접 호출(죽은 코드) | 브라우저→외부 API | `static/realtime_core.js:3065·3088·3106` (Claude/OpenAI/Gemini) — 호출부 0건. 실제 버튼은 `:3122` `POST /llm/vision`인데 **서버에 라우트 없음** | 키 = 화면 입력창 `llmApiKey`(`:3198`). 구모델명 하드코딩 |
| ⓔ 구 BODA 에이전트(격리 대상) | 외부 API(urllib 직접) | `ml/boda/{safety_agent,fitness_agent}.py:114·155` `https://api.anthropic.com/v1/messages` | `AX_VLM_PROVIDER`·`ANTHROPIC_API_KEY` env. 코어 미사용 |
| RAG 임베딩(선택) | 로컬 sentence-transformers | `safety_rag.py:146-160` 미설치 시 bigram 폴백 | `jhgan/ko-sroberta-multitask` ~400MB HF 캐시 |

**부가 판정 근거**: 이 PC(Windows)에는 `openai`·`anthropic`·`mlx` 모두 **미설치**(`pip list` ✅)인데 481 테스트 통과 · 서버 코어(`app_state.py:14`)가 `agents` 패키지를 import하지만 에이전트 내부의 LLM 호출은 전부 지연 import + 예외 삼킴이라 **키·패키지 없이 감시 서버가 단독 실행**된다.

**Windows에서 이 기능을 살리기 위한 환경 (실측 기반)**

| 항목 | 현재 이 PC | 필요 |
|---|---|---|
| GPU/CUDA | ✅ RTX 5070 Ti 16GB · torch 2.12.0+**cu130** · CUDA 가용 True(`torch.cuda.is_available()`) · 드라이버 610.74 | — |
| ⓐ 텍스트 LLM(클라우드) | `openai`/`anthropic` 미설치 | `pip install openai==2.44.0 anthropic==0.115.1` + `.env` 키. VRAM 불필요 |
| ⓒ 로컬 VLM | mlx 불가 | **대체 구현 필요** — 선택지: (1) transformers+CUDA로 Qwen2.5-VL-7B 4bit 로드(추정 VRAM 6~8GB, **미측정**) (2) vLLM/LM Studio 로컬 OpenAI 호환 서버 + `llm_provider`에 `base_url` 옵션 추가 (3) 클라우드 비전만 사용(`VIGENT_CLOUD_VLM=1`). 현 코드엔 (1)(2) 어느 것도 없음 → **신규 작업**(4단계 이후) |
| RAG 임베딩 | 미설치(bigram 폴백 중) | `sentence-transformers==5.6.0`(CPU 가능) |

### 9-b. Windows에서 깨지는 부분 (LLM·모델 경로)

| 위치 | 내용 |
|---|---|
| `ml/vlm_risk_summary.py:101` · `rfdetr_service.py:224·242` | `Path("/tmp")` 하드코딩 — Windows엔 `/tmp` 없음(`tempfile` 대체 필요) |
| `ml/vlm_risk_summary.py:154` · `vlm_confirm.py` · `rfdetr_service.py:215` | `mlx_vlm` import — Windows 미설치 → 조용히 `available=False` |
| `config/settings.yaml:7·35·52` | `device: "mps"` 3곳 — ✅ 읽는 코드 없음(train_fire/ppe docstring 언급뿐) → **고아 설정 파일** |
| `ml/train_{fire,forklift,ppe}.py` · `training/{rfdetr_train,rfdetr_smoke,mps_bench}.py` · `tools/train_merged.py` | 기본 device `"mps"` |
| `~/.cache/huggingface` 절대경로 | ✅ 하드코딩 없음(HF 기본 캐시에 의존) · `/Applications` 0건 · `RF_HOME` env 1건(정상) |
| 프롬프트 | 파일 내 상수: `incident.py:14` `_ACCIDENT_PROMPT` · `behavior.py:57` · `scene_vlm.py:19` · `vlm_confirm.py:17-` `CONFIRM_PROMPTS` · `routers/safety_core.py:126` · `vlm_risk_summary.py:20`(이것만 `vision.yaml`로 덮어쓰기 가능) |

### 9-c. 모델 가중치 커밋 여부 (✅ 이력 전수)

`git log --all --diff-filter=A -- '*.safetensors' '*.gguf' '*.bin' '*.pt' '*.pth' '*.onnx' '*.ckpt'` → **0건**. 가중치는 작업트리·이력 어디에도 커밋된 적 없다. (`vigent-core/weights/*` gitignore, `weights_manifest.json`+`scripts/fetch_weights.py`로 배포 시 다운로드·SHA 검증.)

### 9-d. 하드코딩 → 설정/환경변수 이관 대상

| # | 위치 | 내용 | 이관 제안 |
|---|---|---|---|
| 1 | `themes/safety/vision.yaml:99` · `deploy/academy/vision.academy.yaml:89` | VLM 모델 `mlx-community/Qwen2.5-VL-7B-Instruct-4bit` | 이미 yaml(양호). 백엔드 종류(mlx/transformers/openai-compatible) 키 추가 필요 |
| 2 | `llm_provider.py` | 엔드포인트 = SDK 기본(api.openai.com / api.anthropic.com). `base_url` 주입 없음 | `OPENAI_BASE_URL` 지원 → vLLM·LM Studio 로컬 서버 연결 가능 |
| 3 | 프롬프트 6곳(9-b 표) | 파일 상수 | `config/prompts.yaml` 한 곳 |
| 4 | `static/realtime_core.js:3075·3093·3107` | `claude-3-5-sonnet-20241022`·`gpt-4o`·`gemini-2.0-flash-lite` | 죽은 코드 → 삭제(4단계) |
| 5 | `static/console_terminal.html:141-142` | 표시용 문자열 "gpt-4o · MLX" | `/health`의 `llm.model` 실값 표시로 |
| 6 | `ml/vlm_risk_summary.py:101`·`rfdetr_service.py:224·242` | `/tmp` | `tempfile.gettempdir()` |

### 9-e. `eval/golden` 평가 스크립트 실행 가능 여부 (✅ 실제 실행)

| 스크립트 | 결과 | 비고 |
|---|---|---|
| `scripts/golden_score.py` | ✅ 실행됨 — "item_01_crane 총점 89점" 출력 | 인자 무시(`--help`에도 채점 실행) |
| `scripts/golden_score_checklist.py` | ✅ 실행됨 — 분리지표 3/3 출력, `eval/golden/item_01_crane_checklist_score.md` **재작성**(내용 동일 → git 무변경 확인) | `--help`에도 파일을 씀(부작용) |
| `scripts/golden_regression.py` | ✅ `--help` 정상 | 실행 시 `regression_baseline.json` 갱신 옵션 있음 |
| `datasets/goldens/T1/*.py` 4개 | 미실행(전문가 채점표 생성·병합 도구) | 의존성 표준 라이브러리로 보임 |

의존성: `legal_whitelist`·`agents.copilot`·`agents.scribe`만(LLM 키 불필요, 규칙 기반) → **Windows에서 그대로 실행 가능**.

---

## 10. 남은 결정 (★2단계 계획서와 함께 대표 확인)

1. **B mac 런처**: `deploy/macos/`(재배포 가능성 있음) vs `_archive/macos/`(없음) — **미기입**. 기본안은 `_archive/macos/`(가역).
2. §4 추가 발견 **pose 군집 5파일**(`pose_features`·`posture_model`·`bootstrap_labels`·`retrain`·`ingest_coco_keypoints`)을 fitness와 함께 격리할지.
3. `config/settings.yaml`(읽는 코드 0건, mps 3곳) 격리 여부.

> 계획서: [CLEANUP_PLAN.md](CLEANUP_PLAN.md). **아직 어떤 파일도 이동·삭제하지 않았다.**
