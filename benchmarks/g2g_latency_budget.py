#!/usr/bin/env python3
"""benchmarks/g2g_latency_budget.py — Part A: 글라스-투-글라스 지연 예산 분해(데스크탑, 계산값).

**정직 고지(스크립트 최상단에 먼저)**: 이건 "계산된 지연"이지 "눈으로 본 지연"이 아니다. 카메라
노출·인코딩, (실카메라라면) WebRTC/USB 전송, 모니터 응답속도는 이 파일 기반 측정에 전혀 안 잡힌다.
실제 눈-화면 지연은 Part B(safety-local ?dbg=1 HUD의 "박스 나이(ms)" + 맥 실측 절차, docs/
glass_to_glass_measurement.md)로 재야 한다.

구성요소:
  ① 검출: 서버가 이미지를 받아 guard.detect(person) 끝낼 때까지(디코드+추론, in-process 직접 타이밍 —
     네트워크 제외). 실측.
  ② 검출주기: 연속 검출 갱신 간격. index_local.html:753 의 적응형 최소주기
     `VIGENT_DETECT_MIN_DYN=max(100, RTT_p50×1.2)` — 이 RTT 수준에선 항상 100ms 바닥(코드 확인).
     평균 대기 기여분은 주기/2(폴링 시점이 실제 물체 위치와 비동기라는 표준 가정).
  ③ 폴링/전송: FastAPI TestClient 로 잰 전체 왕복(라우팅+직렬화+디코드+추론 전부 포함, 실제 OS 네트워크
     스택은 미포함 — 로컬호스트 프로세스 내부) 에서 ①(디코드+추론)을 뺀 나머지.
  ④ 보간지연: BoxTracker(현재 배포값 extrapCap=0.85)가 표시하는 위치와 실측 위치의 오차(px)를, 그
     샘플 시점의 실제 이동속도(px/s)로 나눠 ms로 환산 — "속도로 나눠 지연 환산"(사용자 지시 방법1과
     동일 원리를 시뮬레이션 데이터에 적용). box_quality.py 의 GT 보간·표시재생을 그대로 재사용
     (재구현 아님). 네트워크 지연은 0으로 두고(시나리오 'ideal') 순수 보간 기여만 분리 — ①·③과
     이중계산 방지.

실행: python3 benchmarks/g2g_latency_budget.py
"""
from __future__ import annotations

import base64
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "vigent-core"))

import box_quality as bq  # noqa: E402
import env_guard  # noqa: E402
import web_util  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

N_SAMPLES = 30
CADENCE_MS = 100.0   # ②: 적응형 최소주기 코드값(VIGENT_DETECT_MIN_DYN 바닥)
EXTRAP_CAP = 0.85     # 현재 배포값(2026-08, local_slowdown_ab.md 근거)


def _percentile(xs: list[float], p: float) -> float:
    xs2 = sorted(xs)
    n = len(xs2)
    return xs2[min(n - 1, int(n * p))]


def _build_payload_b64() -> str:
    import cv2
    cap = cv2.VideoCapture(str(_ROOT / "runs" / "rfdetr" / "multi_scene.mp4"))
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("multi_scene.mp4 프레임 읽기 실패")
    h, w = img.shape[:2]
    scale = min(1.0, 640.0 / w)
    cw, ch = round(w * scale), round(h * scale)
    small = cv2.resize(img, (cw, ch))
    ok, buf = cv2.imencode(".jpg", small, [int(cv2 .IMWRITE_JPEG_QUALITY), 72])
    return base64.b64encode(buf.tobytes()).decode()


