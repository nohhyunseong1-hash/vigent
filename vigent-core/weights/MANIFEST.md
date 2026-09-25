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
| test 분할 수 | 82(기존 `vision.yaml` 주석 "test 82 box mAP@50 75.62%"(단서 2026-09-25: valid/test 영상의 83~93%가 train에 포함된 누출 분할. 실성능 미확인. docs/model/ppe_rfdetr_v1_provenance.md 참조)와 일치) | 82장 실측(`test/images` 파일 수) | ✅ |
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

**측정치 재현성 경고**: 기존 문서(`vision.yaml`)에 적힌 "test 82 box mAP@50 75.62%"(단서 2026-09-25: valid/test 영상의 83~93%가 train에 포함된 누출 분할. 실성능 미확인. docs/model/ppe_rfdetr_v1_provenance.md 참조)가 정확히 어느
체크포인트(ema 인지 total 인지)를 측정한 값인지 이 저장소 안에서 재현 가능한 기록을 못 찾았다
(측정 자체가 Colab에서 이뤄져 로컬 아티팩트가 없음). **이 파일(best_total)에 대해 로컬로 새로
측정된 mAP는 아직 없다** — 76.62%를 이 파일의 실측치로 그대로 인용하지 말 것(모른다 — 규칙7).

## ppe_rfdetr_v1.onnx ([C-3] 저가 CPU 박스 배포용 ONNX fp32, 2026-08-12)

`ppe_rfdetr_v1.pth`를 ONNX로 변환한 것 — `config/tuning.yaml`의 `detect.backend:
onnx-cpu` 설정 시 이 파일을 로드한다(`detect.backend: torch`가 기본값이면 이 파일은
쓰이지 않는다). 근거: `benchmarks/onnx_cpu_bench.md`([C-2]) — torch fp32 대비 CPU
추론 1.85배 빠르고 dev 74장 person/PPE/NO-Hardhat 재현율 전부 동일(정확도 손실 0 확인).

| 항목 | 값 |
|---|---|
| 파일명 | `ppe_rfdetr_v1.onnx` |
| SHA256 | `beb80941a2c920e87113af89d7e9265852c8f7abc47c4f9607847667f6da8a2a` |
| 바이트 크기 | `115033243` |
| 배치 경로 | `vigent-core/weights/ppe_rfdetr_v1.onnx`(gitignore 대상, 이 표만 커밋) |
| 원본 pth SHA256 | `3380fa7d4bb1be878698535d575050e13a52330ffab0d37a16dd0a16c50bf570`(위 `ppe_rfdetr_v1.pth`와 동일 — 같은 가중치에서 변환) |
| 변환일 | 2026-08-12(이 데스크탑) |
| 변환 커맨드 | ```python\nfrom rfdetr import RFDETRNano\nm = RFDETRNano(device="cpu", pretrain_weights="vigent-core/weights/ppe_rfdetr_v1.pth", resolution=384)\nm.export(output_dir="vigent-core/weights", format="onnx", opset_version=17, notes=json.dumps({...}))\n``` (전체는 `benchmarks/onnx_cpu_bench.md` §재현 방법) — 출력 파일명이 `rfdetr-nano.onnx` 고정이라 수동으로 `ppe_rfdetr_v1.onnx`로 rename 필요 |
| opset | 17 |
| 변환 시 패키지 버전 | rfdetr 1.8.0 · onnx 1.22.0 · onnxruntime 1.27.0 · torch 2.12.0+cu130(export 자체는 CPU로 실행, GPU 무관) |
| 클래스 이름 | ONNX 메타데이터 `rfdetr_notes`(JSON)에 `class_names` 포함 — 위 pth와 동일 10종. 런타임이 이 메타데이터를 읽어 클래스 매핑(torch 경로처럼 `model.class_names`에 의존하지 않음, ONNX 단독 로드 가능) |
| 입출력 shape | `input`(1,3,384,384) → `dets`(1,300,4, 정규화 cxcywh) · `labels`(1,300,11, raw logits — sigmoid+topk 후처리 필요, `rfdetr.models.postprocess.PostProcess` 재사용) |
| 정확도 검증 | `benchmarks/results/c2_onnx_cpu_bench.json`(dev 74장, torch와 완전 동일 결과) |
| 재변환 시 검증 | `benchmarks/c2_onnx_cpu_bench.py --backend onnx_fp32 --onnx-path vigent-core/weights/ppe_rfdetr_v1.onnx`로 dev 74장 재채점해 위 수치와 같은지 확인할 것 |

## [V2] 추가 ONNX export (2026-08-18) — 같은 가중치, 다른 실행기

`ppe_rfdetr_v1.onnx` 와 **같은 절차**로 나머지 슬롯을 변환했다. 가중치 교체가 아니라
**실행기만** 바꾼 것이다. `detect.backend: onnx-cpu` 일 때만 쓰이고, 기본값(`torch`)에서는
이 파일들이 전혀 로드되지 않는다.

★**원본 pth SHA256 을 ONNX 메타데이터(`rfdetr_notes.source_pth_sha256`) 안에도 심었다**
— 파일 하나만 있어도 출처를 추적할 수 있다.

