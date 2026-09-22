# PPE GPU 경로 조사 — 선택지 비교와 권고 (H-2, 2026-09-23)

> **성격**: 조사·권고까지만이다. **구현하지 않았다.** PPE 경로 변경은 결정권자의 판단 뒤에 한다.
> **측정 기계**: 개발기(Ryzen 9 9900X · **RTX 5070 Ti** · Win11). ★**RTX 5060·현장 노트북이 아니다.**

---

## 0. 왜 이걸 보는가

파일럿기 병목은 **CPU** 다(노트북 소크 실측: 시스템 CPU 84~94%, 합격선 70% 미달).
VRAM 은 8GB 중 약 1.3GB 만 쓴다 — **남는 자원이 있다.**
그런데 PPE 슬롯은 `onnx-cpu` 로 돌아 **모자란 자원(CPU)을 쓰고 남는 자원(GPU)을 논다.**
속도 문제가 아니라 **자원 배분 문제**다.

---

## 1. 현재 PPE 가 onnx-cpu 인 이유 — 설정이다, 호환성 문제가 아니다

| 무엇 | 위치 | 내용 |
|---|---|---|
| 설정 | [`deploy/portable/portable_overrides.yaml`](../../deploy/portable/portable_overrides.yaml) | `detect.backend: torch` → **`onnx-cpu`** 로 치환 |
| 적힌 사유 | 같은 파일 | *"포터블은 CPU 전용 torch(PyPI 기본 휠)를 싣는다"* |
| 적용 결과 | [`rfdetr_adapter.py:199`](../../vigent-core/detectors/rfdetr_adapter.py#L199) | 슬롯 가중치와 같은 이름의 `.onnx` 가 있으면 ONNX 경로 |
| 장치 | [`rfdetr_adapter.py:204`](../../vigent-core/detectors/rfdetr_adapter.py#L204) | `self.device = "cpu"` **고정** |
| 실행 공급자 | [`rfdetr_adapter.py:119`](../../vigent-core/detectors/rfdetr_adapter.py#L119) | `providers=["CPUExecutionProvider"]` **하드코딩** |

★**전제가 이미 깨졌다.** `-Gpu` 빌드는 CPU 전용 torch 를 싣지 않는다 — cu130 torch(2.73GB)를 싣는다.
즉 `onnx-cpu` 치환의 **근거였던 조건이 GPU 빌드에서는 성립하지 않는다.**

person 슬롯은 `.onnx` 가 포터블에 없어 자동으로 torch 로 폴백 → **이미 GPU 를 쓴다.**
GPU 를 안 쓰는 것은 **`.onnx` 가 동봉된 슬롯(ppe)** 뿐이다.

★포터블은 `ppe_rfdetr_v1.onnx`(109.7MB)와 **`ppe_rfdetr_v1.pth`(115.3MB)를 둘 다** 싣고 있다.
→ (B) 로 가는 데 **새로 넣을 파일이 없다.**

---

## 2. 실측 비교 (PPE 슬롯 1프레임, 384px, 예열 5회 후 20회)

입력: 사고영상 `KakaoTalk_20260807_000438282.mp4` 30번째 프레임(720×406).
ONNX 세션 옵션은 **앱과 동일**하게 맞췄다(`intra_op=4 · inter_op=1 · spin=off`,
[`ort_tune.py`](../../vigent-core/ort_tune.py) 기본값).

| 경로 | 지연 평균 | p95 | ★**CPU 시간/추론** | 코어 점유 | VRAM(torch) | 패키지 용량 | 구현 난이도 |
|---|---|---|---|---|---|---|---|
| **(C) onnx-cpu — 현행** | 60.5 ms | 65.0 | **175 ~ 181 ms** | **2.90 ~ 3.00** | — | 기준 6.49 GB | 변경 없음 |
| **(A) onnxruntime-gpu** | **5.9 ~ 7.9 ms** | 7.0 ~ 9.3 | **5.5 ~ 7.8 ms** | 0.93 ~ 0.99 | 미계측(별도 할당자) | **+0.17 GB** (6.66) | **코드 변경 필요** |
| **(B) torch 경로 통일** | 12.2 ms | 13.1 | **12.5 ms** | 1.02 | **268 MB** | **±0** (.onnx 제거 시 −0.31 GB) | **설정 1줄** |

**읽는 법**: 핵심 열은 지연이 아니라 **CPU 시간/추론**이다. (C)는 한 번 추론에 CPU 를 **175ms**
태운다. (B)는 **12.5ms** — **14배** 적다. (A)는 7.8ms 로 (B)보다 조금 더 낫다.

### 참고 — 튜닝 없이 재면 (C)가 훨씬 나빠 보인다

ORT 기본 SessionOptions(스핀 on·intra_op=코어수)로 재면 (C)는 **538 ms/추론 · 11.6코어**다.
앱은 이미 `tune_sessions` 로 이걸 끄고 있으므로 **위 표(175ms)가 맞는 값**이다.
★처음 이 비교를 할 때 기본 옵션으로 재서 (C)를 과장했다 — 앱 설정으로 다시 쟀다.

---

## 3. (A) 검증 결과 — 공존은 되지만 ★조용한 폴백 위험이 있다 (R-9)

지시대로 **실제로 설치해** 확인했다(포터블 복사본 `D:\vigent_portable_ortgpu`,
`onnxruntime-gpu==1.30.0`, **nvidia-\* 패키지는 설치하지 않음**).

| 시험 | 결과 |
|---|---|
| torch(cu130) import → ORT CUDA 세션 | ✅ `['CUDAExecutionProvider', ...]` · 추론 5.8ms · torch 이후에도 정상 |
| ORT import 먼저 → torch import → 세션 | ✅ 동일하게 성공 |
| ★**torch 를 아예 import 하지 않고** ORT CUDA 세션 | ❌ **`cublasLt64_13.dll` 없음 → CPU 로 폴백** |

마지막 줄이 R-9 다. 실패 메시지는 **로그로만** 나가고 **예외는 안 난다**:

```
Error loading "onnxruntime_providers_cuda.dll" which depends on "cublasLt64_13.dll" which is missing.
Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*, and the latest MSVC runtime.
providers: ['CPUExecutionProvider']      ← 조용히 CPU 로 내려앉는다
```

즉 **ORT 의 CUDA 는 torch 가 `torch\lib` 을 DLL 검색경로에 넣어 준 덕분에만 동작한다.**
import 순서가 바뀌거나 person 슬롯이 torch 를 안 쓰게 되는 날, PPE 는 **아무 말 없이 CPU 로
되돌아가고 CPU 가 다시 포화된다.** 이건 이 프로젝트가 반복해서 당한 **조용한 실패** 유형이다.

★부수 소득: ORT 오류 메시지가 *"the latest MSVC runtime"* 을 요구한다 — H-1 의 VC++ 검사와 같은 방향.

(A)로 가려면 최소한 **CUDA EP 로 안 붙었을 때 기동을 실패로 보고** `/health` 에 드러내야 한다.
그 장치까지 만들어야 (A)가 (B)보다 나은 선택이 된다.

---

## 4. 권고 — **(B) torch 경로 통일**

| 근거 | 내용 |
|---|---|
| **CPU 를 14배 줄인다** | 175 → 12.5 ms/추론. 병목 자원을 직접 돌려준다 |
| **코드 변경 0** | `portable_overrides.yaml` 에서 GPU 빌드일 때 `detect.backend` 치환을 안 하면 끝 |
| **새 파일 0** | `ppe_rfdetr_v1.pth` 가 이미 포터블에 있다 |
| **조용한 폴백 없음** | torch 경로는 `device.pick_device()` 하나로 결정되고 `/health` 에 드러난다 |
| **용량이 줄어든다** | `.onnx` 3개(315MB)를 뺄 수 있다 (★뺀 뒤 동작은 미확인) |
| **되돌리기 쉽다** | 설정 한 줄이라 즉시 롤백 |

(A)는 CPU 를 조금 더 아끼지만(7.8 vs 12.5ms) **코드 변경 + 패키지 +179MB + R-9** 를 떠안는다.
그 차이(4.7ms/추론)는 4채널 2fps 기준 **초당 0.038코어** — R-9 를 감수할 만한 크기가 아니다.

**단, (B) 는 CPU 빌드 포터블에는 적용하면 안 된다.** CPU 전용 torch 에서 torch 경로는
onnx-cpu 보다 느리다(`benchmarks/onnx_cpu_bench.md`: onnx 가 1.85배 빠름).
→ **`-Gpu` 빌드일 때만** 치환을 건너뛰는 분기가 필요하다.

---

## 5. 아직 모르는 것 (정직하게)

- **RTX 5060·현장 노트북에서의 값은 모른다.** 위는 전부 5070 Ti 다.
- **4채널 동시 구동 시 시스템 CPU 는 이 표로 알 수 없다.** 단일 프레임 마이크로벤치다 → H-3.
- **VRAM**: `nvidia-smi --query-compute-apps` 가 이 기기에서 `[N/A]` 를 반환해(WDDM)
  프로세스 단위 VRAM 을 못 쟀다. torch allocated(268MB)만 안다. **ORT 가 쓰는 VRAM 은 미계측.**
- **정확도 동등성**: `.onnx` ↔ `.pth` 동등성 시험은 있으나(`tests/test_rfdetr_onnx_parity.py`)
  **GPU 경로에서 다시 확인하지 않았다.** (B) 채택 시 규칙6에 따라 변경 전후 비교가 선행돼야 한다.
- `.onnx` 3개를 뺀 패키지가 정상 동작하는지 **확인하지 않았다**(뺄셈으로 계산한 용량이다).

---

## 6. 재현 방법

```
# (C) 현행
D:\vigent_portable_gpu\python\python.exe ppe_path_bench.py onnx-cpu-tuned <weights> <video>
# (A) onnxruntime-gpu (별도 복사본에 onnxruntime-gpu==1.30.0 설치)
D:\vigent_portable_ortgpu\python\python.exe ppe_path_bench.py ort-cuda-tuned <weights> <video>
# (B) torch
D:\vigent_portable_gpu\python\python.exe ppe_path_bench.py torch-cuda <weights> <video>
```

스크립트는 [`scripts/bench/ppe_path_bench.py`](../../scripts/bench/ppe_path_bench.py).
