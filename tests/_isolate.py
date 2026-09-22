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

import atexit
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))


def isolate_logs():
    """vlog 의 로그 디렉터리(logs/vigent.log · logs/events.jsonl)를 임시 디렉터리로 바꾼다. [5단계 마무리, 2026-09-06]

    실측: test_machine_guard·test_bypass_paths_gated 가 /dispatch/relay 를 호출하며 vlog.log_event 로 운영
    logs/events.jsonl 에 dispatch_relay 행 3개를 남겼다(21:27~21:28). 이벤트 로거는 첫 호출 때 파일 핸들러를 만들어
    캐시하므로 캐시를 비우고, 루트 로거에 붙은 logs/ 아래 파일 핸들러도 임시 경로로 옮긴다. cleanup 이 전부 원복한다."""
    import logging

    import vlog

    tmp = tempfile.TemporaryDirectory(prefix="vigent_test_logs_", ignore_cleanup_errors=True)
    root_dir = Path(tmp.name)
    saved_dir = vlog._LOG_DIR
    saved_events = vlog._event_logger
    swapped: dict[int, logging.Handler] = {}   # id(임시 핸들러) → 원래 핸들러

    def _under(h: logging.Handler, d: Path) -> bool:
        base = getattr(h, "baseFilename", "")
        try:
            return bool(base) and Path(base).resolve().is_relative_to(d.resolve())
        except OSError:
            return False

    def _close(lg: logging.Logger | None) -> None:
        if lg is None:
            return
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass

    _close(saved_events)                     # 캐시된 events.jsonl 핸들러 분리(원복 때 다시 만든다)
    vlog._event_logger = None
    vlog._LOG_DIR = root_dir
    root = logging.getLogger()
    for h in list(root.handlers):            # 루트의 logs/vigent.log 파일 핸들러 → 임시 파일
        if _under(h, saved_dir):
            new = logging.FileHandler(root_dir / Path(getattr(h, "baseFilename")).name, encoding="utf-8")
            new.setFormatter(h.formatter)
            new.setLevel(h.level)
            root.removeHandler(h)
            root.addHandler(new)
            swapped[id(new)] = h

    def _restore() -> None:
        _close(vlog._event_logger)
        vlog._event_logger = None            # 다음 log_event 가 원래 경로에 새 핸들러를 만든다
        vlog._LOG_DIR = saved_dir
        for h in list(root.handlers):        # 임시 경로를 가리키는 핸들러는 전부 닫는다(격리 중 vlog.setup() 이 만든 것 포함)
            if not _under(h, root_dir):
                continue
            root.removeHandler(h)
            try:
                h.close()
            except Exception:  # noqa: BLE001
                pass
            old = swapped.pop(id(h), None)
            if old is not None:
                root.addHandler(old)
            else:                            # 격리 중 setup() 이 만든 핸들러 → 같은 이름으로 원래 디렉터리에 다시
                try:
                    saved_dir.mkdir(parents=True, exist_ok=True)
                    re = logging.FileHandler(saved_dir / Path(getattr(h, "baseFilename")).name, encoding="utf-8")
                    re.setFormatter(h.formatter)
                    re.setLevel(h.level)
                    root.addHandler(re)
                except Exception:  # noqa: BLE001
                    pass
        tmp.cleanup()

    return _restore


# ── 프로세스 전체 logs/ 격리 ─────────────────────────────────────────────────────────────────────
#   실측(2026-09-06 전체 스위트 전후 data/+logs/ 해시 비교): 개별 격리만으로는 루트 로거의 logs/vigent.log 가 테스트 로그로
#   10MB 회전(vigent.log·.1·.2 변경 3건)했다. unittest discover 는 모든 test 모듈을 먼저 import 한 뒤 실행하므로, 이 모듈이
#   import 되는 순간(어느 test 모듈이든 _isolate 를 쓰면) 루트 파일 핸들러·이벤트 로거를 임시 경로로 돌려 두면 실행 단계의
#   모든 테스트 로그가 운영 logs/ 를 건드리지 않는다. 프로세스 종료 때 원복(atexit). VIGENT_TEST_KEEP_LOGS=1 이면 끄기.
# ── ★[F-35, 2026-09-22] 테스트는 **망을 타지 않는다** ────────────────────────────────────────
#   실측 사고: 알림 채널 자가시험(getMe)을 기동 경로에 넣자 **전체 테스트가 실제 텔레그램에
#   접속했다**(test_startup_services 2건 실패로 드러남). 망이 없거나 느린 환경에서는 테스트가
#   불안정해지고, 토큰이 설정된 PC 에서는 **외부로 요청이 나간다.**
#   이 모듈이 import 되는 순간(어느 test 모듈이든) 자가시험을 꺼 둔다.
#   실제로 망을 태워 보려면 VIGENT_TEST_ALLOW_NET=1.
if os.environ.get("VIGENT_TEST_ALLOW_NET", "") != "1":
    os.environ.setdefault("VIGENT_NOTIFY_SELFTEST", "0")

_PROCESS_LOG_RESTORE = None
if os.environ.get("VIGENT_TEST_KEEP_LOGS", "") != "1":
    try:
        _PROCESS_LOG_RESTORE = isolate_logs()
        atexit.register(_PROCESS_LOG_RESTORE)
    except Exception:  # noqa: BLE001  격리 실패가 테스트 자체를 막지는 않는다(해시 비교가 잡는다)
        _PROCESS_LOG_RESTORE = None


def isolate_alerts():
    """운영 alert_queue.db·전송기를 임시 상태로 바꾸고, 원복 함수를 돌려준다(addCleanup 용).
    [5단계 마무리] logs/ 격리(isolate_logs)를 포함한다 — 경보·릴레이 경로는 vlog.log_event 로 events.jsonl 에도 쓴다."""
    import alert_notify
    import alert_queue
    import data_engine

    restore_logs = isolate_logs()
    tmp = tempfile.TemporaryDirectory(prefix="vigent_test_alerts_")
    saved_db = alert_queue._DB_PATH
    saved_sender = alert_queue._sender
    # [M6-10 후속, 2026-09-06 실측] mark_sent(critical/high) 가 자동 pin 을 쓰므로 pin 목록도 격리한다 — 격리 전에는
    #   임시 DB 의 행 id 로 만든 "alert:1" pin 이 운영 data/retention/pinned.json 에 남았다.
    saved_pins = (data_engine._PINNED, data_engine._PINNED_LEGACY)
    data_engine._PINNED = Path(tmp.name) / "retention" / "pinned.json"
    data_engine._PINNED_LEGACY = Path(tmp.name) / "evidence" / "pinned.json"
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
        data_engine._PINNED, data_engine._PINNED_LEGACY = saved_pins
        tmp.cleanup()
        restore_logs()

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
