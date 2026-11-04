import io
from faster_whisper import WhisperModel
from ..config import settings
_model = None
def transcribe(audio_bytes: bytes) -> str:
    global _model
    if _model is None:
        _model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")
    segs, _ = _model.transcribe(io.BytesIO(audio_bytes), language="es", vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()
