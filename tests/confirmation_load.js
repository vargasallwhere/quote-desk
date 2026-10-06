const assert = require("node:assert/strict");
const vm = require("node:vm");

async function runTests(html) {
  const openPO = html.slice(html.indexOf("async function openPO("), html.indexOf("function showOrder("));
  const bodyFunction = html.slice(html.indexOf("function confirmationPhone("), html.indexOf("function composer("));
  const flush = () => new Promise(resolve => setImmediate(resolve));

  function setup() {
    const pending = new Map(), rendered = [], elements = new Map();
    const context = {
      cur: "", req: 0, order: { recipient: { phone: "old-phone" } }, tinfo: null,
      bar() {}, localStorage: { setItem() {} }, esc: String,
      stopStatusUpdates() {}, startStatusUpdates() {},
      $(key) { if (!elements.has(key)) elements.set(key, {}); return elements.get(key); },
      showOrder() {}, showCountry() {}, showCto() {},
      fetch(url) { return new Promise((resolve, reject) => pending.set(url, { resolve, reject })); },
    };
    context.showThreads = data => rendered.push({ data, order: context.order });
    vm.createContext(context);
    vm.runInContext(openPO + "\n" + bodyFunction, context);
    const reply = (url, data) => pending.get(url).resolve({ json: async () => data });
    return { context, pending, rendered, reply };
  }

  {
    const t = setup();
    await t.context.openPO("first");
    assert.equal(t.context.order, null, "Old order must be cleared immediately");
    t.reply("/api/threads/first", { name: "first" });
    await flush();
    assert.equal(t.rendered.length, 0, "Gmail must wait for current recipient data");
    t.reply("/api/order/first", { recipient: { phone: "+61400000001" } });
    await flush();
    assert.equal(t.rendered[0].order.recipient.phone, "+61400000001");
  }
  {
    const t = setup();
    await t.context.openPO("first");
    await t.context.openPO("second");
    t.reply("/api/threads/first", { name: "first" });
    t.reply("/api/order/second", { recipient: { phone: "+61400000002" } });
    t.reply("/api/threads/second", { name: "second" });
    await flush();
    t.reply("/api/order/first", { recipient: { phone: "old-phone" } });
    await flush();
    assert.equal(t.rendered.length, 1, "Late responses cannot overwrite a newer order");
    assert.equal(t.rendered[0].data.name, "second");
    assert.equal(t.context.order.recipient.phone, "+61400000002");
  }
  {
    const t = setup();
    await t.context.openPO("failed");
    t.reply("/api/threads/failed", {});
    t.pending.get("/api/order/failed").reject(new Error("Order unavailable"));
    await flush();
    assert.equal(t.rendered[0].order, null);
    assert.equal(t.context.confirmationBody(t.context.order, null), "");
    assert.equal(t.context.confirmationBody({ error: "Not found" }, null), "");
  }
  {
    const t = setup();
    const text = t.context.confirmationBody({ recipient: { phone: " +61400000003 " } }, null);
    assert.equal(text, "Thank you. This order is confirmed, please process it.\n\n+61400000003\n\nBest,\nSara");
    const saved = "My edited confirmation\n\nOn Monday someone wrote:\nPrevious message";
    assert.equal(t.context.confirmationBody({ recipient: { phone: "+61400000003" } }, { text: saved }), "My edited confirmation");
    const missingPhone = t.context.confirmationBody({ confirmation_phone: "", recipient: { phone: "warehouse-phone" } }, null);
    assert.equal(missingPhone.includes("warehouse-phone"), false, "Warehouse fallback cannot be used as the recipient phone");
  }
  console.log("Confirmation loading tests passed (race, switching, failure, phone source, saved draft).");
}

module.exports = runTests;
if (require.main === module) {
  const fs = require("node:fs");
  const path = require("node:path");
  runTests(fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8")).catch(error => {
    console.error(error);
    process.exitCode = 1;
  });
}
