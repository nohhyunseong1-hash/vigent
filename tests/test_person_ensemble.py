"""[P-2] person 이중 신호 앙상블(PERSON_ENSEMBLE) 회귀 테스트.

실제 모델 없이 GuardAgent.__new__() + 가짜 어댑터(고정 박스 반환)로 detect() 전체 경로를
실행한다 — _cross_validate_ppe → 앙상블 필터(_drop_ppe_origin_person) → _track →
_merge_cross_source_person 순서가 실제로 그렇게 연결돼 있는지, 플래그 on/off 각각과
추적·containment·교차게이트가 뒤섞인 박스를 정상 처리하는지 검증한다(사용자 지시 확인2).
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402

_FAKE_IMG = np.zeros((10, 10, 3), dtype=np.uint8)   # detect() 가 .shape 만 읽고 실제 픽셀은 안 씀


class _FakeModel:
    """detect(image_bgr, conf, imgsz, augment) → 고정 박스 목록. conf 이하는 실제 어댑터처럼 걸러낸다."""

    def __init__(self, boxes):
        self._boxes = boxes  # [{"label":..., "bbox":[x1,y1,x2,y2], "conf":...}]

    def detect(self, image_bgr, conf=0.0, imgsz=None, augment=False):
        return [dict(b) for b in self._boxes if b["conf"] >= conf]


def _guard(person_boxes, ppe_boxes, person_ensemble: bool) -> guard_mod.GuardAgent:
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)   # __init__ 우회 — 클래스 기본값(DETECTOR_CONF 등)은 그대로 유효
    g._models = {"person": _FakeModel(person_boxes), "ppe": _FakeModel(ppe_boxes)}
    g._load_errors = {}
    g._predict_fail_streak = {}
    g._slot_degraded = {}
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.HYSTERESIS = dict(g.HYSTERESIS_FRAMES)
    g._sig_streak = {}
    g.PERSON_ENSEMBLE = person_ensemble
    return g


def _box(label, x1, y1, x2, y2, conf):
    return {"label": label, "bbox": [x1, y1, x2, y2], "conf": conf}


class PersonEnsembleWiring(unittest.TestCase):
    """시나리오: person 슬롯 = P1(왼쪽 사람). ppe 슬롯 = P1과 거의 겹치는 중복 박스(P2, 병합 대상) +
    person 슬롯이 놓친 오른쪽 사람(P3, 앙상블 고유 기여) + Hardhat(P1 근처) + NO-Hardhat(P3 근처만)."""

    def _boxes(self):
        person_boxes = [_box("person", 0.10, 0.10, 0.30, 0.40, 0.90)]
        ppe_boxes = [
            _box("person", 0.12, 0.11, 0.31, 0.41, 0.85),   # P1 과 거의 겹침(교차소스 중복, IoU>=0.45)
            _box("person", 0.60, 0.60, 0.80, 0.90, 0.60),   # person 슬롯이 놓친 사람(앙상블 고유 기여)
            _box("Hardhat", 0.15, 0.05, 0.25, 0.15, 0.90),  # P1 근처 → cross_validate_ppe 통과해야 함
            _box("NO-Hardhat", 0.62, 0.55, 0.72, 0.62, 0.80),  # P3 근처만(person 슬롯엔 대응 박스 없음)
        ]
        return person_boxes, ppe_boxes

    def test_ensemble_on_merges_dup_and_keeps_unique_catch(self):
        person_boxes, ppe_boxes = self._boxes()
        g = _guard(person_boxes, ppe_boxes, person_ensemble=True)
        out = g.detect(_FAKE_IMG, detectors=["person", "ppe"], track_key="t:on")
        persons = [d for d in out["detections"] if d["label"] == "person"]
        self.assertEqual(len(persons), 2, f"교차소스 중복 병합 + 고유 기여 보존 실패: {persons}")
        # 중복 쌍(P1/P2) 중 더 높은 conf(P1, person 슬롯)가 남아야 함
        left = next(p for p in persons if p["bbox"][0] < 0.5)
        self.assertAlmostEqual(left["conf"], 0.90, places=2)
        self.assertEqual(left["detector"], "person")
        labels = {d["label"] for d in out["detections"]}
        self.assertIn("Hardhat", labels)
        self.assertIn("NO-Hardhat", labels, "person 슬롯이 놓친 사람 근처 PPE도 앙상블 켜면 살아야 함")
        self.assertEqual(out["person_count"], 2)

    def test_ensemble_off_drops_ppe_origin_person_but_keeps_its_ppe_items(self):
        person_boxes, ppe_boxes = self._boxes()
        g = _guard(person_boxes, ppe_boxes, person_ensemble=False)
        out = g.detect(_FAKE_IMG, detectors=["person", "ppe"], track_key="t:off")
        persons = [d for d in out["detections"] if d["label"] == "person"]
        self.assertEqual(len(persons), 1, f"앙상블 끔인데 ppe 유래 person 이 남음: {persons}")
        self.assertEqual(persons[0]["detector"], "person")
        self.assertEqual(out["person_count"], 1)
        # cross_validate_ppe 는 앙상블 필터보다 먼저 돌아 이미 전체 person 컨텍스트로 판정했으므로
        # NO-Hardhat(P3 근처)은 person_ensemble=False 여도 그대로 남는다(의도된 동작, docstring 참고).
        labels = {d["label"] for d in out["detections"]}
        self.assertIn("Hardhat", labels)
        self.assertIn("NO-Hardhat", labels)

    def test_tracking_stable_across_frames_both_flag_states(self):
        """같은 track_key 로 5프레임 연속 호출해도 크래시 없이 person tid 가 안정적으로 부여되는지
        (앙상블 on/off 각각) — 병합된/걸러진 박스가 _track 을 깨지 않는지 확인(사용자 지시 확인2)."""
        for flag in (True, False):
            person_boxes, ppe_boxes = self._boxes()
            g = _guard(person_boxes, ppe_boxes, person_ensemble=flag)
            tids_per_frame = []
            for i in range(5):
                out = g.detect(_FAKE_IMG, detectors=["person", "ppe"], track_key=f"cam:stable:{flag}")
                persons = [d for d in out["detections"] if d["label"] == "person"]
                tids_per_frame.append(sorted(d.get("tid") for d in persons if d.get("tid") is not None))
            # 매 프레임 동일 장면이므로 tid 목록이 프레임마다 흔들리지 않아야(안정 추적)
            self.assertTrue(all(t == tids_per_frame[0] for t in tids_per_frame),
                             f"flag={flag}: tid 가 프레임마다 흔들림(추적 불안정): {tids_per_frame}")

    def test_containment_suppress_handles_mixed_detector_boxes(self):
        """포함비 억제(1.9d)가 서로 다른 detector 출처의 person 박스에도 정상 동작하는지(큰 박스 안
        작은 박스, conf 낮은 쪽 제거) — 앙상블 on 상태에서 cross_validate 전에 이미 실행되는 단계."""
        person_boxes = [_box("person", 0.10, 0.10, 0.50, 0.50, 0.90)]   # 큰 박스(person 슬롯)
        ppe_boxes = [_box("person", 0.20, 0.20, 0.30, 0.30, 0.40)]      # 그 안의 작은 박스(ppe 슬롯, conf 낮음)
        g = _guard(person_boxes, ppe_boxes, person_ensemble=True)
        out = g.detect(_FAKE_IMG, detectors=["person", "ppe"], track_key="t:contain")
        persons = [d for d in out["detections"] if d["label"] == "person"]
        self.assertEqual(len(persons), 1, f"포함비 억제가 mixed-detector 박스에서 안 먹음: {persons}")
        self.assertAlmostEqual(persons[0]["conf"], 0.90, places=2)


if __name__ == "__main__":
    unittest.main()
