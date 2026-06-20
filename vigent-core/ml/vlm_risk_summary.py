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
MODEL = "mlx-community/Qwen2.5-VL-3B-Instruct-4bit"   # ~2-3GB(1회 다운로드)

PROMPT = (
    "당신은 산업안전 관제 분석가다. 이 CCTV 프레임을 보고 작업장 위험을 분석하라.\n"
    "반드시 아래 JSON 형식 하나만 출력하라(설명·코드블록 금지):\n"
    '{"위험요인": "...", "위험등급": "낮음|중간|높음", "근거": "...", "권고조치": "..."}\n'
    "한국어로, 보이는 것에만 근거해 간결히."
)


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

    def summarize(self, img_path: str) -> dict:
        safe = _safe_image(img_path)
        fmt = self._apply(self.processor, self.config, PROMPT, num_images=1)
        res = self._generate(self.model, self.processor, fmt, image=safe,
                             max_tokens=256, verbose=False)
        text = res if isinstance(res, str) else getattr(res, "text", str(res))
        return extract_json(text)


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
