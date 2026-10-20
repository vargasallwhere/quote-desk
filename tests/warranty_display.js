const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const source = html.slice(html.indexOf("function warrantyHtml("), html.indexOf('let focusK=""'));
// Exercise the production escaping helper, not a more permissive test substitute.
const escSource = html.slice(html.indexOf("const esc="), html.indexOf("\n", html.indexOf("const esc=")));
const context = {};
vm.createContext(context);
vm.runInContext(escSource + "\n" + source, context);
assert.equal(context.warrantyHtml(null), "—");
assert.equal(context.warrantyHtml({ devices: [], lines: [] }), "—");
const rendered = context.warrantyHtml({
  devices: [
    { name: "Apple MacBook", plan: "Add protection plan", qty: 8 },
    { name: "Apple MacBook", plan: "Plan Alpha", qty: 4 },
    { name: "Apple MacBook", plan: "Plan <Beta>", qty: 5 },
  ],
  lines: [{ name: "Standalone warranty", sku: "TEST", qty: 2, price: 55.7 }],
});
assert.match(rendered, /8 × Apple MacBook/);
assert.match(rendered, /4 × Apple MacBook/);
assert.match(rendered, /5 × Apple MacBook/);
assert.match(rendered, /Add protection plan/);
assert.match(rendered, /Plan Alpha/);
assert.match(rendered, /Plan &lt;Beta&gt;/);
assert.doesNotMatch(rendered, /<Beta>/);
assert.match(rendered, /<span class="chip ok">Add protection plan<\/span>/);
assert.match(rendered, /<span class="chip plain">Plan Alpha<\/span>/);
assert.match(rendered, /<b>2x Standalone warranty<\/b>/);
assert.match(rendered, /SKU TEST · Unit price \$55.70/);
assert.doesNotMatch(rendered, /qty /);

const warranty = (overrides={}) => ({
  name: "AppleCare+ - extended service agreement - 3 years",
  sku: "CARE-3", qty: 1, price: 55.7, ...overrides,
});
const display = lines => context.warrantyHtml({ devices: [], lines });
const ten = Array.from({ length: 10 }, () => warranty());
assert.equal(display(ten), '<p style="margin:6px 0 0"><b>10x AppleCare+ - extended service agreement - 3 years</b><small>SKU CARE-3 · Unit price $55.70</small></p>');
assert.match(display([warranty(), warranty()]), /<b>2x AppleCare/);
assert.match(display([warranty({qty: 3}), warranty({qty: 7})]), /<b>10x AppleCare/);
assert.match(display([warranty()]), /<b>AppleCare/);
assert.doesNotMatch(display([warranty()]), /1x |qty 1/);

// Interleaved products retain first-seen order; every identity field matters.
const mixed = [
  warranty({qty: 2}), warranty({sku: "OTHER"}), warranty({qty: 4}),
  warranty({name: "Other warranty"}), warranty({price: 60}),
  warranty({sku: "OTHER", qty: 2}), warranty({price: 55.704}),
];
const mixedHtml = display(mixed);
assert.deepEqual([...mixedHtml.matchAll(/<b>(.*?)<\/b>/g)].map(m => m[1]), [
  "6x " + warranty().name, "3x " + warranty().name, "Other warranty",
  warranty().name, warranty().name,
]);
assert.equal((mixedHtml.match(/Unit price \$55.70/g)||[]).length, 4);
assert.match(mixedHtml, /Unit price \$60.00/);

for(const sku of ["", "   ", null, undefined]){
  const missing = display([warranty({sku}), warranty({sku})]);
  assert.equal((missing.match(/<b>/g)||[]).length, 2);
  assert.doesNotMatch(missing, /2x /);
}
const unsafe = warranty({name: '<img src=x onerror="alert(1)"> & warranty', sku: '<script>"&'});
const safe = display([unsafe, {...unsafe}]);
assert.match(safe, /2x &lt;img src=x onerror=&quot;alert\(1\)&quot;&gt; &amp; warranty/);
assert.match(safe, /SKU &lt;script&gt;&quot;&amp;/);
assert.doesNotMatch(safe, /<img|<script/);

const original = {devices: [{name: "Device", plan: "Plan Alpha", qty: 2}], lines: mixed};
const before = JSON.stringify(original);
original.lines.forEach(Object.freeze);
Object.freeze(original.lines);
Object.freeze(original.devices[0]);
Object.freeze(original.devices);
Object.freeze(original);
const first = context.warrantyHtml(original);
assert.equal(context.warrantyHtml(original), first);
assert.equal(JSON.stringify(original), before);
assert.equal(context.warrantyHtml({devices: original.devices, lines: []}),
  '2 × Device… <span class="chip plain">Plan Alpha</span>');
console.log("Warranty display checks passed: consolidation, quantities, ordering, distinct identities, missing SKUs, immutability, empty/single states, escaping, and protection-plan badges.");
