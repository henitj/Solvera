// One playback owner for neural audio, device fallback, previews, and interruption.
class SpeechPlayer {
  constructor(onStatus) {
    this.token = 0;
    this.active = false;
    this.context = null;
    this.source = null;
    this.resolve = null;
    this.onStatus = onStatus;
    for (const id of ["speech-engine", "speech-rate", "voice-read"]) {
      const saved = storeGet("solvra." + id);
      if (saved)
        $(id).type === "checkbox" ? ($(id).checked = saved === "true") : ($(id).value = saved);
      $(id).addEventListener("change", () => {
        this.stop();
        storeSet("solvra." + id, $(id).type === "checkbox" ? String($(id).checked) : $(id).value);
        this.refreshVoices();
      });
    }
    $("speech-voice").addEventListener("change", () => {
      this.stop();
      storeSet("solvra.voice." + $("speech-engine").value, $("speech-voice").value);
    });
    $("speech-preview").addEventListener("click", () =>
      this.active ? this.stop() : this.play(this.caps?.preview),
    );
    $("speech-stop").addEventListener("click", () => this.stop());
    this.voicesChanged = () => this.refreshVoices();
    window.speechSynthesis?.addEventListener?.("voiceschanged", this.voicesChanged);
  }
  configure(caps = {}) {
    this.caps = caps;
    $("speech-preview").disabled = false;
    this.refreshVoices();
  }
  status(text) {
    $("speech-status").textContent = text;
    this.onStatus?.(text);
  }
  refreshVoices() {
    const neural = $("speech-engine").value === "neural";
    this.deviceVoices = [...(window.speechSynthesis?.getVoices() || [])]
      .filter((v) => /^en[-_]/i.test(v.lang))
      .sort((a, b) => this.voiceScore(b) - this.voiceScore(a));
    const choices = neural
      ? this.caps?.voices || []
      : this.deviceVoices.map((v) => ({
          id: v.voiceURI || v.name,
          label: v.name,
        }));
    const selected =
      storeGet("solvra.voice." + $("speech-engine").value) || $("speech-voice").value;
    $("speech-voice").innerHTML = choices
      .map((v) => `<option value="${esc(v.id)}">${esc(v.label)}</option>`)
      .join("");
    if (choices.some((v) => v.id === selected)) $("speech-voice").value = selected;
    $("speech-voice").disabled = !choices.length;
    $("speech-engine-detail").textContent = neural
      ? "Natural neural speech, generated on this app’s server."
      : "Uses your browser/OS voice. Its provider may process speech.";
    if (!this.active)
      this.status(
        neural
          ? this.caps?.ready
            ? "Natural neural voice · ready on this server."
            : "Natural voice downloads about 90 MB once. Reply text never goes to a speech provider."
          : choices.length
            ? "Device fallback · quality depends on your installed voices."
            : "Waiting for device voices. Natural voice does not need a system voice.",
      );
  }
  voiceScore(voice) {
    return (
      (/neural|natural|enhanced|premium|online|google|samantha/i.test(voice.name) ? 100 : 0) +
      (voice.lang === $("voice-language").value ? 10 : 0) -
      (/espeak|festival|mbrola|compact/i.test(voice.name) ? 100 : 0)
    );
  }
  unlock() {
    try {
      if ($("speech-engine").value === "neural") {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (Context && (!this.context || this.context.state === "closed"))
          this.context = new Context();
        this.context?.resume().catch(() => {});
      } else if (window.speechSynthesis && !this.active) {
        const silent = new SpeechSynthesisUtterance(" ");
        silent.volume = 0;
        speechSynthesis.speak(silent);
      }
    } catch {
      /* Audio playback must never block microphone capture or chat. */
    }
  }
  mark(active, message = {}) {
    this.active = active;
    this.messageId = active ? message.id : null;
    $("speech-stop").disabled = !active;
    $("speech-preview").textContent = active && message.preview ? "Stop preview" : "Preview voice";
    root.querySelectorAll("[data-read-message]").forEach((button) => {
      const selected =
        active &&
        state.messages[Number(button.dataset.readMessage)]?.id === message.id &&
        !!message.id;
      button.setAttribute("aria-pressed", String(selected));
      button.setAttribute("aria-label", selected ? "Stop reading answer" : "Read answer aloud");
    });
  }
  stop(release = false) {
    if (this.active) this.status("Audio stopped. Your written answer is still here.");
    ++this.token;
    window.speechSynthesis?.cancel();
    try {
      this.source?.stop();
    } catch {
      /* Already ended. */
    }
    this.source = null;
    this.resolve?.();
    this.resolve = null;
    this.mark(false);
    if (release) {
      this.context?.close().catch(() => {});
      this.context = null;
    }
  }
  async play(message) {
    if (!message) return false;
    if (this.active && this.messageId && this.messageId === message.id) {
      this.stop();
      return false;
    }
    this.stop();
    this.unlock(); // Unlock while still in the click, not after synthesis finishes.
    const session = state.session;
    const token = this.token,
      neural = $("speech-engine").value === "neural";
    const voiceId = $("speech-voice").value,
      speed = Number($("speech-rate").value);
    const passages = message.speech_chunks || [message.speech || message.content || ""];
    this.mark(true, message);
    const request = (index) =>
      timed(
        server.workspace_action({
          op: "speech",
          session,
          preview: !!message.preview,
          message_id: message.id,
          index,
          voice: voiceId,
          speed,
        }),
        180000,
      )
        .then(unpack)
        .catch((error) => ({ failed: error }));
    try {
      if (neural && !this.context)
        throw new Error("Audio playback is not supported in this browser.");
      if (!neural && !this.deviceVoices.length) {
        await new Promise((resolve) => setTimeout(resolve, 900));
        this.refreshVoices();
      }
      if (token !== this.token) return false;
      const device = this.deviceVoices.find(
        (v) => (v.voiceURI || v.name) === $("speech-voice").value,
      );
      if (!neural && !device)
        throw new Error("No English device voice is installed. Choose Natural voice instead.");
      this.status(
        neural
          ? "Preparing your natural voice. The first use can take a minute…"
          : "Reading with your selected device voice.",
      );
      let pending = neural ? request(0) : null;
      for (let i = 0; i < passages.length && token === this.token; i++) {
        if (neural) {
          const clip = await pending;
          if (token !== this.token) return false;
          if (clip.failed) throw clip.failed;
          // Generate just one passage ahead while the current passage plays.
          pending = i + 1 < passages.length ? request(i + 1) : null;
          this.status(
            `${clip.engine} · ${i + 1} of ${passages.length}. Stop or interrupt at any time.`,
          );
          await this.playAudio(clip.audio, token);
        } else await this.playDevice(passages[i], device, speed, token);
      }
      if (token !== this.token) return false;
      this.status(neural ? "Natural neural voice · finished." : "Device voice · finished.");
      return true;
    } catch (error) {
      if (token === this.token) {
        const message = error.message || "Audio playback failed.";
        this.status(message);
        toast(message + (neural ? " Try Device voice in microphone & voice settings." : ""), true);
      }
      return false;
    } finally {
      if (token === this.token) this.mark(false);
    }
  }
  async playAudio(encoded, token) {
    const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
    const buffer = await this.context.decodeAudioData(bytes.buffer);
    if (token !== this.token) return;
    await this.context.resume();
    if (token !== this.token) return;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    this.source = source;
    await new Promise((resolve) => {
      this.resolve = resolve;
      source.onended = () => {
        if (this.resolve === resolve) this.resolve = null;
        resolve();
      };
      source.start();
    });
    if (this.source === source) this.source = null;
    source.disconnect();
  }
  playDevice(text, voice, rate, token) {
    return new Promise((resolve, reject) => {
      if (token !== this.token) return resolve();
      const utterance = new SpeechSynthesisUtterance(text);
      Object.assign(utterance, {
        voice,
        lang: voice.lang,
        rate,
        pitch: 1,
        volume: 1,
      });
      const finish = (error) => {
        clearTimeout(guard);
        if (this.resolve === finish) this.resolve = null;
        error ? reject(error) : resolve();
      };
      const guard = setTimeout(
        () => finish(new Error("Device speech stopped responding. Try Natural voice.")),
        Math.max(12000, text.length * 120),
      );
      this.resolve = finish;
      utterance.onend = () => finish();
      utterance.onerror = (event) =>
        finish(token === this.token ? new Error(`Device speech failed (${event.error}).`) : null);
      try {
        speechSynthesis.speak(utterance);
      } catch (error) {
        finish(error);
      }
    });
  }
  dispose() {
    this.stop(true);
    window.speechSynthesis?.removeEventListener?.("voiceschanged", this.voicesChanged);
  }
}
