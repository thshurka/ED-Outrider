# Agent instructions

Before changing anything, read `docs/AGENT_GUIDE.md` (code map, data flow, rules, recipes). Also:
`docs/JOURNAL_REFERENCE.md` (what the game writes and its traps), `docs/DESIGN_NOTES.md` (deliberate
decisions and known limits) and `docs/CHANGELOG.md`.

Layout: `ed_outrider.py` and `voice_lab.py` (entry points), `outrider/` (the modules; CLIs run as
`python3 -m outrider.<name>`), `resources/` (shipped data), `static/` (the page), `data/` (the player's own files,
git-ignored), `docs/`, `tests/`, `scripts/`.

The rules that matter most:

- Run `scripts/verify.sh` after every change; it must end in PASS. Every fix gets a test that fails without it.
- Never point tests or a scratch server at the player's own Outrider (port 8025) or real `data/` (`ed_outrider.sqlite`, ...) /
  `ed_outrider.toml`: use copies, a spare port and a scratch config, and stop servers by PID.
- Never trigger auto honk (uinput key presses) or open real input devices (co-pilot button); use the fakes in
  `tests/test_units.py`.
- Keep the paired lists in step: `SETTINGS_KEYS` (page.js) with `BROWSER_SETTINGS` (ed_outrider.py); speech keys
  across `resources/speech.json`, `outrider.speech.KEYS`/`SAMPLES` and page.js `LINE_SAMPLES`. Bump `PARSER_VERSION` when past
  journals must be re-read, and keep live-only tables out of `RESET_JOURNAL_DATA`.
