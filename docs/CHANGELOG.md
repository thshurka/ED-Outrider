# Changelog

Newest first, one entry per commit.

## 2026-10-03 · The tablet layout (tablet plan, phase 3)
- `http://<PC>:8025/tablet`: the same pages in a layout for a landscape tablet, in its first theme, LCARS. The
  status strip (system, fuel, unsold) and the link in words are on top. The pages are on the left in three groups of
  four, with no Overview. Hush, Status report and the last line said are in the footer. The right-hand column is kept
  for the game buttons of the next phase.
- On the tablet:
  - It never speaks or plays sounds; an alert is a banner (red for danger).
  - A tap on a table row opens all of its facts, with Show in Here and Bookmark.
  - It goes to Now while the surface map shows and back afterwards; the Now button says MAP.
  - Target next runs without a countdown.
  - The settings sheet has the theme, dim, the screen size and Sign out.
- The maps by touch, on any touch screen: one finger rotates the galaxy map, two fingers move it and a pinch zooms; on
  the Highway map two fingers move and pinch.
- The fonts are Antonio and Barlow Condensed (SIL OFL 1.1), shipped in static/fonts/. A font of your own goes in
  data/fonts/lcars-display.ttf.

## 2026-10-03 · Exact plots work again
- The Highway's Exact plots always failed with "Spansh: Unable to find route": Spansh's exact plotter now takes
  systems by id64, not by name (found in game). Outrider sends the id64 of where you are, of a system it already
  knows, or of the one Spansh's search finds by the exact name. The neutron plotter still takes names.
- A start system Spansh has not received yet (a new one; it reaches Spansh a minute or two after your visit) now says
  so: "Spansh has not received ... yet: try again in a minute".

## 2026-10-03 · A password for devices on your network (tablet plan, phase 1)
- `[server] password`: a tablet or phone signs in once on a small sign-in page and stays signed in, across Outrider
  restarts, until the password changes or it signs out. This PC itself never needs it. Empty (the default) asks
  nobody, as before. Five wrong tries a minute per device, then a wait.
- The Android app's side of it: `GET /api/version` (Outrider's version, the API level, the oldest app it works with,
  whether a password is set, whether you are signed in), `POST /api/auth/signin` and `/api/auth/signout`, a Bearer
  token as well as the cookie, and every error as `{error, code}`. An app that is too old gets 426.
- The page sends you to sign in again if its session ends (a changed password) instead of showing a dead link.

