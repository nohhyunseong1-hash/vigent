#!/usr/bin/env python3
"""[TP] tapo_test 영상 3편 — 실서비스 파이프라인 검출·추적 품질 실측.

방법: 파일 카메라로 등록(fps 2.0, 실서비스 페이싱)하고 `/cameras/{cid}/detections` 를
고빈도 폴링(ts 변화로 중복 제거)해 검출 스트림을 수집한다. 30초마다 스냅샷 + 최신 검출로
주석 프레임을 저장한다(스냅샷은 P1a 얼굴 모자이크가 적용된 상태 — 원본 검출에는 무영향).

추적 지표는 scripts/eval_tracking.py(P2b)의 프록시 정의를 재사용한다:
  ID스위치(같은 자리 다른 id) · 트랙 단절 · 재식별 성공률 · 고유 tid 수.
★파일 소스는 EOF 에서 되감기라 루프 경계에서 인위적 ID 전환이 생긴다 — 경계 ±2s 는
따로 센다(실제 품질 문제와 구분).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("D:/vigent_original")
BASE = "http://127.0.0.1:8010"
OUT = ROOT / "runs" / "tapo_test_eval"
TOK = ""
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("VIGENT_API_TOKEN="):
        TOK = line.split("=", 1)[1].strip()

VIDEOS = sorted(Path("C:/Users/shgus/OneDrive/바탕 화면/tapo_test").glob("*.mp4"))
MATCH_IOU = 0.5
PPE_CLASSES = {"Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest", "Safety Vest",
               "NO-Safety Vest", "Mask", "NO-Mask", "Safety Cone"}
FIRE_CLASSES = {"fire", "smoke", "Fire", "Smoke"}


def api(path, method="GET", body=None, raw=False, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        return b if raw else (json.loads(b) if b else {})


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ub = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    u = ua + ub - inter
    return inter / u if u > 0 else 0.0


def video_duration(p: Path) -> float:
    c = cv2.VideoCapture(str(p))
    n, fps = c.get(cv2.CAP_PROP_FRAME_COUNT), c.get(cv2.CAP_PROP_FPS)
    c.release()
    return (n / fps) if fps else 0.0


def wait_worker(cid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        cams = api("/health").get("cameras") or {}
        v = cams.get(cid) or {}
        if v.get("status") == "ok" and (v.get("last_detect_age_s") or 99) < 5:
            return True
        time.sleep(1.5)
    return False


def annotate(cid, out_path: Path):
    """스냅샷(640x360, 얼굴 모자이크됨) + 최신 검출을 겹쳐 저장."""
    try:
        jpg = api(f"/cameras/{cid}/snapshot", raw=True)
        d = api(f"/cameras/{cid}/detections")
    except Exception:
        return False
    arr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        return False
    h, w = arr.shape[:2]
    for det in d.get("detections", []):
        bb = det.get("bbox") or []
        if len(bb) != 4:
            continue
        x1, y1, x2, y2 = int(bb[0]*w), int(bb[1]*h), int(bb[2]*w), int(bb[3]*h)
        cls = str(det.get("class"))
        color = ((80, 220, 80) if cls == "person" else
                 (60, 140, 255) if cls in PPE_CLASSES else
                 (50, 50, 230) if cls in FIRE_CLASSES else (200, 200, 200))
        cv2.rectangle(arr, (x1, y1), (x2, y2), color, 2)
        tid = det.get("id")
        label = f"{cls} {det.get('score', 0):.2f}" + (f" #{tid}" if tid is not None else "")
        cv2.putText(arr, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), arr)
    return True


def collect(cid, secs, dur_loop, outdir: Path):
    """검출 스트림 수집 + 30초마다 주석 프레임."""
    samples = []      # {t, ts, dets, pc}
    health = []       # {t, lat, status, overall}
    last_ts = -1
    t0 = time.time()
    next_snap = t0 + 10.0
    snap_i = 0
    while time.time() - t0 < secs:
        try:
            d = api(f"/cameras/{cid}/detections")
        except Exception:
            time.sleep(0.5)
            continue
        ts = d.get("ts") or 0
        if ts != last_ts:
            last_ts = ts
            samples.append({"t": round(time.time() - t0, 2), "ts": ts,
                            "pc": d.get("person_count"),
                            "dets": [{"c": x.get("class"), "f": round(float(x.get("score") or 0), 3),   # ★필드명은 score (worker._det_dict)
                                      "b": x.get("bbox"), "id": x.get("id")}
                                     for x in d.get("detections", [])]})
        now = time.time()
        if now >= next_snap:
            snap_i += 1
            annotate(cid, outdir / f"frame_{snap_i:02d}.jpg")
            next_snap = now + 30.0
            try:
                h = api("/health")
                cam = (h.get("cameras") or {}).get(cid) or {}
                health.append({"t": round(now - t0, 1), "overall": h.get("status"),
                               "lat": cam.get("last_detect_latency_ms"),
                               "st": cam.get("status")})
            except Exception:
                pass
        time.sleep(0.18)
    return samples, health


def person_frames(samples):
    out = []
    for s in samples:
        persons = [{"tid": d.get("id"), "box": d["b"], "conf": d["f"]}
                   for d in s["dets"] if d["c"] == "person" and d.get("id") is not None and d.get("b")]
        out.append({"t": s["t"], "tracks": persons})
    return out


def track_metrics(frames, dur_loop):
    """eval_tracking.py 의 프록시 지표 + 루프 경계 분리."""
    def near_boundary(t):
        if dur_loop <= 0:
            return False
        m = t % dur_loop
        return m < 2.0 or m > dur_loop - 2.0
    id_sw = id_sw_boundary = 0
    for prev, cur in zip(frames, frames[1:]):
        for t in cur["tracks"]:
            best, bi = None, 0.0
            for p in prev["tracks"]:
                v = iou(t["box"], p["box"])
                if v > bi:
                    best, bi = p, v
            if best is not None and bi >= MATCH_IOU and best["tid"] != t["tid"]:
                if near_boundary(cur["t"]):
                    id_sw_boundary += 1
                else:
                    id_sw += 1
    # 단절/재식별: 사라진 트랙이 이후 같은 자리에 같은/다른 id 로 복귀
    last_seen = {}
    reid_ok = frag = 0
    active_prev = {}
    for f in frames:
        cur_ids = {t["tid"] for t in f["tracks"]}
        for tid, (box, t_last) in list(last_seen.items()):
            for t in f["tracks"]:
                if iou(box, t["box"]) >= MATCH_IOU:
                    if t["tid"] == tid:
                        reid_ok += 1
                    else:
                        frag += 1
                    last_seen.pop(tid, None)
                    break
        for tid, t in active_prev.items():
            if tid not in cur_ids:
                last_seen[tid] = (t["box"], f["t"])
        active_prev = {t["tid"]: t for t in f["tracks"]}
    uniq = len({t["tid"] for f in frames for t in f["tracks"]})
    denom = reid_ok + frag
    return {"unique_tids": uniq, "id_switches": id_sw, "id_switches_loop_boundary": id_sw_boundary,
            "fragmented": frag, "reid_ok": reid_ok,
            "reid_rate_pct": round(reid_ok / denom * 100, 1) if denom else None}


def slot_stats(samples):
    buckets = {"person": [], "ppe": [], "fire_smoke": [], "other": []}
    for s in samples:
        for d in s["dets"]:
            c = d["c"]
            k = ("person" if c == "person" else
                 "ppe" if c in PPE_CLASSES else
                 "fire_smoke" if c in FIRE_CLASSES else "other")
            buckets[k].append(d["f"])
    n = max(1, len(samples))
    out = {}
    for k, v in buckets.items():
        out[k] = {"total": len(v), "per_frame": round(len(v) / n, 2),
                  "mean_conf": round(sum(v) / len(v), 3) if v else None,
                  "min_conf": round(min(v), 3) if v else None}
    # 검출 0 인 구간(연속 3샘플 이상 person 없음)
    gaps = []
    run = None
    for s in samples:
        has_p = any(d["c"] == "person" for d in s["dets"])
        if not has_p:
            run = [s["t"], s["t"]] if run is None else [run[0], s["t"]]
        else:
            if run and run[1] - run[0] >= 1.5:
                gaps.append([round(run[0], 1), round(run[1], 1)])
            run = None
    if run and run[1] - run[0] >= 1.5:
        gaps.append([round(run[0], 1), round(run[1], 1)])
    out["person_empty_spans_s"] = gaps
    return out


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
    report = []
    OUT.mkdir(parents=True, exist_ok=True)
    for i, vp in enumerate(VIDEOS, 1):
        cid = f"tp{i}"
        dur = video_duration(vp)
        outdir = OUT / cid
        print(f"[{cid}] {vp.name} ({dur:.1f}s 루프) 등록·관찰 {secs:.0f}초", flush=True)
        try:
            api(f"/cameras/{cid}", "DELETE")
        except Exception:
            pass
        api("/cameras", "POST", {"id": cid, "name": f"tapo시험{i}", "source": str(vp),
                                 "fps": 2.0, "enabled": True})
        if not wait_worker(cid):
            print(f"  ⚠ {cid} 워커 기동 실패 — 건너뜀", flush=True)
            api(f"/cameras/{cid}", "DELETE")
            continue
        samples, health = collect(cid, secs, dur, outdir)
        api(f"/cameras/{cid}", "DELETE")
        time.sleep(2)
        pf = person_frames(samples)
        rec = {"video": vp.name, "cid": cid, "loop_s": round(dur, 1),
               "samples": len(samples), "slot": slot_stats(samples),
               "tracking": track_metrics(pf, dur),
               "health": health,
               "lat_list": [h["lat"] for h in health if h.get("lat") is not None]}
        report.append(rec)
        s = rec["slot"]; tr = rec["tracking"]
        print(f"  샘플 {rec['samples']} · person/프레임 {s['person']['per_frame']}"
              f"(conf {s['person']['mean_conf']}) · ppe/프레임 {s['ppe']['per_frame']}"
              f"(conf {s['ppe']['mean_conf']}) · fire {s['fire_smoke']['total']}건 · "
              f"고유트랙 {tr['unique_tids']} · ID스위치 {tr['id_switches']}"
              f"(+경계 {tr['id_switches_loop_boundary']}) · 재식별 {tr['reid_rate_pct']}%", flush=True)
    (OUT / "tp_eval_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # 원상복구 확인
    time.sleep(2)
    cams = api("/cameras")
    lst = cams if isinstance(cams, list) else cams.get("cameras", [])
    left = [x.get("id") for x in lst if str(x.get("id", "")).startswith("tp")]
    h = api("/health")
    t = (h.get("cameras") or {}).get("test", {})
    print(f"[복구] 등록 잔여 tp*: {left or '없음'} · status={h.get('status')} · "
          f"실카 {t.get('status')} lat={t.get('last_detect_latency_ms')}ms", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
