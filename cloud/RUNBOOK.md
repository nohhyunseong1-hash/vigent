# T10b 클라우드 학습 런북 — ppe + fire_smoke RF-DETR (CUDA)

> 목적: 로컬 M5 MPS 다중클래스 NaN 버그 우회. **학습만** 클라우드(CUDA), 산출물은 **가중치 파일만 로컬 회수**.
> 제품 런타임 로컬 원칙 불변. 공개/허용 데이터만: css_safety(CC BY 4.0, 확인됨) · D-Fire(공개).

## ★ 실행 경로 = Google Colab (RunPod 결제 불가 → 전환)
- **노트북**: `cloud/VIGENT_T10b_train.ipynb` (Colab 업로드 → T4 GPU 런타임).
- **세션 끊김 복원력**: 에폭마다 Drive 체크포인트 + 자동 재개. 끊기면 위에서부터 재실행하면 이어짐.
- **Colab 보안수칙**(RunPod 수칙의 Colab판):
  1. **시크릿 미탑재**: `.env`·API키·웹훅 등 어떤 비밀도 노트북/Drive에 올리지 않음(학습은 데이터+코드만).
  2. **완료 후 Drive 데이터 소멸**: `vigent_t10b/`(css_safety·D-Fire·체크포인트) 삭제 확인. 가중치만 로컬 회수 후.
  3. **가중치 SHA256 대조**: 노트북이 `.sha256` 생성 → 로컬 다운로드 후 `shasum -a 256` 재계산 대조.
  4. **비용**: Colab 무료 T4는 과금 없음($15 상한 무의미). Pro 구독 시에만 비용 발생 — 무료 티어 사용 권장.
  5. **버전 파일명**: `ppe_rfdetr_v1.pth`·`fire_smoke_rfdetr_v1.pth` → 회수 후 weights_manifest 등재.
- **T4 예상시간**: 노트북 스모크 셀이 에폭당 시간 실측 → 총시간 자동 추정 출력(T4는 4090보다 느림 → ppe 50ep 수시간 예상, 끊김 재개로 누적).
- 아래 RunPod 스크립트(setup_env/run_all)는 **참고/대안**(유료 CUDA 확보 시). 게이트·보안 원칙은 공통.

---

## 0. 인스턴스 스펙
- **플랫폼**: RunPod Community (또는 Vast.ai)
- **GPU**: RTX 4090 24GB 1장 (RF-DETR Nano 경량 — A100 불필요)
- **이미지**: `runpod/pytorch:2.x-py3.11-cuda12.x` (CUDA torch 사전탑재) 또는 동급 PyTorch+CUDA
- **디스크**: 컨테이너 30GB + 볼륨 20GB(데이터·체크포인트) 이상
- **예상**: ~5–7h, ~$2(4090 $0.34/hr), **상한 $15 초과 시 중단**

## 1. 클라우드 보안 수칙 (필수 — 위반 시 중단)
1. **일회용 SSH 키**: 이 세션 전용 ephemeral 키쌍 생성(`ssh-keygen -t ed25519 -f ./cloud_ephemeral -N ""`), 종료 후 폐기. 개인 상시 키 미사용.
2. **시크릿 미탑재**: `.env`·API 토큰·ANTHROPIC/OPENAI 키·웹훅 URL 등 **어떤 비밀도 인스턴스에 올리지 않음**. 학습은 데이터+코드만 필요.
3. **종료 즉시 terminate + 데이터 소멸 확인**: 가중치 회수 완료 → 인스턴스 terminate → 볼륨 삭제 → 콘솔에서 소멸 확인. (stop 아닌 **terminate**.)
4. **가중치 무결성 대조**: 인스턴스에서 SHA256 생성 → 로컬 다운로드 후 재계산 → **일치 확인**(전송 변조·손상 검출).
5. **비용 상한 $15**: 누적 과금 모니터, 초과 조짐 시 중단·보고.

## 2. 단계 (턴키)
로컬에서 css_safety COCO(ppe_rfdetr_ds)는 이미 빌드됨 → 업로드. D-Fire는 인스턴스가 공개소스 직접 다운로드(업로드보다 빠름).