## 2026-10-03 · Split Here in halves; every table's sort reverses; Materials side by side
- Here in split: the body list and the schematic each take half the pane and scroll on their own.
- Every sortable table (Nearby, My firsts, Bookmarks, Search, Here): a second click on a heading reverses it, a
  third goes back to the table's default. Here's tree is never sorted (it keeps the orbits' order).
- Materials: Mining sites beside "Where to find FSD-injection materials" (one above the other on a narrow window).
- The lost-contact line is two sentences with a clear pause between them.
- The jump line starts 2.5 s after Status.json says you are entering hyperspace, with the tunnel itself.

## 2026-10-03 · Codex finds as a reason to stay is a config option; a tab icon
- `[defaults] codex_interesting` (on by default; also the alerts dialog's tick, per browser): off, a species new to
  your codex here (✦) no longer puts a body on Now's next stops or in the leaving warnings, nor in the leaving card's
  text, nor exempts it from "skip?"; the ✦ marks stay as facts.
- A tab icon (static/favicon.svg): a ship's arrowhead in a scanner ring, in the HUD's orange; an original drawing.

## 2026-10-03 · Here's sort reverses; "lost contact" in your own voice
- Here's Dist, Grav, Now and Max headings: a second click reverses the order (▴), a third goes back to the default,
  Max (found in game).
- "Lost contact with Outrider" plays in your Piper voice: the page makes the line in advance while Outrider can, and
  plays it when the link drops; without it, the alert sound, never the browser's robotic voice (found in game).

## 2026-10-03 · Docs and screenshots refreshed; the Rhino no longer forgotten at launch
- Launching the Rhino no longer loses track of it: Status.json written while the SRV deploys from the bay lacks the
  SRV flag, and a fallback took that for "back in the ship", so the co-pilot button gave the status report instead
  of marking a rig (found in game). The fallback now needs Status.json to say you are in your ship, a minute after
  the launch. PARSER_VERSION 39: the next start re-reads the journals once, which finds the vehicle you are in again.
- The line under the tiles says which vehicle you are in on a body, "On A 2 (in the Rhino)" or "(in the Nomad)", from
  the journal's launch (Status.json's SRV flag is the same for all of them); "the SRV" when the launch was never seen.
  The welcome back line likewise.
- AGENT_GUIDE, JOURNAL_REFERENCE, DESIGN_NOTES, README, the example config and the program's own description brought
  up to date with batches 4-12; every README screenshot taken again (the Highway one at a refuel stop).

## 2026-10-03 · Page suggestions (fix plan, batch 12)
- Here shows each genus's colony distance (metres between samples) before you land: in the row's tooltip, the
  body pop-up and the body panel (review S1).
- Here's body table sorts by distance, gravity, Now or Max (click the heading); not by bio, which has no single
  value (S19).
- A cut-off line in a header tile shows the whole of it on hover (S17, part a; wrapping is left for later).
- Search's mining: a mineral you have refined is searchable (Gold, water...), and the bodies where you refined it
  come first, "Gold 22 t mined here before", surveyed for it or not (S38).
- A link pill in the top bar: "linked · 2 s", "stale · 48 s" (no answer for longer than a long poll takes), "no link
  · retrying since 14:02"; the page still dims when the link is down (S41).
- The alerts dialog has a sticky row of section chips, and reopens at the last section used on this device (S43).
- Header tiles on this device: one line on a small window (under 800 px high or 1200 wide), always six, always one
  line, or as ▴/▾ sets them (shared, as before) (S44).
- The rig leash warning says which way the rig is: "Rig 1 is 3.6 kilometres away, behind you" (S9).

## 2026-10-03 · Voice (fix plan, batch 11)
- The jump line is said in the hyperspace tunnel, not over the game's countdown call (review S14), and has its own
  varied, bannable lines in speech.json, `fsd_charge`, 50 per personality list (S15).
- The next queued line is synthesised while the current one plays, on the PC and in the browser (S11).
- A Volume for Outrider's own voice and sounds, per device (S12).
- Your own alert sounds: `[speech] sound_dir`, a folder of `<name>.wav` files up to 3 s each (S16).
- The last line said, beside the header's icons, with ▶ to hear it again (S18).
- S23 (the status report composed on the server) is left to PLAN-tablet phase 6, as its review advised.

## 2026-10-03 · Robustness (fix plan, batch 10)
- One of the work steps after each journal read that keeps failing no longer stops the ones after it (auto-target,
  the quit backup, the clipboard copy only work within a short window); its error shows on the page and its
  traceback prints once (review S5).
- When Outrider stops answering for 30 s, the page says so once in the browser's own voice ("Lost contact with
  Outrider"), and again when it is back (S13).
- The page's data (the long poll) is gzipped, about 4x smaller (S20).
- On a jump, Nearby shows what the local cache already knows around you at once, while Spansh is asked (S6).

## 2026-10-03 · Spansh, config, backups and restore, start-up (fix plan, batch 9)
- With Spansh down, systems cached from its earlier searches still read as Spansh's, not "not in Spansh"; EDSM's own
  records stay EDSM's (review F27). A failed body refetch keeps the cached full dump instead of the search's partial
  one (F28); a "no dump" answer gives way to the bodies the search now lists (F29). EDSM's fallback list asks for at
  most 100 ly, its limit, and the status says so (F48).
- The example config, `--write-config` and `--legacy`'s help say what the code does: legacy folders are
  auto-detected only while `live` is unset too (F18). The README says what plain `python3 ed_outrider.py` finds in a
  `.venv` (Piper and evdev, not aiohttp) (F47).
- A `[server] host` that is not this machine's (a changed LAN address, a typo) says so at start, not "port already in
  use" (F20).
- Upgrading from before the data/ folder: the database, browser_defaults.json, speech_banned.json, backups/ and
  piper-voices/ move from the repository folder into data/ once, saying so; an old config's
  `speech_file = "speech.json"` finds resources/speech.json, with a warning (F22).
- Closing Outrider within 10 s of the game quitting still makes the quit backup (F32); a backup still running at
  shutdown past 5 minutes is waited for and recorded, not dropped (F35).
- `--restore` restores a database not named *.sqlite (F33); a browser_defaults.json that cannot be written leaves the
  old one and reports the database as restored (F34); a defaults file of the wrong type is refused by --restore and
  ignored by the page instead of stopping it (Codex F9).
- The co-pilot button picks, of the devices whose names match, the one that can send the button (the throttle of a
  two-part X-56, not the stick) (F41).

## 2026-10-03 · Speech, voice, wording and page details (fix plan, batch 8)
- A map's "Next" says the body's whole mapped value, without and with your bonuses: "Next: map 7 (771k/2.2M)",
  spoken "771 thousand, 2.2 million with bonuses" (one number when no bonus applies), on Now, in the mapped call-out
  and in the status report (review Q5).
- A speech file with valid JSON but the wrong shapes inside keeps the last good lines and says what is wrong; bans
  keep working (Codex F7).
- Voice Lab: Stop drops a line still being synthesised (Codex F6); "Call me" starts from `[defaults] speech_names`
  (F38).
- A browser-voice error is not logged as said, nor repeated by "say again" (F44); a heat or interdiction line that
  was dropped unsaid no longer holds back the next one for 30 s (F46).
- "Your carrier departs in under a minute" instead of "in 1 minutes" (F37).
- The ship-loss card's "My firsts (lost)" link also enables the "within N ly" box (F23).
- Retargeting while reading the schematic no longer scrolls Here to the top (F17); a system whose stars sit under
  nested barycentres, (A+B)+(C+D), gets its star rows (F40).
- Systems are compared by their exact id strings in the speech queue and Nearby (Codex C2).

## 2026-10-03 · Sales, history and unsold estimates (fix plan, batch 7)
- A Vista Genomics visit sold in several goes is checked as one against the x5 prediction: History's trip note no
  longer counts an x5 run twice, or reports a miss when the x1 run was sold first (review F21).
- Two Vista Genomics sales in the same second stay two (bio_sales keyed by journal line: Codex C1).
  PARSER_VERSION 38: the next start re-reads the journals once.
- A login with no jump, two hours or more after anything else (a sampling or Rhino evening in one system), is a
  History session of its own, not more of the one before; a relog shortly before a session's first jump starts
  that session (F31).
- A body mapped before any line named its system (a carrier jump, then the DSS) is sold with the system, not left
  "aboard" (F36).
- The unsold pop-up's headings: a ship loss with no sale before it says "since your ship was lost", and exobiology
  says "since you died" (any death takes it) (F45).
- `python3 -m outrider.unsold --calibrate --commander X` leaves other commanders' sales out of the comparison (Codex F8).

## 2026-10-03 · Play fixes outside the Highway (fix plan, batch 6)
- Launching the Nomad no longer forgets the body you are on: a Rhino launched after it records its mining again
  (review F5). PARSER_VERSION 37: the next start re-reads the journals once to rebuild Mined previously.
- The SRV's and the Nomad's damage is not the ship's hull, nor a spoken danger line (F25); a login in the Nomad names
  your ship (F26).
- Here's "➜ Heading to" line and highlighted row follow the in-game target as it changes, without waiting for a scan
  (F4).
- Climbing past the surface map's altitude hides it at once; a browser's own altitude is capped at the server's
  (F24). A rig lost past the 5 km leash says "rig lost", not "rig picked up" (F43).
- The fuel tile no longer says "game not running" when the first reading is on foot or in the SRV: "ship's tank not
  read yet", with the vehicle's fuel (F9).
- A second scan of the arrival star (after the honk, or a nav beacon) no longer repeats the arrival call-out and its
  sound (F30).
- Undocking within seconds of a sale no longer announces the pre-sale total as still aboard (F39).
- `/api/status` and `/api/status.txt` send `Access-Control-Allow-Origin: *`, so a stream overlay on another origin can
  read them, as documented (F6).

## 2026-10-03 · Target next highway system, Retry, and the Highway in the status report (fix plan, batch 5)
- 🎯 Target next: in the Highway tab's auto-target box and beside "Next:" in the route line, it targets the next route
  system (off the route, the closest one) after a 5-second countdown, whether or not auto-target is on. A failed
  auto-target puts ⟳ Retry on its route row (review Q4). POST /api/highway/target, {countdown: 0-10}; a cleared or
  replaced route stops it.
- The co-pilot's status report and the welcome back line say the Highway: boost here, the next stop, the refuel
  coming up, the too-much-fuel warning first; off the route, the closest route system. "Nearest unvisited" is left
  out of the report while a route is followed (review S2).

## 2026-10-03 · Automation safety (fix plan, batch 4)
- Switching auto-target off stops a run under way, even mid-sequence while auto honk keeps the virtual keyboard
  open; switching auto honk off ends its hold the same way (Codex F1, review F12). Clearing or replacing the Highway
  route stops a pending or running auto-target (Codex F2).
- Both check everything again under the keyboard's lock, just before the first key: a jump, docking, landing, a
  panel opening or the switch-off while they waited for the other to finish means nothing is pressed (Codex F3).
  Auto honk goes back to waiting instead.
- Auto-target: "already targeted" is checked first (F11); a waypoint plotted as a route of several jumps counts when
  NavRoute.json ends at it (F2); a wrong target is said by name: "Targeted the wrong system: X. Check before you
  jump." (Q3); the map-closing tap of a stopped run is held in full (F13); the log has one line per run unless it
  fails (Q6).
- New default sequence, from the in-game tests: a camera turn before the search, 1.5 s before the first Enter, a
  zoom instead of a turn in the plot step (Q2). Camera Zoom Out needs a keyboard binding.
- Auto honk no longer blames the fire group when your own jump cut the honk short (F42).
- POST /api/autohonk takes only a JSON boolean: `"false"` used to switch it on (Codex F10).

## 2026-10-03 · The drive maths and the Highway's helpers in their own modules (fix plan, batch 3)
- outrider/fsd.py: the frame shift drive's maths (drive tables, range, fuel per jump, the fuel model, a fleet ship's
  plotter inputs, the conservative range); outrider/highway.py: the route helpers, HighwayError and the desktop
  clipboard; outrider/core.py: the shared timestamp helpers. ed_outrider.py imports them (about 400 lines lighter).
