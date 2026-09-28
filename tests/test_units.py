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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ed_bio  # noqa: E402
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


class BioRules(unittest.TestCase):
    def names(self, body):
        return [s["name"] for s in ed_bio.predict(body)]

    def test_icy_argon_is_bacterium_and_fonticulua_only(self):
        n = self.names({"class": "Icy body", "atmosphere": "Argon", "gravity": 0.2, "temperature": 80, "star": "M"})
        self.assertIn("Fonticulua Campestris", n)
        self.assertNotIn("Tussock Capillum", n)
        self.assertNotIn("Osseus Pumice", n)

    def test_spansh_two_prefix_atmosphere(self):
        self.assertEqual(ed_bio.norm_atmosphere("Hot thin Sulphur dioxide"), "sulphurdioxide")
        n = self.names({"class": "Rocky body", "atmosphere": "Hot thin Sulphur dioxide", "gravity": 0.3, "temperature": 420})
        self.assertIn("Stratum Cucumisis", n)

    def test_tubus_needs_low_gravity(self):
        base = {"class": "Rocky body", "atmosphere": "CarbonDioxide", "temperature": 170}
        self.assertIn("Tubus Compagibus", self.names(dict(base, gravity=0.1)))
        self.assertNotIn("Tubus Compagibus", self.names(dict(base, gravity=0.2)))

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
