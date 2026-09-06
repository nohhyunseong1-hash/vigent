# CODE_REVIEW.md — 4단계 정밀 코드 리뷰 (감사 2026-09-06)

> 대상 브랜치 `audit/cleanup-20260906` (3단계 완료 HEAD `aab7d05` 이후). 방식: 모듈 단위로 **전체 읽기 → 보고 → 승인 → 수정(테스트 선행) → 게이트(ruff·mypy·OpenAPI·481 unittest) → 커밋**.
> 범위(CLEANUP_PLAN §10 범위 결정 2차): 비전(감시 서버 코어)만 정밀 리뷰. `agents/`는 치명(비밀정보 노출·코어를 깨뜨리는 import)만.
> 원칙: 모든 지적은 **파일:줄 근거**를 달고, 수치는 실행·측정한 값만 적는다. 추측은 "추측/미검증"으로 표기.
> ※ 2026-07-15의 1차 검토 보고서는 [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md)(P0~P2 조치 완료)이며 이 문서와 별개다.

## 0. 등록 항목 (1~3단계에서 넘어온 것) — 현황표

| # | 등급(등록 시) | 항목 | 출처 | 담당 모듈 | 현황 |
|---|---|---|---|---|---|
| R1 | **치명** | 서비스 크래시 루프 3주 미감지(4,067회 재시작) — 기동 실패 알림 / NSSM 재시작 제한 / `service_status.ps1` 회전 파일 증가 검사 | audit/c4_smoke §3·§5 | 4(통보)·7(기동) | 대기 |
| R2 | **치명/높음** | 프론트 `realtime_core.js:3122` → `POST /llm/vision` 404(죽은 버튼) | AUDIT §9-d | 8(프론트) | 대기 |
| R3 | **치명(범위 규칙)** | `agents/`는 비밀정보 노출·코어 파괴 import만 점검 | CLEANUP_PLAN §10 | 전 모듈 공통 | 3단계 C4 비밀 스캔 0건 · C9 선택 import 완료. 4단계 중 추가 발견 시 기재 |
| R4 | 높음 | W1 rf-detr `_kp_active_mask` 부분 로드 경고(3슬롯 공통) | c4_smoke §2 W1 | 1 | ★**정정 → 낮음(영향 없음)**. §1 M1-2 실측 근거 |
| R5 | 중간 | forklift 설계상 비활성(F-7)로 `/health status=degraded` | c4_smoke §1·§6 | 1 | ★**정정 → 사유 오판**. degraded 실제 사유는 미전송 경보 pending 15건(§1 M1-3). 후속은 모듈 4 |
| R6 | 중간 | 골든 스크립트 `--help` 부작용(파일 생성) | AUDIT §9-e | agents 자산 → 코드 무수정, 문서 기재만 | 대기 |
| R7 | 중간 | W5 개발 런처 `RF_HOME` 기본값이 사용자 프로필(`~/.roboflow/models`) — 저장소 `vigent-core/weights` 고정 여부 | c4_smoke §2 W5 | 7 | 대기 |
| R8 | 보류 | `safety_manager.py` UI 연결 여부 | CLEANUP_PLAN §6 | (agents 범위 밖) | 보류 유지 |
| R9 | 보류 | ergo 4파일(`ml/ergonomics.py` 등) — 포즈 스레드는 살아 있음(`worker.py:1069`), 경보·저장까지 이어지는지 | AUDIT §4 | 2(규칙) | 대기 |
| R10 | 낮음 | W2 rf-detr `num_classes` 미전달 경고 | c4_smoke §2 W2 | 1 | §1 M1-9 |
| R11 | 낮음 | CI Python 3.13 vs `.python-version` 3.11.9 | AUDIT §2-2 | 7 | 대기 |
| R12 | 낮음 | C1 unittest 1회 flaky(이름 미포착, 이후 8회 연속 OK) | 3단계 | 게이트 공통 | ★**이름 포착·원인·수정(2026-09-06 run3)**: `test_readiness_warmup.TestWarmup.test_on_ready_not_called_when_warmup_fails`('ready' != 'failed'). 로그 `audit/unittest_flaky_2026-09-06_run3.log`. 원인 = `test_endpoints_smoke`가 TestClient startup 으로 띄운 **실모델 예열 스레드**("vigent-warmup", 20초+)가 자기 모듈이 끝난 뒤에도 살아 전역 readiness 상태에 READY 를 덮어씀(테스트 격리 결함, 제품 결함 아님). 단독 실행 3/3 통과. 수정: 해당 모듈 setUp 에서 잔존 예열 스레드 join. C1 때 실패가 같은 테스트였는지는 **미확인**(당시 이름 미포착) |
| R13 | 낮음 | `training/train_merged.py`·`train_monitor.py` mac 경로·mps 기본값 | C3 | (training 범위 밖) | 문서 기재만 |
| R14 | **치명** | 테스트 스위트가 운영 `data/`(alert_queue.db·evidence·recognition·risk_assessments)에 쓴다 — notify.yaml 설정 PC 에서는 시험 문구가 실제 텔레그램으로 발송 가능 | §4-0 ④ 실측 | 테스트 격리 | ✅ **수정 완료**(커밋 `[CODE_REVIEW ④]`): `tests/_isolate.py` + 9개 모듈 적용. 검증 = data/ 28,815파일 sha256 전후 비교 **추가 0·변경 0**(격리 전엔 +3 파일·1 변경) |
| R15 | 중간 | 카메라별 무동작 임계값(45s/0.03) 설정화 — 앉아 작업 현장 오경보 방지(M2-7) | §2 M2-7 | 7(설정) | 대표 등록 2026-09-06. 하드코딩 상수 7개(§2-3)와 함께 모듈 7에서 설정 모듈로 |
| R16 | **FINAL_SUMMARY 1순위군** | 중장비 협착 규칙이 forklift 를 장비로 못 본다(F-7 슬롯 비활성 → COCO car/truck/bus/motorcycle 만) — "forklift 슬롯 활성화 또는 대체 감지 경로"를 Windows VLM 대체와 같은 1순위군으로 | §2-1 협착 행 | (범위 밖) | FINAL_SUMMARY 에 기재 |

---

## 1. 모듈 1 — 감지 파이프라인 (guard.py · rf-detr 로드/슬롯 · 초당 2회 스케줄링)

**읽은 파일(전체)**: `vigent-core/agents/guard.py`(1,015줄) · `detectors/{base,rfdetr_adapter,yolo_adapter}.py` · `rfdetr_service.py` · `isolated_detect.py` · `health_status.py` · `device.py` · `app_state.py` · `readiness.py`(예열) · `worker.py`의 캡처·루프·`_process_frame`·감독자·hang 감시 부분(1~130 · 500~1164) · `routers/detect.py`·`routers/system.py`(/health) 호출부 · rfdetr 1.8.0 라이브러리 `models/lwdetr.py`·`models/weights.py`·`config.py`(W1 원인 확인용).

**스케줄링 확인(정상)**: 워커 루프 간격 `_interval=1/fps`(기본 2fps=0.5s, `worker.py:649·1004·1152`) · 풀세트(person+ppe+fire) 주기 `_full_interval=max(interval, 1/fullset_fps)`(`worker.py:1066`, tuning `worker.fullset_fps: 2`) · 포즈 2fps 별도 스레드(`worker.py:71·815`) · 확대뷰 포커스 시 person+ppe 고속 경로는 표시 전용이고 판정 입력은 풀세트만(`worker.py:862~923`). 검출 호출은 `DETECT_LOCK`(RLock) 직렬화 — 워커(`worker.py:875`) · `/detect/frame`(`routers/detect.py:138`) · `/safety/voice/scene`(`safety_core.py:488`). ★예외 1건 = M1-4.

