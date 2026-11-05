
const API = location.hostname
  ? `http://${location.hostname}:8001`
  : "http://localhost:8001";

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

// Gestión de conversaciones independientes.
const SESSION_TIMEOUT = 180 * 1000;

let currentSession = null;
let lastInteractionAt = 0;
let idleTimer = null;

function createSessionId() {
  if (window.crypto && crypto.randomUUID) {
    return crypto.randomUUID();
  }

  return (
    "session-" +
    Date.now() +
    "-" +
    Math.random().toString(36).substring(2)
  );
}

function getSessionId() {
  const now = Date.now();

  if (
    !currentSession ||
    now - lastInteractionAt >= SESSION_TIMEOUT
  ) {
    currentSession = createSessionId();
  }

  lastInteractionAt = now;

  return currentSession;
}

// Cancela el temporizador anterior y programa uno nuevo.
function scheduleSessionReset() {
  clearTimeout(idleTimer);

  idleTimer = setTimeout(() => {
    // No limpiar mientras se está procesando una conversación.
    if (busy) {
      scheduleSessionReset();
      return;
    }

    // Eliminar el contexto del visitante actual.
    currentSession = null;
    lastInteractionAt = 0;

    // Limpiar los mensajes visibles.
    $("log").replaceChildren();

    // Volver al estado inicial.
    setState("IDLE");

    console.log(
      "[SESIONES] Conversación finalizada por 3 minutos de inactividad."
    );

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
  if (busy) return;

  // Si comienza una nueva interacción, cancelar el borrado.
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

    fd.append(
      "audio",
      await voice.stop(),
      "voz.webm"
    );

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

    if (result.transcript) {
      say("v", result.transcript);
    }

    say("s", result.reply);

    await speak(result.audio_b64);

  } catch (error) {
    console.error("Error en la conversación:", error);

    setState("DENIED");

    say(
      "s",
      "El servicio no responde. Pedí ayuda en recepción."
    );

  } finally {
    busy = false;
    btn.disabled = false;
    btn.classList.remove("on");

    // Comenzar a contar los 3 minutos desde el final
    // de la última respuesta de Sofía.
    scheduleSessionReset();
  }
});

// Decisión del residente (app móvil) en tiempo real.
const ws = new WebSocket(
  `ws://${location.hostname || "localhost"}:8001/ws/totem`
);

ws.onmessage = event => {
  const message = JSON.parse(event.data);

  if (message.type !== "decision") return;

  setState(
    message.approved ? "GRANTED" : "DENIED"
  );

  say(
    "s",
    message.approved
      ? "¡Bienvenido! Ya podés pasar."
      : "El residente no autorizó el ingreso. Podés pedir ayuda en recepción."
  );

  setTimeout(() => {
    setState("IDLE");
  }, 6000);
};

ws.onerror = error => {
  console.error("Error en la conexión con UniGuard:", error);
};

// Si se recarga la página, no se conserva una sesión anterior.
currentSession = null;
lastInteractionAt = 0;
