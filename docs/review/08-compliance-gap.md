# Phase 8. 규제/표준 및 경쟁 제품 대비 격차 분석

> 작성 2026-09-08 · 대상 `D:\vigent_original` 브랜치 `audit/cleanup-20260906`(HEAD `d4517fc`) · 방식: 코드 정독(Read/Grep) + 웹 검색(출처 URL·확인 날짜 명기) · **코드 수정·서버 기동 없음**.
>
> **원칙(CLAUDE.md 규칙 7·11)**: 코드 지적은 `파일:줄`, 규제·경쟁 주장은 출처 URL + 확인 날짜. 법령 해석이 필요한 항목은 **법률 자문이 아니며 "확인 필요"** 로 표기한다. 경쟁사 기능은 **제품 페이지에 적힌 것만** 인용하고, 실제 성능·정확도는 검증하지 않았다(과장 금지).
>
> **심각도**: P0 = "증빙·안전·법규" 주장을 대외에 쓰기 전 차단 · P1 = 파일럿/계약 전 필수 · P2 = 경쟁 열위(영업 시 불리) · P3 = 개선. **공수** S(수시간~1일) · M(수일, 설계 필요) · L(수주, 외부 선행조건).

---

## 0. 한 줄 결론

VIGENT 는 **"보조·감시 계층"이라는 기능안전 경계 문구는 코드·UI·문서 전반에 일관되게 박혀 있고**(§2), 얼굴 모자이크·보존기간 자동 파기·승인 감사추적 같은 개인정보·책임 분리 장치도 **구현돼 있다**. 그러나 산안법·중처법 관점의 **"안전조치 이행 증빙"으로 쓰려면** ①승인자 신원이 로그인 세션과 결속되지 않고 ②기록에 위변조 방지 장치(해시체인·서명·WORM)가 전혀 없으며 ③조치 이력(무엇을·언제까지·완료 여부)이 없고 ④정기(반기·월간) 보고서 자동 생성이 없다(§1). 경쟁 기준선 26항목 중 **있음 9 · 부분 8 · 없음 9**(§4) — 특히 안전대/장갑 검출, 체류시간, 모바일 앱, 다국어, 중앙 관제, 오탐 피드백 학습, RBAC 가 없다. **P0 1건 · P1 7건 · P2 10건 · P3 4건.**

---

## 1. 산안법·중처법 "안전조치 이행 증빙" 요건 대조표

### 1-1. 법적 근거(웹 확인, 2026-09-08)