- No behaviour change: the 533 tests pass unchanged (four test references now point at outrider.fsd). The Highway's
  state and auto-target stay in ed_outrider.State, where verify.sh's offline patches reach their constants.

## 2026-10-03 · Highway page state and requests (fix plan, batch 2)
- The Highway plot form follows the current ship, its Loadout and the cargo aboard: it used to keep its first
  answer and plot with the old ship and cargo after a swap or new cargo (review F3, Codex F4). Opening the tab asks
  again.
- An older Highway or Left behind answer arriving after a newer one is dropped (a cleared route could come back, a
  smaller radius could replace a larger one): a small newest-request guard (Codex F11).
- A failed region-map fetch is asked again after 30 s instead of never; only a missing map (404) is final (review
  F14, Codex F12).

## 2026-10-03 · Highway data fixes (fix plan, batch 1)
- A ship whose Loadout's MaxJumpRange leaves out the Guardian booster (booster off, or an outfitting Loadout) keeps
  its real FSD optimal mass: the exact plotter planned about 1.5x the real fuel per jump and too many refuel stops
  (review F1). PARSER_VERSION 36: the next start re-reads the journals once to rebuild the ships' figures.
- The neutron plotter's conservative range keeps the ship's booster floor (12 ly with a 10.5 ly booster and a 10 ly
  margin plots 11.25 ly, not 6) and never exceeds the full range (Codex F5).
