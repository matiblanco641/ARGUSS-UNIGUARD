import json
import logging
import re
import time

import httpx

from .. import database as db
from ..config import settings
from ..arguss_client import (
    send_visit_to_arguss,
    ArgussConnectionError,
)

log = logging.getLogger("uniguard.llm")

OLLAMA_URL = "https://ollama.com/api/chat"

SYSTEM = (
    "Sos Sofía, la recepcionista virtual de UniGuard, en Argentina. "
    "Respondé siempre en español rioplatense natural, correcto y amable. "
    "Usá frases cortas y claras. No mezcles idiomas. "
    "No inventes nombres, unidades ni datos. "
    "Si falta información, preguntá qué dato necesitás. "
    "Para registrar una visita necesitás el nombre del visitante "
    "y la unidad de destino. "
    "Nunca autorices la entrada por tu cuenta: el residente debe aprobarla. "
    "Respondé únicamente con el mensaje que debe recibir el usuario."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_residente",
            "description": "Busca residentes por nombre o unidad.",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {"type": "string"},
                },
                "required": ["consulta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solicitar_visita",
            "description": (
                "Envía una solicitud de visita a ARGUSS. "
                "Usar solamente cuando se conozcan el nombre "
                "del visitante y la unidad de destino."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unidad": {"type": "string"},
                    "visitante": {"type": "string"},
                },
                "required": ["unidad", "visitante"],
            },
        },
    },
]


def obtener_departamento(unidad: str) -> int:
    coincidencia = re.match(r"^\s*([1-3])", str(unidad))

    if not coincidencia:
        raise ValueError(
            "La unidad debe comenzar con 1, 2 o 3."
        )

    return int(coincidencia.group(1))


def _parse_arguments(arguments):
    if isinstance(arguments, dict):
        return arguments

    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    return {}


async def _execute_tool(call, events):
    function_data = call.get("function", {})
    function_name = function_data.get("name")
    arguments = _parse_arguments(
        function_data.get("arguments", {})
    )

    if function_name == "buscar_residente":
        consulta = str(arguments.get("consulta", "")).strip()

        if not consulta:
            return {"error": "Falta el nombre o la unidad del residente."}

        return db.find_residents(consulta)

    if function_name == "solicitar_visita":
        unit = str(arguments.get("unidad", "")).strip()
        visitor = str(arguments.get("visitante", "")).strip()

        if not unit or not visitor:
            return {
                "error": "Faltan el nombre del visitante o la unidad."
            }

        department = obtener_departamento(unit)

        try:
            response = await send_visit_to_arguss(
                department=department,
                visitor_name=visitor,
                visitor_reason="",
            )

            if not isinstance(response, dict):
                raise ArgussConnectionError(
                    "ARGUSS devolvió una respuesta inválida."
                )

            visit_id = response.get("visit_id") or response.get("id")

            if visit_id is None:
                raise ArgussConnectionError(
                    "ARGUSS no devolvió el identificador de la visita."
                )

            visit_id = str(visit_id)

            db.log(
                "VISIT_SENT_TO_ARGUSS",
                {
                    "visit_id": visit_id,
                    "department": department,
                    "unit": unit,
                    "visitor": visitor,
                    "response": response,
                },
            )

            events.append(
                {
                    "type": "visit",
                    "visit_id": visit_id,
                    "unit": unit,
                    "visitor": visitor,
                    "department": department,
                }
            )

            return {
                "visit_id": visit_id,
                "estado": "PENDING",
                "mensaje": (
                    "La solicitud fue enviada a ARGUSS "
                    "y espera la respuesta del residente."
                ),
            }

        except (ArgussConnectionError, ValueError) as error:
            db.log(
                "VISIT_SEND_FAILED",
                {
                    "unit": unit,
                    "visitor": visitor,
                    "error": str(error),
                },
            )
            return {
                "error": str(error),
                "mensaje": "No se pudo registrar la visita.",
            }

    return {"error": "Herramienta desconocida."}


async def chat(history: list, user_text: str):
    """
    Procesa la conversación con Sofía.
    Devuelve (respuesta, eventos).
    """

    if not isinstance(history, list):
        history = []

    user_text = str(user_text or "").strip()

    if not user_text:
        return "No escuché ningún mensaje. ¿Podés repetirlo?", []

    history.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    events = []

    headers = {
        "Authorization": f"Bearer {settings.ollama_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            started = time.perf_counter()

            try:
                response = await client.post(
                    OLLAMA_URL,
                    headers=headers,
                    json={
                        "model": settings.llm_model,
                        "keep_alive": "10m",
                        "stream": False,
                        "tools": TOOLS,
                        "messages": [
                            {
                                "role": "system",
                                "content": SYSTEM,
                            }
                        ] + history[-10:],
                    },
                )

                response.raise_for_status()
                data = response.json()

            except (httpx.HTTPError, ValueError) as error:
                log.exception("Error consultando Ollama")

                if attempt < 2:
                    continue

                return (
                    "En este momento tengo problemas para responder. "
                    "¿Podés intentarlo nuevamente?",
                    events,
                )

            elapsed = time.perf_counter() - started

            log.info(
                "Ollama intento %s | duración %.2fs",
                attempt + 1,
                elapsed,
            )

            result = data.get("message") or {}
            if not isinstance(result, dict):
                return "No pude interpretar la respuesta. ¿Probamos otra vez?", events

            history.append(result)

            calls = result.get("tool_calls") or []

            if not calls:
                answer = str(result.get("content") or "").strip()

                if not answer:
                    answer = "No pude generar una respuesta. ¿Podés repetirlo?"

                return answer, events

            for call in calls:
                try:
                    output = await _execute_tool(call, events)
                except (ValueError, ArgussConnectionError) as error:
                    output = {"error": str(error)}
                except Exception:
                    log.exception("Error ejecutando herramienta")
                    output = {
                        "error": "No se pudo completar la operación."
                    }

                function_data = call.get("function", {})
                tool_name = function_data.get("name", "herramienta")

                history.append(
                    {
                        "role": "tool",
                        "content": json.dumps(
                            output,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

        return (
            "Disculpá, no pude completar la solicitud. ¿Probamos de nuevo?",
            events,
        )
