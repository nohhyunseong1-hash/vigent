# 평가 데이터셋 출처·라이선스·구성 (T13, B2G 실사 대비)

> 규칙7: 실제 취득·실측 기록. 원본 데이터셋은 git 미포함(용량·정책) — 평가 서브셋 매니페스트/스크립트로 재현.

## fire_smoke — D-Fire

| 항목 | 내용 |
|---|---|
| 출처 | **D-Fire** (GitHub `gaiasd/DFireDataset`) |
| 라이선스 | **CC0 1.0 (Public Domain)** — LICENSE 파일 직접 확인. 상업 이용·재배포 무제한, 출처표기 의무 없음 |
| 취득 | 2026-07-04, 사용자 직접 취득(공식 OneDrive), ~/Desktop/"D-Fire (1)"/ |
| provenance 실측 | 총 21,527장(train 17,221+test 4,306) = 공식 정확 일치. 총 박스 26,557 일치 |
| 클래스 정의(실측 확정) | YOLO id **0=smoke(11,865박스)·1=fire(14,692박스)** — 공식 클래스별 수와 정확 일치로 매핑 확정 |
| 현행 모델 매핑 | `fire_smoke_boda.pt` names {0:Fire,1:default,2:smoke} → guard 정규화 Fire→fire·smoke→smoke·default=JUNK. GT fire↔Fire, smoke↔smoke 직접 대응 |

### 평가 서브셋 (`build_fire_smoke_eval.py`, 결정적)
- D-Fire **test split**에서 파일명 SHA256 오름차순 층화샘플링(버킷 both/fire_only/smoke_only/none).
- 구성: **395장** — fire 220장/590인스턴스, smoke 330장/367인스턴스(각 ≥150장/≥300인스턴스 충족).
- 선택 목록 = `benchmarks/fire_smoke_eval_manifest.json`(커밋). 이미지·라벨은 `benchmarks/data/fire_smoke/`(gitignore).
- COCO: `instances.json` 957박스, pycocotools 로드 0에러, 박스수 assert 통과.
- **train/test 격리**: 공식 test split만 사용 → T10b 학습(train split)과 이미지 격리(FINDINGS 참조).

### ★ D-Fire 주석 특성 (baseline 해석에 필수)
- D-Fire는 **개별 화염을 각각 소형 박스로, 연기를 별도 영역으로** 세밀 주석(이미지당 화염 여러 개 흔함).
- 현행 boda 모델은 화재를 **대영역 1박스**로 검출(안전 경보용) → **박스 IoU@0.5 스키마 불일치**.
- 증거 오버레이: `benchmarks/results/fire_smoke_diag/`(GT fire=초록·smoke=파랑 vs 예측=빨강).
- 도메인: 지상 감시카메라 화재/연기 혼합(건물·차량·야간 산업 화재 등). 순수 실내 특화는 아님.

## forklift — LOCO (진행 대기)
- 출처 **LOCO**(`tum-fml/loco`), 라이선스 **Public Domain(CC0)**(README 확인), COCO 포맷, 창고/물류 도메인.
- 상태: **재다운로드도 손상(2회 연속)** — 2026-07-05 재취득본 dataset.zip **308MB**(기대 ~733MB의 40%),
  `unzip -t` 종료9 "cannot find zipfile directory", 헤더 `PK\x03\x04`이나 끝이 `</font></body></html>`(HTML 오류페이지로 절단).
  → LOCO 소스 링크가 계속 잘린 파일 반환. **클린 다운로드 수단 확보 필요**(TUM mediaTUM 직링크/미러/`wget -c` 재개 등).
- 도착 시 스펙: 무결성 확인 → 파일명 SHA256 기반 결정적 80/20 분할(test 목록 커밋) → forklift 평가셋(≥150장/≥300인스턴스) → COCO 변환 → box mAP + presence 이중 측정.

## 참고 — 감사에서 제외한 후보
- **ACID**(건설장비): "CC BY 4.0 but No commercial" = **비상업** → B2G 리스크로 제외.
- **FASDD**(화재): UAV·원격탐사(항공) 비중 큼 → 우리 지상 도메인에 약함, 제외.
- **Roboflow indoor-fire**(CC BY 4.0): 사용자 셋 표기 라이선스와 원본 이미지 권리 불일치 가능성 → **공식 baseline에서 격리**, 실내 도메인 '진단 참고'용으로만 별도 등록 예정(`fire_indoor_probe`).
