"""CVAT for video XML → 정답지 변환(scripts/eval/cvat_to_gt.py) — 3프레임 모의 XML.

★무엇을 고정하는가
  1. **track ID 가 보존**된다 — 이것이 CVAT 으로 전환한 이유다(YOLO·COCO 로 내보내면 사라진다).
  2. `keyframe="1"`(사람이 찍음) → `human_verified`,
     `keyframe="0"`(CVAT 자동 보간) → `cvat_interp` 로 **구분**된다.
  3. `outside="1"` 프레임은 내보내지 않는다(그 프레임엔 사람이 없다).
  4. 판정 불가 속성은 `verdict="unresolvable"` + **track_id 제거**로 옮겨진다.
  5. 2fps 샘플링이 **라벨 후** 수행된다(원본 fps 격자에서 추림).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

# 원본 4fps · 3프레임(0·2·4 가 2fps 격자) · 640x480
MOCK_XML = """<?xml version="1.0" encoding="utf-8"?>
<annotations>
  <version>1.1</version>
  <meta>
    <task>
      <name>mock</name>
      <size>6</size>
      <original_size><width>640</width><height>480</height><fps>4.0</fps></original_size>
      <fps>4.0</fps>
    </task>
  </meta>
  <track id="3" label="person">
    <box frame="0" outside="0" keyframe="1" xtl="100" ytl="100" xbr="200" ybr="340"/>
    <box frame="2" outside="0" keyframe="0" xtl="150" ytl="100" xbr="250" ybr="340"/>
    <box frame="4" outside="0" keyframe="1" xtl="200" ytl="100" xbr="300" ybr="340"/>
  </track>
  <track id="7" label="NO-Hardhat">
    <box frame="0" outside="0" keyframe="1" xtl="120" ytl="100" xbr="180" ybr="140"/>
    <box frame="2" outside="1" keyframe="1" xtl="0" ytl="0" xbr="0" ybr="0"/>
    <box frame="4" outside="0" keyframe="1" xtl="220" ytl="100" xbr="280" ybr="140">
      <attribute name="unresolvable">true</attribute>
    </box>
  </track>
  <track id="9" label="Mask">
    <box frame="0" outside="0" keyframe="1" xtl="10" ytl="10" xbr="20" ybr="20"/>
  </track>
