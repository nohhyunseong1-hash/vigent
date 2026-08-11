# VIGENT 운영·배포 절차 (표준)

> 서버 기동·확인·종료·재기동의 **단일 표준**. 2026-07-13 작성 —
> "코드를 고쳤는데 화면에 반영이 안 된다", "서버가 여러 개 떠 있다" 로 헤맨 절차를 문서화한다.

---

## 0. 대전제 — ★ `--reload` 가 없다

표준 기동은 **`--reload` 없이** 뜬다. 즉 **파이썬 코드(`.py`)·설정(`tuning.yaml` 등)을 고쳐도
이미 떠 있는 서버에는 반영되지 않는다.** 반드시 **종료 후 재기동**해야 한다.

| 무엇을 고쳤나 | 재기동 필요? |
|---|---|
| `vigent-core/**/*.py` (main·guard·incident·rig_monitor 등) | **필요** |
| `config/*.yaml`(tuning 등), `themes/*/vision.yaml` | **필요** (tuning `_CACHE` 는 프로세스당 1회 로드 — F-6 실제 사고) |
| `vigent-core/static/*.js`, 프론트 HTML | 브라우저 **강력 새로고침**(⇧⌘R)이면 됨 |
| `config/danger_zone.json` (화면서 그린 구역) | 불필요(매 프레임 읽음) |

> 과거 사고: T14-F 임계를 고쳤으나 **서버 미재시작으로 ~9시간 라이브 미적용**(FINDINGS F-6).

---

## 1. 표준 기동

**방법 A (권장·더블클릭)**
```
~/Desktop/VIGENT/VIGENT 안전엔진.command
```
- 이미 8010이 살아있으면 **새로 띄우지 않고 페이지만 연다**(좀비 방지 내장).

**방법 B (터미널·수동)**
```bash
cd ~/Desktop/VIGENT/vigent-core
python3 -m uvicorn main:app --host 127.0.0.1 --port 8010
```
- `cd vigent-core` **필수**. 다른 경로에서 띄우면 가중치 상대경로가 깨진다(F-8 사고 원인).
- 백그라운드로 띄울 때만 `&` + 로그 리다이렉트: `... --port 8010 > /tmp/vigent.log 2>&1 &`

---

## 2. 기동 확인 (이 3가지를 반드시 본다)

```bash
curl -s http://127.0.0.1:8010/health | python3 -m json.tool
```

**① `status: "ok"` · `loaded: true`**

**② `rfdetr_slots` — 커스텀 가중치 3슬롯이 전부 `LOADED`** (person 은 COCO 사전학습이라 목록에 없음)
```
forklift    rfdetr  LOADED
fire_smoke  rfdetr  LOADED
ppe         rfdetr  LOADED
```
- 하나라도 `MISSING` / `MISSING_FALLBACK` 이면 **가중치 미탑재 상태로 조용히 COCO 폴백** = 검출 무력화(F-8).
  기본은 **기동 자체를 거부**하도록 되어 있다. `VIGENT_ALLOW_FALLBACK=1` 로 강제한 게 아닌지 확인할 것.
- `sha16` 이 `weights_manifest.json` 과 어긋나면 배포 실체가 선언과 다르다는 신호.

**③ `disabled_detectors`** — 의도적으로 끈 슬롯이 사유와 함께 노출된다(은폐형 off 방지).
현재: `forklift` (F-7 과소학습 — 라이브·재해분석·음성 경로 제외).

> 코드를 고치고 재기동했다면, **바뀐 내용이 실제로 서빙되는지**도 확인한다.
> 예) `curl -s .../health | grep 음성안내` — 문구가 갱신됐으면 새 코드가 뜬 것.

---

## 3. 종료 / 재기동 (좀비 방지)

**현재 8010 점유 확인**
```bash
lsof -nP -iTCP:8010 -sTCP:LISTEN
```

**종료**
```bash
pkill -f "uvicorn main:app.*8010"
sleep 2
lsof -nP -iTCP:8010 -sTCP:LISTEN   # 아무것도 안 나와야 정상
```

**재기동** = 종료 확인 후 §1 로.

### ★ 좀비 서버 방지 원칙
1. **띄우기 전에 항상 점유 확인.** 8010에 이미 떠 있으면 **새로 띄우지 않는다**(포트 충돌 또는 유령 프로세스).
2. **코드를 고쳤으면 "종료 → 점유 없음 확인 → 재기동"** 순서를 지킨다. 종료 없이 또 띄우면
   옛 코드를 문 서버가 계속 살아 **고친 게 반영 안 된 것처럼 보인다**(오늘 헤맨 원인).
