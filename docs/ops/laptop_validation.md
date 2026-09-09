# 현장 배포기(노트북) 검증 패키지 — 순서대로 따라 하는 절차서

> 대상 기기: **현장 노트북** i7-10750H / GTX 1650 Ti 4GB / DDR4 16GB / SSD 1TB / Windows 10 Pro (VIGENT 서비스가 이미 설치·기동되는 상태).
> 목적: 카메라 4대를 24시간 맡겨도 되는지 **숫자로** 확인한다. 합격 기준은 미리 정해져 있고(§3), 측정 뒤에 바꾸지 않는다.
> 소요: 사전 점검 30분 + 4시간 소크 2회(각 약 4시간 50분). 하루에 1회씩 이틀에 나눠 해도 된다.
> 이 문서는 개발 지식이 없어도 따라 할 수 있게 썼다. 명령은 전부 **관리자 PowerShell**(시작 메뉴 → "PowerShell" 검색 → 마우스 오른쪽 → "관리자 권한으로 실행")에서 한 줄씩 붙여 넣고 Enter 한다.
> 근거 문서: `docs/review/FINAL-REPORT.md` §5, `docs/LAPTOP_SIZING_PILOT4.md`, `docs/academy_visit_day.md:718-741`(2026-08-22 램프 실측).

---

## 0. 시작 전 준비물 체크

- [ ] 노트북이 전원 어댑터에 꽂혀 있다(배터리로 재지 않는다).
- [ ] 저장소 폴더 위치를 안다(보통 `D:\vigent_original`). 아래 명령의 `D:\vigent_original`은 실제 위치로 바꾼다.
- [ ] 모의 영상 9개가 `D:\vigent_private_data\runs\rfdetr\accident\*.mp4`에 있다(없으면 개발기의 같은 경로에서 USB로 복사). 실제 카메라로 잴 때는 §5 참고.
- [ ] 텔레그램 알림이 시험 중 실제로 발송될 수 있다(시간당 최대 6건). 시험 전에 관리자에게 "시험 중"이라고 알리거나, `config\notify.yaml`을 시험용 채팅으로 바꿔 둔다.
- [ ] 노트북에서 브라우저·게임·다른 프로그램을 모두 닫는다(측정이 흐려진다).
- [ ] 결과를 적을 §7 표를 인쇄하거나 복사해 둔다.

---

## 1. 사전 점검 ① — 절전 설정 현재 값 조회(5분)

아래를 한 줄씩 실행하고, 출력에서 **"현재 AC 전원 설정 색인"** 뒤의 숫자를 §7-1 표에 적는다. `0x00000000`이면 0(끔), 그 외는 켜짐.

```powershell
cd D:\vigent_original
powercfg /getactivescheme                                   # 현재 전원 관리 옵션 이름
powercfg /a                                                 # 사용 가능한 절전 상태 목록
powercfg /query SCHEME_CURRENT SUB_BUTTONS 5ca83367-6e45-459f-a27b-476b1d01c936   # 덮개를 닫을 때 동작 (0 이어야 함)
powercfg /query SCHEME_CURRENT SUB_SLEEP 29f6c1db-86da-48c5-9fdb-f2b67b1f44da     # 절전 진입까지 시간 (0 이어야 함)
powercfg /query SCHEME_CURRENT SUB_SLEEP 9d7815a6-7ee4-497e-8888-515a05f02364     # 최대 절전 진입까지 시간 (0 이어야 함)
powercfg /query SCHEME_CURRENT SUB_SLEEP 94ac6d29-73ce-41a6-809f-6363ba21b47e     # 하이브리드 절전 (0 이어야 함)
powercfg /query SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226   # USB 선택적 절전 (0 이어야 함)
powercfg /query SCHEME_CURRENT 0012ee47-9041-4b5d-9b77-535fba8b1442 6738e2c4-e8a5-4a42-b16a-e040e769756e   # 디스크 끄기까지 시간 (0 이어야 함)
powercfg /query SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5   # PCIe 링크 절전 (0 이어야 함)
powercfg /devicequery wake_armed                             # 깨울 수 있는 장치 목록(참고)
```

## 1-2. 사전 점검 ② — 절전 전부 해제(스크립트, 5분)

