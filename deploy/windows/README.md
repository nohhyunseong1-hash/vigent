# Windows 서비스 배포 (B1)

재부팅·크래시 후 VIGENT 가 **사람 개입 없이** 다시 뜨게 한다. NSSM 으로 서비스 등록한다.

```powershell
# 관리자 권한 PowerShell 에서
cd deploy\windows
.\install_service.ps1              # 등록 + 기동 (기본: 0.0.0.0:8010)
.\service_status.ps1               # 서비스 상태 + /health 검출 생존 확인
.\uninstall_service.ps1            # 제거 (logs/·data/ 는 보존)
```

- **NSSM 이 없으면** install 이 다운로드 방법을 안내하고 멈춘다(`nssm.exe` 를 이 폴더에 두거나 `winget install NSSM.NSSM`).
- 시작 유형은 **지연 자동(Delayed Auto)** — 부팅 후 네트워크·GPU 드라이버가 준비된 뒤 뜬다.
- 죽으면 **5초 뒤 자동 재시작**(`AppExit Default Restart`).
- 로그는 `logs\vigent.out.log` / `vigent.err.log`, **256MB 마다 로테이션**(약 2GB 상한).
- 기동 후 **약 15초는 예열 구간**이라 `/health` 가 `phase=starting` + HTTP 503 이다 — 정상이다(B4).
- `service_status.ps1` 종료코드: `0` healthy · `1` degraded · `2` unhealthy/starting · `3` 무응답.

> DEPLOYMENT.md 는 아직 맥 기준이라 이 폴더의 절차와 다르다 — 재작성은 B7 과제다.
