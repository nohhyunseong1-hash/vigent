# CODE_REVIEW.md — 4단계 정밀 코드 리뷰 (감사 2026-09-06)

> 대상 브랜치 `audit/cleanup-20260906` (3단계 완료 HEAD `aab7d05` 이후). 방식: 모듈 단위로 **전체 읽기 → 보고 → 승인 → 수정(테스트 선행) → 게이트(ruff·mypy·OpenAPI·481 unittest) → 커밋**.
> 범위(CLEANUP_PLAN §10 범위 결정 2차): 비전(감시 서버 코어)만 정밀 리뷰. `agents/`는 치명(비밀정보 노출·코어를 깨뜨리는 import)만.
> 원칙: 모든 지적은 **파일:줄 근거**를 달고, 수치는 실행·측정한 값만 적는다. 추측은 "추측/미검증"으로 표기.
> ※ 2026-07-15의 1차 검토 보고서는 [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md)(P0~P2 조치 완료)이며 이 문서와 별개다.

## 0. 등록 항목 (1~3단계에서 넘어온 것) — 현황표

| # | 등급(등록 시) | 항목 | 출처 | 담당 모듈 | 현황 |
|---|---|---|---|---|---|
| R1 | **치명** | 서비스 크래시 루프 3주 미감지(4,067회 재시작) — 기동 실패 알림 / NSSM 재시작 제한 / `service_status.ps1` 회전 파일 증가 검사 | audit/c4_smoke §3·§5 | 4(통보)·7(기동) | ✅ `99488d9` M4-5(상태파일·Windows 이벤트 로그·1h 1회 통보·NSSM 60s/180s·status 크래시 루프 검사) + `5cf638b` M7-3(필수 서비스 실패도 같은 경로) + `4111dbd` M7-8(스윕 밀림 60s). 서비스 재설치·eventcreate 서비스 계정 경로는 5단계 검증 |
| R2 | **치명/높음** | 프론트 `realtime_core.js:3122` → `POST /llm/vision` 404(죽은 버튼) | AUDIT §9-d | 8(프론트) | ✅ `7ec9509` M8-2: 서버에 없는 9경로를 미구현으로 비활성(fetch 0), 라우트 생성 시 알려 주는 테스트. 안전 페이지엔 LLM 버튼 UI 자체가 없음(실측 0) |
| R3 | **치명(범위 규칙)** | `agents/`는 비밀정보 노출·코어 파괴 import만 점검 | CLEANUP_PLAN §10 | 전 모듈 공통 | 3단계 C4 비밀 스캔 0건 · C9 선택 import 완료. 4단계 중 추가 발견 시 기재 |
| R4 | 높음 | W1 rf-detr `_kp_active_mask` 부분 로드 경고(3슬롯 공통) | c4_smoke §2 W1 | 1 | ★**정정 → 낮음(영향 없음)**. §1 M1-2 실측 근거 |
| R5 | 중간 | forklift 설계상 비활성(F-7)로 `/health status=degraded` | c4_smoke §1·§6 | 1 | ★**정정 → 사유 오판**. degraded 실제 사유는 미전송 경보 pending 15건(§1 M1-3). 후속은 모듈 4 |
| R6 | 중간 | 골든 스크립트 `--help` 부작용(파일 생성) | AUDIT §9-e | agents 자산 → 코드 무수정, 문서 기재만 | 대기 |
| R7 | 중간 | W5 개발 런처 `RF_HOME` 기본값이 사용자 프로필(`~/.roboflow/models`) — 저장소 `vigent-core/weights` 고정 여부 | c4_smoke §2 W5 | 7 | 모듈 7 보고 → M7-2(양쪽 캐시 동일 크기 실측, 전환 비용 0) |
| R8 | 보류 | `safety_manager.py` UI 연결 여부 | CLEANUP_PLAN §6 | (agents 범위 밖) | 보류 유지 |
| R9 | 보류 | ergo 4파일(`ml/ergonomics.py` 등) — 포즈 스레드는 살아 있음(`worker.py:1069`), 경보·저장까지 이어지는지 | AUDIT §4 | 2(규칙) | 대기 |
| R10 | 낮음 | W2 rf-detr `num_classes` 미전달 경고 | c4_smoke §2 W2 | 1 | §1 M1-9 |
| R11 | 낮음 | CI Python 3.13 vs `.python-version` 3.11.9 | AUDIT §2-2 | 7 | 모듈 7 보고 → M7-5(ONBOARDING 3.13.9/anaconda 잔재 포함) |
| R12 | 낮음 | C1 unittest 1회 flaky(이름 미포착, 이후 8회 연속 OK) | 3단계 | 게이트 공통 | ★**이름 포착·원인·수정(2026-09-06 run3)**: `test_readiness_warmup.TestWarmup.test_on_ready_not_called_when_warmup_fails`('ready' != 'failed'). 로그 `audit/unittest_flaky_2026-09-06_run3.log`. 원인 = `test_endpoints_smoke`가 TestClient startup 으로 띄운 **실모델 예열 스레드**("vigent-warmup", 20초+)가 자기 모듈이 끝난 뒤에도 살아 전역 readiness 상태에 READY 를 덮어씀(테스트 격리 결함, 제품 결함 아님). 단독 실행 3/3 통과. 수정: 해당 모듈 setUp 에서 잔존 예열 스레드 join. C1 때 실패가 같은 테스트였는지는 **미확인**(당시 이름 미포착) |
| R13 | 낮음 | `training/train_merged.py`·`train_monitor.py` mac 경로·mps 기본값 | C3 | (training 범위 밖) | 문서 기재만 |
| R14 | **치명** | 테스트 스위트가 운영 `data/`(alert_queue.db·evidence·recognition·risk_assessments)에 쓴다 — notify.yaml 설정 PC 에서는 시험 문구가 실제 텔레그램으로 발송 가능 | §4-0 ④ 실측 | 테스트 격리 | ✅ **수정 완료**(커밋 `[CODE_REVIEW ④]`): `tests/_isolate.py` + 9개 모듈 적용. 검증 = data/ 28,815파일 sha256 전후 비교 **추가 0·변경 0**(격리 전엔 +3 파일·1 변경) |
| R15 | 중간 | 카메라별 무동작 임계값(45s/0.03) 설정화 — 앉아 작업 현장 오경보 방지(M2-7) | §2 M2-7 | 7(설정) | 모듈 7 보고 → M7-7(카메라별 override 구조 없음 확인, 규모 판단 요청) |
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
## 5. 모듈 5 — 카메라 입력·go2rtc 연동 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `worker.py`(캡처 스레드 `_StreamCapture`·`_setup_run`·`_loop`·hang 감시·감독자·`WorkerManager`) · `routers/cameras.py` · `camera_registry.py` · `routers/tapo.py` · `config/go2rtc.yaml` · `starvation_guard.py`(슬롯 회수) · `main.py` startup/shutdown. 실측: `cv2 5.0.0`(백엔드 FFMPEG·MSMF·DSHOW·GSTREAMER 가용), env 확인.

### 5-1. RTSP 끊김 → 재연결 흐름(한 줄씩)

**thread 모드**(`VIGENT_CAPTURE_MODE=thread`, 서비스 기본 — `install_service.ps1`이 주입; 개발 `run.ps1`은 미설정 → **sync**):
1. `_StreamCapture._open()` → `cv2.VideoCapture(src)`(FFmpeg, `OPENCV_FFMPEG_CAPTURE_OPTIONS`=tcp) — 연결 실패해도 객체는 생성됨(`isOpened` 미검사)
2. `_run()` 루프: `grab()` 실패 → `read_fails += 1`, `dropped += 1`, 0.05s 대기
3. 연속 5회(`_READ_FAIL_MAX`) → `reconnects += 1`, `cap.release()`, 백오프 1→2→4→**5s 상한**(`_RECONNECT_MAX`, B3) 대기 → `_open()` 재호출, `generation += 1`
4. 성공 프레임: `grab` 드레인(≤60, 20ms 규칙) → `retrieve()` → 슬롯 `_frame/_ts` 갱신, 백오프 리셋
5. `_loop`: `read_latest()` → None 이면 캡처 스레드 생존 확인(죽었으면 break → 감독자 재시작), 있으면 하트비트 `last_frame_ts=슬롯 시각`
6. `_hang_watch`(1s 주기, 기동 유예 90s): `last_frame_ts` 15s 무진전 → `_restart_req` → `_loop` 종료 → `streamcap.stop()`(join **3s**) → 감독자가 새 `_loop`·새 `_StreamCapture` (hang 은 즉시, crash 는 백오프 ≤30s)
7. 그래도 검출이 멈추면(`stale_detect`) `starvation_guard`: 60s → go2rtc 스트림 삭제(슬롯 회수) → 120s → 워커 재시작 → 3회 → `VIGENT_RESTART_CMD`

