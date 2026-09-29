<p align="center">
  <img src="docs/banner.png" alt="ED Outrider" width="800">
</p>

<p align="center">
  <b>Know what's around you, what you're standing on, and what you're carrying — while you fly.</b>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&logoColor=white">
  <img alt="Runs locally" src="https://img.shields.io/badge/runs-on%20your%20PC-2ea44f">
  <img alt="No account" src="https://img.shields.io/badge/account-none%20needed-6aa8ff">
  <img alt="Uploads" src="https://img.shields.io/badge/uploads-never-ff8c1a">
</p>

---

ED Outrider reads your Elite Dangerous journals as you play and keeps one browser tab up to date
with the things an explorer keeps alt-tabbing to find out: **whether anyone has been to the
systems near you, what's in the one you're in, what your unsold data is worth, and whether you're
about to jump away from something you'll regret leaving.**

It runs on your own machine. It asks [Spansh](https://spansh.co.uk) (and
[EDSM](https://www.edsm.net) as a backup) what the community already knows about the systems
around you, then layers your own scans on top — nothing is ever uploaded.

<p align="center">
  <img src="docs/overview.png" alt="The Overview: the neighbourhood on the left, the system you're in on the right" width="900">
</p>

## ✨ At a glance

| | |
|---|---|
| 🔭 **Find the undiscovered** | Every known system within 25 ly is listed. If the galaxy map shows one that *isn't* on the page, nobody with an uploader has been there. |
| 🔊 **Hear it before you jump** | Target a system and get a fanfare if it's a brand-new discovery, a cheerful note if it's known but unscanned, a thud if it's been done. Arrive somewhere nobody has been and the voice says so. |
| 🪐 **See the whole system** | Every body: value as scanned and if mapped, gravity, atmosphere, rings with hotspots and density, curiosities, and which exobiology species it could hold — before you probe or land. |
| ⚠️ **Don't leave money behind** | Target the next system with mapping or exobiology worth over your thresholds still undone (or a first-discovered Earth-like, water or terraformable world unmapped) and the page says so, out loud if you like. Ordinary systems stay quiet. |
| 💰 **Know what's on board** | Unsold cartographics and exobiology in credits, bonuses included, and how many of your 🏁 first-discovery tags are still unsold. Dock somewhere that buys it and it tells you to sell. |
| 📜 **Your logbook** | Every journal event in a searchable log, every exobiology sample with what became of it, and a schematic of the system you're in. |
| 🧭 **Decide where to go** | Visited systems nearby with work worth going back for, the nearest places that buy your data, your plotted route with its dry stretches, a bookmark as your next stop, notable stellar phenomena, and curiosities (ringed landables, close orbits, moons of moons…). |
| 🌿 **On the ground** | Landed or on foot, a strip shows what is left to sample on that body and counts down the metres to the next colony, then says "clear to sample". |
| 📈 **The long view** | Each trip from sale to sale with what it actually paid, what each ship loss cost, your most valuable finds, your ranks and the game's own career statistics. |
| 🗣 **A voice with personality** | Alerts spoken by a natural neural voice, down to business, sarcastic or sweet (with swearing versions if you like them), calling you by names you choose. It can also call out signal counts as the FSS finds them and where your frame shift drive is taking you. |
| 🎯 **Auto honk** | On Linux, Outrider can fire the Discovery Scanner for you on arrival and tell you how many bodies the system has. |
| 🚢 **Everything else** | Fuel, jumps left and FSD boosts you can synthesise, your credits and ship, where your carrier is, the last codex entry, and a 3D map with your path, your discoveries and neutron stars for boosting. |

## 🚀 Getting started

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Python 3.11 or newer
.venv/bin/python ed_outrider.py
```

Open **<http://127.0.0.1:8025/>** and go fly.

> [!TIP]
> The first start reads all your journals (a few seconds); after that it only reads what's new.
> Journal folders are found automatically on Windows and Steam/Proton. Click the page once so
> the browser allows sound.

`requirements.txt` also installs two optional parts: **Piper** (`piper-tts`, about 100 MB with its
runtime) for a natural speaking voice, and on Linux **evdev** for auto honk (built from source, so it
needs your distribution's Python development headers). Leave either line out if you don't want it;
Outrider works without them.

## 🖥️ The views

<table>
<tr>
<td width="50%" valign="top">
<b>Nearby</b> — every known system within range: distance, how much of it has been scanned,
the main star and whether you can scoop it, notable bodies, curiosities (🔭, hover for which bodies and
why) and a credit estimate. Sort by
distance, name or value; hide visited or fully scanned systems. The radius (20–50 ly) is a dropdown in
the header's Where tile; `radius_choices` in the config file offers other sizes.
<br><br><img src="docs/nearby.png" alt="Nearby systems">
</td>
<td width="50%" valign="top">
<b>Here</b> — the current system body by body, sorted by value, with bio and geo signal counts and a 🌋
on bodies with volcanism (bright where the body is landable, so its geological sites are reachable). Before
the DSS each bio signal shows the genera it could be; when a body has fewer signals than possible genera it
says "one of these" with the range they could pay. Hover a body for a summary, click it for everything
known: composition, orbit, rings, bio, curiosities, your firsts.
<br><br><img src="docs/here.png" alt="The current system">
</td>
</tr>
<tr>
<td width="50%" valign="top">
<b>Map</b> — a 3D view that fills the window: left-drag to rotate, right-drag to move, scroll to
zoom. Your path in orange, systems you first discovered in gold, visited ones in blue; tick <i>boost
stars</i> for neutron stars and white dwarfs, with your boosted range drawn when you're at one.
<br><br><img src="docs/map.png" alt="The 3D map">
</td>
<td width="50%" valign="top">
<b>History</b> — your sessions: jumps, light-years, systems first discovered, bodies mapped,
samples taken, codex entries, with an all-time row, a "since your last sale" row and the game's
own career statistics on top. Below: every trip from sale to sale with what Universal Cartographics and
Vista Genomics actually paid (and, from now on, how close Outrider's estimate was), the credits per hour
and per jump, what each ship loss cost, and your 25 most valuable finds. Expand a session for its systems.
<br><br><img src="docs/history.png" alt="History">
</td>
</tr>
<tr>
<td width="50%" valign="top">
<b>Samples</b> — every exobiology sample run: species, variant, body, value (×5 where nobody had set
foot), and whether it is still <i>aboard</i>, <i>sold</i> or was <i>lost</i> with a ship. Filter by
state or text, sort any column, export. Your codex entries sit underneath.
<br><br><img src="docs/samples.png" alt="Samples">
</td>
<td width="50%" valign="top">
<b>Log</b> — every journal event, newest first, one readable line each: jumps, scans, signals,
samples, docking, sales, synthesis. Filter by category and time, search any text, click a row for
the raw event. It reads the journal files directly and adds new events as they happen.
<br><br><img src="docs/log.png" alt="The log">
</td>
</tr>
<tr>
<td width="50%" valign="top">
<b>Materials</b> — raw, manufactured and encoded materials against their storage caps, and how
many FSD injections (and fuel, repair and limpet syntheses) you can make right now. The FSD boost
count also sits in the header's fuel tile.
<br><br><img src="docs/materials.png" alt="Materials">
</td>
<td width="50%" valign="top">
<b>Schematic</b> — the <b>Here</b> view switches between <i>list</i> (most valuable first), <i>tree</i> (the same
table in orbital order, moons indented under their planets) and <i>schematic</i>. In the Here tab, <i>split</i>
keeps the schematic below whichever of list or tree is on top, and is on by default; the Overview pane
remembers its own choice. The schematic draws the
system as stars with their planets left to right and moons stacked underneath, barycentres boxed,
with your firsts, bio and geo signals, rings and values on each body. Hover and click work as in
the list.
<br><br><img src="docs/schematic.png" alt="The system schematic">
</td>
</tr>
<tr>
<td width="50%" valign="top">
<b>Search</b> — systems with particular stars (or just <i>scoopable</i>), planet types, ring
types, ring hotspot minerals, or exobiology you haven't finished sampling (optionally only where the
rest pays over 1, 5 or 10 million, bonuses left out) within a radius. <i>Local</i> searches what Outrider already knows;
<i>Spansh (online)</i> searches everything anyone has reported.
<br><br><img src="docs/search.png" alt="Search">
</td>
<td width="50%" valign="top">
<b>My firsts</b> — every visited system still holding first-discovery data you haven't sold, and
what it's worth, and <b>Left behind</b>: visited systems nearby with bodies still to find, mapping or
bio over your thresholds. Plus <b>Bookmarks</b>: star a system, leave yourself a note, and make it your
<b>next stop</b> (its distance shows in the header until you arrive).
<br><br><img src="docs/firsts.png" alt="My firsts">
</td>
</tr>
</table>

The **Overview** (top of the page) shows Here and Nearby together — drag the divider, swap sides,
or stack them. **Now** is the cockpit view for a second monitor or a tablet: the system, the target,
fuel, and what is left here (or on the body you are standing on) in big text. Open it directly with
`http://127.0.0.1:8025/?mode=now`; tap to go back.

The header also shows the galactic region you are in, your ranks, a live countdown when your carrier has
a jump booked, the hull when it is damaged, the FSD injections your materials allow, the nearest places to
sell, and a one-click backup of the database and journals (into `backups/` next to the script).

## 🔔 Alerts and thresholds

Alerts fire only for something out of the ordinary: a new discovery targeted, arriving somewhere nobody
has been, leaving a system with work worth coming back for (mapping or bio over your highlight levels,
or a first-discovered Earth-like, water, ammonia or terraformable world), low fuel where you cannot
scoop, a valuable body the moment the FSS resolves it, docking with data to sell and what you banked
when you sold, hull damage, heat damage and interdiction, unsold data crossing a threshold, your carrier
arriving or leaving without you, a new codex entry. Ordinary systems stay quiet.

Each alert can play its own sound (🔊), show a desktop notification, and be spoken (🗣), chosen per
alert in the **🔔 alerts** dialog. Targeting a system plays its sound (the fanfare for an unreported
system); arriving there is announced by the voice, and the arrival only plays a sound to correct a
targeting call that turned out wrong. The same dialog holds the thresholds:

- **Exobiology** — only count a body as unfinished if a single body could pay over a certain
  amount (default 10 million), so one bacterium doesn't nag you.
- **Unsold data** — when the header turns amber (default 50 million on board) and red (250 million),
  or as a multiple of your ship's rebuy.
- **Body highlights** — in Here, a body's row turns green when its scan + map data pays over a level
  (default 500 thousand), and its bio turns violet when its species could pay over another (default
  10 million). Both use straight payouts with no first-discovery, mapping or footfall bonus. The
  config file's `body_highlight_level` and `biology_highlight_value` set the defaults.
- **Max with or without bonuses** — whether Here's Max column (and the system's max total) counts
  first-discovery, first-mapped and first-footfall bonuses. On by default; the config file's
  `body_max_value_include_bonus` sets it. Now always includes the bonuses you have earned.

Everything you change there is remembered by your browser; the config file sets what a new browser starts with.

## 🗣 The voice

Alerts are spoken when 🗣 in the header is on. **Piper**, a neural voice that runs on your CPU, sounds
far better than the browser's own voice (fine on Windows and macOS, robotic on Linux), which is used
when Piper isn't installed. The voice (`voice` in the config file, default a southern English female
voice, with `voice_fallback` as the backup) is downloaded into `piper-voices/` the first time, and the
dialog switches between installed voices. A `.venv` next to the script is found even when you start
Outrider with plain `python3 ed_outrider.py`.

