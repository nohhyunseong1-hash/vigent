# deploy/portable — USB 포터블 패키지 프로필

> 목적: 파이썬이 없는 Windows 10/11 PC 에서 USB 안의 `VIGENT_시작.bat` 더블클릭 한 번으로 서버가 뜨게 한다.
> 방식: **Windows embeddable Python 3.11.9 + 상대경로 런처** (PyInstaller 미사용). 빌드는 `scripts/build_portable.ps1`,
> USB 복사는 `scripts/copy_to_usb.ps1`. 산출물은 저장소 밖 `D:\vigent_portable\`.

## 이 폴더의 파일

| 파일 | 역할 | 어디로 가나 |
|---|---|---|
| `portable_overrides.yaml` | 원본 `config/tuning.yaml` 에 얹는 차이(현재 `detect.backend: onnx-cpu` 1건). 빌드가 원본을 읽어 이 차이만 적용해 `app\config\tuning.yaml` 을 만든다 — 원본은 불변 | (생성물) `app\config\tuning.yaml` |
| `VIGENT_시작.bat` | 런처. `%~dp0` 상대경로 · PATH/PYTHONPATH/PYTHONHOME 격리 · 자가진단(패키지 import·가중치·포트) · `/health` 200 대기 후 브라우저 · 전경 uvicorn | 패키지 루트 |
| `VIGENT_종료.bat` | 패키지 폴더 아래에서 실행된 프로세스(uvicorn 파이썬·go2rtc)만 종료 | 패키지 루트 |
| `portable_wait.py` | 런처가 `start /b` 로 띄우는 대기·브라우저 열기 보조 | `app\deploy\portable\` |
| `사용법.md` | 비개발자용 한 장 | 패키지 루트 |
| `VIGENT_데이터정리.bat` + `portable_cleanup.py` | 현장 사용 후 `app\data`(증거 사진·인식 기록)·`state\logs` 삭제. 기본은 카메라 등록 보존, `--all` 은 전부 | 패키지 루트 / `app\deploy\portable\` |
| `USB_실기동_체크리스트.md` | 실제 USB(삼성 64GB, exFAT) 복사 → 개발기 실기동 → 제3 PC 실기동을 사람이 손으로 하는 절차·기록 칸·합격 기준(3차) | 저장소만(실행은 사람) |

## 패키지 구조

```
<USB>\
  VIGENT_시작.bat  VIGENT_종료.bat  사용법.md  PACKAGE_MANIFEST.md
  python\        embeddable 3.11.9 + Lib\site-packages(requirements 전체, CPU torch) · python311._pth(site 활성 + ..\app\vigent-core)
  python\wheels_cuda\   (선택) build_portable.ps1 -Gpu 로 받은 CUDA 휠 — VIGENT_시작.bat --gpu 에서만 사용
  app\           저장소 사본(반출 금지 제외) · vigent-core\weights(필수 가중치만, SHA256 대조) · bin\go2rtc.exe · config\tuning.yaml(프로필)
  state\logs\    실행 로그(VIGENT_LOG_DIR)
