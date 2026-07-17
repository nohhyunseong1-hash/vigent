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
| B2 | 런타임 가변 config 파일 격리 | 중 | 중(설계 변경) | danger_zone 조사·08fa161 |
| B3 | web_util 언더스코어 prefix 정리 | 중 | 낮음 | P1-7 |
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
- **무엇**: `config/danger_zone.json`·`config/machine_zone.json` 등 **런타임에 앱이 덮어쓰는 파일이 git 추적 대상**이라, UI로 위험구역을 그릴 때마다 워킹트리가 더러워지고 실수로 커밋에 섞인다(계속 churn).
- **왜 미뤘나**: 이번 세션 조사 결과 danger_zone.json 오염은 **런타임 정상 동작**(UI에서 `POST /zone/danger`로 구역 편집)이 원인 — 테스트 버그 아님(자동화는 `/zone/machine`만 만지고 원복). 즉 tmp 격리 같은 테스트 수정으로 풀 문제가 아니라 **구조 문제**. 이전 커밋 `08fa161`도 "런타임 가변 파일이 git 추적 대상인 구조 자체를 재검토" 라고 백로그로 남김.
- **리스크**: 중. 저장 경로를 바꾸면 기존 UI/워커의 zone 로드 경로도 함께 옮겨야 함(저하 없이).
- **권장 접근**: 런타임 zone write 대상을 `data/`(gitignore) 하위로 분리하고, `config/*.json`은 **읽기전용 기본값(시드)**로만 둠. vision.yaml zones 매핑을 data 경로로 바꾸되, 시드가 없으면 config 기본값을 복사하는 폴백. 착수 전 저하 없음 계획 보고 필수.

## B3. web_util 언더스코어 prefix 정리 — [중]
- **무엇**: P1-7 분할 때 `web_util`로 옮긴 공용 헬퍼들의 `_` prefix(예: `_tpl`·`_zone_get`·`_product_version`)를 공개 API 이름으로 정리(_제거).
- **왜 미뤘나**: P1-7은 **move-only** 원칙이라 이름을 그대로 유지("공개 API 정리는 분할 완료 후 별도" — [web_util.py](../vigent-core/web_util.py) 헤더 주석). 분할이 끝났으니 이제 착수 가능.
- **리스크**: 낮음(순수 rename). 다만 import 하는 모든 모듈(routers·worker·rfdetr_service·main)을 일괄 갱신해야 하고, mypy·ruff·체커로 회귀 확인.
- **권장 접근**: 헬퍼별로 `_x → x` rename + 전 호출부 일괄 치환 커밋. 한 번에 몰지 말고 몇 개씩. 게이트(mypy·ruff·55 tests·체커) 유지.

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
