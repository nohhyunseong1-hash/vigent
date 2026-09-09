# VIGENT USB 포터블 패키지 — Claude Code 프롬프트

> 사용법: `D:\vigent_original` 에서 Claude Code 를 열고 아래 `---` 사이의 내용을 그대로 붙여 넣는다.
> (프롬프트는 저장소 상태를 직접 읽고 작업하도록 쓰여 있으므로, 반드시 저장소 루트에서 실행한다.)

---

## 목표

`D:\vigent_original`(VIGENT v0.2.0, Python 3.11 FastAPI 감시 서버)을 **USB 메모리에 통째로 넣어, 파이썬이 설치되지 않은 다른 Windows 10/11 노트북에서 USB 안의 `VIGENT_시작.bat` 더블클릭 한 번으로 서버가 뜨고 브라우저가 열리게** 만드는 포터블 패키지를 구축하라.

패키지는 `D:\vigent_portable\` 에 만들고, 완성본을 USB(드라이브 문자는 실행 시 물어보라)로 복사하는 스크립트까지 제공하라.

## 전제 (먼저 읽고 확인할 것)

- `README.md`, `md/DEPLOYMENT.md`, `run.ps1`, `run.bat`, `scripts/setup_env.py`, `scripts/fetch_weights.py`, `weights_manifest.json`, `vigent-core/weights/MANIFEST.md`, `constraints.txt`, `requirements.txt`, `config/tuning.yaml` 의 `detect:` 절, `docs/ops/laptop_validation.md`, `deploy/academy/` 를 먼저 읽어 현재 기동 방식·환경변수·가중치 목록을 파악하라. 추측하지 말고 파일에서 확인한 사실만 근거로 삼아라.
- 현재 `.venv` 는 `pyvenv.cfg` 의 `home` 이 `C:\Users\shgus\AppData\Local\Programs\Python\Python311` 로 박혀 있어 **다른 PC 로 복사하면 동작하지 않는다.** 이 `.venv` 를 복사하는 방식은 쓰지 마라.
- `run.ps1` 은 `py -3.11` 런처가 대상 PC 에 있다고 가정한다. 포터블 패키지에서는 이 가정을 없애야 한다.
- 정본 파이썬은 3.11.9 다(`.python-version`). 포터블도 3.11.x 로 맞춰라.

## 구현 방식 (이 방식으로 하라 — PyInstaller 금지)

torch·opencv·rfdetr·onnxruntime·rtmlib 처럼 무거운 네이티브 패키지를 PyInstaller 로 단일 exe 화하면 깨지기 쉽고 디버깅이 불가능하다. 대신 **Windows Embeddable Python + 상대경로 런처** 방식을 쓴다.

1. `D:\vigent_portable\python\` 에 python.org 의 **Windows embeddable package (64-bit) 3.11.9** (`python-3.11.9-embed-amd64.zip`)를 내려받아 풀어라. SHA256 을 python.org 게시값과 대조하라.
2. `python311._pth` 를 수정해 `import site` 주석을 해제하고 `..\app\vigent-core` 와 `Lib\site-packages` 가 검색 경로에 들어가게 하라. (embeddable 은 기본으로 site-packages 를 안 읽는다 — 이걸 놓치면 아무 패키지도 import 되지 않는다.)
3. `get-pip.py` 로 이 embeddable 파이썬에 pip 을 넣은 뒤, **그 파이썬으로** `requirements.txt` 를 `-c constraints.txt` 와 함께 설치하라. 설치 후 `scripts/setup_env.py` 가 하는 것과 동일하게 opencv GUI 빌드를 제거하고 `opencv-contrib-python-headless==4.13.0.92` 를 `--no-deps` 로 재설치해 `cv2.__version__ == 4.13.0.92` 임을 검증하라.
4. **torch 는 CPU 빌드(PyPI 기본 휠)를 기본으로** 넣어라. 대상 노트북의 GPU 유무·드라이버 버전을 알 수 없고, CUDA 휠은 2.5GB 이상이라 USB 기동을 느리게 만든다. 대신:
   - `config/tuning.yaml` 의 `detect.backend` 를 포터블 프로필에서 `onnx-cpu` 로 두어라(저장소 실측: ONNX Runtime fp32 가 torch fp32 대비 CPU 추론 1.85배, 정확도 손실 0 — `benchmarks/onnx_cpu_bench.md`). 원본 `config/` 는 건드리지 말고 `deploy/academy/` 처럼 **`deploy/portable/` 프로필**을 새로 만들어 오버라이드하라.
   - 런처에 `--gpu` 옵션(또는 `VIGENT_PORTABLE_GPU=1`)을 두어, 대상 PC 에 NVIDIA 드라이버가 있으면 사용자가 원할 때 CUDA 휠(`cu126` 기본, 드라이버 580 이상이면 `cu130`)을 USB 안의 별도 폴더 `python\wheels_cuda\` 에서 오프라인 설치로 전환할 수 있게 하라. 이 폴더는 **선택 사항**이며 `--gpu` 를 안 쓰면 절대 건드리지 않는다.
5. 가중치는 `weights_manifest.json` 의 `required: true` 항목(`rf-detr-nano.pth`, `ppe_rfdetr_v1.pth` 등)과 `detect.backend=onnx-cpu` 경로가 실제로 읽는 `.onnx` 파일을 `vigent-core/weights/` 에서 그대로 복사하되, 매니페스트 SHA256 으로 대조하라. `rtm_cache/`(RTMPose)도 함께 복사하라. **`rf-detr-nano.pth` 가 없으면 rfdetr 이 기동 시 인터넷에서 349MB 를 받으러 가 오프라인에서 실패한다** — 반드시 포함하고, 런처에서 `RF_HOME` 을 USB 안의 weights 폴더로 지정하라.
6. `bin/go2rtc.exe` 는 그대로 포함하라. `deploy/windows/nssm.exe`·서비스 등록 스크립트는 **포함하지 마라**(USB 는 전경 실행이 목적이고, 서비스는 특정 PC 에 고정 설치되는 것이다).
7. 런처 `VIGENT_시작.bat` 를 패키지 루트에 만들어라. 요구사항:
   - 모든 경로는 `%~dp0` 기준 상대경로. 드라이브 문자(D:, E:, F: …)가 바뀌어도 동작해야 한다.
   - `run.ps1` 이 설정하는 환경변수와 동일한 것을 설정하되 USB 기준으로: `RF_HOME`, `TORCH_HOME`, `PYTHONUTF8=1`, `VIGENT_CAPTURE_MODE=thread`, `VIGENT_HOST=127.0.0.1`, `VIGENT_PORT=8010`, 그리고 `deploy/portable/` 프로필을 가리키는 설정.
   - `data/`·`logs/`·`runs/` 같은 **쓰기 경로는 USB 안 `state\` 폴더로** 보내라. 저장소의 `vigent-core/data_paths.py` 가 쓰기 경로를 어떻게 결정하는지 읽고, 환경변수로 바꿀 수 있으면 그것을 쓰고 없으면 최소 침습으로 환경변수 하나를 추가하라(원본 동작은 기본값 그대로 유지).
   - 기동 전 자가진단: `python\python.exe -c "import cv2, torch, onnxruntime, rfdetr, fastapi"` 가 통과하는지, 필수 가중치 파일이 존재하는지, 8010 포트가 비었는지(사용 중이면 8011 로 폴백) 확인하고 실패 시 **한글로 원인을 출력하고 `pause`** 하라. 창이 바로 닫혀 원인을 못 보는 상황을 없애라.
   - 서버가 `/health` 에 200 을 돌려줄 때까지(최대 90초, 기동 후 ~15초는 503 이 정상) 기다린 뒤 브라우저를 `http://127.0.0.1:<port>/home` 으로 열어라. 서버는 같은 콘솔 창에서 전경 실행하고, 창을 닫으면 종료되게 하라.
   - 종료용 `VIGENT_종료.bat` 도 만들어라(같은 포트의 uvicorn·go2rtc 프로세스만 종료).