```

## 런처가 설정하는 환경변수(run.ps1 과 대응)

`PYTHONUTF8=1` · `VIGENT_CAPTURE_MODE=thread` · `VIGENT_HOST=127.0.0.1` · `VIGENT_PORT=8010`(사용 중이면 8011) ·
`RF_HOME=app\vigent-core\weights` · `TORCH_HOME=app\vigent-core\weights\rtm_cache` · `VIGENT_LOG_DIR=state\logs` · `VIGENT_PORTABLE=1` ·
`PATH=<USB>\python;System32…`(시스템 파이썬 차단) · `PYTHONPATH=` `PYTHONHOME=` 비움 · `PYTHONNOUSERSITE=1`.
`VIGENT_ALLOW_PRETRAIN_DOWNLOAD` 는 비워 둔다 → `rf-detr-nano.pth` 가 없으면 인터넷으로 가지 않고 **기동 거부**(guard.py `_require_rfdetr_pretrain`).

## 쓰기 경로 — 결정 사항

- 로그는 `state\logs` (기존 환경변수 `VIGENT_LOG_DIR`, `vlog.py:18`).
- 증거·인식 기록·카메라 등록·경보 큐는 **`app\data`** 에 남는다. 코드 13개 모듈(`data_engine.py` `camera_registry.py` `retention.py` `audit_store.py` `alert_queue.py` `main.py` 등)이 `<앱루트>\data` 를 각자 `_ROOT / "data"` 로 고정하고 있어 환경변수 하나로 돌릴 수 없다. **원본 코드 수정 0** 을 지키기 위해 그대로 두었다(USB 안이므로 대상 PC 에는 남지 않는다). 디렉터리 정션은 절대경로를 저장해 드라이브 문자가 바뀌면 깨지므로 쓰지 않았다.
- 바꾸고 싶으면: 13개 모듈이 공통 헬퍼(예: `data_paths.state_dir()`)를 읽게 하는 코드 변경이 필요하다 — 별도 결정 사항.

## 백엔드 — onnx-cpu 의 의미

- `ppe`·`forklift`·`fire_smoke` 는 `weights\<슬롯>.onnx` 로 ONNX Runtime CPU 추론, `person` 은 .onnx 가 없어 **torch CPU** 로 폴백한다(`rfdetr_adapter.py` [C-3]). 그래서 CPU torch 휠은 어차피 필수다.
- 근거: `benchmarks/onnx_cpu_bench.md`(torch CPU 대비 지연 1.85배 개선, dev 74장 정확도 손실 0). 단 `benchmarks/v2_onnx_report.md` 는 **CPU 사용량이 1.7~2.2배 늘 수 있다**(ORT 스핀)고 실측했고, `onnxruntime.tune_sessions` 기본 on 이후 재측정은 없다. 포터블은 데모·소수 카메라 용도라 지연 우선으로 둔다.

## 빌드·복사

```powershell
cd D:\vigent_original
.\scripts\build_portable.ps1                 # D:\vigent_portable (캐시 D:\vigent_portable_cache) — 재실행 시 SHA 일치 파일은 재다운로드 없음
.\scripts\build_portable.ps1 -Gpu -Cuda cu126   # (선택) CUDA 휠 동봉. 드라이버 580 이상이면 -Cuda cu130
.\scripts\copy_to_usb.ps1 -Drive E:          # E:\VIGENT\ 로 robocopy + 파일 수·바이트·SHA 표본 검증
```

## 검증 방법(빌드 후 개발기에서)

1. `subst X: D:\vigent_portable` → `X:\VIGENT_시작.bat` 기동 → `/health` 200·`rfdetr_slots` LOADED·`/home` 200 → `X:\VIGENT_종료.bat` → `subst X: /d`
2. PATH 격리는 런처 안에서 항상 적용된다(별도 조치 없음).
3. `set HTTPS_PROXY=http://127.0.0.1:9` 로 인터넷을 막고 기동 → `state\logs\vigent.log` 에 다운로드 시도 0.
4. `/detect/frame` 에 `vigent-core/demo_assets/demo1.jpg` 를 넣어 검출 확인 + 슬롯별 지연.

## 검증 결과(2026-09-09, 개발기 DESKTOP-STLQ1LM · Ryzen 9 9900X, 포터블은 CPU 전용 torch)

> **개발기(RTX 5070 Ti, Windows 11) 실측 · 실제 USB 매체·타 노트북·Windows Home·VC++ 미설치 PC 는 미검증.**
> 아래 표는 전부 `D:\vigent_portable` 을 `subst` 가상 드라이브로 띄워 잰 값이다.