아래 묶음을 **통째로** 붙여 넣는다. 끝나면 `audit\power_<날짜>.txt`에 적용 후 값이 저장된다. 한 줄이라도 빨간 오류가 나면 그 줄을 §7-1 비고에 적고 계속 진행한다.

```powershell
cd D:\vigent_original
# 덮개를 닫아도 아무 것도 하지 않음 (AC / 배터리 둘 다)
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS 5ca83367-6e45-459f-a27b-476b1d01c936 0
powercfg /setdcvalueindex SCHEME_CURRENT SUB_BUTTONS 5ca83367-6e45-459f-a27b-476b1d01c936 0
# 절전·최대 절전·하이브리드 절전 끔 (AC)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP 94ac6d29-73ce-41a6-809f-6363ba21b47e 0
powercfg /h off
# 화면은 꺼져도 됨(무관) — 단 디스크 끄기·USB 선택적 절전·PCIe 절전은 끔
powercfg /change disk-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0
powercfg /setacvalueindex SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20 ee12f906-d277-404b-b6da-e5fa1a576df5 0
powercfg /setactive SCHEME_CURRENT
# 적용 후 값을 파일로 보관
New-Item -ItemType Directory -Force audit | Out-Null
$f = "audit\power_$(Get-Date -Format yyyyMMdd).txt"
powercfg /getactivescheme | Out-File -Encoding utf8 $f
powercfg /query SCHEME_CURRENT SUB_BUTTONS 5ca83367-6e45-459f-a27b-476b1d01c936 | Out-File -Append -Encoding utf8 $f
powercfg /query SCHEME_CURRENT SUB_SLEEP | Out-File -Append -Encoding utf8 $f
powercfg /query SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 | Out-File -Append -Encoding utf8 $f
powercfg /query SCHEME_CURRENT 0012ee47-9041-4b5d-9b77-535fba8b1442 | Out-File -Append -Encoding utf8 $f
"저장: $f"
```

**확인**: 노트북 덮개를 살짝 닫았다가 10초 뒤 열어 본다. 화면이 바로 돌아오고 `Get-Service VIGENT`가 `Running`이면 통과. 그리고 **재부팅 후** §1의 조회 명령을 한 번 더 실행해 값이 그대로인지 확인한다(일부 제조사 유틸리티가 되돌린다).

또 하나: 노트북 제조사 프로그램(예: Lenovo Vantage, Dell Power Manager)에 "배터리 충전 상한 60~80%" 옵션이 있으면 켠다. 24시간 어댑터에 꽂아 두면 배터리가 부푸는 것을 막는다.

## 1-3. 사전 점검 ③ — 정전 후 자동으로 켜지는지(BIOS, 10분)

1. 노트북을 껐다가 켜자마자 제조사 안내 키(F2·Del·F10 중 하나)를 눌러 BIOS 화면으로 들어간다.
2. **Power / Advanced / Configuration** 메뉴에서 이런 이름의 항목을 찾는다: `AC Power Recovery`, `Restore on AC Power Loss`, `Power On AC Attach`, `Wake on AC`, `AC Back`.
3. 있으면 **Power On**(또는 Enabled)으로 바꾸고, 화면을 휴대폰으로 찍어 보관한다. → §7-1 "자동 부팅" 칸에 **있음/설정함**.
4. 없으면 → §7-1 에 **없음**. 이 경우 정전 뒤에는 사람이 켜야 하므로 **UPS**(무정전 전원장치)가 필수이고, 관리자가 서버 죽음을 알 수 있는 외부 알림(FINAL-REPORT P0-1 ③)이 필요하다.
5. 저장하고 나온다. Windows 로 돌아오면 `Get-Service VIGENT` 가 자동으로 Running 이 되는지 본다(지연 자동 시작이라 1~2분 걸린다).

## 1-4. 사전 점검 ④ — 디스크 여유·기기 상태(5분)

