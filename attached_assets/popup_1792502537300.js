// ── Sourcing Scout ───────────────────────────────────────────────────────────
// Ticket Creator — POST /order-info → fetch order, create Airtable ticket
// Panel version: served by Flask, uses postMessage bridge for chrome.* APIs
// ─────────────────────────────────────────────────────────────────────────────

const BASE_URL = window.location.origin;

// ── Bridge to extension context (for chrome.tabs / chrome.scripting) ─────────

const _ext = {
  _id: 0,
  _pending: new Map(),

  call(action, args) {
    return new Promise((resolve, reject) => {
      const id = ++this._id;
      this._pending.set(id, { resolve, reject });
      window.parent.postMessage({ __scout: true, id, action, args }, '*');
    });
  },
};

window.addEventListener('message', (event) => {
  if (!event.data || !event.data.__scout_reply) return;
  const { id, result, error } = event.data;
  const p = _ext._pending.get(id);
  if (!p) return;
  _ext._pending.delete(id);
  if (error) p.reject(new Error(error));
  else p.resolve(result);
});

// ── Tab switching ─────────────────────────────────────────────────────────────

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// TICKET CREATOR TAB
// ══════════════════════════════════════════════════════════════════════════════

const orderInput     = document.getElementById("orderInput");
const checkBtn       = document.getElementById("checkBtn");
const spinner        = document.getElementById("spinner");
const errorBox       = document.getElementById("errorBox");
const ctoAlert       = document.getElementById("ctoAlert");
const enterpriseWarrantyAlert = document.getElementById("enterpriseWarrantyAlert");

// Country-specific button references
const orderNoteBtnUs   = document.getElementById("orderNoteBtnUs");
const orderNoteBtnUk   = document.getElementById("orderNoteBtnUk");
const v2TicketBtnUs    = document.getElementById("v2TicketBtnUs");
const v2TicketBtnUk    = document.getElementById("v2TicketBtnUk");
const addressBtnUs     = document.getElementById("addressBtnUs");
const addressBtnUk     = document.getElementById("addressBtnUk");
const autoQuoteBtnUs     = document.getElementById("autoQuoteBtnUs");
const autoQuoteBtnUk     = document.getElementById("autoQuoteBtnUk");
const autoQuoteBtnEu     = document.getElementById("autoQuoteBtnEu");

const countryBanner    = document.getElementById("countryBanner");
const orderActionsUs   = document.getElementById("orderActionsUs");
const orderActionsUk   = document.getElementById("orderActionsUk");
const orderActionsEu   = document.getElementById("orderActionsEu");

let _lastOrderInfo    = null;   // full response from /order-info
let _lastFetchedOrder = null;   // order number corresponding to _lastOrderInfo
let _selectedItems    = [];     // items chosen in multi-item selector
let _currentCountry   = null;   // "us", "uk", or "eu"

// ── Country detection & display ──────────────────────────────────────────────

const COUNTRY_FLAGS = {
  "united states": "🇺🇸", "us": "🇺🇸", "usa": "🇺🇸",
  "united kingdom": "🇬🇧", "uk": "🇬🇧", "gb": "🇬🇧", "great britain": "🇬🇧",
  "germany": "🇩🇪", "france": "🇫🇷", "netherlands": "🇳🇱", "spain": "🇪🇸",
  "italy": "🇮🇹", "belgium": "🇧🇪", "ireland": "🇮🇪", "austria": "🇦🇹",
  "poland": "🇵🇱", "portugal": "🇵🇹", "sweden": "🇸🇪", "denmark": "🇩🇰",
  "finland": "🇫🇮", "norway": "🇳🇴", "switzerland": "🇨🇭", "czech republic": "🇨🇿",
  "czechia": "🇨🇿", "romania": "🇷🇴", "hungary": "🇭🇺", "luxembourg": "🇱🇺",
  "greece": "🇬🇷", "croatia": "🇭🇷", "slovakia": "🇸🇰", "slovenia": "🇸🇮",
  "bulgaria": "🇧🇬", "estonia": "🇪🇪", "latvia": "🇱🇻", "lithuania": "🇱🇹",
  "canada": "🇨🇦", "australia": "🇦🇺", "japan": "🇯🇵", "india": "🇮🇳",
  "singapore": "🇸🇬", "mexico": "🇲🇽", "brazil": "🇧🇷",
};

function getCountryFlag(shippingCountry) {
  return COUNTRY_FLAGS[(shippingCountry || "").toLowerCase()] || "🌍";
}

function detectCountry(shippingCountry) {
  const c = (shippingCountry || "").toLowerCase();
  if (c === "united kingdom" || c === "gb" || c === "uk" || c === "great britain") return "uk";
  if (c === "australia" || c === "au") return "uk";
  if (c === "united states" || c === "us" || c === "usa" || !c) return "us";
  return "eu";
}

function showCountryActions(shippingCountry, hasAutopilot) {
  const country = detectCountry(shippingCountry);
  _currentCountry = country;
  const flag = getCountryFlag(shippingCountry);

  orderActionsUs.classList.add("hidden");
  orderActionsUk.classList.add("hidden");
  orderActionsEu.classList.add("hidden");

  if (country === "uk") {
    orderActionsUk.classList.remove("hidden");
    const c = (shippingCountry || "").toLowerCase();
    const label = (c === "australia" || c === "au") ? (shippingCountry || "").trim() : "UK";
    countryBanner.textContent = `${flag} ${label} Order`;
    countryBanner.className = "country-banner country-uk";
  } else if (country === "eu") {
    orderActionsEu.classList.remove("hidden");
    const displayName = (shippingCountry || "").trim();
    countryBanner.textContent = `${flag} ${displayName} Order`;
    countryBanner.className = "country-banner country-eu";
  } else {
    orderActionsUs.classList.remove("hidden");
    countryBanner.textContent = `${flag} US Order`;
    countryBanner.className = "country-banner country-us";
    autopilotBtnUs.classList.remove("hidden");
  }

}

// ── Inline address panel (Ticket Creator tab) ─────────────────────────────────

const addressPanel        = document.getElementById("addressPanel");
const addressPanelSpinner = document.getElementById("addressPanelSpinner");
const addressPanelPreview = document.getElementById("addressPanelPreview");
const addressPanelError   = document.getElementById("addressPanelError");
const addressPanelBtns    = document.getElementById("addressPanelBtns");
const addressPanelSuccess = document.getElementById("addressPanelSuccess");

let _addrCache      = null;  // cached recipient for current order
let _addrCacheOrder = null;  // which order the cache belongs to

async function handleAddressClick(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) return;

  const isOpen = !addressPanel.classList.contains("hidden");

  if (isOpen) {
    addressPanel.classList.add("hidden");
    btn.classList.remove("active");
    return;
  }

  addressPanel.classList.remove("hidden");
  btn.classList.add("active");

  if (_addrCache && _addrCacheOrder === orderNumber) {
    addrShowPreview(_addrCache);
    addressPanelBtns.classList.remove("hidden");
    return;
  }

  addressPanelError.classList.add("hidden");
  addressPanelPreview.classList.add("hidden");
  addressPanelBtns.classList.add("hidden");
  addressPanelSuccess.classList.add("hidden");
  addressPanelSpinner.classList.remove("hidden");

  try {
    const res  = await fetch(`${BASE_URL}/recipient?orderNumber=${encodeURIComponent(orderNumber)}`);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Failed to fetch recipient");
    if (data.phone) data.phone = data.phone.replace(/^\+1[\s-]*/, "");
    _addrCache      = data;
    _addrCacheOrder = orderNumber;
    addrShowPreview(data);
    addressPanelBtns.classList.remove("hidden");
  } catch (e) {
    addressPanelError.textContent = e.message;
    addressPanelError.classList.remove("hidden");
  } finally {
    addressPanelSpinner.classList.add("hidden");
  }
}

