// Settings live in this browser's localStorage. A setting it has never set comes from the server's copy
// ("use these for new browsers" in the alerts dialog, inlined into the page as SERVER_DEFAULTS), then from
// the config file's [defaults] (data.defaults) where the page asks for one. Only SETTINGS_KEYS are shared:
// per-device ones (the view, layouts, the search form, which screen speaks) never are. ed_outrider.py has the
// same list (BROWSER_SETTINGS).
const SETTINGS_KEYS = ["alerts", "alertSound", "alertSpeak", "speech", "speechStyles", "speechNames", "speechSpeed",
  "speechProfanity", "speechProfanityPct", "speechDangerBusiness", "speechShift", "sayBio", "sayGeo", "sayHazard",
  "honkAnnounce", "sound", "unsoldCfg", "highlightCfg", "bioMinCfg", "maxBonus", "codexNewCounts",
  "highG", "streakCfg", "skipFloor", "sort", "sorts", "showVisited", "showExplored", "oneJump", "map",
  "log", "lbRadius", "fShowLost", "mHeld", "bioSort", "bState", "bDays", "hDays"];
const serverSettings = () => { const s = typeof window !== "undefined" && window.SERVER_DEFAULTS;
  return s && s.settings && typeof s.settings === "object" ? s.settings : {}; };
// The shape a shared setting must have to be used: a hand-edited import or server copy with, say, a string for
// the personalities would otherwise throw in every spoken alert. A value of the wrong type reads as unset.
const isObj = v => v !== null && typeof v === "object" && !Array.isArray(v);
const SETTING_SHAPES = {alerts: isObj, alertSound: isObj, alertSpeak: isObj, speechStyles: Array.isArray, unsoldCfg: isObj,
  highlightCfg: isObj, streakCfg: isObj, sorts: isObj, map: isObj, log: isObj, bioSort: isObj};
