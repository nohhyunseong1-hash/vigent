"""[CODE_REVIEW M8-2·R2] 시연 화면이 서버에 없는 경로를 부르지 않는다 — "미구현" 으로 비활성(서버 라우트 신설 없음).

실측(2026-09-06): realtime_core.js 가 부르던 8경로(/llm/vision·/llm/status·/vision/capabilities·/vision/analyze-current·
/sensor/temperature·/alert/overspeed·/vitals/rppg·/dataset/small-object/crop)는 서버에 라우트가 0건이었고, /zone/state 는 스텁이었다.
LLM 분석은 항상 404, 열화상 과열·과속 경보는 .catch(()=>{}) 로 조용히 실패(화면엔 경보, 통보 없음), "E-stop 보조정지 신호" 는 스텁 호출.
계약: 이 경로들은 UNIMPLEMENTED_SERVER_PATHS 목록에만 있고 fetch(...) 호출에는 없다. 페이지 라벨에 '통보 미구현' 배지.
"""
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

_JS = _ROOT / "vigent-core" / "static" / "realtime_core.js"
_PATHS = ["/llm/vision", "/llm/status", "/vision/capabilities", "/vision/analyze-current",
          "/sensor/temperature", "/alert/overspeed", "/vitals/rppg", "/dataset/small-object/crop", "/zone/state"]


class FrontendUnimplemented(unittest.TestCase):
    def test_dead_paths_are_listed_and_never_fetched(self):
        js = _JS.read_text(encoding="utf-8")
        m = re.search(r"const UNIMPLEMENTED_SERVER_PATHS=\[(.*?)\];", js, flags=re.S)
        self.assertIsNotNone(m, "미구현 경로 목록 상수가 있어야 한다")
        listed = set(re.findall(r"'([^']+)'", m.group(1)))
        self.assertEqual(listed, set(_PATHS))
        fetch_lines = [ln for ln in js.splitlines() if "fetch(" in ln]
        for p in _PATHS:
            bad = [ln.strip()[:100] for ln in fetch_lines if p in ln]
            self.assertEqual(bad, [], f"서버에 없는 경로를 fetch 한다: {p}")

    def test_server_really_has_no_such_routes(self):
        """서버 쪽 사실 재확인 — 누군가 라우트를 만들면 이 테스트가 알려 주고, 그때 프론트를 다시 배선한다."""
        import main
        routes = {getattr(r, "path", "") for r in main.app.routes}
        for p in _PATHS:
            if p == "/zone/state":
                continue                                    # 스텁 라우트는 존재(응답 idle 고정)
            self.assertNotIn(p, routes, f"{p} 라우트가 생겼다 — 프론트 미구현 표시를 해제할 것")

    def test_pages_show_unimplemented_badges(self):
        for name in ("index.html", "index_local.html"):
            t = (_ROOT / "themes" / "safety" / name).read_text(encoding="utf-8")
            self.assertEqual(t.count("통보 미구현"), 2, f"{name}: 열화상·과속 라벨에 배지 2개")
        js = _JS.read_text(encoding="utf-8")
        self.assertIn("과열 경보 '+maxT.toFixed(1)+'°C (통보 미구현)", js)


if __name__ == "__main__":
    unittest.main()
