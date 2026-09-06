# 메타 프롬프트 — VIGENT: "Vision + AI Agent" 산업특화 플랫폼 구축

> ★[Z-3, 2026-08-10] **office(자세교정)·sports(요가) 테마는 영구 삭제됐다** — 제품 방향을
> 산업안전 CCTV 단일 라인으로 확정(낙상·LOTO 기능 제거와 동일한 판단). 아래 본문은 3테마
> 체제를 전제로 쓰인 원 설계 기록이라 office/sports를 언급하는 부분은 더 이상 유효하지
> 않다 — 삭제하지 않고 남겨두는 이유는 "왜 이런 구조였는지"의 역사적 맥락 보존을 위해서다.
> 현재 유효한 범위는 **safety 단일**이며, CLAUDE.md가 최신 사실관계의 기준이다.
>
> 회사 **VIGENT**. 하나의 컴퓨터비전·에이전트 코어를 공유하고, 산업 테마(safety / office / sports → 향후 smart-city / smart-farm)를 **선언적 `vision.yaml`** 로 분기한다.
> `«»` 는 시작 전에 채운다. 데이터·모델·로직은 새로 학습하지 말고 기존 MVP(`~/Desktop/사업계획서/AX안전`, 코드명 BODA)에서 **이식**한다. 없을 때만 자동 폴백.

---

## 0) 역할과 목표
너는 **풀스택 + 컴퓨터비전 + AI 에이전트** 엔지니어다. 실시간 영상에서 사람·사물·자세·행동을 인식하고, 에이전트가 **판단 → 보고서 작성 → 논문/규정 근거 검색 → 피드백·알림**까지 수행하는 산업특화 서비스 **VIGENT**를 구축한다.

- 인식은 딥러닝, 판단은 **규칙 + 딥러닝 하이브리드(가산식)**.
- **백엔드 코어 1개를 공유**, 프론트·에이전트 설정은 테마별로 분리.
- 1차 완성 테마: **safety**(기본). 이어서 office, sports.

---

## 1) 제품 / 회사 정의

**VIGENT = 산업특화 Vision + Agent 플랫폼.** 모든 테마가 동일한 5단계 파이프라인을 공유한다:

```
[감지] Vision  →  [판단] Agent  →  [보고서] Agent  →  [논문/근거 써치] Agent  →  [피드백·알림] Agent
```

| 테마 | 인식 대상 | 핵심 산출물 |
|---|---|---|
| **safety** (산업안전) | 작업자 수·PPE·위험구역 침입·부담자세·프레스/전단기 위험노출·화재/연기·중장비 근접 | 산안법 기반 위험성평가서, 증거 리포트, 경보·관리자 통보, (보조) 방호 신호 |
| **office** (자세교정) | 거북목·어깨 불균형·허리 굽힘·자리비움·착석시간 | 자세 점수, 교정·근무효율 피드백, 휴식 알림 |
| **sports** (요가·필라테스) | 개인 신체구조 기반 정적 자세 정확도·ROM·좌우대칭·호흡 | 실시간 음성 코칭, 개인별 습관/교정 PDF·모바일 리포트 |
| *(향후)* smart-city / smart-farm | 동선·이상행동 / 작물·가축·시설 상태 | 동일 5단계 루프 재사용 |

각 테마는 **독립 페이지**(`/safety`, `/office`, `/sports`)다. 통합 대시보드는 만들지 않는다.

---

