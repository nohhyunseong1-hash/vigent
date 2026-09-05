"""[CODE_REVIEW M1-1] guard._guard_logger() 가 호출마다 sys.path 를 늘리던 결함 회귀 테스트.

배경: 예전 구현은 호출할 때마다 `sys.path.insert(0, <vigent-core>)` 를 반복했다. 추론 실패
경로(guard.detect 의 except 절)는 **실패 프레임마다** 로거를 부르므로, 슬롯이 죽은 채 운영되면
경로 항목이 무한히 쌓였다(실측: 100회 호출 → 7→107). 수정 후 조건:
  ① 반복 호출해도 sys.path 길이 불변(1회·멱등 삽입)  ② 같은 로거 객체 캐시
  ③ 정상 환경에서는 vlog 로거가 잡힌다  ④ vlog 를 못 올리면 표준 logging 으로 WARNING 1줄(조용한 폴백 금지)
"""
import builtins
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import agents.guard as guard_mod  # noqa: E402

_CORE = str(guard_mod._PROJECT_ROOT / "vigent-core")


class GuardLoggerSysPath(unittest.TestCase):
    # ※ 전체 스위트에서는 테스트 모듈마다 `sys.path.insert(0, <vigent-core>)` 를 하므로(60개 파일)
    #   절대 개수는 검사하지 않는다 — guard 가 **더 늘리지 않는지**(증분 0)만 본다.
    def test_repeated_calls_do_not_grow_syspath(self):
        guard_mod._guard_logger()                 # 1회째(필요하면 여기서 1번만 삽입)
        n0, c0 = len(sys.path), sys.path.count(_CORE)
        for _ in range(100):
            guard_mod._guard_logger()
        self.assertEqual(len(sys.path), n0, "호출 100회에 sys.path 길이가 변했다 — 반복 삽입 재발")
        self.assertEqual(sys.path.count(_CORE), c0, "guard 가 vigent-core 경로를 추가로 삽입했다")

    def test_ensure_core_on_path_is_idempotent(self):
        guard_mod._ensure_core_on_path()
        c0 = sys.path.count(_CORE)
        self.assertGreaterEqual(c0, 1, "경로 보장이 안 됐다")
        for _ in range(5):
            guard_mod._ensure_core_on_path()
        self.assertEqual(sys.path.count(_CORE), c0)

    def test_logger_cached_and_backend_is_vlog(self):
        a = guard_mod._guard_logger()
        b = guard_mod._guard_logger()
        self.assertIs(a, b, "로거가 캐시되지 않았다")
        self.assertEqual(guard_mod._LOG_BACKEND, "vlog",
                         f"정상 환경인데 vlog 가 아니라 {guard_mod._LOG_BACKEND!r} 로 잡혔다")

    def test_fallback_to_logging_emits_warning(self):
        saved = (guard_mod._LOG, guard_mod._LOG_BACKEND)
        real_import = builtins.__import__

        def _no_vlog(name, *a, **k):
            if name == "vlog":
                raise ImportError("vlog 차단(테스트)")
            return real_import(name, *a, **k)

        try:
            guard_mod._LOG, guard_mod._LOG_BACKEND = None, ""
            with mock.patch.object(builtins, "__import__", side_effect=_no_vlog), \
                    self.assertLogs("vigent.guard", level="WARNING") as cm:
                lg = guard_mod._guard_logger()
            self.assertEqual(guard_mod._LOG_BACKEND, "logging")
            self.assertEqual(lg.name, "vigent.guard")
            self.assertTrue(any("표준 logging 폴백" in line for line in cm.output),
                            f"폴백 WARNING 이 없다: {cm.output}")
        finally:
            guard_mod._LOG, guard_mod._LOG_BACKEND = saved


if __name__ == "__main__":
    unittest.main()