**sync 모드**: `_loop` 안에서 `cap.read()` 직접 → 실패 5회 → release·백오프·`VideoCapture` 재생성(같은 규칙). 파일 소스는 끝나면 되감기.

### 5-2. 프레임 None·손상 처리 / Windows 백엔드 / N대 구조

- **None**: `retrieve()`·`read()` 실패는 `(False, None)` → 재연결 카운트. `_loop`에 `frame is None` 방어(`:1236`), `_process_frame`은 shape 를 그대로 신뢰(None 도달 불가). 손상 프레임(부분 디코드 아티팩트)은 정상 배열로 들어와 **별도 판별 없음** — 검출기가 그대로 본다(오검출 가능, 측정 안 됨).
- **Windows 백엔드**: `cv2.VideoCapture(src)` 에 `apiPreference` **미지정**. RTSP/파일 문자열 → FFMPEG 자동 선택(정상). 웹캠 정수 인덱스 → Windows 기본 **MSMF**(느린 open·일부 장치 hang 사례) — `CAP_DSHOW` 지정 없음. 현장 주 입력은 RTSP 라 영향 낮음.
- **N대 동시**: 카메라 1대 = `Worker` 1개 = 스레드 **4개**(감독자 `_run_supervised` · `_hang_watch` · `_pose_loop` · 캡처 `_StreamCapture`) + 프레임 참조 3개(`_last_frame`·캡처 슬롯·`_pose_input`). 추론은 `DETECT_LOCK`(RLock) 으로 **전 카메라 직렬화**(풀세트 ~85ms → 2fps 기준 약 5대에서 GPU 예산 포화, `capacity_probe` 계열 실측은 별도). `_PoseModel`·guard 는 싱글톤 공유(포즈는 N개 스레드가 같은 ONNX 세션을 동시에 호출 — ORT `run` 은 스레드 안전, 지연 로드 경합만 남음).

### 5-3. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| M5-1 | `worker.py:64` vs `:613-614` | **중간** | 저지연 FFmpeg 옵션(`fflags;nobuffer\|flags;low_delay`, T-E2E 잔여지연 조치)이 **죽은 코드**. 모듈 import 시 `:64` 가 `OPENCV_FFMPEG_CAPTURE_OPTIONS` 를 먼저 `setdefault` 하므로 `_open()` 의 두 번째 `setdefault` 는 절대 적용되지 않는다 | 실측: env 비운 뒤 `import worker` → `rtsp_transport;tcp\|max_delay;500000`, 이어서 `_open` 식 setdefault → **불변** | 모듈 상단 한 곳으로 통일(값은 저지연 포함으로 — 원 의도). ★영상 지연 특성이 바뀌므로(규칙 6) 실카메라 재측정이 필요한데 이 PC 에는 RTSP 카메라가 없다 → 대표 판단(코드만 고치고 5단계 현장 검증 항목으로) |
| M5-2 | `worker.py:615·1146·1221` · `routers/cameras.py:192` | **중간** | RTSP **연결·읽기 타임아웃 미설정** — 죽은 IP 는 FFmpeg 기본 ~30s 를 블로킹한다(전체 스위트 로그에 `Stream timeout triggered after 30093ms` 실측). thread 모드에서 `_open()` 30s 블로킹 중 hang 감시가 재시작 → `streamcap.stop()` join 3s 초과 → **옛 캡처 스레드가 최대 30s 더 살아 새 캡처와 공존**(daemon 이라 종료는 되나 카메라 세션 2개 → 슬롯 한도 2 인 카메라에서 go2rtc 와 경합). `/cameras/{cid}/test` 는 요청 스레드가 30s 멈춤 | 코드 + 스위트 로그 | `OPENCV_FFMPEG_CAPTURE_OPTIONS` 에 `timeout;5000000`(µs, RTSP 소켓 타임아웃 — FFmpeg 버전에 따라 `stimeout`) 추가 → 5s 안에 실패. `/cameras/{cid}/test` 는 스레드+타임아웃으로 감싸 응답 보장. M5-1 과 같은 커밋·같은 검증 조건 |
| M5-3 | `routers/cameras.py:246-292` · `main.py _shutdown` | **중간** | `ensure_go2rtc()` 가 `Popen` 핸들을 버린다 → 서버 종료 시 go2rtc 를 정리하지 않음. 이전 인스턴스가 1984 를 잡고 있으면 새 서버는 "이미 실행 중"으로 재사용하는데, 런타임 yaml 은 **매 기동 템플릿으로 덮어써도 옛 프로세스는 다시 읽지 않는다**(등록 스트림 잔존). 1984 를 못 잡은 인스턴스는 고아로 남는다 | C4 실측: 고아 `go2rtc.exe` 2개(부모 종료됨) 발견·정리 | Popen 핸들을 모듈 전역에 보관, `_shutdown` 에서 우리가 띄운 것만 `terminate()`; 기동 시 포트 점유자가 우리 것이 아니면 경고 로그 |
| M5-4 | `worker.py:615` | 낮음 | `VideoCapture` 반환 직후 `isOpened()` 미검사 — 실패도 정상 경로로 들어가 5회 grab 실패(0.25s)+백오프를 거쳐서야 재연결. 로그에 "열기 실패" 대신 "스트림 끊김"으로 찍혀 원인 구분이 안 됨 | 코드 | `isOpened()` False 면 즉시 재연결 분기 + 로그 문구 구분("열기 실패(주소·자격증명·네트워크)") |
| M5-5 | `routers/cameras.py:35·46` vs `starvation_guard.py:54` | 낮음 | go2rtc API 주소가 `localhost`(cameras) / `127.0.0.1`(starvation) 혼용 — Windows 에서 `localhost` 는 `::1` 우선 해석, go2rtc 는 `127.0.0.1:1984` 만 리슨 → 첫 시도 거부 후 폴백(지연·간헐 실패 가능) | `config/go2rtc.yaml:20` | `127.0.0.1` 로 통일(1줄×2) |
| M5-6 | `run.ps1` vs `install_service.ps1` | 낮음(모듈 7) | 개발 실행은 `VIGENT_CAPTURE_MODE` 미설정 → **sync**, 서비스는 **thread** — 개발에서 못 보는 캡처 경로가 현장에서 돈다 | `run.ps1:3-10` · `install_service.ps1:126` | `run.ps1` 도 `thread` 기본(모듈 7 설정 통일에서) |
| M5-7 | `worker.py:329-338` (`_PoseModel.persons`) | 낮음 | 카메라 N대의 포즈 스레드가 같은 싱글톤을 **동시에 지연 로드**할 수 있다(락 없음) → 첫 프레임에 RTMPose 를 2회 로드하거나 부분 초기화 import 경합(M1-4 동류, CPU/ONNX 라 VRAM 영향은 없음) | 코드 | 로드에 `threading.Lock` |
| M5-8 | `routers/cameras.py:192-194` | 낮음 | 연결 테스트가 `apiPreference` 없이 `VideoCapture` → 웹캠 인덱스는 MSMF. `CAP_DSHOW` 를 쓰면 open 이 빠르고 hang 사례가 적다는 통설이 있으나 **이 PC 에서 미측정** | — | 정수 소스에 한해 `cv2.CAP_DSHOW` 지정(측정 후) — 5단계 |
| M5-9 | `worker.py` 전체 | 정보 | 손상 프레임(부분 디코드) 판별 없음. RTSP TCP 강제(:64)로 손실은 줄였고, 검출기가 아티팩트를 어떻게 보는지는 측정 없음 | — | 현 상태 유지(측정 항목으로 기록) |