// null is a fine value for a plain setting (a reset stores it: "follow the default"), but a key with a shape is
// read as an object or list at start-up, so a null there reads as unset too (else `lSaved.days` stops the script)
const settingOk = (k, v) => !SETTING_SHAPES[k] || SETTING_SHAPES[k](v);
const store = {
  get(k, d) {
    let v = null;
    try { v = localStorage.getItem(k); } catch {}   // storage blocked: the server copy still applies
    if (v !== null) { try { const x = JSON.parse(v); return !settingOk(k, x) ? d : x; } catch { return d; } }
    const sv = serverSettings();
    return SETTINGS_KEYS.includes(k) && Object.prototype.hasOwnProperty.call(sv, k) && settingOk(k, sv[k]) ? sv[k] : d;
  },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let data = null, version = -1;
// Where you are, as the exact id64 string (position.id). The JSON number position.id64 loses the last digits above
// 2^53, so string comparisons with the server's exact ids (arrival, Here, moments) must use this.
const posId = () => data && data.position ? data.position.id ?? String(data.position.id64) : null;
// Each sortable table keeps its own sort (a value sort chosen in My firsts must not re-sort Nearby).
const SORT_TABLES = {nearTable: "near", firstsTable: "firsts", bmTable: "bm", sTable: "search"};
const sortKeys = Object.assign({near: store.get("sort", "distance"), firsts: "distance", bm: "distance", search: "distance"},
                               store.get("sorts", {}));
const showVisited = document.getElementById("showVisited");
const showExplored = document.getElementById("showExplored");
showVisited.checked = store.get("showVisited", true);
showExplored.checked = store.get("showExplored", true);

async function apiJson(url, opts) {
  // Server errors come back as JSON from the API middleware; anything else is reported plainly.
  const r = await fetch(url, opts);
  const ct = r.headers.get("content-type") || "";
  if (ct.includes("application/json")) { const j = await r.json(); if (!r.ok && j && !j.error) j.error = `HTTP ${r.status}`; return j; }
  return {error: r.ok ? "unexpected non-JSON response" : `HTTP ${r.status} — see the terminal`};
}
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// Lists are redrawn on every payload, which replaces the element that had keyboard focus. focusKey(id) notes
// which one it was (by tag and data attributes) before the redraw, refocus(id, key) finds its new copy after.
function focusKey(id) {
  const box = document.getElementById(id), a = document.activeElement;
  if (!box || !a || a === box || !box.contains(a)) return null;
  const attrs = [...a.attributes].filter(x => x.name.startsWith("data-"));
  return attrs.length ? a.tagName.toLowerCase() + attrs.map(x => `[${x.name}="${x.value.replace(/["\\]/g, "\\$&")}"]`).join("") : null;
}
function refocus(id, key) {
  if (!key) return;
  const el = document.getElementById(id).querySelector(key); if (!el) return;
  markKeyable();   // the new copy gets its tabindex now, not at the next animation frame
  el.focus({preventScroll: true});
}
const icon = (cls, id, n, title) =>
  `<span class="ic ${cls}" title="${title}"><svg><use href="#${id}"/></svg>${n}</span>`;
const q = v => v === null || v === undefined ? "?" : v;

function valueCell(s) {
  if (!s.value_max) return "";
  return s.value_now ? `<b>${credits(s.value_now)}</b> / ${credits(s.value_max)}` : credits(s.value_max);
}
function valueTitle(s) {
  const v = s.value_parts; if (!v) return "";
  const part = (c, b) => [c ? `${credits(c)} cartographics` : "", b ? `${credits(b)} exobiology` : ""].filter(Boolean).join(" + ") || "nothing";
  return `On board from here: ${part(v.carto_now, v.bio_now)}\nStill available: ${part(v.carto_left, v.bio_left)}\n\nExobiology counts ×5 on bodies nobody had set foot on when you scanned them, ×1 on bodies you have not scanned.`;
}
function notable(s) {
  const n = s.notable || {};
  const names = {ELW: "Earth-like", WW: "water world", AW: "ammonia world", T: "terraformable"};
  return ["ELW", "WW", "AW", "T"].filter(k => n[k]).map(k =>
    `<span class="nb ${k}" title="${names[k]}${n[k] > 1 ? "s" : ""}">${k}${n[k] > 1 ? "×" + n[k] : ""}</span>`).join("") +
    (s.bio_potential ? `<span class="nb bio" title="exobiology: up to this much across ${s.bio_bodies_guessed} bod${s.bio_bodies_guessed === 1 ? "y" : "ies"}, from spawn rules">🧬≤${credits(s.bio_potential)}</span>` : "") +
    phenomenaTag(s.phenomena) +
    (s.curiosities ? `<span class="nb cur" title="${(s.curiosity_list || []).map(c => esc(`${c.body}: ${c.tag} (${c.why})`)).join("&#10;")}">🔭${s.curiosities > 1 ? "×" + s.curiosities : ""}</span>` : "");
}
// 🌀 notable stellar phenomena your FSS found in a system (life clouds, rings); dimmed once you have been to it
function phenomenaTag(list) {
  if (!list || !list.length) return "";
  const left = list.filter(p => !p.reached_ts);
  return `<span class="nb nsp${left.length ? "" : " done"}" title="notable stellar phenomena: ${list.map(p => p.kind + (p.reached_ts ? " (reached)" : "")).join(", ")}">🌀${list.length > 1 ? "×" + list.length : ""}</span>`;
}
// Journal ship ids -> the names the game shows.
const SHIP_NAMES = {sidewinder: "Sidewinder", eagle: "Eagle", hauler: "Hauler", adder: "Adder", empire_eagle: "Imperial Eagle",
  viper: "Viper Mk III", cobramkiii: "Cobra Mk III", viper_mkiv: "Viper Mk IV", diamondback: "Diamondback Scout",
  cobramkiv: "Cobra Mk IV", type6: "Type-6 Transporter", dolphin: "Dolphin", diamondbackxl: "Diamondback Explorer",
  empire_courier: "Imperial Courier", independant_trader: "Keelback", asp_scout: "Asp Scout", vulture: "Vulture",
  asp: "Asp Explorer", federation_dropship: "Federal Dropship", type7: "Type-7 Transporter", typex: "Alliance Chieftain",
  federation_dropship_mkii: "Federal Assault Ship", empire_trader: "Imperial Clipper", typex_2: "Alliance Crusader",
  typex_3: "Alliance Challenger", federation_gunship: "Federal Gunship", krait_light: "Krait Phantom", krait_mkii: "Krait Mk II",
  orca: "Orca", ferdelance: "Fer-de-Lance", mamba: "Mamba", python: "Python", python_nx: "Python Mk II", type9: "Type-9 Heavy",
  belugaliner: "Beluga Liner", type9_military: "Type-10 Defender", anaconda: "Anaconda", federation_corvette: "Federal Corvette",
  cutter: "Imperial Cutter", mandalay: "Mandalay", type8: "Type-8 Transporter", cobramkv: "Cobra Mk V", corsair: "Corsair",
  panthermkii: "Panther Clipper Mk II", explorer_nx: "Caspian Explorer", lakonminer: "Type-11 Prospector", smallcombat01_nx: "Kestrel Mk II"};
const shipName = t => SHIP_NAMES[(t || "").toLowerCase()] || (t || "").replace(/_/g, " ");
// what to call a ship: its own name, or its type's proper name when it has none (the journal gives an unnamed
// ship its type id as the name, "krait_mkii", which reads and speaks badly)
const shipLabel = (name, type) => { const n = String(name || "").trim();
  return !n || (type && n.toLowerCase() === String(type).toLowerCase()) || SHIP_NAMES[n.toLowerCase()] ? shipName(type || n) : n; };
// FSD injections you could synthesise now (from the materials you carry).
// Hull, when it is not full: the percentage. (No synthesis repairs the ship: "Repair basic" is the SRV's.)
function hullLine() {
  const h = data.hull;
  if (h && h.pct == null && h.repaired)   // repair limpets: the journal gives no new %
    return `<div class="ln" title="repaired by limpets: the journal gives the new hull % only at the next Loadout (docking, SRV/fighter return) or hull damage">hull <b>repaired</b> · % unknown</div>`;
  if (!h || h.pct == null || h.pct >= 100) return "";
  const cls = h.pct < 25 ? "noscoop" : h.pct < 50 ? "warnc" : "";
  return `<div class="ln" title="hull integrity, from the journal">hull <b class="${cls}">${h.pct}%</b></div>`;
}
function boostLine() {
  const m = data.materials; if (!m || !m.boosts) return "";
  const b = m.boosts, part = k => `<b class="${b[k] ? "" : "zero"}">${b[k]}</b>`;
  return `<div class="ln" id="fuelBoost" title="FSD injections you can synthesise with the materials aboard: premium (+100%) / standard (+50%) / basic (+25%)${m.stale ? ". Counts predate your last login." : ""}">` +
    `FSD boosts ${part("premium")} / ${part("standard")} / ${part("basic")}</div>`;
}
document.getElementById("radiusSel").onchange = async e => {
  const sel = e.target; sel.dataset.pending = "1";
  let r;
  try { r = await apiJson("api/radius", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({radius: Number(sel.value)})}); }
  catch (err) { r = {error: err.message}; }
  toast(r.error ? `Could not change the radius: ${r.error}` : `Nearby now covers ${r.radius} ly — asking Spansh…`);
  delete sel.dataset.pending; sel.blur();
};
// The Data tile's "journal N min ago" and its stale colouring depend on the clock, not on new data: a
// hung or crashed game writes nothing, every poll answers 204, and nothing would redraw it.
setInterval(() => { if (data) renderStrip(); }, 30000);
// ---- carrier tile: where it is, the rendezvous maths, and a live countdown to a booked jump ----
let carrierWarned = null;
function renderCarrier() {
  const c = data && data.carrier, cl = document.getElementById("carrierLine");
  const val = (v, title) => `<div class="val"${title ? ` title="${title}"` : ""}>${v}</div>`, ln = v => v ? `<div class="ln">${v}</div>` : "";
  if (!c) { cl.innerHTML = val(`<span class="unk">none seen</span>`); return; }
  const fmtLy = d => d.toLocaleString("en-US", {maximumFractionDigits: 1});
  let where = c.aboard ? "<b>aboard</b>" : c.here ? "<b>in this system</b>"
    : `<span class="copy" data-name="${esc(c.system)}" title="click to copy">${esc(c.system)}</span>` + (c.distance != null ? ` · <b>${fmtLy(c.distance)} ly</b>` : "");
  // the game was not running when a booked jump left: this is where it was booked to go
  if (c.assumed) where += ` <span class="unk" title="the booked jump's destination: the journal confirms it at your next login">(booked jump, not yet confirmed)</span>`;
  // straight-line lower bounds: the real route is never shorter
  let meet = "";
  if (!c.here && c.distance) {
    const jr = effRange(), f = data.fuel;
    const mine = jr ? jumpsFor(c.distance) : null, theirs = Math.ceil(c.distance / (c.jump_range || 500));
    const tank = f && f.jumps_max != null ? f.jumps_max : null;
    meet = (mine != null ? `you → it ≈ <b>${mine}</b> jump${mine === 1 ? "" : "s"}` +
             (tank != null ? ` <span class="${tank < mine ? "warnc" : "unk"}" title="jumps at max range your tank covers now">(tank ${tank})</span>` : "") : "") +
           ` · it → you ≈ <b>${theirs}</b> carrier jump${theirs === 1 ? "" : "s"}`;
  }
  let plan = "";
  const pl = c.planned;
  if (pl && pl.departure) {
    const left = (Date.parse(pl.departure) - Date.now()) / 1000;
    const mmss = t => t >= 3600 ? `${Math.floor(t / 3600)} h ${Math.floor(t % 3600 / 60)} min` : `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
    const urgent = left > 0 && left < 300 && !c.aboard;
    plan = `<span class="${urgent ? "noscoop" : ""}">${left > 0 ? `departs for <b>${esc(pl.system)}</b> in <b>${mmss(left)}</b>` : `jumping to <b>${esc(pl.system)}</b>`}</span>` +
      (pl.jump_ly ? ` <span class="unk">(${fmtLy(pl.jump_ly)} ly jump${pl.distance_from_you != null ? `, then ${fmtLy(pl.distance_from_you)} ly from you` : ""})</span>` : "");
    if (urgent && carrierWarned !== pl.departure) {   // once per booking, only if you are not aboard
      carrierWarned = pl.departure;
      alertOut("carrier", `${c.name} departs in ${Math.ceil(left / 60)} minutes`, `for ${pl.system}; you are not aboard`,
               {sound: "alert", tag: "carrier_departs", say: () => line("carrier_departs", {minutes: Math.ceil(left / 60), carrier: c.name},
                                                `Your carrier departs in ${Math.ceil(left / 60)} minutes, and you are not aboard.`)});
    }
  }
  cl.innerHTML = val(esc(c.name), esc(c.callsign || "")) + ln(where) + ln(meet) + ln(plan) +
    ln(`${c.has_uc ? "UC ✓" : "no UC"} · ${c.has_vista ? "Vista ✓" : "no Vista"}${c.fuel != null ? ` · ${c.fuel} t tritium` : ""}`);
}
// the countdown ticks without new data
setInterval(() => { if (data && data.carrier && data.carrier.planned) renderCarrier(); }, 1000);
document.addEventListener("click", async e => {
  if (!e.target.closest || !e.target.closest("#backupBtn")) return;
  let r;
  try { r = await apiJson("api/backup", {method: "POST"}); }
  catch (err) { r = {error: err.message}; }   // the server is not answering (restarting, stopped)
  toast(r.error ? `Backup failed: ${r.error}` : "Backing up the database and journals…");
});
// The Data tile's backup line: when, how many dated zips are kept, how far the journal archive goes. Red when
// the last backup failed (no zip written); amber when it is overdue (twice the automatic interval, or 30 days
// with it off) or when it worked but left something out (a journal it could not archive: `warning`).
function backupHtml(bk) {
  if (bk.running) return "backing up…";
  const h = bk.ts ? (Date.now() - Date.parse(bk.ts)) / 3600000 : null;
  const ago = h == null ? "" : h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} d ago`;
  const every = Number(bk.every_days) || 0, late = h == null || h > 24 * (every > 0 ? 2 * every : 30);
  // a journal not archived was an error before it became a warning: an older record of one still reads as a warning
  const oldWarn = bk.error && /^(\d+ journals? not archived|journal archive:)/.test(bk.error);
  const error = oldWarn ? null : bk.error, warning = bk.warning || (oldWarn ? bk.error : null);
  const cls = error ? "badc" : warning || late ? "warnc" : "unk";
  const title = (error ? `last backup failed${bk.error_ts ? ` (${bk.error_ts.replace("T", " ").slice(0, 16)} UTC)` : ""}: ${error}\n` : "") +
    (warning && !error ? `the last backup worked, but: ${warning}\n` : "") +
    (bk.path ? `latest: ${bk.path}` : "no backup made yet") +
    // what that zip holds (the database, and your browser defaults, lines and settings when they exist)
    (bk.path && Array.isArray(bk.files) && bk.files.length ? `\nholds: ${bk.files.join(", ")}` : "") + (bk.journals_dir ? `\njournals archived in ${bk.journals_dir} (restore: --legacy that folder)` : "") +
    (every > 0 ? `\nautomatic: at start when the last is over ${every} day${every === 1 ? "" : "s"} old, and when the game quits` : "\nautomatic backups are off (backup_every_days = 0)");
  // the warning's detail (which file, why) is in the title: the line keeps "1 journal not archived (…)"
  const warnShort = warning && !error ? warning.replace(/\s*\(.*$/s, "") + (/\(/.test(warning) ? " (…)" : "") : "";
  const bits = [bk.ts ? `backed up ${ago}` : "no backup yet", bk.ts && bk.kept && !warnShort ? `${bk.kept} kept` : "",
                bk.journals_to && !warnShort ? `journals to ${bk.journals_to}` : "", warnShort].filter(Boolean);
  return `<span class="${cls}" title="${esc(title)}">${esc(bits.join(" · "))}${error ? " · last one failed" : ""}</span> <button type="button" id="backupBtn" class="mini">back up now</button>`;
}
// The discovery streak: the last 20 arrivals as dots, each coloured when its arrival star was scanned and never
// again: gold new (nobody had discovered it), amber known with bodies Spansh had not heard of, blue fully
// reported, grey visited before, hollow known but Spansh had nothing on it at the time, blank not scanned.
const STREAK_WORDS = {new: "first discovery", partial: "known, bodies unreported", complete: "fully reported",
                      visited: "visited before", known: "known (Spansh had no data then)"};
function streakHtml(sk) {
  if (!sk || !sk.arrivals || !sk.arrivals.length) return "";
  const dots = sk.arrivals.map(a => `<span class="sk ${a.verdict || "none"}" title="${esc(a.name)} · ${esc(STREAK_WORDS[a.verdict] || "arrival star not scanned")}` +
    `${a.firsts ? ` · ${a.firsts} first discover${a.firsts === 1 ? "y" : "ies"}` : ""}${a.value ? ` · ${credits(a.value)} cr scanned` : ""} · ${esc(a.ts.replace("T", " ").slice(0, 16))}"></span>`).join("");
  return `<b>${sk.new}/${sk.total}</b> new <span class="streak" title="your last ${sk.total} arrivals, oldest first">${dots}</span>`;
}
// The unreported horizon: the nearest system Spansh or EDSM know that you have not visited. Any unvisited star
// on the galaxy map closer than that is one nobody has reported. Never "undiscovered": the game may know it.
// Only once the sphere search has come back (while it runs the list is empty or partial); honours sphere_cut
// (the list is complete only to there, so the claim stops there).
function horizon() {
  const p = data && data.position;
  if (!p || /^(starting|asking|Spansh search failed|refresh failed)/.test(data.status || "")) return null;
  const cut = data.sphere_cut, r = cut != null ? Math.min(cut, data.radius) : data.radius;
  const n = (Array.isArray(data.systems) ? data.systems : []).filter(s => s.id64 !== p.id64 && !s.visited && s.source !== "route")
    .sort((a, b) => a.distance - b.distance)[0];
  const ly = x => `${Number(x).toLocaleString("en-US", {maximumFractionDigits: 1})} ly`;
  const why = "Systems on the galaxy map that are not in this list have never been reported to Spansh or EDSM (the game itself may still know them).";
  if (!n || (cut != null && n.distance > cut)) {
    const lead = n ? `nearest known unvisited: ${n.name} ${ly(n.distance)} (the list is complete only to ${ly(cut)})` : `no known unvisited star within ${ly(r)}`;
    return {text: `${lead} — any unvisited star on the map within ${ly(r)} is unreported`, why, system: n || null};
  }
  const star = n.main_class ? ` · ${n.main_class}${n.main_scoopable ? " ⛽" : ""}` : "";
  return {text: `nearest known unvisited: ${n.name} ${ly(n.distance)}${star} — unvisited stars closer than this aren't reported to Spansh or EDSM`, why, system: n};
}
function renderStrip() {
  const val = (v, title) => `<div class="val"${title ? ` title="${title}"` : ""}>${v}</div>`, ln = v => v ? `<div class="ln">${v}</div>` : "";
  // commander tile: credits at login plus exploration sales since, and the ship
  const cm = data.commander, sh = data.ship, cmEl = document.getElementById("cmdrLine");
  document.getElementById("cmdrLbl").textContent = cm && cm.name ? `Cmdr ${cm.name}` : "Commander";
  const shipLine = sh ? `<span title="${esc(shipName(sh.type))}${data.jump_range ? ` · ${data.jump_range.toFixed(1)} ly max jump` : ""}">${esc(shipLabel(sh.name, sh.type))}` +
    `${sh.type && shipName(sh.type) !== shipLabel(sh.name, sh.type) ? ` <span class="unk">· ${esc(shipName(sh.type))}</span>` : ""}</span>` : "";
  cmEl.innerHTML = !cm ? val(`<span class="unk">no login seen</span>`) + ln(shipLine) :
    val(cm.credits != null ? `≈ ${credits(cm.credits)} cr` : `<span class="unk">credits unknown</span>`,
        `Credits at login (${esc((cm.login_ts || "").replace("T", " ").slice(0, 16))} UTC)${cm.credits_login != null ? ": " + cm.credits_login.toLocaleString() : ""}` +
        ` plus exploration and exobiology sales since. Other spending and income (market, repairs, missions) is not tracked.`) +
    ln(shipLine) + ln(cm.earned ? `+${credits(cm.earned)} cr sold since login` : "") +
    ln(["Explore", "Exobiologist"].filter(k => cm.ranks && cm.ranks[k]).map(k => { const r = cm.ranks[k];
      return `<span title="${k === "Explore" ? "exploration" : "exobiology"} rank${r.progress != null ? `, ${r.progress}% to the next` : ""}">${k === "Explore" ? "Explorer" : "Exobiologist"}: <b>${esc(r.name)}</b>${r.progress != null ? ` <span class="unk">${r.progress}%</span>` : ""}</span>`; }).join(" · "));
  const ns = data.next_stop, nsEl = document.getElementById("nextStopLn"), jr0 = effRange();
  nsEl.innerHTML = ns ? `<span title="your chosen next stop (clears when you arrive)">next stop:</span> <span class="copy" data-name="${esc(ns.name)}" title="click to copy">${esc(ns.name)}</span>` +
    (ns.distance != null ? ` · <b>${ns.distance.toLocaleString("en-US", {maximumFractionDigits: 1})} ly</b>${jr0 ? ` ≈ ${jumpsFor(ns.distance)} jump${jumpsFor(ns.distance) === 1 ? "" : "s"}` : ""}` : "") +
    ` <span class="unk" id="nsClear" title="clear the next stop" style="cursor:pointer">✕</span>` : "";
  const p0 = data.position, wl = document.getElementById("whereLn");
  wl.innerHTML = p0 ? `<span title="galactic coordinates (x / y / z)">Coord: ${[p0.x, p0.y, p0.z].map(v => v.toFixed(2)).join(" / ")}</span>` +
    (p0.visits ? ` · <span title="arrivals in this system, from your journals">visit ${p0.visits}</span>` : "") : "";
  document.getElementById("streakLn").innerHTML = streakHtml(data.streak);
  const hz = horizon();
  document.getElementById("horizonLn").innerHTML = hz ? `<span title="${esc(hz.text + ".\n" + hz.why)}">${esc(hz.text)}</span>` : "";
  // fuel tile
  const f = data.fuel, tf = document.getElementById("tFuel"), el = document.getElementById("fuelLine");
  tf.className = "tile"; tf.title = "";
  if (!f) el.innerHTML = val(`<span class="unk">—</span>`);
  else if (!f.live) el.innerHTML = val(`<span class="unk">${f.main != null ? f.main.toFixed(1) + " t (last reading)" : "no reading"}</span>`) + ln("game not running") + boostLine();
  else {
    tf.className = "tile " + (f.pct == null ? "" : f.pct < 15 ? "urgent" : f.pct < 30 ? "warn" : "");   // null < 15 is true
    el.innerHTML = val(`${f.main.toFixed(1)}${f.capacity ? " / " + f.capacity + " t" : " t"}${f.pct != null ? ` · ${f.pct}%` : ""}`) + hullLine() +
      ln((f.jumps_max != null ? `≈<b>${f.jumps_max}</b> jumps at max range` : "") + (f.jumps_recent != null ? (f.jumps_max != null ? ", " : "") + `<b>${f.jumps_recent}</b> at your pace` : "")) +
      ln(f.since_scoop != null ? `${f.since_scoop} jump${f.since_scoop === 1 ? "" : "s"} since the last scoop` : "") + boostLine();
    tf.title = "From Status.json. Jump estimates use fuel burned on your recent jumps; a max-range jump costs several times a short hop.";
  }
  renderCarrier();
  // data tile: journal freshness, link health, server state
  const fr = data.freshness, fl = document.getElementById("freshLine"), sl = document.getElementById("statusLine"), td = document.getElementById("tData");
  let dot = "", text = "", tcls = "";
  if (fr && fr.journal) {
    const age = Math.max(0, (Date.now() - Date.parse(fr.journal)) / 60000);
    const cls = fr.live && age > 10 ? "bad" : fr.live && age > 3 ? "warn" : "";
    dot = cls; tcls = cls === "bad" ? "urgent" : cls;
    text = `journal ${esc(fr.journal.slice(11, 16))} UTC` + (age >= 1 ? ` · ${age < 90 ? Math.round(age) + " min" : Math.round(age / 60) + " h"} ago` : "") + (fr.live ? "" : " · game off");
  } else text = fr && !fr.dirs.length ? "no journal folder — pass --journals" : "waiting for a journal";
  const failed = /failed|error/.test(data.status || "");
  const problems = [disconnected && `NOT CONNECTED since ${disconnected}`, data.tail_error && "journal tailing error — see the terminal",
                    pageError && `page error (${esc(pageError)}) — see the browser console`,
                    failed && esc(data.status)].filter(Boolean);
  if (problems.length) { dot = disconnected || data.tail_error || pageError ? "bad" : "warn"; tcls = dot === "bad" ? "urgent" : "warn"; }
  td.className = "tile " + tcls; td.title = data.tail_error || data.status || "";
  fl.innerHTML = val(`<span class="dot ${dot}"></span>${text}`);
  sl.innerHTML = problems.length ? problems.join(" · ") : /^asking|^fetching/.test(data.status || "") ? esc(data.status) : "Spansh ok";
  document.getElementById("backupLine").innerHTML = backupHtml(data.backup || {});
  // docked somewhere that buys data with a worthwhile amount aboard: say so plainly
  const dk = data.docked, sellHere = sellableHere(dk, data.unsold), se = document.getElementById("sell");
  if (lossCard && Date.now() < lossCard.until) {
    const m = lossCard.m;
    se.className = "urgent";
    se.innerHTML = `💀 ${esc(lossCard.text)}` + (m.top && m.top.length ? `<br><span class="unk">most valuable lost: ${m.top.map(x =>
      `${esc(x.name)} ${credits(x.value)} cr${x.distance != null ? ` · ${x.distance.toLocaleString("en-US", {maximumFractionDigits: 0})} ly` : ""}`).join("; ")}</span>` : "") +
      ` <a href="#" data-lossfirsts>My firsts (lost)</a> <a href="#" data-lossclose title="close">✕</a>`;
  } else if (saleBanner && Date.now() < saleBanner.until) {
    se.className = "ok"; se.textContent = saleBanner.text;
  } else if (sellHere && sellHere.level && sellHere.level !== "ok") {
    se.className = sellHere.level;
    se.innerHTML = `💰 Docked at ${esc(dk.station)}${dk.has_uc ? " with Universal Cartographics" : ""}${dk.has_vista ? (dk.has_uc ? " and" : " with") + " Vista Genomics" : ""}: ` +
      `<b>${credits(sellHere.value)} cr</b> to sell here — sell before you undock.`;
  } else se.innerHTML = "";
  // tab title: what a background tab needs to know
  const p = data.position;
  document.title = (disconnected ? "⚠ " : "") + (p ? p.name : "ED Outrider") +
    (f && f.live && f.pct != null && f.pct < 30 ? ` · ⛽${f.pct}%` : "") +
    (unsoldLevel(data.unsold) === "urgent" ? " · 💰 sell!" : "");
}
// Per-browser override of the bio threshold; null follows bio_min in ed_outrider.toml (reset = null).
let bioMinCfg = store.get("bioMinCfg", store.get("bioMin", null));
const bioMinNow = () => bioMinCfg ?? (data && data.defaults && data.defaults.bio_min) ?? 10000000;
function worthLeavingFor(l) {
  // The server lists everything unfinished; the page applies your exobiology threshold:
  // un-started bio only counts if a single body could pay over bioMin (started sampling always counts).
  if (!l) return null;
  // a body the rules cannot price (potential null) is kept: unknown is not the same as worthless
  const bio = l.bio_pending.filter(b => Object.keys(b.partial || {}).length || b.potential == null || b.potential >= bioMinNow()
    || (codexNewCounts && b.codex_new));   // a species new to your codex here is worth stopping for (vouchers)
  // mapping only counts when it would add at least the green-row level (bonus-free, like the highlight),
  // or the body is special: a first-discovered / first-map ELW, water world, ammonia world or terraformable.
  // Unscanned bodies and a missing honk stay on Here's to-do line; they never sound the alert on their own.
  const maps = (l.unmapped || []).filter(u => u.special || (u.increment != null && u.increment >= hlLevel("body")));
  return {...l, bio_pending: bio, maps, clean: !maps.length && !bio.length};
}
// what a bio_pending body could pay with its first-footfall factor (the server's potential is bonus-free, so the
// bio threshold compares what it always did; the order, the per-minute figure and the "up to" use this)
const pendingWorth = b => (b.potential || 0) * (b.factor || 1);
const ffMark = b => b.factor === 5 ? " 👣×5" : "";   // the figure before it includes the x5 (spokenText drops the glyph)
// the DSS genera not started yet: a genus with samples under way is already listed as "Stratum 2/3"
const unstarted = b => (b.genera || []).filter(g => !(g in (b.partial || {})));
// a body with no DSS: the runs under way, then the signals nobody has identified ("Stratum 1/3, 2 signals not DSS'd")
const noDssText = (b, parts) => [...parts, b.signals ? `${b.signals} signal${b.signals === 1 ? "" : "s"}${parts.length ? "" : ","} not DSS'd` : ""]
  .filter(Boolean).join(", ");
function leavingText(l) {
  l = worthLeavingFor(l);
  if (!l || l.clean) return "";
  const bits = [];
  if (l.maps.length) bits.push("unmapped " + l.maps.map(u => `<b>${esc(u.body)}</b> (${esc(u.subtype)}${u.terraformable ? " T" : ""}` +
    (u.increment ? `, +${credits(u.increment)}` : "") + ")").join(", "));
  for (const b of l.bio_pending) {
    const parts = Object.entries(b.partial).map(([g, n]) => `${esc(g)} ${n}/3`).concat(unstarted(b).map(esc));
    bits.push(`bio on <b>${esc(b.body)}</b>${b.genera === null ? ` (${noDssText(b, parts)})` : parts.length ? ` (${parts.join(", ")})` : ""}` +
              (b.potential ? ` up to ${credits(pendingWorth(b))}${ffMark(b)}` : b.potential == null && !Object.keys(b.partial || {}).length ? " (value unknown)" : "") +
              (b.codex_new ? " ✦ new to your codex here" : ""));
  }
  return `Leaving with unfinished work: ${bits.join(" · ")}`;
}
// ---- the suggested order in a system (Here's to-do list, Now's Next) ----
// Supercruise time from the arrival star on a fixed community curve: about 7.5·ln(d) − 20 s up to 2,000 ls, then
// roughly linear to 6 minutes at 100,000 ls; never under 15 s, and never shorter for a farther body. Only a rough
// guide (it ignores where you are now and the time spent mapping or on foot): "suggested order", not a route.
const SC_KNEE = 7.5 * Math.log(2000) - 20;   // ~37 s at 2,000 ls
const scSeconds = ls => ls == null || !isFinite(ls) || ls < 0 ? null
  : ls <= 2000 ? Math.max(15, 7.5 * Math.log(Math.max(ls, 1)) - 20) : SC_KNEE + (ls - 2000) * (360 - SC_KNEE) / 98000;
// the spoken discovery streak: "10 known systems in a row" and "5 undiscovered systems in a row" (0 = off; a 1 from
// an older save or an import reads as 2, the smallest run that can fire)
const STREAK_DEFAULTS = {known: 10, new: 5};
const streakCfg = () => { const c = store.get("streakCfg", {}) || {}, v = k => { const n = Number(c[k] ?? STREAK_DEFAULTS[k]); const r = Math.max(0, Math.round(n)); return !isFinite(n) ? STREAK_DEFAULTS[k] : r === 1 ? 2 : r; };
  return {known: v("known"), new: v("new")}; };
// items under this many credits per minute of supercruise get a muted "skip?" (per browser; blank = 100k)
const skipFloor = () => { const v = Number(store.get("skipFloor", null) ?? 100000); return isFinite(v) && v >= 0 ? v : 100000; };
const scText = sec => sec < 90 ? `~${Math.max(10, Math.round(sec / 5) * 5)} s` : `~${Math.round(sec / 60)} min`;
// the map and bio items worth doing by your thresholds, nearest to the arrival star first, value per minute of
// supercruise breaking ties, a body with no distance last (in the server's order)
function planItems(l) {
  const w = worthLeavingFor(l);
  if (!w) return [];
  const items = [...w.maps.map(u => ({kind: "map", body: u.body, dist: u.dist_ls, value: u.increment, keep: u.special, u})),
                 ...w.bio_pending.map(b => ({kind: "bio", body: b.body, dist: b.dist_ls, value: b.potential == null ? null : pendingWorth(b),
                                             keep: !!Object.keys(b.partial || {}).length || !!b.codex_new, b}))];
  for (const it of items) {
    it.sec = scSeconds(it.dist);
    it.perMin = it.sec && it.value ? it.value / (it.sec / 60) : null;
    it.skip = !it.keep && it.perMin != null && it.perMin < skipFloor();   // started samples and specials never
  }
  return items.map((it, i) => [it, i]).sort(([a, i], [b, j]) => (a.dist == null) - (b.dist == null) || (a.dist || 0) - (b.dist || 0)
    || (b.perMin ?? -1) - (a.perMin ?? -1) || i - j).map(([it]) => it);
}
function planText(it) {
  if (it.kind === "map") { const u = it.u; return `map <b>${esc(u.body)}</b> (${esc(u.subtype)}${u.terraformable ? " T" : ""}${u.increment ? `, +${credits(u.increment)}` : ""})`; }
  const b = it.b, parts = Object.entries(b.partial || {}).map(([g, n]) => `${esc(g)} ${n}/3`).concat(unstarted(b).map(esc));
  // gravity and atmosphere: whether the landing is worth it is decided before the supercruise, not at the approach
  const g = b.gravity != null ? ` · <span class="${b.gravity >= highGravity() ? "warnc" : ""}" title="surface gravity${b.gravity >= highGravity() ? ": at or over your high-gravity level" : ""}">${b.gravity.toFixed(1)} g</span>` : "";
  const atm = b.atmosphere && b.atmosphere !== "None" ? ` · ${esc(b.atmosphere)}` : "";
  return `bio on <b>${esc(b.body)}</b>` + (b.genera === null ? ` (${noDssText(b, parts)})` : parts.length ? `: ${parts.join(", ")}` : "") +
    (b.potential ? ` up to ${credits(pendingWorth(b))}` + (b.factor === 5 ? ` <span class="ok" title="nobody had set foot here when you scanned it: exobiology pays ×5 (included)">👣×5</span>` : "") : "") +
    (b.codex_new ? ` <span class="cxnew">✦</span>` : "") + g + atm;
}
const planCost = it => it.sec == null ? "" : ` <span class="unk" title="supercruise from the arrival star (${Math.round(it.dist).toLocaleString("en-US")} ls), and what it pays per minute of that">· ${scText(it.sec)}${it.perMin ? ` · ${credits(it.perMin)}/min` : ""}</span>` +
  (it.skip ? ` <span class="unk skipq" title="under your ${credits(skipFloor())} cr per minute of supercruise">skip?</span>` : "");
// The honk's body count against the bodies Spansh has on record (l.base_known, in Here's data only): whether the FSS
// is worth it in a known system. A count only, never "first discovery": the Scan's WasDiscovered decides that, and
// Spansh is a snapshot. "" when either side is unknown.
function spanshNote(l) {
  if (!l || !l.honked || !l.body_count || l.base_known == null) return "";
  const n = Math.max(0, l.body_count - l.base_known);
  return n === 0 ? (l.unscanned > 0 ? "all on Spansh, nothing hidden" : "all on Spansh") : l.base_known === 0 ? "none on Spansh" : `${n} not on Spansh`;
}
const spanshNoteHtml = l => { const t = spanshNote(l);
  return t ? ` <span class="unk" title="the honk's body count against the bodies Spansh has on record (as of its last update)">· ${t}</span>` : ""; };
// Here's to-do list for the system: ticks itself off as you honk, find, map and sample. Items worth
// doing by your thresholds are listed in a suggested order; the rest are summarised so nothing is hidden.
function checklistHtml(l) {
  const w = worthLeavingFor(l);
  const item = (done, text) => `<li class="${done ? "done" : "todo"}">${done ? "✓" : "○"} ${text}</li>`;
  const items = [item(l.honked, l.honked ? "honked" : "honk (FSS discovery scan)"),
    item(!l.unscanned && l.honked, (l.unscanned ? `${l.unscanned} bod${l.unscanned === 1 ? "y" : "ies"} left to find in the FSS` : l.all_found ? "all bodies found" : "bodies found") + spanshNoteHtml(l))];
  const plan = planItems(l);
  if (plan.length > 1) items.push(`<li class="unk" title="nearest to the arrival star first, then the best value per minute of supercruise; a rough guide, not a route">suggested order:</li>`);
  for (const it of plan) items.push(item(false, planText(it) + planCost(it)));
  const smallMaps = (l.unmapped || []).length - w.maps.length;
  if (!w.maps.length) items.push(item(true, "no mapping worth doing" + (smallMaps ? ` <span class="unk">(${smallMaps} small, under your ${credits(hlLevel("body"))} level)</span>` : "")));
  const smallBio = l.bio_pending.length - w.bio_pending.length;
  if (!w.bio_pending.length) items.push(item(true, "no bio worth sampling" + (smallBio ? ` <span class="unk">(${smallBio} under your ${credits(bioMinNow())} threshold)</span>` : "")));
  return `<ul class="checklist">${items.join("")}</ul>`;
}
// ---- on-body strip: what is left to sample on the body you are standing on (landed, SRV, on foot) ----
let obKey = null, obData = null;
async function loadOnBody() {
  const ob = data && data.on_body;
  if (!ob) { if (obData) { obData = null; obKey = null; } renderOnBody(); return; }
  const key = `${ob.system}|${data.scan_version}`;
  if (key === obKey) return renderOnBody();
  obKey = key;
  // a thrown fetch (the server restarting, a dropped connection) is an error like a JSON one: asked again next time
  try { obData = await apiJson(`api/system/${ob.system}`); } catch (err) { obData = {error: err.message}; }
  if (obData && obData.error) obKey = null;
  renderOnBody();
}
// sample spacing: how far to walk before the next sample of this species counts as a new colony
function samplingHtml() {
  const sm = data.sampling; if (!sm || !sm.samples || sm.samples >= 3) return "";
  const head = `<b>${esc(sm.genus || "")}</b> <span class="unk">${esc((sm.species || "").split(" ").slice(1).join(" "))}</span> · sample ${sm.samples}/3`;
  // no colony distance for this genus (one ed_bio does not know): the positions may well be recorded
  if (sm.need == null && sm.points > 0) return `<div class="spacing unk">${head} · spacing unknown for this genus</div>`;
  if (sm.to_go == null) return `<div class="spacing unk">${head} · ${sm.need ? `need ${sm.need} m from the last sample` : "spacing unknown"}` +
    ` <span title="the position of your earlier samples was not recorded (they were taken before Outrider was running)">(position unknown)</span></div>`;
  return `<div class="spacing ${sm.clear ? "clear" : ""}">${head} · ` +
    (sm.clear ? `✓ clear to sample <span class="unk">(${sm.nearest} m from the nearest, ${sm.need} m needed)</span>`
              : `<b>${sm.to_go} m</b> to go <span class="unk">(${sm.nearest} of ${sm.need} m)</span>`) + `</div>`;
}
let clearAnnounced = null;
function renderOnBody() {
  const el = document.getElementById("onbody"), ob = data && data.on_body;
  if (!ob) { el.innerHTML = ""; return; }
  const b = obData && !obData.error && obData.bodies.find(x => x.name === ob.body);
  if (!b) { el.innerHTML = `On <b>${esc(ob.body)}</b> (${ob.how})`; return; }
  const bits = [], f = bioFactor(b);
  for (const g of bioGenera(b)) {
    const o = b.organics.find(o => o.genus === g), x = (b.bio_guess || []).find(q => q.genus === g);
    bits.push(o ? `<span class="sp ${o.lost ? "lost" : o.done ? "done" : "part"}">${esc(g)} ${o.lost ? "lost ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}` +
                  `${o.species ? ` <span class="unk">${esc(o.species.split(" ").slice(1).join(" "))}</span>` : ""}</span>`
               : `<span class="sp">${esc(g)} 0/3${x && x.best ? ` <span class="unk">likely ${esc(x.best.split(" ").slice(1).join(" "))} ${credits((x.value || 0) * f)}</span>${variantTxt(x)}` : ""}${codexMark(x, obData.region)}</span>`);
  }
  const unk = bioUnknown(b);
  if (unk) bits.push(`<span class="unk">${unk.label.replace(/ signals?/, m => " bio" + m)}</span>`);
  if (b.geo) bits.push(`<span class="sp geo">🪨 ${b.geo} geo</span>`);
  const x5 = b.value_parts && b.value_parts.bio_factor === 5;
  el.innerHTML = samplingHtml() + `On <b>${esc(ob.body)}</b> <span class="unk">(${ob.how})</span>: ` + (bits.join(" ") || `<span class="unk">no bio or geo signals known</span>`) +
    (x5 && (b.genera.length || b.bio) ? ` · <span class="ok" title="nobody had set foot here when you scanned it: exobiology pays ×5">first footfall ×5</span>` : "");
}
// ---- route strip: the plotted route from here, hop by hop ----
function renderRoute() {
  const r = data.route, el = document.getElementById("routeStrip");
  if (!r || !r.hops.length) { el.innerHTML = ""; return; }
  const n = r.hops.length;
  const chips = r.hops.slice(0, 24).map(h => `<span class="hop${h.scoopable ? " sc" : h.scoopable === false ? " dry" : ""}${h.visited ? " vis" : ""}" ` +
    `title="${esc(h.name)} · ${esc(h.star_class || "?")}${h.scoopable ? " (scoopable)" : h.scoopable === false ? " (not scoopable)" : ""} · ${h.ly} ly${h.visited ? " · visited" : ""}${h.known ? "" : " · not reported to Spansh"}">` +
    `${esc(h.star_class || "?")}${h.known ? "" : "✦"}</span>`).join("");
  el.innerHTML = `Route: <b>${n}</b> jump${n === 1 ? "" : "s"} · <b>${Math.round(r.ly).toLocaleString()}</b> ly` +
    (r.next_scoop ? ` · next scoop in <b>${r.next_scoop}</b>` : ` · <span class="warnc">no scoopable star on the route</span>`) +
    (r.longest_dry > 1 ? ` · <span class="${r.longest_dry >= 4 ? "warnc" : ""}">longest dry stretch ${r.longest_dry}</span>` : "") +
    ` <span class="hops">${chips}${n > 24 ? ` <span class="unk">+${n - 24}</span>` : ""}</span>`;
}
// ---- Now mode: five big lines for a second monitor, readable from the chair ----
function renderNow() {
  const el = document.getElementById("nowView"), p = data.position, f = data.fuel, t = data.target, a = data.arrival;
  if (!p) { el.innerHTML = `<div class="now-sys">waiting for your first jump…</div>`; return; }
  const lines = [`<div class="now-sys">${esc(p.name)}</div>`];
  // the arrival verdict, for twenty seconds after a jump
  if (a && a.id64 === posId() && Date.now() - Date.parse(a.ts) < 20000)
    lines.push(`<div class="now-card ${a.undiscovered ? "yes" : "no"}">${a.undiscovered ? "🏁 Undiscovered — first discovery is yours" : "Already discovered"}</div>`);
  if (t) {
    const label = {"unreported": "never reported — new discovery!", "no bodies": "no scan data", "partial": "partly scanned",
      "explored": "fully scanned", "visited": "you've been here"}[t.status] || t.status;
    const hz = hazardNote(t.star_class);
    lines.push(`<div class="now-line">➜ <b>${esc(t.name)}</b> <span class="t-${t.status.replace(" ", "")}">${esc(label)}</span>` +
      (t.star_class ? ` <span class="${/^[OBAFGKM](_|$)/.test(t.star_class) ? "ok" : "noscoop"}">${esc(t.star_class)}${/^[OBAFGKM](_|$)/.test(t.star_class) ? " ⛽" : " ✕"}</span>` : "") +
      (hz ? ` <span class="hazard">⚠ ${esc(hz)}</span>` : "") + `</div>`);
  }
  if (f && f.live && f.pct != null)
    lines.push(`<div class="now-line ${f.pct < 15 ? "urgent" : f.pct < 30 ? "warn" : ""}">⛽ <b>${f.pct}%</b>` +
      (f.jumps_max != null ? ` · ${f.jumps_max} jumps` : "") + (f.since_scoop != null ? ` · ${f.since_scoop} since scoop` : "") +
      (data.boost ? ` · <span class="boosted">boosted ×${data.boost}</span>` : "") + `</div>`);
  // landed: what is left on this body (and the sample spacing); otherwise what is left in the system
  if (data.on_body) lines.push(`<div class="now-line now-body">${document.getElementById("onbody").innerHTML}</div>`);
  else {
    const here = data.systems.find(s => s.id64 === p.id64);
    // the all-clear only once Here's data is for this system and the honk has found every body: before that
    // (just after a jump, a failed lookup, an unhonked system) there is nothing to be clear about yet
    const hd = hereData && !hereData.error && hereData.id64 === posId() ? hereData : null, l = hd && hd.leaving;
    const w = l ? worthLeavingFor(l) : null;
    const plan = w && !w.clean ? planItems(l) : [];
    const dest = hd && data.destination ? hd.bodies.find(b => b.body_id === data.destination.body_id) : null;
    const destIsNext = !!(dest && plan.length && plan[0].body === dest.name);
    lines.push(`<div class="now-line">${plan.length ? `<span class="warnc">Next: ${destIsNext ? `<span title="the body you have targeted">➜</span> ` : ""}${planText(plan[0])}${plan[0].sec != null ? ` <span class="unk">${scText(plan[0].sec)}</span>` : ""}` +
      `${plan.length > 1 ? ` <span class="unk">· ${plan.length - 1} more</span>` : ""}</span>`
      : !hd ? `<span class="unk">checking…</span>`
      : !l || !l.honked ? `<span class="warnc">Next: honk</span> <span class="unk">(FSS discovery scan)</span>`
      : l.unscanned > 0 ? `<span class="warnc">Next: ${nBodies(l.unscanned)} to find in the FSS</span>${spanshNoteHtml(l)}`
      : `<span class="ok">✓ nothing worth staying for</span>`}${here && here.value_now ? ` · <span class="unk">${credits(here.value_now)} cr aboard from here</span>` : ""}</div>`);
    // a body targeted that is not the next item: an extra line, never in place of Next (Status.json keeps the target
    // after you finish a body, so Next must stay visible)
    if (dest && !destIsNext) lines.push(`<div class="now-line now-small">${nowDestText(hd, l, plan, dest)}</div>`);
  }
  const hz = horizon(), sk = data.streak;
  if (hz || (sk && sk.total)) lines.push(`<div class="now-line now-small">${[sk && sk.total ? `<b>${sk.new}/${sk.total}</b> new` : "",
    hz ? esc(hz.system ? `nearest known unvisited: ${hz.system.name} ${hz.system.distance.toLocaleString("en-US", {maximumFractionDigits: 1})} ly` : hz.text.split(" — ")[0]) : ""].filter(Boolean).join(" · ")}</div>`);
  const ls = data.last_session;
  if (ls) lines.push(`<div class="now-line now-small">Last session: ${esc(sessionLine(ls))}</div>`);
  if (lastAlert && Date.now() - lastAlert.at < 15000)
    lines.push(`<div class="now-card alert">${esc(lastAlert.title)}${lastAlert.body ? ` <span class="unk">${esc(lastAlert.body)}</span>` : ""}</div>`);
  el.innerHTML = lines.join("");
}
// Now's heading-to line: what the targeted body is, the supercruise time (only from the arrival star or open space:
// the curve is star-relative) and what the suggested order makes of it
function nowDestText(hd, l, plan, b) {
  const it = plan.find(x => x.body === b.name);
  const listed = l && [...(l.bio_pending || []), ...(l.unmapped || [])].some(x => x.body === b.name);
  const verdict = it ? (it.skip ? `<span class="unk skipq">skip?${it.perMin ? ` ${credits(it.perMin)}/min` : ""}</span>`
                                : `<span class="ok">worth it${it.perMin ? ` · ${credits(it.perMin)}/min` : ""}</span>`)
    : listed ? `<span class="unk">under your threshold</span>`
    : b.type === "Star" ? (b.scoopable ? `<span class="ok">scoopable star</span>` : `<span class="unk">not scoopable</span>`)
    : `<span class="unk">nothing to do here</span>`;
  const near = data.destination && data.destination.near, main = hd.bodies.find(x => x.main);
  const eta = (!near || (main && near === main.name)) && near !== b.name ? scSeconds(b.dist_ls) : null;
  return `➜ <b>${esc(b.name)}</b> · ${destBits(b).map(esc).join(" · ")}${eta != null ? ` · ${scText(eta)}` : ""} · ${verdict}`;
}
document.getElementById("nowView").addEventListener("click", () => {
  view = viewBeforeNow || "overview"; store.set("view", view);
  if (new URLSearchParams(location.search).get("mode") === "now") history.replaceState(null, "", location.pathname);
  render();
});
setInterval(() => {   // arrival card and alert card expire; a failed system lookup is asked again
  if (view !== "now" || !data) return;
  if (hereData && hereData.error) loadHere();
  renderNow();
}, 2000);
function renderLeaving(l) {
  const t = leavingText(l);
  document.getElementById("leaving").innerHTML = t ? "⚠ " + t : "";
}
function statusPill(s) {
  let label = s.status, title = "";
  if (s.status === "no bodies") { label = "no scan data"; title = "known to exist, but nobody has reported scanning anything"; }
  else if (s.status === "explored") label = "fully scanned";
  else if (s.status === "partial") {
    label = s.body_count ? `${Math.floor(100 * s.bodies_known / s.body_count)}% scanned` : "partly scanned";
    title = s.body_count ? `${s.bodies_known} of ${s.body_count} bodies known` : "body count unknown (no FSS honk reported)";
  }
  return `<span class="badge s-${s.status.replace(" ", "")}" title="${title}">${label}</span>`;
}
function bodies(s) {
  if (s.source === "route" || (!s.bodies_known)) return `<span class="unk">—</span>`;
  const plain = s.ringed === null ? null : s.planets - s.ringed;
  // Hide zero counts; "?" means still loading from Spansh.
  const opt = (cls, id, n, title) => n === 0 ? "" : icon(cls, id, q(n), title);
  return `<span class="icons">${opt("star", "i-star", s.stars, "stars")}` +
    `${opt("ring", "i-ring", s.ringed, "ringed planets")}` +
    `${opt("plain", "i-plain", plain, "planets without rings")}` +
    (s.detail && s.detail.hotspots.length
      ? icon("hot", "i-hot", s.detail.hotspots.reduce((n, h) => n + Object.values(h.minerals).reduce((a, b) => a + b, 0), 0),
             "ring hotspots") : "") + `</span>`;
}
function star(s) {
  if (!s.main_class) return `<span class="unk">?</span>`;
  const scoop = s.main_scoopable
    ? ` <span class="scoop" title="scoopable">⛽</span>`
    : ` <span class="noscoop" title="not scoopable">✕</span>`;
  return `<span class="mono" title="${esc(s.main_star)}">${esc(s.main_class)}</span>${scoop}`;
}

let view = store.get("view", "near");
let viewBeforeNow = view === "now" ? "overview" : view;
if (new URLSearchParams(location.search).get("mode") === "now") view = "now";   // the only URL parameter the page reads
// Alert kinds: [key, what triggers it, its sound]. Each can notify, play its sound and be spoken, chosen
// per kind in the alerts dialog. Everything here fires for something out of the ordinary, never routine.
const ALERTS = [["discovery", "targeting a system: the fanfare if nobody has reported it (upbeat or thud if it is known)", "fanfare"],
  ["arrival", "arriving somewhere undiscovered (first visit), and a run of new or fully known systems in a row (the streak thresholds below); the sound only corrects a targeting call that was wrong", null],
  ["game", "loading into the game and quitting it", null],
  ["jump", "the frame shift drive charging for a jump (and whether the star there is scoopable)", null],
  ["honk", "the auto honk's result (when it is on; unspoken while the arrival briefing is)", null],
  ["brief", "a one-sentence briefing on arriving: discovered or not, bodies, the star, the best unmapped planet and bio (after the honk, or 12 s after arriving without one)", null],
  ["fss", "the FSS finished (what is worth mapping, or nothing worth staying for), or closed with bodies still hidden", null],
  ["leaving", "leaving a system with work worth coming back for", "alert"], ["fuel", "fuel low where you cannot scoop", "alert"],
  ["scoop", "fuel scooping filled the tank", null],
  ["scoopstop", "fuel scooping stopped early (not above 90%, nor when you jump)", null],
  ["supercharge", "the frame shift drive supercharged in a neutron star or white dwarf cone", null],
  ["find", "a valuable body just scanned (over your highlight levels)", "find"],
  ["sampling", "leaving a body with exobiology unfinished (untouched genera only if you landed there); a species completed", "alert"],
  ["approach", "approaching a landable body at or over your high-gravity level with unsold data over the amber level or rebuy multiple", "alert"],
  ["bodybrief", "approaching a body with biological signals: what they could be (the FSS already said so, so off by default)", null],
  ["sell", "docked where you can sell, and what you banked", "cash"],
  ["unsold", "unsold data crosses a threshold", "cash"], ["hull", "hull damage, heat damage, interdiction", "danger"],
  ["carrier", "your carrier arrives somewhere", "chime"], ["codex", "a new codex entry", "chime"],
  ["loss", "your ship was destroyed with data aboard (or samples died with you): what was lost, and the nearest system to rescan", "danger"]];
const UNSPOKEN = new Set(["discovery"]);   // a target's verdict: the arrival is what gets spoken
const alertCfg = Object.assign({enabled: false}, Object.fromEntries(ALERTS.map(([k]) => [k, true])),
  // a notification on every jump (or scoop, or FSS) would be noise: these are spoken by default, not notified
  {jump: false, honk: false, brief: false, fss: false, scoop: false, scoopstop: false, supercharge: false,
   sampling: false, approach: false, bodybrief: false},
  store.get("alerts", {}));
const alertSound = Object.assign(Object.fromEntries(ALERTS.map(([k]) => [k, true])), store.get("alertSound", {}));
// not spoken until you tick them: they repeat what the game (or another alert) already told you
const QUIET_KINDS = {scoopstop: false, supercharge: false, bodybrief: false};
const alertSpeak = Object.assign(Object.fromEntries(ALERTS.map(([k]) => [k, true])), QUIET_KINDS, store.get("alertSpeak", {}));
let speechOn = store.get("speech", false);
function notify(kind, title, body) {
  if (!alertCfg.enabled || !alertCfg[kind] || typeof Notification === "undefined" || Notification.permission !== "granted") return false;
  try { new Notification(title, {body, tag: "ed-" + kind}); return true; } catch { return false; }
}
// ---- one speaker: with the page open in several windows (the second screen at ?mode=now, a forgotten tab),
// only one of them speaks and plays the alert sounds; every window still shows the cards and notifications.
// The browser's Web Locks pick it: the first window holds "ed-speaker" until it closes, then the next one in
// line gets it, with no heartbeats to go stale. Without Web Locks (an old browser, a plain-http LAN address,
// the jsdom smoke test) every window speaks, as before. "This screen speaks" in the alerts dialog (per browser)
// can make this browser always speak or never.
let isSpeaker = !(typeof navigator !== "undefined" && navigator.locks && navigator.locks.request);
let speakerWait = null;   // this window's place in the queue for the lock (an AbortController)
function claimSpeaker(steal = false) {
  if (!(typeof navigator !== "undefined" && navigator.locks && navigator.locks.request)) return;
  if (speakerWait) { const w = speakerWait; speakerWait = null; w.abort(); }   // stealing: leave the queue first
  const ac = steal ? null : new AbortController();
  speakerWait = ac;
  navigator.locks.request("ed-speaker", steal ? {steal: true} : {signal: ac.signal}, () => {
    if (speakerWait === ac) speakerWait = null;
    isSpeaker = true; drawSpeaker();
    return new Promise(() => {});   // held for the life of the window (or until another window takes it)
  }).catch(() => {
    if (ac && ac.signal.aborted) return;   // we left the queue ourselves, to steal it
    isSpeaker = false; drawSpeaker(); claimSpeaker();   // another window took it: wait in line again
  });
}
const speakMode = () => { const m = store.get("speakMode", "auto"); return ["auto", "always", "never"].includes(m) ? m : "auto"; };
const speakerHere = () => speakMode() === "always" || (speakMode() === "auto" && isSpeaker);
// One path for every alert: its sound (if sounds are on and the kind's sound is ticked), a desktop
// notification (if enabled), and speech (if 🗣 is on and the kind is ticked). `say` defaults to the title;
// it may be a function (a personality line from speech.json), called only when the alert is spoken.
// Sound and speech only in the speaking window. `tag` (a speech.json key) and `still` go to the speech queue.
// Returns whether the alert reached you: spoken (queued) or notified.
let lastAlert = null;
// ---- the spoken-line transcript ("Spoken lines" at the bottom of the alerts dialog): the last 100 alerts and
// lines in this window, each with its fate (said, cut short, dropped and why, silent and why), so the first live
// session can answer "why did it not say X". In memory only: a reload starts it afresh.
const SPEECH_LOG_MAX = 100;
const speechLog = [];
let speechPlaying = null;   // the entry of the line being said now: whatever cuts it short marks it
function logSpeech(e) {
  const entry = Object.assign({t: Date.now(), kind: "manual", tag: null, style: null, voice: null, words: "", fate: null}, e);
  speechLog.push(entry);
  if (speechLog.length > SPEECH_LOG_MAX) speechLog.shift();
  drawSpeechLogSoon();
  return entry;
}
// the first fate given is the one kept (a line cut short is not then also "said")
function setFate(entry, fate) { if (entry && !entry.fate) { entry.fate = fate; drawSpeechLogSoon(); } }
// the queued lines a step took out, each given its fate (a string, or a function of the item)
function dropFates(before, after, fate) {
  for (const it of before) if (!after.includes(it)) setFate(it.log, typeof fate === "function" ? fate(it) : fate);
}
// how long each sound plays before the voice starts (the fanfare's held chord runs to 1.7 s); others 900 ms
const SOUND_LEAD = {fanfare: 1700, chime: 1000};
function alertOut(kind, title, body, {sound, say, delay = 0, tag = null, still = null, quiet = false} = {}) {
  lastAlert = {kind, title, body, at: Date.now()};
  const entry = logSpeech({kind, tag, words: title});
  const snd = sound === undefined ? (ALERTS.find(a => a[0] === kind) || [])[2] : sound;
  const loud = speakerHere();
  const plays = !!(loud && snd && soundOn && alertSound[kind]);   // no sound, no wait before the words
  if (plays) setTimeout(() => play(snd), delay);
  const notified = notify(kind, title, body);
  if (loud && speechOn && alertSpeak[kind] && !UNSPOKEN.has(kind) && !quiet) {
    lineStyle = null;
    const words = (typeof say === "function" ? say() : say) || title;
    entry.style = lineStyle;
    speak(words, {delay: plays ? delay + (SOUND_LEAD[snd] ?? 900) : delay, kind, tag, still, log: entry, ...styleVoice(lineStyle)});
    return true;
  }
  setFate(entry, !loud ? "silent: another window speaks" : !speechOn ? "silent: speech off" : UNSPOKEN.has(kind) ? "not spoken (the arrival is)"
    : quiet ? "merged into another line (quiet)" : "silent: not ticked to speak");
  return notified;
}
// ---- the speech queue: the most urgent line first, stale ones dropped ----
// Danger (hull, heat, interdiction, fuel, the carrier leaving without you) goes first, then a line you asked
// for, then arrivals, jumps, the honk, selling; finds, signals and codex last. Oldest first within a level.
// A line is dropped when it comes up if it waited over 20 s, if it is about a system you have since left
// (a find, signals, the honk, "FSD charging" once you arrived), or if its `still` check fails (clear to
// sample after the next sample). A newer line with the same tag replaces a queued one, and heat and
// interdiction are said at most once in 30 s, so a flapping condition cannot keep repeating.
const SPEECH_MAX_AGE = 20000;
const SPEECH_COOLDOWN = {heat: 30000, interdicted: 30000};
const SPEECH_SYS_BOUND = new Set(["find", "signals", "jump", "honk", "brief", "fss", "approach", "bodybrief"]);
const speechPrio = (kind, tag) => DANGER.has(tag) || kind === "hull" || kind === "fuel" ? 0 : kind === "manual" ? 1
  : ["find", "signals", "codex", "bodybrief", "supercharge"].includes(kind) ? 3 : 2;
// the queue without what went stale by `now` with the ship at `pos`
const speechExpire = (items, now, pos) => items.filter(it => now - it.notBefore <= SPEECH_MAX_AGE
  && (it.sys == null || it.sys === pos) && (!it.still || it.still()));
// the index of the next line: the most urgent, then the oldest
const speechPick = items => items.reduce((b, it, i) => b < 0 || it.prio < items[b].prio || (it.prio === items[b].prio && it.at < items[b].at) ? i : b, -1);
// may a line with this tag be queued now? (only the cooled-down kinds are ever refused)
const speechCooled = (last, tag, now) => !(tag in SPEECH_COOLDOWN) || last[tag] == null || now - last[tag] >= SPEECH_COOLDOWN[tag];
// a new line joins the queue, replacing a waiting one with the same tag (the newer news wins)
const speechAdd = (items, item) => [...items.filter(it => !item.tag || it.tag !== item.tag), item];
let speechItems = [], speechBusy = false, speechWake = null, speechNow = null, speechLast = {};
// numbers are spoken to a tenth at most, and "52.0" as "52" (12.64B is "12.6 billion", 52.0M "52 million")
const spokenNumber = m => String(Math.round(Number(m) * 10) / 10);
// a procedural system name's sector suffix, letter by letter: "Drojau LL-O b26-3" is said "Drojau L L O, b 26 3"
// (read as written, a voice mangles "LL-O b26-3"). It needs the space, mass code and number after the letters,
// so a carrier id ("K7F-3XZ") and a hand-named system ("Jaques") are left alone. ed_speech.spoken_text has the twin.
const PROC_NAME = /\b([A-Z])([A-Z])-([A-Z]) ([a-h])(\d+)(?:-(\d+))?\b/g;
const procSpoken = (_, a, b, c, mass, n, m) => `${a} ${b} ${c}, ${mass} ${n}${m ? " " + m : ""}`;
const spokenText = t => String(t).replace(/<[^>]+>/g, "").replace(/[⚠📖🚢💰🧬🏁🗺👣⛽🌋🪨✦★☆]/gu, "")
  .replace(/(?<![\d.])\d+\.\d+(?![\d.])/g, spokenNumber)
  .replace(/(\d+(?:\.\d+)?)M\b/g, "$1 million").replace(/(\d+(?:\.\d+)?)k\b/g, "$1 thousand")
  .replace(/(\d+(?:\.\d+)?)B\b/g, "$1 billion").replace(/\bcr\b/g, "credits").replace(/\s·\s/g, ", ")
  .replace(PROC_NAME, procSpoken).replace(/\s+/g, " ").trim();
// Piper's audio plays through the AudioContext, which the browser keeps suspended until you click the page.
// Wait up to a second for it to resume; if it will not, the line goes to the browser's own voice instead
// of being dropped, and the page says once what unlocks Piper.
let piperBlockedSaid = false;
async function runningAudio() {
  const ctx = audio(); if (!ctx) return null;
  if (ctx.state !== "running") { try { await Promise.race([ctx.resume(), new Promise(res => setTimeout(res, 1000))]); } catch {} }
  return ctx.state === "running" ? ctx : null;
}
// Queue a line. `delay` (ms) holds it back without holding up the lines behind it (it lets an alert's sound
// play first); `kind` is the alert kind ("manual" for a click in this window), `tag` its speech.json key.
// `log` is the transcript entry alertOut made for it (a line spoken some other way gets its own).
function speak(text, {delay = 0, kind = "manual", tag = null, still = null, voice = null, pace = 1, log = null} = {}) {
  const words = spokenText(text);
  const entry = log || logSpeech({kind, tag});
  if (words) entry.words = words;
  if (voice) entry.voice = voice;
  if (!words) return setFate(entry, "nothing to say");
  const now = Date.now();
  if (tag && !speechCooled(speechLast, tag, now)) return setFate(entry, `refused: said under ${SPEECH_COOLDOWN[tag] / 1000} s ago`);
  if (tag) speechLast[tag] = now;
  const item = {words, kind, tag, still, voice, pace, prio: speechPrio(kind, tag), at: now, notBefore: now + delay,
                sys: SPEECH_SYS_BOUND.has(kind) && data && data.position ? data.position.id64 : null, log: entry};
  const before = speechItems;
  speechItems = speechAdd(speechItems, item);
  dropFates(before, speechItems, `replaced by a newer ${tag}`);
  if (item.prio === 0 && speechNow && speechNow.prio >= 3) { setFate(speechPlaying, "cut short by danger"); speechNow.stop(); }   // danger cuts a find short
  if (speechWake) speechWake();
  if (!speechBusy) speechWorker();
}
// The FSD is charging for a jump: whatever was queued or playing is about where you are leaving, so it goes
// and the charging line takes its place. Danger lines stay (a low tank or an unscoopable target matters most
// now), and so does anything asked for in this window (the ▶ try button).
const speechForJump = items => items.filter(it => it.prio === 0 || it.kind === "manual");
function clearForJump() {
  const before = speechItems;
  speechItems = speechForJump(speechItems);
  dropFates(before, speechItems, "dropped: the FSD charged for a jump");
  if (speechNow && speechNow.prio !== 0 && speechNow.kind !== "manual") { setFate(speechPlaying, "cut short: the FSD charged"); speechNow.stop(); }
}
const hushReason = () => !speechOn ? "speech off" : "another window speaks";
// Speech turned off, or this window no longer the one speaking: the alerts queued (and the one playing) go
// quiet at once; `all` also drops lines asked for here (the ▶ try button). The worker checks it too.
function hushSpeech(all = false) {
  const before = speechItems;
  speechItems = all ? [] : speechItems.filter(it => it.kind === "manual");
  dropFates(before, speechItems, `dropped: ${hushReason()}`);
  if (speechNow && (all || speechNow.kind !== "manual")) { setFate(speechPlaying, `cut short: ${hushReason()}`); speechNow.stop(); }
}
// the one worker: says a line at a time until the queue is empty
async function speechWorker() {
  speechBusy = true;
  try {
    for (;;) {
      if (!speechOn || !speakerHere()) {
        const before = speechItems;
        speechItems = speechItems.filter(it => it.kind === "manual");
        dropFates(before, speechItems, `dropped: ${hushReason()}`);
      }
      // speechExpire stays pure (the smoke test calls it): what it took out is told apart here
      const before = speechItems, now = Date.now(), pos = data && data.position && data.position.id64;
      speechItems = speechExpire(speechItems, now, pos);
      dropFates(before, speechItems, it => now - it.notBefore > SPEECH_MAX_AGE ? `dropped: waited over ${SPEECH_MAX_AGE / 1000} s`
        : it.sys != null && it.sys !== pos ? "dropped: you left the system" : "dropped: no longer true");
      const i = speechPick(speechItems); if (i < 0) break;
      const wait = speechItems[i].notBefore - Date.now();
      if (wait > 0) {   // a new line wakes it early: it may be more urgent
        await new Promise(res => { speechWake = res; setTimeout(res, wait); });
        speechWake = null; continue;
      }
      const [item] = speechItems.splice(i, 1);
      const e = item.log, t0 = Date.now();
      if (e) e.waited = t0 - item.at;
      speechPlaying = e || null;
      try { await sayNow(item); } catch {}
      speechPlaying = null;
      if (e) {
        e.took = Date.now() - t0; e.engine = item.engine || null;
        setFate(e, item.unsaid ? `not said: ${item.unsaid}` : item.timedOut ? "timed out (the browser voice hung)" : "said");
      }
    }
  } finally { speechBusy = false; }
}
// say one line: Piper on the server when it has a voice ready, else the browser's own; stop() cuts it short
async function sayNow(item) {
  const cur = speechNow = {prio: item.prio, kind: item.kind, stopped: false, halt: null, stop() { this.stopped = true; if (this.halt) this.halt(); }};
  try {
    const tts = data && data.tts;
    const ctx = tts && tts.engine === "piper" ? await runningAudio() : null;
    if (tts && tts.engine === "piper" && !ctx && !piperBlockedSaid) {
      piperBlockedSaid = true; toast("Click the page to allow Piper audio (the browser's voice speaks until then)");
    }
    if (ctx) {
      try {
        const speed = Math.min(2, Math.max(0.5, speechSpeed() * (item.pace || 1)));
        const r = await fetch(`api/say?text=${encodeURIComponent(item.words)}&speed=${speed}${item.voice ? `&voice=${encodeURIComponent(item.voice)}` : ""}`);
        if (r.ok) {
          const buf = await ctx.decodeAudioData(await r.arrayBuffer());
          if (cur.stopped) return;
          const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination);
          item.engine = "Piper";
          await new Promise(res => { src.onended = res; cur.halt = () => { try { src.stop(); } catch {} res(); }; src.start(); });
          return;
        }
      } catch {}
    }
    if (cur.stopped) return;
    if (typeof speechSynthesis === "undefined") { item.unsaid = "no voice in this browser"; return; }
    item.engine = tts && tts.engine === "piper" ? (ctx ? "browser voice (Piper failed)" : "browser voice (Piper audio blocked)") : "browser voice";
    await new Promise(res => {
      let done = false; const finish = () => { if (!done) { done = true; res(); } };
      const rate = Math.min(2, Math.max(0.5, speechSpeed() * (item.pace || 1)));
      const u = new SpeechSynthesisUtterance(item.words); u.rate = rate; u.onend = u.onerror = finish;
      cur.halt = () => { speechSynthesis.cancel(); finish(); };
      speechSynthesis.speak(u);
      // The end event does not always come (Chrome drops it on long lines). After 15 s go by what the browser
      // says it is doing, and past a cap from the line's length (about 11 characters a second) cancel it: the
      // next line must never wait inside the browser's own queue, where expiry and priority cannot reach it.
      const cap = Date.now() + Math.max(15000, Math.min(60000, 5000 + item.words.length * 90 / rate));
      const check = () => {
        if (done) return;
        if (Date.now() > cap) { item.timedOut = true; speechSynthesis.cancel(); finish(); }
        else if (!speechSynthesis.speaking && !speechSynthesis.pending) finish();
        else setTimeout(check, 250);
      };
      setTimeout(check, 15000);
    });
  } finally { if (speechNow === cur) speechNow = null; }
}
// ---- spoken lines: speech.json's versions of each alert, per personality (see ed_speech.py) ----
let speechLib = {styles: {}, lines: {}, version: null}, speechLibWanted = null;
const speechStyles = () => { const v = store.get("speechStyles", null) ?? (data && data.defaults && data.defaults.speech_styles);
  return Array.isArray(v) ? v.filter(x => typeof x === "string") : ["business"]; };   // store.get already drops a non-list
const speechProfane = () => store.get("speechProfanity", null) ?? (data && data.defaults && data.defaults.speech_profanity) ?? false;
// how often (percent) a line comes from the swearing versions when profanity is on
const speechProfanePct = () => Math.min(100, Math.max(0, Number(store.get("speechProfanityPct", null)
  ?? (data && data.defaults && data.defaults.speech_profanity_pct) ?? 50)));
// what the voice calls you: commander names are often unpronounceable, so {name} is one of these at random
const speechNames = () => String(store.get("speechNames", null) ?? (data && data.defaults && data.defaults.speech_names) ?? "Boss, Hefay, Sir")
  .split(",").map(x => x.trim()).filter(Boolean);
// the voice's pace: 1 is its own, 1.3 is 30% faster
const speechSpeed = () => Math.min(2, Math.max(0.5, Number(store.get("speechSpeed", null) ?? (data && data.defaults && data.defaults.speech_speed) ?? 1) || 1));
// say signal counts as the FSS finds them: "bio" and "geo", each its own tick
const saySignals = k => !!(store.get(k === "bio" ? "sayBio" : "sayGeo", null)
  ?? (data && data.defaults && data.defaults[k === "bio" ? "speak_bio_signals" : "speak_geo_signals"]) ?? true);
const recentLines = {};
async function loadSpeechLib() {
  // a failed load forgets the version it wanted, so the next payload tries again
  try { const r = await fetch("api/speech"); if (r.ok) { speechLib = await r.json(); drawSpeechStyles(); return; } } catch {}
  speechLibWanted = null;
}
// a line's {placeholders}; {name}, {cmdr}, {ship} and {here} are always there when known
function lineVars(vars) {
  const names = speechNames();
  // a function: every {name} in a line is its own random pick
  const all = {name: () => names.length ? names[Math.floor(Math.random() * names.length)] : "Commander",
               cmdr: data && data.commander && data.commander.name, ship: data && data.ship ? shipLabel(data.ship.name, data.ship.type) : null,
               here: data && data.position && data.position.name};
  for (const [k, v] of Object.entries(vars)) if (v != null && v !== "") all[k] = v;
  return all;
}
const fillLine = (text, all) => text.replace(/\{(\w+)\}/g, (_, k) => all[k] == null ? "" : String(typeof all[k] === "function" ? all[k]() : all[k]));
const allFilled = (text, all) => [...text.matchAll(/\{(\w+)\}/g)].every(m => all[m[1]] != null);
// Danger lines: a joke at 20% hull costs clarity, so with "Danger alerts always down to business" ticked (the
// default) these come only from the business lists and never swear, whatever personalities are ticked.
// (ship_lost too: a debrief after a rebuy is no time for a joke; it also jumps the queue like the others)
const DANGER = new Set(["hull", "heat", "interdicted", "fuel_low", "fuel_star", "fuel_target", "carrier_departs", "ship_lost"]);
const speechDangerBusiness = () => !!(store.get("speechDangerBusiness", null) ?? (data && data.defaults && data.defaults.speech_danger_business) ?? true);
// "One personality per system": the personality is drawn at game start and at each arrival and says every line
// until the next one, so a character (and its own voice) holds through a system. In memory only: a reload draws
// afresh on its first line. Danger lines still come from business when that box is ticked.
const speechShift = () => !!store.get("speechShift", false);
let shiftStyle = null;
function pickShift() {
  const lines = Object.values(speechLib.lines || {});
  const has = st => lines.some(e => e && [st, st + "_profane"].some(k => Array.isArray(e[k]) && e[k].length));
  const pool = speechStyles().filter(has);
  shiftStyle = pool.length ? pool[Math.floor(Math.random() * pool.length)] : null;
}
// A random version of alert `key` from every personality ticked (and their swearing versions when
// profanity is on), not one of the last few heard; `plain` when the file has nothing for it.
function line(key, vars = {}, plain = "") {
  const entry = speechLib.lines && speechLib.lines[key];
  const listOf = name => !entry || typeof entry !== "object" || !Array.isArray(entry[name]) ? []
    : entry[name].filter(x => typeof x === "string" && x.trim());
  // a danger line: business alone (a custom speech.json without business lines falls back to the ticked ones)
  const serious = DANGER.has(key) && speechDangerBusiness();
  const ticked = speechStyles(), shift = speechShift();
  if (shift && !(shiftStyle && ticked.includes(shiftStyle))) pickShift();   // first line, or its personality unticked
  // the personality on shift, unless it has nothing for this alert (then every ticked one, as without the tick)
  const onShift = shift && shiftStyle && (listOf(shiftStyle).length || (speechProfane() && listOf(shiftStyle + "_profane").length));
  const styles = serious && listOf("business").length ? ["business"] : onShift ? [shiftStyle] : ticked;
  const lists = suffix => styles.flatMap(st => listOf(st + suffix).map(x => [st, x]));   // [personality, line]
  // with profanity on, roll first: the swearing versions this share of the time, the clean ones otherwise
  // (whichever side has nothing for this alert gives way to the other)
  const clean = lists(""), rude = speechProfane() && !serious ? lists("_profane") : [];
  let pool = rude.length && (!clean.length || Math.random() * 100 < speechProfanePct()) ? rude : clean;
  if (!pool.length) return plain;
  const all = lineVars(vars), whole = pool.filter(x => allFilled(x[1], all));
  if (whole.length) pool = whole;   // a line that needs a value this alert lacks only as a last resort
  const recent = recentLines[key] || (recentLines[key] = []);
  const fresh = pool.filter(x => !recent.includes(x[1]));
  const [style, pick] = (fresh.length ? fresh : pool)[Math.floor(Math.random() * (fresh.length || pool.length))];
  recent.push(pick);
  while (recent.length > Math.min(4, Math.floor(pool.length / 2))) recent.shift();
  lineStyle = style;
  return fillLine(pick, all);
}
// The personality of the line line() picked last, and the voice it asks for: a style in speech.json may be
// {label, voice, speed}, a Piper voice of its own (only if installed; it wins over the dialog's voice) and a
// pace multiplying yours. The browser's own speech ignores the voice.
let lineStyle = null;
function styleVoice(style) {
  const st = style && speechLib.styles && speechLib.styles[style];
  return st && typeof st === "object" ? {voice: typeof st.voice === "string" ? st.voice : null,
                                         pace: Number(st.speed) >= 0.5 && Number(st.speed) <= 2 ? Number(st.speed) : 1} : {voice: null, pace: 1};
}
// a star class as words, for {star}
const spokenStar = c => !c ? "star" : /^D/.test(c) ? "white dwarf" : c === "N" ? "neutron star"
  : /^(H|BH|SupermassiveBlackHole)$/.test(c) ? "black hole" : /^W/.test(c) ? "Wolf-Rayet star" : /^(C|CN|CJ|CH|CHd|CS)$/.test(c) ? "carbon star"
  : /^[LTY]$/.test(c) ? "brown dwarf" : c === "TTS" ? "T Tauri star" : c === "AeBe" ? "Herbig star" : /^(S|MS)$/.test(c) ? "S-type star"
  // giants and supergiants: K_OrangeGiant is "K orange giant", A_BlueWhiteSuperGiant "A blue white supergiant"
  : /^[OBAFGKM]_\w+$/.test(c) ? `${c[0]} ${c.slice(2).replace(/SuperGiant/g, "Supergiant").replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()}`
  : `${c} star`;
// sample values for the ▶ try button
const LINE_SAMPLES = {
  speech_on: {}, game_start: {}, game_exit: {}, heat: {},
  arrival_undiscovered: {system: "Drojau LL-O b26-3"}, arrival_discovered: {system: "Drojau LL-O b26-3"},
  leaving: {text: "A 2, a class two gas giant, plus 1.4M to map"},
  find_body: {what: "Water world, terraformable, undiscovered", body: "A 3", value: "2.3M"},
  find_bio: {body: "B 7", value: "19.0M"}, sample_clear: {genus: "Stratum"},
  codex: {entry: "Stratum Tectonicas", what: "new to your codex for this region"},
  fuel_low: {pct: 18}, fuel_star: {pct: 22, star: "white dwarf"}, fuel_target: {pct: 22, system: "Drojau LL-O b26-3"},
  hull: {pct: 42}, interdicted: {by: "someone"},
  docked_sell: {value: "114.1M", station: "Jaques Station"}, undocked_unsold: {value: "260.4M"},
  sold: {sold: "12.6M cr cartographics and 4.1M cr exobiology", still: ""},
  unsold_warn: {value: "52.0M"}, unsold_urgent: {value: "251.3M"},
  carrier_departs: {minutes: 4, carrier: "Out Of The Blue"}, carrier_arrived: {carrier: "Out Of The Blue", system: "Smojooe AR-E b25-8"},
  fss_done: {count: 14, text: "B 1, Earth-like world, 3.1M to map, and biology on C 2, up to 19.0M"},
  fss_nothing: {count: 14}, fss_unfinished: {left: "3 bodies"},
  left_body: {body: "A 3", text: "Stratum 2 of 3, and Tussock untouched, up to 4.1M"},
  bio_done_more: {species: "Stratum Tectonicas", value: "19.2M", left: "Bacterium and Fungoida"},
  bio_done_last: {species: "Stratum Tectonicas", value: "19.2M"},
  tank_full: {jumps: 8}, scoop_stopped: {pct: 64}, supercharged: {mult: "4 times"},
  body_brief: {body: "B 7", text: "3 biological signals, one of Stratum, Bacterium or Fungoida, 1.0M to 19.0M"},
  high_g: {gravity: "2.6", value: "480.2M", rebuys: "3.2"},
  arrival_brief: {text: "Undiscovered. 14 bodies. Scoopable K star."},
  session_recap: {text: "142 jumps, 3,100 light-years, 12 systems nobody had seen, 9 species sampled"},
  streak_known: {count: 10}, streak_new: {count: 5},
  welcome_back: {text: "Away 3 days. 412.0M aboard, unsold for 5 days. Fuel 64 percent. Docked at Jaques Station."},
  ship_lost: {text: "Lost 212.4M: 148.1M cartographics and 64.3M exobiology, 31 systems and 9 first discoveries. The nearest lost system is Drojau LL-O b26-3, 42 light-years."},
};
// ---- the words of the composed call-outs: the server sends the facts, these apply your thresholds ----
// The login greeting after a long break: how long, what is at stake, the tank, where you are. The amount aboard
// only past the amber level, and not when the dock alert on the same payload says it (one line carries it).
function welcomeText(away, dockSays) {
  const u = data.unsold, lvl = unsoldLevel(u), ss = data.since_sale, f = data.fuel, dk = data.docked, ob = data.on_body;
  const parts = [`Away ${away}.`];
  if (u && !u.error && lvl && lvl !== "ok" && !dockSays) {
    const d = ss && ss.days >= 1 ? Math.round(ss.days) : 0;
    parts.push(`${credits(u.total)} aboard${d ? `, unsold for ${d} day${d === 1 ? "" : "s"}` : ""}.`);
  }
  if (f && f.pct != null) parts.push(`Fuel ${f.pct} percent.`);
  if (dk && dk.station) parts.push(`Docked at ${dk.station}.`);
  else if (ob && ob.body) parts.push(`${ob.how === "on foot" ? "On foot" : ob.how === "in the SRV" ? "In the SRV" : "Landed"} on ${ob.body}.`);
  return parts.join(" ");
}
// The ship-loss debrief: what died with the ship (the server's totals, the same as History's) and the nearest
// system whose scans were lost. A death on foot that cost only samples says just that.
function lossText(m) {
  const kinds = [m.carto && [credits(m.carto), "cartographics"], m.bio && [credits(m.bio), "exobiology"]].filter(Boolean);
  const what = [m.systems && `${m.systems} system${m.systems === 1 ? "" : "s"}`,
                m.firsts && `${m.firsts} first discover${m.firsts === 1 ? "y" : "ies"}`,
                m.bio_runs && `${m.bio_runs} species sampled`].filter(Boolean);
  const n = m.nearest;
  return `Lost ${credits(m.value)}${kinds.length > 1 ? `: ${kinds.map(k => k.join(" ")).join(" and ")}` : kinds.length ? ` of ${kinds[0][1]}` : ""}` +
    `${what.length ? `, ${andList(what)}` : ""}.` + (n && n.distance != null ? ` The nearest lost system is ${n.name}, ${Math.round(n.distance)} light-years.` : "");
}
let lossCard = null;   // the debrief card under the header: {m, text, until}, until closed or half an hour
const andList = xs => xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0] || "";
const orList = xs => xs.length > 1 ? `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}` : xs[0] || "";
const nBodies = n => `${n} bod${n === 1 ? "y" : "ies"}`;
// a planet class for the voice: "Earth-like world", "terraformable high metal content world"
const spokenClass = (sub, tf) => `${tf ? "terraformable " : ""}${String(sub || "planet").replace(/^(?!Earth)\w/, c => tf ? c.toLowerCase() : c)}`;
// what the FSS debrief names: the maps and the bio your thresholds keep, most valuable first, three at most
function worthSaying(l) {
  const w = worthLeavingFor(l); if (!w || w.clean) return "";
  const maps = w.maps.map(u => ({v: u.increment || 0, t: `${u.body}, ${spokenClass(u.subtype, u.terraformable)}${u.increment ? `, ${credits(u.increment)} to map` : ""}`}));
  const bio = w.bio_pending.map(b => ({v: pendingWorth(b), t: `biology on ${b.body}${b.potential ? `, up to ${credits(pendingWorth(b))}${b.factor === 5 ? " with first footfall" : ""}` : ""}`}));
  const items = [...maps.sort((a, b) => b.v - a.v).slice(0, 2), ...bio.sort((a, b) => b.v - a.v).slice(0, 2)].slice(0, 3).map(x => x.t);
  const more = w.maps.length + w.bio_pending.length - items.length;
  return andList(items) + (more > 0 ? `, and ${more} more` : "");
}
// the leaving alert's spoken words: three items at most, picked as the FSS debrief picks them (the two best maps,
// then the two best bio bodies, a sampling run under way first), then "and N more"; the notification keeps the
// whole list. A long line is slow to hear, and Piper cuts one past 1,000 characters at a sentence end.
function leavingSaid(l) {
  const w = worthLeavingFor(l); if (!w || w.clean) return "";
  const maps = w.maps.map(u => ({v: u.increment || 0, t: `${u.body}, ${spokenClass(u.subtype, u.terraformable)}${u.increment ? `, ${credits(u.increment)} to map` : ""}`}));
  const bio = w.bio_pending.map(b => { const runs = Object.entries(b.partial || {}).map(([g, n]) => `${g} ${n} of 3`);
    return {v: runs.length ? Infinity : pendingWorth(b), t: `biology on ${b.body}${runs.length ? ` (${andList(runs)})` : ""}${b.potential ? `, up to ${credits(pendingWorth(b))}${b.factor === 5 ? " with first footfall" : ""}` : ""}`}; });
  const items = [...maps.sort((a, b) => b.v - a.v).slice(0, 2), ...bio.sort((a, b) => b.v - a.v).slice(0, 2)].slice(0, 3).map(x => x.t);
  const more = maps.length + bio.length - items.length;
  return andList(items) + (more > 0 ? `, and ${more} more` : "");
}
// leaving a body: runs under way always; the DSS's untouched genera (over your bio threshold, or unpriced) only
// when you touched down or sampled there this visit
function leftBodyText(m) {
  const parts = Object.entries(m.partial || {}).map(([g, n]) => `${g} ${n} of 3`);
  if (m.touched) {
    for (const u of m.untouched || [])
      if (u.value == null || u.value >= bioMinNow()) parts.push(`${u.genus} untouched${u.value ? `, up to ${credits(u.value * (m.factor || 1))}` : ""}`);
    if (m.unidentified) parts.push(`${m.unidentified} signal${m.unidentified === 1 ? "" : "s"} not identified`);
  }
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")}, and ${parts[parts.length - 1]}` : parts[0] || "";
}
// what is still worth sampling on a body after a species is done: "" only when nothing at all is left (with only
// genera under your bio threshold left: "only 1 small one", so the line never says the body is finished);
// signals no DSS has named (unidentified) are always left, whatever they turn out to be
function bioLeftText(m) {
  const all = [...Object.keys(m.partial || {}).map(g => ({genus: g, value: null, started: true})), ...(m.untouched || [])];
  const big = all.filter(u => u.started || u.value == null || u.value >= bioMinNow()), small = all.length - big.length;
  const names = big.map(u => u.genus);
  if (m.unidentified > 0) names.push(`${m.unidentified} more signal${m.unidentified === 1 ? "" : "s"} not identified`);
  if (!names.length) return small ? `only ${small} small one${small === 1 ? "" : "s"}` : "";
  return andList(names) + (small ? `, plus ${small} small one${small === 1 ? "" : "s"}` : "");
}
// the approach: what the bio signals could be ("" without any)
function bodyBriefText(m) {
  if (!m.signals && !(m.genera || []).length) return "";
  const n = m.signals ? `${m.signals} biological signal${m.signals === 1 ? "" : "s"}` : "biology";
  const x = m.factor === 5 ? ", first footfall times five" : "";   // the values are before the bonus
  if ((m.genera || []).length) return `${n}: ${andList(m.genera)}${m.bio_value ? `, up to ${credits(m.bio_value)}` : ""}${x}`;
  if (m.bio_options) return `${n}, ${m.signals === 1 ? "one" : m.signals} of ${orList(m.bio_options.genera.slice(0, 4))}${m.bio_options.genera.length > 4 ? " or others" : ""}, ` +
    `${credits(m.bio_options.low)} to ${credits(m.bio_options.high)}${x}`;
  return n + (m.bio_value ? `, up to ${credits(m.bio_value)}` : "") + x;
}
// the approach's stakes: a landable body at or over the high-g level while the data aboard is over the amber
// level or the rebuy multiple; null when it is not worth a word
const highGravity = () => { const v = Number(store.get("highG", null) ?? (data && data.defaults && data.defaults.high_gravity) ?? 2); return isFinite(v) && v > 0 ? v : 2; };
function highGStakes(m) {
  const u = data && data.unsold, rebuy = data && data.ship && data.ship.rebuy;
  if (!m.landable || m.gravity == null || m.gravity < highGravity() || !u || u.error || u.total == null) return null;
  const lvl = unsoldLevel(u); if (lvl !== "warn" && lvl !== "urgent") return null;
  return {gravity: String(Math.round(m.gravity * 10) / 10), value: credits(u.total), rebuys: rebuy ? (u.total / rebuy).toFixed(1) : ""};
}
// the arrival briefing: verdict, body count, star, then the best unmapped planet and the richest bio over your levels
function arrivalBriefText(m) {
  const verdict = m.undiscovered && !(m.visits > 1) ? "Undiscovered." : m.visits > 1 ? "Visited before." : m.status === "explored" ? "Fully scanned."
    : m.in_spansh ? "Known." : m.undiscovered === false ? "Known, not in Spansh." : "";
  const bits = [verdict];
  if (m.body_count) bits.push(m.all_found ? `All ${nBodies(m.body_count)} found.` : `${nBodies(m.body_count)}.`);
  // how many of them Spansh has no record of (a count: the tags are still yours to scan, whatever Spansh says)
  const unrep = m.in_spansh && m.body_count && m.base_known != null ? m.body_count - m.base_known : 0;
  if (unrep > 0) bits.push(m.base_known === 0 ? "None of them on Spansh." : `${unrep} of them not on Spansh.`);
  if (m.star_class) { const sc = /^[OBAFGKM](_|$)/.test(m.star_class), st = spokenStar(m.star_class);
    bits.push(sc ? `Scoopable ${st}.` : st[0].toUpperCase() + st.slice(1) + "."); }
  const w = (m.worth || []).filter(x => x.notable || x.terraformable || (x.value != null && x.value >= hlLevel("body")))
    .sort((a, b) => (b.value || 0) - (a.value || 0))[0];
  if (w) bits.push(`The ${spokenClass(w.subtype, w.terraformable)} at ${w.body} is unmapped${w.value ? `, ${credits(w.value)}` : ""}.`);
  if (m.bio && m.bio.value >= bioMinNow()) bits.push(`Biology on ${m.bio.body}, up to ${credits(m.bio.value)}.`);
  if (!w && !(m.bio && m.bio.value >= bioMinNow()) && m.status === "explored") bits.push("Nothing here for you.");
  return bits.filter(Boolean).join(" ");
}
// the session recap at quit: "" under three jumps (a quick relog is not a session); zero counts are left out
function recapText(st) {
  if (!st || (st.jumps || 0) < 3) return "";
  const n = (k, one, many) => st[k] ? `${st[k].toLocaleString("en-US")} ${st[k] === 1 ? one : many}` : null;
  return andList([`${st.jumps.toLocaleString("en-US")} jumps`, st.ly ? `${Math.round(st.ly).toLocaleString("en-US")} light-years` : null,
    n("firsts", "system nobody had seen", "systems nobody had seen"), n("mapped", "body mapped", "bodies mapped"),
    n("samples", "species sampled", "species sampled"), n("codex_new", "new codex entry", "new codex entries")].filter(Boolean));
}
// the FSD-charging line's hazard: "Neutron star ahead: throttle down on arrival." ("" for an ordinary star)
const sayHazard = () => !!(store.get("sayHazard", null) ?? true);
const hazardSaid = sc => { const h = hazardNote(sc); return h ? `${h[0].toUpperCase()}${h.slice(1).replace(/:/, " ahead:")}.` : ""; };
// "system|body" -> what the left-body warning named there ({genera, unidentified: the count it gave, null when it
// could not say}), once it reached you: the
// system's leaving alert leaves those out (not the rest of the body). Cleared when you arrive in that system.
const leftWarned = new Map();
// a bio_pending entry without what the left-body warning already said; null when nothing is left to say
function unwarned(sys, b) {
  const said = leftWarned.get(`${sys}|${b.body}`); if (!said) return b;
  const partial = Object.fromEntries(Object.entries(b.partial || {}).filter(([g]) => !said.genera.has(g)));
  const genera = b.genera === null ? null : (b.genera || []).filter(g => !said.genera.has(g));
  // before a DSS the signals left are only covered if the warning counted them (it does once you touched down)
  const rest = Object.keys(partial).length + (genera === null ? (b.signals && said.unidentified == null ? 1 : 0) : genera.filter(g => !(g in partial)).length);
  return rest ? {...b, partial, genera} : null;
}
// Before the DSS, fewer signals than possible genera: which it is cannot be told, so say so ("one of these,
// 1.0M to 19.0M") instead of naming the most valuable as the likely one.
// every genus known on a body: the DSS's, plus any you sampled without a DSS
const bioGenera = b => [...new Set([...(b.genera || []), ...(b.organics || []).map(o => o.genus)])];
const bioFactor = b => (b.value_parts && b.value_parts.bio_factor) || 1;   // x5 on a first footfall
// Bio figures carry the body's first-footfall factor everywhere they are shown (the server's are x1), so a row,
// its pop-up and the body panel never show x1 and x5 side by side
const optLabel = (n, opt, f = 1) => `${n === 1 ? "one" : n} of these, ${credits(opt.low * f)} to ${credits(opt.high * f)}`;
const bioRange = b => { const f = bioFactor(b);
  return b.bio_options ? ` · ${credits(b.bio_options.low * f)} to ${credits(b.bio_options.high * f)}` : b.bio_potential ? ` · up to ${credits(b.bio_potential * f)}` : ""; };
// Signals no genus accounts for yet (before the DSS, less any genus sampled without one): how many, and what they
// could be (the server's options already leave out the sampled genera). null when every signal is named.
function bioUnknown(b) {
  const known = bioGenera(b), n = (b.bio || 0) - known.length;
  if (n <= 0) return null;
  const opt = b.bio_options, list = opt ? opt.genera.filter(x => !known.includes(x.genus))
    : (b.bio_guess || []).filter(x => !known.includes(x.genus)).slice(0, n);
  const label = known.length ? `${n} more signal${n === 1 ? "" : "s"} not identified` : `${n} signal${n === 1 ? "" : "s"}, not DSS'd`;
  return {n, opt, list, label};
}
const bmMap = () => Object.fromEntries((data.bookmarks || []).map(b => [b.id, b]));
const day = ts => (ts || "").slice(0, 10);
function firstsIcon(f) {
  if (!f) return "";
  let h = "";
  if (f.system) {
    const why = {sold: `You discovered this system (sold ${day(f.system_ts)})`,
                 unsold: "You discovered this system: data not sold yet",
                 lost: `You discovered this system, but the data was lost when your ship was destroyed ${day(f.system_ts)}`}[f.system_state]
                || "You discovered this system";
    const extra = f.sale !== f.system_state && f.sale === "unsold" ? " · other data here still unsold" : "";
    h += `<span class="first ${f.system_state || ""}" title="${why}${extra}">🏁</span>`;
  }
  if (f.footfall) h += `<span class="first" title="First footfall on ${f.footfall} bod${f.footfall > 1 ? "ies" : "y"}">👣</span>`;
  return h;
}
function firstsHtml(f) {
  if (!f) return "";
  const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  // "3 sold · 1 unsold · 2 lost", omitting zero buckets
  const by = b => ["sold", "unsold", "lost"].filter(k => b && b[k]).map(k => `<span class="${k}">${b[k]} ${k}</span>`).join(" · ");
  const sysLabel = {sold: `<span class="sold">system tag sold ${day(f.system_ts)}</span>`,
                    unsold: `<span class="unsold">system tag not sold yet</span>`,
                    lost: `<span class="lost">system tag lost with the ship ${day(f.system_ts)}</span>`}[f.system_state];
  const items = [
    f.system && `First to discover the system · ${sysLabel}`,
    f.bodies && `${n(f.bodies, "body first discovered", "bodies first discovered")} · ${by(f.bodies_by)}`,
    f.mapped && `${n(f.mapped, "body first mapped", "bodies first mapped")} · ${by(f.mapped_by)}`,
    f.footfall && n(f.footfall, "first footfall", "first footfalls") + " (credited on landing)",
  ].filter(Boolean);
  const advice = {unsold: `<span class="unsold">sell at Universal Cartographics to claim what's unsold</span>`,
                  lost: `<span class="lost">lost data can be re-earned by scanning those bodies again</span>`,
                  sold: `<span class="sold">all sold: the tags should be yours</span>`}[f.sale];
  return `<div class="sec firsts"><div class="lbl">Your firsts</div><ul>` +
    items.map(i => `<li>🏁 <span>${i}</span></li>`).join("") + (advice ? `<li>${advice}</li>` : "") + `</ul></div>`;
}
function bmIcon(id, name, bms) {
  const b = bms[id];
  return `<span class="bm${b ? " on" : ""}" data-bm="${id}" data-name="${esc(name)}"` +
    ` title="${b ? "" : "bookmark this system"}">${b ? "★" : "☆"}</span>`;
}

// the unit is picked by what the value rounds to: 999,600 is "1.0M", not "1000k"
const credits = n => n >= 999.95e6 ? (n / 1e9).toFixed(2) + "B" : n >= 999.5e3 ? (n / 1e6).toFixed(1) + "M"
                    : n >= 999.5 ? Math.round(n / 1e3) + "k" : String(Math.round(n));
// Your own thresholds for the unsold-data warning; the server's defaults apply until you change them.
const unsoldCfg = Object.assign({warn: null, urgent: null}, store.get("unsoldCfg", {}));
function unsoldThresholds(u) {
  const [dw, du] = (u && u.thresholds) || [50000000, 250000000];
  return [unsoldCfg.warn ?? dw, unsoldCfg.urgent ?? du];
}
// What the station you are docked at buys of your unsold data (cartographics at Universal Cartographics,
// exobiology at Vista Genomics), and its level: a UC-only carrier is no place to sell 300M of bio.
function sellableHere(dk, u) {
  if (!dk || !(dk.has_uc || dk.has_vista) || !u || u.error || u.total == null) return null;
  const value = (dk.has_uc ? (u.carto || {}).estimated_payout || 0 : 0) + (dk.has_vista ? (u.bio || {}).estimated_value || 0 : 0);
  return {value, level: unsoldLevel({...u, total: value})};
}
const leftToSell = u => [(u.carto || {}).estimated_payout && `${credits(u.carto.estimated_payout)} cr cartographics (Universal Cartographics)`,
                         (u.bio || {}).estimated_value && `${credits(u.bio.estimated_value)} cr exobiology (Vista Genomics)`].filter(Boolean).join(", ");
function unsoldLevel(u) {
  if (!u || u.error || u.total == null) return null;
  const [w, g] = unsoldThresholds(u);
  const rebuy = data && data.ship && data.ship.rebuy, rw = unsoldCfg.rebuyWarn, ru = unsoldCfg.rebuyUrgent;
  const x = rebuy ? u.total / rebuy : 0;
  return u.total >= g || (ru && x >= ru) ? "urgent" : u.total >= w || (rw && x >= rw) ? "warn" : "ok";
}
function renderUnsold() {
  const el = document.getElementById("unsold"), u = data.unsold, tile = document.getElementById("tUnsold"), fl = document.getElementById("firstsLine");
  tile.className = "tile " + (unsoldLevel(u) || "");
  if (!u) { el.innerHTML = `<div class="val"><span class="unk">estimating…</span></div>`; fl.innerHTML = ""; return; }
  if (u.error) { el.innerHTML = `<div class="val"><span class="unk">unavailable</span></div>`; fl.innerHTML = esc(u.error).slice(0, 80); return; }
  const f = u.firsts;
  const rebuy = data.ship && data.ship.rebuy, ss = data.since_sale;
  el.innerHTML = `<div class="val">${credits(u.total)} cr${rebuy ? ` <span class="unk" title="what the data on board is worth, in rebuys of your ship (${credits(rebuy)} cr)">= ${(u.total / rebuy).toFixed(u.total / rebuy < 10 ? 1 : 0)}× rebuy</span>` : ""}</div>` +
    `<div class="ln">🗺 <b>${credits(u.carto.estimated_payout ?? u.carto.estimated_value)}</b> · 🧬 <b>${credits(u.bio.estimated_value)}</b></div>` +
    (ss ? `<div class="ln" title="since your last sale to Universal Cartographics (${esc(ss.ts.slice(0, 10))})"><b>${ss.days}</b> d · <b>${Math.round(ss.ly).toLocaleString()}</b> ly since you last sold</div>` : "") +
    sellersLine();
  fl.innerHTML = !f || !(f.systems || f.planets || f.mapped) ? "no unsold firsts" :
    `🏁 <b>${f.systems}</b> system${f.systems === 1 ? "" : "s"} · <b>${f.planets}</b> planet${f.planets === 1 ? "" : "s"} · <b>${f.mapped}</b> mapped unsold`;
}
// The nearest places to sell (Spansh station search): the nearest trustworthy one of each kind.
const sellerTxt = x => !x ? "" : `${esc(x.name)}${x.yours ? " (your carrier)" : x.carrier ? " (carrier)" : ""} · ${esc(x.system)} · ${x.distance.toLocaleString("en-US", {maximumFractionDigits: 0})} ly` +
  (effRange() ? ` ≈ ${jumpsFor(x.distance)} jump${jumpsFor(x.distance) > 1 ? "s" : ""}` : "") +
  (x.carrier && !x.yours && x.age_days != null ? ` <span class="unk">(seen ${x.age_days < 1 ? "today" : Math.round(x.age_days) + " d ago"})</span>` : "");
function sellersLine() {
  const s = data.sellers; if (!s || !s.uc) return "";
  const uc = s.uc.fresh || s.uc.nearest, vi = s.vista.fresh || s.vista.nearest;
  const d = x => x ? `${x.distance.toLocaleString("en-US", {maximumFractionDigits: 0})} ly` : "?";
  return `<div class="ln" title="nearest Universal Cartographics: ${uc ? sellerTxt(uc).replace(/<[^>]+>/g, "") : "none known"}\nnearest Vista Genomics: ${vi ? sellerTxt(vi).replace(/<[^>]+>/g, "") : "none known"}">sell: UC <b>${d(uc)}</b> · Vista <b>${d(vi)}</b>${uc && uc.yours ? " <span class=\"unk\">(your carrier)</span>" : ""}</div>`;
}
function unsoldHtml(u) {
  if (!u || u.error) return "";
  const c = u.carto, b = u.bio, cr = n => Math.round(n).toLocaleString("en-US") + " cr";
  const from = x => x.cutoff && x.last_sold && x.cutoff > x.last_sold
    ? `since your ship was lost ${day(x.cutoff)}` : x.last_sold ? `since you last sold ${day(x.last_sold)}` : "all on record";
  const cx = data.carrier, where = cx && cx.has_uc ? (cx.here ? ` Your carrier (with UC) is right here.` :
    cx.distance != null ? ` Your carrier has UC and is ${cx.distance.toLocaleString("en-US", {maximumFractionDigits: 0})} ly away at ${esc(cx.system)}.` : "") : "";
  const [tw, tu] = unsoldThresholds(u), lvl = unsoldLevel(u);
  const advice = ({urgent: `Go sell: over ${credits(tu)} cr would be lost with the ship.`,
                  warn: `Worth selling soon: over ${credits(tw)} cr at risk.`,
                  ok: `Nothing urgent: under your ${credits(tw)} cr threshold.`}[lvl]) + where;
  return `<h3>Unsold data (estimate)</h3>` +
    `<div class="sec"><div class="lbl">🗺 Cartographics · ${from(c)}</div><ul>` +
    `<li><span>${c.bodies.toLocaleString()} bodies in ${c.systems.toLocaleString()} systems</span><b>${cr(c.estimated_payout ?? c.estimated_value)}</b></li>` +
    (c.payout_note ? `<li><span class="bn">${esc(c.payout_note)}${c.payout_ratio && c.payout_ratio < 0.999 ? ` (${cr(c.estimated_value)} before the cut)` : ""}</span></li>` : "") +
    `<li><span>${c.first_discoveries.toLocaleString()} first discoveries · ${c.mapped.toLocaleString()} mapped</span></li>` +
    (u.firsts ? `<li><span class="bn">🏁 ${u.firsts.systems} systems (arrival star) · ${u.firsts.stars} stars · ` +
                `${u.firsts.planets} planets first discovered · ${u.firsts.mapped} first mapped</span></li>` : "") +
    `</ul></div>` +
    `<div class="sec"><div class="lbl">🧬 Exobiology · ${from(b)}</div><ul>` +
    `<li><span>${b.samples} sample${b.samples === 1 ? "" : "s"}</span><b>${cr(b.estimated_value)}</b></li>` +
    (b.samples ? `<li><span class="bn">range ${cr(b.base_value)} – ${cr(b.max_value)}; first-log bonus assumed on ` +
                 `${Math.round(b.bonus_rate * 100)}%</span></li>` : "") +
    u.species.map(r => `<li><span class="bn">${esc(r.species)} ×${r.count}</span><b>${cr(r.value)}</b></li>`).join("") +
    (b.unknown_species.length ? `<li><span class="bn">not priced: ${b.unknown_species.map(esc).join(", ")}</span></li>` : "") +
    `</ul></div>` +
    ((u.top_bodies || []).length ? `<div class="sec"><div class="lbl">Most valuable aboard</div><ul>` +
      u.top_bodies.map(t => `<li><span class="bn">${esc(t.body)} · ${esc(t.type)}${t.first_discovered ? " 🏁" : ""}${t.mapped ? " 🗺" : ""}</span><b>${cr(t.value)}</b></li>`).join("") + `</ul></div>` : "") +
    (data.sellers && data.sellers.uc ? `<div class="sec"><div class="lbl">Nearest places to sell</div><ul>` +
      [["Universal Cartographics", data.sellers.uc], ["Vista Genomics", data.sellers.vista]].map(([k, g]) =>
        `<li><span class="bn">${k}: ${sellerTxt(g.fresh || g.nearest) || "none known"}</span></li>` +
        (g.station && g.station !== (g.fresh || g.nearest) ? `<li><span class="bn">&nbsp;&nbsp;nearest station: ${sellerTxt(g.station)}</span></li>` : "")).join("") +
      `</ul></div>` : "") +
    `<div class="adv ${lvl}">${advice}</div>` +
    `<div class="sec unk">first-discovery and mapping bonuses included · belts and rings not counted · updated ${u.computed}</div>`;
}

function render() {
  if (!data) return;
  const bms = bmMap();
  renderUnsold();
  const p = data.position;
  const here = p && data.systems.find(s => s.id64 === p.id64), known = !!here;
  // distances to the two hubs: Sol, and Colonia (Eol Prou RS-T d3-94)
  const lyTo = (x, y, z) => p && Math.hypot(p.x - x, p.y - y, p.z - z).toLocaleString("en-US", {maximumFractionDigits: 0});
  const rg = data.region;
  document.getElementById("refLn").innerHTML = p ? (rg && rg.name ? `<span title="galactic region (codex entries are per region)${rg.nebula ? "; inside a nebula zone" : ""}">${esc(rg.name)}${rg.nebula ? " · nebula" : ""}</span> · ` : "") +
    `Sol <b>${lyTo(0, 0, 0)}</b> ly · Colonia <b>${lyTo(-9530.5, -910.28125, 19808.125)}</b> ly` : "";
  const fkHere = focusKey("here");
  document.getElementById("here").innerHTML = !p ? "waiting for your first jump…" :
    `<span class="copy" data-name="${esc(p.name)}" title="click to copy"` +
    (known ? ` data-pop data-id="${esc(here.id)}"` : "") + `>${esc(p.name)}</span>` + (here ? firstsIcon(here.firsts) : "") +
    (here ? bmIcon(here.id, here.name, bms) : "");
  refocus("here", fkHere);
  placeOverview();
  document.getElementById("nearWrap").hidden = !(view === "near" || view === "overview");
  document.getElementById("overView").hidden = view !== "overview";
  document.getElementById("bmTable").hidden = view !== "bm";
  document.getElementById("bmTools").hidden = view !== "bm";
  const nearPinned = view === "near" && !!pinnedSystem;
  document.getElementById("hereView").hidden = !(view === "here" || nearPinned || (view === "overview" && !ovState.collapsed));
  document.querySelector("main").classList.toggle("nearPinned", nearPinned);
  document.getElementById("firstsView").hidden = view !== "firsts";
  if (view === "firsts") { loadFirsts(); loadLeft(); }
  document.documentElement.style.setProperty("--head-h", document.querySelector("header").offsetHeight + "px");
  document.getElementById("hereView").classList.toggle("detail", !!selectedBody);
  document.getElementById("histView").hidden = view !== "hist";
  document.getElementById("matView").hidden = view !== "mat";
  if (view === "mat") loadMat();
  document.getElementById("logView").hidden = view !== "log";
  if (view === "log") { if (L.key === null) loadLog(); else tailLog(); }
  document.getElementById("bioView").hidden = view !== "bio";
  if (view === "bio") loadBio();
  if (view === "here" || nearPinned || (view === "overview" && !ovState.collapsed) || view === "now") {   // Now reads Here's data
    loadHere();
    if (hereData && lastHereCtx !== hereCtx()) renderHere();   // tab and pane keep different modes
  }
  if (view === "hist") { renderLastSession(); loadHistory(); }
  renderStrip();
  loadOnBody();
  document.getElementById("searchView").hidden = view !== "search";
  document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  document.getElementById("bmViewBtn").textContent = `Bookmarks${(data.bookmarks || []).length ? ` (${data.bookmarks.length})` : ""}`;
  document.getElementById("sFrom").textContent = p ? p.name : "—";
  renderBookmarks(bms);
  renderSearch(bms);
  document.getElementById("mapView").hidden = view !== "map";
  document.body.classList.toggle("nowmode", view === "now");
  document.getElementById("nowView").hidden = view !== "now";
  if (view === "now") renderNow();
  if (view === "map") { loadMap(); drawMap(); }
  refreshPop();
  const jr = effRange();
  let rows = data.systems.filter(s => s.id64 !== (p && p.id64))
    .filter(s => showVisited.checked || !s.visited)
    .filter(s => showExplored.checked || s.status !== "explored")
    .filter(s => !oneJump.checked || !jr || s.distance <= jr);
  rows.sort(sortKeys.near === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
    : sortKeys.near === "value" ? (a, b) => (b.value_max || 0) - (a.value_max || 0) || a.distance - b.distance
    : (a, b) => a.distance - b.distance);
  // Fuel: the nearest scoopable star you can reach (visited or not) gets a tag when the tank is low.
  const fuel = data.fuel, lowFuel = fuel && fuel.live && fuel.pct != null && fuel.pct < 30;
  const scoopNext = lowFuel && data.systems.filter(s => s.id64 !== (p && p.id64) && s.main_scoopable && (!jr || s.distance <= jr))
    .sort((a, b) => a.distance - b.distance)[0];
  const prev = data.previous;
  const unvisited = data.systems.filter(s => !s.visited).length;
  document.getElementById("subKnown").textContent = data.systems.length;
  document.getElementById("subUnvisited").textContent = unvisited;
  document.getElementById("subCut").innerHTML = data.sphere_cut != null
    ? ` · <span class="warn" title="Spansh knows more systems in range than Outrider fetches; the list is complete only out to ${data.sphere_cut} ly. A smaller radius shows them all.">complete to ${data.sphere_cut} ly</span>` : "";
  const rs = document.getElementById("radiusSel"), choices = data.radius_choices || [data.radius];
  if (rs.dataset.opts !== choices.join(",")) {   // rebuilt only when the choices change, so an open list stays open
    rs.innerHTML = choices.map(r => `<option value="${r}">${r}</option>`).join(""); rs.dataset.opts = choices.join(",");
    rs.title = `how far around you Nearby lists systems (radius_choices in ed_outrider.toml sets these; bigger spheres take longer to fill in)`;
  }
  if (document.activeElement !== rs && !rs.dataset.pending) rs.value = String(data.radius);
  document.getElementById("subJump").innerHTML = (jr ? `<span title="Loadout MaxJumpRange: the best case with a near-empty tank">max jump ${(data.jump_range || jr).toFixed(1)} ly</span>` +
    (data.boost ? ` <b class="boosted" title="jet-cone charge: your next jump reaches this far">boosted ×${data.boost} → ${jr.toFixed(0)} ly</b>` : "") : "") +
    (prev && p ? `${jr ? " · " : ""}came from ${esc(prev.name)} (${Math.hypot(prev.x - p.x, prev.y - p.y, prev.z - p.z).toFixed(1)} ly)` : "");
  document.body.classList.toggle("disconnected", !!disconnected);
  document.querySelectorAll("table th[data-sort]").forEach(b =>
    b.classList.toggle("on", b.dataset.sort === sortKeys[SORT_TABLES[b.closest("table").id]]));
  const t = data.target, tEl = document.getElementById("target");
  if (!t) tEl.innerHTML = "";
  else {
    const label = {"unreported": "never reported — new discovery!", "no bodies": "no scan data",
      "partial": "partly scanned", "explored": "fully scanned", "visited": "you've been here",
      "lookup failed": "Spansh lookup failed"}[t.status] || t.status;
    const row = data.systems.find(s => s.id64 === t.id64);
    const sc = t.star_class ? ` · <span class="mono">${esc(t.star_class)}</span>` +
      (/^[OBAFGKM](_|$)/.test(t.star_class) ? ` <span class="scoop" title="scoopable">⛽</span>`
                                           : ` <span class="noscoop" title="not scoopable">✕</span>`) : "";
    const src = t.source === "edsm" ? " (known to EDSM only)" : "";
    const hz = hazardNote(t.star_class);
    tEl.innerHTML = `Target: <b>${esc(t.name)}</b>${row ? ` · ${row.distance.toFixed(2)} ly` : ""}${sc}` +
      ` · <span class="t-${t.status.replace(" ", "")}">${label}${src}</span>` + (hz ? ` · <span class="hazard">⚠ ${hz}</span>` : "");
  }
  renderLeaving(t && t.leaving);
  renderRoute();
  const a = data.arrival, aEl = document.getElementById("arrival");
  aEl.innerHTML = !a || !p || a.id64 !== posId() ? "" :
    `Arrived at <b>${esc(a.name)}</b>: ` + (a.undiscovered
      ? `<span class="yes">arrival star undiscovered — first discovery is yours to sell</span>`
      : `<span class="no">already discovered by someone` + (a.announced === "unreported" ? " — Spansh just hadn't heard of it" : "") + `</span>`);
  const fkRows = focusKey("rows");
  document.getElementById("rows").innerHTML = rows.map(s => {
    const isPrev = prev && s.id64 === prev.id64;
    const far = jr && s.distance > jr;
    const jumps = jr ? jumpsFor(s.distance) : null;
    const cls = [s.visited && "visited", far && "far", isPrev && "prev", scoopNext && s.id64 === scoopNext.id64 && "scoopnext",
                 data.next_stop && s.id === data.next_stop.id && "nextstop",
                 pinnedSystem === s.id && "pinned",
                 data.target && s.id64 === data.target.id64 && "target"]
      .filter(Boolean).join(" ");
    const known = s.body_count ? `${s.bodies_known}/${s.body_count}` : (s.bodies_known || "");
    return `<tr class="${cls}">
      <td class="bmcell">${bmIcon(s.id, s.name, bms)}</td>
      <td class="name" data-name="${esc(s.name)}" title="click to copy">${isPrev
        ? `<span class="prevmark" title="you just came from here">↩</span>` : ""}${esc(s.name)}${firstsIcon(s.firsts)}</td>
      <td class="num dist"${far ? ` title="beyond your max jump range"` : ""}>${s.distance.toFixed(2)}</td>
      <td class="num hide-sm">${jumps == null ? "" : jumps === 1 ? "1" : `<span class="unk">${jumps}</span>`}</td>
      <td>${statusPill(s)}${s.mapped ? `<span class="badge s-mapped" title="DSS-mapped bodies, from your own journal">${s.mapped} mapped</span>` : ""}${s.source === "own"
        ? `<span class="badge s-own" title="Spansh doesn't have this system; data is from your own scans">yours only</span>` : ""}${s.source === "edsm"
        ? `<span class="badge s-edsm" title="Spansh is unreachable; this comes from EDSM (no body data)">EDSM</span>` : ""}</td>
      <td>${star(s)}</td><td class="bodies" data-pop data-id="${esc(s.id)}">${bodies(s)}</td>
      <td class="notable">${notable(s)}</td><td class="num hide-sm" title="${valueTitle(s)}">${valueCell(s)}</td><td class="num hide-sm">${known}</td></tr>`;
  }).join("") || `<tr><td colspan="10" class="unk">${emptyMessage(rows)}</td></tr>`;
  refocus("rows", fkRows);
}
function emptyMessage(rows) {
  const others = data.systems.filter(s => s.id64 !== (data.position && data.position.id64)).length;
  if (/^asking|^fetching/.test(data.status)) return "loading…";
  if (/failed/.test(data.status)) return "Spansh lookup failed — the list is incomplete, so no conclusions about undiscovered systems yet.";
  if (others > rows.length) return `${others - rows.length} system${others - rows.length === 1 ? "" : "s"} hidden by the filters above.`;
  return "Nothing known nearby — everything here is undiscovered.";
}

function renderBookmarks(bms) {
  const list = Object.values(bms);
  list.sort(sortKeys.bm === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
    : (a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9));
  const fk = focusKey("bmRows");
  document.getElementById("bmRows").innerHTML = list.map(b => `<tr>
      <td class="bmcell">${bmIcon(b.id, b.name, bms)}</td>
      <td class="name" data-name="${esc(b.name)}" title="click to copy">${esc(b.name)}</td>
      <td class="num dist">${b.distance == null ? "?" : b.distance.toLocaleString("en-US", {maximumFractionDigits: 2})}</td>
      <td class="note">${esc(b.note) || `<span class="unk">no note</span>`}</td>
      <td class="hide-sm unk">${esc((b.created || "").slice(0, 10))}</td></tr>`).join("") ||
    `<tr><td colspan="5" class="unk">No bookmarks yet. Click ☆ beside any system to add one.</td></tr>`;
  refocus("bmRows", fk);
}

// ---- Bookmark dialog ----
const bmDialog = document.getElementById("bmDialog"), bmNote = document.getElementById("bmNote");
let bmTarget = null;
function openBookmark(id, name) {
  hidePop();
  const existing = bmMap()[id];
  bmTarget = id;
  document.getElementById("bmName").textContent = name;
  document.getElementById("bmRemove").hidden = !existing;
  bmNote.value = existing ? existing.note : "";
  bmDialog.returnValue = "";
  bmDialog.showModal();
  bmNote.focus();
}
bmNote.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); bmDialog.close("save"); }
});
bmDialog.addEventListener("close", async () => {
  const action = bmDialog.returnValue, id = bmTarget;
  bmTarget = null;
  if (id && action === "next") {   // the dialog's "Set as next stop"
    let r;
    try { r = await apiJson("api/nextstop", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id})}); }
    catch (err) { r = {error: err.message}; }   // the server is not answering
    toast(r.error ? `could not set the next stop: ${r.error}` : "next stop set");
    return;
  }
  if (!id || (action !== "save" && action !== "remove")) return;
  try {
    const r = await fetch("api/bookmark", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(action === "remove" ? {id, remove: true} : {id, note: bmNote.value.trim()})});
    if (!r.ok) throw new Error((await r.json()).error || r.status);
    toast(action === "remove" ? "bookmark removed" : "bookmarked");
    version = -1;  // fetch fresh data right away
    poll(true);
  } catch (err) { toast("bookmark failed: " + err.message); }
});
document.querySelectorAll("[data-view]").forEach(b => b.onclick = () => {
  if (b.dataset.view !== view && pinnedSystem) { pinnedSystem = null; if (selectedBody) closeBody(); }  // a pin belongs to the view it was made in
  if (b.dataset.view === "now" && view !== "now") viewBeforeNow = view;
  if (b.dataset.view === "hist" && view !== "hist") histKey = null;   // fresh numbers each time the tab opens
  view = b.dataset.view; store.set("view", view); render();
});

