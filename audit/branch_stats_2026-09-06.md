# 브랜치 통계 — audit/cleanup-20260906 (5단계 5-3, 2026-09-06 실측)

기준: 태그 `audit-before-cleanup` = `e1ba0ab`(감사 시작 직전) → HEAD.

| 항목 | 값 |
|---|---|
| 커밋 수 | 59(3단계 `[감사]` 11 · 4단계 `[CODE_REVIEW]` 48) + 5단계 |
| `git diff --shortstat e1ba0ab..HEAD` | 424 files changed, 13,071 insertions(+), 3,575 deletions(-) |
| 커밋별 stat 누적(`git log --shortstat`) | 파일변경 766 · +10,339 · −5,571 (같은 파일이 여러 커밋에서 바뀐 것을 합산) |
| 추적 파일 수 | 1,054 → 1,064 |
| 추적 파일 용량(blob 합) | 58.9MB → 22.9MB (−36.0MB: 영상·현장 이미지 98파일 사설 폴더로, field_eval jpg 530장 사설 폴더로) |
| 삭제 / 추가 / 이름변경 | 113 / 123 / 40 (삭제 확장자: jpg 77 · mp4 21 · py 9 · json 4 …) |
| 테스트 파일 | 61 → 92 (`tests/test_*.py`) |
| 테스트 수 | README 기준 34(감사 전 문구) → 481(4단계 시작) → **638**(종료, 새 클론에서도 638 OK) |
| requirements | `requirements.txt`·`-optional`·`-eval` → `requirements.txt`(서빙)·`-agents`(LLM·RAG)·`-train`(학습·측정, 구 eval 흡수)·`-optional` |
| 저장소 pack 크기 | 47.19 MiB(이력 포함 — 민감 미디어 2a98fa9·b9e8289 는 이력에 남아 있음, 재작성 미실시) |

디렉터리별 변경 비중(파일 수, 상위): audit/logs_service_crashloop 12.9%(→ 5-3 에서 zip 1개로 대체) · tests 11.6% · benchmarks 9.8% · runs/site01_eval 5.3% · vigent-core 4.5% · docs 2.5%.

전체 목록은 `git log --stat e1ba0ab..HEAD` 로 재현한다(이 파일은 요약만 둔다).