const addressBtnEu = document.getElementById("addressBtnEu");
addressBtnUs.addEventListener("click", () => handleAddressClick(addressBtnUs));
addressBtnUk.addEventListener("click", () => handleAddressClick(addressBtnUk));
addressBtnEu.addEventListener("click", () => handleAddressClick(addressBtnEu));

// Clear cache when order number changes
orderInput.addEventListener("input", () => {
  _addrCache = null;
  _addrCacheOrder = null;
  addressPanel.classList.add("hidden");
  addressBtnUs.classList.remove("active");
  addressBtnUk.classList.remove("active");
  addressBtnEu.classList.remove("active");
});

function addrShowPreview(r) {
  addressPanelPreview.innerHTML = `
    <div class="bhfill-preview-name">${r.first_name} ${r.last_name}</div>
    <div class="bhfill-preview-dim">${r.org_name || ""}</div>
    <div class="bhfill-preview-dim">${r.email}</div>
    <div>${r.address1}${r.address2 ? ", " + r.address2 : ""}</div>
    <div>${r.city}, ${r.state} ${r.zip}</div>
    <div class="bhfill-preview-dim">${r.phone}</div>
  `;
  addressPanelPreview.classList.remove("hidden");
}

// Sends a fill message to a tab's content script.
// If the content script isn't running (tab opened before extension loaded, or
// orphaned after extension reload), injects the script on demand and retries.
async function sendFillMessage(tabId, type, recipient) {
  const fileMap = {
    "SCOUT_FILL_TD":     "td_autofill.js",
    "SCOUT_FILL_BH":     "bh_autofill.js",
    "SCOUT_FILL_INGRAM":  "ingram_autofill.js",
    "SCOUT_FILL_BECHTLE": "bechtle_autofill.js",
  };

  async function tryFrame(fid) {
    try {
      return await _ext.call('tabs.sendMessage', { tabId, message: { type, recipient }, options: { frameId: fid } });
    } catch (e) {
      if (!e.message.includes("Could not establish connection")) throw e;
      const file = fileMap[type];
      if (!file) throw e;
      await _ext.call('scripting.executeScript', { target: { tabId, frameIds: [fid] }, files: [file] });
      await new Promise(r => setTimeout(r, 150));
      return await _ext.call('tabs.sendMessage', { tabId, message: { type, recipient }, options: { frameId: fid } });
    }
  }

  // Non-TD vendors: always main frame
  if (type !== "SCOUT_FILL_TD") {
    return tryFrame(0);
  }

  // TD Synnex: try every accessible frame; return the first that fills > 0 fields
  let frameIds = [0];
  try {
    const frames = await _ext.call('scripting.enumFrames', { tabId });
    frameIds = frames.map(f => f.frameId);
  } catch (_) { /* fall back to [0] */ }

  let lastResult = null;
  for (const fid of frameIds) {
    try {
      const r = await tryFrame(fid);
      if (r && r.filled > 0) return r;
      if (!lastResult) lastResult = r;
    } catch (_) { /* skip inaccessible frames */ }
  }
  return lastResult || { ok: false, filled: 0, missed: [], error: "Nothing filled in any frame" };
}

async function addrFill(vendor) {
  if (!_addrCache) return;
  addressPanelError.classList.add("hidden");
  addressPanelSuccess.classList.add("hidden");
  try {
    let tabs, msgType, label;
    if (vendor === "bh") {
      tabs    = await _ext.call('tabs.query', { url: "*://*.bhphotovideo.com/*" });
      msgType = "SCOUT_FILL_BH";
      label   = "BH Photo";
    } else if (vendor === "td") {
      tabs    = await _ext.call('tabs.query', { url: "*://partnerfirst.us.tdsynnex.com/*" });
      msgType = "SCOUT_FILL_TD";
      label   = "TD Synnex";
    } else if (vendor === "ingram") {
      tabs    = await _ext.call('tabs.query', { url: "*://*.ingrammicro.com/*" });
      msgType = "SCOUT_FILL_INGRAM";
      label   = "Ingram Micro";
    } else {
      tabs    = await _ext.call('tabs.query', { url: "*://*.bechtle.com/*" });
      msgType = "SCOUT_FILL_BECHTLE";
      label   = "Bechtle";
    }
    if (!tabs.length) throw new Error(`No ${label} tab found — open the checkout page first.`);
    const fillResult = await sendFillMessage(tabs[0].id, msgType, _addrCache);
    if (!fillResult || fillResult.ok === false) {
      throw new Error(fillResult?.error || "Fill script failed — check the browser console on the TD Synnex tab.");
    }
    if (fillResult.filled === 0) {
      throw new Error(`Nothing was filled — the page structure may have changed. Missed: ${(fillResult.missed || []).join(", ") || "all fields"}`);
    }
    const missedNote = fillResult?.missed?.length ? ` (missed: ${fillResult.missed.join(", ")})` : "";
    addressPanelSuccess.textContent = `✓ Filled! Check the ${label} checkout tab.${missedNote}`;
    addressPanelSuccess.classList.remove("hidden");
  } catch (e) {
    addressPanelError.textContent = e.message;
    addressPanelError.classList.remove("hidden");
  }
}

document.getElementById("ticketBhBtn").addEventListener("click",     () => addrFill("bh"));
document.getElementById("ticketTdBtn").addEventListener("click",     () => addrFill("td"));
document.getElementById("ticketIngramBtn").addEventListener("click",  () => addrFill("ingram"));
document.getElementById("ticketBechtleBtn").addEventListener("click", () => addrFill("bechtle"));

try { const _s = sessionStorage.getItem("lastOrder"); if (_s) orderInput.value = _s; } catch (_) {}

// Clear CTO alert + country actions when user types a different order number
orderInput.addEventListener("input", () => {
  if (orderInput.value.trim() !== _lastFetchedOrder) {
    ctoAlert.classList.add("hidden");
    enterpriseWarrantyAlert.classList.add("hidden");
    orderActionsUs.classList.add("hidden");
    orderActionsUk.classList.add("hidden");
    orderActionsEu.classList.add("hidden");
    countryBanner.classList.add("hidden");
  }
});

// Arrow button and Enter: fetch order info + detect country + show CTO alert
orderInput.addEventListener("keydown", (e) => { if (e.key === "Enter") fetchAndCheck(); });
checkBtn.addEventListener("click", fetchAndCheck);