## 2) 핵심 설계 원칙 (반드시 준수)
1. **절대 저하 없음 = 가산식 + 폴백.** 딥러닝 신호는 기존 규칙 점수에 *가산*만. 모델이 없거나 실패하면 규칙/휴리스틱으로 **자동 폴백**, 기능은 죽지 않는다.
2. **테마는 코드가 아니라 설정.** 신규 테마 = 새 `vision.yaml` + 프론트 테마 1개. 코어 로직은 수정하지 않는다.
3. **에이전트는 근거를 인용한다.** 위험성평가·피드백은 항상 출처(법령 조항·KOSHA 가이드·논문)를 함께 제시한다.
4. **즉시 인지 우선 UI.** 관제 콘솔 룩(모노스페이스, 검은 반투명 패널, HUD, 위험 시 빨강/주황).
5. **개인정보·기능안전 경계 준수**(§8). 얼굴 비식별화 토글 기본 제공. 비밀키는 코드/채팅 금지(env/파일).
6. **공유 JS는 null-guard.** 일부 DOM이 없는 테마 페이지에서도 깨지지 않게.

---

## 3) 에이전트 모델 — 6-에이전트 ↔ 5단계 루프

| 단계 | 에이전트 | 책임 | 핵심 출력 |
|---|---|---|---|
| 감지 | **Guard** | 실시간 탐지·추적·이벤트 발생 | 객체/포즈/구역 이벤트 스트림 |
| 판단 | **Analyst** | 규칙+딥러닝 가산 점수, 위험등급, 정량 평가 | severity, score, 위반 항목 |
| 보고서 | **Scribe** | 문서 생성(위험성평가서·증거 리포트·피드백 PDF) | PDF/웹 문서 |
| 논문/근거 써치 | **Copilot** | 법령·가이드·논문 RAG 검색, 근거·인용 제공 | citation 포함 근거 블록 |
| 피드백·연동 | **Dispatcher** | 알림(텔레그램/웹훅), 관리자 통보, 외부 장치 신호 | 경보, 통보, (보조)방호 신호 |
| (코칭 특화) | **Coach** | office/sports 실시간 교정·음성 코칭 | 음성/텍스트 피드백 |

> Copilot(논문 써치)은 신규 핵심 기능이다. §9 사양을 따른다.

---

## 4) 아키텍처

**공유 코어 + 테마 앱(하이브리드).**

```
vigent-core/         # 공유: 비전 파이프라인 + 에이전트 런타임 + vision.yaml 로더 + 폴백
themes/
  safety/  office/  sports/   # 각 테마 = vision.yaml + 프론트 + 에이전트 설정
```

**인식 파이프라인 — 4계층 융합:**
1. **검출/추적**: YOLO11(주 탐지) + ByteTrack. *폴백: BODA의 YOLOv8s.*
2. **시계열 행동인식**: RTMPose/Halpe 키포인트 → pyskl/mmaction2(반복동작). *폴백: 체류시간 규칙 + BODA TF 분류기.* (낙상 감지는 미구현 상태였고 폴백이던 몸통각 규칙도 2026-08 기능 제거 — `docs/P3_BACKLOG.md` PF)
3. **VLM 의미추론**: Qwen2.5-VL(MLX, Apple Silicon) — Set-of-Marks 프롬프팅 / crop-and-describe / 구조화 컨텍스트 주입. (선택: on-demand 정밀분석)
4. **LLM 오케스트레이션**: 에이전트 판단·보고서·피드백 생성.

**브라우저 측(저지연)**: MediaPipe Holistic + TF.js(coco-ssd 등) 실시간 오버레이. 정밀 보정은 백엔드 `/detect/frame` on-demand.

**판단**: 위험구역 폴리곤 ray-casting, 몸통 기울기, 체류시간, 근접거리 규칙 + 딥러닝 분류기 **가산**.

---

## 5) `vision.yaml` 선언적 바인딩 (테마의 핵심)

신규 테마는 이 파일만 작성하면 코어가 전 파이프라인을 구성한다. **safety 예시:**

