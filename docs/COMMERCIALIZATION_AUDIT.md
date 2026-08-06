# VIGENT 상용화 준비도 종합 감사 (Commercialization Readiness Audit)

> 작성 시작: 2026-08-05 · 대상 브랜치: `main` · 방식: 기존 감사 문서 승계 + 코드 재확인(직접 Read/Grep) + 위임 조사(서브에이전트, 결과는 원본 작성자가 직접 재검증한 항목만 채택)
>
> **원칙(사용자 지시 + CLAUDE.md 규칙7 준수)**: 측정하지 않은 수치·완성도 %를 지어내지 않는다. 미측정은 "미측정"으로 표기한다. 각 발견은 `[파일:줄번호] · 증상 · 실패 시나리오 · 심각도 · 예상 작업량`으로 기록한다. 이번 작업에서는 **코드를 고치지 않는다** — 발견·분류·우선순위만.
>
> **심각도 정의**: P0 출시 차단(보안사고급 포함) · P1 출시 전 필수 · P2 초기 고객 이후 · P3 개선.
> **작업량 정의**: S(수시간 이내 단순 수정) · M(설계 필요, 수일) · L(현장 데이터·정책 결정 등 선행조건 필요, 수주 이상).

---

## Phase 1 — 미해결 결함 승계 + 신규 코드 리뷰

### 1.0 승계 대상 기존 문서 (중복 작업 방지용 인덱스)

| 문서 | 작성일 | 다루는 범위 | 이번 감사와의 관계 |
|---|---|---|---|
| `COMMERCIAL_AUDIT.md` | 2026-07-14 | 사업 관점 갭 분석(현장 정확도·법무서류·KISA F1·법인자격), 수익화 경로 A/B/C 평가 | **승계** — Phase 3·5·7에서 그대로 인용. 이번 문서는 그 기술적 하부구조(코드 결함)를 보강 |
| `VIGENT 상용화 준비 체크리스트.md` | 2026-07-02~07 | AGPL 라이선스(해소)·기능안전 문구·개인정보·정확도 실측·제품분리(E-1) | **승계** — Phase 3(법규)에서 재확인 |
| `docs/CODE_REVIEW.md` | 2026-07-15 | main.py 구조·중복코드·에러처리·보안(path traversal·의존성·토큰)·협업준비 | **승계** — 이번 §1.2는 이 문서가 다루지 않은 항목만 신규 조사 |
| `docs/P3_BACKLOG.md` | 2026-07-16/17 | B1~B7(CI·config 격리·네이밍 등, B1~B3 완료) | **승계** — B4(rig_monitor 미배선)는 Phase 4·5에서 재인용 |
| `benchmarks/FINDINGS.md` | ~2026-07-15 | F-1~F-15(모델 성능·MPS 크래시·경로버그·법령게이트·클라우드VLM 등) | **승계** — Phase 5(성능)에서 재인용 |
| `audit/STATUS_REPORT_2026-07.md` | 2026-07-07 | 등급표 A~C(라이선스/모델/코드위생/배포/보안/에이전트/안정성) | **승계** — 이후 라운드(P0~P2, T10b)로 상당수 해소, Phase 4에서 최신화 |
| `AGENT_STATUS.md` | 2026-07-12 | 6-에이전트·4-문서유형·3-계층근거 구현/검증 상태 | **승계** — Phase 6(품질체계)에서 재인용 |
| `attribution/SOURCES.md` | 2026-07-08 | forklift 데이터셋 라이선스 표시 | **승계** — Phase 3(라이선스)에서 재확인 |

### 1.1 미해결 결함 9건 재확인

> 조사 방법: 서브에이전트에 위임 후, 핵심 주장(특히 파일 존재·인증 우회)은 이 문서 작성자가 직접 Read/Grep으로 재검증했다. 저장소는 로컬에 새로 clone한 shallow 상태이며 커밋 해시 인용은 `main` HEAD(`7157870`) 기준.

