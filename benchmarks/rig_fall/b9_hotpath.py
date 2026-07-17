import sys, os, glob, time, json; sys.path.insert(0,"vigent-core")
os.environ["VIGENT_ALLOW_FALLBACK"]="1"
import cv2
SC="/private/tmp/claude-501/-Users-nohyeonseong-Desktop-VIGENT/45405339-172f-46c1-b3aa-59834ee29253/scratchpad"
import rfdetr_service, zone_tile
ZONE=[(0.20,0.55),(0.52,0.55),(0.52,0.85),(0.20,0.85)]
frames=sorted(glob.glob(f"{SC}/inc37/*.jpg"))[:12]
detfn=lambda img: rfdetr_service.rfdetr.detect_persons(img, thr=0.1)
# 워밍업(모델로드) 제외
t=time.time(); zone_tile.zone_tile_detect(cv2.imread(frames[0]),ZONE,detfn); load=time.time()-t
ts=[]
for fp in frames[1:]:
    fr=cv2.imread(fp); t=time.time(); zone_tile.zone_tile_detect(fr,ZONE,detfn); ts.append((time.time()-t)*1000)
avg=sum(ts)/len(ts)
res={"model_load_incl_first_s":round(load,1),"tile_per_frame_ms_avg":round(avg,1),
     "tile_per_frame_ms_min_max":[round(min(ts),1),round(max(ts),1)],"n":len(ts),
     "env":"CPU RF-DETR COCO 폴백(GPU는 훨씬 빠름)"}
open(f"{SC}/b9_hotpath.json","w").write(json.dumps(res,ensure_ascii=False,indent=2))
print("DONE",json.dumps(res,ensure_ascii=False))
