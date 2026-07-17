"""runtime_config 읽기 우선순위 테스트 (B2).

config/ 는 커밋된 읽기전용 시드, data/<cfg_rel> 는 런타임 write 대상(gitignore).
read_path 는 런타임 우선 → 없으면 시드 폴백. runtime_path 는 항상 data/ 하위.
tmp root 로 3가지 상태(시드만 / 런타임만 / 둘 다)를 격리 검증한다.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import runtime_config  # noqa: E402


class TestRuntimeConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.rel = "config/danger_zone.json"
        (self.root / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "config").mkdir(parents=True, exist_ok=True)
        self.seed = self.root / self.rel                      # config/danger_zone.json
        self.rt = self.root / "data" / self.rel               # data/config/danger_zone.json

    def tearDown(self):
        self._tmp.cleanup()

    def test_runtime_path_is_under_data(self):
        self.assertEqual(runtime_config.runtime_path(self.rel, self.root), self.rt)

    def test_seed_only_reads_seed(self):
        # 시드만 존재(fresh clone / CI) → read_path 는 config/ 시드를 가리킨다
        self.seed.write_text('{"points": [1]}', encoding="utf-8")
        self.assertEqual(runtime_config.read_path(self.rel, self.root), self.seed)

    def test_runtime_only_reads_runtime(self):
        # 런타임만 존재 → read_path 는 data/ 를 가리킨다
        self.rt.write_text('{"points": [2]}', encoding="utf-8")
        self.assertEqual(runtime_config.read_path(self.rel, self.root), self.rt)

    def test_both_prefers_runtime(self):
        # 둘 다 존재 → 런타임(data/) 우선(사용자가 그린 값이 시드를 덮는다)
        self.seed.write_text('{"points": [1]}', encoding="utf-8")
        self.rt.write_text('{"points": [2]}', encoding="utf-8")
        self.assertEqual(runtime_config.read_path(self.rel, self.root), self.rt)

    def test_neither_falls_back_to_seed_path(self):
        # 둘 다 없으면 시드 경로 반환(존재하지 않아도 호출부가 .exists() 로 처리)
        self.assertEqual(runtime_config.read_path(self.rel, self.root), self.seed)


if __name__ == "__main__":
    unittest.main()
