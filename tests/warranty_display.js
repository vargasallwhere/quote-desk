const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const source = html.slice(html.indexOf("function warrantyHtml("), html.indexOf('let focusK=""'));
const esc = value => String(value).replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const context = { esc };
vm.createContext(context);
vm.runInContext(source, context);
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
assert.match(rendered, /Standalone warranty/);
assert.match(rendered, /qty 2 · \$55.70/);
console.log("Warranty display checks passed: distinct plans, covered quantities, standalone products, escaping.");