def measure_detect(b64: str) -> dict[str, Any]:
    """① 검출: 서버 도착(디코드) → guard.detect 완료. in-process, 네트워크 제외."""
    raw = "data:image/jpeg;base64," + b64
    guard = bq._build_guard()
    img0 = web_util.decode_data_url(raw)
    guard.detect(img0, detectors=["person"], imgsz=640, track_key="g2g_bench")   # warmup

    decode_ms, detect_ms = [], []
    for _ in range(N_SAMPLES):
        t0 = time.perf_counter()
        img = web_util.decode_data_url(raw)
        t1 = time.perf_counter()
        guard.detect(img, detectors=["person"], imgsz=640, track_key="g2g_bench")
        t2 = time.perf_counter()
        decode_ms.append((t1 - t0) * 1000)
        detect_ms.append((t2 - t1) * 1000)
    return {
        "decode_p50": round(statistics.median(decode_ms), 2),
        "detect_p50": round(statistics.median(detect_ms), 2),
        "detect_p90": round(_percentile(detect_ms, 0.9), 2),
        "total_p50": round(statistics.median(decode_ms) + statistics.median(detect_ms), 2),
    }


def measure_roundtrip(b64: str) -> dict[str, Any]:
    """③ 산출용: FastAPI TestClient 전체 왕복(라우팅+직렬화+디코드+추론) — 실 네트워크 스택은 제외."""
    import main
    from fastapi.testclient import TestClient

    with TestClient(main.app) as client:
        payload = {"image_base64": b64, "ppe": False, "safety_only": True,
                   "seg": False, "pose": True, "press": False}
        client.post("/detect/frame", json=payload)   # warmup
        rtts = []
        for _ in range(N_SAMPLES):
            t0 = time.perf_counter()
            r = client.post("/detect/frame", json=payload)
            rtts.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
    return {"rtt_p50": round(statistics.median(rtts), 2), "rtt_p90": round(_percentile(rtts, 0.9), 2)}


def measure_interp_lag_ms() -> dict[str, Any]:
    """④ 보간지연: 실측 person 트랙(multi_scene) → 현재 배포 extrapCap=0.85, 캐던스 100ms, 지연 0
    ('ideal' 시나리오 — 네트워크 지연 미포함, ①·③과 이중계산 방지) 표시 후, 샘플별 표시오차(px)를
    그 샘플의 실제속도(px/s)로 나눠 ms 환산."""
    frames, _fps = bq.load_detections_cache(_HERE / "_sweep_cache" / "multi_scene.json")
    ingest_frames = bq.subsample_for_ingest(frames, CADENCE_MS)
    sc = next(s for s in bq.SCENARIOS if s["name"] == "ideal")
    vis = bq.run_display_scenario(ingest_frames, sc, "node", None, 12345, {"extrapCap": EXTRAP_CAP})

    traj = bq._traj_by_tid(frames)
    lags_ms: list[float] = []
    for tick in vis:
        t = tick["t_ms"]
        for v in tick["vis"]:
            gt_box, speed = bq._interp(traj.get(v["tid"], []), t)
            if gt_box is None or not speed or speed < 5.0:   # 사실상 정지(속도<5px/s)는 ms환산이 불안정(0나눗셈 근접) → 제외
                continue
            gc = bq._center(gt_box)
            vc = bq._center(v["box"])
            err_px = ((gc[0] - vc[0]) ** 2 + (gc[1] - vc[1]) ** 2) ** 0.5
            lags_ms.append(err_px / speed * 1000.0)

    return {
        "n": len(lags_ms),
        "p50": round(statistics.median(lags_ms), 1) if lags_ms else None,
        "p90": round(_percentile(lags_ms, 0.9), 1) if lags_ms else None,
    }


