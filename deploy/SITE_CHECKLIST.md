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
```powershell
Enable-BitLocker -MountPoint "D:" -EncryptionMethod XtsAes256 -UsedSpaceOnly -PasswordProtector
Get-BitLockerVolume -MountPoint "D:"     # ProtectionStatus = On 확인
```

*B. EFS(폴더 단위)* — 일반 PowerShell로도 가능:
```powershell
cipher /e /s:D:\vigent_original\data\evidence
cipher /c D:\vigent_original\data\evidence   # 각 파일 앞 'E' 표시 확인
```
> EFS 는 **복구 인증서를 반드시 백업**할 것(`certmgr.msc` → 개인 → 인증서 → 내보내기).
> 인증서를 잃으면 암호화된 파일을 영구히 열 수 없다.

**현재 상태(2026-08-17 실측)**: 이 개발 PC 는 **미적용**이다
(`storage_encrypted: false`, EFS 미적용, BitLocker 는 관리자 권한이 없어 `unknown`).
현장 배포 전 반드시 적용할 것.

> ※ 앱 레벨 파일 암호화(Fernet 등)는 만들지 않았다 — 폴더/볼륨 암호화로 처리하고, 앱은
> **검사해서 드러내는 역할만** 한다. 법적 충분성 판단은 이 문서가 하지 않는다(법무 검토 대상).

---

## N-3. 물리 출력(사이렌·경광등) 릴레이 — 모델·IP·채널 확정 **필수**

> 물리 출력을 쓰는 현장에서만 해당. 안 쓰면 `relay.enabled: false`(기본) 그대로 두고
> "화면·메신저 경보만 제공"임을 계약서에 명시할 것.

- [ ] **릴레이 모델** 확정(HTTP 제어 지원 여부 확인 — 파일럿은 HTTP/Modbus TCP 1채널만 지원)
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