8. **반출 금지 데이터 절대 제외.** `footage/`, `data/`, `runs/`, `logs/`, `datasets/`, `business_assets/`, `.git/`, `.venv/`, `_archive/`, `audit/`, `reports/`, `.env`, `config/notify.yaml` 의 실제 토큰은 패키지에 넣지 마라(`D:\vigent_field` 와 `D:\vigent_private_data` 는 언급조차 하지 마라). 무엇을 넣고 뺐는지 `PACKAGE_MANIFEST.md` 에 목록과 용량으로 남겨라.
9. 패키지 빌드는 재현 가능한 스크립트 `scripts/build_portable.ps1` 로 만들어라(1~8 을 자동화). 두 번 실행하면 동일 결과가 나와야 하고, 이미 받은 파일은 SHA256 확인 후 재다운로드하지 않는다.
10. `scripts/copy_to_usb.ps1 -Drive E:` 로 USB 에 복사(robocopy, 검증 포함)하라. 최소 여유 용량을 먼저 계산해 부족하면 중단하라.

## 검증 (반드시 실제로 수행하고 결과를 보고하라)

- 빌드 후 `D:\vigent_portable` 의 총 용량, 파일 수를 보고하라. 목표는 **CPU 기본 패키지 4GB 이하**(가중치 ~1.2GB + 파이썬/패키지). 넘으면 어디가 큰지 상위 10개 항목을 보고하라.
- **다른 드라이브 문자로 옮겨도 되는지** 실제로 검증하라: `subst X: D:\vigent_portable` 로 가상 드라이브를 만들고, `X:\VIGENT_시작.bat` 로 기동해 `/health` 가 `status: ok` 이고 rfdetr 슬롯이 LOADED 인지, `/home` 이 열리는지 확인한 뒤 `subst X: /d` 로 해제하라.
- 시스템 파이썬을 못 보게 격리한 상태에서 기동 검증하라: 런처 안에서 `set PATH=%SystemRoot%\System32` 로 PATH 를 잘라도 기동되어야 한다(대상 노트북에 파이썬이 없는 상황을 흉내 낸다). `PYTHONPATH`, `PYTHONHOME` 도 런처 안에서 비워라.
- 인터넷을 끊은 상태(또는 `HTTPS_PROXY=http://127.0.0.1:9` 로 강제 차단)에서 기동해 **가중치를 인터넷에서 받으려다 실패하는 일이 없는지** 확인하라.
- `scripts/offline_probe.py` 가 있으면 그것으로 오프라인 추론 1회를 돌려 person/PPE 검출이 나오는지 확인하라. 없으면 `vigent-core/demo_assets` 의 샘플 프레임으로 `/detect/frame` 을 한 번 호출하라.
- CPU 추론 속도를 보고하라(프레임당 ms, 슬롯별). 현장 판정 fps 는 2fps 였으므로 슬롯 3개 합산이 500ms/프레임 이내면 합격, 넘으면 `detect_every`·해상도 조정 옵션을 포터블 프로필에 제안만 하라(원본 config 는 수정 금지).
- 원본 저장소 `D:\vigent_original` 의 `git status` 가 작업 전후로 **의도한 추가 파일(`deploy/portable/`, `scripts/build_portable.ps1`, `scripts/copy_to_usb.ps1`, 문서) 외에 변경이 없는지** 확인해 보고하라. `.venv`, `config/`, `vigent-core/weights/` 는 건드리지 마라.

