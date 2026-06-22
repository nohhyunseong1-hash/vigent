"""vlm_confirm.py — CNN→VLM 하이브리드 확정(오탐 최소화)

CNN/CV(눈)가 1차로 의심 이벤트를 감지하면, VLM(두뇌)이 프레임을 보고
'정말 그 위험이 맞는지' 한국어로 2차 판정한다. 결과는 가산식으로만 작용한다:
  · 확정(confirmed)            → 알림 유지(+VLM 한국어 근거)
  · 오탐(rejected, 고신뢰)     → 푸시 억제(단, 기록·증거는 호출측이 그대로 남김 = 미탐 방지)
  · 불확실/VLM없음/실패        → 기존 동작 그대로 (절대 저하 없음, 폴백)

VLM 은 무겁고 느리므로 이벤트 '확정 순간'에만 드물게 호출한다(매 프레임 아님).
mlx_vlm 미설치·로드 실패 등 어떤 경우에도 예외로 죽지 않고 available=False 로 폴백한다.
"""
from __future__ import annotations

from typing import Any

# 규칙별 확정 프롬프트 — 무엇을 의심했는지 + 대표 오탐 예시(정상 상황) 를 알려준다.
CONFIRM_PROMPTS: dict[str, str] = {
    "fall_suspected":
        "당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 '사람이 쓰러짐(낙상)'을 감지했다. "
        "실제로 사람이 바닥에 쓰러지거나 넘어진 위급 상황인지 판정하라. "
        "쪼그려 앉기·눕는 작업·몸을 숙인 정상 자세이면 '오탐'이다.",
    "ppe_missing":
        "당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 '개인보호구(안전모·안전조끼) 미착용'을 감지했다. "
        "실제로 보호구를 착용하지 않은 작업자가 있는지 판정하라. "
        "보호구를 정상 착용했는데 각도·조명 때문에 잘못 본 것이면 '오탐'이다.",
    "zone_intrusion":
        "당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 '위험구역 침입'을 감지했다. "
        "실제로 사람이 출입금지·위험 구역 안에 들어가 있는지 판정하라. "
        "구역 경계 밖에 있거나 단순 통과이면 '오탐'이다.",
    "fire_smoke":
        "당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 '화재·연기'를 감지했다. "
        "실제로 불꽃이나 연기가 발생했는지 판정하라. "
        "수증기·먼지·안개·조명 반사 등이면 '오탐'이다.",
    "guard_bypass":
        "당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 '프레스·전단기 등 위험기계 방호구역에 신체 진입'을 감지했다. "
        "실제로 손·신체가 위험 지점에 들어갔는지 판정하라. 안전한 거리에 있으면 '오탐'이다.",
}
_GENERIC = ("당신은 한국 산업안전 관제 분석가다. CNN이 이 화면에서 위험 이벤트를 감지했다. "
            "실제 위험 상황이 맞는지 판정하라.")

# 소형 VLM(3B)은 범주형("확정/오탐")을 잘 못 골라 템플릿을 그대로 따라 쓴다.
# 반면 숫자(위험확률)는 잘 생성한다 → 숫자 기반으로 받는다(안정성↑).
_FMT = ("\n이 화면에 실제로 위 위험이 발생했을 확률을 0에서 100 사이 정수로 매겨라.\n"
        "아래 JSON 하나만 출력하라(다른 설명·코드블록 금지):\n"
        '{"위험확률": 50, "이유": "한국어 한 문장"}\n'
        "실제 위험이 분명하면 70~100, 애매하면 40~60, 정상·오탐이면 0~30 으로 한다.")

# 판정 경계 + 푸시 억제 임계(미탐 방지: 위험확률이 충분히 낮을 때만 억제)
CONFIRM_AT = 60        # 위험확률 ≥ 60 → 확정
REJECT_AT = 35         # 위험확률 ≤ 35 → 오탐
SUPPRESS_AT = 25       # 위험확률 ≤ 25 → 고신뢰 오탐(푸시 억제)


def build_prompt(rule: str, reason: str = "") -> str:
    """규칙(+1차 감지 사유) → VLM 확정 프롬프트."""
    base = CONFIRM_PROMPTS.get(rule, _GENERIC)
    if reason:
        base += f"\n참고(1차 감지 사유): {reason}"
    return base + _FMT


