#!/usr/bin/env python3
"""benchmarks/mac_rtt_contention_probe.py — Phase 1: /detect/frame RTT 157ms 원인 분해(맥에서 직접 실행).

이 스크립트는 **맥의 실제 실행 중인 vigent-core 서버**를 상대로 돈다(이 세션은 맥에 직접 접속할 수
없어, 사용자가 맥 터미널에서 직접 실행 — 사용자 확인 사항). 측정만 한다 — 검출·판정·표시 코드는
일절 수정하지 않는다.

측정 원리: "워커(카메라) 끄기 전/후 RTT 차이" = DETECT_LOCK 경합(락 큐잉) 기여분. 워커가 없으면
RTT ≈ ①검출(디코드+추론)+③네트워크/직렬화만 남고, 워커가 GPU를 동시에 쓰면 그 대기가 RTT에 더해진다
— 그래서 "끄기 전 vs 끄기 후"만 비교하면 경합 기여분이 그대로 드러난다(각 항목을 따로 안 재도 됨).

**안전장치(필수, 이 스크립트가 자동 보장)**:
  1. 시작 전 카메라 상태를 전부 스냅샷(GET /cameras) — 손대는 건 '이미 enabled 인' 카메라뿐.
  2. 각 카메라를 끌 때마다 즉시 다시 켜고, online 복구를 폴링(최대 --restore-timeout 초)해서 확인한다.
     실패하면 화면에 큰 경고를 찍고 **exit code 1로 종료**(조용히 넘어가지 않음).
  3. 스크립트 끝에 "복구 확인" 표를 반드시 출력한다 — 이걸 그대로 캡처해서 보고하면 된다.
  4. --dry-run 이면 카메라를 전혀 안 건드리고 스냅샷·RTT(AS-IS)·이미지 인코딩만 잰다(경합 비교 없음).

사용(맥 터미널, vigent-core 서버가 이미 떠 있는 상태에서):
  python3 benchmarks/mac_rtt_contention_probe.py --base-url http://127.0.0.1:8000
  (VIGENT_API_TOKEN 설정된 배포면 --token <토큰> 추가, 또는 환경변수 VIGENT_API_TOKEN 그대로 사용됨)
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from typing import Any

try:   # 콘솔 인코딩이 UTF-8이 아닌 환경(일부 Windows) 대비 — 로직 무관
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _args() -> argparse.Namespace:
    import os
    p = argparse.ArgumentParser(description="맥 /detect/frame RTT 경합 원인분해(측정 전용)")
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="실행 중인 vigent-core 서버 주소")
    p.add_argument("--token", default=os.environ.get("VIGENT_API_TOKEN", ""), help="VIGENT_API_TOKEN(설정된 배포만 필요)")
    p.add_argument("--n", type=int, default=25, help="조건별 RTT 샘플 수")
    p.add_argument("--restore-timeout", type=float, default=20.0, help="워커 재기동 후 online 복구 대기 상한(초)")
    p.add_argument("--dry-run", action="store_true", help="카메라를 건드리지 않고 AS-IS RTT·이미지 인코딩만 측정")
    return p.parse_args()


def _headers(token: str) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _req(base_url: str, method: str, path: str, token: str, payload: dict | None = None, timeout: float = 15.0) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base_url + path, data=data, headers=_headers(token), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        return json.loads(body) if body else None


def _build_test_image_b64() -> str:
    """실제 카메라 영상 없이도 실행 가능하게 640x480 합성 JPEG 생성(cv2 는 이 프로젝트 필수 의존성이라
    항상 존재 — guard.detect() 도 이걸 씀). 내용은 무관(락 경합은 이미지 내용과 무관하게 재는 것)."""
    import cv2
    import numpy as np
    rng = np.random.default_rng(12345)
    img = rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
    if not ok:
        raise SystemExit("[mac_rtt_contention_probe] 테스트 이미지 인코딩 실패")
    import base64
    return base64.b64encode(buf.tobytes()).decode(), len(buf)


def _percentile(xs: list[float], p: float) -> float:
    xs2 = sorted(xs)
    n = len(xs2)
    return xs2[min(n - 1, int(n * p))]


def _measure_rtt(base_url: str, token: str, b64: str, n: int, label: str) -> dict[str, Any]:
    payload = {"image_base64": b64, "ppe": False, "safety_only": True, "seg": False, "pose": True, "press": False,
               "track_key": "mac_rtt_probe"}   # 전용 track_key — 실 브라우저 추적 상태와 격리(회귀 방지)
    print(f"  [{label}] 워밍업...")
    _req(base_url, "POST", "/detect/frame", token, payload, timeout=60)
    rtts = []
    for i in range(n):
        t0 = time.perf_counter()
        _req(base_url, "POST", "/detect/frame", token, payload, timeout=15)
        rtts.append((time.perf_counter() - t0) * 1000)
    return {
        "label": label, "n": len(rtts),
        "p50": round(statistics.median(rtts), 1), "p90": round(_percentile(rtts, 0.9), 1),
        "min": round(min(rtts), 1), "max": round(max(rtts), 1),
    }


def _wait_online(base_url: str, token: str, cid: str, want_enabled: bool, timeout: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        cams = _req(base_url, "GET", "/cameras", token)
        cam = next((c for c in cams.get("cameras", []) if c["id"] == cid), None)
        if cam is None:
            return not want_enabled
        if want_enabled and cam.get("online"):
            return True
        if not want_enabled and not cam.get("enabled"):
            return True
        time.sleep(1.0)
    return False


def main() -> None:
    a = _args()
    print(f"대상 서버: {a.base_url}")
    try:
        health = _req(a.base_url, "GET", "/health", a.token, timeout=10)
        print("health:", health)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[mac_rtt_contention_probe] 서버 접속 실패({a.base_url}) — 주소·포트·토큰 확인: {e}") from e

    b64, img_bytes = _build_test_image_b64()
    print(f"테스트 이미지: {img_bytes}bytes(jpeg) / base64 {len(b64)}자 (합성, 카메라 무관)")

    cams_before = _req(a.base_url, "GET", "/cameras", a.token).get("cameras", [])
    enabled_before = [c for c in cams_before if c.get("enabled")]
    print(f"\n현재 등록된 카메라: {len(cams_before)}개, 그 중 enabled: {len(enabled_before)}개")
    for c in cams_before:
        print(f"  - {c['id']}: enabled={c.get('enabled')} online={c.get('online')} source(마스킹)={c.get('source')}")

    print("\n=== AS-IS(현재 상태 그대로) RTT 측정 ===")
    as_is = _measure_rtt(a.base_url, a.token, b64, a.n, "AS-IS(현재)")
    print(f"  p50={as_is['p50']}ms p90={as_is['p90']}ms (n={as_is['n']})")

    if a.dry_run or not enabled_before:
        if not enabled_before:
            print("\n[안내] enabled 카메라가 없어 경합 비교(끄기 전/후)를 생략합니다 — 이 서버에는 RTT를 "
                  "부풀릴 워커 경합 후보가 현재 없다는 뜻입니다(다른 원인 의심).")
        else:
            print("\n[--dry-run] 카메라는 건드리지 않았습니다.")
        print("\n결과 저장 없이 종료(측정값은 위 출력 참고).")
        return

    print(f"\n=== 카메라 {len(enabled_before)}개 임시 비활성화 → RTT 재측정 → 반드시 원복 ===")
    disabled_ids: list[str] = []
    restore_ok: dict[str, bool] = {}
    try:
        for c in enabled_before:
            cid = c["id"]
            print(f"  비활성화: {cid} ...")
            _req(a.base_url, "POST", f"/cameras/{cid}/disable", a.token, {})
            disabled_ids.append(cid)
        ok_off = _wait_online(a.base_url, a.token, disabled_ids[-1], want_enabled=False, timeout=a.restore_timeout)
        if not ok_off:
            print("  [경고] 비활성화 확인 폴링 타임아웃 — 그래도 측정은 진행하되 아래 결과 해석에 주의")

        workers_off = _measure_rtt(a.base_url, a.token, b64, a.n, "워커 OFF")
        print(f"  p50={workers_off['p50']}ms p90={workers_off['p90']}ms (n={workers_off['n']})")
    finally:
        print("\n=== 복구: 비활성화한 카메라 전부 재활성화 ===")
        for cid in disabled_ids:
            try:
                _req(a.base_url, "POST", f"/cameras/{cid}/enable", a.token, {})
                ok = _wait_online(a.base_url, a.token, cid, want_enabled=True, timeout=a.restore_timeout)
                restore_ok[cid] = ok
                print(f"  {cid}: {'✅ online 복구 확인' if ok else '🔴 복구 실패(수동 확인 필요!)'}")
            except Exception as e:  # noqa: BLE001
                restore_ok[cid] = False
                print(f"  {cid}: 🔴 재활성화 요청 자체가 실패 — 수동 확인 필요! ({e})")

    print("\n=== 최종 복구 확인표(이걸 그대로 보고에 붙여넣기) ===")
    all_ok = True
    for cid, ok in restore_ok.items():
        print(f"  {cid}: {'복구 성공' if ok else '복구 실패 — 즉시 수동 확인 필요'}")
        all_ok = all_ok and ok
    if not all_ok:
        print("\n🔴🔴🔴 일부 카메라가 정상 복구되지 않았습니다 — 위 표를 그대로 알려주시고, "
              "맥에서 /cameras 로 직접 상태를 확인해주세요.")
        sys.exit(1)

    print("\n=== 결과 요약 ===")
    gap = round(as_is["p50"] - workers_off["p50"], 1)
    print(f"AS-IS(현재 상태)   p50={as_is['p50']}ms  p90={as_is['p90']}ms")
    print(f"워커 OFF(경합 제거) p50={workers_off['p50']}ms  p90={workers_off['p90']}ms")
    print(f"차이(경합 기여분 추정) = {gap}ms")
    if gap > 30:
        print("→ 워커 경합이 RTT를 유의미하게 부풀리고 있는 것으로 보입니다(GPU/DETECT_LOCK 큐잉 유력).")
    else:
        print("→ 워커 유무로 RTT 차이가 크지 않습니다 — 경합이 주원인이 아닐 가능성. "
              "네트워크·이미지 인코딩·모델 자체 추론시간 쪽을 봐야 합니다.")
    print("\n모든 출력(카메라 목록·AS-IS·워커OFF·복구확인표·요약)을 그대로 복사해 보고해 주세요.")


if __name__ == "__main__":
    main()
