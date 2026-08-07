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

> **⚠️ 2026-08 갱신(규칙7 — 정직 고지)**: `frames_manifest.json`의 person 크기 버킷(`size_bucket`/
> `height_frac`)이 track_key 재사용 버그(`extract_eval_frames.py`, `track_key="eval_extract"`를 109장
> 전체에 재사용해 무관한 이미지 사이에 트랙이 이어붙던 문제, 실측 확인·`benchmarks/
> recompute_frame_metadata_diff.md`)로 오염돼 있었다. `detect_isolated()`로 격리 재계산 완료 —
> **"사람없음"이 구값 13장 → 신값 28장으로 변경**(원거리 22→19, 근거리 74→62). 아래 §2의 "13장"은
> **28장**으로 갱신됐다. 이 표의 Hardhat/Mask 육안 tally(30/49 등)는 **구 96장(=109-13) 기준으로 수행된
> 것**이라 신 81장(=109-28) 기준으로는 재검증이 안 됐다 — 라벨링 중 실제 분포로 자연히 갱신된다(아래
> "의도한 층화가 아니라 실제 분포" 원칙 참고).

라벨링 시작 전에 이미 확인된 이 데이터의 한계다. 라벨을 이 한계에 맞춰 단다(무리하게 전부 채우지 않는다):

| 클래스 | 이번 데이터로 측정 가능한 범위 |
|---|---|
| **Hardhat / NO-Hardhat** | **완전 측정**(정밀도·재현율 양쪽) — 착용 30장·미착용 49장 표본 확보(1차 육안 확인, **구 96장 기준 — 위 갱신 고지 참고**). |
| **Safety-Vest / NO-Safety-Vest** | **NO-Safety-Vest 재현율만.** 착용(Safety-Vest) 표본이 1차 확인상 0장 — Safety-Vest 오탐률(정밀도)은 "측정 불가"로 리포트에 명시한다. **라벨에는 NO-Safety-Vest만 달릴 것으로 예상**된다. (단, 라벨링 중 실제로 조끼 착용자가 보이면 정상적으로 `Safety-Vest`로 단다 — 표본이 늘면 좋은 일이다. 안 보인다고 미리 가정하고 스킵하지 말 것.) |
| **Mask / NO-Mask** | **재확인 결과(영상별 재점검) 비대칭이다** — `KakaoTalk_20260807_000632301.mp4`(자재 컨베이어 작업, person 인덱스 65~72) 8장 중 최소 6장에서 흰 마스크 착용이 육안으로 명확히 보였다(`Mask` 표본 확보). 반대로 `NO-Mask`(맨얼굴이 명확히 보이는 프레임)는 이번 재확인에서 자신 있게 특정하지 못했다 — 대부분 프레임이 측면·후면·원거리라 얼굴 자체가 안 보인다. **라벨링 중 각 프레임에서 얼굴이 보이면 마스크 유무를 그대로 판단해 달고, 얼굴이 아예 안 보이면 Mask/NO-Mask 둘 다 달지 않는다**(억지로 추정 금지). |
| **person** | height_frac(=person 박스 높이/프레임 높이, `frames_manifest.json`, **격리 재계산 반영됨**) **< 0.15인 5장은 "person-only, PPE 제외"**(구 5장과 파일 목록이 다름 — `recompute_frame_metadata_diff.md` 참고) — person 박스만 달고(식별 가능하면) PPE 박스는 안 단다. |

### 원칙 — "의도한 층화 분포"가 아니라 "실제 분포"를 쓴다
`frames_manifest.json`의 밝기·크기 버킷은 추출 스크립트가 계산한 **참고 분류**일 뿐, 라벨링 결과를
이 분류에 강제로 맞추지 않는다. 격리 재계산으로도 실측 person 존재 여부는 사람이 라벨링하며 최종
확정된다 — 버킷 값이 틀렸으면(예: "원거리"인데 실제로 사람이 잘 보임) 라벨링 결과가 진실이고
버킷 표시는 참고용으로만 남긴다.

### 리포트 상단 고정 꼬리표 (Phase 3 채점 결과에 항상 그대로 포함)
```
주간·실내조명 기준 / 야간 미검증 / 조끼 착용 오탐 미검증 / 특정 사고영상 9종 기준(일반화 아님)
```

## 2. person 없는 28장(구값 13장) + person-only 5장 라벨링 규칙

- **person 없는 28장**(`frames_manifest.json`의 `size_bucket == "사람없음"`, **격리 재계산값 — 구값
  13장에서 갱신됨**, 목록은 `benchmarks/recompute_frame_metadata_diff.md`): **빈 라벨 파일**(0바이트
  `.txt`)을 그대로 만든다. 빈 라벨을 빼먹으면 "원래 없어서 안 그렸는지 라벨링을 안 했는지" 구분이 안 돼
  **오탐(false positive) 측정이 무의미**해진다 — 반드시 포함. **단, 이것도 참고 분류일 뿐이다** — 검수
  중 실제로 사람이 보이면 당연히 person 박스를 단다(위 원칙 참고).
- **person-only 5장**(`height_frac < 0.15`, 격리 재계산값): person 박스만(식별 가능한 경우) 달고, PPE
  박스는 달지 않는다. Phase 3 하네스는 `frames_manifest.json`의 `height_frac` 필드로 이 5장을 자동
  식별해 PPE 채점에서 제외한다 — **별도 플래그 파일을 만들 필요 없음**(중복 관리 방지).

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

### 3-3. 사전라벨 초안 불러오기 (0부터 그리지 않는다 — 검수 작업으로 시작)