async function fetchAndCheck() {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  try { sessionStorage.setItem("lastOrder", orderNumber); } catch (_) {}

  _lastOrderInfo    = null;
  _lastFetchedOrder = null;

  checkBtn.disabled = true;
  spinner.classList.remove("hidden");
  errorBox.classList.add("hidden");
  ctoAlert.classList.add("hidden");
  enterpriseWarrantyAlert.classList.add("hidden");
  v2AltBox.classList.add("hidden");
  v2AltInput.value = "";
  v2ItemSelector.classList.add("hidden");

  orderActionsUs.classList.add("hidden");
  orderActionsUk.classList.add("hidden");
  orderActionsEu.classList.add("hidden");
  countryBanner.classList.add("hidden");
  emailRatingPanel.classList.add("hidden");
  currentEmailContext = null;

  try {
    const resp = await fetch(`${BASE_URL}/order-info`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ order_number: orderNumber }),
    });
    const data = await resp.json();

    if (data.error) {
      showEnterpriseWarrantyAlert(data);
      showError(data.error);
      return;
    }

    _lastOrderInfo    = data;
    _lastFetchedOrder = orderNumber;
    _selectedItems    = [];

    showCtoAlert(data);
    showEnterpriseWarrantyAlert(data);
    showCountryActions(data.shipping_country, data.has_autopilot);

  } catch (_) {
    showError("Cannot connect to server. Make sure it's running:\n  python3 ~/Claude_projects/scout_app.py");
  } finally {
    spinner.classList.add("hidden");
    checkBtn.disabled = false;
  }
}

function showCtoAlert(data) {
  if (!data.cto_detected) {
    ctoAlert.classList.add("hidden");
    return;
  }

  const mpns     = (data.cto_mpns || []).join(", ");
  const approved = data.lead_time_approved;

  ctoAlert.className   = approved ? "cto-alert cto-approved" : "cto-alert cto-warning";
  ctoAlert.textContent = approved
    ? `This is a CTO device with an approved lead time, please proceed.${mpns ? " MPN: " + mpns : ""}`
    : `⚠️ CTO — lead time not approved. A ticket is required.${mpns ? " MPN: " + mpns : ""}`;
}

function showEnterpriseWarrantyAlert(data) {
  if (!data.enterprise_warranty) {
    enterpriseWarrantyAlert.classList.add("hidden");
    return;
  }
  enterpriseWarrantyAlert.className = "cto-alert enterprise-warranty";
  enterpriseWarrantyAlert.textContent = `Enterprise Warranty Required — ${data.enterprise_warranty_notes}`;
}

// ── Order Notes handler ──────────────────────────────────────────────────────

async function handleOrderNote(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  btn.disabled    = true;
  btn.textContent = "Loading…";
  errorBox.classList.add("hidden");
  ctoAlert.classList.add("hidden");

  try {
    const resp = await fetch(`${BASE_URL}/order-note`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ order_number: orderNumber }),
    });
    const data = await resp.json();
    btn.disabled    = false;
    btn.textContent = "📝 Order Notes";

    if (data.error) {
      showEnterpriseWarrantyAlert(data);
      showError(data.error);
      return;
    }

    if (data.cto_detected) {
      const mpns     = (data.cto_mpns || []).join(", ");
      const approved = data.lead_time_approved;
      ctoAlert.className   = approved ? "cto-alert cto-approved" : "cto-alert cto-warning";
      ctoAlert.textContent = approved
        ? `This is a CTO device with an approved lead time, please proceed.${mpns ? " MPN: " + mpns : ""}`
        : `⚠️ CTO — lead time not approved. A ticket is required.${mpns ? " MPN: " + mpns : ""}`;
    }

    showEnterpriseWarrantyAlert(data);

    navigator.clipboard.writeText(data.note).then(() => {
      btn.textContent      = "✓ Copied!";
      btn.style.background = "#14532d";
      setTimeout(() => {
        btn.textContent      = "📝 Order Notes";
        btn.style.background = "";
      }, 2000);
    });
  } catch (_) {
    btn.disabled    = false;
    btn.textContent = "📝 Order Notes";
    showError("Cannot connect to server.");
  }
}

const orderNoteBtnEu = document.getElementById("orderNoteBtnEu");
orderNoteBtnUs.addEventListener("click", () => handleOrderNote(orderNoteBtnUs));
orderNoteBtnUk.addEventListener("click", () => handleOrderNote(orderNoteBtnUk));
orderNoteBtnEu.addEventListener("click", () => handleOrderNote(orderNoteBtnEu));

// ── Email accuracy rating ─────────────────────────────────────────────────────

const emailRatingPanel       = document.getElementById("emailRatingPanel");
const emailRatingRegionLabel = document.getElementById("emailRatingRegionLabel");
const emailRatingGreenBtn    = document.getElementById("emailRatingGreenBtn");
const emailRatingOrangeBtn   = document.getElementById("emailRatingOrangeBtn");
const emailRatingReasonRow   = document.getElementById("emailRatingReasonRow");
const emailRatingReasonSelect = document.getElementById("emailRatingReasonSelect");
const emailRatingAddReasonBtn = document.getElementById("emailRatingAddReasonBtn");
const emailRatingSubmitBtn   = document.getElementById("emailRatingSubmitBtn");
const emailRatingNewReasonRow = document.getElementById("emailRatingNewReasonRow");
const emailRatingNewReasonInput = document.getElementById("emailRatingNewReasonInput");
const emailRatingNewReasonSaveBtn = document.getElementById("emailRatingNewReasonSaveBtn");
const emailRatingNewReasonCancelBtn = document.getElementById("emailRatingNewReasonCancelBtn");
const emailRatingConfirm     = document.getElementById("emailRatingConfirm");

let currentEmailContext = null; // { orderNumber, region }
let reasonCodesLoaded = false;

async function loadReasonCodes() {
  try {
    const resp = await fetch(`${BASE_URL}/email-reason-codes`);
    const data = await resp.json();
    emailRatingReasonSelect.innerHTML = `<option value="">Select reason…</option>`;
    (data.codes || []).forEach(code => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = code;
      emailRatingReasonSelect.appendChild(opt);
    });
    reasonCodesLoaded = true;
  } catch (_) { /* leave dropdown as-is */ }
}

function resetEmailRatingPanel() {
  emailRatingReasonRow.classList.add("hidden");
  emailRatingNewReasonRow.classList.add("hidden");
  emailRatingConfirm.classList.add("hidden");
  emailRatingSubmitBtn.disabled = true;
  emailRatingReasonSelect.value = "";
  emailRatingGreenBtn.classList.remove("selected");
  emailRatingOrangeBtn.classList.remove("selected");
}

function showEmailRatingPanel(region, orderNumber) {
  currentEmailContext = { orderNumber, region };
  emailRatingRegionLabel.textContent = region;
  resetEmailRatingPanel();
  emailRatingPanel.classList.remove("hidden");
  if (!reasonCodesLoaded) loadReasonCodes();
}

async function submitEmailRating(status, reasonCode) {
  if (!currentEmailContext) return;
  try {
    await fetch(`${BASE_URL}/email-feedback`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        order_number: currentEmailContext.orderNumber,
        region:       currentEmailContext.region,
        status,
        reason_code:  reasonCode || "",
      }),
    });
    emailRatingConfirm.textContent = status === "green" ? "✓ Logged as accurate" : "✓ Logged for review";
    emailRatingConfirm.classList.remove("hidden");
    emailRatingReasonRow.classList.add("hidden");
  } catch (_) {
    emailRatingConfirm.textContent = "Could not save — try again.";
    emailRatingConfirm.classList.remove("hidden");
  }
}

