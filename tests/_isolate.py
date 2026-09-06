"""tests/_isolate.py — 테스트가 **운영 데이터를 건드리지 못하게** 하는 공용 격리 헬퍼(4단계 ④, 2026-09-06).

배경(실측): 2026-08-28 19:27 에 테스트 스위트가 운영 `data/alert_queue.db` 에 "[TZ] 위험구역…"·
"[TESTCAM] 화재/연기 감지" 행을 남겼다(CODE_REVIEW.md §4-0 #81·#82). 경로는
`test_endpoints_smoke` 가 앱 startup 으로 `alert_notify` 전송기를 **실제 dispatcher** 에 배선한 뒤,
다른 모듈의 `_process_frame`/`submit()` 호출이 그 배선을 타 큐에 기록한 것. notify.yaml 이 설정된
PC 라면 **시험 문구가 실제 텔레그램으로 나간다.**

사용: 큐·전송 경로에 닿을 수 있는 테스트의 setUp/setUpClass 에서
    from _isolate import isolate_alerts
    self.addCleanup(isolate_alerts())          # 또는 cls.addClassCleanup(isolate_alerts())
효과: ① alert_queue DB 를 임시 파일로 교체 ② 배경 스레드(재시도·전송) 정지 ③ 전송기 미주입 상태로
초기화 → 큐 기록은 임시 DB, 원격 전송은 불가. cleanup 이 원래 경로·상태를 복구한다.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))


def isolate_alerts():
    """운영 alert_queue.db·전송기를 임시 상태로 바꾸고, 원복 함수를 돌려준다(addCleanup 용)."""
    import alert_notify
    import alert_queue

    tmp = tempfile.TemporaryDirectory(prefix="vigent_test_alerts_")
    saved_db = alert_queue._DB_PATH
    saved_sender = alert_queue._sender
    alert_queue.stop()
    alert_notify.stop()
    alert_queue._reset_for_test(Path(tmp.name) / "alert_queue.db")
    alert_notify.reset_for_test()          # 큐·sender·게이트 초기화(스레드 없음)

    def _restore() -> None:
        alert_queue.stop()
        alert_notify.stop()
        alert_notify.reset_for_test()
        alert_queue._reset_for_test(saved_db)
        alert_queue._sender = saved_sender
        tmp.cleanup()

    return _restore


def isolate_data_dirs():
    """data_engine(증거·인식 로그·pin)·scribe(위험성평가서) 저장 경로를 임시 디렉터리로 바꾼다.

    실측(2026-09-06 전체 스위트 전후 data/ 해시 비교): test_data_engine_report 가
    data/evidence/·data/risk_assessments/ 에 파일을 만들고, test_privacy_failure_policy 가
    data/recognition/events_<날짜>.jsonl 에 줄을 덧붙였다. 상대경로 계약(`data/evidence/...`)을
    지키기 위해 임시 루트 아래에 같은 `data/` 구조를 만든다."""
    import data_engine
    from agents import scribe as _scribe

    tmp = tempfile.TemporaryDirectory(prefix="vigent_test_data_")
    root = Path(tmp.name)
    saved_de = (data_engine._ROOT, data_engine._EVIDENCE, data_engine._RECOG, data_engine._PINNED)
    saved_legacy = data_engine._PINNED_LEGACY
    saved_sc = (_scribe._ROOT, _scribe._SAVE_DIR, _scribe._EVIDENCE_DIR)
    data_engine._ROOT = root
    data_engine._EVIDENCE = root / "data" / "evidence"
    data_engine._RECOG = root / "data" / "recognition"
    data_engine._PINNED = root / "data" / "retention" / "pinned.json"     # [M6-1] evidence 폴더 밖
    data_engine._PINNED_LEGACY = data_engine._EVIDENCE / "pinned.json"
    _scribe._ROOT = root
    _scribe._SAVE_DIR = root / "data" / "risk_assessments"
    _scribe._EVIDENCE_DIR = (root / "data" / "evidence").resolve()

    def _restore() -> None:
        (data_engine._ROOT, data_engine._EVIDENCE, data_engine._RECOG, data_engine._PINNED) = saved_de
        data_engine._PINNED_LEGACY = saved_legacy
        (_scribe._ROOT, _scribe._SAVE_DIR, _scribe._EVIDENCE_DIR) = saved_sc
        tmp.cleanup()

    return _restore
