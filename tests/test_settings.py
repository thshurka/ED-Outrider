"""The Settings dialog's Server settings: every config key listed (GET /api/config, secrets only as set or not) and
changed in place in the config file (POST /api/config: comments kept, the old file kept as .bak, nothing written when
the result would not read back or settings_from finds something new wrong). Only ever a temporary config file."""
import argparse
import asyncio
import contextlib
import io
import os
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock

from support import ed_outrider

import outrider.auth  # noqa: E402
import outrider.config_edit as ce  # noqa: E402

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
EXAMPLE = os.path.join(os.path.dirname(ed_outrider.STATIC_DIR), "ed_outrider.toml.example")


def settings(cfg):
    with contextlib.redirect_stderr(io.StringIO()):
        return ed_outrider.settings_from(cfg, ARGS, None, ([], []))


class ConfigEdit(unittest.TestCase):
    def test_every_key_listed_and_writable(self):
        """Every key --write-config writes is listed, and setting each to its own value in an empty file reads back to
        the same setting (so the page can change any of them)."""
        st = settings({})
        secs = ce.entries(ed_outrider.config_text(st))
        self.assertEqual([s["section"] for s in secs],
                         ["journals", "server", "defaults", "spansh", "speech", "autohonk", "copilot", "highway", "assistant", "mcp"])
        keys = [(s["section"], k["key"]) for s in secs for k in s["keys"]]
        self.assertGreaterEqual(len(keys), 80)
        for want in [("server", "password"), ("server", "db"), ("server", "backup_dir"), ("journals", "live"), ("assistant", "api_key"),
                     ("highway", "autotarget_keys"), ("mcp", "url"), ("speech", "sound_dir"), ("defaults", "speech_styles")]:
            self.assertIn(want, keys)
        for s in secs:
            for k in s["keys"]:
                text = ce.set_key("", s["section"], k["key"], k["value"])
                self.assertEqual(tomllib.loads(text)[s["section"]][k["key"]], k["value"], (s["section"], k["key"]))
        self.assertTrue(all(k["help"] for s in secs for k in s["keys"] if (s["section"], k["key"]) != ("server", "db") and k["set"]))

    def test_in_place(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            ex = f.read()
        t = ce.set_key(ex, "server", "port", 8931)                       # a commented-out key switched on, its help kept
        t = ce.set_key(t, "highway", "autotarget_keys", {"Enter": "KEY_KPENTER", "a b": "KEY_A"})
        self.assertIn('port = 8931', t)
        self.assertIn('# (without a password below', t)                 # the comments round it untouched
        self.assertEqual(len(t.splitlines()), len(ex.splitlines()))       # no line added or lost
        self.assertEqual(tomllib.loads(t)["highway"]["autotarget_keys"], {"Enter": "KEY_KPENTER", "a b": "KEY_A"})
        multi = '[server]\nallowed_hosts = [\n  "a",   # one\n  "b",\n]   # the names\nport = 1\n'
        t = ce.set_key(multi, "server", "allowed_hosts", ["x"])         # a list over several lines replaced whole
        self.assertEqual((tomllib.loads(t)["server"], t.count("# the names")), ({"allowed_hosts": ["x"], "port": 1}, 1))
        t = ce.set_key('[server]\nhost = "a # not a comment"   # the real one\n', "server", "host", 'q"uote')
        self.assertEqual((tomllib.loads(t)["server"]["host"], "# the real one" in t), ('q"uote', True))
        t = ce.set_key("[server]\nport = 1\n\n[spansh]\n", "server", "password", "pw")   # a new key: in its own section
        self.assertEqual(tomllib.loads(t), {"server": {"port": 1, "password": "pw"}, "spansh": {}})

    def test_coerce(self):
        self.assertEqual([ce.coerce("int", "8025"), ce.coerce("float", "2.5"), ce.coerce("bool", True), ce.coerce("lines", "a\n\n b \n"),
                          ce.coerce("numbers", "20, 25 30"), ce.coerce("table", '{"Enter": "KEY_KPENTER"}'), ce.coerce("table", "")],
                         [8025, 2.5, True, ["a", "b"], [20, 25, 30], {"Enter": "KEY_KPENTER"}, {}])
        for kind, bad in (("int", "x"), ("int", ""), ("bool", "yes"), ("numbers", "a, b"), ("table", "[1]"), ("text", 5), ("table", '{"a": 1}')):
            with self.assertRaises(ValueError, msg=(kind, bad)):
                ce.coerce(kind, bad)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = os.path.join(self.tmp, "ed_outrider.toml")
        with open(EXAMPLE, encoding="utf-8") as f:
            text = f.read().replace('# password = ""        # devices', 'password = "hunter2"   # devices')
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.state = ed_outrider.State(self.db, ed_outrider.Journals(self.db), None, 25)
        self.state.config_path = self.path

    def client(self, go):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return await go(c)
        return asyncio.run(run())

    def test_get_hides_secrets(self):
        async def go(c):
            r = await c.get("/api/config")
            return await r.text(), await r.json()
        text, d = self.client(go)
        self.assertNotIn("hunter2", text)
        pw = next(k for s in d["sections"] if s["section"] == "server" for k in s["keys"] if k["key"] == "password")
        self.assertEqual((pw["secret"], pw["set"], pw["value"], d["path"], d["exists"]), (True, True, None, self.path, True))

    def test_save(self):
        async def go(c):
            out = []
            for body in ({"server": {"port": "8931", "password": "new pw"}, "autohonk": {"enabled": True}, "journals": {"live": "/j/a\n/j/b"}},
                         {"server": {"port": "x"}}, {"server": {"nope": 1}}, {"mcp": {"max_rows": "0"}}, {}, [1]):
                r = await c.post("/api/config", json=body)
                out.append((r.status, await r.json()))
            return out
        with open(self.path, encoding="utf-8") as f:
            before = f.read()
        out = self.client(go)
        self.assertEqual((out[0][0], out[0][1]["changed"], out[0][1]["restart"]), (200, 4, True))
        with open(self.path, encoding="utf-8") as f:
            after = f.read()
        cfg = tomllib.loads(after)
        self.assertEqual((cfg["server"]["port"], cfg["server"]["password"], cfg["autohonk"]["enabled"], cfg["journals"]["live"]),
                         (8931, "new pw", True, ["/j/a", "/j/b"]))
        self.assertIn("# The Highway map draws the galactic regions", after)   # the file's comments are kept
        with open(self.path + ".bak", encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        # refused, and nothing written: not a number, not a key, a value settings_from rejects, an empty body, not an object
        self.assertEqual([s for s, _ in out[1:]], [400] * 5)
        self.assertIn("must be a number", out[1][1]["error"])
        self.assertIn("is not a setting", out[2][1]["error"])
        self.assertIn("max_rows", out[3][1]["error"])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), after)

    def test_no_file_yet_and_who_may(self):
        os.remove(self.path)

        async def go(c):
            r = await c.post("/api/config", json={"server": {"radius": 40}})
            out = [r.status]
            out.append((await c.post("/api/config", json={"server": {"radius": 30}}, headers={"Origin": "http://evil.example"})).status)
            self.state.password = "pw"
            with unittest.mock.patch.object(outrider.auth, "is_loopback", lambda remote: False):
                out.append((await c.get("/api/config")).status)
                out.append((await c.post("/api/config", json={"server": {"radius": 30}})).status)
            return out
        self.assertEqual(self.client(go), [200, 403, 401, 401])
        with open(self.path, encoding="utf-8") as f:   # made from the settings in effect, with the change
            cfg = tomllib.loads(f.read())
        self.assertEqual((cfg["server"]["radius"], cfg["server"]["port"]), (40, 8025))


if __name__ == "__main__":
    unittest.main()