// ---- Here: every body in the current system ----
let hereKey = null, hereData = null;
// The system panel normally shows where you are; clicking a nearby row's Bodies cell pins
// another system into it until the ✕ is clicked.
let pinnedSystem = null;
const shownSystem = () => pinnedSystem || posId();
function pinSystem(id) {
  // the system you are in is not "pinned": Here shows it anyway, with its to-do line
  pinnedSystem = posId() === String(id) ? null : String(id);
  if (view === "overview" && ovState.collapsed) { ovState.collapsed = false; saveOv(); }   // else the pin shows nothing
  if (selectedBody) closeBody(); hidePop(); render(); renderHere();
}
function unpinSystem() { pinnedSystem = null; if (selectedBody) closeBody(); render(); renderHere(); }
let hereRefreshError = null;
async function loadHere() {
  const id = shownSystem(); if (!id) return;
  // Only your own scans change this view, except while Spansh's body details are still arriving
  // ("partial"): then ask again every few seconds until they have.
  const partial = hereData && hereData.partial && hereData.id64 === id ? `|p${Math.floor(Date.now() / 4000)}` : "";
  const key = `${id}|${data.scan_version}${partial}`;
  if (key === hereKey) return;
  hereKey = key;
  let fresh;
  try { fresh = await apiJson(`api/system/${id}`); } catch (err) { fresh = {error: err.message}; }
  if (key !== hereKey) return;   // a newer request is already on its way
  if (fresh.error) hereKey = null;   // a failed fetch is retried at the next render, not kept
  // a failed refresh of the system already shown keeps the last good view (and the open body panel): the error
  // goes in the heading only
  if (fresh.error && hereData && !hereData.error && hereData.id64 === id) { hereRefreshError = fresh.error; renderHere(); return; }
  hereRefreshError = null;
  hereData = fresh;
  renderHere();
  // the open body panel belongs to a system: close it on a jump, refresh it after a scan
  if (selectedBody) {
    if (!fresh.error && fresh.id64 !== selectedSystem) closeBody();
    else if (!fresh.error && fresh.bodies.some(b => b.name === selectedBody)) reloadBody();
  }
}
// ---- Overview: the Here section and the Nearby table shown together ----
// Defaults: side by side, nearby on the left and this system on the right at 40%.
const ovState = Object.assign({layout: "side", collapsed: false, flip: false, split: 40}, store.get("overview", {}));
const ovHome = {here: null, near: null};   // where the sections live when not in the overview
function placeOverview() {
  const ov = document.getElementById("overView"), here = document.getElementById("hereView"), near = document.getElementById("nearWrap");
  const paneHere = document.getElementById("ovHere"), paneNear = document.getElementById("ovNear");
  if (!ovHome.here) { ovHome.here = here.nextSibling; ovHome.near = near.nextSibling; }
  if (view === "overview") {
    if (here.parentNode !== paneHere) paneHere.appendChild(here);
    if (near.parentNode !== paneNear) paneNear.appendChild(near);
  } else {
    const main = document.querySelector("main");
    if (here.parentNode === paneHere) main.insertBefore(here, ovHome.here);
    if (near.parentNode === paneNear) main.insertBefore(near, ovHome.near);
  }
  ov.className = `${ovState.layout}${ovState.collapsed ? " collapsed" : ""}${ovState.flip ? " flip" : ""}`;
  ov.style.setProperty("--ovw", ovState.split + "%");
  paneHere.classList.toggle("compact", ovState.layout === "side");
  paneHere.classList.toggle("hasDetail", !!selectedBody);
  here.classList.toggle("detail", !!selectedBody);
  document.getElementById("ovCollapse").textContent = (ovState.collapsed ? "▸ " : "▾ ") + "This system";
  const r = document.querySelector(`input[name=ovLayout][value="${ovState.layout}"]`); if (r) r.checked = true;
}
const saveOv = () => store.set("overview", ovState);
document.getElementById("ovCollapse").onclick = () => { ovState.collapsed = !ovState.collapsed; saveOv(); render(); };
document.getElementById("ovFlip").onclick = () => { ovState.flip = !ovState.flip; saveOv(); render(); };
document.querySelectorAll("input[name=ovLayout]").forEach(r => r.onchange = () => { ovState.layout = r.value; saveOv(); render(); });
// Drag the divider: the system pane's share of the width, 20-70 %.
const ovDivider = document.getElementById("ovDivider");
ovDivider.addEventListener("pointerdown", e => {
  if (e.button && e.button !== 0) return;
  e.preventDefault(); ovDivider.setPointerCapture(e.pointerId); ovDivider.classList.add("drag"); document.body.classList.add("ovdrag");
  const ov = document.getElementById("overView");
  const move = ev => {
    const r = ov.getBoundingClientRect();
    const fromRight = (r.right - ev.clientX) / r.width * 100, fromLeft = (ev.clientX - r.left) / r.width * 100;
    ovState.split = Math.round(Math.max(20, Math.min(70, ovState.flip ? fromLeft : fromRight)));
    ov.style.setProperty("--ovw", ovState.split + "%");
  };
  const up = () => { for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) ovDivider.removeEventListener(ev, up);
    ovDivider.removeEventListener("pointermove", move);
    ovDivider.classList.remove("drag"); document.body.classList.remove("ovdrag"); saveOv(); };
  ovDivider.addEventListener("pointermove", move);
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) ovDivider.addEventListener(ev, up);
});