| # | 결함 | 상태 | 심각도 | 작업량 |
|---|---|---|---|---|
| 1 | index_vigent.html `/detect/frame` 계약 불일치 | 재현가능하나 **도달 불가(dead file)** | P3 | S |
| 2 | `ppeKeywordScore` '착용' 미반환 | 재현가능 | P1 | S |
| 3 | `window.stats` 미노출 → 낙상/자세 알림 dead | **낙상 절반=해소(2026-08-06 낙상 기능 제거)**, 자세 절반=재현가능(미해소) | P1 | S |
| 4 | 존재하지 않는 엔드포인트 호출 5종 | 재현가능 | P2 | M |
| 5 | 스텁 응답 3종 (`/ppe/analyze-frame`·`/vitals/rppg`·`/segment/frame`) | 재현가능(의도된 스텁) | P2 | L |
| 6 | `GET /zone/danger` 프론트 계약 불일치 | 재현가능(realtime_core.js 경로만) | P2 | S |
| 7 | `ppe_check.py` 라벨 부분매칭 충돌 | **해소**(해당 파일 기준). 인접 함수 별건 발견 | — | — |
| 8 | `WorkerManager.start` TOCTOU | 재현가능 | P1 | S |
| 9 | `loto_serial.py` 시리얼 락 부재 | **해소(2026-08-06 LOTO 기능 제거, 커밋 `09bdd17`)** | P1 | M |

#### 1. index_vigent.html — `/detect/frame` 응답 계약 불일치 → **재분류: P3(도달 불가)**

- 서버(`vigent-core/routers/detect.py:53-57`)는 `{"class":..., "score":..., "bbox":[x,y,w,h]}`(픽셀)를 반환하나, `themes/safety/index_vigent.html:201-202,361-364`는 `d.label`(→ 항상 `undefined`)·`[x1,y1,x2,y2]` 정규화 좌표를 기대 → `boxColor(undefined)`에서 `TypeError`.
- **추가 확인(이 문서 작성자, 원 조사에 없던 검증)**: `themes/safety/index_vigent.html`을 서빙하는 라우트가 **존재하지 않는다.** `/{theme}`(`routers/safety_core.py:801`)는 `themes/{theme}/index.html`만 서빙하고, `/safety-pro`는 `index_rfdetr.html`만 서빙한다. `themes/` 디렉터리 자체가 `StaticFiles`로 마운트되지도 않았다(`main.py`에 마운트된 것은 `/static`→`vigent-core/static/`, `/evidence`뿐). 저장소 전수 grep 결과 `index_vigent.html`을 참조하는 다른 파일도 0건. **즉 이 결함은 실사용자가 도달할 수 없는 죽은 파일에만 존재한다.**
- 실패 시나리오: (도달 불가하므로 해당 없음. 파일이 향후 라우팅될 경우에만 유효)
- 권고: 파일을 정리(삭제 또는 명확히 "미사용" 표기)하거나, 라우팅할 계획이 있다면 그때 계약을 맞춰 재작성.

#### 2. `static/realtime_core.js` `ppeKeywordScore` — '착용' 결과 폐기

- `realtime_core.js:844-867` — 루프에서 `best={state:'worn'}`을 정확히 계산하지만, 함수 끝의 `if((preds||[]).length){ return {state:'missing', ...} }`가 `best`를 참조하지 않고 예측이 하나라도 있으면 무조건 `missing`을 반환. `best`는 죽은 변수.
- 실패 시나리오: 서버 PPE 감지(§1.1-5, 스텁이라 항상 실패)가 실패해 브라우저측 MobileNet 폴백(`classifyPPERegions`)이 동작하는 모든 경우, 실제 착용 여부와 무관하게 상시 "미착용 의심"을 표시.
- 영향: PPE 착용 판정이 사실상 브라우저 폴백 경로에서 **상시 오탐**. 파일럿 데모에서 신뢰도 직결.
- 심각도: P1(브라우저 라이브 모드가 실사용 경로) · 작업량: S(마지막 블록에서 `best` 우선 사용하도록 1개 조건 수정).

#### 3. `window.stats` 미노출 → `/safety/fall`·`/safety/posture` 미호출