### 5-4. 진행 현황(대표 승인 2026-09-06) — 커밋 2개
- **M5-3** ✅ `22e6a39`: go2rtc 핸들 + `data/go2rtc.pid` 추적, 우리 옛 인스턴스면 종료 후 재기동(yaml 재로드 대신), 남의 것이면 무접촉+경고, `_shutdown` 에서 우리 것만 종료, 로그 파일 핸들도 닫음(예전엔 미해제). 테스트 5(모킹).
- **M5-1·M5-2·M5-4·M5-5·M5-7** ✅ (커밋 대기). **실측(캡처 전용 독립 스크립트 `benchmarks/rtsp_capture_probe.py`, 서버·워커·경보 미사용, 옵션마다 새 프로세스)**:

  | 케이스(죽은 IP 192.168.0.251, ping 무응답 확인) | opened | 실패까지 |
  |---|---|---|
  | 구(`rtsp_transport;tcp\|max_delay;500000`) | False | **123.45 s** |
  | 신 FFmpeg 옵션(`…\|timeout;5000000`, FFmpeg 7.1 = avformat 61.7) | False | 98.81 s (**무효**) |
  | 신 + OpenCV `CAP_PROP_OPEN/READ_TIMEOUT_MSEC=5000` | False | **5.06 s** |
  | 워커 코드 경로 `worker._open_capture()` 직접(수정 후) | False | **5.05 s** (OpenCV 로그 "Stream timeout triggered after 5043ms") |

  → 원래 가정(30s)보다 훨씬 나빴다(cv2 5.0 은 기본 열기 타임아웃이 없음). FFmpeg 옵션 이름(`timeout`/`stimeout`)은 **연결 실패에 효과가 없어** OpenCV 속성으로 걸었다(`_RTSP_TIMEOUT_MS=5000`, env `VIGENT_RTSP_TIMEOUT_MS`/tuning `stability.rtsp_timeout_ms`). 스트림은 `CAP_FFMPEG`+타임아웃, 웹캠(정수)·파일은 기본 백엔드. `/cameras/{cid}/test` 는 같은 상수로 스레드 타임아웃(열기+읽기+1s). FFmpeg 옵션은 모듈 상단 한 곳(`_FFMPEG_CAPTURE_OPTIONS`, 저지연 포함)으로 단일화 — `_open()` 의 죽은 setdefault 제거. `isOpened()` 실패는 "열기 실패" WARNING(자격증명 마스킹). go2rtc 주소 `127.0.0.1` 통일(cameras 2·tapo 4). `_PoseModel` 지연 로드 락. 테스트 6.
  ★**(2) 실카메라 10초 수신 프레임 수·None 비율·첫 프레임 지연(저지연 옵션 전/후)은 대표 답변 "아니오"(카메라 미사용)로 이번엔 미측정 → 5단계 현장 검증 항목**(스크립트 `--live <cam_id>` 로 즉시 실행 가능, 자격증명 미출력). READ 타임아웃 5s 는 정상 스트림에서 "5초 넘게 프레임 없음 → 재연결" 이라 hang 15s 보다 먼저 잡힌다(동작 변화 — 현장 검증 항목에 포함).
- **M5-6** → 모듈 7. **M5-8·9** 문서만.
- **용량 스펙(FINAL_SUMMARY 배포 사양 절에 명시, 대표 지시)**: `DETECT_LOCK` 직렬화, 풀세트 ~85ms → 2fps 기준 **PC 1대당 카메라 약 5대 포화(RTX 5070 Ti 기준)**. 카메라 대수 확장(배치 추론 또는 다중 프로세스)은 다음 단계 항목. ★[M8-11, 2026-09-06] **시연 페이지(`/safety`·`/safety-local`) 동시 사용 시 카메라 여유 1대 감소** — 페이지가 `/detect/frame` 을 ≈6.6~9fps 로 불러 워커와 같은 락을 다툰다(index_hub 주석 실측 545ms). 관제는 `/hub` 를 쓴다.
## 6. 모듈 6 — 보존 스윕 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `retention.py` · `retention_scheduler.py` · `scripts/retention_sweep.py` · `data_engine.py`(pin·증거 경로) · `privacy.py` 저장 암호화 검사부 · `vlog.py` 회전 · `config/tuning.yaml retention` · `deploy/windows/install_service.ps1` 로그 회전 · 실측: `data/retention_status.json` · 디렉터리 크기 · 임시 디렉터리 시뮬레이션 2건.

### 6-1. 무엇을 언제 지우는가

| 대상 | 위치 | 삭제 주체 | 기준 | 설정 | 현 상태(2026-09-06 실측) |
|---|---|---|---|---|---|
| 증거 JPEG(얼굴 모자이크 적용본) | `data/evidence/<날짜>/` | `retention.sweep()` A그룹 | mtime > **30일**, pin 제외 | `retention.groups.evidence.days`(잠정값, 법률 검토 전) | 13,749개 945MB, 최고령 20.4일 → 약 10일 뒤 첫 후보 |
| 인식 로그(JSONL, 일 1파일) | `data/recognition/events_YYYYMMDD.jsonl` | A그룹 | mtime > **30일**(파일 단위) | 〃 | 18개 6.6MB |
| 감사·TBM·위험성평가서 | `data/{audit,tbm,risk_assessments}` | B그룹 | mtime > **1095일**(3년) | `groups.*.days` | 0 / 0 / 424개 |
| go2rtc 로그 · legal 차단 로그 | `data/go2rtc.log` 등 | `rotate_if_large()` D그룹 | > 50MB 면 `.1` 로 1회 회전(기동 시점만) | `retention.ops_log_max_mb` | 4.9MB |
| 앱 로그 | `logs/vigent.log`·`events.jsonl` | `vlog` RotatingFileHandler | 10MB × 5 / 10MB × 10 | 코드 고정 | 17.5MB |
| 서비스 stdout/stderr | `logs/vigent.{out,err}.log` + `-*` 회전본 | NSSM `AppRotateBytes` | 256MB 크기 기준 — **개수 상한 없음**(크래시 루프에 8,139개) | `install_service.ps1` | 55개 |
| 경보 큐 행(sent/dead) | `data/alert_queue.db` | **없음** | — | — | 87행(무한 누적) |
| 학습 산출·데이터셋·현장 원본 | `data/runs`(2.0GB, 체크포인트) · `data/datasets`(645MB) · `data/field_eval`(55MB, jpg 530) | **없음**(정책 밖) | — | — | 개인영상 가능성: `field_eval` jpg(현장 촬영) |
| 기동 실패 상태·PID·트랙 디버그 | `data/startup_failure.json` · `go2rtc.pid` · `track_debug.jsonl`(865KB, env 켤 때만) | 없음(작음) | — | — | — |

**주기·안전장치**: 서버 내 스레드(`retention_scheduler`) 기동 10분 뒤 첫 실행, 이후 **24시간**마다. 전체 스위치 `enabled`(true) · `dry_run`(false) · 첫 실주기 보류(후보 ≥1건인 주기를 한 번 보여준 뒤에야 다음 주기부터 삭제) · 화이트리스트(그룹 디렉터리 자체) 밖 삭제 거부 · 삭제 감사 로그 `data/retention/deletion_YYYYMMDD.jsonl`. 수동 CLI `scripts/retention_sweep.py --execute` 는 보류를 우회(명시 지시).
**개인정보 보존 기간 설정 여부**: 있음(A 30일·B 3년, tuning) — 단 코드 주석대로 **잠정값·법률 검토 전**이며 고객사별 조정 전제. 증거는 모자이크본만 저장(privacy P1a), 저장 폴더 암호화는 BitLocker/EFS **검사·노출만**(`/health privacy`).
**삭제 실패 시 동작**: 파일별 `OSError` → `warnings` 에 기록(status.json → `/health disk_retention.warnings`), 다음 주기(24h) 재시도. 스윕 자체 예외는 스케줄러가 잡아 `failures`·`last_error` 로 노출(스레드 생존). 통보는 없음.

