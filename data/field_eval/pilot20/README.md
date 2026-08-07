# 파일럿 20장 검수 — 시작 안내서 (CVAT, 2026-08-07)

## 0. 확인된 사실 (규칙7 — 지어내지 않음)

이 문서의 내용은 실제로 실행해서 확인한 것만 적는다.

- **CVAT가 이 데스크탑에서 실제로 기동됐다.** Docker Desktop(WSL2 backend) 설치 후
  `D:\cvat`에서 `docker compose up -d` → 컨테이너 18개 전부 `Up`, traefik이 8080 포트를 열고
  있는 것을 `docker compose ps`로 확인. `http://localhost:8080` 로그인 성공.
- **왕복 테스트 통과(2026-08-07).** 현재 `labels/`(박스 79건)를 CVAT에 import → 아무것도
  수정하지 않고 즉시 export → 원본과 파일 단위 비교 결과 **20/20 파일 완전 일치**.
  즉 CVAT를 거쳐도 클래스 순서·좌표가 깨지지 않는다는 것이 실측으로 확인됐다.
- **태스크 검증(`inspect`).** `pilot20`(id=1, 20장) / `field_eval_89`(id=2, 89장) 두 태스크 모두
  라벨 7개의 **순서·이름이 `classes.txt`와 정확히 일치**하고, 프레임 목록도 기대한 파일들과
  일치함을 확인.
- **labelImg는 중단했다.** 처음엔 labelImg로 진행했고 실제로 창을 띄워 박스가 보이는 것까지
  확인했으나(PyQt5 5.15.11 호환 버그 `scroll_request`의 `setValue()` float 전달 → `TypeError`를
  로컬 설치본 1줄 패치로 우회), 스크롤 등 상호작용에서 크래시가 재발할 수 있는 임시 패치 상태였고
  사용자 판단으로 **CVAT로 전환**했다. labelImg 관련 잔여물은 로컬 파이썬 환경의 패치뿐이며
  VIGENT 저장소 코드에는 아무 영향이 없다.

## 1. 서버 기동·정지

```powershell
# 기동 (최초 1회는 docker compose pull 먼저 — 이미지 약 10개 내려받음)
cd D:\cvat
docker compose up -d
docker compose ps          # 전부 Up 인지 확인

# 정지 (컨테이너만 멈춤 — 데이터는 볼륨에 남는다)
cd D:\cvat
docker compose stop

# 완전 종료 (컨테이너 삭제. 볼륨은 남으므로 태스크·어노테이션은 보존)
docker compose down
```

**접속 주소: `http://localhost:8080`**

계정이 없으면(최초 1회):
```powershell
docker exec -it cvat_server python3 ~/manage.py createsuperuser
```
아이디 → 이메일(엔터로 건너뛰기 가능) → 비밀번호 2회 순으로 물어본다. 비밀번호는 입력해도 화면에
표시되지 않는 것이 정상.

> **★측정 위생 주의**: CVAT가 떠 있으면 `vmmem`(WSL2 VM)이 CPU를 점유해서 **CPU 전용 torch 추론
> 시간 측정이 오염된다.** 지연·속도 벤치마크를 돌리기 전에는 `docker compose stop` + `wsl --shutdown`
> 을 먼저 하고 측정한다. 상세는 `docs/benchmark_measurement_hygiene.md`.

## 2. 폴더 구조 (편집용 vs 참고용 분리)

```
pilot20/
  images/   20장 원본 이미지 — CVAT 태스크 "pilot20"에 업로드된 것과 동일
  labels/   ★정답지 본체★ — 운용 임계 이상 박스만(person≥0.40 / PPE≥0.35) YOLO txt.
            CVAT에 import 되는 원본이자, 검수 완료 후 export로 되돌아오는 목적지.
            classes.txt 동봉(클래스 순서 정본).
  hints/    참고용 이미지(같은 파일명, .jpg) — 진한 실선=임계 이상(labels/에 이미 들어있는 것),
            회색 점선=0.10~임계 후보(정답지에 없음, conf 숫자 표기).
            ★CVAT 안에는 넣지 않는다★ — 별도 사진 뷰어로 옆 화면에 띄워두고 참고만 한다.
            (CVAT에 넣으면 이미지 수가 20장이 아니게 되어 태스크가 오염된다.)
  classes.txt              labels/classes.txt와 동일 사본(참고용)
  .cvat_tasks.json         CVAT task id 기록(pilot20=1, field_eval_89=2)
  labels_backup_YYYYMMDD*  덮어쓰기 전 자동 백업(export 명령이 매번 생성)
  README.md / notes.md / timing.md
```