```
# [로컬] ppe COCO 업로드(css_safety 는 상업데이터 → 공개소스 없음, 직접 전송)
scp -i cloud_ephemeral -r ~/Downloads/ppe_rfdetr_ds  root@<IP>:/workspace/data/ppe_rfdetr_ds
# [로컬] 학습 코드 업로드(비밀 없는 것만)
scp -i cloud_ephemeral cloud/setup_env.sh cloud/build_fire_smoke_train_ds.py cloud/run_all.sh \
    training/rfdetr_train.py benchmarks/run_eval.py benchmarks/presence_eval.py \
    benchmarks/eval_rfdetr_custom.py  root@<IP>:/workspace/

# [인스턴스]
bash setup_env.sh                 # 환경(rfdetr + 학습 deps)
bash run_all.sh                   # D-Fire 다운로드 → fire COCO 빌드 → ppe 학습 → fire 학습 → 게이트 → SHA
# 산출: /workspace/out/ppe_rfdetr_v1.pth, fire_smoke_rfdetr_v1.pth + *.sha256 + gate_report.txt

# [로컬] 가중치 회수 + SHA 대조
scp -i cloud_ephemeral root@<IP>:/workspace/out/*.pth root@<IP>:/workspace/out/*.sha256 ./recovered/
shasum -a 256 recovered/*.pth   # → *.sha256 와 대조

# [종료] terminate + 볼륨 삭제 + ephemeral 키 폐기
rm -f cloud_ephemeral cloud_ephemeral.pub
```

## 3. 게이트 판정 기준
### ppe (기존 프롬프트 유지)
- **raw mAP@50 ≥ 73.2** (YOLO baseline 75.20 − 2%p). 통과 시 "동일출처 데이터 누출 가능성 감안" 명시.
- 보조: pipeline mAP · confidence 분포(과소학습 여부 — 클라우드 CUDA면 정상 예상).

### fire_smoke (신규 제안 — presence 기반, box mAP 는 스키마 비호환 참고치)
box mAP 는 D-Fire 어노테이션 스키마 비호환이라 게이트 부적합(T13/T14-F 확립). presence(이미지수준 유무) 기반으로 판정:
- **Gate A(저하 없음)**: RF-DETR **raw presence AP: fire ≥ 81%, smoke ≥ 88%** (YOLO baseline fire 83·smoke 90 − 2%p).
- **Gate B(배포 목표 = 진짜 성공)**: **pipeline presence recall 개선** — YOLO 배포 recall fire 53.64%/smoke 24.85%(F-6 약점)를 **초과**하면서 FAR 악화 없음. 이게 이관 실익.
- **보고 항목**: box mAP(raw+pipeline, 참고) · presence AP(raw) · presence recall/precision/FAR(pipeline) · confidence 분포.
- 판정: 통과/부분통과/미달 3단계. 부분통과·미달 시 멈추고 선택지 보고(forklift·ppe와 동일 형식).

## 4. 학습 설정 (forklift·로컬과 동일 트레이너, device=cuda)
- RFDETRNano, 50ep(ppe) / 15ep→resume 30ep(fire_smoke 대안D), batch·grad_accum 은 4090 VRAM 맞춰 상향 가능(예 batch 8/16).
- **본학습 전 1-epoch 스모크로 loss 유한 먼저 확인**(MPS 버그 재발 없음 검증 — CUDA면 정상 예상).
- 산출 가중치: 버전 파일명(`ppe_rfdetr_v1.pth`·`fire_smoke_rfdetr_v1.pth`) + `weights_manifest.json` 등재(회수 후 로컬에서).

## 5. 회수 후 로컬 이관 (기존 forklift 패턴)
- vision.yaml `backend.ppe/fire_smoke → rfdetr` + `rfdetr_weights` 등록 → 어댑터 커스텀 매핑(class_names) → 운용점 튜닝 → 회귀(±0.1) → 커밋.
- A-4 달성: ultralytics 배포 잔존 0 → requirements 에서 ultralytics 를 측정 전용(requirements-eval)으로 이관.
