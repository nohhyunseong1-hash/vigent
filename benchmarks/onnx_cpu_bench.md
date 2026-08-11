# [C-2] CPU 추론 최적화 — ONNX Runtime fp32/INT8 실측 (2026-08-11)

> **해석 주의(규칙7)**: 아래 절대 ms 값은 개발기(AMD Ryzen 9 9900X 12C/24T) CPU 강제 모드
> 실측이다 — 배포 후보(N100급 미니PC·중고 사무용 i5)의 값이 아니다. §4의 환산치는
> "5~10배(N100)"·"2~4배(중고 i5)" 느리다는 **가정**을 곱한 추정이며, 실측이 아니다.

## 1. ONNX 변환 가능성 — 성공(첫 시도, 함정 재현 안 됨)

RF-DETR 커뮤니티에 알려진 ONNX export 실패 이슈를 우려했으나(사용자 지시), **저장소
안에서 관련 ADR 문서를 찾지 못했다** — 언급된 문서가 이 리포지토리엔 없거나 다른 이름일
수 있다(규칙7, 추측으로 출처를 지어내지 않음). 대신 직접 시도했다:

- 필요 패키지(`rfdetr[onnx]`: onnx·onnxsim·onnx_graphsurgeon·polygraphy) 설치 승인
  받아 진행 — `onnxsim` 기본 버전(0.5.0+)은 이 환경에 cmake가 없어 소스 빌드 실패,
  **0.4.36으로 핀**(prebuilt wheel 존재)해 해결. torch/torchvision/numpy/CUDA는 설치
  전후 완전 동일 확인(dry-run으로 사전에도 미포함 확인).
- `RFDETRNano(pretrain_weights="ppe_rfdetr_v1.pth", resolution=384).export(format="onnx")`
  **첫 시도에 성공**(115MB, 에러 0). onnxruntime으로 로드·추론까지 정상 확인
  (`input:(1,3,384,384)` → `dets:(1,300,4)`·`labels:(1,300,11)`, raw pred_boxes/
  pred_logits — PostProcess 후처리는 그래프에 안 들어있고 별도 적용 필요).
- **결론**: 이 버전(rfdetr==1.8.0)에서는 export 자체가 함정이 아니었다. 커뮤니티 이슈는
  더 이전 버전이나 다른 옵션(동적 배치·TFLite 등) 조합에서였을 가능성 — 미확인.

## 2~3. 지연 실측 + dev 74장 정확도 재채점 (통합 측정)

방법론: `benchmarks/c2_onnx_cpu_bench.py`(신규, 재사용 가능) — `guard._get_model("ppe")`로
실제 배포 `RfdetrDetector`(letterbox·finalize_box·class_names 매핑 포함)를 로드하고,
ONNX 백엔드는 `.model.predict`만 onnxruntime 함수로 교체(나머지 파이프라인 100% 동일
코드 경로 — 후처리 차이로 인한 왜곡을 원천 차단). 정확도 채점은 `y2_test_baseline.py`의
검증된 로직(person/PPE IoU≥0.5 매칭, NO-Hardhat 구간+Clopper-Pearson CI)을 그대로
재사용했다. VIGENT_DETECT_DEVICE=cpu 강제, Docker Desktop 종료+`wsl --shutdown` 시도
(관리자 권한 없어 `vmmem` 완전 종료는 못 했으나 **측정 시점 CPU 사용률 0% 확인** — 오염
위험 낮음, 완전한 클린 측정은 아님, `docs/benchmark_measurement_hygiene.md` 규정에 따라
명시).

**★첫 측정에서 ONNX 쪽 NO-Hardhat 재현율이 크게 떨어져(상한 100%→78.6%) 조사한 결과,
내 벤치마크 스크립트의 전처리 버그였다**(PIL `.resize()` 기본 보간=BICUBIC vs RF-DETR
내부 `torchvision.transforms.functional.resize()` 기본 보간=BILINEAR+antialias, 불일치).
`TF.to_tensor→TF.resize→TF.normalize` 순서로 rfdetr 내부 코드를 정확히 재현하도록
수정한 뒤 재측정 — 아래는 **수정 후(올바른 전처리) 결과**다.

