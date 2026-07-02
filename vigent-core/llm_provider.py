"""llm_provider — 외부 LLM(Claude API) 얇은 어댑터. 가산식·폴백 안전.

reason_text(prompt, system) 은 텍스트 추론 1회를 수행한다.
  · ANTHROPIC_API_KEY(.env, main.py 가 이미 dotenv 로 로드) 가 있으면 Claude API 호출.
  · 키 없음 / 오프라인 / 타임아웃 / 그 외 어떤 예외든 전부 삼키고 None 반환 → 호출자가 로컬 폴백.
절대 죽지 않는다(§2 절대 저하 없음). 키·비밀은 로그로 찍지 않는다(§5).

모델·토큰은 하드코딩하지 않고 인자 또는 환경변수로 주입:
  VIGENT_LLM_MODEL(기본 claude-opus-4-8), VIGENT_LLM_MAX_TOKENS(기본 2500).
이미지/영상은 보내지 않는다(텍스트 전용).
"""
from __future__ import annotations

import os


def available() -> bool:
    """API 사용 가능 여부(키 존재)만 확인. 실제 성공은 호출 결과로 판단."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def reason_text(prompt: str, system: str = "",
                model: str | None = None, max_tokens: int | None = None) -> str | None:
    """Claude 로 텍스트 추론 1회. 실패·미설정이면 None(호출자가 로컬 폴백).

    반환: 응답의 text 블록만 이어붙인 문자열(내용 없으면 None).
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # lazy import — 미설치/미사용 시 무영향
        client = anthropic.Anthropic(timeout=20)
        resp = client.messages.create(
            model=model or os.getenv("VIGENT_LLM_MODEL", "claude-opus-4-8"),
            max_tokens=max_tokens or int(os.getenv("VIGENT_LLM_MAX_TOKENS", "2500")),
            thinking={"type": "adaptive"},
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        # content 에 thinking 블록이 섞여 오므로 type=="text" 블록만 이어붙인다
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text").strip()
        return text or None
    except Exception:  # noqa: BLE001  키오류·네트워크·타임아웃 등 전부 폴백(로그로 키 노출 금지)
        return None
