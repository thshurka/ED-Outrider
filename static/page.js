const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
let data = null, version = -1;
let sortKey = store.get("sort", "distance");
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
    (s.bio_potential ? `<span class="nb bio" title="exobiology: up to this much across ${s.bio_bodies_guessed} bod${s.bio_bodies_guessed === 1 ? "y" : "ies"}, from spawn rules">🧬≤${credits(s.bio_potential)}</span>` : "");
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
// FSD injections you could synthesise now (from the materials you carry).
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
function renderStrip() {
  const val = (v, title) => `<div class="val"${title ? ` title="${title}"` : ""}>${v}</div>`, ln = v => v ? `<div class="ln">${v}</div>` : "";
  // commander tile: credits at login plus exploration sales since, and the ship
  const cm = data.commander, sh = data.ship, cmEl = document.getElementById("cmdrLine");
  document.getElementById("cmdrLbl").textContent = cm && cm.name ? `Cmdr ${cm.name}` : "Commander";
  const shipLine = sh ? `<span title="${esc(shipName(sh.type))}${data.jump_range ? ` · ${data.jump_range.toFixed(1)} ly max jump` : ""}">${esc(sh.name || shipName(sh.type))}` +
    `${sh.type && shipName(sh.type) !== sh.name ? ` <span class="unk">· ${esc(shipName(sh.type))}</span>` : ""}</span>` : "";
  cmEl.innerHTML = !cm ? val(`<span class="unk">no login seen</span>`) + ln(shipLine) :
    val(cm.credits != null ? `≈ ${credits(cm.credits)} cr` : `<span class="unk">credits unknown</span>`,
        `Credits at login (${esc((cm.login_ts || "").replace("T", " ").slice(0, 16))} UTC)${cm.credits_login != null ? ": " + cm.credits_login.toLocaleString() : ""}` +
        ` plus exploration and exobiology sales since. Other spending and income (market, repairs, missions) is not tracked.`) +
    ln(shipLine) + ln(cm.earned ? `+${credits(cm.earned)} cr sold since login` : "");
  const p0 = data.position, wl = document.getElementById("whereLn");
  wl.innerHTML = p0 ? `<span title="galactic coordinates (x / y / z)">Coord: ${[p0.x, p0.y, p0.z].map(v => v.toFixed(2)).join(" / ")}</span>` +
    (p0.visits ? ` · <span title="arrivals in this system, from your journals">visit ${p0.visits}</span>` : "") : "";
  // fuel tile
  const f = data.fuel, tf = document.getElementById("tFuel"), el = document.getElementById("fuelLine");
  tf.className = "tile"; tf.title = "";
  if (!f) el.innerHTML = val(`<span class="unk">—</span>`);
  else if (!f.live) el.innerHTML = val(`<span class="unk">${f.main != null ? f.main.toFixed(1) + " t (last reading)" : "no reading"}</span>`) + ln("game not running") + boostLine();
  else {
    tf.className = "tile " + (f.pct < 15 ? "urgent" : f.pct < 30 ? "warn" : "");
    el.innerHTML = val(`${f.main.toFixed(1)}${f.capacity ? " / " + f.capacity + " t" : " t"}${f.pct != null ? ` · ${f.pct}%` : ""}`) +
      ln((f.jumps_max != null ? `≈<b>${f.jumps_max}</b> jumps at max range` : "") + (f.jumps_recent != null ? (f.jumps_max != null ? ", " : "") + `<b>${f.jumps_recent}</b> at your pace` : "")) +
      ln(f.since_scoop != null ? `${f.since_scoop} jump${f.since_scoop === 1 ? "" : "s"} since the last scoop` : "") + boostLine();
    tf.title = "From Status.json. Jump estimates use fuel burned on your recent jumps; a max-range jump costs several times a short hop.";
  }
  // carrier tile
  const c = data.carrier, cl = document.getElementById("carrierLine");
  if (!c) cl.innerHTML = val(`<span class="unk">none seen</span>`);
  else cl.innerHTML = val(esc(c.name), esc(c.callsign || "")) +
    ln(c.here ? "<b>here</b>" : `<span class="copy" data-name="${esc(c.system)}" title="click to copy">${esc(c.system)}</span>` +
       (c.distance != null ? ` · <b>${c.distance.toLocaleString("en-US", {maximumFractionDigits: 1})} ly</b>` : "")) +
    ln(`${c.has_uc ? "UC ✓" : "no UC"} · ${c.has_vista ? "Vista ✓" : "no Vista"}${c.fuel != null ? ` · ${c.fuel} t tritium` : ""}` +
       (c.planned ? ` · jumping to <b>${esc(c.planned.system)}</b> ${esc((c.planned.departure || "").slice(11, 16))} UTC` : ""));
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
                    failed && esc(data.status)].filter(Boolean);
  if (problems.length) { dot = disconnected || data.tail_error ? "bad" : "warn"; tcls = dot === "bad" ? "urgent" : "warn"; }
  td.className = "tile " + tcls; td.title = data.tail_error || data.status || "";
  fl.innerHTML = val(`<span class="dot ${dot}"></span>${text}`);
  sl.innerHTML = problems.length ? problems.join(" · ") : /^asking|^fetching/.test(data.status || "") ? esc(data.status) : "Spansh ok";
  // docked somewhere that buys data with a worthwhile amount aboard: say so plainly
  const dk = data.docked, u = data.unsold, lvl = unsoldLevel(u), se = document.getElementById("sell");
  if (dk && (dk.has_uc || dk.has_vista) && lvl && lvl !== "ok") {
    se.className = lvl;
    se.innerHTML = `💰 Docked at ${esc(dk.station)}${dk.has_uc ? " with Universal Cartographics" : ""}${dk.has_vista ? (dk.has_uc ? " and" : " with") + " Vista Genomics" : ""}: ` +
      `<b>${credits(u.total)} cr</b> on board — sell before you undock.`;
  } else se.innerHTML = "";
  // tab title: what a background tab needs to know
  const p = data.position;
  document.title = (disconnected ? "⚠ " : "") + (p ? p.name : "ED Outrider") +
    (f && f.live && f.pct != null && f.pct < 30 ? ` · ⛽${f.pct}%` : "") +
    (unsoldLevel(data.unsold) === "urgent" ? " · 💰 sell!" : "");
}
let bioMin = store.get("bioMin", null);   // null until the first payload brings the server's default
function worthLeavingFor(l) {
  // The server lists everything unfinished; the page applies your exobiology threshold:
  // un-started bio only counts if a single body could pay over bioMin (started sampling always counts).
  if (!l) return null;
  // a body the rules cannot price (potential null) is kept: unknown is not the same as worthless
  const bio = l.bio_pending.filter(b => Object.keys(b.partial || {}).length || b.potential == null || b.potential >= bioMin);
  return {...l, bio_pending: bio, clean: !l.unscanned && !l.unmapped_valuable.length && !bio.length};
}
function leavingText(l) {
  l = worthLeavingFor(l);
  if (!l || l.clean) return "";
  const bits = [];
  if (l.unscanned) bits.push(`<b>${l.unscanned}</b> bod${l.unscanned === 1 ? "y" : "ies"} unscanned`);
  else if (!l.honked) bits.push("no FSS honk yet");
  for (const b of l.bio_pending) {
    const parts = Object.entries(b.partial).map(([g, n]) => `${esc(g)} ${n}/3`).concat((b.genera || []).map(esc));
    bits.push(`bio on <b>${esc(b.body)}</b>${b.genera === null ? ` (${b.signals} signal${b.signals === 1 ? "" : "s"}, not DSS'd)` : parts.length ? ` (${parts.join(", ")})` : ""}` +
              (b.potential ? ` up to ${credits(b.potential)}` : b.potential == null && !Object.keys(b.partial || {}).length ? " (value unknown)" : ""));
  }
  if (l.unmapped_valuable.length) bits.push(`unmapped valuables: ${l.unmapped_valuable.map(esc).join(", ")}`);
  return `Leaving with unfinished work: ${bits.join(" · ")}`;
}
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
const ALERTS = [["discovery", "a targeted system is a new discovery"], ["arrival", "an arrival contradicts what was announced"],
  ["leaving", "leaving a system with unfinished work"], ["fuel", "fuel low and the target star is not scoopable"],
  ["unsold", "unsold data crosses a threshold"], ["carrier", "your carrier arrives somewhere"], ["codex", "a new codex entry"]];
const alertCfg = Object.assign({enabled: false}, Object.fromEntries(ALERTS.map(([k]) => [k, true])), store.get("alerts", {}));
function notify(kind, title, body) {
  if (!alertCfg.enabled || !alertCfg[kind] || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try { new Notification(title, {body, tag: "ed-" + kind}); } catch {}
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

const credits = n => n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
                    : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(Math.round(n));
// Your own thresholds for the unsold-data warning; the server's defaults apply until you change them.
const unsoldCfg = Object.assign({warn: null, urgent: null}, store.get("unsoldCfg", {}));
function unsoldThresholds(u) {
  const [dw, du] = (u && u.thresholds) || [50000000, 250000000];
  return [unsoldCfg.warn ?? dw, unsoldCfg.urgent ?? du];
}
function unsoldLevel(u) {
  if (!u || u.error || u.total == null) return null;
  const [w, g] = unsoldThresholds(u);
  return u.total >= g ? "urgent" : u.total >= w ? "warn" : "ok";
}
function renderUnsold() {
  const el = document.getElementById("unsold"), u = data.unsold, tile = document.getElementById("tUnsold"), fl = document.getElementById("firstsLine");
  tile.className = "tile " + (unsoldLevel(u) || "");
  if (!u) { el.innerHTML = `<div class="val"><span class="unk">estimating…</span></div>`; fl.innerHTML = ""; return; }
  if (u.error) { el.innerHTML = `<div class="val"><span class="unk">unavailable</span></div>`; fl.innerHTML = esc(u.error).slice(0, 80); return; }
  const f = u.firsts;
  el.innerHTML = `<div class="val">${credits(u.total)} cr</div>` +
    `<div class="ln">🗺 <b>${credits(u.carto.estimated_payout ?? u.carto.estimated_value)}</b> · 🧬 <b>${credits(u.bio.estimated_value)}</b></div>`;
  fl.innerHTML = !f || !(f.systems || f.planets || f.mapped) ? "no unsold firsts" :
    `🏁 <b>${f.systems}</b> system${f.systems === 1 ? "" : "s"} · <b>${f.planets}</b> planet${f.planets === 1 ? "" : "s"} · <b>${f.mapped}</b> mapped unsold`;
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
    `</ul></div><div class="adv ${lvl}">${advice}</div>` +
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
  document.getElementById("refLn").innerHTML = p ? `Sol <b>${lyTo(0, 0, 0)}</b> ly · Colonia <b>${lyTo(-9530.5, -910.28125, 19808.125)}</b> ly` : "";
  document.getElementById("here").innerHTML = !p ? "waiting for your first jump…" :
    `<span class="copy" data-name="${esc(p.name)}" title="click to copy"` +
    (known ? ` data-pop data-id="${p.id64}"` : "") + `>${esc(p.name)}</span>` + (here ? firstsIcon(here.firsts) : "") +
    (here ? bmIcon(here.id, here.name, bms) : "");
  placeOverview();
  document.getElementById("nearWrap").hidden = !(view === "near" || view === "overview");
  document.getElementById("overView").hidden = view !== "overview";
  document.getElementById("bmTable").hidden = view !== "bm";
  document.getElementById("bmTools").hidden = view !== "bm";
  const nearPinned = view === "near" && !!pinnedSystem;
  document.getElementById("hereView").hidden = !(view === "here" || nearPinned || (view === "overview" && !ovState.collapsed));
  document.querySelector("main").classList.toggle("nearPinned", nearPinned);
  document.getElementById("firstsView").hidden = view !== "firsts";
  if (view === "firsts") loadFirsts();
  document.documentElement.style.setProperty("--head-h", document.querySelector("header").offsetHeight + "px");
  document.getElementById("hereView").classList.toggle("detail", !!selectedBody);
  document.getElementById("histView").hidden = view !== "hist";
  document.getElementById("matView").hidden = view !== "mat";
  if (view === "mat") loadMat();
  document.getElementById("logView").hidden = view !== "log";
  if (view === "log") { if (L.key === null) loadLog(); else tailLog(); }
  document.getElementById("bioView").hidden = view !== "bio";
  if (view === "bio") loadBio();
  if (view === "here" || nearPinned || (view === "overview" && !ovState.collapsed)) {
    loadHere();
    if (hereData && lastHereCtx !== hereCtx()) renderHere();   // tab and pane keep different modes
  }
  if (view === "hist") loadHistory();
  renderStrip();
  document.getElementById("searchView").hidden = view !== "search";
  document.querySelectorAll("[data-view]").forEach(b => b.classList.toggle("on", b.dataset.view === view));
  document.getElementById("bmViewBtn").textContent = `Bookmarks${(data.bookmarks || []).length ? ` (${data.bookmarks.length})` : ""}`;
  document.getElementById("sFrom").textContent = p ? p.name : "—";
  renderBookmarks(bms);
  renderSearch(bms);
  document.getElementById("mapView").hidden = view !== "map";
  if (view === "map") { loadMap(); drawMap(); }
  refreshPop();
  const jr = data.jump_range;
  let rows = data.systems.filter(s => s.id64 !== (p && p.id64))
    .filter(s => showVisited.checked || !s.visited)
    .filter(s => showExplored.checked || s.status !== "explored")
    .filter(s => !oneJump.checked || !jr || s.distance <= jr);
  rows.sort(sortKey === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
    : sortKey === "value" ? (a, b) => (b.value_max || 0) - (a.value_max || 0) || a.distance - b.distance
    : (a, b) => a.distance - b.distance);
  // Fuel: the nearest scoopable star you can reach (visited or not) gets a tag when the tank is low.
  const fuel = data.fuel, lowFuel = fuel && fuel.live && fuel.pct != null && fuel.pct < 30;
  const scoopNext = lowFuel && data.systems.filter(s => s.id64 !== (p && p.id64) && s.main_scoopable && (!jr || s.distance <= jr))
    .sort((a, b) => a.distance - b.distance)[0];
  const prev = data.previous;
  const unvisited = data.systems.filter(s => !s.visited).length;
  document.getElementById("subKnown").textContent = data.systems.length;
  document.getElementById("subUnvisited").textContent = unvisited;
  const rs = document.getElementById("radiusSel"), choices = data.radius_choices || [data.radius];
  if (rs.dataset.opts !== choices.join(",")) {   // rebuilt only when the choices change, so an open list stays open
    rs.innerHTML = choices.map(r => `<option value="${r}">${r}</option>`).join(""); rs.dataset.opts = choices.join(",");
    rs.title = `how far around you Nearby lists systems (radius_choices in ed_outrider.toml sets these; bigger spheres take longer to fill in)`;
  }
  if (document.activeElement !== rs && !rs.dataset.pending) rs.value = String(data.radius);
  document.getElementById("subJump").innerHTML = (jr ? `<span title="Loadout MaxJumpRange: the best case with a near-empty tank">max jump ${jr.toFixed(1)} ly</span>` : "") +
    (prev && p ? `${jr ? " · " : ""}came from ${esc(prev.name)} (${Math.hypot(prev.x - p.x, prev.y - p.y, prev.z - p.z).toFixed(1)} ly)` : "");
  document.body.classList.toggle("disconnected", !!disconnected);
  document.querySelectorAll("[data-sort]").forEach(b => b.classList.toggle("on", b.dataset.sort === sortKey));
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
    tEl.innerHTML = `Target: <b>${esc(t.name)}</b>${row ? ` · ${row.distance.toFixed(2)} ly` : ""}${sc}` +
      ` · <span class="t-${t.status.replace(" ", "")}">${label}${src}</span>`;
  }
  renderLeaving(t && t.leaving);
  const a = data.arrival, aEl = document.getElementById("arrival");
  aEl.innerHTML = !a || !p || a.id64 !== String(p.id64) ? "" :
    `Arrived at <b>${esc(a.name)}</b>: ` + (a.undiscovered
      ? `<span class="yes">arrival star undiscovered — first discovery is yours to sell</span>`
      : `<span class="no">already discovered by someone` + (a.announced === "unreported" ? " — Spansh just hadn't heard of it" : "") + `</span>`);
  document.getElementById("rows").innerHTML = rows.map(s => {
    const isPrev = prev && s.id64 === prev.id64;
    const far = jr && s.distance > jr;
    const jumps = jr ? Math.ceil(s.distance / jr) : null;
    const cls = [s.visited && "visited", far && "far", isPrev && "prev", scoopNext && s.id64 === scoopNext.id64 && "scoopnext",
                 pinnedSystem === String(s.id64) && "pinned",
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
      <td>${star(s)}</td><td class="bodies" data-pop data-id="${s.id64}">${bodies(s)}</td>
      <td class="notable">${notable(s)}</td><td class="num hide-sm" title="${valueTitle(s)}">${valueCell(s)}</td><td class="num hide-sm">${known}</td></tr>`;
  }).join("") || `<tr><td colspan="10" class="unk">${emptyMessage(rows)}</td></tr>`;
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
  list.sort(sortKey === "name"
    ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
    : (a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9));
  document.getElementById("bmRows").innerHTML = list.map(b => `<tr>
      <td class="bmcell">${bmIcon(b.id, b.name, bms)}</td>
      <td class="name" data-name="${esc(b.name)}" title="click to copy">${esc(b.name)}</td>
      <td class="num dist">${b.distance == null ? "?" : b.distance.toLocaleString("en-US", {maximumFractionDigits: 2})}</td>
      <td class="note">${esc(b.note) || `<span class="unk">no note</span>`}</td>
      <td class="hide-sm unk">${esc((b.created || "").slice(0, 10))}</td></tr>`).join("") ||
    `<tr><td colspan="5" class="unk">No bookmarks yet. Click ☆ beside any system to add one.</td></tr>`;
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
  view = b.dataset.view; store.set("view", view); render();
});

// ---- Here: every body in the current system ----
let hereKey = null, hereData = null;
// The system panel normally shows where you are; clicking a nearby row's Bodies cell pins
// another system into it until the ✕ is clicked.
let pinnedSystem = null;
const shownSystem = () => pinnedSystem || (data && data.position ? String(data.position.id64) : null);
function pinSystem(id) { pinnedSystem = String(id); if (selectedBody) closeBody(); hidePop(); render(); }
function unpinSystem() { pinnedSystem = null; if (selectedBody) closeBody(); render(); }
async function loadHere() {
  const id = shownSystem(); if (!id) return;
  const key = `${id}|${data.scan_version}`;   // only your own scans change this view
  if (key === hereKey) return;
  hereKey = key;
  let fresh;
  try { fresh = await apiJson(`api/system/${id}`); } catch (err) { fresh = {error: err.message}; }
  if (key !== hereKey) return;   // a newer request is already on its way
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
  const bioPot = h.bodies.reduce((n, b) => n + (b.bio_potential || 0), 0);
  const pinned = !!pinnedSystem, row = pinned && data.systems.find(s => String(s.id64) === pinnedSystem);
  head.innerHTML = (pinned ? `<button type="button" class="unpin" onclick="unpinSystem()" title="back to the system you are in">✕</button><span class="pintag">viewing</span> ` : "") +
    `<b>${esc(h.name)}</b>` + (pinned && row ? ` <span class="unk">· ${row.distance.toFixed(2)} ly away</span>` : "") +
    ` · ${h.bodies.length} bod${h.bodies.length === 1 ? "y" : "ies"} known · ` +
    `<span title="what selling now would pay for data you hold from here / the most this system could pay">now <b>${credits(h.value_now || 0)} cr</b> · max <b>${credits(maxOf(h) || 0)} cr</b>${maxBonus() ? "" : ` <span class="unk" title="Max leaves out first-discovery, first-mapped and first-footfall bonuses (alerts & thresholds dialog)">no bonus</span>`}</span>` +
    `<span class="modes">${HERE_MODES.filter(([m]) => m !== "split" || hereCtx() === "tab").map(([m, label, title]) =>
      `<button type="button" data-mode="${m}" title="${title}"${(m === "split" ? hereMode().split : hereMode().top === m) ? ' class="on"' : ""}>${label}</button>`).join("")}</span>`;
  const l = h.leaving;
  const firstsBlock = h.firsts ? firstsHtml(h.firsts).replace(/<div class="lbl">Your firsts<\/div>/, "") : "";
  lv.innerHTML = firstsBlock + (pinned ? (!h.firsts ? `<span class="unk">${row ? esc(row.status) : ""}${row && row.visited ? " · you have been here" : ""}</span>` : "")
    : !l ? `<span class="unk">Nothing of yours scanned here yet.</span>` : l.clean
    ? `<span class="ok">✓ Nothing left to do here${l.all_found ? " (all bodies found)" : ""}.</span>`
    : `<span class="todo">${[l.unscanned ? `${l.unscanned} bodies unscanned` : !l.honked ? "no FSS honk yet" : "",
        l.bio_pending.length ? `bio pending on ${l.bio_pending.map(b => esc(b.body) + (!Object.keys(b.partial || {}).length && b.potential != null && b.potential < bioMin ? ` <span class="unk">(under your ${credits(bioMin)} threshold)</span>` : b.potential == null && !Object.keys(b.partial || {}).length ? ` <span class="unk">(value unknown)</span>` : "")).join(", ")}` : "",
        l.unmapped_valuable.length ? `unmapped: ${l.unmapped_valuable.map(esc).join(", ")}` : ""].filter(Boolean).join(" · ")}</span>`);
  lastHereCtx = hereCtx();
  const hm = h.tree ? hereMode() : {top: "list", split: false};
  const showTable = hm.top !== "schematic", showSch = hm.top === "schematic" || hm.split;
  document.getElementById("hereTable").hidden = !showTable;
  document.getElementById("hereHint").hidden = !showTable;
  const sEl = document.getElementById("hereSchematic");
  sEl.hidden = !showSch; sEl.classList.toggle("split", showTable && showSch);
  if (showSch) sEl.innerHTML = schematicHtml(h);
  const rowHtml = (b, ind = "") => {
    const done = b.organics.filter(o => o.done).map(o => o.genus);
    const bio = [];
    const guessOf = g => (b.bio_guess || []).find(x => x.genus === g);
    const guessTxt = x => !x || !x.best ? "" : ` <span class="unk" title="likeliest by value: ${esc(x.species.join(" / "))}">(${esc(x.best.split(" ").slice(1).join(" "))}? ${credits(x.value)})</span>`;
    for (const g of b.genera) {
      const o = b.organics.find(o => o.genus === g);
      bio.push(o ? `<span class="sp ${o.lost ? "lost" : o.done ? "done" : "part"}" title="${esc(o.species || "")}${o.variant ? " · " + esc(o.variant) : ""}${o.lost ? " · lost with the ship, sample again" : ""}">${esc(g)} ${o.lost ? "lost ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}${o.done && o.value ? ` <span class="unk">${credits(o.value)}</span>` : ""}</span>` +
                   (o.done && !o.lost ? "" : guessTxt(guessOf(g)))
                 : `<span class="sp">${esc(g)} 0/3</span>` + guessTxt(guessOf(g)));
    }
    for (const o of b.organics) if (!b.genera.includes(o.genus))
      bio.push(`<span class="sp ${o.done ? "done" : "part"}">${esc(o.genus)} ${o.samples}/3${o.done ? " ✓" : ""}</span>`);
    if (!bio.length && b.bio) {
      const gl = (b.bio_guess || []).slice(0, b.bio);
      bio.push(`<span class="unk">${b.bio} signal${b.bio === 1 ? "" : "s"}, not DSS'd</span>` + (gl.length
        ? `<br><span class="unk">likely: </span>${gl.map(x => `<span class="sp" title="${esc(x.species.join(" / "))}">${esc(x.genus)} ≤${credits(x.value || 0)}</span>`).join("")}` : ""));
    }
    if (b.bio_potential) bio.push(`<span class="unk">· up to <b>${credits(b.bio_potential)}</b></span>`);
    const codex = b.codex.map(c => `<span class="sp" title="codex">📖 ${esc(c.name)}${c.voucher ? " 💰" : c.new ? " ✦" : ""}</span>`).join("");
    const firsts = [b.first_discovered && `<span class="fl" title="first discovered">🏁</span>`, b.first_mapped && `<span class="fl" title="first mapped">🗺</span>`,
                    !b.first_mapped && b.mapped && `<span class="fl unk" title="mapped (not first)">🗺</span>`,
                    b.first_footfall && `<span class="fl" title="first footfall">👣</span>`, !b.scanned && `<span class="unk" title="known to Spansh, not scanned by you">—</span>`].filter(Boolean).join("");
    return `<tr class="${b.main ? "main" : ""}${selectedBody === b.name ? " sel" : ""}${hotClasses(b)}" data-body="${esc(b.name)}" data-bodypop="${esc(b.name)}"><td class="name">${ind}${esc(b.name)}${b.notable ? ` <span class="nb ${b.notable}">${b.notable}</span>` : ""}${b.terraformable ? ` <span class="nb T">T</span>` : ""}</td>
      <td>${esc(b.subtype || "")}${b.type === "Star" ? (b.scoopable ? ` <span class="scoop">⛽</span>` : "") : ""}</td>
      <td class="num">${b.dist_ls != null ? Math.round(b.dist_ls).toLocaleString() : ""}</td>
      <td class="num${b.gravity > 2 ? " noscoop" : ""}">${b.gravity != null && b.type === "Planet" ? b.gravity.toFixed(2) : ""}</td>
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
  document.getElementById("hereRows").innerHTML = (hm.top === "text" ? treeRowsHtml(h, rowHtml) : byMax.map(b => rowHtml(b)).join(""))
    || `<tr><td colspan="10" class="unk">No bodies known here.</td></tr>`;
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
    const planets = n.children.filter(c => !isStar(c)), stars = n.children.filter(isStar);
    return `<div class="srowS"><div class="sstar">${discHtml(b, 0)}</div><div class="splanets">${planets.map(c => col(c, 1)).join("") || `<span class="unk">no planets known</span>`}</div></div>` +
      (stars.length ? `<div class="snest">${stars.map(starRow).join("")}</div>` : "");
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
function bodyPopHtml(b) {
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
    for (const g of b.genera || []) {
      const o = (b.organics || []).find(o => o.genus === g), x = (b.bio_guess || []).find(x => x.genus === g);
      lines.push(`<li><span>${esc(g)}${o ? ` · ${esc(o.species || "")} ${o.samples}/3${o.done ? " ✓" : ""}` : x && x.best ? ` · likely ${esc(x.best.split(" ").slice(1).join(" "))}` : ""}</span><b>${x && x.value ? credits(x.value) : ""}</b></li>`);
    }
    if (!(b.genera || []).length && b.bio) lines.push(...(b.bio_guess || []).slice(0, b.bio).map(x => `<li><span>${esc(x.genus)} possible (${esc(x.species.join("/"))})</span><b>≤${credits(x.value || 0)}</b></li>`));
    h += `<div class="sec"><div class="lbl">🧬 Bio${b.bio ? ` · ${b.bio} signal${b.bio === 1 ? "" : "s"}` : ""}${b.bio_potential ? ` · up to ${credits(b.bio_potential)}` : ""}</div><ul>${lines.join("")}</ul></div>`;
  }
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
    for (const g of row.genera || []) {
      const o = (row.organics || []).find(o => o.genus === g), x = (row.bio_guess || []).find(x => x.genus === g);
      const priced = o && o.done && !o.lost && o.value;
      lines.push(`<li><span>${esc(g)}${o ? ` · ${esc(o.species || "")}${o.variant ? " (" + esc(o.variant) + ")" : ""} ${o.lost ? "lost with the ship ✗" : `${o.samples}/3${o.done ? " ✓" : ""}`}` : x ? ` · could be ${esc(x.species.join(" / "))}` : ""}</span>` +
                 `<b>${priced ? credits(o.value) : x && x.value ? "≤" + credits(x.value) : ""}</b></li>`);
    }
    if (!(row.genera || []).length && row.bio) lines.push(...(row.bio_guess || []).slice(0, row.bio).map(x => `<li><span>${esc(x.genus)} possible: ${esc(x.species.join(" / "))}</span><b>≤${credits(x.value || 0)}</b></li>`));
    for (const c of row.codex || []) lines.push(`<li><span>📖 ${esc(c.name)}</span><b>${c.voucher ? "voucher " + c.voucher.toLocaleString() + " cr" : c.new ? "new to your codex" : ""}</b></li>`);
    bioSec = sec("bio", `🧬 Exobiology${row.bio ? ` · ${row.bio} signal${row.bio === 1 ? "" : "s"}` : ""}${row.bio_potential ? ` · up to ${credits(row.bio_potential)}` : ""}`, `<ul>${lines.join("")}</ul>`);
  }
  h += bioSec + ringSec + compSec + `<div class="two">${physSec}${orbitSec}</div>`;
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
  renderFirsts();
}
function renderFirsts() {
  const f = firstsData, st = document.getElementById("fStatus"), bms = bmMap();
  if (!f || f.error) { st.textContent = f ? f.error : ""; return; }
  // lost data stays in the database (a rescan earns it again) but is hidden unless asked for
  const list = f.firsts.filter(x => fShowLost.checked || x.state !== "lost");
  list.sort(sortKey === "name" ? (a, b) => a.name.localeCompare(b.name, undefined, {numeric: true})
          : sortKey === "distance" ? (a, b) => (a.distance ?? 1e9) - (b.distance ?? 1e9)
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
  const key = `${data && data.materials && data.materials.version}|${data && data.run_id}`;
  if (key === matKey) return;
  matKey = key;
  document.getElementById("matStatus").textContent = "loading…";
  try { const m = await apiJson("api/materials"); if (key === matKey) matData = m; else return; } catch (err) { matData = {error: err.message}; }
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
  document.getElementById("matSynth").innerHTML = m.synthesis.map(r => `<div class="synth" title="${r.verified ? "recipe checked against a real synthesis in your journals" : "published in-game recipe"}">
      <span class="n${r.craftable ? "" : " zero"}">×${r.craftable}</span><b>${esc(r.name)}</b>${r.boost ? ` <span class="unk">${esc(r.boost)} range</span>` : ""}
      <div class="mats">${r.materials.map(x => `<span class="${x.have < x.need ? "short" : r.limit === x.name && r.craftable < 10 ? "limit" : ""}">${esc(x.name)} ${x.have}/${x.need}</span>`).join(" · ")}</div></div>`).join("");
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
const L = {rows: [], next: null, newest: null, key: null, loading: false, open: new Set(), journal: null, fresh: new Set()};
const lDays = document.getElementById("lDays"), lNoise = document.getElementById("lNoise"), lFilter = document.getElementById("lFilter");
const lCatBoxes = [...document.querySelectorAll("#lCats input")];
const lSaved = store.get("log", {});
if (lSaved.days) lDays.value = lSaved.days;
lNoise.checked = !!lSaved.noise;
if (lSaved.cats) lCatBoxes.forEach(b => b.checked = lSaved.cats.includes(b.value));
const CAT_GLYPH = {travel: "🚀", exploration: "🔭", bio: "🧬", ship: "🛠", carrier: "🚢", other: "•", noise: "·"};
function logQuery() {
  const cats = lCatBoxes.filter(b => b.checked).map(b => b.value);
  if (lNoise.checked) cats.push("noise");
  return `days=${lDays.value}&cat=${cats.join(",") || "none"}&q=${encodeURIComponent(lFilter.value.trim())}&noise=${lNoise.checked ? 1 : 0}`;
}
function saveLog() {
  store.set("log", {days: lDays.value, noise: lNoise.checked, cats: lCatBoxes.filter(b => b.checked).map(b => b.value)});
}
async function loadLog(force = false) {
  const key = logQuery();
  if (key === L.key && !force) return;
  L.key = key; L.loading = true;
  document.getElementById("lStatus").textContent = "loading…";
  try {
    const r = await apiJson(`api/log?${key}`);
    if (key !== L.key) return;
    Object.assign(L, {rows: r.rows, next: r.next, newest: r.newest, error: null, journal: data && data.freshness && data.freshness.journal});
  } catch (err) { L.error = err.message; }
  L.loading = false;
  renderLog();
}
async function moreLog() {
  if (!L.next || L.loading) return;
  const key = L.key; L.loading = true;
  try {
    const r = await apiJson(`api/log?${key}&before=${encodeURIComponent(L.next)}`);
    if (key === L.key) { L.rows = L.rows.concat(r.rows); L.next = r.next; }
  } catch (err) { L.error = err.message; }
  L.loading = false;
  renderLog();
}
async function tailLog() {   // new journal lines since the newest row: prepend them
  const j = data && data.freshness && data.freshness.journal;
  if (!L.newest || L.loading || j === L.journal) return;
  const key = L.key; L.journal = j; L.loading = true;
  try {
    const r = await apiJson(`api/log?${key}&after=${encodeURIComponent(L.newest)}`);
    L.loading = false;
    if (key !== L.key) return;
    if (r.reset) return loadLog(true);
    L.newest = r.newest || L.newest;
    if (r.rows.length) {
      const before = document.documentElement.scrollHeight, y = window.scrollY;
      r.rows.forEach(x => L.fresh.add(x.id));
      L.rows = r.rows.concat(L.rows);
      renderLog();
      if (y > 0) window.scrollBy(0, document.documentElement.scrollHeight - before);  // keep your place unless at the top
      setTimeout(() => { r.rows.forEach(x => L.fresh.delete(x.id)); }, 2500);
    }
  } catch { L.loading = false; }
}
function openBodyIn(id, name) {
  id = String(id);
  view = "here"; store.set("view", view);
  pinnedSystem = data.position && String(data.position.id64) === id ? null : id;
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
  document.getElementById("lMore").hidden = !L.next;
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
async function loadBio() {
  const key = `${bDays.value}|${data && data.scan_version}`;
  if (key === bioKey) return;
  bioKey = key;
  document.getElementById("bStatus").textContent = "loading…";
  try { const b = await apiJson(`api/organics?days=${bDays.value}`); if (key === bioKey) bioData = b; else return; } catch (err) { bioData = {error: err.message}; }
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
  const key = `${hDays.value}|${data && data.scan_version}`;
  if (key === histKey) return;
  histKey = key;
  document.getElementById("hStatus").textContent = "loading…";
  try { const h = await apiJson(`api/history?days=${hDays.value}`); if (key === histKey) histData = h; else return; } catch (err) { histData = {error: err.message}; }
  renderHistory();
}
const openSessions = new Set();
function renderHistory() {
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
const M = {data: null, key: null, loading: false, proj: [], hover: null, drag: null,
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
mEl("mTop").onclick = () => { M.yaw = 0; M.pitch = Math.PI / 2; drawMap(); };
mEl("mReset").onclick = () => { M.yaw = -0.5; M.pitch = 0.45; M.zoom = 1; drawMap(); };

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
  const dpr = window.devicePixelRatio || 1;
  const w = mEl("mapWrap").clientWidth;
  const h = Math.max(360, Math.min(innerHeight - mapCanvas.getBoundingClientRect().top - 90, 900));
  if (mapCanvas.width !== Math.round(w * dpr) || mapCanvas.height !== Math.round(h * dpr)) {
    mapCanvas.width = Math.round(w * dpr); mapCanvas.height = Math.round(h * dpr); mapCanvas.style.height = h + "px";
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
    return {sx: w / 2 + x1 * scale * k, sy: h / 2 - y2 * scale * k, depth, k, ok: D + depth > D * 0.05};
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
  // Boosted range from here: neutron cone ×4, white dwarf ×1.5.
  const hs = d.here_star, mult = hs === "N" ? 4 : /^D/.test(hs || "") ? 1.5 : 0;
  if (jr && mult) ringAt(jr * mult, "#5ce1e6", [2, 6]);

  const bms = bmMap(), prevId = data.previous && String(data.previous.id64),
        targetId = data.target && String(data.target.id64), hereId = String(c.id64);
  const byColour = mSettings.color === "star";
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

  // Legend.
  const dot = (color, text, ring) => `<span><i class="${ring ? "ring" : ""}" style="background:${color};border-color:${color}"></i>${text}</span>`;
  mEl("mLegend").innerHTML = byColour
    ? [...new Set(d.points.map(pt => starGroup(pt.star)).concat((d.path || []).map(j => starGroup(j.star_class))))]
        .filter(Boolean).sort().map(k => dot(STAR_COLOURS[k] || C.muted, STAR_NAMES[k] || k)).join("") +
      dot(C.muted, "class unknown", true)
    : [dot(C.accent, "you are here"), dot(C.gold, "you discovered it"), dot(C.info, "visited"),
       dot(C.muted, "known, has bodies"), dot(C.muted, "no scan data", true),
       dot(C.text, "your route plots only", true), `<span style="color:${C.accent}">— your path</span>`,
       `<span style="color:${C.accent}">◌ previous / target</span>`, `<span style="color:${C.gold}">★ bookmark</span>`]
       .concat(d.boost ? [`<span style="color:#5ce1e6">▵ neutron · □ white dwarf · ┄ boosted range</span>`] : []).join("");
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
  const what = String(c.id64) === pt.id ? "you are here" : pt.first ? "you discovered it" : pt.visited ? "visited"
    : pt.kind === "route" ? "only in your route plots" : pt.scanned ? "known, has scanned bodies"
    : pt.kind === undefined ? (pt.carrier ? `your carrier ${esc(pt.carrier)} is here` : boost) : "no scan data";
  const what2 = what + (pt.carrier && !what.includes("carrier") ? ` · your carrier ${esc(pt.carrier)} is here` : "") + (boost && what !== boost ? " · " + boost : "");
  const b = bmMap()[pt.id];
  return `<h3>${esc(pt.name)}</h3><div>${dd.toFixed(2)} ly away · ${what2}</div>` +
    (pt.star ? `<div>main star: <span class="mono">${esc(pt.star)}</span></div>` : "") +
    (pt.arrived ? `<div class="unk">on your path: arrived ${esc(pt.arrived.replace("T", " ").replace("Z", ""))}</div>` : "") +
    (b ? `<div class="sec">★ ${esc(b.note) || "bookmarked"}</div>` : "") + `<div class="sec unk">click to copy name</div>`;
}
mapCanvas.addEventListener("pointerdown", e => {
  M.drag = {x: e.clientX, y: e.clientY, yaw: M.yaw, pitch: M.pitch, moved: false};
  mapCanvas.setPointerCapture(e.pointerId); mapCanvas.classList.add("dragging");
});
mapCanvas.addEventListener("pointermove", e => {
  if (M.drag) {
    const dx = e.clientX - M.drag.x, dy = e.clientY - M.drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) M.drag.moved = true;
    M.yaw = M.drag.yaw + dx * 0.008;
    M.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, M.drag.pitch + dy * 0.008));
    hidePop(); M.hover = null; drawMap(); return;
  }
  const q = mapHit(e);
  if ((q && q.pt) !== (M.hover && M.hover.pt)) { M.hover = q; drawMap(); }
  if (q) { popId = "map"; pop.innerHTML = mapPopHtml(q.pt); pop.style.display = "block"; placePop(e.clientX, e.clientY); }
  else if (popId === "map") hidePop();
});
mapCanvas.addEventListener("pointerup", e => {
  const click = M.drag && !M.drag.moved; M.drag = null; mapCanvas.classList.remove("dragging");
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
const sLabels = {stars: "Star", planets: "Planet", rings: "Ring", hotspots: "Hotspot", bio: "Bio"};
// ---- Search results: body pop-ups and a body panel beside the results ----
const sysDetail = {};   // id64 -> system detail (or a pending promise), for the pop-ups
function systemFor(id) {
  if (!sysDetail[id]) sysDetail[id] = apiJson(`api/system/${id}`).then(d => (sysDetail[id] = d)).catch(err => (sysDetail[id] = {error: err.message}));
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
  rows.sort(sortKey === "name"
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
  try {
    do {
      const r = await fetch("api/search");
      search = await r.json();
      render();
      if (search.running) await new Promise(res => setTimeout(res, 800));
    } while (search.running);
  } catch {} finally { searchPolling = false; }
}
sForm.addEventListener("submit", async e => {
  e.preventDefault(); saveForm();
  search = {running: true, status: "searching…", results: []}; render();
  try {
    await fetch("api/search", {method: "POST", headers: {"Content-Type": "application/json"},
                               body: JSON.stringify(formParams())});
  } catch (err) { search = {status: "search failed: " + err.message, results: []}; render(); return; }
  pollSearch();
});
pollSearch();  // show the last search's results after a reload

document.querySelectorAll("th[data-sort]").forEach(b => b.onclick = () => {
  sortKey = b.dataset.sort; store.set("sort", sortKey); render();
});
const oneJump = document.getElementById("oneJump");
oneJump.checked = store.get("oneJump", false);
[showVisited, showExplored, oneJump].forEach(c => c.onchange = () => { store.set(c.id, c.checked); render(); });
// Click a system name (list rows or the current system in the header) to copy it.
function toast(msg) {
  const t = document.getElementById("toast"); t.textContent = msg;
  t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1400);
}
function copyText(text) {
  const fallback = () => {
    try {
      const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand("copy"); ta.remove();
      toast(ok ? "copied " + text : "copy failed — select the name and copy it by hand");
    } catch { toast("copy failed — select the name and copy it by hand"); }
  };
  if (navigator.clipboard && navigator.clipboard.writeText)
    navigator.clipboard.writeText(text).then(() => toast("copied " + text), fallback);
  else fallback();  // http:// from another machine is not a secure context
}
document.addEventListener("click", e => {
  const cell = e.target.closest("#rows td.bodies[data-id]");
  if (cell) return cell.dataset.id === pinnedSystem ? unpinSystem() : pinSystem(cell.dataset.id);  // same system again closes it
  const bm = e.target.closest("[data-bm]");
  if (bm) return openBookmark(bm.dataset.bm, bm.dataset.name);
  const td = e.target.closest("td.name, #here .copy"); if (!td) return;
  copyText(td.dataset.name);
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
function popHtml(s) {
  const src = s.source === "own" ? "not in Spansh · your scans" : s.own_scans ? "Spansh + your scans" : "";
  let h = `<h3>${esc(s.name)}${src ? ` <span class="src">${src}</span>` : ""}</h3>`;
  if (!s.bodies_known) return h + `<div class="unk">No bodies known yet.</div>`;
  h += `<div>${s.body_count ? `${s.bodies_known} of ${s.body_count} bodies known`
                             : `${s.bodies_known} bod${s.bodies_known > 1 ? "ies" : "y"} known, total unknown (no FSS honk reported)`}</div>`;
  h += firstsHtml(s.firsts) + list("Stars", s.star_types) + list("Planets", s.planet_types);
  if (s.bio_potential) h += `<div class="sec"><div class="lbl">🧬 Exobiology</div><div>up to ${credits(s.bio_potential)} cr across ${s.bio_bodies_guessed} bod${s.bio_bodies_guessed === 1 ? "y" : "ies"} <span class="unk">(spawn-rule estimate; the Here view shows which genera)</span></div></div>`;
  const d = s.detail;
  if (!d) return h + `<div class="sec unk">Loading ring, belt and signal details…</div>`;
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
    const key = "sbody" + td.dataset.sys + "|" + td.dataset.sbodypop, sd = sysDetail[td.dataset.sys];
    popId = key;
    if (!sd || sd instanceof Promise) {
      pop.innerHTML = `<div class="unk">loading ${esc(td.dataset.sbodypop)}…</div>`; pop.style.display = "block"; placePop(x, y);
      systemFor(td.dataset.sys).then(() => { if (popId === key) showPop(td, x, y); });
      return;
    }
    const b = sd.bodies && sd.bodies.find(q => q.name === td.dataset.sbodypop);
    if (!b) { pop.innerHTML = `<div class="unk">${esc(sd.error || "no details known for this body")}</div>`; pop.style.display = "block"; placePop(x, y); return; }
    pop.innerHTML = bodyPopHtml(b).replace("click for everything known", "click for the details panel"); pop.style.display = "block"; placePop(x, y);
    return;
  }
  if (td.dataset.bodypop !== undefined) {
    const b = hereData && hereData.bodies && hereData.bodies.find(x => x.name === td.dataset.bodypop);
    if (!b) return hidePop();
    popId = "body" + td.dataset.bodypop; pop.innerHTML = bodyPopHtml(b); pop.style.display = "block"; placePop(x, y);
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
  const s = data && data.systems.find(s => String(s.id64) === td.dataset.id);
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

let runId = null, lastArrival = null, lastUnsoldLevel = null, lastCarrierTs = null, lastCodexTs = null, lastDockTs = null;
function onData() {
  const br = data.bio_rules, brEl = document.getElementById("bioRules");
  if (brEl) brEl.textContent = br
    ? `Species guesses use the BioScan spawn rules (${br.species} species, updated ${(br.generated || "").slice(0, 10)}); each start fetches newer rules from GitHub when there are any.`
    : "Spawn rules missing (bio_rules.json) and could not be downloaded: bodies get no species guesses. Run python3 ed_bio.py --update-rules once online.";
  if (data.run_id !== runId) {  // first payload, or the server was restarted: no sounds for old state
    runId = data.run_id; lastSeq = data.target ? data.target.seq : 0;
    const df = data.defaults || {};
    if (bioMin == null) { bioMin = df.bio_min ?? 10000000; bioMinEl.value = bioMin; }
    showHl(); showMaxBonus();
    if (store.get("sound", null) === null && df.sounds != null) { soundOn = !!df.sounds; drawSoundBtn(); }
    lastArrival = data.arrival ? data.arrival.seq : 0;
    lastUnsoldLevel = unsoldLevel(data.unsold); lastCarrierTs = data.carrier && data.carrier.ts;
    lastCodexTs = (data.codex_recent || [])[0] && data.codex_recent[0].ts;
    lastDockTs = data.docked && data.docked.ts;
    return;
  }
  const dk = data.docked, dl = unsoldLevel(data.unsold);
  if (dk && dk.ts !== lastDockTs) {   // just docked: the moment to sell, if it is worth it
    if (lastDockTs !== undefined && (dk.has_uc || dk.has_vista) && dl && dl !== "ok")
      notify("unsold", `Docked at ${dk.station} — ${credits(data.unsold.total)} cr to sell`, dk.has_uc ? "Universal Cartographics is here." : "Vista Genomics is here.");
    lastDockTs = dk.ts;
  } else if (!dk) lastDockTs = null;
  const t = data.target;
  if (t && t.seq !== lastSeq) {
    if (t.fresh && soundOn && t.sound) play(t.sound);
    if (t.fresh && t.status === "unreported") notify("discovery", "New discovery targeted", `${t.name} is not in Spansh or EDSM`);
    const l = worthLeavingFor(t.leaving);
    if (t.fresh && l && !l.clean) {
      if (soundOn) setTimeout(() => play("alert"), t.sound ? 1600 : 0);
      notify("leaving", "Leaving with unfinished work", leavingText(t.leaving).replace(/<[^>]+>/g, "").replace(/^Leaving with unfinished work: /, ""));
    }
    const f = data.fuel;
    if (t.fresh && f && f.live && f.pct != null && f.pct < 30 && t.star_class && !/^[OBAFGKM](_|$)/.test(t.star_class)) {
      if (soundOn) setTimeout(() => play("alert"), 800);
      notify("fuel", `Fuel ${f.pct}% and ${t.name} is not scoopable`, `${t.star_class} star · ${f.since_scoop} jumps since the last scoop`);
    }
    lastSeq = t.seq;
  }
  const a = data.arrival;
  if (a && a.seq !== lastArrival) {
    if (a.wrong && soundOn && a.sound) play(a.sound);  // correct a wrong call out loud
    if (a.wrong) notify("arrival", a.undiscovered ? `${a.name}: actually undiscovered` : `${a.name}: already discovered`,
                        a.undiscovered ? "the fanfare was deserved after all" : "someone was here before you");
    lastArrival = a.seq;
  }
  const u = data.unsold, ulvl = unsoldLevel(u);
  if (ulvl && ulvl !== lastUnsoldLevel) {
    if (lastUnsoldLevel && ulvl !== "ok") notify("unsold", `Unsold data: ${credits(u.total)} cr on board`, ulvl === "urgent" ? "Go sell." : "Worth selling soon.");
    lastUnsoldLevel = ulvl;
  }
  const c = data.carrier;
  if (c && c.ts !== lastCarrierTs) {
    if (lastCarrierTs) { notify("carrier", `${c.name} is at ${c.system}`, c.distance != null ? `${c.distance} ly from you` : ""); toast(`🚢 ${c.name} arrived at ${c.system}`); }
    lastCarrierTs = c.ts;
  }
  const k = (data.codex_recent || [])[0];
  if (k && k.ts !== lastCodexTs) {
    if (lastCodexTs) { const what = k.voucher ? `codex voucher · ${k.voucher.toLocaleString()} cr` : "new to your codex for this region"; notify("codex", `📖 ${k.name}`, what); toast(`📖 ${k.name} — ${what}`); }
    lastCodexTs = k.ts;
  }
}
// ---- alert settings ----
const alertDialog = document.getElementById("alertDialog");
document.getElementById("alertOpts").innerHTML = ALERTS.map(([k, label]) =>
  `<label><input type="checkbox" data-alert="${k}"> ${esc(label)}</label>`).join("");
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
const thresholdEls = {};
for (const [id, key] of [["unsoldWarn", "warn"], ["unsoldUrgent", "urgent"]]) {
  const el = thresholdEls[id] = document.getElementById(id);
  const fill = () => { const [w, g] = unsoldThresholds(data && data.unsold); el.value = key === "warn" ? w : g; };
  fill(); el.addEventListener("focus", fill);
  el.onchange = () => {
    const v = Number(el.value);
    unsoldCfg[key] = el.value.trim() === "" || !isFinite(v) || v <= 0 ? null : Math.round(v);   // blank or 0 = server default
    if (unsoldCfg.warn != null && unsoldCfg.urgent != null && unsoldCfg.warn > unsoldCfg.urgent) {
      if (key === "warn") unsoldCfg.urgent = unsoldCfg.warn; else unsoldCfg.warn = unsoldCfg.urgent;
    }
    store.set("unsoldCfg", unsoldCfg); render();
    for (const f of Object.values(thresholdEls)) f.dispatchEvent(new Event("focus"));
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
function hotClasses(b) {
  return (b.base_value != null && b.base_value >= hlLevel("body") ? " hot" : "") + (bioWorth(b) >= hlLevel("bio") ? " biohot" : "");
}
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
    store.set("highlightCfg", hlCfg); showHl(); renderHere();
  };
}
showHl();
const bioMinEl = document.getElementById("bioMin");
bioMinEl.value = bioMin ?? "";
bioMinEl.onchange = () => {
  const v = Number(bioMinEl.value);
  bioMin = bioMinEl.value.trim() === "" || !isFinite(v) || v < 0 ? ((data && data.defaults && data.defaults.bio_min) ?? 10000000) : Math.round(v);
  bioMinEl.value = bioMin; store.set("bioMin", bioMin); render();
};
document.querySelectorAll("[data-reset]").forEach(r => r.onclick = e => {
  e.preventDefault();   // the link sits inside a <label>: don't let the click also toggle or focus its input
  const id = r.dataset.reset;
  if (id === "maxBonus") { maxBonusCfg = null; store.set("maxBonus", null); showMaxBonus(); renderHere(); }
  else if (id === "hlBody" || id === "hlBio") { hlCfg[id === "hlBody" ? "body" : "bio"] = null; store.set("highlightCfg", hlCfg); showHl(); renderHere(); }
  else if (id === "bioMin") { bioMin = (data && data.defaults && data.defaults.bio_min) ?? 10000000; bioMinEl.value = bioMin; store.set("bioMin", bioMin); }
  else { unsoldCfg[id === "unsoldWarn" ? "warn" : "urgent"] = null; store.set("unsoldCfg", unsoldCfg); thresholdEls[id].dispatchEvent(new Event("focus")); }
  render();
});
function drawAlertsBtn() { document.getElementById("alertsBtn").classList.toggle("on", !!alertCfg.enabled); }
document.getElementById("alertsBtn").onclick = () => alertDialog.showModal();
drawAlertsBtn();

let disconnected = null;
function setConnected(ok) {
  if (ok && disconnected) { disconnected = null; if (data) render(); }
  else if (!ok && !disconnected) {
    disconnected = new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
    if (data) render();
  }
}
async function poll(once = false) {
  try {
    const r = await fetch(`api/nearby?since=${runId}:${version}`);
    if (r.status === 200) { data = await r.json(); version = data.version; setConnected(true); onData(); render(); }
    else if (r.status === 204) setConnected(true);
    else setConnected(false);
  } catch { setConnected(false); }
  if (!once) setTimeout(poll, 1000);
}
poll();
