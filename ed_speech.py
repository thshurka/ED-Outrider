"""The words for spoken alerts: speech.json, several versions of every line in each personality.

The file maps each alert to lists of lines per personality ("business", "sarcastic", "sweet", or any you
add under "styles"). A list named "<style>_profane" holds that style's swearing versions. The page picks a
line at random from every personality you ticked, not one of the last few heard; with the profanity box
ticked it first rolls whether this line comes from the swearing versions (the percentage beside the box,
50% by default) or the clean ones. It fills in the {placeholders}: each alert's own (see KEYS) plus {name}
(one of the names in "Call me", picked afresh for every {name}), {cmdr}, {ship} and {here}. Numbers are
spoken to a tenth at most ("52.0M" is "52 million"). If the file is missing or broken it falls back to
plain wording.

The file is re-read whenever it changes, so an edit takes effect without restarting Outrider.
"""
import json
import os
import re

# every line the page speaks, and the {placeholders} it fills for it. Always available: {name} (one of the
# names you asked to be called, at random: game commander names are often unpronounceable), {cmdr} (the
# commander name itself), {ship} and {here}.
KEYS = {
    "speech_on": "spoken alerts were just switched on",
    "game_start": "you loaded into the game",
    "game_exit": "you quit the game",
    "arrival_undiscovered": "you jumped into a system nobody has discovered: {system}",
    "arrival_discovered": "a system announced as new turned out to be known: {system}",
    "leaving": "jumping away with work left behind: {text} (what is left)",
    "find_body": "a valuable or special planet was scanned: {what} (its class and flags), {body}, {value}",
    "find_bio": "a body with biology worth your threshold: {body}, {value}",
    "sample_clear": "far enough from the last sample to take the next: {genus}",
    "codex": "a new codex entry: {entry} (the entry's name), {what} (voucher or new to the region)",
    "fuel_low": "the game's low fuel warning: {pct}",
    "fuel_star": "arrived under 30% fuel at a star you cannot scoop: {pct}, {star}",
    "fuel_target": "targeted a star you cannot scoop with under 30% fuel: {pct}, {system}",
    "hull": "hull fell below half or a quarter: {pct}",
    "heat": "heat damage",
    "interdicted": "interdicted: {by}",
    "docked_sell": "docked where you can sell a worthwhile haul: {value}, {station}",
    "undocked_unsold": "undocked with a red-level haul unsold: {value}",
    "sold": "you sold data: {sold} (what was sold), {still} (what is still aboard, may be empty)",
    "unsold_warn": "unsold data reached the amber level: {value}",
    "unsold_urgent": "unsold data reached the red level: {value}",
    "carrier_departs": "your carrier leaves in under five minutes without you: {minutes}, {carrier}",
    "carrier_arrived": "your carrier arrived: {carrier}, {system}",
    "fss_done": "you finished the FSS, every body is found, and some are worth your time: {count} (how many bodies), "
                "{text} (what is worth doing, e.g. 'B 1, Earth-like world, 3.1M to map, and biology on C 2, up to 19M')",
    "fss_nothing": "you finished the FSS, every body is found, and nothing is worth staying for: {count} (how many bodies)",
    "fss_unfinished": "you closed the FSS with bodies still unresolved: {left} (how many, e.g. '3 bodies')",
    "left_body": "you left a body (back to supercruise) with exobiology unfinished: {body}, "
                 "{text} (what is unfinished, e.g. 'Stratum 2 of 3, and Tussock untouched, up to 4.1M')",
    "bio_done_more": "the third sample of a species, and more remain on this body: {species}, {value}, "
                     "{left} (what is left here, e.g. 'Bacterium and Fungoida')",
    "bio_done_last": "the third sample of the last species worth sampling on this body: {species}, {value}",
    "tank_full": "fuel scooping filled the tank: {jumps} (max-range jumps a full tank gives; may be missing)",
    "scoop_stopped": "fuel scooping stopped before the tank was full: {pct}",
    "supercharged": "the frame shift drive was supercharged by a neutron star or white dwarf cone: {mult} (e.g. '4 times')",
    "body_brief": "approaching a body with biological signals: {body}, "
                  "{text} (what they could be, e.g. '3 biological signals, one of Stratum, Bacterium or Fungoida, 1M to 19M')",
    "high_g": "approaching a landable high-gravity body with a lot of unsold data aboard: {gravity} (in g), "
              "{value} (the unsold total), {rebuys} (how many rebuys that is; may be missing)",
    "arrival_brief": "a briefing on the system you just entered, after the honk: "
                     "{text} (e.g. 'Undiscovered. 14 bodies. Scoopable K star.')",
    "session_recap": "you quit the game after a session of at least three jumps, in place of the plain goodbye: "
                     "{text} (e.g. '142 jumps, 3,100 light-years, 12 systems nobody had seen')",
    # the discovery streak: once per streak, when a run reaches its threshold (the page's alerts dialog)
    "streak_known": "several systems in a row were already known to others: {count} (how many in a row)",
    "streak_new": "several undiscovered systems in a row: {count} (how many in a row)",
    "welcome_back": "you loaded into the game after a break of over about two hours, in place of the plain greeting: "
                    "{text} (e.g. 'Away 3 days. 412 million aboard, unsold for 5 days. Fuel 64 percent.')",
    "ship_lost": "your ship was destroyed with data aboard and you paid the rebuy: "
                 "{text} (e.g. 'Lost 212 million: 148 million cartographics, 64 million exobiology, 31 systems.')",
}
# keys with lines in speech.json that nothing speaks yet (the shipped-lines test allows them); none now
RESERVED = ()
ALWAYS = ("name", "cmdr", "ship", "here")
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# a Piper voice name (the same rule as ed_tts.VOICE_NAME: nothing that could leave piper-voices/)
VOICE_NAME = re.compile(r"^[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-(x_low|low|medium|high)$")