### 1-1. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| M1-1 | `agents/guard.py:48-57` (`_guard_logger`) · 호출 `:872·877·908·913·919·653` | **높음** | `_guard_logger()`가 호출될 때마다 `sys.path.insert(0, …)` → **sys.path 무한 증가**(메모리 누적 + 이후 모든 import 가 늘어난 경로를 선형 탐색). 추론 실패 경로(`:908`)는 **실패 프레임마다** 호출되므로 슬롯이 죽은 채 운영되면 2fps 기준 하루 17만 개 항목이 쌓인다 | 실측: `_guard_logger()` 100회 호출 → `len(sys.path)` **7 → 107**(scratchpad `w1_probe.py`, 2026-09-06). 같은 패턴 `_pick_device`(`:451-455`, 인스턴스당 1회라 실해는 없음) | 모듈 로드 시 1회만 vlog import(try/except) 하고 로거를 모듈 전역에 캐시. `_pick_device`도 같은 방식으로 정리. 테스트: 호출 100회 후 `sys.path` 길이 불변 |
| M1-2 | (등록 R4) rfdetr 1.8.0 `models/lwdetr.py:197·244-253·397-412`, `models/weights.py:182·490-513`, `config.py:135·141` | 높음 → **낮음(정정)** | W1 경고 "`_kp_active_mask` … left at random init"는 **오해를 부르는 문구**다. 이 텐서는 학습 파라미터가 아니라 `num_keypoints_per_class`에서 **결정적으로 생성되는 buffer**(`register_buffer`)이며, 검출 전용 모델(`use_grouppose_keypoints=False`, 스키마 `[]`)에서는 형상 `(0,0)`이고 키포인트 부스트 함수가 스키마가 비면 **0을 반환**(`lwdetr.py:399-404`)해 클래스 로짓에 아무 영향이 없다 | 실측(ppe 슬롯 로드, cpu): `num_keypoints_per_class=[]` · `use_grouppose_keypoints=False` · `_kp_active_mask.shape=(0,0)`. 체크포인트 키 검사: 커스텀 3종(.pth)은 키 **있음**(466키), 베이스 `rf-detr-nano.pth`는 **없음**(465키) → person 슬롯은 missing, 커스텀은 형상 불일치로 drop(`weights.py:495-510`) 후 missing → 3슬롯 공통 경고. 어느 쪽도 **정확도 영향 없음** | 코드 수정 불필요. c4_smoke §2 W1 문구("1개 랜덤 초기화") 정정 + 이 표로 종결. (선택) 어댑터에서 해당 경고를 필터해 로그 소음 제거 |
| M1-3 | (등록 R5) `health_status.py:108-140` · `routers/system.py:141-154` · `data/alert_queue.db` | 중간 → **사유 정정** | c4_smoke §1의 "degraded 사유 = forklift 비활성"은 **추론 오류**였다. `health_status.overall()`은 `disabled_detectors`를 **읽지 않는다**(입력: 카메라 판정·모델 로드·`alert_backlog`·`slot_degraded`). 실제 사유는 **미전송 경보 backlog** | 실측 `data/alert_queue.db`: **pending 15건**(2026-08-28 14:16~20:12) · dead 35 · sent 37 → `alert_backlog=15>0` → DEGRADED(`health_status.py:138`) | 상태 분류 수정 **불필요**(설계대로 동작). 후속: pending 15건이 **9일째 재시도·데드레터 처리되지 않음** → 모듈 4(통보) 항목으로 이관(M4-예약). c4_smoke §1·§6 정정 |
| M1-4 | `readiness.py:122-127` (warmup) · `:144-153` (백그라운드 스레드) | **중간** | 예열 스레드가 `guard.detect()`를 **DETECT_LOCK 없이** 호출한다. 예열 중 서버는 이미 응답 중이라 `/detect/frame`(락 보유)이 동시에 같은 슬롯의 지연 로드(`guard.py:802-828`)에 진입할 수 있다 → 같은 모델 **이중 로드**(VRAM 2배) 또는 `rfdetr_adapter.py:35-53`이 기록한 **부분 초기화 import 경합**(`_preload_supervision`는 완화책일 뿐 완전 차단 아님). `_tracks_by_key`·`_predict_fail_streak` dict도 무락 동시 변경 | 코드 경로 확인(호출부 4곳 중 유일한 무락 호출: `readiness.py:125`). 실제 발생 여부는 미측정(추측/미검증 — 창이 예열 시간 ~25s에 한정) | `warmup()`의 슬롯 루프를 `with app_state.DETECT_LOCK:`로 감싼다(RLock, 재진입 안전). 테스트: `guard.detect`를 모킹해 호출 시 `DETECT_LOCK._is_owned()`가 True인지 확인 |
| M1-5 | `agents/guard.py:688-689` (`_track_bytetrack`) | **중간(동작 변경 → 승인·측정 필요)** | person 검출이 0건인 프레임에서 `bt.update()`를 호출하지 않아 **트래커 시간이 멈춘다** → 사람이 화면에서 오래 사라져도 같은 tid가 부활(코드 주석 `:294-303`에 실측 11.55s 사례 기록, 백로그 PQ). 규칙 쪽(모듈 2·3)에서 tid 단위 쿨다운·디바운스 키가 옛 사람에 이어붙을 수 있다 | 주석의 자체 실증(update(empty) 20회 → 새 id / 미호출 → 동일 id) | 빈 `sv.Detections.empty()`로 매 프레임 update 호출. **추적 동작이 바뀌므로**(규칙 6·9) 수정 전 `benchmarks/track_ab_bytetrack.md` 재측정이 필요 → 대표 결정: 이번에 고칠지 / 백로그 유지 |
| M1-6 | `agents/guard.py:340-408` (`__init__` tuning 블록) | **중간** | 튜닝 블록 전체가 한 `try … except Exception: pass`(`:407-408`)로 감싸여 있어, `tuning.yaml`의 값 하나가 잘못되면(예: `ema: "abc"`) **그 줄 이후의 모든 설정이 조용히 기본값으로 남는다**(부분 적용, 로그 0줄). `ppe.required` 오타를 크게 드러내도록 고친 `:378-396`의 취지와 정반대 | 코드 구조(예외 발생 지점 이후 줄은 실행 안 됨) — 실측은 안 함(구조상 명백) | except 절에서 `_guard_logger().error("tuning 적용 중단: %s — 이후 항목은 기본값", ex)` + `status()`에 `tuning_warn` 노출. 기동은 실패시키지 않음. 테스트: `tuning.val`이 예외를 내게 모킹 → ERROR 로그·status 노출 확인 |
| M1-7 | `agents/guard.py:917-922` (복구 경로) · `routers/system.py:66-67` | 낮음 | 추론 실패 후 복구돼도 `_load_errors[slot]`(`:907`에 기록)을 지우지 않아 `/health slot_errors`에 **옛 오류 문자열이 영구 잔존**(복구됐는데 오류로 보임) | 코드 경로 | 복구 시 `self._load_errors.pop(slot, None)`(predict 계열만). 테스트: `test_slot_degraded.py`에 복구 후 `status()["load_errors"]` 비어 있음 추가 |
| M1-8 | `worker.py:846-851` | 낮음 | `_process_frame`의 docstring이 `if … return` **뒤**에 있어 docstring이 아니라 실행 없는 문자열 식(디버그 잔재·린트) | 코드 | docstring을 함수 첫 줄로 이동(포매팅 커밋으로 분리) |
| M1-9 | (등록 R10) `detectors/rfdetr_adapter.py:218` | 낮음 | W2 "Checkpoint has 10 classes but model is configured for 90" — `num_classes` 미전달. 라이브러리가 체크포인트 값으로 자동 정렬하므로(`weights.py:385-395`, 실측 `model_config.num_classes=10`, `class_embed.out_features=11`) **동작 영향 없음** | 실측 | 경고 소음만. 억제하려면 체크포인트 `args.class_names` 길이를 먼저 읽어 넘겨야 해(torch.load 2회) 비용 대비 이득 없음 → 문서 기재로 종결 권고 |
| M1-10 | `detectors/rfdetr_adapter.py:240` · `rfdetr_service.py:90·151` | 낮음 | `from rfdetr.util.coco_classes import COCO_CLASSES` — **deprecated 모듈**(1.6.0 deprecated, **1.9.0 제거 예정**). requirements가 1.8.0 고정이라 지금은 동작하나 업그레이드 시 즉시 ImportError | 라이브러리 `rfdetr/util/coco_classes.py:6-12` | `rfdetr.assets.coco_classes`로 교체(값 동일) |
| M1-11 | `detectors/base.py:47-48` · `rfdetr_adapter.py:278-279` | 낮음(모듈 3에서 재확인) | 세로형 입력의 un-pad 후 bbox를 [0,1]로 **클램프하지 않는다** → 음수/1 초과 좌표 가능. 소비처 중 픽셀 슬라이스(증거 크롭·모자이크)가 음수 인덱스를 받으면 파이썬 슬라이스가 **뒤에서부터** 잘라 엉뚱한 영역이 나온다 | 코드 경로(발생 빈도 미측정) | `finalize_box`에서 `min(max(v,0.0),1.0)` 클램프. 모듈 3(오경보/증거) 리뷰에서 privacy 크롭 경로 확인 후 함께 결정 |
| M1-12 | `rfdetr_service.py:224·242` | 낮음(Windows) | 로컬 VLM 임시 파일 `Path("/tmp")` 하드코딩 → Windows에선 `D:\tmp`(cwd 드라이브 루트)로 풀려 폴더가 없으면 `cv2.imwrite`가 **False를 돌려주고 아무도 확인 안 함**(규칙 11). 현재 로컬 VLM은 mlx(Apple 전용)라 Windows에선 애초 안 돎 | 코드 | Windows VLM 대체 구현(FINAL_SUMMARY 1순위) 때 `tempfile.gettempdir()` + imwrite 반환값 검사로 함께 수정 |
| M1-13 | `rfdetr_service.py:66-80` | 낮음 | `RFDetrService`가 guard의 person 슬롯과 **별개의 RFDETRNano(COCO)를 한 벌 더** 로드(지연). `/detect/rfdetr`·구역 타일(B9, 기본 off) 사용 시 nano 모델 2벌 상주 | 코드 | 현 상태 유지(지연 로드·기본 미사용). 문서 기재 |
| M1-14 | `worker.py:867` | 낮음 | `self._full_interval - 0.06` 매직넘버(루프 지터 허용치) | 코드 | 상수 `_FULLSET_SLACK_S = 0.06` + 주석. 포매팅 커밋 |

