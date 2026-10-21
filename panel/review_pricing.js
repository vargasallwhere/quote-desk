// ── Pricing Approval Review Page ──────────────────────────────────────────────
// Loads pre-filled product data from Flask session, lets user add prices,
// then submits to /create-pricing-approval.
// ──────────────────────────────────────────────────────────────────────────────

const BASE_URL = window.location.origin;

const rpOrder        = document.getElementById("rp-order");
const rpOrg          = document.getElementById("rp-org");
const rpOm           = document.getElementById("rp-om");
const rpRequestedBy  = document.getElementById("rp-requested-by");
const rpProductsText = document.getElementById("rp-products-text");
const rpSubmitBtn    = document.getElementById("rp-submit-btn");
const rpSubmitStatus = document.getElementById("rp-submit-status");
const rpSuccess      = document.getElementById("rp-success");
const rpAirtableLink = document.getElementById("rp-airtable-link");

let _sessionData = null;

(async () => {
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("session");
  if (!sessionId) {
    rpSubmitStatus.textContent = "No session found. Please try again from the extension.";
    rpSubmitBtn.disabled = true;
    return;
  }
  try {
    const resp = await fetch(`${BASE_URL}/review-session/${sessionId}`);
    if (!resp.ok) throw new Error("expired");
    _sessionData = await resp.json();
    populateFields(_sessionData);
  } catch (e) {
    rpSubmitStatus.textContent = "Session expired. Please try again from the extension.";
    rpSubmitBtn.disabled = true;
  }
})();

function populateFields(d) {
  rpOrder.textContent = d.order_number || "";
  rpOrg.textContent   = d.org_name || "—";
  rpOm.textContent    = d.order_manager_name || "—";

  setSelect(rpRequestedBy, d.procurement_manager_email || "sara@allwhere.co");

  const items = d.items || [];
  const lines = [];
  items.forEach((item, i) => {
    if (i > 0) lines.push("");
    lines.push(item.sku || "");
    lines.push(item.product_name || "");
    lines.push("Old Price: ");
    lines.push("New Price: ");
  });
  rpProductsText.value = lines.join("\n");
}

function setSelect(el, value) {
  for (const opt of el.options) {
    if (opt.value === value || opt.text === value) {
      el.value = opt.value;
      return;
    }
  }
}

rpSubmitBtn.addEventListener("click", async () => {
  if (!_sessionData) return;

  const productsText = rpProductsText.value.trim();
  if (!productsText) {
    rpSubmitStatus.textContent = "Please fill in the product details.";
    return;
  }

  rpSubmitBtn.disabled       = true;
  rpSubmitBtn.textContent    = "Creating…";
  rpSubmitStatus.textContent = "";
  rpSuccess.classList.add("hidden");

  const header = {
    is_rush:                     _sessionData.is_rush || false,
    org_name:                    rpOrg.textContent,
    order_manager_email:         _sessionData.order_manager_email || "",
    order_manager_name:          _sessionData.order_manager_name  || "",
    procurement_manager_email:   rpRequestedBy.value,
  };

  try {
    const resp = await fetch(`${BASE_URL}/create-pricing-approval`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        order_number:  _sessionData.order_number,
        header:        header,
        products_text: productsText,
      }),
    });
    const result = await resp.json();

    if (result.ok) {
      rpAirtableLink.href = result.url;
      rpSuccess.classList.remove("hidden");
      rpSubmitBtn.textContent = "✓ Submitted";
    } else {
      rpSubmitStatus.textContent = result.error || "Failed to create ticket.";
      rpSubmitBtn.disabled    = false;
      rpSubmitBtn.textContent = "Submit";
    }
  } catch (_) {
    rpSubmitStatus.textContent = "Cannot connect to server. Is it running?";
    rpSubmitBtn.disabled    = false;
    rpSubmitBtn.textContent = "Submit";
  }
});
