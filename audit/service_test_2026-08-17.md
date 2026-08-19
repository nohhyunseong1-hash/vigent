# [B1] Windows 서비스 등록 시험 (2026-08-17)

> 대상: `deploy/windows/install_service.ps1`(NSSM). 감사 🔴B1 — 재부팅 후 자동 기동 부재 해소.
> 실행 주체: 사용자(관리자 권한 PowerShell). 검증 일부는 Claude 세션에서 확인.

## 결과 요약

| # | 시험 | 결과 | 근거 |
|---|---|---|---|
| 1 | 서비스 등록 | ✅ **성공** | `install_service.ps1` → 서비스 `VIGENT` 생성·기동 |
| 2 | 기동 후 정상화 | ✅ **성공** | 등록 직후 HTTP 503(예열) → 약 30초 후 `HTTP 200 status=healthy phase=ready test=ok(f0.1/d0.5)` |
| 3 | 방화벽 개방 | ✅ 완료 | `New-NetFirewallRule "VIGENT 8010"` (TCP 8010, Private 프로파일) |
| 4 | 강제 kill → 자동 재기동 | ✅ **완료(2026-08-20)** | 관리자 세션에서 실측 — 재바인드 총 10.0s(AppRestartDelay 5s 포함) · healthy +28.8s · 카메라 자동 복귀. [`human_tests_2026-08-20.md`](human_tests_2026-08-20.md) T2 |
| 5 | 재부팅 → 로그인 전 `/health` | ⏸ **대기** | 사용자가 별도 시점에 수행 예정 |

**B1 현재 상태: 서비스 등록·healthy 확인 완료, 재부팅 시험 대기.**

## 확인된 것

- 서비스가 **지연 자동 시작(Delayed Auto)** 으로 등록됐고 기동 직후 정상 동작한다.
- **예열 구간이 설계대로 드러난다**: 등록 직후 `HTTP 503`, 약 30초 뒤 `healthy`.
  B4(예열↔워치독 분리)가 서비스 환경에서도 그대로 작동함을 확인.
- 카메라 워커가 서비스 컨텍스트에서 정상 기동한다(`test=ok`, frame 0.1s / detect 0.5s).
  → LocalSystem 계정으로도 `data/camera_secrets.json` 읽기·RTSP 접속에 문제가 없다.

## 발견해 수정한 결함 (2건)

### ① PowerShell 5.1 이 BOM 없는 UTF-8 을 ANSI 로 읽어 스크립트가 파싱 불가
한글 주석이 깨지면서 따옴표 짝이 무너져 **스크립트가 실행조차 안 됐다**. 세 스크립트를
UTF-8 BOM 으로 저장해 해소(`Parser.ParseFile` 3종 구문 검증 통과). 현장 배포에서 그대로
터졌을 문제다.

### ② `service_status.ps1` 이 "응답 없음"과 "기동 중"을 구분 못 함
사용자 관측: 등록 직후 `HTTP 503 | status= phase= | 카메라 없음` — 상태값이 **빈칸**으로 찍혔다.
원인은 기동 극초기에 HTTP 코드는 오는데 **본문이 비어 있거나 JSON 이 아닌** 구간이 있고,
`ConvertFrom-Json` 결과가 `$null` 이면 `$h.status` 가 빈 문자열이 되어 "무응답"과 구별이 안 되던 것.
수정: 본문 파싱 실패를 명시 분기해 **"앱 기동 중 — /health 본문 아직 없음"** 으로 표시하고,
`starting` 은 장애(빨강)가 아니라 준비 중(노랑)으로 구분해 `← 예열 중(약 15초), 정상` 힌트를 붙였다.

## 잔여 — 사람이 해야 할 시험

### (A) 강제 kill 후 5초 내 재기동
**관리자 권한 PowerShell**에서:

```powershell
$p = (Get-NetTCPConnection -LocalPort 8010 -State Listen | Select-Object -First 1).OwningProcess
"kill PID $p"; $t0 = Get-Date
Stop-Process -Id $p -Force
for ($i=0; $i -lt 60; $i++) {
  Start-Sleep -Milliseconds 500
  $c = Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c -and $c.OwningProcess -ne $p) { "새 PID $($c.OwningProcess) — 소요 $([math]::Round(((Get-Date)-$t0).TotalSeconds,1))초"; break }
}
```
합격 기준: **10초 이내 새 PID 로 8010 재기동**(NSSM `AppRestartDelay` 5초 + 프로세스 기동 오버헤드).
※ 재기동 직후 약 15초는 예열 구간이라 `/health` 가 503 인 것이 정상이다.

### (B) 재부팅 → 로그인 전 `/health`
다른 기기(폰·맥)에서 같은 WiFi 로:
- 폰 브라우저: `http://192.168.0.5:8010/health`
- 맥: `curl -s http://192.168.0.5:8010/health | python3 -m json.tool`

합격 기준: **로그인하지 않은 상태에서** `"status":"healthy"` 와 `"cameras":{"test":{"status":"ok"…}}`.

★주의: PC IP(192.168.0.5)가 **DHCP** 라 재부팅 후 바뀔 수 있다. 실제로 이 주소는 몇 시간 전
카메라가 쓰던 주소다 — DHCP 가 주소를 돌려쓰고 있다는 증거. 현장에서는 **PC·카메라 모두
고정 IP(DHCP 예약)** 가 필수다(백로그 등록 대상).
