"""USB 재빌드(2026-09-28) — 학원 프로파일 포터블에 fk510_smoke 지게차가 실린다.

★무엇을 고정하는가
  ① academy 오버라이드가 vision forklift 가중치를 forklift_rfdetr_fk510_smoke.pth 로, tuning include_forklift 1 · conf.forklift 0.50 으로 바꾼다.
     from: 은 전역 원본에 정확히 1곳(기존 test_audit_fix3_profile 도 검사) — 여기서는 치환 결과를 실제로 만들어 yaml 로 읽어 확인한다.
  ② 그 가중치는 weights_manifest.json 에 SHA 와 함께 있고(required=false), 개발기에 파일이 있으면 SHA 가 manifest 와 같다.
  ③ build_portable.ps1 이 프로파일 to: 의 가중치를 manifest SHA 로 복사하고, academy 산출물을 사후 검증한다(파서 오류 0).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
FK = "forklift_rfdetr_fk510_smoke.pth"


def _apply(overrides: dict, src_text: str, fkey: str) -> str:
    t = src_text
    for k, v in overrides.items():
        if (v.get("file") or "tuning") != fkey:
            continue
        assert t.count(v["from"]) == 1, k
        t = t.replace(v["from"], v["to"], 1)
    return t


class AcademyOverrides(unittest.TestCase):
    def setUp(self):
        base = yaml.safe_load((_ROOT / "deploy/portable/portable_overrides.yaml").read_text(encoding="utf-8")) or {}
        acad = yaml.safe_load((_ROOT / "deploy/academy/portable_overrides.academy.yaml").read_text(encoding="utf-8")) or {}
        self.ov = {**base, **acad}
        self.ov = {k: v for k, v in self.ov.items() if not v.get("skip_when_gpu")}     # GPU 빌드 기준

    def test_forklift_wiring_in_outputs(self):
        vision = yaml.safe_load(_apply(self.ov, (_ROOT / "themes/safety/vision.yaml").read_text(encoding="utf-8"), "vision"))
        tuning = yaml.safe_load(_apply(self.ov, (_ROOT / "config/tuning.yaml").read_text(encoding="utf-8"), "tuning"))

        def find(d, k):
            if isinstance(d, dict):
                if k in d:
                    return d[k]
                for x in d.values():
                    r = find(x, k)
                    if r is not None:
                        return r
            return None
        self.assertTrue(str(find(vision, "rfdetr_weights")["forklift"]).endswith(FK))
        self.assertEqual(int(tuning["detect"]["include_forklift"]), 1)
        self.assertAlmostEqual(float(tuning["detect"]["conf"]["forklift"]), 0.50)
        acad_t = yaml.safe_load((_ROOT / "deploy/academy/tuning.academy.yaml").read_text(encoding="utf-8"))
        self.assertAlmostEqual(float(acad_t["detect"]["conf"]["forklift"]), float(tuning["detect"]["conf"]["forklift"]), msg="학원 프로파일 yaml 과 같은 운용점")

    def test_manifest_and_local_sha(self):
        man = json.loads((_ROOT / "weights_manifest.json").read_text(encoding="utf-8"))
        e = next(w for w in man["weights"] if w["file"] == FK)
        self.assertEqual(len(e["sha256"]), 64)
        f = _ROOT / "vigent-core" / "weights" / FK
        if not f.exists():
            self.skipTest("개발기 가중치 없음")
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), e["sha256"]); self.assertEqual(f.stat().st_size, e["size_bytes"])


class BuildScript(unittest.TestCase):
    def test_build_portable_copies_profile_weights_and_checks_academy(self):
        s = (_ROOT / "scripts/build_portable.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Copy-Verified $wf $me.sha256", s); self.assertIn("weights_manifest.json 에 없다", s)
        self.assertIn("forklift_rfdetr_fk510_smoke.pth'), w", s); self.assertIn("include_forklift',0))==1", s)
        self.assertRegex(s, re.compile(r"Select-String -Path \$ovp -Pattern '\^\\s\*to:"), "to: 줄만 본다(why: 의 다른 가중치 언급을 복사하지 않게)")

    def test_ps1_parses(self):
        ps = shutil.which("powershell")
        if not ps:
            self.skipTest("powershell 없음")
        f = _ROOT / "scripts/build_portable.ps1"
        cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('" + str(f).replace("'", "''")
               + "',[ref]$t,[ref]$e);Write-Output $e.Count")
        r = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "0", r.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
