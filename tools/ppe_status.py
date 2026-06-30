#!/usr/bin/env python3
"""PPE 학습 상태 한 줄 출력 (루프 폴링용, 읽기 전용).
출력 예: RUNNING|17|70|0.509|0.475|0.613|1.250
         DONE|70|70|...   (epoch==total)
         STOPPED|17|70|... (프로세스 종료됨)
"""
import os, csv

RUN = os.path.expanduser("~/Desktop/VIGENT/runs/ppe_train/merged_v1")
CSV = os.path.join(RUN, "results.csv")
PID = 40209
TOTAL = 70


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def last_row():
    try:
        with open(CSV) as f:
            rows = list(csv.reader(f))
        return rows[-1] if len(rows) > 1 else None
    except Exception:
        return None


r = last_row()
if not r:
    print("NODATA|0|%d|0|0|0|0" % TOTAL)
else:
    ep = int(float(r[0]))
    mAP50, recall, prec, box = float(r[7]), float(r[6]), float(r[5]), float(r[2])
    if ep >= TOTAL:
        state = "DONE"
    elif not alive(PID):
        state = "STOPPED"
    else:
        state = "RUNNING"
    print("%s|%d|%d|%.3f|%.3f|%.3f|%.3f" % (state, ep, TOTAL, mAP50, recall, prec, box))