**`data/field_eval/labels_draft/`는 건드리지 않는다** — 원본 초안(정답지 출처 추적용,
`docs/labeling_guide.md` §3-4). 이 `pilot20/labels/`는 그 초안에서 임계 이상만 추린 **별도 사본**이다.

## 3. 태스크 열기

1. `http://localhost:8080` 로그인
2. 상단 **Tasks** 탭 → 목록에서 **`pilot20`** 클릭
3. Jobs 섹션의 **Job #N** 을 클릭하면 어노테이션 화면이 열린다 (또는 태스크 카드의 **Open** → **Job**)

`field_eval_89`는 89장 전수 검수용으로 미리 만들어 둔 것이다 — **지금은 열지 않는다.**
파일럿 결과로 규칙이 확정된 뒤에 착수한다(규칙이 바뀌면 재작업 범위가 20장으로 묶이도록 분리한 것).

## 4. 조작법 (CVAT 어노테이션 화면)

| 동작 | 방법 |
|---|---|
| 박스 선택 | 박스 클릭 (또는 우측 Objects 패널에서 클릭) |
| 박스 이동·크기 조절 | 선택 후 드래그 / 모서리 핸들 드래그 |
| 박스 삭제 | 선택 후 `Delete` |
| 새 박스 그리기 | 좌측 툴바의 사각형(Draw new rectangle) → 라벨 선택 → **Shape** → 드래그. 단축키 `N`으로 그리기 시작/종료 |
| 클래스(라벨) 바꾸기 | 우측 Objects 패널에서 해당 객체의 라벨 드롭다운 변경 |
| 다음 / 이전 이미지 | `F` / `D` (또는 상단 화살표 버튼) |
| **저장** | `Ctrl+S` (또는 상단 저장 아이콘) |
| 실행 취소 / 재실행 | `Ctrl+Z` / `Ctrl+Shift+Z` |
| 화면 맞춤 | `Shift+F` |

- CVAT는 서버에 저장하는 방식이라 **`Ctrl+S`를 누르기 전까지는 브라우저에만 있다.** 프레임 몇 장
  넘길 때마다 습관적으로 `Ctrl+S`를 누를 것.
- 단축키가 기억 안 나면 화면 우상단 **`?`(키보드) 아이콘**에서 전체 목록을 볼 수 있다.

## 5. 검수 순서 (①조끼 4 → ②사람없음 6 → ③근거리·원거리 10)

`docs/pilot20_frames.md`의 선정 카테고리(A/B/C/D)와 아래 **보는 순서**는 다르다 — 카테고리는
"왜 이 20장을 뽑았는지"의 근거이고, 아래는 **우선순위대로 보는 순서**다.

**① 조끼(Safety-Vest) 임계 이상 4프레임 — 가장 먼저, 가장 꼼꼼히**
(`benchmarks/conf_threshold_report_L.md` §2에서 확인된, 운용 임계 0.35를 실제로 넘긴 5건이 속한 프레임):

1. `KakaoTalk_20260807_000438282_1000ms.jpg` (최고 conf 0.538)
2. `KakaoTalk_20260807_000611749_1000ms.jpg` (0.409)
3. `KakaoTalk_20260807_000611749_0ms.jpg` (0.367)
4. `KakaoTalk_20260807_000633827_4000ms.jpg` (0.358)

**② 사람없음 관련 6장** (원래 선정 A카테고리 5장 + 조끼 경계사례 1장 — `000611749_5000ms`는
Safety-Vest conf 0.342로 임계 바로 아래라 ①에는 안 넣었지만 size_bucket이 "사람없음"이라 여기서 같이 본다):

5. `KakaoTalk_20260807_000633827_3000ms.jpg`
6. `KakaoTalk_20260807_000552920_0ms.jpg`
7. `KakaoTalk_20260807_000601541_8000ms.jpg`
8. `KakaoTalk_20260807_000442974_1000ms.jpg`
9. `KakaoTalk_20260807_000552920_11000ms.jpg`
10. `KakaoTalk_20260807_000611749_5000ms.jpg`

**③ 근거리·원거리 10장**:

