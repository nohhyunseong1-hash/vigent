# 현장 노트북 반영 절차 — F-34 경보 유실 수정 + 알림 채널 복구

> # ⚠️ 이 문서는 **USB 설치기 완성 전 임시 절차**다 (2026-09-23 표기)
>
> 최종 방향은 **USB 하나로 현장 기기를 설치**하는 것이다
> (`docs/deploy/usb_installer_design.md`). 설치기 1차가 나오면
> **노트북·파일럿 데스크톱 2대를 그것으로 재설치**한다 — 그러면 기기에서 git 을 쓰지 않게 되어
> **코드 분기가 구조적으로 사라진다**(지금 노트북↔개발기가 갈라진 것이 그 문제다).
>
> **그때까지는 이 절차가 유효하다.** 설치기를 기다리는 동안에도 F-34(경보 유실)는
> 현장에서 계속 일어나고 있으므로, 급하면 이 절차로 먼저 반영한다. **삭제하지 않는다.**

> **실행일: ____________** (대표 결정 — 이 문서는 절차이며 아직 실행하지 않았다)
>
> ⚠️ **선행 조건: 원격(GitHub) 복구.** 현재 `git ls-remote origin` 이 404 다
> (로그인 계정 `kimsunwu4981-ship-it` 이 저장소 소유자 `nohhyunseong1-hash` 와 다름).
> 이 절차는 **원격이 살아난 뒤** 쓴다. 원격 없이 가려면 USB 번들 경로가 따로 필요하다.

## 0. 왜 지금 해야 하나

**현장 노트북이 지금도 경보를 버리고 있다.**

| 항목 | 값 |
|---|---|
| 결함 | F-34 — 포즈 3-튜플/4-튜플 불일치로 **그 프레임의 모든 경보가 버려진다** |
| 수정 커밋 | **`c33e3ab`** (2026-09-10 04:09, 개발기) |
| 노트북 반영 | **안 됨** — 커밋이 푸시되지 않았다 |
| 노트북 오류 실측 | `vigent.log` 09-17 **736줄** (누계 8,167줄) |
| 영향 | 오류 1줄 = 그 프레임의 침입·PPE·화재·근접·무동작 경보 **전부** 유실 |

여기에 **F-35**(텔레그램 401)까지 겹쳐 있다 — 노트북의 `config/notify.yaml` 도 옛 토큰일
가능성이 높다. 검출이 살아나도 **통보가 죽어 있으면 의미가 없다.**

## 1. 양쪽이 무엇을 갖고 있나

**공통 조상은 `9b5ea29`** 다(실측: `git merge-base 9b5ea29 HEAD` = 9b5ea29).
양쪽이 그 지점에서 갈라졌다 — 깨끗한 분기다.

### 노트북에만 있는 커밋 3개 (2026-09-17 17:48 커밋)

| 커밋 | 제목 | 건드렸을 파일(추정) |
|---|---|---|
| `b500447` | 키트: 서버 PID 트리 합산, perf% 로깅, 시작 게이트 | `scripts/pilot_load_test.py` |
| `97ac1a3` | 인수시험 절차서, 오프라인 번들 v1(4.07GB), D-1 4대 실측 근거 | `docs/acceptance_test.md`·`scripts/build_bundle.ps1`·`BUNDLE.txt` |
| `8bcd8c8` | 학원 프로파일 + pose_fps 0.2 (3차 소크 미달 판정 근거) | `config/tuning.yaml`·`deploy/academy/*` |

★**파일 목록은 커밋 제목에서 추정한 것이다.** 실제 내용은 `git show --stat` 으로
**개발기에서 직접 확인한 뒤** 병합한다(§3-2). 노트북에서는 확인만 하고 손대지 않는다.

### 개발기에만 있는 커밋 (30개 이상)

F-34 수정(`c33e3ab`) · F-33 · 포터블 패키지 · 소크 판독 · F-35 조용한 실패 제거 등.

### ⚠️ 충돌이 예상되는 파일 3개 (실측)

`git diff --name-only 9b5ea29..HEAD` 와 노트북 커밋 제목을 대조한 결과:

| 파일 | 개발기 변경 | 노트북 변경 | 충돌 |
|---|---|---|---|
| **`scripts/pilot_load_test.py`** | `run_config`·`health_config`·`browsers` 추가(bd7986c) | PID 트리 합산·perf% 로깅·시작 게이트(b500447) | **거의 확실** |
| **`config/tuning.yaml`** | `notify.heartbeat_at` 추가 | `pose_fps 0.2` | 가능(다른 줄이면 자동 병합) |
| **`deploy/academy/tuning.academy.yaml`** | `notify.heartbeat_at: '08:30'` | 학원 프로파일 | 가능 |

