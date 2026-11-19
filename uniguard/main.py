
import base64
import time
import hmac
import secrets
import hashlib
import json
import asyncio

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

sessions: dict[str, list] = {}
session_last_seen: dict[str, float] = {}

SESSION_TIMEOUT = 180
MAX_IMAGE_SIZE = 5 * 1024 * 1024
FACE_CHALLENGE_TIMEOUT = 60
MAX_PASSWORD_ATTEMPTS = 5

CALL_TIMEOUT = 180
CALL_TICKET_TIMEOUT = 60

face_challenges = {}
calls = {}
call_tickets = {}


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

    for challenge_id, challenge in list(face_challenges.items()):
        if now - challenge["created"] > FACE_CHALLENGE_TIMEOUT:
            face_challenges.pop(challenge_id, None)

    for ticket, data in list(call_tickets.items()):
        if now - data["created"] > CALL_TICKET_TIMEOUT:
            call_tickets.pop(ticket, None)

    for call_id, call in list(calls.items()):
        if now - call["last_seen"] > CALL_TIMEOUT:
            calls.pop(call_id, None)


async def _broadcast(targets, payload):
    for ws in list(targets):
        try:
            await ws.send_json(payload)
        except Exception:
            targets.discard(ws)


async def close_call(call_id: str, reason: str):
    call = calls.pop(call_id, None)

    if not call:
        return

    for ticket in call.get("tickets", []):
        call_tickets.pop(ticket, None)

    payload = {
        "type": "call_ended",
        "call_id": call_id,
        "reason": reason,
    }

    await _broadcast(call["connections"], payload)


async def close_visit_calls(visit_id: int):
    for call_id, call in list(calls.items()):
        if call["visit_id"] == visit_id:
            await close_call(call_id, "visit_resolved")


async def send_call_signal(call_id: str, sender: str, payload: dict):
    call = calls.get(call_id)

    if not call:
        raise HTTPException(
            status_code=404,
            detail="La llamada ya no existe."
        )

    call["last_seen"] = time.monotonic()

    message = {
        "type": "signal",
        "from": sender,
        "data": payload,
    }

    for ws in list(call["connections"]):
        if call["roles"].get(ws) != sender:
            try:
                await ws.send_json(message)
            except Exception:
                call["connections"].discard(ws)
                call["roles"].pop(ws, None)


async def read_image(upload: UploadFile):
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise HTTPException(
            status_code=415,
            detail="El archivo debe ser una imagen."
        )

    data = await upload.read(MAX_IMAGE_SIZE + 1)

    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="La imagen supera el límite de 5 MB."
        )

    if not data:
        raise HTTPException(
            status_code=400,
            detail="La imagen está vacía."
        )

    return data


def verify_password_hash(password: str, encoded: str):
    try:
        algorithm, salt_hex, hash_hex = encoded.split("$")

        if algorithm != "scrypt":
            return False

        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)

        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
            dklen=len(expected),
        )

        return hmac.compare_digest(actual, expected)

    except (ValueError, TypeError):
        return False


class Decision(BaseModel):
    approve: bool


class FacePasswordRequest(BaseModel):
    challenge_id: str
    password: str


class CallRequest(BaseModel):
    visit_id: int


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
# IDENTIFICACIÓN FACIAL
# --------------------------------------------------

@app.post("/api/face/identify")
async def identify_face(image: UploadFile):
    clean_expired_sessions()
    image_bytes = await read_image(image)

    try:
        templates = await run_in_threadpool(
            db.get_face_templates
        )

        result = await run_in_threadpool(
            face_service.identify,
            image_bytes,
            templates
        )

        if not result["matched"]:
            db.log(
                "FACE_IDENTIFICATION_FAILED",
                {"reason": result["reason"]}
            )

            return {
                "matched": False,
                "message": (
                    "No se pudo confirmar la identidad. "
                    "Podés continuar con la verificación alternativa."
                ),
            }

        challenge_id = secrets.token_urlsafe(32)

        face_challenges[challenge_id] = {
            "resident_id": result["resident_id"],
            "created": time.monotonic(),
            "attempts": 0,
        }

        db.log(
            "FACE_IDENTIFICATION_CANDIDATE",
            {
                "resident_id": result["resident_id"],
                "similarity": round(result["similarity"], 4),
            }
        )

        return {
            "matched": True,
            "challenge_id": challenge_id,
            "name": result["name"],
            "unit": result["unit"],
            "message": "Coincidencia preliminar. Se necesita la contraseña.",
        }

    except FaceServiceError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        ) from error

    finally:
        await image.close()


# --------------------------------------------------
# SEGUNDO FACTOR
# --------------------------------------------------

@app.post("/api/face/verify-password")
async def verify_face_password(data: FacePasswordRequest):
    clean_expired_sessions()

    challenge = face_challenges.get(data.challenge_id)

    if not challenge:
        raise HTTPException(
            status_code=401,
            detail="La verificación venció. Volvé a intentarlo."
        )

    if challenge["attempts"] >= MAX_PASSWORD_ATTEMPTS:
        face_challenges.pop(data.challenge_id, None)

        raise HTTPException(
            status_code=429,
            detail="Se alcanzó el máximo de intentos."
        )

    challenge["attempts"] += 1

    resident = db.get_resident_auth(
        challenge["resident_id"]
    )

    if not resident or not resident.get("password_hash"):
        face_challenges.pop(data.challenge_id, None)

        raise HTTPException(
            status_code=401,
            detail="No se pudo completar la verificación."
        )

    valid = verify_password_hash(
        data.password,
        resident["password_hash"]
    )

    if not valid:
        db.log(
            "FACE_PASSWORD_FAILED",
            {"resident_id": resident["id"]}
        )

        if challenge["attempts"] >= MAX_PASSWORD_ATTEMPTS:
            face_challenges.pop(data.challenge_id, None)

        raise HTTPException(
            status_code=401,
            detail="La contraseña no es correcta."
        )

    face_challenges.pop(data.challenge_id, None)

    db.log(
        "RESIDENT_IDENTITY_VERIFIED",
        {"resident_id": resident["id"]}
    )

    return {
        "ok": True,
        "resident": {
            "id": resident["id"],
            "name": resident["name"],
            "unit": resident["unit"],
        },
        "message": (
            "Identidad verificada. "
            "Esto no autoriza la apertura de la puerta."
        ),
    }


