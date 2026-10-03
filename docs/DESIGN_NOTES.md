# Design notes: deliberate decisions and known limits

Each line is a choice the project made on purpose, or a limit it knows about, with the reason. Don't
"fix" these as bugs without reading the reason. A fork is free to decide differently: these are the
upstream project's choices, not rules of the game.

## Deliberate decisions

- **No keyboard shortcuts.** A deliberate upstream choice, declined more than once; clickable things are reachable with
  Tab and act on Enter/Space instead.
- **No VoiceAttack integration.** Not used upstream; the co-pilot button and the page cover the same ground.
- **Nothing is uploaded.** No EDDN sender, no accounts; outside calls are read-only lookups (Spansh, EDSM,
  GitHub for bio rules, Hugging Face for voices).
- **Survey odds are odds, not contents.** The mining tooltip shows what a community survey found at that kind of
  ground; the game never says what a location holds.
- **No hand-logging of mining location contents.** Considered and left out for now; "Mined previously" records
  what was actually refined.
- **Rhino rigs are marked with the co-pilot button** until the game logs deploy and pickup; the record is
  Outrider's, not the game's, and is labelled so.
- **Exobiology predictions say "up to".** The genus is usually right, the species sometimes not; nothing is
  ruled out on bodies not found yet.
- **Values are estimates** from the community formula (it matches EDDiscovery's), bonuses included; no extra
  clamp on planet values.
- **"Not on the page" means nobody with an uploader reported it,** not "certainly undiscovered".
- **Alerts only for the out of the ordinary.** Routine systems stay quiet (or get a soft two-note sound when
  that is ticked).
- **Danger lines are said plainly** (business personality, no swearing) by default; profanity is opt-in.
- **The voice uses names the player picks,** never the commander name (often unpronounceable).
- **One window speaks** with the page open in several, so nothing is said twice.
- **Auto honk is off until ticked,** because its key presses go to whichever window has focus.
- **The co-pilot button only reads the device,** never grabs it; unbinding it in the game is the player's job.
- **Listens on 127.0.0.1 by default, no password.** Opening it to the network is an explicit setting; the Host
  and cross-site guards stop other web sites, not people on your network.
- **Only `/api/status` and `/api/status.txt` are readable cross-site,** for stream overlays: they alone send
  `Access-Control-Allow-Origin: *` (no credentials are involved), so a fetch from an overlay page on another origin or
  a local file can read them (review F6).
- **The surface map's altitude in a browser is capped at the server's** (`[defaults] surface_alt`, review F24): the
  server sends positions only below its own altitude, so a browser set higher would show a frozen map. A lower one
  hides sooner, as before. Climbing past the altitude wakes the page once, so the map goes away on time.
- **A HullDamage line with no `Fighter` key is the SRV's or the Nomad's,** not the ship's (review F25): every ship
  line in the author's journals carries `"Fighter": false`, and the vehicle lines never do.
- **The journal archive in backups is never pruned;** database zips rotate. `--restore` leaves `speech.json`,
  bans and the config alone.
- **The firsts watch is gentle to Spansh:** each system daily for a month, then weekly, at most 150 checks a day,
  and it can be switched off.
- **The suggested order is not a route planner:** a fixed supercruise time curve, no spoken next stop.
- **Discovery streak lines are limited to two kinds,** no records or milestones.
- **The approach warning fires on ApproachBody only** and reuses the unsold amber level rather than a new setting.
- **"Leaving a body unfinished" only nags** if you landed or sampled there this visit.
- **Alternatives to a finished target and a heading-aware neighbourhood were declined:** undiscovered systems
  rarely turn up close by.
- **Parked:** nearest neutron star and a wasted-charge warning (now that the Highway exists, the next candidates).
- **The Highway keeps one active route.** A new plot replaces it; waypoints may come later. It is live-only data
  (`highway_route`), kept through a journal re-read and carried by backups.
- **Detour and resume:** arriving off the route counts as a detour only once the route was joined (flying to its
  start is not one), and arriving at *any* route system resumes it, neutron or not, forwards or back. Said once each.
  A respawn or a login somewhere else (a Location that moves you, not a relog) counts as an arrival too. Off the route
  the nearest route system marked is the CLOSEST one, passed or not (the author's rule, 2026-10-03: getting back on
  the highway is the fastest way on). Arrivals count when newer than the position the route was plotted at (its
  journal time, not the wall clock), so a jump read just after the plot finished still moves the route.
- **The status report and welcome back say the Highway** (review S2): one clause right after the fuel ("Highway: boost
  here, then Hwy Stop 38, 4.2 light-years, refuel in 3 jumps"), led by the too-much-fuel warning when it is set, the
  closest route system when off the route; the report's "Nearest unvisited" is left out while a route is followed.
  No position "38 of 399" (the index and total are easy to say one off).
- **The Highway's cargo is not remembered.** The form takes the cargo aboard from the journals each time (a
  remembered figure would be stale the next day); only the plotter and its options are per-browser settings.
- **Auto-target presses keys in the galaxy map** (opt-in, Linux; decided with the author 2026-10-01): open the map,
  the search box (UI_Up highlights "Search the Galaxy", UI_Select puts the cursor in it; found in game 2026-10-02 — UI_Right, Auto_Neutron's older step, moves along the tab column to Trade Routes, and UI_Select alone opens the current system; `autotarget_search` changes it), type the name (US keymap; a name it cannot type is pasted when a
  clipboard tool exists), Enter twice after short waits (the search lists its suggestion a moment after the name goes in, and an Enter before that selects nothing; found in game 2026-10-02; `autotarget_submit`), the plot-route step (configurable: the map's focus after a search varies), close the
  map, then Status.json `Destination.System` must be the next id64. It shares auto honk's virtual keyboard and lock;
  an auto honk running on the arrival goes first. It checks GuiFocus, the system, a jump and danger before every step
  and while waiting, and on an abort closes the map only if it opened it and the map is still the focus. One try per
  supercharge, nothing repeats. Its results are plain spoken lines under their own alerts row (no `speech.json` keys).
  The default sequence is what worked in game on 2026-10-03: the map reopens on the panel it last showed, so the
  search starts with a short CamYawRight (a camera move hands the focus back to the map); the first Enter waits
  1.5 s (the suggestion lists late on a long name); the plot step zooms out instead of turning, since a turn after
  the search could swing the cursor onto a neighbouring star and plot to it.
  Target next and Retry (review Q4) are one action, POST /api/highway/target: a run the page asks for, like "test
  now" but against the route (the next system; off the route the closest one, as the line's "nearest"; before the
  start, the start), with or without the toggle; {countdown} 0-10 s, 5 by default for the desktop page (the click
  took the keyboard focus), 0 for the tablet. Not on the X56 co-pilot button (the author's decision). Clearing or
  replacing the route stops it like the automatic run; switching the toggle off does not (it is not the toggle's
  run). Retry shows only while the failed run's row (autotarget_last's route and index) is still the one Target next
  would aim at.
  Guards (review batch 4): the keyboard's owners (who keeps the device open) and a run's cancel token are separate,
  so switching auto-target or auto honk off stops that feature's run even while the other keeps the device open;
  clearing or replacing the Highway route stops a pending or running auto-target too. Everything is checked again
  under the keyboard's lock before the first key (the wait for it can be long: one feature holds it for its whole
  sequence), against the system the run was decided in rather than wherever you are when it starts. "Already
  targeted" is checked before anything else (a panel open does not make it an error), and the check after the plot
  also accepts NavRoute.json ending at the next system (a waypoint beyond a plain jump plots a route whose first
  hop differs). A wrong target is said by name. A cancelled run still holds its closing map tap for the full
  TAP_S. Auto honk's miss is not held against the fire group when your own jump started during the hold or the
  wait for the scan.
  The toggle and delay are the server's (meta `autotarget`, beating the config once used), not per browser.
