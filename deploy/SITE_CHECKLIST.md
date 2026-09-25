# VIGENT 현장 설치 필수 조건 체크리스트

> **이 파일은 "현장에 설치하기 전에 반드시 충족해야 하는 조건"만 모은다.**
> 권장·선택 사항은 넣지 않는다 — 여기 있는 항목은 **미충족 시 설치 불가 또는 기능 무효**다.
> 새로 발견되는 현장 필수 조건은 앞으로 전부 이 파일에 추가한다.

---

## N-1. 네트워크 — PC·카메라 고정 IP(DHCP 예약) **필수**

- [ ] 공유기/스위치에서 **처리 PC** 의 MAC 기반 DHCP 예약(또는 고정 IP) 설정
- [ ] 공유기/스위치에서 **모든 카메라** 의 MAC 기반 DHCP 예약(또는 고정 IP) 설정
- [ ] 설정 후 재부팅 1회 하여 주소가 유지되는지 확인

**미적용 시 무엇이 깨지나 (실측 근거)**

| 대상 | 결과 |
|---|---|
| **카메라 IP 변동** | 워커가 등록된 옛 주소로 계속 접속 시도 → **검출 영구 정지**. B3 자동복구(전원차단 후 6~50초 복구)도 **성립하지 않는다** — 주소 자체가 틀리므로 재시도해도 못 붙는다 |
| **PC IP 변동** | 관제 PC·모바일에서 대시보드와 `/health` 주소가 끊긴다. 외부 모니터링도 함께 끊긴다 |

**이 조건이 필수인 이유(관측 사실, 2026-08-16~17)**: 하루 사이 같은 카메라의 IP 가
`192.168.0.4` → `.5` → `.4` 로 두 번 바뀌었고(전원 차단 때마다 재할당), 그 사이 **처리 PC 가
`.5` 를 가져갔다**. DHCP 가 주소를 돌려쓴다는 직접 증거다. 실제로 이 때문에 검출이 멈춰
`data/cameras.json`·`data/camera_secrets.json` 을 **수동으로 고쳐야 했다**(2회).

**설치 후 확인 방법**
```powershell
# PC 주소
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^127\.' }
# 카메라 도달 확인(등록 주소와 일치해야 함)
Test-NetConnection <카메라IP> -Port 554
```
등록된 주소는 `data/cameras.json` 의 `source` 에서 확인한다(자격증명은 `camera_secrets.json`).

---

## 관련 문서 (중복 기재하지 않고 링크만)

- 카메라 설치각·화각·자체 지연 요구: [docs/camera_requirements.md](../docs/camera_requirements.md)
- 네트워크 보안·방화벽(8555 등): [docs/edge_network_hardening.md](../docs/edge_network_hardening.md)
- Windows 서비스 등록(재부팅 자동 기동): [deploy/windows/README.md](windows/README.md)
- 24시간 소크 절차: [docs/SOAK_24H_CHECKLIST.md](../docs/SOAK_24H_CHECKLIST.md)

---

## N-2. 저장 폴더 암호화(BitLocker 또는 EFS) **필수**

> ★**Windows Pro 이상 필수 — Home 은 EFS·BitLocker 둘 다 불가**(2026-08-19 실측:
> 개발 PC(Windows 11 Home)에서 `cipher /e` 가 전 파일 "지원되지 않는 요청입니다"로 0개
> 암호화. Home 에디션은 EFS 미지원이며 BitLocker 관리 기능도 없다 — 장치 암호화(Device
> Encryption)는 별개 기능으로 요건 충족 여부를 별도 확인해야 한다). **현장 장비 OS 는
> 반드시 Pro 이상으로 조달할 것** — `docs/edgebox_purchase_guide.md` OS 요건 연동.

- [ ] 개인영상정보 저장 폴더를 **BitLocker**(볼륨 단위, 권장) 또는 **EFS**(폴더 단위)로 보호
- [ ] 적용 후 `/health` 의 `privacy.storage_encrypted` 가 `true` 인지 확인

**대상 폴더**(개인영상정보가 저장되는 곳)
```
data\evidence          증거 프레임(얼굴 비식별화 적용됨, 그래도 원본 장면이 담긴다)
data\recognition       출입 인식 기록
data\audit             감사 기록
data\tbm               TBM 회의록
data\risk_assessments  위험성평가서
```

**적용 방법 — 둘 중 하나**

*A. BitLocker(볼륨 전체, 권장)* — 관리자 PowerShell:

