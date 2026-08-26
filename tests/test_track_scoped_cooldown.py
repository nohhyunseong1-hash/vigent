"""[D1-C] 사람 단위 판정 — 두 번째 사람을 놓치지 않되, 알림 폭주는 만들지 않는다.

★배경(2026-08-24 재생 검증): 예전 구역 판정은 `raw_inside` 라는 **카메라 단위 집계
불리언**이었고 디바운서 키도 카메라였다. 그래서 **A가 구역 안에 있는 동안 B가 들어오면
아예 발화하지 않았다** — 15초 쿨다운의 문제가 아니라 A가 나갈 때까지 **무기한** 가려졌다.

★채택안은 C(완화안)다:
  · 구역 디바운스·쿨다운 → **트랙 단위**  (두 번째 사람을 기록·증거로 반드시 남긴다)
  · 통보 게이트(alert_gate) → **카메라 단위 그대로**  (적응형 백오프 유지 = 폭주 0)
  게이트 키까지 트랙으로 바꾸면(B안) 백오프가 무력화돼 재생 검증에서 알림이 66배였다
  (benchmarks/d1d3_track_key_findings.md).

여기서 고정하는 계약 3가지(사용자 지시):
  1) C 적용 후 **알림 수 = 현행과 동일**
  2) **두 번째 사람 진입이 이벤트로 기록**된다
  3) **증거 쿨다운(30초)이 디스크 폭주를 막는다**
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_gate  # noqa: E402
import worker as W  # noqa: E402
import zone_debounce  # noqa: E402

# ★화면 일부만 구역으로 잡는다 — 전체로 잡으면 '구역 밖'을 만들 수 없어 퇴장 시험이 불가능하다.
ZONE = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8)]


def _det(tid: int, inside: bool = True):
    """person 검출 1건. 판정 기준점은 박스 하단 중앙(발끝)이다."""
    b = [0.4, 0.4, 0.6, 0.7] if inside else [0.90, 0.90, 0.99, 0.95]
    return {"label": "person", "conf": 0.9, "bbox": b, "tid": tid}


def _out(*dets):
    return {"detections": list(dets), "signals": {}, "person_count": len(dets)}


class SecondPersonIsNotMasked(unittest.TestCase):
    """계약 2 — 두 번째 사람의 진입이 남는다.

    ★디바운서는 **첫 관측에서 절대 발화하지 않는다**(기동 순간 구역 안에 사람이 있으면
      유예 없이 울리는 것을 막는 설계). 트랙별 키도 각자 그 유예를 거치므로,
      테스트는 프레임을 2회 이상 넣어 '유예를 통과한 뒤'를 본다.
    """

    def setUp(self):
        self.db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)

    def _pump(self, *dets, n: int = 2):
        """같은 장면을 n 프레임 넣고 **발화 목록을 합쳐** 돌려준다."""
        got = []
        for _ in range(n):
            got += W._derive(_out(*dets), ZONE, None, cid="c1", debouncer=self.db)
        return got

    def test_second_person_fires_while_first_stays_inside(self):
        """★핵심 회귀 — A가 안에 있는 동안 B가 들어오면 발화해야 한다.

        수정 전에는 집계 불리언이 계속 True 라 전이가 없어 **영영 발화하지 않았다.**
        """
        f1 = self._pump(_det(1))
        self.assertEqual([s for r, _lv, _n, s in f1 if r == "zone_intrusion"], ["t1"],
                         "A 진입이 발화 안 됨")
        f2 = self._pump(_det(1), _det(2))              # A 체류 + B 진입
        subj = [s for r, _lv, _n, s in f2 if r == "zone_intrusion"]
        self.assertEqual(subj, ["t2"],
                         f"★A가 안에 있는 동안 B 진입이 남지 않았다(무기한 가려짐 재발): {subj}")

    def test_same_person_staying_does_not_refire(self):
        """★같은 사람의 체류는 재발화하지 않는다 — 이게 무너지면 매 프레임 폭주다."""
        self._pump(_det(1))                             # 최초 진입(발화)
        later = self._pump(_det(1), n=6)                # 계속 체류
        self.assertEqual([r for r, *_ in later], [], "체류 중인데 재발화했다")

    def test_leaving_and_returning_refires(self):
        """나갔다 다시 들어오면 새 진입이다(같은 사람이라도)."""
        self._pump(_det(1))
        self._pump(_det(1, inside=False), n=2)          # 퇴장 확정
        again = self._pump(_det(1), n=2)                # 재진입
        self.assertIn("zone_intrusion", [r for r, *_ in again], "재진입이 발화 안 됨")

    def test_no_track_id_falls_back_to_camera_scope(self):
        """tid 가 없으면(추적 실패) 기존 카메라 단위 동작 — 하위호환."""
        d = {"label": "person", "conf": 0.9, "bbox": [0.4, 0.4, 0.6, 0.7]}   # tid 없음
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        got = []
        for _ in range(2):
            got += W._derive(_out(d), ZONE, None, cid="c9", debouncer=db)
        self.assertIn("zone_intrusion", [r for r, *_ in got], "폴백 경로가 발화하지 않는다")


class CooldownIsPerPerson(unittest.TestCase):
    """계약 2 — 쿨다운이 다른 사람을 가리지 않는다(worker 소비부 계약)."""

    def test_cooldown_key_includes_subject(self):
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "worker.py").read_text(encoding="utf-8")
        self.assertIn('ck = f"{rule}|{subject}" if subject else rule', src,
                      "쿨다운 키에 발화 주체가 안 들어갔다 — A의 쿨다운이 B를 가린다")
        self.assertIn("ctx.cooldown[ck] = now", src)

    def test_evidence_cooldown_stays_rule_scoped(self):
        """★계약 3 — 증거 JPEG 쿨다운은 **규칙 단위 그대로**여야 한다.

        사람마다 30초 증거를 뜨면 디스크가 인원수만큼 빨리 찬다. 디스크 풀은 [F2] 경로로
        기록·통보를 함께 죽이므로, 여기서 트랙 단위로 바꾸면 미검출을 고치려다 더 큰
        구멍을 연다. 이벤트(JSONL)는 사람 단위로 남아 '누가 언제'는 보존된다.
        """
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "worker.py").read_text(encoding="utf-8")
        self.assertIn("ctx.evidence_cd.get(rule, 0)", src,
                      "★증거 쿨다운이 규칙 단위가 아니다 — 디스크 폭주 위험")
        self.assertNotIn("ctx.evidence_cd.get(ck", src)


class NotificationCountUnchanged(unittest.TestCase):
    """계약 1 — ★알림 수가 현행과 같다(폭주 위험 0)."""

    def test_gate_key_is_camera_not_track(self):
        """통보 게이트 키에 트랙이 들어가면 백오프가 무력화된다(B안 = 66배)."""
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "worker.py").read_text(encoding="utf-8")
        self.assertIn("cam=str(ctx.name)", src,
                      "★통보 게이트 키가 카메라가 아니다 — 적응형 백오프가 무력화된다")

    def test_many_tracks_still_yield_one_notification(self):
        """★재생 검증 고정 — 사람이 10명 들어와도 **기록은 10건, 알림은 게이트가 묶는다**.

        C안의 핵심이 이것이다: 미검출은 기록으로 막고, 폭주는 통보 게이트로 막는다.
        """
        alert_gate.reset()
        db = zone_debounce.ZoneDebouncer(enter=0.0, exit_=0.0)
        dets = [_det(i) for i in range(1, 11)]
        fires = notifs = 0
        for i in range(3):                       # 유예 통과를 위해 같은 장면을 여러 프레임
            for _r, lv, _n, _s in W._derive(_out(*dets), ZONE, None, cid="cam", debouncer=db):
                if _r != "zone_intrusion":      # 10명이면 crowd_density 도 뜬다 — 여기선 침입만 센다
                    continue
                fires += 1
                # worker 는 **카메라 이름**으로 통보한다(트랙 아님) — 그대로 흉내낸다
                if alert_gate.decide("cam", "zone_intrusion", lv, now=float(i))["notify"]:
                    notifs += 1
        self.assertEqual(fires, 10, f"10명이 들어왔는데 기록이 {fires}건(사람 단위 기록 실패)")
        self.assertEqual(notifs, 1, f"★알림이 {notifs}건 — 폭주다(게이트 키를 확인하라)")


if __name__ == "__main__":
    unittest.main()
