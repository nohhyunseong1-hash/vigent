#!/usr/bin/env python3
"""[현장 준비] 오프라인 완주 자동 기록 — 사람이 랜선을 뽑는 동안 스스로 증거를 남긴다.

왜 필요한가: 검증하는 사람(또는 원격 에이전트)이 **그 노트북의 네트워크로 접속해 있으면**
끊는 순간 자기도 끊겨 실시간 관측이 불가능하다. 그래서 로컬에서 주기 샘플링해 파일로
남기고, 복구 후 그 파일을 읽어 판정한다.

측정 대상(=오프라인에서 깨지면 안 되는 것):
  1. /health 가 계속 healthy 인가 (127.0.0.1 이라 인터넷과 무관해야 한다)
  2. 카메라 워커가 계속 검출하는가 (last_detect_age_s 가 갱신되는가)
  3. 인터넷이 실제로 끊겼는가 (끊기지 않았다면 시험 자체가 무의미 — 이걸 반드시 같이 잰다)
  4. 로그에 신규 다운로드 시도가 있는가 (rf-detr-nano / rtmlib 캐시 미스)

사용:
    python scripts/offline_probe.py --minutes 6
    → audit/offline_probe_<시각>.json 및 .md 생성
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
_LOG = _ROOT / "logs" / "vigent.err.log"
_OUT = _ROOT / "audit"

HEALTH = "http://127.0.0.1:8010/health"


def internet_up(timeout: float = 3.0) -> bool:
    """외부 도달 가능 여부. DNS+TCP 둘 다 본다(둘 중 하나만 죽는 경우가 있다)."""
    for host, port in (("api.telegram.org", 443), ("storage.googleapis.com", 443)):
        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            continue
    return False


def sample() -> dict:
    row: dict = {"t": time.strftime("%H:%M:%S"), "internet": internet_up()}
    try:
        with urllib.request.urlopen(HEALTH, timeout=8) as r:
            d = json.loads(r.read().decode("utf-8"))
        row["http"] = r.status
        row["status"] = d.get("status")
        row["phase"] = d.get("phase")
        cams = d.get("cameras") or {}
        row["cameras"] = {k: {"status": v.get("status"),
                              "detect_age_s": v.get("last_detect_age_s"),
                              "infer_ms": v.get("infer_ms")}
                          for k, v in cams.items()}
        row["alerts"] = d.get("alerts")
    except (urllib.error.URLError, OSError, ValueError) as ex:
        row["http"] = None
        row["error"] = str(ex)[:200]
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="오프라인 완주 자동 기록")
    ap.add_argument("--minutes", type=float, default=6.0, help="총 관측 시간(분)")
    ap.add_argument("--interval", type=float, default=5.0, help="샘플 주기(초)")
    ap.add_argument("--min-run", type=int, default=3,
                    help="통과에 필요한 **연속** 오프라인 샘플 수(짧은 단절 반복을 통과시키지 않는다)")
    a = ap.parse_args()
    min_run = a.min_run

    log_start = _LOG.stat().st_size if _LOG.exists() else 0
    t_end = time.time() + a.minutes * 60
    rows: list[dict] = []
    print(f"관측 시작 — {a.minutes:.0f}분 · {a.interval:.0f}초 주기. 지금 네트워크를 끊으세요.")
    while time.time() < t_end:
        r = sample()
        rows.append(r)
        cam = next(iter(r.get("cameras", {}).values()), {})
        print(f"  {r['t']}  인터넷={'O' if r['internet'] else 'X'}  "
              f"http={r.get('http')}  {r.get('status')}  "
              f"cam={cam.get('status')} age={cam.get('detect_age_s')}s", flush=True)
        time.sleep(a.interval)

    # 관측 중 새로 쌓인 로그에서 다운로드 시도 탐지
    new_log = ""
    if _LOG.exists():
        with _LOG.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(log_start)
            new_log = f.read()
    downloads = [ln.strip()[:160] for ln in new_log.splitlines() if "Downloading" in ln]

    offline = [r for r in rows if not r["internet"]]

    # 연속 오프라인 최장 구간 — 뽑았다 꽂았다 하면 짧은 단절만 잡혀 시험이 무의미해진다.
    longest = cur = 0
    for r in rows:
        cur = cur + 1 if not r["internet"] else 0
        longest = max(longest, cur)

    def cams_ok(r: dict) -> bool:
        c = r.get("cameras") or {}
        return bool(c) and all(v.get("status") == "ok" for v in c.values())

    # ★status 는 healthy 가 아니어도 된다. 인터넷이 끊기면 텔레그램이 못 나가고,
    #   설계상 '미전송 경보 있음 → degraded'(md/DEPLOYMENT.md §8)가 **정상**이다.
    #   봐야 할 것은 "검출이 살아 있는가" 이지 "경보가 나갔는가" 가 아니다.
    serving = [r for r in offline if r.get("http") == 200 and r.get("status") in ("healthy", "degraded")]
    detecting = [r for r in offline if cams_ok(r)]

    verdict = {
        "samples": len(rows),
        "offline_samples": len(offline),
        "longest_offline_run": longest,
        "serving_while_offline": len(serving),
        "detecting_while_offline": len(detecting),
        "download_attempts": len(downloads),
        "download_lines": downloads[:10],
    }
    fails = []
    if not offline:
        fails.append("관측 중 인터넷이 한 번도 끊기지 않았다(시험 무효)")
    if offline and longest < min_run:
        fails.append(f"연속 오프라인 최장 {longest}샘플 < 요구 {min_run}샘플 — "
                     "짧은 단절만 잡혀 지속 단절을 증명하지 못한다")
    if offline and len(serving) != len(offline):
        fails.append(f"오프라인 중 서비스 응답 실패 {len(offline) - len(serving)}건")
    if offline and len(detecting) != len(offline):
        fails.append(f"오프라인 중 검출 정지 {len(offline) - len(detecting)}건")
    if downloads:
        fails.append(f"신규 다운로드 시도 {len(downloads)}건 — 캐시 미비")

    verdict["fails"] = fails
    verdict["result"] = ("통과 — 오프라인 지속 구간에서 서비스 응답 + 검출 지속, 다운로드 0건"
                         if not fails else "★실패 — " + " / ".join(fails))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    _OUT.mkdir(exist_ok=True)
    (_OUT / f"offline_probe_{stamp}.json").write_text(
        json.dumps({"verdict": verdict, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")

    md = [f"# 오프라인 완주 자동 기록 ({time.strftime('%Y-%m-%d %H:%M')})", "",
          f"**판정: {verdict['result']}**", "",
          f"- 총 샘플 {verdict['samples']} · 그중 오프라인 {verdict['offline_samples']}",
          f"- **연속** 오프라인 최장 {verdict['longest_offline_run']}샘플",
          f"- 오프라인 중 서비스 응답(200·healthy|degraded) {verdict['serving_while_offline']}/{verdict['offline_samples']}",
          f"- 오프라인 중 검출 지속 {verdict['detecting_while_offline']}/{verdict['offline_samples']}",
          f"- 신규 다운로드 시도 **{verdict['download_attempts']}건**", "",
          "| 시각 | 인터넷 | HTTP | status | 카메라 | detect_age |", "|---|---|---|---|---|---|"]
    for r in rows:
        cam = next(iter(r.get("cameras", {}).values()), {})
        md.append(f"| {r['t']} | {'O' if r['internet'] else '**X**'} | {r.get('http')} | "
                  f"{r.get('status')} | {cam.get('status')} | {cam.get('detect_age_s')} |")
    if downloads:
        md += ["", "## ★다운로드 시도(있으면 실패)", ""] + [f"- `{d}`" for d in downloads]
    (_OUT / f"offline_probe_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print()
    print(verdict["result"])
    print(f"기록: audit/offline_probe_{stamp}.md")
    return 0 if verdict["result"].startswith("통과") else 1


if __name__ == "__main__":
    raise SystemExit(main())
