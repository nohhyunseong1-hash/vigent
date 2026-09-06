"""routers/cameras.py — 카메라 등록·관리 CRUD + 워커 연동(3.0 Phase 1).

자격증명은 camera_registry 가 secrets 로 분리·마스킹 → 응답엔 마스킹된 source 만 노출.
enable=워커 start(cam_id=track_key 격리), disable=stop. startup 자동복원은 autostart_enabled().
"""
import camera_registry as _reg
from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException, Response
from web_util import is_safety_label as _is_safety

router = APIRouter()


def _worker(cid: str):
    import worker as _w
    return _w.manager._workers.get(cid)


def _guard():
    bundle = STATE.get(DEFAULT_THEME) or _load_theme(DEFAULT_THEME)
    return bundle["agents"].get("Guard")


def _g2_register(cid: str) -> None:
    """go2rtc(localhost:1984)에 카메라 스트림을 동적 등록 — 대시보드 WebRTC 저지연 재생용.
    go2rtc 미실행이면 조용히 무시(스냅샷 폴링으로 폴백 — 규칙6 무중단). 자격증명은 로그에 남기지 않음."""
    try:
        import urllib.parse
        import urllib.request
        src = _reg.source_of(cid)
        if not src:
            return
        url = "http://127.0.0.1:1984/api/streams?" + urllib.parse.urlencode({"name": cid, "src": src})
        urllib.request.urlopen(urllib.request.Request(url, method="PUT"), timeout=3)
    except Exception:  # noqa: BLE001  go2rtc 미실행/실패 — WebRTC 없이 폴백
        pass


def _g2_unregister(cid: str) -> None:
    """go2rtc 스트림 해제(카메라 중지·삭제 시). 미실행이면 무시."""
    try:
        import urllib.parse
        import urllib.request
        url = "http://127.0.0.1:1984/api/streams?" + urllib.parse.urlencode({"src": cid})
        urllib.request.urlopen(urllib.request.Request(url, method="DELETE"), timeout=3)
    except Exception:  # noqa: BLE001
        pass


def _start(cid: str):
    """레지스트리 원본 source 로 워커 시작(자격증명은 워커 내부만, 로그는 마스킹).
    동시에 go2rtc 에도 스트림 등록(있으면 WebRTC, 없으면 스냅샷 폴백)."""
    import worker as _w
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    src = _reg.source_of(cid)
    if not src:
        raise HTTPException(status_code=400, detail="source 미등록")
    res = _w.manager.start(_guard(), _DETECT_LOCK, cid, src,
                           name=c.get("name") or cid, fps=float(c.get("fps", 2.0)),
                           zone=c.get("zone"))
    _g2_register(cid)
    return res


@router.get("/cameras")
def cameras_list():
    """등록 카메라 목록(마스킹) + 워커 라이브 상태 병합."""
    import worker as _w
    st = _w.manager.status().get("cameras", {})
    out = []
    for c in _reg.list_cameras():
        w = st.get(c["id"], {})
        out.append({**c, "online": bool(w.get("running")), "fps_live": w.get("fps"),
                    "reconnects": w.get("reconnects"), "last_frame_secs_ago": w.get("last_frame_secs_ago")})
    return {"cameras": out, "count": len(out)}


