// Page smoke test: node tests/page_smoke.js <port> [path-to-node_modules-with-jsdom]
// Needs jsdom (npm install jsdom). Loads the page from a running server, checks it renders, then opens
// every view in turn and fails on any script error or a view that stays empty.
const port = process.argv[2] || 8025;
const mods = process.argv[3] || "node_modules";
const {JSDOM} = require(require("path").resolve(mods, "jsdom"));
const base = `http://127.0.0.1:${port}/`; const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const html = await (await fetch(base)).text(); const errors = [];
  const dom = new JSDOM(html, {url: base, runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = (u, o) => fetch(new URL(u, base), o); w.addEventListener("error", e => errors.push(e.message));
      w.localStorage.clear();
      w.scrollBy = () => {};
    }});
  const d = dom.window.document;
  for (let i = 0; i < 60 && !d.querySelector("#sub") ; i++) await sleep(500);
  await sleep(3000);
  const ok = errors.length === 0 && /known within/.test(d.querySelector("#sub").textContent);
  console.log(ok ? "OK" : "FAIL", "| header |", d.querySelector("#sub").textContent.slice(0, 80), "| errors:", errors);
  // every view: [button, element that must end up with content]
  const views = [["overview", "#ovPanes"], ["near", "#rows"], ["here", "#hereRows"], ["bio", "#bioRows"], ["bm", "#bmTable"],
                 ["search", "#searchForm"], ["hist", "#histRows"], ["log", "#logRows"], ["mat", "#matGrid"], ["firsts", "#firstsRows"], ["now", "#nowView"]];
  let allOk = ok;
  for (const [v, sel] of views) {
    const btn = d.querySelector(`[data-view="${v}"]`);
    if (!btn) { console.log("FAIL | no view button", v); allOk = false; continue; }
    const before = errors.length;
    btn.click();
    await sleep(2500);
    const el = d.querySelector(sel);
    const filled = el && el.textContent.trim().length > 0 && !/^loading/.test(el.textContent.trim());
    const good = filled && errors.length === before;
    allOk = allOk && good;
    console.log(good ? "OK" : "FAIL", "|", v.padEnd(8), "|", (el ? el.textContent.trim().replace(/\s+/g, " ").slice(0, 90) : "missing " + sel), errors.slice(before));
  }
  // the schematic toggle inside Here (Now mode hides the view buttons: tap it to go back first)
  if (!d.getElementById("nowView").hidden) { d.getElementById("nowView").click(); await sleep(500); }
  d.querySelector('[data-view="here"]').click(); await sleep(1500);
  const tog = d.querySelector('[data-mode="schematic"]');
  if (tog) {
    const before = errors.length; tog.click(); await sleep(1500);
    const sch = d.querySelector("#hereSchematic");
    const good = sch && !sch.hidden && sch.querySelectorAll(".disc").length > 0 && errors.length === before;
    allOk = allOk && good;
    console.log(good ? "OK" : "FAIL", "| schematic |", sch ? sch.querySelectorAll(".disc").length + " discs" : "missing", errors.slice(before));
    // split on, then tree: the top half becomes the tree and the schematic stays below
    const before2 = errors.length;
    d.querySelector('[data-mode="split"]').click(); await sleep(500);
    d.querySelector('[data-mode="text"]').click(); await sleep(1000);
    const treeRows = d.querySelectorAll("#hereRows tr[data-body]").length, indented = d.querySelectorAll("#hereRows .tind").length;
    const schKept = !d.querySelector("#hereSchematic").hidden && !d.querySelector("#hereTable").hidden;
    const good2 = treeRows > 0 && indented > 0 && schKept && errors.length === before2;
    allOk = allOk && good2;
    console.log(good2 ? "OK" : "FAIL", "| tree+split |", `${treeRows} rows, ${indented} indented, schematic kept: ${schKept}`, errors.slice(before2));
    d.querySelector('[data-mode="list"]').click();
  } else { console.log("FAIL | no schematic toggle"); allOk = false; }
  process.exit(allOk ? 0 : 1);
})();
