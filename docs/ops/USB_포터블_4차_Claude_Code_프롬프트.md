# VIGENT — 4차 Claude Code 프롬프트 (F-34 수정 · 근골격 규칙 프로필 오프 · 포터블 화면/슬롯 수정)

> 사용법: `D:\vigent_original` 에서 Claude Code 를 열고(3차 세션이 아직 열려 있으면 그 세션에 이어서) 아래 `---` 사이의 내용을 그대로 붙여 넣는다.
> 전제: 3차 작업 1·2·4·5 완료(커밋 d9da468 · 8c24652 · 811224e · 86eb188). 작업 3(노트북 소크 판독)은 파일 대기. F-34 수정은 승인됨, 코드 미적용.

---

## 배경

- **F-34(승인)**: 포즈 스레드가 내는 `ergonomic_risk` 이벤트는 3-튜플(`worker.py:492`)인데 메인 루프는 4-튜플로 풀어(`worker.py:1098`) `ValueError` 가 나고, 그 프레임의 모든 경보(침입·PPE·화재·근접·무동작)가 기록·통보에 도달하지 못한다. 예외는 삼켜져 서버는 정상으로 보인다. 1h 소크 289회, vigent.log 9/8 21:23 이후 717회, 8월 회전 로그 20회.
- **근골격(ergonomic_risk) 운영 결정**: 학원 현장 계약 범위 밖이고 현장 보고서 §387 에 기울기 판정 오류 지적이 있다. **규칙만 프로필에서 끈다.** 포즈 스레드와 낙상 감지는 그대로 둔다(P0-3 낙상 감지 관련). 전역 기본값 불변.
- **포터블 화면**: 제3 PC 에서 USB 기동은 성공했으나 런처가 `/home`(허브)을 열어 사용자가 현장 관제 화면(`/safety-hub`, `docs/academy_visit_day.md` §A-1 "관제 대시보드 = /safety-hub")을 못 찾았다.
- **포터블 슬롯**: 포터블은 전역 config 라 forklift 잠정 비활성·fire_smoke 켜짐. 현장(학원) 프로필은 forklift 켬(yolo `forklift_boda_ax.pt` conf 0.50)·fire_smoke 끔(`deploy/academy/README_academy.md`).

네 작업을 **순서대로** 하고, 각 작업 끝에 실측 결과를 보고한 뒤 다음으로 넘어가라. 작업 1 이 끝나면 멈춰 내 확인을 받아라.

## 작업 1 — F-34 수정 적용 (승인 조건 5개)

1. `git blame` 으로 `worker.py:492`(3-튜플)와 `:1098`(4-튜플)의 불일치가 들어온 커밋·날짜를 찾아 **영향 기간**을 확정하라. 2026-08-27 현장 테스트, 노트북 1차·2차 소크, 9/8·9/9 개발기 소크가 기간 안인지 F-34 에 표로 명시하라. 기간 안이면 `reports/현장테스트_보고서_*v1.2*` 의 경보 수치와 `docs/ops/laptop_*` 의 "경보 n/p95" 에 "★F-34 유실 포함 가능" 단서만 달아라(값은 유지).
2. 수정: `fired += [(r, lv, n, "") for r, lv, n in _pose_ev]` 한 줄 + 회귀 테스트(3-튜플 포즈 이벤트가 섞여도 같은 프레임의 다른 경보가 기록 단계까지 도달하는지).
3. 그 `except … 계속 진행` 블록에서 **버려진 프레임 수·경보 수를 카운터**로 세어 `/health` 에 노출하라(예: `alerts_dropped_by_error: {frames, alerts, last_error, last_at}`). 삼키는 동작은 유지하되 보이게 만드는 것이 목적이다. `baseline_openapi.json` 과 `scripts/check_openapi_diff.py` 가 있으니 스키마 변경을 그 절차로 통과시켜라.
4. 검증: `.venv\Scripts\python -m unittest discover -s tests` → 662 + 신규 OK. 그다음 드라이런 7분(4대 · `run.ps1` 기동 · Task Scheduler 로 도구 트리 밖에서 · 사전 조건 기록 동일)에서 `ValueError` 0회, `alerts_dropped_by_error.frames == 0`, 경보가 `events.jsonl`/통보 큐까지 도달하는지 확인하라. 드라이런 전에 `data\cameras.json` 에 잔존 카메라가 없는지 확인하라.
5. `ergonomic_risk` 규칙을 **설정으로** 끌 수 있는지 확인하라(`config/tuning.yaml` · `vigent-core/hazard_rules.py` · `themes/safety/*.yaml`). 가능하면 `deploy/academy/tuning.academy.yaml` 과 `deploy/portable/portable_overrides.yaml` 에서만 끄고 전역 기본값은 유지하라. 포즈 스레드·낙상 감지는 그대로 둔다 — 끈 뒤 낙상 이벤트가 여전히 나오는지 테스트로 확인하라. 설정으로 끌 수 없으면 **최소 수정안만 제안하고 멈춰라.**