function bodyValueTitle(b) {
  const v = b.value_parts; if (!v) return "";
  const part = (c, b, note) => [c ? `${credits(c)} cartographics${note || ""}` : "", b ? `${credits(b)} exobiology` : ""].filter(Boolean).join(" + ") || "nothing";
  const scan = v.scan_state && v.scan_state !== "unsold" ? ` (scan ${v.scan_state})` : "";
  return (maxBonus() ? "" : `Max without bonuses: ${credits(b.value_max_base || 0)} (with them: ${credits(b.value_max || 0)})\n\n`) +
    `On board: ${part(v.carto_now, v.bio_now, scan)}\nStill available: ${part(v.carto_left, v.bio_left)}\n\nExobiology here counts ×${v.bio_factor}${v.bio_factor === 5 ? " (nobody had set foot here when you scanned)" : " (someone had already landed here, or you have not scanned it)"}.`;
}
function renderHere() {
  const h = hereData, head = document.getElementById("hereHead"), lv = document.getElementById("hereLeaving");
  if (!h) { head.textContent = "loading…"; return; }
  if (h.error) {
    head.textContent = h.error; lv.innerHTML = "";
    document.getElementById("hereRows").innerHTML = `<tr><td colspan="10" class="unk">${esc(h.error)}</td></tr>`;
    if (selectedBody) closeBody();
    return;
  }
  const pinned = !!pinnedSystem, row = pinned && data.systems.find(s => s.id === pinnedSystem);
  // a system opened by name from Search may be far outside the sphere: its distance is the lookup's
  const away = row ? row.distance : pinned && foundSys[pinnedSystem] ? foundSys[pinnedSystem].distance : null;
  head.innerHTML = (pinned ? `<button type="button" class="unpin" onclick="unpinSystem()" title="back to the system you are in">✕</button><span class="pintag">viewing</span> ` : "") +
    // the bookmark star (its dialog also sets the next stop) for a viewed system, which may be in no other list
    (pinned ? bmIcon(pinnedSystem, h.name, bmMap()) + " " : "") +
    `<b>${esc(h.name)}</b>` + (away != null ? ` <span class="unk">· ${away.toFixed(2)} ly away</span>` : "") +
    ` · ${h.bodies.length} bod${h.bodies.length === 1 ? "y" : "ies"} known · ` + (h.phenomena && h.phenomena.length ? phenomenaTag(h.phenomena) + " · " : "") +
    `<span title="what selling now would pay for data you hold from here / the most this system could pay">now <b>${credits(h.value_now || 0)} cr</b> · max <b>${credits(maxOf(h) || 0)} cr</b>${maxBonus() ? "" : ` <span class="unk" title="Max leaves out first-discovery, first-mapped and first-footfall bonuses (alerts & thresholds dialog)">no bonus</span>`}</span>` +
    `<span class="modes">${HERE_MODES.filter(([m]) => m !== "split" || hereCtx() === "tab").map(([m, label, title]) =>
      `<button type="button" data-mode="${m}" title="${title}"${(m === "split" ? hereMode().split : hereMode().top === m) ? ' class="on"' : ""}>${label}</button>`).join("")}</span>` +
    (hereRefreshError && h.id64 === shownSystem() ? ` <span class="unk" title="${esc(hereRefreshError)}">· refresh failed</span>` : "");
  const l = h.leaving;
  const firstsBlock = h.firsts ? firstsHtml(h.firsts).replace(/<div class="lbl">Your firsts<\/div>/, "") : "";
  lv.innerHTML = firstsBlock + (pinned ? (!h.firsts ? `<span class="unk">${row ? esc(row.status) : ""}${row && row.visited ? " · you have been here" : ""}</span>` : "")
    : !l ? `<span class="unk">Nothing of yours scanned here yet.</span>` : checklistHtml(l));
  lastHereCtx = hereCtx();
  const hm = h.tree ? hereMode() : {top: "list", split: false};
  const showTable = hm.top !== "schematic", showSch = hm.top === "schematic" || hm.split;
  document.getElementById("hereTable").hidden = !showTable;
  document.getElementById("hereHint").hidden = !showTable;
  const sEl = document.getElementById("hereSchematic");
  sEl.hidden = !showSch; sEl.classList.toggle("split", showTable && showSch);
  if (showSch) sEl.innerHTML = schematicHtml(h);
  const dest = data.destination && posId() === h.id64 ? data.destination : null;
  const destBody = dest && h.bodies.find(b => b.body_id === dest.body_id);
  const rowHtml = (b, ind = "") => {
    const bio = [], f = bioFactor(b);
    const guessOf = g => (b.bio_guess || []).find(x => x.genus === g);
    const guessTxt = x => !x || !x.best ? "" : ` <span class="unk" title="likeliest by value: ${esc(x.species.join(" / "))}">(${esc(x.best.split(" ").slice(1).join(" "))}? ${credits(x.value * f)})</span>` + codexMark(x, h.region);
    for (const g of bioGenera(b)) {
      const o = b.organics.find(o => o.genus === g);
      bio.push(o ? `<span class="sp ${o.lost ? "lost" : o.done ? "done" : "part"}" title="${esc(o.species || "")}${o.variant ? " · " + esc(o.variant) : ""}${o.lost ? " · lost with the ship, sample again" : ""}">${esc(g)} ${o.lost ? "lost ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}${!o.lost && o.value ? ` <span class="unk">${credits(o.value * f)}</span>` : ""}</span>` +
                   // a run under way prices the species you logged (known from its first sample), like the pop-up and
                   // the panel; the predictor's guess is only for a lost run or one whose species has no price
                   (o.lost || (!o.done && !o.value) ? guessTxt(guessOf(g)) : "")
                 : `<span class="sp">${esc(g)} 0/3</span>` + guessTxt(guessOf(g)));
    }
    // signals no genus accounts for: before a DSS, and after a sample taken without one (that genus is listed above)
    const unk = bioUnknown(b);
    if (unk) {
      const {opt, list: gl} = unk;
      bio.push((bio.length ? "<br>" : "") + `<span class="unk">${unk.label}</span>` + (gl.length
        ? `<br><span class="unk">${opt ? `${optLabel(unk.n, opt, f)}: ` : "likely: "}</span>${gl.map(x => `<span class="sp" title="${esc(x.species.join(" / "))}">${esc(x.genus)} ≤${credits((x.value || 0) * f)}${codexMark(x, h.region)}</span>`).join(opt ? `<span class="unk"> or </span>` : "")}` : ""));
    }
    const codex = b.codex.map(c => `<span class="sp" title="codex">📖 ${esc(c.name)}${c.voucher ? " 💰" : c.new ? " ✦" : ""}</span>`).join("");
    const firsts = [b.first_discovered && `<span class="fl" title="first discovered">🏁</span>`, b.first_mapped && `<span class="fl" title="first mapped">🗺</span>`,
                    !b.first_mapped && b.mapped && `<span class="fl unk" title="mapped (not first)">🗺</span>`,
                    b.first_footfall && `<span class="fl" title="first footfall">👣</span>`, !b.scanned && `<span class="unk" title="known to Spansh, not scanned by you">—</span>`].filter(Boolean).join("");
    return `<tr class="${b.main ? "main" : ""}${selectedBody === b.name ? " sel" : ""}${destBody === b ? " dest" : ""}${hotClasses(b)}" data-body="${esc(b.name)}" data-bodypop="${esc(b.name)}"><td class="name" data-name="${esc(b.name)}">${ind}${esc(b.name)}${(b.curiosities || []).length ? ` <span class="cur" title="${b.curiosities.map(c => esc(c.tag + ": " + c.why)).join("&#10;")}">🔭</span>` : ""}${b.notable ? ` <span class="nb ${b.notable}">${b.notable}</span>` : ""}${b.terraformable ? ` <span class="nb T">T</span>` : ""}</td>
      <td>${esc(b.subtype || "")}${b.type === "Star" ? (b.scoopable ? ` <span class="scoop">⛽</span>` : "") : ""}</td>
      <td class="num">${b.dist_ls != null ? Math.round(b.dist_ls).toLocaleString() : ""}</td>
      <td class="num${b.gravity >= highGravity() ? " noscoop" : ""}">${b.gravity != null && b.type === "Planet" ? b.gravity.toFixed(2) : ""}</td>
      <td class="hide-sm">${b.type === "Planet" ? esc(b.atmosphere && b.atmosphere !== "None" ? b.atmosphere : (b.landable ? "none · landable" : "")) : ""}</td>
      <td class="bio">${bio.join(" ")}${geoTag(b)}${volcanoIcon(b)}${codex}</td>
      <td>${b.rings ? `${b.rings}${b.rings_mapped ? ` (${b.rings_mapped} mapped${b.hotspots < b.rings_mapped ? `, ${b.hotspots} with hotspots` : ""})` : ""}` : ""}</td>
      <td>${firsts}</td>
      <td class="num" title="${bodyValueTitle(b)}">${b.value_now ? credits(b.value_now) : ""}</td>
      <td class="num" title="${bodyValueTitle(b)}">${maxOf(b) ? credits(maxOf(b)) : ""}</td></tr>`;
  };
  document.getElementById("hereMaxTh").title = maxBonus()
    ? "the most it could pay once scanned, mapped and sampled, including first-discovery, first-mapped and first-footfall (×5 bio) bonuses where they apply"
    : "the most it could pay once scanned, mapped and sampled, with no bonuses: plain Universal Cartographics and Vista Genomics payouts";
  const byMax = maxBonus() ? h.bodies : [...h.bodies].sort((a, b) => (maxOf(b) || 0) - (maxOf(a) || 0));
  const fk = focusKey("hereRows");
  document.getElementById("hereRows").innerHTML = (hm.top === "text" ? treeRowsHtml(h, rowHtml) : byMax.map(b => rowHtml(b)).join(""))
    || `<tr><td colspan="10" class="unk">No bodies known here.</td></tr>`;
  refocus("hereRows", fk);
  // the body targeted in-game: a line saying what it is worth going to, and its row brought into view
  if (destBody) {
    const b = destBody;
    lv.insertAdjacentHTML("afterbegin", `<div class="destline">➜ Heading to <b>${esc(b.name)}</b> · ${destBits(b).map(esc).join(" · ")}</div>`);
    const dk = `${h.id64}|${b.body_id}`;
    if (dk !== lastDestKey) {
      lastDestKey = dk;
      const tr = document.querySelector("#hereRows tr.dest"); if (tr && tr.scrollIntoView) tr.scrollIntoView({block: "nearest"});
    }
  } else lastDestKey = null;
}
let lastDestKey = null;
// what the body targeted in-game is (plain text bits): Here's heading-to line and Now's
function destBits(b) {
  const f = bioFactor(b), bio = b.bio_options ? [`${b.bio_options.genera.map(x => x.genus).join(" or ")}, ${credits(b.bio_options.low * f)} to ${credits(b.bio_options.high * f)}`]
    : (b.bio_guess || []).slice(0, b.bio || b.genera.length).map(x => x.best ? `${x.best.split(" ")[0]}? ${credits((x.value || 0) * f)}` : x.genus);
  return [b.subtype, b.gravity != null && b.type === "Planet" && `${b.gravity.toFixed(2)} g`,
    b.atmosphere && b.atmosphere !== "None" && b.atmosphere, (b.bio || b.genera.length) && `${b.bio || b.genera.length} bio${bio.length ? ` (${bio.join(", ")})` : ""}`,
    b.geo && `${b.geo} geo`, b.dist_ls != null && `${Math.round(b.dist_ls).toLocaleString()} ls`, maxOf(b) && `max ${credits(maxOf(b))}`].filter(Boolean);
}
document.getElementById("hereRows").addEventListener("click", e => {
  const tr = e.target.closest("tr[data-body]"); if (!tr) return;
  tr.dataset.body === selectedBody ? closeBody() : openBody(tr.dataset.body);
});

// ---- Here as a schematic: stars, planets and moons in their hierarchy ----
// Modes are remembered separately for the Here tab (default: table above, schematic below) and for
// the Here pane in the Overview or beside Nearby (default: the table).
const HERE_MODES = [["list", "☰ list", "the body table, most valuable first"],
                    ["text", "≡ tree", "the body table in orbital order, moons indented under their planet"],
                    ["schematic", "◉ schematic", "the system drawn as stars, planets and moons"],
                    ["split", "⬒ split", "add the schematic below the list or tree"]];
// {top: list | text | schematic, split: schematic below the table (Here tab only)}
const hereModes = {tab: {top: "list", split: true}, pane: {top: "list", split: false}};
for (const [k, v] of Object.entries(store.get("hereModes", {})))   // older saves held a plain mode name
  if (hereModes[k]) hereModes[k] = typeof v === "string" ? {top: v === "split" ? "list" : v, split: v === "split"} : Object.assign(hereModes[k], v);
const hereCtx = () => view === "here" ? "tab" : "pane";
const hereMode = () => { const m = hereModes[hereCtx()]; return hereCtx() === "tab" ? m : {top: m.top, split: false}; };
function setHereMode(mode) {
  const m = hereModes[hereCtx()];
  if (mode === "split") { m.split = !m.split; if (m.split && m.top === "schematic") m.top = "list"; }
  else if (mode === "schematic") { m.top = "schematic"; m.split = false; }
  else m.top = mode;   // list or tree: swaps the top half, split stays as it was
  store.set("hereModes", hereModes);
}
let lastHereCtx = null;
// Tree mode: the same table rows in orbital order, each child indented under its parent. A barycentre
// (two or more bodies circling a shared centre of mass rather than each other) gets a row of its own.
function treeRowsHtml(h, rowHtml) {
  const by = Object.fromEntries(h.bodies.map(b => [b.name, b]));
  const out = [];
  const walk = (n, depth) => {
    const ind = depth ? `<span class="tind">${"→".repeat(depth)}</span>` : "";
    if (n.kind === "body" && by[n.name]) out.push(rowHtml(by[n.name], ind));
    else {
      // name everything circling this centre: bodies by name, a nested barycentre as "the B and C pair"
      const list = xs => xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}` : xs[0] || "";
      const named = c => c.kind === "body" ? esc(c.name)
        : c.kind === "barycentre" ? `the ${list(c.children.map(named))} ${c.children.length > 2 ? "group" : "pair"}`
        : esc(c.label);
      const members = n.children.map(named);
      const what = n.kind === "unknown" ? `${esc(n.label)} (not scanned by you)`
        : members.length > 1 ? `${list(members)} orbit a shared centre (barycentre)`
        : members.length ? `${members[0]} orbits a barycentre whose other members are not known yet`
        : `barycentre ${esc(n.label)}`;
      out.push(`<tr class="bary"><td colspan="10">${ind}<span class="unk">${n.kind === "unknown" ? "?" : "⊕"} ${what}</span></td></tr>`);
    }
    n.children.forEach(c => walk(c, depth + 1));
  };
  h.tree.forEach(n => walk(n, 0));
  return out.join("");
}
function starCode(sub) {
  sub = sub || "";
  if (/Neutron/i.test(sub)) return "N";
  if (/Black Hole/i.test(sub)) return "BH";
  if (/White Dwarf/i.test(sub)) return "D";
  if (/Wolf-Rayet/i.test(sub)) return "W";
  if (/T Tauri/i.test(sub)) return "TTS";
  if (/Herbig/i.test(sub)) return "AeBe";
  if (/^C[A-Z]*[- ]|Carbon/.test(sub)) return "C";
  if (/^(MS|S)-type/.test(sub)) return "S";
  return sub[0] || null;
}
const PLANET_COLOURS = [[/Earth-like/, "#4fbf6a"], [/^Water world/, "#3f8ee8"], [/Ammonia/, "#b377e0"], [/High metal/, "#a0826d"],
  [/Metal.rich/, "#8c3b30"], [/Rocky ice/i, "#c7ccd4"], [/^Rocky/, "#8f8f8f"], [/Icy/, "#dbe9f7"], [/Water giant/, "#5aa9e6"],
  [/water-based life/, "#6fb3a0"], [/ammonia-based life/, "#c79a5b"], [/Helium/, "#e8d7b0"], [/Class I gas/, "#d9b47a"],
  [/Class II gas/, "#e8e0c8"], [/Class III gas/, "#8fb0d9"], [/Class IV gas/, "#c98b5a"], [/Class V gas/, "#b0a0c8"], [/gas giant/i, "#c9a36b"]];
const planetColour = sub => (PLANET_COLOURS.find(([re]) => re.test(sub || "")) || [null, "#999"])[1];
function discSize(b, depth) {
  if (b.type === "Star") {
    const c = starCode(b.subtype);
    const px = ["N", "D", "BH"].includes(c) ? 22 : ["L", "T", "Y"].includes(c) ? 34 : 46;
    return b.main ? px + 6 : px;
  }
  const r = b.radius_km;
  const px = r == null ? 20 : r < 1500 ? 12 : r < 4000 ? 18 : r < 10000 ? 26 : r < 30000 ? 34 : 44;
  return depth > 1 ? Math.max(10, Math.round(px * .8)) : px;
}
function discHtml(b, depth) {
  const size = discSize(b, depth);
  const col = b.type === "Star" ? (STAR_COLOURS[starGroup(starCode(b.subtype))] || "#ccc") : planetColour(b.subtype);
  const cls = ["disc", b.scanned ? "" : "hollow", b.landable ? "landable" : "", selectedBody === b.name ? "sel" : ""].filter(Boolean).join(" ");
  const ring = b.rings ? `<svg class="ringmark" viewBox="0 0 16 16" style="width:${size + 14}px;height:${size + 14}px"><ellipse cx="8" cy="8" rx="7.6" ry="2.3" transform="rotate(-18 8 8)"/></svg>` : "";
  const badges = [b.first_discovered && "🏁", b.first_mapped ? "🗺" : b.mapped ? `<span class="unk">🗺</span>` : "",
    (b.bio || b.genera.length) && `🧬${b.bio || b.genera.length}`, b.geo && `🪨${b.geo}`, hasVolcanism(b) && `<span title="${esc(b.volcanism)}">🌋</span>`, b.first_footfall && "👣",
    b.terraformable && `<span class="nb T">T</span>`, b.notable && `<span class="nb ${b.notable}">${b.notable}</span>`,
    b.type === "Star" && b.scoopable && `<span class="scoop">⛽</span>`].filter(Boolean).join("");
  const belts = (b.belts || []).length ? `<span class="belt" title="${b.belts.length} belt${b.belts.length === 1 ? "" : "s"}">⋯</span>` : "";
  return `<div class="sbody${hotClasses(b)}" data-body="${esc(b.name)}" data-bodypop="${esc(b.name)}">` +
    `<div class="discwrap" style="width:${size + 14}px;height:${size + 14}px">${ring}<span class="${cls}" style="width:${size}px;height:${size}px;--c:${col}"></span></div>` +
    `<div class="sname" title="${esc(b.name)}">${esc(b.name)}${belts}</div><div class="badges">${badges}</div>` +
    `<div class="sval${maxOf(b) ? "" : " unk"}">${maxOf(b) ? credits(maxOf(b)) : "—"}</div>` +
    (b.type === "Planet" && b.dist_ls != null ? `<div class="sdist">${Math.round(b.dist_ls).toLocaleString()} ls</div>` : "") + `</div>`;
}
function schematicHtml(h) {
  const by = Object.fromEntries(h.bodies.map(b => [b.name, b]));
  const isStar = n => n.kind === "body" && by[n.name] && by[n.name].type === "Star";
  // a column: a body with its moons stacked beneath it, or a barycentre box with its members side by side
  const col = (n, depth) => {
    if (n.kind === "body" && by[n.name]) {
      const moons = n.children.map(c => col(c, depth + 1)).join("");
      return `<div class="scol">${discHtml(by[n.name], depth)}${moons ? `<div class="smoons">${moons}</div>` : ""}</div>`;
    }
    const inner = n.children.map(c => col(c, depth)).join("");
    return `<div class="scol sbary"><div class="sblabel" title="${n.kind === "unknown" ? "a body you have not scanned" : "barycentre: these orbit their common centre"}">${n.kind === "unknown" ? "?" : "⊕"} ${esc(n.label)}</div><div class="sgroup">${inner}</div></div>`;
  };
  // a row: a star and everything orbiting it, left to right in orbital order
  const starRow = n => {
    const b = by[n.name];
    // a pair of stars circling this one is drawn as its own nested group, not in the planet row
    const pairOfStars = c => c.kind === "barycentre" && c.children.some(isStar);
    const planets = n.children.filter(c => !isStar(c) && !pairOfStars(c)), stars = n.children.filter(isStar);
    const groups = n.children.filter(pairOfStars);
    return `<div class="srowS"><div class="sstar">${discHtml(b, 0)}</div><div class="splanets">${planets.map(c => col(c, 1)).join("") || `<span class="unk">no planets known</span>`}</div></div>` +
      (stars.length || groups.length ? `<div class="snest">${stars.map(starRow).join("")}${groups.map(top).join("")}</div>` : "");
  };
  const top = n => {
    if (isStar(n)) return starRow(n);
    if (n.kind === "barycentre" && n.children.some(isStar)) {
      const starGroupOf = c => c.kind === "barycentre" && c.children.some(isStar);   // a nested star pair: drawn as its own group
      const stars = n.children.filter(isStar), other = n.children.filter(c => !isStar(c) && !starGroupOf(c));
      return `<div class="sgroupTop"><div class="sblabel">⊕ ${esc(n.label)}</div>${stars.map(starRow).join("")}` +
        (other.length ? `<div class="srowS"><div class="sstar sround">around ${esc(n.label)}</div><div class="splanets">${other.map(c => col(c, 1)).join("")}</div></div>` : "") +
        n.children.filter(starGroupOf).map(top).join("") + `</div>`;
    }
    return `<div class="srowS"><div class="splanets">${col(n, 1)}</div></div>`;
  };
  return h.tree.map(top).join("") || `<div class="unk">No bodies known here.</div>`;
}
document.getElementById("hereHead").addEventListener("click", e => {
  const m = e.target.closest("[data-mode]"); if (!m) return;
  setHereMode(m.dataset.mode); renderHere();
});
document.getElementById("hereSchematic").addEventListener("click", e => {
  const b = e.target.closest("[data-body]"); if (!b) return;
  b.dataset.body === selectedBody ? closeBody() : openBody(b.dataset.body);
});

