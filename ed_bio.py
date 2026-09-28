#!/usr/bin/env python3
"""
ed_bio.py -- Which exobiology species can a planet host, and what are they worth?

The game only spawns each species inside known bands of planet class, atmosphere, gravity,
surface temperature and volcanism (the "spawn conditions" the community has mapped out).
Given a body's scan data this module lists the species that could be there, grouped by genus
with the most valuable candidate first, so you know before you drop a probe whether a body's
bio signals might be a 19M Stratum Tectonicas or a 1M Bacterium Aurasus.

    python3 ed_bio.py --backtest      check the rules against your own journals

A prediction is a possibility, not a promise: the genus is usually reliable, the species within
it (which sets the value) often depends on things the scan does not tell you, so several
species of one genus are commonly listed together. The backtest prints how often your own
finds were on the list.

Body dict used by predict():
    class        journal PlanetClass or Spansh subtype ("Rocky body", "High metal content world")
    atmosphere   journal AtmosphereType ("CarbonDioxide") or Spansh ("Thin Carbon dioxide")
    gravity      g
    temperature  K
    volcanism    journal Volcanism string or Spansh volcanismType ("" / None for none)
    dist_ls      distance from arrival (only Clypeus Speculumi cares)
    star         arrival star class letter (only Electricae care)
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from glob import glob

try:
    from ed_unsold import ORGANIC_VALUES, DEFAULT_DIRS
except ImportError:  # standalone use without the price table
    ORGANIC_VALUES, DEFAULT_DIRS = {}, []

# --------------------------------------------------------------------------
# Normalisation of the different spellings the journal and Spansh use
# --------------------------------------------------------------------------

CLASSES = {
    "rocky body": "rocky", "high metal content body": "hmc", "high metal content world": "hmc",
    "icy body": "icy", "rocky ice body": "rockyice", "rocky ice world": "rockyice",
    "metal rich body": "metalrich", "metal-rich body": "metalrich",
}


def norm_class(c):
    return CLASSES.get((c or "").strip().lower())


def norm_atmosphere(a):
    """'CarbonDioxide', 'Thin Carbon dioxide', 'carbon dioxide-rich' -> 'carbondioxide' / 'carbondioxiderich'."""
    a = (a or "").strip().lower()
    if a in ("", "none", "no atmosphere"):
        return "none"
    a = re.sub(r"^((thin|thick|hot)\s+)+", "", a)
    a = re.sub(r"\s+atmosphere$", "", a)
    return re.sub(r"[\s\-]", "", a)


def norm_volcanism(v):
    v = (v or "").strip().lower()
    if v in ("", "none", "no volcanism"):
        return ""
    return v.replace(" volcanism", "")


# --------------------------------------------------------------------------
# Spawn rules
#
# atm: atmosphere keys (see norm_atmosphere); cls: planet class keys; g/t: inclusive ranges;
# volc: None (don't care), "none" (must have no volcanism), "any" (must have some), or a tuple
# of substrings one of which must appear in the volcanism text.
# --------------------------------------------------------------------------

CO2 = ("carbondioxide", "carbondioxiderich")
AMM = ("ammonia",)
ARG = ("argon", "argonrich")
NEON = ("neon", "neonrich")
METH = ("methane", "methanerich")
SO2 = ("sulphurdioxide",)
WATER = ("water", "waterrich")
ROCKY_HMC = ("rocky", "hmc")
ICES = ("icy", "rockyice")
ALL_LANDABLE = ("rocky", "hmc", "icy", "rockyice", "metalrich")


def rule(name, cls, atm, g=(0, 0.28), t=(0, 9999), volc=None, genus=None, **extra):
    return dict(name=name, genus=genus or name.split()[0], cls=tuple(cls), atm=tuple(atm), g=g, t=t, volc=volc, **extra)


RULES = [
    # Aleoida: rocky/HMC, low gravity
    rule("Aleoida Arcus", ROCKY_HMC, CO2, t=(175, 180)),
    rule("Aleoida Coronamus", ROCKY_HMC, CO2, t=(180, 190)),
    rule("Aleoida Gravis", ROCKY_HMC, CO2, t=(190, 196)),
    rule("Aleoida Spica", ROCKY_HMC, AMM, t=(170, 177)),
    rule("Aleoida Laminiae", ROCKY_HMC, AMM, t=(152, 177)),
    # Bacterium: almost anywhere there is a thin atmosphere; the atmosphere picks the species
    rule("Bacterium Aurasus", ALL_LANDABLE, CO2, g=(0, 0.61)),
    rule("Bacterium Alcyoneum", ALL_LANDABLE, AMM, g=(0, 0.61)),
    rule("Bacterium Vesicula", ALL_LANDABLE, ARG, g=(0, 0.61)),
    rule("Bacterium Acies", ALL_LANDABLE, NEON, g=(0, 0.61)),
    rule("Bacterium Bullaris", ALL_LANDABLE, METH, g=(0, 0.61)),
    rule("Bacterium Cerbrus", ALL_LANDABLE, SO2 + WATER, g=(0, 0.61)),
    rule("Bacterium Informem", ALL_LANDABLE, ("nitrogen",), g=(0, 0.61)),
    rule("Bacterium Volu", ALL_LANDABLE, ("oxygen",), g=(0, 0.61)),
    rule("Bacterium Nebulus", ALL_LANDABLE, ("helium",), g=(0, 0.61)),
    rule("Bacterium Tela", ALL_LANDABLE, WATER + ("oxygen", "helium", "neonrich", "argonrich"), g=(0, 0.61)),
    rule("Bacterium Tela", ALL_LANDABLE, CO2 + AMM + ARG + NEON + METH + SO2 + ("nitrogen",), g=(0, 0.61), volc="any"),
    rule("Bacterium Scopulum", ALL_LANDABLE, NEON, g=(0, 0.61), volc=("carbon", "methane")),
    rule("Bacterium Omentum", ALL_LANDABLE, NEON, g=(0, 0.61), volc=("nitrogen", "ammonia")),
    rule("Bacterium Verrata", ALL_LANDABLE, NEON + WATER, g=(0, 0.61), volc=("water",)),
    # Cactoida
    rule("Cactoida Cortexum", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Cactoida Pullulanta", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Cactoida Lapis", ROCKY_HMC, AMM, t=(160, 180)),
    rule("Cactoida Peperatis", ROCKY_HMC, AMM, t=(160, 180)),
    rule("Cactoida Vermis", ROCKY_HMC, WATER + SO2),
    # Clypeus: warm, CO2 or water
    rule("Clypeus Lacrimam", ROCKY_HMC, CO2 + WATER, t=(190, 9999)),
    rule("Clypeus Margaritus", ROCKY_HMC, CO2 + WATER, t=(190, 9999)),
    rule("Clypeus Speculumi", ROCKY_HMC, CO2 + WATER, t=(190, 9999), dist_min=2500),
    # Concha
    rule("Concha Renibus", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Concha Renibus", ROCKY_HMC, WATER, t=(180, 9999)),
    rule("Concha Labiata", ROCKY_HMC, CO2, t=(150, 200)),
    rule("Concha Aureolas", ROCKY_HMC, AMM),
    rule("Concha Biconcavis", ROCKY_HMC, ("nitrogen",)),
    # Electricae: icy, cold, noble gases; Pluma wants a hot blue star
    rule("Electricae Pluma", ("icy",), ARG + NEON + ("helium",), t=(0, 150), star=("A", "B", "O", "N", "D")),
    rule("Electricae Radialem", ("icy",), ARG + NEON + ("helium",), t=(0, 150), star=("A", "B", "O", "N", "D")),
    # Fonticulua: ice worlds, the atmosphere picks the species
    rule("Fonticulua Campestris", ICES, ARG),
    rule("Fonticulua Segmentatus", ICES, NEON),
    rule("Fonticulua Digitos", ICES, METH),
    rule("Fonticulua Upupam", ICES, ("argonrich",)),
    rule("Fonticulua Lapida", ICES, ("nitrogen",)),
    rule("Fonticulua Fluctus", ICES, ("oxygen",)),
    # Frutexa
    rule("Frutexa Acus", ("rocky",), CO2, t=(0, 195)),
    rule("Frutexa Fera", ("rocky",), CO2, t=(0, 195)),
    rule("Frutexa Metallicum", ("hmc",), AMM + CO2, t=(0, 195)),
    rule("Frutexa Flabellum", ("rocky",), AMM),
    rule("Frutexa Flammasis", ("rocky",), AMM),
    rule("Frutexa Sponsae", ("rocky",), WATER),
    rule("Frutexa Collum", ("rocky",), SO2),
    # Fumerola: needs volcanism of the matching kind
    rule("Fumerola Carbosis", ALL_LANDABLE, ARG + METH + NEON, volc=("carbon", "methane")),
    rule("Fumerola Extremus", ALL_LANDABLE, ARG + METH + NEON + ("nitrogen",), volc=("silicate", "iron", "rocky", "metallic")),
    rule("Fumerola Nitris", ALL_LANDABLE, ARG + METH + NEON + ("nitrogen",), volc=("nitrogen", "ammonia")),
    rule("Fumerola Aquatis", ALL_LANDABLE, ARG + METH + NEON + WATER, volc=("water",)),
    # Fungoida
    rule("Fungoida Setisis", ROCKY_HMC + ("rockyice",), AMM + METH),
    rule("Fungoida Stabitis", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Fungoida Stabitis", ROCKY_HMC, WATER, t=(180, 9999)),
    rule("Fungoida Gelata", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Fungoida Gelata", ROCKY_HMC, WATER, t=(180, 9999)),
    rule("Fungoida Bullarum", ("rockyice",), ARG),
    # Osseus
    rule("Osseus Spiralis", ROCKY_HMC, AMM, t=(160, 180)),
    rule("Osseus Pumice", ("rockyice",), ARG + METH + ("nitrogen",)),
    rule("Osseus Cornibus", ROCKY_HMC, CO2, t=(180, 196)),
    rule("Osseus Fractus", ROCKY_HMC, CO2, t=(180, 190)),
    rule("Osseus Pellebantus", ROCKY_HMC, CO2, t=(190, 196)),
    rule("Osseus Discus", ROCKY_HMC, WATER),
    # Recepta: sulphur dioxide
    rule("Recepta Umbrux", ALL_LANDABLE, SO2, t=(132, 9999)),
    rule("Recepta Deltahedronix", ROCKY_HMC, SO2, t=(132, 9999)),
    rule("Recepta Conditivus", ICES, SO2, t=(132, 9999)),
    # Stratum: tolerates more gravity than the rest; Tectonicas is the HMC one
    rule("Stratum Tectonicas", ("hmc",), AMM + CO2 + SO2 + WATER + ("oxygen",), g=(0, 0.61), t=(165, 9999)),
    rule("Stratum Paleas", ("rocky",), AMM + CO2 + WATER, g=(0, 0.61), t=(165, 9999)),
    rule("Stratum Laminamus", ("rocky",), AMM, g=(0, 0.61), t=(165, 9999)),
    rule("Stratum Excutitus", ("rocky",), CO2 + SO2, g=(0, 0.61), t=(165, 190)),
    rule("Stratum Limaxus", ("rocky",), CO2 + SO2, g=(0, 0.61), t=(165, 190)),
    rule("Stratum Frigus", ("rocky",), CO2 + SO2, g=(0, 0.61), t=(190, 9999)),
    rule("Stratum Cucumisis", ("rocky",), CO2 + SO2, g=(0, 0.61), t=(190, 9999)),
    rule("Stratum Araneamus", ("rocky",), SO2, g=(0, 0.61), t=(165, 9999)),
    # Tubus: very low gravity only
    rule("Tubus Compagibus", ("rocky",), CO2, g=(0, 0.153), t=(160, 190)),
    rule("Tubus Cavas", ("rocky",), CO2, g=(0, 0.153), t=(160, 190)),
    rule("Tubus Conifer", ("rocky",), CO2, g=(0, 0.153), t=(160, 190)),
    rule("Tubus Rosarium", ("rocky",), AMM, g=(0, 0.153), t=(160, 190)),
    rule("Tubus Sororibus", ("hmc",), CO2 + AMM, g=(0, 0.153), t=(160, 190)),
    # Tussock: the CO2 ones are sorted by temperature band
    rule("Tussock Pennata", ROCKY_HMC, CO2, t=(145, 155)),
    rule("Tussock Ventusa", ROCKY_HMC, CO2, t=(155, 160)),
    rule("Tussock Ignis", ROCKY_HMC, CO2, t=(160, 170)),
    rule("Tussock Serrati", ROCKY_HMC, CO2, t=(170, 175)),
    rule("Tussock Albata", ROCKY_HMC, CO2, t=(175, 180)),
    rule("Tussock Caputus", ROCKY_HMC, CO2, t=(180, 190)),
    rule("Tussock Triticum", ROCKY_HMC, CO2, t=(190, 197)),
    rule("Tussock Pennatis", ROCKY_HMC, CO2, t=(145, 197)),
    rule("Tussock Propagito", ROCKY_HMC, CO2, t=(145, 197)),
    rule("Tussock Cultro", ROCKY_HMC, AMM),
    rule("Tussock Catena", ROCKY_HMC, AMM),
    rule("Tussock Divisa", ROCKY_HMC, AMM),
    rule("Tussock Virgam", ROCKY_HMC, WATER),
    rule("Tussock Stigmasis", ROCKY_HMC, SO2),
    rule("Tussock Capillum", ("rockyice",), ARG + METH),
    # Horizons-era life on airless bodies
    rule("Brain Tree", ROCKY_HMC + ("metalrich",), ("none",), g=(0, 0.61), t=(200, 500), volc="any", genus="Brain Trees"),
    rule("Sinuous Tubers", ROCKY_HMC + ("metalrich",), ("none",), g=(0, 0.61), t=(200, 500), volc="any", genus="Sinuous Tubers"),
    rule("Crystalline Shards", ALL_LANDABLE, ("none",), g=(0, 0.61), t=(0, 273), dist_min=12000, star=("A", "F", "G", "K", "M", "S"),
         genus="Crystalline Shards"),
]

GENERA = sorted({r["genus"] for r in RULES})


def genus_value(genus):
    """The most valuable species of a genus in the price table, by name prefix/suffix."""
    g = genus.lower().rstrip("s")
    best = 0
    for value, vname in ORGANIC_VALUES.values():
        n = vname.lower()
        if n.startswith(g) or n.endswith(" " + g) or n.endswith(" " + g + "s"):
            best = max(best, value)
    return best or None


def species_value(name):
    """Credits for a species (max over colour variants for the Horizons ones)."""
    best = 0
    for value, vname in ORGANIC_VALUES.values():
        if vname == name or vname.endswith(" " + name):
            best = max(best, value)
    return best or None


def _matches(r, cls, atm, g, t, volc, dist_ls, star):
    if cls not in r["cls"] or atm not in r["atm"]:
        return False
    if g is not None and not (r["g"][0] <= g <= r["g"][1]):
        return False
    if t is not None and not (r["t"][0] <= t <= r["t"][1]):
        return False
    v = r["volc"]
    if v == "none" and volc:
        return False
    if v == "any" and not volc:
        return False
    if isinstance(v, tuple) and not any(k in volc for k in v):
        return False
    if r.get("dist_min") and dist_ls is not None and dist_ls < r["dist_min"]:
        return False
    if r.get("star") and star and star[0] not in r["star"]:
        return False
    return True


def predict(body):
    """Species that could live on this body, most valuable first.

    Returns [] for a body that cannot host anything (gas giant, no atmosphere and no
    volcanism, too heavy). Each entry: {name, genus, value}.
    """
    cls = norm_class(body.get("class"))
    if not cls:
        return []
    atm = norm_atmosphere(body.get("atmosphere"))
    g = body.get("gravity")
    t = body.get("temperature")
    volc = norm_volcanism(body.get("volcanism"))
    out, seen = [], set()
    for r in RULES:
        if r["name"] in seen or not _matches(r, cls, atm, g, t, volc, body.get("dist_ls"), body.get("star")):
            continue
        seen.add(r["name"])
        out.append({"name": r["name"], "genus": r["genus"], "value": species_value(r["name"])})
    out.sort(key=lambda s: -(s["value"] or 0))
    return out


def potential(candidates, signals=None, genera=None):
    """An upper bound on what a body's bio could pay: the best species of each confirmed genus,
    or, before the DSS, of the `signals` most valuable possible genera."""
    groups = by_genus(candidates, genera)
    if genera is None and signals:
        groups = groups[:signals]
    return sum(g["value"] or 0 for g in groups), groups


def short_species(name, genus):
    """'Tussock Capillum' -> 'Capillum'; 'Brain Tree' stays whole."""
    return name[len(genus) + 1:] if name.startswith(genus + " ") else name


def by_genus(candidates, genera=None):
    """Group candidates by genus: [{genus, best (name), value, species:[...]}], most valuable first.

    If `genera` (the DSS's list) is given, only those genera are kept -- and a genus the DSS
    found that no rule predicts is still listed, with no value guess.
    """
    groups = collections.OrderedDict()
    for c in candidates:
        if genera is not None and c["genus"] not in genera:
            continue
        gr = groups.setdefault(c["genus"], {"genus": c["genus"], "best": c["name"], "value": c["value"],
                                            "min_value": c["value"], "species": []})
        gr["species"].append(c)
        if c["value"] and (gr["min_value"] is None or c["value"] < gr["min_value"]):
            gr["min_value"] = c["value"]
    for g in genera or []:
        if g not in groups:
            # No rule predicts it (Horizons life, or a gap in the table): bound it by the price
            # table so it still counts, and flag that the rules had nothing to say.
            v = genus_value(g)
            groups[g] = {"genus": g, "best": None, "value": v, "min_value": v, "species": [], "unruled": True}
    return sorted(groups.values(), key=lambda gr: -(gr["value"] or 0))


def body_from_scan(ev, star=None):
    """Journal Scan event -> predict() body."""
    g = ev.get("SurfaceGravity")
    return {"class": ev.get("PlanetClass"), "atmosphere": ev.get("AtmosphereType"),
            "gravity": g / 9.80665 if g else None, "temperature": ev.get("SurfaceTemperature"),
            "volcanism": ev.get("Volcanism"), "dist_ls": ev.get("DistanceFromArrivalLS"), "star": star}


# --------------------------------------------------------------------------
# Backtest against the journals
# --------------------------------------------------------------------------

def backtest(dirs, verbose=False, since=None):
    """since: only score samples/DSS results at or after this 'YYYY-MM' (an out-of-sample check)."""
    scans, stars, analysed, genera = {}, {}, [], collections.defaultdict(set)
    for d in dirs:
        for path in sorted(glob(os.path.join(d, "Journal*.log"))):
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"event":"Scan"' in line:
                        ev = json.loads(line)
                        if ev.get("PlanetClass"):
                            scans[(ev.get("SystemAddress"), ev.get("BodyID"))] = ev
                        elif ev.get("StarType") and not ev.get("DistanceFromArrivalLS"):
                            stars[ev.get("SystemAddress")] = ev["StarType"]
                    elif '"event":"ScanOrganic"' in line and '"Analyse"' in line:
                        ev = json.loads(line)
                        if not since or ev.get("timestamp", "") >= since:
                            analysed.append(ev)
                    elif '"event":"SAASignalsFound"' in line and "Genuses" in line:
                        ev = json.loads(line)
                        if since and ev.get("timestamp", "") < since:
                            continue
                        for g in ev.get("Genuses") or []:
                            genera[(ev["SystemAddress"], ev["BodyID"])].add(g.get("Genus_Localised"))

    seen = set()
    sp_hit = sp_total = 0
    misses = collections.Counter()
    ranks = []
    for o in analysed:
        key = (o["SystemAddress"], o["Body"], o["Species_Localised"])
        if key in seen:
            continue
        seen.add(key)
        sc = scans.get((o["SystemAddress"], o["Body"]))
        if not sc:
            continue
        cands = predict(body_from_scan(sc, stars.get(o["SystemAddress"])))
        names = [c["name"] for c in cands]
        sp_total += 1
        if o["Species_Localised"] in names:
            sp_hit += 1
            same = [c["name"] for c in cands if c["genus"] == o["Genus_Localised"]]
            ranks.append(same.index(o["Species_Localised"]) + 1 if o["Species_Localised"] in same else 0)
        else:
            b = body_from_scan(sc)
            misses[(o["Species_Localised"], norm_class(b["class"]), norm_atmosphere(b["atmosphere"]),
                    round(b["gravity"] or 0, 2), round(b["temperature"] or 0), norm_volcanism(b["volcanism"])[:20])] += 1
    g_hit = g_total = 0
    extra = []
    g_misses = collections.Counter()
    for key, gs in genera.items():
        sc = scans.get(key)
        if not sc:
            continue
        cands = predict(body_from_scan(sc, stars.get(key[0])))
        pg = {c["genus"] for c in cands}
        for g in gs:
            g_total += 1
            if g in pg:
                g_hit += 1
            else:
                b = body_from_scan(sc)
                g_misses[(g, norm_class(b["class"]), norm_atmosphere(b["atmosphere"]), round(b["gravity"] or 0, 2),
                          round(b["temperature"] or 0))] += 1
        extra.append(len(pg - gs))
    print(f"species: {sp_hit}/{sp_total} of your analysed species were on the list "
          f"({100 * sp_hit / max(sp_total, 1):.0f}%)")
    if ranks:
        top = sum(1 for r in ranks if r == 1)
        print(f"         when the genus was right, the actual species was the top-valued candidate of that genus "
              f"{top}/{len(ranks)} times; candidates per genus: {sum(ranks) / len(ranks):.1f} avg rank")
    print(f"genera:  {g_hit}/{g_total} of the genera the DSS found were predicted ({100 * g_hit / max(g_total, 1):.0f}%); "
          f"on average {sum(extra) / max(len(extra), 1):.1f} predicted genera per body did not show up")
    if misses:
        print("\nspecies misses (species, class, atmosphere, g, K, volcanism) x n:")
        for k, n in misses.most_common(40):
            print("  ", k, "x", n)
    if g_misses:
        print("\ngenus misses:")
        for k, n in g_misses.most_common(20):
            print("  ", k, "x", n)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--backtest", action="store_true", help="Check the rules against your journals.")
    p.add_argument("--since", metavar="YYYY-MM", help="With --backtest: only score finds from this month on (out-of-sample).")
    p.add_argument("--dir", action="append", help="Journal directory (repeatable).")
    p.add_argument("--body", help='Predict for a body given as JSON, e.g. \'{"class":"Rocky body","atmosphere":"Ammonia","gravity":0.15,"temperature":170}\'')
    a = p.parse_args(argv)
    if a.body:
        for gr in by_genus(predict(json.loads(a.body))):
            print(f"{gr['genus']:12} up to {gr['value'] or 0:>11,} cr  ({', '.join(short_species(s['name'], gr['genus']) + ' ' + str((s['value'] or 0) // 1000) + 'k' for s in gr['species'])})")
        return
    if a.backtest:
        backtest(a.dir or DEFAULT_DIRS, since=a.since)
        return
    p.print_help()


if __name__ == "__main__":
    main()
