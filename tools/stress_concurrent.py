#!/usr/bin/env python3
"""VIGENT 동시요청 스트레스 하네스 — F-14(동시부하 네이티브 크래시) 실증·회귀가드.

무엇을 하나:
  실행 중인 서버에 **여러 클라이언트가 동시에** 추론 엔드포인트를 두드린다. 브라우저 여러 개가
  라이브뷰·재해분석을 동시에 여는 상황을 재현한다. F-14 는 이때 guard.detect·rfdetr·VLM 세
  네이티브 엔진이 MPS(Apple GPU)에서 동시에 forward 되며 GIL 없이 파이썬을 건드려 프로세스가
  즉사(SIGTRAP/exit 133)하던 사고다. 해소책은 app_state.DETECT_LOCK(RLock) 으로 세 엔진을
  한 락에 직렬화한 것(커밋 361eb32). 이 스크립트는 **클라이언트가 동시에 보내도 서버가 안 죽는지**
  를 실증하고, 나중에 누가 락을 제거·우회하면 크래시로 회귀를 잡는다.

soak_test.py 와의 차이(중복 아님, 상보):
  - soak_test.py = **인프로세스 워커 누수관측**(RSS/FD/스레드 기울기 + hang/kill 복구). `--url` 은
    /health·/status **수동 프로브만** — 추론 부하를 주지 않아 F-14 를 재현하지 못한다.
  - stress_concurrent.py = **HTTP 동시 추론 부하생성**. 서버 밖에서 진짜 동시요청을 쏴서
    다모델 MPS 동시추론(크래시 트리거)을 유발하고, 서버 생존을 판정한다.
  둘을 함께 돌리면(soak 가 서버를 관측 + stress 가 부하) 24시간 소크의 부하생성 부품이 된다.

크래시 판정(권위 순):
  1) --pid 서버PID 주면: 실행 중 프로세스 사망 감지 = **확정 크래시**(F-14 의 정확한 증상).
  2) PID 없으면: 종료 후 /health 프로브 실패 + 실행 중 연결거부(conn_err) 발생 = 크래시 추정.
  연결거부(ConnectionRefused/Reset)와 타임아웃(느림)은 구분한다 — 타임아웃은 크래시 아님(모델
  로딩·VLM 6~8초). 첫 요청은 모델 lazy-load 로 느리니 --timeout 을 넉넉히.

사용 예:
  # 8클라이언트 5분, 서버PID 주고 확정 크래시 감지(VLM 10% 섞음)
  python3 tools/stress_concurrent.py --url http://127.0.0.1:8010 --duration 5m \
      --concurrency 8 --pid $(pgrep -f 'vigent-core.*main') --vlm-ratio 0.1 --tag f14
  # 토큰 필요한 배포서버
  python3 tools/stress_concurrent.py --url https://host --token $VIGENT_API_TOKEN --duration 1h

종료 시 audit/stress_YYYY-MM-DD[_tag].md(요약+판정) 와 .csv(요청별 원자료)를 생성한다.
종료코드: 무크래시 0 · 크래시 감지 1.
"""
from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False


def _parse_duration(s: str) -> float:
    s = str(s).strip().lower()
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s)


def _args():
    p = argparse.ArgumentParser(description="VIGENT 동시요청 스트레스(F-14 실증)")
    p.add_argument("--url", required=True, help="실행 중 서버(예: http://127.0.0.1:8010)")
    p.add_argument("--duration", default="5m", help="총 부하시간(예: 5m, 1h, 300). 기본 5m")
    p.add_argument("--concurrency", type=int, default=8, help="동시 클라이언트 스레드 수. 기본 8")
    p.add_argument("--token", default="", help="VIGENT_API_TOKEN(외부노출 서버). 없으면 무인증")
    p.add_argument("--pid", type=int, default=0, help="서버 프로세스 PID — 주면 사망을 확정 크래시로 감지")
    p.add_argument("--timeout", type=float, default=120.0,
                   help="요청 타임아웃(초). 첫 VLM/모델로드가 느려 넉넉히. 기본 120")
    p.add_argument("--vlm-ratio", type=float, default=0.1,
                   help="VLM(느린 6~8s) 경로 비율 0~1. 기본 0.1(과다하면 처리량↓). 0=VLM 제외")
    p.add_argument("--endpoints", default="detect,rfdetr,incident_frame,incident_analyze",
                   help="쉼표구분: detect,rfdetr,rfdetr_vlm,incident_frame,incident_analyze,ppe")
    p.add_argument("--img", default="", help="테스트 이미지 경로(없으면 합성 노이즈 생성)")
    p.add_argument("--img-size", default="480x640", help="합성 이미지 HxW. 기본 480x640")
    p.add_argument("--report-dir", default=str(_ROOT / "audit"), help="리포트 출력 디렉토리")
    p.add_argument("--tag", default="", help="리포트 파일명 접미(예: f14)")
    return p.parse_args()


