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

## 2-1. [K] 파일럿 20장 우선 — 109장 전수 검수 전에 (2026-08-07 신설)

**전수(109장, 초안 박스 1,574개) 검수는 3~4시간 이상 걸린다. 판독 규칙이 검수 중간에 바뀌면 이미 본
프레임을 처음부터 다시 봐야 한다.** 그래서 아래 순서를 강제한다:

1. **20장 파일럿부터** — 목록·선정 근거는 `docs/pilot20_frames.md`(무작위가 아니라 사람없음 오탐 5·
   Safety-Vest 5·근거리 5·원거리 5로 의도적으로 구성, 9개 원본 영상 전부 포함). CVAT 태스크도
   `docs/pilot20_frames.md` §3의 절차대로 이 20장만 별도 태스크로 먼저 만든다.
2. 20장을 보면서 아래 §3-3c(판독 규칙 초안)를 확정하고, §3-3d(조끼 오탐 계수표)를 채운다.
3. **파일럿 완료 후 반드시 보고하고 멈춘다** — 소요시간·확정 규칙·89장 예상 시간·재검토 필요 항목
   (`docs/pilot20_frames.md` §4 항목). **사용자 승인 후에만** 나머지 89장에 착수한다.

이미 확정된 §0~§2의 규칙(클래스 스킴·person 없는 28장은 빈 라벨·person-only 5장은 PPE 생략)은
파일럿에서도 그대로 적용한다 — 파일럿이 새로 정하는 건 §3-3c의 5개 판독 기준뿐이다.

## 3. 라벨링 도구 — 로컬 CVAT 우선 (Roboflow 등 외부 클라우드 지양)

**★개인정보 경고**: `runs/rfdetr/accident/`의 원본은 실제 사고·부상 장면을 담은 재해 영상이다. 외부
클라우드 서비스(Roboflow 등)에 업로드하면 실제 피해자로 추정되는 인물 영상이 제3자 서버에 저장된다 —
개인정보보호법상 민감할 수 있어 **지양**한다. 대신 **로컬에서 완전히 도는 CVAT**을 권장한다.

### 3-1. CVAT 로컬 설치 (Docker 필요)

**★2026-08-07 이 데스크탑에서 실제로 완료됨** — 아래는 추정 절차가 아니라 실행해서 동작을 확인한
명령이다(규칙7). `D:\cvat` 에 클론, Docker Desktop(WSL2 backend) 설치, 컨테이너 18개 `Up` 확인,
`http://localhost:8080` 로그인 성공, 왕복 테스트 20/20 통과까지 검증됨.

1. Docker Desktop(WSL2 포함) 설치 → `docker --version` + `docker run hello-world` 로 데몬 동작 확인.
   (WSL2 미설치면 **관리자 PowerShell**에서 `wsl --install` 후 재부팅이 먼저 필요하다.)
2. CVAT 저장소 클론: `git clone https://github.com/cvat-ai/cvat` (별도 디렉터리 — VIGENT 저장소 밖. 이 환경은 `D:\cvat`).
3. `cd D:\cvat` → `docker compose pull` → `docker compose up -d` (이미지 약 10개, 최초 수 분 소요).
   PowerShell 은 `&&` 를 못 쓰므로 줄을 나누거나 `;` 로 연결한다.
4. 관리자 계정 생성: `docker exec -it cvat_server python3 ~/manage.py createsuperuser`
   (**`~/manage.py`** — 경로에 `~/` 가 필요하다. `manage.py` 만 쓰면 실패.)
5. 브라우저로 `http://localhost:8080` 접속 → 방금 만든 계정으로 로그인.
6. 정지는 `docker compose stop`(데이터 보존), 컨테이너 삭제까지는 `docker compose down`(볼륨은 유지).

> **버전 주의**: CVAT은 활발히 업데이트되는 오픈소스라 위 명령이 버전에 따라 달라질 수 있다.
> 위 절차는 2026-08-07 시점 `cvat/server:dev` 기준으로 실제 동작을 확인한 것이다.
>
> **★태스크 생성·import·export 는 웹 UI 대신 스크립트 권장**: `benchmarks/cvat_setup_pilot.py`
> (`setup`/`inspect`/`roundtrip`/`export`)가 REST API로 같은 일을 하되 라벨 순서 검증과 덮어쓰기 전
> 백업까지 자동으로 한다. 절차·단축키는 `data/field_eval/pilot20/README.md` 참조.
>
> **★왕복 테스트를 먼저 통과시킬 것(2026-08-07 통과 확인)**: 진짜 검수 전에 "현재 정답지를 import →
> 무수정 export → 원본과 비교"를 돌려 클래스 순서·좌표 변환이 깨지지 않는지 확인한다.
> `python benchmarks/cvat_setup_pilot.py roundtrip` → **20/20 파일 완전 일치**여야 통과
> (비교 로직은 `benchmarks/cvat_roundtrip_check.py`).
>
> **★latency 측정 주의(2026-08 신설)**: Docker Desktop이 떠 있으면 CPU 전용 torch 추론 시간 측정이
> 오염될 수 있다 — CVAT 작업이 끝나면 `docs/benchmark_measurement_hygiene.md`대로 Docker Desktop을
> 끄고 지연·속도 벤치마크를 돌릴 것.

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