- `realtime_core.js:8`은 classic `<script>`에서 `const stats={...}`로 선언(→ `window.stats`로 노출 안 됨). `index.html`/`index_local.html`의 폴링 코드는 `window.stats.fall`/`window.stats.posture`를 참조 → 항상 `undefined`→`0` → 증가 조건이 항상 거짓 → 낙상/자세 경보 POST가 영구히 발화하지 않음.
- **추가 확인(이 문서 작성자)**: 이 결함은 **브라우저 라이브 페이지(webcam/MediaPipe 경로)의 알림 발화만** 죽인다. 서버사이드 RTSP 상시 감시 경로(`worker.py:175 FallTracker`, `worker.py:652` 부근 `data_engine.log_event`)는 이 브라우저 코드와 **독립적**으로 동작하며 영향받지 않는다(worker.py 전수 확인, `window.stats`/`realtime_core.js` 미참조).
- 실패 시나리오: 사용자가 브라우저에서 웹캠 라이브뷰로 낙상을 시연해도, 서버가 낙상을 인지해도, 이 UI 경로의 원격 알림(텔레그램 등) 트리거는 발화하지 않는다. 서버 워커 기반 상시감시(주력 배포 경로로 추정)는 무관.
- 심각도: P1(브라우저 데모/파일럿 시연 경로에서 낙상 알림이 조용히 죽어있음 — 파일럿 시연 시 발각 위험) · 작업량: S(`window.stats=stats` 한 줄 추가 또는 선언을 `var`/`window.` 프로퍼티로 변경).
- **후속(2026-08-06, 이 문서 작성자)**: 작업자 낙상 감지 기능 자체를 제거(사유·재도입 조건은 `docs/P3_BACKLOG.md` PF 항목 참고). 이로써 이 결함의 **낙상 절반은 자동 해소** — `stats.fall`·`/safety/fall` 엔드포인트·해당 폴링 코드 전부 삭제되어 코드에 `window.stats`/`/safety/fall` 참조가 0건이다. 그러나 **`window.stats.posture`(부담자세) 절반은 그대로 남아있다** — 부담자세는 이번 제거 대상이 아니었고, `realtime_core.js`의 `stats` 선언은 여전히 `window.stats`로 노출되지 않는다. 위 표의 "작업량 S" 수정(`window.stats=stats` 한 줄)은 자세 절반에 대해 여전히 유효하다.

#### 4. 존재하지 않는 엔드포인트 호출 5종

- `realtime_core.js`에서 호출: `/dataset/small-object/crop`(1125행) · `/vision/capabilities`(2164행) · `/vision/analyze-current`(2178행) · `/llm/vision`(3182행) · `/sensor/temperature`(4480행) · `/alert/overspeed`(4510행).
- 백엔드 전수 대조(`routers/*.py`, `main.py` include_router 목록, `baseline_openapi.json` 91개 경로) 결과 6개 경로 모두 미존재. 유사 기능은 다른 이름(`/alerts/status`, `/alerts/test`, `/safety/sensor`)으로 존재.
- 실패 시나리오: 대부분 `.catch(()=>{})`로 조용히 무시되어 기능(과속경보·소형물체 데이터수집·VLM 캡션·온도경보)이 무동작. `/llm/vision`만 예외 없이 throw되어 사용자에게 "서버 LLM 오류: 404"로 노출됨.
- 심각도: P2(기능 자체가 부가 기능들이고 조용히 죽어있어 핵심 경로 저해는 아니나, 방치 시 죽은 코드 누적) · 작업량: M(6개 호출부 각각 실제 라우트로 교체하거나 기능 제거 결정 필요 — 콜사이트가 흩어져 있음).

#### 5. 스텁 응답 3종

