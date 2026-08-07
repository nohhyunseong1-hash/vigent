# 사전라벨 초안 생성 요약 (자체모델 RF-DETR person+ppe, conf=0.10 — 초안 전용, 정답 아님)

입력: `D:\vigent_original\data\field_eval\frames`(109장) · 출력: `D:\vigent_original\data\field_eval\labels_draft`(YOLO txt) + `D:\vigent_original\data\field_eval\labels_draft_preview`(미리보기 jpg)
검출 설정: detectors=['person', 'ppe'], conf=0.1(초안 전용), imgsz=640(실배포 동일)
PPE_PER_CLASS 확인: guard.PPE_PER_CLASS 비어있음(기본) — conf=0.10 이 전 클래스에 그대로 적용됨.

## 🔴 차단 이슈 — PPE 클래스 박스가 0개(전 109장)
이 실행 환경(desktop)에는 PPE 파인튜닝 가중치(`ppe_rfdetr_v1.pth`/`ppe_css_v1.pt`)가 없다(`/health`의 `rfdetr_slots`에서 `ppe: MISSING_FALLBACK` 확인됨, 이전 세션들에서 이미 문서화된 환경 한계). `VIGENT_ALLOW_FALLBACK=1`이 이 슬롯을 **COCO 사전학습 모델로 대체**하는데, COCO엔 애초에 Hardhat/Safety-Vest/Mask 같은 클래스가 없어 **PPE 검출이 구조적으로 0건**이다.

실제로 이 실행에서 'ppe' 슬롯은 COCO 80종(의자·TV·병·가방 등)을 대신 검출했다(diagnostics: 1123건, 클래스 예시: ['bottle', 'sports ball', 'boat', 'bench', 'baseball bat', 'chair', 'truck', 'surfboard']...) — 이 값들은 라벨 파일·미리보기에 **안 들어갔다**(우리 7종 스킴 밖이라 자동 제외, 코드로 필터링됨).

**PPE 사전라벨(초안)은 이 환경에서 생성 불가능하다.** person 사전라벨(아래)은 정상 생성됐다 — person 슬롯은 파인튜닝 없이 COCO 기반 모델을 그대로 쓰는 설계라 이 한계의 영향을 안 받는다.

**진행 옵션(사용자 결정 필요)**: ① 실제 PPE 가중치 파일을 이 데스크탑 `vigent-core/weights/`로 복사 후 재실행 ② PPE 가중치가 있는 맥에서 이 스크립트 재실행 ③ 지금은 person만 검수 대상으로 진행하고 PPE는 나중으로 미룸.

## 전체 요약
- 총 초안 박스 수: **415개** (109장 평균 3.8개/장)
- 박스 0개 프레임: **5장**

## 클래스별 총계
| 클래스 | 박스 수 |
|---|---|
| person | 415 |
| Hardhat | 0 |
| NO-Hardhat | 0 |
| Safety-Vest | 0 |
| NO-Safety-Vest | 0 |
| Mask | 0 |
| NO-Mask | 0 |

⚠️ 우리 7종 스킴 밖 라벨 발견(라벨 파일엔 안 씀, 확인 필요): {'bottle': 49, 'sports ball': 9, 'boat': 47, 'bench': 45, 'baseball bat': 9, 'chair': 178, 'truck': 67, 'surfboard': 8, 'bowl': 5, 'knife': 14, 'dog': 36, 'toothbrush': 7, 'bird': 10, 'scissors': 12, 'cup': 17, 'umbrella': 9, 'kite': 4, 'cell phone': 28, 'bus': 10, 'baseball glove': 3, 'handbag': 15, 'backpack': 13, 'train': 33, 'sheep': 3, 'horse': 5, 'cow': 3, 'suitcase': 82, 'car': 30, 'skis': 5, 'snowboard': 3, 'banana': 2, 'elephant': 6, 'airplane': 26, 'toilet': 8, 'refrigerator': 31, 'oven': 28, 'bed': 27, 'sink': 7, 'couch': 11, 'dining table': 12, 'vase': 4, 'tie': 1, 'skateboard': 3, 'bear': 2, 'parking meter': 1, 'toaster': 1, 'stop sign': 2, 'microwave': 6, 'tv': 108, 'bicycle': 1, 'keyboard': 12, 'book': 3, 'laptop': 4, 'giraffe': 4, 'clock': 7, 'remote': 2, 'mouse': 3, 'teddy bear': 17, 'spoon': 4, 'cat': 14, 'cake': 3, 'donut': 1, 'hair drier': 1, 'traffic light': 2}

