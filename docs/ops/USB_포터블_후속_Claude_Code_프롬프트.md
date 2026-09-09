# VIGENT USB 포터블 — 후속 작업 Claude Code 프롬프트 (2차)

> 사용법: `D:\vigent_original` 에서 Claude Code 를 열고 아래 `---` 사이의 내용을 그대로 붙여 넣는다.
> 1차 작업(포터블 패키지 구축)이 끝난 상태를 전제로 한다.

---

## 배경

1차 작업으로 `D:\vigent_portable\`(2.40GB, 46,747 파일)이 완성됐고 개발기에서 검증 항목을 통과했다. 원본 코드는 수정하지 않았다. 새 파일(`deploy/portable/`, `scripts/build_portable.ps1`, `scripts/copy_to_usb.ps1`, `docs/ops/USB_포터블_Claude_Code_프롬프트.md`)은 아직 커밋되지 않았다.

이번 작업은 네 가지다. **순서대로** 하고, 각 단계 끝에 실측 결과를 보고한 뒤 다음으로 넘어가라. 노트북 2차 소크가 별개로 돌고 있으므로 노트북에는 접근하지 마라.

## 작업 1 — 1차 산출물 커밋

1. `git status` 로 미추적·변경 파일을 나열하고, 1차 작업 산출물 외의 변경이 섞여 있으면 커밋에 넣지 말고 목록만 보고하라.
2. `deploy/portable/README.md` 를 열어 검증 결과 절에 **"개발기(RTX 5070 Ti, Windows 11) 실측 · 실제 USB 매체·타 노트북·Windows Home·VC++ 미설치 PC 는 미검증"** 이 명시돼 있는지 확인하고, 없으면 추가하라.
3. 1차 산출물만 하나의 커밋으로 묶어라. 메시지 예: `feat(portable): USB 포터블 패키지 빌드·복사 스크립트 + portable 프로필(onnx-cpu) + 사용법 — 개발기 검증 통과, 실매체 미검증`. `D:\vigent_portable\` 자체와 `python\`·가중치 사본은 절대 저장소에 넣지 마라(`.gitignore` 에 `vigent_portable/` 이 필요하면 추가).

## 작업 2 — VC++ 재배포 패키지 동봉 + 자가진단 보강

미검증으로 남긴 "VC++ 재배포 패키지가 없는 PC 에서 torch 로드 실패"를 **재현하지 못하더라도 대응은 넣어라.**

1. Microsoft 공식 URL(`https://aka.ms/vs/17/release/vc_redist.x64.exe`)에서 `vc_redist.x64.exe` 를 내려받아 `D:\vigent_portable\vc_redist.x64.exe` 에 두어라. 다운로드 후 파일의 Authenticode 서명을 `Get-AuthenticodeSignature` 로 확인해 `Valid` 이고 서명자가 Microsoft 인지 보고하라. `scripts/build_portable.ps1` 에도 이 조달 단계를 추가하라(멱등: 서명 유효하면 재다운로드 안 함).
2. `VIGENT_시작.bat` 의 자가진단에서 torch import 에 실패했을 때, 오류 문자열에 `msvcp140`·`vcruntime140`·`DLL load failed`·`WinError 126` 중 하나가 포함되면 다음을 한글로 출력하고 `pause` 하라:
   `[원인] 이 PC 에 Microsoft Visual C++ 재배포 패키지가 없습니다. [조치] 이 USB 의 vc_redist.x64.exe 를 실행해 설치한 뒤(관리자 권한, 1분) VIGENT_시작.bat 를 다시 실행하세요.`
   그 외 import 실패는 기존 메시지를 유지하라.