def style_voice(styles, style):
    """(voice, speed) a personality asks for in "styles" ({"label", "voice", "speed"}), (None, None) for a plain
    label. A personality's voice wins over the one picked in the dialog; its speed multiplies yours."""
    st = (styles or {}).get((style or "").removesuffix("_profane"))
    if not isinstance(st, dict):
        return None, None
    voice = st.get("voice") if isinstance(st.get("voice"), str) and VOICE_NAME.fullmatch(st["voice"]) else None
    speed = st.get("speed") if isinstance(st.get("speed"), (int, float)) and 0.5 <= st.get("speed") <= 2 else None
    return voice, speed


def style_voices(styles):
    """The distinct voices the personalities in "styles" ask for (see style_voice)."""
    return {v for v in (style_voice(styles, k)[0] for k in (styles or {})) if v}


def fills(key):
    return set(PLACEHOLDER.findall(KEYS.get(key, ""))) | set(ALWAYS)


def check(doc):
    """Problems with a speech document, as readable strings (empty when it is fine)."""
    problems = []
    if not isinstance(doc, dict):
        return ["the file must hold one JSON object"]
    styles, lines = doc.get("styles"), doc.get("lines")
    if not isinstance(styles, dict) or not styles:
        problems.append('"styles" must map each personality to its label')
        styles = {}
    for name, st in styles.items():   # a label, or {label, voice, speed}: a Piper voice of its own (see style_voice)
        if isinstance(st, str):
            continue
        if not isinstance(st, dict):
            problems.append(f'"styles" / "{name}" must be a label or an object {{"label", "voice", "speed"}}')
            continue
        if "voice" in st and not (isinstance(st["voice"], str) and VOICE_NAME.fullmatch(st["voice"])):
            problems.append(f'"styles" / "{name}": "voice" must be a Piper voice name such as "en_US-ryan-high"')
        if "speed" in st and not (isinstance(st["speed"], (int, float)) and not isinstance(st["speed"], bool)
                                  and 0.5 <= st["speed"] <= 2):
            problems.append(f'"styles" / "{name}": "speed" must be a number from 0.5 to 2')
    if not isinstance(lines, dict):
        return problems + ['"lines" must map each alert to its versions']
    known_lists = set(styles) | {s + "_profane" for s in styles}
    for key, entry in lines.items():
        if key not in KEYS:
            problems.append(f'"{key}" is not an alert Outrider speaks (known: {", ".join(KEYS)})')
            continue
        if not isinstance(entry, dict):
            problems.append(f'"{key}" must be an object of personality lists')
            continue
        allowed = fills(key)
        for style, versions in entry.items():
            if style.startswith("_") or style in ("when",):
                continue
            if style not in known_lists:
                problems.append(f'"{key}" has a list "{style}" for a personality not under "styles"')
                continue
            if not isinstance(versions, list) or not all(isinstance(v, str) for v in versions):
                problems.append(f'"{key}" / "{style}" must be a list of strings')
                continue
            for v in versions:
                bad = set(PLACEHOLDER.findall(v)) - allowed
                if bad:
                    problems.append(f'"{key}" / "{style}": {{{"}, {".join(sorted(bad))}}} is not filled for this alert in "{v}"')
    return problems


