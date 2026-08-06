# PPE/person 평가용 라벨링 가이드 (data/field_eval/)

> 목적: **학습이 아니라 평가**용 정답지 제작. 이 문서 자체는 정확도 수치를 만들지 않는다(규칙7) —
> 라벨링은 사람(사용자)이 손으로 하고, 채점은 Phase 3의 별도 하네스가 한다.
> 대상 데이터: `benchmarks/extract_eval_frames.py`가 `runs/rfdetr/accident/`(재해 영상 9개)에서 뽑은
> `data/field_eval/frames/` 109장. 사전 적합성 점검은 `benchmarks/phase2_0_data_fitness.md` 참고.

## 0. 라벨 클래스 (모델과 코드로 정확히 매칭됨)

`vigent-core/agents/guard.py`(`LABEL_NORMALIZE`)·`themes/safety/vision.yaml`(ppe 슬롯 `classes:`)를
직접 확인한 표준 라벨 7개 — **이 순서·철자·대소문자·하이픈 그대로** 쓸 것(모델이 실제로 내보내는 값과
1:1 대조해야 채점이 성립한다):

```
0 person
1 Hardhat
2 NO-Hardhat
3 Safety-Vest
4 NO-Safety-Vest
5 Mask
6 NO-Mask
```

- `Safety-Vest`/`NO-Safety-Vest`는 하이픈 표기(모델 원시 출력은 공백일 수 있으나 `guard.py`가 내부적으로
  정규화 — 라벨 파일에는 표준형인 하이픈 표기를 쓴다).
- `person`은 소문자(COCO 관례, PPE 모델의 `Person`/`PERSON`도 `guard.py`가 `person`으로 통일).

## 1. Phase 2-0 점검 결과 반영 — 이번 109장의 측정 범위(고정)

라벨링 시작 전에 이미 확인된 이 데이터의 한계다. 라벨을 이 한계에 맞춰 단다(무리하게 전부 채우지 않는다):

| 클래스 | 이번 데이터로 측정 가능한 범위 |
|---|---|
| **Hardhat / NO-Hardhat** | **완전 측정**(정밀도·재현율 양쪽) — 착용 30장·미착용 49장 표본 확보(1차 육안 확인). |
| **Safety-Vest / NO-Safety-Vest** | **NO-Safety-Vest 재현율만.** 착용(Safety-Vest) 표본이 1차 확인상 0장 — Safety-Vest 오탐률(정밀도)은 "측정 불가"로 리포트에 명시한다. **라벨에는 NO-Safety-Vest만 달릴 것으로 예상**된다. (단, 라벨링 중 실제로 조끼 착용자가 보이면 정상적으로 `Safety-Vest`로 단다 — 표본이 늘면 좋은 일이다. 안 보인다고 미리 가정하고 스킵하지 말 것.) |
| **Mask / NO-Mask** | **재확인 결과(영상별 재점검) 비대칭이다** — `KakaoTalk_20260807_000632301.mp4`(자재 컨베이어 작업, person 인덱스 65~72) 8장 중 최소 6장에서 흰 마스크 착용이 육안으로 명확히 보였다(`Mask` 표본 확보). 반대로 `NO-Mask`(맨얼굴이 명확히 보이는 프레임)는 이번 재확인에서 자신 있게 특정하지 못했다 — 대부분 프레임이 측면·후면·원거리라 얼굴 자체가 안 보인다. **라벨링 중 각 프레임에서 얼굴이 보이면 마스크 유무를 그대로 판단해 달고, 얼굴이 아예 안 보이면 Mask/NO-Mask 둘 다 달지 않는다**(억지로 추정 금지). |
| **person** | height_frac(=person 박스 높이/프레임 높이, `frames_manifest.json`에 이미 기록됨) **< 0.15인 5장은 "person-only, PPE 제외"** — person 박스만 달고(식별 가능하면) PPE 박스는 안 단다. |

