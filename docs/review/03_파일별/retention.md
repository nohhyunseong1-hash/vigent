# retention.py (332줄) + retention_scheduler.py (140줄) — 자동 파기

**책임 한 줄**: 보존 기한 지난 증거 파일을 **지운다**(되돌릴 수 없는 유일한 상시 동작).

**진입점·호출 관계**
- 주기 실행: main.py:385 `retention_scheduler.start()` → `_loop` :71 → `_run_once` :52 → `retention.sweep` :201.
- 수동: `scripts/retention_sweep.py`.
- 경계: `allowed_roots` :88 · `is_path_allowed` :109 — 지워도 되는 뿌리의 화이트리스트.

**★불변 조건**
1. **화이트리스트 밖은 절대 지우지 않는다** — `is_path_allowed` 가 마지막 방벽.
2. dry-run 이 기본이거나, 실삭제는 명시적 opt-in 이다(`is_dry_run` :146 — 어느 쪽인지 **확인**).
3. 스케줄러 스레드 최대 1개, stop 은 join(★alert_queue 병과 같은 패턴인지 :110 확인).

**의심하며 볼 지점**
| 위치 | 질문 |
|---|---|
| :201 `sweep` **124줄** | 삭제 대상 결정 로직 — 심볼릭 링크·정션(Windows)·상대경로 `..` 를 `is_path_allowed` 가 막는가(**S2 최우선**) |
| :109 `is_path_allowed` 13줄 | `resolve()` 를 쓰는가? 문자열 prefix 비교면 `D:\vigent2` 가 `D:\vigent` 에 걸리는 고전 버그 |
| :52 `_run_once` | 예외 시 다음 주기에 재시도되나, 스레드가 죽나(계열 B·K) |
| :88 `allowed_roots` | 설정 오타로 루트가 비면 — "지울 게 0개 = 통과"인가(규칙 11: 0의 의미) |
| 스케줄러 :92 `start` | 중복 start 방어 — 두 스레드가 동시에 sweep 하면 경합 |

**알려진 함정**
- [F6] "실행 주체 없음"은 해소됐지만 `SAFETY_REVIEW_REPORT.md` 는 아직 "미조치"라 적혀 있다(05_문서불일치 #5).
- 테스트가 실삭제 경로를 얼마나 밟는지 **미확인**(06 §3) — 검토 때 직접 세라.
