
(() => {
    const video = document.getElementById("face-video");
    const panel = document.getElementById("face-panel");

    if (!video || !panel) {
        console.error("UniGuard: no se encontró el panel o la cámara.");
        return;
    }

    const style = document.createElement("style");
    style.textContent = `
        #face-reference-input {
            display: none;
        }

        .face-demo-button {
            width: 100%;
            margin-top: 9px;
            padding: 10px;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: #252019;
            color: var(--tx);
            cursor: pointer;
            font-size: 12px;
        }

        .face-demo-button:hover {
            border-color: var(--gold);
        }

        #face-compare-result {
            margin-top: 10px;
            font-size: 12px;
            line-height: 1.5;
            color: var(--mut);
        }
    `;
    document.head.appendChild(style);

    const fileInput = document.createElement("input");
    fileInput.id = "face-reference-input";
    fileInput.type = "file";
    fileInput.accept = "image/jpeg,image/png,image/webp";

    const selectButton = document.createElement("button");
    selectButton.className = "face-demo-button";
    selectButton.type = "button";
    selectButton.textContent = "Seleccionar foto de referencia";

    const compareButton = document.createElement("button");
    compareButton.className = "face-demo-button";
    compareButton.type = "button";
    compareButton.textContent = "Comparar con la cámara";
    compareButton.disabled = true;

    const result = document.createElement("div");
    result.id = "face-compare-result";
    result.textContent = "Seleccioná una foto para comenzar.";

    panel.append(
        fileInput,
        selectButton,
        compareButton,
        result
    );

    let referenceFile = null;
    let comparing = false;

    selectButton.addEventListener("click", () => {
        fileInput.click();
    });

    fileInput.addEventListener("change", () => {
        const file = fileInput.files?.[0];

        if (!file) return;

        const allowedTypes = [
            "image/jpeg",
            "image/png",
            "image/webp"
        ];

        if (!allowedTypes.includes(file.type)) {
            result.textContent = "Formato no válido. Elegí JPG, PNG o WEBP.";
            referenceFile = null;
            compareButton.disabled = true;
            return;
        }

        if (file.size > 5 * 1024 * 1024) {
            result.textContent = "La foto supera el límite de 5 MB.";
            referenceFile = null;
            compareButton.disabled = true;
            return;
        }

        referenceFile = file;
        compareButton.disabled = false;
        result.textContent = `Foto seleccionada: ${file.name}`;
    });

    compareButton.addEventListener("click", async () => {
        if (comparing) return;

        if (!referenceFile) {
            result.textContent = "Primero seleccioná una foto.";
            return;
        }

        if (
            !video.srcObject ||
            video.readyState < 2 ||
            !video.videoWidth ||
            !video.videoHeight
        ) {
            result.textContent = "La cámara todavía no está disponible.";
            return;
        }

        comparing = true;
        compareButton.disabled = true;
        result.textContent = "Capturando imagen y comparando...";

        try {
            const canvas = document.createElement("canvas");
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;

            const context = canvas.getContext("2d");
            context.drawImage(video, 0, 0, canvas.width, canvas.height);

            const cameraBlob = await new Promise((resolve, reject) => {
                canvas.toBlob(
                    blob => {
                        if (blob) resolve(blob);
                        else reject(new Error("No se pudo capturar la cámara."));
                    },
                    "image/jpeg",
                    0.90
                );
            });

            const formData = new FormData();
            formData.append("image_a", referenceFile, referenceFile.name);
            formData.append("image_b", cameraBlob, "captura-camara.jpg");

            const response = await fetch(
                "http://127.0.0.1:8001/api/face/compare",
                {
                    method: "POST",
                    body: formData
                }
            );

            const data = await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail || "No se pudo realizar la comparación."
                );
            }

            result.textContent =
                `Comparación completada. Similitud: ${data.similarity.toFixed(4)}. ` +
                "Este resultado es solo demostrativo y no autoriza el acceso.";

        } catch (error) {
            console.error("Error en comparación facial:", error);
            result.textContent = `Error: ${error.message}`;
        } finally {
            comparing = false;
            compareButton.disabled = !referenceFile;
        }
    });
})();
