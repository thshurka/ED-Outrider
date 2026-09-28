"""Regression tests for ED Outrider.

    python3 -m unittest discover tests            # unit tests (no journals or network needed)
    node tests/page_smoke.js <port>               # optional page smoke test against a running server

The synthetic cases here are the failure scenarios earlier reviews found: partial sales, ship
losses, re-scans, abandoned bio runs, crew cuts, ring naming and bio spawn rules.
"""
import argparse
import datetime as dt
import os
import sys
import unittest
import unittest.mock
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ed_bio  # noqa: E402
import ed_materials  # noqa: E402
import ed_log  # noqa: E402
import ed_outrider  # noqa: E402
import ed_unsold  # noqa: E402


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
        self.db.execute("INSERT INTO own_mapped VALUES (1, 2, 'T3')")
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
        n = self.names({"class": "Rocky body", "atmosphere": "Hot thin Sulphur dioxide", "gravity": 0.3, "temperature": 420})
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
        self.assertEqual(self.j.fuel_hist, [[10.0, 1.0], [10.0, 1.0]])                          # one per jump
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
        self.assertEqual(self.state.destination(), {"body_id": 7, "name": "7 a"})
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
        ed_outrider.meta_set(self.db, "route", {"ts": "t", "hops": hops})
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
