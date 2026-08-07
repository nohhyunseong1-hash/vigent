# `/safety/voice/scene` — session_id 배선 가이드 (2026-08)

`POST /safety/voice/scene`은 **session_id가 필수**다(2026-08, [D-2](나) — 없으면 400).
현재 이 엔드포인트를 호출하는 프론트엔드 코드가 저장소에 없다(전수 검색 0건) — 나중에 실제로
이 API를 연결할 때 아래 절차를 그대로 따를 것.

## 왜 필요한가
이 엔드포인트는 연속 프레임(같은 카메라·같은 세션)을 계속 받는 용도라 서버측 추적(`_track_iou`)의
"잠깐 놓쳐도 이전 박스 유지" 이점을 그대로 살려야 한다 — 그래서 `detect_isolated()`(정지 이미지용,
매 호출 격리)를 쓰지 않는다. 대신 **세션마다** track_key를 분리해야 한다 — 안 그러면 여러 브라우저
탭/세션이 하나의 트랙 풀을 공유해 서로 다른 화면의 박스가 섞인다(2026-08 확정된 track_key 재사용
버그와 같은 유형, 대상만 "정지 이미지"에서 "동시 세션"으로 다를 뿐).

## 배선 절차
1. 페이지 로드 시 **1회만** 세션 ID 생성:
   ```js
   const VOICE_SESSION_ID = crypto.randomUUID();   // 예: "a1b2c3d4-e5f6-4890-..."
   ```
2. 그 페이지가 살아있는 동안(탭을 닫거나 새로고침하기 전까지) `/safety/voice/scene`을 호출할 때마다
   **같은 값을 계속 재사용**:
   ```js
   fetch('/safety/voice/scene', {
     method: 'POST',
     headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({
       image_base64: frameB64,
       session_id: VOICE_SESSION_ID,   // 필수 — 없으면 400
       use_vlm: false,
     })
   });
   ```
3. **새로고침·다른 탭·다른 사용자마다 새 값**을 발급한다(1번으로 돌아가 다시 생성) — 같은 값을
   여러 세션이 공유하면 안 된다.

## 검증
- `session_id` 없이/빈 문자열로/8자 미만으로 호출하면 `400`(`영문·숫자·-·_ 8~128자` 위반 메시지).
- 유효한 값이면 `200` + 평소와 동일한 `liveguide.build_guidance()` 응답.
- 같은 `session_id`로 연속 호출하면 서버 추적이 이전처럼 자연스럽게 이어진다(잠깐 놓쳐도 깜빡임 없음)
  — `agents/guard.py`의 `_track_iou` 동작 자체는 무수정.

## 알아둘 것 (F-2, 별도 처리 예정)
`session_id`는 클라이언트가 주는 값이 그대로 서버 딕셔너리 키(`_tracks_by_key`)가 된다 — 세션이
끝나도(탭을 닫아도) 서버가 자동으로 그 키를 지우지는 않는다(정리 메커니즘은 F-2에서 별도 설계·승인
예정, 아직 미구현). 대량의 세션이 생겼다 사라지는 사용 패턴이면 이 메커니즘이 갖춰지기 전까지는
운영 중 `_tracks_by_key` 크기를 주기적으로 확인할 것.
