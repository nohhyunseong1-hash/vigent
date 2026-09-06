#!/usr/bin/env python3
"""scripts/setup_env.py — 서빙 의존성 설치를 **한 번에** 끝낸다(pip 설치 + opencv GUI 빌드 제거 + cv2 검증). [5단계 마무리, 2026-09-06]

왜 필요한가(실측): supervision·trackers·rtmlib 가 GUI 빌드 opencv 를 하드 의존으로 끌어와 `pip install -r requirements.txt`
만으로는 cv2 가 headless 가 아니다(새 클론 2026-09-06: 5.0.0 GUI 가 headless 4.13 을 가림). constraints.txt 가 버전은 4.13 으로
고정하지만 GUI 빌드 자체는 남는다 → 이 스크립트가 설치 직후 GUI 빌드를 지우고 headless 를 --no-deps 로 다시 얹어
"cv2 == 4.13.x · GUI 없음" 을 **같은 실행 안에서 확인**한다(규칙 11). 실패하면 종료코드 1.

사용(대상 venv 의 python 으로):
    .\\.venv\\Scripts\\python.exe scripts\\setup_env.py            # 설치 + opencv 정리 + 검증
    .\\.venv\\Scripts\\python.exe scripts\\setup_env.py --weights  # + fetch_weights.py --all (가중치·go2rtc)
    .\\.venv\\Scripts\\python.exe scripts\\setup_env.py --no-install   # 이미 설치된 venv 의 opencv 정리·검증만
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
HEADLESS = "opencv-contrib-python-headless==4.13.0.92"     # requirements.txt 핀과 같아야 한다(테스트가 대조)
GUI_DISTS = ("opencv-python", "opencv-contrib-python", "opencv-python-headless")   # 남기는 것은 contrib-headless 하나


def _pip(*args: str, check: bool = True) -> int:
    cmd = [sys.executable, "-m", "pip", "--disable-pip-version-check", *args]
    print("  $", " ".join(cmd[2:]), flush=True)
    r = subprocess.run(cmd, cwd=str(_ROOT))
    if check and r.returncode != 0:
        raise SystemExit(f"[오류] pip 실패(exit {r.returncode}): {' '.join(args)}")
    return r.returncode


def installed_opencv() -> dict[str, str]:
    """설치된 opencv 배포판 {이름: 버전} — 같은 인터프리터 메타데이터 기준."""
    import importlib.metadata as m
    out: dict[str, str] = {}
    for d in m.distributions():
        name = (d.metadata["Name"] or "").lower()
        if name.startswith("opencv-"):
            out[name] = d.version
    return out


def verify_cv2() -> tuple[bool, str]:
    """cv2 를 **새 프로세스**에서 import 해 버전·GUI 유무를 본다(이 프로세스는 pip 전 상태를 캐시했을 수 있다)."""
    code = ("import cv2, json; bi = cv2.getBuildInformation(); "
            "gui = [l.strip() for l in bi.splitlines() if l.strip().startswith(('GUI', 'Win32 UI', 'QT', 'GTK'))]; "
            "print(json.dumps({'version': cv2.__version__, 'gui': gui}))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(_ROOT))
    if r.returncode != 0:
        return False, f"cv2 import 실패: {r.stderr.strip()[-300:]}"
    import json
    info = json.loads(r.stdout.strip().splitlines()[-1])
    ver = str(info["version"])
    gui_lines = [g for g in info["gui"] if not g.endswith(("NONE", "NO"))]
    ok = ver.startswith("4.13.") and not gui_lines
    return ok, f"cv2 {ver} · GUI 항목 {info['gui'] or ['(없음)']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--no-install", action="store_true", help="pip install 생략(opencv 정리·검증만)")
    ap.add_argument("--weights", action="store_true", help="설치 뒤 scripts/fetch_weights.py --all 실행")
    a = ap.parse_args()
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    if sys.version_info[:2] != (3, 11):
        print("[오류] Python 3.11 전용(.python-version). 대상 venv 의 python 으로 실행하세요.")
        return 1
    if not a.no_install:
        print("\n[1/3] pip install -r requirements.txt (constraints.txt 동반)")
        _pip("install", "-r", str(_ROOT / "requirements.txt"))
    print("\n[2/3] opencv 정리: GUI 빌드 제거 → headless --no-deps 재설치")
    before = installed_opencv()
    print(f"  설치 전: {before or '(opencv 없음)'}")
    to_remove = [d for d in GUI_DISTS if d in before]
    if to_remove:
        _pip("uninstall", "-y", *to_remove)
    _pip("install", "--force-reinstall", "--no-deps", HEADLESS)
    after = installed_opencv()
    print(f"  설치 후: {after}")
    print("\n[3/3] cv2 검증(새 프로세스)")
    ok, why = verify_cv2()
    print(f"  {'OK' if ok else '★실패'}: {why}")
    if set(after) != {"opencv-contrib-python-headless"}:
        print(f"  ★opencv 배포판이 headless 하나가 아니다: {sorted(after)}")
        ok = False
    if not ok:
        return 1
    if a.weights:
        print("\n[+] 가중치·바이너리 조달: fetch_weights.py --all")
        r = subprocess.run([sys.executable, str(_ROOT / "scripts" / "fetch_weights.py"), "--all"], cwd=str(_ROOT))
        if r.returncode != 0:
            print(f"  ★fetch_weights 실패(exit {r.returncode})")
            return 1
    print("\n완료 — cv2 headless 4.13 확인됨.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