// ---- body hover summary ----
const fmtK = n => n == null ? "?" : Math.round(n).toLocaleString();
// region: the region of the system the body is in (a search result may be elsewhere than Here)
function bodyPopHtml(b, region) {
  const isStar = b.type === "Star";
  const phys = [
    b.dist_ls != null && `${fmtK(b.dist_ls)} ls from arrival`,
    !isStar && b.gravity != null && `${b.gravity.toFixed(2)} g`,
    b.temperature != null && `${fmtK(b.temperature)} K`,
    !isStar && b.atmosphere && b.atmosphere !== "None" && esc(b.atmosphere) + (b.pressure != null ? ` (${b.pressure < 0.01 ? b.pressure.toFixed(4) : b.pressure.toFixed(2)} atm)` : ""),
    !isStar && b.volcanism && esc(b.volcanism.replace(/ volcanism$/, "")),
    !isStar && (b.landable ? "landable" : "not landable"), b.terraformable && "terraformable",
    isStar && (b.scoopable ? "scoopable" : "not scoopable"),
  ].filter(Boolean);
  let h = `<h3>${esc(b.name)} <span class="src">${esc(b.subtype || "")}</span></h3><div>${phys.join(" · ")}</div>`;
  if ((b.ring_details || []).length)
    h += `<div class="sec"><div class="lbl">Rings</div><ul>` + b.ring_details.map(r =>
      `<li><span>${esc(r.name)} · ${esc(r.type || "?")}${r.density != null ? ` · ${r.density.toFixed(3)} Mt/km²` : ""}${r.width_km ? ` · ${fmtK(r.width_km)} km wide` : ""}</span>` +
      (r.hotspots && Object.keys(r.hotspots).length ? `<b>${Object.entries(r.hotspots).map(([k, v]) => `${esc(k)} ${v}`).join(", ")}</b>` : r.mapped ? `<b class="unk">mapped, no hotspots</b>` : `<b class="unk">not mapped</b>`) + `</li>`).join("") + `</ul></div>`;
  if (b.bio || (b.genera || []).length || (b.organics || []).length) {
    const lines = [];
    const f = bioFactor(b);
    for (const g of bioGenera(b)) {
      const o = (b.organics || []).find(o => o.genus === g), x = (b.bio_guess || []).find(x => x.genus === g);
      // a logged species pays its own price (a lost one again once resampled); the best guess only bounds the rest
      const price = o ? (o.value ? (o.lost ? `<span class="unk">${credits(o.value * f)}</span>` : credits(o.value * f)) : "")
                      : x && x.value ? "≤" + credits(x.value * f) : "";
      lines.push(`<li><span>${esc(g)}${o ? ` · ${esc(o.species || "")} ${o.lost ? "lost ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}` : x && x.best ? ` · likely ${esc(x.best.split(" ").slice(1).join(" "))}${variantTxt(x)}` : ""}</span><b>${price}</b></li>`);
    }
    const unk = bioUnknown(b);   // signals no genus above accounts for, and what they could be
    if (unk) {
      lines.push(`<li><span class="unk">${unk.label}${unk.opt ? `: ${optLabel(unk.n, unk.opt, f)}; the DSS tells which` : ""}</span></li>`);
      lines.push(...unk.list.map(x => `<li><span>${esc(x.genus)} possible (${esc(x.species.join("/"))})${codexMark(x, region)}</span><b>≤${credits((x.value || 0) * f)}</b></li>`));
    }
    h += `<div class="sec"><div class="lbl">🧬 Bio${b.bio ? ` · ${b.bio} signal${b.bio === 1 ? "" : "s"}` : ""}${bioRange(b)}</div><ul>${lines.join("")}</ul></div>`;
  }
  h += curiosityList(b.curiosities);
  if (b.geo) h += `<div class="sec">${b.geo} geological signal${b.geo === 1 ? "" : "s"}</div>`;
  const flags = [b.first_discovered && "🏁 first discovered", b.first_mapped && "🗺 first mapped", !b.first_mapped && b.mapped && "mapped", b.first_footfall && "👣 first footfall", !b.scanned && "not scanned by you"].filter(Boolean);
  h += `<div class="sec"><span>${maxOf(b) ? `now ${credits(b.value_now || 0)} · max ${credits(maxOf(b))}` : ""}</span>` +
       (flags.length ? `<div class="unk">${flags.join(" · ")}</div>` : "") + `</div><div class="sec unk">click for everything known</div>`;
  return h;
}

// ---- body detail panel ----
let selectedBody = null, selectedSystem = null, bodyData = null;
async function reloadBody() {
  const name = selectedBody, sys = selectedSystem;
  let fresh;
  try { fresh = await apiJson(`api/body?system=${sys}&name=${encodeURIComponent(name)}`); } catch (err) { fresh = {error: err.message}; }
  if (selectedBody !== name || selectedSystem !== sys) return;
  bodyData = fresh; renderBody();
}
async function openBody(name) {
  const id = hereData && !hereData.error ? hereData.id64 : shownSystem(); if (!id) return;
  selectedBody = name; selectedSystem = String(id); bodyData = null; hidePop();
  const panel = document.getElementById("bodyPanel");
  panel.hidden = false; panel.innerHTML = `<h3><b>${esc(name)}</b> <button type="button" onclick="closeBody()">✕</button></h3><div class="unk">loading…</div>`;
  render(); renderHere();
  await reloadBody();
}
function closeBody() { selectedBody = null; selectedSystem = null; bodyData = null; document.getElementById("bodyPanel").hidden = true; render(); renderHere(); }
const bodySecs = store.get("bodySecs", {});   // which detail sections you've collapsed
for (const id of ["bodyPanel", "sBodyPanel"]) document.getElementById(id).addEventListener("click", e => {
  const lbl = e.target.closest(".sec > .lbl"); if (!lbl) return;
  const sec = lbl.parentNode; sec.classList.toggle("closed");
  bodySecs[sec.dataset.sec] = sec.classList.contains("closed"); store.set("bodySecs", bodySecs);
});
function renderBody() { renderBodyInto(document.getElementById("bodyPanel"), bodyData, selectedBody, "closeBody()"); }
// The body detail panel, drawn into any container (Here's, or Search's); closeJs is the ✕ button's action.
function renderBodyInto(panel, d, bodyName, closeJs) {
  if (!d) return;
  const short = name => name && name.startsWith(d.full_name + " ") ? name.slice(d.full_name.length + 1) : name;
  if (d.error) { panel.innerHTML = `<h3><b>${esc(bodyName)}</b> <button type="button" onclick="${closeJs}">✕</button></h3><div class="unk">${esc(d.error)}</div>`; return; }
  const own = d.own || {}, sp = d.spansh || {}, row = d.row || {};
  const has = v => v !== undefined && v !== null && v !== "";
  const pick = (a, b) => has(a) ? a : has(b) ? b : null;
  const n = (v, dp = 2) => v == null ? null : Number(v).toLocaleString("en-US", {maximumFractionDigits: dp});
  const days = sec => sec == null ? null : `${n(Math.abs(sec) / 86400, 2)} d`;
  const isStar = !!own.StarType || sp.type === "Star";
  const kv = pairs => `<dl>${pairs.filter(([, v]) => has(v)).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  const sec = (key, title, body) => body ? `<div class="sec${bodySecs[key] ? " closed" : ""}" data-sec="${key}"><div class="lbl">${title}</div><div class="secbody">${body}</div></div>` : "";
  // materials in a three-column table, most abundant first
  const matTable = obj => {
    const e = Object.entries(obj || {}).sort((a, b) => b[1] - a[1]); if (!e.length) return null;
    let rows = "";
    for (let i = 0; i < e.length; i += 3) rows += "<tr>" + e.slice(i, i + 3).map(([k, v]) => `<td>${esc(k)}</td><td class="pct">${n(v, 1)}%</td>`).join("") + "</tr>";
    return `<table class="mats">${rows}</table>`;
  };
  const pct = obj => obj && Object.keys(obj).length ? Object.entries(obj).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(k)} ${n(v, 1)}%`).join(" · ") : null;
  const ownComp = own.Composition && Object.fromEntries(Object.entries(own.Composition).map(([k, v]) => [k, v * 100]));
  const ownMat = own.Materials && Object.fromEntries(own.Materials.map(m => [m.Name, m.Percent]));
  const ownAtm = own.AtmosphereComposition && Object.fromEntries(own.AtmosphereComposition.map(m => [m.Name, m.Percent]));
  let h = `<h3><b>${esc(d.full_name)}</b> <span class="cls">${esc(pick(own.PlanetClass && row.subtype, sp.subType) || row.subtype || own.StarType || "")}</span>` +
    `<button type="button" onclick="copyText(${esc(JSON.stringify(d.full_name))})">copy name</button><button type="button" onclick="${closeJs}">✕</button></h3>`;
  let physSec = "", orbitSec = "", compSec = "", ringSec = "";
  if (isStar) physSec = sec("star", "Star", kv([
    ["Class", (own.StarType ? `${esc(own.StarType)}${own.Subclass != null ? own.Subclass : ""} ${esc(own.Luminosity || "")}` : `${esc(sp.spectralClass || sp.subType || "")} ${esc(sp.luminosity || "")}`).trim()],
    ["Mass", has(own.StellarMass) ? `${n(own.StellarMass, 3)} solar` : has(sp.solarMasses) ? `${n(sp.solarMasses, 3)} solar` : null],
    ["Radius", has(own.Radius) ? `${n(own.Radius / 695700000, 3)} solar (${n(own.Radius / 1000, 0)} km)` : has(sp.solarRadius) ? `${n(sp.solarRadius, 3)} solar` : null],
    ["Temperature", has(pick(own.SurfaceTemperature, sp.surfaceTemperature)) ? `${n(pick(own.SurfaceTemperature, sp.surfaceTemperature), 0)} K` : null],
    ["Age", has(pick(own.Age_MY, sp.age)) ? `${n(pick(own.Age_MY, sp.age), 0)} My` : null],
    ["Absolute magnitude", n(pick(own.AbsoluteMagnitude, sp.absoluteMagnitude), 2)],
    ["Scoopable", row.scoopable == null ? null : row.scoopable ? "yes" : "no"],
    ["Distance", has(pick(own.DistanceFromArrivalLS, sp.distanceToArrival)) ? `${n(pick(own.DistanceFromArrivalLS, sp.distanceToArrival), 0)} ls` : null],
  ]));
  else physSec = sec("physical", "Physical", kv([
    ["Distance", has(pick(own.DistanceFromArrivalLS, sp.distanceToArrival)) ? `${n(pick(own.DistanceFromArrivalLS, sp.distanceToArrival), 0)} ls` : null],
    ["Mass", has(pick(own.MassEM, sp.earthMasses)) ? `${n(pick(own.MassEM, sp.earthMasses), 4)} Earth` : null],
    ["Radius", has(own.Radius) ? `${n(own.Radius / 1000, 0)} km` : has(sp.radius) ? `${n(sp.radius, 0)} km` : null],
    ["Gravity", has(row.gravity) ? `${n(row.gravity, 2)} g` : null],
    ["Temperature", has(pick(own.SurfaceTemperature, sp.surfaceTemperature)) ? `${n(pick(own.SurfaceTemperature, sp.surfaceTemperature), 0)} K` : null],
    ["Pressure", has(row.pressure) ? `${row.pressure < 0.01 ? n(row.pressure, 5) : n(row.pressure, 3)} atm` : null],
    ["Atmosphere", esc(pick(own.Atmosphere, sp.atmosphereType) || "none")],
    ["Atmosphere composition", pct(ownAtm || sp.atmosphereComposition)],
    ["Volcanism", esc(pick(own.Volcanism, sp.volcanismType) || "none")],
    ["Landable", (has(own.Landable) ? own.Landable : sp.isLandable) ? "yes" : "no"],
    ["Terraforming", esc(pick(own.TerraformState, sp.terraformingState) || "not terraformable")],
    ["Reserves", esc(pick(own.ReserveLevel, sp.reserveLevel))],
  ]));
  orbitSec = sec("orbit", "Orbit and rotation", kv([
    ["Orbital period", days(pick(own.OrbitalPeriod, sp.orbitalPeriod != null ? sp.orbitalPeriod * 86400 : null))],
    ["Semi-major axis", has(own.SemiMajorAxis) ? `${n(own.SemiMajorAxis / 1.496e11, 4)} AU` : has(sp.semiMajorAxis) ? `${n(sp.semiMajorAxis, 4)} AU` : null],
    ["Eccentricity", n(pick(own.Eccentricity, sp.orbitalEccentricity), 4)],
    ["Inclination", has(pick(own.OrbitalInclination, sp.orbitalInclination)) ? `${n(pick(own.OrbitalInclination, sp.orbitalInclination), 2)}°` : null],
    ["Argument of periapsis", has(pick(own.Periapsis, sp.argOfPeriapsis)) ? `${n(pick(own.Periapsis, sp.argOfPeriapsis), 2)}°` : null],
    ["Rotation period", days(pick(own.RotationPeriod, sp.rotationalPeriod != null ? sp.rotationalPeriod * 86400 : null))],
    ["Tidally locked", has(own.TidalLock) ? (own.TidalLock ? "yes" : "no") : has(sp.rotationalPeriodTidallyLocked) ? (sp.rotationalPeriodTidallyLocked ? "yes" : "no") : null],
    ["Axial tilt", has(own.AxialTilt) ? `${n(own.AxialTilt * 180 / Math.PI, 2)}°` : has(sp.axialTilt) ? `${n(sp.axialTilt * 180 / Math.PI, 2)}°` : null],
    ["Parents", (own.Parents || []).map(p => Object.entries(p).map(([k, v]) => `${k} ${v}`).join(" ")).join(" → ") || null],
  ]));
  if (!isStar) {
    const solid = pct(ownComp || sp.solidComposition), mats = matTable(ownMat || sp.materials);
    if (solid) compSec += sec("composition", "Composition", `<dl><dt>Solid</dt><dd>${solid}</dd></dl>`);
    if (mats) compSec += sec("materials", "Materials", mats);
  }
  if ((d.rings || []).length) ringSec = sec("rings", "Rings", `<table><thead><tr><th>Ring</th><th>Type</th><th class="num">Mass Mt</th><th class="num">Inner km</th><th class="num">Outer km</th><th class="num">Width km</th><th class="num">Density Mt/km²</th></tr></thead><tbody>` +
    d.rings.map(r => {
      const hs = Object.entries(r.hotspots || {}).sort((a, b) => a[0].localeCompare(b[0]));
      return `<tr class="ring"><td>${esc(short(r.name))}</td><td>${esc(r.type || "")}</td><td class="num">${r.mass != null ? n(r.mass, 0) : ""}</td><td class="num">${r.inner_km != null ? n(r.inner_km, 0) : ""}</td><td class="num">${r.outer_km != null ? n(r.outer_km, 0) : ""}</td><td class="num">${r.width_km != null ? n(r.width_km, 0) : ""}</td><td class="num">${r.density != null ? n(r.density, 4) : ""}</td></tr>` +
        `<tr class="hs"><td colspan="7">${hs.length ? `<ul>${hs.map(([k, v]) => `<li><b>${esc(k)}</b> ×${v}</li>`).join("")}</ul>` : r.mapped ? "mapped · no hotspots" : "not mapped"}</td></tr>`;
    }).join("") + `</tbody></table>`);
  // Order: bio first (it decides whether to land), then rings and composition, then physical | orbit, then value.
  let bioSec = "";
  if (row.bio || (row.genera || []).length || (row.organics || []).length || (row.codex || []).length) {
    const lines = [];
    const f = bioFactor(row);
    for (const g of bioGenera(row)) {
      const o = (row.organics || []).find(o => o.genus === g), x = (row.bio_guess || []).find(x => x.genus === g);
      const priced = o && !o.lost && o.value;   // the species is known from its first sample on
      lines.push(`<li><span>${esc(g)}${o ? ` · ${esc(o.species || "")}${o.variant ? " (" + esc(o.variant) + ")" : ""} ${o.lost ? "lost with the ship ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}` : x ? ` · could be ${esc(x.species.join(" / "))}${x.best && (x.variants || []).length ? ` <span class="unk" title="expected colour variant of the likeliest species">(${esc(x.variants.join(" or "))})</span>` : ""}` : ""}</span>` +
                 `<b>${priced ? credits(o.value * f) : x && x.value ? "≤" + credits(x.value * f) : ""}</b></li>`);
    }
    const unk = bioUnknown(row);   // signals no genus above accounts for, and what they could be
    if (unk) {
      lines.push(`<li><span class="unk">${unk.label}${unk.opt ? `: ${optLabel(unk.n, unk.opt, f)}; the DSS tells which` : ""}</span></li>`);
      lines.push(...unk.list.map(x => `<li><span>${esc(x.genus)} possible: ${esc(x.species.join(" / "))}${codexMark(x)}</span><b>≤${credits((x.value || 0) * f)}</b></li>`));
    }
    for (const c of row.codex || []) lines.push(`<li><span>📖 ${esc(c.name)}</span><b>${c.voucher ? "voucher " + c.voucher.toLocaleString() + " cr" : c.new ? "new to your codex" : ""}</b></li>`);
    bioSec = sec("bio", `🧬 Exobiology${row.bio ? ` · ${row.bio} signal${row.bio === 1 ? "" : "s"}` : ""}${bioRange(row)}`, `<ul>${lines.join("")}</ul>`);
  }
  const curSec = (row.curiosities || []).length ? sec("curiosities", "🔭 Curiosities", row.curiosities.map(c => `<div><b>${esc(c.tag)}</b> · ${esc(c.why)}</div>`).join("")) : "";
  h += curSec + bioSec + ringSec + compSec + `<div class="two">${physSec}${orbitSec}</div>`;
  h += sec("value", "Value and discovery", kv([
    ["Pays now", has(row.value_now) ? credits(row.value_now) + " cr" : null], ["Could pay", has(row.value_max) ? credits(row.value_max) + " cr" + (has(row.value_max_base) && row.value_max_base !== row.value_max ? ` (${credits(row.value_max_base)} without bonuses)` : "") : null],
    ["Of which", row.value_parts ? `${credits(row.value_parts.carto_now)} + ${credits(row.value_parts.bio_now)} bio held · ${credits(row.value_parts.carto_left)} + ${credits(row.value_parts.bio_left)} bio still there (bio ×${row.value_parts.bio_factor})` : null],
    ["Scan value", has(row.value) ? credits(row.value) + " cr" + (has(row.value_if_mapped) ? `, ${credits(row.value_if_mapped)} if mapped` : "") : null],
    ["Spansh estimate", has(sp.estimatedMappingValue || row.spansh_value) ? credits(sp.estimatedMappingValue || row.spansh_value) + " cr mapped" : null],
    ["When you scanned it", has(own.WasDiscovered) ? `${own.WasDiscovered ? "already discovered" : "undiscovered"} · ${own.WasMapped ? "already mapped" : "unmapped"}${has(own.WasFootfalled) ? " · " + (own.WasFootfalled ? "footfalled" : "no footfall") : ""}` : null],
    ["Your firsts", [row.first_discovered && "🏁 discovered", row.first_mapped && "🗺 mapped", row.first_footfall && "👣 footfall"].filter(Boolean).join(", ") || null],
    ["Mapped by you", row.mapped ? "yes" : "no"], ["Scan", own.ScanType ? `${esc(own.ScanType)} · ${esc(own.timestamp.replace("T", " ").replace("Z", ""))}` : "not scanned by you"],
  ]));
  h += `<div class="src">Sources: ${d.own ? "your journal Scan" : "no scan of yours"}${d.spansh ? ` · Spansh (updated ${esc((sp.updateTime || "").slice(0, 10))})` : d.spansh_error ? ` · Spansh lookup failed (${esc(d.spansh_error)})` : " · not on Spansh"}</div>`;
  panel.innerHTML = h;
}

// ---- My firsts ----
let firstsKey = null, firstsData = null;
async function loadFirsts() {
  const key = `${data && data.scan_version}|${data && data.unsold && data.unsold.computed}`;
  if (key === firstsKey) return;
  firstsKey = key;
  document.getElementById("fStatus").textContent = "loading…";
  try { const f = await apiJson("api/firsts"); if (key === firstsKey) firstsData = f; else return; } catch (err) { firstsData = {error: err.message}; }
  if (firstsData && firstsData.error) firstsKey = null;   // retried at the next render
  renderFirsts();
}
function renderFirsts() {
  const f = firstsData, st = document.getElementById("fStatus"), bms = bmMap();
  if (!f || f.error) { st.textContent = f ? f.error : ""; return; }
  // lost data stays in the database (a rescan earns it again) but is hidden unless asked for
  const list = f.firsts.filter(x => fShowLost.checked || x.state !== "lost");
  list.sort(sortKeys.firsts === "name" ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
          : sortKeys.firsts === "distance" ? (a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9)
          : (a, b) => (b.value || 0) - (a.value || 0));
  const unsold = f.firsts.filter(x => x.state === "unsold"), lost = f.firsts.filter(x => x.state === "lost");
  st.textContent = `${unsold.length} systems with unsold firsts (${credits(unsold.reduce((n, x) => n + (x.value || 0), 0))} cr on board) · ${lost.length} with lost firsts${fShowLost.checked ? "" : " (hidden)"}`;
  const by = b => ["sold", "unsold", "lost"].filter(k => b && b[k]).map(k => `<span class="${k}">${b[k]} ${k}</span>`).join(" · ");
  document.getElementById("firstsRows").innerHTML = list.map(x => `<tr>
      <td class="bmcell">${bmIcon(x.id, x.name, bms)}</td>
      <td class="name" data-name="${esc(x.name)}" title="click to copy">${esc(x.name)}</td>
      <td class="num dist">${x.distance == null ? "?" : x.distance.toLocaleString("en-US", {maximumFractionDigits: 1})}</td>
      <td>${x.system ? `<span class="${x.system_state}">🏁 ${x.system_state}</span>` : ""}</td>
      <td class="by">${by(x.bodies_by)}</td><td class="by">${by(x.mapped_by)}</td>
      <td class="num">${x.value ? credits(x.value) : ""}</td></tr>`).join("") ||
    `<tr><td colspan="7" class="unk">${lost.length && !fShowLost.checked ? `Nothing unsold. ${lost.length} systems with lost data are hidden — tick "show lost" to see them.`
      : "Nothing unsold or lost: every first you have found is banked."}</td></tr>`;
}
// ---- Left behind: unfinished work in systems you have visited nearby ----
let leftKey = null, leftData = null;
const lbRadius = document.getElementById("lbRadius");
lbRadius.value = store.get("lbRadius", "100");
lbRadius.onchange = () => { store.set("lbRadius", lbRadius.value); leftKey = null; loadLeft(); };
async function loadLeft() {
  const key = `${lbRadius.value}|${data && data.scan_version}|${data && data.position && data.position.id64}`;
  if (key === leftKey) return renderLeft();
  leftKey = key;
  try { leftData = await apiJson(`api/left?radius=${lbRadius.value}`); } catch (err) { leftData = {error: err.message}; }
  if (leftData.error) leftKey = null;
  renderLeft();
}
function renderLeft() {
  const el = document.getElementById("leftRows"), d = leftData;
  if (!d || d.error) { el.innerHTML = `<tr><td colspan="4" class="unk">${d ? esc(d.error) : "loading…"}</td></tr>`; return; }
  const rows = d.systems.map(r => {
    const maps = r.maps.filter(m => m.increment >= hlLevel("body")), bio = r.bio.filter(b => b.value >= bioMinNow());
    const worth = maps.reduce((n, m) => n + m.increment, 0) + bio.reduce((n, b) => n + b.value, 0);
    const bits = [r.unfound ? `${r.unfound} bod${r.unfound === 1 ? "y" : "ies"} not found` : "",
      maps.length ? "map " + maps.map(m => `<b>${esc(m.body)}</b> <span class="unk">${esc(m.subtype)}${m.terraformable ? " T" : ""} +${credits(m.increment)}</span>`).join(", ") : "",
      // genera null: FSS signals nobody DSS'd, priced as the leaving alert prices them (an upper bound)
      bio.length ? "bio " + bio.map(b => `<b>${esc(b.body)}</b> <span class="unk">${b.genera === null ? `${b.signals} signal${b.signals === 1 ? "" : "s"}, not DSS'd`
        : b.genera.map(esc).join(", ")} ≤${credits(b.value)}</span>`).join(", ") : ""].filter(Boolean);
    return {r, bits, worth, keep: maps.length || bio.length || r.unfound};
  }).filter(x => x.keep && x.bits.length);
  el.innerHTML = rows.map(({r, bits, worth}) => `<tr><td><span class="name" data-name="${esc(r.name)}" title="click to copy">${esc(r.name)}</span><span class="goto" data-goto="${esc(r.id)}" title="open in Here">⌖</span></td>
      <td class="num">${r.distance.toFixed(1)}</td><td class="left-what">${bits.join(" · ")}</td><td class="num">${worth ? credits(worth) : ""}</td></tr>`).join("")
    || `<tr><td colspan="4" class="unk">Nothing worth going back for within ${d.radius} ly.</td></tr>`;
}
document.getElementById("leftRows").addEventListener("click", e => {
  const g = e.target.closest("[data-goto]"); if (g) return showInHere(g.dataset.goto);
  const n = e.target.closest(".name"); if (n) copyText(n.dataset.name);
});
const fShowLost = document.getElementById("fShowLost");
fShowLost.checked = store.get("fShowLost", false);
fShowLost.onchange = () => { store.set("fShowLost", fShowLost.checked); renderFirsts(); };

// ---- Materials ----
let matKey = null, matData = null;
const mFilter = document.getElementById("mFilter"), mHeld = document.getElementById("mHeld");
mHeld.checked = store.get("mHeld", false);
mHeld.onchange = () => { store.set("mHeld", mHeld.checked); renderMat(); };
mFilter.oninput = () => renderMat();
async function loadMat() {
  // the sources list depends on where you are and what you have scanned; the stale note on the materials snapshot
  const m0 = data && data.materials;
  const key = `${m0 && m0.version}|${m0 && m0.stale}|${data && data.scan_version}|${data && data.position && data.position.id64}|${data && data.run_id}`;
  if (key === matKey) return;
  matKey = key;
  document.getElementById("matStatus").textContent = "loading…";
  try { const m = await apiJson("api/materials"); if (key === matKey) matData = m; else return; } catch (err) { matData = {error: err.message}; }
  if (matData && matData.error) matKey = null;   // retried at the next render
  renderMat();
}
function renderMat() {
  const m = matData, st = document.getElementById("matStatus");
  if (!m || m.error) { st.textContent = m ? m.error : ""; return; }
  const held = m.rows.filter(r => r.count);
  st.innerHTML = !m.snapshot_ts ? "No Materials snapshot in your journals yet: log in to the game once." :
    `${held.length} materials held, ${held.reduce((n, r) => n + r.count, 0).toLocaleString()} units · snapshot ${esc(m.snapshot_ts.replace("T", " ").slice(0, 16))} UTC` +
    (m.ts !== m.snapshot_ts ? ` · last change ${esc((m.ts || "").replace("T", " ").slice(0, 16))}` : "") +
    (m.stale ? ` · <span class="noscoop">your last login wrote no Materials line: these counts predate it</span>` : "");
  // every material that runs out at the craftable count limits it (ties included, e.g. all three at 4)
  const limiting = r => r.materials.filter(x => Math.floor(x.have / x.need) === r.craftable).map(x => x.name);
  document.getElementById("matSynth").innerHTML = m.synthesis.map(r => `<div class="synth" title="${r.verified ? "recipe checked against a real synthesis in your journals" : "published in-game recipe"}">
      <span class="n${r.craftable ? "" : " zero"}">×${r.craftable}</span><b>${esc(r.name)}</b>${r.boost ? `<div class="unk boostline">${esc(r.boost)} range</div>` : ""}
      <div class="mats">${r.materials.map(x => `<span class="${x.have < x.need ? "short" : r.craftable < 10 && limiting(r).includes(x.name) ? "limit" : ""}">${esc(x.name)} ${x.have}/${x.need}</span>`).join(" · ")}</div></div>`).join("");
  // where to find the FSD-injection materials: the nearest landable bodies you have scanned that carry them
  // only a recipe you are short of (under 10, the grid's threshold) has a limiting material worth fetching
  const src = m.sources || {}, limits = new Set(m.synthesis.filter(r => /^FSD/.test(r.name) && r.craftable < 10).flatMap(limiting));
  const have = Object.fromEntries(m.rows.map(r => [r.id, r]));
  document.getElementById("matSources").innerHTML = Object.keys(src).length ? `<h3 class="subhead">Where to find FSD-injection materials <span class="unk">· scanned landable bodies within 300 ly, nearest first</span></h3>` +
    `<table class="srcTable"><tbody>` + Object.entries(src).map(([mat, list]) => { const h = have[mat] || {};
      return `<tr class="${limits.has(h.name) ? "limiting" : ""}"><td><b>${esc(h.name || mat)}</b>${limits.has(h.name) ? ` <span class="noscoop" title="limits how many injections you can make">limiting</span>` : ""}</td>` +
        `<td class="num">${h.count ?? 0}${h.cap ? " / " + h.cap : ""}</td><td>` +
        (list.map(x => `<span class="name" data-name="${esc(x.system)}" title="click to copy the system">${esc(x.body)}</span> <span class="unk">${x.pct}% · ${x.distance} ly</span>`).join(" · ") || `<span class="unk">none scanned nearby</span>`) + `</td></tr>`; }).join("") +
    `</tbody></table>` : "";
  const f = mFilter.value.trim().toLowerCase();
  const rows = m.rows.filter(r => (!mHeld.checked || r.count) && (!f || r.name.toLowerCase().includes(f)));
  const cats = ["Raw", "Manufactured", "Encoded", "Other"];
  document.getElementById("matGrid").innerHTML = cats.map(c => {
    const list = rows.filter(r => r.category === c);
    if (!list.length) return "";
    const grades = [...new Set(list.map(r => r.grade))].sort();
    return `<div><h4>${c}</h4>` + grades.map(g => `<div class="grade">${g ? `Grade ${g} · cap ${list.find(r => r.grade === g).cap}` : "Unknown grade"}</div>` +
      list.filter(r => r.grade === g).sort((a, b) => a.name.localeCompare(b.name)).map(r => {
        const pct = r.cap ? Math.min(100, 100 * r.count / r.cap) : 0;
        return `<div class="mrow${!r.count ? " none" : r.cap && r.count >= r.cap ? " full" : ""}"><span>${esc(r.name)}</span>` +
          `<span class="cnt"><b>${r.count}</b>${r.cap ? " / " + r.cap : ""}</span><span class="bar"><i style="width:${pct}%"></i></span></div>`;
      }).join("")).join("") + `</div>`;
  }).join("") || `<div class="unk">No materials match.</div>`;
}

// ---- Log: every journal event ----
// gen: bumped by every fresh load, so an answer to an older request (a tail or "more" still on its way when the
// filters changed) is dropped and cannot release the lock or prepend rows from the old cursor
const L = {rows: [], next: null, newest: null, key: null, loading: false, open: new Set(), journal: null, fresh: new Set(), gen: 0};
const LOG_MAX_ROWS = 1000;   // tailing keeps the newest this many; "more" continues below the last one kept
// what the tail keys on: freshness.read moves with every journal line consumed (the journal time is to the second)
const logMark = () => data && data.freshness ? data.freshness.read ?? data.freshness.journal : null;
const lDays = document.getElementById("lDays"), lNoise = document.getElementById("lNoise"), lFilter = document.getElementById("lFilter");
const lCatBoxes = [...document.querySelectorAll("#lCats input")];
const lSaved = store.get("log", {});
if (lSaved.days && (typeof lSaved.days === "string" || typeof lSaved.days === "number")) lDays.value = lSaved.days;
lNoise.checked = !!lSaved.noise;
// a category added since the filters were saved starts ticked
// (a hand-edited import or server copy may hold anything there: a list that is not a list reads as unset)
const lKnown = Array.isArray(lSaved.known) ? lSaved.known : ["travel", "exploration", "bio", "ship", "carrier", "other"];   // saves from before "known"
if (Array.isArray(lSaved.cats)) lCatBoxes.forEach(b => b.checked = lSaved.cats.includes(b.value) || !lKnown.includes(b.value));
const CAT_GLYPH = {travel: "🚀", exploration: "🔭", phenomena: "🌀", bio: "🧬", ship: "🛠", carrier: "🚢", other: "•", noise: "·"};
function logQuery() {
  const cats = lCatBoxes.filter(b => b.checked).map(b => b.value);
  if (lNoise.checked) cats.push("noise");
  return `days=${lDays.value}&cat=${cats.join(",") || "none"}&q=${encodeURIComponent(lFilter.value.trim())}&noise=${lNoise.checked ? 1 : 0}`;
}
function saveLog() {
  store.set("log", {days: lDays.value, noise: lNoise.checked, cats: lCatBoxes.filter(b => b.checked).map(b => b.value),
                    known: lCatBoxes.map(b => b.value)});
}
async function loadLog(force = false) {
  const key = logQuery();
  if (key === L.key && !force) return;
  const gen = ++L.gen, mark = logMark();   // the mark as of the request: lines read after it are tailed next
  L.key = key; L.loading = true; L.newest = null;   // no tail from the old filter's cursor meanwhile
  document.getElementById("lStatus").textContent = "loading…";
  try {
    const r = await apiJson(`api/log?${key}`);
    if (gen !== L.gen) return;
    if (r.error) throw new Error(r.error);
    Object.assign(L, {rows: r.rows || [], next: r.next, newest: r.newest, error: null, journal: mark});
  } catch (err) { if (gen !== L.gen) return; L.error = "log failed: " + err.message; L.key = null; }   // rows kept; the next render tries again
  L.loading = false;
  renderLog();
}
async function moreLog() {
  // after a failed reload there are no filters to page with (L.key null): the next render reloads first
  if (!L.next || L.loading || L.key === null) return;
  const key = L.key, gen = L.gen; L.loading = true;
  try {
    const r = await apiJson(`api/log?${key}&before=${encodeURIComponent(L.next)}`);
    if (gen !== L.gen) return;   // the filters changed meanwhile: that load owns the lock now
    if (r.error) throw new Error(r.error);
    L.rows = L.rows.concat(r.rows || []); L.next = r.next; L.error = null;
  } catch (err) { if (gen !== L.gen) return; L.error = "loading more failed: " + err.message; }   // L.next kept: "more" tries again
  L.loading = false;
  renderLog();
}
async function tailLog() {   // new journal lines since the newest row: prepend them
  const j = logMark();
  if (!L.newest || L.loading || j === L.journal) return;
  const key = L.key, gen = L.gen; L.journal = j; L.loading = true;
  try {
    const r = await apiJson(`api/log?${key}&after=${encodeURIComponent(L.newest)}`);
    if (gen !== L.gen) return;   // a fresh load started meanwhile: its answer replaces everything
    L.loading = false;
    if (r.error) { L.journal = null; return; }   // asked again at the next change
    if (r.reset) return loadLog(true);
    L.newest = r.newest || L.newest;
    // the tail answered: a "loading more failed" from earlier is old news (L.next is kept, so "more" still works)
    const hadError = !!L.error; L.error = null;
    if (hadError && !(r.rows && r.rows.length)) renderLog();
    if (r.rows && r.rows.length) {
      const before = document.documentElement.scrollHeight, y = window.scrollY;
      r.rows.forEach(x => L.fresh.add(x.id));
      L.rows = r.rows.concat(L.rows);
      // a long session with the Log open: keep the newest rows (each holds its raw event), "more" fetches the rest
      if (L.rows.length > LOG_MAX_ROWS) { L.rows.length = LOG_MAX_ROWS; L.next = L.rows[LOG_MAX_ROWS - 1].id; }
      renderLog();
      if (y > 0) window.scrollBy(0, document.documentElement.scrollHeight - before);  // keep your place unless at the top
      setTimeout(() => { r.rows.forEach(x => L.fresh.delete(x.id)); }, 2500);
    }
  } catch { if (gen === L.gen) { L.loading = false; L.journal = null; } }
}
function openBodyIn(id, name) {
  id = String(id);
  view = "here"; store.set("view", view);
  pinnedSystem = posId() === id ? null : id;
  hidePop();
  selectedBody = name; selectedSystem = id; bodyData = null;
  const panel = document.getElementById("bodyPanel");
  panel.hidden = false; panel.innerHTML = `<h3><b>${esc(name)}</b> <button type="button" onclick="closeBody()">✕</button></h3><div class="unk">loading…</div>`;
  render(); renderHere(); reloadBody();
}
const localTime = ts => { const d = new Date(ts); return isNaN(d) ? ts : d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}); };
const localDay = ts => { const d = new Date(ts); return isNaN(d) ? "" : d.toLocaleDateString([], {weekday: "short", year: "numeric", month: "short", day: "numeric"}); };
function renderLog() {
  const st = document.getElementById("lStatus");
  st.textContent = L.error ? L.error : L.loading ? "loading…" : `${L.rows.length} events${L.next ? " (more below)" : ""}`;
  let day = null, h = "";
  for (const r of L.rows) {
    const d = localDay(r.ts);
    if (d !== day) { h += `<tr class="day"><td colspan="5">${esc(d)}</td></tr>`; day = d; }
    const sys = r.system ? `<span class="name" data-name="${esc(r.system)}" title="click to copy">${esc(r.system)}</span>` +
      (r.id64 ? `<span class="goto" data-goto="${esc(r.id64)}" title="open in Here">⌖</span>` : "") : "";
    const body = r.body && r.id64 ? ` <span class="goto" data-body="${esc(r.body)}" data-bsys="${esc(r.id64)}" title="open ${esc(r.body)} in Here">🔍</span>` : "";
    h += `<tr class="ln ${r.cat}${L.fresh.has(r.id) ? " fresh" : ""}" data-id="${esc(r.id)}"><td class="t" title="${esc(r.ts)}">${localTime(r.ts)}</td>` +
      `<td title="${r.cat}">${CAT_GLYPH[r.cat] || ""}</td><td class="ev hide-sm">${esc(r.event)}</td><td class="sum">${esc(r.summary)}${body}</td><td>${sys}</td></tr>`;
    if (L.open.has(r.id)) h += `<tr class="raw"><td colspan="5"><pre>${esc(JSON.stringify(r.raw, null, 2))}</pre></td></tr>`;
  }
  document.getElementById("logRows").innerHTML = h || `<tr><td colspan="5" class="unk">${L.loading ? "" : "No events match."}</td></tr>`;
  document.getElementById("lMore").hidden = !L.next || L.key === null;
}
lCatBoxes.forEach(b => b.onchange = () => { saveLog(); loadLog(); });
lNoise.onchange = () => { saveLog(); loadLog(); };
lDays.onchange = () => { saveLog(); loadLog(); };
let lTimer = null;
lFilter.oninput = () => { clearTimeout(lTimer); lTimer = setTimeout(() => loadLog(), 350); };
document.getElementById("lMore").onclick = moreLog;
document.getElementById("logRows").addEventListener("click", e => {
  const b = e.target.closest("[data-body]"); if (b) return openBodyIn(b.dataset.bsys, b.dataset.body);
  const g = e.target.closest("[data-goto]"); if (g) return showInHere(g.dataset.goto);
  const n = e.target.closest(".name"); if (n) return copyText(n.dataset.name);
  const tr = e.target.closest("tr.ln"); if (!tr) return;
  L.open.has(tr.dataset.id) ? L.open.delete(tr.dataset.id) : L.open.add(tr.dataset.id);
  renderLog();
});

// ---- Samples: every exobiology run and codex entry ----
let bioKey = null, bioData = null;
const bDays = document.getElementById("bDays"), bState = document.getElementById("bState"), bFilter = document.getElementById("bFilter");
bDays.value = store.get("bDays", "30"); bState.value = store.get("bState", "");
let bioSort = store.get("bioSort", {key: "ts", dir: -1});
bDays.onchange = () => { store.set("bDays", bDays.value); bioKey = null; loadBio(); };
bState.onchange = () => { store.set("bState", bState.value); renderBio(); };
bFilter.oninput = () => renderBio();
function showInHere(id) { view = "here"; store.set("view", view); pinSystem(id); }
// ---- Find a system by name (Search's top row): the server resolves it, Here shows it ----
const foundSys = {};   // id -> the last /api/find answer: the pinned Here heading's distance for a system not nearby
document.getElementById("findForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = document.getElementById("findName").value.trim(), st = document.getElementById("findStatus");
  if (!name) return;
  st.textContent = `looking up ${name}…`;
  let d;
  try { d = await apiJson(`api/find?name=${encodeURIComponent(name)}`); } catch (err) { d = {error: err.message}; }
  if (d.error) { st.textContent = d.error; return; }
  foundSys[d.id] = d;
  const v = d.visited;
  st.textContent = [d.name, d.distance != null ? `${d.distance.toLocaleString("en-US", {maximumFractionDigits: 2})} ly` : null,
    v ? `visited ${v.count}× (last ${day(v.last_ts)})` : "never visited", d.bookmarked && "bookmarked", d.next_stop && "the next stop",
    d.source === "edsm" && "found on EDSM"].filter(Boolean).join(" · ");
  showInHere(d.id);
});
async function loadBio() {
  const key = `${bDays.value}|${data && data.scan_version}`;
  if (key === bioKey) return;
  bioKey = key;
  document.getElementById("bStatus").textContent = "loading…";
  try { const b = await apiJson(`api/organics?days=${bDays.value}`); if (key === bioKey) bioData = b; else return; } catch (err) { bioData = {error: err.message}; }
  if (bioData && bioData.error) bioKey = null;   // retried at the next render
  renderBio();
}
const when = ts => ts ? ts.slice(0, 10) + " " + ts.slice(11, 16) : "";
const sysCell = s => !s ? "" : `<span class="name" data-name="${esc(s.name)}" title="click to copy">${esc(s.name)}</span><span class="goto" data-goto="${esc(s.id)}" title="open in Here">⌖</span>`;
function renderBio() {
  const b = bioData, st = document.getElementById("bStatus");
  if (!b || b.error) { st.textContent = b ? b.error : ""; return; }
  const f = bFilter.value.trim().toLowerCase();
  const match = r => !f || [r.genus, r.species, r.variant, r.system.name, r.body].some(x => (x || "").toLowerCase().includes(f));
  const rows = b.rows.filter(r => (!bState.value || r.state === bState.value) && match(r));
  const k = bioSort.key, dir = bioSort.dir;
  const val = r => k === "system" ? r.system.name : r[k];
  rows.sort((x, y) => { const a = val(x), c = val(y);
    if (typeof a === "number" || typeof c === "number") return dir * ((a ?? -1) - (c ?? -1));
    return dir * String(a ?? "").localeCompare(String(c ?? ""), undefined, {numeric: true}); });
  const n = b.counts, t = b.totals;
  st.innerHTML = `${b.rows.length} sample runs · <span class="aboard">${n.aboard} aboard <b>${credits(t.aboard)} cr</b></span> · ` +
    `<span class="sold">${n.sold} sold <b>${credits(t.sold)} cr</b></span> · <span class="lost">${n.lost} lost <b>${credits(t.lost)} cr</b></span>` +
    (n["in progress"] ? ` · <span class="progress">${n["in progress"]} in progress</span>` : "") +
    (rows.length !== b.rows.length ? ` · showing ${rows.length}` : "");
  document.querySelectorAll("th[data-bsort]").forEach(h => h.classList.toggle("on", h.dataset.bsort === k));
  document.getElementById("bioRows").innerHTML = rows.map(r => `<tr>
      <td>${when(r.ts)}</td><td>${sysCell(r.system)}</td><td>${esc(r.body)}</td><td>${esc(r.genus || "")}</td>
      <td>${esc((r.species || "").split(" ").slice(1).join(" ") || r.species || "")}</td><td class="hide-sm">${esc((r.variant || "").split(" - ").pop())}</td>
      <td class="num">${r.samples}/3</td>
      <td class="${r.state === "in progress" ? "progress" : r.state}" title="${r.sold_ts ? "sold " + when(r.sold_ts) : ""}">${r.state}</td>
      <td class="num" title="${r.factor === 5 ? "×5 first footfall bonus" : ""}">${r.value ? credits(r.value) + (r.factor === 5 ? " ✦" : "") : "?"}</td></tr>`).join("") ||
    `<tr><td colspan="9" class="unk">${b.rows.length ? "Nothing matches the filter." : "No samples in this period."}</td></tr>`;
  const cx = b.codex.filter(c => !f || [c.name, c.category, c.region, c.system && c.system.name].some(x => (x || "").toLowerCase().includes(f)));
  document.getElementById("cStatus").textContent = `· ${b.codex.length} in this period, ${b.codex.filter(c => c.new).length} new to your codex, ` +
    `${credits(b.codex.reduce((s, c) => s + (c.voucher || 0), 0))} cr in vouchers`;
  document.getElementById("codexRows").innerHTML = cx.map(c => `<tr><td>${when(c.ts)}</td><td>${esc(c.name)}</td>
      <td class="hide-sm">${esc([c.category, c.subcategory].filter(Boolean).join(" · "))}</td><td class="hide-sm">${esc(c.region || "")}</td>
      <td>${sysCell(c.system)}</td><td>${c.voucher ? `💰 ${c.voucher.toLocaleString()} cr` : c.new ? "✦ new" : ""}</td></tr>`).join("") ||
    `<tr><td colspan="6" class="unk">No codex entries in this period.</td></tr>`;
}
document.querySelectorAll("th[data-bsort]").forEach(h => h.onclick = () => {
  bioSort = {key: h.dataset.bsort, dir: bioSort.key === h.dataset.bsort ? -bioSort.dir : (["ts", "value", "samples"].includes(h.dataset.bsort) ? -1 : 1)};
  store.set("bioSort", bioSort); renderBio();
});
document.getElementById("bioView").addEventListener("click", e => {
  const g = e.target.closest("[data-goto]"); if (g) return showInHere(g.dataset.goto);
  const n = e.target.closest(".name"); if (n) copyText(n.dataset.name);
});

// ---- History ----
let histKey = null, histData = null;
const hDays = document.getElementById("hDays");
hDays.value = store.get("hDays", "30");
hDays.onchange = () => { store.set("hDays", hDays.value); histKey = null; loadHistory(); };
async function loadHistory() {
  // not scan_version: the ledger is a full pass on the server, so only a jump, a sale or a death (or opening
  // the tab) fetches it again, not every scan while the tab is open
  const key = `${hDays.value}|${data && data.history_version}`;
  if (key === histKey) return;
  histKey = key;
  document.getElementById("hStatus").textContent = "loading…";
  try { const h = await apiJson(`api/history?days=${hDays.value}`); if (key === histKey) histData = h; else return; } catch (err) { histData = {error: err.message}; }
  if (histData && histData.error) histKey = null;   // retried at the next render
  renderHistory();
}
// the Last session card: the session your latest quit ended, from the quit until you load into the game again
function sessionLine(st) {
  const n = (k, one, many) => st[k] ? `${st[k].toLocaleString("en-US")} ${st[k] === 1 ? one : many}` : null;
  return [`${(st.jumps || 0).toLocaleString("en-US")} jump${st.jumps === 1 ? "" : "s"}`, st.ly ? `${Math.round(st.ly).toLocaleString("en-US")} ly` : null,
    n("firsts", "new system", "new systems"), n("bodies_first", "new body", "new bodies"), n("mapped", "mapped", "mapped"), n("footfalls", "footfall", "footfalls"),
    n("samples", "sample", "samples"), n("codex_new", "codex entry", "codex entries")].filter(Boolean).join(" · ");
}
function renderLastSession() {
  const ls = data && data.last_session, el = document.getElementById("lastSession");
  if (!el) return;
  el.innerHTML = !ls ? "" : `<b>Last session</b> <span class="unk">${esc(ls.start.replace("T", " ").slice(0, 16))} → ${esc(ls.end.slice(11, 16))} UTC</span> · ${esc(sessionLine(ls))}` +
    (ls.max_sol ? ` <span class="unk">· ${ls.max_sol.toLocaleString("en-US")} ly from Sol at most</span>` : "");
  el.hidden = !ls;
}
const openSessions = new Set();
function renderHistory() {
  renderLastSession();
  const h = histData, st = document.getElementById("hStatus");
  if (!h || h.error) { st.textContent = h ? h.error : ""; return; }
  const tot = k => h.sessions.reduce((n, s) => n + s[k], 0);
  st.textContent = `${h.sessions.length} sessions · ${tot("jumps")} jumps · ${Math.round(tot("ly")).toLocaleString()} ly · ${tot("firsts")} systems first discovered · ${tot("samples")} samples`;
  const fmt = ts => ts.slice(0, 10) + " " + ts.slice(11, 16);
  const a = h.all_time;
  document.getElementById("histAll").innerHTML = !a ? "" : `<tr class="alltime" title="every session in your journals${a.since ? ", since " + a.since.slice(0, 10) : ""}">
      <td><b>All time</b> <span class="unk">${a.sessions.toLocaleString()} sessions</span></td>
      <td class="num">${a.jumps.toLocaleString()}</td><td class="num">${Math.round(a.ly).toLocaleString()}</td><td class="num hide-sm">${a.max_sol.toLocaleString()}</td>
      <td class="num">${a.firsts.toLocaleString()}</td><td class="num hide-sm">${a.bodies_first.toLocaleString()}</td><td class="num">${a.mapped.toLocaleString()}</td>
      <td class="num hide-sm">${a.footfalls.toLocaleString()}</td><td class="num">${a.samples.toLocaleString()}</td><td class="num hide-sm">${a.codex_new.toLocaleString()}</td></tr>`;
  const L = h.ledger || {}, ss = L.since_last_sale, car = L.career;
  if (ss && ss.since) document.getElementById("histAll").insertAdjacentHTML("beforeend",
    `<tr class="alltime sincesale" title="everything since your last sale to Universal Cartographics"><td><b>Since your last sale</b> <span class="unk">${ss.days} d · ${esc(ss.since.slice(0, 10))}</span></td>
      <td class="num">${ss.jumps.toLocaleString()}</td><td class="num">${Math.round(ss.ly).toLocaleString()}</td><td class="num hide-sm">${ss.max_sol.toLocaleString()}</td>
      <td class="num">${ss.firsts}</td><td class="num hide-sm">${ss.bodies_first}</td><td class="num">${ss.mapped}</td>
      <td class="num hide-sm">${ss.footfalls}</td><td class="num">${ss.samples}</td><td class="num hide-sm">${ss.codex_new}</td></tr>`);
  if (car && car.Exploration) { const e = car.Exploration, o = car.Exobiology || {};
    document.getElementById("histAll").insertAdjacentHTML("beforeend",
      `<tr class="alltime career" title="the game's own statistics (your whole career, including journals Outrider never saw), as of ${esc((car.ts || "").slice(0, 10))}">
        <td><b>Career</b> <span class="unk">game statistics</span></td><td class="num">${(e.Total_Hyperspace_Jumps || 0).toLocaleString()}</td>
        <td class="num">${Math.round(e.Total_Hyperspace_Distance || 0).toLocaleString()}</td><td class="num hide-sm" title="greatest distance from your start">${Math.round(e.Greatest_Distance_From_Start || 0).toLocaleString()}</td>
        <td class="num" title="systems visited">${(e.Systems_Visited || 0).toLocaleString()}</td><td class="num hide-sm"></td><td class="num" title="planets mapped (surface scans)">${(e.Planets_Scanned_To_Level_3 || 0).toLocaleString()}</td>
        <td class="num hide-sm">${(e.First_Footfalls || 0).toLocaleString()}</td><td class="num" title="organic species encountered">${(o.Organic_Species_Encountered || 0).toLocaleString()}</td><td class="num hide-sm"></td></tr>`); }
  const fmtD = t => t ? t.slice(0, 10) : "start";
  const lossHtml = ls => ls.map(l => `<span class="lost" title="${l.ship ? `${l.bodies} bodies (${l.firsts} first discoveries) died with the ship` : "you died, the ship survived"}` +
    `${l.bio_runs ? `; ${l.bio_runs} completed sample run${l.bio_runs === 1 ? "" : "s"} lost` : ""}">✗ ${esc(l.ts.slice(0, 10))} −${credits((l.value || 0) + (l.bio_value || 0))}` +
    `${l.bio_value ? ` (${l.value ? `${credits(l.value)} carto, ` : ""}${credits(l.bio_value)} bio)` : ""}</span>`).join(" ");
  // the trip still under way: a trip row only exists once a sale ends it, so losses since the last sale (every
  // loss, if you have never sold) would show nowhere
  const cur = (L.losses || []).filter(l => !(ss && ss.since) || l.ts > ss.since);
  const curRow = !cur.length ? "" : `<tr class="curtrip" title="since your last sale: the trip ends at your next sale"><td>${ss && ss.since ? fmtD(ss.since) : "start"} → now</td>` +
    `<td class="num">${ss && ss.days != null ? ss.days : ""}</td><td class="num">${ss ? (ss.jumps || 0).toLocaleString() : ""}</td>` +
    `<td class="num hide-sm">${ss ? Math.round(ss.ly || 0).toLocaleString() : ""}</td><td class="num">${ss ? ss.firsts ?? "" : ""}</td>` +
    `<td class="num unk">not sold</td><td class="num hide-sm"></td><td class="num hide-sm"></td><td class="num hide-sm"></td><td class="num hide-sm"></td><td>${lossHtml(cur)}</td></tr>`;
  document.getElementById("tripRows").innerHTML = curRow + (L.trips || []).map(t => {
    const est = t.estimate ? ` <span class="unk">${t.estimate ? (t.paid_carto >= t.estimate ? "+" : "") + Math.round(100 * (t.paid_carto - t.estimate) / t.estimate) + "%" : ""}</span>` : "";
    const losses = lossHtml(t.losses);
    return `<tr><td>${fmtD(t.start)} → ${fmtD(t.end)}</td><td class="num">${t.days ?? ""}</td><td class="num">${t.jumps.toLocaleString()}</td>
      <td class="num hide-sm">${Math.round(t.ly).toLocaleString()}</td><td class="num">${t.firsts}</td>
      <td class="num" title="${credits(t.paid_carto || 0)} cartographics + ${credits(t.paid_bio || 0)} exobiology">${credits(t.paid)}</td>
      <td class="num hide-sm">${t.estimate ? credits(t.estimate) + est : ""}</td><td class="num hide-sm">${t.per_hour ? credits(t.per_hour) : ""}</td>
      <td class="num hide-sm">${t.per_jump ? credits(t.per_jump) : ""}</td><td class="num hide-sm">${t.first_rate ?? ""}</td><td>${losses}</td></tr>`;
  }).join("") + ((L.trips || []).length ? "" : `<tr><td colspan="11" class="unk">No sales on record yet.</td></tr>`);
  document.getElementById("topRows").innerHTML = (L.top_finds || []).map(f => `<tr><td><span class="name" data-name="${esc(f.body)}" title="click to copy">${esc(f.body)}</span></td>
      <td>${esc(f.type || "")}${f.first_discovered ? " 🏁" : ""}${f.mapped ? " 🗺" : ""}</td><td class="num">${credits(f.value)}</td>
      <td class="${f.state === "lost" ? "lost" : f.state === "sold" ? "sold" : "unsold"}">${f.state === "unsold" ? "aboard" : f.state}</td><td class="hide-sm">${esc((f.ts || "").slice(0, 10))}</td></tr>`).join("");
  document.getElementById("histRows").innerHTML = h.sessions.map((s, i) => {
    const open = openSessions.has(s.start);
    return `<tr class="sess${open ? " open" : ""}" data-sess="${esc(s.start)}"><td>${fmt(s.start)} → ${s.end.slice(11, 16)}</td>
      <td class="num">${s.jumps}</td><td class="num">${s.ly.toLocaleString()}</td><td class="num hide-sm">${s.max_sol.toLocaleString()}</td>
      <td class="num">${s.firsts}</td><td class="num hide-sm">${s.bodies_first}</td><td class="num">${s.mapped}</td>
      <td class="num hide-sm">${s.footfalls}</td><td class="num">${s.samples}</td><td class="num hide-sm">${s.codex_new}</td></tr>` +
      (open ? `<tr><td colspan="10" class="systems">${s.systems.map(x => `<span><span class="name" data-name="${esc(x.name)}" title="click to copy">${esc(x.name)}</span>` +
        `${x.kind === "CarrierJump" ? " 🚢" : x.kind === "Location" ? " ⟳" : ""} <span class="unk">${x.ts.slice(11, 16)}</span></span>`).join("")}</td></tr>` : "");
  }).join("") || `<tr><td colspan="10" class="unk">No jumps in this period.</td></tr>`;
}
document.getElementById("histRows").addEventListener("click", e => {
  const name = e.target.closest(".name"); if (name) return copyText(name.dataset.name);
  const tr = e.target.closest("tr.sess"); if (!tr) return;
  openSessions.has(tr.dataset.sess) ? openSessions.delete(tr.dataset.sess) : openSessions.add(tr.dataset.sess);
  renderHistory();
});

// ---- 3D map ----
const M = {data: null, key: null, loading: false, proj: [], hover: null, drag: null, panX: 0, panY: 0,
           yaw: -0.5, pitch: 0.45, zoom: 1};
const mEl = id => document.getElementById(id);
const mapCanvas = mEl("mapCanvas");
const mSettings = Object.assign({radius: "50", path: "100", color: "status", labels: true, stalks: true, boost: false},
                                store.get("map", {}));
mEl("mRadius").value = mSettings.radius; mEl("mPath").value = mSettings.path; mEl("mColor").value = mSettings.color;
mEl("mLabels").checked = mSettings.labels; mEl("mStalks").checked = mSettings.stalks; mEl("mBoost").checked = mSettings.boost;
for (const [id, key, prop] of [["mRadius", "radius", "value"], ["mPath", "path", "value"], ["mColor", "color", "value"],
                               ["mLabels", "labels", "checked"], ["mStalks", "stalks", "checked"], ["mBoost", "boost", "checked"]])
  mEl(id).onchange = () => { mSettings[key] = mEl(id)[prop]; store.set("map", mSettings); loadMap(); drawMap(); };
mEl("mTop").onclick = () => { M.yaw = 0; M.pitch = Math.PI / 2; M.panX = M.panY = 0; drawMap(); };
mEl("mReset").onclick = () => { M.yaw = -0.5; M.pitch = 0.45; M.zoom = 1; M.panX = M.panY = 0; drawMap(); };

async function loadMap() {
  const p = data && data.position; if (!p) return;
  const key = `${p.id64}|${mSettings.radius}|${mSettings.path}|${mSettings.boost ? 1 : 0}`;
  if (key === M.key) return;
  M.key = key; M.loading = true;
  mEl("mStatus").textContent = "loading…";
  try {
    const d = await apiJson(`api/map?radius=${mSettings.radius}&path=${mSettings.path}&boost=${mSettings.boost ? 1 : 0}`);
    if (M.key !== key) return;  // settings changed while we waited
    if (d.error) throw new Error(d.error);
    M.data = d;
    // a failed Spansh lookup (sphere or boost stars) is not cached by the server: ask again in a while
    if (d.partial) setTimeout(() => { if (M.key === key) { M.key = null; if (view === "map") { loadMap(); drawMap(); } } }, 30000);
    const nearestN = d.boost && d.boost.points.find(b => b.boost === "N");
    mEl("mStatus").innerHTML = d.error ? esc(d.error) :
      `${d.points.length.toLocaleString()} systems within ${d.radius} ly` + (d.note ? ` · ${esc(d.note)}` : "") +
      (d.boost && d.boost.error ? ` · <span class="err">${esc(d.boost.error)}</span>` : "") +
      (d.boost && !d.boost.error ? ` · <span class="boost">${d.boost.points.length} boost star${d.boost.points.length === 1 ? "" : "s"}` +
        (nearestN ? `, nearest neutron <span class="copy" data-name="${esc(nearestN.name)}" title="click to copy">${esc(nearestN.name)}</span> ${nearestN.distance} ly` : "") + `</span>` : "");
  } catch (err) { mEl("mStatus").textContent = "map failed: " + err.message; M.key = null; }
  M.loading = false; drawMap();
}

function starGroup(sc) {
  if (!sc) return null;
  if (/^(H|BH|SMBH|Supermassive)/.test(sc)) return "BH";
  if (sc === "TTS" || sc === "AeBe" || sc === "N") return sc;
  if (/^D/.test(sc)) return "D";
  if (/^W/.test(sc)) return "W";
  if (/^(MS|S)$/.test(sc)) return "S";
  if (/^C/.test(sc)) return "C";
  return sc[0];
}
const STAR_COLOURS = {O: "#9bb0ff", B: "#aabfff", A: "#d5e0ff", F: "#f8f7ff", G: "#fff1a0", K: "#ffc46b",
  M: "#ff7b54", L: "#c0662a", T: "#9a4f2e", Y: "#7a3d2a", D: "#e6f2ff", N: "#5ce1e6", BH: "#a060ff",
  W: "#7fd3ff", C: "#ff4f6d", S: "#ff9a70", TTS: "#ffb3a0", AeBe: "#d6b3ff"};
const STAR_NAMES = {O: "O", B: "B", A: "A", F: "F", G: "G", K: "K", M: "M", L: "L dwarf", T: "T dwarf",
  Y: "Y dwarf", D: "White dwarf", N: "Neutron", BH: "Black hole", W: "Wolf-Rayet", C: "Carbon",
  S: "MS/S-type", TTS: "T Tauri", AeBe: "Herbig Ae/Be"};

function drawMap() {
  if (view !== "map" || !M.data || M.data.error) return;
  const cs = getComputedStyle(document.documentElement), col = v => cs.getPropertyValue(v).trim();
  const C = {line: col("--line"), muted: col("--muted"), text: col("--text"), accent: col("--accent"),
             info: col("--info"), good: col("--good"), bg: col("--bg"), gold: "#f2c94c"};
  const byColour = mSettings.color === "star";
  // Legend first: its height is part of the sizing below (written after it, the first draw was sized wrong).
  const dot = (color, text, ring) => `<span><i class="${ring ? "ring" : ""}" style="background:${color};border-color:${color}"></i>${text}</span>`;
  const legend = byColour
    ? [...new Set(M.data.points.map(pt => starGroup(pt.star)).concat((M.data.path || []).map(j => starGroup(j.star_class))))]
        .filter(Boolean).sort().map(k => dot(STAR_COLOURS[k] || C.muted, STAR_NAMES[k] || k)).join("") +
      dot(C.muted, "class unknown", true)
    : [dot(C.accent, "you are here"), dot(C.gold, "you discovered it"), dot(C.info, "visited"),
       dot(C.muted, "known, has bodies"), dot(C.muted, "no scan data", true),
       dot(C.text, "your route plots only", true), `<span style="color:${C.accent}">— your path</span>`,
       `<span style="color:${C.accent}">◌ previous / target</span>`, `<span style="color:${C.gold}">★ bookmark</span>`]
       .concat(M.data.boost ? [`<span style="color:#5ce1e6">▵ neutron · □ white dwarf · ┄ boosted range</span>`] : []).join("");
  if (M.legend !== legend) { M.legend = legend; mEl("mLegend").innerHTML = legend; }   // not on every drag frame
  const dpr = window.devicePixelRatio || 1;
  const w = mEl("mapWrap").clientWidth;
  // fill the window down to the legend and hint beneath it (measured, since the legend's length varies)
  const top = mapCanvas.getBoundingClientRect().top + scrollY;
  const below = [mEl("mLegend"), mapCanvas.closest("section").querySelector(".hint")]
    .reduce((n, el) => n + (el ? el.offsetHeight + (parseFloat(getComputedStyle(el).marginTop) || 0) : 0), 0);
  const sizeKey = `${innerHeight}|${Math.round(top)}|${below}|${w}`;
  if (M.sizeKey !== sizeKey) {   // only when the window or what is around the map changed (not on every drag frame)
    M.sizeKey = sizeKey;
    M.h = Math.max(360, Math.floor(innerHeight - top - below - 4));
    mapCanvas.style.height = M.h + "px";
    // whatever padding sits below the map (the page's own) still makes it scroll: take exactly that off
    const over = document.documentElement.scrollHeight - innerHeight;
    if (over > 0) { M.h = Math.max(360, M.h - over); mapCanvas.style.height = M.h + "px"; }
  }
  const h = M.h;
  if (mapCanvas.width !== Math.round(w * dpr) || mapCanvas.height !== Math.round(h * dpr)) {
    mapCanvas.width = Math.round(w * dpr); mapCanvas.height = Math.round(h * dpr);
  }
  const g = mapCanvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);

  const d = M.data, c = d.center, R = d.radius;
  const scale = Math.min(w, h) / 2 / (R * 1.1) * M.zoom, D = R * 4;
  const cy = Math.cos(M.yaw), sy = Math.sin(M.yaw), cp = Math.cos(M.pitch), sp = Math.sin(M.pitch);
  // Elite axes: x right, y up out of the galactic plane, z toward the core.
  const proj = (x, y, z) => {
    const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
    const y2 = y * cp + z1 * sp, depth = z1 * cp - y * sp;
    const k = D / (D + depth);
    return {sx: w / 2 + M.panX + x1 * scale * k, sy: h / 2 + M.panY - y2 * scale * k, depth, k, ok: D + depth > D * 0.05};
  };
  const rel = pt => [pt.x - c.x, pt.y - c.y, pt.z - c.z];
  const line = (a, b) => { if (a.ok && b.ok) { g.moveTo(a.sx, a.sy); g.lineTo(b.sx, b.sy); } };

  // Galactic-plane grid through your position.
  const step = R <= 50 ? 10 : R <= 100 ? 25 : 50;
  g.strokeStyle = C.line; g.lineWidth = 1; g.beginPath();
  for (let r = step; r <= R + 0.01; r += step)
    for (let i = 0; i < 96; i++) {
      const a0 = i / 96 * 2 * Math.PI, a1 = (i + 1) / 96 * 2 * Math.PI;
      line(proj(r * Math.cos(a0), 0, r * Math.sin(a0)), proj(r * Math.cos(a1), 0, r * Math.sin(a1)));
    }
  line(proj(-R, 0, 0), proj(R, 0, 0)); line(proj(0, 0, -R), proj(0, 0, R));
  g.stroke();
  g.font = "11px system-ui, sans-serif"; g.fillStyle = C.muted;
  for (let r = step; r <= R + 0.01; r += step) { const q = proj(r, 0, 0); if (q.ok) g.fillText(`${r} ly`, q.sx + 3, q.sy - 3); }
  const lbl = (x, z, text) => {
    const q = proj(x, 0, z); if (!q.ok) return;
    const tw = g.measureText(text).width;
    g.fillText(text, Math.max(4, Math.min(w - tw - 4, q.sx - tw / 2)), Math.max(14, Math.min(h - 6, q.sy)));
  };
  const kx = 25.21875 - c.x, kz = 25899.96875 - c.z, kn = Math.hypot(kx, kz) || 1;  // Sagittarius A*
  g.fillStyle = C.text; lbl(kx / kn * R * 1.08, kz / kn * R * 1.08, "▲ core");
  const sol = Math.hypot(c.x, c.z);
  if (sol > 1) lbl(-c.x / sol * R * 1.08, -c.z / sol * R * 1.08, `Sol ${Math.round(Math.hypot(c.x, c.y, c.z)).toLocaleString()} ly`);
  const jr = data && data.jump_range;
  const ringAt = (radius, color, dash) => {
    if (!radius || radius > R * 1.6) return;
    g.strokeStyle = color; g.setLineDash(dash); g.globalAlpha = .6; g.beginPath();
    for (let i = 0; i < 96; i++) {
      const a0 = i / 96 * 2 * Math.PI, a1 = (i + 1) / 96 * 2 * Math.PI;
      line(proj(radius * Math.cos(a0), 0, radius * Math.sin(a0)), proj(radius * Math.cos(a1), 0, radius * Math.sin(a1)));
    }
    g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
  };
  ringAt(jr, C.accent, [4, 4]);
  if (data && data.boost) ringAt(jr * data.boost, "#5ce1e6", [2, 3]);   // charged: this jump's real reach
  // Boosted range from here: neutron cone ×4, white dwarf ×1.5.
  const hs = d.here_star, mult = hs === "N" ? 4 : /^D/.test(hs || "") ? 1.5 : 0;
  if (jr && mult) ringAt(jr * mult, "#5ce1e6", [2, 6]);

  // exact string ids (id), as the points carry: an id64 over 2^53 is rounded as a JavaScript number
  const sid = x => x && (x.id ?? String(x.id64));
  const bms = bmMap(), prevId = sid(data.previous), targetId = sid(data.target), hereId = sid(c);
  const pts = d.points.map(pt => ({pt, ...proj(...rel(pt))})).filter(q => q.ok);
  // Busy regions fade the background systems so your own stand out.
  const density = Math.min(1, 150 / Math.max(1, pts.length));

  // Path first, underneath the systems.
  M.proj = [];
  const labels = [];
  if (d.path && d.path.length) {
    const pp = d.path.map(j => ({j, ...proj(...rel(j))}));
    g.strokeStyle = C.accent; g.lineWidth = 1.5; g.globalAlpha = .75; g.beginPath();
    for (let i = 1; i < pp.length; i++) if (pp[i].j.kind !== "Location") line(pp[i - 1], pp[i]);
    g.stroke(); g.globalAlpha = 1;
    const inView = new Set(d.points.map(pt => pt.id));
    for (const q of pp) {
      if (!q.ok || inView.has(q.j.id)) continue;
      g.fillStyle = byColour ? (STAR_COLOURS[starGroup(q.j.star_class)] || C.muted) : C.accent;
      g.beginPath(); g.arc(q.sx, q.sy, 2.2, 0, 2 * Math.PI); g.fill();
      M.proj.push({sx: q.sx, sy: q.sy, pt: {name: q.j.name, id: q.j.id, star: q.j.star_class, x: q.j.x, y: q.j.y, z: q.j.z,
                                            visited: true, arrived: q.j.ts, path: true}});
    }
  }

  // Boost stars (neutron / white dwarf arrival stars) and your carrier.
  const boostOf = {};
  if (d.boost) for (const b of d.boost.points) boostOf[b.id] = b.boost;
  if (d.boost) for (const b of d.boost.points) {
    const q = proj(...rel(b)); if (!q.ok) continue;
    g.strokeStyle = "#5ce1e6"; g.lineWidth = 1.5; g.beginPath();
    if (b.boost === "N") { g.moveTo(q.sx, q.sy - 6); g.lineTo(q.sx + 5, q.sy + 4); g.lineTo(q.sx - 5, q.sy + 4); g.closePath(); }
    else g.rect(q.sx - 4, q.sy - 4, 8, 8);
    g.stroke();
    if (!d.points.some(pt => pt.id === b.id))   // a system dot of its own carries the popup otherwise
      M.proj.push({sx: q.sx, sy: q.sy, pt: {name: b.name, id: b.id, x: b.x, y: b.y, z: b.z, boost: b.boost}});
  }
  const cr = data.carrier || d.carrier;   // the live one: it may have jumped since the map was fetched
  let carrierAt = null;
  if (cr && cr.x != null && !cr.here) {
    const q = proj(...rel(cr));
    if (q.ok) {
      g.fillStyle = C.gold; g.font = "14px system-ui"; g.fillText("🚢", q.sx - 7, q.sy + 5);
      carrierAt = String(cr.id64);
      if (!d.points.some(pt => pt.id === carrierAt))   // otherwise the system's own dot carries the popup
        M.proj.push({sx: q.sx, sy: q.sy, pt: {name: cr.system, id: cr.id64, x: cr.x, y: cr.y, z: cr.z, carrier: cr.name}});
      if (mSettings.labels) labels.push([q, `${cr.name} (carrier)`]);
    }
  }
  // Stalks down to the plane.
  if (mSettings.stalks && Math.abs(M.pitch) < 1.35) {  // from straight above they only point outward
    g.strokeStyle = C.muted; g.globalAlpha = .06 + .3 * density; g.lineWidth = 1; g.beginPath();
    for (const q of pts) { const [x, , z] = rel(q.pt); line(q, proj(x, 0, z)); }
    g.stroke(); g.globalAlpha = 1;
  }

  pts.sort((a, b) => b.depth - a.depth);
  for (const q of pts) {
    const pt = q.pt, id = pt.id, r0 = Math.max(1.6, 3 * q.k);
    let fill, ring = false, r = r0;
    if (byColour) { fill = STAR_COLOURS[starGroup(pt.star)] || C.muted; if (!pt.star) ring = true; }
    else if (pt.first) { fill = C.gold; r = r0 * 1.3; }
    else if (pt.visited) { fill = C.info; r = r0 * 1.15; }
    else if (pt.kind === "route") { fill = C.text; ring = true; }
    else { fill = C.muted; ring = !pt.scanned; r = r0 * .8; }
    if (id === hereId) { fill = C.accent; ring = false; r = 7; }
    g.globalAlpha = pt.visited || id === hereId ? 1 : byColour ? .5 + .5 * density : .35 + .5 * density;
    g.beginPath(); g.arc(q.sx, q.sy, r, 0, 2 * Math.PI);
    if (ring) { g.strokeStyle = fill; g.lineWidth = 1.3; g.stroke(); } else { g.fillStyle = fill; g.fill(); }
    g.globalAlpha = 1;
    if (id === prevId || id === targetId) {
      g.strokeStyle = C.accent; g.lineWidth = 1.5; if (id === targetId) g.setLineDash([3, 3]);
      g.beginPath(); g.arc(q.sx, q.sy, r + 4, 0, 2 * Math.PI); g.stroke(); g.setLineDash([]);
    }
    if (bms[id]) { g.fillStyle = C.gold; g.font = "12px system-ui"; g.fillText("★", q.sx + r + 1, q.sy - r); }
    M.proj.push({sx: q.sx, sy: q.sy, pt: boostOf[id] || id === carrierAt ? {...pt, boost: boostOf[id], carrier: id === carrierAt ? cr.name : undefined} : pt});
    if (mSettings.labels && (id === hereId || id === prevId || id === targetId || bms[id]))
      labels.push([q, pt.name + (id === prevId ? " (previous)" : id === targetId ? " (target)" : "")]);
  }
  if (M.hover) labels.push([M.hover, M.hover.pt.name]);
  g.font = "12px system-ui, sans-serif";
  const placed = [];
  for (const [q, text] of labels) {
    const tw = g.measureText(text).width + 6;
    let x = q.sx + 8, y = q.sy - 16;
    for (const dy of [0, 16, -16, 32, -32, 48]) {  // nudge until it doesn't sit on another label
      const yy = q.sy - 16 + dy;
      if (!placed.some(b => x < b.x + b.w && b.x < x + tw && yy < b.y + 15 && b.y < yy + 15)) { y = yy; break; }
    }
    placed.push({x, y, w: tw});
    if (y !== q.sy - 16) { g.strokeStyle = C.muted; g.beginPath(); g.moveTo(q.sx, q.sy); g.lineTo(x, y + 8); g.stroke(); }
    g.fillStyle = C.bg; g.globalAlpha = .75; g.fillRect(x, y, tw, 15); g.globalAlpha = 1;
    g.fillStyle = C.text; g.fillText(text, x + 3, y + 11);
  }
}

function mapHit(e) {
  const b = mapCanvas.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
  let best = null, bd = 100;
  for (const q of M.proj) { const dd = (q.sx - x) ** 2 + (q.sy - y) ** 2; if (dd < bd) { bd = dd; best = q; } }
  return best;
}
function mapPopHtml(pt) {
  const c = M.data.center, dd = Math.hypot(pt.x - c.x, pt.y - c.y, pt.z - c.z);
  const boost = pt.boost ? (pt.boost === "N" ? "neutron star: jet-cone boost ×4" : "white dwarf: jet-cone boost ×1.5") : "";
  const what = (c.id ?? String(c.id64)) === pt.id ? "you are here" : pt.first ? "you discovered it" : pt.visited ? "visited"
    : pt.kind === "route" ? "only in your route plots" : pt.scanned ? "known, has scanned bodies"
    : pt.kind === undefined ? (pt.carrier ? `your carrier ${esc(pt.carrier)} is here` : boost) : "no scan data";
  const what2 = what + (pt.carrier && !what.includes("carrier") ? ` · your carrier ${esc(pt.carrier)} is here` : "") + (boost && what !== boost ? " · " + boost : "");
  const b = bmMap()[pt.id];
  return `<h3>${esc(pt.name)}</h3><div>${dd.toFixed(2)} ly away · ${what2}</div>` +
    (pt.star ? `<div>main star: <span class="mono">${esc(pt.star)}</span></div>` : "") +
    (pt.arrived ? `<div class="unk">on your path: arrived ${esc(pt.arrived.replace("T", " ").replace("Z", ""))}</div>` : "") +
    (b ? `<div class="sec">★ ${esc(b.note) || "bookmarked"}</div>` : "") + `<div class="sec unk">click to copy name</div>`;
}
// left drag rotates; right (or middle) drag moves the picture; the wheel zooms
mapCanvas.addEventListener("contextmenu", e => e.preventDefault());
mapCanvas.addEventListener("pointerdown", e => {
  M.drag = {x: e.clientX, y: e.clientY, yaw: M.yaw, pitch: M.pitch, panX: M.panX, panY: M.panY,
            pan: e.button === 2 || e.button === 1, moved: false};
  if (M.drag.pan) e.preventDefault();
  mapCanvas.setPointerCapture(e.pointerId); mapCanvas.classList.add("dragging");
});
mapCanvas.addEventListener("pointermove", e => {
  if (M.drag) {
    const dx = e.clientX - M.drag.x, dy = e.clientY - M.drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) M.drag.moved = true;
    if (M.drag.pan) { M.panX = M.drag.panX + dx; M.panY = M.drag.panY + dy; }
    else {
      M.yaw = M.drag.yaw + dx * 0.008;
      M.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, M.drag.pitch + dy * 0.008));
    }
    hidePop(); M.hover = null; drawMap(); return;
  }
  const q = mapHit(e);
  if ((q && q.pt) !== (M.hover && M.hover.pt)) { M.hover = q; drawMap(); }
  if (q) { popId = "map"; pop.innerHTML = mapPopHtml(q.pt); pop.style.display = "block"; placePop(e.clientX, e.clientY); }
  else if (popId === "map") hidePop();
});
mapCanvas.addEventListener("pointerup", e => {
  const click = M.drag && !M.drag.moved && !M.drag.pan; M.drag = null; mapCanvas.classList.remove("dragging");
  if (click) { const q = mapHit(e); if (q) copyText(q.pt.name); }
});
mapCanvas.addEventListener("pointerleave", () => { if (!M.drag) { M.hover = null; if (popId === "map") hidePop(); drawMap(); } });
mapCanvas.addEventListener("wheel", e => {
  e.preventDefault(); M.zoom = Math.max(0.2, Math.min(12, M.zoom * Math.exp(-e.deltaY * 0.0015))); drawMap();
}, {passive: false});
addEventListener("resize", () => drawMap());

