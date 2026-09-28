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
import json
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


def _torch_cuda_build() -> str:
    """현재 인터프리터의 torch CUDA 빌드 문자열('13.0' 등). 미설치·CPU 빌드면 ''.

    ★[F-33] 이 프로세스 안에서 import 하지 않고 **새 프로세스**에서 읽는다 — pip 설치 전후로 같은 프로세스가
    import 캐시를 들고 있으면 바뀐 빌드를 못 본다(verify_cv2 와 같은 이유).
    """
    r = subprocess.run([sys.executable, "-c", "import torch; print(torch.version.cuda or '')"],
                       capture_output=True, text=True, cwd=str(_ROOT))
    return r.stdout.strip() if r.returncode == 0 else ""


def requirements_for_install(cuda_build: str) -> Path:
    """설치에 쓸 requirements 경로. CUDA 빌드 torch 가 있으면 torch/torchvision 줄을 뺀 임시 파일(%TEMP%)을 돌려준다.

    ★[F-33 재발 방지, 2026-09-09] requirements.txt 의 `torch==2.12.0` 핀은 PyPI 에서 **CPU 휠**로 해석돼 이미 깔린
    +cu130 을 조용히 덮어썼다(2026-09-06 20:08 실제 사고, benchmarks/FINDINGS.md F-33). CUDA 빌드가 있으면 두 줄을
    제외하고 설치한다. CPU 빌드·미설치는 보호 대상이 아니다(requirements 그대로 = 기존 동작).
    임시 파일은 %TEMP% 에 두므로 파일 안의 `-c constraints.txt`(파일 위치 기준 상대경로) 줄은 빼고, 호출측(main)이
    `-c <절대경로>` 를 pip 인자로 따로 넘긴다(실측 2026-09-09: 파일 안에 절대경로를 적으면 pip 가 경로를 깨뜨렸다 —
    'D:\\vigent_original\\vigent_originalconstraints.txt').
    """
    req = _ROOT / "requirements.txt"
    if not cuda_build:
        return req
    import tempfile
    lines = []
    for line in req.read_text(encoding="utf-8").splitlines():
        code = line.split("#")[0].strip()
        if code.startswith(("torch==", "torchvision==", "-c ")):
            continue
        lines.append(line)
    tmp = Path(tempfile.gettempdir()) / "vigent_setup_env_requirements_no_torch.txt"
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp


PROTECTED_PINS = ("numpy", "opencv-contrib-python-headless")   # [CODE_AUDIT_20260928 B-3] rfdetr[train]·albumentations 가 강등/교체하던 것


def requirement_pins(req: Path | None = None) -> dict[str, str]:
    """requirements.txt 의 `name==ver` 핀 → {소문자 이름: 버전}. 주석·`-r/-c` 줄은 무시."""
    req = req or (_ROOT / "requirements.txt")
    pins: dict[str, str] = {}
    for ln in req.read_text(encoding="utf-8").splitlines():
        code = ln.split("#", 1)[0].strip()
        if "==" in code and not code.startswith("-"):
            name, ver = code.split("==", 1)
            pins[name.strip().lower()] = ver.strip()
    return pins


def check_pins(installed: dict[str, str], pins: dict[str, str], names: tuple[str, ...] = PROTECTED_PINS) -> list[str]:
    """설치본이 핀과 다르거나 없으면 사유 목록(빈 목록 = 통과). [B-3] F-33(torch) 가드의 numpy·cv2 판 — 순수 함수라 테스트가 고정한다."""
    out: list[str] = []
    for n in names:
        want = pins.get(n.lower())
        if want is None:
            continue
        have = installed.get(n.lower())
        if have is None:
            out.append(f"{n}: 미설치 (핀 {want})")
        elif have != want:
            out.append(f"{n}: 설치 {have} != 핀 {want}")
    return out


def installed_versions(names: tuple[str, ...] = PROTECTED_PINS) -> dict[str, str]:
    """이름별 설치 버전(없으면 빠짐) — **새 프로세스**에서 읽는다(pip 전후 같은 프로세스의 메타데이터 캐시를 피한다)."""
    code = ("import importlib.metadata as m, json, sys; out = {}\n"
            "for n in sys.argv[1:]:\n"
            "    try: out[n.lower()] = m.version(n)\n"
            "    except Exception: pass\n"
            "print(json.dumps(out))")
    r = subprocess.run([sys.executable, "-c", code, *names], capture_output=True, text=True)
    try:
        return dict(json.loads(r.stdout.strip() or "{}"))
    except Exception:  # noqa: BLE001
        return {}


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
        cuda_before = _torch_cuda_build()
        req = requirements_for_install(cuda_before)
        if cuda_before:
            print(f"\n[1/3] pip install -r requirements.txt (constraints.txt 동반) — ★경고: torch CUDA 빌드(cu{cuda_before}) 보호를 위해 "
                  f"torch/torchvision 줄을 제외하고 설치한다(F-33). 임시 목록: {req}")
        else:
            print("\n[1/3] pip install -r requirements.txt (constraints.txt 동반) — torch 는 PyPI CPU 휠이 설치된다"
                  "(GPU 는 md/DEPLOYMENT.md §3 의 CUDA 휠로 교체)")
        if cuda_before:
            _pip("install", "-r", str(req), "-c", str(_ROOT / "constraints.txt"))   # 임시 목록엔 -c 줄이 없다 → 여기서 동반
        else:
            _pip("install", "-r", str(req))
        if cuda_before:
            cuda_after = _torch_cuda_build()
            if cuda_after != cuda_before:
                print(f"  ★[오류] torch 빌드가 cu{cuda_before} → {cuda_after or 'cpu/없음'} 로 바뀌었다(F-33 재발). "
                      f"복구: requirements.txt 의 CUDA 휠 설치 명령(--index-url https://download.pytorch.org/whl/cu{cuda_before.replace('.', '')})")
                return 1
            print(f"  torch CUDA 빌드 유지 확인: cu{cuda_after}")
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
    # [CODE_AUDIT_20260928 B-3] numpy·cv2 핀 가드 — rfdetr[train]·albumentations 설치가 numpy 를 강등하거나 cv2 를 바꿔도 여기서 잡힌다
    bad = check_pins(installed_versions(), requirement_pins())
    if bad:
        print("  ★핀 불일치(requirements.txt 와 다름 — 학습 의존성 설치가 바꿨을 가능성): " + "; ".join(bad))
        ok = False
    else:
        print("  핀 확인: " + ", ".join(PROTECTED_PINS) + " = requirements.txt")
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