emailRatingGreenBtn.addEventListener("click", () => {
  emailRatingGreenBtn.classList.add("selected");
  emailRatingOrangeBtn.classList.remove("selected");
  emailRatingReasonRow.classList.add("hidden");
  emailRatingNewReasonRow.classList.add("hidden");
  submitEmailRating("green", "");
});

emailRatingOrangeBtn.addEventListener("click", () => {
  emailRatingOrangeBtn.classList.add("selected");
  emailRatingGreenBtn.classList.remove("selected");
  emailRatingConfirm.classList.add("hidden");
  emailRatingReasonRow.classList.remove("hidden");
  if (!reasonCodesLoaded) loadReasonCodes();
});

emailRatingReasonSelect.addEventListener("change", () => {
  emailRatingSubmitBtn.disabled = !emailRatingReasonSelect.value;
});

emailRatingSubmitBtn.addEventListener("click", () => {
  submitEmailRating("orange", emailRatingReasonSelect.value);
});

emailRatingAddReasonBtn.addEventListener("click", () => {
  emailRatingNewReasonRow.classList.remove("hidden");
  emailRatingNewReasonInput.value = "";
  emailRatingNewReasonInput.focus();
});

emailRatingNewReasonCancelBtn.addEventListener("click", () => {
  emailRatingNewReasonRow.classList.add("hidden");
});

emailRatingNewReasonSaveBtn.addEventListener("click", async () => {
  const code = emailRatingNewReasonInput.value.trim();
  if (!code) return;
  try {
    const resp = await fetch(`${BASE_URL}/email-reason-codes`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ code }),
    });
    const data = await resp.json();
    emailRatingReasonSelect.innerHTML = `<option value="">Select reason…</option>`;
    (data.codes || []).forEach(c => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      emailRatingReasonSelect.appendChild(opt);
    });
    emailRatingReasonSelect.value = code;
    emailRatingSubmitBtn.disabled = false;
    emailRatingNewReasonRow.classList.add("hidden");
  } catch (_) { /* leave row open so Sara can retry */ }
});


// ── Auto-Quote Draft handler ───────────────────────────────────────────────

async function handleAutoQuote(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  const savedLabel = btn.textContent;
  btn.disabled    = true;
  btn.textContent = "Creating draft…";
  errorBox.classList.add("hidden");

  try {
    const resp = await fetch(`${BASE_URL}/auto-quote`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ order_number: orderNumber }),
    });
    const data = await resp.json();
    btn.disabled = false;

    if (data.error) {
      btn.textContent = savedLabel;
      showError(data.error);
      return;
    }

    btn.textContent      = "✓ Draft created!";
    btn.style.background = "#14532d";
    setTimeout(() => {
      btn.textContent      = savedLabel;
      btn.style.background = "";
    }, 3000);
  } catch (_) {
    btn.disabled    = false;
    btn.textContent = savedLabel;
    showError("Cannot connect to server.");
  }
}

autoQuoteBtnUs.addEventListener("click", () => handleAutoQuote(autoQuoteBtnUs));
autoQuoteBtnUk.addEventListener("click", () => handleAutoQuote(autoQuoteBtnUk));
autoQuoteBtnEu.addEventListener("click", () => handleAutoQuote(autoQuoteBtnEu));

// ── Confirm Alt Approval ────────────────────────────────────────────────────
const altConfirmBtnUk = document.getElementById("altConfirmBtnUk");
const altConfirmBtnEu = document.getElementById("altConfirmBtnEu");
const altResultBox    = document.getElementById("altResultBox");

async function handleAltConfirm(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Enter an order number first."); return; }
  const savedLabel = btn.textContent;
  btn.disabled    = true;
  btn.textContent = "Processing…";
  errorBox.classList.add("hidden");

  try {
    const resp = await fetch(`${BASE_URL}/process-alt-approval`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ order_number: orderNumber }),
    });
    const data = await resp.json();
    btn.disabled = false;

    if (data.error) {
      btn.textContent = savedLabel;
      showError(data.error);
      return;
    }

    btn.textContent      = "✓ Done!";
    btn.style.background = "#14532d";
    altResultBox.classList.remove("hidden");
    altResultBox.textContent = data.order_notes || "Processed but no notes returned.";
    setTimeout(() => {
      btn.textContent      = savedLabel;
      btn.style.background = "";
    }, 5000);
  } catch (_) {
    btn.disabled    = false;
    btn.textContent = savedLabel;
    showError("Cannot connect to server.");
  }
}

altConfirmBtnUk.addEventListener("click", () => handleAltConfirm(altConfirmBtnUk));
altConfirmBtnEu.addEventListener("click", () => handleAltConfirm(altConfirmBtnEu));