```yaml
theme: safety
brand: VIGENT
display_name: "VIGENT Safety"

perception:                       # ── Guard (감지)
  detectors:
    - {id: person, model: yolo11s, fallback: yolov8s, classes: [person]}
    - {id: ppe,    model: weights/ppe_construction_v30.pt, fallback: heuristic,
       classes: [Hardhat, NO-Hardhat, Safety-Vest, NO-Safety-Vest]}
    - {id: fire_smoke, model: weights/fire_detector.pt, fallback: hsv_heuristic}
    - {id: forklift,   model: weights/forklift_boda_ax.pt, fallback: none}
  pose:    {model: rtmpose, fallback: [mediapipe_holistic, yolov8n-pose]}
  tracker: bytetrack
  temporal: {model: mmaction2_fall, fallback: torso_angle_rule}

judgment:                         # ── Analyst (판단), 가산식
  zones:
    danger_zones: config/zones/safety_zones.json
    intrusion: ray_casting
  rules:
    - {id: zone_intrusion, when: "person.center in danger_zone", severity: high}
    - {id: ppe_missing,    when: "NO-Hardhat or NO-Safety-Vest",  severity: medium}
    - {id: fall_suspected, when: "temporal.fall or torso_angle>60 for 1.5s", severity: high}
    - {id: guard_bypass,   when: "hand in machine_hazard_zone",    severity: critical}  # 프레스/전단기
  score: additive

report:                           # ── Scribe (보고서)
  templates: [risk_assessment_kr, incident_evidence]
  output: [pdf, web]

evidence:                         # ── Copilot (논문/근거 써치)
  corpus: [산업안전보건법, 산업안전보건기준에관한규칙, KOSHA_Guide]
  retrieval: rag
  cite: true

dispatch:                         # ── Dispatcher (피드백·연동)
  channels: [telegram, webhook]
  on_severity:
    critical: [alarm, manager_call, safety_relay_signal]   # ⚠ §8 경계 참조
    high:     [alarm, manager_call]
    medium:   [log]
```

**office / sports 델타(요약)** — 구조는 동일, 슬롯만 교체:
- `office`: detectors 생략, `pose=rtmpose`, rules에 `forward_head`(거북목 CVA 각도), `shoulder_imbalance`, `absence`(자리비움), `prolonged_sitting`. report=`posture_feedback`. dispatch=desktop notify. **coach: text**.
- `sports`: rules에 `pose_accuracy`(레퍼런스 자세 대비 관절각 편차, 개인 신체비율 정규화), `rom`, `lr_symmetry`, `breathing`. report=`student_feedback_pdf`. **coach: voice**(실시간 음성).

---

## 6) 기술 스택 + 라이선스 전략

**스택**: Python 3.11 · FastAPI · uvicorn · ultralytics(YOLO11/8) · ByteTrack · RTMPose · mmaction2/pyskl · Qwen2.5-VL(MLX) · TensorFlow 2.x(BODA 분류기) · OpenCV · numpy. 프론트: 순수 HTML/JS(번들러 없음), MediaPipe·TF.js는 CDN. 테스트: `python -m unittest discover -s tests`.

**⚠ 라이선스 (상용화 차단 요소 — 2단계 해소):**
- Ultralytics YOLO는 **AGPL-3.0**. 상용 비공개 배포 시 소스 공개 의무 발생.
- **1단계(PoC)**: Ultralytics **Enterprise License** 구매 **또는** 온프레미스 소스 공개 조건 충족 후 단기 검증.
- **2단계(상용)**: 완전 허용형(Apache/MIT 계열)으로 마이그레이션 — 검출 **RF-DETR**, 포즈 **RTMPose**. `vision.yaml`의 `model` 슬롯 교체만으로 전환 가능하도록 코어를 모델-불가지론적으로 설계.
- 데이터셋 라이선스(CC BY 등) 출처·표기 보존.

---

## 7) 테마별 상세 명세

### 7.1 safety (1차 완성 — 핵심)
**A. 위험구역 침입 + 위험성평가 자동작성**
딥러닝으로 안전구역 설정 → 위험구역 침입 시 경보 → Analyst가 등급 산정 → Scribe가 산안법/안전보건규칙 기반 **위험성평가서** 자동 생성(Copilot 근거 인용 포함).

