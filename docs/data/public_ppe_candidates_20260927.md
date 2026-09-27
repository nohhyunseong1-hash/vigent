# 공개 PPE 데이터 후보 검증 — SHWD + Roboflow Universe 10종 (2026-09-27)

> **첫 줄 결론: 통과 0건 → "보조 후보" 없음.** 판정 기준(상업 사용 가능 라이선스 **+** 감시 시점 비율 ≥50% **+** 사람 박스 p50 ≤0.5 **+** 착용/미착용 둘 다 라벨)을 모두 만족하는 공개 데이터셋은 이번 조사 범위(SHWD 1 + Roboflow 10 + 기준선 CSS)에 **없다.** 결정적 탈락 사유는 전부 같다 — **감시 시점 비율이 최고 17%(대부분 0%)**. 공개 PPE 데이터는 웹 스톡·뉴스·연출 사진이지 고정 CCTV 가 아니다. 우리 학습셋 CSS 도 같은 결과(0/30)다.
> → AI Hub 163 판정(1인칭 액션캠, 부적합)과 합쳐 **공개 데이터로 CCTV 도메인 PPE 를 채우는 경로는 종결**. 다음은 재방문 현장 GT.
>
> 수치 꼬리표: [실측] 파일로 잰 것(라벨 전수·표본 박스 비율·해상도) · [육안] 격자 사진을 보고 센 것(장수 명시) · [문서상 주장] 저장소/페이지 표기 · [추정]. 표본은 seed 0 무작위, SHWD 200장·Roboflow 각 30장·CSS held-out 30장. 원자료: `D:\vigent_private_data\public_ppe\{shwd,roboflow}\*.zip`(총 3.4 GB) · `audit/public_ppe/<이름>/_summary_*.json` · 격자 `_contact_*.jpg`(**얼굴 포함 → 미추적·커밋 금지**). 코드: `scripts/data/{roboflow_probe,public_ds_size,public_ds_fetch,public_ds_sample}.py`.

---

## 1. 판정 기준과 측정 방법

| 기준 | 측정 |
|---|---|
| 상업 사용 가능 라이선스 | 저장소 LICENSE / Roboflow API `project.license` [문서상 주장] + **이미지 출처 실체**(웹 수집·스톡 워터마크·연구용 전용 셋 포함 여부) [실측/육안] |
| 감시 시점 비율 ≥50% | 표본 격자를 보고 **고정 감시카메라 / 근접(스톡·연출·1인칭) / 기타(뉴스·군중·무관 도메인)** 로 분류 [육안]. SHWD 는 파일명 접두(PartA=SCUT 교실 CCTV)로 **실측** 보강 |
| 사람 p50 ≤0.5 | 표본의 사람(전신) 박스 높이 / 이미지 높이 중앙값 [실측]. 사람 클래스가 없으면 **평가 불가**로 두고 머리·안전모 비율을 참고로 적는다 |
| 착용/미착용 둘 다 라벨 | 클래스 목록 [실측 전수 박스 수] |

기준선 **CSS v27 held-out 91**(우리 v1 학습셋): Person p50 **0.355**(p10 0.075·p90 0.797) · Hardhat 0.056 · NO-Hardhat 0.050 · 감시 시점 **0/30 [육안]**(웹·연출 사진, 사다리 연출 컷 포함).

## 2. SHWD (Safety Helmet Wearing Dataset, njvisionpower) — **제외**