★`pilot_load_test.py` 는 **양쪽 변경을 모두 살려야 한다** — 한쪽을 버리면 측정 도구가
반쪽이 된다(개발기: 구성 지문 / 노트북: 서버 PID 정확도).

## 2. 방식 — 노트북은 병합하지 않는다

```
노트북  ──push──▶  origin/laptop/20260917   (커밋 3개만)
                         │
개발기  ──fetch──────────┘
        내용 확인 → 병합 → origin/audit/cleanup-20260906 에 push
                         │
노트북  ◀──fetch/reset───┘   병합된 결과를 받기만 한다
```

★**노트북에서 merge·rebase 하지 않는다.** 이유:
- 노트북에는 충돌을 해결할 근거(개발기 30개 커밋의 맥락)가 없다.
- 현장 기기에서 병합하다 실패하면 **감시가 멈춘 채로 복구해야 한다.**
- 2026-07-07 사고 재발 방지: 여러 워킹트리가 HEAD 를 공유하면 커밋이 엉뚱한 브랜치에 얹힌다
  (CLAUDE.md 규칙 8).

⚠️ **브랜치 이름 확인 필요**: 지시에는 "노트북은 병합된 main 을 받는다" 라고 돼 있으나,
현재 양쪽 작업 브랜치는 **`audit/cleanup-20260906`** 이고 `main` 은 `ee4557d` 에 멈춰 있다.
아래 절차는 **`audit/cleanup-20260906`** 기준으로 썼다. `main` 으로 합칠 계획이면 알려 달라.

---

## 3. 절차

### 3-1. 노트북 — 백업 후 푸시 (노트북에서 실행)

★**복사해서 한 번에 붙여 넣는다.** 각 줄이 끝날 때까지 기다린다.

```powershell
cd C:\Users\1\Desktop\VIGENT
git branch --show-current
git log --oneline -4
git bundle create E:\laptop_backup_20260917.bundle --all
git bundle verify E:\laptop_backup_20260917.bundle
git branch laptop/20260917
git push -u origin laptop/20260917
git log --oneline origin/laptop/20260917 -3
```

확인할 것:

| 줄 | 기대 |
|---|---|
| `git branch --show-current` | `audit/cleanup-20260906` |
| `git log --oneline -4` | `8bcd8c8` · `97ac1a3` · `b500447` · `9b5ea29` |
| `git bundle verify` | `The bundle records a complete history.` |
| `git push` | `new branch  laptop/20260917 -> laptop/20260917` |

