# 최근 수정 5건 회귀 확인 (2026-08-24)

> **대상**: F1·F2·F5·F6·F29 — [docs/CODE_REVIEW_AZ.md](../docs/CODE_REVIEW_AZ.md) 의 ✅ 항목.
> **방법**: ①코드 직접 확인 ②담당 테스트 실행 ③`/health` 실호출. 셋 다 되는 항목만 "완전"으로 적는다.
>
> ★**라이브 확인의 한계를 먼저 밝힌다**: 개발 PC 의 가동 중 서비스는 uptime **41,865초(약 11.6시간)**
> 로, 오늘 수정 **이전**에 뜬 구 코드다. 실카메라가 붙어 있어 임의 재시작을 하지 않았다.
> 그래서 ③은 **현재 코드로 `/health` 를 실제 호출**(TestClient)해 확인했다 —
> "가동 중 서비스가 그렇다"가 아니라 "현재 코드가 그렇다"는 뜻이다.

## 결과표

| 수정 | ①코드 | ②테스트 | ③/health(현재 코드) | 판정 |
|---|---|---|---|---|
| **F1** 슬롯 저하 노출 | ✅ `system.py:60·154·184` 에서 꺼내기→판정→본문 3곳 배선 확인 | ✅ `test_safety_review_fixes` 17건 | ✅ `slot_degraded: {}` 필드 존재 | **완전** |
| **F2** 기록 실패 격리 | ✅ AST 검사 — `_save_frame.mkdir`·`log_event.mkdir/open` **3건 모두 try 안** | ✅ 위 17건에 포함(통합 5건) | — (디스크풀 상황 필요) | **코드·테스트 확인** |
| **F5** 구역 폴백 차단 | ✅ `worker.py:949·954·960·963` — camera/global/none 3분기 + 상태 노출 | ✅ 위 17건에 포함 | ⚠ 워커 기동 필요(TestClient 는 카메라 없음) | **코드·테스트 확인** |
| **F6** 자동 스윕 | ✅ `retention_scheduler.py:58` — `sweep()` **execute 인자 없음**(첫 주기 보류 유지) | ✅ `test_retention_scheduler` 13건 | ✅ `auto_sweep:True · interval_h:24.0 · failures:0` | **완전** |
| **F29** relay flake | ✅ `ThreadingHTTPServer` + `start(wait_s)` 기동 대기 | ✅ `test_relay` 10건 (단독 3회·전체 4회 연속 통과) | — (mock 전용) | **코드·테스트 확인** |

**추가 확인 — F31**(오늘 수정): `slot_errors: {}` 필드가 `/health` 에 존재. 테스트 11건 통과.
수정 전 코드로 돌리면 5건이 실패함을 확인해 **테스트가 실제로 결함을 잡는지**까지 검증했다.

## 남은 것 — 재시작해야 완결되는 항목

F5 의 `zone_source`·`zone_points` 는 **워커가 떠야** 채워진다. 개발 PC 서비스를 재시작하면
바로 확인되지만, 실카메라 가동 중이라 하지 않았다. **노트북 소크에서 함께 확인**하면 된다
(`docs/soak_after_safety_fixes.md` 3단계에 이미 포함돼 있다).

## 프로파일 드리프트 (같은 날 처리)

- 저장소의 학원 프로파일에 **누락 6키가 그대로 남아 있었다**(노트북 세션의 수정은 미푸시).
  → `scripts/check_profile_drift.py --fix` 로 채우고, 값 보존을 확인했다.
- `vision.academy.yaml` 도 person 항목이 기본값과 어긋나 있어 동일하게 정리했다.
  ★**forklift 항목은 건드리지 않았다** — 학원은 `backend.forklift=yolo` 라 경로가 필요하고,
  지우면 지게차 검출이 조용히 죽는다(테스트로 고정).
- 게이트 테스트 5건 추가. 기본값에 임시 키를 넣어 **실제로 실패하는지 확인**했다.