**✅ 2026-08-07 갱신**: PPE 가중치(`ppe_rfdetr_v1.pth`, `vigent-core/weights/MANIFEST.md` 참고)가
배치되면서 초안을 재실행했다 — 이제 PPE 클래스도 실제 박스가 있다: 109장 전체 person 665·Hardhat 174·
NO-Hardhat 177·Safety-Vest 71·NO-Safety-Vest 280·Mask 82·NO-Mask 125, 박스 0개 프레임 0장
(`benchmarks/generate_prelabels_draft_summary.md`). **단, Safety-Vest는 특히 주의** — conf=0.10
초안 71건 중 과반(39건, 55%)이 conf 0.10~0.15 구간에 몰려 있고, 스팟체크(`benchmarks/
phase2_0_reverify.md` §1-1)에서 최고-conf(0.538) 박스를 포함해 확인한 건 전부 오탐(짙은 작업복을
조끼로 오인)이었다 — **이 9개 사고영상엔 조끼 착용 표본이 없다는 기존 결론이 아직 안 뒤집혔다.**
검수 시 Safety-Vest 박스는 특히 의심하고 볼 것 — 아래 §3-3c "hi-vis 조끼 구분 기준"과 §3-3d 조끼
오탐 계수표를 반드시 채울 것.

**CVAT에 초안을 불러오는 법**: Task 생성 시 이미지 업로드만 하고, 라벨은 **Upload annotations**
(Task 메뉴 → Actions → Upload annotations → format: **YOLO 1.1**)로 `labels_draft/`(+`classes.txt`를
`obj.names`로 리네임한 사본)를 업로드하면 각 이미지에 초안 박스가 미리 그려진 채로 열린다 — 검수자는
그리기가 아니라 "지우기·고치기" 작업을 하게 된다(의도된 워크플로, conf=0.10 과다생성의 목적).

### 3-3b. 검수 프로토콜 — 두 갈래(2026-08-07 갱신, [M]) — 프레임마다 반드시 이 순서로

**채점은 운용 임계에서 한다** — person **0.40**, PPE(Hardhat/NO-Hardhat/Safety-Vest/NO-Safety-Vest/
Mask/NO-Mask) **0.35**(`config/tuning.yaml` `detect.conf` 실측, `benchmarks/
conf_threshold_report_L.md` §0 — **person과 PPE의 임계가 다르다**, 이전에 "0.35 하나"로
통칭했던 건 부정확). conf=0.10 초안 박스 중 **0.10~임계 구간은 최종 채점에 아예 안 들어간다** — 그래서
검수 강도를 둘로 나눈다. 박스의 conf는 `data/field_eval/labels_draft_preview/<파일명>.jpg`에 박스 옆
텍스트로 그려져 있다(CVAT은 YOLO 임포트 시 conf를 못 들고 오므로, 미리보기 jpg를 CVAT과 나란히 띄워
conf를 확인하며 작업한다).

**갈래 1 — 임계 이상 박스(person≥0.40 / PPE≥0.35): 하나씩 정밀 판정.** 정밀도에 직접 영향을 주는
채점 대상이므로 아래 1~3을 전부 적용하고 **수정 내역을 기록**한다(어떤 클래스를 몇 건 삭제/수정
했는지 — §3-3d 계수표, §3-3e 로그 참고):
1. **잘못 잡은 박스 삭제** — 사람이 아닌데 person으로 잡혔거나, PPE가 아닌 걸 PPE로 잡은 경우.
2. **클래스 오류 수정** — 예: Hardhat인데 NO-Hardhat으로 잡힌 경우(착용/미착용 반전은 특히 조심).
3. **박스 경계 보정** — 대상을 살짝 벗어나거나 너무 크게/작게 잡힌 박스를 정확히 맞춘다.

**갈래 2 — 0.10~임계 박스: 개별 판정 대상이 아니다.** 이 구간의 유일한 목적은 검수자가 놓친 객체를
눈에 띄게 하는 것 — "실제로 존재하는 객체"라고 판단되는 것만 정답지에 남기고(필요하면 클래스·경계도
정확히 고쳐서 남긴다), **나머지는 기록 없이 삭제**한다. 삭제 하나하나를 세거나 사유를 남기지 않는다
(갈래 1과 달리 채점에 안 들어가는 구간이라 그럴 가치가 없음 — 단, Safety-Vest만은 §3-3d에서
conf 구간별로 셈, 오탐 규모 파악 목적).