- **Personalities.** Every alert has fifty versions in each personality in `speech.json`: down to
  business, sarcastic and sweet. Tick any mix and each alert picks a line at random from all of them,
  never one you have just heard. **With profanity** adds the swearing versions of sarcastic and sweet,
  used the percentage of the time set beside it (50% by default, `speech_profanity_pct`).
- **Your names.** Commander names are often unpronounceable, so the voice calls you by the names in
  **Call me** instead (comma separated, a random one each time; default "Boss, Hefay, Sir",
  `speech_names` in the config file).
- **Speed.** 1× is the voice's own pace (`speech_speed` sets the default). How much faster a setting
  sounds depends on the voice: some Piper models respond less than others.
- **Extra call-outs.** Signal counts as the FSS finds them ("2 Biological and 1 Geological Signals found
  on body A 3", one tick each, `speak_bio_signals` and `speak_geo_signals`); "Frame Shift Drive charging
  to jump to …", adding "This star is scoopable" when it is; a greeting when you load into the game and a
  goodbye when you quit.
- **Your own lines.** Edit `speech.json` to change lines, add your own, or add a whole personality (a new
  entry under `styles` and lists of that name). The page picks the changes up without a restart, and the
  dialog reports a mistake in the file while the last good copy stays in use. Numbers are spoken to a
  tenth at most ("52 million", not "52.0 million"). Notifications keep the plain wording.

**The voice lab.** `python3 voice_lab.py` opens a small window, separate from Outrider, for hearing the
lines before you settle on a voice. Pick any installed Piper voice (and its speaker, for voices with
several) and a speed, then play a random line from any alert and personality, filled in with made-up
values and your names, or type your own text; Save WAV keeps the audio. The lower half lists every Piper
voice on Hugging Face (English by default; clear the filter or type another language): double-click one
to download it into `piper-voices/`, where Outrider's voice picker finds it too. Outrider itself uses a
voice's first speaker.

## 🎯 Auto honk

On Linux, Outrider can fire the Discovery Scanner for you. On arriving in a system by hyperspace it waits
a moment, holds Primary Fire, checks the journal for the discovery scan, and says how it went ("System
Scan Completed, 12 Bodies discovered", or "System scan complete, and all bodies were found" when the
honk found everything). Systems you have already honked are left alone. It is off until you tick it in
the 🔔 alerts dialog.

- **The Discovery Scanner must be on primary fire** in the fire group that is active when you jump.
- **Primary Fire needs a keyboard binding** in Elite's controls, as its second binding if your trigger is
  the first. Outrider reads it from your active controls preset, modifiers too (such as the
  Alt + Alt + K that VoiceAttack profiles use), so there is nothing to set up; `[autohonk] key` in the
  config file overrides it, alongside the delay and hold time.
- **Try it first.** The dialog's *test in 5 s* button, or `python3 ed_honk.py --test 10` from a terminal,
  counts down (click into the game) and holds Primary Fire once. `python3 ed_honk.py --show` prints the
  binding it will press.
- It presses keys through a virtual keyboard (`evdev`; Steam's controller rule already gives you access),
  and the keys go to whichever window has focus, so switch it off before alt-tabbing away mid-jump.

## 🧭 Good to know

> [!NOTE]
> **"Not on the page" means "nobody with an uploader has reported it."** Players who don't run
> EDMC or a similar tool never reach Spansh or EDSM, so a missing system is *almost* certainly
> undiscovered. One second after you arrive, the arrival star's scan settles it — and the page
> (and the voice) says which it was.

- **Exobiology guesses are possibilities, not promises.** They come from each species' known spawn
  conditions (planet type, atmosphere, gravity, temperature, pressure, volcanism, the system's
  stars, the galactic region, nearby nebulae) as maintained by the
  [BioScan](https://github.com/Silarn/EDMC-BioScan) project, plus BioScan's colour check: a species
  that has never been seen around the kind of star a body orbits (or without certain surface
  materials) is ruled out, so Stratum never shows up at a G star. When a body has fewer signals than
  the genera it could hold, the page says so ("one of these, 1.0M to 19.0M") rather than guessing;
  the DSS tells which. The genus is usually right, the species within it sometimes isn't, so values
  are shown as "up to". The rules ship with Outrider
  and each start checks GitHub for a newer set (a couple of small requests; offline just keeps the
  copy you have).
- **Values are estimates** using the same formula as the community tools, first-discovery and
  first-mapping bonuses included. If you employ an NPC crew member, their cut comes off
  automatically, based on what your past sales actually paid.
- **Losing your ship loses your data**, and the page tracks it: discoveries and samples that went
  down with the ship show as *lost* until you scan them again.

## ⚙️ Settings

<details>
<summary>Outrider needs no configuration — but everything can be changed.</summary>
<br>

Copy `ed_outrider.toml.example` to `ed_outrider.toml` next to the script and edit the lines you
need. The file explains each setting, in five sections: `[journals]` (folders that aren't
auto-detected), `[server]` (address, port, radius, database, backups, the speech file), `[defaults]`
(what a new browser starts with: thresholds, highlights, voice, personalities, names, speed, signal
call-outs), `[spansh]` (request limits) and `[autohonk]`. `python3 ed_outrider.py --write-config` writes one with the settings
currently in effect, and command-line flags do the same for a single run
(`python3 ed_outrider.py --help`).

</details>

## 🔬 For the curious

<details>
<summary>What's in the box</summary>
<br>

| File | What it does |
|---|---|
| `ed_outrider.py` | The server and the journal reader |
| `static/` | The page (HTML, CSS, JS) — edit and reload |
| `ed_unsold.py` | The unsold-data estimate; also works on its own from the command line |
| `ed_log.py` | One-line summaries of journal events for the Log view, and the file reader behind it |
| `ed_materials.py` | Material names, grades and caps, synthesis recipes, and the running inventory |
| `ed_tts.py` | Spoken alerts with Piper (optional): voice selection, first-use download, synthesis |
| `speech.json` | The spoken alerts' lines: fifty per alert in each personality, yours to edit |
| `ed_speech.py` | Loads and checks `speech.json` (re-read when it changes); the alerts and the fill-ins each one has |
| `voice_lab.py` | A window for trying voices and lines, and downloading Piper voices |
| `ed_honk.py` | Auto honk: reads Primary Fire's keyboard binding and holds it through a virtual keyboard (Linux, optional); `--show`, `--test` |
| `ed_bio.py` | The exobiology predictor (spawn rules plus the colour check); `--backtest` scores it against your own journals, `--update-rules` fetches the rules by hand |
| `bio_rules.json` | The spawn rules, colour variants, nebula tables and region map, as fetched from BioScan, ExploData and klightspeed's region map; refreshed automatically |
| `tests/` | `python3 -m unittest discover tests`; `node tests/page_smoke.js <port>` for the page |

For overlays and other tools, `GET /api/status` returns a compact JSON status, and
`GET /api/status.txt?fields=system,region,fuel,target,unsold,body,sampling` one line for an OBS
text source. Both are read-only.

</details>

---

<p align="center">
Data from <a href="https://spansh.co.uk">Spansh</a> and <a href="https://www.edsm.net">EDSM</a>.
Exobiology spawn conditions are the community's work, as gathered by the Canonn Research Group and maintained in
<a href="https://github.com/Silarn/EDMC-BioScan">EDMC-BioScan</a>; the galactic region map is
<a href="https://github.com/klightspeed/EliteDangerousRegionMap">klightspeed's</a> (MIT); sample colony
distances and colour variants are from <a href="https://github.com/Silarn/EDMC-ExploData">EDMC-ExploData</a> (GPL-2.0).<br>
ED Outrider is free software under the <a href="LICENSE">GNU GPL v2 or later</a>.<br>
Elite Dangerous © Frontier Developments — this is a fan-made tool, not affiliated with Frontier.
</p>