### 6-2. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거 | 수정안 |
|---|---|---|---|---|---|
| **M6-1** | `retention.py:169-185` · `data_engine.py:27` | **높음** | **`pinned.json` 자체가 삭제 후보**가 된다 — pin 목록 파일이 `data/evidence/` 안에 있고 스캔이 `rglob("*")` 전체를 후보로 보며 pin 집합에는 자기 경로가 없다. 30일간 pin 변경이 없으면 목록 파일이 지워져 **모든 pin 이 풀리고** 다음 주기에 pin 했던 증거가 삭제된다 | 실측(임시 디렉터리 시뮬): 40일 된 `pinned.json` 이 후보 목록에 포함 | `scan_group` 에서 `pinned.json` 을 항상 제외(또는 pin 목록을 `data/evidence/` 밖으로 이동 — 이동은 기존 파일 마이그레이션 필요) |
| **M6-2** | `retention.py:181-183` · `data_engine.py:68·81` | **높음(Windows)** | pin 비교가 **경로 구분자를 정규화하지 않는다**. Windows 에서 증거 상대경로는 `data\evidence\...`(실측 인식 로그)인데, pin 이 `/` 로 들어오면(브라우저 URL·수동 입력) 매칭 실패 → **pin 된 증거가 삭제**된다 | 실측(시뮬): `/` 로 pin 한 파일이 후보에 포함 | 양쪽 모두 `Path(...).as_posix()` 로 정규화해 비교(저장도 posix) |
| **M6-3** | `data_engine.pin_evidence` | **중간** | pin 기능은 **호출부가 0건**(API·UI 없음, 테스트만) — "pin 하면 안 지워진다"는 안전장치가 운영에서 쓸 수 없다(규칙 11 유형: 절차·주석만 있고 장치 없음) | grep: `pin_evidence(` 호출 = data_engine 정의 + tests | `POST /recognition/pin` 류 라우트 + 대시보드 버튼(모듈 8) — 이번엔 라우트만 |
| M6-4 | `alert_queue.py` | 중간 | sent/dead 행을 **영구 보관**(삭제 경로 없음) — 현장 1년이면 수만 행, `/health counts()` 는 전체 GROUP BY 라 느려짐. 데드레터 사유(`last_error`)에 메시지 원문 포함 | 실측 87행 | `retention.sweep()` 에 "큐 행 30일"(B그룹 아님·개인정보 아님이라 별도 키 `alert_queue_days`) 추가 |
| M6-5 | `install_service.ps1:115-117` · `service_status.ps1` | 중간 | NSSM 회전본(`vigent.err-*`) **개수 상한 없음** — 크래시 루프가 8,139개(49.7MB) 만들었다. M4-5 로 루프 자체는 완화됐지만 정리 장치는 없음 | C4 실측 | 스윕에 `logs/` D그룹 추가: `vigent.{err,out}-*` 회전본 **최근 N개(50)만 유지**(크기 기준 아님) — 루프 흔적은 `service_status.ps1` 1h 검사가 먼저 잡음 |
| M6-6 | `data/field_eval` · `data/runs` · `data/datasets` | 중간(개인정보) | 정책 밖 디렉터리에 현장 촬영 jpg 530장(`field_eval`) 과 2.7GB 학습 산출이 있다. `field_eval` 은 현장 원본일 수 있어 보존 기간·암호화 검사 대상에 없음 | 디렉터리 크기 실측 | `field_eval` 은 `privacy._protected_dirs` 와 보존 그룹(A, 30일 또는 별도 일수)에 편입할지 대표 판단 — 학습 산출(runs/datasets)은 개인정보 아님, 디스크 관점만(수동) |
| M6-7 | `retention.py:158-187` | 낮음 | 스캔이 24시간마다 14k 파일 `rglob`+`stat` — 지금 945MB/13.7k 파일이면 문제없으나 10만 파일대에서 수십 초. 별도 스레드라 검출 영향은 없음 | — | 문서만(측정치 기록) |
| M6-8 | `retention.sweep()` | 낮음 | 삭제 실패·디스크 부족 경고가 **/health 와 로그에만** 남고 통보 없음(M4-2 요약 통보에 합류 가능) | 코드 | M4-2 `system/alert_dead` 처럼 `system/retention_warning` 1일 1회 통보(모듈 4 배선 재사용) |
| M6-9 | `retention_scheduler.py:73` | 낮음 | 첫 실행이 기동 10분 뒤·24h 주기 — 서비스가 매일 재기동되면(스케줄 재시작) 첫 10분 안에 죽는 경우 **영영 안 돈다**. `last_run` 08-26(11일 전)은 서버 미기동 때문이나 같은 지문. **★M4-5(크래시 루프 3주 미감지)와 같은 계열** — 프로세스가 10분을 못 넘기면 스윕도, 통보도 없다(서로 참조: §4-1 M4-5 ↔ 여기) | status.json 실측 | `next_run_at` 을 status.json 에 남기고 기동 시 마지막 실행이 25h 넘었으면 초기 지연을 1분으로 단축 — 모듈 7 기동 순서에서 재검토 |
| **R17** | (FINAL_SUMMARY 결정 필요) | — | **증거 30일은 법률 검토 전 잠정값** — 산업재해 증거 보존 기간은 법률 자문 필요(대표 지시 2026-09-06). FINAL_SUMMARY "결정 필요" 항목에 명시 | tuning 주석 | — |

### 6-3. 진행 현황(대표 승인·추가 지시 반영, 2026-09-06) — 커밋 4개
- **M6-1·M6-2** ✅ `69045db`: pin 목록 → `data/retention/pinned.json`(스윕 그룹 밖), 구 위치 1회 병합·이동(구 형식 list 호환), 이름이 `pinned.json` 이면 어디서든 후보 제외, 비교는 `resolve()` 절대경로 집합·저장은 posix 정규화. 테스트 5 + 기존 2건 계약 갱신.
- **M6-3·M6-10** ✅ `e7f7542`: `POST /recognition/pin`·`/unpin`(증거·인식 로그 아래만, 탈출 거부) + **자동 보존 규칙**: 발송(sent)된 critical/high 경보의 증거 JPEG·그날 `events_YYYYMMDD.jsonl` 을 사유 `alert:<id>` 로 pin(tuning `retention.auto_pin_sent_alerts`, 기본 true; 인식 로그도 pin 그룹 편입). 규모 62줄(≤100) → 같은 커밋. 테스트 5. UI 버튼은 모듈 8.
- **OpenAPI** ✅ `a34edc4`: 기준선 재생성 — 추가 2경로 + `/alerts/test` 설명 1줄. 108 → 110.
- **M6-4·M6-5** ✅ `54b0a27`: `alert_queue.prune(days=30)` — sent/dead 만(pending 불변), `config_error` 최신 1건 유지 · `retention.prune_rotated_logs(keep=50)` — `logs/vigent.{err,out}-*` 최신순 유지, logs/ 바로 아래만. 둘 다 `sweep()` 에 합류(dry_run·첫 주기 보류 그대로, status.json `alert_queue`·`logs` 항목). 테스트 5.
- **M6-6** ✅ `281fd81` + 정정 커밋: 대표 결정 = 이동 + 그룹 E(365일) + 보호 폴더. jpg 530장 → `VIGENT_DATA_DIR/field_eval`, 보존 그룹 `field_eval`(저장소 밖 그룹은 절대경로 표기), privacy 보호 폴더. **정정(대표 지시)**: git 추적 정답 라벨 116파일(txt·json·md)은 저장소 `data/field_eval` 로 복원·추적 유지(PII 아님, 평가 정답지로 버전 관리) — 사설 폴더는 jpg 만. 스크립트는 `data_paths.field_eval(rel)` 라우터(이미지 확장자·이미지 디렉터리 → 사설, 그 외 파일·labels* → 저장소) 로 25파일 92참조 통일, 컴파일·실경로 검증(frames 109·labels 110·pilot20 images 20/labels 21).
- **M6-7·8·9** 문서만(M6-9 ↔ M4-5 상호 참조 기재). **R17** 증거 30일 잠정값 → FINAL_SUMMARY 결정 필요 항목.
## 7. 모듈 7 — 설정·경로·기동 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `run.ps1` · `run.bat` · `VIGENT Safety 시작.bat` · `run.sh` · `deploy/windows/install_service.ps1` · `.github/workflows/ci.yml` · `vigent-core/main.py`(1~185 import·보안 게이트, 186~272 미들웨어, 274~483 안전망·기동실패·startup/shutdown, 486~559 정적 마운트) · `tuning.py` · `app_state.py` · `runtime_config.py` · `data_paths.py` · `vision_loader.py` · `vlog.py` · `starvation_guard.py` · `retention_scheduler.py` · `readiness.start_background` · `config/tuning.yaml`(전체) · `config/security.json` · `config/site.example.yaml` · `.env.example` · `deploy/academy/profile_intent.yaml`(앞부분) · `scripts/check_profile_drift.py`(비교 방식) · `guard.py:565~605`(RF_HOME·사전학습 검사) · `worker.py:38~101`(env/tuning 상수)·`1160~1182`(캡처 모드).

### 7-1. 기동 순서(확인)

