# CVAT 자체 설치 — 라벨링 도구 전환 절차 (2026-09-22 작성)

> **설치일: ____________** (대표 결정 — 이 문서는 절차만이며 아직 설치하지 않았다)

## 0. 왜 CVAT 자체 설치인가

| 이유 | 내용 |
|---|---|
| **추적 ID 라벨링이 필요하다** | 우리가 재야 하는 것은 IDSW(같은 사람이 프레임 사이에 번호를 바꾸는가)다. **Roboflow 는 검출 라벨 전용**이라 프레임 간 track 을 잇지 못한다. CVAT 은 영상 트랙 라벨링과 키프레임 보간을 지원한다. |
| **얼굴이 있는 현장 영상을 외부에 올릴 수 없다** | 수집물은 작업자 얼굴이 찍힌 개인영상정보다(CLAUDE.md 규칙 10). SaaS 라벨링 서비스에 업로드하면 **외부 반출**이 된다. 그래서 **Docker 자체 설치**로 사내 PC 안에서만 돌린다. |
| 비용 | 오픈소스(MIT). 자체 호스팅은 무료. |

★**이 결정 전까지 쓰던 방식**: 사고영상 1fps 정답지를 보간해 자체 뷰어로 검수
(`scripts/eval/review_viewer.py`). **중단했으나 삭제하지 않고 보존**한다 —
재개 조건은 "현장 데이터에서 IDSW 가 실제 문제로 확인될 때"다.

## 1. 대상 기기와 요구 사양

**파일럿 데스크톱(Windows)** 에 설치한다. 현장 노트북·배포기에는 설치하지 않는다(부하 간섭).

| 항목 | 최소 | 권장 | 근거 |
|---|---|---|---|
| OS | Windows 10/11 64비트 | 동일 | Docker Desktop 요구사항 |
| **디스크** | **20 GB** | **50 GB** | CVAT 이미지 약 5~8GB + 영상·프레임 캐시. 45분 원본 + 추출 프레임이 쌓인다(**추정 — 실측 전**) |
| **메모리** | **8 GB** | **16 GB** | CVAT 은 컨테이너 6~8개(서버·DB·Redis·워커·UI)를 띄운다 |
| CPU | 4코어 | 8코어 | 프레임 추출·썸네일 생성이 CPU 작업 |
| 선행 | Docker Desktop + WSL2 | | Windows 에서 CVAT 공식 지원 경로 |

⚠️ **디스크·메모리 수치는 CVAT 공식 문서 기준의 일반값이며 우리 데이터로 실측한 값이 아니다.**
설치 후 실제 사용량을 재서 이 표를 갱신한다(규칙 7·9).

## 2. 설치 절차 (아직 실행하지 않았다)

### 2-1. Docker Desktop

1. Docker Desktop for Windows 설치 → **WSL2 백엔드** 사용에 체크.
2. 설치 후 재부팅. PowerShell 에서 확인:
   ```powershell
   docker --version
   docker compose version
   ```
3. Docker Desktop 설정 → Resources 에서 **메모리 8GB 이상** 할당.

### 2-2. CVAT 내려받기·기동

```powershell
cd D:\
git clone https://github.com/cvat-ai/cvat
cd D:\cvat
git checkout v2.x                      # ★태그를 고정한다 — main 은 바뀐다
docker compose up -d
```

기동 확인(컨테이너가 전부 `running` 이어야 한다):
```powershell
docker compose ps
```

### 2-3. 관리자 계정

```powershell
docker exec -it cvat_server bash -ic 'python3 ~/manage.py createsuperuser'
```
아이디·비밀번호를 만든다. **비밀번호는 코드·채팅에 쓰지 않는다**(규칙 5).

### 2-4. 접속

| 항목 | 값 |
|---|---|
| 주소 | **http://localhost:8080** |
| 포트 | 8080(UI). 내부 8070·5432·6379 등은 컨테이너 사이에서만 씀 |
| 외부 공개 | **하지 않는다.** 얼굴이 있는 영상이 올라간다 — 방화벽에서 8080 외부 유입 차단 |

⚠️ 8080 이 이미 쓰이고 있으면 `docker-compose.yml` 의 포트 매핑을 바꾼다.
(VIGENT 서버는 8010, 검수 뷰어는 8777 을 쓴다 — 충돌 없음)

## 3. 프로젝트·라벨 스키마

### 3-1. 프로젝트 생성

1. 로그인 → **Projects** → **+ Create new project**
2. 이름: `VIGENT 현장 정답지` (재방문 수집분)

### 3-2. 라벨 등록 (5종)

**Constructor** 탭에서 아래를 그대로 만든다. 전부 **Rectangle** 타입.

