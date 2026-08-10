# vigent-core/weights/ — 가중치 소재 매니페스트 (2026-08 신설, [I])

> `weights/`는 `.gitignore` 대상(용량)이라 **어느 머신에 뭐가 있는지 git 히스토리로 추적이 안 된다**
> — 이번에 데스크탑에 PPE 가중치가 없어 진행이 막혔던 원인. 이 파일(`MANIFEST.md`)만 예외로
> git에 커밋한다(`.gitignore`에 `!vigent-core/weights/MANIFEST.md` 명시) — **가중치 파일 자체는
> 계속 gitignore 유지**, 여기엔 "무엇을 어디서 구해서 어떻게 검증했는지"만 기록한다.
>
> **새 가중치를 이 폴더에 배치할 때마다 이 표에 한 줄 추가할 것.**

## ppe_rfdetr_v1.pth (현재 슬롯: `themes/safety/vision.yaml` `rfdetr_weights.ppe`)

| 항목 | 값 |
|---|---|
| 파일명 | `ppe_rfdetr_v1.pth` |
| SHA256 | `3380fa7d4bb1be878698535d575050e13a52330ffab0d37a16dd0a16c50bf570` |
| 바이트 크기 | `120910843` |
| 배치 경로 | `vigent-core/weights/ppe_rfdetr_v1.pth` |
| 확인일 | 2026-08-07 (이 데스크탑, Google Drive에서 직접 다운로드해 배치) |
| Drive 출처 | **(미기록 — 사용자가 실제 공유 링크/파일ID를 알려주면 갱신)** |
| 학습 노트북 | Colab(구 문서 "best_ema" 표기 — 아래 §정정 참고, 노트북 링크 자체는 미기록) |
| 모델 아키텍처 | `RFDETRNano`(체크포인트 `model_name` 필드 실측), rfdetr 1.8.0, PyTorch-Lightning 2.6.5, global_step=8150 |
| 학습 데이터셋 | Roboflow Universe 공개셋 **"Construction Site Safety" v27**(체크포인트 `args.dataset_dir=/content/data/ppe_rfdetr_ds`, `dataset_file=roboflow`) |
| 라이선스 | CC BY 4.0(Roboflow Universe 공개셋 — `md/VIGENT 정확도 측정 기록.md` 기존 기록과 일치) |
| 클래스(10개, 체크포인트 `args.class_names` 실측) | `Hardhat, Mask, NO-Hardhat, NO-Mask, NO-Safety Vest, Person, Safety Cone, Safety Vest, machinery, vehicle` — VIGENT 7종 스킴(`person·Hardhat·NO-Hardhat·Safety-Vest·NO-Safety-Vest·Mask·NO-Mask`)과 정확히 매칭(대소문자·공백만 `guard.py LABEL_NORMALIZE`가 정규화), `Safety Cone`/`machinery`/`vehicle` 3개는 우리 스킴 밖(무시됨) |
| 로드 검증 | `/health`의 `rfdetr_slots` → `ppe: state=LOADED`(2026-08-07 확인, `MISSING_FALLBACK` 아님) |

### [W-1] 학습 데이터셋(css v27) 재확보 — 검증 결과 (2026-08-10)

`data/datasets/css_safety`가 이 데스크탑에 없어(확인됨) 위 §학습 데이터셋의 v27이 로컬에
부재했다. Roboflow REST API로 원본을 재확보하고 위 표의 기록과 대조 검증했다:

| 항목 | MANIFEST 기록 | 재확보본 실측 | 일치 |
|---|---|---|---|
| 클래스(10개) | `Hardhat, Mask, NO-Hardhat, NO-Mask, NO-Safety Vest, Person, Safety Cone, Safety Vest, machinery, vehicle` | `data.yaml`의 `names` 필드가 순서·표기까지 동일 | ✅ |
| 라이선스 | CC BY 4.0 | `data.yaml`의 `roboflow.license` = CC BY 4.0 | ✅ |
| 출처 | v27 | `data.yaml`의 `roboflow.version`=27, `url`=`https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety/dataset/27` | ✅ |
| test 분할 수 | 82(기존 `vision.yaml` 주석 "test 82 box mAP@50 75.62%"와 일치) | 82장 실측(`test/images` 파일 수) | ✅ |
| valid 분할 수 | (미기록) | 114장 | 참고 |
| train 분할 수 | (미기록) | 2603장(API 메타데이터 상 증강 후 2605 — 2장 차이, 원인 미확인이나 나머지 전 항목이 정확히 일치해 동일 데이터셋으로 판단) | 대체로 일치 |