★**서비스가 LocalSystem 으로 도는 배포에서는 BitLocker 를 쓴다(EFS 아님).** EFS 는 계정별
키라, 서비스(SYSTEM)가 만든 증거 파일을 로그인 계정이 못 여는 상황이 생긴다 — 사고 조사용
증거 반출 절차가 곤란해진다(2026-08-20 판단).

```powershell
# 0) TPM 확인 — 없으면 여기서 멈춘다
Get-Tpm | Select-Object TpmPresent,TpmReady,TpmEnabled,TpmActivated
```
> ★**TpmPresent/TpmReady 가 False 면 진행하지 말 것.** TPM 없이 걸면 부팅마다 암호 입력이
> 필요해져 **B1 무인 운영(재부팅 자동 기동)이 깨진다.** 그 경우 사람 판단으로 되돌아간다.

```powershell
# 1) 암호화 — TPM 보호기로 부팅 시 자동 잠금해제(무인 운영 유지)
Enable-BitLocker -MountPoint "C:" -EncryptionMethod XtsAes256 -UsedSpaceOnly -TpmProtector -SkipHardwareTest
# 2) 복구 키 보호기 추가(TPM 상태가 바뀌어도 열 수 있게)
Add-BitLockerKeyProtector -MountPoint "C:" -RecoveryPasswordProtector
# 3) 진행률 — 100% / FullyEncrypted / On 이 되어야 완료
Get-BitLockerVolume -MountPoint "C:" | Select-Object VolumeStatus,EncryptionPercentage,ProtectionStatus,EncryptionMethod
```

### ★★ 복구 키 백업 — 드라이브 문자를 반드시 먼저 확인할 것

> **2026-08-20 실제 사고**: USB 를 `E:` 로 가정하고 복구 키를 저장했는데, 이 노트북의 `E:` 는
> **내장 AOMEI 복구 파티션**이었다. 실제 USB 는 `G:` 였다. `Out-File` 은 **오류 없이 성공**했고
> 복구 키가 **잠긴 디스크와 같은 기계 안에 평문으로** 저장됐다. 나중에 전수 검색으로 발견해
> 지웠지만, 현장에서 이걸 못 잡으면 ①키가 기계와 함께 도난·분실되고 ②본인은 USB 에 있다고
> 믿는다. **드라이브 문자는 가정하지 말고 매번 조회할 것.**

```powershell
# 1) 실제 이동식 드라이브만 조회 — 여기서 나온 문자만 쓴다
Get-Volume | Where-Object DriveType -eq 'Removable' |
  Select-Object DriveLetter, FileSystemLabel, @{n='GB';e={[math]::Round($_.SizeRemaining/1GB,1)}}

# 2) 위에서 확인한 문자로 저장(<USB> 를 교체)
(Get-BitLockerVolume -MountPoint C:).KeyProtector |
  Where-Object KeyProtectorType -eq 'RecoveryPassword' |
  ForEach-Object { "ID : $($_.KeyProtectorId)"; "KEY: $($_.RecoveryPassword)" } |
  Out-File -Encoding utf8 "<USB>:\VIGENT-BitLocker-복구키.txt"

# 3) ★저장 검증 — 파일이 '이동식' 드라이브에 있는지 되짚어 확인(내용은 열지 않는다)
$f = Get-Item "<USB>:\VIGENT-BitLocker-복구키.txt"
$f | Select-Object FullName, Length, LastWriteTime
(Get-Volume -DriveLetter $f.PSDrive.Name).DriveType   # 'Removable' 이어야 한다

# 4) ★내장 디스크에 잘못 저장된 사본이 없는지 전수 검색
Get-PSDrive -PSProvider FileSystem | ForEach-Object {
  Get-ChildItem "$($_.Root)" -Filter "*BitLocker*복구키*" -Recurse -Force -ErrorAction SilentlyContinue
} | Select-Object FullName
```

- [ ] 이동식 드라이브 문자 **조회로** 확인(가정 금지)
- [ ] 저장 후 `DriveType = Removable` 로 되짚어 검증
- [ ] 내장 디스크 전수 검색 → 잘못된 사본 **0건**
- [ ] USB 는 노트북과 **분리 보관**(같은 가방 금지 — 분실 시 둘 다 잃는다)
- [ ] 복구 키를 채팅·문서·이슈에 붙여넣지 않았는지 확인

