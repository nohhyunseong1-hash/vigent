# Phase 5. 보안 및 개인정보 검토 — VIGENT

- 검토일: 2026-09-08 · 대상 커밋: `b7f49d9` (브랜치 `audit/cleanup-20260906`)
- 방식: 코드·설정·문서 정독 + 명령 실행(git 이력 검색, pip-audit). **코드 수정 없음 · 서버 기동 없음.**
- 비밀값(토큰·비밀번호·RTSP 자격증명·챗 ID)은 이 문서에 **값을 적지 않는다** — 종류·길이·파일:줄만 적는다.
- 심각도: P0(안전사고 직결) / P1(보안 침해·데이터 유실) / P2(경쟁 열위) / P3(품질). 읽지 않은 것은 "확인 필요".

---

## 0. 한 줄 요약

인증 게이트(Bearer + 세션 쿠키 + Host 허용목록 + 로그인 잠금), 자격증명 분리·마스킹, 보존 자동 삭제, 얼굴 비식별화(서버 경로), 클라우드 전송 opt-in 등 **핵심 장치는 코드로 실재하고 테스트(20개 파일)로 뒷받침된다.** 그러나 **① 토큰 1개 = 관리자 전권(역할 없음), ② TLS 는 문서만 있고 서비스 기동 코드에 없음, ③ 카메라 `source` 문자열이 무검증으로 go2rtc·OpenCV 에 전달, ④ 브라우저 경로로 들어온 증거 이미지는 비식별화 없이 저장, ⑤ 설정 변경·열람 감사로그 없음** 이 남아 있다. P0 없음, **P1 5건**.

---

## 1. 매트릭스

| 영역 | 상태 | 근거(파일:줄) |
|---|---|---|
| 인증(토큰·세션·잠금) | **있음** | `vigent-core/main.py:171-262` `_auth_guard`(Bearer 상수시간 비교 + 세션 쿠키 폴백), `auth_session.py:57-80`(IP 별 5회/15분 잠금), `ws_auth.py:23-39`(WS 핸드셰이크), 테스트 `tests/test_security_gate.py`·`test_browser_session_auth.py`·`test_ws_auth.py` |
| 인가(역할 분리) | **없음** | `auth_session.py:8-10` "단일 운영자 전제 — RBAC 는 백로그 B12". 토큰 1개가 모든 라우트(설정 변경·삭제·열람) 공통 |
| 시크릿 관리(분리·gitignore·마스킹) | **있음(부분)** | `.gitignore:2,6,21` 로 `.env`·`config/notify.yaml`·`data/` 제외 확인(`git check-ignore -v`), `camera_registry.py:17-36`(secrets 파일 분리+마스킹), `worker.py:34-35,90,699,...`(로그 마스킹), `agents/dispatcher.py:82-95`(예외 메시지 redact). **부분**: `setup_console.py:65` `webhook_url` 은 비밀로 취급 안 함, 비밀 파일 OS 권한 설정 코드 없음 |
| 네트워크(바인드·포트·TLS) | **부분** | 앱 기본 127.0.0.1(`main.py:173`), Windows 서비스 기본 `0.0.0.0`(`deploy/windows/install_service.ps1:37,166`) + `VIGENT_REQUIRE_TOKEN=1`(`:159`). go2rtc api 1984 는 127.0.0.1, rtsp 8554 비활성, webrtc 8555 전체 바인딩(`config/go2rtc.yaml:17-22`). **TLS: 문서(`docs/TLS_DEPLOYMENT.md`)만 있고 코드 0건**(grep `ssl_keyfile|--ssl|proxy_headers` → 없음; `deploy/windows/service_entry.py:95` `uvicorn.run(app, host, port)`) |
| OWASP(인젝션·업로드·경로·SSRF·CORS·에러) | **부분** | SQL 파라미터화(`alert_queue.py:98-255` 전부 `?`), 업로드 10MB 상한(`web_util.py:53-56`), theme 경로 정규식(`safety_core.py:810`), pin 경로 prefix 검증(`recognition.py:66-74`), CORS 미들웨어 없음(=동일 출처만, 기본 안전), 전역 예외는 타입명만 응답(`main.py:292-300`). **부분**: 카메라 `source` 무검증(§5-4), 본문 크기 제한은 JSON 파싱 이후에만, 일반 rate limit 없음, 역프록시 헤더 미처리 |
| 개인정보(보존·삭제·비식별화·반출·암호화·클라우드) | **부분** | 보존 자동 삭제 **실동작 확인**(`data/retention_status.json` last_run 2026-09-08 · 74건 삭제 · `data/retention/deletion_20260908.jsonl` 74줄), 서버 경로 비식별화(`worker.py:194`, `cameras.py:183,220`), 클라우드 VLM opt-in(`llm_provider.py:115`). **부분/없음**: 브라우저 경로 증거는 원본 저장(`data_engine.py:67`), 열람 기록 없음, 반출 통제·워터마크 없음, 저장 암호화는 OS 의존(검사만 `privacy.py:322-357`) |
| 감사 로그(변경·열람) | **없음(승인 이력만 있음)** | `audit_store.py` 는 "승인(acknowledge/risk_assessment)" 1종만 기록, 호출부 `safety_core.py:296` 1곳. 설정 변경 라우트(`zone.py` 4개·`cameras.py` 7개·`/site/config`·`/notify/config`)의 로그·감사 호출 **0건**(grep). 열람 로그 없음. 접속 기록은 uvicorn 표준 access 로그(NSSM stdout 회전, `install_service.ps1:147-151`)뿐 — 사용자 식별 없음 |

---

## 2. 항목별 상세

### 2-1. 인증/인가

