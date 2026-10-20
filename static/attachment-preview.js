/* Read-only viewer: retain the thread/composer DOM; never save or refetch it. */
window.AttachmentPreview = window.AttachmentPreview?.ready ? window.AttachmentPreview : (() => {
  const $ = id => document.getElementById(id);
  let serial = 0, controller, objectURL, selected, origin, savedScroll, zoom = "fit", media;
  let pdfTask, pdfWorker, nativeWorker, pdfDoc, renderTask, renderSerial = 0, pageNumber = 1, pdfScale = 1;
  let deadline, expires, attempt = 0, stage = "request";
  // Only fixed codes, numeric HTTP status and a validated release may be reported.
  // Never forward exception messages, filenames, identifiers or request URLs.
  const version = new URL(document.currentScript.src).searchParams.get("v");
  const release = /^[a-f0-9]{16}$/.test(version) ? version : "unknown";
  const messages = {
    request: "Could not retrieve this attachment.",
    body: "The attachment transfer was interrupted.",
    module: "The PDF renderer could not load.",
    worker: "The PDF worker could not start.",
    document: "The PDF document could not open.",
    page: "This PDF page could not load.",
    render: "This PDF page could not be displayed.",
    image: "This image could not be displayed."
  };
  function watch(next, milliseconds) {
    stage = next;
    if (milliseconds !== undefined) expires = performance.now() + milliseconds;
    clearTimeout(deadline);
    const token = serial, draw = renderSerial;
    deadline = setTimeout(() => {
      if (token === serial && draw === renderSerial) fail(next, "timeout");
    }, Math.max(0, expires - performance.now()));
  }
  const supported = new Set(["application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"]);
  function dispose() {
    ++serial;
    clearTimeout(deadline);
    if (controller) controller.abort();
    controller = null;
    ++renderSerial;
    if (renderTask) renderTask.cancel();
    renderTask = null;
    if (pdfTask) pdfTask.destroy().catch(() => {});
    if (pdfWorker) pdfWorker.destroy();
    pdfWorker = null;
    if (nativeWorker) nativeWorker.terminate();
    nativeWorker = null;
    pdfTask = null; pdfDoc = null;
    if ($("av-stage")) $("av-stage").replaceChildren();
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = null; media = null;
  }
  function clear(restore = false) {
    dispose();
    if (!$("attachment-preview")) return;
    $("attachment-preview").hidden = true;
    $("thread").hidden = false;
    document.body.classList.remove("attachment-view");
    if (restore && savedScroll) {
      window.scrollTo(savedScroll.x, savedScroll.y);
      $("thread").scrollTop = savedScroll.thread;
      if (origin && origin.isConnected) origin.focus({preventScroll: true});
    }
    selected = null; origin = null; savedScroll = null;
  }
  async function renderPDF() {
    const token = serial, draw = ++renderSerial, doc = pdfDoc, canvas = media;
    const previous = renderTask;
    if (previous) previous.cancel();
    $("av-feedback").textContent = "Rendering page…";
    let drawing = false;
    watch("page", 20000);
    try {
      if (previous) await previous.promise.catch(() => {});
      if (token !== serial || draw !== renderSerial) return;
      const page = await doc.getPage(pageNumber);
      if (token !== serial || draw !== renderSerial) return;
      const base = page.getViewport({scale: 1});
      pdfScale = zoom === "fit" ? Math.max(0.1, ($("av-stage").clientWidth - 20) / base.width) : zoom / 100;
      const viewport = page.getViewport({scale: pdfScale});
      const ratio = Math.min(window.devicePixelRatio || 1, 2,
        Math.sqrt(16000000 / (viewport.width * viewport.height)),
        16000 / Math.max(viewport.width, viewport.height));
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      canvas.style.width = viewport.width + "px";
      canvas.style.height = viewport.height + "px";
      $("av-feedback").textContent = "Rendering page…";
      drawing = true;
      watch("render");
      renderTask = page.render({canvasContext: canvas.getContext("2d"), viewport,
        transform: [ratio, 0, 0, ratio, 0, 0]});
      await renderTask.promise;
      if (token !== serial || draw !== renderSerial) return;
      clearTimeout(deadline);
      $("av-feedback").textContent = "";
      $("av-page").textContent = "Page " + pageNumber + " of " + doc.numPages;
      $("av-prev").disabled = pageNumber === 1;
      $("av-next").disabled = pageNumber === doc.numPages;
    } catch (error) {
      if (token === serial && draw === renderSerial && error.name !== "RenderingCancelledException")
        fail(drawing ? "render" : "page");
    }
  }
  function scale() {
    if (!media) return;
    $("av-zoom").textContent = zoom === "fit" ? "Fit width" : zoom + "%";
    if (pdfDoc) {
      renderPDF();
    } else {
      media.style.width = zoom === "fit" ? "100%" : media.naturalWidth * zoom / 100 + "px";
      media.style.maxWidth = "none";
    }
  }
  function fail(failedStage, reason = "failed", status) {
    const code = failedStage + "/" + reason + (Number.isInteger(status) ? "/" + status : "");
    const diagnostic = {stage: failedStage, reason, release, attempt};
    if (Number.isInteger(status)) diagnostic.status = status;
    console.warn("Attachment preview", diagnostic);
    dispose();
    $("av-feedback").textContent = messages[failedStage] +
      (reason === "password" ? " This PDF requires a password." : "") +
      (reason === "timeout" ? " The operation timed out." : "") +
      " Retry preview. Diagnostic: " + code + " · viewer " + release + " · attempt " + attempt + ".";
    $("av-feedback").classList.add("is-error");
    $("av-retry").hidden = false;
    $("av-controls").hidden = true;
    $("av-pages").hidden = true;
    $("av-stage").replaceChildren();
  }
  async function load() {
    dispose();
    const token = serial;
    ++attempt;
    controller = new AbortController();
    $("av-stage").scrollTop = 0;
    $("av-controls").hidden = true;
    $("av-pages").hidden = true;
    $("av-retry").hidden = true;
    $("av-feedback").classList.remove("is-error");
    $("av-feedback").textContent = "Loading attachment…";
    watch("request", 30000);
    try {
      const response = await fetch(selected.href, {signal: controller.signal, cache: "no-store",
        mode: "same-origin", headers: {"X-Attachment-Preview": "1"}});
      if (token !== serial) return;
      if (!response.ok) {
        // Do not echo a proxy's HTML, error body or private upstream details.
        fail("request", "http", response.status);
        return;
      }
      watch("body");
      $("av-feedback").textContent = "Reading attachment…";
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (token !== serial) return;
      const type = (response.headers.get("Content-Type") || "").split(";")[0].trim().toLowerCase();
      if (!supported.has(type)) {
        clearTimeout(deadline);
        $("av-feedback").textContent = "Preview is not available for this file format. Download it to open in an appropriate application.";
        return;
      }
      zoom = "fit";
      if (type === "application/pdf") {
        // Canvas-only PDF.js: no scripting, forms, annotations or attachment HTML.
        $("av-feedback").textContent = "Starting PDF renderer…";
        // Unique retry URLs avoid the browser's cached failed module imports.
        const assetQuery = "?v=" + encodeURIComponent(release) + "&attempt=" + attempt;
        watch("module");
        const renderer = await import("/attachment-renderer/build/pdf.min.mjs" + assetQuery);
        if (token !== serial) return;
        // Own and await worker startup separately from PDF parsing. Dispose it on
        // failure/Back/Retry, including BEFORE PDF.js has accepted its worker port.
        // PDF.js otherwise retains a stalled startup Worker until its handshake.
        watch("worker");
        nativeWorker = new Worker("/attachment-renderer/build/pdf.worker.min.mjs" + assetQuery, {type: "module"});
        const worker = nativeWorker;
        const started = new Promise((resolve, reject) => {
          // This is PDF.js's ready handshake, not document data. Keep in step
          // with the locked renderer when upgrading it.
          worker.addEventListener("message", function ready(event) {
            if (event.data?.action !== "ready" || event.data?.sourceName !== "worker") return;
            worker.removeEventListener("message", ready);
            resolve();
          });
          worker.addEventListener("error", () => reject(new Error("worker")), {once: true});
        });
        pdfWorker = new renderer.PDFWorker({port: worker, verbosity: 0});
        await started;
        await pdfWorker.promise;
        if (token !== serial) return;
        watch("document");
        pdfTask = renderer.getDocument({data: bytes, worker: pdfWorker, verbosity: 0, isEvalSupported: false,
          cMapUrl: "/attachment-renderer/cmaps/", cMapPacked: true,
          standardFontDataUrl: "/attachment-renderer/standard_fonts/",
          wasmUrl: "/attachment-renderer/wasm/", useSystemFonts: true});
        const loaded = await pdfTask.promise;
        if (token !== serial) return;
        pdfDoc = loaded; pageNumber = 1;
        media = document.createElement("canvas");
        media.className = "av-pdf";
        media.setAttribute("role", "img");
        media.setAttribute("aria-label", "PDF preview: " + selected.name);
        $("av-pages").hidden = false;
        $("av-prev").onclick = () => { if (pageNumber > 1) { --pageNumber; $("av-stage").scrollTop = 0; scale(); } };
        $("av-next").onclick = () => { if (pageNumber < pdfDoc.numPages) { ++pageNumber; $("av-stage").scrollTop = 0; scale(); } };
      } else {
        watch("image");
        objectURL = URL.createObjectURL(new Blob([bytes], {type}));
        media = document.createElement("img");
        media.className = "av-image";
        media.alt = selected.name;
        media.onload = () => { if (token === serial) { clearTimeout(deadline); $("av-feedback").textContent = ""; scale(); } };
        media.onerror = () => { if (token === serial) fail("image"); };
        media.src = objectURL;
        $("av-feedback").textContent = "Loading image…";
      }
      $("av-stage").append(media);
      $("av-controls").hidden = false;
      scale();
    } catch (error) {
      if (token !== serial) return;
      fail(stage, error.name === "PasswordException" ? "password" : stage === "request" ? "transport" : "failed");
    }
  }
  function open(link) {
    if (!selected) {
      savedScroll = {x: window.scrollX, y: window.scrollY, thread: $("thread").scrollTop};
      origin = link;
    }
    selected = {href: link.dataset.href, name: link.dataset.name};
    $("av-name").textContent = selected.name;
    $("av-download").href = selected.href;
    $("av-download").download = selected.name;
    $("thread").hidden = true;
    $("attachment-preview").hidden = false;
    document.body.classList.add("attachment-view");
    $("av-back").onclick = () => clear(true);
    $("av-retry").onclick = load;
    $("av-fit").onclick = () => { zoom = "fit"; scale(); };
    $("av-actual").onclick = () => { zoom = 100; scale(); };
    const step = delta => {
      const fit = pdfDoc ? Math.round(pdfScale * 100) :
        media && media.tagName === "IMG" ? Math.round($("av-stage").clientWidth / media.naturalWidth * 100) : 100;
      zoom = Math.max(25, Math.min(400, (zoom === "fit" ? fit : zoom) + delta)); scale();
    };
    $("av-out").onclick = () => step(-25);
    $("av-in").onclick = () => step(25);
    $("vendor-panel").scrollIntoView({block: "start"});
    $("av-back").focus({preventScroll: true});
    load();
  }
  window.addEventListener("resize", () => { if (selected && zoom === "fit" && pdfDoc) scale(); });
  return {open, clear, ready: true};
})();