| 라벨 | 용도 |
|---|---|
| `person` | 사람 — **IDSW 측정의 주 대상** |
| `Hardhat` | 안전모 착용 |
| `NO-Hardhat` | 안전모 미착용 |
| `Safety-Vest` | 안전조끼 착용 |
| `NO-Safety-Vest` | 안전조끼 미착용 |

★**기존 정답지 클래스 순서와 맞춘다**(`data/field_eval/classes.txt`):
`person`(0) · `Hardhat`(1) · `NO-Hardhat`(2) · `Safety-Vest`(3) · `NO-Safety-Vest`(4).
Mask·NO-Mask 는 **이번 수집에서 제외**한다 — 현장 보고서 §7-1 에서 마스크를 보호구 경보에서
뺐기 때문이다(`reports/현장테스트_보고서_20260827_v1.2.md`).

### 3-3. 태스크 생성

1. 프로젝트 안에서 **+ Create new task**
2. **원본 mp4 를 그대로 올린다**(프레임으로 잘라 올리지 않는다 — 트랙 보간이 영상 단위로 동작).
3. 고급 설정: `Use cache` 켜기(디스크 절약), `Image quality` 는 기본값 유지.
4. ★**2fps 샘플링은 여기서 하지 않는다.** 라벨을 마친 뒤 변환 단계에서 뽑는다(§5).

## 4. 트랙 라벨링 방법 (CVAT)

- 박스를 그릴 때 **Track** 모드로 그린다(Shape 아님). 그래야 프레임 사이에 ID 가 이어진다.
- 사람이 **키프레임**만 찍으면 CVAT 이 그 사이를 **선형 보간**한다.
- 사람이 사라지면 그 프레임에서 **Outside** 로 표시한다(트랙 종료가 아니라 "이 프레임엔 없음").
- 가림 뒤 같은 사람이 다시 나오면 **같은 트랙**을 이어 쓴다 — 이것이 IDSW 정답이 된다.
- 화질 때문에 같은 사람인지 판단이 안 되면 **새 트랙을 만들지 말고** 속성으로 표시한다
  (기존 뷰어의 `U`(판정 불가)에 해당 — 변환 시 `verdict="unresolvable"` 로 옮긴다).

## 5. 내보내기와 변환

### 5-1. 포맷 선택 — **CVAT for video 1.1 (XML)**

| 포맷 | track ID 보존 | 채택 |
|---|---|---|
| **CVAT for video 1.1 (XML)** | ✅ `<track id=... label=...>` 아래 `<box frame= outside= keyframe=>` | ★**채택** |
| MOT 1.1 | ✅ 보존하나 **person 단일 클래스 전제**라 PPE 라벨이 빠진다 | 보조 |
| YOLO / COCO | ❌ 프레임별 박스만 — **트랙이 사라진다** | 사용 금지 |

`keyframe` 속성이 있어 **사람이 찍은 키프레임과 CVAT 이 보간한 프레임을 구분할 수 있다** —
이것이 XML 을 고른 결정적 이유다.

### 5-2. 변환

```bash
python scripts/eval/cvat_to_gt.py --xml <내보낸.xml> --fps 2 --out data/field_eval/labels_field_2fps
```

- `--fps 2` 로 **라벨 후 2fps 샘플링**을 수행한다(원본 fps 에서 500ms 격자만 추린다).
- 출력은 기존 스키마 그대로: `track_id` · `source` · `parent_track_id` · `video_role`
- **`source` 구분**
  | CVAT 상태 | source |
  |---|---|
  | `keyframe="1"` (사람이 직접 찍음) | `human_verified` |
  | `keyframe="0"` (CVAT 자동 보간) | `cvat_interp` |
  | `outside="1"` | 박스를 내보내지 않는다(그 프레임엔 없음) |

## 6. 설치 후 확인할 것 (규칙 11)

- [ ] `docker compose ps` — 컨테이너 전부 running
- [ ] http://localhost:8080 접속·로그인
- [ ] 라벨 5종이 등록됐는가
- [ ] 시험 영상 10초를 올려 **Track 박스 2개**를 그리고 XML 로 내보내 보기
- [ ] `scripts/eval/cvat_to_gt.py` 로 변환했을 때 track_id 가 살아 있는가
- [ ] 디스크·메모리 실사용량을 재서 §1 표를 갱신
- [ ] 방화벽에서 8080 외부 유입이 차단돼 있는가

## 7. 하지 않는 것

- **외부 클라우드 라벨링 서비스에 올리지 않는다** — 얼굴이 있는 영상이다.
- **사고영상(저해상도 재인코딩본)은 이 프로젝트에 넣지 않는다** — 학습·평가 기준이 섞인다.
- 설치는 **파일럿 데스크톱에만**. 현장 배포기(노트북)에는 넣지 않는다.
