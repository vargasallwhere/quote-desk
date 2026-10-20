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
  assert.match(t.$("#apbox").innerHTML, /2x First/);
  assert.match(t.$("#apbox").innerHTML, /1x Duplicate/);
  assert.match(t.$("#apbox").innerHTML, /Second/);
  await t.$("#apGo").onclick();
  assert.equal(t.calls[0].url, "/api/alt-review");
  assert.deepEqual(JSON.parse(t.calls[0].options.body), {po:"TEST-PO",items:[0,2],text:"vendor alternative"});
  assert.equal(popup.location, "/alt-review?session=test");
  assert.equal(t.$("#rbody").value, "Unsaved vendor reply");
  assert.equal(t.calls.length, 1);
  const items=[
    {sku:"137",product_name:"First <script>",quantity:2,protection_plan:"Plan <Alpha>",price:10},
    {sku:"OTHER",product_name:"Second",quantity:4},
    {sku:"137",product_name:"Changed",quantity:3,protection_plan:"Plan Beta",price:20},
    ...[""," ",null,undefined,"abc","ABC"].map(sku=>({sku,product_name:"Unknown",quantity:1}))
  ];
  const before=JSON.stringify(items);
  items.forEach(Object.freeze);Object.freeze(items);
  t.context.tinfo.items=items;
  const grouped=t.context.uniq(items);
  assert.deepEqual(JSON.parse(JSON.stringify(grouped.map(([it,i])=>[it.quantity,i]))),
    [[5,0],[4,1],[1,3],[1,4],[1,5],[1,6],[1,7],[1,8]]);
  // Use production escaping for labels, while submitted indices still refer to originals.
  t.context.esc=value=>String(value??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  t.$("#bAlt").onclick();
  const picker=t.$("#apbox").innerHTML;
  assert.match(picker,/5x First &lt;script&gt;/);
  assert.match(picker,/2x First &lt;script&gt; · Unit price \$10 · Plan &lt;Alpha&gt;/);
  assert.match(picker,/3x Changed · Unit price \$20 · Plan Beta/);
  assert.doesNotMatch(picker,/<script>/);
  assert.equal(JSON.stringify(items),before);
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
