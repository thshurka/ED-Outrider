"""[server] password and the Android app's native-facing contract (tablet plan, phase 1): /api/version, sign in,
sign out, the error shape, and what a device on the network may reach without a session. The test client connects
from 127.0.0.1, so "from the network" patches outrider.auth.is_loopback."""
import asyncio
import unittest
import unittest.mock
import urllib.parse

from support import ed_outrider  # also puts the repository root on sys.path

import outrider  # noqa: E402
import outrider.auth  # noqa: E402


class Auth(unittest.TestCase):
    def setUp(self):
        self.db = ed_outrider.open_db(":memory:")
        self.addCleanup(self.db.close)
        self.j = ed_outrider.Journals(self.db)
        self.state = ed_outrider.State(self.db, self.j, None, 25)
        self.state.password = "hunter2"

    def lan(self):
        """Requests as if from another device on the network."""
        p = unittest.mock.patch.object(outrider.auth, "is_loopback", lambda remote: False)
        p.start()
        self.addCleanup(p.stop)

    def client(self, go, state=None):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            async with TestClient(TestServer(ed_outrider.make_app(state or self.state))) as c:
                return await go(c)
        return asyncio.run(run())

    # ---- the contract's answers: exact keys and types ----
    def test_version_is_open_and_says_nothing_else(self):
        self.lan()

        async def go(c):
            r = await c.get("/api/version")
            return r.status, await r.json()
        status, body = self.client(go)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"outrider", "api", "min_app", "password", "signed_in"})
        self.assertEqual((body["outrider"], body["api"], body["min_app"]), (outrider.__version__, 1, "1.0.0"))
        self.assertEqual((body["password"], body["signed_in"]), (True, False))
        self.assertIsInstance(body["outrider"], str)

    def test_signin_signout_and_the_session(self):
        self.lan()

        async def go(c):
            out = {}
            r = await c.get("/api/nearby")
            out["before"] = (r.status, await r.json())
            r = await c.post("/api/auth/signin", json={"password": "wrong"})
            out["wrong"] = (r.status, await r.json())
            r = await c.post("/api/auth/signin", json={"password": "hunter2"})
            body = await r.json()
            out["ok"] = (r.status, set(body), body["ok"])
            out["cookie"] = r.headers.get("Set-Cookie", "")
            token = body["token"]
            out["cookie_works"] = (await c.get("/api/nearby")).status   # the client keeps the cookie, as the WebView does
            c.session.cookie_jar.clear()
            out["bearer"] = (await c.get("/api/nearby", headers={"Authorization": f"Bearer {token}"})).status
            out["version"] = (await (await c.get("/api/version", headers={"Authorization": f"Bearer {token}"})).json())["signed_in"]
            # a second device signs in; the first signs out: only the first stops working
            r2 = await c.post("/api/auth/signin", json={"password": "hunter2"})
            other = (await r2.json())["token"]
            c.session.cookie_jar.clear()
            r = await c.post("/api/auth/signout", headers={"Authorization": f"Bearer {token}"})
            out["signout"] = (r.status, await r.json())
            out["after"] = (await c.get("/api/nearby", headers={"Authorization": f"Bearer {token}"})).status
            out["other"] = (await c.get("/api/nearby", headers={"Authorization": f"Bearer {other}"})).status
            return out, other
        out, other = self.client(go)
        self.assertEqual(out["before"], (401, {"error": out["before"][1]["error"], "code": "signin_required"}))
        self.assertEqual(out["wrong"], (401, {"error": "wrong password", "code": "bad_password"}))
        self.assertEqual(out["ok"], (200, {"ok", "token"}, True))
        for part in ("outrider_session=", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(part, out["cookie"])
        self.assertEqual((out["cookie_works"], out["bearer"], out["version"]), (200, 200, True))
        self.assertEqual(out["signout"], (200, {"ok": True}))
        self.assertEqual((out["after"], out["other"]), (401, 200))
        # the session survives an Outrider restart (a new State on the same database)...
        again = ed_outrider.State(self.db, self.j, None, 25)
        again.password = "hunter2"
        self.assertTrue(again.session_ok(other))
        # ...and a changed password ends every session
        again.password = "correct horse"
        self.assertFalse(again.session_ok(other))

    def test_rate_limit(self):
        self.lan()

        async def go(c):
            codes = [(await c.post("/api/auth/signin", json={"password": "no"})).status for _ in range(5)]
            r = await c.post("/api/auth/signin", json={"password": "hunter2"})   # even the right one waits now
            return codes, r.status, await r.json(), r.headers.get("Retry-After")
        codes, status, body, retry = self.client(go)
        self.assertEqual(codes, [401] * 5)
        self.assertEqual((status, body["code"]), (429, "rate_limited"))
        self.assertTrue(retry and int(retry) > 0)

    def test_bad_requests_and_an_old_app(self):
        self.lan()

        async def go(c):
            out = [(await c.post("/api/auth/signin", json=b)).status for b in ([1], {"password": 5}, {})]
            r = await c.post("/api/auth/signin", json={"password": "hunter2"}, headers={"X-Outrider-App": "0.9.0"})
            out.append((r.status, (await r.json())["code"]))
            r = await c.post("/api/auth/signin", json={"password": "hunter2"}, headers={"X-Outrider-App": "1.0.0"})
            out.append(r.status)
            return out
        self.assertEqual(self.client(go), [400, 400, 400, (426, "app_too_old"), 200])

    # ---- what the network reaches without a session ----
    def test_pages_without_a_session(self):
        self.lan()

        async def go(c):
            out = {}
            r = await c.get("/", allow_redirects=False)
            out["browser"] = (r.status, r.headers.get("Location"))
            r = await c.get("/", headers={"User-Agent": "Mozilla/5.0 OutriderApp/1.0.0"}, allow_redirects=False)
            out["app"] = (r.status, (await r.json())["code"])
            out["static"] = (await c.get("/static/page.js")).status
            r = await c.get("/signin")
            out["signin"] = (r.status, "password" in await r.text())
            out["favicon"] = (await c.get("/static/favicon.svg")).status
            out["status"] = [(await c.get(p)).status for p in ed_outrider.OPEN_GETS]   # the overlays stay open
            out["post"] = (await c.post("/api/hush", json={"minutes": 10})).status
            # request_guard still refuses another site's request, signed in or not
            out["cross"] = (await c.post("/api/auth/signin", json={"password": "hunter2"},
                                         headers={"Origin": "http://evil.example"})).status
            return out
        out = self.client(go)
        status, where = out["browser"]
        where = urllib.parse.urlsplit(where)
        self.assertEqual((status, where.path, urllib.parse.parse_qs(where.query)), (302, "/signin", {"next": ["/"]}))
        self.assertEqual(out["app"], (401, "signin_required"))
        self.assertEqual(out["static"], 401)
        self.assertEqual(out["signin"], (200, True))
        self.assertEqual((out["favicon"], out["status"], out["post"], out["cross"]), (200, [200, 200], 401, 403))

    def test_this_pc_and_no_password_need_nothing(self):
        async def go(c):   # from 127.0.0.1, with a password set
            r = await c.get("/api/version")
            return (await c.get("/api/nearby")).status, (await r.json())["signed_in"]
        self.assertEqual(self.client(go), (200, True))
        self.lan()
        self.state.password = ""

        async def go2(c):   # no password: every device, as before
            r = await c.post("/api/auth/signin", json={"password": "anything"})
            v = await (await c.get("/api/version")).json()
            return (await c.get("/api/nearby")).status, r.status, await r.json(), (v["password"], v["signed_in"])
        self.assertEqual(self.client(go2), (200, 200, {"ok": True, "token": ""}, (False, True)))

    def test_config_and_helpers(self):
        import argparse
        import contextlib
        import io
        import tomllib
        args = argparse.Namespace(journals=None, legacy=None, host=None, port=None, radius=None, db=None)
        self.assertEqual(ed_outrider.settings_from({}, args, None, ([], []))["password"], "")
        st = ed_outrider.settings_from({"server": {"password": "s3cret"}}, args, None, ([], []))
        self.assertEqual(tomllib.loads(ed_outrider.config_text(st))["server"]["password"], "s3cret")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ed_outrider.settings_from({"server": {"password": 1234}}, args, None, ([], []))["password"], "")
        self.assertIn("password must be a string", err.getvalue())
        A = outrider.auth
        self.assertTrue(all(A.is_loopback(x) for x in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "127.0.0.5")))
        self.assertFalse(any(A.is_loopback(x) for x in ("192.168.1.208", "fe80::1", None, "")))
        self.assertEqual((A.version_tuple("1.10.0") > A.version_tuple("1.9.9"), A.version_tuple("x")), (True, ()))
        t = A.make_token("s" * 64, "pw")
        self.assertTrue(A.check_token("s" * 64, "pw", t))
        self.assertFalse(A.check_token("s" * 64, "pw2", t))
        self.assertFalse(A.check_token("s" * 64, "pw", t, revoked={A.token_id(t)}))
        self.assertFalse(A.check_token("s" * 64, "pw", t[:-1] + ("0" if t[-1] != "0" else "1")))


if __name__ == "__main__":
    unittest.main()
