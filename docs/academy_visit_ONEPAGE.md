# 학원 방문 당일 — 한 장 요약 (인쇄·폰 저장용)

> 상세: [academy_visit_day.md](academy_visit_day.md) · 준비 상태: 부록 D-2 **현장 갈 준비 완료**(2026-08-26)

## 출발 전 최종 확인 (집에서, 5분)

```powershell
curl.exe -s http://127.0.0.1:8010/health | .venv\Scripts\python.exe -c "import sys,json;d=json.load(sys.stdin);print('status',d['status']);print('forklift',d['backend']['forklift']);print('sweep_h',(d.get('retention_sweep') or {}).get('interval_h'))"
```
`healthy` / `yolo` / `24.0` — **셋 다 맞아야 출발**

> **왜 `yolo` 가 맞는가**: 이 제품의 검출기는 **RF-DETR** 이다(person·ppe·fire_smoke).
> **지게차 슬롯 하나만** 예외로 YOLO(`forklift_boda_ax.pt`)를 쓴다 —
> RF-DETR 지게차 모델이 과소학습(F-7, **재현율 2.8%**)이라 G1 대결에서 밀렸기 때문이다.
> 학원은 지게차 실습장이라 지게차를 못 잡으면 방문이 무의미하므로 **학원 프로파일 한정**
> 임시 채택이다. ⚠ultralytics 는 **AGPL** — 파일럿 시험 한정이며 **상용 배포 전
> 지게차 RF-DETR 재학습으로 대체**한다(불변 방침, `deploy/academy/README_academy.md`).
>
> 즉 `backend` 가 이렇게 보이면 정상이다:
> ```
> person rfdetr · ppe rfdetr · fire_smoke rfdetr · forklift yolo
> ```

## 준비물

노트북+충전기 · **랜선(긴 것/짧은 것)** · USB-랜 어댑터 · **휴대용 공유기(폰 대역 대비)** ·
USB 64GB+ · 질문지 답변 메모 · **★계정 정보 확보 방법**(미해결이면 방문 연기)

---

## 1. CCTV 연결 (도착 직후, 30분)

1. 노트북을 NVR 과 **같은 네트워크**에 (랜선 우선)
2. `ping <NVR IP>` → 응답 확인
3. **브라우저로 등록** — `http://127.0.0.1:8010/safety-hub` → 카메라 추가
   `ID: academy1` / `이름: 1번 카메라` / `주소: rtsp://계정:암호@<IP>:554/<경로>` / `FPS: 2`

| ✅ 성공 기준 | `/health` 에 `academy1: ok` · `last_frame_age_s < 2` |
|---|---|
| ❌ 실패 시 | ①서브스트림 주소로 교체 ②VLC 로 같은 주소 열어 **카메라 문제/우리 문제 분리** ③NVR 웹설정에서 RTSP 활성 확인 |
| 최후 | 녹화본 반출로 전환(5단계) — **헛걸음 아니다** |

> 🔴 **PowerShell 로 등록하지 말 것** — 한글 이름이 `????` 로 깨져 경보 문구에서 카메라를 구분할 수 없다.
> 🔴 **주소를 고쳐 재등록해도 화면이 안 바뀐다** — 반드시 **비활성→활성** 하고 **스냅샷을 눈으로** 확인.
> 🔴 등록 직후 `/cameras` 로 **이름을 눈으로 확인**(오타·한 글자 방지).

## 1-1. 폰 모니터링 주소 (5분, 건너뛰지 말 것)

```powershell
Get-NetIPAddress -AddressFamily IPv4 | ? {$_.IPAddress -notmatch '^(127\.|169\.254\.)'} | Select IPAddress,InterfaceAlias
```
폰 IP 앞 세 자리가 **같아야** 한다 → `http://<노트북IP>:8010/health`

