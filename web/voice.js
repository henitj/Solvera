// Explicit microphone state machine. Capture, transcription, and chat are independent.
// Every asynchronous callback is generation-checked so a stopped mic never restarts itself.
const FINAL_SPEECH_PAUSE_MS = 1800;

class VoiceController {
  constructor() {
    this.epoch = 0;
    this.phase = "idle";
    this.stream = null;
    this.ctx = null;
    this.recognition = null;
    this.recorder = null;
    this.chunks = [];
    this.interval = null;
    this.pauseTimer = null;
    this.watchdog = null;
    this.player = new SpeechPlayer((text) => {
      if (this.phase === "speaking") $("voice-detail").textContent = text;
    });
    this.awaitingReply = false;
    this.voiceSession = false;
    this.inlineActive = false;
    this.inlineRec = null;
    this.inlinePauseTimer = null;
    this.inlineLimitTimer = null;
    this.inlineRecorder = null;
    this.inlineStream = null;
    this.inlineChunks = [];
    this.inlineShouldSend = false;
    this.inlineGeneration = 0;
    this.inlineSegments = new Map();
    this.inlineText = "";
    this.inlineMeter = null;
    this.inlinePhase = "idle";
    this.inlineSendStarted = false;
    this.browserSegments = new Map();
    this.caps = {};
    this.mode = "browser";
    this.transcript = "";
    this.SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if ($("voice-new-tab")) $("voice-new-tab").href = window.location.href;
    if (!this.SR) {
      $("voice-engine").value = "offline";
      $("voice-engine").options[0].disabled = true;
    }
    $("chat-mic")?.addEventListener("click", () => this.toggleInline());
    $("voice-start").addEventListener("click", () => {
      if (["listening", "testing", "requesting"].includes(this.phase)) this.finishCapture();
      else if (this.phase === "speaking") {
        this.stopSpeaking();
        this.start();
      } else this.start();
    });
    $("voice-use").addEventListener("click", () => this.sendTranscript());
    $("voice-transcript").addEventListener("input", () => {
      this.transcript = $("voice-transcript").value;
      this.syncButtons();
    });
    $("close-voice").addEventListener("click", () => {
      // Release tracks synchronously; the dialog's close event is queued later.
      this.stopAll();
      $("voice-dialog").close();
    });
    $("voice-dialog").addEventListener("close", () => this.stopAll());
    $("voice-dialog").addEventListener("cancel", () => this.stopAll());
    $("voice-engine").addEventListener("change", () => {
      this.cancelCapture();
      this.setPhase(
        "idle",
        "Ready when you are",
        this.selectedMode() === "offline"
          ? "Offline English recording. Pause or stop when done; Solvera will process and send it."
          : "Browser speech recognition with live captions.",
      );
      $("voice-language").disabled = this.selectedMode() === "offline";
    });
    $("voice-device").addEventListener("change", () => {
      this.cancelCapture();
      this.setPhase("idle", "Microphone changed", "Tap Start listening to use the selected input.");
    });
    $("test-mic").addEventListener("click", () => this.start(true));
    $("voice-upload").addEventListener("click", () => $("audio-upload").click());
    $("attach-audio").addEventListener("click", () => {
      this.open();
      $("audio-upload").click();
    });
    $("audio-upload").addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (file) {
        this.open();
        this.cancelCapture();
        await this.transcribeFile(file, ++this.epoch);
      }
    });
    // Asking by voice stays in the composer. The detailed dialog is now reserved
    // for microphone tests, uploads, and read-aloud settings—not the normal flow.
    $("voice-launch")?.addEventListener("click", () => this.toggleInline());
    $("voice-error").addEventListener("click", (e) => {
      if (e.target.closest("[data-voice-offline]")) {
        $("voice-engine").value = "offline";
        this.start();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && ["requesting", "listening", "testing"].includes(this.phase)) {
        this.cancelCapture();
        this.setPhase(
          "idle",
          "Microphone paused",
          "Capture stopped because this page was hidden. Tap Start listening to continue.",
        );
      }
    });
  }
  configure(caps) {
    this.caps = caps || {};
    this.player.configure(this.caps.speech);
    $("voice-engine").options[1].disabled = !this.caps.offline;
    if (!this.SR && !this.caps.offline)
      this.error(
        "This browser has no speech recognition and offline transcription is not installed. You can still type any question.",
      );
  }
  selectedMode() {
    return $("voice-engine").value === "offline" || !this.SR ? "offline" : "browser";
  }
  open(settings = false) {
    if (!state.profile) return;
    if (!$("voice-dialog").open) $("voice-dialog").showModal();
    this.voiceSession = true;
    if ($("voice-new-tab")) $("voice-new-tab").href = window.location.href;
    if (settings) {
      root.querySelector(".voice-settings").open = true;
      $("speech-engine").focus();
    }
    this.syncButtons();
  }
  syncButtons() {
    const capturing = ["listening", "testing", "requesting"].includes(this.phase),
      working = ["stopping", "transcribing", "thinking"].includes(this.phase);
    $("voice-start").disabled = working;
    $("voice-start").innerHTML =
      icon(capturing ? "stop" : this.phase === "speaking" ? "mic" : "mic") +
      `<span id="voice-start-label">${capturing ? "Stop listening" : this.phase === "speaking" ? "Interrupt & speak" : "Start listening"}</span>`;
    $("voice-use").disabled = working || state.busy || !$("voice-transcript").value.trim();
    $("voice-engine").disabled = capturing || working;
    $("voice-device").disabled = capturing || working;
    $("voice-language").disabled = capturing || working || this.selectedMode() === "offline";
    $("test-mic").disabled = capturing || working;
    $("speech-preview").disabled = capturing || working;
  }
  setPhase(phase, title, detail = "") {
    this.phase = phase;
    $("voice-stage").dataset.phase = phase;
    $("voice-status").textContent = title;
    $("voice-detail").textContent = detail;
    this.syncButtons();
  }
  error(message, offerOffline = false) {
    $("voice-error").hidden = false;
    $("voice-error").innerHTML =
      esc(message) +
      (offerOffline && this.caps.offline
        ? '<br><button type="button" data-voice-offline>Switch to offline recording</button>'
        : "");
    this.setPhase(
      "error",
      "Let’s check the microphone",
      "Your transcript is kept. You can edit it, try again, or type in the chat.",
    );
  }
  clearError() {
    $("voice-error").hidden = true;
    $("voice-error").textContent = "";
  }
  async requestStream(epoch) {
    if (!window.isSecureContext)
      throw new Error(
        "Microphone access requires HTTPS or localhost. Open this app using its secure preview link.",
      );
    if (!navigator.mediaDevices?.getUserMedia)
      throw new Error(
        "This browser cannot capture microphone audio here. Try current Chrome, Edge, or Safari, or upload a recording.",
      );
    const device = $("voice-device").value;
    const request = navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...(device ? { deviceId: { exact: device } } : {}),
      },
    });
    request
      .then((stream) => {
        if (epoch !== this.epoch) stream.getTracks().forEach((t) => t.stop());
      })
      .catch(() => {});
    return await timed(request, 22000);
  }
  permissionMessage(e) {
    if (e.name === "NotAllowedError" || e.name === "PermissionDeniedError")
      return "Microphone permission was denied or blocked. Allow microphone access in your browser site settings, then try again.";
    if (e.name === "NotFoundError" || e.name === "DevicesNotFoundError")
      return "No microphone was found. Connect a microphone, choose an input in settings below, and try again.";
    if (e.name === "NotReadableError" || e.name === "TrackStartError")
      return "The microphone could not be opened. Another app may be using it. Close other recording apps, or choose a different microphone.";
    if (e.name === "OverconstrainedError") {
      $("voice-device").value = "";
      return "The selected microphone is no longer available. The input has been reset to the system default. Try again.";
    }
    return (
      e.message || "The microphone could not be started. Try a different input or upload audio."
    );
  }
  async start(testOnly = false) {
    if (!state.profile) return;
    if (state.busy) {
      toast("Wait for the current answer before starting another voice question.");
      return;
    }
    this.cancelCapture();
    this.stopSpeaking();
    this.clearError();
    const epoch = ++this.epoch;
    this.mode = this.selectedMode();
    this.transcript = "";
    this.browserSegments = new Map();
    $("voice-transcript").value = "";
    $("voice-timer").textContent = "00:00";
    this.setPhase(
      "requesting",
      "Waiting for microphone access",
      "Allow microphone access when your browser asks.",
    );
    if (!testOnly && $("voice-read").checked) this.player.unlock();
    // Resume Web Audio while still inside a user action (important on Safari/iOS).
    const AC = window.AudioContext || window.webkitAudioContext;
    let ctx = null;
    try {
      if (AC) {
        ctx = new AC();
        this.ctx = ctx;
        ctx.resume().catch(() => {});
      }
    } catch {
      /* The capture can still work without a visual meter. */
    }
    try {
      const stream = await this.requestStream(epoch);
      if (epoch !== this.epoch) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      this.stream = stream;
      this.started = performance.now();
      this.heard = false;
      this.signalFrames = 0;
      this.lastVoice = 0;
      this.maxLevel = 0;
      this.forceOffline = false;
      this.testOnly = testOnly;
      this.enumerateDevices();
      for (const track of stream.getAudioTracks())
        track.addEventListener(
          "ended",
          () => {
            if (epoch === this.epoch && ["listening", "testing"].includes(this.phase)) {
              this.cancelCapture();
              this.error(
                "The microphone disconnected or access was revoked. Reconnect it and try again.",
              );
            }
          },
          { once: true },
        );
      if (!testOnly) this.beginRecorder(stream);
      this.setPhase(
        testOnly ? "testing" : "listening",
        testOnly
          ? "Testing your microphone…"
          : this.mode === "browser"
            ? "I’m listening. Go ahead."
            : "Recording offline.",
        testOnly
          ? "Speak and watch the bars. Nothing from this test is uploaded."
          : this.mode === "browser"
            ? "Your words appear below. Pause or tap Stop when you’re done."
            : "Speak clearly, then pause or tap Stop. Solvera will process and send one question.",
      );
      this.beginMeter(stream, ctx, epoch, testOnly);
      if (!testOnly && this.mode === "browser") this.beginBrowser(epoch);
      if (!testOnly && this.mode === "offline" && !this.recorder) {
        this.cancelCapture();
        this.error(
          "This browser cannot record audio in a supported format. Use browser recognition or upload an audio recording.",
        );
      }
    } catch (e) {
      if (epoch !== this.epoch) return;
      this.cancelCapture();
      this.error(this.permissionMessage(e));
    }
  }
  async enumerateDevices() {
    try {
      const current = $("voice-device").value;
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter(
        (d) => d.kind === "audioinput",
      );
      $("voice-device").innerHTML =
        '<option value="">System default microphone</option>' +
        devices
          .filter((d) => d.deviceId !== "default")
          .map(
            (d, i) =>
              `<option value="${esc(d.deviceId)}">${esc(d.label || "Microphone " + (i + 1))}</option>`,
          )
          .join("");
      if ([...$("voice-device").options].some((o) => o.value === current))
        $("voice-device").value = current;
    } catch {
      /* Device labels are optional and never block capture. */
    }
  }
  beginRecorder(stream) {
    this.chunks = [];
    this.recorder = null;
    if (!window.MediaRecorder) return;
    try {
      const mime = [
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/ogg;codecs=opus",
        "audio/webm",
      ].find((t) => MediaRecorder.isTypeSupported(t));
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined),
        chunks = this.chunks;
      recorder.ondataavailable = (e) => {
        if (e.data?.size) chunks.push(e.data);
      };
      recorder.onerror = () => {
        if (this.mode === "offline") {
          this.cancelCapture();
          this.error(
            "The audio recorder stopped unexpectedly. Your microphone has been released. Try again or upload a recording.",
          );
        }
      };
      recorder.start(200);
      this.recorder = recorder;
    } catch {
      this.recorder = null;
    }
  }
  beginMeter(stream, ctx, epoch, testOnly) {
    let analyser = null,
      samples = null;
    try {
      if (ctx) {
        const source = ctx.createMediaStreamSource(stream);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser);
        samples = new Float32Array(analyser.fftSize);
      }
    } catch {
      /* Timer and explicit stop still work without Web Audio. */
    }
    const bars = [...$("voice-wave").children];
    let noise = 0.002;
    this.interval = setInterval(() => {
      if (epoch !== this.epoch) return;
      const now = performance.now(),
        elapsed = now - this.started;
      let rms = 0;
      if (analyser) {
        analyser.getFloatTimeDomainData(samples);
        rms = Math.sqrt(samples.reduce((s, v) => s + v * v, 0) / samples.length);
      }
      this.maxLevel = Math.max(this.maxLevel, rms);
      if (elapsed < 400) noise = Math.min(0.009, noise * 0.9 + rms * 0.1);
      const threshold = Math.max(0.006, noise * 2.4);
      if (rms > threshold) {
        this.signalFrames++;
        if (this.signalFrames >= 2) this.heard = true;
        this.lastVoice = now;
      }
      bars.forEach((bar, i) => {
        const envelope = 0.35 + 0.65 * Math.sin(((i + 1) / bars.length) * Math.PI);
        bar.style.height =
          Math.min(
            25,
            4 + rms * 180 * envelope + (rms > 0.005 ? Math.sin(now / 110 + i) * rms * 40 : 0),
          ) + "px";
      });
      const secs = Math.floor(elapsed / 1000);
      $("voice-timer").textContent =
        String(Math.floor(secs / 60)).padStart(2, "0") + ":" + String(secs % 60).padStart(2, "0");
      if (testOnly && elapsed > 6000) {
        const heard = this.heard;
        this.cancelCapture();
        this.setPhase(
          "idle",
          heard ? "Your microphone is receiving sound." : "We didn’t detect much sound.",
          heard
            ? "The bars responded to your input. Tap Start listening to ask a question."
            : "Check your system input level, unmute the microphone, or choose another input below.",
        );
        return;
      }
      if (!testOnly && elapsed > 44000) {
        this.finishCapture();
        return;
      }
      if (
        !testOnly &&
        this.mode === "offline" &&
        this.heard &&
        elapsed > 1400 &&
        now - this.lastVoice > 1500
      ) {
        this.finishCapture();
        return;
      }
      if (!testOnly && elapsed > 14000 && !this.transcript.trim() && this.mode === "browser") {
        if (this.heard && this.caps.offline && this.recorder) {
          this.fallbackToOffline(
            epoch,
            "The browser speech service did not return words. Your microphone works; using offline recording instead.",
          );
          if (now - this.lastVoice > 1000) this.finishCapture();
        } else if (!this.heard) {
          this.cancelCapture();
          this.error(
            "No words or microphone signal were detected. Check that your input is not muted, choose another microphone, or use “Test microphone only” below.",
          );
        } else {
          this.cancelCapture();
          this.error(
            "Your microphone is receiving sound, but browser speech recognition is not responding. Try offline recording or a different browser.",
            true,
          );
        }
        return;
      }
      if (!testOnly && this.mode === "offline" && !this.heard && elapsed > 14000 && analyser) {
        this.cancelCapture();
        this.error(
          "No microphone signal was detected. Check your selected input and system volume, then try the microphone test below.",
        );
      }
    }, 60);
  }
  beginBrowser(epoch) {
    let rec;
    try {
      rec = new this.SR();
    } catch {
      this.fallbackToOffline(
        epoch,
        "Browser recognition could not start. Use offline recording; Solvera will process and send the completed question.",
      );
      return;
    }
    this.recognition = rec;
    this.configureRecognizer(rec);
    let hadError = false;
    rec.onresult = (event) => {
      if (epoch !== this.epoch || this.phase !== "listening") return;
      // Result indexes are stable for a recognition session. Replacing changed
      // entries prevents Chrome/Safari revisions from being appended twice.
      this.updateRecognitionSegments(event, this.browserSegments, true);
      this.transcript = this.cleanVoiceTranscript(
        [...this.browserSegments.values()].join(" "),
      );
      $("voice-transcript").value = this.transcript;
      this.syncButtons();
      clearTimeout(this.pauseTimer);
      this.pauseTimer = setTimeout(() => {
        if (epoch === this.epoch && this.phase === "listening" && this.transcript.trim())
          this.finishCapture();
      }, FINAL_SPEECH_PAUSE_MS);
    };
    rec.onerror = (event) => {
      if (epoch !== this.epoch) return;
      hadError = true;
      clearTimeout(this.pauseTimer);
      if (event.error === "aborted") return;
      if (event.error === "not-allowed") {
        this.cancelCapture();
        this.error(
          "Browser speech recognition was blocked. Check site permissions. If microphone permission is allowed, use offline recording to avoid the browser’s remote speech service.",
          true,
        );
        return;
      }
      if (
        ["network", "service-not-allowed", "language-not-supported", "audio-capture"].includes(
          event.error,
        )
      ) {
        this.fallbackToOffline(
          epoch,
          event.error === "network"
            ? "The browser’s speech service is unreachable. The microphone is working; recording offline instead."
            : "Browser recognition is unavailable. Recording offline instead.",
        );
        return;
      }
      if (event.error === "no-speech") {
        if (this.transcript.trim()) this.finishCapture();
        return;
      }
      this.fallbackToOffline(
        epoch,
        "Browser recognition stopped unexpectedly. You can finish with offline recording.",
      );
    };
    rec.onend = () => {
      if (epoch !== this.epoch || this.phase !== "listening" || hadError || this.mode === "offline")
        return;
      if (this.transcript.trim()) this.finishCapture();
      else {
        try { rec.start(); } catch {}
      }
    };
    try {
      rec.start();
    } catch {
      this.fallbackToOffline(
        epoch,
        "Browser recognition could not start. Recording offline instead.",
      );
    }
  }
  fallbackToOffline(epoch, message) {
    if (epoch !== this.epoch) return;
    if (!this.caps.offline || !this.recorder) {
      this.cancelCapture();
      this.error(
        message + " Offline transcription is not available. You can still type or upload audio.",
      );
      return;
    }
    this.detachRecognition();
    this.mode = "offline";
    this.forceOffline = true;
    $("voice-engine").value = "offline";
    this.clearError();
    this.setPhase(
      "listening",
      "Recording offline.",
      message + " Pause or tap Stop when done. Solvera will process and send the completed question.",
    );
  }
  detachRecognition() {
    const rec = this.recognition;
    this.recognition = null;
    if (rec) {
      rec.onresult = null;
      rec.onerror = null;
      rec.onend = null;
      try {
        rec.abort();
      } catch {}
    }
  }
  releaseResources() {
    clearInterval(this.interval);
    this.interval = null;
    clearTimeout(this.pauseTimer);
    this.pauseTimer = null;
    clearTimeout(this.watchdog);
    this.watchdog = null;
    this.detachRecognition();
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.ctx) {
      try {
        this.ctx.close().catch(() => {});
      } catch {}
      this.ctx = null;
    }
    $("voice-wave")
      .querySelectorAll("i")
      .forEach((b) => (b.style.height = "4px"));
  }
  cancelCapture() {
    this.epoch++;
    if (this.recorder) {
      const r = this.recorder;
      this.recorder = null;
      r.onerror = null;
      try {
        if (r.state !== "inactive") r.stop();
      } catch {}
    }
    this.releaseResources();
    this.syncButtons();
  }
  async finishCapture() {
    if (this.phase === "requesting") {
      this.cancelCapture();
      this.setPhase(
        "idle",
        "Microphone request canceled",
        "If a permission prompt remains open, you may dismiss it.",
      );
      return;
    }
    if (!["listening", "testing"].includes(this.phase)) return;
    const wasTest = this.testOnly;
    const epoch = ++this.epoch;
    this.setPhase("stopping", "Finishing your recording…", "Releasing the microphone.");
    clearInterval(this.interval);
    clearTimeout(this.pauseTimer);
    this.detachRecognition();
    const recorder = this.recorder,
      chunks = this.chunks,
      mime = recorder?.mimeType || "audio/webm";
    this.recorder = null;
    if (recorder && recorder.state !== "inactive") {
      recorder.onerror = null;
      await Promise.race([
        new Promise((resolve) => {
          recorder.addEventListener("stop", resolve, { once: true });
          try {
            recorder.stop();
          } catch {
            resolve();
          }
        }),
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]);
    }
    if (epoch !== this.epoch) return;
    this.releaseResources();
    if (wasTest) {
      this.setPhase(
        "idle",
        this.heard ? "Microphone signal detected." : "Microphone test stopped.",
        "Nothing was uploaded. Tap Start listening to ask a question.",
      );
      return;
    }
    const text = $("voice-transcript").value.trim();
    if (text && !this.forceOffline) {
      this.transcript = text;
      this.setPhase(
        "review",
        "Question ready.",
        "Sending your completed voice question. Your microphone is off.",
      );
      await this.sendTranscript();
      return;
    }
    if (chunks.length && this.caps.offline) {
      const type = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
      const file = new File(chunks, "solvera-voice." + type, { type: mime });
      await this.transcribeFile(file, epoch, { sendWhenReady: true });
      return;
    }
    this.error(
      "No words were captured. Your microphone is now off. Try the input test, offline recording, or type your question.",
      true,
    );
  }
  async transcribeFile(file, epoch, { sendWhenReady = false } = {}) {
    if (file.size > 15 * 1024 * 1024) {
      this.error("Choose an audio recording smaller than 15 MB and shorter than 45 seconds.");
      return;
    }
    if (!this.caps.offline) {
      this.error(
        "Offline transcription is not available on this server. Try browser recognition or type your question.",
      );
      return;
    }
    this.clearError();
    this.setPhase(
      "transcribing",
      "Turning audio into words…",
      "Microphone off. Audio is processed by this app’s offline English engine.",
    );
    try {
      const uploaded = await timed(upload(file), 45000);
      if (epoch !== this.epoch) return;
      const res = unpack(await timed(server.transcribe_clip({ path: uploaded.path }), 90000));
      if (epoch !== this.epoch) return;
      this.transcript = this.cleanVoiceTranscript(res.text);
      $("voice-transcript").value = this.transcript;
      if (!this.transcript) throw new Error("No words were detected. Try again or type your question.");
      this.setPhase(
        "review",
        sendWhenReady ? "Question ready." : "Check what we heard.",
        sendWhenReady
          ? `${res.engine || "Offline English"} finished processing. Sending your voice question now.`
          : `${res.engine || "Offline English"} transcript. You can edit it or tap Send. Your microphone is off.`,
      );
      if (sendWhenReady) await this.sendTranscript();
    } catch (e) {
      if (epoch === this.epoch)
        this.error(
          e.message || "Could not transcribe that recording. Try again or type your question.",
        );
    }
  }
  async sendTranscript() {
    if (["listening", "testing", "requesting"].includes(this.phase)) await this.finishCapture();
    const text = $("voice-transcript").value.trim();
    if (!text || ["transcribing", "thinking"].includes(this.phase) || state.busy) return;
    this.awaitingReply = true;
    this.voiceSession = true;
    this.clearError();
    this.setPhase(
      "thinking",
      "Working through the numbers…",
      "Microphone off. Your question is in the assistant conversation.",
    );
    await sendMessage(text);
    if (state.failed && this.awaitingReply) {
      this.awaitingReply = false;
      this.error(state.failed.error);
    }
  }
  async onReply(response) {
    const text = response.reply;
    if (!this.awaitingReply || !this.voiceSession) return;
    const epoch = this.epoch;
    this.awaitingReply = false;
    let answer = $("voice-answer");
    if (!answer) {
      answer = document.createElement("div");
      answer.id = "voice-answer";
      answer.className = "voice-answer";
      $("voice-dialog").querySelector(".voice-controls").after(answer);
    }
    answer.textContent = text;
    answer.hidden = false;
    if ($("voice-read").checked) {
      this.setPhase(
        "speaking",
        "Here’s what the numbers say.",
        "Tap Interrupt & speak to ask a follow-up.",
      );
      await this.speak({
        ...response,
        id: response.message_id,
        content: text,
      });
    }
    if (epoch !== this.epoch || !this.voiceSession || !$("voice-dialog").open) return;
    this.setPhase(
      "review",
      "Ready for a follow-up?",
      "Your microphone is off. Start listening again, or return to the conversation.",
    );
  }
  stopSpeaking() {
    this.player.stop();
  }
  speak(message, manual = false) {
    if (manual) {
      this.cancelCapture();
      this.voiceSession = false;
    }
    return this.player.play(message);
  }
  clearProfile() {
    this.stopAll();
    this.transcript = "";
    $("voice-transcript").value = "";
    $("voice-answer")?.remove();
    $("audio-upload").value = "";
    this.clearError();
    this.syncButtons();
  }
  recognitionTerms() {
    const profileName = String(state.profile?.name || "").trim();
    return [
      "Solvera",
      "checking account",
      "checking balance",
      "savings account",
      "savings balance",
      "credit card",
      "auto loan",
      "student loan",
      "debt payment",
      "payment plan",
      "upcoming bill",
      "overdue bill",
      "rent",
      "utilities",
      "electricity bill",
      "phone bill",
      "grocery spending",
      "emergency fund",
      "cash flow",
      "interest rate",
      "paycheck",
      "income",
      "budget",
      "financial trouble",
      "Maya Chen",
      "Jordan Reyes",
      "Aisha Patel",
      "Marcus Bennett",
      profileName,
    ].filter(Boolean);
  }
  configureRecognizer(rec) {
    rec.lang = $("voice-language")?.value || "en-US";
    // A completed voice question must never be sent from an interim caption.
    rec.interimResults = false;
    rec.continuous = true;
    // The browser's first alternative is normally preferred. A few alternatives
    // let a close finance-specific match win only when recognition confidence is
    // comparable, instead of replacing spoken words with a low-confidence guess.
    rec.maxAlternatives = 3;
    const Phrase = window.SpeechRecognitionPhrase || window.webkitSpeechRecognitionPhrase;
    if (!Phrase || !("phrases" in rec)) return;
    try {
      // Chromium's optional phrase-bias API improves recognition of product,
      // account, and bill terms without changing audio routing or requiring a
      // third-party speech service. Browsers that do not implement it use their
      // normal recognizer unchanged.
      rec.phrases = [...new Set(this.recognitionTerms())].map(
        (term) => new Phrase(term, term === "Solvera" ? 7 : 5),
      );
    } catch {
      // Phrase bias is experimental; an unsupported implementation must not
      // prevent ordinary browser recognition from starting.
    }
  }
  cleanVoiceTranscript(value) {
    const words = String(value || "")
      .normalize("NFKC")
      .replace(/\s+/g, " ")
      .trim()
      .split(" ")
      .filter(Boolean);
    // Browser recognizers sometimes repeat a finalized phrase in the next result.
    // Collapse only adjacent multi-word copies so emphatic single words stay intact.
    let changed = true;
    while (changed) {
      changed = false;
      const normalized = words.map((word) => word.toLowerCase().replace(/[^a-z0-9']/g, ""));
      outer: for (let size = Math.min(12, Math.floor(words.length / 2)); size >= 2; size--) {
        for (let start = 0; start + size * 2 <= words.length; start++) {
          let same = true;
          for (let offset = 0; offset < size; offset++) {
            if (normalized[start + offset] !== normalized[start + size + offset]) {
              same = false;
              break;
            }
          }
          if (same) {
            words.splice(start + size, size);
            changed = true;
            break outer;
          }
        }
      }
    }
    return words.join(" ").replace(/\s+([,.;!?])/g, "$1").slice(0, 3000);
  }
  bestRecognitionCandidate(result) {
    const financeWords = new Set([
      "checking",
      "savings",
      "balance",
      "bill",
      "bills",
      "rent",
      "utilities",
      "debt",
      "money",
      "spend",
      "spending",
      "pay",
      "paid",
      "payment",
      "budget",
      "income",
      "credit",
      "card",
      "groceries",
      "electricity",
      "phone",
      "afford",
      "loan",
      "cash",
      "flow",
      "interest",
      "paycheck",
      "overdue",
      "emergency",
      "trouble",
    ]);
    const candidates = Array.from(result || [])
      .map((candidate, index) => {
        const transcript = String(candidate?.transcript || "").trim();
        const terms = transcript.toLowerCase().match(/[a-z']+/g) || [];
        const domainHits = terms.filter((term) => financeWords.has(term)).length;
        const confidence = Number.isFinite(candidate?.confidence)
          ? Math.max(0, Math.min(1, candidate.confidence))
          : index === 0
            ? 0.7
            : 0.45;
        return { transcript, index, confidence, domainHits };
      })
      .filter((candidate) => candidate.transcript);
    const leadConfidence = Math.max(...candidates.map((candidate) => candidate.confidence));
    return candidates
      .map((candidate) => {
        // Prefer the recognizer's highest-confidence wording. Finance language
        // breaks ties only for genuinely close alternatives, so a vague
        // low-confidence "balance" guess cannot overwrite what was spoken.
        const closeToLead = leadConfidence - candidate.confidence <= 0.09;
        const financeBoost = closeToLead ? Math.min(candidate.domainHits, 3) * 0.03 : 0;
        return {
          ...candidate,
          score: candidate.confidence + financeBoost - candidate.index * 0.001,
        };
      })
      .sort((a, b) => b.score - a.score)[0]?.transcript;
  }
  updateRecognitionSegments(event, segments, finalOnly = false) {
    if (!event?.results) return;
    const first = Number.isInteger(event.resultIndex) ? event.resultIndex : 0;
    for (let index = first; index < event.results.length; index++) {
      if (finalOnly && !event.results[index].isFinal) continue;
      const candidate = this.bestRecognitionCandidate(event.results[index]);
      if (candidate) segments.set(index, candidate);
    }
    for (const index of [...segments.keys()]) {
      if (index >= event.results.length) segments.delete(index);
    }
  }
  recognitionText(segments) {
    return this.cleanVoiceTranscript(
      [...segments.entries()]
        .sort(([a], [b]) => a - b)
        .map(([, value]) => value)
        .join(" "),
    );
  }
  setInlineStatus(phase = "idle", message = "") {
    this.inlinePhase = phase;
    const panel = $("inline-voice-status");
    const detail = $("inline-voice-status-text");
    if (panel) {
      panel.hidden = !message;
      panel.dataset.phase = phase;
    }
    if (detail) detail.textContent = message;
    const listening = ["requesting", "listening"].includes(phase);
    const mic = $("chat-mic");
    if (mic) {
      mic.classList.toggle("recording", listening);
      mic.setAttribute("aria-label", listening ? "Stop and send voice question" : "Ask Solvera by voice");
      mic.setAttribute("title", listening ? "Listening… tap to finish" : "Ask by voice");
    }
    const launch = $("voice-launch");
    launch?.classList.toggle("recording", listening);
    launch?.setAttribute("aria-pressed", String(listening));
    if ($("voice-launch-label"))
      $("voice-launch-label").textContent = listening ? "Listening… tap to finish" : "Ask by voice";
  }
  resetInlineUI() {
    clearTimeout(this.inlinePauseTimer);
    clearTimeout(this.inlineLimitTimer);
    clearInterval(this.inlineMeter);
    this.inlinePauseTimer = this.inlineLimitTimer = this.inlineMeter = null;
    this.inlineActive = false;
    this.inlineShouldSend = false;
    this.inlineSendStarted = false;
    this.inlineText = "";
    this.inlineSegments = new Map();
    this.setInlineStatus();
    const input = $("chat-input");
    if (input) input.placeholder = "Ask anything about your money…";
  }
  detachInlineRecognition() {
    const rec = this.inlineRec;
    this.inlineRec = null;
    if (!rec) return;
    rec.onresult = rec.onerror = rec.onend = null;
    try {
      rec.abort();
    } catch {
      /* The browser may have already ended this recognizer. */
    }
  }
  toggleInline() {
    if (this.inlinePhase === "transcribing") {
      // Abort a pending local upload/transcript before another capture begins.
      ++this.inlineGeneration;
      this.stopInline(false);
    } else if (this.inlineActive) this.stopInline(true);
    else this.startInline();
  }
  async startInline() {
    if (!state.profile) return;
    if (state.busy) {
      toast("Wait for the current answer before asking another question.");
      return;
    }
    this.stopInline(false);
    this.stopSpeaking();
    this.inlineActive = true;
    this.inlineShouldSend = false;
    this.inlineSendStarted = false;
    this.inlineText = "";
    this.inlineSegments = new Map();
    this.inlineChunks = [];
    // Keep any typed draft intact until a complete voice question is ready.
    const generation = ++this.inlineGeneration;
    const input = $("chat-input");
    if (input) input.placeholder = "Listening… speak your question now";
    this.setInlineStatus("requesting", "Listening… speak naturally. Tap the microphone when you’re done.");
    this.inlineLimitTimer = setTimeout(() => {
      if (this.inlineActive && generation === this.inlineGeneration) {
        toast("Voice capture reached 45 seconds; finishing what we heard.");
        this.stopInline(true);
      }
    }, 45000);

    if (this.SR && this.selectedMode() === "browser") {
      this.beginInlineBrowser(generation);
      return;
    }
    this.beginInlineRecorder(generation);
  }
  beginInlineBrowser(generation) {
    try {
      const rec = new this.SR();
      this.inlineRec = rec;
      this.configureRecognizer(rec);
      rec.onresult = (event) => {
        if (!this.inlineActive || generation !== this.inlineGeneration) return;
        // Ignore an unexpected interim result even if a browser disregards the
        // interimResults setting: only a completed utterance may be sent.
        this.updateRecognitionSegments(event, this.inlineSegments, true);
        const text = this.recognitionText(this.inlineSegments);
        if (!text) return;
        this.inlineText = text;
        this.setInlineStatus("listening", "Heard you. Finishing your question…");
        clearTimeout(this.inlinePauseTimer);
        this.inlinePauseTimer = setTimeout(() => {
          if (this.inlineActive && generation === this.inlineGeneration && this.inlineText) {
            this.stopInline(true);
          }
        }, FINAL_SPEECH_PAUSE_MS);
      };
      rec.onerror = (event) => {
        if (generation !== this.inlineGeneration || !this.inlineActive || event.error === "aborted") return;
        if (["network", "service-not-allowed", "audio-capture", "language-not-supported"].includes(event.error)) {
          this.detachInlineRecognition();
          if (this.caps.offline) {
            this.setInlineStatus("requesting", "Browser recognition is unavailable. Recording a local transcript…");
            this.beginInlineRecorder(generation);
          } else {
            this.stopInline(false);
            toast("Speech recognition is unavailable. Try typing your question.", true);
          }
          return;
        }
        const message =
          event.error === "not-allowed"
            ? "Microphone or speech recognition permission was denied. Check this site’s permissions."
            : "Speech recognition stopped. Try the microphone again or type your question.";
        this.stopInline(false);
        toast(message, true);
      };
      rec.onend = () => {
        if (generation !== this.inlineGeneration || !this.inlineActive) return;
        if (this.inlineText) this.stopInline(true);
        else {
          this.stopInline(false);
          toast("No clear words were detected. Try again or type your question.", true);
        }
      };
      rec.start();
      this.setInlineStatus("listening", "Listening… speak naturally. Tap the microphone when you’re done.");
    } catch {
      this.inlineRec = null;
      this.beginInlineRecorder(generation);
    }
  }
  beginInlineMeter(stream, generation) {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    let context, analyser, samples;
    try {
      context = new Context();
      const source = context.createMediaStreamSource(stream);
      analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      samples = new Float32Array(analyser.fftSize);
    } catch {
      context?.close?.().catch(() => {});
      return;
    }
    let noise = 0.002;
    let heard = false;
    let lastVoice = performance.now();
    const started = performance.now();
    this.inlineMeter = setInterval(() => {
      if (!this.inlineActive || generation !== this.inlineGeneration) return;
      analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
      if (performance.now() - started < 400) noise = Math.min(0.009, noise * 0.9 + rms * 0.1);
      if (rms > Math.max(0.006, noise * 2.4)) {
        heard = true;
        lastVoice = performance.now();
      }
      if (heard && performance.now() - started > 1400 && performance.now() - lastVoice > 1400)
        this.stopInline(true);
    }, 70);
    // Closing the tracks is enough to release the source; close the lightweight
    // meter context once capture has ended instead of retaining it in the session.
    stream.getTracks()[0]?.addEventListener("ended", () => context.close().catch(() => {}), {
      once: true,
    });
  }
  async beginInlineRecorder(generation) {
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
        throw new Error("Microphone access requires a secure page and a supported browser.");
      if (!window.MediaRecorder) throw new Error("Audio recording is not supported by this browser.");
      const device = $("voice-device")?.value;
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(device ? { deviceId: { exact: device } } : {}),
        },
      });
      if (!this.inlineActive || generation !== this.inlineGeneration) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      this.inlineStream = stream;
      this.inlineChunks = [];
      const mime = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus", "audio/webm"].find(
        (type) => MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      this.inlineRecorder = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data?.size) this.inlineChunks.push(event.data);
      };
      recorder.onerror = () => {
        if (generation === this.inlineGeneration) {
          this.stopInline(false);
          toast("Audio recording failed. Try again or type your question.", true);
        }
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        if (this.inlineStream === stream) this.inlineStream = null;
        if (this.inlineRecorder === recorder) this.inlineRecorder = null;
        // A new capture can start before an old recorder dispatches its stop
        // event. That stale event must release only its own stream, never reset
        // the newer capture's controls or transcript.
        if (generation !== this.inlineGeneration) return;
        if (!this.inlineShouldSend) {
          this.resetInlineUI();
          return;
        }
        if (!this.caps.offline) {
          this.resetInlineUI();
          toast("Offline transcription is unavailable. Choose browser recognition or type your question.", true);
          return;
        }
        try {
          this.setInlineStatus("transcribing", "Checking your words…");
          const type = mime?.includes("mp4") ? "m4a" : mime?.includes("ogg") ? "ogg" : "webm";
          const file = new File(this.inlineChunks, "inline-voice." + type, {
            type: mime || "audio/webm",
          });
          if (!file.size || file.size > 15 * 1024 * 1024)
            throw new Error("The recording is empty or too large. Please try a shorter question.");
          const uploaded = await timed(upload(file), 45000);
          if (generation !== this.inlineGeneration || !state.profile) return;
          const res = unpack(await timed(server.transcribe_clip({ path: uploaded.path }), 90000));
          if (generation !== this.inlineGeneration || !state.profile) return;
          const text = this.cleanVoiceTranscript(res.text);
          if (!text) throw new Error("No words were detected. Try again or type your question.");
          // A spoken question remains one flow even when recognition falls back
          // locally: process the completed audio, then send exactly one turn.
          await this.sendInlineText(text, generation);
        } catch (error) {
          if (generation === this.inlineGeneration) {
            this.resetInlineUI();
            toast(error.message || "Could not transcribe audio.", true);
          }
        }
      };
      recorder.start(200);
      this.beginInlineMeter(stream, generation);
      this.setInlineStatus("listening", "Listening locally… pause when you’re done.");
    } catch (error) {
      if (generation === this.inlineGeneration) {
        this.stopInline(false);
        toast("Microphone could not start: " + (error.message || "permission denied"), true);
      }
    }
  }
  async sendInlineText(text, generation) {
    text = this.cleanVoiceTranscript(text);
    if (
      !text ||
      this.inlineSendStarted ||
      generation !== this.inlineGeneration ||
      state.busy ||
      !state.profile
    )
      return;
    this.inlineSendStarted = true;
    this.inlineActive = false;
    this.inlineShouldSend = false;
    this.setInlineStatus("thinking", "Sending your question…");
    await sendMessage(text);
    if (generation === this.inlineGeneration) this.resetInlineUI();
  }
  stopInline(send = true) {
    clearTimeout(this.inlinePauseTimer);
    clearTimeout(this.inlineLimitTimer);
    clearInterval(this.inlineMeter);
    this.inlinePauseTimer = this.inlineLimitTimer = this.inlineMeter = null;
    const text = this.inlineText;
    this.inlineActive = false;
    this.inlineShouldSend = send;
    this.detachInlineRecognition();
    const recorder = this.inlineRecorder;
    if (recorder && recorder.state !== "inactive") {
      this.setInlineStatus(send ? "transcribing" : "idle", send ? "Checking your words…" : "");
      try {
        recorder.stop();
      } catch {
        /* Its stop callback will either finish transcription or release the stream. */
      }
      return;
    }
    if (this.inlineStream) {
      this.inlineStream.getTracks().forEach((track) => track.stop());
      this.inlineStream = null;
    }
    if (send && text) {
      void this.sendInlineText(text, this.inlineGeneration);
      return;
    }
    this.resetInlineUI();
  }
  stopAll() {
    this.stopInline(false);
    this.inlineGeneration++;
    this.cancelCapture();
    this.player.stop(true);
    this.voiceSession = false;
    this.awaitingReply = false;
    this.setPhase(
      "idle",
      "Ready when you are",
      "Microphone off. Tap Start listening when you’re ready.",
    );
  }
}
voice = new VoiceController();
const cleanup = () => {
  voice.stopAll();
  voice.player.dispose();
  financeAI?.dispose();
  window.removeEventListener("keydown", shortcuts);
};
window.addEventListener("pagehide", cleanup, { once: true });
const unmountObserver = new MutationObserver(() => {
  if (!root.isConnected) {
    cleanup();
    unmountObserver.disconnect();
  }
});
unmountObserver.observe(document.body, { childList: true, subtree: true });
bootstrap();