### 리포트 상단 고정 꼬리표 (Phase 3 채점 결과에 항상 그대로 포함)
```
주간·실내조명 기준 / 야간 미검증 / 조끼 착용 오탐 미검증 / 특정 사고영상 9종 기준(일반화 아님)
```

## 2. person 없는 13장 + person-only 5장 라벨링 규칙

- **person 없는 13장**(`frames_manifest.json`의 `size_bucket == "사람없음"`): **빈 라벨 파일**(0바이트 `.txt`)을
  그대로 만든다. 빈 라벨을 빼먹으면 "원래 없어서 안 그렸는지 라벨링을 안 했는지" 구분이 안 돼 **오탐(false
  positive) 측정이 무의미**해진다 — 반드시 포함.
- **person-only 5장**(`height_frac < 0.15`): person 박스만(식별 가능한 경우) 달고, PPE 박스는 달지 않는다.
  Phase 3 하네스는 `frames_manifest.json`의 `height_frac` 필드로 이 5장을 자동 식별해 PPE 채점에서
  제외한다 — **별도 플래그 파일을 만들 필요 없음**(중복 관리 방지).

## 3. 라벨링 도구 — 로컬 CVAT 우선 (Roboflow 등 외부 클라우드 지양)

**★개인정보 경고**: `runs/rfdetr/accident/`의 원본은 실제 사고·부상 장면을 담은 재해 영상이다. 외부
클라우드 서비스(Roboflow 등)에 업로드하면 실제 피해자로 추정되는 인물 영상이 제3자 서버에 저장된다 —
개인정보보호법상 민감할 수 있어 **지양**한다. 대신 **로컬에서 완전히 도는 CVAT**을 권장한다.

### 3-1. CVAT 로컬 설치 (Docker 필요)
1. Docker Desktop 설치·실행 확인(`docker --version`).
2. CVAT 저장소 클론: `git clone https://github.com/cvat-ai/cvat` (별도 디렉터리 — VIGENT 저장소 밖 권장).
3. `cd cvat && docker compose up -d` — 최초 실행 시 이미지 다운로드로 수 분 소요.
4. 관리자 계정 생성: `docker exec -it cvat_server python3 manage.py createsuperuser` (아이디·비번 설정).
5. 브라우저로 `http://localhost:8080` 접속 → 방금 만든 계정으로 로그인.

> **버전 주의**: CVAT은 활발히 업데이트되는 오픈소스라 위 명령이 버전에 따라 조금 다를 수 있다(정직
> 고지 — 이 문서 작성 시점 기준 일반적인 절차이며, 실행 전 CVAT 공식 저장소의 README로 최신 설치법을
> 한 번 대조할 것을 권장).

### 3-2. 프로젝트·태스크 생성 + 라벨 스키마
1. CVAT 웹 UI → **Projects → Create new project**. 이름 예: `vigent-ppe-eval`.
2. **Labels**(라벨 스키마) 추가 — 위 §0의 7개를 **그대로**(순서·철자 무관, CVAT은 이름으로 매핑) 추가:
   `person`, `Hardhat`, `NO-Hardhat`, `Safety-Vest`, `NO-Safety-Vest`, `Mask`, `NO-Mask`. 전부 **Rectangle**
   (bounding box) 타입.
3. 프로젝트 안에 **Create new task** → `data/field_eval/frames/` 안의 이미지 109장을 업로드(로컬 파일
   업로드 — 클라우드 연동 안 씀).

### 3-3. 라벨링 작업
- 이미지마다 사람이 있으면 `person` 박스, 그리고 안전모/조끼/마스크 상태에 따라 해당 클래스 박스를
  **person 박스와 겹치게** 그린다(모델이 실제로 내는 방식과 동일 — PPE 박스는 부위별로 별도 박스).
