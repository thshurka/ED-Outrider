"""Outrider as a server away from the game PC ([server] game_pc; the Docker plan's D1): the setting, how auto decides
(inside a container: not the game PC), every route that presses keys or plays on this PC refused, the rail empty, and
the payload and /api/version saying so. Fakes only: nothing here opens a device."""
import argparse
import asyncio
import contextlib
import io
import os
import tempfile
import tomllib
import unittest

from support import ed_outrider

ARGS = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)


def settings(cfg):
    with contextlib.redirect_stderr(io.StringIO()) as err:
        return ed_outrider.settings_from(cfg, ARGS, None, ([], [])), err.getvalue()


class Setting(unittest.TestCase):
    def test_values(self):
        for given, want in ((None, "auto"), ("auto", "auto"), (True, True), (False, False), ("false", False), ("On", True)):
            cfg = {} if given is None else {"server": {"game_pc": given}}
            self.assertEqual(settings(cfg)[0]["game_pc"], want, given)
        st, err = settings({"server": {"game_pc": 3}})
        self.assertEqual(st["game_pc"], "auto")
        self.assertIn("game_pc", err)
        for v in ("auto", True, False):   # --write-config and Settings write it back as it was
            st, _ = settings({"server": {"game_pc": v}})
            self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["server"]["game_pc"], v)

    def test_auto_and_containers(self):
        self.assertEqual(ed_outrider.resolve_game_pc("auto", container=False), (True, "auto"))
        self.assertFalse(ed_outrider.resolve_game_pc("auto", container=True)[0])
        self.assertTrue(ed_outrider.resolve_game_pc(True, container=True)[0])    # set by hand: as set
        self.assertFalse(ed_outrider.resolve_game_pc(False, container=False)[0])
        with tempfile.TemporaryDirectory() as d:
            marker = os.path.join(d, ".dockerenv")
            self.assertFalse(ed_outrider.in_container(marker, env={}))
            self.assertTrue(ed_outrider.in_container(marker, env={"OUTRIDER_CONTAINER": "1"}))
            open(marker, "w").close()
            self.assertTrue(ed_outrider.in_container(marker, env={}))


class ServerMode(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.state = ed_outrider.State(self.db, ed_outrider.Journals(self.db), None, 25)
        self.state.game_pc = False
        self.state.journals.status_json = {"live": True, "flags": 1 << 24}   # in the ship: the rail would have buttons

    def test_routes_refused(self):
        from aiohttp.test_utils import TestClient, TestServer
        routes = [("/api/autohonk", {"enabled": True}), ("/api/autohonk/test", None), ("/api/autohonk/forget", None),
                  ("/api/highway/autotarget", {"enabled": True}), ("/api/highway/autotarget/test", None),
                  ("/api/highway/target", None), ("/api/rail/press", {"context": "ship", "id": "gear"}),
                  ("/api/rail/sets", {"context": "ship", "reset": True}), ("/api/say/play", {"text": "hi"}),
                  ("/api/sound/play", {"name": "chime"})]

        async def go():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                out = []
                for path, body in routes:
                    r = await c.post(path, json=body) if body is not None else await c.post(path)
                    out.append((path, r.status, (await r.json()).get("code")))
                v = await (await c.get("/api/version")).json()
                rail = await (await c.get("/api/rail")).json()
                return out, v, rail
        out, v, rail = asyncio.run(go())
        self.assertEqual([x for x in out if x[1:] != (409, "not_game_pc")], [])
        self.assertIs(v["game_pc"], False)
        self.assertEqual((rail["context"], rail["buttons"], rail["can_press"]), (None, [], False))
        self.assertIn("the PC the game runs on", rail["why"])
        self.assertIs(self.state.payload()["game_pc"], False)

    def test_game_pc_unchanged(self):
        self.state.game_pc = True
        self.assertIs(self.state.payload()["game_pc"], True)
        self.assertEqual(self.state.rail_info()["context"], "ship")

    def test_keyboard_off(self):
        import outrider.honk
        h = ed_outrider.simulate_keyboard_off(outrider.honk.Honker("KEY_K"), "server mode")
        self.assertEqual((h.available, h.status, h.open("rail")), (False, "off (server mode)", False))


if __name__ == "__main__":
    unittest.main()