- Off the route, the nearest route system is the closest one, passed or not (the author's rule), and a second detour
  through the same system no longer shows a stale one (review F7).
- A jump read just after a plot finished moves the route (arrivals are compared with the position's journal time,
  not the wall clock: review F8); a respawn or a login elsewhere counts as an arrival, so it shows the detour
  (review F10).
- The map greys the route up to where you are, as the list does, after flying back along it (review F15);
  "refuel in 3 jumps" has its unit (F16); a neutron route hides the ⛽ column and the refuel legend and says "no
  refuel stops: scoop as you go".

## 2026-10-03 · Test safety and test tooling (fix plan, batch 0)
- The page smoke test needs an explicit port and refuses 8025: run bare, it used to default to a real Outrider's
  port, and it clicks and POSTs (found by the Codex review).
- verify.sh's scratch server always reads the fixture journals: an exported ED_JOURNALS used to win over the scratch
  config (review F19).
- verify.sh fails on any ResourceWarning in the unit tests (24 test set-ups left in-memory databases open: now closed)
  and on any pyflakes warning.
- tests/test_units.py (11,200 lines) is split by subject into tests/test_*.py with the shared fixtures and fakes in
  tests/support.py; one file runs alone as `python3 -m unittest tests.test_highway`.
- New guard tests: an old database (the first public schema, frozen in tests/fixtures/schema_0046634.sql) upgrades to
  today's, x/y/z backfill included; every Journals attribute a failed tick could leave wrong, and every meta key a
  re-read could double, is accounted for, with the reasons written down.
- The auto-target runner's tests run on a fake clock (instant instead of seconds), and the smoke test waits for the
  page's requests to settle instead of fixed sleeps: unit tests 46 s -> 34 s, the smoke test about 70 s -> 35 s.

## 2026-10-02 · Highway screenshot with refuel stops; two unused lines removed
- The README's Highway screenshot shows an exact-plotter route: fuel used and left per jump, a ⛽ refuel stop in the
  list and its ring on the map (the old one was a neutron-plotter route, which has no refuel stops).
- Removed an unused import (`outrider/bio.py`) and a dead assignment (`outrider/unsold.py`): pyflakes is clean.

## 2026-10-02 · Here's bio column stays readable; --simulate for screenshots
- Here: a bio item ("Bacterium 3/3 ✓ 38.9M") no longer breaks inside itself, and a compact table shows a codex
  entry as 📖 ✦ (the name in its tooltip), so a body's row no longer grows to seven lines beside an open panel.
- `--simulate`: the panels show the last known values as if the game were running (fuel from the last reading,
  else the last jump, else a full tank), for screenshots and demos. Only the display reads it; the virtual
  keyboard, the co-pilot button and the clipboard are off. Screenshots regenerated with it.

## 2026-10-02 · The Highway: auto-target the next system; vehicle fuel; a shorter README
- **Auto-target** replaces the stub (Linux, off by default): after an FSD supercharge in a route system and
  `autotarget_delay` s, Outrider presses keys through auto honk's virtual keyboard to open the galaxy map, search for
  the next system (typed with a US keymap, or pasted), plot the route, close the map and check Status.json's
  `Destination.System` (`outrider/target.py`). Keys come from the active preset's keyboard bindings (GalaxyMapOpen,
  UI_Up, UI_Select, CamYawRight...) or `autotarget_keys`.