- **Too much fuel for the next jump.** Spansh's exact plotter simulates the fuel, so a long neutron jump may be in
  range only with about the fuel it expects aboard (the Caspian's 487.9 ly ×6 jump: at most about 36 t; a full 160 t
  tank gives 75.3 × 6 = 452 ly). Checked on a live arrival in a route system (or a plot made where you are) and again
  as Status.json's fuel changes there (every 3 s at most), against the fuel actually aboard (the main tank, with the
  reservoir and cargo counted as mass), the current ship's fuel model and its supercharge in a neutron route system.
  The most fuel that still reaches the jump is found by bisection on `fsd_range` past one max jump's fuel (below that
  the fuel itself limits the jump). Warned past that by more than 0.5 t (Spansh plans at the limit), said once per
  system, cleared when the fuel drops or you leave. Only for the ship the route was plotted for; the neutron plotter
  only when the next waypoint is one jump away (the first jump of several has no known length).
- **Conservative range** shortens the plan, not the ship: the neutron plotter gets the range less the margin, the
  exact plotter a smaller optimal mass, scaled so the normal full-tank range is the margin shorter (the range less the
  booster's ly goes as the optimal mass at every mass, so Spansh's fuel simulation stays consistent; the booster is
  untouched). Neither cuts the drive's own range by more than half. The margin is recorded in the route's options.
