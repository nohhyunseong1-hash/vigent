"""isolated_detect.detect_isolated 회귀(2026-08 신설): 서로 다른 두 "이미지"를 연속 호출해도
앞 이미지의 박스가 뒤 결과에 이어붙지 않음(track_key 재사용 버그 재발 방지 — 근거: benchmarks/
extract_eval_frames.py가 track_key="eval_extract" 를 109장 전체에 재사용해 트랙이 새던 버그,
2026-08 실측 확인: conf가 직전 호출과 소수점까지 일치). 모델 로드 없이 Guard._track만 검증
(test_track_key_isolation.py와 동일 패턴 — __new__ + 클래스 기본 속성)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402
from isolated_detect import detect_isolated  # noqa: E402


def _box(x1, y1, x2, y2, label="person", conf=0.9):
    return {"label": label, "bbox": [x1, y1, x2, y2], "conf": conf, "detector": "person"}


def _guard_with_fake_detect(box_by_call):
    """실제 모델 로드 없이 _track()(진짜 추적 로직)만 실행하는 stub guard.
    box_by_call: 호출될 때마다 순서대로 반환할 박스 리스트(빈 리스트=이번 이미지엔 검출 없음)."""
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)   # __init__ 우회(모델·설정 로드 없이)
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}   # F-2: TTL 청소 상태
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.TRACK_ALGO = "iou"
    calls = {"n": 0}

    def _fake_detect(img, detectors=None, conf=None, imgsz=None, augment=False, *, track_key):
        fresh = box_by_call[calls["n"]]
        calls["n"] += 1
        tracked = g._track(list(fresh), track_key)
        return {"detections": tracked}

    g.detect = _fake_detect
    return g


class IsolatedDetect(unittest.TestCase):
    def test_stale_box_does_not_leak_into_unrelated_next_image(self):
        """1번째 '이미지'에 person 있음 → 2번째 '이미지'는 완전히 무관(검출 0건) → detect_isolated
        를 쓰면 2번째 결과에 1번째의 박스가 안 이어붙는다(버그 재현: 격리 없이 같은 key를 쓰면 이어붙음)."""
        img1_box = _box(0.10, 0.10, 0.30, 0.30, conf=0.55)
        g = _guard_with_fake_detect([[img1_box], []])   # 2번째 이미지는 진짜로 아무것도 없음

        out1 = detect_isolated(g, object(), detectors=["person"])
        out2 = detect_isolated(g, object(), detectors=["person"])

        self.assertEqual(len(out1["detections"]), 1, "1번째 이미지는 person 1개가 나와야 함")
        self.assertEqual(len(out2["detections"]), 0,
                          "무관한 2번째 이미지에 1번째의 박스가 이어붙음(격리 실패 — 버그 재발)")

    def test_each_call_gets_a_fresh_unique_track_key(self):
        """호출마다 고유 track_key 발급 확인 — 재사용 실수 자체가 구조적으로 불가능한지."""
        g = _guard_with_fake_detect([[], [], []])
        seen_keys: list[str] = []

        def _capture_reset(track_key):
            seen_keys.append(track_key)
            g._tracks_by_key[track_key] = []

        g.reset_tracks = _capture_reset
        for _ in range(3):
            detect_isolated(g, object(), detectors=["person"])
        # 매 호출 reset_tracks가 (사용 전 1회 + 사용 후 1회) 같은 새 키로 2번씩, 총 3회 호출×2 = 6개,
        # unique key 개수는 3개(호출당 1개, 전/후 동일 키 재사용은 같은 호출 내에서만 허용).
        unique = set(seen_keys)
        self.assertEqual(len(seen_keys), 6)
        self.assertEqual(len(unique), 3, "호출마다 서로 다른 고유 track_key가 발급돼야 함")


if __name__ == "__main__":
    unittest.main()