function showError(message) {
  spinner.classList.add("hidden");
  errorBox.classList.remove("hidden");
  errorBox.textContent = message;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// Group items by variant_id, summing quantities for identical SKUs
function groupItems(items) {
  const groupMap  = new Map();
  const groupOrder = [];
  items.forEach(item => {
    const key = item.variant_id || item.product_name || "";
    if (!groupMap.has(key)) {
      groupMap.set(key, Object.assign({}, item, { quantity: item.quantity || 1 }));
      groupOrder.push(key);
    } else {
      groupMap.get(key).quantity += (item.quantity || 1);
    }
  });
  return groupOrder.map(k => groupMap.get(k));
}

// ══════════════════════════════════════════════════════════════════════════════
// FINANCE PANEL
// ══════════════════════════════════════════════════════════════════════════════

const financePanel          = document.getElementById("financePanel");
const financeClose          = document.getElementById("financeClose");
const financeOrderNum       = document.getElementById("financeOrderNum");
const financeOrg            = document.getElementById("financeOrg");
const financeNotesInput     = document.getElementById("financeNotesInput");
const financeSubmitBtn      = document.getElementById("financeSubmitBtn");
const financeStatus         = document.getElementById("financeStatus");
const financeSuccess        = document.getElementById("financeSuccess");
const financeModeCheckout   = document.getElementById("financeModeCheckout");
const financeModeHold       = document.getElementById("financeModeHold");
const financeCheckoutMode   = document.getElementById("financeCheckoutMode");
const financeHoldMode       = document.getElementById("financeHoldMode");
const financeHoldItems      = document.getElementById("financeHoldItems");
const financeHoldSubmitBtn  = document.getElementById("financeHoldSubmitBtn");
const financeHoldStatus     = document.getElementById("financeHoldStatus");

let _activeFinanceBtn = null;

// Mode tab switching
financeModeCheckout.addEventListener("click", () => {
  financeModeCheckout.classList.add("active");
  financeModeHold.classList.remove("active");
  financeCheckoutMode.classList.remove("hidden");
  financeHoldMode.classList.add("hidden");
});

financeModeHold.addEventListener("click", () => {
  financeModeHold.classList.add("active");
  financeModeCheckout.classList.remove("active");
  financeHoldMode.classList.remove("hidden");
  financeCheckoutMode.classList.add("hidden");
  renderHoldItems();
});

function renderHoldItems() {
  const items = groupItems((_lastOrderInfo && _lastOrderInfo.items) || []);
  if (!items.length) {
    financeHoldItems.innerHTML = '<p class="finance-notes-label" style="color:#888">No items loaded — fetch an order first.</p>';
    return;
  }
  financeHoldItems.innerHTML = items.map((item, i) => {
    const name = item.product_name || `Item ${i + 1}`;
    const maxQty = item.quantity || 1;
    return `
      <div class="finance-hold-item" data-index="${i}">
        <label class="finance-hold-check">
          <input type="checkbox" class="hold-cb" data-index="${i}" />
          <span class="finance-hold-name">${escapeHtml(name)}</span>
        </label>
        <div class="finance-hold-fields hidden">
          <div class="finance-hold-qty-row">
            <span>Qty on hold:</span>
            <input type="number" class="finance-hold-qty" min="1" max="${maxQty}" value="${maxQty}" data-max="${maxQty}" />
            <span>of ${maxQty}</span>
          </div>
          <input type="text" class="finance-hold-reason" placeholder="Reason (e.g. awaiting stock, color swap)" />
        </div>
      </div>
    `;
  }).join("");

  // Show/hide fields when checkbox toggled
  financeHoldItems.querySelectorAll(".hold-cb").forEach(cb => {
    cb.addEventListener("change", () => {
      const fields = cb.closest(".finance-hold-item").querySelector(".finance-hold-fields");
      fields.classList.toggle("hidden", !cb.checked);
    });
  });
}

async function handleFinanceClick(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  _activeFinanceBtn = btn;

  if (_lastFetchedOrder !== orderNumber || !_lastOrderInfo) {
    btn.disabled = true;
    await fetchAndCheck();
    btn.disabled = false;
    if (!_lastOrderInfo) return;
  }

  financeOrderNum.textContent  = orderNumber;
  financeOrg.textContent       = (_lastOrderInfo && _lastOrderInfo.org_name) || "—";
  financeSubmitBtn.disabled    = false;
  financeSubmitBtn.textContent = "Send to Sheet →";
  financeStatus.textContent    = "";
  financeHoldStatus.textContent = "";
  financeSuccess.classList.add("hidden");

  financeModeCheckout.classList.add("active");
  financeModeHold.classList.remove("active");
  financeCheckoutMode.classList.remove("hidden");
  financeHoldMode.classList.add("hidden");

  financePanel.classList.remove("hidden");
  financeNotesInput.focus();
}

financeClose.addEventListener("click", () => {
  financePanel.classList.add("hidden");
});

financeSubmitBtn.addEventListener("click", async () => {
  const notes = financeNotesInput.value.trim();
  if (!notes) { financeStatus.textContent = "Paste the order notes first."; return; }

  const totalItems = groupItems((_lastOrderInfo && _lastOrderInfo.items) || []).length;

  financeSubmitBtn.disabled    = true;
  financeSubmitBtn.textContent = "Sending…";
  financeStatus.textContent    = "";

  try {
    const resp = await fetch(`${BASE_URL}/send-to-finance`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_number:      orderInput.value.trim(),
        proc_manager_name: (_lastOrderInfo && _lastOrderInfo.procurement_manager_name) || "",
        notes_text:        notes,
        total_items:       totalItems,
      }),
    });
    const data = await resp.json();

    if (data.ok) {
      financePanel.classList.add("hidden");
      financeSuccess.textContent = `✓ Sent to finance sheet! (${data.rows_added} row${data.rows_added !== 1 ? "s" : ""})`;
      financeSuccess.classList.remove("hidden");
      if (_activeFinanceBtn) {
        _activeFinanceBtn.textContent = "✓ Sent!";
        setTimeout(() => {
          _activeFinanceBtn.textContent = "💸 Finance";
          financeSuccess.classList.add("hidden");
        }, 3000);
      }
    } else {
      financeSubmitBtn.disabled    = false;
      financeSubmitBtn.textContent = "Send to Sheet →";
      financeStatus.textContent    = data.error || "Failed — check that FINANCE_SHEET_ID is set.";
    }
  } catch (_) {
    financeSubmitBtn.disabled    = false;
    financeSubmitBtn.textContent = "Send to Sheet →";
    financeStatus.textContent    = "Cannot connect to server.";
  }
});

financeHoldSubmitBtn.addEventListener("click", async () => {
  const checkedItems = financeHoldItems.querySelectorAll(".hold-cb:checked");
  if (!checkedItems.length) {
    financeHoldStatus.textContent = "Select at least one item on hold.";
    return;
  }

  const allGrouped = groupItems((_lastOrderInfo && _lastOrderInfo.items) || []);
  const totalItems = allGrouped.length;

  const holdPayload = [];
  checkedItems.forEach(cb => {
    const idx    = parseInt(cb.dataset.index, 10);
    const item   = allGrouped[idx];
    if (!item) return;
    const parent = cb.closest(".finance-hold-item");
    const qty    = parseInt(parent.querySelector(".finance-hold-qty").value, 10) || 1;
    const reason = parent.querySelector(".finance-hold-reason").value.trim();
    holdPayload.push({
      description: item.product_name || `Item ${idx + 1}`,
      qty,
      reason,
    });
  });

  financeHoldSubmitBtn.disabled    = true;
  financeHoldSubmitBtn.textContent = "Sending…";
  financeHoldStatus.textContent    = "";

  try {
    const resp = await fetch(`${BASE_URL}/send-hold-to-finance`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_number:      orderInput.value.trim(),
        proc_manager_name: (_lastOrderInfo && _lastOrderInfo.procurement_manager_name) || "",
        hold_items:        holdPayload,
        total_items:       totalItems,
      }),
    });
    const data = await resp.json();

    if (data.ok) {
      financePanel.classList.add("hidden");
      financeSuccess.textContent = `✓ Hold logged (${data.rows_added} item${data.rows_added !== 1 ? "s" : ""})`;
      financeSuccess.classList.remove("hidden");
      if (_activeFinanceBtn) {
        _activeFinanceBtn.textContent = "✓ Logged!";
        setTimeout(() => {
          _activeFinanceBtn.textContent = "💸 Finance";
          financeSuccess.classList.add("hidden");
        }, 3000);
      }
    } else {
      financeHoldSubmitBtn.disabled    = false;
      financeHoldSubmitBtn.textContent = "Submit Hold →";
      financeHoldStatus.textContent    = data.error || "Failed.";
    }
  } catch (_) {
    financeHoldSubmitBtn.disabled    = false;
    financeHoldSubmitBtn.textContent = "Submit Hold →";
    financeHoldStatus.textContent    = "Cannot connect to server.";
  }
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;");
}

// ══════════════════════════════════════════════════════════════════════════════
// TICKETS V2 — button lives inside the Ticket Creator tab, shares the same
// order number input and _lastOrderInfo as V1.
// ══════════════════════════════════════════════════════════════════════════════

const v2ItemSelector   = document.getElementById("v2ItemSelector");
const v2ItemList       = document.getElementById("v2ItemList");
const v2ItemConfirmBtn = document.getElementById("v2ItemConfirmBtn");
const v2AltBox         = document.getElementById("v2AltBox");
const v2AltInput       = document.getElementById("v2AltInput");
const v2ReviewBtn      = document.getElementById("v2ReviewBtn");
const v2ParseSpinner   = document.getElementById("v2ParseSpinner");
const v2AltError       = document.getElementById("v2AltError");

let _v2SelectedItems = [];
let _v2UniqueItems   = [];