@router.post("/cameras")
def cameras_add(payload: dict = Body(...)):
    """등록/수정. payload={id, name?, source(rtsp/파일/웹캠번호), fps?, zone?, enabled?}. source 는 마스킹 저장."""
    cid = str(payload.get("id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="id 필요")
    c = _reg.upsert(cid, name=payload.get("name"), source=payload.get("source"),
                    fps=payload.get("fps"), zone=payload.get("zone"), enabled=payload.get("enabled"))
    worker = _start(cid) if c.get("enabled") else None
    return {"ok": True, "camera": c, "worker": worker}


@router.post("/cameras/{cid}/enable")
def cameras_enable(cid: str):
    if _reg.set_enabled(cid, True) is None:
        raise HTTPException(status_code=404, detail="없는 카메라")
    return {"ok": True, "worker": _start(cid)}


@router.post("/cameras/{cid}/disable")
def cameras_disable(cid: str):
    import worker as _w
    if _reg.set_enabled(cid, False) is None:
        raise HTTPException(status_code=404, detail="없는 카메라")
    _g2_unregister(cid)
    return {"ok": True, "worker": _w.manager.stop(cid)}


@router.delete("/cameras/{cid}")
def cameras_delete(cid: str):
    import worker as _w
    # ★[2026-08-26] **등록부를 가장 먼저 지운다** — 순서가 안전의 핵심이다.
    #   이전 순서(remove → g2_unregister → reg.delete)에는 경합 창이 있었다:
    #   `_g2_unregister` 는 go2rtc 가 안 떠 있으면 **최대 3초를 기다린다**(timeout=3).
    #   그 3초 동안 등록부에는 카메라가 살아 있으므로, 기아 감시(starvation_guard)가
    #   그 틈에 `_start(cid)` 를 부르면 **워커가 되살아난다**. 이후 reg.delete 가 등록부만
    #   지우므로 "등록부에 없는데 돌고 있는 워커"가 남아, 죽은 주소로 15초마다 재접속하며
    #   /health 를 영구 unhealthy 로 만든다(2026-08-26 소크 준비 중 실제 발생).
    #   등록부를 먼저 지우면 그 사이 어떤 경로가 _start 를 불러도 "없는 카메라"로 거부된다.
    ok = _reg.delete(cid)
    _w.manager.remove(cid)
    _g2_unregister(cid)
    # 등록부 삭제와 워커 제거 사이에 되살아났을 수 있다(위 3초 창의 잔여분) — 한 번 더 거둔다.
    _w.manager.remove(cid)
    return {"ok": ok}


@router.get("/cameras/{cid}/detections")
def cameras_detections(cid: str):
    """경량 오버레이용 — 워커 최신 검출(정규화 bbox)·인원·신호. 프론트가 화면크기로 복원."""
    wk = _worker(cid)
    if wk is None:
        return {"online": False, "detections": [], "person_count": 0, "signals": {}, "fired": [], "ts": 0}
    # safety_only(표시 단): 잡동사니(tv·laptop·의자 등) 제거 → 사람·보호구(NO-*)·위험물·차량·화재만.
    #   워커 이벤트/신호는 guard.detect 내부 out 으로 계산되므로 이 필터는 응답·오버레이 표시에만 영향(회귀 0).
    #   ts(3.8): 검출 갱신 시각(ms) — 확대뷰가 새 배치일 때만 BoxTracker.ingest 하도록. id 는 트랙 매칭용.
    # [T-E2E 유령박스] stale(미매칭 코스팅 트랙) 제외 — 표시는 실검출만. 이동 시 옛 위치에
    #   동결 박스가 TTL(1.2s)까지 잔류하던 유령의 서버측 차단(계측 근거: track_debug.jsonl).
    #   신호·판정은 워커 내부 out 기준이라 불변(이 경로는 오버레이 전용).
    dets = [d for d in wk._last_dets if _is_safety(d.get("class")) and not d.get("stale")]
    return {"online": bool(wk.state.get("running")), "detections": dets, "ts": int(wk._last_det_ts * 1000),
            "person_count": wk._last_pc, "signals": wk._last_sig, "fired": wk._last_fired}


@router.post("/cameras/{cid}/focus")
def cameras_focus(cid: str, payload: dict = Body(default={})):
    """확대뷰 포커스 부스트(3.8) — 선택 중 워커 fps 를 focus_fps(tuning hub.focus_fps, 기본5)로 임시 상향,
    해제/탭이탈 시 등록 fps 복원. 확대뷰는 워커 결과 재사용(자체 추론 없음)이라 다중 시청자여도
    워커 1개 → 부하 불변(중복 추론과의 차이). 재시작 없이 루프 간격만 바꿈."""
    import tuning
    import worker as _w
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    on = bool(payload.get("on"))
    base = float(c.get("fps", 2.0))
    # [B안③] payload.fps 로 부스트 값 임시 지정 가능(없으면 tuning 값) — fps 5↔8 A/B 실측용.
    #   dict Body 라 OpenAPI 스키마 불변. 남용 방지로 0.5~15 클램프(set_fps 자체엔 상한 없음).
    focus = float(payload.get("fps") or tuning.val("hub", "focus_fps", 5.0))
    focus = max(0.5, min(15.0, focus))
    return _w.manager.set_fps(cid, focus if on else base)


@router.get("/cameras/{cid}/snapshot")
def cameras_snapshot(cid: str):
    """워커 최신 프레임 JPEG(파일소스 카드/미리보기 — WebRTC 미가용 시 폴링용)."""
    import cv2
    wk = _worker(cid)
    fr = getattr(wk, "_last_frame", None) if wk else None
    if fr is None:
        raise HTTPException(status_code=404, detail="프레임 없음(오프라인/워밍업)")
    # [P1a] 스냅샷은 화면·외부로 나가는 이미지 → 얼굴 비식별화. 워커의 최신 person 박스를 넘겨
    #   머리 영역을 확실히 가린다(원본 _last_frame 은 수정되지 않는다 — 검출 무영향).
    import privacy
    _pb = [d.get("bbox") for d in (getattr(wk, "_last_dets", None) or [])
           if d.get("class") == "person"]
    fr = privacy.anonymize_faces(fr, _pb)
    ok, buf = cv2.imencode(".jpg", cv2.resize(fr, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.post("/cameras/{cid}/test")
def cameras_test(cid: str):
    """연결 테스트 — source 에서 1프레임 잡기 성공 여부(+스냅샷 미리보기). 자격증명은 응답에 노출 안 함."""
    import base64
    import threading

    import cv2
    import worker as _w
    src = _reg.source_of(cid)
    if not src:
        raise HTTPException(status_code=404, detail="source 미등록")
    # [CODE_REVIEW M5-2] 예전엔 요청 스레드가 죽은 주소에 최대 123s(실측) 멈췄다. 워커와 같은 타임아웃 상수로
    #   열기·읽기를 걸고, 그래도 넘기면 응답을 먼저 돌려준다(캡처 스레드는 타임아웃 후 스스로 끝난다).
    box: dict = {}

    def _grab() -> None:
        cap = _w._open_capture(str(src))
        try:
            ok, fr = cap.read()
            box["ok"], box["fr"] = bool(ok), fr
        finally:
            cap.release()
    t = threading.Thread(target=_grab, daemon=True)
    t.start()
    t.join(timeout=_w._RTSP_TIMEOUT_MS / 1000.0 * 2 + 1.0)      # 열기 + 읽기 타임아웃 합 + 여유
    if t.is_alive():
        return {"ok": False, "error": f"연결 시간 초과({_w._RTSP_TIMEOUT_MS}ms) — 주소·네트워크 확인"}
    ok, fr = box.get("ok"), box.get("fr")
    if not ok or fr is None:
        return {"ok": False, "error": "프레임을 못 잡음(연결 실패/경로 오류)"}
    # [P1a] 연결테스트 미리보기도 응답으로 나가는 이미지다(person 박스 없음 → haar 만)
    import privacy
    fr = privacy.anonymize_faces(fr)
    _, buf = cv2.imencode(".jpg", cv2.resize(fr, (480, 270)), [cv2.IMWRITE_JPEG_QUALITY, 65])
    return {"ok": True, "snapshot": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()}


@router.get("/cameras/{cid}/zone")
def cameras_zone_get(cid: str):
    """카메라별 위험구역 폴리곤(정규화 좌표). 비어 있으면 워커는 전역 구역으로 폴백."""
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    pts = c.get("zone") or []
    return {"points": [{"x": float(p[0]), "y": float(p[1])} for p in pts], "count": len(pts)}


@router.post("/cameras/{cid}/zone")
def cameras_zone_set(cid: str, payload: dict = Body(...)):
    """카메라별 위험구역 저장. payload={"points":[{"x":..,"y":..}, ...]}(정규화 0~1).
    비우면 전역 구역 폴백. 실행 중 카메라는 워커를 재시작해 즉시 반영한다."""
    import worker as _w
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    pts = payload.get("points") or []
    zone = [[float(p["x"]), float(p["y"])] for p in pts]
    _reg.upsert(cid, zone=zone)
    restarted = False
    if _worker(cid) is not None and (_reg.get(cid) or {}).get("enabled"):
        _w.manager.stop(cid)
        _start(cid)
        restarted = True
    return {"ok": True, "count": len(zone), "restarted": restarted}


def _lan_ip() -> str:
    """이 머신의 아웃바운드 LAN IP(패킷 전송 없이 소켓 트릭). go2rtc WebRTC 후보용 — 감지 실패 시 127.0.0.1."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


# ── [CODE_REVIEW M5-3, 2026-09-06] go2rtc 수명 관리 ──────────────────────────────────────
#   예전엔 Popen 핸들을 버려 서버 종료 후 go2rtc 가 고아로 남았고(C4 실측 2개), 다음 기동은 포트가 잡혀 있으면
#   옛 프로세스를 그대로 썼다 — 런타임 yaml 은 매 기동 템플릿으로 덮어써도 옛 프로세스는 다시 읽지 않는다.
#   이제 ①우리가 띄운 프로세스는 핸들 + data/go2rtc.pid 로 추적 ②포트 점유자가 우리 PID 파일의 살아 있는
#   프로세스면 종료 후 재기동(yaml 재로드 대신) ③남의 프로세스면 손대지 않고 재사용 + 경고 ④서버 shutdown 에서
#   우리 것만 종료. 테스트: tests/test_go2rtc_lifecycle.py(전부 모킹).
import logging as _logging
from pathlib import Path as _Path

_LOG = _logging.getLogger("vigent.cameras")
_G2_ROOT = _Path(__file__).resolve().parent.parent.parent      # 테스트가 임시 루트로 바꾼다
_G2_PROC = None                                                 # 우리가 띄운 Popen 핸들(이 프로세스 수명)
_G2_LOGF = None                                                 # go2rtc stdout/stderr 파일 핸들(예전엔 열고 닫지 않았다)
_G2_PORT = 1984


def _close_logf() -> None:
    global _G2_LOGF
    try:
        if _G2_LOGF is not None:
            _G2_LOGF.close()
    except Exception:  # noqa: BLE001
        pass
    _G2_LOGF = None


def _g2_pidfile() -> _Path:
    return _G2_ROOT / "data" / "go2rtc.pid"


def _g2_port_busy() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", _G2_PORT), timeout=0.5):
            return True
    except Exception:  # noqa: BLE001
        return False


def _pid_alive(pid: int) -> bool:
    """PID 가 살아 있는 go2rtc 인가. psutil 있으면 이름까지 대조, 없으면 tasklist(Windows)/ps.
    ★os.kill(pid, 0) 은 Windows 에서 TerminateProcess 를 부르므로 절대 쓰지 않는다."""
    try:
        import psutil
        p = psutil.Process(pid)
        return p.is_running() and "go2rtc" in (p.name() or "").lower()
    except Exception:  # noqa: BLE001  psutil 없음/권한 → 보수적으로 False(남의 것으로 간주)
        return False


def _terminate_pid(pid: int) -> bool:
    try:
        import psutil
        p = psutil.Process(pid)
        if "go2rtc" not in (p.name() or "").lower():
            return False
        p.terminate()
        p.wait(timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _read_pidfile() -> int | None:
    try:
        return int(_g2_pidfile().read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001
        return None


def ensure_go2rtc() -> bool:
    """go2rtc(WebRTC 변환기)가 안 떠 있으면 백그라운드로 기동. 바이너리 없으면 조용히 건너뜀(스냅샷 폴백).
    서버 startup 에서 1회 호출 → 카메라 확대뷰 실시간 재생 준비. 실패해도 서버·검출은 무중단.
    GO2RTC_LAN_IP 를 주입 → go2rtc.yaml 이 WebRTC 후보에 실제 UDP 바인딩 주소를 광고(127.0.0.1
    후보만으론 실브라우저 ICE 가 UDP 바인딩 불일치로 실패)."""
    global _G2_PROC, _G2_LOGF
    import os
    if _g2_port_busy():
        old = _read_pidfile()
        if old is not None and _pid_alive(old):
            # 우리가 이전 서버 수명에서 띄운 go2rtc — 런타임 yaml 을 새로 쓰므로 재기동한다(재로드 API 대신)
            _LOG.warning("go2rtc 옛 인스턴스(pid %d) 발견 — 종료 후 재기동(런타임 설정 갱신)", old)
            _terminate_pid(old)
        else:
            _LOG.warning("포트 %d 를 다른 프로세스가 점유 중(우리 PID 파일 없음/불일치) — 손대지 않고 재사용. "
                         "확대뷰 스트림 등록이 옛 설정을 볼 수 있다", _G2_PORT)
            return True
    try:
        import subprocess
        root = _G2_ROOT
        # [S3] Windows 배포는 bin/go2rtc.exe(확장자 필수 — 무확장자 파일은 CreateProcess가 실행
        #   파일로 인식 못 함). 확장자 없는 bin/go2rtc(맥/리눅스)도 계속 지원 — 존재하는 쪽을 쓴다.
        binp = root / "bin" / "go2rtc.exe"
        if not binp.exists():
            binp = root / "bin" / "go2rtc"
        template = root / "config" / "go2rtc.yaml"
        runtime = root / "data" / "go2rtc.runtime.yaml"   # gitignore(data/) — 동적 스트림·비번은 여기에만 기록
        if not binp.exists():
            return False
        try:                                              # 매 기동 템플릿으로 초기화(옛 동적 스트림·비번 잔재 제거)
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:  # noqa: BLE001  런타임 사본 실패 → 템플릿에 비번 기록 방지 위해 go2rtc 미기동(스냅샷 폴백)
            return False
        env = dict(os.environ)
        env.setdefault("RTSP_URL", "")                    # 레거시 tapo 스트림용(없어도 무방)
        env["GO2RTC_LAN_IP"] = _lan_ip()                  # WebRTC 후보에 실제 LAN IP 광고(ICE 성립)
        go2rtc_log = root / "data" / "go2rtc.log"
        # [Z-2] D그룹 회전 — 기동 시점에만 가능(파일이 Popen 수명 동안 열려 있어 세션 중 회전 불가)
        try:
            import tuning
            from retention import rotate_if_large
            rotate_if_large(go2rtc_log, tuning.val("retention", "ops_log_max_mb", 50))
        except Exception:  # noqa: BLE001  회전 실패해도 go2rtc 기동은 막지 않는다
            pass
        _close_logf()
        logf = open(go2rtc_log, "ab")   # noqa: SIM115  Popen 수명 동안 유지(관측성 — WebRTC 진단), stop_go2rtc 가 닫는다
        _G2_LOGF = logf
        proc = subprocess.Popen([str(binp), "-config", str(runtime)], cwd=str(binp.parent),
                                stdout=logf, stderr=logf, env=env)
        _G2_PROC = proc
        try:
            _g2_pidfile().write_text(str(proc.pid), encoding="utf-8")
        except Exception:  # noqa: BLE001  PID 파일 실패해도 핸들은 남는다(이 수명 안에서는 정리 가능)
            pass
        _LOG.info("go2rtc 기동(pid %d)", proc.pid)
        return True
    except Exception:  # noqa: BLE001
        return False


def stop_go2rtc() -> bool:
    """서버 shutdown: **우리가 띄운** go2rtc 만 종료(핸들 → 없으면 PID 파일의 살아 있는 go2rtc). 남의 것은 무시."""
    global _G2_PROC
    done = False
    p = _G2_PROC
    if p is not None:
        try:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=5)
            done = True
        except Exception:  # noqa: BLE001
            pass
        _G2_PROC = None
    else:
        old = _read_pidfile()
        if old is not None and _pid_alive(old):
            done = _terminate_pid(old)
    _close_logf()
    try:
        _g2_pidfile().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    if done:
        _LOG.info("go2rtc 종료(우리가 띄운 인스턴스)")
    return done


def autostart_enabled() -> dict:
    """서버 startup 자동복원 — enabled 카메라 워커 자동 start. 실패해도 서버는 뜬다."""
    res: dict = {}
    for c in _reg.list_cameras():
        if not c.get("enabled"):
            continue
        try:
            _start(c["id"])
            res[c["id"]] = "started"
        except Exception as ex:  # noqa: BLE001
            res[c["id"]] = f"fail: {type(ex).__name__}"
    return res