| ❌ 대역 다름 | 노트북을 폰과 같은 Wi-Fi 에 / **휴대용 공유기** |
|---|---|
| ❌ 같은데 안 열림 | **AP 격리** 유력 → 폰 핫스팟으로 갈라 확인 |
| 최후 | 노트북 화면으로 직접 관제(시험은 진행 가능) |

## 2. 화각 확인 (15분)

`GET /cameras/academy1/snapshot` 을 브라우저로 열어 확인

- ✅ **사람 박스 높이가 화면의 10% 이상**(1080p 기준 108px) ← 미달이면 침입 감지 신뢰 불가
- ✅ 실습 코스 전체 · 지게차 동선 · 보행 동선이 보이나
- ❌ 미달 시: 더 가까운 채널로 교체 / 지참 카메라 보조 설치 협의

> ★**사람 없이 스냅샷을 먼저 찍어** person 오탐이 잡히는 자리(자재 더미·천막·적재물)를
> 확인하고 **그 영역을 피해** 구역을 그린다.

## 3. 지게차 검출 (실습 중, 20분)

기록할 것: ①잡히는 프레임 비율 ②표시 conf ③라벨(`forklift` 인지) ④추적 id 유지

- ✅ 주행 중 박스가 따라다니고 **conf 0.5 이상** 안정, id 유지
- ❌ 검출 0 이면: G1 결론대로 재학습 확정. **4·5 단계는 그대로 진행**

## 4. 근접·구역 경보 (30분)

★**사람이 지게차에 접근하는 시험 금지.** 구역 경계와 기존 동선만으로 확인.

1. 스냅샷 위 폴리곤 지정 — **발끝(박스 하단 중앙)** 기준. 카메라가 가까워 발이 잘리면 **구역 아래를 화면 바닥까지**
2. **구역 경보**: 휴식 중 강사 협조로 한 명이 경계를 넘음 → **1.0초 체류** 후 발화
3. **근접 경보**: 연출 금지 — 실습 중 자연 발생을 기다린다
4. ★**운전자 제외(G5)**: 탑승 상태에서 **10분 이상 경보가 안 울리는지** / **하차 순간** 다시 울리는지

**경보 확인은 로그가 아니라 이것으로:**
```powershell
Get-Content data\recognition\events_20260827.jsonl -Encoding UTF8 | Select-String "zone_intrusion" | Select -Last 3
.venv\Scripts\python.exe -c "import sqlite3;d=sqlite3.connect('data/alert_queue.db');print(d.execute('SELECT status,COUNT(*) FROM alerts GROUP BY status').fetchall())"
```
| 이벤트 있고 큐 `sent` | ✅ 정상 — 폰에 도착 |
|---|---|
| 이벤트 있고 큐 `dead` | 통보 채널 문제. **검출은 정상** |
| 이벤트 있고 큐에 없음 | 쿨다운 억제(정상, 300초) |
| **이벤트 자체가 없음** | 그제서야 구역·검출을 의심 |

> 🔴 `logs\vigent.err.log` 에서 "위험구역" 찾지 말 것 — **실패한 경보만** 남는다.
> ★**재시연은 5분 간격**(300초 억제가 정상).

## 5. 녹화 회수 (철수 전, 필수)

NVR 녹화본 USB 반출. **동의 문구**: "본 영상은 지게차 감지 모델 개선·시험 목적에 한해
사용하며, 인물 식별 정보는 비식별화 처리 후 보관합니다. 외부 공개하지 않습니다."
→ 불가 시 `data\evidence\` 증거 프레임이라도 확보

## 6. 철수

- [ ] 카메라 제거 → **`/health.cameras` 가 비는지 확인**(남으면 보고)
- [ ] 계정 정보 삭제 확인(`data\camera_secrets.json`)
- [ ] `VIGENT_TRACK_DEBUG` **껐는지**(아래)
- [ ] 당일 기록·스냅샷 백업

---

## ★ track_debug 수집 (실습 20분 이상)

```powershell
# 켜기 — 관리자
if (Test-Path data\track_debug.jsonl) { Move-Item data\track_debug.jsonl data\track_debug_이전.jsonl }
[Environment]::SetEnvironmentVariable("VIGENT_TRACK_DEBUG","1","Machine"); Restart-Service VIGENT