// ---- Search ----
const OPTS = window.__SEARCH_OPTIONS__;
const sForm = document.getElementById("searchForm");
const box = (group, value, label) =>
  `<label><input type="checkbox" data-group="${group}" value="${esc(value)}"> ${esc(label)}</label>`;
document.getElementById("sScoopOpts").innerHTML = OPTS.scoopable.map(k => box("stars", k, k)).join("");
document.getElementById("sOtherStars").innerHTML = OPTS.other_stars.map(([k, l]) => box("stars", k, l)).join("");
document.getElementById("sPlanets").innerHTML = OPTS.planets.map(t => box("planets", t, t)).join("");
document.getElementById("sRings").innerHTML = OPTS.rings.map(t => box("rings", t, t)).join("");
document.getElementById("sHotspots").innerHTML = OPTS.hotspots.map(t => box("hotspots", t, t)).join("");
document.getElementById("sBio").innerHTML = (OPTS.bio || []).map(([k, l]) => box("bio", k, l)).join("");
const sScoop = document.getElementById("sScoop");
const scoopBoxes = () => [...document.querySelectorAll("#sScoopOpts input")];
function syncScoop() {
  const n = scoopBoxes().filter(b => b.checked).length;
  sScoop.checked = n === OPTS.scoopable.length; sScoop.indeterminate = n > 0 && n < OPTS.scoopable.length;
}
sScoop.onchange = () => { scoopBoxes().forEach(b => b.checked = sScoop.checked); saveForm(); };
document.getElementById("sScoopOpts").addEventListener("change", syncScoop);

function formParams() {
  const ticked = g => [...sForm.querySelectorAll(`input[data-group="${g}"]:checked`)].map(b => b.value);
  return {
    source: sForm.querySelector("input[name=sSource]:checked").value,
    radius: parseFloat(document.getElementById("sRadius").value) || 100,
    main_only: document.getElementById("sMainOnly").checked,
    stars: ticked("stars"), planets: ticked("planets"), rings: ticked("rings"), hotspots: ticked("hotspots"), bio: ticked("bio"),
  };
}
function loadForm(p) {
  if (!p) return;
  document.getElementById("sRadius").value = p.radius ?? 100;
  const src = sForm.querySelector(`input[name=sSource][value="${p.source}"]`); if (src) src.checked = true;
  document.getElementById("sMainOnly").checked = p.main_only ?? true;
  for (const g of ["stars", "planets", "rings", "hotspots", "bio"])
    sForm.querySelectorAll(`input[data-group="${g}"]`).forEach(b => b.checked = (p[g] || []).includes(b.value));
  syncScoop();
}
function saveForm() { store.set("search", formParams()); }
sForm.addEventListener("change", saveForm);
document.getElementById("sClear").onclick = () => {
  sForm.querySelectorAll("input[data-group]").forEach(b => b.checked = false); syncScoop(); saveForm();
};
loadForm(store.get("search", null));

let search = null, searchPolling = false;
// The seq the server gave the last search started here: an older result (a GET sent before that POST) is not it.
let searchWant = 0;
// set by a refused search POST: a poll loop still running for the previous search must not paint its progress
// (or its results) over the "search failed" line. Cleared by the next accepted search.
let searchRefused = false;
const sLabels = {stars: "Star", planets: "Planet", rings: "Ring", hotspots: "Hotspot", bio: "Bio"};
// ---- Search results: body pop-ups and a body panel beside the results ----
const sysDetail = {};   // id64 -> system detail (or a pending promise), for the pop-ups
const sysRetryAt = {};  // id64 -> when an error, partial or empty answer may be asked for again
function sysCached(id) {   // what is known now; an incomplete answer is dropped once it is due a retry
  if (sysRetryAt[id] && Date.now() >= sysRetryAt[id] && !(sysDetail[id] instanceof Promise)) { delete sysDetail[id]; delete sysRetryAt[id]; }
  return sysDetail[id];
}
function systemFor(id) {
  if (!sysCached(id)) sysDetail[id] = apiJson(`api/system/${id}`).catch(err => ({error: err.message})).then(d => {
    // a Spansh timeout, bodies still arriving or none known yet: shown now, asked again on a later hover
    if (!d || d.error || d.partial || !(d.bodies || []).length) sysRetryAt[id] = Date.now() + 15000; else delete sysRetryAt[id];
    return (sysDetail[id] = d);
  });
  return sysDetail[id];
}
const sBody = {sys: null, name: null, data: null};
async function openSearchBody(sys, name) {
  if (sBody.sys === sys && sBody.name === name) return closeSearchBody();
  Object.assign(sBody, {sys, name, data: null}); hidePop();
  const panel = document.getElementById("sBodyPanel");
  panel.hidden = false; panel.innerHTML = `<h3><b>${esc(name)}</b> <button type="button" onclick="closeSearchBody()">✕</button></h3><div class="unk">loading…</div>`;
  document.getElementById("sMain").classList.add("detail");
  renderSearch();
  await systemFor(sys);   // makes sure the server has the system's bodies before asking for one
  let d;
  try { d = await apiJson(`api/body?system=${sys}&name=${encodeURIComponent(name)}`); } catch (err) { d = {error: err.message}; }
  if (sBody.sys !== sys || sBody.name !== name) return;
  sBody.data = d; renderBodyInto(panel, d, name, "closeSearchBody()");
}
function closeSearchBody() {
  Object.assign(sBody, {sys: null, name: null, data: null});
  document.getElementById("sBodyPanel").hidden = true; document.getElementById("sMain").classList.remove("detail");
  renderSearch();
}
const hitHtml = (h, sys) => typeof h === "string" ? esc(h)
  : `<span class="shit${sBody.sys === sys && sBody.name === h.body ? " sel" : ""}" data-sbodypop="${esc(h.body)}" data-sys="${esc(sys)}">${esc(h.t)}</span>`;
document.getElementById("sRows").addEventListener("click", e => {
  const h = e.target.closest("[data-sbodypop]"); if (h) openSearchBody(h.dataset.sys, h.dataset.sbodypop);
});

