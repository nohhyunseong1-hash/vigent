"""검수 뷰어 ID 연쇄(V-2) — 3프레임 모의 시퀀스로 확인한다.

★무엇을 고정하는가: 보간 박스에서 track_id 를 확정하면, **우측 원본 프레임(t+500ms)의
  대응 박스에도 같은 ID 가 기록**돼야 한다. 그래야 다음 프레임의 후보 목록이 방금 확정한
  ID 를 보여 주고 연쇄가 이어진다. 대응 박스는 보간 때 짝지은 그 박스(`src_tid`)다.
★좌표는 **수정하지 않는다** — track_id 필드만 바뀐다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

# ★모듈 **최상위**에서 가져와야 한다 — 아래 _minimal_app 의 `s: Save` 애노테이션은
#   `from __future__ import annotations` 로 문자열이 되고, FastAPI 는 그것을 이 모듈의
#   전역에서 해석한다. 지역 변수(RV.Save)로 두면 못 찾아 **쿼리 파라미터**로 취급해 422 가
#   난다 — 이 파일을 쓰다가 같은 결함을 그대로 재현했다(2026-09-22).
from review_viewer import Save  # noqa: E402


class ReviewChainTest(unittest.TestCase):
    """0ms(원본) → 500ms(보간) → 1000ms(원본) 3프레임."""

    def setUp(self) -> None:
        import review_viewer as RV
        self.RV = RV
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._saved = (RV._FE, RV._DRAFT, RV._SIDE_1FPS, RV._PROGRESS)
        RV._FE = base
        RV._DRAFT = base / "labels_2fps_draft"
        RV._SIDE_1FPS = base / "labels_1fps_tid"
        RV._PROGRESS = base / "review_progress.json"
        RV._DRAFT.mkdir(parents=True)
        RV._SIDE_1FPS.mkdir(parents=True)

        box_a = [0.30, 0.50, 0.10, 0.40]
        box_b = [0.50, 0.50, 0.10, 0.40]
        # 원본 0ms·1000ms — 둘 다 track_id 7(보간 단계가 부여한 값)
        for stem, bx in (("vid_0ms", box_a), ("vid_1000ms", box_b)):
            (RV._SIDE_1FPS / f"{stem}.json").write_text(json.dumps(
                {"file": f"{stem}.jpg", "video": "vid", "boxes": [
                    {"cls": 0, "box": bx, "track_id": 7, "source": "human", "parent_track_id": None}]},
                ensure_ascii=False), encoding="utf-8")
        # 보간 500ms — src_tid 7 을 보존한다
        mid = [(a + b) / 2 for a, b in zip(box_a, box_b)]
        (RV._DRAFT / "vid_500ms.json").write_text(json.dumps(
            {"file": "vid_500ms.jpg", "video": "vid", "video_role": "full", "boxes": [
                {"cls": 0, "box": mid, "track_id": 7, "src_tid": 7,
                 "source": "interp", "parent_track_id": None}]}, ensure_ascii=False), encoding="utf-8")
        self.box_b = box_b

    def tearDown(self) -> None:
        RV = self.RV
        RV._FE, RV._DRAFT, RV._SIDE_1FPS, RV._PROGRESS = self._saved
        self.tmp.cleanup()

    def _chain(self, stem: str, boxes: list[dict], next_file: str) -> int:
        """api_save 의 연쇄 부분만 떼어 실행한다(FastAPI 기동 없이)."""
        RV = self.RV
        nxt = RV._SIDE_1FPS / f"{Path(next_file).stem}.json"
        d = json.loads(nxt.read_text(encoding="utf-8"))
        by_src = {b.get("src_tid"): b.get("track_id") for b in boxes if b.get("src_tid") is not None}
        chained = 0
        for b in d.get("boxes", []):
            new = by_src.get(b.get("track_id"))
            if new is not None and new != b.get("track_id"):
                b["track_id"] = new
                chained += 1
        if chained:
            nxt.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return chained

    def test_id_change_propagates_to_next_frame(self) -> None:
        """보간 박스 ID 를 7 → 42 로 바꾸면 우측 원본도 42 가 된다(좌표 불변)."""
        RV = self.RV
        draft = json.loads((RV._DRAFT / "vid_500ms.json").read_text(encoding="utf-8"))
        boxes = [{**draft["boxes"][0], "track_id": 42}]        # 사람이 42 로 확정
        n = self._chain("vid_500ms", boxes, "vid_1000ms.jpg")
        self.assertEqual(n, 1, "대응 박스 1개가 갱신돼야 한다")
        after = json.loads((RV._SIDE_1FPS / "vid_1000ms.json").read_text(encoding="utf-8"))
        self.assertEqual(after["boxes"][0]["track_id"], 42)
        self.assertEqual(after["boxes"][0]["box"], self.box_b, "★좌표는 바뀌면 안 된다")

    def test_no_change_when_id_kept(self) -> None:
        """ID 를 그대로 승인하면 아무것도 바꾸지 않는다(불필요한 쓰기 금지)."""
        RV = self.RV
        draft = json.loads((RV._DRAFT / "vid_500ms.json").read_text(encoding="utf-8"))
        n = self._chain("vid_500ms", draft["boxes"], "vid_1000ms.jpg")
        self.assertEqual(n, 0)

    def test_next_frame_candidates_reflect_chain(self) -> None:
        """연쇄 뒤 다음 프레임의 후보 목록에 새 ID 가 보인다 — 연쇄의 목적."""
        RV = self.RV
        draft = json.loads((RV._DRAFT / "vid_500ms.json").read_text(encoding="utf-8"))
        self._chain("vid_500ms", [{**draft["boxes"][0], "track_id": 42}], "vid_1000ms.jpg")
        cands = [b.get("track_id") for b in RV.load_src_labels("vid_1000ms")]
        self.assertIn(42, cands)
        self.assertNotIn(7, cands)

    def test_progress_overrides_sidecar(self) -> None:
        """검수 확정분(review_progress)이 사이드카보다 우선한다(V-2 최신 우선)."""
        RV = self.RV
        RV.save_progress({"done": {"vid_0ms": {"boxes": [
            {"cls": 0, "box": [0.3, 0.5, 0.1, 0.4], "track_id": 99}], "verified": True}},
            "started": None, "durations": []})
        self.assertEqual([b["track_id"] for b in RV.load_src_labels("vid_0ms")], [99])


class ReviewSaveRoundTripTest(unittest.TestCase):
    """★저장 왕복 — 오늘(2026-09-22) 잡은 422 결함의 재발 방지.

    `from __future__ import annotations` 로 애노테이션이 문자열이 되는데 FastAPI 는 그것을
    **모듈 전역**에서 해석한다. `Save` 모델이 함수 안에 있으면 못 찾아 본문이 아니라
    **쿼리 파라미터**로 취급해 모든 저장이 422 가 된다. 함수를 직접 부르는 시험은 이걸
    못 잡는다 — **실제 HTTP 경로**로 왕복해야 한다.
    """

    def test_selftest_passes_on_real_app(self) -> None:
        """뷰어가 기동 시 돌리는 자체 점검이 실제 앱에서 통과한다."""
        import review_viewer as RV
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        saved = (RV._FE, RV._DRAFT, RV._SIDE_1FPS, RV._PROGRESS)
        try:
            RV._FE, RV._DRAFT = base, base / "d"
            RV._SIDE_1FPS, RV._PROGRESS = base / "s", base / "p.json"
            RV._DRAFT.mkdir(parents=True)
            RV._SIDE_1FPS.mkdir(parents=True)
            app = _minimal_app(RV)
            RV.selftest(app)                     # 예외가 나면 실패
            self.assertNotIn(RV.SELFTEST_STEM, RV.progress()["done"], "점검 흔적이 남으면 안 된다")
        finally:
            RV._FE, RV._DRAFT, RV._SIDE_1FPS, RV._PROGRESS = saved
            tmp.cleanup()

    def test_selftest_detects_broken_binding(self) -> None:
        """모델 바인딩이 깨진 앱(라우트 없음)에서는 점검이 **반드시 실패**한다."""
        import review_viewer as RV
        from fastapi import FastAPI
        with self.assertRaises(Exception):
            RV.selftest(FastAPI())


def _minimal_app(RV):
    """뷰어의 저장·큐 라우트만 떼어 만든 앱 — main() 을 통째로 띄우지 않는다."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    app = FastAPI()

    @app.post("/api/save")
    def save(s: Save) -> JSONResponse:
        p = RV.progress()
        boxes = []
        for b in s.boxes:
            if b.get("verdict") == "unresolvable":
                b = {**b, "track_id": None, "reason": b.get("reason") or "low_quality"}
            boxes.append(b)
        p["done"][s.stem] = {"boxes": boxes, "verified": s.verified,
                             "n_unresolvable": sum(1 for b in boxes if b.get("verdict") == "unresolvable")}
        RV.save_progress(p)
        return JSONResponse({"ok": True})

    @app.get("/api/queue")
    def queue() -> JSONResponse:
        p = RV.progress()
        return JSONResponse({"queue": [], "done": p["done"],
                             "unresolvable": sum(int(v.get("n_unresolvable", 0)) for v in p["done"].values())})

    return app


if __name__ == "__main__":
    unittest.main()
