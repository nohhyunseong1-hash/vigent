# 코드 감사 — 하드코딩·충돌·오류·증강 설정 (2026-09-28, 목록만 · 수정 없음)

> **범위**: `vigent-core/ scripts/ configs/ config/ deploy/ themes/` (tests·docs·audit·runs 제외). **수정하지 않았다.** 산출물은 이 문서와 증강 대조군 설정 초안 `configs/finetune_field_v2_aug.yaml`(실행 안 함) 둘뿐이다.
> **방법**: rg 로 후보를 뽑고 주변 코드를 읽어 실제 하드코딩·결함인지 확인했다. 재현이 되는 것은 개발기에서 **실행해서 확인**했고 그렇게 표시했다(`[실행 확인]`). 코드만 읽고 판단한 것은 `[코드 근거]`. 값·줄 번호는 커밋 `0dfe957` 기준.
> **심각도**: **H** 판매·설치·알림·검출 결과에 직접 영향 / **M** 조건부(설정 누락·환경 변화) 영향 / **L** 정리·문서.
> **우선순위 규칙**: 판매·설치(설치 스크립트·알림·어댑터·프로파일) → 학습·평가 → 문서. §0 상위 10건에는 수정안을 붙였고, 나머지는 목록이다. **수정은 다음 승인 후.**

---

## 0. 상위 10건 (판매·설치 영향 순, 수정안 포함)

