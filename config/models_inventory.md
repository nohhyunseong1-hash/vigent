# VIGENT 모델 인벤토리 (AX안전 능력 패리티)

> VIGENT = AX안전(BODA) 업그레이드 버전. AX안전의 학습된 모델을 복사해 능력을 그대로 물려받음.
> 가중치 .pt 는 .gitignore 로 git 제외(디스크에만 존재) → 이 문서가 복사 이력·인벤토리 정본.
> AX 원본(`~/Desktop/사업계획서/AX안전`)은 읽기 전용. 복사만 함.

## 보유 모델 (vigent-core/weights/)

### 1단계에서 복사한 것
| 파일 | 클래스 | 용도 |
|---|---|---|
| `ppe_construction_v30.pt` | 25 (Hardhat/NO-Hardhat/Safety Vest/NO-Safety Vest/차량 등) | PPE 주력 |
| `forklift_boda_ax.pt` | 2 (Forklift, Load) | 지게차 |
| `fire_detector.pt` | 1 (fire) | 화재(연기 없음 — 하위호환, fire_smoke_boda 로 대체 예정) |
| `yolo11s.pt` | 80 (COCO) | 사람·일반객체 |
| `yolov8s.pt`, `yolov8n-pose.pt`, `yolov8s-seg.pt` | - | 폴백/포즈/세그 |

### 능력 패리티용 추가 복사 (2026-06-19)
| 파일 | 클래스 | AX 원본 경로 |
|---|---|---|
| `fire_smoke_boda.pt` | 3: **Fire, default, smoke** | runs/detect/fire_boda_ax/weights/best.pt |
| `fire_smoke_hf.pt` | 2: **smoke, fire** (연기 백업) | models/fire_smoke_hf.pt |
| `openimages_objects.pt` | 17: person·**goggles**·glove·ladder·chair·laptop·keyboard·mouse·mobile_phone·bottle·cup·backpack·snack·**knife**·**scissors** 등 | runs/detect/runs/train/ax_openimages_smoke/weights/best.pt |
| `ppe_construction_ax.pt` | 11: helmet·gloves·vest·boots·**goggles**·none·Person·no_helmet·no_goggle·no_gloves·no_boots | runs/detect/ppe_construction_ax/weights/best.pt |

→ 추가 복사로 **연기(smoke)·고글(goggles)·사다리·칼·가위·boots** 등 탐지 능력 회복.
→ 전부 ultralytics 8.3.253 에서 실제 로드 성공 검증 완료.

### 복사 제외 (중복 — 상위 모델에 포함)
- `safety_ppe_helmet_local_smoke` (person+helmet 2클래스)
- `ppe_helmet_candidate` (person+helmet 2클래스)

## 다음 단계 (이번 단계 범위 밖)
- vision.yaml 에 새 검출기 등록(fire_smoke 를 fire_smoke_boda 로 교체, openimages·ppe_ax 추가)
- 프론트가 모든 검출기 호출 + 박스·경보 표시
- 판단 규칙에 연기·화재 등 안전 이벤트 추가(Analyst·Dispatcher)
- 여러 모델 간 중복 탐지 정리(주력 모델 선정)
