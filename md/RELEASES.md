# VIGENT 릴리스 노트

## 태그 축 (두 축 분리 — 혼동 방지)

- **`v1.0-copyleft-zero`** (c1863d5) — **라이선스 축**: 배포 경로 강카피레프트(AGPL) 0 달성. T10b 전 검출 슬롯 RF-DETR(Apache) 이관 + A-4(ultralytics 배포 requirements 제거). 런타임 실증으로 `sys.modules` 에 ultralytics 부재 확인.
- **`v1.0.1-server-verified`** (3725eb1) — **성능검증 축**: "측정=배포" 보증. 서버 실배포(`/detect/frame`) 검출기가 EVAL 인프로세스 수치와 **Δ0.00 일치**(F-8 silent failure 차단: rfdetr 커스텀 가중치 경로버그로 서버가 COCO로 조용히 폴백하던 결함 해소).

> **v1.0 = 라이선스 축(copyleft 0), v1.0.1 = 성능검증 축(측정=배포).** 두 축은 독립이다 — v1.0 시점에도 라이선스(배포물에 AGPL 없음)는 유효했고, "서버 배포가 측정 성능을 실제로 낸다"는 보증은 v1.0.1부터 성립한다.

### 잔여(다음 마일스톤 후보)
- **현장 재검증(T10c-V)**: 이관 4종(person/ppe/fire_smoke/forklift)의 in-domain 한계 해소 — 현장 영상 일반화 검증.
- **라이브 추적 계층 검증**: 낱장 mAP로 안 잡히는 추적 고유 실패(ID 스위치·유령추적) 연속 프레임 시퀀스 회귀(FINDINGS F-8 백로그).
