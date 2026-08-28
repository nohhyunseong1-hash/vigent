#!/usr/bin/env python3
"""테스트 스위트를 **실행 순서를 섞어** 여러 번 돌린다 — 순서 의존 결함(flake) 검증용.

★왜 필요한가(2026-08-28): relay flake 의 원인 하나가 **다른 테스트가 띄운 배경 스레드**였다.
그런 결함은 실행 순서에 따라 나타났다 사라진다. 고정 순서로 몇 번 통과했다고
"해결"이라 말하면 근거가 부족하다 — 수정 전 실패율이 3회 중 2회였다면
우연히 2회 통과할 확률이 약 11%다.

사용:
    python scripts/run_tests_shuffled.py --runs 10
    python scripts/run_tests_shuffled.py --runs 10 --seed-base 100

각 회차는 **다른 시드**로 테스트 순서를 섞고, 실패한 테스트 이름을 함께 남긴다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _run_one(seed: int, start_dir: str) -> tuple[int, list[str]]:
    """★한 회차를 **별도 프로세스**로 돌린다.

    처음에는 한 프로세스에서 10회를 반복했는데, 그건 실제 게이트(매번 새 프로세스로
    `unittest discover`)와 다르다. 회차 간에 모듈 전역·파일 상태가 쌓여
    **6회차부터 일관되게 실패**하는 현상이 나왔고, 그건 순서 의존 결함이 아니라
    **측정 도구가 만든 인공물**이었다. 프로세스를 분리하면 그 오염이 사라지고,
    순서 셔플이라는 본래 신호만 남는다.
    """
    code = textwrap.dedent(f"""
        import json, random, sys, unittest
        def flat(s):
            out=[]
            for i in s:
                out.extend(flat(i)) if isinstance(i, unittest.TestSuite) else out.append(i)
            return out
        loader = unittest.TestLoader()
        tests = flat(loader.discover(start_dir={start_dir!r}, top_level_dir={start_dir!r}))
        random.Random({seed}).shuffle(tests)
        r = unittest.TextTestRunner(verbosity=0).run(unittest.TestSuite(tests))
        bad = []
        for t, tb in r.failures + r.errors:
            last = [x for x in tb.strip().splitlines() if x.strip()][-1]
            bad.append(t.id().split(".", 1)[-1] + " :: " + last[:120])
        print("SHUFFLE_RESULT " + json.dumps({{"ran": r.testsRun, "bad": bad}}, ensure_ascii=False))
    """)
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               VIGENT_API_TOKEN="", VIGENT_REQUIRE_TOKEN="0")
    pr = subprocess.run([sys.executable, "-u", "-c", code], capture_output=True,
                        text=True, encoding="utf-8", errors="replace", env=env, cwd=str(_ROOT))
    for line in (pr.stdout or "").splitlines():
        if line.startswith("SHUFFLE_RESULT "):
            d = json.loads(line[len("SHUFFLE_RESULT "):])
            return d["ran"], d["bad"]
    return 0, [f"(결과 파싱 실패 rc={pr.returncode}) " + (pr.stderr or "")[-200:]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--start-dir", default="tests")
    args = ap.parse_args()

    start = str(_ROOT / args.start_dir)
    results = []
    for i in range(1, args.runs + 1):
        seed = args.seed_base + i
        ran, bad = _run_one(seed, start)
        results.append((i, seed, ran, bad))
        print(f"  회차 {i:>2} (seed {seed:>3})  {ran}건  " + ("OK" if not bad else "FAILED"))
        for b in bad:
            print(f"      ← {b}")

    print()
    ok = sum(1 for r in results if not r[3])
    print(f"★결과: {ok}/{args.runs} 회 통과 (회차마다 **별도 프로세스** · 순서 셔플)")
    if ok < args.runs:
        c = Counter(b.split(" :: ")[0] for r in results for b in r[3])
        print("★실패한 테스트(횟수):")
        for name, n in c.most_common():
            print(f"    {name}  {n}회")
        return 1
    print("★전 회차 통과 — 순서 셔플에도 재현되지 않았다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