**공통 — 누락(어떤 임계에서도 안 잡힌 객체) 확인: 별도 1회 패스.** 이게 (b)방법(자체모델 초안)의
유일한 구조적 맹점이다 — 모델이 conf 0.10에서도 아예 못 본 사람/PPE는 위 갈래 1·2 어느 쪽 작업으로도
못 잡는다. **2026-08-07 갱신: PPE 가중치 반영 재생성 후 박스 0개 프레임은 0장**이다(모든 프레임에
최소 1개 이상 초안 박스, `generate_prelabels_draft_summary.md`) — 그래도 "박스가 있다"가 "이 프레임의
모든 사람·PPE가 다 잡혔다"를 보장하진 않으므로, 109장 전체를 "초안에 없는 객체가 화면에 있는가"만
보는 별도 패스로 한 번 더 훑는다. 새로 그린 박스는 갈래 1과 동일하게(정밀 판정·기록) 취급한다.

**추가 확정 사항**:
- **person 없는 28장(§1 갱신 고지 참고)은 원칙상 빈 라벨** — 단, `benchmarks/
  conf_threshold_report_L.md` §3에서 확인했듯 28장 중 17장은 person 슬롯+ppe 슬롯 합산 기준
  임계 이상 박스가 실제로 존재한다(person 슬롯만으로 "사람없음"이 정해졌기 때문 — ppe 슬롯의
  독립 `Person` 클래스나 PPE 항목은 별개로 잡힐 수 있음). 이 17장은 위 "갈래 1"로 정밀 판정하고,
  실제로 사람이 보이면 정상적으로 Person(및 보이는 PPE)을 단다. 안 보이면 빈 라벨 유지(§2 참고).
- **애매하면 라벨 달지 말고 해당 프레임을 제외 목록에 기록** — `docs/labeling_exclusions.md`(없으면
  새로 만들어) 같은 곳에 "파일명 + 왜 제외했는지" 한 줄로 남긴다. 억지로 단 라벨보다 "이 프레임은
  판단 보류"가 정답지 품질에 낫다(규칙7). (갈래 1·2 공통 원칙 — 갈래 2도 "존재 자체가 애매하면"
  이 규칙을 따른다.)

### 3-3c. 판독 기준 초안 — 파일럿 20장에서 실제 사례로 확정할 것 (2026-08-07, 확정 전)

**★이 5개 기준은 초안이다.** 지금은 실제 사례(파일럿 20장)를 보기 전에 합리적으로 정한 기본값일 뿐 —
파일럿 검수 중 애매한 경우가 나오면 그 사례를 기준으로 아래를 고치고, **이 문서(§3-3c)를 파일럿
완료 시 반드시 갱신**한다(§2-1). 이미 이 기준으로 본 프레임이 있으면 바뀐 부분만 다시 확인한다.

1. **가려짐·프레임 밖 — Person을 다는 최소 기준(초안)**: 몸통 또는 머리 중 하나가 **명확히 사람이라고
   식별 가능한 만큼** 보이면 단다(예: 상반신만 보여도 사람 형태가 뚜렷하면 O). 다리만 살짝 스치거나,
   그림자·실루엣만으로 사람인지 물체인지 애매하면 **달지 않고 §3-3c 5번(판단 불가 처리) 원칙대로 제외 목록에 기록**. 프레임 경계에
   걸려 몸의 절반 이상이 잘린 경우: 잘리지 않은 부분만으로 사람이라고 확신할 수 있으면 단다(박스는
   보이는 부분만, 화면 밖으로 추정 확장하지 않는다).
2. **Hardhat/NO-Hardhat과 Person 관계(초안)**: **배타적이지 않다 — 함께 단다.** Person은 사람 전체를
   감싸는 박스, Hardhat/NO-Hardhat은 머리 부분만 감싸는 별도 박스다(모델의 실제 출력 방식과 동일 —
   `guard.py`가 이 둘을 독립된 검출로 취급). 즉 사람 1명이 안전모를 쓰고 있으면 **Person 박스 1개 +
   Hardhat 박스 1개**가 한 프레임에 같이 존재해야 정상이다. 머리가 안 보이면(후면·가려짐) Person만
   달고 Hardhat/NO-Hardhat은 §3-3c 5번(판단 불가) 원칙대로 스킵.
