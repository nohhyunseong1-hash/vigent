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
| `VIGENT_CLOUD_VLM` | off | **1** 일 때만 클라우드 VLM(OpenAI 비전)에 프레임 전송. **영상 불유출 원칙 — 상용 배포 미포함**(F-12). 키만 있어도 off면 전송 안 함. |
| `VIGENT_ALLOW_FALLBACK` | off | **1** 이면 커스텀 가중치 부재 시 COCO 폴백 허용(**검출 저하**). 기본은 기동 거부(F-8). |
| `VIGENT_DETECT_DEVICE` | 자동 | `mps` 강제 시 속도↑·크래시 위험(YOLO 경로). |

> ⚠️ 이 스위치들은 **위험한 기본동작을 명시 opt-in 뒤로 숨긴 것**이다. 켤 때는 이유를 알고 켠다.
