"""rig_replay.py — rig_monitor 상태기계를 '수동 주석 obs(CSV)'로 재생·검증 (B4 Option 1).

★ 기존 검출 파이프라인 무영향: 독립 실행 도구다. detect→obs 자동배선(하물 검출기 부재로 불가)이
  아니라, 사람이 영상을 보고 주석한 CSV 를 프레임별 obs 로 보간해 rig_monitor 에 주입하고,
  상태 전이 타임라인을 만든다 → 실영상 장면과 대조해 상태기계 로직을 검증한다.

수동 주석 CSV 스키마(최소 부담 — 변하는 순간에만 한 줄, 사이는 자동 보간):
    t,load_h,n_in,fall,note
    - t      : 초(float). 국면이 바뀌는 순간 + 몇 개 확인점만. 매초 안 해도 됨(사이 보간).
    - load_h : 하물 하단 높이(m, 지면=0). 눈대중 추정. **빈칸 = None**(추적 불가 → (a)·권상 전이 보류).
    - n_in   : 하물/후크 반경 내 작업자 수(눈으로 카운트).
    - fall   : 반경 내 낙상/급자세이상 0 또는 1.
    - note   : 장면 설명(대조용 ground truth. 예: "미동권상 시작", "작업자 이탈").
  load_h 는 인접 두 행 사이를 선형보간(양끝 중 하나라도 빈칸이면 그 구간은 None).
  n_in·fall 은 계단 유지(가장 최근 행 값). t 는 fps 로 프레임마다 생성.

CLI:  python rig_replay.py obs.csv --fps 24 [--video footage/x.mp4]
      → 상태 전이 타임라인(초, from→to, reason)과 ALARM 시각을 출력.
"""
from __future__ import annotations

import csv

from rig_monitor import RigConfig, RigStateMachine


def load_obs_csv(path: str) -> list[dict]:
    """주석 CSV → 정렬된 키프레임 행 목록. load_h 빈칸은 None."""
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lh = (r.get("load_h") or "").strip()
            rows.append({
                "t": float(r["t"]),
                "load_h": (float(lh) if lh != "" else None),
                "n_in": int(float(r.get("n_in") or 0)),
                "fall": str(r.get("fall") or "0").strip() in ("1", "true", "True"),
                "note": (r.get("note") or "").strip(),
            })
    rows.sort(key=lambda x: x["t"])
    return rows


def _interp_load_h(rows: list[dict], t: float) -> float | None:
    """t 시점 load_h — 인접 두 키프레임 선형보간(양끝 중 None 있으면 None). 범위 밖은 최근값 유지."""
    if not rows:
        return None
    if t <= rows[0]["t"]:
        return rows[0]["load_h"]
    if t >= rows[-1]["t"]:
        return rows[-1]["load_h"]
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["t"] <= t <= b["t"]:
            if a["load_h"] is None or b["load_h"] is None:
                return None
            if b["t"] == a["t"]:
                return b["load_h"]
            f = (t - a["t"]) / (b["t"] - a["t"])
            return a["load_h"] + f * (b["load_h"] - a["load_h"])
    return rows[-1]["load_h"]


def _step(rows: list[dict], t: float, key: str):
    """t 이하 최근 키프레임의 값(계단 유지)."""
    val = rows[0][key] if rows else None
    for r in rows:
        if r["t"] <= t:
            val = r[key]
        else:
            break
    return val


def build_frame_obs(rows: list[dict], fps: float, duration: float | None = None) -> list[dict]:
    """키프레임 행 → 프레임별 obs 목록(fps 간격, load_h 보간 · n_in/fall 계단)."""
    if not rows:
        return []
    end = duration if duration is not None else rows[-1]["t"]
    dt = 1.0 / max(1e-6, fps)
    obs, t = [], 0.0
    n = int(end / dt) + 1
    for i in range(n):
        t = round(i * dt, 6)
        obs.append({
            "t": t,
            "load_h": _interp_load_h(rows, t),
            "n_in": int(_step(rows, t, "n_in") or 0),
            "ids_in": set(range(int(_step(rows, t, "n_in") or 0))),   # id 는 수동주석 없음 → 인원수만큼 가상 id
            "fall": bool(_step(rows, t, "fall")),
        })
    return obs


def replay(rows: list[dict], fps: float, cfg: RigConfig | None = None,
           duration: float | None = None) -> dict:
    """프레임 obs 를 상태기계에 주입 → 전이 로그·ALARM 시각·최종상태 반환."""
    m = RigStateMachine(cfg=cfg or RigConfig())
    frames = build_frame_obs(rows, fps, duration)
    alarms = []
    for o in frames:
        r = m.update(o)
        if r["alarm"] and (not alarms or alarms[-1]["reason"] != r["reason"]):
            alarms.append({"t": r["t"], "reason": r["reason"]})
    return {"transitions": list(m.log), "alarms": alarms,
            "final_state": m.state, "n_frames": len(frames)}


def _fmt(rows: list[dict], res: dict) -> str:
    lines = ["시각(s)  전이               사유"]
    note_at = {round(r["t"], 1): r["note"] for r in rows if r["note"]}
    for (t, frm, to, reason) in res["transitions"]:
        note = note_at.get(round(t, 1), "")
        lines.append(f"{t:6.2f}  {frm:>10}→{to:<10}  {reason or ''}   {('· 주석: ' + note) if note else ''}")
    lines.append(f"\nALARM {len(res['alarms'])}건: " +
                 "; ".join(f"{a['t']:.2f}s {a['reason']}" for a in res["alarms"]) if res["alarms"] else "\nALARM 없음")
    lines.append(f"최종상태: {res['final_state']} · 프레임 {res['n_frames']}개")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="rig_monitor 수동 obs 재생·검증(B4)")
    ap.add_argument("csv", help="주석 CSV(t,load_h,n_in,fall,note)")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--video", default=None, help="(선택) 영상 — fps 자동감지용")
    ap.add_argument("--duration", type=float, default=None)
    a = ap.parse_args(argv)
    fps = a.fps
    if a.video:
        import cv2
        cap = cv2.VideoCapture(a.video)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS) or fps
        cap.release()
    rows = load_obs_csv(a.csv)
    res = replay(rows, fps, duration=a.duration)
    print(_fmt(rows, res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
