
(() => {
  const video = document.getElementById("face-video");
  const panel = document.getElementById("face-panel");

  if (!video || !panel || window.UniGuardFaceComparison) return;
  window.UniGuardFaceComparison = true;

  const API =
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1"
      ? "http://127.0.0.1:8001"
      : "https://arguss-uniguard.onrender.com";

  document.getElementById("face-reference-input")?.remove();
  document.getElementById("face-compare-result")?.remove();
  document.getElementById("face-auto-status")?.remove();

  panel.querySelectorAll(".face-demo-button").forEach(el => el.remove());

  const style = document.createElement("style");
  style.textContent = `
    #face-auto-status {
      margin-top: 12px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--tx);
      font-size: 13px;
      line-height: 1.5;
    }
    #face-auto-status.face-warning { color: #e0b25a; border-color: #e0b25a; }
    #face-auto-status.face-success { color: #55c98a; border-color: #55c98a; }
    #face-auto-status.face-error { color: #e46d6d; border-color: #e46d6d; }
    #face-password-form { display: none; margin-top: 12px; }
    #face-password-form input {
      width: 100%; box-sizing: border-box; padding: 11px;
      margin-bottom: 9px; border: 1px solid var(--border);
      border-radius: 5px; background: #171717; color: white;
    }
    #face-password-form button {
      width: 100%; padding: 11px; border: 1px solid var(--gold);
      border-radius: 5px; background: #252019; color: white;
      cursor: pointer;
    }
    #face-password-form button:disabled { opacity: .6; cursor: wait; }
  `;
  document.head.appendChild(style);

  const status = document.createElement("div");
  status.id = "face-auto-status";
  status.textContent = "Esperando que la cámara esté disponible...";

  const form = document.createElement("form");
  form.id = "face-password-form";

  const password = document.createElement("input");
  password.type = "password";
  password.placeholder = "Ingresá tu contraseña";
  password.autocomplete = "current-password";
  password.required = true;

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Verificar identidad";

  form.append(password, submit);
  panel.append(status, form);

  let scanning = false;
  let verified = false;
  let challengeId = null;
  let lastAttempt = 0;
  let stopped = false;

  function setStatus(message, type = "") {
    status.textContent = message;
    status.className = type;
  }

  function wait(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function captureFrame() {
    return new Promise((resolve, reject) => {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;

      const context = canvas.getContext("2d");

      if (!context || !canvas.width || !canvas.height) {
        reject(new Error("La cámara todavía no está lista."));
        return;
      }

      context.drawImage(video, 0, 0, canvas.width, canvas.height);

      canvas.toBlob(blob => {
        if (blob) resolve(blob);
        else reject(new Error("No se pudo capturar la imagen."));
      }, "image/jpeg", 0.85);
    });
  }

  async function readResponse(response) {
    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(
        typeof result.detail === "string"
          ? result.detail
          : `Error del servidor: ${response.status}`
      );
    }

    return result;
  }

  async function identify() {
    if (scanning || verified || challengeId || stopped) return;

    if (
      !video.srcObject ||
      video.readyState < 2 ||
      !video.videoWidth ||
      !video.videoHeight
    ) {
      setStatus("Esperando la cámara...");
      return;
    }

    scanning = true;

    try {
      const image = await captureFrame();
      const data = new FormData();
      data.append("image", image, "captura.jpg");

      const response = await fetch(`${API}/api/face/identify`, {
        method: "POST",
        body: data
      });

      const result = await readResponse(response);

      if (!result.matched || !result.challenge_id) {
        setStatus(
          "No se reconoció un rostro registrado. Podés volver a intentarlo o solicitar asistencia.",
          "face-warning"
        );
        return;
      }

      challengeId = result.challenge_id;

      setStatus(
        `Hola, ${result.name}. Unidad ${result.unit}. Ingresá tu contraseña para verificar tu identidad.`,
        "face-success"
      );

      form.style.display = "block";
      password.focus();

    } catch (error) {
      console.error("UniGuard - reconocimiento facial:", error);
      setStatus(
        `No se pudo realizar el reconocimiento: ${error.message}`,
        "face-error"
      );
    } finally {
      scanning = false;
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();

    if (!challengeId || verified || submit.disabled) return;

    submit.disabled = true;
    submit.textContent = "Verificando...";

    try {
      const response = await fetch(`${API}/api/face/verify-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          challenge_id: challengeId,
          password: password.value
        })
      });

      const result = await readResponse(response);

      if (!result.resident?.name || !result.resident?.unit) {
        throw new Error("El servidor devolvió datos de residente incompletos.");
      }

      verified = true;
      challengeId = null;
      form.style.display = "none";

      setStatus(
        `Identidad verificada: ${result.resident.name}, unidad ${result.resident.unit}. La puerta no se ha abierto.`,
        "face-success"
      );

    } catch (error) {
      setStatus(error.message, "face-error");

      const message = error.message.toLowerCase();

      if (
        message.includes("venció") ||
        message.includes("expiró") ||
        message.includes("máximo de intentos")
      ) {
        challengeId = null;
        form.style.display = "none";
      }

    } finally {
      password.value = "";
      submit.disabled = false;
      submit.textContent = "Verificar identidad";
    }
  });

  async function start() {
    while (!verified && !stopped) {
      if (Date.now() - lastAttempt >= 3000) {
        lastAttempt = Date.now();
        await identify();
      }

      await wait(1000);
    }
  }

  window.addEventListener("beforeunload", () => {
    stopped = true;
  });

  start();
})();