def main() -> None:
    env_guard.warn_if_docker_running("g2g_latency_budget")
    b64 = _build_payload_b64()

    print("① 검출(디코드+guard.detect, in-process) 측정 중...")
    det = measure_detect(b64)
    print("③ 산출용 전체 왕복(TestClient) 측정 중...")
    rtt = measure_roundtrip(b64)
    print("④ 보간지연(px오차/속도 환산) 측정 중...")
    lag = measure_interp_lag_ms()

    c1 = det["total_p50"]              # ① 검출(디코드+추론)
    c2_half = CADENCE_MS / 2           # ② 검출주기의 절반(평균 대기 기여분)
    c3 = max(0.0, round(rtt["rtt_p50"] - c1, 2))   # ③ = 전체왕복 - ①
    c4 = lag["p50"] or 0.0             # ④ 보간지연(px오차/속도 환산 p50)
    total = c1 + c2_half + c3 + c4

    lines = [
        "# Part A — 글라스-투-글라스 지연 예산 분해 (데스크탑, 계산값 — 정직 고지: 눈으로 본 지연 아님)",
        "",
        "**이건 '계산된 지연'이지 '눈으로 본 지연'이 아니다.** 카메라 노출·인코딩·(실카메라의) WebRTC/USB "
        "전송·모니터 응답속도는 이 측정에 전혀 안 잡힌다 — Part B(HUD 실측)와 반드시 대조할 것.",
        "",
        "## 구성요소별 실측/계산값",
        "| 구성요소 | 값(ms, p50) | 방법 |",
        "|---|---|---|",
        f"| ① 검출(디코드+guard.detect) | **{c1:.1f}** | in-process 직접 타이밍(네트워크 제외), "
        f"디코드 {det['decode_p50']}ms + 추론 {det['detect_p50']}ms(p90 {det['detect_p90']}ms) |",
        f"| ② 검출주기 ÷ 2 | **{c2_half:.1f}** | 코드값 100ms(VIGENT_DETECT_MIN_DYN 바닥, "
        "index_local.html:753) ÷ 2(평균 대기 가정) |",
        f"| ③ 폴링/전송(네트워크·직렬화) | **{c3:.1f}** | TestClient 전체왕복 {rtt['rtt_p50']}ms(p90 "
        f"{rtt['rtt_p90']}ms) − ①{c1:.1f}ms — **로컬호스트 프로세스 내부값, 실 OS 네트워크 스택 제외** |",
        f"| ④ 보간지연(BoxTracker, extrapCap={EXTRAP_CAP}) | **{c4:.1f}** | 실측 person 표시오차(px) ÷ "
        f"그 시점 실제속도(px/s), n={lag['n']}, p90={lag['p90']}ms — 지연 시나리오 'ideal'(순수 보간만, "
        "①③과 이중계산 방지) |",
        "",
        f"## 이론적 총 지연 = ①+②/2+③+④ = **{total:.1f}ms**",
        "",
        "| 구성요소 | ms | 비중 |",
        "|---|---|---|",
        f"| ① 검출 | {c1:.1f} | {c1/total*100:.0f}% |",
        f"| ②/2 검출주기 | {c2_half:.1f} | {c2_half/total*100:.0f}% |",
        f"| ③ 폴링/전송 | {c3:.1f} | {c3/total*100:.0f}% |",
        f"| ④ 보간지연 | {c4:.1f} | {c4/total*100:.0f}% |",
        "",
        "## 정직 고지",
        "- **①이 압도적 비중** — 이 환경(desktop, RF-DETR-nano)의 person 추론 자체가 지배적 지연원. "
        "맥 하드웨어(추론 백엔드·가속기 차이)에서는 이 값이 다를 수 있다(모른다, 맥 실측 필요).",
        "- **③은 로컬호스트값**이라 사실상 0에 가깝다(FastAPI 직렬화만) — 실제 배포(다른 기기·네트워크)의 "
        "네트워크 왕복은 이보다 훨씬 클 수 있다. Part B 실측과 대조해서 차이를 메울 것.",
        "- **④는 '정지에 가까운' 샘플(<5px/s)을 제외**했다(속도로 나누는 환산식이 저속에서 발산해 왜곡되므로) "
        "— 그런 프레임은 애초에 지연이 안 보이므로(안 움직이면 늦게 그려도 안 늦어 보임) 제외가 타당하다.",
        "- 이 표의 '① 검출'은 person 단일 클래스 기준(이 환경에 PPE 가중치 없음) — 실배포에서 ppe=true로 "
        "PPE·화재까지 함께 추론하면 ①이 더 커질 수 있다(미검증).",
    ]
    out = _HERE / "g2g_latency_budget.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print()
    print("\n".join(lines))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
