"""[CODE_REVIEW M6-1·M6-2] pin 목록 자체 삭제 방지 + 경로 구분자 무관 pin 비교 + 구 위치 마이그레이션.

실측(2026-09-06, 임시 디렉터리 시뮬): ① `data/evidence/pinned.json` 이 40일 지나면 삭제 후보에 올랐다(모든 pin 해제)
② `/` 로 pin 한 파일이 Windows 경로(`\\`)와 매칭되지 않아 후보에 올랐다. 계약:
  ① pin 목록은 evidence 폴더 밖(data/retention/pinned.json)에 두고, 어디에 있든 이름이 pinned.json 이면 후보 제외
  ② 구 위치의 목록은 첫 접근에서 1회 병합·이동(마이그레이션), 구 형식(list)도 읽는다
  ③ `\\`·`/`·상대·절대 표기와 무관하게 pin 이 보호된다(resolve 비교)
  ④ pin 사유를 저장한다(manual / alert:<id>)
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import data_engine  # noqa: E402
import retention  # noqa: E402


def _old(p: Path, days: float = 40.0) -> None:
    t = time.time() - days * 86400
    os.utime(p, (t, t))


class PinHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.ev = root / "data" / "evidence"
        (self.ev / "20260701").mkdir(parents=True)
        for name in ("keep_slash.jpg", "keep_backslash.jpg", "drop.jpg"):
            p = self.ev / "20260701" / name
            p.write_bytes(b"x")
            _old(p)
        ps = [mock.patch.object(retention, "_ROOT", root),
              mock.patch.dict(retention.GROUP_DIRS, {"evidence": self.ev}),
              mock.patch.object(data_engine, "_ROOT", root),
              mock.patch.object(data_engine, "_EVIDENCE", self.ev),
              mock.patch.object(data_engine, "_PINNED", root / "data" / "retention" / "pinned.json"),
              mock.patch.object(data_engine, "_PINNED_LEGACY", self.ev / "pinned.json")]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def _cands(self):
        return [Path(c["path"]).as_posix() for c in retention.scan_group("evidence", 30)["candidates"]]

    def test_pin_file_itself_is_never_a_candidate(self):
        legacy = self.ev / "pinned.json"
        legacy.write_text("[]", encoding="utf-8")
        _old(legacy)
        cands = self._cands()
        self.assertFalse(any(c.endswith("pinned.json") for c in cands), f"pin 목록 파일이 후보에 올랐다: {cands}")

    def test_mixed_separators_are_all_protected(self):
        data_engine.pin_evidence("data/evidence/20260701/keep_slash.jpg")            # posix 표기
        data_engine.pin_evidence("data\\evidence\\20260701\\keep_backslash.jpg")     # Windows 표기
        cands = self._cands()
        self.assertEqual(cands, ["data/evidence/20260701/drop.jpg"], f"pin 된 파일이 후보에 남았다: {cands}")

    def test_legacy_location_is_migrated_once(self):
        legacy = self.ev / "pinned.json"
        legacy.write_text(json.dumps(["data/evidence/20260701/keep_slash.jpg"]), encoding="utf-8")   # 구 형식(list)
        pins = data_engine.pinned_map()
        self.assertEqual(pins, {"data/evidence/20260701/keep_slash.jpg": "manual"})
        self.assertFalse(legacy.exists(), "구 위치 파일은 이동 후 제거돼야 한다")
        self.assertTrue(data_engine._PINNED.exists())
        self.assertNotIn("data/evidence/20260701/keep_slash.jpg", self._cands())

    def test_reason_is_stored_and_unpin_removes(self):
        data_engine.pin_evidence("data/evidence/20260701/drop.jpg", reason="alert:42")
        self.assertEqual(data_engine.pinned_map()["data/evidence/20260701/drop.jpg"], "alert:42")
        data_engine.unpin_evidence("data\\evidence\\20260701\\drop.jpg")
        self.assertNotIn("data/evidence/20260701/drop.jpg", data_engine.pinned_map())
        self.assertIn("data/evidence/20260701/drop.jpg", self._cands())

    def test_new_pin_file_lives_outside_swept_groups(self):
        data_engine.pin_evidence("data/evidence/20260701/keep_slash.jpg")
        self.assertFalse(str(data_engine._PINNED).startswith(str(self.ev)))
        self.assertNotIn("retention", retention.GROUP_DIRS)


if __name__ == "__main__":
    unittest.main()
