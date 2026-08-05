# B-1 — person 슬롯 COCO 잡클래스 필터 추적 결과 (2026-08-06)

> 결론: **코드 변경 없음.** 표시 경로엔 이미 `web_util.is_safety_label` 필터가 걸려 있고, 실제로 걸린다는 것을
> 실측(전/후)으로 확인했다. Phase1 감사가 보고한 "person 없이 뜬 타클래스 12~16%"는 **필터를 거치지 않은
> 원시 `guard.detect()` 출력을 측정한 진단값**이었고, 실제 사용자가 보는 값이 아니었다.

## 추적한 경로

| 경로 | 필터 적용? | 근거 |
|---|---|---|
| 허브 그리드뷰 (`index_hub.html:468`) | ✅ | `/cameras/{cid}/detections` 호출 |
| 허브 확대뷰 (`index_hub.html:351,377`) | ✅ | 동일 엔드포인트 |
| `/cameras/{cid}/detections` (`routers/cameras.py:118-127`) | ✅ | `dets = [d for d in wk._last_dets if _is_safety(d.get("class"))]` — `_is_safety = web_util.is_safety_label` |
| 필드명 일치 확인 | ✅ | `worker.py:83` `_det_dict()`가 `"class"` 키로 반환 → cameras.py의 `d.get("class")`와 정확히 일치 |
| 브라우저 safety 모드 (`realtime_core.js:989`) | ✅(조건부) | `safety_only: activeServiceMode==='safety'` — safety 모드에서 true 전달 → `routers/detect.py:196-197`에서 필터 |
| 워커 위험판정(`_derive`, `worker.py:106-132`) | 해당없음(설계상 안전) | 신호는 라벨 문자열을 직접 비교(`ppe_missing`·`fire_smoke`·`forklift`·`person`)하므로 COCO 잡클래스(bed·dining table 등)가 애초에 그 라벨과 매칭될 수 없음 — 잡음이 신호를 오염시킬 경로 자체가 없음 |
| `proximity.detect`(협착) | 해당없음 | `VEHICLE_REF_M`(forklift·truck·car·bus 등)만 대상 — COCO 잡클래스 무관 |

## 측정 (전/후)

새 하네스 옵션 `--safety-only-filter`(`box_quality.py`)로 **실제 앱이 쓰는 것과 동일한 함수**
(`web_util.is_safety_label`, 재구현 아님·직접 import)를 검출 스트림에 적용해 재측정했다.

| 영상 | 필터 전(진단, Phase1) | 필터 후(실사용, 이번 측정) |
|---|---|---|
| test_fast | person없이뜬타클래스 12.5~15.8% (시나리오별) | **0.0%(전 시나리오)** — `box_quality_test_fast_filtered.md` |
| test_walk | person없이뜬타클래스 5.7~6.7% (시나리오별) | **0.0%(전 시나리오)** — `box_quality_test_walk_filtered.md` |

필터 적용 시 검출 수 자체도 감소(예: person+잡클래스 혼합 919개 → person만 328개 수준, 정확한 수치는
각 필터 리포트의 "검출 현황" 참고) — 잡클래스가 실제로 걸러진다는 것을 직접 확인.

## 결론

- **B-1이 우려한 누락은 존재하지 않는다.** 표시(그리드·확대뷰)·브라우저(safety 모드)·이벤트판정(신호 라벨매칭)
  전부 이미 안전하다.
- Phase1 감사의 "12~16%" 수치는 **틀린 게 아니라 범위가 달랐다** — "필터를 안 거치면 이 정도"라는 진단값이었지,
  "사용자가 보는 값"이 아니었다. 이번에 그 구분을 명시적으로 측정해 교차검증했다.
- 하네스에 `--safety-only-filter`를 남겨둔다 — 앞으로 다른 클립·다른 검출기 조합으로 재측정할 때도
  "진단값 vs 실사용값"을 항상 구분해서 보고할 수 있게.