```powershell
Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter, @{n='전체GB';e={[math]::Round($_.Size/1GB)}}, @{n='여유GB';e={[math]::Round($_.SizeRemaining/1GB)}}
Get-PhysicalDisk | Select-Object FriendlyName, MediaType, HealthStatus
Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object DeviceId, Wear, Temperature, PowerOnHours     # 관리자 필요, 안 나오면 비고에 "미지원"
Get-CimInstance Win32_Battery | Select-Object EstimatedChargeRemaining, BatteryStatus
powercfg /batteryreport /output "D:\vigent_field\battery_$(Get-Date -Format yyyyMMdd).html"    # 배터리 상태 보고서(브라우저로 열어 '설계 용량' 대비 '완충 용량' 확인)
Get-NetAdapter | Select-Object Name, Status, LinkSpeed                                            # 유선 1Gbps 또는 100Mbps 인지
Get-BitLockerVolume | Select-Object MountPoint, ProtectionStatus                                  # On 이어야 함
Get-Service VIGENT | Select-Object Status, StartType                                              # Running / Automatic
nvidia-smi --query-gpu=name,driver_version,memory.total,temperature.gpu --format=csv
w32tm /query /status                                                                              # 시간 동기 상태(오차·마지막 동기)
```

합격: 저장소가 있는 드라이브 여유 **200GB 이상**, 디스크 HealthStatus **Healthy**, BitLocker **On**, 서비스 **Running**. 값은 §7-1 에 적는다.

---

## 2. 소크(장시간 부하) 시험 — 기본 요령

- "소크"는 카메라 4대를 **4시간** 계속 돌리면서 10분마다 CPU·온도·검출 속도를 자동으로 기록하는 시험이다. 노트북은 처음 10분과 3시간 뒤가 다르기 때문에 반드시 4시간을 채운다.
- 실행 명령 한 줄이 등록→측정→과부하(5·6대)→정리→보고서까지 전부 한다. 실행 중에는 노트북을 만지지 않는다(덮개도 열어 둔다).
- 끝나면 `audit\loadtest_<날짜시각>_<이름>.md` 가 생긴다. 맨 위 "판정" 줄에 **통과 / 미달** 과 사유가 적혀 있다.
- 중간에 멈춰야 하면 창을 닫지 말고 `Ctrl+C` 를 누른 뒤 `python scripts\pilot_load_test.py --phase cleanup` 을 실행해 시험용 카메라를 지운다.

시험 전에 반드시:
```powershell
cd D:\vigent_original
Get-Service VIGENT                                         # Running 확인
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health | Select-Object -ExpandProperty Content   # "status":"healthy" 확인
```
`status` 가 `healthy` 가 아니면(카메라 하나가 끊겨 `degraded` 등) 그 카메라를 먼저 고치거나, 시험에서 빼려면 명령 끝에 `--exclude <카메라id>` 를 붙인다.

---

## 3. 합격 기준(측정 전에 정해진 값 — 바꾸지 않는다)

키트(`scripts\pilot_load_test.py`)가 자동으로 판정하는 기준이다. 보고서의 "판정" 줄이 이 기준을 그대로 쓴다.

| 항목 | 기준 | 보고서에서 볼 곳 |
|---|---|---|
| 검출 주기 | 4대 모두, 10분 창마다 `age p95 ≤ 1.0s` 이고 age ≤ 0.55s 비율 ≥ 90% | 표의 "age p95(대별)" 열 — 전부 1.0 이하 |
| CPU | 10분 창 평균 시스템 CPU **≤ 70%**, 서버 프로세스 **≤ 8.0 코어** | "sysCPU%" · "서버코어" |
| 온도·발열 | 3시간 이후 창의 CPU 클럭 성능(`CPU perf%`)과 GPU 클럭(`GPU clk`)이 **첫 30분 평균의 80% 이상**, GPU 온도 **< 87°C** | "CPU perf%" · "GPU clk" · "GPU°C" — 판정 줄에 "열:" 로 표시 |
| 메모리 추세 | 서버 RSS **≤ 6GB**, 4시간 동안 우상향 기울기 **≤ 100MB/h**, 시스템 가용 ≥ 2GB | "RSS MB" · 판정 줄 "RSS 기울기" |
| 카메라 상태 | 카메라 사유 degraded **0건**(경보 적체 사유는 따로 세고 판정 제외) | "deg cam/alert" — 앞 숫자 0 |
| 프레임 유실 | dropped 증가 ≤ 창 예상 프레임의 1%, 파일 카메라 재연결 0 | "dropped" |
| VRAM | ≤ 3.5GB(4GB 카드 기준) | "VRAM MB" |
| 경보 지연 | 큐 적재→텔레그램 전송 p95 ≤ 5s(채널이 살아 있을 때만; 죽어 있으면 "미측정") | "경보 n/p95s" — ★2026-09-10 이전 배포본으로 잰 값은 F-34 유실 포함 가능(건수 n 이 실제보다 적을 수 있음, `benchmarks/FINDINGS.md`) |
| 지속 시간 | 4h 미만이면 결과는 남되 **무효** | 보고서 "★무효·주의" |
| 과부하(5·6대) | 판정 항목 아님 — 무엇이 벌어지는지 기록만(밀림·드롭·degraded 표시 여부) | "과부하 관찰" 표 |

