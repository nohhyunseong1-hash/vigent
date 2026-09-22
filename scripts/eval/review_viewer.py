#!/usr/bin/env python3
"""scripts/eval/review_viewer.py — 2fps 정답지 초안 검수 뷰어(로컬 전용).

★프레임에 **사람 얼굴이 있다**(개인영상정보). 이 뷰어는 **127.0.0.1 에만** 바인딩하고
  이미지를 외부로 보내지 않는다. 공개 배포·클라우드 업로드 금지.

배경: `interpolate_gt_2fps.py` 가 만든 500ms 초안은 **정답지가 아니다.** 사람이 확인해
  `source="human_verified"` 로 바꾼 것만 정답지로 쓴다(규칙 7·11).

화면: 좌(t-1000ms 원본 라벨) · 중(t-500ms **보간 초안**) · 우(t 원본 라벨) 3연.
조작(마우스 없이 가능):
  Enter  승인(source → human_verified)      1~9  후보 트랙 선택
  N      선택 박스에 새 트랙 부여            D    선택 박스 삭제
  U      판정 불가(화질 등) — ID 를 부여하지 않고 IDSW 분모에서 뺀다
  ← →    이전·다음                          Tab  박스 선택 이동
  드래그  박스 수정(마우스, 선택)            S    즉시 저장(자동 저장도 됨)

저장: 조작마다 즉시 `data/field_eval/review_progress.json` 에 기록 — 새로고침해도 진행 유지.

실행:
    python scripts/eval/review_viewer.py
    → http://127.0.0.1:8777  (포트 사용 중이면 --port 로 바꾼다)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

if hasattr(sys.stdout, "reconfigure"):
    # ★Windows 콘솔 기본 cp949 에서는 '—' 같은 문자에 UnicodeEncodeError 가 나 **기동이 죽는다**
    #   (2026-09-22 실측). 다른 스크립트(check_raw_capture.py)와 같은 방식으로 utf-8 로 맞춘다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

_FE = _ROOT / "data" / "field_eval"
_DRAFT = _FE / "labels_2fps_draft"
_SIDE_1FPS = _FE / "labels_1fps_tid"
_PROGRESS = _FE / "review_progress.json"


class Save(BaseModel):
    """★모듈 최상위에 둬야 한다 — `from __future__ import annotations` 로 애노테이션이
    문자열이 되는데, FastAPI 는 그것을 **모듈 전역**에서 해석한다. main() 안에 두면
    'Save' 를 못 찾아 본문이 아니라 **쿼리 파라미터**로 취급해 422 가 난다
    (2026-09-22 실측: POST /api/save 가 계속 실패하고 있었다)."""

    stem: str
    boxes: list[dict]
    verified: bool = True
    seconds: float = 0.0


def build_queue() -> list[dict[str, Any]]:
    """검수 대기열 — 영상별 검수 필요 장수 **내림차순**, 영상 안에서는 시간순(지시 2026-09-22)."""
    man = json.loads((_FE / "frames_manifest_2fps_draft.json").read_text(encoding="utf-8"))
    frames = man["frames"] if isinstance(man, dict) else man
    src = json.loads((_FE / "frames_manifest.json").read_text(encoding="utf-8"))
    at = {(r["video"], int(r["t_ms"])): r["file"] for r in src}
    need: dict[str, int] = {}
    for f in frames:
        if f.get("status") == "needs_review":
            need[f["video"]] = need.get(f["video"], 0) + 1
    order = {v: i for i, (v, _n) in enumerate(sorted(need.items(), key=lambda kv: -kv[1]))}
    q = []
    for f in frames:
        t = int(f["t_ms"])
        q.append({**f, "t_ms": t,
                  "prev_file": at.get((f["video"], t - 500)), "next_file": at.get((f["video"], t + 500)),
                  "_ord": (order.get(f["video"], 99), t)})
    q.sort(key=lambda x: (x["status"] != "needs_review", x["_ord"]))   # 검수 필요분 먼저
    # ★V-3: 자동 연결분(interp) 중 **10장을 무작위 표본**으로 뒤에 붙인다 — 자동 연결 정확도 측정용.
    #   시드를 고정해 새로고침해도 같은 표본이 나온다(재현성).
    need = [x for x in q if x["status"] == "needs_review"]
    auto = [x for x in q if x["status"] != "needs_review"]
    rnd = random.Random(20260922)
    sample = rnd.sample(auto, min(10, len(auto)))
    ids = {id(x) for x in sample}
    for x in sample:
        x["review_kind"] = "auto_sample"
    for x in need:
        x["review_kind"] = "needs_review"
    out = need + sample + [x for x in auto if id(x) not in ids]
    for x in out:
        x.pop("_ord", None)
        x.setdefault("review_kind", "auto")
    return out


def load_draft(stem: str) -> dict[str, Any]:
    p = _DRAFT / f"{stem}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"boxes": []}


def load_src_labels(stem: str) -> list[dict[str, Any]]:
    """원본 1fps 라벨(person 만) — 좌·우 패널용.

    ★V-1(2026-09-22): 원본 `.txt` 는 5필드라 track_id 가 없다. 보간 단계가 부여한 ID 는
      `labels_1fps_tid/<stem>.json` 사이드카에 있다 — 그것을 우선 읽는다(좌표는 txt 와 동일).
    ★V-2: 검수에서 바뀐 ID 가 있으면 `review_progress.json` 을 **덮어쓴다**(최신 우선).
      그래야 다음 프레임의 후보 목록이 방금 확정한 ID 를 반영한다.
    """
    out: list[dict[str, Any]] = []
    sc = _SIDE_1FPS / f"{stem}.json"
    if sc.exists():
        d = json.loads(sc.read_text(encoding="utf-8"))
        out = [dict(b) for b in d.get("boxes", [])]
    else:                                        # 사이드카가 없으면 좌표만이라도 보여준다
        p = _FE / "labels" / f"{stem}.txt"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                a = line.split()
                if len(a) < 5:
                    continue
                try:
                    cls = int(a[0])
                except ValueError:
                    continue
                if cls == 0:
                    out.append({"cls": cls, "box": [float(v) for v in a[1:5]], "track_id": None})
    done = progress()["done"].get(stem)
    if done:                                     # V-2: 확정분이 있으면 그것이 정본
        out = [dict(b) for b in done["boxes"]]
    return out


SELFTEST_STEM = "__selftest_roundtrip__"


def selftest(app: Any) -> None:
    """기동 자체 점검 — 저장 → 재읽기 → 삭제 왕복을 **실제 HTTP 경로**로 한 번 돌린다.

    ★왜 HTTP 로 하나(2026-09-22 사고): `from __future__ import annotations` 로 애노테이션이
      문자열이 되는데 FastAPI 는 그것을 **모듈 전역**에서 해석한다. `Save` 모델이 함수 안에
      있어 못 찾고 본문이 아니라 **쿼리 파라미터**로 취급해 **모든 저장이 422 로 실패**하고
      있었다. 함수를 직접 부르는 점검이었다면 통과했을 것이다 — 라우팅·모델 바인딩까지
      지나가야 잡힌다.
    ★실패하면 기동을 **중단**한다. 저장이 안 되는 뷰어로 검수하면 결과가 통째로 사라진다(규칙 11).
    """
    from fastapi.testclient import TestClient

    box = {"cls": 0, "box": [0.5, 0.5, 0.1, 0.3], "track_id": 12345,
           "verdict": "unresolvable", "src_tid": None}
    before = progress()
    try:
        with TestClient(app) as c:
            r = c.post("/api/save", json={"stem": SELFTEST_STEM, "boxes": [box],
                                          "verified": False, "seconds": 0})
            if r.status_code != 200:
                raise RuntimeError(f"저장 요청이 {r.status_code} — 응답 {r.text[:300]}")
            if not (r.json() or {}).get("ok"):
                raise RuntimeError(f"저장 응답에 ok 가 없다 — {r.text[:300]}")
            q = c.get("/api/queue")
            if q.status_code != 200:
                raise RuntimeError(f"큐 조회가 {q.status_code}")
            done = (q.json() or {}).get("done", {})
            saved = done.get(SELFTEST_STEM)
            if not saved:
                raise RuntimeError("저장했는데 다시 읽으니 없다(저장이 실제로 안 됐다)")
            b = (saved.get("boxes") or [{}])[0]
            if b.get("verdict") != "unresolvable":
                raise RuntimeError(f"판정 불가가 보존되지 않았다 — {b}")
            if b.get("track_id") is not None:
                raise RuntimeError(f"판정 불가인데 track_id 가 남아 있다 — {b.get('track_id')}")
            if (q.json() or {}).get("unresolvable", 0) < 1:
                raise RuntimeError("판정 불가 집계가 올라가지 않았다")
    finally:
        # 삭제 — 점검 흔적을 남기지 않는다(진행률·평균 시간 오염 방지)
        cur = progress()
        cur["done"].pop(SELFTEST_STEM, None)
        cur["durations"] = before.get("durations", [])
        save_progress(cur)
        for d in (_DRAFT, _SIDE_1FPS):
            for ext in (".json", ".txt"):
                f = d / f"{SELFTEST_STEM}{ext}"
                if f.exists():
                    f.unlink()
    if SELFTEST_STEM in progress()["done"]:
        raise RuntimeError("점검 항목이 지워지지 않았다")
    print("자체 점검 통과 — 저장→재읽기→삭제 왕복 OK(판정 불가 보존·track_id 제거·집계 확인)")


def progress() -> dict[str, Any]:
    if _PROGRESS.exists():
        return json.loads(_PROGRESS.read_text(encoding="utf-8"))
    return {"done": {}, "started": None, "durations": []}


def save_progress(p: dict[str, Any]) -> None:
    _PROGRESS.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="2fps 정답지 초안 검수 뷰어(로컬)")
    ap.add_argument("--port", type=int, default=8777)
    a = ap.parse_args()

    import uvicorn
    from data_paths import media
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    frames_2fps = media("field_eval") / "frames_2fps_draft"
    frames_1fps = media("field_eval") / "frames"
    queue = build_queue()
    app = FastAPI(title="VIGENT 2fps 정답지 검수")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return HTML

    @app.get("/api/queue")
    def api_queue() -> JSONResponse:
        p = progress()
        unres = sum(int(v.get("n_unresolvable", 0)) for v in p["done"].values())
        return JSONResponse({"queue": queue, "done": p["done"], "unresolvable": unres,
                             "avg_sec": (sum(p["durations"]) / len(p["durations"])) if p["durations"] else None})

    @app.get("/api/item/{idx}")
    def api_item(idx: int) -> JSONResponse:
        if not 0 <= idx < len(queue):
            return JSONResponse({"error": "범위 밖"}, status_code=404)
        it = queue[idx]
        stem = Path(it["file"]).stem
        d = progress()["done"].get(stem)
        draft = load_draft(stem)
        return JSONResponse({
            "idx": idx, "total": len(queue), "item": it, "stem": stem,
            "boxes": d["boxes"] if d else draft.get("boxes", []),
            "verified": bool(d),
            "video_role": draft.get("video_role", "full"),
            "prev": {"file": it.get("prev_file"),
                     "boxes": load_src_labels(Path(it["prev_file"]).stem) if it.get("prev_file") else []},
            "next": {"file": it.get("next_file"),
                     "boxes": load_src_labels(Path(it["next_file"]).stem) if it.get("next_file") else []},
        })

    @app.post("/api/save")
    def api_save(s: Save) -> JSONResponse:
        p = progress()
        # ★Q-1: 판정 불가 박스는 track_id 를 지운다(ID 를 부여하지 않는다는 뜻).
        #   IDSW 분모에서 빼되 **개수는 따로 센다** — 정답지 한계를 숫자로 남기기 위함.
        boxes = []
        for b in s.boxes:
            if b.get("verdict") == "unresolvable":
                b = {**b, "track_id": None, "reason": b.get("reason") or "low_quality"}
            boxes.append(b)
        p["done"][s.stem] = {"boxes": boxes, "verified": s.verified,
                             "n_unresolvable": sum(1 for b in boxes if b.get("verdict") == "unresolvable")}
        s.boxes = boxes
        if s.seconds > 0:
            p["durations"].append(round(s.seconds, 1))
        save_progress(p)
        # 확정분은 사이드카 JSON 에도 즉시 반영(source → human_verified)
        jp = _DRAFT / f"{s.stem}.json"
        if jp.exists():
            d = json.loads(jp.read_text(encoding="utf-8"))
            d["boxes"] = [{**b, "source": "human_verified" if s.verified else b.get("source", "interp")}
                          for b in s.boxes]
            jp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            tp = jp.with_suffix(".txt")
            lines = [f"{b.get('cls', 0)} {b['box'][0]:.6f} {b['box'][1]:.6f} "
                     f"{b['box'][2]:.6f} {b['box'][3]:.6f} {b.get('track_id', 0)}" for b in s.boxes]
            tp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        # ★V-2 ID 연쇄: 보간 박스에서 확정한 track_id 를 **우측 원본 프레임(t+500ms)** 의
        #   대응 박스에도 기록한다. 대응 박스는 보간 때 짝지은 그 박스(src_tid 로 찾는다).
        #   좌표는 **수정하지 않는다** — track_id 필드만 바꾼다.
        chained = 0
        it = next((x for x in queue if Path(x["file"]).stem == s.stem), None)
        if it and it.get("next_file"):
            nxt = _SIDE_1FPS / f"{Path(it['next_file']).stem}.json"
            if nxt.exists():
                d = json.loads(nxt.read_text(encoding="utf-8"))
                by_src = {b.get("src_tid"): b.get("track_id") for b in s.boxes
                          if b.get("src_tid") is not None}
                for b in d.get("boxes", []):
                    new = by_src.get(b.get("track_id"))
                    if new is not None and new != b.get("track_id"):
                        b["track_id"] = new
                        chained += 1
                if chained:
                    nxt.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return JSONResponse({"ok": True, "done": len(p["done"]), "chained": chained})

    @app.get("/img/2fps/{name}")
    def img2(name: str) -> Any:
        p = frames_2fps / name
        return FileResponse(p) if p.exists() else JSONResponse({"error": "없음"}, status_code=404)

    @app.get("/img/1fps/{name}")
    def img1(name: str) -> Any:
        p = frames_1fps / name
        return FileResponse(p) if p.exists() else JSONResponse({"error": "없음"}, status_code=404)

    try:
        selftest(app)
    except Exception as ex:                       # noqa: BLE001
        print(f"★기동 중단 — 자체 점검 실패: {type(ex).__name__}: {ex}")
        print("  저장이 안 되는 상태로 검수하면 결과가 통째로 사라진다. 고치고 다시 띄운다.")
        return 2

    need = sum(1 for x in queue if x["status"] == "needs_review")
    print(f"검수 대기 {len(queue)}장(그중 검수 필요 {need}장) · 진행 {len(progress()['done'])}장")
    print(f"★로컬 전용 — http://127.0.0.1:{a.port}  (얼굴이 있는 이미지다. 외부로 내보내지 않는다)")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


HTML = r"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>VIGENT 2fps 정답지 검수</title>
<style>
:root{--bg:#0f1115;--fg:#e6e6e6;--dim:#8b93a1;--line:#242833;--accent:#ff9f43}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 system-ui,"Malgun Gothic",sans-serif}
header{padding:8px 14px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:center;flex-wrap:wrap}
h1{font-size:14px;margin:0;color:var(--accent)}
.note{color:var(--dim);font-size:12px}
.wrap{display:grid;grid-template-columns:1fr 1.6fr 1fr;gap:8px;padding:10px}
.pane{border:1px solid var(--line);border-radius:6px;overflow:hidden}
.pane h2{font-size:12px;margin:0;padding:6px 8px;background:#161a22;color:var(--dim);font-weight:600}
.cv{position:relative;width:100%;background:#000}
canvas{display:block;width:100%;height:auto}
footer{padding:8px 14px;border-top:1px solid var(--line);color:var(--dim);display:flex;gap:16px;flex-wrap:wrap}
kbd{background:#1c2029;border:1px solid var(--line);border-radius:3px;padding:1px 5px;color:var(--fg)}
.bar{height:4px;background:#1c2029;border-radius:2px;overflow:hidden;flex:1;min-width:120px}
.bar>i{display:block;height:100%;background:var(--accent)}
.ok{color:#3ddc84}
</style>
<header>
  <h1>VIGENT 2fps 정답지 검수</h1>
  <span id="pos" class="note"></span>
  <div class="bar"><i id="pb" style="width:0%"></i></div>
  <span id="eta" class="note"></span>
  <span id="state" class="note"></span>
</header>
<div class="note" style="padding:0 14px 6px">
  회색 점선은 <b>참고용 제안</b>이다. 자동 반영하지 않는다 — <b>최종 판단은 사람이 한다.</b>
</div>
<div class="note" id="cand" style="padding:0 14px 8px"></div>
<div class="wrap">
  <div class="pane"><h2 id="h-prev">이전 (t−500ms, 원본 라벨)</h2><div class="cv"><canvas id="cPrev"></canvas></div></div>
  <div class="pane"><h2 id="h-mid">검수 대상 (보간 초안)</h2><div class="cv"><canvas id="cMid"></canvas></div></div>
  <div class="pane"><h2 id="h-next">다음 (t+500ms, 원본 라벨)</h2><div class="cv"><canvas id="cNext"></canvas></div></div>
</div>
<footer>
  <span><kbd>Enter</kbd> 승인</span><span><kbd>1</kbd>~<kbd>9</kbd> 후보 선택</span>
  <span><kbd>N</kbd> 새 트랙</span><span><kbd>D</kbd> 삭제</span><span><kbd>U</kbd> 판정 불가(화질)</span><span><kbd>Tab</kbd> 박스 선택</span>
  <span><kbd>←</kbd><kbd>→</kbd> 이동</span><span><kbd>S</kbd> 저장</span><span>드래그: 박스 수정</span>
</footer>
<script>
const PAL=["#ff9f43","#3ddc84","#4aa8ff","#ff6b6b","#c678dd","#ffd93d","#00d2d3","#f368e0","#7bed9f","#ff7f50"];
let idx=0,cur=null,sel=0,t0=Date.now(),drag=null,avg=null;
const $=id=>document.getElementById(id);
const col=t=>PAL[(t||0)%PAL.length];

async function load(i){
  const r=await fetch('/api/item/'+i); if(!r.ok)return;
  cur=await r.json(); idx=cur.idx; sel=0; t0=Date.now();
  $('pos').textContent=`${idx+1} / ${cur.total} · ${cur.stem}`;
  const kind=cur.item.review_kind==='auto_sample'?'🔎 자동 보간 표본 확인'
            :cur.item.status==='needs_review'?'★검수 필요':'자동 보간';
  $('h-mid').textContent=`검수 대상 (보간 초안) — ${kind}`
    +(cur.video_role==='detector_only'?' · [검출기 전용 영상]':'');
  $('state').innerHTML=cur.verified?'<span class="ok">확정됨</span>':'미확정';
  draw(); renderCand();
  const q=await (await fetch('/api/queue')).json();
  const done=Object.keys(q.done).length; avg=q.avg_sec;
  $('pb').style.width=(done/cur.total*100)+'%';
  const left=cur.total-done;
  const un=q.unresolvable||0;
  $('eta').textContent=(avg?`남은 ${left}장 · 예상 ${Math.round(left*avg/60)}분 (평균 ${avg.toFixed(1)}초/장)`
                           :`남은 ${left}장 · 평균 측정 전`)
                       +(un?` · 판정 불가 ${un}개`:'');
}
function paint(cv,src,boxes,dashed,selIdx){
  const im=new Image();
  im.onload=()=>{cv.width=im.width;cv.height=im.height;const g=cv.getContext('2d');
    g.drawImage(im,0,0);
    boxes.forEach((b,i)=>{
      const[cx,cy,w,h]=b.box,x=(cx-w/2)*cv.width,y=(cy-h/2)*cv.height,W=w*cv.width,H=h*cv.height;
      g.lineWidth=(i===selIdx?4:2); g.setLineDash(dashed?[7,5]:[]);
      g.strokeStyle=dashed?'#8b93a1':col(b.track_id); g.strokeRect(x,y,W,H);
      g.font='bold 15px sans-serif';
      if(dashed){ // 참고 패널 — ID 만 흐리게(후보 고를 때 눈으로 대조하라고)
        g.fillStyle='#b9c0cc'; g.fillText(`id${b.track_id??'?'}`,x+3,Math.max(14,y-4));
      }else if(b.verdict==='unresolvable'){
        g.setLineDash([3,3]); g.strokeStyle='#ff6b6b'; g.strokeRect(x,y,W,H);
        g.fillStyle='#ff6b6b'; g.fillText(`${i+1}·판정불가`,x+3,Math.max(14,y-4));
      }else{
        g.fillStyle=col(b.track_id); g.fillText(`${i+1}·id${b.track_id??'?'}`,x+3,Math.max(14,y-4));
      }
    });};
  im.src=src;
}
function candidates(){
  // ★V-1: 후보는 **좌측(t-500ms) 원본 ID 먼저**, 그다음 우측(t+500ms) ID 에 "다음" 표시.
  const seen=new Set(), out=[];
  (cur.prev.boxes||[]).forEach(b=>{if(b.track_id!=null&&!seen.has(b.track_id)){
    seen.add(b.track_id);out.push({id:b.track_id,src:'이전'});}});
  (cur.next.boxes||[]).forEach(b=>{if(b.track_id!=null&&!seen.has(b.track_id)){
    seen.add(b.track_id);out.push({id:b.track_id,src:'다음'});}});
  return out.slice(0,9);
}
function renderCand(){
  const c=candidates(), el=$('cand');
  if(!c.length){el.innerHTML='<b style="color:#ff6b6b">후보 없음</b> — 진짜 등장·퇴장일 수 있다. <kbd>N</kbd> 으로 새 트랙.';return;}
  el.innerHTML='후보: '+c.map((x,i)=>
    `<span style="color:${col(x.id)}"><kbd>${i+1}</kbd> id${x.id}`+
    (x.src==='다음'?'<span style="color:#8b93a1">(다음)</span>':'')+'</span>').join(' · ');
}
function draw(){
  if(!cur)return;
  paint($('cMid'),'/img/2fps/'+cur.item.file,cur.boxes,false,sel);
  if(cur.prev.file)paint($('cPrev'),'/img/1fps/'+cur.prev.file,cur.prev.boxes,true,-1);
  if(cur.next.file)paint($('cNext'),'/img/1fps/'+cur.next.file,cur.next.boxes,true,-1);
}
async function save(verified){
  if(!cur)return;
  await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({stem:cur.stem,boxes:cur.boxes,verified:verified,seconds:(Date.now()-t0)/1000})});
  $('state').innerHTML='<span class="ok">저장됨</span>';
}
document.addEventListener('keydown',async e=>{
  if(!cur)return;
  if(e.key==='Enter'){await save(true);if(idx+1<cur.total)load(idx+1);e.preventDefault();return;}
  if(e.key==='ArrowRight'){if(idx+1<cur.total)load(idx+1);return;}
  if(e.key==='ArrowLeft'){if(idx>0)load(idx-1);return;}
  if(e.key==='Tab'){sel=(sel+1)%Math.max(1,cur.boxes.length);draw();e.preventDefault();return;}
  if(e.key.toLowerCase()==='d'){cur.boxes.splice(sel,1);sel=0;draw();await save(false);return;}
  if(e.key.toLowerCase()==='u'){          // ★판정 불가 — ID 를 부여하지 않는다
    const b=cur.boxes[sel]; if(b){
      if(b.verdict==='unresolvable'){delete b.verdict;delete b.reason;}
      else{b.verdict='unresolvable';b.reason='low_quality';b.track_id=null;}
      draw();renderCand();await save(false);} return;}
  if(e.key.toLowerCase()==='s'){await save(false);return;}
  if(e.key.toLowerCase()==='n'){
    const mx=Math.max(0,...cur.boxes.map(b=>b.track_id||0));
    if(cur.boxes[sel]){cur.boxes[sel].track_id=mx+1;draw();await save(false);} return;}
  if(/^[1-9]$/.test(e.key)){
    const c=candidates(); const t=c[+e.key-1];
    if(t&&cur.boxes[sel]){cur.boxes[sel].track_id=t.id;draw();renderCand();await save(false);}
    return;}
});
const mid=$('cMid');
mid.addEventListener('mousedown',e=>{const r=mid.getBoundingClientRect();
  drag={x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height};});
mid.addEventListener('mouseup',async e=>{
  if(!drag||!cur||!cur.boxes[sel]){drag=null;return;}
  const r=mid.getBoundingClientRect();
  const x2=(e.clientX-r.left)/r.width,y2=(e.clientY-r.top)/r.height;
  if(Math.abs(x2-drag.x)>0.01&&Math.abs(y2-drag.y)>0.01){
    cur.boxes[sel].box=[(drag.x+x2)/2,(drag.y+y2)/2,Math.abs(x2-drag.x),Math.abs(y2-drag.y)];
    draw();await save(false);}
  drag=null;});
load(0);
</script></html>"""


if __name__ == "__main__":
    sys.exit(main())
