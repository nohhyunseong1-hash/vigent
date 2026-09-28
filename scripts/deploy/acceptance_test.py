#!/usr/bin/env python3
r"""acceptance_test.py — 설치 인수시험 2단계. [USB 1차 계획 5, 설계서 §6]

  <Target>\python\python.exe <Target>\app\scripts\deploy\acceptance_test.py [--base http://127.0.0.1:8010] [--no-service] [--only-human] [--non-interactive]

6-1 자동 (하나라도 실패 = **설치 미완료**, 종료코드 1)
  A1 서비스 기동         sc query VIGENT = RUNNING            (--no-service 면 '건너뜀' 으로 기록 — 개발기 임시 설치)
  A2 /health 응답        HTTP 200 · status=healthy · phase=ready
  A3 모델 로드           rfdetr_slots 전부 state=LOADED
  A4 GPU 사용            /health.gpu: torch_cuda=true 이고 fallback=false (1차 근거) · nvidia-smi 에 서버 python 이 보이면 보조 근거
  A5 카메라 프레임 수신   등록된 enabled 카메라 전부 /health.cameras 에 있고 last_frame_age_s ≤ 10s
  A6 알림 채널           notify.selftest_state="ok" · config_error=null
  A7 /alerts/test 전송   telegram sent=true (Bearer 토큰은 <app>\.env 에서 읽고 출력하지 않는다)
  A8 /health 전 항목     status=healthy 이고 warnings 비어 있음 (★/health 에 'problems' 키는 없다 — 이 둘로 판정한다)
6-2 사람 확인 (실패 = **경고**, 설치는 완료)
  H1 검출 1회 이상        "카메라 앞에 3초간 서 주세요" → 10초 대기 → 화면/로그에서 person 박스를 봤는지 사람이 y/N
  H2 경보 수신            A7 메시지가 폰에 왔는지 사람이 y/N
  --non-interactive 면 둘 다 'skipped' 로 기록한다(자동만 통과하고 사람 확인을 건너뛴 기기가 "검증됐다" 로 오인되지 않게).

결과: <app>\data\install_report_<최신>.json 에 auto_tests/human_tests/result 를 **합쳐 넣는다**(기기에 남는다, USB 아님).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP / "vigent-core"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

FRESH_FRAME_S = 10.0


# ── 순수 판정기(테스트 대상) ───────────────────────────────────────────────────
def eval_a2(code: int, h: dict[str, Any]) -> tuple[bool, str]:
    ok = code == 200 and h.get("status") == "healthy" and h.get("phase") == "ready"
    return ok, f"HTTP {code} · status={h.get('status')} · phase={h.get('phase')}"


def eval_a3(h: dict[str, Any]) -> tuple[bool, str]:
    slots = h.get("rfdetr_slots") or []
    bad = [f"{s.get('slot')}={s.get('state')}" for s in slots if s.get("state") != "LOADED"]
    if not slots:
        return False, "rfdetr_slots 비어 있음"
    return (not bad), ("전부 LOADED " + str([s.get("slot") for s in slots]) if not bad else "미로드: " + ", ".join(bad))


def eval_a4(h: dict[str, Any], smi_names: list[str] | None = None) -> tuple[bool, str]:
    g = h.get("gpu") or {}
    ok = bool(g.get("torch_cuda")) and not bool(g.get("fallback"))
    note = f"torch_cuda={g.get('torch_cuda')} fallback={g.get('fallback')} {g.get('device_name')} {g.get('arch')} {g.get('vram_total_mb')}MB"
    if smi_names is not None:
        seen = any("python" in n.lower() for n in smi_names)
        note += " · nvidia-smi: " + ("서버 python 보임" if seen else "서버 python 안 보임(보조 근거만, WDDM 은 [N/A] 가능)")
    if not ok and g.get("fallback_reason"):
        note += f" · 이유: {g.get('fallback_reason')}"
    return ok, note


def eval_a5(h: dict[str, Any], registered: list[dict[str, Any]], fresh_s: float = FRESH_FRAME_S) -> tuple[bool, str]:
    cams = h.get("cameras") or {}
    want = [c["id"] for c in registered if c.get("enabled")]
    if not want:
        return False, "enabled 카메라가 등록돼 있지 않다(마법사 3단계)"
    bad = []
    for cid in want:
        c = cams.get(cid)
        if not c:
            bad.append(f"{cid}: /health 에 없음"); continue
        age = c.get("last_frame_age_s")
        if age is None or float(age) > fresh_s:
            bad.append(f"{cid}: last_frame_age_s={age}")
    return (not bad), ("전부 수신 " + str(want) if not bad else "; ".join(bad))


def eval_a6(h: dict[str, Any]) -> tuple[bool, str]:
    n = h.get("notify") or {}
    ok = n.get("selftest_state") == "ok" and not n.get("config_error")
    return ok, f"selftest_state={n.get('selftest_state')} config_error={n.get('config_error')}"


def eval_a7(resp: dict[str, Any]) -> tuple[bool, str]:
    res = resp.get("results") or []
    tg = next((r for r in res if r.get("channel") == "telegram"), None)
    if tg is None:
        return False, "응답에 telegram 채널 결과 없음"
    return bool(tg.get("sent")), f"telegram sent={tg.get('sent')} status={tg.get('status') or tg.get('reason')}"


def eval_a8(h: dict[str, Any]) -> tuple[bool, str]:
    w = h.get("warnings") or []
    ok = h.get("status") == "healthy" and not w
    return ok, f"status={h.get('status')} warnings={w}"


def merge_report(report_path: Path, auto: dict[str, dict[str, Any]], human: dict[str, str]) -> dict[str, Any]:
    # ★utf-8-sig: install.ps1(PowerShell 5.1) 이 쓴 보고서에 BOM 이 붙어 있을 수 있다 — 2026-09-23 실설치에서
    #   json.loads 가 "Unexpected UTF-8 BOM" 으로 죽어 판정이 보고서에 합쳐지지 않았다. 읽을 때 BOM 을 허용한다.
    rep = json.loads(report_path.read_text(encoding="utf-8-sig")) if report_path.exists() else {}
    rep["auto_tests"] = auto
    rep["human_tests"] = human
    fails = [k for k, v in auto.items() if v.get("result") == "fail"]
    rep["acceptance_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rep["result"] = "완료" if not fails else "미완료(" + ", ".join(fails) + ")"
    if not fails and any(v == "skipped" for v in human.values()):
        rep["result"] = "완료(사람 확인 건너뜀 — 재시험: acceptance_test.py --only-human)"
    report_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


# ── 실행부 ─────────────────────────────────────────────────────────────────────
def _token() -> str:
    env = APP / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            if ln.startswith("VIGENT_API_TOKEN="):
                return ln.split("=", 1)[1].strip()
    return os.environ.get("VIGENT_API_TOKEN", "")


def _get_health(base: str) -> tuple[int, dict[str, Any]]:
    import requests
    r = requests.get(base + "/health", timeout=10)
    try:
        return r.status_code, r.json()
    except Exception:  # noqa: BLE001
        return r.status_code, {}


_SC_STATE = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING", 4: "RUNNING", 5: "CONTINUE_PENDING", 6: "PAUSE_PENDING", 7: "PAUSED"}


def parse_sc_state(out: str) -> str:
    """`sc query` 출력 → 상태 이름. ★[2026-09-28 실기] 한국어 Windows 는 라벨이 '상태' 이고 출력 인코딩(OEM cp949)에 따라 영문 상태어를
    못 찾아 서비스가 RUNNING 인데 '없음/알 수 없음' 으로 오판했다(A1 오판). 라벨·언어에 기대지 않고 **': <숫자>'** 의 SCM 상태 코드
    (1 STOPPED … 4 RUNNING)를 읽는다. 코드가 없으면 영문 상태어 폴백."""
    import re
    # ': 4  RUNNING' — 상태어 자체가 '???' 로 깨져도 코드 한 자리만 본다('종류 : 10 …' 은 두 자리라 안 걸린다)
    m = re.search(r":\s*([1-7])\s+\S+", out) or re.search(r"(?:STATE|상태)\s*:\s*([1-7])\b", out)
    if m:
        return _SC_STATE.get(int(m.group(1)), f"code{m.group(1)}")
    for w in ("RUNNING", "STOPPED"):
        if w in out:
            return w
    return "없음/알 수 없음"


def _service_running(name: str = "VIGENT") -> tuple[bool, str]:
    # 1순위: PowerShell Get-Service — 상태가 enum 이름(Running/Stopped)이라 언어·코드페이지와 무관
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Service -Name '{name}' -ErrorAction Stop).Status.ToString()"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        st = (r.stdout or "").strip()
        if r.returncode == 0 and st:
            return st.lower() == "running", st.upper()
    except Exception:  # noqa: BLE001  powershell 없음 등 — sc 로
        pass
    try:
        out = subprocess.run(["sc", "query", name], capture_output=True, text=True, errors="replace", timeout=15).stdout
    except Exception as ex:  # noqa: BLE001
        return False, f"sc query 실패: {type(ex).__name__}"
    st = parse_sc_state(out)
    return st == "RUNNING", st


def _smi_names() -> list[str] | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=15).stdout
        return [ln.split(",", 1)[1].strip().rsplit("\\", 1)[-1] for ln in out.splitlines() if "," in ln]
    except Exception:  # noqa: BLE001
        return None


def _registered() -> list[dict[str, Any]]:
    try:
        import camera_registry
        return camera_registry.list_cameras()
    except Exception:  # noqa: BLE001
        return []


def run(base: str, *, no_service: bool, only_human: bool, non_interactive: bool,
        ask: Callable[[str], str] = input, out: Callable[[str], None] = print) -> int:
    auto: dict[str, dict[str, Any]] = {}
    def rec(k: str, ok: bool | None, note: str) -> None:
        auto[k] = {"result": "skipped" if ok is None else ("pass" if ok else "fail"), "note": note}
        out(f"  {k} {'건너뜀' if ok is None else ('통과' if ok else '★실패')} — {note}")

    reports = sorted(glob.glob(str(APP / "data" / "install_report_*.json")))
    report_path = Path(reports[-1]) if reports else APP / "data" / f"install_report_{time.strftime('%Y%m%d_%H%M')}.json"

    if not only_human:
        out("=== 6-1 자동 인수시험 ===")
        if no_service:
            rec("A1", None, "--no-service: 서비스 없이 설치된 개발기 임시 설치")
        else:
            ok, st = _service_running(); rec("A1", ok, f"sc query VIGENT = {st}")
        try:
            code, h = _get_health(base)
        except Exception as ex:  # noqa: BLE001
            code, h = 0, {}
            out(f"  /health 요청 실패: {type(ex).__name__}: {ex}")
        rec("A2", *eval_a2(code, h))
        rec("A3", *eval_a3(h))
        rec("A4", *eval_a4(h, _smi_names()))
        rec("A5", *eval_a5(h, _registered()))
        rec("A6", *eval_a6(h))
        try:
            import requests
            tok = _token()
            r = requests.post(base + "/alerts/test", headers={"Authorization": "Bearer " + tok},
                              json={"level": "high", "message": "[VIGENT 인수시험 A7] 설치 직후 알림 채널 시험"}, timeout=30)
            rec("A7", *eval_a7(r.json() if r.status_code == 200 else {"results": [], "http": r.status_code}))
        except Exception as ex:  # noqa: BLE001
            rec("A7", False, f"요청 실패: {type(ex).__name__}: {ex}")
        try:
            code2, h2 = _get_health(base)
        except Exception:  # noqa: BLE001
            code2, h2 = code, h
        rec("A8", *eval_a8(h2 if code2 == 200 else h))

    human: dict[str, str] = {}
    out("=== 6-2 사람 확인 ===")
    if non_interactive:
        human = {"H1": "skipped", "H2": "skipped"}
        out("  H1/H2 건너뜀(--non-interactive) — 나중에 acceptance_test.py --only-human 으로")
    else:
        out("  H1: 카메라 앞에 3초간 서 주세요. 10초 뒤에 묻습니다.")
        time.sleep(10)
        a = ask("  H1: 대시보드/로그에서 person 박스가 보였습니까? [y/N] ").strip().lower()
        human["H1"] = "pass" if a == "y" else "warn"
        a = ask("  H2: A7 시험 메시지가 텔레그램(또는 메일)에 도착했습니까? [y/N] ").strip().lower()
        human["H2"] = "pass" if a == "y" else "warn"
        for k, v in human.items():
            if v == "warn":
                out(f"  {k} 경고 — 설치는 완료로 두되 재시험 권고")

    if only_human:
        rep = json.loads(report_path.read_text(encoding="utf-8-sig")) if report_path.exists() else {}   # BOM 허용(위와 같은 이유)
        auto = rep.get("auto_tests") or {}
    rep = merge_report(report_path, auto, human)
    fails = [k for k, v in auto.items() if v.get("result") == "fail"]
    out(f"=== 결과: {rep['result']} → {report_path.name} ===")
    return 1 if fails else 0


def default_base(app: Path = APP) -> str:
    """[CODE_AUDIT_20260928 #5] install.ps1 이 남긴 app/data/install_result.json 의 port 로 base URL 을 만든다. 없으면 8010."""
    p = app / "data" / "install_result.json"
    try:
        port = int((json.loads(p.read_text(encoding="utf-8-sig")) or {}).get("port") or 8010)
    except Exception:  # noqa: BLE001  파일 없음/손상 → 기본 포트
        port = 8010
    return f"http://127.0.0.1:{port}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None, help="기본: app/data/install_result.json 의 port(없으면 8010)")
    ap.add_argument("--no-service", action="store_true")
    ap.add_argument("--only-human", action="store_true")
    ap.add_argument("--non-interactive", action="store_true")
    a = ap.parse_args()
    return run(a.base or default_base(), no_service=a.no_service, only_human=a.only_human, non_interactive=a.non_interactive)


if __name__ == "__main__":
    raise SystemExit(main())