---

## 4. 1차 — 기준선 4시간 소크(현재 설정 그대로)

```powershell
cd D:\vigent_original
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_base
```
- 약 4시간 50분 걸린다. 끝나면 마지막 줄에 `보고서: D:\vigent_original\audit\loadtest_..._laptop_base.md — 통과/미달` 이 나온다.
- 보고서를 열어 §7-2 표 1행에 옮겨 적는다(10분 창 중 **첫 창·2시간 창·마지막 창** 세 줄과 판정 줄).
- **통과**면 §6 으로 간다(4대 운용 확정 가능). **미달**이면 §5 로 간다.

---

## 5. 2차 — 부하 줄이기(S8+S2+S9) 적용 후 4시간 소크

세 가지를 적용한다. 전부 설정·운영 방법만 바꾸고 프로그램 코드는 건드리지 않는다.

### 5-1. S8 — 카메라를 "서브스트림"(저화질 두 번째 영상) 주소로 등록

카메라는 보통 고화질(메인)·저화질(서브) 두 개의 영상 주소를 낸다. 검출은 저화질로도 되므로(입력이 어차피 384px 로 줄어든다) 서브스트림을 쓰면 노트북이 풀어야 할 영상이 작아진다. 단 화면에서 **사람 키가 너무 작아지면** 검출이 떨어지므로, 등록 후 관제 화면에서 가장 먼 작업자가 화면 높이의 10% 이상으로 보이는지 확인한다(`docs/camera_requirements.md`).

| 카메라 종류 | 메인 스트림 주소 예 | 서브스트림 주소 예 |
|---|---|---|
| TP-Link Tapo C200/C210 | `rtsp://아이디:비밀번호@카메라IP:554/stream1` | `rtsp://아이디:비밀번호@카메라IP:554/stream2` |
| Hikvision 계열 | `.../Streaming/Channels/101` | `.../Streaming/Channels/102` |
| Dahua 계열 | `.../cam/realmonitor?channel=1&subtype=0` | `.../cam/realmonitor?channel=1&subtype=1` |
| 그 외 | 카메라 설명서의 "Sub stream / 2nd stream RTSP URL" | 카메라 설정 화면에서 서브스트림 해상도를 **640×360 이상, 15fps** 로 두면 충분(추정 — 현장에서 사람 크기로 확인) |

등록 방법(둘 중 하나):
- **관제 화면**: 브라우저에서 `http://127.0.0.1:8010/hub` → 카메라 추가 → "source" 칸에 서브스트림 주소 → 저장. 이미 등록된 카메라는 **삭제 후 다시 추가**한다(실행 중인 카메라의 주소 변경은 저장만 되고 적용되지 않는다 — `docs/review/03-video-input.md` I-5).
- **시험용 목록 파일**: 메모장으로 `D:\vigent_field\cams_sub.txt` 를 만들고 한 줄에 서브스트림 주소 1개씩 4줄을 적는다(이 파일은 비밀번호가 들어 있으니 저장소 폴더 밖에 두고 시험 뒤 지운다). 키트는 이 목록으로 카메라를 직접 등록·정리한다.

### 5-2. S2 — 자세(포즈) 추정 주기 낮추기

