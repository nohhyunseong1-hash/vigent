"""[CODE_REVIEW M8-4(b)] 시연 화면(realtime_core.js) 개인정보·유출 경로 정적 게이트.

대표 결정(2026-09-06): 성별·연령·감정 추정 함수와 브라우저→클라우드(Anthropic·OpenAI·Gemini) 직접 호출 함수를 삭제한다.
  · 근거: 얼굴 랜드마크로 성별·연령·감정을 추정하는 것은 산업안전 감시 목적 밖의 민감정보 추정.
  · 근거: 현장 프레임+API 키를 브라우저에서 외부로 보내는 코드는 F-12(영상 현장 외 불유출) 원칙 위반(호출부 0 이었어도 경로 자체가 위험).
이 테스트는 그 심볼·도메인이 다시 들어오지 않게 막는다. node 가 있으면 구문 검사도 한다(없으면 건너뜀).
"""
import shutil
import subprocess
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_JS = _ROOT / "vigent-core" / "static" / "realtime_core.js"
_PAGES = sorted((_ROOT / "themes" / "safety").glob("*.html"))

_FORBIDDEN = (
    "function estimateGender(", "function estimateAge(", "function detectEmotion(",
    "estimateGender(f", "estimateAge(f", "detectEmotion(f",
    "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
    "anthropic-dangerous-direct-browser-access",
    "function analyzeWithClaude(", "function analyzeWithOpenAI(", "function analyzeWithGemini(",
)


class FrontendPrivacyGate(unittest.TestCase):
    def test_no_sensitive_inference_or_cloud_direct_calls(self):
        text = _JS.read_text(encoding="utf-8", errors="replace")
        hits = [s for s in _FORBIDDEN if s in text]
        self.assertEqual(hits, [], f"삭제된 민감 추정/클라우드 직접호출이 다시 들어왔다: {hits}")
        for p in _PAGES:
            t = p.read_text(encoding="utf-8", errors="replace")
            bad = [s for s in ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com") if s in t]
            self.assertEqual(bad, [], f"{p.name}: 브라우저 → 클라우드 직접 호출 도메인")

    def test_js_syntax_if_node_available(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 없음 — 구문 검사 생략")
        r = subprocess.run([node, "--check", str(_JS)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
