# track_debug 가 person 을 기록하지 못하던 결함 — 발견·수정·검증

- **날짜**: 2026-08-26 (학원 방문 전날, 출발 전 최종 점검 중)
- **발견 경위**: 방문 당일 절차의 `track_debug` 수집을 **현장에서 처음 하지 말자**는 판단으로
  리허설(1~2분 수집)을 돌렸다. 그 리허설이 아니었으면 현장에서 20분을 붓고 나서야 알았다.

## 증상

파일 카메라(`runs/rfdetr/accident/KakaoTalk_20260807_000438282.mp4`)로 90초 수집 후
`benchmarks/b_passthru_2fps_check.py` 를 돌리자:

```
추적 전 고신뢰 person(conf≥0.6): 0건
★그중 추적이 버린 것: **0건** (0.0%)
```

영상 탓으로 보였으나 아니었다. 같은 기록에 **`Hardhat` 624건 · `NO-Safety-Vest` 688건**이
있었다. PPE 박스로 역산한 몸통 높이가 화면의 31%(720p 기준 **222px**) — 작아서 놓친 사람이
아니라 **크게 찍힌 사람**이었다.

## 원인

계측이 `GuardAgent._track_iou` **안에** 있었다. 그런데 운영 설정은 `track.algo: bytetrack`
(2026-08-13 채택)이고, `_track_bytetrack` 은 person 을 먼저 떼어낸 뒤 나머지만 넘긴다:

```python
# vigent-core/agents/guard.py (수정 전)
person = [d for d in fresh if ... == "person"]
other  = [d for d in fresh if ... != "person"]
tracked_other = self._track_iou(other, track_key)   # ← person 이 없다
```

즉 **bytetrack 에서는 person 이 계측 함수에 도달할 수 없었다.** 기록되는 건 PPE·지게차·
COCO 잡객체뿐이었다. 분석 스크립트가 "수집 당시 추적기가 bytetrack 이었는가?"를 되묻고
있었는데, 실제로는 **bytetrack 이면 person 이 절대 안 담기는** 구조였다.

## 영향

방문 당일 `track_debug` 20분 수집은 **판정 3건(유령 박스·검출통과·구역 판정)의 재료**를
모으는 작업이다. 그 재료가 person 데이터다. 고치지 않았으면 20분·수십 MB 를 쓰고도
**측정 목적이 통째로 사라질 뻔했다.**

`VIGENT_TRACK_DEBUG` 는 기본 꺼짐이라 **운영 검출·판정에는 영향이 없었다**(계측 전용 결함).

## 수정

계측을 디스패처 `_track` 으로 올렸다 — algo 와 무관하게 `fresh` 원본 전체를 본다.
기록은 새 헬퍼 `_dbg_write(now, track_key, fresh, out)` 로 분리했다.

- `fresh` = 추적 전 원본(person 포함)
- `tracks` = **실제 반환분**(예전엔 내부 트랙 전체) — "버려진 검출" 판정엔 이쪽이 정확하다
- `hits`/`misses`/`age_ms` 는 `_track_iou` 내부 상태에서 `tid` 로 이어 붙인다.
  ByteTrack 이 모는 person 은 내부 상태가 트래커 안이라 `None`(분석기는 `label`·`bbox` 만 쓴다)
- `algo` 필드 추가 — 분석기가 되묻던 "수집 당시 추적기"를 기록 자체에 남긴다

## 검증 (4건 전부 통과)

| # | 조건 | 결과 |
|---|---|---|
| 1 | person 이 실제로 담기는가 | 0건 → **107건**(최고 conf 0.986), 추적 후 83건 ✅ |
| 1 | 기존 기록이 그대로인가 | 프레임당 Hardhat 1.89→1.81 · 조끼 2.40→2.31 · 지게차 0.49→0.48 ✅ |
| 2 | 분석기가 새 데이터를 읽는가 | `b_passthru_2fps_check.py` 완주 — 고신뢰 85건·버려진 9건·구간 분포·판정 선언까지 ✅ |
| 2 | 필드 형식 불변인가 | `fresh`{label,conf,bbox} · `tracks`{tid,label,bbox,hits,misses,age_ms} **동일** ✅ |
| 3 | 꺼진 상태 동작 불변인가 | ruff 0 · mypy 0 · **468 테스트 OK** · 드리프트 0 · OpenAPI 108 무변경 ✅ |
| 4 | 재발 방지 | `tests/test_track_debug_covers_person.py` 4건 추가 ✅ |

원자료: `audit/track_debug_rehearsal_2026-08-26.jsonl`(수정 전, person 0건) ·
`audit/track_debug_afterfix_2026-08-26.jsonl`(수정 후, person 107건).

## 현장 이중 안전장치

원인은 고쳤지만 **현장에서는 카메라 각도·조명·거리 때문에도 person 0건이 날 수 있다.**
그래서 20분을 붓기 전에 **1분 샘플로 거르는** 단계를 절차서에 넣었다:

```
.venv\Scripts\python.exe benchmarks\dbg_person_check.py
```

person>0 이면 계속, 0이면 즉시 중단하고 원인 3가지를 순서대로 확인한다(종료 코드 0/1).
안 풀리면 track_debug 를 포기하고 **녹화본 반출**로 대체한다.

## 교훈

- **측정 도구도 측정 대상이다.** 리허설 없이 현장에서 처음 켰으면 그날 측정을 날렸다.
- **0건은 "없다"가 아니라 "못 봤다"일 수 있다.** 같은 기록의 다른 라벨이 반증을 준다
  (Hardhat 624건 옆의 person 0건은 영상 문제일 수 없다).
- 이번 건은 [측정 위생 교훈](../audit/capacity_probe_invalid_2026-08-21.md)의 유령 카메라와
  같은 계열이다 — **이상한 수치는 장비보다 측정 경로부터 의심한다.**