- `/ppe/analyze-frame`(`routers/ppe.py:65-67`)·`/vitals/rppg`(`routers/vitals.py:7-9`)·`/segment/frame`(`routers/detect.py:92-94`) 전부 `{"ok": True, ...: [], "note":"stub"}` 하드코딩.
- 부가 발견: `/ppe/analyze-frame`은 스텁 여부와 별개로 응답 계약도 프론트(`realtime_core.js:941-942`, `if(!data.success) return`)와 불일치 — 스텁이 `success` 키를 주지 않아 항상 조기 return. 이중으로 죽어있음.
- 실패 시나리오: 세 기능(서버 PPE 분석·원격 심박(rPPG)·세그멘테이션) 모두 실제 추론 없이 항상 빈 결과. 코드 자체에 "stub"로 명시돼 팀도 인지 중인 의도된 미구현으로 판단됨(은폐 아님).
- 심각도: P2(영업자료에 "지원"으로 기재하지만 않으면 즉각 출시 차단은 아님. 단, 상용 계약서에 이 3기능이 언급된다면 P0로 격상) · 작업량: L(실제 추론 로직 구현은 각각 별도 모델/알고리즘 필요 — rPPG는 특히 신뢰도 검증까지 필요).
- **권고 우선 조치**: 코드 구현 전에 **영업자료·UI에 이 3기능이 "가능"으로 노출되지 않는지부터 확인**(Phase 3·7에서 재확인).

#### 6. `GET /zone/danger` 프론트 계약 불일치

- 서버(`web_util.py:83-91` `zone_get`, `93-108` `zone_set`)는 `{"points":[...]}`만 반환/저장.
- `realtime_core.js:1789`는 `if(j.success && j.zone && zonePolygon(j.zone))`을 기대 — `success`/`zone` 키가 없어 항상 거짓.
- 실패 시나리오: 위험구역을 브라우저에서 저장하면 `localStorage`에는 남지만(로컬 폴백 정상 동작), 새로고침·다른 기기에서는 서버에 저장된 구역을 불러오지 못함 — 다중 기기/카메라 간 구역 동기화가 사실상 죽어있음. `index_vigent.html`·`index_rfdetr.html`은 `d.points`를 올바르게 파싱해 문제없음 — **`realtime_core.js` 소비 경로에만 국한**.
- 심각도: P2 · 작업량: S(프론트 조건을 `j.points` 기준으로 수정).

#### 7. `ppe_check.py` 라벨 부분매칭 충돌 — 해소 확인 + 별건 발견

- `ppe_check.py:121,129-133`의 `item["miss"] in low`는 리스트 원소 완전일치(Python `in`이 `list` 대상이면 `==` 비교) — "hardhat"이 "no-hardhat"의 부분문자열이어도 오매칭되지 않음. **해소(애초에 이 파일에서는 재현 안 됨).**
- 별건: `web_util.py:110-114` `is_safety_label`은 진짜 부분문자열 매칭(`"hardhat" in "no-hardhat"` → True)이지만, 이 함수는 present/missing 판정이 아니라 `/detect/frame`의 표시용 필터(`safety_only`)에만 쓰임 — "Hardhat"과 "NO-Hardhat"을 둘 다 안전 관련으로 유지하는 것이 의도된 동작으로 보임. 원 리뷰 코멘트가 정확히 이 함수를 가리킨 것인지는 **미확인**(정확한 원 지적 대상을 특정할 수 없음).
- 심각도: 해당 없음(해소) / 별건은 P3(정상 동작 가능성이 높으나 확인 필요).

#### 8. `worker.py` `WorkerManager.start` TOCTOU

- `worker.py:815-824` — `_reg_lock` 보호 구간은 "확인 후 딕셔너리에 새 `Worker()` 등록"까지만이고, `state["running"]=True` 설정은 락 해제 후 `w.start()` 내부(`511`행)에서 일어남.
- 실패 시나리오: `WorkerManager.start(cam_id)`를 거의 동시에 2회 호출(이중클릭·재시도) → 두 호출 모두 `cur.state["running"]==False` 구간을 통과해 `Worker()` 인스턴스 2개(`w1`,`w2`)가 각각 생성·`self._workers[cam_id]`에 순차 덮어쓰기 → 두 스레드가 동일 카메라 소스를 중복 오픈, 먼저 생성된 `w1`은 딕셔너리에서 밀려나 `WorkerManager.stop()`으로도 멈출 수 없는 좀비 daemon 스레드로 잔존.
- 심각도: P1(카메라 리소스 중복 점유·좀비 스레드 누적은 장기 무인운영 안정성 직결) · 작업량: S(락을 `w.start()` 호출까지 확장하거나 `state["running"]`을 락 안에서 먼저 세팅).

