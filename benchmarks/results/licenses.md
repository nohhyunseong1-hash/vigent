# 의존성 라이선스 — T12-B 벤치마크 관련 (pip-licenses 실측)

> 측정: `/opt/anaconda3/bin/pip-licenses` · 2026-07-04. 규칙7: 실제 출력 그대로.

## 1) 벤치마크 직접/핵심 의존성
| Name             | Version   | License                                                 |
|------------------|-----------|---------------------------------------------------------|
| PyYAML           | 6.0.3     | MIT License                                             |
| numpy            | 2.4.6     | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0      |
| opencv-python    | 4.13.0.92 | Apache Software License                                 |
| pycocotools      | 2.0.11    | FreeBSD                                                 |
| torch            | 2.12.0    | BSD-3-Clause                                            |
| torchvision      | 0.27.0    | BSD                                                     |
| ultralytics      | 8.3.253   | GNU Affero General Public License v3 or later (AGPLv3+) |
| ultralytics-thop | 2.0.20    | GNU Affero General Public License v3 or later (AGPLv3+) |

## 1-b) RF-DETR 이관 스택 (T10a, person 검출)
| Name        | Version      | License                |
|-------------|--------------|------------------------|
| rfdetr      | 1.8.0        | Apache License 2.0     |
| supervision | 0.29.0.post0 | MIT License            |
| trackers    | (설치됨)      | Apache/MIT (permissive) |

## 2) copyleft 판정

- **T12-B 신규 도입분**(pycocotools·pip-licenses·prettytable·wcwidth): 전부 permissive(FreeBSD/MIT/BSD) → **AGPL/GPL 0건**.
- **T10a RF-DETR 스택**(rfdetr=Apache-2.0·supervision=MIT): permissive → person 검출 경로는 **copyleft 0**.
- **기존 의존성 중 copyleft(잔존)**: `ultralytics` / `ultralytics-thop` = **AGPLv3+**.
  - ⚠️ **T10a 후에도 ultralytics 는 라이브 경로에 남아 있다**(정직 표기, 규칙7): `detectors/yolo_adapter.py`(ppe·fire_smoke·forklift 검출) + `worker.py`(포즈=yolov8n-pose).
  - **person 검출만** RF-DETR 로 이관 완료 → guard.py 에서 `from ultralytics import YOLO` **직접 import 소멸**(어댑터로 격리).
  - **copyleft 0 달성 조건**: **T10b**(ppe/fire/forklift RF-DETR 모델 학습) + **T10c**(포즈 RTMPose) 완료 시. T10a 단독으로는 미달성(설계상 person-only 스코프).
- 아나콘다 base 환경의 기타 GPL/LGPL 패키지(PyQt5·pylint·rope 등)는 개발도구로 VIGENT 배포물과 무관.
