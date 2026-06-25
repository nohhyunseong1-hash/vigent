# 운명 매칭

사주 계산 정확도와 해석 충실도를 분리한 데이팅 매칭 앱 스캐폴드다.

## 원칙

- 사주 명식 계산은 검증된 만세력 라이브러리로만 처리한다.
- 얼굴 이미지는 품질 검수와 프로필 연출에만 사용한다.
- 성격, 운명, 위험도, 민감 특성을 얼굴에서 추론하지 않는다.
- LLM은 계산을 하지 않고 룰북과 계산 결과를 설명만 한다.

## 현재 범위

- `backend/`
  - FastAPI 기반 API 골격
  - 사주 엔진 인터페이스
  - 프로필 이미지 품질 모듈
  - 설명 가능한 궁합 점수 엔진
- `data/rulebooks/`
  - 사주/궁합/프로필 톤 샘플 룰북
- `docs/`
  - 얼굴 추론을 배제한 프로필 이미지 메타 프롬프트
- `web/`
  - Phase 1 입력/결과 UI
- `tests/`
  - 핵심 모듈 단위 테스트

## 아직 구현하지 않은 것

- 실제 만세력 라이브러리 연동
- 벡터스토어 기반 RAG
- 실제 LLM 호출
- 인증, 결제, 채팅, 신고/차단

## 문서

- 안전형 이미지/인상 처리 기준: `docs/profile-image-meta-prompt.md`

## 권장 다음 단계

1. `SajuEngine` 어댑터에 `sajupy` 또는 `manseryeok-js`를 붙인다.
2. 골든셋 50~100건을 만들고 CI에 넣는다.
3. 이미지 품질 모듈을 온디바이스 또는 엣지 처리로 옮긴다.
4. 룰북을 도메인 검수 가능한 별도 저장소로 분리한다.

## 실행 예시

```bash
cd destiny-matching
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn backend.app.main:app --reload
```

정적 UI는 `web/index.html`을 브라우저에서 직접 열어도 된다.
