"""forklift_rfdetr_v1 의 최고 신뢰 박스가 어디에 찍히는지(개수·면적·중심·신뢰) — 지게차 없는 507 표본 · 현장 프레임 · 빈 화면/잡음."""
import glob
import json
import os
import statistics as st
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "scripts" / "eval")); sys.path.insert(0, str(_ROOT / "scripts" / "data"))
import cv2
import data_paths as _dp  # noqa: E402
import numpy as np
from PIL import Image
from rfdetr import RFDETRNano

fk = RFDETRNano(pretrain_weights=str(_ROOT / 'vigent-core' / 'weights' / 'forklift_rfdetr_v1.pth'), resolution=384, device='cuda')
out = {}
def stats(name, imgs):
    nb, area, cx, cy, top = [], [], [], [], []
    for im in imgs:
        W, H = im.size
        d = fk.predict(im, threshold=0.001); nb.append(len(d.confidence))
        if len(d.confidence):
            i = int(max(range(len(d.confidence)), key=lambda k: d.confidence[k])); x1, y1, x2, y2 = map(float, d.xyxy[i])
            area.append((x2 - x1) * (y2 - y1) / (W * H)); cx.append((x1 + x2) / 2 / W); cy.append((y1 + y2) / 2 / H); top.append(float(d.confidence[i]))
    q = lambda xs, p: round(sorted(xs)[min(len(xs) - 1, int(len(xs) * p))], 3)
    r = {'n': len(imgs), 'boxes_per_img_at_0.001_p50': st.median(nb), 'top_area_frac_p10_p50_p90': [q(area, .1), q(area, .5), q(area, .9)],
         'top_cx_p50': q(cx, .5), 'top_cy_p50': q(cy, .5), 'top_conf_p10_p50_p90': [q(top, .1), q(top, .5), q(top, .9)], 'top_conf_ge_0.5_rate': round(sum(t >= .5 for t in top) / len(top) * 100, 1)}
    out[name] = r; print(name, json.dumps(r), flush=True)
neg = sorted(glob.glob(str(_dp.media('aihub/docs_507') / '**' / '*.jpg'), recursive=True))[::12][:60]
stats('507_neg_no_forklift', [Image.open(p).convert('RGB') for p in neg])
root = str(_dp.field_root() / '20260827' / 'field_20260827')
fr = []
for sc in sorted(os.listdir(root)):
    p = os.path.join(root, sc, 'overlay.mp4')
    if not os.path.exists(p): continue
    cap = cv2.VideoCapture(p); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    for fi in range(0, n, max(1, n // 8)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi); ok, f = cap.read()
        if ok: fr.append(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
    cap.release()
print('field frames', len(fr), 'size', fr[0].size if fr else None)
stats('field_0827_overlay', fr)
rng = np.random.default_rng(0)
blank = [Image.fromarray(np.full((720, 1280, 3), v, np.uint8)) for v in (0, 128, 255)] + [Image.fromarray(rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)) for _ in range(3)]
stats('blank_and_noise', blank)
json.dump(out, open(_ROOT / 'audit' / 'forklift_box_geom_20260926.json', 'w', encoding='utf-8'), indent=1)
