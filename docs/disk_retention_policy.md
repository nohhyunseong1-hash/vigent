# 디스크 보존 정책 — [Z-1] 전수 조사 + [Z-2] 설계안·구현 (2026-08-10)

> **★1~3단계 구현 완료(2026-08-10).** `vigent-core/retention.py`·`scripts/retention_sweep.py`·
> `/health` disk_retention 필드·D그룹 회전(legal_whitelist.py·routers/cameras.py) 전부
> 구현·테스트(`tests/test_retention.py`, 11건)·게이트 통과. 4단계(A/B/C 보존일수)도
> `config/tuning.yaml`에 잠정값으로 채움(법률 전문가 확인 전 — 아래 §Z-2 표 주석 참고).
> 실측 소요시간·용량 계산은 `docs/ops_disk_sizing.md` 참고. [B11](P3_BACKLOG.md#b11) 후속.

## [Z-1] 디스크 증가 경로 전수 조사

`vigent-core/` 실서버 코드(main.py·routers/·agents/·data_engine.py·worker.py 등) 전수 조사
결과. SQLite 등 임베디드 DB는 미사용(전수 grep 0건), 얼굴인식 모듈(`vigentFacialRecognition/`)
은 vigent-core에 미연동, RTSP 녹화/클립 저장 기능 없음(go2rtc는 SDP/WS 중계만).

| 경로 패턴 | 트리거 | 기존 정리 로직 | 축적 속도 추정 | 근거 |
|---|---|---|---|---|
| `data/evidence/<YYYYMMDD>/ev_*.jpg` | 위험 이벤트마다(이미지 첨부 시) | **없음** | 이벤트당 JPEG 수십KB. 실측 122KB(현재) | `data_engine.py:40-54` |
| `data/recognition/events_<YYYYMMDD>.jsonl` | 위험 이벤트마다 | **없음**(조회 함수만 존재) | 이벤트당 1줄, 일별 파일 무기한 누적. 실측 60KB | `data_engine.py:57-73` |
| `data/audit/audit_<YYYYMMDD>.jsonl` | 위험성평가 승인/조치확인마다 | **없음** | 승인 1건당 1줄, 무기한 | `audit_store.py:21-40` |
| `data/tbm/tbm_<YYYYMMDD_HHMMSS>.json` | TBM(작업전 안전점검회의) 저장마다 | **없음** | 회의록 1건당 파일 1개, 무기한 | `tbm_store.py:122-158` |
| `data/risk_assessments/ra_<stamp>.{html,json}` | 위험성평가서 생성마다 | **없음**(목록 limit만) | 평가서 1건당 파일 2개. **실측 186개/812KB(현재)** | `agents/scribe.py:762-802` |
| `data/office/posture_<YYYYMMDD>.jsonl` | 자세 모니터링 주기(예 60초)마다 | **없음** | 사용자당 60초 1줄, 무기한 | `office_data.py:22-39` |
| `data/sports/sessions_<YYYYMMDD>.jsonl` | 운동 세션 종료마다 | **없음** | 세션당 1줄, 무기한 | `sports_data.py:19-30` |
| `data/go2rtc.log` | 서버 재시작 시 go2rtc 기동마다 | **없음**(append-binary) | 재시작마다 프로세스 종료까지 무기한 append | `routers/cameras.py:249-251` |
| `data/legal/blocked_citations.log` | 법령 인용이 화이트리스트를 벗어나 차단될 때마다 | **없음**(append) | 차단 이벤트당 1줄, 무기한 | `legal_whitelist.py:98-104`(★이번 조사에서 직접 확인 추가) |
| `data/dataset/images/*.jpg`(조건부) | `VIGENT_COLLECT=1`일 때만, 카메라별 주기(기본 30초)마다 | **없음** | **기본 비활성**(opt-in). 활성화 시 다른 항목보다 빠르게 누적 | `worker.py:710-712` |

**이미 정상 처리 중(참고, 정책 대상 아님)**: `logs/vigent.log`(10MB×5)·`logs/events.jsonl`
(10MB×10)은 `RotatingFileHandler`로 이미 크기 상한·회전이 구현돼 있다(`vlog.py:42-45,66-67`).

**총 9개(+조건부 1개) 무기한 누적 경로**를 확인했다 — B11에서 다룬 evidence는 이 중 하나일
뿐이다.

## [Z-2] 보존 정책 설계안

### 설계 원칙

경로를 하나로 묶어 같은 보존기간을 적용하지 않는다 — 성격이 다르면 법적 요구도 다르다.

| 그룹 | 포함 경로 | 성격 | 설계 방향 |
|---|---|---|---|
| **A. 안전 증거** | evidence, recognition 이벤트 로그 | 위험 감지 시점의 시각·행위 증거 — 사고 조사·법적 분쟁 시 증빙으로 쓰일 수 있음 | 짧게 지우면 안 될 수 있다(★산업안전보건법상 기록 보관 의무 여부 미확인 — 법무 확인 필요, 임의로 짧은 기본값을 넣지 않는다) |
| **B. 감사·문서 산출물** | audit, tbm, risk_assessments | 위험성평가·회의록·조치확인 — 컴플라이언스 문서 | 통상 수년 단위 보관이 관행(추정, 미확인) — A와 마찬가지로 임의 기본값 지양 |
| **C. 개인 모니터링 로그** | office posture, sports sessions | 개인 행동·자세 데이터 — 개인정보보호법 대상(CLAUDE.md 원칙: "근로자 영상감시는 동의·고지 대상, 기본은 익명 집계") | **A/B보다 짧은 보존이 원칙에 더 부합**(목적 달성 후 최소 보관) — 그래도 정확한 일수는 사용자 결정 |
| **D. 순수 운영 로그** | go2rtc.log, legal/blocked_citations.log | 디버깅·관측용, 법적/개인정보 요구 없음 | 가장 공격적으로 정리 가능(예: 크기 상한 회전 — `vlog.py`의 기존 RotatingFileHandler 패턴을 그대로 재사용) |

**★핵심 판단(규칙7)**: A·B·C 그룹의 정확한 보존 일수는 이 조사만으로 정할 수 없다 — 법적
요구사항·회사 정책 확인이 먼저다. 그래서 이 설계안은 "일수"를 제안하지 않고, **일수를
나중에 채울 수 있는 인프라**를 먼저 제안한다.

### 메커니즘 제안

1. **가시성 먼저(즉시 착수 가능, 데이터 손실 위험 없음)**: `data/` 하위 각 폴더의 현재
   크기·파일 수를 보여주는 조회 전용 스크립트(또는 `/health`에 필드 추가). 지금 당장 "지우기"
   결정 없이도 문제 규모를 계속 볼 수 있게 한다. B11이 이번에 처음 정량화된 것 자체가 이
   가시성 부재 때문이었다.
2. **정리 스크립트(수동/cron 트리거, 서버 프로세스 내부 아님)**: FastAPI 프로세스 안에 백그
   라운드 스레드로 넣지 않고 **독립 스크립트**(`scripts/retention_sweep.py` 가칭)로 분리한다.
   이유: 서버 재시작·동시성과 무관하게 안전하게 실행·재시도 가능하고, Windows 작업 스케줄러/
   cron 등 운영 환경의 기존 스케줄러에 얹기 쉽다.
3. **그룹별 설정 키**(`config/tuning.yaml`에 신설, 예시 — 값은 미정):
   ```yaml
   retention:
     evidence_days: null      # A — 미정(법무 확인 전 null=보존 정책 비활성)
     recognition_days: null   # A
     audit_days: null         # B
     tbm_days: null           # B
     risk_assessment_days: null  # B
     office_posture_days: null   # C — 사용자 결정
     sports_session_days: null   # C
     ops_log_max_mb: 50       # D — 크기 상한 회전(법적 쟁점 없어 즉시 기본값 제안 가능)
   ```
   `null`(미설정)이면 **정리 안 함**(현재와 동일 동작, 저하 없음 — 규칙6). 값을 넣은 그룹만
   정리 대상이 된다 — 그룹별로 따로 켤 수 있다.
4. **삭제 전 dry-run 기본**: 스크립트 기본 동작은 "삭제 대상 목록·용량만 출력"이고,
   `--execute` 같은 명시적 플래그를 줘야 실제 삭제한다 — 실수로 지우는 사고를 막는다
   (CLAUDE.md 규칙2: 파괴적 작업은 먼저 보여주고 확인).
5. **삭제 자체도 감사 대상**: 무엇을 언제 지웠는지 별도 로그(D그룹과 같은 회전 로그)로
   남긴다 — "증거를 지웠다"는 사실 자체가 나중에 필요할 수 있다.

### 단계적 진행 — ★전부 완료(2026-08-10)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 가시성 스크립트/`/health` 필드 | ✅ `retention.sweep()`(항상 스캔) + `/health`의 `disk_retention` |
| 2 | D그룹(go2rtc.log·legal 로그) 크기상한 회전 | ✅ `retention.rotate_if_large()`, legal_whitelist.py·routers/cameras.py 배선 |
| 3 | 정리 스크립트 인프라(dry-run 포함) | ✅ `scripts/retention_sweep.py`, 기본 `enabled=false`·`dry_run=true` |
| 4 | A/B/C 그룹 실제 보존 일수 확정 | ✅ **잠정값**으로 채움(사용자 지시, 2026-08-10) — 아래 참고 |

**4단계 실제 구현은 위 §Z-2 예시의 `null`이 아니라 잠정 숫자값이다**(무기한 지연 방지를
위한 사용자 결정) — `config/tuning.yaml`의 `retention.groups.*`: evidence/recognition
30일, audit/tbm/risk_assessments 1095일(3년), office/sports 7일. **전부 "법률 전문가 확인
전 잠정값 — 고객사 개인정보 처리방침에 따라 계약 시 조정"** 주석이 tuning.yaml에 명시돼
있다. 정리 기능 자체(`retention.enabled`)는 여전히 기본 `false` — 잠정값이 들어있어도
명시적으로 켜지 않으면 아무것도 지워지지 않는다.

## 결과물

- `vigent-core/retention.py` — 스캔·삭제·회전 핵심 로직
- `scripts/retention_sweep.py` — CLI(가시성/dry-run/--execute)
- `vigent-core/data_engine.py` — `pin_evidence`/`unpin_evidence`/`pinned_paths`(A그룹 증거 보호)
- `tests/test_retention.py` — 11개 회귀 테스트(pin 보호·dry-run·disabled·경고·회전)
- `docs/ops_disk_sizing.md` — 카메라×규칙×보존일 용량 계산표
- 실측: 이 저장소 실제 데이터(evidence 96장·recognition 5개·risk_assessments 190건) 스캔
  소요시간 **0.033초**(F-2 원칙 — 라이브 검출과 무관한 별도 프로세스 전제, 그래도 참고 실측치)