def _risk_prob(data: dict) -> int | None:
    """VLM JSON → 위험확률(0~100). 없거나 템플릿을 그대로 따라 쓴 경우 None."""
    val = data.get("위험확률")
    if val is None:
        return None
    s = str(val).strip()
    if "또는" in s or "0에서" in s or not any(c.isdigit() for c in s):
        return None  # 소형 모델이 형식 문구를 그대로 출력 → 무효
    import re
    m = re.search(r"\d+", s)
    if not m:
        return None
    return max(0, min(100, int(m.group(0))))


def classify(data: dict) -> tuple[str, int]:
    """VLM JSON → (verdict, risk). verdict ∈ confirmed/rejected/uncertain.
    risk = 위험확률(0~100). 무효/없음이면 uncertain, risk=-1(억제 안 함)."""
    risk = _risk_prob(data)
    if risk is None:
        return "uncertain", -1
    if risk >= CONFIRM_AT:
        return "confirmed", risk
    if risk <= REJECT_AT:
        return "rejected", risk
    return "uncertain", risk


def _fallback(reason: str) -> dict[str, Any]:
    """VLM 미가용/실패 — 기존 동작 유지(억제 안 함)."""
    return {"available": False, "verdict": "uncertain", "risk": -1,
            "reason": reason, "suppress": False}


def confirm(image_bgr, rule: str, reason: str = "") -> dict[str, Any]:
    """CNN 의심 이벤트 → VLM 2차 판정. 절대 예외로 죽지 않는다.
    반환: {available, verdict, confidence, reason, suppress, raw?}
      · suppress=True 는 '고신뢰 오탐'일 때만(호출측은 그래도 기록은 남길 것)."""
    if image_bgr is None:
        return _fallback("이미지 없음")
    try:
        import rfdetr_service
    except Exception as ex:  # noqa: BLE001  mlx 등 의존성 미설치 → 폴백
        return _fallback(f"VLM 미가용({type(ex).__name__})")
    try:
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=build_prompt(rule, reason))
    except Exception as ex:  # noqa: BLE001  로드/추론 실패 → 폴백
        return _fallback(f"VLM 실패({type(ex).__name__})")
    if not isinstance(data, dict) or data.get("_error"):
        return _fallback(str(data.get("_error", "VLM 응답 오류")) if isinstance(data, dict) else "VLM 응답 오류")

    verdict, risk = classify(data)
    suppress = (0 <= risk <= SUPPRESS_AT)   # 위험확률이 충분히 낮을 때만 푸시 억제
    reason = str(data.get("이유", "")).strip()
    if not reason or any(t in reason for t in ("한 문장", "한국어 설명")):  # 소형 모델 placeholder echo
        reason = "(VLM 근거 미생성)"
    return {"available": True, "verdict": verdict, "risk": risk,
            "reason": reason, "suppress": suppress, "raw": data}


_SCENE_PROMPT = (
    "이 산업안전 CCTV 증거 사진을 보고, 무슨 작업·상황이 보이는지 한국어 한 문장으로 객관적으로 설명하라. "
    "보이는 것에만 근거하고 추측·과장하지 마라. JSON·코드블록 없이 한 문장만 출력하라."
)


def describe_scene(image_bgr) -> str:
    """증거 프레임 → 한국어 장면 설명 1문장(보조·초안). VLM 미가용/실패 시 빈 문자열(폴백)."""
    if image_bgr is None:
        return ""
    try:
        import rfdetr_service
        data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=_SCENE_PROMPT)
    except Exception:  # noqa: BLE001  의존성/추론 실패 → 폴백
        return ""
    if not isinstance(data, dict) or data.get("_error"):
        return ""
    # 자유문장 응답은 보통 raw 에, 혹은 값들에 들어온다. 합쳐서 한 줄로.
    txt = data.get("raw") or " ".join(
        str(v) for k, v in data.items() if not str(k).startswith("_") and k != "관련법령")
    txt = " ".join(str(txt).split())            # 개행·중복공백 정리
    if not txt or any(t in txt for t in ("한 문장", "코드블록", "JSON")):  # placeholder echo 방어
        return ""
    return txt[:200]