| 단계 | 시점 | 내용 | 실패 시 |
|---|---|---|---|
| 0 | import | `.env` 로드(`main.py:33-37`, override 안 함) → `sys.path` 보정 → 라우터 import → **보안 게이트**(`main.py:162-185`: 외부 바인딩+무토큰 → `SystemExit(1)`) → 미들웨어 3개 → `/static`·`/evidence` 마운트 | 프로세스 종료(uvicorn 이전) |
| 1 | startup | `_install_safety_nets()`(스레드·메인·asyncio 훅) | — |
| 2 | startup | `_load_theme()` = vision.yaml 해석 + **에이전트 생성(guard 모델 로드·RF-DETR 사전학습 캐시 검사 `guard.py:584-605`)** | [M4-5] 상태파일·이벤트로그·통보 후 **재raise**(기동 실패) |
| 3 | startup | go2rtc 기동(`ensure_go2rtc`, M5-3) | 경고만(스냅샷 폴백) |
| 4 | startup | `readiness.start_background(on_ready=_start_workers_after_warmup)` — 예열 스레드, 성공 시 카메라 자동복원 + `VIGENT_EDGE` 자동시작 | 예외 시 아래 M7-3 |
| 5 | startup | `starvation_guard.start()` → `alert_queue.set_sender(remote_only)`+`start()` → `alert_notify.set_sender`+`start()` → `retention_scheduler.start()`(첫 실행 10분 뒤) | 같은 try 블록 — M7-3 |
| 종료 | shutdown | `manager.stop_all()` → `stop_go2rtc()`(M5-3). alert_queue·alert_notify·retention·starvation 스레드는 **정리 호출 없음**(데몬 스레드 종료) | 경고만 |

### 7-2. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거(실측) | 수정안 |
|---|---|---|---|---|---|
| **M7-1** | `config/tuning.yaml:4` · `:224` | **높음** | 최상위 `alerts:` 키가 **2번** 선언돼 있다. PyYAML `safe_load` 는 뒤 블록으로 덮어쓴다 → 4행 블록의 **8개 키(notify·notify_cooldown_s·backoff_factor·backoff_max_s·quiet_reset_s·max_per_hour·queue_max·guard_bypass_text)는 파일에 적혀 있지만 어떤 코드도 읽지 못한다**. 오늘은 코드 기본값(`alert_gate.py:54-76`·`alert_notify.py:40`·`dispatch.py:33`·`dispatcher.py:317`)이 파일값과 같아 동작 차이 0 이지만, 현장에서 이 8개를 바꾸면(예: 프레스 공장 문구·시간당 상한) **조용히 무시**된다 — 파일 1행의 약속("이 파일만 고치면 됨") 위반. 학원 프로파일은 4행 블록 자체가 없고(`tuning.academy.yaml:171` 만) 드리프트 게이트는 **파싱 결과**를 비교하므로 잡지 못했다 | 파싱 실측: `alerts == {max_attempts: 10, backoff_cap_s: 60}`(base·academy 동일). 도입: `758c270`(08-17 B5, 224행 블록) → `63cb7a1`(08-20 W1, 4행 블록 추가) — 17일 잠복. 키 대조 스크립트: 코드가 읽는 (섹션.키) 70 / yaml 65, 이 8개만 "파일엔 있는데 파싱 결과에 없음" | ① 게이트 테스트: 최상위 중복 키를 거부하는 로더로 base+academy 검사 ② 두 블록 병합(값 불변) ③ academy 프로파일에 8키 추가(드리프트 게이트 통과) |
| M7-2 | `run.ps1` ↔ `install_service.ps1:139-167` | 중간 | 개발 런처와 서비스의 환경변수 **4개 불일치**: `VIGENT_CAPTURE_MODE`(sync↔thread, M5-6) · `PYTHONUTF8`(없음↔1) · `RF_HOME`(`~/.roboflow/models`↔`weights/`, R7) · `TORCH_HOME`(rtmlib 기본↔`weights/rtm_cache`). 개발에서 못 보는 캡처 경로·인코딩·캐시가 현장에서 돈다 | 개발 PC 실측: `rf-detr-nano.pth` 가 `~/.roboflow/models` 와 `vigent-core/weights` **양쪽에 각 366,287,238 bytes(동일)** → 개발을 weights/ 로 돌려도 추가 다운로드 0. rtmlib 캐시는 `~/.cache/rtmlib/hub` 만 있고 `weights/rtm_cache` **없음** → 서비스 첫 검출 시 156MB 다운로드 경로(사전 조달 여부 M7-2b) | `run.ps1` 이 4개를 **미설정 시에만** 서비스와 같은 값으로 주입(셸에서 준 값은 우선). 테스트: PowerShell 파서로 `run.ps1` 이 4개 이름을 설정하는지 검사 |
| M7-2b | `install_service.ps1:159-165` · `scripts/fetch_weights.py` · `weights/MANIFEST.md:121` | 중간 | 서비스는 포즈(rtmlib) 캐시를 `weights/rtm_cache` 로 고정하지만 **조달 절차가 없다**: `fetch_weights.py` 에 rtmlib 항목 0건(grep), MANIFEST 는 pose 를 "미확인". 인터넷 없는 현장에서 서비스는 뜨지만 **첫 사람 검출에서 156MB 다운로드를 시도**한다(`install_service.ps1:160-164` 주석이 스스로 인정하는 경로) | 개발 PC: `weights/rtm_cache` 없음 · `~/.cache/rtmlib/hub` 있음 | `fetch_weights.py` 매니페스트에 rtmlib 2파일(yolox_m·rtmpose-m) 추가 + `--check` 가 `rtm_cache` 존재를 검사. 5단계 오프라인 검증 항목에 "카메라 물린 뒤 첫 검출" 추가(2026-08-21 재발 방지) |
| M7-3 | `main.py:450-482` | 중간 | 기동 try 블록이 거칠다: 예열 스레드 기동(4) 뒤 5단계 중 하나라도 예외면 except 가 `_start_workers_after_warmup()` 을 **즉시(콜드 모델)** 호출 → B4 가 막았던 "콜드 로드 hang → 재시작 폭주" 경로 부활 + 예열 완료 시 `on_ready` 가 **또** 호출(워커는 `manager.start` "이미 실행 중" 거부로 중복 없음, `worker.py:1317`) + 예외 지점 뒤의 배선(alert_notify·retention)이 건너뛰어져 **검출은 도는데 통보 없는** 상태가 WARNING 1줄로만 남는다 | 코드 구조(`try` 1개에 5개 서비스). 실사고 없음 | 서비스별 독립 try(각각 로그) + 워커 즉시 시작 폴백은 `readiness.start_background` 실패 시에만. 테스트: `alert_queue.start` 가 예외를 던져도 `alert_notify.start`·`retention_scheduler.start` 가 호출되고 워커 즉시 시작이 일어나지 않는다(모킹) |
| M7-4 | `main.py:33-37` · `run.ps1:9-10` · `.env.example:22-23` | 낮음 | `.env` 의 `VIGENT_HOST`/`VIGENT_PORT` 는 **효과가 없다**: `run.ps1:10` 이 VIGENT_HOST 를 항상 먼저 설정(`load_dotenv` 는 기존 env 를 덮지 않음), PORT 는 `run.ps1` 이 셸 env 만 읽어 uvicorn 인자로 준다. `.env.example` 은 VIGENT_HOST 를 `.env` 항목으로 안내. 토큰·REQUIRE_TOKEN·ALLOWED_HOSTS 는 `.env` 로 정상 동작(import 시 로드 후 `main.py:162·175·198` 읽음) | 코드 순서 | 문서 정정(`.env.example`: HOST/PORT 는 셸 환경변수만) 또는 `run.ps1` 이 `.env` 의 두 키를 읽음. 후자는 파서 추가 — 전자 권장 |
| M7-5 | `ci.yml:21-24` · `docs/ONBOARDING.md:16·25` | 낮음(R11) | CI 는 **Python 3.13**, `.python-version`=3.11.9·`pyproject` py311·README 3.11 — 스텝 이름 "(.python-version 정합)" 이 거짓. ONBOARDING §2.1 은 "3.13.9 고정·`/opt/anaconda3`"(mac 시절) → 문서 3중 불일치 | 개발 PC 실측: `python`=3.11.9 · `py -3.11`=3.11.9 · **py 기본(*)=3.14** · 3.13 없음 → CI 가 검증하는 인터프리터를 로컬 어디서도 못 돌린다. opencv: requirements `4.13.0.92 headless` vs 개발 PC `cv2 5.0.0` → M5 RTSP 타임아웃 실측(5.05s)은 5.0.0 기준, 4.13 미검증(5단계) | CI `python-version-file: .python-version` · ONBOARDING §2.1 정정 · opencv 버전 차이를 5단계 검증 항목에 추가 |
| M7-6 | `install_service.ps1:59-64` | 낮음 | 서비스 파이썬 선택 = `.venv` → PATH `python`(런처 `py -3.11` 아님). PATH 가 3.14 로 바뀌면 서비스가 미검증 인터프리터로 뜬다(`run.ps1` 은 `py -3.11` 정본 우선) | `py -0`: 3.14 가 기본 | 후보에 `py -3.11` 추가(run.ps1 과 동일 순서). 서비스 재설치는 5단계 뒤 |
| M7-7 | `proximity.py:87` · `worker.py:500·502·605` · `MATCH`·`HIST_S`·`_MIN_INTERVAL` · `camera_registry.py:76-90` | 중간(R15·§2-3) | 하드코딩 상수 7개(장비 크기 필터 0.9/0.7 · IMMOBILE_SPREAD 0.03 · 무동작 최소 샘플 5 · RAPID_T 1.0 · 매칭 0.32/0.18 · 이력 60s/소멸 3.0s · 자세 평가 0.5s) + **카메라별 override 구조 없음**(등록부 공개 필드 id·name·enabled·fps·zone·source·has_creds 뿐) → R15(앉아 작업 현장 무동작 45s 카메라별) 불가 | 코드 | ① `tuning.yaml` 에 코드 기본값과 **같은 값**으로 키 추가(동작 불변): `motion.immobile_spread/immobile_min_samples/rapid_window_s`, `proximity.vehicle_max_w/vehicle_max_area`, `track.match_dist/pose_match_dist`, `worker.pose_eval_min_s` ② R15: 등록부에 `overrides: {motion: {immobile_s}}` 1키만(워커가 `MotionTracker` 생성 시 반영) ③ academy 프로파일 동기(드리프트 게이트). 규모: 코드 ~60줄 + yaml + 테스트 |
| M7-8 | `retention_scheduler.py:42-44·73` | 낮음(M6-9) | 초기 지연 600s 고정 — 재기동이 잦으면 영영 안 돈다 | `status.json` 에 `last_run` 있음(`retention.py:360`) | 기동 시 `last_run` 이 `sweep_interval_s + 1h` 보다 오래됐으면 초기 지연 60s(설정 `sweep_overdue_delay_s`). ~25줄 + 테스트 |
| M7-9 | `config/tuning.yaml` | 낮음 | 코드가 읽지만 yaml 에 **없는** 키 11개(코드 기본값·미문서): `detect.evidence_cooldown_s/include_fire_smoke/include_forklift/pose_interleave`, `ppe.required`, `press.confirm_frames/kp_conf`, `privacy.face_conf`, `retention.auto_pin_sent_alerts/alert_queue_days/logs_keep_rotated`(모듈 6 추가분), `stability.cap_buffersize/rtsp_timeout_ms`(모듈 5), `zone.grid_cells` | 키 대조 스크립트 | 주석 형태로 기본값 기재(주석은 드리프트 게이트 무관). 문서만 |
| M7-10 | 환경변수 | 낮음 | 코어가 읽는 `VIGENT_*` **43개** 중 문서(.env.example·README·DEPLOYMENT·ONBOARDING·STABILITY)에 있는 것 **23개** → 미문서 20개(`VIGENT_ALERT_DB`·`LOG_DIR`·`LOG_LEVEL`·`THEME`·`DATA_DIR`·`DETECT_DEVICE`·`DETECT_BACKEND`·`ALERT_NOTIFY`·`RADIUS_M`·`CROWD`·`COLLECT`·`COLLECT_EVERY`·`TRACK_DEBUG`·`ZONE_GRID`·`STARTUP_GRACE`·`RTSP_TIMEOUT_MS`·`INCLUDE_FORKLIFT`·`INCLUDE_FIRE_SMOKE`·`ORT_TUNE`·`FAULT_STOP_DETECT`·`DEV_SYMLINK`·`LLM_MODEL`·`LLM_MAX_TOKENS`) | grep 집계 | `docs/ONBOARDING.md` 에 표 1개. 문서만 |
| M7-11 | `main.py:397·412` · `_shutdown` | 낮음 | `@app.on_event` 는 FastAPI 0.137 에서 deprecated(lifespan 권장) — 동작은 함. `_shutdown` 이 alert_queue·alert_notify·retention·starvation 스레드를 정리하지 않음(sqlite 쓰기 도중 종료 가능, 재기동 시 이월되므로 손실은 없음) | 코드 | lifespan 전환은 라우트 무변경이나 별도 작업 — 백로그. `_shutdown` 에 `alert_queue.stop()`·`alert_notify.stop()` 추가는 10줄 |

