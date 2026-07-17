import sys, os, glob, json, math; sys.path.insert(0,"vigent-core")
os.environ["VIGENT_ALLOW_FALLBACK"]="1"
import cv2, numpy as np
from PIL import Image
SC="/private/tmp/claude-501/-Users-nohyeonseong-Desktop-VIGENT/45405339-172f-46c1-b3aa-59834ee29253/scratchpad"
FPS=24.0; DT=0.5
ZONE=(0.20,0.55,0.52,0.85); ROI=(0.27,0.60,0.42,0.80)
def cen(nb): return ((nb[0]+nb[2])/2,(nb[1]+nb[3])/2)
def cen_in(c,z): return z[0]<=c[0]<=z[2] and z[1]<=c[1]<=z[3]
import rfdetr_service
svc=rfdetr_service.rfdetr; svc._ensure()
from rfdetr.util.coco_classes import COCO_CLASSES
def zone_persons(fr, thr=0.10, up=2.0, min_h_px=15):
    H,W=fr.shape[:2]
    zx0,zy0,zx1,zy1=int(ZONE[0]*W),int(ZONE[1]*H),int(ZONE[2]*W),int(ZONE[3]*H)
    crop=fr[zy0:zy1,zx0:zx1]; ch,cw=crop.shape[:2]
    big=cv2.resize(crop,(int(cw*up),int(ch*up)))
    det=svc._model.predict(Image.fromarray(cv2.cvtColor(big,cv2.COLOR_BGR2RGB)),threshold=thr)
    out=[]
    for i in range(len(det)):
        if COCO_CLASSES[det.class_id[i]]!="person": continue
        x1,y1,x2,y2=(float(v) for v in det.xyxy[i])
        px1,py1,px2,py2=zx0+x1/up,zy0+y1/up,zx0+x2/up,zy0+y2/up
        if (py2-py1)<min_h_px: continue      # 노이즈 슬라이버 제거
        nb=[px1/W,py1/H,px2/W,py2/H]; c=cen(nb)
        if cen_in(c,ZONE): out.append(c)
    return out

MATCH=0.07; STATIC_EPS=0.025; GAP=2
def track(frames):
    tracks=[]  # {cx,cy,ss_t,maxstat,last_t,missed,in_roi}
    for fp in sorted(frames):
        fi=int(os.path.basename(fp).split(".")[0]); t=fi/FPS
        dets=zone_persons(cv2.imread(fp))
        used=set()
        for tr in tracks:
            best=None;bd=MATCH
            for j,c in enumerate(dets):
                if j in used: continue
                d=math.hypot(c[0]-tr["cx"],c[1]-tr["cy"])
                if d<bd: bd=d;best=j
            if best is not None:
                c=dets[best];used.add(best)
                disp=math.hypot(c[0]-tr["cx"],c[1]-tr["cy"])
                if disp>=STATIC_EPS: tr["ss_t"]=t          # 움직임 → 정적런 리셋
                tr["cx"],tr["cy"],tr["last_t"],tr["missed"]=c[0],c[1],t,0
                tr["maxstat"]=max(tr["maxstat"],t-tr["ss_t"])
                if cen_in(c,ROI): tr["in_roi"]=True
            else:
                tr["missed"]+=1
        tracks=[tr for tr in tracks if tr["missed"]<=GAP]
        for j,c in enumerate(dets):
            if j in used: continue
            tracks.append({"cx":c[0],"cy":c[1],"ss_t":t,"maxstat":0.0,"last_t":t,"missed":0,
                           "in_roi":cen_in(c,ROI)})
        # 닫힌 트랙도 보존하려면 별도 리스트 필요 — 여기선 활성 유지, maxstat는 계속 갱신됨
        for tr in tracks: pass
    return tracks

# 활성 트랙만으론 종료 트랙 maxstat 유실 → 전체 이력 보존판
def track_all(frames):
    active=[]; closed=[]
    for fp in sorted(frames):
        fi=int(os.path.basename(fp).split(".")[0]); t=fi/FPS
        dets=zone_persons(cv2.imread(fp)); used=set()
        for tr in active:
            best=None;bd=MATCH
            for j,c in enumerate(dets):
                if j in used: continue
                d=math.hypot(c[0]-tr["cx"],c[1]-tr["cy"])
                if d<bd: bd=d;best=j
            if best is not None:
                c=dets[best];used.add(best)
                if math.hypot(c[0]-tr["cx"],c[1]-tr["cy"])>=STATIC_EPS: tr["ss_t"]=t
                tr["cx"],tr["cy"],tr["last_t"],tr["missed"]=c[0],c[1],t,0
                tr["maxstat"]=max(tr["maxstat"],t-tr["ss_t"])
                if cen_in(c,ROI): tr["in_roi"]=True
            else: tr["missed"]+=1
        keep=[]
        for tr in active:
            (closed if tr["missed"]>GAP else keep).append(tr)
        active=keep
        for j,c in enumerate(dets):
            if j in used: continue
            active.append({"cx":c[0],"cy":c[1],"ss_t":t,"maxstat":0.0,"last_t":t,"missed":0,"in_roi":cen_in(c,ROI)})
    return active+closed

inc=track_all(sorted(glob.glob(f"{SC}/inc2/*.jpg")))
noinc=track_all(sorted(glob.glob(f"{SC}/noinc2/*.jpg")))
fallen_stat=max([tr["maxstat"] for tr in inc if tr["in_roi"]], default=0.0)
res={"params":{"fps_sample":2,"static_eps":STATIC_EPS,"match":MATCH,"gap":GAP,"zone":ZONE,"roi":ROI},
     "incident":{"n_tracks":len(inc),"fallen_max_static_s":round(fallen_stat,1)},
     "noincident":{"n_tracks":len(noinc)}, "sweep":[]}
for T in (3,5,10):
    recall = fallen_stat>=T
    fp = sum(1 for tr in noinc if tr["maxstat"]>=T)
    res["sweep"].append({"T_s":T,"incident_caught":bool(recall),
        "fallen_static_s":round(fallen_stat,1),"noincident_FP_tracks":fp})
open(f"{SC}/b8_temporal.json","w").write(json.dumps(res,ensure_ascii=False,indent=2))
print("DONE"); print(json.dumps(res,ensure_ascii=False,indent=2))
