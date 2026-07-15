"""P0-1 회귀 — Scribe evidence 경로 path traversal 차단.

_evidence_data_uri / _safe_evidence_path 가 data/evidence 하위로 격리되는지:
  - '../../../../etc/passwd' · '../.env' 등 탈출 경로 → None(파일 내용 노출 0)
  - 정상 evidence 경로(data/evidence/*.jpg) → 여전히 data URI 반환(저하 없음)
"""
import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

from agents import scribe as S  # noqa: E402

_PROJECT_ROOT = ROOT
_EVID = _PROJECT_ROOT / "data" / "evidence"


class TestScribePathTraversal(unittest.TestCase):
    def test_traversal_paths_blocked(self):
        """탈출 경로는 전부 None — 어떤 파일 내용도 반환하지 않는다."""
        for bad in ["../../../../etc/passwd", "../.env", "../../.env",
                    "/etc/passwd", "data/evidence/../../.env",
                    "data/evidence/../../../etc/hosts"]:
            self.assertIsNone(S._safe_evidence_path(bad), f"격리 실패: {bad}")
            self.assertIsNone(S._evidence_data_uri(bad), f"data_uri 유출 위험: {bad}")

    def test_real_secret_not_leaked_in_output(self):
        """실제 민감 파일(/etc/passwd)을 evidence 로 지정해도 그 내용이 결과에 안 섞인다."""
        # /etc/passwd 가 있으면 그 첫 토큰('root')이 data_uri 로 새지 않음을 증명
        pw = Path("/etc/passwd")
        if pw.exists():
            leaked = S._evidence_data_uri("../../../../etc/passwd")
            self.assertIsNone(leaked)
            # 혹시라도 문자열이 반환되면 base64 안에 실제 내용이 없어야 한다(이중 방어)
            if leaked:
                self.assertNotIn(b"root:", base64.b64decode(leaked.split(",", 1)[1]))

    def test_legitimate_evidence_still_works(self):
        """정상 data/evidence 경로는 여전히 동작(저하 없음)."""
        _EVID.mkdir(parents=True, exist_ok=True)
        tmp = _EVID / "_pytest_traversal_ok.jpg"
        # 최소 유효 바이트(내용은 무관 — 경로 격리·인코딩만 검증)
        tmp.write_bytes(b"\xff\xd8\xff\xe0JFIF-test-bytes")
        try:
            rel = str(tmp.relative_to(_PROJECT_ROOT))       # 'data/evidence/_pytest_traversal_ok.jpg'
            self.assertIsNotNone(S._safe_evidence_path(rel))
            uri = S._evidence_data_uri(rel)
            self.assertIsNotNone(uri)
            self.assertTrue(uri.startswith("data:image/"))
            # 왕복 디코딩 = 원본 바이트 보존
            self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), tmp.read_bytes())
        finally:
            tmp.unlink(missing_ok=True)

    def test_empty_and_none(self):
        self.assertIsNone(S._safe_evidence_path(""))
        self.assertIsNone(S._evidence_data_uri(""))


if __name__ == "__main__":
    unittest.main()
