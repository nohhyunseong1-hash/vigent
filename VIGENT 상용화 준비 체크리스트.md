# VIGENT 상용화 준비 체크리스트

> 상태: **측정·준비 단계** (2026-07-02 결정). 지금은 코드를 바꾸지 않는다.
> AGPL 등 차단요소는 **실제 유료 배포(고객 온프렘 납품 또는 SaaS 제공) 직전**에 해소한다.
> 파일럿·데모·내부 평가 단계에서는 현재 구성 그대로 진행 가능하다.
>
> 아래 내용은 **파일로 검증한 사실만** 기록한다. 추정은 "미검증"으로 표시한다.

---

## 1. AGPL 라이선스 (최우선 관문) — ✅ 해소 (2026-07-07, T10b + A-4)

**결론: 라이브 배포 경로 강카피레프트(AGPL) 0 달성. 방향 A(Apache 모델 이관)로 완결.** 마일스톤 태그 `v1.0-copyleft-zero`.

### 해소 내역 (T10 이관 완료 — 저하 0, 오히려 개선)
- 검출 4슬롯 + 포즈 전부 **permissive 백엔드로 이관**(각 게이트 통과·회귀 Δ0.00):
  - 사람 → RF-DETR(Apache, T10a) — pipeline mAP@50 70.95→**92.94%**
  - 포즈 → RTMPose(rtmlib/onnx, Apache, T10c)
  - 지게차 → RF-DETR(Apache, LOCO, T10b) — box mAP 개선(운용점 튜닝 잔존, F-7)
  - **화재·연기 → RF-DETR(Apache, D-Fire, T10b)** — presence recall fire 53.6→**95.9**/smoke 24.9→**87.9**
  - **PPE → RF-DETR(Apache, css_safety, T10b)** — pipeline mAP@50 58.6→**71.5%**
- **A-4**: ultralytics(AGPL) 를 배포 `requirements.txt` 에서 제거 → 측정 전용(`requirements-eval.txt`)으로만 잔존.
- **런타임 실증**: 테마 빌드 + 전 슬롯 `guard.detect` + 포즈 실행 후 `sys.modules` 에 ultralytics 부재(PASS).
- `detectors/yolo_adapter.py` 는 **롤백 안전망**으로 존치(지연 import·배포 미포함 → copyleft 0 유지).

### ⚠️ 잔여 유의 (경미)
- **in-domain 한계**: 이관된 RF-DETR 4종은 학습셋과 동일 출처로 평가(D-Fire/css_safety/LOCO). 정당한 홀드아웃이나 **현장 영상 일반화는 별도 검증 대기(T10c-V)**. 상용 납품 전 현장 정확도 실측 필수(아래 §4 연계).
- 매니페스트 `yolov8n-pose.pt`(구 포즈 백엔드) legacy 항목 잔존 — 실제 백엔드는 RTMPose(런타임 무영향, 정리 백로그).
- ultralytics Enterprise 유료 라이선스(구 방향 B)는 **불필요해짐**(이관으로 해소).

### 구 기록 (해소 전, 2026-07-02) — 경위 보존
- 당시 걸리던 커스텀 YOLO 5종: yolo11m/s(사람)·ppe_css_v1·fire_smoke_boda·forklift_boda_ax·yolov8n-pose.
- 당시 노출 경로: 서버 정밀탐지 `/detect/frame` → Guard 의 커스텀 YOLO. 브라우저층(COCO-SSD·MediaPipe)은 원래부터 Apache.
- 당시 선택지: (B)ultralytics Enterprise 구매 / (A)Apache 모델 이관 / (C)혼합 → **최종 (A) 채택·완결.**

---

## 2. 기능안전 경계 (프레스·전단기 등)

- 비전 ML은 확률적이므로 **인증 안전기능을 대체할 수 없다.**
- 프레스/전단기 비상정지의 1차 책임은 인증 하드웨어(Type 4 광전자식 방호장치, 안전 PLC)에 있다.
- VIGENT는 **보조·감시 계층으로 신호만 제공**한다. → 이 문구를 **계약서·UI·영업자료에 명시**할 것.
- [ ] 영업/계약 문서에 기능안전 면책·경계 문구 삽입 확인.

---

## 3. 개인정보 · 영상감시

- 얼굴 인식/작업자 인식, office 테마의 근로자 영상은 **개인정보보호법·근로기준법상 동의·고지·노사협의 대상**.
- 기본값: **익명 집계 + 얼굴 블러 on**.
- [ ] 상용 배포 현장별로 동의·고지 절차 확보.
- [ ] 얼굴 블러 기본 on 상태 실측 확인.

---

## 4. 정확도 실측 (과장 금지)

- 상용 마케팅에 정확도 수치를 쓰려면 **측정 도구로 실제 잰 값만** 사용한다(지어내지 않는다).
- 자체 측정 화면 존재: `/safety/eval` (재현율·정밀도 측정).
- [ ] 판매 전 대표 시나리오별 정확도 실측 → 근거와 함께 기록.
- [ ] (미검증) KISA/공인 평가 기준 필요 여부는 타깃 고객·조달 요건 확인 후 결정.

---

## 5. 제품 분리 — E-1 (외부 상업화 감사 치명 항목)

**E-1 정의**(외부 감사): sports/office 라우트가 safety 코어(`main.py`)에 상시 로드, 테마 가드 없음 → **safety 배포에 타 제품 코드 동봉**. 해소 태스크 = C-SPRINT S3.

### 실측 상태 (2026-07-07) — **부분 해소**
- **S3-1 라우터 테마 가드: ✅ 완료.** `main.py` `_theme_gate` 미들웨어 + `VIGENT_THEMES`(기본 safety). `/office`·`/sports` 는 safety 배포에서 **404**(미노출) → **노출(exposure) 리스크 해소.**
- **S3-2 코어 분리: ❌ 미완.** `vigent-core/office_data.py`(118줄)·`sports_data.py`(78줄) 코어 물리 존재. `main.py` 에 /office 5개·/sports 6개 라우트 핸들러 잔존 → **코드 동봉(bundling)은 남음.** (facial/face_recognition 은 코어에 없음.)
- **S3-3 safety-only 기동 회귀: ❌ 미완.** `tests/` 에 safety-only 기동 검증 없음.

### 판정
**부분 해소** — 접근은 404 게이트로 차단(감사 '노출' 항목 완화), 단 **코드 동봉은 잔존**. clean safety-only 빌드/납품에는 **S3-2 필요.**
### 잔여 태스크
S3-2(코어 분리, 이동 목록 **승인 게이트**) + S3-3(safety-only 기동 회귀). 이동은 CLAUDE.md §1(기존 MVP 읽기전용)·파괴적작업 승인 규칙 준수.

---

## 요약 한 줄
> **§1 AGPL 해소 완료(2026-07-07, 태그 v1.0-copyleft-zero).** 남은 배포 직전 관문: §2 기능안전 문구·§3 개인정보 절차·§4 정확도 실측(이관 4종 **현장 재검증 T10c-V**)·**§5 E-1 제품분리 부분해소(S3-2/S3-3 잔여).** 첫 유료 배포 시 확인.
