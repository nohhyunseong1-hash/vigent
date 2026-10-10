"""tests/test_legal_gate_failclosed.py — 법령 게이트 fail-closed·재적재 회귀 (2단계 A-5+A-9, 2026-10-10).

배경(점검 실측): ① statutes.yaml 이 없거나 import 시점에 못 읽히면 게이트가 '비활성
(전부 통과)'가 돼 VLM 환각 조문이 평가서에 그대로 인용됐다(fail-open) — copilot 의
fail-closed 는 게이트가 '예외를 던질 때'만 동작하고 '조용히 비활성'은 못 막았다.
② `_WL = load_whitelist()` 가 import 시 1회라 파일을 나중에 넣어도 재시작까지 비활성.
③ `import yaml` 의 무주석 except Exception 이 사유를 침묵시켰다(A-9).
→ gate_vlm_text 미로드 시 '안전관리자 확인 필요(사유)' 치환 + ERROR 1회 로그,
지연 적재 + 파일 변경 감지 재적재, ImportError 한정 + 사유 포함으로 수정(사용자 승인).

격리: _STATUTES·_BLOCKED_LOG 를 임시 경로로 바꾸고 캐시를 비운다(운영 data/ 불변).
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import legal_whitelist as L  # noqa: E402

MINI_YAML = """
statutes:
  - id: osha_38
    law: 산업안전보건법
    law_key: osha
    article: 제38조
    article_from: 38
    article_to: 38
    status: active
"""


class TestLegalGateFailClosed(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="vigent_test_legal_")
        self._saved = (L._STATUTES, L._BLOCKED_LOG, dict(L._WL_CACHE))
        L._STATUTES = Path(self._tmp.name) / "statutes.yaml"          # 기본: 파일 없음
        L._BLOCKED_LOG = Path(self._tmp.name) / "blocked.log"
        L._WL_CACHE.clear()

    def tearDown(self):
        L._STATUTES, L._BLOCKED_LOG, saved_cache = self._saved
        L._WL_CACHE.clear()
        L._WL_CACHE.update(saved_cache)
        self._tmp.cleanup()

    def test_missing_file_blocks_generated_text(self):
        """핵심: 파일 없음 → VLM 생성 조문이 통과되지 않고, 사유가 담긴 안내문으로 치환."""
        with self.assertLogs("vigent.legal", level="ERROR"):
            out = L.gate_vlm_text("산업안전보건법 제38조에 따라 조치하라")
        self.assertNotIn("제38조", out, "미로드 상태에서 생성 조문이 통과되면 안 된다")
        self.assertIn("안전관리자 확인 필요", out)
        self.assertIn("법령 게이트 미로드", out)
        self.assertIn("statutes.yaml 없음", out)     # 사용자에게 원인이 보여야 한다

    def test_error_logged_once_per_reason(self):
        with self.assertLogs("vigent.legal", level="ERROR") as cm:
            L.gate_vlm_text("아무 조문")
        self.assertEqual(len(cm.output), 1)
        # 같은 사유의 두 번째 호출은 ERROR 재발행 없음(로그 폭주 방지) — assertLogs 는
        # 로그 0건이면 실패하므로 더미 ERROR 를 하나 섞어 '게이트 ERROR 없음'을 검증한다
        import logging
        with self.assertLogs("vigent.legal", level="ERROR") as cm2:
            L.gate_vlm_text("아무 조문")
            logging.getLogger("vigent.legal").error("더미")
        self.assertEqual(len(cm2.output), 1, "같은 사유 반복에 ERROR 가 또 나면 안 된다")

    def test_file_added_later_reactivates_without_restart(self):
        """[A-5 ②] 재시작 없이 재적재 — 미로드로 차단되던 상태에서 파일이 생기면 즉시 정상 판정."""
        self.assertIn("안전관리자 확인 필요", L.gate_vlm_text("산업안전보건법 제38조"))
        L._STATUTES.write_text(MINI_YAML, encoding="utf-8")
        self.assertEqual(L.gate_vlm_text("산업안전보건법 제38조"), "산업안전보건법 제38조")
        self.assertIn("안전관리자 확인 필요", L.gate_vlm_text("산업안전보건법 제999조"))

    def test_normal_config_unchanged(self):
        """정상 설정(실제 저장소 statutes.yaml)에서 기존 동작 보존 — 목록 내 통과·밖 치환."""
        L._STATUTES = ROOT / "data" / "legal" / "statutes.yaml"
        L._WL_CACHE.clear()
        self.assertTrue(L._wl().get("enabled"))
        self.assertEqual(L.gate_vlm_text("산업안전보건법 제36조"), "산업안전보건법 제36조")
        self.assertEqual(L.gate_vlm_text("산업안전보건법 제999조"), "안전관리자 확인 필요")

    def test_audit_path_still_nondestructive_when_unloaded(self):
        """감사(audit_citations)는 원래 비파괴 — 미로드 시 기존대로 빈 목록(문서 불변)."""
        self.assertEqual(L.audit_citations([{"source": "산업안전보건법", "clause": "제999조"}], "test"), [])


if __name__ == "__main__":
    unittest.main()