</annotations>
"""


class CvatToGtTest(unittest.TestCase):
    def setUp(self) -> None:
        import cvat_to_gt as C
        self.C = C
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = Path(self.tmp.name) / "mock.xml"
        self.xml.write_text(MOCK_XML, encoding="utf-8")
        self.parsed = C.parse_cvat(self.xml)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parses_meta_and_tracks(self) -> None:
        self.assertEqual(self.parsed["meta"]["fps"], 4.0)
        self.assertEqual(self.parsed["meta"]["size"], 6)
        self.assertEqual({t["id"] for t in self.parsed["tracks"]}, {3, 7, 9})

    def test_outside_box_is_dropped(self) -> None:
        """outside=1 은 '그 프레임엔 없음' 이므로 내보내지 않는다."""
        t7 = next(t for t in self.parsed["tracks"] if t["id"] == 7)
        self.assertEqual([b["frame"] for b in t7["boxes"]], [0, 4])

    def test_track_id_preserved(self) -> None:
        """★전환 이유 — track ID 가 프레임을 건너 살아남는다."""
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        tids = {b["track_id"] for f in g.values() for b in f["boxes"] if b.get("track_id") is not None}
        self.assertIn(3, tids)
        p_frames = [fr for fr, f in g.items() if any(b["track_id"] == 3 for b in f["boxes"])]
        self.assertEqual(sorted(p_frames), [0, 2, 4], "같은 트랙이 3프레임에 걸쳐 이어져야 한다")

    def test_keyframe_vs_interp_source(self) -> None:
        """사람이 찍은 키프레임과 CVAT 보간을 구분한다."""
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        by_frame = {fr: {b["track_id"]: b for b in f["boxes"]} for fr, f in g.items()}
        self.assertEqual(by_frame[0][3]["source"], "human_verified")
        self.assertEqual(by_frame[2][3]["source"], "cvat_interp")
        self.assertEqual(by_frame[4][3]["source"], "human_verified")

    def test_unresolvable_clears_track_id(self) -> None:
        """판정 불가는 verdict 로 옮기고 track_id 를 지운다(IDSW 분모에서 뺀다)."""
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        box = next(b for b in g[4]["boxes"] if b["cls"] == self.C.CLASSES.index("NO-Hardhat"))
        self.assertEqual(box["verdict"], "unresolvable")
        self.assertEqual(box["reason"], "low_quality")
        self.assertIsNone(box["track_id"])

    def test_excluded_class_dropped_silently(self) -> None:
        """★Mask 는 **의도적 제외**다 — 버그가 아니라 현장 조건에 따른 결정.

        2026-08-27 학원에서 보호구 경보 490건 중 87건이 마스크 단독 발화였고 81건이
        보호구를 갖춰 입은 장면이었다. 야외 중장비 실습장에서 마스크는 필수 보호구가 아니라
        학원 프로파일의 `ppe.required` 에서 뺐다(2026-08-28). 규칙이 안 보는 것은 라벨하지 않는다.
        ⚠전역 기본값은 3종 그대로 — 이 제외는 **학원 현장 한정**이다.
        """
        self.assertIn("Mask", self.C.EXCLUDED_CLASSES)
        self.assertIn("NO-Mask", self.C.EXCLUDED_CLASSES)
        self.assertNotIn("Mask", self.C.CLASSES)
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        self.assertEqual(len(g[0]["boxes"]), 2, "person·NO-Hardhat 만 남아야 한다")

    def test_excluded_and_unmapped_are_distinguished(self) -> None:
        """의도적 제외와 '스키마 밖 미지의 라벨' 은 **다르게** 다뤄야 한다.

        제외는 조용히 건너뛰고(집계만), 미지의 라벨은 경고 대상이다 — 오타일 수 있다.
        """
        typo_track = '<track id="9" label="Mask"></track>' + chr(10) + '  <track id="11" label="Hardhatt">'
        xml = self.xml.read_text(encoding="utf-8").replace('<track id="9" label="Mask">', typo_track)
        p2 = self.xml.with_name("mock2.xml")
        p2.write_text(xml, encoding="utf-8")
        parsed = self.C.parse_cvat(p2)
        labels = {t["label"] for t in parsed["tracks"]}
        self.assertIn("Hardhatt", labels, "오타 라벨이 파싱돼야 경고할 수 있다")
        excluded = [x for x in labels if x in self.C.EXCLUDED_CLASSES]
        unmapped = [x for x in labels if x not in self.C.CLASSES and x not in self.C.EXCLUDED_CLASSES]
        self.assertEqual(excluded, ["Mask"])
        self.assertEqual(unmapped, ["Hardhatt"], "오타는 '제외' 가 아니라 '미지' 로 분류돼야 한다")

    def test_box_normalized_cxcywh(self) -> None:
        """좌표가 정규화 cx,cy,w,h 로 바뀐다(기존 정답지 형식)."""
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        b = next(x for x in g[0]["boxes"] if x["track_id"] == 3)
        cx, cy, w, h = b["box"]
        self.assertAlmostEqual(cx, 150 / 640, places=6)
        self.assertAlmostEqual(cy, 220 / 480, places=6)
        self.assertAlmostEqual(w, 100 / 640, places=6)
        self.assertAlmostEqual(h, 240 / 480, places=6)

    def test_fps_sampling_after_labeling(self) -> None:
        """2fps 추림이 라벨 후에 일어난다 — 4fps 원본에서 짝수 프레임만."""
        g = self.C.to_gt(self.parsed, 2.0, 640, 480)
        self.assertEqual(sorted(g), [0, 2, 4])
        self.assertEqual(g[2]["t_ms"], 500, "4fps 의 2번 프레임 = 500ms")

    def test_missing_fps_raises(self) -> None:
        """원본 fps 를 모르면 조용히 넘어가지 않고 멈춘다(규칙 11)."""
        p = dict(self.parsed)
        p["meta"] = {**p["meta"], "fps": 0.0}
        with self.assertRaises(ValueError):
            self.C.to_gt(p, 2.0, 640, 480)


if __name__ == "__main__":
    unittest.main()