| 슬롯 | 파일명 | 바이트 | SHA256 | 원본 pth | 원본 pth SHA256 | 동일성 검증 |
|---|---|---|---|---|---|---|
| **fire_smoke** | `fire_smoke_rfdetr_v1_e17.onnx` | 107,664,664 | `453e6798c22123701ea5898fb63768d81909b371d50332c0833398577f06246f` | `fire_smoke_rfdetr_v1_e17.pth` | `b7425ce450f12cad25cd821f616cd8e3f64d544de51d45bc6e0e6c833be6b4fb` | ✅ **PASS** |
| **forklift** | `forklift_rfdetr_v1.onnx` | 107,662,591 | `4812da8a62953c1cf27acfda05867209f3fdaaa4c2c67af51adabcd9ab9572b0` | `forklift_rfdetr_v1.pth` | `cd76eb56487bf1aa308a2da428e0348c8f6fbff0187007db77ec577d693373ac` | ❌ **부결** |
| person(측정 전용) | `person_rfdetr_coco_MEASURE_ONLY.onnx` | 107,846,251 | `74d7116ef4cb27928c9f65086cfde0c73cd5f108d1a9ffb663e93d86545beb96` | COCO 사전학습(rf-detr-nano) | (커스텀 아님) | 미실시 |

- 클래스: fire_smoke = `['smoke','fire']` · forklift = `['forklift']` · person = COCO 80종
- opset 17 · resolution 384 · 패키지: rfdetr 1.8.0 · onnx 1.22.0 · onnxruntime 1.27.0 · torch 2.12.0+cu130
- 변환 커맨드: `benchmarks/e1_bottleneck/v2_export.py`(재현 가능). ★`notes=` 로 `class_names` 를
  반드시 심어야 한다 — 없으면 `rfdetr_adapter.py:82` 가 로드를 거부하고 조용히 torch 로 폴백한다
  (첫 시도에서 실제로 발생).
- 검증 결과·판정 근거: `benchmarks/v2_onnx_report.md`

### ★person 은 현재 배선으로 ONNX 가 적용되지 않는다

`rfdetr_adapter.py:147` 이 `Path(weights).with_suffix(".onnx")` 로 경로를 만드는데,
person 슬롯은 `vision.yaml` 에 `rfdetr_weights.person` 항목이 없다(COCO 사전학습을 그대로
쓴다). 따라서 `weights` 가 비어 **onnx 경로 자체가 생성되지 않는다.**
위 `person_..._MEASURE_ONLY.onnx` 는 **측정 목적 전용**이며 서빙 경로에 배선돼 있지 않다.

## 그 외 vision.yaml 참조 가중치 (이 데스크탑엔 없음 — 확인되는 대로 채울 것)

| 파일명 | 슬롯 | 상태 |
|---|---|---|
| `forklift_rfdetr_v1.pth` | forklift(rfdetr) | ★[2026-08-18 정정] **이 환경에 있음** — 2026-08-17 Release 복원. SHA256 `cd76eb56487bf1aa308a2da428e0348c8f6fbff0187007db77ec577d693373ac`(120,781,691B) |
| `fire_smoke_rfdetr_v1_e17.pth` | fire_smoke(rfdetr) | ★[2026-08-18 정정] **이 환경에 있음** — 2026-08-17 Release 복원. SHA256 `b7425ce450f12cad25cd821f616cd8e3f64d544de51d45bc6e0e6c833be6b4fb`(120,807,675B) |
| `ppe_css_v1.pt` | ppe(yolo 폴백, 비활성 backend) | ★[2026-08-19] 검증 완료 — SHA `17a968ab…` 일치 |
| `forklift_boda_ax.pt` | forklift(yolo 폴백) | ★[2026-08-19] **검증 완료** — Release weights-v1 에서 조달, SHA256 `30579655ea0f…`(6,274,161B) 매니페스트 일치 |
| `fire_smoke_boda.pt` | fire_smoke(yolo 폴백) | ★[2026-08-19] 검증 완료 — SHA `95ecffe9…` 일치 |
| `yolo11m.pt` / `yolo11s.pt` | person(fallback) | 이 환경에 있음(`/health` 확인됨, SHA256 미기록 — 필요시 추가) |
| `yolov8n-pose.pt` | pose(레거시 이름, 실제 백엔드 RTMPose) | 미확인 |
| `rtm_cache/hub/checkpoints/yolox_m_8xb8-300e_humanart-c2c7a14a.onnx` | pose — RTMPose(rtmlib balanced) 사람 검출기, [M7-2b] fetch_weights 조달(required) | 2026-09-06 실측 101,400,344B sha 3dea6513… |
| `rtm_cache/hub/checkpoints/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx` | pose — RTMPose-m 자세 추정기, [M7-2b] fetch_weights 조달(required) | 2026-09-06 실측 54,330,655B sha 5c0a4bf6… |

## Release 전달 자산 (Mac→데스크탑 이관, git 미추적 → GitHub Releases)

> ★[2026-08-19] **Release 백업 완비** — `weights-v1` 에 매니페스트 10종 전부 업로드됐고,
> 이 데스크탑에서 `fetch_weights.py --all` 로 내려받아 **10/10 SHA256·크기 일치**를
> 재검증했다(독립 재계산). 맥 포맷 후에도 어느 PC 든 Release 만으로 전체 복원 가능하다.

자체학습 RF-DETR 가중치는 git에 올리지 않고 **Release `weights-v1`** 자산으로 전달한다.
데스크탑에서 `gh release download weights-v1 --pattern <파일> --dir weights/`(또는 브라우저 다운로드)로 받고,
SHA256이 아래와 일치하는지 확인할 것.

| 파일명 | 용도 | 바이트 크기 | SHA256 | 전달 |
|---|---|---|---|---|
| forklift_rfdetr_v1.pth | 지게차 검출 (RF-DETR 자체학습) | 120,781,691 | cd76eb56487bf1aa308a2da428e0348c8f6fbff0187007db77ec577d693373ac | Release weights-v1 |
| fire_smoke_rfdetr_v1_e17.pth | 화재/연기 검출 (RF-DETR 자체학습) | 120,807,675 | b7425ce450f12cad25cd821f616cd8e3f64d544de51d45bc6e0e6c833be6b4fb | Release weights-v1 |
