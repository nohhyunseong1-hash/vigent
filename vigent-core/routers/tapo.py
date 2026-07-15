"""routers/tapo.py — Tapo 카메라 go2rtc 중계(WebRTC/WS) 라우트 (P1-7 분할).

go2rtc(localhost:1984)를 같은 출처로 프록시해 CORS 회피. main·app_state 의존 없음(자립).
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from fastapi.responses import PlainTextResponse

router = APIRouter()


@router.get("/tapo/video-rtc.js")
def tapo_videortc_js():
    """go2rtc 의 video-rtc.js(ES모듈)를 VIGENT 서버가 대신 받아 같은 출처로 제공."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:1984/video-rtc.js", timeout=5) as r:
            return Response(r.read(), media_type="application/javascript")
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"go2rtc 미실행: {ex}")


@router.websocket("/tapo/ws")
async def tapo_ws(ws: WebSocket):
    """브라우저 ↔ go2rtc WebSocket(/api/ws?src=tapo) 양방향 중계(같은 출처)."""
    await ws.accept()
    import websockets
    try:
        async with websockets.connect("ws://localhost:1984/api/ws?src=tapo") as up:
            async def c2u():
                while True:
                    data = await ws.receive()
                    if data.get("type") == "websocket.disconnect":
                        break
                    if data.get("text") is not None:
                        await up.send(data["text"])
                    elif data.get("bytes") is not None:
                        await up.send(data["bytes"])

            async def u2c():
                async for msg in up:
                    if isinstance(msg, (bytes, bytearray)):
                        await ws.send_bytes(msg)
                    else:
                        await ws.send_text(msg)

            await asyncio.gather(c2u(), u2c())
    except Exception:  # noqa: BLE001  연결 종료/실패 시 조용히 닫음
        pass


# ── go2rtc WebRTC 신호 중계(같은 출처로 만들어 CORS 회피) ──
@router.post("/tapo/webrtc")
async def tapo_webrtc(request: Request):
    """브라우저 ↔ go2rtc WebRTC 핸드셰이크(SDP)를 VIGENT 서버가 중계.
    영상(미디어)은 WebRTC로 직접 흐르고, 여기선 SDP 신호만 전달 → CORS 문제 없음."""
    import urllib.request
    sdp = await request.body()
    req = urllib.request.Request("http://localhost:1984/api/webrtc?src=tapo",
                                 data=sdp, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return PlainTextResponse(r.read().decode())
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"go2rtc 연결 실패: {ex}")
