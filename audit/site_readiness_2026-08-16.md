# VIGENT 현장 설치 준비도 감사 (2026-08-16)

> 감사 방식: 저장소 코드·설정·문서를 직접 읽어 `경로:라인` 근거를 붙였다. 읽기 전용 — 이 보고서
> 외에 어떤 파일도 수정하지 않았다. 확인 못 한 것은 §10 "미확인"으로 분리했다.
> 기준 브랜치: `fix/review-bugs` @ `2dc1da1` · `main` 대비 **197 커밋** 앞섬.
> 심각도: 🔴 설치차단 / 🟠 파일럿차단 / 🟡 파일럿중개선 / 🟢 참고

---

# 1페이지 요약

**지금 이 코드를 현장에 설치하면 안 된다.** 검출·추적 파이프라인 자체는 실카메라로 종단 검증을
마쳤고 품질 게이트(ruff·mypy·테스트·OpenAPI)도 살아 있다. 막는 것은 알고리즘이 아니라 **무인
운영에 필요한 뼈대가 없다는 것**이다. 구체적으로 다섯 가지다.

1. **재부팅하면 시스템이 안 올라온다.** Windows 서비스·작업스케줄러 등록 절차가 저장소에 없고,
   설치 문서는 맥 전용(`~/Desktop`, `python3`, `.command`, `lsof`, `pkill`)이라 그대로는 한 줄도
   실행되지 않는다.
