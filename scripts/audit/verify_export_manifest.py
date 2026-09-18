"""노트북 반출 묶음의 MANIFEST.txt(SHA256·바이트)와 실제 파일을 대조한다(읽기 전용).

사용: python scripts/audit/verify_export_manifest.py audit/export_laptop_2026-09-18
종료코드: 전부 일치 0, 하나라도 불일치·누락 1, MANIFEST 에 행이 0개면 2(규칙 11 — 0건은 실패로 의심).
"""
import hashlib
import re
import sys
from pathlib import Path


def main(folder: str) -> int:
    root = Path(folder)
    rows = []
    for line in (root / "MANIFEST.txt").read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|\s*([0-9A-Fa-f]{64})\s*\|", line)
        if m:
            rows.append((m.group(1), int(m.group(2)), m.group(3).upper()))
    if not rows:
        print("MANIFEST 에서 해시 행을 하나도 못 읽음 — 실패")
        return 2
    bad = 0
    for src, size, sha in rows:
        name = src.replace("\\", "/").rsplit("/", 1)[-1]
        p = root / name
        if not p.is_file():
            print(f"누락   {name}")
            bad += 1
            continue
        data = p.read_bytes()
        got = hashlib.sha256(data).hexdigest().upper()
        ok = got == sha and len(data) == size
        bad += 0 if ok else 1
        print(f"{'일치' if ok else '불일치'}  {name}  {len(data)}B/{size}B  {got[:12]}…")
    listed = {r[0].replace("\\", "/").rsplit("/", 1)[-1] for r in rows}
    extra = sorted(f.name for f in root.iterdir() if f.is_file() and f.name not in listed)
    print(f"MANIFEST 해시 행 {len(rows)}개 · 일치 {len(rows) - bad} · 불일치/누락 {bad}")
    print(f"해시 없는 파일(폴더에서 새로 만든 것) {len(extra)}개: {extra}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
