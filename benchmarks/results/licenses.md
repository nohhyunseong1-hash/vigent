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

## 1-d) RF-DETR 학습 스택 (T10b, 신규 설치 2026-07-05) — 의존성 폐포 71개 감사
| Name (신규 설치) | Version | License | 용도 |
|---|---|---|---|
| pytorch-lightning | 2.6.5 | Apache-2.0 | 학습 루프 |
| torchmetrics | 1.9.0 | Apache-2.0 | 학습 지표 |
| lightning-utilities | 0.15.3 | Apache-2.0 | Lightning 유틸 |
| albumentations / albucore | 2.0.8 / 0.0.24 | MIT | 데이터 증강 |
| kornia / kornia-rs | 0.8.3 / 0.1.14 | Apache-2.0 | GPU 증강 |
| peft | 0.19.1 | Apache-2.0 | 백본(DINOv2) 로딩 |
| accelerate | 1.14.0 | Apache-2.0 | HF 학습 가속 |
| faster-coco-eval | 1.7.2 | Apache-2.0 | 학습 중 COCO eval |
| simsimd / stringzilla | 6.5.16 / 4.6.2 | Apache-2.0 | albumentations 의존 |
- **감사 범위**: rfdetr+pytorch_lightning+peft+albumentations+kornia+accelerate **의존성 폐포 71개** 실측(2026-07-05).
- **강카피레프트(AGPL/GPL/LGPL): 0건** ✓ — 학습 스택은 Apache/BSD/MIT/PSF 계열.
- 약카피레프트: **certifi(MPL-2.0)** — 파일단위·**학습 전용·배포물 아님** → 실질 리스크 없음. (tqdm은 MPL/MIT 듀얼, MIT로 사용)
- ⚠️ env 전체 스캔에서 잡힌 **ultralytics/ultralytics-thop(AGPL-3.0)**은 **학습 폐포 밖** = T10b가 제거 대상인 기존 런타임 YOLO(별개). 그 외 LGPL/GPL 항목은 아나콘다 base 개발도구(jupyter/conda/PyQt 등)로 VIGENT 런타임·학습 import 경로와 무관.
- → **T10b 학습 도구 도입으로 copyleft 재유입 없음.** AGPL 제거 목적 보존.

## 2) copyleft 판정

- **T12-B 신규 도입분**(pycocotools·pip-licenses·prettytable·wcwidth): 전부 permissive(FreeBSD/MIT/BSD) → **AGPL/GPL 0건**.
- **T10a RF-DETR 스택**(rfdetr=Apache-2.0·supervision=MIT): permissive → person 검출 경로는 **copyleft 0**.
- **✅ A-4 완료(T10b, 2026-07-07): 라이브 배포 경로 강카피레프트(AGPL) 0 달성.**
  - person(T10a)·포즈(T10c)·**ppe·fire_smoke·forklift(T10b)** 전부 RF-DETR/RTMPose 이관 완료 → guard 전 검출 슬롯 `backend=rfdetr`.
  - **런타임 실증**: safety 테마 빌드 + 전 슬롯 `guard.detect` + `worker` 포즈 실행 후 `sys.modules` 에 `ultralytics` **부재 확인**(지연 import 포함 실경로 커버). PROOF=PASS.
  - `ultralytics`/`ultralytics-thop`(AGPLv3+)은 **배포 requirements 에서 제거**(requirements.txt), YOLO baseline **측정 전용**으로만 잔존(requirements-eval.txt).
  - `detectors/yolo_adapter.py` 는 **롤백용으로 잔존**(backend=yolo 지연 import — 현재 미로드, AGPL 코드는 import 되지 않으면 배포 라이선스 의무 미발생). 제거 여부는 사용자 결정 대기.
- 아나콘다 base 환경의 기타 GPL/LGPL 패키지(PyQt5·pylint·rope 등)는 개발도구로 VIGENT 배포물과 무관.