| 근거 | 요지 | 출처 |
|---|---|---|
| 산업안전보건법 제36조 | 사업주의 위험성평가 실시 의무 | [law.go.kr 산업안전보건법](https://www.law.go.kr/법령/산업안전보건법/제36조) (저장소 `data/legal/statutes.yaml:19-31` 도 동일 조문 등재, 원문 text 미보관) |
| 산업안전보건법 제164조 | 안전조치·산업재해 발생원인 기록 등 서류 **3년 보존** | [casenote 제164조](https://casenote.kr/법령/산업안전보건법/제164조) · [hseworld 해설](https://hseworld.co.kr/35) |
| 사업장 위험성평가에 관한 지침(고용노동부고시 2023-19호) 제14조 | 위험성평가 실시내용 **3년 기록·보존**, 제15조 상시평가 | [law.go.kr 행정규칙](https://www.law.go.kr/LSW//admRulInfoP.do?admRulSeq=2100000251014&chrClsCd=010201) |
| 중대재해처벌법 시행령 제4조 | 유해·위험요인 확인·개선 절차 마련 + **반기 1회 이상 점검**, 안전·보건 관계 법령 의무 이행 **반기 1회 점검·보고** | [law.go.kr 시행령](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lspttninfSeq=173767&chrClsCd=010202) · [worklaw 반기 점검 해설](https://www.worklaw.co.kr/main2022/view/view.asp?bi_pidx=34823) |

> ⚠ "CCTV 이벤트 로그가 중처법상 '안전조치 이행 증빙'으로 인정되는가"는 **법령에 명문 규정이 없고 판례도 확인하지 못했다 — 확인 필요(법무).** 아래 표는 "증빙으로 제출될 때 상대방이 다툴 수 있는 지점"을 기술적으로 대조한 것이다.

### 1-2. 대조표

| # | 증빙 요건 | 현재 코드 | 판정 | 근거(파일:줄) |
|---|---|---|---|---|
| E1 | **이벤트 기록의 원본성**(사후 수정·삭제 탐지) | 인식 로그는 일자별 JSONL **append 만**; 해시체인·서명·타임스탬프 없음. 증거 JPEG 도 해시 미기록 | ❌ 없음 | `vigent-core/data_engine.py:152-188` (`log_event` — 레코드에 `ts/rule/level/score/site/note/evidence` 만), `:52-72` (`_save_frame`: 파일 쓰기만) |
| E2 | **승인 기록의 원본성** | 동일 — `data/audit/audit_<날짜>.jsonl` append, 무결성 장치 없음 | ❌ 없음 | `vigent-core/audit_store.py:21-40` |
| E3 | **승인자 신원 결속**(누가) | `approver` 가 **요청 본문의 자유 문자열**(기본값 "안전관리자"); 로그인 세션(auth_session)의 사용자 식별과 연결되지 않음. 세션 자체도 단일 운영자 전제 | ❌ 없음 | `vigent-core/routers/safety_core.py:274` (`approver = payload.get("approver") or "안전관리자"`), `:296`; `vigent-core/auth_session.py:8-10` (단일 운영자, RBAC 백로그 B12) |
| E4 | **조치 이력**(언제·어떻게·완료 여부·담당·기한) | `action ∈ {risk_assessment, acknowledge}` 두 종류만. `note` 인자가 있으나 라우트가 전달하지 않아 **조치 내용이 기록될 경로가 없다.** 상태(접수→조치중→완료)·기한·담당자 필드 없음 | ⚠ 부분(확인 여부만) | `vigent-core/audit_store.py:21-23` (`note` 인자), `routers/safety_core.py:296` (`note` 미전달), `:299-319` (감사추적 화면 6열: 일시·승인자·위험·조치유형·현장·평가서) |
| E5 | **위험성평가서 생성·보존** | 이벤트 집계→평가표 HTML+JSON 저장(`data/risk_assessments/`), 법령 인용 KB 내장, LLM 은 옵션(`use_llm=False` 기본) | ✅ 있음 | `vigent-core/agents/scribe.py:1-11, 242-256, 353-361, 384-387`; 보존 1095일 `config/tuning.yaml:161-163` |
| E6 | **TBM(작업 전 회의) 기록** | JSON 저장, 참석자 `signed: bool` — **전자서명이 아니라 체크박스** | ⚠ 부분 | `vigent-core/tbm_store.py:13, 43-47`, `routers/tbm.py:124, 141` |
| E7 | **정기 보고서**(월간·반기 점검 보고) 자동 생성 | 대시보드는 **요청 시 HTML 렌더**만(전월 대비 집계 있음). 주기 생성·PDF 출력·반기 점검 서식 없음(`주간|월간|weekly|monthly|schedule` grep 0건: scribe/safety_manager/analyst/dashboard/safety_core) | ❌ 없음 | `vigent-core/dashboard.py:1-6, 39-83`; `vigent-core/routers/safety_core.py:162` (`/report/safety` on-demand) |
| E8 | **보관 기간** | 자동 파기 스케줄러 있음(24h 주기, 첫 주기 보류 안전장치). 증거·인식로그 **30일**, 감사·TBM·평가서 **1095일(3년)** — 잠정값, 법무 미확인이라고 스스로 표기 | ⚠ 부분(정책 미확정) | `config/tuning.yaml:127-163`; `vigent-core/retention.py:39-46, 264-`; `vigent-core/retention_scheduler.py:1-5` |
| E9 | **증거와 평가서의 연결 유지**(30일 후 증거 삭제 시) | 평가서 생성 시 증거를 data URI 로 **내장**하므로 삭제 후에도 평가서는 자립. 단 **인식 로그(빈도 근거)는 30일 후 소실** — 발송 경보만 자동 pin | ⚠ 부분 | `vigent-core/agents/scribe.py:224-241` (`_evidence_data_uri`), `data_engine.py:121-131` (pin), `config/tuning.yaml:140` (`auto_pin_sent_alerts` 주석 처리) |
| E10 | **열람·접근 기록**(누가 증거를 봤나) | 없음. uvicorn 접근 로그 설정도 없음(`access.?log` grep 0건) | ❌ 없음 | `vigent-core/main.py`, `vigent-core/vlog.py` 전수 grep |
| E11 | **재해 원인분석 기록** | 업로드 영상 분석 결과를 화면에 반환만 — **저장·조치 연결 없음**, 면책 문구 있음 | ⚠ 부분 | `vigent-core/incident.py:7-8, 254-255`; `routers/incident.py:16-60` (저장 호출 없음) |
| E12 | **시간 동기** | 이벤트 시각은 KST 고정, NTP 검증 없음(설치 체크리스트 항목화 권고만) | ⚠ 부분 | `SAFETY_REVIEW_REPORT.md:94` |

---

## 2. 기능안전 경계·인터록 요건

### 2-1. "보조·감시 계층" 경계 문구 — 어디에 있는가

| 위치 | 문구 | 근거 |
|---|---|---|
| 규칙서 | "비전 ML은 확률적이므로 인증 안전기능을 대체할 수 없다… Type 4 광전자식 방호장치, 안전 PLC… 보조·감시 계층으로 신호만 제공" | `CLAUDE.md:77-78` |
| 릴레이 출력 | "이 릴레이는 보조 신호다. 인증 안전회로(안전 PLC·Type4 방호장치)를 대체하지 않는다" + OFF 보장 설계 | `vigent-core/relay.py:16-17, 10-14` |
| 디스패치 라우트 | `/dispatch/relay` 응답에 `is_primary_safety: False`, `relay: "auxiliary_signal"`, boundary 필드 | `vigent-core/routers/dispatch.py:3-6, 19-21, 40` |
| 프레스 방호구역 | "1차 방호 책임은 인증 하드웨어… 본 판정은 그 보조·예방" | `vigent-core/press_zone.py:3-4` |
| 테마 설정 | `critical: [alarm, manager_call, safety_relay_signal]  # §8 기능안전 경계: 보조 신호만` | `themes/safety/vision.yaml:123` |
| UI 푸터 | "보조·기록 도구이며 인증 안전장치를 대체하지 않습니다. 최종 판단·조치는 안전관리자 승인하에" | `vigent-core/hub.py:70`; `ppe_check.py:192, 231`; `liveguide.py:86`; `voice.py:50`; `quote.py:93-94`; `demo.py:159`; `setup_console.py:155` |
| 브라우저 E-stop 보조신호 | `/zone/state` 는 서버 스텁이라 **호출하지 않음**으로 명시(미구현 표시) | `vigent-core/static/realtime_core.js:1836-1844` |
| 문서 | 체크리스트 §2(계약서·영업자료 명시 항목 **미체크**), 개인정보 방침 초안 §1·§2, 파일럿 제안서 각주 | `docs/COMMERCIALIZATION_CHECKLIST.md:40-47`; `docs/PRIVACY_POLICY_DRAFT.md` §1·§2; `docs/PILOT_PROPOSAL.md` [^boundary] |

판정: **코드·UI 는 충분히 일관**. 빠진 것은 **계약서·견적서 표준 조항**(체크리스트 §2 `[ ]` 그대로)과 "설비 정지 연동을 요구하는 고객에게 무엇을 요구할지"의 문서(아래 2-2).

### 2-2. 설비 정지 인터록에 쓰려면 — 추가 요건(출처 포함)

VIGENT 의 릴레이는 HTTP GET/POST 1채널(`relay.py:70-82`), 진단·이중화·응답 확인 없음 → **ISO 13849-1 카테고리 B 수준의 단일 채널 신호**로 봐야 한다. 설비 정지에 얹으려면:

| 요건 | 내용 | 출처(확인 2026-09-08) |
|---|---|---|
| 인증 안전 PLC/안전 릴레이 경유 | 비전 신호는 안전 PLC 의 **비안전 입력**으로만 들어가고, 정지 명령은 안전 PLC 가 자체 안전기능(광전자식·양수조작 등)의 논리와 결합해 내린다 | [TÜV SÜD ISO 13849/IEC 62061](https://www.tuvsud.com/en-us/services/functional-safety/iso-13849-iec-62061) · [Pilz EN ISO 13849-1](https://www.pilz.com/en-US/support/law-standards-norms/functional-safety/en-iso-13849-1) |
| 2채널·교차 감시 | ISO 13849 Cat.3/4, IEC 62061 SIL2/3 은 이중 채널 + 교차 모니터링 요구 | [AMD Machines Safety PLC design](https://amdmachines.com/blog/safety-plc-and-safety-system-design/) · [Patsnap SIL vs PL](https://www.patsnap.com/resources/blog/articles/sil-vs-performance-level-iec-62061-vs-iso-13849/) |
| 진단(DC)·MTTFd·CCF | PL 산정에 진단범위·공통원인고장 평가 필요 — 비전 알고리즘은 확률적이라 **PL 을 부여할 수 없음**(방호장치가 아니라 보조) | [IFA Report 2/2017e](https://www.dguv.de/medien/ifa/en/pub/rep/pdf/reports-2019/report0217e/rep0217e.pdf) |
| 정지 카테고리 | IEC 60204-1 §9.2.2 정지 카테고리 0/1/2; **비상정지는 0·1 만**(ISO 13850) — 비전 트리거 정지는 "운전 정지(카테고리 2 포함)"로 설계하고 비상정지 회로와 분리 | [Kollmorgen Stop & E-stop](https://www.kollmorgen.com/en-us/developer-network/stop-and-emergency-stop-function) · [machinerysafety101](https://machinerysafety101.com/2010/09/27/emergency-stop-categories/) |
| 안전거리 | 광전자식 방호장치는 ISO 13855 로 접근속도·응답시간 기반 설치거리를 정함 — VIGENT 지연(침입→기록 1.31s, `SAFETY_REVIEW_REPORT.md:463`)은 이 계산에 넣을 수 없는 수준 | 확인 필요(ISO 13855 원문 미열람) |

권고: `docs/` 에 **"설비 연동 요구사항서"** 1장을 두고, "VIGENT 출력 = 안전 PLC 의 비안전 입력, 정지 논리는 고객 안전 PLC 책임, 비상정지 회로 비접속" 을 계약 조항으로 고정한다(현재 어느 문서에도 없음).

---

## 3. 표준/가이드 대응표

| 표준/제도 | 요구 요지(출처, 확인 2026-09-08) | 현재 대응 | 근거 |
|---|---|---|---|
| **개인정보보호법 제25조**(고정형 영상정보처리기기) | 공개 장소 설치 제한 사유(시설 안전·화재 예방 등), **안내판**(목적·장소·범위·시간·관리책임자·연락처) 의무, 임의 조작·녹음 금지, 보관기간 명시 없으면 **30일 기준 파기**(표준지침·가이드라인) — [law.go.kr 제25조](https://www.law.go.kr/LSW//lsLawLinkInfo.do?lsJoLnkSeq=900079397&lsId=011357&chrClsCd=010202&print=print) · [찾기쉬운 생활법령](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=1257&ccfNo=2&cciNo=3&cnpClsNo=3) · [PIPC 고정형 가이드라인 PDF](https://www.privacy.go.kr/cmm/fms/FileDown.do?atchFileId=ATCH_000000000873764&fileSn=2) | **부분** — 기술: 모자이크 기본 on(`config/tuning.yaml:261-266`, `privacy.py:36-37`), 30일 자동 파기(`tuning.yaml:158-159`), 저장 암호화 검사(`privacy.py:322-363`). **문서·절차: 안내판·고지문·운영관리방침·열람요청 절차 없음**(`docs/PRIVACY_POLICY_DRAFT.md` §9-10 전부 `[ ]`). ★모자이크 실패 시 **원본 저장**(D4 결정, `privacy.py:150-160`) | 사업장 내부(비공개 장소) 여부에 따라 §25 적용 범위가 달라짐 — **확인 필요(법무)** |
| 근로자참여법·근기법(감시설비 노사협의) | 사업장 감시설비 설치는 노사협의회 협의 사항 — 저장소 문서가 자체 인용(`docs/PRIVACY_POLICY_DRAFT.md` §2) | **불가(문서 없음)** — 협의록·고지 양식 없음 | 확인 필요(법무) |
| **AI 기본법**(2026-01-22 시행) | 고영향 AI = "생명·신체 안전·기본권에 중대한 영향" 영역(제2조4호, 채용·대출 등 열거형); 투명성(제31조 사전 고지), 안전성·신뢰성(제32~35조 위험관리·설명·인간 감독·**문서 5년 보관**), 과태료 3천만원 이하, **계도기간 최소 1년** — [신김 뉴스레터](https://www.shinkim.com/kor/media/newsletter/3114) · [법률신문](https://www.lawtimes.co.kr/news/articleView.html?idxno=216500) · [MS TODAY](https://www.mstoday.co.kr/news/articleView.html?idxno=99963) | **부분** — 인간 감독(승인 게이트 `safety_core.py:267`), 한계 고지(UI 푸터·detection_limits.md)는 있음. **"AI 기반 운용 사실 사전 고지" 문구·위험관리방안 문서·5년 보관 정책 없음** | ★산업안전 CCTV 가 고영향 AI 열거 영역에 **명시돼 있지 않음**(신김 요약 기준). 근로자 신체 안전에 영향 → 해당 가능성 있음 — **확인 필요(시행령 별표 원문 미열람)** |
| **KISA 지능형 CCTV 성능시험·인증** | 일반 분야(배회·침입·화재 등 10종) + 안전 분야(2024-08 8종: 무인매장·스토킹·요양병원·드론화재·치매수색·무인경비로봇·학교생활·도시철도) — [KISA 공지 2433](https://www.kisa.kr/402/form?postSeq=2433) · [KISA 성능시험인증](https://www.kisa.or.kr/1041504) · [보안뉴스 정상상황 탐지 의무화](https://www.boannews.com/news/articleView.html?idxno=145656) | **해당 분야 없음** — 산업안전(안전모·지게차) 항목이 인증 분류에 **없다**(확인 범위 내). 일반 분야 "침입·화재"로는 응시 가능성 있음 — 확인 필요 | `vigent-core/evaluator.py:8, 172, 185` 가 "KOSHA 스마트 안전장치 인증 기준 후보"·"공인 인증은 KOLAS·한국표준협회·한국스마트건설안전협회" 라 적음 — **이 인증 제도의 존재·기준(90%)을 확인하지 못했다. 근거 없으면 문구 삭제 대상**(규칙 7) |
| **KOSHA 스마트 안전장비 지원사업**(안전일터 조성지원) | 50인 미만 사업장, 사업장당 최대 4천만원·80%; 2026 관리품목 "AI 기반 인체감지시스템(고정식)" — [nsafe 공고](https://nsafe.co.kr/article/1-%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD/1/363/) · [saige 가이드](https://saige.ai/blog/smart-safety-equipment-support-program-guide/) | **확인 필요** — 관리품목 등록 요건(성능 기준·시험성적서·제조자 자격)을 확인하지 못함. 저장소에 관련 문서 0건 | 판로 관점에서 중요(경쟁사가 이 채널로 보급) |
| **IEC 62443**(산업 보안) | 자산 소유자 보안 프로그램(2-1), 시스템 요구(3-3: 접근통제·식별·감사로그·무결성 등), 구역/도관 분리 — [arXiv OT 보안 튜토리얼](https://arxiv.org/pdf/2502.14017) | **부분** — 토큰 인증·Host 검증·세션 잠금(`main.py:176-250`, `auth_session.py`, `tuning.yaml:168-172`), TLS 문서, 네트워크 하드닝 문서(`docs/edge_network_hardening.md`). **없음**: 역할 분리, 감사로그(누가 무엇을), RTSP 자격증명 평문(`SAFETY_REVIEW_REPORT.md:433` F21), 취약점 공개·패치 절차, SBOM | 인증 목표가 아니라면 3-3 FR1~FR7 자체 점검표로 대체 가능 |
| **ISO/IEC 42001**(AI 관리체계) | AI 위험관리·수명주기 통제·영향평가·모니터링·문서화 — [ISO 42001](https://www.iso.org/standard/42001) · [Microsoft 요약](https://learn.microsoft.com/en-us/compliance/regulatory/offering-iso-42001) | **부분(비공식)** — 기준선 재측정 규칙(`CLAUDE.md` 규칙 9), 한계 문서(`docs/detection_limits.md`), 측정 위생(`docs/benchmark_measurement_hygiene.md`), 가중치 매니페스트. **없음**: 모델 카드, AI 영향평가, 데이터 출처·편향 검토, 변경관리 절차 문서 | 인증 대상 아님(조직 규모) — 고객 실사 대응용 "AI 관리 요약서" 1장이면 충분 |
| **ISO 13849-1 / IEC 62061 / IEC 60204-1** | §2-2 참조 | **비대상 선언 일관** | §2-1 |
| **산안법 제164조·위험성평가 지침 제14조**(3년 보존) | §1-1 | **부분** — 감사·TBM·평가서 1095일. 증거·인식로그는 30일(개인정보 30일 관행과 충돌) | `config/tuning.yaml:158-163` 잠정값 표기 |

---

## 4. 경쟁 기준선과 격차표

### 4-1. 기준선 출처(제품 페이지에 명시된 것만, 확인 2026-09-08)

| 제품 | 페이지가 명시한 기능 | 출처 |
|---|---|---|
| Intenseye (Core AI) | 50+ 시나리오; PPE 9종(Apron·Cal Suit·Glasses·Gloves·Hard Hat·Hearing Muff·Mask·Reflective Vest·Sleeve); 차량-보행자·차량-차량·속도·차량구역; 구역(크레인·기계·인원 상한/하한); RULA/REBA 인체공학; 행동(오르기·전기접촉·군집·보행로 위반·계단난간); 하우스키핑(누수·개방문); "privacy by design"; 스코어카드·리포트; smart plug·네트워크 스피커·산업센서 연동. 모바일·다국어·온프렘·오탐피드백은 **미기재** | [intenseye.com/products/core-ai](https://www.intenseye.com/products/core-ai) · [PPE](https://www.intenseye.com/core-ai/ppe-monitoring) · [safety solutions](https://www.intenseye.com/solutions/safety) |
| Protex AI | 차량 통제·인체공학·행동·구역·PPE·하우스키핑·실시간 알림; **온프렘 비식별 처리·익명화**; 예측 분석; 단일~수백 현장; **Hardware & PLC Integration**, "Protex Signal" 경보 장치; 엣지 퍼스트. API·오탐피드백 **미기재** | [protex.ai/safety/overview](https://www.protex.ai/safety/overview) · [vehicle-control](https://www.protex.ai/safety/vehicle-control) |
| Voxel | 차량 속도·교차로·근접, 인체공학·PPE, 유출물·장애물·비상구 막힘, 현장별 파인튜닝·하이브리드 클라우드 지속학습("95%+" 는 **자사 주장, 미검증**) | [voxelai.com/solutions-safety](https://www.voxelai.com/solutions-safety) · [voxelai.com](https://www.voxelai.com/) |
| Everguard Sentri360 | CV+웨어러블+센서 융합; 낙상·미끄러짐·충돌·위험구역·열스트레스·근골격 | [everguard.ai/sentri360](https://everguard.ai/sentri360.php) · [PR](https://www.prnewswire.com/news-releases/everguard-sentri360-system-named-best-computer-vision-system-for-employee-health-and-safety-301854764.html) |
| 국내 — SAIGE SAFETY | 안전모·**안전대** 착용, 위험구역 접근, **Depth 3D 거리** | [saige 업체 비교](https://saige.ai/blog/blog-ai-cctv-vendor-comparison-2026/) · [saige 이동형 CCTV](https://saige.ai/blog/mobile-ai-cctv-hazard-detection/) |
| 국내 — 영신 온디바이스 포터블 CCTV | 침입·안전모 미착용·**쓰러짐**·화재, 플랫폼 연동 알람·영상기록·통계 리포트 | [kidd.co.kr](https://kidd.co.kr/news/244106) |
| 국내 — 경우시스테크 | 지게차 AI 영상인식 + **자동제동** + 위치인식 | [daum/AIoT 위크](https://v.daum.net/v/0t3tDWaerE) |
| 국내 — 아이브스 | IoT·AI 융복합 화재 감시 | [ivstech](https://www.ivstech.co.kr/menu.es?mid=a10309010000) |

> 국내 대형 VMS(한화비전·이노뎁·인텔리빅스 등)는 비교 페이지에 산업안전 세부 기능이 "미기재"라 기준선에 넣지 않았다.

### 4-2. 격차표 — 있음/부분/없음 + 근거

| # | 기준선 항목 | VIGENT | 근거(파일:줄) / 비고 |
|---|---|---|---|
| 1 | 다중 카메라 동시 처리 + 실측 FPS | **있음** | 실측 한계 7대·권장 5대, **카메라당 2.0 fps**, RTX 5070 Ti 기준(`benchmarks/capacity_report.md:9-13, 26-36, 59-71`). ORT 튜닝 후 재실측 전(`:18-25`). 경쟁사 fps 는 미기재라 비교 불가 |
| 2 | 보호구 세부 항목 | **부분** | 모델 직접: 안전모·조끼·마스크(`themes/safety/vision.yaml:58-59`, `config/ppe_rules.yaml:1-3` 기본 required 2종). 장갑·보안경·용접면·**안전대는 VLM 보조**(`vigent-core/ppe_check.py:33-41`), 하네스는 모델 클래스 **없음**(`docs/detection_limits.md` [C]). Intenseye 9종·SAIGE 안전대 대비 열위 |
| 3 | 위험구역 편집 UI | **있음** | 허브에서 카메라별 폴리곤 편집·저장(`themes/safety/index_hub.html:155-172, 343-344`), 브라우저 라이브뷰도 점 찍기(`static/realtime_core.js:1702-1964`), 서버 `/cameras/{cid}/zone`(`routers/cameras.py:225-235`) |
| 4 | 차량-사람 근접 + 거리 추정 | **부분** | 장비 폭 기준 단안 근사(`vigent-core/proximity.py:6-9, 102-113`), 운전자 제외(`:29-38`). **지게차 모델은 과소학습으로 기본 비활성**(`worker.py:120, 135-137`; `routers/detect.py:112-115`). 속도·역주행 없음. SAIGE Depth·Voxel 속도 대비 열위 |
| 5 | 넘어짐/쓰러짐(낙상) | **없음(2026-08-06 제거, 대체 기능 없음)** | 재도입 조건 명시(`docs/P3_BACKLOG.md:328-333`, `docs/PILOT_PROPOSAL.md` §3). 영신·Everguard 는 제공 표기. ★2026-09-09 정정: 무동작 45s 규칙(행 7)은 낙상의 **부분 대체가 아니다** — 넘어지는 순간·넘어졌다 일어남·추적 끊김을 못 잡고, 누워서 하는 작업과 구분 못 한다(FINAL-REPORT §4 문단). 비교표에서 "부분"으로 표기하지 말 것 |
| 6 | 화재/연기 | **있음(현장 재검증 대기)** | RF-DETR D-Fire 학습 mAP@50 80.13%(`vision.yaml:19-20`), 워커 발화(`worker.py` `fire_smoke` 1곳). 현장 프로파일에서 끄는 경우 있음(`worker.py:139-140`) |
| 7 | 고정 자세/움직임 없음(무동작) | **있음** | `MotionTracker` 45초 무동작→`immobility` high(`worker.py:501-503, 617-624`; `config/tuning.yaml:64-70`), 카메라별 override |
| 8 | 밀폐공간 출입 관리(인원 카운트·감시인·가스) | **없음** | 밀폐공간은 지식·체크리스트 층에만(`config/critical_controls.yaml:28-55`, `behavior.py:42-43`); 출입 인원 in/out 카운트·체류 관리 코드 없음 |
| 9 | 트래킹 기반 체류시간 | **부분** | 구역 진입 1.0초 디바운스·"체류 확정"(`tuning.yaml:239`, `worker.py:291-298`)은 있으나 **체류 시간 집계·임계(예: 10분 이상) 경보·리포트 없음** |
| 10 | 야간/열화상 | **없음(미검증)** | 열화상·IR grep 0건(`docs/camera_requirements.md` 포함). 야간은 "재연결·조명 변화 여유"로만 언급(`capacity_report.md:57`) |
| 11 | 얼굴 비식별화 | **있음(조건부)** | 모자이크(person 머리 + YuNet), 저장·전송 이미지 대상(`privacy.py:1-21, 92-149`). **실패 시 원본 저장**(D4, `:150-160`), /health 노출 |
| 12 | PLC/경광등 연동 | **부분** | HTTP 릴레이 1채널·자동 OFF(`relay.py:105-158`), Modbus 는 주석 언급만(`:7`) 구현 0. 웹훅 URL(`setup_console.py:147`). Protex "PLC Integration" 대비 열위 |
| 13 | 모바일 앱 | **없음** | 텔레그램 봇·웹훅만(`agents/dispatcher.py:4-6, 54-56`; `config/notify.example.yaml:2`). PWA/manifest 0건 |
| 14 | 다국어 | **없음** | `lang="ko"` 고정(`themes/safety/index_hub.html:1`, `console.html:2`), i18n 0건; VLM 프롬프트도 한국어 강제(`vision.yaml:105`) |
| 15 | 리포트 자동 생성 | **부분** | 위험성평가서 자동(§1 E5), 대시보드 on-demand(`dashboard.py`). 주기 생성·PDF·이메일 발송 없음 |
| 16 | 중앙 관제(다중 현장) | **없음** | `site` 는 문자열 1개(`config/site.example.yaml:5`); multi-site/tenant grep 0건. Protex "수백 현장" 대비 열위 |
| 17 | OTA / 원격 업데이트 | **없음** | `ota|auto.?update` grep 0건; 배포는 수동(`md/DEPLOYMENT.md`) |
| 18 | 오탐 피드백 학습 | **없음** | `/safety/eval` 은 **측정만**(`evaluator.py:3, 114-121`); VLM 이중확인은 있으나 라벨 저장·재학습 루프 없음(`vlm_confirm.py:1-6`). Voxel "현장 파인튜닝·지속학습" 대비 열위 |
| 19 | 감사 로그(시스템 조작 이력) | **부분** | 승인 이력만(`audit_store.py`). 설정 변경·카메라 추가·구역 수정·증거 열람 기록 없음(§1 E10) |
| 20 | 역할 기반 권한(RBAC) | **없음** | 단일 운영자·단일 토큰(`auth_session.py:8-10`; `docs/P3_BACKLOG.md:25, 65-69` 보류 결정) |
| 21 | 오프라인 설치 | **부분** | 가중치 사전 조달·`TORCH_HOME` 고정·설치 체크리스트 N-5(`deploy/SITE_CHECKLIST.md:219-226`, `md/DEPLOYMENT.md:247-303`). 그러나 **일부 화면이 CDN 의존**(`themes/safety/console.html:7-8, 403` jsdelivr; 라이브뷰 MediaPipe CDN `docs/ONBOARDING.md:112`). 대시보드·TBM 은 CDN 무의존(`dashboard.py:5`) |
| 22 | 인체공학(REBA) | **있음** | `vision.yaml:86-94`, `ergonomics.py` — 단 "확정 진단 금지" 보조(`ergonomics.py:10`) |
| 23 | 인원 밀집·단독작업 | **있음** | `crowd_density`·`lone_worker` 규칙(`data_engine.py:35-41`, `worker.py` crowd 1곳) |
| 24 | 행동 안전(흡연·휴대폰·사다리 등) | **부분(VLM)** | `behavior.py:15-54` VLM 개방형 판단 — 정확도 미측정, 로컬 VLM 은 Apple mlx 전용(`requirements-agents.txt` 주석) → **Windows 현장에서는 클라우드 키 없으면 비활성** |
| 25 | 법령 근거 자동 인용 | **있음(차별점)** | RAG + 화이트리스트 게이트(`legal_whitelist.py:1-12`, `safety_rag.py`, `data/legal/statutes.yaml`). 경쟁사 페이지에 동종 기능 미기재 |
| 26 | 재해 원인분석 보조 | **있음(보조)** | `incident.py` — 경쟁사 미기재 |

**집계**: 있음 9(1·3·6·7·11·22·23·25·26) · 부분 8(2·4·9·12·15·19·21·24) · 없음 9(5·8·10·13·14·16·17·18·20).

---

## 5. 이슈 목록

| ID | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| C-1 | **P0** | 승인 기록이 "누가"를 증명하지 못한다 — approver 자유 문자열 + 무결성 장치 없음 | `routers/safety_core.py:274, 296`; `audit_store.py:21-40`; `auth_session.py:8-10` | `audit_store.py:3-5` 가 스스로 "법적 분쟁 시 사람이 최종판단했음을 입증"이라 선언하지만, 누구나 임의 이름으로 POST 가능하고 파일을 열어 고쳐도 탐지 불가 → **증빙 주장 자체가 무너진다.** 대외 문서에 "감사추적" 을 쓰기 전 차단 | ① 승인 시 세션 사용자 id 를 서버가 채움(요청값 무시) ② 레코드마다 `prev_hash`+`sha256` 체인, 일자 파일 마감 시 루트 해시를 별도 저장(가능하면 외부 TSA/텔레그램 채널로 송신해 앵커링) ③ 증거 JPEG 해시를 이벤트 레코드에 기록 | M |
| C-2 | P1 | 조치 이력 부재 — 확인(acknowledge)만 있고 조치 내용·기한·완료 상태가 없다 | `audit_store.py:21-23`(note 미전달), `safety_core.py:296`, `:299-319` | 중처법 시행령 §4 "확인→개선" 절차 증빙 불가; 경쟁사(Intenseye 워크플로우) 대비 열위 | 이벤트별 조치 티켓(상태·담당·기한·완료 사진) 필드 추가, 감사추적 화면에 열 추가 | M |
| C-3 | P1 | 정기 보고서(월간·반기 점검) 자동 생성·PDF 없음 | `dashboard.py:1-6`; grep 0건 | 반기 점검 보고 서식을 사람이 다시 만들어야 함 — "서류 자동화" 가치 제안과 불일치(`hub.py:67`) | 월간 집계 HTML→PDF(Playwright/브라우저 인쇄) 스케줄러 + 반기 점검 서식 템플릿 | M |
| C-4 | P1 | 개인정보 운영 문서 0건 — 안내판·고지문·운영관리방침·정보주체 권리 절차·노사협의 양식 | `docs/PRIVACY_POLICY_DRAFT.md` §9-10 전부 `[ ]`; 저장소 grep | 개인정보보호법 §25 안내판은 **운영자(고객) 의무**지만 양식 없이 파일럿 진입하면 고객이 법 위반 상태로 시작 | 양식 4종(안내판·고지문·운영관리방침·열람/삭제 요청서) + 노사협의 안건서 초안 → 법무 검토 | S(초안)·L(법무) |
| C-5 | P1 | AI 기본법 대응 미착수 — 고영향 여부 미판단, "AI 운용 사실 고지" 문구·위험관리방안·5년 보관 없음 | 웹 확인(§3); 저장소에 "AI 기본법" grep 0건 | 계도기간 1년이라 즉시 제재는 낮으나, 고객 실사 질문에 답이 없음 | ①고영향 해당 여부 법무 확인 ②UI/안내판에 "AI 영상분석 운용" 고지 문구 ③위험관리방안 = 기존 detection_limits·기준선·승인게이트를 1장으로 정리 ④감사·평가서 보존을 5년으로 상향 검토 | S~M |
| C-6 | P1 | 계약서·견적서 표준 조항 미확정(기능안전 면책·오탐/미탐·데이터 소유·파기·설비연동 요건) | `docs/COMMERCIALIZATION_CHECKLIST.md:40-47` `[ ]`; `PRIVACY_POLICY_DRAFT.md` §10 마지막 항목 | 코드·UI 문구는 완비됐으나 **법적 효력이 있는 곳(계약)에 없다** | §2-2 표를 조항화한 "설비 연동 요구사항서" + 계약 부속서 초안 | S(초안) |
| C-7 | P1 | 모자이크 실패 시 원본 저장(D4) 이 법무 미검토 상태로 운영 기본값 | `privacy.py:150-160, 229-241`; `docs/PILOT_DECISIONS.md` D4 | 실패 건은 표시되지만 **원본이 디스크에 남는다** — §25 목적 외 보관 논란 소지 | 법무 결정 전까지 실패 건 자동 격리 폴더 + 짧은 보존(예 7일) 옵션 | S |
| C-8 | P1 | evaluator 의 "KOSHA 스마트 안전장치 인증 기준(90%)" 문구 근거 미확인 | `vigent-core/evaluator.py:8, 172-173, 185` | 존재를 확인 못한 인증을 UI 가 언급 → 규칙 7 위반·고객 오인 | 근거 URL 확보 못 하면 문구 삭제, "자체 측정" 만 남김 | S |
| C-9 | P2 | 안전대(하네스)·장갑·보안경 모델 클래스 없음(VLM 보조·Windows 에서 로컬 VLM 불가) | `ppe_check.py:33-41`; `detection_limits.md` [C]; `requirements-agents.txt` 주석 | 고소작업 현장 필수 항목에서 SAIGE·Intenseye 대비 열위; VLM 경로는 클라우드 키 없으면 비활성 | 하네스 데이터셋·클래스 확장 새 모델(문서가 이미 "새 모델" 로 규정) | L |
| C-10 | P2 | 지게차 검출 기본 비활성(과소학습) → 근접 기능이 사실상 꺼져 있음 | `worker.py:120, 135-137`; `routers/detect.py:112-115` | "지게차-작업자 근접" 이 제품 정의 5대 기능인데 현장 기본값에서 비활성 | LOCO 외 현장 데이터 재학습(T10b full) 후 복원 | L |
| C-11 | P2 | 낙상/쓰러짐 없음(제거) — 국내 경쟁 제품 표준 기능 | `P3_BACKLOG.md:328-333` | 영업 비교표에서 빈칸; 무동작 45초 규칙은 "장시간 정지 감지"이지 낙상 대체가 아님(★2026-09-09 정정) — "쓰러짐 감지" 표기 금지 | 재도입 조건(참조 클립·근접 카메라) 충족 전까지 "무동작 감지" 로 표기 통일 | — |
| C-12 | P2 | 체류시간·밀폐공간 출입 관리 없음 | `worker.py:291-298`; grep 0건 | 트랙 id 가 이미 있어 집계는 가능하나 기능·리포트 없음 | 구역별 트랙 체류 초 집계 + 임계 경보 + 대시보드 열 | M |
| C-13 | P2 | 모바일 앱·다국어 없음 | `dispatcher.py:4-6`; `index_hub.html:1` | 외국인 근로자 다수 현장·현장 관리자 이동 시 열위 | 단기: 텔레그램 메시지 다국어 템플릿 + 반응형 웹; 장기: PWA | S~M |
| C-14 | P2 | 중앙 관제(다중 현장)·OTA 없음 | `site.example.yaml:5`; grep 0건 | 2현장 이상 고객 확장 불가, 업데이트마다 방문 | 이벤트 원격 집계 웹훅(이미 있음)을 받는 중앙 수집기 + 서명된 업데이트 번들 | L |
| C-15 | P2 | 오탐 피드백 → 재학습 루프 없음 | `evaluator.py:3, 114-121`; `vlm_confirm.py` | 현장 튜닝이 사람 손(프로파일 편집)에 의존 | 콘솔에서 "오탐/정탐" 표시 → 라벨 JSONL 저장 → 재학습 데이터셋 자동 편입 | M |
| C-16 | P2 | RBAC·조작 감사로그 없음(IEC 62443 FR1/FR2/FR6 상당) | `auth_session.py:8-10`; §1 E10 | 안전관리자·현장 반장·열람자 구분 불가, 증거 열람 기록 없음 | 최소 2역할(admin/viewer) + 설정 변경·열람 로그 | M |
| C-17 | P2 | 오프라인 설치 부분 — 일부 화면 CDN 의존 | `console.html:7-8, 403`; `ONBOARDING.md:112` | 폐쇄망 현장에서 해당 화면 깨짐 | CDN 자산 로컬 번들(라이선스 확인 후) | S |
| C-18 | P2 | PLC 연동이 HTTP 1채널뿐(Modbus 미구현) | `relay.py:7, 70-82` | Protex "PLC Integration" 대비 열위; 경광등 외 설비 신호 불가 | Modbus TCP 코일 쓰기 채널 추가(보조 신호 경계 유지) | S~M |
| C-19 | P3 | 보존기간 잠정값(증거 30일 vs 인식로그 30일 vs 감사 3년) 법무 미확정, 발송 경보 자동 pin 이 주석 처리 | `tuning.yaml:140, 153-163` | 30일 뒤 위험성평가 빈도 근거가 사라짐(평가서는 자립) | 정책 확정 후 `auto_pin_sent_alerts` 활성 여부 결정 | S |
| C-20 | P3 | ISO/IEC 42001 식 AI 관리 문서 부재(모델 카드·영향평가) | §3 | 대기업 고객 실사 대응 지연 | 기존 문서를 모아 "AI 관리 요약서" 1장 | S |
| C-21 | P3 | TBM 서명이 체크박스(전자서명 아님) | `tbm_store.py:43-47` | 서명 증빙력 약함 | 터치 서명 이미지 또는 본인 인증 링크 | M |
| C-22 | P3 | 시간 동기(NTP) 확인 장치 없음 | `SAFETY_REVIEW_REPORT.md:94` | 이벤트 시각 신뢰성 다툼 소지 | /health 에 시스템 시간-NTP 오차 노출 | S |

---

## 6. "아예 빠져 있는 것" — 코드·문서에 흔적조차 없는 항목

| 구분 | 항목 | 확인 방법 |
|---|---|---|
| 증빙 | 해시체인·전자서명·타임스탬프(TSA)·WORM 저장 | `hash|sha256|hmac|sign` 이 audit_store/data_engine 에 0건(hmac 은 auth_session 토큰 비교에만) |
| 증빙 | 증거·기록 **열람 로그**(누가 언제 봤나) | access log 설정 0건 |
| 증빙 | 조치 티켓(상태·담당·기한·완료 증빙) | §1 E4 |
| 증빙 | 반기 점검 보고 서식·월간 리포트 스케줄·PDF 출력·이메일 발송 | grep 0건 |
| 개인정보 | 안내판·고지문·운영관리방침·열람/삭제 요청 처리 흐름·노사협의 안건서 | `docs/PRIVACY_POLICY_DRAFT.md` §9-10 미체크, 파일 0건 |
| AI 기본법 | "AI 운용 사실 고지" 문구, 위험관리방안 문서, 5년 보관 정책 | grep "AI 기본법|인공지능 기본법" 0건 |
| 계약 | 기능안전 면책·설비연동 요구사항·데이터 소유/파기 조항 초안 | 체크리스트 `[ ]` |
| 보안 | 취약점 공개·패치 절차, SBOM, 침해사고 대응 절차 | 파일 0건 |
| 기능 | 하네스·장갑 모델 클래스, 차량 속도/역주행, 체류시간, 밀폐공간 in/out 카운트, 열화상/야간 검증, 모바일 앱, 다국어, 중앙 관제, OTA, 오탐 피드백 학습, RBAC, Modbus | §4-2 |
| 운영 | 운영자 매뉴얼(현장 관리자용 한국어 사용 설명서) | `docs/` 에 설치·온보딩(개발자용)만 |
| 산재 | 산업재해조사표·아차사고 보고 양식 연계 | grep 0건 |

---

## 7. 확인 질문(판단 유보 — 답에 따라 심각도·권장이 바뀐다)

1. **제품 포지셔닝**: VIGENT 를 "안전조치 이행 **증빙** 도구" 로 팔 것인가, "보조 감시 + 서류 초안 도구" 로 팔 것인가? 전자면 C-1·C-2·C-3 이 계약 전 필수(P0/P1), 후자면 C-1 은 P1 로 내려갈 수 있다.
2. **AI 기본법 고영향 판단**: 산업안전 CCTV 를 고영향 AI 로 볼지 법무 확인이 필요하다. 시행령 별표 원문을 열람하지 못했다(확인 필요).
3. **보존기간**: 증거 30일(개인정보 관행) vs 안전 기록 3년(산안법 §164) 충돌을 어떻게 해소할 것인가 — "경보 발송 건만 3년 pin" 이 현재 구조로 가능한 절충안이다(`auto_pin_sent_alerts`).
4. **릴레이 용도**: 경광등·사이렌까지만인가, 설비 정지를 요구하는 고객이 있는가? 후자면 §2-2 요건서가 계약 전 필수다.
5. **KOSHA 인증 문구 출처**: `evaluator.py:8, 172, 185` 의 인증 제도·90% 기준을 누가 어디서 가져왔는가? 출처 없으면 삭제한다.
6. **판로**: KOSHA 스마트 안전장비 지원사업(50인 미만, 최대 4천만원) 관리품목 등록을 목표로 하는가? 그렇다면 등록 요건(시험성적서 등)을 먼저 확인해야 한다.
7. **recognition(얼굴인식) 모듈**: `PRIVACY_POLICY_DRAFT.md` §3 에 "실동작·정확도 미검증" 으로 남아 있다. 제품 범위에서 제외할 것인가? 남기면 §25 와 별개로 민감정보(생체) 이슈가 추가된다.
8. **클라우드 VLM 사용 여부**: Windows 현장에서 행동 분석(behavior.py)·PPE VLM 보조는 클라우드 키가 있어야 동작한다. 국외 이전 고지·동의를 감수하고 켤 것인가, 끈 채로 기능 표에서 뺄 것인가?
9. **외국인 근로자 비율**: 타깃 현장에 외국인 근로자가 많다면 C-13(다국어)은 P1 로 올려야 한다.

---

## 8. 출처 목록(확인 날짜 2026-09-08)

- AI 기본법: [신김 뉴스레터](https://www.shinkim.com/kor/media/newsletter/3114) · [법률신문](https://www.lawtimes.co.kr/news/articleView.html?idxno=216500) · [MS TODAY](https://www.mstoday.co.kr/news/articleView.html?idxno=99963)
- 개인정보보호법 §25: [law.go.kr](https://www.law.go.kr/LSW//lsLawLinkInfo.do?lsJoLnkSeq=900079397&lsId=011357&chrClsCd=010202&print=print) · [생활법령](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=1257&ccfNo=2&cciNo=3&cnpClsNo=3) · [PIPC 가이드라인](https://www.privacy.go.kr/cmm/fms/FileDown.do?atchFileId=ATCH_000000000873764&fileSn=2)
- 산안법 §164·위험성평가 지침: [casenote](https://casenote.kr/법령/산업안전보건법/제164조) · [law.go.kr 고시](https://www.law.go.kr/LSW//admRulInfoP.do?admRulSeq=2100000251014&chrClsCd=010201)
- 중처법 시행령 §4: [law.go.kr](https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lspttninfSeq=173767&chrClsCd=010202) · [worklaw](https://www.worklaw.co.kr/main2022/view/view.asp?bi_pidx=34823)
- KISA 지능형 CCTV: [KISA 2433](https://www.kisa.kr/402/form?postSeq=2433) · [KISA 인증](https://www.kisa.or.kr/1041504) · [보안뉴스](https://www.boannews.com/news/articleView.html?idxno=145656)
- KOSHA 스마트 안전장비: [nsafe 공고](https://nsafe.co.kr/article/1-%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD/1/363/) · [saige 가이드](https://saige.ai/blog/smart-safety-equipment-support-program-guide/)
- 기능안전: [TÜV SÜD](https://www.tuvsud.com/en-us/services/functional-safety/iso-13849-iec-62061) · [Pilz](https://www.pilz.com/en-US/support/law-standards-norms/functional-safety/en-iso-13849-1) · [IFA Report](https://www.dguv.de/medien/ifa/en/pub/rep/pdf/reports-2019/report0217e/rep0217e.pdf) · [Kollmorgen](https://www.kollmorgen.com/en-us/developer-network/stop-and-emergency-stop-function) · [machinerysafety101](https://machinerysafety101.com/2010/09/27/emergency-stop-categories/)
- 보안·AI 관리: [ISO 42001](https://www.iso.org/standard/42001) · [Microsoft ISO 42001](https://learn.microsoft.com/en-us/compliance/regulatory/offering-iso-42001) · [arXiv OT 보안](https://arxiv.org/pdf/2502.14017)
- 경쟁: [Intenseye Core AI](https://www.intenseye.com/products/core-ai) · [Protex overview](https://www.protex.ai/safety/overview) · [Voxel](https://www.voxelai.com/solutions-safety) · [Everguard](https://everguard.ai/sentri360.php) · [SAIGE 비교](https://saige.ai/blog/blog-ai-cctv-vendor-comparison-2026/) · [영신 kidd](https://kidd.co.kr/news/244106) · [경우시스테크](https://v.daum.net/v/0t3tDWaerE)

---

**산출물**: `D:\vigent_original\docs\review\08-compliance-gap.md` — **P0 1건 · P1 7건 · P2 10건 · P3 4건**(총 22건).
