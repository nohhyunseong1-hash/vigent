# 사람 시험 묶음 결과 — T0~T3 (2026-08-20 새벽)

> 방식: 관리자 PowerShell 은 사람이 실행, 검증·실측은 Claude 가 1초 폴링으로 수행.

## T0. 전제 확인 — ✅

- 워킹트리 클린 · 미푸시 0 (미추적 4건 정리: 24h 소크 원본 등 3건 커밋, 임시 스크립트 삭제)
- /health healthy · 실카 94.3ms

## T1. EFS 적용 (C3) — ⛔ **이 PC 에서 불가 (요건 발견으로 종결)**

관리자 PowerShell 에서 `cipher /e` 실행 결과 5개 폴더 전 파일 **"지원되지 않는 요청입니다"
— 0개 암호화**. **Windows 11 Home 은 EFS 미지원**(BitLocker 관리 기능도 없음).

- 판정: 실패가 아니라 **조달 요건 발견** — 현장 장비 OS 는 **Pro 이상 필수**.
- `/health` `storage_encrypted: false` 는 사실을 정직하게 반영하므로 유지.
- 문서 정정 3곳 완료(커밋 `3b945ac`): SITE_CHECKLIST N-2 · edgebox_purchase_guide OS 요건 ·
  DEPLOYMENT §0.