- 판단이 애매하면(가려짐·너무 작음·각도) **달지 않는다** — 억지로 추정해서 달면 정답지 자체가
  오염된다(규칙7, "모르면 모른다"는 라벨링에도 적용).
- §1·§2의 예외(빈 라벨·person-only)를 지킨다.

### 3-4. 내보내기 (YOLO 형식)
1. Task 완료 후 **Actions → Export task dataset**.
2. Export format: **YOLO 1.1**.
3. 압축 해제하면 보통 `obj_train_data/`(이미지+라벨 `.txt`)와 `obj.names`(클래스 목록)가 나온다 —
   §4의 폴더 구조로 옮겨 정리한다.

## 4. 측정 하네스가 읽을 최종 폴더 구조

```
data/field_eval/
  frames/                    이미 있음 — 원본 추출 이미지(gitignore)
  frames_manifest.json       이미 있음 — video/t_ms/bright/size_bucket/height_frac/file
  classes.txt                신규 — §0의 7줄, 순서가 class_id(0~6)를 정의
  labels/                    신규 — CVAT YOLO 내보내기 결과를 여기로
    <파일명동일>.txt          예: KakaoTalk_..._0ms.txt (frames/의 .jpg와 basename 동일)
                              한 줄 = "class_id cx cy w h"(정규화 0~1, YOLO 표준)
                              person 없는 13장은 0바이트 빈 파일
```

`classes.txt` 내용(그대로 생성):
```
person
Hardhat
NO-Hardhat
Safety-Vest
NO-Safety-Vest
Mask
NO-Mask
```

Phase 3 하네스는 `frames/<f>.jpg` ↔ `labels/<f>.txt`를 basename으로 짝짓고, `frames_manifest.json`의
`height_frac`로 person-only 5장을 자동 식별해 PPE 채점에서 제외, `classes.txt` 순서로 class_id를
클래스명으로 되돌린 뒤 `guard.detect()` 실제 출력과 IoU 매칭해 정밀도·재현율을 계산한다(다음 Phase에서
구현).

## 5. 최소 라벨량 — 지금(30/49)이면 충분한가

**일반적인 통계 어림**(이 프로젝트 실측이 아니라 이항분포 신뢰구간의 표준 근사, 95% 신뢰수준
`1.96·√(0.25/n)`)이지, 배포 정확도를 지어낸 수치가 아니다:

| 표본 수(n) | 비율 추정 오차(±, 95% 신뢰) |
|---|---|
| 10 | ±31%p |
| 30 | ±18%p |
| 50 | ±14%p |
| 100 | ±10%p |

**Hardhat(착용 30·미착용 49)**: n=30~49 구간 — "대략 이 정도"를 보는 **1차 baseline**으로는 쓸 만하지만,
±14~18%p 오차 폭이라 "재현율 92% 확보"처럼 정밀한 주장의 근거로 쓰기엔 약하다. 제품 출시 판단에
쓰려면 최소 n=50(±14%p) 이상, 가능하면 n=100+(±10%p)를 권장 — 지금은 1차 baseline으로 진행하고,
결과가 애매한 경계(예: recall 70~85% 근처)로 나오면 표본을 더 모아 재확인하는 방식을 제안한다.

**Safety-Vest**: 착용 표본 0 → 위 표 자체가 적용 불가(오차 계산의 전제인 "표본이 있음"이 성립 안 함).
**Mask**: 착용 표본 최소 6(632301 영상) — n=6이면 ±40%p대로 사실상 참고치 수준. NO-Mask는 라벨링해봐야
확보량을 알 수 있다.

## 6. 다음 (Phase 3, 미착수)
라벨링 완료(§3) 후, `benchmarks/`에 §4 폴더를 읽어 `guard.detect()` 실제 출력과 IoU 매칭해 클래스별
정밀도·재현율·오탐 표를 내는 채점 하네스를 만든다 — 지금은 만들지 않는다(라벨이 없으면 채점 불가).