def _make_test_b64(img_path: str, hw: tuple[int, int]) -> str:
    """테스트 이미지 → base64(접두사 없음). 없으면 합성 노이즈(추론경로는 그대로 탄다)."""
    import base64

    import cv2
    import numpy as np
    if img_path and Path(img_path).exists():
        img = cv2.imread(img_path)
    else:
        # 고정 시드 노이즈 — 정확도가 아니라 '추론이 도는지'가 목적(MPS forward 유발).
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (hw[0], hw[1], 3), dtype="uint8")
    ok, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── 엔드포인트 정의: (경로, payload 빌더) — 전부 서버측 DETECT_LOCK 을 거치는 MPS 경로 ──
def _build_endpoints(names: list[str], b64: str, vlm_ratio: float):
    data_url = "data:image/jpeg;base64," + b64
    catalog = {
        # guard.detect (MPS) — 라이브뷰 백엔드
        "detect": ("/detect/frame", {"image_base64": b64, "ppe": True}),
        # rfdetr_service.detect (MPS) — 별도 엔진(웹캠 rf-detr 경로)
        "rfdetr": ("/rfdetr/frame", {"image": data_url}),
        # VLM(mlx-vlm, MPS) — 느림. summarize_bgr 직접
        "rfdetr_vlm": ("/rfdetr/vlm", {"image": data_url}),
        # guard.detect (MPS) — 재해분석 프레임 채점(빠름)
        "incident_frame": ("/safety/incident/frame", {"image_base64": b64}),
        # guard.detect(1280) + (vlm_ratio 확률로) VLM — F-14 의 정확한 충돌쌍
        "incident_analyze": ("/safety/incident/analyze", {"image_base64": b64}),
        # PPE 프레임(guard + 선택 VLM)
        "ppe": ("/ppe/analyze-frame", {"image_base64": b64}),
    }
    chosen = []
    for n in names:
        n = n.strip()
        if n in catalog:
            chosen.append((n, *catalog[n]))
    return chosen, vlm_ratio


