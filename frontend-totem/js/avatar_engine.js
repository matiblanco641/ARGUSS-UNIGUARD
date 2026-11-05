/* UniGuard avatar: animación facial sutil para receptionist.jpg (521x587).
   Mantiene la voz y el resto del proyecto sin cambios. */

const CFG = {
  image: "assets/receptionist.jpg",
  mouth: { x: 258, y: 176, w: 48, h: 17 },
  eyes: [{ x: 226, y: 126 }, { x: 282, y: 125 }],
  eyeW: 27,
  eyeH: 8,
  skin: "#e5b9a8",
  lip: "#b85e68"
};

const STATES = {
  IDLE: { smile: 0.12, gaze: 0 },
  LISTENING: { smile: 0.10, gaze: -0.4 },
  THINKING: { smile: 0.02, gaze: 1.4 },
  SPEAKING: { smile: 0.08, gaze: 0 },
  GRANTED: { smile: 0.22, gaze: 0 },
  DENIED: { smile: -0.08, gaze: 0 }
};

class Avatar {
  constructor(canvas) {
    this.c = canvas;
    this.x = canvas.getContext("2d");
    this.state = "IDLE";
    this.cur = { ...STATES.IDLE };
    this.mouth = { open: 0, wide: 0.5 };
    this.level = { amp: 0, centroid: 0.5 };
    this.blink = 0;
    this.blinking = 0;
    this.nextBlink = performance.now() + 1800;
    this.t0 = performance.now();
    this.ok = false;

    this.img = new Image();

    this.img.onload = () => {
      this.c.width = this.img.naturalWidth || 521;
      this.c.height = this.img.naturalHeight || 587;
      this.ok = true;
    };

    this.img.onerror = () => {
      console.error("No se pudo cargar el avatar:", CFG.image);
    };

    this.img.src = CFG.image;

    requestAnimationFrame(t => this.frame(t));
  }

  setState(state) {
    if (STATES[state]) {
      this.state = state;
    }
  }

  setLevel(level) {
    if (!level) return;

    this.level = {
      amp: Number.isFinite(level.amp)
        ? Math.max(0, level.amp)
        : 0,

      centroid: Number.isFinite(level.centroid)
        ? level.centroid
        : 0.5
    };
  }

  frame(t) {
    const target = STATES[this.state] || STATES.IDLE;
    const elapsed = (t - this.t0) / 1000;

    // Transiciones suaves entre expresiones.
    for (const key of ["smile", "gaze"]) {
      this.cur[key] +=
        (target[key] - this.cur[key]) * 0.08;
    }

    // Parpadeos ocasionales.
    if (t > this.nextBlink && !this.blinking) {
      this.blinking = t;
    }

    if (this.blinking) {
      const p = (t - this.blinking) / 145;

      this.blink = p < 1
        ? Math.sin(p * Math.PI)
        : 0;

      if (p >= 1) {
        this.blinking = 0;
        this.nextBlink =
          t + 2300 + Math.random() * 3000;
      }
    }

    // Apertura progresiva de la boca al hablar.
    const speaking = this.state === "SPEAKING";
    const amp = Math.min(1, this.level.amp || 0);

    const targetOpen = speaking
      ? Math.min(0.48, amp * 1.05)
      : 0;

    this.mouth.open +=
      (targetOpen - this.mouth.open) *
      (speaking ? 0.22 : 0.16);

    // Ajuste sutil del ancho de la boca según la voz.
    const targetWide = speaking
      ? Math.max(
        0.42,
        Math.min(0.62, this.level.centroid || 0.5)
      )
      : 0.5;

    this.mouth.wide +=
      (targetWide - this.mouth.wide) * 0.10;

    this.draw(elapsed);

    requestAnimationFrame(next => this.frame(next));
  }

  draw(elapsed) {
    const ctx = this.x;
    const w = this.c.width;
    const h = this.c.height;

    ctx.clearRect(0, 0, w, h);

    if (this.ok) {
      // Movimiento muy leve del avatar completo.
      // Se amplía un poco la foto para evitar bordes vacíos.
      const angle = Math.sin(elapsed * 0.72) * 0.0028;
      const dx = Math.sin(elapsed * 0.55) * 0.7;
      const dy = Math.sin(elapsed * 1.05) * 0.45;

      ctx.save();
      ctx.translate(w / 2 + dx, h / 2 + dy);
      ctx.rotate(angle);
      ctx.scale(1.012, 1.012);

      ctx.drawImage(
        this.img,
        -w / 2,
        -h / 2,
        w,
        h
      );

      ctx.restore();

      // Parpadeo discreto sobre los ojos.
      if (this.blink > 0.02) {
        for (const eye of CFG.eyes) {
          ctx.save();
          ctx.fillStyle = CFG.skin;

          ctx.beginPath();
          ctx.ellipse(
            eye.x,
            eye.y - CFG.eyeH * 0.45,
            CFG.eyeW / 2,
            Math.max(
              0.7,
              this.blink * CFG.eyeH * 0.75
            ),
            0,
            0,
            Math.PI * 2
          );

          ctx.fill();
          ctx.restore();
        }
      }

      this.drawMouth(ctx);
    } else {
      ctx.fillStyle = "#12161f";
      ctx.fillRect(0, 0, w, h);
    }
  }

  drawMouth(ctx) {
    const { x, y, w, h } = CFG.mouth;
    const open = this.mouth.open;
    const smile = this.cur.smile;

    const mouthW = w * (0.96 + this.mouth.wide * 0.08);
    const opening = Math.max(1.1, h * open * 0.72);
    const cornerY = y + smile * -1.4;

    ctx.save();

    ctx.beginPath();
    ctx.moveTo(
      x - mouthW / 2,
      cornerY
    );

    ctx.quadraticCurveTo(
      x,
      y - opening * 0.35 - smile,
      x + mouthW / 2,
      cornerY
    );

    ctx.quadraticCurveTo(
      x,
      y + opening * 0.65 + smile,
      x - mouthW / 2,
      cornerY
    );

    ctx.closePath();

    // Boca oscura al hablar y labios al cerrarse.
    ctx.fillStyle = open > 0.10
      ? "#642d38"
      : CFG.lip;

    ctx.fill();

    // Borde fino, sin dientes blancos artificiales.
    ctx.strokeStyle = CFG.lip;
    ctx.lineWidth = 1.15;
    ctx.lineJoin = "round";
    ctx.stroke();

    ctx.restore();
  }
}

window.Avatar = Avatar;