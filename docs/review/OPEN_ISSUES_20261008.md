# 열린 문제 한 곳에 — 2026-10-08

> 출처: `CODE_AUDIT_20260928` §0~§5 중 미해결 · `STATUS_20261008` §5 · `field_verification_20260928` 미측정 · `SETUP_NEW_MACHINE` 수동 항목 · `NEXT.md` 대기 항목 · `ALGORITHM_TRUTH_20260926` §7.
> 이미 고친 것은 본문에 없고 부록 A 에 커밋만 있다. 각 항목의 "근거" 는 2026-10-08 밤 코드·파일을 다시 열어 확인한 위치다(파일:줄은 당일 HEAD `cf335ce` 기준).
> 상태: **미착수** / **코드로 고침·실기 미확인** / **사용자 대기** / **데이터 대기**. 예상 소요는 [추정].

## 오늘 바로 할 것 5개

| # | 항목(아래 번호) | 누가 | 승인 | 왜 오늘인가 |
|---|---|---|---|---|
| 1 | 텔레그램 봇 토큰 재발급 (#1) | 대표 | — | 노출된 토큰이 11일째 유효. 5분 |
| 2 | Gmail 앱 비밀번호 → `SMTP_PASS` (#3) | 대표 | — | 원격 채널이 하나뿐(20일 213건 미전달 사고 구조 그대로). 코드는 끝나 있음 |
| 3 | 개발기 경보 큐 pending 3건 처리 (#6) | Claude Code | **승인 필요**(DB 행 삭제/이동) | 개발기 서버를 띄우면 실채널로 나간다 |
| 4 | 법령 화이트리스트 게이트 fail-closed (#5) | Claude Code | ☑ 승인 없이 가능 — **실행 대기** | 검증 안 된 조문이 통과하는 안전 결함, 1시간 |
| 5 | 감시 중단 원격 통보 구현 (#4) | Claude Code | ☑ 승인 없이 가능 — **실행 대기** | 기존 큐 재사용, 반나절. 토큰·Gmail 과 무관하게 진행 가능 |

---

## H (안전·판매·보안에 직접)

| # | 증상 | 근거 | 상태 | 누가 | 해결 방법 | 소요 |
|---|---|---|---|---|---|---|
| 1 | 텔레그램 봇 토큰이 2026-09-27 도구 출력에 노출됐는데 **아직 재발급 안 됨** | `config/notify.yaml` mtime 2026-09-27 03:15(노출 이후 변경 없음), STATUS_20261008 §2-d | 사용자 대기 | 대표 | BotFather 재발급 → notify.yaml 갱신 → 서버 기동 로그 `자가시험 통과` 확인 | 5분 |
| 2 | **현장 데이터 0** — PPE v2 학습·현장 평가·held-out 전부 대기 | `D:\vigent_private_data\field\` 에 합성 픽스처만(451 파일), `D:\vigent_field` 09-03 이후 변화 0 (STATUS §2-b) · ALGORITHM_TRUTH §7-1 "현장 정답지 부재" | 사용자 대기 | 대표 | 촬영 날짜 확정(체크리스트 `docs/data/field_capture_checklist.md`) 또는 학원 DVR 녹화본 확보 → `field_prelabel.py` | 촬영 반나절 + 동의서 |
| 3 | 원격 알림 채널이 텔레그램 **하나**(Gmail `smtp_pass` 미입력) | notify.yaml `smtp_host/user/email_to` 비어 있음, `.env` 에 `SMTP_PASS` 없음 · ALGORITHM_TRUTH §7-1 "통보 채널 2중화" | 사용자 대기 | 대표 | Gmail 앱 비밀번호 발급 → `.env` `SMTP_PASS` + notify.yaml smtp 3값 → `/health notify.smtp_state=ok` | 10분 |
| 4 | **감시 중단 원격 통보 코드 0건** — health 전이·슬롯 사망·카메라 stale 가 아무에게도 안 감 | `grep -rln "health_transition\|notify_health\|phase_change" vigent-core` = 0 (10-08) · ALGORITHM_TRUTH §7-3 #2 | 미착수 | Claude Code | `health_status` 전이(healthy→degraded/failed, 슬롯 DEGRADED, 카메라 stale>N s)에서 `alert_notify.submit(cam="system", rule=...)` + 억제(같은 전이 1회) + 테스트 | 반나절 |
| 5 | 법령 화이트리스트 게이트 **fail-open** — 검증 실패 시 조문이 그대로 통과 | `vigent-core/agents/copilot.py` `gate_vlm_text` 예외 → `pass`(CODE_AUDIT §3-5 H) | 미착수 | Claude Code | 예외 시 "안전관리자 확인 필요" 문구로 대체 + ERROR 로그 + 테스트(게이트 실패 주입) | 1시간 |
| 6 | 개발기 `data/alert_queue.db` 에 **pending 3건**(09-28 실기 중 생성, 시도 0) — 실채널 설정된 개발기 서버를 띄우면 텔레그램으로 나간다 | sqlite `status='pending'` 3건(id 452~454) · 개발기 운용 원칙(CLAUDE.md) | 미착수 | Claude Code(대표 승인) | 대표가 "dead 이동" 또는 "삭제" 결정 → 처리 → `pending 0` 확인 | 5분 |
| 7 | PPE 미착용 현장 성능 **미달** — NO-Hardhat R 64.1 [51.8, 74.7] (합격 85), NO-Safety Vest 83.7 (합격 90) | `benchmarks/results/v1_heldout_eval.json` · STATUS_REPORT_20260928 §2-2 · 재학습 6회 전부 v1 구간(정지 규칙) | 데이터 대기(#2) | Claude Code | 현장 held-out 300 확보 후 `configs/finetune_field_v2{,_cont,_aug}.yaml` 3종 학습 → `eval_v1_heldout.py --field-heldout` 판정 | 데이터 후 1~2일 |
| 8 | AI Hub 510 **상업 활용 문의 발송·회신 기록 0** — fk510_smoke 를 실증 밖(판매)에 쓸 수 없음 | `docs/model/*`·NEXT.md 에 날짜·요지 없음(STATUS §2-e) · STATUS_REPORT §4-5 | 사용자 대기 | 대표 | 문의 발송(주체 = 사업자) → 회신을 `docs/model/forklift_finetune_smoke_20260926.md` 에 기록 | 작성 1시간 + 회신 대기 |
| 9 | 학원 실기 **GTX 1650 Ti 4 GB 미실측**(5070 Ti 에서 nvidia-smi 3,425 MB — 여유 불명) · RTX 5060 미실측 | STATUS_REPORT §2-4 · ALGORITHM_TRUTH §7-1 | 사용자 대기(기기) | 대표(기기) → Claude Code(벤치) | 노트북에 USB 스테이지 설치 → `bench_4ch.py --repeat 3` → VRAM·age p95 | 1시간 |

## M (운용 신뢰·정합·설치)

| # | 증상 | 근거 | 상태 | 누가 | 해결 방법 | 소요 |
|---|---|---|---|---|---|---|
| 10 | VLM 대기 중 `DETECT_LOCK` 을 쥔 채 `ev.wait()` → VLM 이 멈추면 **모든 워커 검출 정지** | `vigent-core/rfdetr_service.py` DETECT_LOCK(F-14 RLock) 안에서 대기(CODE_AUDIT §3-6 M) | 미착수 | Claude Code | 락 밖에서 timeout 있는 대기 + 테스트(VLM 지연 주입 시 다른 워커 검출 지속) | 2시간 |
| 11 | RTMPose 로드 실패가 **영구 침묵**(`_failed=True`, 로그 0, /health 모름) → 근골격·무동작 경보 조용히 사라짐 | `vigent-core/worker.py:396` 부근(CODE_AUDIT §3-5 M) | 미착수 | Claude Code | `state["pose_error"]` + 간헐 WARNING + `/health` 노출 + 테스트 | 1시간 |
| 12 | go2rtc 고아 프로세스 오판 — `psutil` 이 requirements 에 없어 `import psutil` 이 항상 실패 → 남의 go2rtc 로 봄 · `wait(timeout)` 뒤 kill 없음 | `routers/cameras.py:318` `import psutil`(try 안) · `requirements.txt` psutil 0건 · 벤치 `bench_4ch.py:326 terminate()` · `VIGENT_종료.bat` `Stop-Process -Force` 패턴 | 미착수 | Claude Code | psutil 명시(또는 `tasklist` 폴백) + `p.kill()` + 종료 스크립트 `%PKG%` 한정 + 테스트 | 2시간 |
| 13 | `Path("/tmp")` 3곳(Windows 에선 `\tmp`) + `cv2.imwrite` 반환 미검사 2곳 → VLM 이 이전 이미지 분석 / 수집 수 과대 | `rfdetr_service.py`·`ml/vlm_risk_summary.py` `/tmp` 3건 · `worker.py:1032` imwrite(CODE_AUDIT §3-4·§3-5) | 미착수 | Claude Code | `tempfile.NamedTemporaryFile` + imwrite/`imencode+tofile` 반환 확인 + 테스트 | 1시간 |
| 14 | 종료 경로 잔여: 예열 스레드 미추적(종료 뒤 `on_ready` 가 워커 기동) · `starvation_guard.stop()` join 없음 · `dispatcher.mark_sent(row_id)` 채널 인자 없음(`email_last_success` 미기록 → "이메일만 죽음" 미감지) | `readiness.py` vigent-warmup join/stop 0 · `starvation_guard.py` stop 에 join 0 · `dispatcher.py:410` | 미착수 | Claude Code | 종료 플래그·join·`mark_sent(row_id, channels=)` + 테스트 3건 | 2시간 |
| 15 | 코드 기본값 ≠ yaml 잔여 4곳 — `BYTETRACK_MIN_FRAMES=1`(yaml 0) · `ergonomics.py` neck 15/25·shoulder 12/25(vision 25/40·15/35) · `retention.WARN_FREE_BYTES` 5 GB(yaml 없음) · `preflight.ps1` 사양 상수(VRAM 8·RAM 16·Disk 20·cu130·드라이버 580) | `guard.py:364` · `ergonomics.py:79,89` · `retention.py:102` · `preflight.ps1:24-64`(CODE_AUDIT §1-4) | 미착수 | Claude Code | `defaults.py` 로 모으고 yaml 과 대조 테스트(#6 방식) · preflight 사양은 JSON 하나로 build_portable 과 공유 | 2시간 |
| 16 | 포트·호스트 리터럴 — `realtime_core.js:2769` **8005**(고아 포트) · go2rtc `127.0.0.1:1984` cameras 2·tapo 5곳 · 8010 20곳 · `/tapo/*`·스트림명 `tapo` 브랜드 종속 | CODE_AUDIT §1-2 | 미착수 | Claude Code | JS 8010 정정 · `go2rtc_client.BASE` 하나 · `VIGENT_PORT` 정본 · tapo 범용명은 OpenAPI 110 불변 조건 검토 후 별도 승인 | 2시간(tapo 제외) |
| 17 | 설치 도구 실기 **미측정 2건** — 카메라 2대 이상 상태의 `sc stop` 정지 시간(실측은 카메라 0대 3.06 s) · Move-Item 실패 유도 후 `Start-Service` 복구 | `field_verification_20260928.md` §미측정 | 코드로 고침·실기 미확인 | 대표(학원 실기) | 학원 기기에서 §3 재실행 · 파일 열어 둔 채 업데이트 설치 | 각 10분 |
| 18 | 새 기계에서 **수동 복사**가 필요한 자산 — `forklift_rfdetr_fk510_smoke.pth`(매니페스트 `local:`, Release 미업로드) · `.onnx` 3종(매니페스트 미등재) | `weights_manifest.json` fk510 `url: local:` · `SETUP_NEW_MACHINE.md` §2 · `setup_env.py --preflight` 출력 | 미착수 | Claude Code(Release 쓰기 권한 필요) | Release `weights-v1`(또는 새 태그)에 4파일 업로드 → 매니페스트 `release:` + onnx 3종 등재 → `fetch_weights.py --check --all` 전부 OK | 30분 |
| 19 | 학원 임시 테마 2개가 공용 `themes/` 에 미추적으로 남음 | `themes/academy_boda_tmp/`·`themes/academy_fk2_tmp/`(CODE_AUDIT §1-6 M) | 미착수 | Claude Code(삭제 승인) | `deploy/academy/` 로 옮기거나 삭제(git 미추적이라 복구 불가 — 대표 결정) | 10분 |
| 20 | 지게차 **주행 장면** 검출 저하 원인 미확인(04/05 86.1/87.0 % vs boda_ax 99.3/92.5) | `docs/model/forklift_finetune_smoke_20260926.md` §3-1 · ALGORITHM_TRUTH §7-2 | 미착수 | Claude Code | 주행 프레임만 뽑아 conf 분포·박스 크기 대조 → 운용점/증강(motion blur) 가설 검증 — 시드 1개 스모크라 재학습 포함 가능 | 2시간 분석 |
| 21 | 노트북·개발기 **두 계보 미통합** — 노트북 브랜치 원격 없음, 노트북은 F-34(경보 유실) 미반영 상태로 추정 | `git branch -r` 에 `laptop/*` 없음 · NEXT.md 남은 결정 4 · ALGORITHM_TRUTH §7-1 | 사용자 대기 | 대표 | USB 스테이지(`D:\vigent_usb_stage`, 커밋 f9bddf9)로 노트북·파일럿기 **재설치** — git 분기가 구조적으로 사라짐 | 1시간/대 |
| 22 | L2 계보 미결정(`vigent-l2` 설계 우수·미실행 vs `vigent-vlm` 실행 실적·기본값 클라우드) — L1 이벤트 브리지 0 | ALGORITHM_TRUTH §7-2·§7-3 #4 · 저장소 옆 폴더 없음, 번들만(`vigent-l2_wip_20260926.bundle`) | 사용자 대기 | 대표 → Claude Code | 하나 선택 → `L1Event` 계약으로 브리지 구현 · VLM 기본 엔드포인트 로컬로 | 결정 후 1~2일 |
| 23 | Windows 전용 가정 — `vlog` RotatingFileHandler 가 다른 프로세스가 열고 있으면 rollover 실패(로그 무한 증가) · `bench_4ch.py` Get-Counter(Linux 불가·한국어 카운터명 **미검증**) · `pilot_load_test.py` typeperf/OEM 디코드 | CODE_AUDIT §3-4 M | 미착수 | Claude Code | 프로세스별 로그 파일명 · nvidia-smi 폴백 · psutil | 2시간 |
| 24 | `main` 브랜치가 `audit/cleanup-20260906` 보다 **126 커밋 뒤**(2026-09-08 정지) — 어느 쪽이 정본인지 외부엔 보이지 않음 | `git rev-list --count main..HEAD` = 126 (STATUS §1-1) | 사용자 대기 | 대표 | PR/병합 결정(공개 전환 시 CLAUDE.md 규칙 10 ⛔차단 항목 — 얼굴 이미지 이력 재작성 — 먼저) | 결정 10분 + 이력 재작성 반나절 |
| 25 | vcruntime 동봉본 14.38 vs 요구 14.44 — 포터블 런처 로드 위험 | NEXT.md "결정 없이도 남은 숙제" · `docs/deploy/vcruntime_load_2026-09-23.md` | 사용자 대기(결정) | 대표 → Claude Code | 권고 (a) 동봉본 교체 → build_portable 1b 단계 SHA 갱신 | 30분 |
| 26 | 사업자 등록 — 데이터 활용 동의서·AI Hub 문의 주체 | NEXT.md 남은 결정 2-2 · STATUS §3 | 사용자 대기 | 대표 | — | — |
| 27 | CVAT 미설치(Docker 데몬 꺼짐) — 현장 초벌 라벨 검수 경로 미검증 | `docker ps` 연결 실패(10-08) · NEXT.md 남은 결정 3 | 사용자 대기 | 대표 → Claude Code | Docker 기동 → `docs/labeling/cvat_setup.md` → 픽스처 XML 10초 왕복 | 1시간 |

## L (정리·설계 공백·기록)

| # | 증상 | 근거 | 상태 | 누가 | 해결 방법 | 소요 |
|---|---|---|---|---|---|---|
| 28 | 알고리즘 설계 공백(기록) — 시계열 N-of-M 투표 없음 · 카메라별 마스크/시간대 프로파일 없음 · 자세가 안전 규칙에 미사용 · 다중 카메라 동일인 없음 · 야간/역광 데이터 0 · 거리 캘리브레이션 없음 · 오탐 피드백→재학습 루프 없음 · 카메라 tamper 없음 · 클래스별 검출률 시계열 없음 | ALGORITHM_TRUTH §7-2 | 미착수 | 대표(우선순위) → Claude Code | 현장 데이터(#2) 뒤 우선순위 결정. 각 항목 S~M | — |
| 29 | RIG(줄걸이) 상태기계 구현됐으나 **호출부 0** | `grep -rln rig_monitor vigent-core` = 0(10-08) · ALGORITHM_TRUTH §7-2 | 미착수 | 대표(쓸지 결정) | 쓰면 워커 신호에 연결, 안 쓰면 `_archive/` | 결정 후 1시간 |
| 30 | `/alerts/test` 첫 건 `channels_sent` 미기록 | NEXT.md `B-alerts-test-channels` | 미착수 | Claude Code | 기록 경로 보강 + 테스트 | 30분 |
| 31 | 벤치 `ppe_path_bench.py` 가 `optimize_for_inference` 실패를 숨김(`infer_breakdown.py` 는 기록) | CODE_AUDIT §3-5 M · B-2 와 같은 병 | 미착수 | Claude Code | `optimized=false` 기록 | 15분 |
| 32 | `scripts/capacity_probe.py` ruff I001(게이트 범위 밖이라 방치) | `ruff check scripts/capacity_probe.py` 1건 | 미착수 | Claude Code | 그 파일만 `--fix` | 2분 |
| 33 | 마법사 실카메라·실토큰 미검증 · 검수 잔여 28장 보류 | NEXT.md "결정 없이도 남은 숙제" | 데이터 대기 | 대표 | 파일럿기 설치 때 자연 검증 · 28장은 재방문 정답지가 정본 | — |
| 34 | 새 환경 점검이 **이 기계 안의 새 clone** 으로만 된 것 — 다른 OS·GPU 미검증 · 전역 PATH `ruff`(0.16.1)가 남아 있어 진짜 새 기계의 "ruff 없음" 은 재현 못 함 | `SETUP_NEW_MACHINE.md` 전제 | 코드로 고침·실기 미확인 | 대표(기기) | 노트북에서 §1~§6 수행 → 통과 기록 표 | 1시간 |
| 35 | 문서 노후 — ALGORITHM_TRUTH §7-1 "forklift 스모크 진행 중"(완료됨) · CLAUDE.md 스택의 mmaction2·TensorFlow [미검증] | STATUS §2-f | 미착수 | Claude Code | 한 줄 정정 | 10분 |

---

## 부록 A. 이미 고친 것 (본문에 없음 — 날짜·커밋만)

| 날짜 | 커밋 | 내용 |
|---|---|---|
| 2026-09-28 | `6df1ef6` `f40596d` `75b6285` `4edb5af` `aecc5d3` `69166e1` `2bce623` `78d8c11` `286f1ef` `af34d11` | CODE_AUDIT A 그룹 #1~#10 + B-1 |
| 2026-09-28 | `0c8718d` `3bf29bc` `1a2bf5e` `a6820bd` `7eb5d01` | B-2 평가 결정성 · B-3 학습 핀 · B-4 절대경로 · B-5 클래스 정본 · B-6 pip check |
| 2026-09-28 | `3b6dbe7` `b4aa504` | C-1 문서 6건 · C-2 상태표 |
| 2026-09-28 | `5d5b69e` `f766c8a` `88ea5ad` `f9bddf9` `493e699` | USB fk510 배선 · 실기 결함 8건(go2rtc `src=`·`VIGENT_HOST=$Bind`·업데이트 복구·A1 sc 파싱·relay 로그·회귀) · uninstall 설치본 복사 · 최종 스테이지 |
| 2026-10-08 | `5bf53a3` `b2817a5` | STATUS_20261008 |
| 2026-10-08 | `b0065e7` `cf335ce` | 새 환경: guard 캐시 폴백+RF_HOME · `setup_env --preflight` · gate.ps1 venv ruff + **mypy 단계**(그동안 없었음) · fetch_weights local: 안내 · pip check ultralytics · 진입 스크립트 14개 UTF-8 · SETUP_NEW_MACHINE.md |

## 부록 B. 이 문서를 다시 만드는 법
`git log --oneline 493e699..HEAD` · `grep -rln "health_transition\|notify_health" vigent-core` · `grep -n -A3 gate_vlm_text vigent-core/agents/copilot.py` · `python -c "import sqlite3;print(sqlite3.connect('data/alert_queue.db').execute(\"select status,count(*) from alerts group by 1\").fetchall())"` · `python scripts/setup_env.py --preflight` · `git rev-list --count main..HEAD` · `git branch -r`