11. `KakaoTalk_20260807_000442974_6000ms.jpg` (근거리)
12. `KakaoTalk_20260807_000552920_6000ms.jpg` (근거리)
13. `KakaoTalk_20260807_000601541_7000ms.jpg` (근거리)
14. `KakaoTalk_20260807_000632301_0ms.jpg` (근거리)
15. `KakaoTalk_20260807_000658251_1000ms.jpg` (근거리)
16. `KakaoTalk_20260807_000552920_19000ms.jpg` (원거리)
17. `KakaoTalk_20260807_000601541_2000ms.jpg` (원거리)
18. `KakaoTalk_20260807_000611749_13000ms.jpg` (원거리)
19. `KakaoTalk_20260807_000632301_8000ms.jpg` (원거리)
20. `KakaoTalk_20260807_000721865_16000ms.jpg` (원거리)

CVAT의 프레임 순서는 파일명 사전순(lexicographical)이라 위 순서와 다르다 — 상단 프레임 번호
입력칸에 번호를 넣어 이동하거나, 위 목록을 옆에 띄워두고 `F`/`D`로 넘기며 순서를 맞춘다.

## 6. 프레임당 절차 3단계 (`docs/labeling_guide.md` §3-3b 갈래 요약)

1. **임계 이상 박스 정밀 판정** — CVAT에 이미 로드된 박스를 하나씩: 틀렸으면 삭제(`Delete`),
   클래스가 틀렸으면 우측 패널에서 라벨 변경, 경계가 어긋났으면 드래그로 보정.
   수정 내역은 `docs/labeling_guide.md` §3-3d(조끼)·§3-3e(전체 클래스)에 기록.
2. **회색 점선 후보 중 진짜만 추가** — `hints/<파일명>.jpg`를 별도 뷰어로 띄워 회색 점선 박스를
   확인하고, **실제로 존재하는 객체라고 확신하는 것만** 새 박스로 추가한다. 나머지는 기록 없이 무시.
3. **아무것도 없는 곳의 누락 훑기** — `hints/`에도 전혀 안 잡힌(점선조차 없는) 사람·PPE가 화면에
   있는지 마지막으로 한 번 더 본다. 있으면 추가(①과 동일하게 정밀 취급).

**애매하면 라벨을 달지 말고** `notes.md`에 "파일명 + 무엇이 애매한지"만 한 줄 적고 다음으로 넘어간다
(억지 판단 금지 — `docs/labeling_guide.md` §3-3c 5번).

## 7. ★검수 완료 후 — export 해서 `labels/`로 되돌리기

CVAT에서 `Ctrl+S`로 저장한 것은 **CVAT 서버 안에만** 있다. 정답지 파일로 되돌리려면:

```powershell
cd D:\vigent_original
python benchmarks/cvat_setup_pilot.py export
```

아이디·비밀번호를 물어본 뒤(비밀번호는 화면에 안 보임):

1. CVAT `pilot20` 태스크의 어노테이션을 YOLO 1.1 포맷으로 내려받고,
2. **덮어쓰기 전에 `labels_backup_<날짜>_<시각>/`으로 현재 `labels/`를 자동 백업**한 다음,
3. `labels/*.txt`를 갱신한다. 반영된 파일 수·내용이 바뀐 파일 수·총 박스 수를 출력한다.

되돌리고 싶으면 출력에 표시된 백업 폴더의 내용을 `labels/`로 복사하면 된다.

> 손으로 하고 싶다면: CVAT 태스크 메뉴 → **Export task dataset** → Format `YOLO 1.1`,
> "Save images" 체크 해제 → 받은 zip 안의 `obj_train_data/*.txt`를 `labels/`로 복사.
> (스크립트 쪽이 백업까지 자동이라 안전하다.)

## 8. 참고 — 스크립트 명령 요약

```powershell
cd D:\vigent_original
python benchmarks/cvat_setup_pilot.py setup      # 태스크 2개 생성 + 이미지 업로드(최초 1회)
python benchmarks/cvat_setup_pilot.py inspect    # 라벨 순서·이미지 목록이 기대와 같은지 검증
python benchmarks/cvat_setup_pilot.py roundtrip  # import→무수정 export→원본 비교(20/20 이어야 통과)
python benchmarks/cvat_setup_pilot.py export     # 검수 결과를 labels/로 회수(백업 자동)
```

비밀번호는 인자로 받지 않는다(규칙5) — 실행 중 입력받거나 환경변수 `CVAT_USER`/`CVAT_PASSWORD`를 쓴다.

## 9. 완료 후

`notes.md`·`timing.md`를 채운 뒤 `docs/pilot20_frames.md` §4 항목대로 보고한다. `labels/`가 검수
완료본이 된다 — 89장 착수 승인 전까지 `data/field_eval/labels/`(전수용 최종 경로)로는 옮기지 않는다.
