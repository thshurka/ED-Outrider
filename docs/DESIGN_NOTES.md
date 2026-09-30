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
- **Parked:** nearest neutron star and a wasted-charge warning (useful if a neutron route plotter is ever added).
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
