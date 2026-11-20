
const API =
  location.hostname === "localhost" ||
  location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8001"
    : "https://arguss-uniguard.onrender.com";

const WS = API.replace(/^http/, "ws");

const $ = id => document.getElementById(id);

const avatar = new Avatar($("avatar"));
const voice = new Voice();

const LABEL = {
  IDLE: "Lista para ayudarte",
  LISTENING: "Te escucho…",
  THINKING: "Un momento…",
  SPEAKING: "Hablando",
  GRANTED: "Acceso permitido",
  DENIED: "Acceso no autorizado"
};

let busy = false;
let currentSession = null;
let lastInteractionAt = 0;
let idleTimer = null;

const SESSION_TIMEOUT = 180000;

let activeCall = null;
let callSocket = null;
let peerConnection = null;
let callAudioStream = null;

let ws = null;
let reconnectTimer = null;
let reconnectDelay = 1000;
let shuttingDown = false;

function createSessionId() {
  if (window.crypto?.randomUUID) {
    return crypto.randomUUID();
  }

  return "session-" + Date.now() + "-" +
    Math.random().toString(36).substring(2);
}

function getSessionId() {
  const now = Date.now();

  if (!currentSession || now - lastInteractionAt >= SESSION_TIMEOUT) {
    currentSession = createSessionId();
  }

  lastInteractionAt = now;
  return currentSession;
}

function scheduleSessionReset() {
  clearTimeout(idleTimer);

  idleTimer = setTimeout(() => {
    if (busy || activeCall) {
      scheduleSessionReset();
      return;
    }

    currentSession = null;
    lastInteractionAt = 0;

    $("log")?.replaceChildren();
    setState("IDLE");
  }, SESSION_TIMEOUT);
}

function cancelSessionReset() {
  clearTimeout(idleTimer);
  idleTimer = null;
}

function setState(state) {
  avatar.setState(state);

  const status = $("stxt");
  const dot = $("dot");

  if (status) status.textContent = LABEL[state] || LABEL.IDLE;

  if (dot) {
    dot.className = {
      LISTENING: "listening",
      THINKING: "thinking",
      GRANTED: "granted",
      DENIED: "denied"
    }[state] || "";
  }
}

function say(cls, text) {
  const log = $("log");
  if (!log || !text) return;

  const paragraph = document.createElement("p");
  paragraph.className = cls;
  paragraph.textContent = String(text);

  log.append(paragraph);

  while (log.children.length > 4) {
    log.firstChild.remove();
  }
}

async function speak(b64) {
  if (!b64) {
    setState("IDLE");
    return;
  }

  setState("SPEAKING");

  try {
    await voice.play(b64);
  } catch (error) {
    console.error("Error reproduciendo audio:", error);
  } finally {
    setState("IDLE");
  }
}

(function tick() {
  avatar.setLevel(voice.level());
  requestAnimationFrame(tick);
})();

const btn = $("talk");

if (btn) {
  btn.addEventListener("pointerdown", async event => {
    if (busy || activeCall || !ws || ws.readyState !== WebSocket.OPEN) {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        say("s", "Conexión con UniGuard no disponible.");
      }
      return;
    }

    cancelSessionReset();

    btn.setPointerCapture(event.pointerId);
    btn.classList.add("on");

    try {
      await voice.start();
      setState("LISTENING");
    } catch (error) {
      console.error("Error de micrófono:", error);
      btn.classList.remove("on");
      say("s", "No puedo acceder al micrófono.");
      scheduleSessionReset();
    }
  });

  btn.addEventListener("pointerup", async () => {
    if (
      busy ||
      activeCall ||
      !voice.rec ||
      voice.rec.state !== "recording"
    ) {
      btn.classList.remove("on");
      return;
    }

    btn.classList.remove("on");
    busy = true;
    btn.disabled = true;
    setState("THINKING");

    try {
      const sessionId = getSessionId();
      const audioBlob = await voice.stop();

      if (!audioBlob || !audioBlob.size) {
        throw new Error("No se grabó audio.");
      }

      const fd = new FormData();
      fd.append("audio", audioBlob, "voz.webm");

      const response = await fetch(
        `${API}/api/converse?session=${encodeURIComponent(sessionId)}`,
        {
          method: "POST",
          body: fd
        }
      );

      if (!response.ok) {
        throw new Error(`Error del servidor: ${response.status}`);
      }

      const result = await response.json();

      if (result.transcript) say("v", result.transcript);

      if (result.reply) {
        say("s", result.reply);
      } else {
        throw new Error("El servidor no devolvió una respuesta.");
      }

      if (result.audio_b64) {
        await speak(result.audio_b64);
      } else {
        setState("IDLE");
      }

    } catch (error) {
      console.error("Error en conversación:", error);
      setState("DENIED");
      say("s", "El servicio no responde. Pedí ayuda en recepción.");

    } finally {
      busy = false;
      btn.disabled = Boolean(activeCall);
      btn.classList.remove("on");
      scheduleSessionReset();
    }
  });

  btn.addEventListener("pointercancel", async () => {
    btn.classList.remove("on");

    if (voice.rec?.state === "recording") {
      try {
        await voice.stop();
      } catch (error) {
        console.error(error);
      }
    }

    scheduleSessionReset();
  });
}