3. 재현 시도: 임시 사용자 계정이나 Windows Sandbox 를 쓸 수 있으면 VC++ 없는 환경을 만들어 실제로 위 메시지가 나오는지 확인하라. 불가능하면 `python\` 폴더에 임시로 `msvcp140.dll` 이 로드되지 않게 하는 방법(예: `python\python.exe` 실행 시 `PATH` 를 `System32` 제외로 잘라 보기)으로 **오류 문자열 분기만이라도** 단위 검증하고, 완전 재현은 "미검증" 으로 남겨라. 지어낸 검증 결과는 쓰지 마라.

## 작업 3 — USB 안 개인정보(증거 사진) 정리 절차

1차에서 증거 이미지·인식 기록·카메라 등록이 `D:\vigent_portable\app\data\` 에 남는 구조로 두기로 결정했다(코드 수정 0 유지). 이 폴더에는 얼굴이 식별 가능한 이미지가 쌓이므로 다음을 만들어라.

1. `VIGENT_데이터정리.bat` 를 패키지 루트에 추가하라. 동작: `app\data\` 안의 증거 이미지·기록 파일과 `state\logs\` 를 지우되, **카메라 등록 정보(어떤 파일인지 `vigent-core/camera_registry.py` 와 `data_paths.py` 를 읽어 특정하라)는 남기는 것을 기본**으로 하고 `--all` 인자를 주면 카메라 등록까지 지운다. 지우기 전에 삭제 대상 파일 수·용량을 보여 주고 `Y` 확인을 받아라. 삭제 후 남은 파일 목록을 보여 줘라.
2. `사용법.md` 에 "현장 사용 후 반드시 `VIGENT_데이터정리.bat` 실행 — USB 안에 사람 얼굴이 찍힌 사진이 남는다. USB 를 다른 사람에게 넘기거나 분실 위험이 있는 곳에 두기 전에 실행할 것" 절을 추가하라.
3. `scripts/copy_to_usb.ps1` 를 열어 (a) `D:\vigent_portable\app\data\` 와 `state\` 를 USB 로 복사할 때 **개발기 쪽에 쌓인 실데이터가 딸려가지 않는지**, (b) USB → 개발기 방향 복사(역방향)가 없는지 확인하라. 딸려간다면 `app\data\`·`state\logs\` 를 robocopy 제외 목록에 넣고 빈 폴더 구조만 만들어라. 검증: 개발기 `app\data` 에 더미 파일 하나를 넣고 `subst` 드라이브로 복사한 뒤 더미가 복사되지 않았음을 확인하고, 더미를 제거하라.

## 작업 4 — 개발기 .venv torch CUDA 빌드 복구 + FINDINGS 기록

부수 발견: 개발기 `.venv` 의 torch 가 2026-09-06 20:08 이후 CPU 빌드(`2.12.0+cpu`, `torch.cuda.is_available() == False`)다. `scripts/setup_env.py` 재실행(5단계 5-1)이 PyPI 휠로 바꾼 것으로 추정된다.

1. 복구 전 현재 상태를 기록하라: `.venv\Scripts\python -c "import torch, torchvision; print(torch.__version__, torchvision.__version__, torch.cuda.is_available())"` 와 `nvidia-smi` 의 드라이버 버전.
2. `README.md`·`requirements.txt` 주석의 정본 명령으로 복구하라:
   `.venv\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cu130 torch==2.12.0+cu130 torchvision==0.27.0+cu130`
   드라이버가 580 미만이면 멈추고 보고하라(cu126 으로 임의 변경 금지).
3. 복구 후 `torch.cuda.is_available() == True`, `torch.cuda.get_device_name(0)` 에 RTX 5070 Ti, 그리고 실제 텐서 연산 한 번(`torch.ones(1000,1000,device="cuda") @ torch.ones(1000,1000,device="cuda")`)이 되는지 확인하라. `cv2.__version__ == 4.13.0.92`, `numpy == 2.4.6` 이 불변인지도 확인하라(torch 재설치가 numpy 를 끌어올리는 사례가 저장소에 기록돼 있다).
4. `py -3.11 -m unittest discover -s tests` 를 돌려 662 OK 가 유지되는지 확인하라.
5. 재발 방지: `scripts/setup_env.py` 를 읽고, 이미 CUDA 빌드 torch 가 설치돼 있으면 **PyPI CPU 휠로 덮어쓰지 않도록** 하는 최소 수정을 제안하라(예: 설치 전 `torch.version.cuda` 를 검사해 CUDA 빌드면 torch/torchvision 을 건너뛰고 경고 출력). 수정은 **제안과 diff 까지만** 하고 적용은 내 승인 후에 하라 — 이 스크립트는 노트북 서비스 설치 경로와도 연결돼 있다.
6. `benchmarks/FINDINGS.md` 에 새 F-항목을 추가하라: 발생 시각, 원인 추정, 영향 범위(2026-09-06 20:08 이후 개발기에서 잰 GPU 관련 수치 전부 — 어떤 문서·표의 어떤 수치인지 `git log --since=2026-09-06` 로 찾아 나열), 복구 명령, 재발 방지 제안. 영향받은 수치는 각 문서에 "★재측정 필요(F-xx)" 주석만 달고 값은 지우지 마라.
7. 작업 2~4 의 변경을 작업별로 커밋 3개로 나눠라. 작업 4 의 `setup_env.py` 수정은 승인 전이므로 커밋에 넣지 마라.

## 보고 형식

각 작업마다: 실행한 명령 → 실측 결과(수치·경로·종료코드) → 합격/불합격/미검증. 미검증 항목은 이유를 적어라. 원본 저장소 `git status` 를 작업 전후로 첨부하라.

## 작업 규칙

- `CLAUDE.md` 의 규칙을 따른다. 지어낸 수치·버전은 쓰지 않는다.
- 노트북(소크 진행 중)에는 접근하지 않는다.
- `config/`, `vigent-core/weights/`, `D:\vigent_field`, `D:\vigent_private_data` 는 읽기만 하고 수정·복사하지 않는다.
- 막히면 우회하지 말고 원인과 선택지를 정리해 나에게 물어라.

---
