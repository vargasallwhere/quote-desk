const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("index.html", "utf8");
const source = html.slice(html.indexOf("function uniq("), html.indexOf('$("#bAr").onclick='));

function setup(popup = {}) {
  const elements = new Map();
  const $ = key => {
    if (!elements.has(key)) elements.set(key, {value:"vendor alternative",textContent:""});
    return elements.get(key);
  };
  const calls = [];
  const context = {
    $, esc: String, cur: "TEST-PO", tinfo: {items:[
      {sku:"1",product_name:"First"}, {sku:"1",product_name:"Duplicate"}, {sku:"2",product_name:"Second"}
    ]},
    catalogWarningsHtml: () => "", window:{open:()=>popup},
    document: {querySelectorAll:()=>[{value:"0"},{value:"2"}]},
    fetch: async (url, options) => { calls.push({url,options}); return {ok:true,json:async()=>({url:"/alt-review?session=test"})};}
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {context, $, calls};
}

(async () => {
  const popup = {close(){}};
  const t = setup(popup);
  t.$("#rbody").value = "Unsaved vendor reply";
  t.$("#bAlt").onclick();
  assert.match(t.$("#apbox").innerHTML, /First/);
  assert.doesNotMatch(t.$("#apbox").innerHTML, /Duplicate/);
  assert.match(t.$("#apbox").innerHTML, /Second/);
  await t.$("#apGo").onclick();
  assert.equal(t.calls[0].url, "/api/alt-review");
  assert.deepEqual(JSON.parse(t.calls[0].options.body), {po:"TEST-PO",items:[0,2],text:"vendor alternative"});
  assert.equal(popup.location, "/alt-review?session=test");
  assert.equal(t.$("#rbody").value, "Unsaved vendor reply");
  assert.equal(t.calls.length, 1);
  const blocked = setup(null);
  blocked.$("#bAlt").onclick();
  await blocked.$("#apGo").onclick();
  assert.match(blocked.$("#apStat").textContent, /Allow popups/);
  assert.equal(blocked.calls.length, 0);
  const error = setup({close(){}});
  error.context.fetch = async () => ({ok:false,json:async()=>({error:"Order lookup failed"})});
  error.$("#bAlt").onclick();
  await error.$("#apGo").onclick();
  assert.match(error.$("#apStat").textContent, /Order lookup failed/);
  assert.doesNotMatch(error.$("#apStat").textContent, /Scout/);
  const configSource = html.slice(html.lastIndexOf('fetch("/api/config")'), html.lastIndexOf("</script>"));
  const buttons = {bAlt:{hidden:false}, bPr:{hidden:false}, bAp:{hidden:false}};
  const config = {fetch:async()=>({json:async()=>({scout:false})}),document:{getElementById:id=>buttons[id]}};
  vm.createContext(config);
  vm.runInContext(configSource,config);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(buttons.bAlt.hidden,false);
  assert.equal(buttons.bPr.hidden,true);
  assert.equal(buttons.bAp.hidden,true);
  console.log("Alternative picker checks passed: standalone button, distinct SKUs, popup blocking, errors, no reply mutations.");
})().catch(error=>{console.error(error);process.exitCode=1});