| 항목 | 값 |
|---|---|
| 라이선스 | GitHub API `license.spdx_id = MIT` [문서상 주장]. README 에는 라이선스 문장 없음 |
| 이미지 출처 | README 원문: "The positive objects got from goolge or baidu, and we manually labeld with LabelImg. Some of negative objects got from SCUT-HEAD" → **웹 수집 + SCUT-HEAD 재배포**. SCUT-HEAD README 원문: "free to the academic community **for research purpose usage only**" |
| 구성 [실측 전수 7,581장] | helmet 웹(part2/숫자) **3,241장**(hat 9,044 박스 전부 여기) · SCUT PartA(교실 CCTV) **1,999장**(hat 0) · SCUT PartB(웹 군중) **2,341장**(hat 0) |
| 표본 200 시점 | PartA 교실 고정 CCTV **48**(24%) · helmet 웹 근접 89 · PartB 웹 군중 63 [파일명 실측 + 격자 육안 일치]. **안전모가 있는 감시 프레임 0장** — 감시 프레임은 전부 교실(안전모 없음) |
| 박스 비율 [실측 표본] | hat p10·p50·p90 = 0.046·**0.213**·0.514(근접) · person(=머리) 0.027·0.043·0.121. 사람 전신 클래스 **없음** |
| 해상도 | 제각각(198×300 ~ 5281×3521), 웹 수집 특성 |

**판정: 제외** — (a) MIT 는 주석에만 해당하고 이미지는 웹 수집 + 연구전용 SCUT-HEAD 포함 → 상업 사용 불안전 (b) 안전모 프레임의 감시 시점 0% (c) 사람 클래스 없음.

## 3. Roboflow Universe 후보 10종 — 전부 제외

라이선스·클래스·장수는 API 메타 [실측 2026-09-27]. 시점은 표본 30장 [육안]. 비율은 표본 박스 [실측].

