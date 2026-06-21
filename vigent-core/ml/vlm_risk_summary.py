"""이벤트 프레임 → mlx-vlm(Qwen2.5-VL, MLX/MIT) 로 '위험 요약'을 JSON 으로 받기.

전부 로컬(Apple Silicon MLX) — 영상이 외부 서버로 나가지 않는다(규칙 2·3).
사용: python3 vigent-core/ml/vlm_risk_summary.py <이미지경로>
출력: 위험요인·위험등급·권고조치 JSON (runs/rfdetr/vlm_<파일명>.json 저장)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# 기본값(테마 vision.yaml 에 vlm 블록이 없을 때만 사용 — 규칙 6: 절대 저하 없음)
_DEFAULT_MODEL = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"   # ~2-3GB(1회 다운로드)
_DEFAULT_PROMPT = (
    "당신은 한국 산업안전 관제 분석가다. 답변은 무조건 한국어(Korean)로만 한다. "
    "절대 영어·중국어·일본어를 쓰지 마라.\n"
    "이 CCTV 프레임을 보고 작업장 위험을 분석해, 아래 JSON 하나만 출력하라(설명·코드블록 금지):\n"
    '{"위험요인": "한국어 설명", "위험등급": "낮음 또는 중간 또는 높음", '
    '"근거": "한국어 설명", "권고조치": "한국어 설명"}\n'
    "보이는 것에만 근거해 모든 값을 한국어로 간결히 작성하라."
)


def _load_vlm_config() -> tuple[str, str]:
    """테마(vision.yaml)에서 VLM 모델·프롬프트를 읽는다. 없으면 기본값(폴백).
    VIGENT_THEME 환경변수로 테마 선택(기본 safety) → office·sports 확장 시 그대로 재사용."""
    import os
    theme = os.environ.get("VIGENT_THEME", "safety")
    vy = ROOT / "themes" / theme / "vision.yaml"
    model, prompt = _DEFAULT_MODEL, _DEFAULT_PROMPT
    try:
        import yaml
        cfg = yaml.safe_load(vy.read_text(encoding="utf-8")) or {}
        v = cfg.get("vlm") or {}
        model = v.get("model") or model
        prompt = v.get("prompt") or prompt
    except Exception:   # noqa: BLE001  설정 못 읽어도 기본값으로 동작(저하 없음)
        pass
    return model, prompt


MODEL, PROMPT = _load_vlm_config()


def _enrich_with_law(data: dict) -> dict:
    """Copilot 으로 '관련법령'을 보강. Copilot 미가용/실패해도 원본 그대로(저하 없음)."""
    try:
        import sys
        sys.path.insert(0, str(ROOT / "vigent-core"))
        from agents.copilot import CopilotAgent
        return CopilotAgent(config={}).enrich_vlm(data)
    except Exception:   # noqa: BLE001
        return data


def _is_korean(data: dict) -> bool:
    """JSON 값에 한글이 충분히 들어있는지(중국어/영어 새는지 감지)."""
    blob = " ".join(str(v) for k, v in data.items() if k != "위험등급")
    if not blob.strip():
        return True
    kr = sum(1 for ch in blob if "가" <= ch <= "힣")
    cjk = sum(1 for ch in blob if "一" <= ch <= "鿿")   # 한자(중국어)
    return kr >= max(3, cjk)   # 한글이 한자보다 많아야 OK


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"raw": text.strip()}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"raw": text.strip()}


def _safe_image(img_path: str, max_side: int = 1024) -> str:
    """Qwen2.5-VL 은 특정 해상도(예: 960x540)에서 생성이 깨진다.
    패치 크기(28)의 배수로 리사이즈해 안전한 임시 이미지를 만든다."""
    from PIL import Image
    im = Image.open(img_path).convert("RGB")
    w, h = im.size
    s = min(1.0, max_side / max(w, h))
    nw, nh = max(28, int(w * s) // 28 * 28), max(28, int(h * s) // 28 * 28)
    out = Path("/tmp") / f"vlm_in_{Path(img_path).stem}.jpg"
    im.resize((nw, nh)).save(out)
    return str(out)


class RiskVLM:
    """모델을 1회 로드해 재사용하는 위험요약 VLM (통합 파이프라인에서 사용)."""

    def __init__(self):
        from mlx_vlm import load, generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config
        self._generate = generate
        self._apply = apply_chat_template
        t0 = time.time()
        self.model, self.processor = load(MODEL)
        self.config = load_config(MODEL)
        print(f"[vlm] 모델 로드 {time.time()-t0:.1f}s")

    def _ask(self, safe: str, prompt: str) -> dict:
        fmt = self._apply(self.processor, self.config, prompt, num_images=1)
        # 안정성: 낮은 temperature + 반복 억제(같은 말 반복/degeneration 방지)
        res = self._generate(self.model, self.processor, fmt, image=safe,
                             max_tokens=200, temperature=0.2, repetition_penalty=1.15,
                             verbose=False)
        text = res if isinstance(res, str) else getattr(res, "text", str(res))
        return extract_json(text)

    def summarize(self, img_path: str) -> dict:
        """이벤트 프레임 → 위험요약 JSON. 절대 예외로 죽지 않는다(모니터링 안정성).
        한국어가 아니면 1회 재시도. 그래도 안 되면 경고 플래그를 달아 그대로 반환.
        끝으로 Copilot 으로 '관련법령'을 보강한다(빈 값일 때만 — 규칙 6 가산)."""
        try:
            safe = _safe_image(img_path)
            data = self._ask(safe, PROMPT)
            if not _is_korean(data):
                data2 = self._ask(safe, PROMPT + "\n주의: 이전 답이 한국어가 아니었다. 반드시 한국어로만.")
                if _is_korean(data2):
                    data = data2
                else:
                    data2.setdefault("_warn", "VLM이 한국어로 답하지 않음(작은 모델 한계)")
                    data = data2
            return _enrich_with_law(data)
        except Exception as ex:   # noqa: BLE001  VLM 실패가 파이프라인을 멈추지 않게
            return {"_error": f"VLM 요약 실패: {type(ex).__name__}", "위험등급": "미상"}


def main(img_path: str) -> None:
    vlm = RiskVLM()
    t1 = time.time()
    data = vlm.summarize(img_path)
    print(f"[vlm] 생성 {time.time()-t1:.1f}s")
    out = ROOT / "runs" / "rfdetr" / f"vlm_{Path(img_path).stem}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("─── 위험 요약(JSON) ───")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"✅ 저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python3 vigent-core/ml/vlm_risk_summary.py <이미지경로>")
        sys.exit(1)
    main(sys.argv[1])
