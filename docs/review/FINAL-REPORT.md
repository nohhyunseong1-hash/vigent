# VIGENT 전체 서비스 검토 — 최종 보고서 (2026-09-08)

> 대상: `D:\vigent_original` 브랜치 `audit/cleanup-20260906` = `b7f49d9`(main `ee4557d` 동일 트리). 검토 방식: 코드 정독·grep·정적 분석·테스트 실행·읽기 전용 조회·웹 검색. **코드는 수정하지 않았다.**
> 산출물: `docs/review/00-inventory.md` ~ `08-compliance-gap.md`(Phase 별 근거 전문, 총 2,900여 줄). 이 보고서는 그 요약이며 모든 항목은 Phase 문서의 `파일:줄` 근거를 가리킨다. 지어낸 수치는 없고, 재지 못한 것은 "미측정"으로 남겼다.
> 배포 전제: RTSP 카메라 4대 · Windows NSSM 서비스 · 대상 현장 미확정(제조/건설/물류). ★**기기 역할(2026-09-09 대표 정정)**: **배포기 = 현장 노트북**(i7-10750H / GTX 1650 Ti 4GB / DDR4 16GB / SSD 1TB / Win10 Pro — `md/DEPLOYMENT.md:22`), **개발기 = 이 데스크톱**(Ryzen 9 9900X / RTX 5070 Ti / Win11 Home — 현장에 가지 않는다). 검토·테스트·부하 키트 검증은 개발기에서 돌았고, 현장 성능 판정의 유일한 근거는 배포기의 2026-08-22 램프 실측이다(`docs/academy_visit_day.md:718-741`). 역할표는 `00-inventory.md` 맨 위에 고정.

---

## 1. 요약 (경영진용)

1. 현재 상태 한 문장: **"1대 카메라·사람이 지켜보는 조건에서는 잘 동작하고 기록·통보 내부 장치는 상용 수준이지만, 무인 4대 운영에서 '감시가 멈춘 것'을 아무도 모르게 되는 경로가 여러 갈래로 열려 있고, 판매 5대 기능 중 2개(근접·통과형 침입)의 미탐률이 실측되지 않았거나 낮다."**
2. 설치 전 반드시 해결할 **P0 10건**(§2). 그중 코드 수정이 필요한 것 7건(공수 S 4·M 3), 절차·장비로 해결하는 것 3건.
3. 핵심 3가지:
   - **감시 중단 무통보**: 카메라 단절·슬롯 사망·예열 실패·프로세스 정지가 전부 `/health` 503으로만 수렴하고, Windows 배포에는 그것을 읽는 주체가 없다. 통보 채널은 텔레그램 1개뿐이며 **검토 시점에 그 채널이 401로 죽어 있었다**(오늘 발생한 critical 26건 전부 dead).
   - **미탐 근거 부족**: 경보 경로 person 재현율 dev 38~42%(원거리 0~8%, 2026-08-25, 1fps 정답지)이고, "멈추지 않고 통과하는 침입자"와 "지게차 옆 보행자가 운전자로 오인되는 7.6%"는 안전사고 직결인데 대책이 보류 상태다.
   - **배포기(노트북)는 4대 상한에 걸려 있고 근거가 램프 1회뿐이다**: 2026-08-22 램프 실측이 유일한 성능 근거(한계 6·권장 4, N=3→4에서 검출 p95 220→675ms 3배 급증, 한계 시 CPU 94.9%·GPU util 40%·VRAM 1.47GB) — 4h 소크·발열·경보 지연·실카메라 4대는 미측정. VRAM 4GB는 충분하다(개발기에서 본 4.0GB 신호는 다른 앱 몫, 서버 몫 1.2~1.4GB 확정). 절전·덮개·정전 복구·UPS 절차는 문서에 0건. 하드웨어 교체 전에 코드로 부하를 줄일 선택지(§5-3)를 노트북에서 실측하고, 미달이면 §5-4의 대안(교체 사양 또는 3대 축소)으로 간다.
4. 강점(코드로 확인): 경보 선기록 후전송 큐·데드레터·게이트, 기동 실패 이벤트 로그·통보, 보존 자동 삭제·pin·삭제 감사, 얼굴 모자이크, 자격증명 마스킹, 법령 인용 위험성평가서, 실측 문서화 규율(규칙 7·9·11). 게이트 5종 통과·662 테스트·커버리지 59%.
5. 경쟁 기준선 26항목: **있음 9 · 부분 8 · 없음 9**(§3). 없음 9개 중 6개(모바일 앱·다국어·중앙 관제·OTA·오탐 피드백 학습·RBAC)는 상용 제품 기본 항목이다.

---

## 2. 심각도별 이슈 목록

형식: 제목 / 근거(파일:줄, Phase 문서 ID) / 영향 / 권장 조치 / 공수(S·M·L). 여러 Phase가 같은 결함을 다른 각도에서 본 경우 합쳤다.

### P0 — 설치 전 필수(안전사고 직결 또는 현장에서 시스템이 죽을 수 있음)

| # | 제목 | 근거 | 영향 | 권장 조치 | 공수 |
|---|---|---|---|---|---|
| P0-1 | **"감시 중단"을 원격으로 알리는 코드 경로가 0건 — Windows 배포에 `/health`를 읽는 주체도 없다** | Ph1 A-02: `alert_notify.submit` 호출부 8곳 전수에 health 상태 전이·카메라 stale·슬롯 degraded·예열 실패·워커 전멸 통보 없음; `install_service.ps1`에 `schtasks` 0건, `watchdog.sh`는 Linux 전용. Ph3 I-2: `stale_*|unhealthy` 참조 0건. Ph6 OPS-02: 외부 heartbeat 0 | 4대 중 1대가 야간에 죽어도 `/health` 200+degraded뿐. 프로세스 자체가 없으면(수동 `sc stop`·3단계 재기동 실패) `/health`도 사라져 무기한 무감시 | ① 앱 내부 health 전이 통보기(`overall` healthy→degraded/unhealthy 및 회복 시 `alert_notify.submit(cam="system", rule="health_*", level="critical")`) ② 설치 스크립트가 `service_status.ps1` 5분 주기 예약 작업 등록 + exit≥2 시 텔레그램 curl ③ 가능하면 외부(관제 PC/클라우드) 주기 heartbeat | S / S / M |
| P0-2 | **사람에게 닿는 채널이 텔레그램 1개뿐이고, 지금 401로 죽어 있다 — 데드레터 요약 통보까지 같은 채널로 죽는다** | Ph4 P0-1: `data/alert_queue.db` 오늘 21:22~21:35 dead 26/26 `telegram 401`(부하 시험 발생분, id 88~113, 요약 통보 id 93 포함); `notify.yaml` 이메일·웹훅 비어 있음; 기동 시 채널 자가시험(`getMe`) 없음; `/hub` 배너가 `channels_configured`·`last_config_error`를 그리지 않음(`index_hub.html:217-229`) | 실카메라를 붙이면 화재·쓰러짐 경보가 아무에게도 가지 않는다 | ① 토큰 재발급·`/alerts/test` 검증 + **2번째 원격 채널(이메일 또는 웹훅→문자 게이트웨이) 필수 항목화** ② 기동 시 `getMe` 검증 실패 → STARTUP_WARNINGS + Windows 이벤트 로그 ③ 데드레터 요약은 로컬 채널(이벤트 로그·화면 배너)로도 ④ `/hub` 붉은 배너 | S(①②④) / M(③) |
| P0-3 | **경보 경로 person 재현율 dev 38~42%, 원거리(화면높이<10%) 0~8% — 추적기가 검출을 버린다** | Ph2 #1: `x5_recall_knobs_interim.md:49-60`, `v1_field_baseline_report.md:61-87`(2026-08-25, ByteTrack 운영 구성, 1fps 표본), 검출 직전 71.3%→추적 후 42.0%; `guard.py:744-800`. 현장 생존율 88.3%(`reports/…v1.2.md:297-308`)는 GT 없는 값이라 반증이 못 됨 | 위험구역 침입·협착 **미탐**. 원거리 작업자는 사실상 안 보임. 재현율 목표치 자체가 선언돼 있지 않음 | ① 2fps 정답지로 재현율 재측정(현재 전부 1fps) ② 검출통과(passthrough)를 디바운스와 맞물리게 재설계 ③ ByteTrack 빈 프레임 `update()` 호출(백로그 PQ) ④ person 재현율 목표치 선언 + CI 회귀 게이트 | M |
| P0-4 | **"멈추지 않고 통과하는 침입자" 미측정 — enter_s 1.0s + 2fps + tid 교체 4회/20초** | Ph2 #2: `zone_debounce.py:30-31,95`, `tuning.yaml:239`, `field_academy_2026-08-27.md:89,122-123`("미측정" 자인) | 유일한 판매 기능(구역 침입)이 빠른 통과를 놓칠 수 있는데 검증 없음 | 통과 시나리오(1~3m/s) 실카메라 실측 → enter_s 를 시간·속도 기준으로 재정의 또는 tid 무관 위치 기반 키(grid) 상시 병행 | M |
| P0-5 | **근접(협착) 거리 무캘리브레이션 + 깊이 없는 운전자 제외 → 지면 보행자 7.6%(26/344)·최장 2.1초가 경보 대상에서 빠진다** | Ph2 #3: `proximity.py:103-112`(장비 박스 폭 기준자), grep 호모그래피 0건, `reports/…v1.2.md:31,143,152`, `field_academy_2026-08-27.md:118-121`(리포트 스스로 "안전 관련·최우선") | 지게차 옆 보행자가 "탑승자"로 분류돼 협착 경보 누락 — 사망 직결 시나리오. 지게차 검출 자체도 기본 비활성(F-7)이라 safety 프로파일에서는 근접 기능이 꺼져 있음(Ph8 C-10) | 단기: 발끝 높이 비교(리포트 16/16 육안 분류 기준) 추가; 중기: 바닥 호모그래피(4점 마킹) + 거리 오차 실측 리포트 | M / L |
| P0-6 | **카메라 1대 장기 단절이 hang 오판 → `stale_detect` 오분류 → 기아 3단계 전체 프로세스 재기동 후보로 승격되며, 그 재기동 명령의 성공은 미검증** | Ph1 A-01/B-08, Ph3 I-1: `worker.py:917`(hang 재시작이 `last_frame_ts=now` 리셋), `:1229-1234`(무프레임은 하트비트 미갱신) → 15~16s마다 hang 반복 → `health_status.py:398-401`이 STALE_DETECT → `starvation_guard.py:114-131` → `Popen("sc.exe stop VIGENT & sc.exe start VIGENT", shell=True)`(`:100`). 실측 부합: `audit/soak_after_fixes_2026-08-26.md`(죽은 주소 cam_c200 → stale_detect + 기아 2단계). ★Ph3 I-9는 restarts 카운터가 STARTING 에서 리셋돼 3단계 도달 불가로 분석 — **두 분석이 갈리므로 실측으로 확정 필요** | 최선: 카메라 문제를 "검출 정지"로 오진하고 워커·go2rtc 슬롯을 불필요하게 재시작. 최악: 6분마다 4대 전체 재기동 또는 `sc stop` 뒤 `sc start` 실패로 **서비스 STOPPED 잔류 + 무통보** | ① hang 판정과 프레임 하트비트 분리(`loop_alive_ts`), 재시작 시 `last_frame_ts` 리셋 금지 ② 캡처 "프레임 없음" 신호를 health 입력에 넣어 STALE_FRAME 정확 분류 ③ 3단계는 `os._exit(3)` + NSSM `AppExit 3 Restart`로(SCM 정지 금지) ④ 실카메라 단절 ≥6분 시험을 절차에 추가 | M |
| P0-7 | **예열 실패는 조용하다 — 프로세스는 살고 워커 0대, 재시도·통보·재기동 없음** | Ph1 A-03: `readiness.py:269-275,306-309`(FAILED 로그·상태만), `:318-324`(`on_ready` 미호출), `main.py:517`(`_required`가 스레드 시작만 감쌈). 필수 가중치 부재(F-8·M4-5 원 사고 유형)가 이제 이 경로로 들어옴 | 설치 당일 가중치 누락·CUDA 초기화 실패가 곧 무기한 무감시. M4-5가 막았다고 믿는 사고가 다른 문으로 재진입 | FAILED 시 `_notify_startup_failure` 경로(상태파일·이벤트 1000·원격 통보) + 정책 결정(재raise로 기동 실패 처리 또는 N회 재시도 후 확정) | S |
| P0-8 | **배포기(노트북) 절전·덮개 닫힘·USB/NIC 절전 통제 절차 0건** | Ph6 OPS-01: `grep powercfg/덮개/UPS docs deploy md` → 0; `SITE_CHECKLIST.md` N-1~N-5에 전원 항목 없음. 노트북의 실제 `powercfg` 값은 **미확인**(이 세션은 개발기에서 돌았다) — 개발기조차 USB 선택적 절전이 켜져 있었으므로 노트북 기본값도 같을 가능성이 크다(추정). Win10 Pro·BitLocker는 이미 적용(`SITE_CHECKLIST.md:142-153` 실증) | 덮개를 닫거나 절전 진입 시 서비스가 멈춰 감시·경보 무기한 공백, 앱은 아무것도 못 남김 | `deploy/windows/set_power_plan.ps1`(덮개=아무 것도 안 함 AC/DC·절전/최대절전 AC 0·USB/PCIe/NIC 절전 해제·`powercfg /h off` + `powercfg /query` 재검증 출력 + audit 저장) + SITE_CHECKLIST N-6 + 재설치 검증 스크립트에 전원 검증 단계 | S |
| P0-9 | **정전 → 전원 복구 시 배포기(노트북) 자동 부팅 보장 없음, UPS·외부 heartbeat 절차 0건** | Ph6 OPS-02, §4-2 정전 추적: 서비스 자동 기동은 "부팅 이후"만(`install_service.ps1:132`); BIOS AC 복구·UPS 언급 0. 노트북은 배터리 소진 후 AC 복구 시 자동 켜짐이 BIOS에 없는 기종이 많다(기종별 **확인 필요**) | 노트북은 배터리가 짧은 UPS 역할을 하지만 소진 뒤에는 사람이 켜기 전까지 죽어 있고 원격에서 알 수 없다 | BIOS "AC Power Recovery/Power On AC" 유무 확인 · UPS(노트북 어댑터+공유기+PoE, 정전 창을 넘길 용량) · SITE_CHECKLIST N-7·N-8(외부 heartbeat) — P0-1 ③과 같은 장치 | S(문서) / M(폴러) |
| P0-10 | **승인(감사추적) 기록이 "누가"를 증명하지 못한다 — approver 자유 문자열 + 해시체인·서명 없음** (증빙 도구로 팔 경우) | Ph8 C-1: `routers/safety_core.py:274`(`approver = payload.get("approver") or "안전관리자"`), `:296`; `audit_store.py:21-40`(append JSONL, 무결성 0); `auth_session.py:8-10`(단일 운영자). Ph4 P1-4: ack 키가 (ts, rule)뿐이라 같은 초 다른 카메라 이벤트가 한꺼번에 "승인됨"(`audit_store.py:62-64`) | `audit_store.py:3-5`가 "법적 분쟁 시 사람이 최종판단했음을 입증"이라 선언하나 누구나 임의 이름으로 POST 가능·파일 수정 탐지 불가 → 증빙 주장이 무너진다. **제품을 "보조 감시 + 서류 초안"으로만 팔면 P1으로 내려갈 수 있다(§8 Q1)** | ① 승인자 = 서버가 세션 주체로 채움(요청값 무시) ② 레코드 `prev_hash`+`sha256` 체인 + 일자 마감 루트 해시 외부 앵커링 ③ 이벤트 id 부여(ack·pin·평가서 모두 id 참조) ④ 증거 JPEG 해시를 이벤트에 기록 | M |

