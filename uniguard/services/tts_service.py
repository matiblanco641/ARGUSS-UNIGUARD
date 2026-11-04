
import io
import re
import unicodedata

import numpy as np
import soundfile as sf
from kokoro import KPipeline

_pipeline = None

SAMPLE_RATE = 24000
VOICE = "ef_dora"


def get_pipeline():
    global _pipeline

    if _pipeline is None:
        _pipeline = KPipeline(lang_code="e")

    return _pipeline


def prepare_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = unicodedata.normalize("NFC", text)
    text = re.sub(
        r"\bUniGuard\b",
        "Uni Guard",
        text,
        flags=re.IGNORECASE,
    )

    text = "".join(
        char
        for char in text
        if unicodedata.category(char) not in ("Cc", "Cf", "Cs")
        or char in "\n\t"
    )

    text = "".join(
        " " if unicodedata.category(char).startswith("S") else char
        for char in text
    )

    return re.sub(r"\s+", " ", text).strip()


def synthesize(text: str) -> bytes:
    clean_text = prepare_text(text)

    if not clean_text:
        raise ValueError("No hay texto válido para generar el audio.")

    pipeline = get_pipeline()
    audio_chunks = []

    # Procesar cada fragmento apenas lo genera Kokoro.
    for _, _, audio in pipeline(clean_text, voice=VOICE):
        if audio is not None and len(audio) > 0:
            audio_chunks.append(
                np.asarray(audio, dtype=np.float32).reshape(-1)
            )

    if not audio_chunks:
        raise RuntimeError("Kokoro no generó audio.")

    audio = np.concatenate(audio_chunks)

    buffer = io.BytesIO()
    sf.write(buffer, audio, SAMPLE_RATE, format="WAV")

    return buffer.getvalue()
