# VIGENT P3 백로그 (P0~P2 완료 후 후속 항목)

> 작성 기준: 2026-07-16 · P0~P2 라운드 완료 시점.
> 이 문서는 P0~P2 작업 중 **"후속 항목으로 기록"하기로 미룬 것들**을 우선순위·리스크와 함께 모은다.
> 각 항목은 왜 그때 미뤘는지(출처)를 함께 적어, 착수 시 맥락을 잃지 않게 한다.
> 원칙(CLAUDE.md): 저하 없는 방향으로만, 착수 전 계획 보고, 근거 있는 것만.

---

## 우선순위 한눈

| # | 항목 | 우선순위 | 리스크 | 출처 |
|---|---|---|---|---|
| ~~B11~~ | ~~디스크 보존 정책 — 증거 이미지 무한 증가(상용화 실차단)~~ ✅ 인프라 구현 완료(잠정값) | — | 낮음(기본 비활성) | [Y-4/Z](#b11), 2026-08-10 |
| ~~B1~~ | ~~CI 첫 실행 green 실검증~~ ✅ 완료 | — | — | run #2 green(4m 1s) |
| ~~B2~~ | ~~런타임 가변 config 파일 격리~~ ✅ 완료 | — | — | runtime_config.py |
| ~~B3~~ | ~~web_util 언더스코어 prefix 정리~~ ✅ 완료 | — | — | 공개함수 12개 rename |
| B4 | rig_monitor 배선 — 상태기(b) 검증완료, 배선은 B8 의존 | 중(제품) | 중 | P1-10·F-13 |
| ~~B8~~ | ~~쓰러진/저자세 사람 검출 개선~~ ⛔ 종결(해상도 한계) — 검출강화는 B9로 | — | — | 실측 4R |
| ~~B9~~ | ~~구역-타일링 검출 강화~~ ✅ 구현완료(기본 off, VIGENT_ZONE_TILE) | — | — | 커밋 ①②③ |
| B5 | worker 반환 타입힌트 보강(28) | 낮~중 | 낮음 | P2-12 |
| ~~B6~~ | ~~vlm_text 헬퍼 미적용 11곳~~ ⛔ 재평가 후 종결(적용 안 함) | — | — | P1-6 |
| ~~B7~~ | ~~ml/rfdetr_zone_track 중복 제거~~ ✅ 완료(zone_geom 순수모듈) | — | — | P2-11 |
| B10 | 추적기 MOTA/IDF1 라벨 재확인(SORT→ByteTrack 검증) | 중 | 낮음 | item4 A/B |
| B12 | RBAC(역할별 권한 분리) — 현 단계 보류 | 낮(현재)·**재개조건부** | 낮음(현재) | [S2-수정](#b12), 2026-08-10 |

기존 다른 트랙의 백로그(참조)는 맨 아래 별도.

<a id="b11"></a>
## B11. 디스크 보존 정책 — 증거 이미지 무한 증가 — ✅ 인프라 구현 완료(2026-08-10, 잠정값)
- **무엇**: `vigent-core/data_engine.py`의 `log_event()`→`_save_frame()`이 이벤트(위험 감지)마다
  `data/evidence/<YYYYMMDD>/ev_*.jpg`로 프레임을 저장한다(`main.py`가 `/evidence`로 정적 서빙).
  **삭제·보존기간·용량 상한 로직이 코드 어디에도 없다**(전수 grep 확인, `retention`·`purge`·
  `rotate` 등 관련 키워드 0건) — 이벤트가 나는 만큼 디스크가 계속 찬다.
- **왜 상용화 실차단인가**: 실제 현장에 24시간 배포하면 이벤트 빈도에 따라 evidence 디렉터리가
  무한정 커진다. 디스크가 꽉 차면(로그·DB·OS 자체까지 영향권) 서비스 중단으로 이어질 수 있는
  운영 리스크이지, 성능 튜닝처럼 미뤄도 되는 항목이 아니다.
- **아직 하지 않은 것(설계 필요, 미착수)**: 보존기간(예: N일 후 자동삭제) 정책 값 결정 — 안전
  사고 조사·법적 증거 보관 요건과 충돌할 수 있어(산업안전보건법상 증빙 보관 의무 존재 가능,
  법무 확인 필요) 단순 삭제보다 신중한 설계가 필요하다. 옵션: ①보존기간 설정 + cron/백그라운드
  정리 작업 ②사고 심각도(level)별 차등 보존 ③외부 스토리지(S3 등) 이관 후 로컬 삭제 ④디스크
  사용량 모니터링·경고만 우선 추가.
- **[Z-1](2026-08-10) 전수 조사**: evidence 외 8개 무기한 누적 경로를 추가 확인(총 9개+조건부
  1개) — audit·tbm·risk_assessments·office·sports·recognition 이벤트 로그·go2rtc.log·legal
  차단 로그. 그룹별(안전증거/감사문서/개인모니터링/운영로그) 상세는 `docs/
  disk_retention_policy.md`.
- **[Z-2](2026-08-10) 인프라 구현 완료**: `vigent-core/retention.py`(스캔·삭제·회전)·
  `scripts/retention_sweep.py`(CLI, dry-run 기본)·`data_engine.py`의 evidence pin 보호·
  `/health`의 `disk_retention` 필드(침묵 실패 금지)·D그룹(go2rtc.log·legal 로그) 크기상한
  회전. 테스트 11건(`tests/test_retention.py`, pin 보호 포함). **정리 기능 자체는 여전히
  기본 비활성**(`retention.enabled: false`) — 활성화는 배포 시 명시적 결정.
- **보존 일수 잠정값 확정**: A(evidence/recognition) 30일·B(audit/tbm/risk_assessments)
  1095일(3년)·~~C(office/sports) 7일~~을 `config/tuning.yaml`에 채움 — **법률 전문가 확인 전
  잠정값**(무기한 지연 방지를 위한 사용자 결정, 고객사 개인정보 처리방침에 따라 계약 시
  조정 필요, 규칙7 명시).
- **용량 산정**: `docs/ops_disk_sizing.md`(카메라×이벤트빈도×보존일 계산표, 실측 단가
  기반) — 예시 시나리오 기준 그룹A(안전증거)가 용량을 압도적으로 지배.
- **[Z-3](2026-08-10) 갱신**: office/sports 기능이 영구 삭제되며 그룹 C(위 [Z-1]의 office·
  sports 경로, 위 잠정값의 C 7일)가 통째로 없어졌다 — 현재 유효 그룹은 A/B/D뿐(상세는
  `docs/disk_retention_policy.md` 상단 갱신 공지).
- **남은 것**: 실제 배포 시 그룹별 `enabled`/`dry_run` 활성화 여부는 현장별 결정 필요.
  잠정 보존일수의 법무 검토(아직 안 됨).

<a id="b12"></a>
## B12. RBAC(역할별 권한 분리) — 현 단계 보류 (2026-08-10)
- **배경**: [S2] 보안 점검 Phase 2에서 발견 — 106개 HTTP 라우트 전부가 단일 토큰
  (`VIGENT_API_TOKEN`)으로 동일하게 게이트된다. 라우트별 차등 권한(읽기 전용 뷰어 vs
  카메라/위험구역 설정 변경 권한 등)이 없어, 토큰 하나가 유출되면 전권이 유출된다.
- **왜 지금은 보류인가(사용자 결정)**: 현 단계(운영자 1인 가정)에서 RBAC 설계는 과설계다 —
  구현 난이도가 높고(역할 정의·미들웨어·세션 관리 재설계) 지금 얻는 방어 이득이 작다.
- **재개 조건(명시)**: **고객사 측에서 여러 명(2인 이상)이 VIGENT에 접속하는 시점**이 되면
  필수로 재검토한다 — 예: 현장 관리자(설정 변경 가능)와 단순 모니터링 뷰어(조회만)를
  구분해야 하는 배포가 생기는 시점. 그 전까지는 단일 토큰 모델 유지.
- **참고**: 재개 시 최소 구현 방향(미검증 제안) — 토큰을 role 클레임 포함 JWT로 바꾸거나,
  라우트를 read/write로 나눠 별도 토큰 2종(뷰어용·관리자용)을 두는 정도부터 시작 가능.

<a id="b10"></a>
## B10. 추적기 MOTA/IDF1 라벨 재확인 — [중]
- **배경**: item4(2026-07-21) 추적기 A/B(`tools/track_quality.py`)에서 현행 SORT 가 크레인 다중작업자 400f 에서 심각히 단편화(39 ID·ID스위치 13·단편화 3.9)됨을 확인, **ByteTrack**(5 ID·0 스위치·단편화 1.0)으로 교체(rfdetr_service·rfdetr_zone_track). 게이트 통과·저하 없음.
- **한계(교체 근거의 캐비어트)**: ① **GT 트랙ID 없는 프록시 지표**(ID스위치·단편화는 IoU 매칭 기반, '5명=정답'은 최대동시 가정) ② **다중인 클립 1개**(크레인)뿐 — walk 클립은 단일인이라 변별 없음 ③ 검출은 COCO nano(단 4추적기 동일 입력이라 A/B 자체는 공정).
- **할 일(라벨/footage 확보 후)**: 다중인 현장 클립에 **트랙ID GT 라벨** → **MOTA·IDF1·IDsw** 정식 산출로 ByteTrack 우위 재확인. 필요 시 ByteTrack 파라미터(`track_activation_threshold`·`lost_track_buffer`·`minimum_iou_threshold`) 현장 튜닝(현재 기본값). `tools/track_quality.py` 를 GT 대조 모드로 확장.
- **재개 조건**: 다인 top-down 현장 클립 + 트랙ID 라벨(F-1·라이브 추적 백로그와 묶어 진행).

<a id="b8"></a>
## B8. 쓰러진/저자세 사람 검출 개선 — [높음·제품]
> **주석(2026-08-06)**: 이 조사 당시 존재하던 `worker.py`의 `FallTracker`는 이후 작업자 낙상 감지 기능 자체가
> 제거되며 함께 삭제됐다(PF 항목 참고). 아래는 그 삭제 이전 시점의 실측·분석 기록이며, **카메라 해상도
> 한계에 대한 결론(자세/pose 판별 물리적 불가)은 지금도 유효**하다 — 재도입 시 참고할 근거로 보존.
- **문제(당시)**: rig_monitor ALARM (b)는 `fall` obs 에 의존하고, fall 은 person 박스를 입력받는 FallTracker 가 만든다. 그런데 광역 CCTV·작은 작업자(F-13)·쓰러진 저자세에서 **person 검출이 실패** → fall obs 못 만듦 → (b) 경보 안 뜸.
- **Baseline 실측(크레인재해 영상 사고구간 t=36~45)**: 현재 검출(RF-DETR COCO 폴백, 기본 임계 0.4) 쓰러진 작업자 **recall = 0%(37프레임 중 0)**. 프레임당 평균 person 0.65개. ※ COCO 폴백 기준(커스텀 person 가중치 없음) 캐비어트.
- **접근법 실측·분석(이 영상)**:

  | 접근 | 이 영상 실측/판단 | 효과 | 비용 | 리스크 |
  |---|---|---|---|---|
  | (a) 저임계 | recall 0%→**80%@0.05·90%@0.02** (검출 conf 0.05~0.24 — 기본 0.4가 걸러냄) | 큼(신호 복구) | 낮음(설정) | **높음: 전역 저임계=오탐 폭증(정밀도 저하)** |
  | (b) 시간단서 | (a)로 박스 있어야 성립. 정적·저위치 지속 = 쓰러짐 추정 | 중 | 중 | 높음: 사라짐/정지를 가림·이탈과 구분 어려움 |
  | (c) pose 저자세 | (a) 박스에 RTMPose → 저자세 확정. **단 26~64px 에서 pose 정확도 미검증** | 중~큼(정제) | 낮음(기존 pose 재사용) | 중: tiny 박스 pose 신뢰도 |
  | (d) fine-tune | 이 영상=쓰러진 1인 216프레임(다양성 부족). 유사 overhead CCTV 낙상 데이터 수집 필요 | 큼(정밀 신호) | 높음(라벨+학습+데이터) | 중: 과적합·데이터 출처 |
- **구조적 의존성**: (b)(c)는 person 박스가 먼저 있어야 함 → baseline 0% 에선 신호 없음. **1차 신호는 (a) 저임계 or (d) 학습만 생성.** (a) 결과가 "저임계로 복구됨"이라 (a)+(c)/(b) 조합이 열림.
- **2차 실측(3종, 사고=t36~45 37f / 무사고=t0~35 36f)**:

  | 측정 | 결과 | 해석 |
  |---|---|---|
  | ① 저임계 오탐 | 전역 thr0.05 **~70박스/frame** · ROI 140 vs thr0.4 16 | 전역 저임계 파탄. 구역스코프여도 무사고 ROI ~3.9후보/f → 확정레이어 부담 |
  | ② 타일링(e) | **recall 95%(35/37)**, best conf 최대 **0.561**, 6/37>0.4. **3.8× 시간**(0.49→1.87s) | 신호품질 최고 — 문제가 '해상도'임 확정. 완전recall엔 임계~0.1 병행 |
  | ③ YOLO11m(f) | **recall 0%(0/37)** conf0.05에서도 0 | 아키텍처 부적합. RF-DETR≫YOLO. (ROI만 측정) |
- **결론**: RF-DETR 유지(YOLO 아님). 문제 핵심=해상도 → **타일링이 conf를 0.24→0.56 로 끌어올림**. 저임계 단독은 오탐 과다.
- **추천 최종설계(미착수·승인 대기)**: **RF-DETR + 위험구역-한정 타일링 + 중간임계(~0.1) + (b/c) 쓰러짐 확정.** 구역 안에서만 타일링(전체 3.8× 회피·오탐 구역한정) → 중간임계로 recall↑ → 정적·저자세로 확정. 가산 레이어(규칙6).
- **측정환경 주의**: RF-DETR 모델로드 ~251s로 매우 느림 → 측정은 프레임 디스크추출 후 백그라운드 배치로.
- **3차 실측(확정레이어) — 🔴 합격기준 미달(NO-GO)**: 합격기준=무사고 오경보 0 + 사고 recall≥80%.

  | 항목 | 결과 | 판정 |
  |---|---|---|
  | 구역-타일 recall(확정 전) | 33/37=89% | recall 자체는 OK |
  | (c) pose 산출률 | 사고 5/128(3.9%)·무사고 13/108 | 🔴 26~64px 에서 keypoint 거의 미산출 |
  | (c) pose '쓰러짐' 플래그 | 사고 0·무사고 0 | 🔴 실제 쓰러진자도 pose 확정 실패 |
  | (b) bbox 종횡비 | 사고 median 0.79·무사고 1.5 | 🔴 분리 안 됨(쓰러진자가 더 넓지도 않음) |
  | 무사고 후보 | 108/36f, 실작업자 conf 최대 0.83 | 🔴 확정 부담 과다 |
- **결론(규칙7 정직)**: **이 카메라 해상도(작업자 26~64px)에선 자세/pose 기반 낙상 판별이 물리적으로 불가** — pose 미산출·bbox 모양 무변별. F-13(하물 미가시)의 '자세' 버전. 추천 설계(구역타일+b/c)는 오경보0+recall80% 동시 달성 불가.
- **4차 실측(시간단서 정적-지속) — 부분 성공(어드바이저 경계선)**: 2fps 트래킹+정적런 스윕.
  - 쓰러진 작업자 정적-지속 **8.0s**(주석 "8초+"와 일치) → **시간단서로 포착됨**(자세/pose 완전실패와 대조).

  | T | 사고 포착 | 무사고 오탐트랙(35s창) |
  |---|---|---|
  | 3s | ✅ | 6 |
  | 5s | ✅ | 3 |
  | 10s | ❌(8s<10s) | 1 |
  - **판정**: recall 은 되나 "쓰러짐" 특정은 못 함 — 잡는 건 '위험구역 내 정적 사람'(리깅 작업자도 정적이라 오탐). T=5s=recall1/1+오탐3/35s(~5/분). **하드알람 실패, 스코프-다운 어드바이저("구역에 5s+ 정지→확인요청")로는 경계선.** rig_monitor 실관심(인양 중 반경 미이탈)과는 부합.
  - **한계**: n=1(영상1·쓰러진자1·무사고창1). 오탐율 일반화 불확실.
- **B8 종합 결론**: 검출 recall=구역타일링으로 해결(89~95%, →B9). **자동 '낙상' 특정은 이 해상도로 불가**(자세/pose 실패). 시간단서는 '정적-사람' 어드바이저로만 경계선 유효. → **하드 fall-alarm 배선 불가 확정. 스코프-다운 어드바이저는 다중영상 검증 후 판단.** rig (b) 하드배선 계속 보류.
- **재검토 옵션(미착수)**: ① 스코프-다운 어드바이저 구현(오탐 감수, 다중영상 검증 선행) ② (d) fine-tune(해상도 한계 잔존) ③ **근접·고해상 카메라**(물리적 해결·F-13 동일).

### B8 종결 (2026-07-17) + 재개 조건
**종결 사유**: 검출 recall 은 구역-타일링으로 해결(→[B9](#b9)). 그러나 **자동 '낙상' 특정은 이 카메라 해상도(작업자 26~64px)로 불가 확정** — 자세/pose 산출 3.9%, bbox 무변별, 시간단서는 '낙상'과 '작업 중 정적' 미분리. **rig_monitor (b) 하드 fall-alarm 라이브 배선 불가.** 스코프-다운 어드바이저는 n=1 이라 보류.

**재개 조건 (나중에 이 데이터가 생기면 진행)**:
1. **어드바이저 검증 재개용 영상 요건** — 통계적 유의성(현재 n=1 탈피):
   - 광역 CCTV 낙상/깔림 **사고 영상 ≥ 10건**(서로 다른 현장·시간대·조명, 작업자 픽셀높이 다양).
   - 정상 리깅/작업(정적 자세 포함) **≥ 3시간** 무사고 영상(오탐율 분모).
   - 목표: 정적-지속 임계 T 를 고정했을 때 recall(사고 포착률)·오탐율(건/시간)을 **신뢰구간과 함께** 산출. 어드바이저 채택선(예: recall≥80% & 오탐 ≤ N건/시간)을 데이터로 결정.
2. **근접 카메라 도입 시 요구 스펙(초안)** — 자세/pose 기반 낙상판별이 성립하려면:
   - **rig 위험구역 기준 작업자 최소 픽셀높이 ≥ 120px**(현재 26~64px). pose(RTMPose)가 안정적으로 keypoint 를 내는 하한 경험칙(이 영상 61px median 에서 pose 산출 3.9% → 최소 2배 필요).
   - 역산 가이드(초안, 실측 보정 전제): 작업자 실키 ~1.7m 를 120px 로 담으려면 세로화각당 픽셀밀도 ≈ 70px/m 이상. 1080p(1080세로)면 세로 실시야 ≤ ~15m, 720p 면 ≤ ~10m 안에 작업역이 들어오도록 **설치 거리·초점거리(화각)** 를 잡는다. → 광역 조망용이 아니라 **rig 작업역 전용 근접 카메라**(별도 채널) 필요.
   - 검증: 도입 후 이 B8 측정 스크립트(아래 보존 자산)로 pose 산출률·낙상 recall 재측정.

**보존한 회귀 자산** → [benchmarks/rig_fall/](../benchmarks/rig_fall/) (스크립트 4종 + 결과 JSON 3종 + README):
- b8_lowthr / b8_measure3(오탐·타일링·YOLO) / b8_confirm(pose·aspect) / b8_temporal(정적-지속 스윕).
- `footage/크레인재해.MP4`·`.obs.csv` 는 대용량/주석이라 gitignore(로컬 관리). 재현법은 benchmarks README 참조.

---

## B1. CI 첫 실행 green 실검증 — ✅ 완료 (2026-07-17, run #2 gates 4m 1s Success)
- **결과**: GitHub Actions CI 4개 스텝(ruff·mypy·unittest·OpenAPI 체커) 전부 green. 첫 런은 CI 러너 가중치 부재로 F-8 기동거부 실패 → `VIGENT_ALLOW_FALLBACK=1`(F-8 공식 opt-in) 반영 후 run #2 통과.
- **무엇이었나**: `.github/workflows/ci.yml`의 실제 GitHub Actions 첫 런 green 확인. (원격 미연결로 미뤘던 항목)
- **리스크**: 낮음. 다만 리눅스 러너에서 torch/onnxruntime 설치 실패, 또는 `python -m mypy`/`check_openapi_diff.py`의 `import main` 시 Apple전용 의존(mlx 등 — 현재 하드 import 없음 확인)이 첫 런에서 드러날 수 있음.
- **권장 접근**: ① GitHub 리포 생성·`git remote add origin`·`git push -u origin main` → ② Actions 탭에서 CI 런의 4개 스텝(ruff/mypy/unittest/체커) green 확인 → ③ 실패 시 로그로 원인 분석(requirements 핀 조정 등). 상세 체크리스트는 [ONBOARDING.md](ONBOARDING.md) §6.
- **가중치·F-8 맥락(첫 런 실패로 확인)**: **CI 러너에는 커스텀 가중치(`weights/*.pth`, `.gitignore` 제외)가 없는 것이 정상 상태**다. Guard 생성 시 F-8 기동거부가 발동하므로, `ci.yml` gates 잡에 `VIGENT_ALLOW_FALLBACK: "1"`(F-8 공식 opt-in 처리 경로)을 둔다 — 현재 CI 테스트는 실제 `guard.detect()`를 호출하지 않아 COCO 다운로드는 발생하지 않는다. **나중에 CI에 검출 테스트(guard.detect 호출)를 추가하는 사람**은 이 폴백이 COCO 사전학습을 쓴다는 점(커스텀 검출 저하)을 인지하고, 검출 정확도를 단정하는 assert 는 피하거나 더미 가중치를 주입할 것.

## B2. 런타임 가변 config 파일 격리 — [중]
- **해결(2026-07-17)**: `runtime_config.py` 신설 — **config/ 는 커밋된 읽기전용 시드**, **런타임 write 는 `data/config/`(gitignore)** 로. `read_path`(런타임 우선→시드 폴백)·`runtime_path`(항상 data/). 배선: `web_util._zone_get/_zone_set` · `worker._load_zone` · `rfdetr_service._load_zone_and_threshold` · `ppe_check.get_rules/save_rules`.
- **전수 조사 결과**: 런타임 write + git 추적은 **3개뿐** — `config/danger_zone.json`·`config/machine_zone.json`(이미 빈값)·`config/ppe_rules.yaml`(코드 기본값 `_DEFAULT_REQUIRED`와 동일). site/notify.yaml 은 이미 gitignore, demo·zones.json 은 data/·오프라인이라 무관.
- **마이그레이션 결정(조건 3 → 자동복사 미포함)**: read 폴백(data/→config/ 시드)이 기존 config/ 커스터마이즈를 투명하게 읽어 데이터 손실 0 + 아직 실배포 없음 → 기동 시 상시 자동복사(부작용·테스트 결합)는 도입하지 않음. **기존 배포에서 config/ 를 이미 수정(구역 그림)한 경우**: 그 값이 시드로 계속 읽히므로 동작엔 문제없고, 트리를 깨끗이 하려면 **1회 `git checkout config/danger_zone.json config/machine_zone.json config/ppe_rules.yaml`**(그린 값은 이후 UI 저장 시 data/ 로 이관됨) 하면 됨. 실배포가 생기면 상시 로직 대신 1회성 opt-in 스크립트를 별도 추가.
- **검증**: `tests/test_runtime_config.py`(시드만/런타임만/둘 다) + fresh-clone 상태(data/ 부재)에서 시드 로드 실증(zone 3점·ppe 기본값) + write→data/·config/ 불변 실증 + CI green(B1과 동일 환경).

## B3. web_util 언더스코어 prefix 정리 — ✅ 완료 (2026-07-17)
- **한 것**: web_util 의 **공개 헬퍼 함수 12개**를 `_x → x` 로 rename(순수 rename, 로직 불변) + 전 호출부(main·worker·rfdetr_service·routers 13) 일괄 갱신.
- **대응표**: `_decode_data_url→decode_data_url` · `_img_from_b64→img_from_b64` · `_incident_boxes→incident_boxes` · `_zone_points→zone_points` · `_zone_get→zone_get` · `_zone_set→zone_set` · `_is_safety_label→is_safety_label` · `_webhook_allowed→webhook_allowed` · `_tpl→tpl` · `_env_or_dotenv→env_or_dotenv` · `_evidence_url→evidence_url` · `_product_version→product_version`.
- **유지(_ 그대로)**: 내부 전용 함수 `_zone_cfg_path`·`_load_allowed_webhook_hosts`(외부 미import), 모듈 상수 `_HERE`·`_ROOT`·`_SAFETY_KEEP`·`_TBM_CSS`(함수 아님 + `_ROOT` 는 타 모듈 로컬과 충돌 회피).
- **검증**: shadowing/충돌 0(사전 grep) · 옛 이름 잔여 0(grep) · ruff 0 · mypy 18파일 · 60 tests · OpenAPI 106.

## B4. rig_monitor 배선 여부 결정 — [중·제품]
- **무엇**: [rig_monitor.py](../vigent-core/rig_monitor.py)(줄걸이 상태기계)는 로직 완성이나 라이브 경로(main·worker)에 **미배선**, 유닛테스트에서만 사용.
- **진행(2026-07-17)**: 검증 도구 `rig_replay.py`(수동 obs CSV → 상태기계 재생) 신설 + footage(크레인재해.MP4, 1280x720 24fps 45.5s, HEVC 정상 디코드·변환 불필요)로 **부분 검증 완료**. ▶ 아래 검증 결과.
- **검증 결과(수동 obs 주입)**:
  - ✅ **(b) 낙상 경보 타이밍 정확**: 주석 사고시각 t=38 → 상태기계 ALARM (b) t=38.21s(설계된 alarm_confirm 0.2s 지연과 일치). 상태기계 로직 정상.
  - ⚠️ **(a) 하물높이 경보는 미검증**: 이 영상은 하물(파이프)이 지면 적재/높이판단불가(load_h 대부분 None) → LIFT_CHECK/HOISTING 국면 자체가 없어 (a)·(c) 검증 불가. (a) 검증은 여전히 하물 검출기+미터보정 필요(B4 Option 2).
  - 🔴 **실배선의 진짜 갭 발견**: COCO person 자동검출을 실영상에 돌린 결과, **사고순간 t=38 에서 2명 중 1명만 검출(쓰러진 저자세 작업자 누락)** · t=24 리깅작업자 0/1 누락. 프레임 육안확인 결과 광역 CCTV·작은 작업자(F-13)·쓰러진 저자세가 원인. **즉 실제 자동배선 시 `fall` obs 는 person 박스에 의존하는데, 쓰러진 사람을 person 검출이 놓쳐 ALARM (b)가 안 뜰 위험** — 상태기계 로직은 맞지만 obs 생성(검출)이 약점.
- **Option 2 판단**: 하물 검출기(crane/steel_plate)를 학습해도 **이 사고(낙상/깔림)는 못 잡음**. 우선순위가 더 높은 것은 **쓰러진/저자세 사람 검출**(fall obs 신뢰성). 크레인 하물 검출기는 (a) 시나리오 전용 — 별도 판단.
- **리스크**: 중. 검증 없이 배선하면 "동작한다" 오주장 위험(규칙 7). (b) 로직은 검증됐으나 검출 갭 미해소 → **여전히 라이브 배선 보류**(가산 경보로도, 놓침이 잦으면 오히려 신뢰 저하).
- **상태(2026-07-17)**: **상태기 (b) 실영상 검증 완료 · 라이브 배선은 [B8](#b8) 에 의존.** obs 생성(쓰러진 사람 검출)이 선결이라 B8(쓰러진/저자세 사람 검출 개선)로 분리.

## B9. 구역-타일링 검출 강화 (B8 부산물) — [중·제품]
- **무엇**: B8에서 만든 **위험구역-한정 타일링 추론**(구역 크롭을 확대해 RF-DETR)이 **소형 객체 person recall 을 실측으로 크게 올림** — 낙상과 무관하게 재사용 가능한 자산.
- **실측 근거(크레인재해 영상)**: 전체프레임 기본검출 person recall 0%(쓰러진자)·평균 0.65명/frame → **구역-타일링(임계~0.1)으로 89~95%**. conf 도 0.24→최대 0.56 으로 상승. 문제 핵심이 '해상도(작은 객체)'임을 확정.
- **재사용처**: 광역 CCTV 의 모든 소형객체 기능 — **zone_intrusion(위험구역 침입) recall**, 협착(proximity) 사람 카운트, 인원 밀집(crowd) 등. 위험구역은 이미 정의돼 있으니(danger_zone) 그 구역에만 타일 추론을 얹으면 됨.
- **비용/리스크**: 타일링은 구역당 추론 1~N회(전체 프레임 3.8× 아님, 구역 한정). 저임계는 오탐↑라 구역 스코프 + 기존 임계 유지(가산). 핫패스 영향은 구역 크기·타일 수로 조절. **기존 일반검출 무영향(가산 레이어, 규칙6).**
- **구현 완료(2026-07-17, 커밋 ①②③) — 기본 off**:
  - `zone_tile.py`(가산 헬퍼, detector 주입식): 구역 크롭 확대 재검출 → zone 내부 person 박스. `foot_in_zone` 판정.
  - `rfdetr_service.detect_persons(img, thr=0.1)`: 저임계 person 검출 가산 메서드(지연로드 — off 면 모델 로드 0).
  - `worker._process_frame`: `VIGENT_ZONE_TILE=1` 일 때만 `_derive` 직후 구역-타일 재검출 → zone 내부 person 있으면 **zone_intrusion 만** 추가발화(★스코프 한정: 공유 detections 미병합 → proximity/crowd/motion/PPE 무영향, 확인1). 중복 발화 금지.
  - `VIGENT_ZONE_TILE_EVERY=N`: N프레임마다 타일(기본 1). 최악 지연 = N/fps초.
- **검증(③)**:
  - **recall 개선**: 소형 person recall 0%→**89~95%**(B8 실측), conf 0.24→0.56 → zone_intrusion recall 직결.
  - **오탐 변화**: 저임계 타일은 노이즈 후보를 냄(B8 ①) → **h≥15px 필터 + zone_intrusion 쿨다운 15s** 로 완화. 노이즈 박스가 false zone_intrusion 가능성 잔존 → **활성 전 현장별 오탐 확인 권장**. 기본 off + 스코프 한정으로 위험 국한.
  - **핫패스 비용**: 구역-타일 추론 **≈415ms/frame**(CPU RF-DETR 폴백, 343~485ms; **GPU 훨씬 빠름**). 2fps 워커에서 매 프레임은 과부하 → **every-N 권장**(N=4면 amortized ~104ms/frame).
  - **카메라 확장**: `DETECT_LOCK` 직렬화라 추가부하 = ΣK(415ms/N). N·구역크기·GPU로 조절.
  - 게이트: ruff0·mypy19·73→76 tests·OpenAPI106·순환0. 기본 off 라 프로덕션 동작 변화 0.
- **운영 가이드**: `VIGENT_ZONE_TILE=1` 로 활성, `VIGENT_ZONE_TILE_EVERY=N`(CPU면 N≥4 또는 GPU 권장). 활성 전 현장 오탐·핫패스 비용 실측.
- **확장 보류(proximity·crowd)**: 동일 헬퍼를 협착(proximity)·인원밀집(crowd) 등 다른 소형객체 기능에도 적용 가능하나, **현장 오탐 확인(활성 후 실측) 전까지 보류.** zone_intrusion 에서 저임계 타일의 오탐율이 현장에서 검증된 뒤 확장 판단.

## B5. worker 반환 타입힌트 보강 — ✅ 부분완료(2026-07-17)
- **한 것**: worker 미힌트 함수 **29→13** (16개에 힌트 부여, 동작 불변). numpy 는 이미 최상위 import 라 `np.ndarray` 직접 사용. mypy 0·ruff 0·76 tests.
  - 부여: `_point_in_poly`·`_frame_to_dataurl`·`_person_metrics`/`gp`(np.ndarray)·`persons`·`read_latest`(tuple)·`FallTracker/ErgonomicsTracker.update`(반환)·`_PoseModel`/`FallTracker`/`MotionTracker`/`ErgonomicsTracker.__init__ -> None`(+ `self._m: Any`·`self._tracks: list` 변수annotation).
- **잔여 13개(불가피 — 그대로 둠, 사유)**:
  - **cv2.VideoCapture 경로(스텁 없음 → Any + None→객체 재대입)**: `_open`·`_setup_run`(9-tuple w/ cv2)·`_loop`(cap 재접속 재대입)·`Worker.__init__`(self._cap)·`_StreamCapture.__init__/start/_run/stop`. 반환/변수 힌트를 붙이면 mypy 가 해당 함수를 typed 승격 → `cap=None`(None추론)↔`cv2.VideoCapture` 재대입 충돌. cv2 는 스텁이 없어(전역 `disable_error_code=import-untyped`) 깨끗한 해결 불가.
  - **_FrameCtx.__init__**: 파라미터를 타이핑하면 그 호출부 `_setup_run`(cv2 캡처 함수)가 strict 로 승격돼 위 cap 충돌을 유발(cascade) → 미타이핑 유지.
  - **guard(에이전트, 느슨한 덕타입) 인자**: `_process_frame`·`_run_supervised`·`_hang_watch`. guard 는 깨끗이 import 가능한 타입이 없어(Protocol 도입 전) Any → 보류.
  - `WorkerManager.__init__` — 위 그룹과 함께 남김(경미).
- **결론(규칙4·무리하지 말 것)**: 나머지는 cv2 스텁 부재·guard 덕타입이라 억지 Any/type:ignore 를 쓰지 않고 lenient(본문검사)로 유지. worker strict 승격은 **cv2 타입 스텁 or guard Protocol 도입 후** 재개.

## B6. vlm_text 헬퍼 미적용 11곳 — ⛔ 재평가 후 종결(적용 안 함, 2026-07-17)
- **재평가 대상**: `summarize_bgr` 직접 호출 잔여(scene_vlm ×2·behavior·incident·vlm_confirm ×2·routers office/safety_core/detect). `vlm_dict()` 2차 헬퍼가 실익 있는지 검토(구현 금지, 재평가만).
- **분석**: 흡수 가능한 preamble(지역 import + 호출 + except + `_error`/dict 가드) ~6줄 × ~5곳 = ~20줄 절감(모뎀). 그러나:
  - **폴백이 사이트마다 다름**(None/""/`_fallback(msg)`/`_parse_accident`) → `vlm_dict→None` 은 vlm_confirm 의 `_error` 메시지를 잃음(불완전 흡수).
  - scene_vlm 은 dict 받아 raw 재파싱, vlm_confirm 은 2단 try(로드/추론 분리) → 1:1 부적합.
  - behavior.py 는 실은 **str 소비처**(raw 추출·join) — dict 아님, 기존 `vlm_text()` 케이스(별개·경미).
- **결론**: 흡수 대상이 전부 **폴백-크리티컬 프로덕션 VLM 경로**(재해분석·장면이해·PPE확정·라우터). 저우선 정리를 위해 7곳을 건드릴 리스크 > 모뎀한 dedup 이득. **적용 안 함으로 종결**(규칙: 무리하지 말 것·구현 강행 금지·애매하면 종결). 남은 중복은 의도적 수용.
- **선택적 후속(강제 아님)**: behavior.py 1곳만 기존 `vlm_text()`(str)로 교체하면 자연스러우나, 단독 이득이 작아 보류.

## B7. ml/rfdetr_zone_track.py 중복 comprehension 제거 — ✅ 완료(2026-07-17)
- **한 것**: `zone_points` 를 **의존 없는 순수 모듈 `zone_geom.py`** 로 분리(fastapi/app_state 무관).
  - web_util: `def zone_points` 제거 → `from zone_geom import zone_points`(재export, worker·rfdetr_service 는 여전히 `from web_util import zone_points` 로 무변경).
  - ml/rfdetr_zone_track: `sys.path` 에 vigent-core 추가(worker._PoseModel 과 동일 기존 패턴) → `from zone_geom import zone_points` 로 인라인 comprehension 대체.
- **결과**: worker·rfdetr_service·web_util·ml **4곳이 단일 순수 함수 공유**, fastapi 유입 0. zone_geom mypy strict 편입.
- **게이트**: ruff 0 · mypy 20파일 0 · 76 tests · OpenAPI 106 · 순환 0.

---

## 참조 — 다른 트랙의 기존 백로그(P0~P2 범위 밖)
이 라운드에서 새로 만든 건 아니나, 스캔 중 발견돼 누락 방지 차 링크만 남긴다.
- **라이브 추적 계층 검증**: 낱장 mAP로 안 잡히는 추적 고유 실패(ID 스위치·유령추적) 연속프레임 회귀 — FINDINGS F-8 백로그([RELEASES.md](../md/RELEASES.md)·[COMMERCIAL_AUDIT.md](../md/COMMERCIAL_AUDIT.md)).
- **문서 커버리지 확장(A-SPRINT Phase 2)**: 위험성평가서 외 관리체계·TBM·아차사고 생성기 — 골든셋·감사 이후([AGENT_STATUS.md](../md/AGENT_STATUS.md)).
- **pose 매니페스트 legacy 정리**: `yolov8n-pose.pt`(구 포즈 백엔드) 항목 잔존(런타임 무영향) — 실제 백엔드 RTMPose.

---

## PA. Phase A(ByteTrack 2단계 저신뢰 연계) — ✅ 재평가 완료(2026-08-06, 채택 여부는 사용자 결정 대기)
- **무엇**: guard._track 을 2단계 연계로(고신뢰=1단계 매칭·새트랙, 저신뢰=기존 트랙 유지만·새트랙/이벤트 금지). 구현·게이트 통과했으나 **되돌림**(미커밋).
- **왜 보류했었나**: 확보 클립(초근접 단일 인물·완만 보행)에선 주 person tid 교체가 이미 **0**(1.9d 포함비·수정1 2차매칭으로 트랙 안정) → 개선 대상 없음. test_walk 검출수 +7(완료기준 "변화 0" 위반), fast 검출수 +28·2+박스 31→32%. **이득 0·비용만** → 규칙6.
- **재평가 완료**: 다인·가림·빠른이동 클립(`runs/rfdetr/multi_scene.mp4`) 확보 후 `trackers.ByteTrackTracker`(Apache-2.0, 칼만필터+2단계매칭+전역최적할당)로 재평가.
  구현은 `agents/guard.py`(`track.algo` 튜닝, 기본 iou 불변) 커밋 `fccb558`, A/B 실측은 `benchmarks/track_ab_bytetrack.md` 커밋 `3b3276b`.
  결과: person 고유 tid 42→13(-69%)·파편화 대폭 감소(S1 16→3·S4 4→0·S5 19→7)·swap 회귀 0. 단 인원수 평균 -10.3%
  (S2 기준구간은 0.00 — 노이즈 억제로 해석되나 정답 없이 확정 아님). 4개 채택기준 중 3개 명확 충족, 인원수 1개는
  사용자 판단 필요해 자동 채택 안 함(규칙6) — 채택 여부 결정 대기 중.
- **비고**: Phase B(슬롯 백엔드 A/B)는 Phase C(오탐 억제) 완료 후 — 억제 스택이 깔린 동일 조건에서 백엔드 비교.

---

## PB. 검출 계층 잔여(빠른 이동 블러) — 파인튜닝 augmentation(2026-08-04)
- **배경(2.2 측정)**: 클라 표시오차를 One-Euro(②)로 빠름 p50 6.6→4.4px(목표 달성)까지 줄였으나, 잔여 오차의 상당분은 **모션블러로 검출 자체가 흔들리는 검출 계층 한계**(서버 EMA 기여 ~3.4px, 나머지 블러). 평활·외삽으로는 더 못 줄임.
- **(a) 파인튜닝 augmentation**: person/PPE 재학습(클라우드) 시 **모션블러·고속이동 augmentation**(motion blur kernel·random resized crop·속도 시뮬) 추가 → 블러 프레임 검출 안정화. [[accuracy-baseline-measured]] 재학습과 연계.
- **(b) Phase A 재평가**: 다인·가림 클립 확보 후 ByteTrack 2단계 재측정 — 상세는 위 **PA** 항목.
- **완화(코드 아님)**: 웹캠 노출을 짧게(조명 밝게)하면 블러 감소 → 안내문 `docs/team/97_웹캠_블러_노출_안내.md`.
- **정량 증거 추가(2026-08-06, B-2 조사)**: 이 모션블러 한계가 **낙상(FallTracker) 오발화의 실제 원인**임을
  실측 확인 — 빠른 이동 클립(낙상 없음) 재생 시 16초 중 **30건** 낙상 오발화, 원인 진단 결과 하반신
  키포인트는 검출됐으나(`lower_valid=True`) 모션블러로 위치 자체가 잘못 추정됨. 상세: `benchmarks/box_quality_b2_findings.md`.

---

## PC. 프레스 다인 포즈 사용 시점 재결정(2026-08-04)
- 2.7 로 /safety-local 기본을 MediaPipe(pose off)로 복원, 다인 포즈·프레스 판정(2.4~2.6)은 togPress opt-in 뒤로 보존(코드 삭제 안 함).
- **togPress 실사용(프레스 파일럿) 시점에 재결정**: (a) pose_interleave N=3→2(발화 지연 ~660→330ms, 서버 pose +50%) (b) machine_hazard_zones 편집 UI(기존 danger_zone 도구를 /zone/machine 에 연결) — 현재 machine_zone.json 비어 판정 대상 없음.

---

## PD. 박스 표시 지연내성 잔여 2건 — 실카메라 필요, 맥 백로그(2026-08-05, Phase2A 종료 시 기록)
> `benchmarks/box_quality_phase2a_findings.md` 측정 중 발견. 둘 다 **데스크탑(파일 소스 하네스)으로는 검증 불가** —
> 원인이 서버측 트래커/워커 실시간 동작이라 실카메라·실서버 구동이 전제조건이라서다. 코드 변경 없이 기록만.

### PD-1. tid 재생성 시 클라 재부착 미시도(1차 id매칭 분기)
- **관찰**: `test_fast`(빠른 좌우이동)에서 person 고유 tid **5개** 발급, tid교체(IoU매칭 기준) **0회** — 즉 서버가 트랙을
  놓치면 **교체가 아니라 완전히 새 tid를 발급**하고, 클라이언트(`BoxTracker.ingest()`)의 1차(id매칭) 분기는 미매칭
  tid를 무조건 `alpha=0`부터 새 트랙으로 만든다(기하학적으로 옛 트랙과 가까운지 IoU 재부착 시도 없음).
- **왜 지금 안 하나**: 이 분기를 고치려면 "새 tid가 옛(사라져가는) 트랙과 공간적으로 이어붙는지" 판단 기준(IoU·거리·
  클래스)이 필요한데, 이 판단이 **실제 트랙 손실·재획득이 일어나는 실카메라 클립**에서만 타당성을 검증할 수 있다
  (지금 보유한 두 클립은 폴백 tid<0 이 0건이라, 새 코드가 도입될 근접 오매칭 리스크도 실측 못 함 — Phase2A 후보2·4
  참조). 데스크탑에서 섣불리 구현하면 규칙6(측정 없는 변경 금지) 위반.
- **재평가 조건**: 사람이 카메라 프레임을 잠깐 벗어났다 돌아오는 실카메라 클립 확보 시. 재부착 성공률·오재부착률
  (다른 사람에게 잘못 붙는 경우)을 함께 측정해야 함.

### PD-2. 워커 갱신율 하한 ~205ms(포커스 부스트 상태에서도)
- **관찰**: `index_hub.html:360`의 스포트라이트(확대뷰) 폴링 주석에 "~205ms ts 신호" 명시 — 확대뷰 진입 시
  `spotFocus(true)`로 워커 fps를 부스트해도, 실측 워커 갱신(`ts`) 간격이 **205ms 아래로는 못 내려간다.**
- **영향**: box_quality 하네스는 파일 소스에 `guard.detect()`를 직접 돌려 이 워커 갱신율 자체를 재현하지 못한다
  (하네스는 ingest 캐던스를 인위로 주입할 뿐, 실제 워커 추론·프레임 캡처 파이프라인의 205ms 하한은 측정 대상이
  아니라 전제조건이다). 이 하한을 낮추려면(예: 프레임 캡처·추론 파이프라인 자체 최적화) 실카메라·실워커 구동
  프로파일링이 필요 — 데스크탑 하네스로는 접근 불가.
- **재평가 조건**: 맥에서 실카메라로 워커 프로파일(캡처~추론~기록 각 단계 소요) 실측 후, 어느 단계가 205ms 를
  지배하는지 확인 → 병목 단계별 최적화 검토(예: focus_fps 상한 재조정, 캡처 해상도 다운스케일 등).

---

## PE. safety-local 판정의 MediaPipe 1인 포즈 의존 — 다인현장 오판 위험(2026-08-06) — **P1(출시 전 필수)**
- **무엇**: `themes/safety/index_local.html`의 부담자세·구역침입(부위별) 판정이 서버 다인 포즈가 아니라
  **MediaPipe(브라우저, 1인) 출력**에 직접 의존한다 — `updatePoseUI`/`updateSafetyUI`(`realtime_core.js:2223,2249`,
  `getTrunkTilt(lm)`)와 `vgZoneSeverity`(`index_local.html:394-424`, 주석 "백엔드 포즈 대신 '브라우저 스켈레톤' 사용")
  전부 `frame.pose`/`window._vgPose`(MediaPipe)를 참조. (낙상은 별도 처리 — 아래 비고.)
- **왜 위험한가**: MediaPipe Pose/Holistic 은 구조적으로 단일인물 추정이라, **다인 현장에서 어느 사람을 추적할지
  기기가 임의로 결정**한다. 화면에 여러 작업자가 있으면 판정이 "엉뚱한 사람" 기준으로 나올 수 있다 — 산업안전
  다인 현장(대부분의 실제 현장)에서는 이게 표시 문제가 아니라 **판정 정확도 문제**.
  (2026-08-06 스켈레톤 표시 토글 작업 — 커밋 `826b60d` — 은 이 문제의 **표시(화면에 점이 잘못 그려짐)만** 없앴다.
  MediaPipe 는 토글과 무관하게 계속 돌고, 판정도 계속 그 위에서 계산된다 — 근본 원인은 그대로.)
- **해결 방향**: 이 판정들을 서버 다인 포즈(worker.py, RTMPose 기반 사람별 tid — CLAUDE.md 최신 스택 기준. 과거
  yolov8n-pose 언급은 레거시 이름이니 착수 시 `worker.py`의 `_PoseModel`/`pose/rtmpose_adapter.py` 실제 구현을
  코드로 재확인할 것)로 이관 — 사람마다 별도 tid 로 자세 판정해 "다인 중 특정인" 문제를 원천 해결.
- **비고(낙상)**: 낙상 판정은 2026-08-06 사용자 결정으로 **기능 자체를 제거/비활성화 완료**(worker.py FallTracker·
  realtime_core.js 낙상 판정 경로·console.html 낙상 표시 — 상세는 PF 항목·해당 커밋 참고). 따라서 이 항목의
  "다인화 이관" 대상에서는 **제외**한다.
- **검증 조건**: 맥 실카메라 + 다인 시나리오(2인 이상 동시 작업) 필요 — 데스크탑에서는 재현 불가.

## PF. 작업자 낙상 감지 제거(커밋: "작업자 낙상 감지 제거" — git log 참고, 2026-08-06)
- 사유: 착석 등 정상 상태에서 오발화 지속, 참조 클립(진짜 낙상 영상) 부재로 임계 재보정 불가.
- 재도입 조건: ①정상/양성 참조 클립 세트 확보 ②서버 다인 포즈 기반으로 재구현(기존 MediaPipe 1인 의존 문제 회피)
  ③오탐률·미탐률 측정 후 채택.
- 산업안전 제품 경쟁력상 중장기 재도입 권장.

## PG. team PDF 4종 재생성 필요(낙상 제거분 반영) — [낮음·문서]
- **무엇**: `docs/team/pdf/VIGENT_기획안_통합본_v0.9_20260727.{html,pdf}`·`VIGENT_비전트랙_v0.9_20260727.{html,pdf}`·
  `VIGENT_에이전트트랙_v0.9_20260727.{html,pdf}`·`VIGENT_신규팀원_온보딩_v0.9_20260727.{html,pdf}` 8개 파일은
  `docs/team/00~80_*.md` 소스를 2026-07-27에 1회성으로 컴파일한 산출물(`docs/team/pdf/README.md` §"원본은 항상
  docs/team/*.md"). 소스 중 `01_현황_숫자로_보기.md`의 낙상 관련 서술을 2026-08-06 갱신했으나(Tier1, "기능
  제거됨"으로 정정) 이 8개 산출물에는 **반영되지 않은 구 문구가 그대로 남아있다**(비전트랙·에이전트트랙·통합본
  3종 각 4곳, 대외비— 외부 배포는 안 되지만 팀 내부 열람 시 부정확).
- **재생성 절차 확인 결과**: `docs/team/pdf/README.md`에 변환 방식은 문서화돼 있음("Markdown → 스타일 HTML →
  Chrome 헤드리스 인쇄") 그러나 **이를 수행하는 스크립트/도구는 저장소에 없음**(최초 커밋 `9572481`에 README와
  결과물(html/pdf)만 포함, 변환 스크립트 자체는 커밋된 적이 없다 — 전수 grep으로 확인). 즉 자동 재생성이 불가능
  하고, 사람이 직접 (a) 각 md를 다시 스타일 HTML로 변환하거나 (b) README의 폴백 절차(HTML을 브라우저로 열어
  Cmd/Ctrl+P → PDF 저장)로 진행해야 한다 — 단 (b)도 **먼저 HTML 자체가 최신 md 내용으로 갱신돼 있어야** 유효하므로
  이 역시 사람이 변환 작업을 재수행해야 함.
- **재도입 조건 아님(문서 정합성 항목)**: 우선순위는 낮음(내부 문서, 대외비라 계약 리스크는 낮음)이나 신규
  팀원·비전/에이전트 트랙 담당이 구 낙상 문구를 참고할 수 있어 다음 team 문서 갱신 주기에 함께 재생성 권장.

## PH. Vigent Face Scanner 재구현(LOTO 제거 커밋 `09bdd17` 후속, 2026-08-06) — [높음·제품]
- **★[곁다리 정리, 2026-08-12] `vigentFacialRecognition/`(38MB) 디렉터리 자체를 삭제했다** —
  vigent-core 어디서도 import 0건(grep 실측 확인), 안전 제품 저장소에 생체인식 코드가 남아있는
  것 자체가 고객사 보안 실사에서 불필요한 리스크라 판단. **복구 방법**: 이 삭제 커밋 직전
  마지막 커밋(`bbaa790`) 또는 그 이전 아무 커밋에서 `git checkout bbaa790 -- vigentFacialRecognition/`
  (또는 `git show bbaa790:vigentFacialRecognition/<파일>`)로 전체 복구 가능 — 아래 재구현
  착수 시 이 명령으로 먼저 되살릴 것.
- **배경**: `vigentFacialRecognition/`의 Smart LOTO(전자 잠금장치 연동) 기능을 제거했다(사유: LOTO 자체가
  아니라 "Vigent Face Scanner"라는 더 넓은 형태로 재구현할 계획). 얼굴인식 코어(`recognizer.py`·`iris.py`·
  `enrollment.py`·`liveness.py`·`mfa.py`·`privacy.py`·`config.py`·`api.py`)는 전부 무수정으로 남아있어
  재구현의 기반 자산으로 그대로 재사용 가능(단, 위 삭제로 지금은 git 히스토리에서만 존재).
- **재구현 시 반드시 피할 것(구 LOTO 구현에서 실제 발견된 결함 3가지 — `09bdd17` 커밋 메시지·조사 기록 참고)**:
  1. **신원 검증을 클라이언트 입력(person_id)만으로 하지 말 것** — 생체 확인(얼굴/기타 요소)을 선택이 아닌
     필수로 강제할 것. 구 LOTO의 `_resolve_worker()`는 사진이 없거나 `live=false`면 얼굴 인증을 통째로
     건너뛰고 클라이언트가 보낸 `person_id`를 그대로 신뢰했다(데모 UI 체크박스로도 재현 가능한 경로였음).
  2. **"요청자(caller)"와 "작업 대상자(target)" 신원을 같은 변수로 섞지 말 것** — 구 LOTO는
     `remove_lock(pid, by=pid, ...)`처럼 대상자 신원을 요청자 신원 자리에도 그대로 대입해, 상태머신 자체의
     "본인 것만 해제 가능" 검사(`by != person_id`)가 API 경로에서는 구조적으로 절대 발동하지 않았다. 상태머신
     로직 자체는 정상이었다(단위테스트로 증명됨) — 문제는 API 계층이 두 신원을 분리해서 넘기지 않은 배선.
  3. **`live`·`supervisor` 같은 안전 관련 플래그를 클라이언트가 그냥 넘기게 두지 말 것** — 구 LOTO는
     `live: bool`(이름과 달리 실제 라이브니스 모듈 `liveness.py`를 호출하지 않는 단순 스위치)과
     `supervisor: bool`(권한 확인 없이 클라이언트가 `true`로 보내면 그대로 통과)을 서버측 검증 없이 신뢰했다.
     실제 라이브니스 확인이 필요하면 `liveness.py`의 `LivenessSession`을 연결하고, 관리자 권한은 별도 인증
     경로(예: MFA `high`/`vault` 정책)로 확인할 것.
- **선결 필요(개인정보 — 생체정보)**: 얼굴 임베딩은 개인정보보호법상 **민감정보**(§23). 재구현 착수 전에
  ① 별도 명시적 동의(목적·항목·보유기간을 일반 동의와 분리) ② 보관기간·자동파기 정책 ③ 특징값(임베딩)
  저장방식(원본 얼굴 미저장·암호화)을 먼저 결정할 것. `vigentFacialRecognition/README.md`의 법적 체크리스트
  8개 항목이 그대로 적용 가능하며, 옵트인 스위치(`VIGENT_FR_ENABLED`)·동의기록(`Consent`)·보존기간
  (`VIGENT_FR_RETENTION_DAYS`)·삭제(`DELETE /facial/persons/{id}`)·만료일괄삭제(`purge-expired`)는 이미
  구현돼 있어 재사용 가능 — 새로 만들 필요 없음.
- **범위 참고**: `vigent-core`는 이 기능과 무관(LOTO도 face scanner 예정 자산도 main.py 미장착). 재구현이
  vigent-core에 통합될지, `vigentFacialRecognition/`을 계속 별도 모듈로 둘지는 별도 결정 필요.

## PI. person 박스 추적 baseline — 공학적 한계 지점 도달로 판정, 추가 개선 보류(2026-08-06)
- **무엇**: safety-local person→BoxTracker 이관(커밋 `b653f6b`) 이후 제기된 "박스 겹침·놓침" 문제를
  실측으로 끝까지 추적한 결과, 다음 baseline 이 확정됐고 추가 파라미터 조정은 착수하지 않기로 결정.
- **실측(측정 전용, 코드 무수정 — `benchmarks/person_overlap_investigate.py`·`person_overlap_mac_vs_multi.py`·
  `person_miss_baseline.py`, 결과는 각 동명 `.md`)**:
  - **트랙 커버리지**: mac_single_move(1인, 핸드헬드 근접) **100%·놓침 0건**. multi_scene(다인, 최대 동시
    6명) **93.4%**, 놓침 19건·평균 복구 168.9ms·최대 541.7ms.
  - **겹침(박스 2~3개 중복 표시)**: 원인은 서버 ByteTrack tid 파편화(다인 클립에서 42개 고유 tid 재현
    확인, 1000ms 윈도 내 최대 11건 재발급) — 클라 dedup·anchor 로직은 코드·실측 둘 다로 정상 확인
    (dedup 임계 미만이라 못 잡을 뿐, 우회 아님). **단 사용자가 실제로 증상을 겪은 1인 클립
    (mac_single_move.mp4.mp4)으로는 재현 실패**(tid 1개·재발급 0건, 조밀/성김 재생 둘 다) — 파일
    측정만으로는 실시간 표시 경로(폴링·BoxTracker) 문제 가능성을 확인도 배제도 못 함.
  - **놓침 원인 분해**(다인 19건): 가림 1건(5.3%), 빠른이동·방향전환·모션블러(클립 내 상대비교, 실제
    픽셀 Laplacian 분산 실측) **전부 0건** — **18건(94.7%)이 원인불명**. 검출기 confidence 노이즈로
    추정되나 미검증.
- **판정(사용자 결정, 2026-08-06)**: "박스 추적은 공학적 한계 지점 도달." 근거 — 1인 커버리지 100%·
  놓침 0(더 개선할 게 없음), 다인 93.4%·평균 복구 169ms(이미 빠름), 놓침 대부분이 원인불명이라
  `track_buffer`·외삽 파라미터 조정이 이 18건을 잡는다는 근거가 없고 부작용(사라진 사람 박스가 화면에
  남는 등)만 우려됨. **추가 개선은 실익 낮음 — Phase 2(파라미터 조정) 착수하지 않음.**
- **재현 보조로 남긴 것**: `/safety-local?dbg=1`(또는 'd' 토글) HUD에 표시 중인 person 박스 개수·tid를
  실시간 표기(커밋 `898d245`, 표시 전용·판정 무관) — 향후 실제 겹침 재현 시 tid 동일/상이 여부를
  즉시 육안 확인 가능.
- **재개 조건**: 고정 CCTV 현장 클립(핸드헬드 아닌 실제 설치 환경) 확보 후 재평가. 특히 놓침 94.7%
  원인불명 구간은 이 baseline 만으로는 설명이 안 되므로, 새 클립에서 같은 현상이 재현되는지부터
  다시 본다.

## PJ. 마스크 존(카메라별 검출 제외 영역) — 설계만, 구현 보류(2026-08-12)
- **배경**: [R-2] 000633827(현장 영상, 오탐 압도 사례 — `field_eval_gt_summary.md` "유일하게
  오탐이 압도")를 검토하며 "고정 설비를 마스킹해 오탐을 줄이자"는 안이 나와 정량화했다
  (`benchmarks/r2_mask_zone_review.md`).
- **000633827 자체는 보류 확정**: GT 라벨과 정밀 좌표 대조 결과, 순수 오탐(GT 0개 프레임 6개)의
  위치가 좌상·우상·중앙·중하 등 프레임 전역에 산발적이라 하나의 작은 사각형으로 특정할 수 없고,
  오탐이 몰리는 우측~우상단 영역이 **실제 작업자가 서는 자리(9000·11000·12000ms GT)와 겹친다** —
  그 영역을 마스킹하면 진짜 위험을 놓칠 위험이 있어(규칙6, 저하 방향 변경은 임의 진행 금지) 이
  카메라에는 적용하지 않는다. 근본 원인은 설비 근접·클로즈업 촬영(화각 문제)으로 추정 —
  `docs/camera_requirements.md`에 관련 조항 추가함([A-2]).
- **기능 자체(마스크 존 메커니즘)는 설계안만 남긴다 — 구현하지 않음**: `config/danger_zone.json`과
  같은 패턴(카메라별 정규화 폴리곤)으로 특정 클래스의 검출만 특정 영역에서 버리는 기능. 상세 설계
  (config 포맷·안전장치·감사로그 필요성)는 `benchmarks/r2_mask_zone_review.md` §4 참고.
- **재개 조건**: **실제 현장 설치에서 고정 설비가 반복적으로 오탐을 일으키는 케이스가 확인될 때.**
  단, 000633827에서 배운 대로 착수 전 반드시 "오탐 위치가 실제 작업자 위치와 공간적으로 분리되는지"
  부터 GT나 현장 확인으로 검증할 것 — 겹치면 마스킹이 아니라 다른 접근(임계 조정·카메라 재설치
  등)을 먼저 검토.

## PK. 스냅샷 폴링 — 미연결 카메라 백오프 없음(2026-08-12, [T-E2E] 진단 중 발견)
- **무엇**: `/safety-hub`가 카메라 스냅샷을 폴링하는 주기가 워커 연결 상태와 무관하게 고정으로
  보인다 — TEST1(RTSP 미도달, `hang`)이 붙지 않는 동안 스냅샷 요청이 404를 계속 반복(빈도
  그대로) 냈다. 연결 안 된 카메라를 계속 같은 주기로 찔러봐야 응답은 항상 404뿐이라 실익 없는
  요청이 쌓인다.
- **개선 방향(미구현, 코드 안 건드림)**: 워커 `error`/`hang` 상태가 지속되면 그 카메라의 스냅샷
  폴링 간격을 점진적으로 늘리는 백오프를 프론트(`index_hub.html`)에 추가 — 연결 복구되면 즉시
  정상 주기로 복귀.
- **우선순위**: 낮음(기능 저하 아님, 순수 효율 개선) — 실카메라 배포가 늘어나 폴링 트래픽이
  실제 문제가 될 때 착수.

## PL. 테스트 스위트가 로컬 `.env`의 VIGENT_API_TOKEN에 오염됨(2026-08-12, [T-E2E] 준비 중 발견)
- **무엇**: [T-E2E] 실카메라 검증을 위해 `.env`에 `VIGENT_API_TOKEN`을 상시 설정했더니(파일럿과
  동일 조건 재현 목적), 이후 `python -m unittest discover -s tests`가 **9개 테스트에서
  401 오류로 실패**했다(`test_endpoints_smoke.py`·`test_machine_guard.py` 등 — 대다수가
  Authorization 헤더 없이 호출하는 스모크 테스트). `main.py`가 dotenv로 `.env`를 읽어
  `VIGENT_API_TOKEN`이 전역으로 채워지면서, 원래 무토큰 전제로 짜인 테스트들이 인증 미들웨어에
  막힌 것 — 회귀가 아니라 **테스트 격리 부재**(pyproject.toml/CI 어디에도 `VIGENT_API_TOKEN=`
  강제 초기화가 없음).
- **임시 우회(이번엔 이렇게 게이트 통과)**: `VIGENT_API_TOKEN= python -m unittest ...`처럼
  빈 값을 명시해 `.env`보다 우선시킴(python-dotenv는 이미 설정된 OS 환경변수를 기본적으로
  덮어쓰지 않음, `override=False`).
- **개선 방향(미구현)**: 테스트 실행 스크립트/`tests/`의 공통 setUp(또는 `conftest`격
  헬퍼)에서 `VIGENT_API_TOKEN`을 명시적으로 비우거나, 이미 토큰이 필요한 개별 테스트처럼
  각자 monkeypatch로 격리하게 통일 — 로컬에 토큰을 상시 설정해두는 사람(엣지박스 배포
  프로파일을 로컬에서 재현하는 경우, 이번처럼)이 늘어날수록 이 문제가 반복될 것.
- **우선순위**: 중(다음에 누군가 `.env`에 토큰을 설정한 채 게이트를 돌리면 똑같이 재현됨).
