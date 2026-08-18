# VIGENT 설치·운영 절차 (Windows)

> **대상 독자**: 이 프로젝트를 처음 보는 사람. 새 Windows PC에 **30분 안에** 설치하는 것이 목표다.
> **[B7, 2026-08-17 전면 재작성]** 이전 문서는 맥 기준(`~/Desktop`, `python3`, `.command`,
> `lsof`, `pkill`)이라 Windows에서 한 줄도 실행되지 않았다. 맥 관련 내용은 전부 삭제했다.
>
> 설치 **전에** 반드시 읽을 것: [deploy/SITE_CHECKLIST.md](../deploy/SITE_CHECKLIST.md)
> — 미충족 시 기능이 무효가 되는 현장 필수 조건(고정 IP 등)이 있다.

---

## 0. 사전 요구사항

| 항목 | 요구 | 이 문서 작성 시점의 검증 환경 |
|---|---|---|
| OS | Windows 10/11 (64bit) | Windows 11 Home 10.0.26200 |
| Python | **3.11.x** | 3.11.9 |
| GPU | NVIDIA(선택이나 강력 권장) | RTX 5070 Ti, 드라이버 610.74 |
| CUDA | torch 휠과 맞는 버전 | cu130 (torch 2.12.0+cu130) |
| git | 최신 | 2.55.0 |
| NSSM | 서비스 등록용 | winget으로 설치 |
| **카메라 대수** | **권장 5대 이하**(한계 7대) | Ryzen 9 9900X(24스레드) 기준 실측 |
| **CPU** | 카메라당 **2.1 환산코어** | ★대수를 좌우하는 것은 **GPU 가 아니라 CPU** 다 |

**GPU 없이도 동작한다**(CPU 폴백). 다만 카메라 여러 대는 GPU가 사실상 필수다.

**카메라 대수**: **Ryzen 9 9900X(12코어/24스레드) + RTX 5070 Ti** 기준 실측 결과
**한계 7대 / 권장 5대**다([benchmarks/capacity_report.md](../benchmarks/capacity_report.md), 2026-08-18).
8대에서 검출 지연 p95가 116ms → 309ms로 무너진다.

★**병목은 CPU다** — [E1 실측](../benchmarks/e1_bottleneck_report.md)으로 특정됐다.
8대 시점에도 GPU는 VRAM 3.2GB·util 16~42%로 **놀고 있다**. 카메라당 **2.1 환산코어**를
쓰며, 8번째 카메라에서 CPU 증분이 208%→109%로 반토막나며 포화한다.
- **GPU를 키워도 대수는 늘지 않는다.** 대수를 좌우하는 것은 CPU 코어 수·코어당 성능이다.
- **영상 디코드는 병목이 아니다**(프레임당 1ms 미만). 해상도를 낮춰도 CPU는 5%만 준다.

★**다른 기계라면 이 숫자를 그대로 쓰지 말고** `python scripts\capacity_probe.py --max-n 8 --hold 180`
으로 재측정할 것. 구매 전 환산·체크리스트는 [docs/edgebox_purchase_guide.md](../docs/edgebox_purchase_guide.md).

> ⚠️ **CUDA 버전 주의**: RTX 50 시리즈(sm_120)는 **cu126 이하에서 런타임 에러**가 난다.
> 반드시 cu130 휠을 쓸 것(아래 3단계).

---

## 1. 저장소 받기

```powershell
cd D:\
git clone https://github.com/nohhyunseong1-hash/vigent.git vigent_original
cd D:\vigent_original
```

**성공하면 이렇게 보인다**
```
Cloning into 'vigent_original'...
Resolving deltas: 100% (...), done.
```

---

## 2. 가상환경

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**실행정책 오류가 나면**(자주 발생):
```
.\.venv\Scripts\Activate.ps1 : ... 이 시스템에서 스크립트를 실행할 수 없으므로 ...
```
→ 현재 세션에만 우회한다(시스템 설정을 바꾸지 않는다):
```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

**성공하면** 프롬프트 앞에 `(.venv)` 가 붙는다.

---

## 3. 의존성 설치

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**GPU를 쓸 경우 torch를 CUDA 휠로 교체**(위 CUDA 주의 참고):
```powershell
python -m pip install --index-url https://download.pytorch.org/whl/cu130 `
  torch==2.12.0+cu130 torchvision==0.27.0+cu130
