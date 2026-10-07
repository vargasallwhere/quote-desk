const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const source = html.slice(html.indexOf("function catalogWarningsHtml("), html.indexOf("const fmt="));
const elements = { "#order": {}, "#po": {} };
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const context = {
  $: key => elements[key], esc, hl: esc, cur: "161880-1-JUST",
  statusText: String, statusCheckedText: String, warrantyHtml: () => "Test warranty",
};
vm.createContext(context);
vm.runInContext(source, context);
const base = {
  order_number: "161880-1-JUST", recipient: {}, purchaser: {},
  order_items: [{ name: "Samsung Essential S3", qty: 2, mpn: "", mpn_source: "unavailable" }],
};
context.showOrder(base);
assert.match(elements["#order"].innerHTML, /2 × Samsung Essential S3/);
assert.match(elements["#order"].innerHTML, /MPN unavailable/);
context.showOrder({
  ...base,
  order_items: [{ name: "Dell Keyboard", qty: 2, mpn: "KM3322W-R-UK", mpn_source: "order_snapshot" }],
  catalog_warnings: [{ sku: "16699", message: "Catalog authentication was rejected (HTTP 401).",
    mpn_source: "order_snapshot" }],
});
assert.match(elements["#order"].innerHTML, /KM3322W-R-UK/);
assert.match(elements["#order"].innerHTML, /catalog not verified/);
assert.match(elements["#order"].innerHTML, /HTTP 401/);
assert.match(elements["#order"].innerHTML, /Using structured order-snapshot MPN/);
assert.doesNotMatch(context.catalogWarningsHtml([{ sku: "<script>", message: "<script>" }]), /<script>/);
context.showOrder({
  ...base, order_items: [{ name: "Samsung", qty: 2, mpn: "LS24D310EAUXXU", mpn_source: "catalog" }],
  catalog_warnings: [],
});
assert.match(elements["#order"].innerHTML, /LS24D310EAUXXU/);
assert.doesNotMatch(elements["#order"].innerHTML, /catalog not verified/);
context.showOrder(base, [{ sku: "10237", message: "Catalog was unavailable for this quote." }]);
assert.match(elements["#order"].innerHTML, /when the quote was generated/);
assert.match(elements["#order"].innerHTML, /unavailable for this quote/);
console.log("Catalog display checks passed: MPNs, visible unresolved items, outage diagnostics, escaped content.");
