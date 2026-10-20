const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync(require("node:path").join(__dirname, "..", "index.html"), "utf8");
const context = {};
vm.createContext(context);
vm.runInContext(html.slice(html.indexOf("function composerState("), html.indexOf("function composer(")), context);
const msg = (id, labels, attachments = []) => ({ id, labels, attachments });
const draft = msg("draft", ["DRAFT"]), other = msg("other", ["DRAFT"]);
const vendor = msg("vendor", ["INBOX"], [{ name: "quote.pdf", type: "application/pdf" }]);
const sent = msg("sent", ["SENT"]), noQuote = msg("noquote", ["INBOX"]);
for (const [messages, mode, selected] of [
  [[draft], "quote", draft],
  [[other, draft], "quote", draft],
  [[sent, vendor, other, draft], "confirmation", draft],
  [[vendor], "confirmation", undefined],
  [[vendor, draft, sent], "waiting", null],
  [[vendor, draft, noQuote], "noquote", null],
  [[], "empty", null],
]) {
  const before = JSON.stringify(messages);
  const state = context.composerState({ messages });
  assert.equal(state.mode, mode);
  assert.equal(state.draft, selected);
  assert.equal(JSON.stringify(messages), before, "Selecting an editor must not mutate thread data");
  const visible = messages.filter(m => !state.draft || m.id !== state.draft.id);
  assert.equal(visible.length, messages.length - (selected ? 1 : 0));
  if (messages.includes(other)) assert.ok(visible.includes(other), "Distinct drafts stay in history");
}
console.log("Draft selection checks passed: exact identity, eligibility, distinct drafts, original data.");