```

**성공 확인**
```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
```
2.12.0+cu130 True        ← GPU 사용 가능
2.12.0+cpu False         ← CPU 폴백(동작은 하지만 느리다)
```

---

## 4. 가중치 조달

모델 파일은 git에 없다(용량·라이선스). 스크립트로 받는다:

```powershell
python scripts\fetch_weights.py
```

**성공하면 이렇게 보인다**
```
가중치 디렉터리: D:\vigent_original\vigent-core\weights
대상 3개 (required 만)

  [OK]   ppe_rfdetr_v1.pth  (필수) — 검증됨
  [OK]   forklift_rfdetr_v1.pth  (필수) — 검증됨
  [OK]   fire_smoke_rfdetr_v1_e17.pth  (필수) — 검증됨

필수 가중치 전부 확인됨.
```

> **왜 forklift도 필수인가**: 지게차 검출기는 과소학습(F-7)이라 검출기 목록에서 제외돼 있지만,
> `vision.yaml`의 `rfdetr_weights`에 슬롯이 선언돼 있어 **파일이 없으면 서버가 기동을 거부**한다
> (조용한 COCO 폴백 차단 — F-8). 쓰지 않아도 파일은 있어야 한다.

- 처음이면 `[없음]` → 다운로드 진행 → `[OK]` 순으로 나온다(파일당 약 115MB).
- **실패하면 종료 코드 1**과 함께 어느 파일이 왜 실패했는지 나온다. 저장소가 비공개면
  접근 권한이 필요하다.
- 선택 가중치(YOLO 폴백)까지 받으려면 `--all`. 없어도 기동에는 지장 없다.
- 검증만: `--check`

> 필수 가중치가 없으면 **서버가 예열 단계에서 명시적으로 실패**한다(`/health` `phase=failed`).
> 조용히 COCO로 폴백해 "정상처럼 보이는데 아무것도 못 잡는" 상태가 되지 않도록 막아둔 것이다.

---

## 5. 설정 파일

### 5-1. `.env` (비밀값)

```powershell
Copy-Item .env.example .env
notepad .env
```

최소한 이것만 채우면 된다:

| 키 | 용도 | 필수 |
|---|---|---|
| `VIGENT_API_TOKEN` | 대시보드 로그인·API 인증 | **필수**(외부 바인딩 시) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 텔레그램 경보 | 선택 |
| `WEBHOOK_URL` | 웹훅 경보 | 선택 |

토큰은 아무 긴 문자열이면 된다:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> `.env`는 `.gitignore` 대상이다. **채팅·문서에 값을 붙여넣지 말 것.**

### 5-2. 카메라 등록

서버를 먼저 띄운 뒤(6단계) 대시보드에서 추가하거나, API로 등록한다:

```powershell
$t = "<VIGENT_API_TOKEN 값>"
$body = @{ id="cam1"; name="1번 카메라"; source="rtsp://아이디:비번@192.168.0.4:554/stream1"; fps=2 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/cameras `
  -Headers @{Authorization="Bearer $t"} -ContentType "application/json" -Body $body
```

자격증명은 `data\camera_secrets.json`에만 저장되고 API 응답·로그에는 마스킹된다.

> 카메라 IP는 **반드시 공유기에서 고정(DHCP 예약)** 할 것 —
> [deploy/SITE_CHECKLIST.md](../deploy/SITE_CHECKLIST.md) N-1. IP가 바뀌면 자동복구가 성립하지 않는다.

### 5-3. 위험구역 좌표 지정

1. 대시보드(`http://127.0.0.1:8010/safety-hub`)에서 카메라 타일 클릭 → 확대뷰
2. 설정 패널의 **구역 편집** 켜기
3. 영상 위를 클릭해 다각형 꼭짓점을 3개 이상 찍는다 → 저장
4. 저장 위치는 `data\danger_zone.json`(정규화 좌표 0~1). **매 프레임 읽으므로 재기동 불필요**

