"""[R4] 소크 리포트 RSS 판정 테스트.

배경: 2026-08-17 소크에서 스크립트가 **−163.9MB/h 를 FAIL** 로 판정했다. 메모리 감소는
누수의 반대인데 abs(기울기)로 비교한 탓이다. 또 외부 요인(GPU 부하로 인한 Windows 워킹셋
트리밍)으로 RSS 가 계단식으로 급락하면 전체 단일 회귀 자체가 무의미해진다
(실측: 구간별 +1.2 ~ −4.9MB/h 인데 전체로는 −163.9MB/h).

검증:
  1. 증가가 상한을 넘으면 FAIL
  2. ★감소는 PASS (누수가 아니다)
  3. ★계단 낙차가 있으면 구간 분리 후 **최악(가장 큰 양의 기울기)** 구간으로 판정
  4. 2시간 미만은 판정 보류
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "soak_report.py"


def _write(rows, path, hours=24.0):
    header = {
        "_type": "header", "started_at": "2026-08-17T02:37:01",
        "ends_at": "2026-08-18T02:37:01", "hours": hours, "interval_s": 60,
        "pass_criteria": {"degraded_minutes_max": 5, "rss_growth_mb_per_hour_max": 30},
    }
    with path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _row(t, rss, status="healthy"):
    return {"t": t, "ts": "2026-08-17T02:37:01", "code": 200, "status": status,
            "phase": "ready",
            "cams": {"test": {"s": "ok", "f": 0.4, "d": 0.3, "rc": 0, "hg": 0, "gen": 1}},
            "alerts": {"pending": 0}, "rss_mb": rss, "gpu_mb": 2500}


def _run(path):
    r = subprocess.run([sys.executable, str(_SCRIPT), str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


class TestRssJudgment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "soak.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_growth_over_limit_fails(self):
        """증가가 상한(30MB/h)을 넘으면 FAIL."""
        rows = [_row(i * 60, 1000 + i * 60 / 3600 * 50) for i in range(200)]   # +50MB/h
        _write(rows, self.p)
        code, out = _run(self.p)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_decrease_passes(self):
        """★감소는 PASS — 메모리가 줄어드는 것은 누수의 반대다."""
        rows = [_row(i * 60, 3000 - i * 60 / 3600 * 40) for i in range(200)]   # -40MB/h
        _write(rows, self.p)
        code, out = _run(self.p)
        self.assertEqual(code, 0, f"감소인데 FAIL 이 났다\n{out}")
        self.assertIn("종합: PASS", out)

    def test_step_drop_is_segmented_and_worst_segment_judged(self):
        """★계단 낙차가 있으면 구간을 나누고 **최악(가장 큰 양의 기울기)** 구간으로 판정한다.

        전체 회귀로는 큰 음수가 나와 통과해버리지만, 낙차 이후 구간에 누수가 있으면 잡아야 한다."""
        rows = [_row(i * 60, 3000 + i * 60 / 3600 * 1.0) for i in range(120)]  # 2h, +1MB/h
        base_t = 120 * 60
        # 계단 낙차(-2000MB) 후 구간은 +60MB/h 로 누수
        rows += [_row(base_t + i * 60, 1000 + i * 60 / 3600 * 60) for i in range(120)]
        _write(rows, self.p)
        code, out = _run(self.p)
        self.assertIn("계단", out, "계단 낙차를 감지하지 못했다")
        self.assertEqual(code, 1, f"낙차 이후 구간의 누수를 놓쳤다\n{out}")

    def test_short_run_defers(self):
        """2시간 미만은 판정 보류(짧은 구간 외삽은 무의미)."""
        rows = [_row(i * 60, 1000 + i * 5) for i in range(30)]                 # 0.5h
        _write(rows, self.p, hours=0.5)
        code, out = _run(self.p)
        self.assertIn("판정보류", out)
        self.assertEqual(code, 0)

    def test_real_soak_data_passes(self):
        """★실제 2026-08-17 소크 기록으로 PASS 가 나와야 한다(수동 재계산과 일치)."""
        real = _ROOT / "audit" / "soak_realcam_2026-08-17_0237.jsonl"
        if not real.exists():
            self.skipTest("소크 원본 없음")
        code, out = _run(real)
        self.assertEqual(code, 0, f"실측 데이터가 FAIL 로 나온다\n{out}")
        self.assertIn("계단 2회 분리", out)


if __name__ == "__main__":
    unittest.main()
