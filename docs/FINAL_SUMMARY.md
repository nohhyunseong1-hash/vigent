# VIGENT 저장소 감사·정리 최종 요약 (2026-09-06)

> 브랜치 `audit/cleanup-20260906` · 시작 태그 `audit-before-cleanup`(= `e1ba0ab`) · 이 문서 작성 시점 HEAD `ee5ef18` + 이 문서 커밋.
> **main 병합·태그(v-audit-2026-09)는 대표 결정 사항**이며 아직 하지 않았다. 브랜치는 원격에 푸시되지 않았다(로컬만).
> 상세 근거: [AUDIT_REPORT.md](../AUDIT_REPORT.md)(1단계) · [CLEANUP_PLAN.md](../CLEANUP_PLAN.md)(2단계) · [CODE_REVIEW.md](../CODE_REVIEW.md)(4단계 모듈 1~8) · [audit/](../audit/)(실측 기록).

## 1. 한 문단 요약

VIGENT 는 공장 CCTV 영상에서 사람·보호구·화재·위험구역 침입 같은 위험을 자동으로 찾아 담당자 휴대폰(텔레그램)으로 알리는 Windows 프로그램이다. 이번 작업은 "지금 저장소에 있는 코드가 실제로 현장에서 믿고 돌릴 수 있는 상태인가"를 한 번에 점검한 것이다. 저장소에 섞여 있던 얼굴이 찍힌 사진·영상(98파일 + 평가 프레임 530장)을 저장소 밖으로 빼고, 지워진 옛 기능(사무·운동 테마) 잔재를 격리하고, 감지·경보·저장·기동에 관한 코드 8개 영역을 줄 단위로 읽어 문제 100여 건을 찾아 그중 치명·높음 16건을 전부 고쳤다. 대표적으로 "서비스가 3주 동안 4,067번 죽고 다시 켜지는데 아무도 몰랐던 문제", "카메라 IP가 죽으면 123초씩 멈추던 문제(→ 5초)", "설정 파일에 같은 이름의 블록이 두 번 있어 8개 설정이 조용히 무시되던 문제", "같은 침입을 브라우저와 서버가 두 번 통보하던 문제"를 고쳤다. 테스트는 481개에서 638개로 늘었고, 아무것도 없는 새 PC에 설치하는 것을 실제로 해 봐서(새 클론) 638개가 전부 통과함을 확인했다. 남은 큰 결정 4가지(증거 보존 기간 법률 자문, 지게차 감지 대체 경로, 저장소 이력 재작성, 에이전트 통합 설계)는 §6 에 정리했다.

## 2. 변경 전/후 수치

| 항목 | 전(`e1ba0ab`, 2026-09-06 감사 시작) | 후(HEAD) | 근거 |
|---|---|---|---|
| 커밋 | — | **60**(3단계 `[감사]` 11 · 4단계 `[CODE_REVIEW]` 48 · 5단계 1) | `git log e1ba0ab..HEAD` |
| 추적 파일 수 | 1,054 | 1,064 | `git ls-tree -r` |
| 추적 파일 용량(blob 합) | 58.9MB | **22.9MB** | 영상·이미지 98파일 + 평가 jpg 530장 → 저장소 밖 |
| 변경 규모 | — | 424 files, +13,071 / −3,575 | `git diff --shortstat` |
| 테스트 | 481(4단계 시작 실측; 감사 전 README 문구는 34) | **638**(새 클론에서도 638 OK, skip 1) | [audit/verify_clean_clone](../audit/verify_clean_clone_2026-09-06.md) |
| 테스트 파일 | 61 | 92 | `tests/test_*.py` |
| 의존성 파일 | requirements.txt · -optional · -eval | requirements.txt(서빙) · **-agents**(LLM·RAG) · **-train**(학습·측정) · -optional | 3단계 C6 |
| 치명·높음 | 등록 항목 R1·R2·R14 치명 3 + 모듈 발견 높음 13 | **16/16 수정 커밋됨** | CODE_REVIEW §0·각 모듈 표 |
| Python 정본 | 문서 3.13/3.11 혼재, CI 3.13 | **3.11.9 단일**(CI·런처·문서·서비스) | M7-5·6 |
| 가중치 조달 | 스크립트 있으나 rtmlib 2종 누락 | 매니페스트 13종(필수 6) · 새 클론 938MB/117초 | M7-2b |
| 저장소 pack | 47MB(이력 포함) | 47MB — **민감 미디어 이력(`2a98fa9`·`b9e8289`)은 그대로** | §6-3 |

