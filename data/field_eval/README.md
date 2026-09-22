# field_eval — 사고영상 정답지 (알려진 한계)

> 라벨·매니페스트 정본은 이 폴더(저장소, git 추적)다. 이미지는 개인영상정보라 저장소 밖
> (`VIGENT_DATA_DIR/field_eval`)에 있다 — `vigent-core/data_paths.field_eval()` 이 자동 분기한다.

## 구성

| 항목 | 값 |
|---|---|
| 원본 | 사고영상 9종(24fps), `VIGENT_DATA_DIR/runs/rfdetr/accident/*.mp4` |
| 라벨 프레임 | **109장** · 표본 간격 **1,000ms(1fps)** — 100구간 중 83이 1,000ms |
| 클래스 | person · Hardhat · NO-Hardhat · Safety-Vest · NO-Safety-Vest · Mask · NO-Mask |
| 형식 | YOLO 정규화 `cls cx cy w h`(5필드) — **track ID 없음** |
| 분할 | dev 74 / test 35, **영상 단위**(근접중복 누출 방지), `dev_test_split.json` 에 frozen |

## ★알려진 한계 (규칙 9 — 수치를 인용할 때 함께 적는다)

### 1. 사람이 존재하는 17구간(약 83프레임)이 라벨되지 않았다

인접 간격이 1,000ms 가 아닌 구간이 **17개**(2,000~7,000ms) 있다. 원본 24fps 영상에서
구간 중간 시점 83장을 뽑아 검출기(conf 0.10, 추적기 우회)로 확인한 결과
**17구간 전부에서 person 이 검출됐다**(최대 conf 0.417~0.956). 구간 양끝에도 person 라벨이
1~4명씩 있다. 즉 **"사람이 없어서 라벨이 없다" 는 것은 사실이 아니다.**

**왜 빠졌는지는 모른다.** 샘플링 규칙 문서가 없다(라벨링 누락인지 의도적 제외인지 불명).

★**영향**: 어려운 프레임이 제외됐을 가능성이 있다. 그렇다면 **검출기 재현율 71.3% 는 이 편향
위의 값**이다. 이 수치를 인용할 때 이 한계를 함께 적는다.

- 근거: `audit/long_gaps_20260922.json` · `scripts/eval/check_long_gaps.py`
- 프레임 83장: `VIGENT_DATA_DIR/field_eval/long_gap_check/` (**삭제 금지**)
- **후속**: 이 83장 추가 라벨링.

### 2. 1fps 표본이라 추적기 이후 지표를 대표하지 못한다

운영은 2fps(500ms)인데 이 정답지는 1,000ms 간격이다. 추적 성능은 프레임 간격에 직접
의존하므로, 이 표본으로 잰 **파이프라인 재현율·추적 파라미터 선택은 운영 조건과 다르다.**

- 폐기된 수치: "person 파이프라인 재현율 42.0%(dev 1fps)" — 커밋 `e1d875d`
- 유지되는 수치: **검출기** 재현율 71.3%(dev 1fps) — 검출 단계는 프레임 연속성과 무관.
  단 위 §1 의 편향은 그대로 적용된다.
- 현장 지표는 별도: 추적기 고신뢰 손실률 3.9%(현장 2fps) — `audit/passthru_field_20260922.json`

### 3. 사고영상이지 현장 카메라가 아니다

카카오톡 사고영상이며 학원 현장 CCTV 와 화각·해상도·조도가 다르다.
**현장 파이프라인 재현율의 근거로 쓰지 않는다.** 현장 지표는 재방문 수집으로 따로 만든다
(`docs/refield_plan_addendum_20260922.md`).

## 2fps 확장(진행 중, 2026-09-22~)

| 항목 | 값 |
|---|---|
| 목적 | **사고 상황 검출기 재현율 + 2fps IDSW** |
| 방법 | 1,000ms 쌍의 중간(+500ms)을 선형 보간해 **초안** 생성 → 사람이 뷰어로 검수 |
| 대상 | **person 만**(안전모·마스크는 1fps 에서 IoU 중앙값 0.000~0.17 로 자동 연결 불가) |
| 긴 간격 17구간 | **제외** — IDSW 는 연속 구간에서만 성립. 제외 사유·구간은 매니페스트 `gaps_excluded` 에 기록 |
| 스키마 | `track_id` · `source`(human/interp/human_verified) · `parent_track_id`(비움) · `video_role`(full/detector_only) |
| detector_only | `KakaoTalk_20260807_000721865` — 8프레임 중 6구간이 긴 간격이라 연속 쌍이 1개뿐 |
| 도구 | `scripts/eval/interpolate_gt_2fps.py` · 검수 뷰어 `scripts/eval/review_viewer.py` |

★**보간 결과는 초안이다. 정답지가 아니다.** 사람이 검수해 `source="human_verified"` 로 바뀐
것만 정답지로 쓴다(규칙 7·11).

**기존 109장 라벨은 수정하지 않는다.** 2fps 분은 `labels_2fps_draft/` 에 따로 쓴다.