**있는 것**
- 게이트 순서: Host 허용목록 → Bearer(`hmac.compare_digest`) → 세션 쿠키 폴백 → HTML 요청은 `/login` 리다이렉트, API 는 401 JSON (`main.py:225-249`).
- 외부 바인딩 + 무토큰 → 기동 거부(`main.py:176-183`); `VIGENT_REQUIRE_TOKEN=1` 로 로컬도 강제(`:186-191`); 로컬 무토큰은 경고 1줄(`:193-197`).
- 면제 라우트: `/health`, `/favicon.ico`, `/login`, `/logout` (`main.py:201`).
- 세션: `secrets.token_urlsafe(32)`, TTL 12h(`config/tuning.yaml:171`), 프로세스 메모리 보관(재기동 시 전부 무효).
- 로그인 잠금: 5회/15분 → 15분 잠금, IP 키(`auth_session.py:68-74`, `tuning.yaml:172-174`).
- 오픈 리다이렉트 방지 `_safe_next`(`main.py:117-122`), 테스트 `test_open_redirect_blocked`.
- WebSocket: HTTP 미들웨어가 WS scope 에 안 걸리는 문제를 `ws_auth.ws_token_ok` 로 별도 처리, 유일한 WS 라우트 `/tapo/ws` 에서 호출(`routers/tapo.py:64`).
- 프론트엔드는 토큰을 localStorage 에 저장하지 않는다(grep 결과 `boda_clean`·`vigent_field_mode` 등 UI 설정만) — 세션 쿠키 방식.

**없는 것 / 한계**
- **역할 분리 없음.** 관리자/현장관리자/열람자 구분이 없고, 토큰 1개를 아는 사람은 카메라 삭제(`DELETE /cameras/{cid}`), 알림 설정 변경(`POST /notify/config`), 워커 기동(`POST /worker/start`), 증거 열람(`/evidence/*`) 전부 가능.
- **비밀번호 정책 없음** — "비밀번호"가 아니라 운영자가 정한 토큰 1개. 길이·복잡도·주기 교체 강제 없음(현재 `.env` 의 `VIGENT_API_TOKEN` 은 64자 — 값은 기록하지 않음). 토큰 교체 = 서비스 재기동(환경변수), 개별 폐기 불가.
- **기본 계정·기본 토큰**: 하드코딩 기본값 없음(`.env.example` 은 빈 값). 다만 로컬 무토큰 모드가 기본이라 개발 PC 에서 그대로 파일럿에 쓰면 무인증(경고만 나옴).
- 세션 쿠키에 `secure` 플래그 없음(`main.py:155-156`; grep `secure=` 0건) — TLS 도입 시 함께 넣어야 한다.
- WS 인증이 `?token=` 쿼리를 허용(`ws_auth.py:33-35`) → uvicorn access 로그·프록시 로그에 토큰이 URL 로 남는다.
- 역프록시 뒤에서 `request.client.host` 가 항상 127.0.0.1 이 되면 로그인 잠금이 **전 사용자 공동 잠금**(또는 프록시 없이 X-Forwarded-For 로 우회 불가하지만 잠금 자체가 무의미) — `ProxyHeadersMiddleware`/`--proxy-headers` 미사용.
- `legal_whitelist.py` 는 인증과 무관한 **법령 인용 화이트리스트**(VLM 환각 차단, `legal_whitelist.py:1-12`)다 — 이 항목에서 보안 기능은 아니다.

### 2-2. 시크릿 관리

- gitignore 확인(`git check-ignore -v`):
  - `.env` → `.gitignore:2` ✅ · `config/notify.yaml` → `:6` ✅ · `data/camera_secrets.json` → `:21`(`data/`) ✅ · `config/site.yaml` → `:38` ✅
  - `config/security.json` 은 **추적됨** — 내용은 아웃바운드 웹훅 허용 호스트 목록뿐(비밀 없음, `config/security.json:1-10`) → 문제 없음.
  - `data/` 는 통째로 ignore 이지만 예외 없이 **119개 파일이 추적**돼 있다(`git ls-files data/` = 119 — `data/field_eval/labels/*.txt`, `data/datasets/.../POC_REPORT.md` 등 라벨·텍스트). ignore 규칙 추가 이전에 add 된 것. 비밀은 아니나 "data/ 는 안 올라간다"는 전제가 부분적으로만 참.
- 로컬 비밀 파일 현황(값 미기록):
  - `.env`: `ROBOFLOW_API_KEY`(20자), `VIGENT_API_TOKEN`(64자)
  - `config/notify.yaml`: `telegram_chat`(10자), `telegram_token`(46자), `smtp_port` 설정, 나머지 빈 값
  - `data/camera_secrets.json`: 카메라 1대(`test`), rtsp 자격증명 포함 46자
- 분리 설계: `camera_registry.upsert()` 가 원본은 `data/camera_secrets.json`, 공개 레지스트리·API 응답엔 `rtsp://***:***@host`(`camera_registry.py:114-117`). 워커는 `source_of()` 로 원본을 받음. 로그는 `_mask_src`/`_scrub`(`worker.py:34-35`, 사용처 9곳). 예외 메시지의 `scheme://user:pass@` 도 `scrub_credentials` 로 마스킹(`camera_registry.py:31-36`). 알림 채널 예외는 `dispatcher.redact_secrets`(`agents/dispatcher.py:82-95`, 테스트 `test_redact_secrets.py`).
- **누락**: `GET /notify/config` 가 `webhook_url` 을 **평문 반환**(`setup_console.py:59-70`, `_SECRET = {"telegram_token","smtp_pass"}` 에 webhook_url 없음). Slack/Discord 웹훅 URL 은 그 자체가 자격증명이다.
- **누락**: `docs/edge_network_hardening.md:135` 가 "서비스 계정만 읽기(chmod 600 상당)"을 요구하지만 `install_service.ps1`·`scripts/setup_env.py` 어디에도 `icacls`/ACL 설정 코드 없음(grep 0건). 앱 수준 암호화는 하지 않기로 결정(같은 문서 §5, 2026-08-10) — 근거는 타당하나 OS 권한 설정도 코드로 안 만들어졌다.
- 프론트 HTML 4개가 CDN 스크립트 7종 로드, **SRI(`integrity=`) 0건**, 3종은 버전 미고정(`@mediapipe/camera_utils`, `drawing_utils`, `pose` — `themes/safety/index.html:14-15`, `console.html:8`, `index_vigent.html:8-10`, `index_boda_ref.html:14-15`). 폐쇄망용 `/safety-local` 은 `/static/vendor` 사용.

