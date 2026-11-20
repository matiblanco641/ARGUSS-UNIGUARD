import logging

from ..config import settings

log = logging.getLogger("hardware")


def unlock_pulse() -> dict:
    """
    Modo de simulación.
    No acciona cerraduras ni relés físicos.
    """

    mode = str(settings.access_controller_mode).upper()

    if mode == "REAL":
        log.error(
            "Se solicitó el modo REAL, pero el accionamiento físico "
            "no está habilitado en este servicio."
        )
        return {
            "ok": False,
            "mode": "REAL",
            "error": (
                "El accionamiento físico requiere una integración "
                "de control de acceso verificada e instalada por "
                "un técnico autorizado."
            )
        }

    log.warning("[SIMULADO] Solicitud de apertura de puerta.")

    return {
        "ok": True,
        "mode": "SIMULATED",
        "message": "Solicitud simulada correctamente."
    }