#### 9. `loto_serial.py` 시리얼 락 부재

- `vigentFacialRecognition/loto_serial.py` 전체에 `threading`/`Lock` 사용 0건. 전역 싱글톤 `loto_controller`(`app.py:92`)를 `async def`(이벤트루프) 라우트와 `def`(스레드풀) 라우트가 공유(`/loto/apply`,`/loto/remove`,`/loto/arm`은 async, `/loto/energize`,`/loto/shutdown`은 sync).
- 실패 시나리오: 서로 다른 요청이 동시에 같은 `pyserial.Serial` 객체에 `write()`→`readline()`을 인터리빙 → 한 명령의 응답을 다른 명령이 가로채 반환 가능 → **LOTO(잠금장치) 상태가 실제 하드웨어와 불일치**할 수 있는 안전 관련 레이스.
- 비고: `simulated=True`(포트 미연결) 상태에서는 즉시 문자열 반환이라 레이스가 드러나지 않음 — **실하드웨어 연결 배포에서만 재현**.
- 심각도: P1(안전잠금장치 오상태는 사고 직결 가능성 있으나, 현재 LOTO 기능 자체가 파일럿 단계 부가기능으로 추정되어 P0까지는 아님 — 실배포 확정 시 P0 재평가 권고) · 작업량: M(`threading.Lock`을 `_send` 전체에 걸고, async 라우트에서의 블로킹 I/O 처리 방식도 함께 재검토 필요).
- **후속(2026-08-06, 이 문서 작성자)**: LOTO 기능 자체를 제거(`09bdd17`, "Vigent Face Scanner"로 재구현 예정 —
  `docs/P3_BACKLOG.md` PH). `loto_serial.py` 파일이 삭제되며 이 레이스 자체가 **제거로 해소**됐다. 같은 제거
  조사 중 이 결함과는 별개로 **`/loto/remove`의 인증 우회(사진 없이 person_id만으로 타인 잠금 해제 가능 +
  요청자/대상자 신원 미분리로 "본인 것만 해제" 검사가 API 경로에서 무력화)도 함께 신규 발견했으며, 이 역시
  코드 삭제로 제거로 해소됐다** — 단 face scanner 재구현 시 동일 패턴이 재발하지 않도록 PH 항목의 "피할 것
  3가지"를 반드시 참조할 것.

### 1.2 신규 코드 전수 리뷰

> 감사 지시서에 명시된 8개 대상 중 **5개는 저장소에 파일 자체가 존재하지 않는다.** 이 문서 작성자가 `Glob`·`git log --all`로 직접 재확인했다(전체 히스토리에 해당 파일명 커밋 0건, 현재 브랜치는 `main` 1개뿐).

| 대상 | 상태 |
|---|---|
| `vigent-core/routers/cameras.py` | **미존재**(현재도, 과거 커밋에도 없음) |
| `vigent-core/camera_registry.py` | **미존재**. 유사 역할은 `worker.py`의 `WorkerManager._workers`(dict, `threading.Lock` 보호)가 부분 수행 |
| `vigent-core/press_zone.py` | **미존재**. 기능은 `routers/zone.py` + `web_util.py`의 `zone_get`/`zone_set`(`/zone/machine`)으로 구현 — 이번 감사에서 대체 리뷰함(아래) |
| `static/vigent-box-display.js` | **미존재**. `static/`에는 `realtime_core.js`·`pose3d.js`·`posture-model.js`·`ergonomics.js`·`vt-rail-collapse.js` 등 9개 JS만 존재 |
| `themes/safety/index_hub.html` | **미존재**. `themes/safety/`엔 `index.html`·`index_local.html`·`index_rfdetr.html`·`index_vigent.html`·`index_boda_ref.html`·`console.html`만 존재. `hub.py`+`static/hub_terminal.html`(바탕화면 런처용 앱 타일 메뉴)은 이름은 유사하나 완전히 다른 기능이라 대체 리뷰하지 않음 |
| go2rtc 연동(1984/8554/8555)·live/webrtc | **존재** — `routers/tapo.py`. 아래 리뷰함 |
| `worker.py` 포즈 스레드 분리·`set_fps`·차등 캐던스·focus 부스트 | **미존재**. `worker.py` 857줄 전체 정독 + 전역 키워드 grep(`set_fps`/`cadence`/`focus_boost`/`pose_thread` 등) 0건. 포즈는 별도 스레드가 아니라 `_process_frame`의 코어 추론 락 **안에서 동기 호출**되는 구조(`FallTracker`/`ErgonomicsTracker`가 `_PoseModel` 싱글톤 사용) |