#### 이력 검색 결과 (전 커밋 790개 · 브랜치 7개, `git grep -E <패턴> $(git rev-list --all)`; 값 미기록)

| 패턴 | 작업트리 파일 수 | 이력 hit(커밋×파일) | 고유 파일 | 판정 |
|---|---|---|---|---|
| 텔레그램 토큰 `\d{8,10}:[A-Za-z0-9_-]{35}` | 1 | 123 | `tests/test_redact_secrets.py`(3e6b351) | 테스트 픽스처(가짜) — 실토큰 아님 |
| `sk-…` (OpenAI) | 0 | 0 | — | 없음 |
| `AKIA…` (AWS) | 0 | 0 | — | 없음 |
| `-----BEGIN … PRIVATE KEY` | 0 | 0 | — | 없음 |
| Slack 웹훅 `hooks.slack.com/services/T…/B…/…` | 1 | 123 | `tests/test_redact_secrets.py` | 테스트 픽스처 |
| `Bearer <24자 이상>` | 0 | 0 | — | 없음 |
| `api_key\s*[=:]\s*<16자 이상>` | 0 | 0 | — | 없음 |
| `password\s*[=:]…` | 1 | 244 | `benchmarks/cvat_setup_pilot.py`(306afd2~c23e2fc) | 함수 인자명/JSON 키(`password=<변수>`) — 값 아님 |
| chat_id 숫자 | 1 | 134 | `docs/telegram_setup.md`(bd34d15) | 설명 문장("2단계 숫자를 넣는다") — 값 아님 |
| `rtsp://user:pass@` | 15 | 4,235 | 16 파일(아래) | **12개 고유 (user,pass) 쌍 — 전부 예시·픽스처로 판정** |

RTSP 16개 파일: `audit/c4_smoke_2026-09-06.md`, `config/site.example.yaml`, `docs/SOAK_24H_CHECKLIST.md`, `docs/academy_visit_ONEPAGE.md`, `docs/academy_visit_day.md`, `docs/docs_rtsp_tapo.md`, `md/DEPLOYMENT.md`, `runs/field_20260827/session_meta.json`, `tests/test_browser_intrusion_ownership.py`, `tests/test_capture_timeouts.py`, `tests/test_health_detect_alive.py`, `tests/test_worker_credential_masking.py`, `themes/safety/index_hub.html`, `tools/rtsp_test.py`, `vigent-core/camera_registry.py`, `vigent-core/ml/rtsp_test.py`(HEAD 에 없음, 59181e9~9f46f8d).
판정 근거(값 출력 없이 스크립트로 비교): 12쌍 중 비밀번호 길이 1~4자 10쌍·6자 1쌍(코드 주석)·8자 1쌍(테스트 픽스처), **어느 쌍도 로컬 비밀 파일(`.env`·`camera_secrets.json`·`notify.yaml`·`go2rtc.runtime.yaml`)의 값과 일치하지 않음.** 단, `docs/academy_visit_*.md`·`docs/docs_rtsp_tapo.md` 의 사용자명은 일반명(admin/user)이 아니어서 **실제 카메라 계정명일 가능성은 배제 못함 → 확인 질문 Q3.**

→ 결론: **토큰·API 키 실값의 이력 유출은 발견되지 않았다.** 이력 재작성이 필요한 사유는 비밀값이 아니라 **얼굴 식별 이미지·고객 설비 사진·사고 영상**(`docs/public_release_checklist.md:12-37`, `docs/FINAL_SUMMARY.md:84`, 커밋 `2a98fa9`·`b9e8289`)이며 **아직 미완**이다.

### 2-3. 네트워크

| 항목 | 현황 | 근거 |
|---|---|---|
| 앱 기본 바인드 | 127.0.0.1 | `main.py:173`, `service_entry.py:124` 기본값 |
| Windows 서비스 기본 | **0.0.0.0:8010** + `VIGENT_REQUIRE_TOKEN=1` + `VIGENT_HOST=0.0.0.0` | `install_service.ps1:37,159,166` — 외부 바인딩이지만 토큰 강제라 무인증 노출은 아님. Host 허용목록은 외부 바인딩+미지정 시 **검사 스킵**(`main.py:216-218`) |
| systemd(Linux) | 127.0.0.1 기본 | `deploy/systemd/vigent-edge.service:18` |
| go2rtc | api 127.0.0.1:1984 · rtsp 비활성 · webrtc **:8555 전체 바인딩**(ICE 성립 위해 의도적) | `config/go2rtc.yaml:16-22`, `docs/edge_network_hardening.md` §1·§1-2 |
| go2rtc 관리 API 자격증명 노출 | `/api/streams` 가 원본 URL(자격증명 포함) 반환 — localhost 고정이 유일한 방어선 | `docs/edge_network_hardening.md` §7 |
| TLS | **코드 없음.** `TLS_DEPLOYMENT.md:71` 이 `uvicorn --ssl-keyfile …` 을 안내하지만 `service_entry.py:95` 는 옵션 없이 `uvicorn.run(app, host, port)`; 역프록시 헤더 처리(`X-Forwarded-*`) 코드도 없음 | grep `ssl|proxy_headers|forwarded` → 0건 |
| RTSP 평문 | 카메라→엣지박스 RTSP 는 평문(Tapo 등 카메라 제약). 카메라망 분리·고정 IP 는 **문서 전제** | `deploy/SITE_CHECKLIST.md` N-1, `docs/edge_network_hardening.md` §2-3 |
| CORS | 미들웨어 없음 → 브라우저 교차출처 차단(기본 안전). go2rtc 는 동일 출처 중계(`/tapo/*`)로 우회 | `main.py` grep `CORSMiddleware` 0건 |
| 방화벽 안내 | `edge_network_hardening.md` §3(화이트리스트 방식) 있음. `deploy/DEPLOYMENT.md` 에는 방화벽 절 없음(grep `방화벽|firewall|netsh` 0건) | — |
| DNS-rebinding | 로컬 모드 Host 허용목록(루프백+testserver) | `main.py:210-218`, 테스트 `test_host_allowlist_*` |

