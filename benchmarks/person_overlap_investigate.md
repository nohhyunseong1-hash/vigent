# Phase 1 조사 — person 박스 겹침 원인 (수정 없음)

입력: `_sweep_cache/multi_scene.json`(497프레임 실측, ByteTrack tid 포함).

## A) 서버 원본(raw) — 같은 프레임에 다른 tid person 박스가 이미 겹치는가
- 멀티person 프레임: 366/497
- IoU>0.10 겹침 프레임: 112 (22.5%)
- IoU>0.40 겹침 프레임: 1 (0.2%)

## A) 신규 tid 탄생이 파편화(최근 6프레임 내 인접 tid와 공간중첩)로 보이는 비율
- 신규 tid 탄생 수: 42
- 이 중 공간중첩(IoU>0.15): 14 (33.3%)

## B/C) 클라 표시단(BoxTracker, 프로덕션 설정 anchor:true+noAnchorClass:'person') 출력 겹침
- 렌더틱: 1270, 겹침틱(IoU>0.10): 272 (21.4%)
- 겹친 쌍 수: 274, 평균IoU: 0.136, 이 중 IoU≥0.40(=dedup 임계 이상인데도 안 잡힘): 0
- tid<0(fallback) person 표시 항목 수: 0 (0이면 C=페이드잔존 구조적으로 불가)

## 참고: anchor 끄면(순수 id매칭+One-Euro+dedup만) 겹침이 달라지는가
- 렌더틱: 1270, 겹침틱(IoU>0.10): 272 (21.4%)
- 겹친 쌍 평균IoU: 0.136, IoU≥0.40: 0
