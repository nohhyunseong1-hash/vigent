"""CODE_AUDIT_20260928 C-2 — 감사 문서에 A·B·C 그룹 완료 상태(커밋 해시)·실기 미검증 표가 있다. [2026-09-28]"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
A_COMMITS = ("6df1ef6", "f40596d", "75b6285", "4edb5af", "aecc5d3", "69166e1", "2bce623", "78d8c11", "286f1ef", "af34d11")


class C2(unittest.TestCase):
    def test_audit_doc_has_status_tables(self):
        s = (_ROOT / "docs/review/CODE_AUDIT_20260928.md").read_text(encoding="utf-8")
        self.assertIn("## 0-1. 수정 완료 상태", s)
        for h in A_COMMITS:
            self.assertIn(h, s, h)
        self.assertIn("## 0-2. 실기 미검증", s)
        self.assertRegex(s, r"\| B-2 [^|]*\| `[0-9a-f]{7}` \|"); self.assertRegex(s, r"\| C-1 [^|]*\| `[0-9a-f]{7}` \|")
        hashes = re.findall(r"`([0-9a-f]{7})`", s.split("## 0-1.")[1].split("## 0-2.")[0])
        self.assertGreaterEqual(len(set(hashes)), 16, "A 10 + B 5 + C 1 이상의 커밋 해시가 표에 있어야 한다")


if __name__ == "__main__":
    unittest.main()
