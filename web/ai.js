// Puter owns authentication and inference; Python owns financial facts and every mutation.
class FinanceAI {
  constructor() {
    this.enabled = false;
    this.connecting = false;
    this.error = "";
    this.phase = "";
    this.epoch = 0;
    this.controller = null;
    root.addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "ai-settings") this.open();
      if (action === "ai-connect") this.connect();
      if (action === "ai-disconnect") this.disconnect();
    });
    root.addEventListener("change", (event) => {
      if (event.target.id === "ai-consent") this.syncUI();
    });
    this.syncUI();
  }
  restore() {
    if (
      !state.profile ||
      storeGet("solvra.ai-consent.v1") !== "yes" ||
      storeGet("solvra.ai-profile.v1") !== state.profile.id
    )
      return;
    try {
      this.sdk = loadPuterSDK();
      this.enabled = this.sdk.auth.isSignedIn();
    } catch {
      this.error = "Puter could not restore its sign-in. Connect again to use Grok.";
    }
    this.syncUI();
  }
  resetProfile() {
    this.dispose();
    this.enabled = false;
    this.connecting = false;
    this.error = "";
    this.phase = "";
    storeSet("solvra.ai-consent.v1", "no");
    storeSet("solvra.ai-profile.v1", "");
    this.syncUI();
  }
  syncUI() {
    $("ai-status-button").dataset.connected = String(this.enabled);
    $("ai-status-label").textContent = this.connecting
      ? "Connecting to Puter…"
      : this.enabled
        ? this.error
          ? "Grok needs attention"
          : "Grok AI connected"
        : "Connect Grok AI";
    $("ai-status-detail").textContent =
      this.phase ||
      (this.enabled ? "Finance-only · read-only guidance" : "Local calculations until connected");
    const button = $("ai-connect");
    if (button) {
      button.disabled = this.connecting || state.busy || !$("ai-consent")?.checked;
      button.textContent = this.connecting ? "Complete Puter sign-in…" : "Connect with Puter";
    }
    if ($("ai-connection-status")) {
      $("ai-connection-status").textContent =
        this.error ||
        (this.enabled
          ? "Connected. New finance questions can use Grok; recordings and ledger changes keep their existing safeguards."
          : "Not connected. The local finance engine is still available.");
    }
  }
  open() {
    if (!state.profile) return;
    openDialog(
      "Smarter guidance. Your control.",
      `<div class="dialog-copy"><p><b>Grok via Puter</b> helps with budgeting, saving, debt strategies, credit, investing, retirement, tax education, and financial follow-ups. Unrelated and mixed-topic requests are declined.</p><p><b>What leaves this app</b><br>Once enabled, finance prompts, up to four recent financial exchanges, the selected fictional person’s financial summaries, financial-trouble ranking with its factors, and relevant local calculations are sent to Puter and its model provider. A calculation may include matching transactions. The full ledger and microphone recordings are not sent to Grok. Do not type bank credentials or sensitive identifiers.</p><p><b>Your Puter account covers usage</b><br>No API key is needed. Puter sign-in and internet are required. A free allowance may apply; limits and charges are set by Puter, not unlimited free access. This app does not upgrade your plan.</p><p><b>Guidance, not execution</b><br>Grok cannot edit your ledger or pay anyone. Financial calculations and explicit confirmation controls stay on this server. AI can make mistakes; verify important decisions with a qualified professional.</p></div>
       <p id="ai-connection-status" class="form-note" role="status"></p>
       ${this.enabled ? `<div class="dialog-actions"><button class="button secondary" data-action="ai-disconnect">Disconnect AI</button><button class="button primary" data-action="close-dialog">Back to my finances</button></div><p class="form-note">Disconnect stops new sharing. It does not delete earlier requests from Puter or sign you out of your Puter account.</p>` : `<label class="checkbox-label ai-consent"><input id="ai-consent" type="checkbox">I agree to send the described financial context to Puter / the model provider and use my Puter allowance.</label><div class="dialog-actions"><a class="button secondary" href="${esc(location.href)}" target="_blank" rel="noopener noreferrer">Open app in a new tab</a><button id="ai-connect" class="button primary" data-action="ai-connect" disabled>Connect with Puter</button></div><p class="form-note">Allow the Puter sign-in popup. If an embedded preview blocks it, open this app in its own HTTPS tab.</p>`}
       <p class="form-note"><a href="https://docs.puter.com/user-pays-model/" target="_blank" rel="noopener noreferrer">How Puter usage works</a> · <a href="https://puter.com/dashboard#usage" target="_blank" rel="noopener noreferrer">Puter usage dashboard</a></p>`,
      "FINANCE-ONLY AI",
    );
    this.syncUI();
  }
  async connect() {
    if (!state.profile || this.connecting || state.busy || !$("ai-consent")?.checked) return;
    this.connecting = true;
    this.error = "";
    const epoch = ++this.epoch;
    this.syncUI();
    try {
      this.sdk = loadPuterSDK();
      // Keep signIn synchronous with this click so the browser permits its popup.
      const signIn = this.sdk.auth.isSignedIn()
        ? Promise.resolve()
        : this.sdk.auth.signIn({ attempt_temp_user_creation: false });
      await timed(signIn, 120000);
      if (epoch !== this.epoch) return;
      if (!this.sdk.auth.isSignedIn()) throw new Error("sign_in_required");
      this.enabled = true;
      storeSet("solvra.ai-consent.v1", "yes");
      storeSet("solvra.ai-profile.v1", state.profile.id);
      if ($("ai-connection-status")) this.open();
      toast("Grok connected. Your next finance question can use AI.");
    } catch (error) {
      if (epoch === this.epoch) this.error = this.describeError(error, true);
    } finally {
      if (epoch === this.epoch) {
        this.connecting = false;
        this.syncUI();
      }
    }
  }
  disconnect() {
    ++this.epoch;
    this.controller?.abort();
    this.enabled = false;
    this.error = "";
    storeSet("solvra.ai-consent.v1", "no");
    this.open();
    toast("AI disconnected. New questions use the local finance engine.");
  }
  describeError(error, signingIn = false) {
    const code = String(error?.code || error?.error?.code || error?.error || error?.message || "");
    if (/popup|origin/i.test(code))
      return "Puter sign-in was blocked. Open this app in its own HTTPS tab and allow the sign-in popup.";
    if (signingIn && /closed|cancel/i.test(code))
      return "Sign-in canceled. Nothing was sent to Grok.";
    if (/quota|credit|usage|limit|balance|fund/i.test(code))
      return "Puter usage is unavailable or its allowance is exhausted. Check your Puter usage dashboard; no plan was upgraded.";
    if (/auth|sign.?in|token/i.test(code))
      return "Puter sign-in is required or expired. Disconnect and connect again.";
    return signingIn
      ? "Puter could not connect. Check your network and popup settings; local finance tools still work."
      : "Grok did not complete this question. Showing the local finance engine instead; you can retry with your next question.";
  }
  content(response) {
    if (response?.finish_reason === "length") throw new Error("incomplete_answer");
    const value = response?.message?.content;
    const text = Array.isArray(value)
      ? value
          .filter((part) => part.type === "text")
          .map((part) => part.text)
          .join("")
      : value;
    if (typeof text !== "string" || !text.trim() || text.length > 14000)
      throw new Error("invalid_answer");
    return text;
  }
  async complete(messages, outputFormat, model, maxTokens) {
    const controller = this.controller;
    if (!this.enabled || controller.signal.aborted)
      throw new DOMException("AI request stopped", "AbortError");
    let onAbort;
    const stopped = new Promise((_, reject) => {
      onAbort = () => reject(new DOMException("AI request stopped", "AbortError"));
      controller.signal.addEventListener("abort", onAbort, { once: true });
      if (controller.signal.aborted) onAbort();
    });
    const timer = setTimeout(() => controller.abort(), 45000);
    try {
      return this.content(
        await Promise.race([
          this.sdk.ai.chat(messages, {
            model,
            temperature: 0.2,
            max_tokens: maxTokens,
            normalize: true,
            outputFormat,
            signal: controller.signal,
          }),
          stopped,
        ]),
      );
    } finally {
      clearTimeout(timer);
      controller.signal.removeEventListener("abort", onAbort);
    }
  }
  async enhance(response, context = currentRequest()) {
    const job = response.ai_job;
    if (!job) return response;
    const epoch = this.epoch;
    this.controller = new AbortController();
    this.error = "";
    try {
      if (!this.enabled || !this.sdk?.auth.isSignedIn()) throw new Error("sign_in_required");
      this.phase = "Checking financial scope…";
      this.syncUI();
      const verdict = await this.complete(job.messages, job.output_format, job.model, 80);
      if (epoch !== this.epoch) throw new Error("canceled");
      const prepared = await api("ai_context", { ticket: job.ticket, verdict }, context);
      if (prepared.response) return prepared.response;
      if (epoch !== this.epoch) throw new Error("canceled");
      this.phase = "Thinking with your financial context…";
      this.syncUI();
      const completion = await this.complete(
        prepared.messages,
        prepared.output_format,
        prepared.model,
        1100,
      );
      if (epoch !== this.epoch) throw new Error("canceled");
      return await api("ai_finish", { ticket: job.ticket, completion }, context);
    } catch (error) {
      if (context.epoch !== state.epoch) return response;
      if (epoch === this.epoch) {
        this.error = this.describeError(error);
        toast(this.error, true);
      }
      return await api("ai_abort", { ticket: job.ticket }, context);
    } finally {
      if (context.epoch === state.epoch) {
        this.phase = "";
        this.controller = null;
        this.syncUI();
      }
    }
  }
  dispose() {
    ++this.epoch;
    this.controller?.abort();
  }
}
financeAI = new FinanceAI();
