const assert = require("node:assert/strict");
const vm = require("node:vm");

async function runTests(html) {
  const source = html.slice(html.indexOf("function statusText("), html.indexOf("async function openPO("));
  function setup() {
    const elements = {
      "#order-status": { textContent: "Pending Approval" },
      "#status-check": { textContent: "Previously checked" },
      "#rbody": { value: "My unsaved reply" },
    };
    const events = {}, calls = [];
    let resolveRequest;
    const context = {
      req: 1, cur: "123456-1-TEST",
      order: { status: "PENDING_APPROVAL", recipient: { phone: "test-phone" } },
      statusTimer: null, statusInFlight: null,
      $: key => elements[key],
      document: { hidden: false, addEventListener: (event, fn) => { events[event] = fn; } },
      window: { addEventListener: (event, fn) => { events[event] = fn; } },
      setInterval(fn, delay) { context.poll = fn; context.delay = delay; return 1; },
      clearInterval() { context.stopped = true; },
      fetch(url, options) { calls.push({ url, options }); return new Promise(resolve => { resolveRequest = resolve; }); },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    const respond = (data, ok = true) => resolveRequest({ ok, json: async () => data });
    return { context, elements, events, calls, respond };
  }
  {
    const t = setup(), originalOrder = t.context.order;
    const request = t.context.refreshOrderStatus();
    const overlapping = t.context.refreshOrderStatus();
    assert.equal(t.calls.length, 1, "Checks cannot overlap for the same order");
    t.respond({ status: "QUOTE_IN_PROGRESS", status_checked_at: 1000 });
    await request; await overlapping;
    assert.equal(t.elements["#order-status"].textContent, "Quote In Progress");
    assert.ok(t.elements["#status-check"].textContent.startsWith("Checked "));
    assert.equal(t.elements["#rbody"].value, "My unsaved reply");
    assert.equal(t.context.order, originalOrder, "Status updates must not rebuild the order or composer");
    assert.equal(t.calls[0].options.cache, "no-store");
  }
  {
    const t = setup(), request = t.context.refreshOrderStatus();
    t.respond({ error: "Service unavailable" }, false);
    await request;
    assert.equal(t.elements["#order-status"].textContent, "Pending Approval");
    assert.match(t.elements["#status-check"].textContent, /last known status/);
    assert.equal(t.elements["#rbody"].value, "My unsaved reply");
  }
  {
    const t = setup(), request = t.context.refreshOrderStatus();
    t.context.req = 2; t.context.cur = "654321-1-NEXT";
    t.context.order = { status: "SHIPPED" };
    t.elements["#order-status"].textContent = "Shipped";
    t.respond({ status: "QUOTE_IN_PROGRESS", status_checked_at: 1000 });
    await request;
    assert.equal(t.context.order.status, "SHIPPED");
    assert.equal(t.elements["#order-status"].textContent, "Shipped");
  }
  {
    const t = setup();
    t.context.startStatusUpdates(t.context.cur, t.context.req);
    assert.equal(t.context.delay, 15000);
    t.context.document.hidden = true;
    await t.context.poll();
    assert.equal(t.calls.length, 0);
    t.context.document.hidden = false;
    const request = t.events.focus();
    t.respond({ status: "QUOTE_IN_PROGRESS", status_checked_at: 1000 });
    await request;
    assert.equal(t.elements["#order-status"].textContent, "Quote In Progress");
    t.context.stopStatusUpdates();
    assert.equal(t.context.statusTimer, null);
  }
  return { passed: true, checks: ["fresh status", "no draft changes", "uncached requests", "failures", "order switching", "visibility", "focus"] };
}

module.exports = runTests;
if (require.main === module) {
  const fs = require("node:fs"), path = require("node:path");
  runTests(fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8"))
    .then(console.log).catch(error => { console.error(error); process.exitCode = 1; });
}
