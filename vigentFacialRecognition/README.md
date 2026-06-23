# vigentFacialRecognition — VIGENT 얼굴 인식 모듈

VIGENT 플랫폼의 4번째 모듈(얼굴 인식)의 **기술 코어**. 출입통제·인가자 식별·무자격자
위험구역 진입 차단·근태 집계·재난 시 인원 식별 보조에 쓰인다.

- **정확도**: SFace LFW 99.4% 모델 기반 → 운용 임계값에서 **95%+** 충족.
- **속도**: 얼굴당 검출+인식 보통 **10~50ms** (CPU) → **1초 이내** 요건 충족.
- **라이선스(상용 안전)**: YuNet 검출 **MIT** + SFace 인식 **Apache-2.0**. 둘 다 상업적
  사용 가능. ⚠ InsightFace/CompreFace 의 사전학습 모델은 보통 **비상업 전용**이라 사업에
  부적합 — 그래서 본 모듈은 의도적으로 OpenCV Zoo 모델을 선택했다.

## 설치 / 실행

```bash
cd ~/Desktop/VIGENT

# 1) 모델 받기 (새 pip 설치 없음 — OpenCV는 이미 설치돼 있음)
python -m vigentFacialRecognition.download_models

# 2) 동의·고지 절차 완료 후에만 옵트인 활성화
export VIGENT_FR_ENABLED=1

# 3) 테스트 / 벤치마크
python -m unittest vigentFacialRecognition.tests.test_engine
python -m vigentFacialRecognition.benchmark --image face.jpg --runs 50
python -m vigentFacialRecognition.benchmark --data <사람별폴더> --threshold 0.40
```

코드에서:
```python
from vigentFacialRecognition import enroll_person, identify
import cv2
img = cv2.imread("hong.jpg")
enroll_person("hong", "홍길동", [img], purpose="현장 출입통제", consented_by="안전관리자")
for m in identify(cv2.imread("frame.jpg")):
    print(m.name or "unknown", m.similarity)
```

VIGENT 코어(main.py)에 장착(다음 단계, 승인 후):
```python
from vigentFacialRecognition.api import router as facial_router
app.include_router(facial_router)   # /facial/status, /enroll, /identify, /persons ...
```

## 환경변수
| 변수 | 기본 | 설명 |
|---|---|---|
| `VIGENT_FR_ENABLED` | `0`(OFF) | **옵트인 마스터 스위치**. 동의 절차 후에만 1 |
| `VIGENT_FR_THRESHOLD` | `0.40` | 코사인 임계값(↑ 엄격=오인식↓) |
| `VIGENT_FR_RETENTION_DAYS` | `365` | 생체정보 보존기간(일) |
| `VIGENT_FR_STORE_RAW` | `0` | 원본 얼굴 저장 여부(기본 미저장=데이터 최소화) |
| `VIGENT_FR_KEY` | (없음) | 임베딩 암호화 키. 있으면 Fernet 암호화 |

## ⚖️ 법적 체크리스트 (개인정보보호법 — 반드시 확인)
얼굴 임베딩은 **생체정보 = 민감정보**(개인정보보호법 §23, 시행령 §18). 코드의 안전장치
(옵트인·동의기록·보존기간·감사추적·암호화·삭제)는 **기술적 보호조치일 뿐**, 아래 **운영
절차**가 없으면 위법이 될 수 있다.

- [ ] **별도의 명시적 동의**: 일반 개인정보 동의와 분리된 민감정보 동의서(목적·항목·보유기간).
- [ ] **고지·게시**: 카메라 운영·생체정보 처리 사실 안내문 게시.
- [ ] **근로자 대상 시**: 근로기준법상 노사협의, 비례성(목적 달성 최소 범위).
- [ ] **목적 제한**: 등록 시 적은 `purpose` 외 용도 사용 금지.
- [ ] **보존기간·파기**: 기간 경과 시 `purge-expired` 로 자동 파기, 파기 기록 보존.
- [ ] **접근통제·암호화**: `VIGENT_FR_KEY` 설정, 데이터 폴더 접근 최소화.
- [ ] **정보주체 권리**: 열람·삭제(`DELETE /facial/persons/{id}`) 응대 절차.
- [ ] **자동화된 의사결정 주의**: 인식 결과를 불이익 처분의 **유일 근거로 쓰지 말 것**
      (오인식 가능성 — 사람의 확인 절차 결합).
- [ ] **대규모/민감 처리 시 DPIA(개인정보 영향평가)** 검토.

> 본 문서는 기술 가이드이며 법률 자문이 아니다. 실제 도입 전 개인정보 담당자/변호사 검토 필수.
