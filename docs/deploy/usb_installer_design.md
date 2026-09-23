# USB 설치기 1차 설계 (2026-09-23)

> **목표**: USB 하나로 사양 맞는 PC(데스크톱·노트북 무관)를 VIGENT 현장 기기로 설치하고,
> 카메라 연결 후 바로 가동한다.
>
> ⚠️ **이 문서는 설계다. 구현하지 않았다.** 착수는 대표 검토 후.

---

## 0. 현황 — 무엇이 이미 있고 무엇이 없나

### 0-1. 두 계보가 갈라져 있다 (★착수 조건)

| 산출물 | 크기 | 커밋 | 위치 | 상태 |
|---|---|---|---|---|
| **오프라인 번들 v1** | 4.07 GB | `97ac1a3` | **노트북 전용** | ❌ 개발기에서 **내용 확인 불가**(원격 404) |
| **USB 포터블** | 2.43 GB | `615a52e` 등 | 개발기 `D:\vigent_portable` | ✅ 검증 완료 |

★**차이가 무엇인지 모른다.** 1.64GB 차이는 CUDA 휠(약 2.5GB)일 수 있으나 **추측이며 미검증**이다.
`build_bundle.ps1`·`BUNDLE.txt`·`docs/acceptance_test.md` 셋 다 개발기에 없다.

> **★1차 착수 조건**: 원격 복구 후 두 계보를 비교해 **하나로 합친다.**
> 그 전까지 이 설계서는 **포터블 계보** 기준으로 쓴다.

### 0-2. 포터블 v1이 이미 해결한 것 (재사용)

| 항목 | 상태 | 근거 |
|---|---|---|
| 파이썬 런타임 | ✅ 임베디드 3.11.9 동봉 | `PACKAGE_MANIFEST.md` |
| 의존성 | ✅ torch·onnxruntime·fastapi 전부 동봉 | 46,746 파일 |
| 모델 가중치 | ✅ 동봉 | `rf-detr-nano.pth` 포함 |
| **인터넷 0 기동** | ✅ **실증** | `HTTPS_PROXY` 차단 → `/health` 200, 다운로드 0줄 |
| 다운로드 차단 | ✅ | `VIGENT_ALLOW_PRETRAIN_DOWNLOAD` 비우면 가중치 없을 때 **기동 거부** |
| VC++ 재배포 | ✅ `vc_redist.x64.exe` 동봉 | |
| 개인정보 정리 | ✅ `VIGENT_데이터정리.bat` | |

### 0-3. 없는 것 (1차에서 만들 것)

사양 검사 · 마법사 · 서비스 자동 등록 · 자동 인수시험 · **GPU 동작**

---

## 1. ★CUDA — 가장 큰 위험 (실측 확인)

### 1-1. RTX 5060은 sm_120이고, 포터블 기본값으로는 **못 돈다**

실측(2026-09-23, 개발기):

```
torch 2.12.0+cu130 · CUDA 빌드 13.0
지원 아키텍처: ['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']
GPU: RTX 5070 Ti · 드라이버 610.74
```

| 빌드 | sm_120(Blackwell) | 판정 |
|---|---|---|
| **cu126** ← `build_portable.ps1` **기본값** | ❌ **미지원** | **쓰면 안 된다** |
| **cu130** ← 개발기 현재 | ✅ **지원 확인** | ★이것을 쓴다 |

> ★**`scripts/build_portable.ps1` 의 `-Cuda` 기본값이 `cu126` 이다.** 그대로 빌드하면
> RTX 5060 에서 **CUDA 초기화는 되지만 커널이 없어 실패**하거나 CPU 로 조용히 떨어진다.
> **1차 구현 시 기본값을 `cu130` 으로 바꾸고, preflight 가 아키텍처를 검사한다.**

### 1-2. 드라이버는 USB가 설치한다 (단, 재부팅 필요)

- NVIDIA 드라이버 설치 파일(`.exe`)을 USB에 **동봉**한다.
- `nvidia-smi` 가 없으면 **설치를 중단**하고 안내한다:
  > `USB의 driver\<파일명>.exe 를 실행 → 재부팅 → VIGENT_설치.bat 다시 실행`