**B. 보호구 미착용·부담자세 감지**
PPE 모델로 미착용 직접 감지, 포즈 기반 근골격계 부담자세 지속 감지 → 산안법 근거 위험성평가 작성.
(낙상·쓰러짐 자동감지는 2026-08 기능 제거 — 오탐 지속·참조 클립 부재, `docs/P3_BACKLOG.md` PF. 재도입 조건도 같은 항목 참고.)

**C. 프레스·전단기 위험노출 + 방호장치 연동**
- 광전자식 방호장치(Type 4 등)를 **우회**하여 위험구역에 신체·손을 넣는 행동을 딥러닝 비전으로 감지(`guard_bypass`, severity=critical).
- 동작: **알람 → 관리자 통보 → 위험성평가 작성**.
- 고도화: 비상정지 회로에 **신호 제공**(연동). **단, §8 기능안전 경계 필수 — 비전은 보조·감시 계층이며 1차 정지 책임이 아님.**

### 7.2 office (자세교정)
기존/신규 사무실 카메라 → 거북목(CVA 각도)·자세 틀어짐·자리비움·장시간 착석 탐지 → Coach가 자세 교정·근무효율·휴식 피드백.
**필수: §8.2 근로자 영상감시 법적 요건(동의·고지·노사협의·익명 집계) 준수.**

### 7.3 sports (요가·필라테스)
강의 중 수강생별 신체구조에 맞춘 자세 정확도 실시간 판정 → 부정확/저효율 시 **음성 알림** → 개인별 나쁜 습관·자세·호흡을 특화 에이전트가 **모바일/PDF 피드백**.

---

## 8) 기능안전 · 법규 · 개인정보 경계 (중요 — 문서에 명시)

**8.1 기능안전 (프레스·전단기 / 비상정지 연동)**
- 비전 ML은 본질적으로 확률적 → **인증된 안전기능을 대체할 수 없다.**
- 1차 방호는 반드시 **인증 하드웨어**(Type 4 광전자식 방호장치, 안전 PLC, ISO 13849 PLd/PLe, IEC 62046 presence-sensing).
- VIGENT의 비상정지 연동은 **"감지→인증 안전회로에 보조 신호 제공"** 형태로만. 비전 단독으로 SIL/PL 안전기능을 구현·대체한다고 표기/구현하지 말 것. 이 경계를 코드 주석·문서·UI에 명시.

**8.2 근로자 영상감시 (office)**
- 개인정보보호법·근로기준법상 **사전 고지·동의·노사협의** 필요. 개인 식별·실시간 감시형 운영은 법적 리스크.
- 기본은 **익명화·집계 지표**(개인 추적 off). 얼굴 블러 기본 on. 보존기간·접근통제 명시.

**8.3 개인정보 일반**
- 얼굴 비식별화 토글, 영상 최소수집·로컬 처리 우선, 증거 프레임은 암호화 저장.

---

## 9) 논문/근거 써치 (Copilot RAG) 사양
- **코퍼스(테마별)**: safety = 산업안전보건법·안전보건규칙·KOSHA 가이드·사고사례 / office·sports = 자세·물리치료·운동과학 논문.
- **파이프라인**: 임베딩 인덱스(로컬) → 검색 → LLM 근거 합성. 외부 최신 정보는 웹 검색 보강.
- **출력**: 모든 주장에 **출처·조항·DOI 인용** 부착. 위험성평가/피드백에 자동 삽입.
- **저작권**: 검색·요약·인용만. 원문 대량 복제 금지(짧은 인용·출처 표기).

---

