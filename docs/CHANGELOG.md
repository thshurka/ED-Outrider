# Changelog

Newest first, one entry per commit.

## 2026-10-01 · The page fits the window; header tiles fold into one line; compact tables
- On a window of at least 900 × 600 (not Now) the page no longer scrolls: the header stays, the view fills the
  rest, and its lists scroll in bordered panes with sticky column headings. Overview: Nearby and This system each
  the full height, the body table scrolling above the surface map or body panel (stacked: the map or panel beside
  the table). Here: the table and the body panel scroll apart. Nearby, Samples, Bookmarks, History, Log, Materials,
  My firsts: one pane under the view's controls. Search: one pane for the forms and results. Map: the canvas fills
  the view. Smaller windows and phones scroll the page as before; a header too tall for the window falls back too.
- Page Up/Down, Home and End scroll the view's pane when nothing else has the focus; the Log fetches more when its
  pane nears the end; a row brought into view (Here's in-game target) and the Log's new rows scroll the pane.
- ▴ beside the tiles folds them into one line in the tiles' colours (per browser: `tilesCollapsed`).
- Compact tables: a table wider than its box (by fit, not screen size: a pane, the Overview's split, a phone) shows
  short forms (HMC, Rocky ice, G star, WD DA, CO₂; Nearby's status as —, 62%, ✓, ?, 🗺3; shorter headings), and if
  that is not enough, a tighter level that merges or drops low-value columns (Nearby: status under the name, notable
  under the bodies; Here: atmosphere under gravity, ls under the class, firsts under the name, mining in Bio, Now under
  Max; My firsts, Samples, History, Log, Bookmarks likewise). The full text is in the title. A table that fits is unchanged.

## 2026-09-30 · Repository layout: the outrider package, resources/, data/, docs/
- The modules moved into the `outrider/` package without their `ed_` prefix (`outrider/bio.py`, ...); their
  command lines run as `python3 -m outrider.honk --test`, `python3 -m outrider.button --listen`,
  `python3 -m outrider.bio --backtest|--update-rules` and `python3 -m outrider.unsold`.
- Shipped data (`bio_rules.json`, `mining_odds.json`, `speech.json`) is in `resources/`; your own files
  (the database, `browser_defaults.json`, `speech_banned.json`, `backups/`, `piper-voices/`) default to `data/`,
  git-ignored as a whole. Relative config paths are still relative to the repository folder.
- The notes moved from `reference/` to `docs/`, the screenshots to `docs/images/`; local scripts to `scripts/`.

## 2026-09-30 · Rig spacing ring defaults to 50 m (`be16993`)
- The surface map's rig spacing ring is 50 m by default (two rigs were allowed about 44-51 m apart in a test;
  the game draws a 50 m ring). Still a per-browser setting and `[defaults] rig_spacing`.

## 2026-09-30 · My firsts: a rescan checklist for lost first discoveries (`dd66f2e`)
- "within N ly" beside "show lost" lists systems whose data went down with a ship, nearest first.
- Rows stay while you rescan: amber part-way ("rescanned 5 of 12", "1 map to redo"), green when everything is
  back, gone once sold. Hover a part-way row for what is left, with values.
- Lost scan, lost map and lost total columns, sortable.

## 2026-09-30 · Review fixes and additions: Rhino state, sales, fuel, voice, firsts watch, security (`567e7ae`)
- Surface map fixes: the Rhino is remembered when you step out; rigs are lost on death, SRV loss and relog.
- Sales and exobiology: per-run x5 pricing, multi-part Vista visits counted once, the "data still aboard" line
  waits 90 s; fuel constants for every drive size (the Caspian's Mk II included), engineering applied at once.
- Cross-site GETs refused except `/api/status`; a "rigs still out" warning when you dock the Rhino.
- Status report leads with the targeted body; optional "mapped" call-out; mining search (Local); core module
  health under a configurable level; "This session" on Now.

## 2026-09-30 · Surface map on Now; Rhino rig marking with the co-pilot button (`829c786`)
- A heading-up map on Now below 1,000 m: you, the ship, bio samples with spacing rings, rigs 1-6, saved mining
  sites and targeted mining locations, with a legend.
- In the Rhino the co-pilot button places a rig 7 m behind you or picks up the one you are next to; collections
  are added to the rig from the refined tons.
- Rig leash warnings at 3.5 and 4.5 km; mining sites per body in Materials.
- New settings: `surface_alt`, `rig_spacing`, `surface_map_min`, `surface_map_strip`, `rig_warn`.

## 2026-09-30 · Mining locations in Here, what you mined per body, unsold-after-sale alert (`7fa44ec`)
- A ⛏ column in Here with each body's planetary mining locations and a survey-odds tooltip (EDFM, CC BY-SA 4.0).
- "Mined previously": what your SRV refined on each body, rebuilt from the journals.
- A spoken line when a sale leaves data aboard (50 systems per page), and the same after a Vista Genomics sale.

## 2026-09-29 · Server audio, hush and co-pilot button, fuel model, firsts watch, verified backups (`fc9cfcb`)
- Speech and sounds can play on the PC itself; hush for 10/30 minutes or until the next jump; a read-only HOTAS
  co-pilot button; ban lines from the Spoken lines list.
- Fuel: laden range, fuel per hop and jumps left from your own jumps, a top-up warning.
- Exobiology priced run by run with an x5 check at each sale; a watch for unsold firsts someone else scanned.
- Backups checked before rotation; `--restore` and `--list-backups`.

## 2026-09-29 · Three review rounds of fixes, new call-outs, rolling backups and a safer server (`1bc2993`)
- A Host/Origin request guard: no cross-site key presses or journal reads.
- Fixes for repeated or wrong alerts, wrong values after sales and re-scans, and journal state after a failed read.
- One speaking window and a priority speech queue; many new call-outs (FSS debrief, approach, welcome back,
  ship-loss debrief, streaks); rolling automatic backups with a journal archive; portable settings.

## 2026-09-28 · Voice personalities, auto honk, bio colour check and a voice lab (`003c7be`)
- `speech.json` with 50 lines per alert in business, sarcastic and sweet, optional swearing versions, your names.
- Auto honk on Linux, pressing Primary Fire's binding from the controls preset.
- Colour-variant checks for exobiology; `voice_lab.py` for trying voices.

## 2026-09-28 · Review fixes; alerts, speech, ledger and exploration tools (`cac9b24`)
- Fixes for 44 review findings, including values outside the sphere and tailing that could freeze.
- Alerts with sound, notification and speech (Piper or the browser); long-polled updates.
- Trip ledger, top finds, ranks and career stats; Left behind, nearest sellers, jumponium, next stop, Now mode.

## 2026-09-28 · Exploration log, samples, materials and schematic (`a2410fe`)
- New views: Samples, Log, Materials; Here as list, tree or schematic.
- Search for unfinished exobiology; radius dropdown; highlight levels for valuable bodies and bio.
- Fixes for fresh installs failing on the first Scan and for Spansh genus codes.

## 2026-09-28 · Lost firsts hidden by default (`5de0b9f`)
- My firsts hides systems whose firsts were lost with a ship unless "show lost" is ticked.

## 2026-09-28 · README with screenshots; search radius step fixed (`710cfce`)
- A README with screenshots; the Search radius box takes any number.

## 2026-09-28 · Initial commit (`0046634`)
- First public version: Nearby, Here, Map, History, Search and bookmarks from your journals and Spansh, with
  the unsold-data estimate and the exobiology predictor.
