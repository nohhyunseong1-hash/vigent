"""app.py — 통합 데모 서버 (얼굴인식 · 동요지표 · 모션확대 하나로)

세 데모를 각각 띄우지 않고 하나의 서버(포트 8010) + 탭 페이지로 합친다.
기존 라우터/엔진을 그대로 재사용한다(중복 로직 없음).

  /                → 탭 허브(hub.html)
  /demo/facial     → 얼굴 인식 데모(index.html)      + /facial/*  (api.router)
  /demo/wellbeing  → 동요/피로 지표 데모             + /wellbeing/*
  /demo/evm        → 모션 확대(EVM) 데모             + /evm/*

실행:
    cd ~/Desktop/VIGENT
    python -m vigentFacialRecognition.app
  → http://127.0.0.1:8010 자동 오픈.

⚠ 데모 편의로 얼굴인식 옵트인을 강제 ON(운영 금지). README 법적 체크리스트 참조.
"""
from __future__ import annotations

import socket
import webbrowser
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, Response

from . import config
from . import iris as iris_mod
from .agitation import AgitationMonitor
from .api import router as facial_router
from .evm import MotionMagnifier
from .liveness import LivenessSession
from .loto_serial import LotoController
from .mfa import Authenticator, CardStore, DEFAULT_POLICIES, FaceFactor, PinStore
from .smartloto import LotoStation

config.ENABLED = True                 # 데모 한정(운영 금지 — demo_server 와 동일 주석)
config.IRIS_ENABLED = True            # 데모 한정: 홍채 시뮬레이터 사용
iris_mod.set_provider(iris_mod.SimIrisProvider())


def _decode(data: bytes):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return img

HERE = Path(__file__).resolve().parent
DEMO = HERE / "demo"

app = FastAPI(title="VIGENT Vision Demos")
app.include_router(facial_router)     # /facial/*

monitor = AgitationMonitor()          # 동요/피로(1인 세션)
mag = MotionMagnifier()               # 모션 확대(1인 세션)


# ── 페이지 ────────────────────────────────────────────────────
@app.get("/")
def hub():
    return FileResponse(DEMO / "hub.html")


@app.get("/demo/facial")
def page_facial():
    return FileResponse(DEMO / "index.html")


@app.get("/demo/wellbeing")
def page_wellbeing():
    return FileResponse(DEMO / "wellbeing.html")


@app.get("/demo/evm")
def page_evm():
    return FileResponse(DEMO / "evm.html")


@app.get("/demo/mfa")
def page_mfa():
    return FileResponse(DEMO / "mfa.html")


@app.get("/demo/loto")
def page_loto():
    return FileResponse(DEMO / "loto.html")


# ── Smart LOTO (실물 서보 연동) ──────────────────────────────
loto_controller = LotoController()                 # 포트 자동탐지(없으면 시뮬)
loto_station = LotoStation("PRESS-01", loto_controller)


async def _resolve_worker(person_id, name, image, live):
    """얼굴 이미지가 오면 인증해 신원 확정, 없으면 입력 person_id 사용."""
    if image is not None and live:
        r = FaceFactor().check([_decode(await image.read())])
        if r.ok:
            return r.subject_id, (name or r.subject_id), None
        return None, None, r.reason
    if person_id:
        return person_id, (name or person_id), None
    return None, None, "신원 없음(얼굴 인증 또는 person_id 필요)"


@app.get("/loto/status")
def loto_status():
    return loto_station.snapshot()


