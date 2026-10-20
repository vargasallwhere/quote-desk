(() => {
  "use strict";

  const BASE_URL = window.location.origin;
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("session");
  const byId = (id) => document.getElementById(id);
  const fields = {
    requested_by: "rv-requested-by",
    alt_type: "rv-alt-type",
    alt_subtype: "rv-alt-subtype",
    requested_sku: "rv-req-sku",
    multiple_skus: "rv-multi-skus",
    device_type: "rv-device-type",
    make: "rv-make",
    model: "rv-model",
    display_size: "rv-display",
    processor: "rv-processor",
    memory: "rv-memory",
    storage: "rv-storage",
    color: "rv-color",
    keyboard_language: "rv-keyboard",
    sku_country: "rv-country",
    mpn: "rv-mpn",
    price: "rv-price",
    lead_time: "rv-lead-time"
  };
  const sourceChoices = [
    { email: "sara@allwhere.co", name: "Sara Vargas" },
    { email: "keajah@allwhere.co", name: "Keajah" },
    { email: "giancarlo@allwhere.co", name: "Giancarlo Sanchez" },
    { email: "olivia@allwhere.co", name: "Olivia" },
    { email: "emma@allwhere.co", name: "Emma Vasey" }
  ];
  const form = byId("rv-form");
  const submitButton = byId("rv-submit-btn");
  const submitStatus = byId("rv-submit-status");
  const leadRow = byId("rv-lead-time-row");
  let review = null;
  let locked = true;
  let state = "loading";
  let ambiguousRecovery = false;

  function setText(id, value, fallback = "—") {
    byId(id).textContent = value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function showNotice(id, text) {
    const element = byId(id);
    if (text) {
      element.textContent = text;
      element.classList.remove("hidden");
    } else {
      element.textContent = "";
      element.classList.add("hidden");
    }
  }

  function showListNotice(id, title, messages) {
    const element = byId(id);
    element.replaceChildren();
    if (!Array.isArray(messages) || !messages.length) {
      element.classList.add("hidden");
      return;
    }
    const strong = document.createElement("strong");
    strong.textContent = `${title} `;
    const list = document.createElement("span");
    list.textContent = messages.join(" · ");
    element.append(strong, list);
    element.classList.remove("hidden");
  }

  function setSelectValue(select, value, labelPrefix = "Unverified source value") {
    if (value === null || value === undefined || value === "") return false;
    const stringValue = String(value);
    const found = Array.from(select.options).find((option) =>
      option.value === stringValue || option.textContent === stringValue
    );
    if (found) {
      select.value = found.value;
      return false;
    }
    const option = document.createElement("option");
    option.value = stringValue;
    option.textContent = `${labelPrefix}: ${stringValue}`;
    option.dataset.unverified = "true";
    select.add(option);
    select.value = stringValue;
    return true;
  }

  function populateRequestedBy(options, selected) {
    const select = byId("rv-requested-by");
    const merged = [...sourceChoices];
    if (review?.procurement_manager_email) {
      merged.push({
        email: String(review.procurement_manager_email),
        name: String(review.procurement_manager_name || "Procurement Manager")
      });
    }
    if (Array.isArray(options)) {
      for (const choice of options) {
        if (!choice || !choice.email) continue;
        const exists = merged.some((item) => item.email.toLowerCase() === String(choice.email).toLowerCase());
        if (!exists) merged.push({ email: String(choice.email), name: String(choice.name || choice.email) });
        else {
          const entry = merged.find((item) => item.email.toLowerCase() === String(choice.email).toLowerCase());
          if (choice.name) entry.name = String(choice.name);
        }
      }
    }
    select.replaceChildren(new Option("Select a requester", ""));
    for (const choice of merged) {
      select.add(new Option(`${choice.name} · ${choice.email}`, choice.email));
    }
    if (selected) {
      const found = merged.find((item) => item.email.toLowerCase() === String(selected).toLowerCase());
      if (found) select.value = found.email;
      else {
        const unknown = new Option(`Unverified source value: ${selected}`, String(selected));
        unknown.dataset.unverified = "true";
        select.add(unknown);
        select.value = String(selected);
        byId("rv-unverified").classList.remove("hidden");
      }
    }
  }

  function populate(reviewData, options) {
    review = reviewData || {};
    setText("rv-order", review.order_number);
    setText("rv-org", review.org_name);
    setText("rv-om", review.order_manager_name);
    populateRequestedBy(options, review.requested_by);
    const selectKeys = new Set(["alt_type", "alt_subtype", "device_type"]);
    const unverified = [];
    for (const [key, id] of Object.entries(fields)) {
      const value = review[key];
      if (key === "requested_by") continue;
      const element = byId(id);
      if (value === null || value === undefined) continue;
      if (selectKeys.has(key)) {
        if (setSelectValue(element, value)) unverified.push(key.replaceAll("_", " "));
      } else if (key === "multiple_skus") {
        element.checked = value === true || value === "true" || value === 1;
      } else {
        element.value = String(value);
      }
    }
    if (unverified.length) byId("rv-unverified").classList.remove("hidden");
    showListNotice("rv-mapping-errors", "Mapping notes:", review.mapping_errors);
    showListNotice("rv-errors", "Configuration:", review.configuration_errors);
    updateLeadTimeVisibility(false);
  }

  function updateLeadTimeVisibility(fromUser) {
    const type = byId("rv-alt-type").value;
    const show = type === "CTO device" || type === "Out of stock / backordered";
    leadRow.classList.toggle("hidden", !show);
    if (show && type === "CTO device" && (fromUser || !byId("rv-lead-time").value)) {
      byId("rv-lead-time").value = "3-5 weeks";
    }
    if (fromUser && type === "Out of stock / backordered") byId("rv-lead-time").value = "";
    if (fromUser && !show) byId("rv-lead-time").value = "";
  }

  function lockForm(nextState, message) {
    state = nextState;
    locked = true;
    for (const control of form.elements) control.disabled = true;
    submitButton.disabled = true;
    submitButton.querySelector("span").textContent = nextState === "submitting" ? "Creating ticket…" : "Review locked";
    if (message) showNotice("rv-state-message", message);
  }

  function unlockForm() {
    locked = false;
    state = "pending";
    for (const control of form.elements) control.disabled = false;
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Submit to Airtable";
    updateLeadTimeVisibility(false);
    showNotice("rv-state-message", "");
  }

  function safeTicketUrl(url) {
    try {
      const parsed = new URL(url, BASE_URL);
      return parsed.protocol === "https:" || parsed.origin === BASE_URL ? parsed.href : "";
    } catch {
      return "";
    }
  }

  function showResult(result) {
    const card = byId("rv-result");
    const link = byId("rv-airtable-link");
    const title = byId("rv-result-title");
    const message = byId("rv-result-message");
    card.classList.remove("hidden");
    const created = result && result.created === true;
    const successful = result && result.ok === true;
    if (created) {
      showListNotice("rv-mapping-errors", "", []);
      showListNotice("rv-errors", "", []);
      title.textContent = "Ticket created";
      message.textContent = result.message || (result.notification === "failed"
        ? "The ticket was created, but the customer notification failed. Do not create another ticket."
        : result.notification === "uncertain"
          ? "The ticket was created; customer notification status is uncertain. Do not create another ticket."
          : "The ticket was created successfully.");
      byId("rv-no-duplicate").classList.remove("hidden");
      const href = safeTicketUrl(result.url);
      if (href) {
        link.href = href;
        link.classList.remove("hidden");
      } else {
        link.classList.add("hidden");
      }
      lockForm("completed", "");
      submitButton.querySelector("span").textContent = "Ticket created";
    } else if (state === "uncertain" || (result && result.retryable === false)) {
      title.textContent = "Submission status uncertain";
      message.textContent = result?.message || result?.error || "Quote Desk could not confirm the ticket outcome.";
      byId("rv-no-duplicate").textContent = "Do not submit again. Check Airtable for this request before taking any further action.";
      byId("rv-no-duplicate").classList.remove("hidden");
      lockForm("uncertain", "Check Airtable before any further action. This request will not be submitted automatically.");
    } else {
      card.classList.add("hidden");
    }
    if (result?.error || result?.message) submitStatus.textContent = result.error || result.message;
    if (Array.isArray(result?.mapping_errors)) showListNotice("rv-mapping-errors", "Mapping notes:", result.mapping_errors);
    if (Array.isArray(result?.configuration_errors)) showListNotice("rv-errors", "Configuration:", result.configuration_errors);
    if (successful && !created) {
      title.textContent = "Request completed";
      message.textContent = result.message || "Quote Desk marked this request complete.";
      lockForm("completed", "");
    }
  }

  function renderState(payload) {
    const currentState = payload?.state || "pending";
    const result = payload?.result;
    if (currentState === "completed") {
      if (result) showResult(result);
      else lockForm("completed", "This review has already been completed and is locked.");
      return;
    }
    if (currentState === "uncertain") {
      if (result) showResult(result);
      else lockForm("uncertain", "Submission status is uncertain. Check Airtable before creating another ticket.");
      return;
    }
    if (currentState === "submitting") {
      lockForm("submitting", "A submission is already in progress. This review is locked to prevent a duplicate ticket.");
      return;
    }
    if (result?.ok || result?.created) {
      showResult(result);
      return;
    }
    unlockForm();
    if (result?.error || result?.message) {
      submitStatus.textContent = result.error || result.message;
      if (result.retryable === true) {
        submitButton.disabled = false;
      } else if (result.retryable === false) {
        state = "uncertain";
        lockForm("uncertain", "Check Airtable before any further action. Do not submit this request again.");
      }
    }
  }

  function gatherTicket() {
    const ticket = {};
    for (const [key, id] of Object.entries(fields)) {
      const element = byId(id);
      ticket[key] = key === "multiple_skus" ? element.checked : element.value.trim();
    }
    return ticket;
  }

  function validate(ticket) {
    const missing = [];
    const required = [
      ["requested_by", "Requested by (Procurement)"],
      ["alt_type", "Alternate type"],
      ["requested_sku", "Requested SKU"],
      ["device_type", "Device type"],
      ["make", "Make"],
      ["model", "Model"],
      ["display_size", "Display size"],
      ["processor", "Processor"],
      ["memory", "Memory"],
      ["storage", "Storage"],
      ["color", "Color"],
      ["keyboard_language", "Keyboard language"],
      ["sku_country", "SKU country / region"],
      ["price", "Price (USD)"]
    ];
    for (const [key, label] of required) {
      if (!String(ticket[key] ?? "").trim()) missing.push(label);
    }
    const price = Number(ticket.price);
    if (ticket.price && (!Number.isFinite(price) || price < 0)) {
      byId("rv-price").setAttribute("aria-invalid", "true");
      return `Price must be a finite, non-negative USD amount.${missing.length ? ` Also required: ${missing.join(", ")}.` : ""}`;
    }
    byId("rv-price").removeAttribute("aria-invalid");
    if (missing.length) return `Complete the required fields: ${missing.join(", ")}.`;
    return "";
  }

  async function recoverAmbiguousPost() {
    ambiguousRecovery = true;
    submitStatus.textContent = "Connection interrupted. Checking the saved session once; no second submission will be sent.";
    try {
      const response = await fetch(`${BASE_URL}/api/alt-review/${encodeURIComponent(sessionId)}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("Recovery check was unavailable.");
      const payload = await response.json();
      showListNotice("rv-mapping-errors", "Mapping notes:", payload.mapping_errors || payload.review?.mapping_errors);
      renderState(payload);
      if (payload.state === "pending" && !payload.result) {
        lockForm("uncertain", "Quote Desk still reports this review as pending after a connection interruption. Check Airtable before retrying.");
        byId("rv-result").classList.remove("hidden");
        byId("rv-result-title").textContent = "Check Airtable before retrying";
        byId("rv-result-message").textContent = "The save outcome could not be confirmed. Quote Desk did not send another submission.";
        byId("rv-no-duplicate").textContent = "Do not create another ticket until you have checked Airtable.";
        byId("rv-no-duplicate").classList.remove("hidden");
      }
    } catch {
      lockForm("uncertain", "The submission outcome could not be confirmed. Check Airtable before creating another ticket.");
      byId("rv-result").classList.remove("hidden");
      byId("rv-result-title").textContent = "Check Airtable before retrying";
      byId("rv-result-message").textContent = "Quote Desk could not recover the saved session. No automatic retry was sent.";
      byId("rv-no-duplicate").textContent = "Do not create another ticket until you have checked Airtable.";
      byId("rv-no-duplicate").classList.remove("hidden");
    }
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (!review || locked || state !== "pending" || ambiguousRecovery) return;
    const ticket = gatherTicket();
    const validationError = validate(ticket);
    if (validationError) {
      submitStatus.textContent = validationError;
      const firstInvalid = form.querySelector(":invalid");
      if (firstInvalid) firstInvalid.focus();
      return;
    }
    submitStatus.textContent = "";
    lockForm("submitting", "Creating the ticket and sending the customer notification…");
    submitButton.querySelector("span").textContent = "Creating ticket…";
    try {
      const response = await fetch(`${BASE_URL}/api/alt-review/${encodeURIComponent(sessionId)}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(ticket)
      });
      let result = {};
      try { result = await response.json(); } catch { /* A response without JSON is ambiguous. */ }
      if (result.retryable === true) {
        unlockedAfterRetryableFailure(result, response.status);
      } else if (response.ok) {
        state = result.created || result.ok ? "completed" : "uncertain";
        showResult(result);
      } else {
        state = "uncertain";
        showResult({ ...result, retryable: false });
      }
    } catch {
      await recoverAmbiguousPost();
    }
  }

  function unlockedAfterRetryableFailure(result, status) {
    state = "pending";
    unlockForm();
    submitStatus.textContent = result.error || result.message || (status === 503
      ? "Quote Desk is temporarily unavailable. Review configuration and try again when ready."
      : "Please correct the review details and try again.");
    if (Array.isArray(result.mapping_errors)) showListNotice("rv-mapping-errors", "Mapping notes:", result.mapping_errors);
    if (Array.isArray(result.configuration_errors)) showListNotice("rv-errors", "Configuration:", result.configuration_errors);
  }

  async function loadReview() {
    if (!sessionId) {
      setText("rv-session-ref", "NOT FOUND");
      lockForm("expired", "This Quote Desk review link has no session identifier. Return to Quote Desk and open the review again.");
      byId("rv-state-message").classList.add("notice-error");
      return;
    }
    setText("rv-session-ref", sessionId.length > 16 ? `${sessionId.slice(0, 8)}…${sessionId.slice(-5)}` : sessionId);
    try {
      const response = await fetch(`${BASE_URL}/api/alt-review/${encodeURIComponent(sessionId)}`, { headers: { Accept: "application/json" } });
      if (response.status === 404 || response.status === 410) {
        lockForm("expired", "This Quote Desk review session has expired or is no longer available. If you submitted it, check Airtable before starting another review. Otherwise reopen it from Quote Desk.");
        byId("rv-state-message").classList.add("notice-error");
        return;
      }
      if (!response.ok) throw new Error(`Quote Desk returned ${response.status}.`);
      const payload = await response.json();
      if (!payload || !payload.review) throw new Error("The review response was incomplete.");
      populate(payload.review, payload.requested_by_options);
      showListNotice("rv-mapping-errors", "Mapping notes:", payload.mapping_errors || payload.review.mapping_errors);
      showListNotice("rv-errors", "Configuration:", payload.configuration_errors);
      renderState(payload);
    } catch (error) {
      lockForm("error", `Quote Desk could not load this review. ${error.message || "Check your connection and return to Quote Desk to try again."}`);
      byId("rv-state-message").classList.add("notice-error");
    }
  }

  byId("rv-alt-type").addEventListener("change", () => updateLeadTimeVisibility(true));
  form.addEventListener("submit", onSubmit);
  loadReview();
})();
