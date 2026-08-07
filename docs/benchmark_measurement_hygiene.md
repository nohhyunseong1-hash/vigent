# 벤치마크 측정 위생 — Docker/WSL2 설치 후 주의사항 (2026-08-07 신설)

## 배경

이 개발 데스크탑은 **CPU 전용 torch 환경**이다(GPU 없음 — `guard.detect`/`model.predict` 등 추론은
전부 CPU에서 돈다). 2026-08-07 이 데스크탑에 **Docker Desktop(WSL2 백엔드)**을 설치했다(CVAT 로컬
실행용, `docs/labeling_guide.md` §3-1). Docker Desktop이 켜져 있으면 `vmmem`(WSL2 VM) 프로세스가
백그라운드에서 CPU 코어를 점유한다 — 실측 확인: Docker Desktop을 설치·기동한 상태에서 `vmmem`
프로세스가 상시 실행 중임을 확인했다(이 저장소 작업 중 `tasklist`로 직접 확인).

**결과적으로 CPU 추론 시간(지연·속도) 측정값이 실제보다 느리게 나올 수 있다** — 검출 정확도(mAP·
recall 등)에는 영향 없다(같은 모델이 같은 출력을 냄, 느려질 뿐 결과가 바뀌진 않음). **영향받는 건
"몇 ms 걸리는가"를 재는 측정뿐**이다.

## 원칙 — 막지 않는다, 표시만 한다(사용자 지시)

측정 자체를 차단하지 않는다 — Docker가 떠 있어도 스크립트는 정상 실행되고 결과도 나온다. 대신
**결과에 오염 가능성을 경고로 표기**해, 그 결과를 나중에 인용할 때 "이 수치는 Docker가 떠 있는
상태에서 쟀을 수 있다"는 걸 놓치지 않게 한다.

## 구현 — `benchmarks/env_guard.py`

`benchmarks/env_guard.py`의 `warn_if_docker_running(script_name)`을 지연·속도 측정 스크립트의
`main()` 최상단에서 호출한다. 두 가지 신호로 감지한다(윈도우 전용, 다른 OS에서는 조용히 통과):
1. `tasklist`로 Docker 관련 프로세스명(`Docker Desktop.exe`, `com.docker.backend.exe`, `vmmem` 등)
   검색 — Docker Desktop 버전에 따라 실행 파일명이 다를 수 있어 최선노력(못 잡을 수 있음).
2. `wsl.exe -l --running`으로 현재 실행 중인 WSL 배포 확인 — Windows 내장 명령이라 더 신뢰할 수
   있음(Docker Desktop은 `docker-desktop`/`docker-desktop-data` 배포를 씀).

감지되면 `stderr`에 경고 1줄을 출력하고(측정은 계속 진행), 이 문서를 가리킨다.

**적용된 스크립트** (guard.detect/model.predict 등 실제 torch 추론 시간을 재는 것들만 — 정확도만
재는 스크립트나 캐시된 검출 결과를 재생하는 시뮬레이션 스크립트는 대상 아님, 오염될 게 없음):
- `benchmarks/g2g_latency_budget.py` (① 검출 in-process 타이밍)
- `benchmarks/webcam_bench.py` (HTTP 경유 latency_ms)
- `benchmarks/run_eval.py` (raw/pipeline 두 트랙 모두 latency 기록)

`benchmarks/local_slowdown_ab.py`·`pose_follow_ab.py`·`ppe_anchor_ab.py` 등은 **사전 녹화된
detection 캐시(JSON)를 재생**하는 시뮬레이션이라 라이브 torch 추론이 없다 — Docker 오염과 무관해서
대상에서 뺐다.

## ★측정 전 절차 — 정확한 수치가 필요할 때

경고가 뜨거나, 애초에 오염 없이 재고 싶으면 측정 전에:

```powershell
# 1) Docker Desktop 완전 종료 (트레이 아이콘 우클릭 → Quit Docker Desktop, 또는:)
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2) WSL2 VM까지 확실히 내리기(Docker Desktop만 끄면 vmmem이 잠시 남아있을 수 있음)
wsl --shutdown

# 3) 확인 — vmmem이 사라졌는지
Get-Process vmmem -ErrorAction SilentlyContinue   # 아무 것도 안 나오면 정상
```

측정이 끝나면 다시 Docker Desktop을 켜서 CVAT 등을 재사용하면 된다.

## 과거 측정치는 영향 없음 (규칙7)

Docker Desktop/WSL2는 **2026-08-07 이 세션에서 처음 설치**됐다(그 전까지 `docker`/`wsl --status`
전부 미설치로 반복 확인됨, `git log` 상 이 문서 이전 커밋들은 전부 그 설치 이전 작업). **따라서 이
문서보다 먼저 커밋된 모든 벤치마크 결과(예: `benchmarks/g2g_latency_budget.md`의 156.3ms 총 지연,
`benchmarks/EVAL.md`의 latency 기록(측정일 2026-07-04), `benchmarks/local_slowdown_ab.md`의
extrapCap 비교)는 이 오염 우려와 무관하다** — 재측정할 필요 없음. 앞으로 이 문서 커밋 이후 새로
측정하는 latency/속도 수치만 이 절차를 따르면 된다.