커밋 1개(F-34 수정 + 카운터 + 프로필 오프 + 문서). `docs/ops/USB_포터블_3차_Claude_Code_프롬프트.md` 와 이 4차 프롬프트 문서도 1·2차와 일관되게 같은 커밋에 넣어라. **여기서 멈추고 보고하라.**

## 작업 2 — 포터블 런처가 관제 화면을 열도록

1. `deploy/portable/` 의 `VIGENT_시작.bat` 템플릿과 `scripts/build_portable.ps1` 이 브라우저를 `/home` 이 아니라 **`/safety-hub`** 로 열게 바꿔라. 포트 폴백(8011)도 그대로 반영.
2. `/safety-hub` 가 토큰 없이(127.0.0.1 무토큰) 로그인 화면 없이 열리는지 확인하라. 토큰을 요구하면 원인(`auth_session.py`)과 선택지를 보고하고 멈춰라.
3. `사용법.md` 의 주소·화면 설명을 맞추고, "메뉴(허브)로 가려면 `/home`" 한 줄을 추가하라.

## 작업 3 — 포터블 슬롯을 현장 프로필과 맞추기

1. `portable_overrides.yaml` 에 forklift 켬 · fire_smoke 끔 · ergonomic_risk 끔(작업 1-5 결과)을 얹어라. 근거는 `deploy/academy/README_academy.md`.
2. **forklift 백엔드**: academy 프로필은 yolo(`forklift_boda_ax.pt`)라 `ultralytics` 가 필요한데 포터블 requirements 에 없다(AGPL·배포 제거 A-4). 포터블은 onnx-cpu 경로이므로 `vigent-core/weights/forklift_rfdetr_v1.onnx` 로 forklift 슬롯을 켤 수 있는지 `detectors/rfdetr_adapter.py` [C-3] 경로에서 확인하라. 가능하면 그것으로 켜고, 현장 프로필(yolo boda_ax)과 **검출기가 다르다**는 점을 `deploy/portable/README.md` 와 `사용법.md` 에 명시하라. 불가능하면 이유와 선택지(ultralytics 동봉 시 용량·AGPL 문제 포함)를 보고하고 멈춰라.
3. 검증: `demo_assets` 또는 `D:\vigent_private_data\runs\rfdetr\accident\*.mp4`(읽기만)의 지게차 장면으로 forklift 검출이 나오는지, fire_smoke 슬롯이 로드되지 않는지(`/health` 슬롯 목록), 근골격 경보가 나오지 않으면서 낙상은 나오는지 확인하라.

## 작업 4 — 포터블 재빌드 · 재검증 · USB 재복사

1. `scripts\build_portable.ps1` 재실행(멱등 — 변경분만). 용량·파일 수 보고.
2. `subst` 가상 드라이브 검증: `VIGENT_시작.bat` → `/health` ok · 슬롯 목록(person·ppe·forklift, fire_smoke 없음) · 브라우저가 `/safety-hub` 를 여는지 · `VIGENT_종료.bat` 잔존 0 · `VIGENT_데이터정리.bat` 동작. PATH 격리·인터넷 차단 기동도 1차와 같이 재확인.
3. USB 가 꽂혀 있으면(드라이브 문자는 나에게 물어라) `scripts\copy_to_usb.ps1 -Drive <문자>:` 로 재복사하고 파일 수·바이트 검증 결과를 보고하라. USB 안 `app\data`·`state\logs` 에 제3 PC 시험 때 생긴 사진이 남아 있으면 복사 전에 `VIGENT_데이터정리.bat` 을 먼저 돌려라. 꽂혀 있지 않으면 이 단계는 "사용자가 체크리스트대로 수행" 으로 남겨라.
4. 작업 2~4 를 커밋 1개로. `deploy/portable/README.md` 의 검증 결과 절을 이번 실측으로 갱신하되 "제3 PC 실기동 1회 성공(2026-09-09, 사양 미기록)" 을 사실대로 적어라.

## 보고 형식

작업마다: 실행한 명령 → 실측 결과(수치·경로·종료코드) → 합격/불합격/미검증(이유). 작업 1 후 멈춤. 작업 전후 `git status`, 최종 `git log --oneline -10`.

## 작업 규칙

- `CLAUDE.md` 를 따른다. 지어낸 수치·버전은 쓰지 않는다.
- 노트북은 접근하지 않는다. `config/`·`themes/` 전역 파일, `vigent-core/weights/`, `D:\vigent_field`, `D:\vigent_private_data` 는 읽기만.
- 서버를 띄울 때는 반드시 `run.ps1` + Task Scheduler(도구 트리 밖). 끝나면 태스크 삭제·잔존 프로세스 0 확인.
- 소크·드라이런 중 GPU 를 쓰는 다른 프로그램이 있으면 시작하지 말고 보고하라.
- 푸시하지 않는다. 막히면 우회하지 말고 원인과 선택지를 정리해 나에게 물어라.

---