**해석**: 이 6개 항목(cameras.py 등)은 실제 구현되지 않은 상태다. 로드맵·기획 문서에만 존재하거나, 지시서가 다른 브랜치/저장소를 참조했을 가능성이 있다. **사업 관점에서 중요한 시사점**: `COMMERCIAL_AUDIT.md`나 사업추진계획서 등 외부 문서에 "카메라 관리 UI"·"프레스존 전용 모듈"·"박스 디스플레이 컴포넌트"·"허브 화면" 등이 이미 구현된 것처럼 기술돼 있다면 **사실과 다르므로 확인이 필요하다.** (Phase 7에서 사업추진계획서와의 정합성 재확인 시 함께 점검할 것.)

#### press_zone(실체: `routers/zone.py` + `web_util.py`) 리뷰

- **[P3/S] `zone.py:29-32`, `web_util.py:93-108` 동시 저장 시 파일 락 부재**: `zone_set`이 락 없이 `open(p,"w")`+`json.dump`. 관리자 2명이 거의 동시에 `POST /zone/machine`하면 마지막 쓰기가 이전 쓰기를 조용히 덮어씀. 단일 관리자 UI 전제라 실발생 가능성 낮음.
- 좌표계 일관성: `zone_set`이 `[0.0,1.0]` 클램프하고, `index_vigent.html:446`이 MediaPipe 정규화 좌표를 그대로 저장 — **불일치 없음(정상, 발견 아님)**.
- path traversal: `zone_path`는 서버측 `vision.yaml` 설정에서만 오고 요청 바디로 제어되지 않음 — **해당 없음(정상)**.

#### go2rtc 연동(`routers/tapo.py`) 리뷰

- **[P0/M] `/tapo/ws` 가 HTTP 인증 미들웨어를 우회 — 이 문서 작성자가 독립적으로 재검증함.**
  - `main.py`의 인증(`_auth_guard`, 122행)·테마게이트(`_theme_gate`, 134행)·캐시제어(`_no_cache_dynamic`, 144행) 미들웨어 3개 **전부** `@app.middleware("http")`로 등록되어 있다(직접 확인, `main.py:122,134,144`). Starlette에서 `@app.middleware("http")`는 ASGI `http` scope에만 적용되고 `websocket` scope에는 적용되지 않는다 — `app.add_middleware(...)`(scope 무관 적용 가능한 형태)나 `Depends`를 통한 라우트별 인증도 저장소 전체에 0건(grep 확인).
  - `tapo.py:24-27`의 `@router.websocket("/tapo/ws")` 핸들러는 토큰 검증 없이 즉시 `await ws.accept()`.
  - 실패 시나리오: `VIGENT_API_TOKEN`을 설정해 외부 노출한 배포(`main.py`가 스스로 "외부 바인딩엔 토큰 필수, 설정 시 전 라우트 Bearer 인증"이라고 선언한 바로 그 계약)에서도, 누구나 `ws://<host>/tapo/ws`에 연결하면 **토큰 없이 실시간 카메라 영상 스트림을 열람**할 수 있다. `COMMERCIAL_AUDIT.md`/이번 감사 지시서에도 "알려진 것"으로 언급된 항목이나, **정확한 우회 메커니즘(Starlette HTTP-scope 미들웨어의 구조적 한계)을 이번에 코드로 확정**했다.
  - 심각도: **P0(출시 차단, 보안사고급)** — 근로자 얼굴이 담긴 실시간 영상이 인증 계약을 깨고 노출됨(Phase 3 개인정보 감사와 직결). 작업량: M — WebSocket 라우트 진입 시 수동 토큰 검증(쿼리 파라미터 또는 첫 메시지로 토큰 전달) 추가 + 회귀 테스트 필요.