## 3. 폴더 구조와 역할

```
vigent_original/
  CLAUDE.md · README.md · CODE_REVIEW.md · AUDIT_REPORT.md · CLEANUP_PLAN.md   루트 고정 문서
  vigent-core/        서버 본체(FastAPI). main.py=앱 골격·기동 순서, worker.py=카메라 1대당 감시 루프,
                      agents/guard.py=검출(RF-DETR)·추적, alert_*.py=경보 게이트·큐·통보, retention*.py=보존 삭제,
                      routers/=HTTP API(카메라·구역·인식 로그·시스템), static/·templates/=화면, weights/=모델(gitignore)
  themes/safety/      화면 HTML(index=시연, index_hub=관제, console)과 vision.yaml(모델 슬롯·규칙 설정)
  config/             현장 설정 시드: tuning.yaml(임계값 정본) · go2rtc.yaml · *.example.yaml(복사해서 쓰는 견본)
  deploy/             windows/(서비스 설치·상태·재설치 검증 스크립트) · academy/(학원 현장 프로파일) · SITE_CHECKLIST.md
  scripts/            운영 도구: fetch_weights(가중치 조달) · check_openapi_diff·check_profile_drift(게이트)
  tests/              단위 테스트 92파일 638건(카메라·GPU 없이 실행)
  benchmarks/ eval/   측정 스크립트·리포트(숫자 근거). 학습은 training/, 유틸은 tools/
  data/               런타임 산출물(gitignore) + 추적 대상인 평가 정답 라벨(data/field_eval/labels)
  docs/ md/           운영·온보딩·정책 문서(DEPLOYMENT·ONBOARDING·disk_retention_policy 등)
  audit/              감사 실측 기록(스모크·크래시 루프 로그 zip·클론 검증·서비스 백업)
  _archive/           삭제 기능 잔재 격리(macOS 런처, office/sports)
D:\vigent_private_data\   저장소 밖 미디어(VIGENT_DATA_DIR): runs/·benchmarks/(사고 영상·현장 이미지 98) · field_eval/(평가 jpg 530)
```

## 4. 발견·수정한 문제 상위 10