**다운로드 경로**: Roboflow REST API(`api.roboflow.com/roboflow-universe-projects/construction-site-safety/27/yolov8?api_key=...`)로 export 링크를 얻어 zip(157.2MB) 다운로드 → `data/datasets/css_safety`에 압축 해제(YOLOv8 포맷, `train/valid/test` 각 `images/labels`). API 키는 기존 `.env`의 `ROBOFLOW_API_KEY`(이미 설정돼 있었음 — 새 발급 없음). `data/`는 `.gitignore` 대상이라 이 데이터셋 자체는 git에 안 들어간다.

**참고(v27 자체 내장 증강, `data.yaml`이 아니라 API 메타데이터 `augmentation` 필드 실측)**: 이 v27 export는 Roboflow 플랫폼에서 이미 `versions:5`(원본 521장→train 2605장), `cutout`(2%, 6회), `blur`(0.5px), `rotate`(12˚) 등을 적용한 증강본이다 — [V-1]에서 만들 별도 person 가림/축소 증강과는 무관한, 데이터셋 자체의 기존 증강이니 혼동 주의.

### 정정(규칙7): "best_ema"가 아니라 "best_total"
`themes/safety/vision.yaml`의 기존 주석은 이 가중치를 "Colab best_ema" 산출물로 적어뒀으나,
실측 결과 **이 파일은 `checkpoint_best_total.pth`(120,910,843B)와 바이트 크기가 정확히 일치**한다
(`checkpoint_best_ema.pth`는 120,922,427B로 11,584B 다름). 체크포인트 내부 메타데이터도 이를
뒷받침한다: `args.use_ema=True`(학습 중 EMA는 켜져 있었음)이지만 `args.early_stopping_use_ema=False`
(어느 체크포인트를 "best"로 선정할지는 EMA 아닌 일반 가중치 기준)이고, `model`/`state_dict`에 별도
EMA 전용 키가 없다(EMA 사본이었다면 보통 구분되는 키가 있음) — **best_total로 결론.**
`vision.yaml`의 주석을 정정했다(별도 커밋).

**측정치 재현성 경고**: 기존 문서(`vision.yaml`)에 적힌 "test 82 box mAP@50 75.62%"가 정확히 어느
체크포인트(ema 인지 total 인지)를 측정한 값인지 이 저장소 안에서 재현 가능한 기록을 못 찾았다
(측정 자체가 Colab에서 이뤄져 로컬 아티팩트가 없음). **이 파일(best_total)에 대해 로컬로 새로
측정된 mAP는 아직 없다** — 76.62%를 이 파일의 실측치로 그대로 인용하지 말 것(모른다 — 규칙7).

## 그 외 vision.yaml 참조 가중치 (이 데스크탑엔 없음 — 확인되는 대로 채울 것)

| 파일명 | 슬롯 | 상태 |
|---|---|---|
| `forklift_rfdetr_v1.pth` | forklift(rfdetr) | 이 환경에 없음(`/health` MISSING_FALLBACK 확인) |
| `fire_smoke_rfdetr_v1_e17.pth` | fire_smoke(rfdetr) | 이 환경에 없음(`/health` MISSING_FALLBACK 확인) |
| `ppe_css_v1.pt` | ppe(yolo 폴백, 비활성 backend) | 미확인 |
| `forklift_boda_ax.pt` | forklift(yolo 폴백) | 미확인 |
| `fire_smoke_boda.pt` | fire_smoke(yolo 폴백) | 미확인 |
| `yolo11m.pt` / `yolo11s.pt` | person(fallback) | 이 환경에 있음(`/health` 확인됨, SHA256 미기록 — 필요시 추가) |
| `yolov8n-pose.pt` | pose(레거시 이름, 실제 백엔드 RTMPose) | 미확인 |
