"""portable_cleanup.py — VIGENT_데이터정리.bat 의 실제 작업(삭제 대상 계산·표시·삭제·잔여 목록).

사용: python portable_cleanup.py plan|run <app\\data> <state\\logs> keep|all
  plan : 삭제 대상 파일 수·용량·목록을 출력. 종료코드 0=대상 있음, 2=대상 없음, 1=오류
  run  : 삭제 후 남은 파일 목록 출력

삭제 규칙(근거는 VIGENT_데이터정리.bat 머리 주석):
  · 항상 남김: data\\legal\\**(법령 화이트리스트, 읽기 전용 자산)
  · keep 모드에서 남김: data\\cameras.json · data\\camera_secrets.json(+ .bak) · data\\go2rtc.runtime.yaml(카메라 스트림·자격증명)
  · 그 외 data\\ 아래 모든 파일(증거 evidence\\, 인식 recognition\\, 감사 audit\\, tbm\\, risk_assessments\\, retention\\,
    alert_queue.db, retention_status.json, startup_failure.json, go2rtc.log, go2rtc.pid, track_debug.jsonl 등)과 logs\\ 아래 모든 파일
  · all 모드: keep 목록도 지운다(legal 만 남김)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ALWAYS_KEEP_DIRS = ("legal",)
KEEP_MODE_FILES = {"cameras.json", "cameras.json.bak", "camera_secrets.json", "camera_secrets.json.bak", "go2rtc.runtime.yaml"}


def targets(data: Path, logs: Path, mode: str) -> tuple[list[Path], list[Path]]:
    """(삭제 대상, 남길 파일)"""
    dele: list[Path] = []
    keep: list[Path] = []
    if data.exists():
        for p in sorted(data.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(data)
            if rel.parts and rel.parts[0] in ALWAYS_KEEP_DIRS:
                keep.append(p)
            elif mode == "keep" and len(rel.parts) == 1 and rel.name in KEEP_MODE_FILES:
                keep.append(p)
            else:
                dele.append(p)
    if logs.exists():
        dele += [p for p in sorted(logs.rglob("*")) if p.is_file()]
    return dele, keep


def fmt(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.0f} KB"


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] not in ("plan", "run") or sys.argv[4] not in ("keep", "all"):
        print(__doc__)
        return 1
    cmd, data, logs, mode = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    dele, keep = targets(data, logs, mode)
    if cmd == "plan":
        if not dele:
            return 2
        total = sum(p.stat().st_size for p in dele)
        print(f"  삭제 대상: {len(dele)}개 파일, {fmt(total)}")
        by_dir: dict[str, tuple[int, int]] = {}
        for p in dele:
            root = data if str(p).startswith(str(data)) else logs
            key = str(p.relative_to(root).parent) if p.relative_to(root).parent != Path(".") else "(루트)"
            key = ("data\\" if root == data else "logs\\") + key
            c, s = by_dir.get(key, (0, 0))
            by_dir[key] = (c + 1, s + p.stat().st_size)
        for k, (c, s) in sorted(by_dir.items()):
            print(f"    {k:40s} {c:6d}개  {fmt(s):>10s}")
        if keep:
            print(f"  남기는 파일: {len(keep)}개 — " + ", ".join(str(p.relative_to(data)) for p in keep[:8]) + (" …" if len(keep) > 8 else ""))
        return 0
    # run
    n_ok = n_fail = 0
    for p in dele:
        try:
            p.unlink()
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            print(f"  [실패] {p}: {e}")
    # 빈 디렉터리 정리(legal 제외) — 다음 기동 때 서버가 다시 만든다
    for root in (data, logs):
        if not root.exists():
            continue
        for d in sorted((x for x in root.rglob("*") if x.is_dir()), key=lambda x: -len(x.parts)):
            if d.name in ALWAYS_KEEP_DIRS or any(part in ALWAYS_KEEP_DIRS for part in d.relative_to(root).parts):
                continue
            try:
                d.rmdir()
            except OSError:
                pass
    print(f"  삭제 완료: {n_ok}개" + (f", 실패 {n_fail}개" if n_fail else ""))
    left = [p for p in sorted(data.rglob("*")) if p.is_file()] if data.exists() else []
    left_logs = [p for p in sorted(logs.rglob("*")) if p.is_file()] if logs.exists() else []
    print(f"  남은 파일(app\\data): {len(left)}개")
    for p in left:
        print(f"    {p.relative_to(data)}  {fmt(p.stat().st_size)}")
    print(f"  남은 파일(state\\logs): {len(left_logs)}개")
    for p in left_logs:
        print(f"    {p.relative_to(logs)}  {fmt(p.stat().st_size)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