| 항목 | 결과 | 수치·명령 |
|---|---|---|
| 패키지 용량·파일 수 | **합격**(목표 4GB 이하) | 2.40 GB · 46,747 파일(`PACKAGE_MANIFEST.md`). python 1,280 MB(torch 496 · cv2 122 · scipy 113 · transformers 101) · app 1,181 MB(가중치 1.19 GB) |
| 다른 드라이브 문자 | **합격** | `subst X: D:\vigent_portable` → `X:\VIGENT_시작.bat` → `/health` 200(17~21초, status `healthy`·phase `ready`), `rfdetr_slots` forklift·fire_smoke·ppe **LOADED**, `/home` 200(5,668 B) → `X:\VIGENT_종료.bat`(python·go2rtc 2개 종료, 잔존 0) → `subst X: /d` |
| 시스템 파이썬 격리 | **합격** | 런처가 PATH 를 `<USB>\python;System32…` 로 자르고 PYTHONPATH/PYTHONHOME 을 비움. 실행 프로세스 실측: `python.exe exe=X:\python\python.exe` |
| 인터넷 차단 기동 | **합격** | `HTTPS_PROXY=HTTP_PROXY=http://127.0.0.1:9` 로 기동 → `vigent.log` 에 download/roboflow/openmmlab/ProxyError 0줄, "RF-DETR 사전학습 캐시 확인: X:\app\vigent-core\weights\rf-detr-nano.pth", 예열 8.87s(person 7.7·ppe 0.6·fire 0.5) |
| 검출 동작 | **합격** | `/detect/frame`(ppe=true) 데모 3장 성공. 현장 프레임 1장(저장소 밖, 패키지 미포함): 단발 호출은 person 0(ByteTrack 트랙 미확정이 정상), 같은 track_key 연속 2회째부터 **person 3명**, ppe Hardhat 0.80·NO-Safety-Vest 0.81. 단독 모델 프로브(포터블 CPU torch)도 person 0.92/0.86/0.75 — 개발 .venv CPU 와 동일 |
| CPU 추론 속도(클라이언트 왕복, 640px, n=5 중앙값) | **합격**(3슬롯 합산 ≤ 500 ms) | person 165~243 · ppe 156~170 · fire_smoke 156~180 · forklift 166 · **person+ppe+fire_smoke 321~423 ms**(2회 측정). 워커 경로(384px)는 더 빠를 것으로 예상하나 **미측정** |
| USB 복사 스크립트 | 가상 드라이브로 확인 | `subst W: D:\vigent_usb_test` → `copy_to_usb.ps1 -Drive W:` — 여유 용량 계산·robocopy /MIR(하위 VIGENT\)·파일 수/바이트/SHA 표본 대조. 실제 USB(exFAT/FAT32)는 **미측정** |
| 원본 저장소 변경 | **없음** | `git status`: 추가 파일만(`deploy/portable/`, `scripts/build_portable.ps1`, `scripts/copy_to_usb.ps1`). 추적 파일 수정 0, `.venv`·`config/`·`vigent-core/weights/` 불변 |
| 데이터 정리(2차) | **합격** | `VIGENT_데이터정리.bat`: 더미 증거 jpg·인식 jsonl·cameras.json·camera_secrets.json·로그 생성 → 기본 모드 `Y`: 7개 삭제, cameras.json·camera_secrets.json·go2rtc.runtime.yaml·legal\statutes.yaml 보존 → `--all`: 3개 삭제, statutes.yaml 만 잔존 → 재실행 "지울 것이 없습니다" |
| USB 복사 시 개인정보 격리(2차) | **합격** | 개발기 `app\data\evidence\dummy.jpg`·`state\logs\dummy.log` 를 만든 뒤 `subst W:` → `copy_to_usb.ps1 -Drive W:`: USB 쪽 `app\data` 에 `legal\statutes.yaml` 만, `state` 파일 0, 검증 46,744 파일/2,606,144,265 B 양쪽 일치. 역방향(USB→개발기) 복사 코드 없음 |

**미검증·주의**
- **VC++ 재배포 패키지 없는 PC**: 포터블에는 `vcruntime140.dll`·`vcruntime140_1.dll`(embeddable 동봉)만 있고 `msvcp140.dll` 은 없다(torch/onnxruntime 이 시스템 것을 쓴다). 그런 PC 에서는 `import torch` 가 `[WinError 126] … Error loading …\torch\lib\*.dll or one of its dependencies` 로 실패한다.
  **대응(2026-09-09 2차)**: `vc_redist.x64.exe`(Microsoft `https://aka.ms/vs/17/release/vc_redist.x64.exe`, v14.44.35211.0, Authenticode **Valid**·CN=Microsoft Corporation, 25,635,768 B)를 패키지 루트에 동봉(빌드 1b 단계, 서명 유효하면 재다운로드 안 함). 런처는 import 실패 시 오류 파일에 `msvcp140`·`vcruntime140`·`DLL load failed`·`WinError 126` 중 하나가 있으면 `[원인] … [조치] 이 USB 의 vc_redist.x64.exe 를 실행 …` 을 출력하고 멈춘다.
  **단위검증(2026-09-09)**: 개발기(Windows 11 Home — Windows Sandbox 미지원, VC++ 는 시스템 전역이라 임시 계정으로도 제거 불가)에서 torch 의존 DLL(`torch\lib\libiomp5md.dll`)을 임시로 이름을 바꿔 같은 종류의 오류(`[WinError 126] … Error loading "…\torch\lib\shm.dll" or one of its dependencies`)를 유도 → 지정 메시지 출력·종료코드 1 확인, DLL 원복 후 `import torch` 정상. **VC++ 가 실제로 없는 PC 의 완전 재현은 미검증**(vc_redist 설치로 해결되는지는 그런 PC 에서 확인해야 한다).
- `--gpu`(CUDA 휠 오프라인 교체)는 코드 경로만 있고 **미실행**(`-Gpu` 로 휠을 받지 않았다).
- Windows Home/Pro, FAT32 USB(4GB 파일 제한은 없음 — 최대 파일 366 MB), 실제 USB 3.0 첫 기동 시간: **미측정**.
- 부수 발견: 개발기 `.venv` 의 torch 가 2026-09-06 20:08 이후 **CPU 빌드(2.12.0+cpu, cuda None)** 다(5단계 5-1 `setup_env.py` 재실행이 PyPI 휠로 교체한 것으로 추정). 그 뒤 개발기에서 잰 GPU 관련 값은 재확인이 필요하다 — 이 작업 범위 밖이라 기록만 남긴다.