function renderSearch(bms) {
  const st = document.getElementById("sStatus"), table = document.getElementById("sTable");
  if (!search) { st.textContent = ""; table.hidden = true; return; }
  st.innerHTML = esc(search.status) + (search.sparse && !search.running
    ? ` <button type="button" id="sOnline" class="go" style="margin-left:8px">Search Spansh (online) instead</button>` : "");
  st.classList.toggle("busy", !!search.running);
  const ob = document.getElementById("sOnline");
  if (ob) ob.onclick = () => { sForm.querySelector('input[name=sSource][value=spansh]').checked = true; saveForm(); sForm.requestSubmit(); };
  const rows = [...(search.results || [])];
  table.hidden = !rows.length;
  rows.sort(sortKeys.search === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
    : (a, b) => a.distance - b.distance);
  document.getElementById("sRows").innerHTML = rows.map(r => `<tr>
      <td class="bmcell">${bmIcon(r.id, r.name, bms || bmMap())}</td>
      <td class="name" data-name="${esc(r.name)}" title="click to copy">${esc(r.name)}${firstsIcon(r.firsts)}${r.visited
        ? `<span class="badge s-visited">visited</span>` : ""}</td>
      <td class="num dist">${r.distance.toFixed(2)}</td>
      <td class="matches">${Object.entries(r.matches).map(([k, hits]) =>
        `<div><span class="mlbl">${sLabels[k] || k}</span>${hits.map(h => hitHtml(h, r.id)).join("; ")}</div>`).join("")}</td></tr>`).join("");
}
async function pollSearch() {
  if (searchPolling) return;
  searchPolling = true;
  // A failed poll (server restarting, a dropped connection) is retried with a growing pause; after a few
  // the search is shown as stopped instead of 'searching…' forever.
  let fails = 0, stale = 0;
  try {
    for (;;) {
      try {
        const r = await fetch("api/search");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const got = await r.json(); fails = 0;
        if (searchRefused) return;
        if (got && (got.seq || 0) < searchWant) {
          // the previous search, from a poll sent before the new one started: keep waiting, never show it as new.
          // Only ever one or two of these; many means the server restarted and forgot the search.
          if (++stale >= 8) { search = {running: false, status: "lost track of the search (the server restarted?)", results: []}; render(); return; }
          await new Promise(res => setTimeout(res, 800));
          continue;
        }
        search = got; stale = 0;   // a resubmit's one stale answer each must not add up across a long search
        render();
        if (!search || !search.running) return;
        await new Promise(res => setTimeout(res, 800));
      } catch (err) {
        if (!search || !search.running) return;   // nothing in progress (e.g. the first poll after a reload)
        if (++fails >= 5) { search = Object.assign({}, search, {running: false, status: "lost track of the search: " + err.message}); render(); return; }
        await new Promise(res => setTimeout(res, 1000 * 2 ** fails));
      }
    }
  } finally { searchPolling = false; }
}
sForm.addEventListener("submit", async e => {
  e.preventDefault(); saveForm();
  search = {running: true, status: "searching…", results: []}; render();
  for (const id of Object.keys(sysDetail)) if (!(sysDetail[id] instanceof Promise)) delete sysDetail[id];   // bodies may have been scanned since
  let r;
  try {
    r = await apiJson("api/search", {method: "POST", headers: {"Content-Type": "application/json"},
                                     body: JSON.stringify(formParams())});
  } catch (err) { r = {error: err.message}; }
  // A refused search (403 through a proxy, 400, 500) must say so, not fall back to showing the previous results.
  if (!r || r.error) { searchRefused = true; search = {running: false, status: "search failed: " + ((r && r.error) || "no answer"), results: []}; render(); return; }
  searchRefused = false;
  searchWant = r.seq || 0;
  pollSearch();
});
pollSearch();  // show the last search's results after a reload

document.querySelectorAll("th[data-sort]").forEach(b => b.onclick = () => {
  const t = SORT_TABLES[b.closest("table").id]; if (!t) return;
  sortKeys[t] = b.dataset.sort; store.set("sorts", sortKeys);
  if (t === "firsts") renderFirsts();
  render();
});
const oneJump = document.getElementById("oneJump");
oneJump.checked = store.get("oneJump", false);
[showVisited, showExplored, oneJump].forEach(c => c.onchange = () => { store.set(c.id, c.checked); render(); });
// Click a system name (list rows or the current system in the header) to copy it.
function toast(msg) {
  const t = document.getElementById("toast"); t.textContent = msg;
  t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1400);
}
function copyText(text, what = text) {   // `what`: the toast's name for it (a long text is not repeated)
  const fallback = () => {
    try {
      const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy"); ta.remove();
      toast(ok ? "copied " + what : "copy failed — select the name and copy it by hand");
    } catch { toast("copy failed — select the name and copy it by hand"); }
  };
  if (navigator.clipboard && navigator.clipboard.writeText)
    navigator.clipboard.writeText(text).then(() => toast("copied " + what), fallback);
  else fallback();  // http:// from another machine is not a secure context
}
document.addEventListener("click", e => {
  if (e.target.closest("[data-lossclose]")) { e.preventDefault(); lossCard = null; return renderStrip(); }
  if (e.target.closest("[data-lossfirsts]")) {   // the systems to rescan: My firsts with the lost ones shown
    e.preventDefault(); fShowLost.checked = true; store.set("fShowLost", true);
    return document.querySelector('[data-view="firsts"]').click();
  }
  const cell = e.target.closest("#rows td.bodies[data-id]");
  if (cell) return cell.dataset.id === pinnedSystem ? unpinSystem() : pinSystem(cell.dataset.id);  // same system again closes it
  const bm = e.target.closest("[data-bm]");
  if (bm) return openBookmark(bm.dataset.bm, bm.dataset.name);
  // every "click to copy" name outside the views that handle their own (.name spans in Log, Bio, History,
  // Ledger and Materials); an element without data-name copies nothing (it used to copy "undefined")
  const el = e.target.closest("td.name[data-name], .copy[data-name], #topRows .name[data-name]"); if (!el) return;
  copyText(el.dataset.name);
});

const pop = document.getElementById("pop");
const list = (title, obj) => {
  const e = Object.entries(obj || {});
  if (!e.length) return "";
  const total = e.reduce((n, [, v]) => n + v, 0);
  return `<div class="sec"><div class="lbl">${title} (${total})</div><ul>` +
    e.map(([k, v]) => `<li><span>${esc(k)}</span><b>${v}</b></li>`).join("") + `</ul></div>`;
};
function ringList(d) {
  const e = Object.entries(d.rings || {});
  const rb = d.ring_bodies || {};
  if (!e.length) return "";
  const total = e.reduce((n, [, v]) => n + v, 0);
  return `<div class="sec"><div class="lbl">Rings (${total})</div><ul>` + e.map(([k, v]) =>
    `<li><span>${esc(k)}${rb[k] ? ` <span class="bn">(${rb[k].map(esc).join(", ")})</span>` : ""}</span>` +
    `<b>${v}</b></li>`).join("") + `</ul></div>`;
}
const mineral = k => k.replace(/([a-z])([A-Z])/g, "$1 $2");
function hotspotList(d) {
  if (!d.ring_count) return "";
  if (!d.hotspots.length) return `<div class="sec"><div class="lbl">Ring hotspots</div>` +
    `<div class="unk">none of the ${d.ring_count} ring${d.ring_count > 1 ? "s" : ""} mapped yet</div></div>`;
  return `<div class="sec"><div class="lbl">Ring hotspots (${d.rings_mapped} of ${d.ring_count} rings mapped)</div><ul>` +
    d.hotspots.map(h => `<li><span>${esc(h.ring)} <span class="bn">(${esc(h.type)})</span>` +
      `<span class="hs">${Object.entries(h.minerals).map(([k, v]) => `${esc(mineral(k))} ${v}`).join(" · ")}</span>` +
      `</span></li>`).join("") + `</ul></div>`;
}
// curiosities as a list: [{body?, tag, why}]
const curiosityList = (items, withBody) => !(items || []).length ? "" :
  `<div class="sec"><div class="lbl">🔭 Curiosities</div><ul>${items.map(c => `<li><span>${withBody ? `<b>${esc(c.body)}</b> ` : ""}<b>${esc(c.tag)}</b> · ${esc(c.why)}</span></li>`).join("")}</ul></div>`;
function popHtml(s) {
  const src = s.source === "own" ? "not in Spansh · your scans" : s.own_scans ? "Spansh + your scans" : "";
  let h = `<h3>${esc(s.name)}${src ? ` <span class="src">${src}</span>` : ""}</h3>`;
  if (!s.bodies_known) return h + `<div class="unk">No bodies known yet.</div>`;
  h += `<div>${s.body_count ? `${s.bodies_known} of ${s.body_count} bodies known`
                             : `${s.bodies_known} bod${s.bodies_known > 1 ? "ies" : "y"} known, total unknown (no FSS honk reported)`}</div>`;
  h += firstsHtml(s.firsts) + list("Stars", s.star_types) + list("Planets", s.planet_types);
  h += curiosityList(s.curiosity_list, true);
  if (s.bio_potential) h += `<div class="sec"><div class="lbl">🧬 Exobiology</div><div>up to ${credits(s.bio_potential)} cr across ${s.bio_bodies_guessed} bod${s.bio_bodies_guessed === 1 ? "y" : "ies"} <span class="unk">(spawn-rule estimate; the Here view shows which genera)</span></div></div>`;
  const d = s.detail;
  if (!d) return h + `<div class="sec unk">${s.no_dump ? "Spansh has no ring, belt or signal details for this system." : "Loading ring, belt and signal details…"}</div>`;
  h += list("Ringed planets", d.ringed_types) + ringList(d) + hotspotList(d) + list("Asteroid belts", d.belts);
  const flags = [
    d.ringed_stars && `${d.ringed_stars} ringed star${d.ringed_stars > 1 ? "s" : ""}`,
    s.planets && `${d.landable} landable`,
    s.terraformable && `${s.terraformable} terraformable`,
    d.bio && `${d.bio} bio signal${d.bio > 1 ? "s" : ""} on ${d.bio_bodies} bod${d.bio_bodies > 1 ? "ies" : "y"}`,
    d.geo && `${d.geo} geo signal${d.geo > 1 ? "s" : ""} on ${d.geo_bodies} bod${d.geo_bodies > 1 ? "ies" : "y"}`,
  ].filter(Boolean);
  return h + `<div class="flags">${flags.map(f => `<span>${f}</span>`).join("")}</div>`;
}
let popId = null;
function placePop(x, y) {
  const r = pop.getBoundingClientRect(), pad = 14;
  let left = x + pad, top = y + pad;
  if (left + r.width > innerWidth - 8) left = Math.max(8, x - r.width - pad);
  if (top + r.height > innerHeight - 8) top = Math.max(8, y - r.height - pad);
  pop.style.left = left + "px"; pop.style.top = top + "px";
}
function showPop(td, x, y) {
  if (td.dataset.unsold !== undefined) {
    const h = data && unsoldHtml(data.unsold);
    if (!h) return hidePop();
    popId = "unsold"; pop.innerHTML = h; pop.style.display = "block"; placePop(x, y);
    return;
  }
  if (td.dataset.sbodypop !== undefined) {   // a body in a search result: its system may still be loading
    const key = "sbody" + td.dataset.sys + "|" + td.dataset.sbodypop, sd = sysCached(td.dataset.sys);
    popId = key;
    if (!sd || sd instanceof Promise) {
      pop.innerHTML = `<div class="unk">loading ${esc(td.dataset.sbodypop)}…</div>`; pop.style.display = "block"; placePop(x, y);
      systemFor(td.dataset.sys).then(() => { if (popId === key) showPop(td, x, y); });
      return;
    }
    const b = sd.bodies && sd.bodies.find(q => q.name === td.dataset.sbodypop);
    if (!b) { pop.innerHTML = `<div class="unk">${esc(sd.error || "no details known for this body")}</div>`; pop.style.display = "block"; placePop(x, y); return; }
    pop.innerHTML = bodyPopHtml(b, sd.region).replace("click for everything known", "click for the details panel"); pop.style.display = "block"; placePop(x, y);
    return;
  }
  if (td.dataset.bodypop !== undefined) {
    const b = hereData && hereData.bodies && hereData.bodies.find(x => x.name === td.dataset.bodypop);
    if (!b) return hidePop();
    popId = "body" + td.dataset.bodypop; pop.innerHTML = bodyPopHtml(b, hereData.region); pop.style.display = "block"; placePop(x, y);
    return;
  }
  if (td.dataset.bm !== undefined) {
    const b = data && bmMap()[td.dataset.bm];
    if (!b) return hidePop();
    popId = "bm" + td.dataset.bm;
    pop.innerHTML = `<h3>★ ${esc(b.name)}</h3><div class="note">${esc(b.note) || `<span class="unk">no note</span>`}</div>` +
      `<div class="sec unk">saved ${esc((b.created || "").slice(0, 10))} · click to edit</div>`;
    pop.style.display = "block"; placePop(x, y);
    return;
  }
  const s = data && data.systems.find(s => s.id === td.dataset.id);
  if (!s) return hidePop();
  popId = td.dataset.id;
  pop.innerHTML = popHtml(s); pop.style.display = "block"; placePop(x, y);
}
function hidePop() { popId = null; pop.style.display = "none"; }
let lastPointer = null;
document.addEventListener("mousemove", e => {
  if (e.target === mapCanvas) return;  // the map draws its own hover
  lastPointer = {x: e.clientX, y: e.clientY};
  const td = e.target.closest("[data-pop], [data-bm], [data-unsold], [data-bodypop], [data-sbodypop]");
  td ? showPop(td, e.clientX, e.clientY) : popId !== null && hidePop();
});
function refreshPop() {
  // render() has just rebuilt the DOM: re-resolve whatever the pointer is over.
  if (popId === null || popId === "map" || !lastPointer) return;
  const el = document.elementFromPoint(lastPointer.x, lastPointer.y);
  const td = el && el.closest && el.closest("[data-pop], [data-bm], [data-unsold], [data-bodypop], [data-sbodypop]");
  td ? showPop(td, lastPointer.x, lastPointer.y) : hidePop();
}
document.addEventListener("mouseleave", hidePop);
// Touch: tap the bodies cell to toggle.
document.addEventListener("touchstart", e => {
  if (e.target.closest("[data-bm]")) return;  // taps on a star open the bookmark dialog
  const td = e.target.closest("[data-pop], [data-unsold], [data-bodypop], [data-sbodypop]"); if (!td) return hidePop();
  const t = e.touches[0];
  const key = td.dataset.unsold !== undefined ? "unsold" : td.dataset.sbodypop !== undefined ? "sbody" + td.dataset.sys + "|" + td.dataset.sbodypop
    : td.dataset.bodypop !== undefined ? "body" + td.dataset.bodypop : td.dataset.id;
  popId === key ? hidePop() : showPop(td, t.clientX, t.clientY);
}, {passive: true});

// ---- Sounds, synthesized so there are no files to ship ----
let actx = null, soundOn = store.get("sound", null), lastSeq = null;
const soundBtn = document.getElementById("sound");
function audio() {
  if (!actx) { try { actx = new AudioContext(); } catch { return null; } }
  if (actx.state === "suspended") actx.resume();
  return actx;
}
function tone(ctx, out, freq, start, dur, {type = "triangle", vol = .3, attack = .01, glideTo = null} = {}) {
  const o = ctx.createOscillator(), g = ctx.createGain(), t0 = ctx.currentTime + start;
  o.type = type; o.frequency.setValueAtTime(freq, t0);
  if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, t0 + dur);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(vol, t0 + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(out); o.start(t0); o.stop(t0 + dur + .05);
}
const SOUNDS = {
  fanfare(ctx, out) {   // brassy rising arpeggio into a held major chord
    const f = ctx.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = 2400; f.connect(out);
    const b = {type: "sawtooth", vol: .16, attack: .02};
    [[523.25, 0], [659.25, .13], [783.99, .26]].forEach(([hz, t]) => tone(ctx, f, hz, t, .16, b));
    tone(ctx, f, 783.99, .42, .12, b);
    [523.25, 659.25, 783.99, 1046.5].forEach(hz => tone(ctx, f, hz, .56, 1.1, {...b, vol: .11, attack: .03}));
    tone(ctx, out, 261.63, .56, 1.1, {type: "triangle", vol: .2});
  },
  upbeat(ctx, out) {    // two quick rising notes
    tone(ctx, out, 659.25, 0, .14, {vol: .28});
    tone(ctx, out, 880, .12, .26, {vol: .28});
  },
  thud(ctx, out) {      // low drop with a soft knock
    tone(ctx, out, 120, 0, .32, {type: "sine", vol: .6, attack: .005, glideTo: 40});
    tone(ctx, out, 70, 0, .08, {type: "square", vol: .06, attack: .002});
  },
  alert(ctx, out) {     // two-note nag: something is unfinished here
    [0, .22].forEach(t => { tone(ctx, out, 987.77, t, .1, {type: "square", vol: .12}); tone(ctx, out, 739.99, t + .1, .1, {type: "square", vol: .12}); });
  },
  chime(ctx, out) {     // soft bell: news, nothing to do right now
    [[1318.5, 0], [1760, .09]].forEach(([hz, t]) => tone(ctx, out, hz, t, .9, {type: "sine", vol: .16, attack: .004}));
  },
  cash(ctx, out) {      // bright two-step "ka-ching": money
    tone(ctx, out, 1567.98, 0, .08, {type: "triangle", vol: .22, attack: .002});
    tone(ctx, out, 2093, .07, .5, {type: "triangle", vol: .2, attack: .002});
    tone(ctx, out, 3135.96, .07, .35, {type: "sine", vol: .06, attack: .002});
  },
  find(ctx, out) {      // rising sparkle: something worth a look just turned up
    [880, 1108.73, 1318.51, 1760].forEach((hz, i) => tone(ctx, out, hz, i * .07, .35, {type: "sine", vol: .14, attack: .005}));
  },
  danger(ctx, out) {    // low two-tone klaxon: the ship is in trouble
    [0, .3].forEach(t => { tone(ctx, out, 330, t, .25, {type: "sawtooth", vol: .1}); tone(ctx, out, 247, t + .14, .14, {type: "sawtooth", vol: .1}); });
  },
};
function play(name) {
  const ctx = audio(); if (!ctx || !SOUNDS[name]) return;
  if (ctx.state !== "running") { drawSoundBtn(); return; }  // would only pile up and play late
  const out = ctx.createGain(); out.gain.value = .8; out.connect(ctx.destination);
  SOUNDS[name](ctx, out);
}
function drawSoundBtn() {
  const blocked = soundOn && actx && actx.state !== "running";
  soundBtn.textContent = soundOn ? "🔊" : "🔇";
  soundBtn.title = !soundOn ? "sounds off — click to turn on" : blocked ? "sounds on, but the browser needs one click on the page to allow audio" : "sounds on — click to turn off";
  // a silent second window should not look broken
  if (!speakerHere()) soundBtn.title += speakMode() === "never" ? " (this browser never plays alert sounds: see the alerts dialog)" : " (another window is speaking)";
  soundBtn.style.opacity = speakerHere() ? "" : .45;
  soundBtn.classList.toggle("on", !!soundOn);
  soundBtn.classList.toggle("blocked", !!blocked);
}
soundBtn.onclick = () => { soundOn = !soundOn; store.set("sound", soundOn); if (soundOn) audio(); drawSoundBtn(); };
document.querySelectorAll("[data-try]").forEach(b => b.onclick = () => { play(b.dataset.try); drawSoundBtn(); });
// Browsers only allow audio after a click; any click on the page unlocks it.
document.addEventListener("pointerdown", () => { if (soundOn) { audio(); setTimeout(drawSoundBtn, 50); } });
if (soundOn === null) soundOn = true;  // provisional until the payload's defaults arrive
if (soundOn) audio();
drawSoundBtn();

let runId = null, lastArrival = null, lastUnsoldLevel = null, lastCarrierMoved = null, lastCodexTs = null, lastDockTs = null;
let lastMomentSeq = 0, lastSaleTs = null, lastPosId, lastLowFlag = false, hullLatch = 0, saleBanner = null;
const hullBand = h => !h || h.pct == null ? 0 : h.pct < 25 ? 2 : h.pct < 50 ? 1 : 0;
// "nearest KNOWN scoopable": out in the black most systems are unreported and most stars are scoopable,
// so the absence of a known one is not a reason to panic, and the text says so
function scoopHint() {
  const p = data.position, jr = effRange();
  const s = (data.systems || []).filter(x => x.id64 !== (p && p.id64) && x.main_scoopable).sort((a, b) => a.distance - b.distance)[0];
  return s ? `nearest known scoopable: ${s.name} · ${s.distance.toFixed(1)} ly${jr && s.distance > jr ? " (beyond one jump)" : ""}`
           : "no known scoopable star nearby (most unreported stars are scoopable: check the galaxy map)";
}
function onData() {
  drawTts();
  const sv = data.speech && data.speech.version;
  if (sv && sv !== speechLib.version && sv !== speechLibWanted) { speechLibWanted = sv; loadSpeechLib(); }
  const br = data.bio_rules, brEl = document.getElementById("bioRules");
  if (brEl) brEl.textContent = br
    ? `Species guesses use the BioScan spawn rules (${br.species} species, updated ${(br.generated || "").slice(0, 10)}); each start fetches newer rules from GitHub when there are any.`
    : "Spawn rules missing (bio_rules.json) and could not be downloaded: bodies get no species guesses. Run python3 ed_bio.py --update-rules once online.";
  // first payload, the server was restarted, or this window slept (see poll): no sounds for old state
  if (data.run_id !== runId || woke) {
    woke = false;
    runId = data.run_id; lastSeq = data.target ? data.target.seq : 0;
    const df = data.defaults || {};
    showBioMin();
    showHl(); showMaxBonus(); fillThresholds(); showHighG();
    if (store.get("sound", null) === null && df.sounds != null) { soundOn = !!df.sounds; drawSoundBtn(); }
    lastArrival = data.arrival ? data.arrival.seq : 0;
    lastUnsoldLevel = unsoldLevel(data.unsold); lastCarrierMoved = data.carrier && data.carrier.moved_ts;
    lastCodexTs = (data.codex_recent || [])[0] && data.codex_recent[0].ts;
    lastDockTs = data.docked ? data.docked.ts : data.docked_ts ?? null;   // docked_ts: a dock Status.json hides for now
    lastMomentSeq = Math.max(0, ...(data.moments || []).map(m => m.seq));
    lastSaleTs = data.last_sale && data.last_sale.ts;
    lastPosId = data.position && data.position.id64; lastLowFlag = !!(data.fuel && data.fuel.low_flag);
    hullLatch = hullBand(data.hull);
    clearAnnounced = data.sampling && data.sampling.clear ? `${data.sampling.species}|${data.sampling.samples}` : null;
    return;
  }
  // Just docked: the moment to sell, if what this station buys is worth it. Each Docked event has its own ts,
  // so walking about the station (or a Status.json that briefly reads 'not docked') never re-announces it.
  const dk = data.docked, canSell = sellableHere(dk, data.unsold);
  // the dock alert below says the haul: a login greeting on this same payload leaves the amount to it
  const dockSays = !!(dk && dk.ts !== lastDockTs && lastDockTs !== undefined && canSell && canSell.level !== "ok");
  if (dk && dk.ts !== lastDockTs) {
    if (lastDockTs !== undefined && canSell && canSell.level !== "ok")
      alertOut("sell", `Docked at ${dk.station} — ${credits(canSell.value)} cr to sell`, dk.has_uc && dk.has_vista ? "Universal Cartographics and Vista Genomics are here."
               : dk.has_uc ? "Universal Cartographics is here." : "Vista Genomics is here.",
               {say: () => line("docked_sell", {value: credits(canSell.value), station: dk.station}, `Docked. ${credits(canSell.value)} credits to sell here.`)});
    lastDockTs = dk.ts;
  }
  const sale = data.last_sale;
  if (sale && sale.ts !== lastSaleTs) {   // what did I bank, and is half of it still aboard?
    const parts = [sale.carto && `${credits(sale.carto)} cr cartographics`, sale.bio && `${credits(sale.bio)} cr exobiology`].filter(Boolean);
    const u = data.unsold || {}, bioLeft = (u.bio || {}).estimated_value || 0, cartoLeft = (u.carto || {}).estimated_payout || 0;
    const still = sale.carto && !sale.bio && bioLeft > 0 ? `Exobiology still aboard: ${credits(bioLeft)} cr (Vista Genomics)`
                : sale.bio && !sale.carto && cartoLeft > 0 ? `Cartographics still aboard: ${credits(cartoLeft)} cr (Universal Cartographics)` : "";
    saleBanner = {text: `💰 Sold ${parts.join(" · ")}${sale.systems ? ` · ${sale.systems} systems` : ""}${still ? ` — ${still}` : ""}`, until: Date.now() + 60000};
    alertOut("sell", `Sold ${parts.join(" and ")}`, still,
             {say: () => line("sold", {sold: parts.join(" and "), still: still ? still.replace(/ \((.+)\)$/, " at $1") + "." : ""}, `Sold ${parts.join(" and ")}. ${still}`)});
    lastSaleTs = sale.ts;
  }
  // arrival: low fuel at a star you cannot scoop (the target-time warning only covers plotted jumps)
  const pos = data.position, f0 = data.fuel;
  if (pos && pos.id64 !== lastPosId) {
    const hs = data.here_star;
    if (lastPosId !== undefined && f0 && f0.live && f0.pct != null && f0.pct < 30 && hs && !/^[OBAFGKM](_|$)/.test(hs))
      alertOut("fuel", `Fuel ${f0.pct}% at a ${hs} star you cannot scoop`, scoopHint(), {tag: "fuel_star", say: () => line("fuel_star", {pct: f0.pct, star: spokenStar(hs)}, `Fuel ${f0.pct} percent, and this star cannot be scooped.`)});
    lastPosId = pos.id64;
    // back in a system: what you were warned about leaving its bodies last time is unfinished news again
    const here = posId();
    for (const k of [...leftWarned.keys()]) if (k.startsWith(here + "|")) leftWarned.delete(k);
  }
  // the LowFuel flag is only about the ship while you sit in it: on foot or in the SRV it reads clear, and
  // boarding again would re-announce it, so those payloads keep the last reading
  if (!(f0 && f0.live && f0.in_ship === false)) {
    const low = !!(f0 && f0.low_flag);
    if (low && !lastLowFlag) alertOut("fuel", "Fuel low", scoopHint(), {tag: "fuel_low", say: () => line("fuel_low", {pct: f0 && f0.pct}, "Fuel low.")});
    lastLowFlag = low;
  }
  // moments: valuable finds (priced by the server, judged against your highlight levels), heat, interdiction
  for (const m of (data.moments || []).filter(m => m.seq > lastMomentSeq)) {
    // first: a moment whose handler throws (a bad setting, an odd field) is not retried on every payload, and
    // the moments after it still get their turn
    lastMomentSeq = Math.max(lastMomentSeq, m.seq);
    try {
      if (m.kind === "scan") {
        const special = (m.notable || m.terraformable) && m.first_discovered;
        if (special || (m.base_value != null && m.base_value >= hlLevel("body"))) {
          const what = [m.subtype, m.terraformable && "terraformable", m.first_discovered && "undiscovered"].filter(Boolean).join(", ");
          alertOut("find", `${m.body}: ${what}`, m.base_value ? `${credits(m.base_value)} cr scanned and mapped` : "", {say: () => line("find_body", {what, body: m.body, value: m.base_value ? credits(m.base_value) : ""}, `${what}, ${m.body}.`)});
          toast(`✦ ${m.body}: ${what}`);
        }
      } else if (m.kind === "bio" && m.bio_value != null && m.bio_value >= hlLevel("bio")) {
        alertOut("find", `Bio on ${m.body}: up to ${credits(m.bio_value)} cr`, `${m.signals} signal${m.signals === 1 ? "" : "s"}`,
                 {say: () => line("find_bio", {body: m.body, value: credits(m.bio_value)}, `Biology on ${m.body}, worth up to ${credits(m.bio_value)} credits.`)});
        toast(`🧬 ${m.body}: up to ${credits(m.bio_value)} cr`);
      } else if (m.kind === "heat") alertOut("hull", "Heat damage", "", {tag: "heat", say: () => line("heat", {}, "Heat damage.")});
      else if (m.kind === "interdicted") alertOut("hull", `Interdicted${m.by ? " by " + m.by : ""}`, m.submitted ? "you submitted" : "",
                                                  {tag: "interdicted", say: () => line("interdicted", {by: m.by || "someone"}, "Interdicted.")});
      else if (m.kind === "game_start") { const ship = m.ship ? shipLabel(m.ship) : "";
        if (speechShift()) pickShift();
        // after a break of over two hours (the server says how long) the greeting carries what is at stake
        const wb = m.away ? welcomeText(m.away, dockSays) : "";
        alertOut("game", `Game loaded${m.cmdr ? ": CMDR " + m.cmdr : ""}`, [ship ? `flying ${ship}` : "", wb].filter(Boolean).join(" · "),
                 {say: () => wb ? line("welcome_back", {cmdr: m.cmdr, ship, text: wb}, `Welcome back, Commander. ${wb}`)
                                : line("game_start", {cmdr: m.cmdr, ship}, "Welcome back, Commander.")}); }
      else if (m.kind === "loss") {   // after the rebuy: what went down with the ship, and the nearest place to rescan
        const text = lossText(m);
        lossCard = {m, text, until: Date.now() + 30 * 60000};
        alertOut("loss", m.ship ? `Ship lost with ${credits(m.value)} cr of data` : `Samples lost: ${credits(m.bio)} cr`, text,
                 {tag: "ship_lost", say: () => m.ship ? line("ship_lost", {text}, `Rebuy complete. ${text}`) : `Your samples died with you. ${text}`});
        renderStrip();
      }
      else if (m.kind === "signals") {   // the FSS found signals on a body: counts only, per the two ticks
        const b = saySignals("bio") && m.bio, g = saySignals("geo") && m.geo;
        const n = (c, what) => `${c} ${what} Signal${c === 1 ? "" : "s"}`;
        const text = b && g ? `${m.bio} Biological and ${m.geo} Geological Signals found on body ${m.body}.`
          : b ? `${n(m.bio, "Biological")} on body ${m.body}.` : g ? `${n(m.geo, "Geological")} on body ${m.body}.` : "";
        if (text && speechOn && speakerHere()) speak(text, {kind: "signals"});
      }
      else if (m.kind === "honk") {
        const n = m.bodies, count = m.all_found ? "all bodies found" : n != null ? `${n} bod${n === 1 ? "y" : "ies"}` : "";
        // a honk that worked also gave the arrival briefing, which says the body count: one summary, not two
        alertOut("honk", m.ok ? `Honked ${m.system}${count ? " · " + count : ""}` : `Auto honk failed in ${m.system}`, m.why || "",
                 {quiet: !!(m.ok && m.brief && alertSpeak.brief), say: !m.ok ? (/gave up/.test(m.why || "") ? (/still in the jump/.test(m.why) ? "Honk skipped." : "Honk skipped. The map stayed open.")   // never pressed: "gave up waiting: the galaxy map is open"
                                : /map|FSS|panel|orrery|codex|scanner is open|services/.test(m.why || "") ? "Honk failed. A map or panel was open."
                                : "Honk failed. Is the discovery scanner on primary fire?")
                       : !honkAnnounce() ? "System honked."
                       : m.all_found ? "System scan complete, and all bodies were found."
                       : n != null ? `System Scan Completed, ${n} Bod${n === 1 ? "y" : "ies"} discovered.` : "System scan completed."});
      }
      else if (m.kind === "fsd_charge") {
        const scoop = /^[OBAFGKM](_|$)/.test(m.star_class || "");
        const hz = sayHazard() ? hazardSaid(m.star_class) : "";   // a neutron star, white dwarf or black hole ahead
        clearForJump();
        alertOut("jump", `Jumping to ${m.system}`, m.star_class ? `${spokenStar(m.star_class)}${scoop ? ", scoopable" : ", not scoopable"}` : "",
                 {tag: "fsd_charge", say: `Frame Shift Drive charging to jump to ${m.system}.${scoop ? " This star is scoopable." : ""}${hz ? " " + hz : ""}`});
      }
      else if (m.kind === "arrival_brief") {   // after the honk (or 12 s after arriving without one): one sentence
        const text = arrivalBriefText(m);
        if (text) alertOut("brief", `${m.system_name || "Arrived"}: ${text.split(". ")[0].replace(/\.$/, "")}`, text,
                           {tag: "arrival_brief", say: () => line("arrival_brief", {text}, text)});
      }
      else if (m.kind === "fss_done" && m.leaving) {   // every body found in the FSS: go here, or move on
        const count = m.count || m.leaving.body_count, text = worthSaying(m.leaving);
        alertOut("fss", `All ${count ? nBodies(count) + " " : "bodies "}found`, text ? `worth it: ${text}` : "nothing worth staying for",
                 {tag: "fss_done", say: () => text ? line("fss_done", {count, text}, `All ${count || ""} found. Worth it: ${text}.`)
                                                   : line("fss_nothing", {count}, `All ${count || ""} found. Nothing worth staying for.`)});
      }
      else if (m.kind === "fss_unfinished" && m.left) {
        alertOut("fss", `FSS closed: ${nBodies(m.left)} still hidden`, m.system_name || "",
                 {tag: "fss_unfinished", say: () => line("fss_unfinished", {left: nBodies(m.left)}, `${nBodies(m.left)} still unresolved.`)});
      }
      else if (m.kind === "left_body") {   // back to supercruise with sampling unfinished
        const text = leftBodyText(m);
        // only a warning that reached you (spoken or notified) spares the leaving alert, and only what it named
        if (text && alertOut("sampling", `Left ${m.body} unfinished`, text, {say: () => line("left_body", {body: m.body, text}, `Leaving ${m.body} unfinished: ${text}.`)})) {
          // once you touched down the warning had its chance at every untouched genus (it leaves out the cheap
          // ones on purpose): the whole body counts as covered, or a 1M Bacterium would bring the body back in the
          // system's leaving alert with the whole body's value
          const named = new Set(Object.keys(m.partial || {}));
          if (m.touched) for (const u of m.untouched || []) named.add(u.genus);
          const key = `${m.system}|${m.body}`, had = leftWarned.get(key);
          leftWarned.set(key, {genera: new Set([...named, ...(had ? had.genera : [])]), unidentified: m.touched ? m.unidentified || 0 : had ? had.unidentified : null});
        }
      }
      else if (m.kind === "bio_done" && m.species) {   // the third sample: what it paid and what is left here
        const left = bioLeftText(m), value = m.value ? credits(m.value) : "";
        alertOut("sampling", `${m.species} complete${value ? ` · ${value} cr` : ""}`, left ? `left on ${m.body}: ${left}` : `the last one on ${m.body}`,
                 {sound: "upbeat", say: () => left ? line("bio_done_more", {species: m.species, value, left}, `${m.species} complete. Left here: ${left}.`)
                                                   : line("bio_done_last", {species: m.species, value}, `${m.species} complete. That was the last one here.`)});
      }
      else if (m.kind === "approach") {   // orbital cruise at a body: the stakes of a high-g landing, and (if ticked) its bio
        const hg = highGStakes(m), bt = bodyBriefText(m);
        const brief = () => line("body_brief", {body: m.body, text: bt}, `${m.body}: ${bt}.`);
        // with both spoken, one utterance: the bio briefing leads into the high-g warning. Otherwise each alert
        // follows its own ticks (the approach alert off must not swallow the body briefing).
        const merge = !!(hg && bt && alertSpeak.approach && alertSpeak.bodybrief);
        if (bt) alertOut("bodybrief", `Approaching ${m.body}`, bt, {tag: "body_brief", say: brief, quiet: merge});
        if (hg)
          alertOut("approach", `${m.body}: ${hg.gravity} g with ${hg.value} cr aboard`, hg.rebuys ? `${hg.rebuys}× your rebuy · land gently` : "land gently",
                   {tag: "high_g", say: () => [merge ? brief() : "", line("high_g", hg, `${hg.gravity} g. ${hg.value} credits aboard. Land gently.`)].filter(Boolean).join(" ")});
      }
      else if (m.kind === "scoop_end") {   // Status.json: the scoop has ended (a jump cutting it short says nothing)
        if (m.full) alertOut("scoop", "Tank full", m.jumps != null ? `${m.jumps} jumps at max range` : "",
                             {tag: "scoop", say: () => line("tank_full", {jumps: m.jumps}, "Tank full.")});
        else if (m.pct < 90) alertOut("scoopstop", `Scooping stopped at ${m.pct}%`, "",
                                      {tag: "scoop", say: () => line("scoop_stopped", {pct: m.pct}, `Scooping stopped at ${m.pct} percent.`)});
      }
      else if (m.kind === "supercharged") {
        const mult = `${Number(m.mult) || 4} times`;
        alertOut("supercharge", `FSD supercharged ×${Number(m.mult) || 4}`, "the next jump's range", {say: () => line("supercharged", {mult}, `Frame Shift Drive supercharged, ${mult} range.`)});
      }
      else if (m.kind === "undocked" && unsoldLevel(data.unsold) === "urgent") {   // the journal's Undocked, with a red-level haul aboard
        const u = data.unsold, sold = data.last_sale && m.dock_ts && data.last_sale.ts >= m.dock_ts;
        // "nothing was sold" only where you could have: a carrier or settlement without UC or Vista (a fuel
        // stop) says nothing, and one with only one of them counts only what it buys
        const could = sellableHere({has_uc: m.has_uc, has_vista: m.has_vista}, u);
        if (!sold) { if (could && could.level === "urgent") alertOut("sell", `Undocked with ${credits(u.total)} cr still aboard`, "Nothing was sold.",
                                                                  {sound: "alert", say: () => line("undocked_unsold", {value: credits(u.total)})}); }
        else alertOut("sell", `Undocked with ${credits(u.total)} cr still aboard`, `Still to sell: ${leftToSell(u)}.`,   // part of it was sold here
                      {sound: "alert", say: () => line("unsold_urgent", {value: credits(u.total)})});
      }
      else if (m.kind === "game_exit") {   // a session of three jumps or more gets its recap in place of the plain goodbye
        const recap = recapText(m.session);
        alertOut("game", "Game closed", recap, {say: () => recap ? line("session_recap", {text: recap}, `Session over: ${recap}.`)
                                                                  : line("game_exit", {}, "Game closed. Fly safe, Commander.")});
      }
    } catch (e) { console.error(e); pageError = `alert ${m.kind}: ${e && e.message || e}`; }
  }
  // sample spacing: say so once when you are far enough from every earlier sample of the species
  const sm = data.sampling, smKey = sm && `${sm.species}|${sm.samples}`;
  if (sm && sm.clear && smKey !== clearAnnounced) {
    clearAnnounced = smKey;
    alertOut("find", `Clear to sample ${sm.genus}`, `${sm.nearest} m from the nearest sample (${sm.need} m needed)`, {sound: "upbeat", tag: "sample_clear",
             still: () => { const s = data && data.sampling; return !!s && `${s.species}|${s.samples}` === smKey; }, say: () => line("sample_clear", {genus: sm.genus}, `Clear to sample ${sm.genus}.`)});
  }
  // hull: once below half, once below a quarter (re-armed by a repair)
  const band = hullBand(data.hull);
  if (band > hullLatch) {
    alertOut("hull", `Hull ${data.hull.pct}%`, "", {tag: "hull", say: () => line("hull", {pct: data.hull.pct}, `Hull at ${data.hull.pct} percent.`)});
  }
  hullLatch = band;
  const t = data.target;
  if (t && t.seq !== lastSeq) {
    if (t.fresh && soundOn && t.sound && alertSound.discovery && speakerHere()) play(t.sound);   // the targeting sound
    if (t.fresh && t.status === "unreported")   // the fanfare above is the sound; this adds the notification (never
                                                // spoken: arriving in an undiscovered system is announced instead)
      alertOut("discovery", "New discovery targeted", `${t.name} is not in Spansh or EDSM`, {sound: null});
    // bio you were already warned about when you left its body is not said twice (the rest of that body is)
    const pid = posId();
    const tl = t.leaving && {...t.leaving, bio_pending: (t.leaving.bio_pending || []).map(b => unwarned(pid, b)).filter(Boolean)};
    const l = worthLeavingFor(tl);
    if (t.fresh && l && !l.clean) {
      // the notification lists everything; the voice the three most valuable, then "and N more"
      const text = leavingText(tl).replace(/<[^>]+>/g, "").replace(/^Leaving with unfinished work: /, ""), said = leavingSaid(tl);
      alertOut("leaving", "Leaving with unfinished work", text, {delay: t.sound ? 1600 : 0, say: () => line("leaving", {text: said}, `Leaving with unfinished work: ${said}`)});
    }
    const f = data.fuel;
    if (t.fresh && f && f.live && f.pct != null && f.pct < 30 && t.star_class && !/^[OBAFGKM](_|$)/.test(t.star_class))
      alertOut("fuel", `Fuel ${f.pct}% and ${t.name} is not scoopable`, `${t.star_class} star · ${f.since_scoop} jumps since the last scoop`,
               {delay: 800, tag: "fuel_target", say: () => line("fuel_target", {pct: f.pct, system: t.name}, `Fuel ${f.pct} percent, and the target cannot be scooped.`)});
    lastSeq = t.seq;
  }
  const a = data.arrival;
  if (a && a.seq !== lastArrival) {
    if (speechShift()) pickShift();   // a new system, a new personality on shift (before anything here is said)
    // the discovery streak: said once per streak, when a run reaches its threshold (a run grows by one per
    // arrival, so "equal" happens once); the new-streak line takes the place of "undiscovered", not after it
    const sk = a.streak || {}, cfg = streakCfg();
    const newRun = cfg.new > 1 && a.verdict === "new" && sk.new === cfg.new;
    const knownRun = cfg.known > 1 && sk.known === cfg.known && ["complete", "known"].includes(a.verdict);
    if (a.undiscovered && a.first_visit)   // nobody has been here before you (your own unsold find does not count twice)
      alertOut("arrival", `${a.name}: ${a.wrong ? "actually undiscovered" : "undiscovered"}${newRun ? ` · ${sk.new} in a row` : ""}`,
               a.wrong ? "the fanfare was deserved after all" : "you are the first here",
               {sound: a.sound || null, say: () => newRun ? line("streak_new", {count: sk.new}, `${sk.new} undiscovered systems in a row.`)
                                                          : line("arrival_undiscovered", {system: a.name}, `${a.name} is undiscovered. You are the first here.`)});
    else if (a.wrong && !a.undiscovered)   // correct a wrong fanfare out loud
      alertOut("arrival", `${a.name}: already discovered`, "someone was here before you",
               {sound: a.sound || null, say: () => line("arrival_discovered", {system: a.name}, `${a.name}: already discovered`)});
    else if (knownRun)
      alertOut("arrival", `${sk.known} known systems in a row`, "maybe change heading", {sound: null,
               say: () => line("streak_known", {count: sk.known}, `${sk.known} known systems in a row. Maybe change heading.`)});
    lastArrival = a.seq;
  }
  const u = data.unsold, ulvl = unsoldLevel(u);
  const rank = {ok: 0, warn: 1, urgent: 2};
  if (ulvl && ulvl !== lastUnsoldLevel) {
    if (lastUnsoldLevel && rank[ulvl] > rank[lastUnsoldLevel]) alertOut("unsold", `Unsold data: ${credits(u.total)} cr on board`, ulvl === "urgent" ? "Go sell." : "Worth selling soon.",
                                                   {say: () => line(ulvl === "urgent" ? "unsold_urgent" : "unsold_warn", {value: credits(u.total)})});
    lastUnsoldLevel = ulvl;
  }
  // the carrier arrived somewhere new: moved_ts, not ts (which also changes at every login and every dock at it)
  const c = data.carrier;
  if (c && c.moved_ts !== lastCarrierMoved) {
    if (lastCarrierMoved) { alertOut("carrier", `${c.name} ${c.assumed ? "should now be" : "is"} at ${c.system}`,
                                     (c.distance != null ? `${c.distance} ly from you` : "") + (c.assumed ? (c.distance != null ? " · " : "") + "the booked jump (not yet confirmed)" : ""),
                                     {say: () => line("carrier_arrived", {carrier: c.name, system: c.system})}); toast(`🚢 ${c.name} arrived at ${c.system}`); }
    lastCarrierMoved = c.moved_ts;
  }
  const k = (data.codex_recent || [])[0];
  if (k && k.ts !== lastCodexTs) {
    if (lastCodexTs) { const what = k.voucher ? `codex voucher · ${k.voucher.toLocaleString()} cr` : "new to your codex for this region"; alertOut("codex", `📖 ${k.name}`, what, {say: () => line("codex", {entry: k.name, what}, `Codex: ${k.name}, ${what}.`)}); toast(`📖 ${k.name} — ${what}`); }
    lastCodexTs = k.ts;
  }
}
// ---- the spoken-line transcript, drawn only while its section of the alerts dialog is open ----
const fateGroup = f => !f ? "wait" : /^said/.test(f) ? "said" : /^(cut|timed)/.test(f) ? "cut"
  : /^(dropped|replaced|refused|not said|nothing)/.test(f) ? "dropped" : "silent";