**정상 확인(수정 불필요)**: `runtime_config`(config/ 시드 읽기 전용·data/config 런타임 쓰기) · `vision_loader` 테마명 화이트리스트·가중치 폴백 해석 · `tuning.val` env 우선 규칙 · `security.json` 웹훅 목적지 화이트리스트 · `vlog` 10MB×5 회전(+NSSM stdout 회전, 모듈 6 정리와 분리) · `data_paths` 저장소 밖 미디어 · `VIGENT Safety 시작.bat` /health 대기 90s · `check_profile_drift` 가 게이트에 있음(단, M7-1 처럼 **파싱 전** 문제는 못 잡음).

### 7-3. 진행 현황(대표 승인 2026-09-06 반영) — 커밋 6개

| 커밋 | 항목 | 내용(실측) |
|---|---|---|
| `5ba2c31` | **M7-1** | 엄격 로더(중복 키·파싱 오류 → `TuningConfigError` = 기동 실패) · `alerts:` 두 블록 병합(값 불변) · 드리프트 게이트 검사 4 "파일 키 ⊆ 코드가 읽는 키"(정적 수집: 읽기 키 90, 섹션 통째 relay·retention, 미읽기 0) · academy 는 현행 safety 프로파일(08-19~08-28)로 확인 → 8키 추가. 테스트 8 |
| `7c0ca90` | **M7-2·2b** | `run.ps1` 미설정 시 4개 주입(서비스 동일 값, BOM/CRLF 유지) · rtmlib 2파일을 매니페스트 required 로(dest `rtm_cache/hub/checkpoints`, zip 1개 추출) · readiness 도 dest 인식 · **다운로드 실측 155.7MB / 14.4s** · SITE_CHECKLIST N-3 신설. 테스트 6 |
| `5cf638b` | **M7-3·11** | `_required`(예열·경보 큐·통보: 실패 → M4-5 경로 후 재raise) / `_optional`(go2rtc·기아·보존: `STARTUP_WARNINGS` → /health warnings) · 콜드 워커 즉시 시작 폴백 제거 · lifespan 전환 · 종료 시 4개 스레드 정리. 테스트 7 + 텍스트 계약 1 갱신 |
| `3114a12` | **M7-7(b)·R15** | 상수 7개(10키)를 tuning.yaml 에 같은 값으로 기재하고 트래커·proximity 가 생성/호출 시점에 읽음 · 등록부 `overrides.motion.immobile_s` 1키(검증·400·워커 state 노출). 테스트 8 |
| `4111dbd` | **M7-5·6·8·9 + 문서 M7-4·10** | CI `python-version-file` · ONBOARDING §1·§2.1·§2.6·DEPLOYMENT 표 3.11 통일 · `run.ps1` 3.11 전용(bare python 후보 제거, 3.11 검사, 없으면 안내 후 종료; run.bat·시작.bat 은 run.ps1 경유) · M7-8 `overdue()` → 초기 지연 60s(`sweep_overdue_delay_s`) + status.overdue · M7-9 미기재 읽기 키 14개 주석 기재 · `.env.example` HOST/PORT 무효 명시 · ONBOARDING §7 환경변수 표 43개 |
| — | **M7-6 서비스 파이썬** | `install_service.ps1` 후보 변경은 5단계 재설치와 함께(문서만) |

- 게이트: 매 커밋 ruff 0 · mypy 0 · unittest 589 → 595 → 602 → 610 → 616 OK · OpenAPI 무변경 · 프로파일 드리프트 없음.
- 부수 발견·처리: M7-2b 매니페스트 편집 중 readiness `required_weights_missing` 이 `dest` 를 몰라 예열 테스트 4건이 "가중치 없음"으로 실패 → dest 인식 추가(실사고였다면 서비스가 기동 거부).
## 8. 모듈 8 — 프론트 realtime_core.js 감시 화면 (보고 2026-09-06, 수정 대기)

