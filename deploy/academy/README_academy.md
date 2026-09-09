# 학원 현장 프로파일 적용 안내 (2026-08-19)

> 대상: 중장비 학원 방문용 노트북. **전역 기본값(저장소 `config/`·`themes/`)은 불변** —
> 이 폴더의 파일을 노트북에서 덮어써서만 적용한다.
> 근거 실측: [`benchmarks/forklift_duel_2026-08-19.md`](../../benchmarks/forklift_duel_2026-08-19.md)

## 슬롯 구성 (확정)

| 슬롯 | 상태 | 백엔드 |
|---|---|---|
| person | ✅ | rfdetr (전역과 동일) |
| **forklift** | ✅ **켬** | **yolo · `forklift_boda_ax.pt`** (G1 대결 채택 — 운용 conf 0.50) |
| ppe | ✅ | rfdetr (전역과 동일) |
| fire_smoke | ❌ **끔** | — (계약 범위 밖 + 배경 오탐 리스크) |

## 적용 절차 (노트북에서)

```powershell
# 0. 백업
copy config\tuning.yaml config\tuning.yaml.bak
copy themes\safety\vision.yaml themes\safety\vision.yaml.bak

# 1. 프로파일 덮어쓰기
copy deploy\academy\tuning.academy.yaml config\tuning.yaml
copy deploy\academy\vision.academy.yaml themes\safety\vision.yaml

# 2. YOLO 실행기 설치(⚠ boda_ax 는 ultralytics 필요 — 아래 라이선스 주의)
pip install ultralytics
# 2-1. ★필수 — ultralytics 가 GUI opencv 를 딸려와 headless 를 가린다. 즉시 되돌린다.
pip uninstall -y opencv-python opencv-contrib-python
pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.13.0.92
pip list | Select-String opencv     # headless 하나만 남아야 한다

# 3. 가중치 확인(forklift_boda_ax.pt 포함 10종)
python scripts\fetch_weights.py --all

# 4. 재기동 후 검증
#    /health 슬롯에 forklift(yolo·boda_ax) LOADED, fire_smoke 워커 미호출 확인
```

**되돌리기**: `.bak` 2개를 원위치 + 재기동.

## 검증(적용 후 스모크)

- `/health` → `backend` 에 `forklift: yolo` 확인
  > ★[2026-08-20 정정] `/health` 에 **`slots` 키는 없다**. 실제로 볼 곳은 `backend` 맵이다.
  > 또 `rfdetr_slots` 의 forklift 항목은 `backend=yolo` 인데 `weights` 로
  > **`forklift_rfdetr_v1.pth`** 를 보여준다 — 오탑재가 아니라 *rfdetr 가중치 존재검사(F-8)*
  > 결과라서 그렇다. yolo 백엔드가 실제로 쓰는 `forklift_boda_ax.pt` 는 `models` 목록에서 확인한다.
  > ★**`disabled_detectors` 에 `forklift` 가 계속 남아 있는 것은 `/health` 하드코딩 표기 결함이다**
  > (`vigent-core/routers/system.py`) — `detect.include_forklift: 1` 을 반영하지 않는다.
  > 학원 프로파일에서 지게차는 **실제로는 활성**이다(`worker.py:_default_detectors`).
- 지게차 영상 파일 카메라 등록 → 오버레이에 `forklift 0.9x` 박스 확인
- proximity 는 변경 불필요 — boda 라벨이 `forklift` 라 기준자(`vehicle_ref_m.forklift: 2.5`)가
  그대로 정확하다(COCO 대용이었다면 필요했을 truck 오버라이드 불필요)
- ★[2026-09-10 배포 전 확인] 근골격 규칙 OFF(`vision.academy.yaml` 의 `joints` → `joints_off_academy`, F-34) 상태에서 **브라우저 자세 화면(`ergonomics.js`, `/vision` raw 를 읽음)이 정상 동작하는지** 확인.
  워커 쪽은 `ErgonomicsTracker` 비활성으로 확인됐으나(tests/test_worker_pose_event_tuple_f34.py ④) 프론트는 실기동 미확인 — 코드 읽기(`vigent-core/static/ergonomics.js:41 setConfig`: `c.joints` 가 없으면 **내장 기본값(DEFAULT)으로 계속 동작**)로는 화면이 깨지지 않고 브라우저 쪽 자세 판정만 기본 임계로 돈다. 배포 전 브라우저에서 한 번 열어 확인.
- ★[2026-09-10 배포 전 필수] 텔레그램 통보 401(F-35) — 새 봇 토큰·chat_id 로 테스트 전송 1건 성공 + `/health alerts.dead_1h == 0` 확인. 이 상태로 배포하면 경보가 기록만 되고 아무에게도 가지 않는다.

## ⚠ 한계·조건 (판정문 그대로)

1. **이 채택은 "학원 유사 영상 기준"이다** — 판정 근거는 학원 실습장과 유사한 조건의
   휴대폰 영상 1편(160초·320프레임)이며, 학원 CCTV 화각·해상도에서의 재검증은
   방문 당일 절차서 3단계에서 한다. salvage 드라이브 도착 시 LOCO 평가 분할본으로
   교차 검증을 추가한다.
2. **ultralytics 는 AGPL 이다** — 파일럿 시험 사용에 한정한다.
   ★**상용 배포 전 지게차 RF-DETR 재학습으로 대체한다(불변 방침)** — boda_ax 는
   그때까지의 임시 채택이다.
3. fire_smoke 를 껐으므로 화재 감지는 이 프로파일에서 동작하지 않는다(의도된 것).
