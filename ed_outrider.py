#!/usr/bin/env python3
"""
ed_outrider.py -- ED Outrider: a live web page for exploring Elite Dangerous: what is around you, what you have
found, and what is still on board.

Reads every Elite Dangerous journal into a local SQLite database (visited systems, jump history,
your scans, DSS ring hotspots, first discoveries, mapping, footfalls, exobiology sampling, codex
entries, sales, deaths, fuel, your fleet carrier), then tails the live journal and Status.json.
Whenever you arrive somewhere new it asks Spansh for every known system within --radius light
years (EDSM as a fallback when Spansh is down) and serves http://127.0.0.1:8025/ with:

  Nearby     known systems sorted by distance / name / value, with scan status, main star and
             scoopability, body and ring icons, notable bodies (ELW/WW/AW/terraformable), Spansh's
             credit estimate, your 🏁 first-discovery markers (sold / unsold / lost), bookmarks
  Here       every body in the current system: value as scanned and if mapped, gravity, atmosphere,
             bio genera with 0/3..3/3 sampling progress and which species they could be (ed_bio.py
             spawn rules plus BioScan's colour check, with credit values; "one of these" with a range
             when a body has fewer signals than possible genera), ring hotspots, codex entries,
             curiosities (ringed landables, close orbits, planet pairs...), your firsts; as a list,
             a tree in orbital order, or a schematic of stars, planets, moons and barycentres
  Samples    every exobiology sample run (aboard / sold / lost, with value) and codex entry
  Bookmarks  systems you starred, with a note each
  Search     local database or Spansh: star classes (scoopable shortcut), planet types, ring types,
             ring hotspot minerals
  Map        3D canvas of the neighbourhood with your path, first discoveries, boost stars
             (neutron / white dwarf) and your carrier; fills the window; left-drag rotates,
             right-drag moves, the wheel zooms
  History    your sessions: jumps, light-years, firsts, mapped, footfalls, samples, codex, plus an
             all-time row; exports
  Log        every journal event with a one-line summary (ed_log.py), filtered by category, time and
             text, read straight from the journal files and updated live
  Materials  engineering materials against their caps, and how many FSD injections and other
             syntheses you can make (ed_materials.py)
  My firsts  unsold first discoveries, and visited systems nearby with work worth going back for
  Now        big text for a second monitor (also ?mode=now)

The header shows the current system (coordinates, visit count), the commander (credits at login plus
sales since, ship), fuel (with jumps left, jumps since the last scoop and FSD boosts on hand), your
carrier (distance, UC / Vista services), the latest codex first, unsold firsts, and the unsold
cartographic + exobiology estimate from ed_unsold.py. Targeting a system plays a sound: fanfare if
neither Spansh nor EDSM has heard of it, upbeat if it is not fully scanned, thud if you have been
there or it is fully scanned, plus an alert if you are leaving unfinished work behind. Arriving
somewhere undiscovered is announced by the voice (a sound only corrects a targeting call that was
wrong). Desktop notifications are optional (🔔 alerts).

Alerts can be spoken (🗣): with Piper (ed_tts.py) when it is installed, else the browser's voice, in
the personalities of speech.json (ed_speech.py: business, sarcastic, sweet, with swearing versions at
a chosen rate), calling you by the names you choose. Besides the alerts the voice can say signal
counts as the FSS finds them, where the frame shift drive is taking you and whether that star is
scoopable, and greet you on loading into the game. voice_lab.py is a separate window for trying
voices and lines. Auto honk (ed_honk.py, Linux, optional) holds Primary Fire's keyboard binding on
arriving by hyperspace so the Discovery Scanner fires, and says how many bodies it found.

Body data is Spansh's merged with your own journal scans, so what you scan shows up immediately,
even for systems Spansh has never heard of. Your own data wins where both exist.

Each row shows how much is known about the system:

  unreported    only seen in your own NavRoute.json, nobody has reported any bodies
  no scan data  the system is known (route plot or a jump) but nothing scanned
  NN% scanned   some bodies known, fewer than the system's FSS body count
  fully scanned every body known
  N mapped      bodies DSS-mapped, as far as your own journal knows (Spansh doesn't record it)

A system that the galaxy map shows within range but this page does not list is one nobody has
reported to Spansh or EDSM -- almost certainly undiscovered.

Journal folders are auto-detected (Windows save folder, every Steam library's Proton prefix,
mounted Windows drives for older journals); --journals / --legacy / ED_JOURNALS override. Files
are remembered by path and byte offset, so a restart only reads what is new; legacy folders are
imported once. Pass --rescan to rebuild everything from scratch.

Settings come from ed_outrider.toml next to this script (see ed_outrider.toml.example; make one with
--write-config); flags and ED_JOURNALS override it, and nothing is required.
The page itself is static/page.html + page.css + page.js next to this script (edit and reload).
Tests: python3 -m unittest discover tests; ed_bio.py --backtest scores the bio rules against
your journals.

Requires Python 3.11+ (for reading the config file; 3.9/3.10 need `pip install tomli`) and aiohttp;
piper-tts (spoken alerts) and evdev (auto honk, Linux) are optional.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import os
import re
import sqlite3
import sys
import time
from glob import glob

from aiohttp import ClientSession, ClientTimeout, web

try:  # the unsold-data estimate (and journal-folder detection) live in a script next to this one
    import ed_unsold
except ImportError:
    ed_unsold = None
try:  # exobiology spawn rules: which species a body could host
    import ed_bio
except ImportError:
    ed_bio = None
import ed_materials  # engineering materials and synthesis recipes (no dependencies)
import ed_tts        # spoken alerts; Piper itself is optional (the page falls back to browser speech)
import ed_speech     # the words for spoken alerts, per personality (speech.json)
import ed_honk       # auto honk: holds Primary Fire on arrival (optional; Linux, needs evdev)
try:  # one-line summaries of every journal event, for the Log view
    import ed_log
except ImportError:
    ed_log = None


# Which deaths cost the ship (and its cartographic data): shared with ed_unsold so the
# header and the per-system markers can never disagree about the same death.
SHIP_SURVIVED_OPTIONS = ed_unsold.SHIP_SURVIVED_OPTIONS if ed_unsold else ("recover", "rejoin")
SHIP_LOSS_SQL = ("coalesce(option, 'rebuy') NOT IN (" +
                 ",".join("'%s'" % o for o in SHIP_SURVIVED_OPTIONS) + ")")

# --------------------------------------------------------------------------
# Journal locations. LIVE_DIRS are tailed; LEGACY_DIRS are imported once.
# --------------------------------------------------------------------------

# Auto-detected (see ed_unsold.find_journal_dirs); --journals / --legacy / ED_JOURNALS override.
LIVE_DIRS, LEGACY_DIRS = ed_unsold.find_journal_dirs() if ed_unsold else ([], [])

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ed_outrider.sqlite")
_OLD_DB = os.path.join(SCRIPT_DIR, "ed_nearby.sqlite")   # the name before the tool was called ED Outrider
if not os.path.exists(DB_PATH) and os.path.exists(_OLD_DB):
    os.replace(_OLD_DB, DB_PATH)
CONFIG_PATH = os.path.join(SCRIPT_DIR, "ed_outrider.toml")   # optional; see ed_outrider.toml.example

SPANSH_SEARCH = "https://spansh.co.uk/api/systems/search"
SPANSH_DUMP = "https://spansh.co.uk/api/dump/{id64}"
SPANSH_BODY_SEARCH = "https://spansh.co.uk/api/bodies/search"
SPANSH_STATION_SEARCH = "https://spansh.co.uk/api/stations/search"
SELLER_REFRESH_LY = 100      # look for the nearest places to sell again after moving this far
SELLER_REFRESH_S = 6 * 3600  # ...or this long (carriers move)
EDSM_SYSTEM = "https://www.edsm.net/api-v1/system"
EDSM_SPHERE = "https://www.edsm.net/api-v1/sphere-systems"
BOOST_STARS = ["Neutron Star"] + [f"White Dwarf ({c}) Star" for c in
                                  ("D", "DA", "DAB", "DAZ", "DAV", "DB", "DBZ", "DBV", "DQ", "DC", "DCV")]
SPANSH_PAGE = 500          # largest page size the search endpoint honours
SPANSH_MAX_PAGES = 10
SPANSH_CONCURRENCY = 4     # body-detail fetches after an arrival
SPANSH_INTERACTIVE = 2     # separate lane for target/body lookups so they never queue behind the above
LONG_POLL_SECONDS = 25     # s: how long /api/nearby holds a request with nothing new before answering 204
ON_DEMAND_MAX_AGE = 86400  # s: a system fetched for Search/bookmarks/pins is fetched again after a day
DUMP_MAX_TRIES = 5         # body-detail fetches for one system before we stop asking (this stay)
USER_AGENT = "ED Outrider (personal exploration helper)"

POLL_SECONDS = 1.0
RUN_ID = int(time.time())  # identifies this server process to the page

# 3D map: how far out it can look, and how many Spansh pages (of 500 systems) it will fetch.
# Spansh returns at most 10,000 systems per search; near the bubble each page is several MB.
MAP_MAX_RADIUS = 250
MAP_MAX_PAGES = 6

# Unsold data: recompute at most this often while the journal is growing (a full pass is ~1 s).
UNSOLD_MIN_SECONDS = 15
# Header colour thresholds for "how much are you risking by not selling" (credits).
UNSOLD_WARN = 50_000_000
UNSOLD_URGENT = 250_000_000
# Defaults a browser adopts until its user changes them (page settings live in the browser).
BIO_MIN = 10_000_000
SOUNDS_DEFAULT = True
# Rows in Here stand out when a body's data is worth this much, bonuses left out: cartographic (scan +
# map, no first-discovery / first-mapped / efficiency bonus) and exobiology (no first-footfall x5).
BODY_HIGHLIGHT = 500_000
BIO_HIGHLIGHT = 10_000_000
# Whether Here's Max column counts first-discovery / first-mapped / first-footfall bonuses (Now always does:
# it is what a sale would pay).
MAX_INCLUDE_BONUS = True
# The Nearby radius choices offered on the page (ly). Bigger spheres cost Spansh requests and page redraws:
# ~1,500 systems at 100 ly out in the black, far more near the bubble.
RADIUS_CHOICES = (20, 25, 30, 40, 50)
# Spoken alerts: the Piper voice, and the one used when it is missing (see ed_tts.py).
VOICE, VOICE_FALLBACK = ed_tts.DEFAULT_VOICE, ed_tts.DEFAULT_FALLBACK
BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups")   # where "Back up now" writes (git-ignored)
# Spoken alerts' wording: the lines file, and the personalities a browser starts with (see ed_speech.py).
SPEECH_FILE = os.path.join(SCRIPT_DIR, "speech.json")
SPEECH_STYLES, SPEECH_PROFANITY = ("business",), False
SPEECH_PROFANITY_PCT = 50   # with profanity on: how often (%) a line comes from the swearing versions
SPEECH_NAMES = "Boss, Hefay, Sir"   # what the voice calls you ({name}), one at random per line
# Auto honk (see ed_honk.py): on arriving by hyperspace, hold a key bound to Primary Fire so the Discovery
# Scanner fires. The D-Scanner MUST be on PRIMARY FIRE in the active fire group when you jump.
AUTOHONK = {"enabled": False, "key": ed_honk.DEFAULT_KEY, "delay": 2.0, "hold": 6.0, "skip_honked": True,
            "announce": True}   # announce: say the body count (or "all bodies were found") when it completes
AUTOHONK_MAX_AGE = 30   # s: an arrival older than this is a journal being caught up on, not a live jump
SPEAK_BIO_SIGNALS = SPEAK_GEO_SIGNALS = True   # say "2 Biological Signals on body A 3" as the FSS finds them
SPEECH_SPEED = 1.0   # spoken alerts' pace: 1 is the voice's own, 1.3 is 30% faster (0.5 to 2)


# --------------------------------------------------------------------------
# Configuration: command-line flag > environment (ED_JOURNALS) > ed_outrider.toml > auto-detection.
# Every key is optional; with no file at all the defaults above and auto-detection apply.
# --------------------------------------------------------------------------

def load_config(path):
    """The TOML config as a dict ({} if there is no file); a broken file is reported, not fatal."""
    try:
        import tomllib
    except ImportError:  # Python < 3.11: the tomli package is the same reader under another name
        try:
            import tomli as tomllib
        except ImportError:
            if os.path.exists(path):
                print(f"config {path} ignored: reading it needs Python 3.11+ (or pip install tomli)", file=sys.stderr)
            return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"config {path}: {e} (ignored)", file=sys.stderr)
        return {}


def _config_folders(value, key):
    """A [journals] live/legacy value as a list of folders: a single string is one folder."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
        return list(value)
    print(f"config: [journals] {key} must be a list of folders, e.g. {key} = [\"C:/...\"]; ignored", file=sys.stderr)
    return None


def _config_value(section, key, value, conv, default):
    """A config value converted with `conv`; a value of the wrong type is reported and the default used."""
    if value is None:
        return default
    try:
        return conv(value)
    except (TypeError, ValueError):
        print(f"config: [{section}] {key} = {value!r} is not valid here, using {default!r}", file=sys.stderr)
        return default


def settings_from(cfg, args, env_journals=None, detected=((), ())):
    """Resolve every setting with the precedence flag > env > config > default/auto-detect."""
    j, sv, df, sp = cfg.get("journals", {}), cfg.get("server", {}), cfg.get("defaults", {}), cfg.get("spansh", {})
    ah = cfg.get("autohonk", {})
    j = dict(j, live=_config_folders(j.get("live"), "live"), legacy=_config_folders(j.get("legacy"), "legacy"))
    num = lambda sec, table, key, conv, default: _config_value(sec, key, table.get(key), conv, default)
    choices = sv.get("radius_choices", RADIUS_CHOICES)
    if not isinstance(choices, (list, tuple)):
        print(f"config: [server] radius_choices = {choices!r} must be a list, e.g. [20, 25, 30]; using the defaults",
              file=sys.stderr)
        choices = RADIUS_CHOICES
    radius_choices = sorted({x for x in (_config_value("server", "radius_choices", c, float, None) for c in choices)
                             if x and x > 0}) or [float(x) for x in RADIUS_CHOICES]
    pick = lambda flag, key, default: flag if flag is not None else key if key is not None else default
    if args.journals:
        live = list(args.journals)
    elif env_journals:
        live = [d for d in env_journals.split(os.pathsep) if d]
    elif j.get("live"):
        live = list(j["live"])
    else:
        live = list(detected[0])
    legacy = list(args.legacy) if args.legacy else list(j.get("legacy") or ([] if (args.journals or env_journals or j.get("live")) else detected[1]))
    return {
        "live": [os.path.expanduser(d) for d in live], "legacy": [os.path.expanduser(d) for d in legacy],
        "host": pick(args.host, sv.get("host"), "127.0.0.1"),
        "port": pick(args.port, num("server", sv, "port", int, None), 8025),
        "radius": pick(args.radius, num("server", sv, "radius", float, None), 25.0),
        "radius_choices": radius_choices,
        # a relative db path is relative to the script, so a copied folder keeps working
        "db": os.path.join(SCRIPT_DIR, os.path.expanduser(pick(args.db, sv.get("db"), DB_PATH))),
        "unsold_warn": num("defaults", df, "unsold_warn", int, UNSOLD_WARN),
        "unsold_urgent": num("defaults", df, "unsold_urgent", int, UNSOLD_URGENT),
        "bio_min": num("defaults", df, "bio_min", int, BIO_MIN),
        "sounds": bool(df.get("sounds", SOUNDS_DEFAULT)),
        "body_highlight": num("defaults", df, "body_highlight_level", int, BODY_HIGHLIGHT),
        "bio_highlight": num("defaults", df, "biology_highlight_value", int, BIO_HIGHLIGHT),
        "max_include_bonus": bool(df.get("body_max_value_include_bonus", MAX_INCLUDE_BONUS)),
        "voice": str(df.get("voice") or VOICE), "voice_fallback": str(df.get("voice_fallback") or VOICE_FALLBACK),
        "speech_styles": [str(x) for x in (df.get("speech_styles") if isinstance(df.get("speech_styles"), list)
                                           else SPEECH_STYLES)],
        "speech_profanity": bool(df.get("speech_profanity", SPEECH_PROFANITY)),
        "speech_profanity_pct": min(100, max(0, num("defaults", df, "speech_profanity_pct", int, SPEECH_PROFANITY_PCT))),
        "speak_bio_signals": bool(df.get("speak_bio_signals", SPEAK_BIO_SIGNALS)),
        "speak_geo_signals": bool(df.get("speak_geo_signals", SPEAK_GEO_SIGNALS)),
        "speech_speed": min(2.0, max(0.5, num("defaults", df, "speech_speed", float, SPEECH_SPEED))),
        "speech_names": ", ".join(str(x) for x in df["speech_names"]) if isinstance(df.get("speech_names"), list)
                        else str(df.get("speech_names", SPEECH_NAMES)),
        "speech_file": os.path.join(SCRIPT_DIR, os.path.expanduser(str(sv.get("speech_file") or SPEECH_FILE))),
        "backup_dir": os.path.join(SCRIPT_DIR, os.path.expanduser(str(sv.get("backup_dir") or BACKUP_DIR))),
        "concurrency": num("spansh", sp, "concurrency", int, SPANSH_CONCURRENCY),
        "map_max_radius": num("spansh", sp, "map_max_radius", float, MAP_MAX_RADIUS),
        "map_max_pages": num("spansh", sp, "map_max_pages", int, MAP_MAX_PAGES),
        "autohonk": {"enabled": bool(ah.get("enabled", AUTOHONK["enabled"])),
                     "key": str(ah.get("key") or AUTOHONK["key"]),
                     "delay": max(0.0, num("autohonk", ah, "delay", float, AUTOHONK["delay"])),
                     "hold": min(20.0, max(0.5, num("autohonk", ah, "hold", float, AUTOHONK["hold"]))),
                     "skip_honked": bool(ah.get("skip_honked", AUTOHONK["skip_honked"])),
                     "announce": bool(ah.get("announce", AUTOHONK["announce"]))},
    }


def config_text(st):
    """The effective settings as a TOML document (what --write-config writes)."""
    q = lambda v: '"' + str(v).replace("\\", "/").replace('"', '\\"') + '"'
    lst = lambda vs: "[" + ", ".join(q(v) for v in vs) + "]"
    return f"""# ED Outrider configuration. Every key is optional; command-line flags and the ED_JOURNALS
# environment variable override this file, and journal folders are auto-detected when absent.

[journals]
live = {lst(st["live"])}      # folders holding Journal.*.log that are tailed live
legacy = {lst(st["legacy"])}  # folders of older journals, imported once and never re-read

[server]
host = {q(st["host"])}   # "0.0.0.0" to reach the page from another device on your network
port = {st["port"]}
radius = {st["radius"]:g}      # ly: the sphere of nearby systems the page lists
radius_choices = [{", ".join(f"{x:g}" for x in st["radius_choices"])}]   # ly: what the page's radius dropdown offers
backup_dir = {q(st["backup_dir"])}   # where "Back up now" writes the database and a copy of the journals
speech_file = {q(os.path.basename(st["speech_file"]) if os.path.dirname(st["speech_file"]) == SCRIPT_DIR else st["speech_file"])}   # the spoken alerts' lines, per personality
db = {q(os.path.basename(st["db"]) if os.path.dirname(st["db"]) == SCRIPT_DIR else st["db"])}

[defaults]   # what a browser uses until its user changes it (page settings stay per browser)
unsold_warn = {st["unsold_warn"]}     # amber "worth selling soon", credits on board
unsold_urgent = {st["unsold_urgent"]}   # red "go sell"
bio_min = {st["bio_min"]}         # a body only counts as unfinished bio if it could pay over this
sounds = {"true" if st["sounds"] else "false"}
body_highlight_level = {st["body_highlight"]}     # Here: a body's row turns green if scan + map pays this, no bonuses
biology_highlight_value = {st["bio_highlight"]}  # Here: a body's bio turns violet if it could pay this, no x5 bonus
body_max_value_include_bonus = {"true" if st["max_include_bonus"] else "false"}  # Here: Max counts first-discovery/mapped/footfall bonuses
voice = {q(st["voice"])}          # spoken alerts: Piper voice (downloaded into piper-voices/ on first use)
voice_fallback = {q(st["voice_fallback"])}  # used while the voice above is missing
speech_styles = [{", ".join(q(x) for x in st["speech_styles"])}]   # spoken alerts' personalities: any of the styles in the speech file
speech_profanity = {"true" if st["speech_profanity"] else "false"}   # also use the swearing versions (sarcastic, sweet)
speech_profanity_pct = {st["speech_profanity_pct"]}   # with profanity on: how often (%) a line is a swearing one
speak_bio_signals = {"true" if st["speak_bio_signals"] else "false"}   # say biological signal counts as the FSS finds them
speak_geo_signals = {"true" if st["speak_geo_signals"] else "false"}   # and geological ones
speech_speed = {st["speech_speed"]:g}   # spoken alerts' pace: 1 is the voice's own, 1.3 is 30% faster (0.5 to 2)
speech_names = {q(st["speech_names"])}   # what the voice calls you, comma separated: one is picked at random each time

[spansh]
concurrency = {st["concurrency"]}          # body-detail fetches in flight after an arrival
map_max_radius = {st["map_max_radius"]:g}    # ly: the largest 3D map the page may ask for
map_max_pages = {st["map_max_pages"]}        # pages of 500 systems fetched for the map

[autohonk]   # hold Primary Fire on arriving by hyperspace, so the Discovery Scanner fires (Linux; see ed_honk.py)
# IMPORTANT: the Discovery Scanner MUST be on PRIMARY FIRE in the fire group that is active when you jump,
# and Primary Fire needs a keyboard binding (key = "auto" reads it, modifiers too, from your controls preset).
enabled = {"true" if st["autohonk"]["enabled"] else "false"}   # the page's alerts dialog can switch it on and off too
key = {q(st["autohonk"]["key"])}   # "auto": Primary Fire's keyboard binding from your controls preset; or e.g. KEY_KP0, KEY_LEFTALT+KEY_K
delay = {st["autohonk"]["delay"]:g}   # seconds after arriving before the press (the jump tunnel ignores input)
hold = {st["autohonk"]["hold"]:g}    # seconds to hold the trigger (the scanner fires once charged)
skip_honked = {"true" if st["autohonk"]["skip_honked"] else "false"}   # leave systems you have already honked alone
announce = {"true" if st["autohonk"]["announce"] else "false"}   # say "System scan completed, 12 bodies discovered" (or all found) afterwards
"""

POSITION_EVENTS = ("FSDJump", "CarrierJump", "Location")
STAR_CLASS_EVENTS = ("FSDTarget", "StartJump")
SCAN_EVENTS = ("Scan", "FSSDiscoveryScan", "FSSAllBodiesFound", "SAASignalsFound", "FSSBodySignals",
               "SAAScanComplete", "Disembark", "ScanOrganic", "CodexEntry", "ScanBaryCentre")
# Your fleet carrier, and fuel: where it is, what it carries, how much is in the tank.
SHIP_EVENTS = ("FuelScoop", "RefuelAll", "RefuelPartial", "CarrierStats", "CarrierJump", "CarrierJumpRequest",
               "CarrierJumpCancelled", "CarrierLocation", "Docked", "Undocked",
               # hull and danger: live alerts only (hull % is kept; the rest are moments, not state)
               "HullDamage", "RepairAll", "Repair", "HeatDamage", "Interdicted",
               "JetConeBoost",   # a neutron / white dwarf charge: the next jump's range is multiplied
               "NavRouteClear")  # the plotted route was cleared
# Selling or losing exploration data decides whether your discoveries were credited.
DATA_EVENTS = ("MultiSellExplorationData", "SellExplorationData", "SellOrganicData", "Died", "Resurrect")
# Who is playing and what they had at login: name, credits.
CMDR_EVENTS = ("LoadGame", "Commander", "Rank", "Progress", "Promotion", "Statistics")
RANK_KEYS = ("Combat", "Trade", "Explore", "Soldier", "Exobiologist", "Empire", "Federation", "CQC")
RANK_NAMES = {   # the two ranks an explorer cares about
    "Explore": ["Aimless", "Mostly Aimless", "Scout", "Surveyor", "Trailblazer", "Pathfinder", "Ranger", "Pioneer",
                "Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V"],
    "Exobiologist": ["Directionless", "Mostly Directionless", "Compiler", "Collector", "Cataloguer", "Taxonomist",
                     "Ecologist", "Geneticist", "Elite", "Elite I", "Elite II", "Elite III", "Elite IV", "Elite V"],
}
# Engineering materials: the login snapshot and everything that adds or spends them (see ed_materials).
MATERIAL_EVENTS = ("Materials", "MaterialCollected", "MaterialDiscarded", "Synthesis", "EngineerCraft",
                   "MaterialTrade", "TechnologyBroker", "ScientificResearch", "MissionCompleted",
                   "EngineerContribution")
WANTED = tuple(f'"event":"{e}"'.encode()
               for e in POSITION_EVENTS + STAR_CLASS_EVENTS + SCAN_EVENTS + DATA_EVENTS + SHIP_EVENTS
               + CMDR_EVENTS + MATERIAL_EVENTS + ("Loadout", "Shutdown"))

# Bump when the journal parser learns new events: forces a one-off re-read of every journal.
PARSER_VERSION = 21