**확인했으나 문제 없음**: BGR→RGB 변환(`rfdetr_adapter.py:265`, PIL 입력 전 1회) · dtype/값 범위(uint8 프레임, ONNX 경로는 to_tensor→resize→normalize 순서 `rfdetr_adapter.py:148-150`) · None 프레임(`worker.py:1085·1142`에서 차단, 라우터는 디코드 실패 400) · device 하드코딩 없음(`device.py` 단일 소스, env 강제) · 루프 내 반복 로드 없음(`_get_model` 캐시) · `open()` encoding 미지정 없음(guard·worker 검토 범위) · bare except 없음(모두 `noqa: BLE001` 주석 달린 광역 except — M1-6만 사유 로그가 없음).

| M1-15 | `tests/*.py`(57개 파일, `sys.path.insert(0, <vigent-core>)` 64회) | 낮음(테스트 위생) | 모든 테스트 모듈이 각자 `sys.path` 에 같은 경로를 삽입 → 전체 스위트에서 `vigent-core` 경로가 60회 중복. 동작 문제는 없으나 M1-1 검증 때 절대 개수 검사를 못 하게 만든 원인 | 실측(run2: `sys.path.count(core)=60`) | `tests/conftest`형 공통 경로 설정(unittest 는 `tests/__init__.py` 또는 `discover` 시작 스크립트)으로 1회화 — 별도 정리 커밋(범위 밖, 백로그) |

### 1-2. 수정 계획 → 진행 현황(대표 조건부 승인 2026-09-06)
- **높음 M1-1**: ✅ 커밋 `2d8d218` — 1회·멱등 삽입 유지(cwd 가정 없음) + 캐시 + 폴백 WARNING. 3개 컨텍스트(저장소 루트 unittest / run.ps1 / NSSM cwd+env) 모두 backend=vlog, 101회 호출 sys.path 증가 0~1(최초). LocalSystem 계정 차이는 재현 불가.
- **중간 M1-4·M1-6·M1-7 + 낮음 M1-10**: 테스트 선행(신규 `test_warmup_holds_detect_lock.py`·`test_guard_tuning_partial_failure.py`·`test_slot_degraded.py` +1) → 수정 → 게이트 → 커밋(아래 커밋 목록).
- **중간 M1-5**: ✅ 수정(대표 승인 2026-09-06). 선행 테스트 4 → 측정 → 수정 → 재측정. 저장소 밖 영상 5개(multi_scene + refset 4, 숫자만 기록):

  | 영상 | 프레임(사람0) | 트랙 수 전→후 | 최대 수명 s | 평균 수명 s | ID 스위치 | 부활(≥1.0s 공백) |
  |---|---|---|---|---|---|---|
  | multi_scene | 497(1) | 19→19 | 20.67→20.67 | 2.42→2.42 | 1→1 | 0→0 |
  | multi_cross | 176(1) | 5→5 | 11.64→11.64 | 4.75→4.75 | 0→0 | 0→0 |
  | occlusion | 164(1) | 5→5 | 10.85→10.85 | 4.25→4.25 | 0→0 | 0→0 |
  | single_fast | 217(1) | 11→11 | 14.35→14.35 | 4.0→4.0 | 0→0 | 0→0 |
  | single_move | 84(1) | 1→1 | 3.46→3.46 | 3.46→3.46 | 0→0 | 0→0 |

  multi_scene 구간 지표(S1~S6 ID스위치·swap·신규트랙·가림후유지율)도 전후 동일. **해석**: 5개 영상 모두 사람 0명 프레임이 1개뿐이라 수정이 작용할 "부재 구간"이 없다 → **회귀 0은 입증, 효과는 이 영상으로 입증 불가**. 그래서 통제 실험을 추가했다(`--gap-demo`, 같은 코드에 구 동작을 몽키패치로 재현): multi_scene 앞 120프레임 → 검은 프레임 120개(**5.0s 부재**, lost 버퍼 1.25s) → 뒤 120프레임에서 앞 구간 tid 부활 수 — **구 동작 2/5 → 수정 후 0/5**.
- **낮음 M1-8·M1-14**: 포매팅 커밋 1개(로직 커밋과 분리).
- **정정 M1-2·M1-3·M1-9**: 코드 무수정, `audit/c4_smoke_2026-09-06.md` §1·§2·§6 정정 완료.
- **R12 flaky**: 이름 포착·원인·수정(§0 R12) — 테스트 전용 커밋.

---

## 2. 모듈 2 — 5개 감지 규칙 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `worker.py` 130~500(`_derive`·`MotionTracker`·`ErgonomicsTracker`·`_PoseModel`) · `proximity.py` · `zone_debounce.py` · `zone_tile.py` · `ergonomics.py` · `hazard_rules.py`(라이브 규칙 아님 — incident/scribe용, 범위 밖 확인만) · `alert_notify.py` · `agents/dispatcher.py`(등급 매핑 확인) · `config/tuning.yaml` · `themes/safety/vision.yaml judgment`.

**규칙 발화 경로(공통)**: 풀세트 프레임(2fps)마다 `_derive()`(`worker.py:197`) → `MotionTracker.update()`(`:954`) → 포즈 스레드 산출(`_pose_events`) 합류 → 규칙별 쿨다운 15s(`_COOLDOWN_S`, 주체 있으면 `rule|subject`) → `data_engine.log_event`(증거 JPEG는 규칙별 30s) → `alert_notify.submit`(통보 게이트 → 모듈 3·4).

### 2-1. 규칙별 한 줄 요약(발화 조건 / 억제 조건)

| 규칙 | 발화 | 억제 |
|---|---|---|
| **보호구 미착용 `ppe_missing`**(high) | ppe 슬롯 검출 라벨이 `PPE_REQUIRED`(기본 NO-Hardhat·NO-Safety-Vest·NO-Mask)에 있고, 그 박스가 person 박스와 결부(교차게이트)되며, 같은 카메라 키에서 **연속 3프레임**(`HYSTERESIS ppe_missing=3`) 유지 | 사람 없음(PPE 전부 폐기) · 클래스별 conf 미달(`ppe_per_class`) · 3프레임 미만 · 규칙 쿨다운 15s(주체 없음 = 카메라 단위) |
| **위험구역 `zone_intrusion`**(high) | 카메라별 구역(≥3점) 안에 person **발끝점**(`zone.reference=foot`)이 있고, 그 사람(tid 또는 격자키)이 **1.0s 연속**(`zone.enter_s`) 유지 → 확정 전이 시 1회 | 구역 미설정(전역 폴백 기본 off → 판정 안 함) · 장비 탑승자(포함률≥0.65) · tid 없고 `grid_cells=0`이면 판정에서 제외 · 이탈은 1.0s 유지 후 · 쿨다운은 **사람 단위** |
| **중장비 협착 `proximity_hazard`**(high) | `VEHICLE_REF_M` 클래스(forklift·truck·car·bus·motorcycle·crane·excavator) 박스와 person 박스 최단거리 × (장비 실폭 m / 박스폭) ≤ `radius_m` 3.0 → 카메라 단위 **0.4s 연속**(`proximity.enter_s`) 확정 전이 시 1회 | 장비 박스가 화면 대부분(폭>0.9 또는 면적>0.7) · 탑승자 · 해제는 1.0s · ★forklift 슬롯은 F-7로 기본 제외 → 현재는 **COCO car/truck/bus/motorcycle**만 장비로 잡힘 |
| **급격동작 `rapid_motion`**(mid) | 같은 사람(중심점 매칭 0.32)의 **1.0s 창** 첫·끝 샘플 거리 > `rapid_dist` 0.15(정규화) | 매 프레임 재판정 → 쿨다운 15s · 통보는 **mid 등급 → log 전용**(원격 통보 없음, 설계) |
| **무동작 `immobility`**(high) | 같은 사람 트랙이 **45s**(`immobile_s`) 이상 존재하고 최근 45s 창 샘플 ≥5개의 x·y 퍼짐 < 0.03 | 트랙 3s 미매칭이면 소멸(재시작) · 쿨다운 15s · 통보 게이트 |
| (부가) `crowd_density`(mid) / `fire_smoke`(critical) / `ergonomic_risk` | 인원 ≥6 / fire·smoke 연속 2프레임 / 나쁜 자세 3s 지속(포즈 스레드) | crowd·mid 는 log 전용 · ergonomic 등급이 **한글**("중간"/"높음") → §2-2 M2-4 |

