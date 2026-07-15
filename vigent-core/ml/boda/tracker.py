import math
import time
from typing import Dict, List


def iou(boxA: List[float], boxB: List[float]) -> float:
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interW = max(0.0, xB - xA)
    interH = max(0.0, yB - yA)
    interArea = interW * interH
    boxAArea = max(0.0, boxA[2] - boxA[0]) * max(0.0, boxA[3] - boxA[1])
    boxBArea = max(0.0, boxB[2] - boxB[0]) * max(0.0, boxB[3] - boxB[1])
    denom = boxAArea + boxBArea - interArea
    if denom <= 0:
        return 0.0
    return interArea / denom


class Track:
    def __init__(self, track_id: int, bbox: List[float]):
        # bbox = [x1,y1,x2,y2]
        self.track_id = track_id
        self.bbox = bbox
        self.last_seen = time.time()
        self.start_time = self.last_seen
        self.hits = 1
        # velocity on [dx,dy,dw,d h] approximated per second
        self.vx = 0.0
        self.vy = 0.0
        self.vw = 0.0
        self.vh = 0.0

    def predict(self, dt: float = 0.5) -> List[float]:
        x1, y1, x2, y2 = self.bbox
        w = max(1e-3, x2 - x1)
        h = max(1e-3, y2 - y1)
        cx = x1 + w/2.0
        cy = y1 + h/2.0
        # predict center with simple linear motion
        pcx = cx + self.vx * dt
        pcy = cy + self.vy * dt
        pw = max(1e-3, w + self.vw * dt)
        ph = max(1e-3, h + self.vh * dt)
        px1 = pcx - pw/2.0
        py1 = pcy - ph/2.0
        px2 = pcx + pw/2.0
        py2 = pcy + ph/2.0
        return [px1, py1, px2, py2]

    def update(self, bbox: List[float]):
        now = time.time()
        dt = max(1e-3, now - self.last_seen)
        x1, y1, x2, y2 = self.bbox
        w = max(1e-3, x2 - x1)
        h = max(1e-3, y2 - y1)
        cx = x1 + w / 2.0
        cy = y1 + h / 2.0

        nx1, ny1, nx2, ny2 = bbox
        nw = max(1e-3, nx2 - nx1)
        nh = max(1e-3, ny2 - ny1)
        ncx = nx1 + nw / 2.0
        ncy = ny1 + nh / 2.0

        # instantaneous velocity
        ivx = (ncx - cx) / dt
        ivy = (ncy - cy) / dt
        ivw = (nw - w) / dt
        ivh = (nh - h) / dt

        # exponential smoothing for velocity
        alpha = 0.2
        self.vx = (1 - alpha) * self.vx + alpha * ivx
        self.vy = (1 - alpha) * self.vy + alpha * ivy
        self.vw = (1 - alpha) * self.vw + alpha * ivw
        self.vh = (1 - alpha) * self.vh + alpha * ivh

        self.bbox = bbox
        self.last_seen = now
        self.hits += 1

    def dwell(self) -> float:
        return time.time() - self.start_time


class SimpleTracker:
    """Improved simple tracker with basic linear prediction and greedy matching.
    Keeps the API: update(detections) -> List[detections with track_id, dwell_sec]
    """
    def __init__(self, iou_threshold: float = 0.4, max_age_sec: float = 2.0, predict_dt: float = 0.5):
        self.iou_threshold = iou_threshold
        self.max_age_sec = max_age_sec
        self.predict_dt = predict_dt
        self.tracks: List[Track] = []
        self._next_id = 1

    def _remove_stale(self):
        now = time.time()
        self.tracks = [t for t in self.tracks if (now - t.last_seen) <= self.max_age_sec]

    def update(self, detections: List[Dict]) -> List[Dict]:
        assigned = []
        self._remove_stale()
        if not detections:
            return []

        # prepare predictions
        preds = [(tr, tr.predict(self.predict_dt)) for tr in self.tracks]

        unmatched_tracks = set([tr.track_id for tr in self.tracks])
        used_dets = set()

        # greedy match: for each detection, find best predicted track by IoU
        for di, det in enumerate(detections):
            best_tr = None
            best_iou = 0.0
            for tr, pred_box in preds:
                if tr.track_id not in unmatched_tracks:
                    continue
                val = iou(det['box'], pred_box)
                if val > best_iou:
                    best_iou = val
                    best_tr = tr
            if best_tr is not None and best_iou >= self.iou_threshold:
                best_tr.update(det['box'])
                det['track_id'] = best_tr.track_id
                det['dwell_sec'] = best_tr.dwell()
                det['velocity'] = math.hypot(best_tr.vx, best_tr.vy)
                assigned.append(det)
                unmatched_tracks.remove(best_tr.track_id)
                used_dets.add(di)

        # remaining detections -> new tracks
        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            tr = Track(self._next_id, det['box'])
            self._next_id += 1
            self.tracks.append(tr)
            det['track_id'] = tr.track_id
            det['dwell_sec'] = tr.dwell()
            det['velocity'] = math.hypot(tr.vx, tr.vy)
            assigned.append(det)

        self._remove_stale()
        return assigned
