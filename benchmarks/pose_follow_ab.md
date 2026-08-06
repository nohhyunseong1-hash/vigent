# Phase 3 A/B — person을 BoxTracker anchor에 태울 때(구) vs 금지(신규)

입력: `_sweep_cache/multi_scene.json`(497프레임 실측 IoU baseline, 406x720).
anchor 신호: 프레임별 '화면상 가장 큰 person 박스' 중심(실측 검출 기반 대리 신호 — MediaPipe 실측 아님, 명시).

## 1) 다인 끌림 — 표시 박스가 '자기 tid 실측 위치'에서 벗어난 거리(대각선 정규화)
| 설정 | n | 평균오차 | p95오차 | 최대오차 |
|---|---|---|---|---|
| 구(anchor:true, person 포함) | 2590 | 0.0305 | 0.1633 | 0.285 |
| 신규(noAnchorClass:'person') | 2684 | 0.0028 | 0.0135 | 0.0967 |

## 2) 부드러움 회귀 — person 정지프레임%(연속 틱 박스 byte-동일 비율, box_quality.py와 동일 정의)
| 설정 | n | 정지프레임% |
|---|---|---|
| 구(anchor:true, person 포함) | 2542 | 57.47 |
| 신규(noAnchorClass:'person') | 2638 | 3.37 |

**끌림 평균오차 개선: 90.8%** (구 대비, 신규가 낮을수록 자기 위치를 더 정확히 따라감)