## 산출물

1. `D:\vigent_portable\` — 완성된 포터블 패키지
2. `scripts/build_portable.ps1`, `scripts/copy_to_usb.ps1`
3. `deploy/portable/` 프로필(yaml)과 `deploy/portable/README.md`
4. `D:\vigent_portable\사용법.md` — 개발 지식 없는 사람용 한 페이지. USB 꽂기 → `VIGENT_시작.bat` 더블클릭 → SmartScreen "추가 정보 → 실행" 안내 → 브라우저 열림 → 카메라 등록 → 종료 방법. Windows 는 USB 삽입 자동실행(Autorun)이 보안상 막혀 있어 **더블클릭 한 번은 반드시 필요하다**는 점을 명시하라.
5. 위 검증 항목의 실측 결과표(합격/불합격, 수치, 실행한 명령)

## 작업 규칙

- `CLAUDE.md` 의 규칙을 따른다. 지어낸 수치·버전은 쓰지 않는다. 실측하지 못한 항목은 "미측정" 으로 남긴다.
- 원본 코드 수정은 쓰기 경로 환경변수 추가처럼 **포터블 실행에 꼭 필요한 최소한**으로 제한하고, 수정한 파일·이유·원본 동작이 보존됨을 확인한 방법을 보고하라.
- 다운로드는 python.org·pypi.org·download.pytorch.org 공식 출처만 쓴다.
- 막히는 지점(예: rfdetr 이 embeddable 파이썬에서 캐시 경로를 못 찾음, onnx-cpu 경로가 특정 슬롯을 지원하지 않음)은 우회하지 말고 원인과 선택지를 정리해 나에게 물어라.

---

## 참고 — 이 프롬프트를 만든 근거 (저장소 실측)

| 항목 | 확인 내용 |
|---|---|
| 실제 프로젝트 | `D:\vigent_original` (VIGENT v0.2.0). 현장 테스트 보고서 v1.2 가 참조하는 `benchmarks/field_v12_reanalysis.py`, `runs/`, `audit/` 가 여기 있음. `D:\vigent-vision-l1`, `D:\Vision_1`, `D:\비전_추출` 은 8월 초 구버전 |
| 스택 | Python 3.11.9 · FastAPI/uvicorn · RF-DETR(rfdetr 1.8.0) + YOLO 가중치 + ByteTrack(trackers) + RTMPose(rtmlib/onnxruntime) · go2rtc.exe |
| 가중치 | `vigent-core/weights/` 약 1.2GB. `rf-detr-nano.pth`(366MB) 없으면 기동 시 인터넷 다운로드 시도 |
| 현재 실행 | `run.bat → run.ps1` 이 `.venv`(3.11) 또는 `py -3.11` 을 찾음. `.venv` 는 `C:\Users\shgus\...\Python311` 에 종속 → 복사 불가 |
| GPU | 개발 PC RTX 5070 Ti(cu130 필수), 현장 노트북 GTX 1650 Ti. PyPI torch Windows 휠은 CPU 전용. ONNX CPU 경로(`detect.backend=onnx-cpu`)가 이미 구현·실측됨 |
| 반출 금지 | `D:\vigent_field`, `footage/`, `data/`, `runs/` 에 얼굴 식별 가능 영상 존재 (해당 README 명시) |
