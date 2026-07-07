# VIGENT 배포 가이드 (C-S1/S2)

## 설치 경로 제약 (중요 — macOS)
- **macOS 에서 launchd 자동기동/워치독을 쓸 경우, 앱을 `~/Desktop`·`~/Documents`·`~/Downloads` 안에 두지 말 것.**
  - 이유: macOS **TCC(개인정보 보호)** 가 이 폴더들을 보호한다. launchd 에이전트로 실행되는 프로세스는
    기본적으로 이 폴더에 접근이 거부되어(`Operation not permitted` / `getcwd 실패`) 서버가 기동하지 못한다.
  - **권장 설치 경로**: `/usr/local/vigent`, `/opt/vigent`, 또는 `~/vigent`(홈 루트 하위 사용자 폴더).
  - 대안: 시스템 설정 → 개인정보 보호 및 보안 → 전체 디스크 접근에서 `bash`/런처에 권한 부여(비권장, 취약).
  - **실증**: `~/Desktop/VIGENT` 에서 launchd 기동 실패(TCC) → `~/vigent_deploy_test`(비보호)에서 kill→자동재기동 정상(PID 교체·/health 200).
- Linux(systemd) 에는 이 제약이 없다.

## 프로세스 생존
- **Linux**: `deploy/systemd/vigent-edge.service`(Restart=always) + `vigent-watchdog.{service,timer}`(/health 30초 점검).
- **macOS**: `deploy/launchd/com.vigent.edge.plist`(KeepAlive=true). `__INSTALL_DIR__` 를 실제 경로(위 제약 준수)로 치환.
- 공통 워치독 로직: `deploy/watchdog.sh`(/health N회 실패 시 재기동).

## 바인딩 · 인증 (C-S0)
- 기본 `VIGENT_HOST=127.0.0.1`(로컬 전용, 무토큰). 외부 노출은 `VIGENT_HOST=0.0.0.0` + `VIGENT_API_TOKEN=<비밀>` 필수.
  - 무토큰 + 0.0.0.0 조합은 **기동 거부**(무인증 노출 방지).
- 토큰 설정 시 전 라우트 Bearer 인증(`/health`·`/favicon.ico` 예외). 웹훅 목적지는 `config/security.json` 화이트리스트.

## 가중치 배포 (C-S1)
- 이미지/패키지에 가중치 미포함. `weights_manifest.json`(SHA256) + `fetch_weights.py` 로 검증 다운로드.
  - `python fetch_weights.py verify` (무결성) / `python fetch_weights.py download`(URL: `VIGENT_WEIGHTS_BASE_URL`).
- Docker 는 가중치를 볼륨 마운트: `-v $PWD/vigent-core/weights:/app/vigent-core/weights`.

## Docker (C-S2)
- `docker build -t vigent:0.2.0 .` (가중치 제외, opencv headless 단일화 자동 정리).
- 실행: `docker run -p 8010:8010 -e VIGENT_HOST=0.0.0.0 -e VIGENT_API_TOKEN=<비밀> -v <weights> vigent:0.2.0`
  - 컨테이너는 `0.0.0.0` 바인딩 필요(포트 매핑) → 토큰 필수.
- 이미지 크기 ~9.5GB(torch 풀스택). CPU-only 휠/멀티스테이지로 축소 여지 있음(후속).

## 로깅 (C-S1)
- `VIGENT_LOG_LEVEL`(기본 INFO). 콘솔 + 파일 로테이션(`logs/vigent.log`, 10MB×5).
- 경보 이벤트는 구조화 json lines(`logs/events.jsonl`) — 사고 감사 추적.

## 제품 분리 (C-S3)
- `VIGENT_THEMES`(기본 safety). safety 배포는 office/sports 라우트 404.
- 다중 제품: `VIGENT_THEMES=safety,office,sports`.

## 개발 서버 표준 기동 (F-8 · 좀비 서버 방지)
> 매번 임시 위치에서 서버를 띄우다 **cwd가 꼬여** rfdetr 커스텀 가중치를 못 찾고 COCO로 폴백하던 사고(F-8) 재발 방지. 아래 표준 절차만 쓴다.
```bash
# 반드시 vigent-core 디렉토리에서 기동(rfdetr_weights 는 프로젝트루트 기준 경로 → 절대화되지만, cwd 일관 유지 권장)
cd <프로젝트루트>/vigent-core
/opt/anaconda3/bin/python3 -m uvicorn main:app --port 8010
```
- **기동 직후 로그에서 검출 슬롯 4개(person 제외 3개: ppe/fire_smoke/forklift) `→ LOADED` + SHA를 확인**한다. 
  `MISSING(기동 거부)` / `Application startup failed` 가 뜨면 `vigent-core/weights/*.pth` 부재 → `python fetch_weights.py download` 또는 배치.
  (F-8 가드: 커스텀 가중치 부재 시 **기동을 거부**한다. 임시로 COCO 폴백을 허용하려면 `VIGENT_ALLOW_FALLBACK=1` — 단 검출 저하.)
- **워크트리에서 기동할 때**는 먼저 `bash scripts/setup_worktree.sh` 로 `weights/`·`data/` 심링크를 연결한다(워크트리엔 .gitignore 자산이 빠져 있음 — CLAUDE.md §8).
- 실행 확인: `curl -s localhost:8010/health` → `rfdetr_slots[].state=LOADED` + `sha16` 이 `weights_manifest.json` 과 일치해야 배포 실체가 선언과 같다(F-8).
