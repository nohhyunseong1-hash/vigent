"""Colab 학습 노트북(.ipynb) 생성기 — T10b ppe+fire_smoke (CUDA/T4).
세션 끊김 복원력 최우선: 에폭마다 Drive 체크포인트, 자동 재개. 위에서부터 재실행 = 이어짐.
게이트 평가는 로컬 회수 후(설계 유지) — 노트북은 학습 + 가중치 Drive 저장까지.
"""
import json
from pathlib import Path

# ── 임베드 스크립트(노트북이 %%writefile 로 기록) ─────────────────────────
TRAINER = r'''import argparse, glob, os, sys, time
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_dir", required=True); ap.add_argument("--output_dir", required=True)
    ap.add_argument("--epochs", type=int, default=50); ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad_accum", type=int, default=2); ap.add_argument("--checkpoint_interval", type=int, default=1)
    ap.add_argument("--device", default="cuda"); ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    from rfdetr import RFDETRNano
    os.makedirs(a.output_dir, exist_ok=True)
    ck = sorted(glob.glob(os.path.join(a.output_dir, "checkpoint*.pth")), key=os.path.getmtime)
    resume = ck[-1] if ck else None
    print(f"[trainer] dataset={a.dataset_dir} epochs={a.epochs} device={a.device} resume={resume}", flush=True)
    t0 = time.time()
    try:
        RFDETRNano().train(dataset_dir=a.dataset_dir, epochs=a.epochs, batch_size=a.batch,
            grad_accum_steps=a.grad_accum, device=a.device, num_workers=a.workers, tensorboard=False,
            output_dir=a.output_dir, checkpoint_interval=a.checkpoint_interval, early_stopping=False, resume=resume)
    except Exception as e:
        import traceback; traceback.print_exc(); print(f"[trainer] TRAIN_FAILED: {e}", flush=True); sys.exit(2)
    print(f"[trainer] TRAIN_DONE elapsed_h={(time.time()-t0)/3600:.2f}", flush=True)
if __name__ == "__main__": main()
'''

PPE_BUILDER = r'''import argparse, json, shutil
from collections import Counter
from pathlib import Path
import cv2
NAMES = ['Hardhat','Mask','NO-Hardhat','NO-Mask','NO-Safety Vest','Person','Safety Cone','Safety Vest','machinery','vehicle']
def build(src, out, split):
    idir, ldir = src/split/'images', src/split/'labels'
    o = out/split; o.mkdir(parents=True, exist_ok=True)
    imgs=[]; anns=[]; aid=1; bad=0; emp=0
    for iid,ip in enumerate(sorted(list(idir.glob('*.jpg'))+list(idir.glob('*.png'))),1):
        im=cv2.imread(str(ip));
        if im is None: continue
        H,W=im.shape[:2]; shutil.copy2(ip,o/ip.name)
        imgs.append({'id':iid,'file_name':ip.name,'width':W,'height':H})
        lp=ldir/(ip.stem+'.txt')
        if not lp.exists(): continue
        for ln in lp.read_text().splitlines():
            p=ln.split()
            if len(p)<5: continue
            ci=int(float(p[0])); cx,cy,bw,bh=map(float,p[1:5])
            if not(0<=cx<=1 and 0<=cy<=1 and 0<bw<=1 and 0<bh<=1): bad+=1; continue
            x,y,w,h=(cx-bw/2)*W,(cy-bh/2)*H,bw*W,bh*H
            if w<=0 or h<=0: emp+=1; continue
            anns.append({'id':aid,'image_id':iid,'category_id':ci+1,'bbox':[x,y,w,h],'area':w*h,'iscrowd':0}); aid+=1
    (o/'_annotations.coco.json').write_text(json.dumps({'images':imgs,'annotations':anns,
        'categories':[{'id':i+1,'name':n,'supercategory':'ppe'} for i,n in enumerate(NAMES)]}))
    return len(imgs),len(anns),bad,emp
if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--src',required=True); ap.add_argument('--out',required=True)
    a=ap.parse_args(); src=Path(a.src); out=Path(a.out)
    if out.exists(): shutil.rmtree(out)
    tb=te=0
    for sp in ('train','valid','test'):
        if not (src/sp/'images').exists(): continue
        ni,na,bad,emp=build(src,out,sp); tb+=bad; te+=emp
        print(f'  {sp}: {ni}장/{na}box · 범위밖{bad} · 빈{emp}')
    print(f'  무결성: 범위밖 {tb} · 빈 {te} (0이어야 정상)')
'''

