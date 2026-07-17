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
| **B8** | **쓰러진/저자세 사람 검출 개선**(rig (b) fall obs 신뢰성) | **높음(제품)** | 중 | B4 검증 |
| **B9** | **구역-타일링 검출 강화**(광역 CCTV 소형객체 recall↑) — B8 부산물 | 중(제품) | 낮음 | B8 실측 |
| B5 | worker 반환 타입힌트 보강(28) | 낮~중 | 낮음 | P2-12 |
| B6 | vlm_text 헬퍼 미적용 11곳 | 낮 | 낮음 | P1-6 |
| B7 | ml/rfdetr_zone_track 중복 제거 | 낮 | 낮음 | P2-11 |

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
- **다음(재검토 필요·미착수)**: ① (d) fallen-person fine-tune(해상도 한계 잔존·불확실) ② 시간단서(정적/사라짐) 단독 실측(미측정) ③ **근본: rig 작업역 근접·고해상 카메라**(F-13과 동일 결론) ④ 스코프 다운(하드알람 대신 저신뢰 어드바이저). → **rig (b) 라이브 배선은 계속 보류.**

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
- **권장 접근**: rig 낙상과 분리해 독립 추진. `guard.detect`/`worker` 에 "위험구역 내부만 타일 재검출 → 침입 판정 보강" 가산 경로. 착수 전 zone_intrusion recall 개선치·핫패스 비용 실측.

## B5. worker 반환 타입힌트 보강(28개) — [낮~중]
- **무엇**: `worker.py`의 미힌트 함수 28개에 반환 타입 부여(현재는 '관대' 모드로 본문만 검사).
- **왜 미뤘나**: P2-12에서 `_setup_run`(9-tuple)·`persons`/`_person_metrics`(numpy)·캡처(`cv2.VideoCapture`) 등 여러 함수가 **정확 타입에 Any가 불가피** → 규칙4(Any 남발 금지)로 반환힌트 강제를 제외하고 body-check만 편입.
- **리스크**: 낮음(힌트만, 동작 불변). 단 numpy(`np.ndarray`)·cv2 반환은 `TYPE_CHECKING` import + Protocol/별칭 설계 필요.
- **권장 접근**: 정확 타입이 명확한 함수부터 점진 부여(`__init__ -> None` 등) → 명확해지면 worker를 strict override로 승격. numpy/cv2 반환은 타입 별칭 도입 후.

## B6. vlm_text 헬퍼 미적용 11곳 — [낮]
- **무엇**: P1-6에서 만든 `rfdetr_service.vlm_text()`(텍스트 요약 흡수) 미적용 소비처 — `summarize_bgr` 직접 호출이 남은 곳(behavior.py·scene_vlm.py·vlm_confirm.py·incident.py·routers/office·safety_core·detect 등).
- **왜 미뤘나**: P1-6은 "텍스트형 사이트에만 적용"으로 종결(`60eaa04`). 나머지는 **dict(구조화) 반환이 필요한 소비처**라 `str|None` 반환의 vlm_text로는 못 흡수 — 의도적 범위 제외.
- **리스크**: 낮음. 무리한 통합은 오히려 저하.
- **권장 접근**: dict 반환이 필요한 곳을 흡수할 `vlm_dict()` 류 2차 헬퍼가 정말 중복을 줄이는지 먼저 검토 후, 이득이 분명할 때만.

## B7. ml/rfdetr_zone_track.py 중복 comprehension 제거 — [낮]
- **무엇**: `ml/rfdetr_zone_track.py:38`의 "zone json → (x,y) 튜플" comprehension이 `web_util._zone_points`와 중복.
- **왜 미뤘나**: P2-11에서 `web_util._zone_points`로 통합했으나, 주변 ml 스크립트에 `web_util`(→fastapi·app_state)을 끌어들이지 않으려 이 파일은 제외.
- **리스크**: 낮음.
- **권장 접근**: 순수 헬퍼 `_zone_points`를 **의존 없는 경량 모듈**(예: `zone_util.py`)로 분리하고, worker·rfdetr_service·ml·web_util 4곳이 그걸 재사용. fastapi 유입 없이 완전 통합 달성.

---

## 참조 — 다른 트랙의 기존 백로그(P0~P2 범위 밖)
이 라운드에서 새로 만든 건 아니나, 스캔 중 발견돼 누락 방지 차 링크만 남긴다.
- **라이브 추적 계층 검증**: 낱장 mAP로 안 잡히는 추적 고유 실패(ID 스위치·유령추적) 연속프레임 회귀 — FINDINGS F-8 백로그([RELEASES.md](../RELEASES.md)·[COMMERCIAL_AUDIT.md](../COMMERCIAL_AUDIT.md)).
- **문서 커버리지 확장(A-SPRINT Phase 2)**: 위험성평가서 외 관리체계·TBM·아차사고 생성기 — 골든셋·감사 이후([AGENT_STATUS.md](../AGENT_STATUS.md)).
- **pose 매니페스트 legacy 정리**: `yolov8n-pose.pt`(구 포즈 백엔드) 항목 잔존(런타임 무영향) — 실제 백엔드 RTMPose.
