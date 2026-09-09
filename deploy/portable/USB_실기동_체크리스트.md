# VIGENT USB 실기동 체크리스트 — 삼성 64GB USB 메모리 (사람이 손으로 하는 절차)

> 대상: 개발 지식이 없어도 따라 할 수 있게 썼다. 명령은 한 줄씩, **개발기의 PowerShell 창**(시작 → "PowerShell" 입력 → 실행)에 그대로 붙여 넣는다.
> 이 문서의 기준값은 2026-09-09 빌드(`D:\vigent_portable`, 2.43 GB)다. 패키지를 다시 빌드하면 파일 수·바이트가 달라질 수 있으니 `PACKAGE_MANIFEST.md` 의 값과 함께 본다.
> Claude Code 는 이 절차를 실행하지 않는다(실제 USB 를 꽂아야 한다). 결과는 아래 기록 칸에 손으로 적는다.

## 합격 기준(미리 선언 — 시험 뒤에 바꾸지 않는다)

| 항목 | 기준 |
|---|---|
| 첫 기동 시간(더블클릭 → 브라우저 관제 화면 `/safety-hub` 열림) | **3분 이하**. 3분을 넘기면 "불합격 아님 · USB SSD 로 매체 교체 검토" 로 분류 |
| `/health` | 검은 창에 "서버 준비 완료" 가 뜨고 브라우저가 열린다(= HTTP 200, status healthy) |
| 모델 슬롯 | 브라우저에서 `http://127.0.0.1:8010/health` 를 열어 `rfdetr_slots` 에 forklift·fire_smoke·ppe 3개가 `LOADED` |
| person 검출 | 웹캠 앞에 사람이 서면 타일에 person 박스가 **1회 이상** 그려진다 |
| 종료 | `VIGENT_종료.bat` 후 작업 관리자에 USB 경로의 python.exe·go2rtc.exe 가 **0개** |
| 정리 | `VIGENT_데이터정리.bat` 후 `app\data` 에 `legal\statutes.yaml` 만 남는다 |

---

## 1. 준비 — USB 확인·포맷 (개발기)

- [ ] 1-1. USB 를 개발기에 꽂는다. 탐색기에서 드라이브 문자를 확인한다(예: `E:`). 아래 명령의 `E:` 는 실제 문자로 바꾼다.
- [ ] 1-2. 파일 시스템을 확인한다. `FileSystem` 열이 **exFAT** 이면 1-4 로 간다.
  ```powershell
  Get-Volume -DriveLetter E | Select-Object DriveLetter, FileSystem, @{n='FreeGB';e={[math]::Round($_.SizeRemaining/1GB,1)}}, @{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}}
  ```
- [ ] 1-3. **FAT32 면 exFAT 로 포맷한다.** ⚠ 포맷은 USB 안의 모든 파일을 지운다. 필요한 파일은 먼저 옮긴다. NTFS 는 쓰지 않는다(USB 메모리에서 안전 제거 없이 뽑으면 손상되기 쉽고, 다른 PC 에서 권한 문제가 난다).
  ```powershell
  Format-Volume -DriveLetter E -FileSystem exFAT -NewFileSystemLabel VIGENT -Confirm:$true
  ```
  (확인을 물으면 `Y`. 끝나면 1-2 를 다시 실행해 exFAT 인지 본다.)
- [ ] 1-4. 여유 용량이 **3 GB 이상**인지 1-2 의 `FreeGB` 로 확인한다.

기록: 드라이브 문자 ____ · 파일 시스템(포맷 전) ____ · (포맷 후) ____ · 여유 ____ GB

## 2. 복사 (개발기)

- [ ] 2-1. 개발기의 서버가 켜져 있으면 끈다(`D:\vigent_portable\VIGENT_종료.bat` 더블클릭).
- [ ] 2-2. 복사 스크립트를 실행한다. USB 안에 `VIGENT` 폴더가 만들어진다(USB 의 다른 파일은 건드리지 않는다).
  ```powershell
  cd D:\vigent_original
  .\scripts\copy_to_usb.ps1 -Drive E:
  ```
- [ ] 2-3. 스크립트 마지막 부분의 `검증: 원본 N 파일 / B ↔ USB N 파일 / B` 에서 **두 값이 서로 같은지** 본다. 2026-09-09 빌드 기준값은 `46,744 파일 / 2,606,144,567 B`(app\data·state 제외 — 개인정보 폴더는 일부러 복사하지 않는다).
- [ ] 2-4. `OK …` 줄 7개(python.exe·go2rtc.exe·가중치 3개·tuning.yaml·VIGENT_시작.bat)가 모두 보이고 `완료: E:\VIGENT` 로 끝나는지 본다. 빨간 오류가 있으면 그 줄을 그대로 적고 중단한다.
- [ ] 2-5. `E:\VIGENT` 안에 `VIGENT_시작.bat`·`VIGENT_종료.bat`·`VIGENT_데이터정리.bat`·`vc_redist.x64.exe`·`사용법.md`·`python`·`app` 이 있는지 탐색기로 본다.

기록: 원본 ____ 파일 / ____ B · USB ____ 파일 / ____ B · 일치(예/아니오) ____ · 소요 시간 ____ 분

## 3. 개발기 자체 검증 — 실제 USB 에서 기동 (`subst` 가 아니라 USB)