## 10) BODA 자산 이식 맵 (복사해서 사용 / 없으면 폴백)
원본 루트: `~/Desktop/사업계획서/AX안전`
- **YOLO 가중치**: `runs/detect/` — PPE `construction_ppe_v30/weights/best.pt`(25클래스, 미착용 직접 감지), 화재 `.../fire_detector/weights/best.pt`, 지게차 `forklift_boda_ax/weights/best.pt`. 없으면 yolov8s 폴백.
- **자세 TF 분류기**: `backend/ml/artifacts/` + `posture_model.py`·`pose_features.py`(COCO 키포인트 4만+ 학습). (`fall_model.py`는 2026-08 낙상 기능 제거로 vigent-core에서 삭제됨 — 원본 MVP 폴더엔 남아있을 수 있으나 이관 대상 아님)
- **운동 폼 모델·학습 스크립트**: `form_model.py`, `train_*_classifier.py`, `ingest_*`, `retrain.py`. (★2026-09-06 감사: office/sports 잔재로 `_archive/themes/fitness/` 격리)
- **베이스 가중치**: `yolov8s.pt`, `yolov8n-pose.pt`, `yolov8s-seg.pt`.
- **데이터셋**: `data/external/`, `data/data_engine/`, `data/scene/`, `data/openimages/`.
- **에이전트 로직**: `safety_agent.py`(위험성평가 build/save), `fitness_agent.py`, `hazard_detector.py`, `evaluator.py`, `tracker.py`, `zones.py`, `scene_classifier.py`, `report_builder.py`, `vitals.py`(rPPG). (★2026-09-06 감사: BODA 계열 전부 `_archive/themes/boda/` 격리 — 코어 import 0건)
- **설정**: `config/settings.yaml`(`*_model_path` 슬롯 — ★2026-09-06 감사: 읽는 코드 0건이라 `_archive/config/` 격리. 현행 모델 경로는 `themes/safety/vision.yaml`), `danger_zone.json`/`zones.json`, `safety_dataset.yaml`, `notify.example.yaml`.
- **테마 임계값**: `realtime_core.js`의 `SERVICE_META`(테마별 pipeline·metrics·thresholds) → `vision.yaml`로 마이그레이션.
> 모델 경로는 설정으로 주입, 파일 없으면 폴백 유지.

---

## 11) 백엔드 API (최소 재현 목록)
- 카메라: `/camera/on|off|status|frame|info`
- 탐지: `/detect/frame`(ppe/seg/pose 옵션), `/detect/scan`, `/detect/hazards`, `/segment/frame`, `/system/capabilities`
- 안전: `/safety/risk-assessment(+/save,/list,/{id})`, `/report/safety`, `/zone/danger(get/post)`, `/zone/intrusion`, `/zone/state`, `/machine/guard-bypass`
- 자세/운동: `/posture/classify`, `/fitness/feedback`, `/vitals/rppg`
- 근거: `/evidence/search`(Copilot RAG, citation 반환)
- 데이터엔진: `/recognition/log(+/note,/download)`, `/ml/retrain`
- 알림·연동: `/alerts/status|test`, `/notify/telegram/*`, `/dispatch/relay`(⚠ 보조 신호, §8)
- RTSP(상용 카메라): `/rtsp/connect|disconnect|status|stream`
- 라우트: `/«theme»` → 테마 `index.html`

---

## 12) 프론트 UI (관제 콘솔 룩)
- 실시간 웹캠/RTSP + 투명 캔버스 오버레이(영상·캔버스 동일 mirror).
- **전신 스켈레톤**(≈1.4px + 미세 글로우, 정확한 인체 연결, 관절 점) + **손 랜드마크/손 박스**(코너 틱·라벨).
- **검은 반투명 상태 패널(blur)**: 좌측 SYSTEM STATUS(FPS·프레임·작업자·자세·PPE·구역·종합 위험등급+신호바), 우측 DETECTIONS.
- **콘솔 HUD 로그** 스트리밍: `frame=… person=… hands=… zone=… alert=…`.
- **위험 강조**: 위험구역 폴리곤 / 몸통 진입=DANGER(빨강) / 손·팔 접근=WARNING(주황) / 과다 기울기=위험자세(2026-08 이전엔 낙상 의심으로 표시했으나 기능 제거 후 자세 심각도 표시로 전환, PF). 위험 시 스켈레톤·라벨·테두리·배너 색 전환.
- CCTV 분위기: REC 점멸, 시계, CAM 태그, 코너 브래킷, 스캔라인/비네팅, NO SIGNAL 폴백.
- 카메라는 보안 컨텍스트 필요 → `file://` 금지, localhost(서버) 또는 https.
- 참고 구현: BODA `backend/static/themes/safety/console.html`, `index.html`.

