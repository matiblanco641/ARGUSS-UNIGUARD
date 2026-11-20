import httpx

from .config import settings


class ArgussConnectionError(Exception):
    pass


def _get_headers():
    if not settings.arguss_api_url:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_API_URL."
        )

    if not settings.arguss_service_token:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_SERVICE_TOKEN."
        )

    return {
        "X-TOTEM-KEY": settings.arguss_service_token,
        "Content-Type": "application/json",
    }


def _parse_response(response: httpx.Response):
    try:
        result = response.json()
    except ValueError as error:
        raise ArgussConnectionError(
            "ARGUSS devolvió una respuesta que no es JSON válido."
        ) from error

    if not isinstance(result, dict):
        raise ArgussConnectionError(
            "ARGUSS devolvió un formato de respuesta inesperado."
        )

    return result


async def send_visit_to_arguss(
    department: int,
    visitor_name: str,
    visitor_reason: str = "",
):
    """
    Envía una solicitud de visita al servidor central ARGUSS.
    """

    if department not in (1, 2, 3):
        raise ValueError(
            "El departamento debe ser 1, 2 o 3."
        )

    visitor_name = visitor_name.strip()
    visitor_reason = visitor_reason.strip()

    if not visitor_name:
        raise ValueError(
            "El nombre del visitante es obligatorio."
        )

    headers = _get_headers()

    url = (
        f"{settings.arguss_api_url}"
        "/api/totem/visits"
    )

    payload = {
        "department": department,
        "visitor_name": visitor_name,
        "visitor_reason": visitor_reason,
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.arguss_timeout,
        ) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

            response.raise_for_status()

            return _parse_response(response)

    except httpx.HTTPStatusError as error:
        raise ArgussConnectionError(
            f"ARGUSS respondió con HTTP "
            f"{error.response.status_code}."
        ) from error

    except httpx.RequestError as error:
        raise ArgussConnectionError(
            "No se pudo establecer conexión con ARGUSS."
        ) from error


async def get_visit_status(visit_id: str):
    """
    Consulta el estado de una visita en ARGUSS.
    Requiere que ARGUSS tenga implementada la ruta GET correspondiente.
    """

    if not visit_id or not str(visit_id).strip():
        raise ValueError(
            "El identificador de visita es obligatorio."
        )

    headers = _get_headers()

    url = (
        f"{settings.arguss_api_url}"
        f"/api/totem/visits/{visit_id}"
    )

    try:
        async with httpx.AsyncClient(
            timeout=settings.arguss_timeout,
        ) as client:
            response = await client.get(
                url,
                headers=headers,
            )

            response.raise_for_status()

            return _parse_response(response)

    except httpx.HTTPStatusError as error:
        raise ArgussConnectionError(
            f"ARGUSS respondió con HTTP "
            f"{error.response.status_code}."
        ) from error

    except httpx.RequestError as error:
        raise ArgussConnectionError(
            "No se pudo consultar el estado de la visita en ARGUSS."
        ) from error