### 2-4. 의존성 취약점 스캔 (실행 결과 전문)

도구: `pip-audit 2.10.1` (scratch venv `…\scratchpad\venv_sec`, 저장소 `.venv` 무변경). 첫 실행은 `requirements.txt` 한국어 주석이 cp949 로 디코드돼 `UnicodeDecodeError` — `PYTHONUTF8=1` 로 재실행.

**(a) `pip-audit -r requirements.txt`** — PyPI 해석 기준(고정 버전 그대로) · **3건 / 2패키지**

```
Name       Version ID              Fix Versions Description
torch      2.12.0  PYSEC-2025-194  2.13.0       A vulnerability classified as critical has been found in PyTorch 2.6.0. This affects the function torch.jit.script. The manipulation leads to memory corruption. It is possible to launch the attack on the local host. The exploit has been disclosed to the public and may be used.
setuptools 81.0.0  PYSEC-2026-3447 83.0.0       setuptools ... Prior to 83.0.0, FileList applied MANIFEST.in exclude/global-exclude/recursive-exclude/prune directives ... without Unicode normalization, so on macOS APFS or HFS+ an NFD file name could bypass an NFC exclusion rule and be packed into a source distribution. Fixed in 83.0.0.
setuptools 81.0.0  PYSEC-2026-3447 83.0.0       (동일 취약점 GHSA 상세 — MANIFEST.in 제외 규칙 우회로 비밀 파일이 sdist 에 포함될 수 있음)
```

**(b) `pip-audit -r requirements-agents.txt`** — 동일 3건(torch PYSEC-2025-194, setuptools PYSEC-2026-3447 ×2).

**(c) `pip-audit -r requirements-optional.txt`** — **실패**: `mlx==0.31.2` 가 PyPI(Windows)에 없어 해석 불가(`No matching distribution found for mlx==0.31.2`). Apple 전용 패키지라 Windows 배포와 무관.

**(d) 실제 `.venv` 설치본** (`.venv\Scripts\python -m pip freeze --all` 72줄 → `pip-audit -r freeze.txt --no-deps`) · **8건 / 2패키지**

```
Name       Version ID               Fix Versions Description
setuptools 65.5.0  PYSEC-2022-43012 65.5.1       ReDoS in package_index.py (malicious HTML from PyPI/custom index)
setuptools 65.5.0  PYSEC-2022-43012 65.5.1       (동일, CVE 설명 중복)
setuptools 65.5.0  PYSEC-2025-49    78.1.1       Path traversal in PackageIndex._download_url — arbitrary file write
setuptools 65.5.0  PYSEC-2025-49    78.1.1       (동일, GHSA 설명 중복)
setuptools 65.5.0  PYSEC-2026-1918  70.0.0       package_index download functions — remote code execution (command injection) via crafted URL
setuptools 65.5.0  PYSEC-2026-3447  83.0.0       MANIFEST.in exclude bypass (Unicode normalization)
setuptools 65.5.0  PYSEC-2026-3447  83.0.0       (동일 중복)
torch      2.12.0  PYSEC-2025-194   2.13.0       torch.jit.script memory corruption (local)
```

해석
- `torch 2.12.0 / PYSEC-2025-194`: `torch.jit.script` 로컬 메모리 손상. VIGENT 는 신뢰되지 않은 TorchScript 를 로드하지 않으므로(가중치는 `weights_manifest.json` SHA 검증) **실질 위험 낮음**. `requirements.txt:14` 주석대로 "보류(P0-2b)" 상태 — 근거를 이 문서에 기록.
- `setuptools 65.5.0`(`.venv` 실제) vs `81.0.0`(해석): `.venv` 는 Python 3.11 번들 setuptools 그대로. 취약점은 전부 `package_index`(easy_install 경로)·sdist 빌드 시점 것이라 **런타임 공격면 아님**. 다만 `pip install` 로 신뢰 안 되는 인덱스를 쓰지 않는 한 무해. 83.0.0 으로 올리는 것은 비용이 거의 없다.
- fastapi 0.137.2 · uvicorn 0.23.2 · requests 2.33.0 · Pillow 12.3.0 · python-dotenv 1.2.2 · PyYAML 6.0.3 · websockets 16.0 · numpy 2.4.6 · opencv 4.13.0.92 · onnxruntime 1.27.0 · rfdetr 1.8.0: **알려진 취약점 0건**(이번 DB 기준).
- npm 없음(순수 HTML/JS + CDN) — CDN·SRI 는 §2-2 참고.

### 2-5. OWASP 웹/API