`benchmarks/generate_prelabels_draft.py`(자체모델 RF-DETR person+ppe, conf=0.10 "과다생성" 의도)가
이미 초안을 만들어 뒀다 — **이 초안은 정답이 아니라 검수 대상**이다(규칙7, §3-3b 참고).

- `data/field_eval/labels_draft/<파일명>.txt` — YOLO 형식 초안(§4 클래스 순서 그대로).
- `data/field_eval/labels_draft_preview/<파일명>.jpg` — 초안 박스+클래스+conf를 그린 미리보기. **CVAT을
  열기 전에 이 폴더를 먼저 쭉 훑어보면** 어떤 프레임에 박스가 몰려있는지/비어있는지 감이 잡힌다.
- `benchmarks/generate_prelabels_draft_summary.md` — 프레임별·클래스별 초안 박스 집계, 박스 0개 프레임
  목록.

**⚠️ 현재 환경 한계(2026-08-07 확인)**: 이 초안은 desktop 환경에서 생성됐는데, 이 환경엔 PPE 파인튜닝
가중치가 없어(`VIGENT_ALLOW_FALLBACK=1`이 COCO로 대체) **PPE 클래스(Hardhat 등) 초안이 0건**이다 —
`person` 초안(415개, 109장 중 104장에 박스 있음)만 유효하다. PPE 가중치가 있는 환경(맥 등)에서
재실행하기 전까지는 PPE 박스를 **처음부터 직접(초안 없이)** 그려야 한다. 재실행하면
`labels_draft/`가 갱신되니 그때 이 문단은 지운다.

**CVAT에 초안을 불러오는 법**: Task 생성 시 이미지 업로드만 하고, 라벨은 **Upload annotations**
(Task 메뉴 → Actions → Upload annotations → format: **YOLO 1.1**)로 `labels_draft/`(+`classes.txt`를
`obj.names`로 리네임한 사본)를 업로드하면 각 이미지에 초안 박스가 미리 그려진 채로 열린다 — 검수자는
그리기가 아니라 "지우기·고치기" 작업을 하게 된다(의도된 워크플로, conf=0.10 과다생성의 목적).

### 3-3b. 검수 체크리스트 (프레임마다, 반드시 이 순서로)

1. **잘못 잡은 박스 삭제** — 사람이 아닌데 person으로 잡혔거나, PPE가 아닌 걸 PPE로 잡은 초안 박스.
2. **클래스 오류 수정** — 예: Hardhat인데 NO-Hardhat으로 잡힌 경우(착용/미착용 반전은 특히 조심).
3. **박스 경계 보정** — 대상을 살짝 벗어나거나 너무 크게/작게 잡힌 초안 박스를 정확히 맞춘다.
4. **★별도 1회 패스 — 박스가 하나도 없는 사람이 있는지만 훑기.** 이게 (b)방법(자체모델 초안)의
   유일한 구조적 맹점이다 — 우리 모델이 아예 놓친 사람은 초안에 없어서 위 1~3번 작업(있는 박스
   고치기)만 해서는 절대 못 잡는다. **`generate_prelabels_draft_summary.md`의 "박스 0개 프레임 목록"
   (5장)부터 먼저 확인**하고, 그다음 나머지 104장도 "초안에 없는 사람이 화면에 있는가"만 보는 별도
   패스로 한 번 더 훑는다. person 박스를 추가로 그렸으면 그 사람의 PPE 상태도 마저 판단해서 단다.
5. **person 없는 13장은 빈 라벨 유지** — 초안도 이미 빈 파일이지만, 검수 중 실수로 뭔가 그리지 않았는지
   확인만 한다(§2 참고).
6. **애매하면 라벨 달지 말고 해당 프레임을 제외 목록에 기록** — `docs/labeling_exclusions.md`(없으면
   새로 만들어) 같은 곳에 "파일명 + 왜 제외했는지" 한 줄로 남긴다. 억지로 단 라벨보다 "이 프레임은
   판단 보류"가 정답지 품질에 낫다(규칙7).

### 3-4. 검수 완료본 내보내기 → labels/ (labels_draft/는 보존)

1. CVAT에서 검수(수정) 완료 후 **Actions → Export task dataset**, format **YOLO 1.1**.
2. 압축 해제하면 보통 `obj_train_data/`(이미지+라벨 `.txt`)와 `obj.names`가 나온다.
3. **검수 완료된 라벨 `.txt`만 `data/field_eval/labels/`로 옮긴다** — `labels_draft/`는 **지우지 말고
   그대로 둔다**(정답지가 어디서 왔는지 추적용 — "자체모델 초안 X% 그대로 채택 / Y% 수정"을 나중에
   `labels_draft/`와 `labels/`를 diff해서 잴 수 있다).
4. **최종 리포트에 반드시 명기**: `정답지 출처: 자체모델(RF-DETR person+ppe) conf=0.10 초안 + 사람
   전수 검수`. 검수 전 초안을 그대로 채점에 쓰지 않는다(규칙7 — 검수 없이 쓰면 "정확도"가 아니라
   "다른 모델과의 일치율"이 되어버린다).

## 4. 측정 하네스가 읽을 최종 폴더 구조

```
data/field_eval/
  frames/                     이미 있음 — 원본 추출 이미지(gitignore)
  frames_manifest.json        이미 있음 — video/t_ms/bright/size_bucket/height_frac/file
  classes.txt                 있음 — §0의 7줄, 순서가 class_id(0~6)를 정의
  labels_draft/                자체모델 conf=0.10 초안(YOLO txt) — 검수 전, 정답 아님. 지우지 말 것(§3-4).
  labels_draft_preview/        초안 박스 그린 미리보기 jpg(검수 참고용, 채점엔 미사용)
  labels/                     신규 — §3-4 검수 완료본을 여기로(CVAT YOLO 내보내기 결과)
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
