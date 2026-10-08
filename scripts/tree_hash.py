#!/usr/bin/env python3
"""scripts/tree_hash.py — 디렉터리 트리의 파일별 SHA256 스냅샷과 두 스냅샷 비교(테스트 오염 검증 도구). [5단계 마무리, 2026-09-06]

왜: 규칙 11 — "테스트가 운영 데이터를 안 건드린다"는 말이 아니라 **전후 해시 비교**로 증명한다. 4단계 ④ 때는 data/ 만
  손으로 비교했다(28,815파일). 이제 data/ + logs/ 를 도구로 잰다(테스트가 logs/events.jsonl 에 dispatch_relay 행을 남긴
  실사고 2026-09-06 21:2x 이후 범위 확장).

사용:
    python scripts/tree_hash.py snapshot data logs -o before.json
    python -m unittest discover -s tests
    python scripts/tree_hash.py snapshot data logs -o after.json
    python scripts/tree_hash.py compare before.json after.json      # 추가·삭제·변경 0 이면 종료코드 0, 아니면 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# [2026-10-08 새 환경 점검] cp949 콘솔(PYTHONUTF8 미설정 Windows)에서 한글·기호 print 가 UnicodeEncodeError 로 죽던 것 —
#   실측: setup_env.py 가 새 clone 의 첫 print 에서 종료돼 pip 설치가 시작도 안 됐다. stdout/stderr 를 UTF-8 로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


_ROOT = Path(__file__).resolve().parent.parent


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def snapshot(dirs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for d in dirs:
        base = (_ROOT / d) if not Path(d).is_absolute() else Path(d)
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(_ROOT)) if p.is_relative_to(_ROOT) else str(p)
                try:
                    out[rel] = sha256_of(p)
                except OSError as ex:      # 열려 있는 로그 등 — 상태를 기록에 남긴다(조용히 빠뜨리지 않는다)
                    out[rel] = f"ERR:{type(ex).__name__}"
    return out


def compare(a: dict[str, str], b: dict[str, str]) -> dict[str, list[str]]:
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    changed = sorted(k for k in a if k in b and a[k] != b[k])
    return {"added": added, "removed": removed, "changed": changed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("dirs", nargs="+")
    s.add_argument("-o", "--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snap = snapshot(a.dirs)
        Path(a.out).write_text(json.dumps(snap, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"스냅샷 {len(snap):,}파일 → {a.out}")
        return 0
    before = json.loads(Path(a.before).read_text(encoding="utf-8"))
    after = json.loads(Path(a.after).read_text(encoding="utf-8"))
    d = compare(before, after)
    print(f"전 {len(before):,}파일 / 후 {len(after):,}파일 — 추가 {len(d['added'])} · 삭제 {len(d['removed'])} · 변경 {len(d['changed'])}")
    for k in ("added", "removed", "changed"):
        for p in d[k][:30]:
            print(f"  [{k}] {p}")
    return 0 if not (d["added"] or d["removed"] or d["changed"]) else 1


if __name__ == "__main__":
    sys.exit(main())