### P1 — 운영 신뢰성(오탐/미탐 급증·보안 침해·데이터 유실)

| # | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|
| P1-1 | 인터넷 단절 ≈4~5분이면 경보 dead → 재전송 없음, 요약 통보도 같이 죽음 | Ph1 B-01, Ph6 OPS-03: `alert_queue.py:47-52,142-149,214-217`(10회·백오프 상한 60s, `due()`는 PENDING만) | 통신 장애·공유기 재부팅·정전 복구 직후 경보 영구 소실 | 시간 기반 재시도(24h, 상한 5~10분) + 회복 시 dead→pending 일괄 재전송 + 관리자 재전송 라우트 | S~M |
| P1-2 | 릴레이(사이렌)가 원격 3채널 타임아웃(최대 ≈20s) **뒤에** 호출되고, 릴레이 재시도가 `_lock`을 잡은 채 통보 스레드를 최대 ≈87s 정지 | Ph1 B-02, Ph4 P1-2: `dispatcher.py:269-299`, `relay.py:85-138` | 현장에서 가장 빨라야 할 물리 출력이 가장 느린 채널에 묶임; 릴레이 장애 시 다음 critical 통보 1분+ 지연 | 릴레이를 `submit` 직후 별도 즉시 경로/스레드로, 원격 채널 병렬 전송 | S~M |
| P1-3 | 크래시 시 사이렌 ON 고정(F13) — 기동·종료 시 OFF 송신 없음, 하드웨어 read-back 없음 | Ph4 P1-1: `relay.py:153-158,161-175`, `main.py:419-442` relay 호출 0 | 사이렌 무한 ON → 소음 민원·경보 무시 학습 | 기동 직후·`_shutdown()`에서 무조건 OFF 1회 + `/health relay.startup_off`; 조달 릴레이의 자체 타임아웃 모드 확인 | S |
| P1-4 | critical 증거가 30일 뒤 지워질 수 있다 — 자동 pin은 "발송 성공"한 건만 | Ph4 P1-3: `alert_queue.py:95-128`(mark_sent에서만) — 채널 401인 지금은 pin 0 | 사고 후 30일 넘어 조사·소송 시 증거 없음; 산안법 3년 보존과 불일치 | 자동 pin 기준을 등급(critical/high) 발생으로; ack 된 이벤트 자동 pin; 인식 로그 3년 보존 검토 | S |
| P1-5 | 현장 안에서 들리는·보이는 경보가 실질적으로 없다 | Ph4 P1-5: 릴레이 `enabled:false` 기본 + 실물 미보유(mock), `/hub` 무음, 관제 PC 로컬 알림 0 | 위험구역에 들어간 작업자 본인과 관제석 담당자가 폰을 안 보면 모른다 | `/hub` 오디오·점멸·미확인 카운터; 릴레이 실물 조달·현장 시험을 파일럿 필수로 | S / M |
| P1-6 | 야간·저조도 유인 재현율 0회 측정, 무인 오탐 86.4→100% | Ph2 #4: `m2_night_person.md:15,67-69,110-116` | 야간 교대·옥외에서 미탐·오탐 모두 미지 | 절차서대로 유인 3조건 실측·조도계·야간 라벨링 | S |
| P1-7 | forklift 전역 모델 불용(mAP 8.83%) → 학원은 AGPL YOLO boda_ax(LOCO 도메인 21.4%)에 의존 | Ph2 #5: `vision.yaml:18`, `forklift_duel_2026-08-19.md:13,26`, `profile_intent.yaml:36-55` | 현장 종류가 바뀌면 지게차 검출 붕괴; 라이선스 리스크 | RF-DETR forklift 재학습(현장+LOCO), 도메인별 재현율 게이트 | L |
| P1-8 | 기준선-운영 불일치 재발 방지 장치 없음 + ppe 체크포인트 출처 불확실 | Ph2 #6: CLAUDE.md 규칙 9는 문서뿐, `vision.yaml:21-26`, `MANIFEST.md:19` | 대외 수치 신뢰 붕괴 재발; 배포 모델 mAP 근거 재현 불가 | 구성 해시(vision+tuning+manifest sha) 스탬프 + 불일치 시 CI 실패; best_total 로컬 재평가 1회 | S |
| P1-9 | 현장 노트북 4대: 램프 실측 권장 상한(4)에 딱 걸리고 N=4에서 검출 p95 675ms(3배 급증), 4h 소크·스로틀링·경보 지연 미측정 | Ph2 #7, Ph6 §9: `docs/academy_visit_day.md:718-741`(2026-08-22), `LAPTOP_SIZING_PILOT4.md:114-123` | 납품 후 발열 시 검출주기 초과·경보 지연 | 키트 4h 소크 통과 전 "4대 상시" 계약 금지; 미달 시 3대 또는 1.5fps 또는 §5 장비 | S(측정) |
| P1-10 | ~~개발기 드라이런 GPU util 83~89%·VRAM 4.0GB가 기준선과 모순~~ → **해소(2026-09-09 개발기 소크)**: 서버 종료 후에도 7,660MiB·util 19% 잔존 = 게임·브라우저 등 개발기의 다른 앱 몫. 서버 자체 ≈1.1~1.2GB(기준선 1.4GB 부합) → **배포기 GTX 1650 Ti 4GB 는 VRAM 관점에서 충분**(노트북 램프 실측 1.47GB 와도 일치) | §5-5, `audit/loadtest_20260908_2356_desktop_1h.md`, `docs/academy_visit_day.md:731` | 구매 전제 유지. 남는 결함은 "공용 개발기에서 GPU 지표를 단독 판정에 썼다"는 측정 위생 | 키트에 다른 GPU 프로세스 존재 시 경고 출력(코드 변경, 후속) | S |
| P1-11 | 입력 단절이 `stale_detect`로 오분류(P0-6의 뿌리) + 4대 동시 실 RTSP 대역폭·디코드 CPU·재연결 미실측 | Ph3 I-1·I-3: 수용량 실측은 실카메라 1대+파일 모의; `worker.py:672-677` "grab은 디코드 없음" 전제 미검증 | 권장 5대·한계 7대가 실 RTSP 4대에서 성립하는지 근거 없음 | PILOT4 §6 실카메라 4대 `--rtsp-list` 실측 + 캡처 스레드 CPU 분리 + 4대 운전 중 1대 차단 재현 | M(측정) |
| P1-12 | 카메라 `source` 무검증 → go2rtc·OpenCV에 임의 스킴/로컬 경로 전달(SSRF·명령 실행 가능성 미검증) | Ph5 S-1: `camera_registry.py:114-116`, `cameras.py:35-36,188-222`, `tapo.py:41-43`, `worker.py:77-87` | 토큰 보유자(또는 로컬 무토큰)가 로컬 파일 열람·내부망 스캔·go2rtc `exec:` 류 | 스킴 화이트리스트(rtsp/rtsps/정수/허용 디렉터리), `/cameras/{id}/test`는 사설 대역만 | S |
| P1-13 | 브라우저 경로로 들어온 증거 이미지는 비식별화 없이 원본 저장·서빙 | Ph5 S-2: `data_engine.py:52-67`, `zone.py:100-101`, `recognition.py:40-43`, `safety_core.py:619-629,660-663,767-770` | "증거는 비식별화된다"는 문서·헬스 지표와 불일치, 개인정보 노출 | `_save_frame` 진입부에서 `anonymize_faces` 경유(실패 시 `privacy_failed` 동일 적용) | S |
| P1-14 | 토큰 1개 = 전권, 역할·개별 폐기·만료 없음 | Ph5 S-3, Ph8 C-16: `auth_session.py:8-10`, `main.py:201-249` | 유출 1건이 관리자 전권; 열람자도 삭제·설정 가능 | 최소 2역할(admin/viewer) + 라우트별 요구 역할 + 세션 영속화 | M |
| P1-15 | TLS 코드 미지원(문서만), 세션 쿠키 `secure` 없음, WS 토큰 쿼리가 로그에 남음, 서비스 기본 0.0.0.0 | Ph5 S-4: `service_entry.py:95`, `main.py:155-156`, `ws_auth.py:33-35` | LAN에서 토큰·세션·증거 이미지 평문 | `VIGENT_SSL_CERT/KEY` 옵션 → `uvicorn.run(ssl_*)`, secure 쿠키, 역프록시 헤더 처리 | M |
| P1-16 | git 이력에 얼굴 식별 이미지·설비 사진·사고 영상 110객체 잔존(원격 push됨), 재작성 미완 | Ph5 S-5, Ph7 P1-2: `docs/NEXT_SESSIONS.md` 세션 1, `public_release_checklist.md:12-37` | 저장소 공유·이관 시 개인영상정보 유출 | 세션 1 절차(백업 번들 → filter-repo → force-push → 재클론) | M |
| P1-17 | 레지스트리·pin 파일 비원자적 쓰기 → 손상 시 카메라 0대가 healthy로 보임 | Ph6 OPS-04: `camera_registry.py:46-48`, `data_engine.py:95`, `_load` 실패 시 `{}`, `health_status.py:135` | 쓰기 중 정전 → 재부팅 후 복원 0대 → 아무 경고 없이 감시 중단 | tmp+`os.replace` 원자 쓰기 + `.bak` + "직전 N대→지금 0대"면 degraded+통보 | S |
| P1-18 | 백업·복구 절차 0건 | Ph6 OPS-05: `scripts/` backup/restore 0 | 디스크 고장·오삭제 시 카메라·구역·자격증명·경보 이력·pin 복구 불가 | `scripts/backup_state.py`(zip+sha256) + 주기 편입 + 복구 런북 | M |
| P1-19 | CUDA→CPU 조용한 폴백 + `/health`에 추론 장치 미노출 | Ph6 OPS-06: `device.py:33-39`, `/health` device 필드 0 | 드라이버 교체·휠 재설치 후 CPU로 돌며 4대 부하 2.2배 → stale_detect 연쇄, 원인은 로그에서만 | `/health.device` + `VIGENT_REQUIRE_CUDA=1`(없으면 기동 거부·이벤트 1000) | S |
| P1-20 | Windows Update 자동 재부팅·드라이버 교체 통제 없음 | Ph6 OPS-07 | 야간 재부팅 공백 + 드라이버 교체 시 P1-19 경로 | 그룹정책 스크립트(드라이버 제외·활성 시간·재시작 창) + 재부팅 후 상태 자동 통보 | S |
| P1-21 | 테스트 스위트가 운영 `data/` 4파일을 바꾸고 실 `go2rtc.exe`를 기동·재기동한다 | Ph7 P1-1: `test_alert_queue.py`가 `isolate_alerts()` 미사용 → 운영 `pinned.json`; `TestClient(main.app)` → `main.py:479-482` → `cameras.py:337 ensure_go2rtc()` 가드 없음 → `bin/go2rtc.exe` 기동, 기존 인스턴스 종료·런타임 yaml 초기화(`:342-349,363-366`). 이 세션의 이전 "전후 변경 0" 측정은 고아 go2rtc(03:35 기동, 포트 점유)가 "재사용" 경로를 타게 만들어 쓰기를 가린 상태였다 — 해당 고아도 테스트가 띄운 것으로 추정(확인 필요) | 운영 PC에서 테스트 실행 시 라이브 확대뷰 끊김·등록 초기화·pin 오염 | `test_alert_queue`에 `isolate_alerts()`; `ensure_go2rtc()`에 `VIGENT_GO2RTC_AUTOSTART=0` 가드 + `_isolate`에서 강제; CI에 `tree_hash compare` 게이트 | S |
| P1-22 | 슬롯 추론·로드 실패 자동 복구 없음(로드 실패는 재시작 필요), 디스크 풀 사전 경보 없음(24h 스윕 때만), `alert_queue.db` 손상 시 기동 실패 루프 | Ph1 B-04·B-05·B-06: `guard.py:900-905,930-961`, `retention.py:102,285-290`, `alert_queue.py:349` | GPU 리셋 후 person 슬롯 사망 무통보; 증거 없는 경보; 손상 DB 60s 재시작 루프 | slot_degraded N분 → `empty_cache`+재로드 1회, 실패 시 자진 종료; 1~5분 주기 `disk_usage` 검사; `_db()` 손상 파일 격리+WAL | S~M |
| P1-23 | 시간 동기(NTP) 절차 없음, 이벤트 시각이 캡처가 아닌 기록 시각(카메라 지연 ~1.4s 미반영), naive datetime 3곳 | Ph1 B-07, Ph3 I-8, Ph6 OPS-19, Ph8 C-22: `data_engine.py:164-169`, `worker.py:719,1222` | 사고 조사 시 NVR·증거·큐 시각 불일치 | SITE_CHECKLIST N-10 + `/health.clock_offset` + 이벤트에 `frame_ts`·`detect_latency_ms` 기록 | S |
| P1-24 | 조치 이력 부재(ack만, note 미전달)·정기(월간·반기) 보고서 자동 생성·PDF 없음·개인정보 운영 문서(안내판·고지문·운영관리방침·노사협의) 0건·AI 기본법 대응 미착수·계약 표준 조항 미확정·모자이크 실패 원본 저장(D4) 법무 미검토·evaluator "KOSHA 인증 90%" 문구 근거 미확인 | Ph8 C-2~C-8: `audit_store.py:21-23`, `safety_core.py:296`, `dashboard.py:1-6`, `PRIVACY_POLICY_DRAFT.md` §9-10 `[ ]`, `evaluator.py:8,172,185` | 산안법·중처법·개인정보보호법 §25·AI 기본법 관점에서 고객이 법 위반 상태로 파일럿을 시작할 수 있음; 근거 없는 인증 문구는 규칙 7 위반 | 양식 4종+안건서 초안 → 법무; 조치 티켓 필드; 월간 PDF 스케줄러; "AI 운용 고지" 문구; 인증 문구 삭제 | S~M(초안) / L(법무) |

