
import json
import time
import httpx
import asyncio
import re

from .. import database as db
from ..config import settings
from ..arguss_client import (
    send_visit_to_arguss,
    ArgussConnectionError,
)


SYSTEM = (
    "Sos Sofía, la recepcionista virtual de UniGuard, en Argentina. "
    "Respondé siempre en español rioplatense natural, correcto y amable. "
    "Usá frases cortas y claras, con buena gramática y acentuación. "
    "No uses portugués ni mezcles idiomas. "
    "No inventes nombres, unidades, datos ni respuestas. "
    "Si falta información, preguntá de forma natural qué dato necesitás. "
    "Para recibir una visita, averiguá quién viene y a qué unidad se dirige. "
    "Usá correctamente los signos de interrogación y exclamación. "
    "Respondé únicamente con el mensaje que debe recibir el usuario. "
    "Nunca autorices la entrada por tu cuenta: el residente debe aprobarla. "
    "Para buscar residentes o registrar visitas, utilizá las herramientas disponibles. "
    "Antes de registrar una visita, asegurate de tener el nombre del visitante "
    "y la unidad de destino. No inventes ninguno de esos datos."
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
                    "consulta": {"type": "string"}
                },
                "required": ["consulta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "solicitar_visita",
            "description": (
                "Envía una solicitud de visita al sistema central ARGUSS. "
                "Usar solo cuando se conozcan el nombre del visitante "
                "y la unidad de destino."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unidad": {"type": "string"},
                    "visitante": {"type": "string"}
                },
                "required": ["unidad", "visitante"]
            }
        }
    }
]


def obtener_departamento(unidad: str) -> int:
    """
    Convierte unidades como 1A, 2B o 3C
    en departamentos 1, 2 o 3.
    """
    coincidencia = re.match(r"^\s*([1-3])", unidad)

    if not coincidencia:
        raise ValueError(
            "La unidad debe comenzar con 1, 2 o 3."
        )

    return int(coincidencia.group(1))


def chat(history: list, user_text: str):
    """
    Procesa la conversación con Sofía.
    Las solicitudes de visita se envían al ARGUSS central.
    """

    history.append({
        "role": "user",
        "content": user_text
    })

    events = []

    for intento in range(3):
        inicio_ia = time.perf_counter()

        response = httpx.post(
            f"{settings.ollama_url}/api/chat",
            timeout=120,
            json={
                "model": settings.llm_model,
                "keep_alive": "10m",
                "stream": False,
                "tools": TOOLS,
                "messages": [
                    {"role": "system", "content": SYSTEM}
                ] + history[-6:]
            }
        )

        response.raise_for_status()
        datos = response.json()

        duracion_total = time.perf_counter() - inicio_ia
        duracion_generacion = (
            datos.get("eval_duration", 0) / 1_000_000_000
        )

        print(
            f"[OLLAMA] Intento: {intento + 1}"
            f" | Consulta: {duracion_total:.2f}s"
            f" | Tokens de entrada: "
            f"{datos.get('prompt_eval_count', 0)}"
            f" | Tokens generados: {datos.get('eval_count', 0)}"
            f" | Tiempo de generación: {duracion_generacion:.2f}s",
            flush=True
        )

        result = datos.get("message", {})
        history.append(result)

        calls = result.get("tool_calls")

        if not calls:
            answer = result.get("content") or ""
            return answer.strip(), events

        for call in calls:
            function = call["function"]["name"]
            arguments = call["function"]["arguments"]

            if function == "buscar_residente":

                output = db.find_residents(
                    arguments.get("consulta", "")
                )

            elif function == "solicitar_visita":

                unit = str(
                    arguments.get("unidad", "")
                ).strip()

                visitor = str(
                    arguments.get("visitante", "")
                ).strip()

                if not unit or not visitor:
                    output = {
                        "error": (
                            "Faltan el nombre del visitante "
                            "o la unidad de destino."
                        )
                    }

                else:
                    try:
                        department = obtener_departamento(unit)

                        # Enviar la visita al servidor central ARGUSS.
                        respuesta = asyncio.run(
                            send_visit_to_arguss(
                                department=department,
                                visitor_name=visitor,
                                visitor_reason=""
                            )
                        )

                        visit_id = respuesta.get("visit_id")

                        if visit_id is None:
                            visit_id = respuesta.get("id")

                        if visit_id is None:
                            raise ArgussConnectionError(
                                "ARGUSS no devolvió el identificador "
                                "de la visita. Revisar la respuesta del servidor."
                            )

                        # Auditoría local de UniGuard.
                        db.log(
                            "VISIT_SENT_TO_ARGUSS",
                            {
                                "visit_id": str(visit_id),
                                "departamento": department,
                                "unidad": unit,
                                "visitante": visitor,
                                "respuesta_arguss": respuesta
                            }
                        )

                        # Aviso al residente conectado.
                        events.append({
                            "type": "visit",
                            "visit_id": str(visit_id),
                            "unit": unit,
                            "visitor": visitor,
                            "department": department
                        })

                        output = {
                            "visit_id": str(visit_id),
                            "estado": "PENDING",
                            "mensaje": (
                                "La solicitud fue enviada al sistema ARGUSS "
                                "y está esperando la respuesta del residente."
                            )
                        }

                    except (ArgussConnectionError, ValueError) as error:
                        db.log(
                            "VISIT_SEND_FAILED",
                            {
                                "unidad": unit,
                                "visitante": visitor,
                                "error": str(error)
                            }
                        )

                        output = {
                            "error": str(error),
                            "mensaje": (
                                "No se pudo registrar la visita. "
                                "No confirmes que fue enviada."
                            )
                        }

            else:
                output = {
                    "error": "Herramienta desconocida"
                }

            history.append({
                "role": "tool",
                "content": json.dumps(
                    output,
                    ensure_ascii=False
                )
            })

    return (
        "Disculpá, no pude completar la solicitud. ¿Probamos de nuevo?",
        events
    )