- 드라이버 **버전 하한 — 확정됨(2026-09-23)**

  | 항목 | 값 | 출처 |
  |---|---|---|
  | **CUDA 13.0 (Windows) 최소 드라이버** | **≥ 580** | NVIDIA CUDA Toolkit Release Notes, Table 3 |
  | CUDA 12.8 (Windows) 참고 | ≥ 570.65 | 동일 |
  | **개발기 실측 드라이버** | **610.74** (RTX 5070 Ti) | `nvidia-smi` 2026-09-23 |

  → **preflight 기준값은 580** 으로 둔다. 개발기 610.74 는 여유 있게 통과한다.

### 1-3. ★GPU 포터블 실증 (2026-09-23, 개발기 RTX 5070 Ti)

**인터넷 차단(`HTTPS_PROXY=http://127.0.0.1:9`) 상태에서 전 과정 확인.**

| 항목 | 결과 |
|---|---|
| 빌드 | ✅ `D:\vigent_portable_gpu` · 빌드 직후 **4.23 GB** · 46,848 파일 · **1.3분** |
| **최종 용량** | ★**6.49 GB** · 46,902 파일 (휠 교체 **후** 실측 2026-09-23) |
| CUDA 휠 동봉 | ✅ `torch-2.12.0+cu130`(1,926MB) · `torchvision-0.27.0+cu130` |
| **오프라인 휠 교체** | ✅ **0.9분** (`--no-index --find-links wheels_cuda`) |
| CUDA 인식 | ✅ `torch 2.12.0+cu130` · `is_available True` · **`sm_120` 포함** |
| **nvidia-smi 점유** | ✅ `D:\vigent_portable_gpu\python\python.exe` 가 GPU 프로세스로 잡힘 |
| torch VRAM | allocated 281MB · reserved 558MB |

**추론 시간 비교** (같은 사고영상 1프레임, 예열 후 4회 평균, person+ppe):

| 패키지 | torch | 평균 | 최소 | 첫 추론 |
|---|---|---|---|---|
| CPU 포터블 | 2.12.0+cpu | **231.6 ms** | 229.5 | 36.1 s |
| **GPU 포터블** | **2.12.0+cu130** | **128.6 ms** | 111.1 | 11.1 s |
| | | **1.80배 빠름** | | **3.3배 빠름** |

⚠️ **PPE 슬롯은 포터블 프로필상 `onnx-cpu`** 라 GPU 를 쓰지 않는다(`portable_overrides.yaml`).
person 만 torch/GPU 다. **현장 프로필에서는 차이가 더 클 수 있으나 미측정**이다.

⚠️ **RTX 5060 실기는 여전히 미검증**(R-1). 위 값은 **5070 Ti** 기준이다.

#### ★2026-09-23 정정 — 용량을 4.23GB 로 적었던 것은 틀렸다

