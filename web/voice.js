// Explicit microphone state machine. Capture, transcription, and chat are independent.
// Every asynchronous callback is generation-checked so a stopped mic never restarts itself.
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
    this.caps = {};
    this.mode = "browser";
    this.transcript = "";
    this.SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    $("voice-new-tab").href = window.location.href;
    if (!this.SR) {
      $("voice-engine").value = "offline";
      $("voice-engine").options[0].disabled = true;
    }
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
          ? "Offline English recording. Stop, review, then send."
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
    for (const id of ["voice-launch", "sidebar-voice"])
      $(id).addEventListener("click", () => {
        this.open();
        this.start();
      });
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
    $("voice-new-tab").href = window.location.href;
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
    if (
      document.permissionsPolicy?.allowsFeature &&
      !document.permissionsPolicy.allowsFeature("microphone")
    )
      throw new Error(
        "The page embedding this app blocks microphone access. Use “Open in a new tab” below, then allow the microphone there.",
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
      return (
        "Microphone permission was denied or blocked. Allow microphone access in your address bar’s site settings, then try again." +
        (window.top !== window
          ? " This app is embedded: open it in a new tab if the embedding page blocks microphone access."
          : "")
      );
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
            : "Speak clearly, then pause or tap Stop. You’ll review the transcript before sending.",
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
        "Browser recognition could not start. Use offline recording, then review the result.",
      );
      return;
    }
    this.recognition = rec;
    rec.lang = $("voice-language").value;
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
    let hadError = false;
    rec.onresult = (event) => {
      if (epoch !== this.epoch || this.phase !== "listening") return;
      let text = "";
      for (let i = 0; i < event.results.length; i++) text += event.results[i][0].transcript + " ";
      this.transcript = text.trim();
      $("voice-transcript").value = this.transcript;
      this.syncButtons();
      clearTimeout(this.pauseTimer);
      this.pauseTimer = setTimeout(() => {
        if (epoch === this.epoch && this.phase === "listening" && this.transcript.trim())
          this.finishCapture();
      }, 1800);
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
        else if (this.heard)
          this.fallbackToOffline(
            epoch,
            "The browser returned no words. Recording offline instead.",
          );
        else {
          this.cancelCapture();
          this.error(
            "The browser did not hear speech. Check the input meter and microphone selection, then try again.",
          );
        }
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
      else if (this.heard)
        this.fallbackToOffline(
          epoch,
          "The browser stopped before returning a transcript. Recording offline instead.",
        );
      else {
        this.cancelCapture();
        this.error(
          "No speech was recognized. Try again, check the input meter, or use offline recording.",
          true,
        );
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
      message + " Pause or tap Stop when done. Review is always required.",
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
  async finishCapture({ forceReview = false } = {}) {
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
        "Here’s what we heard.",
        "Review or edit your question, then send. Your microphone is off.",
      );
      if ($("voice-auto").checked && !forceReview) this.sendTranscript();
      return;
    }
    if (chunks.length && this.caps.offline) {
      const type = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
      const file = new File(chunks, "solvra-voice." + type, { type: mime });
      await this.transcribeFile(file, epoch);
      return;
    }
    this.error(
      "No words were captured. Your microphone is now off. Try the input test, offline recording, or type your question.",
      true,
    );
  }
  async transcribeFile(file, epoch) {
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
      this.transcript = res.text || "";
      $("voice-transcript").value = this.transcript;
      this.setPhase(
        "review",
        "Check what we heard.",
        `${res.engine || "Offline English"} transcript. It may be inaccurate—edit it before sending. Your microphone is off.`,
      );
    } catch (e) {
      if (epoch === this.epoch)
        this.error(
          e.message || "Could not transcribe that recording. Try again or type your question.",
        );
    }
  }
  async sendTranscript() {
    if (["listening", "testing", "requesting"].includes(this.phase))
      await this.finishCapture({ forceReview: true });
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
    let played = false;
    if ($("voice-read").checked) {
      this.setPhase(
        "speaking",
        "Here’s what the numbers say.",
        "Tap Interrupt & speak to ask a follow-up.",
      );
      played = await this.speak({
        ...response,
        id: response.message_id,
        content: text,
      });
    }
    if (epoch !== this.epoch || !this.voiceSession || !$("voice-dialog").open) return;
    if (played && $("voice-auto").checked && this.phase === "speaking") this.start();
    else
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
  stopAll() {
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