3. 재기동 후 **§2의 `/health` 3항목**을 눈으로 확인하기 전엔 "됐다"고 판단하지 않는다.
4. 백그라운드로 띄웠으면 **로그 파일 경로를 기억**한다. 로그 없이 띄우면 죽어도 이유를 못 본다.
5. VS Code / 터미널을 닫아도 백그라운드 서버는 **살아남을 수 있다** — 재시작 후엔 §3 점유 확인부터.

---

## 4. 주요 화면 (기동 후)

| 화면 | URL |
|---|---|
| 안전 엔진 | `http://127.0.0.1:8010/safety/brain` |
| 라이브(Safety) | `http://127.0.0.1:8010/safety-local` |
| 재해 원인분석 | `http://127.0.0.1:8010/safety/incident` |
| 헬스체크 | `http://127.0.0.1:8010/health` |

---

## 5. 환경변수 (opt-in 스위치 — 기본 off)

| 변수 | 기본 | 의미 |
|---|---|---|
| `VIGENT_API_TOKEN` | (없음) | 설정 시 **전 라우트 Bearer 인증**(`/health`·favicon 제외). ★ **파일럿·공유 네트워크 환경에서는 상시 설정 필수.** 미설정 + 로컬 바인딩은 개발 편의로 허용되나 기동 시 경고 1줄 출력(P0-3). **외부 바인딩(`VIGENT_HOST`≠127.0.0.1) + 무토큰은 기동 거부.** 토큰 비교는 상수시간(`hmac.compare_digest`). 생성·설정 절차는 아래 §5.1. |
| `VIGENT_REQUIRE_TOKEN` | (없음) | **1**이면 로컬 바인딩이어도 무토큰 기동을 거부(엣지박스 배포 프로파일 기본값, `Dockerfile`이 `1`로 설정 — [S2-수정, 2026-08-10]). 순수 로컬 개발(`uvicorn main:app` 직접 실행)은 이 변수를 안 건드리면 기존 동작 그대로. |
| `VIGENT_LLM_PROVIDER` | `openai` | 텍스트 LLM 프로바이더 — `openai`(기본) / `anthropic`. **2026-07-14: ollama(로컬) 제거 → OpenAI 단일화.** ⚠️ **키가 없거나 API 장애여도 기능은 죽지 않는다** — 규칙 기반 폴백(위험성평가서의 점검항목·법령·위계는 애초에 규칙 기반이라 영향 0). 단 **폐쇄망에서는 LLM 종합의견 불가**(규칙 폴백만). 실제 설정은 `/health`의 `llm` 필드로 확인. |
| `VIGENT_CLOUD_VLM` | off | **1** 일 때만 클라우드 VLM(OpenAI 비전)에 프레임 전송. **영상 불유출 원칙 — 상용 배포 미포함**(F-12). 키만 있어도 off면 전송 안 함. **위 LLM provider 정리와 무관하게 그대로 유지됨.** |
| `VIGENT_ALLOW_FALLBACK` | off | **1** 이면 커스텀 가중치 부재 시 COCO 폴백 허용(**검출 저하**). 기본은 기동 거부(F-8). |
| `VIGENT_DETECT_DEVICE` | 자동 | `mps` 강제 시 속도↑·크래시 위험(YOLO 경로). |

### 5.1 VIGENT_API_TOKEN 생성·설정 절차

1. **생성**: 충분히 무작위한 문자열을 만든다(예: `openssl rand -hex 32` 또는
   `python -c "import secrets; print(secrets.token_hex(32))"`). 짧거나 예측 가능한 값(제품명·
   날짜 등)은 쓰지 않는다.
2. **설정**: `.env`에 `VIGENT_API_TOKEN=<생성한 값>`을 추가하거나(로컬/Docker 볼륨 마운트),
   `docker run -e VIGENT_API_TOKEN=<값>`처럼 컨테이너 환경변수로 직접 준다. **`.env` 파일은
   git에 커밋하지 않는다**(CLAUDE.md 규칙5, `.gitignore` 대상 이미 확인됨).
3. **클라이언트 쪽**: 모든 API 호출에 `Authorization: Bearer <토큰>` 헤더를 붙인다. WebSocket
   (`/tapo/ws`)은 헤더 대신 `?token=<토큰>` 쿼리 파라미터도 허용(`ws_auth.py`).
4. **브라우저(대시보드) 쪽 — [S3-후속1, 2026-08-11]**: 평범한 브라우저 페이지 이동은
   Authorization 헤더를 실을 방법이 없다(S3 엣지박스 리허설에서 발견 — 토큰 모드 켜면
   대시보드 전체가 401). 이 경우 브라우저를 `http://<엣지박스>:8010/login`으로 열어 API
   토큰을 로그인 폼에 입력한다 — 성공하면 세션 쿠키(`vigent_session`, httponly, 12시간
   유효, `config/tuning.yaml`의 `auth.session_ttl_hours`로 조정 가능)가 발급되고, 이후
   같은 브라우저의 페이지 이동·AJAX·WebSocket(`/tapo/ws` 포함) 전부 별도 조치 없이 통과한다.
   로그인 실패가 15분 내 5회(설정 가능, `auth.lockout_*`) 누적되면 15분간 잠긴다.
   로그아웃은 `POST /logout`. 세션은 서버 프로세스 메모리에만 있어 **재기동 시 전부
   무효화**된다(재로그인 필요 — 단일 운영자 엣지박스 전제의 트레이드오프, 다중 사용자
   시점엔 RBAC([[B12]], 백로그) 재검토).
