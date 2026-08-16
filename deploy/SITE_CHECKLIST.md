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
