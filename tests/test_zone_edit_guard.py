"""[W3] 구역 편집 안전 가드 테스트 — 편집 중 대상 전환 차단 + 저장 대상 검증.

배경(2026-08-20 발견): `/safety-hub` 의 `updatePulseSpot()` 이 경보 발생 시 스포트라이트를
자동 전환하는데, 그 경로가 `selectCam()` 을 거치지 않아 **편집 상태(zoneEdit·zonePts)가
그대로 남은 채 대상 카메라만 바뀐다.** 그 상태로 저장하면 **A 카메라를 보고 찍은 좌표가
B 카메라의 위험구역으로 저장된다** — 화면상 경고도 없어 현장에서 원인 추적이 불가능하다.

★이 테스트는 **실제 배포 파일의 함수 소스를 그대로 꺼내** Node 로 실행한다(복사본이 아니다).
가드를 지우거나 조건을 바꾸면 이 테스트가 깨진다.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "themes" / "safety" / "index_hub.html"
PRO = ROOT / "themes" / "safety" / "index_rfdetr.html"
NODE = shutil.which("node")


def grab(src: str, name: str) -> str:
    """HTML 안의 `function <name>(...){...}` 본문을 중괄호 균형으로 잘라낸다."""
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", src)
    if not m:
        raise AssertionError(f"함수를 찾지 못했다: {name}")
    i = src.index("{", m.end() - 1)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
        j += 1
    raise AssertionError(f"함수 본문이 닫히지 않았다: {name}")


def run_node(funcs: str, body: str):
    """추출한 함수 + 검사 스크립트를 Node 로 실행하고 JSON 결과를 돌려준다."""
    d = Path(tempfile.mkdtemp(prefix="w3_"))
    p = d / "t.js"
    p.write_text(funcs + "\n" + body, encoding="utf-8")
    r = subprocess.run([NODE, str(p)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{r.stderr[:600]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipIf(NODE is None, "node 미설치 — JS 동작 테스트 생략")
class TestAutoSwitchBlocked(unittest.TestCase):
    """가드 ① — 편집 중에는 경보 자동전환이 일어나지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.src = HUB.read_text(encoding="utf-8")
        cls.fn = grab(cls.src, "canAutoSwitchSpot")

    def test_switch_allowed_when_idle(self):
        """평상시(편집 아님·핀 없음)에는 자동전환이 동작해야 한다 — 기능을 죽이면 안 된다."""
        r = run_node(self.fn, "console.log(JSON.stringify("
                              "canAutoSwitchSpot({pinned:false,zoneEdit:false})));")
        self.assertTrue(r)

    def test_switch_blocked_while_editing(self):
        """★편집 중에는 차단 — 이 사고의 본체."""
        r = run_node(self.fn, "console.log(JSON.stringify("
                              "canAutoSwitchSpot({pinned:false,zoneEdit:true})));")
        self.assertFalse(r, "편집 중인데 자동전환이 허용됐다")

    def test_switch_blocked_when_pinned(self):
        r = run_node(self.fn, "console.log(JSON.stringify("
                              "canAutoSwitchSpot({pinned:true,zoneEdit:false})));")
        self.assertFalse(r)

    def test_auto_switch_call_site_uses_guard(self):
        """호출부가 실제로 가드를 쓰는지 — 함수만 있고 안 쓰면 의미가 없다."""
        m = re.search(r"canAutoSwitchSpot\(\{[^}]*\}\)\s*&&\s*newlyAlert\.length", self.src)
        self.assertIsNotNone(m, "자동전환 호출부가 canAutoSwitchSpot 을 쓰지 않는다")

    def test_empty_spot_fallback_also_guarded(self):
        """대상이 비었을 때의 자동 선택도 편집 중에는 막아야 한다(같은 사고 경로)."""
        self.assertIn("if(!spotId && !zoneEdit)", self.src,
                      "빈 대상 자동선택이 편집 중에도 동작한다")