- **[P1/S] `tapo.py:24-50` `asyncio.gather`로 인한 태스크·업스트림 연결 누수**: 브라우저가 라이브뷰를 닫아 `c2u()`가 종료돼도 `u2c()`(go2rtc→브라우저 방향)는 `async for msg in up`에서 무한 대기 — `asyncio.gather`는 두 태스크가 모두 끝나야 반환되므로 go2rtc 업스트림 연결도 닫히지 않는다. 라이브뷰를 반복 열람하는 정상 사용 패턴에서 태스크·연결이 누적. 작업량: S(`asyncio.wait(..., return_when=FIRST_COMPLETED)`로 교체 후 나머지 태스크 취소).
- **[P3/S] `tapo.py:54-66` `/tapo/webrtc` 요청 바디 크기 제한 없음**: `request.body()`를 무제한 로드. SDP 특성상 실질 악용 난이도 낮고 이 경로는 인증 적용 대상(HTTP scope)이라 낮은 우선순위.

---

### Phase 1 발견 종합 (심각도순)

| 심각도 | 발견 | 작업량 |
|---|---|---|
| **P0** | `/tapo/ws` WebSocket 인증 우회(HTTP 미들웨어가 WS scope 미적용) | M |
| P1 | `ppeKeywordScore` '착용' 미반환 → 브라우저 PPE 판정 상시 오탐 | S |
| P1 | `window.stats` 미노출 → 브라우저 낙상/자세 알림 dead(서버 워커 경로는 무관) — **낙상 절반 2026-08-06 해소(기능 제거), 자세 절반 미해소** | S |
| P1 | `WorkerManager.start` TOCTOU → 중복 워커·좀비 스레드 | S |
| P1 | `loto_serial.py` 락 부재 → 실하드웨어에서 LOTO 상태 레이스 — **2026-08-06 LOTO 제거로 해소** | M |
| P1 | `tapo.py` `asyncio.gather` 태스크/연결 누수 | S |
| P2 | 존재하지 않는 엔드포인트 5종 호출(부가기능 무동작) | M |
| P2 | 스텁 응답 3종(`/ppe/analyze-frame`·`/vitals/rppg`·`/segment/frame`) | L |
| P2 | `GET /zone/danger` 계약 불일치(다중기기 구역 동기화 dead) | S |
| P3 | `index_vigent.html` 계약 불일치 — 단, **도달 불가(dead file)** | S |
| P3 | `zone.py`/`web_util.py` 동시저장 파일락 부재 | S |
| P3 | `web_util.is_safety_label` 부분매칭(정상 동작 가능성 높음, 확인 필요) | — |
| P3 | `tapo.py` 요청 바디 크기 제한 없음 | S |
| — | `ppe_check.py` 라벨 매칭 | 해소 |
| — | cameras.py·camera_registry.py·press_zone.py(파일)·box-display.js·index_hub.html | **미구현(존재하지 않음)** — 사업 문서와의 정합성 확인 필요(Phase 7) |

**Phase 1 결론**: 가장 시급한 단일 항목은 **`/tapo/ws` 인증 우회(P0)** — 외부 노출 배포에서 카메라 실영상이 인증 없이 열람 가능하며, 이는 Phase 2(보안)·Phase 3(개인정보)에서 재차 다룬다. P1 5건 중 3건(ppeKeywordScore·window.stats·tapo 태스크누수)은 각각 작업량 S로 저비용 고효과 수정이다. 감사 지시서가 지목한 "신규 코드"의 상당수(cameras.py 등 5개)가 실제로는 저장소에 없다는 점은 이번 감사의 범위 자체에 대한 중요한 정정이며, 사업추진계획서 등 외부 문서와의 기능 정합성을 Phase 7에서 반드시 재확인해야 한다.
