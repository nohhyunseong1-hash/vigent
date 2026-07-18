# VIGENT P3 백로그 (P0~P2 완료 후 후속 항목)

> 작성 기준: 2026-07-16 · P0~P2 라운드 완료 시점.
> 이 문서는 P0~P2 작업 중 **"후속 항목으로 기록"하기로 미룬 것들**을 우선순위·리스크와 함께 모은다.
> 각 항목은 왜 그때 미뤘는지(출처)를 함께 적어, 착수 시 맥락을 잃지 않게 한다.
> 원칙(CLAUDE.md): 저하 없는 방향으로만, 착수 전 계획 보고, 근거 있는 것만.

---

## 우선순위 한눈

| # | 항목 | 우선순위 | 리스크 | 출처 |
|---|---|---|---|---|
| ~~B1~~ | ~~CI 첫 실행 green 실검증~~ ✅ 완료 | — | — | run #2 green(4m 1s) |
| ~~B2~~ | ~~런타임 가변 config 파일 격리~~ ✅ 완료 | — | — | runtime_config.py |
| ~~B3~~ | ~~web_util 언더스코어 prefix 정리~~ ✅ 완료 | — | — | 공개함수 12개 rename |
| B4 | rig_monitor 배선 — 상태기(b) 검증완료, 배선은 B8 의존 | 중(제품) | 중 | P1-10·F-13 |
| ~~B8~~ | ~~쓰러진/저자세 사람 검출 개선~~ ⛔ 종결(해상도 한계) — 검출강화는 B9로 | — | — | 실측 4R |
| ~~B9~~ | ~~구역-타일링 검출 강화~~ ✅ 구현완료(기본 off, VIGENT_ZONE_TILE) | — | — | 커밋 ①②③ |
| B5 | worker 반환 타입힌트 보강(28) | 낮~중 | 낮음 | P2-12 |
| B6 | vlm_text 헬퍼 미적용 11곳 | 낮 | 낮음 | P1-6 |
| ~~B7~~ | ~~ml/rfdetr_zone_track 중복 제거~~ ✅ 완료(zone_geom 순수모듈) | — | — | P2-11 |

기존 다른 트랙의 백로그(참조)는 맨 아래 별도.

<a id="b8"></a>
## B8. 쓰러진/저자세 사람 검출 개선 — [높음·제품]
- **문제**: rig_monitor ALARM (b)는 `fall` obs 에 의존하고, fall 은 person 박스를 입력받는 FallTracker 가 만든다. 그런데 광역 CCTV·작은 작업자(F-13)·쓰러진 저자세에서 **person 검출이 실패** → fall obs 못 만듦 → (b) 경보 안 뜸.
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
- **운영 가이드**: `VIGENT_ZONE_TILE=1` 로 활성, `VIGENT_ZONE_TILE_EVERY=N`(CPU면 N≥4 또는 GPU 권장). 활성 전 현장 오탐·핫패스 비용 실측. (재사용 확장: proximity·crowd 등 다른 소형객체 기능에도 동일 헬퍼 적용 가능 — 후속.)

## B5. worker 반환 타입힌트 보강 — ✅ 부분완료(2026-07-17)
- **한 것**: worker 미힌트 함수 **29→13** (16개에 힌트 부여, 동작 불변). numpy 는 이미 최상위 import 라 `np.ndarray` 직접 사용. mypy 0·ruff 0·76 tests.
  - 부여: `_point_in_poly`·`_frame_to_dataurl`·`_person_metrics`/`gp`(np.ndarray)·`persons`·`read_latest`(tuple)·`FallTracker/ErgonomicsTracker.update`(반환)·`_PoseModel`/`FallTracker`/`MotionTracker`/`ErgonomicsTracker.__init__ -> None`(+ `self._m: Any`·`self._tracks: list` 변수annotation).
