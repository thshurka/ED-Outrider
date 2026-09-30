"""Regression tests for ED Outrider.

    python3 -m unittest discover tests            # unit tests (no journals or network needed)
    node tests/page_smoke.js <port>               # optional page smoke test against a running server

The synthetic cases here are the failure scenarios earlier reviews found: partial sales, ship
losses, re-scans, abandoned bio runs, crew cuts, ring naming and bio spawn rules.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import unittest
import unittest.mock
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ed_bio  # noqa: E402
import ed_materials  # noqa: E402
import ed_log  # noqa: E402
import ed_outrider  # noqa: E402
import ed_unsold  # noqa: E402
import ed_speech  # noqa: E402


def T(s):
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


ARGS = argparse.Namespace(commander=None, since=None, ignore_deaths=False, bonus_rate=None,
                          efficiency_bonus=False, no_odyssey=False, top=0)


def scan(ts, system, addr, body_id, name, disc=False, star=False):
    ev = {"event": "Scan", "timestamp": ts, "StarSystem": system, "SystemAddress": addr, "BodyID": body_id,
          "BodyName": name, "WasDiscovered": disc, "WasMapped": False, "ScanType": "Detailed",
          "DistanceFromArrivalLS": 0.0 if star else 500.0}
    if star:
        ev.update(StarType="K", StellarMass=0.8)
    else:
        ev.update(PlanetClass="High metal content body", MassEM=1.0, TerraformState="")
    return (T(ts), None, ev)


def sale(ts, systems):
    return (T(ts), None, {"event": "MultiSellExplorationData", "timestamp": ts, "TotalEarnings": 1000, "BaseValue": 1000,
                          "Bonus": 0, "Discovered": [{"SystemName": s, "NumBodies": 1} for s in systems]})


def death(ts, option="rebuy"):
    return [(T(ts), None, {"event": "Died", "timestamp": ts}), (T(ts), None, {"event": "Resurrect", "timestamp": ts, "Option": option})]


class UnsoldEstimate(unittest.TestCase):
    def test_partial_sale_keeps_unsold_systems(self):
        ev = [scan("2026-01-01T00:00:00Z", "A", 1, 0, "A", star=True), scan("2026-01-01T00:00:00Z", "B", 2, 0, "B", star=True),
              sale("2026-01-02T00:00:00Z", ["A"])]
        ex = ed_unsold.analyse(ev, ARGS)["exploration"]
        self.assertEqual({r["system"] for r in ex["rows"]}, {"B"})

    def test_ship_loss_before_sale_is_lost_but_rescan_counts(self):
        ev = [scan("2026-01-01T00:00:00Z", "A", 1, 0, "A", star=True)] + death("2026-01-02T00:00:00Z") + \
             [sale("2026-01-03T00:00:00Z", ["A"]), scan("2026-01-04T00:00:00Z", "A", 1, 0, "A", star=True)]
        ex = ed_unsold.analyse(ev, ARGS)["exploration"]
        self.assertEqual([r["system"] for r in ex["rows"]], ["A"])
        self.assertTrue(ex["rows"][0]["first_discovered"])

    def test_on_foot_death_keeps_ship_data(self):
        ev = [scan("2026-01-01T00:00:00Z", "A", 1, 0, "A", star=True)] + death("2026-01-02T00:00:00Z", "recover")
        self.assertEqual(ed_unsold.analyse(ev, ARGS)["exploration"]["bodies"], 1)

    def test_crew_cut_only_from_sales_with_same_crew(self):
        stats = lambda ts, hired, fired: (T(ts), None, {"event": "Statistics", "timestamp": ts,
                                                         "Crew": {"NpcCrew_Hired": hired, "NpcCrew_Fired": fired}})
        cut = (T("2026-01-02T00:00:00Z"), None, {"event": "MultiSellExplorationData", "timestamp": "2026-01-02T00:00:00Z",
                                                  "TotalEarnings": 910, "BaseValue": 1000, "Bonus": 0, "Discovered": []})
        ev = [stats("2026-01-01T00:00:00Z", 1, 0), cut, stats("2026-02-01T00:00:00Z", 1, 1)]
        ex = ed_unsold.analyse(ev, ARGS)["exploration"]
        self.assertEqual(ex["npc_crew"], 0)
        self.assertEqual(ex["payout_ratio"], 1.0)
        ev = [stats("2026-01-01T00:00:00Z", 1, 0), cut]
        self.assertAlmostEqual(ed_unsold.analyse(ev, ARGS)["exploration"]["payout_ratio"], 0.91)

    def test_journal_dirs_env_override(self):
        os.environ["ED_JOURNALS"] = os.pathsep.join([os.getcwd(), "/nonexistent/xyz"])
        try:
            live, legacy = ed_unsold.find_journal_dirs()
        finally:
            del os.environ["ED_JOURNALS"]
        self.assertEqual(live, [os.getcwd()])


class FirstsAndRings(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")

    def first(self, ts, bid, name, disc, mapped, main=0):
        self.db.execute("INSERT INTO own_firsts VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(system, body_id) DO UPDATE SET "
                        "undisc_ts=coalesce(excluded.undisc_ts, undisc_ts)",
                        (1, bid, name, main, int(disc), int(mapped), None, ts, None if disc else ts))

    def test_rescan_after_loss_is_unsold_per_body(self):
        self.first("T1", 0, "Sys", False, True, main=1); self.first("T1", 1, "Sys 1", False, True)
        self.db.execute("INSERT INTO deaths VALUES ('T2', 'rebuy')")
        self.first("T3", 0, "Sys", False, True, main=1)
        f = ed_outrider.own_firsts(self.db, 1, "Sys")
        self.assertEqual(f["system_state"], "unsold")
        self.assertEqual(f["bodies_by"], {"sold": 0, "unsold": 1, "lost": 1})

    def test_partial_sale_headline(self):
        self.first("T1", 0, "Sys", False, True, main=1)
        self.db.execute("INSERT INTO sales VALUES ('Sys', 'T2', 1)")
        self.first("T3", 2, "Sys 2", True, False)
        self.db.execute("INSERT INTO own_mapped (system, body_id, ts) VALUES (1, 2, 'T3')")
        f = ed_outrider.own_firsts(self.db, 1, "Sys")
        self.assertEqual((f["system_state"], f["sale"]), ("sold", "unsold"))

    def test_lone_star_ring_name(self):
        self.assertEqual(ed_outrider.split_ring_name("Sys", "Sys A Ring"), ("Sys", "A Ring"))
        self.assertEqual(ed_outrider.split_ring_name("Sys", "Sys 3 B Ring"), ("3", "B Ring"))

    def test_organic_state(self):
        self.db.execute("INSERT INTO deaths VALUES ('T2', 'rebuy')")
        self.db.execute("INSERT INTO bio_sales VALUES ('T4', 3)")
        self.assertEqual(ed_outrider.organic_state(self.db, "T1"), "lost")
        self.assertEqual(ed_outrider.organic_state(self.db, "T3"), "sold")
        self.assertEqual(ed_outrider.organic_state(self.db, "T5"), "aboard")

    def test_ring_density(self):
        r = ed_outrider.ring_stats([{"name": "A Ring", "type": "Rocky", "mass": 1000.0, "inner": 1000.0, "outer": 2000.0}])[0]
        self.assertEqual(r["width_km"], 1)
        self.assertAlmostEqual(r["density"], 1000.0 / (3.141592653589793 * 3e6 / 1e6), places=3)


class BioNames(unittest.TestCase):
    """Spelling normalisation needs no downloaded rules."""

    def test_atmosphere_and_volcanism_spellings(self):
        self.assertEqual(ed_bio.norm_atmosphere("Hot thin Sulphur dioxide"), "sulphurdioxide")
        self.assertEqual(ed_bio.norm_atmosphere("CarbonDioxideRich"), "carbondioxiderich")
        self.assertEqual(ed_bio.norm_atmosphere(None), "none")
        self.assertEqual(ed_bio.norm_volcanism("Major Rocky Magma"), "major rocky magma volcanism")
        self.assertEqual(ed_bio.norm_volcanism("No volcanism"), "")
        self.assertEqual(ed_bio.journal_class("High metal content world"), "High metal content body")
        self.assertEqual(ed_bio.journal_class("Earth-like world"), "Earthlike body")

    def test_star_codes(self):
        for name, code in [("M (Red dwarf) Star", "M"), ("M (Red giant) Star", "M_RedGiant"),
                           ("K (Yellow-Orange giant) Star", "K_OrangeGiant"), ("White Dwarf (DA) Star", "DA"),
                           ("Wolf-Rayet N Star", "WN"), ("Neutron Star", "N"), ("Black Hole", "H"),
                           ("Herbig Ae/Be Star", "AeBe"), ("T Tauri Star", "TTS"), ("DA", "DA"), ("M_RedGiant", "M_RedGiant")]:
            self.assertEqual(ed_bio.star_code(name), code, name)
        self.assertTrue(ed_bio.star_matches("M", "M_RedGiant"))
        self.assertTrue(ed_bio.star_matches("D", "DAB"))
        self.assertFalse(ed_bio.star_matches("K", "M"))
        self.assertTrue(ed_bio.luminosity_matches("V", "Vab"))
        self.assertFalse(ed_bio.luminosity_matches("V", "IV"))


@unittest.skipUnless(ed_bio.available(), "bio_rules.json not downloaded (python3 ed_bio.py --update-rules)")
class BioRules(unittest.TestCase):
    """Against the downloaded BioScan rules: the things a wrong evaluator would get wrong."""
    M_SYSTEM = {"x": -3485, "y": 39, "z": 7320, "stars": [{"type": "M", "luminosity": "Va", "main": True}],
                "planet_types": ["Rocky body", "Icy body"]}

    def names(self, body, system=None):
        return [s["name"] for s in ed_bio.predict(body, system or self.M_SYSTEM)]

    def test_icy_argon_is_bacterium_and_fonticulua_only(self):
        n = self.names({"class": "Icy body", "atmosphere": "Argon", "gravity": 0.2, "temperature": 80, "parents": ["M"]})
        self.assertIn("Fonticulua Campestris", n)
        self.assertNotIn("Tussock Capillum", n)
        self.assertNotIn("Osseus Pumice", n)
        self.assertFalse([x for x in n if x.startswith("Electricae")], "Electricae need an A/N/D/H parent star")

    def test_spansh_two_prefix_atmosphere(self):
        # every body known (F20: until then an unscanned companion star could still be the hot one)
        n = self.names({"class": "Rocky body", "atmosphere": "Hot thin Sulphur dioxide", "gravity": 0.3, "temperature": 420},
                       dict(self.M_SYSTEM, complete=True))
        self.assertIn("Bacterium Tela", n)
        self.assertNotIn("Prasinum Bioluminescent Anemone", n, "anemones want a hot star")

    def test_tubus_needs_low_gravity(self):
        base = {"class": "Rocky body", "atmosphere": "CarbonDioxide", "temperature": 170}
        self.assertIn("Tubus Compagibus", self.names(dict(base, gravity=0.1)))
        self.assertNotIn("Tubus Compagibus", self.names(dict(base, gravity=0.2)))

    def test_brain_trees_only_near_guardian_nebulae(self):
        body = {"class": "Rocky body", "atmosphere": "None", "gravity": 0.2, "temperature": 300,
                "volcanism": "minor metallic magma volcanism"}
        near = {"x": -840, "y": -561, "z": 13361, "stars": [{"type": "K", "main": True}], "planet_types": ["Water world"]}
        self.assertIn("Roseum Brain Tree", self.names(body, near))
        self.assertNotIn("Roseum Brain Tree", self.names(body))

    def test_regions(self):
        self.assertEqual(ed_bio.region_name(0, 0, 0), "Inner Orion Spur")
        self.assertEqual(ed_bio.region_name(-9530.5, -910.3, 19808.1), "Inner Scutum-Centaurus Arm")
        self.assertIsNone(ed_bio.region_number(90000, 0, 0))

    def test_unruled_genus_still_priced(self):
        val, groups = ed_bio.potential([], genera=["Crystalline Shards"])
        self.assertGreater(val, 1_000_000)
        self.assertTrue(groups[0]["unruled"])


if __name__ == "__main__":
    unittest.main()


class Config(unittest.TestCase):
    def test_precedence_flag_env_file_detect(self):
        cfg = {"journals": {"live": ["/from/file"]}, "server": {"port": 9000}, "defaults": {"bio_min": 5}}
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from(cfg, args, None, (["/detected"], ["/detected-legacy"]))
        self.assertEqual((st["live"], st["legacy"], st["port"], st["bio_min"]), (["/from/file"], [], 9000, 5))
        st = ed_outrider.settings_from(cfg, args, "/from/env", (["/detected"], []))
        self.assertEqual(st["live"], ["/from/env"])
        args.journals, args.port = ["/from/flag"], 7000
        st = ed_outrider.settings_from(cfg, args, "/from/env", (["/detected"], []))
        self.assertEqual((st["live"], st["port"]), (["/from/flag"], 7000))
        st = ed_outrider.settings_from({}, argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None),
                                     None, (["/detected"], ["/detected-legacy"]))
        self.assertEqual((st["live"], st["legacy"], st["port"], st["host"]), (["/detected"], ["/detected-legacy"], 8025, "127.0.0.1"))

    def test_config_text_round_trips(self):
        import tomllib
        args = argparse.Namespace(journals=["/a b/c"], legacy=None, host="0.0.0.0", port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        back = tomllib.loads(ed_outrider.config_text(st))
        self.assertEqual(back["journals"]["live"], ["/a b/c"])
        self.assertEqual(back["server"]["host"], "0.0.0.0")
        self.assertEqual(back["defaults"]["unsold_warn"], 50_000_000)

    def test_speech_danger_business(self):   # P10(a): on unless the config turns it off, and written back
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertIs(st["speech_danger_business"], True)
        self.assertIs(tomllib.loads(ed_outrider.config_text(st))["defaults"]["speech_danger_business"], True)
        st = ed_outrider.settings_from({"defaults": {"speech_danger_business": False}}, args, None, ([], []))
        self.assertIs(st["speech_danger_business"], False)
        self.assertIs(tomllib.loads(ed_outrider.config_text(st))["defaults"]["speech_danger_business"], False)


class ConfigValidation(unittest.TestCase):
    """Batch 1 (2026-09-30b): a bad config value is reported on stderr and the default kept."""

    def settings(self, cfg, **flags):
        import contextlib, io
        args = argparse.Namespace(**dict(dict(journals=None, legacy=None, host=None, port=None, radius=None, db=None),
                                         **flags))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            st = ed_outrider.settings_from(cfg, args, None, ([], []))
        return st, err.getvalue()

    def test_quoted_false_is_not_true(self):   # G2.1: bool("false") is True; it must not switch auto honk on
        st, err = self.settings({"autohonk": {"enabled": "false"}})
        self.assertIs(st["autohonk"]["enabled"], False)
        self.assertIn("[autohonk] enabled = 'false' is not valid here, using False", err)

    def test_every_boolean_is_strict(self):   # G2.1
        st, err = self.settings({"defaults": {"sounds": "false", "body_max_value_include_bonus": "no",
                                              "speech_profanity": "yes", "speech_danger_business": "off",
                                              "speak_bio_signals": 2, "speak_geo_signals": "false"},
                                 "autohonk": {"skip_honked": "no", "announce": []}})
        self.assertEqual((st["sounds"], st["max_include_bonus"], st["speech_profanity"], st["speech_danger_business"],
                          st["speak_bio_signals"], st["speak_geo_signals"], st["autohonk"]["skip_honked"],
                          st["autohonk"]["announce"]),
                         (ed_outrider.SOUNDS_DEFAULT, ed_outrider.MAX_INCLUDE_BONUS, ed_outrider.SPEECH_PROFANITY,
                          ed_outrider.SPEECH_DANGER_BUSINESS, ed_outrider.SPEAK_BIO_SIGNALS,
                          ed_outrider.SPEAK_GEO_SIGNALS, ed_outrider.AUTOHONK["skip_honked"],
                          ed_outrider.AUTOHONK["announce"]))
        self.assertEqual(err.count("is not valid here"), 8)

    def test_real_booleans_and_0_1_pass(self):   # G2.1
        st, err = self.settings({"defaults": {"speech_profanity": True, "sounds": 0}, "autohonk": {"enabled": 1}})
        self.assertEqual((st["speech_profanity"], st["sounds"], st["autohonk"]["enabled"]), (True, False, True))
        self.assertEqual(err, "")

    def test_radius_at_least_1(self):   # F1
        for bad in (0, -10):
            st, err = self.settings({"server": {"radius": bad}})
            self.assertEqual(st["radius"], 25.0)
            self.assertIn("[server] radius", err)
        self.assertEqual(self.settings({"server": {"radius": 30}})[0]["radius"], 30.0)
        self.assertEqual(self.settings({}, radius=0.0)[0]["radius"], 1.0)   # the --radius flag is clamped

    def test_host_must_be_a_string(self):   # F2
        st, err = self.settings({"server": {"host": 0}})
        self.assertEqual(st["host"], "127.0.0.1")
        self.assertIn("[server] host = 0 is not valid here", err)
        self.assertEqual(self.settings({"server": {"host": "0.0.0.0"}})[0]["host"], "0.0.0.0")

    def test_speech_styles(self):   # G2.3
        st, err = self.settings({"defaults": {"speech_styles": "sarcastic"}})
        self.assertEqual((st["speech_styles"], err), (["sarcastic"], ""))
        st, err = self.settings({"defaults": {"speech_styles": 3}})
        self.assertEqual(st["speech_styles"], list(ed_outrider.SPEECH_STYLES))
        self.assertIn("[defaults] speech_styles = 3 must be a list", err)

    def test_high_gravity_positive(self):   # G2.4: the page reads 0 as unset (2 g), so the server keeps it above 0
        self.assertEqual(self.settings({"defaults": {"high_gravity": 0}})[0]["high_gravity"], 0.1)
        self.assertEqual(self.settings({"defaults": {"high_gravity": 1.5}})[0]["high_gravity"], 1.5)


class FreshInstall(unittest.TestCase):
    """Batch 0: a brand-new database must accept every event the parser handles."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)

    def test_first_scan_on_fresh_database(self):
        ev = scan("2026-01-01T00:00:00Z", "Sys", 7, 1, "Sys 1")[2]
        self.j.handle(ev)
        raw = self.db.execute("SELECT raw FROM own_bodies WHERE system=7").fetchone()["raw"]
        self.assertIn('"BodyName": "Sys 1"', raw)

    def test_barycentre_stored(self):
        self.j.handle({"event": "ScanBaryCentre", "timestamp": "2026-01-01T00:00:00Z", "SystemAddress": 7,
                       "BodyID": 3, "SemiMajorAxis": 1.5e10, "Eccentricity": 0.1})
        row = self.db.execute("SELECT record FROM own_barycentres WHERE system=7 AND body_id=3").fetchone()
        self.assertIn("SemiMajorAxis", row["record"])

    def test_commander_credits_and_sales(self):
        self.j.handle({"event": "Commander", "timestamp": "2026-01-01T00:00:00Z", "Name": "Jameson", "FID": "F1"})
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:01Z", "Commander": "Jameson",
                       "Credits": 1000, "Loan": 0})
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": "2026-01-01T01:00:00Z", "TotalEarnings": 500,
                       "Discovered": []})
        self.j.handle({"event": "SellOrganicData", "timestamp": "2026-01-01T02:00:00Z",
                       "BioData": [{"Value": 100, "Bonus": 400}]})
        c = self.j.commander
        self.assertEqual((c["name"], c["credits"], c["earned"]), ("Jameson", 1000, 1000))
        # a new login resets the baseline; an older one read later is ignored
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T00:00:00Z", "Commander": "Jameson", "Credits": 3000})
        self.j.handle({"event": "LoadGame", "timestamp": "2025-12-01T00:00:00Z", "Commander": "Jameson", "Credits": 1})
        self.assertEqual((self.j.commander["credits"], self.j.commander["earned"]), (3000, 0))


class Materials(unittest.TestCase):
    def snap(self, ts="2026-01-01T00:00:00Z", **raw):
        return {"event": "Materials", "timestamp": ts, "Raw": [{"Name": k, "Count": v} for k, v in raw.items()],
                "Manufactured": [], "Encoded": []}

    def test_snapshot_then_deltas(self):
        st = ed_materials.new_state()
        ed_materials.apply(st, self.snap(carbon=5, iron=10, nickel=3))
        ed_materials.apply(st, {"event": "MaterialCollected", "timestamp": "2026-01-01T00:01:00Z", "Category": "Raw",
                                "Name": "carbon", "Count": 2})
        ed_materials.apply(st, {"event": "Synthesis", "timestamp": "2026-01-01T00:02:00Z", "Name": "Repair Basic",
                                "Materials": [{"Name": "iron", "Count": 2}, {"Name": "nickel", "Count": 1}]})
        ed_materials.apply(st, {"event": "MaterialDiscarded", "timestamp": "2026-01-01T00:03:00Z", "Name": "nickel", "Count": 9})
        self.assertEqual(st["counts"], {"carbon": 7, "iron": 8})

    def test_trade_sign_convention(self):
        st = ed_materials.new_state()
        ed_materials.apply(st, self.snap(arsenic=10))
        ed_materials.apply(st, {"event": "MaterialTrade", "timestamp": "2026-01-01T00:01:00Z", "TraderType": "raw",
                                "Paid": {"Material": "arsenic", "Quantity": 6},
                                "Received": {"Material": "polonium", "Quantity": 1}})
        self.assertEqual(st["counts"], {"arsenic": 4, "polonium": 1})

    def test_events_before_snapshot_ignored(self):
        st = ed_materials.new_state()
        ed_materials.apply(st, self.snap("2026-01-02T00:00:00Z", carbon=1))
        ed_materials.apply(st, {"event": "MaterialCollected", "timestamp": "2026-01-01T00:00:00Z", "Name": "carbon", "Count": 5})
        ed_materials.apply(st, self.snap("2026-01-01T00:00:00Z", carbon=99))
        self.assertEqual(st["counts"], {"carbon": 1})

    def test_boosts(self):
        counts = {"carbon": 9, "vanadium": 4, "germanium": 5, "cadmium": 2, "niobium": 3, "arsenic": 1,
                  "yttrium": 1, "polonium": 0}
        self.assertEqual(ed_materials.boosts(counts), {"basic": 4, "standard": 2, "premium": 0})
        self.assertEqual(ed_materials.craftable(counts, {"carbon": 2, "niobium": 1}), (3, "niobium"))

    def test_raw_names_and_caps(self):
        inv = ed_materials.inventory(None)
        carbon = next(r for r in inv["rows"] if r["id"] == "carbon")
        self.assertEqual((carbon["name"], carbon["grade"], carbon["cap"]), ("Carbon", 1, 300))


def org(ts, system, body, species, kind):
    return {"event": "ScanOrganic", "timestamp": ts, "SystemAddress": system, "Body": body, "ScanType": kind,
            "Species": f"$Codex_Ent_{species};", "Species_Localised": "Bacterium Aurasus",
            "Genus_Localised": "Bacterium", "Variant_Localised": "Bacterium Aurasus - Teal"}


class Samples(unittest.TestCase):
    """Batch 1: the Samples view's states, first-footfall factor and totals."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, None, 25)
        now = dt.datetime.now(dt.timezone.utc)
        self.t = lambda h: (now - dt.timedelta(hours=100 - h)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def sample_run(self, h, system, body, sp):
        for i, k in enumerate(("Log", "Sample", "Analyse")):
            self.j.handle(org(self.t(h + i * 0.01), system, body, sp, k))

    def test_states_factor_totals(self):
        s = scan(self.t(0), "Sys", 1, 5, "Sys 5")[2]; s["WasFootfalled"] = False
        self.j.handle(s)
        self.j.handle({"event": "FSDJump", "timestamp": self.t(0), "StarSystem": "Sys", "SystemAddress": 1, "StarPos": [0, 0, 0]})
        self.sample_run(1, 1, 5, "Bacterial_01")                     # sold below
        self.j.handle({"event": "SellOrganicData", "timestamp": self.t(2), "BioData": [{"Value": 1, "Bonus": 0}]})
        self.sample_run(3, 1, 6, "Bacterial_02")                     # lost below
        self.j.handle({"event": "Died", "timestamp": self.t(4)}); self.j.handle({"event": "Resurrect", "timestamp": self.t(4), "Option": "rebuy"})
        self.sample_run(5, 1, 7, "Bacterial_03")                     # aboard
        self.j.handle(org(self.t(6), 1, 8, "Bacterial_04", "Log"))   # in progress
        o = self.state.organics(30)
        by = {r["body"]: r for r in o["rows"]}
        self.assertEqual(by["5"]["state"], "sold")
        self.assertEqual(by["5"]["factor"], 5)
        self.assertEqual(by["body #6"]["state"], "lost")
        self.assertEqual(by["body #7"]["state"], "aboard")
        self.assertEqual(by["body #8"]["state"], "in progress")
        self.assertEqual(o["counts"], {"aboard": 1, "sold": 1, "lost": 1, "in progress": 1})
        self.assertEqual(by["5"]["system"]["name"], "Sys")
        if ed_outrider.ed_bio:
            self.assertEqual(o["totals"]["sold"], by["5"]["value"])


class HeaderAndTotals(unittest.TestCase):
    """Batch 2: commander, position details and the all-time history row."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, None, 25)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def test_payload_fields(self):
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:00Z", "Commander": "Jameson", "Credits": 1000})
        self.jump("2026-01-01T00:01:00Z", 1, 0); self.jump("2026-01-01T00:02:00Z", 2, 10); self.jump("2026-01-01T00:03:00Z", 1, 0)
        p = self.state.payload()
        self.assertEqual(p["commander"]["name"], "Jameson")
        self.assertEqual(p["commander"]["credits"], 1000)
        self.assertEqual(p["position"]["visits"], 2)
        self.assertIsNone(p["materials"])

    def test_exact_string_ids(self):   # F57: an id64 above 2^53 is rounded by a JavaScript number
        big = 2 ** 53 + 1
        self.jump("2026-01-01T00:01:00Z", big + 2, 0); self.jump("2026-01-01T00:02:00Z", big, 10)
        self.state.target = {"id64": big + 4, "name": "T", "status": "unreported", "seq": 1}
        p = self.state.payload()
        self.assertEqual((p["position"]["id"], p["previous"]["id"], p["target"]["id"]),
                         (str(big), str(big + 2), str(big + 4)))
        self.assertEqual(p["position"]["id64"], big)            # the number stays for what already uses it
        read = p["freshness"]["read"]
        self.j.offsets["/j/Journal.2026-01-01T000000.01.log"] = 1234
        self.assertEqual(self.state.payload()["freshness"]["read"], read + 1234)   # moves with every line read

    def test_all_time_equals_sum_of_sessions(self):
        for i, ts in enumerate(("2020-01-01T00:00:00Z", "2020-01-01T00:10:00Z", "2020-01-01T00:20:00Z",
                                "2020-02-01T00:00:00Z", "2020-02-01T00:30:00Z")):
            self.jump(ts, i + 1, i * 7)
        h = self.state.history(3650 * 3)
        self.assertEqual(len(h["sessions"]), 2)
        self.assertEqual(h["all_time"]["jumps"], sum(s["jumps"] for s in h["sessions"]))
        self.assertAlmostEqual(h["all_time"]["ly"], sum(s["ly"] for s in h["sessions"]), places=1)
        self.assertEqual(h["all_time"]["since"], "2020-01-01T00:00:00Z")
        # a short window still reports everything in the all-time row
        self.assertEqual(self.state.history(1)["all_time"]["jumps"], 5)


class Log(unittest.TestCase):
    """Batch 3: formatters never throw, file windows, cursors and the live tail."""

    SAMPLES = [
        {"event": "FSDJump", "StarSystem": "Sys", "JumpDist": 32.1, "FuelUsed": 2.4, "BoostUsed": 4},
        {"event": "StartJump", "JumpType": "Hyperspace", "StarSystem": "Sys", "StarClass": "K"},
        {"event": "FSDTarget", "Name": "Sys", "StarClass": "M", "RemainingJumpsInRoute": 3},
        {"event": "Location", "StarSystem": "Sys", "Docked": True, "StationName": "Port"},
        {"event": "CarrierJump", "StarSystem": "Sys"}, {"event": "SupercruiseExit", "Body": "Sys 1", "BodyType": "Planet"},
        {"event": "Touchdown", "Body": "Sys 1", "Latitude": 1.5, "Longitude": -3.2}, {"event": "Docked", "StationName": "Port"},
        {"event": "FuelScoop", "Scooped": 2.1, "Total": 30.5}, {"event": "JetConeBoost", "BoostValue": 4.0},
        {"event": "Scan", "BodyName": "Sys 1", "StarSystem": "Sys", "PlanetClass": "Icy body", "MassEM": 1.1,
         "WasDiscovered": False, "WasMapped": False, "ScanType": "Detailed", "Landable": True, "SurfaceGravity": 1.9},
        {"event": "Scan", "BodyName": "Sys", "StarSystem": "Sys", "StarType": "K", "StellarMass": 0.8, "Age_MY": 10},
        {"event": "Scan", "BodyName": "Sys A Belt Cluster 1", "ScanType": "AutoScan"},
        {"event": "FSSDiscoveryScan", "BodyCount": 15, "NonBodyCount": 3, "Progress": 0.5},
        {"event": "FSSAllBodiesFound", "Count": 15, "SystemName": "Sys"},
        {"event": "FSSBodySignals", "BodyName": "Sys 1", "Signals": [{"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 5}]},
        {"event": "SAASignalsFound", "BodyName": "Sys 1", "Signals": [], "Genuses": [{"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"}]},
        {"event": "SAAScanComplete", "BodyName": "Sys 1", "ProbesUsed": 6, "EfficiencyTarget": 8},
        {"event": "ScanBaryCentre", "BodyID": 3, "SemiMajorAxis": 1e10},
        {"event": "MultiSellExplorationData", "Discovered": [{}, {}], "TotalEarnings": 8200000, "Bonus": 1100000},
        {"event": "SellExplorationData", "Systems": ["a"], "TotalEarnings": 5},
        {"event": "ScanOrganic", "ScanType": "Log", "Species_Localised": "Bacterium Cerbrus", "Body": 7, "SystemAddress": 1},
        {"event": "CodexEntry", "Name_Localised": "Thing", "Category_Localised": "Bio", "IsNewEntry": True, "VoucherAmount": 5000},
        {"event": "SellOrganicData", "BioData": [{"Value": 1, "Bonus": 2}]},
        {"event": "Disembark", "OnPlanet": True, "Body": "Sys 1"}, {"event": "Embark", "SRV": True},
        {"event": "Loadout", "ShipName": "Mandalay", "Ship": "mandalay", "MaxJumpRange": 78.07, "Rebuy": 100},
        {"event": "RefuelAll", "Amount": 5.0, "Cost": 200}, {"event": "Resurrect", "Option": "rebuy", "Cost": 5},
        {"event": "Died"}, {"event": "HullDamage", "Health": 0.8}, {"event": "Synthesis", "Name": "FSD Premium"},
        {"event": "EngineerCraft", "Engineer": "Felicity", "BlueprintName": "FSD_LongRange", "Level": 5, "Slot": "FSD"},
        {"event": "MaterialCollected", "Name": "carbon", "Count": 3}, {"event": "MaterialTrade", "Paid": {}, "Received": {}},
        {"event": "Materials", "Raw": [{"Count": 3}]}, {"event": "LoadGame", "Commander": "J", "Credits": 5, "GameMode": "Solo"},
        {"event": "CarrierJumpRequest", "SystemName": "Sys", "DepartureTime": "2026-01-01T12:34:00Z"},
        {"event": "CarrierStats", "Name": "C", "Callsign": "X", "FuelLevel": 500, "Finance": {"CarrierBalance": 9}},
        {"event": "CarrierDepositFuel", "Amount": 5, "Total": 505}, {"event": "SupercruiseDestinationDrop", "Type": "$x;"},
        {"event": "SomethingNew", "Thing_Localised": "Nice", "Thing": "$nice;", "Count": 3, "Ratio": 0.5, "Nested": {"a": 1}},
    ]

    def test_formatters_never_throw(self):
        for ev in self.SAMPLES:
            s = ed_log.summary(dict(ev, timestamp="2026-01-01T00:00:00Z"), {(1, 7): "B 7"})
            self.assertIsInstance(s, str, ev["event"])
            self.assertTrue(s, ev["event"])
        # every formatter survives an event with no fields at all
        for name in ed_log.LOG_FORMAT:
            self.assertIsInstance(ed_log.summary({"event": name}), str, name)

    def test_specific_summaries(self):
        self.assertEqual(ed_log.summary(self.SAMPLES[0]), "→ Sys · 32.10 ly · 2.40 t · boosted")
        self.assertIn("🏁 undiscovered", ed_log.summary(self.SAMPLES[10]))
        self.assertIn("landable 0.19 g", ed_log.summary(self.SAMPLES[10]))
        self.assertEqual(ed_log.summary(self.SAMPLES[21], {(1, 7): "B 7"}), "Log: Bacterium Cerbrus on B 7")
        self.assertEqual(ed_log.fallback({"event": "X", "Thing": "$nice;", "Thing_Localised": "Nice", "Count": 3}),
                         "X · Thing: Nice · Count: 3")
        self.assertEqual(ed_log.fallback({"event": "RepairDrone"}), "Repair drone")   # never blank
        self.assertEqual(ed_log.category("CarrierBankTransfer"), "carrier")
        self.assertEqual(ed_log.category("Music"), "noise")

    def test_file_keys_and_window(self):
        self.assertEqual(ed_log.file_key("/x/Journal.2026-09-27T220610.01.log"), ("2026-09-27T22:06:10", 1))
        self.assertEqual(ed_log.file_key("Journal.180615221530.02.log"), ("2018-06-15T22:15:30", 2))
        files = [(("2026-01-01T00:00:00", 1), "a"), (("2026-01-05T00:00:00", 1), "b"), (("2026-01-09T00:00:00", 1), "c")]
        now = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual([p for _, p in ed_log.window(files, 2, now)], ["b", "c"])   # the one before runs into it
        self.assertEqual([p for _, p in ed_log.window(files, 30, now)], ["a", "b", "c"])

    def test_read_paging_tail_and_half_line(self):
        import tempfile
        d = tempfile.mkdtemp()
        now = dt.datetime.now(dt.timezone.utc)
        ts = lambda m: (now - dt.timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        name = lambda m: (now - dt.timedelta(minutes=m)).strftime("Journal.%Y-%m-%dT%H%M%S.01.log")
        import json as _j
        with open(os.path.join(d, name(60)), "w") as f:
            for i in range(5):
                f.write(_j.dumps({"timestamp": ts(60 - i), "event": "FSDJump", "StarSystem": f"Old{i}", "JumpDist": 1, "FuelUsed": 1}) + "\n")
        p2 = os.path.join(d, name(30))
        with open(p2, "w") as f:
            f.write(_j.dumps({"timestamp": ts(30), "event": "Music", "MusicTrack": "x"}) + "\n")
            for i in range(3):
                f.write(_j.dumps({"timestamp": ts(29 - i), "event": "FSDJump", "StarSystem": f"New{i}", "JumpDist": 1, "FuelUsed": 1}) + "\n")
            f.write('{"timestamp":"' + ts(1) + '","event":"FSDJump","StarSys')   # half-written line
        r = ed_log.read_log([d], days=1, limit=4)
        self.assertEqual([x["system"] for x in r["rows"]], ["New2", "New1", "New0", "Old4"])
        r2 = ed_log.read_log([d], days=1, limit=4, before=r["next"])
        self.assertEqual([x["system"] for x in r2["rows"]], ["Old3", "Old2", "Old1", "Old0"])
        self.assertTrue(ed_log.read_log([d], days=1, noise=True)["rows"][3]["event"] == "Music")
        self.assertEqual(len(ed_log.read_log([d], days=1, q="new1")["rows"]), 1)
        self.assertEqual(len(ed_log.read_log([d], days=1, q="→ old")["rows"]), 5)   # matches the summary only
        tail = r["newest"]
        with open(p2, "a") as f:
            f.write('tem":"Fresh","JumpDist":1,"FuelUsed":1}\n')
        t = ed_log.read_log([d], after=tail)
        self.assertEqual([x["system"] for x in t["rows"]], ["Fresh"])
        self.assertEqual(ed_log.read_log([d], after=t["newest"])["rows"], [])


def B(name, bid=None, parents=None, kind="Planet", main=False):
    pf = None if parents is None else [{"kind": k, "id": v} for k, v in parents]
    return {"name": name, "body_id": bid, "parents_full": pf, "type": kind, "main": main}


def shape(nodes):
    """A tree as nested tuples of names/labels, for readable assertions."""
    return [(n.get("name") or n["label"], shape(n["children"])) if n["children"] else (n.get("name") or n["label"]) for n in nodes]


class Schematic(unittest.TestCase):
    """Batch 5: the system hierarchy from Parents chains, names, and barycentres."""

    def test_single_star_planets_moons(self):
        bodies = [B("Sys", 0, [], "Star", True), B("1", 1, [("Star", 0)]), B("2", 2, [("Star", 0)]),
                  B("2 a", 3, [("Planet", 2), ("Star", 0)]), B("2 a a", 4, [("Planet", 3), ("Planet", 2), ("Star", 0)])]
        tree, parent_of = ed_outrider.build_tree("Sys", bodies)
        self.assertEqual(shape(tree), [("Sys", ["1", ("2", [("2 a", ["2 a a"])])])])
        self.assertEqual(parent_of["2 a"], ("b", "2"))

    def test_binary_with_barycentre(self):
        bodies = [B("A", 1, [("Null", 0)], "Star", True), B("B", 2, [("Null", 0)], "Star"),
                  B("AB 1", 3, [("Null", 0)]), B("A 1", 4, [("Star", 1), ("Null", 0)]),
                  B("AB 2", 5, None)]                     # no Parents: found by name through the barycentre label
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        self.assertEqual(shape(tree), [("A+B", [("A", ["A 1"]), "B", "AB 1", "AB 2"])])

    def test_name_only(self):
        bodies = [B("A", None, None, "Star", True), B("A 6", None, None), B("A 6 a", None, None), B("7", None, None)]
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        self.assertEqual(shape(tree), [("A", ["7", ("A 6", ["A 6 a"])])])

    def test_named_body_with_parents_only(self):
        bodies = [B("Sol", 0, [], "Star", True), B("Earth", 3, [("Star", 0)]), B("Moon", 4, [("Planet", 3), ("Star", 0)])]
        tree, _ = ed_outrider.build_tree("Sol", bodies)
        self.assertEqual(shape(tree), [("Sol", [("Earth", ["Moon"])])])

    def test_unscanned_barycentre_and_parent(self):
        # the Null the pair orbits was never scanned and the planet the moon orbits is unknown: both still appear
        bodies = [B("A", 1, [("Null", 0)], "Star", True), B("B", 2, [("Null", 0)], "Star"),
                  B("C 1 a", 9, [("Planet", 8), ("Star", 7), ("Null", 6)])]
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        labels = shape(tree)
        self.assertIn(("A+B", ["A", "B"]), labels)
        self.assertIn(("barycentre #6", [("body #7", [("body #8", ["C 1 a"])])]), labels)

    def test_cycle_does_not_hang(self):
        bodies = [B("X", 1, [("Planet", 2)]), B("Y", 2, [("Planet", 1)])]
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        self.assertEqual(len(tree), 1)


class Highlights(unittest.TestCase):
    def test_highlight_settings(self):
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertEqual((st["body_highlight"], st["bio_highlight"]), (500_000, 10_000_000))
        st = ed_outrider.settings_from({"defaults": {"body_highlight_level": 750000, "biology_highlight_value": 5000000}},
                                       args, None, ([], []))
        self.assertEqual((st["body_highlight"], st["bio_highlight"]), (750_000, 5_000_000))
        import tomllib
        back = tomllib.loads(ed_outrider.config_text(st))["defaults"]
        self.assertEqual((back["body_highlight_level"], back["biology_highlight_value"]), (750_000, 5_000_000))
        self.assertTrue(st["max_include_bonus"])
        st = ed_outrider.settings_from({"defaults": {"body_max_value_include_bonus": False}}, args, None, ([], []))
        self.assertFalse(st["max_include_bonus"])
        self.assertIs(tomllib.loads(ed_outrider.config_text(st))["defaults"]["body_max_value_include_bonus"], False)


class BarycentreLabels(unittest.TestCase):
    def test_star_orbiting_a_pair(self):
        # A circles the centre it shares with the B-C pair (Drojau TF-H c13-3)
        bodies = [B("A", 1, [("Null", 0)], "Star", True), B("B", 3, [("Null", 2), ("Null", 0)], "Star"),
                  B("C", 4, [("Null", 2), ("Null", 0)], "Star")]
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        self.assertEqual(tree[0]["label"], "A+(B+C)")
        self.assertEqual(tree[0]["children"][1]["label"], "B+C")


class RadiusChoices(unittest.TestCase):
    def test_radius_choices(self):
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertEqual(st["radius_choices"], [20.0, 25.0, 30.0, 40.0, 50.0])
        st = ed_outrider.settings_from({"server": {"radius_choices": [80, 25, 25, 0, 50]}}, args, None, ([], []))
        self.assertEqual(st["radius_choices"], [25.0, 50.0, 80.0])   # sorted, de-duplicated, zero dropped
        import tomllib
        self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["server"]["radius_choices"], [25, 50, 80])


class BioSearch(unittest.TestCase):
    """Search: bodies with bio you have not finished, by what the rest could pay."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")

    def test_finished_bodies_drop_out_and_threshold_applies(self):
        recs = [{"name": "1", "type": "Planet", "subtype": "Rocky body", "body_id": 1, "bio": 1},
                {"name": "2", "type": "Planet", "subtype": "Rocky body", "body_id": 2, "bio": 2}]
        # body 1: its one species analysed; body 2: one of two analysed
        for bid, g in ((1, "Bacterium"), (2, "Stratum")):
            self.db.execute("INSERT INTO own_organic (system, body_id, species, genus_name, species_name, samples, done_ts, ts) "
                            "VALUES (9, ?, 'x', ?, 'y', 3, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')", (bid, g))
        hits = ed_outrider.bio_hits(self.db, 9, "Sys", 0, 0, 0, recs, 0)
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]["t"].startswith("2 · 1 of 2 unscanned"))
        self.assertEqual(hits[0]["body"], "2")
        # an unpriceable remainder never passes a credit threshold
        with unittest.mock.patch.object(ed_outrider, "bio_guess", return_value=(None, [])):
            self.assertEqual(ed_outrider.bio_hits(self.db, 9, "Sys", 0, 0, 0, recs, 1_000_000), [])
            self.assertEqual(len(ed_outrider.bio_hits(self.db, 9, "Sys", 0, 0, 0, recs, 0)), 1)


class SpanshGenera(unittest.TestCase):
    def test_dump_genera_as_codes_or_objects(self):
        b = {"name": "Sys 1", "type": "Planet", "subType": "Rocky body",
             "signals": {"genuses": ["$Codex_Ent_Bacterial_Genus_Name;", {"name": "Stratum"}]}}
        self.assertEqual(ed_outrider.record_from_dump("Sys", b)["genera"], ["Bacterium", "Stratum"])


class LatestPickup(unittest.TestCase):
    """Batch 0.2: data is judged by your latest scan, maps separately; lost data is recoverable."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        import types
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def ev(self, ts, **kw):
        self.j.handle(dict(kw, timestamp=ts))

    def body(self):
        self.db.commit()
        return next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == "5")

    def lose_ship(self, ts):
        self.ev(ts, event="Died"); self.ev(ts, event="Resurrect", Option="rebuy")

    def test_already_discovered_body_rescanned_after_loss_counts(self):
        self.j.handle(scan("2026-01-01T00:01:00Z", "Sys", 1, 5, "Sys 5", disc=True)[2])
        self.lose_ship("2026-01-02T00:00:00Z")
        self.assertEqual(self.body()["value_parts"]["scan_state"], "lost")
        self.j.handle(scan("2026-01-03T00:01:00Z", "Sys", 1, 5, "Sys 5", disc=True)[2])
        b = self.body()
        self.assertEqual(b["value_parts"]["scan_state"], "unsold")
        self.assertGreater(b["value_now"], 0)

    def test_map_lost_with_ship_is_not_counted_until_remapped(self):
        self.j.handle(scan("2026-01-01T00:01:00Z", "Sys", 1, 5, "Sys 5")[2])
        self.ev("2026-01-01T00:02:00Z", event="SAAScanComplete", SystemAddress=1, BodyID=5, BodyName="Sys 5")
        mapped_now = self.body()["value_now"]
        self.lose_ship("2026-01-02T00:00:00Z")
        self.j.handle(scan("2026-01-03T00:01:00Z", "Sys", 1, 5, "Sys 5")[2])     # rescanned, not remapped
        b = self.body()
        self.assertFalse(b["mapped"]); self.assertFalse(b["first_mapped"])
        self.assertEqual(b["map_state"], "lost")
        self.assertLess(b["value_now"], mapped_now)                  # the scan only
        self.assertEqual(b["value_now"] + b["value_parts"]["carto_left"], mapped_now)   # the map is still there to redo
        self.ev("2026-01-03T00:02:00Z", event="SAAScanComplete", SystemAddress=1, BodyID=5, BodyName="Sys 5")
        self.assertEqual(self.body()["value_now"], mapped_now)

    def test_lost_scan_not_rescanned_is_recoverable_in_max(self):
        self.j.handle(scan("2026-01-01T00:01:00Z", "Sys", 1, 5, "Sys 5")[2])
        full = self.body()["value_max"]
        self.lose_ship("2026-01-02T00:00:00Z")
        b = self.body()
        self.assertEqual(b["value_now"], 0)
        self.assertEqual(b["value_max"], full)     # scan and map it again: the same credits are there

    def test_sold_data_is_done(self):
        self.j.handle(scan("2026-01-01T00:01:00Z", "Sys", 1, 5, "Sys 5")[2])
        self.ev("2026-01-01T00:02:00Z", event="SAAScanComplete", SystemAddress=1, BodyID=5, BodyName="Sys 5")
        self.j.handle(sale("2026-01-02T00:00:00Z", ["Sys"])[2])
        b = self.body()
        self.assertEqual((b["value_now"], b["value_max"]), (0, 0))
        self.assertTrue(b["mapped"])


class DumpPricing(unittest.TestCase):
    """Batch 0.2: Spansh bodies are priced with the same formula as your scans."""

    def test_dump_body_priced_like_a_scan(self):
        dump = {"name": "Sys 1", "type": "Planet", "subType": "Water world", "earthMasses": 0.5,
                "terraformingState": "Candidate for terraforming", "bodyId": 1}
        r = ed_outrider.record_from_dump("Sys", dump)
        cv = ed_outrider.carto_values(r, False, None, None, None)
        expect = ed_unsold.body_value({"PlanetClass": "Water world", "MassEM": 0.5, "TerraformState": "Terraformable"},
                                      True, False, True)
        self.assertEqual(cv["left"], expect)
        self.assertEqual(cv["now"], 0)
        # the same body once you have scanned it (no bonuses: someone discovered it) is worth the same in total
        f = {"was_discovered": 1, "was_mapped": 1}
        scanned = ed_outrider.carto_values(r, True, f, "unsold", None)
        self.assertEqual(scanned["now"] + scanned["left"], expect)

    def test_star_and_unpriceable(self):
        star = ed_outrider.record_from_dump("Sys", {"name": "Sys", "type": "Star", "subType": "Neutron Star", "solarMasses": 1.4})
        self.assertEqual(star["ed"]["StarType"], "N")
        self.assertGreater(ed_outrider.carto_values(star, False, None, None, None)["left"], 20000)
        odd = ed_outrider.record_from_dump("Sys", {"name": "Sys 2", "type": "Planet", "subType": "Icy body"})   # no mass
        self.assertIsNone(odd["ed"])


class DumpRetries(unittest.TestCase):
    """Batch 0.1: failed body-detail fetches are retried a few times, logged, then given up on."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.state = ed_outrider.State(self.db, ed_outrider.Journals(self.db),
                                       types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def test_cap(self):
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(ed_outrider.DUMP_MAX_TRIES):
                self.state.dump_failed(7, RuntimeError("boom"))
                if 7 in self.state.failed_dumps and self.state.dump_tries[7] < ed_outrider.DUMP_MAX_TRIES:
                    self.state.failed_dumps.discard(7)
        self.assertNotIn(7, self.state.failed_dumps)
        self.assertEqual(err.getvalue().count("RuntimeError"), 2)   # first failure and giving up, not every retry

    def test_partial_while_details_pending(self):
        self.db.execute("INSERT INTO visits VALUES (7, 'Sys', 0, 0, 0, 't', 't', 1)")
        search_level = {"name": "Sys 1", "type": "Planet", "subtype": "Icy body", "full": False, "value": 1000,
                        "scan_value": 500}
        self.state.bases[7] = ("spansh", {"name": "Sys", "x": 0, "y": 0, "z": 0, "records": [search_level]})
        self.assertTrue(self.state.system_detail(7)["partial"])
        self.state.dump_tries[7] = ed_outrider.DUMP_MAX_TRIES     # given up: stop asking the page to poll
        self.assertFalse(self.state.system_detail(7)["partial"])


class TickSafety(unittest.TestCase):
    """Batch 0.3: a bad file or a failed tick never loses or double-counts journal events."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)

    def write(self, name, events):
        import json as _j
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            for e in events:
                f.write(_j.dumps(e, separators=(",", ":")) + "\n")
        return path

    def jump(self, ts, id64, x):
        return {"timestamp": ts, "event": "FSDJump", "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0],
                "JumpDist": 10.0, "FuelUsed": 1.0}

    def tick(self):
        """What watch() does: scan, commit; on an exception roll back and reload."""
        try:
            self.j.scan_dir(self.dir)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            self.j.reload()
            return False

    def test_unreadable_file_is_skipped_not_fatal(self):
        import contextlib, io
        self.write("Journal.2026-01-01T000000.01.log", [self.jump("2026-01-01T00:00:00Z", 1, 0)])
        bad = self.write("Journal.2026-01-02T000000.01.log", [self.jump("2026-01-02T00:00:00Z", 2, 10)])
        self.write("Journal.2026-01-03T000000.01.log", [self.jump("2026-01-03T00:00:00Z", 3, 20)])
        os.chmod(bad, 0)
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertTrue(self.tick())
                self.tick()
            self.assertEqual(self.j.pos["id64"], 3)          # the newer file was still read
            self.assertEqual(err.getvalue().count("journal skipped"), 1)   # reported once, not every tick
        finally:
            os.chmod(bad, 0o644)
        self.tick()
        self.assertEqual({r[0] for r in self.db.execute("SELECT id64 FROM visits")}, {1, 2, 3})

    def test_failed_tick_is_retried_exactly(self):
        self.write("Journal.2026-01-01T000000.01.log", [
            self.jump("2026-01-01T00:00:00Z", 1, 0),
            {"timestamp": "2026-01-01T00:01:00Z", "event": "MaterialCollected", "Category": "Raw", "Name": "iron", "Count": 3},
            {"timestamp": "2026-01-01T00:02:00Z", "event": "LoadGame", "Commander": "J", "Credits": 100}])
        self.write("Journal.2026-01-02T000000.01.log", [
            {"timestamp": "2026-01-02T00:00:00Z", "event": "MultiSellExplorationData", "TotalEarnings": 50, "Discovered": []},
            self.jump("2026-01-02T00:01:00Z", 2, 10)])
        calls = {"n": 0}
        # the first file's events land, then a database error in the second file fails the tick once
        orig_handle = self.j.handle
        def flaky(ev):
            if ev.get("event") == "FSDJump" and ev.get("SystemAddress") == 2 and not calls["n"]:
                calls["n"] += 1
                raise sqlite3.OperationalError("database is locked")
            return orig_handle(ev)
        self.j.handle = flaky
        self.assertFalse(self.tick())
        self.assertTrue(self.tick())
        self.assertEqual({r[0] for r in self.db.execute("SELECT id64 FROM visits")}, {1, 2})   # nothing lost
        self.assertEqual(self.j.materials["counts"].get("iron"), 3)                             # nothing doubled
        self.assertEqual(self.j.fuel_hist, [[10.0, 1.0, None, None]] * 2)                     # one per jump
        self.assertEqual(self.j.commander["earned"], 50)


class ConfigRobustness(unittest.TestCase):
    """Batch 0.3: config mistakes are reported and survived, not tracebacks or silent nonsense."""

    ARGS = dict(journals=None, legacy=None, host=None, port=None, radius=None, db=None)

    def settings(self, cfg):
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            st = ed_outrider.settings_from(cfg, argparse.Namespace(**self.ARGS), None, ([], []))
        return st, err.getvalue()

    def test_single_folder_string(self):
        st, _ = self.settings({"journals": {"live": "C:/Games/Elite Dangerous"}})
        self.assertEqual(st["live"], ["C:/Games/Elite Dangerous"])

    def test_wrong_types_fall_back_with_a_message(self):
        st, err = self.settings({"server": {"port": "8025x", "radius": "far", "radius_choices": 25},
                                 "defaults": {"bio_min": "ten million"}})
        self.assertEqual((st["port"], st["radius"], st["bio_min"]), (8025, 25.0, ed_outrider.BIO_MIN))
        self.assertEqual(st["radius_choices"], [20.0, 25.0, 30.0, 40.0, 50.0])
        for key in ("port", "radius", "radius_choices", "bio_min"):
            self.assertIn(key, err)

    def test_quoted_number_still_works(self):
        st, err = self.settings({"server": {"port": "9000"}})
        self.assertEqual((st["port"], err), (9000, ""))


class LogTailRace(unittest.TestCase):
    def test_line_written_during_the_scan_is_not_lost(self):
        import tempfile, json as _j
        d = tempfile.mkdtemp(); now = dt.datetime.now(dt.timezone.utc)
        p = os.path.join(d, now.strftime("Journal.%Y-%m-%dT%H%M%S.01.log"))
        line = lambda n: _j.dumps({"timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "FSDJump", "StarSystem": n}) + "\n"
        with open(p, "w") as f:
            f.write(line("S0"))
        first = ed_log.read_log([d], days=1)
        real = ed_log._load
        calls = []
        def racing(path):
            e = real(path)
            if not calls:
                calls.append(1)
                with open(p, "a") as f:
                    f.write(line("S1"))
            return e
        with unittest.mock.patch.object(ed_log, "_load", racing):
            t1 = ed_log.read_log([d], after=first["newest"])
        t2 = ed_log.read_log([d], after=t1["newest"])
        self.assertEqual([r["system"] for r in t1["rows"] + t2["rows"]], ["S1"])


class NamedBodyPanel(unittest.TestCase):
    def test_named_body_finds_its_scan(self):
        import asyncio, types
        db = ed_outrider.open_db(":memory:")
        j = ed_outrider.Journals(db)
        j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sol", "SystemAddress": 10,
                  "StarPos": [0, 0, 0]})
        ev = scan("2026-01-01T00:01:00Z", "Sol", 10, 3, "Earth")[2]
        j.handle(ev)
        db.commit()
        async def lookup(id64, interactive=True):
            return None
        state = ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None), lookup=lookup), 25)
        d = asyncio.run(state.body_detail(10, "Earth"))
        self.assertEqual(d["full_name"], "Earth")          # not the fabricated "Sol Earth"
        self.assertIsNotNone(d["own"])                      # your raw scan was found


class LogFixes(unittest.TestCase):
    def folder(self, files):
        import tempfile, json as _j
        d = tempfile.mkdtemp()
        for name, events in files.items():
            with open(os.path.join(d, name), "w") as f:
                for e in events:
                    f.write(_j.dumps(e, separators=(",", ":")) + "\n")
        return d

    def test_search_ignores_json_keys(self):
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        d = self.folder({dt.datetime.now(dt.timezone.utc).strftime("Journal.%Y-%m-%dT%H%M%S.01.log"): [
            {"timestamp": now, "event": "FSDJump", "StarSystem": "Alpha", "StarPos": [0, 0, 0], "JumpDist": 5, "FuelUsed": 1},
            {"timestamp": now, "event": "Scan", "BodyName": "Alpha 1", "StarSystem": "Alpha", "PlanetClass": "Icy body",
             "WasMapped": False, "ScanType": "Detailed"}]})
        self.assertEqual(len(ed_log.read_log([d], days=1, q="star")["rows"]), 0)     # only the StarSystem key has it
        self.assertEqual(len(ed_log.read_log([d], days=1, q="alpha")["rows"]), 2)    # a value in both
        self.assertEqual(len(ed_log.read_log([d], days=1, q="icy")["rows"]), 1)

    def test_before_cursor_past_the_end(self):
        now = dt.datetime.now(dt.timezone.utc)
        name = now.strftime("Journal.%Y-%m-%dT%H%M%S.01.log")
        d = self.folder({name: [{"timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "event": "Music"}]})
        r = ed_log.read_log([d], days=1, before=f"{name}|999999", noise=True)   # no IndexError
        self.assertEqual(len(r["rows"]), 1)

    def test_files_ordered_by_first_line_not_local_name(self):
        # DST fall-back: the newer session's local-time name sorts before the older one's
        d = self.folder({"Journal.2026-10-25T013000.01.log": [{"timestamp": "2026-10-25T00:30:00Z", "event": "Music"}],
                         "Journal.2026-10-25T011500.01.log": [{"timestamp": "2026-10-25T01:15:00Z", "event": "Music"}]})
        order = [os.path.basename(p) for _, p in ed_log.journal_files([d])]
        self.assertEqual(order, ["Journal.2026-10-25T013000.01.log", "Journal.2026-10-25T011500.01.log"])

    def test_legacy_sale_counts_systems(self):
        s = ed_log.summary({"event": "SellExplorationData", "Systems": ["A", "B", "C", "D", "E"], "Discovered": ["B"],
                            "TotalEarnings": 1500, "Bonus": 500})
        self.assertTrue(s.startswith("Sold data from 5 systems (1 new)"), s)

    def test_organic_body_name_from_touchdown(self):
        now = dt.datetime.now(dt.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        d = self.folder({now.strftime("Journal.%Y-%m-%dT%H%M%S.01.log"): [
            {"timestamp": ts, "event": "Touchdown", "Body": "Sys 8 g", "BodyID": 29, "SystemAddress": 5, "StarSystem": "Sys"},
            {"timestamp": ts, "event": "ScanOrganic", "ScanType": "Sample", "Species_Localised": "Bacterium Aurasus",
             "SystemAddress": 5, "Body": 29}]})
        rows = ed_log.read_log([d], days=1, cats={"bio"})["rows"]
        self.assertEqual(rows[0]["summary"], "Sample: Bacterium Aurasus on 8 g")


class BrownDwarfPairLabel(unittest.TestCase):
    def test_star_and_planet_sharing_a_centre(self):
        # Scaulae GH-V e2-1: a numbered brown dwarf "15" and planet "16" circle a shared centre
        bodies = [B("A", 1, [], "Star", True), B("15", 30, [("Null", 29), ("Star", 1)], "Star"),
                  B("16", 31, [("Null", 29), ("Star", 1)])]
        tree, _ = ed_outrider.build_tree("Sys", bodies)
        bary = tree[0]["children"][0]
        self.assertEqual(bary["label"], "15 + 16")


class Batch1Server(unittest.TestCase):
    """Batch 1: hull, danger moments, sales, finds and the priced leaving summary."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def test_hull_only_counts_your_ship(self):
        self.j.handle({"event": "HullDamage", "timestamp": "2026-01-01T00:01:00Z", "Health": 0.48, "PlayerPilot": True})
        self.assertEqual(self.j.hull["pct"], 48)
        self.j.handle({"event": "HullDamage", "timestamp": "2026-01-01T00:02:00Z", "Health": 0.1, "PlayerPilot": True, "Fighter": True})
        self.j.handle({"event": "HullDamage", "timestamp": "2026-01-01T00:02:00Z", "Health": 0.2, "PlayerPilot": False})
        self.assertEqual(self.j.hull["pct"], 48)                       # a fighter or the SRV is not the ship
        self.j.handle({"event": "RepairAll", "timestamp": "2026-01-01T00:03:00Z", "Cost": 100})
        self.assertEqual(self.j.hull["pct"], 100)

    def test_sales_merge_into_one(self):
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": "2026-01-01T01:00:00Z", "TotalEarnings": 5000,
                       "Discovered": [{"SystemName": "Sys", "NumBodies": 3}]})
        self.j.handle({"event": "SellOrganicData", "timestamp": "2026-01-01T01:04:00Z", "BioData": [{"Value": 100, "Bonus": 400}]})
        self.assertEqual(self.j.last_sale["carto"], 5000)
        self.assertEqual(self.j.last_sale["bio"], 500)                  # same visit: one sale
        self.j.handle({"event": "SellOrganicData", "timestamp": "2026-01-02T01:00:00Z", "BioData": [{"Value": 7, "Bonus": 0}]})
        self.assertEqual((self.j.last_sale["carto"], self.j.last_sale["bio"]), (0, 7))

    def test_moments_priced(self):
        ev = scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4")[2]
        ev.update(PlanetClass="Water world", MassEM=0.5, TerraformState="Terraformable")
        self.j.handle(ev)
        self.j.handle({"event": "HeatDamage", "timestamp": "2026-01-01T00:06:00Z"})
        self.db.commit()
        m = self.state.moments_summary()
        scanm = next(x for x in m if x["kind"] == "scan")
        self.assertEqual((scanm["body"], scanm["terraformable"]), ("4", True))
        self.assertGreater(scanm["base_value"], 500000)
        self.assertTrue(any(x["kind"] == "heat" for x in m))
        self.assertEqual(m[-1]["seq"], self.j.moment_seq)

    def test_leaving_lists_increments(self):
        ev = scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4", disc=True)[2]
        ev.update(PlanetClass="Sudarsky class II gas giant", MassEM=300)
        self.j.handle(ev)
        self.db.commit()
        l = self.state.leaving_summary(1)
        u = l["unmapped"][0]
        self.assertEqual(u["body"], "4")
        self.assertFalse(u["special"])
        self.assertGreater(u["increment"], 0)


class Batch2Server(unittest.TestCase):
    """Batch 2: jet-cone boost, stellar phenomena, the on-body strip and the in-game destination."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def test_boost_until_the_next_jump(self):
        self.j.handle({"event": "JetConeBoost", "timestamp": "2026-01-01T00:01:00Z", "BoostValue": 3.0})
        self.assertEqual(self.state.payload()["boost"], 3.0)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:02:00Z", "StarSystem": "Two", "SystemAddress": 2,
                       "StarPos": [100, 0, 0], "BoostUsed": 4})
        self.assertIsNone(self.state.payload()["boost"])

    def test_phenomena_found_then_reached(self):
        self.j.handle({"event": "FSSSignalDiscovered", "timestamp": "2026-01-01T00:01:00Z", "SystemAddress": 1,
                       "SignalName": "$Fixed_Event_Life_Cloud;", "SignalType": "Codex"})
        self.j.handle({"event": "FSSSignalDiscovered", "timestamp": "2026-01-01T00:01:00Z", "SystemAddress": 1,
                       "SignalName": "$USS_Type_Salvage;"})                                  # ordinary signal: ignored
        rows = [dict(r) for r in self.db.execute("SELECT kind, reached_ts FROM phenomena")]
        self.assertEqual(rows, [{"kind": "cloud", "reached_ts": None}])
        self.j.handle({"event": "SupercruiseDestinationDrop", "timestamp": "2026-01-01T00:09:00Z", "Type": "$Fixed_Event_Life_Cloud;"})
        self.assertEqual(self.db.execute("SELECT reached_ts FROM phenomena").fetchone()[0], "2026-01-01T00:09:00Z")

    def test_phenomena_lines_pass_the_filter(self):
        import tempfile, json as _j
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "Journal.2026-01-01T000000.01.log"), "w") as f:
            f.write(_j.dumps({"timestamp": "2026-01-01T00:05:00Z", "event": "FSSSignalDiscovered", "SystemAddress": 1,
                              "SignalName": "$Fixed_Event_Life_Ring;"}, separators=(",", ":")) + "\n")
        self.j.scan_dir(d)
        self.assertEqual(self.db.execute("SELECT kind FROM phenomena").fetchone()[0], "ring")

    def status(self, **kw):
        self.j.status_json = dict({"live": True, "fuel_main": 20, "flags": 0, "flags2": 0}, **kw)

    def test_on_body(self):
        self.status(body="Sys A 4", flags=2)                        # landed
        self.assertEqual(self.state.on_body()["body"], "A 4")
        self.status(body="Sys A 4", flags2=1)                       # on foot
        self.assertEqual(self.state.on_body()["how"], "on foot")
        self.status(body="Sys A 4")                                 # flying near it: not on it
        self.assertIsNone(self.state.on_body())

    def test_destination(self):
        self.status(destination={"System": 1, "Body": 7, "Name": "Sys 7 a"})
        self.assertEqual(self.state.destination(), {"body_id": 7, "name": "7 a", "near": None})
        self.status(destination={"System": 1, "Body": 7, "Name": "Sys 7 a"}, body="Sys A 1")   # P13: flying near A 1
        self.assertEqual(self.state.destination()["near"], "A 1")
        self.status(destination={"System": 99, "Body": 7, "Name": "Elsewhere 7"})   # another system: not a body here
        self.assertIsNone(self.state.destination())


class Batch4Ledger(unittest.TestCase):
    """Batch 4: sale payouts, trips between sales, what a ship loss cost, ranks."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def sell(self, ts, total, systems):
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": ts, "TotalEarnings": total, "BaseValue": total, "Bonus": 0,
                       "Discovered": [{"SystemName": s, "NumBodies": 1} for s in systems]})

    def test_trips_merge_batches_and_price_losses(self):
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        self.j.handle(scan("2026-01-01T00:01:00Z", "S1", 1, 0, "S1", star=True)[2])
        self.sell("2026-01-02T00:00:00Z", 100, ["S1"])
        self.sell("2026-01-02T00:05:00Z", 50, [])                 # a second batch at the same station
        self.jump("2026-01-03T00:00:00Z", 2, 10)
        self.j.handle(scan("2026-01-03T00:01:00Z", "S2", 2, 0, "S2", star=True)[2])
        self.j.handle({"event": "Died", "timestamp": "2026-01-04T00:00:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-04T00:00:00Z", "Option": "rebuy"})
        self.db.commit()
        L = self.state.ledger()
        self.assertEqual(len(L["trips"]), 1)
        self.assertEqual(L["trips"][0]["paid"], 150)
        self.assertEqual(len(L["losses"]), 1)
        self.assertEqual(L["losses"][0]["bodies"], 1)              # S2's star died with the ship; S1's was sold
        self.assertGreater(L["losses"][0]["value"], 0)
        self.assertEqual(L["since_last_sale"]["jumps"], 1)

    def test_ranks_named(self):
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:00Z", "Commander": "J", "Credits": 1})
        self.j.handle({"event": "Rank", "timestamp": "2026-01-01T00:00:01Z", "Explore": 10, "Exobiologist": 7})
        self.j.handle({"event": "Progress", "timestamp": "2026-01-01T00:00:01Z", "Explore": 24, "Exobiologist": 43})
        r = self.state.commander_summary()["ranks"]
        self.assertEqual((r["Explore"]["name"], r["Explore"]["progress"]), ("Elite II", 24))
        self.j.handle({"event": "Promotion", "timestamp": "2026-01-02T00:00:00Z", "Explore": 11})
        r = self.state.commander_summary()["ranks"]
        self.assertEqual((r["Explore"]["name"], r["Explore"]["progress"]), ("Elite III", 0))


class Curiosities(unittest.TestCase):
    def test_flags(self):
        star = {"name": "A", "type": "Star", "radius_km": 700000, "body_id": 0}
        hot = {"name": "1", "type": "Planet", "subtype": "Class I gas giant", "sma_ls": 20, "radius_km": 70000}
        self.assertIn("hot Jupiter", [t for t, _ in ed_outrider.curiosities(hot, star)])
        ringed = {"name": "2", "type": "Planet", "subtype": "Icy body", "landable": True, "gravity": 3.5, "radius_km": 2000,
                  "ring_details": [{"name": "A Ring", "inner": 3e6, "outer": 30e6}], "rings": 1}
        tags = [t for t, _ in ed_outrider.curiosities(ringed)]
        self.assertEqual(set(tags), {"ringed landable", "high g", "wide rings"})
        moon = {"name": "3 a a", "type": "Planet", "parents_full": [{"kind": "Planet", "id": 5}, {"kind": "Planet", "id": 4}]}
        self.assertEqual([t for t, _ in ed_outrider.curiosities(moon)], ["moon of a moon"])
        spin = {"name": "4", "type": "Planet"}
        self.assertEqual([t for t, _ in ed_outrider.curiosities(spin, raw={"RotationPeriod": 3600, "TidalLock": False})], ["fast spin"])
        self.assertEqual(ed_outrider.curiosities({"name": "5", "type": "Planet", "subtype": "Rocky body"}), [])

    def test_system_pair_not_close_orbit(self):
        # two planets round a barycentre that circles the star: a pair, and never a "close orbit" of the star
        # (their small orbit is around the shared centre, not the star's surface)
        star = {"name": "A", "type": "Star", "radius_km": 700000, "body_id": 1, "parents_full": []}
        via = [{"kind": "Null", "id": 7}, {"kind": "Star", "id": 1}]
        p5 = {"name": "5", "type": "Planet", "body_id": 8, "sma_ls": 1.0, "radius_km": 3000, "parents_full": via}
        p6 = {"name": "6", "type": "Planet", "body_id": 9, "sma_ls": 1.0, "radius_km": 3000, "parents_full": via}
        moon = {"name": "6 a", "type": "Planet", "body_id": 10, "sma_ls": 0.02,
                "parents_full": [{"kind": "Planet", "id": 9}] + via}
        got = ed_outrider.system_curiosities("S", [star, p5, p6, moon])
        self.assertEqual([t for t, _ in got["5"]], ["planet pair"])
        self.assertEqual([t for t, _ in got["6"]], ["planet pair"])
        self.assertEqual([t for t, _ in got["6 a"]], ["close orbit"])   # 6 a really does hug planet 6
        # a star sharing the centre stops it being a planet pair
        s2 = {"name": "B", "type": "Star", "body_id": 11, "parents_full": [{"kind": "Null", "id": 7}]}
        self.assertNotIn("5", ed_outrider.system_curiosities("S", [star, p5, s2]))


class BioColours(unittest.TestCase):
    """BioScan's colour check (a species needs a colour variant for its star or materials) and the
    undecided-genus options shown before the DSS."""

    def test_colour_ok(self):
        stratum = {"star": {"F": "Emerald", "K": "Lime", "M": "Green", "Ae": "Teal"}}
        b = lambda parents, mats=None: {"parents": parents, "materials": mats}
        s = lambda main, n=1, complete=True: {"main": {"type": main} if main else None, "stars": [{}] * n, "complete": complete}
        self.assertFalse(ed_bio._colour_ok(stratum, b(["G"]), s("G")))         # never seen at a G star
        self.assertTrue(ed_bio._colour_ok(stratum, b(["K_OrangeGiant"]), s("G")))   # giant variants count
        self.assertTrue(ed_bio._colour_ok(stratum, b(["G"]), s("M")))          # the main star counts too
        self.assertTrue(ed_bio._colour_ok(stratum, b(["AeBe"]), s("AeBe")))    # Ae is the journal's AeBe
        self.assertTrue(ed_bio._colour_ok(stratum, b(None), s("G", 2)))        # parents unknown, 2 stars: no call
        self.assertFalse(ed_bio._colour_ok(stratum, b(None), s("G", 1)))       # one star: it must be that one
        self.assertTrue(ed_bio._colour_ok(stratum, b(None), s("G", 1, False)))  # one star known, others may be (F39)
        self.assertTrue(ed_bio._colour_ok(stratum, b(["G"]), s("H")))          # black hole primary: no call
        fung = {"element": {"polonium": "Yellow", "tin": "Grey"}}
        self.assertTrue(ed_bio._colour_ok(fung, b(["G"], None), s("G")))       # materials unknown: no call
        self.assertFalse(ed_bio._colour_ok(fung, b(["G"], {"iron", "nickel"}), s("G")))
        self.assertTrue(ed_bio._colour_ok(fung, b(["G"], {"iron", "tin"}), s("G")))
        self.assertTrue(ed_bio._colour_ok(None, b(["G"]), s("G")))            # no colour table: no check

    def test_variant_names(self):   # P11: the colour variant, a candidate set that is [] whenever unsure
        aur = {"name": "Bacterium Aurasus", "colors": {"star": {"K": "Teal", "M": "Green", "F": "Lime", "Y": "Mauve"}}}
        b = lambda parents, mats=None: {"parents": parents, "materials": mats}
        s = lambda *types, complete=True: {"main": {"type": types[0]} if types else None, "complete": complete,
                                           "stars": [{"type": t} for t in types]}
        v = ed_bio.variant_names
        self.assertEqual(v(aur, b(["K"]), s("K")), ["Bacterium Aurasus - Teal"])           # K parent
        self.assertEqual(v(aur, b(["K_OrangeGiant"]), s("K_OrangeGiant")), ["Bacterium Aurasus - Teal"])
        self.assertEqual(v(aur, b([None]), s("K")), [])                  # nearest parent not a known star
        self.assertEqual(v(aur, b([]), s("K")), [])                      # only barycentres above it
        self.assertEqual(v(aur, b(None), s("K")), ["Bacterium Aurasus - Teal"])   # complete, one star: that one
        self.assertEqual(v(aur, b(None), s("K", "M")), [])               # parents unknown, two stars
        self.assertEqual(v(aur, b(["K"]), s("K", complete=False)), [])   # a star not found yet may colour it
        # another star could give another colour: in the journals a Y dwarf's moons took the F star's colour
        self.assertEqual(v(aur, b(["Y"]), s("F", "Y")), [])
        self.assertEqual(v(aur, b(["K"]), s("K", "G")), ["Bacterium Aurasus - Teal"])   # G gives no colour: no rival
        self.assertEqual(v(aur, b(["K"]), s("K", "K")), ["Bacterium Aurasus - Teal"])   # two K stars agree
        self.assertEqual(v(aur, b(["G"]), s("G")), [])                    # no colour for the parent
        self.assertEqual(v(aur, b(["K"]), s("H", "K")), [])               # black hole primary
        fung = {"name": "Fungoida Setisis", "colors": {"element": {"polonium": "Yellow", "tin": "Grey", "iron": "Red"}}}
        self.assertEqual(v(fung, b(["K"], {"tin", "polonium", "nickel"}), s("K")),
                         ["Fungoida Setisis - Yellow", "Fungoida Setisis - Grey"])   # two materials: two names
        self.assertEqual(v(fung, b(["K"], None), s("K")), [])            # materials unknown
        self.assertEqual(v({"name": "Frutexa Acus", "colors": None}, b(["K"]), s("K")), [])   # no table

    def test_variant_names_real_rules(self):
        # the colour spellings come from ExploData's tables; they match the journal's (e.g. "Ocher", "Grey")
        if not ed_bio.load_rules():
            self.skipTest("no bio_rules.json")
        cols = {c for sp in ed_bio.load_rules()["species"] for t in (sp.get("colors") or {}).values() for c in t.values()}
        self.assertIn("Ocher", cols)
        self.assertIn("Grey", cols)
        self.assertNotIn("Ochre", cols)
        self.assertNotIn("Gray", cols)

    def test_codex_per_variant(self):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        db.execute("INSERT INTO codex (ts, entry_id, name, region) VALUES ('t', 1, 'Bacterium Aurasus - Green', 'Inner Orion Spur')")
        known = ed_outrider.codex_species(db, "Inner Orion Spur")
        self.assertEqual(known, ({"bacterium aurasus - green"}, {"bacterium aurasus"}))
        self.assertEqual(ed_outrider.codex_species(db, None), (set(), set()))
        g = {"genus": "Bacterium", "best": "Bacterium Aurasus", "variants": ["Bacterium Aurasus - Teal"]}
        self.assertTrue(ed_outrider.codex_new_group(g, known))            # a new colour of a logged species
        self.assertFalse(ed_outrider.codex_new_group(dict(g, variants=["Bacterium Aurasus - Green"]), known))
        self.assertFalse(ed_outrider.codex_new_group(dict(g, variants=[]), known))   # unsure: species level
        self.assertTrue(ed_outrider.codex_new_group(dict(g, best="Bacterium Vesicula", variants=[]), known))
        self.assertFalse(ed_outrider.codex_new_group(dict(g, best=None, variants=[]), known))
        # the colour the journal logged wins over the guess
        [lg] = ed_outrider.with_logged_variants([g], {"Bacterium": "Bacterium Aurasus - Green"})
        self.assertEqual((lg["variants"], lg["variant"]), (["Bacterium Aurasus - Green"], "Bacterium Aurasus - Green"))
        self.assertFalse(ed_outrider.codex_new_group(lg, known))
        self.assertIs(ed_outrider.with_logged_variants([g], {})[0], g)

    def test_by_genus_carries_variants(self):
        cands = [{"name": "Bacterium Aurasus", "genus": "Bacterium", "value": 1000000, "variants": ["Bacterium Aurasus - Teal"]},
                 {"name": "Bacterium Vesicula", "genus": "Bacterium", "value": 500000, "variants": []}]
        [g] = ed_bio.by_genus(cands)
        self.assertEqual((g["variants"], g["variant"]), (["Bacterium Aurasus - Teal"], "Bacterium Aurasus - Teal"))
        self.assertEqual(ed_bio.by_genus(cands, ["Stratum"])[0]["variants"], [])   # unruled genus

    def test_options(self):
        cands = [{"name": "Stratum Tectonicas", "genus": "Stratum", "value": 19010800},
                 {"name": "Bacterium Aurasus", "genus": "Bacterium", "value": 1000000}]
        with unittest.mock.patch.object(ed_bio, "predict", return_value=cands):
            r = {"type": "Planet", "bio": 1}
            o = ed_outrider.bio_options(r)
            self.assertEqual((o["low"], o["high"], [g["genus"] for g in o["genera"]]),
                             (1000000, 19010800, ["Stratum", "Bacterium"]))
            self.assertIsNone(ed_outrider.bio_options(dict(r, bio=2)))   # two signals, two genera: both are there
            self.assertIsNone(ed_outrider.bio_options(dict(r, bio=0)))
            # F27: a genus sampled without a DSS takes one signal and is no longer an option
            cands.append({"name": "Fungoida Setisis", "genus": "Fungoida", "value": 1500000})
            o = ed_outrider.bio_options(dict(r, bio=2), known={"Stratum"})
            self.assertEqual((o["low"], o["high"], [g["genus"] for g in o["genera"]]),
                             (1000000, 1500000, ["Fungoida", "Bacterium"]))
            self.assertIsNone(ed_outrider.bio_options(dict(r, bio=2), known={"Stratum", "Bacterium"}))   # all known


class HonkBinding(unittest.TestCase):
    """Auto honk reads Primary Fire's keyboard binding (with modifiers) from the active controls preset."""

    def test_reads_preset(self):
        import tempfile
        import ed_honk
        self.assertEqual([ed_honk.elite_key(k) for k in ("Key_K", "Key_Numpad_0", "Key_LeftAlt", "Key_RightControl", "Joy_1")],
                         ["KEY_K", "KEY_KP0", "KEY_LEFTALT", "KEY_RIGHTCTRL", None])
        with tempfile.TemporaryDirectory() as root:
            journals = os.path.join(root, "steamuser", "Saved Games", "Frontier Developments", "Elite Dangerous")
            binds = os.path.join(root, "steamuser", "AppData", "Local", "Frontier Developments", "Elite Dangerous",
                                 "Options", "Bindings")
            os.makedirs(journals)
            os.makedirs(binds)
            with open(os.path.join(binds, "StartPreset.4.start"), "w") as f:
                f.write("My X56\nMy X56\nMy X56\nMy X56")

            def preset(secondary):
                with open(os.path.join(binds, "My X56.4.2.binds"), "w") as f:
                    f.write(f"""<?xml version="1.0" encoding="UTF-8" ?><Root PresetName="My X56"><PrimaryFire>
                        <Primary Device="SaitekX56Joystick" Key="Joy_1" />{secondary}</PrimaryFire></Root>""")
            preset('<Secondary Device="Keyboard" Key="Key_K"><Modifier Device="Keyboard" Key="Key_LeftAlt" />'
                   '<Modifier Device="Keyboard" Key="Key_RightAlt" /></Secondary>')
            keys, what = ed_honk.primary_fire_binding([journals])
            self.assertEqual(keys, ["KEY_LEFTALT", "KEY_RIGHTALT", "KEY_K"])
            self.assertIn("Left Alt + Right Alt + K", what)
            preset('<Secondary Device="{NoDevice}" Key="" />')
            keys, what = ed_honk.primary_fire_binding([journals])
            self.assertIsNone(keys)
            self.assertIn("no keyboard binding", what)
        self.assertEqual(ed_honk.parse_combo("alt+k"), ["KEY_LEFTALT", "KEY_K"])


class Speech(unittest.TestCase):
    """Spoken alerts: the lines file, and the game / arrival triggers."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def test_game_moments(self):
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:00Z", "Commander": "Briadin",
                       "ShipName": "Out There", "Ship": "krait_light", "GameMode": "Solo", "Credits": 5})
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T02:00:00Z"})
        kinds = [(m["kind"], m.get("cmdr"), m.get("ship")) for m in self.state.moments_summary()]
        self.assertEqual(kinds, [("game_start", "Briadin", "Out There"), ("game_exit", None, None)])
        self.assertTrue(any(b'"event":"Shutdown"' == w for w in ed_outrider.WANTED))

    def test_arrival_on_a_route(self):
        # targeted and announced as new, then the route re-targets the next hop before the arrival star scan:
        # the arrival must not play the fanfare again
        self.state.target_verdicts = {5: "unreported", 6: "partial"}
        self.state.last_target = {"id64": 99, "name": "next hop", "status": "partial"}
        self.jump("2026-01-01T00:05:00Z", 5, 10)
        self.j.handle(scan("2026-01-01T00:05:05Z", "S5", 5, 0, "S5", disc=False, star=True)[2])
        self.state.reconcile_arrival()
        a = self.state.arrival
        self.assertEqual((a["undiscovered"], a["wrong"], a["sound"]), (True, False, None))
        # announced as known but nobody had been there: the surprise gets its fanfare on arrival
        self.jump("2026-01-01T00:06:00Z", 6, 20)
        self.j.handle(scan("2026-01-01T00:06:05Z", "S6", 6, 0, "S6", disc=False, star=True)[2])
        self.state.reconcile_arrival()
        a = self.state.arrival
        self.assertEqual((a["undiscovered"], a["wrong"], a["sound"]), (True, True, "fanfare"))

    def test_fsd_charge_moment(self):
        # hyperspace jumps only (supercruise also writes StartJump), with the destination's star class
        self.j.handle({"event": "StartJump", "timestamp": "2026-01-01T00:00:00Z", "JumpType": "Supercruise"})
        self.j.handle({"event": "StartJump", "timestamp": "2026-01-01T00:00:10Z", "JumpType": "Hyperspace",
                       "StarSystem": "Drojau LL-O b26-3", "SystemAddress": 7, "StarClass": "K"})
        got = [(m["kind"], m.get("system"), m.get("star_class")) for m in self.state.moments_summary()]
        self.assertEqual(got, [("fsd_charge", "Drojau LL-O b26-3", "K")])

    def test_signals_moment(self):
        self.jump("2026-01-01T00:00:00Z", 9, 0)
        sig = lambda body, bio, geo: {"event": "FSSBodySignals", "timestamp": "2026-01-01T00:01:00Z", "BodyName": body,
                                      "BodyID": 3, "SystemAddress": 9, "Signals": [
                                          {"Type": ed_outrider.BIO, "Count": bio}, {"Type": ed_outrider.GEO, "Count": geo}]}
        self.j.handle(sig("S9 A 3", 2, 1))
        self.j.handle(sig("S9 B 1", 0, 0))   # nothing found: nothing to say
        got = [(m["kind"], m["body"], m["bio"], m["geo"]) for m in self.state.moments_summary() if m["kind"] == "signals"]
        self.assertEqual(got, [("signals", "A 3", 2, 1)])

    def test_autohonk(self):
        import asyncio, datetime as _dt
        now = lambda s=0: (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")
        j = self.j

        class FakeHonker:
            ready, available, status, presses = True, True, "ready", []

            def __init__(self, game_answers):
                self.game_answers = game_answers

            def press(self):
                self.presses.append(j.jump_arrival["id64"])
                if self.game_answers:   # the game writes FSSDiscoveryScan (set directly: sqlite is per thread)
                    j.last_honk = {"id64": j.jump_arrival["id64"], "ts": now(), "bodies": 12,
                                   "progress": 1.0 if self.game_answers == "all" else 0.2}
                return True

        def arrive(id64, age=0, answers=True):
            FakeHonker.presses = []
            self.state.honker = FakeHonker(answers)
            self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0)
            self.state.honk_confirm = 0.3
            self.j.handle({"event": "FSDJump", "timestamp": now(age), "StarSystem": f"S{id64}", "SystemAddress": id64,
                           "StarPos": [id64, 0, 0]})

            async def go():
                self.state.maybe_honk()
                await asyncio.sleep(0.5)
            asyncio.run(go())
            honks = [m for m in self.state.moments_summary() if m["kind"] == "honk" and m["system"] == f"S{id64}"]
            self.last_honks = honks
            return FakeHonker.presses, [(m["ok"], bool(m["why"])) for m in honks]

        self.assertEqual(arrive(21), ([21], [(True, False)]))            # live arrival: pressed, confirmed
        self.assertEqual((self.last_honks[0]["bodies"], self.last_honks[0]["all_found"]), (12, False))
        self.assertEqual(arrive(25, answers="all"), ([25], [(True, False)]))   # the honk found everything
        self.assertTrue(self.last_honks[0]["all_found"])
        self.assertEqual(arrive(22, age=120), ([], []))                  # an old journal line: never pressed
        self.assertEqual(arrive(23, answers=False), ([23], [(False, True)]))   # no scan followed: says so
        self.j.handle({"event": "FSSDiscoveryScan", "timestamp": now(), "SystemName": "S24", "SystemAddress": 24,
                       "BodyCount": 3, "Progress": 1.0})
        self.assertEqual(arrive(24), ([], []))                           # honked here before: left alone

    def test_honk_decision(self):
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        live = lambda **kw: dict({"live": True, "ts": ts, "flags": 1 << 4 | 1 << 27, "gui_focus": 0}, **kw)
        t = now.timestamp()
        d = ed_outrider.honk_decision
        self.assertEqual(d(live(), t), ("press", None))
        self.assertEqual(d(live(gui_focus=6), t), ("wait", "the galaxy map is open"))
        self.assertEqual(d(live(gui_focus=9), t), ("wait", "the FSS is open"))
        self.assertEqual(d(live(flags=1 << 30), t), ("wait", "still in the jump"))
        self.assertEqual(d(live(gui_focus=6), t + 120), ("press", None))   # stale reading: behave as before
        self.assertEqual(d(dict(live(gui_focus=6), live=False), t), ("press", None))
        self.assertEqual(d(None, t), ("press", None))

    def test_autohonk_waits_for_cockpit(self):
        import asyncio, datetime as _dt
        now = lambda: _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        presses = []

        class FakeHonker:
            ready, available, status = True, True, "ready"

            def press(self):
                presses.append(time.time())
                return True
        self.state.honker = FakeHonker()
        self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0)
        self.state.honk_confirm = 0.2
        self.j.status_json = {"live": True, "ts": now(), "flags": 1 << 4 | 1 << 27, "gui_focus": 6}   # galaxy map open
        self.j.handle({"event": "FSDJump", "timestamp": now(), "StarSystem": "S31", "SystemAddress": 31, "StarPos": [1, 0, 0]})

        async def go():
            self.state.maybe_honk()
            await asyncio.sleep(0.6)
            waiting = (list(presses), self.state.honker.status)
            self.j.status_json = dict(self.j.status_json, gui_focus=0)   # map closed
            await asyncio.sleep(0.8)
            return waiting
        waiting = asyncio.run(go())
        self.assertEqual(waiting, ([], "waiting: the galaxy map is open"))
        self.assertEqual(len(presses), 1)

    def test_arrival_without_target(self):
        self.jump("2026-01-01T00:01:00Z", 2, 30)
        self.j.handle(scan("2026-01-01T00:01:05Z", "S2", 2, 0, "S2", disc=False, star=True)[2])
        self.state.reconcile_arrival()
        a = self.state.arrival
        self.assertEqual((a["name"], a["undiscovered"], a["first_visit"], a["wrong"], a["sound"]),
                         ("S2", True, True, False, None))   # never announced: voice only, no fanfare
        # back again before selling: still undiscovered in the journal, but no longer news
        self.jump("2026-01-01T00:02:00Z", 3, 60)
        self.jump("2026-01-01T00:03:00Z", 2, 30)
        self.j.handle(scan("2026-01-01T00:03:05Z", "S2", 2, 0, "S2", disc=False, star=True)[2])
        self.state.reconcile_arrival()
        a = self.state.arrival
        self.assertEqual((a["undiscovered"], a["first_visit"], a["sound"]), (True, False, None))

    def test_lines_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "speech.json")
            sl = ed_speech.SpeechLines(path)
            self.assertIsNone(sl.info()["version"])
            doc = {"styles": {"business": "Business"}, "lines": {"hull": {"business": ["Hull {pct} percent."]}}}
            with open(path, "w") as f:
                json.dump(doc, f)
            self.assertTrue(sl.info()["version"])
            self.assertEqual(sl.lines()["lines"]["hull"]["business"], ["Hull {pct} percent."])
            with open(path, "w") as f:
                f.write("{ broken")
            os.utime(path, ns=(1, 1))   # a new modification time, whatever the clock's resolution
            info = sl.info()
            self.assertIn("last good copy", info["error"])
            self.assertEqual(sl.lines()["lines"]["hull"]["business"], ["Hull {pct} percent."])
        bad = {"styles": {"business": 1}, "lines": {"hull": {"business": ["{body} is hot"], "pirate": ["arr"]}, "nope": {}}}
        probs = " ".join(ed_speech.check(bad))
        self.assertIn("{body}", probs)
        self.assertIn('"pirate"', probs)
        self.assertIn('"nope"', probs)

    def test_fill_and_spoken_text(self):
        import random
        rng = random.Random(3)
        got = {ed_speech.fill("{name}", {}, "Boss, Hefay, Sir", rng) for _ in range(60)}
        self.assertEqual(got, {"Boss", "Hefay", "Sir"})   # each {name} is its own random pick
        self.assertEqual(ed_speech.fill("{name}, hull {pct}. {missing}", {"pct": 40}, " , "), "Commander, hull 40. ")
        self.assertEqual(ed_speech.spoken_text("⚠ Sold 12.6M cr · 3k left <b>now</b>"),
                         "Sold 12.6 million credits, 3 thousand left now")
        self.assertEqual(ed_speech.spoken_text("52.0M unsold, 12.64B banked, 1.96M left, 0.04M, 7.25 ly, 1.4M to map"),
                         "52 million unsold, 12.6 billion banked, 2 million left, 0 million, 7.2 ly, 1.4 million to map")
        for key in ed_speech.KEYS:   # the voice lab's sample values fill every placeholder an alert has
            self.assertLessEqual(ed_speech.fills(key) - set(ed_speech.ALWAYS), set(ed_speech.SAMPLES.get(key, {})), key)

    def test_shipped_lines(self):
        # speech.json covers every alert in every personality, and the page asks for exactly those alerts
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "speech.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(ed_speech.check(doc), [])
        for key in ed_speech.KEYS:
            for style in list(doc["styles"]) + [s + "_profane" for s in ("sarcastic", "sweet")]:
                self.assertGreaterEqual(len(doc["lines"][key].get(style, [])), 10, f"{key}/{style}")
        # the voice calls you by your chosen names ({name}): commander names are often unpronounceable
        said = [x for e in doc["lines"].values() for k, v in e.items() if k != "when" for x in v]
        self.assertEqual([x for x in said if "{cmdr}" in x], [])
        with open(os.path.join(here, "static", "page.js"), encoding="utf-8") as f:
            js = f.read()
        import re
        used = set(re.findall(r'line\("(\w+)"', js)) | set(re.findall(r'"(unsold_\w+)"', js))
        # every key is spoken by the page (RESERVED would list any with lines written ahead of their trigger)
        self.assertEqual(used, set(ed_speech.KEYS) - set(ed_speech.RESERVED))
        self.assertLessEqual(set(ed_speech.RESERVED), set(ed_speech.KEYS))
        samples = js[js.index("const LINE_SAMPLES = {"):]
        samples = samples[:samples.index("\n};")]
        for key in ed_speech.KEYS:   # the ▶ try button has sample values for every alert
            self.assertRegex(samples, r"\b%s: \{" % key, key)


class Batch5(unittest.TestCase):
    """Batch 5: route strip, next stop, left behind, jumponium sources."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.jump("2026-01-01T00:00:00Z", 1, 0)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def test_route_summary(self):
        hops = [{"id64": i, "name": f"S{i}", "star_class": c, "x": i * 10.0, "y": 0, "z": 0}
                for i, c in ((1, "K"), (2, "N"), (3, "D"), (4, "Y"), (5, "M"))]
        ed_outrider.meta_set(self.db, "route", {"ts": "2026-01-01T00:00:30Z", "hops": hops})
        r = self.state.route_summary()
        self.assertEqual([h["name"] for h in r["hops"]], ["S2", "S3", "S4", "S5"])   # from where you are
        self.assertEqual((r["next_scoop"], r["longest_dry"]), (4, 3))
        self.j.handle({"event": "NavRouteClear", "timestamp": "2026-01-01T00:01:00Z"})
        self.assertIsNone(self.state.route_summary())

    def test_next_stop_clears_on_arrival(self):
        self.jump("2026-01-01T00:01:00Z", 2, 30)
        self.jump("2026-01-01T00:02:00Z", 1, 0)
        self.assertTrue(self.state.set_next_stop(2))
        self.assertEqual(self.state.next_stop_summary()["distance"], 30.0)
        self.jump("2026-01-01T00:03:00Z", 2, 30)
        self.assertIsNone(self.state.next_stop_summary())

    def test_left_behind_and_sources(self):
        self.jump("2026-01-01T00:01:00Z", 2, 30)
        ev = scan("2026-01-01T00:02:00Z", "S2", 2, 4, "S2 4")[2]
        ev.update(PlanetClass="High metal content body", MassEM=1.0, TerraformState="Terraformable", Landable=True,
                  Materials=[{"Name": "polonium", "Percent": 0.8}, {"Name": "iron", "Percent": 20}])
        self.j.handle(ev)
        self.j.handle({"event": "SAASignalsFound", "timestamp": "2026-01-01T00:03:00Z", "SystemAddress": 2, "BodyID": 4,
                       "BodyName": "S2 4", "Signals": [], "Genuses": [{"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"}]})
        self.jump("2026-01-01T00:04:00Z", 1, 0)
        self.db.commit()
        left = self.state.left_behind(100)["systems"]
        self.assertEqual(left[0]["name"], "S2")
        self.assertEqual(left[0]["bio"][0]["genera"], ["Stratum"])
        self.assertGreater(left[0]["maps"][0]["increment"], 500000)      # a terraformable HMC's map
        src = self.state.material_sources()
        self.assertEqual((src["polonium"][0]["body"], src["polonium"][0]["pct"]), ("4", 0.8))
        self.assertEqual(src["arsenic"], [])


class SampleSpacing(unittest.TestCase):
    """Batch 6: positions are recorded live and the distance to go counts down as you walk."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def at(self, ts, lat, lon):
        self.j.status_json = {"live": True, "ts": ts, "fuel_main": 10, "flags": 0, "flags2": 1, "body": "Sys 4",
                              "lat": lat, "lon": lon, "planet_radius": 1_000_000}

    def organic(self, ts, kind):
        self.j.handle({"event": "ScanOrganic", "timestamp": ts, "SystemAddress": 1, "Body": 4, "ScanType": kind,
                       "Genus": "$Codex_Ent_Tussocks_Genus_Name;", "Genus_Localised": "Tussock",
                       "Species": "$Codex_Ent_Tussocks_01_Name;", "Species_Localised": "Tussock Pennata"})

    def test_countdown(self):
        self.at("2026-01-01T00:10:00Z", 0.0, 0.0)
        self.organic("2026-01-01T00:10:00Z", "Log")
        s = self.state.sampling_summary()
        self.assertEqual((s["need"], s["to_go"], s["clear"]), (200, 200, False))
        # 0.009 degrees on a 1,000 km body is about 157 m: 43 m still to go
        self.at("2026-01-01T00:11:00Z", 0.0, 0.009)
        s = self.state.sampling_summary()
        self.assertEqual((s["nearest"], s["to_go"], s["clear"]), (157, 43, False))
        self.at("2026-01-01T00:12:00Z", 0.0, 0.012)
        self.assertTrue(self.state.sampling_summary()["clear"])
        self.organic("2026-01-01T00:12:00Z", "Sample")                   # the second sample: now measured from both
        self.at("2026-01-01T00:13:00Z", 0.0, 0.006)                      # back between them
        self.assertFalse(self.state.sampling_summary()["clear"])
        self.organic("2026-01-01T00:20:00Z", "Analyse")
        self.assertIsNone(self.state.sampling_summary())                  # run complete

    def test_no_position_from_an_old_line(self):
        self.at("2026-01-02T00:00:00Z", 0.0, 0.0)                         # today's reading...
        self.organic("2026-01-01T00:10:00Z", "Log")                      # ...does not belong to yesterday's sample
        s = self.state.sampling_summary()
        self.assertEqual((s["points"], s["to_go"]), (0, None))


class Batch0Security(unittest.TestCase):
    """Batch 0: Host / Origin checks, the backup gap, voice names, and auto honk's switch-off and test races."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.addCleanup(self.db.close)

    def guard(self, method, host, origin=None, site=None, allowed=None, path="/api/autohonk/test"):
        """Status the request guard gives a request (200: it reached the handler)."""
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request
        headers = {"Host": host}
        if origin:
            headers["Origin"] = origin
        if site:
            headers["Sec-Fetch-Site"] = site
        allowed = ed_outrider.allowed_hosts("127.0.0.1", 8025) if allowed is None else allowed

        async def handler(_):
            return web.Response(text="ok")

        async def go():
            return (await ed_outrider.request_guard(allowed)(make_mocked_request(method, path, headers=headers),
                                                             handler)).status
        return asyncio.run(go())

    def test_allowed_hosts(self):
        a = ed_outrider.allowed_hosts("127.0.0.1", 8025, own=lambda: {"should-not-appear"})
        self.assertEqual(a, {"127.0.0.1:8025", "localhost:8025", "[::1]:8025"})
        a = ed_outrider.allowed_hosts("0.0.0.0", 8025, ["phone.lan", "10.0.0.2:9000", "fe80::1", "[::2]:8025"],
                                      own=lambda: {"MyPC", "192.168.1.5"})
        self.assertTrue({"mypc:8025", "192.168.1.5:8025", "phone.lan:8025", "10.0.0.2:9000", "[fe80::1]:8025",
                         "[::2]:8025", "localhost:8025"} <= a, a)
        self.assertIn("192.168.1.5:8025", ed_outrider.allowed_hosts("192.168.1.5", 8025))
        self.assertIn("localhost", ed_outrider.allowed_hosts("127.0.0.1", 80))   # the default port is left out of Host
        # the config key: a list (or one string) of names, carried through --write-config
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({"server": {"allowed_hosts": ["phone.lan", " "]}}, args, None, ([], []))
        self.assertEqual(st["allowed_hosts"], ["phone.lan"])
        self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["server"]["allowed_hosts"], ["phone.lan"])
        self.assertEqual(ed_outrider.settings_from({"server": {"allowed_hosts": "pc"}}, args, None, ([], []))["allowed_hosts"], ["pc"])

    def test_origin_check(self):
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", origin="http://evil.example"), 403)   # another site
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", origin="null"), 403)                 # a sandboxed frame
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", origin="http://localhost:8025"), 403)  # not this origin
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", origin="http://127.0.0.1:8025"), 200)  # the page itself
        self.assertEqual(self.guard("POST", "localhost:8025", origin="http://localhost:8025"), 200)
        self.assertEqual(self.guard("POST", "127.0.0.1:8025"), 200)                                  # curl: no Origin
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", site="cross-site"), 403)
        self.assertEqual(self.guard("POST", "127.0.0.1:8025", origin="http://127.0.0.1:8025", site="same-origin"), 200)
        self.assertEqual(self.guard("GET", "127.0.0.1:8025", origin="http://evil.example"), 200)     # reads: the Host check

    def test_host_check(self):
        self.assertEqual(self.guard("GET", "attacker.example:8025"), 403)   # DNS rebinding
        self.assertEqual(self.guard("GET", "mypc.lan:8025"), 403)          # an unknown name
        self.assertEqual(self.guard("GET", ""), 403)
        # F39: any IP address (DNS rebinding needs a name): a LAN address own_addresses() missed behind a VPN
        for ip in ("192.168.1.208:8025", "10.10.10.208:8025", "[fe80::1]:8025", "0.0.0.0:8025", "127.0.0.1:9999"):
            self.assertEqual(self.guard("GET", ip), 200, ip)
        self.assertFalse(ed_outrider.ip_literal_host("192.168.1.208.evil.example:8025"))
        self.assertEqual(self.guard("POST", "attacker.example:8025", origin="http://attacker.example:8025"), 403)
        for good in ("127.0.0.1:8025", "localhost:8025", "LOCALHOST:8025", "[::1]:8025"):
            self.assertEqual(self.guard("GET", good), 200, good)
        # make_app without host names answers any Host (tests), but still refuses other sites' POSTs
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                r1 = await c.post("/api/backup", headers={"Origin": "http://evil.example"})
                r2 = await c.post("/api/backup")   # passes the guard: no database path in tests
                self.state.db_path, self.state.backup_done_at = "x.sqlite", time.monotonic()
                r3 = await c.post("/api/backup")   # G1.4: not again within a minute
                r4 = await c.get("/api/speech", headers={"Host": "attacker.example"})
            async with TestClient(TestServer(ed_outrider.make_app(self.state, {"good:1"}))) as c:
                r5 = await c.get("/api/speech", headers={"Host": "bad:1"})   # (the client's own 127.0.0.1 is an IP: answered)
                r6 = await c.get("/api/speech", headers={"Host": "good:1"})
            return [r.status for r in (r1, r2, r3, r4, r5, r6)]
        self.assertEqual(asyncio.run(go()), [403, 500, 429, 200, 403, 200])

    def test_voice_names(self):
        import tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            for ext in (".onnx", ".onnx.json"):   # installed = both files
                open(os.path.join(d, "my-odd.voice" + ext), "w").close()
            sp = ed_tts.Speaker(voices_dir=d)
            ok = ("en_GB-southern_english_female-low", "zh_CN-huayan-x_low", "en_US-l2arctic-medium", "my-odd.voice")
            bad = ("../x_y-z-low", "/home/u/x_Y-z-low", "en_GB-a/b-low", "en_GB-x-huge", "", "en_GB-x-low\n")
            self.assertEqual([sp.valid_name(v) for v in ok], [True] * len(ok))
            self.assertEqual([sp.valid_name(v) for v in bad], [False] * len(bad))
            started = []
            sp.PiperVoice = object   # "installed", without starting any real work
            with unittest.mock.patch.object(ed_tts.threading, "Thread", lambda **kw: started.append(kw) or unittest.mock.Mock()):
                self.assertFalse(sp.use("../../etc/x_y-z-low"))
                self.assertTrue(sp.use("en_US-lessac-medium"))
                self.assertTrue(sp.use("en_US-amy-medium"))   # while the first switch runs: queued, no second thread
            self.assertEqual((len(started), sp._switch_to), (1, "en_US-amy-medium"))

    def test_honk_off_during_delay(self):
        # F58: switching auto honk off while it waits out the delay drops the honk without a 'failed' moment
        import asyncio, datetime as _dt
        presses = []

        class FakeHonker:
            available, status = True, "ready"
            ready = True

            def press(self):
                presses.append(1)
                return "K"

            def close(self):
                self.ready = False
        self.state.honker = FakeHonker()
        self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0.3)
        now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.j.handle({"event": "FSDJump", "timestamp": now, "StarSystem": "S41", "SystemAddress": 41, "StarPos": [1, 0, 0]})

        async def go():
            self.state.maybe_honk()
            await asyncio.sleep(0.1)
            self.state.set_autohonk(False)
            await asyncio.sleep(0.5)
        asyncio.run(go())
        self.assertEqual(presses, [])
        self.assertEqual([m for m in self.state.moments_summary() if m["kind"] == "honk"], [])

    def test_honk_test_runs(self):
        # F60: one test at a time; F77: a failed press reaches the dialog; the device closes after (auto honk off)
        import asyncio
        log = []

        class FakeHonker:
            available, status, fail = True, "off", None

            def __init__(self):
                self.ready = False

            def combo(self):
                return ["KEY_K"], "K"

            def open(self):
                self.ready = True
                return True

            def close(self):
                self.ready = False
                log.append("close")

            def press(self):
                time.sleep(0.1)
                log.append("press")
                if self.fail:
                    raise ValueError(self.fail)
                return "K"
        self.state.honker = FakeHonker()
        self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=False)
        self.state.honk_test_countdown = 0.05

        async def go():
            first = self.state.start_honk_test()
            second = self.state.start_honk_test()
            self.state.set_autohonk(False)   # unticking during a test leaves the device to the test
            closed_early = list(log)
            await self.state.honk_test_task
            return first, second, closed_early
        first, second, closed_early = asyncio.run(go())
        self.assertEqual((first[1], first[0]["in"], second[1]), (200, 0.05, 409))
        self.assertEqual(closed_early, [])
        self.assertEqual(log, ["press", "close"])
        self.assertEqual(self.state.autohonk_info()["test"]["state"], "done")
        self.state.honker.fail = "no keyboard binding for Primary Fire"
        asyncio.run(self._run_test())
        t = self.state.autohonk_info()["test"]
        self.assertEqual((t["seq"], t["state"], t["error"]), (2, "failed", "no keyboard binding for Primary Fire"))

    async def _run_test(self):
        self.assertEqual(self.state.start_honk_test()[1], 200)
        await self.state.honk_test_task

    def test_honker_close_during_press(self):
        # F86: close() while press() holds the key: the hold ends early, keys are let go, then the device closes
        import threading
        import types
        import ed_honk
        writes = []

        class FakeUI:
            closed = False

            def write(self, _type, code, value):
                if self.closed:
                    raise AttributeError("closed")
                writes.append((code, value))

            def syn(self):
                pass

            def close(self):
                self.closed = True
        h = ed_honk.Honker("KEY_K", hold=5)
        h.evdev = types.SimpleNamespace(ecodes=types.SimpleNamespace(EV_KEY=1, ecodes={"KEY_K": 37}))
        h.ui = ui = FakeUI()
        out = []
        t = threading.Thread(target=lambda: out.append(h.press()))
        start = time.time()
        t.start()
        time.sleep(0.2)
        h.close()   # returns at once: the event loop must not wait out the hold
        self.assertLess(time.time() - start, 1)
        self.assertFalse(h.ready)
        t.join(2)
        self.assertLess(time.time() - start, 1.5)
        self.assertEqual((out, writes, ui.closed, h.ui), ([None], [(37, 1), (37, 0)], True, None))
        with self.assertRaises(ValueError):   # closed: a later press says so instead of an AttributeError
            h.press()
        # close with no press running closes at once
        h.ui = ui2 = FakeUI()
        h.close()
        self.assertTrue(ui2.closed and h.ui is None)


class Batch1Alerts(unittest.TestCase):
    """Second review, batch 1: alerts that repeated or said something false."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def kinds(self, kind):
        return [m for m in self.j.moments if m["kind"] == kind]

    def test_mapping_or_rescanning_a_body_announces_it_once(self):   # F1
        self.j.handle(scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4")[2])
        self.j.handle({"event": "SAAScanComplete", "timestamp": "2026-01-01T00:08:00Z", "SystemAddress": 1,
                       "BodyName": "Sys 4", "BodyID": 4, "ProbesUsed": 5, "EfficiencyTarget": 6})
        self.j.handle(scan("2026-01-01T00:08:01Z", "Sys", 1, 4, "Sys 4")[2])      # the Detailed rescan after mapping
        self.j.handle(scan("2026-03-01T00:00:00Z", "Sys", 1, 4, "Sys 4")[2])      # an AutoScan on a return visit
        self.assertEqual([m["body_id"] for m in self.kinds("scan")], [4])
        self.j.handle(scan("2026-03-01T00:00:05Z", "Sys", 1, 5, "Sys 5")[2])      # a new body still is news
        self.assertEqual([m["body_id"] for m in self.kinds("scan")], [4, 5])

    def test_heat_damage_is_one_alert_per_30_s(self):   # F15
        for t in ("00:10:00", "00:10:03", "00:10:20", "00:10:31", "00:10:40"):
            self.j.handle({"event": "HeatDamage", "timestamp": f"2026-01-01T{t}Z"})
        self.assertEqual([m["ts"] for m in self.kinds("heat")], ["2026-01-01T00:10:00Z", "2026-01-01T00:10:31Z"])

    def test_failed_tick_does_not_repeat_moments_or_codex(self):   # F12
        import contextlib, io, tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "Journal.2026-01-02T000000.01.log"), "w") as f:
            for e in ({"timestamp": "2026-01-02T00:00:00Z", "event": "StartJump", "JumpType": "Hyperspace",
                       "StarSystem": "Next", "SystemAddress": 2, "StarClass": "K"},
                      {"timestamp": "2026-01-02T00:00:10Z", "event": "CodexEntry", "EntryID": 1, "Name": "x",
                       "SystemAddress": 1, "System": "Sys", "IsNewEntry": True},
                      {"timestamp": "2026-01-02T00:00:20Z", "event": "HeatDamage"},
                      {"timestamp": "2026-01-02T00:00:30Z", "event": "FSDJump", "StarSystem": "Next", "SystemAddress": 2,
                       "StarPos": [10, 0, 0]}):
                f.write(json.dumps(e, separators=(",", ":")) + "\n")   # the game writes "event":"X"
        calls = {"n": 0}
        orig = self.j.handle
        def flaky(ev):
            if ev.get("event") == "FSDJump" and not calls["n"]:
                calls["n"] += 1
                raise sqlite3.OperationalError("database is locked")
            return orig(ev)
        self.j.handle = flaky
        codex_rows = lambda: self.j.db.execute("SELECT count(*) FROM codex").fetchone()[0]
        seq0, codex0 = self.j.moment_seq, codex_rows()
        later = ("maybe_refresh", "apply_own_changes", "maybe_classify_target", "maybe_unsold", "maybe_locate_carrier",
                 "maybe_find_sellers")
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [d]))
            for name in later:
                stack.enter_context(unittest.mock.patch.object(self.state, name, lambda: None))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            self.state.tick({})
            self.assertTrue(self.state.tail_error)
            self.assertEqual((self.j.moment_seq, codex_rows()), (seq0, codex0))   # the failed tick left nothing
            self.state.tick({})
        self.assertIsNone(self.state.tail_error)
        self.assertEqual([m["kind"] for m in self.j.moments if m["seq"] > seq0], ["fsd_charge", "heat"])
        self.assertEqual(codex_rows(), codex0 + 1)
        self.assertEqual(self.j.pos["id64"], 2)

    def carrier_event(self, name, ts, **kw):
        base = {"CarrierLocation": {"CarrierType": "FleetCarrier", "CarrierID": 99},
                "CarrierJumpRequest": {"CarrierType": "FleetCarrier", "CarrierID": 99},
                "Docked": {"StationType": "FleetCarrier", "MarketID": 99, "StationName": "XYZ-123",
                           "StationServices": ["exploration"]}}.get(name, {})
        self.j.handle(dict(base, event=name, timestamp=ts, **kw))
        return self.j.carrier

    def test_carrier_arrival_and_booked_jump(self):   # F5, F45, F26
        self.carrier_event("CarrierStats", "2026-01-01T00:00:00Z", CarrierType="FleetCarrier", CarrierID=99,
                           Name="OUT OF THE BLUE", Callsign="XYZ-123")
        c = self.carrier_event("CarrierLocation", "2026-01-01T00:00:01Z", StarSystem="A", SystemAddress=10)
        first = c["moved_ts"]
        # a relog and a dock at the carrier where it already is: not an arrival
        self.carrier_event("CarrierLocation", "2026-01-02T00:00:00Z", StarSystem="A", SystemAddress=10)
        self.assertEqual(self.j.carrier["moved_ts"], first)
        self.carrier_event("CarrierJumpRequest", "2026-01-02T01:00:00Z", SystemName="B", SystemAddress=20,
                           DepartureTime="2026-01-02T01:15:00Z")
        self.carrier_event("Docked", "2026-01-02T01:05:00Z", StarSystem="A", SystemAddress=10)
        self.carrier_event("Undocked", "2026-01-02T01:06:00Z", StationName="XYZ-123")
        self.carrier_event("CarrierLocation", "2026-01-02T01:07:00Z", StarSystem="A", SystemAddress=10)   # relog
        c = self.j.carrier
        self.assertEqual((c["moved_ts"], c["planned"]["system"]), (first, "B"))   # the booking survives both
        self.assertEqual(self.state.carrier_summary()["moved_ts"], first)
        # the game writes CarrierLocation at the departure time; riding along adds a CarrierJump a minute later
        c = self.carrier_event("CarrierLocation", "2026-01-02T01:15:00Z", StarSystem="B", SystemAddress=20)
        self.assertEqual((c["system"], c["moved_ts"], c["planned"]), ("B", "2026-01-02T01:15:00Z", None))
        self.j.handle({"event": "CarrierJump", "timestamp": "2026-01-02T01:16:00Z", "StarSystem": "B", "SystemAddress": 20,
                       "StarPos": [5, 0, 0], "MarketID": 99, "Docked": True, "StationType": "FleetCarrier"})
        self.assertEqual((self.j.carrier["moved_ts"], self.j.carrier["x"]), ("2026-01-02T01:15:00Z", 5))
        # a booking made before quitting: nothing in the journal says it left, so after departure + 5 min it
        # is assumed at the destination, and the confirming CarrierLocation at the next login is no second arrival
        self.carrier_event("CarrierJumpRequest", "2026-01-03T00:00:00Z", SystemName="C", SystemAddress=30,
                           DepartureTime="2026-01-03T00:15:00Z")
        dep = ed_outrider.ts_seconds("2026-01-03T00:15:00Z")
        self.assertFalse(self.j.settle_carrier(dep + 60))
        self.assertTrue(self.j.settle_carrier(dep + 400))
        c = self.j.carrier
        self.assertEqual((c["system"], c["id64"], c["planned"], c["assumed"], c["moved_ts"]),
                         ("C", 30, None, True, "2026-01-03T00:15:00Z"))
        self.assertTrue(self.state.carrier_summary()["assumed"])
        self.assertFalse(self.j.settle_carrier(dep + 500))
        c = self.carrier_event("CarrierLocation", "2026-01-04T00:00:00Z", StarSystem="C", SystemAddress=30)
        self.assertEqual((c["moved_ts"], c["assumed"]), ("2026-01-03T00:15:00Z", False))
        self.assertEqual(ed_outrider.meta_get(self.db, "carrier")["system"], "C")
        # a jump that did not happen (the carrier is still here well after departure) is forgotten
        self.carrier_event("CarrierJumpRequest", "2026-01-05T00:00:00Z", SystemName="D", SystemAddress=40,
                           DepartureTime="2026-01-05T00:15:00Z")
        c = self.carrier_event("CarrierLocation", "2026-01-05T01:00:00Z", StarSystem="C", SystemAddress=30)
        self.assertEqual((c["system"], c["planned"]), ("C", None))
        # cancelling still ends a booking
        self.carrier_event("CarrierJumpRequest", "2026-01-06T00:00:00Z", SystemName="D", SystemAddress=40,
                           DepartureTime="2026-01-06T00:15:00Z")
        self.carrier_event("CarrierJumpCancelled", "2026-01-06T00:01:00Z", CarrierID=99)
        self.assertIsNone(self.j.carrier["planned"])

    def test_on_foot_in_a_station_is_still_docked(self):   # F6
        self.j.handle({"event": "Docked", "timestamp": "2026-01-01T01:00:00Z", "StationName": "Port", "StationType": "Coriolis",
                       "MarketID": 5, "StarSystem": "Sys", "SystemAddress": 1, "StationServices": ["exploration", "vistagenomics"]})
        live = lambda flags, flags2: setattr(self.j, "status_json", {"live": True, "flags": flags, "flags2": flags2, "fuel_main": 8})
        live(1 | (1 << 24), 0)
        self.assertTrue(self.state.docked_summary()["docked_now"])
        for bit in (3, 13, 14):   # walking the concourse to Vista Genomics: Flags 0, Flags2 OnFoot + where
            live(0, 1 | (1 << bit))
            self.assertEqual(self.state.docked_summary()["station"], "Port", bit)
        live(0, 1 | (1 << 4))     # on foot on a planet is not docked
        self.assertIsNone(self.state.docked_summary())
        # ...but the page is still told which dock that was, so a baseline taken now does not re-announce it (F44)
        self.assertEqual(self.state.payload()["docked_ts"], "2026-01-01T01:00:00Z")
        # the undock alert comes from the journal's Undocked, with the dock's ts (was anything sold since?)
        self.j.handle({"event": "Undocked", "timestamp": "2026-01-01T01:30:00Z", "StationName": "Port"})
        m = self.kinds("undocked")[-1]
        self.assertEqual((m["station"], m["dock_ts"], m["has_uc"], m["has_vista"]), ("Port", "2026-01-01T01:00:00Z", True, True))
        self.assertIsNone(self.state.docked_summary())

    def test_fuel_says_whether_you_are_in_the_ship(self):   # F75
        self.j.status_json = {"live": True, "flags": (1 << 24) | (1 << 19), "fuel_main": 4}
        f = self.state.fuel_summary()
        self.assertEqual((f["in_ship"], f["low_flag"]), (True, True))
        self.j.status_json = {"live": True, "flags": 0, "flags2": 1, "fuel_main": 4}   # on foot: LowFuel reads clear
        self.assertFalse(self.state.fuel_summary()["in_ship"])

    def test_late_target_verdict_is_reconciled_in_place(self):   # F56
        self.j.arrival_scan = {"id64": 1, "was_discovered": True, "ts": "2026-01-01T00:00:05Z"}
        self.state.reconcile_arrival()
        a = dict(self.state.arrival)
        self.assertIsNone(a["announced"])
        self.state.target_verdicts[1] = "unreported"   # the slow Spansh/EDSM lookup lands after the arrival scan
        self.state.reconcile_arrival()
        b = self.state.arrival
        self.assertEqual((b["announced"], b["wrong"], b["seq"], b["sound"]), ("unreported", True, a["seq"], None))
        v = self.state.version
        self.state.reconcile_arrival()               # settled: nothing more to do
        self.assertEqual(self.state.version, v)


class Batch2Values(unittest.TestCase):
    """Second review, batch 2: values shown or spoken, and the exobiology guesses."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def body(self, name):
        self.db.commit()
        return next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == name)

    def test_rescan_after_sale_adds_only_the_map(self):   # F36
        mapped = lambda ts: (T(ts), None, {"event": "SAAScanComplete", "timestamp": ts, "SystemAddress": 1, "BodyID": 4,
                                           "BodyName": "Sys 4", "ProbesUsed": 5, "EfficiencyTarget": 6})
        ev = [scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4"), sale("2026-01-02T00:00:00Z", ["Sys"]),
              scan("2026-01-03T00:00:00Z", "Sys", 1, 4, "Sys 4")]           # an AutoScan on the way back
        self.assertEqual(ed_unsold.analyse(ev, ARGS)["exploration"]["rows"], [])
        rows = ed_unsold.analyse(ev + [mapped("2026-01-03T00:05:00Z")], ARGS)["exploration"]["rows"]
        body = {"PlanetClass": "High metal content body", "MassEM": 1.0, "TerraformState": "", "first_mapped": True}
        self.assertEqual([(r["map_only"], r["value"]) for r in rows],
                         [(True, ed_unsold.body_value(body, True, False, True) - ed_unsold.body_value(body, False, False, True))])
        # Here agrees: the rescanned body is sold data, not something on board
        for e in ev:
            self.j.handle(e[2])
        b = self.body("4")
        self.assertEqual((b["value_parts"]["scan_state"], b["value_now"]), ("sold", 0))
        self.assertEqual(b["value_max"], b["value_parts"]["carto_left"])        # only the map is still there to add

    def test_small_body_floor_matches_eddiscovery(self):   # F35: checked, left as the reference has it
        # EDDiscovery's EstimatedValues.cs floors the base value at 500 before the mapping multiplier
        icy = {"PlanetClass": "Icy body", "MassEM": 0.01, "TerraformState": "", "first_discovered": True, "first_mapped": True}
        self.assertEqual(ed_unsold.planet_base_value(300.0, 0.01), 500.0)
        self.assertEqual(ed_unsold.body_value(icy, True, False, True), int((500 * 3.699622554 + 555) * 2.6))

    def test_sold_bio_is_not_on_board(self):   # F3
        if not ed_outrider.ed_bio:
            self.skipTest("no rules")
        s = scan("2026-01-01T00:01:00Z", "Sys", 1, 5, "Sys 5")[2]; s["WasFootfalled"] = False
        self.j.handle(s)
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:01:00Z", "SystemAddress": 1, "BodyID": 5,
                       "BodyName": "Sys 5", "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 1}]})
        for i, k in enumerate(("Log", "Sample", "Analyse")):
            self.j.handle(org(f"2026-01-01T00:0{2 + i}:00Z", 1, 5, "Bacterial_01", k))
        value = ed_bio.species_value("Bacterium Aurasus")
        self.assertEqual(self.body("5")["value_parts"]["bio_now"], value * 5)
        recs = lambda: ed_outrider.merge_records([], *ed_outrider.own_data(self.db, 1, "Sys")[:2])
        self.assertEqual(self.state.system_value(1, "Sys", recs(), None)["value_parts"]["bio_now"], value * 5)
        self.j.handle({"event": "SellOrganicData", "timestamp": "2026-01-01T01:00:00Z", "BioData": [{"Value": value, "Bonus": 0}]})
        b = self.body("5")
        self.assertEqual(b["value_parts"]["bio_now"], 0)                            # banked at Vista Genomics
        self.assertEqual(self.state.system_value(1, "Sys", recs(), None)["value_parts"]["bio_now"], 0)

    CANDS = [{"name": "Stratum Tectonicas", "genus": "Stratum", "value": 19_010_800},
             {"name": "Concha Biconcavis", "genus": "Concha", "value": 16_777_215},
             {"name": "Fungoida Bullarum", "genus": "Fungoida", "value": 3_703_200},
             {"name": "Bacterium Aurasus", "genus": "Bacterium", "value": 1_000_000}]

    def test_nearby_uses_your_dss_genera(self):   # F2
        recs = [{"name": "4", "type": "Planet", "subtype": "Rocky body", "bio": 2, "full": True}]
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            self.assertEqual(ed_outrider.summarise(recs, 1)["bio_potential"], 19_010_800 + 16_777_215)
            s = ed_outrider.summarise(recs, 1, genera={"4": ["Bacterium", "Fungoida"]})
        self.assertEqual(s["bio_potential"], 4_703_200)

    def test_search_remainder_after_a_sampled_genus(self):   # F20
        self.db.execute("INSERT INTO own_organic (system, body_id, species, genus_name, species_name, samples, done_ts, ts) "
                        "VALUES (9, 2, 'x', 'Bacterium', 'Bacterium Aurasus', 3, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')")
        recs = [{"name": "2", "type": "Planet", "subtype": "Rocky body", "body_id": 2, "bio": 2}]
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            hits = ed_outrider.bio_hits(self.db, 9, "Sys", 0, 0, 0, recs, 0)
            self.assertEqual(hits[0]["t"], "2 · 1 of 2 unscanned · up to 19.0M")
            self.assertEqual(ed_outrider.bio_hits(self.db, 9, "Sys", 0, 0, 0, recs, 20_000_000), [])

    def test_sample_run_on_another_body_is_not_shown(self):   # F4
        for bid in (4, 5):
            self.j.handle(scan("2026-01-01T00:01:00Z", "Sys", 1, bid, f"Sys {bid}")[2])
        self.j.handle({"event": "ScanOrganic", "timestamp": "2026-01-01T00:10:00Z", "SystemAddress": 1, "Body": 4, "ScanType": "Log",
                       "Genus": "$Codex_Ent_Tussocks_Genus_Name;", "Genus_Localised": "Tussock",
                       "Species": "$Codex_Ent_Tussocks_01_Name;", "Species_Localised": "Tussock Pennata"})
        at = lambda body: setattr(self.j, "status_json", {"live": True, "ts": "2026-01-01T00:11:00Z", "fuel_main": 10, "flags": 0,
                                                          "flags2": 1, "body": body, "lat": 0.0, "lon": 0.0, "planet_radius": 1_000_000})
        at("Sys 5")   # no distance across two planets: only the in-progress-elsewhere line (P5)
        self.assertEqual(set(self.state.sampling_summary()), {"elsewhere"})
        at("Sys 4")
        self.assertEqual(self.state.sampling_summary()["genus"], "Tussock")

    def test_rules_see_unrounded_gravity_and_unknown_volcanism(self):   # F10, F9
        ev = scan("2026-01-01T00:01:00Z", "Sys", 1, 4, "Sys 4")[2]
        ev.update(SurfaceGravity=0.2756 * 9.80665, Volcanism="")
        r = ed_outrider.record_from_scan(ev)
        self.assertEqual(r["gravity"], 0.28)                                     # shown rounded
        self.assertAlmostEqual(ed_outrider._bio_body(r, None, None)["gravity"], 0.2756)   # judged unrounded (max 0.276)
        self.assertEqual(r["volcanism"], "")                                     # the journal says: none
        del ev["Volcanism"]
        self.assertIsNone(ed_outrider.record_from_scan(ev)["volcanism"])         # not said: unknown
        facts = lambda v: ed_bio._body_facts({"class": "Rocky body", "volcanism": v})
        self.assertIs(ed_bio._check("volcanism", "None", facts(None), {}), ed_bio.SKIP)
        self.assertIs(ed_bio._check("volcanism", ["silicate"], facts(None), {}), ed_bio.SKIP)
        self.assertTrue(ed_bio._check("volcanism", "None", facts(""), {}))
        self.assertFalse(ed_bio._check("volcanism", "Any", facts("No volcanism"), {}))

    def test_incomplete_system_rules_nothing_out(self):   # F37, F39
        recs = [{"type": "Star", "subtype": "M", "main": True, "body_id": 0},
                {"type": "Planet", "subtype": "Rocky body", "body_id": 3, "parents": [2]}]
        ctx = ed_outrider.bio_context("Sys", recs, body_count=4)
        self.assertEqual((ctx["planet_types"], ctx["complete"]), (None, False))   # a water giant may be unscanned
        self.assertIs(ed_bio._check("bodies", {"Water giant"}, {}, ed_bio._system_facts(ctx, {})), ed_bio.SKIP)
        done = ed_outrider.bio_context("Sys", recs, body_count=2)
        self.assertEqual((done["planet_types"], done["complete"]), (["Rocky body"], True))
        # the planet orbits star 2, not scanned yet: its parents are unknown, not "the arrival M star"
        self.assertIsNone(ed_outrider._bio_body(recs[1], None, ctx)["parents"])
        self.assertEqual(ed_outrider._bio_body(recs[1], None, dict(ctx, star_types={0: "M", 2: "B"}))["parents"], ["B"])
        stratum = {"star": {"F": "Emerald", "K": "Lime", "M": "Green"}}
        b = ed_bio._body_facts({"class": "Rocky body", "parents": None})
        self.assertTrue(ed_bio._colour_ok(stratum, b, ed_bio._system_facts(dict(ctx, stars=[{"type": "G", "main": True}]), {})))

    def test_obelisk_data_caps_at_150(self):   # G3.2
        self.assertEqual(ed_materials.MATERIALS["ancientculturaldata"][2], 4)
        st = ed_materials.new_state()
        ed_materials._add(st, "AncientCulturalData", 149)
        ed_materials._add(st, "AncientCulturalData", 3)
        self.assertEqual(st["counts"]["ancientculturaldata"], 150)


class RulesDownload(unittest.TestCase):
    """F38/F80: the spawn-rules download (every fetch mocked: bio_rules.json is never touched)."""

    V = {"bioscan": "b1", "regionmap": "r1", "explodata": "e1"}

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rules.json")
        self.log = []

    def tearDown(self):
        ed_bio.load_rules(ed_bio.RULES_FILE, force=True)   # back to the shipped copy for the other tests
        self.tmp.cleanup()

    def fake_get(self, fail=()):
        def get(url):
            if any(f in url for f in fail):
                raise OSError("timed out")
            for key, src in (("contents/", '[{"name": "stratum.py"}]'), ("rulesets", "catalog = {}"), ("species.py", "_mound_amphora = {}"),
                             ("regions.py", "region_map = {}"), ("reference_stars.py", "coordinates = {}"),
                             ("sectors.py", "data = []"), ("RegionMapData", "regions = []\nregionmap = []"),
                             ("genus.py", "data = {}")):
                if key in url:
                    return src
            raise AssertionError(f"unexpected fetch {url}")
        return get

    def test_a_failed_part_is_saved_without_a_version(self):   # F38
        with unittest.mock.patch.object(ed_bio, "_get", self.fake_get(fail=("contents/", "genus.py"))):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V))
        with open(self.path) as fh:
            saved = json.load(fh)["versions"]
        self.assertEqual(saved, {"bioscan": "", "regionmap": "r1", "explodata": ""})   # retried at the next start
        with unittest.mock.patch.object(ed_bio, "_get", self.fake_get()):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V))
        with open(self.path) as fh:
            self.assertEqual(json.load(fh)["versions"], self.V)
        # and the next start sees the gap and fetches again
        with unittest.mock.patch.object(ed_bio, "_get", self.fake_get(fail=("genus.py",))):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V))
        with unittest.mock.patch.object(ed_bio, "remote_versions", return_value=dict(self.V)), \
                unittest.mock.patch.object(ed_bio, "update_rules") as upd:
            self.assertTrue(ed_bio.update_if_newer(self.path, log=self.log.append))
            upd.assert_called_once()

    def test_failed_update_keeps_the_old_copy(self):   # F80
        with unittest.mock.patch.object(ed_bio, "_get", self.fake_get()):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V))
        with open(self.path) as fh:
            before = fh.read()
        newer = dict(self.V, bioscan="b2")
        with unittest.mock.patch.object(ed_bio, "remote_versions", return_value=newer), \
                unittest.mock.patch.object(ed_bio, "_get", self.fake_get(fail=("reference_stars.py",))):
            self.assertIsNone(ed_bio.update_if_newer(self.path, log=self.log.append))
        self.assertIn("update failed", self.log[-1])
        with open(self.path) as fh:
            self.assertEqual(fh.read(), before)
        with unittest.mock.patch.object(ed_bio, "remote_versions", return_value=dict(self.V)):
            self.assertIs(ed_bio.update_if_newer(self.path, log=self.log.append), False)   # current
        missing = os.path.join(self.tmp.name, "none.json")
        with unittest.mock.patch.object(ed_bio, "remote_versions", return_value=newer), \
                unittest.mock.patch.object(ed_bio, "_get", self.fake_get(fail=("reference_stars.py",))):
            with self.assertRaises(OSError):
                ed_bio.update_if_newer(missing, log=self.log.append)       # nothing to fall back on

    def test_failed_colour_fetch_keeps_the_colours_there(self):   # F66
        catalog = ('catalog = {"$Codex_Ent_Bacterial_Genus_Name;": {"$Codex_Ent_Bacterial_01_Name;": '
                   '{"name": "Bacterium Aurasus", "value": 1000000, "rulesets": []}}}')
        genus = ('data = {"$Codex_Ent_Bacterial_Genus_Name;": {"colors": {"species": '
                 '{"$Codex_Ent_Bacterial_01_Name;": {"star": {"F": "Teal"}}}}}}')

        def get_with(fail=()):
            base = self.fake_get(fail)

            def get(url):
                if any(f in url for f in fail):
                    raise OSError("timed out")
                if "rulesets/" in url:
                    return catalog
                return genus if "genus.py" in url else base(url)
            return get

        def colours():
            with open(self.path) as fh:
                return [sp["colors"] for sp in json.load(fh)["species"]]
        with unittest.mock.patch.object(ed_bio, "_get", get_with()):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V))
        self.assertEqual(colours(), [{"star": {"F": "Teal"}}])
        with unittest.mock.patch.object(ed_bio, "_get", get_with(fail=("genus.py",))):
            ed_bio.update_rules(self.path, log=self.log.append, versions=dict(self.V, bioscan="b2"))
        self.assertEqual(colours(), [{"star": {"F": "Teal"}}])      # the colour check stays on
        with open(self.path) as fh:
            self.assertEqual(json.load(fh)["versions"]["explodata"], "")   # and ExploData is fetched again next start


class Batch3Journal(unittest.TestCase):
    """Second review, batch 3: the journal reader (order, repairs, duplicate files)."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)

    def write(self, folder, name, events):
        d = os.path.join(self.tmp.name, folder)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "a") as f:
            for e in events:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        return d

    @staticmethod
    def jump(ts, id64, x=0.0):
        return {"timestamp": ts, "event": "FSDJump", "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0],
                "JumpDist": 10.0, "FuelUsed": 1.0}

    def test_legacy_read_after_live_changes_nothing_current(self):   # F11
        live = self.write("live", "Journal.2026-05-01T100000.01.log", [
            {"timestamp": "2026-05-01T10:00:00Z", "event": "CarrierStats", "CarrierID": 7, "Name": "C", "Callsign": "ABC-123",
             "FuelLevel": 800, "JumpRangeCurr": 500},
            {"timestamp": "2026-05-01T10:00:05Z", "event": "CarrierLocation", "CarrierID": 7, "StarSystem": "S100",
             "SystemAddress": 100},
            self.jump("2026-05-01T10:01:00Z", 100),
            {"timestamp": "2026-05-01T10:02:00Z", "event": "Docked", "StationName": "Stn", "StationType": "Coriolis",
             "MarketID": 5, "StarSystem": "S100", "SystemAddress": 100, "StationServices": []},
            {"timestamp": "2026-05-01T10:03:00Z", "event": "HullDamage", "Health": 0.6, "PlayerPilot": True},
            {"timestamp": "2026-05-01T10:04:00Z", "event": "FuelScoop", "Scooped": 5.0, "Total": 32.0},
            {"timestamp": "2026-05-01T10:05:00Z", "event": "MultiSellExplorationData", "TotalEarnings": 1000,
             "BaseValue": 1000, "Bonus": 0, "Discovered": []},
            org("2026-05-01T10:06:00Z", 100, 3, "Bacterial_01", "Log")])
        legacy = self.write("legacy", "Journal.2025-01-01T100000.01.log", [
            {"timestamp": "2025-01-01T10:00:00Z", "event": "CarrierLocation", "CarrierID": 7, "StarSystem": "S50",
             "SystemAddress": 50},
            {"timestamp": "2025-01-01T10:00:01Z", "event": "CarrierStats", "CarrierID": 7, "Name": "C", "Callsign": "ABC-123",
             "FuelLevel": 100, "JumpRangeCurr": 500},
            self.jump("2025-01-01T10:01:00Z", 50, 10),
            {"timestamp": "2025-01-01T10:02:00Z", "event": "Undocked", "StationName": "Stn"},
            {"timestamp": "2025-01-01T10:02:30Z", "event": "Docked", "StationName": "Old", "StationType": "Outpost",
             "MarketID": 6, "StarSystem": "S50", "SystemAddress": 50, "StationServices": []},
            {"timestamp": "2025-01-01T10:03:00Z", "event": "HullDamage", "Health": 0.2, "PlayerPilot": True},
            {"timestamp": "2025-01-01T10:04:00Z", "event": "FuelScoop", "Scooped": 5.0, "Total": 32.0},
            {"timestamp": "2025-01-01T10:04:30Z", "event": "JetConeBoost", "BoostValue": 4.0},
            {"timestamp": "2025-01-01T10:04:40Z", "event": "SupercruiseDestinationDrop", "Type": "$Fixed_Event_Life_Cloud;"},
            {"timestamp": "2025-01-01T10:05:00Z", "event": "MultiSellExplorationData", "TotalEarnings": 5,
             "BaseValue": 5, "Bonus": 0, "Discovered": []},
            {"timestamp": "2025-01-01T10:06:00Z", "event": "Died"},
            org("2025-01-01T10:07:00Z", 50, 2, "Bacterial_02", "Log")])
        self.j.scan_dir(live)
        self.j.scan_dir(legacy)       # a legacy folder mounted later: imported after the live data
        j = self.j
        self.assertEqual((j.pos["id64"], j.docked["station"], j.hull["pct"]), (100, "Stn", 60))
        self.assertEqual((j.carrier["id64"], j.carrier["fuel"]), (100, 800))
        self.assertEqual(j.last_scoop, "2026-05-01T10:04:00Z")
        self.assertIsNone(j.boost)
        self.assertEqual((j.last_sale["ts"], j.last_sale["carto"]), ("2026-05-01T10:05:00Z", 1000))
        self.assertEqual(self.db.execute("SELECT count(*) FROM phenomena").fetchone()[0], 0)   # no old drop filed here
        runs = {r[0] for r in self.db.execute("SELECT system FROM own_organic WHERE done_ts IS NULL")}
        self.assertIn(100, runs)      # the old death and the old run did not abandon the current sample run
        # and the same state survives a reload from the database
        j.reload()
        self.assertEqual((j.docked["station"], j.hull["pct"], j.carrier["fuel"]), ("Stn", 60, 800))

    def test_station_repair_lists_items(self):   # F13
        self.j.handle({"timestamp": "2026-01-01T00:00:00Z", "event": "HullDamage", "Health": 0.57, "PlayerPilot": True})
        self.j.handle({"timestamp": "2026-01-01T00:01:00Z", "event": "Repair", "Items": ["Paint"], "Cost": 2})
        self.assertEqual(self.j.hull["pct"], 57)
        self.j.handle({"timestamp": "2026-01-01T00:02:00Z", "event": "Repair", "Items": ["Hull"], "Cost": 3134})
        self.assertEqual(self.j.hull["pct"], 100)
        self.j.handle({"timestamp": "2026-01-01T00:03:00Z", "event": "HullDamage", "Health": 0.5, "PlayerPilot": True})
        self.j.handle({"timestamp": "2026-01-01T00:04:00Z", "event": "Repair", "Item": "Hull", "Cost": 10})   # the older form
        self.assertEqual(self.j.hull["pct"], 100)

    def test_limpet_repair_makes_hull_unknown(self):   # F14; fourth review F4: Synthesis "Repair Basic" is the SRV's
        self.assertIn(b'"event":"RepairDrone"', ed_outrider.WANTED)
        self.j.handle({"timestamp": "2026-01-01T00:00:00Z", "event": "HullDamage", "Health": 0.38, "PlayerPilot": True})
        self.j.handle({"timestamp": "2026-01-01T00:01:00Z", "event": "RepairDrone", "HullRepaired": 58.5})
        self.assertEqual(self.j.hull, {"pct": None, "ts": "2026-01-01T00:01:00Z", "repaired": True})
        self.j.handle({"timestamp": "2026-01-01T00:02:00Z", "event": "HullDamage", "Health": 0.7, "PlayerPilot": True})
        self.assertEqual(self.j.hull["pct"], 70)
        self.j.handle({"timestamp": "2026-01-01T00:03:00Z", "event": "Synthesis", "Name": "Repair Basic",
                       "Materials": [{"Name": "iron", "Count": 2}, {"Name": "nickel", "Count": 1}]})
        self.assertEqual(self.j.hull["pct"], 70)   # the SRV's repair: the ship's hull stays known, no second alert
        self.assertIn("SRV repair basic", ed_materials.SYNTH)

    def test_same_journal_in_two_folders_counts_once(self):   # F51
        name = "Journal.2026-01-01T000000.01.log"
        a = self.write("a", name, [self.jump("2026-01-01T00:00:00Z", 1)])
        b = self.write("b", name, [self.jump("2026-01-01T00:00:00Z", 1)])
        self.j.scan_dir(a)
        self.j.scan_dir(b)
        self.assertEqual(self.db.execute("SELECT count FROM visits WHERE id64=1").fetchone()[0], 1)
        self.write("b", name, [self.jump("2026-01-01T00:10:00Z", 2, 10)])   # the copy grows: only the new line is read
        self.j.scan_dir(b)
        self.j.scan_dir(a)
        self.assertEqual({r[0]: r[1] for r in self.db.execute("SELECT id64, count FROM visits")}, {1: 1, 2: 1})
        self.j.reload()                                                     # and after a restart
        self.j.scan_dir(a)
        self.j.scan_dir(b)
        self.assertEqual({r[0]: r[1] for r in self.db.execute("SELECT id64, count FROM visits")}, {1: 1, 2: 1})


class Batch3Server(unittest.TestCase):
    """Second review, batch 3: server state and background work."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def jump(self, ts, id64, x, kind="FSDJump"):
        self.j.handle({"event": kind, "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def fake_spansh(self, dump):
        calls = []

        class FakeSpansh(ed_outrider.Spansh):
            async def lookup(self, id64, interactive=True):
                calls.append(id64)
                return dump
        return FakeSpansh(self.db), calls

    def test_dump_404_is_remembered(self):   # F52
        import asyncio
        sp, calls = self.fake_spansh(None)
        self.state.spansh = sp
        base = {"v": ed_outrider.CACHE_VERSION, "name": "Sys", "x": 0, "y": 0, "z": 0, "body_count": 3,
                "records": [{"name": "Sys 1", "type": "Planet", "subtype": "Icy body", "full": False}]}
        got = asyncio.run(sp.full_records(7, "u1", base))
        self.assertTrue(got["no_dump"])
        self.assertEqual(sp.cached(7)[0], "u1")                # cached with the search's updated_at
        self.db.execute("INSERT INTO visits VALUES (7, 'Sys', 0, 0, 0, 't', 't', 1)")
        self.state.bases[7] = ("spansh", got)
        self.assertFalse(self.state.system_detail(7)["partial"])  # the page stops polling
        del self.state.bases[7]
        asyncio.run(self.state.ensure_records(7))                 # on demand: not asked again within the day
        self.assertEqual(calls, [7])

    def test_dump_body_count_is_kept(self):   # F53
        import asyncio
        sp, _ = self.fake_spansh({"system": {"bodyCount": 12, "bodies": []}})
        got = asyncio.run(sp.full_records(7, None, {"v": ed_outrider.CACHE_VERSION, "name": "Sys", "x": 0, "y": 0, "z": 0,
                                                    "body_count": None, "records": [], "no_dump": True}))
        self.assertEqual(got["body_count"], 12)
        self.assertNotIn("no_dump", got)

    def test_edsm_star_is_a_placeholder(self):   # F54
        base = ed_outrider.base_from_edsm({"name": "Sys", "coords": {"x": 0, "y": 0, "z": 0},
                                           "primaryStar": {"type": "K (Yellow-Orange) Star", "isScoopable": True}})
        own = {"A": {"name": "A", "type": "Star", "subtype": "K (Yellow-Orange) Star", "main": True, "rings": []},
               "B": {"name": "B", "type": "Star", "subtype": "M (Red dwarf) Star", "main": False, "rings": []}}
        self.assertEqual([r["name"] for r in ed_outrider.merge_records(base["records"], own, {})], ["A", "B"])
        planets = {"1": {"name": "1", "type": "Planet", "subtype": "Icy body", "main": False, "rings": []}}
        self.assertEqual(len(ed_outrider.merge_records(base["records"], planets, {})), 2)   # still the only star known

    def test_carrier_lookup_backs_off(self):   # F19
        import asyncio
        sp, calls = self.fake_spansh(None)
        self.state.spansh = sp
        self.j.carrier = {"id": 7, "id64": 555, "system": "Deep", "x": None}

        async def go():
            for _ in range(3):
                self.state.maybe_locate_carrier()
                if self.state.carrier_task:
                    await self.state.carrier_task
        asyncio.run(go())
        self.assertEqual(calls, [555])
        self.state.carrier_retry[555] = 0     # ten minutes later: asked again
        asyncio.run(go())
        self.assertEqual(calls, [555, 555])

    def test_seller_reported_minutes_ago_is_fresh(self):   # F17
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 1200))
        uc = [{"name": "XYZ-123", "type": "Drake-Class Carrier", "updated_at": now, "x": 40, "y": 0, "z": 0, "distance": 40},
              {"name": "Far Port", "type": "Coriolis Starport", "updated_at": "2026-01-01T00:00:00Z",
               "x": 400, "y": 0, "z": 0, "distance": 400}]
        ed_outrider.meta_set(self.db, "sellers", {"pos": {"x": 0, "y": 0, "z": 0, "name": "S1"}, "fetched": time.time(),
                                                  "uc": uc, "vista": []})
        self.assertEqual(self.state.sellers_summary()["uc"]["fresh"]["name"], "XYZ-123")

    def test_value_only_changes_leave_scan_version(self):   # G2.1
        import asyncio
        self.state.bases = {1: ("spansh", {"name": "S1", "x": 0, "y": 0, "z": 0, "records": []}),
                            2: ("spansh", {"name": "S2", "x": 1, "y": 0, "z": 0, "records": []})}
        self.state.center = {"x": 0, "y": 0, "z": 0}
        results = iter([{"carto": {}, "system_values": {"S1": 10}}, {"carto": {}, "system_values": {"S1": 10}},
                        {"carto": {}, "system_values": {"S1": 10, "S2": 5}}])

        async def unsold_once():
            self.state.unsold_dirty, self.state.unsold_at = True, 0
            self.state.maybe_unsold()
            await self.state.unsold_task
            return set(self.state.value_dirty)
        with unittest.mock.patch.object(ed_outrider, "compute_unsold", lambda: next(results)):
            self.assertEqual(asyncio.run(unsold_once()), {1})
            self.state.apply_own_changes()
            self.assertEqual(self.state.scan_version, 0)          # rows rebuilt, no "new scan data"
            self.assertIn(1, self.state.systems)
            self.assertEqual(asyncio.run(unsold_once()), set())   # nothing moved: nothing rebuilt
            self.assertEqual(asyncio.run(unsold_once()), {2})

    def test_failed_estimate_does_not_break_a_sale(self):   # F18
        self.state.unsold = {"error": "no journals"}
        self.state.bases = {1: ("spansh", {"name": "S1", "x": 0, "y": 0, "z": 0, "records": []})}
        self.state.center = {"x": 0, "y": 0, "z": 0}
        self.j.sales_changed = True
        self.j.dirty.add(1)
        self.state.apply_own_changes()
        self.assertIn(1, self.state.systems)
        self.assertFalse(self.j.sales_changed)

    def test_row_error_stays_visible_and_retries(self):   # F89
        import asyncio, contextlib, io
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        self.state.center = self.j.pos
        self.state.bases = {1: ("spansh", {"name": "S1", "x": 0, "y": 0, "z": 0, "records": []})}
        self.state.unsold_dirty = False
        self.j.dirty.add(1)
        fail = {"on": True}
        real = self.state.row

        def row(id64):
            if fail["on"]:
                raise ValueError("bad record")
            return real(id64)
        self.state.row = row
        err = io.StringIO()

        async def ticks(n):
            for _ in range(n):
                self.state.tick({})
        with unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []), contextlib.redirect_stderr(err):
            asyncio.run(ticks(3))
            self.assertIn("bad record", self.state.tail_error)     # still shown after the tick that set it
            self.assertEqual(err.getvalue().count("Traceback"), 1)   # one traceback, not one a second
            v = self.state.scan_version
            fail["on"] = False
            asyncio.run(ticks(1))
        self.assertIsNone(self.state.tail_error)
        self.assertIn(1, self.state.systems)                       # retried and built
        self.assertEqual(self.state.scan_version, v)               # a retry is not new scan data

    def test_backup_failure_leaves_nothing(self):   # F55
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            dbp = os.path.join(d, "x.sqlite")
            sqlite3.connect(dbp).close()
            out = os.path.join(d, "backups")
            self.state.db_path = dbp
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(zipfile.ZipFile, "write", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(OSError):
                    self.state.make_backup()
            self.assertEqual(os.listdir(out), [])

    def test_route_export_after_respawn(self):   # F57
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        self.jump("2026-01-01T01:00:00Z", 2, 100, kind="Location")   # respawn somewhere new
        self.jump("2026-01-01T01:10:00Z", 3, 122)
        _, rows = self.state.export_rows("route")
        self.assertEqual([r["ly"] for r in rows], [None, None, 22.0])
        self.assertEqual(self.state.sessions("")[0]["ly"], 22.0)

    def test_history_counts_after_the_last_jump(self):   # F7
        self.jump("2026-01-01T22:00:00Z", 1, 0)
        self.db.execute("INSERT INTO own_mapped (system, body_id, ts) VALUES (1, 4, '2026-01-01T23:00:00Z')")   # after the session's only jump
        self.db.execute("INSERT INTO own_mapped (system, body_id, ts) VALUES (1, 5, '2026-01-02T03:00:00Z')")   # a long stay, no jump
        self.jump("2026-01-03T10:00:00Z", 2, 10)
        self.db.execute("INSERT INTO own_mapped (system, body_id, ts) VALUES (2, 1, '2026-01-03T11:00:00Z')")
        h = self.state.history(3650 * 3)
        self.assertEqual([s["mapped"] for s in h["sessions"]], [1, 2])   # newest first; together = all time
        self.assertEqual(h["all_time"]["mapped"], 3)

    def test_trip_hours_clip_sessions_at_the_sale(self):   # F16
        # one session: 3 h flying home, a sale, 1 h more exploring (jumps every 30 min keep it one session)
        t0 = ed_outrider.ts_seconds("2026-01-01T00:00:00Z")
        stamp = lambda s: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 + s))
        for i in range(9):
            self.jump(stamp(i * 1800), 10 + i, i * 10)
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": stamp(3 * 3600), "TotalEarnings": 300,
                       "BaseValue": 300, "Bonus": 0, "Discovered": []})
        self.jump(stamp(4 * 3600 + 1800), 30, 200)
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": stamp(5 * 3600), "TotalEarnings": 100,
                       "BaseValue": 100, "Bonus": 0, "Discovered": []})
        self.db.commit()
        trips = self.state.ledger()["trips"]          # newest first
        self.assertEqual([t["hours"] for t in trips], [1.5, 3.0])
        self.assertEqual(trips[1]["per_hour"], 100)

    def test_autohonk_toggle_is_committed(self):   # F62
        self.state.set_autohonk(True)
        self.db.rollback()                            # a failing watcher tick
        self.assertIs(ed_outrider.meta_get(self.db, "autohonk_enabled"), True)

    def test_voice_choice_is_saved(self):   # F21
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        class FakeSpeaker:
            available = True

            def use(self, name):
                return name == "en_GB-alba-medium"
        self.state.speaker = FakeSpeaker()

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return (await c.post("/api/voice", json={"voice": "en_GB-alba-medium"})).status
        self.assertEqual(asyncio.run(go()), 200)
        self.assertIsNone(ed_outrider.meta_get(self.db, "voice_choice"))   # F36: saved once it has loaded
        self.state.remember_voice("en_GB-alba-medium")                      # (the Speaker's on_switched)
        self.db.rollback()
        self.assertEqual(ed_outrider.meta_get(self.db, "voice_choice"), "en_GB-alba-medium")

    def test_startup_voice_load_does_not_replace_the_chosen_one(self):   # F21
        import io, tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            for v in ("en_GB-a-low", "en_GB-b-low"):
                for ext in (".onnx", ".onnx.json"):
                    open(os.path.join(d, v + ext), "w").close()
            sp = ed_tts.Speaker("en_GB-a-low", None, voices_dir=d)
            sp.PiperVoice = unittest.mock.Mock()
            sp.PiperVoice.load = lambda path: os.path.basename(path)
            sp.wanted = "en_GB-b-low"
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                sp._prepare("en_GB-b-low")    # the dialog's pick loads first
                sp._prepare(None)             # then the slow start-up load of the configured voice finishes
            self.assertEqual((sp.voice_name, sp._voice), ("en_GB-b-low", "en_GB-b-low.onnx"))

    def test_star_pair_planets_are_not_a_planet_pair(self):   # F47
        via = [{"kind": "Null", "id": 3}, {"kind": "Star", "id": 0}]
        p1 = {"name": "BC 1", "type": "Planet", "body_id": 20, "parents_full": via}
        p2 = {"name": "BC 2", "type": "Planet", "body_id": 21, "parents_full": via}
        self.assertEqual(ed_outrider.system_curiosities("S", [p1, p2]), {})   # stars B and C not scanned
        moons = [{"name": f"BC 1 {m}", "type": "Planet", "body_id": 30 + i, "parents_full": [{"kind": "Null", "id": 29}] + via}
                 for i, m in enumerate("ab")]
        self.assertEqual(set(ed_outrider.system_curiosities("S", moons)), {"BC 1 a", "BC 1 b"})   # a real pair of moons

    def test_bio_left_after_a_finished_genus(self):   # F20b
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        s = scan("2026-01-01T00:01:00Z", "S1", 1, 2, "S1 2")[2]
        self.j.handle(s)
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:01:00Z", "SystemAddress": 1, "BodyID": 2,
                       "BodyName": "S1 2", "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 1}]})
        for i, k in enumerate(("Log", "Sample", "Analyse")):
            self.j.handle(org(f"2026-01-01T00:0{2 + i}:00Z", 1, 2, "Bacterial_01", k))
        self.db.commit()
        cands = Batch2Values.CANDS
        with unittest.mock.patch.object(ed_bio, "predict", return_value=cands):
            b = next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == "2")
            self.assertEqual(b["value_parts"]["bio_left"], 0)        # the one signal is done
            recs = ed_outrider.merge_records([], *ed_outrider.own_data(self.db, 1, "S1")[:2])
            self.assertEqual(self.state.system_value(1, "S1", recs, None)["value_parts"]["bio_left"], 0)
            # two signals, Bacterium done: the other is the most valuable of the rest (not Stratum + Concha)
            self.db.execute("UPDATE own_signals SET bio = 2")
            b = next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == "2")
            self.assertEqual(b["value_parts"]["bio_left"], 19_010_800 * b["value_parts"]["bio_factor"])
            recs = ed_outrider.merge_records([], *ed_outrider.own_data(self.db, 1, "S1")[:2])
            self.assertEqual(self.state.system_value(1, "S1", recs, None)["value_parts"]["bio_left"], 19_010_800)

    def test_local_search_runs_off_the_loop(self):   # F22
        import asyncio, tempfile, threading
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "odd name.sqlite")
            db = ed_outrider.open_db(path)
            self.addCleanup(db.close)
            j = ed_outrider.Journals(db)
            j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "S1", "SystemAddress": 1,
                      "StarPos": [0, 0, 0]})
            j.handle(scan("2026-01-01T00:01:00Z", "S1", 1, 0, "S1", star=True)[2])
            db.commit()
            state = ed_outrider.State(db, j, ed_outrider.Spansh(db), 25)
            state.db_path = path
            s = ed_outrider.Searcher(state)
            seen = []
            real = s.match

            def match(conn, *a):
                seen.append((threading.current_thread() is threading.main_thread(), conn is db))
                return real(conn, *a)
            s.match = match

            async def go():
                s.start({"source": "local", "radius": 50, "stars": ["K"]})
                await s.task
            asyncio.run(go())
            self.assertEqual(seen, [(False, False)])       # a worker thread, with its own connection
            self.assertEqual([r["name"] for r in s.result["results"]], ["S1"])


class Batch4Page(unittest.TestCase):
    """Second review, batch 4: the server side of the page-robustness fixes (map, schematic, Log)."""

    def folder(self, files):
        import tempfile, json as _j
        d = tempfile.mkdtemp()
        for name, events in files.items():
            with open(os.path.join(d, name), "w") as f:
                for e in events:
                    f.write(_j.dumps(e, separators=(",", ":")) + "\n")
        return d

    def state(self, spansh):
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        j = ed_outrider.Journals(db)
        j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "S1", "SystemAddress": 1,
                  "StarPos": [0, 0, 0]})
        return ed_outrider.State(db, j, spansh, 25), j, db

    def test_body_rows_carry_belts(self):   # F69
        import types
        state, j, db = self.state(types.SimpleNamespace(cached=lambda i: (None, None)))
        ev = scan("2026-01-01T00:01:00Z", "S1", 1, 0, "S1", star=True)[2]
        ev["Rings"] = [{"Name": "S1 A Belt", "RingClass": "eRingClass_Rocky", "MassMT": 1e9, "InnerRad": 1, "OuterRad": 2}]
        j.handle(ev)
        db.commit()
        star = next(b for b in state.system_detail(1)["bodies"] if b["type"] == "Star")
        self.assertEqual(len(star["belts"]), 1)
        self.assertEqual(star["rings"], 0)

    def test_map_says_partial_when_spansh_failed(self):   # F71
        import asyncio, types
        ok = {"fail": True}

        async def sphere(pos, radius, pages):
            if ok["fail"]:
                raise RuntimeError("timeout")
            return [{"id64": 2, "name": "S2", "x": 1, "y": 0, "z": 0, "distance": 1, "bodies": []}]
        state, j, db = self.state(types.SimpleNamespace(cached=lambda i: (None, None), sphere=sphere))
        d = asyncio.run(state.map_payload(10, 5))
        self.assertTrue(d["partial"])
        self.assertIn("Spansh lookup failed", d["note"])
        ok["fail"] = False
        d = asyncio.run(state.map_payload(10, 5))          # not cached: asked again, and complete now
        self.assertFalse(d["partial"])
        self.assertIn("S2", [p["name"] for p in d["points"]])

    def test_tail_past_an_empty_new_journal(self):   # F84
        now = dt.datetime.now(dt.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        a = (now - dt.timedelta(minutes=5)).strftime("Journal.%Y-%m-%dT%H%M%S.01.log")
        b = now.strftime("Journal.%Y-%m-%dT%H%M%S.01.log")
        d = self.folder({a: [{"timestamp": ts, "event": "FSDJump", "StarSystem": f"S{i}"} for i in range(4)]})
        open(os.path.join(d, b), "w").close()                 # the game just created it: no complete line yet
        first = ed_log.read_log([d], days=1)
        self.assertEqual(first["newest"], f"{a}|3")             # not None: the tail can start
        t1 = ed_log.read_log([d], after=f"{a}|1")
        self.assertEqual([r["system"] for r in t1["rows"]], ["S3", "S2"])
        self.assertEqual(t1["newest"], f"{a}|3")                # not back to a|1
        self.assertEqual(ed_log.read_log([d], after=t1["newest"])["rows"], [])   # nothing twice
        with open(os.path.join(d, b), "a") as f:
            f.write(json.dumps({"timestamp": ts, "event": "FSDJump", "StarSystem": "S9"}) + "\n")
        t2 = ed_log.read_log([d], after=t1["newest"])
        self.assertEqual([r["system"] for r in t2["rows"]], ["S9"])
        self.assertEqual(t2["newest"], f"{b}|0")

    def test_unreadable_journal_is_skipped(self):   # F29
        now = dt.datetime.now(dt.timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        d = self.folder({now.strftime("Journal.%Y-%m-%dT%H%M%S.01.log"): [{"timestamp": ts, "event": "FSDJump", "StarSystem": "S1"}]})
        real_open = open

        def failing(path, *a, **k):
            if str(path).startswith(d):
                raise PermissionError(13, "Permission denied")
            return real_open(path, *a, **k)
        with unittest.mock.patch("builtins.open", failing):
            r = ed_log.read_log([d], days=1)
        self.assertEqual(r["rows"], [])

    def test_cache_is_thread_safe(self):   # F83
        import tempfile, threading
        d = tempfile.mkdtemp()
        paths = []
        for i in range(ed_log._CACHE_MAX * 2):
            p = os.path.join(d, f"Journal.2026-09-{1 + i // 10:02d}T{10 + i % 10:02d}0000.01.log")
            with open(p, "w") as f:
                f.write('{"timestamp":"2026-09-01T00:00:00Z","event":"Music"}\n')
            paths.append(p)
        errors = []

        def work(k):
            for n in range(600):
                try:
                    ed_log._load(paths[(n * 7 + k) % len(paths)])
                except Exception as e:     # without the lock: "OrderedDict mutated during iteration"
                    errors.append(e)
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        try:
            ts = [threading.Thread(target=work, args=(k,)) for k in range(6)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        finally:
            sys.setswitchinterval(old)
        self.assertEqual(errors, [])


class _FakeResponse:
    """A urlopen() result for the download tests: serves `data` in chunks, then fails with `fail` if set."""

    def __init__(self, data, fail=None, length=None):
        self.data, self.fail = data, fail
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        if not self.data:
            if self.fail:
                raise self.fail
            return b""
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk


class Batch5ConfigCli(unittest.TestCase):
    """Second review, batch 5: config edge cases, the auto honk binding, Piper downloads and the voice lab."""

    ARGS = dict(journals=None, legacy=None, host=None, port=None, radius=None, db=None)

    def settings(self, cfg, detected=([], []), **args):
        import contextlib, io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            st = ed_outrider.settings_from(cfg, argparse.Namespace(**dict(self.ARGS, **args)), None, detected)
        return st, err.getvalue()

    def test_config_not_utf8(self):   # F48
        import contextlib, io, tempfile
        with tempfile.NamedTemporaryFile("wb", suffix=".toml", delete=False) as f:
            f.write('[defaults]\nspeech_names = "Jos\xe9"\n'.encode("cp1252"))
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                self.assertEqual(ed_outrider.load_config(f.name), {})
        finally:
            os.remove(f.name)
        self.assertIn("(ignored)", err.getvalue())

    def test_infinite_numbers(self):   # F49
        import tomllib
        cfg = tomllib.loads("[defaults]\nunsold_warn = inf\nspeech_speed = nan\n[server]\nradius = inf\n"
                            "radius_choices = [inf, 30]\n[spansh]\nconcurrency = -inf\n")
        st, err = self.settings(cfg)
        self.assertEqual((st["unsold_warn"], st["speech_speed"], st["radius"], st["radius_choices"], st["concurrency"]),
                         (ed_outrider.UNSOLD_WARN, ed_outrider.SPEECH_SPEED, 25.0, [30.0], ed_outrider.SPANSH_CONCURRENCY))
        for key in ("unsold_warn", "speech_speed", "radius", "concurrency"):
            self.assertIn(key, err)

    def test_empty_folder_lists_turn_detection_off(self):   # F46
        det = (["/live"], ["/mnt/c/old"])
        self.assertEqual(self.settings({"journals": {"legacy": []}}, det)[0]["legacy"], [])
        self.assertEqual(self.settings({"journals": {"legacy": []}}, det)[0]["live"], ["/live"])
        st = self.settings({"journals": {"live": []}}, det)[0]
        self.assertEqual((st["live"], st["legacy"]), ([], []))
        st = self.settings({"journals": {}}, det)[0]
        self.assertEqual((st["live"], st["legacy"]), (["/live"], ["/mnt/c/old"]))
        self.assertEqual(self.settings({"journals": {"legacy": []}}, det, legacy=["/flag"])[0]["legacy"], ["/flag"])

    def test_write_config_keeps_detection_for_an_empty_live_list(self):   # F46: --write-config with nothing found
        import tomllib
        st = self.settings({}, ([], []))[0]
        back = tomllib.loads(ed_outrider.config_text(st))["journals"]
        self.assertNotIn("live", back)          # a written "live = []" would turn detection off for good
        self.assertNotIn("legacy", back)        # F40: nor would "legacy = []" for the legacy folders

    def test_db_flag_is_relative_to_the_current_folder(self):   # F23
        st = self.settings({"server": {"db": "from-config.sqlite"}}, db="scratch.sqlite")[0]
        self.assertEqual(st["db"], os.path.join(os.getcwd(), "scratch.sqlite"))
        st = self.settings({"server": {"db": "from-config.sqlite"}})[0]
        self.assertEqual(st["db"], os.path.join(ed_outrider.SCRIPT_DIR, "from-config.sqlite"))
        self.assertEqual(self.settings({})[0]["db"], ed_outrider.DB_PATH)
        self.assertEqual(self.settings({}, db="/abs/x.sqlite")[0]["db"], "/abs/x.sqlite")

    def test_spansh_limits(self):   # F50
        st = self.settings({"spansh": {"concurrency": 0, "map_max_pages": -2, "map_max_radius": 1}})[0]
        self.assertEqual((st["concurrency"], st["map_max_pages"], st["map_max_radius"]), (1, 1, 5.0))
        st = self.settings({"spansh": {"concurrency": 8, "map_max_pages": 3, "map_max_radius": 400}})[0]
        self.assertEqual((st["concurrency"], st["map_max_pages"], st["map_max_radius"]), (8, 3, 400.0))

    # ---- auto honk binding ----
    def controls(self, root, start="My X56\nMy X56\nMy X56\nMy X56"):
        journals = os.path.join(root, "steamuser", "Saved Games", "Frontier Developments", "Elite Dangerous")
        binds = os.path.join(root, "steamuser", "AppData", "Local", "Frontier Developments", "Elite Dangerous",
                             "Options", "Bindings")
        os.makedirs(journals, exist_ok=True)
        os.makedirs(binds, exist_ok=True)
        if start is not None:
            with open(os.path.join(binds, "StartPreset.4.start"), "w") as f:
                f.write(start)
        return journals, binds

    @staticmethod
    def binds_file(binds, preset, key="Key_K", mods=()):
        m = "".join(f'<Modifier Device="Keyboard" Key="{k}" />' for k in mods)
        with open(os.path.join(binds, f"{preset}.4.2.binds"), "w") as f:
            f.write(f'<?xml version="1.0" encoding="UTF-8" ?><Root PresetName="{preset}"><PrimaryFire>'
                    f'<Primary Device="Keyboard" Key="{key}">{m}</Primary></PrimaryFire></Root>')

    def test_ship_line_of_the_start_preset(self):   # F42
        import tempfile
        import ed_honk
        with tempfile.TemporaryDirectory() as root:
            journals, binds = self.controls(root, "General One\nShip Two\nSRV Three\nFoot Four")
            self.binds_file(binds, "General One", "Key_G")
            self.binds_file(binds, "Ship Two", "Key_S")
            keys, what = ed_honk.primary_fire_binding([journals])
            self.assertEqual(keys, ["KEY_S"])
            self.assertIn("Ship Two", what)
        with tempfile.TemporaryDirectory() as root:   # an older single-line file
            journals, binds = self.controls(root, "General One\n")
            self.binds_file(binds, "General One", "Key_G")
            self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_G"])

    def test_built_in_preset_does_not_borrow_a_custom_file(self):   # F43
        import tempfile
        import ed_honk
        with tempfile.TemporaryDirectory() as root:
            journals, binds = self.controls(root, "KeyboardMouseOnly\n" * 4)
            self.binds_file(binds, "Custom", "Key_C")
            keys, what = ed_honk.primary_fire_binding([journals])
            self.assertIsNone(keys)
            self.assertIn("built-in", what)
            self.assertIn("KeyboardMouseOnly", what)
        with tempfile.TemporaryDirectory() as root:   # no preset named at all: the newest Custom file
            journals, binds = self.controls(root, None)
            self.binds_file(binds, "Custom", "Key_C")
            self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_C"])

    def test_auto_binding_checked_against_evdev(self):   # F41
        import tempfile, types
        import ed_honk
        self.assertEqual([ed_honk.elite_key(k) for k in ("Key_Apps", "Key_Numpad_Equals", "Key_OEM_102", "Key_Hash",
                                                        "Key_PrintScreen", "Key_Numpad_Comma")],
                         ["KEY_COMPOSE", "KEY_KPEQUAL", "KEY_102ND", "KEY_BACKSLASH", "KEY_SYSRQ", "KEY_KPCOMMA"])
        fake = types.SimpleNamespace(ecodes=types.SimpleNamespace(ecodes={"KEY_COMPOSE": 127, "KEY_LEFTALT": 56}))
        with tempfile.TemporaryDirectory() as root:
            journals, binds = self.controls(root)
            h = ed_honk.Honker("auto", journal_dirs=[journals])
            h.evdev = fake
            self.binds_file(binds, "My X56", "Key_Apps", ["Key_LeftAlt"])
            self.assertEqual(h.combo()[0], ["KEY_LEFTALT", "KEY_COMPOSE"])
            time.sleep(0.01)
            self.binds_file(binds, "My X56", "Key_Frobnicate")
            os.utime(os.path.join(binds, "My X56.4.2.binds"), (time.time() + 5, time.time() + 5))
            keys, what = h.combo()
            self.assertIsNone(keys)
            self.assertIn("no evdev equivalent for KEY_FROBNICATE", what)

    def test_binding_read_errors_and_cache(self):   # F59
        import tempfile
        import ed_honk
        with tempfile.TemporaryDirectory() as root:
            journals, binds = self.controls(root)
            self.binds_file(binds, "My X56", "Key_K")
            real = ed_honk.ET.parse
            calls = []
            with unittest.mock.patch.object(ed_honk.ET, "parse", lambda p: calls.append(p) or real(p)):
                self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_K"])
                self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_K"])
                self.assertEqual(len(calls), 1)            # unchanged files: not parsed again
                self.binds_file(binds, "My X56", "Key_L")
                os.utime(os.path.join(binds, "My X56.4.2.binds"), (time.time() + 5, time.time() + 5))
                self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_L"])   # a rebind is picked up
                self.assertEqual(len(calls), 2)
            os.utime(os.path.join(binds, "StartPreset.4.start"), (time.time() + 9, time.time() + 9))
            with unittest.mock.patch.object(ed_honk.ET, "parse", side_effect=FileNotFoundError(2, "gone")):
                keys, what = ed_honk.primary_fire_binding([journals])   # Elite rewriting the file right now
            self.assertIsNone(keys)
            self.assertIn("could not be read", what)

    def test_honk_cli_uses_config_and_detection(self):   # F85
        import contextlib, io, tempfile
        import ed_honk
        with tempfile.TemporaryDirectory() as root:
            journals, binds = self.controls(root)
            self.binds_file(binds, "My X56", "Key_K")
            here = os.path.join(root, "app")
            os.makedirs(here)
            out = io.StringIO()
            with unittest.mock.patch.object(ed_honk, "HERE", here), \
                    unittest.mock.patch.object(ed_unsold, "find_journal_dirs", return_value=([journals], [])), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(ed_honk.main(["--show"]), 0)         # no config: auto-detected folders
                with open(os.path.join(here, "ed_outrider.toml"), "w") as f:
                    f.write('[autohonk]\nkey = "KEY_KP0"\n')
                self.assertEqual(ed_honk.main(["--show"]), 0)         # the configured key
                self.assertEqual(ed_honk.main(["--show", "--key", "auto"]), 0)
            lines = out.getvalue().splitlines()
            self.assertIn("K (primary binding of Primary Fire in My X56)", lines[0])
            self.assertEqual(lines[1], "Primary Fire: Numpad 0")
            self.assertIn("My X56", lines[2])

    # ---- Piper ----
    def test_speaker_reports_every_status_and_falls_back(self):   # G2.2, F40
        import contextlib, io, tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            for v in ("en_GB-a-low", "en_GB-b-low"):
                for ext in (".onnx", ".onnx.json"):
                    open(os.path.join(d, v + ext), "w").close()
            seen = []
            sp = ed_tts.Speaker("en_GB-a-low", "en_GB-b-low", voices_dir=d, on_change=lambda: seen.append(sp.status))
            sp.PiperVoice = unittest.mock.Mock()

            def load(path):
                if "en_GB-a-low" in path:
                    raise RuntimeError("truncated model")
                return os.path.basename(path)
            sp.PiperVoice.load = load
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                sp._prepare(None)
            self.assertEqual((sp.voice_name, sp._voice), ("en_GB-b-low", "en_GB-b-low.onnx"))   # the fallback
            self.assertEqual(seen, ["loading en_GB-a-low", "loading en_GB-b-low", "ready"])
            # a voice that fails to download and one that fails to load both reach the page
            seen.clear()
            with unittest.mock.patch.object(ed_tts, "download_voice_files", side_effect=OSError("offline")), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                sp._prepare("en_GB-c-low")
            self.assertEqual(seen, ["downloading en_GB-c-low (about 63 MB)",   # F36: the loaded voice keeps speaking
                                    "could not switch to en_GB-c-low (download failed); still using en_GB-b-low"])
            seen.clear()
            with contextlib.redirect_stderr(io.StringIO()):
                sp._prepare("en_GB-a-low")
            self.assertEqual(seen[0], "loading en_GB-a-low")
            self.assertIn("could not load en_GB-a-low", seen[-1])

    def test_installed_needs_both_files(self):   # F40
        import tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "en_GB-a-low.onnx"), "w").close()
            open(os.path.join(d, "en_GB-b-low.onnx"), "w").close()
            open(os.path.join(d, "en_GB-b-low.onnx.json"), "w").close()
            open(os.path.join(d, "en_GB-c-low.onnx.part"), "w").close()
            self.assertEqual(ed_tts.installed_voices(d), ["en_GB-b-low"])

    def test_voice_paths_match_the_catalogue(self):   # F40: Outrider now downloads itself, like Piper's own tool
        import ed_tts
        self.assertEqual(ed_tts.voice_paths("en_GB-jenny_dioco-medium"),
                         ["en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx.json",
                          "en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx"])
        with self.assertRaises(ValueError):
            ed_tts.voice_paths("../x-y-low")
        cat = os.path.join(ed_tts.VOICES_DIR, "voices.json")
        if os.path.exists(cat):   # the voice lab's cached catalogue, when there is one
            with open(cat, encoding="utf-8") as f:
                doc = json.load(f)
            for name, v in doc.items():
                if ed_tts.VOICE_NAME.fullmatch(name):
                    want = sorted(p for p in v["files"] if p.endswith((".onnx", ".onnx.json")))
                    self.assertEqual(sorted(ed_tts.voice_paths(name)), want, name)

    def test_download_moves_files_in_only_when_complete(self):   # F40, F88
        import hashlib, tempfile
        import ed_tts
        files = [("en/en_GB/x/low/en_GB-x-low.onnx.json", {}), ("en/en_GB/x/low/en_GB-x-low.onnx", {})]
        with tempfile.TemporaryDirectory() as d:
            def run(responses, files=files):
                it = iter(responses)
                with unittest.mock.patch.object(ed_tts.urllib.request, "urlopen", lambda url, timeout: next(it)):
                    ed_tts.download_voice_files(files, d)
            # the connection drops 3 bytes into the model: nothing is left, not even the finished config
            with self.assertRaises(ConnectionResetError):
                run([_FakeResponse(b"{}"), _FakeResponse(b"abc", ConnectionResetError("reset"))])
            self.assertEqual(os.listdir(d), [])
            # a short body (the server closed early without an error)
            with self.assertRaises(IOError):
                run([_FakeResponse(b"{}"), _FakeResponse(b"abc", length=10)])
            self.assertEqual(os.listdir(d), [])
            # a checksum mismatch
            with self.assertRaises(IOError):
                run([_FakeResponse(b"model")], [("a/en_GB-x-low.onnx", {"md5_digest": "0" * 32})])
            self.assertEqual(os.listdir(d), [])
            run([_FakeResponse(b"{}"), _FakeResponse(b"model")],
                [files[0], (files[1][0], {"md5_digest": hashlib.md5(b"model").hexdigest()})])
            self.assertEqual(sorted(os.listdir(d)), ["en_GB-x-low.onnx", "en_GB-x-low.onnx.json"])
            self.assertEqual(ed_tts.installed_voices(d), ["en_GB-x-low"])

    def test_voice_lab_download_and_pump(self):   # F88, F44
        import tempfile, types, queue
        try:
            import voice_lab
        except (ImportError, SystemExit):
            self.skipTest("no tkinter")
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(voice_lab, "VOICES_DIR", d):
            entry = {"files": {"en/en_GB/x/low/en_GB-x-low.onnx": {"size_bytes": 10},
                               "en/en_GB/x/low/en_GB-x-low.onnx.json": {"size_bytes": 2},
                               "en/en_GB/x/low/MODEL_CARD": {}}}
            it = iter([_FakeResponse(b"{}"), _FakeResponse(b"abc", OSError("Wi-Fi dropped"))])
            with unittest.mock.patch.object(voice_lab.ed_tts.urllib.request, "urlopen", lambda url, timeout: next(it)):
                with self.assertRaises(OSError):
                    voice_lab.download(entry, lambda done, total: None)
            self.assertEqual(os.listdir(d), [])
        # a failing callback neither stops the queue nor the pump's re-arming
        ran, status, rearmed = [], [], []
        lab = types.SimpleNamespace(q=queue.Queue(), root=types.SimpleNamespace(after=lambda ms, f: rearmed.append(ms)),
                                    set_status=lambda text, error=False: status.append((text, error)), pump=None)
        lab.q.put(lambda: open("/nonexistent-dir/x.wav", "wb"))
        lab.q.put(lambda: ran.append(1))
        voice_lab.Lab.pump(lab)
        self.assertEqual((ran, rearmed, status[0][1]), ([1], [80], True))
        self.assertIn("FileNotFoundError", status[0][0])

    def test_spoken_numbers_stay_fixed_point(self):   # F82
        self.assertEqual(ed_speech.spoken_text("Carried 1234567.89 cr"), "Carried 1234567.9 credits")
        self.assertEqual(ed_speech.spoken_text("123456.78 and 52.0M and 0.96"), "123456.8 and 52 million and 1")


class Batch6Voice(unittest.TestCase):
    """Batch 6 part 2: the FSS debrief, leaving a body, species complete, flight call-outs, the approach and
    arrival briefings, and the session recap (server-side triggers and the facts they carry)."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.jump("2026-01-01T00:00:00Z", 1, 0)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def honk(self, ts, id64, count, progress=0.2):
        self.j.handle({"event": "FSSDiscoveryScan", "timestamp": ts, "SystemName": f"S{id64}", "SystemAddress": id64,
                       "BodyCount": count, "Progress": progress})

    def planet(self, ts, id64, body_id, name, **kw):
        ev = scan(ts, f"S{id64}", id64, body_id, f"S{id64} {name}")[2]
        ev.update(kw)
        self.j.handle(ev)

    def moments(self, kind):
        self.db.commit()
        return [m for m in self.state.moments_summary() if m["kind"] == kind]

    def test_events_wanted(self):
        for e in ("ApproachBody", "LeaveBody", "Touchdown"):
            self.assertIn(f'"event":"{e}"'.encode(), ed_outrider.WANTED)
        self.assertGreaterEqual(ed_outrider.PARSER_VERSION, 25)

    def test_fss_done(self):   # P1: after a manual FSS, with the leaving summary; not after a honk that found everything
        self.honk("2026-01-01T00:00:10Z", 1, 3)
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", PlanetClass="Water world", TerraformState="Terraformable", MassEM=0.5)
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:02:00Z", "SystemName": "S1", "SystemAddress": 1, "Count": 3})
        done = self.moments("fss_done")
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["count"], done[0]["system_name"], done[0]["leaving"]["all_found"]), (3, "S1", True))
        self.assertEqual(done[0]["leaving"]["unmapped"][0]["body"], "A 4")
        self.jump("2026-01-01T00:10:00Z", 2, 10)
        self.honk("2026-01-01T00:10:10Z", 2, 1, progress=1.0)
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:10:10Z", "SystemName": "S2", "SystemAddress": 2, "Count": 1})
        self.jump("2026-01-01T00:20:00Z", 3, 20)
        self.honk("2026-01-01T00:20:10Z", 3, 2, progress=0.5)
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:20:12Z", "SystemName": "S3", "SystemAddress": 3, "Count": 2})
        self.assertEqual([m["system"] for m in self.moments("fss_done")], ["1"])   # the honk said it: no debrief

    def test_fss_closed_unfinished(self):   # P1: GuiFocus 9 -> 0 with bodies hidden, judged 2 s later, once per visit
        live = lambda focus: {"live": True, "ts": "2026-01-01T00:05:00Z", "flags": 0, "gui_focus": focus}
        self.honk("2026-01-01T00:00:10Z", 1, 5)
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4")
        self.db.commit()
        for t, focus in ((0, 9), (1, 0), (2, 0)):
            self.j.status_json = live(focus)
            self.state.watch_fss(1000 + t)
        self.assertEqual(self.moments("fss_unfinished"), [])          # not yet: the journal may still be catching up
        self.state.watch_fss(1003.5)
        got = self.moments("fss_unfinished")
        self.assertEqual([(m["left"], m["system_name"]) for m in got], [(4, "S1")])
        for t, focus in ((10, 9), (11, 0), (20, 0)):                  # closed again on the same visit: said once
            self.j.status_json = live(focus)
            self.state.watch_fss(1000 + t)
        self.assertEqual(len(self.moments("fss_unfinished")), 1)
        # all found, or a system never honked: nothing to say
        self.jump("2026-01-01T00:10:00Z", 2, 10)
        self.db.commit()
        for t, focus in ((30, 9), (31, 0), (40, 0)):
            self.j.status_json = live(focus)
            self.state.watch_fss(1000 + t)
        self.honk("2026-01-01T00:10:10Z", 2, 5)
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:11:00Z", "SystemName": "S2", "SystemAddress": 2, "Count": 5})
        self.db.commit()
        for t, focus in ((50, 9), (51, 0), (60, 0)):
            self.j.status_json = live(focus)
            self.state.watch_fss(1000 + t)
        self.assertEqual(len(self.moments("fss_unfinished")), 1)
        # not live (the game at the menu): no edge
        self.j.status_json = dict(live(9), live=False)
        self.state.watch_fss(2000)
        self.assertIsNone(self.state._fss_closed)

    def sampling_body(self):
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", Landable=True, SurfaceGravity=2.6 * 9.80665, WasFootfalled=False,
                    AtmosphereType="CarbonDioxide", SurfaceTemperature=180, PlanetClass="Rocky body", MassEM=0.2)
        self.j.handle({"event": "SAASignalsFound", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyName": "S1 A 4",
                       "BodyID": 4, "Signals": [{"Type": ed_outrider.BIO, "Count": 2}],
                       "Genuses": [{"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"},
                                   {"Genus": "$Codex_Ent_Bacterial_Genus_Name;", "Genus_Localised": "Bacterium"}]})

    def organic(self, ts, kind, species="Stratum Tectonicas", genus="Stratum"):
        self.j.handle({"event": "ScanOrganic", "timestamp": ts, "ScanType": kind, "SystemAddress": 1, "Body": 4,
                       "Genus": f"$Codex_Ent_{genus}_Genus_Name;", "Genus_Localised": genus,
                       "Species": f"$Codex_Ent_{species.replace(' ', '_')}_Name;", "Species_Localised": species})

    def test_left_body_and_species_complete(self):   # P4: LeaveBody (not Liftoff); untouched genera only once you landed
        self.sampling_body()
        self.j.handle({"event": "Liftoff", "timestamp": "2026-01-01T00:02:30Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        self.j.handle({"event": "LeaveBody", "timestamp": "2026-01-01T00:03:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        first = self.moments("left_body")
        self.assertEqual(len(first), 1)                                  # Liftoff says nothing
        self.assertEqual((first[0]["body"], first[0]["touched"], first[0]["partial"]), ("A 4", False, {}))
        self.assertEqual(sorted(u["genus"] for u in first[0]["untouched"]), ["Bacterium", "Stratum"])
        self.organic("2026-01-01T00:04:00Z", "Log")
        self.organic("2026-01-01T00:05:00Z", "Sample")
        self.j.handle({"event": "LeaveBody", "timestamp": "2026-01-01T00:06:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        second = self.moments("left_body")[-1]
        self.assertEqual((second["touched"], second["partial"], second["factor"]), (True, {"Stratum": 2}, 5))
        self.assertEqual([u["genus"] for u in second["untouched"]], ["Bacterium"])
        self.organic("2026-01-01T00:07:00Z", "Analyse")
        done = self.moments("bio_done")
        self.assertEqual(len(done), 1)
        self.assertEqual((done[0]["species"], done[0]["body"], done[0]["partial"]), ("Stratum Tectonicas", "A 4", {}))
        self.assertEqual([u["genus"] for u in done[0]["untouched"]], ["Bacterium"])
        self.assertEqual(done[0]["value"], ed_bio.species_value("Stratum Tectonicas") * 5)   # first footfall x5
        self.j.handle({"event": "Touchdown", "timestamp": "2026-01-01T00:08:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4,
                       "PlayerControlled": True, "OnPlanet": True})
        self.assertIn((1, 4), self.j.body_touched)

    def test_approach_once_per_body_per_session(self):   # P13: ApproachBody only, once per body until the next login
        self.sampling_body()
        for ts in ("2026-01-01T00:03:00Z", "2026-01-01T00:04:00Z"):
            self.j.handle({"event": "ApproachBody", "timestamp": ts, "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        got = self.moments("approach")
        self.assertEqual(len(got), 1)
        a = got[0]
        self.assertEqual((a["body"], a["gravity"], a["landable"], a["signals"], a["factor"]), ("A 4", 2.6, True, 2, 5))
        self.assertEqual(a["genera"], ["Bacterium", "Stratum"])
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T01:00:00Z", "Commander": "X"})
        self.j.handle({"event": "ApproachBody", "timestamp": "2026-01-01T01:05:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        self.assertEqual(len(self.moments("approach")), 2)

    def test_scoop_watch(self):   # P8: debounced end of a scoop; a jump cutting it short says nothing
        W = ed_outrider.ScoopWatch
        S = ed_outrider.FLAG_SCOOPING

        def run(steps, cap=32.0, jump_ts=None):
            w, out = W(), []
            for t, flags, fuel in steps:
                r = w.update({"live": True, "flags": flags, "fuel_main": fuel}, cap, 1000 + t, jump_ts)
                if r:
                    out.append((t, r))
            return out
        scoop = [(t, S, 10 + t) for t in range(0, 20)]
        self.assertEqual(run(scoop + [(20, 0, 32), (21, 0, 32), (23, 0, 32)]), [(23, {"pct": 100, "full": True})])
        self.assertEqual(run(scoop + [(20, 0, 20), (23, 0, 20)]), [(23, {"pct": 62, "full": False})])   # stopped early
        flicker = scoop[:10] + [(10, 0, 20), (11, S, 21)] + scoop[12:] + [(20, 0, 32), (23, 0, 32)]
        self.assertEqual(len(run(flicker)), 1)                                       # the edge of the zone: one scoop
        self.assertEqual(run([(0, S, 10), (3, S, 11), (4, 0, 11), (8, 0, 11)]), [])  # skimmed for 4 s: nothing
        charging = scoop + [(20, ed_outrider.FLAG_FSD_CHARGING, 20), (23, 0, 20)]
        self.assertEqual(run(charging), [])                                          # left early on purpose
        self.assertEqual(run(scoop + [(20, 0, 20), (23, 0, 20)], jump_ts=ed_outrider.iso_ts(1019)), [])
        self.assertEqual(len(run(scoop + [(20, ed_outrider.FLAG_FSD_CHARGING, 32), (23, 0, 32)])), 1)   # full is still full
        self.assertEqual(run(scoop + [(20, 0, 32), (23, 0, 32)], cap=None), [])      # capacity unknown: silent
        # through the state: a moment with the jumps a full tank gives
        self.j.ship = {"fuel_main": 32.0}
        for t, flags, fuel in scoop + [(20, 0, 32), (23, 0, 32)]:
            self.j.status_json = {"live": True, "flags": flags, "fuel_main": fuel, "ts": "2026-01-01T00:05:00Z"}
            self.state.watch_status(1000 + t)
        got = self.moments("scoop_end")
        self.assertEqual([(m["full"], m["pct"]) for m in got], [(True, 100)])

    def test_supercharged(self):   # P8: JetConeBoost
        self.j.handle({"event": "JetConeBoost", "timestamp": "2026-01-01T00:01:00Z", "BoostValue": 1.5})
        self.assertEqual([m["mult"] for m in self.moments("supercharged")], [1.5])

    def test_arrival_brief_from_the_honk(self):   # P7: once per arrival, with the facts known at the time
        self.j.handle({"event": "StartJump", "timestamp": "2026-01-01T00:09:50Z", "JumpType": "Hyperspace", "StarSystem": "S5",
                       "SystemAddress": 5, "StarClass": "K"})
        self.jump("2026-01-01T00:10:00Z", 5, 30)
        self.j.handle(scan("2026-01-01T00:10:02Z", "S5", 5, 0, "S5", disc=False, star=True)[2])
        self.planet("2026-01-01T00:10:03Z", 5, 3, "A 3", PlanetClass="Earthlike body", MassEM=1.0)
        self.planet("2026-01-01T00:10:03Z", 5, 4, "A 4", PlanetClass="Water world", MassEM=0.5)
        self.j.handle({"event": "SAAScanComplete", "timestamp": "2026-01-01T00:10:04Z", "SystemAddress": 5, "BodyName": "S5 A 4", "BodyID": 4})
        self.honk("2026-01-01T00:10:05Z", 5, 14)
        self.honk("2026-01-01T00:11:05Z", 5, 14)                         # a second honk: no second briefing
        got = self.moments("arrival_brief")
        self.assertEqual(len(got), 1)
        b = got[0]
        self.assertEqual((b["source"], b["undiscovered"], b["body_count"], b["star_class"], b["system_name"]), ("honk", True, 14, "K", "S5"))
        self.assertEqual([w["body"] for w in b["worth"]], ["A 3"])        # the mapped water world is left out
        self.assertEqual(b["worth"][0]["notable"], "ELW")
        # a honk in a system you are not in (read late) gives none
        self.honk("2026-01-01T00:12:00Z", 6, 3)
        self.assertEqual(len(self.moments("arrival_brief")), 1)

    def test_arrival_brief_fallback(self):   # P7: 12 s after a live arrival with no honk; not for old journals or mid-honk
        now = time.time()
        self.jump(ed_outrider.iso_ts(now - 5), 7, 40)
        self.state.maybe_brief(now)
        self.assertEqual(self.moments("arrival_brief"), [])               # too soon
        self.state._honk_running = self.j.jump_arrival
        self.state.maybe_brief(now + 10)
        self.assertEqual(self.moments("arrival_brief"), [])               # the auto honk is working on it
        self.state._honk_running = None
        self.state.maybe_brief(now + 10)
        self.state.maybe_brief(now + 11)
        got = self.moments("arrival_brief")
        self.assertEqual([(m["source"], m["system"]) for m in got], [("spansh", "7")])
        self.honk(ed_outrider.iso_ts(now + 20), 7, 5)                    # a honk later on the same visit adds none
        self.assertEqual(len(self.moments("arrival_brief")), 1)
        self.jump(ed_outrider.iso_ts(now - 600), 8, 50)                  # a journal being caught up on
        self.state.maybe_brief(now)
        self.assertEqual(len(self.moments("arrival_brief")), 1)

    def test_session_recap(self):   # P19: game_exit carries the session's numbers over login..quit
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T01:00:00Z", "Commander": "X"})
        for i in range(4):
            self.jump(f"2026-01-01T01:0{i + 1}:00Z", 10 + i, 10 * (i + 1))
        self.j.handle(scan("2026-01-01T01:04:05Z", "S13", 13, 0, "S13", disc=False, star=True)[2])
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T01:30:00Z"})
        s = self.moments("game_exit")[0]["session"]
        self.assertEqual((s["jumps"], s["ly"], s["firsts"]), (4, 40.0, 1))   # F5: the first jump starts where you logged in
        self.j.commander = None
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T02:00:00Z"})
        self.assertIsNone(self.moments("game_exit")[-1]["session"])

    def test_high_gravity_setting(self):
        import tomllib
        args = argparse.Namespace(**{k: None for k in ("journals", "legacy", "host", "port", "radius", "db", "config")})
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertEqual(st["high_gravity"], 2.0)
        st = ed_outrider.settings_from({"defaults": {"high_gravity": 2.5}}, args, None, ([], []))
        self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["defaults"]["high_gravity"], 2.5)

    def test_style_voice(self):   # P10(b): a personality may name its own Piper voice and pace
        doc = {"styles": {"business": "Business", "sarcastic": {"label": "Sarcastic", "voice": "en_US-ryan-high", "speed": 1.1},
                          "sweet": {"label": "Sweet", "voice": "../../etc/passwd", "speed": 9}}, "lines": {}}
        probs = " ".join(ed_speech.check(doc))
        self.assertIn('"sweet": "voice"', probs)
        self.assertIn('"sweet": "speed"', probs)
        self.assertNotIn("sarcastic", probs)
        self.assertEqual(ed_speech.style_voice(doc["styles"], "sarcastic_profane"), ("en_US-ryan-high", 1.1))
        self.assertEqual(ed_speech.style_voice(doc["styles"], "business"), (None, None))
        self.assertEqual(ed_speech.style_voice(doc["styles"], "sweet"), (None, None))   # never a path

    def test_voice_pool(self):   # P10(b): installed personality voices load on first use, at most EXTRA_VOICES kept
        import io, tempfile, contextlib, wave as _wave
        import ed_tts
        loads = []

        class FakeVoice:
            def __init__(self, name):
                self.name = name

            def synthesize_wav(self, text, wf, syn_config=None):
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(8000)
                wf.writeframes(self.name.encode())
        with tempfile.TemporaryDirectory() as d:
            for v in ("en_GB-main-low", "en_US-a-low", "en_US-b-low", "en_US-c-low"):
                for ext in (".onnx", ".onnx.json"):
                    open(os.path.join(d, v + ext), "w").close()
            sp = ed_tts.Speaker("en_GB-main-low", None, voices_dir=d)
            sp.PiperVoice = unittest.mock.Mock()
            sp.PiperVoice.load = lambda path: loads.append(os.path.basename(path)) or FakeVoice(os.path.basename(path))
            with contextlib.redirect_stdout(io.StringIO()):
                sp._prepare(None)
            said = lambda text, voice=None: _wave.open(io.BytesIO(sp.say(text, 1.0, voice))).readframes(99).decode()
            self.assertEqual(said("hi"), "en_GB-main-low.onnx")
            self.assertEqual(said("hi", "en_US-a-low"), "en_US-a-low.onnx")   # same words, its own voice (and cache entry)
            self.assertEqual(said("hi", "en_US-zz-low"), "en_GB-main-low.onnx")   # not installed: the main voice, no download
            said("x", "en_US-b-low"); said("x", "en_US-c-low")
            self.assertEqual(list(sp._extra), ["en_US-b-low", "en_US-c-low"])   # the least recently used went
            said("y", "en_US-c-low")
            self.assertEqual(loads.count("en_US-c-low.onnx"), 1)             # loaded once

    def test_say_voice_only_if_installed(self):   # P10(b): /api/say?voice= never names a voice to download
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer
        got = []

        class FakeSpeaker:
            ready = available = True

            def installed(self):
                return ["en_US-ryan-high"]

            def say(self, text, speed, voice=None):
                got.append(voice)
                return b"RIFF"
        self.state.speaker = FakeSpeaker()

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                for v in ("en_US-ryan-high", "en_US-nope-high", ""):
                    self.assertEqual((await c.get("/api/say", params={"text": "hi", "voice": v})).status, 200)
        asyncio.run(go())
        self.assertEqual(got, ["en_US-ryan-high", None, None])


class Batch7Data(unittest.TestCase):
    """Batch 7: rolling backups with the journal archive, exobiology in ship losses, the discovery streak's fixed
    verdicts, the Last session card and the browser defaults saved on the server. Files only in temp folders."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.addCleanup(self.db.close)

    def jump(self, ts, id64, x, kind="FSDJump"):
        self.j.handle({"event": kind, "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def star(self, ts, id64, disc):
        self.j.handle(scan(ts, f"S{id64}", id64, 0, f"S{id64}", disc=disc, star=True)[2])

    @staticmethod
    def journal(folder, name, text):
        with open(os.path.join(folder, name), "w") as f:
            f.write(text)

    def test_journal_archive(self):   # P11: copied when missing or a different size, never deleted, via .part files
        import tempfile
        with tempfile.TemporaryDirectory() as live, tempfile.TemporaryDirectory() as out:
            dest = os.path.join(out, "journals")
            self.journal(live, "Journal.2026-09-27T100000.01.log", "a\n")
            self.journal(live, "Journal.2026-09-28T100000.01.log", "b\n")
            self.journal(live, "Status.json", "{}")                      # not a journal
            copied, newest, failed = ed_outrider.archive_journals([live], dest)
            self.assertEqual(failed, [])
            self.assertEqual(copied, 2)
            self.assertRegex(newest, r"^\d{4}-\d{2}-\d{2}$")
            self.assertEqual(sorted(os.listdir(dest)), ["Journal.2026-09-27T100000.01.log", "Journal.2026-09-28T100000.01.log"])
            self.assertEqual(ed_outrider.archive_journals([live], dest)[0], 0)   # unchanged: nothing copied
            self.journal(live, "Journal.2026-09-28T100000.01.log", "b\nc\n")     # the game appended a line
            self.assertEqual(ed_outrider.archive_journals([live], dest)[0], 1)
            with open(os.path.join(dest, "Journal.2026-09-28T100000.01.log")) as f:
                self.assertEqual(f.read(), "b\nc\n")
            os.remove(os.path.join(live, "Journal.2026-09-27T100000.01.log"))  # gone from the game folder: kept here
            ed_outrider.archive_journals([live], dest)
            self.assertIn("Journal.2026-09-27T100000.01.log", os.listdir(dest))

    def test_rotation_keeps_the_newest_and_nothing_else(self):   # P11
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            zips = [f"outrider-2026090{i}-120000.zip" for i in range(1, 10)]   # old names: the default database's
            others = ["outrider-keep-this.zip", "notes.txt", "outrider-20260901-120000.zip.part",
                      "outrider-test-20260901-120000Z.zip"]                    # G2.1: another database's zip
            for f in zips + others:
                self.journal(d, f, "x")
            os.makedirs(os.path.join(d, "journals"))
            self.assertEqual(ed_outrider.rotate_backups(d, 3, ed_outrider.DB_PATH), 3)
            self.assertEqual(sorted(os.listdir(d)), sorted(zips[-3:] + others + ["journals"]))
            self.assertEqual(ed_outrider.rotate_backups(d, 0, ed_outrider.DB_PATH), 1)   # at least one is always kept
            self.assertEqual(ed_outrider.rotate_backups(d, 1, "/x/test.sqlite"), 1)      # only its own zips count

    def test_backup_is_database_only_then_rotates(self):   # P11: zip = db (+ browser defaults), journals archived
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            live, out = os.path.join(d, "live"), os.path.join(d, "backups")
            os.makedirs(live); os.makedirs(out)
            self.journal(live, "Journal.2026-09-28T100000.01.log", '{"event":"Fileheader"}\n')
            for i in range(1, 4):
                self.journal(out, f"outrider-x-2020010{i}-000000Z.zip", "old")
            self.journal(out, "outrider-20200101-000000.zip", "another database's, from an older build")
            dbp = os.path.join(d, "x.sqlite")
            sqlite3.connect(dbp).close()
            ed_outrider.write_browser_defaults(ed_outrider.browser_defaults_path(dbp), {"version": 1, "settings": {"sound": True}})
            self.state.db_path = dbp
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 2):
                res = self.state.make_backup()
            self.assertEqual(res["kept"], 2)
            self.assertEqual(res["copied"], 1)
            with zipfile.ZipFile(res["path"]) as z:
                self.assertEqual(sorted(z.namelist()), ["browser_defaults.json", "x.sqlite"])   # no journals in the zip
            self.assertEqual(sorted(f for f in os.listdir(out) if f.endswith(".zip")),
                             sorted(["outrider-20200101-000000.zip", "outrider-x-20200103-000000Z.zip",
                                     os.path.basename(res["path"])]))
            self.assertRegex(os.path.basename(res["path"]), r"^outrider-x-\d{8}-\d{6}Z\.zip$")
            self.assertEqual(os.listdir(os.path.join(out, "journals")), ["Journal.2026-09-28T100000.01.log"])
            # a failure before the zip is written deletes nothing
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 1), \
                    unittest.mock.patch.object(zipfile.ZipFile, "write", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(OSError):
                    self.state.make_backup()
            self.assertEqual(len([f for f in os.listdir(out) if f.endswith(".zip")]), 3)

    def test_when_automatic_backups_run(self):   # P11: at start when due; on a live Shutdown only; 0 turns them off
        import asyncio
        now = time.time()
        self.assertTrue(ed_outrider.backup_due(None, 1, now))
        self.assertTrue(ed_outrider.backup_due({"error": "x"}, 1, now))               # never worked
        self.assertFalse(ed_outrider.backup_due({"ts": ed_outrider.iso_ts(now - 3600)}, 1, now))
        self.assertTrue(ed_outrider.backup_due({"ts": ed_outrider.iso_ts(now - 2 * 86400)}, 1, now))
        self.assertFalse(ed_outrider.backup_due(None, 0, now))
        started = []

        async def go(ts, every=1.0):
            self.state.start_backup = lambda auto=False: started.append(auto)
            with unittest.mock.patch.object(ed_outrider, "SHUTDOWN_BACKUP_DELAY", 0), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_EVERY_DAYS", every):
                self.j.handle({"event": "Shutdown", "timestamp": ts})
                self.state.maybe_backup_on_quit(now)
                self.state.maybe_backup_on_quit(now)   # the same Shutdown seen again: nothing more
                await asyncio.sleep(0.05)
        asyncio.run(go(ed_outrider.iso_ts(now - 3 * 86400)))    # an old journal read now
        self.assertEqual(started, [])
        asyncio.run(go(ed_outrider.iso_ts(now - 5)))            # the game just quit
        self.assertEqual(started, [True])
        asyncio.run(go(ed_outrider.iso_ts(now - 2), every=0))   # automatic backups off
        self.assertEqual(started, [True])

    def test_backup_settings(self):
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertEqual((st["backup_keep"], st["backup_every_days"]), (7, 1.0))
        st = ed_outrider.settings_from({"server": {"backup_keep": 0, "backup_every_days": 0.5}}, args, None, ([], []))
        self.assertEqual((st["backup_keep"], st["backup_every_days"]), (1, 0.5))
        back = tomllib.loads(ed_outrider.config_text(st))["server"]
        self.assertEqual((back["backup_keep"], back["backup_every_days"]), (1, 0.5))
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ed_outrider.toml.example")) as f:
            ex = f.read()
        self.assertIn("# backup_keep = 7 ", ex)
        self.assertIn("# backup_every_days = 1 ", ex)

    def test_losses_count_exobiology(self):   # P18
        run = lambda ts, system, body, sp: [self.j.handle(org(ts[:-3] + f"{i}Z", system, body, sp, k))
                                            for i, k in enumerate(("Log", "Sample", "Analyse"))]
        value = ed_bio.species_value("Bacterium Aurasus")
        self.assertTrue(value)
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        run("2026-01-01T01:00:00Z", 1, 3, "A")                       # sold before any death
        self.j.handle({"event": "SellOrganicData", "timestamp": "2026-01-01T02:00:00Z", "BioData": [{"Value": 1}]})
        run("2026-01-01T03:00:00Z", 1, 4, "B")                       # lost on foot: the ship survived
        self.j.handle({"event": "Died", "timestamp": "2026-01-01T04:00:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-01T04:00:01Z", "Option": "recover"})
        run("2026-01-01T05:00:00Z", 1, 5, "C")                       # lost with the ship
        self.star("2026-01-01T05:30:00Z", 1, disc=True)
        self.j.handle({"event": "Died", "timestamp": "2026-01-01T06:00:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-01T06:00:01Z", "Option": "rebuy"})
        self.j.handle({"event": "Died", "timestamp": "2026-01-01T07:00:00Z"})   # on foot again, nothing aboard: no row
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-01T07:00:01Z", "Option": "recover"})
        self.db.commit()
        losses = self.state.ship_losses()
        self.assertEqual([(l["ts"][11:13], l["ship"], l["bio_runs"], l["bio_value"], l["bodies"]) for l in losses],
                         [("04", False, 1, value, 0), ("06", True, 1, value, 1)])
        self.assertGreater(losses[1]["value"], 0)                    # the carto side is unchanged
        # the Samples tab calls the same runs lost, for the same money
        self.assertEqual(self.state.organics(36500)["totals"]["lost"], 2 * value)
        cols, rows = self.state.export_rows("trips")
        self.assertIn("lost_bio", cols)

    def test_streak_verdicts_are_fixed_at_the_arrival_scan(self):   # P16
        self.jump("2026-01-01T00:00:00Z", 1, 0)
        self.star("2026-01-01T00:00:05Z", 1, disc=False)             # nobody had discovered it
        self.jump("2026-01-01T00:01:00Z", 2, 10)
        self.star("2026-01-01T00:01:05Z", 2, disc=True)              # known: what did Spansh know?
        self.state.target_verdicts[2] = "explored"
        self.db.commit()
        self.state.reconcile_arrival()
        self.assertEqual(self.state.arrival["verdict"], "complete")
        self.jump("2026-01-01T00:02:00Z", 3, 20)
        self.star("2026-01-01T00:02:05Z", 3, disc=True)
        self.state.target_verdicts[3] = "partial"
        self.state.reconcile_arrival()
        self.jump("2026-01-01T00:03:00Z", 1, 0)                      # back to 1: visited, though still "undiscovered"
        self.star("2026-01-01T00:03:05Z", 1, disc=False)
        self.star("2026-01-01T00:04:00Z", 1, disc=True)              # a later scan changes nothing
        self.jump("2026-01-01T00:05:00Z", 4, 30)                     # not scanned yet
        self.db.commit()
        sk = self.state.streak()
        self.assertEqual([a["verdict"] for a in sk["arrivals"]], ["new", "complete", "partial", "visited", None])
        self.assertEqual((sk["new"], sk["total"]), (1, 5))
        self.assertEqual(sk["arrivals"][0]["firsts"], 1)
        # a journal re-read rebuilds the jumps: the journal verdicts come back the same, and what Spansh knew then
        # is kept (it cannot be asked again), so no dot changes colour
        self.db.executescript(ed_outrider.RESET_JOURNAL_DATA)
        self.j.reload()
        self.jump("2026-01-01T00:01:00Z", 2, 10)
        self.star("2026-01-01T00:01:05Z", 2, disc=True)
        self.db.commit()
        self.assertEqual([a["verdict"] for a in self.state.streak()["arrivals"]], ["complete"])

    def test_streak_runs(self):   # P16: what counts as "in a row"
        runs = ed_outrider.State.streak_runs
        self.assertEqual(runs(["new", "new", "known"]), (2, 0))
        self.assertEqual(runs(["complete", "known", "complete", "partial"]), (0, 3))   # amber ends a known run
        self.assertEqual(runs(["complete", "visited", "complete"]), (0, 1))            # so does a way back
        self.assertEqual(runs([None, "new"]), (0, 0))
        self.assertEqual(runs([]), (0, 0))
        for i in range(12):   # the arrival carries the runs, for the page's once-per-streak line
            self.jump(f"2026-01-01T01:{i:02d}:00Z", 100 + i, i)
            self.star(f"2026-01-01T01:{i:02d}:05Z", 100 + i, disc=True)
            self.state.target_verdicts[100 + i] = "explored"
            self.state.reconcile_arrival()
        self.assertEqual(self.state.arrival["streak"], {"new": 0, "known": 12})

    def test_last_session_card(self):   # P19: kept (meta) until the next login
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T01:00:00Z", "Commander": "X"})
        self.assertIsNone(self.state.last_session())                          # playing
        for i in range(3):
            self.jump(f"2026-01-01T01:0{i + 1}:00Z", 10 + i, 10 * (i + 1))
        self.star("2026-01-01T01:03:05Z", 12, disc=False)
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T02:00:00Z"})
        self.db.commit()
        ls = self.state.last_session()
        self.assertEqual((ls["jumps"], ls["firsts"], ls["start"], ls["end"]), (3, 1, "2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"))
        j2 = ed_outrider.Journals(self.db)                                    # a restart: still there
        self.assertEqual(ed_outrider.State(self.db, j2, None, 25).last_session()["jumps"], 3)
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T01:00:00Z", "Commander": "X"})
        self.assertIsNone(self.state.last_session())                          # the next login hides it
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-02T01:01:00Z"})   # a quick relog: nothing to show
        self.assertIsNone(self.state.last_session())

    def test_browser_defaults(self):   # P20: allow-list, size cap, atomic write, inlined into the page
        import asyncio, re, tempfile
        from aiohttp.test_utils import TestClient, TestServer
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "static", "page.js"), encoding="utf-8") as f:
            js = f.read()
        page_keys = re.findall(r'"(\w+)"', js[js.index("const SETTINGS_KEYS = ["):js.index("];", js.index("const SETTINGS_KEYS = ["))])
        self.assertEqual(page_keys, list(ed_outrider.BROWSER_SETTINGS))       # the page and the server share one list
        for per_device in ("view", "overview", "hereModes", "bodySecs", "search", "speakMode"):
            self.assertNotIn(per_device, ed_outrider.BROWSER_SETTINGS)
        ok, why = ed_outrider.check_browser_defaults({"version": 1, "settings": {"view": "map"}})
        self.assertIsNone(ok)
        self.assertIn("view", why)
        self.assertIsNone(ed_outrider.check_browser_defaults({"version": 2, "settings": {}})[0])
        self.assertIsNone(ed_outrider.check_browser_defaults([])[0])
        with tempfile.TemporaryDirectory() as d:
            self.state.db_path = os.path.join(d, "x.sqlite")
            path = ed_outrider.browser_defaults_path(self.state.db_path)

            async def go():
                async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                    out = [(await c.post("/api/defaults", json={"version": 1, "settings": {"view": "x"}})).status,
                           (await c.post("/api/defaults", data="x" * (ed_outrider.BROWSER_DEFAULTS_MAX + 1))).status,
                           (await c.post("/api/defaults", data="{not json")).status,
                           (await c.post("/api/defaults", json={"version": 1, "settings": {"sound": True}},
                                         headers={"Origin": "http://evil.example"})).status]
                    self.assertFalse(os.path.exists(path))
                    r = await c.post("/api/defaults", json={"version": 1, "settings": {"speechNames": "</script><b>", "sound": False}})
                    out.append(r.status)
                    page = await (await c.get("/")).text()
                    got = await (await c.get("/api/defaults")).json()
                    out.append((await c.post("/api/defaults", json={"clear": True})).status)
                    gone = await (await c.get("/api/defaults")).json()
                    return out, page, got, gone
            out, page, got, gone = asyncio.run(go())
            self.assertEqual(out, [400, 413, 400, 403, 200, 200])
            self.assertEqual(got["settings"], {"speechNames": "</script><b>", "sound": False})
            self.assertIn('window.SERVER_DEFAULTS = {"version": 1, "settings": {"speechNames": "\\u003c/script>', page)
            self.assertNotIn("</script><b>", page)
            self.assertIsNone(gone)
            self.assertEqual(os.listdir(d), [])                                   # no .part left, and cleared


class BatchAIntegrity(unittest.TestCase):
    """Review 2026-09-30 batch A: live-only data kept through a re-read, sale pages, backups, config, journal
    reading. Files only in temp folders."""

    def setUp(self):
        import tempfile, types
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def write(self, folder, name, events):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            for e in events:
                f.write(json.dumps(e, separators=(",", ":")) + "\r\n")   # the game writes CRLF
        return path

    @staticmethod
    def page(ts, total, systems):
        return {"timestamp": ts, "event": "MultiSellExplorationData", "BaseValue": total, "Bonus": 0,
                "TotalEarnings": total, "Discovered": [{"SystemName": s, "NumBodies": 1} for s in systems]}

    def jump(self, ts, id64, x=0):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64,
                       "StarPos": [x, 0, 0]})

    # ---- F1: estimates and sample positions survive a journal re-read ----
    def test_old_database_keeps_estimates_and_sample_points(self):   # F1
        path = os.path.join(self.tmp, "old.sqlite")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE sale_events (ts TEXT, kind TEXT, base INTEGER, bonus INTEGER, total INTEGER, systems INTEGER,
                                      species INTEGER, estimate INTEGER, PRIMARY KEY (ts, kind));
            CREATE TABLE sample_points (system INTEGER, body_id INTEGER, species TEXT, genus TEXT, n INTEGER,
                                        lat REAL, lon REAL, ts TEXT, PRIMARY KEY (system, body_id, species, n));
            INSERT INTO meta VALUES ('parser_version', '21');
            INSERT INTO sale_events VALUES ('2026-01-02T00:00:00Z', 'carto', 900, 0, 900, 1, 0, 1000);
            INSERT INTO sale_events VALUES ('2026-01-03T00:00:00Z', 'bio', 50, 0, 50, 0, 1, NULL);
            INSERT INTO sample_points VALUES (1, 4, '$Codex_Ent_Tussocks_01_Name;', 'g', 1, 1.0, 2.0,
                                              '2026-01-04T00:00:00Z');""")
        old.commit()
        old.close()
        db = ed_outrider.open_db(path)   # parser_version differs: the journal data is reset
        try:
            self.assertEqual(ed_outrider.meta_get(db, "parser_version"), ed_outrider.PARSER_VERSION)
            self.assertEqual(db.execute("SELECT count(*) FROM sale_events").fetchone()[0], 0)   # rebuilt by the replay
            self.assertEqual([tuple(r) for r in db.execute("SELECT * FROM sale_estimates")],
                             [("2026-01-02T00:00:00Z", "carto", 1000)])
            self.assertEqual(db.execute("SELECT lat, lon FROM sample_points").fetchall()[0][:], (1.0, 2.0))
            cols = [r["name"] for r in db.execute("PRAGMA table_info(sale_events)")]
            self.assertIn("source", cols)
            self.assertNotIn("estimate", cols)
            self.assertNotIn("sale_events_old", [r[0] for r in db.execute("SELECT name FROM sqlite_master")])
            # the replay: the sale comes back and the ledger shows its estimate again
            import types
            j = ed_outrider.Journals(db)
            state = ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
            live = os.path.join(self.tmp, "live")
            self.write(live, "Journal.2026-01-01T000000.01.log", [
                {"timestamp": "2026-01-01T00:00:00Z", "event": "FSDJump", "StarSystem": "S1", "SystemAddress": 1,
                 "StarPos": [0, 0, 0]},
                self.page("2026-01-02T00:00:00Z", 900, ["S1"])])
            j.scan_dir(live)
            db.commit()
            trip = state.ledger()["trips"][0]
            self.assertEqual((trip["paid_carto"], trip["estimate"]), (900, 1000))
            db.close()
            db = ed_outrider.open_db(path, rescan=True)   # --rescan: the same again
            self.assertEqual(db.execute("SELECT count(*) FROM sale_estimates").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM sample_points").fetchone()[0], 1)
        finally:
            db.close()

    def test_replayed_log_keeps_the_current_runs_points(self):   # F1: the Log that began the run is read again
        self.jump("2026-01-01T00:00:00Z", 1)
        self.j.status_json = {"live": True, "ts": "2026-01-01T00:10:00Z", "lat": 0.0, "lon": 0.0}
        org = lambda ts, kind: {"event": "ScanOrganic", "timestamp": ts, "SystemAddress": 1, "Body": 4, "ScanType": kind,
                                "Genus": "$Codex_Ent_Tussocks_Genus_Name;", "Genus_Localised": "Tussock",
                                "Species": "$Codex_Ent_Tussocks_01_Name;", "Species_Localised": "Tussock Pennata"}
        self.j.handle(org("2026-01-01T00:10:00Z", "Log"))
        self.j.status_json = {"live": True, "ts": "2026-01-01T00:12:00Z", "lat": 0.0, "lon": 0.02}
        self.j.handle(org("2026-01-01T00:12:00Z", "Sample"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM sample_points").fetchone()[0], 2)
        self.j.status_json = {"live": True, "ts": "2026-01-02T00:00:00Z", "lat": 5.0, "lon": 5.0}   # a day later
        self.j.handle(org("2026-01-01T00:10:00Z", "Log"))       # the re-read replays the run's Log...
        self.j.handle(org("2026-01-01T00:12:00Z", "Sample"))
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT n, lat, lon FROM sample_points ORDER BY n")],
                         [(1, 0.0, 0.0), (2, 0.0, 0.02)])          # ...and the positions stay
        self.j.handle(org("2026-01-01T00:13:00Z", "Log"))       # a new run of it: the old points go
        self.assertEqual(self.db.execute("SELECT count(*) FROM sample_points").fetchone()[0], 0)

    # ---- F13: every page of a 'Sell all' counts, once ----
    def test_same_second_sale_pages_all_count_once(self):   # F13
        live = os.path.join(self.tmp, "live")
        path = self.write(live, "Journal.2026-01-01T000000.01.log", [
            {"timestamp": "2026-01-01T00:00:00Z", "event": "FSDJump", "StarSystem": "S1", "SystemAddress": 1,
             "StarPos": [0, 0, 0]},
            self.page("2026-01-02T10:00:00Z", 40_000_000, ["S1"]),
            self.page("2026-01-02T10:00:00Z", 38_000_000, ["S2"]),
            self.page("2026-01-02T10:00:00Z", 35_000_000, ["S3"])])
        self.j.scan_dir(live)
        self.db.commit()
        L = self.state.ledger()
        self.assertEqual(L["trips"][0]["paid_carto"], 113_000_000)
        # the same lines handled again (a twin folder, a retried tick): the same keys, nothing doubles
        self.j.offsets.clear()
        self.j.twins.clear()
        self.j.read_file(path)
        self.db.commit()
        self.assertEqual(self.db.execute("SELECT count(*) FROM sale_events").fetchone()[0], 3)
        self.assertEqual(self.state.ledger()["trips"][0]["paid_carto"], 113_000_000)
        # a copy of the file in another folder is the same journal: the same keys again
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        import shutil
        shutil.copy(path, other)
        self.j.offsets.clear()
        self.j.twins.clear()
        self.j.scan_dir(other)
        self.assertEqual(self.db.execute("SELECT count(*) FROM sale_events").fetchone()[0], 3)

    def test_estimate_recorded_for_a_live_sale(self):   # F1: written to sale_estimates, one per sale moment
        now = ed_outrider.iso_ts(time.time() - 60)
        live = os.path.join(self.tmp, "live")
        self.write(live, "Journal.2026-01-01T000000.01.log", [self.page(now, 10, ["A"]), self.page(now, 20, ["B"])])
        self.j.scan_dir(live)
        self.state.unsold_log = [(ed_outrider.iso_ts(time.time() - 120), {"carto": {"estimated_payout": 31}, "bio": {"estimated_value": 0}})]
        self.state.note_sale_estimates()
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT kind, estimate FROM sale_estimates")], [("carto", 31)])
        self.assertEqual(self.state.ledger()["trips"][0]["estimate"], 31)

    # ---- F15 / F49 / F16: sold or already-lost data is not lost again ----
    def star_and_record(self, ts, id64):
        self.j.handle(scan(ts, f"S{id64}", id64, 0, f"S{id64}", star=True)[2])

    def test_sold_then_rescanned_is_not_lost(self):   # F15, F16
        self.jump("2026-01-01T00:00:00Z", 1)
        self.star_and_record("2026-01-01T00:01:00Z", 1)
        self.j.handle(self.page("2026-01-02T00:00:00Z", 100, ["S1"]))
        self.jump("2026-01-03T00:00:00Z", 1)                   # a return visit: the arrival scan again
        self.star_and_record("2026-01-03T00:01:00Z", 1)
        self.j.handle({"event": "Died", "timestamp": "2026-01-04T00:00:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-04T00:00:00Z", "Option": "rebuy"})
        self.db.commit()
        loss = self.state.ship_losses()[0]
        self.assertEqual((loss["bodies"], loss["value"], loss["firsts"]), (0, 0, 0))
        self.assertEqual(self.state.top_finds()[0]["state"], "sold")

    def test_map_lost_at_an_earlier_loss_is_not_lost_again(self):   # F49
        self.jump("2026-01-01T00:00:00Z", 1)
        self.star_and_record("2026-01-01T00:01:00Z", 1)
        self.j.handle(scan("2026-01-01T00:02:00Z", "S1", 1, 1, "S1 1")[2])
        self.j.handle({"event": "SAAScanComplete", "timestamp": "2026-01-01T00:03:00Z", "SystemAddress": 1, "BodyID": 1,
                       "BodyName": "S1 1"})
        for ts in ("2026-01-02T00:00:00Z", "2026-01-04T00:00:00Z"):
            self.j.handle({"event": "Died", "timestamp": ts})
            self.j.handle({"event": "Resurrect", "timestamp": ts, "Option": "rebuy"})
            if ts.startswith("2026-01-02"):
                self.j.handle(scan("2026-01-03T00:00:00Z", "S1", 1, 1, "S1 1")[2])   # rescanned, not mapped again
        self.db.commit()
        rec = json.loads(self.db.execute("SELECT record FROM own_bodies WHERE body_id = 1").fetchone()[0])
        body = dict(rec["ed"], first_discovered=True, first_mapped=True)
        second = self.state.ship_losses()[1]
        self.assertEqual(second["bodies"], 1)
        self.assertEqual(second["value"], ed_unsold.body_value(body, False, False, True))   # not as mapped

    # ---- F46 / F19 / F50: sessions ----
    def test_rescan_of_own_unsold_discovery_is_not_a_new_first(self):   # F46
        self.jump("2026-01-01T00:00:00Z", 1)
        self.star_and_record("2026-01-01T00:01:00Z", 1)
        self.jump("2026-01-05T00:00:00Z", 1)
        self.star_and_record("2026-01-05T00:01:00Z", 1)             # still reads as undiscovered: not sold yet
        self.assertEqual(self.state.range_counts("2026-01-05T00:00:00Z", "~")["firsts"], 0)
        self.assertEqual(self.state.range_counts("", "2026-01-02T00:00:00Z")["firsts"], 1)

    def test_session_window_starts_at_login(self):   # F19
        self.jump("2026-01-01T00:00:00Z", 1)
        self.jump("2026-01-01T01:00:00Z", 2, 10)
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T00:00:00Z", "Commander": "J", "Credits": 1})
        self.j.handle({"event": "SAAScanComplete", "timestamp": "2026-01-02T00:10:00Z", "SystemAddress": 2, "BodyID": 3,
                       "BodyName": "S2 3"})                         # mapped after logging in, before the first jump
        self.jump("2026-01-02T01:00:00Z", 3, 20)
        rows = self.state.history(3650 * 3)["sessions"]
        self.assertEqual([(s["start"], s["from"], s["mapped"]) for s in rows],
                         [("2026-01-02T01:00:00Z", "2026-01-02T00:00:00Z", 1),
                          ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 0)])

    def test_session_gaps_in_utc(self):   # F50: 1.5 h across the UK clocks going back is one session
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/London"
        time.tzset()
        try:
            self.jump("2026-10-25T00:15:00Z", 1)
            self.jump("2026-10-25T01:45:00Z", 2, 10)
            self.assertEqual(len(self.state.sessions("")), 1)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    # ---- backups: G2.1 / G2.2 / G2.3 / G2.4 / F53 ----
    def test_backup_names_and_rotation(self):   # G2.1, G2.3
        self.assertRegex(ed_outrider.backup_name("/a/ed_outrider.sqlite", 0), r"^outrider-ed_outrider-19700101-000000Z\.zip$")
        d = os.path.join(self.tmp, "b")
        os.makedirs(d)
        for f in ("outrider-x-20260101-000000Z.zip", "outrider-x-20260102-000000Z.zip", "outrider-x-20250101-000000Z.zip"):
            open(os.path.join(d, f), "w").close()
        # the zip just written sorts first (a clock set back): it is kept all the same
        self.assertEqual(ed_outrider.rotate_backups(d, 1, "/q/x.sqlite", current=os.path.join(d, "outrider-x-20250101-000000Z.zip")), 1)
        self.assertEqual(os.listdir(d), ["outrider-x-20250101-000000Z.zip"])

    def test_archive_failure_is_reported_and_rotation_still_runs(self):   # G2.2
        import shutil
        live, dest = os.path.join(self.tmp, "live"), os.path.join(self.tmp, "arch")
        self.write(live, "Journal.2026-01-01T000000.01.log", [{"event": "Fileheader"}])
        self.write(live, "Journal.2026-01-02T000000.01.log", [{"event": "Fileheader"}])
        real = shutil.copy2

        def copy2(src, dst):
            if "01-01" in src:
                with open(dst, "w") as f:
                    f.write("half")                      # a .part left by the failure
                raise OSError(28, "No space left on device")
            return real(src, dst)
        with unittest.mock.patch.object(shutil, "copy2", copy2):
            copied, _, failed = ed_outrider.archive_journals([live], dest)
        self.assertEqual((copied, [f for f, _ in failed]), (1, ["Journal.2026-01-01T000000.01.log"]))
        self.assertEqual(os.listdir(dest), ["Journal.2026-01-02T000000.01.log"])      # no .part left behind
        # make_backup: the zip is good, so the rotation runs and the failure is reported, not raised
        out = os.path.join(self.tmp, "backups")
        os.makedirs(out)
        dbp = os.path.join(self.tmp, "x.sqlite")
        sqlite3.connect(dbp).close()
        for i in range(1, 4):
            open(os.path.join(out, f"outrider-x-2020010{i}-000000Z.zip"), "w").close()
        self.state.db_path = dbp
        with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]), \
                unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 2), \
                unittest.mock.patch.object(shutil, "copy2", copy2):
            res = self.state.make_backup()
        # a warning, not an error: the zip was written, so it is the latest backup (amber on the page, not red)
        self.assertIn("not archived", res["warning"])
        self.assertNotIn("error", res)
        self.assertEqual(res["kept"], 2)
        self.assertEqual(len([f for f in os.listdir(out) if f.endswith(".zip")]), 2)

    def test_backup_records_warning_apart_from_error(self):   # the Data tile: amber for a warning, red for an error
        import asyncio, contextlib, io
        results = [{"path": "/b/1.zip", "size": 1, "kept": 1, "journals_to": None, "copied": 0,
                    "warning": "1 journal not archived (J.log: disk full)"},
                   {"path": "/b/2.zip", "size": 1, "kept": 2, "journals_to": None, "copied": 1}]
        with unittest.mock.patch.object(self.state, "make_backup", side_effect=results + [OSError("disk full")]), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            asyncio.run(self.state.backup())
            first = ed_outrider.meta_get(self.state.db, "last_backup")
            asyncio.run(self.state.backup())
            second = ed_outrider.meta_get(self.state.db, "last_backup")
            asyncio.run(self.state.backup())
            third = ed_outrider.meta_get(self.state.db, "last_backup")
        self.assertEqual((first["path"], "error" in first), ("/b/1.zip", False))
        self.assertIn("not archived", first["warning"])
        self.assertNotIn("warning", second)                     # the next good backup clears it
        self.assertEqual((third["path"], third["ts"]), (second["path"], second["ts"]))   # a failure keeps the last good one
        self.assertIn("disk full", third["error"])

    def test_archive_never_replaces_with_a_smaller_or_different_file(self):   # G2.1
        live, dest = os.path.join(self.tmp, "live"), os.path.join(self.tmp, "arch")
        os.makedirs(dest)
        self.write(live, "Journal.2026-01-01T000000.01.log", [{"event": "Fileheader", "part": 1}])
        self.write(live, "Journal.2026-01-02T000000.01.log", [{"event": "Fileheader", "who": "me"}, {"event": "More"}])
        self.write(dest, "Journal.2026-01-01T000000.01.log", [{"event": "Fileheader", "part": 1}, {"event": "Longer"}])
        self.write(dest, "Journal.2026-01-02T000000.01.log", [{"event": "Fileheader", "who": "someone else"}])
        self.assertEqual(ed_outrider.archive_journals([live], dest)[0], 0)
        with open(os.path.join(dest, "Journal.2026-01-02T000000.01.log")) as f:
            self.assertIn("someone else", f.read())

    def test_stale_browser_default_key_is_dropped_not_the_document(self):   # G2.4
        import contextlib, io
        path = os.path.join(self.tmp, "browser_defaults.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "settings": {"sound": False, "someRetiredKey": 1}, "saved": "2026-01-01T00:00:00Z"}, f)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            doc = ed_outrider.read_browser_defaults(path)
        self.assertEqual(doc["settings"], {"sound": False})
        self.assertIn("someRetiredKey", err.getvalue())
        self.assertEqual(ed_outrider.check_browser_defaults({"version": 1, "settings": {"someRetiredKey": 1}})[0], None)

    def test_browser_defaults_saved_must_be_a_string(self):   # F64
        path = os.path.join(self.tmp, "browser_defaults.json")
        for saved, want in ((1727700000, None), (True, None), ({"a": 1}, None), ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z")):
            with open(path, "w") as f:
                json.dump({"version": 1, "settings": {"sound": False}, "saved": saved}, f)
            doc = ed_outrider.read_browser_defaults(path)
            self.assertEqual((doc["settings"], doc["saved"]), ({"sound": False}, want))

    def test_shutdown_waits_for_a_running_backup(self):   # F53
        import asyncio, contextlib, io
        done = []

        async def go(delay, wait):
            async def backup():
                await asyncio.sleep(delay)
                done.append(delay)
            self.state.backup_task = asyncio.create_task(backup())
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                await ed_outrider.finish_backup(self.state, wait)
            return self.state.backup_task.cancelled()
        self.assertFalse(asyncio.run(go(0.05, 5)))
        self.assertEqual(done, [0.05])
        self.assertTrue(asyncio.run(go(5, 0.05)))          # past the wait: cancelled, not left to a closed database
        self.assertEqual(done, [0.05])

    # ---- config: F42 / F40 ----
    def test_config_section_that_is_not_a_table(self):   # F42
        import contextlib, io
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            st = ed_outrider.settings_from({"journals": ["D:/Saved Games"], "server": 5, "defaults": "x",
                                            "spansh": [], "autohonk": True}, args, None, (["/det"], []))
        self.assertEqual((st["live"], st["port"]), (["/det"], 8025))
        self.assertIn("journals = ", err.getvalue())

    def test_write_config_comments_legacy_out_with_live(self):   # F40
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], ["/mnt/win/Saved Games"]))
        self.assertEqual(st["live"], [])
        back = tomllib.loads(ed_outrider.config_text(st))["journals"]
        self.assertEqual(back, {})                          # both left to auto-detection

    # ---- journal reading: F12 / F11 / F14 / F6 / F17 ----
    def test_journal_folder_with_brackets(self):   # F12
        d = os.path.join(self.tmp, "Games [SSD]")
        self.write(d, "Journal.2026-01-01T000000.01.log", [
            {"timestamp": "2026-01-01T00:00:00Z", "event": "FSDJump", "StarSystem": "S1", "SystemAddress": 1, "StarPos": [0, 0, 0]}])
        self.assertEqual(self.j.scan_dir(d), 1)
        self.assertEqual(self.j.pos["id64"], 1)
        self.assertEqual(len(ed_log.journal_files([d])), 1)
        self.assertEqual(len(ed_unsold.journal_files([d])), 1)

    def test_one_file_two_paths_read_once(self):   # F11
        a = os.path.join(self.tmp, "a")
        path = self.write(a, "Journal.2026-01-01T000000.01.log", [{"event": "Fileheader"}])
        b = os.path.join(self.tmp, "b")
        os.symlink(a, b)
        self.assertEqual(ed_outrider.unique_dirs([a, b, a + "/"]), [a])
        other = os.path.join(b, os.path.basename(path))
        self.j.offsets = {path: 100, other: 50}
        self.j.twins = {os.path.basename(path): path}
        self.assertEqual(self.j.start_offset(other), 100)   # its own offset lags the twin's: the further one

    def test_stale_navroute_and_status_in_a_second_folder(self):   # F14
        new, old = os.path.join(self.tmp, "new"), os.path.join(self.tmp, "old")
        hop = lambda i: {"StarSystem": f"S{i}", "SystemAddress": i, "StarPos": [i, 0, 0], "StarClass": "K"}
        for d, ts, n in ((new, "2026-09-01T00:00:00Z", 3), (old, "2026-01-01T00:00:00Z", 5)):
            os.makedirs(d)
            with open(os.path.join(d, "NavRoute.json"), "w") as f:
                json.dump({"timestamp": ts, "event": "NavRoute", "Route": [hop(i) for i in range(1, n + 1)]}, f)
            with open(os.path.join(d, "Status.json"), "w") as f:
                json.dump({"timestamp": ts, "event": "Status", "Flags": 1, "Fuel": {"FuelMain": n}}, f)
        for d in (new, old):
            self.j.read_navroute(d)
            self.j.read_status(d)
        self.assertEqual(len(ed_outrider.meta_get(self.db, "route")["hops"]), 3)
        self.assertEqual(self.j.status_json["fuel_main"], 3)
        self.j.handle({"event": "NavRouteClear", "timestamp": "2026-09-02T00:00:00Z"})
        self.j.read_navroute(new)                         # the file from before the clear: stays cleared
        self.assertIsNone(ed_outrider.meta_get(self.db, "route"))

    def test_failed_tick_reads_the_route_again_and_keeps_status_moments(self):   # F6, F17
        import contextlib, io
        d = os.path.join(self.tmp, "live")
        os.makedirs(d)
        with open(os.path.join(d, "NavRoute.json"), "w") as f:
            json.dump({"timestamp": "2026-01-01T00:00:00Z", "event": "NavRoute",
                       "Route": [{"StarSystem": "S1", "SystemAddress": 1, "StarPos": [0, 0, 0], "StarClass": "K"}]}, f)
        later = ("maybe_refresh", "apply_own_changes", "maybe_classify_target", "maybe_unsold", "maybe_locate_carrier",
                 "maybe_find_sellers", "maybe_backup_on_quit")
        watched, mtimes = [], {}
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [d]))
            for name in later:
                stack.enter_context(unittest.mock.patch.object(self.state, name, lambda: None))
            stack.enter_context(unittest.mock.patch.object(self.state, "watch_status", lambda now: watched.append(now)))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            with unittest.mock.patch.object(self.j, "settle_carrier", side_effect=sqlite3.OperationalError("database is locked")):
                self.state.tick(mtimes)
            self.assertTrue(self.state.tail_error)
            self.assertEqual(mtimes, {})                          # F6: the route will be read again
            self.assertEqual(watched, [])                         # F17: nothing consumed before the commit failed
            self.assertIsNone(ed_outrider.meta_get(self.db, "route"))
            self.state.tick(mtimes)
        self.assertIsNone(self.state.tail_error)
        self.assertEqual(len(ed_outrider.meta_get(self.db, "route")["hops"]), 1)
        self.assertEqual(len(watched), 1)

    # ---- server: F54 / F45 ----
    def test_port_80_extras_get_the_bare_name(self):   # F54
        h = ed_outrider.allowed_hosts("127.0.0.1", 80, ["mypc", "Box.lan:80"], own=lambda: set())
        self.assertTrue({"mypc", "mypc:80", "box.lan", "box.lan:80"} <= h)
        self.assertNotIn("mypc", ed_outrider.allowed_hosts("127.0.0.1", 8025, ["mypc"], own=lambda: set()))

    def test_spansh_cache_version(self):   # F45: gravity_raw and body_count need a refetch of older entries
        self.assertGreaterEqual(ed_outrider.CACHE_VERSION, 13)


class BatchBState(unittest.TestCase):
    """Third review, batch B: server state, call-outs and the helper modules."""

    CANDS = Batch2Values.CANDS

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.jump("2026-01-01T00:00:00Z", 1, 0)

    jump, honk, planet, moments, organic = (Batch6Voice.jump, Batch6Voice.honk, Batch6Voice.planet,
                                            Batch6Voice.moments, Batch6Voice.organic)

    # ---- G3.1 / G3.2: the next stop ----
    def test_bookmark_is_located(self):   # G3.1
        self.db.execute("INSERT INTO bookmarks VALUES (99, 'Far Away', 400, 0, 0, 'note', '2026-01-01T00:00:00Z')")
        self.assertEqual(self.state.locate(99), ("Far Away", 400, 0, 0))
        self.assertTrue(self.state.set_next_stop(99))
        self.assertEqual(ed_outrider.meta_get(self.db, "next_stop")["name"], "Far Away")
        self.assertTrue(self.state.set_bookmark(99, "new note"))

    def test_rescan_keeps_a_next_stop_visited_before(self):   # G3.2
        import tempfile
        self.jump("2026-01-01T01:00:00Z", 2, 10)
        self.jump("2026-01-01T02:00:00Z", 3, 20)
        self.assertTrue(self.state.set_next_stop(2))
        self.assertEqual(ed_outrider.meta_get(self.db, "next_stop")["set_ts"], "2026-01-01T02:00:00Z")
        with tempfile.TemporaryDirectory() as d:   # a re-read replays the earlier visit to S2: it stays
            path = os.path.join(d, "t.sqlite")
            db = ed_outrider.open_db(path)
            ed_outrider.meta_set(db, "pos", {"id64": 3, "ts": "2026-01-01T02:00:00Z"})
            ed_outrider.meta_set(db, "next_stop", {"id64": 2, "name": "S2", "x": 10, "y": 0, "z": 0})   # from before set_ts
            db.commit()
            db.close()
            db = ed_outrider.open_db(path, rescan=True)
            j = ed_outrider.Journals(db)
            for ts, i in (("2026-01-01T00:00:00Z", 1), ("2026-01-01T01:00:00Z", 2), ("2026-01-01T02:00:00Z", 3)):
                j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{i}", "SystemAddress": i, "StarPos": [i, 0, 0]})
            self.assertEqual(ed_outrider.meta_get(db, "next_stop")["id64"], 2)
            j.handle({"event": "FSDJump", "timestamp": "2026-01-01T03:00:00Z", "StarSystem": "S2", "SystemAddress": 2,
                      "StarPos": [10, 0, 0]})
            self.assertIsNone(ed_outrider.meta_get(db, "next_stop"))   # arriving after it was chosen clears it
            db.close()

    # ---- G3.3 / F8: the Nearby refresh ----
    def refresh(self, sphere, bad=None):
        import asyncio, types

        async def fail(*a):
            raise OSError("Spansh down")

        async def dump(id64, updated, base):
            return base
        self.state.spansh = types.SimpleNamespace(sphere=sphere, edsm_sphere=fail, cached=lambda i: (None, None),
                                                  store=lambda *a: None, full_records=dump)
        real = self.state.row

        def row(id64):
            if id64 == bad:
                raise ValueError("bad record")
            return real(id64)
        self.state.row = row
        self.state.center = self.j.pos
        asyncio.run(self.state._refresh(self.j.pos))

    def test_failed_search_drops_the_old_sphere_cut(self):   # G3.3
        async def down(pos, r):
            raise OSError("Spansh down")
        self.state.sphere_cut = 11.8
        self.refresh(down)
        self.assertIsNone(self.state.sphere_cut)
        self.assertIn("Spansh search failed", self.state.status)

    def test_one_bad_row_does_not_stop_the_refresh(self):   # F8
        import contextlib, io
        body = lambda s: [{"name": f"{s} A 1", "type": "Planet", "subtype": "Rocky body"}]

        async def found(pos, r):
            return [{"id64": i, "name": f"N{i}", "x": i, "y": 0, "z": 0, "distance": i, "bodies": body(f"N{i}")}
                    for i in (11, 12, 13)]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.refresh(found, bad=12)
        self.assertTrue({11, 13} <= set(self.state.systems))
        self.assertNotIn(12, self.state.systems)
        self.assertIn(12, self.state.row_failed)
        self.assertIn(12, self.state.value_dirty)       # tried again at the next tick
        self.assertIn("bad record", self.state.tail_error)
        self.assertEqual(err.getvalue().count("Traceback"), 1)

    # ---- F9 / F10: fuel and boost state ----
    def test_ship_swap_counts_jumps_from_the_swap(self):   # F9
        loadout = lambda ts, sid: {"event": "Loadout", "timestamp": ts, "Ship": "anaconda", "ShipID": sid, "MaxJumpRange": 50,
                                   "FuelCapacity": {"Main": 32, "Reserve": 1}, "Modules": []}
        self.j.handle(loadout("2026-01-01T00:00:30Z", 1))
        self.jump("2026-01-01T00:01:00Z", 2, 10)
        self.j.handle(loadout("2026-01-01T00:02:00Z", 2))
        self.assertEqual(self.j.last_scoop, "2026-01-01T00:02:00Z")
        n = self.db.execute("SELECT count(*) FROM jumps WHERE kind='FSDJump' AND ts > ?", (self.j.last_scoop,)).fetchone()[0]
        self.assertEqual(n, 0)

    def test_rebuy_drops_the_jet_cone_charge(self):   # F10
        self.j.handle({"event": "JetConeBoost", "timestamp": "2026-01-01T00:01:00Z", "BoostValue": 4.0})
        self.j.handle({"event": "Died", "timestamp": "2026-01-01T00:02:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-01T00:03:00Z", "Option": "rebuy"})
        self.assertIsNone(self.j.boost)
        self.assertIsNone(ed_outrider.meta_get(self.db, "boost"))
        self.j.handle({"event": "JetConeBoost", "timestamp": "2026-01-01T00:04:00Z", "BoostValue": 4.0})
        self.j.handle({"event": "Location", "timestamp": "2026-01-01T00:05:00Z", "StarSystem": "S9", "SystemAddress": 9,
                       "StarPos": [90, 0, 0]})   # arrived without a jump: a respawn elsewhere
        self.assertIsNone(self.j.boost)

    # ---- F56: moments answer the long poll ----
    def test_new_moment_bumps(self):   # F56
        import contextlib
        later = ("maybe_refresh", "apply_own_changes", "maybe_classify_target", "maybe_unsold", "maybe_locate_carrier",
                 "maybe_find_sellers", "maybe_backup_on_quit", "watch_status")
        with contextlib.ExitStack() as stack:
            stack.enter_context(unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", ["/nonexistent-outrider-dir"]))
            for name in later:
                stack.enter_context(unittest.mock.patch.object(self.state, name, lambda *a: None))
            stack.enter_context(unittest.mock.patch.object(
                self.j, "scan_dir", lambda d: self.j.moment("supercharged", "2026-01-01T00:01:00Z", mult=4.0) and False))
            v = self.state.version
            self.state.tick({})
        self.assertGreater(self.state.version, v)

    # ---- F43 / F44 / F38 / F52: call-outs ----
    def test_login_on_foot_names_your_ship(self):   # F43
        self.j.ship = {"name": "Wanderer", "ship_id": 39}
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:05:00Z", "Commander": "X", "Ship": "ExplorationSuit_Class1",
                       "Ship_Localised": "Artemis Suit", "ShipID": 4293000001, "ShipName": ""})
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:06:00Z", "Commander": "X", "Ship": "TestBuggy",
                       "Ship_Localised": "SRV Scarab", "ShipID": 33})
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:07:00Z", "Commander": "X", "Ship": "Explorer_NX",
                       "Ship_Localised": "Caspian Explorer", "ShipID": 39, "ShipName": "Wanderer II"})
        self.assertEqual([m["ship"] for m in self.j.moments if m["kind"] == "game_start"], ["Wanderer", "Wanderer", "Wanderer II"])

    def test_relog_then_honk_gives_no_second_briefing(self):   # F44
        self.jump("2026-01-01T00:10:00Z", 5, 30)
        self.honk("2026-01-01T00:10:05Z", 5, 3)
        self.j.handle({"event": "Location", "timestamp": "2026-01-01T00:20:00Z", "StarSystem": "S5", "SystemAddress": 5,
                       "StarPos": [30, 0, 0]})
        self.assertEqual(self.j.pos["ts"], "2026-01-01T00:10:00Z")   # still the arrival
        self.honk("2026-01-01T00:20:05Z", 5, 3)
        self.assertEqual(len([m for m in self.j.moments if m["kind"] == "arrival_brief"]), 1)

    def test_all_found_after_the_briefing_is_still_said(self):   # F38
        self.jump("2026-01-01T00:10:00Z", 5, 30)
        self.honk("2026-01-01T00:10:05Z", 5, 3, progress=1.0)
        self.assertFalse(self.moments("arrival_brief")[0]["all_found"])    # the page got it before the next line
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:10:06Z", "SystemName": "S5",
                       "SystemAddress": 5, "Count": 3})
        self.assertEqual([m["system"] for m in self.moments("fss_done")], ["5"])

    def test_briefing_after_a_honk_that_gave_up_late(self):   # F52
        now = time.time()
        self.jump(ed_outrider.iso_ts(now - 70), 7, 40)
        a = self.j.jump_arrival
        self.state._honk_done = (a, now - 1)             # the honk task waited ~70 s for the cockpit, then gave up
        self.state.maybe_brief(now)
        self.assertEqual([m["source"] for m in self.moments("arrival_brief")], ["spansh"])

    # ---- F5 / F2 / F18: facts ----
    def test_arrival_bio_counts_mapped_bodies_and_skips_done_species(self):   # F5
        self.sampling_body = Batch6Voice.sampling_body.__get__(self)
        self.sampling_body()                              # A 4: DSS'd (so mapped), Stratum + Bacterium
        self.organic("2026-01-01T00:04:00Z", "Analyse", "Bacterium Aurasus", "Bacterium")
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            f = self.state.arrival_facts(1)
        self.assertEqual(f["bio"], {"body": "A 4", "value": 19_010_800})   # Stratum left, Bacterium done
        self.organic("2026-01-01T00:05:00Z", "Analyse", "Stratum Tectonicas", "Stratum")
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            self.assertIsNone(self.state.arrival_facts(1)["bio"])

    def test_codex_new_per_variant_in_the_summaries(self):   # P11
        region = ed_bio.region_name(0, 0, 0)
        if not region:
            self.skipTest("no bio_rules.json")
        Batch6Voice.sampling_body(self)
        for i, name in enumerate(("Stratum Tectonicas - Green", "Bacterium Aurasus - Teal")):
            self.db.execute("INSERT INTO codex (ts, entry_id, name, region) VALUES ('t', ?, ?, ?)", (i, name, region))
        self.db.commit()
        cands = lambda colour: [dict(self.CANDS[0], variants=[f"Stratum Tectonicas - {colour}"]), dict(self.CANDS[1], variants=[])]
        new_of = lambda: {p["body"]: p["codex_new"] for p in self.state.leaving_summary(1)["bio_pending"]}
        with unittest.mock.patch.object(ed_bio, "predict", return_value=cands("Teal")):
            self.assertEqual(new_of(), {"A 4": True})                  # Teal Stratum is new here, Green is logged
            g = {x["genus"]: x for x in next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == "A 4")["bio_guess"]}
            self.assertEqual((g["Stratum"]["variant"], g["Stratum"]["codex_new"]), ("Stratum Tectonicas - Teal", True))
            self.assertEqual((g["Bacterium"]["variants"], g["Bacterium"]["codex_new"]), ([], False))   # species logged
            # the journal logged Green on the first sample: that, not the guess, is what the codex gets
            self.j.handle({"event": "ScanOrganic", "timestamp": "2026-01-01T00:04:00Z", "ScanType": "Log", "SystemAddress": 1,
                           "Body": 4, "Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum",
                           "Species": "$Codex_Ent_Stratum_07_Name;", "Species_Localised": "Stratum Tectonicas",
                           "Variant": "$Codex_Ent_Stratum_07_M_Name;", "Variant_Localised": "Stratum Tectonicas - Green"})
            self.db.commit()
            self.assertEqual(new_of(), {"A 4": False})
        with unittest.mock.patch.object(ed_bio, "predict", return_value=cands("Green")):
            self.assertEqual(new_of(), {"A 4": False})

    def test_leaving_skips_a_finished_body_without_dss(self):   # F2
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", Landable=True, PlanetClass="Rocky body", MassEM=0.2)
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyName": "S1 A 4",
                       "BodyID": 4, "Signals": [{"Type": ed_outrider.BIO, "Count": 2}]})
        self.organic("2026-01-01T00:04:00Z", "Analyse", "Bacterium Aurasus", "Bacterium")
        self.db.commit()
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            pend = self.state.leaving_summary(1)["bio_pending"]
            self.assertEqual([(p["body"], p["signals"], p["potential"]) for p in pend], [("A 4", 1, 19_010_800)])
            self.organic("2026-01-01T00:05:00Z", "Analyse", "Stratum Tectonicas", "Stratum")
            self.assertEqual(self.state.leaving_summary(1)["bio_pending"], [])

    def test_return_visit_is_visited(self):   # F18
        self.jump("2026-01-01T01:00:00Z", 2, 10)
        self.jump("2026-01-01T02:00:00Z", 1, 0)
        rows = self.db.execute("SELECT id64, verdict FROM jumps ORDER BY ts").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(1, None), (2, None), (1, "visited")])
        self.assertGreaterEqual(ed_outrider.PARSER_VERSION, 28)

    # ---- G1.2 / F36: speech ----
    def test_long_lines_are_cut_at_a_boundary(self):   # G1.2
        import ed_tts
        line = "Leaving with unfinished work: bio on C 2 (Osseus, Tussock), up to 3.1M. " * 20
        cut = ed_tts.clip_text(line)
        self.assertLessEqual(len(cut), ed_tts.SAY_MAX)
        self.assertTrue(cut.endswith("up to 3.1M."))
        self.assertEqual(ed_tts.clip_text("short   line "), "short line")
        words = ed_tts.clip_text("word " * 400, 50)
        self.assertTrue(words.endswith("word") and len(words) <= 50)
        self.assertEqual(ed_tts.clip_text("one, two " * 10, 30)[-1], ".")

    def test_failed_switch_keeps_the_old_voice_and_is_not_saved(self):   # F36
        import contextlib, io, tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            for v in ("en_GB-a-low", "en_GB-b-low"):
                for ext in (".onnx", ".onnx.json"):
                    open(os.path.join(d, v + ext), "w").close()
            switched = []
            sp = ed_tts.Speaker("en_GB-a-low", "en_GB-b-low", voices_dir=d, on_switched=switched.append)
            sp.PiperVoice = unittest.mock.Mock()
            sp.PiperVoice.load = lambda path: (_ for _ in ()).throw(RuntimeError("damaged")) if "b-low" in path else path
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                sp._prepare(None)                         # start-up: not a choice to remember
                self.assertEqual(switched, [])
                sp._prepare("en_GB-b-low")
            self.assertEqual(sp.voice_name, "en_GB-a-low")
            self.assertTrue(sp.status.startswith("could not switch to en_GB-b-low"))
            self.assertTrue(sp.status.endswith("still using en_GB-a-low"))
            self.assertEqual(switched, [])
        self.state.remember_voice("en_GB-a-low")
        self.db.rollback()
        self.assertEqual(ed_outrider.meta_get(self.db, "voice_choice"), "en_GB-a-low")

    # ---- F20 / F67 / F68: ed_bio ----
    @unittest.skipUnless(ed_bio.available(), "bio_rules.json not downloaded")
    def test_star_rule_waits_for_every_star(self):   # F20
        body = {"class": "Rocky body", "atmosphere": "Hot thin Sulphur dioxide", "gravity": 0.3, "temperature": 420}
        system = dict(BioRules.M_SYSTEM)
        names = lambda s: [x["name"] for x in ed_bio.predict(body, s)]
        self.assertIn("Prasinum Bioluminescent Anemone", names(dict(system, complete=False)))   # a companion may be the one
        self.assertNotIn("Prasinum Bioluminescent Anemone", names(dict(system, complete=True)))

    def test_species_value_of_nothing(self):   # F67
        self.assertIsNone(ed_bio.species_value(None))

    @unittest.skipUnless(ed_bio.available(), "bio_rules.json not downloaded")
    def test_backtest_skips_a_corrupt_line(self):   # F68
        import contextlib, io, tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Journal.2026-01-01T000000.01.log"), "w") as f:
                f.write('{"timestamp":"2026-01-01T00:00:00Z","event":"Scan","BodyName":"X 1","Planet\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ed_bio.backtest([d])
        self.assertNotIn("Traceback", out.getvalue())

    # ---- F37: ed_honk ----
    def test_joystick_modifier_slot_is_skipped(self):   # F37
        import tempfile
        import ed_honk
        with tempfile.TemporaryDirectory() as root:
            journals, binds = Batch5ConfigCli.controls(self, root)
            with open(os.path.join(binds, "My X56.4.2.binds"), "w") as f:
                f.write('<?xml version="1.0" encoding="UTF-8" ?><Root PresetName="My X56"><PrimaryFire>'
                        '<Primary Device="Keyboard" Key="Key_K"><Modifier Device="231D0200" Key="Joy_3" /></Primary>'
                        '<Secondary Device="Keyboard" Key="Key_Space" /></PrimaryFire></Root>')
            self.assertEqual(ed_honk.primary_fire_binding([journals])[0], ["KEY_SPACE"])
            with open(os.path.join(binds, "My X56.4.2.binds"), "w") as f:
                f.write('<?xml version="1.0" encoding="UTF-8" ?><Root PresetName="My X56"><PrimaryFire>'
                        '<Primary Device="Keyboard" Key="Key_K"><Modifier Device="231D0200" Key="Joy_3" /></Primary>'
                        '</PrimaryFire></Root>')
            keys, what = ed_honk.primary_fire_binding([journals])
        self.assertIsNone(keys)
        self.assertIn("joystick modifier", what)



class BatchS1(unittest.TestCase):
    """Suggestions batch S1: values and decisions on screen (P1, P2, P6, P13, P17)."""

    CANDS = Batch2Values.CANDS

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.jump("2026-01-01T00:00:00Z", 1, 0)

    jump, honk, planet = Batch6Voice.jump, Batch6Voice.honk, Batch6Voice.planet

    def signals(self, ts, id64, body_id, name, n):
        self.j.handle({"event": "FSSBodySignals", "timestamp": ts, "SystemAddress": id64, "BodyName": f"S{id64} {name}",
                       "BodyID": body_id, "Signals": [{"Type": ed_outrider.BIO, "Count": n}]})

    def analysed(self, ts, id64, body_id, species, genus):
        self.j.handle({"event": "ScanOrganic", "timestamp": ts, "ScanType": "Analyse", "SystemAddress": id64, "Body": body_id,
                       "Genus": f"$Codex_Ent_{genus}_Genus_Name;", "Genus_Localised": genus,
                       "Species": f"$Codex_Ent_{species.replace(' ', '_')}_Name;", "Species_Localised": species})

    def test_leaving_carries_factor_gravity_and_atmosphere(self):   # P1, P13
        rocky = dict(Landable=True, PlanetClass="Rocky body", MassEM=0.2)
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", WasFootfalled=False, SurfaceGravity=2.6 * 9.80665,
                    AtmosphereType="CarbonDioxide", **rocky)
        self.planet("2026-01-01T00:01:10Z", 1, 5, "A 5", WasFootfalled=True, **rocky)
        self.planet("2026-01-01T00:01:20Z", 1, 6, "A 6", **rocky)                    # no WasFootfalled at all
        for bid, name in ((4, "A 4"), (5, "A 5"), (6, "A 6")):
            self.signals("2026-01-01T00:02:00Z", 1, bid, name, 1)
        self.db.commit()
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            pend = {p["body"]: p for p in self.state.leaving_summary(1)["bio_pending"]}
        self.assertEqual({b: p["factor"] for b, p in pend.items()}, {"A 4": 5, "A 5": 1, "A 6": 1})
        self.assertEqual(pend["A 4"]["potential"], 19_010_800)                      # still bonus-free
        self.assertEqual((pend["A 4"]["gravity"], pend["A 4"]["atmosphere"]), (2.6, "CarbonDioxide"))
        self.assertIsNone(pend["A 6"]["atmosphere"])

    def test_left_behind_lists_signals_never_dssd(self):   # P2
        self.jump("2026-01-01T00:01:00Z", 2, 30)
        rocky = dict(Landable=True, PlanetClass="Rocky body", MassEM=0.2)
        self.planet("2026-01-01T00:02:00Z", 2, 4, "A 4", **rocky)
        self.signals("2026-01-01T00:02:10Z", 2, 4, "A 4", 3)
        self.planet("2026-01-01T00:02:20Z", 2, 5, "A 5", **rocky)
        self.signals("2026-01-01T00:02:30Z", 2, 5, "A 5", 1)                        # its one signal is sampled
        self.analysed("2026-01-01T00:03:00Z", 2, 5, "Bacterium Aurasus", "Bacterium")
        self.planet("2026-01-01T00:03:10Z", 2, 6, "A 6", **rocky)                   # DSS'd: its genera win
        self.signals("2026-01-01T00:03:20Z", 2, 6, "A 6", 2)
        self.j.handle({"event": "SAASignalsFound", "timestamp": "2026-01-01T00:03:30Z", "SystemAddress": 2, "BodyID": 6,
                       "BodyName": "S2 A 6", "Signals": [{"Type": ed_outrider.BIO, "Count": 2}],
                       "Genuses": [{"Genus": "$Codex_Ent_Stratum_Genus_Name;", "Genus_Localised": "Stratum"}]})
        self.jump("2026-01-01T00:04:00Z", 1, 0)
        self.db.commit()
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            left = self.state.left_behind(100)["systems"]
        self.assertEqual([r["name"] for r in left], ["S2"])
        bio = {b["body"]: b for b in left[0]["bio"]}
        self.assertEqual(sorted(bio), ["A 4", "A 6"])                                # A 5: nothing left
        self.assertEqual((bio["A 4"]["genera"], bio["A 4"]["signals"]), (None, 3))
        self.assertEqual(bio["A 4"]["value"], 19_010_800 + 16_777_215 + 3_703_200)   # the three best the rules allow
        self.assertEqual(bio["A 6"]["genera"], ["Stratum"])

    def test_base_known(self):   # P6
        recs = [ed_outrider.record_from_dump("S1", {"name": f"S1 A {i}", "type": "Planet", "subType": "Icy body", "bodyId": i})
                for i in range(1, 12)] + [ed_outrider.record_from_dump("S1", {"name": "S1 A", "type": "Star", "subType": "K (Yellow-Orange) Star",
                                                                                "mainStar": True, "bodyId": 0})]
        base = {"name": "S1", "x": 0, "y": 0, "z": 0, "body_count": 12, "records": recs}
        self.assertEqual(ed_outrider.base_known(base), 12)
        self.assertEqual(ed_outrider.base_known(dict(base, records=[{"name": "S1", "type": "Star", "placeholder": True}])), 0)
        self.assertIsNone(ed_outrider.base_known(base, "own"))                       # a stand-in: knows nothing
        self.assertIsNone(ed_outrider.base_known(None))
        self.state.bases[1] = ("spansh", base)
        self.honk("2026-01-01T00:00:10Z", 1, 14)
        self.db.commit()
        f = self.state.arrival_facts(1)
        self.assertEqual((f["body_count"], f["base_known"]), (14, 12))              # 2 not on Spansh
        self.assertEqual(self.state.system_detail(1)["leaving"]["base_known"], 12)
        self.state.bases[1] = ("own", dict(base, records=[]))
        self.assertIsNone(self.state.arrival_facts(1)["base_known"])

    def test_backup_holds_speech_and_config(self):   # P17
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            dbp = os.path.join(d, "x.sqlite")
            sqlite3.connect(dbp).close()
            self.state.db_path = dbp
            self.state.speech_path, self.state.config_path = os.path.join(d, "my_lines.json"), os.path.join(d, "cfg.toml")
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", os.path.join(d, "b1")), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []):
                out = self.state.make_backup()                                      # neither file exists yet
            self.assertEqual(out["files"], ["x.sqlite"])
            self.assertNotIn("warning", out)
            with open(self.state.speech_path, "w") as f:
                f.write("{}")
            with open(self.state.config_path, "w") as f:
                f.write("radius = 25\n")
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", os.path.join(d, "b2")), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []):
                out = self.state.make_backup()
            self.assertEqual(out["files"], ["x.sqlite", "speech.json", "ed_outrider.toml"])
            with zipfile.ZipFile(out["path"]) as z:
                self.assertEqual(sorted(z.namelist()), ["ed_outrider.toml", "speech.json", "x.sqlite"])
                self.assertEqual(z.read("ed_outrider.toml"), b"radius = 25\n")
            os.chmod(self.state.speech_path, 0)
            if not os.access(self.state.speech_path, os.R_OK):                     # (root reads it anyway)
                with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", os.path.join(d, "b3")), \
                        unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []):
                    out = self.state.make_backup()                                  # unreadable: a warning, not a failure
                self.assertEqual(out["files"], ["x.sqlite", "ed_outrider.toml"])
                self.assertIn("speech.json not backed up", out["warning"])
                self.assertTrue(os.path.exists(out["path"]))
            os.chmod(self.state.speech_path, 0o600)

class PlausibleFixes(unittest.TestCase):
    """Third review: the verified plausible findings."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def test_carrier_lookup_does_not_stamp_a_moved_carrier(self):   # F51
        import asyncio, types
        self.j.handle({"event": "CarrierStats", "timestamp": "2026-09-30T10:00:00Z", "CarrierType": "FleetCarrier",
                       "CarrierID": 7, "Name": "C", "Callsign": "ABC-123"})
        self.j.handle({"event": "CarrierLocation", "timestamp": "2026-09-30T10:00:01Z", "CarrierType": "FleetCarrier",
                       "CarrierID": 7, "StarSystem": "Old", "SystemAddress": 111, "BodyID": 0})
        self.assertEqual(self.j.carrier["id64"], 111)

        async def lookup(id64, interactive=True):
            await asyncio.sleep(0.2)
            return {"system": {"coords": {"x": 1.0, "y": 2.0, "z": 3.0}}}   # the OLD system's coordinates
        self.state.spansh = types.SimpleNamespace(cached=lambda i: (None, None), lookup=lookup)

        async def race():
            self.state.maybe_locate_carrier()
            await asyncio.sleep(0.05)
            self.j.handle({"event": "CarrierLocation", "timestamp": "2026-09-30T10:00:10Z", "CarrierType": "FleetCarrier",
                           "CarrierID": 7, "StarSystem": "New", "SystemAddress": 222, "BodyID": 0})
            await self.state.carrier_task
        asyncio.run(race())
        self.assertEqual(self.j.carrier["id64"], 222)
        self.assertIsNone(self.j.carrier.get("x"))
        saved = ed_outrider.meta_get(self.db, "carrier") or {}
        self.assertIsNone(saved.get("x"))

    def test_non_object_json_body_is_a_400(self):   # F55
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer
        called = []
        self.state.set_autohonk = lambda on: called.append(on)   # never reached; auto honk is never switched on here

        async def go():
            got = []
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                for path in ("/api/nextstop", "/api/autohonk"):
                    for body in ([1], "x", 5, None):
                        r = await c.post(path, data=json.dumps(body), headers={"Content-Type": "application/json"})
                        got.append((path, body, r.status))
            return got
        for path, body, status in asyncio.run(go()):
            self.assertEqual(status, 400, (path, body))
        self.assertEqual(called, [])

    def voice_lab(self):
        try:
            import voice_lab
        except (ImportError, SystemExit):
            self.skipTest("no tkinter")
        return voice_lab

    def test_voice_lab_keeps_two_voices_loaded(self):   # F73
        import threading, types
        vl = self.voice_lab()
        loads = []
        v = vl.Voices.__new__(vl.Voices)
        v.PiperVoice = types.SimpleNamespace(load=lambda path: loads.append(os.path.basename(path)) or object())
        v.loaded, v.current, v.lock = vl.OrderedDict(), None, threading.Lock()
        for name in ("a", "b", "c", "d"):
            v.current = name
            v.load(name)
        self.assertEqual(list(v.loaded), ["c", "d"])
        v.current = "d"
        v.load("e")                      # a personality's own voice: the selected one stays loaded
        v.load("f")
        self.assertEqual(sorted(v.loaded), ["d", "f"])
        self.assertEqual(len(loads), 6)

    def test_voice_lab_uses_the_personality_pace(self):   # F70
        import types
        vl = self.voice_lab()
        text = "Carto data aboard, Commander."
        lab = types.SimpleNamespace(voice=types.SimpleNamespace(get=lambda: "en_GB-x-low"), speaker_ids=[],
                                    speed=types.SimpleNamespace(get=lambda: 1.2), current_text=lambda: text,
                                    line_pace=(text, 1.5), line_voice=None)
        self.assertEqual(vl.Lab.synth_args(lab), ("en_GB-x-low", None, 1.8, 1.5, None))
        lab.speed = types.SimpleNamespace(get=lambda: 1.6)
        self.assertEqual(vl.Lab.synth_args(lab)[2], 2.0)            # clamped to Piper's range
        lab.current_text = lambda: "My own words."                    # typed over the line: the slider alone
        self.assertEqual(vl.Lab.synth_args(lab)[2:], (1.6, None, None))

    def test_voice_lab_uses_the_personality_voice(self):   # P19: "any personality" plays a line in its own voice
        import types
        vl = self.voice_lab()
        text = "Oh look, a rock."
        installed = ["en_GB-x-low", "en_US-ryan-high"]
        lab = types.SimpleNamespace(voice=types.SimpleNamespace(get=lambda: "en_GB-x-low"), speaker_ids=[3],
                                    speaker=types.SimpleNamespace(current=lambda: 0),
                                    speed=types.SimpleNamespace(get=lambda: 1.0), current_text=lambda: text,
                                    line_pace=None, line_voice=(text, "en_US-ryan-high", "sarcastic"),
                                    voices=types.SimpleNamespace(installed=lambda: installed))
        self.assertEqual(vl.Lab.synth_args(lab), ("en_US-ryan-high", None, 1.0, None, "sarcastic"))   # its first speaker
        installed.remove("en_US-ryan-high")                                  # not installed: the lab's voice
        self.assertEqual(vl.Lab.synth_args(lab), ("en_GB-x-low", 3, 1.0, None, None))
        installed.append("en_US-ryan-high")
        lab.current_text = lambda: "My own words."                           # typed over the line: the lab's voice
        self.assertEqual(vl.Lab.synth_args(lab)[0], "en_GB-x-low")

    def test_two_downloads_of_one_voice_do_not_collide(self):   # F69
        import hashlib, io, tempfile, threading
        import ed_tts
        payload = os.urandom(300_000)

        class Slow(io.BytesIO):
            def read(self, n=-1):
                time.sleep(0.002)
                return super().read(8192)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()
        files = [("en/en_GB/x/low/en_GB-x-low.onnx", {"size_bytes": len(payload), "md5_digest": hashlib.md5(payload).hexdigest()}),
                 ("en/en_GB/x/low/en_GB-x-low.onnx.json", {})]
        errs = []
        with tempfile.TemporaryDirectory() as d:
            def dl():
                try:
                    ed_tts.download_voice_files(files, d)
                except Exception as e:   # noqa: BLE001 -- collected for the assertion
                    errs.append(f"{type(e).__name__}: {e}")
            with unittest.mock.patch.object(ed_tts.urllib.request, "urlopen",
                                            lambda url, timeout: Slow(b"{}" if url.split("?")[0].endswith(".json") else payload)):
                threads = [threading.Thread(target=dl) for _ in range(2)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            self.assertEqual(errs, [])
            self.assertEqual(sorted(os.listdir(d)), ["en_GB-x-low.onnx", "en_GB-x-low.onnx.json"])
            with open(os.path.join(d, "en_GB-x-low.onnx"), "rb") as f:
                self.assertEqual(f.read(), payload)

    def test_three_personality_voices_stay_loaded(self):   # F72
        import tempfile
        import ed_tts
        loads = []

        class FakeVoice:
            @staticmethod
            def load(path):
                loads.append(os.path.basename(path))
                return FakeVoice()

            def synthesize_wav(self, text, wf, syn_config=None):
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\0\0" * 10)
        names = ("en_GB-a-low", "en_GB-b-low", "en_GB-c-low")
        styles = {"business": "Down to business", "sweet": {"label": "Sweet", "voice": names[0]},
                  "sarcastic": {"label": "Sarcastic", "voice": names[1], "speed": 1.3}, "dry": {"label": "Dry", "voice": names[2]}}
        self.assertEqual(ed_speech.style_voices(styles), set(names))
        with tempfile.TemporaryDirectory() as d:
            for n in names + ("en_GB-main-low",):
                for ext in (".onnx", ".onnx.json"):
                    with open(os.path.join(d, n + ext), "w") as f:
                        f.write("{}")
            sp = ed_tts.Speaker("en_GB-main-low", "en_GB-main-low", voices_dir=d)
            sp.PiperVoice, sp._voice, sp.voice_name = FakeVoice, FakeVoice(), "en_GB-main-low"
            if sp.SynthesisConfig is None:
                sp.SynthesisConfig = lambda **kw: None
            sp.size_extra(ed_speech.style_voices(styles))
            for i in range(9):
                sp.say(f"line {i}", voice=names[i % 3])
        self.assertEqual(sorted(loads), [n + ".onnx" for n in names])   # each loaded once
        sp.size_extra(["x"] * 9 + [f"en_GB-v{i}-low" for i in range(9)])
        self.assertEqual(sp._extra_slots, ed_tts.EXTRA_VOICES_MAX)   # bounded
        # the server sizes the cache from speech.json's personalities when a line asks for one of their voices
        import asyncio, types
        from aiohttp.test_utils import TestClient, TestServer
        sized = []
        self.state.speaker = types.SimpleNamespace(ready=True, installed=lambda: list(names), size_extra=lambda n: sized.append(set(n)),
                                                   say=lambda text, speed, voice: b"RIFF")
        self.state.speech = types.SimpleNamespace(lines=lambda: {"styles": styles})

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return (await c.get("/api/say", params={"text": "Hello.", "voice": names[1]})).status
        self.assertEqual(asyncio.run(go()), 200)
        self.assertEqual(sized, [set(names)])

    def test_backup_copies_in_steps(self):   # F48
        import sqlite3, tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "live.sqlite")
            live = sqlite3.connect(path)
            live.execute("CREATE TABLE t (x)")
            live.executemany("INSERT INTO t VALUES (?)", [(os.urandom(400),) for _ in range(8000)])   # ~800 pages
            live.commit()
            writer = sqlite3.connect(path, timeout=0)   # a commit that had to wait would fail at once
            wrote = []

            class Src:   # the live database, with the tailer committing between every step of the copy
                def backup(self, dst, **kw):
                    if kw.get("progress"):
                        inner = kw["progress"]

                        def progress(*a):
                            writer.execute("INSERT INTO t VALUES (1)")
                            writer.commit()
                            wrote.append(1)
                            return inner(*a)
                        kw["progress"] = progress
                    return live.backup(dst, **kw)
            dst = sqlite3.connect(os.path.join(d, "copy.sqlite"))
            ed_outrider.copy_database(Src(), dst)
            self.assertGreater(len(wrote), 1)                                  # writes got through meanwhile
            self.assertEqual(dst.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(dst.execute("SELECT count(*) FROM t").fetchone()[0],    # and it finished, complete
                             live.execute("SELECT count(*) FROM t").fetchone()[0])
            quiet = sqlite3.connect(os.path.join(d, "quiet.sqlite"))
            ed_outrider.copy_database(live, quiet)                             # no writer: an identical copy
            self.assertEqual(list(quiet.iterdump()), list(live.iterdump()))
            for c in (writer, dst, quiet, live):
                c.close()


class FableServer(unittest.TestCase):
    """Fourth review (Fable audit), batch 2: server state, call-outs and robustness."""

    CANDS = Batch2Values.CANDS

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.jump("2026-01-01T00:00:00Z", 1, 0)

    jump, honk, planet, moments, organic, sampling_body = (
        Batch6Voice.jump, Batch6Voice.honk, Batch6Voice.planet, Batch6Voice.moments, Batch6Voice.organic,
        Batch6Voice.sampling_body)

    def sell(self, ts, systems):
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": ts, "TotalEarnings": 1000, "BaseValue": 1000,
                       "Bonus": 0, "Discovered": [{"SystemName": s, "NumBodies": 1} for s in systems]})

    # ---- F5: the first jump of a session starts where you logged in ----
    def test_first_jump_counts_its_light_years(self):   # F5
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T10:00:00Z", "Commander": "X"})
        self.j.handle({"event": "Location", "timestamp": "2026-01-02T10:00:12Z", "StarSystem": "S1", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})                          # a relog: no jumps row
        for i in range(3):
            self.jump(f"2026-01-02T10:0{i + 1}:00Z", 2 + i, 40 * (i + 1))
        st = self.state.span_stats("2026-01-02T10:00:00Z", "2026-01-02T11:00:00Z")
        self.assertEqual((st["jumps"], st["ly"]), (3, 120.0))
        latest = self.state.sessions("")[0]                            # two sessions: day 1's arrival, then day 2
        self.assertEqual((latest["jumps"], latest["ly"]), (3, 120.0))
        self.assertEqual(self.state.sessions("2026-01-02T00:00:00Z")[0]["ly"], 120.0)
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-02T11:00:00Z"})
        self.db.commit()
        self.assertEqual(self.state.last_session()["ly"], 120.0)
        self.assertEqual(self.moments("game_exit")[-1]["session"]["ly"], 120.0)

    # ---- F21: a launch that never loaded a commander ends no session ----
    def test_menu_only_launch_keeps_the_last_session(self):   # F21
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T09:00:00Z", "Commander": "X"})
        for i in range(3):
            self.jump(f"2026-01-01T09:0{i + 1}:00Z", 2 + i, 10 * (i + 1))
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T12:00:00Z"})
        self.db.commit()
        first = self.state.last_session()
        self.assertEqual((first["start"], first["end"], first["jumps"]), ("2026-01-01T09:00:00Z", "2026-01-01T12:00:00Z", 3))
        self.assertIsNotNone(self.moments("game_exit")[-1]["session"])
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T18:03:00Z"})   # quit from the main menu
        self.db.commit()
        self.assertEqual(self.state.last_session()["end"], "2026-01-01T12:00:00Z")
        self.assertIsNone(self.moments("game_exit")[-1]["session"])                # no recap said again
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T09:00:00Z", "Commander": "X"})
        self.jump("2026-01-02T09:01:00Z", 9, 90)
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-02T10:00:00Z"})
        self.db.commit()
        self.assertEqual(self.state.last_session()["start"], "2026-01-02T09:00:00Z")   # a real session again

    # ---- F4: "Repair Basic" is the SRV's repair ----
    def test_srv_repair_leaves_the_ship_hull(self):   # F4
        self.j.handle({"timestamp": "2026-01-01T00:00:30Z", "event": "HullDamage", "Health": 0.62, "PlayerPilot": True})
        self.j.handle({"event": "Materials", "timestamp": "2026-01-01T00:00:40Z", "Raw": [{"Name": "iron", "Count": 9},
                       {"Name": "nickel", "Count": 9}], "Manufactured": [], "Encoded": []})
        self.j.handle({"timestamp": "2026-01-01T00:01:00Z", "event": "Synthesis", "Name": "Repair Basic",
                       "Materials": [{"Name": "iron", "Count": 2}, {"Name": "nickel", "Count": 1}]})
        self.assertEqual(self.j.hull["pct"], 62)
        self.assertNotIn("repairs", self.state.materials_summary())    # no "basic repairs can be synthesised"
        self.assertNotIn("Repair basic", ed_materials.SYNTH)

    # ---- F6: an Apex shuttle or another commander's ship ----
    def test_taxi_and_multicrew_are_not_your_ship(self):   # F6
        self.j.handle({"event": "JetConeBoost", "timestamp": "2026-01-01T00:00:30Z", "BoostValue": 4.0})
        hist = list(self.j.fuel_hist)
        self.j.jump_arrival = None
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:01:00Z", "StarSystem": "S2", "SystemAddress": 2,
                       "StarPos": [20, 0, 0], "Taxi": True, "Multicrew": False, "FuelUsed": 0.3, "JumpDist": 20})
        self.assertEqual(self.j.fuel_hist, hist)                         # not a pace sample for your ship
        self.assertIsNone(self.j.jump_arrival)                           # no auto honk in a taxi
        self.assertIsNotNone(self.j.boost)                               # your ship's charge is still there
        self.assertEqual(self.j.pos["id64"], 2)                          # but you are there
        self.assertEqual(self.db.execute("SELECT count(*) FROM jumps WHERE id64 = 2").fetchone()[0], 1)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:02:00Z", "StarSystem": "S3", "SystemAddress": 3,
                       "StarPos": [40, 0, 0], "Multicrew": True, "FuelUsed": 2.0, "JumpDist": 20})
        self.assertIsNone(self.j.jump_arrival)
        self.j.handle({"event": "Docked", "timestamp": "2026-01-01T00:03:00Z", "StationName": "Port", "StationType": "Coriolis",
                       "MarketID": 5, "StarSystem": "S3", "Taxi": True, "StationServices": ["exploration"]})
        self.assertIsNone(self.j.docked)                                 # no "docked, N cr to sell"
        self.j.handle({"event": "Docked", "timestamp": "2026-01-01T00:04:00Z", "StationName": "Port", "StationType": "Coriolis",
                       "MarketID": 5, "StarSystem": "S3", "Taxi": False, "StationServices": ["exploration"]})
        self.assertEqual(self.j.docked["station"], "Port")
        self.j.handle({"event": "Undocked", "timestamp": "2026-01-01T00:05:00Z", "StationName": "Port", "Taxi": True})
        self.assertIsNone(self.j.docked)                                 # you left the station, in the shuttle
        self.assertEqual(self.moments("undocked"), [])                   # but no undock alert
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:06:00Z", "StarSystem": "S4", "SystemAddress": 4,
                       "StarPos": [60, 0, 0], "Taxi": False, "Multicrew": False, "FuelUsed": 2.0, "JumpDist": 20})
        self.assertEqual(self.j.jump_arrival["id64"], 4)                 # your own jumps as before
        self.assertIsNone(self.j.boost)

    # ---- F10 / F51: when a rescan or remap is sold data ----
    def first_body(self, ts, name="S1 A 1"):
        ev = scan(ts, "S1", 1, 5, name)[2]
        self.j.handle(ev)

    def mapped(self, ts):
        self.j.handle({"event": "SAAScanComplete", "timestamp": ts, "SystemAddress": 1, "BodyName": "S1 A 1", "BodyID": 5})

    def test_remap_after_a_sale_is_sold(self):   # F10
        self.first_body("2026-01-01T00:01:00Z")
        self.mapped("2026-01-01T00:02:00Z")
        self.sell("2026-01-01T01:00:00Z", ["S1"])
        self.mapped("2026-01-01T02:00:00Z")                                # a second DSS on a return visit
        f = ed_outrider.own_firsts(self.db, 1, "S1")
        self.assertEqual((f["mapped_by"]["sold"], f["mapped_by"]["unsold"]), (1, 0))
        row = self.db.execute("SELECT ts, first_ts FROM own_mapped").fetchone()
        self.assertEqual(tuple(row), ("2026-01-01T02:00:00Z", "2026-01-01T00:02:00Z"))

    def test_first_map_after_a_scan_sale_is_unsold(self):   # F10: the first map, not the first scan
        self.first_body("2026-01-01T00:01:00Z")
        self.sell("2026-01-01T01:00:00Z", ["S1"])
        self.mapped("2026-01-01T02:00:00Z")
        f = ed_outrider.own_firsts(self.db, 1, "S1")
        self.assertEqual(f["mapped_by"]["unsold"], 1)

    def test_sale_after_a_loss_did_not_buy_the_lost_scan(self):   # F51
        for e in death("2026-01-01T00:30:00Z"):
            self.j.handle(e[2])
        self.sell("2026-01-01T01:00:00Z", ["S1"])
        judge = ed_outrider.pickup_judge(self.db, "S1")
        # first scanned 00:10, ship lost 00:30, a sale naming S1 (other bodies) 01:00, rescanned 02:00
        self.assertEqual(judge("2026-01-01T02:00:00Z", "2026-01-01T00:10:00Z")[0], "unsold")
        self.assertEqual(judge("2026-01-01T02:00:00Z", "2026-01-01T00:40:00Z")[0], "sold")   # no loss in between

    # ---- F14: the approach briefing knows what you already sampled ----
    def test_approach_skips_finished_species(self):   # F14
        self.sampling_body()
        self.organic("2026-01-01T00:02:30Z", "Analyse", "Stratum Tectonicas", "Stratum")
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T01:00:00Z", "Commander": "X"})   # a later session
        self.j.handle({"event": "ApproachBody", "timestamp": "2026-01-01T01:05:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            a = self.moments("approach")[-1]
        self.assertEqual((a["genera"], a["signals"], a["bio_value"]), (["Bacterium"], 1, 1_000_000))

    def test_approach_options_leave_out_a_sampled_genus(self):   # F14: no DSS
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", Landable=True, PlanetClass="Rocky body", MassEM=0.2)
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyName": "S1 A 4",
                       "BodyID": 4, "Signals": [{"Type": ed_outrider.BIO, "Count": 2}]})
        self.organic("2026-01-01T00:03:00Z", "Log", "Stratum Tectonicas", "Stratum")
        self.j.handle({"event": "ApproachBody", "timestamp": "2026-01-01T00:05:00Z", "SystemAddress": 1, "Body": "S1 A 4", "BodyID": 4})
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            a = self.moments("approach")[-1]
        self.assertNotIn("Stratum", a["bio_options"]["genera"])

    # ---- F31: a run under way on a body with no DSS keeps its unidentified signals ----
    def test_leaving_keeps_unidentified_signals_during_a_run(self):   # F31
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4", Landable=True, PlanetClass="Rocky body", MassEM=0.2)
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyName": "S1 A 4",
                       "BodyID": 4, "Signals": [{"Type": ed_outrider.BIO, "Count": 3}]})
        self.organic("2026-01-01T00:03:00Z", "Log", "Stratum Tectonicas", "Stratum")
        self.db.commit()
        with unittest.mock.patch.object(ed_bio, "predict", return_value=self.CANDS):
            p = self.state.leaving_summary(1)["bio_pending"]
        self.assertEqual([(b["genera"], b["signals"], b["partial"]) for b in p], [(None, 2, {"Stratum": 1})])
        self.assertEqual(p[0]["potential"], 19_010_800 + 16_777_215 + 3_703_200)   # the run plus the two best left

    # ---- F25 / G1.1: the arrival verdict ----
    def star(self, ts, id64, disc):
        self.j.handle(scan(ts, f"S{id64}", id64, 0, f"S{id64}", disc=disc, star=True)[2])

    def test_failed_lookup_is_no_announcement(self):   # F25
        self.jump("2026-01-01T00:01:00Z", 2, 10)
        self.state.target_verdicts[2] = "lookup failed"
        self.star("2026-01-01T00:01:05Z", 2, disc=False)
        self.state.reconcile_arrival()
        a = self.state.arrival
        self.assertEqual((a["announced"], a["undiscovered"], a["wrong"], a["sound"]), (None, True, False, None))

    def test_failed_verdict_is_reconciled_again(self):   # G1.1
        self.jump("2026-01-01T00:01:00Z", 2, 10)
        self.star("2026-01-01T00:01:05Z", 2, disc=True)
        self.state.target_verdicts[2] = "explored"
        with unittest.mock.patch.object(self.state, "fix_verdict", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                self.state.reconcile_arrival()
        self.assertIsNone(self.state.arrival)                           # not marked reconciled
        self.state.reconcile_arrival()                                  # the next tick
        self.assertEqual(self.state.arrival["verdict"], "complete")
        self.assertIsNotNone(self.state.arrival["streak"])

    # ---- F3: a cancelled charge during a flicker ----
    def test_scoop_end_after_a_cancelled_charge(self):   # F3
        W, S, C = ed_outrider.ScoopWatch, ed_outrider.FLAG_SCOOPING, ed_outrider.FLAG_FSD_CHARGING
        w, out = W(), []
        steps = [(t, S, 10 + t) for t in range(10)] + [(10, C, 20)] + [(t, S, 10 + t) for t in range(11, 20)] + \
            [(20, 0, 25), (23, 0, 25)]
        for t, flags, fuel in steps:
            r = w.update({"live": True, "flags": flags, "fuel_main": fuel}, 32.0, 1000 + t)
            if r:
                out.append(r)
        self.assertEqual(out, [{"pct": 78, "full": False}])

    # ---- F12: a malformed NavRoute.json ----
    def test_malformed_route_is_skipped(self):   # F12
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for route in ({"timestamp": "2026-01-01T00:05:00Z", "Route": [{"SystemAddress": 7, "StarPos": [1, 2, 3]}, "junk",
                                                                          {"StarSystem": "X", "SystemAddress": 8, "StarPos": 5}]},
                          ["not", "an", "object"], {"Route": 5}):
                with open(os.path.join(d, "NavRoute.json"), "w") as f:
                    json.dump(route, f)
                self.j.read_navroute(d)                                 # no exception
            self.assertEqual([tuple(r) for r in self.db.execute("SELECT id64, name FROM route_systems")], [(7, None)])

    # ---- F62: every moment the server holds ----
    def test_moments_payload_sends_the_whole_deque(self):   # F62
        for i in range(14):
            self.j.handle({"event": "Interdicted", "timestamp": f"2026-01-01T00:{i + 10:02d}:00Z", "Interdictor": "x"})
        self.assertEqual(len(self.moments("interdicted")), 14)

    # ---- F27: /api/say from another site ----
    def test_say_refused_cross_site(self):   # F27
        guard = Batch0Security.guard
        self.assertEqual(guard(self, "GET", "127.0.0.1:8025", site="cross-site", path="/api/say"), 403)
        self.assertEqual(guard(self, "GET", "127.0.0.1:8025", site="same-site", path="/api/say"), 403)
        self.assertEqual(guard(self, "GET", "127.0.0.1:8025", site="same-origin", path="/api/say"), 200)   # the page
        self.assertEqual(guard(self, "GET", "127.0.0.1:8025", path="/api/say"), 200)                      # curl
        self.assertEqual(guard(self, "GET", "127.0.0.1:8025", site="cross-site", path="/api/nearby"), 200)   # reads

    # ---- F18 / F19: backups ----
    def test_backup_of_a_missing_database_fails(self):   # F18
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "backups")
            os.makedirs(out)
            with open(os.path.join(out, "outrider-x-20200101-000000Z.zip"), "w") as f:
                f.write("a good old one")
            self.state.db_path = os.path.join(d, "x.sqlite")            # moved away while the server runs
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 1):
                with self.assertRaises(sqlite3.OperationalError):
                    self.state.make_backup()
            self.assertFalse(os.path.exists(self.state.db_path))          # not created
            self.assertEqual(os.listdir(out), ["outrider-x-20200101-000000Z.zip"])   # nothing rotated out

    def test_rotation_failure_is_a_warning(self):   # F19
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "backups")
            os.makedirs(out)
            for i in (1, 2):
                with open(os.path.join(out, f"outrider-x-2020010{i}-000000Z.zip"), "w") as f:
                    f.write("old")
            dbp = os.path.join(d, "x.sqlite")
            sqlite3.connect(dbp).close()
            self.state.db_path = dbp
            real = os.remove

            def remove(p):
                if p.endswith(".zip"):
                    raise PermissionError(13, "Permission denied", p)
                return real(p)
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 1), \
                    unittest.mock.patch.object(ed_outrider.os, "remove", remove):
                res = self.state.make_backup()
            self.assertTrue(os.path.exists(res["path"]))
            self.assertEqual(res["kept"], 3)
            self.assertIn("old backups not rotated", res["warning"])
            self.assertIn("Permission denied", res["warning"])

    # ---- F16 / F17 / F15: the Spansh cache ----
    def spansh(self, dump):
        calls = []

        class FakeSpansh(ed_outrider.Spansh):
            async def lookup(self, id64, interactive=True):
                calls.append(id64)
                return dump

            async def sphere(self, pos, r):
                return [{"id64": 7, "name": "S7", "x": 1, "y": 0, "z": 0, "updated_at": "u1", "body_count": 2,
                         "bodies": [{"name": "S7 1", "type": "Planet", "subtype": "Icy body"}]}]
        sp = FakeSpansh(self.db)
        self.state.spansh = sp
        self.state.center = self.j.pos
        return sp, calls

    def test_dump_404_is_asked_again_later(self):   # F16
        import asyncio
        sp, calls = self.spansh(None)
        asyncio.run(self.state._refresh(self.j.pos))
        self.assertEqual(calls, [7])
        asyncio.run(self.state._refresh(self.j.pos))                    # at once: the 404 is remembered
        self.assertEqual(calls, [7])
        self.db.execute("UPDATE spansh_systems SET fetched_ts = ? WHERE id64 = 7", (time.time() - ed_outrider.NO_DUMP_RETRY - 1,))
        asyncio.run(self.state._refresh(self.j.pos))                    # an hour on: asked again
        self.assertEqual(calls, [7, 7])

    def test_cached_system_without_bodies_is_not_refetched(self):   # F17
        import asyncio
        sp, calls = self.spansh({"system": {"bodyCount": 0, "bodies": [{"name": "S9 A Belt Cluster 1", "type": "Belt"}]}})
        self.db.execute("INSERT INTO visits VALUES (9, 'S9', 500, 0, 0, 't', 't', 1)")
        asyncio.run(self.state.ensure_records(9))
        asyncio.run(self.state.ensure_records(9))
        self.assertEqual(calls, [9])

    def test_on_demand_dump_is_current_for_the_refresh(self):   # F15
        import asyncio
        sp, calls = self.spansh({"system": {"bodyCount": 2, "bodies": [{"name": "S7 1", "type": "Planet", "subType": "Icy body",
                                                                          "bodyId": 1}]}})
        self.db.execute("INSERT INTO visits VALUES (7, 'S7', 1, 0, 0, 't', 't', 1)")
        asyncio.run(self.state.ensure_records(7))                       # a bookmark opened before it is in range
        self.assertEqual(calls, [7])
        asyncio.run(self.state._refresh(self.j.pos))                    # then the sphere: no second fetch
        self.assertEqual(calls, [7])

    # ---- F23: History refetches on jumps and sales, not scans ----
    def test_history_version(self):   # F23
        self.state.apply_own_changes()
        v = self.state.history_version
        self.planet("2026-01-01T00:01:00Z", 1, 4, "A 4")
        self.state.apply_own_changes()
        self.assertEqual(self.state.history_version, v)                 # a scan: History is not fetched again
        self.jump("2026-01-01T00:02:00Z", 2, 10)
        self.state.apply_own_changes()
        self.assertEqual(self.state.history_version, v + 1)
        self.sell("2026-01-01T00:03:00Z", ["S2"])
        self.state.apply_own_changes()
        self.assertEqual(self.state.history_version, v + 2)
        self.assertEqual(self.state.payload()["history_version"], v + 2)

    # ---- F24: a sale is stamped with the estimate made before it ----
    def test_sale_estimate_is_the_one_before_the_sale(self):   # F24
        now = time.time()
        pre = {"carto": {"estimated_payout": 40}, "bio": {"estimated_value": 7}}
        post = {"carto": {"estimated_payout": 0}, "bio": {"estimated_value": 0}}
        self.sell(ed_outrider.iso_ts(now - 600), ["S1"])              # read at start, before any estimate
        self.state.unsold_log = [(ed_outrider.iso_ts(now - 300), post)]
        self.state.note_sale_estimates()
        self.assertEqual(self.db.execute("SELECT count(*) FROM sale_estimates").fetchone()[0], 0)
        # a later bio sale does not stamp the old carto sale with today's post-sale figure
        self.state.unsold_log = [(ed_outrider.iso_ts(now - 300), pre), (ed_outrider.iso_ts(now - 5), post)]
        self.j.handle({"event": "SellOrganicData", "timestamp": ed_outrider.iso_ts(now - 60),
                       "BioData": [{"Species_Localised": "X", "Value": 7, "Bonus": 0}]})
        self.state.note_sale_estimates()
        rows = [tuple(r) for r in self.db.execute("SELECT kind, estimate FROM sale_estimates")]
        self.assertEqual(rows, [("bio", 7)])                            # the estimate finished before the sale


class Batch4Review(unittest.TestCase):
    """PLAN-review-2026-09-30b Batch 4: exobiology, unsold and the helper modules."""

    def test_bark_mounds_are_priced(self):   # F50
        self.assertEqual(ed_bio.species_value("Bark Mounds"), 1471900)
        self.assertEqual(ed_bio.species_value("Bark Mound"), 1471900)
        self.assertEqual(ed_bio.species_value("Bacterium Aurasus"), ed_unsold.species_value("$Codex_Ent_Bacterial_01")[0])

    def test_pressure_keeps_its_fine_digits(self):   # F53
        ev = {"event": "Scan", "BodyName": "S 1", "BodyID": 1, "PlanetClass": "Rocky body", "MassEM": 0.1,
              "SurfacePressure": 0.002862 * 101325, "DistanceFromArrivalLS": 10}
        r = ed_outrider.record_from_scan(ev)
        self.assertEqual(r["pressure"], 0.0029)                     # shown rounded
        self.assertAlmostEqual(ed_outrider._bio_body(r, "K", {})["pressure"], 0.002862)   # judged unrounded
        self.assertLess(ed_outrider._bio_body(r, "K", {})["pressure"], 0.00289)
        d = ed_outrider.record_from_dump("S", {"name": "S 1", "type": "Planet", "subType": "Rocky body",
                                               "surfacePressure": 0.002862})
        self.assertEqual((d["pressure"], d["pressure_raw"]), (0.0029, 0.002862))
        self.assertIsNone(ed_outrider.record_from_scan(dict(ev, SurfacePressure=0))["pressure_raw"])

    @unittest.skipUnless(ed_bio.available(), "bio_rules.json not downloaded")
    def test_rules_file_missing_a_key_counts_as_absent(self):   # F54
        import tempfile
        good = ed_bio._rules_path or ed_bio.RULES_FILE
        with open(good, encoding="utf-8") as f:
            data = json.load(f)
        try:
            with tempfile.TemporaryDirectory() as d:
                for drop in ("nebulae_planetary", "tuber_zones"):
                    path = os.path.join(d, f"no-{drop}.json")
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({k: v for k, v in data.items() if k != drop}, f)
                    self.assertIsNone(ed_bio.load_rules(path, force=True))
                    self.assertIsNone(ed_bio.load_rules(path))               # no KeyError on the next call either
                path = os.path.join(d, "list.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([1, 2], f)
                self.assertIsNone(ed_bio.load_rules(path, force=True))
        finally:
            self.assertIsNotNone(ed_bio.load_rules(good, force=True))

    def test_unknown_luminosity_does_not_rule_out_anemone(self):   # F52
        want = [["B", "IV"], ["B", "V"]]
        facts = lambda lum, complete=True: {"stars": [{"type": "B", "luminosity": lum, "main": True}],
                                            "main": {"type": "B", "luminosity": lum, "main": True}, "complete": complete}
        self.assertIs(ed_bio._check("star", want, {}, facts(None)), ed_bio.SKIP)
        self.assertIs(ed_bio._check("star", want, {}, facts("Va")), True)
        self.assertIs(ed_bio._check("star", want, {}, facts("III")), False)     # known and wrong: still out
        self.assertIs(ed_bio._check("main_star", want, {}, facts(None)), ed_bio.SKIP)
        self.assertIs(ed_bio._check("main_star", want, {}, facts("III")), False)
        self.assertIs(ed_bio._check("star", ["O"], {}, facts(None)), False)       # wrong class: out

    def test_remap_after_the_map_was_sold_adds_nothing(self):   # F55
        mapped = lambda ts: (T(ts), None, {"event": "SAAScanComplete", "timestamp": ts, "SystemAddress": 1, "BodyID": 4,
                                           "BodyName": "Sys 4", "ProbesUsed": 5, "EfficiencyTarget": 6})
        ev = [scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4"), mapped("2026-01-01T00:06:00Z"),
              sale("2026-01-02T00:00:00Z", ["Sys"]), mapped("2026-01-03T00:00:00Z")]
        self.assertEqual(ed_unsold.analyse(ev, ARGS)["exploration"]["rows"], [])
        # a first mapping after the scan alone was sold is still worth the map (F36)
        ev = [scan("2026-01-01T00:05:00Z", "Sys", 1, 4, "Sys 4"), sale("2026-01-02T00:00:00Z", ["Sys"]),
              mapped("2026-01-03T00:00:00Z")]
        self.assertEqual([r["map_only"] for r in ed_unsold.analyse(ev, ARGS)["exploration"]["rows"]], [True])

    # ---- Piper ----
    def _speaker(self, d, **kw):
        import ed_tts
        open(os.path.join(d, "en_GB-b-low.onnx"), "w").close()
        open(os.path.join(d, "en_GB-b-low.onnx.json"), "w").close()
        sp = ed_tts.Speaker("en_GB-a-low", "en_GB-b-low", voices_dir=d, **kw)
        sp.PiperVoice = unittest.mock.Mock()
        sp.PiperVoice.load = lambda path: os.path.basename(path)
        return sp

    def test_missing_preferred_voice_is_fetched_behind_the_fallback(self):   # G3.2
        import contextlib, io, tempfile
        import ed_tts
        with tempfile.TemporaryDirectory() as d:
            seen, switched, threads = [], [], []
            sp = self._speaker(d, on_switched=switched.append)
            sp.on_change = lambda: seen.append(sp.status)
            with unittest.mock.patch.object(ed_tts.threading, "Thread",
                                            lambda **kw: threads.append(kw) or unittest.mock.Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                sp._prepare(None)
            self.assertEqual(sp.voice_name, "en_GB-b-low")                # the installed one speaks at once
            self.assertEqual([t["args"] for t in threads], [("en_GB-a-low", "en_GB-b-low")])
            it = iter([_FakeResponse(b"{}"), _FakeResponse(b"model")])
            with unittest.mock.patch.object(ed_tts.urllib.request, "urlopen", lambda url, timeout: next(it)), \
                    contextlib.redirect_stdout(io.StringIO()):
                threads[0]["target"](*threads[0]["args"])
            self.assertEqual(sp.voice_name, "en_GB-a-low")                # switched once it arrived
            self.assertEqual(seen[2:], ["using en_GB-b-low; downloading en_GB-a-low (about 63 MB), switching to it "
                                        "when it is ready", "loading en_GB-a-low", "ready"])
            self.assertEqual(switched, [])                                # the config's voice, not a dialog choice
            self.assertIn("en_GB-a-low", ed_tts.installed_voices(d))
        # a failed download keeps the fallback and says so; a dialog pick made meanwhile wins
        with tempfile.TemporaryDirectory() as d:
            sp = self._speaker(d)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    unittest.mock.patch.object(ed_tts.threading, "Thread", lambda **kw: unittest.mock.Mock()):
                sp._prepare(None)
                with unittest.mock.patch.object(ed_tts, "download_voice_files", side_effect=OSError("offline")):
                    sp._fetch_preferred("en_GB-a-low", "en_GB-b-low")
            self.assertEqual((sp.voice_name, sp.status), ("en_GB-b-low", "using en_GB-b-low; could not download en_GB-a-low"))
            sp.wanted = "en_GB-c-low"
            with contextlib.redirect_stdout(io.StringIO()), \
                    unittest.mock.patch.object(ed_tts, "download_voice_files", lambda files, d: None):
                sp._fetch_preferred("en_GB-a-low", "en_GB-b-low")
            self.assertEqual(sp.voice_name, "en_GB-b-low")
        # an installed preferred voice starts no download
        with tempfile.TemporaryDirectory() as d:
            sp = self._speaker(d)
            sp.preferred = "en_GB-b-low"
            threads = []
            with unittest.mock.patch.object(ed_tts.threading, "Thread",
                                            lambda **kw: threads.append(kw) or unittest.mock.Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                sp._prepare(None)
            self.assertEqual(threads, [])

    def test_unspeakable_line_is_none_not_an_error(self):   # G3.1
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            sp = self._speaker(d)
            calls = []
            sp._voice = types_ns(synthesize_wav=lambda text, wf, syn_config=None: calls.append(text))
            self.assertIsNone(sp.say("…"))
            self.assertIsNone(sp.say("…"))
            self.assertEqual(calls, ["…"])                               # remembered, not synthesised again

    # ---- voice lab ----
    def _lab(self):
        try:
            import voice_lab
        except (ImportError, SystemExit):
            self.skipTest("no tkinter")
        return voice_lab

    def test_voice_lab_reads_the_configured_speech_file(self):   # F59
        voice_lab = self._lab()
        with unittest.mock.patch.object(voice_lab, "_config", lambda: {"server": {"speech_file": "~/my_lines.json"}}):
            self.assertEqual(voice_lab.configured_speech_file(), os.path.expanduser("~/my_lines.json"))
        with unittest.mock.patch.object(voice_lab, "_config", lambda: {"server": {"speech_file": "mine.json"}}):
            self.assertEqual(voice_lab.configured_speech_file(), os.path.join(voice_lab.ed_tts.HERE, "mine.json"))
        with unittest.mock.patch.object(voice_lab, "_config", lambda: {}):
            self.assertEqual(voice_lab.configured_speech_file(), voice_lab.SPEECH_FILE)

    def test_voice_lab_removes_each_spoken_wav(self):   # F60
        import tempfile
        voice_lab = self._lab()
        with tempfile.TemporaryDirectory() as d:
            p = voice_lab.Player()
            p.cmd = None                                                  # nothing is played in a test
            a, b = os.path.join(d, "a.wav"), os.path.join(d, "b.wav")
            for path in (a, b):
                open(path, "wb").close()
            p.play(a)
            p.play(b)
            self.assertEqual(os.listdir(d), ["b.wav"])
            p.stop()
            self.assertEqual(os.listdir(d), [])

    def test_voice_lab_refetches_a_truncated_catalogue(self):   # F61
        import io, tempfile
        voice_lab = self._lab()
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, "voices.json")
            with open(cache, "w") as f:
                f.write('{"en_GB-a-low": {"lang')
            with unittest.mock.patch.object(voice_lab, "VOICES_DIR", d), \
                    unittest.mock.patch.object(voice_lab, "CATALOGUE_CACHE", cache), \
                    unittest.mock.patch.object(voice_lab.urllib.request, "urlopen",
                                               lambda url, timeout: io.BytesIO(b'{"en_GB-a-low": {}}')):
                self.assertEqual(voice_lab.fetch_catalogue(), {"en_GB-a-low": {}})
            with open(cache) as f:
                self.assertEqual(json.load(f), {"en_GB-a-low": {}})
            self.assertEqual(os.listdir(d), ["voices.json"])              # no .part left behind

    def test_numpad_operator_labels(self):   # F57
        import ed_honk
        self.assertEqual([ed_honk.key_label(k) for k in ("KEY_KPPLUS", "KEY_KPENTER", "KEY_KPDOT", "KEY_SYSRQ",
                                                         "KEY_102ND", "KEY_KP5", "KEY_LEFTALT", "KEY_K")],
                         ["Numpad +", "Numpad Enter", "Numpad .", "Print Screen", "OEM 102", "Numpad 5", "Left Alt", "K"])


class BatchS2Voice(unittest.TestCase):
    """Batch S2: procedural names said properly, the welcome back after a break, the ship-loss debrief, the audition."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def jump(self, ts, id64, x):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [x, 0, 0]})

    def test_procedural_names_spoken(self):   # P4
        st = ed_speech.spoken_text
        self.assertEqual(st("Drojau LL-O b26-3 is undiscovered."), "Drojau L L O, b 26 3 is undiscovered.")
        self.assertEqual(st("Syreadiae JX-F c0, 42 ly"), "Syreadiae J X F, c 0, 42 ly")
        self.assertEqual(st("Lost 212.4M near Smojooe AR-E b25-8."), "Lost 212.4 million near Smojooe A R E, b 25 8.")
        self.assertEqual(st("Docked at Jaques Station."), "Docked at Jaques Station.")             # hand-named: untouched
        self.assertEqual(st("Out Of The Blue (K7F-3XZ) arrived"), "Out Of The Blue (K7F-3XZ) arrived")  # a carrier id too

    def test_away_text(self):   # P7
        self.assertIsNone(ed_outrider.away_text(None))
        self.assertIsNone(ed_outrider.away_text(90 * 60))
        self.assertEqual(ed_outrider.away_text(5 * 3600 + 600), "5 hours")
        self.assertEqual(ed_outrider.away_text(3 * 86400 + 600), "3 days")

    def login(self, ts):
        self.j.handle({"event": "LoadGame", "timestamp": ts, "Commander": "J", "Credits": 1})
        return [m for m in self.j.moments if m["kind"] == "game_start"][-1]

    def test_away_from_the_last_session_end(self):   # P7: Shutdown, a crash without one, a relog
        self.assertIsNone(self.login("2026-01-01T00:00:00Z")["away"])   # nothing before it: plain greeting
        self.jump("2026-01-01T01:00:00Z", 1, 0)
        self.j.handle({"event": "Shutdown", "timestamp": "2026-01-01T02:00:00Z"})
        # the game's menu writes Commander and Materials minutes before LoadGame: not where the break ended
        self.j.handle({"event": "Commander", "timestamp": "2026-01-04T01:50:00Z", "Name": "J", "FID": "F1"})
        self.j.handle({"event": "Materials", "timestamp": "2026-01-04T01:50:01Z", "Raw": [], "Manufactured": [], "Encoded": []})
        self.assertEqual(self.login("2026-01-04T02:00:00Z")["away"], "3 days")
        self.jump("2026-01-04T05:00:00Z", 2, 10)                          # then the game crashed: no Shutdown
        self.assertEqual(self.login("2026-01-04T10:20:00Z")["away"], "5 hours")
        self.jump("2026-01-04T10:21:00Z", 3, 20)
        self.assertIsNone(self.login("2026-01-04T10:30:00Z")["away"])    # a relog or mode switch: plain greeting

    def scan_star(self, ts, id64):
        self.j.handle(scan(ts, f"S{id64}", id64, 0, f"S{id64}", star=True)[2])

    def test_ship_loss_debrief(self):   # P15
        base = time.time() - 3600
        t = lambda minutes: ed_outrider.iso_ts(base + minutes * 60)
        self.jump(t(0), 1, 0)
        self.scan_star(t(1), 1)
        self.jump(t(5), 2, 10)
        self.scan_star(t(6), 2)
        self.j.handle(scan(t(7), "S2", 2, 1, "S2 1")[2])
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": t(10), "TotalEarnings": 1, "BaseValue": 1, "Bonus": 0,
                       "Discovered": [{"SystemName": "S1", "NumBodies": 1}]})   # S1 sold before the loss
        self.jump(t(15), 3, 20)
        self.scan_star(t(16), 3)
        self.j.handle({"event": "Died", "timestamp": t(58)})
        self.j.handle({"event": "Resurrect", "timestamp": t(58), "Option": "rebuy"})
        self.jump(t(59), 4, 100)                                          # respawned elsewhere
        self.db.commit()
        loss = self.state.ship_losses()[0]
        (m,) = [x for x in self.state.moments_summary() if x["kind"] == "loss"]
        self.assertEqual((m["carto"], m["bodies"], m["firsts"], m["ship"]), (round(loss["value"]), loss["bodies"], loss["firsts"], True))
        self.assertEqual(m["value"], round(loss["value"] + loss["bio_value"]))
        self.assertEqual(sorted(x["name"] for x in m["top"]), ["S2", "S3"])   # the sold system is not lost
        self.assertEqual(m["systems"], 2)
        self.assertEqual(sum(x["value"] for x in m["top"]), m["carto"])
        self.assertEqual((m["nearest"]["name"], m["nearest"]["distance"]), ("S3", 80.0))   # from where you respawned

    def test_no_debrief_when_the_ship_survived_or_the_death_is_old(self):   # P15
        now = ed_outrider.iso_ts(time.time() - 30)
        self.jump(now, 1, 0)
        self.scan_star(now, 1)
        self.j.handle({"event": "Died", "timestamp": now})
        self.j.handle({"event": "Resurrect", "timestamp": now, "Option": "recover"})   # on foot, nothing lost
        self.db.commit()
        self.assertEqual([x for x in self.state.moments_summary() if x["kind"] == "loss"], [])
        # a death read from an old journal (a catch-up, a re-read) is never narrated
        self.j.handle({"event": "Died", "timestamp": "2026-01-02T00:00:00Z"})
        self.j.handle({"event": "Resurrect", "timestamp": "2026-01-02T00:00:00Z", "Option": "rebuy"})
        self.assertEqual(len([x for x in self.j.moments if x["kind"] == "loss"]), 1)   # only the live one above

    def test_audition_alerts_exist(self):   # P19
        self.assertEqual(len(ed_speech.AUDITION), 8)
        self.assertLessEqual(set(ed_speech.AUDITION), set(ed_speech.KEYS))
        for key in ed_speech.AUDITION:   # every one has sample values for its placeholders
            self.assertLessEqual(ed_speech.fills(key) - set(ed_speech.ALWAYS), set(ed_speech.SAMPLES.get(key, {})), key)


class FindSystem(unittest.TestCase):
    """P12: GET /api/find, a system by name. EDSM is mocked (the Spansh object has no session: a real call fails)."""

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.sp = ed_outrider.Spansh(self.db)
        self.edsm = unittest.mock.AsyncMock(return_value=None)
        self.sp.edsm_system = self.edsm
        self.state = ed_outrider.State(self.db, self.j, self.sp, 25)

    def find(self, name):
        import asyncio
        return asyncio.run(self.state.find_system(name))

    def test_resolution_order_and_case(self):
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Here", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})
        self.db.execute("INSERT INTO bookmarks VALUES (5, 'Far Away', 30, 40, 0, '', 't')")
        self.sp.store(6, None, {"v": ed_outrider.CACHE_VERSION, "name": "Synuefe XR-H d11-102", "x": 3, "y": 4, "z": 0,
                                "records": [{"name": "Decoy", "type": "Planet"}]})
        self.sp.store(8, None, {"v": ed_outrider.CACHE_VERSION, "name": "Other", "x": 0, "y": 0, "z": 1,
                                "records": [{"name": "Decoy 100%", "type": "Planet"}]})
        self.db.execute("INSERT INTO route_systems VALUES (7, 'Far Away', 1, 1, 1, 'K', 't')")   # the bookmark wins
        self.db.execute("INSERT INTO route_systems VALUES (9, 'Route Only', 0, 6, 8, 'K', 't')")
        st, d = self.find("far away")
        self.assertEqual((st, d["id"], d["name"], d["source"], d["distance"], d["bookmarked"], d["visited"]),
                         (200, "5", "Far Away", "bookmark", 50.0, True, None))
        st, d = self.find("SYNUEFE xr-h D11-102")
        self.assertEqual((d["id"], d["source"], d["distance"], d["bookmarked"]), ("6", "spansh", 5.0, False))
        self.assertEqual(self.find("decoy")[0], 404)          # a body record's name is not a system
        self.assertEqual(self.find("Decoy 100%")[0], 404)     # LIKE wildcards are taken literally
        self.assertEqual(self.find("route only")[1]["source"], "route")
        st, d = self.find("here")
        self.assertEqual((d["id"], d["source"], d["visited"]["count"], d["next_stop"]), ("1", "visited", 1, False))
        self.state.set_next_stop(5)
        self.assertTrue(self.find("Far Away")[1]["next_stop"])
        # only the two names nobody here knows went on to (the mocked) EDSM
        self.assertEqual([c.args for c in self.edsm.await_args_list], [("decoy",), ("Decoy 100%",)])

    def test_edsm_hit_is_kept_for_after_a_restart(self):
        self.edsm.return_value = {"name": "Deep Space", "id64": 4242, "coords": {"x": 100, "y": 0, "z": 0},
                                  "primaryStar": {"type": "K (Yellow-Orange) Star", "isScoopable": True}}
        st, d = self.find("deep space")
        self.assertEqual((st, d["id"], d["name"], d["source"], d["distance"]), (200, "4242", "Deep Space", "edsm", None))
        self.edsm.assert_awaited_once_with("deep space")
        # a new State (a restart) finds it by id64: bookmark and next stop work
        state2 = ed_outrider.State(self.db, ed_outrider.Journals(self.db), self.sp, 25)
        self.assertEqual(state2.locate(4242), ("Deep Space", 100, 0, 0))
        self.assertTrue(state2.set_next_stop(4242))
        # the cached answer is stale on purpose: opening the system fetches Spansh's bodies at once
        self.assertGreater(self.sp.fetched_age(4242), ed_outrider.ON_DEMAND_MAX_AGE)
        self.assertEqual(self.find("Deep Space")[1]["source"], "spansh")   # now local
        self.assertEqual(self.edsm.await_count, 1)

    def test_unknown_and_failed(self):
        st, d = self.find("Nowhere")
        self.assertEqual(st, 404)
        self.assertIn("Nowhere", d["error"])
        self.edsm.return_value = {"name": "Vague", "id64": 3}      # EDSM knows it but has no coordinates
        self.assertEqual(self.find("Vague")[0], 404)
        self.edsm.side_effect = OSError("down")
        self.assertEqual(self.find("Nowhere")[0], 502)
        self.assertEqual(self.db.execute("SELECT count(*) FROM spansh_systems").fetchone()[0], 0)

    def test_route(self):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                self.assertEqual((await c.get("/api/find", params={"name": "  "})).status, 400)
                self.assertEqual((await c.get("/api/find", params={"name": "x" * 101})).status, 400)
                r = await c.get("/api/find", params={"name": "  Nowhere   Here "})
                self.assertEqual(r.status, 404)
                # another site's no-cors fetch cannot make it look names up on EDSM
                r = await c.get("/api/find", params={"name": "a"}, headers={"Sec-Fetch-Site": "cross-site"})
                self.assertEqual(r.status, 403)
        asyncio.run(go())
        self.edsm.assert_awaited_once_with("Nowhere Here")   # whitespace tidied; the cross-site one never asked


class BatchAAudio(unittest.TestCase):
    """Batch A: speech and sounds played on the server (the page's "Play speech and sounds on this PC" tick).
    Only fake players (small Python scripts) run here: nothing ever plays on the speakers."""

    def setUp(self):
        import tempfile
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.addCleanup(self.db.close)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "played")

        class FakeSpeaker:
            ready = available = True

            def installed(self):
                return []

            def say(self, text, speed, voice=None):
                return b"RIFF" + text.encode()
        self.state.speaker = FakeSpeaker()

    def fake(self, seconds=0.0, rc=0, stdin=True):
        """A LinePlayer whose player is a Python script: it appends what it was given to self.log (the WAV on
        stdin, or the file it was handed and whether it existed), sleeps, and exits with `rc`."""
        import ed_tts
        code = ("import os, sys, time\n"
                "data = sys.stdin.buffer.read() if len(sys.argv) < 2 else open(sys.argv[1], 'rb').read()\n"
                f"open({self.log!r}, 'a').write(data.hex() + '|' + (sys.argv[1] if len(sys.argv) > 1 else '-') + '\\n')\n"
                f"time.sleep({seconds}); sys.exit({rc})\n")
        cmd = [sys.executable, "-c", code]
        pl = ed_tts.LinePlayer("auto", which=lambda n: None)
        pl.player = ("fake", cmd, cmd if stdin else None)
        return pl

    def played(self):
        """[(the WAV bytes played, "-" for stdin or the file's path)]"""
        try:
            with open(self.log) as f:
                return [(bytes.fromhex(a), b) for a, b in (x.split("|") for x in f.read().splitlines())]
        except FileNotFoundError:
            return []

    def client(self, go):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return await go(c)
        return asyncio.run(run())

    def test_player_choice(self):
        import ed_tts
        have = lambda *names: (lambda n: f"/usr/bin/{n}" if n in names else None)
        self.assertEqual(ed_tts.find_player("auto", have("paplay", "aplay"))[0], "paplay")   # the first in order
        self.assertEqual(ed_tts.find_player("auto", have("pw-play", "aplay"))[0], "pw-play")
        self.assertEqual(ed_tts.find_player("aplay", have("pw-play", "aplay"))[0], "aplay")   # named: that one
        self.assertIsNone(ed_tts.find_player("ffplay", have("pw-play")))                       # named, missing
        self.assertIsNone(ed_tts.find_player("auto", have()))
        self.assertIsNone(ed_tts.find_player("off", have("pw-play")))
        self.assertIsNone(ed_tts.find_player("vlc", have("vlc", "pw-play")))
        self.assertIsNone(ed_tts.find_player("auto", have("pw-play"))[2])   # pw-play gets a file, not stdin
        self.assertIsNone(ed_tts.LinePlayer("off", have("pw-play")).name)
        self.assertEqual(ed_tts.LinePlayer("nonsense", have("aplay")).choice, "auto")
        self.assertEqual(ed_tts.LinePlayer("auto", have("aplay")).name, "aplay")
        try:   # the voice lab uses the same detection
            import voice_lab
        except (ImportError, SystemExit):
            return
        with unittest.mock.patch.object(ed_tts.shutil, "which", have("aplay")), \
                unittest.mock.patch.object(voice_lab.platform, "system", lambda: "Linux"):
            self.assertEqual(voice_lab.Player().cmd, ["aplay", "-q"])

    def test_config_server_player(self):
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = lambda cfg: ed_outrider.settings_from(cfg, args, None, ([], []))["server_player"]
        self.assertEqual(st({}), "auto")
        self.assertEqual(st({"speech": {"server_player": "PaPlay"}}), "paplay")
        self.assertEqual(st({"speech": {"server_player": "off"}}), "off")
        with unittest.mock.patch("sys.stderr"):
            self.assertEqual(st({"speech": {"server_player": "vlc"}}), "auto")   # reported, default kept
            self.assertEqual(st({"speech": {"server_player": 1}}), "auto")
            self.assertEqual(st({"speech": "off"}), "auto")
        full = ed_outrider.settings_from({"speech": {"server_player": "aplay"}}, args, None, ([], []))
        self.assertEqual(tomllib.loads(ed_outrider.config_text(full))["speech"]["server_player"], "aplay")
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ed_outrider.toml.example"),
                  encoding="utf-8") as f:
            example = f.read()
        self.assertIn("speech", tomllib.loads(example))   # the section, with the key shown commented out
        self.assertRegex(example.split("[speech]", 1)[1], r'# server_player = "auto"')

    def test_play_waits_and_refuses_a_second_line(self):
        import asyncio
        self.state.player = self.fake(seconds=0.6)

        async def go(c):
            first = asyncio.ensure_future(c.post("/api/say/play", json={"text": "one", "speed": 1.2}))
            await asyncio.sleep(0.25)
            second = await c.post("/api/say/play", json={"text": "two"})   # the first is still playing
            t0 = time.monotonic()
            r1 = await first
            return r1.status, await r1.json(), second.status, time.monotonic() - t0
        s1, b1, s2, _ = self.client(go)
        self.assertEqual((s1, b1, s2), (200, {"ok": True, "stopped": False}, 409))
        self.assertEqual(self.played(), [(b"RIFFone", "-")])   # on stdin; the refused line never played
        self.assertFalse(self.state.player.busy)

    def test_stop(self):
        import asyncio
        self.state.player = self.fake(seconds=10)

        async def go(c):
            t0 = time.monotonic()
            first = asyncio.ensure_future(c.post("/api/say/play", json={"text": "long", "id": "a1"}))
            await asyncio.sleep(0.4)
            other = await (await c.post("/api/say/stop", json={"id": "zz"})).json()   # another page's line: not this
            mine = await (await c.post("/api/say/stop", json={"id": "a1"})).json()
            r = await first
            took = time.monotonic() - t0
            # a stop that overtakes its line: the line is then not played at all
            await c.post("/api/say/stop", json={"id": "b2"})
            early = await (await c.post("/api/say/play", json={"text": "late", "id": "b2"})).json()
            return other, mine, r.status, await r.json(), took, early
        other, mine, status, body, took, early = self.client(go)
        self.assertEqual((other["stopped"], mine["stopped"], status, body), (False, True, 200, {"ok": True, "stopped": True}))
        self.assertLess(took, 5)
        self.assertEqual(early, {"ok": True, "stopped": True})
        self.assertEqual([x[0] for x in self.played()], [b"RIFFlong"])

    def test_503_and_file_players(self):
        import ed_tts

        async def go(c):
            out = []
            self.state.player = None                                  # tests / no LinePlayer
            out.append((await c.post("/api/say/play", json={"text": "x"})).status)
            self.state.player = ed_tts.LinePlayer("off")              # server_player = "off"
            r = await c.post("/api/say/play", json={"text": "x"})
            out.append((r.status, (await r.json())["error"]))
            out.append((await c.post("/api/sound/play", json={"name": "chime"})).status)
            self.state.player = self.fake()
            self.state.speaker.ready = False                          # no Piper voice ready
            out.append((await c.post("/api/say/play", json={"text": "x"})).status)
            self.state.speaker.ready = True
            self.state.player = self.fake(rc=1)                       # the player fails: the browser says it
            out.append((await c.post("/api/say/play", json={"text": "x"})).status)
            self.state.player = self.fake(stdin=False)                # pw-play style: a temporary file
            out.append((await c.post("/api/say/play", json={"text": "file"})).status)
            out.append((await c.post("/api/say/play", json=[1])).status)
            out.append((await c.post("/api/say/play", json={"text": "  "})).status)
            return out
        with unittest.mock.patch("sys.stderr"):
            got = self.client(go)
        self.assertEqual(got, [503, (503, "[speech] server_player is off"), 503, 503, 503, 200, 400, 400])
        data, path = self.played()[-1]
        self.assertEqual(data, b"RIFFfile")
        self.assertTrue(path.endswith(".wav"))
        self.assertFalse(os.path.exists(path))   # removed once played

    def test_cap(self):
        import asyncio
        pl = self.fake(seconds=30)
        pl.cap = 0.5
        line = pl.claim()
        t0 = time.monotonic()
        with unittest.mock.patch("sys.stderr"):
            result = asyncio.run(pl.play_line(line, b"RIFF"))
        self.assertEqual(result, "stopped")   # played up to the cap: not failed, or the browser says it again
        self.assertLess(time.monotonic() - t0, 5)

    def test_sound_play(self):
        import asyncio
        self.state.player = self.fake()

        async def go(c):
            r = await c.post("/api/sound/play", json={"name": "chime"})
            bad = await c.post("/api/sound/play", json={"name": "nope"})
            none = await c.post("/api/sound/play", json={})
            cross = await c.post("/api/sound/play", json={"name": "chime"}, headers={"Sec-Fetch-Site": "cross-site"})
            for _ in range(50):   # it answers at once and plays behind
                if self.played():
                    break
                await asyncio.sleep(0.1)
            await self.state.player.close()
            return r.status, bad.status, none.status, cross.status
        self.assertEqual(self.client(go), (200, 404, 400, 403))
        self.assertEqual(len(self.played()), 1)
        self.assertEqual(self.played()[0][0], self.state.sounds.wav("chime"))

    def test_render_sound(self):
        import io
        import wave
        import ed_tts
        doc = ed_tts.load_sounds()
        for name, spec in doc["sounds"].items():
            wav = ed_tts.render_sound(spec, doc["gain"])
            with wave.open(io.BytesIO(wav)) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, ed_tts.SOUND_RATE), name)
                frames = w.readframes(w.getnframes())
                length = w.getnframes() / w.getframerate()
            end = max(t.get("start", 0) + t["dur"] for t in spec["tones"])
            self.assertAlmostEqual(length, end + 0.05, delta=0.01, msg=name)
            peak = max(abs(v) for v in __import__("struct").unpack(f"<{len(frames) // 2}h", frames))
            self.assertGreater(peak, 1000, name)   # audible
            self.assertLessEqual(peak, 32767, name)
        # the lowpass does something, and a dry tone is left out of it
        fan = doc["sounds"]["fanfare"]
        self.assertNotEqual(ed_tts.render_sound(fan), ed_tts.render_sound(dict(fan, lowpass=None)))
        bank = ed_tts.SoundBank()
        self.assertIsNone(bank.wav("nope"))
        self.assertIs(bank.wav("chime"), bank.wav("chime"))   # rendered once

    def test_sound_names_match_the_page(self):
        import re
        import ed_tts
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "static", "page.js"), encoding="utf-8") as f:
            js = f.read()
        with open(os.path.join(root, "static", "page.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(root, "ed_outrider.py"), encoding="utf-8") as f:
            py = f.read()
        names = set(ed_tts.load_sounds()["sounds"])
        alerts = js[js.index("const ALERTS = "):js.index("const UNSPOKEN")]
        used = set(re.findall(r', "(\w+)"\]', alerts))                    # the alerts table's sound column
        used |= set(re.findall(r'\bsound: "(\w+)"', js))                     # alertOut(..., {sound: "upbeat"})
        lead = re.search(r"const SOUND_LEAD = \{([^}]*)\}", js).group(1)
        used |= set(re.findall(r"(\w+):", lead))
        used |= set(re.findall(r'"(thud|fanfare|upbeat)"', py))              # the target and arrival sounds
        tries = set(re.findall(r'data-try="(\w+)"', html))                   # the ▶ buttons
        self.assertTrue(used, "no sound names found in page.js")
        self.assertLessEqual(used, names, used - names)
        self.assertEqual(tries, names)   # every sound can be tried, and every button has a sound
        self.assertNotIn("fanfare(ctx", js)   # the page's own table is gone: it builds from sounds.json
        self.assertIn("/*SOUNDS*/null", html)
        self.assertEqual(set(json.loads(ed_outrider.sounds_json())["sounds"]), names)



class BatchBVoiceControl(unittest.TestCase):
    """Batch B: the hush, the co-pilot channel and button (never a real input device: the device layer is a
    stand-in), banned lines (temp files only, never a speech_banned.json in the repo)."""

    def setUp(self):
        import tempfile
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.addCleanup(self.db.close)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def client(self, go):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return await go(c)
        return asyncio.run(run())

    def speech_file(self, lines=None):
        path = os.path.join(self.tmp, "speech.json")
        doc = {"styles": {"business": "Business", "sarcastic": "Sarcastic"},
               "lines": lines or {"hull": {"business": ["Hull {pct}.", "Hull at {pct} percent.", "Hull damage."],
                                           "sarcastic": ["Ouch, {pct}."]},
                                  "heat": {"business": ["Heat damage.", "Hot."]}}}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    # ---- the gesture classifier: a pure function ----
    def test_gestures(self):
        import ed_button
        c = lambda ev, end=None: ed_button.classify(ev, 600, 350, end)
        self.assertEqual(c([(0, 1), (100, 0)]), ["status"])                                  # a tap
        self.assertEqual(c([(0, 1), (100, 0)], end=400), [])                                 # still waiting for a second
        self.assertEqual(c([(0, 1), (100, 0)], end=451), ["status"])
        self.assertEqual(c([(0, 1), (100, 0), (300, 1), (380, 0)]), ["again"])               # press 200 ms after the release
        self.assertEqual(c([(0, 1), (100, 0), (500, 1), (580, 0)]), ["status", "status"])    # too far apart: two taps
        self.assertEqual(c([(0, 1), (650, 0)]), ["hush"])                                    # a hold: on the release
        self.assertEqual(c([(0, 1), (599, 0)]), ["status"])                                  # just short of a hold
        self.assertEqual(c([(0, 1), (200, 2), (400, 2), (700, 0)]), ["hush"])                # autorepeat ignored
        self.assertEqual(c([(0, 1), (100, 0), (200, 1), (900, 0)]), ["hush"])                # a hold swallows the tap before
        self.assertEqual(c([(0, 0), (50, 2)]), [])                                           # a release with no press
        self.assertEqual(c([(0, 1), (100, 0), (300, 1), (380, 0), (500, 1), (560, 0)]), ["again", "status"])
        g = ed_button.Gestures(600, 350)
        self.assertEqual(g.feed(0, 1) + g.feed(50, 0), [])
        self.assertEqual(g.due(300), [])
        self.assertEqual(g.due(401), ["status"])
        self.assertEqual(g.due(900), [])                                                     # said once

    def fake_evdev(self, script):
        """A stand-in for the evdev module: one device ("Saitek X-56 Throttle") whose events come from `script`
        (a list of (seconds to wait, value) for the button, then an OSError, as an unplug gives). grab() and any
        virtual device fail the test."""
        import types
        test = self

        class Ev:
            def __init__(self, value, code=300, type_=1):
                self.type, self.code, self.value = type_, code, value

        class Dev:
            opened = []

            def __init__(self, path):
                if path == "/dev/input/event9":
                    raise PermissionError(13, "Permission denied")
                self.path, self.name, self.closed = path, "Saitek X-56 Throttle" if path.endswith("5") else "Keyboard", False
                Dev.opened.append(self)

            def grab(self):
                test.fail("the button must never grab the device")

            def close(self):
                self.closed = True

            async def async_read_loop(self):
                import asyncio
                for wait, value in script:
                    await asyncio.sleep(wait)
                    yield Ev(value, code=1, type_=0)   # noise: another event type
                    yield Ev(value, code=301)          # another button
                    yield Ev(value)
                raise OSError(19, "No such device")

        def uinput(*a, **k):
            test.fail("the button must never create a virtual device")
        ecodes = types.SimpleNamespace(EV_KEY=1, ecodes={"BTN_TRIGGER_HAPPY5": 300, "KEY_F13": 183},
                                       BTN={300: "BTN_TRIGGER_HAPPY5"}, KEY={183: "KEY_F13"})
        return types.SimpleNamespace(ecodes=ecodes, InputDevice=Dev, UInput=uinput,
                                     list_devices=lambda: ["/dev/input/event3", "/dev/input/event5", "/dev/input/event9"]), Dev

    def test_button_code_and_find_device(self):
        import ed_button
        ev, Dev = self.fake_evdev([])
        self.assertEqual(ed_button.button_code(ev, "btn_trigger_happy5"), 300)
        self.assertEqual(ed_button.button_code(ev, "183"), 183)
        self.assertEqual(ed_button.button_code(ev, 300), 300)
        self.assertIsNone(ed_button.button_code(ev, "BTN_NOPE"))
        self.assertIsNone(ed_button.button_code(ev, ""))
        dev, why = ed_button.find_device(ev, "x-56")
        self.assertEqual((dev.path, why), ("/dev/input/event5", None))
        self.assertTrue(all(d.closed for d in Dev.opened if d is not dev))   # the others are let go
        dev, why = ed_button.find_device(ev, "Rhino")
        self.assertIsNone(dev)
        self.assertIn("1 could not be opened", why)                           # the unreadable one is counted
        self.assertEqual(ed_button.find_device(ev, "/dev/input/event5")[0].path, "/dev/input/event5")
        self.assertIn("Permission denied", ed_button.find_device(ev, "/dev/input/event9")[1])
        self.assertIsNone(ed_button.find_device(ev, "")[0])

    def test_button_watch(self):
        import asyncio
        import ed_button
        # a tap, then a double tap, then a hold, then the device goes away
        ev, Dev = self.fake_evdev([(0, 1), (0.02, 0), (0.25, 1), (0.02, 0), (0.03, 1), (0.02, 0),
                                   (0.25, 1), (0.2, 0), (0.05, 2)])
        got = []

        async def go():
            w = ed_button.ButtonWatch("X-56", "BTN_TRIGGER_HAPPY5", got.append, hold_ms=150, double_ms=100, evdev=ev)
            seen = set()
            with unittest.mock.patch.object(ed_button, "RETRY", 0.05):
                t = asyncio.ensure_future(w.run())
                for _ in range(130):   # every status it shows on the way
                    seen.add(w.status)
                    await asyncio.sleep(0.01)
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)
            return seen
        seen = asyncio.run(go())
        self.assertIn("listening to Saitek X-56 Throttle for BTN_TRIGGER_HAPPY5", seen)
        self.assertEqual(got[:3], ["status", "again", "hush"])
        self.assertTrue(set(got) <= {"status", "again", "hush"})
        self.assertTrue(any("No such device; looking again" in x for x in seen), seen)   # the unplug, then a retry
        self.assertTrue(all(d.closed for d in Dev.opened))        # every device it opened was closed again
        self.assertGreater(len([d for d in Dev.opened if d.path.endswith("5")]), 1)   # and it looked again

        async def bad(button):
            w = ed_button.ButtonWatch("X-56", button, got.append, evdev=ev)
            await w.run()   # returns at once: nothing to listen for
            return w.status
        self.assertIn("is not a button name or number", asyncio.run(bad("BTN_NOPE")))

    def test_config(self):
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = lambda cfg: ed_outrider.settings_from(cfg, args, None, ([], []))["copilot"]
        self.assertEqual(st({}), {"enabled": False, "device": "", "button": "", "hold_ms": 600, "double_ms": 350})
        got = st({"copilot": {"enabled": True, "device": "X-56 Rhino Throttle", "button": 300, "hold_ms": 50, "double_ms": 5000}})
        self.assertEqual(got, {"enabled": True, "device": "X-56 Rhino Throttle", "button": "300", "hold_ms": 200, "double_ms": 1000})
        with unittest.mock.patch("sys.stderr"):
            self.assertFalse(st({"copilot": {"enabled": "true"}})["enabled"])   # a quoted switch is reported, stays off
            self.assertEqual(st({"copilot": {"button": True}})["button"], "")
            self.assertEqual(st({"copilot": {"device": 5}})["device"], "")
        full = ed_outrider.settings_from({"copilot": {"device": "X-56", "button": "BTN_TRIGGER_HAPPY5"}}, args, None, ([], []))
        back = tomllib.loads(ed_outrider.config_text(full))["copilot"]
        self.assertEqual(back, {"enabled": False, "device": "X-56", "button": "BTN_TRIGGER_HAPPY5", "hold_ms": 600, "double_ms": 350})
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ed_outrider.toml.example"), encoding="utf-8") as f:
            example = f.read()
        self.assertIn("copilot", tomllib.loads(example))
        section = example.split("[copilot]", 1)[1]
        for key in ("enabled = false", "device", "button", "hold_ms = 600", "double_ms = 350"):
            self.assertIn(f"# {key}", section)
        with open(os.path.join(root, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        for words in ("[copilot]", "uaccess", "`input` group", "latching", "Spoken lines", "Cut this line", "sound only"):
            self.assertIn(words, readme)

    # ---- the hush (server side) ----
    def test_hush(self):
        self.j.pos = {"id64": 11, "name": "A", "x": 0, "y": 0, "z": 0}
        self.assertIsNone(self.state.hush_info())
        v = self.state.version
        self.state.set_hush("10m")
        h = self.state.hush_info()
        self.assertEqual((h["mode"], h["sys"], self.state.version), ("10m", None, v + 1))
        self.assertAlmostEqual(h["left"], 600, delta=2)
        with unittest.mock.patch.object(ed_outrider.time, "time", lambda: h["until"] + 1):
            self.assertIsNone(self.state.hush_info())                      # run out
        self.assertIsNone(self.state.hush)
        self.state.set_hush("jump")
        self.assertEqual(self.state.hush_info(), {"mode": "jump", "until": None, "left": None, "sys": "11"})
        self.j.pos = dict(self.j.pos, id64=12)                              # the jump ends it
        self.assertIsNone(self.state.hush_info())
        self.state.set_hush("30m")
        self.state.set_hush("off")
        self.assertIsNone(self.state.hush_info())

        async def go(c):
            out = [(await c.post("/api/hush", json={"mode": "jump"})).status, self.state.hush_info()["sys"]]
            for body in ({"mode": "5m"}, {}, [1]):
                out.append((await c.post("/api/hush", json=body)).status)
            out.append((await c.post("/api/hush", json={"mode": "off"}, headers={"Sec-Fetch-Site": "cross-site"})).status)
            out.append(self.state.hush_info() is not None)                  # the refused request changed nothing
            r = await c.post("/api/hush", json={"mode": "off"})
            out.append((r.status, (await r.json())["hush"]))
            return out
        self.assertEqual(self.client(go), [200, "12", 400, 400, 400, 403, True, (200, None)])

    # ---- the co-pilot channel ----
    def test_copilot(self):
        self.j.pos = {"id64": 11, "name": "A", "x": 0, "y": 0, "z": 0}
        moments = list(self.j.moments) if hasattr(self.j, "moments") else None

        async def go(c):
            out = []
            r = await c.post("/api/copilot", json={"action": "status"})
            out.append((r.status, (await r.json())["seq"], self.state.copilot["action"]))
            out.append((await c.post("/api/copilot", json={"action": "replay"})).status)          # no words
            r = await c.post("/api/copilot", json={"action": "replay", "words": "  Tank   full. "})
            out.append((r.status, self.state.copilot["words"]))
            out.append((await c.post("/api/copilot", json={"action": "dance"})).status)
            out.append((await c.post("/api/copilot", json={"action": "status"}, headers={"Origin": "http://evil.example"})).status)
            await c.post("/api/copilot", json={"action": "hush"})                                  # a hold: hush till the jump
            out.append(self.state.hush_info()["mode"])
            await c.post("/api/copilot", json={"action": "hush"})                                  # another hold ends it
            out.append(self.state.hush_info())
            out.append(self.state.copilot["seq"])
            return out
        self.assertEqual(self.client(go), [(200, 1, "status"), 400, (200, "Tank full."), 400, 403, "jump", None, 4])
        if moments is not None:
            self.assertEqual(list(self.j.moments), moments)   # never a moment: a journal re-read cannot replay it
        # the button's gestures go through the same channel
        self.state.copilot_action("again")
        self.assertEqual((self.state.copilot["seq"], self.state.copilot["action"]), (5, "again"))

    # ---- banned lines ----
    def test_ban_validation(self):
        path = self.speech_file()
        sl = ed_speech.SpeechLines(path)
        v0 = sl.version()
        self.assertEqual(sl.set_ban("fuel_low", "Hull {pct}.")[0], 400)             # not an alert in the file
        self.assertEqual(sl.set_ban("hull", "Hull {pct} percent!")[0], 400)         # not a line in the file
        self.assertEqual(sl.set_ban("hull", 5)[0], 400)
        self.assertFalse(os.path.exists(ed_speech.banned_path(path)))               # nothing written for a refusal
        status, out = sl.set_ban("hull", "Hull {pct}.")
        self.assertEqual((status, out), (200, {"ok": True, "banned": 1}))
        self.assertEqual(os.path.dirname(ed_speech.banned_path(path)), self.tmp)    # next to the speech file
        got = sl.lines()
        self.assertEqual(got["lines"]["hull"]["business"], ["Hull at {pct} percent.", "Hull damage."])
        self.assertEqual(got["banned"], {"hull": ["Hull {pct}."]})
        self.assertNotEqual(sl.version(), v0)                                        # pages fetch the trimmed lines
        self.assertEqual(sl.set_ban("hull", "Hull {pct}.")[1]["banned"], 1)         # twice is once
        # a second reader (the voice lab, another process) sees the same bans
        self.assertEqual(ed_speech.SpeechLines(path).lines()["lines"]["hull"]["business"], ["Hull at {pct} percent.", "Hull damage."])
        self.assertEqual(sl.set_ban("hull", "Hull {pct}.", ban=False), (200, {"ok": True, "banned": 0}))
        self.assertEqual(len(sl.lines()["lines"]["hull"]["business"]), 3)
        # a broken or odd file bans nothing, and never stops the lines loading
        for text in ("{not json", "[1, 2]", '{"hull": "Hull {pct}."}'):
            with open(ed_speech.banned_path(path), "w") as f:
                f.write(text)
            fresh = ed_speech.SpeechLines(path)
            self.assertEqual(len(fresh.lines()["lines"]["hull"]["business"]), 3, text)
            self.assertIsNone(fresh.lines()["error"])
        self.assertEqual(ed_speech.read_bans(os.path.join(self.tmp, "missing.json")), {})

    def test_ban_never_empties_a_list(self):
        path = self.speech_file()
        sl = ed_speech.SpeechLines(path)
        self.assertEqual(sl.set_ban("heat", "Heat damage.")[0], 200)
        status, out = sl.set_ban("heat", "Hot.")                                    # the last line left in the list
        self.assertEqual(status, 409)
        self.assertIn("last line", out["error"])
        self.assertEqual(sl.lines()["lines"]["heat"]["business"], ["Hot."])
        self.assertEqual(sl.set_ban("hull", "Ouch, {pct}.")[0], 409)               # a list of one
        # a hand-edited file that bans a whole list: the list is used whole, and the review says so
        with open(ed_speech.banned_path(path), "w") as f:
            json.dump({"heat": ["Heat damage.", "Hot."]}, f)
        got = ed_speech.SpeechLines(path).lines()
        self.assertEqual(got["lines"]["heat"]["business"], ["Heat damage.", "Hot."])
        self.assertEqual(got["banned_whole"], ["heat/business"])
        lines, whole = ed_speech.apply_bans({"hull": {"business": ["a", "b"], "_note": "x", "when": ["a"]}}, {"hull": ["a"]})
        self.assertEqual((lines["hull"], whole), ({"business": ["b"], "_note": "x", "when": ["a"]}, []))

    def test_ban_endpoints_and_backup(self):
        import zipfile
        path = self.speech_file()
        self.state.speech = ed_speech.SpeechLines(path)

        async def go(c):
            out = []
            v = self.state.version
            out.append((await c.post("/api/speech/ban", json={"alert": "hull", "template": "Hull damage."})).status)
            out.append(self.state.version > v)
            r = await c.get("/api/speech")
            doc = await r.json()
            out.append(("Hull damage." in doc["lines"]["hull"]["business"], doc["banned"]))
            out.append((await c.post("/api/speech/ban", json={"alert": "hull", "template": "made up"})).status)
            out.append((await c.post("/api/speech/ban", json={"alert": "hull"})).status)
            out.append((await c.post("/api/speech/ban", json={"alert": "hull", "template": "Hull {pct}."},
                                     headers={"Sec-Fetch-Site": "cross-site"})).status)
            out.append((await c.post("/api/speech/unban", json={"alert": "hull", "template": "Hull damage."})).status)
            out.append((await (await c.get("/api/speech")).json())["banned"])
            await c.post("/api/speech/ban", json={"alert": "heat", "template": "Hot."})
            return out
        self.assertEqual(self.client(go), [200, True, (False, {"hull": ["Hull damage."]}), 400, 400, 403, 200, {}])
        # the backup zip carries the bans beside the speech file
        dbp = os.path.join(self.tmp, "x.sqlite")
        sqlite3.connect(dbp).close()
        self.state.db_path, self.state.speech_path, self.state.config_path = dbp, path, None
        with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", os.path.join(self.tmp, "b")), \
                unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []):
            out = self.state.make_backup()
        self.assertEqual(out["files"], ["x.sqlite", "speech.json", "speech_banned.json"])
        with zipfile.ZipFile(out["path"]) as z:
            self.assertEqual(json.loads(z.read("speech_banned.json")), {"heat": ["Hot."]})

    def test_voice_lab_sees_the_bans(self):
        try:
            import voice_lab
        except (ImportError, SystemExit):
            self.skipTest("voice_lab needs tkinter")
        path = self.speech_file()
        self.assertEqual(ed_speech.ban_line(path, "hull", "Hull damage.")[0], 200)
        styles, lines = voice_lab.load_lines(path)
        self.assertEqual(lines["hull"]["business"], ["Hull {pct}.", "Hull at {pct} percent."])
        self.assertIn("sarcastic", styles)

    def test_gitignored(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, ".gitignore"), encoding="utf-8") as f:
            self.assertIn("speech_banned.json", f.read().split())


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


class BatchDFuel(unittest.TestCase):
    """Batch D: the fuel model (laden range, per-hop fuel, jumps left), the local scoopable share, the in-system
    scoopable star and the targeted jump's cost."""

    # Real [JumpDist, FuelUsed, FuelLevel, cargo t] from the author's journals (copied here, never read from a live
    # database): a Mandalay (SCO 5A, Guardian booster size 5, UnladenMass 323.15 t, MaxJumpRange 83.487473 ly)
    # hopping to the nearest unvisited system, and a Panther Clipper Mk II (SCO 7A, booster size 4, 1596.8 t,
    # 44.958641 ly) on the same 12.571 ly jump empty and with 1,153 t in the hold.
    MANDALAY = {"unladen": 323.150024, "max_range": 83.487473, "fsd_size": 5, "booster_ly": 10.5, "max_fuel": None}
    MANDALAY_JUMPS = [[1.177, 0.000179, 31.999821, 0], [1.875, 0.000559, 30.999441, 0], [2.791, 0.001483, 31.498516, 0],
                      [3.295, 0.002229, 31.490419, 0], [3.914, 0.003346, 28.849634, 0], [4.245, 0.004158, 31.995842, 0],
                      [4.663, 0.005234, 31.994766, 0], [4.878, 0.005739, 28.935785, 0], [5.252, 0.006984, 31.477118, 0],
                      [5.985, 0.00962, 31.490379, 0], [7.012, 0.014219, 31.985781, 0], [12.441, 0.057825, 31.56846, 0]]
    PANTHER = {"unladen": 1596.800049, "max_range": 44.958641, "fsd_size": 7, "booster_ly": 9.25, "max_fuel": None}
    PANTHER_JUMPS = [[12.571, 0.456644, 126.433357, 0], [12.571, 1.287122, 126.712875, 1153],
                     [12.571, 0.457277, 127.542725, 0], [12.571, 1.285804, 125.146919, 1153], [12.571, 0.456283, 125.799706, 0]]

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    def test_model_against_real_jumps(self):
        m = ed_outrider.fuel_model(self.MANDALAY, self.MANDALAY_JUMPS)
        self.assertEqual((m["power"], m["fitted"]), (2.45, True))
        self.assertAlmostEqual(m["max_fuel"], 5.2, delta=0.01)          # an SCO 5A's MaxFuelPerJump
        for d, used, left, cargo in self.MANDALAY_JUMPS:                 # every real burn, to within 1%
            self.assertAlmostEqual(ed_outrider.hop_fuel(m, d, m["unladen"] + left + used + cargo) / used, 1, delta=0.01)
        # the Panther's cargo counts: the same jump burns 2.8 times the fuel with the hold full
        p = ed_outrider.fuel_model(self.PANTHER, self.PANTHER_JUMPS)
        self.assertEqual(p["power"], 2.75)
        self.assertAlmostEqual(p["max_fuel"], 13.1, delta=0.02)
        for d, used, left, cargo in self.PANTHER_JUMPS:
            self.assertAlmostEqual(ed_outrider.hop_fuel(p, d, p["unladen"] + left + used + cargo) / used, 1, delta=0.01)
        # a wrong exponent would not fit: at p 2.30 the estimates drift with the distance
        e = ed_outrider._fit_estimates(m, self.MANDALAY_JUMPS, 2.30)
        self.assertGreater((max(e) - min(e)) / min(e), 0.3)
        # an engineered drive that says its MaxFuelPerJump is taken as said
        self.assertEqual(ed_outrider.fuel_model(dict(self.MANDALAY, max_fuel=6.1), self.MANDALAY_JUMPS)["max_fuel"], 6.1)

    def test_power_fitted_for_a_size_the_table_lacks(self):
        truth = dict(unladen=1600.0, r0=50.0, boost=0, power=2.6, max_fuel=8.0)
        # jumps as that drive would burn them, 100 t in the tank before each
        jumps = [[d, ed_outrider.hop_fuel(truth, d, 1700), 100 - ed_outrider.hop_fuel(truth, d, 1700), 0] for d in (3, 9, 17, 25, 33, 40)]
        m = ed_outrider.fuel_model({"unladen": 1600.0, "max_range": 50.0, "fsd_size": 8, "booster_ly": 0}, jumps)
        self.assertEqual(m["power"], 2.6)
        self.assertAlmostEqual(m["max_fuel"], 8.0, places=2)
        # too few jumps to tell: no exponent, so no per-hop fuel (the range still works)
        few = ed_outrider.fuel_model({"unladen": 1600.0, "max_range": 50.0, "fsd_size": 8, "booster_ly": 0}, jumps[:3])
        self.assertIsNone(few["power"])
        self.assertIsNone(ed_outrider.jumps_left(few, 50, 0))

    def test_range_scaling_and_jumps_left(self):
        m = ed_outrider.fuel_model(self.MANDALAY, self.MANDALAY_JUMPS)
        u, mf = m["unladen"], m["max_fuel"]
        self.assertAlmostEqual(ed_outrider.fsd_range(m, u + mf), m["r0"], places=6)   # the Loadout's figure
        full = ed_outrider.fsd_range(m, u + 32)
        self.assertAlmostEqual(full, 77.98, delta=0.02)
        # the booster's 10.5 ly do not shrink with mass: 700 t of cargo halves only the drive's own part
        heavy = ed_outrider.fsd_range(m, 2 * (u + 32))
        self.assertAlmostEqual(heavy - 10.5, (full - 10.5) / 2, places=6)
        # at max range every jump burns MaxFuelPerJump, and each is longer than the one before (lighter)
        n, ly = ed_outrider.jumps_left(m, 32, 0)
        self.assertEqual(n, int(32 / mf))
        self.assertGreater(ly, n * full)
        # hops of 5 ly: thousands of them, counted past the cap at the last hop's cost
        pace, _ = ed_outrider.jumps_left(m, 32, 0, d=5)
        self.assertGreater(pace, 3000)
        self.assertEqual(ed_outrider.jumps_left(m, 3, 0), (0, 0.0))    # under one max jump's fuel
        self.assertIsNone(ed_outrider.jumps_left(m, 32, None))          # no cargo figure: no answer, not a wrong one

    def test_journal_loadout_cargo_and_samples(self):
        mods = [{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size5_class5",
                 "Engineering": {"Modifiers": [{"Label": "FSDOptimalMass", "Value": 2077.4}]}},
                {"Slot": "Slot03_Size5", "Item": "Int_GuardianFSDBooster_Size5"}]
        lo = {"event": "Loadout", "timestamp": "2026-01-01T00:00:00Z", "Ship": "mandalay", "ShipID": 32,
              "UnladenMass": 323.150024, "MaxJumpRange": 83.487473, "FuelCapacity": {"Main": 32.0, "Reserve": 0.5}, "Modules": mods}
        self.j.handle(lo)
        s = self.j.ship
        self.assertEqual((s["unladen"], s["fsd_size"], s["booster_ly"], s["max_fuel"]), (323.150024, 5, 10.5, None))
        self.j.handle({"event": "Cargo", "timestamp": "2026-01-01T00:00:01Z", "Vessel": "SRV", "Count": 4})   # the SRV's hold
        self.assertIsNone(self.j.cargo)
        self.j.handle({"event": "Cargo", "timestamp": "2026-01-01T00:00:02Z", "Vessel": "Ship", "Count": 0})
        self.assertEqual(self.j.cargo["count"], 0)
        for k, (d, used, left, _) in enumerate(self.MANDALAY_JUMPS[:4]):
            self.j.handle({"event": "FSDJump", "timestamp": f"2026-01-01T00:0{k + 1}:00Z", "StarSystem": f"S{k}", "SystemAddress": 100 + k,
                           "StarPos": [k, 0, 0], "JumpDist": d, "FuelUsed": used, "FuelLevel": left})
        self.assertEqual(self.j.fuel_hist[0], self.MANDALAY_JUMPS[0])
        self.assertIsNotNone(ed_outrider.fuel_model(self.j.ship, self.j.fuel_hist)["max_fuel"])
        # the same ship logged again with float jitter keeps its samples; a new drive starts them afresh
        self.j.handle(dict(lo, timestamp="2026-01-01T01:00:00Z", UnladenMass=323.149994, MaxJumpRange=83.487465))
        self.assertEqual(len(self.j.fuel_hist), 4)
        mods2 = [dict(mods[0], Item="int_hyperdrive_size5_class5"), mods[1]]
        self.j.handle(dict(lo, timestamp="2026-01-01T02:00:00Z", Modules=mods2, MaxJumpRange=70.1))
        self.assertEqual(self.j.fuel_hist, [])

    def test_fuel_summary_model_and_null_paths(self):
        self.j.ship = dict(self.MANDALAY, fuel_main=32.0)
        self.j.jump_range = {"ly": self.MANDALAY["max_range"], "ts": "x"}
        self.j.fuel_hist = [list(x) for x in self.MANDALAY_JUMPS]
        self.j.status_json = {"live": True, "fuel_main": 32.0, "flags": 1 << 24}   # no Cargo in Status.json, none from the journal
        f = self.state.fuel_summary()
        self.assertIsNone(f["model"])                                    # no cargo figure: the old estimate, no model
        self.assertIsNone(self.state.payload()["jump_range_now"])
        old_max = f["jumps_max"]
        self.j.status_json["cargo"] = 0
        f = self.state.fuel_summary()
        self.assertEqual((f["jumps_max"], f["model"]["fitted"]), (6, True))
        self.assertAlmostEqual(f["model"]["range_now"], 77.98, delta=0.02)
        self.assertNotEqual(old_max, f["jumps_max"])                     # the dist^2.5 guess said otherwise
        self.assertGreater(f["jumps_recent"], 1000)
        self.assertAlmostEqual(self.state.payload()["jump_range_now"], 77.98, delta=0.02)
        self.j.ship = {"fuel_main": 32.0, "max_range": 83.5}             # a Loadout from before UnladenMass was kept
        self.assertIsNone(self.state.fuel_summary()["model"])
        self.assertIsNone(self.state.range_now())

    def test_scoop_rate_and_dry_run(self):
        self.assertIsNone(self.state.scoop_rate())
        classes = ["K", "M", "L", "F", "T", "G", "M_RedGiant", "Y", "DA", "N"]   # oldest first; the newest three are dry
        for k, c in enumerate(classes):
            self.db.execute("INSERT INTO jumps (ts, id64, star_class, kind) VALUES (?, ?, ?, 'FSDJump')", (f"2026-01-01T00:{k:02d}:00Z", k, c))
        self.db.execute("INSERT INTO jumps (ts, id64, star_class, kind) VALUES ('2026-01-01T01:00:00Z', 50, NULL, 'FSDJump')")      # a journal gap
        self.db.execute("INSERT INTO jumps (ts, id64, star_class, kind) VALUES ('2026-01-01T01:01:00Z', 51, 'K', 'CarrierJump')")   # the carrier's
        self.assertEqual(self.state.scoop_rate(), {"scoopable": 5, "of": 10, "dry_run": 3})
        self.db.execute("DELETE FROM jumps WHERE id64 < 3")
        self.assertIsNone(self.state.scoop_rate())                       # 7 known: too few to say

    def test_here_scoop_complete_and_incomplete(self):
        self.j.pos = {"id64": 9, "name": "Here", "x": 0, "y": 0, "z": 0, "ts": "2026-01-01T00:00:00Z"}
        self.state.here_star = lambda: "DA"
        recs = [{"name": "A", "type": "Star", "main": True, "scoopable": False, "dist_ls": 0},
                {"name": "B", "type": "Star", "main": False, "scoopable": True, "subtype": "K (Yellow-Orange) Star", "dist_ls": 1240.4},
                {"name": "C", "type": "Star", "main": False, "scoopable": True, "subtype": "M (Red dwarf) Star", "dist_ls": 88000},
                {"name": "A 1", "type": "Planet", "main": False, "scoopable": False, "dist_ls": 12}]
        self.state.merged_records = lambda i: {"records": recs}
        self.assertEqual(self.state.here_scoop(), {"name": "B", "subtype": "K (Yellow-Orange) Star", "dist_ls": 1240, "complete": False})
        self.state.scan_version += 1                                     # every body found: now complete
        self.db.execute("INSERT INTO own_systems VALUES (9, 'Here', 4, 1)")
        recs[1]["scoopable"] = recs[2]["scoopable"] = False
        self.assertEqual(self.state.here_scoop(), {"name": None, "subtype": None, "dist_ls": None, "complete": True})
        self.state.scan_version += 1                                     # Spansh knows 6 bodies, 4 records here: not complete
        self.db.execute("DELETE FROM own_systems")
        self.state.bases[9] = ("spansh", {"body_count": 6})
        self.assertFalse(self.state.here_scoop()["complete"])
        self.state.here_star = lambda: "K"                               # the arrival star scoops: nothing to find
        self.assertIsNone(self.state.here_scoop())

    def test_target_hop(self):
        self.j.pos = {"id64": 9, "name": "Here", "x": 0, "y": 0, "z": 0, "ts": "2026-01-01T00:00:00Z"}
        self.db.execute("INSERT INTO route_systems VALUES (77, 'Next', 38.2, 0, 0, 'K', 'x')")
        t = {"id64": 77, "name": "Next"}
        self.assertEqual(self.state.target_hop(t), {"ly": 38.2, "fuel": None, "left": None, "reach": None})   # no model yet
        self.j.ship = dict(self.MANDALAY, fuel_main=32.0)
        self.j.fuel_hist = [list(x) for x in self.MANDALAY_JUMPS]
        self.j.status_json = {"live": True, "fuel_main": 32.0, "cargo": 0}
        h = self.state.target_hop(t)
        self.assertAlmostEqual(h["fuel"], 0.91, delta=0.01)
        self.assertEqual((h["left"], h["reach"]), (5, True))
        self.db.execute("UPDATE route_systems SET x = 95 WHERE id64 = 77")   # past the laden range
        self.assertEqual(self.state.target_hop(t)["reach"], False)
        self.j.boost = {"value": 4.0, "ts": "x"}                         # a neutron charge reaches it
        self.assertTrue(self.state.target_hop(t)["reach"])


class BatchEExobio(unittest.TestCase):
    """Batch E: the run in progress elsewhere (P5), per-run x5 pricing and the sale check (P8), the region crossing
    (P10) and the jumponium call-out (P17)."""

    STRATUM = "$Codex_Ent_Stratum_07_Name;"
    TUSSOCK = "$Codex_Ent_Tussocks_01_Name;"

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    @staticmethod
    def body_scan(ts, body_id, footfalled, addr=1, system="Sys", **kw):
        ev = scan(ts, system, addr, body_id, f"{system} {body_id}")[2]
        if footfalled is not None:
            ev["WasFootfalled"] = footfalled
        ev.update(kw)
        return ev

    @staticmethod
    def organic(ts, body_id, kind, species, name, addr=1):
        genus = name.split()[0]
        return {"event": "ScanOrganic", "timestamp": ts, "SystemAddress": addr, "Body": body_id, "ScanType": kind,
                "Genus": f"$Codex_Ent_{genus}_Genus_Name;", "Genus_Localised": genus, "Species": species, "Species_Localised": name}

    # ---- P8: per-run pricing ----
    def test_per_run_pricing(self):
        ev = lambda e: (T(e["timestamp"]), None, e)
        v, _ = ed_unsold.species_value(self.STRATUM)
        sold = {"event": "SellOrganicData", "timestamp": "2026-01-01T00:00:00Z",   # 1 of 4 sold entries earned x5: 25%
                "BioData": [{"Species": self.TUSSOCK, "Value": 10, "Bonus": 40}] + [{"Species": self.TUSSOCK, "Value": 10, "Bonus": 0}] * 3}
        events = [ev(sold)] + [ev(self.body_scan("2026-01-02T00:00:00Z", b, f)) for b, f in ((1, False), (2, True), (3, None))] + \
                 [ev(self.organic(f"2026-01-03T00:0{b}:00Z", b, "Analyse", self.STRATUM, "Stratum Tectonicas")) for b in (1, 2, 3)]
        bio = ed_unsold.analyse(events, ARGS)["exobiology"]
        self.assertEqual((bio["x5_runs"], bio["x1_runs"], bio["unknown_runs"]), (1, 1, 1))
        self.assertEqual(bio["estimated_value"], int(v * 5 + v + v * (1 + 4 * 0.25)))
        self.assertEqual((bio["base_value"], bio["max_value"]), (3 * v, 15 * v))   # unchanged
        self.assertEqual({k: bio["rows"][0][k] for k in ("x5", "x1", "unknown")}, {"x5": 1, "x1": 1, "unknown": 1})
        # a rescan after your own landing says footfalled: the first scan decides
        events.insert(4, ev(self.body_scan("2026-01-02T01:00:00Z", 1, True)))
        self.assertEqual(ed_unsold.analyse(events, ARGS)["exobiology"]["x5_runs"], 1)

    # ---- P8: the sale check ----
    def sale_journal(self):
        return [self.body_scan("2026-01-01T00:00:00Z", 1, False), self.body_scan("2026-01-01T00:00:01Z", 2, False),
                self.body_scan("2026-01-01T00:00:02Z", 3, True), self.body_scan("2026-01-01T00:00:03Z", 4, None),
                self.organic("2026-01-01T01:00:00Z", 1, "Analyse", self.STRATUM, "Stratum Tectonicas"),
                self.organic("2026-01-01T01:10:00Z", 2, "Analyse", self.STRATUM, "Stratum Tectonicas"),
                self.organic("2026-01-01T01:20:00Z", 3, "Analyse", self.TUSSOCK, "Tussock Pennata"),
                self.organic("2026-01-01T01:30:00Z", 4, "Analyse", self.TUSSOCK, "Tussock Pennata"),
                {"event": "SellOrganicData", "timestamp": "2026-01-02T00:00:00Z", "BioData": [
                    {"Species": self.STRATUM, "Value": 100, "Bonus": 400}, {"Species": self.STRATUM, "Value": 100, "Bonus": 0},
                    {"Species": self.TUSSOCK, "Value": 10, "Bonus": 40}, {"Species": self.TUSSOCK, "Value": 10, "Bonus": 0}]},
                {"event": "MultiSellExplorationData", "timestamp": "2026-01-02T00:05:00Z", "TotalEarnings": 1000,
                 "BaseValue": 1000, "Bonus": 0, "Discovered": []}]

    def test_sale_check(self):
        for i, e in enumerate(self.sale_journal()):
            self.j.line_source = f"j:{i}"
            self.j.handle(e)
        row = self.db.execute("SELECT x5_check FROM sale_events WHERE kind = 'bio'").fetchone()
        want = {"sold": 4, "predicted": 2, "matched": 1, "paid": 2, "unknown": 1}
        used = {self.STRATUM.lower(): [2, 0], self.TUSSOCK.lower(): [0, 1]}
        self.assertEqual(json.loads(row[0]), dict(want, used=used))
        # the estimate is live only; the check comes back from the journals alone after a re-read
        self.db.execute("INSERT INTO sale_estimates VALUES ('2026-01-02T00:00:00Z', 'bio', 400)")
        self.db.executescript(ed_outrider.RESET_JOURNAL_DATA)
        self.j.reload()
        for i, e in enumerate(self.sale_journal()):
            self.j.line_source = f"j:{i}"
            self.j.handle(e)
        self.assertEqual(json.loads(self.db.execute("SELECT x5_check FROM sale_events WHERE kind = 'bio'").fetchone()[0]), dict(want, used=used))
        trip = self.state.ledger()["trips"][0]
        self.assertEqual(trip["x5"], want)
        self.assertEqual((trip["estimate_bio"], trip["paid_bio_estimated"]), (400, 660))
        # a death before the sale takes the runs done before it out of the prediction
        self.assertEqual(ed_outrider.sale_check(self.db, "2026-01-02T00:00:00Z", []), None)
        self.db.execute("INSERT INTO deaths VALUES ('2026-01-01T01:15:00Z', 'recover')")
        self.assertEqual(ed_outrider.sale_check(self.db, "2026-01-03T00:00:00Z", [{"Species": self.STRATUM, "Bonus": 1}]),
                         {"sold": 1, "predicted": 0, "matched": 0, "paid": 1, "unknown": 0, "used": {self.STRATUM.lower(): [0, 0]}})

    def test_sale_check_over_one_visit(self):
        # selling in three goes at one station: each later sale draws on the runs the earlier ones left
        journal = self.sale_journal()[:8]
        parts = [[{"Species": self.STRATUM, "Value": 100, "Bonus": 400}], [{"Species": self.STRATUM, "Value": 100, "Bonus": 400}],
                 [{"Species": self.TUSSOCK, "Value": 10, "Bonus": 0}, {"Species": self.TUSSOCK, "Value": 10, "Bonus": 0}]]
        for i, (t, bio) in enumerate(zip(("00:00:00", "00:00:11", "00:02:10"), parts)):
            journal.append({"event": "SellOrganicData", "timestamp": f"2026-01-02T{t}Z", "BioData": bio})
        for i, e in enumerate(journal):
            self.j.line_source = f"j:{i}"
            self.j.handle(e)
        got = [{k: c[k] for k in ("sold", "predicted", "matched", "unknown")} for c in
               (json.loads(r[0]) for r in self.db.execute("SELECT x5_check FROM sale_events WHERE kind = 'bio' ORDER BY ts"))]
        self.assertEqual(got, [{"sold": 1, "predicted": 1, "matched": 1, "unknown": 0}, {"sold": 1, "predicted": 1, "matched": 1, "unknown": 0},
                               {"sold": 2, "predicted": 0, "matched": 0, "unknown": 1}])

    def test_old_sale_events_gain_the_column(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.sqlite")
        try:
            old = sqlite3.connect(path)
            old.executescript("""CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE sale_events (ts TEXT, kind TEXT, base INTEGER, bonus INTEGER, total INTEGER, systems INTEGER,
                                          species INTEGER, source TEXT, PRIMARY KEY (ts, kind, source));
                CREATE TABLE sale_estimates (ts TEXT, kind TEXT, estimate INTEGER, PRIMARY KEY (ts, kind));
                INSERT INTO meta VALUES ('parser_version', '30');
                INSERT INTO sale_events VALUES ('2026-01-02T00:00:00Z', 'bio', 1, 0, 1, 0, 1, 'j:1');
                INSERT INTO sale_estimates VALUES ('2026-01-02T00:00:00Z', 'bio', 2);""")
            old.commit()
            old.close()
            db = ed_outrider.open_db(path)   # PARSER_VERSION 31: the sales are re-read to gain their check
            try:
                self.assertIn("x5_check", [r["name"] for r in db.execute("PRAGMA table_info(sale_events)")])
                self.assertEqual(db.execute("SELECT count(*) FROM sale_events").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT estimate FROM sale_estimates").fetchone()[0], 2)   # live only: kept
            finally:
                db.close()
        finally:
            if os.path.exists(path):
                os.remove(path)

    # ---- P5: the run in progress elsewhere ----
    def test_run_elsewhere_and_discard_card(self):
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 1, "StarPos": [0, 0, 0]})
        for b in (4, 5):
            self.j.handle(self.body_scan("2026-01-01T00:01:00Z", b, False))
        self.j.handle(self.organic("2026-01-01T00:10:00Z", 4, "Log", self.TUSSOCK, "Tussock Pennata"))
        self.j.handle(self.organic("2026-01-01T00:12:00Z", 4, "Sample", self.TUSSOCK, "Tussock Pennata"))
        self.j.status_json = {"live": True, "ts": "2026-01-01T00:20:00Z", "fuel_main": 10, "flags": 0, "flags2": 1,
                              "body": "Sys 5", "lat": 0.0, "lon": 0.0, "planet_radius": 1_000_000}
        e = self.state.sampling_summary()["elsewhere"]
        self.assertEqual((e["species"], e["samples"], e["body"], e["system"]), ("Tussock Pennata", 2, "4", None))
        self.assertEqual(e["value"], ed_bio.species_value("Tussock Pennata") * 5)
        # an old Log (a re-read) discards it silently; a live one leaves a card
        seq = self.j.moment_seq
        now = ed_outrider.iso_ts(time.time())
        self.j.handle(self.organic(now, 5, "Log", self.STRATUM, "Stratum Tectonicas"))
        m = [x for x in self.j.moments if x["seq"] > seq and x["kind"] == "bio_dropped"]
        self.assertEqual([(x["species"], x["body"], x["elsewhere"]) for x in m], [("Tussock Pennata", "4", False)])
        self.assertIsNone(self.db.execute("SELECT 1 FROM own_organic WHERE body_id = 4").fetchone())
        self.db.execute("INSERT INTO own_organic VALUES (1, 4, 'x', 'Bacterium', 'Bacterium Aurasus', NULL, 2, NULL, '2026-01-01T00:30:00Z')")
        seq = self.j.moment_seq
        self.j.handle(self.organic("2026-01-01T00:40:00Z", 5, "Log", self.TUSSOCK, "Tussock Pennata"))
        self.assertEqual([x for x in self.j.moments if x["seq"] > seq and x["kind"] == "bio_dropped"], [])

    # ---- P10: the region crossing ----
    def jump(self, ts, id64, z):
        self.j.handle({"event": "FSDJump", "timestamp": ts, "StarSystem": f"S{id64}", "SystemAddress": id64, "StarPos": [0, 0, z]})

    def regions(self, seq=0):
        return [(m["region"], m["spoken"], m["count"]) for m in self.j.moments if m["kind"] == "region" and m["seq"] > seq]

    def test_region_crossing_once(self):
        if not ed_bio.available():
            self.skipTest("no bio rules")
        for i, (name, region) in enumerate((("Stratum Tectonicas - Green", "Inner Orion Spur"), ("Aleoida Spica - Yellow", "Inner Orion Spur"),
                                            ("Aleoida Laminiae - Teal", "Inner Orion Spur"), ("Tussock Pennata - Red", "Inner Orion Spur"),
                                            ("Fumarole", "Inner Orion Spur"), ("Tussock Pennata - Red", "Inner Scutum-Centaurus Arm"))):
            self.db.execute("INSERT INTO codex (ts, entry_id, name, region) VALUES (?, ?, ?, ?)", (f"2025-01-01T00:00:0{i}Z", i, name, region))
        self.jump("2026-01-01T00:00:00Z", 1, 0)         # first position known: nothing (the startup Location)
        self.assertEqual(self.regions(), [])
        self.jump("2026-01-01T00:01:00Z", 2, 9000)      # into the Inner Scutum-Centaurus Arm: once
        # Stratum (no region rule) and Aleoida Laminiae; Spica cannot grow there, Tussock is logged there, Fumarole is no species
        self.assertEqual(self.regions(), [("Inner Scutum-Centaurus Arm", "the Inner Scutum-Centaurus Arm", 2)])
        self.assertEqual(self.state.region_crossed(2), {"region": "Inner Scutum-Centaurus Arm", "spoken": "the Inner Scutum-Centaurus Arm", "count": 2})
        seq = self.j.moment_seq
        cp = self.j.checkpoint()
        self.jump("2026-01-01T00:02:00Z", 3, 0)         # back and forth along the border: nothing more
        self.jump("2026-01-01T00:03:00Z", 4, 9000)
        self.assertEqual(self.regions(seq), [])
        self.assertIsNone(self.state.region_crossed(4))   # a later arrival is not the crossing
        self.j.restore(cp)                              # a rolled-back tick keeps the announced set
        self.assertIn("Inner Scutum-Centaurus Arm", self.j.regions_said)
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-02T00:00:00Z", "Commander": "X"})   # a new session
        self.jump("2026-01-02T00:01:00Z", 5, 0)
        self.assertEqual(self.regions(seq), [("Inner Orion Spur", "the Inner Orion Spur", 0)])
        self.assertEqual([ed_outrider.region_spoken(n) for n in ("Norma Arm", "The Veils", "Ryker's Hope", "Izanami", "Mare Somnia")],
                         ["the Norma Arm", "the Veils", "Ryker's Hope", "Izanami", "Mare Somnia"])

    # ---- P17: jumponium ----
    def test_jumponium_limits(self):
        short = ed_materials.jumponium_short
        c = {"carbon": 10, "germanium": 10, "arsenic": 2, "niobium": 2, "yttrium": 2, "polonium": 10, "vanadium": 10, "cadmium": 10}
        self.assertEqual(short(c), {"arsenic": 2, "yttrium": 2})    # the tie set, niobium (not scarce) left out
        self.assertEqual(short(dict(c, arsenic=3, niobium=3, yttrium=3)), {})   # 3 premium boosts: not short
        self.assertEqual(short(dict(c, cadmium=1)), {"arsenic": 2, "yttrium": 2, "cadmium": 1})   # standard at 1 too
        pick = ed_materials.jumponium_pick
        self.assertIsNone(pick([{"Name": "yttrium", "Percent": 0.8}, {"Name": "iron", "Percent": 20}], {"yttrium": 2}))   # under the floor
        self.assertEqual(pick([{"Name": "arsenic", "Percent": 1.6}, {"Name": "yttrium", "Percent": 1.3}], {"arsenic": 2, "yttrium": 1}),
                         {"material": "yttrium", "pct": 1.3})      # the scarcest held wins over a richer share
        self.assertIsNone(pick([{"Name": "arsenic", "Percent": 1.2}], {"arsenic": 2}))   # grade 2-3 floor 1.5%

    def mats_login(self, snap_ts="2026-01-01T00:00:05Z"):
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:00Z", "Commander": "X"})
        self.j.handle({"event": "Materials", "timestamp": snap_ts, "Raw": [{"Name": n, "Count": c} for n, c in (
            ("carbon", 10), ("germanium", 10), ("arsenic", 10), ("niobium", 10), ("yttrium", 10), ("polonium", 1), ("vanadium", 10), ("cadmium", 10))]})
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:01:00Z", "StarSystem": "Sys", "SystemAddress": 1, "StarPos": [0, 0, 0]})

    def rich(self, ts, body_id, pct, landable=True):
        return self.body_scan(ts, body_id, False, Landable=landable, Materials=[{"Name": "iron", "Percent": 20.0}, {"Name": "polonium", "Percent": pct}])

    def test_jumponium_fss_and_alone(self):
        self.mats_login()
        self.j.handle(self.rich("2026-01-01T00:02:00Z", 3, 1.3))
        self.j.handle(self.rich("2026-01-01T00:02:10Z", 4, 1.1))   # a lower share in the same system: silent
        self.j.handle(self.rich("2026-01-01T00:02:20Z", 5, 2.0, landable=False))   # not landable
        self.j.handle({"event": "FSSAllBodiesFound", "timestamp": "2026-01-01T00:03:00Z", "SystemName": "Sys", "SystemAddress": 1, "Count": 6})
        fss = [m for m in self.j.moments if m["kind"] == "fss_done"]
        self.assertEqual(fss[-1]["jumponium"], {"body": "3", "material": "polonium", "name": "Polonium", "pct": 1.3})
        self.assertEqual([m for m in self.j.moments if m["kind"] == "jumponium"], [])
        self.j.handle(self.rich("2026-01-01T00:04:00Z", 6, 1.8))   # richer, after the debrief: said alone
        self.assertEqual([m["jumponium"]["body"] for m in self.j.moments if m["kind"] == "jumponium"], ["6"])
        # no FSS finished in the next system: said when the FSD charges to leave
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:10:00Z", "StarSystem": "Two", "SystemAddress": 2, "StarPos": [0, 0, 5]})
        self.j.handle(self.rich("2026-01-01T00:11:00Z", 1, 1.5) | {"SystemAddress": 2, "StarSystem": "Two", "BodyName": "Two 1"})
        self.j.handle({"event": "StartJump", "timestamp": "2026-01-01T00:12:00Z", "JumpType": "Hyperspace", "StarSystem": "Three",
                       "SystemAddress": 3, "StarClass": "K"})
        said = [m for m in self.j.moments if m["kind"] == "jumponium"]
        self.assertEqual((said[-1]["system"], said[-1]["jumponium"]["body"]), (2, "1"))

    def test_jumponium_silent_when_counts_are_stale(self):
        self.mats_login(snap_ts="2025-12-31T00:00:00Z")   # the login wrote no Materials line: yesterday's counts
        self.j.handle({"event": "LoadGame", "timestamp": "2026-01-01T00:00:30Z", "Commander": "X"})
        self.j.handle(self.rich("2026-01-01T00:02:00Z", 3, 1.3))
        self.assertIsNone(self.j.jumponium)


class BatchFSpansh(unittest.TestCase):
    """Batch F: the pre-Odyssey mark (P16) and the firsts watch (P20). No network: Spansh is a fake."""

    # a thin-atmosphere rocky world as a 2019 client reported it: not landable, no signals block
    OLD = {"name": "Sys A 3", "type": "Planet", "subType": "Rocky body", "isLandable": False,
           "atmosphereType": "Thin Carbon dioxide", "surfacePressure": 0.02, "gravity": 0.12, "surfaceTemperature": 180,
           "volcanismType": "No volcanism", "distanceToArrival": 500, "bodyId": 3, "earthMasses": 0.01,
           "updateTime": "2019-06-01 10:00:00+00"}

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types_ns(cached=lambda i: (None, None)), 25)

    def rec(self, **kw):
        return ed_outrider.record_from_dump("Sys", dict(self.OLD, **kw))

    # ---- P16 ----

    def test_record_keeps_update_time_and_signals_block(self):
        self.assertEqual(ed_outrider.CACHE_VERSION, 16)   # 16: mining (Batch M4)
        r = self.rec()
        self.assertEqual((r["updated"], r["signals_known"]), ("2019-06-01 10:00:00+00", False))
        self.assertTrue(self.rec(signals={"signals": {}, "updateTime": "2019-06-01"})["signals_known"])

    def test_stale_bio_cases(self):
        self.assertTrue(ed_outrider.stale_bio_body(self.rec(), "K"))                             # the old one
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(signals={"signals": {}}), "K"))    # a signals block
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(updateTime="2023-01-05T10:00:00Z"), "K"))   # after the cutoff
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(updateTime="2022-11-29T00:00:00Z"), "K"))   # the day itself
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(isLandable=True), "K"))             # already landable
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(atmosphereType="Carbon dioxide"), "K"))   # not thin
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(atmosphereType=None), "K"))
        # the rules allow nothing on a 30 K neon world, however old the record
        self.assertFalse(ed_outrider.stale_bio_body(self.rec(atmosphereType="Thin Neon", surfaceTemperature=30, gravity=0.3), "K"))
        # your own scan replaces the Spansh record: no updated, never flagged
        own = dict(self.rec(), updated=None)
        own.pop("signals_known")
        self.assertFalse(ed_outrider.stale_bio_body(own, "K"))

    def test_summary_is_a_mark_and_values_are_unchanged(self):
        star = ed_outrider.record_from_dump("Sys", {"name": "Sys A", "type": "Star", "subType": "K (Yellow-Orange) Star",
                                                    "mainStar": True, "solarMasses": 0.8, "bodyId": 1,
                                                    "updateTime": "2019-06-01 10:00:00+00"})
        old, new = [star, self.rec()], [star, self.rec(updateTime="2023-01-05T10:00:00Z")]
        s_old, s_new = ed_outrider.summarise(old, 2, "K"), ed_outrider.summarise(new, 2, "K")
        self.assertEqual(s_old["stale_bio"]["bodies"], 1)
        self.assertEqual(s_old["stale_bio"]["reported"], "2019-06-01")
        self.assertTrue(s_old["stale_bio"]["genera_top"])
        groups = ed_outrider.stale_bio_groups(self.rec(), "K")
        vals = sorted(g["value"] or 0 for g in groups)
        self.assertEqual(s_old["stale_bio"]["up_to"], vals[len(vals) // 2])   # one genus, the median, not the best
        self.assertIsNone(s_new["stale_bio"])
        self.assertEqual((s_old["bio_potential"], s_old["est_value"]), (s_new["bio_potential"], s_new["est_value"]))
        # system_value (Nearby's value columns) counts nothing for it
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 9,
                       "StarPos": [0, 0, 0]})
        self.assertEqual(self.state.system_value(9, "Sys", old, "K"), self.state.system_value(9, "Sys", new, "K"))

    def test_here_and_left_behind_show_the_mark(self):
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "Sys", "SystemAddress": 9,
                       "StarPos": [0, 0, 0]})
        base = {"v": ed_outrider.CACHE_VERSION, "name": "Sys", "x": 0, "y": 0, "z": 0, "body_count": 2,
                "records": [self.rec(), self.rec(name="Sys A 4", bodyId=4, updateTime="2024-01-01T00:00:00Z")]}
        self.db.execute("INSERT INTO spansh_systems (id64, updated_at, summary, fetched_ts, x, y, z) VALUES (9, 'u', ?, 0, 0, 0, 0)",
                        (json.dumps(base),))
        self.state.bases[9] = ("spansh", base)
        self.state.center = {"x": 0, "y": 0, "z": 0}
        bodies = {b["name"]: b for b in self.state.system_detail(9)["bodies"]}
        self.assertTrue(bodies["A 3"]["stale_bio"])
        self.assertFalse(bodies["A 4"]["stale_bio"])
        self.assertEqual(self.state.row(9)["stale_bio"]["bodies"], 1)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T01:00:00Z", "StarSystem": "Far", "SystemAddress": 10,
                       "StarPos": [20, 0, 0]})
        left = {r["id"]: r for r in self.state.left_behind(100)["systems"]}
        self.assertEqual(left["9"]["old_data"]["bodies"], 1)
        # scanned yourself: the Spansh record is replaced, and the mark goes
        ev = scan("2026-01-01T01:10:00Z", "Sys", 9, 3, "Sys A 3", disc=True)[2]
        self.j.handle(dict(ev, event="Scan", StarSystem="Sys"))
        self.db.commit()
        self.state.scan_version += 1
        left = {r["id"]: r for r in self.state.left_behind(100)["systems"]}
        self.assertIsNone((left.get("9") or {}).get("old_data"))

    # ---- P20 ----

    # a fixture dump in Spansh's layout: your three discoveries (A, A 1 and A 2), one body you never scanned
    def dump(self, a1_time, a2_time="2026-01-01T00:02:00Z", extra=None):
        bodies = [{"name": "Sys A", "type": "Star", "subType": "K (Yellow-Orange) Star", "bodyId": 1,
                   "updateTime": "2026-01-01T00:00:10Z"},
                  {"name": "Sys A 1", "type": "Planet", "subType": "Icy body", "bodyId": 2, "updateTime": a1_time},
                  {"name": "Sys A 2", "type": "Planet", "subType": "Icy body", "bodyId": 3, "updateTime": a2_time},
                  {"name": "Sys A belt cluster", "type": "Barycentre", "updateTime": "2026-02-01T00:00:00Z"}]
        return {"system": {"name": "Sys", "id64": 9, "bodyCount": 4, "date": "2026-02-01T00:00:00Z",
                           "bodies": bodies + (extra or [])}}

    def records(self, d):
        return [ed_outrider.record_from_dump("Sys", b) for b in d["system"]["bodies"] if b["type"] in ("Star", "Planet")]

    MINE = {"A": ["2026-01-01T00:00:10Z"], "A 1": ["2026-01-01T00:01:00Z", "2026-01-01T00:05:00Z"],
            "A 2": ["2026-01-01T00:02:00Z"]}

    def test_own_uploads_are_not_someone_else(self):
        # EDDN stamps an upload with the journal's time: every update matches one of your own scans or the map
        self.assertIsNone(ed_outrider.firsts_reported(self.records(self.dump("2026-01-01T00:05:00Z")), self.MINE, 4))
        self.assertIsNone(ed_outrider.firsts_reported(self.records(self.dump("2026-01-01T00:06:30Z")), self.MINE, 4))   # grace

    def test_someone_else_later(self):
        d = self.dump("2026-01-09T12:00:00Z", "2026-01-08T00:00:00Z",
                      extra=[{"name": "Sys B", "type": "Star", "subType": "M (Red dwarf) Star", "bodyId": 5,
                              "updateTime": "2026-01-07T00:00:00Z"}])   # a body you never discovered: not counted
        got = ed_outrider.firsts_reported(self.records(d), self.MINE, 4)
        self.assertEqual(got, {"reported_ts": "2026-01-08T00:00:00Z", "bodies": 2, "spansh_bodies": 4, "body_count": 4})
        # Spansh's other time format reads the same
        d2 = self.dump("2026-01-09 12:00:00+00")
        self.assertEqual(ed_outrider.firsts_reported(self.records(d2), self.MINE, None)["reported_ts"], "2026-01-09T12:00:00Z")

    def test_snapshot_and_unknown_times_do_not_count(self):
        # updated before your scan: in the snapshot when you arrived; no time at all: cannot tell
        self.assertIsNone(ed_outrider.firsts_reported(self.records(self.dump("2025-12-01T00:00:00Z")), self.MINE, 4))
        d = self.dump(None)
        self.assertIsNone(ed_outrider.firsts_reported(self.records(d), self.MINE, 4))
        self.assertIsNone(ed_outrider.firsts_reported([], self.MINE, 4))   # Spansh has nothing: nobody reported

    def discover(self, id64, name, t0, x=0):
        self.j.handle({"event": "FSDJump", "timestamp": t0, "StarSystem": name, "SystemAddress": id64, "StarPos": [x, 0, 0]})
        self.j.handle(scan(t0[:-3] + "10Z", name, id64, 1, f"{name} A", star=True)[2])
        self.j.handle(scan(t0[:-6] + "01:00Z", name, id64, 2, f"{name} A 1")[2])
        self.j.handle(scan(t0[:-6] + "02:00Z", name, id64, 3, f"{name} A 2")[2])
        self.db.commit()

    def fake(self, dumps):
        calls = []

        class FakeSpansh(ed_outrider.Spansh):
            async def lookup(self, id64, interactive=True):
                calls.append((id64, interactive))
                return dumps.get(id64)
        return FakeSpansh(self.db), calls

    def test_watch_step_most_valuable_first_once_a_day(self):
        import asyncio
        self.discover(9, "Sys", "2026-01-01T00:00:00Z")
        self.discover(8, "Cheap", "2026-01-02T00:00:00Z", x=5)
        self.state.system_values = {"Sys": 5_000_000, "Cheap": 100}
        cheap = self.dump("2026-01-02T00:01:00Z", "2026-01-02T00:02:00Z")
        for b in cheap["system"]["bodies"]:
            b["name"] = b["name"].replace("Sys", "Cheap")
        sp, calls = self.fake({9: self.dump("2026-01-09T12:00:00Z"), 8: cheap})
        self.state.spansh = sp
        now = ed_outrider.ts_seconds("2026-01-10T00:00:00Z")
        got = asyncio.run(self.state.firsts_watch_step(now))
        self.assertEqual(calls, [(9, False)])                  # the valuable one first, on the bulk lane
        self.assertEqual(got["reported_ts"], "2026-01-09T12:00:00Z")
        self.assertIsNone(asyncio.run(self.state.firsts_watch_step(now + 20)))   # Cheap: your own upload
        self.assertEqual(calls, [(9, False), (8, False)])
        self.assertIsNone(asyncio.run(self.state.firsts_watch_step(now + 40)))   # nothing due until tomorrow
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.db.execute("SELECT * FROM spansh_systems").fetchone())   # never cached: not stored
        seen = {x["name"]: x["seen"] for x in self.state.firsts_list()}
        self.assertEqual(seen["Sys"], {"reported_ts": "2026-01-09T12:00:00Z", "days": 8, "bodies": 1,
                                       "spansh_bodies": 3, "body_count": 4})
        self.assertIsNone(seen["Cheap"])
        # the watch is off here, but what it found still counts on the Unsold tile
        self.assertEqual(self.state.firsts_watch_info(), {"on": False, "seen": 1, "checked": 2, "of": 2})

    def test_watch_info_and_reports_stay(self):
        import asyncio
        self.discover(9, "Sys", "2026-01-01T00:00:00Z")
        self.state.system_values = {"Sys": 5_000_000}
        self.state.firsts_watch_on = True
        self.assertEqual(self.state.firsts_watch_info(), {"on": True, "seen": 0, "checked": 0, "of": 1})
        sp, calls = self.fake({9: self.dump("2026-01-09T12:00:00Z")})
        self.state.spansh = sp
        now = ed_outrider.ts_seconds("2026-01-10T00:00:00Z")
        asyncio.run(self.state.firsts_watch_step(now))
        self.assertEqual(self.state.firsts_watch_info(), {"on": True, "seen": 1, "checked": 1, "of": 1})
        self.assertEqual(self.state.payload()["firsts_watch"]["seen"], 1)
        # seen by others: not due again for a week; then Spansh answers without it (a glitch): the first sighting stays
        sp2, calls2 = self.fake({9: None})
        self.state.spansh = sp2
        self.assertIsNone(asyncio.run(self.state.firsts_watch_step(now + 86400)))
        self.assertEqual(calls2, [])
        later = now + ed_outrider.FIRSTS_WATCH_SLOW
        asyncio.run(self.state.firsts_watch_step(later))
        row = self.db.execute("SELECT * FROM firsts_watch WHERE id64=9").fetchone()
        self.assertEqual((row["reported_ts"], row["checked_ts"]), ("2026-01-09T12:00:00Z", later))
        self.state.firsts_watch_on = False
        self.assertEqual(self.state.firsts_watch_info()["seen"], 1)   # off: what was found still shows

    def test_watch_gap_slows_for_old_or_seen_firsts(self):
        gap, day = ed_outrider.firsts_watch_gap, 86400
        t0 = ed_outrider.ts_seconds("2026-01-01T00:00:10Z")
        row = {"first_ts": "2026-01-01T00:00:10Z", "reported_ts": None}
        self.assertEqual(gap(row, t0 + 10 * day), ed_outrider.FIRSTS_WATCH_EVERY)           # young: daily
        self.assertEqual(gap(row, t0 + 31 * day), ed_outrider.FIRSTS_WATCH_SLOW)            # a month on: weekly
        self.assertEqual(gap(dict(row, reported_ts="2026-01-02T00:00:00Z"), t0 + day), ed_outrider.FIRSTS_WATCH_SLOW)
        self.assertEqual(gap({"first_ts": None, "reported_ts": None}, t0), ed_outrider.FIRSTS_WATCH_EVERY)

    def test_watch_daily_cap(self):
        self.discover(9, "Sys", "2026-01-01T00:00:00Z")
        self.state.system_values = {"Sys": 5_000_000}
        now = ed_outrider.ts_seconds("2026-01-10T00:00:00Z")
        self.assertEqual(self.state.firsts_watch_due(now), (9, "Sys"))
        cap = ed_outrider.FIRSTS_WATCH_DAY_CAP
        self.db.executemany("INSERT INTO firsts_watch VALUES (?, ?, NULL, 0, 0, 0, NULL)",
                            [(1000 + i, now - 3600) for i in range(cap)])   # other systems checked in the last hour
        self.assertIsNone(self.state.firsts_watch_due(now))                  # the day's checks are used up
        self.assertEqual(self.state.firsts_watch_due(now + 86400), (9, "Sys"))   # a day on they have aged out

    def test_watch_uses_a_fresh_cache_and_refreshes_a_stale_one(self):
        import asyncio
        self.discover(9, "Sys", "2026-01-01T00:00:00Z")
        sp, calls = self.fake({9: self.dump("2026-01-09T12:00:00Z")})
        self.state.spansh = sp
        base = {"v": ed_outrider.CACHE_VERSION, "name": "Sys", "x": 0, "y": 0, "z": 0, "body_count": 4,
                "records": self.records(self.dump("2026-01-01T00:01:00Z"))}
        sp.store(9, "u1", base)   # fetched just now, with your own upload only
        got = asyncio.run(self.state.firsts_watch_step())
        self.assertIsNone(got)
        self.assertEqual(calls, [])                              # no request: the cache is under a day old
        self.db.execute("UPDATE spansh_systems SET fetched_ts = ?", (time.time() - 2 * 86400,))
        self.db.execute("UPDATE firsts_watch SET checked_ts = 0")
        got = asyncio.run(self.state.firsts_watch_step())
        self.assertEqual(calls, [(9, False)])
        self.assertEqual(got["bodies"], 1)
        self.assertEqual(sp.cached(9)[1]["records"][1]["updated"], "2026-01-09T12:00:00Z")   # Nearby's cache refreshed too

    def test_watch_table_survives_a_journal_reread_and_goes_in_the_backup(self):
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.sqlite")
            db = ed_outrider.open_db(path)
            db.execute("INSERT INTO firsts_watch VALUES (9, 1.5, '2026-01-09T12:00:00Z', 2, 3, 4, '2026-01-01T00:00:10Z')")
            db.commit(); db.close()
            db = ed_outrider.open_db(path, rescan=True)   # the journal re-read (also what a PARSER_VERSION bump does)
            try:
                self.assertEqual(tuple(db.execute("SELECT * FROM firsts_watch").fetchone()),
                                 (9, 1.5, "2026-01-09T12:00:00Z", 2, 3, 4, "2026-01-01T00:00:10Z"))
                self.assertNotIn("firsts_watch", ed_outrider.RESET_JOURNAL_DATA)
                state = ed_outrider.State(db, ed_outrider.Journals(db), types_ns(cached=lambda i: (None, None)), 25)
                state.db_path = path
                out = os.path.join(d, "backups")
                with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                        unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", []):
                    res = state.make_backup()
                with zipfile.ZipFile(res["path"]) as z:
                    z.extract("w.sqlite", os.path.join(d, "x"))
                copy = sqlite3.connect(os.path.join(d, "x", "w.sqlite"))
                self.assertEqual(copy.execute("SELECT reported_ts FROM firsts_watch").fetchone()[0], "2026-01-09T12:00:00Z")
                copy.close()
            finally:
                db.close()

    def test_config_switch(self):
        import tomllib
        st = ed_outrider.settings_from({}, argparse.Namespace(journals=None, legacy=None, host=None, port=None,
                                                               radius=None, db=None))
        self.assertIs(st["watch_firsts"], True)
        st = ed_outrider.settings_from({"spansh": {"watch_firsts": False}},
                                       argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None))
        self.assertIs(st["watch_firsts"], False)
        self.assertIs(tomllib.loads(ed_outrider.config_text(st))["spansh"]["watch_firsts"], False)
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ed_outrider.toml.example")) as f:
            self.assertIn("watch_firsts", f.read())

    def test_your_own_later_visit_is_not_someone_else(self):
        # found on the real journals: a jump back in two days later updated the arrival star on Spansh (EDDN)
        d = self.dump("2026-01-01T00:01:00Z")
        d["system"]["bodies"][0]["updateTime"] = "2026-01-03T03:09:50Z"
        self.assertIsNone(ed_outrider.firsts_reported(self.records(d), self.MINE, 4, ["2026-01-03T03:09:50Z"]))
        self.assertEqual(ed_outrider.firsts_reported(self.records(d), self.MINE, 4, ["2026-01-02T00:00:00Z"])["bodies"], 1)
        # and the watch passes your arrivals in: a revisit leaves the system unflagged
        import asyncio
        self.discover(9, "Sys", "2026-01-01T00:00:00Z")
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-02T00:00:00Z", "StarSystem": "Elsewhere", "SystemAddress": 7,
                       "StarPos": [9, 0, 0]})
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-03T03:09:50Z", "StarSystem": "Sys", "SystemAddress": 9,
                       "StarPos": [0, 0, 0]})
        self.db.commit()
        sp, calls = self.fake({9: d})
        self.state.spansh = sp
        self.assertIsNone(asyncio.run(self.state.firsts_watch_step(ed_outrider.ts_seconds("2026-01-10T00:00:00Z"))))
        self.assertEqual(calls, [(9, False)])


class BatchGHonkBackups(unittest.TestCase):
    """Batch G: auto honk's combat-mode and fire-group safety (P7, unit tests only: fake honkers, no device, no
    keys), and verified backups with --restore / --list-backups (P19, temp files only)."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)

    @staticmethod
    def now_ts():
        import datetime as _dt
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def live(self, **kw):
        return dict({"live": True, "ts": self.now_ts(), "flags": 1 << 4 | 1 << 27, "gui_focus": 0, "fire_group": 0}, **kw)

    # ---- P7 ----
    def test_read_status_keeps_the_fire_group(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Status.json"), "w") as f:
                json.dump({"timestamp": self.now_ts(), "Flags": 1 << 27, "Flags2": 0, "FireGroup": 2, "GuiFocus": 0,
                           "Fuel": {"FuelMain": 8.0, "FuelReservoir": 0.5}}, f)
            self.j.read_status(d)
        self.assertEqual((self.j.status_json["fire_group"], ed_outrider.fire_group_letter(2)), (2, "C"))
        self.assertIsNone(ed_outrider.fire_group_letter(None))
        self.assertIsNone(ed_outrider.fire_group_letter(True))

    def test_honk_decision_combat_mode_and_groups(self):
        d, t = ed_outrider.honk_decision, time.time()
        self.assertEqual(d(self.live(), t), ("press", None))
        # combat mode: Primary Fire would fire the weapons
        self.assertEqual(d(self.live(flags=1 << 4), t), ("wait", "the HUD is in combat mode"))
        self.assertEqual(d(self.live(flags=1 << 4 | 1 << 30), t), ("wait", "still in the jump"))
        self.assertEqual(d(self.live(flags=1 << 4, gui_focus=6), t), ("wait", "the galaxy map is open"))
        self.assertEqual(d(self.live(flags=None), t), ("press", None))           # no flags at all: as before
        groups = {"good": ["A"], "bad": ["C"]}
        self.assertEqual(d(self.live(fire_group=2), t, groups),
                         ("wait", "fire group C selected; honks missed there before (worked on A)"))
        self.assertEqual(d(self.live(fire_group=2), t, {"good": [], "bad": ["C"]}),
                         ("wait", "fire group C selected; honks missed there before"))
        self.assertEqual(d(self.live(fire_group=1), t, groups), ("press", None))   # unknown group: still pressed
        self.assertEqual(d(self.live(fire_group=0), t, groups), ("press", None))
        self.assertEqual(d(self.live(fire_group=2), t), ("press", None))            # nothing learned for this ship
        # a stale reading presses, whatever it says
        self.assertEqual(d(self.live(fire_group=2, flags=1 << 4), t + 120, groups), ("press", None))
        self.assertEqual(d(dict(self.live(fire_group=2), live=False), t, groups), ("press", None))

    def test_honk_learn(self):
        learn = ed_outrider.honk_learn
        self.assertEqual(learn(None, "A", True), {"good": ["A"], "bad": []})
        self.assertEqual(learn({"good": ["A"], "bad": []}, "C", False), {"good": ["A"], "bad": ["C"]})
        self.assertEqual(learn({"good": ["A"], "bad": []}, "A", False), {"good": ["A"], "bad": []})   # worked there before
        self.assertEqual(learn({"good": ["A"], "bad": ["C"]}, "C", True), {"good": ["A", "C"], "bad": []})   # a success clears it
        self.assertEqual(learn({"good": ["A"], "bad": []}, None, False), {"good": ["A"], "bad": []})

    def honk(self, id64, answers, status, ship_id=7, during=None):
        """One auto-honk arrival with a fake honker (no device, no keys): the presses, and the honk moment."""
        import asyncio
        j, presses, now_ts = self.j, [], self.now_ts

        class FakeHonker:
            ready, available, status = True, True, "ready"

            def press(self):
                presses.append(id64)
                if during:
                    j.status_json = dict(j.status_json, **during)
                if answers:
                    j.last_honk = {"id64": id64, "ts": now_ts(), "bodies": 5, "progress": 0.3}
                return True
        self.j.ship = {"name": "Ship", "type": "dolphin", "ship_id": ship_id}
        self.state.honker = FakeHonker()
        self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0)
        self.state.honk_confirm = 0.2
        self.j.handle({"event": "FSDJump", "timestamp": now_ts(), "StarSystem": f"S{id64}", "SystemAddress": id64,
                       "StarPos": [id64, 0, 0]})
        self.j.ship = {"name": "Ship", "type": "dolphin", "ship_id": ship_id}
        self.j.status_json = status

        async def go():
            self.state.maybe_honk()
            await asyncio.sleep(0.6)
        asyncio.run(go())
        honks = [m for m in self.state.moments_summary() if m["kind"] == "honk" and m["system"] == f"S{id64}"]
        return presses, honks[-1] if honks else None

    def test_fire_groups_learned_from_auto_honk_presses(self):
        # a confirmed press in group A: good
        presses, m = self.honk(101, True, self.live(fire_group=0))
        self.assertEqual((presses, m["ok"]), ([101], True))
        self.assertEqual(self.state.honk_groups(), {"good": ["A"], "bad": []})
        # a miss in group C with the cockpit focused and analysis mode on: bad, and the message names the group
        presses, m = self.honk(102, False, self.live(fire_group=2))
        self.assertEqual(presses, [102])
        self.assertEqual(m["why"], "no discovery scan followed with fire group C selected: is the D-Scanner on primary fire there?")
        self.assertEqual(self.state.honk_groups(), {"good": ["A"], "bad": ["C"]})
        self.state.honker.combo = lambda: (["KEY_K"], "K")
        self.assertEqual(self.state.autohonk_info()["groups"], {"good": ["A"], "bad": ["C"]})
        # a miss explained by a screen opening during the press is not held against the group
        presses, m = self.honk(103, False, self.live(fire_group=1), during={"gui_focus": 6})
        self.assertEqual(m["why"], "no discovery scan followed with fire group B selected: the galaxy map is open")
        self.assertEqual(self.state.honk_groups(), {"good": ["A"], "bad": ["C"]})
        # a miss with no fresh status names no group and learns nothing
        stale = self.live(fire_group=1, ts="2020-01-01T00:00:00Z")
        presses, m = self.honk(104, False, stale)
        self.assertEqual(m["why"], "no discovery scan followed: is the D-Scanner on primary fire?")
        self.assertEqual(self.state.honk_groups(), {"good": ["A"], "bad": ["C"]})
        # another ship has its own record: group C is not held against it
        presses, m = self.honk(105, True, self.live(fire_group=2), ship_id=8)
        self.assertEqual(presses, [105])
        self.assertEqual(self.state.honk_groups(8), {"good": ["C"], "bad": []})
        self.assertEqual(self.state.honk_groups(7), {"good": ["A"], "bad": ["C"]})
        # back in ship 7 with C selected: it waits, and a switch to A releases the press
        import asyncio
        self.j.ship = {"name": "Ship", "type": "dolphin", "ship_id": 7}
        presses = []

        class FakeHonker:
            ready, available, status = True, True, "ready"

            def press(self):
                presses.append(1)
                return True
        self.state.honker = FakeHonker()
        self.j.handle({"event": "FSDJump", "timestamp": self.now_ts(), "StarSystem": "S106", "SystemAddress": 106,
                       "StarPos": [106, 0, 0]})
        self.j.ship = {"name": "Ship", "type": "dolphin", "ship_id": 7}
        self.j.status_json = self.live(fire_group=2)

        async def go():
            self.state.maybe_honk()
            await asyncio.sleep(0.5)
            waiting = (list(presses), self.state.honker.status)
            self.j.status_json = self.live(fire_group=0)
            await asyncio.sleep(0.8)
            return waiting
        waiting = asyncio.run(go())
        self.assertEqual(waiting, ([], "waiting: fire group C selected; honks missed there before (worked on A)"))
        self.assertEqual(presses, [1])

    def test_combat_mode_waits_then_gives_up(self):
        import asyncio
        presses = []

        class FakeHonker:
            ready, available, status = True, True, "ready"

            def press(self):
                presses.append(1)
                return True
        self.state.honker = FakeHonker()
        self.state.autohonk = dict(ed_outrider.AUTOHONK, enabled=True, delay=0)
        self.j.handle({"event": "FSDJump", "timestamp": self.now_ts(), "StarSystem": "S111", "SystemAddress": 111,
                       "StarPos": [1, 0, 0]})
        self.j.status_json = self.live(flags=1 << 4)

        async def go():
            with unittest.mock.patch.object(ed_outrider, "AUTOHONK_WAIT_MAX", 0.4):
                self.state.maybe_honk()
                await asyncio.sleep(0.2)
                status = self.state.honker.status
                await asyncio.sleep(0.6)
                return status
        self.assertEqual(asyncio.run(go()), "waiting: the HUD is in combat mode")
        self.assertEqual(presses, [])
        m = [m for m in self.state.moments_summary() if m["kind"] == "honk"][-1]
        self.assertEqual((m["ok"], m["why"]), (False, "gave up waiting: the HUD is in combat mode"))
        self.assertIsNone(self.state.honk_groups())   # never pressed: nothing learned

    def test_forget_fire_groups(self):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer
        self.j.ship = {"name": "Ship", "type": "dolphin", "ship_id": 7}
        self.state.note_honk_group(7, "A", True)
        self.state.note_honk_group(7, "C", False)
        self.state.note_honk_group(8, "B", True)

        async def go():   # the test client only: no auto honk, no device (forget touches the meta record alone)
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                r = await c.post("/api/autohonk/forget")
                return r.status, await r.json()
        status, body = asyncio.run(go())
        self.assertEqual((status, body["groups"]), (200, None))
        self.assertIsNone(self.state.honk_groups(7))
        self.assertEqual(self.state.honk_groups(8), {"good": ["B"], "bad": []})   # other ships keep theirs

    def test_page_names_the_group(self):
        with open(os.path.join(os.path.dirname(ed_outrider.__file__), "static", "page.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("Is the discovery scanner on primary fire in fire group ${honkGroup(m.why)}?", js)
        self.assertIn("api/autohonk/forget", js)

    # ---- P19 ----
    def make_db(self, path, rows=50):
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        con.execute("CREATE INDEX t_v ON t (v)")
        con.executemany("INSERT INTO t (v) VALUES (?)", [(f"row {i} " + "x" * 200,) for i in range(rows)])
        con.commit()
        con.close()

    def backup_env(self, d):
        live, out = os.path.join(d, "live"), os.path.join(d, "backups")
        os.makedirs(live); os.makedirs(out)
        dbp = os.path.join(d, "x.sqlite")
        self.make_db(dbp)
        self.state.db_path = dbp
        self.state.speech_path = self.state.config_path = None
        return live, out, dbp

    def test_backup_is_verified(self):
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            live, out, dbp = self.backup_env(d)
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]):
                res = self.state.make_backup()
            self.assertTrue(res["verified"])
            self.assertIsNone(ed_outrider.check_zip(res["path"]))
            with zipfile.ZipFile(res["path"]) as z:
                self.assertIsNone(z.testzip())

    def test_corrupt_copy_fails_and_keeps_older_zips(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            live, out, dbp = self.backup_env(d)
            older = []
            for i in range(1, 3):
                older.append(f"outrider-x-2020010{i}-000000Z.zip")
                with open(os.path.join(out, older[-1]), "w") as f:
                    f.write("old")
            real = ed_outrider.copy_database

            def corrupting(src, dst, **kw):   # the copy goes through, then its pages are overwritten
                real(src, dst, **kw)
                path = dst.execute("PRAGMA database_list").fetchone()[2]
                size = os.path.getsize(path)
                with open(path, "r+b") as f:
                    f.seek(24)
                    f.write(b"\x7f\x7f\x7f\x7f")   # a new change counter: the connection re-reads the pages
                    f.seek(size // 4096 // 2 * 4096 if size > 8192 else 4096)
                    f.write(b"\xde\xad" * 2048)
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 1), \
                    unittest.mock.patch.object(ed_outrider, "copy_database", corrupting):
                with self.assertRaises(Exception) as e:
                    self.state.make_backup()
            self.assertRegex(str(e.exception), "check|malformed|corrupt")
            self.assertEqual(sorted(os.listdir(out)), older)   # nothing rotated, no bad zip, no temp copy left

    def test_bad_zip_is_deleted_and_nothing_rotates(self):
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            live, out, dbp = self.backup_env(d)
            with open(os.path.join(out, "outrider-x-20200101-000000Z.zip"), "w") as f:
                f.write("old")
            with unittest.mock.patch.object(ed_outrider, "BACKUP_DIR", out), \
                    unittest.mock.patch.object(ed_outrider, "LIVE_DIRS", [live]), \
                    unittest.mock.patch.object(ed_outrider, "BACKUP_KEEP", 1), \
                    unittest.mock.patch.object(zipfile.ZipFile, "testzip", return_value="x.sqlite"):
                with self.assertRaisesRegex(RuntimeError, "the zip failed its check: x.sqlite is damaged"):
                    self.state.make_backup()
            self.assertEqual(os.listdir(out), ["outrider-x-20200101-000000Z.zip"])

    def make_zip(self, d, name="outrider-x-20260101-000000Z.zip", rows=10, defaults=None):
        import zipfile
        src = os.path.join(d, f"src-{name}.sqlite")
        self.make_db(src, rows)
        path = os.path.join(d, "backups", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(src, "x.sqlite")
            if defaults is not None:
                z.writestr("browser_defaults.json", json.dumps(defaults))
            z.writestr("speech.json", "{}")
        return path

    def test_restore(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            dbp = os.path.join(d, "x.sqlite")
            self.make_db(dbp, 3)
            with open(dbp + "-journal", "w") as f:
                f.write("left over")
            defaults = ed_outrider.browser_defaults_path(dbp)
            ed_outrider.write_browser_defaults(defaults, {"version": 1, "settings": {"sound": False}})
            z = self.make_zip(d, rows=10, defaults={"version": 1, "settings": {"sound": True}})
            lines = ed_outrider.restore_backup(z, dbp, "127.0.0.1", 0, now=0)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(0))
            con = sqlite3.connect(dbp)
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 10)
            con.close()
            aside = f"{dbp}.pre-restore-{stamp}"
            self.assertFalse(os.path.exists(dbp + "-journal"))
            self.assertTrue(os.path.exists(aside + "-journal"))   # went with the old file (before SQLite opens it)
            con = sqlite3.connect(aside)
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 3)   # the old one kept
            con.close()
            with open(defaults) as f:
                self.assertEqual(json.load(f)["settings"], {"sound": True})
            with open(f"{defaults}.pre-restore-{stamp}") as f:
                self.assertEqual(json.load(f)["settings"], {"sound": False})
            self.assertTrue(lines[0].startswith(f"restored {dbp} from {z}"))
            self.assertIn("also in the zip, not restored: speech.json", lines[-1])
            self.assertFalse([f for f in os.listdir(d) if f.endswith(".part")])

    def test_restore_refuses_while_the_port_is_bound(self):
        import socket, tempfile
        with tempfile.TemporaryDirectory() as d, socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            port = sock.getsockname()[1]
            dbp = os.path.join(d, "x.sqlite")
            self.make_db(dbp, 3)
            z = self.make_zip(d)
            with self.assertRaisesRegex(RuntimeError, f"port {port} is in use"):
                ed_outrider.restore_backup(z, dbp, "127.0.0.1", port)
            self.assertEqual(sorted(os.listdir(d)), ["backups", "src-outrider-x-20260101-000000Z.zip.sqlite", "x.sqlite"])

    def test_restore_refuses_a_bad_zip_or_database(self):
        import tempfile, zipfile
        with tempfile.TemporaryDirectory() as d:
            dbp = os.path.join(d, "x.sqlite")
            self.make_db(dbp, 3)
            os.makedirs(os.path.join(d, "backups"))
            junk = os.path.join(d, "backups", "outrider-x-20260101-000000Z.zip")
            with open(junk, "w") as f:
                f.write("not a zip")
            with self.assertRaisesRegex(RuntimeError, "failed its check"):
                ed_outrider.restore_backup(junk, dbp, "127.0.0.1", 0)
            with zipfile.ZipFile(junk, "w") as z:
                z.writestr("x.sqlite", b"SQLite format 3\x00" + b"\x00" * 200)
            with self.assertRaisesRegex(RuntimeError, "the database in .* failed its check"):
                ed_outrider.restore_backup(junk, dbp, "127.0.0.1", 0)
            self.assertEqual(sorted(os.listdir(d)), ["backups", "x.sqlite"])   # untouched, no temp file left

    def test_list_backups_and_cli(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            z1 = self.make_zip(d, "outrider-x-20260101-000000Z.zip", rows=4)
            self.make_zip(d, "outrider-x-20260102-000000Z.zip", rows=6)
            self.make_zip(d, "outrider-other-20260103-000000Z.zip")
            out = os.path.join(d, "backups")
            lines = ed_outrider.list_backups(out, os.path.join(d, "x.sqlite"))
            self.assertEqual([l.split()[0] for l in lines], ["outrider-x-20260101-000000Z.zip", "outrider-x-20260102-000000Z.zip"])
            self.assertIn(" MB ", lines[0])
            self.assertEqual(ed_outrider.list_backups(os.path.join(d, "none"), "x.sqlite")[0][:11], "no backups:")
            cfg = os.path.join(d, "t.toml")
            with open(cfg, "w") as f:
                f.write(f'[server]\nbackup_dir = "{out}"\n')
            dbp = os.path.join(d, "x.sqlite")
            got = self.cli(["--config", cfg, "--db", dbp, "--list-backups"])
            self.assertEqual(len(got.stdout.strip().splitlines()), 2)
            got = self.cli(["--config", cfg, "--db", dbp, "--restore"])   # no zip named: the newest of this database's
            self.assertEqual(got.returncode, 0, got.stderr)
            con = sqlite3.connect(dbp)
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 6)
            con.close()
            got = self.cli(["--config", cfg, "--db", dbp, "--restore", os.path.basename(z1)])   # a bare name, found in backup_dir
            self.assertEqual(got.returncode, 0, got.stderr)
            con = sqlite3.connect(dbp)
            self.assertEqual(con.execute("SELECT count(*) FROM t").fetchone()[0], 4)
            con.close()
            self.assertEqual(len([f for f in os.listdir(d) if ".pre-restore-" in f]), 1)   # the first had no database to move
            got = self.cli(["--config", cfg, "--db", dbp, "--restore", "nope.zip"])
            self.assertEqual(got.returncode, 1)
            self.assertIn("not restored:", got.stderr)

    @staticmethod
    def cli(args):
        """ed_outrider.py in a subprocess on a free scratch port: these flags exit before any server starts."""
        import socket, subprocess
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        return subprocess.run([sys.executable, ed_outrider.__file__, "--port", str(port), "--host", "127.0.0.1"] + args,
                              capture_output=True, text=True, timeout=60)

    def test_help_and_readme_name_the_flags(self):
        out = self.cli(["--help"]).stdout
        self.assertIn("--restore", out)
        self.assertIn("--list-backups", out)
        with open(os.path.join(os.path.dirname(ed_outrider.__file__), "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn("--restore", readme)
        self.assertIn("--list-backups", readme)


class MiningLocations(unittest.TestCase):
    """Batch M4: planetary mining locations in Here, with the EDFM survey's odds as a tooltip."""

    MINE = "$PlanetaryMiningLocation_Name;"

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.j.handle({"event": "FSDJump", "timestamp": "2026-01-01T00:00:00Z", "StarSystem": "S1", "SystemAddress": 1,
                       "StarPos": [0, 0, 0]})

    def body(self, name, cls="Rocky body", volcanism=""):
        ev = scan("2026-01-01T00:01:00Z", "S1", 1, sum(map(ord, name)), f"S1 {name}")[2]
        ev.update(PlanetClass=cls, Volcanism=volcanism, Landable=True)
        self.j.handle(ev)

    def detail(self, name):
        self.db.commit()
        return next(b for b in self.state.system_detail(1)["bodies"] if b["name"] == name)

    def test_count_from_fss_and_dss(self):
        self.body("A 1", "Icy body")
        self.body("A 2", "Metal rich body")
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyID": 3,
                       "BodyName": "S1 A 1", "Signals": [
                           {"Type": self.MINE, "Type_Localised": "Planetary Mining Location", "Count": 4},
                           {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 2}]})
        self.j.handle({"event": "SAASignalsFound", "timestamp": "2026-01-01T00:03:00Z", "SystemAddress": 1, "BodyID": 3,
                       "BodyName": "S1 A 2", "Signals": [
                           {"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 7},
                           {"Type": self.MINE, "Type_Localised": "Planetary Mining Location", "Count": 19}],
                       "Genuses": []})
        a1, a2 = self.detail("A 1"), self.detail("A 2")
        self.assertEqual((a1["mining"], a1["geo"], a2["mining"], a2["bio"]), (4, 2, 19, 7))
        self.assertEqual(a1["mining_odds"]["ground"], "icy")
        self.assertEqual(a2["mining_odds"]["ground"], "metal-rich")

    def test_no_count_no_tooltip(self):
        self.body("A 1", "Icy body")
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyID": 3,
                       "BodyName": "S1 A 1", "Signals": [{"Type": "$SAA_SignalType_Geological;", "Count": 2}]})
        b = self.detail("A 1")
        self.assertEqual((b["mining"], b["mining_odds"]), (0, None))

    def test_ground_classification(self):
        g = ed_outrider.mining_ground
        self.assertEqual(g("Metal-rich body", None), "metal-rich")
        self.assertEqual(g("High metal content world", "major rocky magma volcanism"), "high-metal-content")
        self.assertEqual(g("Rocky Ice world", ""), "rocky-ice")
        self.assertEqual(g("Icy body", "water geysers volcanism"), "icy")
        self.assertEqual(g("Rocky body", ""), "rocky")
        self.assertEqual(g("Rocky body", None), "rocky")
        self.assertEqual(g("Rocky body", "carbon dioxide geysers volcanism"), "rocky")
        self.assertEqual(g("Rocky body", "minor metallic magma volcanism"), "volcanic magma")
        self.assertEqual(g("Rocky body", "Rocky Magma"), "volcanic magma")          # Spansh's wording
        self.assertEqual(g("Rocky body", "major silicate vapour geysers volcanism"), "volcanic silicate")
        self.assertEqual(g("Rocky body", "Silicate Vapour Geysers"), "volcanic silicate")
        self.assertIsNone(g("Water world", ""))
        self.assertIsNone(g("Class I gas giant", None))
        # a scan's journal class is normalised to these names on the record
        self.body("B 1", "Rocky ice body")
        self.j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyID": 3,
                       "BodyName": "S1 B 1", "Signals": [{"Type": self.MINE, "Count": 3}]})
        self.assertEqual(self.detail("B 1")["mining_odds"]["ground"], "rocky-ice")

    def test_odds_file_loads(self):
        with open(ed_outrider.MINING_ODDS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        self.assertIn("CC BY-SA 4.0", raw["_note"]["license"])
        self.assertIn("edfieldmanual.com", raw["_note"]["source"])
        self.assertEqual(raw["attribution"]["researcher"], "CMDR Grumlop")
        odds = ed_outrider.load_mining_odds()
        self.assertEqual(set(odds), {"metal-rich", "high-metal-content", "rocky-ice", "rocky", "icy",
                                     "volcanic magma", "volcanic silicate"})
        for e in odds.values():
            pcts = [p for _, p in e["materials"]]
            self.assertEqual(pcts, sorted(pcts, reverse=True))
        self.assertEqual(ed_outrider.load_mining_odds("/nonexistent/mining_odds.json"), {})

    def test_odds_for_one_ground(self):
        o = ed_outrider.mining_odds("volcanic magma")
        self.assertEqual((o["surveyed"], o["few"]), (57, False))
        self.assertEqual([m["name"] for m in o["top"][:4]], ["Olivine", "Monazite", "Bastnasite", "Alexandrite"])
        self.assertEqual(o["top"][0]["pct"], 56.1)
        self.assertEqual((len(o["top"]), o["more"]), (ed_outrider.MINING_TOP, True))
        icy = ed_outrider.mining_odds("icy")
        self.assertEqual(icy["surveyed"], 124)
        self.assertEqual(icy["top"][0]["name"], "Deuterium")
        self.assertTrue(ed_outrider.mining_odds("rocky-ice")["few"])      # 14 locations surveyed
        self.assertIsNone(ed_outrider.mining_odds(None))
        self.assertIsNone(ed_outrider.mining_odds("gas giant"))

    def test_spansh_count_for_unscanned_and_scanned_bodies(self):
        dump = {"name": "S1 A 3", "type": "Planet", "subType": "Rocky body", "volcanismType": "Silicate Vapour Geysers",
                "signals": {"signals": {self.MINE: 12}, "updateTime": "2026-09-28T03:16:00Z"}}
        r = ed_outrider.record_from_dump("S1", dump)
        self.assertEqual(r["mining"], 12)
        self.assertEqual(ed_outrider.mining_ground(r["subtype"], r["volcanism"]), "volcanic silicate")
        # your scan without an FSS signal count takes Spansh's
        own = {"A 3": {"name": "A 3", "subtype": "Rocky body", "bio": 0, "geo": 0, "rings": []}}
        merged = ed_outrider.merge_records([r], own, {})
        self.assertEqual(merged[0]["mining"], 12)

    def test_old_database_gets_the_column(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.sqlite")
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE own_signals (system INTEGER, name TEXT, bio INTEGER, geo INTEGER, ts TEXT, "
                        "PRIMARY KEY (system, name))")
            con.commit()
            con.close()
            db = ed_outrider.open_db(path)
            self.addCleanup(db.close)
            self.assertIn("mining", {r["name"] for r in db.execute("PRAGMA table_info(own_signals)")})
            j = ed_outrider.Journals(db)
            j.handle({"event": "FSSBodySignals", "timestamp": "2026-01-01T00:02:00Z", "SystemAddress": 1, "BodyID": 3,
                      "BodyName": "S1 A 1", "Signals": [{"Type": self.MINE, "Count": 5}]})
            self.assertEqual(db.execute("SELECT mining FROM own_signals").fetchone()[0], 5)



class MinedPreviously(unittest.TestCase):
    """Batch M4b: what the SRV's refinery collected on each body (MiningRefined, 1 t each), rebuilt by a re-read."""

    SYS = 18207037532889

    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)

    @staticmethod
    def session(t0="2026-09-30T03:00:"):
        """A login, a Rhino on body 19 (3 refined, docked), then relaunched on body 12 (2 refined)."""
        sys_ = MinedPreviously.SYS
        n = iter(range(10, 60))
        t = lambda: f"{t0}{next(n):02d}Z"
        body = lambda ev, bid, **kw: dict({"event": ev, "timestamp": t(), "StarSystem": "Smojooe AR-E b25-8",
                                           "SystemAddress": sys_, "Body": f"B {bid}", "BodyID": bid}, **kw)
        refine = lambda kind, loc: {"event": "MiningRefined", "timestamp": t(), "Type": f"${kind};", "Type_Localised": loc}
        return [
            {"event": "LoadGame", "timestamp": t(), "Commander": "X", "Ship": "Explorer_NX"},
            {"event": "Location", "timestamp": t(), "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": sys_,
             "StarPos": [0, 0, 0], "Docked": True, "StationName": "G0X-85Z", "StationType": "FleetCarrier"},
            body("ApproachBody", 19), body("SupercruiseExit", 19, BodyType="Planet"),
            {"event": "LaunchSRV", "timestamp": t(), "SRVType": "mev_rhino", "ID": 51, "PlayerControlled": True},
            refine("water_name", "Water"), refine("water_name", "Water"),
            refine("methanolmonohydratecrystals_name", "Methanol Monohydrate Crystals"),
            {"event": "DockSRV", "timestamp": t(), "SRVType": "mev_rhino", "ID": 51},
            refine("water_name", "Water"),                     # the ship's own refinery (no SRV out): not counted
            body("LeaveBody", 19), body("ApproachBody", 12), body("Touchdown", 12, PlayerControlled=True),
            {"event": "LaunchSRV", "timestamp": t(), "SRVType": "mev_rhino", "ID": 51, "PlayerControlled": True},
            refine("gold_name", "Gold"), refine("gold_name", "Gold"),
            {"event": "DockSRV", "timestamp": t(), "SRVType": "mev_rhino", "ID": 51},
        ]

    def mined(self, db=None):
        return {(r["body_id"], r["name"]): (r["tons"], r["first_ts"], r["last_ts"]) for r in
                (db or self.db).execute("SELECT * FROM own_mined WHERE system=?", (self.SYS,))}

    def test_launch_refine_dock_relaunch_on_another_body(self):
        for ev in self.session():
            self.j.handle(ev)
        got = self.mined()
        self.assertEqual({k: v[0] for k, v in got.items()},
                         {(19, "Water"): 2, (19, "Methanol Monohydrate Crystals"): 1, (12, "Gold"): 2})
        self.assertEqual(got[(19, "Water")][1:], ("2026-09-30T03:00:15Z", "2026-09-30T03:00:16Z"))
        self.assertIsNone(self.j.srv_state[""]["srv"])       # docked

    def test_refined_with_no_known_body_is_ignored(self):
        ts = iter(f"2026-09-30T04:00:{i:02d}Z" for i in range(10, 60))
        # a ring: the ship's refinery
        self.j.handle({"event": "MiningRefined", "timestamp": next(ts), "Type": "$painite_name;", "Type_Localised": "Painite"})
        # an SRV launched with no body known (the journals began mid-session)
        self.j.handle({"event": "LaunchSRV", "timestamp": next(ts), "SRVType": "mev_rhino"})
        self.j.handle({"event": "MiningRefined", "timestamp": next(ts), "Type": "$water_name;", "Type_Localised": "Water"})
        # at a station, not a planet
        self.j.handle({"event": "SupercruiseExit", "timestamp": next(ts), "SystemAddress": 5, "Body": "Port", "BodyID": 40,
                       "BodyType": "Station"})
        self.j.handle({"event": "LaunchSRV", "timestamp": next(ts), "SRVType": "mev_rhino"})
        self.j.handle({"event": "MiningRefined", "timestamp": next(ts), "Type": "$water_name;"})
        # on a body, but supercruise in between ends the SRV
        self.j.handle({"event": "Touchdown", "timestamp": next(ts), "SystemAddress": 5, "Body": "P", "BodyID": 7})
        self.j.handle({"event": "LaunchSRV", "timestamp": next(ts), "SRVType": "mev_rhino"})
        self.j.handle({"event": "SupercruiseEntry", "timestamp": next(ts), "SystemAddress": 5})
        self.j.handle({"event": "MiningRefined", "timestamp": next(ts), "Type": "$water_name;"})
        self.assertEqual(self.db.execute("SELECT count(*) FROM own_mined").fetchone()[0], 0)

    def test_login_in_the_srv(self):
        self.j.handle({"event": "LoadGame", "timestamp": "2026-09-19T15:48:00Z", "Commander": "X", "Ship": "Lander01"})
        self.j.handle({"event": "Location", "timestamp": "2026-09-19T15:49:04Z", "InSRV": True, "StarSystem": "Scaulae",
                       "SystemAddress": 8, "StarPos": [0, 0, 0], "Body": "Scaulae 8 g", "BodyID": 29, "BodyType": "Planet"})
        self.j.handle({"event": "MiningRefined", "timestamp": "2026-09-19T15:50:00Z", "Type": "$gold_name;",
                       "Type_Localised": "Gold"})
        self.assertEqual(self.db.execute("SELECT system, body_id, tons FROM own_mined").fetchall()[0][:], (8, 29, 1))

    def write_journals(self, d):
        """Two sessions in two files: the second's lines must not borrow the first's SRV."""
        first = self.session()
        second = [{"event": "MiningRefined", "timestamp": "2026-09-30T05:00:00Z", "Type": "$gold_name;",
                   "Type_Localised": "Gold"}]   # no LoadGame, no body: an SRV the journals never saw launched
        # the first session leaves an SRV out when its journal ends (a crash): drop its last DockSRV
        first = first[:-1]
        for name, evs in (("Journal.2026-09-30T030000.01.log", first), ("Journal.2026-09-30T045900.01.log", second)):
            with open(os.path.join(d, name), "w") as f:
                f.write("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in evs))   # the game writes "event":"X"

    def test_a_reread_gives_the_same_totals(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            jdir = os.path.join(d, "j"); os.mkdir(jdir)
            self.write_journals(jdir)
            path = os.path.join(d, "m.sqlite")
            db = ed_outrider.open_db(path)
            ed_outrider.Journals(db).scan_dir(jdir)
            db.commit()
            before = self.mined(db)
            self.assertEqual({k: v[0] for k, v in before.items()},
                             {(19, "Water"): 2, (19, "Methanol Monohydrate Crystals"): 1, (12, "Gold"): 2})
            # the same file read again (a line handled twice) adds nothing: offsets, and the source guard
            j = ed_outrider.Journals(db)
            j.line_source = "Journal.2026-09-30T030000.01.log:999"
            j.srv_state[j.session_key()] = {"at": None, "srv": {"system": self.SYS, "body_id": 12, "ts": ""}}
            ev = {"event": "MiningRefined", "timestamp": "2026-09-30T03:01:00Z", "Type": "$gold_name;", "Type_Localised": "Gold"}
            j.handle(ev); j.handle(ev)
            self.assertEqual(self.mined(db)[(12, "Gold")][0], 3)
            db.close()
            db = ed_outrider.open_db(path, rescan=True)
            self.addCleanup(db.close)
            self.assertEqual(db.execute("SELECT count(*) FROM own_mined").fetchone()[0], 0)
            self.assertIsNone(ed_outrider.meta_get(db, "srv_state"))
            ed_outrider.Journals(db).scan_dir(jdir)
            db.commit()
            self.assertEqual(self.mined(db), before)

    def test_session_key_drops_the_part_number(self):
        self.j.line_source = "Journal.2026-09-30T023726.02.log:12345"
        self.assertEqual(self.j.session_key(), "Journal.2026-09-30T023726")
        self.j.line_source = ""
        self.assertEqual(self.j.session_key(), "")

    def test_payload(self):
        import types
        state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        for ev in self.session():
            self.j.handle(ev)
        for bid in (19, 12):
            self.j.handle(dict(scan("2026-09-30T03:01:00Z", "Smojooe AR-E b25-8", self.SYS, bid,
                                    f"Smojooe AR-E b25-8 B {bid}")[2], PlanetClass="Icy body", Landable=True))
        self.db.commit()
        bodies = {b["name"]: b for b in state.system_detail(self.SYS)["bodies"]}
        self.assertEqual(bodies["B 19"]["mined"], [
            {"name": "Water", "tons": 2, "last": "2026-09-30T03:00:16Z"},
            {"name": "Methanol Monohydrate Crystals", "tons": 1, "last": "2026-09-30T03:00:17Z"}])
        self.assertEqual([m["tons"] for m in bodies["B 12"]["mined"]], [2])
        self.assertEqual(bodies["B 12"]["mining"], 0)        # mined history with no survey count still shows

class SaleLeft(unittest.TestCase):
    """A sale that leaves data aboard: said once the pages stop and a fresh estimate has run, live sales only."""

    def setUp(self):
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.base = time.time()

    def at(self, s, ev):
        """Handle ev as a journal line read s seconds after the test's start (its timestamp then too)."""
        with unittest.mock.patch.object(ed_outrider.time, "time", lambda: self.base + s):
            self.j.handle(dict(ev, timestamp=ed_outrider.iso_ts(self.base + s)))

    def page(self, s, systems, earned):
        self.at(s, {"event": "MultiSellExplorationData", "TotalEarnings": earned, "BaseValue": earned, "Bonus": 0,
                    "Discovered": [{"SystemName": f"S{i}", "NumBodies": 3} for i in range(systems)]})

    def estimate(self, started, systems=0, payout=0, firsts=0, samples=0, bio=0):
        self.state.unsold = {"carto": {"systems": systems, "estimated_payout": payout, "first_discoveries": firsts},
                             "bio": {"samples": samples, "estimated_value": bio}}
        self.state.unsold_from = self.base + started

    def kinds(self):
        return [m for m in self.j.moments if m["kind"] in ("sale_left", "bio_left")]

    def test_one_page_with_data_left(self):
        self.estimate(-30, 93, 16800000, 300)            # before the sale: it cannot say what the sale left
        self.page(0, 50, 14814687)
        self.state.maybe_sale_left(self.base + 5)
        self.state.maybe_sale_left(self.base + 12)       # quiet long enough, but no estimate since the page
        self.assertEqual(self.kinds(), [])
        self.estimate(3, 43, 2026392, 270)
        self.state.maybe_sale_left(self.base + 20)
        m = self.kinds()
        self.assertEqual(len(m), 1)
        self.assertEqual({k: m[0][k] for k in ("kind", "sold_systems", "sold_value", "left_systems", "left_value", "left_firsts")},
                         {"kind": "sale_left", "sold_systems": 50, "sold_value": 14814687, "left_systems": 43,
                          "left_value": 2026392, "left_firsts": 270})
        self.assertIsNone(self.j.sale_run)
        self.state.maybe_sale_left(self.base + 40)       # said once
        self.assertEqual(len(self.kinds()), 1)

    def test_three_pages_all_sold(self):
        self.page(0, 50, 14000000)
        self.estimate(1, 60, 9000000, 100)               # between pages: data left, but the sale is still going
        self.state.maybe_sale_left(self.base + 3)
        self.page(4, 50, 9000000)
        self.estimate(5, 10, 1000000, 20)
        self.state.maybe_sale_left(self.base + 7)
        self.page(8, 10, 1000000)
        self.state.maybe_sale_left(self.base + 12)       # the page-2 estimate is older than the last page
        self.state.maybe_sale_left(self.base + 19)
        self.assertEqual(self.kinds(), [])
        self.assertEqual((self.j.sale_run["systems"], self.j.sale_run["carto"]), (110, 24000000))
        self.estimate(10)                                # everything sold
        self.state.maybe_sale_left(self.base + 25)
        self.assertEqual(self.kinds(), [])
        self.assertIsNone(self.j.sale_run)

    def test_three_pages_with_data_left_counts_the_whole_sale(self):
        for s in (0, 3, 6):
            self.page(s, 50, 5000000)
        self.estimate(8, 43, 2000000, 270)
        self.state.maybe_sale_left(self.base + 20)
        m = self.kinds()
        self.assertEqual([(x["sold_systems"], x["sold_value"], x["left_systems"]) for x in m], [(150, 15000000, 43)])

    def test_replayed_sale_says_nothing(self):
        self.j.handle({"event": "MultiSellExplorationData", "timestamp": "2026-01-01T01:00:00Z", "TotalEarnings": 5000,
                       "Discovered": [{"SystemName": "Sys", "NumBodies": 3}]})
        self.assertIsNone(self.j.sale_run)
        self.estimate(10, 43, 2000000, 270)
        self.state.maybe_sale_left(self.base + 60)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.j.last_sale["carto"], 5000)   # the sale itself still counts

    def test_bio_left(self):
        self.at(0, {"event": "SellOrganicData", "BioData": [{"Value": 1000000, "Bonus": 4000000}] * 3})
        self.estimate(2, 40, 3000000, 10, samples=2, bio=30000000)
        self.state.maybe_sale_left(self.base + 20)
        m = self.kinds()
        self.assertEqual([(x["kind"], x["sold_species"], x["sold_value"], x["left_samples"], x["left_value"]) for x in m],
                         [("bio_left", 3, 15000000, 2, 30000000)])   # cartographics aboard: not this sale's news

    def test_carto_sale_says_nothing_of_bio(self):
        self.page(0, 20, 3000000)
        self.estimate(2, samples=4, bio=50000000)
        self.state.maybe_sale_left(self.base + 20)
        self.assertEqual(self.kinds(), [])

    def test_failed_tick_does_not_double_the_run(self):
        self.page(0, 50, 1000)
        cp = self.j.checkpoint()
        self.page(2, 50, 1000)
        self.j.restore(cp)
        self.assertEqual(self.j.sale_run["systems"], 50)


class SurfaceRigs(unittest.TestCase):
    """Batch M1: the surface map's server side: rigs marked by the co-pilot button in the Rhino, collections placed
    from Status.json, the ship marker, the vehicle, mining location markers, the leash and the payload block."""

    SYS, BODY, NAME, R = 18207037532889, 19, "Smojooe AR-E b25-8 ABC 3 d", 1_000_000.0
    SRV = 1 << 26

    def setUp(self):
        import tempfile
        import types
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))
        self.base = time.time()
        self.line = 0
        self.ev(0, {"event": "Location", "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": self.SYS, "StarPos": [0, 0, 0],
                    "Docked": True, "StationType": "FleetCarrier"})
        self.ev(1, {"event": "SupercruiseExit", "StarSystem": "Smojooe AR-E b25-8", "SystemAddress": self.SYS,
                    "Body": self.NAME, "BodyID": self.BODY, "BodyType": "Planet"})

    def ts(self, s):
        return ed_outrider.iso_ts(self.base + s)

    def ev(self, s, ev):
        """A journal line read s seconds into the test (its timestamp then too), as a live line."""
        self.line += 1
        self.j.line_source = f"Journal.2026-09-30T030000.01.log:{self.line}"
        with unittest.mock.patch.object(ed_outrider.time, "time", lambda: self.base + s):
            self.j.handle(dict(ev, timestamp=self.ts(s)))
        self.j.line_source = ""

    def status(self, s, north=0.0, east=0.0, heading=0, flags=None, alt=0, flags2=0, **kw):
        """Status.json at s seconds, `north`/`east` metres from lat 0, lon 0 (read the way the tick reads it)."""
        k = 180 / math.pi / self.R
        st = {"timestamp": self.ts(s), "event": "Status", "Flags": self.SRV if flags is None else flags, "Flags2": flags2,
              "Latitude": north * k, "Longitude": east * k, "Heading": heading, "Altitude": alt,
              "BodyName": self.NAME, "PlanetRadius": self.R, **kw}
        with open(os.path.join(self.dir, "Status.json"), "w") as f:
            json.dump(st, f)
        self.j.read_status(self.dir)

    def launch(self, s=2, srv="mev_rhino"):
        self.ev(s, {"event": "LaunchSRV", "SRVType": srv, "ID": 51, "PlayerControlled": True})

    def texts(self, kinds=("rig", "rig_leash")):
        return [m["text"] for m in self.j.moments if m["kind"] in kinds]

    def refine(self, s, what="Water", n=1):
        for i in range(n):
            self.ev(s + i, {"event": "MiningRefined", "Type": f"${what.lower()}_name;", "Type_Localised": what})

    def out(self):
        return {r["n"]: r for r in self.state.rigs_out(self.SYS, self.BODY)}

    def test_presses_place_1_2_3_and_a_tap_by_one_picks_it_up(self):
        self.launch()
        self.status(10, 0, 0, heading=0)
        self.assertEqual(self.state.mark_rig(self.base + 10)["n"], 1)
        rig = self.out()[1]   # 7 m behind the cockpit: heading north, so 7 m south
        self.assertAlmostEqual(ed_outrider.surface_m(0, 0, rig["lat"], rig["lon"], self.R), 7.0, places=2)
        self.assertLess(rig["lat"], 0)
        self.status(20, 100, 0, heading=90)
        self.state.mark_rig(self.base + 20)
        self.status(30, 200, 0, heading=90)
        self.state.mark_rig(self.base + 30)
        self.assertEqual(sorted(self.out()), [1, 2, 3])
        self.state.mark_rig(self.base + 35)          # the same spot again: rig 3 is within 5 m, so it is picked up
        self.assertEqual(sorted(self.out()), [1, 2])
        self.assertEqual(self.texts(), ["Rig 1 placed.", "Rig 2 placed.", "Rig 3 placed.", "Rig 3 picked up."])
        self.assertEqual(self.db.execute("SELECT count(*) FROM surface_rigs").fetchone()[0], 2)   # an empty rig is forgotten

    def test_the_lowest_free_number_after_a_pickup(self):
        self.launch()
        for i, north in enumerate((0, 100, 200)):
            self.status(10 + i, north, 0, heading=0)
            self.state.mark_rig(self.base + 10 + i)
        self.status(20, 100 - 5, 0, heading=90)      # drive over rig 2 (7 m south of where you pressed): 2 m off
        self.assertEqual(self.state.mark_rig(self.base + 20)["what"], "picked")
        self.status(30, 400, 0, heading=0)
        self.assertEqual(self.state.mark_rig(self.base + 30)["n"], 2)
        self.status(40, 600, 0, heading=0)
        self.assertEqual(self.state.mark_rig(self.base + 40)["n"], 4)

    def test_six_out_refuses(self):
        self.launch()
        for i in range(7):
            self.status(10 + i, 100 * i, 0)
            self.state.mark_rig(self.base + 10 + i)
        self.assertEqual(sorted(self.out()), [1, 2, 3, 4, 5, 6])
        self.assertEqual(self.texts()[-1], "Six rigs out.")

    def test_the_button_does_nothing_else_in_the_rhino(self):
        self.launch()
        self.status(10)
        for g in ("status", "again", "hush"):
            self.state.copilot_gesture(g)
        self.assertEqual(self.state.copilot["seq"], 0)       # no status report, say again...
        self.assertIsNone(self.state.hush)                    # ...or hush
        self.assertEqual(self.texts(), ["Rig 1 placed.", "Rig 1 picked up.", "Rig 1 placed."])
        # outside the Rhino (on foot, in the ship, in a Scarab) the button works as before
        self.status(20, flags=1 << 3)                         # landed, in the ship: the in-SRV flag gone
        self.state.watch_surface(self.base + 20)
        self.assertIsNone(self.j.vehicle)
        self.state.copilot_gesture("status")
        self.state.copilot_gesture("hush")
        self.assertEqual((self.state.copilot["seq"], self.state.copilot["action"]), (2, "hush"))
        self.assertIsNotNone(self.state.hush)
        self.launch(30, "testbuggy")
        self.status(31)
        self.state.copilot_gesture("again")
        self.assertEqual(self.state.copilot["action"], "again")
        self.assertEqual(len(self.texts()), 3)
        # the page's own requests (the Now bar) never mark rigs, even in the Rhino
        self.launch(40)
        self.status(41, 300)
        self.state.copilot_action("status")
        self.assertEqual(self.state.copilot["action"], "status")
        self.assertEqual(len(self.texts()), 3)

    def test_the_button_watch_marks_rigs_through_a_stand_in_device(self):
        """The co-pilot path end to end with the stand-in evdev (never a real device): the button's tap, double tap
        and hold reach State.copilot_gesture, which in the Rhino marks rigs with each."""
        import asyncio
        import ed_button
        ev, Dev = BatchBVoiceControl.fake_evdev(self, [(0, 1), (0.02, 0), (0.25, 1), (0.02, 0), (0.03, 1), (0.02, 0),
                                                        (0.25, 1), (0.2, 0), (0.05, 2)])
        self.launch()
        self.status(10, 0, 0, heading=180)

        async def go():
            w = ed_button.ButtonWatch("X-56", "BTN_TRIGGER_HAPPY5", self.state.copilot_gesture, hold_ms=150,
                                      double_ms=100, evdev=ev)
            with unittest.mock.patch.object(ed_button, "RETRY", 5):
                t = asyncio.ensure_future(w.run())
                await asyncio.sleep(1.0)
                t.cancel()
                await asyncio.gather(t, return_exceptions=True)
        asyncio.run(go())
        self.assertEqual(self.texts(), ["Rig 1 placed.", "Rig 1 picked up.", "Rig 1 placed."])
        self.assertEqual(self.state.copilot["seq"], 0)
        self.assertIsNone(self.state.hush)

    def test_collections_add_up_on_a_rig_and_a_far_one_is_an_unmarked_site(self):
        self.launch()
        self.status(10, 0, 0, heading=180)                    # facing south: the rig lands 7 m north
        self.state.mark_rig(self.base + 10)
        self.status(100, 9, 0, heading=0)                     # over the rig, 2 m off
        self.refine(101, "Water", 11)
        self.state.watch_surface(self.base + 120)             # still going: not said yet
        self.assertEqual(self.texts()[-1], "Rig 1 placed.")
        self.state.watch_surface(self.base + 145)
        self.assertEqual(self.texts()[-1], "Rig 1: 11 tons of Water.")
        self.status(300, 7, 1)                                # a second collection three minutes later
        self.refine(301, "Water", 3)
        self.state.watch_surface(self.base + 340)
        rig = self.out()[1]
        self.assertEqual((json.loads(rig["minerals"]), rig["tons"]), ({"Water": 14}, 14))
        self.assertIsNone(rig["picked_ts"])                   # the rig stays out
        self.status(500, 0, 400)                              # 400 m away, no rig marked there
        self.refine(501, "Gold", 1)
        self.state.watch_surface(self.base + 540)
        self.assertEqual(self.texts()[-1], "1 ton of Gold. No rig marked here; site saved.")
        site = self.db.execute("SELECT * FROM surface_sites").fetchone()
        self.assertEqual((site["tons"], json.loads(site["minerals"])), (1, {"Gold": 1}))
        # own_mined counted the same tons once each (the map only says where they came from)
        self.assertEqual({r["name"]: r["tons"] for r in self.db.execute("SELECT * FROM own_mined")}, {"Water": 14, "Gold": 1})
        # a replayed (old) line places nothing
        self.j.handle({"event": "MiningRefined", "timestamp": "2026-01-01T00:00:00Z", "Type": "$water_name;", "Type_Localised": "Water"})
        self.assertEqual(self.out()[1]["tons"], 14)

    def test_a_late_ton_joins_the_collection_and_a_failed_tick_does_not_double_it(self):
        self.launch()
        self.status(10, 0, 0, heading=180)
        self.state.mark_rig(self.base + 10)
        self.status(20, 7, 0)
        self.refine(21, "Water", 2)
        self.state.watch_surface(self.base + 60)
        self.db.commit()                                     # the tick commits before a later one fails
        cp = self.j.checkpoint()
        self.refine(70, "Water", 1)                          # 48 s later: the refinery's last bin, same rig, unsaid
        self.j.restore(cp)
        self.db.rollback()
        self.refine(70, "Water", 1)
        self.state.watch_surface(self.base + 110)
        self.assertEqual(self.out()[1]["tons"], 3)
        self.assertEqual(self.texts(), ["Rig 1 placed.", "Rig 1: 2 tons of Water."])

    def test_two_rigs_collected_within_the_minute_are_two_collections(self):
        self.launch()
        for s, north in ((10, 0), (20, 80)):
            self.status(s, north, 0, heading=180)
            self.state.mark_rig(self.base + s)
        self.status(100, 7, 0)
        self.refine(101, "Water", 10)
        self.status(130, 87, 0)                               # 80 m on, 20 s after the last ton
        self.refine(131, "Water", 2)
        self.state.watch_surface(self.base + 170)
        self.assertEqual(self.texts()[-2:], ["Rig 1: 10 tons of Water.", "Rig 2: 2 tons of Water."])
        self.assertEqual({n: r["tons"] for n, r in self.out().items()}, {1: 10, 2: 2})

    def test_tables_survive_a_journal_reread(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.sqlite")
            db = ed_outrider.open_db(path)
            db.execute("INSERT INTO surface_rigs (system, body_id, n, lat, lon, placed_ts, minerals, tons) VALUES (1, 2, 1, 0, 0, 'x', '{}', 0)")
            db.execute("INSERT INTO surface_sites (system, body_id, lat, lon, minerals, tons) VALUES (1, 2, 0, 0, '{}', 3)")
            db.execute("INSERT INTO mining_locations VALUES (1, 2, 3, 'B', 0, 0, 'x')")
            ed_outrider.meta_set(db, "vehicle", {"srv_type": "mev_rhino", "ts": "x"})
            db.commit(); db.close()
            db = ed_outrider.open_db(path, rescan=True)
            self.addCleanup(db.close)
            for t in ("surface_rigs", "surface_sites", "mining_locations"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {t}").fetchone()[0], 1, t)
            self.assertIsNone(ed_outrider.meta_get(db, "vehicle"))   # journal-derived: rebuilt by the re-read
        self.assertNotIn("surface_", ed_outrider.RESET_JOURNAL_DATA)
        self.assertNotIn("mining_locations", ed_outrider.RESET_JOURNAL_DATA)

    def test_show_hide_hysteresis(self):
        show = lambda s, **kw: (self.status(s, **kw), self.state.surface_summary()["show"])[1]
        self.assertTrue(show(1, flags=0, alt=900))
        self.assertTrue(show(2, flags=0, alt=1050))           # between the two: unchanged
        self.assertFalse(show(3, flags=0, alt=1150))
        self.assertFalse(show(4, flags=0, alt=1050))          # still unchanged, from the other side
        self.assertTrue(show(5, flags=0, alt=999))
        self.assertFalse(show(6, flags=ed_outrider.FLAG_ALT_AVG, alt=500))   # altitude from the average radius
        self.assertTrue(show(7, alt=None))                    # in the SRV, no altitude
        self.assertTrue(show(8, flags=0, flags2=1, alt=None))  # on foot
        self.assertFalse(show(9, flags=0, alt=None))          # flying with no altitude
        sf = self.state.surface_summary()
        self.assertEqual((sf["down"], sf["alt_avg"]), (False, False))   # the page's own show/hide altitude reads these
        self.status(9, flags=ed_outrider.FLAG_ALT_AVG, alt=500)
        self.assertEqual((self.state.surface_summary()["down"], self.state.surface_summary()["alt_avg"]), (False, True))
        self.status(9, flags=ed_outrider.FLAG_LANDED, alt=0)
        self.assertTrue(self.state.surface_summary()["down"])
        self.status(9, flags=0, flags2=1, alt=None)
        self.assertTrue(self.state.surface_summary()["down"])
        self.status(10, flags=0, alt=500, BodyName=None)
        self.assertIsNone(self.state.surface_summary())       # no body under you: no block at all

    def test_the_map_bumps_on_5_m_or_10_degrees_twice_a_second_at_most(self):
        self.status(1, 0, 0, heading=10)
        self.assertTrue(self.state.surface_moved(100.0))
        self.status(2, 3, 0, heading=15)
        self.assertFalse(self.state.surface_moved(101.0))     # 3 m and 5 degrees
        self.status(3, 6, 0, heading=15)
        self.assertTrue(self.state.surface_moved(101.6))
        self.status(4, 12, 0, heading=15)
        self.assertFalse(self.state.surface_moved(101.9))     # 6 m more, but too soon
        self.status(4, 6, 0, heading=359)
        self.assertTrue(self.state.surface_moved(102.5))      # a 16 degree turn across north
        self.status(5, 6, 0, heading=359, flags=0, alt=5000)
        self.assertFalse(self.state.surface_moved(104.0))     # the map is hidden: no bumps

    def test_ship_marker_survives_an_srv_or_on_foot_liftoff(self):
        td = {"event": "Touchdown", "StarSystem": "S", "SystemAddress": self.SYS, "Body": self.NAME, "BodyID": self.BODY,
              "Latitude": 1.5, "Longitude": 2.5, "PlayerControlled": True}
        self.ev(10, td)
        self.assertEqual((self.j.ship_marker["lat"], self.j.ship_marker["lon"]), (1.5, 2.5))
        self.ev(20, {"event": "Liftoff", "SystemAddress": self.SYS, "BodyID": self.BODY, "Latitude": 1.5, "Longitude": 2.5,
                     "PlayerControlled": False})       # dismissed with you on foot or in the SRV
        self.assertIsNotNone(self.j.ship_marker)
        self.ev(25, dict(td, Latitude=9.0, Taxi=True))         # an Apex shuttle is not your ship
        self.assertEqual(self.j.ship_marker["lat"], 1.5)
        self.status(26, 0, 0)
        self.assertEqual(self.state.surface_summary()["ship"]["lat"], 1.5)
        self.ev(30, {"event": "Liftoff", "SystemAddress": self.SYS, "BodyID": self.BODY, "PlayerControlled": True})
        self.assertIsNone(self.j.ship_marker)
        # no Touchdown seen on this body (the 30 Sep run): the SRV's launch spot is the ship's
        self.status(40, 50, 60, flags=1 << 1)
        self.launch(41)
        self.assertAlmostEqual(self.j.ship_marker["lat"], 50 * 180 / math.pi / self.R)

    def test_vehicle_and_a_relog_in_the_srv(self):
        self.launch()
        self.assertEqual(self.j.vehicle["srv_type"], "mev_rhino")
        self.ev(10, {"event": "LoadGame", "Commander": "X", "Ship": "Explorer_NX"})
        self.ev(11, {"event": "Location", "InSRV": True, "StarSystem": "S", "SystemAddress": self.SYS, "StarPos": [0, 0, 0],
                     "Body": self.NAME, "BodyID": self.BODY, "BodyType": "Planet"})
        self.assertEqual(self.j.vehicle["srv_type"], "mev_rhino")   # the SRV launched and never docked
        self.status(12)
        self.assertTrue(self.state.in_rhino())
        self.launch(13)                                       # a relaunch read before Status.json catches up:
        self.status(13, flags=1 << 1)                         # the in-SRV flag not set yet, same second
        self.state.watch_surface(self.base + 13)
        self.assertEqual(self.j.vehicle["srv_type"], "mev_rhino")   # not taken for leaving the SRV
        self.ev(20, {"event": "DockSRV", "SRVType": "mev_rhino", "ID": 51})
        self.assertIsNone(self.j.vehicle)
        self.ev(30, {"event": "Location", "InSRV": True, "StarSystem": "S", "SystemAddress": self.SYS, "StarPos": [0, 0, 0],
                     "Body": self.NAME, "BodyID": self.BODY, "BodyType": "Planet"})
        self.assertIsNone(self.j.vehicle["srv_type"])               # an SRV of unknown type: the button is unchanged
        self.assertFalse(self.state.in_rhino())

    def test_the_leash(self):
        self.launch()
        self.status(10, 0, 0, heading=180)
        self.state.mark_rig(self.base + 10)
        for s, north in ((20, 3000), (30, 3600), (40, 3700), (50, 4600), (60, 4700)):
            self.status(s, north, 0)
            self.state.watch_surface(self.base + s)
        self.assertEqual(self.texts(("rig_leash",)), ["Rig 1 is 3.6 kilometres away; it is lost at 5.",
                                                   "Rig 1 is 4.6 kilometres away; it is lost at 5."])
        self.status(70, 2000, 0)
        self.state.watch_surface(self.base + 70)              # back in range: it may warn again
        self.status(80, 5100, 0)
        self.state.watch_surface(self.base + 80)
        self.assertEqual(self.texts(("rig_leash",))[-1], "Rig 1 lost: over 5 kilometres from the Rhino.")
        self.assertEqual(self.out(), {})
        # leaving the body loses the rigs too; one that collected keeps its site
        self.status(90, 0, 0, heading=180)
        self.state.mark_rig(self.base + 90)
        self.status(100, 7, 0)
        self.refine(101, "Gold", 2)
        self.ev(200, {"event": "LeaveBody", "StarSystem": "S", "SystemAddress": self.SYS, "Body": self.NAME, "BodyID": self.BODY})
        self.assertEqual(self.out(), {})
        self.assertEqual([(s["kind"], s["tons"]) for s in self.state.surface_sites(self.SYS, self.BODY)], [("rig", 2)])

    def test_mining_location_marker_and_sites_grouped_by_it(self):
        dest = {"System": self.SYS, "Body": self.BODY, "Name": "$SAA_Unknown_Signal:#type=$PlanetaryMiningLocation_Name;:#index=3;"}
        self.status(10, 500, 0, flags=0, alt=300, Destination=dest)
        self.state.watch_surface(self.base + 10)              # flying: not arrived
        self.assertEqual(self.db.execute("SELECT count(*) FROM mining_locations").fetchone()[0], 0)
        self.status(20, 1000, 0, flags=1 << 1, Destination=dest)   # landed with it targeted
        self.state.watch_surface(self.base + 20)
        self.launch(30)
        self.status(31, 1010, 0, heading=180, Destination=dest)
        self.state.watch_surface(self.base + 31)              # in the SRV: the landing's marker stays
        loc = self.state.surface_summary()["locations"]
        self.assertEqual([(l["n"], round(l["dist"])) for l in loc], [(3, 10)])
        self.state.mark_rig(self.base + 32)
        self.status(40, 1017, 0)
        self.refine(41, "Water", 2)
        self.state.watch_surface(self.base + 80)
        self.status(90, 1017, 0, heading=0)
        self.state.mark_rig(self.base + 90)                   # pick it up: now a saved site
        self.status(200, 9000, 0)
        self.refine(201, "Gold", 1)                           # far from L3: an unmarked site of no location
        sites = self.state.surface_sites(self.SYS, self.BODY, self.state.surface_here())
        self.assertEqual([(s["kind"], s["location"], s["tons"]) for s in sites], [("rig", 3, 2), ("site", None, 1)])
        # a location on another body is not this body's
        self.db.execute("INSERT INTO own_bodies (system, body_id, name) VALUES (?, 12, 'other')", (self.SYS,))
        self.status(110, 9000, 0, flags=1 << 1, Destination=dict(dest, Body=12, Name=dest["Name"].replace("=3", "=5")))
        self.state.watch_surface(self.base + 110)
        self.assertEqual([r[0] for r in self.db.execute("SELECT idx FROM mining_locations")], [3])

    def test_payload_block(self):
        self.ev(3, {"event": "Touchdown", "SystemAddress": self.SYS, "Body": self.NAME, "BodyID": self.BODY,
                    "Latitude": 0.0, "Longitude": 0.0, "PlayerControlled": True})
        self.launch(4)
        self.db.execute("INSERT INTO own_organic (system, body_id, species, genus_name, species_name, samples, ts) "
                        "VALUES (?, ?, 'sp_a', 'Bacterium', 'Bacterium Aurasus', 1, ?)", (self.SYS, self.BODY, self.ts(5)))
        self.db.execute("INSERT INTO own_organic (system, body_id, species, genus_name, species_name, samples, ts) "
                        "VALUES (?, ?, 'sp_b', 'Stratum', 'Stratum Tectonicas', 2, ?)", (self.SYS, self.BODY, self.ts(4)))
        k = 180 / math.pi / self.R
        self.db.execute("INSERT INTO sample_points VALUES (?, ?, 'sp_a', '$Codex_Ent_Bacterial_Genus_Name;', 1, ?, 0, ?)",
                        (self.SYS, self.BODY, 600 * k, self.ts(5)))
        self.db.execute("INSERT INTO sample_points VALUES (?, ?, 'sp_b', '$Codex_Ent_Stratum_Genus_Name;', 1, ?, 0, ?)",
                        (self.SYS, self.BODY, 100 * k, self.ts(4)))
        self.status(10, 0, 0, heading=180)
        self.state.mark_rig(self.base + 10)
        p = self.state.payload()
        sf = p["surface"]
        self.assertEqual((sf["body"], sf["body_id"], sf["heading"], sf["show"], sf["rhino"]), ("ABC 3 d", 19, 180, True, True))
        self.assertEqual(sf["ship"]["dist"], 0)
        self.assertEqual([(r["n"], r["dist"], r["tons"], r["full"]) for r in sf["rigs"]], [(1, 7, 0, False)])
        self.assertEqual([(b["species"], b["current"], b["need"], b["clear"]) for b in sf["bio"]],
                         [("Bacterium Aurasus", True, 500, True), ("Stratum Tectonicas", False, 500, False)])
        self.assertEqual(p["defaults"]["rig_spacing"], 78)
        self.assertTrue(self.state.surface_summary(now=self.base + 10 + 481)["rigs"][0]["full"])   # 8 min: probably full

    def test_mining_sites_list(self):
        """Batch M3: Materials' Mining sites, one entry per body: a rig and two unmarked sites on ABC 3 d (Water twice,
        combined), own_mined on another body only, tons never counted twice, and forget keeping the mined history."""
        self.launch()
        self.status(10, 0, 0, heading=0)
        self.state.mark_rig(self.base + 10)                       # rig 1, 7 m south
        self.status(20, -7, 0, heading=0)
        self.refine(20, "Water", 4)
        self.status(200, 500, 0)
        self.refine(200, "Methanol Monohydrate Crystals", 3)      # far from the rig: an unmarked site
        self.status(400, 1000, 0)
        self.refine(400, "Water", 2)                              # another unmarked site
        self.state.journals.end_burst(self.base + 1000, force=True)
        self.db.execute("INSERT INTO mining_locations VALUES (?, ?, 3, ?, 0, 0, 'x')", (self.SYS, self.BODY, self.NAME))
        self.db.execute("INSERT INTO mining_locations VALUES (?, 5, 1, 'elsewhere', 0, 0, 'x')", (self.SYS,))  # nothing mined
        self.db.execute("INSERT INTO own_mined VALUES (?, 7, 'gold', 'Gold', 5, ?, ?, '')", (self.SYS, self.ts(1), self.ts(1)))
        sites = {s["body_id"]: s for s in self.state.mining_sites()}
        self.assertEqual(sorted(sites), [7, self.BODY])
        abc = sites[self.BODY]
        self.assertEqual((abc["system"], abc["id"], abc["body"], abc["distance"]), ("Smojooe AR-E b25-8", str(self.SYS), "ABC 3 d", 0.0))
        self.assertEqual(abc["minerals"], [{"name": "Water", "tons": 6}, {"name": "Methanol Monohydrate Crystals", "tons": 3}])
        self.assertEqual((abc["tons"], abc["rigs"], abc["unmarked"], abc["locations"], abc["saved"]), (9, 1, 2, [3], True))
        self.assertEqual(abc["last"], self.ts(401))
        self.assertEqual((sites[7]["body"], sites[7]["minerals"], sites[7]["saved"]), ("body 7", [{"name": "Gold", "tons": 5}], False))
        self.state.forget_sites(self.SYS, self.BODY)             # the rig is still out, so it stays
        abc = {s["body_id"]: s for s in self.state.mining_sites()}[self.BODY]
        self.assertEqual((abc["tons"], abc["rigs"], abc["unmarked"], abc["locations"]), (9, 1, 0, []))
        self.state.mark_rig(self.base + 1100)                    # not by the rig: a new one (empty rigs are not sites)
        self.status(1110, -7, 0, heading=0)
        self.state.mark_rig(self.base + 1110)                    # by rig 1: picked up, kept as a saved site
        self.state.forget_sites(self.SYS, self.BODY)
        abc = {s["body_id"]: s for s in self.state.mining_sites()}[self.BODY]
        self.assertEqual((abc["tons"], abc["rigs"], abc["saved"]), (6 + 3, 0, False))   # the mined history stays

    def test_rig_restock_recipe(self):
        inv = ed_materials.inventory({"counts": {"iron": 10, "nickel": 5, "mechanicalequipment": 4}, "names": {}})
        r = next(x for x in inv["synthesis"] if x["name"] == "Mining rig restock")
        self.assertEqual((r["craftable"], r["limit"]), (2, "Nickel"))
        self.assertEqual([(m["name"], m["need"]) for m in r["materials"]], [("Iron", 3), ("Nickel", 2), ("Mechanical Equipment", 1)])
        self.assertEqual(ed_materials.MATERIALS["mechanicalequipment"], ("Mechanical Equipment", "Manufactured", 2))
        self.assertEqual(ed_materials.craftable({"iron": 30, "nickel": 20}, r and ed_materials.SYNTH["Mining rig restock"]["materials"]),
                         (0, "mechanicalequipment"))

    def test_endpoints(self):
        import asyncio
        from aiohttp.test_utils import TestClient, TestServer
        self.launch()
        self.status(10, 0, 0, heading=180)
        rid = self.state.mark_rig(self.base + 10)["id"]
        self.db.execute("INSERT INTO surface_sites (system, body_id, lat, lon, minerals, tons) VALUES (?, ?, 0, 0, '{}', 3)",
                        (self.SYS, self.BODY))
        self.db.execute("INSERT INTO mining_locations VALUES (?, ?, 1, 'B', 0, 0, 'x')", (self.SYS, self.BODY))

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                mat = await (await c.get("/api/materials")).json()
                self.assertEqual([x["unmarked"] for x in mat["mining_sites"]], [1])
                r1 = await c.post("/api/rigs/remove", json={"id": rid}, headers={"Origin": "http://evil.example"})
                r2 = await c.post("/api/rigs/remove", json={"id": "x"})
                r3 = await c.post("/api/rigs/remove", json={"id": rid})
                r4 = await c.post("/api/rigs/remove", json={"id": rid})
                r5 = await c.post("/api/sites/forget", json={"system": str(self.SYS), "body": self.BODY})
                r6 = await c.post("/api/sites/forget", json={"system": "nope"})
                return [r.status for r in (r1, r2, r3, r4, r5, r6)], await r5.json()
        statuses, forgot = asyncio.run(go())
        self.assertEqual(statuses, [403, 400, 200, 404, 200, 400])
        self.assertEqual(forgot["forgot"], 2)
        for t in ("surface_rigs", "surface_sites", "mining_locations"):
            self.assertEqual(self.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0], 0, t)

    def test_config_keys(self):
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        st = ed_outrider.settings_from({}, args, None, ([], []))
        self.assertEqual((st["surface_alt"], st["rig_spacing"], st["surface_map_min"], st["surface_map_strip"], st["rig_warn"]),
                         (1000, 78, 500, False, 3500))
        back = tomllib.loads(ed_outrider.config_text(st))["defaults"]
        self.assertEqual((back["surface_alt"], back["rig_spacing"], back["surface_map_min"], back["surface_map_strip"], back["rig_warn"]),
                         (1000, 78, 500, False, 3500))
        st = ed_outrider.settings_from({"defaults": {"rig_warn": 9000, "rig_spacing": -1}}, args, None, ([], []))
        self.assertEqual((st["rig_warn"], st["rig_spacing"]), (4900, 0))
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ed_outrider.toml.example")) as f:
            example = f.read()
        for key in ("surface_alt", "rig_spacing", "surface_map_min", "surface_map_strip", "rig_warn"):
            self.assertIn(f"# {key} = ", example)

    def test_replay_of_the_rhino_session(self):
        """The author's 30 Sep Rhino run on ABC 3 d (journal and Status.json as recorded), with the presses where the
        recording shows the rigs were placed: rig 1 at 03:10:13, rig 2 at 03:22:59, and at 03:35:21 (rig 2 still out,
        so that press is rig 3). Water 10 from rig 1; Methanol 11 + 3 + 6 from rig 2."""
        presses = {"2026-09-30T03:10:13Z", "2026-09-30T03:22:59Z", "2026-09-30T03:35:21Z"}
        t0 = ed_outrider.ts_seconds("2026-09-30T03:06:00Z")
        db = ed_outrider.open_db(":memory:")
        self.addCleanup(db.close)
        j = ed_outrider.Journals(db)
        import types
        state = ed_outrider.State(db, j, types.SimpleNamespace(cached=lambda i: (None, None)), 25)
        clock = [t0]
        with unittest.mock.patch.object(ed_outrider.time, "time", lambda: clock[0]):
            for i, line in enumerate(RHINO_SESSION):
                kind, doc = line[0], json.loads(line[2:])
                t = ed_outrider.ts_seconds(doc["timestamp"])
                while clock[0] < t:              # the watch loop's ticks in between
                    clock[0] += 1
                    state.watch_surface(clock[0])
                if kind == "S":
                    with open(os.path.join(self.dir, "Status.json"), "w") as f:
                        json.dump(doc, f)
                    j.read_status(self.dir)
                    if doc["timestamp"] in presses:
                        state.mark_rig(t)
                else:
                    j.line_source = f"Journal.2026-09-29T223726.01.log:{i}"
                    j.handle(doc)
                    j.line_source = ""
            for _ in range(90):
                clock[0] += 1
                state.watch_surface(clock[0])
        said = [m["text"] for m in j.moments if m["kind"] in ("rig", "rig_leash")]
        self.assertEqual(said, ["Rig 1 placed.", "Rig 1: 10 tons of Water.", "Rig 2 placed.",
                                "Rig 2: 11 tons of Methanol Monohydrate Crystals.",
                                "Rig 2: 3 tons of Methanol Monohydrate Crystals.", "Rig 3 placed.",
                                "Rig 2: 6 tons of Methanol Monohydrate Crystals."])
        water = [m for m in j.moments if m.get("what") == "collected"][0]
        self.assertEqual((water["lat"], water["lon"]), (-53.794037, -144.581116))   # where the Water was refined
        rigs = {r["n"]: r for r in db.execute("SELECT * FROM surface_rigs")}
        self.assertEqual({n: (json.loads(r["minerals"]), r["tons"]) for n, r in rigs.items()},
                         {1: ({"Water": 10}, 10), 2: ({"Methanol Monohydrate Crystals": 20}, 20), 3: ({}, 0)})
        self.assertEqual((rigs[1]["site_lat"], rigs[1]["site_lon"]), (-53.794037, -144.581116))
        r = 1204549.875
        self.assertLess(ed_outrider.surface_m(rigs[1]["lat"], rigs[1]["lon"], -53.794037, -144.581116, r), 10)
        self.assertLess(ed_outrider.surface_m(rigs[2]["lat"], rigs[2]["lon"], -53.868797, -144.483139, r), 1)   # 7 m behind: spot on
        self.assertEqual(db.execute("SELECT count(*) FROM surface_sites").fetchone()[0], 0)   # every collection had its rig
        # the journal's own count agrees, ton for ton
        self.assertEqual({x["name"]: x["tons"] for x in db.execute("SELECT * FROM own_mined")},
                         {"Water": 10, "Methanol Monohydrate Crystals": 20})
        self.assertIsNone(j.vehicle)                     # docked
        self.assertFalse(state.in_rhino())


# The author's Rhino run of 2026-09-30 on Smojooe AR-E b25-8 ABC 3 d: the journal lines (Journal.2026-09-29T223726.01.log)
# and the Status.json changes recorded during it (Pips, Fuel, FireGroup, LegalState and Balance left out), trimmed to the
# presses and the collections. "S " = Status.json, "J " = a journal line.
RHINO_SESSION = [
    'J {"timestamp":"2026-09-30T02:53:30Z", "event":"Location", "Docked":true, "StationName":"G0X-85Z", "StationType":"FleetCarrier", "StarSystem":"Smojooe AR-E b25-8", "SystemAddress":18207037532889, "StarPos":[-4177.09375, -1.0, 3324.53125]}',
    'J { "timestamp":"2026-09-30T03:06:20Z", "event":"SupercruiseExit", "Taxi":false, "Multicrew":false, "StarSystem":"Smojooe AR-E b25-8", "SystemAddress":18207037532889, "Body":"Smojooe AR-E b25-8 ABC 3 d", "BodyID":19, "BodyType":"Planet" }',
    'J { "timestamp":"2026-09-30T03:07:25Z", "event":"LaunchSRV", "SRVType":"mev_rhino", "SRVType_Localised":"SRV Rhino", "Loadout":"base", "ID":51, "PlayerControlled":true }',
    'S {"timestamp":"2026-09-30T03:10:13Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":0.0, "Latitude":-53.79417, "Longitude":-144.581131, "Heading":177, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:16:46Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":4, "Cargo":0.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:16:48Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":3, "Cargo":0.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:16:49Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":1, "Cargo":0.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:16:56Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'J { "timestamp":"2026-09-30T03:16:56Z", "event":"MaterialCollected", "Category":"Raw", "Name":"nickel", "Count":1 }',
    'S {"timestamp":"2026-09-30T03:16:57Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":1, "Cargo":2.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:16:57Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'J { "timestamp":"2026-09-30T03:16:58Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:16:59Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":1, "Cargo":4.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:16:59Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:00Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":4.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:17:00Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:01Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":5.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:17:02Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:02Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":6.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:17:03Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:03Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":7.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:17:04Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":8.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:17:04Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'J { "timestamp":"2026-09-30T03:17:05Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:06Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":9.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:17:07Z", "event":"MiningRefined", "Type":"$water_name;", "Type_Localised":"Water" }',
    'S {"timestamp":"2026-09-30T03:17:07Z", "event":"Status", "Flags":203456584, "Flags2":0, "GuiFocus":0, "Cargo":10.0, "Latitude":-53.794037, "Longitude":-144.581116, "Heading":176, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:22:59Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":10.0, "Latitude":-53.869118, "Longitude":-144.48291, "Heading":158, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:29:46Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":10.0, "Latitude":-53.868958, "Longitude":-144.482742, "Heading":302, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:50Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:51Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":11.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:51Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:52Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":12.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:53Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:53Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":13.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:54Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:55Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":14.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:55Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:56Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":15.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:57Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:57Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":16.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:58Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:29:59Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":17.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:29:59Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:30:00Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":18.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:30:01Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:30:02Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":19.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:30:03Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:30:03Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":20.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:30:04Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:30:05Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":21.0, "Latitude":-53.868797, "Longitude":-144.483139, "Heading":303, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:33:17Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":21.0, "Latitude":-53.868618, "Longitude":-144.483551, "Heading":310, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:33:18Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:33:19Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":22.0, "Latitude":-53.868687, "Longitude":-144.483444, "Heading":309, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:33:20Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:33:20Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":23.0, "Latitude":-53.868687, "Longitude":-144.483444, "Heading":309, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:33:21Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":24.0, "Latitude":-53.868687, "Longitude":-144.483444, "Heading":309, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:33:21Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:33:23Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":2, "Cargo":24.0, "Latitude":-53.868687, "Longitude":-144.483444, "Heading":309, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:33:28Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":24.0, "Latitude":-53.868687, "Longitude":-144.483444, "Heading":309, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:35:21Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":24.0, "Latitude":-53.869404, "Longitude":-144.481781, "Heading":323, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:29Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":24.0, "Latitude":-53.869209, "Longitude":-144.482346, "Heading":310, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:30Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":24.0, "Latitude":-53.8689, "Longitude":-144.48291, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:31Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":25.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:38:31Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'J { "timestamp":"2026-09-30T03:38:32Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:38:33Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":26.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:38:34Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:38:34Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":27.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:35Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":28.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:38:35Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'J { "timestamp":"2026-09-30T03:38:36Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:38:37Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":29.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:38:37Z", "event":"MiningRefined", "Type":"$methanolmonohydratecrystals_name;", "Type_Localised":"Methanol Monohydrate Crystals" }',
    'S {"timestamp":"2026-09-30T03:38:38Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":30.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:41Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":2, "Cargo":30.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:38:45Z", "event":"Status", "Flags":471892040, "Flags2":0, "GuiFocus":0, "Cargo":30.0, "Latitude":-53.86887, "Longitude":-144.482971, "Heading":308, "Altitude":1, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:41:17Z", "event":"Status", "Flags":471908424, "Flags2":0, "GuiFocus":0, "Cargo":30.0, "Latitude":-53.864246, "Longitude":-144.48613, "Heading":346, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'J { "timestamp":"2026-09-30T03:41:31Z", "event":"DockSRV", "SRVType":"mev_rhino", "SRVType_Localised":"SRV Rhino", "ID":51 }',
    'S {"timestamp":"2026-09-30T03:41:31Z", "event":"Status", "Flags":471875656, "Flags2":0, "GuiFocus":0, "Cargo":30.0, "Latitude":-53.864037, "Longitude":-144.486206, "Heading":341, "Altitude":0, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
    'S {"timestamp":"2026-09-30T03:41:33Z", "event":"Status", "Flags":153092104, "Flags2":0, "GuiFocus":0, "Cargo":30.0, "Latitude":-53.861923, "Longitude":-144.487473, "Heading":341, "Altitude":30, "BodyName":"Smojooe AR-E b25-8 ABC 3 d", "PlanetRadius":1204549.875}',
]
