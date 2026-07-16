# CLAUDE.md — VIGENT 프로젝트 규칙서

> 이 파일은 Claude Code가 매 대화마다 자동으로 읽는다. 상세 설계는 `VIGENT_META_PROMPT.md`를 따른다.

## 프로젝트
- **VIGENT**: Vision + AI Agent 산업특화 플랫폼. 공유 코어 1개 + 테마(safety/office/sports)별 `vision.yaml` 분기.
- 1차 완성 테마: **safety**.
- 언어: 모든 설명·주석·문서는 **한국어**로.

## 작업자(나)에 대해
- 바이브코딩 입문자다. 한 번에 하나씩, 쉽게 설명하며 진행한다.
- 전문용어는 풀어서 쓰고, 명령을 실행하기 전에 **무엇을·왜** 하는지 먼저 한 줄로 말한다.

## 절대 규칙 (반드시 준수)
1. **기존 MVP 폴더 `~/Desktop/사업계획서/AX안전` 은 읽기 전용.** 절대 수정·삭제하지 않는다. 자산은 **복사**해서 가져온다.
2. **파괴적 작업은 먼저 보여주고 확인받는다** — 파일 삭제, 덮어쓰기, 대량 변경, 외부 전송/설치는 실행 전 계획을 보여주고 내 "진행해"를 기다린다.
3. **한 번에 한 단계만.** `VIGENT_META_PROMPT.md` §15 빌드 순서를 한 단계씩 진행하고, 끝나면 멈춰서 결과를 보고한다. 다음 단계로 임의로 넘어가지 않는다.
4. **의미 있는 진행마다 git 커밋.** 동작 확인이 끝나면 변경사항을 커밋한다(커밋 메시지는 한국어).
5. **비밀키·토큰은 코드/채팅에 쓰지 않는다.** `.env` 파일에 두고 `.gitignore`에 추가한다.
6. **기능은 좋아지는 방향으로만.** 어떤 작업이든 기존 동작·인식·정확도·속도를 저하시킬 우려가 있으면, 실행하기 전에 "무엇이 좋아지고 무엇이 나빠질 수 있는지"를 먼저 보고하고 내 승인을 받는다. 저하가 불가피한 트레이드오프는 임의로 진행하지 않는다. 변경 후 저하가 확인되면 즉시 직전 상태로 되돌린다.
7. **할루시네이션 절대 금지 — 증명 가능한 것만 말한다.** 측정·실행·검증하지 않은 수치(정확도·재현율·완성도 % 등)나 사실을 지어내지 않는다. 근거는 "실제로 돌려본 결과·로그·파일·출처"여야 한다.
   - **모르면 "모른다"고 말한다.** 추측이 필요하면 반드시 "추측/미검증"이라고 명시하고, 구체적 숫자로 포장하지 않는다.
   - **% 등 수치는 측정 도구·시험으로 잰 값만** 제시한다. 측정 전이면 "측정해야 안다"고 답한다.
   - 그럴듯한 숫자로 안심시키지 않는다. 정직한 "모름"이 가짜 확신보다 낫다.
8. **동시 세션은 반드시 git worktree로 격리한다.** 여러 백그라운드 세션이 한 워킹트리·HEAD를 공유하면 한 세션의 `git checkout`이 전역 HEAD를 옮겨 다른 세션의 커밋이 엉뚱한 브랜치에 얹힌다(2026-07-07 실제 발생: T10b 커밋이 audit 브랜치에 얹힘). 따라서 **세션당 독립 워킹트리+HEAD**를 쓰고, **공유 워킹트리에서 브랜치 checkout 금지**, **커밋 직전 반드시 `git branch --show-current`로 대상 브랜치를 확인**한다. 또한 **새 워크트리를 만들면 기동·측정 전에 `.gitignore` 대상 자산(가중치 `weights/`, `.env`, 학습·평가 데이터 `data/`)의 존재를 확인**한다 — 워크트리에는 추적 파일만 체크아웃되어 이들이 빠지고, 그러면 모델이 조용히 폴백해 검출이 무력화되는 사고가 난다(2026-07-07 F-8: 워크트리 weights 누락→COCO 폴백). `scripts/setup_worktree.sh`로 심링크·검증을 자동화하거나, 최소한 파일 편집이 아닌 실행(서버·벤치)을 워크트리에서 하기 전에 자산 유무를 눈으로 확인한다.

