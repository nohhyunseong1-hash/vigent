# 노트북 단축 소크 지시문 (2~3시간) — 안전 리뷰 수정 반영 검증

> **이 문서를 노트북 세션에 그대로 붙여넣으면 된다.**
>
> **왜 도는가**: 2026-08-21 안전 리뷰 수정(F5·F1·F2·F6·F29)이 장시간 동작에 영향을 줄 수
> 있다. 특히 **F6 으로 새 스레드(보존 스윕)가 생겼다** — 24시간마다 디스크를 훑는데,
> 그게 검출을 방해하는지 아무도 본 적이 없다.
>
> **왜 24시간이 아니라 2~3시간인가**: 24시간 소크의 목적은 ①메모리 누수 ②프로세스 사망
> ③경보 유실인데, 이번 변경은 그 셋의 성격을 바꾸지 않는다. 대신 **스윕이 실제로 도는
> 것**을 봐야 하므로 주기를 30분으로 낮춰 2~3시간에 4~5회 실행시킨다. 24시간 전체
> 재실행은 학원 방문 후 변경이 쌓였을 때 한 번에 하는 것이 효율적이다.

---

## 0. 시작 전 확인 (2분)

```powershell
cd C:\Users\1\Desktop\VIGENT     # ← 노트북의 실제 경로로

git pull
python scripts\fetch_weights.py --all --check
```

- [ ] `git pull` 로 `28d903c` 이후 코드를 받았는가
- [ ] **필수 가중치 전부 확인됨** 이 떠야 한다 — 하나라도 없으면 서비스가 안 뜬다
- [ ] 카메라가 붙어 있고 `/health` 가 `healthy` 인가 (`http://127.0.0.1:8010/health`)

---

## 1. 설정 변경 — 스윕 주기를 낮춘다

`config\tuning.yaml` 을 메모장으로 열어 `retention:` 아래 **두 줄만** 바꾼다.

```yaml
retention:
  sweep_initial_delay_s: 60      # 원래 600  ← 1분 뒤 첫 스윕
  sweep_interval_s: 1800         # 원래 86400 ← 30분마다
```

> ⚠**★원복을 빠뜨리면 현장에서 30분마다 스윕한다.**
> 이 값을 되돌리지 않은 채 학원에 가면 노트북이 30분마다 디스크를 훑는다. 파일이 적을
> 땐 티가 안 나지만 증거가 쌓이면 스캔이 길어지고, 시연 도중 스윕이 겹치면 원인 모를
> 지연으로 보인다. **4단계(원복)까지 반드시 끝낼 것.** 지금 알람을 맞춰 두는 것을 권한다.

바꾼 뒤 **관리자 PowerShell** 에서 재시작(설정은 기동 시 1회만 읽는다):

```powershell
Restart-Service VIGENT
```

재시작 후 확인 — 아래 두 가지가 보여야 한다:

```powershell
# 예열 완료(30초쯤 걸린다) 후
curl.exe -s http://127.0.0.1:8010/health | python -c "import sys,json; d=json.load(sys.stdin); print('status:',d['status']); print('sweep:',d.get('retention_sweep'))"
```

- [ ] `status: healthy`
- [ ] `sweep:` 에 `'thread_alive': True` · `'interval_h': 0.5` · `'next_run_in_s'` 숫자
      ★`sweep: None` 이 나오면 **구 코드로 돌고 있다는 뜻**이다 — `git pull` 이 안 됐거나
      재시작을 안 한 것이다. 0단계로 돌아간다.
- [ ] ★**재시작했으므로 `/safety-hub` 는 재로그인이 필요하다**(세션이 메모리에만 있음)

---

## 2. 소크 실행 (2~3시간)

**별도 PowerShell 창**에서 (소크는 `/health` 를 읽기만 하는 별개 프로세스다):

```powershell
python scripts\soak_realcam.py --hours 3 --interval 60
```

> - 창을 닫지 말 것. 노트북이 **절전으로 잠들지 않게** 전원 설정을 확인한다.
> - 소크 중에는 **서비스를 재시작하지 말 것** — 그 시점까지의 결과가 무효가 된다.
> - 카메라 앞을 사람이 오가도 된다(오히려 실제 부하에 가깝다).
> - 기록은 `audit\soak_realcam_<날짜>_<시각>.jsonl` 로 쌓인다.

**소크가 도는 동안 스윕 로그를 따로 봐 두면 좋다**(선택, 또 다른 창):

```powershell
Get-Content logs\vigent.log -Wait -Tail 20 | Select-String "보존 스윕"
```

