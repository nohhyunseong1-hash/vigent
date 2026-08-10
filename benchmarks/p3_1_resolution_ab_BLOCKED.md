# [P-3-1] PPE 해상도 A/B — ★차단됨(2026-08-10). 실행 전 반드시 읽을 것

`benchmarks/p3_1_resolution_ab.py`를 dev 74장 × {640,960,1280} × {앙상블 on,off}로 돌렸더니
**6개 조합 전부 완전히 동일한 수치**가 나왔다(person·NO-Hardhat·전체 PPE·지연 전부, 소수점까지
일치). 이게 "해상도가 영향 없다"는 결론이 아니라 **측정 자체가 안 되고 있다는 신호**라 즉시
원인을 추적했다.

## 근본 원인(실측으로 확인한 사실 연쇄, 규칙7)

1. **`vigent-core/detectors/rfdetr_adapter.py`의 `detect()`가 `imgsz` 매개변수를 받기만 하고
   실제로 안 쓴다.** `self.model.predict(pil, threshold=conf)` 호출에 해상도 관련 인자가
   전혀 안 들어간다(소스 직접 확인, `detect()` 시그니처엔 `imgsz` 가 있지만 본문 어디서도
   참조 안 됨).
2. RF-DETR 라이브러리 자체는 `predict(images, threshold, shape=(h,w), ...)` 로 **호출별 해상도
   오버라이드를 지원한다**(라이브러리 소스의 `predict()` docstring 확인: "Optional (height, width)
   tuple... overrides the model's default inference resolution").
3. 그런데 `rfdetr_adapter.py.__init__`이 모델 로드 직후 `self.model.optimize_for_inference()`를
   호출한다(37~40행) — 이게 모델을 **그 시점 기본 해상도로 고정 컴파일**해버린다. 기본 해상도는
   `RFDETRNanoConfig.resolution`(기본값 **384**, 실측: `RFDETRNanoConfig()` 인스턴스에서 직접
   확인) — `imgsz` 를 어디서도 안 넘겼으니 항상 384다.
4. **최적화된 모델에 다른 shape 를 주면 예외가 난다**(직접 재현):
   ```
   ValueError: Resolution mismatch. Model was optimized for resolution 384x384,
   but got 640x640. You can explicitly remove the optimized model by calling
   model.remove_optimized_model().
   ```
   `guard.detect()`의 `except Exception: continue`(저하 없음 설계)가 이 예외를 조용히 삼켜서,
   `imgsz=640/960/1280`로 부른 person 슬롯이 **매번 검출 0건으로 통째로 비활성화**됐다 —
   `p3_1_resolution_ab.py`가 3개 해상도에서 똑같은 숫자를 낸 진짜 이유는 "640/960/1280 결과가
   같아서"가 아니라 **384(shape 미지정 default 경로)만 항상 쓰이고 있었기 때문**이다.
   (`p3_1_resolution_ab.py` 자체는 `imgsz`를 정상적으로 넘기는 코드다 — 버그는 그 아래
   어댑터 계층에 있다.)

## 이게 뜻하는 것 (규칙7 — 파급 범위)

- **`config/tuning.yaml`의 `detect.imgsz: 960`, `EVAL.md`·`field_eval_results.md`의
  "imgsz=960(측정=배포 조건)" 서술은 실제로 RF-DETR 백엔드에 적용된 적이 없다.** person·ppe·
  forklift·fire_smoke 전부 `vision.yaml`에서 backend=rfdetr(T10b 이관 완료)이므로, **현재
  배포된 모든 검출은 384×384로 돈다** — 960이 아니다. 이건 새 저하가 아니라(오늘 처음 생긴 문제가
  아니라 T10a/T10b 이관 이후 계속 이 상태였다) 문서와 실제가 어긋나 있었다는 뜻이다.
- **이번 세션의 기존 측정치는 이 사실에 영향받지 않는다** — [P-0] dev/test 분할, [P-1] GPU 전환
  속도(384 그대로 GPU만 바뀜), [P-2] 이중신호 앙상블 비교(양쪽 다 항상 384라 비교 자체는 유효)
  전부 "384 고정" 이라는 동일 조건 아래 잰 값이라 내부 비교로서는 문제없다. **단, 그 수치들을
  "imgsz=960 기준"이라고 인용하면 안 된다** — 실제로는 384 기준이었다.
- **perf_improvement_plan.md §0의 "PPE 정답의 61%가 화면의 1% 미만 소형 객체, 해상도 문제일 수
  있다" 가설이 오히려 더 그럴듯해졌다** — 실제 입력 해상도가 960이 아니라 384였다면, 작은 객체가
  모델이 보는 화면에서 지금까지 가정했던 것보다 훨씬 더 작게 들어갔다는 뜻이다.

## 해상도를 바꾸려면 뭐가 필요한가 (분석만, 미구현)

`optimize_for_inference()`가 해상도를 컴파일 시점에 고정하는 구조라, **호출마다 해상도를 바꾸는
건 이 최적화 경로에서 근본적으로 지원 안 된다.** 선택지:

1. **해상도별로 별도 모델 인스턴스를 미리 로드**(각각 `resolution=640/960/1280`으로
   `RFDETRNanoConfig` 구성 → 각각 `optimize_for_inference()`) — 메모리·워밍업 비용이 해상도
   개수만큼 배가. A/B 실험엔 이 방식이 필요(정확한 비교엔 매번 그 해상도로 진짜 최적화된 모델을
   써야 함).
2. **`optimize_for_inference()`를 아예 안 부르거나 `remove_optimized_model()`로 풀기** — 유연하게
   해상도를 바꿀 순 있지만, 지금까지 이 세션 전체(P-1 GPU 10배 등)에서 측정한 지연 수치가 전부
   "최적화된 모델" 기준이었으므로, 최적화를 풀면 **그 수치들과 더 이상 비교 가능하지 않다**(별도로
   재측정 필요).

**둘 다 코드·모델 로딩 구조를 건드리는 변경**이라 이 자리에서 임의로 진행하지 않았다. 어느 쪽으로
갈지, 아니면 P-3-1을 다른 방식(예: YOLO 백엔드로 일시 전환해 비교, 또는 아예 다른 우선순위로
전환)으로 접근할지 사용자 결정이 필요하다.

## 이 발견까지 실행한 것 (재현 가능)

- `benchmarks/p3_1_resolution_ab.py`: 정상 코드, dev 74장에 imgsz/앙상블 6조합 실행 — 현재는
  전부 384 고정이라 조합 간 차이가 안 나온다는 걸 보여주는 증거로 남겨둔다(원본 결과:
  `benchmarks/results/p3_1_resolution_ab.json`).
- `RFDETRNanoConfig()` 기본 `resolution` 필드 직접 확인 → 384.
- `model.model.predict(pil, threshold=0.1, shape=(640,640))` 직접 호출 → `ValueError: Resolution
  mismatch` 실측 재현.
- 코드에 아무 변경도 하지 않았다(진단 전용, 몽키패치는 인메모리 테스트뿐 — 저장 안 함).
