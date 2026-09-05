import time
from ultralytics import YOLO
data="/Users/nohyeonseong/Desktop/VIGENT/data/datasets/ppe_merged/data.yaml"
print("[merged] 통합 PPE 학습 (13클래스, 3616장)", flush=True)
t0=time.time()
m=YOLO('/Users/nohyeonseong/Desktop/VIGENT/vigent-core/weights/yolo11s.pt')
r=m.train(data=data, epochs=70, imgsz=640, batch=8, device='mps',
          patience=20, workers=4,
          project='/Users/nohyeonseong/Desktop/VIGENT/runs/ppe_train', name='merged_v1',
          exist_ok=True, verbose=True)
print(f"[merged] 완료 {(time.time()-t0)/60:.1f}분 → {r.save_dir}", flush=True)