5. **로테이션**: 토큰을 바꾸려면 `.env`/컨테이너 환경변수를 갱신하고 재기동 — 별도 무효화
   메커니즘은 없다(단일 정적 토큰이므로 갱신 즉시 이전 값은 그냥 안 먹는다). 기존 브라우저
   세션 쿠키는 토큰과 무관하게 자체 만료 시각까지는 유지된다(원치 않으면 재기동해 전
   세션을 함께 무효화할 것).
6. **엣지박스 배포는 이 토큰을 반드시 설정해야 기동한다**(`VIGENT_REQUIRE_TOKEN=1`이
   `Dockerfile` 기본값 — 위 §5 표 참고). 토큰 없이 컨테이너를 띄우면 즉시 종료된다(로그에
   원인 안내 출력).

> ⚠️ 이 스위치들은 **위험한 기본동작을 명시 opt-in 뒤로 숨긴 것**이다. 켤 때는 이유를 알고 켠다.

### 5.2 저가 CPU 박스 배포 — `detect.backend: onnx-cpu`

GPU 없는 저가 미니PC(N100급·중고 사무용 PC 등)에 배포할 때 켜는 설정. `config/tuning.yaml`
`detect.backend`를 `onnx-cpu`로 바꾸면(기본값은 `torch`) PPE 검출(현재 `ppe_rfdetr_v1`
슬롯)이 ONNX Runtime CPU로 돈다 — 실측(`benchmarks/onnx_cpu_bench.md`, [C-2]) 근거:
torch CPU 대비 **1.85배 빠르고 dev 74장 person/PPE/NO-Hardhat 정확도 손실 0**.

1. **전제**: `vigent-core/weights/ppe_rfdetr_v1.onnx`가 있어야 한다(gitignore 대상이라
   git에는 안 들어있음 — `vigent-core/weights/MANIFEST.md`의 변환 커맨드로 직접 생성하거나
   기존 파일을 박스에 복사). 이 파일이 없으면 `detect.backend: onnx-cpu`를 켜도 **자동으로
   torch로 폴백**한다(규칙6 — 설정만 켜고 파일을 깜빡해도 서버가 죽거나 조용히 검출이
   빠지지 않음, 로그에 "ONNX 백엔드 로드 실패 — torch로 폴백" 경고만 남는다).
2. **적용 범위**: 슬롯별 `.onnx` 파일이 있는 슬롯만 ONNX로 바뀐다 — 지금은 `ppe`만 해당
   (`person`은 커스텀 파인튜닝이 없어 애초에 COCO 사전학습 torch 경로, `forklift`/
   `fire_smoke`는 이 desktop에 가중치 자체가 없음). 나머지 슬롯은 그대로 torch(또는
   COCO 폴백)로 동작 — 부분 적용이 정상 동작이다.
3. **설정 방법**: `config/tuning.yaml`의 `detect: backend: onnx-cpu`로 수정 후 재기동.
   즉시 확인 없이 스모크만 해보고 싶으면 재기동 전 `VIGENT_DETECT_BACKEND=onnx-cpu`
   환경변수로 임시 override 가능(tuning.yaml보다 우선, 파일을 안 건드리고 1회성 확인용).
4. **회귀 확인**: `tests/test_rfdetr_onnx_parity.py`가 torch/ONNX 두 백엔드의 검출 결과가
   같은 이미지에서 사실상 일치하는지 잠근다(이 desktop처럼 `.onnx`/`.pth` 둘 다 있는
   환경에서만 실행, 없으면 스킵).
5. **스모크(2026-08-12 실측)**: 파일 카메라 2대·`detect.backend`를 onnx-cpu로 설정한 실서버에서
   확인 — 검출 정상(`ppe_missing` 등 이벤트 정상 발생), `/detect/frame`(person+ppe+fire_smoke
   전체 파이프라인, 카메라 2대 동시 부하 상태) p50 **184.3ms**·p95 366.7ms. 최초 기동 직후
   두 워커가 동시에 모델을 지연 로드하며 각 2회씩 hang이 발생했으나(콜드스타트 경합,
   15초 초과) 이후 안정화돼 재발하지 않았다 — 워밍업 여유를 두고 배포할 것.
