"""llm_provider — LLM 텍스트 추론 얇은 어댑터. 가산식·폴백 안전.

reason_text(prompt, system) 은 텍스트 추론 1회를 수행한다. provider 를 환경변수로 선택:
  VIGENT_LLM_PROVIDER = "ollama"(기본, 무료·로컬) | "anthropic"(실사업용 Claude API)
  · ollama    : http://localhost:11434 로컬 서버 호출(키 불필요, 무료).
  · anthropic : ANTHROPIC_API_KEY(.env, main.py 가 이미 dotenv 로 로드) 있으면 Claude 호출.
  · 미설정 / 오프라인 / 타임아웃 / 그 외 어떤 예외든 전부 삼키고 None 반환 → 호출자가 로컬 폴백.
절대 죽지 않는다(§2 절대 저하 없음). 키·비밀은 로그로 찍지 않는다(§5).

모델·토큰은 하드코딩하지 않고 인자 또는 환경변수로 주입:
  VIGENT_OLLAMA_MODEL(기본 qwen2.5:7b),
  VIGENT_LLM_MODEL(기본 claude-opus-4-8), VIGENT_LLM_MAX_TOKENS(기본 2500).
이미지/영상은 보내지 않는다(텍스트 전용).
"""
from __future__ import annotations

import os


def available() -> bool:
    """provider 사용 가능성(대략). ollama=로컬 가정 True, anthropic=키 존재. 실제 성공은 호출 결과로 판단."""
    provider = os.getenv("VIGENT_LLM_PROVIDER", "ollama")
    if provider == "anthropic":
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    return provider == "ollama"


def _ollama_reason(prompt: str, system: str = "") -> tuple[str | None, str | None]:
    """로컬 Ollama(무료, 키 불필요)로 추론 1회 → (text, backend). 실패 → (None, None)."""
    import json
    import urllib.request
    model = os.getenv("VIGENT_OLLAMA_MODEL", "qwen2.5:7b")
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system or ""},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310  로컬 고정 URL
            data = json.loads(resp.read().decode("utf-8"))
        text = ((data.get("message") or {}).get("content") or "").strip()
        return (text, f"Ollama:{model}") if text else (None, None)
    except Exception:  # noqa: BLE001  연결·타임아웃·파싱 등 전부 폴백
        return None, None


def _anthropic_reason(prompt: str, system: str = "",
                      model: str | None = None, max_tokens: int | None = None) -> tuple[str | None, str | None]:
    """Claude API(실사업용, 키 필요)로 추론 1회 → (text, backend). 실패·미설정 → (None, None)."""
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


def reason_text(prompt: str, system: str = "",
                model: str | None = None, max_tokens: int | None = None) -> tuple[str | None, str | None]:
    """provider 선택 후 추론 1회 → (text, backend). 실패·미설정이면 (None, None)(호출자가 로컬 폴백).

    backend 예: "Ollama:qwen2.5:7b" / "Claude:claude-opus-4-8".
    """
    provider = os.getenv("VIGENT_LLM_PROVIDER", "ollama")
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        return _anthropic_reason(prompt, system, model, max_tokens)
    if provider == "ollama":
        return _ollama_reason(prompt, system)
    # 알 수 없는 provider / 키 없는 anthropic → 안전 폴백
    return None, None
