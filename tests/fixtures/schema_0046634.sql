-- The database schema of the first public ED Outrider (commit 0046634, 2026-09-28), frozen: the oldest
-- database a player can have. tests/test_state.py SchemaUpgrade builds it and lets open_db upgrade it.
-- Never edit it to match the current SCHEMA (that would defeat the test).
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
    system INTEGER, body_id INTEGER, name TEXT, record TEXT, ts TEXT,
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
-- Bookmarks made on the page (the game's own bookmarks never reach the journal).
CREATE TABLE IF NOT EXISTS bookmarks (
    id64 INTEGER PRIMARY KEY, name TEXT, x REAL, y REAL, z REAL, note TEXT, created_ts TEXT);
CREATE INDEX IF NOT EXISTS route_xyz ON route_systems (x, y, z);
CREATE INDEX IF NOT EXISTS visits_xyz ON visits (x, y, z);
