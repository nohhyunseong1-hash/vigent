# main.py (464줄) + health_status.py (153줄) — 앱 조립·건강 판정

**책임 한 줄**: main = 라우터·미들웨어·startup 배선(로직 없음이 계약) / health = "지금 성한가"의 단일 진실.

**진입점·호출 관계**
- main: 인증 `_auth_guard` :218 · 호스트 제한 `_host_allowlist` :197 · 전역 예외 `_global_exception_handler` :276 · 안전망 `_install_safety_nets` :285(스레드 예외 훅) · startup 배선 :363-385(starvation_guard·alert_queue·alert_notify·retention_scheduler·dispatcher 주입).
- health: `camera_status` :44(57줄) → `overall` :108 → `build` :143 — routers/system 이 노출.

**★불변 조건**
1. **main 에 도메인 로직 없음**(라우터 분리 계약, P1-7). 로직이 생기면 계약 위반.
2. 라우터는 main 을 import 하지 않는다(✔grep 0건 — 05 #7).
3. 인증 없이 닿는 경로는 **의도된 목록뿐**(로그인 페이지·정적 등 — 그 목록을 명시적으로 확인).
4. degraded 는 **원인이 구분돼** 노출된다(뭉뚱그림 병력 — 계열 J).

**의심하며 볼 지점**
| 위치 | 질문 |
|---|---|
| :218 `_auth_guard` 26줄 | 예외 목록에 **WS·/detect/frame·정적 경로**가 어떻게 걸리나 — 우회 경로 전수 |
| :276 전역 예외 핸들러 | 무엇을 먹고 몇을 돌려주나 — 500 을 200 으로 바꾸는 경로가 없는지 |
| :285 `_install_safety_nets` | 스레드 예외 훅이 **로그만** 남기나, 스레드 재기동도 하나 — 죽은 스레드가 조용히 누적되는지(계열 B) |
| health :44 `camera_status` 57줄 | 분모: **정지/삭제된 카메라**가 어떻게 집계되나(✔유령 카메라 병력 — 계열 J 재발 확인) |
| health :108 `overall` | "카메라 0대"일 때 healthy 인가 — **0 = 통과 병력**(규칙 11) 이 여기 남아 있는지 |
| main :363-385 | startup 배선 순서 — 하나가 실패하면 나머지는 뜨나, 전체가 죽나. 실패가 /health 에 보이나 |

**알려진 함정**
- CLAUDE.md "302줄" 주장은 낡음(실측 464 — 05 #2). **로직 없음 계약이 아직 참인지** 늘어난 162줄을 직접 봐라.
- 이 세션에서 main·health 는 **깊게 읽지 않았다** — 이 노트는 다른 파일 노트보다 얕다(06 §6).
