"""llm_provider — LLM 텍스트 추론 얇은 어댑터. 가산식·폴백 안전.

reason_text(prompt, system) 은 텍스트 추론 1회를 수행한다. provider 를 환경변수로 선택:
  VIGENT_LLM_PROVIDER = "openai"(기본) | "anthropic"(Claude API)
  · openai    : OPENAI_API_KEY(.env, main.py 가 이미 dotenv 로 로드) 있으면 호출.
  · anthropic : ANTHROPIC_API_KEY 있으면 Claude 호출(추후 마이그레이션 대비 유지).
  · 키 없음 / 오프라인 / 타임아웃 / 그 외 어떤 예외든 전부 삼키고 None 반환 → 호출자가 규칙 기반 폴백.
절대 죽지 않는다(§2 절대 저하 없음). 키·비밀은 로그로 찍지 않는다(§5).

※ Ollama(로컬) 경로는 제거됨(2026-07-14). 이전엔 기본 provider 였으나 OpenAI 단일화.
   → 오프라인/폐쇄망에서는 LLM 텍스트 보강이 동작하지 않고 **규칙 기반 폴백**으로만 동작한다.
   LLM 은 '종합의견' 한 문단에만 opt-in(use_llm=True)으로 쓰이며, 위험성평가서의 점검항목 표·
   법령 인용·위계 분류는 전부 규칙 기반이라 provider 유무와 무관하다(저하 없음).

모델·토큰은 하드코딩하지 않고 인자 또는 환경변수로 주입:
  OPENAI_MODEL(기본 gpt-4o-mini),
  VIGENT_LLM_MODEL(기본 claude-opus-4-8), VIGENT_LLM_MAX_TOKENS(기본 2500).
이미지/영상은 보내지 않는다(텍스트 전용). 비전(프레임)은 reason_vision 이며 별도 게이트(F-12).
"""
from __future__ import annotations

import os

_DEFAULT_PROVIDER = "openai"


def current_provider() -> str:
    """현재 설정된 provider 이름(환경변수 실값). UI·/health 표시용 — 추측 금지, 실제 설정을 반환."""
    return os.getenv("VIGENT_LLM_PROVIDER", _DEFAULT_PROVIDER)


def available() -> bool:
    """provider 사용 가능성(대략) = 해당 provider 의 키 존재. 실제 성공은 호출 결과로 판단."""
    provider = current_provider()
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    return False


def status() -> dict:
    """UI·/health 노출용 상태(키 값은 절대 반환하지 않고 존재여부만)."""
    provider = current_provider()
    return {
        "provider": provider,
        "available": available(),
        "model": (os.getenv("VIGENT_LLM_MODEL", "claude-opus-4-8") if provider == "anthropic"
                  else os.getenv("OPENAI_MODEL", "gpt-4o-mini")),
        "note": ("키 없음 → 규칙 기반 폴백으로 동작(기능 유지)" if not available()
                 else "LLM 보강 활성(종합의견 등 opt-in 경로에만 사용)"),
    }


def _is_korean_clean(text: str) -> bool:
    """한국어 오염 가드(공용) — 모델이 중국어/낱자 한자로 새는 경우 차단.
    한자(CJK Unified Ideographs, U+4E00~U+9FFF)가 1글자라도 있으면 오염으로 본다('안전帽' 같은 치환까지 차단).
    한글(U+AC00~U+D7A3)은 절대 트리거하지 않는다. reason_text 에서 provider 무관하게 일괄 적용(방어 유지)."""
    return not any("一" <= ch <= "鿿" for ch in text)