| 항목 | 상태 | 근거 |
|---|---|---|
| SQL 인젝션 | ✅ 없음 | sqlite 사용처 `alert_queue.py` 단일, 모든 쿼리 파라미터 바인딩(`:98,115,140-150,196,214-255`). `execute(f"` / `% (` 조립 0건 |
| 파일 업로드 | ✅ 부분 | data URL 만 수용, base64 길이로 10MB 사전 차단(`web_util.py:53-56`, `tuning.yaml:167-168`, 테스트 `test_web_util_upload_limit.py`). `cv2.imdecode` 실패 시 None. **단** `data_engine._save_frame()`(`:52-67`)은 자체 정규식으로 base64 를 **디코드 검증 없이 `.jpg` 로 기록** — `recognition.py:40-43` 는 decode 없이 바로 저장 경로로 감(크기 제한 미적용 가능성 — 확인 질문 Q5) |
| 본문 크기 | ⚠ 부분 | uvicorn/FastAPI 는 기본 본문 상한이 없어 10MB 검사 전에 JSON 파싱으로 메모리 소비. 역프록시(`client_max_body_size`) 전제인데 프록시가 없다 |
| 경로 순회 | ✅ | `theme` 정규식 `^[a-z0-9_-]+$`(`safety_core.py:810`), pin 경로 `..`/절대경로/드라이브 차단 + prefix 강제(`recognition.py:66-74`), `/static` `follow_symlink` 배포 기본 False(`main.py:611-616`), 테스트 `test_scribe_path_traversal.py`. `safe_rule` 정제(`data_engine.py:59`) |
| SSRF / 임의 소스 | ❌ **없음** | `POST /cameras`·`POST /worker/start` 의 `source` 가 **아무 검증 없이** 저장되고(`camera_registry.py:114-116`, `safety_core.py:333-344`) ① `cv2.VideoCapture(source)` 로 열림(`worker.py:77-87` — 로컬 파일 경로·`http://` 내부 주소 포함) ② go2rtc 에 `src=<그대로>` 로 등록(`cameras.py:35-36`, `tapo.py:41-43`). go2rtc 는 `exec:` 등 명령 실행형 소스 스킴을 지원하는 것으로 알려져 있어 **인증 통과자가 임의 명령 실행에 이를 수 있음(실행 검증은 하지 않음 — 확인 필요)**. `/cameras/{id}/test` 도 같은 source 로 1프레임 시도(`cameras.py:188-222`) → 내부망 스캔 오라클. WS `?src=` 는 등록 카메라 id 만 허용(`tapo.py:14-26`)이라 오픈 프록시는 막혀 있음 |
| 아웃바운드 웹훅 SSRF | ✅ | 허용 호스트 목록(`config/security.json`) — 미등재 403(주석 기준; dispatcher 구현부는 이번에 정독 안 함 → 확인 필요) |
| CORS | ✅ | 미들웨어 없음(동일 출처만) |
| 에러 메시지 | ✅ | 전역 500 은 `type(exc).__name__` 만(`main.py:292-300`), `/health` 오류는 `_strip_paths`(`system.py:30-33`) |
| Rate limit | ⚠ | 로그인 잠금만. 일반 API·`/detect/frame`(추론 비용) 제한 없음 |
| WebSocket | ✅ | `ws_auth.ws_token_ok` — 쿼리 토큰은 로그 노출(§2-1) |
| CSRF | ✅ 부분 | 세션 쿠키 `SameSite=Lax`(`main.py:155`) → 교차 사이트 POST 차단. Bearer 경로는 CSRF 무관 |
| 데모 주입 API | ⚠ | `POST /safety/demo/seed`(`safety_core.py:691`) 운영 게이트 없음(`demo.py` 에 환경변수 게이트 없음) — SAFETY_REVIEW F16 그대로 |

### 2-6. 개인정보(영상정보처리기기 운영)

| 항목 | 상태 | 근거 |
|---|---|---|
| 보관기간·자동 삭제 | ✅ **코드로 구현·실동작** | `tuning.yaml:127-165`(evidence 30d·recognition 30d·audit/tbm/risk 1095d·field_eval 365d, `dry_run: false`, `auto_sweep: true` 24h). `retention_scheduler.py` 서버 내 스레드, `retention.py:136-170` 삭제 허용 루트 화이트리스트, `:172-188` 첫 주기 보류, `:198-251` pin 예외(`data/retention/pinned.json`). **실측**: `data/retention_status.json` last_run `2026-09-08T21:19:40` · `armed_with_candidates: true` · `deleted_count: 74`(evidence 70 + recognition 4) · 삭제 감사 `data/retention/deletion_20260908.jsonl` 74줄. ※ 상태 파일 위치는 `data/retention_status.json`(과제문의 `data/retention/status.json` 아님) |
| 접근 기록(누가·언제·무엇을 봤는가) | ❌ **없음** | `audit_store.py` 는 승인 이력만(`record()` 필드: event_ts/rule/action/approver/site). `/evidence/*` 정적 서빙(`main.py:621`)·`/recognition/log`·`/cameras/{id}/snapshot` 열람 기록 없음. uvicorn access 로그는 IP·경로만(사용자 식별 불가). `data/audit/` 현재 파일 0개 |
| 얼굴 비식별화 | ✅ 부분 | `privacy.py:92-160` person 박스 머리 `head_ratio` 0.30 모자이크 + YuNet. 적용처: 워커 증거(`worker.py:194`), 스냅샷(`cameras.py:183`), 연결테스트(`:220`), 클라우드 전송 직전(`llm_provider.py:127`). 실패 시 **원본 저장 + `privacy_failed` 꼬리표**(D4, `worker.py:198`, `data_engine.py:172-173`) + `/health.privacy` 노출(`privacy.py:229-241`). **미적용**: 실시간 프레임(설계 결정, `privacy.py:7-9`) · **브라우저 경로 증거**(`zone.py:100-101`, `recognition.py:40-43`, `safety_core.py:619-629,660-663,767-770` → `data_engine._save_frame():67` 원본 바이트 그대로 기록, `anonymize_faces` 호출 0건) · 학습용 수집 `VIGENT_COLLECT=1`(`worker.py:985-990` 원본 imwrite, SAFETY_REVIEW F17 그대로) |
| 영상 반출 통제 | ❌ 없음 | 다운로드 라우트는 `/recognition/log/download`(CSV, `recognition.py:51`)뿐이지만 `/evidence/<날짜>/<파일>.jpg` 는 인증만 통과하면 누구나 URL 로 내려받음. 워터마크·반출 승인·반출 로그 없음(grep `watermark|반출|export` 0건) |
| 안내판·고지 | 문서 전제 | `docs/PRIVACY_POLICY_DRAFT.md` §2·§10(안내판·취업규칙·노사협의 체크리스트). 코드 관여 없음(당연) |
| 저장 폴더 암호화 | OS 의존 + 검사 | `privacy.py:265-357` EFS(`cipher`)·BitLocker(관리자 필요) 상태를 `/health.privacy.storage_encrypted` 로 노출. `SITE_CHECKLIST.md` N-2 "Pro 이상 필수"(Home 은 EFS/BitLocker 불가 실측). 앱이 강제하지는 않음 |
| 클라우드 전송 | ✅ opt-in 이중 게이트 | `llm_provider.reason_vision()`: `VIGENT_CLOUD_VLM=1` **and** `OPENAI_API_KEY` 둘 다 있어야 전송(`:115`), 전송 전 비식별화(person 박스 없이 YuNet 만). 호출부 `incident.py:57`, `ml/vlm_risk_summary.py:180`, `safety_core.py:134`. 현재 `.env` 에 `OPENAI_API_KEY`·`VIGENT_CLOUD_VLM` **없음** → 전송 경로 비활성 |
| `/health` 무인증 노출 | ⚠ | 버전·모델 SHA·카메라별 상태·privacy 실패 카운트·retention 경고(`system.py:190-215`). 비밀은 없으나 정찰 정보 |

