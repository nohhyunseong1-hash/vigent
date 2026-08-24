"""privacy.py — [P1a] 저장·전송 이미지의 얼굴 비식별화.

배경(audit/site_readiness_2026-08-16.md 🟠C1): `data_engine.py:12` 에 *"얼굴 비식별화·암호화는
상용 단계 과제"* 라는 주석만 있고 **구현이 없었다**. 근로자 얼굴이 담긴 증거 프레임이 그대로
디스크에 저장되고 알림·클라우드 VLM 으로 나갔다.

★적용 범위(결정된 사항): **저장·전송되는 이미지에만** 적용한다. 실시간 검출 파이프라인이
보는 원본 프레임은 건드리지 않는다 — 비식별화가 검출 정확도에 영향을 주면 안 되기 때문이다.
대상: 증거 JPEG · 스냅샷 · 연결테스트 미리보기 · 클라우드 VLM 전송.

★방식: **모자이크**(픽셀화). 블러는 역합성 복원 공격에 약해서 쓰지 않는다.

★검출 방법(새 의존성 0):
  1) person 박스가 주어지면 **머리 영역(박스 상단부)을 모자이크** — 검출된 사람은 절대 놓치지
     않는다. CCTV 는 측면·후면·고각이 많아 얼굴 검출기가 자주 실패하는데, 개인정보 보호에서
     '놓침'은 곧 실패이므로 보수적으로 넓게 가린다.
  2) 추가로 **YuNet**(cv2.FaceDetectorYN, 모델 227KB)으로 얼굴을 찾아 덮는다 —
     person 박스 밖 인물이나 박스가 없는 경로(연결테스트·클라우드 VLM) 대비.
  ※ 처음엔 OpenCV 번들 haarcascade 를 쓰려 했으나 **OpenCV 5.0 에서 cv2.CascadeClassifier 가
     제거**돼 동작 불가였다(실측 AttributeError). YuNet 이 대체이자 개선이다(측면 얼굴도 잡음).
"""
from __future__ import annotations

import threading
import threading as _threading
import time as _time
from typing import Any

import tuning

_cascade: Any = None
_cascade_tried = False
_lock = threading.Lock()


def enabled() -> bool:
    return bool(tuning.val("privacy", "face_anonymize", True))


def _blocks() -> int:
    """모자이크 격자 수(작을수록 강하게 뭉갠다)."""
    return max(2, int(tuning.val("privacy", "mosaic_blocks", 8)))


def _head_ratio() -> float:
    """person 박스에서 머리로 간주해 가릴 상단 비율."""
    return float(tuning.val("privacy", "head_ratio", 0.30))


def _get_cascade() -> Any:
    """YuNet 얼굴 검출기(cv2.FaceDetectorYN). 모델 파일이 없으면 None.

    ★haarcascade 를 쓰려 했으나 **OpenCV 5.0 에서 cv2.CascadeClassifier 가 제거**돼
    (AttributeError 실측) 이 환경에서는 동작 자체가 불가능했다. YuNet 은 OpenCV 5 에 API 가
    내장돼 있고 모델이 227KB 로 작으며 측면 얼굴도 잡는다 — haar 보다 낫다.
    모델은 weights/face_detection_yunet.onnx(fetch_weights 로 조달, 선택 항목).
    """
    global _cascade, _cascade_tried
    with _lock:
        if _cascade_tried:
            return _cascade
        _cascade_tried = True
        try:
            from pathlib import Path

            import cv2
            p = Path(__file__).resolve().parent / "weights" / "face_detection_yunet.onnx"
            if p.exists() and hasattr(cv2, "FaceDetectorYN"):
                _cascade = cv2.FaceDetectorYN.create(
                    str(p), "", (320, 320),
                    float(tuning.val("privacy", "face_conf", 0.6)), 0.3, 5000)
        except Exception:  # noqa: BLE001  얼굴검출기 없어도 person 박스 경로는 동작한다
            _cascade = None
        return _cascade