| # | 프로젝트 | 라이선스(표기) | 이미지 | 착용/미착용 클래스 | 감시 시점 /30 | 사람 p50 | 안전모·머리 p50 | 출처 실체 [육안] | 제외 사유 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ppe-kit-detection/**hardhat-safetyvest** | CC BY 4.0 | 22,068 | head 124k / helmet 57k / vest 8k(no-vest 없음) | **4**(전부 SCUT 교실, 안전모 0) | 없음 | helmet 0.094 / head 0.044 | 파일명이 SHWD(bPartA/bPartB/bpart2)+hard_hat_workers+safety_vests 의 **재집계본** → SCUT 연구전용 포함 | 감시 13%·라이선스 실체 불일치·사람 없음 |
| 2 | joseph-nelson/**hard-hat-workers** (v10) | Public Domain | 7,035 | helmet 19.7k / head 6.7k / person 615 | **0** | 표본에 person 0 | helmet 0.087 / head 0.163 | 중국 뉴스·스톡(xinhuanet·dreamstime 워터마크) | 감시 0%·"Public Domain" 표기와 출처 불일치 |
| 3 | ppe-tm7re/**no-hard-hat** | Public Domain | 349 | hat 418 / no hat 570 / vest 245 / no vest 731 | **4** | 없음 | hat 0.107 / no hat 0.145 | pond5 워터마크 스톡 + 소량 통로 카메라 | 감시 13%·349장·사람 없음 |
| 4 | v2-wo7jr/**ppe-construction-detection** (v16) | CC BY 4.0 | 2,926 | helmet 5.7k / no_helmet 1.1k / vest 3.0k / no_vest 3.4k / person 6.6k | **5**(야간 현장 카메라·타임스탬프 프레임) | **0.652**(p10 0.32·p90 0.92) | helmet 0.114 / no_helmet 0.036 | 스톡·연출 + 현장 카메라 소량 | 감시 17%·사람 p50 > 0.5 |
| 5 | tutorial-tivgz/**helmet-detection-v3** | CC BY 4.0 | 2,692 | CSS 10클래스 동일 | **0** | (모자이크) | — | **CSS 의 모자이크 증강 사본**(파일명 construction-*/youtube-* 동일) | CSS 중복·증강본 |
| 6 | trialforobjectdetection/**ppe-v1.1** | CC BY 4.0 | 549 | helmet 1.6k / no_helmet 739(+장갑·고글·신발) | **0** | 없음 | helmet 0.113 / no_helmet 0.049 | hard_hat_workers 파일명 + 좌우반전 증강 | 감시 0%·#2 파생 |
| 7 | hemet-annotations/**helmet-detection-0xjjk** | CC BY 4.0 | 502 | helmet 1.5k / no-helmet 477 | **0** | 없음 | helmet 0.041 / no-helmet 0.052 | **오토바이 헬멧, 인도 도로 대시캠** | 도메인 불일치 |
| 8 | latest-version/**new-ppe** | CC BY 4.0 | 427 | Helmet 221 / No Helmet 207 / 보호복 263 / 없음 165 | **0** | 없음 | Helmet 0.252 | 한 거리에서 같은 인물 연출, 416² 증강 | 감시 0%·연출 |
| 9 | roboflow-universe-projects/**safety-vests** (v7) | CC BY 4.0 | 3,897 | vest 6.4k / no-vest 2.0k (안전모 없음) | **2** | 없음 | vest 0.231 / no-vest 0.257 | 스톡·연출·뉴스 | 감시 7%·안전모 없음·사람 없음 |
| 10 | new-ja4hn/**ppe-detection-q897z** | **MIT** | 1,366 | helmet 2.0k / no-helmet 980 / vest / no-vest | 미검증 | — | — | **버전 0 → export 불가**(API `versions=0`) | 표본 수신 불가 |
| 참고 | roboflow-universe-projects/**construction-site-safety** v27 (CSS, 우리 학습셋) | CC BY 4.0 | 717 원본(export 2,603) | 4클래스 + Person | **0** | 0.355 | 0.056 / 0.050 | 웹·YouTube·연출 | (기준선) |

메타만 보고 다운로드 없이 제외한 것: ppe-pnqgr/hard-hat-universe(Safety Helmet·Vest 만, 미착용 없음) · safety-helmet-and-vest(미착용 없음) · no-helmet/construction-helmet(미착용 없음) · 007-kd2zw(CSS 사본, 박스 0) · siabar(미착용 없음) · echo-dotf3/safety-vests(#9 와 동일 3,897장) · helmet-detection-xy5ky(오토바이) · ppe-wqipw(클래스명 숫자, 정의 불명) · universe-datasets/hard-hat-universe(#2 와 동일 7,035장) · work-safe-project(404).

## 4. 사람·머리 박스 크기 나란히 [실측, 이미지 높이 대비]

| 집합 | 사람(전신) p10·**p50**·p90 | 안전모(착용) p50 | 미착용(머리) p50 |
|---|---|---|---|
| CSS held-out 91 (기준) | 0.075·**0.355**·0.797 | 0.056 | 0.050 |
| ppe-construction-detection (#4) | 0.324·**0.652**·0.921 | 0.114 | 0.036 |
| SHWD 200 | 없음 | 0.213 (hat) | 0.043 (person=머리) |
| hardhat-safetyvest (#1) | 없음 | 0.094 | 0.044 |
| hard-hat-workers (#2) | 표본 0 | 0.087 | 0.163 |
| no-hard-hat (#3) | 없음 | 0.107 | 0.145 |
| (참고) 현장 CCTV 학원 | 작업자 26~64 px @720p ≈ 0.04~0.09 | — | — |

CSS 보다 사람이 큰(가까운) 것뿐이고, 현장(0.04~0.09)에 가까운 집합은 없다.

## 5. 결론·다음

- **보조 후보 0건.** 상업 사용 가능 표기가 있어도 이미지 출처가 웹 스톡·뉴스·연구전용(SCUT-HEAD) 인 경우가 많아 표기 자체도 믿기 어렵다(#1·#2 는 표기와 실체 불일치).
- 감시 시점 비율은 최고 17%(#4). 기준 50% 의 1/3.
- **공개 데이터(AI Hub 163·507·510, SHWD, Roboflow 10종)로 CCTV 도메인 PPE 를 채우는 경로는 종결.** PPE v1 유지. 다음 판정·보강은 **재방문 현장 GT** 로만.
- 표본 zip 3.4 GB 는 `D:\vigent_private_data\public_ppe\` 에 있다(재검증용, 학습 사용 없음). 격자 이미지는 `audit/public_ppe/`(얼굴 포함, 커밋 금지).