def _http_post(url: str, path: str, payload: dict, token: str, timeout: float):
    """(분류, 지연ms, http_status|None). 분류: ok | http_err | conn_err | timeout | other."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + path, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("X-API-Token", token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return "ok", round((time.time() - t0) * 1000, 1), r.status
    except urllib.error.HTTPError as e:
        return "http_err", round((time.time() - t0) * 1000, 1), e.code
    except (socket.timeout, TimeoutError):
        return "timeout", round((time.time() - t0) * 1000, 1), None
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        # 연결거부/리셋 = 서버 사망 신호(F-14). 그 외 URLError 는 other.
        if isinstance(reason, (ConnectionRefusedError, ConnectionResetError)):
            return "conn_err", round((time.time() - t0) * 1000, 1), None
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "timeout", round((time.time() - t0) * 1000, 1), None
        return "conn_err" if reason is None else "other", round((time.time() - t0) * 1000, 1), None
    except (ConnectionResetError, ConnectionRefusedError):
        return "conn_err", round((time.time() - t0) * 1000, 1), None
    except Exception:  # noqa: BLE001
        return "other", round((time.time() - t0) * 1000, 1), None


def _health(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as r:
            r.read()
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _warmup(endpoints, vlm_ratio, url, token, timeout):
    """타이밍 측정 전, 각 엔드포인트를 1회씩 순차 호출해 지연로드 싱글톤을 미리 적재한다.
    rfdetr_service.detect·VLM 은 첫 호출 시에만 모델을 로드하는데(그것도 DETECT_LOCK 안에서),
    이를 측정 구간에 두면 첫 요청이 락을 수십초 붙잡아 나머지가 전부 대기 → 크래시로 오인된다.
    (실운영도 첫 호출 지연이 있음 — 여기서 그 값을 로그로 남긴다.)"""
    print("[stress] 워밍업(지연로드 선적재)…")
    for name, path, base_payload in endpoints:
        payload = dict(base_payload)
        if name in ("incident_analyze", "ppe") and vlm_ratio > 0:
            payload["use_vlm"] = True     # VLM 경로도 미리 로드
        kind, ms, status = _http_post(url, path, payload, token, timeout)
        print(f"[stress]   {name}: {kind} {ms}ms (status={status})")


class _Shared:
    def __init__(self):
        self.rows = []           # 요청별: (t_elapsed, thread, endpoint, kind, ms, status)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.server_died = False
        self.died_at = None      # elapsed 초


def _worker(tid: int, sh: _Shared, endpoints, vlm_ratio, url, token, timeout, t_start):
    i = 0
    n_ep = len(endpoints)
    while not sh.stop.is_set():
        name, path, base_payload = endpoints[(tid + i) % n_ep]   # 스레드마다 위상 어긋나게 라운드로빈
        payload = dict(base_payload)
        # analyze/ppe 는 vlm_ratio 확률로 무거운 VLM 경로를 켠다(느린 6~8s 동시 유발)
        if name in ("incident_analyze", "ppe"):
            # Math.random 불가 → 결정적 의사난수(카운터 기반)로 비율 근사
            payload["use_vlm"] = ((tid * 7 + i * 13) % 100) < int(vlm_ratio * 100)
        kind, ms, status = _http_post(url, path, payload, token, timeout)
        elapsed = round(time.time() - t_start, 2)
        with sh.lock:
            sh.rows.append((elapsed, tid, name, kind, ms, status))
        i += 1


def _pid_monitor(sh: _Shared, pid: int, t_start):
    """서버 PID 생존 감시 — 사망 즉시 stop + died_at 기록(F-14 확정 신호)."""
    proc = None
    if _HAVE_PSUTIL:
        try:
            proc = psutil.Process(pid)
        except Exception:  # noqa: BLE001
            proc = None
    while not sh.stop.is_set():
        alive = True
        try:
            if proc is not None:
                alive = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            else:
                import os
                os.kill(pid, 0)     # 신호0=존재확인
        except Exception:  # noqa: BLE001
            alive = False
        if not alive:
            sh.server_died = True
            sh.died_at = round(time.time() - t_start, 2)
            sh.stop.set()
            print(f"[stress] 🔴 서버 프로세스(PID {pid}) 사망 감지 @ {sh.died_at}s — F-14 크래시 확정")
            return
        time.sleep(0.5)


def main():
    a = _args()
    duration = _parse_duration(a.duration)
    h, w = (int(x) for x in a.img_size.lower().split("x"))
    b64 = _make_test_b64(a.img, (h, w))
    endpoints, vlm_ratio = _build_endpoints(a.endpoints.split(","), b64, a.vlm_ratio)
    if not endpoints:
        print(f"[stress] 유효 엔드포인트 없음: {a.endpoints}")
        return 2

    # 사전점검: 서버 살아있나
    if not _health(a.url):
        print(f"[stress] ❌ 사전 /health 실패 — 서버({a.url})가 안 떠 있음. 먼저 기동하라.")
        return 2
    print(f"[stress] 시작: url={a.url} duration={a.duration}({duration:.0f}s) "
          f"concurrency={a.concurrency} endpoints={[e[0] for e in endpoints]} "
          f"vlm_ratio={vlm_ratio} pid={a.pid or '없음'} psutil={_HAVE_PSUTIL}")

    # 워밍업: 지연로드를 측정 구간 밖으로. (로딩이 락을 붙잡아 '가짜 hang' 되는 것 방지)
    _warmup(endpoints, vlm_ratio, a.url, a.token, a.timeout)
    if not _health(a.url):
        print("[stress] ⚠️ 워밍업 후 /health 실패 — 워밍업 중 크래시? 서버 확인 요망.")

    sh = _Shared()
    t_start = time.time()
    threads = []
    if a.pid:
        mon = threading.Thread(target=_pid_monitor, args=(sh, a.pid, t_start), daemon=True)
        mon.start()
        threads.append(mon)
    for tid in range(a.concurrency):
        th = threading.Thread(target=_worker,
                              args=(tid, sh, endpoints, vlm_ratio, a.url, a.token, a.timeout, t_start),
                              daemon=True)
        th.start()
        threads.append(th)

    # 진행 로그: 5초마다 누적
    last_log = t_start
    try:
        while not sh.stop.is_set():
            now = time.time()
            if now - t_start >= duration:
                break
            if now - last_log >= 5.0:
                with sh.lock:
                    tot = len(sh.rows)
                    ok = sum(1 for r in sh.rows if r[3] == "ok")
                    ce = sum(1 for r in sh.rows if r[3] == "conn_err")
                    to = sum(1 for r in sh.rows if r[3] == "timeout")
                print(f"[stress] t={now - t_start:5.0f}s 요청={tot} ok={ok} conn_err={ce} timeout={to}")
                last_log = now
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("[stress] 중단(Ctrl-C) — 리포트 생성 후 종료")
    sh.stop.set()
    # in-flight 요청 마무리 짧게 대기(워밍업 후 정상요청은 빠름). 길게 붙잡히면 서버 이상 신호.
    drain = min(a.timeout, 20.0)
    for th in threads:
        th.join(timeout=drain)

    # 종료 후 서버 생존 최종 확인
    final_health = _health(a.url)
    return _report(a, duration, sh, endpoints, final_health, t_start)


def _pctile(vals: list[float], q: float):
    if not vals:
        return None
    s = sorted(vals)
    k = int(round((len(s) - 1) * q))
    return s[k]


def _report(a, duration, sh: _Shared, endpoints, final_health: bool, t_start):
    Path(a.report_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    suffix = f"_{a.tag}" if a.tag else ""
    base = Path(a.report_dir) / f"stress_{stamp}{suffix}"
    md_path = base.with_suffix(".md")
    csv_path = base.with_suffix(".csv")

    rows = sh.rows
    total = len(rows)
    kinds = {}
    for r in rows:
        kinds[r[3]] = kinds.get(r[3], 0) + 1
    conn_err = kinds.get("conn_err", 0)
    ok = kinds.get("ok", 0)

    # 엔드포인트별 집계
    per_ep = {}
    for name, _p, _pl in endpoints:
        per_ep[name] = {"n": 0, "ok": 0, "err": 0, "lat": []}
    for r in rows:
        _t, _tid, name, kind, ms, _st = r
        d = per_ep.get(name)
        if d is None:
            continue
        d["n"] += 1
        if kind == "ok":
            d["ok"] += 1
            d["lat"].append(ms)
        else:
            d["err"] += 1

    # ── 크래시 판정 ──
    if sh.server_died:
        verdict = "❌ 크래시 감지(프로세스 사망)"
        crashed = True
    elif conn_err > 0 and not final_health:
        verdict = "❌ 크래시 추정(연결거부 + 종료후 /health 실패)"
        crashed = True
    elif not final_health:
        verdict = "⚠️ 불확실(종료후 /health 실패, 연결거부는 없음 — 서버 확인 요망)"
        crashed = True
    else:
        verdict = "✅ 무크래시(부하 중 서버 생존 · 종료후 /health 200)"
        crashed = False

    dur_actual = round((rows[-1][0] if rows else 0.0), 1)
    thru = round(total / dur_actual, 1) if dur_actual > 0 else 0.0

    L = []
    L.append(f"# VIGENT 동시요청 스트레스 리포트 — {stamp}{(' / ' + a.tag) if a.tag else ''}")
    L.append("")
    L.append(f"> F-14(동시부하 네이티브 크래시) 실증. 동시 {a.concurrency} 클라이언트 · "
             f"{a.duration}({duration:.0f}s) · 엔드포인트 {[e[0] for e in endpoints]} · "
             f"vlm_ratio={a.vlm_ratio} · pid감시={'ON' if a.pid else 'OFF'} · psutil={_HAVE_PSUTIL}")
    L.append("")
    L.append(f"## 판정: {verdict}")
    L.append("")
    L.append("**한 줄 요약**: "
             f"총 {total}요청 · ok {ok} · **conn_err {conn_err}** · timeout {kinds.get('timeout', 0)} · "
             f"http_err {kinds.get('http_err', 0)} · 처리량 {thru} req/s · "
             f"서버사망 {'예 @' + str(sh.died_at) + 's' if sh.server_died else '아니오'} · "
             f"종료후 /health {'200' if final_health else '실패'}")
    L.append("")
    L.append("## 요청 분류")
    L.append("| 분류 | 수 | 의미 |")
    L.append("|---|---|---|")
    meaning = {"ok": "2xx 정상", "http_err": "4xx/5xx(앱 오류 — 크래시 아님)",
               "timeout": "타임아웃(느림 — 모델로드/VLM, 크래시 아님)",
               "conn_err": "**연결거부/리셋(서버 사망 신호)**", "other": "기타 네트워크"}
    for k in ("ok", "conn_err", "timeout", "http_err", "other"):
        if kinds.get(k):
            L.append(f"| {k} | {kinds[k]} | {meaning.get(k, '')} |")
    L.append("")
    L.append("## 엔드포인트별 (전부 서버측 DETECT_LOCK 직렬화)")
    L.append("| 엔드포인트 | 요청 | ok | 오류 | 지연 p50 | p95 | max (ms) |")
    L.append("|---|---|---|---|---|---|---|")
    for name, d in per_ep.items():
        p50 = _pctile(d["lat"], 0.5)
        p95 = _pctile(d["lat"], 0.95)
        mx = max(d["lat"]) if d["lat"] else None
        L.append(f"| {name} | {d['n']} | {d['ok']} | {d['err']} | "
                 f"{p50} | {p95} | {mx} |")
    L.append("")
    L.append("## 판정 근거")
    L.append(f"- 서버 프로세스 사망(PID 감시): {'예 @ ' + str(sh.died_at) + 's → F-14 확정' if sh.server_died else ('아니오' if a.pid else 'PID 미지정(감시 안 함)')}")
    L.append(f"- 실행 중 연결거부(conn_err): {conn_err}건 {'→ 서버 사망 의심' if conn_err else '→ 없음'}")
    L.append(f"- 종료 후 /health: {'200(생존)' if final_health else '실패'}")
    L.append(f"- 해석: DETECT_LOCK(RLock)이 guard·rfdetr·VLM 3개 MPS 엔진을 직렬화하므로 "
             f"동시요청이 와도 네이티브 동시 forward 가 발생하지 않아야 한다. "
             f"{'크래시가 났다면 락 회귀(제거·우회)를 의심하라.' if crashed else '무크래시 = 락이 의도대로 동작.'}")
    L.append("")
    L.append("## 비고")
    L.append("- 합성 노이즈 이미지로 추론경로(MPS forward)만 유발 — 검출 정확도는 이 시험의 관심사가 아니다.")
    L.append("- 타임아웃은 크래시가 아니다(첫 모델로드·VLM 6~8s). conn_err/프로세스 사망만이 F-14 신호.")
    L.append("- 소크(24h) 부품: soak_test.py(누수관측)와 함께 돌리면 부하생성 계층이 된다.")
    L.append(f"- 원자료(요청별): `{csv_path.name}`")

    md_path.write_text("\n".join(L), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        wtr = csv.writer(f)
        wtr.writerow(["t_elapsed", "thread", "endpoint", "kind", "latency_ms", "http_status"])
        wtr.writerows(rows)

    print("")
    print(f"[stress] 판정: {verdict}")
    print(f"[stress] 총 {total}요청 ok={ok} conn_err={conn_err} 처리량={thru}req/s")
    print(f"[stress] 리포트: {md_path}")
    print(f"[stress] 원자료: {csv_path}")
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