**문서 불일치**: `docs/PRIVACY_POLICY_DRAFT.md` §5·§6·§9 가 "보관기간 자동 파기 **미구현**", "얼굴 비식별화 **미구현**", "저장 암호화 미구현"이라고 적혀 있으나 앞 두 개는 **구현·동작 중**이다(위 근거). 고객·심사에 보여줄 문서가 현재 코드보다 나쁘게 서술돼 있다.

### 2-7. 감사 로그(설정 변경·열람)

- 호출부 grep: `audit_store.record()` 호출 **1곳**(`safety_core.py:296`, 승인 라우트). `approver` 는 요청 본문의 자유 문자열(기본 "안전관리자") — 인증 주체와 결합되지 않아 위조 가능.
- 변경 라우트에 로그·감사 없음: `zone.py`(4 POST, 로그 호출 0), `cameras.py`(7 변경 라우트, 로그는 go2rtc 프로세스 관리 4줄뿐 `:348-422`), `system.py`(변경 라우트 0), `safety_core.py` `/site/config`·`/notify/config`(`:734-746` → `setup_console.write_site/write_notify` 에 로그 0), `/worker/start`, `/recognition/pin|unpin`, 튜닝 변경(파일 직접 편집).
- 보존 삭제는 감사됨(`retention.py:253` `_write_deletion_audit` → `data/retention/deletion_*.jsonl`).
- 결론: **"누가·언제·무엇을 바꿨나/봤나"는 재구성 불가.** 단일 토큰 구조라 "누가"는 기록해도 한 사람으로만 나온다 — RBAC 와 묶인 문제.

### 2-8. 기존 검토 대비 현재 상태

| 출처 | 항목 | 현재 |
|---|---|---|
| `SAFETY_REVIEW_REPORT.md` F16 | 데모 주입 API 운영 비활성 권장 | **미조치**(`safety_core.py:691`, 게이트 없음) |
| 같은 문서 F17 | `VIGENT_COLLECT=1` 원본 저장 | **미조치**(`worker.py:990`) — 기본 off |
| 같은 문서 §4 하드코딩 표 | 알림 토큰 코드 밖 | ✅ 유지 |
| `docs/edge_network_hardening.md` §1·§1-2·§4·§6 | go2rtc 1984 localhost·8554 비활성·토큰 상시 | ✅ 코드/설정 일치(`go2rtc.yaml`, `install_service.ps1:159`) |
| 같은 문서 §5 | 비밀 파일 OS 권한 제한 | ❌ 코드 없음 |
| `docs/public_release_checklist.md` ⛔ | 이력 재작성(얼굴 9장·설비 24장·영상 9개) | ❌ **미완**(`FINAL_SUMMARY.md:27,84`) — 저장소 비공개 상태로 보류 |
| `docs/CODE_REVIEW.md` 모듈 8 M8-4 | 개인정보 추정 함수 삭제 | `docs/CODE_REVIEW.md` 에서 "M8-4" 문자열 **미발견**(FINAL_SUMMARY:90 에 M8-4(a) 만 언급) → 확인 필요 Q6 |
| `docs/FINAL_SUMMARY.md` §6-3 | 이력 재작성 | 위와 동일, 미완 |

---

## 3. 이슈 목록

| # | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| S-1 | **P1** | 카메라 `source` 무검증 → go2rtc·OpenCV 에 임의 스킴/경로 전달 | `camera_registry.py:114-116`, `cameras.py:35-36,188-222`, `tapo.py:41-43`, `safety_core.py:333-344`, `worker.py:77-87` | 토큰 보유자(또는 로컬 무토큰 모드)가 로컬 파일 열람·내부망 스캔, go2rtc `exec:` 류 소스로 **명령 실행 가능성**(미검증) | 허용 스킴 화이트리스트(`rtsp://`, `rtsps://`, 정수 웹캠, 허용 디렉터리 내 파일만), go2rtc 등록 전 스킴 재검증, `/cameras/{id}/test` 는 사설 IP 대역만 | S |
| S-2 | **P1** | 브라우저 경로 증거 이미지 비식별화 미적용 | `data_engine.py:52-67`, `zone.py:100-101`, `recognition.py:40-43`, `safety_core.py:619-629,660-663,767-770` | 브라우저 파이프라인(coco-ssd)이 보낸 프레임은 얼굴 원본으로 `data/evidence` 에 저장·`/evidence` 로 서빙 — "증거는 비식별화된다"는 문서·헬스 지표와 불일치 | `_save_frame` 진입부에서 `decode_data_url` → `privacy.anonymize_faces` → 재인코딩(실패 시 `privacy_failed` 꼬리표 동일 적용) | S |
| S-3 | **P1** | 토큰 1개 = 전권, 역할·개별 폐기·만료 없음 | `auth_session.py:8-10`, `main.py:171,201-249` | 유출 1건이 관리자 전권 유출; 퇴사·교체 시 전원 재발급; 열람자에게도 삭제·설정 권한 | 최소 2역할(admin/viewer) — 토큰 2개 또는 사용자 파일(해시) + 라우트별 요구 역할 데코레이터, 세션 저장 영속화 | M |
| S-4 | **P1** | TLS 코드 미지원(문서만), 세션 쿠키 `secure` 없음, WS 토큰 쿼리 노출 | `service_entry.py:95`, `main.py:155-156`, `ws_auth.py:33-35`, `TLS_DEPLOYMENT.md:71` | LAN 에서 토큰·세션·증거 이미지 평문. 서비스 기본이 0.0.0.0 이라 조합 위험 | `service_entry.py` 에 `VIGENT_SSL_CERT/KEY` 옵션 → `uvicorn.run(ssl_certfile=…)`, TLS 시 `secure=True`, 역프록시 시 `proxy_headers=True, forwarded_allow_ips`, WS 는 쿠키/헤더만 허용 | M |
| S-5 | **P1** | git 이력에 얼굴 식별 이미지·고객 설비 사진·사고 영상 잔존(재작성 미완) | `public_release_checklist.md:12-37`, `FINAL_SUMMARY.md:84`, 커밋 `2a98fa9`·`b9e8289` | 저장소 공개·외부 이관·협력사 클론 시 개인영상정보 유출 | 외부 이관 전 `git filter-repo` + 원격 강제 갱신 + 협업자 재클론(체크리스트 그대로) | M |
| S-6 | P2 | 설정 변경·열람 감사로그 없음, 승인자 자유 문자열 | `audit_store.py:21-40`, `zone.py`·`cameras.py`·`setup_console.py` 로그 0건 | 개인영상정보 접근기록 요구 대응 불가, 오조작 추적 불가 | 미들웨어에서 변경 메서드(POST/PUT/DELETE)+대상 경로+주체(세션 id/역할)+시각을 `data/audit/access_*.jsonl` 로; `/evidence` 열람도 기록 | M |
| S-7 | P2 | `GET /notify/config` 가 `webhook_url` 평문 반환 | `setup_console.py:59-70` | 인증 통과자 누구나 Slack/Discord 웹훅 비밀 획득 → 위장 경보 발송 | `_SECRET` 에 `webhook_url` 추가(설정됨 여부만) | S |
| S-8 | P2 | 비밀 파일 OS 권한 미설정(문서만) | `edge_network_hardening.md:135` vs `install_service.ps1`(icacls 0건) | 같은 PC 의 다른 계정이 `.env`·`camera_secrets.json`·`notify.yaml` 읽기 | `install_service.ps1` 에 `icacls … /inheritance:r /grant:r <서비스계정>:R` 추가 + 검증 | S |
| S-9 | P2 | CDN 스크립트 SRI 없음·3종 버전 미고정 | `themes/safety/index.html:14-15` 외 4파일 | CDN 변조/버전 드리프트 시 대시보드 JS 공급망 위험(대시보드는 카메라 프레임을 다룸) | 버전 고정 + `integrity`·`crossorigin`, 또는 `/safety-local`(vendor) 를 기본으로 | S |
| S-10 | P2 | 본문 크기 상한·일반 rate limit 없음 | `web_util.py:53-56`(파싱 후 검사), `main.py` 미들웨어 | 대용량 JSON·추론 라우트 반복 호출로 메모리/GPU 고갈 | Content-Length 검사 미들웨어(예: 16MB), 추론 라우트 토큰당 초당 제한 | S |
| S-11 | P2 | 역프록시 헤더 미처리 → 로그인 잠금이 IP 단위로 오작동 | `main.py:130`, `auth_session.py:68-74` | 프록시 뒤에서 한 사람의 실패가 전원 잠금(가용성) | S-4 와 함께 처리 | S |
| S-12 | P2 | `VIGENT_COLLECT=1` 학습 수집 원본 저장 (F17) | `worker.py:985-990` | 켜는 순간 개인영상 원본 누적, 보존 그룹 밖 | 수집 프레임도 `anonymize_faces` 경유 또는 수집 디렉터리를 retention 그룹에 편입 | S |
| S-13 | P2 | 영상 반출 통제·워터마크 없음 | `main.py:621`, `recognition.py:51` | 증거 이미지가 추적 없이 유출 가능 | 반출 라우트 단일화(사유 기록·워터마크·역할 admin) | M |
| S-14 | P2 | 의존성: `.venv` setuptools 65.5.0(4건), torch 2.12.0(1건) | §2-4 | 런타임 공격면은 아님(빌드·easy_install 경로) | `setuptools>=83` 로 상향(무비용), torch 는 2.13 검증 후 | S |
| S-15 | P3 | `POST /safety/demo/seed` 운영 게이트 없음 (F16) | `safety_core.py:691` | 가짜 사고를 이벤트 로그에 주입 | `VIGENT_DEMO=1` 게이트 | S |
| S-16 | P3 | `PRIVACY_POLICY_DRAFT.md` 가 구현된 기능을 "미구현"으로 서술 | 문서 §5·§6·§9 | 대외 신뢰 손해(실제보다 나쁘게 보임), 규칙 9 위반 | 현재 코드 기준으로 갱신(보존 30/1095일·D4 정책·retention 상태 파일) | S |
| S-17 | P3 | `data/` 통째 ignore 인데 119개 파일 추적 중 | `git ls-files data/` | "data/ 는 안 올라간다" 전제 오해 | 라벨 텍스트를 `data/field_eval/` 예외로 명시하거나 `benchmarks/` 로 이동 | S |
| S-18 | P3 | `/health` 무인증 정찰 정보(모델 SHA·카메라 상태·privacy 실패) | `system.py:190-215`, `main.py:201` | 낮음(내부망) | 워치독 필요 최소 필드만 무인증, 상세는 인증 | S |

