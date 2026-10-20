// Controller lifecycle with no browser, files, quote data or external requests.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const code = fs.readFileSync("static/pdf-ocr-worker.js", "utf8");
const deferred = () => {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return {promise, resolve};
};
function fixture(stage) {
  const startup = deferred(), recognition = deferred();
  const children = [], messages = [], imports = [];
  let closed = false, options;
  const self = {
    location: "https://local.invalid/static/pdf-ocr-worker.js",
    Worker: class {
      constructor(path) { this.path = path; children.push(this); }
      terminate() { this.terminated = true; }
    },
    close() { closed = true; },
    postMessage(message) { messages.push(message); }
  };
  const engine = {recognize: () => recognition.promise};
  const Tesseract = {
    createWorker: async (language, mode, opts) => {
      assert.equal(language, "eng");
      assert.equal(mode, 1);
      options = opts;
      new self.Worker(opts.workerPath);
      return stage === "startup" ? startup.promise : engine;
    }
  };
  vm.runInNewContext(code, {self, Tesseract, URL, Uint8Array,
    importScripts: url => imports.push(url)});
  return {self, children, messages, imports, startup, recognition,
    get closed() { return closed; }, get options() { return options; }};
}
(async () => {
  for (const stage of ["startup", "recognition"]) {
    const f = fixture(stage);
    f.self.onmessage({data: {image: new ArrayBuffer(1)}});
    await Promise.resolve();
    assert.equal(f.children.length, 1);
    assert.equal(f.options.cacheMethod, "none");
    for (const name of ["workerPath", "corePath", "langPath"])
      assert.equal(new URL(f.options[name]).origin, "https://local.invalid");
    assert.deepEqual(f.imports, ["/attachment-ocr/tesseract.min.js"]);
    await f.self.onmessage({data: {cancel: true}});
    assert(f.closed);
    assert(f.children.every(child => child.terminated));
  }
  const f = fixture("recognition");
  const job = f.self.onmessage({data: {image: new ArrayBuffer(1)}});
  await Promise.resolve();
  f.options.logger({status: "recognizing text", progress: 0.4});
  f.recognition.resolve({data: {blocks: []}});
  await job;
  assert.equal(f.messages[0].progress, 40);
  assert(Array.isArray(f.messages[1].blocks));
  assert(f.children.every(child => child.terminated));
  assert(f.closed);
  console.log("Local OCR controller: startup/recognition cancellation, same-origin paths, no cache, progress and cleanup passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
