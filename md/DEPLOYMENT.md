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
| OS | **Windows 10/11 Pro 이상**(64bit) ★현장 필수 | Windows 11 **Home** 10.0.26200 — ⚠개발 PC 가 Home 이라 **저장 암호화(N-2)는 이 PC 에서 검증 불가**(EFS·BitLocker 미지원, 2026-08-19 실측). 현장 장비(Pro)에서 검증할 것 |
| Python | **3.11.x** | 3.11.9 |
| | ⚠**모순 주의**: 저장소 `.python-version` 은 `3.13.9`, `pyproject.toml` 은 `target-version="py313"` 이다. 어느 쪽이 정본인지 확정 필요(2026-08-20 제기). 3.11.9 로 전 의존성 설치·기동 실증됨 | |
| GPU | NVIDIA(선택이나 강력 권장) | RTX 5070 Ti, 드라이버 610.74 |
| CUDA | torch 휠과 맞는 버전 | cu130 (torch 2.12.0+cu130) |
| git | 최신 | 2.55.0 |
| **2차 검증 환경** | — | ★2026-08-20 **학원 현장 노트북**에서 이 문서로 재설치 실증: Windows 10 **Pro**(N-2 암호화 가능) · i7-10750H · **GTX 1650 Ti 4GB** · 드라이버 576.83(CUDA 12.9) · Python 3.11.9 · **torch 2.12.0+cu126** |
| NSSM | 서비스 등록용 | winget으로 설치 |
| **카메라 대수** | **권장 5대 이하**(한계 7대) | Ryzen 9 9900X(24스레드) 기준 실측 |
| **CPU** | 카메라당 **1.55 환산코어** ([Q10] 스핀 제거 후) | ★대수를 좌우하는 것은 **GPU 가 아니라 CPU** 다 |

**GPU 없이도 동작한다**(CPU 폴백). 다만 카메라 여러 대는 GPU가 사실상 필수다.

**카메라 대수**: **Ryzen 9 9900X(12코어/24스레드) + RTX 5070 Ti** 기준 실측 결과
**한계 7대 / 권장 5대**다([benchmarks/capacity_report.md](../benchmarks/capacity_report.md), 2026-08-18).
8대에서 검출 지연 p95가 116ms → 309ms로 무너진다.

★**병목은 CPU다** — [E1 실측](../benchmarks/e1_bottleneck_report.md)으로 특정됐다.
8대 시점에도 GPU는 util 16~42%로 **놀고 있다**(VIGENT 단독 VRAM 실측 **1.4GB** —
[V1](../benchmarks/v1_slot_config_report.md) §3·§4). 카메라당 **2.03 환산코어**를 쓰며,
8번째 카메라에서 CPU 증분이 208%→109%로 반토막나며 포화한다.
- **GPU 는 VRAM 4GB(GTX 1650급)면 충분하다.** 다만 **GPU 를 빼면 CPU 를 2.2배** 써야 한다
  (카메라당 4.43코어, [V2](../benchmarks/v2_onnx_report.md) §5) — GPU 는 성능이 아니라
  **CPU 절약 장치**다.
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

> ⚠️ **[2026-08-21] 저장소가 비공개로 전환됐다 — 인증이 필요하다.**
> 비공개 저장소는 권한이 없으면 **403 이 아니라 404** 로 응답한다(존재 자체를 숨긴다).
> `repository not found` 가 뜨면 "주소가 틀렸나" 가 아니라 **"로그인이 안 됐나"** 를 먼저 의심한다.
>
> Windows 는 Git for Windows 에 포함된 **자격증명 관리자(GCM)** 가 처리한다 — `git clone` 시
> 브라우저 로그인 창이 뜨고, 한 번 로그인하면 이후에는 자동이다. 창이 안 뜨거나 실패하면:
>
> ```powershell
> # 저장된 자격증명 확인(값은 화면에 찍히니 남 앞에서 실행하지 말 것)
> git credential fill
> #   protocol=https  ⏎  host=github.com  ⏎  ⏎  입력
> ```
>
> 토큰을 직접 쓰려면 GitHub → Settings → Developer settings →
> **Personal access tokens** 에서 `repo` 권한(또는 fine-grained 로 이 저장소 Contents: Read)
> 토큰을 만들어 아래처럼 넣는다:
> ```powershell
> $env:GITHUB_TOKEN = "<발급받은 토큰>"
> ```

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