침입 판정 기준점은 **사람 박스의 하단 중앙(발끝)** 이다. 카메라가 거의 수직으로 내려다보는
설치라면 `config\tuning.yaml`의 `zone.reference: center`로 바꿀 수 있다.

---

## 6. 수동 기동(설치 확인용)

```powershell
cd D:\vigent_original\vigent-core
$env:VIGENT_REQUIRE_TOKEN = "1"
$env:VIGENT_CAPTURE_MODE = "thread"
python -m uvicorn main:app --host 127.0.0.1 --port 8010
```

**성공하면 이렇게 보인다**
```
INFO:     Uvicorn running on http://127.0.0.1:8010 (Press CTRL+C to quit)
[INFO] vigent.readiness: 예열 slot=person 9.2s
[INFO] vigent.readiness: 예열 slot=ppe 2.3s
[INFO] vigent.readiness: 예열 slot=fire_smoke 2.6s
[INFO] vigent.readiness: ★예열 완료 14.13s — 이제 워커 기동, 워치독 정상 적용
```

> **기동 후 약 15초는 예열 구간**이다. 그동안 `/health`는 `phase=starting` + **HTTP 503**을
> 반환한다 — 정상이다. 예열이 끝나야 카메라 워커가 붙는다.

확인:
```powershell
curl.exe -s http://127.0.0.1:8010/health | python -m json.tool
```
```json
{
    "status": "healthy",
    "phase": "ready",
    "alerts": { "pending": 0, "sent": 0, "dead": 0 },
    "cameras": { "cam1": { "status": "ok", "last_frame_age_s": 0.4, "last_detect_age_s": 0.3 } }
}
```

`Ctrl+C`로 종료한다.

---

## 7. 서비스 등록 (재부팅 자동 기동)

> ⚠️ **여기부터는 관리자 권한 PowerShell이 필요하다.**
> 시작 메뉴 → PowerShell → 우클릭 → **관리자 권한으로 실행**

```powershell
Set-ExecutionPolicy -Scope Process Bypass      # 실행정책 우회(현재 세션만)
cd D:\vigent_original\deploy\windows
.\install_service.ps1
```

NSSM이 없으면 스크립트가 설치 방법을 안내하고 멈춘다:
```powershell
winget install NSSM.NSSM
```

**성공하면 이렇게 보인다**
```
루트 : D:\vigent_original
파이썬: D:\vigent_original\.venv\Scripts\python.exe
NSSM : ...\nssm.exe

서비스 시작...
서비스 'VIGENT' 상태: Running
로그 : D:\vigent_original\logs\vigent.out.log
```

### 방화벽 (다른 기기에서 접속할 경우만)

```powershell
New-NetFirewallRule -DisplayName "VIGENT 8010" -Direction Inbound -Protocol TCP `
  -LocalPort 8010 -Action Allow -Profile Private
