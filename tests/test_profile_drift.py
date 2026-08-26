"""현장 프로파일 드리프트 게이트 — 기본값에 키가 추가돼도 프로파일이 뒤처지지 않게.

★배경(2026-08-24 실제 사고): 학원 프로파일은 `copy` 로 **파일 전체를 덮는다**.
그래서 전역 기본값에 키가 추가되면 프로파일은 **조용히 뒤처진다**. 실제로 6개 키가
누락된 상태였고, 그 프로파일을 적용하는 순간 [F5](전역 구역 폴백 차단)와
[F6](자동 파기 스레드)이 학원에서 **무효화**됐다. 경고도 로그도 없었다.

★이 테스트가 게이트에 있는 이유: 드리프트는 "다음에 기본값을 바꾼 사람"이 만든다.
그 사람은 프로파일의 존재조차 모를 수 있다. 사람의 기억이 아니라 게이트가 잡아야 한다.

여기서 고정하는 계약:
  1) 기본값의 **모든 키**가 프로파일에 있다(누락 = 실패).
  2) 값이 다르면 `profile_intent.yaml` 에 **이유와 함께 선언**돼 있다(미선언 = 실패).
  3) 프로파일에만 있는 키도 선언돼 있다.
  4) ★학원은 backend.forklift=yolo 라 **detectors 의 forklift 항목이 반드시 살아 있어야**
     한다 — 없으면 guard `_get_model` 이 None 을 돌려주고 지게차 검출이 통째로 죽는다([F31]).
"""
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import check_profile_drift as cpd  # noqa: E402


def _load(rel: str) -> dict:
    return yaml.safe_load((_ROOT / rel).read_text(encoding="utf-8")) or {}


class ProfileDrift(unittest.TestCase):
    """계약 1·2·3 — 선언되지 않은 차이는 전부 실패."""

    def test_no_drift(self):
        """★게이트 본체 — 드리프트가 있으면 여기서 막힌다."""
        intent = _load("deploy/academy/profile_intent.yaml")
        self.assertTrue(intent, "profile_intent.yaml 이 비어 있다")
        problems: list[str] = []
        for name, spec in intent.items():
            problems += cpd.check_one(name, spec)
        self.assertEqual(problems, [], "★프로파일 드리프트:\n  " + "\n  ".join(problems))

    def test_script_exits_zero(self):
        """스크립트 자체도 통과해야 한다(사람이 손으로 돌리는 경로)."""
        r = subprocess.run([sys.executable, str(_ROOT / "scripts" / "check_profile_drift.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, f"드리프트 검사 실패:\n{r.stdout}\n{r.stderr}")

    def test_every_declared_difference_has_a_reason(self):
        """★'왜 바꿨는지' 없는 선언은 선언이 아니다 — 나중에 아무도 못 되돌린다."""
        intent = _load("deploy/academy/profile_intent.yaml")
        for name, spec in intent.items():
            for group in ("overrides", "profile_only"):
                for key, decl in (spec.get(group) or {}).items():
                    self.assertTrue((decl or {}).get("why", "").strip(),
                                    f"[{name}] {group}.{key} 에 why(이유)가 없다")


class AcademySlotSafety(unittest.TestCase):
    """계약 4 — 학원 프로파일에서 지게차가 죽지 않게."""

    def test_forklift_entry_survives_because_backend_is_yolo(self):
        """★학원은 forklift 가 yolo 다 — detectors 항목이 없으면 검출이 조용히 죽는다.

        guard `_get_model`: `if backend == "yolo" and not path: return None`.
        rfdetr 슬롯은 경로를 안 보지만 yolo 슬롯은 **반드시 본다**. 이 비대칭 때문에
        "죽은 설정이니 지워도 된다"가 forklift 에는 성립하지 않는다.
        """
        v = _load("deploy/academy/vision.academy.yaml")["perception"]
        for slot, be in v["backend"].items():
            if be != "yolo":
                continue
            ids = [d["id"] for d in v["detectors"]]
            self.assertIn(slot, ids,
                          f"★backend.{slot}=yolo 인데 detectors 에 항목이 없다 — 검출이 죽는다")
            entry = next(d for d in v["detectors"] if d["id"] == slot)
            self.assertTrue(entry.get("model"), f"{slot} 항목에 model 경로가 없다")

    def test_academy_keeps_safety_fixes_on(self):
        """★학원 프로파일이 안전 수정을 꺼두지 않았는가 — 값 자체를 직접 본다.

        드리프트 검사는 '키가 있는가'를 보지만, 여기서는 **켜져 있는가**를 본다.
        키는 있는데 값이 뒤집혀 있으면 게이트를 통과하면서 현장에서만 무력화된다.
        """
        t = _load("deploy/academy/tuning.academy.yaml")
        self.assertFalse(t["zone"]["global_fallback"],
                         "★학원에서 전역 구역 폴백이 켜졌다 — F5 무효화(남의 구역으로 침입 판정)")
        self.assertTrue(t["retention"]["auto_sweep"],
                        "★학원에서 자동 파기가 꺼졌다 — F6 무효화('자동 파기'가 거짓이 된다)")
        self.assertGreater(t["proximity"]["enter_s"], 0,
                           "근접 디바운스가 꺼졌다(W2 롤백 상태)")


if __name__ == "__main__":
    unittest.main()