### 2-2. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| M2-1 | `worker.py:254-272` (`_derive` zone, `debouncer._vigent_seen`) · `zone_debounce.py:65` | **높음(루프 내 메모리 누적)** | 구역 안에 들어온 주체 키(`t<tid>`·`g<x>_<y>`)를 `known` 집합과 디바운서 `_st`에 넣기만 하고 **어디서도 지우지 않는다**. ByteTrack tid는 단조 증가하므로 카메라가 켜져 있는 한 키가 계속 쌓이고, 매 프레임 `for subj in sorted(known)`을 전수 순회한다(하루 수천 명 통행 현장이면 프레임마다 수천 회 정렬·상태 조회) | 코드 경로(`known |= …` 후 pop 없음 · `ZoneDebouncer.reset()` 호출부 0) | 프레임마다 "이번에 안 보인 주체"는 디바운서 상태가 `confirmed=False`이고 `exit_s` 이상 밖이면 `known`·`_st`에서 제거(퇴장 확정 후 정리). 테스트: tid 1..N 순차 진입·퇴장 후 `len(known)` 상한 확인 |
| M2-2 | `worker.py:444-497` (`MotionTracker`) | **중간(오경보 방향)** | guard가 이미 안정 tid(ByteTrack)를 주는데 **무시하고** 중심점 최근접 매칭(`MATCH=0.32`, 화면 폭의 1/3)으로 사람을 다시 잇는다. 두 사람이 0.32 안에 있으면 ID가 서로 바뀌어 "1초에 0.15 이동"이 되어 **급격동작 오발화**, 반대로 무동작 트랙이 옆 사람에게 이어져 리셋된다 | 코드. 실 운영 흔적: `dispatcher.py:190` "rapid_motion 이 #19 dead·#24 pending"(test 카메라) · dead 35건 중 rapid_motion 3건 | tid가 있으면 tid로 잇고(없을 때만 중심점, 임계 0.15로 축소). **경보 동작 변경** → 수정 전후 `multi_scene.mp4` 재생으로 rapid/immobility 발화 수 비교(M1-5와 같은 절차) |
| M2-3 | `worker.py:486-489` · `proximity.py:60-67` 대비 | 낮음 | `rapid_motion` 거리는 x(폭)·y(높이) 정규화 스케일이 다른데 무보정으로 유클리드 → 세로 이동이 과대(16:9면 1.78배). `proximity._gap`은 `aspect_hw`로 보정했는데 여기만 빠짐(감사 E-1 동류) | 코드 | `MotionTracker.update(detections, ts, aspect_hw)`로 y에 h/w 곱. M2-2와 같은 커밋·같은 측정 |
| M2-4 | `worker.py:434` (`ErgonomicsTracker`) · `dispatcher.py:193-198` · `alert_gate` | **중간** | ergonomic_risk 등급이 **한글**("중간"/"높음")로 발화되는데 통보 배선 `on_severity` 키는 `critical/high/medium` → `get(level, ["log"])`로 **항상 log 전용**. 즉 근골격 경보는 기록만 되고 원격 통보가 구조적으로 불가(의도라면 `/safety/posture`처럼 명시해야 하는데 여기엔 주석 없음). R9(ergo 4파일 보류)의 "경보까지 이어지는가" 답: **기록 O · 통보 X** | 코드(`{"warn":"중간","bad":"높음"}`) · `safety_core.py:739` 는 근골격은 통보 안 한다고 명시 | 대표 결정: (a) 의도(기록 전용)면 `level="low"`로 통일하고 주석 명시 (b) 통보 원하면 `"medium"/"high"`로. 어느 쪽이든 한글 등급은 제거 |
| M2-5 | `worker.py:275-276` | 낮음 | `ppe_missing` note가 "보호구 미착용 감지" 고정 — 어떤 항목(안전모/조끼/마스크)인지 이벤트·통보에 없다. 운영자가 현장 조치를 못 고른다. guard 는 `ppe_missing_hits` 라벨을 갖고 있으나 signals에 안 실림 | 코드 | guard signals에 `ppe_missing_labels` 추가 → note "보호구 미착용(NO-Hardhat)". 출력 계약 추가(기존 키 불변) |
| M2-6 | `worker.py:298`·`:280` 등 | 낮음 | `tuning.val`을 **프레임마다** 호출(crowd threshold·radius·grid_cells·enter_s…) — `tuning.cfg()`가 캐시라 비용은 dict 조회 수준, 실해 없음. 다만 `MotionTracker.IMMOBILE_S/RAPID_DIST`는 **import 시점 1회**라 같은 파일의 다른 키와 반영 시점이 다르다(F-6 재시작 필요 원칙과 일치하나 혼재) | 코드 | 문서 기재만(동작 무변경) |
| M2-7 | `worker.py:491-496` | 낮음(제품 판단) | 무동작 45s는 **앉아서 작업하는 사람**(프레스 조작·검사대)도 매 45s 마다 "쓰러짐 의심"으로 잡는다. 억제는 쿨다운·통보 게이트뿐 | 설계 | 현장 프로파일에서 `motion.immobile_s` 상향 또는 구역 한정 옵션 — 대표 판단 |
| M2-8 | `tests/` | 낮음(테스트 공백) | `MotionTracker`(급격동작·무동작)·`crowd_density` 단위 테스트 **0건**(grep). zone_debounce·proximity·쿨다운은 있음 | grep | M2-2 수정 시 선행 테스트로 추가(중심점·tid 매칭, 45s 창, 1.0s 창) |

**확인했으나 문제 없음**: zone 디바운서 첫 관측을 '밖'으로 초기화(기동 순간 발화 방지, `zone_debounce.py:83-87`) · 탑승자 제외 포함률 실측 근거(`proximity.py:22-31`) · 협착 y 스케일 보정(`aspect_hw=h/w` 전달 `worker.py:929`) · 포즈 스레드는 풀세트 프레임에서만 입력 갱신 · 규칙 쿨다운 키에 주체 포함(D1-C).

### 2-4. 진행 현황(대표 승인 2026-09-06) — 커밋 3개
- **M2-1** ✅ `6e7e964`: 퇴장 확정 주체 정리(known·디바운서). 선행 테스트 5(300명 순차 진입·퇴장 시뮬 → 키 ≤2).
- **M2-2·M2-3·M2-8** ✅ `8a9a61c`: tid 우선(중심점은 tid 없는 검출만 폴백) + ByteTrack ID 재부여 방어 게이트(실측 중 발견: 같은 tid가 한 표본에 0.45~0.64 점프) + y×(h/w) 보정 + 단위 테스트 11. 측정(`benchmarks/motion_rules_ab.py`, 영상 5개 ByteTrack 캐시를 2fps 표본화):

  | 영상 | 표본 | 급격동작 프레임 발화 구→신 | 15s 쿨다운 이벤트 시각(s) 구→신 | 무동작 | 구 동작 ID 스왑 |
  |---|---|---|---|---|---|
  | multi_scene | 42/497f | 7→11 | [9.0]→[2.5, 18.5] | 0→0 | 11 |
  | multi_cross | 22/176f | 6→7 | [3.73]→[3.73] | 0→0 | 5 |
  | occlusion | 21/164f | 2→1 | [4.79]→[4.79] | 0→0 | 3 |
  | single_fast | 28/217f | 7→4 | [5.85]→[9.57] | 0→0 | 22 |
  | single_move | 7/84f | 0→0 | []→[] | 0→0 | 0 |

  사라진 발화(구에만): single_fast 5.8·6.4·8.0·13.3·13.8s(d 0.22~0.30, tid 없음=파편 트랙 사이 "가짜 이동"), occlusion 10.1s, multi_scene 12.5s(둘째). 생긴 발화(신에만): multi_scene 2.5s(tid …000, d 0.17, S1 카메라 급이동 구간)·9.5·13.0·13.5·19.x s(tid …001·009·015·017, d 0.18~0.73, S5 다인 교차). **해석은 추측/미검증(육안 미확인)**: 구 동작은 스왑(11·22회)으로 궤적이 끊겨 실제 이동량이 작게 계산됐고, 신 동작은 같은 사람의 1초 이동량이 온전히 잡힌다. 무동작은 영상이 ≤20s라 전부 0(임계 45s) — 무동작 회귀는 단위 테스트로만 확인.
