"""The tablet layout (PLAN-tablet phase 3), the server's side: GET /tablet is the same page in a tablet mode with its
shell and theme stylesheets, the desktop page is left as it was, the fonts are OFL with their licences, and a font of
your own comes from data/fonts/ by a safe name only. The page itself is checked by tests/page_smoke.js."""
import asyncio
import os
import re
import tempfile
import unittest
import unittest.mock

from support import ed_outrider  # also puts the repository root on sys.path

import outrider.auth  # noqa: E402


class Tablet(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.state = ed_outrider.State(self.db, ed_outrider.Journals(self.db), None, 25)

    def client(self, go):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(self.state))) as c:
                return await go(c)
        return asyncio.run(run())

    def test_tablet_page_and_desktop_page(self):
        async def go(c):
            return [(r.status, await r.text()) for r in (await c.get("/tablet"), await c.get("/"))]
        (ts, tablet), (ds, desk) = self.client(go)
        self.assertEqual((ts, ds), (200, 200))
        self.assertIn('<body class="tablet">', tablet)
        self.assertRegex(tablet, r'<html lang="en" data-theme="lcars">')
        for name in ed_outrider.TABLET_STYLES:   # stamped like page.css, so a changed theme is fetched at once
            self.assertRegex(tablet, rf'href="static/{re.escape(name)}\?v=\d+"')
            self.assertTrue(os.path.isfile(os.path.join(ed_outrider.STATIC_DIR, name)), name)
        # the server's data is filled in the same as on the desktop page
        self.assertNotIn("/*SEARCH_OPTIONS*/null", tablet)
        # the desktop page: no tablet class, no theme, no tablet stylesheet (its shell's markup stays hidden)
        self.assertNotIn('class="tablet"', desk)
        self.assertNotIn("data-theme", desk)
        self.assertNotIn("tablet.css", desk)
        self.assertIn('<nav id="tabNav" class="tb-nav" aria-label="Pages" hidden>', desk)
        # every theme the page offers has its stylesheet, scoped to its data-theme (the desktop is never themed)
        for t in ed_outrider.TABLET_THEMES:
            with open(os.path.join(ed_outrider.STATIC_DIR, "themes", f"{t}.css"), encoding="utf-8") as f:
                css = f.read()
            self.assertIn(f'[data-theme="{t}"]', css)
            self.assertIsNone(re.search(r"^:root\s*\{", css, re.M), "a theme sets nothing outside its data-theme")
            self.assertIn(f'<option value="{t}">', tablet)

    def test_name_fields_are_not_auto_capitalised(self):
        """A tablet keyboard capitalises a field's first letter and corrects words: system names and search terms
        must reach Outrider as typed (found on the Galaxy Tab's Samsung keyboard)."""
        with open(os.path.join(ed_outrider.STATIC_DIR, "page.html"), encoding="utf-8") as f:
            html = f.read()
        for id_ in ("findName", "hwyFrom", "hwyTo", "lFilter", "mFilter", "bFilter"):
            tag = re.search(rf'<input [^>]*id="{id_}"[^>]*>', html).group(0)
            for attr in ('autocapitalize="off"', 'autocorrect="off"', 'spellcheck="false"'):
                self.assertIn(attr, tag, id_)

    def test_page_stamp(self):
        """An open page reloads itself when Outrider has newer page files (a tablet left open over a restart kept its
        old Search): the stamp it is served with, the same in every payload, changes with any page file."""
        async def go(c):
            pages = [await (await c.get(u)).text() for u in ("/", "/tablet")]
            return pages, (await (await c.get("/api/nearby")).json())["page_stamp"]
        pages, stamp = self.client(go)
        self.assertRegex(stamp, r"^[0-9a-f]{12}$")
        for html in pages:
            self.assertIn(f'window.__PAGE_STAMP__ = "{stamp}";', html)
        with tempfile.TemporaryDirectory() as d:
            for name in ed_outrider.PAGE_FILES:
                os.makedirs(os.path.dirname(os.path.join(d, name)), exist_ok=True)
                with open(os.path.join(d, name), "w") as f:
                    f.write("x")
            a = ed_outrider.page_stamp(d)
            self.assertEqual(ed_outrider.page_stamp(d), a)
            path = os.path.join(d, "themes", "lcars.css")
            os.utime(path, ns=(1, os.stat(path).st_mtime_ns + 10 ** 9))
            self.assertNotEqual(ed_outrider.page_stamp(d), a)

    def test_fonts_are_ofl_and_shipped_with_their_licences(self):
        fonts = os.path.join(ed_outrider.STATIC_DIR, "fonts")
        files = os.listdir(fonts)
        ttf = [f for f in files if f.endswith((".ttf", ".otf", ".woff", ".woff2"))]
        self.assertTrue(ttf)
        for f in ttf:   # Antonio-VF.ttf -> OFL-Antonio.txt; BarlowCondensed-Medium.ttf -> OFL-BarlowCondensed.txt
            family = f.split("-")[0]
            lic = os.path.join(fonts, f"OFL-{family}.txt")
            self.assertTrue(os.path.isfile(lic), f"{f}: no {lic}")
            with open(lic, encoding="utf-8") as fh:
                self.assertIn("SIL Open Font License, Version 1.1", fh.read())
        # every font a stylesheet asks for from static/fonts/ is there (a typo would silently fall back)
        for css in ("tablet.css", os.path.join("themes", "lcars.css")):
            with open(os.path.join(ed_outrider.STATIC_DIR, css), encoding="utf-8") as fh:
                for name in re.findall(r'url\("\.\./fonts/([^"]+)"\)', fh.read()):
                    self.assertIn(name, files, css)

    def test_user_fonts(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "lcars-display.ttf"), "wb") as f:
                f.write(b"\x00\x01\x00\x00font")
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write("not a font")
            with unittest.mock.patch.object(ed_outrider, "FONT_DIR", d):
                async def go(c):
                    r = await c.get("/userfonts/lcars-display.ttf")
                    out = [(r.status, await r.read())]
                    for bad in ("/userfonts/notes.txt", "/userfonts/missing.ttf", "/userfonts/..%2Fsecret.ttf",
                                "/userfonts/.hidden.ttf"):
                        out.append((await c.get(bad)).status)
                    return out
                got = self.client(go)
        self.assertEqual(got[0], (200, b"\x00\x01\x00\x00font"))
        self.assertEqual(got[1:], [404, 404, 404, 404])

    def test_tablet_needs_the_password_from_the_network(self):
        self.state.password = "pw"
        p = unittest.mock.patch.object(outrider.auth, "is_loopback", lambda remote: False)
        p.start()
        self.addCleanup(p.stop)

        async def go(c):
            r = await c.get("/tablet", allow_redirects=False)
            app = await c.get("/tablet", headers={"User-Agent": "Mozilla/5.0 OutriderApp/1.0.0"}, allow_redirects=False)
            font = await c.get("/userfonts/x.ttf")
            return r.status, r.headers.get("Location"), app.status, font.status
        status, where, app, font = self.client(go)
        self.assertEqual((status, app, font), (302, 401, 401))
        self.assertTrue(where.startswith("/signin?next=") and "tablet" in where)


if __name__ == "__main__":
    unittest.main()