@app.post("/api/face/compare")
async def compare_faces(
    image_a: UploadFile,
    image_b: UploadFile,
):
    image_a_bytes = await read_image(image_a)
    image_b_bytes = await read_image(image_b)

    try:
        return await run_in_threadpool(
            face_service.compare_images,
            image_a_bytes,
            image_b_bytes
        )

    except FaceServiceError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error)
        ) from error

    finally:
        await image_a.close()
        await image_b.close()


# --------------------------------------------------
# AUTENTICACIÓN ACTUAL DE RESIDENTES
# --------------------------------------------------

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


# --------------------------------------------------
# INICIO DE LLAMADA
# --------------------------------------------------

@app.post("/api/calls")
async def start_call(
    data: CallRequest,
    x_token: str = Header("")
):
    _auth(x_token)
    clean_expired_sessions()

    visit = db.get_visit(data.visit_id)

    if not visit:
        raise HTTPException(
            status_code=404,
            detail="Visita no encontrada."
        )

    if visit["status"] != "PENDING":
        raise HTTPException(
            status_code=409,
            detail="La visita ya fue resuelta."
        )

    unit = str(visit["unit"] or "").strip()

    if not unit:
        raise HTTPException(
            status_code=400,
            detail="La visita no tiene una unidad asociada."
        )

    call_id = secrets.token_urlsafe(18)
    totem_ticket = secrets.token_urlsafe(32)
    resident_ticket = secrets.token_urlsafe(32)
    now = time.monotonic()

    calls[call_id] = {
        "visit_id": data.visit_id,
        "unit": unit,
        "created": now,
        "last_seen": now,
        "connections": set(),
        "roles": {},
        "tickets": [totem_ticket, resident_ticket],
    }

    call_tickets[totem_ticket] = {
        "call_id": call_id,
        "role": "totem",
        "created": now,
    }

    call_tickets[resident_ticket] = {
        "call_id": call_id,
        "role": "resident",
        "created": now,
    }

    await _broadcast(
        totems,
        {
            "type": "incoming_call",
            "call_id": call_id,
            "visit_id": data.visit_id,
            "unit": unit,
            "ticket": totem_ticket,
        }
    )

    await _broadcast(
        residents.setdefault(unit, set()),
        {
            "type": "incoming_call",
            "call_id": call_id,
            "visit_id": data.visit_id,
            "unit": unit,
            "ticket": resident_ticket,
        }
    )

    db.log(
        "CALL_STARTED",
        {
            "call_id": call_id,
            "visit_id": data.visit_id,
            "unit": unit,
        }
    )

    return {
        "ok": True,
        "call_id": call_id,
        "message": "Solicitud de llamada enviada.",
    }


# --------------------------------------------------
# SEÑALIZACIÓN WEBRTC
# --------------------------------------------------

@app.websocket("/ws/call/{call_id}")
async def ws_call(
    ws: WebSocket,
    call_id: str,
    ticket: str = "",
):
    ticket_data = call_tickets.get(ticket)

    if (
        not ticket_data
        or ticket_data["call_id"] != call_id
        or time.monotonic() - ticket_data["created"] > CALL_TICKET_TIMEOUT
    ):
        await ws.close(code=4401)
        return

    call = calls.get(call_id)

    if not call:
        await ws.close(code=4404)
        return

    role = ticket_data["role"]

    if role in call["roles"].values():
        await ws.close(code=4409)
        return

    await ws.accept()

    call["connections"].add(ws)
    call["roles"][ws] = role
    call["last_seen"] = time.monotonic()

    await _broadcast(
        call["connections"],
        {
            "type": "call_peer",
            "role": role,
        }
    )

    try:
        while True:
            raw = await ws.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            message_type = message.get("type")

            if message_type == "signal":
                payload = message.get("data")

                if isinstance(payload, dict):
                    await send_call_signal(
                        call_id,
                        role,
                        payload
                    )

            elif message_type == "hangup":
                await close_call(call_id, "hangup")
                break

            call["last_seen"] = time.monotonic()

    except WebSocketDisconnect:
        pass

    finally:
        call = calls.get(call_id)

        if call:
            call["connections"].discard(ws)
            call["roles"].pop(ws, None)

            if not call["connections"]:
                await close_call(call_id, "disconnected")


# --------------------------------------------------
# DECISIÓN DE VISITA
# --------------------------------------------------

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

    if visit["status"] != "PENDING":
        raise HTTPException(
            status_code=409,
            detail="La visita ya fue resuelta."
        )

    db.set_visit(
        vid,
        "APPROVED" if d.approve else "DENIED"
    )

    await close_visit_calls(vid)

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


# --------------------------------------------------
# WEBSOCKET TÓTEM
# --------------------------------------------------

@app.websocket("/ws/totem")
async def ws_totem(ws: WebSocket):
    await ws.accept()
    totems.add(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        totems.discard(ws)


# --------------------------------------------------
# WEBSOCKET RESIDENTE
# --------------------------------------------------

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
