/* Same-origin, bounded launch observation. Never reads or changes the vendor editor. */
async function openAlternativeReview({po, items, text, state, button, status, recovery, current, start, finish}) {
  const launch = {controller:new AbortController(), window:null, cancelled:false};
  start(launch);
  let timer, stage = "popup", navigated = false;
  const active = () => !launch.cancelled && current();
  const key = JSON.stringify({po, items, text});
  try {
    if (state.key !== key) {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      Object.assign(state, {key, url:null, id:Array.from(bytes, b=>b.toString(16).padStart(2,"0")).join("")});
      recovery.hidden = true;
    }
    launch.window = window.open("/alt-review-launch", "_blank", "width=1280,height=1000,resizable=yes,scrollbars=yes");
    const w = launch.window;
    if (!w) throw new Error("Allow popups for Quote Desk, then click Open again. In an embedded preview, open Quote Desk in its own browser tab first.");
    // Detachment/document restrictions must not prevent same-origin session creation.
    try { w.opener = null; } catch (_) { /* Recovery link remains available. */ }
    button.disabled = true;
    if (!state.url) {
      stage = "creation";
      status.textContent = "Creating review…";
      timer = setTimeout(()=>launch.controller.abort(), 30000);
      const r = await fetch("/api/alt-review", {
        method:"POST", headers:{"Content-Type":"application/json"},
        signal:launch.controller.signal,
        body:JSON.stringify({po, items, text, launch_id:state.id})
      });
      let data;
      try { data = await r.json(); } catch (_) {
        throw new Error(`Review creation returned an unreadable response (HTTP ${r.status}). Retry opening; the same launch will be reused.`);
      }
      if (!r.ok) {
        const label = {origin:"Address configuration", lookup:"Order lookup", selection:"Item selection",
          preparation:"Review preparation", storage:"Local review storage"}[data?.stage] || "Review creation";
        throw new Error(`${label} failed (HTTP ${r.status}). ${data?.error || "Try opening again shortly."}`);
      }
      stage = "link";
      if (typeof data?.url !== "string") throw new Error("The review service returned an invalid review link.");
      const url = new URL(data.url, location.origin);
      if (url.origin !== location.origin || url.pathname !== "/alt-review" ||
          !url.searchParams.get("session") || url.hash)
        throw new Error("The review service returned an invalid review link.");
      state.url = url.href;
      clearTimeout(timer);
    }
    if (!active()) return;
    recovery.href = state.url;
    recovery.hidden = false;
    stage = "navigation";
    if (w.closed) throw new Error("The review tab was closed. Use Open saved review below or click Open again.");
    try { w.location = state.url; } catch (_) {
      throw new Error("The browser could not navigate the review tab. Use Open saved review below; no new session is needed.");
    }
    status.textContent = "Waiting for the review to load…";
    // A navigation assignment is not success. Confirm the exact session's rendered form.
    for (let attempt = 0, deadline = Date.now() + 10000;
         attempt < 100 && Date.now() < deadline; attempt++) {
      if (!active()) return;
      if (w.closed) throw new Error("The review tab was closed before readiness was confirmed. Use Open saved review below.");
      try {
        const url = new URL(w.location.href);
        if (url.href === state.url) {
          navigated = true;
          if (w.document.documentElement.dataset.reviewState === "ready") {
            status.textContent = "Review ready in its dedicated tab. No ticket has been submitted.";
            return;
          }
          if (w.document.documentElement.dataset.reviewState === "error")
            throw new Error("REVIEW_LOAD_FAILED");
        }
      } catch (error) {
        if (error.message === "REVIEW_LOAD_FAILED")
          throw new Error("The saved review could not load. Use its Retry loading link or Open saved review below.");
        // Browser isolation can prohibit observation; do not interpret that as success.
      }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error(navigated
      ? "Quote Desk could not confirm the review form loaded. Use Retry loading in that tab or Open saved review below."
      : "Quote Desk could not confirm review navigation. Use Open saved review below; the session is already saved.");
  } catch (error) {
    if (!state.url) {
      try { launch.window?.close(); } catch (_) { /* No unexplained waiting tab on creation failure. */ }
    }
    if (active()) {
      status.textContent = "Could not open review. " + (error.name === "AbortError"
        ? "Review creation timed out. Retry opening; the same launch will be reused."
        : stage === "popup" && error.name === "SecurityError"
          ? "The browser restricted the review tab. Allow popups or open Quote Desk outside its embedded preview, then click Open again."
          : error.message || "Review creation failed. Check your connection and retry opening; the same launch will be reused.");
    }
  } finally {
    clearTimeout(timer);
    finish(launch);
    if (current()) button.disabled = false;
  }
}
