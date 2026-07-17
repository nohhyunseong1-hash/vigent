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
| B4 | rig_monitor 배선 여부 결정 | 중(제품) | 중(실영상 필요) | P1-10·F-13 |
| B5 | worker 반환 타입힌트 보강(28) | 낮~중 | 낮음 | P2-12 |
| B6 | vlm_text 헬퍼 미적용 11곳 | 낮 | 낮음 | P1-6 |
| B7 | ml/rfdetr_zone_track 중복 제거 | 낮 | 낮음 | P2-11 |

기존 다른 트랙의 백로그(참조)는 맨 아래 별도.

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
- **왜 미뤘나**: P1-10은 "미배선 상태 명시(docstring+ONBOARDING)"까지만 했음. 핵심 경보(하물 높이) 실영상 검증이 **적합 footage(근접 카메라 인양 1사이클) 확보 대기**(F-13: 광역 CCTV는 하물/후크 미가시, 작업자 26~64px).
- **리스크**: 중. 검증 없이 배선하면 "동작한다" 오주장 위험(규칙 7). footage 확보가 선결.
- **권장 접근**: 적합 footage 확보 → 실영상으로 상태기계 검증 → 통과 시 배선(가산 신호로만), 실패 시 미배선 유지. 근거 없이 제품 기능으로 표기 금지.

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
