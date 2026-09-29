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
}
ALWAYS = ("name", "cmdr", "ship", "here")
PLACEHOLDER = re.compile(r"\{(\w+)\}")


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
}
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


_EMOJI = re.compile("[☀-➿\U0001f300-\U0001faff⭐✨⚠️]")


def spoken_text(text):
    """Text as the page hands it to the voice: markup and emoji out, 2.3M as "2.3 million", cr as credits."""
    t = re.sub(r"<[^>]+>", "", str(text))
    t = _EMOJI.sub("", t)
    # numbers to a tenth at most, and "52.0" as "52" (12.64B is "12.6 billion", 52.0M "52 million")
    t = re.sub(r"(?<![\d.])\d+\.\d+(?![\d.])", lambda m: f"{round(float(m.group()), 1):g}", t)
    t = re.sub(r"(\d+(?:\.\d+)?)M\b", r"\1 million", t)
    t = re.sub(r"(\d+(?:\.\d+)?)k\b", r"\1 thousand", t)
    t = re.sub(r"(\d+(?:\.\d+)?)B\b", r"\1 billion", t)
    t = re.sub(r"\bcr\b", "credits", t)
    t = re.sub(r"\s·\s", ", ", t)
    return re.sub(r"\s+", " ", t).strip()
