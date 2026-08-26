"""[2026-08-26] 학원 프로파일이 기본 설정으로부터 **드리프트**하지 않는지.

배경(실제 사고): `deploy/academy/tuning.academy.yaml` 은 `config/tuning.yaml` 을
**파일 통째로 덮는** 방식이다. 그래서 기본값에 키가 추가되면 학원 프로파일은 조용히
뒤처지고, 적용하는 순간 그 키들이 **사라진다**.

2026-08-26 단축 소크 준비 중 실제로 6개 키가 빠져 있었다:

    retention.auto_sweep = True            <- F6 자동 파기가 꺼진다("자동 파기"가 다시 거짓)
    retention.sweep_initial_delay_s = 600
    retention.sweep_interval_s = 86400
    zone.global_fallback = False           <- F5 수정 무효화(전역 구역 폴백 부활)
    proximity.enter_s = 0.4                <- W2 근접 디바운스 소실
    proximity.exit_s = 1.0

즉 학원 프로파일을 적용하는 것만으로 **안전 리뷰에서 고친 F5·F6 이 무효화**됐다.
그대로 소크를 돌렸다면 스윕이 아예 안 돌아 시험 자체가 성립하지 않았을 것이다.

이 테스트는 그 재발을 막는다. **의도된 차이만 화이트리스트**로 두고, 그 외에 키가
빠지거나 값이 달라지면 실패한다.

★근본 해법은 오버레이 방식(학원 파일에 다른 키만 두고 기본값 위에 병합)이며 별도 과제다.
  이 테스트는 그때까지의 방어선이자, 전환 후에도 회귀 잠금으로 남는다.
"""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "config" / "tuning.yaml"
ACADEMY = ROOT / "deploy" / "academy" / "tuning.academy.yaml"
NL = chr(10)

# ★학원 프로파일이 **의도적으로** 기본값과 다르게 두는 키만 여기 적는다.
#   근거: deploy/academy/README_academy.md — forklift 슬롯 켬(boda_ax) · fire_smoke 끔.
INTENTIONAL_DIFFS = {
    "detect.include_forklift": 1,      # 학원 전용 키(기본에는 없음)
    "detect.include_fire_smoke": 0,    # 학원 전용 키(기본에는 없음)
    "detect.conf.forklift": 0.5,       # 기본 0.002 → 운용점 0.50(G1 대결 채택)
}


def _flat(d, pre=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{pre}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def _load(p):
    return _flat(yaml.safe_load(p.read_text(encoding="utf-8")))


class TestAcademyProfileNoDrift(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.base = _load(BASE)
        cls.acad = _load(ACADEMY)

    def test_no_base_key_is_missing(self):
        """★기본값의 키가 학원 프로파일에서 빠지면 안 된다 — 빠지면 그 설정이 사라진다."""
        missing = sorted(set(self.base) - set(self.acad))
        detail = NL.join(f"  {k} = {self.base[k]!r}" for k in missing)
        self.assertEqual(missing, [],
                         "학원 프로파일에 기본 설정 키가 빠졌다 — 적용 시 이 값들이 사라진다:"
                         + NL + detail + NL
                         + "deploy/academy/tuning.academy.yaml 에 위 키를 추가하라.")

    def test_only_whitelisted_values_differ(self):
        """값이 다른 키는 화이트리스트에 있는 것뿐이어야 한다."""
        diffs = {k: (self.base[k], self.acad[k])
                 for k in set(self.base) & set(self.acad) if self.base[k] != self.acad[k]}
        unexpected = {k: v for k, v in diffs.items() if k not in INTENTIONAL_DIFFS}
        detail = NL.join(f"  {k}: 기본={a!r} → 학원={b!r}" for k, (a, b) in unexpected.items())
        self.assertEqual(unexpected, {},
                         "의도하지 않은 값 차이 — 학원 프로파일이 기본값에서 벗어났다:"
                         + NL + detail + NL
                         + "의도된 것이면 INTENTIONAL_DIFFS 에 근거와 함께 추가하라.")

    def test_whitelisted_diffs_still_hold(self):
        """화이트리스트가 낡지 않았는지 — 적힌 값이 실제 학원 프로파일과 같아야 한다."""
        for key, want in INTENTIONAL_DIFFS.items():
            with self.subTest(key=key):
                self.assertIn(key, self.acad, f"{key} 가 학원 프로파일에 없다")
                self.assertEqual(self.acad[key], want,
                                 f"{key}: 화이트리스트 {want!r} != 실제 {self.acad[key]!r} — "
                                 "값을 바꿨다면 화이트리스트도 갱신하라")

    def test_academy_extra_keys_are_declared(self):
        """학원에만 있는 키도 화이트리스트에 선언돼 있어야 한다(무단 추가 방지)."""
        extra = sorted(set(self.acad) - set(self.base))
        undeclared = [k for k in extra if k not in INTENTIONAL_DIFFS]
        self.assertEqual(undeclared, [],
                         f"학원 프로파일에만 있는 미선언 키: {undeclared}")

    def test_safety_review_keys_survive(self):
        """★F5·F6·W2 가 학원 프로파일에서도 살아 있는지 — 사고가 났던 바로 그 키들."""
        for key, want in (("retention.auto_sweep", True),
                          ("zone.global_fallback", False)):
            with self.subTest(key=key):
                self.assertIn(key, self.acad, f"{key} 누락 — 안전 리뷰 수정이 무효화된다")
                self.assertEqual(self.acad[key], want)
        for key in ("retention.sweep_interval_s", "retention.sweep_initial_delay_s",
                    "proximity.enter_s", "proximity.exit_s"):
            with self.subTest(key=key):
                self.assertIn(key, self.acad, f"{key} 누락")


if __name__ == "__main__":
    unittest.main()