@unittest.skipIf(NODE is None, "node 미설치 — JS 동작 테스트 생략")
class TestSaveTargetVerified(unittest.TestCase):
    """가드 ③ — 저장 직전 '편집 시작 카메라 == 저장 대상' 검증."""

    @classmethod
    def setUpClass(cls):
        cls.src = HUB.read_text(encoding="utf-8")
        cls.fn = grab(cls.src, "zoneSaveCheck")

    def _chk(self, st):
        return run_node(self.fn, f"console.log(JSON.stringify(zoneSaveCheck({json.dumps(st)})));")

    def test_ok_when_target_matches(self):
        r = self._chk({"zoneEditCam": "cam1", "spotId": "cam1",
                       "zonePts": [[0, 0], [1, 0], [1, 1]]})
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 3)

    def test_refuses_when_target_changed(self):
        """★대상이 바뀌었으면 저장 거부 — 다른 카메라에 구역이 저장되는 것을 막는다."""
        r = self._chk({"zoneEditCam": "zonelab", "spotId": "test",
                       "zonePts": [[0, 0], [1, 0], [1, 1], [0, 1]]})
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "target_mismatch")
        self.assertEqual(r["from"], "zonelab")
        self.assertEqual(r["to"], "test")

    def test_refuses_when_not_editing(self):
        r = self._chk({"zoneEditCam": None, "spotId": "cam1", "zonePts": []})
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "no_edit")

    def test_refuses_one_or_two_points(self):
        """3점 미만은 판정에 안 쓰이므로(worker `len(zone)>=3`) 조용히 저장되면 안 된다."""
        for n in (1, 2):
            r = self._chk({"zoneEditCam": "c", "spotId": "c", "zonePts": [[0, 0]] * n})
            self.assertFalse(r["ok"], f"{n}점인데 저장이 허용됐다")
            self.assertEqual(r["reason"], "too_few_points")

    def test_allows_zero_points_for_clearing(self):
        """0점 저장은 '구역 삭제' 라는 정당한 조작이다 — 막으면 안 된다."""
        r = self._chk({"zoneEditCam": "c", "spotId": "c", "zonePts": []})
        self.assertTrue(r["ok"])

    def test_save_call_site_uses_check_and_verified_target(self):
        """호출부 계약: 검증을 거치고, 보낼 때 spotId 가 아니라 검증된 대상을 쓴다."""
        self.assertIn("zoneSaveCheck({zoneEditCam:zoneEditCam", self.src)
        self.assertIn("var target=zoneEditCam;", self.src,
                      "저장 대상이 zoneEditCam 으로 고정돼 있지 않다")
        self.assertIn("encodeURIComponent(target)", self.src,
                      "저장 요청이 검증된 대상을 쓰지 않는다")


@unittest.skipIf(NODE is None, "node 미설치 — JS 동작 테스트 생략")
class TestIncidentScenario(unittest.TestCase):
    """★실제 사고 시퀀스 재현 — 이 순서가 현장에서 조용히 잘못된 저장을 만들었다."""

    @classmethod
    def setUpClass(cls):
        src = HUB.read_text(encoding="utf-8")
        cls.fns = grab(src, "canAutoSwitchSpot") + "\n" + grab(src, "zoneSaveCheck")

    def test_alert_during_edit_does_not_hijack_target(self):
        """zonelab 편집 중 test 카메라 경보 → 대상 유지 → 올바른 카메라에 저장."""
        body = """
        var st={pinned:false, zoneEdit:true, spotId:'zonelab',
                zoneEditCam:'zonelab', zonePts:[[0,0],[1,0],[1,1],[0,1]]};
        // poll(): test 카메라가 새로 경보 상태가 됐다
        var newlyAlert=['test'];
        if(canAutoSwitchSpot(st) && newlyAlert.length) st.spotId=newlyAlert[newlyAlert.length-1];
        var chk=zoneSaveCheck(st);
        console.log(JSON.stringify({spotId:st.spotId, save:chk}));
        """
        r = run_node(self.fns, body)
        self.assertEqual(r["spotId"], "zonelab", "★편집 중 대상이 test 로 넘어갔다")
        self.assertTrue(r["save"]["ok"])

    def test_without_guard_the_save_would_be_refused(self):
        """가드 ①이 뚫려 대상이 바뀌더라도, 가드 ③이 저장을 막는다(2중 방어 확인)."""
        body = """
        var st={pinned:false, zoneEdit:true, spotId:'test',   // ①이 뚫린 상태를 가정
                zoneEditCam:'zonelab', zonePts:[[0,0],[1,0],[1,1]]};
        console.log(JSON.stringify(zoneSaveCheck(st)));
        """
        r = run_node(self.fns, body)
        self.assertFalse(r["ok"], "가드 ③ 마저 뚫렸다 — 잘못된 카메라에 저장된다")
        self.assertEqual(r["reason"], "target_mismatch")

    def test_normal_operation_still_auto_switches(self):
        """★편집이 아닐 때는 경보 자동전환이 그대로 동작해야 한다(기능 저하 금지)."""
        body = """
        var st={pinned:false, zoneEdit:false, spotId:'zonelab'};
        var newlyAlert=['test'];
        if(canAutoSwitchSpot(st) && newlyAlert.length) st.spotId=newlyAlert[newlyAlert.length-1];
        console.log(JSON.stringify({spotId:st.spotId}));
        """
        self.assertEqual(run_node(self.fns, body)["spotId"], "test",
                         "평상시 경보 자동전환이 죽었다(기능 저하)")