## 설계 원칙 (요약 — 상세는 메타 프롬프트)
- **절대 저하 없음 = 가산식 + 폴백**: 딥러닝 신호는 규칙 점수에 가산만. 모델이 없거나 실패하면 휴리스틱으로 자동 폴백하고 기능은 죽지 않는다.
- **테마는 코드가 아니라 설정**: 신규 테마 = `vision.yaml` + 프론트 1개. 코어 로직은 수정하지 않는다.
- **에이전트는 근거를 인용한다**: 위험성평가·피드백에는 출처(법령 조항·가이드·논문)를 함께 단다.
- **모델 불가지론**: 모델 경로는 `vision.yaml`/설정으로 주입. 나중에 다른 모델로 교체 가능하게.

## 안전·법규 경계 (코드·문서·UI에 명시할 것)
- **기능안전**: 비전 ML은 확률적이므로 인증 안전기능을 대체할 수 없다. 프레스·전단기 비상정지의 1차 책임은 인증 하드웨어(Type 4 광전자식 방호장치, 안전 PLC)에 있다. VIGENT는 **보조·감시 계층으로 신호만 제공**한다.
- **근로자 영상감시(office)**: 개인정보보호법·근로기준법상 동의·고지·노사협의 대상. 기본은 **익명 집계**, 얼굴 블러 기본 on.

## 폴더 구조 (목표)
```
~/Desktop/VIGENT/                  ← 작업 폴더 (여기)
  CLAUDE.md
  VIGENT_META_PROMPT.md
  vigent-core/
    main.py            앱 인프라만(302줄): app 생성 · include_router · 미들웨어 · startup · `/` 루트
    app_state.py       공유 런타임 상태(STATE·DETECT_LOCK·load_theme 등) — main 미import
    web_util.py        공유 웹 헬퍼(이미지·zone·_tpl·_TBM_CSS 등) — main 미import
    routers/           도메인별 APIRouter(P1-7 분할): tapo·vitals·zone·sports·office·system·
                       detect·incident·tbm·ppe·recognition·dispatch·safety_core
  themes/{safety,office,sports}/   config/  data/  runs/  tests/
~/Desktop/사업계획서/AX안전/        ← 기존 MVP (읽기 전용 참고)
```
> **라우터 규칙(P1-7):** 라우터는 `main`을 import하지 않는다(순환 금지). 공유는 `app_state`(상태)·`web_util`(헬퍼)로. 라우트 변경 시 `scripts/check_openapi_diff.py`로 회귀 확인. 상세는 [docs/ONBOARDING.md](docs/ONBOARDING.md) §3.5.

## 기술 스택
Python 3.11 · FastAPI · ultralytics(YOLO11/8, AGPL 주의 — §6) · ByteTrack · RTMPose · mmaction2 · TensorFlow(BODA 분류기) · OpenCV. 프론트는 순수 HTML/JS + CDN(MediaPipe·TF.js). 테스트: `python -m unittest discover -s tests`.

## 코드 품질 게이트 (P0~P2 완료 — 변경 시 통과 필수)
CODE_REVIEW.md §5의 P0~P2 조치가 완료됐다. 코드 변경 시 아래를 모두 통과 후 커밋(= CI 스텝과 동일):
1. **ruff** `ruff check vigent-core tests` → 0
2. **mypy**(점진) `python -m mypy` → 화이트리스트 0 에러 (라우트 핸들러엔 `-> dict/str` 금지: FastAPI가 response_model 로 채택해 응답 스키마가 바뀜)
3. **테스트** `.../python3 -m unittest discover -s tests` → **55 tests**
4. **OpenAPI 무변경** `python scripts/check_openapi_diff.py` → 106 == baseline + WS 불변
5. **CI** `.github/workflows/ci.yml` 이 위 4개를 push/PR 시 자동 실행
- 구조·게이트·후속 백로그 상세: [docs/ONBOARDING.md](docs/ONBOARDING.md) §3.5·§6 · [docs/P3_BACKLOG.md](docs/P3_BACKLOG.md).

## 막혔을 때
- 정보가 부족하면 추측하지 말고 **나에게 질문**한다.
- 외부 라이브러리 설치가 필요하면 먼저 목록과 이유를 보여주고 확인받는다.