const hms = t => new Date(t).toTimeString().slice(0, 8);
const speechLogFacts = e => [e.kind + (e.tag ? "/" + e.tag : ""), e.style, e.voice, e.engine,
  e.waited != null ? `waited ${(e.waited / 1000).toFixed(1)} s` : "", e.took != null && /^said/.test(e.fate || "") ? `${(e.took / 1000).toFixed(1)} s long` : ""].filter(Boolean);
function drawSpeechLog() {
  const box = document.getElementById("speechLogBox"), dlg = document.getElementById("alertDialog");
  if (!box || !box.open || !dlg || !dlg.open) return;
  document.getElementById("speechLog").innerHTML = speechLog.length ? [...speechLog].reverse().map(e =>
    `<div class="slog ${fateGroup(e.fate)}"><span class="unk">${hms(e.t)}</span> <b>${esc(e.fate || "waiting")}</b> <span class="unk">· ${esc(speechLogFacts(e).join(" · "))}</span><br>“${esc(e.words)}”</div>`).join("")
    : `<div class="unk">Nothing yet in this window since it opened.</div>`;
}
let speechLogTimer = null;
function drawSpeechLogSoon() { if (!speechLogTimer) speechLogTimer = setTimeout(() => { speechLogTimer = null; drawSpeechLog(); }, 200); }
const speechLogText = () => [...speechLog].reverse().map(e => `${hms(e.t)}  ${e.fate || "waiting"}  [${speechLogFacts(e).join(", ")}]  ${e.words}`).join("\n");
document.getElementById("speechLogBox").addEventListener("toggle", drawSpeechLog);
document.getElementById("speechLogCopy").onclick = () => copyText(speechLogText() || "(nothing yet)", `${speechLog.length} lines`);
// ---- alert settings ----
const alertDialog = document.getElementById("alertDialog");
document.getElementById("alertOpts").innerHTML = ALERTS.map(([k, label, snd]) =>
  `<tr><td>${esc(label)}</td><td><input type="checkbox" data-alert="${k}" aria-label="notify"></td>` +
  `<td>${snd || k === "arrival" ? `<input type="checkbox" data-asound="${k}" aria-label="sound">` : `<span class="unk" title="${k === "discovery" ? "the target sound" : "no sound"}">·</span>`}</td>` +
  `<td>${UNSPOKEN.has(k) ? `<span class="unk" title="not spoken: arriving there is">·</span>` : `<input type="checkbox" data-aspeak="${k}" aria-label="speak">`}</td></tr>`).join("");
for (const [attr, cfg, key] of [["asound", alertSound, "alertSound"], ["aspeak", alertSpeak, "alertSpeak"]])
  alertDialog.querySelectorAll(`[data-${attr}]`).forEach(cb => {
    cb.checked = !!cfg[cb.dataset[attr]];
    cb.onchange = () => { cfg[cb.dataset[attr]] = cb.checked; store.set(key, cfg); };
  });
// spoken alerts: header toggle, voice picker, a test button
const speechBtn = document.getElementById("speechBtn");
function drawSpeechBtn() {
  speechBtn.classList.toggle("on", !!speechOn); speechBtn.style.opacity = speechOn && speakerHere() ? 1 : .45;
  const t = data && data.tts;
  speechBtn.title = (speechOn ? "spoken alerts on" : "spoken alerts off") + " — " +
    (t && t.engine === "piper" ? `Piper voice ${t.voice}` : t && t.available ? `Piper: ${t.status}; browser speech meanwhile` : "browser speech (install Piper for a better voice: see ed_tts.py)") +
    (speakerHere() ? "" : speakMode() === "never" ? " — this browser never speaks (see the alerts dialog)" : " — another window is speaking");
}
// "This screen speaks": the setting, whether this window is the one, and a way to take over
function drawSpeaker() {
  const sel = document.getElementById("speakMode"), locks = !!(navigator.locks && navigator.locks.request);
  if (document.activeElement !== sel) sel.value = speakMode();
  document.getElementById("speakerStatus").textContent = speakMode() !== "auto" ? ""
    : !locks ? "(this browser cannot tell its windows apart, so every window speaks)"
    : isSpeaker ? "this window is the one speaking" : "another window is speaking";
  document.getElementById("speakerClaim").hidden = !(locks && speakMode() === "auto" && !isSpeaker);
  if (!speakerHere()) hushSpeech();   // another window took over, or this one was set to never speak
  drawSpeechBtn(); drawSoundBtn();
}
speechBtn.onclick = () => {
  speechOn = !speechOn; store.set("speech", speechOn); audio(); drawSpeechBtn();
  if (speechOn) { lineStyle = null; const t = line("speech_on", {}, "Spoken alerts on."); speak(t, styleVoice(lineStyle)); }
  else hushSpeech(true);   // off means quiet now, not after the queue has drained
};
// ▶ voice: a random alert in the chosen personalities, with made-up values (the words are shown too)
document.getElementById("trySpeak").onclick = () => {
  audio();
  const keys = Object.keys(LINE_SAMPLES).filter(k => line(k, LINE_SAMPLES[k]));
  const key = keys[Math.floor(Math.random() * keys.length)] || "leaving";
  lineStyle = null;
  const text = line(key, LINE_SAMPLES[key], "Leaving with unfinished work: A 2, a class two gas giant, plus 1.4M to map.");
  const sv = styleVoice(lineStyle);
  document.getElementById("speechTried").textContent = `${key}: “${spokenText(text)}”${sv.voice ? ` (${sv.voice})` : ""}`;
  speak(text, sv);
};
// personalities: one box per style in speech.json, plus profanity for the styles with swearing versions
function drawSpeechStyles() {
  const box = document.getElementById("speechStyles"), on = speechStyles();
  const styles = Object.entries(speechLib.styles || {});
  box.innerHTML = styles.map(([k, v]) => `<label${v && v.voice ? ` title="this personality speaks in its own voice when it is installed (set in speech.json)"` : ""}><input type="checkbox" data-sstyle="${esc(k)}"${on.includes(k) ? " checked" : ""}> ${esc(typeof v === "string" ? v : (v && v.label) || k)}` +
    `${v && typeof v.voice === "string" ? ` <span class="unk">(${esc(v.voice)}${data && data.tts && data.tts.voices && !data.tts.voices.includes(v.voice) ? ", not installed" : ""})</span>` : ""}</label>`).join(" ");
  box.querySelectorAll("[data-sstyle]").forEach(cb => cb.onchange = () => {
    store.set("speechStyles", [...box.querySelectorAll("[data-sstyle]:checked")].map(x => x.dataset.sstyle)); shiftStyle = null; drawSpeechStyles();
  });
  const lines = Object.values(speechLib.lines || {});
  const swear = styles.map(([k]) => k).filter(k => lines.some(e => e && Array.isArray(e[k + "_profane"]) && e[k + "_profane"].length));
  if (document.activeElement !== namesBox) namesBox.value = speechNames().join(", ");
  document.getElementById("sayBio").checked = saySignals("bio"); document.getElementById("sayGeo").checked = saySignals("geo");
  document.getElementById("sayHazard").checked = sayHazard();
  speedBox.value = speechSpeed(); speedOut.textContent = speechSpeed().toFixed(2) + "×";
  const pr = document.getElementById("speechProfanity");
  pr.checked = !!speechProfane(); pr.disabled = !swear.length;
  const pct = document.getElementById("speechProfanityPct");
  if (document.activeElement !== pct) pct.value = speechProfanePct();
  pct.disabled = !swear.length || !speechProfane();
  document.getElementById("speechProfanityWho").textContent = swear.length ? `(${swear.join(", ")})` : "";
  document.getElementById("speechDangerBusiness").checked = speechDangerBusiness();
  document.getElementById("speechShift").checked = speechShift();
  const err = speechLib.error || (speechLib.problems || []).slice(0, 3).join("; ");
  document.getElementById("speechHint").innerHTML =
    (err ? `<span class="noscoop">${esc(err)}</span><br>` : "") +
    (!styles.length ? "No lines file, so alerts use plain wording." :
     !on.some(k => speechLib.styles[k]) ? "No personality ticked, so alerts use plain wording. " : "") +
    (styles.length ? `A line is picked at random from ${speechShift() ? "the personality on shift (drawn from those ticked at each arrival)" : "every personality ticked"}. The lines live in ${esc((data && data.speech && data.speech.file) || "speech.json")} next to the script: edit it to change or add lines (or whole personalities) and the page picks the changes up on its own. Notifications keep the plain wording.` : "");
}
document.getElementById("speechProfanity").onchange = e => { store.set("speechProfanity", e.target.checked); drawSpeechStyles(); };
document.getElementById("speechProfanityPct").onchange = e => {
  const v = e.target.value.trim() === "" ? null : Math.min(100, Math.max(0, Math.round(Number(e.target.value) || 0)));
  store.set("speechProfanityPct", v); drawSpeechStyles();   // blank goes back to the config file's default
};
const namesBox = document.getElementById("speechNames");
const speedBox = document.getElementById("speechSpeed"), speedOut = document.getElementById("speechSpeedOut");
speedBox.oninput = () => { speedOut.textContent = Number(speedBox.value).toFixed(2) + "×"; };
speedBox.onchange = () => { store.set("speechSpeed", Number(speedBox.value)); drawSpeechStyles(); };
for (const [id, key] of [["sayBio", "sayBio"], ["sayGeo", "sayGeo"], ["sayHazard", "sayHazard"]])
  document.getElementById(id).onchange = e => store.set(key, e.target.checked);
namesBox.onchange = () => { store.set("speechNames", namesBox.value.trim() ? namesBox.value : null); drawSpeechStyles(); };
drawSpeechStyles();
document.getElementById("speechDangerBusiness").onchange = e => store.set("speechDangerBusiness", e.target.checked);
document.getElementById("speechShift").onchange = e => { store.set("speechShift", e.target.checked); shiftStyle = null; drawSpeechStyles(); };
document.getElementById("speakMode").onchange = e => { store.set("speakMode", e.target.value); drawSpeaker(); };
document.getElementById("speakerClaim").onclick = () => claimSpeaker(true);
// another window changed the setting (localStorage is shared by the browser's windows)
window.addEventListener("storage", e => { if (e.key === "speakMode") drawSpeaker(); });
drawSpeaker();
// a window opened at ?mode=now (the second screen) waits a moment, so a main window opened with it speaks
if (view === "now") setTimeout(() => claimSpeaker(), 1000); else claimSpeaker();
// auto honk: the server holds Primary Fire on arrival; this is its on/off and status
const honkBox = document.getElementById("autoHonk"), honkSayBox = document.getElementById("autoHonkSay");
// say the body count when an auto honk completes: per browser, the config's [autohonk] announce by default
const honkAnnounce = () => !!(store.get("honkAnnounce", null) ?? (data && data.autohonk && data.autohonk.announce) ?? true);
honkSayBox.onchange = () => store.set("honkAnnounce", honkSayBox.checked);
let honkTest = null;   // the Test run this page started: {seq, done}
function drawHonk() {
  const a = data && data.autohonk;
  honkBox.checked = !!(a && a.wanted); honkBox.disabled = !(a && a.available);
  honkSayBox.checked = honkAnnounce(); honkSayBox.disabled = !(a && a.wanted);   // only means anything with auto honk on
  honkSayBox.closest("label").style.opacity = honkSayBox.disabled ? .5 : 1;
  document.getElementById("autoHonkStatus").textContent = a ? a.status : "";
  document.getElementById("autoHonkKey").textContent = a ? (a.pressing || a.key) : "";
  document.getElementById("autoHonkTest").disabled = !(a && a.available);
  // the test's outcome comes back in the payload: a failed press would otherwise end on "holding …"
  const t = a && a.test;
  if (honkTest && !honkTest.done && t && t.seq === honkTest.seq && ["done", "failed", "stopped"].includes(t.state)) {
    honkTest.done = true;
    document.getElementById("autoHonkTestMsg").textContent = t.state === "done" ? `held ${t.what}: did the scanner fire?`
      : t.state === "failed" ? `test failed: ${t.error}` : "test stopped";
  }
}
document.getElementById("autoHonkTest").onclick = async () => {
  const msg = document.getElementById("autoHonkTestMsg");
  try {
    const r = await fetch("api/autohonk/test", {method: "POST"}), j = await r.json();
    if (!r.ok) { msg.textContent = j.error || "could not test"; return; }
    const mine = honkTest = {seq: j.seq, done: false};
    let n = j.in;
    const tick = () => {
      if (mine.done || mine !== honkTest) return;
      msg.textContent = n > 0 ? `click into the game: pressing ${j.pressing} in ${n} s` : `holding ${j.pressing}…`;
      if (n-- > 0) setTimeout(tick, 1000);
    };
    tick();
  } catch { msg.textContent = "could not reach Outrider"; }
};
honkBox.onchange = async () => {
  try { await apiJson("api/autohonk", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: honkBox.checked})}); }
  catch { toast("could not switch auto honk"); }
};
function drawTts() {
  const t = data && data.tts, sel = document.getElementById("ttsVoice");
  document.getElementById("ttsEngine").textContent = t && t.engine === "piper" ? "· Piper" : "· browser speech";
  document.getElementById("ttsStatus").textContent = t && t.available ? t.status : "";
  document.getElementById("ttsHint").textContent = !t || !t.available
    ? "Piper is not installed, so the browser's own voice is used (robotic on Linux). For a natural voice: python3 -m venv --system-site-packages .venv && .venv/bin/pip install piper-tts, then restart Outrider."
    : "Voices live in piper-voices/ next to the script; a configured voice that is missing is downloaded there on first use.";
  const opts = (t && t.voices) || [];
  if (sel.dataset.opts !== opts.join(",")) {
    sel.innerHTML = opts.map(v => `<option>${esc(v)}</option>`).join("") || `<option value="">(none installed yet)</option>`;
    sel.dataset.opts = opts.join(",");
  }
  if (t && t.voice && document.activeElement !== sel) sel.value = t.voice;
  sel.disabled = !opts.length;
  drawSpeechBtn();
  drawHonk();
}
drawSpeechBtn();
document.getElementById("ttsVoice").onchange = e => apiJson("api/voice", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({voice: e.target.value})});
alertDialog.querySelectorAll("[data-alert]").forEach(cb => {
  cb.checked = !!alertCfg[cb.dataset.alert];
  cb.onchange = async () => {
    alertCfg[cb.dataset.alert] = cb.checked;
    if (cb.dataset.alert === "enabled" && cb.checked && typeof Notification !== "undefined" && Notification.permission !== "granted") {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { alertCfg.enabled = false; cb.checked = false; toast("notifications blocked by the browser"); }
    }
    store.set("alerts", alertCfg); drawAlertsBtn();
  };
});
const thresholdEls = {}, thresholdFills = [];
// the configured thresholds arrive with the first payload: filled then, when the dialog opens and on focus
const fillThresholds = () => thresholdFills.forEach(f => f());
for (const [id, key] of [["unsoldWarn", "warn"], ["unsoldUrgent", "urgent"]]) {
  const el = thresholdEls[id] = document.getElementById(id);
  const fill = () => { const [w, g] = unsoldThresholds(data && data.unsold); el.value = key === "warn" ? w : g; };
  thresholdFills.push(fill);
  fill(); el.addEventListener("focus", fill);
  el.onchange = () => {
    const v = Number(el.value);
    unsoldCfg[key] = el.value.trim() === "" || !isFinite(v) || v <= 0 ? null : Math.round(v);   // blank or 0 = server default
    if (unsoldCfg.warn != null && unsoldCfg.urgent != null && unsoldCfg.warn > unsoldCfg.urgent) {
      if (key === "warn") unsoldCfg.urgent = unsoldCfg.warn; else unsoldCfg.warn = unsoldCfg.urgent;
    }
    store.set("unsoldCfg", unsoldCfg); render();
    fillThresholds();
  };
}
// ---- body highlights (Here list, tree and schematic) ----
// Per browser; blank means the server default from ed_outrider.toml (body_highlight_level, biology_highlight_value).
const hlCfg = Object.assign({body: null, bio: null}, store.get("highlightCfg", {}));
const hlDefault = k => (data && data.defaults && data.defaults[k === "body" ? "body_highlight" : "bio_highlight"]) ?? (k === "body" ? 500000 : 10000000);
const hlLevel = k => hlCfg[k] ?? hlDefault(k);
// Bio worth: the likeliest species' value for what is still unknown, or what you have analysed, whichever is
// more; both are straight Vista Genomics prices (the x5 first-footfall bonus is applied elsewhere).
const bioWorth = b => Math.max(b.bio_potential || 0, (b.organics || []).filter(o => !o.lost).reduce((n, o) => n + (o.value || 0), 0));
// Geology: signal counts from the FSS/DSS, and volcanism from the scan (where geological sites and
// the materials they hold are found on landable bodies).
const hasVolcanism = b => b.type === "Planet" && !!b.volcanism && !/^no volcanism$/i.test(b.volcanism.trim());
// just the fact of volcanism (hover names it, the body panel has the rest); brighter where the body is landable
const volcanoIcon = b => hasVolcanism(b)
  ? ` <span class="volc${b.landable ? " land" : ""}" title="${esc(b.volcanism)}${b.landable ? " · landable: geological sites possible" : " · not landable"}">🌋</span>` : "";
const geoTag = b => b.geo ? ` <span class="sp geo" title="geological signals">🪨 ${b.geo} geo</span>` : "";
// Max with or without first-discovery / first-mapped / first-footfall bonuses: body_max_value_include_bonus in
// ed_outrider.toml, overridable per browser. Now always includes them (it is what a sale would pay).
let maxBonusCfg = store.get("maxBonus", null);
const maxBonus = () => maxBonusCfg ?? (data && data.defaults && data.defaults.max_include_bonus) ?? true;
const maxOf = x => maxBonus() || x.value_max_base == null ? x.value_max : x.value_max_base;
// ✦: the likeliest species of a genus has no codex entry of yours in this region (codex entries, and their
// vouchers, are per region). A codex entry is per colour variant: when the server could settle the colour
// (x.variants) it checked those; otherwise it checked the species, which never over-flags.
const codexMark = (x, region) => x && x.codex_new
  ? ` <span class="cxnew" title="new to your codex in ${esc(region || "this region")} (${(x.variants || []).length
      ? `variant ${esc(x.variants.join(" or "))}` : "likeliest species; the colour variant may differ"})">✦</span>` : "";
// The colour the likeliest species should show, muted after the guess ("Teal", "Lime or Green"); "" when unsure.
const variantTxt = x => x && (x.variants || []).length
  ? ` <span class="unk" title="expected colour variant">${esc(x.variants.map(v => v.split(" - ").pop()).join(" or "))}</span>` : "";
let codexNewCounts = store.get("codexNewCounts", true);
// Jump range with a jet-cone charge applied (neutron x4, white dwarf x1.5; the journal gives the exact value).
const effRange = () => data && data.jump_range ? data.jump_range * (data.boost || 1) : null;
// Straight-line jumps to cover d ly: the charge boosts only the first jump, the rest are at plain range.
const jumpsFor = d => {
  const r = data && data.jump_range; if (!r) return null;
  const first = r * (data.boost || 1);
  return d <= first ? 1 : 1 + Math.ceil((d - first) / r);
};
// Arrival stars worth a warning before you jump: exclusion zones and jet cones at the drop.
const hazardNote = sc => !sc ? "" : /^N$/.test(sc) ? "neutron star: throttle down on arrival, mind the jet cone"
  : /^D/.test(sc) ? "white dwarf: throttle down on arrival, mind the jet cone"
  : /^(H|SupermassiveBlackHole)$/.test(sc) ? "black hole: throttle down on arrival" : "";
function hotClasses(b) {
  return (b.base_value != null && b.base_value >= hlLevel("body") ? " hot" : "") + (bioWorth(b) >= hlLevel("bio") ? " biohot" : "");
}
// rebuy multiples: blank = off
for (const [id, key] of [["rebuyWarn", "rebuyWarn"], ["rebuyUrgent", "rebuyUrgent"]]) {
  const el = document.getElementById(id);
  el.value = unsoldCfg[key] ?? "";
  el.onchange = () => {
    const v = Number(el.value);
    unsoldCfg[key] = el.value.trim() === "" || !isFinite(v) || v <= 0 ? null : v;
    el.value = unsoldCfg[key] ?? ""; store.set("unsoldCfg", unsoldCfg); render();
  };
}
const codexNewEl = document.getElementById("codexNewCounts");
codexNewEl.checked = codexNewCounts;
codexNewEl.onchange = () => { codexNewCounts = codexNewEl.checked; store.set("codexNewCounts", codexNewCounts); render(); };
const maxBonusEl = document.getElementById("maxBonus");
const showMaxBonus = () => { maxBonusEl.checked = maxBonus(); };
maxBonusEl.onchange = () => { maxBonusCfg = maxBonusEl.checked; store.set("maxBonus", maxBonusCfg); renderHere(); };
showMaxBonus();
const hlEls = {hlBody: document.getElementById("hlBody"), hlBio: document.getElementById("hlBio")};
function showHl() { for (const [id, el] of Object.entries(hlEls)) { const k = id === "hlBody" ? "body" : "bio"; el.value = hlCfg[k] ?? ""; el.placeholder = hlDefault(k); } }
for (const [id, el] of Object.entries(hlEls)) {
  const k = id === "hlBody" ? "body" : "bio";
  el.onfocus = showHl;
  el.onchange = () => {
    const v = Number(el.value);
    hlCfg[k] = el.value.trim() === "" || !isFinite(v) || v < 0 ? null : Math.round(v);
    // the body level also drives the header's leaving strip, Now and the Left-behind table: redraw them all
    store.set("highlightCfg", hlCfg); showHl(); renderHere(); render();
  };
}
showHl();
const highGEl = document.getElementById("highG");
const showHighG = () => { highGEl.value = store.get("highG", null) ?? ""; highGEl.placeholder = highGravity(); };
highGEl.onfocus = showHighG;
highGEl.onchange = () => {
  const v = Number(highGEl.value);
  store.set("highG", highGEl.value.trim() === "" || !isFinite(v) || v <= 0 ? null : v); showHighG(); renderHere();   // Here reds gravity at it
};
showHighG();
// the discovery streak's spoken thresholds and the suggested order's "skip?" floor (blank = the default)
const streakEls = {known: document.getElementById("streakKnown"), new: document.getElementById("streakNew")};
const showStreak = () => { const c = store.get("streakCfg", {}) || {}, now = streakCfg();
  for (const [k, el] of Object.entries(streakEls)) { el.value = c[k] ?? ""; el.placeholder = now[k]; } };
for (const [k, el] of Object.entries(streakEls)) {
  el.onfocus = showStreak;
  el.onchange = () => {
    const c = {...(store.get("streakCfg", {}) || {})}, v = Number(el.value);
    // a run of one is no streak: 1 is stored as 2, the smallest that can fire (0 = off)
    if (el.value.trim() === "" || !isFinite(v) || v < 0) delete c[k]; else { const n = Math.min(99, Math.round(v)); c[k] = n === 1 ? 2 : n; }
    store.set("streakCfg", c); showStreak();
  };
}
showStreak();
const skipEl = document.getElementById("skipFloor");
const showSkip = () => { skipEl.value = store.get("skipFloor", null) ?? ""; skipEl.placeholder = skipFloor(); };
skipEl.onfocus = showSkip;
skipEl.onchange = () => {
  const v = Number(skipEl.value);
  store.set("skipFloor", skipEl.value.trim() === "" || !isFinite(v) || v < 0 ? null : Math.round(v)); showSkip(); renderHere();
};
showSkip();
// ---- portable settings: export to a file, import from one, or keep a copy on the server for new browsers ----
// Only SETTINGS_KEYS travel. Import replaces this browser's copy of each of them (one missing from the file
// goes back to its default) and reloads, since most settings are read once when the page starts.
// What this browser actually uses: its own value of each, else the server copy's (the order store.get reads
// them in), so saving or exporting never drops what the browser inherited.
function settingsDoc() {
  const settings = {}, sv = serverSettings();
  for (const k of SETTINGS_KEYS) {
    let v = null;
    try { v = localStorage.getItem(k); } catch {}
    if (v !== null) { try { settings[k] = JSON.parse(v); } catch {} }
    else if (Object.prototype.hasOwnProperty.call(sv, k) && settingOk(k, sv[k])) settings[k] = sv[k];
  }
  return {version: 1, settings};
}
function applySettings(doc) {
  if (!doc || doc.version !== 1 || !doc.settings || typeof doc.settings !== "object" || Array.isArray(doc.settings))
    return {error: "not an ED Outrider settings file"};
  // unknown keys and values of the wrong shape (a string where a list belongs) are left out, not stored
  const skipped = Object.keys(doc.settings).filter(k => !SETTINGS_KEYS.includes(k) || !settingOk(k, doc.settings[k]));
  const use = k => k in doc.settings && settingOk(k, doc.settings[k]);
  for (const k of SETTINGS_KEYS) {
    try { if (use(k)) localStorage.setItem(k, JSON.stringify(doc.settings[k])); else localStorage.removeItem(k); } catch {}
  }
  return {applied: SETTINGS_KEYS.filter(use).length, skipped};
}
function drawSettingsServer() {
  const sd = window.SERVER_DEFAULTS, clr = document.getElementById("settingsServerClear");
  clr.hidden = !sd;
  document.getElementById("settingsServer").title = sd ? `the server has settings saved ${String(sd.saved || "").replace("T", " ").slice(0, 16)} UTC; saving replaces them`
    : "save these settings on the server: a browser uses them for anything it has not set itself";
}
drawSettingsServer();
document.getElementById("settingsExport").onclick = () => {
  const blob = new Blob([JSON.stringify(settingsDoc(), null, 1)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `outrider-settings-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
const settingsFile = document.getElementById("settingsFile");
document.getElementById("settingsImport").onclick = () => settingsFile.click();
settingsFile.onchange = async () => {
  const f = settingsFile.files && settingsFile.files[0];
  settingsFile.value = "";
  if (!f) return;
  let doc = null;
  try { doc = f.size <= 256 * 1024 ? JSON.parse(await f.text()) : null; } catch {}
  const r = applySettings(doc);
  if (r.error) { toast(r.error); return; }
  toast(`imported ${r.applied} settings${r.skipped.length ? ` (${r.skipped.length} unknown left out)` : ""}; reloading`);
  setTimeout(() => location.reload(), 600);
};
async function saveServerSettings(body) {
  try {
    const r = await apiJson("api/defaults", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    if (r.error) { toast(`not saved: ${r.error}`); return; }
    window.SERVER_DEFAULTS = r.saved ? Object.assign(body, {saved: r.saved}) : null;
    toast(r.saved ? "saved on the server: new browsers start with these settings" : "the server's copy is gone");
  } catch (e) { toast(`not saved: ${e.message}`); }
  drawSettingsServer();
}
document.getElementById("settingsServer").onclick = () => saveServerSettings(settingsDoc());
document.getElementById("settingsServerClear").onclick = () => saveServerSettings({clear: true});
const bioMinEl = document.getElementById("bioMin");
const showBioMin = () => { bioMinEl.value = bioMinCfg ?? ""; bioMinEl.placeholder = bioMinNow(); };
showBioMin();
bioMinEl.onchange = () => {
  const v = Number(bioMinEl.value);
  bioMinCfg = bioMinEl.value.trim() === "" || !isFinite(v) || v < 0 ? null : Math.round(v);
  store.set("bioMinCfg", bioMinCfg); showBioMin(); render();
};
document.querySelectorAll("[data-reset]").forEach(r => r.onclick = e => {
  e.preventDefault();   // the link sits inside a <label>: don't let the click also toggle or focus its input
  const id = r.dataset.reset;
  if (id === "rebuy") {
    unsoldCfg.rebuyWarn = unsoldCfg.rebuyUrgent = null; store.set("unsoldCfg", unsoldCfg);
    document.getElementById("rebuyWarn").value = document.getElementById("rebuyUrgent").value = "";
  }
  else if (id === "maxBonus") { maxBonusCfg = null; store.set("maxBonus", null); showMaxBonus(); renderHere(); }
  else if (id === "hlBody" || id === "hlBio") { hlCfg[id === "hlBody" ? "body" : "bio"] = null; store.set("highlightCfg", hlCfg); showHl(); renderHere(); }
  else if (id === "bioMin") { bioMinCfg = null; store.set("bioMinCfg", null); showBioMin(); }
  else if (id === "highG") { store.set("highG", null); showHighG(); renderHere(); }
  else if (id === "streak") { store.set("streakCfg", {}); showStreak(); }
  else if (id === "skipFloor") { store.set("skipFloor", null); showSkip(); renderHere(); }
  else if (id === "speechSpeed") { store.set("speechSpeed", null); drawSpeechStyles(); }
  else { unsoldCfg[id === "unsoldWarn" ? "warn" : "urgent"] = null; store.set("unsoldCfg", unsoldCfg); thresholdEls[id].dispatchEvent(new Event("focus")); }
  render();
});
function drawAlertsBtn() { document.getElementById("alertsBtn").classList.toggle("on", !!alertCfg.enabled); }
document.getElementById("alertsBtn").onclick = () => { drawSpeechStyles(); fillThresholds(); alertDialog.showModal(); drawSpeechLog(); };
drawAlertsBtn();

let disconnected = null;
function setConnected(ok) {
  if (ok && disconnected) { disconnected = null; if (data) render(); }
  else if (!ok && !disconnected) {
    disconnected = new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    if (data) render();
  }
}
// A payload the page fails to draw is not a lost connection: the error shows in the Data tile, and polling
// goes on (the next payload may draw fine). Without this one bad field froze the page for good.
let pageError = null;
function guarded(what, fn) {
  try { fn(); return true; }
  catch (e) { console.error(e); pageError = `${what}: ${e && e.message || e}`; return false; }
}
// A window that slept (a laptop lid, a phone screen, a frozen background tab) must not replay what it missed
// as live alerts: hours-old klaxons, "FSD charging" for a jump long made. The server answers a long poll within
// LONG_POLL_SECONDS (25 s), so a minute without hearing from it means this page was not running: the next
// payload is taken as it is (like a first one), not announced.
const SLEPT_MS = 60000;
let lastHeard = 0, woke = false;
// lastHeard moves only on an answer (200/204): a server or network outage is a minute without hearing from it too,
// and the retries every 2 s meanwhile must not keep it fresh (the moments missed would replay as live speech)
const heard = (answered) => { const now = Date.now(); if (lastHeard && now - lastHeard > SLEPT_MS) woke = true; if (answered) lastHeard = now; };
async function poll(once = false) {
  let ok = false, fresh = false;
  heard(false);   // a request sent long after the last answer: timers were frozen, or the server was unreachable
  try {
    const r = await fetch(`api/nearby?since=${runId}:${version}`);
    if (r.status === 200 || r.status === 204) heard(true);   // an answer long after it was asked: the page slept meanwhile
    if (r.status === 200) { data = await r.json(); version = data.version; fresh = true; }
    else if (r.status === 204 && woke) version = -1;   // no news, but come back with the whole payload to re-baseline on
    ok = r.status === 200 || r.status === 204;
  } catch {}
  if (fresh) pageError = null;
  let drawn = guarded("drawing", () => setConnected(ok));
  if (fresh) { const alerted = guarded("alerts", onData), rendered = guarded("drawing", render); drawn = drawn && alerted && rendered; }
  if (!drawn && data) guarded("drawing", renderStrip);   // at least the Data tile, which says what failed
  // the server holds the request until something changes, so ask again at once; back off if it failed
  if (!once) setTimeout(poll, ok ? 0 : 2000);
}
poll();

// ---- keyboard reachability ----
// Clickable things that are not real buttons (sort headers, ☆, ⌖/🔍 links, Bodies pin cells, copyable
// names, bodies in search results) get focus and act on Enter/Space like a click. Not shortcuts: Tab to it.
const KEYABLE = 'th[data-sort], [data-bm], .goto, td.bodies[data-pop], td.name[data-name], .copy[data-name], [data-sbodypop], #hereRows tr[data-body], .sbody[data-body], ' +
  '[data-reset], #nsClear, span.name[data-name]';
let keyablePending = false;
function markKeyable() {
  keyablePending = false;
  document.querySelectorAll(KEYABLE).forEach(el => {
    if (el.tabIndex < 0) el.tabIndex = 0;
    if (!el.hasAttribute("role")) el.setAttribute("role", "button");
  });
}
new MutationObserver(() => { if (!keyablePending) { keyablePending = true; requestAnimationFrame(markKeyable); } })
  .observe(document.body, {childList: true, subtree: true});
markKeyable();
document.addEventListener("keydown", e => {
  if ((e.key === "Enter" || e.key === " ") && e.target.getAttribute && e.target.getAttribute("role") === "button"
      && e.target.tagName !== "BUTTON") {
    e.preventDefault(); e.target.click();
  }
});
document.getElementById("matSources").addEventListener("click", e => {
  const n = e.target.closest(".name"); if (n) copyText(n.dataset.name);
});
document.addEventListener("click", async e => {
  if (!e.target.closest || !e.target.closest("#nsClear")) return;
  let r;
  try { r = await apiJson("api/nextstop", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({clear: true})}); }
  catch (err) { r = {error: err.message}; }
  if (r.error) toast(`could not clear the next stop: ${r.error}`);
});