- **The Highway's spoken lines are plain text** carried by the moment, not `speech.json` keys yet (personality later).
- **The Highway map's regions are drawn by the page,** not rendered to an image on the server: `GET /api/regions`
  sends klightspeed's run-length grid as it is shipped (185 KB, about 40 KB gzipped, an ETag so a reload costs a 304)
  and the page colours it with the theme's colours at the zoom it needs. A server PNG would need one per theme, an
  encoder Outrider doesn't have, and the grid again for the borders and names. The tints and borders go into an
  offscreen canvas covering the view plus a margin, redrawn only when the view leaves it, the zoom moves by more than
  1.6×, or the theme or layers change; the names are drawn every frame (crisp, sized by zoom, the biggest regions'
  first, none overlapping). Over your own image the regions are borders only.
- **The map's layer toggles are per device** (`hwyLayers` in this browser's storage, not a shared setting): how one
  screen shows the map is not an alert preference, and a phone may want the names off.
- **The background image is the player's own.** Outrider ships none; only the configured file is served, only as an
  image type checked by extension and first bytes (no SVG), never a path from the request. The default extent
  (X −45000…45000, Z −20000…70000) is the bounds quoted for EDAstro's galaxy charts and the galaxy map texture
  (40 ly per pixel at 2250 px, Sol at pixel 1125, 1750).
- **Landmarks are fixed:** Sol, Sagittarius A*, Colonia and Beagle Point at EDSM's locked coordinates, and your carrier
  where the journals put it.
- **`--simulate` is display only.** For screenshots and demos the panels read as if the game were running, with the
  last known values (fuel from the last reading, else the last jump, else a full tank; the Data tile doesn't flag the
  old journal). Nothing is invented (a target the game cleared stays cleared), every guard still reads the real
  Status.json, and the virtual keyboard, the co-pilot button and the clipboard are off whatever the config says.
- **Here's bio items never break inside themselves,** and a compact table shows a codex entry as 📖 ✦ with the name
  in its tooltip (the run beside it already names the species), so a row stays one or two lines beside an open panel.
- **History's sessions are split by 2 h without a jump.** A session's window runs from its login (the latest one
  within 2 h before its first jump) to the next session's; a login no jump followed, 2 h or more after anything
  else, opens a session with no jumps (review F31), whose "end" is its last login (nothing later is known).
- **A Vista Genomics visit is one x5 check** (sales under 5 minutes apart): the runs aboard before its first sale
  against everything it sold; each sale stores what it adds, so the ledger's sum is the visit's check whatever order
  the entries came in (review F21).
- **A map's "Next" gives the body's whole mapped value, without and with your bonuses** (the author's choice,
  review Q5): "Next: map 7 (771k/2.2M)", spoken "771 thousand, 2.2 million with bonuses", one number when no bonus
  of yours applies; on Now's Next line, the mapped call-out and the status report. Which bodies make the list and
  their order still go by the bonus-free increment (what mapping adds), as the green-row level does.
