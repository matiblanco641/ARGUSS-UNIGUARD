import os


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))

    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"La variable {name} debe ser un número entero."
        )


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))

    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"La variable {name} debe ser un número."
        )


class Settings:
    # Controlador de acceso
    access_controller_mode = os.getenv(
        "ACCESS_CONTROLLER_MODE",
        "SIMULATED",
    ).upper()

    controller_host = os.getenv(
        "CONTROLLER_HOST",
        "192.168.1.50",
    )

    controller_port = _get_int(
        "CONTROLLER_PORT",
        502,
    )

    relay_coil = _get_int(
        "RELAY_COIL",
        0,
    )

    unlock_seconds = _get_float(
        "UNLOCK_SECONDS",
        5.0,
    )

    # Inteligencia artificial
    ollama_url = os.getenv(
        "OLLAMA_URL",
        "https://ollama.com",
    ).rstrip("/")

    ollama_api_key = os.getenv(
        "OLLAMA_API_KEY",
        "",
    )

    llm_model = os.getenv(
        "OLLAMA_MODEL",
        "deepseek-v4.1-flash",
    )

    # Reconocimiento de voz
    whisper_model = os.getenv(
        "WHISPER_MODEL",
        "base",
    )

    # Voz de Sofía
    piper_model = os.getenv(
        "PIPER_MODEL",
        "models/es_AR-daniela-high.onnx",
    )

    # Base de datos local
    db_path = os.getenv(
        "DB_PATH",
        "uniguard.db",
    )

    # Comunicación con ARGUSS
    arguss_api_url = os.getenv(
        "ARGUSS_API_URL",
        "",
    ).rstrip("/")

    arguss_service_token = os.getenv(
        "ARGUSS_SERVICE_TOKEN",
        "",
    )

    arguss_timeout = _get_float(
        "ARGUSS_TIMEOUT",
        10.0,
    )

    # Autenticación de residentes
    resident_token = os.getenv(
        "RESIDENT_TOKEN",
        "",
    )


settings = Settings()