**GPU를 쓸 경우 torch를 CUDA 휠로 교체** — ★**드라이버 버전에 맞는 휠을 고를 것**:

| 이 PC 의 GPU·드라이버 | 쓸 휠 | 근거 |
|---|---|---|
| RTX 50 시리즈(sm_120) | **cu130** | cu126 이하는 sm_120 커널이 없어 런타임 에러 |
| 그 외(GTX 16 / RTX 20~40) **+ 드라이버 580 미만** | **cu126** | CUDA 13 런타임은 드라이버 580+ 를 요구한다 |

먼저 `nvidia-smi` 우상단의 **`CUDA Version:`** 을 본다 — 이것이 **드라이버가 지원하는 상한**이다.
`12.x` 로 나오면 cu130 을 깔아도 `torch.cuda.is_available()` 이 False 가 되거나 런타임 에러가 난다.

```powershell
# RTX 50 시리즈(드라이버 580+)
python -m pip install --index-url https://download.pytorch.org/whl/cu130 `
  torch==2.12.0+cu130 torchvision==0.27.0+cu130

# 그 외 GPU / 드라이버 580 미만
python -m pip install --index-url https://download.pytorch.org/whl/cu126 `
  torch==2.12.0+cu126 torchvision==0.27.0+cu126
```

> **실측(2026-08-20, 학원 현장 노트북)**: GTX 1650 Ti(sm_75)·드라이버 **576.83**(`CUDA Version: 12.9`)
> 에서 **cu126 으로 `2.12.0+cu126 True` 확인**. 이 드라이버에서 cu130 은 쓸 수 없다.

**성공 확인**
```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```
```
2.12.0+cu130 True        ← GPU 사용 가능(RTX 50)
2.12.0+cu126 True        ← GPU 사용 가능(그 외)
2.12.0+cpu   False       ← CPU 폴백(동작은 하지만 느리다)
```

### 3-1. ★opencv 정리 (필수 — 빠뜨리면 headless 가 가려진다)

`supervision`·`rtmlib` 등이 **GUI opencv 를 전이의존으로 끌어온다**. 그대로 두면 배포가
전제한 headless 대신 GUI 빌드의 `cv2` 가 쓰인다(같은 `cv2` 네임스페이스 충돌).
`requirements.txt` 설치 **직후 반드시** 정리한다:

```powershell
python -m pip uninstall -y opencv-python opencv-contrib-python
python -m pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.13.0.92
```

확인 — `opencv-contrib-python-headless` **하나만** 남아야 한다:
```powershell
python -m pip list | Select-String opencv
```

> **실측(2026-08-20)**: 정리 전 `opencv-python 5.0.0.93` + `opencv-contrib-python 5.0.0.93` 이
> 함께 깔려 headless(4.13.0.92)를 가렸다. ★**`ultralytics` 를 설치하면(학원 프로파일 등)
> GUI opencv 가 다시 딸려오므로 그때도 이 정리를 반복해야 한다** — `deploy/academy/README_academy.md` 참고.

---

## 4. 가중치 조달

모델 파일은 git에 없다(용량·라이선스). 스크립트로 받는다:

```powershell
python scripts\fetch_weights.py
```

> ⚠️ **반드시 `scripts\` 경로로 실행할 것.** 저장소 **루트에도 같은 이름의 구판**
> `fetch_weights.py` 가 있는데 CLI 가 전혀 다르다(`verify`/`download` 서브커맨드,
> `--all` 없음, URL 이 PLACEHOLDER). 루트본으로 `--all` 을 치면 실패한다.
> 정본은 `scripts\fetch_weights.py` 하나이며 `weights_manifest.json` 도
> 이쪽을 가리킨다(2026-08-20 학원 노트북 설치 시 확인).

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
- **실패하면 종료 코드 1**과 함께 어느 파일이 왜 실패했는지 나온다.

> ★**[2026-08-21] 저장소가 비공개라 릴리스 자산도 인증이 필요하다.**
> `scripts/fetch_weights.py` 는 토큰을 **자동으로 찾는다**:
> 1. 환경변수 `GITHUB_TOKEN` / `GH_TOKEN` / `VIGENT_GITHUB_TOKEN`
> 2. git 자격증명 도우미(`git credential fill`) — clone 할 때 로그인했다면 여기 이미 있다
>
> 토큰이 있으면 릴리스 **자산 API**(`/repos/{repo}/releases/assets/{id}` +
> `Accept: application/octet-stream`)로 받는다. 브라우저용 `releases/download/...` URL 은
> 비공개에서 토큰을 붙여도 잘 안 되기 때문이다.
>
> **토큰이 없으면** 공개 저장소 시절과 같은 URL 로 시도하다 실패한다:
> ```
> [실패] yolo11s.pt — HTTP 404
> ```
> 이 404 는 **"파일이 없다"가 아니라 "권한이 없다"** 다(비공개는 404 로 숨긴다).
> 위 1·2 중 하나를 채우고 다시 실행한다.
>
> 사내 미러를 쓰면 GitHub 인증 자체가 불필요하다:
> ```powershell
> $env:VIGENT_WEIGHTS_BASE_URL = "https://<미러주소>"
> ```
>
> **실증(2026-08-21)**: 비공개 전환 후 `yolo11s.pt` 를 지우고 재조달 → 자산 API 로
> 다운로드·SHA256 검증 통과 확인.
- 선택 가중치(YOLO 폴백)까지 받으려면 `--all`. 없어도 기동에는 지장 없다.
- 검증만: `--check`

> 필수 가중치가 없으면 **서버가 예열 단계에서 명시적으로 실패**한다(`/health` `phase=failed`).
> 조용히 COCO로 폴백해 "정상처럼 보이는데 아무것도 못 잡는" 상태가 되지 않도록 막아둔 것이다.

---

### 4-1. ★RF_HOME — 오프라인 현장이면 반드시 확인

RF-DETR 은 커스텀 가중치 밑에 **베이스 사전학습 체크포인트**(`rf-detr-nano.pth`, 349MB)를 깐다.
이 파일이 없으면 rfdetr 이 **런타임에 인터넷에서 받아온다** — 인터넷이 없는 현장이면 기동 실패다.

캐시 위치는 `RF_HOME` 이 정하고, 기본값 `~/.roboflow/models` 는 **계정별**이다.
★서비스는 **LocalSystem** 으로 돌기 때문에 기본값이면
`C:\Windows\System32\config\systemprofile\.roboflow\models` 를 본다 —
**로그인 계정에서 미리 데워둔 캐시는 서비스에 아무 소용이 없다**(2026-08-20 실측: 서비스 첫
기동에서 349MB 를 새로 받았다).

그래서 배포는 `RF_HOME` 을 **`vigent-core\weights`** 로 고정한다:

- 서비스: `install_service.ps1` 이 자동 주입한다(**기존 서비스는 재등록해야 반영된다**).
- 수동 기동(6단계): 아래처럼 직접 넣는다.
- 조달: 이 위치가 `scripts\fetch_weights.py` 의 다운로드 경로와 같아
  `--all` 하나로 같이 받아진다(매니페스트 `rf-detr-nano.pth`, **required**).

```powershell
$env:RF_HOME = "C:\Users\1\Desktop\VIGENT\vigent-core\weights"
```

> **기동 시 캐시가 없으면 명시적으로 실패한다**(조용한 인터넷 의존 금지):
> ```
> [기동거부] RF-DETR 사전학습 체크포인트 부재: ...\rf-detr-nano.pth (파일 없음).
> ```
> 다운로드를 감수하고 띄우려면 `VIGENT_ALLOW_PRETRAIN_DOWNLOAD=1` 을 명시해야 한다.

#### 포즈 모델도 같은 함정이 있다 — `TORCH_HOME`

`rtmlib`(RTMPose)은 **첫 사람 검출 시점에** 모델 2개를 인터넷에서 받는다:

| 파일 | 크기 |
|---|---|
| `yolox_m_8xb8-300e_humanart-c2c7a14a.onnx` | 101MB |
| `rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx` | 54MB |

기본 캐시가 `~/.cache/rtmlib` 이라 `RF_HOME` 과 똑같이 **계정별로 흩어진다**(서비스는
LocalSystem 프로필). 배포는 `TORCH_HOME` 을 **`vigent-core\weights\rtm_cache`** 로 고정한다
— `install_service.ps1` 이 자동 주입하고, 수동 기동은 직접 넣는다:

```powershell
$env:TORCH_HOME = "C:\Users\1\Desktop\VIGENT\vigent-core\weights\rtm_cache"
```

> ★**이건 기동 경로가 아니라 검출 경로다.** 서버가 healthy 로 떠도 캐시가 없으면
> **사람이 처음 잡히는 순간** 다운로드를 시도한다 — 인터넷이 없으면 그때 실패한다.
> 그래서 "서비스가 떴으니 오프라인 OK" 는 **검증이 아니다**. 반드시 카메라를 붙이고
> 사람이 잡히는 것까지 확인해야 한다(2026-08-20 오프라인 시험이 카메라 없이 돌아 이걸
> 놓쳤고, 다음날 지게차 영상을 물리자마자 156MB 다운로드가 관측됐다).

미리 채우려면 인터넷이 되는 곳에서 한 번 돌려 둔다:
```powershell
$env:TORCH_HOME = "<루트>\vigent-core\weights\rtm_cache"
python -c "from rtmlib import Body; Body(mode='balanced', backend='onnxruntime', device='cpu')"
```

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
$env:PYTHONUTF8 = "1"                 # 한글 로그 깨짐 방지(cp949 콘솔)
$env:RF_HOME = "$PWD\weights"         # 4-1 참고 — 없으면 349MB 를 받으러 나간다
$env:TORCH_HOME = "$PWD\weights
tm_cache"   # 포즈 모델 156MB — 4-1 참고
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

### 7-1. Windows 서비스 설치·재설치 절차 (★2026-09-06 감사 — 크래시 루프 사고 후 정리)

> **사고**: 이 개발 PC의 서비스 `VIGENT`가 2026-08-17~09-06 **3주간 130초마다 재시작을 반복**(4,067회,
> `logs/` 8,139파일 49.7MB)했는데 아무도 몰랐다. 원인은 `install_service.ps1`이 `RF_HOME`을 넣도록 고쳐진
> (`a37538a`, 08-20) **이전에 설치된 서비스가 그대로 남아** LocalSystem 프로필(`\Windows\System32\config\systemprofile\
> .roboflow\models`)에서 `rf-detr-nano.pth`를 못 찾아 기동 거부 → NSSM 재시작 → 반복. 기록: `audit/c4_smoke_2026-09-06.md` §3.
> 개발 PC의 서비스는 **비활성화(SERVICE_DISABLED)** 했고, 설정 백업은 `audit/vigent_service_backup_2026-09-06*.txt`.

**원칙**: 서비스는 **항상 최신 `install_service.ps1`로 (재)설치**한다. 스크립트가 바뀌면 `uninstall_service.ps1` → `install_service.ps1`.
env를 `nssm set`으로 손으로 고치지 않는다(다음 재설치 때 되돌아간다).

| 순서 | 명령(관리자 PowerShell) | 확인 |
|---|---|---|
| 1 | `cd D:\vigent_original\deploy\windows; .\uninstall_service.ps1` (기존 서비스가 있을 때) | `Get-Service VIGENT` → 없음 |
| 2 | 가중치 조달: `python scripts\fetch_weights.py --all` (§4) | `vigent-core\weights\rf-detr-nano.pth` + rfdetr 3종 존재 |
| 3 | `.\install_service.ps1` | "서비스 'VIGENT' 상태: Running" |
| 4 | `.\service_status.ps1` 를 **예열 후(≥20초) 한 번 더** | `HTTP 200 · status=healthy/degraded · phase=ready` — 15초 넘게 503이면 §9-② |
| 5 | **크래시 루프 검사**: `.\service_status.ps1` 종료코드 **4**(최근 1시간 `vigent.err-*` 회전 파일 ≥ 임계 10, `-CrashLoopThreshold` 조정) 또는 `Get-ChildItem logs\vigent.err-* \| Measure-Object` 가 몇 분 사이 계속 늘면 루프다 | 종료코드 0~2, 늘지 않음 |

**`install_service.ps1`이 서비스에 넣는 환경변수(2026-09-06 현재, 스크립트 `$envLines`)** — 재설치 시 전부 자동 설정된다:

| 변수 | 값 | 왜 필요한가 |
|---|---|---|
| `VIGENT_REQUIRE_TOKEN` | `1` | LAN 바인딩이라 전 라우트 Bearer 필수(`/health` 면제) |
| `VIGENT_CAPTURE_MODE` | `thread` | 캡처 스레드 모드 |
| `VIGENT_HOST` | `0.0.0.0` | uvicorn 바인드와 앱 인식 일치(불일치 시 LAN 403) |
| `PYTHONUTF8` | `1` | 서비스 로그 한글 깨짐 방지 |
| **`RF_HOME`** | `<루트>\vigent-core\weights` | ★RF-DETR 사전학습 캐시를 배포 폴더로 고정 — **없으면 LocalSystem 프로필을 보고 기동 거부(이번 사고)** |
| `TORCH_HOME` | `<루트>\vigent-core\weights\rtm_cache` | RTMPose(rtmlib) 모델 캐시 고정(오프라인 현장) |
| `VIGENT_RESTART_CMD` | `sc.exe stop VIGENT & sc.exe start VIGENT` | 기아 3단계(starvation_guard)가 소비 |

비밀값(`VIGENT_API_TOKEN`·텔레그램·카메라 자격증명)은 서비스 env가 아니라 `.env`·`config/notify.yaml`·`data/camera_secrets.json`(전부 gitignore)에서 읽는다.

**크래시 루프 재발 방지(4단계 CODE_REVIEW M4-5, 2026-09-06 반영)** — "3주간 미감지"를 세 겹으로 막는다:
1. **기동 실패 통보·기록**(`main._startup`): `_load_theme` 실패 시 ① `data/startup_failure.json`에 누적 횟수·마지막 통보 시각 ② **Windows 이벤트 로그** Application / 소스 `VIGENT` / ID 1000 에 ERROR 1줄(매 실패 — 텔레그램 설정 자체가 원인일 때 대비) ③ 원격 채널(notify.yaml/.env)이 있으면 텔레그램·이메일·웹훅 통보(첫 실패 즉시, 이후 **1시간 1회**) → 그 뒤 재raise(기동은 실패시킨다). 확인: `Get-EventLog -LogName Application -Source VIGENT -Newest 5`.
2. **NSSM 파라미터**(`install_service.ps1`): `AppRestartDelay 60000`(재시작 지연 60s, 구 5s) · `AppThrottle 180000`(기동 후 180s 안에 죽으면 폭주로 보고 감속, 구 10s — 모델 로드 ~25s 뒤 실패하는 루프에 10s 스로틀은 무력했다). **재설치해야 적용**(현재 개발 PC 서비스는 SERVICE_DISABLED, 재설치는 5단계 검증 후 결정).
3. **`service_status.ps1`**: 최근 1시간 `logs/vigent.err-*` 회전 파일 수를 항상 출력하고 임계(기본 10) 이상이면 **종료코드 4** + 빨간 안내(서버가 응답하지 않을 때도 동작). 작업 스케줄러 등에서 종료코드 ≥3 을 감시하면 된다.

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

> ⚠️ **로그를 읽을 때는 `-Encoding UTF8` 을 붙일 것.** 로그 파일은 UTF-8 로 저장되는데
> PowerShell 5.1 의 `Get-Content` 는 기본적으로 시스템 ANSI(한국어 Windows=CP949)로 읽어
> 한글이 `?덉뿴 slot=ppe` 처럼 깨져 보인다 — **파일이 깨진 게 아니라 읽는 쪽 문제다**.
> ```powershell
> Get-Content logs\vigent.err.log -Tail 30 -Encoding UTF8
> ```
> (서비스가 UTF-8 로 쓰도록 `install_service.ps1` 이 `PYTHONUTF8=1` 을 주입한다. 이게
> 없던 시절엔 파일 자체가 `???? slot=ppe` 로 깨졌다 — 증상이 비슷하니 구분할 것:
> `????` = 쓰기 문제 / `?덉뿴` = 읽기 문제.)

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