3. **헬멧 vs 모자·비슷한 물체 구분(초안)**: 산업안전보건 현장의 **안전모(단단한 셸 형태, 턱끈 유무
   무관)만** Hardhat으로 본다. 일반 야구모자·방한모·후드는 **Hardhat이 아니라 NO-Hardhat**(안전모
   미착용 상태로 판단). 색이 화사해도(주황·노랑 등) 형태가 안전모 셸이 아니면 NO-Hardhat. 원거리·저
   해상도라 형태 구분이 안 되면 §3-3c 5번 원칙대로 Hardhat/NO-Hardhat 둘 다 스킵(억지 추정 금지).
4. **hi-vis 조끼 vs 밝은 작업복 구분(초안, ★현재 오탐의 핵심)**: `benchmarks/phase2_0_reverify.md`
   §1-1에서 확인된 오탐 패턴은 "짙은 색 패딩/작업복을 조끼로 오인"이었다 — 실제 hi-vis 조끼는 보통
   ①형광색(주로 주황·노랑·연두)이면서 ②반사띠(은색 가로줄)가 보이고 ③조끼 특유의 민소매·오버레이
   실루엣(양옆이 트여 안에 옷이 비침)을 가진다. **①~③ 중 최소 2개가 명확히 보여야 Safety-Vest.**
   단순히 "밝은 색 옷"이라는 이유만으로는 달지 않는다(예: 밝은 파란 점퍼는 조끼 아님). 애매하면
   NO-Safety-Vest가 아니라 §3-3c 5번 원칙대로 **스킵**(조끼 여부 자체가 불확실하면 "미착용"이라고 단정하는
   것도 오답이 될 수 있음 — 안 보이면 안 보인다고 기록).
5. **판단 불가 처리(확정)**: 라벨을 달지 않고 `docs/labeling_exclusions.md`(없으면 새로 생성)에
   `파일명 | 클래스 | 사유` 한 줄로 기록한다. 예: `KakaoTalk_..._5000ms.jpg | Safety-Vest | 원거리+
   저해상도로 조끼 형태 식별 불가`.

### 3-3d. Safety-Vest 오탐 계수표 — 파일럿 중 채울 것 (2026-08-07 신설)

**목적**: 조끼 오탐을 그냥 지우기만 하지 말고 conf 구간별로 세어, "운용 임계(0.35, `config/
tuning.yaml` ppe) 이상에서 살아남는 오탐"이 몇 개인지 확인한다 — 이게 실제 배포 시 화면에 뜨는
오탐 개수다. 초안 박스의 conf는 `data/field_eval/labels_draft_preview/<파일명>.jpg`에 박스 옆
텍스트로 그려져 있다(예: "Safety-Vest 0.34") — CVAT에서 삭제하기 전에 이 미리보기로 conf를 먼저
확인한다.

| conf 구간 | 삭제한 오탐 개수(파일럿 20장 기준) | 비고 |
|---|---|---|
| 0.10 ~ 0.15 | (검수 중 기록) | |
| 0.15 ~ 0.35 | (검수 중 기록) | |
| **0.35 이상(운용 임계)** | (검수 중 기록) | **이 칸이 "현장에서 실제로 뜨는 오탐" 개수** |
| 진짜 조끼로 확정(오탐 아님) | (검수 중 기록) | 있으면 §0의 "조끼 착용 표본 0" 결론이 갱신됨 |

### 3-3e. 임계 이상 박스 수정 로그 — 갈래 1 전체 클래스 (2026-08-07 신설)

갈래 1(person≥0.40 / PPE≥0.35) 수정 내역을 클래스별로 기록한다 — Safety-Vest는 §3-3d로 이미
별도 집계하므로 아래 표에서 중복 기록하지 않아도 된다(참고용으로 채워도 무방).

| 클래스 | 임계 이상 박스 수(§L, 파일럿 20장) | 그대로 유지 | 클래스 수정 | 경계 보정 | 삭제(오탐) |
|---|---|---|---|---|---|
| person | 35 | | | | |
| Hardhat | 13 | | | | |
| NO-Hardhat | 8 | | | | |
| Safety-Vest | 5 | §3-3d 참고 | | | |
| NO-Safety-Vest | 16 | | | | |
| Mask | 3 | | | | |
| NO-Mask | 3 | | | | |

("임계 이상 박스 수" 열은 `benchmarks/conf_threshold_report_L.md` §2 실측값 — 검수 시작 전
채워둔 참고치, 나머지 열은 검수 중 기록.)

### 3-4. 검수 완료본 내보내기 → labels/ (labels_draft/는 보존)

> **파일럿 20장은 스크립트로 회수한다**: `python benchmarks/cvat_setup_pilot.py export` — 내려받기·
> 압축해제·`labels/` 반영을 한 번에 하고, **덮어쓰기 전에 `labels_backup_<날짜>_<시각>/`을 자동
> 생성**한다(규칙2). 아래 1~3은 손으로 할 때의 절차.

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
                              person 없는 28장(§1 갱신 고지)은 원칙상 0바이트 빈 파일
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