P0: 0건 · **P1: 5건**(S-1~S-5) · P2: 9건 · P3: 4건.

---

## 4. 경쟁 상용 제품(VMS·산업안전 AI CCTV) 대비 격차

| 기능 | 상용 제품 일반 수준(추정/미검증 — 특정 제품 실측 아님) | VIGENT 현재 | 격차 |
|---|---|---|---|
| RBAC | 관리자/운영자/열람자 + 카메라·구역 단위 권한 | 단일 토큰, 역할 없음 | 큼 (S-3) |
| SSO / 디렉터리 연동 | AD/LDAP/SAML/OIDC | 없음 | 큼 — 파일럿 단계에선 후순위 |
| 감사로그 | 로그인·설정 변경·영상 열람·반출 전부 사용자별 기록, 변조 방지 | 승인 이력 1종 + 삭제 이력 | 큼 (S-6) |
| 전송 암호화 | HTTPS 기본, 카메라 SRTP/RTSPS 옵션 | 문서만 | 중 (S-4) |
| 저장 암호화 | 앱 레벨 또는 OS 볼륨 암호화 + 키 관리 | OS 의존 + 상태 검사 | 중 — 파일럿엔 N-2 로 수용 가능 |
| 비식별화 | 실시간·저장 모두 마스킹 옵션, 반출 시 강제 | 저장·전송 경로(서버) 마스킹, 브라우저 경로·반출 미적용 | 중 (S-2, S-13) |
| 보존 정책 | 그룹별 기간·법적 보류(legal hold)·삭제 증적 | 그룹별 기간·pin·삭제 증적 | **작음** — 이 항목은 동등 |
| 반출 통제 | 승인 워크플로·워터마크·반출 로그 | 없음 | 중 (S-13) |

---

## 5. 확인 질문

1. **Q1 (S-1)** go2rtc 배포본(v1.9.14 win64, `b72242d`)에서 `exec:`·`ffmpeg:` 소스 스킴이 실제로 활성인가? 실행 검증은 하지 않았다 — 실행 검증(고립된 환경에서 `src=exec:...` 등록 시도) 후 S-1 심각도를 확정하고 싶다.
2. **Q2 (S-3)** 파일럿 현장의 실제 이용자는 몇 명·어떤 역할인가(안전관리자 1인 vs 현장관리자+열람자)? 1인이면 S-3 는 P2 로 낮출 수 있다.
3. **Q3 (이력)** `docs/academy_visit_day.md:134`·`docs/academy_visit_ONEPAGE.md:36`·`docs/docs_rtsp_tapo.md:12`·`tools/rtsp_test.py:7-47` 의 RTSP 사용자명(일반명 아님)은 **예시**인가, 실제 카메라 계정인가? 비밀번호는 로컬 비밀 파일과 불일치했지만, 실제 계정명이면 회전 권장.
4. **Q4 (S-4)** 파일럿 배포는 역프록시(Caddy/nginx) 를 둘 계획인가, uvicorn 직접 TLS 인가? 답에 따라 `service_entry.py` 수정 범위가 달라진다.
5. **Q5 (S-2)** `recognition.py:40-43` 경로는 `decode_data_url`(10MB 검사)을 거치지 않고 `_save_frame` 으로 가는 것으로 읽었다 — 프론트가 이 라우트에 이미지를 실제로 보내는지(`realtime_core.js` 호출부 미정독) 확인 필요.
6. **Q6** `docs/CODE_REVIEW.md` 에 "M8-4 개인정보 추정 함수 삭제" 항목이 없다(grep 0건). 다른 문서(`CODE_REVIEW_AZ.md`?)에 있는지, 해당 함수가 무엇이었는지 알려주면 삭제 여부를 코드로 확인하겠다.
7. **Q7 (S-8)** 엣지박스 서비스 계정은 LocalSystem 인가 전용 계정인가? icacls 규칙의 대상이 달라진다.
8. **Q8 (아웃바운드 SSRF)** `config/security.json` 허용 호스트 검사가 `agents/dispatcher.py` 에서 실제로 강제되는지 이번엔 정독하지 않았다 — 확인 필요.

---

## 6. 재현 명령(값 출력 없음)

```
git check-ignore -v .env config/notify.yaml data/camera_secrets.json config/security.json
git ls-files data/ | wc -l                                  # 119
git grep -I -l -E 'rtsp://[^:/@[:space:]*]+:[^@[:space:]*]+@' $(git rev-list --all) -- . ':!*.svg' | wc -l   # 4235
PYTHONUTF8=1 pip-audit -r requirements.txt --desc on
.venv\Scripts\python -m pip freeze --all > freeze.txt && PYTHONUTF8=1 pip-audit -r freeze.txt --no-deps
python -c "import json;d=json.load(open('data/retention_status.json'));print(d['last_run'],d['deleted_count'])"
```

---

**산출물**: `D:\vigent_original\docs\review\05-security-privacy.md` — **P0 0건 · P1 5건**(P2 9 · P3 4).
