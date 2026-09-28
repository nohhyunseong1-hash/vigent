"""CODE_AUDIT_20260928 B-4 — 절대경로 제거. [2026-09-28]

★무엇을 고정하는가
  ① configs/finetune_*.yaml 의 값(주석 제외)에 D:/ 절대경로가 없고 ${VIGENT_DATA_DIR} 를 쓴다.
  ② finetune_rfdetr.expand_path 가 ${VIGENT_DATA_DIR} 를 env(없으면 data_paths.data_dir) 로 치환한다.
  ③ data_paths.field_root() 는 VIGENT_FIELD_ROOT 우선, 없으면 미디어 루트 옆 vigent_field.
  ④ 감사가 지목한 스크립트의 **코드 문자열 상수**(docstring 제외)에 D:\\vigent_… / D:/vigent_… 가 없다(사용 예시 docstring 은 허용).
"""
from __future__ import annotations

import ast
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "train"))

import data_paths  # noqa: E402
import finetune_rfdetr as F  # noqa: E402

AUDITED = ["scripts/train/finetune_rfdetr.py", "scripts/eval/forklift_compare_harness.py", "scripts/eval/forklift_field_yardstick.py",
           "scripts/eval/forklift_aihub_imagelevel.py", "scripts/eval/forklift_field_rerun.py", "scripts/eval/forklift_box_geom.py",
           "scripts/eval/forklift_fp_dump.py", "scripts/eval/scan_507_unlabeled.py", "scripts/eval/head_box_stats.py",
           "scripts/build_report_v12.py", "scripts/data/field_prelabel.py"]
_ABS = re.compile(r"D:[/\\]+vigent", re.IGNORECASE)


def code_string_literals(path: Path) -> list[str]:
    """docstring 이 아닌 문자열 상수 전부."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


class Configs(unittest.TestCase):
    def test_no_absolute_paths_in_values(self):
        for f in sorted((_ROOT / "configs").glob("finetune_*.yaml")):
            for i, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = ln.split("#", 1)[0]
                self.assertIsNone(_ABS.search(code), f"{f.name}:{i}: {code.strip()}")
        aihub = [f for f in (_ROOT / "configs").glob("finetune_aihub_*.yaml") if "labels:" in f.read_text(encoding="utf-8")]
        self.assertTrue(aihub, "labels: 소스를 가진 aihub 설정이 하나도 없다")
        for f in aihub:
            self.assertIn("${VIGENT_DATA_DIR}", f.read_text(encoding="utf-8"), f.name)


class ExpandPath(unittest.TestCase):
    def test_data_dir_default_and_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIGENT_DATA_DIR", None)
            self.assertEqual(F.expand_path("${VIGENT_DATA_DIR}/aihub/x"), str(data_paths.data_dir()) + "/aihub/x")
        with mock.patch.dict(os.environ, {"VIGENT_DATA_DIR": "/mnt/data"}):
            self.assertEqual(F.expand_path("${VIGENT_DATA_DIR}/aihub/x"), "/mnt/data/aihub/x")
        self.assertEqual(F.expand_path("plain/path"), "plain/path"); self.assertEqual(F.expand_path("${UNKNOWN_X}/a"), "${UNKNOWN_X}/a")
        self.assertFalse(_ABS.search(F.FIELD_DIR_DEFAULT) and not str(data_paths.data_dir()).lower().startswith("d:"), F.FIELD_DIR_DEFAULT)


class FieldRoot(unittest.TestCase):
    def test_field_root(self):
        with mock.patch.dict(os.environ, {"VIGENT_FIELD_ROOT": str(_ROOT / "tests")}):
            self.assertEqual(data_paths.field_root(), (_ROOT / "tests").resolve())
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIGENT_FIELD_ROOT", None)
            self.assertEqual(data_paths.field_root(), data_paths.data_dir().parent / "vigent_field")


class ScriptsNoLiteral(unittest.TestCase):
    def test_audited_scripts_have_no_absolute_path_literals(self):
        for rel in AUDITED:
            bad = [s for s in code_string_literals(_ROOT / rel) if _ABS.search(s)]
            self.assertEqual(bad, [], f"{rel}: {bad[:3]}")


if __name__ == "__main__":
    unittest.main()