async function handleV2TicketClick(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  v2ItemSelector.classList.add("hidden");
  v2AltBox.classList.add("hidden");
  v2AltError.classList.add("hidden");
  errorBox.classList.add("hidden");
  _v2SelectedItems = [];

  if (_lastFetchedOrder !== orderNumber || !_lastOrderInfo) {
    btn.disabled = true;
    await fetchAndCheck();
    btn.disabled = false;
    if (!_lastOrderInfo) return;
  }

  const uniqueItems = groupItems(_lastOrderInfo.items || []);
  v2ShowItemSelector(uniqueItems);
}

const v2TicketBtnEu = document.getElementById("v2TicketBtnEu");
v2TicketBtnUs.addEventListener("click", () => handleV2TicketClick(v2TicketBtnUs));
v2TicketBtnUk.addEventListener("click", () => handleV2TicketClick(v2TicketBtnUk));
v2TicketBtnEu.addEventListener("click", () => handleV2TicketClick(v2TicketBtnEu));

// ── Manual AR Ticket ─────────────────────────────────────────────────────────
const manualArBtnUs = document.getElementById("manualArBtnUs");
const manualArBtnUk = document.getElementById("manualArBtnUk");
const manualArBtnEu = document.getElementById("manualArBtnEu");

function handleManualArClick() {
  if (!_lastOrderInfo) return;
  const info = _lastOrderInfo;
  const formBase = "https://airtable.com/appnu2ZO4IDLIErUO/shrFlB1YyS0mmyxlA";
  const params = new URLSearchParams();
  params.set("prefill_Placed By", info.procurement_manager_name || "Sara Vargas");
  params.set("prefill_Action Request Type", "Alternate Approval");
  if (info.order_manager_name) {
    params.set("prefill_Request for", info.order_manager_name);
  }
  params.set("prefill_Order #", info.order_number);
  params.set("prefill_Alternate Reason", "Out of stock / backordered");
  params.set("prefill_Alternate Sub-reason", "Model unavailable");
  params.set("prefill_Priority", "High");
  params.set("prefill_Escalation (Y/N)", "No");
  params.set("prefill_Summary/Subject", `${info.order_number} | Alternative Approval`);
  if (info.org_name) {
    params.set("prefill_Organization", info.org_name);
  }
  window.open(`${formBase}?${params.toString()}`, "_blank");
}

manualArBtnUs.addEventListener("click", handleManualArClick);
manualArBtnUk.addEventListener("click", handleManualArClick);
manualArBtnEu.addEventListener("click", handleManualArClick);

function v2ShowItemSelector(items) {
  _v2UniqueItems    = items;
  v2ItemList.innerHTML = "";
  items.forEach((item, i) => {
    const label = document.createElement("label");
    label.className = "item-checkbox-row";
    const cb = document.createElement("input");
    cb.type    = "checkbox";
    cb.value   = String(i);
    cb.checked = true;
    const name = item.product_name || `Item ${i + 1}`;
    const mpn  = item.mpn ? ` (${item.mpn})` : "";
    label.appendChild(cb);
    label.appendChild(document.createTextNode(` ${name}${mpn}`));
    v2ItemList.appendChild(label);
  });
  v2ItemSelector.classList.remove("hidden");
}

v2ItemConfirmBtn.addEventListener("click", () => {
  const checks = v2ItemList.querySelectorAll("input[type=checkbox]");
  _v2SelectedItems = [];
  checks.forEach((cb, i) => {
    if (cb.checked) _v2SelectedItems.push(_v2UniqueItems[i]);
  });
  if (!_v2SelectedItems.length) { showError("Please select at least one item."); return; }
  v2ItemSelector.classList.add("hidden");
  v2AltBox.classList.remove("hidden");
});

