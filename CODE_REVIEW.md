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
- **중간 M1-5**: 대표 결정 대기(동작 변경·재측정 동반) — "앞서 승인한 대로"가 이 항목의 **수정 승인**인지 **백로그 유지**인지 명시 필요.
- **낮음 M1-8·M1-14**: 포매팅 커밋 1개(로직 커밋과 분리).
- **정정 M1-2·M1-3·M1-9**: 코드 무수정, `audit/c4_smoke_2026-09-06.md` §1·§2·§6 정정 완료.
- **R12 flaky**: 이름 포착·원인·수정(§0 R12) — 테스트 전용 커밋.

---

## 2. 모듈 2 — 5개 감지 규칙 (대기)
## 3. 모듈 3 — 오경보 억제 (대기)
## 4. 모듈 4 — 통보(dispatcher·텔레그램·기동 실패 알림) (대기)
> 예약: M1-3 후속 — `data/alert_queue.db` pending 15건(2026-08-28)이 재시도 스레드에 의해 sent/dead로 옮겨지지 않은 원인.
## 5. 모듈 5 — 카메라 입력·go2rtc (대기)
## 6. 모듈 6 — 보존 스윕 (대기)
## 7. 모듈 7 — 설정·경로·기동 (대기)
## 8. 모듈 8 — 프론트 realtime_core.js 감시 화면 (대기)
