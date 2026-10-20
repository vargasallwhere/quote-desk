/* Read-only viewer: retain the thread/composer DOM; never save or refetch it. */
window.AttachmentPreview = window.AttachmentPreview?.ready ? window.AttachmentPreview : (() => {
  const $ = id => document.getElementById(id);
  let serial = 0, controller, objectURL, selected, origin, savedScroll, zoom = "fit", media;
  let pdfTask, pdfDoc, renderTask, renderSerial = 0, pageNumber = 1, pdfScale = 1;
  let deadline, attempt = 0;
  const release = new URL(document.currentScript.src).searchParams.get("v");
  function watch(message, milliseconds = 30000) {
    clearTimeout(deadline);
    const token = serial, draw = renderSerial;
    deadline = setTimeout(() => {
      if (token === serial && draw === renderSerial) fail(message);
    }, milliseconds);
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
    watch("This PDF page took too long to render. Retry preview or download it.", 20000);
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
        fail("This PDF page could not be displayed. Retry or download it.");
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
  function fail(message) {
    dispose();
    $("av-feedback").textContent = message;
    $("av-feedback").classList.add("is-error");
    $("av-retry").hidden = false;
    $("av-controls").hidden = true;
    $("av-pages").hidden = true;
    $("av-stage").replaceChildren();
  }
  async function load() {
    dispose();
    const token = serial;
    controller = new AbortController();
    $("av-stage").scrollTop = 0;
    $("av-controls").hidden = true;
    $("av-pages").hidden = true;
    $("av-retry").hidden = true;
    $("av-feedback").classList.remove("is-error");
    $("av-feedback").textContent = "Loading attachment…";
    watch("This attachment took too long to load. Retry preview or download it.");
    try {
      const response = await fetch(selected.href, {signal: controller.signal, cache: "no-store"});
      if (!response.ok) {
        let message = "Could not retrieve this attachment. Try again or download it.";
        try { message = (await response.json()).error || message; } catch (_) {}
        throw new Error(message);
      }
      const blob = await response.blob();
      if (token !== serial) return;
      const type = blob.type.split(";")[0].toLowerCase();
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
        const assetQuery = "?v=" + encodeURIComponent(release) + "&attempt=" + (++attempt);
        const renderer = await import("/attachment-renderer/build/pdf.min.mjs" + assetQuery);
        const bytes = new Uint8Array(await blob.arrayBuffer());
        if (token !== serial) return;
        renderer.GlobalWorkerOptions.workerSrc = "/attachment-renderer/build/pdf.worker.min.mjs" + assetQuery;
        pdfTask = renderer.getDocument({data: bytes, isEvalSupported: false,
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
        objectURL = URL.createObjectURL(blob);
        media = document.createElement("img");
        media.className = "av-image";
        media.alt = selected.name;
        media.onload = () => { if (token === serial) { clearTimeout(deadline); $("av-feedback").textContent = ""; scale(); } };
        media.onerror = () => { if (token === serial) fail("This image could not be displayed. Retry or download it."); };
        media.src = objectURL;
        $("av-feedback").textContent = "Loading image…";
      }
      $("av-stage").append(media);
      $("av-controls").hidden = false;
      scale();
    } catch (error) {
      if (token !== serial) return;
      fail(error.name === "PasswordException" ? "This PDF requires a password. Download it to open it securely." :
        "Could not display this attachment. Retry or download it. " + (error.message || ""));
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
