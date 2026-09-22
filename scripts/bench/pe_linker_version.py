"""포터블 DLL/EXE 의 PE 링커 버전(=MSVC 빌드툴 버전)을 읽는다.

근거: Microsoft Learn "C++ binary compatibility 2015-2026"
  "the Redistributable version must be at least as new as the latest build tools
   used by any app component."
→ 시스템 VC++ 재배포 하한 = 구성요소 중 가장 높은 빌드툴 버전.
"""
import struct
import sys
from pathlib import Path


def linker_version(p: Path):
    try:
        with p.open("rb") as f:
            if f.read(2) != b"MZ":
                return None
            f.seek(0x3C)
            off = struct.unpack("<I", f.read(4))[0]
            f.seek(off)
            if f.read(4) != b"PE\0\0":
                return None
            f.seek(off + 24)                 # COFF 헤더 20바이트 뒤 = 옵션 헤더
            oh = f.read(4)
            return (oh[2], oh[3])            # Major, Minor LinkerVersion
    except Exception:
        return None


root = Path(sys.argv[1])
pats = ["**/*.dll", "**/*.pyd", "python/python.exe"]
best = (0, 0)
best_files: list[str] = []
counted = 0
by_ver: dict[tuple[int, int], int] = {}
for pat in pats:
    for p in root.glob(pat):
        v = linker_version(p)
        if not v or v[0] != 14:              # MSVC v14.x 만 본다(다른 툴체인 제외)
            continue
        counted += 1
        by_ver[v] = by_ver.get(v, 0) + 1
        if v > best:
            best, best_files = v, [str(p.relative_to(root))]
        elif v == best and len(best_files) < 5:
            best_files.append(str(p.relative_to(root)))

print(f"검사 대상(MSVC v14.x PE): {counted}개")
print("링커 버전 분포(상위 8):")
for v, n in sorted(by_ver.items(), reverse=True)[:8]:
    print(f"  14.{v[1]:<3} : {n:>6}개")
print(f"\n최댓값 = 14.{best[1]}")
for f in best_files:
    print(f"  - {f}")
