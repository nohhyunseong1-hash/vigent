#!/usr/bin/env python3
r"""usb_layout.py — USB 설치기 1차: USB 루트 **레이아웃 계약** + 검증. [USB 1차 계획 1]

★이 docstring 은 raw 문자열이다 — 아래에 `installer\uninstall.ps1` 같은 Windows 경로가 있어 `\u` 가
  유니코드 이스케이프로 읽히면 SyntaxError 가 난다(2026-09-23 실제로 났다: import 자체가 실패해 테스트·빌드가 같이 죽었다).

★왜 파이썬인가: build_usb.ps1(빌드)과 tests/test_usb_layout.py(테스트)가 **같은 계약**을 봐야 한다.
  PowerShell 에만 적어 두면 테스트가 못 읽고, 테스트에만 적어 두면 빌드가 다른 걸 만든다.
  이 파일이 유일한 정본이고 둘 다 여기를 부른다.

USB 루트 레이아웃 (설계서 docs/deploy/usb_installer_design.md §3·§7):
  VERSION.txt                태그 · 빌드일 · 커밋 SHA · 포터블 용량  (사람이 읽는다)
  usb_manifest.json          이 계약의 기계용 사본 + 파일별 크기·SHA256 (설치기가 읽는다)
  설치.bat                   더블클릭 진입점 → installer\install.ps1
  installer\install.ps1      설치 본체(계획 2) — 없으면 빌드가 경고만 하고 계속(1차 진행 순서상 뒤에 온다)
  installer\preflight.ps1    사양 검사(G-4·H-1)
  installer\uninstall.ps1    제거(계획 2)
  portable\                  build_portable.ps1 -Gpu 산출물 그대로 (python\ · app\ · VIGENT_시작.bat · vc_redist.x64.exe · python\wheels_cuda\)
  driver\README.txt          NVIDIA 드라이버 exe 를 사람이 넣는 자리(경로 빈칸 — 설계서 §2)
  ★portable\app\.git 은 있으면 안 된다(기기에서 git 금지, §7).

사용:
    python scripts/deploy/usb_layout.py verify <usb_root>      # 종료코드 0=통과, 1=미달(항목별 한 줄)
    python scripts/deploy/usb_layout.py manifest <usb_root> --tag v1.0 --commit abc1234   # usb_manifest.json 생성
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

# 필수 파일/폴더 (상대경로, 뒤에 '/' 면 폴더). 이 목록이 계약이다.
REQUIRED: list[str] = [
    "VERSION.txt",
    "usb_manifest.json",
    "설치.bat",
    "installer/preflight.ps1",
    "installer/setup_wizard.py",       # 계획 3: 첫 실행 마법사 — install.ps1 이 <Target>\app\scripts\deploy\ 로 복사한다
    # 서비스 런처·NSSM — 포터블 빌드가 app\deploy\windows 를 잘라내므로 USB 가 따로 싣고 install.ps1 이 되돌린다
    "installer/windows/service_entry.py",
    "installer/windows/nssm.exe",
    "installer/windows/install_service.ps1",
    "portable/",
    "portable/VIGENT_시작.bat",
    "portable/vc_redist.x64.exe",
    "portable/python/python.exe",
    "portable/python/wheels_cuda/",
    "portable/app/vigent-core/main.py",
    "portable/app/vigent-core/weights/ppe_rfdetr_v1.pth",
    "portable/app/config/tuning.yaml",
    "driver/README.txt",
]
# 있으면 좋지만 1차 순서상 나중에 채워지는 것 — 없으면 '경고'
OPTIONAL: list[str] = ["installer/install.ps1", "installer/uninstall.ps1"]
# 있으면 안 되는 것
FORBIDDEN: list[str] = ["portable/app/.git", "portable/app/.git/", "portable/app/config/notify.yaml",
                        "portable/app/data/camera_secrets.json"]
# SHA256 을 매니페스트에 싣는 핵심 파일(설치 후 A-검증에서 대조)
HASHED: list[str] = ["portable/VIGENT_시작.bat", "portable/vc_redist.x64.exe", "portable/app/vigent-core/main.py",
                     "portable/app/vigent-core/weights/ppe_rfdetr_v1.pth", "installer/preflight.ps1"]


def _exists(root: Path, rel: str) -> bool:
    p = root / rel.rstrip("/")
    return p.is_dir() if rel.endswith("/") else p.is_file()


def verify(root: Path) -> tuple[list[str], list[str]]:
    """(미달 목록, 경고 목록). 미달이 있으면 설치기는 시작하면 안 된다."""
    fails, warns = [], []
    for rel in REQUIRED:
        if not _exists(root, rel):
            fails.append(f"없음: {rel}")
    for rel in OPTIONAL:
        if not _exists(root, rel):
            warns.append(f"아직 없음(1차 순서상 뒤): {rel}")
    for rel in FORBIDDEN:
        p = root / rel.rstrip("/")
        if p.exists():
            fails.append(f"있으면 안 됨: {rel}")
    wc = root / "portable" / "python" / "wheels_cuda"
    if wc.is_dir() and not any(wc.glob("torch-*+cu*.whl")):
        fails.append("wheels_cuda 에 torch cu 휠이 없다(-Gpu 빌드가 아니다)")
    tun = root / "portable" / "app" / "config" / "tuning.yaml"
    if tun.is_file():
        t = tun.read_text(encoding="utf-8", errors="replace")
        if "backend: torch" not in t:
            fails.append("portable tuning.yaml 의 detect.backend 가 torch 가 아니다(GPU 빌드는 torch 여야 한다 — I-1)")
    man = root / "usb_manifest.json"
    if man.is_file():
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
            for rel, h in (m.get("sha256") or {}).items():
                p = root / rel
                if p.is_file() and _sha256(p) != h:
                    fails.append(f"SHA256 불일치: {rel}")
        except Exception as ex:  # noqa: BLE001
            fails.append(f"usb_manifest.json 읽기 실패: {type(ex).__name__}")
    return fails, warns


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def manifest(root: Path, tag: str, commit: str) -> dict:
    portable = root / "portable"
    m = {
        "schema": 1, "tag": tag, "commit": commit,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "portable_bytes": _tree_size(portable) if portable.is_dir() else None,
        "portable_files": sum(1 for f in portable.rglob("*") if f.is_file()) if portable.is_dir() else None,
        "required": REQUIRED, "optional": OPTIONAL, "forbidden": FORBIDDEN,
        "sha256": {rel: _sha256(root / rel) for rel in HASHED if (root / rel).is_file()},
    }
    (root / "usb_manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify"); v.add_argument("root")
    mf = sub.add_parser("manifest"); mf.add_argument("root"); mf.add_argument("--tag", required=True); mf.add_argument("--commit", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    if a.cmd == "manifest":
        m = manifest(root, a.tag, a.commit)
        print(f"usb_manifest.json: {m['portable_bytes'] / 1024**3:.2f} GB · {m['portable_files']:,} 파일 · sha256 {len(m['sha256'])}건")
        return 0
    fails, warns = verify(root)
    for w in warns:
        print(f"  [경고] {w}")
    for f in fails:
        print(f"  [미달] {f}")
    print("USB 레이아웃: " + ("통과" if not fails else f"미달 {len(fails)}건"))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
