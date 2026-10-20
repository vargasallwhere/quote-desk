/* Private OCR controller. All engine/model files are same-origin.
   Own the nested engine Worker even during createWorker's asynchronous startup,
   so cancellation also stops model loading, not just recognition results. */
const children = new Set();
const NativeWorker = self.Worker;
self.Worker = class extends NativeWorker {
  constructor(...args) {
    super(...args);
    children.add(this);
  }
};
function stop() {
  for (const child of children) child.terminate();
  children.clear();
  self.close();
}
self.onmessage = async ({data}) => {
  if (data.cancel) { stop(); return; }
  try {
    importScripts("/attachment-ocr/tesseract.min.js");
    const engine = await Tesseract.createWorker("eng", 1, {
      workerPath: new URL("/attachment-ocr/worker.min.js", self.location).href,
      corePath: new URL("/attachment-ocr/", self.location).href,
      langPath: new URL("/attachment-ocr", self.location).href,
      workerBlobURL: false,
      cacheMethod: "none",
      logger: message => {
        if (message.status === "recognizing text")
          self.postMessage({progress: Math.round(message.progress * 100)});
      },
      errorHandler: () => {} // Report only a fixed code, never recognized content.
    });
    const result = await engine.recognize(new Uint8Array(data.image), {}, {blocks: true, text: true});
    self.postMessage({blocks: result.data.blocks || []});
  } catch (_) {
    self.postMessage({error: true});
  } finally {
    stop();
  }
};