SCOOPABLE = set("OBAFGKM")
FUEL_HISTORY = 20          # recent jumps used to estimate fuel per jump
# Planet classes worth a detour (plus anything terraformable).
NOTABLE_PLANETS = {"Earth-like world": "ELW", "Water world": "WW", "Ammonia world": "AW"}
BIO = "$SAA_SignalType_Biological;"
GEO = "$SAA_SignalType_Geological;"

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS journal_files (
    path TEXT PRIMARY KEY, offset INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS visits (
    id64 INTEGER PRIMARY KEY, name TEXT, x REAL, y REAL, z REAL,
    first_ts TEXT, last_ts TEXT, count INTEGER NOT NULL DEFAULT 0);
-- Every arrival, in order: the path you flew. kind is the event (FSDJump, CarrierJump, or Location
-- for a login/respawn somewhere new, which breaks the path). star_class comes from StartJump.
CREATE TABLE IF NOT EXISTS jumps (
    ts TEXT, id64 INTEGER, name TEXT, x REAL, y REAL, z REAL, star_class TEXT, kind TEXT,
    PRIMARY KEY (ts, id64));
CREATE TABLE IF NOT EXISTS route_systems (
    id64 INTEGER PRIMARY KEY, name TEXT, x REAL, y REAL, z REAL,
    star_class TEXT, seen_ts TEXT);
CREATE TABLE IF NOT EXISTS star_classes (
    id64 INTEGER PRIMARY KEY, star_class TEXT);
CREATE TABLE IF NOT EXISTS spansh_systems (
    id64 INTEGER PRIMARY KEY, updated_at TEXT, summary TEXT, fetched_ts REAL);
-- Your own scans, straight from the journal.
CREATE TABLE IF NOT EXISTS own_systems (
    id64 INTEGER PRIMARY KEY, name TEXT, body_count INTEGER, all_found INTEGER);
CREATE TABLE IF NOT EXISTS own_bodies (
    system INTEGER, body_id INTEGER, name TEXT, record TEXT, ts TEXT, raw TEXT,
    PRIMARY KEY (system, body_id));
-- Barycentres (the Null entries in a body's Parents): their orbit, from ScanBaryCentre.
CREATE TABLE IF NOT EXISTS own_barycentres (
    system INTEGER, body_id INTEGER, record TEXT, ts TEXT,
    PRIMARY KEY (system, body_id));
CREATE TABLE IF NOT EXISTS own_signals (
    system INTEGER, name TEXT, bio INTEGER, geo INTEGER, ts TEXT,
    PRIMARY KEY (system, name));
-- Discovery flags from your *first* scan of each body (later rescans say "discovered" once you've sold).
CREATE TABLE IF NOT EXISTS own_firsts (
    system INTEGER, body_id INTEGER, name TEXT, is_main INTEGER,
    was_discovered INTEGER, was_mapped INTEGER, was_footfalled INTEGER,
    first_ts TEXT, undisc_ts TEXT, PRIMARY KEY (system, body_id));
CREATE TABLE IF NOT EXISTS own_mapped (system INTEGER, body_id INTEGER, ts TEXT, PRIMARY KEY (system, body_id));
CREATE TABLE IF NOT EXISTS own_footfall (system INTEGER, body_id INTEGER, ts TEXT, PRIMARY KEY (system, body_id));
CREATE TABLE IF NOT EXISTS sales (name TEXT, ts TEXT, bodies INTEGER);
CREATE TABLE IF NOT EXISTS bio_sales (ts TEXT PRIMARY KEY, species INTEGER);
CREATE INDEX IF NOT EXISTS sales_name ON sales (name);
-- option is the Resurrect choice that followed: "rebuy" means the ship (and its data) was lost.
CREATE TABLE IF NOT EXISTS deaths (ts TEXT PRIMARY KEY, option TEXT);
-- Exobiology: genera a DSS found on a body, and your sampling progress per species.
CREATE TABLE IF NOT EXISTS own_genera (
    system INTEGER, body_id INTEGER, genus TEXT, genus_name TEXT, ts TEXT,
    PRIMARY KEY (system, body_id, genus));
CREATE TABLE IF NOT EXISTS own_organic (
    system INTEGER, body_id INTEGER, species TEXT, genus_name TEXT, species_name TEXT, variant_name TEXT,
    samples INTEGER NOT NULL DEFAULT 0, done_ts TEXT, ts TEXT,
    PRIMARY KEY (system, body_id, species));
-- Codex entries: is_new = new to your codex for that region; voucher = codex credits paid (not a galactic first).
CREATE TABLE IF NOT EXISTS codex (
    ts TEXT, entry_id INTEGER, name TEXT, category TEXT, subcategory TEXT, region TEXT,
    system INTEGER, system_name TEXT, body_id INTEGER, is_new INTEGER, new_traits TEXT, voucher INTEGER,
    PRIMARY KEY (ts, entry_id));
CREATE INDEX IF NOT EXISTS codex_system ON codex (system);
CREATE INDEX IF NOT EXISTS jumps_ts ON jumps (ts);
CREATE INDEX IF NOT EXISTS own_firsts_system ON own_firsts (system);
CREATE TABLE IF NOT EXISTS own_ring_signals (
    system INTEGER, name TEXT, hotspots TEXT, ts TEXT,
    PRIMARY KEY (system, name));
-- Where each exobiology sample of the current run was taken (from Status.json at the time, live play only):
-- the sample-spacing readout measures from these. n = 1 (Log), 2 (Sample).
CREATE TABLE IF NOT EXISTS sample_points (
    system INTEGER, body_id INTEGER, species TEXT, genus TEXT, n INTEGER, lat REAL, lon REAL, ts TEXT,
    PRIMARY KEY (system, body_id, species, n));
-- Every sale, with what it actually paid (the trip ledger); estimate = Outrider's estimate just before it
-- (recorded live from now on, NULL for sales before the tool saw them).
CREATE TABLE IF NOT EXISTS sale_events (
    ts TEXT, kind TEXT, base INTEGER, bonus INTEGER, total INTEGER, systems INTEGER, species INTEGER, estimate INTEGER,
    PRIMARY KEY (ts, kind));
-- Notable stellar phenomena (the FSS "Codex" signals $Fixed_Event_Life_Cloud/Ring): kind cloud|ring;
-- reached_ts is set when you drop out of supercruise at one.
CREATE TABLE IF NOT EXISTS phenomena (
    system INTEGER, kind TEXT, ts TEXT, reached_ts TEXT, PRIMARY KEY (system, kind));
-- Bookmarks made on the page (the game's own bookmarks never reach the journal).
CREATE TABLE IF NOT EXISTS bookmarks (
    id64 INTEGER PRIMARY KEY, name TEXT, x REAL, y REAL, z REAL, note TEXT, created_ts TEXT);
CREATE INDEX IF NOT EXISTS route_xyz ON route_systems (x, y, z);
CREATE INDEX IF NOT EXISTS visits_xyz ON visits (x, y, z);
"""

RESET_JOURNAL_DATA = """
DELETE FROM meta WHERE key IN ('hull', 'last_sale', 'boost', 'statistics', 'route');
DELETE FROM journal_files; DELETE FROM visits; DELETE FROM jumps;
DELETE FROM own_systems; DELETE FROM own_bodies; DELETE FROM own_signals; DELETE FROM own_ring_signals;
DELETE FROM own_firsts; DELETE FROM own_mapped; DELETE FROM own_footfall; DELETE FROM sales; DELETE FROM deaths;
DELETE FROM own_genera; DELETE FROM own_organic; DELETE FROM codex; DELETE FROM bio_sales;
DELETE FROM own_barycentres; DELETE FROM phenomena; DELETE FROM sale_events; DELETE FROM sample_points;
DELETE FROM meta WHERE key IN ('ship', 'carrier', 'fuel_hist', 'last_scoop', 'commander', 'materials');
DELETE FROM meta WHERE key LIKE 'legacy:%' OR key IN ('pos', 'prev', 'jump_range');
"""


def open_db(path, rescan=False):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    # Columns added to an existing table since the database was created: add them.
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", SCHEMA, re.S):
        table, body = m.group(1), m.group(2)
        have = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        for col in re.split(r",\s*(?![^()]*\))", body):
            col = col.strip()
            name = col.split()[0] if col else ""
            if name and name.upper() not in ("PRIMARY",) and name not in have and not col.upper().startswith("PRIMARY KEY"):
                db.execute(f"ALTER TABLE {table} ADD COLUMN {col.split(',')[0]}")
    cols = {r["name"] for r in db.execute("PRAGMA table_info(spansh_systems)")}
    if "x" not in cols:
        db.executescript("ALTER TABLE spansh_systems ADD COLUMN x REAL;"
                         "ALTER TABLE spansh_systems ADD COLUMN y REAL;"
                         "ALTER TABLE spansh_systems ADD COLUMN z REAL;")
        for r in db.execute("SELECT id64, summary FROM spansh_systems").fetchall():
            b = json.loads(r["summary"])
            db.execute("UPDATE spansh_systems SET x=?, y=?, z=? WHERE id64=?",
                       (b.get("x"), b.get("y"), b.get("z"), r["id64"]))
        db.execute("CREATE INDEX IF NOT EXISTS spansh_xyz ON spansh_systems (x, y, z)")
        db.commit()
    if rescan or meta_get(db, "parser_version") != PARSER_VERSION:
        db.executescript(RESET_JOURNAL_DATA)
        meta_set(db, "parser_version", PARSER_VERSION)
        db.commit()
    return db


def ts_seconds(ts):
    """Journal timestamp ('2026-09-28T02:06:56Z') -> seconds since the epoch (UTC)."""
    import calendar
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def meta_get(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def meta_set(db, key, value):
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))


# --------------------------------------------------------------------------
# Body records
#
# Every body, whether from Spansh or your own journal, is reduced to one shape:
#   {name (short, e.g. "A 4"), type "Star"|"Planet", subtype (Spansh wording), main,
#    scoopable, terraformable, landable, rings [{name, type, hotspots}], belts [type],
#    bio, geo, full}
# "full" is False for Spansh search results, which lack rings, belts and signals.
# --------------------------------------------------------------------------

TERRAFORMABLE = {"Candidate for terraforming", "Terraforming", "Terraformable"}

JOURNAL_STARS = {
    "O": "O (Blue-White) Star", "B": "B (Blue-White) Star", "A": "A (Blue-White) Star",
    "F": "F (White) Star", "G": "G (White-Yellow) Star", "K": "K (Yellow-Orange) Star",
    "M": "M (Red dwarf) Star", "L": "L (Brown dwarf) Star", "T": "T (Brown dwarf) Star",
    "Y": "Y (Brown dwarf) Star", "TTS": "T Tauri Star", "AeBe": "Herbig Ae/Be Star",
    "W": "Wolf-Rayet Star", "WN": "Wolf-Rayet N Star", "WNC": "Wolf-Rayet NC Star",
    "WC": "Wolf-Rayet C Star", "WO": "Wolf-Rayet O Star",
    "CS": "CS Star", "C": "C Star", "CN": "CN Star", "CJ": "CJ Star", "CH": "CH Star",
    "CHd": "CHd Star", "MS": "MS-type Star", "S": "S-type Star",
    "N": "Neutron Star", "H": "Black Hole", "SupermassiveBlackHole": "Supermassive Black Hole",
    "A_BlueWhiteSuperGiant": "A (Blue-White super giant) Star",
    "B_BlueWhiteSuperGiant": "B (Blue-White super giant) Star",
    "F_WhiteSuperGiant": "F (White super giant) Star",
    "G_WhiteSuperGiant": "G (White-Yellow super giant) Star",
    "K_OrangeGiant": "K (Yellow-Orange giant) Star",
    "M_RedGiant": "M (Red giant) Star", "M_RedSuperGiant": "M (Red super giant) Star",
}

JOURNAL_PLANETS = {
    "Metal rich body": "Metal-rich body", "High metal content body": "High metal content world",
    "Rocky ice body": "Rocky Ice world", "Earthlike body": "Earth-like world",
    "Gas giant with water based life": "Gas giant with water-based life",
    "Gas giant with ammonia based life": "Gas giant with ammonia-based life",
    "Helium rich gas giant": "Helium-rich gas giant",
}

RING_CLASSES = {"eRingClass_Icy": "Icy", "eRingClass_Rocky": "Rocky",
                "eRingClass_MetalRich": "Metal Rich", "eRingClass_Metalic": "Metallic"}


def journal_star(code):
    if code in JOURNAL_STARS:
        return JOURNAL_STARS[code]
    if code and code.startswith("D"):
        return f"White Dwarf ({code}) Star"
    return code


def journal_planet(cls):
    if cls in JOURNAL_PLANETS:
        return JOURNAL_PLANETS[cls]
    m = re.match(r"^Sudarsky class (\w+) gas giant$", cls or "")
    return f"Class {m.group(1)} gas giant" if m else cls


# Spansh's names back to the journal's, for pricing Spansh bodies with the same formula as your scans.
SPANSH_STARS = {v: k for k, v in JOURNAL_STARS.items()}
SPANSH_PLANETS = {v: k for k, v in JOURNAL_PLANETS.items()}
SPANSH_TERRAFORM = {"Candidate for terraforming": "Terraformable", "Terraforming": "Terraforming",
                    "Terraformed": "Terraformed"}


def ed_from_dump(b):
    """The fields ed_unsold.body_value prices by, from a Spansh dump body; None if it cannot be priced
    (a star or planet class, or a mass, missing)."""
    st = b.get("subType") or ""
    if b.get("type") == "Star":
        code = SPANSH_STARS.get(st)
        if not code:
            m = re.match(r"^White Dwarf \((\w+)\) Star$", st)
            code = m.group(1) if m else None
        if not code or b.get("solarMasses") is None:
            return None
        return {"StarType": code, "StellarMass": b["solarMasses"], "PlanetClass": None, "TerraformState": None,
                "MassEM": None}
    if b.get("type") == "Planet":
        m = re.match(r"^Class (\w+) gas giant$", st)
        cls = SPANSH_PLANETS.get(st) or (f"Sudarsky class {m.group(1)} gas giant" if m else st)
        if not cls or b.get("earthMasses") is None:
            return None
        return {"StarType": None, "StellarMass": None, "PlanetClass": cls,
                "TerraformState": SPANSH_TERRAFORM.get(b.get("terraformingState"), ""), "MassEM": b["earthMasses"]}
    return None


def carto_values(r, scanned, f, scan_state, map_state, odyssey=True):
    """Cartographic credits for one body, as pairs of (with bonuses, bonus-free):

    now   what the data you hold would pay if sold now
    left  what is still there to add: an unscanned or lost scan, and an unmapped or lost map

    `scan_state` / `map_state` are pickup_judge verdicts (unsold / sold / lost) for your latest scan
    and your latest map; None when you have not scanned or mapped. Lost data counts as recoverable
    (scan and map it again); sold data is done. Bodies with pricing fields ("ed", from your scan or a
    Spansh dump) use ed_unsold.body_value; the rest fall back to Spansh's search estimates.
    """
    planet = r.get("type") == "Planet"
    first_disc = bool(f and f["was_discovered"] == 0)
    first_map = bool(f and f["was_mapped"] == 0)
    if r.get("ed") and ed_unsold:
        def price(bonus):
            body = dict(r["ed"], first_discovered=first_disc and bonus, first_mapped=first_map and bonus)
            return (ed_unsold.body_value(body, False, False, odyssey),
                    ed_unsold.body_value(body, True, False, odyssey) if planet else None)
        (scan_b, map_b), (scan_p, map_p) = price(True), price(False)
    else:   # Spansh's search-level estimates (scan, scan + map), no bonuses in them
        scan_b = scan_p = r.get("scan_value") or 0
        map_b = map_p = (r.get("value") or scan_b) if planet else None

    def split(scan, mapped):
        extra = max(0, (mapped or scan) - scan) if planet else 0     # what the map adds on top of the scan
        now = (scan if scan_state == "unsold" else 0) + (extra if map_state == "unsold" else 0)
        left = (scan if scan_state in (None, "lost") else 0) + (extra if planet and map_state in (None, "lost") else 0)
        return now, left
    (now, left), (now_nb, left_nb) = split(scan_b, map_b), split(scan_p, map_p)
    did_map = map_state in ("unsold", "sold")
    return {"now": now, "left": left, "now_nb": now_nb, "left_nb": left_nb,
            "value": (map_b if did_map else scan_b) if scanned else scan_b,
            "value_if_mapped": map_b if planet and not did_map else None,
            "base_value": map_p if planet else scan_p,
            "mapped": did_map, "first_mapped": did_map and first_map}


def short_name(parent, name):
    """'Smojoo AL-P c5-27 A 4' -> 'A 4' under the system; a lone main star keeps its name."""
    if name and parent and name.startswith(parent + " "):
        return name[len(parent) + 1:]
    return name


def split_ring_name(system, ring):
    """'Sys A 3 B Ring' -> ('A 3', 'B Ring')."""
    parts = short_name(system, ring).rsplit(" ", 2)
    if len(parts) == 3:
        return parts[0], f"{parts[1]} {parts[2]}"
    if len(parts) == 2:  # "Sys A Ring": a ring around the lone main star, whose record is named "Sys"
        return system, f"{parts[0]} {parts[1]}"
    return None, ring


# Journal and Spansh dumps say "LowTemperatureDiamond"/"Opal"; Spansh's search API and the
# game's UI say "Low Temperature Diamonds"/"Void Opal". Everything here uses the latter.
MINERAL_NAMES = {"LowTemperatureDiamond": "Low Temperature Diamonds", "Opal": "Void Opal"}
HOTSPOT_MINERALS = ["Alexandrite", "Benitoite", "Bromellite", "Grandidierite",
                    "Low Temperature Diamonds", "Monazite", "Musgravite", "Painite", "Platinum",
                    "Rhodplumsite", "Serendibite", "Tritium", "Void Opal"]
_MINERAL_BY_LOWER = {m.lower(): m for m in HOTSPOT_MINERALS} | {k.lower(): v for k, v in MINERAL_NAMES.items()}


def mineral_name(k):
    """The canonical hotspot name, whatever the case: the game writes both "tritium" and "Tritium"."""
    return MINERAL_NAMES.get(k) or _MINERAL_BY_LOWER.get((k or "").lower(), k)


def minerals(signals):
    """Ring hotspots, dropping any non-mineral $SAA_... entries."""
    return {mineral_name(k): v for k, v in (signals or {}).items() if not k.startswith("$")}


LIGHT_SPEED = 299792458.0       # m/s: journal distances are metres
AU_LS = 499.00478384            # light-seconds in an AU (Spansh orbits are in AU)
SOLAR_RADIUS_KM = 695700.0


def parents_full(parents):
    """A journal/Spansh Parents list -> [{kind: Star|Planet|Null|Ring, id}], nearest first. None if unknown."""
    if parents is None:
        return None
    return [{"kind": k, "id": v} for p in parents for k, v in p.items()]


def build_tree(system, bodies):
    """The system's hierarchy for the schematic view.

    `bodies` are rows with name (short), type, main, body_id and parents_full. Trust order: the
    Parents chain (Null entries are barycentres), then the body's name ('A 6 a' orbits 'A 6'; 'AB 1'
    orbits the A-B barycentre), then the main star. Returns nested nodes:
    {kind: body|barycentre|unknown, name|id, label, children: [...]}, children in orbital order.
    """
    names = {b["name"]: b for b in bodies}
    by_id = {b["body_id"]: b["name"] for b in bodies if b.get("body_id") is not None}
    parent = {}
    ref = lambda kind, i: ("n", i) if kind == "Null" else (("b", by_id[i]) if i in by_id else ("u", i))
    for b in bodies:
        chain = [p for p in b.get("parents_full") or [] if p["kind"] != "Ring"]
        cur = ("b", b["name"])
        for p in chain:
            k = ref(p["kind"], p["id"])
            if k == cur or cur in parent:
                break
            parent[cur] = k
            cur = k
    # direct star children of each barycentre give it its label ("A+B") and let names like "AB 1" find it
    kids = {}
    for c, par in parent.items():
        kids.setdefault(par, []).append(c)
    star_letters = lambda key: sorted(c[1] for c in kids.get(key, []) if c[0] == "b" and names[c[1]]["type"] == "Star")
    groups = {}
    for key in kids:
        if key[0] == "n":
            letters = star_letters(key)
            if letters and all(len(x) == 1 and x.isupper() for x in letters):
                groups.setdefault("".join(letters), key)
    main = next((b["name"] for b in bodies if b.get("main")), None)
    for b in bodies:
        k = ("b", b["name"])
        if k in parent or b.get("parents_full") == [] or b["name"] == main:
            continue    # placed by its Parents chain, or known to orbit nothing
        tokens = b["name"].split()
        found = None
        for i in range(len(tokens) - 1, 0, -1):
            cand = " ".join(tokens[:i])
            if cand in names and cand != b["name"]:
                found = ("b", cand)
                break
        if not found and len(tokens) > 1 and len(tokens[0]) > 1 and tokens[0].isalpha() and tokens[0].isupper():
            found = groups.get(tokens[0]) or ("g", tokens[0])   # 'AB 1': around the A-B barycentre
        if not found and b["type"] != "Star" and main and main != b["name"]:
            found = ("b", main)
        if found:
            parent[k] = found
    # assemble, guarding against cycles in odd data
    kids = {}
    for c, par in parent.items():
        kids.setdefault(par, []).append(c)
    everything = {("b", n) for n in names} | set(parent.values())
    def order(key):   # orbital order: body id, then distance from arrival, then the name
        b = names.get(key[1]) if key[0] == "b" else None
        bid = b.get("body_id") if b else key[1] if key[0] in "nu" else None
        return (bid if bid is not None else 10 ** 6, (b or {}).get("dist_ls") or 0, natural(str(key[1])))
    seen = set()

    def node(key):
        seen.add(key)
        children = [node(c) for c in sorted(kids.get(key, []), key=order) if c not in seen]
        if key[0] == "b":
            return {"kind": "body", "name": key[1], "children": children}
        if key[0] == "n":
            letters = star_letters(key)
            members = [c["name"] for c in children if c["kind"] == "body"]
            nested = [f"({c['label']})" for c in children if c["kind"] == "barycentre"]   # a pair inside this one
            if letters and all(len(x) == 1 and x.isupper() for x in letters):
                # lettered stars name the centre (A+B); planets circling the pair (AB 1) are not part of it
                parts = ["+".join(letters)]
            else:
                parts = [" + ".join(members)] if members else []
            label = "+".join(parts + nested) if parts or nested else f"barycentre #{key[1]}"
            return {"kind": "barycentre", "id": key[1], "label": label, "children": children}
        if key[0] == "g":
            return {"kind": "barycentre", "id": None, "label": "+".join(key[1]), "children": children}
        return {"kind": "unknown", "id": key[1], "label": f"body #{key[1]}", "children": children}

    roots = sorted((k for k in everything if k not in parent), key=order)
    tree = [node(k) for k in roots]
    tree += [node(k) for k in sorted(everything - seen, key=order) if k not in seen]  # cycle leftovers
    return tree, {c[1]: p for c, p in parent.items() if c[0] == "b"}


def record_from_search(system, b):
    st = b.get("subtype")
    return {"name": short_name(system, b.get("name")), "type": b.get("type"), "subtype": st,
            "main": bool(b.get("is_main_star")), "scoopable": subtype_scoopable(st),
            "terraformable": b.get("terraforming_state") in TERRAFORMABLE, "full": False,
            # Spansh's own credit estimates: what a scan is worth, and what scan+map is worth.
            "value": b.get("estimated_mapping_value"), "scan_value": b.get("estimated_scan_value"),
            "dist_ls": b.get("distance_to_arrival")}


def genus_label(g):
    """A genus from a Spansh dump ({name: ...} or '$Codex_Ent_..._Genus_Name;') -> its display name."""
    name = g.get("name") or g.get("genus") if isinstance(g, dict) else g
    return ed_bio.genus_from_id(name) if ed_bio else name


def record_from_dump(system, b):
    st = b.get("subType")
    signals = (b.get("signals") or {}).get("signals") or {}
    return {
        "name": short_name(system, b.get("name")), "type": b.get("type"), "subtype": st,
        "main": bool(b.get("mainStar")), "scoopable": subtype_scoopable(st),
        "terraformable": b.get("terraformingState") in TERRAFORMABLE,
        "landable": bool(b.get("isLandable")),
        "rings": [{"name": short_name(b.get("name"), r.get("name")), "type": r.get("type"),
                   "hotspots": minerals((r.get("signals") or {}).get("signals")), "mapped": "signals" in r,
                   "mass": r.get("mass"), "inner": r.get("innerRadius"), "outer": r.get("outerRadius")}
                  for r in b.get("rings") or []],
        "pressure": round(b["surfacePressure"], 4) if b.get("surfacePressure") is not None else None,
        "belts": [r.get("type") for r in b.get("belts") or []],
        "bio": signals.get(BIO, 0), "geo": signals.get(GEO, 0), "full": True,
        "gravity": round(b["gravity"], 2) if b.get("gravity") is not None else None,
        "atmosphere": b.get("atmosphereType"), "dist_ls": b.get("distanceToArrival"),
        "temperature": b.get("surfaceTemperature"), "volcanism": b.get("volcanismType"),
        # Spansh lists the DSS's genera as objects in some dumps and as bare genus codes in others
        "genera": [genus_label(g) for g in (b.get("signals") or {}).get("genuses") or [] if g],
        # what the exobiology rules ask about beyond the basics (see ed_bio)
        "body_id": b.get("bodyId"), "luminosity": b.get("luminosity"),
        "parents": [p["Star"] for p in b.get("parents") or [] if "Star" in p],
        "orbital_period_s": round(b["orbitalPeriod"] * 86400) if b.get("orbitalPeriod") else None,
        "atmo_comp": b.get("atmosphereComposition"),
        "materials": surface_materials(b.get("materials")),   # some bios' colours (and so their chances) depend on them
        # the system schematic: hierarchy, size, orbit
        "parents_full": parents_full(b.get("parents")),
        "radius_km": b.get("radius") or (b["solarRadius"] * SOLAR_RADIUS_KM if b.get("solarRadius") else None),
        "sma_ls": b["semiMajorAxis"] * AU_LS if b.get("semiMajorAxis") else None,
        "ed": ed_from_dump(b),   # priced with the same formula as your own scans (see carto_values)
    }


def record_from_scan(ev):
    """Journal Scan event -> body record (names still full; shortened when merged)."""
    name = ev.get("BodyName")
    if ev.get("StarType"):
        kind, subtype = "Star", journal_star(ev["StarType"])
    elif ev.get("PlanetClass"):
        kind, subtype = "Planet", journal_planet(ev["PlanetClass"])
    else:
        return None  # belt clusters and the like
    rings, belts = [], []
    for r in ev.get("Rings") or []:
        rtype = RING_CLASSES.get(r.get("RingClass"), r.get("RingClass"))
        if r.get("Name", "").endswith("Belt"):
            belts.append(rtype)
        else:
            rings.append({"name": short_name(name, r.get("Name")), "type": rtype, "hotspots": {},
                          "mass": r.get("MassMT"), "inner": r.get("InnerRad"), "outer": r.get("OuterRad")})
    g = ev.get("SurfaceGravity")
    return {
        "name": name, "type": kind, "subtype": subtype,
        "main": kind == "Star" and not ev.get("DistanceFromArrivalLS"),
        "scoopable": kind == "Star" and class_scoopable(ev["StarType"]),
        "terraformable": ev.get("TerraformState") in TERRAFORMABLE,
        "landable": bool(ev.get("Landable")),
        "rings": rings, "belts": belts, "bio": 0, "geo": 0, "full": True,
        "gravity": round(g / 9.80665, 2) if g else None,
        "atmosphere": ev.get("AtmosphereType") or None, "volcanism": ev.get("Volcanism") or None,
        "dist_ls": ev.get("DistanceFromArrivalLS"), "temperature": ev.get("SurfaceTemperature"),
        "pressure": round(ev["SurfacePressure"] / 101325, 4) if ev.get("SurfacePressure") else (0 if "SurfacePressure" in ev else None),
        "was_discovered": ev.get("WasDiscovered"), "was_mapped": ev.get("WasMapped"),
        "scan_type": ev.get("ScanType"),
        "body_id": ev.get("BodyID"), "luminosity": ev.get("Luminosity"),
        "parents": [p["Star"] for p in ev.get("Parents") or [] if "Star" in p],
        "orbital_period_s": ev.get("OrbitalPeriod"),
        "parents_full": parents_full(ev.get("Parents")),
        "radius_km": ev["Radius"] / 1000 if ev.get("Radius") else None,
        "sma_ls": ev["SemiMajorAxis"] / LIGHT_SPEED if ev.get("SemiMajorAxis") else None,
        "atmo_comp": ({c["Name"]: c["Percent"] for c in ev.get("AtmosphereComposition") or []}
                      if "AtmosphereComposition" in ev else None),
        "materials": surface_materials(ev.get("Materials")),
        # what ed_unsold.body_value needs to price it
        "ed": {k: ev.get(k) for k in ("StarType", "StellarMass", "PlanetClass", "TerraformState", "MassEM")},
    }


def own_data(db, id64, system):
    """Your own scans of a system: (records keyed by short name, ring hotspots, FSS body count)."""
    records = {}
    for row in db.execute("SELECT record FROM own_bodies WHERE system=?", (id64,)):
        r = json.loads(row["record"])
        r["name"] = short_name(system, r["name"])
        records[r["name"]] = r
    for row in db.execute("SELECT * FROM own_signals WHERE system=?", (id64,)):
        r = records.get(short_name(system, row["name"]))
        if r:
            r["bio"], r["geo"] = row["bio"], row["geo"]
    hotspots = {}
    for row in db.execute("SELECT * FROM own_ring_signals WHERE system=?", (id64,)):
        hotspots[split_ring_name(system, row["name"])] = json.loads(row["hotspots"])
    sysrow = db.execute("SELECT body_count FROM own_systems WHERE id64=?", (id64,)).fetchone()
    return records, hotspots, sysrow["body_count"] if sysrow else None


def merge_records(spansh, own, hotspots):
    """Spansh records overlaid with your own; your DSS ring hotspots win over Spansh's."""
    out = {r["name"]: dict(r) for r in spansh}
    for name, r in own.items():
        base = out.get(name)
        if base and not r.get("bio") and not r.get("geo"):
            # Your scan may predate the DSS that gave Spansh its signal counts.
            r = dict(r, bio=base.get("bio", 0), geo=base.get("geo", 0))
        if base:
            spansh_rings = {x["name"]: x for x in base.get("rings") or []}
            r = dict(r, rings=[dict(x, hotspots=x["hotspots"] or
                                    (spansh_rings.get(x["name"]) or {}).get("hotspots") or {},
                                    mapped=x.get("mapped") or (spansh_rings.get(x["name"]) or {}).get("mapped", False))
                               for x in r["rings"]],
                     value=base.get("value"), scan_value=base.get("scan_value"),
                     genera=r.get("genera") or base.get("genera"))
        out[name] = r
    for (body, ring), hs in hotspots.items():
        r = out.get(body)
        if not r:
            continue
        for x in r.get("rings") or []:
            if x["name"] == ring:
                x["hotspots"] = hs or x.get("hotspots") or {}
                x["mapped"] = True
    return sorted(out.values(), key=lambda r: natural(r["name"] or ""))


# --------------------------------------------------------------------------
# Journal reading
# --------------------------------------------------------------------------

class Journals:
    """Incremental reader: each file is read from where the last pass stopped."""

    def __init__(self, db):
        self.db = db
        self.jump_class = {}       # id64 -> StarClass from the StartJump heading there
        self.arrival_scan = None   # the latest arrival-star Scan: {id64, was_discovered, ts}
        self.status_json = None    # live Status.json: {fuel_main, fuel_reservoir, ts}
        self.codex_new = 0         # new codex entries since the page last looked
        self.bio_sales_changed = False
        self.target = None         # latest FSDTarget, cleared on arrival
        self.dirty = set()         # systems whose own scan data changed since last looked
        self.sales_changed = False  # a sale or death: every row's discovery status may change
        self.materials_changed = False
        self.cmdr_changed = False
        self.bad_files = set()     # journals that could not be read (reported once each)
        # recent moments the page may announce: {seq, ts, kind, ...}; kinds: scan, bio (a body worth a
        # look, priced by State), heat, interdicted. seq only grows; the page remembers the last it saw.
        self.moments = collections.deque(maxlen=16)
        self.jump_arrival = None   # the latest hyperspace arrival {id64, name, ts} (auto honk)
        self.last_honk = None      # the latest discovery scan {id64, ts, bodies, progress}
        self.last_all_found = None # the latest FSSAllBodiesFound {id64, ts}
        self.moment_seq = 0
        self.reload()

    def moment(self, kind, ts, **kw):
        self.moment_seq += 1
        self.moments.append(dict(kw, seq=self.moment_seq, ts=ts, kind=kind))

    def reload(self):
        """(Re)load everything the reader keeps in the database: file offsets and the meta state.

        Called at start, and after a failed tick is rolled back: memory must go back to what the
        database holds, or the retry would skip lines whose rows were rolled back (offsets already
        advanced) and count additive things twice (materials, fuel history, credits earned).
        """
        db = self.db
        self.offsets = {r["path"]: r["offset"] for r in db.execute("SELECT * FROM journal_files")}
        self.pos = meta_get(db, "pos")
        self.prev = meta_get(db, "prev")  # the system you were in before this one
        self.ship = meta_get(db, "ship")            # {name, type, fuel_main, fuel_reserve, max_range, ts}
        self.fuel_hist = meta_get(db, "fuel_hist", [])   # recent [jump ly, fuel t] pairs
        self.last_scoop = meta_get(db, "last_scoop")     # ts of the last FuelScoop
        self.carrier = meta_get(db, "carrier")      # your fleet carrier, see handle_ship
        self.last_event_ts = meta_get(db, "last_event_ts")  # newest journal line handled (freshness)
        self.docked = meta_get(db, "docked")    # {station, type, services, market_id, ts} while docked
        self.jump_range = meta_get(db, "jump_range")
        # {name, fid, credits (at the last LoadGame), login_ts, earned (exploration sales since)}
        self.commander = meta_get(db, "commander")
        self.materials = meta_get(db, "materials") or ed_materials.new_state()
        self.hull = meta_get(db, "hull")            # {pct, ts}: your ship's hull, from Loadout / HullDamage
        self.boost = meta_get(db, "boost")          # {value, ts}: a jet-cone charge, until the next FSDJump
        self.last_sale = meta_get(db, "last_sale")  # {ts, carto, bio, systems, species} of the latest sale

    def import_legacy(self):
        for d in LEGACY_DIRS:
            if meta_get(self.db, f"legacy:{d}"):
                continue
            if not os.path.isdir(d):
                print(f"legacy journal dir not found, skipping: {d}", file=sys.stderr)
                continue
            n = self.scan_dir(d)
            meta_set(self.db, f"legacy:{d}", True)
            self.db.commit()
            print(f"imported {n} journal files from {d}")

    def scan_dir(self, d):
        """Read new data from every journal in d. Returns the number of files touched."""
        touched = 0
        for path in sorted(glob(os.path.join(d, "Journal.*.log"))):
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > self.offsets.get(path, 0):
                try:
                    self.read_file(path)
                except OSError as e:   # unreadable (permissions, a disk error): skip it, keep tailing the rest
                    if path not in self.bad_files:
                        self.bad_files.add(path)
                        print(f"journal skipped, cannot read it ({e.strerror or e}): {path}", file=sys.stderr)
                    continue
                self.bad_files.discard(path)
                touched += 1
        return touched

    def read_file(self, path):
        start = self.offsets.get(path, 0)
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read()
        # Only consume complete lines; the game may be mid-write on the last one.
        end = data.rfind(b"\n") + 1
        for line in data[:end].splitlines():
            if any(w in line for w in WANTED) or b"Fixed_Event_Life" in line:
                try:
                    self.handle(json.loads(line))
                except ValueError:
                    pass
                except (KeyError, TypeError, AttributeError, IndexError) as e:
                    # an event missing a field we index: skip it, not the file (database errors
                    # propagate so the tick is rolled back and retried with the offset unchanged)
                    print(f"journal line skipped ({type(e).__name__}: {e}): {line[:200]!r}", file=sys.stderr)
        self.db.execute("INSERT OR REPLACE INTO journal_files (path, offset) VALUES (?, ?)",
                        (path, start + end))
        self.offsets[path] = start + end
        if end and b'"timestamp":"' in data[:end]:
            ts = data[:end].rsplit(b'"timestamp":"', 1)[-1][:20].decode("ascii", "replace")
            if ts > (self.last_event_ts or ""):
                self.last_event_ts = ts
                meta_set(self.db, "last_event_ts", ts)

    def handle(self, ev):
        ts = ev.get("timestamp", "")
        name = ev.get("event")
        if name in ("FSSSignalDiscovered", "SupercruiseDestinationDrop"):
            self.handle_phenomenon(name, ev, ts)
            return
        if name == "Loadout":
            if ev.get("HullHealth") is not None and ts >= (self.hull or {}).get("ts", ""):
                self.hull = {"pct": round(ev["HullHealth"] * 100), "ts": ts}
                meta_set(self.db, "hull", self.hull)
            if ev.get("MaxJumpRange") and ts >= (self.jump_range or {}).get("ts", ""):
                self.jump_range = {"ly": ev["MaxJumpRange"], "ts": ts}
                meta_set(self.db, "jump_range", self.jump_range)
                cap = ev.get("FuelCapacity") or {}
                fsd = next((m.get("Item", "") for m in ev.get("Modules") or [] if m.get("Slot") == "FrameShiftDrive"), "")
                size = re.search(r"size(\d)", fsd)
                if self.ship and self.ship.get("ship_id") not in (None, ev.get("ShipID")):
                    self.fuel_hist, self.last_scoop = [], None   # a different ship burns differently
                    meta_set(self.db, "fuel_hist", []); meta_set(self.db, "last_scoop", None)
                self.ship = {"name": ev.get("ShipName") or ev.get("Ship"), "type": ev.get("Ship"),
                             "ship_id": ev.get("ShipID"),
                             "fuel_main": cap.get("Main"), "fuel_reserve": cap.get("Reserve"),
                             "max_range": ev["MaxJumpRange"], "fsd_size": int(size.group(1)) if size else None,
                             "rebuy": ev.get("Rebuy"), "hull_value": ev.get("HullValue"), "modules_value": ev.get("ModulesValue"),
                             "ts": ts}
                meta_set(self.db, "ship", self.ship)
            return
        if name in CMDR_EVENTS:
            self.handle_cmdr(name, ev, ts)
            return
        if name == "Shutdown":   # a clean quit to the desktop (a crash writes nothing)
            self.moment("game_exit", ts)
            return
        if name in MATERIAL_EVENTS:
            if ed_materials.apply(self.materials, ev):
                meta_set(self.db, "materials", self.materials)
                self.materials_changed = True
            return
        if name in SHIP_EVENTS and name != "CarrierJump":  # CarrierJump is also a position event
            self.handle_ship(name, ev, ts)
            return
        if name in STAR_CLASS_EVENTS:
            # Targeting a system reveals its main star class, even if nobody has scanned it.
            if ev.get("SystemAddress") and ev.get("StarClass"):
                self.db.execute("INSERT OR REPLACE INTO star_classes VALUES (?, ?)",
                                (ev["SystemAddress"], ev["StarClass"]))
            if name == "StartJump" and ev.get("SystemAddress"):
                self.jump_class = {ev["SystemAddress"]: ev.get("StarClass")}
            if name == "StartJump" and ev.get("JumpType") == "Hyperspace":   # the FSD is charging (not supercruise)
                self.moment("fsd_charge", ts, system=ev.get("StarSystem") or "", star_class=ev.get("StarClass") or "")
            if name == "FSDTarget" and ev.get("SystemAddress"):
                self.target = {"id64": ev["SystemAddress"], "name": ev.get("Name"),
                               "star_class": ev.get("StarClass"), "ts": ts}
            return
        if name in SCAN_EVENTS:
            self.handle_scan(name, ev, ts)
            return
        if name in DATA_EVENTS:
            if name == "Died":
                self.db.execute("INSERT OR IGNORE INTO deaths VALUES (?, NULL)", (ts,))
                # any sample in progress dies with you
                self.db.execute("DELETE FROM own_organic WHERE done_ts IS NULL")
                self.bio_sales_changed = True
            elif name == "SellOrganicData":
                self.db.execute("INSERT OR IGNORE INTO bio_sales VALUES (?, ?)", (ts, len(ev.get("BioData") or [])))
                self.bio_sales_changed = True
                paid = sum((b.get("Value") or 0) + (b.get("Bonus") or 0) for b in ev.get("BioData") or [])
                self.add_earnings(ts, paid)
                self.db.execute("INSERT OR IGNORE INTO sale_events VALUES (?, 'bio', ?, ?, ?, 0, ?, NULL)",
                                (ts, sum(b.get("Value") or 0 for b in ev.get("BioData") or []),
                                 sum(b.get("Bonus") or 0 for b in ev.get("BioData") or []), paid, len(ev.get("BioData") or [])))
                self.note_sale(ts, bio=paid, species=len(ev.get("BioData") or []))
            elif name == "Resurrect":
                self.db.execute("UPDATE deaths SET option = ? WHERE ts = (SELECT max(ts) FROM deaths WHERE ts <= ?)",
                                (ev.get("Option"), ts))
                if ev.get("Option") not in SHIP_SURVIVED_OPTIONS:   # a replacement ship comes with a full tank
                    self.last_scoop = ts
                    meta_set(self.db, "last_scoop", ts)
                    self.hull = {"pct": 100, "ts": ts}
                    meta_set(self.db, "hull", self.hull)
            elif name == "MultiSellExplorationData":
                self.add_earnings(ts, ev.get("TotalEarnings") or 0)
                self.db.execute("INSERT OR IGNORE INTO sale_events VALUES (?, 'carto', ?, ?, ?, ?, 0, NULL)",
                                (ts, ev.get("BaseValue"), ev.get("Bonus"), ev.get("TotalEarnings"), len(ev.get("Discovered") or [])))
                self.note_sale(ts, carto=ev.get("TotalEarnings") or 0, systems=len(ev.get("Discovered") or []))
                for d in ev.get("Discovered") or []:
                    self.db.execute("INSERT INTO sales VALUES (?, ?, ?)",
                                    (d.get("SystemName"), ts, d.get("NumBodies")))
            else:  # the pre-3.3 sale event: just a list of system names
                self.add_earnings(ts, ev.get("TotalEarnings") or 0)
                self.db.execute("INSERT OR IGNORE INTO sale_events VALUES (?, 'carto', ?, ?, ?, ?, 0, NULL)",
                                (ts, ev.get("BaseValue"), ev.get("Bonus"), ev.get("TotalEarnings"), len(ev.get("Systems") or [])))
                for sysname in ev.get("Systems") or []:
                    self.db.execute("INSERT INTO sales VALUES (?, ?, NULL)", (sysname, ts))
            self.sales_changed = True
            return
        id64, star_pos = ev.get("SystemAddress"), ev.get("StarPos")
        if id64 is None or not star_pos:
            return
        # A Location in the system you're already in (a relog) is not an arrival: not a visit, not movement.
        relog = ev.get("event") == "Location" and bool(self.pos) and self.pos["id64"] == id64
        x, y, z = star_pos
        if name == "FSDJump" and self.boost and ts >= self.boost["ts"]:
            self.boost = None                           # the charge is used by the jump
            meta_set(self.db, "boost", None)
        if name == "FSDJump" and ev.get("FuelUsed") and ev.get("JumpDist") and not ev.get("BoostUsed"):
            # boosted jumps (neutron cone, FSD injection) go further for the same fuel: not a pace sample
            self.fuel_hist = (self.fuel_hist + [[ev["JumpDist"], ev["FuelUsed"]]])[-FUEL_HISTORY:]
            meta_set(self.db, "fuel_hist", self.fuel_hist)
        if name == "CarrierJump" and self.carrier and ev.get("MarketID") == self.carrier.get("id"):
            self.carrier.update(system=ev.get("StarSystem"), id64=id64, x=x, y=y, z=z, ts=ts, planned=None,
                                services=ev.get("StationServices") or self.carrier.get("services"))
            meta_set(self.db, "carrier", self.carrier)
        self.db.execute(
            """INSERT INTO visits (id64, name, x, y, z, first_ts, last_ts, count)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(id64) DO UPDATE SET
                 count = count + ?,
                 first_ts = min(first_ts, excluded.first_ts),
                 last_ts = max(last_ts, excluded.last_ts)""",
            (id64, ev.get("StarSystem"), x, y, z, ts, ts, 0 if relog else 1))
        self.dirty.add(id64)
        if not relog:
            star = self.jump_class.pop(id64, None)
            if not star:
                row = self.db.execute("SELECT star_class FROM star_classes WHERE id64=?", (id64,)).fetchone()
                star = row["star_class"] if row else None
            self.db.execute("INSERT OR IGNORE INTO jumps VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (ts, id64, ev.get("StarSystem"), x, y, z, star, ev.get("event")))
        if self.target and self.target["id64"] == id64:
            self.target = None
        ns = meta_get(self.db, "next_stop")
        if ns and ns.get("id64") == id64 and not relog:   # arrived at the chosen next stop
            meta_set(self.db, "next_stop", None)
        if ts >= (self.pos or {}).get("ts", ""):
            if self.pos and self.pos["id64"] != id64:
                self.prev = self.pos
                meta_set(self.db, "prev", self.prev)
            self.pos = {"name": ev.get("StarSystem"), "id64": id64, "x": x, "y": y, "z": z, "ts": ts}
            meta_set(self.db, "pos", self.pos)
        if ev.get("event") == "FSDJump":
            self.jump_arrival = {"id64": id64, "name": ev.get("StarSystem"), "ts": ts}

    def note_sample_point(self, system, body, species, genus, kind, n, ts):
        """Remember where a sample was taken, from the live Status.json reading (at most a second old at
        walking pace). Only live play records positions: a journal read later has no position to pair with."""
        if kind == "Log":   # a new run: forget the old one's points
            self.db.execute("DELETE FROM sample_points WHERE system=? AND body_id=? AND species=?", (system, body, species))
        if kind == "Analyse":   # the run is complete: nothing left to space
            self.db.execute("DELETE FROM sample_points WHERE system=? AND body_id=? AND species=?", (system, body, species))
            return
        st = self.status_json or {}
        if not st.get("live") or st.get("lat") is None or st.get("lon") is None or not st.get("ts"):
            return
        try:
            if abs(ts_seconds(ts) - ts_seconds(st["ts"])) > 90:   # the reading is not from this moment
                return
        except ValueError:
            return
        self.db.execute("INSERT OR REPLACE INTO sample_points VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (system, body, species, genus, n, st["lat"], st["lon"], ts))

    def handle_phenomenon(self, name, ev, ts):
        """Notable stellar phenomena: found by the FSS, reached by dropping out of supercruise at one."""
        code = ev.get("SignalName") if name == "FSSSignalDiscovered" else ev.get("Type")
        m = re.match(r"^\$Fixed_Event_Life_(\w+?);?$", code or "")
        if not m:
            return
        kind = m.group(1).lower()
        if name == "FSSSignalDiscovered":
            system = ev.get("SystemAddress")
            if system is None:
                return
            self.db.execute("INSERT OR IGNORE INTO phenomena VALUES (?, ?, ?, NULL)", (system, kind, ts))
        elif self.pos:   # the drop happens in the system you are in
            system = self.pos["id64"]
            self.db.execute("INSERT INTO phenomena VALUES (?, ?, ?, ?) ON CONFLICT(system, kind) "
                            "DO UPDATE SET reached_ts = coalesce(reached_ts, excluded.reached_ts)", (system, kind, ts, ts))
        else:
            return
        self.dirty.add(system)

    def handle_cmdr(self, name, ev, ts):
        c = self.commander or {}
        if ts < c.get("login_ts", ""):
            return   # an older login read out of order (legacy folders are imported after the fact)
        if name in ("Rank", "Progress", "Promotion"):
            key = "progress" if name == "Progress" else "rank"
            c[key] = dict(c.get(key) or {}, **{k: v for k, v in ev.items() if k in RANK_KEYS})
            if name == "Promotion":     # a new rank starts at 0%
                c["progress"] = dict(c.get("progress") or {}, **{k: 0 for k in ev if k in RANK_KEYS})
        elif name == "Statistics":
            meta_set(self.db, "statistics", {"ts": ts, "Exploration": ev.get("Exploration") or {},
                                             "Exobiology": ev.get("Exobiology") or {}})
            return
        elif name == "Commander":
            c.update(name=ev.get("Name") or c.get("name"), fid=ev.get("FID") or c.get("fid"))
        else:  # LoadGame: the credit balance at login is the baseline; sales since are added to it
            self.moment("game_start", ts, cmdr=ev.get("Commander") or c.get("name") or "",
                        ship=ev.get("ShipName") or ev.get("Ship_Localised") or ev.get("Ship") or "",
                        mode=ev.get("GameMode") or "")
            c.update(name=ev.get("Commander") or c.get("name"), fid=ev.get("FID") or c.get("fid"),
                     credits=ev.get("Credits"), loan=ev.get("Loan"), login_ts=ts, earned=0,
                     mode=ev.get("GameMode"))
        self.commander = c
        self.cmdr_changed = True
        meta_set(self.db, "commander", c)

    def note_sale(self, ts, carto=0, bio=0, systems=0, species=0):
        """The latest sale, for the page's "what did I bank" line. Sales within ten minutes of each other
        (cartographics and exobiology at the same station) are one sale."""
        last = self.last_sale
        if last and ts_seconds(ts) - ts_seconds(last["ts"]) < 600:
            last = dict(last, ts=ts, carto=last["carto"] + carto, bio=last["bio"] + bio,
                        systems=last["systems"] + systems, species=last["species"] + species)
        else:
            last = {"ts": ts, "carto": carto, "bio": bio, "systems": systems, "species": species}
        self.last_sale = last
        meta_set(self.db, "last_sale", last)

    def add_earnings(self, ts, amount):
        c = self.commander
        if c and amount and ts >= c.get("login_ts", ""):
            c["earned"] = (c.get("earned") or 0) + int(amount)
            self.cmdr_changed = True
            meta_set(self.db, "commander", c)

    def handle_ship(self, name, ev, ts):
        if name == "HullDamage":
            # your own ship only: the same event reports fighters and SRVs, and repeats
            if ev.get("PlayerPilot") is False or ev.get("Fighter") or ev.get("Health") is None:
                return
            self.hull = {"pct": round(ev["Health"] * 100), "ts": ts}
            meta_set(self.db, "hull", self.hull)
            return
        if name in ("RepairAll", "Repair"):
            if name == "RepairAll" or str(ev.get("Item", "")).lower() in ("hull", "all", "wear"):
                self.hull = {"pct": 100, "ts": ts}
                meta_set(self.db, "hull", self.hull)
            return
        if name == "HeatDamage":
            self.moment("heat", ts)
            return
        if name == "NavRouteClear":
            meta_set(self.db, "route", None)
            return
        if name == "JetConeBoost":
            self.boost = {"value": ev.get("BoostValue") or 4.0, "ts": ts}   # the journal says how much (x4, x1.5...)
            meta_set(self.db, "boost", self.boost)
            return
        if name == "Interdicted":
            self.moment("interdicted", ts, by=ev.get("Interdictor_Localised") or ev.get("Interdictor") or "",
                        submitted=bool(ev.get("Submitted")), player=bool(ev.get("IsPlayer")))
            return
        if name in ("FuelScoop", "RefuelAll", "RefuelPartial"):
            self.last_scoop = ts
            meta_set(self.db, "last_scoop", ts)
            return
        if name == "Undocked":
            self.docked = None
            meta_set(self.db, "docked", None)
            return
        c = self.carrier or {}
        if name == "CarrierStats":
            if ev.get("CarrierType", "FleetCarrier") != "FleetCarrier":
                return
            c.update(id=ev.get("CarrierID"), name=ev.get("Name"), callsign=ev.get("Callsign"),
                     fuel=ev.get("FuelLevel"), jump_range=ev.get("JumpRangeCurr"), stats_ts=ts)
        elif name == "CarrierLocation":
            if ev.get("CarrierType", "FleetCarrier") != "FleetCarrier" or ev.get("CarrierID") != c.get("id"):
                return
            if ev.get("SystemAddress") != c.get("id64"):
                c.update(system=ev.get("StarSystem"), id64=ev.get("SystemAddress"), x=None, y=None, z=None)
            c.update(ts=ts, planned=None)
        elif name == "Docked":
            services = ev.get("StationServices") or []
            self.docked = {"station": ev.get("StationName"), "type": ev.get("StationType"),
                           "market_id": ev.get("MarketID"), "system": ev.get("StarSystem"), "ts": ts,
                           "has_uc": "exploration" in services, "has_vista": "vistagenomics" in services}
            meta_set(self.db, "docked", self.docked)
            if ev.get("StationType") != "FleetCarrier" or ev.get("MarketID") != c.get("id"):
                return
            moved = ev.get("SystemAddress") != c.get("id64")
            c.update(system=ev.get("StarSystem"), id64=ev.get("SystemAddress"), ts=ts, planned=None,
                     services=ev.get("StationServices") or c.get("services"))
            if moved:
                c.update(x=None, y=None, z=None)
        elif name == "CarrierJumpRequest":
            if ev.get("CarrierID") != c.get("id"):
                return
            c["planned"] = {"system": ev.get("SystemName"), "id64": ev.get("SystemAddress"),
                            "departure": ev.get("DepartureTime"), "ts": ts}
        elif name == "CarrierJumpCancelled":
            if ev.get("CarrierID") == c.get("id"):
                c["planned"] = None
        elif name == "CarrierJump":
            return  # handled with the position events (it carries StarPos)
        if c:
            self.carrier = c
            meta_set(self.db, "carrier", c)

    def handle_scan(self, name, ev, ts):
        system = ev.get("SystemAddress")
        if system is None:
            return
        if name == "ScanOrganic":
            body, species, kind = ev.get("Body"), ev.get("Species"), ev.get("ScanType")
            if body is None or not species or kind not in ("Log", "Sample", "Analyse"):
                return
            row = self.db.execute("SELECT samples, done_ts FROM own_organic WHERE system=? AND body_id=? AND species=?",
                                  (system, body, species)).fetchone()
            samples, done = (row["samples"], row["done_ts"]) if row else (0, None)
            if kind == "Log":            # first sample of a run (a new run if this species was already done)
                samples, done = 1, None
                # only one sample run exists at a time: starting this one abandons any other
                self.db.execute("DELETE FROM own_organic WHERE done_ts IS NULL AND NOT (system=? AND body_id=? AND species=?)",
                                (system, body, species))
            elif kind == "Sample":
                samples = min(3, samples + 1)
            else:                        # Analyse: the run is complete
                samples, done = 3, ts
            self.db.execute(
                """INSERT OR REPLACE INTO own_organic VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (system, body, species, ev.get("Genus_Localised"), ev.get("Species_Localised"),
                 ev.get("Variant_Localised"), samples, done, ts))
            self.note_sample_point(system, body, species, ev.get("Genus"), kind, samples, ts)
            self.dirty.add(system)
            return
        if name == "CodexEntry":
            self.db.execute(
                "INSERT OR IGNORE INTO codex VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, ev.get("EntryID"), ev.get("Name_Localised") or ev.get("Name"),
                 ev.get("Category_Localised"), ev.get("SubCategory_Localised"), ev.get("Region_Localised"),
                 system, ev.get("System"), ev.get("BodyID"), int(bool(ev.get("IsNewEntry"))),
                 ev.get("NewTraitsDiscovered") and json.dumps(ev["NewTraitsDiscovered"]),
                 ev.get("VoucherAmount")))
            if ev.get("IsNewEntry") or ev.get("VoucherAmount"):
                self.codex_new += 1
            self.dirty.add(system)
            return
        if name == "ScanBaryCentre":
            if ev.get("BodyID") is not None:
                rec = {k: ev.get(k) for k in ("SemiMajorAxis", "Eccentricity", "OrbitalInclination",
                                              "OrbitalPeriod", "Periapsis", "AscendingNode", "MeanAnomaly")}
                self.db.execute("INSERT OR REPLACE INTO own_barycentres VALUES (?, ?, ?, ?)",
                                (system, ev["BodyID"], json.dumps(rec), ts))
                self.dirty.add(system)
            return
        if name == "Scan":
            record = record_from_scan(ev)
            if record and record["main"] and "WasDiscovered" in ev:
                self.arrival_scan = {"id64": system, "was_discovered": bool(ev["WasDiscovered"]), "ts": ts}
            if record and ev.get("BodyID") is not None:
                self.db.execute("INSERT OR REPLACE INTO own_bodies (system, body_id, name, record, ts, raw) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (system, ev["BodyID"], ev["BodyName"], json.dumps(record), ts, json.dumps(ev)))
                flag = lambda k: None if k not in ev else int(bool(ev[k]))
                undisc = ts if ev.get("WasDiscovered") is False else None
                if record["type"] == "Planet":
                    self.moment("scan", ts, system=system, body_id=ev["BodyID"])
                self.db.execute(
                    """INSERT INTO own_firsts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(system, body_id) DO UPDATE SET
                         undisc_ts = coalesce(excluded.undisc_ts, undisc_ts)""",
                    (system, ev["BodyID"], ev["BodyName"], int(record["main"]),
                     flag("WasDiscovered"), flag("WasMapped"), flag("WasFootfalled"), ts, undisc))
        elif name == "SAAScanComplete":
            if (ev.get("BodyName") or "").endswith(" Ring"):
                # A ring with no hotspots never gets an SAASignalsFound: this is the only record of the probe.
                self.db.execute("INSERT OR IGNORE INTO own_ring_signals VALUES (?, ?, '{}', ?)",
                                (system, ev["BodyName"], ts))
            elif ev.get("BodyID") is not None:
                self.db.execute("INSERT INTO own_mapped VALUES (?, ?, ?) ON CONFLICT(system, body_id) "
                                "DO UPDATE SET ts = excluded.ts", (system, ev["BodyID"], ts))
        elif name == "Disembark":
            if not ev.get("OnPlanet") or ev.get("BodyID") is None:
                return
            self.db.execute("INSERT OR IGNORE INTO own_footfall VALUES (?, ?, ?)", (system, ev["BodyID"], ts))
        elif name == "FSSDiscoveryScan":
            self.last_honk = {"id64": system, "ts": ts, "bodies": ev.get("BodyCount"), "progress": ev.get("Progress")}
            self.db.execute(
                """INSERT INTO own_systems (id64, name, body_count, all_found) VALUES (?, ?, ?, 0)
                   ON CONFLICT(id64) DO UPDATE SET body_count = excluded.body_count""",
                (system, ev.get("SystemName"), ev.get("BodyCount")))
        elif name == "FSSAllBodiesFound":
            self.last_all_found = {"id64": system, "ts": ts}
            self.db.execute(
                """INSERT INTO own_systems (id64, name, body_count, all_found) VALUES (?, ?, ?, 1)
                   ON CONFLICT(id64) DO UPDATE SET all_found = 1,
                     body_count = coalesce(body_count, excluded.body_count)""",
                (system, ev.get("SystemName"), ev.get("Count")))
        else:  # SAASignalsFound / FSSBodySignals
            body = ev.get("BodyName") or ""
            signals = {s.get("Type"): s.get("Count", 0) for s in ev.get("Signals") or []}
            if body.endswith(" Ring"):
                self.db.execute("INSERT OR REPLACE INTO own_ring_signals VALUES (?, ?, ?, ?)",
                                (system, body, json.dumps(minerals(signals)), ts))
            else:
                self.db.execute("INSERT OR REPLACE INTO own_signals VALUES (?, ?, ?, ?, ?)",
                                (system, body, signals.get(BIO, 0), signals.get(GEO, 0), ts))
                if name == "FSSBodySignals" and (signals.get(BIO) or signals.get(GEO)):   # the FSS just found them
                    self.moment("signals", ts, system=system, body_name=body, bio=signals.get(BIO, 0), geo=signals.get(GEO, 0))
                if signals.get(BIO) and ev.get("BodyID") is not None and name == "FSSBodySignals":
                    self.moment("bio", ts, system=system, body_id=ev["BodyID"], signals=signals[BIO])
                for g in ev.get("Genuses") or []:
                    if g.get("Genus") and ev.get("BodyID") is not None:
                        self.db.execute("INSERT OR IGNORE INTO own_genera VALUES (?, ?, ?, ?, ?)",
                                        (system, ev["BodyID"], g["Genus"], g.get("Genus_Localised"), ts))
        self.dirty.add(system)

    def read_status(self, d):
        """Status.json: the live fuel gauge (rewritten by the game every few seconds)."""
        try:
            with open(os.path.join(d, "Status.json"), encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError):
            return
        fuel = st.get("Fuel") or {}
        if "FuelMain" in fuel or st.get("Flags2") is not None:   # on foot there is no Fuel block, but the game is live
            prev = self.status_json or {}
            self.status_json = {"fuel_main": fuel.get("FuelMain", prev.get("fuel_main")),
                                "fuel_reservoir": fuel.get("FuelReservoir", prev.get("fuel_reservoir")),
                                "ts": st.get("timestamp"), "flags": st.get("Flags"), "flags2": st.get("Flags2"),
                                # where you are on a body (the on-body strip, sample spacing) and the target
                                "body": st.get("BodyName"), "lat": st.get("Latitude"), "lon": st.get("Longitude"),
                                "alt": st.get("Altitude"), "planet_radius": st.get("PlanetRadius"),
                                "destination": st.get("Destination"), "live": True}
        elif self.status_json:  # game closed or at the menu: keep the last reading, mark it stale
            self.status_json = dict(self.status_json, live=False)
        else:
            self.status_json = {"live": False, "ts": st.get("timestamp")}

    def read_navroute(self, d):
        path = os.path.join(d, "NavRoute.json")
        try:
            with open(path, encoding="utf-8") as f:
                route = json.load(f)
        except (OSError, ValueError):
            return
        hops = [{"id64": h["SystemAddress"], "name": h.get("StarSystem"), "star_class": h.get("StarClass"),
                 "x": h["StarPos"][0], "y": h["StarPos"][1], "z": h["StarPos"][2]}
                for h in route.get("Route") or [] if h.get("StarPos") and h.get("SystemAddress") and len(h["StarPos"]) == 3]
        # the plotted route in order (the route strip); an empty file means the route was cleared
        meta_set(self.db, "route", {"ts": route.get("timestamp"), "hops": hops} if hops else None)
        for hop in route.get("Route") or []:
            if not (hop.get("StarPos") and hop.get("SystemAddress") and len(hop["StarPos"]) == 3):
                continue
            x, y, z = hop["StarPos"]
            self.db.execute(
                "INSERT OR REPLACE INTO route_systems VALUES (?, ?, ?, ?, ?, ?, ?)",
                (hop["SystemAddress"], hop["StarSystem"], x, y, z,
                 hop.get("StarClass"), route.get("timestamp")))
            if hop.get("StarClass"):
                self.db.execute("INSERT OR REPLACE INTO star_classes VALUES (?, ?)",
                                (hop["SystemAddress"], hop["StarClass"]))


def codex_species(db, region):
    """Species with a codex entry of yours in `region`. Codex bio entries are per colour variant
    ("Bacterium Aurasus - Teal"); a species counts as known once any of its variants is logged there."""
    if not region:
        return set()
    return {(r[0] or "").split(" - ")[0].strip().lower()
            for r in db.execute("SELECT name FROM codex WHERE region = ?", (region,))}


def organic_state(db, done_ts):
    """Was a completed sample banked? sold if a Vista Genomics sale followed it before any death,
    lost if a death came first, else aboard."""
    if not done_ts:
        return None
    sale = db.execute("SELECT min(ts) FROM bio_sales WHERE ts > ?", (done_ts,)).fetchone()[0]
    death = db.execute("SELECT min(ts) FROM deaths WHERE ts > ?", (done_ts,)).fetchone()[0]
    if sale and (not death or sale < death):
        return "sold"
    return "lost" if death else "aboard"


def pickup_judge(db, system):
    """A function pickup_ts -> (state, ts): sold / lost / unsold, for cartographic data from `system`."""
    sales = [r[0] for r in db.execute("SELECT ts FROM sales WHERE name = ? ORDER BY ts", (system,))]
    losses = [r[0] for r in db.execute(f"SELECT ts FROM deaths WHERE {SHIP_LOSS_SQL} ORDER BY ts")]

    def state(pickup):
        if not pickup:
            return "unsold", None
        sale = next((t for t in sales if t > pickup), None)
        loss = next((t for t in losses if t > pickup), None)
        if sale and (not loss or sale < loss):
            return "sold", sale
        if loss:
            return "lost", loss
        return "unsold", None
    return state


def own_firsts(db, id64, system):
    """What you were first to: discovery, mapping, footfall -- and whether the data was sold.

    Discovery and mapping only count once sold to Universal Cartographics, and unsold data is
    lost if you die; footfall is credited on the spot.
    """
    rows = db.execute(
        """SELECT f.*, m.ts AS mapped_ts, ff.ts AS foot_ts FROM own_firsts f
           LEFT JOIN own_mapped m ON m.system = f.system AND m.body_id = f.body_id
           LEFT JOIN own_footfall ff ON ff.system = f.system AND ff.body_id = f.body_id
           WHERE f.system = ?""", (id64,)).fetchall()
    disc = [r for r in rows if r["was_discovered"] == 0]
    mapped = [r for r in rows if r["was_mapped"] == 0 and r["mapped_ts"]]
    foot = [r for r in rows if r["was_footfalled"] == 0 and r["foot_ts"]]
    if not (disc or mapped or foot):
        return None

    # Each body is judged on its own pickup time: the data must reach a cartographer after
    # that, and a lost ship in between loses it (a rescan picks it up again, and undisc_ts
    # advances with every unsold rescan).
    state = pickup_judge(db, system)

    disc_states = [state(r["undisc_ts"] or r["first_ts"]) for r in disc]
    map_states = [state(r["mapped_ts"]) for r in mapped]
    arrival = next((st for r, st in zip(disc, disc_states) if r["is_main"]), None)
    counts = lambda states: {k: sum(1 for st, _ in states if st == k) for k in ("sold", "unsold", "lost")}
    out = {"system": arrival is not None, "system_state": arrival[0] if arrival else None,
           "system_ts": arrival[1] if arrival else None,
           "bodies": len(disc), "bodies_by": counts(disc_states),
           "mapped": len(mapped), "mapped_by": counts(map_states),
           "footfall": len(foot)}
    # One headline state for the marker: unsold needs your attention, lost is bad news,
    # sold is settled. Footfall alone has no sale to wait for.
    all_states = [st for st, _ in disc_states + map_states]
    out["sale"] = ("unsold" if "unsold" in all_states else "lost" if "lost" in all_states
                   else "sold" if all_states else None)
    if out["sale"] == "sold":
        out["sold_ts"] = max(t for st, t in disc_states + map_states if st == "sold")
    elif out["sale"] == "lost":
        out["lost_ts"] = max(t for st, t in disc_states + map_states if st == "lost")
    return out


# --------------------------------------------------------------------------
# Summaries: what the page shows for a system, computed from merged records
# --------------------------------------------------------------------------

def dist(a, b):
    return math.sqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2)


def star_short(subtype):
    """'K (Yellow-Orange giant) Star' -> 'K', 'White Dwarf (DA) Star' -> 'DA', etc."""
    if not subtype:
        return None
    m = re.match(r"^([OBAFGKMLTY]) \(", subtype)
    if m:
        return m.group(1)
    m = re.match(r"^White Dwarf \((\w+)\)", subtype)
    if m:
        return m.group(1)
    fixed = {"Neutron Star": "N", "Black Hole": "BH", "Supermassive Black Hole": "SMBH",
             "T Tauri Star": "TTS", "Herbig Ae/Be Star": "AeBe", "MS-type Star": "MS",
             "S-type Star": "S", "C Star": "C", "CN Star": "CN", "CJ Star": "CJ"}
    if subtype in fixed:
        return fixed[subtype]
    if subtype.startswith("Wolf-Rayet"):
        return "W"
    return subtype.split()[0]


def subtype_scoopable(subtype):
    return bool(subtype) and re.match(r"^[OBAFGKM] \(", subtype) is not None


def class_scoopable(star_class):
    """NavRoute StarClass codes: 'K', 'M_RedGiant', 'DA', 'TTS', ..."""
    return bool(star_class) and star_class.split("_")[0] in SCOOPABLE


def natural(s):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def tally(items):
    out = {}
    for i in items:
        if i:
            out[i] = out.get(i, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def ring_stats(rings):
    """Rings with width and surface density (megatonnes per km^2), for miners' eyes."""
    out = []
    for x in rings or []:
        d = dict(x)
        inner, outer, mass = x.get("inner"), x.get("outer"), x.get("mass")
        if inner is not None and outer is not None:
            d["width_km"] = round((outer - inner) / 1000)
            area_km2 = math.pi * (outer ** 2 - inner ** 2) / 1e6
            d["density"] = round(mass / area_km2, 5) if mass and area_km2 > 0 else None
            d["inner_km"], d["outer_km"] = round(inner / 1000), round(outer / 1000)
        out.append(d)
    return out


def curiosities(r, parent=None, raw=None, binary=False):
    """Observatory-style "interesting body" flags: [(tag, why)]. `parent` is the record this body orbits
    (if a body), `raw` your own Scan event (rotation, tidal lock), `binary` true when it circles a shared
    centre with another planet. Only facts that are known are tested: nothing is flagged on a guess."""
    out = []
    planet = r.get("type") == "Planet"
    g, landable = r.get("gravity"), r.get("landable")
    # a page row keeps its rings under ring_details (rings is a count there); a stored record has the list
    rings = r["ring_details"] if isinstance(r.get("ring_details"), list) else r["rings"] if isinstance(r.get("rings"), list) else []
    if planet and landable and rings:
        out.append(("ringed landable", "a landable body with rings: the view from the surface"))
    if planet and landable and g and g > 3:
        out.append(("high g", f"{g:.1f} g and landable"))
    raw = raw or {}
    rot = raw.get("RotationPeriod")
    if planet and rot and abs(rot) < 7200 and not raw.get("TidalLock"):
        out.append(("fast spin", f"a day of {abs(rot) / 60:.0f} minutes"))
    if planet and landable and raw.get("TidalLock") and r.get("atmosphere") and r.get("atmosphere") != "None":
        out.append(("locked, with air", "tidally locked, landable and with an atmosphere"))
    sma_km = (r.get("sma_ls") or 0) * LIGHT_SPEED / 1000
    if parent and sma_km and parent.get("radius_km") and sma_km < 3 * parent["radius_km"]:
        out.append(("close orbit", f"orbits {sma_km / parent['radius_km']:.1f} radii from {parent['name']}"))
    rk = r.get("radius_km")
    for x in ring_stats(rings):
        if rk and x.get("width_km") and x["width_km"] > 5 * rk:
            out.append(("wide rings", f"{x['name']}: {x['width_km']:,} km wide, {x['width_km'] / rk:.0f}x the body's radius"))
            break
    if planet and "gas giant" in (r.get("subtype") or "").lower() and parent and parent.get("type") == "Star" \
            and r.get("sma_ls") and r["sma_ls"] < 50:
        out.append(("hot Jupiter", f"a gas giant {r['sma_ls']:.0f} ls from its star"))
    pf = [p for p in r.get("parents_full") or [] if p["kind"] != "Ring"]
    if planet and len(pf) >= 2 and pf[0]["kind"] == "Planet" and pf[1]["kind"] == "Planet":
        out.append(("moon of a moon", "a moon orbiting a moon"))
    if planet and binary:
        out.append(("planet pair", "circles a shared centre with another planet"))
    return out


def system_curiosities(system, records, raws=None):
    """{short body name: [(tag, why)]} for a system, the same for Here and Nearby. A body's parent is the
    body it directly orbits (never through a barycentre: an orbit around a shared centre is measured from
    that centre, so comparing it with a star's radius would be meaningless); planets that share a
    barycentre with only other planets are a planet pair."""
    raws = raws or {}
    by_id = {x.get("body_id"): x for x in records if x.get("body_id") is not None}
    first = lambda x: next((q for q in x.get("parents_full") or [] if q["kind"] != "Ring"), None)
    centres = {}
    for x in records:
        f = first(x)
        if f and f["kind"] == "Null":
            centres.setdefault(f["id"], []).append(x.get("type"))
    out = {}
    for x in records:
        f = first(x)
        parent = by_id.get(f["id"]) if f and f["kind"] in ("Star", "Planet") else None
        members = centres.get(f["id"], []) if f and f["kind"] == "Null" else []
        binary = len(members) >= 2 and all(t == "Planet" for t in members)
        c = curiosities(x, parent, raws.get(x["name"]), binary)
        if c:
            out[x["name"]] = c
    return out


def bio_context(name, records, x=None, y=None, z=None, star=None):
    """What the exobiology rules want to know about a system as a whole: where it is (region,
    nebulae), its stars, and which planet classes it holds. `star` is the arrival star class
    from the journal, used when no star has been scanned yet."""
    stars, planet_types, star_types = [], [], {}
    for r in records:
        if r.get("type") == "Star":
            stars.append({"type": r.get("subtype"), "luminosity": r.get("luminosity"), "main": r.get("main")})
            if r.get("body_id") is not None:
                star_types[r["body_id"]] = r.get("subtype")
        elif r.get("type") == "Planet":
            planet_types.append(r.get("subtype"))
    if not any(s.get("main") for s in stars) and star:
        stars.append({"type": star, "luminosity": None, "main": True})
    return {"name": name, "x": x, "y": y, "z": z, "stars": stars, "planet_types": planet_types,
            "star_types": star_types}


def surface_materials(m):
    """A body's surface materials as lower-case names, from a journal list ([{Name, Percent}]), a Spansh
    dump dict ({Iron: 20.1}) or a search list ([{name, share}]); None when not known."""
    if isinstance(m, dict):
        return sorted(str(k).lower() for k in m)
    if isinstance(m, list) and m:
        return sorted(str(x.get("Name") or x.get("name") or "").lower() for x in m if isinstance(x, dict)) or None
    return None


def _bio_body(r, star, ctx):
    star_types = (ctx or {}).get("star_types") or {}
    parents = r.get("parent_star_types") or [star_types[p] for p in r.get("parents") or [] if p in star_types]
    body = {"class": r.get("subtype"), "atmosphere": r.get("atmosphere"), "gravity": r.get("gravity"),
            "temperature": r.get("temperature"), "volcanism": r.get("volcanism"), "dist_ls": r.get("dist_ls"),
            "pressure": r.get("pressure"), "orbital_period_s": r.get("orbital_period_s"),
            "atmosphere_composition": r.get("atmo_comp"), "parents": parents or None, "star": star,
            "materials": r.get("materials")}
    return body


def bio_guess(r, star=None, genera=None, ctx=None):
    """What a body's bio signals could be: (upper-bound credits, genus groups) or (None, [])."""
    if not ed_bio or r.get("type") != "Planet":
        return None, []
    cands = ed_bio.predict(_bio_body(r, star, ctx), ctx)
    if not cands and not genera:
        return None, []
    val, groups = ed_bio.potential(cands, signals=r.get("bio") or None, genera=genera)
    return (val if any(g.get("value") for g in groups) else None), groups


def bio_options(r, star=None, ctx=None):
    """Before the DSS, when a body has fewer signals than genera the rules allow, which genus it is cannot
    be told: {low, high, genera} -- every possible genus (most valuable first) and the range the signals
    could pay, from the cheapest to the most valuable. None when the signals already cover the choices."""
    n = r.get("bio") or 0
    if not ed_bio or r.get("type") != "Planet" or not n:
        return None
    groups = ed_bio.by_genus(ed_bio.predict(_bio_body(r, star, ctx), ctx))
    if len(groups) <= n:
        return None
    lows = sorted(g.get("min_value") or 0 for g in groups)
    return {"low": sum(lows[:n]), "high": sum(g.get("value") or 0 for g in groups[:n]),
            "genera": [{"genus": g["genus"], "best": g["best"], "value": g["value"],
                        "species": [ed_bio.short_species(x["name"], g["genus"]) for x in g["species"]]} for g in groups]}


def summarise(records, body_count, star=None, ctx=None):
    stars = [r for r in records if r["type"] == "Star"]
    planets = [r for r in records if r["type"] == "Planet"]
    main = next((r for r in stars if r.get("main")), stars[0] if len(stars) == 1 else None)
    full = all(r.get("full") for r in records)
    s = {
        "body_count": body_count,
        "bodies_known": len(stars) + len(planets),
        "stars": len(stars),
        "scoopable_stars": sum(bool(r.get("scoopable")) for r in stars),
        "main_star": main["subtype"] if main else None,
        "main_scoopable": bool(main.get("scoopable")) if main else None,
        "planets": len(planets),
        "star_types": tally(r["subtype"] for r in stars),
        "planet_types": tally(r["subtype"] for r in planets),
        "terraformable": sum(bool(r.get("terraformable")) for r in planets),
        "notable": tally([NOTABLE_PLANETS[r["subtype"]] for r in planets if r["subtype"] in NOTABLE_PLANETS] +
                         ["T" for r in planets if r.get("terraformable")]),
        # Spansh's estimate of scanning and mapping everything known here (None if unknown)
        "est_value": sum(r["value"] for r in records if r.get("value")) or None,
        # exobiology: an upper bound on what the bio-signal bodies could pay, from spawn rules
        "bio_potential": None, "bio_bodies_guessed": 0,
        "ringed": None, "detail": None,
    }
    pot, n = 0, 0
    for r in records:
        if r.get("bio"):
            val, groups = bio_guess(r, star, r.get("genera") or None, ctx)
            if val:
                pot += val
                n += 1
    if n:
        s["bio_potential"], s["bio_bodies_guessed"] = pot, n
    if not full:
        return s  # rings, belts and signals arrive with the Spansh dump
    ringed = [r for r in planets if r.get("rings")]
    all_rings = [(r, x) for r in records for x in r.get("rings") or []]
    ring_types = tally(x["type"] for _, x in all_rings)
    s["ringed"] = len(ringed)
    s["detail"] = {
        "rings": ring_types,
        # Ring type -> the bodies (planets or stars) carrying a ring of that type.
        "ring_bodies": {t: sorted({r["name"] for r, x in all_rings if x["type"] == t}, key=natural)
                        for t in ring_types},
        "ringed_types": tally(r["subtype"] for r in ringed),
        "ringed_stars": sum(1 for r in stars if r.get("rings")),
        "belts": tally(t for r in records for t in r.get("belts") or []),
        "landable": sum(1 for r in planets if r.get("landable")),
        "bio": sum(r.get("bio") or 0 for r in records),
        "bio_bodies": sum(1 for r in records if r.get("bio")),
        "geo": sum(r.get("geo") or 0 for r in records),
        "geo_bodies": sum(1 for r in records if r.get("geo")),
        "hotspots": [{"ring": f"{r['name']} {x['name']}", "type": x["type"], "minerals":
                      dict(sorted(minerals(x["hotspots"]).items(), key=lambda kv: (-kv[1], kv[0])))}
                     for r, x in all_rings if x.get("hotspots")],
        "rings_mapped": sum(1 for _, x in all_rings if x.get("hotspots") or x.get("mapped")),
        "ring_count": len(all_rings),
    }
    return s


# --------------------------------------------------------------------------
# Spansh
# --------------------------------------------------------------------------

# Bump when the cached record layout changes so cached systems get re-fetched.
CACHE_VERSION = 12


class Spansh:
    def __init__(self, db):
        self.db = db
        self.session = None
        self.sem = asyncio.Semaphore(SPANSH_CONCURRENCY)
        self.sem_fast = asyncio.Semaphore(SPANSH_INTERACTIVE)
        self.sem_search = asyncio.Semaphore(SPANSH_INTERACTIVE)   # online Search: never queues behind a refresh

    async def start(self):
        self.session = ClientSession(timeout=ClientTimeout(total=60),
                                     headers={"User-Agent": USER_AGENT})

    async def close(self):
        await self.session.close()

    async def sphere(self, pos, radius, max_pages=SPANSH_MAX_PAGES):
        """Every system Spansh knows within radius of pos (search-level detail), nearest first."""
        results, page = [], 0
        while page < max_pages:
            body = {
                "filters": {"distance": {"min": "0", "max": str(radius + 0.5)}},
                "reference_coords": {"x": pos["x"], "y": pos["y"], "z": pos["z"]},
                "sort": [{"distance": {"direction": "asc"}}],
                "size": SPANSH_PAGE, "page": page,
            }
            async with self.session.post(SPANSH_SEARCH, json=body) as r:
                r.raise_for_status()
                d = await r.json()
            results += d.get("results") or []
            if len(results) >= d.get("count", 0) or not d.get("results"):
                break
            page += 1
        return results

    async def body_search(self, filters, pos, radius, max_pages):
        """Bodies matching filters within radius, nearest first.

        Returns (bodies, cut): cut is None if every match was fetched, otherwise the distance
        of the last body fetched -- results are only complete out to there.
        """
        results, page = [], 0
        while page < max_pages:
            body = {
                "filters": dict(filters, distance={"min": "0", "max": str(radius)}),
                "reference_coords": {"x": pos["x"], "y": pos["y"], "z": pos["z"]},
                "sort": [{"distance": {"direction": "asc"}}],
                "size": SPANSH_PAGE, "page": page,
            }
            async with self.sem_search:
                async with self.session.post(SPANSH_BODY_SEARCH, json=body) as r:
                    r.raise_for_status()
                    d = await r.json()
            batch = d.get("results") or []
            results += batch
            if len(results) >= d.get("count", 0) or not batch:
                return results, None
            page += 1
        return results, results[-1]["distance"]

    def fetched_age(self, id64):
        """Seconds since a system's cached record was fetched, or None if it is not cached."""
        row = self.db.execute("SELECT fetched_ts FROM spansh_systems WHERE id64=?", (id64,)).fetchone()
        return time.time() - row["fetched_ts"] if row and row["fetched_ts"] else None

    async def stations(self, service, pos, size=20):
        """The stations nearest `pos` offering `service` (e.g. "Universal Cartographics"), nearest first."""
        body = {"filters": {"services": {"value": [service]}, "distance": {"min": "0", "max": "20000"}},
                "reference_coords": {"x": pos["x"], "y": pos["y"], "z": pos["z"]},
                "sort": [{"distance": {"direction": "asc"}}], "size": size, "page": 0}
        async with self.sem_fast:
            async with self.session.post(SPANSH_STATION_SEARCH, json=body) as r:
                r.raise_for_status()
                d = await r.json()
        return [{"name": x.get("name"), "system": x.get("system_name"), "id64": str(x.get("system_id64")),
                 "distance": round(x.get("distance") or 0, 1), "type": x.get("type"), "updated_at": x.get("updated_at"),
                 "ls": round(x.get("distance_to_arrival") or 0), "large_pad": bool(x.get("has_large_pad")),
                 "x": x.get("system_x"), "y": x.get("system_y"), "z": x.get("system_z")}
                for x in d.get("results") or []]

    def cached(self, id64):
        row = self.db.execute("SELECT * FROM spansh_systems WHERE id64=?", (id64,)).fetchone()
        if not row:
            return None, None
        base = json.loads(row["summary"])
        return (row["updated_at"], base) if base.get("v") == CACHE_VERSION else (None, None)

    def store(self, id64, updated_at, base):
        self.db.execute("INSERT OR REPLACE INTO spansh_systems (id64, updated_at, summary, fetched_ts, x, y, z)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (id64, updated_at, json.dumps(base), time.time(), base["x"], base["y"], base["z"]))
        self.db.commit()

    async def lookup(self, id64, interactive=True):
        """The full Spansh record for one system, or None if Spansh has never heard of it."""
        async with (self.sem_fast if interactive else self.sem):
            async with self.session.get(SPANSH_DUMP.format(id64=id64)) as r:
                if r.status == 404:
                    return None
                r.raise_for_status()
                return await r.json()

    async def edsm_system(self, name):
        """EDSM's record for a system by name, or None if EDSM doesn't know it either."""
        params = {"systemName": name, "showId": 1, "showCoordinates": 1, "showPrimaryStar": 1}
        async with self.sem_fast:
            async with self.session.get(EDSM_SYSTEM, params=params) as r:
                r.raise_for_status()
                d = await r.json()
        return d if isinstance(d, dict) and d.get("name") else None

    async def edsm_sphere(self, pos, radius):
        params = {"x": pos["x"], "y": pos["y"], "z": pos["z"], "radius": radius,
                  "showId": 1, "showCoordinates": 1, "showPrimaryStar": 1}
        async with self.sem:
            async with self.session.get(EDSM_SPHERE, params=params) as r:
                r.raise_for_status()
                d = await r.json()
        return d if isinstance(d, list) else []

    async def full_records(self, id64, updated_at, base, interactive=False):
        """Fetch a system's dump and cache its body records. `interactive` uses the fast lane: something
        on the page is waiting for this one (the bulk lane is for a refresh's many fetches)."""
        dump = await self.lookup(id64, interactive=interactive)
        if dump is None:  # search knew bodies but the dump 404s: keep what we have, don't cache
            return base
        system = dump.get("system") or {}
        values = {r["name"]: r for r in base.get("records") or []}  # search-level credit estimates
        records = []
        for b in system.get("bodies") or []:
            if b.get("type") not in ("Star", "Planet"):
                continue
            r = record_from_dump(base["name"], b)
            v = values.get(r["name"]) or {}
            r.update(value=v.get("value"), scan_value=v.get("scan_value"))
            records.append(r)
        base = dict(base, records=records)
        self.store(id64, updated_at, base)
        return base


def base_from_edsm(d):
    """An EDSM sphere/system record as a base: coordinates plus the primary star if given."""
    c, ps = d.get("coords") or {}, d.get("primaryStar") or {}
    records = []
    if ps.get("type"):
        records.append({"name": d["name"], "type": "Star", "subtype": ps["type"], "main": True,
                        "scoopable": bool(ps.get("isScoopable")), "terraformable": False, "full": False})
    return {"v": CACHE_VERSION, "name": d["name"], "x": c.get("x"), "y": c.get("y"), "z": c.get("z"),
            "body_count": None, "records": records}


def base_from_search(s):
    """What we keep per Spansh system: position, FSS count and (maybe partial) body records."""
    return {"v": CACHE_VERSION, "name": s["name"], "x": s["x"], "y": s["y"], "z": s["z"],
            "body_count": s.get("body_count"),
            "records": [record_from_search(s["name"], b) for b in s.get("bodies") or []
                        if b.get("type") in ("Star", "Planet")]}


# --------------------------------------------------------------------------
# App state: the list the page shows, rebuilt on every arrival
# --------------------------------------------------------------------------

class State:
    def __init__(self, db, journals, spansh, radius):
        self.db, self.journals, self.spansh, self.radius = db, journals, spansh, radius
        self.version = 0
        self.changed = asyncio.Event()   # set (and replaced) by bump(): long-polling pages wait on it
        self.bases = {}            # id64 -> (source, base) for systems in the current sphere
        self.systems = {}          # id64 -> row dict for the page
        self.visited = set()
        self.status = "starting"
        self.center = None
        self.refresh_task = None
        self.target = None         # classified FSD target for the page
        self.target_key = None
        self.target_seq = 0
        self.target_task = None
        self.searcher = None       # set once the Searcher exists
        self.speaker = None        # ed_tts.Speaker, set at start (None in tests)
        self.speech = None         # ed_speech.SpeechLines, set at start (None in tests)
        self.honker = None         # ed_honk.Honker, set at start (None in tests)
        self.autohonk = dict(AUTOHONK)
        self._honk_arrival = None  # the arrival the auto honk last looked at
        self.honk_confirm = 10.0   # s to wait for the journal's discovery scan after the press
        self.db_path = None        # for backups (a second connection reads it on a worker thread)
        self.backup_task = None
        self.seller_task = None
        self.seller_retry_at = None
        self._sampling_key = None
        self.unsold = None         # compute_unsold() result
        self.unsold_dirty = ed_unsold is not None
        self.unsold_at = 0.0
        self.unsold_task = None
        self.map_cache = {}        # (id64, radius) -> Spansh systems, so reopening the map is instant
        self.dump_cache = {}       # id64 -> (time, Spansh dump) for the body detail panel
        self.carrier_task = None
        self.retry_at = None       # when to ask Spansh again after a failed refresh
        self.retry_backoff = 30
        self.failed_dumps = set()  # systems whose body details failed last time
        self.sphere_cut = None     # ly: Nearby is complete only to here (Spansh had more than we fetch)
        self.dump_updated = {}     # id64 -> Spansh updated_at from the sphere search (for retries)
        self.dump_tries = {}       # id64 -> failed body-detail fetches this stay
        self.last_target = None    # the target we announced, kept after arrival clears it
        self.target_verdicts = {}  # id64 -> status for recent targets: a route re-targets on arrival
        self.arrival = None        # reconciliation of that announcement with the arrival scan
        self.arrival_seq = 0
        self.tail_error = None     # last journal-tailing exception, shown on the page
        self.materials_version = 0  # bumps when the materials inventory changes (Materials view keys on it)
        self.scan_version = 0      # bumps only when your own scan data changes (Here/History views key on it)
        self.system_values = {}    # system name -> unsold cartographic value, from the last estimate
        t = journals.target        # whatever was targeted before we started: no sound for it
        self.startup_target_key = t and (t["id64"], t["ts"])

    def bump(self):
        self.version += 1
        changed, self.changed = self.changed, asyncio.Event()
        changed.set()      # wakes every page request waiting in /api/nearby

    def payload(self):
        pos, jr = self.journals.pos, self.journals.jump_range
        return {
            "version": self.version, "run_id": RUN_ID, "status": self.status, "radius": self.radius,
            "radius_choices": sorted({float(x) for x in RADIUS_CHOICES} | {self.radius}),
            "sphere_cut": self.sphere_cut,
            "tts": self.speaker.info() if self.speaker else None,
            "speech": self.speech.info() if self.speech else None,
            "autohonk": self.autohonk_info(),
            "region": self.region_info(),
            "boost": (self.journals.boost or {}).get("value"),
            "on_body": self.on_body(),
            "sampling": self.sampling_summary(),
            "since_sale": self.since_sale(),
            "sellers": self.sellers_summary(),
            "next_stop": self.next_stop_summary(),
            "route": self.route_summary(),
            "backup": dict(meta_get(self.db, "last_backup") or {}, running=bool(self.backup_task and not self.backup_task.done())),
            "destination": self.destination(),
            "moments": self.moments_summary(),
            "hull": self.journals.hull,
            "last_sale": self.journals.last_sale,
            "position": dict(pos, visits=self.visit_count(pos["id64"])) if pos else pos,
            "previous": self.journals.prev,
            "commander": self.commander_summary(),
            "materials": self.materials_summary(), "jump_range": jr["ly"] if jr else None,
            "systems": list(self.systems.values()),
            "target": dict(self.target, leaving=self.leaving_summary(pos["id64"])) if self.target and pos else self.target,
            "arrival": self.arrival,
            "scan_version": self.scan_version,
            "freshness": {"journal": self.journals.last_event_ts, "status": (self.journals.status_json or {}).get("ts"),
                          "live": bool((self.journals.status_json or {}).get("live")),
                          "dirs": LIVE_DIRS, "legacy": LEGACY_DIRS},
            "docked": self.docked_summary(),
            "defaults": {"unsold_warn": UNSOLD_WARN, "unsold_urgent": UNSOLD_URGENT, "bio_min": BIO_MIN, "sounds": SOUNDS_DEFAULT,
                         "body_highlight": BODY_HIGHLIGHT, "bio_highlight": BIO_HIGHLIGHT,
                         "max_include_bonus": MAX_INCLUDE_BONUS,
                         "speech_styles": list(SPEECH_STYLES), "speech_profanity": SPEECH_PROFANITY,
                         "speech_profanity_pct": SPEECH_PROFANITY_PCT,
                         "speech_names": SPEECH_NAMES, "speech_speed": SPEECH_SPEED,
                         "speak_bio_signals": SPEAK_BIO_SIGNALS, "speak_geo_signals": SPEAK_GEO_SIGNALS},
            "bio_rules": ed_bio.rules_info() if ed_bio else None,
            "fuel": self.fuel_summary(),
            "ship": self.journals.ship,
            "carrier": self.carrier_summary(),
            "here_star": self.here_star(),
            "codex_recent": self.codex_recent(),
            "tail_error": self.tail_error,
            "bookmarks": self.bookmarks(),
            "unsold": self.unsold,
        }

    # ---- commander, materials, fuel, carrier, current system ----

    def make_backup(self):
        """One zip in BACKUP_DIR: a consistent copy of the database (SQLite's backup API, safe while the
        tailer writes) and every journal file. Runs on a worker thread; returns (path, size)."""
        import zipfile
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(BACKUP_DIR, f"outrider-{stamp}.zip")
        tmp_db = os.path.join(BACKUP_DIR, f".db-{stamp}.sqlite")
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
        try:
            with zipfile.ZipFile(path + ".part", "w", zipfile.ZIP_DEFLATED) as z:
                z.write(tmp_db, os.path.basename(self.db_path))
                for d in LIVE_DIRS + LEGACY_DIRS:
                    for j in sorted(glob(os.path.join(d, "Journal.*.log"))):
                        z.write(j, os.path.join("journals", os.path.basename(j)))
            os.replace(path + ".part", path)
        finally:
            os.remove(tmp_db)
        return path, os.path.getsize(path)

    async def backup(self):
        try:
            path, size = await asyncio.get_running_loop().run_in_executor(None, self.make_backup)
            meta_set(self.db, "last_backup", {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "path": path, "size": size})
            self.db.commit()
            print(f"backup written: {path} ({size / 1e6:.1f} MB)")
        except Exception as e:
            meta_set(self.db, "last_backup", dict(meta_get(self.db, "last_backup") or {}, error=f"{type(e).__name__}: {e}"))
            self.db.commit()
            print(f"backup failed: {type(e).__name__}: {e}", file=sys.stderr)
        self.bump()

    def since_sale(self):
        """Days, jumps and light-years since your last cartographic sale (the Unsold tile's turn-back line)."""
        key = (self.scan_version, self.version // 50)
        if getattr(self, "_since_sale_key", None) != key:
            last = self.db.execute("SELECT max(ts) FROM sale_events WHERE kind = 'carto'").fetchone()[0]
            if not last:
                self._since_sale = None
            else:
                st = self.span_stats(last, "~")
                self._since_sale = {"ts": last, "days": round((time.time() - ts_seconds(last)) / 86400, 1),
                                    "jumps": st["jumps"], "ly": st["ly"]}
            self._since_sale_key = key
        return self._since_sale

    def sampling_summary(self):
        """While you are on a body with a sample run in progress: how far you are from the samples you have
        taken, against the genus's colony distance. None otherwise (or when positions are unknown)."""
        st, pos = self.journals.status_json or {}, self.journals.pos
        ob = self.on_body()
        if not ob or st.get("lat") is None or not st.get("planet_radius") or not ed_bio:
            return None
        run = self.db.execute("SELECT system, body_id, species, genus_name, species_name, samples FROM own_organic "
                              "WHERE system=? AND done_ts IS NULL ORDER BY ts DESC LIMIT 1", (pos["id64"],)).fetchone()
        if not run:
            return None
        pts = [dict(r) for r in self.db.execute("SELECT genus, lat, lon, n FROM sample_points WHERE system=? AND body_id=? AND species=?",
                                                (run["system"], run["body_id"], run["species"]))]
        need = ed_bio.colony_distance(pts[0]["genus"] if pts else None, run["genus_name"])
        out = {"genus": run["genus_name"], "species": run["species_name"], "samples": run["samples"], "need": need,
               "points": len(pts), "nearest": None, "to_go": None, "clear": None}
        if pts and need:
            nearest = min(ed_bio.surface_distance(st["lat"], st["lon"], p["lat"], p["lon"], st["planet_radius"]) for p in pts)
            out.update(nearest=round(nearest), to_go=max(0, round(need - nearest)), clear=nearest >= need)
        return out

    def on_body(self):
        """The body you are landed on, driving on or walking on (Status.json), else None."""
        st, pos = self.journals.status_json or {}, self.journals.pos
        if not st.get("live") or not st.get("body") or not pos:
            return None
        flags, flags2 = st.get("flags") or 0, st.get("flags2") or 0
        how = "on foot" if flags2 & 1 else "in the SRV" if flags & (1 << 26) else "landed" if flags & 2 else None
        if not how:
            return None
        return {"body": short_name(pos["name"], st["body"]), "full": st["body"], "how": how, "system": str(pos["id64"])}

    def destination(self):
        """The in-game destination when it is a body in the system you are in (Status.json), else None."""
        st, pos = self.journals.status_json or {}, self.journals.pos
        d = st.get("destination") if st.get("live") else None
        if not d or not pos or d.get("System") != pos["id64"] or d.get("Body") is None:
            return None
        return {"body_id": d["Body"], "name": short_name(pos["name"], d.get("Name") or "")}

    def region_info(self):
        """The galactic region you are in (codex entries are per region) and whether it is a nebula zone."""
        pos = self.journals.pos
        if not pos or not ed_bio:
            return None
        name = ed_bio.region_name(pos["x"], pos["y"], pos["z"])
        return {"name": name, "nebula": bool(ed_bio.in_nebula({"name": pos["name"], "x": pos["x"], "y": pos["y"], "z": pos["z"]}))}

    def moments_summary(self):
        """The latest journal moments for the page's alerts, with scans and bio signals priced: the page
        compares them with your (per-browser) highlight levels and announces only what crosses them."""
        out, ctxs = [], {}
        for m in list(self.journals.moments)[-10:]:
            m = dict(m)
            if m["kind"] == "signals":
                where = self.locate(m["system"])
                m.update(system=str(m["system"]), body=short_name(where[0], m["body_name"]) if where else m["body_name"])
            if m["kind"] in ("scan", "bio"):
                row = self.db.execute("SELECT name, record FROM own_bodies WHERE system=? AND body_id=?",
                                      (m["system"], m["body_id"])).fetchone()
                where = self.locate(m["system"])
                if not row or not where:
                    continue
                rec = json.loads(row["record"])
                sysname = where[0]
                m.update(system=str(m["system"]), system_name=sysname, body=short_name(sysname, rec["name"]),
                         subtype=rec.get("subtype"), terraformable=bool(rec.get("terraformable")),
                         landable=bool(rec.get("landable")), first_discovered=rec.get("was_discovered") is False,
                         notable=NOTABLE_PLANETS.get(rec.get("subtype")))
                if rec.get("ed") and ed_unsold:
                    m["base_value"] = ed_unsold.body_value(dict(rec["ed"], first_discovered=False, first_mapped=False),
                                                           True, False, True)
                if m["kind"] == "bio":
                    if m["system"] not in ctxs:
                        recs = [json.loads(r["record"]) for r in self.db.execute(
                            "SELECT record FROM own_bodies WHERE system=?", (int(m["system"]),))]
                        star = self.db.execute("SELECT star_class FROM jumps WHERE id64=? ORDER BY ts DESC LIMIT 1",
                                               (int(m["system"]),)).fetchone()
                        ctxs[m["system"]] = (bio_context(sysname, recs, where[1], where[2], where[3],
                                                         star["star_class"] if star else None),
                                             star["star_class"] if star else None)
                    ctx, star = ctxs[m["system"]]
                    m["bio_value"], _ = bio_guess(dict(rec, bio=m.get("signals") or 1), star, None, ctx)
            out.append(m)
        return out

    def visit_count(self, id64):
        row = self.db.execute("SELECT count FROM visits WHERE id64=?", (id64,)).fetchone()
        return row["count"] if row else 0

    def commander_summary(self):
        c = self.journals.commander
        if not c:
            return None
        cr = c.get("credits")
        rank, prog = c.get("rank") or {}, c.get("progress") or {}
        ranks = {k: {"rank": rank[k], "name": RANK_NAMES[k][rank[k]] if 0 <= rank[k] < len(RANK_NAMES[k]) else str(rank[k]),
                     "progress": prog.get(k)} for k in RANK_NAMES if isinstance(rank.get(k), int)}
        return {"name": c.get("name"), "credits": cr + (c.get("earned") or 0) if cr is not None else None,
                "credits_login": cr, "earned": c.get("earned") or 0, "login_ts": c.get("login_ts"),
                "loan": c.get("loan"), "mode": c.get("mode"), "ranks": ranks}

    def materials_summary(self):
        m = self.journals.materials
        if not m or not m.get("snapshot_ts"):
            return None
        login = (self.journals.commander or {}).get("login_ts")
        return {"ts": m.get("ts"), "snapshot_ts": m["snapshot_ts"], "version": self.materials_version,
                "boosts": ed_materials.boosts(m["counts"]), "count": sum(m["counts"].values()),
                "repairs": ed_materials.craftable(m["counts"], ed_materials.SYNTH["Repair basic"]["materials"])[0],
                # a login whose Materials line was never seen: the counts predate it
                "stale": bool(login and ts_seconds(login) - ts_seconds(m["snapshot_ts"]) > 120)}

    def fuel_summary(self):
        j = self.journals
        st, ship = j.status_json, j.ship or {}
        if not st or st.get("fuel_main") is None:   # no reading yet (or on foot before any)
            return {"live": False}
        cap = ship.get("fuel_main")
        # Fuel per jump at your recent pace, and per max-range jump (fuel use ~ dist^2.x, so a
        # max jump costs far more than a short hop): both are shown.
        hist = j.fuel_hist[-FUEL_HISTORY:]
        per_jump = sum(f for _, f in hist) / len(hist) if hist else None
        max_range = (j.jump_range or {}).get("ly")
        per_max = None
        if hist and max_range:
            # scale the biggest recent jump up to max range with the game's ~2.5 exponent
            d, f = max(hist, key=lambda h: h[0])
            per_max = f * (max_range / d) ** 2.5 if d else None
        since_scoop = self.db.execute("SELECT count(*) FROM jumps WHERE kind='FSDJump' AND ts > ?",
                                      (j.last_scoop or "",)).fetchone()[0]
        return {"main": st["fuel_main"], "reservoir": st.get("fuel_reservoir"), "capacity": cap,
                "pct": round(100 * st["fuel_main"] / cap) if cap else None,
                "jumps_recent": int(st["fuel_main"] / per_jump) if per_jump else None,
                "jumps_max": int(st["fuel_main"] / per_max) if per_max else None,
                "since_scoop": since_scoop, "last_scoop": j.last_scoop, "ts": st.get("ts"),
                "live": bool(st.get("live")),
                "low_flag": bool((st.get("flags") or 0) & (1 << 19))}   # Status.json LowFuel: the game's own warning

    def carrier_summary(self):
        c = self.journals.carrier
        if not c or not c.get("id64"):
            return None
        if c.get("x") is None:
            where = self.locate(c["id64"])
            if where:
                c.update(x=where[1], y=where[2], z=where[3])
        pos = self.journals.pos
        d = dist(pos, c) if pos and c.get("x") is not None else None
        services = c.get("services") or []
        planned = dict(c["planned"]) if c.get("planned") else None
        if planned and planned.get("id64") and pos:   # how far the booked jump takes it from you
            where = self.locate(int(planned["id64"])) if str(planned["id64"]).isdigit() else None
            if where:
                planned["distance_from_you"] = round(dist(pos, {"x": where[1], "y": where[2], "z": where[3]}), 1)
                planned["jump_ly"] = round(dist(c, {"x": where[1], "y": where[2], "z": where[3]}), 1) if c.get("x") is not None else None
        docked = self.journals.docked
        return {"name": c.get("name"), "callsign": c.get("callsign"), "system": c.get("system"),
                "aboard": bool(docked and c.get("id") and docked.get("market_id") == c.get("id")),
                "id64": str(c["id64"]), "distance": round(d, 1) if d is not None else None,
                "fuel": c.get("fuel"), "jump_range": c.get("jump_range"), "planned": planned,
                "has_uc": "exploration" in services, "has_vista": "vistagenomics" in services,
                "x": c.get("x"), "y": c.get("y"), "z": c.get("z"),
                "ts": c.get("ts"), "here": bool(pos and pos["id64"] == c["id64"])}

    def docked_summary(self):
        """Where you are docked, if anywhere, and whether it buys exploration data."""
        d, st = self.journals.docked, self.journals.status_json or {}
        flags = st.get("flags") or 0
        if not d or (st.get("live") and not flags & 1):
            return None
        return dict(d, docked_now=bool(flags & 1) if st.get("live") else None)

    JUMPONIUM = ("carbon", "vanadium", "germanium", "cadmium", "niobium", "arsenic", "yttrium", "polonium")

    def material_sources(self, radius=300.0, per=3):
        """For each FSD-injection material, the nearest landable bodies you have scanned that carry it (your
        Scan events list surface materials), richest first among the near ones. Unscanned bodies are unknown."""
        pos = self.journals.pos
        if not pos:
            return {}
        if getattr(self, "_mat_src_key", None) != self.scan_version:
            where = {r[0]: (r[1], r[2], r[3], r[4]) for r in self.db.execute("SELECT id64, name, x, y, z FROM visits")}
            bodies = []
            for r in self.db.execute("SELECT system, name, raw FROM own_bodies WHERE raw LIKE '%\"Materials\"%'"):
                ev = json.loads(r["raw"])
                mats = {m.get("Name", "").lower(): m.get("Percent") for m in ev.get("Materials") or []}
                if ev.get("Landable") and mats and r["system"] in where:
                    n, x, y, z = where[r["system"]]
                    bodies.append({"system": n, "id": str(r["system"]), "body": short_name(n, r["name"]),
                                   "x": x, "y": y, "z": z, "mats": {k: v for k, v in mats.items() if k in self.JUMPONIUM}})
            self._mat_bodies, self._mat_src_key = bodies, self.scan_version
        out = {}
        near = [(dist(pos, b), b) for b in self._mat_bodies]
        near = [(d, b) for d, b in near if d <= radius]
        near.sort(key=lambda t: t[0])
        for m in self.JUMPONIUM:
            hits = [(d, b) for d, b in near if b["mats"].get(m)]
            out[m] = [{"system": b["system"], "id": b["id"], "body": b["body"], "distance": round(d, 1), "pct": round(b["mats"][m], 1)}
                      for d, b in hits[:per]]
        return out

    def left_behind(self, radius=100.0):
        """Visited systems within `radius` ly with work still to do: bodies not found after a honk, genera the
        DSS found but you never sampled, unmapped planets with what mapping would add (bonus-free). Batched
        queries over all candidates at once; the page applies your thresholds."""
        pos = self.journals.pos
        if not pos:
            return {"radius": radius, "systems": []}
        key = (self.scan_version, pos["id64"], radius)
        if getattr(self, "_left_key", None) == key:
            return self._left
        box = (pos["x"] - radius, pos["x"] + radius, pos["y"] - radius, pos["y"] + radius, pos["z"] - radius, pos["z"] + radius)
        cands = {r["id64"]: dict(r) for r in self.db.execute(
            "SELECT id64, name, x, y, z FROM visits WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?", box)
            if r["id64"] != pos["id64"] and dist(pos, r) <= radius}
        if not cands:
            self._left, self._left_key = {"radius": radius, "systems": []}, key
            return self._left
        ids = list(cands)
        marks = ",".join("?" * len(ids))
        q = lambda sql: self.db.execute(sql.format(marks=marks), ids)
        honk = {r["id64"]: r for r in q("SELECT id64, body_count, all_found FROM own_systems WHERE id64 IN ({marks})")}
        bodies = {}
        for r in q("SELECT system, body_id, name, ts, record FROM own_bodies WHERE system IN ({marks})"):
            bodies.setdefault(r["system"], {})[r["body_id"]] = r
        genera = {}
        for r in q("SELECT system, body_id, genus_name FROM own_genera WHERE system IN ({marks})"):
            genera.setdefault((r["system"], r["body_id"]), set()).add(r["genus_name"])
        done = {}
        for r in q("SELECT system, body_id, genus_name, done_ts FROM own_organic WHERE system IN ({marks}) AND done_ts IS NOT NULL"):
            if organic_state(self.db, r["done_ts"]) != "lost":
                done.setdefault((r["system"], r["body_id"]), set()).add(r["genus_name"])
        mapped = {(r["system"], r["body_id"]): r["ts"] for r in q("SELECT system, body_id, ts FROM own_mapped WHERE system IN ({marks})")}
        out = []
        for id64, c in cands.items():
            bs = bodies.get(id64, {})
            h = honk.get(id64)
            unfound = (h["body_count"] - len(bs)) if h and h["body_count"] and not h["all_found"] else 0
            bio, maps = [], []
            for (sid, bid), gs in genera.items():
                if sid != id64:
                    continue
                left = sorted(gs - done.get((sid, bid), set()))
                if left and bid in bs:
                    bio.append({"body": short_name(c["name"], bs[bid]["name"]), "genera": left,
                                "value": sum((ed_bio.genus_value(g) or 0) if ed_bio else 0 for g in left)})
            judge = None
            for bid, r in bs.items():
                rec = json.loads(r["record"])
                if rec.get("type") != "Planet" or not rec.get("ed") or not ed_unsold:
                    continue
                m = mapped.get((id64, bid))
                if m:
                    judge = judge or pickup_judge(self.db, c["name"])
                    if judge(m)[0] != "lost":
                        continue
                plain = dict(rec["ed"], first_discovered=False, first_mapped=False)
                inc = ed_unsold.body_value(plain, True, False, True) - ed_unsold.body_value(plain, False, False, True)
                maps.append({"body": short_name(c["name"], r["name"]), "subtype": rec.get("subtype"),
                             "terraformable": bool(rec.get("terraformable")), "increment": inc})
            if unfound or bio or maps:
                maps.sort(key=lambda m: -m["increment"])
                out.append({"id": str(id64), "name": c["name"], "distance": round(dist(pos, c), 1),
                            "unfound": unfound, "bio": bio, "maps": maps[:6], "maps_total": len(maps)})
        out.sort(key=lambda r: r["distance"])
        self._left, self._left_key = {"radius": radius, "systems": out}, key
        return self._left

    def firsts_list(self):
        """Every visited system holding first-discovery data, with its sale state and value."""
        pos = self.journals.pos
        out = []
        for r in self.db.execute(
                "SELECT DISTINCT f.system AS id64, v.name, v.x, v.y, v.z FROM own_firsts f "
                "JOIN visits v ON v.id64 = f.system"):
            f = own_firsts(self.db, r["id64"], r["name"])
            if not f or f["sale"] == "sold":
                continue
            out.append({"id": str(r["id64"]), "name": r["name"], "state": f["sale"], "system": f["system"],
                        "system_state": f["system_state"], "bodies_by": f["bodies_by"], "mapped_by": f["mapped_by"],
                        "distance": round(dist(pos, r), 2) if pos else None,
                        "value": self.system_values.get(r["name"])})
        out.sort(key=lambda x: (-(x["value"] or 0), x["distance"] or 0))
        return out

    def here_star(self):
        pos = self.journals.pos
        if not pos:
            return None
        row = self.db.execute("SELECT star_class FROM jumps WHERE id64=? ORDER BY ts DESC LIMIT 1",
                              (pos["id64"],)).fetchone()
        return (row["star_class"] if row else None) or (self.systems.get(pos["id64"]) or {}).get("main_class")

    def codex_recent(self, n=5):
        return [dict(r) for r in self.db.execute(
            "SELECT ts, name, category, subcategory, region, system_name, is_new, voucher FROM codex "
            "WHERE is_new = 1 OR voucher IS NOT NULL ORDER BY ts DESC LIMIT ?", (n,))]

    def leaving_summary(self, id64):
        """What is unfinished in a system: unscanned bodies, unsampled bio, unmapped valuables."""
        sysrow = self.db.execute("SELECT body_count, all_found FROM own_systems WHERE id64=?", (id64,)).fetchone()
        star_row = self.db.execute("SELECT star_class FROM jumps WHERE id64=? ORDER BY ts DESC LIMIT 1", (id64,)).fetchone()
        star = star_row["star_class"] if star_row else None
        bodies = {r["body_id"]: json.loads(r["record"]) for r in
                  self.db.execute("SELECT body_id, record FROM own_bodies WHERE system=?", (id64,))}
        if not sysrow and not bodies:
            return None
        where = self.locate(id64) or ("", None, None, None)
        ctx = bio_context(where[0], bodies.values(), where[1], where[2], where[3], star)
        name_of = lambda bid: short_name(where[0], bodies[bid]["name"])
        count = sysrow["body_count"] if sysrow else None
        unscanned = (count - len(bodies)) if count else None
        judge = pickup_judge(self.db, where[0])
        mapped = {r[0] for r in self.db.execute("SELECT body_id, ts FROM own_mapped WHERE system=?", (id64,))
                  if judge(r[1])[0] != "lost"}   # a map that died with the ship needs doing again
        # bio: genera the DSS found vs species you've completed on that body
        genera = {}
        for r in self.db.execute("SELECT body_id, genus_name FROM own_genera WHERE system=?", (id64,)):
            genera.setdefault(r["body_id"], set()).add(r["genus_name"])
        done = {}
        for r in self.db.execute("SELECT body_id, genus_name, done_ts, samples FROM own_organic WHERE system=?", (id64,)):
            d = done.setdefault(r["body_id"], {"done": set(), "partial": {}})
            if r["done_ts"] and organic_state(self.db, r["done_ts"]) != "lost":
                d["done"].add(r["genus_name"])   # a sample that died with you needs doing again
            elif not r["done_ts"]:
                d["partial"][r["genus_name"]] = r["samples"]
        bio_signals = {r["name"]: r["bio"] for r in self.db.execute(
            "SELECT name, bio FROM own_signals WHERE system=? AND bio > 0", (id64,))}
        region = ed_bio.region_name(where[1], where[2], where[3]) if ed_bio and where[1] is not None else None
        known_species = codex_species(self.db, region)
        codex_new = lambda groups: any(g.get("best") and g["best"].lower() not in known_species for g in groups) if region else False
        bio_pending = []
        for bid, rec in bodies.items():
            n_sig = bio_signals.get(rec["name"], 0)
            if not n_sig and bid not in genera:
                continue
            left = genera.get(bid, set()) - done.get(bid, {}).get("done", set())
            partial = done.get(bid, {}).get("partial", {})
            val, groups = bio_guess(dict(rec, bio=n_sig), star, sorted(genera[bid]) if bid in genera else None, ctx)
            if bid not in genera and not partial:
                bio_pending.append({"body": name_of(bid), "signals": n_sig, "genera": None, "partial": {}, "potential": val,
                                    "codex_new": codex_new(groups)})
            elif left or partial:
                left_val, left_groups = bio_guess(rec, star, sorted(left), ctx) if left else (None, [])
                bio_pending.append({"body": name_of(bid), "signals": n_sig, "genera": sorted(left),
                                    "partial": partial, "potential": left_val, "codex_new": codex_new(left_groups)})
        unmapped, unmapped_all = [], []
        for bid, rec in bodies.items():
            if bid in mapped or rec.get("type") != "Planet":
                continue
            # first-mapping pays 8x even on a body someone else discovered: either flag counts
            special = (rec.get("was_discovered") is False or rec.get("was_mapped") is False) and \
                (rec["subtype"] in NOTABLE_PLANETS or bool(rec.get("terraformable")))
            if special:
                tag = NOTABLE_PLANETS.get(rec["subtype"], "")
                unmapped.append(f"{name_of(bid)} ({tag or rec['subtype']}{' T' if rec.get('terraformable') else ''}"
                                f"{', first map' if rec.get('was_mapped') is False and rec.get('was_discovered') else ''})")
            # what mapping would add, bonus-free (the green-row level is bonus-free too); the page keeps
            # only the ones over that level, so ordinary bodies never sound the leaving alert
            inc = None
            if rec.get("ed") and ed_unsold:
                plain = dict(rec["ed"], first_discovered=False, first_mapped=False)
                inc = ed_unsold.body_value(plain, True, False, True) - ed_unsold.body_value(plain, False, False, True)
            unmapped_all.append({"body": name_of(bid), "subtype": rec["subtype"], "terraformable": bool(rec.get("terraformable")),
                                 "increment": inc, "special": special})
        unmapped_all.sort(key=lambda u: -(u["increment"] or 0))
        return {"body_count": count, "scanned": len(bodies), "unscanned": unscanned,
                "honked": bool(sysrow), "all_found": bool(sysrow and sysrow["all_found"]),
                "bio_pending": bio_pending, "unmapped_valuable": unmapped, "unmapped": unmapped_all,
                "clean": not unscanned and not bio_pending and not unmapped}

    def system_detail(self, id64):
        """Every body known in a system, valued, with your firsts, mapping, bio and codex."""
        where = self.locate(id64)
        if not where:
            return None
        name = where[0]
        base = self.bases.get(id64, (None, None))[1]
        if base is None:
            _, base = self.spansh.cached(id64)
        records = merge_records((base or {}).get("records") or [], *own_data(self.db, id64, name)[:2])
        own_ids = {short_name(name, r["name"]): r["body_id"] for r in
                   self.db.execute("SELECT body_id, name FROM own_bodies WHERE system=?", (id64,))}
        firsts = {r["body_id"]: dict(r) for r in self.db.execute(
            """SELECT f.body_id, f.was_discovered, f.was_mapped, f.was_footfalled, f.undisc_ts, f.first_ts,
                      m.ts AS mapped_ts, ff.ts AS foot_ts FROM own_firsts f
               LEFT JOIN own_mapped m ON m.system = f.system AND m.body_id = f.body_id
               LEFT JOIN own_footfall ff ON ff.system = f.system AND ff.body_id = f.body_id
               WHERE f.system = ?""", (id64,))}
        organics = {}
        for r in self.db.execute("SELECT * FROM own_organic WHERE system=? ORDER BY genus_name", (id64,)):
            st = organic_state(self.db, r["done_ts"])
            organics.setdefault(r["body_id"], []).append(
                {"genus": r["genus_name"], "species": r["species_name"], "variant": r["variant_name"],
                 "samples": r["samples"], "done": bool(r["done_ts"]) and st != "lost", "state": st,
                 "lost": st == "lost",
                 "value": ed_bio.species_value(r["species_name"]) if ed_bio and r["species_name"] else None})
        genera = {}
        for r in self.db.execute("SELECT body_id, genus_name FROM own_genera WHERE system=?", (id64,)):
            genera.setdefault(r["body_id"], []).append(r["genus_name"])
        codex = {}
        for r in self.db.execute("SELECT body_id, name, is_new, voucher FROM codex WHERE system=?", (id64,)):
            codex.setdefault(r["body_id"], []).append({"name": r["name"], "new": bool(r["is_new"]), "voucher": r["voucher"]})
        odyssey = True
        star_row = self.db.execute("SELECT star_class FROM jumps WHERE id64=? ORDER BY ts DESC LIMIT 1", (id64,)).fetchone()
        star = star_row["star_class"] if star_row else None
        ctx = bio_context(name, records, where[1], where[2], where[3], star)
        region = ed_bio.region_name(where[1], where[2], where[3]) if ed_bio and where[1] is not None else None
        known_species = codex_species(self.db, region)
        judge = pickup_judge(self.db, name)
        # your latest scan of each body: data re-collected after a loss or a sale counts again
        latest = {r["body_id"]: r["ts"] for r in self.db.execute("SELECT body_id, ts FROM own_bodies WHERE system=?", (id64,))}
        out = []
        for r in records:
            bid = own_ids.get(r["name"])
            known_genera = genera.get(bid) or r.get("genera") or []
            bio_val, bio_groups = bio_guess(r, star, known_genera or None, ctx) if (r.get("bio") or known_genera) else (None, [])
            f = firsts.get(bid) if bid is not None else None
            first_disc = bool(f and f["was_discovered"] == 0)
            scan_state = judge(latest[bid])[0] if bid in latest else None
            map_state = judge(f["mapped_ts"])[0] if f and f["mapped_ts"] else None   # a map dies with the ship too
            cv = carto_values(r, bid is not None, f, scan_state, map_state, odyssey)
            value, value_if_mapped, base_value = cv["value"], cv["value_if_mapped"], cv["base_value"]
            is_mapped, first_map = cv["mapped"], cv["first_mapped"]
            held = organics.get(bid, [])
            bio_factor = 5 if f and f["was_footfalled"] == 0 else 1   # x5 where nobody had set foot when you scanned
            bio_now = sum((o.get("value") or 0) for o in held if o["done"] and not o["lost"]) * bio_factor
            got = {o["genus"] for o in held if o["done"] and not o["lost"]}
            bio_left = sum((g.get("value") or 0) for g in bio_groups if g["genus"] not in got) * bio_factor
            carto_now, carto_left = cv["now"], cv["left"]
            # Max without any bonus: no first-discovery / first-mapped multipliers, bio at x1
            max_nb = cv["now_nb"] + cv["left_nb"] + (bio_now + bio_left) / bio_factor
            out.append({
                "value_now": int(carto_now + bio_now), "value_max": int(carto_now + bio_now + carto_left + bio_left),
                "value_max_base": int(max_nb),
                "value_parts": {"carto_now": int(carto_now), "bio_now": int(bio_now), "carto_left": int(carto_left),
                                "bio_left": int(bio_left), "scan_state": scan_state, "bio_factor": bio_factor},
                "name": r["name"], "type": r["type"], "subtype": r["subtype"], "main": r.get("main"),
                "dist_ls": r.get("dist_ls"), "gravity": r.get("gravity"), "atmosphere": r.get("atmosphere"),
                "temperature": r.get("temperature"), "volcanism": r.get("volcanism"), "pressure": r.get("pressure"),
                "ring_details": ring_stats(r.get("rings")),
                "landable": r.get("landable"), "terraformable": r.get("terraformable"),
                "notable": NOTABLE_PLANETS.get(r["subtype"]), "scoopable": r.get("scoopable"),
                "rings": len(r.get("rings") or []), "hotspots": sum(1 for x in r.get("rings") or [] if x.get("hotspots")),
                "rings_mapped": sum(1 for x in r.get("rings") or [] if x.get("hotspots") or x.get("mapped")),
                "bio": r.get("bio") or 0, "geo": r.get("geo") or 0,
                "genera": known_genera,
                "bio_guess": [{"genus": g["genus"], "best": g["best"], "value": g["value"], "min_value": g["min_value"],
                               "species": [ed_bio.short_species(x["name"], g["genus"]) for x in g["species"]],
                               "unruled": bool(g.get("unruled")),
                               # the likeliest species has no codex entry of yours in this region yet
                               "codex_new": bool(region and g.get("best") and g["best"].lower() not in known_species
                                                 and g["genus"] not in got)} for g in bio_groups],
                "bio_potential": bio_val,
                # undecided before the DSS: every genus it could be, and the range ("Stratum or Bacterium")
                "bio_options": bio_options(r, star, ctx) if r.get("bio") and not known_genera else None,
                "organics": organics.get(bid, []), "codex": codex.get(bid, []),
                "scanned": bid is not None, "first_discovered": first_disc, "mapped": is_mapped,
                "first_mapped": first_map, "map_state": map_state, "footfall": bool(f and f["foot_ts"]),
                "first_footfall": bool(f and f["was_footfalled"] == 0 and f["foot_ts"]),
                "value": value, "value_if_mapped": value_if_mapped,
                "base_value": base_value,
                "body_id": r.get("body_id"), "radius_km": r.get("radius_km"), "sma_ls": r.get("sma_ls"),
                "parents_full": r.get("parents_full"),
            })
        out.sort(key=lambda b: -(b["value_max"] or 0))
        tree, parent_of = build_tree(name, out)
        types = {b["name"]: b["type"] for b in out}
        raws = {}
        for r_ in self.db.execute("SELECT name, raw FROM own_bodies WHERE system=?", (id64,)):
            if r_["raw"]:
                raws[short_name(name, r_["name"])] = json.loads(r_["raw"])
        cur = system_curiosities(name, out, raws)
        for b in out:
            p = parent_of.get(b["name"])
            b["is_moon"] = bool(p and p[0] == "b" and types.get(p[1]) == "Planet")
            b["curiosities"] = [{"tag": t, "why": w} for t, w in cur.get(b["name"], [])]
            del b["parents_full"]
        # Spansh knows bodies here but their details have not landed yet (a refresh is fetching them):
        # the page asks again until they have, instead of keeping search-level rows and a guessed tree
        spansh_recs = (base or {}).get("records") or []
        partial = bool(spansh_recs) and not any(x.get("full") for x in spansh_recs) \
            and self.dump_tries.get(id64, 0) < DUMP_MAX_TRIES
        phenomena = [dict(r) for r in self.db.execute("SELECT kind, ts, reached_ts FROM phenomena WHERE system=?", (id64,))]
        return {"id64": str(id64), "name": name, "bodies": out, "tree": tree, "partial": partial, "region": region,
                "phenomena": phenomena,
                "leaving": self.leaving_summary(id64),
                "firsts": own_firsts(self.db, id64, name),
                "value_now": sum(b["value_now"] for b in out), "value_max": sum(b["value_max"] for b in out),
                "value_max_base": sum(b["value_max_base"] for b in out)}

    async def ensure_records(self, id64):
        """Make sure a system's bodies are known before showing it: a search result or pinned system with
        no cached Spansh dump gets one fetched (and cached) now. Failures leave things as they were."""
        if id64 in self.bases:
            return      # in the sphere: the refresh fetches it (system_detail says "partial" until then)
        _, base = self.spansh.cached(id64)
        if base and any(r.get("full") for r in base.get("records") or []):
            age = self.spansh.fetched_age(id64)
            if age is None or age < ON_DEMAND_MAX_AGE:
                return  # fetched on demand recently enough; older snapshots are fetched again below
        where = self.locate(id64)
        if not where:
            return
        name, x, y, z = where
        try:
            await self.spansh.full_records(id64, None, {"v": CACHE_VERSION, "name": name, "x": x, "y": y, "z": z,
                                                        "body_count": None, "records": (base or {}).get("records") or []},
                                           interactive=True)
        except Exception as e:
            print(f"body lookup for {name} failed: {type(e).__name__}: {e}", file=sys.stderr)

    async def body_detail(self, id64, body_name):
        """Everything known about one body: your raw Scan, Spansh's record, and the merged row."""
        detail = self.system_detail(id64)
        if not detail:
            return None
        row = next((b for b in detail["bodies"] if b["name"] == body_name), None)
        # The short name is the full one minus the system prefix, except for named bodies (Earth, a
        # catalogue star in a named system) whose names never carried it: try both forms.
        prefixed = f"{detail['name']} {body_name}" if body_name != detail["name"] else body_name
        raw = self.db.execute("SELECT name, raw FROM own_bodies WHERE system=? AND name IN (?, ?) "
                              "ORDER BY name = ? DESC LIMIT 1", (id64, prefixed, body_name, prefixed)).fetchone()
        full = raw["name"] if raw else prefixed
        own = json.loads(raw["raw"]) if raw and raw["raw"] else None
        spansh = None
        cached = self.dump_cache.get(id64)
        if cached and time.time() - cached[0] < 600:
            dump = cached[1]
        else:
            try:
                dump = await self.spansh.lookup(id64)
                self.dump_cache[id64] = (time.time(), dump)
                if len(self.dump_cache) > 20:
                    self.dump_cache.clear()
            except Exception as e:
                dump, lookup_error = None, f"{type(e).__name__}: {e}"
        if dump:
            names = {full, prefixed, body_name}
            spansh = next((b for b in (dump.get("system") or {}).get("bodies") or [] if b.get("name") == full), None) \
                or next((b for b in (dump.get("system") or {}).get("bodies") or [] if b.get("name") in names), None)
            if spansh and not raw:
                full = spansh.get("name") or full
        rings = ring_stats([{"name": r.get("Name"), "type": RING_CLASSES.get(r.get("RingClass"), r.get("RingClass")),
                             "mass": r.get("MassMT"), "inner": r.get("InnerRad"), "outer": r.get("OuterRad")}
                            for r in (own or {}).get("Rings") or [] if not r.get("Name", "").endswith("Belt")]) \
            if own else ring_stats([{"name": r.get("name"), "type": r.get("type"), "mass": r.get("mass"),
                                     "inner": r.get("innerRadius"), "outer": r.get("outerRadius"),
                                     "hotspots": minerals((r.get("signals") or {}).get("signals"))}
                                    for r in (spansh or {}).get("rings") or []])
        if row:
            for x in rings:  # your DSS: hotspots and the mapped flag
                for y in row.get("ring_details") or []:
                    if y.get("name") and x.get("name", "").endswith(y["name"]):
                        if y.get("hotspots"):
                            x["hotspots"] = y["hotspots"]
                        x["mapped"] = bool(y.get("mapped") or y.get("hotspots") or x.get("hotspots"))
        return {"system": detail["name"], "id64": str(id64), "name": body_name, "full_name": full,
                "row": row, "own": own, "spansh": spansh, "rings": rings,
                "spansh_error": locals().get("lookup_error")}

    COUNT_QUERIES = {
        "firsts": "SELECT count(DISTINCT system) FROM own_firsts WHERE is_main=1 AND was_discovered=0 AND undisc_ts BETWEEN ? AND ?",
        "bodies_first": "SELECT count(*) FROM own_firsts WHERE was_discovered=0 AND undisc_ts BETWEEN ? AND ?",
        "mapped": "SELECT count(*) FROM own_mapped WHERE ts BETWEEN ? AND ?",
        "footfalls": "SELECT count(*) FROM own_footfall WHERE ts BETWEEN ? AND ?",
        "samples": "SELECT count(*) FROM own_organic WHERE done_ts BETWEEN ? AND ?",
        "codex_new": "SELECT count(*) FROM codex WHERE is_new=1 AND ts BETWEEN ? AND ?",
    }

    def range_counts(self, a, b):
        """What you achieved between two timestamps (inclusive): the per-session and all-time numbers."""
        return {k: self.db.execute(sql, (a, b)).fetchone()[0] for k, sql in self.COUNT_QUERIES.items()}

    def note_sale_estimates(self):
        """A sale just happened: record what Outrider estimated just before it, so the trip ledger can say how
        close the estimate was. The unsold estimate is recomputed after this tick, so it is still the
        pre-sale figure here. Only recent sales (read live) get one; history keeps NULL rather than a guess."""
        u = self.unsold
        if not u:
            return
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
        self.db.execute("UPDATE sale_events SET estimate = ? WHERE kind = 'carto' AND estimate IS NULL AND ts >= ?",
                        (int(u["carto"]["estimated_payout"]), since))
        self.db.execute("UPDATE sale_events SET estimate = ? WHERE kind = 'bio' AND estimate IS NULL AND ts >= ?",
                        (int(u["bio"]["estimated_value"]), since))

    def span_stats(self, a, b):
        """Jumps, light-years and farthest distance from Sol between two timestamps."""
        jumps = [dict(r) for r in self.db.execute(
            "SELECT ts, x, y, z, kind FROM jumps WHERE ts > ? AND ts <= ? ORDER BY ts", (a, b))]
        n, ly, far, prev = 0, 0.0, 0.0, None
        for j in jumps:
            if j["kind"] != "Location":
                n += 1
                if prev and prev["kind"] != "Location":
                    ly += dist(prev, j)
            far = max(far, math.sqrt(j["x"] ** 2 + j["y"] ** 2 + j["z"] ** 2))
            prev = j
        systems = self.db.execute("SELECT count(DISTINCT id64) FROM jumps WHERE ts > ? AND ts <= ?", (a, b)).fetchone()[0]
        return {"jumps": n, "ly": round(ly, 1), "max_sol": round(far), "systems": systems}

    def ledger(self):
        """The turn-back numbers: since your last sale, each sale-to-sale trip with what it actually paid,
        what each ship loss cost, the game's own career statistics and your most valuable finds."""
        key = (self.scan_version, self.db.execute("SELECT count(*) FROM sale_events").fetchone()[0])
        if getattr(self, "_ledger_key", None) == key:
            return self._ledger
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sales = [dict(r) for r in self.db.execute("SELECT * FROM sale_events ORDER BY ts")]
        # selling in several batches at one station is one sale: merge carto sales within an hour
        carto_sales = []
        for x in (x for x in sales if x["kind"] == "carto"):
            last = carto_sales[-1] if carto_sales else None
            if last and ts_seconds(x["ts"]) - ts_seconds(last["ts"]) < 3600:
                last.update(ts=x["ts"], total=(last["total"] or 0) + (x["total"] or 0),
                            systems=(last["systems"] or 0) + (x["systems"] or 0),
                            estimate=last["estimate"] if last["estimate"] is not None else x["estimate"])
            else:
                carto_sales.append(dict(x))
        last_carto = carto_sales[-1]["ts"] if carto_sales else ""
        last_bio = next((x["ts"] for x in reversed(sales) if x["kind"] == "bio"), None)
        since = dict(self.span_stats(last_carto, now), **self.range_counts(last_carto, "~"),
                     since=last_carto or None, last_bio=last_bio,
                     days=round((time.time() - ts_seconds(last_carto)) / 86400, 1) if last_carto else None)
        losses = self.ship_losses()
        trips, start = [], ""
        for x in carto_sales:
            end = x["ts"]
            paid_bio = sum(y["total"] or 0 for y in sales if y["kind"] == "bio" and start < y["ts"] <= end)
            hours = sum(max(0, ts_seconds(s_["end"]) - ts_seconds(s_["start"])) for s_ in self.sessions(start)
                        if s_["start"] > start and s_["end"] <= end) / 3600
            st = self.span_stats(start, end)
            paid = (x["total"] or 0) + paid_bio
            trips.append(dict(st, **self.range_counts(start, end), start=start or None, end=end,
                              days=round((ts_seconds(end) - ts_seconds(start)) / 86400, 1) if start else None,
                              paid_carto=x["total"], paid_bio=paid_bio, paid=paid, estimate=x["estimate"],
                              hours=round(hours, 1),
                              per_hour=round(paid / hours) if hours >= 0.5 else None,
                              per_jump=round(paid / st["jumps"]) if st["jumps"] else None,
                              per_ly=round(paid / st["ly"]) if st["ly"] else None,
                              first_rate=round(100 * self.range_counts(start, end)["firsts"] / st["jumps"]) if st["jumps"] else None,
                              losses=[l for l in losses if start < l["ts"] <= end]))
            start = end
        trips.reverse()
        stats = meta_get(self.db, "statistics")
        self._ledger = {"since_last_sale": since, "trips": trips, "career": stats, "losses": losses,
                        "top_finds": self.top_finds()}
        self._ledger_key = key
        return self._ledger

    def ship_losses(self):
        """What each ship loss cost: the cartographic data you held that died with it (bodies scanned since
        the previous loss, not sold before it, and not scanned again since; valued with the bonuses)."""
        deaths = [r[0] for r in self.db.execute(f"SELECT ts FROM deaths WHERE {SHIP_LOSS_SQL} ORDER BY ts")]
        if not deaths or not ed_unsold:
            return []
        sales = {}
        for r in self.db.execute("SELECT name, ts FROM sales"):
            sales.setdefault(r["name"], []).append(r["ts"])
        mapped = {(r[0], r[1]): r[2] for r in self.db.execute("SELECT system, body_id, ts FROM own_mapped")}
        firsts = {(r[0], r[1]): r for r in self.db.execute("SELECT system, body_id, was_discovered, was_mapped FROM own_firsts")}
        names = {r[0]: r[1] for r in self.db.execute("SELECT id64, name FROM visits")}
        out = [{"ts": d, "bodies": 0, "value": 0, "firsts": 0} for d in deaths]
        for r in self.db.execute("SELECT system, body_id, ts, record FROM own_bodies"):
            i = next((k for k, d in enumerate(deaths) if d > r["ts"]), None)   # the first loss after your latest scan
            if i is None or (i > 0 and r["ts"] < deaths[i - 1]):
                continue
            if any(r["ts"] < t < deaths[i] for t in sales.get(names.get(r["system"]), [])):
                continue      # sold before the loss
            rec = json.loads(r["record"])
            if not rec.get("ed"):
                continue
            f = firsts.get((r["system"], r["body_id"]))
            m = mapped.get((r["system"], r["body_id"]))
            body = dict(rec["ed"], first_discovered=bool(f and f["was_discovered"] == 0),
                        first_mapped=bool(f and f["was_mapped"] == 0))
            out[i]["bodies"] += 1
            out[i]["value"] += ed_unsold.body_value(body, bool(m and m < deaths[i]), False, True)
            out[i]["firsts"] += int(bool(f and f["was_discovered"] == 0))
        return out

    def top_finds(self, n=25):
        """Your most valuable bodies ever (cartographics, with the bonuses you earned), and what became of them."""
        if not ed_unsold:
            return []
        judges, best = {}, []
        names = {r[0]: r[1] for r in self.db.execute("SELECT id64, name FROM visits")}
        mapped = {(r[0], r[1]): r[2] for r in self.db.execute("SELECT system, body_id, ts FROM own_mapped")}
        firsts = {(r[0], r[1]): r for r in self.db.execute("SELECT system, body_id, was_discovered, was_mapped FROM own_firsts")}
        for r in self.db.execute("SELECT system, body_id, name, ts, record FROM own_bodies"):
            rec = json.loads(r["record"])
            if not rec.get("ed"):
                continue
            f = firsts.get((r["system"], r["body_id"]))
            m = mapped.get((r["system"], r["body_id"]))
            body = dict(rec["ed"], first_discovered=bool(f and f["was_discovered"] == 0),
                        first_mapped=bool(f and f["was_mapped"] == 0))
            v = ed_unsold.body_value(body, bool(m), False, True)
            if len(best) < n or v > best[-1][0]:
                best.append((v, r, rec, bool(m), body))
                best.sort(key=lambda t: -t[0])
                del best[n:]
        out = []
        for v, r, rec, is_mapped, body in best:
            sysname = names.get(r["system"]) or ""
            if sysname not in judges:
                judges[sysname] = pickup_judge(self.db, sysname)
            out.append({"body": r["name"], "system": sysname, "id": str(r["system"]), "type": rec.get("subtype"),
                        "value": v, "mapped": is_mapped, "first_discovered": body["first_discovered"],
                        "state": judges[sysname](r["ts"])[0], "ts": r["ts"]})
        return out

    def history(self, days):
        """Your sessions (gaps of 2 h+ split them), newest first, with what each one achieved,
        plus an all-time row that ignores `days`."""
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
        sessions = self.sessions(since)
        for s_ in sessions:
            s_.update(self.range_counts(s_["start"], s_["end"] + "~"))  # "~" sorts after any time: inclusive
        everything = self.sessions("")
        all_time = {"jumps": sum(x["jumps"] for x in everything), "ly": round(sum(x["ly"] for x in everything), 1),
                    "max_sol": max((x["max_sol"] for x in everything), default=0), "sessions": len(everything),
                    "since": everything[-1]["start"] if everything else None}
        all_time.update(self.range_counts("", "~"))
        return {"days": days, "sessions": sessions, "all_time": all_time, "ledger": self.ledger()}

    def sessions(self, since):
        """Jumps since `since` grouped into sessions, newest first (no achievement counts)."""
        jumps = [dict(r) for r in self.db.execute(
            "SELECT ts, id64, name, x, y, z, kind FROM jumps WHERE ts >= ? ORDER BY ts", (since,))]
        def parse(ts):
            return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
        sessions, cur = [], None
        for j in jumps:
            t = parse(j["ts"])
            if not cur or t - cur["_last"] > 7200:
                cur = {"start": j["ts"], "end": j["ts"], "_last": t, "jumps": 0, "ly": 0.0, "systems": [],
                       "max_sol": 0.0, "_prev": None}
                sessions.append(cur)
            cur["end"], cur["_last"] = j["ts"], t
            if j["kind"] != "Location":
                cur["jumps"] += 1
                if cur["_prev"] and cur["_prev"]["kind"] != "Location":
                    cur["ly"] += dist(cur["_prev"], j)
            cur["max_sol"] = max(cur["max_sol"], math.sqrt(j["x"] ** 2 + j["y"] ** 2 + j["z"] ** 2))
            cur["systems"].append({"ts": j["ts"], "id": str(j["id64"]), "name": j["name"], "kind": j["kind"]})
            cur["_prev"] = j
        for s_ in sessions:
            s_["ly"] = round(s_["ly"], 1); s_["max_sol"] = round(s_["max_sol"])
            del s_["_last"], s_["_prev"]
        sessions.reverse()
        return sessions

    def system_names(self, ids):
        """id64 -> name for systems you have visited or scanned."""
        ids = list(set(ids))
        names = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for table, col in (("own_systems", "id64"), ("visits", "id64")):
                for r in self.db.execute(f"SELECT {col} AS id, name FROM {table} WHERE {col} IN ({marks})", chunk):
                    if r["name"]:
                        names[r["id"]] = r["name"]
        return names

    def organics(self, days):
        """Every exobiology sample run (newest first) with what it is worth and whether it was banked,
        plus your codex entries over the same period."""
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
        runs = [dict(r) for r in self.db.execute(
            """SELECT o.*, b.name AS body_name, f.was_footfalled FROM own_organic o
               LEFT JOIN own_bodies b ON b.system = o.system AND b.body_id = o.body_id
               LEFT JOIN own_firsts f ON f.system = o.system AND f.body_id = o.body_id
               WHERE coalesce(o.done_ts, o.ts) >= ? ORDER BY coalesce(o.done_ts, o.ts) DESC""", (since,))]
        codex = [dict(r) for r in self.db.execute("SELECT * FROM codex WHERE ts >= ? ORDER BY ts DESC", (since,))]
        names = self.system_names([r["system"] for r in runs] + [c["system"] for c in codex if c["system"]])
        sales = [r[0] for r in self.db.execute("SELECT ts FROM bio_sales ORDER BY ts")]
        rows, totals = [], {"aboard": 0, "sold": 0, "lost": 0, "in progress": 0}
        counts = dict.fromkeys(totals, 0)
        for r in runs:
            sysname = names.get(r["system"]) or f"#{r['system']}"
            st = organic_state(self.db, r["done_ts"]) or "in progress"
            factor = 5 if r["was_footfalled"] == 0 else 1
            base = ed_bio.species_value(r["species_name"]) if ed_bio and r["species_name"] else None
            value = base * factor if base else None
            body = short_name(sysname, r["body_name"]) if r["body_name"] else f"body #{r['body_id']}"
            rows.append({"ts": r["done_ts"] or r["ts"], "system": {"id": str(r["system"]), "name": sysname},
                         "body": body, "genus": r["genus_name"], "species": r["species_name"],
                         "variant": r["variant_name"], "samples": r["samples"], "state": st,
                         "value": value, "factor": factor,
                         "sold_ts": next((t for t in sales if t > r["done_ts"]), None) if st == "sold" else None})
            counts[st] += 1
            totals[st] += value or 0
        return {"days": days, "rows": rows, "totals": totals, "counts": counts,
                "codex": [{"ts": c["ts"], "name": c["name"], "category": c["category"], "subcategory": c["subcategory"],
                           "region": c["region"], "new": bool(c["is_new"]), "voucher": c["voucher"],
                           "system": {"id": str(c["system"]), "name": c["system_name"] or names.get(c["system"])}
                           if c["system"] else None} for c in codex]}

    def _unsold_rows(self):
        args = argparse.Namespace(commander=None, since=None, ignore_deaths=False, bonus_rate=None,
                                  efficiency_bonus=False, no_odyssey=False, top=0)
        return ed_unsold.analyse(ed_unsold.read_events(LIVE_DIRS + LEGACY_DIRS), args)["exploration"]["rows"]

    def export_rows(self, what):
        """Rows for the export endpoint: (columns, rows)."""
        if what == "bookmarks":
            rows = [dict(r) for r in self.db.execute("SELECT * FROM bookmarks ORDER BY created_ts")]
            return ["id64", "name", "x", "y", "z", "note", "created_ts"], rows
        if what == "jumps":
            rows = [dict(r) for r in self.db.execute("SELECT * FROM jumps ORDER BY ts")]
            return ["ts", "id64", "name", "x", "y", "z", "star_class", "kind"], rows
        if what == "trips":
            rows = [dict({k: v for k, v in t.items() if k != "losses"}, losses=len(t["losses"]),
                         lost_value=sum(l["value"] for l in t["losses"])) for t in self.ledger()["trips"]]
            return ["start", "end", "days", "jumps", "ly", "systems", "firsts", "bodies_first", "mapped", "footfalls",
                    "samples", "codex_new", "paid_carto", "paid_bio", "paid", "estimate", "hours", "per_hour", "per_jump",
                    "per_ly", "first_rate", "losses", "lost_value"], rows
        if what == "route":   # every jump with what it found: for write-ups and maps
            rows, prev = [], None
            firsts = {r[0]: r[1] for r in self.db.execute(
                "SELECT system, count(*) FROM own_firsts WHERE was_discovered = 0 GROUP BY system")}
            mapped = {r[0]: r[1] for r in self.db.execute("SELECT system, count(*) FROM own_mapped GROUP BY system")}
            samples = {r[0]: r[1] for r in self.db.execute(
                "SELECT system, count(*) FROM own_organic WHERE done_ts IS NOT NULL GROUP BY system")}
            for r in self.db.execute("SELECT ts, id64, name, x, y, z, star_class, kind FROM jumps ORDER BY ts"):
                r = dict(r)
                r["ly"] = round(dist(prev, r), 2) if prev and r["kind"] != "Location" and prev["kind"] != "Location" else None
                r.update(bodies_first=firsts.get(r["id64"], 0), mapped=mapped.get(r["id64"], 0), samples=samples.get(r["id64"], 0))
                rows.append(r)
                prev = r
            return ["ts", "id64", "name", "x", "y", "z", "star_class", "kind", "ly", "bodies_first", "mapped", "samples"], rows
        if what == "organics":
            rows = []
            for r in self.organics(3650)["rows"]:
                rows.append(dict(r, system=r["system"]["name"], system_id=r["system"]["id"]))
            return ["ts", "system", "system_id", "body", "genus", "species", "variant", "samples", "state",
                    "value", "factor", "sold_ts"], rows
        if what == "codex":
            rows = [dict(r) for r in self.db.execute("SELECT * FROM codex ORDER BY ts")]
            return ["ts", "entry_id", "name", "category", "subcategory", "region", "system", "system_name",
                    "body_id", "is_new", "new_traits", "voucher"], rows
        if what == "firsts":
            rows = []
            for r in self.db.execute(
                    "SELECT DISTINCT f.system AS id64, v.name, v.x, v.y, v.z FROM own_firsts f "
                    "JOIN visits v ON v.id64 = f.system ORDER BY v.name"):
                f = own_firsts(self.db, r["id64"], r["name"])
                if not f:
                    continue
                rows.append({"id64": r["id64"], "name": r["name"], "x": r["x"], "y": r["y"], "z": r["z"],
                             "system_first_discovered": int(bool(f["system"])), "system_state": f["system_state"],
                             "system_state_ts": f["system_ts"], "bodies_first_discovered": f["bodies"],
                             "bodies_sold": f["bodies_by"]["sold"], "bodies_unsold": f["bodies_by"]["unsold"],
                             "bodies_lost": f["bodies_by"]["lost"], "first_mapped": f["mapped"],
                             "first_footfalls": f["footfall"]})
            return ["id64", "name", "x", "y", "z", "system_first_discovered", "system_state", "system_state_ts",
                    "bodies_first_discovered", "bodies_sold", "bodies_unsold", "bodies_lost", "first_mapped",
                    "first_footfalls"], rows
        if what == "unsold" and ed_unsold:
            rows = self._unsold_rows()
            return ["system", "body", "type", "first_discovered", "first_mapped", "mapped", "efficient", "value"], rows
        return None, None

    # ---- bookmarks ----

    def bookmarks(self):
        pos = self.journals.pos
        out = []
        for b in self.db.execute("SELECT * FROM bookmarks"):
            out.append({"id": str(b["id64"]), "name": b["name"], "note": b["note"] or "",
                        "created": b["created_ts"],
                        "distance": round(dist(pos, b), 2) if pos else None})
        return out

    def locate(self, id64):
        """Name and coordinates for a system, from wherever we know it."""
        if id64 in self.bases:
            b = self.bases[id64][1]
            return b["name"], b["x"], b["y"], b["z"]
        if self.searcher and id64 in self.searcher.found:
            return self.searcher.found[id64]
        for table in ("visits", "route_systems"):
            r = self.db.execute(f"SELECT name, x, y, z FROM {table} WHERE id64=?", (id64,)).fetchone()
            if r:
                return tuple(r)
        r = self.db.execute("SELECT summary FROM spansh_systems WHERE id64=?", (id64,)).fetchone()
        if r:
            b = json.loads(r["summary"])
            return b["name"], b["x"], b["y"], b["z"]
        return None

    def set_bookmark(self, id64, note):
        existing = self.db.execute("SELECT created_ts FROM bookmarks WHERE id64=?", (id64,)).fetchone()
        where = self.locate(id64)
        if not where:
            return False
        created = existing["created_ts"] if existing else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.db.execute("INSERT OR REPLACE INTO bookmarks VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (id64, *where, note, created))
        self.db.commit()
        self.bump()
        return True

    def remove_bookmark(self, id64):
        self.db.execute("DELETE FROM bookmarks WHERE id64=?", (id64,))
        self.db.commit()
        self.bump()

    def system_value(self, id64, name, records, star, ctx=None):
        """Credits from a system: what selling now would pay for data you hold from it, and the
        most it could pay once everything there is scanned, mapped and sampled.

        Cartographics use the same formula as the unsold estimate for every body (first-discovery and
        first-mapping bonuses from your own scans; Spansh dump fields for bodies you have not
        scanned), through carto_values, the rules Here uses too. Exobiology pays x5 on a body nobody had set foot on when you scanned it (or
        where you took first footfall); a body you have not scanned counts at x1, since its
        footfall state is unknown.
        """
        own_ids = {short_name(name, r["name"]): r["body_id"] for r in
                   self.db.execute("SELECT body_id, name FROM own_bodies WHERE system=?", (id64,))}
        firsts = {r["body_id"]: r for r in self.db.execute(
            """SELECT f.body_id, f.was_discovered, f.was_mapped, f.was_footfalled, m.ts AS mapped_ts
               FROM own_firsts f LEFT JOIN own_mapped m ON m.system = f.system AND m.body_id = f.body_id
               WHERE f.system = ?""", (id64,))}
        genera = {}  # body_id -> genera your DSS found there (limits the guess to what is really present)
        for r in self.db.execute("SELECT body_id, genus_name FROM own_genera WHERE system=?", (id64,)):
            genera.setdefault(r["body_id"], []).append(r["genus_name"])
        done = {}   # body_id -> {genus: species value} for samples you hold (not lost)
        for r in self.db.execute("SELECT body_id, genus_name, species_name, done_ts FROM own_organic WHERE system=? AND done_ts IS NOT NULL", (id64,)):
            if organic_state(self.db, r["done_ts"]) != "lost":
                done.setdefault(r["body_id"], {})[r["genus_name"]] = (ed_bio.species_value(r["species_name"]) if ed_bio else 0) or 0
        now_c = self.system_values.get(name, 0)   # on board: the unsold estimate's own figure for this system
        rem_c = now_b = rem_b = 0
        judge = pickup_judge(self.db, name)
        latest = {r["body_id"]: r["ts"] for r in self.db.execute("SELECT body_id, ts FROM own_bodies WHERE system=?", (id64,))}
        for r in records:
            bid = own_ids.get(r["name"])
            f = firsts.get(bid) if bid is not None else None
            scan_state = judge(latest[bid])[0] if bid in latest else None
            map_state = judge(f["mapped_ts"])[0] if f and f["mapped_ts"] else None
            rem_c += carto_values(r, bid is not None, f, scan_state, map_state)["left"]   # same rules as Here
            if r.get("bio") or r.get("genera"):
                factor = 5 if f and f["was_footfalled"] == 0 else 1
                got = done.get(bid, {}) if bid is not None else {}
                now_b += sum(got.values()) * factor
                known = (genera.get(bid) if bid is not None else None) or r.get("genera") or None
                _, groups = bio_guess(r, star, known, ctx)
                rem_b += sum((g.get("value") or 0) for g in groups if g["genus"] not in got) * factor
        return {"value_now": int(now_c + now_b), "value_max": int(now_c + now_b + rem_c + rem_b),
                "value_parts": {"carto_now": int(now_c), "bio_now": int(now_b), "carto_left": int(rem_c), "bio_left": int(rem_b)}}

    def row(self, id64):
        """Page row for a system: its Spansh base merged with your own scans."""
        source, base = self.bases[id64]
        own, hotspots, own_count = own_data(self.db, id64, base["name"])
        records = merge_records(base.get("records") or [], own, hotspots)
        counts = [c for c in (base.get("body_count"), own_count) if c]
        star_row = self.db.execute("SELECT star_class FROM star_classes WHERE id64=?", (id64,)).fetchone()
        star = star_row["star_class"] if star_row else None
        ctx = bio_context(base["name"], records, base.get("x"), base.get("y"), base.get("z"), star)
        s = summarise(records, max(counts) if counts else None, star, ctx)
        s.update(id64=id64, id=str(id64), name=base["name"], source=source, in_spansh=source == "spansh",
                 visited=id64 in self.visited, distance=round(dist(self.center, base), 2),
                 own_scans=len(own), firsts=own_firsts(self.db, id64, base["name"]),
                 mapped=self.db.execute(
                     """SELECT count(*) FROM own_firsts f LEFT JOIN own_mapped m
                          ON m.system = f.system AND m.body_id = f.body_id
                        WHERE f.system = ? AND (f.was_mapped = 1 OR m.ts IS NOT NULL)""",
                     (id64,)).fetchone()[0])
        s.update(self.system_value(id64, base["name"], records, star, ctx))
        s["phenomena"] = [dict(r) for r in self.db.execute("SELECT kind, reached_ts FROM phenomena WHERE system=?", (id64,))]
        raws = {short_name(base["name"], r_["name"]): json.loads(r_["raw"]) for r_ in self.db.execute(
            "SELECT name, raw FROM own_bodies WHERE system=? AND raw IS NOT NULL", (id64,))}
        cur = system_curiosities(base["name"], records, raws)
        s["curiosity_list"] = [{"body": bn, "tag": t, "why": w} for bn, lst in cur.items() for t, w in lst]
        s["curiosities"] = len(s["curiosity_list"])
        if not s["bodies_known"]:
            s["status"] = "unreported" if source == "route" else "no bodies"
        elif s["body_count"] is None or s["bodies_known"] < s["body_count"]:
            s["status"] = "partial"
        else:
            s["status"] = "explored"
        if s["main_star"]:
            s["main_class"] = star_short(s["main_star"])
        else:
            # Nothing scanned: fall back to a star class seen in your own FSDTarget/NavRoute.
            row = self.db.execute("SELECT star_class FROM star_classes WHERE id64=?",
                                  (id64,)).fetchone()
            sc = (row["star_class"] if row else None) or base.get("star_class")
            s.update(main_star=sc, main_class=sc, main_scoopable=class_scoopable(sc) if sc else None)
        return s

    def set_row(self, id64):
        self.systems[id64] = self.row(id64)

    def maybe_classify_target(self):
        t = self.journals.target
        key = t and (t["id64"], t["ts"])
        if key == self.target_key:
            return
        self.target_key = key
        if not t:
            if self.target:
                self.last_target = self.target
            elif self.target_task and not self.target_task.done():
                self.last_target = None   # classify_target will fill it in when the lookup lands
            self.target = None
            self.bump()
            return
        # Keep a reference: asyncio only holds tasks weakly.
        self.target_task = asyncio.create_task(self.classify_target(t, key))

    async def classify_target(self, t, key):
        """Decide which sound a newly targeted system gets.

        fanfare  Spansh has never heard of it: a brand-new discovery
        upbeat   known, but not fully scanned
        thud     you've been there, or every body is already known
        """
        id64 = t["id64"]
        source = "spansh"
        visited = self.db.execute("SELECT 1 FROM visits WHERE id64=?", (id64,)).fetchone()
        if visited:
            status = "visited"
        elif id64 in self.systems and self.systems[id64]["source"] == "spansh":
            status = self.systems[id64]["status"]
        else:
            try:
                dump = await self.spansh.lookup(id64)
            except Exception:
                dump = False
            if dump is None or dump is False:
                # Spansh doesn't have it (or is down): EDSM is a separate database with its
                # own reporters, so it may still know the system exists.
                try:
                    e_sys = await self.spansh.edsm_system(t["name"])
                except Exception:
                    e_sys = False
                if e_sys:
                    status, source = "no bodies", "edsm"
                elif dump is None and e_sys is None:
                    status = "unreported"
                else:
                    status = "lookup failed"
            else:
                system = dump.get("system") or {}
                known = sum(1 for b in system.get("bodies") or [] if b.get("type") in ("Star", "Planet"))
                count = system.get("bodyCount")
                status = ("no bodies" if not known
                          else "explored" if count and known >= count else "partial")
        self.target_verdicts[id64] = status
        while len(self.target_verdicts) > 50:
            self.target_verdicts.pop(next(iter(self.target_verdicts)))
        if key != self.target_key:
            # A newer target, or we already arrived: no sound, but keep the verdict so the
            # arrival star can still be checked against it.
            pos = self.journals.pos
            if pos and pos["id64"] == id64 and self.last_target is None:
                self.last_target = dict(t, status=status, source=source)
                self.reconcile_arrival()
            return
        sound = {"unreported": "fanfare", "no bodies": "upbeat", "partial": "upbeat",
                 "explored": "thud", "visited": "thud"}.get(status)
        self.target_seq += 1
        self.target = dict(t, status=status, sound=sound, seq=self.target_seq,
                           fresh=key != self.startup_target_key, source=source,
                           leaving=self.leaving_summary(self.journals.pos["id64"]) if self.journals.pos else None)
        self.bump()

    def maybe_refresh(self):
        pos = self.journals.pos
        if not pos:
            return
        retry = False
        if self.center and self.center["id64"] == pos["id64"]:
            if not (self.retry_at and time.time() >= self.retry_at
                    and (not self.refresh_task or self.refresh_task.done())):
                return
            retry = True
        self.center = pos
        self.retry_at = None
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
        self.refresh_task = asyncio.create_task(self.refresh(pos, retry))

    def set_radius(self, r):
        """Change the Nearby sphere from the page: remembered in the database and fetched at once."""
        if r == self.radius:
            return
        self.radius = r
        meta_set(self.db, "radius_choice", r)
        self.db.commit()
        self.center = None          # forces a fresh Spansh sphere around where you are
        self.maybe_refresh()
        self.bump()

    def schedule_retry(self):
        delay = self.retry_backoff
        self.retry_at = time.time() + delay
        self.retry_backoff = min(self.retry_backoff * 2, 300)
        return int(delay)

    def near(self, table, pos, r):
        return self.db.execute(
            f"SELECT * FROM {table} WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?",
            (pos["x"] - r, pos["x"] + r, pos["y"] - r, pos["y"] + r, pos["z"] - r, pos["z"] + r))

    async def refresh(self, pos, retry=False):
        try:
            await self._refresh(pos, retry)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # anything else: say so on the page and try again later
            import traceback
            traceback.print_exc()
            delay = self.schedule_retry()
            self.status = f"refresh failed: {type(e).__name__}: {e} — retrying in {delay}s"
            self.bump()

    def dump_failed(self, id64, e):
        """A body-detail fetch failed: retry it later unless it has failed DUMP_MAX_TRIES times."""
        n = self.dump_tries[id64] = self.dump_tries.get(id64, 0) + 1
        if n == 1 or n == DUMP_MAX_TRIES:   # say why once, and again when giving up (not every retry)
            name = self.bases.get(id64, (None, {}))[1].get("name", id64)
            print(f"body details for {name} failed ({type(e).__name__}: {e})"
                  + (" - giving up until you move" if n >= DUMP_MAX_TRIES else ""), file=sys.stderr)
        if n < DUMP_MAX_TRIES:
            self.failed_dumps.add(id64)

    async def retry_dumps(self, pos):
        """Spansh's search worked but some body-detail fetches failed: fetch just those again."""
        ids = [i for i in self.failed_dumps if i in self.bases and self.bases[i][0] == "spansh"]
        self.failed_dumps = set()
        self.status = f"fetching body details again for {len(ids)} systems…"
        self.bump()
        failed = 0
        for id64 in ids:
            _, base = self.bases[id64]
            try:
                base = await self.spansh.full_records(id64, self.dump_updated.get(id64), base)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failed += 1
                self.dump_failed(id64, e)
                continue
            self.bases[id64] = ("spansh", base)
            self.set_row(id64)
            self.bump()
        if failed and self.failed_dumps:
            self.status = f"ok ({failed} body lookups failed again, retrying in {self.schedule_retry()}s)"
        elif failed:   # every failure has used up its tries: stop retrying, but say so
            self.status = f"ok ({failed} body lookups failed; giving up on them until you move)"
        else:
            self.retry_backoff = 30
            self.status = "ok"
        self.bump()

    async def _refresh(self, pos, retry=False):
        r = self.radius
        self.visited = {row[0] for row in self.db.execute("SELECT id64 FROM visits")}
        if retry and self.failed_dumps and self.status.startswith("ok ("):
            return await self.retry_dumps(pos)
        if not retry:
            self.bases, self.systems = {}, {}
        self.status = (f"asking Spansh again about systems near {pos['name']}…" if retry
                       else f"asking Spansh about systems near {pos['name']}…")
        self.bump()
        edsm, spansh_failed = [], None
        try:
            results = await self.spansh.sphere(pos, r)
            # a dense region (near the bubble or Colonia): Spansh has more than we fetch, so the list is
            # only complete out to the last system returned; say so rather than call it every system
            self.sphere_cut = round(results[-1]["distance"], 1) \
                if len(results) >= SPANSH_PAGE * SPANSH_MAX_PAGES and results else None
        except Exception as e:  # network trouble shouldn't kill the server
            spansh_failed = e
            results = []
            try:  # second opinion: EDSM's list has no body data but says what exists
                edsm = await self.spansh.edsm_sphere(pos, r)
            except Exception:
                pass
        if retry:
            self.bases, self.systems = {}, {}
        if spansh_failed:
            # What we already know about this neighbourhood is better than EDSM's bare list.
            cached_n = 0
            for row in self.near("spansh_systems", pos, r):
                b = json.loads(row["summary"])
                if b.get("v") == CACHE_VERSION and dist(pos, b) <= r:
                    self.bases[row["id64"]] = ("cache", b)
                    cached_n += 1
            delay = self.schedule_retry()
            self.status = (f"Spansh search failed ({spansh_failed}); showing {cached_n} cached systems"
                           f"{' plus EDSM’s list' if edsm else ''} — retrying in {delay}s")
        for d in edsm:
            if d.get("id64") and d.get("coords") and d["id64"] not in self.bases:
                self.bases[d["id64"]] = ("edsm", base_from_edsm(d))

        need_dump = []
        for s in results:
            if dist(pos, s) > r:
                continue
            id64 = s["id64"]
            base = base_from_search(s)
            cached_at, cached = self.spansh.cached(id64)
            if cached and cached_at == s.get("updated_at"):
                base = cached
            elif base["records"]:
                need_dump.append((id64, s.get("updated_at"), base))
            else:
                self.spansh.store(id64, s.get("updated_at"), base)
            self.bases[id64] = ("spansh", base)

        # Systems you've been to that Spansh doesn't have (e.g. your own fresh discoveries).
        for v in self.near("visits", pos, r):
            if v["id64"] not in self.bases and dist(pos, v) <= r:
                self.bases[v["id64"]] = ("own", {"name": v["name"], "x": v["x"], "y": v["y"],
                                                 "z": v["z"], "body_count": None, "records": []})
        # Systems from your own route plots that nobody has reported.
        for rs in self.near("route_systems", pos, r):
            if rs["id64"] not in self.bases and dist(pos, rs) <= r:
                self.bases[rs["id64"]] = ("route", {"name": rs["name"], "x": rs["x"], "y": rs["y"],
                                                    "z": rs["z"], "body_count": None, "records": [],
                                                    "star_class": rs["star_class"]})
        for id64 in self.bases:
            self.set_row(id64)

        if not spansh_failed:
            self.status = (f"fetching body details for {len(need_dump)} systems…"
                           if need_dump else "ok")
            if not need_dump:
                self.retry_backoff = 30
        self.bump()

        # Nearest first, so the rows you care about fill in soonest.
        need_dump.sort(key=lambda t: self.systems[t[0]]["distance"])
        failed = 0
        self.failed_dumps = set()
        self.dump_updated = {i: u for i, u, _ in need_dump}   # Spansh's updated_at, kept for retries
        self.dump_tries = {}

        async def one(id64, updated_at, base):
            nonlocal failed
            try:
                base = await self.spansh.full_records(id64, updated_at, base)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failed += 1
                self.dump_failed(id64, e)
                return
            self.bases[id64] = ("spansh", base)
            self.set_row(id64)
            self.bump()

        await asyncio.gather(*(one(*t) for t in need_dump))
        if need_dump:
            if failed and self.failed_dumps:
                self.status = f"ok ({failed} body lookups failed, retrying in {self.schedule_retry()}s)"
            elif failed:
                self.status = f"ok ({failed} body lookups failed; giving up on them until you move)"
            else:
                self.retry_backoff = 30
                self.status = "ok"
            self.bump()

    def reconcile_arrival(self):
        """Check the sound we played for a target against the arrival star's WasDiscovered."""
        scan, t, pos = self.journals.arrival_scan, self.last_target, self.journals.pos
        if not (scan and pos) or pos["id64"] != scan["id64"]:
            return
        if self.arrival and self.arrival["ts"] == scan["ts"]:
            return
        # what was announced when this system was targeted (a plotted route has already targeted the next
        # hop by now, so the current target is no guide); a jump nobody announced still gets its verdict
        t = t if t and t["id64"] == scan["id64"] else None
        announced = self.target_verdicts.get(scan["id64"]) or (t or {}).get("status")
        expected_new = announced == "unreported"
        actually_new = not scan["was_discovered"]
        self.arrival_seq += 1
        self.arrival = {"name": pos.get("name") or (t or {}).get("name"), "id64": str(scan["id64"]),
                        "ts": scan["ts"], "seq": self.arrival_seq,
                        "announced": announced, "undiscovered": actually_new,
                        # your own unsold discovery still reads as undiscovered: only the first visit is news
                        "first_visit": self.visit_count(scan["id64"]) <= 1,
                        "wrong": bool(announced) and expected_new != actually_new,
                        # sounds belong to targeting: on arrival only a wrong call is corrected (a thud for
                        # a fanfare that was not deserved, the fanfare for a surprise); the voice does the rest
                        "sound": None if not announced
                                 else "thud" if expected_new and not actually_new
                                 else "fanfare" if actually_new and not expected_new
                                 and self.visit_count(scan["id64"]) <= 1 else None}
        self.bump()

    # ---- auto honk ----
    def autohonk_info(self):
        h = self.honker
        return {"available": bool(h and h.available), "enabled": bool(self.autohonk["enabled"] and h and h.ready),
                "wanted": bool(self.autohonk["enabled"]), "status": h.status if h else "not started",
                "key": self.autohonk["key"], "hold": self.autohonk["hold"], "announce": bool(self.autohonk.get("announce", True)),
                "pressing": (h.combo()[1] if h and h.available else None)}

    def set_autohonk(self, enabled):
        """Switch auto honk on or off (the page's toggle; remembered over restarts)."""
        self.autohonk["enabled"] = bool(enabled)
        meta_set(self.db, "autohonk_enabled", bool(enabled))
        if self.honker:
            if enabled:
                self.honker.open()
            else:
                self.honker.close()
                self.honker.status = "off"
        self.bump()

    def maybe_honk(self):
        """A live hyperspace arrival: hold Primary Fire (after `delay`), unless you honked here before."""
        a = self.journals.jump_arrival
        if not a or a is self._honk_arrival:
            return
        self._honk_arrival = a
        if not (self.autohonk["enabled"] and self.honker and self.honker.ready):
            return
        if time.time() - ts_seconds(a["ts"]) > AUTOHONK_MAX_AGE:
            return   # catching up on journals, not a jump happening now
        if self.autohonk["skip_honked"] and self.db.execute(
                "SELECT 1 FROM own_systems WHERE id64=?", (a["id64"],)).fetchone():
            return
        asyncio.get_running_loop().create_task(self.honk_task(a))

    async def honk_task(self, a):
        honked = lambda: (self.journals.last_honk or {}).get("id64") == a["id64"] \
            and self.journals.last_honk["ts"] >= a["ts"]
        await asyncio.sleep(self.autohonk["delay"])
        if honked():
            return   # you beat it to it
        if self.journals.jump_arrival is not a:
            return   # already somewhere else
        try:
            await asyncio.get_running_loop().run_in_executor(None, self.honker.press)
        except ValueError as e:   # nothing to press: Primary Fire has no keyboard binding, say
            self.journals.moment("honk", a["ts"], ok=False, system=a["name"], why=str(e))
            self.bump()
            return
        except Exception as e:  # noqa: BLE001 -- say so on the page rather than die quietly
            self.journals.moment("honk", a["ts"], ok=False, system=a["name"], why=f"{type(e).__name__}: {e}")
            self.bump()
            return
        deadline = time.time() + self.honk_confirm   # the journal confirms a discovery scan within a few seconds
        while not honked() and time.time() < deadline:
            await asyncio.sleep(0.1)
        info, all_found = self.journals.last_honk or {}, False
        if honked():   # a honk that finds everything is followed by FSSAllBodiesFound (a lone star, say)
            found = lambda: (self.journals.last_all_found or {}).get("id64") == a["id64"] \
                and self.journals.last_all_found["ts"] >= a["ts"] or (info.get("progress") or 0) >= 0.999
            end = time.time() + min(1.5, self.honk_confirm)
            while not (all_found := found()) and time.time() < end:
                await asyncio.sleep(0.1)
        self.journals.moment("honk", a["ts"], ok=honked(), system=a["name"],
                             bodies=info.get("bodies") if honked() else None, all_found=all_found,
                             why="" if honked() else "no discovery scan followed: is the D-Scanner on primary fire?")
        self.bump()

    def apply_own_changes(self):
        """Re-merge rows whose systems you just scanned, so the page updates as you go."""
        self.maybe_honk()
        self.reconcile_arrival()
        dirty, self.journals.dirty = self.journals.dirty, set()
        if self.journals.sales_changed:
            self.journals.sales_changed = False
            dirty |= set(self.bases)
            self.note_sale_estimates()
        changed = False
        for id64 in dirty:
            if id64 in self.bases:
                try:
                    if self.db.execute("SELECT 1 FROM visits WHERE id64=?", (id64,)).fetchone():
                        self.visited.add(id64)
                    self.set_row(id64)
                    changed = True
                except Exception as e:  # one bad system must not stall the others
                    import traceback
                    traceback.print_exc()
                    self.tail_error = f"{type(e).__name__} while updating {id64}: {e}"
        bio_sold = self.journals.bio_sales_changed
        if bio_sold:
            self.journals.bio_sales_changed = False
            pos = self.journals.pos
            if pos and pos["id64"] in self.bases:
                dirty.add(pos["id64"])
        if changed or dirty or bio_sold:   # a sale changes the Samples view even far from any row
            self.scan_version += 1
            self.bump()
        if self.journals.materials_changed or self.journals.cmdr_changed:
            if self.journals.materials_changed:
                self.materials_version += 1
            self.journals.materials_changed = self.journals.cmdr_changed = False
            self.bump()

    # ---- 3D map ----

    async def boost_points(self, pos, radius):
        """Neutron stars and white dwarfs (as arrival stars) within radius, for jet-cone boosting."""
        key = ("boost", pos["id64"], radius)
        if key in self.map_cache:
            return self.map_cache[key]
        filters = {"subtype": {"value": BOOST_STARS}, "is_main_star": {"value": True}}
        try:
            bodies, cut = await self.spansh.body_search(filters, pos, radius, 2)
        except Exception as e:
            return {"points": [], "complete_to": None, "error": f"boost-star lookup failed: {e}"}
        out = {}
        for b in bodies:
            out[b["system_id64"]] = {"name": b["system_name"], "x": b["system_x"], "y": b["system_y"],
                                     "z": b["system_z"], "id": str(b["system_id64"]),
                                     "boost": "N" if b.get("subtype") == "Neutron Star" else "D",
                                     "distance": round(dist(pos, {"x": b["system_x"], "y": b["system_y"],
                                                                  "z": b["system_z"]}), 2)}
        res = {"points": sorted(out.values(), key=lambda p: p["distance"]), "complete_to": cut}
        self.map_cache[key] = res
        return res

    async def map_payload(self, radius, path_len, boost=False):
        """Every system within radius for the map: Spansh's plus your visits and route plots."""
        pos = self.journals.pos
        if not pos:
            return {"error": "no current position yet"}
        key = (pos["id64"], radius)
        note = None
        if key not in self.map_cache:
            failed = False
            try:
                results = await self.spansh.sphere(pos, radius, MAP_MAX_PAGES)
            except Exception as e:
                results, note, failed = [], f"Spansh lookup failed: {e}", True
            if len(results) >= SPANSH_PAGE * MAP_MAX_PAGES:
                note = (f"Spansh has more systems in range than the map fetches; showing the nearest "
                        f"{len(results):,} (out to {results[-1]['distance']:.0f} ly)")
            known = {}
            for r in results:
                bodies = [b for b in r.get("bodies") or [] if b.get("type") in ("Star", "Planet")]
                main = next((b for b in bodies if b.get("is_main_star")), None)
                known[r["id64"]] = {"name": r["name"], "x": r["x"], "y": r["y"], "z": r["z"],
                                    "scanned": bool(bodies),
                                    "star": star_short(main.get("subtype")) if main else None}
            if len(self.map_cache) > 4:
                self.map_cache.clear()
            if not failed:
                self.map_cache[key] = (known, note)
        else:
            known, note = self.map_cache[key]

        points = {}
        for id64, k in known.items():
            points[id64] = dict(k, kind="known")
        for v in self.near("visits", pos, radius):
            points.setdefault(v["id64"], {"name": v["name"], "x": v["x"], "y": v["y"], "z": v["z"],
                                          "kind": "own", "scanned": True})["visited"] = True
        for rs in self.near("route_systems", pos, radius):
            points.setdefault(rs["id64"], {"name": rs["name"], "x": rs["x"], "y": rs["y"], "z": rs["z"],
                                           "kind": "route", "scanned": False})
        firsts = {r[0] for r in self.db.execute(
            "SELECT DISTINCT system FROM own_firsts WHERE is_main = 1 AND was_discovered = 0")}
        classes = dict(self.db.execute("SELECT id64, star_class FROM star_classes").fetchall())
        out = []
        for id64, pt in points.items():
            d = dist(pos, pt)
            if d > radius:
                continue
            out.append(dict(pt, id=str(id64), distance=round(d, 2), visited=bool(pt.get("visited")),
                            first=id64 in firsts, star=pt.get("star") or classes.get(id64)))
        path = [dict(r) for r in self.db.execute(
            "SELECT ts, id64, name, x, y, z, star_class, kind FROM jumps ORDER BY ts DESC LIMIT ?",
            (path_len,))][::-1]
        for j in path:
            j["id"] = str(j.pop("id64"))
        boosts = await self.boost_points(pos, radius) if boost else None
        return {"center": pos, "radius": radius, "points": out, "note": note, "path": path,
                "boost": boosts, "here_star": self.here_star(),
                "jump_range": (self.journals.jump_range or {}).get("ly"),
                "carrier": self.carrier_summary()}

    def maybe_locate_carrier(self):
        c = self.journals.carrier
        if not c or not c.get("id64") or c.get("x") is not None or self.locate(c["id64"]):
            return
        if self.carrier_task and not self.carrier_task.done():
            return

        async def go():
            try:
                dump = await self.spansh.lookup(c["id64"])
            except Exception:
                return
            co = ((dump or {}).get("system") or {}).get("coords") or {}
            if "x" in co:
                c.update(x=co["x"], y=co["y"], z=co["z"])
                meta_set(self.db, "carrier", c)
                self.bump()
        self.carrier_task = asyncio.create_task(go())

    def maybe_find_sellers(self):
        """Keep the nearest Universal Cartographics / Vista Genomics stations known (Spansh), refreshed after
        SELLER_REFRESH_LY of travel or SELLER_REFRESH_S. One small request per service."""
        pos = self.journals.pos
        if not pos or (self.seller_task and not self.seller_task.done()):
            return
        cur = meta_get(self.db, "sellers")
        if cur and dist(pos, cur["pos"]) < SELLER_REFRESH_LY and time.time() - cur["fetched"] < SELLER_REFRESH_S:
            return
        if self.seller_retry_at and time.time() < self.seller_retry_at:
            return

        async def go():
            try:
                uc = await self.spansh.stations("Universal Cartographics", pos)
                vista = await self.spansh.stations("Vista Genomics", pos)
            except Exception as e:
                self.seller_retry_at = time.time() + 600
                print(f"nearest sellers lookup failed ({type(e).__name__}: {e}); trying again in 10 min", file=sys.stderr)
                return
            meta_set(self.db, "sellers", {"pos": {k: pos[k] for k in ("x", "y", "z", "name")}, "fetched": time.time(),
                                          "uc": uc, "vista": vista})
            self.db.commit()
            self.bump()
        self.seller_task = asyncio.create_task(go())

    def route_summary(self):
        """The plotted route from where you are: each hop's star (scoopable or not), whether you have been
        there, and the longest stretch without a scoopable star (where fuel runs out)."""
        route, pos = meta_get(self.db, "route"), self.journals.pos
        if not route or not pos:
            return None
        hops = route["hops"]
        i = next((k for k, h in enumerate(hops) if h["id64"] == pos["id64"]), None)
        left = hops[i + 1:] if i is not None else hops
        if not left:
            return None
        visited = {r[0] for r in self.db.execute(
            f"SELECT id64 FROM visits WHERE id64 IN ({','.join('?' * len(left))})", [h["id64"] for h in left])}
        out, prev, dry, longest, total = [], pos, 0, 0, 0.0
        for h in left:
            d = dist(prev, h)
            total += d
            scoop = class_scoopable(h["star_class"]) if h.get("star_class") else None
            dry = 0 if scoop else dry + 1
            longest = max(longest, dry)
            known = h["id64"] in self.systems or bool(self.spansh.cached(h["id64"])[1]) if self.spansh else False
            out.append({"id": str(h["id64"]), "name": h["name"], "star_class": h.get("star_class"), "scoopable": scoop,
                        "ly": round(d, 1), "visited": h["id64"] in visited, "known": known})
            prev = h
        next_scoop = next((k + 1 for k, h in enumerate(out) if h["scoopable"]), None)
        return {"hops": out, "ly": round(total, 1), "longest_dry": longest, "next_scoop": next_scoop, "ts": route.get("ts")}

    def next_stop_summary(self):
        ns, pos = meta_get(self.db, "next_stop"), self.journals.pos
        if not ns:
            return None
        return dict(ns, id=str(ns["id64"]), distance=round(dist(pos, ns), 1) if pos else None)

    def set_next_stop(self, id64):
        """Make a system (a bookmark, usually) the next stop: its distance shows in the header until you arrive."""
        if id64 is None:
            meta_set(self.db, "next_stop", None)
        else:
            where = self.locate(id64)
            if not where:
                return False
            meta_set(self.db, "next_stop", {"id64": id64, "name": where[0], "x": where[1], "y": where[2], "z": where[3]})
        self.db.commit()
        self.bump()
        return True

    def sellers_summary(self):
        """Nearest places to sell from here: the nearest of each kind, preferring fresh entries (a carrier
        seen by Spansh weeks ago may be long gone), and the nearest permanent station."""
        cur, pos = meta_get(self.db, "sellers"), self.journals.pos
        if not cur or not pos:
            return None
        c = self.journals.carrier or {}
        def pick(lst):
            now = time.time()
            out = []
            for x in lst:
                if x.get("x") is not None:   # from where you are now, not where the list was fetched
                    x = dict(x, distance=round(dist(pos, x), 1))
                age = (now - ts_seconds(x["updated_at"])) / 86400 if x.get("updated_at") else None
                x["age_days"] = round(age, 1) if age is not None else None
                x["carrier"] = "Carrier" in (x.get("type") or "")
                x["yours"] = bool(c.get("callsign") and x.get("name") == c.get("callsign"))
                out.append(x)
            out.sort(key=lambda x: x["distance"])
            fresh = next((x for x in out if x["yours"] or not x["carrier"] or (x["age_days"] or 99) <= 14), None)
            station = next((x for x in out if not x["carrier"]), None)
            return {"nearest": out[0] if out else None, "fresh": fresh, "station": station}
        return {"from": cur["pos"].get("name"), "moved": round(dist(pos, cur["pos"]), 1),
                "uc": pick(cur["uc"]), "vista": pick(cur["vista"])}

    def maybe_unsold(self):
        """Re-estimate unsold data in a worker thread once the journal has settled a little."""
        if not self.unsold_dirty or time.time() - self.unsold_at < UNSOLD_MIN_SECONDS:
            return
        if self.unsold_task and not self.unsold_task.done():
            return
        self.unsold_dirty, self.unsold_at = False, time.time()

        async def run():
            try:
                self.unsold = await asyncio.get_running_loop().run_in_executor(None, compute_unsold)
                self.system_values = self.unsold.pop("system_values", {})
                self.journals.dirty |= set(self.bases)   # rows carry per-system values: rebuild them
            except (Exception, SystemExit) as e:  # read_events() fails if it finds no journals
                self.unsold = {"error": str(e)}
            self.bump()
        self.unsold_task = asyncio.create_task(run())

    async def watch(self):
        """Tail the live journals and NavRoute.json forever."""
        route_mtimes = {}
        while True:
            try:
                for d in LIVE_DIRS:
                    if self.journals.scan_dir(d):
                        self.unsold_dirty = True
                    nr = os.path.join(d, "NavRoute.json")
                    try:
                        m = os.path.getmtime(nr)
                    except OSError:
                        m = None
                    if m and route_mtimes.get(nr) != m:
                        route_mtimes[nr] = m
                        self.journals.read_navroute(d)
                    sj = os.path.join(d, "Status.json")
                    try:
                        m = os.path.getmtime(sj)
                    except OSError:
                        m = None
                    if m and route_mtimes.get(sj) != m:
                        route_mtimes[sj] = m
                        before = self.journals.status_json
                        self.journals.read_status(d)
                        gist = lambda st: st and (round(st.get("fuel_main") or 0, 1), st.get("flags"), st.get("flags2"),
                                                  st.get("body"), json.dumps(st.get("destination")), st.get("live"))
                        if gist(self.journals.status_json) != gist(before):
                            self.bump()
                        sm = self.sampling_summary()
                        skey = sm and (sm["clear"], (sm["to_go"] or 0) // 10, sm["samples"])
                        if skey != self._sampling_key:   # walking away from a sample: keep the countdown moving
                            self._sampling_key = skey
                            self.bump()
                self.db.commit()
                self.maybe_refresh()
                self.apply_own_changes()
                self.maybe_classify_target()
                self.maybe_unsold()
                self.maybe_locate_carrier()
                self.maybe_find_sellers()
                if self.tail_error:
                    self.tail_error = None
                    self.bump()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Never let one bad line, a locked database or a malformed NavRoute stop the
                # tailing for good: report it on the page and try again next tick.
                import traceback
                traceback.print_exc()
                try:
                    self.db.rollback()
                    self.journals.reload()   # memory back to what the database holds, so the retry is exact
                except sqlite3.Error:
                    pass
                self.tail_error = f"{type(e).__name__}: {e}"
                self.bump()
            await asyncio.sleep(POLL_SECONDS)


def compute_unsold():
    """ed_unsold's estimate of the cartographic and exobiology data on board, trimmed for the page."""
    args = argparse.Namespace(commander=None, since=None, ignore_deaths=False, bonus_rate=None,
                              efficiency_bonus=False, no_odyssey=False, top=0)
    result = ed_unsold.analyse(ed_unsold.read_events(LIVE_DIRS + LEGACY_DIRS), args)
    ex, bio = result["exploration"], result["exobiology"]
    total = ex["estimated_payout"] + bio["estimated_value"]
    system_values = {}
    for r in ex["rows"]:
        system_values[r["system"]] = system_values.get(r["system"], 0) + r["value"]
    return {
        "carto": {k: ex[k] for k in ("estimated_value", "estimated_payout", "payout_ratio", "payout_note", "npc_crew",
                                     "bodies", "systems", "first_discoveries", "mapped", "last_sold", "cutoff")},
        "system_values": system_values,
        "bio": {k: bio[k] for k in ("estimated_value", "base_value", "max_value", "samples",
                                    "bonus_rate", "bonus_rate_source", "unknown_species",
                                    "last_sold", "cutoff")},
        "species": [{"species": r["species"], "count": r["count"], "value": r["value"]}
                    for r in bio["rows"][:8]],
        # the ten most valuable bodies aboard: the finds of this trip
        "top_bodies": [{"body": r["body"], "system": r["system"], "type": r["type"], "value": r["value"],
                        "first_discovered": r["first_discovered"], "mapped": r.get("mapped")}
                       for r in sorted(ex["rows"], key=lambda r: -r["value"])[:10]],
        "firsts": {
            "systems": sum(1 for r in ex["rows"] if r["first_discovered"] and r.get("arrival")),
            "stars": sum(1 for r in ex["rows"] if r["first_discovered"] and r.get("star")),
            "planets": sum(1 for r in ex["rows"] if r["first_discovered"] and r.get("planet")),
            "mapped": sum(1 for r in ex["rows"] if r.get("first_mapped")),
        },
        "total": total,
        "level": "urgent" if total >= UNSOLD_URGENT else "warn" if total >= UNSOLD_WARN else "ok",
        "thresholds": [UNSOLD_WARN, UNSOLD_URGENT],
        "computed": time.strftime("%H:%M:%S"),
    }


# --------------------------------------------------------------------------
# Search: systems within a radius that have given stars, planets, rings or hotspots
# --------------------------------------------------------------------------

_SCOOP = [
    ("O", ["O (Blue-White) Star"]),
    ("B", ["B (Blue-White) Star", "B (Blue-White super giant) Star"]),
    ("A", ["A (Blue-White) Star", "A (Blue-White super giant) Star"]),
    ("F", ["F (White) Star", "F (White super giant) Star"]),
    ("G", ["G (White-Yellow) Star", "G (White-Yellow super giant) Star"]),
    ("K", ["K (Yellow-Orange) Star", "K (Yellow-Orange giant) Star"]),
    ("M", ["M (Red dwarf) Star", "M (Red giant) Star", "M (Red super giant) Star"]),
]
_OTHER_STARS = [
    ("wd", "White dwarf", [f"White Dwarf ({c}) Star" for c in
                           ("D", "DA", "DAB", "DAZ", "DAV", "DB", "DBZ", "DBV", "DQ", "DC", "DCV")]),
    ("n", "Neutron star", ["Neutron Star"]),
    ("bh", "Black hole", ["Black Hole", "Supermassive Black Hole"]),
    ("bd", "Brown dwarf (L/T/Y)", ["L (Brown dwarf) Star", "T (Brown dwarf) Star", "Y (Brown dwarf) Star"]),
    ("tts", "T Tauri", ["T Tauri Star"]),
    ("aebe", "Herbig Ae/Be", ["Herbig Ae/Be Star"]),
    ("wr", "Wolf-Rayet", ["Wolf-Rayet Star", "Wolf-Rayet N Star", "Wolf-Rayet NC Star",
                          "Wolf-Rayet C Star", "Wolf-Rayet O Star"]),
    ("c", "Carbon star", ["C Star", "CN Star", "CJ Star"]),
    ("ms", "MS / S-type", ["MS-type Star", "S-type Star"]),
]
STAR_GROUPS = {k: v for k, v in _SCOOP} | {k: v for k, _, v in _OTHER_STARS}
PLANET_TYPES = [
    "Earth-like world", "Water world", "Ammonia world", "Metal-rich body", "High metal content world",
    "Rocky body", "Rocky Ice world", "Icy body", "Water giant", "Gas giant with water-based life",
    "Gas giant with ammonia-based life", "Class I gas giant", "Class II gas giant", "Class III gas giant",
    "Class IV gas giant", "Class V gas giant", "Helium-rich gas giant", "Helium gas giant",
]
RING_TYPES = ["Icy", "Rocky", "Metal Rich", "Metallic"]

# Exobiology you have not finished sampling, by what the rest could pay (plain Vista Genomics prices,
# no first-footfall x5): key -> (label, credits threshold).
BIO_SEARCH = {"any": ("Unscanned bio signals", 0), "1m": ("Unscanned bio signals, > 1 mil", 1_000_000),
              "5m": ("Unscanned bio signals, > 5 mil", 5_000_000), "10m": ("Unscanned bio signals, > 10 mil", 10_000_000)}

SEARCH_OPTIONS = {
    "scoopable": [k for k, _ in _SCOOP],
    "other_stars": [[k, label] for k, label, _ in _OTHER_STARS],
    "planets": PLANET_TYPES, "rings": RING_TYPES, "hotspots": HOTSPOT_MINERALS,
    "bio": [[k, label] for k, (label, _) in BIO_SEARCH.items()],
}

SEARCH_MAX_RADIUS = {"local": 5000, "spansh": 500}
SEARCH_PAGES_PER_QUERY = 6        # 3000 bodies per Spansh query before we call it truncated
SEARCH_MAX_RESULTS = 1000


def record_from_body_search(b):
    """A Spansh /bodies/search result -> body record (with what the exobiology rules can use: the
    search leaves out volcanism, so species guesses from it are broader than from a full dump)."""
    rings = []
    for r in b.get("rings") or []:
        rings.append({"name": short_name(b.get("name"), r.get("name")), "type": r.get("type"),
                      "hotspots": minerals({s["name"]: s["count"] for s in r.get("signals") or []})})
    st = b.get("subtype")
    signals = {s.get("name"): s.get("count", 0) for s in b.get("signals") or []}
    return {"name": short_name(b.get("system_name"), b.get("name")), "type": b.get("type"),
            "subtype": st, "main": bool(b.get("is_main_star")), "main_known": True, "scoopable": subtype_scoopable(st),
            "rings": rings, "full": True,
            "bio": signals.get("Biological", 0), "geo": signals.get("Geological", 0),
            "body_id": b.get("body_id"), "landable": bool(b.get("is_landable")),
            "gravity": b.get("gravity"), "atmosphere": b.get("atmosphere"), "temperature": b.get("surface_temperature"),
            "pressure": b.get("surface_pressure"), "dist_ls": b.get("distance_to_arrival"),
            # the search names parent stars directly ([{type, subtype, id64}]) rather than by body id
            "parent_star_types": [p.get("subtype") for p in b.get("parents") or [] if p.get("type") == "Star" and p.get("subtype")],
            "orbital_period_s": round(b["orbital_period"] * 86400) if b.get("orbital_period") else None,
            "atmo_comp": ({a.get("name"): a.get("share") for a in b["atmosphere_composition"]}
                          if isinstance(b.get("atmosphere_composition"), list) else b.get("atmosphere_composition")),
            "materials": surface_materials(b.get("materials"))}


def bio_hits(db, id64, system, x, y, z, records, threshold):
    """Bodies in a system with exobiology you have not finished, worth at least `threshold` for what is
    left (plain prices, no x5). A body the rules cannot price only counts when threshold is 0."""
    got, genera = {}, {}
    for r in db.execute("SELECT body_id, genus_name, done_ts FROM own_organic WHERE system=? AND done_ts IS NOT NULL", (id64,)):
        if organic_state(db, r["done_ts"]) != "lost":
            got.setdefault(r["body_id"], set()).add(r["genus_name"])
    for r in db.execute("SELECT body_id, genus_name FROM own_genera WHERE system=?", (id64,)):
        genera.setdefault(r["body_id"], []).append(r["genus_name"])
    row = db.execute("SELECT star_class FROM star_classes WHERE id64=?", (id64,)).fetchone()
    star = row["star_class"] if row else None
    ctx = bio_context(system, records, x, y, z, star)
    hits = []
    for r in records:
        bid = r.get("body_id")
        known = genera.get(bid) or r.get("genera") or []
        signals = r.get("bio") or len(known)
        if r.get("type") != "Planet" or not signals:
            continue
        done = got.get(bid, set())
        left_n = signals - len(done)
        if left_n <= 0:
            continue                      # every species here analysed
        _, groups = bio_guess(r, star, known or None, ctx)
        priced = [g for g in groups if g["genus"] not in done and g.get("value")]
        left = sum(g["value"] for g in priced) if priced else None
        if (left or 0) < threshold or (left is None and threshold):
            continue
        hits.append((left or 0, {"t": f"{r['name']} · {left_n} of {signals} unscanned"
                                 + (f" · up to {left / 1e6:.1f}M" if left else " · value unknown"), "body": r["name"]}))
    return [h for _, h in sorted(hits, key=lambda t: -t[0])]


def match_system(system, records, crit):
    """Which of the ticked criteria this system satisfies: {section: [descriptions]}."""
    stars = [r for r in records if r["type"] == "Star"]
    out = {}
    if crit["stars"]:
        hits = []
        for r in stars:
            # a lone star is the arrival star, unless the record says otherwise (online search results
            # carry only the bodies that matched, so a lone secondary must not be called the arrival)
            is_main = r.get("main") or (len(stars) == 1 and not r.get("main_known"))
            if r["subtype"] in crit["stars"] and (is_main or not crit["main_only"]):
                label = "arrival star" if r["name"] == system else r["name"]
                hits.append({"t": f"{label} · {r['subtype']}" + (" (arrival)" if is_main and r["name"] != system else ""),
                             "body": r["name"]})
        if hits:
            out["stars"] = hits
    if crit["planets"]:
        hits = [{"t": f"{r['name']} · {r['subtype']}", "body": r["name"]} for r in records
                if r["type"] == "Planet" and r["subtype"] in crit["planets"]]
        if hits:
            out["planets"] = hits
    if crit["rings"]:
        hits = [{"t": f"{r['name']} {x['name']} · {x['type']}", "body": r["name"]} for r in records
                for x in r.get("rings") or [] if x["type"] in crit["rings"]]
        if hits:
            out["rings"] = hits
    if crit["hotspots"]:
        hits = []
        for r in records:
            for x in r.get("rings") or []:
                found = {m: n for m, n in minerals(x.get("hotspots")).items() if m in crit["hotspots"]}
                if found:
                    hits.append({"t": f"{r['name']} {x['name']} ({x['type']}): " +
                                 ", ".join(f"{m} {n}" for m, n in sorted(found.items(), key=lambda kv: -kv[1])),
                                 "body": r["name"]})
        if hits:
            out["hotspots"] = hits
    return out


class Searcher:
    def __init__(self, state):
        self.state, self.db, self.spansh = state, state.db, state.spansh
        self.seq = 0
        self.task = None
        self.found = {}            # id64 -> (name, x, y, z) for bookmarking results
        self.result = {"seq": 0, "running": False, "status": "", "results": [], "params": None}

    def start(self, params):
        if self.task and not self.task.done():
            self.task.cancel()
        self.seq += 1
        self.result = {"seq": self.seq, "running": True, "status": "searching…",
                       "results": [], "params": params}
        self.task = asyncio.create_task(self.run(self.seq, params))

    def update(self, seq, **kw):
        if seq != self.seq:
            return
        if not self.result.get("running") and "running" not in kw:
            return  # a late progress message from a sibling of a failed query
        self.result.update(kw)

    async def run(self, seq, params):
        try:
            await self._run(seq, params)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.update(seq, running=False, status=f"search failed: {e}")

    async def _run(self, seq, params):
        pos = self.state.journals.pos
        if not pos:
            return self.update(seq, running=False, status="no current position yet")
        source = "spansh" if params.get("source") == "spansh" else "local"
        radius = max(1.0, min(float(params.get("radius") or 100), SEARCH_MAX_RADIUS[source]))
        crit = {
            "stars": {st for k in params.get("stars") or [] for st in STAR_GROUPS.get(k, [])},
            "main_only": bool(params.get("main_only", True)),
            "planets": set(params.get("planets") or []) & set(PLANET_TYPES),
            "rings": set(params.get("rings") or []) & set(RING_TYPES),
            "hotspots": set(params.get("hotspots") or []) & set(HOTSPOT_MINERALS),
            # ticked bio thresholds are OR'd like any other section: the lowest one decides
            "bio": min((BIO_SEARCH[k][1] for k in params.get("bio") or [] if k in BIO_SEARCH), default=None),
        }
        sections = [k for k in ("stars", "planets", "rings", "hotspots", "bio") if crit[k] is not None and crit[k] != set()]
        if not sections:
            return self.update(seq, running=False, status="tick at least one star, planet, ring, hotspot or exobiology option")

        if source == "local":
            systems, coverage = self.local(pos, radius), radius
            n = sum(1 for *_, recs in systems.values() if recs)
            n_rings = sum(1 for *_, recs in systems.values() if any(r.get("rings") for r in recs))
            n_hot = sum(1 for *_, recs in systems.values()
                        if any(minerals(x.get("hotspots")) for r in recs for x in r.get("rings") or []))
            note = (f"searched {n} system{'s' if n != 1 else ''} with body data ({n_rings} with ring data, "
                    f"{n_hot} with mapped hotspots); the local database only holds systems you've visited or "
                    f"passed within {self.state.radius:g} ly of — Spansh (online) covers everything reported")
            sparse = bool(sections) and (("hotspots" in sections and n_hot < 5) or ("rings" in sections and n_rings < 10) or n < 20)
        else:
            systems, coverage, note = await self.online(seq, pos, radius, crit)

        visited = {r[0] for r in self.db.execute("SELECT id64 FROM visits")}
        results = []
        for id64, (name, x, y, z, records) in systems.items():
            d = dist(pos, {"x": x, "y": y, "z": z})
            if d > coverage:
                continue
            m = match_system(name, records, crit)
            if crit["bio"] is not None and all(k in m for k in sections if k != "bio"):
                # price from the fullest record we have: a cached Spansh dump plus your scans beats the
                # search result (which lacks volcanism and the system's stars)
                bio_recs = records if source == "local" else (self.local_records(id64, name) or records)
                hits = bio_hits(self.db, id64, name, x, y, z, bio_recs, crit["bio"])
                if hits:
                    m["bio"] = hits
            if all(k in m for k in sections):
                results.append({"id": str(id64), "name": name, "distance": round(d, 2),
                                "visited": id64 in visited, "matches": m,
                                "firsts": own_firsts(self.db, id64, name) if id64 in visited else None})
                self.found[id64] = (name, x, y, z)
        results.sort(key=lambda r: r["distance"])
        total = len(results)
        where = "your local database" if source == "local" else "Spansh"
        status = (f"{total} system{'s' if total != 1 else ''} within {coverage:g} ly of {pos['name']}"
                  f" ({where})")
        if total > SEARCH_MAX_RESULTS:
            status += f", showing the nearest {SEARCH_MAX_RESULTS}"
        if note:
            status += " · " + note
        self.update(seq, running=False, status=status, results=results[:SEARCH_MAX_RESULTS],
                    radius=coverage, source=source, origin=pos["name"], sparse=locals().get("sparse", False))

    def local(self, pos, r):
        """Every system in the database within r: cached Spansh data merged with your own scans."""
        box = (pos["x"] - r, pos["x"] + r, pos["y"] - r, pos["y"] + r, pos["z"] - r, pos["z"] + r)
        found = {}
        for row in self.db.execute(
                "SELECT id64, summary FROM spansh_systems WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? "
                "AND z BETWEEN ? AND ?", box):
            b = json.loads(row["summary"])
            if b.get("records") is not None:  # any cache layout that carries body records is searchable
                found[row["id64"]] = (b["name"], b["x"], b["y"], b["z"], b.get("records") or [])
        for v in self.db.execute(
                "SELECT id64, name, x, y, z FROM visits WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? "
                "AND z BETWEEN ? AND ?", box):
            if v["id64"] not in found:
                found[v["id64"]] = (v["name"], v["x"], v["y"], v["z"], [])
        out = {}
        for id64, (name, x, y, z, records) in found.items():
            if dist(pos, {"x": x, "y": y, "z": z}) > r:
                continue
            own, hotspots, _ = own_data(self.db, id64, name)
            out[id64] = (name, x, y, z, merge_records(records, own, hotspots))
        return out

    def local_records(self, id64, name):
        """A system's cached Spansh dump merged with your scans, or None if nothing full is cached."""
        _, base = self.spansh.cached(id64)
        own, hotspots, _ = own_data(self.db, id64, name)
        recs = (base or {}).get("records") or []
        if not (any(r.get("full") for r in recs) or own):
            return None
        return merge_records(recs, own, hotspots)

    async def online(self, seq, pos, radius, crit):
        """One Spansh body search per OR'd value (its lists are AND'd), merged per system."""
        queries = []
        if crit["stars"]:
            f = {"subtype": {"value": sorted(crit["stars"])}}
            if crit["main_only"]:
                f["is_main_star"] = {"value": True}
            queries.append(("stars", f))
        if crit["planets"]:
            queries.append(("planets", {"subtype": {"value": sorted(crit["planets"])}}))
        for t in sorted(crit["rings"]):
            queries.append(("rings", {"rings": [{"type": t}]}))
        for m in sorted(crit["hotspots"]):
            queries.append(("hotspots", {"ring_signals": [{"name": m, "value": [1, 9999], "comparison": "<=>"}]}))
        if crit["bio"] is not None:
            queries.append(("bio", {"signals": [{"name": "Biological", "value": [1, 999], "comparison": "<=>"}]}))

        done = 0
        truncated_at = []

        async def one(filters):
            nonlocal done
            bodies, cut = await self.spansh.body_search(filters, pos, radius, SEARCH_PAGES_PER_QUERY)
            done += 1
            self.update(seq, status=f"asking Spansh… {done} of {len(queries)} queries done")
            if cut is not None:
                truncated_at.append(cut)
            return bodies

        self.update(seq, status=f"asking Spansh… 0 of {len(queries)} queries done")
        tasks = [asyncio.create_task(one(f)) for _, f in queries]
        try:
            batches = await asyncio.gather(*tasks)
        except BaseException:
            for t in tasks:
                t.cancel()
            raise
        systems = {}
        for bodies in batches:
            for b in bodies:
                id64 = b["system_id64"]
                entry = systems.setdefault(id64, (b["system_name"], b["system_x"], b["system_y"],
                                                  b["system_z"], {}))
                entry[4][b["name"]] = record_from_body_search(b)
        systems = {k: (n, x, y, z, list(recs.values())) for k, (n, x, y, z, recs) in systems.items()}
        coverage, note = radius, None
        if truncated_at:
            coverage = round(min(truncated_at), 1)
            note = (f"Spansh had too many matches to fetch them all, so results are only complete out to "
                    f"{coverage:g} ly. Tick fewer items or shrink the radius to see further.")
        return systems, coverage, note


# --------------------------------------------------------------------------
# Web
# --------------------------------------------------------------------------

# The page lives in static/ next to this script (page.html, page.css, page.js). page.html is read
# on every request so edits show up on reload; __SEARCH_OPTIONS__ is filled in when it is served.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def load_page():
    """page.html with its script and stylesheet links stamped by modification time, so a browser fetches
    the new copy as soon as either file changes instead of running a cached one."""
    with open(os.path.join(STATIC_DIR, "page.html"), encoding="utf-8") as f:
        html = f.read()
    for name in ("page.js", "page.css"):
        try:
            stamp = int(os.path.getmtime(os.path.join(STATIC_DIR, name)))
        except OSError:
            continue
        html = html.replace(f'"static/{name}"', f'"static/{name}?v={stamp}"')
    return html


def make_app(state):
    @web.middleware
    async def json_errors(request, handler):
        """Any unhandled exception in an API handler comes back as JSON, not an HTML traceback."""
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except (Exception, SystemExit) as e:
            import traceback
            traceback.print_exc()
            if request.path.startswith("/api/"):
                return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=500)
            raise

    app = web.Application(middlewares=[json_errors])

    def parse_id64(raw):
        v = int(raw)
        if not 0 <= v < 2 ** 63:
            raise ValueError("id64 out of range")
        return v

    options = json.dumps(SEARCH_OPTIONS)

    async def index(_):
        return web.Response(text=load_page().replace("/*SEARCH_OPTIONS*/null", options), content_type="text/html")

    async def nearby(request):
        # Long poll: a page that already has the current version waits here until something changes
        # (or 25 s pass: 204, and it asks again), so a target verdict reaches it in well under a second.
        if request.query.get("since") == f"{RUN_ID}:{state.version}":
            changed = state.changed
            try:
                await asyncio.wait_for(changed.wait(), LONG_POLL_SECONDS)
            except asyncio.TimeoutError:
                return web.Response(status=204)
            await asyncio.sleep(0.15)   # let a burst of changes (a refresh landing dumps) settle into one payload
        return web.json_response(state.payload())

    async def left_view(request):
        try:
            radius = max(10.0, min(float(request.query.get("radius", 100)), 500.0))
        except ValueError:
            radius = 100.0
        return web.json_response(state.left_behind(radius))   # the database connection belongs to this thread

    async def firsts_view(_):
        return web.json_response({"firsts": state.firsts_list(), "computed": (state.unsold or {}).get("computed")})

    app.router.add_get("/", index)
    app.router.add_static("/static/", STATIC_DIR, show_index=False)
    async def bookmark(request):
        try:
            body = await request.json()
            id64 = parse_id64(body["id"])
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "bad request"}, status=400)
        if body.get("remove"):
            state.remove_bookmark(id64)
        elif not state.set_bookmark(id64, str(body.get("note") or "")[:2000]):
            return web.json_response({"error": "unknown system"}, status=404)
        return web.json_response({"ok": True})

    async def search_start(request):
        try:
            params = await request.json()
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        state.searcher.start(params)
        return web.json_response({"seq": state.searcher.seq})

    async def search_get(_):
        return web.json_response(state.searcher.result)

    async def map_view(request):
        try:
            radius = max(5.0, min(float(request.query.get("radius", 50)), MAP_MAX_RADIUS))
            path_len = max(0, min(int(request.query.get("path", 100)), 5000))
        except ValueError:
            radius, path_len = 50.0, 100
        boost = request.query.get("boost") in ("1", "true")
        return web.json_response(await state.map_payload(radius, path_len, boost))

    async def system_view(request):
        try:
            id64 = parse_id64(request.match_info["id64"])
        except ValueError:
            return web.json_response({"error": "bad id"}, status=400)
        await state.ensure_records(id64)
        d = state.system_detail(id64)
        if not d:
            return web.json_response({"error": "unknown system"}, status=404)
        return web.json_response(d)

    async def body_view(request):
        try:
            id64 = parse_id64(request.query["system"])
            name = request.query["name"][:200]
        except (KeyError, ValueError):
            return web.json_response({"error": "bad request"}, status=400)
        d = await state.body_detail(id64, name)
        if not d:
            return web.json_response({"error": "unknown system"}, status=404)
        return web.json_response(d)

    async def history_view(request):
        try:
            days = max(1, min(int(request.query.get("days", 30)), 3650))
        except ValueError:
            days = 30
        return web.json_response(state.history(days))

    async def organics_view(request):
        try:
            days = max(1, min(int(request.query.get("days", 30)), 3650))
        except ValueError:
            days = 30
        return web.json_response(state.organics(days))

    def status_small():
        """A compact status for overlays and other tools (the page itself uses /api/nearby)."""
        p = state.payload()
        pos, f, t, u, c = p["position"], p["fuel"] or {}, p["target"], p["unsold"] or {}, p["carrier"]
        ob, sm = p["on_body"], p["sampling"]
        return {"system": pos and pos["name"], "id64": pos and str(pos["id64"]),
                "coords": pos and [pos["x"], pos["y"], pos["z"]], "region": (p["region"] or {}).get("name"),
                "fuel_pct": f.get("pct"), "fuel_jumps": f.get("jumps_max"), "jump_range": p["jump_range"], "boost": p["boost"],
                "target": t and {"name": t.get("name"), "status": t.get("status"), "star_class": t.get("star_class")},
                "unsold": u.get("total"), "on_body": ob and ob["body"],
                "sampling": sm and {k: sm.get(k) for k in ("genus", "samples", "to_go", "clear")},
                "carrier": c and {"name": c.get("name"), "system": c.get("system"), "distance": c.get("distance")},
                "commander": (p["commander"] or {}).get("name")}

    STATUS_FIELDS = {
        "system": lambda s: s["system"] or "",
        "fuel": lambda s: f"fuel {s['fuel_pct']}%" if s["fuel_pct"] is not None else "",
        "target": lambda s: f"-> {s['target']['name']} ({s['target']['status']})" if s["target"] else "",
        "unsold": lambda s: f"unsold {s['unsold'] / 1e6:.1f}M cr" if s["unsold"] else "",
        "region": lambda s: s["region"] or "",
        "body": lambda s: f"on {s['on_body']}" if s["on_body"] else "",
        "sampling": lambda s: (f"{s['sampling']['genus']} {s['sampling']['samples']}/3 " +
                               ("clear" if s["sampling"]["clear"] else f"{s['sampling']['to_go']} m to go")) if s["sampling"] and s["sampling"]["to_go"] is not None else "",
    }

    async def status_view(_):
        return web.json_response(status_small(), headers={"Cache-Control": "no-store"})

    async def status_txt_view(request):
        """One line for an OBS text source: /api/status.txt?fields=system,fuel,target (the default set)."""
        s_ = status_small()
        fields = [f for f in (request.query.get("fields") or "system,fuel,target,unsold").split(",") if f in STATUS_FIELDS]
        line = " · ".join(x for x in (STATUS_FIELDS[f](s_) for f in fields) if x)
        return web.Response(text=line + "\n", content_type="text/plain", headers={"Cache-Control": "no-store"})

    async def next_stop_view(request):
        try:
            body = await request.json()
            id64 = None if body.get("clear") else parse_id64(body["id"])
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "bad request"}, status=400)
        if not state.set_next_stop(id64):
            return web.json_response({"error": "unknown system"}, status=404)
        return web.json_response({"ok": True})

    async def backup_view(_):
        if not state.db_path:
            return web.json_response({"error": "no database path"}, status=500)
        if state.backup_task and not state.backup_task.done():
            return web.json_response({"running": True})
        state.backup_task = asyncio.create_task(state.backup())
        state.bump()
        return web.json_response({"running": True})

    async def say_view(request):
        """A spoken alert as WAV (Piper). 503 while no voice is ready: the page then uses browser speech."""
        text = (request.query.get("text") or "")[:400]
        sp = state.speaker
        if not sp or not sp.ready or not text.strip():
            return web.json_response({"error": "no Piper voice ready" if text.strip() else "no text"}, status=503)
        try:
            speed = float(request.query.get("speed") or SPEECH_SPEED)
        except ValueError:
            speed = SPEECH_SPEED
        audio = await asyncio.get_running_loop().run_in_executor(None, sp.say, text, speed)
        if not audio:
            return web.json_response({"error": "no Piper voice ready"}, status=503)
        return web.Response(body=audio, content_type="audio/wav", headers={"Cache-Control": "no-store"})

    async def speech_view(_):
        """The spoken alerts' lines (speech.json): the page asks again when the payload's version changes."""
        return web.json_response(state.speech.lines() if state.speech else {"styles": {}, "lines": {}, "version": None})

    async def autohonk_test_view(request):
        """Hold Primary Fire once after a countdown (time to click into the game), whether or not auto honk
        is on: the dialog's test button."""
        h = state.honker
        if not h or not h.available:
            return web.json_response({"error": h.status if h else "not started"}, status=400)
        keys, what = h.combo()
        if not keys:
            return web.json_response({"error": what}, status=400)
        was_open = h.ready
        if not h.open():
            return web.json_response({"error": h.status}, status=400)

        async def later():
            await asyncio.sleep(5)
            try:
                await asyncio.get_running_loop().run_in_executor(None, h.press)
            finally:
                if not was_open and not state.autohonk["enabled"]:
                    h.close()
                    h.status = "off"
                state.bump()
        asyncio.get_running_loop().create_task(later())
        return web.json_response({"pressing": what, "in": 5})

    async def autohonk_view(request):
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "expected JSON"}, status=400)
        state.set_autohonk(bool(body.get("enabled")))
        return web.json_response(state.autohonk_info())

    async def voice_view(request):
        try:
            name = str((await request.json())["voice"])[:100]
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "bad request"}, status=400)
        if not state.speaker or not state.speaker.available:
            return web.json_response({"error": "Piper is not installed"}, status=503)
        state.speaker.use(name)
        return web.json_response({"ok": True})

    async def radius_view(request):
        try:
            r = float((await request.json())["radius"])
        except (ValueError, KeyError, TypeError):
            return web.json_response({"error": "bad request"}, status=400)
        if r not in RADIUS_CHOICES and r != state.radius:
            return web.json_response({"error": "radius must be one of " + ", ".join(f"{x:g}" for x in RADIUS_CHOICES)}, status=400)
        state.set_radius(r)
        return web.json_response({"radius": state.radius})

    async def materials_view(_):
        inv = ed_materials.inventory(state.journals.materials)
        inv["stale"] = bool((state.materials_summary() or {}).get("stale"))
        inv["sources"] = state.material_sources()
        return web.json_response(inv)

    async def log_view(request):
        if not ed_log:
            return web.json_response({"error": "ed_log.py is missing"}, status=500)
        qs = request.query
        try:
            days = max(1, min(int(qs.get("days", 7)), 3650))
            limit = max(1, min(int(qs.get("limit", 200)), 500))
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        cats = {c for c in qs["cat"].split(",") if c in ed_log.CATEGORIES} if "cat" in qs else None  # empty: nothing
        kw = dict(days=days, limit=limit, cats=cats, q=(qs.get("q") or "").strip()[:200] or None,
                  noise=qs.get("noise") in ("1", "true"), before=qs.get("before"), after=qs.get("after"))
        dirs = LIVE_DIRS + LEGACY_DIRS
        out = await asyncio.get_running_loop().run_in_executor(None, lambda: ed_log.read_log(dirs, **kw))
        return web.json_response(out)

    async def export_view(request):
        what, fmt = request.query.get("what", "firsts"), request.query.get("format", "csv")
        if what == "unsold":  # a full journal pass: keep it off the event loop
            cols, rows = await asyncio.get_running_loop().run_in_executor(None, state.export_rows, what)
        else:
            cols, rows = state.export_rows(what)
        if cols is None:
            return web.json_response({"error": "unknown export"}, status=400)
        stamp = time.strftime("%Y%m%d")
        if fmt == "json":
            return web.json_response(rows, headers={"Content-Disposition": f'attachment; filename="{what}-{stamp}.json"'})
        import csv
        import io
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return web.Response(text=buf.getvalue(), content_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="{what}-{stamp}.csv"'})

    app.router.add_get("/api/nearby", nearby)
    app.router.add_get("/api/map", map_view)
    app.router.add_get("/api/system/{id64}", system_view)
    app.router.add_get("/api/history", history_view)
    app.router.add_get("/api/organics", organics_view)
    app.router.add_get("/api/log", log_view)
    app.router.add_get("/api/materials", materials_view)
    app.router.add_post("/api/radius", radius_view)
    app.router.add_get("/api/say", say_view)
    app.router.add_get("/api/speech", speech_view)
    app.router.add_post("/api/backup", backup_view)
    app.router.add_post("/api/nextstop", next_stop_view)
    app.router.add_get("/api/status", status_view)
    app.router.add_get("/api/status.txt", status_txt_view)
    app.router.add_post("/api/voice", voice_view)
    app.router.add_post("/api/autohonk", autohonk_view)
    app.router.add_post("/api/autohonk/test", autohonk_test_view)
    app.router.add_get("/api/firsts", firsts_view)
    app.router.add_get("/api/left", left_view)
    app.router.add_get("/api/body", body_view)
    app.router.add_get("/api/export", export_view)
    app.router.add_post("/api/search", search_start)
    app.router.add_get("/api/search", search_get)
    app.router.add_post("/api/bookmark", bookmark)
    return app


async def check_bio_rules(state):
    """Keep the exobiology spawn rules current. A copy ships with Outrider; each start asks GitHub
    whether BioScan or the region map changed and fetches the new data if so (offline just keeps
    the copy). Rows carry bio estimates, so they are rebuilt after an update."""
    try:
        updated = await asyncio.get_running_loop().run_in_executor(None, lambda: ed_bio.update_if_newer(log=print))
    except Exception as e:  # noqa: BLE001 -- no shipped copy and no network: the page works without predictions
        print(f"exobiology rules: none available ({e}); no species guesses until "
              f"python3 ed_bio.py --update-rules  succeeds.", file=sys.stderr)
        return
    info = ed_bio.rules_info()
    if updated:
        print(f"exobiology rules: updated from BioScan ({info['species']} species)")
        state.journals.dirty |= set(state.bases)
    else:
        print(f"exobiology rules: {info['species']} species from BioScan, up to date")


def port_free(host, port):
    """Can we listen on host:port? Checked before the journal import so a second copy fails fast."""
    import socket
    try:
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


async def run(args, st):
    global LIVE_DIRS, LEGACY_DIRS, UNSOLD_WARN, UNSOLD_URGENT, BIO_MIN, SOUNDS_DEFAULT, BODY_HIGHLIGHT, BIO_HIGHLIGHT, MAX_INCLUDE_BONUS, RADIUS_CHOICES, VOICE, VOICE_FALLBACK, BACKUP_DIR
    global SPEECH_STYLES, SPEECH_PROFANITY, SPEECH_NAMES, SPEECH_SPEED, SPEAK_BIO_SIGNALS, SPEAK_GEO_SIGNALS, SPEECH_PROFANITY_PCT
    global SPANSH_CONCURRENCY, MAP_MAX_RADIUS, MAP_MAX_PAGES
    LIVE_DIRS = [d for d in st["live"] if os.path.isdir(d)]
    LEGACY_DIRS = [d for d in st["legacy"] if os.path.isdir(d)]
    for d in st["live"] + st["legacy"]:
        if not os.path.isdir(d):
            print(f"journal folder not found, skipping: {d}", file=sys.stderr)
    UNSOLD_WARN, UNSOLD_URGENT, BIO_MIN, SOUNDS_DEFAULT = st["unsold_warn"], st["unsold_urgent"], st["bio_min"], st["sounds"]
    BODY_HIGHLIGHT, BIO_HIGHLIGHT, MAX_INCLUDE_BONUS = st["body_highlight"], st["bio_highlight"], st["max_include_bonus"]
    RADIUS_CHOICES = tuple(st["radius_choices"])
    VOICE, VOICE_FALLBACK = st["voice"], st["voice_fallback"]
    SPEECH_STYLES, SPEECH_PROFANITY, SPEECH_NAMES = tuple(st["speech_styles"]), st["speech_profanity"], st["speech_names"]
    SPEECH_SPEED, SPEECH_PROFANITY_PCT = st["speech_speed"], st["speech_profanity_pct"]
    SPEAK_BIO_SIGNALS, SPEAK_GEO_SIGNALS = st["speak_bio_signals"], st["speak_geo_signals"]
    BACKUP_DIR = st["backup_dir"]
    SPANSH_CONCURRENCY, MAP_MAX_RADIUS, MAP_MAX_PAGES = st["concurrency"], st["map_max_radius"], st["map_max_pages"]
    radius_flag = args.radius   # --radius on the command line beats a radius chosen on the page
    args.host, args.port, args.radius, args.db = st["host"], st["port"], st["radius"], st["db"]
    if ed_unsold:
        ed_unsold.LIVE_DIRS, ed_unsold.LEGACY_DIRS = LIVE_DIRS, LEGACY_DIRS
        ed_unsold.DEFAULT_DIRS = LIVE_DIRS + LEGACY_DIRS
    if not LIVE_DIRS:
        print("No Elite Dangerous journal folder found. Pass --journals PATH (the folder holding "
              "Journal.*.log, usually '<Saved Games>/Frontier Developments/Elite Dangerous') or set "
              "ED_JOURNALS.", file=sys.stderr)
    else:
        print("journals: " + ", ".join(LIVE_DIRS) + (f"  (legacy: {', '.join(LEGACY_DIRS)})" if LEGACY_DIRS else ""))
    if not port_free(args.host, args.port):
        print(f"port {args.port} is already in use: is ED Outrider already running? "
              f"(open http://127.0.0.1:{args.port}/, or start this one with --port N)", file=sys.stderr)
        raise SystemExit(1)
    db = open_db(args.db, rescan=args.rescan)
    journals = Journals(db)

    t = time.time()
    journals.import_legacy()
    for d in LIVE_DIRS:
        journals.scan_dir(d)
        journals.read_navroute(d)
        journals.read_status(d)
    db.commit()
    if journals.last_event_ts is None:   # first run on an already-read database: look at the newest file's tail
        for d in LIVE_DIRS:
            files = sorted(glob(os.path.join(d, "Journal.*.log")))
            if files:
                with open(files[-1], "rb") as f:
                    f.seek(max(0, os.path.getsize(files[-1]) - 4096))
                    tail = f.read()
                if b'"timestamp":"' in tail:
                    journals.last_event_ts = tail.rsplit(b'"timestamp":"', 1)[-1][:20].decode("ascii", "replace")
                    meta_set(db, "last_event_ts", journals.last_event_ts)
    n = db.execute("SELECT count(*) FROM visits").fetchone()[0]
    print(f"journals up to date in {time.time() - t:.1f}s: {n} systems visited")
    if journals.pos:
        print(f"current system: {journals.pos['name']}")
    elif LIVE_DIRS:
        print("no jump found in the journals yet: the page fills in after your first FSD jump")

    spansh = Spansh(db)
    await spansh.start()
    chosen = meta_get(db, "radius_choice")   # picked from the page's Where tile; survives a restart
    usable = chosen and radius_flag is None and float(chosen) in RADIUS_CHOICES   # the config may have dropped it
    state = State(db, journals, spansh, float(chosen) if usable else args.radius)
    state.searcher = Searcher(state)
    state.db_path = args.db
    loop = asyncio.get_running_loop()
    state.speaker = ed_tts.Speaker(VOICE, VOICE_FALLBACK, on_change=lambda: loop.call_soon_threadsafe(state.bump))
    print("spoken alerts: " + ("Piper found, preparing a voice" if state.speaker.available else
                               "Piper not installed, the page uses browser speech (see ed_tts.py)"))
    state.speaker.start()
    state.autohonk = dict(st["autohonk"])
    saved = meta_get(db, "autohonk_enabled")   # the page's toggle beats the config file once used
    if saved is not None:
        state.autohonk["enabled"] = bool(saved)
    state.honker = ed_honk.Honker(state.autohonk["key"], state.autohonk["hold"], LIVE_DIRS)
    if state.autohonk["enabled"]:
        state.honker.open()
    print("auto honk: " + (state.honker.status if state.autohonk["enabled"] else "off")
          + (" (the D-Scanner must be on primary fire)" if state.honker.ready else ""))
    state.speech = ed_speech.SpeechLines(st["speech_file"])
    sp = state.speech.info()
    print(f"spoken alerts: wording from {sp['file']}" if sp["version"] else f"spoken alerts: {sp['error']}")
    for msg in sp["problems"]:
        print(f"  {sp['file']}: {msg}", file=sys.stderr)
    rules_task = asyncio.create_task(check_bio_rules(state)) if ed_bio else None
    watcher = asyncio.create_task(state.watch())

    runner = web.AppRunner(make_app(state))
    await runner.setup()
    try:
        await web.TCPSite(runner, args.host, args.port).start()
    except OSError as e:   # taken in the moment since port_free() said it was free
        print(f"cannot listen on {args.host}:{args.port}: {e.strerror or e}", file=sys.stderr)
        await spansh.close()
        raise SystemExit(1)
    print(f"serving on http://{args.host}:{args.port}/  (Ctrl-C to stop)")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("note: the page is reachable from other machines on your network (no authentication; "
              "it can read your journals' contents and edit bookmarks)")
    try:
        await asyncio.Event().wait()
    finally:
        tasks = [t for t in (watcher, rules_task, state.refresh_task, state.target_task, state.unsold_task, state.seller_task,
                             state.carrier_task, state.searcher.task) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await runner.cleanup()
        await spansh.close()
        db.commit()
        db.close()


def main(argv=None):
    sys.stdout.reconfigure(line_buffering=True)
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--radius", type=float, help="Search radius in ly (default 25).")
    p.add_argument("--host", help="Address to serve on (default 127.0.0.1).")
    p.add_argument("--port", type=int, help="Port to serve on (default 8025).")
    p.add_argument("--db", help=f"SQLite database path (default {DB_PATH}).")
    p.add_argument("--config", default=CONFIG_PATH, metavar="PATH",
                   help=f"TOML config file (default {CONFIG_PATH}; see ed_outrider.toml.example).")
    p.add_argument("--write-config", action="store_true",
                   help="Write the effective settings to --config as a starting point (never overwrites) and exit.")
    p.add_argument("--journals", action="append", metavar="PATH",
                   help="Journal folder to tail (repeatable). Default: auto-detected.")
    p.add_argument("--legacy", action="append", metavar="PATH",
                   help="Folder of older journals to import once (repeatable). Default: auto-detected.")
    p.add_argument("--rescan", action="store_true",
                   help="Forget which journals were read and rebuild visits from scratch, "
                        "including the legacy directories. Spansh cache is kept.")
    args = p.parse_args(argv)
    detected = (ed_unsold.LIVE_DIRS, ed_unsold.LEGACY_DIRS) if ed_unsold else ([], [])
    st = settings_from(load_config(args.config), args, os.environ.get("ED_JOURNALS"), detected)
    if args.write_config:
        if os.path.exists(args.config):
            print(f"{args.config} already exists; the effective settings are:\n")
            print(config_text(st))
        else:
            with open(args.config, "w", encoding="utf-8") as f:
                f.write(config_text(st))
            print(f"wrote {args.config}")
        return
    try:
        asyncio.run(run(args, st))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
