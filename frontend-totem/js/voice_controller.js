
class Voice {
  constructor() {
    this.ctx = null;
    this.an = null;
    this.buf = null;
    this.playing = false;
    this.stream = null;
    this.rec = null;
    this.chunks = [];
    this.source = null;
  }

  async start() {
    if (this.rec?.state === "recording") {
      throw new Error("Ya hay una grabación activa.");
    }

    this.ctx ||= new AudioContext();

    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }

    if (!this.stream) {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
    }

    this.chunks = [];

    const mimeType = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus"
    ].find(type => MediaRecorder.isTypeSupported(type));

    this.rec = mimeType
      ? new MediaRecorder(this.stream, { mimeType })
      : new MediaRecorder(this.stream);

    this.rec.ondataavailable = event => {
      if (event.data?.size > 0) this.chunks.push(event.data);
    };

    this.rec.start();
  }

  stop() {
    return new Promise((resolve, reject) => {
      if (!this.rec || this.rec.state !== "recording") {
        reject(new Error("No hay una grabación activa."));
        return;
      }

      const recorder = this.rec;

      recorder.onstop = () => {
        const audio = new Blob(this.chunks, {
          type: recorder.mimeType || "audio/webm"
        });

        this.chunks = [];
        resolve(audio);
      };

      recorder.onerror = () => {
        reject(new Error("No se pudo completar la grabación."));
      };

      recorder.stop();
    });
  }

  async play(b64) {
    if (!b64) {
      throw new Error("No se recibió audio del servidor.");
    }

    this.ctx ||= new AudioContext();

    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }

    if (!this.an) {
      this.an = this.ctx.createAnalyser();
      this.an.fftSize = 512;
      this.an.connect(this.ctx.destination);
      this.buf = new Uint8Array(this.an.frequencyBinCount);
    }

    this.playing = false;

    try {
      const binary = atob(b64);
      const bytes = Uint8Array.from(
        binary,
        character => character.charCodeAt(0)
      );

      const audioBuffer = await this.ctx.decodeAudioData(bytes.buffer);

      if (this.source) {
        try {
          this.source.stop();
        } catch (_) {}
      }

      const source = this.ctx.createBufferSource();
      this.source = source;
      source.buffer = audioBuffer;
      source.connect(this.an);

      this.playing = true;

      await new Promise((resolve, reject) => {
        source.onended = () => {
          this.playing = false;
          if (this.source === source) this.source = null;
          resolve();
        };

        try {
          source.start(0);
        } catch (error) {
          this.playing = false;
          this.source = null;
          reject(error);
        }
      });

    } catch (error) {
      this.playing = false;
      console.error("Error al reproducir la voz de UniGuard:", error);
      throw error;
    }
  }

  level() {
    if (!this.an || !this.playing) {
      return { amp: 0, centroid: 0.5 };
    }

    this.an.getByteFrequencyData(this.buf);

    let sum = 0;
    let weightedSum = 0;

    for (let i = 0; i < 80; i++) {
      sum += this.buf[i];
      weightedSum += this.buf[i] * i;
    }

    return {
      amp: Math.min(1, sum / 80 / 140),
      centroid: sum > 0
        ? Math.min(1, (weightedSum / sum) / 40)
        : 0.5
    };
  }

  release() {
    if (this.rec?.state === "recording") {
      this.rec.stop();
    }

    if (this.source) {
      try {
        this.source.stop();
      } catch (_) {}
      this.source = null;
    }

    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }

    this.playing = false;
  }
}

window.Voice = Voice;

