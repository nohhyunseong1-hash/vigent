import sys, cv2, glob, os, json; sys.path.insert(0,"vigent-core")
os.environ["VIGENT_ALLOW_FALLBACK"]="1"
import rfdetr_service
svc=rfdetr_service.rfdetr; svc._ensure()
from PIL import Image
from rfdetr.util.coco_classes import COCO_CLASSES
INC="/private/tmp/claude-501/-Users-nohyeonseong-Desktop-VIGENT/45405339-172f-46c1-b3aa-59834ee29253/scratchpad/incident"
ROI=(0.27,0.60,0.42,0.80)
def in_roi(nb):
    cx,cy=(nb[0]+nb[2])/2,(nb[1]+nb[3])/2
    return ROI[0]<=cx<=ROI[2] and ROI[1]<=cy<=ROI[3]
def persons(fr,thr):
    h,w=fr.shape[:2]
    det=svc._model.predict(Image.fromarray(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB)),threshold=thr)
    o=[]
    for i in range(len(det)):
        if COCO_CLASSES[det.class_id[i]]!="person": continue
        x1,y1,x2,y2=(float(v) for v in det.xyxy[i]); o.append(([x1/w,y1/h,x2/w,y2/h],float(det.confidence[i])))
    return o
res={}
for thr in (0.05,0.02):
    hit=tot=0; confs=[]
    for t in range(36,46):
        fp=f"{INC}/t{t}.jpg"
        if not os.path.exists(fp): continue
        fr=cv2.imread(fp); tot+=1
        roi=[(b,c) for b,c in persons(fr,thr) if in_roi(b)]
        if roi: hit+=1; confs.append(round(max(c for _,c in roi),3))
    res[thr]={"recall":f"{hit}/{tot}","confs":confs}
open(f"{INC}/lowthr_result.json","w").write(json.dumps(res,ensure_ascii=False,indent=2))
print("DONE", json.dumps(res,ensure_ascii=False))
