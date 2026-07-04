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

## 2) copyleft 판정

- **T12-B 신규 도입분**(pycocotools·pip-licenses·prettytable·wcwidth): 전부 permissive(FreeBSD/MIT/BSD) → **AGPL/GPL 0건**.
- **기존 의존성 중 copyleft**: `ultralytics` / `ultralytics-thop` = **AGPLv3+**. YOLO 런타임(기존·CLAUDE.md §6에 명시된 알려진 이슈). T12-B가 새로 도입한 것이 아님.
- 아나콘다 base 환경의 기타 GPL/LGPL 패키지(PyQt5·pylint·rope 등)는 개발도구로 VIGENT 배포물과 무관.
