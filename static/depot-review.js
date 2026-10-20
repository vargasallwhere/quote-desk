(() => {
  "use strict";

  const states = new Map();
  const vendorViews = new Map();
  let active = null;
  let requestGeneration = 0;
  let lastRequestedPO = "";

  const el = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
  }[char]));
  const stateFor = po => {
    if (!states.has(po)) states.set(po, {
      po, loaded: false, loading: null, subject: "", body: "", to: "", cc: "",
      warnings: [], notification: { state: "new", revision: null }, error: "",
      busy: false, locked: false, confirmSnapshot: null, confirmation: null
    });
    return states.get(po);
  };
  const isWritable = state => state.loaded && !state.busy && !state.locked &&
    !["sent", "uncertain", "saving", "sending"].includes(state.notification?.state);

  function renderEligibility(order) {
    const host = el("depot-order-banner");
    if (!host) return;
    const notification = order?.depot_notification;
    if (!notification || typeof notification !== "object") {
      host.innerHTML = `<div class="depot-reason"><strong>Depot notification unavailable</strong><br>Destination or source details are missing or conflicting, so eligibility cannot be confirmed.</div>`;
      host.hidden = false;
      return;
    }
    if (notification.eligible === true) {
      host.innerHTML = `<div class="depot-entry-row"><div><div class="depot-destination">Destination: allwhere storage Australia</div><div class="note">Australia depot arrival notification</div></div><button type="button" class="btn primary" id="depot-open">Let depot know this is coming</button></div>`;
      host.hidden = false;
      el("depot-open").onclick = () => open(order.order_number || order.po);
    } else {
      const reason = notification.reason || "The depot notification is not available for this order.";
      host.innerHTML = `<div class="depot-reason"><strong>Depot notification unavailable</strong><br>${esc(reason)}</div>`;
      host.hidden = false;
    }
  }

  function ensureShell() {
    if (el("depot-review")) return;
    const node = document.createElement("section");
    node.id = "depot-review";
    node.setAttribute("aria-label", "Australia depot arrival email review");
    node.innerHTML = `<div class="depot-shell">
      <header class="depot-head"><button type="button" id="depot-back" class="btn">Back</button>
        <div class="depot-heading"><h1>Australia depot arrival email</h1><p id="depot-order-label"></p></div>
        <span class="mono" id="depot-state-badge"></span></header>
      <div class="depot-content">
        <div class="depot-fields">
          <div class="depot-field"><label for="depot-to">To · fixed recipients</label><textarea id="depot-to" rows="5" readonly></textarea></div>
          <div class="depot-field"><label for="depot-cc">Cc · fixed recipients</label><input id="depot-cc" readonly></div>
          <div class="depot-field" style="grid-column:1/-1"><label for="depot-subject">Subject</label><input id="depot-subject" maxlength="998"></div>
        </div>
        <div id="depot-warnings" class="depot-warnings" role="note" hidden></div>
        <label class="depot-body-label" for="depot-body">Message</label>
        <textarea class="depot-body" id="depot-body" spellcheck="true"></textarea>
        <div class="depot-confirm" id="depot-confirm" hidden>
          <h2>Confirm this exact email</h2>
          <p>Review the current recipients, subject, and message. Any edit closes this confirmation.</p>
          <div class="depot-confirm-preview" id="depot-confirm-preview"></div>
          <div class="depot-actions-right" style="margin-top:10px"><button type="button" class="btn" id="depot-cancel-send">Cancel</button><button type="button" class="btn danger" id="depot-confirm-send">Confirm and send</button></div>
        </div>
        <div class="depot-state" id="depot-status" role="status" aria-live="polite"></div>
        <footer class="depot-actions"><span class="note" id="depot-status-note"></span><div class="depot-actions-right">
          <button type="button" class="btn" id="depot-save">Save draft</button><button type="button" class="btn primary" id="depot-send">Send</button>
        </div></footer>
      </div>
    </div>`;
    el("main-split")?.after(node);
    el("depot-back").onclick = () => close();
    el("depot-subject").addEventListener("input", onEdit);
    el("depot-body").addEventListener("input", onEdit);
    el("depot-save").onclick = save;
    el("depot-send").onclick = armConfirmation;
    el("depot-cancel-send").onclick = disarmConfirmation;
    el("depot-confirm-send").onclick = send;
  }

  async function getPreview(state, token) {
    if (state.loaded) return state;
    if (state.loading) return state.loading;
    state.loading = (async () => {
      try {
        const response = await fetch(`/api/depot-preview/${encodeURIComponent(state.po)}`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || "Could not load depot email preview.");
        if (data.order_number !== state.po) throw new Error("The preview did not match the selected order.");
        state.to = data.to || "";
        state.cc = data.cc || "";
        state.subject = data.subject || "";
        state.body = data.body || "";
        state.warnings = Array.isArray(data.warnings) ? data.warnings : [];
        state.notification = data.notification || { state: "new", revision: null };
        state.error = "";
        state.loaded = true;
      } catch (error) {
        state.error = error.message || "Preview unavailable.";
      } finally {
        state.loading = null;
      }
      return state;
    })();
    return state.loading;
  }

  function open(po) {
    if (!po) return;
    ensureShell();
    const key = String(po);
    const state = stateFor(key);
    active = state;
    const token = ++requestGeneration;
    document.body.classList.add("depot-review-active");
    render(state);
    el("depot-back").focus();
    if (!state.loaded && !state.loading) {
      state.error = "";
      setStatus("Loading the depot email preview…");
    }
    getPreview(state, token).then(result => {
      if (active === result && token === requestGeneration) render(result);
    });
  }

  function render(state) {
    ensureShell();
    el("depot-order-label").textContent = `Order ${state.po}`;
    el("depot-to").value = state.to;
    fitRecipients();
    el("depot-cc").value = state.cc;
    el("depot-subject").value = state.subject;
    el("depot-body").value = state.body;
    const warningBox = el("depot-warnings");
    warningBox.hidden = !state.warnings.length;
    warningBox.innerHTML = state.warnings.length
      ? `<strong>Before you send</strong><ul>${state.warnings.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : "";
    const notificationState = state.notification?.state || "new";
    el("depot-state-badge").textContent = notificationState === "sent" ? "SENT" :
      notificationState === "draft" ? "DRAFT SAVED" :
      notificationState === "uncertain" || state.locked ? "CHECK GMAIL" : "NEW";
    el("depot-status-note").textContent = notificationState === "sent"
      ? "This notification has already been sent. Editing and sending are disabled."
      : notificationState === "draft" ? "Draft saved. It has not been sent."
      : notificationState === "uncertain" || state.locked
        ? "The result may be uncertain. Check Gmail before taking any further action; retry is disabled."
        : "Recipients are fixed by the depot notification service.";
    const writable = isWritable(state);
    el("depot-confirm-send").disabled = !writable;
    el("depot-subject").disabled = !writable;
    el("depot-body").disabled = !writable;
    el("depot-save").disabled = !writable;
    el("depot-send").disabled = !writable;
    el("depot-save").textContent = state.busy && state.operation === "save" ? "Saving…" : "Save draft";
    el("depot-send").textContent = state.busy && state.operation === "send" ? "Sending…" : "Send";
    el("depot-confirm").hidden = !state.confirmSnapshot;
    if (state.confirmSnapshot) {
      const snap = state.confirmSnapshot;
      el("depot-confirm-preview").textContent = `To: ${state.to}\nCc: ${state.cc}\nSubject: ${snap.subject}\n\n${snap.body}`;
    }
    if (state.error) {
      setStatus(state.error, "error");
      if (!state.loaded && !state.loading) {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn";
        retry.textContent = "Retry preview";
        retry.style.marginLeft = "8px";
        retry.onclick = () => open(state.po);
        el("depot-status").append(" ", retry);
      }
    }
  }

  function fitRecipients() {
    const to = el("depot-to");
    if (!to) return;
    to.style.height = "auto";
    to.style.height = (to.scrollHeight + 2) + "px";
  }
  window.addEventListener("resize", fitRecipients);

  function setStatus(message, kind = "") {
    const status = el("depot-status");
    if (!status) return;
    status.textContent = message;
    status.dataset.kind = kind;
  }

  function onEdit() {
    if (!active) return;
    active.subject = el("depot-subject").value;
    active.body = el("depot-body").value;
    active.confirmSnapshot = null;
    active.confirmation = null;
    el("depot-confirm").hidden = true;
    setStatus("Edited. Save the draft or review the exact text before sending.");
  }

  function disarmConfirmation() {
    if (!active) return;
    active.confirmSnapshot = null;
    active.confirmation = null;
    el("depot-confirm").hidden = true;
    setStatus("Send confirmation cancelled.");
  }

  function armConfirmation() {
    if (!active || !isWritable(active)) return;
    active.subject = el("depot-subject").value;
    active.body = el("depot-body").value;
    active.confirmSnapshot = { subject: active.subject, body: active.body };
    active.confirmation = null;
    render(active);
    el("depot-confirm-send").focus();
    setStatus("Confirm only if these exact fields are correct.");
  }

  function payload(state) {
    return { po: state.po, subject: state.subject, body: state.body, revision: state.notification?.revision ?? null };
  }

  async function writeRequest(state, action, extra = {}) {
    const token = requestGeneration;
    const response = await fetch(`/api/depot-${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload(state), ...extra })
    });
    let data;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (data.notification) state.notification = data.notification;
    if (!response.ok || data.error) {
      if (data.uncertain) {
        state.locked = true;
        state.notification = { ...state.notification, state: "uncertain" };
        state.error = `${data.error || "The result is uncertain."} Check Gmail before any further action.`;
        if (active === state) render(state);
        return null;
      }
      const error = new Error(data.error || `Request failed (${response.status}).`);
      error.definite = true;
      throw error;
    }
    if ((action === "confirm" && typeof data.confirmation !== "string") ||
        (action !== "confirm" && !data.notification?.state)) {
      throw new Error("The server response was incomplete. Check Gmail before retrying a write.");
    }
    return data;
  }

  async function save() {
    if (!active || !isWritable(active)) return;
    const state = active;
    state.subject = el("depot-subject").value;
    state.body = el("depot-body").value;
    state.busy = true;
    state.operation = "save";
    disarmConfirmation();
    render(state);
    setStatus("Saving draft…");
    try {
      const data = await writeRequest(state, "save");
      if (!data) return;
      state.notification = data.notification || { ...state.notification, state: "draft" };
      state.locked = false;
      state.error = "";
      if (active === state) setStatus(state.notification.state === "sent" ? "This email is already sent." : "Draft saved. Nothing was sent.", "success");
    } catch (error) {
      state.locked = !error.definite;
      if (state.locked) state.notification = { ...state.notification, state: "uncertain" };
      state.error = error.definite ? error.message : "Draft save outcome is uncertain. Check Gmail before taking any further action; retry is disabled.";
    } finally {
      state.busy = false;
      state.operation = "";
      if (active === state) render(state);
    }
  }

  async function send() {
    if (!active || !active.confirmSnapshot || !isWritable(active)) return;
    const state = active;
    const current = { subject: el("depot-subject").value, body: el("depot-body").value };
    if (current.subject !== state.confirmSnapshot.subject || current.body !== state.confirmSnapshot.body) {
      disarmConfirmation();
      return;
    }
    state.subject = current.subject;
    state.body = current.body;
    state.busy = true;
    state.operation = "send";
    render(state);
    setStatus("Confirming the exact email…");
    let sendStarted = false;
    try {
      const checked = await writeRequest(state, "confirm");
      if (!checked || active !== state) {
        state.locked = false;
        state.error = "Confirmation cancelled when the review closed. Nothing was sent.";
        return;
      }
      const confirmation = checked.confirmation;
      if (!confirmation) throw new Error("The server did not return a send confirmation.");
      state.confirmation = confirmation;
      setStatus("Sending the confirmed email…");
      sendStarted = true;
      const sent = await writeRequest(state, "send", { confirmation });
      if (!sent) return;
      state.notification = sent.notification || { ...state.notification, state: "sent" };
      state.locked = false;
      state.confirmSnapshot = null;
      state.confirmation = null;
      state.error = "";
      if (active === state) setStatus(state.notification.state === "sent" ? "Sent to the Australia depot." : "Send request completed.", "success");
    } catch (error) {
      state.locked = sendStarted && !error.definite;
      if (state.locked) state.notification = { ...state.notification, state: "uncertain" };
      state.confirmSnapshot = null;
      state.confirmation = null;
      state.error = !sendStarted ? "Could not confirm this message. Nothing was sent. Review it and try again."
        : error.definite ? error.message : "Send outcome is uncertain. Check Gmail before taking any further action; retry is disabled.";
    } finally {
      state.busy = false;
      state.operation = "";
      if (active === state) render(state);
    }
  }

  function close(restoreFocus = true) {
    if (active?.busy) {
      active.locked = true;
      active.notification = { ...active.notification, state: "uncertain" };
      active.error = "A write was pending when this review closed. Check Gmail before taking any further action; retry is disabled.";
      active.busy = false;
    }
    ++requestGeneration;
    active = null;
    document.body.classList.remove("depot-review-active");
    if (restoreFocus) el("depot-open")?.focus();
  }

  window.DepotReview = {
    open,
    orderChanging(po) {
      const next = String(po || "");
      const thread = el("thread");
      if (lastRequestedPO && thread && ["rto", "rcc", "rsub", "rbody"].some(id => {
        const field = el(id);
        return field && field.value !== field.defaultValue;
      })) vendorViews.set(lastRequestedPO, Array.from(thread.childNodes));
      close(false);
      if (el("depot-order-banner")) el("depot-order-banner").hidden = true;
      lastRequestedPO = next;
    },
    restoreVendorView(po) {
      const nodes = vendorViews.get(po);
      if (!nodes) return false;
      el("thread").replaceChildren(...nodes);
      return true;
    },
    showOrder(order) { renderEligibility(order); }
  };
})();
