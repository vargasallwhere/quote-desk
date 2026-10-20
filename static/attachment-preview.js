/* Read-only viewer: retain the thread/composer DOM; never save or refetch it. */
window.AttachmentPreview = window.AttachmentPreview?.ready ? window.AttachmentPreview : (() => {
  const $ = id => document.getElementById(id);
  let serial = 0, controller, objectURL, selected, origin, savedScroll, zoom = "fit", media;
  let pdfTask, pdfWorker, nativeWorker, pdfDoc, renderTask, renderSerial = 0, pageNumber = 1, pdfScale = 1;
  let deadline, expires, attempt = 0, stage = "request";
  let TextLayer, textTask, textSurface, textReady = false, matchCounts = {};
  let ocrJob, ocrRender, ocrState = "", ocrPages = new Map();
  function highlightStatus() {
    const status = $("av-matches");
    if (!status) return;
    status.hidden = !pdfDoc || (!textReady && !ocrState);
    if (status.hidden) return;
    if (ocrState && ocrState !== "done") {
      status.textContent = ocrState;
      return;
    }
    const key = document.documentElement.dataset.focus;
    const count = key ? matchCounts[key] || 0 : Object.values(matchCounts).reduce((a, b) => a + b, 0);
    const label = [...document.querySelectorAll(".legend button")].find(b => b.dataset.k === key)?.textContent;
    status.textContent = !textSurface.textContent.trim()
      ? (ocrState === "done" ? "No readable text found by local OCR. Try a clearer scan."
        : "No readable text on this page. Scanned PDFs need text recognition before tags can be detected.")
      : count ? (label || "Specifications") + ": " + count + " highlighted match" + (count === 1 ? "" : "es") + " on this page."
      : "No " + (label || "specification").toLowerCase() + " matches found on this page.";
    if (ocrState === "done") status.textContent += " Local OCR — check against the scan.";
  }
  // The same data-focus attribute already drives sidebar/email highlighting.
  new MutationObserver(highlightStatus).observe(document.documentElement,
    {attributes: true, attributeFilter: ["data-focus"]});
  function resetText() {
    ocrJob?.cancel();
    ocrJob = null;
    ocrRender?.cancel();
    ocrRender = null;
    ocrState = "";
    if ($("av-ocr")) $("av-ocr").hidden = true;
    textTask?.cancel();
    textTask = null;
    textReady = false;
    matchCounts = {};
    textSurface?.replaceChildren();
    if ($("av-matches")) $("av-matches").hidden = true;
  }
  function paintOCR(result) {
    textSurface.replaceChildren();
    matchCounts = {};
    let text = "";
    const runs = [];
    for (const block of result.blocks) for (const paragraph of block.paragraphs || [])
      for (const line of paragraph.lines || []) {
        for (const word of line.words || []) {
          const start = text.length;
          text += word.text;
          runs.push({start, end: text.length, word});
          text += " ";
        }
        text += "\n";
      }
    // Keep plain recognized text hidden, using explicit word boxes for the
    // highlights rather than guessing font metrics on a scanned page.
    const plain = document.createElement("span");
    plain.className = "av-ocr-plain";
    plain.textContent = text;
    textSurface.append(plain);
    let offset = 0;
    for (const [value, kind] of hlParts(text)) {
      const end = offset + value.length;
      if (kind) {
        matchCounts[kind] = (matchCounts[kind] || 0) + 1;
        for (const run of runs) {
          if (end <= run.start || offset >= run.end) continue;
          const mark = document.createElement("mark"), box = run.word.bbox;
          mark.className = "hl hl-" + kind + " av-ocr-mark";
          mark.style.left = box.x0 / result.width * 100 + "%";
          mark.style.top = box.y0 / result.height * 100 + "%";
          mark.style.width = (box.x1 - box.x0) / result.width * 100 + "%";
          mark.style.height = (box.y1 - box.y0) / result.height * 100 + "%";
          textSurface.append(mark);
        }
      }
      offset = end;
    }
    ocrState = "done";
    textReady = true;
    highlightStatus();
  }
  async function recognizePage() {
    const token = serial, draw = renderSerial, number = pageNumber, doc = pdfDoc;
    const current = () => token === serial && draw === renderSerial;
    $("av-ocr").hidden = true;
    ocrState = "Starting local text recognition… You can keep reading or leave this page.";
    highlightStatus();
    let raster;
    try {
      const {recognize} = await import("/static/pdf-ocr.js?v=" + release);
      if (!current()) return;
      const page = await doc.getPage(number);
      if (!current()) return;
      const base = page.getViewport({scale: 1});
      const viewport = page.getViewport({scale: Math.min(2.5,
        Math.sqrt(8000000 / (base.width * base.height)), 12000 / Math.max(base.width, base.height))});
      raster = document.createElement("canvas");
      raster.width = Math.ceil(viewport.width);
      raster.height = Math.ceil(viewport.height);
      ocrRender = page.render({canvasContext: raster.getContext("2d"), viewport});
      await ocrRender.promise;
      if (!current()) return;
      ocrRender = null;
      const job = recognize(raster, percent => {
        if (!current()) return;
        ocrState = "Recognizing text locally: " + percent + "%. You can keep reading or leave this page.";
        highlightStatus();
      });
      ocrJob = job;
      const blocks = await job.promise;
      if (!current()) return;
      ocrJob = null;
      const result = {blocks, width: raster.width, height: raster.height};
      ocrPages.set(number, result);
      paintOCR(result);
    } catch (_) {
      if (!current()) return;
      ocrState = "Local text recognition could not finish. The PDF is still readable. Retry recognition or download the quote.";
      $("av-ocr").hidden = false;
      highlightStatus();
    } finally {
      if (raster) { raster.width = 0; raster.height = 0; }
    }
  }
  function tagText(layer, content) {
    // Match a joined logical string, then map ranges back into positioned runs.
    // This also detects specifications split across PDF font/text objects.
    const items = content.items.filter(item => typeof item.str === "string");
    let text = "", previous;
    const runs = items.map((item, index) => {
      if (previous) {
        const lineBreak = previous.hasEOL ||
          Math.abs(item.transform[5] - previous.transform[5]) > Math.max(item.height, previous.height) * 0.5;
        const gap = item.transform[4] - previous.transform[4] - previous.width;
        if (lineBreak) text += "\n";
        else if (gap > Math.max(item.height, previous.height) * 0.2 &&
          !/\s$/.test(text) && !/^\s/.test(item.str)) text += " ";
      }
      const start = text.length;
      text += item.str;
      previous = item;
      return {start, end: text.length, div: layer.textDivs[index], value: item.str};
    });
    let offset = 0;
    const matches = [];
    for (const [value, kind] of hlParts(text)) {
      if (kind) {
        matches.push({start: offset, end: offset + value.length, kind});
        matchCounts[kind] = (matchCounts[kind] || 0) + 1;
      }
      offset += value.length;
    }
    for (const run of runs) {
      if (!run.div || !run.value) continue;
      const nodes = [];
      let cursor = 0;
      for (const match of matches) {
        if (match.end <= run.start || match.start >= run.end) continue;
        const start = Math.max(match.start, run.start) - run.start;
        const end = Math.min(match.end, run.end) - run.start;
        nodes.push(document.createTextNode(run.value.slice(cursor, start)));
        const mark = document.createElement("mark");
        mark.className = "hl hl-" + match.kind;
        mark.textContent = run.value.slice(start, end);
        nodes.push(mark);
        cursor = end;
      }
      nodes.push(document.createTextNode(run.value.slice(cursor)));
      run.div.replaceChildren(...nodes);
    }
  }
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
    resetText();
    ocrPages.clear();
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
    objectURL = null; media = null; textSurface = null;
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
    resetText();
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
      canvas.parentElement.style.width = viewport.width + "px";
      canvas.parentElement.style.height = viewport.height + "px";
      $("av-feedback").textContent = "Rendering page…";
      drawing = true;
      watch("render");
      renderTask = page.render({canvasContext: canvas.getContext("2d"), viewport,
        transform: [ratio, 0, 0, ratio, 0, 0]});
      await renderTask.promise;
      if (token !== serial || draw !== renderSerial) return;
      // Text extraction failure must not discard a successfully painted quote.
      try {
        const content = await page.getTextContent();
        if (token !== serial || draw !== renderSerial) return;
        textSurface.style.setProperty("--total-scale-factor", viewport.scale);
        const layer = new TextLayer({textContentSource: content, container: textSurface, viewport});
        textTask = layer;
        await layer.render();
        if (token !== serial || draw !== renderSerial) return;
        tagText(layer, content);
        textReady = true;
        highlightStatus();
        if (!content.items.some(item => item.str?.trim())) {
          if (ocrPages.has(pageNumber)) paintOCR(ocrPages.get(pageNumber));
          else $("av-ocr").hidden = false;
        }
      } catch (_) {
        if (token !== serial || draw !== renderSerial) return;
        resetText();
        if (ocrPages.has(pageNumber)) paintOCR(ocrPages.get(pageNumber));
        else {
          $("av-matches").hidden = false;
          $("av-matches").textContent = "This page is readable, but native text detection is unavailable. You can try local text recognition.";
          $("av-ocr").hidden = false;
        }
      }
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
        TextLayer = renderer.TextLayer;
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
      if (pdfDoc) {
        const sheet = document.createElement("div");
        sheet.className = "av-sheet";
        textSurface = document.createElement("div");
        textSurface.className = "av-text";
        textSurface.setAttribute("aria-hidden", "true");
        sheet.append(media, textSurface);
        $("av-stage").append(sheet);
      } else $("av-stage").append(media);
      $("av-controls").hidden = false;
      scale();
    } catch (error) {
      if (token !== serial) return;
      fail(stage, error.name === "PasswordException" ? "password" : stage === "request" ? "transport" : "failed");
    }
  }
  function open(link) {
    if (!$("av-matches")) {
      const matchStatus = document.createElement("div");
      matchStatus.id = "av-matches";
      matchStatus.setAttribute("role", "status");
      matchStatus.hidden = true;
      $("av-stage").before(matchStatus);
      const recognizeButton = document.createElement("button");
      recognizeButton.id = "av-ocr";
      recognizeButton.textContent = "Recognize text on this page (local only)";
      recognizeButton.title = "English text recognition runs in your browser. Nothing is uploaded. Results may be inaccurate.";
      recognizeButton.hidden = true;
      recognizeButton.onclick = recognizePage;
      $("av-stage").before(recognizeButton);
    }
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