class TestAutoPinOnEdit(unittest.TestCase):
    """가드 ② — 편집을 시작하면 핀이 자동으로 켜진다(사용자가 잊어도 안전)."""

    @classmethod
    def setUpClass(cls):
        cls.src = HUB.read_text(encoding="utf-8")

    def test_edit_start_sets_target_and_pin(self):
        self.assertIn("zoneEdit=true; zoneEditCam=spotId;", self.src,
                      "편집 시작 시 대상 카메라를 기억하지 않는다")
        self.assertIn("if(!pinned){ pinned=true; zoneAutoPinned=true;", self.src,
                      "편집 시작 시 자동 핀이 없다")

    def test_only_auto_pin_is_released(self):
        """★사용자가 직접 켠 핀은 편집이 끝나도 유지돼야 한다."""
        self.assertIn("if(zoneAutoPinned){", self.src)
        self.assertNotIn("zonePinPrev", self.src, "옛 핀 복원 로직이 남아 있다")

    def test_manual_switch_warns_before_discarding(self):
        """수동 전환은 점을 버리므로(사고는 아님) 말없이 버리지 않고 확인을 받는다."""
        self.assertIn("if(zoneEdit && zonePts.length && id!==spotId){", self.src)
        self.assertIn("찍어둔 점이 사라집니다", self.src)

    def test_edit_end_is_centralized(self):
        """편집 종료가 한 곳(endZoneEdit)으로 모여 있어야 상태가 새지 않는다."""
        self.assertIn("function endZoneEdit(){", self.src)
        for caller in ("zCancel", "zSave", "selectCam"):
            self.assertIn("endZoneEdit()", self.src, f"{caller} 가 endZoneEdit 을 안 쓴다")


class TestSafetyProZoneSaveDisabled(unittest.TestCase):
    """[W3-B] `/safety-pro` 의 구역 저장 비활성 — 웹캠 좌표가 전역 구역으로 새는 경로 차단."""

    @classmethod
    def setUpClass(cls):
        cls.src = PRO.read_text(encoding="utf-8")

    def test_no_zone_save_buttons(self):
        for el in ("zoneDraw", "zoneSave", "zoneClear"):
            self.assertNotIn(f'id="{el}"', self.src, f"{el} 버튼이 아직 있다")

    def test_no_zone_write_request(self):
        """★구역 **쓰기** 요청이 이 화면에 남아 있으면 안 된다.

        (검출용 `POST /rfdetr/frame`·`/rfdetr/vlm` 은 정상이므로 구역 경로만 본다.)
        """
        writes = re.findall(r"fetch\(\s*['\"]/zone/[^'\"]*['\"]\s*,\s*\{[^}]*method", self.src)
        self.assertEqual(writes, [], f"구역 쓰기 요청이 남아 있다: {writes}")

    def test_no_canvas_click_zone_handler(self):
        """캔버스 클릭으로 점을 찍는 경로도 제거됐어야 한다."""
        self.assertNotIn("draftZone.push", self.src, "구역 점 찍기 핸들러가 남아 있다")

    def test_still_reads_and_shows_zone(self):
        """표시 기능은 유지 — 저장만 막는 것이 목적이다."""
        self.assertIn("/zone/danger", self.src, "구역 조회까지 사라졌다")
        self.assertIn("drawPoly(dangerZone", self.src, "구역 표시가 사라졌다")

    def test_points_to_correct_screen(self):
        self.assertIn("/safety-hub", self.src, "올바른 화면 안내가 없다")


if __name__ == "__main__":
    unittest.main()
