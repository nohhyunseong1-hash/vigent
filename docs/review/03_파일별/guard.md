# agents/guard.py (1,014줄) — 검출·추적·파생신호

**책임 한 줄**: 프레임 1장을 받아 박스·라벨·추적ID·파생신호(`ppe_missing` 등)를 만든다.

**진입점·호출 관계**
- `detect()` :830 — **177줄, 저장소 최장 함수.** 호출: worker(`:888/:894`) · routers/detect · 오프라인 도구들.
- 내부 사슬: `_nms` :156 → `_suppress_vehicle_dupes` → `_containment_suppress` :106 → `_cross_validate_ppe` :132 → `_track` :570(→bytetrack :678 / iou :726) → passthrough 분기 → `_merge_cross_source_person`.
- 상태: `_tracks`·`_sig_streak`(track_key 별) — 스윕 `_maybe_sweep_stale_keys` :631.
- 모델: `_get_model` :795 슬롯별 지연 로딩.

**★불변 조건**
1. `detect` 는 **track_key 격리** — 다른 카메라/호출자의 상태가 섞이면 안 된다.
2. 호출자는 `DETECT_LOCK`(RLock)을 잡는다 — **이 파일 안에서 그 가정이 문서화돼 있는가**?
3. 단계 순서가 계약이다: 교차검증은 추적 **앞**(옮기면 고아 PPE 소멸 = 미탐 증가 — 의도적 현행 유지).
4. 모델 로드 실패는 그 슬롯만 죽인다(+ /health DEGRADED).

**의심하며 볼 지점**
| 위치 | 질문 |
|---|---|
| :830 `detect` 177줄 | 인접 단계 순서를 바꾸면 깨지는 쌍이 몇 개인가 — **순서 의존을 주석으로 다 적었는가** |
| :631 `_maybe_sweep_stale_keys` | `_sig_streak`·`_tracks` **둘 다** 쓸어주나? 한쪽만 쓸면 유령 항목(계열 E) |
| :678 bytetrack | supervision 객체 재사용 — **track_key 마다 분리**돼 있는가(카메라 간 오염) |
| :795 `_get_model` | 두 스레드가 같은 슬롯을 동시에 처음 부르면(지연 로딩 경합 — 계열 C·F) |
| :594 `_dbg_write` | 계측이 어느 분기에 있나 — ✔G 병력(iou 안에만 있어 bytetrack 누락)이 **재발했는지** |
| :1008 `_hysteresis` | raw=False 즉시 리셋 — 깜빡이는 검출(원거리)에서 발화가 굶는 구조(실측: 임계미달 33프레임과 결합) |

**알려진 함정**
- `PASSTHROUGH_CONF=0` 기본 off — 켜본 실전 없음, 테스트 얇음(06 참조).
- `person_ensemble=True` 라 `_drop_ppe_origin_person` 은 **안 도는** 분기.
- LABEL_NORMALIZE·ppe_per_class 등 설정 병합부는 계열 I 후보.