> 잘못된 위치에 쓴 사본을 지웠다면, 그 볼륨의 **빈 공간 덮어쓰기**도 검토한다(삭제만으로는
> 미할당 영역에 내용이 남을 수 있다): `cipher /w:E:\` — 시간이 걸리므로 현장 아닌 때 수행.

*B. EFS(폴더 단위)* — 일반 PowerShell로도 가능:
```powershell
cipher /e /s:D:\vigent_original\data\evidence
cipher /c D:\vigent_original\data\evidence   # 각 파일 앞 'E' 표시 확인
```
> EFS 는 **복구 인증서를 반드시 백업**할 것(`certmgr.msc` → 개인 → 인증서 → 내보내기).
> 인증서를 잃으면 암호화된 파일을 영구히 열 수 없다.

**현재 상태 — 장비별로 다르다(2026-08-20 갱신)**

| 장비 | 상태 |
|---|---|
| **학원 현장 노트북**(Windows 10 **Pro**) | ✅ **적용 완료·검증됨** — 아래 실측 |
| 개발 PC(Windows 11 **Home**) | ❌ **적용 불가**(EFS·BitLocker 둘 다 미지원, 2026-08-19 실측) |

*현장 노트북 실측(2026-08-20)*
- TPM 2.0 `Present/Ready/Enabled/Activated` 전부 `True` → **TpmProtector 로 부팅 시 자동
  잠금해제**, B1 무인 운영 유지됨
- `C:` `XtsAes256` · `-UsedSpaceOnly` · `VolumeStatus=FullyEncrypted` ·
  `EncryptionPercentage=100` · `ProtectionStatus=On`
- 재기동 후 `/health` → **`privacy.storage_encrypted: true`, `bitlocker: "on"`** 확인
  (`efs_by_dir` 는 전부 false 지만 볼륨이 BitLocker 로 보호되므로 `true` 가 맞다 —
  `privacy.py` 가 `bitlocker == "on"` 을 우선 판정한다)
- 복구 키: USB 파일 저장 + 내장 디스크 전수 검색 0건 확인(위 사고 사례 참고)

> ★`/health` 의 `bitlocker` 조회는 **관리자 권한**이 필요하다. 서비스는 LocalSystem 이라
> 정상 조회되지만, 일반 사용자 셸로 수동 기동하면 `"unknown"` 이 나온다 — 결함이 아니다.

*개발 PC 잔여 위험(변동 없음)*: `data\evidence` 에 개인영상 프레임 **11,633개**가
비암호화로 쌓여 있다 — **Pro 업그레이드 또는 증거 데이터 현장 이관 시점에 재검토(사람 결정)**.

> ※ 앱 레벨 파일 암호화(Fernet 등)는 만들지 않았다 — 폴더/볼륨 암호화로 처리하고, 앱은
> **검사해서 드러내는 역할만** 한다. 법적 충분성 판단은 이 문서가 하지 않는다(법무 검토 대상).

---

## N-3. 물리 출력(사이렌·경광등) 릴레이 — 모델·IP·채널 확정 **필수**

> 물리 출력을 쓰는 현장에서만 해당. 안 쓰면 `relay.enabled: false`(기본) 그대로 두고
> "화면·메신저 경보만 제공"임을 계약서에 명시할 것.

- [ ] **릴레이 모델** 확정(HTTP GET/POST 제어 지원 여부 확인 — 파일럿은 **HTTP 1채널만** 지원. ★2026-09-26 정정: Modbus TCP 는 미구현이므로 Modbus 전용 릴레이는 동작하지 않는다)
- [ ] **고정 IP** 할당(N-1 과 동일 이유 — IP 가 바뀌면 경보가 물리 출력으로 안 나간다)
- [ ] **채널 번호**(다채널 릴레이인 경우) 확정
- [ ] `config/tuning.yaml` `relay` 설정: `enabled: true`, `url`, `on_duration_s`
- [ ] **ON/OFF 실동작 확인** — 실제로 사이렌이 울리고 **꺼지는지** 눈·귀로 확인
- [ ] **OFF 실패 시 대처 절차**를 현장 담당자와 합의(수동 차단 스위치 위치 등)

**왜 OFF 가 더 중요한가**: 사이렌이 **안 켜지는 것보다 안 꺼지는 것이 최악**이다(소음 민원·
경보 무시 유발·작업 중단). 그래서 OFF 는 ON 보다 재시도를 많이·길게 하고(기본 8회/8초 vs
3회/5초), 최종 실패하면 `/health` 의 `relay.off_failed: true` 로 드러나며 전체 상태가
**degraded** 로 내려간다. 이 신호를 관제에서 반드시 감시할 것.

**기능안전 경계(§8)**: 이 릴레이는 **보조 신호**다. 인증 안전회로(안전 PLC·Type4 방호장치)를
대체하지 않는다. 비상정지의 1차 책임은 인증 하드웨어에 있다.

**현재 상태(2026-08-18)**: 실물 릴레이 미보유 → **mock 서버로만 검증**했다
(`scripts/mock_relay.py`, 10개 시나리오 통과). 실물 연결 시험은 잔여 시험이다.

---

## N-4. 카메라 대수가 **권장 N 이하**인지 확인 **필수**

- [ ] 이 현장의 카메라 대수 = ____대
- [ ] **권장 N 이하인가?** (아래 표)
- [ ] 초과한다면: 처리 장비를 추가하거나(카메라를 나눠 배치), 이 사양에서 재측정할 것

| 사양 | 한계 N | **권장 N** |
|---|---|---|
| RTX 5070 Ti · RF-DETR 4슬롯 · imgsz 384 · 카메라당 2fps | 7대 | **5대** |

**근거**: `benchmarks/capacity_report.md`(2026-08-18 실측). 8대에서 검출 지연 p95 가
116ms → **309ms(2.7배)** 로 무너지고 degraded 가 발생했다. 권장 N 은 한계의 75% —
야간(조명 변화로 검출 증가)·재연결 폭주 여유를 둔 값이다.

★**다른 사양이면 이 숫자를 쓰지 말고 재측정할 것**: `python scripts/capacity_probe.py --max-n 8`

> ⚠️ **재측정 전제 — 모의 소스 영상이 필요하다.** `capacity_probe.py` 는
> `runs/rfdetr/accident/*.mp4` 를 파일 카메라로 등록해 부하를 만든다. 그런데 `runs/` 는
> `.gitignore` 대상이라 **clone 만으로는 없다** — 새 PC 에서 그냥 실행하면
> `모의 소스 영상이 없습니다` 로 종료된다(2026-08-20 현장 노트북에서 확인).
> 개발 PC 에서 `runs/rfdetr/accident/` 를 통째로 복사해 올 것.
> ★**정적 이미지나 합성 영상으로 대체하지 말 것** — 스크립트 주석이 명시하듯 검출 부하가
> 실장면보다 가벼워 **한계 N 이 후하게 나온다**(현장에서 무너질 수를 통과시킨다).

★**GPU 를 키운다고 대수가 늘지 않을 수 있다**: 8대 시점에도 GPU 메모리 18.8%·util 23% 로
**GPU 는 놀고 있었다**. 병목은 CPU 디코드·추론 직렬화 쪽으로 보인다(원인 미확정 —
capacity_report §5). 확장 계획은 CPU 코어 수·프로세스 분리를 함께 검토해야 한다.

## N-5. 오프라인 가중치 — 인터넷 없는 현장은 설치 전에 **전부** 조달 **필수**

> [CODE_REVIEW M7-2b, 2026-09-06] 서버 기동은 RF-DETR 캐시 부재를 즉시 거부하지만, 포즈(rtmlib)는 **첫 사람 검출
> 시점**에 인터넷을 찾는다 — "서버가 떴다"로는 확인이 안 된다(2026-08-21 지게차 영상을 물리자마자 다운로드 관측).

- [ ] `python scripts\fetch_weights.py --all` 실행 → "필수 가중치 전부 확인됨" (required 6종: RF-DETR 4 + rtmlib 2) + 선택 항목까지 — ★[5단계 마무리] `bin\go2rtc.exe`(확대뷰 WebRTC, v1.9.14 win64, sha256 검증)도 이 매니페스트로 받는다(없으면 스냅샷 폴백이라 required 는 아니지만 **오프라인 현장은 미리**)
- [ ] `python scripts\fetch_weights.py --check --all` 로 재확인(다운로드 없이 SHA256 대조) → `bin\go2rtc.exe` 19,737,088B
- [ ] 파이썬 환경은 `scripts\setup_env.py --weights` 로 만들었는지(opencv GUI 빌드 제거·cv2 4.13 headless 검증까지 자동) — 인터넷 없는 곳이면 pip 캐시/휠을 먼저 준비
- [ ] `vigent-core\weights\rtm_cache\hub\checkpoints\` 에 `.onnx` 2파일(101MB + 54MB)이 있는지 확인
- [ ] 서비스(`install_service.ps1`)·개발 런처(`run.ps1`) 모두 `RF_HOME`·`TORCH_HOME` 을 `vigent-core\weights` 계열로 잡는다 — 다른 값을 셸에 넣어 두지 않았는지 확인
- [ ] ★**카메라를 물린 뒤 사람 1명이 지나가는 것까지 확인** — 로그에 `Downloading:` 이 찍히면 실패(캐시 경로 불일치)

```powershell
python scripts\fetch_weights.py --check
Get-ChildItem vigent-core\weights\rtm_cache\hub\checkpoints
Select-String -Path logs\vigent.err.log -Pattern "Downloading:" | Select-Object -Last 3   # 아무것도 안 나와야 정상
```
