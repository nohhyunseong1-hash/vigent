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

## forklift — LOCO (T13b, 취득·측정 완료)

| 항목 | 내용 |
|---|---|
| 출처 | **LOCO**(`tum-fml/loco`), 창고/물류 도메인, COCO 포맷 |
| 라이선스 | **CC0 / Public Domain**(README 확인) — B2G 재배포 적법 |
| 취득 | 2026-07-05 재다운로드. 이미지 zip(공식 TUM webdisk, go.mytum.de/239870 리다이렉트) + 어노 `loco-all-v1.json`(공식 GitHub raw) |
| 취득 경위 | **1차본 손상으로 재취득**. 수동 다운로드가 2회 연속 HTML로 절단(308MB/기대 733MB) → **aria2c 8연결**로 클린 취득. 3중 검증 통과(769,055,500 bytes 정확·Zip·`unzip -t` 무결) |

### provenance 실측 (2026-07-05)
- 이미지: **zip 5,593장 = 공식 정확 일치**. 어노(`loco-all-v1.json`) 참조 이미지 5,097장(무어노 496장은 zip에만).
- 어노테이션: **실측 151,428개** vs 논문 표기 152,421(차이 993, −0.65%). 차이는 논문 시점과 공개 버전의 표기/정제 차로 판단.
- **사용 클래스(forklift) 무결성 별도 확인**: forklift(id5) = **598 inst / 449 img**(재측정 일치). 전체 총계 경미 차이는 우리 클래스 품질에 무관.
- 클래스 분포(실측): pallet 120,445 · small_load_carrier 22,151 · stillage 5,407 · pallet_truck 2,827 · **forklift 598**(최희소).

### 평가셋 구축 (`build_forklift_eval.py`, 결정적)
- **분할**: forklift 등장 449장을 SHA256(file_name) 결정적 분할. LOCO는 forklift 희소 → 80/20은 test ~89장으로 기준(150img/300inst) 미달.
  → **희소 class 라 test 비율 상향**: 0.50(288inst, 미달)→**0.55 채택**(test 238img/**316inst**, train 211img). baseline·T10b 모두 이 test로만 측정(같은 시험지).
- **네거티브 80장(test 전용, FAR 측정용)**: forklift 0개 이미지만(라벨 오염 방지) 중 **hard(pallet_truck 등장) 40 + 일반 창고 40**. hard 는 동력 지게차와 최혼동 물체 → FAR 실질가치.
- 매니페스트 `forklift_eval_manifest.json`(커밋): test/train/negative 목록 + `t10b_no_inject`(test+네거 = 학습 유입 금지).
- 이미지·라벨은 `benchmarks/data/forklift/`(gitignore). YOLO 라벨 박스수 assert 통과.
- **pallet_truck 병합 안 함**: 동력 지게차와 다른 위험군(수동 핸드트럭), `vehicle_ref_m.forklift=2.5m` 오염 방지. 별도 검출 클래스 후보로 FINDINGS 백로그.

### ★ forklift baseline 해석(도메인갭)
- `forklift_boda_ax.pt`는 **다른 출처(boda)** 학습 → LOCO 창고 도메인에서 confidence 낮음. box mAP 저조(raw 7.61%)는 **도메인갭+저신뢰**(스키마 아님 — 검출 시 국소화는 정상, IoU≥0.5가 31%).
- 배포 운용점(conf 0.68): **recall 35.7% + FAR 28.7%**(pallet_truck 혼동으로 네거 80장 중 23장 오탐) → 저recall·고오탐 양쪽 약함. 근본 해결 = T10b(LOCO 재학습 + pallet_truck hard negative).
- 도착 시 스펙: 무결성 확인 → 파일명 SHA256 기반 결정적 80/20 분할(test 목록 커밋) → forklift 평가셋(≥150장/≥300인스턴스) → COCO 변환 → box mAP + presence 이중 측정.

## 참고 — 감사에서 제외한 후보
- **ACID**(건설장비): "CC BY 4.0 but No commercial" = **비상업** → B2G 리스크로 제외.
- **FASDD**(화재): UAV·원격탐사(항공) 비중 큼 → 우리 지상 도메인에 약함, 제외.
- **Roboflow indoor-fire**(CC BY 4.0): 사용자 셋 표기 라이선스와 원본 이미지 권리 불일치 가능성 → **공식 baseline에서 격리**, 실내 도메인 '진단 참고'용으로만 별도 등록 예정(`fire_indoor_probe`).