★**번들 백업이 먼저다.** 푸시가 실패해도 커밋 3개가 USB 에 남는다.
★`E:` 는 실제 USB 드라이브 문자로 바꾼다. USB 가 없으면 `C:\Users\1\Desktop\` 도 된다
(다만 노트북 고장 시 함께 사라진다).

**여기까지 하고 멈춘다. 개발기에서 확인한 뒤 다음 지시를 받는다.**

### 3-2. 개발기 — 내용 확인 (병합 전)

```bash
cd D:\vigent_original
git fetch origin
git log --oneline 9b5ea29..origin/laptop/20260917
git show --stat b500447
git show --stat 97ac1a3
git show --stat 8bcd8c8
git diff --name-only 9b5ea29..origin/laptop/20260917
```

**충돌 예측:**

```bash
git merge-tree $(git merge-base HEAD origin/laptop/20260917) HEAD origin/laptop/20260917 | grep -c "<<<<<<<"
```

### 3-3. 개발기 — 병합 (충돌은 양쪽 살려서)

```bash
git checkout -b merge/laptop-20260917      # ★작업 브랜치에서 시험 병합
git merge origin/laptop/20260917
```

충돌이 나면 파일별로:

| 파일 | 해결 방침 |
|---|---|
| `scripts/pilot_load_test.py` | **양쪽 모두 살린다.** 개발기의 `run_config`/`browsers` + 노트북의 PID 트리·perf%·시작 게이트 |
| `config/tuning.yaml` | 양쪽 키 모두 유지(`pose_fps` 는 노트북 값, `notify` 는 개발기 값) |
| `deploy/academy/*.yaml` | 양쪽 유지 후 **프로파일 드리프트 게이트로 검증** |

병합 후 **반드시** 게이트를 돌린다:

```bash
ruff check vigent-core tests
.venv/Scripts/python.exe -m unittest discover -s tests
python scripts/check_openapi_diff.py
python scripts/check_profile_drift.py
```

전부 통과하면 본 브랜치에 반영:

```bash
git checkout audit/cleanup-20260906
git merge --no-ff merge/laptop-20260917
git branch --show-current          # ★커밋·푸시 전 반드시 확인(규칙 8)
git push origin audit/cleanup-20260906
```

### 3-4. 노트북 — 받기 (노트북에서 실행)

⚠️ **서버를 먼저 멈춘다.** 코드가 바뀌는 중에 돌고 있으면 예측 불가다.

```powershell
cd C:\Users\1\Desktop\VIGENT
Stop-Service VIGENT
Get-Service VIGENT
git stash list
git status --short
git fetch origin
git reset --hard origin/audit/cleanup-20260906
git log --oneline -3
```

⚠️ **`git reset --hard` 는 노트북의 미커밋 변경을 버린다.** 실행 전에
`git status --short` 로 **`M` 표시가 있는 추적 파일이 없는지** 확인한다.
있으면 멈추고 보고한다 — 09-18 시점에 `themes/safety/vision.yaml` 이 34줄 미커밋이었다.

### 3-5. 노트북 — 알림 토큰 갱신 (F-35)

★**이것을 빼먹으면 검출은 살아나도 경보가 안 간다.**

```powershell
notepad C:\Users\1\Desktop\VIGENT\config\notify.yaml
```

- `telegram_token` 을 **새로 발급한 값**으로 바꾼다(개발기와 같은 값).
- 가능하면 `smtp_*`·`email_to` 도 채운다(`docs/ops/email_notify_setup.md`).
  **채널이 하나뿐이면 그것이 죽는 순간 경보가 아무에게도 안 간다.**
- ★비밀번호·토큰은 **채팅·문서에 붙여넣지 않는다**(규칙 5).

### 3-6. 노트북 — 재기동

```powershell
Start-Service VIGENT
Start-Sleep 90
Get-Service VIGENT
curl.exe -s http://127.0.0.1:8010/health
```

---

## 4. 검증 — F-34 가 실제로 반영됐는가 (규칙 11)

★**"커밋이 들어갔다" 는 증거가 아니다.** 로그로 확인한다.

### 4-1. 코드가 바뀌었는지

```powershell
cd C:\Users\1\Desktop\VIGENT
git log --oneline -1 c33e3ab
Select-String -Path vigent-core\worker.py -Pattern "len\(ev\) == 4"
```

`c33e3ab` 가 보이고 `worker.py` 에 `len(ev) == 4` 가 있으면 반영된 것이다.

### 4-2. ★오류가 멈췄는지 — 이것이 진짜 증거다

재기동 **이후 시각**으로 한정해 센다.

```powershell
$since = (Get-Date).AddMinutes(-10)
Select-String -Path C:\Users\1\Desktop\VIGENT\logs\vigent.log `
  -Pattern "not enough values to unpack" | Measure-Object | Select-Object Count
```

| 결과 | 판정 |
|---|---|
| 재기동 후 구간에서 **0줄** | ✅ 반영됨 |
| 1줄 이상 | ❌ **실패** — 되돌리고 보고한다 |

⚠️ 로그 파일 전체를 세면 **과거분이 섞인다**(누계 8,167줄). 반드시 재기동 이후 구간만 본다.

★**카메라가 돌고 사람이 찍혀야** 이 오류가 재현된다. 카메라 0대로 10분 두고 "0줄이니 고쳐졌다"
고 보면 안 된다 — 그건 **0건 처리**다(규칙 11). 최소 1대를 돌리고 사람이 화면에 들어온 뒤 센다.

### 4-3. 알림 채널

```powershell
curl.exe -s http://127.0.0.1:8010/health
```

`notify` 블록에서:

| 필드 | 기대 |
|---|---|
| `selftest_state` | `"ok"` |
| `config_error` | `null` |
| `single_channel` | `false` (이메일도 넣었다면) |
| `last_success` | 최근 시각 |

실제 전송 시험:

```powershell
curl.exe -s -X POST http://127.0.0.1:8010/alerts/test
```

**폰으로 메시지가 오는지 눈으로 확인한다.**

---

## 5. 되돌리기

문제가 생기면 즉시 원복한다. **번들이 있으므로 노트북 커밋 3개는 안 잃는다.**

```powershell
cd C:\Users\1\Desktop\VIGENT
Stop-Service VIGENT
git reset --hard 8bcd8c8          # 09-17 상태로
Start-Service VIGENT
```

★원복하면 **F-34 가 다시 살아난다**(경보 유실). 원복은 임시 조치이고, 원인을 찾아
다시 반영해야 한다.

## 6. 체크리스트

- [ ] 3-1 노트북 번들 백업 + `laptop/20260917` 푸시
- [ ] 3-2 개발기에서 커밋 3개 내용 확인(`git show --stat`)
- [ ] 3-3 병합 + **게이트 4종 통과**
- [ ] 3-4 노트북 서비스 정지 → fetch → reset
- [ ] 3-5 **`notify.yaml` 토큰 갱신** ← 빼먹기 쉽다
- [ ] 3-6 재기동 + `/health` 200
- [ ] 4-2 **재기동 이후 구간에서 F-34 오류 0줄**(카메라 돌린 상태로)
- [ ] 4-3 `/alerts/test` 실제 수신 확인
