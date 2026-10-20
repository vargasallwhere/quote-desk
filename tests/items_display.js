const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const elements = {"#order": {}, "#po": {}};
const context = {
  $: key => elements[key], cur: "MOCK",
  statusText: String, statusCheckedText: String, warrantyHtml: () => "Unchanged warranty",
};
vm.createContext(context);
// Use production highlighting and escaping, not test substitutes.
vm.runInContext(
  html.slice(html.indexOf("const esc="), html.indexOf("function hlDom(")) +
  html.slice(html.indexOf("function catalogWarningsHtml("), html.indexOf("const fmt=")),
  context);
const item = (overrides = {}) => ({
  sku: "MAC", qty: 1, name: 'MacBook Pro 14-inch M4 16GB 512GB Silver US English',
  mpn: "MC123LL/A", mpn_source: "catalog", catalog: {status: "ok"}, ...overrides,
});
const grouped = lines => context.itemDisplayEntries(lines);
const render = lines => context.itemsHtml(lines);
const summary = lines => JSON.parse(JSON.stringify(grouped(lines).map(i => [i.sku, i.qty, i.name])));

assert.equal(render([]), "—");
assert.match(render([item()]), /^1x MacBook/);
const eight = Array.from({length: 8}, () => item());
assert.equal(grouped(eight).length, 1);
assert.equal(grouped(eight)[0].qty, 8);
assert.match(render(eight), /^8x MacBook/);
assert.equal((render(eight).match(/MC123LL\/A/g) || []).length, 1);
for (const kind of ["cpu", "mem", "ssd", "color", "kb", "size", "mpn"])
  assert.match(render(eight), new RegExp('class="hl hl-' + kind + '"'));
assert.doesNotMatch(render(eight), /not verified|unavailable/);
const mixed = [
  item({qty: 2}), item({sku: "OTHER", qty: 3}), item({qty: 4}),
  item({sku: "THIRD"}), item({sku: "OTHER", qty: 5}),
];
assert.deepEqual(summary(mixed).map(i => i.slice(0, 2)), [["MAC", 6], ["OTHER", 8], ["THIRD", 1]]);
// Same name and MPN never merge different SKUs, including case/whitespace differences.
assert.equal(grouped(["MAC", "OTHER", "mac", " MAC "].map(sku => item({sku}))).length, 4);
const changed = item({name: "Different name", mpn: "OTHER-MPN", price: 99, qty: 3});
assert.equal(grouped([item(), changed]).length, 1);
assert.equal(grouped([item(), changed])[0].qty, 4);
assert.equal(grouped([item(), changed])[0].mpn, "MC123LL/A");
assert.match(render([item(), changed]), /3x Different name · OTHER-MPN · Unit price \$99/);

for (const sku of ["", "   ", null, undefined]) {
  const lines = [item({sku}), item({sku, qty: 2})];
  assert.equal(grouped(lines).length, 2);
  assert.match(render(lines), /^1x /);
  assert.match(render(lines), /<br>2x /);
}
const snapshot = item({mpn: "SNAPSHOT", mpn_source: "order_snapshot"});
const unavailable = item({mpn: "", mpn_source: "unavailable"});
assert.match(render([item(), snapshot]), /some source lines use order snapshot; catalog not verified/);
assert.match(render([snapshot, item()]), /SNAPSHOT \(order snapshot; catalog not verified\)/);
assert.match(render([item(), unavailable]), /MPN unavailable on some source lines/);
assert.match(render([item(), unavailable]), /catalog not verified/);
assert.match(render([unavailable, item()]), /MPN unavailable/);
assert.match(render([unavailable, item()]), /MC123LL/);
// Catalog-confirmed null MPNs remain unavailable, without implying a lookup failure.
assert.match(render([item({mpn: ""})]), /MPN unavailable/);
assert.doesNotMatch(render([item({mpn: ""})]), /not verified/);
assert.match(render([item(), item({mpn_source: "legacy_description"})]), /catalog not verified/);

const unsafe = item({name: '<img src=x onerror="alert(1)"> & M4', mpn: '<script>"&', qty: '<svg>'});
assert.match(render([unsafe]), /^&lt;svg&gt;x &lt;img/);
assert.match(render([unsafe]), /&lt;script&gt;&quot;&amp;/);
assert.doesNotMatch(render([unsafe]), /<img|<script|<svg/);
const dangerousSku = [item({sku: "__proto__"}), item({sku: "__proto__"})];
assert.equal(grouped(dangerousSku)[0].qty, 2);
assert.equal(grouped([item({sku: '<script>'}), item({sku: '<script>'})])[0].qty, 2);

const base = {
  order_number: "MOCK", recipient: {}, purchaser: {}, order_items: [item(), snapshot, unavailable],
  catalog_warnings: [
    {sku: "MAC", message: "First source failed", mpn_source: "order_snapshot"},
    {sku: "MAC", message: "Second source failed <script>", mpn_source: "unavailable"},
  ],
};
const quoteWarnings = [{sku: "MAC", message: "Quote lookup failed"}];
const before = JSON.stringify({base, quoteWarnings});
function freeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
}
freeze(base); freeze(quoteWarnings);
context.showOrder(base, quoteWarnings);
const first = elements["#order"].innerHTML;
assert.equal((first.match(/3x MacBook/g) || []).length, 1);
for (const text of ["First source failed", "Second source failed &lt;script&gt;",
  "Using structured order-snapshot MPN", "Quote lookup failed", "when the quote was generated",
  "MPN unavailable on some source lines", "catalog not verified", "Unchanged warranty"])
  assert.ok(first.includes(text), text);
assert.doesNotMatch(first, /<script>/);
context.showOrder(base, quoteWarnings);
assert.equal(elements["#order"].innerHTML, first);
assert.equal(JSON.stringify({base, quoteWarnings}), before);
assert.notEqual(grouped(base.order_items)[0], base.order_items[0]);
context.showOrder({...base, order_items: [], catalog_warnings: []});
assert.match(elements["#order"].innerHTML, /<dt>Items<\/dt><dd>—<\/dd>/);
console.log("Items checks passed: SKU grouping, quantities, ordering, metadata, caveats, diagnostics, highlighting, escaping and immutable source data.");