| 백엔드 | 지연 p50 | p95 | mean | person F1 | PPE F1 | NO-Hardhat 구간(하한/상한) |
|---|---|---|---|---|---|---|
| torch fp32(기준선) | 95.5ms | 110.6ms | 96.5ms | 75.6% | 76.6% | [25.9%, 100.0%](14/14 clear 매칭) |
| **ONNX Runtime fp32** | **51.6ms** | **58.1ms** | **52.2ms** | **75.6%** | **76.6%** | **[25.9%, 100.0%]**(14/14, torch와 완전 동일) |
| ONNX Runtime INT8(동적양자화) | 58.0ms | 61.3ms | 58.3ms | 74.0%(-1.6%p) | 74.2%(-2.4%p) | [22.2%, 85.7%](12/14, 2건 더 놓침) |

(원시 데이터: `benchmarks/results/c2_onnx_cpu_bench.json`, 74장 중 워밍업 10장 제외 64장
타이밍)

### 판정(규칙6)

- **ONNX Runtime fp32 → 채택**. torch 대비 **1.85배 빠르고(96.5ms→52.2ms) 정확도 손실
  0**(person/PPE/NO-Hardhat 전부 dev 74장에서 byte-for-byte 동일 결과) — 순수 이득,
  트레이드오프 없음.
- **ONNX Runtime INT8(동적양자화) → 기각**. fp32 ONNX보다 오히려 **더 느리고**(58.3ms >
  52.2ms — 동적양자화의 양자화/역양자화 오버헤드가 RF-DETR의 attention/deformable-attn
  연산이 많은 구조에서 이득을 상쇄한 것으로 추정, 미확정) **정확도도 떨어진다**(PPE F1
  -2.4%p, NO-Hardhat 2건 추가 누락) — 속도·정확도 둘 다 손해라 기각 사유가 이중으로
  명확하다. 정적 양자화(캘리브레이션)·OpenVINO는 이번 실측 범위 밖(시간·범위 제약,
  fp32 ONNX만으로 이미 목표 응답을 얻어 우선순위 낮춤) — 필요 시 다음 스텝 후보로 남긴다.
- **OpenVINO(d)는 시도하지 않았다**(과제상 "가능하면"으로 선택 사항 — fp32 ONNX가 이미
  순이득을 냈고, OpenVINO도 보통 ONNX를 중간 표현으로 거치므로 이번에 발견된 이슈(전처리
  불일치)와 무관한 추가 이득이 있을지는 미검증).

## 4. N100급·중고 i5 감당 카메라 수 재환산 (추정, 미실측)

ONNX fp32 채택 기준(52.2ms/프레임, 이 개발기): 사용자 지정 배율로 환산하면(§0 해석 주의)

| 등급 | 배율 가정 | 환산 지연/프레임 | 최대 처리량(추정) | "1fps/카메라 × N대" 커버 가능성 |
|---|---|---|---|---|
| N100급 미니PC | 5~10배 느림 | 261~522ms | **1.9~3.8fps**(집계) | 2대: 대체로 가능(추정) / **4대: 근소하게 미달**(3.8fps < 4fps 필요, 낙관적 가정에서도) |
| 중고 사무용 i5 | 2~4배 느림 | 104~209ms | **4.8~9.6fps**(집계) | 2~4대: 여유 있게 가능(추정) |

torch(비최적화) 기준으로도 참고 환산: 96.5ms × 5~10배 = 483~965ms/프레임 → N100급은
**1대조차 1fps 예산에 빠듯**(965ms는 1000ms 예산에 거의 근접) — ONNX 최적화 없이는
N100 경로가 사실상 성립하지 않았을 것이라는 뜻이기도 하다(최적화의 실익이 여기서
드러남).

