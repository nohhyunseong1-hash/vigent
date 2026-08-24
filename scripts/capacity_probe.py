#!/usr/bin/env python3
"""[C5] 카메라 대수 수용량 실측 — N 을 늘려가며 한계 N·권장 N 을 확정한다.

배경(감사 🟠C5): `docs/INFRA_REQUIREMENTS.md` §1.2 가 스스로 "카메라당 FPS·동시 카메라 수를
측정하지 않았다"고 적고 있다. **견적을 낼 수 없는 상태**였다.

방식:
  - 모의 카메라 = `runs/rfdetr/accident/*.mp4`(실제 현장 장면) 을 **파일 소스로 등록**.
    워커가 EOF 에서 자동 재오픈하므로 사실상 루프 재생이 되고, 실카메라와 **같은 파이프라인**
    (디코드→검출→추적→경보 판정)을 탄다.
    ★정적 이미지 반복은 쓰지 않는다 — 검출 부하가 실장면보다 가벼워 결과가 후하게 나온다.
  - N=1 부터 한 대씩 늘리며 각 단계에서 `hold` 초 유지 후 지표를 기록하고 자동 판정.
  - 불합격이 나오면 즉시 중단하고 **직전 N 을 한계**로 본다.

★시험이 끝나면 등록한 모의 카메라를 **전부 제거**하고 원상복구를 확인한다(--cleanup-only 로도 가능).

사용:
    python scripts/capacity_probe.py --max-n 8 --hold 300
    python scripts/capacity_probe.py --cleanup-only      # 중단됐을 때 정리만
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"
PREFIX = "cap"          # 모의 카메라 id 접두 — 정리 시 이 접두만 지운다
SCENE_DIR = _ROOT / "runs" / "rfdetr" / "accident"

# ── 합격 기준 (★측정 전에 선언 — 사후 조정 금지) ────────────────────────────
#   base_cycle_s: 1대 기준 실효 검출 주기(실측으로 채운다)
#   detect p95 가 기준 주기의 2배 초과 / GPU 메모리 90% 초과 / 프레임 드랍 지속 /
#   status=degraded 지속 중 하나라도 걸리면 그 N 은 불합격 → 직전 N 이 한계.
# 기준 주기가 이 값을 넘으면 측정 자체가 오염된 것으로 보고 중단한다(정지 카메라 stale age 방어).
BASE_CYCLE_SANE_MAX_S = 30.0

PASS_CRITERIA = {
    "detect_p95_max_ratio": 2.0,
    "gpu_mem_max_pct": 90.0,
    "dropped_frames_growth": "지속 증가 시 불합격",
    "degraded_not_allowed": True,
    "recommend_ratio": 0.75,     # 권장 N = 한계 N × 0.75 (야간·재연결 폭주 여유)
}


def _token() -> str:
    env = _ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("VIGENT_API_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


TOK = _token()


def api(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Authorization": "Bearer " + TOK,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as ex:  # noqa: BLE001
        return 0, {"error": str(ex)}


def gpu() -> tuple[int | None, int | None, int | None]:
    """(used_mb, total_mb, util_pct)"""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"], stderr=subprocess.DEVNULL).decode().strip()
        u, t, p = (int(x.strip()) for x in out.splitlines()[0].split(","))
        return u, t, p
    except Exception:  # noqa: BLE001
        return None, None, None


def scenes() -> list[Path]:
    return sorted(SCENE_DIR.glob("*.mp4"))


def add_camera(i: int, vids: list[Path]) -> bool:
    """모의 카메라 등록 + **워커 기동까지 확인**.

    ★`enabled: true` 를 반드시 보내야 한다 — 빠뜨리면 등록만 되고 워커가 뜨지 않아
    (`/cameras` enabled=false) **부하가 전혀 걸리지 않은 채 측정이 통과해버린다**.
    2026-08-18 1차 측정이 이 실수로 무효가 됐다(9대까지 전부 PASS 였으나 실제로는 0대 부하).
    """
    cid = f"{PREFIX}{i}"
    src = str(vids[(i - 1) % len(vids)])
    code, _ = api("/cameras", "POST",
                  {"id": cid, "name": f"모의{i}", "source": src, "fps": 2, "enabled": True})
    if not (200 <= code < 300):
        return False
    # 워커가 실제로 /health 에 나타나는지 확인(최대 30초 대기)
    for _ in range(30):
        time.sleep(1)
        _c, h = api("/health")
        if cid in (h.get("cameras") or {}):
            return True
    print(f"   ★경고: {cid} 워커가 30초 안에 뜨지 않았다 — 부하가 안 걸린다")
    return False


def cleanup() -> int:
    """모의 카메라 전부 제거. 반환: 제거한 개수."""
    code, d = api("/cameras")
    n = 0
    for c in (d.get("cameras") or []):
        cid = str(c.get("id") or "")
        if cid.startswith(PREFIX):
            api(f"/cameras/{cid}", "DELETE")
            n += 1
    return n


def sample(n_expected: int) -> dict[str, Any]:
    code, h = api("/health")
    cams = h.get("cameras") or {}
    # ★[2026-08-21] 집계는 **가동 중인 카메라만**. 삭제된 카메라가 `stopped` 로 남아
    #   stale 한 age(수만 초)를 보고하는데, 그게 섞이면 통계가 통째로 오염된다.
    live = {k: c for k, c in cams.items() if c.get("status") != "stopped"}
    lat = [c.get("last_detect_latency_ms") for c in live.values()
           if c.get("last_detect_latency_ms")]
    age = [c.get("last_detect_age_s") for c in live.values()
           if c.get("last_detect_age_s") is not None]
    # ★실카메라(test) 지표를 따로 뽑는다 — 전 카메라 평균만 보면 모의 카메라가 많아질수록
    #   실카메라의 저하가 희석돼 한계를 놓친다(1차 측정의 두 번째 결함).
    real = cams.get("test") or {}
    drop = sum(c.get("dropped_frames") or 0 for c in live.values())
    # [2026-08-21] degraded 를 **사유별로** 가른다.
    #   /health 의 degraded 는 ①카메라 검출 저하 ②미전송 경보 적체 둘 다에서 난다
    #   (md/DEPLOYMENT.md §8). 후자는 통보채널·인터넷 문제라 **카메라 용량과 무관**한데
    #   뭉뚱그려 불합격 처리하면 멀쩡한 N 이 탈락한다(1차 측정 실제 사고: N=2 가 경보 적체
    #   degraded 2샘플만으로 탈락 → "한계 1대"라는 거짓 결과).
    cam_bad = [k for k, c in cams.items() if c.get("status") not in ("ok", "stopped", None)]
    alerts = h.get("alerts") or {}
    alert_backlog = int(alerts.get("pending") or 0)
    gu, gt, gp = gpu()
    return {"ts": time.strftime("%H:%M:%S"), "code": code, "status": h.get("status"),
            "cams": len(cams), "expected": n_expected,
            "lat": lat, "age": age, "dropped": drop,
            "real_lat": real.get("last_detect_latency_ms"),
            "real_age": real.get("last_detect_age_s"),
            "real_status": real.get("status"),
            "gpu_used": gu, "gpu_total": gt, "gpu_util": gp,
            "cam_bad": cam_bad, "alert_backlog": alert_backlog}


def _p(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * q))]


def summarize(samples: list[dict], base_cycle_s: float | None) -> dict[str, Any]:
    lat = [x for s in samples for x in s["lat"]]
    age = [x for s in samples for x in s["age"]]
    gmem = [s["gpu_used"] for s in samples if s["gpu_used"]]
    gtot = next((s["gpu_total"] for s in samples if s["gpu_total"]), None)
    gutil = [s["gpu_util"] for s in samples if s["gpu_util"] is not None]
    drops = [s["dropped"] for s in samples]
    degraded = sum(1 for s in samples if s["status"] not in ("healthy", None))
    return {
        "samples": len(samples),
        "lat_p50": _p(lat, 0.50), "lat_p95": _p(lat, 0.95), "lat_max": max(lat) if lat else None,
        "age_p50": _p(age, 0.50), "age_p95": _p(age, 0.95), "age_max": max(age) if age else None,
        "gpu_mem_max": max(gmem) if gmem else None, "gpu_total": gtot,
        "gpu_mem_pct": round(max(gmem) / gtot * 100, 1) if (gmem and gtot) else None,
        "gpu_util_p95": _p([float(x) for x in gutil], 0.95),
        "drop_growth": (drops[-1] - drops[0]) if drops else 0,
        "degraded_samples": degraded,
        # ★degraded 를 사유별로 나눠 둔다 — 판정은 카메라 쪽만 쓴다.
        "degraded_camera_samples": sum(1 for s in samples if s.get("cam_bad")),
        "degraded_alert_samples": sum(1 for s in samples
                                      if s["status"] not in ("healthy", None)
                                      and not s.get("cam_bad")),
        "alert_backlog_max": max((s.get("alert_backlog") or 0) for s in samples) if samples else 0,
        "cam_bad_names": sorted({k for s in samples for k in (s.get("cam_bad") or [])}),
        # 실카메라 단독 지표(희석 없음) — 판정은 이 값으로 한다
        "real_lat_p95": _p([s["real_lat"] for s in samples if s.get("real_lat")], 0.95),
        "real_age_p95": _p([s["real_age"] for s in samples if s.get("real_age") is not None], 0.95),
        "real_bad_samples": sum(1 for s in samples if s.get("real_status") not in ("ok", None)),
    }


def judge(m: dict[str, Any], base_cycle_s: float) -> tuple[bool, list[str]]:
    """합격 판정. 하나라도 걸리면 불합격."""
    bad: list[str] = []
    limit = base_cycle_s * 1000 * PASS_CRITERIA["detect_p95_max_ratio"]
    # ★판정은 **실카메라 단독 지표**로 한다(전 카메라 평균은 모의 카메라가 희석한다)
    rl = m.get("real_lat_p95")
    if rl is not None and rl > limit:
        bad.append(f"실카메라 detect p95 {rl:.0f}ms > 기준주기×2({limit:.0f}ms)")
    ra = m.get("real_age_p95")
    if ra is not None and ra > base_cycle_s * PASS_CRITERIA["detect_p95_max_ratio"]:
        bad.append(f"실카메라 검출주기 p95 {ra:.2f}s > 기준×2({base_cycle_s*2:.2f}s)")
    if m.get("real_bad_samples"):
        bad.append(f"실카메라 상태 이상 {m['real_bad_samples']}샘플")
    if m["gpu_mem_pct"] is not None and m["gpu_mem_pct"] > PASS_CRITERIA["gpu_mem_max_pct"]:
        bad.append(f"GPU 메모리 {m['gpu_mem_pct']:.1f}% > 90%")
    if m["drop_growth"] > 0:
        bad.append(f"프레임 드랍 증가 {m['drop_growth']}건")
    # ★degraded 는 **카메라 사유일 때만** 불합격. 경보 적체(pending)로 인한 degraded 는
    #   인터넷·통보채널 문제라 카메라 수용량과 무관하다 — 기록만 하고 판정에서 뺀다.
    if m.get("degraded_camera_samples", 0) > 0:
        bad.append(f"카메라 저하 degraded {m['degraded_camera_samples']}샘플 "
                   f"({', '.join(m.get('cam_bad_names') or []) or '이름 미상'})")
    return (not bad), bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-n", type=int, default=8, help="모의 카메라 최대 대수")
    ap.add_argument("--hold", type=float, default=300.0, help="단계별 유지 시간(초)")
    ap.add_argument("--interval", type=float, default=10.0, help="샘플 간격(초)")
    ap.add_argument("--cleanup-only", action="store_true")
    ap.add_argument("--out", default="benchmarks/capacity_probe_result.json")
    a = ap.parse_args()

    if a.cleanup_only:
        print(f"모의 카메라 제거: {cleanup()}대")
        return 0

    vids = scenes()
    if not vids:
        print(f"모의 소스 영상이 없습니다: {SCENE_DIR}")
        return 2
    print(f"모의 소스 {len(vids)}편(실장면 루프 재생) · 단계별 {a.hold:.0f}초 유지\n")

    # ── 1대 기준값(실카메라만) ────────────────────────────────────────────
    print("[기준] 실카메라 1대만 측정 중...")
    base_s = [sample(1) for _ in range(int(min(60, a.hold) / a.interval))
              if not time.sleep(a.interval)]
    base = summarize(base_s, None)
    # ★[2026-08-21] 기준 주기는 **기준 카메라(test) 단독 age** 로 잡는다.
    #   예전에는 전 카메라 age_p95 를 썼는데, /health 에 남은 **정지 카메라 한 대**의
    #   stale age(수만 초)가 섞이면 기준이 통째로 파괴된다. 그러면
    #   limit = base_cycle_s x 1000 x 2 가 수천만 ms 가 되어 **지연 판정이 무력화**된다
    #   (1차 측정 실제 사고: base_cycle_s=40544s -> 어떤 지연도 통과, "한계 1대" 거짓 결과).
    base_cycle_s = base.get("real_age_p95")
    if not base_cycle_s or base_cycle_s <= 0 or base_cycle_s > BASE_CYCLE_SANE_MAX_S:
        print(f"\n★중단: 기준 주기가 비정상입니다 — real_age_p95={base_cycle_s}"
              f" (정상 범위 0<x<={BASE_CYCLE_SANE_MAX_S}s)")
        print("  원인 후보: ①기준 카메라('test')가 등록되지 않았다"
              " ②/health 에 정지 카메라가 남아 지표가 오염됐다(서비스 재시작으로 정리)")
        print("  이 상태의 측정은 무효이므로 진행하지 않습니다.")
        return 2
    print(f"  1대 기준: detect p50 {base['lat_p50']:.0f}ms / p95 {base['lat_p95']:.0f}ms · "
          f"검출주기(기준카메라 age p95) {base_cycle_s:.2f}s · GPU {base['gpu_mem_pct']:.1f}%\n")

    results: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pass_criteria": PASS_CRITERIA,
        "base_cycle_s": base_cycle_s,
        "baseline": base, "steps": {},
    }
    limit_n: int | None = None
    try:
        for n in range(1, a.max_n + 1):
            if not add_camera(n, vids):
                print(f"  N={n}: 카메라 등록 실패 — 중단")
                break
            total = n + 1                       # 실카메라 1대 + 모의 n대
            print(f"[N={total}] 모의 {n}대 추가 → {a.hold:.0f}초 유지...")
            time.sleep(min(30, a.hold * 0.1))   # 예열
            ss = []
            t0 = time.time()
            while time.time() - t0 < a.hold:
                ss.append(sample(total))
                time.sleep(a.interval)
            m = summarize(ss, base_cycle_s)
            ok, bad = judge(m, base_cycle_s)
            results["steps"][str(total)] = {"metrics": m, "pass": ok, "violations": bad}
            print(f"   detect p50 {m['lat_p50']:.0f}ms p95 {m['lat_p95']:.0f}ms "
                  f"최대 {m['lat_max']:.0f}ms · 검출주기 p95 {m['age_p95']:.2f}s · "
                  f"GPU {m['gpu_mem_pct']:.1f}% util p95 {m['gpu_util_p95']:.0f}% · "
                  f"{'PASS' if ok else 'FAIL'}")
            if not ok:
                print(f"   불합격 사유: {'; '.join(bad)}")
                limit_n = total - 1
                break
    finally:
        removed = cleanup()
        print(f"\n[정리] 모의 카메라 {removed}대 제거")

    if limit_n is None:
        limit_n = 1 + min(a.max_n, len(results["steps"]))
        results["note"] = "max-n 까지 전부 통과 — 한계는 이 값 이상일 수 있다(추가 측정 필요)"
    results["limit_n"] = limit_n
    results["recommend_n"] = max(1, int(limit_n * PASS_CRITERIA["recommend_ratio"]))
    print(f"\n한계 N = {results['limit_n']}대 · 권장 N = {results['recommend_n']}대"
          f"(한계의 {PASS_CRITERIA['recommend_ratio']:.0%})")

    outp = _ROOT / a.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"결과: {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