30분마다 `보존 스윕 완료 — 삭제 N건(...) · 대기 M건 · 소요 X초` 가 찍혀야 한다.

---

## 3. 확인 4항목 (소크 종료 후)

```powershell
# 파일명은 실제 생성된 것으로 (audit 폴더에서 가장 최근 jsonl)
python scripts\soak_report.py audit\soak_realcam_<날짜>_<시각>.jsonl
```

그리고 아래 4가지를 직접 본다 — **이번 변경이 건드린 부분**이다.

| # | 확인할 것 | 어디서 | 합격 |
|---|---|---|---|
| **1** | **스윕이 실제로 돌았나** | `logs\vigent.log` 의 `보존 스윕 완료` 횟수 | **4~5회** · `failures` 0 |
| **2** | **스윕이 검출을 방해했나** | 소크 리포트의 detect 지연 + 스윕 시각 대조 | 스윕 시각 전후로 **detect p95 가 튀지 않음** |
| **3** | **메모리 계단이 생겼나** | 소크 리포트의 RSS 기울기 | **기존 기준 ≤30MB/h** 유지 |
| **4** | **오판 degraded 가 났나** | 소크 기록의 `status` 분포 | 스윕·person 판정 때문에 `degraded`/`unhealthy` 로 **튀지 않음** |

**추가로 볼 것**(F1·F5 수정 확인 — 1분):

```powershell
curl.exe -s http://127.0.0.1:8010/health | python -c "import sys,json; d=json.load(sys.stdin); print('slot_degraded:',d.get('slot_degraded')); print('sweep:',d.get('retention_sweep')); [print('cam',k,'zone=',v.get('zone_source'),v.get('zone_points')) for k,v in (d.get('cameras') or {}).items()]"
```

- [ ] `slot_degraded: {}` — 비어 있어야 정상(F1)
- [ ] `retention_sweep` 의 `runs` 가 4~5, `failures` 0 (F6)
- [ ] 각 카메라의 `zone=` 가 **`camera`**(구역을 그린 경우) 또는 **`none`**(안 그린 경우) —
      ★`global` 이 뜨면 전역 폴백이 켜져 있다는 뜻이니 확인할 것(F5)

### 불합격이면

억지로 통과시키지 말고 **관측된 사실을 그대로** 알려 주면 된다. 특히:
- 스윕 시각과 detect 지연 상승이 겹치면 → 스윕이 검출을 방해한 것 → 주기·시간대 조정 필요
- `failures` 가 0 이 아니면 → `logs\vigent.log` 의 `보존 스윕 실패` 줄과 함께
- `status` 가 튀었다면 → 그 샘플의 시각과 직전 로그

---

## 4. ★설정 원복 (필수 — 빠뜨리면 현장에서 30분마다 스윕한다)

`config\tuning.yaml` 을 **원래 값으로 되돌린다**:

```yaml
retention:
  sweep_initial_delay_s: 600     # ← 되돌림(10분)
  sweep_interval_s: 86400        # ← 되돌림(24시간)
```

관리자 PowerShell 에서 재시작:

```powershell
Restart-Service VIGENT
```

**원복 확인** — `interval_h` 가 **24.0** 이어야 한다:

```powershell
curl.exe -s http://127.0.0.1:8010/health | python -c "import sys,json; d=json.load(sys.stdin); s=d.get('retention_sweep') or {}; print('interval_h:',s.get('interval_h'),'(24.0 이어야 정상)'); print('status:',d['status'])"
```

- [ ] `interval_h: 24.0`
- [ ] `status: healthy`
- [ ] `/safety-hub` 재로그인(재시작했으므로)

> **git 으로 확인하는 방법**도 있다 — 원복이 제대로 됐는지 못 미더우면:
> ```powershell
> git diff config\tuning.yaml
> ```
> 아무것도 안 나오면 원복 완료다(다른 의도한 변경이 없다는 전제).

---

## 5. 보고할 것

소크가 끝나면 아래를 알려 주면 판정하고 문서에 반영한다.

1. `soak_report.py` 출력 전체
2. 확인 4항목 결과(위 표)
3. `slot_degraded` · `retention_sweep` · `zone_source` 출력
4. **설정 원복 완료 여부**(`interval_h: 24.0` 확인했는지)
5. 이상하게 느낀 것이 있으면 그대로 — "느낌"도 단서다

★기록 파일(`audit\soak_realcam_*.jsonl`)은 **지우지 말 것**. 판정 근거이고, 커밋 대상이다.