/* CONEXIÓN GENERAL DEL TÓTEM */

function connectTotem() {
  if (shuttingDown) return;

  clearTimeout(reconnectTimer);

  ws = new WebSocket(`${WS}/ws/totem`);

  ws.onopen = () => {
    reconnectDelay = 1000;
    console.log("UniGuard conectado.");
  };

  ws.onmessage = async event => {
    let message;

    try {
      message = JSON.parse(event.data);
    } catch (error) {
      console.error("Mensaje WebSocket inválido:", error);
      return;
    }

    if (message.type === "decision") {
      await endCall("La visita fue resuelta.");

      setState(message.approved ? "GRANTED" : "DENIED");

      say(
        "s",
        message.approved
          ? "¡Bienvenido! Ya podés pasar."
          : "El residente no autorizó el ingreso."
      );

      setTimeout(() => setState("IDLE"), 6000);
    }

    if (message.type === "incoming_call") {
      await acceptCall(message);
    }
  };

  ws.onerror = error => {
    console.error("Error en conexión general:", error);
  };

  ws.onclose = () => {
    if (shuttingDown) return;

    console.warn("Conexión general cerrada. Reintentando...");

    reconnectTimer = setTimeout(() => {
      connectTotem();
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
    }, reconnectDelay);
  };
}

connectTotem();

/* LLAMADA WEBRTC */

function callStatus(message) {
  const element = $("call-status");
  if (element) element.textContent = message;
}

function sendSignal(data) {
  if (callSocket?.readyState === WebSocket.OPEN) {
    callSocket.send(JSON.stringify({
      type: "signal",
      data
    }));
  }
}

async function acceptCall(message) {
  if (activeCall || !message.call_id || !message.ticket) return;

  activeCall = message.call_id;
  cancelSessionReset();

  if (btn) btn.disabled = true;

  callStatus("Conectando con el residente…");

  try {
    const cameraStream = window.uniGuardCameraStream;

    if (!cameraStream?.getVideoTracks().length) {
      throw new Error("La cámara del tótem no está disponible.");
    }

    callAudioStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      },
      video: false
    });

    peerConnection = new RTCPeerConnection({
      iceServers: [
        { urls: "stun:stun.l.google.com:19302" }
      ]
    });

    cameraStream.getVideoTracks().forEach(track => {
      peerConnection.addTrack(track, cameraStream);
    });

    callAudioStream.getAudioTracks().forEach(track => {
      peerConnection.addTrack(track, callAudioStream);
    });

    peerConnection.onicecandidate = event => {
      if (event.candidate) {
        sendSignal({
          kind: "candidate",
          candidate: event.candidate
        });
      }
    };

    peerConnection.onconnectionstatechange = () => {
      if (
        peerConnection &&
        ["failed", "disconnected", "closed"].includes(
          peerConnection.connectionState
        )
      ) {
        endCall("La conexión se interrumpió.");
      }
    };

    callSocket = new WebSocket(
      `${WS}/ws/call/${encodeURIComponent(message.call_id)}?ticket=${encodeURIComponent(message.ticket)}`
    );

    callSocket.onmessage = async event => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "peer_ready") {
          const offer = await peerConnection.createOffer();
          await peerConnection.setLocalDescription(offer);

          sendSignal({
            kind: "description",
            description: peerConnection.localDescription
          });

          callStatus("Esperando al residente…");
        }

        if (data.type === "signal") {
          const signal = data.data;

          if (signal.kind === "description") {
            await peerConnection.setRemoteDescription(
              new RTCSessionDescription(signal.description)
            );
          }

          if (signal.kind === "candidate") {
            await peerConnection.addIceCandidate(
              new RTCIceCandidate(signal.candidate)
            );
          }
        }

        if (data.type === "call_ended") {
          await endCall("La llamada finalizó.");
        }

      } catch (error) {
        console.error("Error procesando señal:", error);
        await endCall("Error durante la llamada.");
      }
    };

    callSocket.onerror = () => {
      endCall("No se pudo establecer la conexión.");
    };

    callSocket.onclose = () => {
      if (activeCall) {
        endCall("La conexión se cerró.");
      }
    };

    setState("LISTENING");

  } catch (error) {
    console.error("Error al iniciar llamada:", error);
    await endCall("No se pudo iniciar la llamada.");
  }
}

async function endCall(message = "") {
  if (!activeCall && !peerConnection && !callAudioStream && !callSocket) {
    return;
  }

  const socket = callSocket;
  const connection = peerConnection;
  const audio = callAudioStream;

  activeCall = null;
  callSocket = null;
  peerConnection = null;
  callAudioStream = null;

  if (socket) {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "hangup" }));
    }

    if (
      socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING
    ) {
      socket.close();
    }
  }

  if (connection) {
    connection.close();
  }

  if (audio) {
    audio.getTracks().forEach(track => track.stop());
  }

  if (btn) btn.disabled = false;

  callStatus(message);
  setState("IDLE");
  scheduleSessionReset();
}

/* CIERRE */

currentSession = null;
lastInteractionAt = 0;

window.addEventListener("beforeunload", () => {
  shuttingDown = true;
  clearTimeout(reconnectTimer);
  clearTimeout(idleTimer);

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.close();
  }

  endCall();
});
