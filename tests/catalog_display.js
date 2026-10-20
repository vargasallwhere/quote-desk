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
assert.match(elements["#order"].innerHTML, /2x Samsung Essential S3/);
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
const warning = (overrides={}) => ({sku:"137",status:"invalid_data",
  message:"The catalog returned invalid product data.",mpn_source:"unavailable",
  quantity:1,...overrides});
const five = Array.from({length:5},()=>warning());
assert.equal(context.catalogWarningsHtml(five),
  '<div class="err" role="status"><small>5x SKU 137: The catalog returned invalid product data.</small></div>');
assert.match(context.catalogWarningsHtml([warning({quantity:2}),warning({quantity:3})]), /5x SKU 137/);
const distinct = context.catalogWarningsHtml([warning(),
  warning({message:"Other failure <script>"}),warning({mpn_source:"order_snapshot"}),
  warning({sku:"137 "}),warning({sku:"abc"}),warning({sku:"ABC"})]);
assert.equal((distinct.match(/<small>/g)||[]).length,6);
assert.match(distinct,/Other failure &lt;script&gt;/);
assert.match(distinct,/Using structured order-snapshot MPN/);
for(const sku of ["", " ", null, undefined])
  assert.equal((context.catalogWarningsHtml([warning({sku}),warning({sku})]).match(/<small>/g)||[]).length,2);
const legacy=context.catalogWarningsHtml([warning(),warning({quantity:undefined})]);
assert.doesNotMatch(legacy,/\dx SKU/);
assert.match(legacy,/Affected quantity unavailable/);
const before=JSON.stringify(five);
five.forEach(Object.freeze);Object.freeze(five);
context.showOrder({...base,catalog_warnings:five},five);
assert.equal(JSON.stringify(five),before);
assert.equal((elements["#order"].innerHTML.match(/5x SKU 137/g)||[]).length,2);
assert.match(elements["#order"].innerHTML,/Current-order catalog diagnostics/);
console.log("Catalog display checks passed: MPNs, visible unresolved items, outage diagnostics, escaped content.");