- ★잔여 위험 등재: `data\evidence` 에 개인영상 프레임 **11,633개 비암호화** —
  **개발 PC Pro 업그레이드 또는 증거 데이터 현장 이관 시점에 재검토(사람 결정)**.
  [2026-08-20 추가] 맥에서 회수한 evidence **4,270장**(`D:\vigent_assets\vigent_salvage_data\`)도
  같은 비암호화 상태다 — 이쪽은 **9/6 처분 결정**으로 정리 예정.
- 신규 생성한 `data\audit`·`data\tbm` 폴더는 유지(retention GROUP_DIRS 정합).
- 복구 인증서 백업(T1-4)은 EFS 자체가 불가라 **해당 없음** — 현장 장비 적용 시 필수 절차로
  SITE_CHECKLIST N-2 에 남아 있다.

## T2. 강제 kill → 자동 재기동 (B1 잔여) — ✅ **PASS**

기준값: PID 36612(09:49 기동) · healthy · pending 0 · dead 1(기존 데드레터).
사람이 `taskkill /PID 36612 /F` 실행, Claude 가 1초 폴링 실측:

| 단계 | 시각 | 소요(kill 기준) |
|---|---|---|
| 구 프로세스 소멸 확인 | 00:07:25.2 | — |
| 새 프로세스(43072) 생성 | 00:07:31.7 | +6.5s |
| 8010 재바인드 | 00:07:35.2 | **총 10.0s (설정 5s 포함, 순수 오버헤드 ~1.5s)** |
| healthy/ready (예열 포함) | 00:07:54.1 | +28.8s |
| 실카메라 자동 복귀(ok 73.7ms) | 00:07:59.1 | +33.8s |

| 합격 기준([§A 사전 선언](service_test_2026-08-17.md): 10초 이내 재바인드) | 결과 |
|---|---|
| 10초 이내 새 PID 8010 재기동 | ✅ 10.0s — **NSSM `AppRestartDelay 5000ms`(크래시 폭주 감속, 의도 설정) 포함** |
| 예열 후 healthy | ✅ +28.8s |
| 카메라 자동 복귀 | ✅ 실카 ok, 5초 안정 확인 |
| 미전송 경보 0 | ✅ pending 0 · dead 1(증가 없음) |

- ★판정 기록: 시험 지시문의 "재기동 시작 5초 이내"는 **설정값(AppRestartDelay 5s)을
  고려하지 않은 표현**이었음 — **§A 사전 선언 기준(10초)을 채택**해 PASS(사용자 결정).
  `AppRestartDelay 5000ms` 는 유지한다 — 설계 목적(폭주 감속)이 유효하고, 전체 공백
  34초의 지배 요인은 예열이라 하향의 실익이 없다.
- ★**신코드 반영 확인 4/4**: 새 PID(43072) · 워킹트리 클린 @HEAD · healthy+실카 ok ·
  로그 "ORT 세션 2개 튜닝 적용" 재출현 → **이 시점부터 G1(fire 스위치)·G5(운전자 제외)
  코드가 서비스에 반영됐다.**

## T3. 재부팅 전 상태 스냅샷 (이 커밋 시점)

| 항목 | 값 |
|---|---|
| 커밋 | 이 커밋(HEAD) — 직전 `3b945ac` |
| 서비스 | VIGENT(NSSM) Running · PID 43072 · 00:07:31 기동 |
| /health | healthy / ready · 실카 test ok ~97ms · pending 0 · dead 1 |
| 바인드 | 0.0.0.0:8010 (LAN IP 192.168.0.5) · `/health` 인증 면제 확인 |
| 시작 유형 | Automatic (Delayed) — 부팅 후 자동 기동 |

### 재부팅 후 확인(로그인 전, 폰으로)

> **폰 브라우저에서 `http://192.168.0.5:8010/health` 접속 → `"status": "healthy"` 확인**
> (부팅 직후 수 분은 503/starting 일 수 있음 — Delayed Auto + 예열 ~30초. 2~3분 뒤 재시도.)

## T3-결과. 재부팅 시험 (2026-08-20 00:26 재부팅)

| 항목 | 결과 |
|---|---|
| 서비스 자동 기동(로그인 전) | ✅ 부팅 00:26:38 → 서비스 00:31:21 기동(**부팅 +284s**, Delayed Auto 설계) |
| /health (127.0.0.1) | ✅ healthy/ready · 실카 ok 150.9ms · pending 0 · dead 1(불변) |
| LAN IP 유지 | ✅ 192.168.0.5 그대로(DHCP 변경 없음) |
| ★폰(로그인 전) /health | ⚠ **흰 화면 — 원인은 사파리가 아니라 서버 403** |

### 403 원인 (실측 확정 — 잠복 결함 발견)

PC 에서 LAN IP 로 직접 요청: `HTTP 403 · 27바이트 · {"detail":"forbidden host"}`.
서비스 등록이 uvicorn 을 `--host 0.0.0.0`(LAN 바인드)으로 띄우면서 앱 환경변수
`VIGENT_HOST` 를 안 넣어 — 앱이 **루프백 바인드로 오인**, Host 허용목록을 루프백만으로
걸어 LAN Host(192.168.0.5)를 거부했다. **서비스 등록(8/17) 이후 줄곧 있던 결함**이며
재부팅과 무관. 폰이 응답을 받았다는 사실 자체는 **로그인 전 서비스 동작의 방증**이다.

조치: `install_service.ps1` 에 `VIGENT_HOST=0.0.0.0` 추가(바인드-인식 정합).
라이브 서비스 반영은 관리자 명령 필요(본 문서 하단). LAN 라우트 방어는 설계 원안대로
토큰(`VIGENT_REQUIRE_TOKEN=1`, `/health` 면제).
백로그 등재: 폰 점검용 `/status` HTML(P3_BACKLOG B-status).

## 잔여 시험 표 (2026-08-20 갱신)

| 항목 | 상태 |
|---|---|
| ~~B1 강제 kill 재기동~~ | ✅ **완료**(본 문서 T2) |
| ~~B1 재부팅 → 로그인 전 /health~~ | ✅ **완료** — 자동 기동·healthy·카메라 복귀 확인. 폰 403 은 별도 결함으로 판명·수정(T3-결과) |
| ~~C3 저장 암호화~~ | ✅ **완결(2026-08-20)** — 현장 노트북(Win10 **Pro**)에 **BitLocker XtsAes256 적용·검증**: `FullyEncrypted/100%/On`, `/health` `storage_encrypted: true`·`bitlocker: on`. TPM 2.0 Ready 라 무인 운영 유지. 복구 키 USB 백업 확인. 개발 PC(Home)는 여전히 불가 — 잔여 위험 유지 |
| 2인 실카메라 추적(P2) | ⏸ 사람 2명 필요(`docs/test_multiperson.md`) |
| 실물 릴레이 연결(P3) | ⏸ 실물 릴레이 조달 시 |
| retention 첫 삭제 주기 승인 | ⏸ 약 17일 후 도래분 — ★맥 회수분 evidence 4,270장 처분도 **같은 자리에서 함께 결정**([salvage_recovery §3-4](salvage_recovery_2026-08-20.md)) |
| 학원 방문(G 시리즈) | ⏸ 질문지 답변·일정 확정 대기 |

### 라이브 반영·재검증 (00:40, 사람 실행 + Claude 검증)

관리자 PowerShell 로 NSSM env 갱신(아래) + `Restart-Service VIGENT`:

```powershell
& $nssm set VIGENT AppEnvironmentExtra "VIGENT_REQUIRE_TOKEN=1" "VIGENT_CAPTURE_MODE=thread" "VIGENT_HOST=0.0.0.0" "VIGENT_RESTART_CMD=sc.exe stop VIGENT & sc.exe start VIGENT"
```

| 검증 | 결과 |
|---|---|
| 재시작 | ✅ 새 PID 28920 (00:40:33) |
| LAN 경로(192.168.0.5:8010/health) | ✅ 예열 중 **503+본문**(정직한 준비중 응답) → 예열 후 **HTTP 200 · 3,566바이트 JSON** · healthy/ready · 실카 ok 72.2ms |
| 403 | **소멸** — 결함 해소 확정 |

→ 폰(사파리)에서 `http://192.168.0.5:8010/health` 재확인 시 JSON 텍스트가 표시돼야 정상.
사람 가독 페이지는 백로그 B-status.

## 최종 확인 (폰 재검증 완료)

- ✅ 폰(사파리)에서 `http://192.168.0.5:8010/health` — **"status":"healthy" JSON 전체
  정상 표시**(사람 확인). LAN 결함 수정 종결.
- 노트북 신규 설치: `install_service.ps1` 수정이 커밋돼 있어(2ded147) DEPLOYMENT
  7단계로 설치하면 **VIGENT_HOST=0.0.0.0 자동 반영** — 학원 절차서 추가 수정 불요.
- 후속 백로그: B-enc(/health privacy 한글 깨짐 — cipher CP949 추정) ·
  B-expose(/health 무인증 공개 범위 — 파일럿 수용, 상용 전 축소 검토) · B-status(HTML).

## 감사 항목 최종 현황 (site_readiness_2026-08-16 대비)

| 등급 | 항목 | 상태 |
|---|---|---|
| 🔴 B1 자동 기동 | 서비스 등록 + **kill PASS(T2) + 재부팅 PASS(T3)** | ✅ **완료** |
| 🔴 B2 /health 생존 정보 | 3단계 판정 + 단계 계측 | ✅ 완료 |
| 🔴 B3 재연결 기아 | 3단계 에스컬레이션, 4/4 복구 실측 | ✅ 완료 |
| 🔴 B4 콜드 로드 워치독 | 예열 분리, 회피 env 제거 | ✅ 완료 |
| 🔴 B5 경보 큐 | sqlite 내구 큐 + 데드레터 | ✅ 완료 |
| 🔴 B6 침입 디바운스 | 시간 기반 1.0s + G5 운전자 제외 공유 | ✅ 완료 |
| 🔴 B7 설치 문서 | Windows 재작성·실행 검증 | ✅ 완료 |
| 🔴 B8 가중치 조달 | fetch_weights + **Release 10종 백업 완비** | ✅ 완료 |
| 🟠 C1 얼굴 비식별화 | P1a 모자이크(4개 유출 경로) | ✅ 완료 |
| 🟠 C2 자동 파기 | 구현+안전장치. ★[2026-08-21 정정] 이 시점까지 **주기 실행 주체가 없어 자동이 아니었다**(안전리뷰 F6) — 서버 내 스윕 스레드 추가로 해소. 첫 주기는 목록만 남긴다(안전장치) | ✅ 완료 |
| 🟠 C3 저장 암호화 | **현장 노트북(Pro)에 BitLocker 적용·검증 완료(2026-08-20)** — `storage_encrypted: true`. 개발 PC(Home)는 불가, 잔여 위험 유지 | ✅ **완결** |
| 🟠 C4 24h 소크 | 실카메라 24h PASS + 1h 재검(Q10) PASS | ✅ 완료 |
| 🟠 C5 카메라 대수 | 한계 7/권장 5 실측 + E1 병목 특정 + Q10 −26% | ✅ 완료 |
| 🟠 C6 다인 추적 | 오프라인(P2b) 완료. **실카 2인만 잔여** | 🔸 사람 대기 |
| 🟠 C7 물리 출력 | mock 10시나리오 완료. **실물 연결만 잔여** | 🔸 조달 대기 |

**🔴 8/8 완료 · 🟠 5/7 완료 + 2건 부분(잔여는 사람·조달 대기).**

잔여 시험(사람·외부 의존): ①실카 2인 추적 ②실물 릴레이 ③retention 첫 삭제 승인(~9/6)
④학원 방문(질문지 답변 대기) ⑤현장 장비(Pro)에서 저장 암호화 적용·검증.
