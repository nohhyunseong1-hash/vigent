#!/usr/bin/env python3
"""[현장 녹화] 장면(시나리오)별로 **바운딩박스 오버레이 영상 + 스틸 + 검출 기록**을 남긴다.

용도(2026-08-27 학원 방문): 지게차·PPE·구역 시나리오 7장면을 눈으로 확인할 증거로.
  · 영상  — 스냅샷(640x360, 얼굴 비식별화 적용됨)에 워커 검출 박스를 그려 mp4 저장
            → "박스가 사람·지게차를 따라오는가"를 재생으로 확인
  · 스틸  — 5초마다 오버레이 JPG 1장 → "검출이 잘 되는가"를 낱장으로 확인
  · 기록  — 프레임마다 detections/person_count/signals/fired 를 JSONL 로
            → 경보 판정(fired)의 사후 증거. 텔레그램 300초 억제와 무관하게 남는다.

원본 고화질 영상은 이 스크립트 몫이 아니다 — C200 SD카드 녹화(절차서 5단계 회수)가 담당.
여기 영상은 워커가 실제로 판정한 그대로(2fps 스냅샷)를 보는 검증용이다.

사용:
  python scripts/field_recorder.py --cam cam_academy --scene 01_지게차정지 --minutes 5
      → runs/field_<날짜>/<scene>/overlay.mp4 · still_*.jpg · dets.jsonl · summary.md
  조기 종료: 같은 폴더에 STOP 파일을 만들면 다음 프레임에서 곱게 닫는다.
      (프로세스 kill 은 금지 — mp4 가 깨진다)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8010"

# 라벨별 박스 색(BGR) — 위반(빨강)·사람(초록)·장비(파랑)·착용(청록)이 한눈에 갈리게.
COLORS = {
    "person": (0, 200, 0),
    "forklift": (255, 120, 0),
    "hardhat": (200, 200, 0),
    "safety-vest": (200, 200, 0),
    "no-hardhat": (0, 0, 255),
    "no-safety-vest": (0, 0, 255),
    "no-mask": (0, 100, 255),
}


def token() -> str:
    for ln in (ROOT / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.strip().startswith("VIGENT_API_TOKEN"):
            return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def api(path: str, tok: str, raw: bool = False):
    req = urllib.request.Request(BASE + path)
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read()
    return data if raw else json.loads(data.decode("utf-8"))


def main() -> int:
    import cv2
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="cam_academy")
    ap.add_argument("--scene", required=True, help="장면 이름(폴더명이 된다) 예: 01_지게차정지")
    ap.add_argument("--minutes", type=float, default=5.0, help="최대 길이(STOP 파일로 조기 종료 가능)")
    ap.add_argument("--interval", type=float, default=0.5, help="캡처 간격 초(워커 2fps 에 맞춤)")
    a = ap.parse_args()

    tok = token()
    day = time.strftime("%Y%m%d")
    out = ROOT / "runs" / f"field_{day}" / a.scene
    out.mkdir(parents=True, exist_ok=True)
    stop_file = out / "STOP"
    if stop_file.exists():
        stop_file.unlink()

    vw = None
    jl = (out / "dets.jsonl").open("a", encoding="utf-8")
    n = n_fail = still_i = 0
    label_counts: dict[str, int] = {}
    fired_seen: dict[str, int] = {}
    pc_max = 0
    t0 = time.time()
    last_still = 0.0
    print(f"[녹화 시작] {a.scene} — 최대 {a.minutes:.0f}분 · 종료: {stop_file} 생성")

    while time.time() - t0 < a.minutes * 60:
        tick = time.time()
        if stop_file.exists():
            print("  STOP 파일 감지 — 곱게 종료")
            break
        try:
            jpg = api(f"/cameras/{a.cam}/snapshot", tok, raw=True)
            det = api(f"/cameras/{a.cam}/detections", tok)
        except Exception as ex:
            n_fail += 1
            if n_fail in (1, 10) or n_fail % 60 == 0:
                print(f"  캡처 실패 {n_fail}회: {type(ex).__name__}")
            time.sleep(a.interval)
            continue

        fr = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if fr is None:
            n_fail += 1
            time.sleep(a.interval)
            continue
        h, w = fr.shape[:2]

        for d in det.get("detections") or []:
            lb = str(d.get("class") or d.get("label") or "?")
            conf = float(d.get("score") or 0)   # /detections 응답 키는 score 다(2026-08-27 실측)
            bb = d.get("bbox") or [0, 0, 0, 0]
            x1, y1, x2, y2 = int(bb[0] * w), int(bb[1] * h), int(bb[2] * w), int(bb[3] * h)
            col = COLORS.get(lb.lower(), (180, 180, 180))
            cv2.rectangle(fr, (x1, y1), (x2, y2), col, 2)
            cv2.putText(fr, f"{lb} {conf:.2f}", (x1, max(12, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1, cv2.LINE_AA)
            label_counts[lb] = label_counts.get(lb, 0) + 1

        pc = int(det.get("person_count") or 0)
        pc_max = max(pc_max, pc)
        fired = det.get("fired") or []
        for f in fired:
            # fired 항목은 문자열(규칙명)로도 온다 — 2026-08-27 장면2에서 실측(dict 가정이 크래시)
            key = str(f.get("rule") or f) if isinstance(f, dict) else str(f)
            fired_seen[key] = fired_seen.get(key, 0) + 1
        head = f"{a.scene}  {time.strftime('%H:%M:%S')}  person={pc}"
        cv2.putText(fr, head, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        if fired:
            cv2.putText(fr, "FIRED: " + ",".join((str(f.get("rule") or f) if isinstance(f, dict) else str(f)) for f in fired)[:60],
                        (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

        if vw is None:
            vw = cv2.VideoWriter(str(out / "overlay.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), 1.0, (w, h))  # 실효 캡처 ~0.8fps(왕복 1.2s) — 1.0 이 실시간에 가깝다
        vw.write(fr)
        jl.write(json.dumps({"t": round(tick * 1000), "person_count": pc,
                             "fired": fired, "signals": det.get("signals"),
                             "detections": det.get("detections")}, ensure_ascii=False) + "\n")
        n += 1
        if tick - last_still >= 5.0:
            still_i += 1
            # cv2.imwrite 는 Windows 한글 경로에서 **조용히 실패**한다(2026-08-27 스모크에서 실측)
            #   → imencode 로 만들고 파이썬이 쓴다.
            ok_j, buf = cv2.imencode(".jpg", fr)
            if ok_j:
                (out / f"still_{still_i:03d}.jpg").write_bytes(buf.tobytes())
            last_still = tick
        if n % 40 == 0:
            print(f"  +{tick - t0:4.0f}s  프레임 {n} · person 최대 {pc_max} · fired {sum(fired_seen.values())}건")
        time.sleep(max(0.0, a.interval - (time.time() - tick)))

    if vw is not None:
        vw.release()
    jl.close()
    dur = time.time() - t0
    lines = [f"# 장면 {a.scene} — {time.strftime('%Y-%m-%d %H:%M')}",
             f"- 길이 {dur / 60:.1f}분 · 프레임 {n} (실효 {n / max(dur, 1):.2f}fps) · 캡처실패 {n_fail}",
             f"- person 최대 동시 {pc_max}명",
             "- 라벨 관측(프레임 합): " + (", ".join(f"{k} {v}" for k, v in
                                                   sorted(label_counts.items(), key=lambda x: -x[1])) or "없음"),
             "- 경보 발화(fired): " + (", ".join(f"{k} {v}건" for k, v in fired_seen.items()) or "없음")]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"[저장] {out}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
