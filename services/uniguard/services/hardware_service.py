import socket, struct, threading, time, logging
from ..config import settings
log = logging.getLogger("hardware")

def _modbus_coil(on: bool):
    """Modbus TCP, función 5 (Write Single Coil)."""
    pdu = struct.pack(">BHH", 5, settings.relay_coil, 0xFF00 if on else 0x0000)
    frame = struct.pack(">HHHB", 1, 0, len(pdu) + 1, 1) + pdu
    with socket.create_connection((settings.controller_host, settings.controller_port), timeout=2) as s:
        s.sendall(frame); s.recv(12)

def _set(on: bool):
    if settings.access_controller_mode.upper() == "REAL": _modbus_coil(on)
    else: log.warning("[SIMULADO] puerta %s", "ABIERTA" if on else "CERRADA")

def unlock_pulse() -> dict:
    """Abre por unlock_seconds y vuelve a cerrar. Fail-safe: ante cualquier error la puerta queda cerrada."""
    try:
        _set(True)
    except Exception as e:
        log.error("fallo al abrir: %s", e)
        return {"ok": False, "error": str(e)}
    def relock():
        time.sleep(settings.unlock_seconds)
        for _ in range(3):
            try: _set(False); return
            except Exception: time.sleep(1)
    threading.Thread(target=relock, daemon=True).start()
    return {"ok": True, "mode": settings.access_controller_mode}