### P2 — 상용 경쟁 제품 대비 기능·성능 열위(대표 항목, 전체는 Phase 문서)

| # | 제목 | 근거 | 공수 |
|---|---|---|---|
| P2-1 | 알람 생명주기가 "진입 1회 통보"뿐 — 해제·ack(키 결함)·에스컬레이션·교대 수신자·체류 시간 규칙 없음 | Ph1 C-01, Ph4 P2-6, Ph8 C-12 | M~L |
| P2-2 | 카메라별 설정이 구역·fps·무동작 3개뿐, 임계 변경은 재시작 필요, 시간대 규칙 없음, PPE 필수 항목 출처가 둘(워커 vs 브라우저) | Ph1 C-02·C-04: `camera_registry.py:258`, `tuning.py:415-419`, `guard.py:426-436` vs `ppe_check.py:186-211` | M |
| P2-3 | PLC(Modbus/OPC-UA/EtherNet-IP) 연동 전무, 릴레이는 HTTP 1채널, 문서는 "Modbus TCP"처럼 읽힘 | Ph4 §2, Ph8 C-18: `relay.py:7,70-82` | M |
| P2-4 | 이벤트 전후 클립(pre/post-roll) 없음, 텔레그램에 증거 사진 미첨부, 이력 필터·CSV/PDF 내보내기 없음(docstring은 "CSV"), 관리자 KPI(착용률·시간대·카메라별) 없음 | Ph4 P2-4·7·8·9 | S~M |
| P2-5 | 오탐 표시→통계→재학습 루프 없음(`/recognition/note`는 빈 스텁), VLM 판정 미저장, 재학습 코드는 사장된 office/YOLO용, 학습이 운영 데이터를 읽는 코드 0건 | Ph2 #10·§9, Ph4 P2-5, Ph8 C-15: `routers/recognition.py:58-60` | L |
| P2-6 | 전 카메라 단일 `DETECT_LOCK` 직렬화 + 배치 없음 + fp32, TensorRT/fp16 0건, ONNX-CPU 경로는 `.onnx` 미등재로 재현 불가·무경고 torch 폴백 | Ph2 #9·#10b: `worker.py:1007`, `rfdetr_adapter.py:199` | L / S |
| P2-7 | 카메라 tamper(가림·초점·과노출·이동) 감지 전무, ONVIF 자동 검색 없음, H.265가 현 cv2 4.13(FFmpeg 4.4)에서 미재검증, 실행 중 source/fps 변경이 조용히 무시 | Ph3 I-5·I-6·I-7: `cameras.py:95-96` | S~M |
| P2-8 | 안전 판정 핵심 4모듈(hazard_rules·ppe_check·incident·safety_brain) 커버리지 0%, 영상 기반 파이프라인 회귀 세트 없음, 광범위 except 223곳(삼킴 54·무로그 124) 중 통보 채널 실패 3종이 무로그, 비동기 핸들러의 블로킹 `urlopen`(최대 13s) | Ph7 P2-1~P2-4: `dispatcher.py:169,187,203`, `routers/tapo.py:104-120` | M / L / M / S |
| P2-9 | Docker 빌드 불가(`Dockerfile:24` constraints 미복사·`:38` 루트 `fetch_weights.py` 부재), systemd가 부재 런처를 가리킴, 폐쇄망 설치 절차 불완전(pip 휠·NSSM·vendor JS), OTA·롤백·배포 단위 없음, 중앙 관제 없음, `/health.status==='ok'` 비교 버그로 허브가 항상 DEGRADED·`/safety-local` 항상 브라우저 폴백 | Ph6 OPS-09~13·16: `hub.py:78`, `index_local.html:472,535` | S~M / L |
| P2-10 | 감사로그(설정 변경·열람) 없음, `GET /notify/config`가 webhook_url 평문 반환, 비밀 파일 OS 권한 미설정, CDN SRI 없음·3종 버전 미고정, 본문 크기·rate limit 없음, 반출 통제·워터마크 없음 | Ph5 S-6~S-13 | S~M |
| P2-11 | 안전대(하네스)·장갑 모델 클래스 없음(VLM 보조, Windows에서 로컬 VLM 불가), 낙상 제거, 밀폐공간 출입 관리 없음, 열화상/야간 미검증, 모바일 앱·다국어·중앙 관제·OTA·RBAC 없음 | Ph8 §4-2 | L |