## 박스 0개 프레임 목록(검수 체크리스트 ④의 1차 후보 — 사람 없음 13장과 대조할 것)

- KakaoTalk_20260807_000601541_8000ms.jpg
- KakaoTalk_20260807_000611749_10000ms.jpg
- KakaoTalk_20260807_000633827_5000ms.jpg
- KakaoTalk_20260807_000721865_23000ms.jpg
- KakaoTalk_20260807_000721865_26000ms.jpg

## 프레임별 박스 수(전체)

| 파일 | 박스 수 |
|---|---|
| KakaoTalk_20260807_000438282_0ms.jpg | 6 |
| KakaoTalk_20260807_000438282_10000ms.jpg | 3 |
| KakaoTalk_20260807_000438282_1000ms.jpg | 7 |
| KakaoTalk_20260807_000438282_11000ms.jpg | 5 |
| KakaoTalk_20260807_000438282_12000ms.jpg | 3 |
| KakaoTalk_20260807_000438282_13000ms.jpg | 1 |
| KakaoTalk_20260807_000438282_14000ms.jpg | 3 |
| KakaoTalk_20260807_000438282_15000ms.jpg | 1 |
| KakaoTalk_20260807_000438282_16000ms.jpg | 2 |
| KakaoTalk_20260807_000438282_17000ms.jpg | 2 |
| KakaoTalk_20260807_000438282_18000ms.jpg | 2 |
| KakaoTalk_20260807_000438282_19000ms.jpg | 8 |
| KakaoTalk_20260807_000438282_20000ms.jpg | 1 |
| KakaoTalk_20260807_000438282_2000ms.jpg | 4 |
| KakaoTalk_20260807_000438282_3000ms.jpg | 4 |
| KakaoTalk_20260807_000438282_4000ms.jpg | 5 |
| KakaoTalk_20260807_000438282_5000ms.jpg | 5 |
| KakaoTalk_20260807_000438282_6000ms.jpg | 2 |
| KakaoTalk_20260807_000438282_7000ms.jpg | 4 |
| KakaoTalk_20260807_000438282_8000ms.jpg | 2 |
| KakaoTalk_20260807_000438282_9000ms.jpg | 1 |
| KakaoTalk_20260807_000442974_0ms.jpg | 3 |
| KakaoTalk_20260807_000442974_10000ms.jpg | 1 |
| KakaoTalk_20260807_000442974_1000ms.jpg | 1 |
| KakaoTalk_20260807_000442974_12000ms.jpg | 2 |
| KakaoTalk_20260807_000442974_13000ms.jpg | 6 |
| KakaoTalk_20260807_000442974_14000ms.jpg | 3 |
| KakaoTalk_20260807_000442974_15000ms.jpg | 4 |
| KakaoTalk_20260807_000442974_16000ms.jpg | 5 |
| KakaoTalk_20260807_000442974_3000ms.jpg | 6 |
| KakaoTalk_20260807_000442974_6000ms.jpg | 2 |
| KakaoTalk_20260807_000552920_0ms.jpg | 5 |
| KakaoTalk_20260807_000552920_10000ms.jpg | 4 |
| KakaoTalk_20260807_000552920_1000ms.jpg | 3 |
| KakaoTalk_20260807_000552920_11000ms.jpg | 3 |
| KakaoTalk_20260807_000552920_12000ms.jpg | 2 |
| KakaoTalk_20260807_000552920_13000ms.jpg | 3 |
| KakaoTalk_20260807_000552920_14000ms.jpg | 5 |
| KakaoTalk_20260807_000552920_16000ms.jpg | 9 |
| KakaoTalk_20260807_000552920_17000ms.jpg | 5 |
| KakaoTalk_20260807_000552920_19000ms.jpg | 7 |
| KakaoTalk_20260807_000552920_2000ms.jpg | 3 |
| KakaoTalk_20260807_000552920_3000ms.jpg | 1 |
| KakaoTalk_20260807_000552920_4000ms.jpg | 1 |
| KakaoTalk_20260807_000552920_5000ms.jpg | 5 |
| KakaoTalk_20260807_000552920_6000ms.jpg | 10 |
| KakaoTalk_20260807_000552920_7000ms.jpg | 3 |
| KakaoTalk_20260807_000552920_8000ms.jpg | 8 |
| KakaoTalk_20260807_000552920_9000ms.jpg | 12 |
| KakaoTalk_20260807_000601541_0ms.jpg | 2 |
| KakaoTalk_20260807_000601541_1000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_2000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_3000ms.jpg | 2 |
| KakaoTalk_20260807_000601541_4000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_5000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_6000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_7000ms.jpg | 1 |
| KakaoTalk_20260807_000601541_8000ms.jpg | 0 |
| KakaoTalk_20260807_000611749_0ms.jpg | 5 |
| KakaoTalk_20260807_000611749_10000ms.jpg | 0 |
| KakaoTalk_20260807_000611749_1000ms.jpg | 3 |
| KakaoTalk_20260807_000611749_11000ms.jpg | 11 |
| KakaoTalk_20260807_000611749_12000ms.jpg | 8 |
| KakaoTalk_20260807_000611749_13000ms.jpg | 9 |
| KakaoTalk_20260807_000611749_14000ms.jpg | 7 |
| KakaoTalk_20260807_000611749_15000ms.jpg | 8 |
| KakaoTalk_20260807_000611749_3000ms.jpg | 1 |
| KakaoTalk_20260807_000611749_4000ms.jpg | 2 |
| KakaoTalk_20260807_000611749_5000ms.jpg | 2 |
| KakaoTalk_20260807_000611749_8000ms.jpg | 4 |
| KakaoTalk_20260807_000632301_0ms.jpg | 3 |
| KakaoTalk_20260807_000632301_1000ms.jpg | 2 |
| KakaoTalk_20260807_000632301_2000ms.jpg | 4 |
| KakaoTalk_20260807_000632301_3000ms.jpg | 1 |
| KakaoTalk_20260807_000632301_4000ms.jpg | 1 |
| KakaoTalk_20260807_000632301_5000ms.jpg | 1 |
| KakaoTalk_20260807_000632301_6000ms.jpg | 1 |
| KakaoTalk_20260807_000632301_8000ms.jpg | 1 |
| KakaoTalk_20260807_000633827_0ms.jpg | 14 |
| KakaoTalk_20260807_000633827_10000ms.jpg | 3 |
| KakaoTalk_20260807_000633827_1000ms.jpg | 6 |
| KakaoTalk_20260807_000633827_11000ms.jpg | 11 |
| KakaoTalk_20260807_000633827_12000ms.jpg | 12 |
| KakaoTalk_20260807_000633827_13000ms.jpg | 9 |
| KakaoTalk_20260807_000633827_2000ms.jpg | 11 |
| KakaoTalk_20260807_000633827_3000ms.jpg | 3 |
| KakaoTalk_20260807_000633827_4000ms.jpg | 6 |
| KakaoTalk_20260807_000633827_5000ms.jpg | 0 |
| KakaoTalk_20260807_000633827_6000ms.jpg | 1 |
| KakaoTalk_20260807_000633827_7000ms.jpg | 1 |
| KakaoTalk_20260807_000633827_8000ms.jpg | 1 |
| KakaoTalk_20260807_000633827_9000ms.jpg | 15 |
| KakaoTalk_20260807_000658251_0ms.jpg | 1 |
| KakaoTalk_20260807_000658251_1000ms.jpg | 5 |
| KakaoTalk_20260807_000658251_2000ms.jpg | 6 |
| KakaoTalk_20260807_000658251_3000ms.jpg | 7 |
| KakaoTalk_20260807_000658251_5000ms.jpg | 3 |
| KakaoTalk_20260807_000658251_6000ms.jpg | 2 |
| KakaoTalk_20260807_000658251_7000ms.jpg | 2 |
| KakaoTalk_20260807_000658251_8000ms.jpg | 4 |
| KakaoTalk_20260807_000658251_9000ms.jpg | 3 |
| KakaoTalk_20260807_000721865_0ms.jpg | 1 |
| KakaoTalk_20260807_000721865_11000ms.jpg | 3 |
| KakaoTalk_20260807_000721865_13000ms.jpg | 1 |
| KakaoTalk_20260807_000721865_16000ms.jpg | 2 |
| KakaoTalk_20260807_000721865_23000ms.jpg | 0 |
| KakaoTalk_20260807_000721865_25000ms.jpg | 4 |
| KakaoTalk_20260807_000721865_26000ms.jpg | 0 |
| KakaoTalk_20260807_000721865_5000ms.jpg | 1 |