def _anthropic_reason(prompt: str, system: str = "",
                      model: str | None = None, max_tokens: int | None = None) -> tuple[str | None, str | None]:
    """Claude API(키 필요)로 추론 1회 → (text, backend). 실패·미설정 → (None, None)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None, None
    used_model = model or os.getenv("VIGENT_LLM_MODEL", "claude-opus-4-8")
    try:
        import anthropic  # lazy import — 미설치/미사용 시 무영향
        client = anthropic.Anthropic(timeout=20)
        resp = client.messages.create(
            model=used_model,
            max_tokens=max_tokens or int(os.getenv("VIGENT_LLM_MAX_TOKENS", "2500")),
            thinking={"type": "adaptive"},
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        # content 에 thinking 블록이 섞여 오므로 type=="text" 블록만 이어붙인다
        text = "".join(b.text for b in resp.content
                       if getattr(b, "type", None) == "text").strip()
        return (text, f"Claude:{used_model}") if text else (None, None)
    except Exception:  # noqa: BLE001  키오류·네트워크·타임아웃 등 전부 폴백(로그로 키 노출 금지)
        return None, None


def _openai_reason(prompt: str, system: str = "",
                   model: str | None = None) -> tuple[str | None, str | None]:
    """OpenAI 텍스트 추론 1회 → (text, backend). 키없음/에러/타임아웃 → (None,None).
    모델명은 env(OPENAI_MODEL) 주입(하드코딩 금지)."""
    if not os.getenv("OPENAI_API_KEY"):
        return None, None
    used_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        from openai import OpenAI  # lazy import
        client = OpenAI(timeout=20)  # OPENAI_API_KEY 자동 로드(.env)
        resp = client.chat.completions.create(
            model=used_model,
            messages=[{"role": "system", "content": system or ""},
                      {"role": "user", "content": prompt}],
        )
        text = (resp.choices[0].message.content or "").strip()
        return (text, f"OpenAI:{used_model}") if text else (None, None)
    except Exception:  # noqa: BLE001  키오류·모델오류·네트워크 등 전부 폴백(키 로그 금지)
        return None, None


def reason_vision(image_bgr, prompt: str, system: str | None = None) -> tuple[str | None, str | None]:
    """OpenAI 비전 추론 1회(이미지+텍스트) → (text, backend). 키없음/에러/타임아웃 → (None,None) 폴백.
    모델명은 env(OPENAI_VISION_MODEL→OPENAI_MODEL→gpt-4o-mini) 주입(하드코딩 금지). 이미지는 JPEG base64로 전송.

    ★ 영상 불유출 원칙: 현장 프레임의 외부 전송은 VIGENT_CLOUD_VLM=1 명시 opt-in 일 때만(기본 off).
    OPENAI_API_KEY 존재만으로는 절대 전송하지 않는다(무동의 활성=조용한 원칙 붕괴 차단, VIGENT_ALLOW_FALLBACK 과 동일 철학).
    상용 배포 미포함 — 데모/내부개발 전용.
    ※ 이 게이트는 provider 정리(2026-07-14)와 무관하게 그대로 유지한다(F-12, 커밋 30da500)."""
    if image_bgr is None or os.getenv("VIGENT_CLOUD_VLM") != "1" or not os.getenv("OPENAI_API_KEY"):
        return None, None
    used_model = os.getenv("OPENAI_VISION_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    try:
        import base64
        import cv2
        ok, buf = cv2.imencode(".jpg", image_bgr)
        if not ok:
            return None, None
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        from openai import OpenAI  # lazy import
        client = OpenAI(timeout=30)  # OPENAI_API_KEY 자동 로드(.env)
        resp = client.chat.completions.create(
            model=used_model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": (system + "\n" if system else "") + prompt},
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + b64}},
            ]}],
        )
        text = (resp.choices[0].message.content or "").strip()
        return (text, f"OpenAI-vision:{used_model}") if text else (None, None)
    except Exception:  # noqa: BLE001  키오류·모델오류·네트워크 등 전부 폴백(키 로그 금지)
        return None, None


def reason_text(prompt: str, system: str = "",
                model: str | None = None, max_tokens: int | None = None) -> tuple[str | None, str | None]:
    """provider 선택 후 추론 1회 → (text, backend). 실패·미설정이면 (None, None)(호출자가 규칙 기반 폴백).

    backend 예: "OpenAI:gpt-4o-mini" / "Claude:claude-opus-4-8".
    키가 없거나 알 수 없는 provider 면 조용히 (None, None) → 기능은 죽지 않고 규칙 기반으로 동작한다.
    """
    provider = current_provider()
    if provider == "anthropic":
        text, backend = _anthropic_reason(prompt, system, model, max_tokens)
    elif provider == "openai":
        text, backend = _openai_reason(prompt, system, model)
    else:
        return None, None   # 알 수 없는 provider → 안전 폴백
    # 한국어 오염 가드(provider 무관 일괄) — 한자 누출 시 규칙 폴백으로 되돌린다.
    if text and not _is_korean_clean(text):
        return None, None
    return text, backend
