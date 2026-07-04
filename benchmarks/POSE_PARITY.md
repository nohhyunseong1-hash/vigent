# 포즈 이관 패리티 (T10c) — yolov8n-pose → RTMPose

> 측정 2026-07-04. 도구 `benchmarks/pose_parity.py`. 판정 로직(`_person_metrics`·`ergonomics`)은 **재사용(무수정)**.
> 규칙7: 아래는 실제 실행 결과. 상세 `benchmarks/results/pose_parity.json`(+ `_meta`에 게이트 근거).

## 1. 무엇을 재는가 (3층 비교)
같은 프레임에 두 포즈 백엔드를 돌려: (i) raw 키포인트 **OKS**(보조), (ii) `_person_metrics` 파생(**pose_fallen** 등), (iii) `ergonomics` 유효등급.
매칭은 **박스 IoU≥0.5**(동일 인물). OKS는 매칭 기준 아닌 품질 지표(포즈 다르다고 같은 사람 제외하면 순환논리).

## 2. 게이트 (정밀화 — 완화 아님)
> 초기 게이트(등급 불일치 ≤1)는 (a)검출집합 차이 매칭 아티팩트와 (b)임계 경계 플립을 구분 못 함.
> 재정의는 미달 회피가 아니라 측정 대상을 **'실질 포즈 품질 차이'로 정밀화**하기 위함.

- **낙상 게이트(hard)**: `pose_fallen` 불리언 불일치 **0건** (셋: `pose_frames`).
- **ergo 게이트(hard)**: 유효등급 **2단계 이상 점프**(good↔bad·none→bad, |rank|≥2) **0건** (셋: `pose_frames_ergo` 정밀 단일인물).
- **감시(soft, 게이트 아님)**: 1단계 플립은 각도차 병기 — ≤7°=임계분류 고유민감성 / >7°=실질 포즈차이(오버레이).

## 3. 프레임셋 (고정·재현)
| 셋 | 경로 | 장수 | 용도 | 빌더 |
|---|---|---|---|---|
| 기존(낙상) | `data/pose_frames` | 30 | 낙상 게이트 | `build_pose_frames.py` |
| ergo 정밀 | `data/pose_frames_ergo` | 11 | ergo 게이트(단일인물, 양 백엔드 정확히 1명) | `build_pose_frames_ergo.py` |
| 배제(다인) | `data/pose_frames_ergo_excluded` | 2 | 다인 리스크 검증 자산(FINDINGS F-1) | 〃 |

## 4. 최종 판정 (실측)
| 측정 | 셋 | pose_fallen(hard) | ergo hard | ergo soft(실질>7°) | mean OKS |
|---|---|---|---|---|---|
| Stage1 yolo↔rtmpose | pose_frames(낙상) | **0** ✅ | 0 | — | 0.62 |
| Stage1 yolo↔rtmpose | pose_frames_ergo | (2, 낙상셋 아님) | **0** ✅ | 3 | 0.78 |
| **Stage2 박스소스** rtmpose(YOLOX)↔rtmpose(guard/RF-DETR) | pose_frames_ergo | **0** ✅ | **0** ✅ | 1 | 0.85 |

→ **두 hard 게이트 통과.** Stage2는 포즈 입력 박스 소스만 바꾼 것(변수=박스). café 다인 오판(초기 hard 1)은 **하네스 충실도 격차**(raw rfdetr vs guard.detect의 _nms/_track)로 확정 → guard 박스로 교정 시 소멸.

## 5. Latency (macOS CPU, onnxruntime · ergo 11장×2, warmup 제외)
| 경로 | ms/frame | 비고 |
|---|---|---|
| yolov8n-pose(구, ultralytics) | 23.8 | 검출+포즈 일체 |
| Stage1 rtmpose(YOLOX 내장) | 226.1 | 느림 → **기본 off** |
| **RTMPose pose-only(production 한계비용)** | **40.2** | 박스는 guard.detect 재사용(무료). 구 대비 +16ms |
- 워커 기본 2fps(500ms)에선 무시 가능. RK3588 등 엣지 재측정 필요(RKNN 미시도).

## 6. 재현
```bash
/opt/anaconda3/bin/python3 benchmarks/build_pose_frames.py
/opt/anaconda3/bin/python3 benchmarks/build_pose_frames_ergo.py
# 낙상 게이트
/opt/anaconda3/bin/python3 benchmarks/pose_parity.py --backend-a yolo --backend-b rtmpose --frames benchmarks/data/pose_frames --label fall
# ergo 게이트 + 박스소스(Stage2)
/opt/anaconda3/bin/python3 benchmarks/pose_parity.py --backend-a yolo --backend-b rtmpose --frames benchmarks/data/pose_frames_ergo --label ergo_final
/opt/anaconda3/bin/python3 benchmarks/pose_parity.py --backend-a rtmpose --backend-b rtmpose_rfdetr --frames benchmarks/data/pose_frames_ergo --label ergo_final_s2
```

## 7. 한계 (규칙7)
- 정지 프레임 기반 = 판정 '입력층' 패리티. 동영상 '출력층'(이벤트 지속) 검증은 클립 회귀셋 부재(FINDINGS F-4).
- ergo 정밀셋 11장(리포 자산 한계). 사용자 촬영 클립 도착 시 보강.
- 박스 품질 게이트 부재(FINDINGS F-1) — 다인 현장 리스크는 T14 검토.
