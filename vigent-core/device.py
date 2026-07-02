"""device.py — 추론 장치 선택 단일 소스 (감사 C-1·C-2)

과거엔 장치 선택 로직이 4곳(guard·rfdetr_service·safety_pipeline·worker)에 제각각이라
리눅스/Jetson에선 CUDA를 두고 CPU로 강등되거나(C-1), worker는 'cpu' 하드코딩이었다(C-2).
여기 하나로 모은다. 우선순위: 강제(env) → CUDA → (선택)MPS → CPU.

모델별 제약 보존: ultralytics(YOLO)는 macOS MPS에서 다회추론 시 네이티브 크래시가 관찰되어
guard·worker(pose)는 prefer_mps=False(맥에선 CPU). rfdetr·pipeline은 MPS 정상이라 True.
→ 현재 맥 동작은 그대로, 리눅스/CUDA 박스에서만 GPU를 실제로 쓴다(저하 없음, 이식성↑).
"""
from __future__ import annotations

import os

_ENV = "VIGENT_DETECT_DEVICE"   # 'cpu'|'mps'|'cuda' 강제(모든 모델 공통)


def pick_device(prefer_mps: bool = True, env: str = _ENV) -> str:
    """추론 장치를 'cuda'|'mps'|'cpu' 중에서 고른다.
    env(VIGENT_DETECT_DEVICE)로 강제 가능. prefer_mps=False면 MPS를 건너뛴다(YOLO 안정성)."""
    forced = os.environ.get(env, "").strip().lower()
    if forced in ("cpu", "mps", "cuda"):
        return forced
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"                     # CUDA(리눅스/엔비디아)는 안정적 → 최우선
        if prefer_mps and torch.backends.mps.is_available():
            return "mps"                      # Apple Silicon(rfdetr 등 안정 모델만)
    except Exception:  # noqa: BLE001  torch 문제여도 최소 CPU로 동작
        pass
    return "cpu"
