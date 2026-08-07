"""track_key TTL 청소(F-2, 2026-08 신설) 회귀:
  1) 계속 쓰이는 키(예: cam:<name>)는 TTL 스윕이 지나도 축출되지 않는다(last_used 갱신 확인).
  2) 유휴 키(예: voice:<session_id>, 세션 종료 후 방치)는 KEY_TTL_SEC 지나면 정리된다.
  3) MAX_TRACKED_KEYS 하드 백스톱: TTL 정리로도 안 줄면 가장 오래된 키부터 축출 + WARNING 로그.
모델 로드 없이 Guard._track 만 검증(__new__ + 클래스 기본 속성, test_track_key_isolation.py 와 동일 패턴).
time.time() 을 결정적으로 흉내내 실제로 몇 분씩 기다리지 않는다."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402


def _box(x1, y1, x2, y2, label="person"):
    return {"label": label, "bbox": [x1, y1, x2, y2], "conf": 0.9, "detector": "person"}


class FakeClock:
    def __init__(self, t0: float):
        self.t = t0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _guard(ttl: float, sweep_interval: float, max_keys: int):
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)   # __init__ 우회(모델·설정 로드 없이 _track 만)
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.TRACK_ALGO = "iou"
    g.KEY_TTL_SEC = ttl
    g.SWEEP_INTERVAL_SEC = sweep_interval
    g.MAX_TRACKED_KEYS = max_keys
    return g


class TrackKeyTTLSweep(unittest.TestCase):
    def test_actively_used_key_survives_while_idle_key_is_purged(self):
        """cam:live 는 계속 쓰이고 voice:abandoned 는 1회 후 방치 — TTL(100s) 지나면 후자만 정리."""
        g = _guard(ttl=100.0, sweep_interval=10.0, max_keys=10_000)
        clock = FakeClock(1_000_000.0)
        box = _box(0.1, 0.1, 0.2, 0.2)
        with mock.patch.object(guard_mod.time, "time", clock):
            g._track([box], "cam:live")
            g._track([box], "voice:abandoned")   # 1회만 쓰고 이후 다시 안 옴(세션 종료 시뮬레이션)
            for _ in range(5):
                clock.advance(30.0)               # 5×30s=150s 경과(TTL 100s·스윕간격 10s 둘 다 넘음)
                g._track([box], "cam:live")        # 계속 쓰이는 키만 매번 갱신
        self.assertIn("cam:live", g._tracks_by_key, "계속 쓰인 키가 스윕에 사라짐(회귀 — F-2④ 위반)")
        self.assertIn("cam:live", g._key_last_used)
        self.assertNotIn("voice:abandoned", g._tracks_by_key, "TTL(100s) 지난 유휴 키가 안 지워짐")
        self.assertNotIn("voice:abandoned", g._key_last_used)

    def test_backstop_evicts_oldest_and_logs_warning_when_ttl_alone_is_not_enough(self):
        """MAX_TRACKED_KEYS=3, TTL=아주 김(스윕이 TTL로는 하나도 못 지움) → 5개 키 투입 시
        가장 오래 안 쓰인 것부터 강제축출 + WARNING 로그, 계속 쓰이는 키는 생존.
        스윕은 '이번 호출의 키를 추가하기 전' 상태를 보고 판단하므로(사용자 지시③: 매 프레임 전수스캔
        방지 위해 가벼운 조건만 먼저 봄) 초과분이 조금 뒤에 잡힐 수 있다 — 그래서 마지막에 안정화 호출을
        1번 더 넣어 최종 수렴 상태를 확인한다(실사용에서도 다음 몇 프레임 안에 자연히 수렴)."""
        g = _guard(ttl=10_000.0, sweep_interval=1.0, max_keys=3)
        clock = FakeClock(2_000_000.0)
        box = _box(0.1, 0.1, 0.2, 0.2)
        with self.assertLogs("vigent.guard", level="WARNING") as cm:
            with mock.patch.object(guard_mod.time, "time", clock):
                for key in ["k0", "k1", "k2", "k3", "cam:live"]:
                    clock.advance(5.0)
                    g._track([box], key)
                clock.advance(5.0)
                g._track([box], "cam:live")   # 안정화 호출(위 docstring 참고) — 계속 쓰이는 키 재사용
        self.assertTrue(any("백스톱" in line for line in cm.output),
                         f"백스톱 WARNING 로그가 안 남음: {cm.output}")
        self.assertLessEqual(len(g._tracks_by_key), 3, "안정화 후에도 MAX_TRACKED_KEYS 초과 상태")
        self.assertIn("cam:live", g._tracks_by_key, "계속 쓰이는 키가 백스톱에 축출됨(회귀 — F-2④ 위반)")
        self.assertNotIn("k0", g._tracks_by_key, "가장 오래된 키가 축출 대상에서 빠짐")


if __name__ == "__main__":
    unittest.main()