| # | 쉬운 설명 | 기술 근거(실측) | 커밋 |
|---|---|---|---|
| 1 | 서버가 3주 동안 계속 죽었다 켜지길 반복했는데 아무 알림이 없었다 | NSSM 재시작 4,067회(로그 회전본 8,139개), 기동 실패 시 통보 경로 0. 이제 상태파일·Windows 이벤트 로그(ID 1000)·1시간 1회 통보 + 재시작 60s/180s + 상태 스크립트가 크래시 루프 감지 | `99488d9` · `5cf638b` |
| 2 | 카메라 IP가 죽으면 서버가 2분씩 멈췄다 | FFmpeg 연결 대기 123.45s → OpenCV 타임아웃 속성으로 **5.05s** | `22311e7` |
| 3 | 설정 파일의 경보 설정 8개가 조용히 무시되고 있었다 | `tuning.yaml` 에 `alerts:` 블록이 두 번 → YAML 이 뒤 블록만 채택(17일 잠복). 병합 + 중복 키를 거부하는 로더 + "파일 키 ⊆ 코드가 읽는 키" 게이트 | `5ba2c31` |
| 4 | 테스트를 돌리면 운영 데이터베이스에 시험 경보가 섞였다(설정된 PC에선 실제 텔레그램으로 나갈 수 있었음) | 운영 `data/` 28,815파일 해시 비교로 오염 확인 → 격리 헬퍼 도입 후 변경 0 | `71cef0d` |
| 5 | 같은 침입을 브라우저 시연 화면과 서버가 각각 통보했다 | 게이트 키가 달라 이중 통보. 이제 서버가 "워커가 감시 중인 카메라"면 기록만 하고 통보는 워커에 위임 | `51b188d` |
| 6 | 텔레그램 토큰이 잘못돼도 영원히 재시도만 하고 아무도 몰랐다 | 401/403/404 → 설정 오류로 분류·데드레터, /health 에 노출, 데드레터 요약 통보 1시간 1회 | `bb7ddef` |
| 7 | 시연 화면의 여러 버튼이 존재하지 않는 서버 기능을 불렀다(항상 404, 일부는 조용히 실패) | 9경로 실측(라우트 0). 미구현 표시로 비활성 + 라우트가 생기면 알려 주는 테스트 | `7ec9509` |
| 8 | 보존(자동 삭제) 정책이 자기 보호 목록까지 지울 수 있었고, 보호 표시가 Windows 경로 표기 차이로 무시됐다 | `pinned.json` 이 삭제 후보에 오름, `\`·`/` 혼용 비교 실패 → 목록 이동 + 절대경로 비교 + 발송 경보 자동 보존 | `69045db` · `e7f7542` |
| 9 | 사람이 화면 밖으로 나간 뒤 옆에 나타난 다른 사람을 "급격한 이동"으로 오인했다 | 추적 ID 우선 매칭 + 카메라 팬/틸트 억제(육안 검증 5 영상, 급이동 오탐 다수 → 0) | `da79a43` |
| 10 | 시연 화면이 얼굴로 성별·나이·감정을 추정하고, 외부 클라우드로 프레임을 보낼 수 있는 코드를 갖고 있었다 | 개인정보 추정 3함수 + 클라우드 직접 호출 3함수 삭제(호출부 0이었음), 정적 게이트 | `f422dcd` |

(전체 목록·근거는 CODE_REVIEW.md 모듈별 표. 이 밖에 오프라인 현장의 포즈 모델 156MB 미조달(M7-2b), 서비스/개발 환경 4개 불일치(M7-2), 기동 실패 격리(M7-3), Python 버전 통일(M7-5·6) 등.)

## 5. 배포 사양·용량

| 항목 | 값 | 근거 |
|---|---|---|
| OS / Python | Windows 10/11 Pro(현장) · **Python 3.11.9**(`.python-version`, CI·런처·서비스 동일) | M7-5·6, 새 클론 실증 |
| GPU | NVIDIA 권장. 개발 PC RTX 5070 Ti(cu130) · 현장 노트북 GTX 1650 Ti 4GB(cu126)로 실증. GPU 없이도 동작(CPU, 느림) | DEPLOYMENT §0 |
| 카메라 대수 | **PC 1대당 약 5대 포화**(추론이 `DETECT_LOCK` 으로 직렬화, 풀세트 ~85ms, 2fps 기준) — 한계 7대 실측(8대에서 p95 116→309ms). **시연 페이지(`/safety`) 동시 사용 시 여유 −1대** | CODE_REVIEW §5 용량 스펙 · M8-11 |
| 병목 | CPU(카메라당 1.55 환산코어). GPU 는 VRAM 4GB 면 충분 | benchmarks/capacity_report |
| 오프라인 조달 목록 | ① `python scripts\fetch_weights.py`(필수 6: RF-DETR 4 + rtmlib 2 · 전체 13종 938MB/117초) ② `bin\go2rtc.exe`(확대뷰 WebRTC, 없으면 스냅샷 폴백) ③ `vigent-core\static\vendor`(시연 화면 폐쇄망 번들, 선택) ④ NSSM(서비스 등록) ⑤ Python 3.11 설치본 ⑥ pip 캐시/휠(인터넷 없는 곳이면 미리) — **opencv 는 requirements 설치 후 GUI 빌드 제거 절차 필수**(§9) | audit/verify_clean_clone §2 |
| 기동 시간 | 새 클론·카메라 0대 기준 /health 200 까지 17.2초(예열 포함) | audit/verify_clean_clone |
| 경보 채널 | 텔레그램·웹훅(config/notify.yaml, .env). 미설정이면 /health warnings 로만 표시(degraded 아님) | M4-1 |

## 6. 결정 필요 항목(대표)

1. **증거 보존 기간(R17)** — 현재 `retention.groups.evidence/recognition: 30일` 은 잠정값(국내 CCTV 관행 근거). 산업재해 증거의 법적 보존 요구는 **법률 자문**이 필요하다. 평가 자료(field_eval)는 365일로 결정됨.
2. **지게차 협착(R16)** — 협착 규칙이 지게차를 장비로 못 본다(F-7 과소학습으로 forklift 슬롯 기본 제외 → COCO 차량류만). "forklift 슬롯 재학습" 또는 "대체 감지 경로" 중 택일(1순위군, §7).
3. **저장소 이력 재작성** — 얼굴 식별 이미지 9장·고객 설비 사진 24장·사고 영상 9개는 작업트리에서 나갔지만 **git 이력(`2a98fa9`·`b9e8289`)과 원격에 남아 있다**. 공개 전환·외부 이관 전 반드시 재작성(docs/public_release_checklist.md). 재작성은 협업자 전원 재클론이 필요해 별도 작업.
4. **에이전트 통합 설계** — LLM 에이전트(Analyst·Scribe·Copilot·SafetyManager)는 코어와 분리돼 있고(requirements-agents, 없이도 기동 OK — C9), 앞으로도 **별도 프로세스·별도 requirements·HTTP API 로만 연결**하는 설계를 권고한다. 서버 기동·검출 루프에 LLM 의존이 들어오지 않게.

## 7. 다음 단계 우선순위

- **1순위**: ① Windows 로컬 VLM 대체 구현(현재 로컬 VLM 은 Apple mlx 전용 → RTX 5070 Ti/CUDA 13 기반, 클라우드 전송 없이 오탐 확정) ② forklift 협착 대체 경로(§6-2).
- **2순위**: 카메라 확장(배치 추론 또는 카메라별 프로세스 분리로 5대 한계 돌파) · 카메라별 설정 override 일반화(R15 는 무동작 1키만) · M8-4(a) 시연 화면에서 삭제 테마 잔재(fitness/office·rPPG·상업화 점검표 등 함수 22개) 정리.
- **3순위**: 학습 도구(training/·benchmarks 일부)를 별도 저장소로 · PTZ 카메라용 전역 이동 보정(M3-1 (a)) · opencv 정리 자동화 · 런처 콘솔 인코딩.
- 5단계 미완: 서비스 재설치 검증(§8) · 실카메라 항목.

## 8. 현장 검증 체크리스트(5단계에서 못 한 것 + 등록 항목)

현장 필수 조건(고정 IP·저장 암호화·릴레이·카메라 대수·오프라인 가중치)은 [deploy/SITE_CHECKLIST.md](../deploy/SITE_CHECKLIST.md) N-1~N-5 를 따른다. 아래는 그 밖의 **코드 리뷰에서 등록된 검증 항목**이다.

- [ ] **서비스 재설치 검증** — 관리자 PowerShell 에서 `deploy\windows\verify_service_reinstall.ps1` 실행 → 보고서 `audit\service_reinstall_*.md` 통과(이 세션은 비관리자라 실행 못 함). 확인 포인트: 이벤트 로그 Application/VIGENT ID 1000 · 재시작 간격 ≥60s · `service_status.ps1` 종료코드 0 · Stopped/Disabled 원복.
- [ ] **실카메라 10초 수신** — 프레임 None 비율, 저지연 옵션(`nobuffer/low_delay/max_delay`) 전후 지연 비교(M5-1 (2)).
- [ ] **READ 5초 재연결** — 카메라 전원 차단 → 5초 타임아웃 → 재연결 동작(M5-2).
- [ ] **오프라인 첫 사람 검출** — 카메라 물린 뒤 사람 1명 통과 시 로그에 `Downloading:` 이 없어야 함(rtmlib 캐시, N-5).
- [ ] **브라우저+워커 이중 통보 실카메라 확인** — `/safety?cam=tapo` 열어 둔 채 침입 1회 → 텔레그램 1건·증거 브라우저 1장(M8-1).
- [ ] **릴레이 자동 경로** — `relay.enabled=true` 현장에서 guard_bypass 발화 → `safety_relay_signal` 로 릴레이 ON(M8-9).
- [ ] **eventcreate 서비스 계정** — LocalSystem 에서 이벤트 소스 자동 등록 여부(개발 PC 비관리자는 Access denied 실측).
- [ ] **opencv headless 4.13 에서 RTSP 타임아웃 실측** — 모듈 5 실측(5.05s)은 cv2 5.0.0 기준.
- [ ] **학원 프로파일 적용 후 드리프트 게이트·기동** — `deploy/academy` 로 덮은 노트북에서 `check_profile_drift.py` 와 /health.

## 9. Windows 개발 환경 체크리스트(새 개발자용)

1. Git for Windows 설치 → `git clone https://github.com/nohhyunseong1-hash/vigent.git D:\vigent_original`(비공개: GCM 로그인 창). 브랜치 `audit/cleanup-20260906`.
2. Python **3.11.x**(python.org) 설치 → `py -3.11 --version` 확인. `py` 기본이 3.14 인 PC 가 있으니 항상 `py -3.11`.
3. `py -3.11 -m venv .venv` → `.\.venv\Scripts\Activate.ps1`(실행정책 오류 시 `Set-ExecutionPolicy -Scope Process Bypass`).
4. `python -m pip install -r requirements.txt`(약 2.5분, 1.4GB). GPU 면 [DEPLOYMENT §3](../md/DEPLOYMENT.md) 의 CUDA 휠로 torch 교체.
5. **★opencv 정리(필수)**: `python -m pip uninstall -y opencv-python opencv-contrib-python` → `python -m pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.13.0.92` → `python -c "import cv2; print(cv2.__version__)"` 가 `4.13.0` 이어야 한다(새 클론 실측: 이 절차 없이는 5.0.0).
6. 가중치: `python scripts\fetch_weights.py --all`(938MB, 약 2분). 비공개 릴리스라 GitHub 로그인(GCM) 또는 `GITHUB_TOKEN` 필요.
7. 기동: `.\run.ps1` → `http://127.0.0.1:8010/health` 가 17초쯤 뒤 200(status healthy, warnings channels_not_configured 는 정상). 관제 화면 `/hub`, 시연 `/safety`.
8. 게이트(변경 후 반드시): `ruff check vigent-core tests` → 0 · `python -m mypy` → 0 · `py -3.11 -m unittest discover -s tests` → 638 OK · `python scripts\check_openapi_diff.py` → 무변경 · `python scripts\check_profile_drift.py` → 드리프트 없음.
9. 선택: `bin\go2rtc.exe`(확대뷰 WebRTC) · node(JS 구문 검사 테스트) · `.env`(텔레그램 토큰, `.env.example` 참조; HOST/PORT 는 셸 환경변수로만).
10. 규칙: 카메라·현장 미디어는 `D:\vigent_private_data\`(`VIGENT_DATA_DIR`)에만, 커밋 전 `git branch --show-current` 확인, 비밀값은 코드·문서·채팅에 쓰지 않는다([CLAUDE.md](../CLAUDE.md)).

## 10. 되돌리기

- **감사 전 상태로**: 태그 `audit-before-cleanup`(= `e1ba0ab`). `git checkout audit-before-cleanup` 또는 새 브랜치 `git switch -c rollback audit-before-cleanup`. main 은 건드리지 않았으므로 main 자체가 감사 전 상태다.
- **특정 커밋만 되돌리기**: 한 모듈 = 한 커밋 원칙이라 `git revert <해시>` 로 항목 단위 복원이 된다(해시는 CODE_REVIEW.md 각 모듈 "진행 현황" 표).
- **사설 미디어**: `D:\vigent_private_data\`(runs/·benchmarks/results/·field_eval/) — 저장소 상대경로를 그대로 유지하므로 되돌릴 때는 같은 위치로 복사만 하면 된다(`VIGENT_DATA_DIR` 로 위치 변경 가능). 정답 라벨(txt/json/md)은 저장소 `data/field_eval` 이 정본.
- **서비스 설정**: 감사 전 NSSM 설정 백업 `audit/vigent_service_backup_2026-09-06.{reg,txt,_nssm_dump.txt}`. 현재 서비스는 Stopped/Disabled.
- **설정 파일**: `config/tuning.yaml` 은 값을 바꾸지 않고 구조만 정리(중복 블록 병합·상수 기재)했다. 옛 값이 필요하면 `git show audit-before-cleanup:config/tuning.yaml`.
