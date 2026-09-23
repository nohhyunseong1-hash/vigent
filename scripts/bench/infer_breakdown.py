#!/usr/bin/env python3
"""infer_breakdown.py — 정적 영상 1프레임 추론을 구간별로 나눠 CPU·GPU 를 잰다. [승인 항목 1]

구간 (앱 경로 순서와 같다 — worker → guard.detect → RfdetrDetector.predict → rfdetr):
  decode      cv2.VideoCapture.read (mp4 디코드)                ★앱의 last_detect_ms 에는 **포함되지 않는다**
  preprocess  BGR→RGB, 384×384 리사이즈, ImageNet 정규화, 텐서화, (GPU 면 H2D 복사)
  person_fwd  rf-detr-nano(COCO) 순전파                          (GPU 는 synchronize 포함)
  ppe_fwd     ppe_rfdetr_v1 순전파                               (CPU 열에는 onnx-cpu 도 따로 — CPU 빌드의 실제 경로)
  postproc    rfdetr PostProcess(top-k·박스 복원), (GPU 면 D2H)
  predict_e2e 참고: rfdetr `.predict(pil)` 을 그대로 부른 슬롯당 end-to-end (앱이 실제로 부르는 함수)

앱 내 p95(41~77ms) 와 비교할 때 주의: 앱 값은 t0(프레임 시각)→완료 = 락 대기 + 그 주기의 슬롯들 + 추적.
focus 주기엔 person 만 돌아 p50 이 낮고, 디코드는 캡처 스레드가 미리 해 두므로 빠진다.

사용: <포터블>\\python\\python.exe scripts\bench\\infer_breakdown.py <weights_dir> <video> [--device cuda|cpu] [--runs 20]
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
import time
from pathlib import Path

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RES = 384
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def pct(xs, q):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))]


def summarize(name, xs):
    return {"stage": name, "mean": st.mean(xs), "p50": pct(xs, .5), "p95": pct(xs, .95), "n": len(xs)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("weights"); ap.add_argument("video")
    ap.add_argument("--device", default="cuda"); ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--frame", type=int, default=30)
    a = ap.parse_args()
    import torch
    from PIL import Image
    from rfdetr import RFDETRNano
    from rfdetr.models.postprocess import PostProcess

    dev = a.device
    if dev == "cuda" and not torch.cuda.is_available():
        print("CUDA 없음 — 측정 불가"); return 2
    sync = (lambda: torch.cuda.synchronize()) if dev == "cuda" else (lambda: None)
    W = Path(a.weights)

    # ── 모델 (앱과 같은 로드: 해상도 384, optimize_for_inference) ──
    def load(pth):
        m = RFDETRNano(pretrain_weights=str(pth), device=dev, resolution=RES)
        try:
            m.optimize_for_inference()
        except Exception:  # noqa: BLE001
            pass
        return m
    person = load(W / "rf-detr-nano.pth")
    ppe = load(W / "ppe_rfdetr_v1.pth")
    post = PostProcess(num_select=300)

    # ── decode: 같은 위치부터 runs 프레임 순차 디코드 ──
    cap = cv2.VideoCapture(a.video); cap.set(cv2.CAP_PROP_POS_FRAMES, a.frame)
    dec = []; frame = None
    for _ in range(a.runs):
        t = time.perf_counter(); ok, f = cap.read(); dec.append((time.perf_counter() - t) * 1000)
        if not ok: break
        frame = f
    cap.release()
    if frame is None:
        print("프레임 없음"); return 1
    H, Wd = frame.shape[:2]
    print(f"frame {frame.shape} · device={dev} · runs={a.runs}")

    def preprocess():
        x = cv2.resize(frame, (RES, RES), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = (x - MEAN) / STD
        t = torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1)[None]))
        t = t.to(dev); sync(); return t

    def fwd(m, t):
        # ★앱이 부르는 것과 같은 객체를 부른다. optimize_for_inference 뒤 rfdetr.predict 는
        #   model.model 이 아니라 **model.inference_model**(export+jit.trace, _optimized_dtype 캐스트)을 쓴다
        #   (rfdetr/detr.py:1593). 처음엔 model.model 을 불러 CPU 열이 predict e2e 보다 2.3배 느리게 나왔다 —
        #   GPU 에선 둘이 같아 안 드러났다. 잰 것이 앱 경로가 아니면 숫자는 의미가 없다.
        im = getattr(m.model, "inference_model", None)
        with torch.inference_mode():
            if im is not None:
                out = im(t.to(dtype=getattr(m, "_optimized_dtype", t.dtype)))
            else:
                out = m.model.model(t)
        sync(); return out

    def postproc(out):
        r = post(out, target_sizes=torch.tensor([[H, Wd]], device=dev))
        _ = r[0]["boxes"].cpu(); sync(); return r

    # 예열
    for _ in range(5):
        t = preprocess(); o1 = fwd(person, t); o2 = fwd(ppe, t); postproc(o1); postproc(o2)

    pre, pf, qf, po = [], [], [], []
    for _ in range(a.runs):
        s = time.perf_counter(); t = preprocess(); pre.append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); o1 = fwd(person, t); pf.append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); o2 = fwd(ppe, t); qf.append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); postproc(o1); postproc(o2); po.append((time.perf_counter() - s) * 1000)

    # 참고: 앱이 실제로 부르는 predict(pil) end-to-end (슬롯당)
    pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    for _ in range(3):
        person.predict(pil, threshold=0.3); ppe.predict(pil, threshold=0.3)
    e2e_p, e2e_q = [], []
    for _ in range(a.runs):
        s = time.perf_counter(); person.predict(pil, threshold=0.3); sync(); e2e_p.append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); ppe.predict(pil, threshold=0.3); sync(); e2e_q.append((time.perf_counter() - s) * 1000)

    rows = [summarize("decode(mp4)", dec), summarize("preprocess(+H2D)", pre), summarize("person_fwd", pf),
            summarize("ppe_fwd(torch)", qf), summarize("postproc(+D2H)", po)]

    # CPU 빌드의 실제 PPE 경로 = onnx-cpu (앱 튜닝: intra 4 · spin off)
    if dev == "cpu" and (W / "ppe_rfdetr_v1.onnx").exists():
        import onnxruntime as ort
        so = ort.SessionOptions(); so.intra_op_num_threads = 4; so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        sess = ort.InferenceSession(str(W / "ppe_rfdetr_v1.onnx"), so, providers=["CPUExecutionProvider"])
        name = sess.get_inputs()[0].name
        xin = preprocess().numpy()
        for _ in range(5): sess.run(None, {name: xin})
        ox = []
        for _ in range(a.runs):
            s = time.perf_counter(); sess.run(None, {name: xin}); ox.append((time.perf_counter() - s) * 1000)
        rows.append(summarize("ppe_fwd(onnx-cpu, CPU빌드 경로)", ox))

    rows += [summarize("predict_e2e person(참고)", e2e_p), summarize("predict_e2e ppe(참고)", e2e_q)]
    core = ["preprocess(+H2D)", "person_fwd", "ppe_fwd(torch)", "postproc(+D2H)"]
    total = sum(r["mean"] for r in rows if r["stage"] in core)

    print("\n| 구간 | 평균 ms | p50 | p95 |\n|---|---|---|---|")
    for r in rows:
        print(f"| {r['stage']} | {r['mean']:.1f} | {r['p50']:.1f} | {r['p95']:.1f} |")
    print(f"| **합계(preprocess+person+ppe+postproc)** | **{total:.1f}** | | |")
    if dev == "cuda":
        print(f"torch VRAM allocated {torch.cuda.memory_allocated()/1048576:.0f} MB · reserved {torch.cuda.memory_reserved()/1048576:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
