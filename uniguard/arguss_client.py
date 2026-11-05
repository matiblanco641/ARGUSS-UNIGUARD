
import httpx

from .config import settings


class ArgussConnectionError(Exception):
    pass


async def send_visit_to_arguss(
    department: int,
    visitor_name: str,
    visitor_reason: str = "",
):
    """
    Envía una solicitud de visita desde UniGuard
    al servidor central ARGUSS.
    """

    if department not in (1, 2, 3):
        raise ValueError("El departamento debe ser 1, 2 o 3.")

    if not settings.arguss_api_url:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_API_URL."
        )

    if not settings.arguss_service_token:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_SERVICE_TOKEN."
        )

    base_url = settings.arguss_api_url.rstrip("/")
    url = f"{base_url}/api/totem/visits"

    headers = {
        "X-TOTEM-KEY": settings.arguss_service_token,
        "Content-Type": "application/json",
    }

    payload = {
        "department": department,
        "visitor_name": visitor_name,
        "visitor_reason": visitor_reason,
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.arguss_timeout
        ) as client:
            response = await client.post(
                url,
                json=payload,
                headers=headers,
            )

            response.raise_for_status()
            return response.json()

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
    Requiere que exista la ruta GET correspondiente
    en el servidor ARGUSS.
    """

    if not settings.arguss_api_url:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_API_URL."
        )

    if not settings.arguss_service_token:
        raise ArgussConnectionError(
            "Falta configurar ARGUSS_SERVICE_TOKEN."
        )

    base_url = settings.arguss_api_url.rstrip("/")
    url = f"{base_url}/api/totem/visits/{visit_id}"

    headers = {
        "X-TOTEM-KEY": settings.arguss_service_token,
    }

    try:
        async with httpx.AsyncClient(
            timeout=settings.arguss_timeout
        ) as client:
            response = await client.get(
                url,
                headers=headers,
            )

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as error:
        raise ArgussConnectionError(
            f"ARGUSS respondió con HTTP "
            f"{error.response.status_code}."
        ) from error

    except httpx.RequestError as error:
        raise ArgussConnectionError(
            "No se pudo consultar ARGUSS."
        ) from error