class SpeechLines:
    """speech.json, re-read when its modification time changes. A broken edit keeps the last good copy
    in use and reports what is wrong, so a typo never silences the alerts."""

    def __init__(self, path):
        self.path = path
        self.doc, self.error, self.problems, self._mtime = None, None, [], None

    def refresh(self):
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError:
            self.doc, self.error, self.problems, self._mtime = None, f"{self.path} not found: plain wording is used", [], None
            return
        if mtime == self._mtime:
            return
        self._mtime = mtime
        try:
            with open(self.path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            self.error = f"{os.path.basename(self.path)} could not be read ({e}); " + \
                ("the last good copy is still in use" if self.doc else "plain wording is used")
            return
        self.problems = check(doc)
        if isinstance(doc, dict) and isinstance(doc.get("styles"), dict) and isinstance(doc.get("lines"), dict):
            self.doc, self.error = doc, None
        else:
            self.error = "; ".join(self.problems)

    def version(self):
        self.refresh()
        return str(self._mtime) if self.doc else None

    def info(self):
        """The payload's small summary: the page fetches the lines themselves when the version changes."""
        self.refresh()
        return {"version": self.version(), "error": self.error, "problems": self.problems[:20],
                "file": os.path.basename(self.path)}

    def lines(self):
        self.refresh()
        return {"styles": (self.doc or {}).get("styles") or {}, "lines": (self.doc or {}).get("lines") or {},
                "version": self.version(), "error": self.error, "problems": self.problems[:20]}


# ---- filling and tidying lines outside the page (the voice lab; the page has its own copies in page.js) ----

# made-up values for trying lines out, already phrased the way the page phrases them
SAMPLES = {
    "arrival_undiscovered": {"system": "Drojau LL-O b26-3"}, "arrival_discovered": {"system": "Drojau LL-O b26-3"},
    "leaving": {"text": "A 2, a class two gas giant, plus 1.4M to map"},
    "find_body": {"what": "Water world, terraformable, undiscovered", "body": "A 3", "value": "2.3M"},
    "find_bio": {"body": "B 7", "value": "19.0M"}, "sample_clear": {"genus": "Stratum"},
    "codex": {"entry": "Stratum Tectonicas", "what": "new to your codex for this region"},
    "fuel_low": {"pct": 18}, "fuel_star": {"pct": 22, "star": "white dwarf"},
    "fuel_target": {"pct": 22, "system": "Drojau LL-O b26-3"}, "hull": {"pct": 42}, "interdicted": {"by": "someone"},
    "docked_sell": {"value": "114.1M", "station": "Jaques Station"}, "undocked_unsold": {"value": "260.4M"},
    "sold": {"sold": "12.6M cr cartographics and 4.1M cr exobiology", "still": ""},
    "unsold_warn": {"value": "52.0M"}, "unsold_urgent": {"value": "251.3M"},
    "carrier_departs": {"minutes": 4, "carrier": "Out Of The Blue"},
    "carrier_arrived": {"carrier": "Out Of The Blue", "system": "Smojooe AR-E b25-8"},
    "fss_done": {"count": 14, "text": "B 1, Earth-like world, 3.1M to map, and biology on C 2, up to 19.0M"},
    "fss_nothing": {"count": 14}, "fss_unfinished": {"left": "3 bodies"},
    "left_body": {"body": "A 3", "text": "Stratum 2 of 3, and Tussock untouched, up to 4.1M"},
    "bio_done_more": {"species": "Stratum Tectonicas", "value": "19.2M", "left": "Bacterium and Fungoida"},
    "bio_done_last": {"species": "Stratum Tectonicas", "value": "19.2M"},
    "tank_full": {"jumps": 8}, "scoop_stopped": {"pct": 64}, "supercharged": {"mult": "4 times"},
    "body_brief": {"body": "B 7", "text": "3 biological signals, one of Stratum, Bacterium or Fungoida, 1.0M to 19.0M"},
    "high_g": {"gravity": "2.6", "value": "480.2M", "rebuys": "3.2"},
    "arrival_brief": {"text": "Undiscovered. 14 bodies. Scoopable K star."},
    "session_recap": {"text": "142 jumps, 3,100 light-years, 12 systems nobody had seen, 9 species sampled"},
    "streak_known": {"count": 10}, "streak_new": {"count": 5},
    "welcome_back": {"text": "Away 3 days. 412.0M aboard, unsold for 5 days. Fuel 64 percent. Docked at Jaques Station."},
    "ship_lost": {"text": "Lost 212.4M: 148.1M cartographics, 64.3M exobiology, 31 systems and 9 first discoveries. "
                          "The nearest lost system is Drojau LL-O b26-3, 42 light-years."},
}
# the voice lab's Audition: one personality across the alerts that matter, in the order a session hears them
AUDITION = ("game_start", "arrival_brief", "find_body", "leaving", "fuel_low", "sold", "bio_done_last", "session_recap")
DEFAULT_NAMES = "Boss, Hefay, Sir"


def names_list(text):
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def fill(text, values, names=DEFAULT_NAMES, rng=None):
    """A line with its {placeholders} filled: every {name} is its own random pick from `names`."""
    import random
    rng = rng or random
    pool = names_list(names) or ["Commander"]

    def one(m):
        k = m.group(1)
        if k == "name":
            return rng.choice(pool)
        v = values.get(k)
        return "" if v is None else str(v)
    return PLACEHOLDER.sub(one, text)


_PROC_NAME = re.compile(r"\b([A-Z])([A-Z])-([A-Z]) ([a-h])(\d+)(?:-(\d+))?\b")
_EMOJI = re.compile("[☀-➿\U0001f300-\U0001faff⭐✨⚠️]")


def spoken_text(text):
    """Text as the page hands it to the voice: markup and emoji out, 2.3M as "2.3 million", cr as credits."""
    t = re.sub(r"<[^>]+>", "", str(text))
    t = _EMOJI.sub("", t)
    # numbers to a tenth at most, and "52.0" as "52" (12.64B is "12.6 billion", 52.0M "52 million")
    # (fixed-point, not :g, which goes to "1.23457e+06" from a million and drops the tenths from 100000)
    t = re.sub(r"(?<![\d.])\d+\.\d+(?![\d.])", lambda m: f"{float(m.group()):.1f}".removesuffix(".0"), t)
    t = re.sub(r"(\d+(?:\.\d+)?)M\b", r"\1 million", t)
    t = re.sub(r"(\d+(?:\.\d+)?)k\b", r"\1 thousand", t)
    t = re.sub(r"(\d+(?:\.\d+)?)B\b", r"\1 billion", t)
    t = re.sub(r"\bcr\b", "credits", t)
    t = re.sub(r"\s·\s", ", ", t)
    # a procedural system name's sector suffix letter by letter ("Drojau LL-O b26-3" -> "Drojau L L O, b 26 3"),
    # as the page's spokenText does; a carrier id (K7F-3XZ) or a hand-named system does not match
    t = _PROC_NAME.sub(lambda m: f"{m[1]} {m[2]} {m[3]}, {m[4]} {m[5]}" + (f" {m[6]}" if m[6] else ""), t)
    return re.sub(r"\s+", " ", t).strip()