**읽은 파일(전체)**: `vigent-core/static/realtime_core.js`(4,507줄 전부) · `themes/safety/index.html`(CDN판, `/safety`)·`index_local.html`(로컬 번들판, `/safety-local`)의 헤더·플래그·getUserMedia 가로채기(1~66·292·345~359·550) · `index_hub.html`(관제, `/hub`)의 영상·검출·구역 경로(150~445) · `routers/zone.py` 전체 · `routers/dispatch.py` · `agents/dispatcher.py:290~330`(relay) · `worker.py:1112~1135`(통보 submit) · `data_engine.list_events` · `templates/auto.html`·`static/auto_terminal.html`(증거 표시) · `routers/safety_core.py` 페이지 라우트(699~830).

### 8-1. 브라우저 검출 경로 vs 서버 경로 — 어느 쪽이 정본인가

| 화면 | 영상 입력 | 검출 | 위험구역 정의 | 통보·기록 | 판단 |
|---|---|---|---|---|---|
| **`/hub`** (index_hub.html, 관제) | go2rtc WebRTC → 실패 시 `/cameras/{id}/snapshot` | **브라우저 추론 없음** — `/cameras/{id}/detections` 폴링으로 워커 결과(tid 포함)만 표시(426~441행 주석: 같은 카메라를 워커가 검출하므로 자체 `/detect/frame` 은 DETECT_LOCK 경합 3.7 실측 545ms) | 카메라별 `/cameras/{cid}/zone` | 워커 → `alert_notify.submit(cam=카메라명)` + `data_engine.log_event` | **정본(운영)** |
| **`/safety`·`/safety-local`** (index.html·index_local.html + realtime_core.js) | `getUserMedia` 를 **가로채** go2rtc(Tapo) 스트림을 주입(index.html:19~63), 실패 시 웹캠 | 브라우저 COCO-SSD(700ms)+MobileNet(900ms)+MediaPipe Holistic + 서버 `/detect/frame`(최소 100ms 간격·루프 150ms ≈ 6.6~9fps, 주 탐지)·`/ppe/analyze-frame`(2.5s)·`/segment/frame` | **localStorage `ax_danger_zones` 우선**, 없으면 전역 `/zone/danger`(config/danger_zone.json) — 워커의 카메라별 구역(F5, 전역 폴백 차단)과 **다른 정의** | 브라우저 `handleDangerZone` → 3프레임 연속 + 8s 쿨다운 → `POST /zone/intrusion`(합성 스냅샷) → `log_event` + `submit(cam="browser_zone:위험구역A")` | 구 AX/BODA 3테마 엔진의 **데모·시연 화면**. 판정·통보 권한을 가지면 안 된다 |

**결론**: 서버 워커 경로가 정본이다. 브라우저 경로는 같은 카메라를 두 번째로 판정하는 **별도 정의(구역·임계·쿨다운 전부 다름)** 이며, 운영 화면(`/hub`)은 이미 브라우저 추론을 쓰지 않는다. `/safety` 계열은 시연 전용으로 격을 낮추고 통보·기록 경로를 서버 판단 아래에 두는 것이 맞다(M8-1).

### 8-2. 발견 사항

| ID | 파일:줄 | 심각도 | 문제 | 근거(실측) | 수정안 |
|---|---|---|---|---|---|
| **M8-1** | `realtime_core.js:1852·1926` · `zone.py:74` · `worker.py:1125` | **높음**(M3-8 확정) | **이중 통보**: 같은 카메라(go2rtc 가로채기)에서 브라우저는 `browser_zone:위험구역A`(payload 에 cam 없음 → 구역 이름), 워커는 `cam=<카메라명>` 으로 submit → 게이트 키가 달라 **둘 다 통보**되고 `log_event` 도 두 번(증거 2장). 타이밍도 다르다(브라우저 3프레임+8s, 워커 `zone.enter_s` 1.0s) | 코드 경로 대조. 실제 2건 발송은 현장 카메라 연결 시 확인(5단계) | (b) 권장: `/zone/intrusion` 에 `cam` 필수화 + 서버가 "등록 워커가 감시 중인 카메라" 면 **기록만 하고 통보는 워커에 위임**(응답 `gate="worker_owned"`); 워커 없는 카메라(웹캠 데모)만 브라우저 통보 허용. 선행 테스트 3건 |
| **M8-2** | `realtime_core.js:3122·3166·2112·2126·4415·4445·1668·1084` · `zone.py:34~37` | **높음**(R2) | 서버에 **없는 경로 8개**를 부른다: `/llm/vision`·`/llm/status`·`/vision/capabilities`·`/vision/analyze-current`·`/sensor/temperature`·`/alert/overspeed`·`/vitals/rppg`·`/dataset/small-object/crop`. ① LLM 분석 버튼은 항상 "❌ 서버 LLM 오류: 404"(`runLLMAnalysis` 는 `analyzeWithServerVision` 만 호출) ② **열화상 과열 경보·과속 경보는 `.catch(()=>{})` 로 조용히 실패** — 화면엔 경보가 뜨는데 텔레그램은 없다(규칙 11 "지어낸 완료") ③ `/zone/state` 는 스텁(`{ok, state:"idle"}`)인데 UI 는 "E-stop 보조정지 신호" 라고 부른다 | 라우트 grep: 8경로 `@router` 0건 · `/zone/state` 스텁 본문 | 서버에 없는 기능은 **UI 에서 제거하거나 "미구현" 표시**(버튼·토글 숨김). `/llm/vision` 은 `scene_vlm`(VIGENT_CLOUD_VLM 게이트)로 배선하거나 버튼 제거 — 브라우저가 입력받은 API 키를 서버로 보내 클라우드 전송하는 구조는 F-12(프레임 불유출) 원칙과 충돌 → 제거 권장. E-stop 문구 삭제 |
| M8-3 | `realtime_core.js:3065~3119` | 중간 | 브라우저 → `api.anthropic.com`·`api.openai.com`·`generativelanguage.googleapis.com` 직접 호출 함수 3개(`anthropic-dangerous-direct-browser-access` 헤더 포함) — **호출부 0** 인 죽은 코드지만 프레임+키를 외부로 보내는 코드가 남아 있다(F-12 위반 잠재·키 노출 경로) | 호출부 grep 0 | 삭제 |
| M8-4 | `realtime_core.js` 전반 | 중간 | **삭제된 테마(Z-3) 잔재**: `SERVICE_META` fitness/office, 스쿼트 카운터·운동 분석, rPPG 심박(얼굴 ROI), 사무 자세, **성별·연령·감정 추정**(`estimateGender/estimateAge/detectEmotion` — 개인정보 민감 추정), 상업화 점검표·세션 리포트, 골프/요가/복싱 프롬프트, 열화상 — 함수 **28개**, `activeServiceMode` 분기 **33곳**(실측). 안전 단일 제품 결정과 불일치, 성별/연령/감정 추정은 개인정보 관점에서 제거 대상 | grep 집계 | 규모가 커서 대표 판단: (a) 안전 경로만 남기는 정리 커밋(위험: 회귀, 시연 화면 검증 필요) (b) 성별·연령·감정·클라우드 직접호출만 제거 (c) 문서만. 권장 (b) 지금 + (a) 는 모듈 8 후속 |
| M8-5 | `realtime_core.js:801~824` | 중간 | 브라우저 PPE 휴리스틱: ImageNet 분류에 positive 키워드가 없으면 **예측이 하나라도 있으면 '미착용 의심'(conf ≥0.45)** 반환(819~822행) → 백엔드 PPE 결과가 없을 때 화면이 거의 항상 "미착용 의심" — 시연 신뢰 저하(통보는 안 나감, 화면 배지·리포트만) | 코드 | 브라우저 휴리스틱 제거, 백엔드(`/ppe/analyze-frame`·`/detect/frame` NO-* 클래스)만 표시 |
| M8-6 | `realtime_core.js:1841~1849` | 중간 | 침입 증거가 **영상+오버레이(박스·스켈레톤·구역·라벨) 합성 캔버스**로 저장된다 → 증거 JPEG 에 그린 선이 들어감. 워커 증거는 원본(+모자이크) | 코드 | 원본 프레임만 전송(오버레이는 화면 전용). 서버 모자이크는 그대로 적용됨 |
| M8-7 | `realtime_core.js:2382·2388` | 낮음 | 디버그 텔레메트리(`coord_mismatch`·`coord_event`)를 **안전 이벤트 로그**(`/recognition/log`)에 기록 | 실측: 인식 로그 23파일 25,433행 중 coord_* **0행**(카메라 전환·리사이즈 때만 발생) — 다만 **rule='t' 194행**(2026-08-24, note '정상', level low) 발견, 출처 미상(프론트·서버 grep 0) | 디버그는 console 만. `/recognition/log` 는 규칙 화이트리스트(guard 규칙명 + browser 규칙명)로 잡음 차단 |
| M8-8 | `templates/auto.html:43~46` · `static/auto_terminal.html:74` | 중간(M6-3) | **pin/unpin 버튼 부재** — 자동처리 콘솔은 `evidence_url` 만 표시. `list_events` 레코드에 `evidence`(상대경로) 있음 | 코드 | 이벤트 행에 "📌 보존/해제" 버튼 → `POST /recognition/pin|unpin {path}`, pin 상태는 `pinned_map()` 을 이벤트 목록 응답에 실어 표시. HTML+JS ~30줄 |
| M8-9 | `routers/dispatch.py:3·17` · `dispatcher.py:309` | 중간 | **`/dispatch/relay` 호출부 0** — 문서는 "guard_bypass(critical) 시 프론트가 호출"이지만 realtime_core.js·hub 어디에도 없고, 서버 `dispatcher.relay()` 호출부도 0(safety_manager 는 문자열 스텁). **실제 §8 보조 방호신호는 다른 경로로 산다**: 워커 guard_bypass → `submit(critical)` → `dispatch` → `on_severity.critical` 기본값 `["alarm","manager_call","safety_relay_signal"]`(dispatcher.py:131~132) → `relay.turn_on`(relay.enabled 일 때). notify.yaml 에는 `on_severity` 키가 없어 기본값 적용(값 미출력) | 코드·설정 키 확인 | `/dispatch/relay` 를 "수동 시험용" 으로 문서화하고 docstring 의 "프론트가 호출" 정정. 자동 경로는 5단계에서 relay.enabled=true 현장 시험 항목 |
| M8-10 | `index.html:346` · `index_local.html:359` | 낮음 | 스크립트 캐시 버전 `?v=20260701-ppefix` 고정(2개월 전) — `_no_cache_dynamic` 미들웨어가 .js 를 no-store 로 내려 실제 영향은 없음 | 코드 | 버전 문자열 제거 또는 product_version 주입. 문서 |
| M8-11 | `realtime_core.js:172~176·2692~2697` | 낮음 | 브라우저 페이지가 열려 있으면 `/detect/frame` 을 ≈6.6~9fps 로 호출(+PPE 2.5s) → 워커(2fps 풀세트)와 `DETECT_LOCK` 경합. 모듈 5 용량 스펙(카메라 ~5대)은 **브라우저 페이지 미포함** | index_hub 주석 실측 545ms | 용량 스펙에 "시연 페이지 동시 사용 시 −1대" 주석. FINAL_SUMMARY 용량 항목에 병기 |