---

## 13) 목표 파일 구조
```
vigent-core/
  main.py  pipeline.py  agents/{guard,analyst,scribe,coach,copilot,dispatcher}.py
  vision_loader.py        # vision.yaml 파서 + 폴백 로더
  ml/ ...                 # BODA 이식
  static/
    realtime_core.js      # 공유 엔진(테마-aware, AX_LOCK_THEME 잠금)
    realtime_shared.css
themes/
  safety/{vision.yaml, index.html}
  office/{vision.yaml, index.html}
  sports/{vision.yaml, index.html}
config/  data/  runs/  tests/
실행/VIGENT_«theme».command   # 더블클릭 런처(헬스체크→재시작→브라우저)
```

---

## 14) 산출물 / 수용 기준
1. `«theme»` 라우트 200, 콘솔 에러 0. 웹캠+스켈레톤+손+위험감지 동작.
2. 모델 있으면 정밀 판정, 없으면 휴리스틱 폴백 — **둘 다 무중단**.
3. `unittest` 통과. 위험구역/PPE/guard_bypass/부담자세 판정이 실제 입력에 반응.
4. 위험성평가/피드백에 **Copilot 근거 인용** 자동 포함.
5. 런처 더블클릭 → 서버 자동 기동/재시작 → 테마 페이지 오픈.
6. **상용화 게이트**: KISA 지능형 CCTV 인증 기준(카테고리별 정확도 **90%+**)을 safety 핵심 이벤트(침입·PPE·부담자세)에 대해 측정·기록하는 평가 파이프라인 포함.
7. §8 경계(기능안전·근로자 감시·개인정보)가 코드/문서/UI에 명시.

---

## 15) 빌드 순서 (권장 로드맵)
1. BODA 자산 인벤토리·복사 → `vigent-core` 골격 + 폴백 로더.
2. `vision_loader.py` + safety `vision.yaml` → 6-에이전트 스텁 연결.
3. safety 테마 페이지(콘솔 룩) → 규칙+TF 가산 판단.
4. Scribe(위험성평가) + Copilot(RAG 근거) + Dispatcher(텔레그램·통보).
5. guard_bypass(프레스/전단기) + `/dispatch/relay` 보조 신호(§8 경계 문서화).
6. 데이터엔진/리포트 → RTSP → KISA 평가 파이프라인.
7. office / sports 테마 확장(vision.yaml + 프론트만).
8. (상용) AGPL → RF-DETR/RTMPose 마이그레이션.

---

## 16) 시작 전 확정할 것 (에이전트가 먼저 질문)
- 1차 테마(기본 safety), 배포 대상(로컬/서버/엣지), 카메라 소스(웹캠/RTSP), 클라우드 LLM 정밀분석 사용 여부.
- 알림 채널(텔레그램 외), Copilot 코퍼스 범위(법령 셋·논문 DB).
- BODA 자산 복사 vs 심볼릭 링크, 데이터셋 라이선스 확인.
- 라이선스 단계(PoC: Enterprise/온프레 공개 vs 상용: 허용형 전환).
- §8 적용 범위: 프레스 비상정지 연동 수준(감지만 / 보조 신호 / 인증 회로 연동), office 근로자 감시 법적 절차 상태.
