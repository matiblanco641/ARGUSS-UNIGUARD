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
    $("log").replaceChildren();
    setState("IDLE");

  }, SESSION_TIMEOUT);
}

function cancelSessionReset() {
  clearTimeout(idleTimer);
  idleTimer = null;
}

function setState(state) {
  avatar.setState(state);
  $("stxt").textContent = LABEL[state];

  $("dot").className = {
    LISTENING: "listening",
    THINKING: "thinking",
    GRANTED: "granted",
    DENIED: "denied"
  }[state] || "";
}

function say(cls, text) {
  const paragraph = document.createElement("p");
  paragraph.className = cls;
  paragraph.textContent = text;

  $("log").append(paragraph);

  while ($("log").children.length > 4) {
    $("log").firstChild.remove();
  }
}

async function speak(b64) {
  setState("SPEAKING");
  await voice.play(b64);
  setState("IDLE");
}

(function tick() {
  avatar.setLevel(voice.level());
  requestAnimationFrame(tick);
})();

const btn = $("talk");

btn.addEventListener("pointerdown", async event => {
  if (busy || activeCall) return;

  cancelSessionReset();

  btn.setPointerCapture(event.pointerId);
  btn.classList.add("on");

  try {
    await voice.start();
    setState("LISTENING");
  } catch (error) {
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
    const fd = new FormData();

    fd.append("audio", await voice.stop(), "voz.webm");

    const response = await fetch(
      `${API}/api/converse?session=${encodeURIComponent(sessionId)}`,
      {
        method: "POST",
        body: fd
      }
    );

    if (!response.ok) {
      throw new Error("Error en el servidor UniGuard.");
    }

    const result = await response.json();

    if (result.transcript) say("v", result.transcript);
    say("s", result.reply);

    await speak(result.audio_b64);

  } catch (error) {
    console.error(error);
    setState("DENIED");
    say("s", "El servicio no responde. Pedí ayuda en recepción.");

  } finally {
    busy = false;
    btn.disabled = Boolean(activeCall);
    btn.classList.remove("on");
    scheduleSessionReset();
  }
});


/* CONEXIÓN GENERAL DEL TÓTEM */

const ws = new WebSocket(`${WS}/ws/totem`);

ws.onmessage = async event => {
  const message = JSON.parse(event.data);

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
  console.error("Error en la conexión con UniGuard:", error);
};


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
  if (activeCall) return;

  activeCall = message.call_id;
  cancelSessionReset();

  btn.disabled = true;
  callStatus("Conectando con el residente…");

  try {
    const cameraStream = window.uniGuardCameraStream;

    if (!cameraStream?.getVideoTracks().length) {
      throw new Error("La cámara del tótem no está disponible.");
    }

    // El micrófono del tótem se utiliza durante la llamada.
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
        ["failed", "disconnected", "closed"].includes(
          peerConnection.connectionState
        )
      ) {
        endCall("La conexión se interrumpió.");
      }
    };

    callSocket = new WebSocket(
      `${protocol}//${location.hostname || "localhost"}:8001/ws/call/` +
      `${encodeURIComponent(message.call_id)}?ticket=` +
      `${encodeURIComponent(message.ticket)}`
    );

    callSocket.onmessage = async event => {
      const data = JSON.parse(event.data);

      if (data.type === "peer_ready") {
        const offer = await peerConnection.createOffer();

        await peerConnection.setLocalDescription(offer);

        sendSignal({
          kind: "description",
          description: peerConnection.localDescription
        });

        callStatus("Llamada conectada.");
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
  if (!activeCall && !peerConnection && !callAudioStream) return;

  const socket = callSocket;
  const connection = peerConnection;
  const audio = callAudioStream;

  activeCall = null;
  callSocket = null;
  peerConnection = null;
  callAudioStream = null;

  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "hangup" }));
    socket.close();
  }

  if (connection) {
    connection.close();
  }

  if (audio) {
    audio.getTracks().forEach(track => track.stop());
  }

  btn.disabled = false;
  callStatus(message);
  setState("IDLE");
  scheduleSessionReset();
}


// Si se recarga la página, no se conserva una sesión anterior.
currentSession = null;
lastInteractionAt = 0;

window.addEventListener("beforeunload", () => {
  endCall();
});
