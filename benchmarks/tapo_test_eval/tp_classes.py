# [TP-보강] 클래스별 분포 60초 수집(리포트 표용) — tp_eval 과 동일 등록·해제 절차
import json, time, urllib.request
from collections import Counter, defaultdict
from pathlib import Path
ROOT = Path("D:/vigent_original")
TOK = [l.split("=",1)[1].strip() for l in (ROOT/".env").read_text(encoding="utf-8").splitlines() if l.startswith("VIGENT_API_TOKEN=")][0]
def api(p, m="GET", b=None):
    d = json.dumps(b).encode() if b else None
    r = urllib.request.Request("http://127.0.0.1:8010"+p, method=m, data=d,
        headers={"Authorization":"Bearer "+TOK, "Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=20) as x:
        raw = x.read(); return json.loads(raw) if raw else {}
VIDEOS = sorted(Path("C:/Users/shgus/OneDrive/바탕 화면/tapo_test").glob("*.mp4"))
out = {}
for i, vp in enumerate(VIDEOS, 1):
    cid = f"tp{i}"
    api("/cameras","POST",{"id":cid,"name":f"cls{i}","source":str(vp),"fps":2.0,"enabled":True})
    t0=time.time()
    while time.time()-t0<45:
        v=(api("/health").get("cameras") or {}).get(cid) or {}
        if v.get("status")=="ok" and (v.get("last_detect_age_s") or 99)<5: break
        time.sleep(1.5)
    cnt=Counter(); confs=defaultdict(list); last=-1; t0=time.time()
    while time.time()-t0<60:
        d=api(f"/cameras/{cid}/detections"); ts=d.get("ts") or 0
        if ts!=last:
            last=ts
            for x in d.get("detections",[]):
                cnt[x.get("class")]+=1; confs[x.get("class")].append(float(x.get("score") or 0))
        time.sleep(0.18)
    api(f"/cameras/{cid}","DELETE"); time.sleep(2)
    out[cid]={k:{"n":v,"mean_conf":round(sum(confs[k])/len(confs[k]),3)} for k,v in cnt.most_common()}
    print(cid, json.dumps(out[cid],ensure_ascii=False), flush=True)
Path("tp_classes.json").write_text(json.dumps(out,ensure_ascii=False,indent=1),encoding="utf-8")
cams=api("/cameras"); lst=cams if isinstance(cams,list) else cams.get("cameras",[])
print("잔여 tp*:", [x.get("id") for x in lst if str(x.get("id","")).startswith("tp")] or "없음", flush=True)