def _mosaic_region(img: Any, x1: int, y1: int, x2: int, y2: int) -> None:
    """지정 사각형을 제자리에서 모자이크(픽셀화)."""
    import cv2
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    roi = img[y1:y2, x1:x2]
    n = _blocks()
    small = cv2.resize(roi, (max(1, (x2 - x1) // n), max(1, (y2 - y1) // n)),
                       interpolation=cv2.INTER_LINEAR)
    img[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


def anonymize_faces(frame: Any, person_boxes: list | None = None) -> Any:
    """저장·전송용 프레임의 얼굴을 가린 **사본**을 돌려준다(원본 불변).

    person_boxes: 정규화 [x1,y1,x2,y2] 목록(있으면 머리 영역을 확실히 가린다).
                  None 이면 haarcascade 만으로 처리한다(놓칠 수 있음 — 위 주석 참고).
    """
    if frame is None or not enabled():
        return frame
    _begin_call()                   # [D4-②] 지난 호출의 실패 표시를 내린다(다음 건 오염 방지)
    try:
        out = frame.copy()          # ★원본은 절대 수정하지 않는다(검출 파이프라인 보호)
        h, w = out.shape[:2]
        covered = 0

        for b in (person_boxes or []):
            try:
                x1, y1, x2, y2 = (float(v) for v in list(b)[:4])
            except Exception:  # noqa: BLE001
                continue
            if max(x1, y1, x2, y2) <= 1.5:      # 정규화 좌표 → 픽셀
                x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
            bw, bh = x2 - x1, y2 - y1
            if bw <= 0 or bh <= 0:
                continue
            # 머리: 박스 상단 head_ratio, 가로는 중앙 80%(어깨 제외)
            hx1 = x1 + bw * 0.10
            hx2 = x2 - bw * 0.10
            _mosaic_region(out, int(hx1), int(y1), int(hx2), int(y1 + bh * _head_ratio()))
            covered += 1

        # ★[P1a-fix, 2026-08-21] YuNet 은 **공유 싱글톤**이라 setInputSize→detect 사이에
        #   다른 스레드가 끼어들면 내부 버퍼 크기가 어긋나 예외가 난다(OpenCV 5 dnn:
        #   "buf.shape() == m.shape()"). 워커(1920×1080)와 스냅샷(640×360)이 동시에 부르는
        #   실서비스에서 **분당 145~160건** 발생했고(로그 4,054건), 그때마다 아래 except 로
        #   빠져 **원본이 저장·전송**됐다. 락 없는 재현 실측 실패율 24%(80회 중 19회).
        #   → 크기 설정과 추론을 한 임계구역으로 묶는다.
        det = _get_cascade()
        if det is not None:
            try:
                with _lock:
                    det.setInputSize((w, h))
                    ok, faces = det.detect(out)
            except Exception:  # noqa: BLE001
                # ★얼굴검출기 실패가 **머리 모자이크까지 버리게 하면 안 된다**(이전 동작의 결함).
                #   person 박스 기반 모자이크는 이미 out 에 적용돼 있으므로 그대로 살린다.
                faces = None
                try:
                    import vlog
                    vlog.get("vigent.privacy").warning(
                        "YuNet 얼굴검출 실패 — person 박스 모자이크는 유지된 채 저장된다")
                except Exception:  # noqa: BLE001
                    pass
            for f in (faces if faces is not None else []):
                fx, fy, fw, fh = (int(v) for v in f[:4])
                m = int(fw * 0.20)      # 여유를 둬 경계 픽셀이 남지 않게
                _mosaic_region(out, fx - m, fy - m, fx + fw + m, fy + fh + m)
                covered += 1
        return out
    except Exception:  # noqa: BLE001  비식별화 실패가 저장 자체를 막으면 안 된다
        # ★[D4, 2026-08-24] 결정: **현행(원본 저장) 유지**. 증거를 버리면 사고를 증명할 수 없다.
        #   단 세 가지를 조건으로 단다 — ①실패가 잦으면 통보 ②기록에 표시 ③법무 검토 대상.
        #   ★단, 실패하면 원본이 나가므로 로그로 반드시 드러낸다.
        _note_failure()
        try:
            import vlog
            vlog.get("vigent.privacy").exception("얼굴 비식별화 실패 — 원본이 저장·전송된다")
        except Exception:  # noqa: BLE001
            pass
        return frame


# ─────────────────────────────────────────────────────────────────────────────
# [D4, 2026-08-24] 모자이크 실패 감시 — "원본이 나갔다"를 조용히 넘기지 않는다.
#   결정: 실패해도 저장은 계속한다(증거 보전 우선). 대신 ①잦으면 통보 ②기록에 표시
#   ③법무 검토 대상 꼬리표. 과거 YuNet 락 누락 때 **분당 145~160건** 실패한 전례가 있다.
_fail_lock = _threading.Lock()
_fail_times: list[float] = []          # 최근 실패 시각(초) — 1분 창
_fail_total = 0
_last_alert_at = 0.0
# ★②용 플래그는 **스레드 로컬**이다. anonymize_faces 는 워커와 스냅샷 경로가 **동시에**
#   부른다(그 동시성이 바로 YuNet 락 사고의 원인이었다). 전역 플래그로 두면 스냅샷의
#   실패가 워커의 이벤트에 붙어 **엉뚱한 건이 '원본 저장'으로 표시**된다 — 선별 삭제가
#   틀린 파일을 지우게 되므로 개인정보 관점에서 더 나쁘다.
_tls = _threading.local()


def _fail_threshold() -> int:
    """분당 몇 건부터 통보할 것인가(기본 5 — 사용자 결정)."""
    return int(tuning.val("privacy", "fail_alert_per_min", 5))


def _note_failure() -> None:
    """실패 1건 기록. 1분 내 임계를 넘으면 **통보 채널로 경보**한다(가산식 — 실패해도 저장은 계속)."""
    global _fail_total, _last_alert_at
    now = _time.time()
    _tls.failed = True                 # 이 스레드의 이번 호출이 실패했다
    with _fail_lock:
        _fail_total += 1
        _fail_times.append(now)
        while _fail_times and now - _fail_times[0] > 60.0:
            _fail_times.pop(0)
        recent = len(_fail_times)
        thr = _fail_threshold()
        # 통보 자체가 폭주하지 않게 10분에 1회로 제한한다.
        if recent >= thr and now - _last_alert_at >= 600.0:
            _last_alert_at = now
            fire = True
        else:
            fire = False
    if not fire:
        return
    try:   # ★통보 실패가 검출·저장을 막으면 안 된다 — 전부 삼킨다.
        import alert_notify
        alert_notify.submit(
            cam="privacy", rule="privacy_anonymize_failed", level="high",
            message=(f"[개인정보] 얼굴 모자이크가 1분간 {recent}건 실패했다 — "
                     f"그 사이 **원본 이미지가 저장·전송**됐다. 즉시 확인 필요."),
            meta={"recent_per_min": recent, "total": _fail_total, "threshold": thr})
    except Exception:  # noqa: BLE001
        pass


def _begin_call() -> None:
    """호출 시작 시 플래그를 내린다 — 지난 호출의 실패가 다음 건에 딸려가지 않게."""
    _tls.failed = False


def took_failure() -> bool:
    """직전 호출이 실패했는지 확인하고 **플래그를 소비**한다(호출부가 이벤트 기록에 남긴다).

    ★스레드 로컬이라 다른 스레드(스냅샷 등)의 실패가 섞이지 않는다.
    """
    v = bool(getattr(_tls, "failed", False))
    _tls.failed = False
    return v


def failure_status() -> dict[str, Any]:
    """/health 노출 — 원본이 나간 적이 있는지 밖에서 보이게."""
    now = _time.time()
    with _fail_lock:
        recent = sum(1 for x in _fail_times if now - x <= 60.0)
        return {"anonymize_failures_total": _fail_total,
                "anonymize_failures_per_min": recent,
                "alert_threshold_per_min": _fail_threshold(),
                # ③ 법무 검토 대상 꼬리표 — 실패가 있었다면 원본이 저장된 기록이 남아 있다.
                "legal_review_required": _fail_total > 0,
                "legal_review_note": ("모자이크 실패 시 원본이 저장된다(설계 결정 D4). "
                                      "실패 이벤트는 기록의 privacy_failed=true 로 선별할 수 있다.")
                if _fail_total > 0 else ""}


def status() -> dict[str, Any]:
    """/health 노출용."""
    return {
        "face_anonymize": enabled(),
        "method": "mosaic",
        "detector": "person_box_head + yunet" if _get_cascade() is not None
                    else "person_box_head(얼굴검출기 모델 없음 — 사람 박스 밖 얼굴은 미처리)",
        "mosaic_blocks": _blocks(),
    }


# ── [P1c] 저장 암호화 검사 ────────────────────────────────────────────────────
#   결정된 사항: 앱 레벨 파일 암호화(Fernet 등)를 새로 만들지 않는다. 저장 폴더를 Windows
#   BitLocker 또는 EFS 로 보호하는 것을 기본으로 하고, 앱은 **암호화돼 있는지 검사해
#   /health 에 노출**만 한다(파일럿 이후 앱 레벨 암호화 재검토).
#   ※ 이 함수는 사실만 보고한다 — 법적 충분성 판단은 하지 않는다(사람이 검토).

_storage_cache: dict[str, Any] = {}
_storage_ts = 0.0


def _protected_dirs() -> list[Any]:
    """개인영상정보가 저장되는 폴더 목록(암호화 검사 대상)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "data"
    return [root / n for n in ("evidence", "recognition", "audit", "tbm", "risk_assessments")]


def _efs_encrypted(path: Any) -> bool | None:
    """`cipher /c` 로 EFS 암호화 여부 판정. True/False/None(판정불가).

    관리자 권한 없이 동작한다(BitLocker 조회와 달리). 출력의 파일별 접두 'E'=암호화,
    'U'=미암호화를 센다.
    """
    import subprocess
    try:
        out = subprocess.run(["cipher", "/c", str(path)], capture_output=True,
                             timeout=20, text=True, errors="replace")
    except Exception:  # noqa: BLE001
        return None
    txt = (out.stdout or "") + (out.stderr or "")
    if not txt.strip():
        return None
    if "will not be encrypted" in txt:
        return False
    if "will be encrypted" in txt:
        return True
    marks = [ln.strip()[:1] for ln in txt.splitlines()
             if ln.strip()[:1] in ("E", "U") and len(ln.strip()) > 2]
    if not marks:
        return None
    return all(m == "E" for m in marks)


def _bitlocker_status(drive: str) -> str:
    """볼륨 BitLocker 상태. 관리자 권한이 없으면 'unknown'(액세스 거부)."""
    import subprocess
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-BitLockerVolume -MountPoint '{drive}').ProtectionStatus"],
            capture_output=True, timeout=25, text=True, errors="replace")
        s = (r.stdout or "").strip()
        if s in ("On", "1"):
            return "on"
        if s in ("Off", "0"):
            return "off"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def storage_status(force: bool = False) -> dict[str, Any]:
    """저장 폴더 암호화 검사 결과(기동 시 1회 + TTL 캐시).

    storage_encrypted: true(전부 보호) | false(하나라도 미보호) | unknown(판정 불가)
    """
    global _storage_cache, _storage_ts
    import time as _t
    with _lock:
        if not force and _storage_cache and (_t.time() - _storage_ts) < 3600:
            return _storage_cache

    dirs = [d for d in _protected_dirs() if d.exists()]
    per: dict[str, Any] = {}
    for d in dirs:
        per[d.name] = _efs_encrypted(d)
    _all = _protected_dirs()
    drive = str(_all[0].drive or "") if _all else ""
    bl = _bitlocker_status(drive) if drive else "unknown"

    if bl == "on":
        overall: Any = True
    elif per and all(v is True for v in per.values()):
        overall = True
    elif per and any(v is False for v in per.values()) and bl == "off":
        overall = False
    elif per and any(v is False for v in per.values()):
        overall = False        # EFS 미적용이 확인됐고 BitLocker 는 미확인 → 보호 미확인으로 본다
    else:
        overall = "unknown"

    res = {
        "storage_encrypted": overall,
        "bitlocker": bl,             # on|off|unknown(관리자 권한 필요)
        "efs_by_dir": per,           # 폴더별 True/False/None
        "checked_dirs": [str(d) for d in dirs],
        "note": ("BitLocker 조회는 관리자 권한이 필요하다. 미적용 시 조치는 "
                 "deploy/SITE_CHECKLIST.md N-2 참고."),
    }
    with _lock:
        _storage_cache = res
        _storage_ts = _t.time()
    return res