`build_portable.ps1` 이 찍는 총용량은 **휠 교체 전** 값이다. 그 시점 패키지는 CPU torch +
`python\wheels_cuda\`(CUDA 휠 1.80GB)를 함께 담고 있다. 오프라인 교체를 하면 cu130 torch
(2.73GB)가 **추가로** 설치되고 **`wheels_cuda` 는 지워지지 않는다.**

| 구간 | 용량 | 비고 |
|---|---|---|
| 빌드 직후(스크립트 출력) | 4.23 GB | CPU torch + `wheels_cuda` 1.80GB |
| **휠 교체 후 = 실제 배포 상태** | **6.49 GB** | cu130 torch 2.73GB · `wheels_cuda` 1.80GB **잔존** |
| (참고) 교체 후 `wheels_cuda` 삭제 시 | 약 **4.69 GB** | ★미실측 — 뺄셈값이다 |

→ **USB 용량 산정은 6.49GB 기준**으로 한다. 설치기가 교체 후 `wheels_cuda` 를 지우면
약 1.8GB 를 회수할 수 있으나 **아직 구현하지 않았고 삭제 후 동작도 확인하지 않았다.**

---

## 2. 사양 검사 (preflight) — 미달이면 설치 중단

★**구현됨(G-4·H-1, 2026-09-23)**: [`scripts/deploy/preflight.ps1`](../../scripts/deploy/preflight.ps1)
아래 표 **8개 항목 전부**를 검사한다. 미달이면 한 줄씩 전부 출력하고 **종료코드 1**.
`-JsonOut` 으로 `install_report` 에 실을 JSON 을 남긴다.

### ★지원 GPU 하한 — cu130 채택의 결과

동봉 torch 가 `cu130` 빌드이므로 **`sm_75` 미만 GPU 는 지원하지 않는다.**
실측 지원 목록: `sm_75, sm_80, sm_86, sm_90, sm_100, sm_120`.

| 세대 | 예시 | 지원 |
|---|---|---|
| Pascal 이하 (`sm_61` 등) | **GTX 1080 / 1060 / 1050** 등 GTX 10xx | ❌ **미지원** |
| Turing (`sm_75`) | GTX 1650 Ti · RTX 2060 | ✅ (현장 노트북이 여기) |
| Ampere~Blackwell | RTX 30/40/50 시리즈 | ✅ |

→ GTX 10xx 이하 기기는 preflight 의 **GPU 아키텍처 항목에서 차단**된다. 되살리려면
CUDA 빌드를 낮춰야 하는데 그러면 `sm_120`(RTX 50)을 잃는다 — **동시 지원은 불가**다.

```
powershell -ExecutionPolicy Bypass -File scripts\deploy\preflight.ps1 -InstallPath C:\VIGENT
```

기준선: **파일럿 사양(Ryzen 9700X / RTX 5060 8GB / RAM 16GB)**
★확정 근거는 **노트북 클론의 `DECISIONS.md` D-1** 이다(계보 통합 전이라 이 저장소에는 없다).
통합되면 이 절에서 그 문서를 인용한다 — **여기서 사양을 다시 정하지 않는다.**

| 항목 | 최소 | 확인 방법 | 미달 시 메시지 |
|---|---|---|---|
| OS | Windows 10/11 **64bit** | `[Environment]::Is64BitOperatingSystem` | "64비트 Windows 10 이상이 필요합니다" |
| **GPU 드라이버** | `nvidia-smi` 응답 | `nvidia-smi` 실행 | "USB의 `driver\*.exe` 실행 → 재부팅 → 재시작" |
| **드라이버 버전** | **≥ 580** (CUDA 13.0 Windows) | `nvidia-smi --query-gpu=driver_version` | "드라이버가 오래됐습니다(현재 X, 필요 Y 이상)" |
| **GPU 아키텍처** | torch 빌드의 `get_arch_list()` 에 포함 | `nvidia-smi --query-gpu=compute_cap` | "이 GPU(sm_XX)는 동봉된 CUDA 빌드가 지원하지 않습니다" |
| **VRAM** | **≥ 8 GB** | `nvidia-smi --query-gpu=memory.total` | "VRAM이 부족합니다(현재 X GB, 필요 8GB)" |
| **RAM** | **≥ 16 GB** | `Win32_ComputerSystem.TotalPhysicalMemory` | "메모리가 부족합니다(현재 X GB, 필요 16GB)" |
| **디스크 여유** | **≥ 20 GB** | 설치 대상 드라이브 | "디스크 여유가 부족합니다(현재 X GB, 필요 20GB)" |
| **VC++ 재배포** | **≥ 14.51** (x64) | 레지스트리 `Installed=1` + 버전 + 필수 DLL 존재 | "USB의 `vc_redist.x64.exe` 실행 후 재시작" |

#### VC++ 재배포 하한 14.51 의 근거 (추측 아님)

1. **무엇이 필요한가 — 바이너리 실측**: 포터블 torch DLL 들이 `vcruntime140.dll` ·
   `vcruntime140_1.dll` · `msvcp140.dll` · `msvcp140_atomic_wait.dll` 을 가져다 쓴다.
   앞의 둘은 포터블이 `python\` 에 **동봉**(14.38.33126.1)하지만, **`msvcp140.dll` 과
   `msvcp140_atomic_wait.dll` 은 동봉되지 않는다** → 시스템 재배포가 없으면 torch import 가 죽는다.
2. **버전 규칙 — 출처**: Microsoft Learn *C++ binary compatibility 2015-2026* —
   "the Redistributable version must be at least as new as **the latest build tools used by
   any app component**."
3. **그 규칙에 넣을 실측값**: 포터블 PE 헤더의 링커 버전(=MSVC 빌드툴 버전) 최댓값 —
   torch/cuDNN 구성요소 **14.44**(`cudnn64_9.dll`), **포터블 전체 14.51**
   (`charset_normalizer`·`fontTools` 확장모듈).
   → 규칙대로 **전체 최댓값 14.51** 을 하한으로 둔다.

★**포터블 구성이 바뀌면 이 값도 다시 재야 한다**(같은 방법: 링커 버전 최댓값).
★MS 문서가 `msvcp140_atomic_wait.dll` 의 **최초 도입 버전**은 명시하지 않는다 — 그래서
그 숫자는 쓰지 않았고, 대신 위 규칙 + 실측으로 유도했다.

★**미달 항목은 한 줄씩 전부 출력한다.** 하나 고치고 다시 돌렸더니 또 다른 게 걸리는 일을 막는다.
★결과는 `install_report` 에 그대로 싣는다(나중에 "왜 이 기기를 골랐나" 의 근거).

---

## 3. 오프라인 설치 — 인터넷 0 전제

| 항목 | USB 동봉 |
|---|---|
| 파이썬 | 임베디드 3.11.9 (`python\`) |
| **CUDA torch 휠** | **cu130** (`python\wheels_cuda\`) — 약 2.5GB |
| 모델 가중치 | `app\vigent-core\weights\` + `rf-detr-nano.pth` |
| 코드 | **태그 스냅샷**(`.git` 없음) |
| 의존성 휠 | 전부 |
| NVIDIA 드라이버 | `driver\*.exe` |
| VC++ | `vc_redist.x64.exe` |
| NSSM | `deploy\windows\nssm.exe` |

**예상 크기**: 2.43GB(현 포터블) + 2.5GB(CUDA 휠) + 드라이버 ~0.8GB ≈ **6GB**
→ **8GB 이상 USB** 필요(현재 삼성 64GB 사용 중이라 여유 충분).

★**기기에 git 을 쓰지 않는다.** 코드는 태그 스냅샷으로만 들어간다.

---

## 4. 첫 실행 마법사 (1차는 명령줄)

★**각 입력 직후 검증한다.** 전부 입력하고 마지막에 한꺼번에 틀렸다고 하면 어디가 문제인지 모른다.

| 순서 | 입력 | 즉시 검증 | 실패 시 |
|---|---|---|---|
| 1 | 기기명 | 형식(영문·숫자·하이픈) | 다시 입력 |
| 2 | 현장 프로파일 | `deploy/*/` 목록에서 선택 | — |
| 3 | **카메라 RTSP 주소** | ① 형식 `rtsp://user:pass@ip:port/path` ② **프레임 1장 수신** | 주소·자격증명 재입력 |
| 4 | **텔레그램** 토큰·chat_id | **`getMe` → `ok=true`** | 재입력 |
| 5 | **이메일** SMTP | **연결·STARTTLS**(로그인 안 함 — 계정 잠금 위험) | 건너뛰기 허용(경고) |
| 6 | 필수 보호구 집합 | 프로파일 기본값 제시 | — |
| 7 | 설정 파일 생성 | `cameras.json`·`camera_secrets.json`·`notify.yaml` | — |

### 보안

| 항목 | 방침 |
|---|---|
| **토큰·비밀번호** | **마법사에서 입력. USB에 저장하지 않는다.** 기기의 `config/notify.yaml` 에만 |
| **카메라 자격증명** | `data/camera_secrets.json` 에만(기존 구조 유지). `cameras.json` 은 마스킹 |
| 설정 파일 권한 | `icacls` 로 Administrators·SYSTEM 만 읽기 |
| **작업자 영상** | **기기 밖으로 나가지 않는다.** `VIGENT_CLOUD_VLM` 은 **설정하지 않는다**(기본 off) |

★**이메일은 건너뛸 수 있게 하되 경고한다** — "채널이 하나뿐이면 그것이 죽는 순간 경보가
아무에게도 가지 않습니다(2026-08-21 실제 사고, 20일간 213건 유실)".

---

## 5. 자동 시작 — NSSM 서비스 (기존 방식 유지)

**제안: 기존 `deploy/windows/install_service.ps1`(NSSM)을 그대로 쓴다.**

| 항목 | NSSM(현행) | 작업 스케줄러 |
|---|---|---|
| 부팅 시 기동 | ✅ `SERVICE_DELAYED_AUTO_START` | ✅ |
| 로그온 불필요 | ✅ | ✅ |
| **크래시 재시작** | ✅ `AppExit Default Restart` | △ 설정 복잡 |
| **폭주 방지** | ✅ `AppThrottle 180s` (모델 로드 25s 감안) | ❌ |
| 표준출력 로깅 | ✅ `AppStdout` | △ |
| **실전 검증** | ✅ 현장 노트북에서 운용 중 | — |

★**이미 검증된 것을 바꾸지 않는다.** `AppThrottle` 이 10초→180초로 조정된 이력이 있다
(모델 로드가 25초라 10초 기준이 무력했다) — 이런 실전 조정이 녹아 있는 자산이다.

---

## 6. 자동 인수시험 — 2단계

### 6-1. 자동 (실패 = **설치 미완료**)

| # | 항목 | 통과 기준 |
|---|---|---|
| A1 | 서비스 기동 | `Get-Service` = Running |
| A2 | `/health` 응답 | HTTP 200, `status=healthy`, `phase=ready` |
| A3 | 모델 로드 | `rfdetr_slots` 전부 `LOADED` |
| A4 | **GPU 사용** | `nvidia-smi` 에 서버 프로세스가 VRAM 점유 |
| A5 | **카메라별 프레임 수신** | 등록 카메라 전부 `last_frame_ts` 갱신 |
| A6 | **알림 채널** | `notify.selftest_state="ok"` · `config_error=null` |
| A7 | **`/alerts/test` 전송** | `sent=true` |
| A8 | `/health` 전 항목 | `problems` 비어 있음 |

### 6-2. 사람 확인 (실패 = **경고**, 설치는 완료)

| # | 항목 | 방법 |
|---|---|---|
| H1 | **검출 1회 이상** | "카메라 앞에 3초간 서 주세요" 안내 → 10초 대기 → person 검출 확인 |
| H2 | 경보 수신 | 폰/메일로 A7 테스트 메시지가 왔는지 사람이 확인 |

★**H1을 설치 실패로 보지 않는 이유**: 설치 시점에 카메라 앞에 사람이 있다는 보장이 없다.
사람이 없는데 "검출 0회"로 실패 처리하면 **오탐**이다. 다만 **경고로 남기고 재시험 명령을 안내**한다:

```
python scripts\acceptance_test.py --only-human
```

### 6-3. 결과 기록

`install_report_<YYYYMMDD_HHMM>.json` 을 **기기에** 저장한다(USB 아님).

```json
{
  "installed_at": "...", "device_name": "...", "profile": "academy",
  "version_tag": "v1.x", "preflight": { "gpu": "RTX 5060", "vram_gb": 8, ... },
  "auto_tests": { "A1": "pass", ..., "A7": "pass" },
  "human_tests": { "H1": "pass|warn|skipped", "H2": "..." },
  "result": "완료 | 미완료(사유)"
}
```

★**둘 다 기록한다.** 자동만 통과하고 사람 확인을 건너뛴 기기가 나중에 "검증됐다"고
오인되지 않게 한다.

---

## 7. 버전·갱신

| 항목 | 방침 |
|---|---|
| USB 표기 | 루트에 `VERSION.txt` — 태그·빌드일·커밋 SHA |
| `/health` 노출 | `version` 에 태그 표시 |
| **갱신 방법** | **새 USB** 또는 온라인 태그 내려받기 |
| **기기에서 git 금지** | 코드는 태그 스냅샷으로만. `.git` 을 넣지 않는다 |

★기기에서 `git pull` 을 허용하면 현장마다 코드가 갈라지고 **무엇이 돌고 있는지 알 수 없게 된다.**
(노트북 ↔ 개발기 분기가 지금 그 상태다)

---

## 8. 위험 항목

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| **R-1** | **RTX 5060 실기 미검증** | sm_120 에서 실제로 도는지 **모른다**. 5070 Ti 로만 검증 | 5070 Ti 로 검증하고 **"5060 미검증"을 설치기에 표시**. 첫 5060 설치 시 A4(GPU 점유)를 반드시 확인 |
| ~~R-2~~ | ~~드라이버 버전 하한 미확정~~ | — | ✅ **해소(2026-09-23)**: CUDA 13.0 Windows 최소 **580**(NVIDIA Release Notes Table 3). 개발기 610.74 동작 확인 |
| ~~R-3~~ | ~~`-Cuda` 기본값이 cu126~~ | — | ✅ **해소(2026-09-23, 커밋 7e2bd08)**: 기본값 cu130 + cu128 미만 선택 시 경고 |
| **R-4** | **두 계보 분리** | 4.07GB 번들 내용을 모른다 | **착수 조건**: 원격 복구 후 비교·통합 |
| ~~R-5~~ | ~~`--gpu` 경로 미실행~~ | — | ✅ **해소(2026-09-23)**: 인터넷 차단 상태에서 빌드·휠교체·GPU 추론까지 실증(§1-3) |
| **R-8** | ★빌드 스크립트가 **stderr 한 줄에 죽었다** | rfdetr FutureWarning 때문에 GPU 빌드가 통째로 실패 | ✅ 수정: `Run` 이 종료코드로만 판정(PS 5.1 NativeCommandError 회피) |
| **R-9** | ★**ORT CUDA 의 조용한 CPU 폴백** (H-2 실측 2026-09-23) | `onnxruntime-gpu` 의 CUDA EP 는 **torch 가 `torch\lib` 을 DLL 경로에 넣어준 덕분에만** 동작한다. torch 없이 세션을 만들면 `cublasLt64_13.dll` 없음으로 **예외 없이 CPU 로 내려앉는다** → PPE 가 조용히 CPU 를 다시 먹는다 | **선택지 (A) 를 채택할 때만 발생**. 채택 시 "CUDA EP 로 안 붙으면 기동 실패 + `/health` 노출" 장치가 필수. 권고안 **(B) torch 통일에서는 이 위험이 없다** — [ppe_gpu_path_2026-09-23.md](ppe_gpu_path_2026-09-23.md) |
| **R-6** | 카메라 IP 할당 방식 기록 없음 | 재부팅 후 IP 가 바뀌면 카메라가 끊긴다 | 1차는 수동 입력. **2차에서 고정 IP 대역으로 해결** |
| **R-7** | USB 분실 | 코드·가중치 유출(토큰·영상은 없음) | 토큰은 USB 에 없다. USB 는 잠긴 곳에 보관 |

---

## 8-1. ★1차 구현 현황 (2026-09-23, 계획 1~6)

| 계획 | 산출물 | 상태 | 검증 |
|---|---|---|---|
| 1 USB 빌드 | `scripts/deploy/build_usb.ps1` · `usb_layout.py`(계약·검증) · `deploy/usb/설치.bat` | ✅ | 테스트 8건 · 스테이징 통과 |
| 2 설치·제거 | `install.ps1`(멱등·업데이트·DryRun) · `uninstall.ps1` · `install_service.ps1` 덮어쓰기 파라미터 | ✅ | DryRun 첫설치·재설치 · **개발기 C:\VIGENT 실설치(-NoService) 2회 → 제거** |
| 3 마법사 | `setup_wizard.py`(명령줄, 각 입력 직후 검증) | ✅ | 테스트 11건(가짜 입력) — ★실카메라·실토큰 미검증 |
| 4 서비스 | 기존 NSSM 스크립트 재사용(`-Root/-PythonExe/-ExtraEnv`) | ⚠ | ★**비관리자 셸이라 실기 등록 미검증** — 관리자 셸에서 `install.ps1`(서비스 포함) 1회 필요 |
| 5 인수시험 | `acceptance_test.py`(A1~A8 자동 + H1·H2 사람 → install_report 합침) | ✅ | 테스트 8건 · 개발기 실설치에서 비대화식 실행(§6-3 결과는 audit/ 보관본) |
| 6 문서 | [usb_install_guide.md](usb_install_guide.md)(현장용) · 이 절 | ✅ | — |
| 승인 항목 1 | 추론 구간 분해 | ✅ | [infer_breakdown_2026-09-23.md](infer_breakdown_2026-09-23.md) |
| 승인 항목 2 | `/health.gpu` 블록 | ✅ | 테스트 · 실설치 `/health` 실측 |
| 승인 항목 3 | 멱등·업데이트·uninstall | ✅ | 위 계획 2 |
| 승인 항목 4 | 런처 기본 --gpu · 조용한 폴백 금지(CRITICAL + `/health.gpu.fallback` + 붉은 배너) | ✅ 확정 | 테스트 5건 · 실설치에서 `--cpu`+기대 강제 → fallback true·CRITICAL 실측 |
| 승인 항목 5 | 벤치 GPU 오염 가드(≥500MB 중단) | ✅ | 테스트 6건 · ★이 개발기 유휴 VRAM 1.5GB 라 임계 500MB 는 항상 막힌다(결정 사항) |

★실설치가 잡은 결함(전부 수정): `.env` 권한(런처 PermissionError) · 남의 VIGENT 서비스를 자기 것으로 봄 · R 권한이라 제거 불가 ·
런처 `--cpu` 가 GPU 로 돌던 것 · 배치 괄호/따옴표 3건 · `usb_layout` docstring `\u` SyntaxError · gpu2 휠 부재.
★사양 검사는 개발기에서도 실제로 거부했다(C: 19.6GB < 20GB) — 인수시험 검증 회차만 `-SkipPreflight` 로 명시적 우회.

## 9. 1차 착수 조건

- [ ] **원격(GitHub) 복구** — 현재 `ls-remote` 404
- [ ] **두 계보 비교·통합** — 4.07GB 번들 vs 2.43GB 포터블 (원격 복구 후)
- [x] `build_portable.ps1` `-Cuda` 기본값 **cu130** 으로 변경 — G-1, 커밋 `7e2bd08`
- [x] `--gpu` 경로 **실제 실행 검증**(개발기 5070 Ti) — G-2, §1-3
- [x] NVIDIA 드라이버 버전 하한 확정 — G-3, **≥ 580**, §1-2
- [x] preflight 스크립트 초안 — G-4, `scripts/deploy/preflight.ps1`

---

## 10. 2차 후보 (기록만 — 구현하지 않음)

### 10-1. ★카메라 네트워크 표준화

**방향**: **VIGENT 자체 PoE 스위치 + 고정 IP 대역(예 `192.168.77.0/24`) + 유선 ONVIF 카메라 1종**

| 근거 | 내용 |
|---|---|
| Tapo C200 은 **Wi-Fi 의존** | 현장 세션 메타에 "현장 Wi-Fi(무선)" — 끊김·지연 위험 |
| **IP 할당 방식 기록 없음** | 고정/DHCP 여부를 **모른다**. DHCP 면 재부팅 후 주소가 바뀔 수 있다 |
| **고객망 분리가 B2G 보안 심사에 유리** | 카메라가 고객 업무망에 붙지 않는다 |
| PoE | 전원·랜을 한 선으로 — 현장 배선이 단순해진다 |

### 10-2. ONVIF 자동 검색

마법사가 대역을 스캔해 카메라 목록을 제시하고 고르게 한다(수동 RTSP 입력 대체).

### 10-3. 화면 마법사

브라우저 기반 `/setup` 페이지를 기존 대시보드에 추가. 명령줄보다 현장 담당자가 쓰기 쉽다.

### 10-4. 원격 상태 수집

여러 현장의 `/health` 를 한 곳에서 본다. ★**영상은 보내지 않는다** — 상태 지표만.

---

## 11. 기존 절차서 처리 (U-4)

`docs/deploy/laptop_update_20260922.md` 는 **"USB 설치기 완성 전 임시 절차"** 로 표기하고
보존한다. 삭제하지 않는다 — 설치기가 나오기 전에 F-34 를 반영해야 할 수 있다.

**목표**: 설치기 1차가 나오면 **노트북·파일럿 데스크톱 2대를 그것으로 재설치**한다.
그러면 두 기기의 코드 분기가 **구조적으로 사라진다**(기기에서 git 을 안 쓰므로).
