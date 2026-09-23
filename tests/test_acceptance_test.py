"""[USB 1차 계획 5] 설치 인수시험(scripts/deploy/acceptance_test.py) — 판정기를 가짜 /health 로 고정한다.

★A4 는 /health.gpu 를 1차 근거로 본다(nvidia-smi 는 보조). A8 은 /health 에 problems 키가 없어
  status=healthy + warnings 비어 있음으로 판정한다 — 그 매핑을 여기서 못 박는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "deploy"))

import acceptance_test as A  # noqa: E402

GOOD = {
    "status": "healthy", "phase": "ready", "warnings": [],
    "rfdetr_slots": [{"slot": "person", "state": "LOADED"}, {"slot": "ppe", "state": "LOADED"}],
    "gpu": {"device_name": "RTX 5060", "arch": "sm_120", "vram_total_mb": 8192, "torch_cuda": True,
            "expected_gpu": True, "fallback": False, "fallback_reason": None},
    "cameras": {"cam1": {"status": "ok", "last_frame_age_s": 0.4}, "cam2": {"status": "ok", "last_frame_age_s": 1.2}},
    "notify": {"selftest_state": "ok", "config_error": None},
}
REG = [{"id": "cam1", "enabled": True}, {"id": "cam2", "enabled": True}, {"id": "old", "enabled": False}]


class Evaluators(unittest.TestCase):
    def test_a2(self):
        self.assertTrue(A.eval_a2(200, GOOD)[0])
        self.assertFalse(A.eval_a2(503, dict(GOOD, phase="starting"))[0])

    def test_a3(self):
        self.assertTrue(A.eval_a3(GOOD)[0])
        h = dict(GOOD, rfdetr_slots=[{"slot": "ppe", "state": "FAILED"}])
        ok, note = A.eval_a3(h); self.assertFalse(ok); self.assertIn("ppe=FAILED", note)
        self.assertFalse(A.eval_a3(dict(GOOD, rfdetr_slots=[]))[0])

    def test_a4_uses_health_gpu_block(self):
        self.assertTrue(A.eval_a4(GOOD, ["python.exe"])[0])
        fb = dict(GOOD, gpu=dict(GOOD["gpu"], fallback=True, fallback_reason="cuda 없음"))
        ok, note = A.eval_a4(fb, ["python.exe"]); self.assertFalse(ok); self.assertIn("cuda 없음", note)
        nocuda = dict(GOOD, gpu=dict(GOOD["gpu"], torch_cuda=False))
        self.assertFalse(A.eval_a4(nocuda, None)[0], "nvidia-smi 가 뭐라 하든 torch_cuda=false 면 실패")

    def test_a5(self):
        self.assertTrue(A.eval_a5(GOOD, REG)[0])
        stale = dict(GOOD, cameras=dict(GOOD["cameras"], cam2={"status": "ok", "last_frame_age_s": 42.0}))
        ok, note = A.eval_a5(stale, REG); self.assertFalse(ok); self.assertIn("cam2", note)
        missing = dict(GOOD, cameras={"cam1": GOOD["cameras"]["cam1"]})
        ok, note = A.eval_a5(missing, REG); self.assertFalse(ok); self.assertIn("cam2", note)
        self.assertFalse(A.eval_a5(GOOD, [])[0], "등록 카메라 0대는 통과가 아니다")

    def test_a6_a8(self):
        self.assertTrue(A.eval_a6(GOOD)[0])
        self.assertFalse(A.eval_a6(dict(GOOD, notify={"selftest_state": "config_error", "config_error": "telegram HTTP 401"}))[0])
        self.assertTrue(A.eval_a8(GOOD)[0])
        self.assertFalse(A.eval_a8(dict(GOOD, warnings=["startup:go2rtc: x"]))[0])
        self.assertFalse(A.eval_a8(dict(GOOD, status="degraded"))[0])

    def test_a7(self):
        self.assertTrue(A.eval_a7({"results": [{"channel": "telegram", "sent": True, "status": 200}]})[0])
        self.assertFalse(A.eval_a7({"results": [{"channel": "telegram", "sent": False, "reason": "미설정"}]})[0])
        self.assertFalse(A.eval_a7({"results": []})[0])


class ReportMerge(unittest.TestCase):
    def test_merge_marks_incomplete_on_fail_and_notes_skipped_human(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "install_report_x.json"
            p.write_text(json.dumps({"installed_at": "t", "mode": "fresh"}), encoding="utf-8")
            rep = A.merge_report(p, {"A2": {"result": "pass", "note": ""}, "A5": {"result": "fail", "note": "cam2"}},
                                 {"H1": "skipped", "H2": "skipped"})
            self.assertTrue(rep["result"].startswith("미완료"))
            self.assertIn("A5", rep["result"])
            self.assertEqual(rep["mode"], "fresh", "기존 보고서 내용은 보존돼야 한다")
            rep2 = A.merge_report(p, {"A2": {"result": "pass", "note": ""}}, {"H1": "skipped", "H2": "skipped"})
            self.assertIn("사람 확인 건너뜀", rep2["result"])
            rep3 = A.merge_report(p, {"A2": {"result": "pass", "note": ""}}, {"H1": "pass", "H2": "pass"})
            self.assertEqual(rep3["result"], "완료")


class ReportWithBom(unittest.TestCase):
    def test_merge_tolerates_utf8_bom(self):
        """install.ps1(PowerShell 5.1)이 쓴 보고서는 BOM 이 붙을 수 있다 — 2026-09-23 실설치에서 json.loads 가 죽었다."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "install_report_bom.json"
            p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"mode": "fresh"}).encode("utf-8"))
            rep = A.merge_report(p, {"A2": {"result": "pass", "note": ""}}, {"H1": "pass", "H2": "pass"})
            self.assertEqual(rep["mode"], "fresh")
            self.assertEqual(rep["result"], "완료")
            json.loads(p.read_text(encoding="utf-8"))          # 다시 쓴 파일은 BOM 없이 읽혀야 한다


