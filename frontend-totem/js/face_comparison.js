(() => {
    const video = document.getElementById("face-video");
    const panel = document.getElementById("face-panel");

    if (!video || !panel) {
        console.error("UniGuard: no se encontró la cámara o el panel.");
        return;
    }

    // Se puede definir window.UNIGUARD_API_URL antes de cargar este archivo
    // (por ejemplo, la URL del backend en Render). Por defecto, igual que antes.
    const API = window.UNIGUARD_API_URL || "http://127.0.0.1:8001";

    // Evita duplicar el sistema si el archivo se carga nuevamente.
    if (window.UniGuardFaceComparison) return;

    window.UniGuardFaceComparison = true;

    // Elimina los controles de la demostración anterior.
    document.getElementById("face-reference-input")?.remove();
    document.getElementById("face-compare-result")?.remove();

    panel.querySelectorAll(".face-demo-button").forEach(element => {
        element.remove();
    });

    const oldStatus = document.getElementById("face-auto-status");
    oldStatus?.remove();

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

        #face-password-form {
            display: none;
            margin-top: 12px;
        }

        #face-password-form input {
            width: 100%;
            box-sizing: border-box;
            padding: 11px;
            margin-bottom: 9px;
            border: 1px solid var(--border);
            border-radius: 5px;
            background: #171717;
            color: white;
        }

        #face-password-form button {
            width: 100%;
            padding: 11px;
            border: 1px solid var(--gold);
            border-radius: 5px;
            background: #252019;
            color: white;
            cursor: pointer;
        }
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

    function setStatus(message) {
        status.textContent = message;
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

            if (!context) {
                reject(new Error("No se pudo acceder al video."));
                return;
            }

            context.drawImage(
                video,
                0,
                0,
                canvas.width,
                canvas.height
            );

            canvas.toBlob(
                blob => {
                    if (blob) resolve(blob);
                    else reject(new Error("No se pudo capturar la imagen."));
                },
                "image/jpeg",
                0.85
            );
        });
    }

    async function identify() {
        if (scanning || verified || challengeId) return;

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

            const response = await fetch(
                `${API}/api/face/identify`,
                {
                    method: "POST",
                    body: data
                }
            );

            const result = await response.json();

            if (response.status === 422) {
                setStatus("No se pudo detectar un rostro. Mirá hacia la cámara.");
                return;
            }

            if (!response.ok) {
                throw new Error(
                    result.detail || "Error al identificar el rostro."
                );
            }

            if (!result.matched) {
                setStatus(
                    "No encontramos una coincidencia. " +
                    "Podés intentar nuevamente o solicitar asistencia."
                );
                return;
            }

            challengeId = result.challenge_id;

            setStatus(
                `Hola, ${result.name}. Unidad ${result.unit}. ` +
                "Ingresá tu contraseña para verificar tu identidad."
            );

            form.style.display = "block";
            password.focus();

        } catch (error) {
            console.error("UniGuard - reconocimiento facial:", error);
            setStatus(`No se pudo realizar el reconocimiento: ${error.message}`);
        } finally {
            scanning = false;
        }
    }

    form.addEventListener("submit", async event => {
        event.preventDefault();

        if (!challengeId || verified) return;

        submit.disabled = true;
        submit.textContent = "Verificando...";

        try {
            const response = await fetch(
                `${API}/api/face/verify-password`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        challenge_id: challengeId,
                        password: password.value
                    })
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    result.detail || "No se pudo verificar la contraseña."
                );
            }

            verified = true;
            challengeId = null;

            form.style.display = "none";

            setStatus(
                `Identidad verificada: ${result.resident.name}, ` +
                `unidad ${result.resident.unit}. ` +
                "La puerta no se ha abierto."
            );

        } catch (error) {
            setStatus(error.message);

            if (responseIsExpired(error.message)) {
                challengeId = null;
                form.style.display = "none";
            }

        } finally {
            password.value = "";
            submit.disabled = false;
            submit.textContent = "Verificar identidad";
        }
    });

    function responseIsExpired(message) {
        return message.toLowerCase().includes("venció") ||
            message.toLowerCase().includes("máximo de intentos");
    }

    async function start() {
        while (!verified) {
            const now = Date.now();

            if (now - lastAttempt >= 3000) {
                lastAttempt = now;
                await identify();
            }

            await wait(1000);
        }
    }

    start();
})();
