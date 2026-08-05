"""routers/tapo.py — Tapo 카메라 go2rtc 중계(WebRTC/WS) 라우트 (P1-7 분할).

go2rtc(localhost:1984)를 같은 출처로 프록시해 CORS 회피. main·app_state 의존 없음(자립).
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket
from fastapi.responses import PlainTextResponse

router = APIRouter()


def _resolve_src(src: str | None) -> str:
    """중계 대상 스트림명 검증 — 'tapo'(레거시/safety-local) 또는 등록된 카메라 id 만 허용.
    임의 문자열을 go2rtc 로 넘기지 않아 오픈프록시·SSRF 를 차단한다."""
    src = (src or "tapo").strip()
    if src == "tapo":
        return "tapo"
    try:
        import camera_registry as _reg
        if _reg.get(src) is not None:
            return src
    except Exception:  # noqa: BLE001  레지스트리 접근 실패 시 보수적으로 거부
        pass
    raise HTTPException(status_code=404, detail="등록되지 않은 스트림")


def _ensure_stream(src: str) -> None:
    """go2rtc 에 해당 카메라 스트림이 없으면 즉시 등록(온디맨드) — 기동 순서·재시작에 무관하게 WebRTC 성립.
    'tapo'(config 고정)나 go2rtc 미실행이면 조용히 무시(스냅샷 폴백)."""
    if src == "tapo":
        return
    try:
        import urllib.parse
        import urllib.request

        import camera_registry as _reg
        source = _reg.source_of(src)
        if not source:
            return
        url = "http://localhost:1984/api/streams?" + urllib.parse.urlencode({"name": src, "src": source})
        urllib.request.urlopen(urllib.request.Request(url, method="PUT"), timeout=3)
    except Exception:  # noqa: BLE001  go2rtc 미실행/실패 — WebRTC 없이 폴백
        pass


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
    """브라우저 ↔ go2rtc WebSocket 양방향 중계(같은 출처). ?src= 로 스트림 선택(기본 tapo)."""
    try:
        src = _resolve_src(ws.query_params.get("src"))
    except HTTPException:
        await ws.close(code=1008)
        return
    _ensure_stream(src)
    await ws.accept()
    import urllib.parse

    import websockets
    up_url = "ws://localhost:1984/api/ws?" + urllib.parse.urlencode({"src": src})
    try:
        async with websockets.connect(up_url) as up:
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
    영상(미디어)은 WebRTC로 직접 흐르고, 여기선 SDP 신호만 전달 → CORS 문제 없음.
    ?src= 로 스트림 선택(기본 tapo)."""
    import urllib.parse
    import urllib.request
    src = _resolve_src(request.query_params.get("src"))
    _ensure_stream(src)
    sdp = await request.body()
    req = urllib.request.Request(
        "http://localhost:1984/api/webrtc?" + urllib.parse.urlencode({"src": src}),
        data=sdp, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return PlainTextResponse(r.read().decode())
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"go2rtc 연결 실패: {ex}")
