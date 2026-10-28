// ── Tickets V2 Review Page ─────────────────────────────────────────────────
// Panel version: loads pre-filled data from Flask session (set by popup.js),
// lets user review and edit every field, then submits to /create-airtable-ticket-v2.
// Sets "Send Alt/Pricing Email" = true on submit → customer notification fires.
// ──────────────────────────────────────────────────────────────────────────────

const BASE_URL = window.location.origin;

// ── Field references ──────────────────────────────────────────────────────────

const rvOrder      = document.getElementById("rv-order");
const rvOrg        = document.getElementById("rv-org");
const rvOm         = document.getElementById("rv-om");
const rvAltType    = document.getElementById("rv-alt-type");
const rvAltSubtype = document.getElementById("rv-alt-subtype");
const rvReqSku     = document.getElementById("rv-req-sku");
const rvMultiSkus  = document.getElementById("rv-multi-skus");
const rvDeviceType = document.getElementById("rv-device-type");
const rvMake       = document.getElementById("rv-make");
const rvModel      = document.getElementById("rv-model");
const rvDisplay    = document.getElementById("rv-display");
const rvProcessor  = document.getElementById("rv-processor");
const rvMemory     = document.getElementById("rv-memory");
const rvStorage    = document.getElementById("rv-storage");
const rvColor      = document.getElementById("rv-color");
const rvKeyboard   = document.getElementById("rv-keyboard");
const rvCountry    = document.getElementById("rv-country");
const rvMpn        = document.getElementById("rv-mpn");
const rvPrice      = document.getElementById("rv-price");

const rvRequestedBy  = document.getElementById("rv-requested-by");
const rvLeadTimeRow  = document.getElementById("rv-lead-time-row");
const rvLeadTime     = document.getElementById("rv-lead-time");

const rvSubmitBtn    = document.getElementById("rv-submit-btn");
const rvSubmitStatus = document.getElementById("rv-submit-status");
const rvSuccess      = document.getElementById("rv-success");
const rvAirtableLink = document.getElementById("rv-airtable-link");

let _reviewData = null;

// ── Load data from storage ────────────────────────────────────────────────────

(async () => {
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get('session');
  if (!sessionId) {
    rvSubmitStatus.textContent = "No session found. Please try again from the extension.";
    rvSubmitBtn.disabled = true;
    return;
  }
  try {
    const resp = await fetch(`${BASE_URL}/review-session/${sessionId}`);
    if (!resp.ok) throw new Error('expired');
    _reviewData = await resp.json();
    populateFields(_reviewData);
    rvAltType.dispatchEvent(new Event("change"));
  } catch (e) {
    rvSubmitStatus.textContent = "Session expired. Please try again from the extension.";
    rvSubmitBtn.disabled = true;
  }
})();

function populateFields(d) {
  rvOrder.textContent = d.order_number || "";
  rvOrg.textContent   = d.org_name || "—";
  rvOm.textContent    = d.order_manager_name || "—";

  setSelect(rvRequestedBy, d.procurement_manager_email || "sara@allwhere.co");
  setSelect(rvAltType,    d.alt_type    || "Out of stock / backordered");
  setSelect(rvAltSubtype, d.alt_subtype || "Model unavailable");

  rvReqSku.value        = d.requested_sku || "";
  rvMultiSkus.checked   = !!d.multiple_skus;

  setSelect(rvDeviceType, d.device_type || "Laptop");
  rvMake.value      = d.make      || "Apple";
  rvModel.value     = d.model     || "";
  rvDisplay.value   = d.display_size || "";
  rvProcessor.value = d.processor || "";
  rvMemory.value    = d.memory    || "";
  rvStorage.value   = d.storage   || "";
  rvColor.value     = d.color     || "";
  rvKeyboard.value  = d.keyboard_language ?? "";
  rvCountry.value   = d.sku_country ?? "";
  rvMpn.value       = d.mpn   || "";
  rvPrice.value     = d.price || "";
}

rvAltType.addEventListener("change", () => {
  const val = rvAltType.value;
  const show = val === "CTO device" || val === "Out of stock / backordered";
  rvLeadTimeRow.classList.toggle("hidden", !show);
  if (val === "CTO device") {
    rvLeadTime.value = "3-5 weeks";
  } else if (val === "Out of stock / backordered") {
    rvLeadTime.value = "";
  }
});

function setSelect(el, value) {
  for (const opt of el.options) {
    if (opt.value === value || opt.text === value) {
      el.value = opt.value;
      return;
    }
  }
}

// ── Submit ────────────────────────────────────────────────────────────────────

rvSubmitBtn.addEventListener("click", async () => {
  if (!_reviewData) return;

  rvSubmitBtn.disabled       = true;
  rvSubmitBtn.textContent    = "Creating…";
  rvSubmitStatus.textContent = "";
  rvSuccess.classList.add("hidden");

  const header = {
    is_rush:             _reviewData.is_rush || false,
    org_name:            rvOrg.textContent,
    order_manager_email: _reviewData.order_manager_email || "",
    order_manager_name:  _reviewData.order_manager_name  || "",
    procurement_manager_email: rvRequestedBy.value,
  };

  const ticketData = {
    alt_type:         rvAltType.value,
    alt_subtype:      rvAltSubtype.value,
    requested_sku:    rvReqSku.value.trim(),
    multiple_skus:    rvMultiSkus.checked,
    device_type:      rvDeviceType.value,
    make:             rvMake.value.trim(),
    model:            rvModel.value.trim(),
    display_size:     rvDisplay.value.trim(),
    processor:        rvProcessor.value.trim(),
    memory:           rvMemory.value.trim(),
    storage:          rvStorage.value.trim(),
    color:            rvColor.value.trim(),
    keyboard_language: rvKeyboard.value.trim(),
    sku_country:      rvCountry.value.trim(),
    mpn:              rvMpn.value.trim(),
    price:            rvPrice.value.trim(),
    lead_time:        rvLeadTime.value.trim(),
  };

  try {
    const resp = await fetch(`${BASE_URL}/create-airtable-ticket-v2`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        order_number: _reviewData.order_number,
        header:       header,
        ticket_data:  ticketData,
      }),
    });
    const result = await resp.json();

    if (result.ok) {
      rvAirtableLink.href = result.url;
      rvSuccess.classList.remove("hidden");
      rvSubmitBtn.textContent = "✓ Submitted";
    } else {
      rvSubmitStatus.textContent = result.error || "Failed to create ticket.";
      rvSubmitBtn.disabled    = false;
      rvSubmitBtn.textContent = "Submit to Airtable";
    }
  } catch (_) {
    rvSubmitStatus.textContent = "Cannot connect to the server. Is Quote Desk running?";
    rvSubmitBtn.disabled    = false;
    rvSubmitBtn.textContent = "Submit to Airtable";
  }
});