| # | 심각도 | 무엇 | 파일:줄 | 재현 · 확인 | 수정안 |
|---|---|---|---|---|---|
| 1 | **H** | **경보 경로의 조용한 유실 3곳** — ① 센서 위험 전이를 submit **전에** 소비(`_SENSOR_DANGER[key]=danger` 뒤 submit 이 gate·queue_full·예외로 막혀도 전이는 사라져 위험 구간에 머무는 동안 다시 안 나감) ② 큐 선기록(`alert_queue.enqueue`) 실패를 로그 없이 `row_id=None` 으로 삼킴 → 즉시 전송까지 실패하면 재시도·데드레터 없이 영구 소실 ③ `alert_notify.stop()` 이 메모리 큐 잔여 항목을 버림(선기록은 스레드 안에서 하므로 DB 에도 없음) | `vigent-core/routers/safety_core.py:538-557` · `agents/dispatcher.py:371-375,378-385` · `alert_notify.py:51-55,91-106` | [코드 근거] ①은 submit 이 `queued=False` 를 돌려주는 조건(시간당 상한 6건)에서 재현 가능 | ① `queued=True` 일 때만 전이 확정 ② `_LOG.error` + `/health` 카운터 `enqueue_fail` ③ stop 시 잔여를 `alert_queue.enqueue` 로 이월하고 개수 로그. 각각 테스트 1건 |
| 2 | **H** | **릴레이(사이렌)가 종료·실패 경로에서 빠짐** — `_shutdown` 에 `relay.turn_off()` 없음(자동 해제 Timer 는 daemon) · OFF 최종 실패 시 `off_failed=True` 만 남기고 재시도 없음 · OFF 재시도(최대 ≈90 s) 동안 `_lock` 을 쥐어 통보 스레드의 `turn_on` 이 막힘 | `vigent-core/main.py:419-442` · `relay.py:132-151` | [코드 근거] `grep turn_off main.py` 0건 | `_shutdown` 첫 단계에 `relay.turn_off("서버 종료")` · off_failed 면 지수 백오프 Timer 재시도 + 알림 · HTTP 호출은 락 밖에서 |
| 3 | **H** | **설치 마법사 기본 프로파일 `academy`** + **포터블 기본 오버라이드가 학원 결정**(근골격 OFF·화재 OFF, 사유 문구 "학원…" 이 /health 에 노출) — 신규 고객 설치가 학원 규칙(마스크 제외)로 시작 | `scripts/deploy/setup_wizard.py:168` · `deploy/portable/portable_overrides.yaml` · `vigent-core/worker.py:139-140` | [코드 근거] 마법사에서 Enter → academy | `default="default"` · 오버라이드를 `deploy/academy/` 로 이동, 포터블 기본은 전역값 · 사유 문구는 프로파일 yaml 에서 주입 |
| 4 | **H** | **서비스 자가 재기동·종료가 자기 손으로 깨질 수 있음** — 기아 3단계 `VIGENT_RESTART_CMD='sc.exe stop X & sc.exe start X'` 를 서비스의 자식 cmd 가 실행하면 NSSM 이 프로세스 트리를 죽여 `sc start` 가 안 돌 수 있음(반환값 미확인) · NSSM `AppStopMethod*` 미설정이라 기본 ≈1.5 s 뒤 강제 종료인데 `_shutdown` 은 카메라당 최대 8 s 순차 + go2rtc 5 s + 큐 2~3 s → 정리가 중간에 잘림 · Linux `systemd` `ExecStart` 가 없는 파일(`bin/vigent-edge.command`, bin 에는 `vigent-serve.sh` 뿐)을 가리킴 · `watchdog.sh` 는 예열 중 503 을 실패로 보고 30 s 마다 재기동(무한 루프) | `deploy/windows/install_service.ps1:148-163` · `vigent-core/starvation_guard.py:100` · `deploy/systemd/vigent-edge.service:24` · `deploy/watchdog.sh:17-20` + `vigent-watchdog.timer:9-10` | [코드 근거, **실기 미검증**](설계서도 "실기 등록 미검증") | 3단계는 `os._exit(3)` 로 NSSM AppExit Restart 에 맡김 · `nssm set AppStopMethodConsole 30000` + stop_all 병렬화·데드라인 · ExecStart 를 `bin/vigent-serve.sh` 로 · watchdog 은 `phase=="starting"` 이면 OK 또는 재기동 후 120 s 유예. 관리자 셸 실기 1회(NEXT.md #5) |
| 5 | **H** | **설치 스크립트 고정값·인자 전달** — `install.ps1:186` 이 `-File … -ExtraEnv $extra` 로 **배열**을 넘겨 첫 값만 바인딩되고 나머지가 위치 인자(ServiceName·LogMaxBytes)로 흘러갈 수 있음 · `C:\VIGENT` 4곳·`8010` 20곳 고정이라 `-Target/-Port` 를 바꾸면 마법사·인수시험(`acceptance_test.py:233`)이 엉뚱한 곳을 봄 · 설치 기본 바인드 `0.0.0.0`(main.py 기본 127.0.0.1)인데 토큰 필수 검사 없음 · `설치.bat` 이 작업트리에서 LF 로 복사됨(.gitattributes 는 CRLF, renormalize 안 됨) | `scripts/deploy/install.ps1:24-26,186` · `deploy/usb/설치.bat:36` · `acceptance_test.py:233` · `deploy/windows/install_service.ps1:37` · `git ls-files --eol` | [코드 근거, 실기 미검증] | `& $isv -ExtraEnv $extra` 직접 호출 · install.ps1 이 `install_result.json`(Target·Port) 을 쓰고 마법사·인수시험이 읽음 · 바인드 질문 기본 "아니오" + 0.0.0.0 이면 `VIGENT_API_TOKEN` 필수 · `git add --renormalize` + build_usb 에서 CRLF 검증 |
| 6 | **H** | **코드 기본값 ≠ yaml + 초기화 순서 버그** — `DETECTOR_CONF={"person":0.35,"ppe":0.55,"forklift":0.55,"fire_smoke":0.70}`·`IMGSZ=960` vs tuning 0.40/0.35/0.002(academy 0.50)/0.55·384 → tuning 키 누락 시 조용히 다른 운용점 · `detect.hysteresis_frames>0` 이면 `self.HYSTERESIS` 를 470행에서 만들기 전에 413행이 참조 → **AttributeError 로 Guard 초기화 실패**(통과해도 470행이 덮어씀) | `vigent-core/agents/guard.py:253-254,411-413,470` vs `config/tuning.yaml:88,102-117` | [코드 근거] tuning 에 `detect: {hysteresis_frames: 2}` 넣고 기동 | 기본값을 yaml 과 같게(384·0.40·0.35) + `vigent-core/defaults.py` 로 모아 guard·rfdetr_service·scripts 가 import, 키 누락 WARN · `self.HYSTERESIS=dict(...)` 를 tuning 블록 앞으로 + 반영 테스트 |
| 7 | **H** | **`notify.example.yaml` 스키마가 dispatcher 와 다름**(`telegram.bot_token`·`sites`·`AX_TELEGRAM_BOT_TOKEN` vs 평면 `telegram_token`/`telegram_chat`·`TELEGRAM_BOT_TOKEN`) — 예시대로 쓰면 알림이 안 나감 · notify.yaml **파싱 오류**도 `cfg={}` 로 삼켜 "미설정" 으로만 보임 | `config/notify.example.yaml:1-8` vs `vigent-core/agents/dispatcher.py:43-44,52-61` | [코드 근거] 예시를 복사해 토큰 기입 → 자가시험 config_error | 예시를 실제 키로 재작성 + 로드 테스트 1건 · 파싱 실패는 ERROR 로그 + selftest `config_error("notify.yaml 파싱 실패")` |
| 8 | **H** | **워커 stop 이 join 결과를 확인하지 않음** — `join(timeout=5)` 뒤 무조건 `running=False` → cap.read 가 막혀 있으면 옛 루프가 살아 있는데 구역 저장(`cameras_zone_set`)·기아 재시작이 **두 번째 Worker 를 띄워** RTSP 세션 2개(카메라 한도 2)·중복 경보. hang·pose 스레드는 join 안 함. 캡처 스레드도 같은 패턴(`worker.py:738-741`) | `vigent-core/worker.py:834-839,738-741` · `routers/cameras.py:248-249` · `starvation_guard.py:82-84` | [코드 근거] | stop 에서 `cap.release()` 로 언블록 → join 확인 → 살아 있으면 running 유지·오류 반환. manager.start 는 `_thread.is_alive()` 로 판정. 테스트: 막힌 read 를 흉내내 stop 이 False 를 돌려줌 |
| 9 | **M** | **슬롯 클래스 허용 목록·로드 검증 없음** — forklift 슬롯(fk510_smoke `['person','forklift']`)의 `person` 이 최종 검출에 섞임: 109프레임 실측 **29개/27프레임**(person_count 106=106 로 수는 같고 출처만 바뀜, `detector="forklift"`) · 어댑터·평가기는 체크포인트 `class_names` 를 검증 없이 믿음(슬롯 가드는 학습 경로에만) | `vigent-core/agents/guard.py:931-1063` · `detectors/rfdetr_adapter.py:238,276-283` · `scripts/eval/eval_v1_heldout.py:239` | [**실행 확인** 2026-09-28: 학원 프로파일·field_eval 109프레임] | vision.yaml `rfdetr_classes: {forklift: [forklift], fire_smoke: [fire, smoke]}` + 어댑터 드롭 + 로드 시 `expected ⊆ class_names` 아니면 DEGRADED(/health 사유). 평가기 `make_predictor` 도 같은 검사. 테스트 2건 |
| 10 | **H(학습)** | **학습 정체 감시 스레드에 중지 경로가 없음** — `while True … os._exit(9)` 가 `m.train()` 이 끝난 뒤 verify·하네스 subprocess(`:752`)·동기 held-out 평가 중에도 돌아, 체크포인트 폴더가 15분 안 바뀌면 **거짓 STALL_ABORT 로 부모를 강제 종료**(하네스 자식은 고아). `_nonfinite` 의 `except: return False` 는 NaN 가드 fail-open | `scripts/train/finetune_rfdetr.py:413-436,295-306,723,752` | [코드 근거] fk510 하네스 9분·PPE 하네스는 15분 미만이라 아직 안 터짐. `--dev74` 포함 하네스나 현장 held-out 300+음성 평가가 15분을 넘기면 재현 | `threading.Event` 를 돌려주고 `m.train()` 직후 set · 중간 평가 중 heartbeat touch · 루프 전체 try/except · `_nonfinite` 예외는 True(의심) |

그 다음 순위(수정안은 §부록 A): `/tmp`(Windows `	mp`, imwrite 반환 미검사) · `copilot.py:104-111` 법령 게이트 fail-open · `worker.py:388-403` RTMPose 로드 실패 영구 침묵 · `rfdetr_service.py:190-197` VLM 대기 중 `DETECT_LOCK` 보유(모든 워커 검출 정지) · `routers/cameras.py:306-314` `psutil` 미의존(go2rtc 고아를 남의 것으로 오판) · `vlog.py:41-47` 로그 파일 생성 실패 침묵 · `bench_with_sink.sh:17` MSYS PID 로 `taskkill /F` · `bench_4ch.py:302` `terminate()`(go2rtc 고아).

## 0-1. 수정 완료 상태 (2026-09-28, 승인 A 그룹 10건 + B-1 · B 그룹 5건 · C 그룹 2건)

항목마다 테스트 1건 이상 + 게이트(ruff·mypy·unittest·OpenAPI 110) 통과 후 커밋. 브랜치 `audit/cleanup-20260906`, 원격 동기화.

| 항목 | 커밋 | 테스트 파일 | 비고 |
|---|---|---|---|
| #1 경보 유실 3곳 | `6df1ef6` | `test_audit_fix1_alert_loss.py`(6) | 전이 확정은 queued=True 일 때만 · enqueue_fail 카운터 · stop 시 이월 |
| #2 릴레이 종료·재시도 | `f40596d` | `test_audit_fix2_relay.py`(4) | _shutdown 첫 단계 OFF · 지수 백오프 · HTTP 락 밖 |
| #3 학원 전용 값 분리 | `75b6285` | `test_audit_fix3_profile.py`(8) | 마법사 기본 default · deploy/academy 오버라이드 · 사유 주입 · ★이 커밋이 build_portable.ps1 BOM 을 글자로 써 파싱 불가 회귀 → #5 에서 수정 |
| #7 notify.example.yaml | `4edb5af` | `test_audit_fix7_notify_example.py`(3) | 평면 스키마 · 파싱 실패 config_error |
| #6 defaults.py | `aecc5d3` | `test_audit_fix6_defaults.py`(5) | 코드 기본값 = yaml · HYSTERESIS 순서 |
| #8 워커 stop join | `69166e1` | `test_audit_fix8_worker_stop.py`(5) | stop_pending · manager is_alive · 재기동 보류 |
| #9 슬롯 클래스 허용 목록 | `2bce623` | `test_audit_fix9_slot_classes.py`(7) | rfdetr_classes/required · DEGRADED · dropped_by_allowlist |
| #5 설치 고정값·인자 | `78d8c11` | `test_audit_fix5_installer.py`(9) | 직접 호출 · 토큰 필수 · install_result.json · CRLF · ★BOM 회귀 수정 + 파서 테스트 |
| #4 서비스 자가 재기동 | `286f1ef` | `test_audit_fix4_service.py`(8) | exit:3 → NSSM · AppStopMethodConsole 30000 · stop_all 병렬 · systemd · watchdog 유예 |
| #10 + B-1 정체 감시·aug_config | `af34d11` | `test_audit_fix10_watchdog.py`(6) | stop_event · heartbeat · NaN fail-closed · aug_config 전달(dry-run 실측 10변환) |
| B-2 평가 결정성 | `0c8718d` | `test_audit_b2_determinism.py`(3) | 원인 = 예열 스레드 GPU 경합; setUp 격리 뒤 전체 스위트 **5회 연속 통과**, 허용 ±0.3 복귀 |
| B-3 학습 의존성 핀 | `3bf29bc` | `test_audit_b3_train_pins.py`(5) | pip freeze 실측 조합 · setup_env numpy/cv2 가드 |
| B-4 절대경로 제거 | `1a2bf5e` | `test_audit_b4_paths.py`(4) | ${VIGENT_DATA_DIR} · data_paths.field_root · 스크립트 11개 |
| B-5 클래스 정본 | `a6820bd` | `test_audit_b5_labels.py`(5) | labels.STD5/CSS_TO_STD/LABEL_NORMALIZE 12곳 · FORKLIFT_OP_CONF |
| B-6 pip check 화이트리스트 | `7eb5d01` | `test_audit_b6_pip_check.py`(4) | 허용 6건 · 개발기 exit 0 |
| C-1 문서·죽은 설정 6건 | `3b6dbe7` | `test_audit_c1_docs.py`(6) | person 만 통과 정정 · ultralytics · 8010 · cooldown_sec · make_prelabels 폐기 · 실기 미검증 표 |
| C-2 이 표 | (이 커밋) | `test_audit_c2_status.py`(1) | — |

★재현 테스트 허용 오차 이력: 09-28 오전 ±0.5 로 넓혔던 것(`aecc5d3`)은 B-2 에서 ±0.3 으로 되돌렸다.

## 0-2. 실기 미검증 (코드·테스트로 고정했으나 실기기·관리자 셸에서 아직 확인하지 않은 것)

| 항목 | 무엇이 미검증인가 | 관련 커밋 | 확인 절차 |
|---|---|---|---|
| NSSM 자가 재기동 | 기아 3단계 exit 3 뒤 AppExit Restart 60 s 재기동 | `286f1ef` | ✅ **실기 검증됨 2026-09-28**(D:\VIGENT_TEST·8020): Restart/60000/30000 · kill 후 재기동 80 s · `_escalate` exit=3 — [field_verification §2](../deploy/field_verification_20260928.md) |
| AppStopMethodConsole 30000 | 서비스 정지 시 _shutdown 완주 | `286f1ef` | ✅ 실기 검증됨 2026-09-28: `sc stop` 3.06 s · pending 없음(카메라 0대) · python 잔존 0 — 〃 §3 |
| install.ps1 직접 호출 | -ExtraEnv 배열 4개 전부 서비스 환경에 반영 | `78d8c11` | ✅ 실기 검증됨 2026-09-28: env 4/4 · 토큰 없는 0.0.0.0 → exit 1 — 〃 §4. ★부수 결함: `-Bind` 가 `VIGENT_HOST` 에 미반영(실기 결함 #2, 수정) |
| install_result.json 경로 | -Target/-Port 변경 시 마법사·인수시험이 따라감 | `78d8c11` | ✅ 실기 검증됨 2026-09-28: 8020/D:\VIGENT_TEST · 인수시험 --base 없이 8020 — 〃 §4. ★부수 결함: A1 한국어 sc query 오판(실기 결함 #4, 수정) |
| CRLF 검증 | 실제 build_usb.ps1 실행 | `78d8c11` | ✅ 실기 검증됨 2026-09-28 13:55 academy 빌드 — 〃 §1 |
| go2rtc DELETE 파라미터 | `name=`(starvation_guard) vs `src=`(cameras) | 실기 결함 #1 로 수정 | ✅ 실기 검증됨 2026-09-28: **`src=` 만 삭제**(name= 은 200 이지만 무효) → starvation_guard 를 `src=` 로 — 〃 §5 |
| 한국어 Windows Get-Counter | 영문 카운터명 동작 | 미수정 | 학원 기기 |
| Linux watchdog.sh·systemd | bash -n 만 통과 | `286f1ef` | Linux 기기 |
| B-1 실제 학습 | rfdetr 1.8.0 TrainConfig.aug_config 필드는 실측, 학습 적용은 현장 데이터 후 | `af34d11` | 첫 현장 학습 |

## 1. 하드코딩

### 1-1. 절대 경로 (data_paths / `VIGENT_DATA_DIR` 우회)

런타임(vigent-core)에서 `data_paths` 를 우회하는 곳은 `/tmp` 2곳(§0 #10) 외에 없다. 우회는 scripts·configs 에 몰려 있다.

| 심각도 | 파일:줄 | 리터럴 | 제안 |
|---|---|---|---|
| H | `deploy/usb/설치.bat:36` · `scripts/deploy/install.ps1:24` · `preflight.ps1:23` · `uninstall.ps1:13` | `C:\VIGENT` 4곳 | §0 #6 |
| M | `configs/finetune_aihub_v2*.yaml:15-22` · `finetune_aihub_forklift_v2.yaml:11-13` | `D:/vigent_private_data/aihub/...` | `${VIGENT_DATA_DIR}` 치환(`finetune_rfdetr.expand_path` 가 이미 `${VIGENT_FIELD_DIR}` 를 치환하므로 env 하나 추가) |
| M | `scripts/train/finetune_rfdetr.py:76` | `D:/vigent_private_data/field/prelabel` (FIELD_DIR_DEFAULT) | `data_paths.media("field/prelabel")` |
| M | `scripts/eval/forklift_compare_harness.py:49,256-260` · `forklift_field_yardstick.py:26` · `forklift_aihub_imagelevel.py:12-55` · `forklift_field_rerun.py:14-22` · `forklift_box_geom.py:12-43` · `forklift_fp_dump.py:26` · `scan_507_unlabeled.py:30` · `head_box_stats.py:61-63` | `D:\vigent_field\20260827\…`, `D:/vigent_private_data/aihub/…`, `D:\vigent_original\…`(sys.path 삽입) | `_ROOT` 상대경로 + `data_paths`. 8/27 날짜는 인자로 |
| M | `scripts/build_report_v12.py:41-42` · `build_field_report.py:23` | `D:\vigent_field\20260827\build`, `C:\Program Files (x86)\Microsoft\Edge\…\msedge.exe` | 인자 + `shutil.which("msedge")` |
| M | `vigent-core/agents/guard.py:582` | `~/.roboflow/models` 폴백 | RF_HOME 없을 때만. 유지하되 주석에 사유 |
| L | `scripts/build_portable.ps1:15-16` · `deploy/build_usb.ps1:24` · `copy_to_usb.ps1:15` | `D:\vigent_portable`, `D:\vigent_portable_cache` | 파라미터 기본값 — 유지, 문서화 |
| L | `scripts/setup_worktree.sh:13,57` · `legal_gate_verify.py:7` | `/Users/nohyeonseong/Desktop/VIGENT`, `/opt/anaconda3/bin/python3` | 개인 Mac 경로 — 인자 필수/`sys.executable` |
| L | `deploy/windows/verify_service_reinstall.ps1:255` | `D:\__vigent_bad_rf_home` | 시험용 가짜 경로 — 유지 |

### 1-2. 호스트·포트·IP·RTSP·카메라

| 심각도 | 파일:줄 | 리터럴 | 제안 |
|---|---|---|---|
| H | `scripts/deploy/install.ps1:26` · `deploy/windows/install_service.ps1:37` | `Bind="0.0.0.0"` | §0 #7 |
| H | `scripts/deploy/acceptance_test.py:233` | `http://127.0.0.1:8010` | §0 #6 |
| M | 8010: `install.ps1:25` `install_service.ps1:36` `service_status.ps1:15` `verify_service_reinstall.ps1:34` `service_entry.py:125` `portable_wait.py:19` `VIGENT_시작.bat:29`(8011 폴백 117-121) `systemd/vigent-edge.service:19` `vigent-watchdog.service:10` `watchdog.sh:11,23` + scripts(`capacity_probe.py:41` `field_recorder.py:33` `soak_realcam.py:38` `test_reconnect.py:32` `test_health_fault_injection.py:40` `offline_probe.py:38`) | 포트 8010 20곳 | 정본 `VIGENT_PORT`/`VIGENT_BASE_URL` 하나(bench_4ch·pilot_load_test 는 이미 env) |
| M | go2rtc `http://127.0.0.1:1984`: `routers/cameras.py:35,46`(`_G2_PORT` 상수는 280행에 있는데 35·46은 리터럴) `routers/tapo.py:42,53,77,114` `starvation_guard.py:54` `config/go2rtc.yaml:20` `scripts/test_reconnect.py:108` | 7곳 이상 | `go2rtc_client.BASE` 하나, 가능하면 go2rtc.yaml `api.listen` 에서 읽기 |
| M | `vigent-core/routers/tapo.py:17-19,32` · `config/go2rtc.yaml:5` | 스트림명 `"tapo"`, API 경로 `/tapo/*` | 특정 브랜드 종속 — 범용명(`cam`) + 라우트 별칭 유지(OpenAPI 110 불변 조건 검토) |
| M | `vigent-core/static/realtime_core.js:2769` | `http://127.0.0.1:8005` (file:// 모드 API_BASE) | 서버는 8010 — 고아 포트. 8010 으로 정정 |
| L | `vigent-core/main.py:14` | docstring `--port 8000` | 8010 으로 |
| L | `config/site.example.yaml:12,19` · `themes/safety/index_hub.html:142` · `tuning.yaml:285` · `academy:207` | `rtsp://아이디:비번@192.168.0.101:554/stream1`, `http://192.168.0.50/relay` | 예시·주석 — 유지 |
| L | `vigent-core/agents/dispatcher.py:165,309` | `https://api.telegram.org` | 유지(security.json 고정 호스트) |
| L | `scripts/mock_relay.py:9-10` · `bench/local_sink.py` · `bench_with_sink.sh:21`(9911) · `eval/review_viewer.py:22`(8777) | 시험용 포트 | 유지 |

### 1-3. 비밀값 (값은 쓰지 않고 길이만)

| 심각도 | 위치 | 내용 | 상태 |
|---|---|---|---|
| H | `config/notify.yaml:7` | 텔레그램 봇 토큰 평문(길이 46, 패턴 일치) | `.gitignore:6` 로 git 미추적 · `build_portable.ps1:185`·`build_usb.ps1:55` 가 제외함을 확인. **이 파일이 채팅·툴 출력에 노출된 적이 있다**(2026-09-27 마감 점검의 grep 출력) → 토큰 **재발급 권장** |
| M | `config/notify.yaml:1` | chat_id(길이 10) | gitignore. 유지 |
| H | `.env:1,3` | `ROBOFLOW_API_KEY`(21) · `VIGENT_API_TOKEN`(64) | gitignore. 유지 |
| — | 코드 전체 | `password=`/`api_key=`/토큰 패턴 리터럴 **0건** | — |

### 1-4. 매직 넘버 — 코드 기본값 vs yaml

| 심각도 | 파일:줄 | 코드 | yaml | 제안 |
|---|---|---|---|---|
| H | `agents/guard.py:253-254` | DETECTOR_CONF 4값·IMGSZ 960 | tuning 0.40/0.35/0.002/0.55 · 384 | §0 #3 |
| M | `agents/guard.py:250` | `DEFAULT_CONF=0.30` | 없음 | defaults.py |
| M | `agents/guard.py:315-316,332-334` | ByteTrack low 0.28 · high 0.50 · frame_rate 10 · lost_buffer 30 · min_iou 0.10 | 키 없음 | tuning `track:` 에 키(주석이라도) |
| M | `agents/guard.py:349` | `BYTETRACK_MIN_FRAMES=1` | tuning.yaml:209 `0` | 다름(yaml 우선). 코드 기본 0 으로 |
| M | `agents/guard.py:184,256,272-273,290,833` | `_nms 0.55`·`TRACK_IOU 0.45`·`CONTAIN_RATIO 0.70`·`PPE_PERSON_EXPAND 0.15`·`HYSTERESIS ppe3/fire2`·재매칭 0.25/0.40 | 없음 | defaults.py(0.55↔0.45 불일치는 주석 208행에 기록됨) |
| M | `rfdetr_service.py:31` · `:80` | `detect_threshold 0.4` · `ByteTrackTracker()` 라이브러리 기본 | vision.yaml:89 0.4 / tuning person 0.40 | person 임계 2번째 출처·추적 파라미터가 guard 와 다름 → guard 와 같은 출처 참조 |
| M | `ergonomics.py:79,89` | neck 15/25 · shoulder 12/25 | vision.yaml:97,99 **25/40 · 15/35** | yaml 과 맞추기 |
| M | `retention.py:102` | `WARN_FREE_BYTES=5GB` | 없음(preflight 최소 20GB 는 별도) | tuning `retention.warn_free_gb` |
| M | `scripts/deploy/preflight.ps1:24-26,31,39,62-64` | VRAM 8·RAM 16·Disk 20 GB·cu130·14.51·드라이버 528/570/580 | 없음 | `build_portable.ps1:22`·`build_usb.ps1:108` 의 cu130 과 짝 — 설치 사양 JSON 하나 |
| M | 반경 3.0 3곳 `proximity.py:19` `worker.py:326` `routers/detect.py:205` | `tuning.val("proximity","radius_m",3.0)` | 3.0 | `proximity.DEFAULT_RADIUS_M` 하나 |
| M | 해상도 384: `bench/infer_breakdown.py:33` `ppe_path_bench.py:34` `eval/aihub_smoke_eval.py:126` `eval_v1_heldout.py:282,352,513` `forklift_compare_harness.py:255` `forklift_fp_dump.py:25` `forklift_neg_eval.py:31` `ppe_fp_dump.py:25` `scan_507_unlabeled.py:52` `finetune_rfdetr.py:650` `configs/finetune_field_v2*.yaml` | 384 | 384 | `tuning.val("detect","imgsz")` 또는 defaults.RES |
| M | 임계 복제: `ppe_fp_dump.py:24`·`eval_v1_heldout.py:461,479` 0.35 · forklift 0.5 4곳(`forklift_compare_harness.py:39` `forklift_fp_dump.py:27` `forklift_neg_eval.py:33` `forklift_field_yardstick.py:33`) · `forklift_field_rerun.py:59` 0.40 | — | tuning ppe 0.35 / forklift 0.002·academy 0.50 / person 0.40 | tuning 에서 읽기. **forklift 운용점이 tuning 0.002 / academy 0.50 / guard 0.55 / scripts 0.5 네 값** |
| L | `worker.py:92-98,1227` `alert_gate.py:58-76` `worker.py:44-74` `zone_debounce.py:31/35` `health_status.py:40` `legal_whitelist.py:104` | cooldown 15·evidence 30·fps 2.0·통보 300/6/3600/1800·재연결 15/5/5/1/5000·enter 1.0/0.4·grace 90·ops_log 50 | 같음 | 중복이지만 값 일치 — defaults.py 로 모을 때 함께 |
| L | `vlm_confirm.py:45-47` · `starvation_guard.py:39` · `dispatcher.py:59,165,229,310,324,348` · `zone_tile.py:31` `worker.py:1088` `rfdetr_service.py:142` · `routers/detect.py:200` · `isolated_detect.py:15`(conf 0.10·imgsz 640) | VLM 60/35/25 · 10s · smtp 587·timeout 8/6 · tile 0.1·15px·2.0 · fire high 0.5 · 오프라인 640 | 없음/일부 | 상수 모듈. isolated_detect 640 은 오프라인 전용이면 유지 |
| L | `themes/safety/vision.yaml:109` | `cooldown_sec: 8` | 코드에서 읽는 곳 0 | 죽은 설정 — 제거 |

### 1-5. 클래스 이름·순서 리스트 중복 (→ §2 대조표)

| 심각도 | 파일:줄 | 리터럴 | 제안 |
|---|---|---|---|
| M | 표준 5클래스 `[person, Hardhat, NO-Hardhat, Safety-Vest, NO-Safety-Vest]` 8곳: `scripts/eval/cvat_to_gt.py:36` `data/field_fixture.py:17` `data/field_prelabel.py:36` `configs/finetune_aihub_v2.yaml:5` `v2B:5` `v2D:4` `v2E:4` `finetune_field_v2.yaml:5` | class id 계약 | `vigent-core/labels.py` 에 `STD5` 하나 |
| M | `scripts/data/aihub_to_vigent.py:38` | 5클래스 + forklift(6) | STD5 파생 |
| M | `scripts/make_prelabels.py:30-31` | `[person, forklift, Hardhat, …]` — **forklift 가 2번**(순서 다름). 2026-08-29 라벨링 도구용, 현재 참조 문서만 | 정본에서 파생하거나 폐기 표시 |
| M | CSS 10클래스 순서: `configs/finetune_aihub_v2A2.yaml:4` `finetune_field_v2_cont.yaml:3` (`Safety-Vest` 표기) vs `scripts/report/status_graphs_20260928.py:73` (`Safety Vest`, 표시 순서용) | 3곳 | 학습 설정은 체크포인트 `class_names` 에서 읽어 자동 생성 |
| M | 정규화 맵 5곳 이상: `finetune_rfdetr.py:68,604` `pseudo_hardhat.py:44` `scan_507_unlabeled.py:23` `eval_v1_heldout.py:143`(역방향) `aihub_smoke_eval.py:158` | CSS 공백형 ↔ 표준형 | `labels.CSS_TO_STD` 하나(guard `LABEL_NORMALIZE` 가 정본) |
| M | 필수 PPE 3종: `guard.py:99` `setup_wizard.py:42,242` `tuning.yaml:281`(주석) · 학원 2종: `setup_wizard.py:43` `tuning.academy.yaml:230` | 3곳/2곳 | guard 에서 import, 학원 값은 프로파일 yaml 만 |
| L | `themes/safety/vision.yaml:63` `deploy/academy/vision.academy.yaml:53` `themes/academy_*_tmp/vision.yaml:51` | yolo 슬롯 `classes:` 6종(죽은 설정) | 4곳 동기화 부담 — 정리 |
| L | `vigent-core/labels.py:17-26` ↔ `incident.py:212-213` | 한글 표시명 2곳 | incident 가 labels 사용 |
| L | `vigent-core/worker.py:142` | `_KNOWN_SLOTS` | vision.yaml backend 키에서 파생 |

### 1-6. 공용 코드에 박힌 학원 전용 값

| 심각도 | 파일:줄 | 내용 | 제안 |
|---|---|---|---|
| H | `scripts/deploy/setup_wizard.py:168` | 기본 프로파일 academy | §0 #1 |
| H | `deploy/portable/portable_overrides.yaml` | 근골격 OFF·화재 OFF 기본(사유 "학원 계약 범위 밖") | §0 #2 |
| M | `vigent-core/worker.py:139-140` | /health 노출 문구에 "학원" | 프로파일에서 주입 |
| M | `deploy/academy/tuning.academy.yaml`(234줄) | `config/tuning.yaml`(300줄)의 통째 복사본, 실제 차이는 5키(conf.forklift 0.5·include_forklift 1·include_fire_smoke 0·heartbeat 08:30·ppe.required) | 차분 오버레이(portable_overrides 방식). `check_profile_drift.py` 는 사후 검사만 |
| M | `themes/academy_boda_tmp/` `themes/academy_fk2_tmp/` | 공용 themes/ 에 학원 임시 테마(미추적) | `deploy/academy/` 로 옮기거나 삭제 |
| M | `themes/safety/vision.yaml:66,68` | 공용 테마의 `fire_smoke_boda.pt`·`forklift_boda_ax.pt`(죽은 yolo 슬롯) | 정리 |
| L | `themes/safety/index*.html` localStorage `'boda_clean'` · `scripts/field_recorder.py:83` `default="cam_academy"` · `build_report_v12.py:41` `20260827` | 레거시 브랜드명·기본값 | 이름 변경·인자화 |

### 1-7. 같은 값이 여러 파일에 (요약)

| 값 | 위치 수 | 비고 |
|---|---|---|
| 해상도 384 | tuning·academy·adapter 2·configs 3·scripts 15+ | **guard.py:254 만 960** |
| person 0.40 | tuning·academy·vision.yaml:89·rfdetr_service:31·forklift_field_rerun:59 | **guard.py:253 만 0.35** |
| ppe 0.35 | tuning·academy·ppe_fp_dump·eval_v1_heldout 2 | **guard.py:253 만 0.55** |
| forklift 운용점 | tuning 0.002 / academy 0.50 / guard 0.55 / scripts 0.5 | 네 값 |
| 포트 8010 | 20곳 | |
| go2rtc 1984 | 9곳 | |
| `C:\VIGENT` | 4곳 | |
| smtp 587 | dispatcher·setup_console·setup_wizard·bench_with_sink | |
| cu130 | build_portable·preflight 3·build_usb | |
| guard_bypass 문구 | tuning·academy·dispatcher:466·routers/dispatch:37 | |
| 심각도 문자열 | worker.py:294-345 `"mid"` ↔ vision.yaml:91-93 `medium` | 명칭 불일치 |

---

## 2. 클래스·슬롯 규약 일관성

### 2-1. 대조표 — 가중치 `class_names`(체크포인트 실측 2026-09-28) vs 코드·설정

| 출처 | 순서 · 표기 | 근거 |
|---|---|---|
| `ppe_rfdetr_v1.pth` | `Hardhat, Mask, NO-Hardhat, NO-Mask, NO-Safety Vest, Person, Safety Cone, Safety Vest, machinery, vehicle` (10, CSS 공백형) | `ckpt_class_names` [실행 확인] |
| `forklift_rfdetr_fk510_smoke.pth` | `person, forklift` (2) | 〃 |
| `forklift_rfdetr_v1.pth` | `forklift` (1) — predict 는 id 1 을 낸다(`resolve_forklift_ids`) | 〃 · `forklift_compare_harness.py` |
| `fire_smoke_rfdetr_v1_e17.pth` | `smoke, fire` (2) | 〃 |
| `rf-detr-nano.pth`(person) | `class_names` 없음 → 어댑터가 `COCO_CLASSES[cid]`(COCO id) | 〃 · `rfdetr_adapter.py:279` |
| 어댑터 `rfdetr_adapter.py:238,276-283` | 커스텀: `class_names[cid]`(0-indexed) → `finalize_box` → `LABEL_NORMALIZE`(guard.py:88-97: 공백형→하이픈, Person→person, Fire→fire, Forklift→forklift, Smoke→smoke) → 없는 이름은 **원문 통과** | 코드 |
| 규칙 `guard.py:99` `PPE_MISSING_LABELS` | `NO-Hardhat, NO-Safety-Vest, NO-Mask` · `ppe.required` 로 축소(academy 2종) | 코드·tuning.academy:230 |
| 평가 `eval_v1_heldout.py:57,143` | `OUR4` CSS 공백형 · `to_css_name` 역변환(person→Person …) | 코드 |
| 변환기 `aihub_to_vigent.py:38` · `cvat_to_gt.py:36` · `field_prelabel.py:36` | 표준 5(+forklift) 하이픈형 | 코드 |
| CVAT 매핑 `field_prelabel.cvat_xml` | 표준 5 하이픈형(labels 순서 = classes.txt) | 코드 |
| 학습 `finetune_rfdetr.std_name`·`slot_alignment` | 공백형→하이픈형·Person→person 정규화 후 순서 비교 | 코드·tests |

결론: 표기는 세 계열(CSS 공백형·표준 하이픈형·COCO 소문자)이 공존하고 어댑터·학습·평가가 각자 변환표를 갖는다(§1-5). **값은 지금 일치**하지만 정본이 없어 새 스크립트마다 표를 복제한다.

### 2-2. 슬롯 가드 적용 범위

| 경로 | 검사 | 갭 |
|---|---|---|
| 학습(`finetune_rfdetr.py` 이어 학습) | `slot_alignment`: 체크포인트 순서 = 데이터셋 순서 아니면 exit 5 | 없음(2026-09-27 추가) |
| 추론 어댑터 로드(`guard._get_model` → `RfdetrDetector`) | SHA·로드 성공(F-8)만. `class_names` 내용·순서 검증 **없음** | **갭** — §0 #9 |
| 슬롯 클래스 허용 목록 | 없음 — 슬롯이 내는 모든 라벨이 통과 | **갭** — §0 #8 (forklift 슬롯 person 29/109 실측) |
| 평가기(`eval_v1_heldout.make_predictor`, `forklift_compare_harness.load_model`) | 이름만 사용, 검증 없음 | 갭(학습 산출물이 잘못돼도 채점됨) |
| ONNX 어댑터(`rfdetr_adapter.py:131`) | 메타 `class_names` 없으면 ValueError | 이름 검증은 없음 |

### 2-3. 사용 안 하는 클래스가 버려지는 곳

| 클래스 | 어디서 어떻게 |
|---|---|
| Mask / NO-Mask | 검출·표시는 통과(`labels.py:18` 한글명 있음). 경보는 `ppe.required` 에 NO-Mask 가 있을 때만(전역 기본 3종 포함, academy 제외). 평가 dev74 는 `exclude_classes={Mask, NO-Mask}`(x4b:102, 의도적 `90d03e9`), held-out 표는 10클래스 전부 채점. 학습 A′/cont 는 `drop_classes`, 변환기는 `EXCLUDED_CLASSES` |
| Safety Cone / machinery / vehicle (PPE 슬롯) | `JUNK_LABELS={"default"}` 뿐이라 **검출 결과에 남는다**(`labels.py:26` 한글명 "기계·설비/차량/안전콘"으로 표시). 근접 규칙은 `VEHICLE_REF_M`(forklift·truck·car·bus·motorcycle…)만 보므로 machinery/Safety Cone 은 규칙에 안 쓰임. 학습은 `drop_classes` |
| COCO 79종(person 슬롯) | **person 만 통과가 아니다** — 109프레임 실측에서 `boat·bench·bottle·cell phone·sports ball` 이 detector=person 으로 최종 검출에 남았다 [실행 확인]. 근접 규칙이 truck/car/bus 를 쓰므로 의도된 통과이나, `ALGORITHM_TRUTH` §2-2 "COCO 80종 중 person 만 통과" 는 **틀린 서술** → 문서 정정 |

---

## 3. 충돌·오류 흔적

### 3-1. 최근 30일 로그 상위 (53개 파일: runs/finetune·audit 벤치 서버 로그·게이트 unittest 로그) [실행 집계]

| 빈도 | 메시지(정규화) | 분류 · 조치 |
|---|---|---|
| 172×2 | rf-detr `Using a different number of positional encodings…` / `Using patch size 16 instead of 14…` | 라이브러리 정보성 경고(파인튜닝 모델 로드 시 항상) — 로거 필터로 1회만 |
| 107 | rf-detr `args.num_queries absent; inferred ckpt_num_queries=300…` | 체크포인트 메타 결측(rfdetr 1.8) — 학습 시 notes 에 기록하거나 필터 |
| 103 | rf-detr `Checkpoint has N classes but model is configured for 90…` | 같은 부류 — `num_classes` 를 명시하면 사라짐(어댑터 로드 인자) |
| 75 | vigent.worker `위험구역 미설정 — 침입 판정을 하지 않는다` | 벤치 모의 카메라(구역 없음) — 정상. 운영에서 나오면 설정 누락 |
| 65 | rf-detr `Pretrained weights at C:\Users\…\.roboflow… loaded only…` | 캐시 경로 노출 + 정보성 |
| 61 | `Traceback` | 게이트 테스트의 **의도된 예외**(`RuntimeError: boom` 21·데드레터 시험 12 등) — 테스트 로그 정상. 실운영 로그의 Traceback 은 0 |
| 23+23 | vigent.worker `HANG 감지(…무진전 > 15s) → 재기동` / `HANG 재시작 #n` | **벤치 r2 종료 시각(02:37, 시작 30분 뒤)에 8건** — 파일 소스 EOF 후 종료 순서에서 워커가 hang 판정됨. r1·r3·gpu2 3회는 0건. 소크 중 발생 아님. 종료 시 워커 정지를 소스 EOF 보다 먼저 하도록 순서 점검(L) |
| 26 | vigent.guard `검출 슬롯 미가동(slot=person…)` | 게이트 테스트(가중치 없는 격리 환경) — 정상 |
| 20 | `System.Management.Automation.RemoteException` | gate.ps1 이 stderr 를 예외로 감싼 것(PowerShell 5.1 특성) — 게이트 출력 잡음 |
| 12 | vigent.cameras `포트 … 점유 중 … 재사용` | 벤치 6회 전부 1건씩 — 이전 go2rtc(1984) 잔존 → 벤치 시작 시 이전 인스턴스 정리 안 됨(§3-6 관련) |
| 12·12 | retention `삭제 예정 …` | 테스트 |
| 13 | `unittest_flaky_2026-09-06_run3.log` 의 깨진 한글(cp949) | 로그 인코딩 — §3-4 |

실운영성 로그(벤치 서버 6개)에서 `[ERROR]` 는 r2 의 HANG 8건뿐. **Traceback 0.**

### 3-2. 비결정 테스트 이력 (전수)

| 시기 | 테스트 | 원인 | 현재 |
|---|---|---|---|
| 2026-09-06 C1 | (이름 미포착 1회) | — | 미확정(R12 와 같은 것으로 추정 `[추정]`) |
| 2026-09-06 R12 `516b58b` | `test_readiness_warmup.test_on_ready_not_called_when_warmup_fails` | `test_endpoints_smoke` 의 실모델 예열 스레드("vigent-warmup")가 모듈 밖까지 살아 READY 를 덮음 — 테스트 격리 결함 | setUp 에서 잔존 스레드 join. 이후 재발 0 |
| 2026-09-23 | `test_field_eval_group` | 실제 `shutil.disk_usage` 읽음 — C: 5GB 미만에서 실패 | mock 으로 고정(CLAUDE.md) |
| 2026-09-26~27 | (이름 미포착 2회, CLAUDE.md) | 게이트 로그 미보존 | `gate_unittest_last.log` 보존 추가(2026-09-27). 이후 `gate_run_20260927_0120.log` 에 FAIL 0 |
| 2026-09-27 `a0c4ed6` | `test_ppe_compare_harness.test_v1_reproduces_baseline` | GPU 를 다른 작업과 같이 쓰면 Person.fp 48 vs 46(비결정 커널) | 허용 오차 ±2(`:105`). **근본 원인(cuDNN 비결정)은 그대로** — `torch.use_deterministic_algorithms` 미적용 |

기계 상태에 닿는 테스트 23파일(시각·subprocess·소켓·디스크): mock/patch 0건인 것은 `test_alert_queue.py`(sleep 없음, sqlite 임시파일) · `test_frontend_privacy.py`·`test_profile_drift.py`·`test_soak_report.py`·`test_verify_service_script.py`·`test_zone_edit_guard.py`(subprocess 로 실제 스크립트/node/PowerShell 실행 — CI 에서 skip 조건 있음) · `test_notify_selftest_f35.py`(sleep 2곳, 실시간 대기). **`time.sleep` 기반 대기 8파일**(alert_wiring·bypass·capture_timeouts·readiness·relay·notify_selftest·…)은 부하가 걸리면 흔들릴 후보 — 지금은 실패 이력 없음.

### 3-3. 의존성

| 항목 | 실측 | 판정 |
|---|---|---|
| `pip check` | 6건: albucore·albumentations 가 `opencv-python-headless`, rtmlib 가 `opencv-contrib-python`/`opencv-python`, supervision·trackers 가 `opencv-python` 을 요구 — 설치된 것은 `opencv-contrib-python-headless 4.13.0.92` | **의도된 상태**(requirements.txt:19-23, GUI cv2 차단). `pip check` 가 항상 실패하므로 CI 에 넣지 못함 — 화이트리스트 스크립트 필요(M) |
| 버전 | torch 2.12.0+cu130 · torchvision 0.27.0+cu130 · numpy 2.4.6 · cv2 4.13.0 · rfdetr 1.8.0 · pytorch_lightning 2.6.6 · torchmetrics 1.9.0 · albumentations 2.0.8 · albucore 0.0.24 · fastapi 0.137.2 · uvicorn 0.23.2 · onnxruntime 1.27.0 · CUDA 13.0 · cuDNN 92000 | ultralytics **미설치**(CLAUDE.md 기술 스택에는 있음 — 문서 정정 L) |
| 핀 | `requirements.txt` numpy·cv2 고정, torch 는 주석(PyPI 휠이 CPU 전용이라 cu130 인덱스로 별도) · `requirements-train.txt` 의 `rfdetr[train]` 주석 처리(2026-09-26 실측: numpy 강등·cv2 교체) → 학습 의존성은 **수동 설치 상태**(pytorch_lightning·torchmetrics·albumentations·albucore 0.0.24·stringzilla·numkong 이 requirements 어디에도 없음) | **M** — `requirements-train.txt` 에 실제 설치된 조합을 핀으로 기록 |
| 포터블 vs .venv | `D:\vigent_usb_stage\portable\app\requirements.txt` 18핀 전부 venv 와 일치(torch/torchvision 은 `+cu130` 접미만 다름, wheels_cuda 로 교체). 포터블에는 학습 의존성 없음(정상) | USB 빌드는 `4100c60`(2026-09-23) — fk510_smoke 교체(`694c5af`) **이전** 이라 학원 프로파일 가중치가 없다(NEXT.md USB 재빌드 항목) |
| `rfdetr[train]` 경고 | 설치 시 numpy 2.4→강등·cv2 교체 이력 | `scripts/setup_env.py` F-33 가드는 torch 만 지킴 — numpy·cv2 가드 추가(L) |

### 3-4. Windows 전용 가정 (Linux / 노트북 포터블에서 깨질 지점) [코드 근거]

괜찮은 쪽 먼저: vigent-core·deploy 의 `open()`·`read_text()`·`write_text()` 는 전부 `encoding="utf-8"`, cp949 하드코딩 0, `sys.stdout.reconfigure` 는 전부 guard 됨, `.ps1` 에 PS7 전용 구문(`&&`·`??`·삼항) 0, BOM 있음.

| 심각도 | 파일:줄 | 근거 | 왜 | 제안 |
|---|---|---|---|---|
| H | `scripts/deploy/install.ps1:186` | `-File $isv … -ExtraEnv $extra`(배열) | 첫 값만 바인딩, 나머지 위치 인자로 → 서비스 이름 오염/등록 실패 가능(실기 미검증) | §0 #5 |
| H | `deploy/systemd/vigent-edge.service:24` | `ExecStart=… bin/vigent-edge.command` | 파일 없음(`_archive/macos/launchers/` 에만) → Linux 서비스 기동 불가 | `bin/vigent-serve.sh` |
| M | `deploy/usb/설치.bat` · `scripts/deploy/*.ps1` | `git ls-files --eol` = `w/lf attr/text eol=crlf` | 작업트리 LF 인 채 USB 로 복사 → cmd 파싱 위험(UTF-8 한글+괄호 블록) | renormalize + build_usb CRLF 검증 |
| M | `deploy/watchdog.sh:13-18` | `set -u` + `"${AUTH[@]}"` | bash <4.4 에서 빈 배열 unbound → curl 불실행 → 재기동 루프 | `${AUTH[@]+"${AUTH[@]}"}` |
| M | `vigent-core/worker.py:994-995` | `isalnum()` 한글 통과 → `cv2.imwrite` | Windows 비ASCII 경로에서 imwrite 가 False(조용) | `imencode`+`tofile`(field_prelabel 방식) |
| M | `vigent-core/rfdetr_service.py:224,242` · `ml/vlm_risk_summary.py:101` | `Path("/tmp")` | Windows 에서 `	mp` | `tempfile` |
| M | `vigent-core/vlog.py:42-43` | `RotatingFileHandler` | Windows 에서 다른 프로세스가 열고 있으면 rollover PermissionError → 로그 무한 증가 | 프로세스별 파일명/`concurrent-log-handler` |
| M | `scripts/bench/bench_4ch.py:189-256` | `Get-Counter '\GPU Process Memory(*)…'` | Linux 불가(nvidia-smi 폴백 없음), 지역화 카운터명 위험 | 비Windows 폴백 |
| M | `scripts/pilot_load_test.py:148,223-245,399-412,807` | `typeperf`·`Get-CimInstance`·`decode("utf-8")` | Windows 전용 + OEM 출력 UTF-8 디코드 | psutil·`locale.getpreferredencoding()` |
| L-M | `scripts/bench/bench_4ch.py:378,389` · `bench_with_sink.sh:12` · `scripts/train/finetune_rfdetr.py:76` · `data/field_prelabel.py:37` | `.venv/Scripts/python.exe` · `D:/…` 기본값 | Linux 경로 불일치 | `sys.executable`·data_paths |
| L | `vigent-core/privacy.py:293-311` · `scripts/deploy/acceptance_test.py:142-153` · `bench_4ch.py:233,242` · `deploy/portable/VIGENT_시작.bat:142` · `VIGENT_종료.bat:10` · `deploy/usb/설치.bat:13` · `portable_wait.py:36` · `scripts/report/status_graphs_20260928.py:26` | 영문 cipher 메시지·`text=True` 인코딩 미지정·`LISTENING` 문자열·경로 작은따옴표·`net session`·`os.startfile`·`Malgun Gothic` | 지역화·권한·플랫폼 | 표시된 대안 |

### 3-5. 예외를 삼키는 곳 [코드 근거] — 위험(조용한 기능 정지) / 허용(best-effort)

| 심각도 | 파일:줄 | 근거 | 왜 | 제안 |
|---|---|---|---|---|
| H 위험 | `routers/safety_core.py:538-557` | 전이 선소비 + `except: pass` | §0 #1 ① | 〃 |
| H 위험 | `agents/copilot.py:104-111` | `legal_whitelist.gate_vlm_text` 실패 → `pass` | 법령 화이트리스트 **fail-open**(검증 안 된 조문 통과) | fail-closed("안전관리자 확인 필요") + ERROR |
| H 위험 | `agents/dispatcher.py:371-375` | enqueue 실패 → `row_id=None` | §0 #1 ② | 〃 |
| H 위험 | `relay.py:146-151` | `off_failed=True` 만 | §0 #2 | 〃 |
| H 위험 | `starvation_guard.py:100` | `Popen(shell=True)` 반환 미확인 | §0 #4 | 〃 |
| M 위험 | `agents/dispatcher.py:43-44` | notify.yaml 파싱 실패 → `cfg={}` | 원인 은폐 | §0 #7 |
| M 위험 | `agents/dispatcher.py:378-385,380-381` | `mark_sent` 실패 `pass` · 채널 인자 없음 | pending 잔류 → 중복 발송 / `email_last_success` 미기록 → "이메일만 죽음" 미감지 | 로그 + `mark_sent(row_id, *_split_channels(res))` |
| M 위험 | `worker.py:388-389,402-403,448-449,971-972` | RTMPose 로드 실패 `_failed=True`(로그 0) · 프레임 예외 `return []` | 근골격 경보 영구 침묵, /health 모름 | `state["pose_error"]`·간헐 WARNING·카운터 |
| M 위험 | `worker.py:995-996` | `imwrite` 반환 무시 + `collected += 1` | 수집 수 과대 | 반환 확인 |
| M 위험 | `routers/cameras.py:394-395,403-410` | `ensure_go2rtc` 예외 → False(로그 0) · `wait(timeout)` 뒤 kill 없음 | WebRTC 조용히 사라짐 · go2rtc 고아 | 로그+STARTUP_WARNINGS · `p.kill()` |
| M 위험 | `starvation_guard.py:52-58` | DELETE `name=` vs cameras.py `src=` | 1단계 회수가 no-op 일 수 있음(**go2rtc API 실측 필요**) | 파라미터 통일 + GET 확인 |
| M 위험 | `vlog.py:41-47` | RotatingFileHandler 실패 `pass` | 파일 로그 전무 | stderr 1줄 + STARTUP_WARNINGS |
| M 위험 | `rfdetr_service.py:224-226,242-244` | imwrite 반환 무시(`/tmp`, PID 고정명) | 이전 호출 이미지를 VLM 이 분석 | 반환 확인 + NamedTemporaryFile |
| M 위험 | `scripts/train/finetune_rfdetr.py:295-306` | `_nonfinite` 예외 → False | NaN 가드 fail-open | §0 #10 |
| M 위험 | `scripts/bench/infer_breakdown.py:66-70` · `ppe_path_bench.py:80-83` | `optimize_for_inference` 실패 숨김 | 벤치 수치 오염 | `optimized=false` 기록 |
| L | `detectors/rfdetr_adapter.py:222-225,113-117` · `guard.py:481-485` · `starvation_guard.py:109-112` · `routers/cameras.py:26-38` · `routers/tapo.py:98-99` · `main.py:412-416` · `finetune_rfdetr.py:450-451` · `agents/analyst.py:143-146` · `scribe.py:218,281,307` · `bench/local_sink.py:33-38` · `pilot_load_test.py:125-129` | best-effort/부가 기능 또는 진단 단서 0 | — | WARNING/debug 로그·카운터 |

### 3-6. 스레드·프로세스·자원 종료 [코드 근거]

| 심각도 | 파일:줄 | 근거 | 왜 | 제안 |
|---|---|---|---|---|
| H | `main.py:419-442` | 종료 경로에 `relay.turn_off` 없음 | §0 #2 | 〃 |
| H | `alert_notify.py:51-55,91-106` | stop 시 큐 잔여 폐기 | §0 #1 ③ | 〃 |
| H | `install_service.ps1:163` + `starvation_guard.py:100` | `sc stop & sc start` 자식 실행 | §0 #4 | 〃 |
| H | `worker.py:834-839,738-741` | join 미확인 → 이중 Worker/캡처 | §0 #8 | 〃 |
| H | `finetune_rfdetr.py:413-436,723,752` | 감시 스레드 중지 경로 없음 | §0 #10 | 〃 |
| H(Linux) | `deploy/watchdog.sh:17-20` + `vigent-watchdog.timer:9-10` | 예열 503 → 30 s 재기동 루프 | §0 #4 | 〃 |
| M-H | `install_service.ps1:148-159` | `AppStopMethod*` 미설정(≈1.5 s) | 정리 잘림 | `AppStopMethodConsole 30000` |
| M | `readiness.py:147-163` | 예열 스레드 미추적 | 종료 뒤 on_ready 가 워커 기동 | 종료 플래그 확인 |
| M | `starvation_guard.py:157-158` | stop 에 join 없음 | 종료 뒤 `_restart_worker` | join + 재확인 |
| M | `worker.py:1395-1398` | stop_all 순차, 데드라인 없음 | N×8 s | 병렬 + 총 타임아웃 |
| M | `rfdetr_service.py:190-197,234-235` | `ev.wait()` 를 DETECT_LOCK 보유 중 | VLM 정지 → **모든 워커 검출 정지** | timeout + 락 밖 대기 |
| M | `relay.py:132-140` | OFF 재시도 중 락 보유 ≈90 s | 통보 정체 | 락 밖 HTTP |
| M | `routers/cameras.py:306-314,203-214,385-393` | `psutil` requirements 미기재 → 항상 False · 연결 테스트 스레드 누적 · Popen 즉사 미확인 | go2rtc 고아 오판·RTSP 세션 고갈 | psutil 명시/폴백 · 카메라별 Lock · `poll()` |
| M | `scripts/bench/bench_4ch.py:302-336` · `bench_with_sink.sh:17,23-24` | `terminate()`(Windows TerminateProcess) · `taskkill //PID $!`(MSYS PID) · 싱크 기동 미확인 | go2rtc 고아·무관 프로세스 kill 위험·경보 p95 미측정 | CTRL_BREAK graceful · `kill $!` · GET 확인 |
| M | `deploy/portable/VIGENT_종료.bat:10` | `Stop-Process -Force` + `*ppin\go2rtc.exe` 패턴 | graceful 없음 · 서비스 설치본 go2rtc 까지 종료 | `/shutdown` 뒤 대기, `%PKG%` 한정 |
| L | `notify_heartbeat.py:155-163` · `dispatcher.py:202-213` · `alert_queue.py:41,60` · `routers/tapo.py:79-97` · `bench/local_sink.py:60-69` · `bin/vigent-serve.sh` | stop 없음 · sqlite close 없음 · gather 미취소 · SIGTERM 핸들러 없음 · `lsof … kill -9` | — | Event/close/cancel/핸들러/명령줄 확인 |

**실측으로 확인해야 할 세 가지(미검증)**: go2rtc DELETE 파라미터(`name=` vs `src=`) · 한국어 Windows 의 Get-Counter/typeperf 영문 카운터명 · `install.ps1 -ExtraEnv` 배열 바인딩(관리자 셸 실기).

## 4. 증강·학습 설정 점검

### 4-1. 현재 학습 설정의 증강 [실측: `benchmarks/results/ppe_smoke_{E,A2}_20260927/training_config.json`]

| 항목 | 값 | 의미 |
|---|---|---|
| `multi_scale` | **true** | 해상도를 스케일 목록에서 무작위 선택 |
| `expanded_scales` | **true** | 오프셋 [-5..+5] × patch 16 × windows 2 → 최소 `32×2=64`→ 실제 하한 `patch×win×2=64` 이상만 → 384 기준 대략 224~544 |
| `do_random_resize_via_padding` | false | — |
| `square_resize_div_64` | true | 정사각 리사이즈(종횡비 무시) |
| `aug_config` | **null → 기본 `AUG_CONFIG = {HorizontalFlip p0.5}` 만** | 색·블러·노이즈·원근·모자이크 **없음** |
| `augmentation_backend` | cpu(albumentations) | — |
| `use_ema` / `ema_decay` | true / 0.993 | — |
| lr / lr_encoder / weight_decay / warmup / lr_drop | 1e-4 / 1.5e-4 / 1e-4 / 0 / 100 | v1 Colab 과 동일(`provenance` 대조) |
| resolution / patch / windows / PE | 384 / 16 / 2 / 24 | — |

즉 **"강한 증강"은 한 번도 켠 적이 없다.** rfdetr 는 `train(aug_config=...)` 로 albumentations 사전을 받으며 `Perspective·Affine·Downscale·GaussianBlur·MotionBlur·ImageCompression·GaussNoise·RandomBrightnessContrast·RandomGamma` 가 이름으로 지원된다(`rfdetr/datasets/transforms.py GEOMETRIC_TRANSFORMS` 에 Perspective·Affine·Downscale 등록, albumentations 2.0.8 에 전부 존재 [실행 확인]).

### 4-2. "CCTV 유사" 증강을 넣을 자리

| 자리 | 가능 여부 | 비고 |
|---|---|---|
| rfdetr `aug_config`(albumentations, 학습 시 온라인) | **가능** — `m.train(..., aug_config=dict)` | `finetune_rfdetr.py:629` 의 `m.train(...)` 호출에 `aug_config` 인자가 **없다** → 설정 파일에 적어도 전달되지 않는다. 한 줄 추가(승인 후) |
| `augmentation_backend="gpu"`(Kornia) | 가능하나 Perspective·Downscale 미지원 목록 확인 필요 | cpu 유지 권장 |
| 오프라인 전처리(`aihub_to_vigent.scale_aug`) | 이미 있음(축소·붙이기) — 현장 데이터에도 `--scale-aug` 로 적용 가능 | 온라인 증강과 중복되지 않게 한쪽만 |

### 4-3. 대조군 설정 초안 — `configs/finetune_field_v2_aug.yaml` (실행 안 함)

`finetune_field_v2.yaml` 과 데이터·검증·held-out·epoch·seed 를 같게 두고 `train.aug_config` 만 추가했다(HorizontalFlip·Perspective(작게)·Affine(축소 위주)·Downscale·GaussianBlur·MotionBlur·ImageCompression·GaussNoise·RandomBrightnessContrast·RandomGamma). 파일 머리에 "finetune_rfdetr 가 aug_config 를 전달하기 전에는 기본 증강만 적용된다"는 단서를 적었다. 판정은 현장 held-out 300 에서 기본 증강 run 과 나란히(구간 겹치면 "미검증").

---

## 5. 우선순위 목록 (전체)

**A. 판매·설치·알림·어댑터·프로파일** — §0 #1~#10, §1-2 포트/바인드, §1-6 학원 값, §2-2 슬롯 가드 갭, §3-3 USB 빌드가 fk510 이전.
**B. 학습·평가** — §1-1 configs 절대경로, §1-4 임계 복제(forklift 4값), §1-5 클래스 리스트 12곳, §3-2 cuDNN 비결정(±2 오차로 덮음), §3-3 학습 의존성 미핀, §4-2 `aug_config` 미전달.
**C. 문서** — `docs/deploy/usb_installer_design.md` 실기 미검증 항목 표시, ALGORITHM_TRUTH §2-2 "person 만 통과" 정정, CLAUDE.md 기술 스택 ultralytics, main.py docstring 8000, vision.yaml 죽은 `cooldown_sec`, make_prelabels 폐기 표시.

수정은 승인 후 A → B → C 순으로, 각 항목에 테스트 1건씩.
