/* One disposable local job per requested page; no persistence or uploads. */
export function recognize(canvas, progress) {
  const worker = new Worker("/static/pdf-ocr-worker.js");
  let settled = false, rejectJob;
  const stop = () => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    // The controller terminates its engine worker, including during startup.
    worker.postMessage({cancel: true});
    rejectJob(new Error("cancelled"));
  };
  const timer = setTimeout(stop, 120000);
  const promise = new Promise((resolve, reject) => {
    rejectJob = reject;
    worker.onerror = () => {
      if (settled) return;
      stop();
      worker.terminate();
    };
    worker.onmessage = ({data}) => {
      if (settled) return;
      if (data.progress !== undefined) { progress(data.progress); return; }
      settled = true;
      clearTimeout(timer);
      if (data.error) reject(new Error("recognition"));
      else resolve(data.blocks);
    };
    canvas.toBlob(async blob => {
      try {
        if (!blob) throw new Error("image");
        const image = await blob.arrayBuffer();
        if (!settled) worker.postMessage({image}, [image]);
      } catch (_) { stop(); }
    }, "image/png");
  });
  return {promise, cancel: stop};
}
