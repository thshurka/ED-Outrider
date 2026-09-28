// Page smoke test: node tests/page_smoke.js <port> [path-to-node_modules-with-jsdom]
// Needs jsdom (npm install jsdom). Loads the page from a running server and checks it renders.
const port = process.argv[2] || 8025;
const mods = process.argv[3] || "node_modules";
const {JSDOM} = require(require("path").resolve(mods, "jsdom"));
const base = `http://127.0.0.1:${port}/`; const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const html = await (await fetch(base)).text(); const errors = [];
  const dom = new JSDOM(html, {url: base, runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, base), o); w.addEventListener("error", e => errors.push(e.message)); }});
  const d = dom.window.document;
  for (let i = 0; i < 60 && !d.querySelector("#sub") ; i++) await sleep(500);
  await sleep(3000);
  const ok = errors.length === 0 && /known within/.test(d.querySelector("#sub").textContent);
  console.log(ok ? "OK" : "FAIL", "|", d.querySelector("#sub").textContent.slice(0, 80), "| errors:", errors);
  process.exit(ok ? 0 : 1);
})();
