# tests/fixtures — 테스트 고정 표본 (얼굴 미식별만)

| 파일 | 출처 | 내용 | 확인 |
|---|---|---|---|
| `person_far.jpg` | `vigent-core/demo_assets/demo1.jpg` 사본(2026-06-24 영업 데모 자산) | 승마장 인물 1명, 원거리·저해상(80KB) — 얼굴 식별 불가 | 2026-09-06 육안 확인 |
| `no_person.jpg` | `vigent-core/demo_assets/demo4.jpg` 사본(Tapo 카메라 캡처) | 실내 배선·물건만, 사람 없음 | 2026-09-06 육안 확인 |

원칙([CLEANUP_PLAN.md](../../CLEANUP_PLAN.md) §5-3): 사고 영상·현장 스틸은 fixtures 에 넣지 않는다.
영상이 필요한 테스트는 `tools/make_test_video.py`(합성 이동 영상)로 만든다.
`.gitignore` 가 `*.jpg` 를 막으므로 이 폴더만 `!tests/fixtures/**` 로 예외.