## 5. 결론 — 초저가 경로 판정

**부분 성립 / 조건부.** ONNX fp32 최적화(1.85배)는 실제로 유효하고 정확도 손실도 없어
채택할 가치가 있다. 그러나 이 최적화를 적용해도 **N100급(25만원)은 "카메라 2~4대"
전체 범위를 안정적으로 커버하지 못한다** — 추정상 2대는 가능해 보이나 4대는 근소하게
미달(여유 없음, 실측 오차·다른 프로세스 경합 등을 고려하면 더 나쁠 가능성이 높음).

**권장**: **중간급(40~60만원대, 중고 사무용 i5) 경로를 기본으로 확정**한다 — 이 등급은
ONNX 최적화 적용 시 2~4대를 여유 있게 커버할 것으로 추정된다(4.8~9.6fps 집계 처리량,
목표 4fps 대비 넉넉한 마진). N100급(25만원)은 **카메라 1~2대의 초소형 현장**에 한해
조건부 후보로 남기되, 반드시 실제 기종으로 재실측한 뒤 채택 여부를 결정할 것 — 이번
desktop 실측은 구조(ONNX가 순이득이라는 것)와 근사 배율만 확인했을 뿐, N100의 절대
처리량은 여전히 추정치다(규칙7).

## 재현 방법

```bash
# 1. ONNX 내보내기(fp32)
python -c "
from rfdetr import RFDETRNano
m = RFDETRNano(device='cpu', pretrain_weights='vigent-core/weights/ppe_rfdetr_v1.pth', resolution=384)
m.export(output_dir='<출력폴더>', format='onnx', opset_version=17)
"

# 2. INT8 동적 양자화(선택 — 이번 실측에서는 기각됨)
python -c "
from onnxruntime.quantization import quantize_dynamic, QuantType
quantize_dynamic(model_input='<출력폴더>/rfdetr-nano.onnx',
                  model_output='<출력폴더>/rfdetr-nano-int8.onnx', weight_type=QuantType.QInt8)
"

# 3. 벤치마크(각 백엔드별로 1회씩 — dev 74장 지연+정확도 재채점)
VIGENT_DETECT_DEVICE=cpu VIGENT_ALLOW_FALLBACK=1 python benchmarks/c2_onnx_cpu_bench.py --backend torch
VIGENT_DETECT_DEVICE=cpu VIGENT_ALLOW_FALLBACK=1 python benchmarks/c2_onnx_cpu_bench.py \
  --backend onnx_fp32 --onnx-path <출력폴더>/rfdetr-nano.onnx
VIGENT_DETECT_DEVICE=cpu VIGENT_ALLOW_FALLBACK=1 python benchmarks/c2_onnx_cpu_bench.py \
  --backend onnx_int8 --onnx-path <출력폴더>/rfdetr-nano-int8.onnx
```

측정 전 `docs/benchmark_measurement_hygiene.md` 절차(Docker Desktop 종료+`wsl --shutdown`)
준수 권장. 결과: `benchmarks/results/c2_onnx_cpu_bench.json`(백엔드별 누적 기록).

## 다음 단계(이번 스코프 밖)

- ONNX 런타임 경로를 실제 서빙 코드(`detectors/rfdetr_adapter.py`)에 배선하는 건 이번에
  하지 않았다 — 측정까지가 이번 스코프. 채택하려면 별도 구현 작업(설계·테스트·게이트)
  필요.
- N100급 실기종 확보 후 `benchmarks/c2_onnx_cpu_bench.py`를 그대로 재실행해 "2대는 되고
  4대는 안 된다"는 이번 추정을 검증할 것.
- INT8은 기각했지만, 정적 양자화(대표 이미지 캘리브레이션)나 OpenVINO는 다른 결과를 낼
  가능성이 있다 — 우선순위는 낮지만 후보로 남긴다.
