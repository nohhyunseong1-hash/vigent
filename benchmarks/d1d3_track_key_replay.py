#!/usr/bin/env python3
"""[D1+D3] 쿨다운·백오프 키를 '사람 단위(track id)'로 바꿨을 때 폭주하는가 — 재생 검증.

★왜 이 측정이 필요한가(사용자 지시 2026-08-24):
  D1·D3 결정은 "같은 사람의 반복은 억제하되 **다른 사람의 진입은 새 경보**"다.
  그러려면 키에 track id 를 넣어야 하는데, **ID 스위치**(같은 사람이 새 ID 로 잡히는 것)가
  나면 새 ID = 새 상태 = 새 경보가 되어 **억제를 통째로 우회**한다.
  추적 품질이 나쁘면 이 수술이 오히려 경보 폭주를 만든다 — 그래서 실측이 먼저다.

측정 방법:
  같은 영상·같은 검출 결과를 두 방식으로 나란히 돌린다(공정 비교).
    A) 현행  — 구역 디바운서 키 = 카메라, 쿨다운 키 = 규칙
    B) 제안  — 구역 디바운서 키 = 카메라:트랙, 쿨다운 키 = 규칙:트랙
  각각에 대해 ①발화 수 ②alert_gate 통과(=폰 알림) 수 를 센다.

사용:
    python benchmarks/d1d3_track_key_replay.py --video footage/xxx.mp4 --fps 2
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import alert_gate  # noqa: E402
import cv2  # noqa: E402
import vision_loader  # noqa: E402
import zone_debounce  # noqa: E402
from agents.guard import GuardAgent  # noqa: E402
from worker import _point_in_poly  # noqa: E402

# 시험용 위험구역 — 화면 중앙~하단(작업 구역을 흉내). 정규화 좌표.
#   ★실제 현장 구역이 아니다. 목적은 "두 방식의 상대 비교"이므로 구역 모양 자체는
#     결론에 영향이 적다(같은 구역을 양쪽에 똑같이 쓴다).
TEST_ZONE = [(0.25, 0.45), (0.85, 0.45), (0.85, 0.99), (0.25, 0.99)]
COOLDOWN_S = 15.0


def _fires_current(states, tids_inside, dbnc, now, cooldown):
    """A) 현행 — 카메라 단위 디바운서 + 규칙 단위 쿨다운."""
    fired = 0
    was = dbnc.state("cam")["confirmed"]
    now_in = dbnc.update("cam", bool(tids_inside), now)
    if now_in and not was:
        if now - cooldown.get("zone_intrusion", -1e9) >= COOLDOWN_S:
            cooldown["zone_intrusion"] = now
            fired = 1
    return fired


def _fires_track(states, tids_inside, dbnc, now, cooldown, seen_tracks):
    """B) 제안 — 트랙 단위 디바운서 + 트랙 단위 쿨다운. **발화한 tid 목록**을 돌려준다.

    ★백오프(alert_gate) 키에도 트랙이 들어가야 결정대로다 — 개수만 돌려주면
      게이트를 카메라 단위로 부르게 되어 **측정이 실제보다 낙관적**으로 나온다.
    """
    fired: list[int] = []
    seen_tracks |= tids_inside
    # 이번 프레임에 보인 트랙만 갱신하고, 안 보인 트랙은 '밖'으로 갱신한다.
    for tid in list(seen_tracks):
        key = f"cam:t{tid}"
        was = dbnc.state(key)["confirmed"]
        now_in = dbnc.update(key, tid in tids_inside, now)
        if now_in and not was:
            ck = f"zone_intrusion:t{tid}"
            if now - cooldown.get(ck, -1e9) >= COOLDOWN_S:
                cooldown[ck] = now
                fired.append(tid)
    return fired


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="검출 주기(운영과 동일하게 2)")
    args = ap.parse_args()

    cap = cv2.VideoCapture(str(_ROOT / args.video))
    if not cap.isOpened():
        print(f"영상을 열 수 없다: {args.video}")
        return 2
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, int(round(src_fps / args.fps)))

    g = GuardAgent(vision_loader.load_vision("safety"))
    dbnc_a = zone_debounce.ZoneDebouncer()
    dbnc_b = zone_debounce.ZoneDebouncer()
    cd_a: dict[str, float] = {}
    cd_b: dict[str, float] = {}
    seen: set[int] = set()
    alert_gate.reset()

    fires_a = fires_b = 0
    notif_a = notif_b = 0
    all_tids: set[int] = set()
    frames = 0
    idx = 0
    vt = 0.0                      # 영상 시각(초) — 실시간이 아니라 영상 기준으로 센다
    t_start = time.time()

    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        ok, frame = cap.retrieve()
        idx += 1
        if not ok:
            break
        frames += 1
        vt = idx / src_fps

        out = g.detect(frame, detectors=["person"], track_key="cam:replay")
        inside: set[int] = set()
        for d in out.get("detections", []):
            if str(d.get("label", "")).lower() != "person":
                continue
            tid = d.get("tid")
            if tid is None:
                continue
            all_tids.add(int(tid))
            px, py = zone_debounce.ref_point(d.get("bbox", [0, 0, 0, 0]))
            if _point_in_poly(px, py, TEST_ZONE):
                inside.add(int(tid))

        fa = _fires_current(None, inside, dbnc_a, vt, cd_a)
        fb_tids = _fires_track(None, inside, dbnc_b, vt, cd_b, seen)
        fires_a += fa
        fires_b += len(fb_tids)
        for _ in range(fa):
            if alert_gate.decide("replayA", "zone_intrusion", "high", now=vt)["notify"]:
                notif_a += 1
        for tid in fb_tids:      # ★게이트 키에도 트랙을 넣는다(결정대로)
            if alert_gate.decide(f"replayB:t{tid}", "zone_intrusion", "high", now=vt)["notify"]:
                notif_b += 1

    cap.release()
    dur = vt
    print(f"\n영상: {args.video}")
    print(f"  처리 {frames}프레임 · 영상 {dur:.1f}초 · 검출주기 {args.fps}fps · 실행 {time.time()-t_start:.1f}초")
    print(f"  person 고유 track id: **{len(all_tids)}개**"
          f"  (분당 {len(all_tids)/max(dur,1)*60:.1f}개 신규)")
    print(f"\n{'방식':<28}{'발화':>8}{'폰 알림':>10}")
    print(f"{'A) 현행(카메라·규칙 단위)':<28}{fires_a:>8}{notif_a:>10}")
    print(f"{'B) 제안(트랙 단위)':<28}{fires_b:>8}{notif_b:>10}")
    if fires_a:
        print(f"\n  발화 배수: {fires_b/max(fires_a,1):.1f}배 · 알림 배수: {notif_b/max(notif_a,1):.1f}배")
    print("\n★해석: B 가 A 보다 크게 늘면 ID 스위치가 억제를 우회한다는 뜻이다"
          "(같은 사람이 새 ID 로 계속 잡혀 새 경보가 된다).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
