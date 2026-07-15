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


def prompt_for_theme(theme: str) -> str:
    """특정 테마(vision.yaml)의 VLM 프롬프트를 반환(office·sports 등). 없으면 기본값."""
    vy = ROOT / "themes" / theme / "vision.yaml"
    try:
        import yaml
        v = (yaml.safe_load(vy.read_text(encoding="utf-8")) or {}).get("vlm") or {}
        return v.get("prompt") or PROMPT
    except Exception:   # noqa: BLE001
        return PROMPT


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


def format_facts(detections, in_danger_zone: bool = False) -> str:
    """YOLO 탐지결과 → '확인된 사실' 문자열(폐쇄형 검증용). 클래스·신뢰도·구역침입만.
    detections=[{label/cls/class, conf/confidence}, ...]. 없거나 유효항목 0개면 빈 문자열(→ 기존 개방형 폴백).
    사람은 명수(+위험구역 내부/외부)로, 나머지는 '라벨(0.91)' 로 나열한다."""
    if not detections:
        return ""
    persons: list[Any] = []
    others: list[str] = []
    for d in detections or []:
        if not isinstance(d, dict):
            continue
        label = str(d.get("label") or d.get("cls") or d.get("class") or "").strip()
        if not label:
            continue
        conf = d.get("conf", d.get("confidence"))
        if label.lower() in ("person", "사람"):
            persons.append(conf)
        else:
            try:
                c = f"({float(conf):.2f})" if conf is not None else ""
            except (TypeError, ValueError):
                c = ""
            others.append(f"{label}{c}")
    parts: list[str] = []
    if persons:
        parts.append(f"사람 {len(persons)}명({'위험구역 내부' if in_danger_zone else '위험구역 외부'})")
    parts.extend(others)
    if not parts:
        return ""
    return ("확인된 탐지 사실(신뢰도 높음): " + ", ".join(parts)
            + ". 이 목록은 CNN이 확정한 사실이다.")