@app.post("/loto/apply")
async def loto_apply(person_id: str = Form(None), name: str = Form(""),
                     image: UploadFile = File(None), live: bool = Form(True)):
    pid, nm, err = await _resolve_worker(person_id, name, image, live)
    if err:
        return {"ok": False, "error": err}
    try:
        return {"ok": True, **loto_station.apply_lock(pid, nm)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/loto/remove")
async def loto_remove(person_id: str = Form(None), image: UploadFile = File(None),
                      live: bool = Form(True), supervisor: bool = Form(False)):
    pid, _, err = await _resolve_worker(person_id, "", image, live)
    if err:
        return {"ok": False, "error": err}
    try:
        return {"ok": True, **loto_station.remove_lock(pid, by=pid, supervisor=supervisor)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/loto/arm")
async def loto_arm(action: str = Form("TOGGLE"), person_id: str = Form(None),
                   name: str = Form(""), image: UploadFile = File(None),
                   live: bool = Form(True)):
    """얼굴 인증된 작업자만 무장. 무장 후 10초 내 물리 버튼을 누르면 서보 작동."""
    pid, nm, err = await _resolve_worker(person_id, name, image, live)
    if err:
        return {"ok": False, "error": err, "armed": False}
    loto_controller.arm(action)
    return {"ok": True, "armed": True, "by": pid, "action": action,
            "hint": "10초 내에 기계의 물리 버튼을 누르세요"}


@app.post("/loto/energize")
def loto_energize(by: str = Form("operator")):
    try:
        return {"ok": True, **loto_station.energize(by=by)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/loto/shutdown")
def loto_shutdown(by: str = Form("operator")):
    return {"ok": True, **loto_station.shutdown(by=by)}


# ── 다중 인증(MFA) 엔드포인트 ────────────────────────────────
@app.get("/mfa/policies")
def mfa_policies():
    return {"policies": [{"key": k, "name": p.name, "combos": p.combos,
                          "desc": p.description} for k, p in DEFAULT_POLICIES.items()]}


@app.post("/mfa/register")
async def mfa_register(person_id: str = Form(...), name: str = Form(""),
                       card_id: str = Form(None), pin: str = Form(None),
                       iris_seed: str = Form(None),
                       images: list[UploadFile] = File(None)):
    out = {"person_id": person_id}
    if images:
        from .enrollment import get_store
        from .privacy import Consent
        imgs = [_decode(await f.read()) for f in images]
        imgs = [i for i in imgs if i is not None]
        if imgs:
            try:
                p = get_store().add_person(person_id, name or person_id, imgs,
                                           Consent(purpose="MFA 데모", consented_by="demo"))
                out["face"] = p.n_embeddings
            except Exception as e:
                out["face_error"] = str(e)
    if card_id:
        CardStore().register(card_id, person_id); out["card"] = card_id
    if pin:
        PinStore().set_pin(person_id, pin); out["pin"] = True
    if iris_seed:
        try:
            iris_mod.IrisRecognizer().enroll(person_id, {"seed": iris_seed})
            out["iris"] = True
        except Exception as e:
            out["iris_error"] = str(e)
    return {"ok": True, **out}


live_session = LivenessSession()


@app.post("/liveness/start")
def liveness_start(require_pulse: bool = Form(False)):
    live_session.require_pulse = require_pulse
    live_session.reset()
    return {"ok": True, "instruction": live_session.instruction,
            "require_pulse": require_pulse}


@app.post("/liveness/frame")
async def liveness_frame(image: UploadFile = File(...), ts: float = Form(None)):
    img = _decode(await image.read())
    if img is None:
        return {"face": False, "error": "decode"}
    return live_session.update(img, ts or 0.0)


@app.post("/mfa/authenticate")
async def mfa_authenticate(policy: str = Form("dusty"), card_id: str = Form(None),
                           pin: str = Form(None), iris_seed: str = Form(None),
                           image: UploadFile = File(None), live: bool = Form(True)):
    frames = None
    if image is not None and live:        # 라이브니스 미통과면 얼굴 신뢰 안 함(사진 차단)
        img = _decode(await image.read())
        frames = [img] if img is not None else None
    iris = {"seed": iris_seed} if iris_seed else None
    auth = Authenticator(policy=policy if policy in DEFAULT_POLICIES else "dusty")
    d = auth.authenticate(face_frames=frames, card_id=card_id or None,
                          pin=pin or None, iris=iris)
    return {"decision": d.decision, "subject": d.subject_id, "policy": d.policy,
            "satisfied": d.satisfied, "needed": d.needed, "reasons": d.reasons,
            "factors": d.factors}


# ── 동요/피로 엔드포인트 ──────────────────────────────────────
@app.post("/wellbeing/frame")
async def wb_frame(image: UploadFile = File(...), ts: float = Form(None)):
    import cv2
    img = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"face": False, "error": "decode"}
    return monitor.update(img, ts)


@app.post("/wellbeing/reset")
def wb_reset():
    monitor.reset()
    return {"ok": True}


# ── 모션 확대 엔드포인트 ──────────────────────────────────────
@app.post("/evm/frame")
async def evm_frame(image: UploadFile = File(...), ts: float = Form(None),
                    alpha: float = Form(None)):
    import cv2
    if alpha is not None:
        mag.alpha = float(alpha)
    img = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return Response(status_code=400)
    out = mag.process(img, ts)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"X-FPS": str(mag.fps)})


@app.post("/evm/reset")
def evm_reset():
    mag.reset()
    return {"ok": True}


def _free_port(host: str, start: int = 8090, tries: int = 40) -> int:
    """start 부터 빈 포트를 찾는다(8010 코어 서버 등과 충돌 회피)."""
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, p))
                return p
            except OSError:
                continue
    return start


def main() -> None:
    if not config.model_files_present():
        print("모델이 없습니다. 먼저: python -m vigentFacialRecognition.download_models")
        return
    host = "127.0.0.1"
    port = _free_port(host)                 # 빈 포트 자동 선택(8010 코어와 충돌 방지)
    url = f"http://{host}:{port}"
    print(f"\n  VIGENT 통합 비전 데모 → {url}")
    print("  탭: 얼굴인식 · 동요지표 · 모션확대  (데모 모드)")
    print("  ※ 브라우저가 안 열리면 위 주소를 직접 입력하세요.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