- [ ] 3-1. 초시계를 준비한다(휴대폰). 탐색기에서 `E:\VIGENT\VIGENT_시작.bat` 을 더블클릭하는 순간 시작.
- [ ] 3-2. 검은 창에 "서버 준비 완료" 가 뜨고 브라우저가 열리는 순간 정지 → **첫 기동 시간** 기록.
- [ ] 3-3. 브라우저 주소창에 `http://127.0.0.1:8010/health` 를 입력해 `"status":"healthy"` 와 `rfdetr_slots` 의 `LOADED` 3개를 확인한다(포트가 8011 로 바뀌었다고 검은 창에 나오면 8011 로).
- [ ] 3-4. 브라우저가 관제 화면 `http://127.0.0.1:8010/safety-hub` 를 열었는지(로그인 창 없이), 메뉴 `http://127.0.0.1:8010/home` 도 열리는지 확인.
- [ ] 3-5. `E:\VIGENT\VIGENT_종료.bat` 더블클릭 → "N개 종료했습니다" 확인.
- [ ] 3-6. 다시 `VIGENT_시작.bat` 을 더블클릭해 **두 번째 기동 시간**을 잰다(파일 캐시 효과 확인). 끝나면 다시 종료.
- [ ] 3-7. `E:\VIGENT\VIGENT_데이터정리.bat` 더블클릭 → 지울 목록 확인 → `Y` → "남은 파일" 에 `legal\statutes.yaml` 만 있는지 본다.
- [ ] 3-8. 작업 표시줄 "하드웨어 안전하게 제거" 로 USB 를 뽑는다.

기록: 첫 기동 ____ 초 · 두 번째 기동 ____ 초 · /health healthy(예/아니오) ____ · LOADED 3개(예/아니오) ____ · /safety-hub 자동 열림(예/아니오) ____ · /home(예/아니오) ____ · 종료 후 잔존 프로세스 ____ 개

## 4. 제3 PC 실기동 (개발기·현장 노트북이 아닌 Windows 10/11 PC — 파이썬이 설치되지 않은 PC 우선)

- [ ] 4-1. PC 사양을 적는다: 시작 → "시스템 정보"(msinfo32) → 프로세서·설치된 RAM·OS 이름(Home/Pro). 파이썬 유무: 시작 메뉴에 "Python" 이 있는지, 또는 명령창에서 `python --version` 이 "찾을 수 없음" 인지.
- [ ] 4-2. USB 를 꽂고 탐색기에서 `VIGENT` 폴더 → `VIGENT_시작.bat` 더블클릭. 초시계 시작.
- [ ] 4-3. 파란 "Windows 의 PC 보호" 창(SmartScreen)이 뜨면 **"추가 정보" → "실행"**. 떴는지 기록.
- [ ] 4-4. 검은 창에 `[원인] 이 PC 에 Microsoft Visual C++ 재배포 패키지가 없습니다` 가 뜨면: 창을 닫고 USB 의 `vc_redist.x64.exe` 를 더블클릭해 설치(관리자 권한 확인창 "예", 약 1분) → 4-2 부터 다시. 떴는지 기록.
- [ ] 4-5. 브라우저가 열리면 초시계 정지 → 첫 기동 시간 기록. `/health` 의 `healthy`·`LOADED` 3개 확인(3-3 과 같은 방법).
- [ ] 4-6. 웹캠 1대 등록: 브라우저 상단 카메라/관제(허브) → 카메라 추가 → 이름 `테스트`, 주소 `0`(내장 웹캠) 또는 USB 웹캠이면 `1` → 저장 → 타일 ON.
- [ ] 4-7. 사람이 카메라 앞에 2~3초 서 있는다 → 타일에 **person 박스**가 그려지면 통과. 안 그려지면 화면 캡처.
- [ ] 4-8. `VIGENT_종료.bat` → 작업 관리자(Ctrl+Shift+Esc) "세부 정보" 탭에서 python.exe·go2rtc.exe 가 남아 있지 않은지 확인.
- [ ] 4-9. `VIGENT_데이터정리.bat` → `Y` → `legal\statutes.yaml` 만 남는지 확인 → "하드웨어 안전하게 제거".

기록: CPU ____ · RAM ____ GB · OS ____ (Home/Pro) · 파이썬 설치(예/아니오) ____ · 첫 기동 ____ 초 · SmartScreen(예/아니오) ____ · VC++ 안내(예/아니오) ____ · person 검출(예/아니오) ____ · 종료 후 잔존 프로세스 ____ 개 · 오류 메시지 원문: ______________________

## 5. 판정

| 결과 | 분류 |
|---|---|
| 첫 기동 ≤ 3분 · healthy · LOADED 3 · person 1회 이상 · 잔존 0 | **합격** |
| 위 항목 중 person 검출만 실패 | 불합격 — 웹캠 주소·조명 확인 후 재시도, 그래도 안 되면 화면 캡처·`state\logs\vigent.log` 를 개발팀에 |
| 첫 기동 > 3분, 나머지 통과 | **불합격 아님 · USB SSD 로 매체 교체 검토** |
| 검은 창 오류로 기동 안 됨 | 불합격 — 오류 원문·`state\logs\selftest_import.err`·`vigent.log` 를 개발팀에 |

## 주의

- 시험 후 USB 안 `app\data` 에 **사람 얼굴 사진**이 남을 수 있다. 3-7·4-9 의 정리 스크립트를 반드시 실행한다.
- USB 를 타인에게 건네지 않는다. 시험이 끝난 USB 는 잠긴 곳에 보관한다.
- exFAT 는 파일 시각을 2초 단위로 기록한다. 복사 스크립트는 파일 수·바이트·SHA256 표본으로 검증하므로 시각 차이로 오탐하지 않으며, 재복사 시 `robocopy /FFT` 로 같은 파일을 다시 복사하지 않게 했다(2026-09-09 3차; 실제 exFAT 매체 실측은 이 체크리스트에서 한다).
