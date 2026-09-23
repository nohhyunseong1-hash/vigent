"""device.py — 추론 장치 선택 단일 소스 (감사 C-1·C-2)

과거엔 장치 선택 로직이 4곳(guard·rfdetr_service·safety_pipeline·worker)에 제각각이라
리눅스/Jetson에선 CUDA를 두고 CPU로 강등되거나(C-1), worker는 'cpu' 하드코딩이었다(C-2).
여기 하나로 모은다. 우선순위: 강제(env) → CUDA → (선택)MPS → CPU.

모델별 제약 보존: ultralytics(YOLO)는 macOS MPS에서 다회추론 시 네이티브 크래시가 관찰돼
YOLO 경로(guard.self.device·worker)는 prefer_mps=False(맥=CPU). RF-DETR·mlx-vlm 은 MPS 정상이라 True.
→ 리눅스/CUDA 박스에서만 GPU를 실제로 쓴다(저하 없음, 이식성↑).

★ 실측 device 현황(2026-07-19, F-14 진단):
  - guard.detect = **MPS** — vision.yaml 전 슬롯 backend:rfdetr → RfdetrDetector(prefer_mps=True).
    (guard.self.device=CPU 는 YOLO 어댑터 전용, RF-DETR 검출엔 미전달. "guard=CPU"로 오해 금지.)
  - rfdetr_service.detect = **MPS** · VLM(mlx-vlm) = **MPS** · pose(RTMPose/onnxruntime) = **CPU**.
  → guard·rfdetr_service·VLM 셋 다 MPS 이므로 **동시추론 시 크래시(F-14)**. app_state.DETECT_LOCK(RLock)
    으로 셋을 한 락에 직렬화(F-14 해소). 새 MPS 추론 경로 추가 시 반드시 이 락으로 감쌀 것.
"""
from __future__ import annotations

import os

_ENV = "VIGENT_DETECT_DEVICE"   # 'cpu'|'mps'|'cuda' 강제(모든 모델 공통)

# [I-3, 2026-09-23] VRAM 상한 모사 — 벤치 전용 훅.
#   개발기는 16GB 카드인데 파일럿기는 8GB 다. 16GB 에서 잰 값을 8GB 값으로 **추정하지 않기** 위해,
#   torch 캐시 할당자에 상한(MB)을 걸어 "8GB 카드였다면 OOM 이 났을까" 를 실제로 돌려 본다.
#   ★한계를 정직하게: 이 상한은 **torch 할당자만** 막는다. CUDA 컨텍스트·cuDNN 워크스페이스·
#     다른 프로세스가 쓰는 VRAM 은 못 막는다. 8GB 카드의 완전한 모사가 아니다.
#   ★운영에서는 쓰지 않는다 — 미설정이면 아무것도 하지 않는다(기본 동작 무변경).
_CAP_ENV = "VIGENT_CUDA_MEM_CAP_MB"
_cap_state: dict = {"applied": False, "cap_mb": None, "total_mb": None, "fraction": None, "error": None}


def apply_cuda_mem_cap(env: str = _CAP_ENV) -> dict:
    """VIGENT_CUDA_MEM_CAP_MB 가 있으면 torch 할당자 상한을 **한 번만** 건다. 결과를 돌려준다."""
    if _cap_state["applied"] or _cap_state["error"]:
        return dict(_cap_state)
    raw = os.environ.get(env, "").strip()
    if not raw:
        return dict(_cap_state)
    try:
        import torch
        cap_mb = float(raw)
        total_mb = torch.cuda.get_device_properties(0).total_memory / 1048576
        frac = max(0.05, min(1.0, cap_mb / total_mb))
        torch.cuda.set_per_process_memory_fraction(frac, 0)
        _cap_state.update(applied=True, cap_mb=cap_mb, total_mb=round(total_mb, 1), fraction=round(frac, 4))
    except Exception as ex:  # noqa: BLE001  훅 실패가 추론을 막으면 안 된다 — 실패를 **기록**하고 계속
        _cap_state["error"] = f"{type(ex).__name__}: {ex}"
    return dict(_cap_state)


def cuda_mem_cap_status() -> dict:
    return dict(_cap_state)


def pick_device(prefer_mps: bool = True, env: str = _ENV) -> str:
    """추론 장치를 'cuda'|'mps'|'cpu' 중에서 고른다.
    env(VIGENT_DETECT_DEVICE)로 강제 가능. prefer_mps=False면 MPS를 건너뛴다(YOLO 안정성)."""
    forced = os.environ.get(env, "").strip().lower()
    if forced in ("cpu", "mps", "cuda"):
        if forced == "cuda":
            apply_cuda_mem_cap()
        return forced
    try:
        import torch
        if torch.cuda.is_available():
            apply_cuda_mem_cap()              # [I-3] 상한 모사(미설정이면 no-op)
            return "cuda"                     # CUDA(리눅스/엔비디아)는 안정적 → 최우선
        if prefer_mps and torch.backends.mps.is_available():
            return "mps"                      # Apple Silicon(rfdetr 등 안정 모델만)
    except Exception:  # noqa: BLE001  torch 문제여도 최소 CPU로 동작
        pass
    return "cpu"