# ★끄기 — 반드시. 켠 채 두면 디스크가 계속 찬다
[Environment]::SetEnvironmentVariable("VIGENT_TRACK_DEBUG",$null,"Machine"); Restart-Service VIGENT
```
저장 위치 `data\track_debug.jsonl` · **20분 미만이면 "측정 불충분"으로 기록**
용량 실측 **카메라 1대당 약 12.7 MB/시간**(2fps) — 4대·3시간이면 약 150MB. 디스크 여유 830GB, 문제 없다.

### 🔴 20분 붓기 전에 — **1분 샘플로 person 이 담기는지 먼저 확인**

켜자마자 20분을 수집하지 마라. **1분 뒤 아래를 돌려 person 이 0건이 아닌지 본다.**
사람이 안 담기면 20분을 부어도 판정 3건의 재료가 하나도 안 남는다
(2026-08-26 리허설에서 실제로 그랬다 — `Hardhat` 624건인데 `person` 0건. 원인은 고쳤지만,
현장에서는 카메라·각도 문제로도 같은 결과가 날 수 있으므로 **1분 확인은 계속 한다**).

```powershell
.\\.venv\\Scripts\\python.exe benchmarks\\dbg_person_check.py
```

- **person > 0** → 그대로 20분 수집 진행
- **person = 0** → 즉시 중단. ①카메라에 사람이 실제로 보이는지 ②`/health` 의
  `active_detectors` 에 `person` 이 있는지 ③스냅샷에 사람 박스가 뜨는지 순으로 확인.
  해결 안 되면 **track_debug 는 포기하고 녹화본 반출로 대체**한다(사후 분석은 가능하다).

## 실전 팁 6가지

| # | 상황 | 알아둘 것 |
|---|---|---|
| 1 | 재시작하면 화면이 빈다 | 세션이 메모리에만 있다 → **F5 → 재로그인** |
| 2 | 사람 없는데 경보 | 정지 물체 오검출. **구역 그리기 전 빈 스냅샷 확인** |
| 3 | 두 번째 시연에 알림 없음 | 300초 억제가 정상 → **5분 간격** |
| 4 | **숫자가 이상하면 먼저 의심** | 장비 탓 전에 **측정 오염**부터. `/health` 카메라 목록에 모르는 항목 없나 |
| 5 | **주소 고쳐도 화면 그대로** | 재등록이 무시된 것 → **비활성→활성** + 스냅샷 확인 |
| 6 | 경보에 이름이 이상 | 등록 직후 `/cameras` 로 이름 확인 |

## 알아둘 정상 동작

- **화면이 초당 1~2회만 갱신** — 스냅샷 API 응답이 0.5~0.8초. **판정은 0.3초로 정상**
- **카메라 1대뿐일 때 그게 끊기면 `/health` 가 503** — 설계대로
- **`degraded`** — 미전송 경보가 있으면 뜬다. 카메라 문제가 아닐 수 있다
- 카메라 끊김 복구는 **로그의 `HANG 감지`** 줄로 확인(`reconnects` 는 0으로 남는다)

## 이 노트북 실측값 (참고)

검출기 **RF-DETR**(person·ppe·fire_smoke) + **지게차만 YOLO boda_ax**(학원 한정·AGPL·상용 전 대체) ·
수용량 **한계 6대·권장 4대**(병목 CPU) · 검출 지연 **p50 184ms** · RTSP read **128ms** ·
예열 **약 16~35초** · 오프라인 완주 확인 · 저장 암호화 **BitLocker on**

## 미검증 — 현장에서 처음 만나는 것

🔴 **H.265** 여부(C200 은 H.264) · 🟠 **NVR 경유 주소 형식** · 🟠 **화각에서 사람 크기** ·
🟠 **역광·야간**