메모장으로 `D:\vigent_original\config\tuning.yaml` 을 열어 `worker:` 아래 `pose_fps: 2` 를 찾아 `pose_fps: 0.2` 로 바꾼다(줄 앞 들여쓰기는 그대로). 이 값은 "근골격 자세 지표"만 늦출 뿐 침입·근접·보호구·무동작·화재 감지와는 무관하다(`docs/review/FINAL-REPORT.md` §5-3 S2 코드 확인). 저장 후 서비스를 재시작한다:
```powershell
Restart-Service VIGENT; Start-Sleep 60; Get-Service VIGENT
```

### 5-3. S9 — 시연 화면·썸네일 끄기

시험 중에는 노트북·다른 PC에서 `/safety`(시연 페이지)와 `/hub`(관제 화면)를 **열어 두지 않는다**. 관제 화면은 2초마다 서버를 부르고 시연 페이지는 브라우저에서 검출을 또 돌려 노트북 부하를 카메라 1대분만큼 올린다(개발기 실측 "여유 −1대"). 확인이 필요할 때만 잠깐 열고 닫는다.

### 5-4. 2차 소크 실행

```powershell
cd D:\vigent_original
# 실제 카메라 서브스트림으로 잴 때
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --rtsp-list D:\vigent_field\cams_sub.txt --tag laptop_s8s2s9
# 실제 카메라가 없어 모의 영상으로 잴 때(S8 효과는 못 잰다 — 비고에 적을 것)
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_s2s9
```
결과를 §7-2 표 2행에 적는다.

### 5-5. 그래도 미달이면(순서대로 하나씩, 매번 4시간 소크로 다시 잰다)

1. **S10** — `config\tuning.yaml` 의 `onnxruntime:` 아래 `intra_op_threads: 4` 를 `2` 로(그다음 `3`) 바꿔 재시작 후 재측정.
2. **S1** — 카메라 초당 처리 횟수(fps)를 2 → 1.5 로 낮춘다(관제 화면 카메라 편집의 fps, 또는 키트 `--fps 1.5`). ★이 방법은 빠르게 지나가는 사람을 놓칠 위험을 키우므로(FINAL-REPORT P0-3·P0-4) **마지막 수단**이며, 적용하면 개발팀이 재현율을 다시 재야 한다.
3. 그래도 미달이면 개발팀에 §7 표를 보내 대안(카메라 3대 / 노트북 교체)을 결정한다(FINAL-REPORT §5-4).

---

## 6. 실제 카메라 4대를 붙였을 때 추가로 확인할 것(30분)

1. 4대가 모두 관제 화면에 초록(ok)으로 보이는지, `/health` 의 `cameras` 에 4대가 `ok` 인지.
2. 카메라 1대의 전원을 30초 뽑았다 꽂는다 → 관제 화면 배지가 "입력 끊김"으로 바뀌었다가 **2분 안에** ok 로 돌아오면 통과. 돌아오는 데 걸린 시간을 §7-3 에 적는다.
3. 유선인지 확인(`Get-NetAdapter` 의 이더넷이 Up). Wi-Fi 로 붙였다면 §7-3 비고에 적는다 — Wi-Fi 4대는 미검증 상태다.
4. 키트 보고서의 `net_rx_mbps`(수신 대역폭) 값을 §7-3 에 옮긴다.

## 6-2. 실카메라 재현율 측정(반나절) — "사람을 몇 번 중 몇 번 잡았나"

**왜 하나.** 지금까지의 재현율 수치(FINAL-REPORT P0-3, dev 38~42%)는 **사고 재현 영상을 1초 간격 정지사진으로 잘라** 잰 것이다(주간만, 휴대폰 영상, 검수 1인). 현장에 붙일 고정 카메라·거리·조명에서는 다를 수 있다. 개발자 없이도 할 수 있는 최소 절차로 "실카메라에서의 값"을 한 번 만든다. 결과는 P0-3 을 닫는 근거가 아니라 **현장 값**으로 기록된다.

**준비물.** 실카메라 4대 중 **대표 1대**(가장 넓은 구역을 보는 것), 바닥에 테이프로 표시한 **지점 3곳**(카메라에서 가깝게·중간·가장 멀리, 가장 먼 지점은 화면에서 사람 키가 화면 높이의 10% 안팎이 되는 곳 — 자로 재지 말고 관제 화면에서 눈으로 맞춘다), 손목시계 또는 휴대폰 시계(서버 시각과 같은지 §1-4 처럼 확인), 인쇄한 기록표(아래).