2. **`/health`가 검출 생존을 보지 않는다.** 응답에 카메라·워커 상태가 아예 없다
   ([system.py:66-80](../vigent-core/routers/system.py#L66)). 알려진 P0(영상은 살고 검출만 죽는
   고장)가 발생해도 표준 감시 엔드포인트로는 **영원히 정상으로 보인다.**
3. **경보가 유실된다.** 알림 전송은 1회성이고 재시도·큐·데드레터가 없다
   ([dispatcher.py:111-120](../vigent-core/agents/dispatcher.py#L111)). 네트워크가 끊긴 순간의
   위험 경보는 로그에만 남고 사라진다.
4. **파일럿 유일 기능인 위험구역 침입에 디바운스가 없다.** 히스테리시스는 PPE(3프레임)·화재
   (2프레임)에만 걸려 있고 `zone_intrusion`은 목록에 없다
   ([guard.py:259](../vigent-core/agents/guard.py#L259)) — **단일 프레임 오검출이 곧 경보**다.
5. **개인정보 기술통제가 코드에 없다.** 얼굴 비식별화·저장 암호화 미구현
   ([data_engine.py:12](../vigent-core/data_engine.py#L12)), 자동 파기는 `dry_run: true`라 실제로
   아무것도 지우지 않는다 ([tuning.yaml:66](../config/tuning.yaml#L66)).

여기에 이미 알려진 **P0(세션 선점 기아)·P1(콜드 로드 12.5초 > 워치독 15초)**가 미해결로 남아 있다.

**🔴 설치차단 8건 / 🟠 파일럿차단 7건.** 🔴를 다 닫는 데 대략 **9~15 사람-일**로 추정한다(§2).
법무·개인정보 트랙은 코드 작업과 **병렬 진행 가능**하며 리드타임이 가장 길다.

**배경 정보 오류 정정 1건**: 메타프롬프트 예시의 "BYTETRACK_FRAME_RATE가 30으로 하드코딩"은
사실과 다르다. 실제 값은 **10.0**이다([guard.py:282](../vigent-core/agents/guard.py#L282)).
불일치의 방향과 크기는 §5-4에 실측 기준으로 다시 계산했다.

---

# 2. 🔴 설치 차단 항목 (이것 없이는 설치 금지)

| # | 항목 | 근거 | 합격 기준 | 작업량 |
|---|---|---|---|---|
| B1 | **재부팅 후 자동 기동 없음** | 저장소에 Windows 서비스/`schtasks` 등록물 0건. `VIGENT_RESTART_CMD` 기본값이 systemd 전제인데([STABILITY.md:103](../docs/STABILITY.md#L103)) 이 변수를 읽는 코드가 저장소에 **0건**(grep 결과 없음) | PC 강제 재부팅 후 **무조작으로** 서버+워커가 올라오고 `/health` 200 | 1~2d |
| B2 | **`/health`에 검출 생존 정보 없음** | [system.py:66-80](../vigent-core/routers/system.py#L66) 반환 키 = status·version·uptime·theme·loaded·backend·models·rfdetr_slots·llm·disk_retention·disabled_detectors. **워커·카메라·프레임 신선도 없음** | `/health`만 보고 "검출 죽음"을 판별 가능. P0 상태에서 non-ok 또는 명시 필드 | 0.5d |
| B3 | **P0 재연결 세션 선점 기아** | 실측 기록 [tapo_e2e_validation.md §8](../benchmarks/tapo_e2e_validation.md). go2rtc가 카메라 동시 세션(2)을 선점 → 워커 영구 기아, 7분간 검출 사망 | 전원 30초 차단 후 **검출 자동 복구**, 또는 최소 B2로 가시화 | 1~2d |
| B4 | **P1 콜드 로드 12.5초 > 워치독 15초** | 실측: person 8.4s + ppe 2.0s + fire_smoke 2.1s. `_HANG_TIMEOUT` 기본 15.0([worker.py:41](../vigent-core/worker.py#L41)). 현재 `VIGENT_HANG_TIMEOUT=60` 환경변수로만 회피 중(**커밋에 없음** — 재부팅 시 소실) | 기동 시 모델 예열 후 **워치독 15초로 정상 기동**. 회피 환경변수 제거 | 0.5~1d |
| B5 | **경보 전송 재시도·큐 없음** | [dispatcher.py:111-120](../vigent-core/agents/dispatcher.py#L111) `_send_webhook` 1회 POST(timeout 6)·실패 시 `sent:False` 반환하고 끝. `_send_email`도 동일([dispatcher.py:97-109](../vigent-core/agents/dispatcher.py#L97)). 저장소 전체에 retry/queue/dead-letter 구현 0건 | 전송 실패 시 **재시도 후 미전송분이 남고**, 복구 시 발송되거나 최소한 "미전송 N건"이 노출 | 1~2d |
| B6 | **위험구역 침입 단일 프레임 발화** | `HYSTERESIS_FRAMES = {"ppe_missing":3, "fire_smoke":2}`([guard.py:259](../vigent-core/agents/guard.py#L259)) — `zone_intrusion` 없음. 판정은 [worker.py:115-122](../vigent-core/worker.py#L115)에서 검출 1건으로 즉시 fired | 침입 판정에 **연속 N프레임 확인**. N은 실측으로 결정 | 0.5~1d |
| B7 | **설치 문서가 Windows에서 실행 불가** | [DEPLOYMENT.md:28](../md/DEPLOYMENT.md#L28) `~/Desktop/VIGENT/…command`, :34-35 `python3`, :72 `lsof`, :77 `pkill` — 전부 맥 전용 | 새 Windows PC에서 문서만 보고 **30분 내 설치 완료** | 1~2d |
| B8 | **가중치 조달 절차 부재** | `.gitignore:14`로 weights 제외. 자동 fetch 스크립트 0건. 현재 파일은 수동 다운로드로 확보 | 새 PC에서 **1개 명령으로** 가중치 획득+SHA 검증 | 0.5d |

**🔴 합계 추정 5.5~11d** (B1~B8, 병렬 불가분 고려 시 실질 9~15d)

---

# 3. 🟠 파일럿 차단 항목 (설치는 되나 4~8주 운영 시작 불가)

| # | 항목 | 근거 | 합격 기준 | 작업량 |
|---|---|---|---|---|
| C1 | **얼굴 비식별화 미구현** | [data_engine.py:12](../vigent-core/data_engine.py#L12) — *"얼굴 비식별화·암호화는 상용 단계 과제"* 주석만 | 증거 프레임 얼굴 처리 방식 확정·구현 또는 명시적 동의 | 2~5d |
| C2 | **자동 파기가 실제로 안 지움** | [tuning.yaml:66](../config/tuning.yaml#L66) `dry_run: true`. [retention.py:92-93](../vigent-core/retention.py#L92) `is_dry_run()` 기본 True | 보관기간 확정 → `dry_run:false` 전환 후 삭제 동작 실증 | 0.5d + 법무 |
| C3 | **저장 암호화 미구현** | 동 C1 근거. 저장소에 암호화 경로 0건 | 구현 또는 "미적용" 문서화·동의 | 2~3d |
| C4 | **실카메라 24h 소크 미실시** | `audit/` 실물: `soakmon_2026-08-11_s3edge24h`는 **파일 소스**([s3_edge_rehearsal.md §0.2](../benchmarks/s3_edge_rehearsal.md)). 실카메라 최장 30분([tapo_e2e_validation.md §8](../benchmarks/tapo_e2e_validation.md)) | 실카메라 24h 통과([SOAK_24H_CHECKLIST.md](../docs/SOAK_24H_CHECKLIST.md) 기준) | 1d(대기) |
| C5 | **카메라 대수 한계 미측정** | [INFRA_REQUIREMENTS.md §1.2](../docs/INFRA_REQUIREMENTS.md) 자체가 "미측정·벤치 필요"로 명시 | N대 동시 실측 → 견적 확정 | 1~2d |
| C6 | **다인 추적 미검증** | [pa_live_camera_verify.md §4](../benchmarks/pa_live_camera_verify.md) — 6d 미실시(2인 확보 불가) | 2인 교차 시 ID swap 측정 | 0.5d |
| C7 | **물리 출력(사이렌·릴레이) 연동 없음** | [dispatcher.py:132-134](../vigent-core/agents/dispatcher.py#L132) `safety_relay_signal`은 **로그 항목만 추가**하고 `sent:True` 반환 — 실제 하드웨어 출력 경로 없음 | 현장 요구 시 릴레이 연동, 아니면 계약서에 "화면·메신저 경보만" 명시 | 1~3d 또는 문서 |

---

# 4. 🟡 파일럿 중 개선 가능

| 항목 | 근거 | 비고 |
|---|---|---|
| 검출 캐던스 2.3fps | [pa_live_camera_verify.md §0](../benchmarks/pa_live_camera_verify.md) 실측. 백로그 PN | 추적 연관의 근본 제약이나 파일럿 기능(침입)엔 치명적이지 않음 |
| 카메라 자체 지연 1.4초 | [tapo_e2e_validation.md §3](../benchmarks/tapo_e2e_validation.md) | 기종 교체 사안. 침입 감시엔 허용 |
| YOLO 폴백 부재 | `vigent-core/weights/`에 .pt 0개 | AGPL 이슈와 함께 "폴백 포기" 결정도 유효한 선택 |
| VLM 비활성 | [vlm_confirm.py:10](../vigent-core/vlm_confirm.py#L10) mlx_vlm(Apple 전용) | 파일럿 범위(침입)에 불필요 |
| `main` 197커밋 격차 | `git rev-list --count main..HEAD` = 197 | 배포 기준선 정리 |

---

# 5. 12개 영역 상세

## 5-1. 가용성·자가복구 🔴

**(a) 현재 상태**
- 워커는 **카메라당 스레드 3개**: 메인 루프([worker.py:511](../vigent-core/worker.py#L511)), hang 감시
  ([worker.py:517](../vigent-core/worker.py#L517)), 포즈([worker.py:806](../vigent-core/worker.py#L806)).
  **프로세스 분리는 없다** — 카메라 N대가 한 프로세스·한 GIL을 공유한다([worker.py:927](../vigent-core/worker.py#L927) `self._workers[cam_id]`).
- 1차 워치독: `last_frame_ts`가 `_HANG_TIMEOUT`(기본 15s) 무진전 → `cap.release()`로 언블록 후
  재시작([worker.py:558-575](../vigent-core/worker.py#L558)).
- 2차 워치독은 **문서에만 존재**: [STABILITY.md:101-103](../docs/STABILITY.md#L101)이 `VIGENT_HANG_RESTART_S`·
  `VIGENT_HEALTH_FAILS`·`VIGENT_RESTART_CMD`를 표로 설명하는데, **이 세 변수를 읽는 코드가 저장소에 0건**이다(grep).
- 엣지 자동시작은 `VIGENT_EDGE=1` + `config/site.yaml`([main.py:333-334](../vigent-core/main.py#L333))인데
  **`config/site.yaml`이 이 저장소에 없다**(`.gitignore:34`).

**(b) 현장에서 터지는 것**
- 정전 복구·Windows 자동 업데이트 재부팅 → **아무도 서버를 켜지 않는다**. 감시 공백이 무기한.
- P0 발생 시 `/health`는 계속 200 OK를 반환하므로 외부 모니터링이 못 잡는다.
- 카메라 1대가 GIL을 오래 잡으면 다른 카메라 워커까지 hang 판정에 걸릴 수 있다(미측정).

**(c) 합격 기준** 재부팅 후 무조작 기동 + `/health`로 검출 생존 판별 가능 + 전원 30초 차단 복구
**(d) 작업량** 3~5d

## 5-2. 성능·용량 🟠

**(a)** 검출 배치 캐던스 실측 **2.3fps**([pa_live_camera_verify.md §0](../benchmarks/pa_live_camera_verify.md)).
풀세트 주기는 `worker.fullset_fps: 2`([tuning.yaml](../config/tuning.yaml)), focus 시 person만 5fps
([tuning.yaml] `hub.focus_fps: 5`). 콜드 로드 **12.5초** 실측. 스케일링은 스레드 기반(§5-1).
실측 자산: `audit/soakmon_2026-08-11_s3edge24h.{md,csv}`(파일 소스), `benchmarks/onnx_cpu_bench.md`.

**(b)** 카메라 2대째부터 무슨 일이 나는지 **아무 데이터가 없다**. 견적 불가.

**(c)** 카메라 1·2·4대에서 fps 유지율·CPU/GPU/RSS·드롭률 실측표 확보
**(d)** 1~2d

## 5-3. 검출 품질·안전 임계값 🔴(B6)

**(a)** 임계는 [tuning.yaml:43-51](../config/tuning.yaml#L43) `detect.conf`: person 0.40 · ppe 0.35 ·
forklift 0.002. 근거는 스윕 실측([person_conf_sweep.md](../benchmarks/person_conf_sweep.md)).
침입 판정은 **발끝 기준**이 맞다 — `(x1+x2)/2, y2`로 박스 하단 중앙을 폴리곤에 넣는다
([worker.py:119-121](../vigent-core/worker.py#L119)). 쿨다운 15초([tuning.yaml] `detect.cooldown_s`).
**지게차는 소비 경로에서 명시 제외**([worker.py:75-82](../vigent-core/worker.py#L75)) — `/health.disabled_detectors`로
노출된다([system.py:78](../vigent-core/routers/system.py#L78)). 가중치는 이번에 확보했으나 conf 0.002라 여전히 비활성이 옳다.

**(b)** 디바운스가 없어 **단일 프레임 오검출 = 경보**. 야간·역광 대응 코드는 없고 야간 성능은 측정된 적이 없다
([v1_field_baseline_report.md §3](../benchmarks/v1_field_baseline_report.md) "주간만").

**(c)** 침입 N프레임 확인 도입 + 야간 표본 확보 후 재측정
**(d)** 0.5~1d(디바운스) / 야간은 데이터 확보 선행

## 5-4. 다인·추적 🟠

**(a)** ByteTrack 채택 완료(`b77f097`). 스폰 임계는 person 운용 임계에 연동
([guard.py `_activation_threshold`](../vigent-core/agents/guard.py)).
**`BYTETRACK_FRAME_RATE = 10.0`**([guard.py:282](../vigent-core/agents/guard.py#L282)) — 주석 자체가
"실배포 호출주기에 맞춰 재조정 필요"라고 적혀 있다.

**★배경 정보 정정**: 값은 30이 아니라 **10.0**이다. 실제 캐던스 2.3fps 대비 **약 4.3배 높게** 설정돼
있다. `lost_track_buffer=30`([guard.py:283](../vigent-core/agents/guard.py#L283))과 조합될 때 라이브러리
내부 환산식을 코드로 확인하지 않아 **최종 유지시간이 몇 초인지는 미확인**이다. 다만 실측에서
**11.55초 부재까지 동일 ID가 복원**됐다([pa_live_camera_verify.md §2](../benchmarks/pa_live_camera_verify.md)) —
"lost 판정이 빠르게 발생한다"는 방향의 문제는 **관측되지 않았다.**

**(b)** 다인 교차 미검증(6d). ID swap이 나면 침입 인원 카운트가 흔들린다.
**(c)** 2인 교차 시 swap 0건 **(d)** 0.5d

## 5-5. 경보·알림 신뢰성 🔴(B5)

**(a)** 채널 3종(telegram·email·webhook) + log([dispatcher.py:122-140](../vigent-core/agents/dispatcher.py#L122)).
타임아웃 webhook 6s·SMTP 8s. **재시도 없음·큐 없음·데드레터 없음**(전수 grep 0건).
`delivered`는 원격 3채널 중 하나라도 성공했는지만 본다([dispatcher.py:137-139](../vigent-core/agents/dispatcher.py#L137)).
설정 파일은 `config/notify.example.yaml`만 있고 **실 설정 `config/notify.yaml`이 없다**.
웹훅 목적지 화이트리스트는 fail-closed로 동작([dispatch.py:20-24](../vigent-core/routers/dispatch.py#L20)).

**(b)** 인터넷 순단 중 발생한 침입 경보가 **영구 소실**된다. 관리자는 경보가 있었는지도 모른다.
ack(확인) 흐름은 저장소에 없다 — 경보를 누가 확인했는지 추적 불가.

**(c)** 미전송분 보존 + 복구 시 재발송 또는 "미전송 N건" 노출. 알림 지연 SLA 정의
**(d)** 1~2d

## 5-6. 개인정보·법무 🟠 (사실만 기재, 법적 판단 없음)

**없는 것**(코드·파일로 확인):
- 얼굴/신체 비식별화 구현 — [data_engine.py:12](../vigent-core/data_engine.py#L12) 주석만
- 저장 암호화 — 구현 0건
- 실제 파기 — [tuning.yaml:66](../config/tuning.yaml#L66) `dry_run: true`, [retention.py:92](../vigent-core/retention.py#L92) 기본 True
- `config/site.yaml`·`config/notify.yaml` — 저장소에 없음

**있는 것**:
- 정책 초안 [PRIVACY_POLICY_DRAFT.md](../docs/PRIVACY_POLICY_DRAFT.md)(73줄)
- 보존 정책 인프라·pin 예외(증거는 pin되면 삭제 불가, [retention.py:9](../vigent-core/retention.py#L9))
- 증거는 로컬 저장, 클라우드 VLM은 opt-in

**없는 것(문서)**: 고지·동의 양식, 노사협의 기록, 계약 면책 조항 — 저장소 내 0건

## 5-7. 보안 🟡

**(a)** 자격증명은 **평문 JSON** `data/camera_secrets.json`([camera_registry.py:18](../vigent-core/camera_registry.py#L18)),
`data/`는 gitignore. 로그·API 노출은 마스킹([camera_registry.py:3](../vigent-core/camera_registry.py#L3),
`worker.py`의 `_mask_src`·`_scrub`). **git 이력에 비밀 파일 커밋 0건**(`git log --all -- '*.env' 'data/camera_secrets*'` 결과 없음) ✅
토큰 인증([auth_session.py], `VIGENT_REQUIRE_TOKEN=1`), 브라우저 로그인+세션 쿠키+로그인 잠금
([main.py:118-140](../vigent-core/main.py#L118)), WS 인증 별도 구현(`ws_auth.ws_token_ok`).
TLS 가이드 [TLS_DEPLOYMENT.md](../docs/TLS_DEPLOYMENT.md). 포트: 8010(앱)·1984(go2rtc API, localhost)·
**8555(WebRTC 전체 바인딩)**([edge_network_hardening.md §1](../docs/edge_network_hardening.md)).

**(b)** `/health`가 무인증([system.py:14-17](../vigent-core/routers/system.py#L14) "워치독·모니터링용
(무인증 허용)") — 모델 파일명·버전·SHA·LLM 설정이 인증 없이 노출된다. 내부망 전제면 수용 가능.
평문 자격증명은 PC 물리 접근 시 즉시 노출.

**(c)** 8555 방화벽 IP 제한 실구성 + `/health` 노출 범위 결정 **(d)** 0.5d

## 5-8. 설치·배포 절차 🔴(B7·B8)

[DEPLOYMENT.md](../md/DEPLOYMENT.md) 한 줄씩 검증:

| 라인 | 내용 | Windows |
|---|---|---|
| :28 | `~/Desktop/VIGENT/VIGENT 안전엔진.command` | ❌ 파일 없음·확장자 무의미 |
| :34 | `cd ~/Desktop/VIGENT/vigent-core` | ❌ 경로 없음(실제 `D:\vigent_original`) |
| :35 | `python3 -m uvicorn` | ❌ `python3` 없음 |
| :45 | `curl … \| python3 -m json.tool` | ❌ 동일 |
| :72 | `lsof -nP -iTCP:8010` | ❌ 미존재 → `netstat -ano` |
| :77 | `pkill -f "uvicorn…"` | ❌ 미존재 → `taskkill` |

**의존성**: `requirements.txt` 버전 고정 양호(fastapi==0.137.2 등). CUDA 요구는 주석으로 명시
([requirements.txt:26-42](../requirements.txt#L26), cu130 필수·cu126 이하 sm_120 커널 없음).
**constraints.txt 참조**가 있으나 파일 존재 여부 미확인.
**CI 간극**: `runs-on: ubuntu-latest`([ci.yml:15](../.github/workflows/ci.yml#L15))인데 운용은 Windows —
경로 구분자·`cv2.imwrite` 비ASCII 경로 실패(이번 감사 중 실제 발생)·프로세스 종료 방식이 CI에서 안 잡힌다.

## 5-9. 설정·운영성 🟠

**(a)** 런타임 설정은 `data/` 우선·`config/` 시드([runtime_config.py], B2 항목). 위험구역은
UI에서 폴리곤을 그려 저장(`/zone/*`, `config/danger_zone.json` — 매 프레임 읽어 재기동 불필요
[DEPLOYMENT.md 표](../md/DEPLOYMENT.md)). 카메라 추가는 `/cameras` API + `data/cameras.json`.
로그 회전은 D그룹만 `rotate_if_large()`([retention.py:59](../vigent-core/retention.py#L59), `ops_log_max_mb: 50`).

**(b)** **현장 설정 파일이 저장소에 없다**(`config/site.yaml`) — 엣지 자동시작이 이 파일에 의존
([main.py:334](../vigent-core/main.py#L334))하는데 없으므로 **자동시작이 성립하지 않는다.**
NTP·타임존 요구사항 문서 0건 — 증거 프레임 타임스탬프가 법적 자료가 될 수 있는데 시간 동기화 절차가 없다.
운영자 매뉴얼(비개발자용) 0건. 원격 접근·업데이트 절차 0건.

**(c)** site.yaml 템플릿 + NTP·타임존 지침 + 1페이지 운영자 매뉴얼 **(d)** 1~2d

## 5-10. 관측성 🟠

**(a)** 구조화 로깅 `vlog`, 이벤트 로그 `log_event`([dispatch.py:31-33](../vigent-core/routers/dispatch.py#L31)).
워커 상태는 `/workers`·`/status`(hang·last_frame_secs_ago·slot_age_s·capture_alive
[worker.py:536-554](../vigent-core/worker.py#L536)). 모델 로드 상태는 `/health.rfdetr_slots`로 노출(F-8 대응).

**(b)** **예외를 삼키는 지점이 141곳**(`except Exception` 전수), 그중 **47곳이 `pass`로 완전 무음**.
`/health`에 워커가 없어 외부 감시 불가(B2). fps·드롭률·큐 길이 메트릭 노출 없음.
Prometheus 등 표준 메트릭 엔드포인트 없음.

**(c)** `/health`에 워커 요약 포함 + 무음 `pass` 47곳 중 안전 경로 분류·로깅 승격 **(d)** 1~2d

## 5-11. VLM/부가기능 🟡

`vlm_confirm.py:10` — mlx_vlm 미설치 시 `available=False` 폴백. Windows에서 **조용히 비활성**되며
사용자에게 드러나는 경로는 확인되지 않았다(미확인). `/health.llm`은 LLM provider만 노출하고
VLM 가용성은 별도 노출이 없다([system.py:44-49](../vigent-core/routers/system.py#L44)).
클라우드 VLM은 opt-in(F-12) — 켜면 영상이 외부로 나가므로 §5-6과 직결.
**파일럿 범위(위험구역 침입)에는 불필요** → 파일럿 차단 아님.

## 5-12. 테스트·검증 이력 🟠

**(a)** 테스트 20+ 파일, 워커·추적·존 관련도 존재(`test_worker_process_frame.py`,
`test_track_key_isolation.py`, `test_worker_zone_tile.py`, `test_hysteresis.py` 등). 게이트 4종 CI 자동.

**(b) 문서 vs 실물 대조** — §7 표 참조. 핵심: "24h 소크 통과"는 **파일 소스** 기준이고 실카메라
기록은 `audit/`에 없다. 재연결 시험 기록은 `benchmarks/tapo_e2e_validation.md`에 있으나 **결과가 실패**
(P0 발견)로 남아 있다. 다인 시험 기록은 없다(미실시로 문서에 명시됨 — 정직하게 기록돼 있음 ✅).

---

# 6. 조용한 실패 표

| 위치 | 무엇이 조용히 꺼지나 | 현장에서 어떻게 보이나 |
|---|---|---|
| [vlm_confirm.py:10](../vigent-core/vlm_confirm.py#L10) | mlx_vlm 없으면 `available=False` | **아무 표시 없음** — VLM 확인 기능이 그냥 동작 안 함 |
| [worker.py:75-82](../vigent-core/worker.py#L75) | forklift 검출기 기본 제외 | `/health.disabled_detectors`에 노출 ✅ (은폐 아님) |
| [tuning.yaml:66](../config/tuning.yaml#L66) | `dry_run:true` → 파기 안 함 | `/health.disk_retention.warnings`에 노출 ✅ |
| [dispatcher.py:97-120](../vigent-core/agents/dispatcher.py#L97) | 알림 전송 실패 | 응답에 `sent:false`만. **재발송 없음·미전송 집계 없음** |
| `vigent-core/weights/` | YOLO 폴백 파일 0개 | RF-DETR 실패 시 폴백 불가 — **선언만 있고 실체 없음** |
| 전체 141곳 `except Exception` (47곳 `pass`) | 프레임 단위 오류 삼킴 | 로그조차 없는 곳 존재 |
| [main.py:334](../vigent-core/main.py#L334) | `VIGENT_EDGE=1`인데 site.yaml 없음 | 자동시작이 **조용히 무동작** |
| [STABILITY.md:101-103](../docs/STABILITY.md#L101) | 2차 워치독 변수 3종 | **코드에 소비처 0건** — 문서만 존재 |

---

# 7. 문서 vs 실물 불일치

| 문서 주장 | 실물 | 근거 |
|---|---|---|
| 2차 워치독(`VIGENT_RESTART_CMD` 등)으로 프로세스 재기동 | **코드에 해당 변수 사용처 0건** | [STABILITY.md:101-103](../docs/STABILITY.md#L101) vs grep |
| "24h 소크 합격" | **파일 소스** 기준. 실카메라 24h 없음 | [s3_edge_rehearsal.md §0.2](../benchmarks/s3_edge_rehearsal.md) |
| 폴백 설계로 기능이 죽지 않음(CLAUDE.md 원칙) | 폴백 가중치 파일 0개 | `ls vigent-core/weights/` |
| `VIGENT_EDGE=1`로 엣지 자동시작 | `config/site.yaml` 부재 | [main.py:334](../vigent-core/main.py#L334), `.gitignore:34` |
| DEPLOYMENT.md 표준 절차 | 맥 전용 — Windows 실행 불가 | [DEPLOYMENT.md:28-79](../md/DEPLOYMENT.md#L28) |
| 정확도 기록(`md/VIGENT 정확도 측정 기록.md`) | **구모델(YOLO, 2026-07-04)** 기준. 현행은 RF-DETR v1 | 해당 문서 vs [v1_field_baseline_report.md](../benchmarks/v1_field_baseline_report.md) |
| MANIFEST "forklift 이 환경에 없음" | 2026-08-16 확보·LOADED 확인 | `weights/MANIFEST.md:86` vs 실측 |

---

# 8. 측정이 필요한 것 (코드로는 알 수 없음)

| 항목 | 왜 필요 | 측정 방법 |
|---|---|---|
| 카메라 N대 수용량 | **견적 불가** | 1·2·4대 순차 기동, fps 유지율·CPU/GPU/RSS·드롭률 기록 |
| 실카메라 24h 안정성 | 무인 운영 전제 | [SOAK_24H_CHECKLIST.md](../docs/SOAK_24H_CHECKLIST.md) 절차 |
| 야간·저조도 검출률 | 24시간 감시 판매 시 필수 | 야간 표본 확보 → dev 채점과 동일 절차 |
| 침입 디바운스 N | B6 파라미터 | 현장 오탐 로그에서 단발 오검출 지속시간 분포 |
| 카메라 기종별 지연 | 즉각 반응 기능 가부 | 시계 촬영법([camera_requirements.md](../docs/camera_requirements.md)) |
| 다인 ID swap | C6 | 2인 교차 보행 |
| GIL 경합(카메라 간 간섭) | 스레드 모델 한계 | N대 동시 부하 시 개별 워커 fps 편차 |

---

# 9. 권장 실행 순서

```
[트랙 A — 코드]                          [트랙 B — 법무·문서]  ← 병렬 가능
B2 /health 워커 노출 (0.5d)              C1 얼굴 비식별화 방침 결정
   ↓ (P0 가시화 선행)                     C2 보관기간 법무 확정
B3 P0 세션 기아 (1~2d)                   고지·동의·노사협의 양식
B4 P1 콜드 로드 예열 (0.5~1d)            계약 면책 조항
   ↓                                        ↓
B1 서비스 등록·자동기동 (1~2d)           C1~C3 구현 반영
B7 DEPLOYMENT 재작성 (1~2d)
B8 가중치 fetch (0.5d)
   ↓
B5 알림 재시도·큐 (1~2d)
B6 침입 디바운스 (0.5~1d)
   ↓
C4 실카메라 24h 소크 ← B1~B4 완료 후에만 의미 있음
C5 카메라 대수 벤치 → 견적
C6 다인 교차
   ↓
설치 → 파일럿
```

**의존 관계 핵심**: C4(24h 소크)를 B1~B4보다 먼저 하면 **무의미하다** — 자동기동·가시화·P0/P1이
없는 상태의 24시간은 현장 조건이 아니다. 반대로 트랙 B(법무)는 코드와 무관하게 **지금 시작**해야
한다(리드타임 최장).

---

# 10. 미확인 목록

| 항목 | 왜 판단 못 했나 | 확인 방법 |
|---|---|---|
| ByteTrack `lost_track_buffer` 실제 환산식 | 라이브러리(`trackers`) 내부 코드 미열람 | `trackers` 패키지 소스에서 `max_time_lost` 계산 확인 |
| `constraints.txt` 존재 | requirements.txt가 참조하나 파일 확인 안 함 | `ls constraints.txt` |
| VLM 비활성이 UI에 드러나는지 | 프론트 코드 미추적 | `available`·`vlm` 키를 소비하는 프론트 경로 grep |
| 카메라 간 GIL 간섭 실제 크기 | 다중 카메라 미실행 | §8 측정 |
| `pip-audit` 취약점 | 미설치(설치 금지 규칙 준수) | 별도 환경에서 실행 |
| 141개 예외 삼킴 중 안전 경로 비중 | 전수 분류에 시간 필요 | 각 지점을 안전/표시/부가로 3분류 |
| `/status` 엔드포인트 정확한 스펙 | 문서 참조만, 구현 미열람 | `routers/` grep |
| Windows에서 `evidence` 저장 경로·권한 | 미검증 | 실제 이벤트 발생시켜 파일 생성 확인 |