class RunNonInteractive(unittest.TestCase):
    def test_run_with_patched_io(self):
        with tempfile.TemporaryDirectory() as d:
            app = Path(d); (app / "data").mkdir()
            (app / "data" / "install_report_20260101_0000.json").write_text("{}", encoding="utf-8")
            log: list[str] = []
            with mock.patch.object(A, "APP", app), \
                    mock.patch.object(A, "_get_health", return_value=(200, GOOD)), \
                    mock.patch.object(A, "_registered", return_value=REG), \
                    mock.patch.object(A, "_smi_names", return_value=["python.exe"]), \
                    mock.patch.object(A, "_token", return_value="x" * 64):
                fake_resp = mock.Mock(status_code=200)
                fake_resp.json.return_value = {"results": [{"channel": "telegram", "sent": True, "status": 200}]}
                with mock.patch("requests.post", return_value=fake_resp):
                    rc = A.run("http://127.0.0.1:8010", no_service=True, only_human=False, non_interactive=True, out=log.append)
            self.assertEqual(rc, 0)
            rep = json.loads((app / "data" / "install_report_20260101_0000.json").read_text(encoding="utf-8"))
            self.assertEqual(rep["auto_tests"]["A1"]["result"], "skipped")
            self.assertEqual({k: v["result"] for k, v in rep["auto_tests"].items() if k != "A1"},
                             {k: "pass" for k in ("A2", "A3", "A4", "A5", "A6", "A7", "A8")})
            self.assertEqual(rep["human_tests"], {"H1": "skipped", "H2": "skipped"})
            self.assertFalse(any("x" * 64 in ln for ln in log), "토큰이 출력되면 안 된다")


if __name__ == "__main__":
    unittest.main()
