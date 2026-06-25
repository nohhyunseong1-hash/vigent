# 다중 인증(MFA) 모듈 설계 — `mfa.py`

산업 현장(먼지·마스크·보안경)에서 **얼굴 단독 인식은 불안정**하다. 이 모듈은 여러 인증
요소를 **정책**으로 결합하고, 얼굴이 약해지면 **자동으로 다른 요소를 추가 요구(step-up)** 한다.

## 인증 요소(factor)
| 요소 | 유형 | 구현 | 비고 |
|---|---|---|---|
| `face` | 무엇인가(생체) | `recognizer` 재사용 | 마스크/가림 → **판정불가**(거부 아님 → step-up 유도) |
| `card` | 무엇을 가짐 | 사번/RFID/QR → 사람 매핑(`CardStore`) | 하드웨어 불가지(리더가 card_id만 주면 됨) |
| `pin` | 무엇을 앎 | 사람별 PIN(`PinStore`) | **솔트+PBKDF2 해시 저장, 평문 저장 안 함** |
| `iris` | 무엇인가(생체) | 스텁 | NIR 홍채 하드웨어 연결 시 활성(쌍둥이·노화 강함) |

## 정책(보안 등급/구역별)
정책 = "통과 가능한 요소 조합들". 하나라도 모두 충족하면 통과.

| 정책 | 조합 | 의도 |
|---|---|---|
| `basic` 보통구역 | `[face]` 또는 `[card+pin]` | 저위험. 얼굴 단독 허용 |
| `dusty` 고분진구역 | `[card+face]` 또는 `[card+pin]` | **얼굴 단독 불가**(마스크 위험). 2요소. 얼굴 약하면 PIN 대체 |
| `high` 고보안구역 | `[card+face+pin]` | 3요소 전부 |

새 구역은 `Policy(name, combos)` 한 줄로 추가(코드 수정 없음).

## 결정 규칙 (보안 핵심)
1. **기본 거부(fail-safe)**: 어떤 조합도 못 채우면 `DENY`.
2. **신원 일치**: 얼굴=A, 카드=B면 → **충돌 `DENY`**.
3. **step-up**: 일부만 통과하면 부족한 요소를 알려 `STEP_UP`(추가 인증 요구).
4. **신원 확정 필수**: 식별 요소(카드/얼굴) 없이 조합만 차도 `DENY`.
5. **감사추적**: 모든 판정(`mfa_decide`)·등록을 `privacy.audit` 로 기록.

## 핵심 흐름 — 먼지 현장
```
작업자 접근(마스크·고글 착용)
 → face: 판정불가(가림)         ← 얼굴 단독으로 틀린 사람 통과시키지 않음
 → 정책(dusty): card+face 불가 → card+pin 필요
 → STEP_UP: "PIN 입력하세요"
 → card(사번) + pin 일치 & 신원 동일 → GRANT
```
즉 **체크포인트(깨끗한 입구)에서는 얼굴, 가림이 심하면 카드+PIN으로 자동 대체** → 오인식 없이 무중단 출입.

## 사용 예
```python
from vigentFacialRecognition.mfa import Authenticator
auth = Authenticator(policy="dusty")
d = auth.authenticate(face_frames=frames, card_id="EMP-1024", pin="8273")
if d.granted:
    open_gate(d.subject_id)
elif d.decision == "STEP_UP":
    prompt(d.needed)          # 예: ['pin']
else:
    deny(d.reasons)           # 사람 확인/우회 경로
```

## VIGENT 원칙 준수
- **advisory 경계**: 출입 판정 보조이며, 최종 책임·우회(수동 개방) 경로를 둔다.
- **페일세이프**: 불확실하면 통과가 아니라 **추가 인증/거부**.
- **개인정보**: 얼굴은 옵트인(기존 규칙), PIN 해시 저장, 카드/PIN 파일 권한 0600, 전 판정 감사.
- **모델/하드웨어 불가지**: 카드 리더·홍채기는 `card_id`/스텁 인터페이스로 교체만.

## 홍채(iris) 요소 — 활성화 완료 (`iris.py`)
쌍둥이·노화·마스크에 강한 최고 정밀 생체. **NIR 하드웨어 플러그형**으로 설계해, 장비가
꽂히면 코드 수정 없이 동작한다.

- **프로바이더 추상화** `IrisProvider`: NIR 카메라+코드추출 SDK 자리.
  - `NullIrisProvider`(기본): 미연결 → 홍채요소 '판정불가'.
  - `SimIrisProvider`: 파이프라인(등록·매칭·정책) 검증용 시뮬레이터. **실제 인식 아님**.
  - 실장비: 이 인터페이스만 구현해 `set_provider()` 로 주입.
- **매칭**: Daugman 방식 — 홍채코드(비트)+마스크 → **정규화 해밍거리** < `IRIS_HAMMING_THRESHOLD`(0.32) 이면 동일인. 가림 비트는 마스크 교집합으로 제외.
- **정책**: `vault`(최고보안) = `[iris+card]` 또는 `[iris+pin]`. iris 도 식별요소라 신원일치·step-up 그대로 적용.
- **법적**: 홍채는 민감 생체정보 → **별도 옵트인** `VIGENT_IRIS_ENABLED=1`(얼굴과 독립),
  템플릿 암호화 저장(`privacy.encrypt_bytes`), 파일 0600, 등록·판정 감사.
- 환경변수: `VIGENT_IRIS_PROVIDER = null(기본) | sim`, `VIGENT_IRIS_HD`(임계값).

```python
from vigentFacialRecognition.mfa import Authenticator
auth = Authenticator(policy="vault")
d = auth.authenticate(iris={"seed": eye_capture}, card_id="EMP-1024")
```

### NIR 홍채 하드웨어 요건(실장비 도입 시)
- 근적외선(700~900nm) 조명 + NIR 카메라, 근접(10~30cm) 협조 촬영.
- 갈색·짙은 홍채도 NIR에서 무늬 선명(가시광 웹캠은 부적합).
- 라이브니스(인쇄/콘택트렌즈 위조 방지) 권장.

## 다음 단계(선택)
- 카드 리더(RFID/QR)·키패드 실연동, 게이트 릴레이 신호(§8 경계: 보조 신호만)
- 웹 데모(카드=QR/입력, PIN=키패드, 얼굴=웹캠)로 step-up 흐름 시연
- NIR 홍채 실장비 `IrisProvider` 구현·연결(현재는 Null/Sim 프로바이더)