- **A malformed speech file is not installed** (Codex F7): valid JSON whose lists hold anything but strings keeps
  the last good document in use, with the problem shown; bans keep working.
- **The README stays short and user-facing;** implementation detail lives in code comments and these notes.

## Known limits

- **Auto honk and the co-pilot button are Linux only** (evdev/uinput); Windows input was discussed, not written.
- **Core module health is as of the last Loadout or repair;** the journal logs nothing in between, so jet-cone
  boosts since are only counted.
- **Status.json does not update while you stand still,** so positions can be up to a reading old.
- **Streak dots for arrivals before the strip existed are hollow** (Spansh cannot be asked about the past);
  carrier jumps usually have no arrival-star scan.
- **A carrier jump booked just before quitting shows as "not yet confirmed"** until the next login.
- **NPC crew deaths are not subtracted** from the crew count: the evidence showed that would be wrong.
- **Spansh cannot search for planetary mining locations;** that search is Local only.
- **The neutron plotter gives waypoints, not fuel:** no fuel columns or refuel stops; the exact plotter has them.
  The page hides the ⛽ column and the map's refuel legend on a neutron route and says "scoop as you go".
- **A Loadout's MaxJumpRange can leave the Guardian booster out** (powered off, or written in outfitting): the drive's
  figures are kept, the booster counts only when it is on; a typed neutron range keeps the booster floor only with a ship.
- **Region borders follow the grid,** cells of 4096/83 ≈ 49 ly, so close up they are steps, as the region map defines
  them; a name sits at its region's centroid (or the region's cell nearest it), so zoomed in it may be off screen (the
  scale bar's "centre:" says the region under the middle).
- **The too-heavy check needs a live arrival:** after an Outrider restart in a route system it waits for the next
  arrival there (as the clipboard copy does). It trusts the fuel model's range scaling, not Spansh's own code.
- **The Highway's ship list is as of each ship's latest Loadout;** an `EngineerCraft` after it is not applied, and a
  ship never flown (no Loadout) can only be plotted with the neutron plotter and a typed range.

## Not yet tried in a live game

These were built and tested with synthetic events, recorded files, fakes or headless browsers, but not
confirmed while playing. Treat reports about them as likely real.

- Status.json Flags2 on-foot-in-station bits (3, 13, 14) counting as docked.
- Auto honk end to end since it reads the binding from the controls preset; the fire-group and combat-mode waits.
- The co-pilot button on a real device (`python3 -m outrider.button --listen`), including rig marking in a live Rhino.
- Rig leash warnings, rigs lost on SRVDestroyed, death or relog, the rigs-still-out warning's timing, and
  `Destination.Body` for a mining location (assumed to be the planet).
- The rig restock recipe (3 Iron, 2 Nickel, 1 Mechanical Equipment), taken from a community guide.
- Playing lines and sounds on the PC (pw-play, paplay, aplay, ffplay) with real audio.
- Piper in the browser and the one-speaker logic across real windows (headless Chromium only).
- Many spoken call-outs (FSS debrief, leaving a body, approach, welcome back, ship-loss debrief, session recap).
- The fuel model against a live Status.json and a laden ship; EngineerCraft at a real engineer.
- Colour-variant prediction against a fresh in-game codex entry (backtested only).
- The firsts watch's rotation against live Spansh; an OBS source on `/api/status` after the guard change.
- `--restore` and `--list-backups` against a real database (temp files only).
- The Highway's plots against live Spansh (both plotters send the requests Spansh's site and Auto_Neutron send;
  tested with a mocked Spansh), following a route in game, and whether a name copied by `wl-copy`/`xclip` pastes
  into the galaxy map under Proton. The too-heavy warning and a conservative plot against a real route.
- Auto-target in game: the default sequence targeted a system end to end with "test now" (2026-10-02, the author's
  bindings and Linux/Proton). Not yet tried: a run triggered by a real supercharge on a route, other keyboard
  layouts and presets, and both entry modes side by side.