- Guards: never docked, landed, in the SRV or on foot, in danger, with the FSD charging, a map or panel open, the game
  not live, or the next system already targeted; aborts on an unexpected GuiFocus, a timeout, a jump or a changed
  system (closing the map only if it opened it). One try per supercharge; one sequence at a time with auto honk (the
  honk first).
- The Highway tab's **Auto-target the next system** box: toggle, delay (remembered, POST `/api/highway/autotarget`),
  **test now** (POST `/api/highway/autotarget/test`: 5 s countdown, then one run; refused with the reason), the last
  result, missing bindings and the steps. Spoken results under the new alerts row **Auto-target**: "Successfully
  targeted neutron jump target X" / "Failed to target neutron jump target X".
- Config: `autotarget_entry`, `autotarget_map_wait`, `autotarget_search_wait`, `autotarget_key_delay`,
  `autotarget_keys`, `autotarget_search`, `autotarget_submit`, `autotarget_plot`, `autotarget_dry_run`.
  `python3 -m outrider.target --show` prints the steps with your keys.
- The default sequence was tuned in game with the author (2026-10-02) and targets a system end to end: UI Up then
  UI Select into the search box (UI Right went to Trade Routes), Enter twice after half-second waits (the suggestion
  lists late), a short Camera Yaw Right to give the focus back to the map, then UI Select held to plot.