**절차(사람 1명, 서버 운영 상태 그대로).**
1. 관제 화면을 켜 두고, 시험 시작 시각을 기록표에 적는다.
2. 지점 ①(가까움)에 가서 **정지 자세로 20초** 서 있는다 → 지점 ②(중간) 20초 → 지점 ③(먼 곳) 20초. 각 지점 도착 시각을 적는다.
3. 지점 ③에서 지점 ①까지 **보통 걸음으로 멈추지 않고** 걸어온다(가로지르기 1회). 출발·도착 시각을 적는다.
4. 2~3 을 **5회 반복**한다(총 정지 15회·가로지르기 5회). 가능하면 밝을 때 3회·어두울 때(조명 켠 저녁) 2회로 나눈다.
5. 두 사람이 가능하면 마지막 1회는 **2명이 동시에**(한 명 정지, 한 명 걷기) 한다.

**채점(개발팀이 서버 기록으로, 사람은 기록표만 넘긴다).** 서버의 인식 로그(`data
ecognition\events_YYYYMMDD.jsonl`, 카메라·시각별 person 박스)를 기록표의 시각과 맞춰 본다. 판정 기준은 dev 측정과 같게 둔다:
- 정지 구간(20초): 그 구간 안에 person 박스가 **연속 3초 이상 끊기지 않고** 있으면 "잡음", 아니면 "놓침". 지점 ③은 "원거리" 로 따로 집계.
- 가로지르기: 출발~도착 사이에 person 박스가 한 번이라도 있고 **구역 침입 경보가 났으면** "잡음". 경보가 없으면 P0-4(통과형 침입) 놓침으로 기록.
- 결과는 "잡음 k / 시도 n" 으로만 적는다. 신뢰구간·퍼센트 환산은 하지 않는다(표본이 작고 서로 독립이 아니다).

**기록표(§7-5 에 옮긴다).**

| 회차 | 조명(밝음/어두움) | 지점① 도착시각 | 잡음/놓침 | 지점② 도착시각 | 잡음/놓침 | 지점③(원거리) 도착시각 | 잡음/놓침 | 가로지르기 출발~도착 | 잡음/놓침(경보 유무) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |
| 4 | | | | | | | | | |
| 5 | | | | | | | | | |

**주의.** 시험 중 텔레그램 경보가 오는 것이 정상이다(시험임을 수신자에게 미리 알린다). 시험 영상 원본은 `scripts\check_raw_capture.py` 로 보존 여부를 확인한다 — 원본이 없으면 나중에 정답지를 만들 수 없다(규칙 11).

---

## 7. 결과 기록 양식(복사해서 채운다)

### 7-1. 사전 점검
| 항목 | 값 | 기준 | 통과 | 비고 |
|---|---|---|---|---|
| 날짜 / 담당자 | | | | |
| 덮개 닫힘 동작 (AC/DC) | / | 0/0 | | |
| 절전 진입(AC) / 최대 절전(AC) / 하이브리드 | / / | 0/0/0 | | |
| USB 선택적 절전 / 디스크 끄기 / PCIe 절전 | / / | 0/0/0 | | |
| 재부팅 후 재확인 | 동일함 / 되돌아감 | 동일함 | | 되돌아가면 제조사 프로그램 이름 |
| 덮개 닫았다 열기 시험 | 서비스 Running 유지 여부 | 유지 | | |
| BIOS 정전 복구 항목 | 있음(설정함) / 없음 | | | 없음 → UPS 필수 |
| 배터리 충전 상한 설정 | 가능(값) / 불가 | | | |
| 디스크 여유 (저장소 드라이브) | GB | ≥ 200GB | | |
| 디스크 상태 / Wear | | Healthy | | |
| BitLocker | On/Off | On | | |
| 이더넷 링크 | Mbps | 유선 | | |
| 시간 동기(w32tm) | 오차 | 정상 | | |
| 서비스 상태 | | Running/Automatic | | |

