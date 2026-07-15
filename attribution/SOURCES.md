# forklift 재학습 데이터 — 출처·라이선스 증빙 (attribution)

> CC BY 4.0 데이터는 **저작자 표시(attribution) 의무**가 있다. 이 문서가 그 표시이며,
> 상업(B2G/유료) 납품 시 함께 배포/보관한다. 라이선스는 각 데이터셋 페이지 배지 확인 기준.
> 확인일: 2026-07-08.

## 사용 데이터셋 (상업 사용 가능, forklift 라벨 유효)

| 소스 | URL | 라이선스 | 이미지 | forklift inst | 다운로드 |
|---|---|---|---|---|---|
| csv2tfrecord/forklift-detection-koqxi | https://universe.roboflow.com/csv2tfrecord/forklift-detection-koqxi | **CC BY 4.0** | 7,383 | 3,761 | v2, 2026-07-08 |
| mohamed-traore-2ekkp/forklift-dsitv | https://universe.roboflow.com/mohamed-traore-2ekkp/forklift-dsitv | **CC BY 4.0** | 1,011 | 1,096 | v5, 2026-07-08 |
| robovis/forklift-ikbzl | https://universe.roboflow.com/robovis/forklift-ikbzl | **CC0 / Public Domain** | 116 | 117 | v1, 2026-07-08 |
| LOCO (tum-fml) | https://github.com/tum-fml/loco | **CC0 (Public Domain Dedication)** | 449(forklift) + 1,312(pallet_truck 네거) | 598 | 로컬 보유 |

## 배제 데이터셋 (정직한 기록)

| 소스 | 사유 |
|---|---|
| hitsz/forklift-and-human | 다운로드했으나 **실제 라벨이 cart(2,705)·person(1,801)뿐 — forklift 클래스 없음**. cart가 forklift인지 불명(추측 금지) → 배제 |
| vehicle-cqntc/forklift-ydsnk | Roboflow **공개 버전 0개**(versions=[]) → 다운로드 불가 → 배제 |

## 라이선스 준수
- 전부 상업 사용 가능(CC BY 4.0 = 표시 조건부 상업 OK / CC0 = 무조건). **비상업(NC) 데이터 없음.**
- CC BY 4.0(csv2tfrecord, mohamed): 본 문서로 저작자 표시 이행.
- 감사 라이선스 A(런타임 copyleft 0) 강점을 데이터에서 훼손하지 않음.
- 원본 export README는 각 `data/datasets/forklift_merge/sources/<name>/README.*`에 보존.
