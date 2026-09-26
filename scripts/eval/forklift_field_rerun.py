"""8/27 학원 현장 overlay.mp4 에 현재 forklift_rfdetr_v1(RF-DETR) 을 돌려 장면별 검출률을 잰다.
기준: dets.jsonl(현장 당시 학원 프로파일 YOLO boda_ax @0.50 의 signals.forklift_present) 과 같은 프레임 수로 균등 추림.
★단서: overlay.mp4 는 박스·글자가 그려진 표시용 영상(원본 미보존) — 그림이 추론에 영향 줄 수 있다. 정답은 장면 대본(프레임 라벨 아님).
출력: D:/vigent_original/audit/forklift_field_rerun_20260926.json"""
import json
import os
import sys
import time

import cv2
import torch
from PIL import Image

sys.path.insert(0, r'D:\vigent_original\scripts\eval')
from rfdetr import RFDETRNano
from rfdetr.assets.coco_classes import COCO_CLASSES

ROOT = r'D:\vigent_field\20260827\field_20260827'
OUT = r'D:\vigent_original\audit\forklift_field_rerun_20260926.json'
THRS = [0.002, 0.01, 0.05, 0.1, 0.3, 0.5]
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
fk = RFDETRNano(pretrain_weights=r'D:\vigent_original\vigent-core\weights\forklift_rfdetr_v1.pth', resolution=384, device=dev)
coco = RFDETRNano(resolution=384, device=dev)
for m in (fk, coco):
    try: m.optimize_for_inference()
    except Exception: pass
VEH = {'truck', 'car', 'bus', 'train'}
res = {'date': time.strftime('%Y-%m-%d %H:%M'), 'device': dev, 'thresholds': THRS,
       'caveat': 'overlay.mp4(박스가 그려진 표시용 영상, 원본 미보존) · 정답=장면 대본 · 기준 열은 현장 당시 boda_ax YOLO @0.50 의 forklift_present', 'scenes': {}}
tot = {'frames': 0, 'boda': 0, 'coco_veh': 0, **{f'rf_ge_{t}': 0 for t in THRS}}
for sc in sorted(os.listdir(ROOT)):
    d = os.path.join(ROOT, sc)
    if not os.path.isdir(d): continue
    rows = [json.loads(l) for l in open(os.path.join(d, 'dets.jsonl'), encoding='utf-8')]
    boda = [bool((r.get('signals') or {}).get('forklift_present')) for r in rows]
    cap = cv2.VideoCapture(os.path.join(d, 'overlay.mp4'))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS)
    k = len(rows); idx = [int(i * n / k) for i in range(k)] if n and k else []
    maxconf, veh, agree, t0 = [], [], [], time.time()   # agree = boda 지게차 박스와 IoU≥0.5 인 RF 박스의 최대 conf(boda 박스 없으면 None)
    for j, fi in enumerate(idx):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, fr = cap.read()
        if not ok: maxconf.append(0.0); veh.append(False); agree.append(None); continue
        H, W = fr.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        det = fk.predict(pil, threshold=0.001)
        maxconf.append(max([float(c) for c in det.confidence], default=0.0))
        bb = [d['bbox'] for d in rows[j].get('detections', []) if d.get('class') == 'forklift' and not d.get('stale')]
        if bb:
            best = 0.0
            for box, c in zip(det.xyxy, det.confidence):
                x1, y1, x2, y2 = [float(v) for v in box]
                for gx1, gy1, gx2, gy2 in bb:
                    gx1, gx2, gy1, gy2 = gx1 * W, gx2 * W, gy1 * H, gy2 * H
                    iw = max(0, min(x2, gx2) - max(x1, gx1)); ih = max(0, min(y2, gy2) - max(y1, gy1))
                    inter = iw * ih; union = (x2 - x1) * (y2 - y1) + (gx2 - gx1) * (gy2 - gy1) - inter
                    if union > 0 and inter / union >= 0.5: best = max(best, float(c))
            agree.append(best)
        else: agree.append(None)
        dc = coco.predict(pil, threshold=0.40)
        veh.append(any(COCO_CLASSES.get(int(c)) in VEH for c in dc.class_id))
    cap.release()
    ag = [a for a in agree if a is not None]
    s = {'dets_rows': k, 'overlay_frames': n, 'overlay_fps': round(fps, 2), 'sampled': len(idx),
         'boda_forklift_present': sum(boda), 'boda_rate': round(sum(boda) / k * 100, 1) if k else None,
         'coco_vehicle_present': sum(veh), 'coco_rate': round(sum(veh) / len(veh) * 100, 1) if veh else None,
         'rf_maxconf_p50': round(sorted(maxconf)[len(maxconf) // 2], 4) if maxconf else None,
         'rf_maxconf_p90': round(sorted(maxconf)[int(len(maxconf) * 0.9)], 4) if maxconf else None,
         'rf_detect_rate': {str(t): round(sum(c >= t for c in maxconf) / len(maxconf) * 100, 1) for t in THRS} if maxconf else None,
         'boda_box_frames': len(ag),
         'rf_agree_iou50_rate': {str(t): round(sum(a >= t for a in ag) / len(ag) * 100, 1) for t in THRS} if ag else None,
         'elapsed_s': round(time.time() - t0, 1)}
    res['scenes'][sc] = s
    tot['frames'] += k; tot['boda'] += sum(boda); tot['coco_veh'] += sum(veh); tot['boda_box_frames'] = tot.get('boda_box_frames', 0) + len(ag)
    for t in THRS:
        tot[f'rf_ge_{t}'] += sum(c >= t for c in maxconf); tot[f'ag_ge_{t}'] = tot.get(f'ag_ge_{t}', 0) + sum(a >= t for a in ag)
    print(sc, json.dumps(s, ensure_ascii=False), flush=True)
res['total'] = {**tot, 'boda_rate': round(tot['boda'] / tot['frames'] * 100, 1), 'coco_rate': round(tot['coco_veh'] / tot['frames'] * 100, 1),
                'rf_detect_rate': {str(t): round(tot[f'rf_ge_{t}'] / tot['frames'] * 100, 1) for t in THRS},
                'rf_agree_iou50_rate': {str(t): round(tot[f'ag_ge_{t}'] / tot['boda_box_frames'] * 100, 1) for t in THRS}}
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('TOTAL', json.dumps(res['total'], ensure_ascii=False)); print('saved', OUT)
