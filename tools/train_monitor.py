#!/usr/bin/env python3
"""VIGENT PPE 학습 진행상황 모니터 — 3초마다 갱신.
실행:  python3 tools/train_monitor.py
종료:  Ctrl+C
"""
import csv, os, time, sys

RUN = os.path.expanduser("~/Desktop/VIGENT/runs/ppe_train/merged_v1")
CSV = os.path.join(RUN, "results.csv")
ARGS = os.path.join(RUN, "args.yaml")
REFRESH = 3
PID = 40209  # train_merged.py


def total_epochs():
    try:
        for line in open(ARGS):
            if line.strip().startswith("epochs:"):
                return int(line.split(":")[1])
    except Exception:
        pass
    return 70


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_rows():
    try:
        with open(CSV) as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def bar(frac, width=34):
    fill = int(frac * width)
    return "█" * fill + "░" * (width - fill)


def fmt_hms(s):
    s = int(s)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}시간 {m}분" if h else f"{m}분 {s}초"


def render():
    rows = read_rows()
    total = total_epochs()
    os.system("clear")
    print("=" * 56)
    print("  VIGENT PPE 객체인식 학습 진행상황 (3초마다 갱신)")
    print("=" * 56)
    if not rows:
        print("\n  아직 첫 epoch 결과 대기 중...\n")
        return
    last = rows[-1]
    done = int(float(last["epoch"]))
    frac = done / total
    elapsed = float(last["time"])
    per = elapsed / done if done else 0
    remain = per * (total - done)
    mAP50 = float(last["metrics/mAP50(B)"])
    mAP5095 = float(last["metrics/mAP50-95(B)"])
    prec = float(last["metrics/precision(B)"])
    rec = float(last["metrics/recall(B)"])
    # best mAP50 so far
    best = max(float(r["metrics/mAP50(B)"]) for r in rows)
    best_ep = max(rows, key=lambda r: float(r["metrics/mAP50(B)"]))["epoch"]

    state = "🟢 학습 중" if alive(PID) else "🔴 종료됨(프로세스 없음)"
    print(f"\n  상태: {state}    경과 {fmt_hms(elapsed)} · epoch당 ~{per:.0f}초")
    print(f"\n  진행  [{bar(frac)}] {done}/{total} ({frac*100:.0f}%)")
    print(f"  남은시간 약 {fmt_hms(remain)}\n")
    print("  ── 최신 성능 (epoch %d) ──" % done)
    print(f"   mAP50      {mAP50:.3f}     mAP50-95   {mAP5095:.3f}")
    print(f"   precision  {prec:.3f}     recall     {rec:.3f}")
    print(f"   최고 mAP50  {best:.3f} (epoch {int(float(best_ep))})\n")
    # mini trend (last 5)
    print("  ── mAP50 추세(최근) ──")
    for r in rows[-6:]:
        e = int(float(r["epoch"]))
        m = float(r["metrics/mAP50(B)"])
        print(f"   ep{e:>2}  {bar(m, 28)} {m:.3f}")
    print()


def main():
    try:
        while True:
            render()
            if not alive(PID):
                print("  학습 프로세스가 종료되었습니다. best.pt 확인하세요.")
                break
            time.sleep(REFRESH)
    except KeyboardInterrupt:
        print("\n모니터 종료.")


if __name__ == "__main__":
    main()