- **잔여 13개(불가피 — 그대로 둠, 사유)**:
  - **cv2.VideoCapture 경로(스텁 없음 → Any + None→객체 재대입)**: `_open`·`_setup_run`(9-tuple w/ cv2)·`_loop`(cap 재접속 재대입)·`Worker.__init__`(self._cap)·`_StreamCapture.__init__/start/_run/stop`. 반환/변수 힌트를 붙이면 mypy 가 해당 함수를 typed 승격 → `cap=None`(None추론)↔`cv2.VideoCapture` 재대입 충돌. cv2 는 스텁이 없어(전역 `disable_error_code=import-untyped`) 깨끗한 해결 불가.
  - **_FrameCtx.__init__**: 파라미터를 타이핑하면 그 호출부 `_setup_run`(cv2 캡처 함수)가 strict 로 승격돼 위 cap 충돌을 유발(cascade) → 미타이핑 유지.
  - **guard(에이전트, 느슨한 덕타입) 인자**: `_process_frame`·`_run_supervised`·`_hang_watch`. guard 는 깨끗이 import 가능한 타입이 없어(Protocol 도입 전) Any → 보류.
  - `WorkerManager.__init__` — 위 그룹과 함께 남김(경미).
- **결론(규칙4·무리하지 말 것)**: 나머지는 cv2 스텁 부재·guard 덕타입이라 억지 Any/type:ignore 를 쓰지 않고 lenient(본문검사)로 유지. worker strict 승격은 **cv2 타입 스텁 or guard Protocol 도입 후** 재개.

## B6. vlm_text 헬퍼 미적용 11곳 — [낮]
- **무엇**: P1-6에서 만든 `rfdetr_service.vlm_text()`(텍스트 요약 흡수) 미적용 소비처 — `summarize_bgr` 직접 호출이 남은 곳(behavior.py·scene_vlm.py·vlm_confirm.py·incident.py·routers/office·safety_core·detect 등).
- **왜 미뤘나**: P1-6은 "텍스트형 사이트에만 적용"으로 종결(`60eaa04`). 나머지는 **dict(구조화) 반환이 필요한 소비처**라 `str|None` 반환의 vlm_text로는 못 흡수 — 의도적 범위 제외.
- **리스크**: 낮음. 무리한 통합은 오히려 저하.
- **권장 접근**: dict 반환이 필요한 곳을 흡수할 `vlm_dict()` 류 2차 헬퍼가 정말 중복을 줄이는지 먼저 검토 후, 이득이 분명할 때만.

## B7. ml/rfdetr_zone_track.py 중복 comprehension 제거 — ✅ 완료(2026-07-17)
- **한 것**: `zone_points` 를 **의존 없는 순수 모듈 `zone_geom.py`** 로 분리(fastapi/app_state 무관).
  - web_util: `def zone_points` 제거 → `from zone_geom import zone_points`(재export, worker·rfdetr_service 는 여전히 `from web_util import zone_points` 로 무변경).
  - ml/rfdetr_zone_track: `sys.path` 에 vigent-core 추가(worker._PoseModel 과 동일 기존 패턴) → `from zone_geom import zone_points` 로 인라인 comprehension 대체.
- **결과**: worker·rfdetr_service·web_util·ml **4곳이 단일 순수 함수 공유**, fastapi 유입 0. zone_geom mypy strict 편입.
- **게이트**: ruff 0 · mypy 20파일 0 · 76 tests · OpenAPI 106 · 순환 0.

---

## 참조 — 다른 트랙의 기존 백로그(P0~P2 범위 밖)
이 라운드에서 새로 만든 건 아니나, 스캔 중 발견돼 누락 방지 차 링크만 남긴다.
- **라이브 추적 계층 검증**: 낱장 mAP로 안 잡히는 추적 고유 실패(ID 스위치·유령추적) 연속프레임 회귀 — FINDINGS F-8 백로그([RELEASES.md](../RELEASES.md)·[COMMERCIAL_AUDIT.md](../COMMERCIAL_AUDIT.md)).
- **문서 커버리지 확장(A-SPRINT Phase 2)**: 위험성평가서 외 관리체계·TBM·아차사고 생성기 — 골든셋·감사 이후([AGENT_STATUS.md](../AGENT_STATUS.md)).
- **pose 매니페스트 legacy 정리**: `yolov8n-pose.pt`(구 포즈 백엔드) 항목 잔존(런타임 무영향) — 실제 백엔드 RTMPose.
