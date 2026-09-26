"""510 VS_03(2,543장)·507 개구부 샘플(720장) 에 forklift_rfdetr_v1 을 돌려 **이미지 단위** 존재 판정률을 잰다 — 현장(forklift_field_rerun.py) 과 같은 지표.
양성 = 지게차 GT 박스가 있는 이미지, 음성 = 없는 이미지. 각 임계에서 '박스 1개 이상' 비율(양성=재현율, 음성=오경보율) + 양성에서 GT 와 IoU≥0.5 인 박스 비율.
출력: D:/vigent_original/audit/forklift_aihub_imagelevel_20260926.json"""
import json
import sys
import time
from pathlib import Path

import torch
from PIL import Image

sys.path.insert(0, r'D:\vigent_original\scripts\eval'); sys.path.insert(0, r'D:\vigent_original\scripts\data')
from aihub_smoke_eval import gt_from_aihub
from rfdetr import RFDETRNano

OUT = r'D:\vigent_original\audit\forklift_aihub_imagelevel_20260926.json'
THRS = [0.002, 0.01, 0.05, 0.1, 0.3, 0.5]
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
fk = RFDETRNano(pretrain_weights=r'D:\vigent_original\vigent-core\weights\forklift_rfdetr_v1.pth', resolution=384, device=dev)
try: fk.optimize_for_inference()
except Exception: pass

def iou(a, b):
    iw = max(0, min(a[2], b[2]) - max(a[0], b[0])); ih = max(0, min(a[3], b[3]) - max(a[1], b[1])); inter = iw * ih
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0

def run(name, dataset, labels, images):
    items = gt_from_aihub(dataset, Path(labels), Path(images), None)
    pos, neg, agree, t0 = [], [], [], time.time()
    for i, (img, boxes) in enumerate(items, 1):
        gts = [b for c, b, _ in boxes if c == 'forklift']
        det = fk.predict(Image.open(img).convert('RGB'), threshold=0.001)
        mc = max([float(c) for c in det.confidence], default=0.0)
        if gts:
            pos.append(mc)
            best = 0.0
            for box, c in zip(det.xyxy, det.confidence):
                bx = [float(v) for v in box]
                if any(iou(bx, g) >= 0.5 for g in gts): best = max(best, float(c))
            agree.append(best)
        else: neg.append(mc)
        if i % 500 == 0: print(f'  {name} {i}/{len(items)} {time.time()-t0:.0f}s', flush=True)
    rate = lambda xs: {str(t): round(sum(x >= t for x in xs) / len(xs) * 100, 1) for t in THRS} if xs else None
    r = {'images': len(items), 'pos_images': len(pos), 'neg_images': len(neg),
         'pos_detect_rate': rate(pos), 'pos_agree_iou50_rate': rate(agree), 'neg_false_alarm_rate': rate(neg),
         'pos_maxconf_p50': round(sorted(pos)[len(pos) // 2], 4) if pos else None,
         'neg_maxconf_p50': round(sorted(neg)[len(neg) // 2], 4) if neg else None,
         'neg_maxconf_p90': round(sorted(neg)[int(len(neg) * 0.9)], 4) if neg else None, 'elapsed_s': round(time.time() - t0, 1)}
    print(name, json.dumps(r, ensure_ascii=False), flush=True); return r

res = {'date': time.strftime('%Y-%m-%d %H:%M'), 'device': dev, 'thresholds': THRS, 'model': 'forklift_rfdetr_v1 res384 predict thr0.001',
       'caveat': 'AI Hub 표본 기준·운용 조건 아님·기준선 아님. 이미지 단위 존재 판정(현장 재측정과 같은 지표).', 'sets': {}}
res['sets']['510_VS03'] = run('510_VS03', '510', r'D:\vigent_private_data\aihub\_inspect\510_all', r'D:\vigent_private_data\aihub\_inspect\510_src_VS03')
res['sets']['507_opening_sample'] = run('507_opening_sample', '507', r'D:\vigent_private_data\aihub\docs_507', r'D:\vigent_private_data\aihub\docs_507')
json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1); print('saved', OUT)
