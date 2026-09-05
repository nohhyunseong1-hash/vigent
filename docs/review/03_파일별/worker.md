# worker.py (1,258줄) — 판정 루프·생명주기

**책임 한 줄**: 카메라당 스레드로 캡처→검출→규칙→통보를 돌리고, 그 스레드들을 관리한다.

**진입점·호출 관계**
- 구조 3층: `_StreamCapture`(:520 start/:606 stop) → `Worker`(:669 start/:1061 _loop/:846 _process_frame/:699 stop) → `WorkerManager`(:1190 start/:1201 stop/:1233 stop_all).
- 판정: `_process_frame` :846(152줄) → `guard.detect` :888/:894 → `_derive` :194(104줄) → `alert_notify.submit` :984.
- 부속: 포즈 스레드 `_pose_loop` :815 · 얼굴 비식별 `_frame_to_dataurl` :152 · 감시는 starvation_guard(외부).

**★불변 조건**
1. 카메라 1대 = 캡처 스레드 1 + 판정 스레드 1(+포즈). **stop 후 남는 스레드 0.**
2. `_derive` 는 순수 함수에 가깝다(디바운서 주입 제외) — 전역을 만지면 안 된다.
3. 원본 frame 은 수정되지 않는다(:156 주석 — privacy 는 사본).
4. 유령 워커 없음 — Manager dict 에서 지워지면 스레드도 끝나 있어야(✔병력 있음).

**의심하며 볼 지점**
| 위치 | 질문 |
|---|---|
| :846 `_process_frame` 152줄 | `:pf`(고속 person) 프레임과 풀세트 프레임의 **상태 격리**(track_key 접미사) — 섞이면 트랙 오염 |
| :1061 `_loop` 105줄 | 재연결 백오프 · STOP 조건 · 예외 시 루프 생존 — **루프 안 광역 except 가 몇 개인가**(01_현황 §7 대조) |
| :984 | `n = alert_notify.submit(...)` — 반환 n 을 쓰는가, 무시하는가(계열 D) |
| :251-256 `_vigent_seen` | 디바운서 객체에 **동적 속성 부착** — 타입 밖 상태. 리셋 경로가 있는가(계열 E) |
| :1201/:1233 stop | join 하는가 — alert_queue 병(✔)과 같은 패턴인지 |
| :152 `_frame_to_dataurl` | 실패 플래그(:163-168) — **다중 카메라에서 전역 플래그 경합**(06 §2 privacy 항목과 동일 의심) |

**알려진 함정**
- `dets.jsonl` 은 **추적 이후·임계 통과분만** — `_pre_track` 은 기록 안 됨.
- `main` import 시 startup 배선으로 스레드가 뜬다(테스트 간섭 병력).
- `ppe_missing` 의 subject 는 `""`(카메라 단위) — 사람 단위 아님.