v2ReviewBtn.addEventListener("click", async () => {
  const orderNumber = orderInput.value.trim();
  const altText     = v2AltInput.value.trim();

  if (!_lastOrderInfo) { showError("Please fetch an order first."); return; }

  v2ReviewBtn.disabled = true;
  v2ParseSpinner.classList.remove("hidden");
  v2AltError.classList.add("hidden");

  try {
    let parsed = {};
    if (altText) {
      const resp = await fetch(`${BASE_URL}/parse-alt-description`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ text: altText, country: _currentCountry || "" }),
      });
      parsed = await resp.json();
    }

    const primaryItem = _v2SelectedItems[0] || {};
    const altMpn      = parsed.mpn || primaryItem.mpn || "";
    const altType     = altMpn.toUpperCase().startsWith("Z")
      ? "CTO device"
      : "Out of stock / backordered";

    const reviewData = {
      order_number:        orderNumber,
      org_name:            _lastOrderInfo.org_name || "",
      order_manager_name:  _lastOrderInfo.order_manager_name || "",
      order_manager_email: _lastOrderInfo.order_manager_email || "",
      procurement_manager_email: _lastOrderInfo.procurement_manager_email || "",
      procurement_manager_name:  _lastOrderInfo.procurement_manager_name || "",
      is_rush:             _lastOrderInfo.is_rush || false,
      requested_sku:       primaryItem.sku || "",
      multiple_skus:       _v2SelectedItems.length > 1,
      alt_type:            altType,
      alt_subtype:         "Model unavailable",
      device_type:         v2DeriveDeviceType(primaryItem.product_name || ""),
      make:                parsed.make || v2DeriveMake(primaryItem.product_name || ""),
      model:               parsed.model || "",
      display_size:        parsed.display_size || "",
      processor:           parsed.processor || "",
      memory:              parsed.memory || "",
      storage:             parsed.storage || "",
      color:               parsed.color || "",
      mpn:                 parsed.mpn || "",
      price:               parsed.price || "",
      keyboard_language:   parsed.keyboard_language ?? (_currentCountry === "uk" ? "UK" : _currentCountry === "us" ? "US" : ""),
      sku_country:         parsed.sku_country ?? (_currentCountry === "uk" ? "UK" : _currentCountry === "us" ? "US" : ""),
    };

    const _sessionResp = await fetch(`${BASE_URL}/review-session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reviewData),
    });
    const { session_id } = await _sessionResp.json();
    window.open(`${BASE_URL}/review-v2?session=${session_id}`, '_blank');

  } catch (_) {
    v2AltError.textContent = "Failed to parse or open review. Please try again.";
    v2AltError.classList.remove("hidden");
  } finally {
    v2ParseSpinner.classList.add("hidden");
    v2ReviewBtn.disabled = false;
  }
});

function v2DeriveDeviceType(productName) {
  const n = (productName || "").toLowerCase();
  if (n.includes("macbook") || n.includes("laptop"))   return "Laptop";
  if (n.includes("ipad")    || n.includes("tablet"))   return "Tablet";
  if (n.includes("iphone")  || n.includes("phone"))    return "Mobile Phone";
  return "Other";
}

function v2DeriveMake(productName) {
  const n = (productName || "").toLowerCase();
  // Longest/most-specific brands checked first to avoid partial matches
  const brands = [
    ["western digital", "Western Digital"],
    ["sennheiser",      "Sennheiser"],
    ["plantronics",     "Plantronics"],
    ["steelseries",     "SteelSeries"],
    ["caldigit",        "CalDigit"],
    ["logitech",        "Logitech"],
    ["microsoft",       "Microsoft"],
    ["samsung",         "Samsung"],
    ["lenovo",          "Lenovo"],
    ["corsair",         "Corsair"],
    ["hyperx",          "HyperX"],
    ["kingston",        "Kingston"],
    ["seagate",         "Seagate"],
    ["synology",        "Synology"],
    ["ubiquiti",        "Ubiquiti"],
    ["elgato",          "Elgato"],
    ["macbook",         "Apple"],
    ["apple",           "Apple"],
    ["sony",            "Sony"],
    ["jabra",           "Jabra"],
    ["bose",            "Bose"],
    ["razer",           "Razer"],
    ["belkin",          "Belkin"],
    ["anker",           "Anker"],
    ["dell",            "Dell"],
    ["asus",            "Asus"],
    ["acer",            "Acer"],
    ["rode",            "Rode"],
    ["poly",            "Poly"],
    [" lg ",            "LG"],
    [" hp ",            "HP"],
  ];
  for (const [key, brand] of brands) {
    if (n.includes(key)) return brand;
  }
  return "";
}

// ══════════════════════════════════════════════════════════════════════════════
// PRICING APPROVAL — reuses item selector pattern, opens review_pricing page
// ══════════════════════════════════════════════════════════════════════════════

const pricingBtnUs           = document.getElementById("pricingBtnUs");
const pricingBtnUk           = document.getElementById("pricingBtnUk");
const pricingBtnEu           = document.getElementById("pricingBtnEu");
const pricingItemSelector    = document.getElementById("pricingItemSelector");
const pricingItemList        = document.getElementById("pricingItemList");
const pricingItemConfirmBtn  = document.getElementById("pricingItemConfirmBtn");

let _pricingUniqueItems = [];

async function handlePricingClick(btn) {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  pricingItemSelector.classList.add("hidden");
  errorBox.classList.add("hidden");

  if (_lastFetchedOrder !== orderNumber || !_lastOrderInfo) {
    btn.disabled = true;
    await fetchAndCheck();
    btn.disabled = false;
    if (!_lastOrderInfo) return;
  }

  const uniqueItems = groupItems(_lastOrderInfo.items || []);
  _pricingUniqueItems = uniqueItems;
  pricingItemList.innerHTML = "";
  uniqueItems.forEach((item, i) => {
    const label = document.createElement("label");
    label.className = "item-checkbox-row";
    const cb = document.createElement("input");
    cb.type    = "checkbox";
    cb.value   = String(i);
    cb.checked = true;
    const name = item.product_name || `Item ${i + 1}`;
    const sku  = item.sku ? ` (SKU ${item.sku})` : "";
    label.appendChild(cb);
    label.appendChild(document.createTextNode(` ${name}${sku}`));
    pricingItemList.appendChild(label);
  });
  pricingItemSelector.classList.remove("hidden");
}

pricingBtnUs.addEventListener("click", () => handlePricingClick(pricingBtnUs));
pricingBtnUk.addEventListener("click", () => handlePricingClick(pricingBtnUk));
pricingBtnEu.addEventListener("click", () => handlePricingClick(pricingBtnEu));

pricingItemConfirmBtn.addEventListener("click", async () => {
  const checks = pricingItemList.querySelectorAll("input[type=checkbox]");
  const selectedItems = [];
  checks.forEach((cb, i) => {
    if (cb.checked) selectedItems.push(_pricingUniqueItems[i]);
  });
  if (!selectedItems.length) { showError("Please select at least one item."); return; }

  pricingItemSelector.classList.add("hidden");

  const sessionData = {
    order_number:                orderInput.value.trim(),
    org_name:                    _lastOrderInfo.org_name || "",
    order_manager_name:          _lastOrderInfo.order_manager_name || "",
    order_manager_email:         _lastOrderInfo.order_manager_email || "",
    procurement_manager_email:   _lastOrderInfo.procurement_manager_email || "",
    is_rush:                     _lastOrderInfo.is_rush || false,
    items: selectedItems.map(it => ({
      sku:          it.sku || "",
      product_name: it.product_name || "",
    })),
  };

  try {
    const resp = await fetch(`${BASE_URL}/review-session`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(sessionData),
    });
    const { session_id } = await resp.json();
    window.open(`${BASE_URL}/review-pricing?session=${session_id}`, "_blank");
  } catch (_) {
    showError("Failed to open pricing review. Is the server running?");
  }
});

// ── Autopilot Form handler (US only) ────────────────────────────────────────

const autopilotBtnUs = document.getElementById("autopilotBtnUs");

autopilotBtnUs.addEventListener("click", async () => {
  const orderNumber = orderInput.value.trim();
  if (!orderNumber) { showError("Please enter an order number."); return; }

  autopilotBtnUs.disabled    = true;
  autopilotBtnUs.textContent = "Generating…";

  try {
    const resp = await fetch(`${BASE_URL}/autopilot-sheet`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ order_number: orderNumber }),
    });
    const data = await resp.json();

    autopilotBtnUs.disabled    = false;
    autopilotBtnUs.textContent = "📋 Generate Autopilot Form";

    if (data.error) { showError(data.error); return; }

    window.open(data.url, "_blank");
    autopilotBtnUs.textContent      = "✓ Opened!";
    autopilotBtnUs.style.background = "#14532d";
    setTimeout(() => {
      autopilotBtnUs.textContent      = "📋 Generate Autopilot Form";
      autopilotBtnUs.style.background = "";
    }, 2000);
  } catch (_) {
    autopilotBtnUs.disabled    = false;
    autopilotBtnUs.textContent = "📋 Generate Autopilot Form";
    showError("Cannot connect to server.");
  }
});

// ══════════════════════════════════════════════════════════════════════════════
// QUOTE VALIDATION
// ══════════════════════════════════════════════════════════════════════════════

const quotePanel         = document.getElementById("quotePanel");
const quoteClose         = document.getElementById("quoteClose");
const quoteItemSelector  = document.getElementById("quoteItemSelector");
const quoteItemList      = document.getElementById("quoteItemList");
const quoteTextInput     = document.getElementById("quoteTextInput");
const quoteDropZone      = document.getElementById("quoteDropZone");
const quoteFileInput     = document.getElementById("quoteFileInput");
const quoteFileName      = document.getElementById("quoteFileName");
const quoteSubmitBtn     = document.getElementById("quoteSubmitBtn");
const quoteStatus        = document.getElementById("quoteStatus");
const quoteSpinner       = document.getElementById("quoteSpinner");
const quoteError         = document.getElementById("quoteError");
const quoteResults       = document.getElementById("quoteResults");

let _quoteSelectedIndex = 0;
let _quoteFileB64       = null;

function handleValidateQuoteClick() {
  if (!_lastOrderInfo) {
    quoteError.textContent = "Fetch an order first.";
    quoteError.classList.remove("hidden");
    return;
  }
  const isOpen = !quotePanel.classList.contains("hidden");
  quotePanel.classList.toggle("hidden");
  if (!isOpen) _quotePopulateItems();
}

quoteClose.addEventListener("click", () => {
  quotePanel.classList.add("hidden");
});

function _quotePopulateItems() {
  const items = (_lastOrderInfo && _lastOrderInfo.items) || [];
  // Filter out warranty/AppleCare items — those aren't devices to compare
  const deviceItems = items.filter(i =>
    !/applecare|warranty|protection\s+plan|extended\s+service/i.test(i.product_name || "")
  );

  if (deviceItems.length <= 1) {
    quoteItemSelector.classList.add("hidden");
    _quoteSelectedIndex = 0;
    return;
  }

  quoteItemSelector.classList.remove("hidden");
  quoteItemList.innerHTML = "";
  deviceItems.forEach((item, idx) => {
    const label = document.createElement("label");
    label.className = "quote-item-radio";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "quoteItem";
    radio.value = idx;
    if (idx === 0) radio.checked = true;
    radio.addEventListener("change", () => { _quoteSelectedIndex = idx; });
    label.appendChild(radio);
    label.appendChild(document.createTextNode(item.product_name || `Item ${idx + 1}`));
    quoteItemList.appendChild(label);
  });
  _quoteSelectedIndex = 0;
}

// File drop / click
quoteDropZone.addEventListener("click", () => quoteFileInput.click());
quoteDropZone.addEventListener("dragover", e => { e.preventDefault(); quoteDropZone.classList.add("dragover"); });
quoteDropZone.addEventListener("dragleave", () => quoteDropZone.classList.remove("dragover"));
quoteDropZone.addEventListener("drop", e => {
  e.preventDefault();
  quoteDropZone.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file) _quoteHandleFile(file);
});
quoteFileInput.addEventListener("change", () => {
  if (quoteFileInput.files[0]) _quoteHandleFile(quoteFileInput.files[0]);
});

function _quoteHandleFile(file) {
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    quoteError.textContent = "Only PDF files are supported.";
    quoteError.classList.remove("hidden");
    return;
  }
  quoteError.classList.add("hidden");
  const reader = new FileReader();
  reader.onload = () => {
    _quoteFileB64 = reader.result.split(",")[1]; // strip data:... prefix
    quoteFileName.textContent = "📄 " + file.name;
    quoteFileName.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
}

// Submit
quoteSubmitBtn.addEventListener("click", async () => {
  const text    = quoteTextInput.value.trim();
  const hasFile = !!_quoteFileB64;
  if (!text && !hasFile) {
    quoteError.textContent = "Paste quote text or upload a PDF.";
    quoteError.classList.remove("hidden");
    return;
  }
  if (!_lastOrderInfo || !_lastOrderInfo.items) {
    quoteError.textContent = "Fetch an order first.";
    quoteError.classList.remove("hidden");
    return;
  }

  quoteError.classList.add("hidden");
  quoteResults.classList.add("hidden");
  quoteSpinner.classList.remove("hidden");
  quoteSubmitBtn.disabled = true;
  quoteStatus.textContent = "";

  // Filter to device items (same logic as _quotePopulateItems)
  const allItems = _lastOrderInfo.items;
  const deviceItems = allItems.filter(i =>
    !/applecare|warranty|protection\s+plan|extended\s+service/i.test(i.product_name || "")
  );
  const item = deviceItems[_quoteSelectedIndex] || deviceItems[0];

  try {
    const body = {
      item:       item,
      all_items:  allItems,
      quote_text: text || null,
      quote_file: _quoteFileB64 || null,
    };
    const resp = await fetch(`${BASE_URL}/validate-quote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    _quoteRenderResults(data);
  } catch (e) {
    quoteError.textContent = e.message;
    quoteError.classList.remove("hidden");
  } finally {
    quoteSpinner.classList.add("hidden");
    quoteSubmitBtn.disabled = false;
  }
});

