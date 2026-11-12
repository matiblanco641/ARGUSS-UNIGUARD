
import os


class Settings:
    # Controlador de acceso
    access_controller_mode = os.getenv(
        "ACCESS_CONTROLLER_MODE", "SIMULATED"
    )
    controller_host = os.getenv(
        "CONTROLLER_HOST", "192.168.1.50"
    )
    controller_port = int(
        os.getenv("CONTROLLER_PORT", "502")
    )
    relay_coil = int(os.getenv("RELAY_COIL", "0"))
    unlock_seconds = float(
        os.getenv("UNLOCK_SECONDS", "5")
    )

    # Inteligencia artificial en la nube
    ollama_url = os.getenv(
        "OLLAMA_URL", "https://ollama.com"
    )
    ollama_api_key = os.getenv(
        "OLLAMA_API_KEY", ""
    )
    llm_model = os.getenv(
        "OLLAMA_MODEL", "deepseek-v4.1-flash"
    )

    # Reconocimiento de voz
    whisper_model = os.getenv(
        "WHISPER_MODEL", "base"
    )

    # Voz de Sofía
    piper_model = os.getenv(
        "PIPER_MODEL",
        "models/es_AR-daniela-high.onnx"
    )

    # Base de datos local de UniGuard
    db_path = os.getenv(
        "DB_PATH", "uniguard.db"
    )

    # Comunicación con ARGUSS
    arguss_api_url = os.getenv(
        "ARGUSS_API_URL", ""
    ).rstrip("/")

    arguss_service_token = os.getenv(
        "ARGUSS_SERVICE_TOKEN", ""
    )

    arguss_timeout = float(
        os.getenv("ARGUSS_TIMEOUT", "10")
    )

    # Autenticación de residentes
    resident_token = os.getenv(
        "RESIDENT_TOKEN", ""
    )


settings = Settings()
