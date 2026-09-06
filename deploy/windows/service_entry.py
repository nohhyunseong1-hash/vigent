r"""service_entry.py — Windows 서비스(NSSM)용 얇은 런처. [5단계 5-2 정정, 2026-09-06]

왜 필요한가(실사고 2026-09-06 재설치 검증): 서비스 env 가 VIGENT_REQUIRE_TOKEN=1 인데 검증 절차가 .env(토큰 출처)를 중화하자
main.py 의 보안 게이트가 **import 시점**에 SystemExit(1) 로 죽었다. 이 단계는 `_startup()` 이전이라 [M4-5] 의 이벤트 로그(ID 1000)·
data/startup_failure.json 이 남지 않는다 — NSSM 이 60초마다 재시작(Paused)만 반복하고 아무 흔적이 없다(3주 크래시 루프와 같은 사각).

이 런처는 `import main` 을 try 로 감싸 **import·인터프리터 단계 실패**를 잡아
  ① data/startup_failure.json 에 stage="import" 로 누적 기록(count·last_error·last_stderr)
  ② Windows 이벤트 로그 Application/VIGENT **ID 1001**(1000 = _startup 단계 실패와 구분)
  ③ 종료코드 반환(SystemExit 코드 그대로, 그 외 예외 2) — NSSM 이 재시작 정책을 적용한다.
성공하면 uvicorn 으로 main.app 을 띄운다(예전 `-m uvicorn main:app` 과 동일 동작). 런처 자체가 못 뜨는 경우(파이썬 부재·구문 오류)는
NSSM AppStderr(logs/vigent.err.log)만 남으므로 service_status.ps1 이 그 마지막 20줄을 보여 준다.

사용: <venv>\python.exe deploy\windows\service_entry.py --host 0.0.0.0 --port 8010
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "vigent-core"
STATE_PATH = ROOT / "data" / "startup_failure.json"
EVENT_ID_IMPORT_FAIL = 1001


def write_windows_event(msg: str, event_id: int = EVENT_ID_IMPORT_FAIL) -> bool:
    """Application/VIGENT 이벤트 1줄(eventcreate → Write-EventLog 폴백). 비Windows·실패 False. main 을 import 못 한 상황이라 독립 구현."""
    if os.name != "nt":
        return False
    text = msg[:900]
    try:
        r = subprocess.run(["eventcreate", "/T", "ERROR", "/ID", str(event_id), "/L", "APPLICATION", "/SO", "VIGENT",
                            "/D", text], capture_output=True, timeout=10)
        if r.returncode == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        safe = text.replace("'", "''")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            f"Write-EventLog -LogName Application -Source VIGENT -EntryType Error -EventId {event_id} "
                            f"-Message '{safe}'"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def record_failure(stage: str, error: str, stderr_tail: str = "", *, state_path: Path = STATE_PATH,
                   event_writer: Callable[[str], bool] = write_windows_event) -> dict[str, Any]:
    """startup_failure.json 갱신(누적 count) + 이벤트 로그. 어떤 예외도 밖으로 내지 않는다(기록 실패가 종료를 막지 않게)."""
    st: dict[str, Any] = {"count": 0, "last_notify_ts": 0.0}
    try:
        st.update(json.loads(state_path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    st["count"] = int(st.get("count", 0)) + 1
    st["last_failure_ts"] = time.time()
    st["stage"] = stage
    st["last_error"] = error[:300]
    if stderr_tail:
        st["last_stderr"] = stderr_tail[-800:]
    msg = (f"[VIGENT] 서비스 런처: {stage} 단계 기동 실패 {st['count']}회 — {st['last_error']} · "
           f"logs/vigent.err.log 확인(인터프리터·패키지·.env/토큰)")
    try:
        st["event_log_ok"] = bool(event_writer(msg))
    except Exception:  # noqa: BLE001
        st["event_log_ok"] = False
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return st


def _default_importer() -> Any:
    sys.path.insert(0, str(CORE))
    os.chdir(CORE)
    import main  # noqa: PLC0415  (지연 import — 실패를 여기서 잡는다)
    return main


def _default_serve(app: Any, host: str, port: int) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port)


class _Tee(io.TextIOBase):
    """stderr 를 그대로 흘리면서 마지막 내용을 잡아 둔다(보안 게이트 안내문 등을 startup_failure.json 에 남기기 위해)."""

    def __init__(self, orig: Any) -> None:
        self.orig = orig
        self.buf = io.StringIO()

    def write(self, s: str) -> int:  # type: ignore[override]
        try:
            self.orig.write(s)
        except Exception:  # noqa: BLE001
            pass
        self.buf.write(s)
        return len(s)

    def flush(self) -> None:
        try:
            self.orig.flush()
        except Exception:  # noqa: BLE001
            pass


def main_entry(argv: list[str] | None = None, *, importer: Callable[[], Any] = _default_importer,
               serve: Callable[[Any, str, int], None] = _default_serve,
               state_path: Path = STATE_PATH, event_writer: Callable[[str], bool] = write_windows_event) -> int:
    ap = argparse.ArgumentParser(description="VIGENT 서비스 런처")
    ap.add_argument("--host", default=os.environ.get("VIGENT_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("VIGENT_PORT", "8010")))
    a = ap.parse_args(argv)
    tee = _Tee(sys.stderr)
    orig_stderr = sys.stderr
    sys.stderr = tee  # type: ignore[assignment]
    try:
        try:
            mod = importer()
        except SystemExit as ex:                      # main.py 보안 게이트 등 — 코드 그대로 반환
            code = ex.code if isinstance(ex.code, int) else 1
            record_failure("import", f"SystemExit({code})", tee.buf.getvalue(), state_path=state_path, event_writer=event_writer)
            return code
        except BaseException as ex:  # noqa: BLE001  ImportError·구문 오류·네이티브 로드 실패 전부
            record_failure("import", f"{type(ex).__name__}: {ex}", tee.buf.getvalue() + traceback.format_exc()[-600:],
                           state_path=state_path, event_writer=event_writer)
            return 2
    finally:
        sys.stderr = orig_stderr
    app = getattr(mod, "app", None)
    if app is None:
        record_failure("import", "main.app 없음", state_path=state_path, event_writer=event_writer)
        return 2
    serve(app, a.host, a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main_entry())