const _STATUS_LABELS = {
  match:       "✓ Match",
  aligned:     "~ Same spec",
  missing:     "? Missing",
  discrepancy: "✗ Mismatch",
};

function _quoteRenderResults(data) {
  const { rows, match_count, aligned_count, missing_count, discrepancy_count } = data;

  let html = '<div class="quote-summary">';
  if (match_count)       html += `<span class="quote-summary-pill qpill-match">${match_count} match</span>`;
  if (aligned_count)     html += `<span class="quote-summary-pill qpill-aligned">${aligned_count} aligned</span>`;
  if (missing_count)     html += `<span class="quote-summary-pill qpill-missing">${missing_count} missing</span>`;
  if (discrepancy_count) html += `<span class="quote-summary-pill qpill-discrepancy">${discrepancy_count} mismatch</span>`;
  html += '</div>';

  html += '<table class="quote-table"><tr><th>Field</th><th>Order</th><th>Quote</th><th></th></tr>';
  for (const row of rows) {
    const oVal = row.order || "—";
    const qVal = row.quote || "—";
    const badge = `<span class="qt-badge ${row.status}">${_STATUS_LABELS[row.status]}</span>`;
    html += `<tr><td>${row.label}</td><td>${_esc(oVal)}</td><td>${_esc(qVal)}</td><td>${badge}</td></tr>`;
  }
  html += '</table>';

  quoteResults.innerHTML = html;
  quoteResults.classList.remove("hidden");
}

function _esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}


// ══════════════════════════════════════════════════════════════════════════════
// TD SYNNEX CONFIRMATION EMAIL (formerly Confirm Order tab)
// ══════════════════════════════════════════════════════════════════════════════

{
  const emailOnlyBtn  = document.getElementById("emailOnlyBtn");
  const spinner       = document.getElementById("confirmSpinner");
  const errorBox      = document.getElementById("confirmError");
  const resultBox     = document.getElementById("confirmResult");
  const validationDiv = document.getElementById("confirmValidation");
  const draftLink     = document.getElementById("confirmDraftLink");
  const emailPre      = document.getElementById("confirmEmailPreview");
  const copyBtn       = document.getElementById("confirmCopyBtn");

  function updateEmailOnlyBtn() {
    emailOnlyBtn.disabled = !orderInput.value.trim();
  }
  orderInput.addEventListener("input", updateEmailOnlyBtn);
  updateEmailOnlyBtn();

  function showResult(data) {
    validationDiv.innerHTML = "";
    if (data.validation && data.validation.length) {
      data.validation.forEach(v => {
        const div = document.createElement("div");
        div.className = `confirm-validation-item ${v.level}`;
        div.textContent = `${v.level === "error" ? "✗" : "⚠"} ${v.msg}`;
        validationDiv.appendChild(div);
      });
    }

    if (data.draft_url) {
      draftLink.innerHTML = `<a href="${data.draft_url}" target="_blank">Open Gmail Draft →</a>`;
    } else if (data.draft_error) {
      draftLink.innerHTML = `<span style="color:#fca5a5;font-size:12px">${data.draft_error}</span>`;
    } else {
      draftLink.innerHTML = "";
    }

    emailPre.textContent = data.email_body || "";
    resultBox.classList.remove("hidden");
  }

  emailOnlyBtn.addEventListener("click", async () => {
    errorBox.classList.add("hidden");
    resultBox.classList.add("hidden");
    spinner.classList.remove("hidden");
    emailOnlyBtn.disabled = true;

    try {
      const res = await fetch(`${BASE_URL}/confirm-email-only`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ order_number: orderInput.value.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Email generation failed");
      showResult(data);
    } catch (e) {
      errorBox.textContent = e.message;
      errorBox.classList.remove("hidden");
    } finally {
      spinner.classList.add("hidden");
      updateEmailOnlyBtn();
    }
  });

  copyBtn.addEventListener("click", () => {
    navigator.clipboard.writeText(emailPre.textContent);
    copyBtn.textContent = "Copied!";
    copyBtn.style.background = "#166534";
    setTimeout(() => { copyBtn.textContent = "Copy"; copyBtn.style.background = ""; }, 2000);
  });
}