```

### 상태 확인

```powershell
.\service_status.ps1
```
```
서비스=Running | HTTP 200 | status=healthy phase=ready | cam1=ok(f0.4/d0.3)
```

예열 중이면:
```
서비스=Running | HTTP 503 | status=starting phase=starting | ...  ← 예열 중(약 15초), 정상
```

상세: [deploy/windows/README.md](../deploy/windows/README.md)

---

## 8. 운영

### 서비스 제어 (관리자 PowerShell)
```powershell
Restart-Service VIGENT      # 코드·설정 변경 후 반드시 재시작
Stop-Service VIGENT
Start-Service VIGENT
```

> **`--reload`가 없다.** `.py`·`config\*.yaml`을 고쳐도 떠 있는 서버엔 반영되지 않는다.
> 반드시 재시작할 것. (프론트 HTML/JS는 브라우저 강력 새로고침 `Ctrl+Shift+R`이면 된다.
> `data\danger_zone.json`은 매 프레임 읽으므로 재시작 불필요.)

### 로그 위치

| 로그 | 경로 |
|---|---|
| 서버 stdout | `logs\vigent.out.log` |
| 서버 stderr | `logs\vigent.err.log` |
| go2rtc | `data\go2rtc.log` |

256MB마다 자동 로테이션(약 2GB 상한).

### 상태 감시

`/health`만 보면 된다. **HTTP 코드로 판단 가능**하다:

| status | HTTP | 뜻 |
|---|---|---|
| `healthy` | 200 | 정상 |
| `degraded` | 200 | 일부 카메라 검출 정지, 또는 **미전송 경보 있음** |
| `starting` | 503 | 예열 중(약 15초) |
| `unhealthy` | 503 | 전 카메라 검출 정지 또는 모델 미로드 |

카메라별 상태에서 **`stale_detect`** 는 특히 중요하다 — **영상은 들어오는데 검출만 멈춘**
상태로, 화면만 보면 정상으로 보인다.

---

## 9. 문제 해결 (자주 나는 오류 5가지)

### ① `Activate.ps1 : 이 시스템에서 스크립트를 실행할 수 없으므로`
실행정책 문제. 현재 세션만 우회:
```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### ② `/health`가 계속 `phase=starting` (15초 넘게)
모델 예열이 안 끝난 것이다. `logs\vigent.err.log`를 본다.
- `필수 가중치 없음: ...` → `python scripts\fetch_weights.py` 실행
- CUDA 관련 오류 → torch 휠이 GPU와 안 맞는다(0단계 CUDA 주의 참고)
- **GPU 없이 CPU로 돌리면 예열이 20~25초까지 걸린다**(실측: GPU 14초 / CPU 23초). 정상이다.

### ②-1 기동 즉시 종료 + `[기동거부·F-8] rfdetr 커스텀 가중치 부재`
가중치가 빠졌다. 4단계를 실행한다:
```powershell
python scripts\fetch_weights.py
```
> 이 오류는 **의도된 안전장치**다. 커스텀 가중치 없이 COCO로 조용히 폴백하면 "정상처럼
> 보이는데 아무것도 못 잡는" 상태가 되기 때문에 아예 기동을 막는다.
> 폴백을 감수하고 띄우려면 `VIGENT_ALLOW_FALLBACK=1`을 명시해야 한다(검출 저하를 받아들인다는 뜻).

### ③ 카메라가 `stale_frame` — 프레임이 안 들어옴
```powershell
Test-NetConnection <카메라IP> -Port 554     # 도달 확인
```
- 실패 → 카메라 전원·네트워크. **IP가 바뀌었을 가능성이 가장 크다**(고정 IP 필수)
- 성공인데 여전히 안 되면 자격증명 확인(카메라 리셋 시 계정이 초기화된다)

### ④ 확대뷰가 검은 화면 / 스냅샷으로만 나옴
go2rtc(WebRTC 변환기) 문제다.
- `data\go2rtc.log` 확인
- 카메라 **동시 RTSP 세션 한도가 2**라 워커 1 + go2rtc 1로 꽉 찬다. 다른 프로그램이
  같은 카메라를 보고 있으면 자리가 없다

### ⑤ 서비스는 Running인데 검출이 안 됨
`/health`의 `cameras`를 본다. `stale_detect`면 검출만 죽은 것이다.
```powershell
Restart-Service VIGENT
```
반복되면 `logs\vigent.err.log`에서 `HANG` 또는 `기아` 로그를 확인한다.

---

## 10. 참고 문서

- **현장 필수 조건**: [deploy/SITE_CHECKLIST.md](../deploy/SITE_CHECKLIST.md)
- 서비스 스크립트: [deploy/windows/README.md](../deploy/windows/README.md)
- 카메라 설치 규격(각도·지연): [docs/camera_requirements.md](../docs/camera_requirements.md)
- 네트워크 보안: [docs/edge_network_hardening.md](../docs/edge_network_hardening.md)
- 안정성 설정값: [docs/STABILITY.md](../docs/STABILITY.md)
- 24시간 소크 절차: [docs/SOAK_24H_CHECKLIST.md](../docs/SOAK_24H_CHECKLIST.md)