### P3 — 코드 품질·유지보수성(대표)

- `vision.yaml:65-74` 주석이 실제와 반대(ByteTrack "미구현", 포즈 "yolov8n-pose") · 매니페스트 `verified_note` "10종"(실제 14) · `config/models_inventory.md` RF-DETR 0줄 (Ph2 #14·#16)
- 문서 낡음: `CLAUDE.md` "55 tests"/"302줄"/`python3`/`~/Desktop`(2026-09-03 지적 후 미정정), `deploy/windows/README.md:15` "5초 재시작"(실제 60s), `README.md:37` 리터럴 CR, `docs/STABILITY.md` 재연결 30s(코드 5s)·"기본 sync", `PRIVACY_POLICY_DRAFT.md`가 구현된 모자이크·자동 파기를 "미구현"으로 서술(실제보다 나쁘게), `deploy/DEPLOYMENT.md` 구 CLI·docker 안내 (Ph1 D-03, Ph3 I-14, Ph4 P3-5, Ph5 S-16, Ph6 OPS-17, Ph7 P2-8)
- `.gitignore:65 pilot_*.md`가 대소문자 무시로 `docs/PILOT_DECISIONS.md`를 삼킴(대표 결정 기록이 git에 없음) (Ph7 P2-6)
- `GET /alerts/status` 항상 빈 스텁, `config/zones.json` 어떤 코드도 읽지 않음, 서빙되지 않는 `index_vigent.html`이 `/dispatch/relay` 호출, `rig_monitor`/`rig_replay` 죽은 섬, `realtime_core.js` 4,335줄 단일 파일, `print` 34곳, `/tmp` 경로 3곳(Windows), BLE001 ignore, mypy 19/88, 도구 핀 드리프트(CI ruff 0.12/로컬 0.16), CI가 main만 감시 (Ph1 D-04·05, Ph4 P3-2·3, Ph7 P3-1~14)
- `/hub` 미전송 배너가 누적 dead(76)를 그려 영구 붉은 표시, `go2rtc.log` 세션 중 무제한 증가(99% EOF 스팸), NSSM 회전본 무제한·앱 로그 이중 기록, 종료 유예 1.5s×3 vs `_shutdown` 5s+ (Ph4 P3-1, Ph3 I-11, Ph6 OPS-14·18)

---

## 3. 경쟁 제품 대비 격차표 (Phase 8 §4, 제품 페이지에 명시된 것만 기준)

기준선 출처: Intenseye Core AI(PPE 9종·50+ 시나리오·스코어카드·스피커/센서 연동) · Protex AI(온프렘 익명화·PLC 연동·수백 현장) · Voxel(속도·지속학습) · Everguard(CV+웨어러블) · SAIGE(안전대·Depth 3D 거리) · 영신(쓰러짐·통계 리포트) · 경우시스테크(지게차 자동제동). 경쟁사 fps·정확도는 페이지에 없어 비교하지 않았다.

| # | 항목 | VIGENT | 비고(근거는 08-compliance-gap.md §4-2) |
|---|---|---|---|
| 1 | 다중 카메라 동시 처리·실측 FPS | **있음** | 데스크톱 한계 7대·권장 5대·카메라당 2fps. 노트북은 램프 1회(한계 6·권장 4) |
| 2 | 보호구 세부(안전모/조끼/안전대/장갑/마스크) | **부분** | 모델 직접 3종(안전모·조끼·마스크). 장갑·보안경·안전대는 VLM 보조(Windows 로컬 VLM 불가), 하네스 클래스 없음 |
| 3 | 위험구역 편집 UI | **있음** | 허브 폴리곤 편집·카메라별 저장 |
| 4 | 차량-사람 근접·거리 추정 | **부분** | 단안 박스 폭 기준자, 캘리브레이션 없음, 지게차 모델 기본 비활성 |
| 5 | 넘어짐/쓰러짐 | **없음(의도적 제거)** | 무동작 45s 규칙으로 부분 대체 |
| 6 | 화재/연기 | **있음** | D-Fire mAP@50 80.13%(in-domain), 현장 재검증 대기 |
| 7 | 고정 자세/움직임 없음 | **있음** | `immobility` 45s, 카메라별 override |
| 8 | 밀폐공간 출입 관리 | **없음** | 지식·체크리스트 층만 |
| 9 | 트래킹 기반 체류시간 | **부분** | 진입 1s 디바운스만, 체류 집계·임계·리포트 없음 |
| 10 | 야간/열화상 | **없음(미검증)** | 야간 유인 재현율 0회 |
| 11 | 얼굴 비식별화 | **있음(조건부)** | 서버 경로만, 브라우저 경로·실패 시 원본 |
| 12 | PLC/경광등 연동 | **부분** | HTTP 릴레이 1채널(mock 검증), Modbus 없음 |
| 13 | 모바일 앱 | **없음** | 텔레그램 봇 |
| 14 | 다국어 | **없음** | `lang="ko"` 고정 |
| 15 | 리포트 자동 생성 | **부분** | 위험성평가서 on-demand, 주기·PDF·발송 없음 |
| 16 | 중앙 관제(다중 현장) | **없음** | `central_url` 저장만 |
| 17 | OTA | **없음** | 수동 git pull·재시작 |
| 18 | 오탐 피드백 학습 | **없음** | 스텁 엔드포인트 |
| 19 | 감사 로그 | **부분** | 승인 이력 1종 + 삭제 감사 |
| 20 | 역할 기반 권한 | **없음** | 단일 토큰 |
| 21 | 오프라인 설치 | **부분** | 가중치·go2rtc 매니페스트 OK, pip 휠·NSSM·CDN 화면 수동 |
| 22 | 인체공학(REBA) | **있음** | 보조 진단 |
| 23 | 인원 밀집·단독작업 | **있음** | crowd·lone_worker |
| 24 | 행동 안전(VLM) | **부분** | 클라우드 키 있을 때만 |
| 25 | 법령 근거 자동 인용 | **있음(차별점)** | RAG + 화이트리스트 |
| 26 | 재해 원인분석 보조 | **있음(보조)** | 저장·조치 연결 없음 |

**집계: 있음 9 · 부분 8 · 없음 9.** 아키텍처·알람·보안 관점 격차(감시자 감시, 카메라 오프라인 알림, 알람 생명주기, 물리 출력 우선순위, 전송 암호화, RBAC·SSO·감사로그, 채널 밀도·TensorRT, BEV 거리, 재현율 SLA, 현장 적응 루프)는 각 Phase §6/§7/§11 표 참조.

---

## 4. 빠져 있는 것 — 코드에 흔적조차 없는 기능·절차·문서

**"있는 줄 알았는데 없는 것"(문서·주석이 있다고 말하거나 그렇게 읽히는데 코드에 없음)**
- **Docker 배포**: `Dockerfile`은 빌드 자체가 안 된다(`:24` constraints 미복사, `:38` 루트 `fetch_weights.py` 부재, CUDA 없음, compose 없음). `deploy/DEPLOYMENT.md:31-33`는 "docker build 자동 정리"라고 안내.
- **Linux systemd**: `vigent-edge.service:24`가 존재하지 않는 `bin/vigent-edge.command`를 가리킨다.
- **TLS**: `docs/TLS_DEPLOYMENT.md`만 있고 `service_entry.py:95`는 평문 `uvicorn.run`.
- **Modbus TCP**: `relay.py:7`·`SITE_CHECKLIST.md:171`이 "HTTP 또는 Modbus TCP"라 쓰지만 구현·라이브러리 0.
- **현장별 수신자**: `notify.example.yaml`의 `sites:` 구조는 dispatcher가 읽지 않는 스키마(복사하면 채널 미설정으로 기동).
- **CSV 내보내기**: `routers/recognition.py:7` docstring은 "CSV", 구현은 JSONL.
- **ByteTrack·RTMPose 상태**: `vision.yaml:65-74` 주석은 "미구현·미사용"이라 하나 실제 운영 중(반대 방향 낡음).
- **오탐 메모**: `/recognition/note`는 `return {"ok": True}` 스텁. `GET /alerts/status`는 항상 빈 목록.
- **테스트 격리 "변경 0"**: `FINAL_SUMMARY.md:57`의 주장과 달리 실 go2rtc 기동·pin 오염(Ph7 §2.3).
- **"KOSHA 스마트 안전장치 인증 기준 90%"**: `evaluator.py:8,172,185` — 제도·기준의 존재를 확인하지 못함.
- **재시작 5초**: `deploy/windows/README.md:15` — 실제 60s.

**흔적 자체가 없는 것**
- 증빙: 해시체인·전자서명·타임스탬프(TSA)·WORM, 증거·기록 열람 로그, 조치 티켓(상태·담당·기한·완료), 반기 점검 보고 서식·월간 리포트 스케줄·PDF·이메일 발송, 산업재해조사표·아차사고 연계
- 개인정보·규제: 안내판·고지문·운영관리방침·열람/삭제 요청 처리·노사협의 안건서, "AI 운용 사실 고지" 문구·위험관리방안·5년 보관 정책, 계약 조항(기능안전 면책·설비연동 요구사항·데이터 소유/파기), 취약점 공개·패치 절차·SBOM·침해사고 대응
- 운영: 전원·절전·덮개·UPS·BIOS AC 복구·NTP·Windows Update 절차, 백업/복구 절차·스크립트, OTA·롤백·배포 단위, 외부 heartbeat/워치독(Windows), 운영자(현장 관리자용) 매뉴얼, 카메라 설치 정량 기준(높이·각도·거리)
- 기능: 카메라 tamper/초점/노출 감지, ONVIF 검색, H.265 HW 디코드, pre/post-roll 클립, 카메라 오프라인 통보, health 전이 통보, 알람 ack/clear/에스컬레이션/교대 수신자, 체류시간·밀폐공간 in/out, 차량 속도·역주행, 호모그래피/BEV, TensorRT/fp16/배치, 오탐 피드백→재학습, 클래스별 검출률 시계열·`/metrics`, RBAC, 모바일 앱·SMS·카카오·푸시, 다국어, 중앙 관제, 하네스·장갑 모델 클래스, 야간·역광·우천·분진·렌즈오염 테스트 데이터, 2fps 정답지, person 재현율 목표치

---

## 5. 하드웨어 권장안

### 5-0. 기기 역할(고정)
- **배포기 = 현장 노트북** i7-10750H(6C/12T) · GTX 1650 Ti 4GB · DDR4 16GB · SSD 1TB · Win10 Pro · torch cu126(`md/DEPLOYMENT.md:22`, 2026-08-20 재설치 실증). 실제 설치 대상.
- **개발기 = 이 데스크톱** Ryzen 9 9900X · RTX 5070 Ti 16GB · 64GB · Win11 Home. 현장에 가지 않는다. 저장소의 수용량 실측(한계 7·권장 5, 2026-08-18)·병목 규명(E1)·VRAM(V1)·오늘 소크는 전부 이 기계 값이며 **현장 판정에 쓰지 않는다**(§5-5).

### 5-1. 배포기(노트북)의 성능 근거 — 램프 1회가 전부다
| 항목 | 값 | 근거 |
|---|---|---|
| 램프 실측(유일) | N=1 219ms · 2 270 · 3 **220** · 4 **675ms**(주기 0.6s) · 5 868 · 6 **972(한계)** · 7 1,177(탈락, 기준 1,000ms) — 검출 p95 | `docs/academy_visit_day.md:718-729`(2026-08-22, 학원 프로파일, 파일 모의) |
| 병목 | **CPU** — 한계 시 CPU 94.9%, GPU util 37~40%, VRAM 35.9% ≈ **1.47GB** | `:731-733` |
| 판정 | **한계 6 · 권장 4**. "권장 4는 급증 직후라 여유가 넉넉하지 않다 — 상시 4대면 실측을 한 번 더" | `:735-737` |
| 소크 | 파일 카메라 **2대** 3h PASS(RSS −52MB/h, unhealthy 0) — 4대 소크 없음 | `audit/soak_after_fixes_2026-08-26.md:6-19` |
| 미측정 | 4h 지속(3h 후 클럭 유지)·실카메라 4대 RTSP·경보 지연·10항목 판정(`docs/LAPTOP_SIZING_PILOT4.md` §7 전부 "미측정") · 1차 램프(08-21)는 유령 카메라로 무효 | `LAPTOP_SIZING_PILOT4.md:114-123`, `audit/capacity_probe_invalid_2026-08-21.md` |
| VRAM | 4GB 로 충분 — 노트북 실측 1.47GB, 서버 몫 1.2~1.4GB 확정(개발기에서 본 4.0GB 신호는 다른 앱, §5-5) | `docs/academy_visit_day.md:731`, `audit/loadtest_20260908_2356_desktop_1h.md` |

→ 노트북은 **4대에서 CPU 상한에 걸린 상태**다. 하드웨어를 바꾸기 전에 코드로 CPU 부하를 줄일 수 있는지(§5-3)를 노트북에서 재는 것이 순서다.

### 5-2. 배포기(노트북)를 현장 서버로 쓸 때의 위험(상세 표는 Phase 6 §9-1)
| # | 위험 | 상태 | 조치 |
|---|---|---|---|
| H1 | 덮개 닫힘·절전 → 서비스 정지 | 절차 0건, 노트북 `powercfg` 값 미확인 | `set_power_plan.ps1` + N-6(P0-8) |
| H2 | USB/NIC/PCIe 절전 | 미확인 | 동일 스크립트 |
| H3 | 정전 후 자동 부팅 불가 가능 | 기종별 확인 필요 | BIOS 확인·UPS·외부 heartbeat(P0-9) |
| H4 | 배터리 상시 만충·팽창 | 미확인 | 충전 상한 설정·월 1회 `batteryreport` |
| H5 | 24h 발열·스로틀링(6C/12T 모바일, 4대에서 CPU 94.9% 근접) | **미측정** | 키트 4h 소크(§5-3 절차) — 3h 후 클럭 ≥ 초기 80%·GPU < 87°C |
| H6 | SSD 쓰기 수명 | 병목 아님(추정 ≈20MB/일, 극단 582MB/일) | 월 1회 Wear 기록·여유 <20% 알림 |
| H7 | 24h 내구(어댑터·팬·힌지) | 미측정 | 예비 어댑터·소크 |
| H8 | 물리 보안(도난) | BitLocker 적용됨 | 켄싱턴 락·잠금 캐비닛·외부 heartbeat |
| H9 | Windows Update 자동 재부팅·드라이버 교체 → cu126 torch 불일치 시 조용한 CPU 폴백 | 절차 0건 | 그룹정책(Pro 가능)·`/health.device`(P1-19) |
| H10 | 네트워크(Wi-Fi 사용 여부·4대 대역폭) | 미측정 | 유선 고정·키트 `net_rx_mbps` |

### 5-3. 하드웨어 교체 전 소프트웨어 부하 감축 선택지(코드 기준, 노트북에서만 유효)

전제: 노트북 병목은 CPU(카메라당 추론 전후처리)이며 GPU 는 40% 이하로 놀고 있다(§5-1). 개발기 실측 단가: 검출 CPU 는 fps 에 정비례(`v3_fps_report.md:11-20`), 검출 1.07코어(슬롯 무관)+0.106×슬롯+검출 밖 0.65코어(`v1_slot_config_report.md:45-60`), ORT 세션 튜닝으로 2.10→1.55코어(이미 적용). **아래 예상 효과는 개발기 단가에서 유도한 추정이며 노트북 값이 아니다 — 노트북 실측으로만 확정한다.**

| # | 선택지 | 현재 코드 상태(파일:줄) | 예상 효과(추정, 노트북 실측 필요) | 구현 난이도 | 정확도 영향(규칙 6·9) |
|---|---|---|---|---|---|
| S1 | **카메라 fps 2 → 1.5/1** | 카메라별 `fps` 등록값(`routers/cameras.py:82-96`), 풀세트 캡 `tuning.yaml:182 worker.fullset_fps: 2`, 루프 간격 `worker.py:1145,1296` | 검출 CPU 정비례 감소(2.0→1.0fps 에서 1.38→0.71코어/카메라, `v3_fps_report.md`) → 4대에서 약 30~50% 절감. **코드 변경 0**(설정만) | **S**(설정) | 통과형 침입·근접 디바운스(enter_s 1.0s)가 프레임 기준이라 판정 지연 ↑ — P0-4 실측과 함께 결정. 히스테리시스 프레임(`guard.py:290`)은 시간 기준으로 재조정 필요 |
| S2 | **포즈(rtmlib RTMPose, onnxruntime CPU) 끄기 또는 pose_fps 낮추기** | 포즈 스레드 상시(`worker.py:946-975`), `tuning.yaml:181 worker.pose_fps: 2`, 근골격 규칙은 **통보 없음**(`worker.py:492`, Ph1 §1-1 "통보 없음") — 끄는 공식 키는 없고 `pose_fps` 하한 0.2(`worker.py:98`) | CPU 전용 추론 1개(YOLOX-m + RTMPose-m) 제거 — 사람이 있을 때 카메라당 상시 부하. 절감량 미측정(포즈 단독 CPU 분리 측정 없음) | **S**(`pose_fps: 0.2`로 사실상 최소화) / **S~M**(off 키 추가는 코드) | 근골격(ergonomic_risk) 지표만 소실 — 5대 검출 기능과 무관 |
| S3 | **불필요 슬롯 제외** — fire_smoke 는 학원 프로파일에서 이미 off, forklift 기본 off | `tuning.yaml:123-124 include_*`, `worker.py:118-140`, 학원 `deploy/academy/profile_intent.yaml` | 슬롯당 0.106코어/카메라(개발기) — 작음 | S(설정) | 해당 위험 감지 소실 — 현장 요구에 따라 |
| S4 | **추론 입력 해상도 축소(384 → 320 등)** | `tuning.yaml:88 detect.imgsz: 384`(RF-DETR 은 로드 시 컴파일 고정, 호출별 변경 불가 `detectors/rfdetr_adapter.py:167-171`), `guard.py:402` | 개발기 실측은 960/640/1280 **모두 dev 지표 악화**(`v1_field_baseline_report.md:158`) — 384 미만은 **미측정**. 전처리·모델 연산 감소 기대치 미상 | S(설정) | 원거리 재현율(이미 0~8%)이 더 떨어질 가능성 큼 — **재현율 재측정 없이는 금지** |
| S5 | **ONNX Runtime FP32 CPU 경로(`onnx-cpu`)** | opt-in `tuning.yaml:80 detect.backend: torch`, `_OnnxRfdetrModel` CPUExecutionProvider 고정(`rfdetr_adapter.py:16-23,118-121`), `.onnx` 4종 **매니페스트 미등재**·없으면 무경고 torch 폴백(`:199,206-208`), export 스크립트 없음(`MANIFEST.md:74-102` 수동) | 개발기 실측: 지연 2.2배 빠르나 **CPU 1.7배 더 씀**(`v2_onnx_report.md:13-19`) → CPU 병목 노트북에는 **역효과**. GPU 를 쓰는 CUDA EP 는 코드에 없음 | M(CUDA EP 추가) | 패리티 테스트 있음(`tests/test_rfdetr_onnx_parity.py`) |
| S6 | **TensorRT / torch FP16(half)** | 0건(`grep tensorrt|half|fp16` vigent-core 0; V2 는 fp16 을 "CPU EP 에서 이득 없음"으로 부결 `v2_onnx_report.md:100`), INT8 은 CPU 에서 fp32 보다 느리고 정확도 −1.6~2.4%p 로 기각(`onnx_cpu_bench.md:46,56-63`) | GPU 추론 시간 감소 → `DETECT_LOCK` 점유 감소. 그러나 노트북 병목은 CPU 전후처리라 **직접 효과 작음**(GPU util 40%) | L(TensorRT 변환·JetPack/TRT 설치·정확도 회귀 게이트) / M(torch `.half()` 만) | FP16 정확도 Δ 미측정 — 회귀 게이트 필수 |
| S7 | **멀티스트림 배치 추론** | 카메라별 워커 스레드 → `DETECT_LOCK`(`worker.py:1007`, `app_state.py:35`) 안에서 슬롯별 **단일 프레임** `unsqueeze(0)`(`rfdetr_adapter.py:151`, `guard.py:970-976`) | 4프레임 배치는 GPU 커널 호출 4→1 로 GPU 시간 절감. CPU 전후처리는 프레임 수에 비례해 **남는다** → 노트북 CPU 병목엔 부분 효과(추정) | L(워커 구조 변경: 프레임 모아 배치, 지연 ↑ 최대 0.5s) | 결과 동등해야 함 — 회귀 게이트 |
| S8 | **하드웨어 디코딩(NVDEC/D3D11)** | 미사용(`worker.py` `CAP_PROP_HW_ACCELERATION` grep 0), 소프트웨어 FFmpeg 디코드. 문서는 "NVDEC 에 돈 쓰지 말 것 — 디코드 0.4~1.2ms/프레임"(`docs/INFRA_REQUIREMENTS.md:47`, E1 §1 H1 기각) | E1 근거는 **파일 소스 2fps 순차 읽기** 측정. thread 모드 캡처 스레드는 실 RTSP 15~30fps 를 **전부 `grab()`** 하며(`worker.py:679-687`) 그 디코드 CPU 는 분리 측정된 적이 없다(Ph3 I-3). 실카메라 4대·1080p 면 카메라당 수십~수백 ms/s 의 디코드 CPU 가 붙을 수 있음(추측) → 카메라 서브스트림(720p/저fps) 사용이 NVDEC 보다 먼저 | S(서브스트림 URL 등록, 코드 0) / M(cv2 HW 가속 플래그 — cv2 4.13 휠의 D3D11/CUVID 지원 여부 확인 필요) | 서브스트림은 해상도 저하 → 원거리 재현율 재측정 |
| S9 | **불필요 후처리 제거** — 증거 JPEG 모자이크·인코딩이 워커 스레드에서 동기(`worker.py:1113-1118,182-201`), 브라우저 시연 페이지 동시 사용 시 −1대(`FINAL_SUMMARY.md` §5), `/hub` 썸네일 1.3s 폴링(`index_hub.html:636`) | 증거 쿨다운 30s 라 평균 부하는 작음; 시연 페이지·썸네일 폴링을 현장에서 닫는 것이 효과 큼(개발기 실측 "여유 −1대") | S(운영 지침) / M(증거 인코딩 별도 스레드) | 없음 |
| S10 | **ORT 세션 스핀·스레드** | 이미 적용(`ort_tune.py`, intra_op 4·spin off, 카메라당 2.10→1.55코어) | 추가 여지: `intra_op_threads` 를 노트북 6코어에 맞춰 2~3 으로 재튜닝(측정 필요) | S(설정) | 없음 |

권장 실험 순서(노트북): **S1(fps 1.5) + S2(pose_fps 0.2) + S9(시연·썸네일 off)** 를 먼저(전부 설정·운영 지침, 코드 0) → 4대 4h 소크 재측정 → 통과 시 S8 서브스트림·S10 재튜닝 → 그래도 미달이면 S7/S6(구조 변경, 회귀 게이트 선행) 또는 §5-4.

**노트북 실행용 벤치마크 절차**(전부 저장소 도구, 코드 변경 없음)
```powershell
# 0) 전제: 노트북에 main(ee4557d 이후) 배포, 서비스 Running, 모의 영상 VIGENT_DATA_DIR\runs\rfdetr\accident\*.mp4 복사, 다른 GPU/CPU 앱 종료
# 1) 기준선(현행 설정) — 4대 4h, 10분 창, 과부하 5·6대 각 20분
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_base
# 2) S1+S2+S9: config\tuning.yaml 에서 worker.pose_fps: 0.2, 카메라 등록 fps 1.5(키트 --fps 1.5), 시연 페이지·허브 닫음 → 서비스 재시작 → 같은 명령
python scripts\pilot_load_test.py --cams 4 --fps 1.5 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_s1s2
# 3) 단계별 단가(램프): capacity_probe 로 N=1..7 재측정(선언 기준 그대로) — 비교 대상은 2026-08-22 표
python scripts\capacity_probe.py --max-n 7 --hold 180
# 4) 실카메라가 있으면 --rtsp-list 로 1)·2) 반복(디코드 CPU 분리: 키트 net_rx_mbps + 캡처 스레드 CPU 는 후속 코드 변경 필요)
# 5) 정확도 회귀: S4·S8 처럼 입력이 바뀌면 v1 기준선 재측정(benchmarks/v1_field_baseline_report.md 절차, 규칙 9)
```
판정 기준은 `scripts/pilot_load_test.py` PASS(=`docs/LAPTOP_SIZING_PILOT4.md` §1) 그대로 — 측정 후 바꾸지 않는다.

### 5-4. 최적화 후에도 미달일 때의 대안
| 대안 | 내용 | 조건·근거 |
|---|---|---|
| A. 카메라 3대로 축소 | 노트북 램프에서 N=3 은 검출 p95 220ms(급증 이전) | 4대째 카메라의 구역을 화각 조정으로 흡수 가능한지 현장 판단. 가장 싸고 즉시 |
| B. fps 1.0 고정 4대 | 검출 CPU 절반(개발기 단가) | 통과형 침입·근접 판정 지연 실측(P0-4) 통과가 조건 |
| C. 노트북 교체 사양 | 병목이 CPU 이므로 **CPU 코어·클럭**만 올린다: 데스크톱급 8코어 이상 모바일/데스크톱 CPU(PassMark 환산코어 ≥ 8.9 for 4대, ≥ 11.1 for 5대 여유 — `edgebox_purchase_guide.md` 공식으로 후보 조회) + GPU 는 **4~8GB 면 충분**(서버 몫 1.2~1.4GB) + Windows **Pro** + 24h 발열 설계(얇은 기기 지양) + SSD 1TB + 유선 이더넷 | 후보 CPU PassMark 값은 저장소에 없음 — 지어내지 않고 조회 후 산정. 값싼 노트북은 대부분 Home 이라 제외 |
| D. 데스크톱급 소형 워크스테이션/미니PC | 개발기(9900X)와 같은 계열이면 한계 7·권장 5 실측과 같은 여유 | 개발기를 현장에 보내는 것은 대표 결정으로 제외됨 |

### 5-5. 개발·테스트 환경(이 데스크톱) — 현장 성능 판정에 사용 불가
개발기(이 데스크톱)의 실측 사양: MSI MAG B850M MORTAR WIFI · 섀시 코드 3(Desktop) · 배터리 없음 · Ryzen 9 9900X · RTX 5070 Ti 16,303MiB · DDR5 64GB · C: SATA SSD 240GB / D: SATA HDD 1TB(저장소 위치) · Windows 11 Home · 이더넷 100Mbps.

- 역할: 코드 검토·테스트·게이트·부하 키트 동작 검증. 저장소의 수용량(한계 7·권장 5, 2026-08-18)·E1 병목·V1 VRAM·V2 CPU 전용 단가는 모두 이 기계 값이며, 노트북 판정에는 **환산 가정(카메라당 코어 단가)** 을 거쳐서만 참고한다.
- 2026-09-08~09 개발기 소크(4대 파일, 1h, `audit/loadtest_20260908_2356_desktop_1h.md`): 시스템 CPU 45~61%·서버 6.1~7.4코어·검출 age p95 ≤0.5s·카메라 degraded 0·GPU 46~63°C·RSS 3.3→1.2GB. **현장 판정에 쓰지 않는다**(다른 기계, 1h<4h 무효). 유일한 소득은 **VRAM 신호의 원인 확정**: 서버 종료 후에도 `nvidia-smi` 7,660MiB·util 19% 잔존, 게임·브라우저 등 30여 개 앱이 GPU 를 점유 → 서버 몫 ≈1.1~1.2GB(기준선 1.4GB 부합) → 노트북 4GB 충분.
- 개발기 위생(현장 무관, 측정 신뢰를 위한 항목): ① GPU 지표 측정은 다른 앱을 끈 상태에서(공용 게임·브라우저) ② 저장소·`data/`·`logs/` 가 SATA HDD 위라 I/O 지표는 현장 SSD 와 다름 ③ 테스트·부하시험이 운영 `data/` 를 오염(P1-21) — 별도 클론/데이터 디렉터리로 분리 ④ Windows Home 이라 BitLocker 검증 불가(N-2 는 노트북에서만 검증됨).

### 5-6. 최종 추천
1. **배포기는 현 노트북을 유지하되 "4대 상시"는 아직 확정하지 않는다.** 램프 1회(2026-08-22)가 유일한 근거이고 권장 상한에 걸려 있다.
2. 노트북에서 §5-3 절차로 **기준선 4h 소크 → S1+S2+S9 적용 4h 소크**를 잰다. 두 결과가 `docs/LAPTOP_SIZING_PILOT4.md` §1 기준을 통과하면 4대 운용 확정(구매 없음).
3. 미달이면 §5-4 A(3대) 또는 B(fps 1.0)를 먼저 검토하고, 그래도 안 되면 C(CPU 상향 노트북, Pro·발열 설계·GPU 4~8GB)로 간다.
4. 어느 경우든 설치 전 조건: 전원·덮개·절전 스크립트(P0-8), UPS·BIOS 자동 부팅·외부 heartbeat(P0-9), 유선 이더넷, BitLocker 유지, 예비 어댑터, 물리 잠금.

## 6. 로드맵

의존 관계는 "→"로 표시. 공수는 Claude Code 세션 단위 추정(S 1세션 이내, M 2~3세션, L 4세션+ 또는 외부 선행조건).

### (a) 현장 설치 전 필수
| 순서 | 항목 | 해결하는 이슈 | 공수 | 의존 |
|---|---|---|---|---|
| a1 | 통보 채널 복구·2채널 필수화·기동 시 `getMe` 검증·`/hub` 배너 | P0-2 | S | — |
| a2 | health 전이 통보기 + `service_status.ps1` 예약 작업 등록 + 크래시 루프·디스크 여유 통보 | P0-1, P1-22 일부 | S | a1 |
| a3 | hang/프레임 하트비트 분리 + STALE_FRAME 정확 분류 + 기아 3단계를 `os._exit`+NSSM Restart로 + 실측 시험 | P0-6, P1-11(오분류) | M | a2 |
| a4 | 예열 FAILED → 기동 실패 경로(통보·이벤트·재raise 정책) | P0-7 | S | a2 |
| a5 | 전원·덮개·절전 스크립트(`set_power_plan.ps1`) + SITE_CHECKLIST N-6~N-14 + BIOS AC 복구·UPS·NTP 절차(배포기 노트북 기준) | P0-8, P0-9, P1-20, P1-23 | S | — |
| a6 | 배포기(노트북) 4h 소크 실측 — 기준선 + S1·S2·S9 적용본(§5-3 절차) + 실카메라 4대 RTSP·재연결 | P1-9, P1-11 | S(측정) | a5 |
| a7 | 근접: 발끝 높이 비교로 운전자 오인 차단 + 통과형 침입 실측 + 2fps 정답지 재현율 재측정·목표치 선언 | P0-3, P0-4, P0-5(단기) | M | a6(실카메라) |
| a8 | 경보 재시도 시간 기반 + 회복 후 일괄 재전송 · 릴레이 즉시 경로·락 분리 · 기동/종료 OFF · 자동 pin 기준 변경 | P1-1~P1-4 | S~M | a1 |
| a9 | 레지스트리·pin 원자 쓰기 + 0대 복원 경보 · `/health.device` + `VIGENT_REQUIRE_CUDA` · `alert_queue.db` 손상 격리 | P1-17, P1-19, P1-22 | S | — |
| a10 | 카메라 `source` 화이트리스트 · 브라우저 증거 비식별화 · `webhook_url` 마스킹 · 비밀 파일 ACL | P1-12, P1-13, P2-10 일부 | S | — |
| a11 | 테스트 격리 완성(`test_alert_queue` isolate, `ensure_go2rtc` 가드, CI tree_hash 게이트) | P1-21 | S | — |
| a12 | 승인 기록 세션 결속 + 이벤트 id + 해시체인 (증빙 도구로 팔 경우) | P0-10, P1-24 일부 | M | Q1 답 |
| a13 | 개인정보 양식 4종·노사협의 안건서·계약 부속서(기능안전·설비연동)·AI 고지 문구 초안 → 법무 | P1-24 | S(초안)·L(법무) | — |
| a14 | 문서 정정 일괄(CLAUDE.md 수치·README CR·5초→60s·PRIVACY 초안·vision.yaml 주석·Dockerfile "미지원" 또는 수정·KOSHA 문구 삭제) | P3 문서군, P1-24 C-8 | S | — |

### (b) 설치 후 1개월 내
| 항목 | 이슈 | 공수 | 의존 |
|---|---|---|---|
| RBAC 최소 2역할 + 설정 변경·열람 감사로그 + TLS 옵션(`service_entry.py` ssl) + secure 쿠키 | P1-14, P1-15, P2-10 | M | a12 |
| 백업/복구 스크립트·런북 + 폐쇄망 번들(`make_offline_bundle.py`) + OTA/롤백 절차(`upgrade.ps1`) | P1-18, P2-9 | M | — |
| 카메라 tamper/노출/초점 최소 감지 + 카메라 오프라인 통보 + H.265 재검증 + 실행 중 source 변경 반영 | P2-7 | M | a2, a3 |
| 알람 생명주기(ack by id·clear·에스컬레이션·교대 수신자) + `/hub` 오디오 + 텔레그램 사진 첨부 + 이력 필터·CSV | P1-5, P2-1, P2-4 | M | a12(id) |
| 야간 유인 실측 + 조치 티켓 필드 + 월간 PDF 스케줄러 | P1-6, P1-24 | S~M | — |
| git 이력 재작성(세션 1) | P1-16 | M | 협업자 없음 확인 |
| 핵심 4모듈 단위 테스트 + 삼킴 except 54곳 로그화 + tapo 비동기 블로킹 제거 | P2-8 | M | — |

### (c) 3개월 내 경쟁력 확보
| 항목 | 이슈 | 공수 | 의존 |
|---|---|---|---|
| 오탐/미탐 피드백 UI → 라벨 큐 → RF-DETR 재학습(시드 고정) → 영상 기반 회귀 러너·CI 게이트 | P2-5, P2-8, P1-8 | L | (b) 이벤트 id |
| forklift RF-DETR 재학습(현장+LOCO) + 근접 호모그래피 + 거리 오차 리포트 | P1-7, P0-5(중기) | L | 현장 원본 영상 회수 |
| pre/post-roll 클립(go2rtc 링버퍼) + Modbus TCP 보조 신호 어댑터 + 체류시간·밀폐공간 카운트 | P2-3, P2-4, P2-11 일부 | M~L | — |
| Windows 로컬 VLM 대체(세션 2) → 하네스·장갑 VLM 보조 + 행동 안전 | P2-11 | L | RTX 환경 |
| 카메라별 override 확장·tuning 핫리로드·시간대 규칙 | P2-2 | M | — |
| 중앙 수집기(각 서버 `/health` 요약 푸시) + 다국어 텔레그램 템플릿/반응형 웹 | P2-9, P2-11 | L | — |
| TensorRT/fp16 + 슬롯 배치(정확도 회귀 게이트 필수) | P2-6 | L | (c)-1 회귀 러너 |

---

## 7. 코드 밖 체크리스트(개발자가 아닌 사람이 챙길 것)

**하드웨어·전원(배포기 = 노트북)** — Windows Pro·BitLocker 유지 확인 · BIOS AC Power Recovery 유무 · UPS(노트북 어댑터+공유기+PoE, 지속 시간 산정) · 덮개·절전·USB/NIC 절전 해제 결과 `powercfg /query` 보관 · 배터리 충전 상한·월 1회 `batteryreport` · 예비 어댑터 · 켄싱턴 락/잠금 캐비닛 · 케이블 고정 · 방진·방수 등급(현장 조사 후) · SSD 여유 <20% 알림 · Defender `data/` 제외 여부(보안 검토 후) · 다른 앱(브라우저·시연 페이지) 상시 실행 금지
**네트워크** — 카메라 고정 IP(DHCP 예약) · 카메라망/사무망 분리 · 유선 이더넷 · 4대 동시 대역폭 실측 · 인터넷 경로(유선/LTE)와 순단 길이 파악 · NTP 서버 · 방화벽 화이트리스트 · 텔레그램 외 2번째 채널 계정
**카메라 설치** — 높이·각도·거리 기준은 **미측정**(다음 현장에서 각도별 표본 후 정량화) · 사람 박스 크기(캐빈 0.24 vs 지상 0.82 실측)가 성능을 좌우함을 배치에 반영 · 구역은 "밟을 수 있는 땅"인지 스냅샷에 겹쳐 확인(2026-08-27 2회 실패 원인) · 야간·역광 조건 사전 촬영 · H.265면 H.264 서브스트림 준비 · NVR 경유 여부
**현장 교육** — 관제 화면(`/hub`) 배지 의미(입력 끊김 vs 검출 정지) · 텔레그램 억제 요약("N건 억제") 해석 · 승인/조치 확인 절차 · 오탐 보고 방법(현재 UI 없음 → 임시 절차) · 카메라 IP 변경 시 재등록 절차 · 서비스 상태 확인(`service_status.ps1`) · 정전·재부팅 후 확인 절차
**계약·법무** — 기능안전 면책(보조·감시 계층, 인증 안전장치 대체 불가) · 설비 정지 연동 시 안전 PLC 비안전 입력·비상정지 회로 비접속 요건서 · 오탐/미탐 한계(재현율 실측치·미측정 조건 명시) · 데이터 소유·보관기간(증거 30일 vs 산안법 3년 충돌 해소)·파기 · 개인정보 안내판·고지·운영관리방침·노사협의 · AI 기본법 "AI 운용 사실 고지" · 텔레그램 단일 채널·인터넷 단절 시 통보 불가 명시 · 클라우드 VLM 사용 여부(국외 이전 고지)
**운영** — 백업 매체(`data/`·`config/`·`.env`·BitLocker 복구 키) · Windows Update 정책·점검 창 · 월 1회 `/health`·디스크·온도 점검표 · 사고 시 증거 반출 절차(현재 워터마크·승인 없음)

---

## 8. 확인 질문(판단 유보 — 답에 따라 심각도·권장이 바뀐다)

**제품·계약**
1. VIGENT를 "안전조치 이행 **증빙** 도구"로 팔 것인가, "보조 감시 + 서류 초안 도구"로 팔 것인가? 전자면 P0-10·P1-24가 계약 전 필수, 후자면 P0-10은 P1. (Ph8 Q1)
2. 파일럿 현장의 운영 형태는? 야간 무인·단일 카메라 구역이 있는가(P0-1·P1-5 등급), 실제 이용자 수·역할(P1-14 등급), 외국인 근로자 비율(다국어 등급). (Ph3 Q1, Ph5 Q2, Ph8 Q9)
3. 텔레그램 외 2번째 채널(이메일/문자 게이트웨이)을 둘 계획인가, 텔레그램 단일 채널이 확정 정책인가? 오늘 401 토큰 상태를 인지하고 있었는가(값은 묻지 않음). (Ph4 Q1·Q2)
4. 현장 작업자 본인에게 알리는 수단(경광등·방송)이 계약 범위인가, 관리자 폰 통보만인가? 조달 릴레이가 자체 타임아웃 모드를 지원하는가? 설비 정지를 요구하는 고객이 있는가? (Ph4 Q3·Q4, Ph8 Q4)
5. 증거 30일·인식 로그 30일 보존은 고객 개인정보 정책에서 온 값인가? 산안법 3년과 어떻게 조화할 것인가("발송 건만 3년 pin"이 현 구조의 절충안). (Ph4 Q5, Ph8 Q3)
6. AI 기본법 고영향 AI 해당 여부 법무 확인, KOSHA 스마트 안전장비 지원사업 관리품목 등록 목표 여부, `evaluator.py`의 "KOSHA 인증 90%" 문구 출처. (Ph8 Q2·Q5·Q6)
7. `PRIVACY_POLICY_DRAFT.md` §3의 얼굴인식 모듈을 제품 범위에서 제외할 것인가? 클라우드 VLM을 켤 것인가(국외 이전 고지 감수) 끈 채로 기능표에서 뺄 것인가? (Ph8 Q7·Q8)

**아키텍처·운영**
8. 기아 3단계 프로세스 재기동(`sc stop & sc start`)을 실서비스 계정에서 발동시켜 본 적이 있는가? Ph1(도달 가능)과 Ph3(카운터 리셋으로 도달 불가) 분석이 갈린다 — 실카메라 단절 ≥6분 시험으로 확정. (Ph1 Q1, Ph3 I-9)
9. 프레스 방호구역(`machine_hazard_zones`, guard_bypass critical)이 브라우저 경로에만 있는 것은 의도인가? (Ph1 Q2)
10. 경보 재시도 10회·≈5분 후 dead·재전송 없음은 의도된 결정인가? 복구 후 일괄 재전송을 원하는가? 인터넷 경로(유선/LTE)와 순단 길이는? (Ph1 Q3, Ph6 Q2)
11. 예열 실패 정책: "기동 실패로 취급(재시작 루프+통보)" vs "떠 있되 통보"? 릴레이를 원격 채널 뒤에 둔 순서는 의도인가? 코드 기본 `VIGENT_CAPTURE_MODE=sync` 유지 이유는? (Ph1 Q8·Q9·Q10)
12. 카메라별 override를 1키로 제한한 우선순위는? 파일럿 4대가 동일 장면인가 이종 장면인가? 해제·ack·에스컬레이션 통보를 넣지 않은 것이 알림 피로 고려인가? (Ph1 Q5·Q6)
13. 배포기 노트북에 BIOS AC Power Recovery 항목이 있는가? 노트북의 현재 `powercfg` 값(덮개·절전·USB)은? 4h 소크 2회(기준선·최적화본)는 언제 하는가? 4대 미달 시 대안 A(3대)·B(fps 1.0)·C(교체) 중 어느 쪽을 선호하는가? `VIGENT_EDGE=1`+`site.yaml` 경로를 계속 지원할 것인가(서비스는 `cameras.json`만 읽음)? Docker·Linux 경로를 제품 범위로 유지할 것인가? VMS/NVR 연동 요구가 고객에게서 나온 적 있는가? (Ph6 Q1·Q4·Q5·Q6·Q10, Ph3 Q5)
14. 4대 실 RTSP 동시 운전을 한 번이라도 해봤는가? 전원은 켜둔 채 네트워크만 끊었을 때 `grab()`이 5s 블로킹인지 즉시 False인지? thread 모드 캡처 스레드 단독 CPU를 잰 적이 있는가("grab은 디코드 없음" 전제 출처)? 배포 현장 카메라 코덱·NVR 여부는 확정됐는가? go2rtc 단일 수신 구조(카메라 세션 1개)로 갈 것인가? (Ph3 Q2·Q3·Q4·Q6·Q7·Q8)

**모델·데이터**
15. 오늘 드라이런 GPU 83~89%/VRAM 4.0GB의 주체는(다른 프로세스 vs 서버 자체)? (Ph2 Q1)
16. person 재현율 목표치("원거리 포함 미탐 허용 한계")를 어느 값으로 선언할 것인가? 대외 수치는 현장 생존율 88.3%(GT 없음)와 dev 원거리 0~8%(GT 있음, 1fps) 중 무엇을 쓸 것인가 — 둘 다 아니면 2fps 정답지 측정 일정은? (Ph2 Q2·Q6)
17. 학원 프로파일의 AGPL YOLO(boda_ax) 사용이 배포·라이선스 방침(copyleft 0)과 어떻게 정합되는가? `.onnx` 3종을 매니페스트에 등재할 것인가, ONNX-CPU 경로를 지원 범위에서 뺄 것인가? Windows 데스크톱에서 VLM(MLX 설정) 경로가 실제 동작하는가? (Ph2 Q3·Q4·Q7)

**보안·품질**
18. go2rtc v1.9.14 win64에서 `exec:`·`ffmpeg:` 소스 스킴이 활성인가(고립 환경에서 실행 검증 후 P1-12 확정)? `docs/academy_visit_*.md`·`docs_rtsp_tapo.md`·`tools/rtsp_test.py`의 RTSP 사용자명은 예시인가 실제 계정명인가? 파일럿은 역프록시(Caddy/nginx)인가 uvicorn 직접 TLS인가? 엣지박스 서비스 계정은 LocalSystem인가 전용 계정인가? `config/security.json` 허용 호스트 검사가 dispatcher에서 실제 강제되는가? `docs/CODE_REVIEW.md`에 "M8-4"가 없다 — 어느 문서에 있는가? (Ph5 Q1·Q3·Q4·Q7·Q8·Q6)
19. `data/go2rtc.log`에 카메라 자격증명이 평문으로 남는가(이번에 열지 않음)? 이 PC 23:16 python PID 30036(WS 4.9GB)은 무엇이었는가(Phase 7 커버리지 실행으로 추정)? 개발 PC 저장소·`data/`가 HDD(D:) 위에 있는 것을 알고 있는가? (Ph6 Q7·Q8·Q9)
20. 이전 "테스트 전후 변경 0" 측정 때 `bin/go2rtc.exe`와 고아 go2rtc(포트 1984 점유)가 어떤 상태였는가 — 재측정 기록으로 대체할 것인가? go2rtc 자동기동 가드를 운영 코드(환경변수)로 둘 것인가 테스트 monkeypatch로 둘 것인가? `rig_monitor`/`rig_replay`·HTML 부속 모듈 7종은 로드맵 기능인가 시연 잔재인가? VERSION 0.2.0과 RELEASES v1.0/v1.0.1 축의 관계·대외 버전은? (Ph7 Q1·Q2·Q3·Q4·Q7)

---

## 9. 다음 단계 제안 — 로드맵 (a)를 Claude Code 작업 단위로

각 작업은 한 세션에 끝나는 크기이며, 이 저장소 규칙(테스트 먼저·게이트 5종·한 항목 한 커밋·`git branch --show-current`·한국어 커밋)을 따른다.

| # | 세션 제목 | 범위(파일) | 착수 조건 | 완료 기준 |
|---|---|---|---|---|
| W1 | 통보 채널 2중화 + 기동 시 검증 + 허브 배너 | `agents/dispatcher.py`, `main.py`(startup getMe), `themes/safety/index_hub.html`, `config/notify.example.yaml`(스키마 정정), `tests/test_alert_delivery_hardening.py` | 새 토큰·2번째 채널 계정 확보 | 채널 미설정/401 시 STARTUP_WARNINGS+이벤트 로그, 허브 붉은 배너, 예시 yaml 복사만으로 채널 설정됨 |
| W2 | health 전이 통보기 + 크래시 루프·디스크 여유 통보 + 예약 작업 등록 | `vigent-core/health_notifier.py`(신규), `main.py` `_optional`, `routers/system.py`, `deploy/windows/install_service.ps1`(schtasks), `service_status.ps1`, 테스트 | W1 | healthy→degraded/unhealthy·회복·디스크<5GB·크래시 루프 N회가 각 1회 통보; 재설치 검증 스크립트가 예약 작업 존재 확인 |
| W3 | 예열 실패 = 기동 실패 경로 | `readiness.py`, `main.py`(`_required` 정책), `tests/test_readiness_warmup.py` | 정책 결정(Q11) | FAILED 시 상태파일·이벤트 1000·통보 후 재raise 또는 N회 재시도, 테스트로 고정 |
| W4 | 워커 하트비트 분리·STALE_FRAME 정확 분류·기아 3단계 재설계 | `worker.py`(`loop_alive_ts`, 재시작 시 `last_frame_ts` 보존, `_hang_watch`), `health_status.py`, `starvation_guard.py`(`os._exit(3)`), `install_service.ps1`(`AppExit 3 Restart`), `tests/test_health_detect_alive.py`·`test_starvation_guard.py` | W2 | 죽은 카메라 시나리오 테스트에서 STALE_FRAME 유지·hang 카운터 불변·정상 카메라 무영향; 실카메라 단절 6분 시험 절차 문서화 |
| W5 | 경보 재시도 시간 기반 + 회복 후 재전송 + 릴레이 즉시 경로·락 분리 + 기동/종료 OFF + 자동 pin 기준 | `alert_queue.py`, `alert_notify.py`, `agents/dispatcher.py`, `relay.py`, `main.py`, `config/tuning.yaml`(키 노출), 테스트 | W1 | 단절 30분 후 회복 시 전부 전송; 릴레이가 원격 채널과 무관하게 ≤1s; `_shutdown` OFF 송신 테스트 |
| W6 | 레지스트리·pin 원자 쓰기 + 0대 복원 경보 + `/health.device`·`VIGENT_REQUIRE_CUDA` + `alert_queue.db` 손상 격리·WAL | `camera_registry.py`, `data_engine.py`, `device.py`, `routers/system.py`, `alert_queue.py`, `install_service.ps1`(env), 테스트 | — | 손상 파일 주입 테스트 통과; cuda 미가용 시 기동 거부·이벤트 1000 |
| W7 | 카메라 source 화이트리스트 + 브라우저 증거 비식별화 + webhook_url 마스킹 + 비밀 파일 ACL | `camera_registry.py`, `routers/cameras.py`, `tapo.py`, `safety_core.py`, `data_engine.py`, `setup_console.py`, `install_service.ps1`(icacls), `tests/test_security_gate.py` 외 | — | `file://`·`exec:`·`http://내부` 거부 테스트; 브라우저 경로 저장본에 모자이크 적용 확인 |
| W8 | 테스트 격리 완성 | `tests/test_alert_queue.py`, `routers/cameras.py`(`VIGENT_GO2RTC_AUTOSTART`), `tests/_isolate.py`, `.github/workflows/ci.yml`(tree_hash 게이트), `docs/FINAL_SUMMARY.md:57` 정정 | — | `tree_hash compare` data/+logs/ 변경 0(고아 go2rtc 없는 상태에서), go2rtc 프로세스 0 |
| W9 | 근접 단기 보정 + 통과형 침입 측정 절차 + 2fps 정답지·재현율 목표 | `proximity.py`(발끝 높이 비교), `zone_debounce.py`(위치 기반 키), `benchmarks/` 측정 스크립트, `docs/labeling_plan.md`, `tests/test_proximity_driver.py` | 실카메라·현장 원본 영상 | 운전자 오인 26/344 케이스 재생 테스트에서 0; 통과형 시나리오 실측 표; 목표치 문서화 |
| W10 | 전원·정전·NTP·Windows Update 절차 스크립트 + SITE_CHECKLIST N-6~N-14(노트북 기준: 덮개·절전·USB/NIC 절전 해제, BIOS AC 복구, UPS, 배터리) + 재설치 검증에 전원 단계 | `deploy/windows/set_power_plan.ps1`(신규), `verify_service_reinstall.ps1`, `deploy/SITE_CHECKLIST.md`, `md/DEPLOYMENT.md` | — | 스크립트가 `powercfg /query` 재검증 출력을 `audit/`에 남김; 체크리스트 항목별 확인 명령 존재 |
| W11 | 승인 기록 세션 결속 + 이벤트 id + 해시체인 (Q1 답이 "증빙"일 때) | `audit_store.py`, `data_engine.py`(id·evidence sha), `routers/safety_core.py`, `templates/auto.html`, 테스트 | Q1 | 임의 approver 거부, 체인 검증 스크립트가 변조 탐지, ack가 id 단위 |
| W12 | 문서 정정 일괄 + 규제·계약 초안 | `CLAUDE.md`, `README.md`, `deploy/windows/README.md`, `deploy/DEPLOYMENT.md`, `docs/STABILITY.md`, `docs/PRIVACY_POLICY_DRAFT.md`, `themes/safety/vision.yaml` 주석, `weights_manifest.json` note, `evaluator.py` 문구, `Dockerfile`(수정 또는 "미지원"), `docs/legal/`(신규: 안내판·고지문·운영관리방침·열람요청서·노사협의 안건·설비연동 요구사항서·계약 부속서 초안), `.gitignore` `pilot_*.md` 정정 + `docs/PILOT_DECISIONS.md` 추가 | — | `tests/test_baseline_freshness.py` 류로 수치 자동 검사; 초안 문서 존재·법무 검토 목록 |
| W13 | 배포기(노트북) 4h 소크 2회(기준선·S1+S2+S9) 실행·판정 기록 + 필요 시 §5-4 대안 선택 | `docs/LAPTOP_SIZING_PILOT4.md` §7 채움, `audit/loadtest_*laptop*` | 노트북 접근, W10 | 10항목 통과/미달 표 ×2 + 판정(A 4대 확정 / B 3대·fps 1.0 / C 교체 사양) |

---

*이 보고서와 Phase 문서(`docs/review/00~08`)는 작업트리에 저장돼 있으며 커밋하지 않았다(이번 작업 원칙: 코드 무수정, 문서 작성만). 커밋·정리 여부는 대표 결정 사항이다. 이전 검토(2026-09-03, `docs/review/01_현황.md`~`07_기록표.md`)는 그대로 두었다.*