class RiskVLM:
    """모델을 1회 로드해 재사용하는 위험요약 VLM (통합 파이프라인에서 사용)."""

    def __init__(self):
        # 지연 로딩: MLX 모델은 실제로 MLX 추론(_ask/quick)이 필요할 때만 로드한다.
        # OpenAI 비전 라우팅으로 처리되는 경우 무거운 MLX 로드를 아예 하지 않게 해 첫 호출을 빠르게.
        self._loaded = False
        self._generate = None
        self._apply = None
        self.model = self.processor = self.config = None

    def _ensure_loaded(self):
        """MLX 모델 1회 로드(최초 MLX 추론 시). 이미 로드됐으면 즉시 반환."""
        if self._loaded:
            return
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config
        self._generate = generate
        self._apply = apply_chat_template
        t0 = time.time()
        self.model, self.processor = load(MODEL)
        self.config = load_config(MODEL)
        self._loaded = True
        print(f"[vlm] 모델 로드 {time.time()-t0:.1f}s")

    def _ask_openai(self, safe: str, prompt: str, max_tokens: int = 260) -> dict | None:
        """OpenAI 비전으로 동일 프롬프트 질의(키 있을 때만·수 초). 데모 성능용 라우팅.
        키 없거나 실패면 None 을 돌려 호출부가 기존 MLX 경로로 폴백하게 한다(규칙6: 저하0)."""
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        try:
            import sys

            import cv2
            sys.path.insert(0, str(ROOT / "vigent-core"))
            import llm_provider
            img = cv2.imread(safe)
            if img is None:
                return None
            text, _backend = llm_provider.reason_vision(img, prompt)
            if not text:
                return None
            return extract_json(text)              # MLX 경로와 동일 파서 재사용(포맷 일치)
        except Exception:  # noqa: BLE001  실패는 조용히 MLX 폴백
            return None

    def _ask(self, safe: str, prompt: str, max_tokens: int = 260) -> dict:
        self._ensure_loaded()                     # MLX 실제 사용 시에만 로드(지연)
        fmt = self._apply(self.processor, self.config, prompt, num_images=1)
        # 안정성: 낮은 temperature + 반복 억제(같은 말 반복/degeneration 방지)
        res = self._generate(self.model, self.processor, fmt, image=safe,
                             max_tokens=max_tokens, temperature=0.2, repetition_penalty=1.15,
                             verbose=False)
        text = res if isinstance(res, str) else getattr(res, "text", str(res))
        return extract_json(text)

    def quick(self, img_path: str, prompt: str, max_tokens: int = 64, max_side: int = 640) -> dict:
        """빠른 단발 질의 — 작은 이미지·짧은 토큰·재시도/법령보강 없음(PPE 등 단답용).
        반환: {"raw": 원문텍스트}. 절대 예외로 죽지 않는다."""
        try:
            self._ensure_loaded()                 # MLX 실제 사용 시에만 로드(지연)
            safe = _safe_image(img_path, max_side=max_side)
            fmt = self._apply(self.processor, self.config, prompt, num_images=1)
            res = self._generate(self.model, self.processor, fmt, image=safe,
                                 max_tokens=max_tokens, temperature=0.0, repetition_penalty=1.1,
                                 verbose=False)
            text = res if isinstance(res, str) else getattr(res, "text", str(res))
            return {"raw": text}
        except Exception as ex:  # noqa: BLE001
            return {"_error": f"VLM quick 실패: {type(ex).__name__}"}

    def summarize(self, img_path: str, prompt: str | None = None,
                  max_tokens: int = 260, enrich: bool = True, facts: str | None = None) -> dict:
        """이벤트 프레임 → 위험요약 JSON. 절대 예외로 죽지 않는다(모니터링 안정성).
        prompt 를 주면 그 테마 프롬프트로(office·sports). 없으면 기본(safety).
        max_tokens: 긴 통합 JSON을 받을 때 늘림(기본 260). enrich=False면 법령보강 생략(통합호출용).
        facts(=format_facts 결과)가 있으면 '폐쇄형 검증' 프롬프트로: 확정 사실을 모두 반영·날조 금지.
          facts=None 이면 기존 개방형 프롬프트 그대로(규칙 6: 폴백=절대 저하 없음).
        한국어가 아니면 1회 재시도. 끝으로 Copilot 으로 '관련법령'을 보강(빈 값일 때만)."""
        p = prompt or PROMPT
        if facts:
            # 폐쇄형: 확정 사실을 앞에 주입 + 규칙. 기존 JSON 스키마는 p 가 그대로 정의.
            p = (f"아래는 신뢰도 높은 탐지 사실이다:\n{facts}\n"
                 "규칙: (1) 이 사실의 모든 항목을 반드시 판단에 반영하라(하나도 빠뜨리지 마라). "
                 "(2) 목록에 없는 위험을 새로 지어내지 마라. 이미지는 자세·환경 보강에만 써라. "
                 "(3) 법령 조항 번호를 지어내지 마라(모르면 생략).\n"
                 "출력: 각 항목의 위험등급(상/중/하)과 조치, 가장 시급한 항목을 포함하되 "
                 "아래 JSON 스키마를 유지하라.\n\n" + p)
        try:
            safe = _safe_image(img_path)
            # OpenAI 비전 우선(키 있으면 빠른 프론티어 ~수 초). 없거나 실패면 아래 MLX 경로 그대로(폴백=저하0).
            odata = self._ask_openai(safe, p, max_tokens=max_tokens)
            if odata is not None:
                return _enrich_with_law(odata) if enrich else odata
            # ── 이하 기존 MLX 경로(불변) ──
            data = self._ask(safe, p, max_tokens=max_tokens)
            if not _is_korean(data):
                data2 = self._ask(safe, p + "\n주의: 이전 답이 한국어가 아니었다. 반드시 한국어로만.",
                                  max_tokens=max_tokens)
                if _is_korean(data2):
                    data = data2
                else:
                    data2.setdefault("_warn", "VLM이 한국어로 답하지 않음(작은 모델 한계)")
                    data = data2
            return _enrich_with_law(data) if enrich else data
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
