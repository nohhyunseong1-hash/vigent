#!/usr/bin/env python3
"""scripts/check_pip_deps.py — `pip check` 를 **화이트리스트**로 판정한다. [CODE_AUDIT_20260928 B-6]

왜: 이 저장소는 GUI 빌드 opencv 를 의도적으로 빼고 `opencv-contrib-python-headless` 하나만 둔다(requirements.txt·setup_env.py).
    그래서 albucore·albumentations(opencv-python-headless 요구)·rtmlib(opencv-contrib-python·opencv-python)·supervision·trackers(opencv-python)
    가 `pip check` 에서 항상 6건 "not installed" 로 나오고, 그 때문에 pip check 를 게이트·CI 에 넣지 못했다.
    여기서는 그 6건(= **cv2 이름 불일치, headless 로 충족되는 것**)만 허용하고, 그 밖의 어떤 줄이든 나오면 실패한다
    (예: 버전 충돌 "has requirement X, but you have Y" · 실제로 빠진 패키지).

사용:  python scripts/check_pip_deps.py            # 종료코드 0 = 허용 목록 안, 1 = 그 밖의 문제
       python scripts/check_pip_deps.py --show     # pip check 원문도 출력
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# 허용: <이름> <버전> requires opencv-(python|python-headless|contrib-python), which is not installed.
#   → headless(contrib) 가 cv2 모듈을 제공하므로 실제로는 충족된다(설치 시 GUI 빌드를 지운 것이 의도).
ALLOWED_PKGS = ("albucore", "albumentations", "rtmlib", "supervision", "trackers")
_ALLOWED = re.compile(r"^(?P<pkg>" + "|".join(ALLOWED_PKGS) + r") \S+ requires opencv-(python|python-headless|contrib-python), which is not installed\.$")
HEADLESS = "opencv-contrib-python-headless"


def classify(lines: list[str]) -> tuple[list[str], list[str]]:
    """pip check 출력 줄 → (허용된 줄, 허용되지 않은 줄). 빈 줄·'No broken requirements found.' 는 무시."""
    ok, bad = [], []
    for ln in lines:
        s = ln.strip()
        if not s or s.lower().startswith("no broken requirements"):
            continue
        (ok if _ALLOWED.match(s) else bad).append(s)
    return ok, bad


def headless_installed() -> bool:
    try:
        import importlib.metadata as md
        md.version(HEADLESS)
        return True
    except Exception:  # noqa: BLE001
        return False


def run_pip_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # cp949 콘솔에서 한글·기호로 죽지 않게
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    code, out = run_pip_check()
    if a.show:
        print(out.rstrip())
    ok, bad = classify(out.splitlines())
    if ok and not headless_installed():
        print(f"★{HEADLESS} 가 없다 — cv2 허용 6건은 headless 가 있을 때만 무해하다")
        return 1
    print(f"pip check: 허용(cv2 이름 불일치·headless 충족) {len(ok)}건 · 그 밖 {len(bad)}건 · pip 종료코드 {code}")
    for b in bad:
        print("  ✗ " + b)
    if bad:
        return 1
    print("OK — 허용 목록 밖의 의존성 문제 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
