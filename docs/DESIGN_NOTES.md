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
- **Only `/api/status` and `/api/status.txt` are readable cross-site,** for stream overlays.
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
- **The Highway's cargo is not remembered.** The form takes the cargo aboard from the journals each time (a
  remembered figure would be stale the next day); only the plotter and its options are per-browser settings.
- **Auto-target is a stub.** `[highway] autotarget` only logs "would target X" after the delay; the real key
  sequence (galaxy map, search, paste, plot) is for later, through auto honk's uinput path, opt-in and Linux only.
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
- **Region borders follow the grid,** cells of 4096/83 ≈ 49 ly, so close up they are steps, as the region map defines
  them; a name sits at its region's centroid (or the region's cell nearest it), so zoomed in it may be off screen (the
  scale bar's "centre:" says the region under the middle).
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
  into the galaxy map under Proton.
