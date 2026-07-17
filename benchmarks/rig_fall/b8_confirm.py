import sys, os, glob, json, statistics as st; sys.path.insert(0,"vigent-core")
os.environ["VIGENT_ALLOW_FALLBACK"]="1"
import cv2, numpy as np
from PIL import Image
SC="/private/tmp/claude-501/-Users-nohyeonseong-Desktop-VIGENT/45405339-172f-46c1-b3aa-59834ee29253/scratchpad"
INC=sorted(glob.glob(f"{SC}/inc37/*.jpg")); NOINC=sorted(glob.glob(f"{SC}/noinc/*.jpg"))
ZONE=(0.20,0.55,0.52,0.85)          # 위험구역(작업 반경) — 이 안에서만 타일 검출
def cen_in(nb,z):
    cx,cy=(nb[0]+nb[2])/2,(nb[1]+nb[3])/2
    return z[0]<=cx<=z[2] and z[1]<=cy<=z[3]

import rfdetr_service
svc=rfdetr_service.rfdetr; svc._ensure()
from rfdetr.util.coco_classes import COCO_CLASSES
# pose 모델(RTMPose) 로드 — tiny 박스 실효성 측정
try:
    from pose.rtmpose_adapter import RtmPoseDetector
    POSE=RtmPoseDetector(); pose_ok_load=True
except Exception as e:
    POSE=None; pose_ok_load=f"{type(e).__name__}: {e}"

def zone_tiled_persons(fr, thr=0.10, up=2.0):
    """ZONE 크롭을 up배 확대해 RF-DETR → 원본 정규화 person 박스(ZONE 내부만)."""
    H,W=fr.shape[:2]
    zx0,zy0,zx1,zy1=int(ZONE[0]*W),int(ZONE[1]*H),int(ZONE[2]*W),int(ZONE[3]*H)
    crop=fr[zy0:zy1,zx0:zx1]
    ch,cw=crop.shape[:2]
    big=cv2.resize(crop,(int(cw*up),int(ch*up)))
    det=svc._model.predict(Image.fromarray(cv2.cvtColor(big,cv2.COLOR_BGR2RGB)),threshold=thr)
    out=[]
    for i in range(len(det)):
        if COCO_CLASSES[det.class_id[i]]!="person": continue
        x1,y1,x2,y2=(float(v) for v in det.xyxy[i])
        # big→crop→full 픽셀
        px1,py1,px2,py2=zx0+x1/up, zy0+y1/up, zx0+x2/up, zy0+y2/up
        nb=[px1/W,py1/H,px2/W,py2/H]
        if cen_in(nb,ZONE):
            out.append({"nb":nb,"px":[px1,py1,px2,py2],"conf":round(float(det.confidence[i]),3)})
    return out

def analyze(fr, cand):
    H,W=fr.shape[:2]
    px1,py1,px2,py2=cand["px"]
    bw,bh=px2-px1,py2-py1
    aspect=round(bw/max(bh,1e-6),2)          # (b) 종횡비: 서있음<1, 쓰러짐≥1
    box_h_px=round(bh,1)
    # (c) pose
    pose={"ok":False}
    if POSE is not None:
        try:
            ppl=POSE.persons(fr, bboxes=[[px1,py1,px2,py2]])
            if ppl:
                xy,cf=ppl[0]; vis=int((cf>=0.3).sum())
                if vis>=4:
                    sc=xy[[5,6]][cf[[5,6]]>=0.3]; hc=xy[[11,12]][cf[[11,12]]>=0.3]
                    hd=xy[[0,1,2,3,4]][cf[[0,1,2,3,4]]>=0.3]
                    if len(sc) and len(hc):
                        import math
                        scm=sc.mean(0); hcm=hc.mean(0)
                        ang=math.degrees(math.atan2(abs(hcm[0]-scm[0]),abs(hcm[1]-scm[1])+1e-6))
                        hbelow= (hd[:,1].mean()>hcm[1]) if len(hd) else False
                        pose={"ok":True,"vis_kp":vis,"trunk_angle":round(ang,1),"head_below_hip":bool(hbelow),
                              "pose_fallen":bool(ang>55 or hbelow)}
                    else: pose={"ok":False,"reason":"no shoulder/hip"}
                else: pose={"ok":False,"reason":f"vis_kp={vis}"}
        except Exception as e:
            pose={"ok":False,"reason":f"{type(e).__name__}"}
    return {"conf":cand["conf"],"aspect":aspect,"box_h_px":box_h_px,"pose":pose}

def run(frames):
    per_frame=[]; cands=[]
    for fp in frames:
        fr=cv2.imread(fp)
        cs=zone_tiled_persons(fr)
        rows=[analyze(fr,c) for c in cs]
        per_frame.append(len(rows)>0)
        cands+=rows
    return per_frame, cands

inc_hit, inc_c = run(INC)
noinc_hit, noinc_c = run(NOINC)

def summ(cands):
    if not cands: return {"n":0}
    asp=[c["aspect"] for c in cands]
    poks=[c for c in cands if c["pose"].get("ok")]
    return {"n":len(cands),"aspect_min_med_max":[min(asp),round(st.median(asp),2),max(asp)],
            "pose_yield":f"{len(poks)}/{len(cands)}",
            "pose_fallen_true":sum(1 for c in poks if c["pose"].get("pose_fallen")),
            "box_h_px_med":round(st.median([c["box_h_px"] for c in cands]),1)}

res={"zone":ZONE,"pose_load":pose_ok_load,
     "incident":{"frames":len(INC),"frames_with_cand":sum(inc_hit),
                 "recall_precand":f"{sum(inc_hit)}/{len(INC)}","cands":summ(inc_c)},
     "noincident":{"frames":len(NOINC),"frames_with_cand":sum(noinc_hit),
                   "cands":summ(noinc_c)},
     "raw_inc":[{"conf":c["conf"],"aspect":c["aspect"],"h":c["box_h_px"],
                 "pose":c["pose"].get("pose_fallen") if c["pose"].get("ok") else c["pose"].get("reason","noload")} for c in inc_c],
     "raw_noinc":[{"conf":c["conf"],"aspect":c["aspect"],"h":c["box_h_px"],
                 "pose":c["pose"].get("pose_fallen") if c["pose"].get("ok") else c["pose"].get("reason","noload")} for c in noinc_c]}
open(f"{SC}/b8_confirm.json","w").write(json.dumps(res,ensure_ascii=False,indent=2))
print("DONE")
print(json.dumps({k:res[k] for k in ("zone","pose_load","incident","noincident")},ensure_ascii=False,indent=2))