- **M2-2 육안 검증(대표 지시, 2026-09-06)** — 발화 시각 전후 1초(2fps 표본 5장)에 박스·tid 를 그려 `D:\vigent_private_data\_audit_tmp\`에서 직접 판독(판독 후 폴더 삭제, 산출물에 이미지 없음):

  | 영상·시각 | tid | 같은 사람? | 실제 이동? | 판정 |
  |---|---|---|---|---|
  | multi_scene 2.5s | …000 | 예(우측 작업자, 연속 5프레임 동일 복장) | 프레임 내 이동 있음 — **카메라 팬**(휴대폰 촬영, S1 "카메라 급이동" 구간)+보행 | 실이동이나 카메라 기여 큼 → **카메라 흔들림 억제 항목(M3)** |
  | multi_scene 9.5s | …001 | 예(철근 운반 작업자) | 예(오른쪽으로 걸어감 + 카메라 추종) | 정상 발화 |
  | multi_scene 13.0s | …001 | 예(12.0s 는 같은 사람의 하반신만 잡힘 — 동일 신발·하의) | 카메라 **틸트**로 프레임 내 위치가 크게 변함(사람 이동은 작음) | 카메라 기여 → M3 |
  | multi_scene 13.5s | …001 | 예 | 카메라 팬(소) | M3 |
  | multi_scene 19.0s | …015 | **아니오**(18.5s 중앙 상단 배경 작업자 → 19.0s 좌상단 다른 배경 작업자; 카메라는 반대 방향으로 팬) | — | **ID 재부여** → 게이트 조정 |
  | multi_scene 19.5s | …009 (d 0.73) | **아니오**(우상단 → 중앙 → 좌상단, 서로 다른 배경 작업자 3명) | — | **ID 재부여** → 게이트 조정 |
  | single_fast 5.85s(구만 발화) | (구 tid 없음 / 신 tid …030) | 예 — 작은 남자(…030)가 큰 남자 뒤로 좌→우 횡단 | **예**(실제 횡단) | ★신 동작 **미탐** — 원인: 15fps 표본 간격 0.533s × 2 = 1.067s > 창 1.0s(가림으로 1표본 결손) |
  | occlusion 10.13s(구만 발화) | (구 tid 없음 / 신 …024) | 예 — 화이트보드 뒤에서 걸어 나옴(9.05→10.12s, x 0.2→0.65) | **예** | ★신 동작 **미탐** — 같은 원인 |

  → 조치: ① 재부여 게이트를 **보정 거리 0.25/표본**(`TID_JUMP_MAX`, y×h/w 포함)으로 — 배경 작업자 재부여는 0.36~0.5/표본, 사람의 실제 급이동은 ≤0.15/표본. 분리된 옛 트랙은 **이력을 비움**(남기면 옛 표본으로 1초간 재발화 — 재측정 중 실측). ② 창 여유 `RAPID_T_SLACK=0.1s`(15fps 표본 2스텝 1.067s 수용). 테스트 13(+3). **재측정**(구 동작 = tid 제거·여유 0):

  | 영상 | 급격동작 프레임 발화 구→신 | 15s 쿨다운 이벤트 시각(s) 구→신 | 구 ID 스왑 |
  |---|---|---|---|
  | multi_scene | 7→6 | [9.0]→[2.5, 18.5] | 11 |
  | multi_cross | 6→6 | [3.73]→[5.32] | 5 |
  | occlusion | 2→7 | [4.79]→[4.26] | 3 |
  | single_fast | 7→16 | [5.85]→[4.78] | 22 |
  | single_move | 0→0 | []→[] | 0 |

  재부여 발화(19.0s tid15·19.5s tid9 d0.45~0.73) **소멸**. 미탐 2건(single_fast 5.8s tid30 d0.25 · occlusion 10.1s tid24 d0.18) **회수**. 15fps 영상의 프레임 발화 증가(2→7·7→16)는 여유 덕에 3표본 창이 성립해 같은 사람의 연속 이동(multi_cross tid20 0.18~0.39·occlusion tid24 0.16~0.31 = 육안상 실제 보행/횡단)을 매 표본 잡는 것 — 15s 쿨다운 이벤트 수는 전부 불변. multi_scene 잔여 신 발화(2.5·13.5·18.5~20.0s, d 0.15~0.25)는 전부 **카메라 팬/틸트 구간** → **M3 등록: 카메라 흔들림 억제(전역 이동 보정 또는 다수 트랙 동시 이동 시 억제)**. **M2-2 육안 검증 완료(종결)**.
- **M2-4·M2-5** ✅ `59f259d`: 근골격 `level="low"` 기록 전용 명시(R9 답: 기록 O·통보 X) · `ppe_missing_labels` 신호 + note.
- **M2-6·M2-7** 문서만(M2-7 → R15 중간 등록). 하드코딩 상수 7개는 모듈 7에서 설정 모듈로.

### 2-3. 규칙 간 상수·시간창 목록(코드 흩어짐)

| 상수 | 값 | 위치 | 설정 가능 |
|---|---|---|---|
| PPE 히스테리시스 | 3프레임 | `guard.py HYSTERESIS_FRAMES` | tuning `detect.hysteresis_frames`(전 신호 통일값만) |
| 화재 히스테리시스 | 2프레임 | 〃 | 〃 |
| 구역 진입/이탈 유지 | 1.0s / 1.0s | tuning `zone.enter_s/exit_s` | O |
| 구역 기준점 | foot | tuning `zone.reference` | O |
| 격자키 분할 | 0(비활성) | tuning `zone.grid_cells` | O |
| 협착 반경 / 진입 / 해제 | 3.0m / 0.4s / 1.0s | tuning `proximity.*` | O |
| 탑승자 포함률 | 0.65 | tuning `proximity.driver_containment` | O |
| 장비 크기 필터 | 폭>0.9 또는 면적>0.7 제외 | `proximity.py:87` | ✗ 하드코딩 |
| 급격동작 거리 / 창 | 0.15 / **1.0s** | tuning `motion.rapid_dist` / `MotionTracker.RAPID_T` | 거리만 O, 창 ✗ |
| 무동작 시간 / 퍼짐 / 최소 샘플 | 45s / **0.03** / **5개** | tuning `motion.immobile_s` / `IMMOBILE_SPREAD` / 코드 | 시간만 O |
| 사람 매칭 거리(모션 / 포즈) | **0.32 / 0.18** | `MotionTracker.MATCH` / `ErgonomicsTracker.MATCH` | ✗ |
| 트랙 이력 / 소멸 | 60s / 3.0s | `HIST_S` / `worker.py:482·440` | ✗ |
| 군집 임계 | 6명 | tuning `crowd.threshold` | O |
| 자세 지속 / 평가 간격 | 3s / 0.5s | vision.yaml `ergonomics.hold_sec` / `_MIN_INTERVAL` | 지속만 O |
| 규칙 쿨다운 / 증거 쿨다운 | 15s / 30s | tuning `detect.cooldown_s / evidence_cooldown_s` | O |
| 통보 게이트 | 300s·×2.0·상한 3600s·조용 1800s·시간당 6 | tuning `alerts.*` | O(모듈 3) |
| 구역 타일 재검출 | thr 0.1·최소 높이 15px·확대 2.0 | `zone_tile.py:31` | ✗(env `VIGENT_ZONE_TILE`) |

## 3. 모듈 3 — 오경보 억제 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `alert_gate.py` · `alert_notify.py` · `alert_queue.py` · `agents/dispatcher.py` · `vlm_confirm.py` · `zone_debounce.py` · `routers/{dispatch,zone}.py` · `routers/safety_core.py`(`/safety/sensor`·`/alerts/test`·brain 통보) · `privacy.py` 실패 통보 · `main.py` 배선(362~380) · `static/realtime_core.js` 1822~1934(브라우저 침입 경보 경로).

### 3-1. 한 경보가 규칙 발화 → 최종 통보까지 통과하는 관문(워커 경로, 순서대로)

| # | 관문 | 임계·시간 상수 | 위치 |
|---|---|---|---|
| G1 | 검출 임계(슬롯별 conf, ppe/fire 클래스별 후필터) | person 0.35 · ppe 0.55 · fire 0.70(tuning `detect.conf.*`) | `guard.py detect()` |
| G2 | 후처리(NMS 0.55 · 포함비 0.70 · PPE↔person 교차게이트 0.15 확장 · 차량 중복) | 고정 | `guard.py:1017~1026` |
| G3 | 신호 히스테리시스(카메라 키 단위 연속 프레임) | ppe 3 · fire 2(tuning `detect.hysteresis_frames`) | `guard.py _hysteresis` |
| G4 | 규칙 판정 디바운스 | zone 진입 1.0s/이탈 1.0s(**사람 단위**) · proximity 0.4s/1.0s(카메라 단위) · **rapid/immobility/crowd 는 없음**(매 프레임) | `worker.py _derive` · `zone_debounce.py` |
| G5 | 규칙 쿨다운(기록 단계) | 15s, 키 `rule\|subject`(zone 만 사람 단위) | `worker.py:1009~1013` |
| G6 | 증거 JPEG 쿨다운(기록은 유지, 이미지만) | 30s 규칙 단위 | `worker.py:1020` |
| G7 | 기록 `data_engine.log_event` | 억제 없음(항상 기록) | `data_engine.py` |
| G8 | 통보 배선 스위치 | tuning `alerts.notify`(env `VIGENT_ALERT_NOTIFY`) | `alert_gate.enabled()` |
| G9 | 통보 게이트(카메라+규칙 단위) | ① 시간당 상한 6 → ② 등급 상승이면 쿨다운 무시 → ③ 쿨다운 300s × 2.0 백오프(상한 3600s, 1800s 조용하면 리셋) | `alert_gate.decide()` |
| G10 | 전송 대기열 | 200건, 가득 차면 **가장 오래된 것 폐기** | `alert_notify.submit()` |
| G11 | 등급 → 채널 배선 | `on_severity`: critical=alarm+manager_call+relay · high=alarm+manager_call · medium/mid/low=log 만 → 원격 채널 없는 등급은 큐에 안 넣음 | `dispatcher._queue_enabled` |
| G12 | 실제 전송(텔레그램 6s·이메일 8s·웹훅 6s 타임아웃, critical 은 relay ON) → `delivered`=원격 1개 이상 성공 | — | `dispatcher._dispatch_now` |
| G13 | 실패 재시도 | 5s 주기 · 지수 백오프 ≤60s · 10회 → dead | `alert_queue` |

### 3-2. 관문을 건너뛰는 경로(우회)

| 경로 | 건너뛰는 관문 | 호출부 | 비고 |
|---|---|---|---|
| `POST /zone/intrusion` → `dispatcher.dispatch("high")` | G3~G10 전부(서버 측 억제 0) | 브라우저 `realtime_core.js:1852`(브라우저 자체 검출: 3프레임 연속 + **8s 쿨다운**만, `:1824`) | 탭 N개 = 통보 N배. `vlm_confirm` 옵션(mlx 전용)은 여기만 배선 |
| `POST /safety/sensor` → `dispatch("critical")` | 전부 | 외부 센서가 주기적 POST | ★임계 초과가 지속되면 **POST 주기마다** critical 통보 + relay ON |
| `POST /safety/brain…`(`safety_core.py:652`) → `dispatch("high")` | 전부 | 프론트 `alert=true` | 억제 0 |
| `POST /dispatch/relay` → `dispatcher.relay()` → critical | 전부 | 정적 JS 에 호출부 **없음**(그 외 위치 미확인 → 모듈 8) | 큐 #75~#87 의 출처 |
| `POST /alerts/test` → `dispatch(level, message)` | 전부 | 설정 콘솔 시험 버튼(`setup_console.py:210`) | 의도된 시험 경로 |
| `privacy._note_failure` → `alert_notify.submit` | (G9 적용, cam="privacy") | 자체 10분 1회 제한 | 정상 |
| `alert_queue` 재시도 → `_dispatch_now` | G9~G11(이미 통과) | 재시도 스레드 | ★**재시도마다 relay.turn_on 재호출** |

### 3-3. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| M3-1 | `worker.py MotionTracker` | **중간**(대표 등록) | 급격동작이 **카메라 팬/틸트**에 발화(육안검증 multi_scene 2.5·13.0·13.5·18.5~20.0s — 같은 사람, 카메라 기여) | §2-4 육안 표 | 전역 이동 보정(모든 트랙의 중위 이동 벡터를 빼고 판정) 또는 다수 트랙(≥2 또는 과반) 동시 이동 시 억제. 고정 CCTV 에선 드물지만 진동·바람 흔들림에도 해당 |
| M3-2 | `routers/safety_core.py:525-538` (`/safety/sensor`) | **높음** | 센서 임계 초과가 지속되면 **POST 마다** critical 기록 + 통보 + relay ON — 억제 관문 0. 센서는 주기(초 단위)로 보내는 장치라 폭주 구조 | 코드 | `alert_notify.submit(cam=f"sensor:{stype}", rule=rule, level="critical", …)` 로 통일해 G9 를 타게. 기록은 유지 |
| M3-3 | `routers/zone.py:70` · `safety_core.py:652` · `routers/dispatch.py:28` | **중간** | 브라우저·수동 경로가 `dispatcher.dispatch` 를 **직접** 호출 → 카메라·규칙 단위 백오프·시간당 상한(G9) 미적용. 브라우저 경로는 8s 쿨다운만이라 탭 수·재접속마다 곱 | 코드 · `realtime_core.js:1824` | 세 호출부를 `alert_notify.submit(cam=<브라우저 세션/센서>, rule=…)`로 통일(게이트 키 = 규칙+출처). `/alerts/test` 는 의도된 시험 경로라 제외 |
| M3-4 | `worker.py:1009-1013` (`ctx.cooldown`) | **중간**(M2-1 동류) | 쿨다운 키 `zone_intrusion\|t<tid>`가 사람마다 생기고 **지워지지 않음** → 운영 일수만큼 누적 | 코드(`ctx.cooldown[ck] = now`, pop 없음) | 프레임마다(또는 60s 마다) `now - ts > _COOLDOWN_S` 인 키 제거. 테스트: 300명 진입 시뮬 후 크기 상한 |
| M3-5 | `agents/dispatcher.py:205-215` + `alert_queue.try_send` | **중간**(모듈 4 이관) | 원격 채널 실패로 재시도될 때 `_dispatch_now` 가 **relay.turn_on 도 다시** 부른다 → 채널 미설정/장애 시 critical 1건이 사이렌을 최대 10회 재트리거(ON 연장) | 코드 | 재시도 경로는 원격 채널만(relay·log 제외) 또는 `_dispatch_now(..., remote_only=True)` |
| M3-6 | `alert_gate.py:113` | 낮음 | 등급 상승 예외 후 `last_rank` 갱신 → high→critical→high→critical 이 번갈아 오면 매번 쿨다운 무시(시간당 상한 6이 최종 방어) | 코드 | 상승 예외에도 최소 간격(예: 60s) 부여 |
| M3-7 | `vlm_confirm.py` · `routers/zone.py:60` | 낮음(FINAL_SUMMARY 연결) | "CNN→VLM 하이브리드 확정"은 **브라우저 `/zone/intrusion` 옵션에만** 배선, 워커 경로 미배선 + mlx 전용(Windows 무효) | 코드 | Windows VLM 대체 구현 시 워커 경로 2차 확정으로 설계 |
| M3-8 | `realtime_core.js:1911-1934` + 워커 | 낮음(모듈 8 확인) | 같은 카메라를 브라우저 라이브뷰와 서버 워커가 동시에 감시하면 **이중 통보**(브라우저 3프레임+8s / 워커 1.0s+15s+게이트) | 코드 | 브라우저 통보를 서버 게이트에 합류(M3-3)시키면 자연 해소 |
| M3-9 | `worker.py _derive` | 정보 | rapid/immobility/crowd 는 디바운스 없이 15s 쿨다운만. crowd 는 매 15s 재기록(mid → log 전용) | 코드 | 현 상태 유지(통보 안 됨). 카메라 흔들림(M3-1)만 처리 |

### 3-4. 진행 현황(대표 승인 2026-09-06) — 커밋 3개
- **M3-4** ✅ `d36e2ee`: 만료 쿨다운 키 정리(테스트 3, 300명 시뮬 상한 ≤ 창 크기).
- **M3-2·M3-3** ✅ `d3feafe`: 우회 4경로 → `alert_notify.submit`(출처 키 `sensor:<종류>`·`browser_zone:<cam>`·`brain`·`manual`, critical 상승 예외 유지). 센서는 **임계 진입 전이**에서만 통보(`edge=True`: 쿨다운 건너뜀·시간당 상한 유지), 지속 초과는 기록만, 정상 복귀 후 재초과 = 새 전이. 테스트 6(10회 초과 → 통보 1·기록 10 / 초과→정상→초과 → 통보 2 / 키 분리 / 브라우저 3→1 / relay 2→1 / `/alerts/test` 우회 유지). 응답 키 의미("큐 적재") `docs/ONBOARDING.md` 한 줄. `/alerts/test` 는 **의도된 게이트 우회**(코드 주석).
- **M3-1 (b)** ✅ (다음 커밋): `CAMERA_COS=0.8` — 창 안 트랙 ≥2·과반이 임계 이상 이동·평균 벡터와 코사인 ≥0.8 이면 그 표본 억제 + `camera_motion` 플래그(워커 `state.camera_motion_frames`·`_last_sig`). 단위 테스트 5(동방향 2트랙 억제 / 1개만 이동 발화 / 반대 방향 발화 / 단일 트랙 불변 / 3중 과반). **재측정(영상 5개)**:

  | 영상 | 급격동작 프레임 발화 구→신 | 15s 이벤트 시각 s | 카메라 억제 표본(신) |
  |---|---|---|---|
  | multi_scene | 7→6 | [9.0]→[2.5, 18.5] | **0** |
  | multi_cross | 6→6 | [3.73]→[5.32] | 0 |
  | occlusion | 2→7 | [4.79]→[4.26] | 0 |
  | single_fast | 7→16 | [5.85]→[4.78] | 0 |
  | single_move | 0→0 | []→[] | 0 |

  ★**검증 기준 미충족을 그대로 보고한다**: multi_scene 2.5·13.5·18.5~20.0s 발화가 소멸하지 않았다(억제 0). 표본별 이동 벡터 실측(신 동작): 2.5s = tid0 (+0.01, **+0.17**) · tid1 (+0.01, +0.07) · tid2 (+0.02, **−0.09**) → 과반이 임계 미달·방향 불일치; 13.0/13.5s = 창 안 트랙 **1개**(규칙 적용 불가, ≥2 필요); 19.0s = 트랙 1개; 19.5/20.0s = tid1 (+0.06, +0.17) · tid9 (**−0.22**, −0.04) · tid17 (0, +0.24) → 방향 불일치. 즉 이 영상은 **휴대폰 손떨림+실제 보행이 섞인 장면**이라 "다수 트랙 동시·동방향 이동"이 성립하지 않는다 — (b)는 고정 CCTV 의 진동·바람 흔들림(전 트랙 동일 이동)을 위한 억제이며 이 클립의 발화는 (b)로 잡을 수 없다. multi_cross·occlusion·single_fast 의 실이동 발화는 유지(억제 0) = 회귀 없음. **결론**: (b) 구현·테스트 완료, 고정 CCTV 전제에서 유효. multi_scene 잔여 발화는 손떨림 영상의 한계로 기록. **PTZ 카메라 도입 시 (a) 전역 이동 보정(트랙 중위 이동 벡터 차감) 필요 — 메모.**
- **M3-5** → 모듈 4(§4 M4-4). **M3-6·7·8·9** 문서만. **M3-8(브라우저+워커 이중 통보)은 모듈 8에서 반드시 다룬다.**
## 4. 모듈 4 — 통보(dispatcher·텔레그램·큐·재시도·기동 실패 알림) (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `agents/dispatcher.py` · `alert_queue.py` · `alert_notify.py` · `alert_gate.py` · `relay.py` · `starvation_guard.py` · `main.py` 기동·안전망(274~390) · `readiness.py` · `deploy/windows/{install_service,service_status,uninstall_service}.ps1` · `audit/c4_smoke §3`(크래시 루프 실측) · `data/alert_queue.db`(실측).

### 4-1. 등록 항목 통합표(치명 ①②③ · M3-5 · 서비스 크래시 미감지)

| ID | 출처 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| **M4-1** (①) | §4-0 | **치명** | 원격 채널이 **하나도 설정되지 않아도** critical/high 는 큐에 적재 → 재시도 10회 → dead. 그동안 `/health` degraded, 데드레터는 로그 1줄 | `dispatcher._queue_enabled`(`:183-194`)는 등급만 봄 · `alert_queue.try_send`(`:177`) 종결 조건은 "원격 시도 흔적 없음"만 · 실측 pending 15 → dead 50 | `_queue_enabled` 에 **채널 설정 여부**(`notify_cfg()` 중 telegram/email/webhook 하나라도 있음) 추가. 미설정이면 큐 미적재 + `dispatcher.status()`·`/health` 에 `channels_configured=false` 경고(현재는 telegram/email/webhook bool 만) |
| **M4-2** (②) | §4-0 | **치명** | 재시도 상한 도달(dead) = **조용한 유실**. 운영자에게 알릴 수단 0(`_LOG.error` 1줄). `/health alerts.dead` 수치만 있고 임계·경고 없음 | `alert_queue.mark_failed`(`:101-104`) · `routers/system.py:149` | dead 발생 시 ①`/health` 를 **degraded**(dead>0 & 최근 1h) ②설정된 채널이 살아 있으면 "데드레터 N건" 요약 통보 1회/시간(게이트 키 `system/alert_dead`) ③`service_status.ps1` 에 dead 수 출력 |
| **M4-3** (③) | §4-0 | **치명** | 텔레그램 **401/403/400**(토큰·chat_id 오류)을 네트워크 실패와 같이 재시도(10회 후 dead). 설정 오류는 재시도해도 영원히 실패 | dead 35건 중 31건 telegram 401(08-18~26) · `_send_telegram` 은 `status` 만 반환 | `_dispatch_now` 결과에 `config_error=True`(4xx) 표시 → `try_send` 는 즉시 dead + `reason="config_error"` + `dispatcher.status()` 에 `last_config_error`(시각·채널·상태코드, 토큰 제외) → `/health llm/notify` 처럼 노출. 설정 콘솔 시험(`/alerts/test`)에서 즉시 보이게 |
| **M4-4** (M3-5) | §3 | **중간** | 재시도 경로 `try_send → _dispatch_now` 가 **relay.turn_on 도 재호출** → 채널 장애 시 critical 1건이 사이렌을 최대 10회 재트리거(ON 연장) | `dispatcher.py:205-215` · `alert_queue.py:169` | `_dispatch_now(level, msg, meta, remote_only=False)`: 재시도(`alert_queue.set_sender`)는 `remote_only=True` 로 relay·log 채널 제외 |
| **M4-5** (R1) | audit/c4_smoke §3 | **치명** | **서비스 크래시 루프 3주 미감지**(4,067회 재시작, 130s 주기). 기동 실패(`_load_theme` → guard `FileNotFoundError`)는 uvicorn "startup failed" 로 프로세스 종료 → NSSM 재시작만 반복. 어디에도 **기동 실패 알림**이 없고, `/health` 는 프로세스가 없어 응답 자체가 없음(`service_status.ps1` 종료코드 3 — 사람이 돌려야 봄) | `main.py:323-327`(예외 처리 없음) · `install_service.ps1:105-108`(AppExit Restart·Delay 5s·Throttle 10s — 130s 주기는 스로틀 대상 아님) · 로그 8,145개 | (a) `_startup` 에서 `_load_theme` 실패를 잡아 **한 번만** 기동 실패 통보(`notify_cfg()` 직접 읽어 최소 전송, `data/startup_failure.json` 에 횟수·마지막 통보 시각 기록 → 1시간 1회 상한) 후 **재raise**(기동은 실패시킨다 — 조용히 뜨지 않음) (b) NSSM: `AppThrottle` 를 기동 시간보다 길게(예: 180000ms) 두어 "기동 후 3분 안에 죽으면 스로틀", `AppExit` 재시작 지연을 60s 로 — 무한 130s 루프를 완만하게 (c) `service_status.ps1`: `logs/vigent.err-*` 회전 파일 **최근 1h 개수** 출력·임계 초과 시 종료코드 4 (d) `md/DEPLOYMENT.md §7-1` 에 재설치 후 `service_status.ps1` 확인 절차 |
| M4-6 | `alert_notify._loop` · `dispatcher._dispatch_now` | 중간 | 전송 스레드가 **채널 3개를 순차·동기**로 부름(텔레그램 6s + 이메일 8s + 웹훅 6s = 최대 20s/건). 네트워크 장애 시 처리량 3건/분 → 큐 200 초과분 **최고령 폐기**(`alert_notify.py:132-142`) — 폐기가 stats 에만 남음 | 코드 | 채널별 타임아웃 합을 줄이거나(텔레그램 우선, 나머지 병렬) 폐기 시 WARNING 로그 + `/health alerts.dropped` 노출 |
| M4-7 | `dispatcher._send_telegram` | 낮음 | 텔레그램 본문 4096자 제한 미처리(긴 note 는 400) → M4-3 경로로 dead | 코드 | 4000자 절단 |
| M4-8 | `dispatcher.notify_cfg` | 낮음 | 전송 3채널마다 `notify.yaml` 을 다시 읽음(1건당 3회 파일 IO) | 코드 | 1건당 1회로(동작 무변경) |
| M4-9 | `starvation_guard._escalate` | 낮음 | 3단계 프로세스 재기동이 `subprocess.Popen(shell=True)` 로 `VIGENT_RESTART_CMD` 실행 — 서비스 계정에서 `sc stop/start` 권한 필요, 실패는 로그만 | 코드 · `install_service.ps1:151` | 재기동 명령 실패도 M4-2 데드레터 통보와 같은 채널로 |
| M4-10 | `relay.turn_off` 실패 | 정보 | OFF 최종 실패는 `/health degraded` 로 드러남(P3a) — 정상. 단 통보는 없음 | `routers/system.py:161` | M4-2 요약 통보에 `relay.off_failed` 포함 |

### 4-2. 진행 현황(대표 승인·조정 3건 반영, 2026-09-06) — 커밋 4개
- **M4-4** ✅ `be5aa2b`: `_dispatch_now(remote_only=True)` — 재시도는 원격 채널만(relay·log 제외). 테스트 3(최초 1 + 재시도 3 → relay 1회).
- **M4-1·M4-2·M4-3·M4-7** ✅ `bb7ddef`: 채널 미설정 → 큐 미적재 + `undeliverable` 집계(`/health` 는 미설정 자체를 `warnings["channels_not_configured"]` 로만, critical/high 폐기가 있을 때만 degraded + `alerts.undeliverable`) · HTTP 400/401/403/404(+SMTP 인증·수신자) = `config_error` → 즉시 dead + `last_config_error`(채널·코드·시각, 토큰 제외) + `warnings["notify_config_error"]` · 429 = Retry-After 존중(없으면 기존 백오프) · 5xx/타임아웃/네트워크 = 기존 · dead → 살아 있는 채널로 요약 통보 1시간 1회(`system/alert_dead`, 재귀 금지) + `alerts.dead_1h`(신규 `dead_at` 열, 구 DB ALTER) → degraded · `service_status.ps1` 에 pending/dead_1h/undeliverable·채널 미설정·설정 오류·warnings 출력 · 텔레그램 4000자 절단. 테스트 10.
- **M4-6** ✅ (커밋 대기): 대기열 가득 → 최고령 폐기 시 WARNING(누적 수·폐기 메시지 요지) + `/health alerts.{dropped, queue_depth, notify_thread_alive}` + `warnings["notify_queue_dropped"]`(status 불변 — 최신 경보는 살아 있음). 테스트 2. 병렬 전송은 백로그.
- **M4-5** ✅ (커밋 대기): (a) `main._startup`: `_load_theme` 실패 → `data/startup_failure.json`(누적 횟수·마지막 통보) + **Windows 이벤트 로그** Application/VIGENT/ID 1000(매 실패; `eventcreate` → 실패 시 `Write-EventLog` 폴백) + 원격 채널 있으면 통보(첫 실패 즉시, 이후 1시간 1회, `remote_only`) → 재raise. 테스트 4. ★실측: 비관리자 개발 세션에서 `eventcreate` 는 "Access is denied" — 서비스(LocalSystem) 경로는 **미검증**(재설치 후 5단계에서 확인). 그래서 `install_service.ps1` 이 소스를 미리 등록(`New-EventLog`, 관리자)하고 결과는 상태 파일 `event_log_ok` 로 남긴다. (b) `install_service.ps1`: `AppRestartDelay 60000`·`AppThrottle 180000`(구 5s/10s — 130s 주기 루프에 무력했던 이유 주석) + `md/DEPLOYMENT.md §7-1` 재발 방지 3겹 기재. **서비스 재설치는 5단계 검증 후 결정**(현재 SERVICE_DISABLED). (c) `service_status.ps1`: 최근 1시간 `vigent.err-*` 회전 파일 수 상시 출력, 임계(기본 10, `-CrashLoopThreshold`) 이상이면 **종료코드 4**(서버 무응답 시에도 동작). 실행 검증: 서비스 정지 상태 exit 3, 임계 0 으로 강제 시 exit 4. BOM·CRLF 유지·파싱 OK.
- **M4-8·9·10** 문서만.

### 4-0. ★예약(치명) — `data/alert_queue.db` pending 15건 실측(2026-09-06, 읽기 전용·발송 0)

| id | 생성(08-28) | 등급 | 카메라 / 규칙 | 메시지(요지) | 시도 | 마지막 실패 사유 | 판별 |
|---|---|---|---|---|---|---|---|
| 73·74·77·79·84·85 | 14:16·14:20·15:09·15:12·19:27·19:31 | critical | (없음, meta `{}`) | "프레스 우회" | 8·8·8·7·5·5 | telegram **미설정** · email **SMTP 미설정** · webhook **미설정** · safety_relay_signal sent(로그) | **시험 경보** — `/alerts/test`(payload level/message 자유 입력, `safety_core.py:728`) 또는 UI 시험 버튼. 코드 어디에도 "프레스 우회" 문자열 없음 |
| 75·76·80·83·87 | 15:09·15:09·18:56·19:27·20:12 | critical | (없음) | "guard_bypass: 위험기계 방호구역 신체 진입 감지" | 8·8·7·5·4 | 동일 | **시험/데모 경보** — `/dispatch/relay`(프론트 프레스 모드) 또는 `dispatcher.relay()` 직접 호출. 카메라·증거 없음 |
| 78·86 | 15:09·19:53 | high | (없음) | "테스트" | 7·4 | 동일 | **시험 경보**(`/alerts/test`) |
| 81 | 19:27:22 | high | **TZ** / zone_intrusion | "[TZ] 위험구역 내 작업자 감지(구역-타일 회수)" | 6 | 동일 | **테스트 스위트가 쓴 행** — 카메라명 TZ·"구역-타일 회수" 문구는 `tests/test_worker_zone_tile.py:29`(VIGENT_ZONE_TILE=1)만 만든다 |
| 82 | 19:27:27 | critical | **TESTCAM** / fire_smoke | "[TESTCAM] 화재/연기 감지" | 6 | 동일 | **테스트 스위트가 쓴 행** — TESTCAM 은 `tests/test_worker_process_frame.py:27`·`test_worker_credential_masking.py:25` |

- **실제 현장 경보 0건 / 시험·데모 13건 / 테스트 스위트 2건.** 토큰·chat_id 는 행에 저장돼 있지 않음(마스킹 대상 없음).
- **실패 분류**: 15건 전부 원격 채널 3종 **미설정**(`config/notify.yaml`·env 모두 비어 있음 — 401/403/네트워크 아님). 즉 dispatcher 재시도 로직의 문제가 아니라 **"보낼 곳이 없는데 큐에 넣는" 설계 공백**: `_queue_enabled()`는 등급의 `on_severity`에 alarm/manager_call 이 있으면 큐에 넣고(`dispatcher.py:193`), `try_send()`의 종결 조건은 "원격 채널을 시도조차 안 한 경우"뿐(`alert_queue.py:177`)이라 **미설정 실패도 재시도 대상**이 되어 pending → 10회 후 dead 로 흐른다. 참고: dead 35건 중 31건은 telegram **401**(토큰 무효, 08-18~08-26) — 당시엔 설정이 있었으나 토큰이 틀렸던 것. 이건 config 문제.
- **왜 아직 pending 인가**: 재시도는 서버 프로세스 안에서만 돈다. 08-28 세션 종료로 멈췄고, 오늘 03:25 스모크 기동 때 1~2회 더 시도된 뒤(`next_attempt_at` 09-06 03:25) 종료. 서버가 다시 뜨면 남은 2~6회를 시도하고 dead 로 간다 — **그동안 /health 는 degraded**.
- **치명 항목으로 등록(모듈 4에서 수정)**: ① 원격 채널이 하나도 설정되지 않은 등급은 큐에 넣지 않거나 즉시 종결(재시도 무의미) ② 재시도 상한·데드레터 도달 시 **운영자에게 알릴 수단이 없음**(데드레터 = 조용한 유실; 로그 ERROR 1줄뿐) ③ 401(토큰 무효) 같은 **설정 오류는 재시도 대상이 아니라 즉시 설정 경고**여야 함 ④ ★**테스트 스위트가 운영 DB(`data/alert_queue.db`)에 행을 쓴다** — `_process_frame` 통합 테스트가 실제 `alert_notify.submit`→dispatcher 경로를 탄다(#81·#82). notify.yaml 이 설정된 PC에서 테스트를 돌리면 **"[TESTCAM] 화재/연기 감지"가 실제 텔레그램으로 나간다**. 테스트에서 `alert_notify` sender·DB 경로를 강제 격리해야 함.
- ✅ **15건 처리(대표 결정 2026-09-06)**: 전부 시험·테스트 행으로 확인 → `status=dead`, `last_error="audit 2026-09-06: 시험/테스트 행 폐기"`(삭제 아님, attempts 보존). 처리 후 집계 dead 50 · sent 37 · pending **0**. ④(테스트 격리)는 모듈 4를 기다리지 않고 즉시 수정(R14). 격리 전 1회 스위트 실행이 남긴 `data/evidence/20260906/ev_20260906_043204_zone_intrusion_high.jpg` · `data/risk_assessments/ra_20260906_043206.{html,json}`(테스트 산출, 검은 프레임·더미 평가서)은 **대표 판단으로 삭제**(자동 삭제 안 함).
- ①②③은 모듈 4 치명 그대로.
## 5. 모듈 5 — 카메라 입력·go2rtc (대기)
## 6. 모듈 6 — 보존 스윕 (대기)
## 7. 모듈 7 — 설정·경로·기동 (대기)
## 8. 모듈 8 — 프론트 realtime_core.js 감시 화면 (대기)
