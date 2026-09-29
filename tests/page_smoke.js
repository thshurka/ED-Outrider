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
  // the schematic toggle inside Here (Now mode hides the view buttons: ✕ back first)
  if (!d.getElementById("nowView").hidden) { d.getElementById("nowBack").click(); await sleep(500); }
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
  // a payload the page cannot draw (systems not a list: render() throws) must not stop the polling: the
  // Data tile says so, and the next long poll still goes out
  {
    const w = dom.window, realFetch = w.fetch; let nearby = 0, injected = false;
    const good = JSON.stringify(w.eval("data")), bad = Object.assign(JSON.parse(good), {systems: 7});
    w.fetch = (u, o) => {
      if (String(u).startsWith("api/nearby")) {
        nearby++;
        if (!injected) { injected = true; return Promise.resolve(new Response(JSON.stringify(bad), {status: 200, headers: {"Content-Type": "application/json"}})); }
      }
      return realFetch(u, o);
    };
    const before = errors.length, consoleError = w.console.error; w.console.error = () => {};   // the page logs the throw
    w.eval("poll()");   // a second loop, fed the bad payload first
    await sleep(1500);
    const status = d.getElementById("statusLine").textContent;
    const goodP = injected && nearby >= 2 && /page error/.test(status);
    allOk = allOk && goodP;
    console.log(goodP ? "OK" : "FAIL", "| bad payload |", `polls after it: ${nearby - 1}, status: ${status.slice(0, 80)}`, errors.slice(before));
    w.fetch = realFetch; w.console.error = consoleError;
    w.eval(`data = ${good}; render()`);   // the bad payload stays until the next change: the tests below need a good one
  }
  // values: a logged species is priced as itself (x5 on a first footfall), a lost one says so, a genus with
  // samples under way is listed once, and a jet-cone charge boosts only the first jump of a trip
  {
    const w = dom.window, before = errors.length;
    const pop = w.eval(`bodyPopHtml({name: "X 1", type: "Planet", bio: 2, genera: ["Bacterium"], value_parts: {bio_factor: 5},
      bio_guess: [{genus: "Bacterium", best: "Bacterium Nebulus", value: 9116600, species: ["Nebulus", "Cerbrus"]}],
      organics: [{genus: "Bacterium", species: "Bacterium Cerbrus", samples: 3, done: true, lost: false, value: 1689800},
                 {genus: "Stratum", species: "Stratum Tectonicas", samples: 3, done: false, lost: true, value: 19010800}]})`);
    const leave = w.eval(`leavingText({bio_pending: [{body: "A 1", signals: 2, genera: ["Stratum", "Bacterium"], partial: {Stratum: 2}, potential: null}], unmapped: []})`);
    // F31: a run under way on a body with no DSS still names the signals nobody has identified
    const noDss = w.eval(`leavingText({bio_pending: [{body: "B 7", signals: 2, genera: null, partial: {Stratum: 1}, potential: 5e6}], unmapped: []})`)
      .replace(/<[^>]+>/g, "");
    const saved = w.eval("[data.jump_range, data.boost]");
    w.eval("data.jump_range = 50; data.boost = 4");
    const jumps = w.eval("[jumpsFor(150), jumpsFor(400)]");
    w.eval(`data.jump_range = ${JSON.stringify(saved[0])}; data.boost = ${JSON.stringify(saved[1])}`);
    const goodV = pop.includes("8.4M") && !pop.includes("9.1M") && /Stratum Tectonicas lost ✗/.test(pop)
      && (leave.match(/Stratum/g) || []).length === 1 && jumps.join() === "1,5" && errors.length === before
      && noDss.includes("B 7 (Stratum 1/3, 2 signals not DSS'd)");
    allOk = allOk && goodV;
    console.log(goodV ? "OK" : "FAIL", "| values |", `jumps ${jumps.join("/")}, leaving: ${leave.replace(/<[^>]+>/g, "").slice(0, 70)}`, errors.slice(before));
  }
  // click to copy: a Here body name copies that name, the current system (a .copy span) its name, and an
  // element without data-name copies nothing (it used to copy "undefined")
  {
    const w = dom.window, before = errors.length, copied = [], realCopy = w.copyText;
    if (!d.getElementById("nowView").hidden) { d.getElementById("nowBack").click(); await sleep(300); }
    d.querySelector('[data-view="here"]').click(); await sleep(1000);
    w.copyText = t => copied.push(t);
    const td = d.querySelector("#hereRows td.name");
    if (td) td.click();   // also opens the body panel, which redraws the header: look the system name up after
    const sys = d.querySelector("#here .copy");
    if (sys) sys.click();
    const stray = d.createElement("span"); stray.className = "copy"; d.body.appendChild(stray); stray.click(); stray.remove();
    w.copyText = realCopy; w.eval("closeBody()");
    const want = [td && td.closest("tr").dataset.body, sys && sys.dataset.name].filter(Boolean);
    const goodC = want.length === 2 && copied.join("|") === want.join("|") && errors.length === before;
    allOk = allOk && goodC;
    console.log(goodC ? "OK" : "FAIL", "| copy |", `copied ${JSON.stringify(copied)}`, errors.slice(before));
  }
  // a failed /api/log says so (not 'loading…' forever) and the next load tries again
  {
    const w = dom.window, realFetch = w.fetch, before = errors.length;
    w.fetch = (u, o) => String(u).startsWith("api/log")
      ? Promise.resolve(new Response(JSON.stringify({error: "boom"}), {status: 500, headers: {"Content-Type": "application/json"}}))
      : realFetch(u, o);
    await w.eval("loadLog(true)");
    const failed = d.getElementById("lStatus").textContent, keyCleared = w.eval("L.key === null");
    w.fetch = realFetch;
    await w.eval("loadLog()");
    const again = d.getElementById("lStatus").textContent;
    const goodL = /log failed: boom/.test(failed) && keyCleared && /\d+ events/.test(again) && errors.length === before;
    allOk = allOk && goodL;
    console.log(goodL ? "OK" : "FAIL", "| log error |", `${failed} -> ${again}`, errors.slice(before));
  }
  // robustness: an errored system lookup is asked again once due, a search whose polls keep failing stops
  // saying 'searching…', the unsold thresholds show the configured values, Materials refetches after a jump
  {
    const w = dom.window, realFetch = w.fetch, realST = w.setTimeout, before = errors.length, asked = [];
    let sysFail = true;
    w.fetch = (u, o) => {
      const s = String(u); asked.push(s.split("?")[0]);
      if (s === "api/system/999") return Promise.resolve(new Response(JSON.stringify(sysFail ? {error: "Spansh timed out"} : {id64: "999", bodies: [{name: "A"}]}),
        {status: sysFail ? 502 : 200, headers: {"Content-Type": "application/json"}}));
      if (s === "api/search") return Promise.reject(new TypeError("fetch failed"));
      return realFetch(u, o);
    };
    const e1 = await w.eval('systemFor("999")');
    w.eval('sysRetryAt["999"] = 1'); sysFail = false;             // due now
    const e2 = await w.eval('systemFor("999")');
    const goodS = !!e1.error && e2.bodies && e2.bodies.length === 1 && asked.filter(x => x === "api/system/999").length === 2;
    w.setTimeout = (f, ms) => realST(f, Math.min(ms || 0, 5));    // the retry back-off, sped up
    w.eval('search = {running: true, status: "searching…", results: []}; pollSearch()');
    await sleep(500);
    w.setTimeout = realST;
    const sr = w.eval("search"), goodP = !sr.running && /lost track of the search/.test(sr.status);
    w.eval("search = null; render()");
    w.fetch = realFetch;
    const th = w.eval(`(() => { const u = data.unsold; data.unsold = Object.assign({}, u, {thresholds: [123, 456]}); fillThresholds();
      const v = [document.getElementById("unsoldWarn").value, document.getElementById("unsoldUrgent").value]; data.unsold = u; fillThresholds(); return v; })()`);
    const goodT = th.join() === "123,456";
    asked.length = 0; w.fetch = (u, o) => { asked.push(String(u).split("?")[0]); return realFetch(u, o); };
    d.querySelector('[data-view="mat"]').click(); await sleep(1500);
    const saved = w.eval("data.position.id64");
    w.eval("data.position.id64 = 42; render()"); await sleep(800);
    w.eval(`data.position.id64 = ${JSON.stringify(saved)}; render()`); await sleep(800);
    w.fetch = realFetch;
    const goodM = asked.filter(x => x === "api/materials").length >= 2;
    const goodR = goodS && goodP && goodT && goodM && errors.length === before;
    allOk = allOk && goodR;
    console.log(goodR ? "OK" : "FAIL", "| retries |", `system retried ${goodS}, search stops ${goodP} (${sr.status}), thresholds ${th.join("/")}, materials refetched ${goodM}`, errors.slice(before));
  }
  // the speech queue: danger jumps ahead of queued finds (and cuts short the one playing), a find about a system
  // you have left is dropped, heat is said once per cooldown; the pure pick/expire rules too
  {
    const w = dom.window, before = errors.length, spoken = [], stopped = [];
    const realSay = w.sayNow, savedPos = w.eval("data.position && data.position.id64");
    const savedFlags = w.eval("[speechOn, isSpeaker]");
    w.eval("speechOn = true; isSpeaker = true");   // the worker drops alert lines while speech is off (F25)
    w.sayNow = async item => {   // a stand-in voice: records the line and 'speaks' for 60 ms
      const cur = w.eval("speechNow = {prio: " + item.prio + ", stop() { this.stopped = true; }}");
      spoken.push(item.words); await sleep(60);
      if (cur.stopped) stopped.push(item.words);
      w.eval("speechNow = null");
    };
    // finds are tied to the system you are in: a live payload arriving mid-test replaces the position, so try again
    let goodPrio = false, goodStale = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      const d0 = w.eval("data"); spoken.length = stopped.length = 0;
      w.eval("speechItems = []; speechLast = {}; data.position.id64 = 42");
      for (const t of ["Find one.", "Find two.", "Find three."]) w.eval(`speak(${JSON.stringify(t)}, {kind: "find"})`);
      w.eval('speak("Hull at 40 percent.", {kind: "hull", tag: "hull"})');
      await sleep(400);
      goodPrio = spoken.join("|") === "Find one.|Hull at 40 percent.|Find two.|Find three." && stopped.join() === "Find one.";
      spoken.length = 0;
      w.eval('speak("Something you asked for.")');                  // holds the voice while the ship moves
      w.eval('speak("Find on the old system.", {kind: "find"})');
      w.eval("data.position.id64 = 43");
      await sleep(300);
      goodStale = spoken.join("|") === "Something you asked for.";
      if (w.eval("data") === d0) break;
    }
    spoken.length = 0;
    w.eval('speak("Heat damage.", {kind: "hull", tag: "heat"}); speak("Heat damage.", {kind: "hull", tag: "heat"})');
    await sleep(300);
    const goodCool = spoken.length === 1;
    w.sayNow = realSay; w.eval(`if ([42, 43].includes(data.position.id64)) data.position.id64 = ${JSON.stringify(savedPos)}; speechLast = {}`);
    w.eval(`[speechOn, isSpeaker] = ${JSON.stringify(savedFlags)}`);
    const pure = w.eval(`(() => {
      const now = 100000, it = (prio, at, extra) => Object.assign({prio, at, notBefore: at, sys: null}, extra);
      const q = [it(3, 1), it(2, 2), it(0, 5), it(0, 3)];
      const kept = speechExpire([it(1, now - 25000), it(3, now, {sys: 7}), it(3, now, {sys: 8}), it(2, now, {still: () => false})], now, 7);
      return [speechPick(q), speechPick([]), kept.length, kept[0] && kept[0].sys, speechPrio("carrier", "carrier_departs"), speechPrio("carrier", null)].join();
    })()`);
    const goodPure = pure === "3,-1,1,7,0,2";
    const goodQ = goodPrio && goodStale && goodCool && goodPure && errors.length === before;
    allOk = allOk && goodQ;
    console.log(goodQ ? "OK" : "FAIL", "| speech queue |", `priority ${goodPrio}, stale dropped ${goodStale}, cooldown ${goodCool}, pick/expire ${pure}`, errors.slice(before));
  }
  // a jump clears the queue: lines queued (and the one playing) about the old system go, the FSD line is said,
  // danger lines and lines asked for by hand stay
  {
    const w = dom.window, before = errors.length, spoken = [], stopped = [];
    const realSay = w.sayNow, saved = w.eval("[speechOn, isSpeaker]");
    w.eval("speechOn = true; isSpeaker = true; speechItems = []; speechLast = {}");
    w.sayNow = async item => {
      const cur = w.eval("speechNow = {prio: " + item.prio + ", kind: " + JSON.stringify(item.kind) + ", stop() { this.stopped = true; }}");
      spoken.push(item.words); await sleep(80);
      if (cur.stopped) stopped.push(item.words);
      w.eval("speechNow = null");
    };
    w.eval('speak("Leaving with unfinished work.", {kind: "leaving"})');   // playing when the charge starts
    w.eval('speak("Codex entry.", {kind: "codex"}); speak("Species complete.", {kind: "sampling"}); speak("Fuel low.", {kind: "fuel", tag: "fuel_low"})');
    await sleep(20);
    w.eval('clearForJump(); speak("Frame Shift Drive charging to jump to X.", {kind: "jump", tag: "fsd_charge"})');
    await sleep(500);
    const pure = w.eval('speechForJump([{prio: 0, kind: "fuel"}, {prio: 2, kind: "leaving"}, {prio: 3, kind: "codex"}, {prio: 1, kind: "manual"}]).map(i => i.kind).join()') === "fuel,manual";
    const ok = spoken.join("|") === "Leaving with unfinished work.|Fuel low.|Frame Shift Drive charging to jump to X." &&
               stopped.join() === "Leaving with unfinished work." && pure;
    w.sayNow = realSay; w.eval(`speechOn = ${saved[0]}; isSpeaker = ${saved[1]}; speechItems = []`);
    console.log(ok ? "OK" : "FAIL", "| jump clears speech |", spoken.join(" / "), "| cut:", stopped.join(), errors.slice(before));
  }
  // one speaker: a window that is not the speaker still shows the alert but plays and says nothing; the
  // ▶ voice button still speaks; a danger line comes only from business and never swears
  {
    const w = dom.window, before = errors.length, calls = [];
    const realPlay = w.play, realSpeak = w.speak;
    w.play = n => calls.push("play " + n); w.speak = t => calls.push("speak");
    w.eval("soundOn = true; speechOn = true; alertSound.hull = true; alertSpeak.hull = true; isSpeaker = false");
    w.eval('alertOut("hull", "Hull 40%", "", {say: "Hull at 40 percent."})');
    await sleep(50);
    const quiet = calls.length === 0 && w.eval("lastAlert && lastAlert.title") === "Hull 40%";
    d.getElementById("trySpeak").click();
    const tryWorks = calls.join() === "speak";
    calls.length = 0; w.eval("isSpeaker = true");
    w.eval('alertOut("hull", "Hull 40%", "", {say: "Hull at 40 percent."})');
    await sleep(50);
    const loud = calls.sort().join() === "play danger,speak";
    w.play = realPlay; w.speak = realSpeak; w.eval("speechOn = false");
    const lib = w.eval("JSON.stringify(speechLib)");
    w.eval(`speechLib = {styles: {business: "Business", sarcastic: "Sarcastic"}, lines: {
      hull: {business: ["B {pct}"], sarcastic: ["S {pct}"], sarcastic_profane: ["P {pct}"]},
      heat: {sarcastic: ["S heat"], sarcastic_profane: ["P heat"]},
      find_body: {business: ["B find"], sarcastic: ["S find"], sarcastic_profane: ["P find"]}}}`);
    w.localStorage.setItem("speechStyles", '["sarcastic"]'); w.localStorage.setItem("speechProfanity", "true");
    w.localStorage.setItem("speechProfanityPct", "100");
    const many = k => new Set(Array.from({length: 30}, () => w.eval(`line(${JSON.stringify(k)}, {pct: 40})`)));
    const hull = [...many("hull")].join(), heat = [...many("heat")].join(), find = [...many("find_body")].join();
    w.localStorage.setItem("speechDangerBusiness", "false");
    const hullOff = [...many("hull")].join();
    for (const k of ["speechStyles", "speechProfanity", "speechProfanityPct", "speechDangerBusiness"]) w.localStorage.removeItem(k);
    w.eval(`speechLib = ${lib}`);
    const goodBiz = hull === "B 40" && heat === "S heat" && find === "P find" && hullOff === "P 40";
    const goodS = quiet && tryWorks && loud && goodBiz && errors.length === before;
    allOk = allOk && goodS;
    console.log(goodS ? "OK" : "FAIL", "| one speaker |", `silent elsewhere ${quiet}, try works ${tryWorks}, speaks here ${loud}, danger business: hull ${hull}, heat ${heat}, find ${find}, tick off ${hullOff}`, errors.slice(before));
  }
  // Batch 6 call-outs: the words the page composes from each moment's facts, your thresholds applied, and the
  // honk left unspoken behind the arrival briefing (plain wording: no speech.json lines while this runs)
  {
    const w = dom.window, before = errors.length, said = [];
    const realSpeak = w.speak, realPlay = w.play;
    w.speak = t => said.push(t); w.play = () => {};
    const got = JSON.parse(w.eval(`(() => {
      const lib = speechLib, saved = {unsold: data.unsold, ship: data.ship, moments: data.moments}, was = {...alertSpeak};
      const flags = [speechOn, isSpeaker]; speechLib = {styles: {}, lines: {}};
      speechOn = true; isSpeaker = true; for (const k of Object.keys(alertSpeak)) alertSpeak[k] = true;
      const clean = {body_count: 3, scanned: 3, unscanned: 0, honked: true, all_found: true, bio_pending: [], unmapped_valuable: [], clean: false,
                     unmapped: [{body: "1", subtype: "Icy body", terraformable: false, increment: 1000, special: false}]};
      const rich = {...clean, unmapped: [{body: "A 3", subtype: "High metal content world", terraformable: true, increment: 1900000, special: true}],
                    bio_pending: [{body: "C 2", signals: 2, genera: null, partial: {}, potential: 19000000, codex_new: false}]};
      data.unsold = {total: 480000000, thresholds: [50000000, 250000000]}; data.ship = {rebuy: 150000000};
      const pure = {
        worth: [worthSaying(clean), worthSaying(rich)],
        g: [highGStakes({landable: true, gravity: 2.6}), highGStakes({landable: true, gravity: 1.5}), highGStakes({landable: false, gravity: 3})],
        brief: [arrivalBriefText({undiscovered: true, body_count: 14, star_class: "K", worth: [], bio: null}),
                arrivalBriefText({undiscovered: false, visits: 1, status: "explored", in_spansh: true, body_count: 5, star_class: "DA",
                                  worth: [{body: "2", subtype: "Icy body", value: 1000}], bio: null}),
                arrivalBriefText({undiscovered: false, visits: 1, status: "partial", in_spansh: true, body_count: 12, star_class: "M",
                                  worth: [{body: "A 2", subtype: "Earth-like world", notable: "ELW", value: 1400000}], bio: {body: "B 1", value: 1000}})],
        recap: [recapText({jumps: 2, ly: 40}), recapText({jumps: 142, ly: 3100.4, firsts: 12, mapped: 0, samples: 9, codex_new: 0})],
        left: [leftBodyText({partial: {Stratum: 2}, untouched: [{genus: "Tussock", value: 14000000}], touched: false}),
               leftBodyText({partial: {Stratum: 2}, untouched: [{genus: "Tussock", value: 14000000}, {genus: "Fungoida", value: 1000}], touched: true, factor: 1}),
               leftBodyText({partial: {}, untouched: [{genus: "Tussock", value: 14000000}], touched: false})],
        bioLeft: [bioLeftText({partial: {}, untouched: [{genus: "Bacterium", value: 12000000}, {genus: "Fungoida", value: 1000}]}),
                  bioLeftText({partial: {}, untouched: [{genus: "Fungoida", value: 1000}]})],
        hazard: [hazardSaid("N"), hazardSaid("K")],
      };
      const s0 = lastMomentSeq, mk = (i, m) => Object.assign({seq: s0 + i, ts: "2026-01-01T00:00:00Z"}, m);
      data.moments = [mk(1, {kind: "honk", ok: true, brief: true, system: "X", bodies: 14, all_found: false}),
        mk(2, {kind: "arrival_brief", system: "9", system_name: "X", undiscovered: true, body_count: 14, star_class: "K", worth: [], bio: null}),
        mk(3, {kind: "fss_done", count: 3, leaving: clean}), mk(4, {kind: "fss_done", count: 3, leaving: rich}),
        mk(5, {kind: "approach", body: "A 4", landable: true, gravity: 2.6, signals: 0}),
        mk(6, {kind: "approach", body: "A 5", landable: true, gravity: 1.2, signals: 0}),
        mk(7, {kind: "scoop_end", full: false, pct: 95}), mk(8, {kind: "scoop_end", full: false, pct: 50}),
        mk(9, {kind: "scoop_end", full: true, pct: 100, jumps: 8}),
        mk(10, {kind: "bio_done", system: "9", body: "A 4", species: "Stratum Tectonicas", value: 19200000, partial: {}, untouched: []}),
        mk(11, {kind: "left_body", system: "9", body: "A 4", touched: false, partial: {}, untouched: [{genus: "Tussock", value: 14000000}]}),
        mk(12, {kind: "game_exit", session: {jumps: 4, ly: 30}}),
        mk(13, {kind: "fsd_charge", system: "Y", star_class: "N"})];
      const lvl = lastUnsoldLevel; lastUnsoldLevel = "urgent";   // the made-up haul must not sound the unsold alert
      onData();
      lastUnsoldLevel = lvl; lastMomentSeq = s0;   // the real moments still to come keep their numbers
      Object.assign(data, saved); Object.assign(alertSpeak, was); [speechOn, isSpeaker] = flags; speechLib = lib;
      return JSON.stringify(pure);
    })()`));
    w.speak = realSpeak; w.play = realPlay;
    // a personality with its own voice in speech.json: the line carries the voice and pace to the queue
    const styled = w.eval(`(() => { const lib = speechLib;
      speechLib = {styles: {sarcastic: {label: "S", voice: "en_US-ryan-high", speed: 1.2}}, lines: {game_start: {sarcastic: ["Hi"]}}};
      localStorage.setItem("speechStyles", '["sarcastic"]'); lineStyle = null;
      const t = line("game_start"), sv = styleVoice(lineStyle), plain = styleVoice("business");
      localStorage.removeItem("speechStyles"); speechLib = lib;
      return [t, sv.voice, sv.pace, plain.voice, plain.pace].join(); })()`);
    got.styled = styled;
    const want = {
      worth: ["", "A 3, terraformable high metal content world, 1.9M to map and biology on C 2, up to 19.0M"],
      g: [{gravity: "2.6", value: "480.0M", rebuys: "3.2"}, null, null],
      brief: ["Undiscovered. 14 bodies. Scoopable K star.", "Fully scanned. 5 bodies. White dwarf. Nothing here for you.",
              "Known. 12 bodies. Scoopable M star. The Earth-like world at A 2 is unmapped, 1.4M."],
      recap: ["", "142 jumps, 3,100 light-years, 12 systems nobody had seen and 9 species sampled"],
      left: ["Stratum 2 of 3", "Stratum 2 of 3, and Tussock untouched, up to 14.0M", ""],   // Fungoida: under the bio threshold
      bioLeft: ["Bacterium, plus 1 small one", "only 1 small one"],   // F32: never "the last one" with a genus left
      hazard: ["Neutron star ahead: throttle down on arrival, mind the jet cone.", ""],
      styled: "Hi,en_US-ryan-high,1.2,,1",
    };
    const wantSaid = ["Undiscovered. 14 bodies. Scoopable K star.", "All 3 found. Nothing worth staying for.",
      "All 3 found. Worth it: A 3, terraformable high metal content world, 1.9M to map and biology on C 2, up to 19.0M.",
      "2.6 g. 480.0M credits aboard. Land gently.", "Scooping stopped at 50 percent.", "Tank full.",
      "Stratum Tectonicas complete. That was the last one here.", "Session over: 4 jumps and 30 light-years.",
      "Frame Shift Drive charging to jump to Y. Neutron star ahead: throttle down on arrival, mind the jet cone."];
    const goodPure = JSON.stringify(got) === JSON.stringify(want), goodSaid = JSON.stringify(said) === JSON.stringify(wantSaid);
    const goodB = goodPure && goodSaid && errors.length === before;
    allOk = allOk && goodB;
    console.log(goodB ? "OK" : "FAIL", "| call-outs |", `words ${goodPure ? "ok" : JSON.stringify(got)}, spoken ${goodSaid ? said.length + " lines" : JSON.stringify(said)}`, errors.slice(before));
  }
  // Batch 7: the unreported horizon (empty, normal, sphere_cut), the streak strip and its once-per-streak lines,
  // the suggested order, the backup line, portable settings, the Last session card and bio in ship losses
  {
    const w = dom.window, before = errors.length, said = [];
    const realSpeak = w.speak, realPlay = w.play;
    w.speak = t => said.push(t); w.play = () => {};
    const got = JSON.parse(w.eval(`(() => {
      const saved = {systems: data.systems, sphere_cut: data.sphere_cut, status: data.status, radius: data.radius, position: data.position,
                     arrival: data.arrival, streak: data.streak, backup: data.backup, last_session: data.last_session};
      const lib = speechLib, flags = [speechOn, isSpeaker, alertSpeak.arrival, lastArrival, lastPosId];
      speechLib = {styles: {}, lines: {}}; speechOn = true; isSpeaker = true; alertSpeak.arrival = true;
      data.position = Object.assign({}, data.position, {id64: 1}); data.status = "ok"; data.radius = 25;
      const sys = (id, d, visited, extra) => Object.assign({id64: id, name: "S" + id, distance: d, visited, source: "spansh", main_class: "K", main_scoopable: true}, extra);
      data.sphere_cut = null; data.systems = [];
      const empty = horizon().text;
      data.systems = [sys(1, 0, true), sys(2, 3.1, true), sys(3, 4.8, false), sys(4, 2.0, false, {source: "route"}), sys(5, 9, false)];
      const normal = horizon().text;
      data.sphere_cut = 7.5; data.systems = [sys(2, 3.1, true), sys(6, 9.2, false, {source: "edsm"})];
      const cut = horizon().text;
      data.status = "asking Spansh about systems near X…";
      const asking = horizon();
      data.status = "ok"; data.sphere_cut = null;
      const strip = streakHtml({arrivals: [{ts: "2026-01-01T00:00:00Z", id: "1", name: "A", verdict: "new", firsts: 3, value: 1500000},
        {ts: "2026-01-01T00:01:00Z", id: "2", name: "B", verdict: "complete", firsts: 0, value: 0},
        {ts: "2026-01-01T00:02:00Z", id: "3", name: "C", verdict: null, firsts: 0, value: 0}], new: 1, total: 3});
      const dots = (strip.match(/class="sk /g) || []).length;
      // the streak lines: said once, when a run reaches its threshold
      const arr = (seq, verdict, st, undiscovered) => ({seq, ts: "2026-01-01T00:00:00Z", id64: "1", name: "N" + seq, undiscovered, first_visit: true,
                                                     wrong: false, announced: null, sound: null, verdict, streak: st});
      const run = a => { data.arrival = a; lastArrival = a.seq - 1; const lvl = lastUnsoldLevel; lastUnsoldLevel = unsoldLevel(data.unsold); onData(); lastUnsoldLevel = lvl; };
      run(arr(9001, "new", {new: 4, known: 0}, true)); run(arr(9002, "new", {new: 5, known: 0}, true));
      run(arr(9003, "complete", {new: 0, known: 10}, false)); run(arr(9004, "complete", {new: 0, known: 11}, false));
      localStorage.setItem("streakCfg", JSON.stringify({known: 0}));
      run(arr(9005, "complete", {new: 0, known: 10}, false));
      localStorage.removeItem("streakCfg");
      // the suggested order: nearest first, value per minute breaking ties, no distance last, a muted skip?
      const l = {body_count: 4, scanned: 4, unscanned: 0, honked: true, all_found: true, unmapped_valuable: [], clean: false,
        unmapped: [{body: "A 9", subtype: "High metal content world", increment: 510000, special: false, dist_ls: 90000},
                   {body: "A 1", subtype: "High metal content world", increment: 800000, special: false, dist_ls: 500},
                   {body: "B 2", subtype: "High metal content world", increment: 700000, special: false, dist_ls: null}],
        bio_pending: [{body: "A 3", signals: 1, genera: ["Stratum"], partial: {}, potential: 19000000, codex_new: false, dist_ls: 500}]};
      const order = planItems(l).map(it => it.body + (it.skip ? "?" : ""));
      const mono = [0, 1, 10, 100, 1000, 1999, 2000, 2001, 5000, 50000, 100000, 300000].map(scSeconds).every((t, i, a) => i === 0 || t >= a[i - 1]);
      const list = checklistHtml(l);
      // the backup line: red when the last one failed, amber when overdue
      const bOk = backupHtml({ts: new Date(Date.now() - 3 * 3600000).toISOString(), kept: 7, journals_to: "2026-09-28", every_days: 1});
      const bBad = backupHtml({ts: new Date(Date.now() - 3 * 3600000).toISOString(), kept: 7, every_days: 1, error: "OSError: disk full"});
      const bLate = backupHtml({ts: new Date(Date.now() - 5 * 86400000).toISOString(), kept: 7, every_days: 1});
      // portable settings: the allow-list only, a missing key back to its default; the server copy under localStorage
      localStorage.setItem("bioMinCfg", "5"); localStorage.setItem("view", '"map"');
      const doc = settingsDoc();
      localStorage.setItem("highG", "3");
      const res = applySettings({version: 1, settings: {bioMinCfg: 7, view: "near", bogus: 1}});
      const after = [localStorage.getItem("bioMinCfg"), localStorage.getItem("highG"), localStorage.getItem("view")];
      const bad = applySettings({version: 2, settings: {}});
      localStorage.removeItem("bioMinCfg"); localStorage.removeItem("view");
      const sdSaved = window.SERVER_DEFAULTS;
      window.SERVER_DEFAULTS = {version: 1, settings: {highG: 2.5, view: "map"}};
      const fromServer = [store.get("highG", null), store.get("view", "near")];
      localStorage.setItem("highG", "1.8");
      const localWins = store.get("highG", null);
      localStorage.removeItem("highG"); window.SERVER_DEFAULTS = sdSaved;
      // the Last session card and the Now line
      data.last_session = {start: "2026-01-01T01:00:00Z", end: "2026-01-01T03:00:00Z", jumps: 42, ly: 900.4, max_sol: 1200, firsts: 3, mapped: 2, samples: 1, codex_new: 0, footfalls: 0};
      renderLastSession();
      const card = document.getElementById("lastSession").textContent;
      renderNow();
      const now = document.getElementById("nowView").textContent;
      Object.assign(data, saved); [speechOn, isSpeaker, alertSpeak.arrival, lastArrival, lastPosId] = flags; speechLib = lib;
      renderLastSession();
      return JSON.stringify({empty, normal, cut, asking, dots, strip: strip.replace(/<[^>]+>/g, "").trim(), order, mono, suggested: /suggested order/.test(list), perMin: list.includes("/min"),
              bOk: bOk.replace(/<[^>]+>/g, "").trim(), bBad: /badc/.test(bBad), bLate: /warnc/.test(bLate),
              doc: "bioMinCfg" in doc.settings && !("view" in doc.settings), res, after, bad: bad.error || "", fromServer, localWins, card, now: /Last session: 42 jumps/.test(now)});
    })()`));
    w.speak = realSpeak; w.play = realPlay;
    const lossTxt = w.eval(`(() => { const h = histData; histData = {sessions: [], all_time: null, ledger: {trips: [{start: null, end: "2026-01-02T00:00:00Z", days: null, jumps: 1, ly: 1, firsts: 0, paid: 1, paid_carto: 1, paid_bio: 0,
      losses: [{ts: "2026-01-01T06:00:00Z", ship: true, bodies: 3, firsts: 1, value: 148000000, bio_value: 64000000, bio_runs: 2},
               {ts: "2026-01-01T04:00:00Z", ship: false, bodies: 0, firsts: 0, value: 0, bio_value: 9000000, bio_runs: 1}]}]}};
      renderHistory(); const t = document.getElementById("tripRows").textContent; histData = h; if (h) renderHistory(); return t; })()`);
    const want = {
      empty: "no known unvisited star within 25 ly — any unvisited star on the map within 25 ly is unreported",
      normal: "nearest known unvisited: S3 4.8 ly · K ⛽ — unvisited stars closer than this aren't reported to Spansh or EDSM",
      cut: "nearest known unvisited: S6 9.2 ly (the list is complete only to 7.5 ly) — any unvisited star on the map within 7.5 ly is unreported",
      asking: null, dots: 3, strip: "1/3 new", order: ["A 3", "A 1", "A 9?", "B 2"], mono: true, suggested: true, perMin: true,
      bOk: "backed up 3 h ago · 7 kept · journals to 2026-09-28 back up now", bBad: true, bLate: true,
      doc: true, res: {applied: 1, skipped: ["view", "bogus"]}, after: ["7", null, '"map"'], bad: "not an ED Outrider settings file",
      fromServer: [2.5, "near"], localWins: 1.8,
      card: "Last session 2026-01-01 01:00 → 03:00 UTC · 42 jumps · 900 ly · 3 new systems · 2 mapped · 1 sample · 1,200 ly from Sol at most", now: true,
    };
    const wantSaid = ["N9001 is undiscovered. You are the first here.", "5 undiscovered systems in a row.", "10 known systems in a row. Maybe change heading."];
    const goodLoss = /−212\.0M \(148\.0M carto, 64\.0M bio\)/.test(lossTxt) && /−9\.0M \(9\.0M bio\)/.test(lossTxt);
    const good7 = JSON.stringify(got) === JSON.stringify(want) && JSON.stringify(said) === JSON.stringify(wantSaid) && goodLoss && errors.length === before;
    allOk = allOk && good7;
    console.log(good7 ? "OK" : "FAIL", "| batch 7 |", JSON.stringify(got) === JSON.stringify(want) ? "horizon, strip, order, backup, settings, last session ok" : JSON.stringify(got),
                JSON.stringify(said) === JSON.stringify(wantSaid) ? `streak lines ${said.length}` : JSON.stringify(said), goodLoss ? "losses ok" : lossTxt.slice(0, 200), errors.slice(before));
  }
  // Batch C (the page): what each fix changed, checked on the live page with made-up data
  {
    const w = dom.window, before = errors.length, said = [], toasts = [];
    const realSpeak = w.speak, realPlay = w.play, realToast = w.toast, realFetch = w.fetch;
    w.speak = (t, o) => said.push([t, o || {}]); w.play = () => {}; w.toast = t => toasts.push(t);
    const got = JSON.parse(w.eval(`(() => {
      const saved = {position: data.position, arrival: data.arrival, unsold: data.unsold, ship: data.ship, moments: data.moments,
                     freshness: data.freshness}, hd = hereData, lib = speechLib, was = {...alertSpeak}, cfg = {...alertCfg},
            flags = [speechOn, isSpeaker, soundOn, lastMomentSeq, lastUnsoldLevel];
      speechLib = {styles: {}, lines: {}}; speechOn = true; isSpeaker = true;
      for (const k of Object.keys(alertSpeak)) alertSpeak[k] = true;
      const out = {};
      // F57: an id64 over 2^53 is rounded as a number; the exact string id still matches the arrival and Here
      const big = "9007199254740993";
      const onBody = data.on_body; data.on_body = null;   // landed, Now shows the body instead of the system line
      data.position = Object.assign({}, saved.position, {id64: Number(big), id: big});
      data.arrival = {seq: 1, id64: big, ts: new Date().toISOString(), undiscovered: true, name: "Big"};
      // F23: no all-clear until Here's data is for this system, honked and every body found
      hereData = null; renderNow(); out.checking = /checking…/.test(document.getElementById("nowView").textContent);
      out.undiscovered = /Undiscovered/.test(document.getElementById("nowView").textContent);
      out.shown = shownSystem();
      const lv = (honked, unscanned) => ({honked, unscanned, all_found: honked && !unscanned, body_count: 5, bio_pending: [], unmapped: []});
      const nowFor = l => { hereData = {id64: big, bodies: [], leaving: l}; renderNow(); return document.getElementById("nowView").textContent; };
      out.now = [/Next: honk/.test(nowFor(lv(false, null))), /Next: 3 bodies to find/.test(nowFor(lv(true, 3))),
                 /nothing worth staying for/.test(nowFor(lv(true, 0)))];
      hereData = hd; data.position = saved.position; data.arrival = saved.arrival; data.on_body = onBody;
      // F60, F22, F21, F3, F61
      out.credits = [credits(999600), credits(999950000), credits(999499), credits(999.6), credits(1234567)];
      out.star = [spokenStar("K_OrangeGiant"), spokenStar("A_BlueWhiteSuperGiant"), spokenStar("K")];
      out.ship = [shipLabel("krait_mkii", "krait_mkii"), shipLabel("", "Anaconda"), shipLabel("Out There", "krait_mkii"), shipLabel("explorer_nx")];
      out.bioLeft = [bioLeftText({partial: {}, untouched: [], unidentified: 1}), bioLeftText({partial: {Bacterium: 1}, untouched: [], unidentified: 2})];
      out.brief = [bodyBriefText({signals: 2, factor: 5, bio_options: {genera: ["Stratum", "Bacterium", "Fungoida"], low: 1000000, high: 20000000}}),
                   bodyBriefText({signals: 1, factor: 5, bio_value: 3000000})];
      // F28 and F27: x5 everywhere on an unfootfalled body; a genus sampled without a DSS is not also 'possible'
      const pop = bodyPopHtml({name: "B 1", type: "Planet", bio: 3, genera: [], value_parts: {bio_factor: 5},
        bio_guess: [], bio_options: {low: 2000000, high: 4000000, genera: [{genus: "Bacterium", value: 3000000, species: ["Aurasus"]},
                                                                        {genus: "Fungoida", value: 1000000, species: ["Setisis"]}]},
        organics: [{genus: "Stratum", species: "Stratum Tectonicas", samples: 3, done: true, lost: false, value: 19010800}]});
      out.pop = [pop.includes("2 more signals not identified"), pop.includes("10.0M to 20.0M"), pop.includes("≤15.0M"),
                 !pop.includes("Stratum possible"), pop.includes("95.1M"), !pop.includes("19.0M")];
      // G1.2: the spoken leaving text stops at three
      const many = {bio_pending: [1, 2, 3, 4].map(i => ({body: "C " + i, signals: 1, genera: null, partial: {}, potential: 20000000 + i})),
                    unmapped: [{body: "A 1", subtype: "Water world", terraformable: false, increment: 900000, special: true}]};
      out.leaving = leavingSaid(many);
      // backup: a journal not archived is a warning (amber), a failed zip an error (red); older records too
      const ago = new Date(Date.now() - 3 * 3600000).toISOString();
      const bw = backupHtml({ts: ago, kept: 7, journals_to: "2026-09-28", every_days: 1, warning: "1 journal not archived (Journal.x.log: disk full)"});
      const bOld = backupHtml({ts: ago, kept: 7, every_days: 1, error: "1 journal not archived (Journal.x.log: disk full)", error_ts: ago});
      const bErr = backupHtml({ts: ago, kept: 7, every_days: 1, error: "OSError: disk full"});
      out.backup = [bw.replace(/<[^>]+>/g, "").trim(), /warnc/.test(bw) && !/badc/.test(bw), /warnc/.test(bOld) && !/badc/.test(bOld), /badc/.test(bErr)];
      // F4: the doc carries what this browser inherited from the server copy; F35: a string where a list belongs
      const sd = window.SERVER_DEFAULTS;
      window.SERVER_DEFAULTS = {version: 1, settings: {highG: 2.5, speechStyles: "sarcastic"}};
      const doc = settingsDoc();
      out.doc = [doc.settings.highG, "speechStyles" in doc.settings, Array.isArray(speechStyles())];
      localStorage.setItem("speechStyles", '"sarcastic"');
      out.styles = Array.isArray(speechStyles());
      localStorage.removeItem("speechStyles"); window.SERVER_DEFAULTS = sd;
      const imp = applySettings({version: 1, settings: {speechStyles: "sarcastic", bioMinCfg: 5}});
      out.imp = [imp.applied, imp.skipped.join()];
      localStorage.removeItem("bioMinCfg");
      Object.assign(alertSpeak, was); speechLib = lib; [speechOn, isSpeaker] = flags;
      return JSON.stringify(out);
    })()`));
    // moments: F26 (only a delivered left-body warning spares the leaving alert, and only what it named), F32, F33,
    // F35 (a handler that throws does not stop the next), G1.3 (no sound, no wait before the words)
    const got2 = JSON.parse(w.eval(`(() => {
      const saved = {unsold: data.unsold, ship: data.ship, moments: data.moments}, lib = speechLib, was = {...alertSpeak};
      const flags = [speechOn, isSpeaker, soundOn, lastMomentSeq, lastUnsoldLevel];
      speechLib = {styles: {}, lines: {}}; speechOn = true; isSpeaker = true; soundOn = false;
      for (const k of Object.keys(alertSpeak)) alertSpeak[k] = true;
      data.unsold = {total: 480000000, thresholds: [50000000, 250000000], carto: {estimated_payout: 300000000}, bio: {estimated_value: 180000000}};
      data.ship = {rebuy: 150000000}; lastUnsoldLevel = "urgent";
      const s0 = lastMomentSeq, sys = posId(), mk = (i, m) => Object.assign({seq: s0 + i, ts: new Date().toISOString()}, m);
      leftWarned.clear();
      const run = ms => { data.moments = ms; onData(); };
      run([mk(1, {kind: "left_body", system: sys, body: "A 1", touched: true, partial: {Stratum: 2}, untouched: [{genus: "Tussock", value: 14000000}], unidentified: 0}),
           mk(2, {kind: "approach", body: "A 2", landable: true, gravity: 2.6, signals: 2, factor: 1, bio_value: 4000000})]);
      alertSpeak.sampling = false;   // not spoken, not notified: nothing to spare
      alertSpeak.approach = false;   // F32: the body briefing still goes out on its own
      run([mk(3, {kind: "left_body", system: sys, body: "A 3", touched: true, partial: {Stratum: 1}, untouched: [], unidentified: 0}),
           mk(4, {kind: "approach", body: "A 4", landable: true, gravity: 2.6, signals: 2, factor: 1, bio_value: 4000000}),
           mk(5, {kind: "undocked", station: "FC", has_uc: false, has_vista: false, dock_ts: "2099-01-01T00:00:00Z"})]);
      const warned = leftWarned.get(sys + "|A 1"), noWarn = leftWarned.has(sys + "|A 3");
      const kept = unwarned(sys, {body: "A 1", signals: 3, genera: ["Stratum", "Tussock", "Bacterium"], partial: {Stratum: 2}, potential: 1});
      const gone = unwarned(sys, {body: "A 1", signals: 2, genera: ["Stratum", "Tussock"], partial: {Stratum: 2}, potential: 1});
      const realToast = toast, ce = console.error; let threw = 0;
      toast = () => { threw++; throw new Error("boom"); }; console.error = () => {};   // the page logs the throw
      run([mk(6, {kind: "scan", body: "B 1", subtype: "Earth-like world", notable: "ELW", first_discovered: true, base_value: 3000000}),
           mk(7, {kind: "heat"})]);
      toast = realToast; console.error = ce;
      const seqOk = lastMomentSeq === s0 + 7;
      Object.assign(data, saved); Object.assign(alertSpeak, was); speechLib = lib;
      [speechOn, isSpeaker, soundOn] = flags; lastMomentSeq = s0; lastUnsoldLevel = flags[4]; leftWarned.clear();
      const pe = pageError; pageError = null;
      return JSON.stringify({warned: warned && [...warned.genera].sort().join(), noWarn, kept: kept && kept.genera.join(), gone, threw, seqOk,
                             pageError: /alert scan: boom/.test(pe || "")});
    })()`));
    // F34: a window that heard nothing from the server for over a minute (it slept) takes the next payload as a
    // first one: the moments in it are not announced
    const nSaid = said.length;
    const slept = w.eval(`(() => { const s0 = lastMomentSeq, saved = data.moments, flags = [speechOn, isSpeaker, alertSpeak.hull];
      speechOn = true; isSpeaker = true; alertSpeak.hull = true;
      lastHeard = Date.now() - 120000; heard(true); const flagged = woke;
      data.moments = [{seq: s0 + 1, ts: new Date().toISOString(), kind: "heat"}]; onData();
      const res = flagged && !woke && lastMomentSeq === s0 + 1;
      data.moments = saved; lastMomentSeq = s0; [speechOn, isSpeaker, alertSpeak.hull] = flags; return res; })()`) && said.length === nSaid;
    // G1.3: with the sound on, the voice waits for that sound (the fanfare's chord runs to 1.7 s)
    const nSaid2 = said.length;
    w.eval(`(() => { const f = [speechOn, isSpeaker, soundOn, alertSound.arrival, alertSpeak.arrival]; speechOn = isSpeaker = soundOn = alertSound.arrival = alertSpeak.arrival = true;
      alertOut("arrival", "X: undiscovered", "", {sound: "fanfare", say: "X is undiscovered."}); alertOut("hull", "Hull 40%", "", {say: "Hull."});
      [speechOn, isSpeaker, soundOn, alertSound.arrival, alertSpeak.arrival] = f; })()`);
    const leads = said.splice(nSaid2).map(([, o]) => o.delay).join();
    const words = said.map(([t]) => t), delays = said.map(([, o]) => o.delay || 0);
    // F25: turning speech off empties the queue of alert lines; a line asked for here stays
    const hush = w.eval(`(() => { const q = speechItems; speechItems = [{kind: "find"}, {kind: "manual"}, {kind: "hull"}]; hushSpeech();
      const left = speechItems.map(i => i.kind).join(); speechItems = q; return left; })()`);
    // F64, F65: reset links take focus; a focused Nearby name keeps focus through a redraw
    const keyable = w.eval(`(() => { markKeyable(); const r = document.querySelector("[data-reset]"); return !!r && r.tabIndex === 0 && r.getAttribute("role") === "button"; })()`);
    if (!d.getElementById("nowView").hidden) { d.getElementById("nowBack").click(); await sleep(300); }
    d.querySelector('[data-view="near"]').click(); await sleep(500);
    const focus = w.eval(`(() => { markKeyable(); const td = document.querySelector("#rows td.name[data-name]"); if (!td) return "no rows";
      td.focus(); const name = td.dataset.name; render(); const a = document.activeElement;
      return a !== td && a.matches("td.name") && a.dataset.name === name ? "kept" : "lost: " + (a && a.tagName); })()`);
    // F58, G3.5: a failed request says so
    w.fetch = (u, o) => /api\/(backup|nextstop)/.test(String(u)) ? Promise.reject(new TypeError("fetch failed")) : realFetch(u, o);
    const btn = d.createElement("button"); btn.id = "backupBtn"; d.body.appendChild(btn); btn.click();
    const ns = d.createElement("span"); ns.id = "nsClear"; d.body.appendChild(ns); ns.click();
    await sleep(200); btn.remove(); ns.remove(); w.fetch = realFetch;
    // F63: a long tail keeps the newest 1000 rows and "more" continues below them; F29: it keys on freshness.read
    const newRows = Array.from({length: 5}, (_, i) => ({id: "new|" + i, ts: "2026-01-01T00:00:01Z", cat: "other", event: "Y", summary: ""}));
    w.fetch = (u, o) => String(u).startsWith("api/log") ? Promise.resolve(new Response(JSON.stringify({rows: newRows, newest: "new|0"}),
      {headers: {"Content-Type": "application/json"}})) : realFetch(u, o);
    const tail = await w.eval(`(async () => {
      const saved = {rows: L.rows, next: L.next, newest: L.newest, journal: L.journal, key: L.key, loading: L.loading}, fr = data.freshness;
      L.rows = Array.from({length: 999}, (_, i) => ({id: "old|" + i, ts: "2026-01-01T00:00:00Z", cat: "other", event: "X", summary: ""}));
      L.newest = "old|0"; L.loading = false; L.journal = 1; data.freshness = Object.assign({}, fr, {read: 2});
      await tailLog();
      const res = [L.rows.length, L.next, L.journal];
      data.freshness = fr; Object.assign(L, saved); renderLog();
      return res; })()`);
    w.fetch = realFetch;
    // F30: losses since the last sale (all of them with no sale yet) show as the trip under way
    const trip = w.eval(`(() => { const h = histData; histData = {sessions: [], all_time: null, ledger: {trips: [], since_last_sale: {since: null, days: null, jumps: 3, ly: 40, firsts: 1},
      losses: [{ts: "2026-01-01T06:00:00Z", ship: true, bodies: 3, firsts: 1, value: 40000000, bio_value: 0, bio_runs: 0}]}};
      renderHistory(); const t = document.getElementById("tripRows").textContent; histData = h; if (h) renderHistory(); return t; })()`);
    w.speak = realSpeak; w.play = realPlay; w.toast = realToast;
    // G1.1: browser speech after 15 s goes by what the browser says it is doing, and cancels a line that never
    // ends (Chrome can drop the end event) at a cap from its length, so the next line never queues behind it
    const g11 = await w.eval(`(async () => {
      const ss = window.speechSynthesis, U = window.SpeechSynthesisUtterance, st = window.setTimeout, now = Date.now, tts = data.tts;
      let t = now(), cancels = 0, endAt = Infinity;
      Date.now = () => t;
      window.setTimeout = (f, ms) => { t += ms || 0; if (t >= endAt) window.speechSynthesis.speaking = false; return st(f, 0); };   // time runs as fast as it is waited for
      window.SpeechSynthesisUtterance = function (words) { this.text = words; };
      data.tts = null;
      const say = async end => { window.speechSynthesis = {speaking: true, pending: false, speak() {}, cancel() { cancels++; this.speaking = false; }};
        cancels = 0; const t0 = t; endAt = t0 + end; await sayNow({words: "x".repeat(380), prio: 2, kind: "leaving", pace: 1}); return [t - t0, cancels]; };
      const stuck = await say(Infinity), ends = await say(20000);
      Date.now = now; window.setTimeout = st; window.speechSynthesis = ss; window.SpeechSynthesisUtterance = U; data.tts = tts;
      lastHeard = Date.now(); woke = false;   // a poll during the fast clock must not look like the page slept
      return [stuck[0] > 20000 && stuck[0] <= 61000 && stuck[1] === 1, ends[0] >= 20000 && ends[0] < 21000 && ends[1] === 0, stuck[0], ends[0]]; })()`);
    const want = {checking: true, undiscovered: true, shown: "9007199254740993", now: [true, true, true],
      credits: ["1.0M", "1.00B", "999k", "1k", "1.2M"], star: ["K orange giant", "A blue white supergiant", "K star"],
      ship: ["Krait Mk II", "Anaconda", "Out There", "Caspian Explorer"],
      bioLeft: ["1 more signal not identified", "Bacterium and 2 more signals not identified"],
      brief: ["2 biological signals, 2 of Stratum, Bacterium or Fungoida, 1.0M to 20.0M, first footfall times five",
              "1 biological signal, up to 3.0M, first footfall times five"],
      pop: [true, true, true, true, true, true],
      leaving: "A 1, Water world, 900k to map, biology on C 4, up to 20.0M and biology on C 3, up to 20.0M, and 2 more",
      backup: ["backed up 3 h ago · 1 journal not archived (…) back up now", true, true, true],
      doc: [2.5, false, true], styles: true, imp: [1, "speechStyles"]};
    const want2 = {warned: "Stratum,Tussock", noWarn: false, kept: "Bacterium", gone: null, threw: 1, seqOk: true, pageError: true};
    const wantWords = ["Leaving A 1 unfinished: Stratum 2 of 3, and Tussock untouched, up to 14.0M.", "A 2: 2 biological signals, up to 4.0M. 2.6 g. 480.0M credits aboard. Land gently.",
                       "A 4: 2 biological signals, up to 4.0M.", "Earth-like world, undiscovered, B 1.", "Heat damage."];
    const goodC = JSON.stringify(got) === JSON.stringify(want) && JSON.stringify(got2) === JSON.stringify(want2)
      && JSON.stringify(words) === JSON.stringify(wantWords) && delays.every(x => x === 0) && leads === "1700,900" && g11[0] && g11[1] && slept && hush === "manual" && keyable && focus === "kept"
      && toasts.some(t => /Backup failed: fetch failed/.test(t)) && toasts.some(t => /could not clear the next stop: fetch failed/.test(t))
      && tail.join() === "1000,old|994,2" && /→ now/.test(trip) && /−40\.0M/.test(trip) && errors.length === before;
    allOk = allOk && goodC;
    console.log(goodC ? "OK" : "FAIL", "| batch C |", JSON.stringify(got) === JSON.stringify(want) ? "words, ids, Now, backup, settings ok" : JSON.stringify(got),
                JSON.stringify(got2) === JSON.stringify(want2) ? "moments ok" : JSON.stringify(got2),
                JSON.stringify(words) === JSON.stringify(wantWords) ? `spoken ${words.length}` : JSON.stringify(words), `delays ${delays.join("/")}, leads ${leads}, browser speech ${g11.join("/")}`,
                `slept ${slept}, hush ${hush}, keyable ${keyable}, focus ${focus}, toasts ${JSON.stringify(toasts)}, tail ${tail.join()}, trip ${/→ now/.test(trip)}`, errors.slice(before));
  }
  // F62: a refused search POST says so instead of showing the previous search's results as the new ones, and an
  // older result (a poll sent before the POST) is not taken for the search just started
  {
    const w = dom.window, realFetch = w.fetch, realST = w.setTimeout, before = errors.length;
    const json = (body, status) => Promise.resolve(new Response(JSON.stringify(body), {status, headers: {"Content-Type": "application/json"}}));
    const old = {seq: 3, running: false, status: "7 systems (old search)", results: [{id: "1", name: "Old", distance: 1, matches: {}}]};
    let postReply = [{error: "refused (simulated)"}, 403], gets = [], seen = [];
    w.fetch = (u, o) => {
      if (String(u) !== "api/search") return realFetch(u, o);
      if (o && o.method === "POST") return json(...postReply);
      return json(gets.length > 1 ? gets.shift() : gets[0] || old, 200);
    };
    w.setTimeout = (f, ms) => realST(f, Math.min(ms || 0, 5));
    const submit = () => d.getElementById("searchForm").dispatchEvent(new w.Event("submit", {cancelable: true}));
    submit(); await sleep(300);
    const refused = w.eval("({status: search.status, n: (search.results || []).length})");
    postReply = [{seq: 5}, 200];
    gets = [old, old, {seq: 5, running: false, status: "2 systems (new search)", results: []}];
    w.__seen = seen; w.eval("window.__render = render; render = function () { window.__seen.push(search && search.status); return window.__render(); }");
    submit(); await sleep(400);
    w.eval("render = window.__render");
    w.setTimeout = realST; w.fetch = realFetch;
    const fresh = w.eval("({status: search.status, seq: search.seq})");
    w.eval("search = null; searchWant = 0; render()");
    const goodF = /search failed: refused \(simulated\)/.test(refused.status) && refused.n === 0
      && fresh.seq === 5 && /new search/.test(fresh.status) && seen.length > 0 && !seen.some(x => /old search/.test(x || "")) && errors.length === before;
    allOk = allOk && goodF;
    console.log(goodF ? "OK" : "FAIL", "| search refused |", `refused: ${refused.status} (${refused.n} rows), then: ${fresh.status}`, errors.slice(before));
  }
  // Batch 3 (review 2026-09-30b): the page's fixes, each on made-up data, everything restored afterwards
  {
    const w = dom.window, realFetch = w.fetch, before = errors.length, said = [];
    const realSpeak = w.speak, realPlay = w.play;
    w.speak = t => said.push(t); w.play = () => {};
    const json = body => Promise.resolve(new Response(JSON.stringify(body), {headers: {"Content-Type": "application/json"}}));
    const out = JSON.parse(w.eval(`(() => {
      const o = {}, sys = posId();
      // F43: once touched down, a cheap genus the warning left out does not bring the body back in the leaving alert
      const flags = [speechOn, isSpeaker, soundOn, lastMomentSeq, alertSpeak.sampling, alertSpeak.honk], saved = data.moments;
      speechOn = true; isSpeaker = true; soundOn = false; alertSpeak.sampling = true; alertSpeak.honk = true; leftWarned.clear();
      const s0 = lastMomentSeq, mk = (i, m) => Object.assign({seq: s0 + i, ts: new Date().toISOString()}, m);
      data.moments = [mk(1, {kind: "left_body", system: sys, body: "A 3", touched: true, partial: {}, unidentified: 0,
                             untouched: [{genus: "Stratum", value: 19000000}, {genus: "Bacterium", value: 1000000}]}),
                      // F26: a honk never pressed (the map stayed open) is "skipped", not "failed"
                      mk(2, {kind: "honk", ok: false, system: "X", why: "gave up waiting: the galaxy map is open"})];
      onData();
      o.unwarned = unwarned(sys, {body: "A 3", signals: 2, genera: ["Bacterium", "Stratum"], partial: {}, potential: 20000000});
      data.moments = saved; [speechOn, isSpeaker, soundOn] = flags; lastMomentSeq = s0; alertSpeak.sampling = flags[4]; alertSpeak.honk = flags[5]; leftWarned.clear();
      // F47: a failed poll neither refreshes lastHeard nor hides a minute of silence
      const lh = lastHeard, wk = woke;
      lastHeard = Date.now() - 30000; const t0 = lastHeard; heard(false); o.kept = lastHeard === t0 && !woke;
      lastHeard = Date.now() - 120000; heard(false); o.outage = woke;
      lastHeard = lh; woke = wk;
      // F29: no colony distance for the genus, positions recorded: not blamed on missing positions
      const sm = data.sampling;
      data.sampling = {genus: "Newgenus", species: "Newgenus x", samples: 1, need: null, points: 1, to_go: null};
      const sp = samplingHtml(); o.spacing = /spacing unknown for this genus/.test(sp) && !/position unknown/.test(sp);
      data.sampling = {genus: "Stratum", species: "Stratum x", samples: 1, need: 500, points: 0, to_go: null};
      o.spacing2 = /position unknown/.test(samplingHtml());
      data.sampling = sm;
      // F34: the codex mark names the region it is given
      o.region = bodyPopHtml({name: "B 1", type: "Planet", bio: 1, genera: [], organics: [], bio_guess: [],
        bio_options: {low: 1, high: 2, genera: [{genus: "Bacterium", value: 2, species: ["Aurasus"], codex_new: true}]}}, "Norma Arm").includes("new to your codex in Norma Arm");
      // F30, F33: a run under way prices the logged species; gravity reds at your high-g level
      const hd = hereData, hk = hereKey, hg = localStorage.getItem("highG");
      if (hd && !hd.error) {
        localStorage.setItem("highG", "1.5");
        const b0 = hd.bodies.find(b => b.type === "Planet") || hd.bodies[0] || {};
        const fake = Object.assign({}, b0, {name: "Fake 1", type: "Planet", subtype: "Rocky body", gravity: 1.8, bio: 1, genera: ["Stratum"],
          organics: [{genus: "Stratum", species: "Stratum Paleas", samples: 1, done: false, lost: false, value: 1362000}],
          bio_guess: [{genus: "Stratum", best: "Stratum Tectonicas", species: ["Stratum Tectonicas"], value: 19010800}],
          value_parts: {bio_factor: 1}, codex: [], curiosities: [], geo: 0});
        hereData = Object.assign({}, hd, {bodies: [fake], tree: null}); renderHere();
        const row = document.querySelector('#hereRows tr[data-body="Fake 1"]');
        o.here = !!row && row.textContent.includes("1.4M") && !row.textContent.includes("Tectonicas?") && !row.textContent.includes("19.0M")
          && row.querySelectorAll("td")[3].classList.contains("noscoop");
        if (hg === null) localStorage.removeItem("highG"); else localStorage.setItem("highG", hg);
        hereData = hd; hereKey = hk; renderHere();
      } else o.here = "no Here data";
      // F39: injections at cap: nothing is "limiting"; 3 left: the short material is
      const md = matData;
      const mat = craftable => ({rows: [{id: "polonium", name: "Polonium", count: craftable, cap: 150}], snapshot_ts: "2026-01-01T00:00:00Z", ts: "2026-01-01T00:00:00Z",
        synthesis: [{name: "FSD Premium", craftable, materials: [{name: "Polonium", have: craftable, need: 1}]}], sources: {polonium: []}});
      matData = mat(150); renderMat(); const capped = document.getElementById("matSources").innerHTML;
      matData = mat(3); renderMat(); const short = document.getElementById("matSources").innerHTML;
      o.mat = !/limiting/.test(capped) && /limiting/.test(short);
      matData = md; if (md) renderMat();
      // F45: a streak of 1 reads as 2; F48: a null where an object belongs reads as unset
      localStorage.setItem("streakCfg", '{"new": 1}'); o.streak = streakCfg().new; localStorage.removeItem("streakCfg");
      const lg = localStorage.getItem("log"), bs = localStorage.getItem("bioSort");
      localStorage.setItem("log", "null"); localStorage.setItem("bioSort", "null");
      o.nulls = [JSON.stringify(store.get("log", {})), store.get("bioSort", {key: "ts", dir: -1}).key];
      if (lg === null) localStorage.removeItem("log"); else localStorage.setItem("log", lg);
      if (bs === null) localStorage.removeItem("bioSort"); else localStorage.setItem("bioSort", bs);
      const imp = applySettings({version: 1, settings: {bioSort: null}}); o.impNull = imp.skipped.join();
      if (bs !== null) localStorage.setItem("bioSort", bs);
      // F64: a 'saved' that is not a string
      const sd = window.SERVER_DEFAULTS; window.SERVER_DEFAULTS = {version: 1, settings: {}, saved: 1727700000};
      try { drawSettingsServer(); o.saved = true; } catch (e) { o.saved = e.message; }
      window.SERVER_DEFAULTS = sd; drawSettingsServer();
      // F44: a baseline taken while Status.json hides the dock keeps the dock's ts: boarding again says nothing
      const dk = data.docked, dts = data.docked_ts, rid = runId, ldt = lastDockTs;
      data.docked = null; data.docked_ts = "2026-01-01T01:00:00Z"; runId = "not this run"; onData();
      o.dock = lastDockTs;
      data.docked = dk; data.docked_ts = dts; lastDockTs = ldt; if (runId !== rid) runId = rid;
      // F49: a new highlight level redraws the whole page (the header's leaving strip, Now), not only Here
      let renders = 0; const realRender = render; render = function () { renders++; return realRender(); };
      const el = document.getElementById("hlBody"), hl = localStorage.getItem("highlightCfg"), v = el.value;
      el.value = "5000000"; el.onchange();
      render = realRender; o.hlRender = renders > 0;
      if (hl === null) localStorage.removeItem("highlightCfg"); else localStorage.setItem("highlightCfg", hl);
      Object.assign(hlCfg, {body: null, bio: null}, hl ? JSON.parse(hl) : {}); el.value = v; showHl();
      // F38: no "more" without the filters of a good load
      const Ls = {key: L.key, next: L.next, loading: L.loading};
      L.key = null; L.next = "x|1"; L.loading = false; moreLog(); renderLog();
      o.more = !L.loading && document.getElementById("lMore").hidden;
      Object.assign(L, Ls); renderLog();
      return JSON.stringify(o);
    })()`));
    // F28: a thrown on-body fetch is asked again; F37: a failed Here refresh keeps the view and says so;
    // F42: a tail answer clears an old "loading more failed"
    w.fetch = (u, o) => /^api\/system\//.test(String(u)) ? Promise.reject(new TypeError("fetch failed"))
      : String(u).startsWith("api/log") ? json({rows: [], newest: "n|0"}) : realFetch(u, o);
    const out2 = await w.eval(`(async () => {
      const o = {};
      const ob = data.on_body, od = obData, ok = obKey;
      data.on_body = {system: "1", body: "X 1", how: "landed"}; obKey = null; await loadOnBody();
      o.onbody = obKey === null && !!(obData && obData.error);
      data.on_body = ob; obData = od; obKey = ok; renderOnBody();
      const hd = hereData, hk = hereKey;
      if (hd && !hd.error && hd.id64 === shownSystem()) {
        hereKey = null; await loadHere();
        o.here = hereData === hd && /refresh failed/.test(document.getElementById("hereHead").textContent);
        hereRefreshError = null; hereKey = hk; renderHere();
      } else o.here = "no Here data";
      const Ls = {rows: L.rows, next: L.next, newest: L.newest, journal: L.journal, key: L.key, loading: L.loading, error: L.error}, fr = data.freshness;
      L.newest = "old|0"; L.loading = false; L.journal = -1; L.error = "loading more failed: HTTP 502"; L.key = L.key || "days=7";
      await tailLog(); o.logError = L.error;
      Object.assign(L, Ls); renderLog();
      return o; })()`);
    w.fetch = realFetch;
    // F40: a refused search while the previous one is still running keeps saying it failed
    const realST = w.setTimeout;
    w.setTimeout = (f, ms) => realST(f, Math.min(ms || 0, 5));
    let postReply = [{seq: 7}, 200];
    w.fetch = (u, o) => {
      if (String(u) !== "api/search") return realFetch(u, o);
      if (o && o.method === "POST") return Promise.resolve(new Response(JSON.stringify(postReply[0]), {status: postReply[1], headers: {"Content-Type": "application/json"}}));
      return json({seq: 7, running: true, status: "searching (first)", results: []});
    };
    const submit = () => d.getElementById("searchForm").dispatchEvent(new w.Event("submit", {cancelable: true}));
    submit(); await sleep(100);
    postReply = [{error: "refused (simulated)"}, 403];
    submit(); await sleep(300);
    const refused = w.eval("search.status");
    w.setTimeout = realST; w.fetch = realFetch;
    w.eval("search = null; searchWant = 0; searchRefused = false; render()");
    w.speak = realSpeak; w.play = realPlay;
    const want = {unwarned: null, kept: true, outage: true, spacing: true, spacing2: true, region: true, here: true, mat: true,
                  streak: 2, nulls: ["{}", "ts"], impNull: "bioSort", saved: true, dock: "2026-01-01T01:00:00Z", hlRender: true, more: true};
    const want2 = {onbody: true, here: true, logError: null};
    const goodH = JSON.stringify(out) === JSON.stringify(want) && JSON.stringify(out2) === JSON.stringify(want2)
      && said.includes("Honk skipped. The map stayed open.") && /search failed: refused/.test(refused) && errors.length === before;
    allOk = allOk && goodH;
    console.log(goodH ? "OK" : "FAIL", "| batch 3 page |", JSON.stringify(out) === JSON.stringify(want) ? "pure ok" : JSON.stringify(out),
                JSON.stringify(out2) === JSON.stringify(want2) ? "fetches ok" : JSON.stringify(out2), `said ${JSON.stringify(said)}, search ${refused}`, errors.slice(before));
  }
  // Suggestions batch S1: first footfall x5 and gravity in the suggested order and the leaving alert, signals never
  // DSS'd in Left behind, bodies not on Spansh, Now's heading-to line, and what the backup zip holds
  {
    const w = dom.window, before = errors.length;
    const got = JSON.parse(w.eval(`(() => {
      const saved = {position: data.position, destination: data.destination, on_body: data.on_body}, hd = hereData, ld = leftData;
      const strip = h => h.replace(/<[^>]+>/g, "");
      localStorage.setItem("skipFloor", "5000000");
      const b5 = {body: "C 2", signals: 1, genera: ["Stratum"], partial: {}, potential: 12000000, factor: 5, codex_new: false,
                  dist_ls: 90000, gravity: 2.6, atmosphere: "CarbonDioxide"};
      const l = {body_count: 14, scanned: 11, unscanned: 3, honked: true, all_found: false, unmapped_valuable: [], unmapped: [], bio_pending: [b5]};
      const it = planItems(l)[0], plain = planItems({...l, bio_pending: [{...b5, factor: 1}]})[0];
      localStorage.removeItem("skipFloor");
      const o = {skip5: it.skip, skip1: plain.skip, value: it.value, text: strip(planText(it)), highG: /class="warnc"[^>]*>2\.6 g/.test(planText(it)),
                 leaving: strip(leavingText(l)).includes("up to 60.0M 👣×5"), said: leavingSaid(l), worth: worthSaying(l)};
      // bodies not on Spansh: the checklist line and the arrival briefing (a count, never names)
      o.notes = [spanshNote({...l, base_known: 12}), spanshNote({...l, base_known: 14}), spanshNote({...l, base_known: 0}),
                 spanshNote({...l, unscanned: 0, all_found: true, base_known: 14}), spanshNote(l)];
      o.brief = arrivalBriefText({in_spansh: true, body_count: 14, base_known: 12, visits: 1, status: "partial"});
      o.briefOwn = arrivalBriefText({in_spansh: false, body_count: 14, base_known: null, visits: 1, undiscovered: true});
      // Left behind: a body with signals and no DSS
      leftData = {radius: 100, systems: [{id: "5", name: "S5", distance: 12.3, unfound: 0, maps: [], maps_total: 0,
        bio: [{body: "A 4", genera: null, signals: 3, value: 39000000}, {body: "A 6", genera: ["Stratum"], value: 19000000}]}]};
      renderLeft();
      o.left = document.getElementById("leftRows").textContent.replace(/\\s+/g, " ").trim();
      leftData = ld; if (ld) renderLeft();
      // Now: the targeted body gets its own line unless it is the next item (then Next is marked ➜)
      data.position = Object.assign({}, data.position, {id: "77", id64: 77}); data.on_body = null;
      const body = (name, id, extra) => Object.assign({name, body_id: id, type: "Planet", subtype: "Icy body", genera: [], bio: 0, geo: 0,
                                                        dist_ls: 1200, gravity: 0.3, atmosphere: "None", value_max: 0, organics: [], codex: []}, extra);
      hereData = {id64: "77", bodies: [body("A", 0, {type: "Star", subtype: "K (Yellow-Orange) Star", main: true, scoopable: true, dist_ls: 0}),
                                       body("B 1", 7), body("C 2", 9, {dist_ls: 90000})], leaving: l};
      data.destination = {body_id: 7, name: "B 1", near: null};
      renderNow(); o.nowOther = document.getElementById("nowView").textContent;
      data.destination = {body_id: 7, name: "B 1", near: "C 2"};
      renderNow(); o.nowFar = document.getElementById("nowView").textContent;
      data.destination = {body_id: 9, name: "C 2", near: null};
      renderNow(); o.nowHead = document.getElementById("nowView").textContent;
      data.destination = {body_id: 0, name: "A", near: null};
      renderNow(); o.nowStar = document.getElementById("nowView").textContent;
      Object.assign(data, saved); hereData = hd; renderNow();
      o.holds = /holds: x\.sqlite, speech\.json, ed_outrider\.toml/.test(backupHtml({ts: new Date().toISOString(), kept: 3, path: "/b/x.zip",
                                                                                 files: ["x.sqlite", "speech.json", "ed_outrider.toml"]}));
      return JSON.stringify(o); })()`));
    const checks = {
      skip: got.skip5 === false && got.skip1 === true && got.value === 60000000,
      text: got.text.includes("up to 60.0M 👣×5") && got.text.includes("· 2.6 g · CarbonDioxide") && got.highG,
      leaving: got.leaving && /up to 60\.0M with first footfall/.test(got.said) && /up to 60\.0M with first footfall/.test(got.worth),
      notes: JSON.stringify(got.notes) === JSON.stringify(["2 not on Spansh", "all on Spansh, nothing hidden", "none on Spansh", "all on Spansh", ""]),
      brief: got.brief === "Known. 14 bodies. 2 of them not on Spansh." && !/Spansh/.test(got.briefOwn),
      left: got.left.includes("A 4 3 signals, not DSS'd ≤39.0M") && got.left.includes("A 6 Stratum ≤19.0M"),
      now: /➜ B 1 · Icy body · 0\.30 g · 1,200 ls · ~\d+ s · nothing to do here/.test(got.nowOther) && !/ls · ~\d+ s · nothing/.test(got.nowFar)
        && /Next: ➜ bio on C 2/.test(got.nowHead) && !/➜ C 2 ·/.test(got.nowHead) && /➜ A · K \(Yellow-Orange\) Star · 0 ls · ~15 s · scoopable star/.test(got.nowStar),
      holds: got.holds,
    };
    const bad = Object.entries(checks).filter(([, v]) => !v).map(([k]) => k);
    const goodS1 = !bad.length && errors.length === before;
    allOk = allOk && goodS1;
    console.log(goodS1 ? "OK" : "FAIL", "| batch S1 |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : "x5, gravity, not on Spansh, left behind, Now target, backup holds ok", errors.slice(before));
  }
  // batch S2 (the voice): procedural names spoken letter by letter, one personality per system, the welcome back
  // and ship-loss texts (ship_lost business-only), and the spoken-line transcript with each line's fate
  {
    const w = dom.window, before = errors.length, got = {}, bad = [];
    got.names = w.eval(`["Drojau LL-O b26-3 is undiscovered.", "Docked at Jaques Station.", "Out Of The Blue (K7F-3XZ)", "Syreadiae JX-F c0, 42 ly"].map(spokenText)`);
    got.shift = JSON.parse(w.eval(`(() => { const lib = speechLib, st = localStorage.getItem("speechStyles");
      speechLib = {styles: {business: "B", sarcastic: "S"}, lines: {find_bio: {business: ["b1", "b2", "b3"], sarcastic: ["s1", "s2", "s3"]}}};
      localStorage.setItem("speechStyles", '["business","sarcastic"]');
      const run = n => new Set(Array.from({length: n}, () => (line("find_bio", {body: "A", value: "1M"}), lineStyle)));
      localStorage.setItem("speechShift", "true"); shiftStyle = null;
      const held = run(20).size, first = shiftStyle;
      let changed = false; for (let i = 0; i < 60 && !changed; i++) { pickShift(); changed = shiftStyle !== first; }   // an arrival draws again
      const heldAfter = run(20), followsShift = [...heldAfter][0] === shiftStyle;
      localStorage.removeItem("speechShift"); shiftStyle = null;
      const mixed = run(60).size;
      speechLib = lib; if (st === null) localStorage.removeItem("speechStyles"); else localStorage.setItem("speechStyles", st);
      return JSON.stringify({held, changed, heldAfter: heldAfter.size, followsShift, mixed}); })()`));
    got.welcome = w.eval(`(() => { const d = data; data = Object.assign({}, d, {unsold: null, fuel: {pct: 64}, docked: {station: "Jaques Station"}, on_body: null});
      const a = welcomeText("3 days", false); data = Object.assign({}, d, {unsold: null, fuel: null, docked: null, on_body: {body: "A 3", how: "landed"}});
      const b = welcomeText("5 hours", false); data = d; return [a, b]; })()`);
    got.loss = w.eval(`[lossText({value: 212400000, carto: 148100000, bio: 64300000, systems: 31, firsts: 9, bio_runs: 0, nearest: {name: "Drojau LL-O b26-3", distance: 42.2}}),
      lossText({ship: false, value: 64300000, carto: 0, bio: 64300000, systems: 0, firsts: 0, bio_runs: 3, nearest: null})]`);
    got.lostBusiness = w.eval(`(() => { const st = localStorage.getItem("speechStyles"); localStorage.setItem("speechStyles", '["sarcastic"]');
      lineStyle = null; const t = line("ship_lost", {text: "Lost 1M."}); const s = lineStyle;
      if (st === null) localStorage.removeItem("speechStyles"); else localStorage.setItem("speechStyles", st);
      return [DANGER.has("ship_lost"), s, /Lost 1M/.test(t)].join(); })()`);
    // the transcript: stub the voice, then a stale find, a cooldown refusal, a tag replaced, danger cutting a find short
    const realSay = w.sayNow, flags = w.eval("[speechOn, isSpeaker]"), savedPos = w.eval("data.position && data.position.id64");
    w.eval("speechOn = true; isSpeaker = true; speechItems = []; speechLast = {}; speechLog.length = 0; data.position.id64 = 42");
    w.sayNow = async item => { const cur = w.eval("speechNow = {prio: " + item.prio + ", stop() { this.stopped = true; }}"); await sleep(80); w.eval("speechNow = null"); };
    w.eval('speak("Old find.", {kind: "find", delay: -25000})');                           // waited too long already
    w.eval('speak("Heat damage.", {kind: "hull", tag: "heat"}); speak("Heat damage.", {kind: "hull", tag: "heat"})');
    await sleep(300);
    w.eval('speak("Busy line.", {kind: "leaving"}); speak("Tank at 40.", {kind: "scoop", tag: "scoop"}); speak("Tank full.", {kind: "scoop", tag: "scoop"})');
    await sleep(400);
    w.eval('speak("A find.", {kind: "find"})'); await sleep(20); w.eval('speak("Hull at 40 percent.", {kind: "hull", tag: "hull"})');
    await sleep(400);
    w.eval("speechOn = false"); w.eval('alertOut("codex", "Codex entry", "", {say: "Codex."})'); w.eval("speechOn = true");
    got.fates = JSON.parse(w.eval(`JSON.stringify(speechLog.map(e => [e.words, e.fate]))`));
    const fate = words => (got.fates.find(f => f[0] === words) || [])[1];
    const heatFates = got.fates.filter(f => f[0] === "Heat damage.").map(f => f[1]).sort().join("|");
    // the dialog draws it when its section is open; the copy text has every line
    w.eval('document.getElementById("alertDialog").showModal ? document.getElementById("alertDialog").showModal() : document.getElementById("alertDialog").setAttribute("open", ""); document.getElementById("speechLogBox").open = true; drawSpeechLog()');
    got.drawn = w.document.querySelectorAll("#speechLog .slog").length;
    got.drawnSaid = w.document.querySelectorAll("#speechLog .slog.said").length;
    got.copyLines = w.eval("speechLogText().split('\\n').length");
    w.eval('document.getElementById("speechLogBox").open = false; const dl = document.getElementById("alertDialog"); if (dl.close) dl.close(); else dl.removeAttribute("open")');
    w.sayNow = realSay; w.eval(`[speechOn, isSpeaker] = ${JSON.stringify(flags)}; speechItems = []; speechLast = {}; if (data.position.id64 === 42) data.position.id64 = ${JSON.stringify(savedPos)}`);
    const want = {
      names: ["Drojau L L O, b 26 3 is undiscovered.", "Docked at Jaques Station.", "Out Of The Blue (K7F-3XZ)", "Syreadiae J X F, c 0, 42 ly"],
      shift: {held: 1, changed: true, heldAfter: 1, followsShift: true, mixed: 2},
      welcome: ["Away 3 days. Fuel 64 percent. Docked at Jaques Station.", "Away 5 hours. Landed on A 3."],
      loss: ["Lost 212.4M: 148.1M cartographics and 64.3M exobiology, 31 systems and 9 first discoveries. The nearest lost system is Drojau LL-O b26-3, 42 light-years.",
             "Lost 64.3M of exobiology, 3 species sampled."],
      lostBusiness: "true,business,true",
    };
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const fatesOk = fate("Old find.") === "dropped: waited over 20 s" && heatFates === "refused: said under 30 s ago|said"
      && fate("Tank at 40.") === "replaced by a newer scoop" && fate("Tank full.") === "said" && fate("A find.") === "cut short by danger"
      && fate("Hull at 40 percent.") === "said" && fate("Codex entry") === "silent: speech off";
    if (!fatesOk) bad.push("fates");
    if (!(got.drawn === got.fates.length && got.drawnSaid >= 3 && got.copyLines === got.fates.length)) bad.push("drawn");
    const goodS2 = !bad.length && errors.length === before;
    allOk = allOk && goodS2;
    console.log(goodS2 ? "OK" : "FAIL", "| batch S2 |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : `names, one personality per system, welcome back, ship lost, transcript (${got.fates.length} lines) ok`, errors.slice(before));
  }
  // batch S3: the colour variant after the guess and in the ✦ title (species wording kept when unsure); the name box
  // finds the system you are in (a local answer: no EDSM call) and opens Here, and an over-long name is refused
  {
    const w = dom.window, before = errors.length, got = {}, bad = [];
    got.variant = w.eval(`[variantTxt({variants: ["Bacterium Aurasus - Teal"]}), variantTxt({variants: ["Fungoida Setisis - Yellow", "Fungoida Setisis - Grey"]}), variantTxt({variants: []}), variantTxt(null)]
      .map(h => h.replace(/<[^>]+>/g, "").trim())`);
    got.mark = w.eval(`[codexMark({codex_new: true, variants: ["Bacterium Aurasus - Teal"]}, "Inner Orion Spur"), codexMark({codex_new: true, variants: []}, "X"), codexMark({codex_new: false, variants: ["A - B"]})]
      .map(h => (h.match(/title="([^"]*)"/) || [])[1] || "")`);
    const here = w.eval("data.position && data.position.name");
    if (here) {
      w.document.querySelector('[data-view="search"]').click(); await sleep(300);
      w.document.getElementById("findName").value = here.toLowerCase();
      w.document.getElementById("findForm").dispatchEvent(new w.Event("submit", {cancelable: true}));
      for (let i = 0; i < 20 && !/visited|never/.test(w.document.getElementById("findStatus").textContent); i++) await sleep(250);
      got.find = [w.eval("view"), /visited/.test(w.document.getElementById("findStatus").textContent)];
    } else got.find = ["here", true];   // no position yet on this server: nothing to look up locally
    got.long = (await fetch(base + "api/find?name=" + "x".repeat(101))).status;
    const want = {variant: ["Teal", "Yellow or Grey", "", ""],
                  mark: ["new to your codex in Inner Orion Spur (variant Bacterium Aurasus - Teal)",
                         "new to your codex in X (likeliest species; the colour variant may differ)", ""],
                  find: ["here", true], long: 400};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodS3 = !bad.length && errors.length === before;
    allOk = allOk && goodS3;
    console.log(goodS3 ? "OK" : "FAIL", "| batch S3 |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : "variant shown, codex title per variant, find by name opens Here, long name refused", errors.slice(before));
  }
  // G2.2, F48, F64: a bad server copy (a list that is not a list, a null object, a number for 'saved') does not stop
  // the page: a fresh browser still starts polling
  {
    const html2 = (await (await fetch(base)).text()).replace(/window\.SERVER_DEFAULTS = .*?;<\/script>/s,
      'window.SERVER_DEFAULTS = {"version": 1, "settings": {"log": {"days": "7", "cats": 1, "known": true}, "bioSort": null}, "saved": 1727700000};</script>');
    const errs2 = [];
    const dom2 = new JSDOM(html2, {url: base, runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
      beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, base), o); w.addEventListener("error", e => errs2.push(e.message)); w.localStorage.clear(); w.scrollBy = () => {}; }});
    const d2 = dom2.window.document;
    // the header's count is "…" until the first payload is drawn
    const known2 = () => ((d2.getElementById("subKnown") || {}).textContent || "").trim();
    for (let i = 0; i < 20 && !/^\d/.test(known2()); i++) await sleep(500);
    const sub2 = (d2.querySelector("#sub") || {}).textContent || "";
    const goodS = errs2.length === 0 && /^\d/.test(known2());
    dom2.window.close();
    allOk = allOk && goodS;
    console.log(goodS ? "OK" : "FAIL", "| bad server copy |", sub2.slice(0, 60) || "no header", errs2);
  }
  // Batch A: with "Play speech and sounds on this PC" ticked a line goes to the PC first. The scratch server has
  // [speech] server_player = "off", so it answers 503 and this browser says the line instead (nothing is lost,
  // and no "click to allow Piper audio" toast); a sound the PC cannot play is played here; the sound button
  // does not ask for a click while the tick is on
  {
    const w = dom.window, realFetch = w.fetch, before = errors.length, asked = [];
    w.fetch = (u, o) => {
      const p = realFetch(u, o);
      if (/^api\/(say|sound)\//.test(String(u))) p.then(r => asked.push(`${String(u)} ${r.status}`), () => asked.push(`${String(u)} failed`));
      return p;
    };
    const got = await w.eval(`(async () => {
      const ss = window.speechSynthesis, U = window.SpeechSynthesisUtterance, tts = data.tts, ph = playHere, tst = toast, a = actx;
      const spoken = [], here = [], toasts = [];
      window.SpeechSynthesisUtterance = function (words) { this.text = words; };
      window.speechSynthesis = {speaking: false, pending: false, speak(u) { spoken.push(u.text); setTimeout(() => u.onend && u.onend(), 0); }, cancel() {}};
      playHere = n => here.push(n); toast = t => toasts.push(t);
      const cb = document.getElementById("serverPlay"); cb.checked = true; cb.onchange({target: cb});
      const ticked = serverPlay();
      data.tts = null;
      const plain = {words: "Server fallback check.", prio: 1, kind: "manual", pace: 1};
      await sayNow(plain);
      piperBlockedSaid = false; data.tts = {engine: "piper", voice: "x", available: true};
      const piper = {words: "Piper fallback check.", prio: 1, kind: "manual", pace: 1};
      await sayNow(piper);   // no AudioContext in jsdom: the browser voice, without the click toast
      play("chime");
      await new Promise(r => setTimeout(r, 400));
      actx = {state: "suspended"}; drawSoundBtn();
      const blockedOn = soundBtn.classList.contains("blocked");
      cb.checked = false; cb.onchange({target: cb});
      const blockedOff = soundBtn.classList.contains("blocked");
      actx = a; drawSoundBtn();
      window.speechSynthesis = ss; window.SpeechSynthesisUtterance = U; data.tts = tts; playHere = ph; toast = tst; piperBlockedSaid = false;
      return {ticked, off: serverPlay(), spoken, engines: [plain.engine, piper.engine], here, toasts, blocked: [blockedOn, blockedOff]}; })()`);
    w.fetch = realFetch;
    const want = {ticked: true, off: false, spoken: ["Server fallback check.", "Piper fallback check."],
      engines: ["browser voice (the PC could not play it)", "browser voice (Piper audio blocked) (the PC could not play it)"],
      here: ["chime"], toasts: [], blocked: [false, true]};
    const wantAsked = ["api/say/play 503", "api/say/play 503", "api/sound/play 503"];
    const goodA = JSON.stringify(got) === JSON.stringify(want) && JSON.stringify(asked) === JSON.stringify(wantAsked) && errors.length === before;
    allOk = allOk && goodA;
    console.log(goodA ? "OK" : "FAIL", "| play on this PC |", goodA ? "503 from the PC: the browser said both lines and played the sound" : JSON.stringify({got, asked}), errors.slice(before));
  }
  // Batch B: the hush drops a find but keeps a hull line and a jump ends a "jump" hush (and the server round trip shows
  // in the header); a co-pilot request is acted on once, and only in the speaking window; the status report; a 👎
  // bans a line (the server's answer stubbed: the scratch server's speech file is the repo's, never written here);
  // isRoutine, and a routine arrival plays the routine sound instead of speaking
  {
    const w = dom.window, before = errors.length, got = {}, bad = [], realFetch = w.fetch;
    const realSay = w.sayNow, flags = w.eval("[speechOn, isSpeaker]");
    const savedData = w.eval("JSON.stringify(data)"), savedLib = w.eval("JSON.stringify(speechLib)");
    w.eval("speechOn = true; isSpeaker = true; speechItems = []; speechLast = {}; speechLog.length = 0; lastSaid = null");
    w.sayNow = async item => { w.eval("speechNow = {prio: " + item.prio + ", kind: " + JSON.stringify(item.kind) + ", stop() { this.stopped = true; }}"); await sleep(30); w.eval("speechNow = null"); };
    const fates = () => JSON.parse(w.eval("JSON.stringify(speechLog.map(e => [e.words, e.fate]))"));
    const fateOf = words => (fates().find(f => f[0] === words) || [])[1];
    // the hush: a jump hush on this system, as the payload brings it
    w.eval(`data.position = Object.assign({}, data.position || {x: 0, y: 0, z: 0, name: "Here"}, {id64: 4242, id: "4242"});
      data.hush = {mode: "jump", until: null, left: null, sys: "4242"}; onHush(false)`);
    got.hushed = w.eval("hushed()");
    w.eval('alertOut("find", "A find", "", {say: "A find."}); alertOut("hull", "Hull at 40%", "", {tag: "hull", say: "Hull at 40 percent."})');
    await sleep(1400);   // the danger sound plays first (900 ms)
    got.hush = [fateOf("Quiet until the next jump."), fateOf("A find"), fateOf("Hull at 40 percent.")];
    got.label = w.document.getElementById("hushLbl").textContent;
    w.eval('data.position = Object.assign({}, data.position, {id64: 4243, id: "4243"})');   // the jump
    got.afterJump = w.eval("hushed()");
    w.eval("data.hush = null; onHush(false)");
    await sleep(300);
    got.back = fateOf("Voice back on.");
    // the server's hush reaches the header (a scratch server: memory only, and cancelled straight after)
    const hr = await (await fetch(base + "api/hush", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode: "10m"})})).json();
    w.eval("speechOn = false");   // the page's own long poll brings it: no confirmation spoken for this part
    for (let i = 0; i < 20 && !/hushed \d+:\d\d/.test(w.document.getElementById("hushLbl").textContent); i++) await sleep(200);
    got.server = [hr.hush && hr.hush.mode, /hushed (9|10):\d\d/.test(w.document.getElementById("hushLbl").textContent)];
    await fetch(base + "api/hush", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({mode: "off"})});
    for (let i = 0; i < 20 && w.eval("hushState") !== null; i++) await sleep(200);
    got.serverOff = w.eval("hushState === null && document.getElementById('hushLbl').hidden");
    w.eval("speechOn = true");
    // the co-pilot channel: once, only in the speaking window, nothing on a first payload
    w.eval(`speechLog.length = 0; const n = lastCopilotSeq;
      takeCopilot({seq: n + 1, action: "replay", words: "Copilot check."}, false); takeCopilot({seq: n + 1, action: "replay", words: "Copilot check."}, false);
      isSpeaker = false; takeCopilot({seq: n + 2, action: "replay", words: "Not this window."}, false); isSpeaker = true;
      takeCopilot({seq: n + 3, action: "replay", words: "Stale."}, true)`);
    await sleep(200);
    got.copilot = [fates().filter(f => f[0] === "Copilot check.").length, fates().some(f => /Not this window|Stale/.test(f[0])), w.eval("lastCopilotSeq > 0")];
    w.eval('takeCopilot({seq: lastCopilotSeq + 1, action: "again"}, false)');
    await sleep(200);
    got.again = fates().filter(f => f[0] === "Copilot check.").length;
    // the status report
    got.status = w.eval(`(() => { const d = data, hd = hereData; hereData = null;
      data = Object.assign({}, d, {status: "ready", radius: 25, sphere_cut: null, on_body: null, sampling: null, fuel: {pct: 64, jumps_max: 8},
        unsold: {total: 412e6}, ship: {rebuy: 128e6}, position: Object.assign({}, d.position, {id64: 1}),
        systems: [{id64: 99, name: "Drojau LL-O b26-3", distance: 6.43, visited: false, source: "spansh"}]});
      const a = statusReportText();
      data = Object.assign({}, data, {on_body: {body: "A 1"}, sampling: {species: "Stratum Tectonicas", samples: 2, to_go: 80, clear: false}});
      const b = statusReportText(); data = d; hereData = hd; return [a, b]; })()`);
    // a 👎 on a spoken line bans it: posted with its alert and wording, and never picked again
    const posted = [];
    w.fetch = (u, o) => {
      if (/^api\/speech\/(ban|unban)/.test(String(u))) { posted.push([String(u), JSON.parse(o.body)]);
        return Promise.resolve(new Response(JSON.stringify({ok: true, banned: 1}), {status: 200, headers: {"Content-Type": "application/json"}})); }
      return realFetch(u, o);
    };
    const st = w.localStorage.getItem("speechStyles");
    w.localStorage.setItem("speechStyles", '["business"]');
    w.eval(`speechLib = {styles: {business: "Business"}, lines: {hull: {business: ["Hull A {pct}.", "Hull B {pct}."]}}, version: speechLib.version, banned: {}};
      speechLog.length = 0; alertOut("hull", "Hull at 30%", "", {tag: "hull", say: () => line("hull", {pct: 30}, "Hull.")})`);
    const entry = JSON.parse(w.eval("JSON.stringify(speechLog[0])"));
    w.eval('const dl0 = document.getElementById("alertDialog"); dl0.showModal ? dl0.showModal() : dl0.setAttribute("open", ""); document.getElementById("speechLogBox").open = true; drawSpeechLog()');
    const thumb = w.document.querySelector("#speechLog [data-ban]");
    if (thumb) thumb.click();
    await sleep(200);
    const picks = new Set(); for (let i = 0; i < 12; i++) picks.add(w.eval('line("hull", {pct: 30})'));
    got.ban = {thumb: !!thumb, posted: posted.map(p => [p[0], p[1].alert, p[1].template === entry.template]),
               picks: [...picks].length === 1 && ![...picks][0].startsWith(entry.template.slice(0, 6)),
               banned: w.eval("speechLog[0].banned"), review: /1 line banned/.test(w.document.getElementById("speechBans").textContent)};
    w.eval('document.getElementById("speechLogBox").open = false; const dl1 = document.getElementById("alertDialog"); if (dl1.close) dl1.close(); else dl1.removeAttribute("open")');
    w.fetch = realFetch;
    if (st === null) w.localStorage.removeItem("speechStyles"); else w.localStorage.setItem("speechStyles", st);
    // isRoutine: known and fully covered is; 4 of 12 on Spansh, an unmapped Earth-like, a neutron star, a first visit to an undiscovered one are not
    got.routine = w.eval(`(() => { const m = {undiscovered: false, visits: 1, in_spansh: true, body_count: 12, all_found: false, base_known: 12, star_class: "K", worth: [], bio: null};
      return [isRoutine(m), isRoutine(Object.assign({}, m, {base_known: 4})), isRoutine(Object.assign({}, m, {base_known: 4, all_found: true})),
              isRoutine(Object.assign({}, m, {worth: [{body: "A 2", subtype: "Earthlike body", notable: "Earth-like world", value: 300000}]})),
              isRoutine(Object.assign({}, m, {star_class: "N"})), isRoutine(Object.assign({}, m, {undiscovered: true})),
              isRoutine(Object.assign({}, m, {bio: {body: "B 1", value: 50e6}}))]; })()`);
    // a routine arrival with the tick on: the routine sound, no words
    const played = [];
    const realPlay = w.play; w.play = n => played.push(n);
    w.localStorage.setItem("routineQuiet", "true");
    w.eval(`speechLog.length = 0; soundOn = true; alertSound.brief = true; alertSpeak.brief = true;
      data.moments = [{seq: lastMomentSeq + 1, kind: "arrival_brief", system: "4243", system_name: "Routine Sys", undiscovered: false, visits: 1, in_spansh: true,
        body_count: 12, all_found: true, base_known: 12, star_class: "G", worth: [], bio: null}]; onData()`);
    await sleep(1200);
    got.hum = [played.join(), fateOf("Routine Sys: Known")];
    w.play = realPlay; w.localStorage.removeItem("routineQuiet");
    w.sayNow = realSay;
    w.eval(`[speechOn, isSpeaker] = ${JSON.stringify(flags)}; speechItems = []; speechLast = {}; hushState = null; hushKey = null; drawHush();
      data = ${savedData}; speechLib = ${savedLib}; render()`);
    const want = {hushed: true, hush: ["said", "silent: hushed", "said"], label: "hushed till the jump", afterJump: false, back: "said",
      server: ["10m", true], serverOff: true, copilot: [1, false, true], again: 2,
      status: ["Fuel 64 percent, 8 jumps. 412.0M aboard, 3.2 rebuys. Nearest unvisited: Drojau LL-O b26-3, 6.4 light-years.",
               "Stratum Tectonicas, sample 2 of 3, 80 metres still to go."],
      ban: {thumb: true, posted: [["api/speech/ban", "hull", true]], picks: true, banned: true, review: true},
      routine: [true, false, true, false, false, false, false], hum: ["routine", "sound only: a routine system"]};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodB = !bad.length && errors.length === before;
    allOk = allOk && goodB;
    console.log(goodB ? "OK" : "FAIL", "| batch B voice |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : "hush, jump clears it, co-pilot once in the speaking window, status report, 👎 ban, routine systems", errors.slice(before));
  }
  // Batch C: Now's at-risk line (normal, docked where it sells, a high-g approach; hidden while the haul is small),
  // captions filled in a window that is not speaking, a caption tap posting a replay without leaving Now, the bar,
  // ✕ back and a double tap; a ?mode=now window stays on Now with its URL; ↗ opens ?mode=now (once)
  {
    const w = dom.window, before = errors.length, got = {}, bad = [], realFetch = w.fetch, posted = [];
    const savedData = w.eval("JSON.stringify(data)"), flags = w.eval("[speechOn, isSpeaker, alertSpeak.sampling]");
    got.risk = JSON.parse(w.eval(`(() => {
      const out = {};
      data.unsold = {total: 792e6, carto: {estimated_payout: 380e6}, bio: {estimated_value: 412e6}, thresholds: [50e6, 250e6]};
      data.ship = Object.assign({}, data.ship, {rebuy: 247.5e6}); data.since_sale = {ts: "2026-01-01T00:00:00Z", days: 6.2, jumps: 1, ly: 1};
      data.docked = null; data.on_body = null; nowStakes = null;
      const txt = r => r ? r.html.replace(/<[^>]+>/g, "") + (r.cls ? " |" : "") : null;
      out.normal = txt(nowRiskLine());
      data.docked = {station: "Carrier", has_uc: true, has_vista: false};
      out.sell = txt(nowRiskLine());
      data.docked = null;
      nowStakes = {sys: posId(), body_id: 3, hg: highGStakes({landable: true, gravity: 2.43}), landed: false};
      out.highg = txt(nowRiskLine());
      view = "now"; render(); out.shown = document.querySelector("#nowView .now-risk").textContent.includes("2.4 g");
      data.on_body = {body: "A 3", how: "landed"}; nowStakesTick(); data.on_body = null; nowStakesTick();
      out.liftoff = nowStakes === null;
      data.unsold = {total: 1e6, carto: {estimated_payout: 1e6}, bio: {estimated_value: 0}, thresholds: [50e6, 250e6]};
      out.small = nowRiskLine();
      return JSON.stringify(out); })()`));
    // captions: a window that is not speaking shows the plain wording, nothing is queued there, three at most
    got.caps = JSON.parse(w.eval(`(() => {
      captions.length = 0; speechOn = true; isSpeaker = false; alertSpeak.sampling = true; const q = speechItems.length;
      alertOut("sampling", "Left A 3 unfinished", "Stratum 2 of 3", {say: () => line("left_body", {body: "A 3", text: "Stratum 2 of 3"}, "Leaving A 3 unfinished: Stratum 2 of 3.")});
      const first = captions.map(c => c.words), queued = speechItems.length - q;
      for (const n of [1, 2, 3]) alertOut("sampling", "Line " + n, "", {say: "Line " + n + "."});
      return JSON.stringify([first, queued, captions.map(c => c.words)]); })()`));
    // a caption tap and the bar post to the co-pilot channel and the hush (stubbed), and Now stays
    w.fetch = (u, o) => {
      if (/^api\/(copilot|hush)/.test(String(u))) { posted.push([String(u), JSON.parse(o.body)]); return Promise.resolve(new Response('{"ok": true}', {status: 200, headers: {"Content-Type": "application/json"}})); }
      return realFetch(u, o);
    };
    w.eval("hushState = null; render()");
    const cap = d.querySelector("#nowView .now-cap");
    if (cap) cap.click();
    d.getElementById("nowStatus").click(); d.getElementById("nowHush").click();
    d.getElementById("nowBody").click();   // a stray tap no longer leaves
    await sleep(200);
    got.tap = [posted, w.eval("view"), d.getElementById("nowView").hidden, d.getElementById("nowBack").hidden];
    w.fetch = realFetch;
    d.getElementById("nowBack").click(); await sleep(100);
    got.back = w.eval("view") !== "now";
    w.eval('view = "now"; render()');
    d.getElementById("nowBody").dispatchEvent(new w.MouseEvent("dblclick", {bubbles: true}));
    await sleep(100);
    got.dbl = w.eval("view") !== "now";
    // ↗: window.open with ?mode=now and a fixed name; a second press focuses the window already open
    const opened = [], realOpen = w.open;
    w.open = (u, n) => { opened.push([u, n]); return {closed: false, focus() { opened.push("focus"); }}; };
    w.eval("nowWin = null");
    d.getElementById("nowPop").click(); d.getElementById("nowPop").click();
    w.open = realOpen; w.eval("nowWin = null");
    got.pop = [/\?mode=now$/.test(opened[0] && opened[0][0]), opened[0] && opened[0][1], opened[1]];
    w.eval(`[speechOn, isSpeaker, alertSpeak.sampling] = ${JSON.stringify(flags)}; captions.length = 0; nowStakes = null; data = ${savedData}; render()`);
    // a window opened at ?mode=now: no ✕ back, a tap or a double tap leaves it on Now, and the URL keeps ?mode=now
    const html2 = await (await fetch(base + "?mode=now")).text(), errs2 = [];
    const dom2 = new JSDOM(html2, {url: base + "?mode=now", runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
      beforeParse(w2) { w2.fetch = (u, o) => fetch(new URL(u, base), o); w2.addEventListener("error", e => errs2.push(e.message)); w2.localStorage.clear(); w2.scrollBy = () => {}; }});
    const d2 = dom2.window.document;
    for (let i = 0; i < 40 && !(d2.getElementById("nowBody") && d2.getElementById("nowBody").textContent.trim()); i++) await sleep(250);
    d2.getElementById("nowBack").click();
    d2.getElementById("nowBody").click();
    d2.getElementById("nowBody").dispatchEvent(new dom2.window.MouseEvent("dblclick", {bubbles: true}));
    await sleep(300);
    got.win = [dom2.window.eval("view"), dom2.window.location.search, d2.getElementById("nowBack").hidden, !d2.getElementById("nowView").hidden, errs2];
    dom2.window.close();
    const want = {risk: {normal: "🗺 380.0M · 🧬 412.0M aboard · 3.2× rebuy · 6 d unsold |", sell: "💰 sell here: 380.0M |",
                         highg: "⚠ 2.4 g · 792.0M aboard · 3.2 rebuys |", shown: true, liftoff: true, small: null},
      caps: [["Leaving A 3 unfinished: Stratum 2 of 3."], 0, ["Line 1.", "Line 2.", "Line 3."]],
      tap: [[["api/copilot", {action: "replay", words: "Line 3."}], ["api/copilot", {action: "status"}], ["api/hush", {mode: "30m"}]], "now", false, false],
      back: true, dbl: true, pop: [true, "ed-outrider-now", "focus"], win: ["now", "?mode=now", true, true, []]};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodC = !bad.length && errors.length === before;
    allOk = allOk && goodC;
    console.log(goodC ? "OK" : "FAIL", "| batch C now |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : "at-risk line (3 states), captions in a quiet window, caption tap replays, bar, ✕ back, double tap, ?mode=now stays, ↗", errors.slice(before));
  }
  // Batch D: the widened fuel_target (a top-up at a scoopable star; one card when both rules match; once per system),
  // the in-system scoopable star's wording (said only when one is known), "under N jumps", the fuel tile and the target cost
  {
    const w = dom.window, before = errors.length, got = {}, bad = [];
    const savedData = w.eval("JSON.stringify(data)"), realAlert = w.alertOut, cards = [];
    w.alertOut = (kind, title, body, o = {}) => { if (kind === "fuel") cards.push({title, body, tag: o.tag || null, say: typeof o.say === "function" ? o.say() : o.say, key: w.eval("lineKey")}); return true; };
    const run = js => { cards.length = 0; w.eval(js + "; onData()"); return cards.map(c => [c.title, c.tag]); };
    const fuel = (pct, j, extra) => JSON.stringify(Object.assign({live: true, pct, main: pct / 2, capacity: 50, jumps_recent: j, jumps_max: j, since_scoop: 5,
      scoop_rate: {scoopable: 6, of: 20, dry_run: 3}, here_scoop: null, low_flag: false, in_ship: true}, extra || {}));
    const target = (name, sc) => `data.target = {seq: (lastSeq || 0) + 1, fresh: true, id64: 7001, id: "7001", name: "${name}", star_class: "${sc}", status: "partial", sound: null, leaving: null}`;
    const at = (id, star) => `data.position = Object.assign({}, data.position || {x: 0, y: 0, z: 0}, {id64: ${id}, id: "${id}", name: "Sys ${id}"}); lastPosId = ${id}; data.here_star = "${star}"`;
    w.eval("lineKey = null");
    // a scoopable star, 3 jumps aboard, 6 of the last 20 scoopable (gap 3.3, so under max(4, 6.7)): top up, spoken as fuel_topup
    got.topup = run(`${at(5001, "K")}; data.fuel = ${fuel(60, 3)}; ${target("Dry Target", "K")}`);
    got.topupSay = [cards[0] && cards[0].key, !!(cards[0] && cards[0].say)];
    got.again = run(`${target("Other Target", "L")}`);                        // re-targeting in the same system: silent
    got.both = run(`${at(5002, "K")}; data.fuel = ${fuel(20, 3)}; ${target("Brown One", "L")}`);   // both rules: one card
    got.bothBody = cards[0] && /Brown One is a L star you cannot scoop/.test(cards[0].body);
    got.low = run(`${at(5003, "L")}; data.fuel = ${fuel(20, 3)}; ${target("Brown Two", "T")}`);     // unscoopable here: the old rule only
    got.lowKey = cards[0] && cards[0].key;
    got.plenty = run(`${at(5004, "K")}; data.fuel = ${fuel(60, 30)}; ${target("Far", "L")}`);       // plenty of jumps: nothing
    // P9: the scoopable star here, complete and incomplete; the arrival line says a known one and never the absence
    got.here = JSON.parse(w.eval(`JSON.stringify([
      hereScoopText({here_scoop: {name: "B", subtype: "K (Yellow-Orange) Star", dist_ls: 1240, complete: false}}).replace(/<[^>]+>/g, ""),
      hereScoopText({here_scoop: {name: "B", subtype: "M (Red dwarf) Star", dist_ls: 5200, complete: false}}).replace(/<[^>]+>/g, ""),
      hereScoopText({here_scoop: {name: null, subtype: null, dist_ls: null, complete: true}}).replace(/<[^>]+>/g, ""),
      hereScoopText({here_scoop: {name: null, subtype: null, dist_ls: null, complete: false}}).replace(/<[^>]+>/g, ""),
      hereScoopText({here_scoop: {name: null, complete: false}}, true)])`));
    w.eval(`${at(5005, "K")}; data.target = null`); cards.length = 0;
    run(`data.position = Object.assign({}, data.position, {id64: 5006, id: "5006"}); data.here_star = "DA";
      data.fuel = ${fuel(20, 3, {here_scoop: {name: "B", subtype: "K (Yellow-Orange) Star", dist_ls: 1240, complete: false}})}`);
    got.starKnown = cards.map(c => [c.tag, /Star B can be scooped, 1,240 light seconds out\.$/.test(c.say), c.body]);
    run(`data.position = Object.assign({}, data.position, {id64: 5007, id: "5007"}); data.here_star = "DA";
      data.fuel = ${fuel(20, 3, {here_scoop: {name: null, subtype: null, dist_ls: null, complete: false}})}`);
    got.starUnknown = cards.map(c => [c.tag, /light seconds out\.$/.test(c.say), c.body === w.eval("scoopHint()")]);
    // "under N jumps": off by default; set to 5, it warns once on crossing (and the arrival rule counts it at 45%)
    got.underOff = run(`data.fuel = ${fuel(60, 3)}`);
    w.localStorage.setItem("fuelJumps", "5");
    got.underOn = run(`lastUnderJumps = false; data.fuel = ${fuel(60, 3)}`);
    got.underOnce = run(`data.fuel = ${fuel(60, 3)}`);
    got.underArrival = run(`lastUnderJumps = true; data.position = Object.assign({}, data.position, {id64: 5008, id: "5008"}); data.here_star = "DA"; data.fuel = ${fuel(45, 3)}`);
    w.localStorage.removeItem("fuelJumps");
    w.alertOut = realAlert;
    // the fuel tile (the local scoopable share, amber under two gaps; the in-system star when low) and the target's cost
    w.eval(`data = ${savedData}; data.fuel = ${fuel(20, 3, {model: {range_now: 78.0, max_fuel: 5.2, fitted: true, power: 2.45, cargo: 0, ly_max: 483.5},
      here_scoop: {name: "B", subtype: "K (Yellow-Orange) Star", dist_ls: 1240, complete: false}})};
      data.target = {seq: lastSeq, fresh: false, id64: 7002, id: "7002", name: "Costed", star_class: "K", status: "partial", leaving: null, hop: {ly: 38.2, fuel: 2.9, left: 3, reach: true}};
      data.jump_range_now = 78.04; render()`);
    const fl = d.getElementById("fuelLine");
    got.tile = [/scoopable: 6 of last 20 · 3 dry in a row/.test(fl.textContent), !!fl.querySelector(".warnc"), /scoopable here: B \(K\) · 1,240 ls/.test(fl.textContent),
                /\(484 ly\)/.test(fl.textContent)];
    got.target = /Costed · 38\.2 ly · 2\.9 t · leaves 3 max jumps/.test(d.getElementById("target").textContent);
    got.laden = /78\.0 laden/.test(d.getElementById("subJump").textContent);
    w.eval(`data = ${savedData}; render()`);
    const want = {topup: [["Top up here: about 3 jumps of fuel left", "fuel_target"]], topupSay: ["fuel_topup", true], again: [],
      both: [["Top up here: about 3 jumps of fuel left", "fuel_target"]], bothBody: true,
      low: [["Fuel 20% and Brown Two is not scoopable", "fuel_target"]], lowKey: "fuel_target", plenty: [],
      here: ["⛽ scoopable here: B (K) · 1,240 ls · ~35 s", "⛽ scoopable here: B (M) · 5,200 ls", "no scoopable star here",
             "no other scoopable star known yet (FSS to check)", ""],
      starKnown: [["fuel_star", true, "Star B can be scooped, 1,240 light seconds out."]], starUnknown: [["fuel_star", false, true]],
      underOff: [], underOn: [["Fuel: 3 jumps left", "fuel_low"]], underOnce: [],
      underArrival: [["Fuel 45% (3 jumps) at a DA star you cannot scoop", "fuel_star"]],
      tile: [true, true, true, true], target: true, laden: true};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodD = !bad.length && errors.length === before;
    allOk = allOk && goodD;
    console.log(goodD ? "OK" : "FAIL", "| batch D fuel |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(got)}` : "top-up card (one, once per system, fuel_topup), old rule kept, in-system star wording, under N jumps, tile, target cost", errors.slice(before));
  }
  // Batch E: the x5 per-run tile line, the trip's sale check line, the run in progress elsewhere (strip line and the
  // discard card), the region crossing (folded into the briefing, or alone) and the jumponium call-out (off by default;
  // folded into the FSS debrief, or alone)
  {
    const w = dom.window, before = errors.length, got = {}, bad = [];
    const savedData = w.eval("JSON.stringify(data)"), realAlert = w.alertOut, realToast = w.toast, cards = [], toasts = [];
    const flags = w.eval("JSON.stringify([speechOn, isSpeaker, alertSpeak, alertCfg, alertSound, lastMomentSeq])");
    w.alertOut = (kind, title, body, o = {}) => { cards.push({kind, title, body, tag: o.tag || null, quiet: o.quiet || null,
      say: o.quiet ? null : typeof o.say === "function" ? o.say() : o.say, key: w.eval("lineKey")}); return true; };
    w.toast = m => toasts.push(m);
    const realLine = w.line, keys = [];
    w.line = (k, v, p) => { keys.push(k); return realLine(k, v, p); };
    w.eval("speechLib = {styles: {}, lines: {}}; speechOn = true; isSpeaker = true; lineKey = null; alertSpeak.brief = true; alertSpeak.fss = true; alertSpeak.arrival = true");
    const s0 = w.eval("lastMomentSeq");
    let n = 0;
    const run = (...ms) => { cards.length = 0; toasts.length = 0;
      w.eval(`data.moments = ${JSON.stringify(ms.map(m => Object.assign({seq: s0 + (++n), ts: new Date().toISOString()}, m)))}; onData()`);
      return cards.map(c => [c.kind, c.title, c.tag, c.say, c.quiet]); };
    got.tile = w.eval(`bioRunsText({samples: 47, x5_runs: 42, x1_runs: 0, unknown_runs: 5, bonus_rate: 0.25})`);
    got.tileKnown = w.eval(`bioRunsText({samples: 3, x5_runs: 3, unknown_runs: 0, bonus_rate: 0.5})`);
    got.trip = w.eval(`tripBioText({x5: {sold: 47, predicted: 47, matched: 44, paid: 44, unknown: 0}, estimate_bio: 400e6, paid_bio_estimated: 380e6})`);
    got.tripNone = w.eval(`tripBioText({x5: null, estimate_bio: null})`);
    got.tripOld = w.eval(`tripBioText({x5: {sold: 43, predicted: 0, matched: 0, paid: 43, unknown: 43}})`);
    got.tripMiss = w.eval(`tripBioText({x5: {sold: 8, predicted: 8, matched: 0, paid: 0, unknown: 0}})`);
    got.elsewhere = [w.eval(`elsewhereText({species: "Fungoida Setisis", genus: "Fungoida", samples: 2, body: "B 2", system: null, value: 1e6})`),
                     w.eval(`elsewhereText({species: "Fungoida Setisis", samples: 1, body: "B 2", value: 1e6})`),
                     w.eval(`elsewhereText({species: "Stratum Tectonicas", samples: 1, body: "C 1", system: "Far Away", value: 95e6})`)];
    got.strip = w.eval(`data.sampling = {elsewhere: {species: "Fungoida Setisis", samples: 2, body: "B 2", value: 1e6}}; samplingHtml().replace(/<[^>]+>/g, "")`);
    got.dropped = run({kind: "bio_dropped", system: 1, body: "B 2", species: "Fungoida Setisis", genus: "Fungoida", elsewhere: false});
    // the region: with the briefing spoken, it waits for the briefing, which opens with it
    const sys = w.eval("posId()");
    got.regionWait = run({kind: "region", system: sys, region: "Norma Arm", spoken: "the Norma Arm", count: 3});
    got.regionToast = toasts.slice();
    got.briefOpens = run({kind: "arrival_brief", system: sys, system_name: "Here", undiscovered: true, visits: 1, body_count: 5, star_class: "K",
                          region: {region: "Norma Arm", spoken: "the Norma Arm", count: 3}}).map(c => [c[0], c[3]]);
    got.pendingCleared = w.eval("pendingRegion === null");
    got.routine = w.eval(`isRoutine({undiscovered: false, visits: 2, all_found: true, star_class: "K", worth: [], bio: null, region: {region: "X"}})`);
    // with the briefing not spoken, its own line (the arrival row, the region key)
    w.eval("alertSpeak.brief = false");
    keys.length = 0;
    got.regionAlone = run({kind: "region", system: sys, region: "Norma Arm", spoken: "the Norma Arm", count: 0});
    got.regionKey = keys.slice();
    w.eval("alertSpeak.brief = true");
    // jumponium: off by default, so the debrief says nothing of it and its own card is not spoken
    const jp = {body: "3", material: "polonium", name: "Polonium", pct: 1.3};
    got.jpDefault = [w.eval("alertSpeak.jumponium"), w.eval("alertCfg.jumponium"), w.eval("alertSound.jumponium")];
    got.jpOff = run({kind: "fss_done", system: sys, count: 6, jumponium: jp, leaving: {body_count: 6, bio_pending: [], unmapped: []}}).map(c => [c[0], c[3]]);
    got.jpOffToast = toasts.length;
    w.eval("alertSpeak.jumponium = true");
    got.jpFold = run({kind: "fss_done", system: sys, count: 6, jumponium: jp, leaving: {body_count: 6, bio_pending: [], unmapped: []}}).map(c => [c[0], c[3]]);
    keys.length = 0;
    got.jpAlone = run({kind: "jumponium", system: sys, jumponium: jp}).map(c => [c[0], c[1], c[3]]);
    got.jpKey = keys.slice();
    w.alertOut = realAlert; w.toast = realToast; w.line = realLine;
    w.eval(`(() => { const f = ${flags}; data = ${savedData}; [speechOn, isSpeaker] = f; Object.assign(alertSpeak, f[2]); Object.assign(alertCfg, f[3]);
      Object.assign(alertSound, f[4]); lastMomentSeq = ${s0} + ${n}; pendingRegion = null; speechLib = {styles: {}, lines: {}}; render(); })()`);
    const want = {
      tile: "x5 on 42 of 47 runs (no footfall when you scanned) · 5 unknown, priced at your 25% sale history",
      tileKnown: "x5 on 3 of 3 runs (no footfall when you scanned)",
      trip: "47 sold, 44 with x5 as predicted, 3 without · estimate 400.0M, paid 380.0M (-5%)", tripNone: "",
      tripOld: "43 sold, 43 with x5 (footfall not in your journals)", tripMiss: "8 sold, 0 with x5 as predicted, 8 without",
      elsewhere: ["In progress elsewhere: Fungoida Setisis 2/3 on B 2. A new species discards it.", "",
                  "In progress elsewhere: Stratum Tectonicas 1/3 on C 1 (Far Away). A new species discards it."],
      strip: "In progress elsewhere: Fungoida Setisis 2/3 on B 2. A new species discards it.",
      dropped: [["sampling", "Fungoida Setisis 2/3 discarded", null, null, "a card only: never spoken"]],
      regionWait: [], regionToast: ["Entering Norma Arm"],
      briefOpens: [["brief", "Entering the Norma Arm. Undiscovered. 5 bodies. Scoopable K star."]], pendingCleared: true, routine: false,
      regionAlone: [["arrival", "Entering Norma Arm", "region", "Entering the Norma Arm.", null]],
      jpDefault: [false, false, false],
      jpOff: [["fss", "All 6 found. Nothing worth staying for."], ["jumponium", "3 has polonium, 1.3 percent."]], jpOffToast: 0,
      jpFold: [["fss", "All 6 found. Nothing worth staying for. 3 has polonium, 1.3 percent."]],
      jpAlone: [["jumponium", "3: polonium 1.3%", "3 has polonium, 1.3 percent."]], jpKey: ["jumponium"], regionKey: ["region"]};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodE = !bad.length && errors.length === before;
    allOk = allOk && goodE;
    console.log(goodE ? "OK" : "FAIL", "| batch E exobio |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(Object.fromEntries(bad.map(k => [k, got[k]])))}` : "x5 runs line, sale check line, elsewhere strip + discard card, region folded or alone, jumponium off by default / folded / alone", errors.slice(before));
  }
  {   // batch F: the pre-Odyssey mark (Nearby, Left behind, Here) and the firsts watch (My firsts, the Unsold tile)
    const w = dom.window, d = w.document, before = errors.length, bad = [], got = {};
    const txt = h => { const el = d.createElement("div"); el.innerHTML = h; return el.textContent; };
    const old = {bodies: 3, genera_top: ["Bacterium", "Stratum"], up_to: 4200000, reported: "2019-06-01"};
    got.near = txt(w.eval(`oldDataTag(${JSON.stringify(old)})`));
    got.nearTitle = /Last reported 2019 by a pre-Odyssey client/.test(w.eval(`oldDataTag(${JSON.stringify(old)})`));
    got.none = w.eval("oldDataTag(null)");
    got.pop = /landable\? \(old data\)/.test(w.eval(`bodyPopHtml({name: "A 3", type: "Planet", landable: false, stale_bio: true, updated: "2019-06-01", bio: 0, genera: [], organics: [], codex: []}, null)`));
    got.popPlain = /not landable/.test(w.eval(`bodyPopHtml({name: "A 4", type: "Planet", landable: false, stale_bio: false, bio: 0, genera: [], organics: [], codex: []}, null)`));
    got.seen = txt(w.eval(`seenCell({reported_ts: "2026-01-09T12:00:00Z", days: 8, bodies: 2, spansh_bodies: 7, body_count: 12})`));
    got.seenSame = txt(w.eval(`seenCell({reported_ts: "2026-01-01T12:00:00Z", days: 0, bodies: 1, spansh_bodies: 3, body_count: null})`));
    got.tile = txt(w.eval(`firstsSeenLine({on: true, seen: 3, checked: 40, of: 40})`));
    got.tileTitle = /someone else has scanned/i.test(w.eval(`firstsSeenLine({on: true, seen: 3, checked: 40, of: 40})`));
    got.tileNone = w.eval(`firstsSeenLine({on: true, seen: 0, checked: 4, of: 40})`) + w.eval("firstsSeenLine(null)");
    const savedLeft = w.eval("JSON.stringify(leftData)");
    w.eval(`leftData = {radius: 100, systems: [{id: "9", name: "Old Sys", distance: 12.5, unfound: 0, bio: [], maps: [], maps_total: 0, old_data: ${JSON.stringify(old)}}]}; renderLeft()`);
    got.left = /old data: 3 bodies/.test(d.getElementById("leftRows").textContent);
    w.eval(`leftData = ${savedLeft}; renderLeft()`);
    const want = {near: "old data: 3 bodies", nearTitle: true, none: "", pop: true, popPlain: true,
      seen: "👁 8 d after you · Spansh has 7 of 12 bodies", seenSame: "👁 the same day · Spansh has 3 bodies",
      tile: " · 👁 3 scanned by someone else", tileTitle: true, tileNone: "", left: true};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodF = !bad.length && errors.length === before;
    allOk = allOk && goodF;
    console.log(goodF ? "OK" : "FAIL", "| batch F spansh |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(Object.fromEntries(bad.map(k => [k, got[k]])))}` : "old-data mark in Nearby/Left behind/Here, seen-by-others cell and Unsold tile count", errors.slice(before));
  }
  {   // batch G: "· verified" on the Data tile, and auto honk's learned fire groups (rendered only: nothing is posted)
    const w = dom.window, d = w.document, before = errors.length, bad = [], got = {};
    const txt = h => { const el = d.createElement("div"); el.innerHTML = h; return el.textContent; };
    const ts = new Date(Date.now() - 3 * 3600000).toISOString();
    got.tile = /backed up 3 h ago · verified · 7 kept/.test(txt(w.eval(`backupHtml({ts: "${ts}", verified: true, kept: 7, path: "/x/b.zip", every_days: 1})`)));
    got.unverified = /verified/.test(txt(w.eval(`backupHtml({ts: "${ts}", kept: 7, path: "/x/b.zip", every_days: 1})`)));
    const savedAh = w.eval("JSON.stringify(data.autohonk || null)");
    w.eval(`data.autohonk = Object.assign({}, data.autohonk || {}, {available: false, wanted: false, status: "off", key: "auto", groups: {good: ["A", "B"], bad: ["C"]}}); drawHonk()`);
    got.shown = !d.getElementById("autoHonkGroups").hidden;
    got.line = d.getElementById("autoHonkGroupsText").textContent;
    got.forget = !!d.getElementById("autoHonkForget");
    w.eval(`data.autohonk = Object.assign({}, data.autohonk, {groups: null}); drawHonk()`);
    got.hidden = d.getElementById("autoHonkGroups").hidden;
    w.eval(`data.autohonk = ${savedAh}; drawHonk()`);
    got.say = w.eval(`honkGroup("no discovery scan followed with fire group C selected: is the D-Scanner on primary fire there?")`) +
      w.eval(`honkGroup("gave up waiting: fire group D selected; honks missed there before")`) + w.eval(`honkGroup("no discovery scan followed: is the D-Scanner on primary fire?")`);
    const want = {tile: true, unverified: false, shown: true, forget: true, hidden: true, say: "CD",
      line: "scanner worked on fire groups A, B; missed on C (auto honk waits while that is selected)"};
    for (const k of Object.keys(want)) if (JSON.stringify(got[k]) !== JSON.stringify(want[k])) bad.push(k);
    const goodGH = !bad.length && errors.length === before;
    allOk = allOk && goodGH;
    console.log(goodGH ? "OK" : "FAIL", "| batch G honk/backups |", bad.length ? `failed ${bad.join(", ")}: ${JSON.stringify(Object.fromEntries(bad.map(k => [k, got[k]])))}` : "verified on the Data tile, learned fire groups line + forget, group letter in the spoken miss", errors.slice(before));
  }
  // another site's POST is refused before any handler runs (radius: harmless even if it got through with {})
  const post = origin => fetch(base + "api/radius", {method: "POST", body: "{}",
    headers: Object.assign({"Content-Type": "application/json"}, origin ? {Origin: origin} : {})}).then(r => r.status);
  const [foreign, own] = [await post("http://evil.example"), await post(base.slice(0, -1))];
  const goodG = foreign === 403 && own === 400;
  allOk = allOk && goodG;
  console.log(goodG ? "OK" : "FAIL", "| origin guard |", `foreign ${foreign}, same origin ${own}`);
  process.exit(allOk ? 0 : 1);
})();
