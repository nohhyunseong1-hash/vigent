# 골든셋 채점 리포트 — 2026-07-06T07:45:25.517512+00:00
- 아이템 10 · 합격 10 · pass-rate 1.0
- judge: {'provider': 'openai', 'model': 'gpt-4o', 'temperature': 0} · scribe_sha 817dedc

| 아이템 | 게이트 | judge | 합격 |
|---|---|---|---|
| edge_contradiction_001 | ✅ | - | ✅ |
| edge_contradiction_002 | ✅ | - | ✅ |
| edge_empty_001 | ✅ | - | ✅ |
| edge_empty_002 | ✅ | - | ✅ |
| edge_empty_003 | ✅ | - | ✅ |
| edge_metaloss_001 | ✅ | - | ✅ |
| edge_metaloss_002 | ✅ | - | ✅ |
| edge_outofscope_001 | ✅ | - | ✅ |
| edge_timeseries_001 | ✅ | - | ✅ |
| edge_timeseries_002 | ✅ | - | ✅ |

## 캘리브레이션 (임계 0.8 · rubric_sha 4fc62cb2074e · 채점 0건)
히스토그램(0.1 bin): 
경계(0.7~0.9): 없음

## 알려진 한계 (verdict 과대해석 금지)
- citation_valid 게이트는 '조 번호' 수준 검증이며 법령명(법/규칙)을 구분하지 않는다. '산업안전보건법 제38조'와 '안전보건규칙 제38조'를 동일 취급 → 법령명 오인용은 미검출. 게이트 v2(법령명+조 키 매칭)는 후속 항목으로 기록됨.
- law_whitelist 는 대표 조항만 등록 — RULE_KB 범위 조항(예: 제619~625조)은 대표 조항으로만 검증됨.