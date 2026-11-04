
import base64
import time
import hmac

from fastapi import (
    FastAPI,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Header,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import database as db
from .config import settings
from .services import (
    stt_service,
    llm_service,
    tts_service,
    hardware_service,
)
from .services.face_service import (
    face_service,
    FaceServiceError,
)


app = FastAPI(title="UniGuard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init()

totems: set[WebSocket] = set()
residents: dict[str, set[WebSocket]] = {}

# Historial independiente de cada conversación.
sessions: dict[str, list] = {}
session_last_seen: dict[str, float] = {}

SESSION_TIMEOUT = 180
MAX_IMAGE_SIZE = 5 * 1024 * 1024


def clean_expired_sessions():
    now = time.monotonic()

    expired = [
        session_id
        for session_id, last_seen in session_last_seen.items()
        if now - last_seen > SESSION_TIMEOUT
    ]

    for session_id in expired:
        sessions.pop(session_id, None)
        session_last_seen.pop(session_id, None)

    if expired:
        print(
            f"[SESIONES] Se eliminaron "
            f"{len(expired)} conversaciones vencidas.",
            flush=True,
        )


async def _broadcast(targets, payload):
    for ws in list(targets):
        try:
            await ws.send_json(payload)
        except Exception:
            targets.discard(ws)


@app.post("/api/converse")
async def converse(audio: UploadFile, session: str = "totem-1"):
    inicio = time.perf_counter()

    clean_expired_sessions()

    session = str(session).strip()

    if not session or len(session) > 100:
        raise HTTPException(
            status_code=400,
            detail="Identificador de conversación inválido."
        )

    conversation = sessions.setdefault(session, [])
    session_last_seen[session] = time.monotonic()

    audio_bytes = await audio.read()
    t_audio = time.perf_counter()

    text = await run_in_threadpool(
        stt_service.transcribe,
        audio_bytes
    )

    t_stt = time.perf_counter()

    if not text:
        reply, events = (
            "No te escuché bien. ¿Podés repetirlo?",
            []
        )
    else:
        reply, events = await run_in_threadpool(
            llm_service.chat,
            conversation,
            text,
        )

    t_llm = time.perf_counter()

    for event in events:
        await _broadcast(
            residents.setdefault(event["unit"], set()),
            event
        )

    t_broadcast = time.perf_counter()

    wav = await run_in_threadpool(
        tts_service.synthesize,
        reply
    )

    t_tts = time.perf_counter()

    session_last_seen[session] = time.monotonic()

    print(
        f"\n[TIEMPOS] "
        f"LECTURA: {t_audio - inicio:.2f}s | "
        f"STT: {t_stt - t_audio:.2f}s | "
        f"IA: {t_llm - t_stt:.2f}s | "
        f"EVENTOS: {t_broadcast - t_llm:.2f}s | "
        f"TTS: {t_tts - t_broadcast:.2f}s | "
        f"TOTAL: {t_tts - inicio:.2f}s",
        flush=True,
    )

    return {
        "transcript": text,
        "reply": reply,
        "audio_b64": base64.b64encode(wav).decode(),
        "events": events,
    }


# --------------------------------------------------
# PRUEBA DE COMPARACIÓN FACIAL
# --------------------------------------------------

@app.post("/api/face/compare")
async def compare_faces(
    image_a: UploadFile,
    image_b: UploadFile,
):
    if not image_a.content_type or not image_a.content_type.startswith("image/"):
        raise HTTPException(
            status_code=415,
            detail="El primer archivo debe ser una imagen."
        )

    if not image_b.content_type or not image_b.content_type.startswith("image/"):
        raise HTTPException(
            status_code=415,
            detail="El segundo archivo debe ser una imagen."
        )

    try:
        image_a_bytes = await image_a.read(MAX_IMAGE_SIZE + 1)
        image_b_bytes = await image_b.read(MAX_IMAGE_SIZE + 1)

        if len(image_a_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="La primera imagen supera los 5 MB."
            )

        if len(image_b_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(
                status_code=413,
                detail="La segunda imagen supera los 5 MB."
            )

        result = await run_in_threadpool(
            face_service.compare_images,
            image_a_bytes,
            image_b_bytes
        )

        return result

    except FaceServiceError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        ) from error

    finally:
        await image_a.close()
        await image_b.close()


class Decision(BaseModel):
    approve: bool


def _auth(token: str):
    configured_token = settings.resident_token

    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="La autenticación de residentes no está configurada."
        )

    if not token or not hmac.compare_digest(
        str(token),
        str(configured_token)
    ):
        raise HTTPException(
            status_code=401,
            detail="Token inválido."
        )


@app.post("/api/visits/{vid}/decision")
async def decide(
    vid: int,
    d: Decision,
    x_token: str = Header("")
):
    _auth(x_token)

    visit = db.get_visit(vid)

    if not visit:
        raise HTTPException(
            status_code=404,
            detail="Visita no encontrada."
        )

    db.set_visit(
        vid,
        "APPROVED" if d.approve else "DENIED"
    )

    door = (
        hardware_service.unlock_pulse()
        if d.approve
        else {"ok": False}
    )

    db.log(
        "VISIT_DECISION",
        {
            "visit": vid,
            "approve": d.approve,
            "door": door
        }
    )

    await _broadcast(
        totems,
        {
            "type": "decision",
            "visit_id": vid,
            "approved": d.approve and door["ok"],
        }
    )

    return {
        "ok": True,
        "door": door
    }


@app.post("/api/door/open")
async def remote_open(x_token: str = Header("")):
    _auth(x_token)

    result = hardware_service.unlock_pulse()

    db.log("REMOTE_OPEN", result)

    return result


@app.websocket("/ws/totem")
async def ws_totem(ws: WebSocket):
    await ws.accept()
    totems.add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        totems.discard(ws)


@app.websocket("/ws/resident/{unit}")
async def ws_resident(
    ws: WebSocket,
    unit: str,
    token: str = ""
):
    configured_token = settings.resident_token

    if (
        not configured_token
        or not token
        or not hmac.compare_digest(
            str(token),
            str(configured_token)
        )
    ):
        await ws.close(code=4401)
        return

    await ws.accept()

    residents.setdefault(unit, set()).add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        residents[unit].discard(ws)


@app.get("/api/health")
def health():
    clean_expired_sessions()

    return {
        "ok": True,
        "mode": settings.access_controller_mode,
        "active_sessions": len(sessions),
        "arguss_configured": bool(
            settings.arguss_api_url
            and settings.arguss_service_token
        )
    }
