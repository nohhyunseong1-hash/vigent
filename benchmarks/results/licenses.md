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

## 1-c) RTMPose 이관 스택 (T10c, 포즈) — pip-licenses 실측 2026-07-04
| Name         | Version  | License                          |
|--------------|----------|----------------------------------|
| rtmlib       | 0.0.15   | Apache-2.0 (번들 LICENSE 파일로 실증; PyPI 메타 공란) |
| onnxruntime  | 1.27.0   | MIT License                      |
| flatbuffers  | 25.12.19 | Apache Software License          |
| protobuf     | 5.29.3   | 3-Clause BSD                     |
| sympy        | 1.14.0   | BSD License                      |
| mpmath       | 1.3.0    | BSD License                      |
| coloredlogs / humanfriendly | (onnxruntime 의존) | MIT (upstream) |
- tqdm(MPL-2.0 AND MIT)은 **T10c 신규 아님**(2026-06-01 기설치). MPL-2.0은 파일단위 약카피레프트.
- → **T10c 신규 트리 강한 카피레프트(GPL/AGPL) 0건.**

## 2) copyleft 판정

- **T12-B 신규 도입분**(pycocotools·pip-licenses·prettytable·wcwidth): 전부 permissive(FreeBSD/MIT/BSD) → **AGPL/GPL 0건**.
- **T10a RF-DETR 스택**(rfdetr=Apache-2.0·supervision=MIT): permissive → person 검출 경로는 **copyleft 0**.
- **기존 의존성 중 copyleft(잔존)**: `ultralytics` / `ultralytics-thop` = **AGPLv3+**.
  - ⚠️ **T10a+T10c 후에도 ultralytics 는 라이브 경로에 남아 있다**(정직 표기, 규칙7): **`detectors/yolo_adapter.py` 한 곳뿐**(ppe·fire_smoke·forklift 검출).
  - 이관 완료: **person 검출**(T10a, guard.py `from ultralytics import YOLO` 소멸) + **포즈**(T10c, `worker.py` `from ultralytics import YOLO` 소멸 → RTMPose).
  - **copyleft 0 달성 조건**: 남은 **T10b**(ppe/fire/forklift RF-DETR 모델 학습·이관) 완료 시. person·포즈는 이관 끝, 검출 3종만 잔존.
- 아나콘다 base 환경의 기타 GPL/LGPL 패키지(PyQt5·pylint·rope 등)는 개발도구로 VIGENT 배포물과 무관.
