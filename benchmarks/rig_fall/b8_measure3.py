import sys, os, glob, time, json; sys.path.insert(0,"vigent-core")
os.environ["VIGENT_ALLOW_FALLBACK"]="1"
import cv2, numpy as np
from PIL import Image
SC="/private/tmp/claude-501/-Users-nohyeonseong-Desktop-VIGENT/45405339-172f-46c1-b3aa-59834ee29253/scratchpad"
INC=sorted(glob.glob(f"{SC}/inc37/*.jpg")); NOINC=sorted(glob.glob(f"{SC}/noinc/*.jpg"))
ROI=(0.27,0.60,0.42,0.80)
def in_roi(nb):
    cx,cy=(nb[0]+nb[2])/2,(nb[1]+nb[3])/2
    return ROI[0]<=cx<=ROI[2] and ROI[1]<=cy<=ROI[3]
res={"frames":{"inc":len(INC),"noinc":len(NOINC)}}

# ── RF-DETR 로드 ──
import rfdetr_service
svc=rfdetr_service.rfdetr; svc._ensure()
from rfdetr.util.coco_classes import COCO_CLASSES
def rfdetr_persons(fr, thr):
    h,w=fr.shape[:2]
    det=svc._model.predict(Image.fromarray(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB)),threshold=thr)
    o=[]
    for i in range(len(det)):
        if COCO_CLASSES[det.class_id[i]]!="person": continue
        x1,y1,x2,y2=(float(v) for v in det.xyxy[i]); o.append(([x1/w,y1/h,x2/w,y2/h],float(det.confidence[i])))
    return o

# ① 오탐율: 무사고 t0~35, 저conf 박스가 ROI/전체에 몇 개(정밀도)
fp={"thr0.4_roi":0,"thr0.05_roi":0,"thr0.02_roi":0,"thr0.05_total":0,"thr0.4_total":0}
for fp_img in NOINC:
    fr=cv2.imread(fp_img); ps=rfdetr_persons(fr,0.02)
    for b,c in ps:
        if c>=0.4: fp["thr0.4_total"]+=1;  fp["thr0.4_roi"]+= in_roi(b)
        if c>=0.05: fp["thr0.05_total"]+=1; fp["thr0.05_roi"]+= in_roi(b)
        if c>=0.02: fp["thr0.02_roi"]+= in_roi(b)
res["FP_noincident"]={**fp,"n_frames":len(NOINC),
    "note":"ROI=쓰러진작업자 위치. 무사고구간이라 ROI 저conf 박스=확정레이어가 걸러야 할 후보"}

# ② 타일링: 사고구간, 2x2+overlap 로 쓰러진작업자 best conf 가 0.4 넘나 + 시간배수
def tiled_persons(fr, thr=0.02, nx=2, ny=2, ov=0.15):
    H,W=fr.shape[:2]; out=[]
    tw,th=int(W/nx),int(H/ny)
    for iy in range(ny):
        for ix in range(nx):
            x0=max(0,int(ix*tw-ov*tw)); y0=max(0,int(iy*th-ov*th))
            x1=min(W,int((ix+1)*tw+ov*tw)); y1=min(H,int((iy+1)*th+ov*th))
            tile=fr[y0:y1,x0:x1]
            det=svc._model.predict(Image.fromarray(cv2.cvtColor(tile,cv2.COLOR_BGR2RGB)),threshold=thr)
            for i in range(len(det)):
                if COCO_CLASSES[det.class_id[i]]!="person": continue
                bx1,by1,bx2,by2=(float(v) for v in det.xyxy[i])
                out.append(([(x0+bx1)/W,(y0+by1)/H,(x0+bx2)/W,(y0+by2)/H],float(det.confidence[i])))
    return out
tile_hit=0; tile_confs=[]; over04=0
for fp_img in INC:
    fr=cv2.imread(fp_img); ps=tiled_persons(fr)
    roi=[c for b,c in ps if in_roi(b)]
    if roi: tile_hit+=1; tile_confs.append(round(max(roi),3)); over04+= (max(roi)>=0.4)
# 시간배수(5프레임 평균)
sample=INC[:5]
t=time.time(); [rfdetr_persons(cv2.imread(p),0.05) for p in sample]; t_full=(time.time()-t)/len(sample)
t=time.time(); [tiled_persons(cv2.imread(p)) for p in sample]; t_tile=(time.time()-t)/len(sample)
res["tiling_incident"]={"recall":f"{tile_hit}/{len(INC)}","best_confs":tile_confs,
    "frames_over_0.4":over04,"time_full_s":round(t_full,2),"time_tiled_s":round(t_tile,2),
    "time_multiplier":round(t_tile/max(t_full,1e-6),1)}

# ③ YOLO A/B: yolo11m, 사고구간, 쓰러진작업자 recall+conf
try:
    from ultralytics import YOLO
    ym=YOLO("vigent-core/weights/yolo11m.pt")
    yhit=0; yconfs=[]
    for fp_img in INC:
        fr=cv2.imread(fp_img); H,W=fr.shape[:2]
        r=ym(fr,conf=0.05,classes=[0],verbose=False)[0]
        roi=[]
        for b in r.boxes:
            x1,y1,x2,y2=(float(v) for v in b.xyxy[0]); nb=[x1/W,y1/H,x2/W,y2/H]
            if in_roi(nb): roi.append(float(b.conf[0]))
        if roi: yhit+=1; yconfs.append(round(max(roi),3))
    res["yolo11m_incident"]={"recall":f"{yhit}/{len(INC)}","best_confs":yconfs,
        "over_0.4":sum(1 for c in yconfs if c>=0.4)}
except Exception as e:
    res["yolo11m_incident"]={"error":f"{type(e).__name__}: {e}"}

open(f"{SC}/b8_measure3.json","w").write(json.dumps(res,ensure_ascii=False,indent=2))
print("DONE"); print(json.dumps(res,ensure_ascii=False,indent=2))