- **Test now** targets the nearest known system within a plain jump, so it needs no route.
- **In the SRV or the Nomad** the fuel tile keeps the ship's tank (it read 0 t, red) and adds "Current vehicle:
  Nomad" with the vehicle's own fuel; `LaunchVessel` (the Nomad) is tracked like `LaunchSRV`.
- README trimmed (views, layout, header and fuel, the Highway) with a new Highway screenshot; every screenshot
  regenerated.

## 2026-10-01 · The Highway: too much fuel for the next jump, conservative range
- **Too much fuel:** on a live arrival in a route system, and as the fuel changes there, the next jump is checked
  against the fuel aboard (the current ship's fuel model, its supercharge in a neutron route system); past the most
  fuel that still reaches it, a warning in the highway line and the Highway header ("⚠ too much fuel for the next
  jump: ≤ 36 t, you have 140 t", summary field `heavy`) and one spoken line per system. Only for the ship the route
  was plotted for; the neutron plotter when the next waypoint is one jump away.
- **Conservative range** in the plot form (off by default; `[highway] conservative`, `conservative_ly = 5`): the
  neutron plotter gets the range less the margin, the exact plotter an optimal mass scaled so the full-tank range is
  the margin shorter. The header says "conservative −5 ly". Stored with the per-browser `highway` form settings.

## 2026-10-01 · The Neutron Highway
- A **Highway** tab (after Map): plot a route with Spansh, the **exact** plotter (every jump with its fuel and refuel
  stops, from the chosen ship's Loadout: drive, masses, tanks, Guardian booster, engineering; cargo, injections,
  exclude secondary stars, already supercharged) or the **neutron** plotter (waypoints from a range, ×4/×6 and an
  efficiency, with a range override). One plot at a time, polled every 1.5 s for up to 180 s, errors in plain words.
- The ship list is every ship flown, as of its latest Loadout (`fleet_loadouts`, journal-derived: PARSER_VERSION 35).
- One active route (`highway_route`, live-only, kept through a re-read and in backups) followed as you fly: progress
  forwards or back, **Off Route: Detour** once joined, resumed at any route system, **Highway complete** at the end.
- The list (the next 200 ahead, done rows folded; off the route the nearest route system is marked and scrolled into
  view in the pane), a top-down map, and a highway line under the tiles on Overview, Nearby and Here.
- On arrival the next system's name goes on the desktop clipboard (`wl-copy` or `xclip`), and a plain spoken line
  ("Next Neutron Highway Stop: …", refuel and boost sentences, off route, back on the highway, complete) under the
  new alerts row **Neutron Highway**, spoken but not notified by default.
- `[highway]` config: `clipboard`, `autotarget` (a stub that only logs "would target …" after an FSD supercharge),
  `autotarget_delay`, `efficiency`. Per browser: `highway` (the plotter and its options).
- The map has a background: the galactic regions (klightspeed's region map, already shipped for the bio rules) as
  soft theme-aware tints with borders and names sized by zoom, a faint glow round Sagittarius A*, and Sol,
  Sagittarius A*, Colonia, Beagle Point and your carrier marked (click to copy); a **galaxy** button; corner toggles
  for regions, names and image (per device). `GET /api/regions` serves the grid (ETag, gzip). Optionally your own
  galaxy image under it: `[highway] background_image`, `background_extent` (default X −45000…45000, Z −20000…70000),
  `background_opacity`, served by `GET /api/highway/background` (that file only, image types only).

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