**정상 확인(수정 불필요)**: `/hub` 는 브라우저 추론 없이 워커 결과만 표시 · `/zone/intrusion` 은 M3-3 게이트 적용 · 브라우저 프레임은 로컬 서버(`/detect/frame` 계열)로만 전송(클라우드 직접 호출은 죽은 코드) · MediaPipe 실패 시 폴백 렌더에서도 침입 판정 실행(2559~2561) · 세그·포즈는 detect 호출에 통합(중복 인코딩 없음).

### 8-3. 진행 현황(대표 승인 2026-09-06 반영)
- **M8-4(b)** ✅ (커밋 대기) 삭제 목록(realtime_core.js 4,507 → 4,397줄):
  - 민감정보 추정: `estimateGender(f)`(얼굴 폭/턱 비율로 남녀 추정), `estimateAge(f)`(눈·이마·코턱 비율 5항목 점수 → 어린이/청소년/청장년/중장년), `detectEmotion(f)`(입·눈 개방도 → 기쁨/중립/놀람/졸음). 호출부 5곳(`updateFaceUI`·`buildCoreFrameState`·`generateNarrative`·`updateEasyScene`·`updateSceneUI`)은 "미추정(개인정보)" 고정 문구로 대체(패널 요소는 유지, 시선 방향·눈 감김·졸음 주의는 안전 관련이라 유지).
  - 클라우드 직접 호출: `analyzeWithClaude`·`analyzeWithOpenAI`·`analyzeWithGemini`(`anthropic-dangerous-direct-browser-access` 헤더 포함) — 호출부 0 이었음.
  - 게이트: `tests/test_frontend_privacy.py`(금지 심볼·도메인 정적 검사 + node `--check` 구문 검사, node 24.19 실측). (a) "안전 경로만 남기는 정리"는 다음 단계.

### 8-4. 진행 현황(대표 승인 2026-09-06, 커밋 순서 M8-4(b) → M8-3·5·6·7 → M8-1 → M8-2 → M8-8)

| 커밋 | 항목 | 내용(실측) |
|---|---|---|
| `f422dcd` | **M8-4(b)** | 성별·연령·감정 추정 3함수 + 클라우드 직접 호출 3함수 삭제(4,507→4,397줄). 정적 게이트 `test_frontend_privacy.py` |
| `2086e49` | **M8-3·5·6·7** | 클라우드 직접호출 잔재 0 재확인 · PPE 휴리스틱 폴백 제거 + '참고(서버 판정 아님)' 문구, 통보 경로는 서버 판정(ppe_yolo)만 · 증거 원본 프레임 + 오버레이 `*_overlay.png` 분리(`data_engine.save_overlay`) · `/recognition/log` 규칙 화이트리스트(RULE_KB 18 + 2, 그 외 400) + `source` 꼬리표 · 프론트 디버그 텔레메트리 콘솔만. 테스트 5 |
| `51b188d` | **M8-1(M3-8)** | `/zone/intrusion` cam 필수(400) · `_worker_owns`: 실행 중 워커 id 또는 go2rtc 고정 스트림(`config/go2rtc.yaml`, `${RTSP_URL}` 확장) 소스 일치 → **기록만(증거 1장·source=browser)·통보 워커 위임(gate=worker_owned)** · 비소유(시연·웹캠)만 브라우저 통보 · 페이지 `window.VIGENT_CAM_ID`. 테스트 7(같은 카메라 브라우저+워커 → 통보 1·증거 1 포함) |
| `7ec9509` | **M8-2(R2)** | 서버에 없는 경로 9개(404 8 + 스텁 1)를 `UNIMPLEMENTED_SERVER_PATHS` 로 묶고 fetch 0 · LLM/비전능력/손크롭/rPPG 함수는 명시적 미구현(안전 페이지엔 해당 UI 요소 자체가 없음 — 실측 0) · 열화상 과열·과속은 화면 배지 '통보 미구현' + 콘솔 안내 · E-stop 문구·하트비트 제거. 테스트 3(서버에 라우트가 생기면 알려 주는 검사 포함) |
| (대기) | **M8-8(M6-3)** | 콘솔 2화면(`templates/auto.html`·`static/auto_terminal.html`) 📌 보존/해제 버튼 → `POST /recognition/pin|unpin {path}` · 피드가 `evidence`(상대경로)·`pinned` 를 실음. 테스트 2(왕복·정적) |
| (문서) | **M8-9** | `/dispatch/relay`·`dispatcher.relay()` 호출부 0 — 실제 §8 보조 방호신호는 워커 guard_bypass → `submit(critical)` → `dispatch` 의 `on_severity.critical` 기본 액션 `safety_relay_signal` → `relay.turn_on`(relay.enabled 시) 경로로 산다(notify.yaml 에 on_severity 없음 → 기본값). `/dispatch/relay` 는 **수동 시험용**으로 docstring 정정. 5단계: relay.enabled=true 현장 시험 |
| (문서) | **M8-10** | 스크립트 캐시 버전 `?v=20260701-ppefix` 고정 — `_no_cache_dynamic` 이 .js 를 no-store 로 내리므로 실영향 없음. 정리는 (a) 정리 커밋 때 |
| (문서) | **M8-11** | §5 용량 스펙에 "시연 페이지 동시 사용 시 카메라 여유 1대 감소" 병기(FINAL_SUMMARY 용량 항목에도) |

- 정정 M6-6(`c23e2fc`): 정답 라벨 116파일 저장소 복원(PII 아님) — §6-3 참조.
- (a) "안전 경로만 남기는 정리"(SERVICE_META fitness/office·스쿼트·rPPG·사무 자세·상업화 점검표·골프/요가/복싱 프롬프트 등 함수 28개 중 잔여 22개) 는 다음 단계.