def _read(p):
    return Path(p).read_text(encoding="utf-8")

FIRE_BUILDER = _read(Path(__file__).parent / "build_fire_smoke_train_ds.py")


def code(src):
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
            "source": src if isinstance(src, list) else src.splitlines(keepends=True)}


def md(src):
    return {"cell_type": "markdown", "metadata": {},
            "source": src if isinstance(src, list) else src.splitlines(keepends=True)}


cells = [
 md("""# VIGENT T10b — ppe + fire_smoke 학습 (Colab / T4, CUDA)

**목적**: 로컬 M5 MPS 다중클래스 NaN 버그 우회. 학습만 클라우드, 산출물=가중치(Drive 저장 → 로컬 회수).
**세션 끊김 대비**: 에폭마다 Drive 체크포인트 + 자동 재개. **끊기면 위에서부터 재실행하면 이어집니다.**
**데이터**: css_safety(내 Drive 업로드, CC BY 4.0) · D-Fire(다운로드 셀, 공개).
**게이트 평가는 이 노트북에서 안 함** — 가중치 회수 후 로컬에서(기존 하네스·기준선 일관).

게이트(로컬): ppe raw mAP@50 ≥ 73.2 · fire_smoke presence Gate A(raw fire≥81/smoke≥88) + Gate B(pipeline recall > 53.64/24.85, FAR 무악화). SHA256 대조 + 버전 파일명 승계.
"""),
 code("""# 1. GPU 확인 (T4 배정 확인 — 아니면 런타임>런타임 유형 변경>T4 GPU)
!nvidia-smi
import torch
print('torch', torch.__version__, '| cuda', torch.cuda.is_available(),
      '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')
assert torch.cuda.is_available(), 'GPU 런타임 아님'"""),
 code("""# 2. 환경 설치 (rfdetr + 학습 deps). 재실행 안전(끊김 후 재실행 필요).
!pip install -q rfdetr==1.8.0 supervision==0.29.0.post0 pytorch_lightning==2.6.5 torchmetrics \\
  lightning-utilities albumentations kornia peft accelerate faster-coco-eval==1.7.2 \\
  pycocotools==2.0.11 pyyaml opencv-python-headless gdown
from rfdetr import RFDETRNano; print('rfdetr OK')"""),
 code("""# 3. Drive 마운트 + 작업 루트(체크포인트·가중치 Drive → 끊겨도 보존)
from google.colab import drive; drive.mount('/content/drive')
import os, glob
WORKROOT = '/content/drive/MyDrive/vigent_t10b'
CSS_SAFETY_DRIVE = '/content/drive/MyDrive/css_safety'   # ← css_safety(YOLO train/valid/test) 업로드 위치(경로 전달 시 수정)
for d in ['', '/data', '/out']: os.makedirs(WORKROOT+d, exist_ok=True)
print('WORKROOT:', WORKROOT)
# 재개 상태(끊김 후 어디부터인지)
for name in ['ppe_full','fire_full']:
    c=sorted(glob.glob(f'{WORKROOT}/out/{name}/checkpoint*.pth')); print(f'  {name}: 체크포인트 {len(c)}개', c[-1].split('/')[-1] if c else '없음')
for w in ['ppe_rfdetr_v1.pth','fire_smoke_rfdetr_v1.pth']:
    print(f'  최종 {w}:', '있음' if os.path.exists(f'{WORKROOT}/out/{w}') else '없음')"""),
 code("# 4. 헬퍼 스크립트 기록(트레이너·빌더)\n%%writefile rfdetr_train_colab.py\n" + TRAINER),
 code("%%writefile build_ppe_train_ds_colab.py\n" + PPE_BUILDER),
 code("%%writefile build_fire_smoke_train_ds.py\n" + FIRE_BUILDER),
 code("""# 5. 데이터 준비 — ppe COCO (css_safety YOLO → COCO). 이미 있으면 스킵.
PPE_DS = f'{WORKROOT}/data/ppe_rfdetr_ds'
if os.path.exists(f'{PPE_DS}/train/_annotations.coco.json'):
    print('ppe COCO 존재 — 스킵')
else:
    assert os.path.exists(f'{CSS_SAFETY_DRIVE}/train/images'), f'css_safety 미발견: {CSS_SAFETY_DRIVE} (Drive 업로드 확인)'
    !python build_ppe_train_ds_colab.py --src "$CSS_SAFETY_DRIVE" --out "$PPE_DS" """),
 code("""# 6. ppe 1-epoch 스모크 (loss 유한 확인 + 에폭당 시간 → T4 총시간 추정)
import time, csv
t=time.time()
!python rfdetr_train_colab.py --dataset_dir "$PPE_DS" --output_dir "$WORKROOT/out/ppe_smoke" --epochs 1 --batch 8 --grad_accum 2 --device cuda
dt=time.time()-t
rows=list(csv.DictReader(open(f'{WORKROOT}/out/ppe_smoke/metrics.csv')))
vals=[r['train/loss'] for r in rows if r.get('train/loss','').strip()]
finite = bool(vals) and not any(v.lower() in ('nan','inf','-inf') for v in vals)
print(f'ppe 스모크 loss={vals[:1]} → {"FINITE" if finite else "NaN"} | 1ep {dt/60:.1f}분 | T4 추정 ppe 50ep ≈ {dt*50/3600:.1f}h')
assert finite, 'CUDA에서도 NaN → 중단(예상 밖, 보고 필요)'"""),
 code("""# 7. ppe 본학습 50ep (에폭마다 Drive 체크포인트 → 자동 재개). 끊기면 이 셀만 재실행.
!python rfdetr_train_colab.py --dataset_dir "$PPE_DS" --output_dir "$WORKROOT/out/ppe_full" --epochs 50 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 1
import shutil
shutil.copy(f'{WORKROOT}/out/ppe_full/checkpoint_best_total.pth', f'{WORKROOT}/out/ppe_rfdetr_v1.pth')
print('✅ ppe 가중치:', f'{WORKROOT}/out/ppe_rfdetr_v1.pth')"""),
 code("""# 8. D-Fire 다운로드 + 검증 (D-Fire 는 OneDrive/Kaggle 배포 — Google Drive 아님)
import os, glob, base64, shutil
FIRE_DS=f'{WORKROOT}/data/fire_rfdetr_ds'; DFIRE=f'{WORKROOT}/data/dfire'
EXPECT_TOTAL = 21527   # README: fire1164 + smoke5867 + both4658 + neither9838

def _find_split_root(base):
    # 압축 내부가 train/ 직하가 아닐 수 있어 train/images 를 탐색해 실제 루트 반환
    for p in glob.glob(f'{base}/**/train/images', recursive=True):
        return os.path.dirname(os.path.dirname(p))
    return None

def _count(root):
    return len(glob.glob(f'{root}/train/images/*.*')) + len(glob.glob(f'{root}/test/images/*.*'))

root = _find_split_root(DFIRE) if os.path.exists(DFIRE) else None
if not (root and _count(root) >= 20000):
    # OneDrive 공식 공유링크 → 직접 다운로드(base64 shares API, 시크릿 불필요)
    ONEDRIVE = "https://1drv.ms/u/c/c0bd25b6b048b01d/EbLgD7bES4FDvUN37Grxn8QBF5gIBBc7YV2qklF08GCiBw"
    b64 = base64.urlsafe_b64encode(ONEDRIVE.encode()).decode().rstrip('=')
    direct = f"https://api.onedrive.com/v1.0/shares/u!{b64}/root/content"
    print('D-Fire OneDrive 다운로드 시도...(수분 소요)')
    os.makedirs(DFIRE, exist_ok=True)
    rc = os.system(f'wget -q --no-check-certificate "{direct}" -O /content/dfire.zip')
    sz = os.path.getsize('/content/dfire.zip') if os.path.exists('/content/dfire.zip') else 0
    if rc == 0 and sz > 1e8:
        os.system(f'unzip -q -o /content/dfire.zip -d "{DFIRE}"'); os.remove('/content/dfire.zip')
        root = _find_split_root(DFIRE)
    else:
        root = None

# ── 검증: 파일 크기·이미지 수가 기대치와 일치하는지 ──
n = _count(root) if root else 0
if not root or n < 20000:
    raise RuntimeError(
        f"❌ D-Fire 다운로드/검증 실패 (이미지 {n}장, 기대 ~{EXPECT_TOTAL}). 다운로드 실패·OneDrive 쿼터 초과·구조 불일치 가능.\\n"
        f"→ 로컬 업로드 폴백: 로컬 ~/Desktop/D-Fire 를 Drive 에 업로드(train/{{images,labels}}, test/{{images,labels}} 구조)한 뒤\\n"
        f"   이 셀의 DFIRE 변수를 업로드 위치로 바꾸고(예: DFIRE='/content/drive/MyDrive/dfire') 재실행하세요.")
if root != DFIRE:
    DFIRE = root   # 압축 내부 실제 루트로 보정
print(f"✅ D-Fire 검증 OK: {n}장 (~{EXPECT_TOTAL} 기대) @ {DFIRE}")"""),
 code("""# 8b. fire_smoke COCO 빌드(대안D). 이미 있으면 스킵.
if os.path.exists(f'{FIRE_DS}/train/_annotations.coco.json'):
    print('fire COCO 존재 — 스킵')
else:
    !python build_fire_smoke_train_ds.py --dfire "$DFIRE" --out "$FIRE_DS" --neg 2000"""),
 code("""# 9. fire_smoke 1-epoch 스모크
import time, csv
t=time.time()
!python rfdetr_train_colab.py --dataset_dir "$FIRE_DS" --output_dir "$WORKROOT/out/fire_smoke" --epochs 1 --batch 8 --grad_accum 2 --device cuda
dt=time.time()-t
rows=list(csv.DictReader(open(f'{WORKROOT}/out/fire_smoke/metrics.csv')))
vals=[r['train/loss'] for r in rows if r.get('train/loss','').strip()]
finite = bool(vals) and not any(v.lower() in ('nan','inf','-inf') for v in vals)
print(f'fire 스모크 loss={vals[:1]} → {"FINITE" if finite else "NaN"} | 1ep {dt/60:.1f}분 | T4 추정 30ep ≈ {dt*30/3600:.1f}h')
assert finite, 'CUDA에서도 NaN → 중단'"""),
 code("""# 10. fire_smoke 본학습 (대안D: 15ep → resume 30ep, 에폭마다 Drive 체크포인트)
!python rfdetr_train_colab.py --dataset_dir "$FIRE_DS" --output_dir "$WORKROOT/out/fire_full" --epochs 15 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 1
!python rfdetr_train_colab.py --dataset_dir "$FIRE_DS" --output_dir "$WORKROOT/out/fire_full" --epochs 30 --batch 8 --grad_accum 2 --device cuda --checkpoint_interval 1
import shutil
shutil.copy(f'{WORKROOT}/out/fire_full/checkpoint_best_total.pth', f'{WORKROOT}/out/fire_smoke_rfdetr_v1.pth')
print('✅ fire_smoke 가중치:', f'{WORKROOT}/out/fire_smoke_rfdetr_v1.pth')"""),
 code("""# 11. SHA256 생성 (로컬 회수 후 대조용) → Drive 저장
import hashlib
for w in ['ppe_rfdetr_v1.pth','fire_smoke_rfdetr_v1.pth']:
    p=f'{WORKROOT}/out/{w}'
    if not os.path.exists(p): print(f'  {w}: 없음(학습 미완)'); continue
    h=hashlib.sha256(open(p,'rb').read()).hexdigest()
    open(p+'.sha256','w').write(h+'  '+w+'\\n')
    print(f'  {w}: {h}')"""),
 md("""## 회수 후 (로컬)
1. Drive `vigent_t10b/out/` 에서 `*.pth` + `*.sha256` 다운로드.
2. 로컬에서 `shasum -a 256 *.pth` → `.sha256` 와 **대조**(전송 무결성).
3. `weights_manifest.json` 등재(버전 파일명) → **로컬 게이트 평가**(eval_rfdetr_custom + presence_eval).
4. 통과 시 이관(vision.yaml backend + rfdetr_weights + 어댑터 + 운용점 + 회귀 ±0.1) → **A-4 달성**(ultralytics 배포 잔존 0).
"""),
]

nb = {"cells": cells, "metadata": {"accelerator": "GPU",
      "colab": {"provenance": [], "gpuType": "T4"}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
      "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 0}

out = Path(__file__).parent / "VIGENT_T10b_train.ipynb"
out.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("생성:", out, "| 셀", len(cells), "개")
