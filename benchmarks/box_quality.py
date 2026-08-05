#!/usr/bin/env python3
"""benchmarks/box_quality.py — 바운딩박스 품질 측정 하네스 (측정 전용, 로직 무수정).

목적: "눈으로 판단"을 "숫자로 판단"으로. 카메라 없이 mp4 파일 하나를 입력받아
  Part A(검출 재생) → Part B(표시 재생) → Part C(지표 산출) → Part D(콘솔+md 출력) 를 자동 수행한다.
  guard.detect()·static/vigent-box-display.js(BoxTracker) 는 **그대로 재사용**한다(재구현·수정 금지).

Part A — 검출 재생: 영상을 프레임순으로 guard.detect() 에 통과시켜 프레임별 검출(bbox·클래스·conf·tid)을 기록.
  guard 는 vision_loader.load_vision("safety") + agents.build_agents(cfg) 로 오프라인 구성
  (main.py/FastAPI 불필요 — tests/test_scribe_copilot_dispatcher.py 와 동일한 표준 오프라인 구성 패턴).

Part B — 표시 재생: 검출 시퀀스를 실제 도착 지연(ingest delay)을 주입한 스케줄로
  box_quality_display.js(Node, BoxTracker 미수정 그대로 구동)에 넘겨 rAF 60fps 를 시뮬레이션,
  매 렌더틱의 표시 박스(vis)를 받는다. 지연 시나리오 5종(이상적·200·400·600ms·맥 실사용p50/jitter)을 반복.

Part C — 지표: 표시오차(px, 속도구간별 p50/p95) · 정지프레임 비율 · 유령(같은클래스 겹침·person 없이 뜬 타클래스)
  · (지연 무관, 검출 스트림 자체 속성) 트랙 안정성(tid 교체 횟수).
  '지상 진실(ground truth)'은 **캡처 시각 사이의 선형보간**으로 정의한다(캡처 프레임 자체가 유일하게
  가진 실측 위치이므로) — 이는 검출기 자체의 정확도를 재측정하는 게 아니라(그건 benchmarks/EVAL.md 소관),
  "서버가 이미 캡처한 위치 시퀀스를 화면이 얼마나 충실히 재구성하는가"를 재는 것이다.

Part D — 콘솔 표 출력 + benchmarks/box_quality_<tag>.md 저장.

사용:
  /path/to/python3 benchmarks/box_quality.py --video runs/rfdetr/test_fast.mp4 --tag test_fast
  /path/to/python3 benchmarks/box_quality.py --video runs/rfdetr/test_walk.mp4 --tag test_walk

주의(정직 고지): 이 실행 환경에는 ppe/forklift/fire_smoke 파인튜닝 가중치가 없다(.gitignore 대상).
  VIGENT_ALLOW_FALLBACK=1 로 그 슬롯들을 켜면 COCO 사전학습으로 대체되는데, COCO 에는애초
  "NO-Hardhat" 등 PPE 클래스가 없어 항상 0건만 나온다 — 그건 "유령 0건(우수)"이 아니라 "미측정"이다.
  그래서 기본 detectors=person 만 쓴다(guard.py 주석 그대로: want = detectors or ["person"] 가 기본
  '범용'(COCO 80종) 검출이라 person 슬롯 자체에서도 bed·dining table 등 비-person 클래스가 섞여
  나온다 — 이건 실제 배포 기본값과 동일한 조건이라 "person 없이 뜨는 타클래스 박스" 유령 지표에 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

RENDER_FPS = 60
OVERLAP_IOU_THRESHOLD = 0.10   # "같은클래스 겹침" 판정 임계. BoxTracker 자체 dedup(0.40)보다 낮게 잡아
                                # dedup 사각지대(억제 안 되는 잔여 겹침)를 포착한다.

SCENARIOS: list[dict[str, Any]] = [
    {"name": "ideal", "label": "이상적(지연 0)", "delay_ms": 0, "jitter_ms": 0},
    {"name": "d200", "label": "지연 200ms", "delay_ms": 200, "jitter_ms": 0},
    {"name": "d400", "label": "지연 400ms", "delay_ms": 400, "jitter_ms": 0},
    {"name": "d600", "label": "지연 600ms", "delay_ms": 600, "jitter_ms": 0},
    {"name": "mac_real", "label": "맥 실사용(p50 423·jitter 572)", "delay_ms": 423, "jitter_ms": 572},
]


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="바운딩박스 품질 측정 하네스(측정 전용 — 로직 무수정)")
    p.add_argument("--video", required=True, help="입력 mp4 경로")
    p.add_argument("--tag", required=True, help="리포트 파일명에 쓸 태그(예: test_fast)")
    p.add_argument("--detectors", default="person",
                   help="쉼표구분 guard 검출기 목록. 기본 person(이 환경엔 ppe/forklift/fire_smoke 가중치 없음)")
    p.add_argument("--imgsz", type=int, default=None, help="추론 해상도 override(기본=guard 설정값)")
    p.add_argument("--conf", type=float, default=None, help="검출 임계 override(기본=검출기별 배포 임계)")
    p.add_argument("--track-key-prefix", default="boxq")
    p.add_argument("--max-frames", type=int, default=0, help="0=전체 프레임")
    p.add_argument("--report-dir", default=str(_ROOT / "benchmarks"))
    p.add_argument("--node-bin", default="node", help="Node 실행파일(PATH 에 없으면 절대경로 지정)")
    p.add_argument("--exclude-class", default=None, help="표시 스택에서 제외할 클래스(예: person — 스켈레톤 화면용)")
    p.add_argument("--seed", type=int, default=12345)
    return p.parse_args()


# ── Part A: 검출 재생 ──────────────────────────────────────────────────────
def _build_guard() -> Any:
    """오프라인 Guard 구성. main.py/FastAPI 불필요 — tests/test_scribe_copilot_dispatcher.py 와 동일 패턴."""
    import vision_loader
    from agents import build_agents
    cfg = vision_loader.load_vision("safety")
    agents = build_agents(cfg)
    return agents["Guard"]


def replay_detections(video: Path, detectors: list[str], track_key: str,
                       imgsz: int | None, conf: float | None, max_frames: int
                       ) -> tuple[list[dict[str, Any]], float, float]:
    """영상을 프레임순으로 guard.detect() 에 통과 → 프레임별 {idx,t_cap_ms,w,h,dets:[{cls,score,tid,box}]}."""
    import cv2
    guard = _build_guard()
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"[box_quality] 영상을 열 수 없음: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames: list[dict[str, Any]] = []
    idx = 0
    t0 = time.time()
    while True:
        ok, img = cap.read()
        if not ok or (max_frames and idx >= max_frames):
            break
        h, w = img.shape[:2]
        out = guard.detect(img, detectors=detectors, imgsz=imgsz, conf=conf, track_key=track_key)
        dets = []
        for d in out.get("detections", []):
            x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
            dets.append({
                "cls": d.get("label"), "score": float(d.get("conf", 0.0)),
                "tid": int(d.get("tid", -1)),
                # 소스 프레임 픽셀 [x,y,w,h] — routers/detect.py 의 실제 배포 변환과 동일(클램프 없음).
                "box": [round(x1 * w, 2), round(y1 * h, 2), round((x2 - x1) * w, 2), round((y2 - y1) * h, 2)],
            })
        frames.append({"idx": idx, "t_cap_ms": (idx / fps) * 1000.0, "w": w, "h": h, "dets": dets})
        idx += 1
    cap.release()
    return frames, fps, time.time() - t0


def _iou_xywh(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def track_stability(frames: list[dict[str, Any]], cls: str = "person") -> dict[str, Any]:
    """트랙 안정성(지연 시나리오와 무관 — 검출 스트림 자체 속성). tools/track_quality.py 와 동일 원리:
    연속 프레임 IoU>=0.5 매칭 시 tid 가 바뀐 횟수 + 고유 tid 수."""
    seq = [[d for d in f["dets"] if d["cls"] == cls] for f in frames]
    tids: set[int] = set()
    for fr in seq:
        for d in fr:
            tids.add(d["tid"])
    switches = 0
    for a, b in zip(seq, seq[1:]):
        for db in b:
            best, best_tid = 0.0, None
            for da in a:
                v = _iou_xywh(da["box"], db["box"])
                if v > best:
                    best, best_tid = v, da["tid"]
            if best >= 0.5 and best_tid is not None and best_tid != db["tid"]:
                switches += 1
    return {"unique_tids": len(tids), "switches": switches}


# ── Part B: 표시 재생(Node, BoxTracker 미수정 그대로 구동) ────────────────────
def run_display_scenario(frames: list[dict[str, Any]], scenario: dict[str, Any], node_bin: str,
                          exclude_class: str | None, seed: int) -> list[dict[str, Any]]:
    payload = {
        "render_fps": RENDER_FPS,
        "delay_ms": scenario["delay_ms"],
        "jitter_ms": scenario["jitter_ms"],
        "exclude_class": exclude_class,
        "seed": seed,
        "frames": [{"t_cap_ms": f["t_cap_ms"],
                    "dets": [{"cls": d["cls"], "score": d["score"], "id": d["tid"], "box": d["box"]}
                             for d in f["dets"]]}
                   for f in frames],
    }
    tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(payload, tf)
        tf.close()
        driver = str(_ROOT / "benchmarks" / "box_quality_display.js")
        r = subprocess.run([node_bin, driver, tf.name], capture_output=True, text=True, timeout=180)
    finally:
        Path(tf.name).unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"[box_quality] 표시 재생 실패({scenario['name']}): {r.stderr[-3000:]}")
    result: list[dict[str, Any]] = json.loads(r.stdout)
    return result


# ── Part C: 지표 산출 ───────────────────────────────────────────────────────
def _center(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def _traj_by_tid(frames: list[dict[str, Any]]) -> dict[int, list[tuple[float, list[float], str]]]:
    traj: dict[int, list[tuple[float, list[float], str]]] = {}
    for f in frames:
        for d in f["dets"]:
            traj.setdefault(d["tid"], []).append((f["t_cap_ms"], d["box"], d["cls"]))
    for tid in traj:
        traj[tid].sort(key=lambda x: x[0])
    return traj


def _interp(pts: list[tuple[float, list[float], str]], t: float) -> tuple[list[float] | None, float | None]:
    """t 시점 지상진실(캡처 프레임 사이 선형보간) 박스 + 그 구간의 속도(px/s).
    첫 검출 이전은 정의 없음(None). 마지막 검출 이후는 정지 유지로 간주(보간 구간이 없으므로 방법론상 단순화)."""
    if not pts:
        return None, None
    if t < pts[0][0]:
        return None, None
    if t >= pts[-1][0]:
        return pts[-1][1], 0.0
    for (t0, b0, _c0), (t1, b1, _c1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            if t1 <= t0:
                return b0, 0.0
            r = (t - t0) / (t1 - t0)
            box = [b0[k] + (b1[k] - b0[k]) * r for k in range(4)]
            c0x, c0y = _center(b0)
            c1x, c1y = _center(b1)
            dist = ((c1x - c0x) ** 2 + (c1y - c0y) ** 2) ** 0.5
            dt_s = (t1 - t0) / 1000.0
            speed = dist / dt_s if dt_s > 0 else 0.0
            return box, speed
    return None, None


def _percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def global_speed_thresholds(frames: list[dict[str, Any]]) -> tuple[float, float]:
    """느림/중간/빠름 33/66분위 경계값을 캡처프레임 구간 속도(px/s)에서 '한 번만' 계산한다.
    시나리오(지연)마다 따로 계산하면 렌더틱 표본 구성이 달라져 버킷 기준이 시나리오별로 어긋난다
    (지연 민감도 비교의 전제는 '동일 물리 속도 구간을 동일 기준으로 비교'하는 것) — 그래서 GT 자체(검출
    스트림)의 속도 분포에서 한 번만 뽑아 전 시나리오에 동일하게 적용한다."""
    traj = _traj_by_tid(frames)
    speeds: list[float] = []
    for pts in traj.values():
        for (t0, b0, _c0), (t1, b1, _c1) in zip(pts, pts[1:]):
            dt_s = (t1 - t0) / 1000.0
            if dt_s <= 0:
                continue
            c0, c1 = _center(b0), _center(b1)
            dist = ((c1[0] - c0[0]) ** 2 + (c1[1] - c0[1]) ** 2) ** 0.5
            speeds.append(dist / dt_s)
    speeds.sort()
    if len(speeds) >= 3:
        return speeds[len(speeds) // 3], speeds[2 * len(speeds) // 3]
    return 0.0, 0.0


def compute_metrics(frames: list[dict[str, Any]], vis_ticks: list[dict[str, Any]],
                     speed_thresholds: tuple[float, float]) -> dict[str, Any]:
    traj = _traj_by_tid(frames)
    q1, q2 = speed_thresholds
    samples: list[tuple[float, float]] = []   # (speed_px_s, error_px)
    freeze_num, freeze_den = 0, 0
    overlap_ticks, total_ticks, other_without_person_ticks = 0, 0, 0
    prev_boxes: dict[int, list[float]] = {}

    for tick in vis_ticks:
        t = tick["t_ms"]
        vis = tick["vis"]
        total_ticks += 1

        cur_boxes: dict[int, list[float]] = {}
        for v in vis:
            tid, box = v["tid"], v["box"]
            cur_boxes[tid] = box
            if tid in prev_boxes:
                freeze_den += 1
                if all(abs(box[k] - prev_boxes[tid][k]) < 1e-6 for k in range(4)):
                    freeze_num += 1
        prev_boxes = cur_boxes

        for v in vis:
            gt_box, speed = _interp(traj.get(v["tid"], []), t)
            if gt_box is None:
                continue
            gc, vc = _center(gt_box), _center(v["box"])
            err = ((gc[0] - vc[0]) ** 2 + (gc[1] - vc[1]) ** 2) ** 0.5
            samples.append((speed or 0.0, err))

        by_cls: dict[str, list[list[float]]] = {}
        for v in vis:
            by_cls.setdefault(v["cls"], []).append(v["box"])
        has_overlap = any(
            _iou_xywh(boxes[i], boxes[j]) >= OVERLAP_IOU_THRESHOLD
            for boxes in by_cls.values()
            for i in range(len(boxes)) for j in range(i + 1, len(boxes))
        )
        if has_overlap:
            overlap_ticks += 1

        has_person = any(v["cls"] == "person" for v in vis)
        has_other = any(v["cls"] != "person" for v in vis)
        if has_other and not has_person:
            other_without_person_ticks += 1

    buckets: dict[str, list[float]] = {"느림": [], "중간": [], "빠름": []}
    for s, e in samples:
        if s <= q1:
            buckets["느림"].append(e)
        elif s <= q2:
            buckets["중간"].append(e)
        else:
            buckets["빠름"].append(e)

    return {
        "n_ticks": total_ticks,
        "freeze_pct": (freeze_num / freeze_den * 100.0) if freeze_den else None,
        "freeze_num": freeze_num, "freeze_den": freeze_den,
        "overlap_pct": (overlap_ticks / total_ticks * 100.0) if total_ticks else None,
        "other_without_person_pct": (other_without_person_ticks / total_ticks * 100.0) if total_ticks else None,
        "other_without_person_ticks": other_without_person_ticks,
        "speed_thresholds_px_s": [round(q1, 1), round(q2, 1)],
        "buckets": {k: {"n": len(v), "p50": _percentile(v, 0.5), "p95": _percentile(v, 0.95)}
                    for k, v in buckets.items()},
        "n_samples": len(samples),
    }


# ── Part D: 출력 ────────────────────────────────────────────────────────────
def _fmt(v: float | None, nd: int = 1) -> str:
    return "—" if v is None else f"{v:.{nd}f}"


def _scenario_table(scenario_results: dict[str, dict[str, Any]]) -> str:
    lines = [
        "| 시나리오 | 느림 p50/p95 | 중간 p50/p95 | 빠름 p50/p95 | 정지프레임% | 겹침%(IoU≥0.10) | person없이뜬타클래스% |",
        "|---|---|---|---|---|---|---|",
    ]
    for sc in SCENARIOS:
        m = scenario_results[sc["name"]]
        b = m["buckets"]
        lines.append(
            f"| {sc['label']} "
            f"| {_fmt(b['느림']['p50'])}/{_fmt(b['느림']['p95'])} "
            f"| {_fmt(b['중간']['p50'])}/{_fmt(b['중간']['p95'])} "
            f"| {_fmt(b['빠름']['p50'])}/{_fmt(b['빠름']['p95'])} "
            f"| {_fmt(m['freeze_pct'])} "
            f"| {_fmt(m['overlap_pct'])} "
            f"| {_fmt(m['other_without_person_pct'])} |"
        )
    return "\n".join(lines)


def _write_report(args: argparse.Namespace, video: Path, detectors: list[str],
                   frames: list[dict[str, Any]], fps: float, detect_dt: float,
                   stab: dict[str, Any], speed_thresholds: tuple[float, float],
                   scenario_results: dict[str, dict[str, Any]]) -> Path:
    n_det = sum(len(f["dets"]) for f in frames)
    n_person = sum(1 for f in frames for d in f["dets"] if d["cls"] == "person")
    other_classes = sorted({d["cls"] for f in frames for d in f["dets"] if d["cls"] != "person"})
    from datetime import datetime
    stamp = datetime.now().strftime("%Y-%m-%d")
    L = [
        f"# 박스 품질 측정 — {args.tag} ({stamp})",
        "",
        f"> 입력 `{video}` · {len(frames)}프레임 @ {fps:.1f}fps · 검출기 `{','.join(detectors)}` "
        f"· 검출재생 {detect_dt:.1f}s(guard.detect, imgsz={args.imgsz or '기본'} conf={args.conf or '기본'})",
        "",
        "## 방법론(요약)",
        "- **Part A(검출재생)**: `guard.detect()` 를 영상 프레임순으로 그대로 호출(vision_loader+build_agents, "
        "main.py/FastAPI 불필요). 검출/추적 로직 무수정.",
        "- **Part B(표시재생)**: 검출 시퀀스에 지연을 주입해 `static/vigent-box-display.js`(BoxTracker, 미수정)를 "
        "Node 로 그대로 구동, rAF 60fps 시뮬레이션의 매 렌더틱 표시박스를 그대로 사용. 표시 로직 무수정.",
        "- **지상진실(GT) 정의**: 캡처 프레임 사이 선형보간(캡처 자체가 유일한 실측 위치). 이 지표는 "
        "**검출기 정확도가 아니라 표시 재구성 충실도**를 잰다(검출기 자체 정확도는 benchmarks/EVAL.md 소관).",
        "- **속도구간(느림/중간/빠름)**: 검출 스트림(GT) 자체의 구간속도(px/s) 33/66분위로 한 번만 분류해 "
        f"**전 시나리오에 동일 기준 적용**(시나리오마다 따로 계산하면 지연별 비교가 어긋난다). "
        f"이번 실행 경계값 = 느림≤{speed_thresholds[0]:.1f} · 중간≤{speed_thresholds[1]:.1f} · 빠름>{speed_thresholds[1]:.1f} (px/s).",
        f"- **겹침(유령) 판정 임계**: IoU≥{OVERLAP_IOU_THRESHOLD}(BoxTracker 자체 dedup 임계 0.40보다 낮게 잡아 "
        "dedup 사각지대의 잔여 겹침을 포착).",
        "- **주의(정직 고지)**: 이 실행 환경엔 ppe/forklift/fire_smoke 파인튜닝 가중치가 없어 "
        "`--detectors person` 만 사용했다. person 슬롯 자체가 COCO 80종 범용 검출(guard.py 기본 동작)이라 "
        f"person 외 클래스가 섞여 나온다(이번 영상 관측: {', '.join(other_classes) if other_classes else '없음'}). "
        "'person 없이 뜬 타클래스' 지표는 이 잡음을 이용해 측정했으나, **PPE 전용 유령 지표는 이 환경에서 "
        "구조적으로 미측정**이다(COCO 폴백엔 PPE 클래스 자체가 없음 — 가중치 있는 환경에서 재실행 필요).",
        "",
        "## 검출 현황",
        f"- 총 검출 {n_det}개(person {n_person}개, 기타 {n_det - n_person}개: "
        f"{', '.join(other_classes) if other_classes else '없음'})",
        f"- **트랙 안정성**(지연 시나리오와 무관 — 검출 스트림 자체 속성): person 고유 tid **{stab['unique_tids']}개** "
        f"· tid 교체 **{stab['switches']}회**",
        "",
        "## 지연 민감도 — 시나리오별 지표",
        "",
        _scenario_table(scenario_results),
        "",
        "## 해석",
    ]
    ideal = scenario_results["ideal"]
    worst = scenario_results["mac_real"]

    def _delta(key: str, sub: str | None = None) -> str:
        def get(d: dict[str, Any]) -> float | None:
            return d["buckets"][sub][key] if sub else d[key]
        a, b = get(ideal), get(worst)
        if a is None or b is None:
            return "미측정"
        return f"{a:.1f} → {b:.1f}"

    L += [
        f"- 표시오차(빠름 p95): {_delta('p95', '빠름')} (이상적 → 맥 실사용)",
        f"- 정지프레임%: {_delta('freeze_pct')} (이상적 → 맥 실사용)",
        f"- 겹침%: {_delta('overlap_pct')} (이상적 → 맥 실사용)",
        "- **표시 로직 문제 vs 검출 지연 문제 분리**: `ideal`(지연 0) 시나리오에서도 남아있는 오차/정지프레임은 "
        "표시 스택 자체(One-Euro 평활 지연·페이드·dedup)에 내재한 값이다. `ideal`→`d600`→`mac_real` 로 갈수록 "
        "악화되는 폭이 곧 **검출 지연이 얹는 몫**이다. 위 표에서 두 성분을 직접 비교할 것.",
        "",
    ]
    out_path = Path(args.report_dir) / f"box_quality_{args.tag}.md"
    out_path.write_text("\n".join(L), encoding="utf-8")
    return out_path


def main() -> None:
    a = _args()
    detectors = [d.strip() for d in a.detectors.split(",") if d.strip()]
    video = Path(a.video)
    track_key = f"{a.track_key_prefix}:{a.tag}"

    print(f"[A] 검출 재생: {video} (detectors={detectors})")
    frames, fps, detect_dt = replay_detections(video, detectors, track_key, a.imgsz, a.conf, a.max_frames)
    n_det = sum(len(f["dets"]) for f in frames)
    print(f"    {len(frames)}프레임 @ {fps:.1f}fps · 검출 총 {n_det}개 · {detect_dt:.1f}s")

    stab = track_stability(frames, cls="person")
    print(f"    person 고유tid {stab['unique_tids']}개 · tid교체 {stab['switches']}회")

    speed_thresholds = global_speed_thresholds(frames)
    print(f"    속도구간 경계(px/s, 전 시나리오 공통): 느림≤{speed_thresholds[0]:.1f} "
          f"중간≤{speed_thresholds[1]:.1f} 빠름>{speed_thresholds[1]:.1f}")

    scenario_results: dict[str, dict[str, Any]] = {}
    for sc in SCENARIOS:
        print(f"[B] 표시 재생: {sc['label']}")
        vis_ticks = run_display_scenario(frames, sc, a.node_bin, a.exclude_class, a.seed)
        print(f"[C] 지표 산출: {sc['label']} ({len(vis_ticks)}틱)")
        scenario_results[sc["name"]] = compute_metrics(frames, vis_ticks, speed_thresholds)

    print()
    print(f"=== {a.tag} — 지연 민감도 ===")
    print(_scenario_table(scenario_results))

    out_path = _write_report(a, video, detectors, frames, fps, detect_dt, stab, speed_thresholds, scenario_results)
    print(f"\n[D] 리포트 저장: {out_path}")


if __name__ == "__main__":
    main()