### 7-2. 소크 결과(보고서 `audit\loadtest_*.md` 에서 옮김)
| 회차 | 태그(파일명) | 소스 | 창 | sysCPU% | 서버코어 | RSS MB | GPU% | VRAM MB | GPU°C | GPU clk | CPU perf% | age p95(4대) | deg cam/alert | 판정 줄(전문) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 기준선 | laptop_base | 파일/실카메라 | 첫 창 | | | | | | | | | | | |
| | | | 2h 창 | | | | | | | | | | | |
| | | | 마지막 창 | | | | | | | | | | | |
| 2 S8+S2+S9 | laptop_s8s2s9 | | 첫 창 | | | | | | | | | | | |
| | | | 2h 창 | | | | | | | | | | | |
| | | | 마지막 창 | | | | | | | | | | | |
| 3 (S10/S1 적용 시) | | | | | | | | | | | | | | |

과부하(5대·6대) 관찰: 밀림(age p95) / 드롭 / degraded 표시 여부 / 경보 지연 — 보고서 "과부하 관찰" 표를 그대로 붙인다.

### 7-3. 실제 카메라 연결 시
| 항목 | 값 | 비고 |
|---|---|---|
| 카메라 4대 주소 종류 | 메인 / 서브 | 비밀번호는 적지 않는다 |
| 서브스트림 해상도·fps | | 사람 키 화면 높이 10% 이상 확인 |
| 4대 ok 확인 시각 | | |
| 전원 차단 복구 시간(초) | | 기준 120초 이내 |
| 유선/Wi-Fi | | |
| net_rx_mbps(4대 수신) | | |

### 7-4. 최종 판정(개발팀·대표 기재)
| 결과 | 조치 |
|---|---|
| 기준선 통과 | 4대 운용 확정. §1-2 절전 설정·UPS·외부 알림은 그대로 필수 |
| 기준선 미달 → S8+S2+S9 통과 | 서브스트림·pose_fps 0.2·시연 화면 금지를 **운영 설정으로 고정**하고 4대 운용 |
| 둘 다 미달 | FINAL-REPORT §5-4: 카메라 3대 / fps 1.0(재현율 재측정) / CPU 상향 노트북 교체(Windows Pro·GPU 4~8GB·발열 설계) 중 결정 |

### 7-5. 실카메라 재현율(§6-2, 개발팀이 채점)
| 항목 | 값 | 비고 |
|---|---|---|
| 카메라 / 지점③ 사람 화면높이 비율 | | 10% 안팎 |
| 정지 잡음 / 시도 (지점①+②) | / | |
| 정지 잡음 / 시도 (지점③ 원거리) | / | dev 원거리 0~8% 와 비교 |
| 가로지르기 경보 / 시도 | / | P0-4 |
| 어두울 때 잡음 / 시도 | / | |
| 원본 영상 보존 확인 | 예 / 아니오 | `check_raw_capture.py` |

---

## 8. 자주 막히는 곳

- `python` 을 찾을 수 없다고 나오면: `.\.venv\Scripts\python.exe scripts\pilot_load_test.py ...` 처럼 앞에 `.\.venv\Scripts\` 를 붙인다.
- "유령 카메라(/health 에만 있음)" 또는 "age 비정상" 으로 중단되면: `Restart-Service VIGENT` 후 2분 기다렸다가 다시 실행한다.
- "running 대수 불일치" 로 중단되면: 카메라 등록은 됐는데 켜지지 않은 것이다. 관제 화면에서 시험용 카메라(`pilot01~`)를 지우고(`--phase cleanup`), 모의 영상 파일 경로가 맞는지 확인한다.
- 시험이 끝났는데 `pilot01~` 카메라가 남아 있으면: `python scripts\pilot_load_test.py --phase cleanup`.
- 결과 보고서의 "미달" 사유에 `VRAM 최대 ... MB > 3.5GB` 만 있고 나머지가 정상이면 다른 프로그램이 GPU 를 쓴 것일 수 있다 — 프로그램을 모두 닫고 다시 잰다.
- 시험 중 텔레그램에 시험 카메라(`파일럿모의N`) 경보가 오면 정상이다(실제 사고 아님). 시험이 끝나면 `data\` 에 남은 시험 증거는 보존 정책(30일)이 자동으로 지운다 — 손으로 지우지 않는다.
