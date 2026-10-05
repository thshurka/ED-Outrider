"""Outrider as a server away from the game PC ([server] game_pc; the Docker plan's D1): the setting, how auto decides
(inside a container: not the game PC), every route that presses keys or plays on this PC refused, the rail empty, and
the payload and /api/version saying so. Fakes only: nothing here opens a device."""
import argparse
import asyncio
import contextlib
import io
import os
import re
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
        for v in ("auto", True, False):   # --write-config and Settings write it back as it was (always quoted: R8)
            st, _ = settings({"server": {"game_pc": v}})
            written = tomllib.loads(ed_outrider.config_text(st))
            self.assertEqual((written["server"]["game_pc"], settings(written)[0]["game_pc"]), (str(v).lower(), v))

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


class Packaging(unittest.TestCase):
    """The Docker files (the plan's D4), checked without Docker: the image marks itself a container (so game_pc auto is
    off), keeps your files out, starts through the entrypoint; compose mounts the journals read-only and keeps the
    config in a folder (Settings writes it)."""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def read(self, name):
        with open(os.path.join(self.ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_files(self):
        df, ignore, compose, entry = (self.read(n) for n in ("Dockerfile", ".dockerignore", "docker-compose.yml", "docker/entrypoint.sh"))
        self.assertIn("OUTRIDER_CONTAINER=1", df)
        self.assertIn('ENTRYPOINT ["docker/entrypoint.sh"]', df)
        self.assertIn("/api/version", df)   # the health check uses the open route
        self.assertTrue(os.access(os.path.join(self.ROOT, "docker", "entrypoint.sh"), os.X_OK))
        for kept_out in ("data", "ed_outrider.toml", "project", ".venv", "docker/config", "docker/data"):
            self.assertIn(kept_out, ignore.split())
        self.assertIn(":/journals:ro", compose)
        self.assertIn("./docker/config:/config", compose)
        self.assertIn("./docker/data:/app/data", compose)
        self.assertIn("--journals /journals", entry)
        self.assertIn('exec python ed_outrider.py --config "$CONFIG"', entry)
        self.assertTrue(ed_outrider.in_container("/nonexistent/.dockerenv", env={"OUTRIDER_CONTAINER": "1"}))

    def test_folders_ship_and_are_checked(self):
        """R1: a fresh clone has docker/data, config and journals (Docker would make missing ones as root, and the
        container could not write them); the entrypoint checks it can write before anything else."""
        import subprocess
        for d in ("data", "config", "journals"):
            keep = os.path.join("docker", d, ".gitkeep")
            self.assertTrue(os.path.exists(os.path.join(self.ROOT, keep)), keep)
            ignored = subprocess.run(["git", "check-ignore", "-q", keep], cwd=self.ROOT).returncode == 0
            self.assertFalse(ignored, f"{keep} must be tracked")
            self.assertEqual(subprocess.run(["git", "check-ignore", "-q", os.path.join("docker", d, "x.sqlite")], cwd=self.ROOT).returncode, 0)
        self.assertEqual(subprocess.run(["git", "check-ignore", "-q", "data/ed_outrider.sqlite"], cwd=self.ROOT).returncode, 0)
        entry = self.read("docker/entrypoint.sh")
        self.assertLess(entry.index(".write-test"), entry.index("--write-config"))
        self.assertIn("sleep infinity", entry)   # waits, not a restart loop
        self.assertNotIn("exec sleep", entry)    # ...as PID 1 it must still stop on SIGTERM: trapped, the sleep in the background
        self.assertIn("trap 'exit 0' TERM", entry)

    def test_stop_grace_outlasts_the_backup_wait(self):
        """R14: Docker must not kill a backup that Outrider is still allowed to finish at shutdown."""
        import re
        m = re.search(r"stop_grace_period:\s*(\d+)([sm])", self.read("docker-compose.yml"))
        secs = int(m.group(1)) * (60 if m.group(2) == "m" else 1)
        self.assertGreaterEqual(secs, ed_outrider.BACKUP_SHUTDOWN_WAIT + 30)

    def test_launch_script(self):
        """launch_outrider.sh: runnable, valid shell, installs when requirements.txt changed (its stamp) or the
        environment is broken, and hands over to Outrider with exec (Ctrl-C and SIGTERM reach it directly)."""
        import subprocess
        path = os.path.join(self.ROOT, "launch_outrider.sh")
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", path], capture_output=True).returncode, 0)
        script = self.read("launch_outrider.sh")
        for part in ("sha256sum requirements.txt", ".requirements.sha256", "import aiohttp", "pip install --quiet -r requirements.txt",
                     'exec python ed_outrider.py "$@"', "sys.version_info < (3, 11)"):
            self.assertIn(part, script)

    def test_windows_launch_script(self):
        """launch_outrider.bat, launch_outrider.sh's twin for Windows: Windows line endings in the file and kept by git
        (.gitattributes), the same install rules, the stamp compared in Python (Wine's fc called identical files
        different: tested 2026-10-05), and a pause before a double-clicked window closes on an error."""
        with open(os.path.join(self.ROOT, "launch_outrider.bat"), "rb") as f:
            raw = f.read()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))   # every line ends in CRLF
        self.assertIn("*.bat text eol=crlf", self.read(".gitattributes").splitlines())
        script = raw.decode("ascii")
        for part in ("sys.version_info < (3, 11)", "py -3", '-m venv "%VENV%"', "pip install --quiet -r requirements.txt",
                     "import aiohttp, sys; sys.exit(open('requirements.txt', 'rb').read() != open(r'%STAMP%', 'rb').read())",
                     "copy /y requirements.txt", '"%VPY%" ed_outrider.py %*', "pause"):
            self.assertIn(part, script)
        self.assertNotIn("fc /b", script)
        labels = {line[1:].strip() for line in script.splitlines() if line.startswith(":")}
        gotos = set(re.findall(r"goto (\w+)", script))
        self.assertLessEqual(gotos, labels)   # every goto has its label

    def test_bundle_rewrites_the_compose_file(self):
        """scripts/docker_bundle.sh runs the saved image instead of a build: the two lines it rewrites are there, and the
        bundles (dist/) and your .env never go into an image."""
        compose = self.read("docker-compose.yml").splitlines()
        self.assertIn("    build: .", compose)
        self.assertIn("    image: ed-outrider:local", compose)
        self.assertLess(compose.index("name: ed-outrider"), compose.index("services:"))   # one project, whichever folder
        self.assertIn("sed -n '/^name:/,$p' docker-compose.yml", self.read("scripts/docker_bundle.sh"))
        ignored = self.read(".dockerignore").splitlines()
        self.assertTrue({"dist", ".env", "data", "docker/data", "docker/config"} <= set(ignored))
        script = self.read("scripts/docker_bundle.sh")
        self.assertIn("pull_policy: never", script)
        self.assertIn('image: $REG:latest', script)   # the release's compose file runs the published image
        self.assertIn("REG=ghcr.io/weslocke/ed-outrider", script)
        self.assertTrue(os.access(os.path.join(self.ROOT, "scripts", "docker_bundle.sh"), os.X_OK))


class NfsCaching(unittest.TestCase):
    """The journals over NFS (a Docker server): Linux caches a file's size for up to 60 s by default, so the journal
    seems not to grow and a minute of alerts comes at once (the author's server, 2026-10-04). Start-up warns unless
    the mount caches for at most a couple of seconds (actimeo=1, or noac)."""
    MOUNTS = "\n".join([
        "/dev/nvme0n1p2 / ext4 rw,relatime 0 0",
        "gamepc:/home/me/Elite\\040Dangerous /mnt/elite nfs4 rw,relatime,vers=4.2,rsize=1048576,hard,proto=tcp,timeo=600,addr=192.168.1.20 0 0",
        "gamepc:/j /mnt/quick nfs4 ro,relatime,vers=4.2,acregmin=1,acregmax=1,acdirmin=1,acdirmax=1,hard,addr=192.168.1.20 0 0",
        "gamepc:/j /mnt/noac nfs ro,sync,relatime,vers=3,noac,addr=192.168.1.20 0 0",
        "gamepc:/j /mnt/slow nfs4 ro,relatime,vers=4.2,acregmin=3,acregmax=30,addr=192.168.1.20 0 0",
        "//gamepc/elite /mnt/cifs cifs ro,relatime,vers=3.0,actimeo=1 0 0",
        "/dev/sdb1 /mnt/elite/local ext4 rw 0 0",
    ])

    def warn(self, d):
        return ed_outrider.nfs_cache_warnings([d], mounts=self.MOUNTS, realpath=lambda p: p)

    def test_default_nfs_warns(self):
        w = self.warn("/mnt/elite/Saved Games")
        self.assertEqual(len(w), 1)
        self.assertIn("60 s", w[0])
        self.assertIn("actimeo=1", w[0])

    def test_short_caching_is_fine(self):
        for d in ("/mnt/quick", "/mnt/noac/x", "/mnt/cifs", "/mnt/elite/local/j", "/home/me/journals"):
            self.assertEqual(self.warn(d), [], d)
        self.assertIn("30 s", self.warn("/mnt/slow")[0])

    def test_unreadable_mounts(self):
        self.assertEqual(ed_outrider.nfs_cache_warnings(["/mnt/elite"], mounts=None, realpath=lambda p: p,
                                                        read=lambda: (_ for _ in ()).throw(OSError("no /proc"))), [])


class StartUp(unittest.TestCase):
    def test_import_keeps_each_file(self):
        """R13: a stop part way through the start-up import keeps the journal files already read (each is committed)."""
        with tempfile.TemporaryDirectory() as d:
            jdir = os.path.join(d, "j")
            os.makedirs(jdir)
            for day in (1, 2, 3):   # three small journals, read in order
                with open(os.path.join(jdir, f"Journal.2026-10-0{day}T000000.01.log"), "w") as f:
                    f.write(f'{{"timestamp":"2026-10-0{day}T00:00:00Z","event":"Fileheader","part":1,"gameversion":"4.0","build":"x"}}\n')
            for commit_each, kept in ((True, 2), (False, 0)):
                path = os.path.join(d, f"db{commit_each}.sqlite")
                db = ed_outrider.open_db(path)
                j = ed_outrider.Journals(db)
                real, n = j.read_file, [0]

                def read(p):
                    n[0] += 1
                    if n[0] == 3:
                        raise SystemExit(0)   # the stop, during the third file
                    return real(p)
                j.read_file = read
                with self.assertRaises(SystemExit):
                    j.scan_dir(jdir, commit_each=commit_each)
                db.close()
                db = ed_outrider.open_db(path)
                got = db.execute("SELECT count(*) FROM journal_files").fetchone()[0]   # files read, with their offsets
                db.close()
                self.assertEqual(got, kept, commit_each)

    def test_backup_leftovers_swept(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("ed_outrider-2026-10-01.zip", "ed_outrider-2026-10-04.zip.part", ".db-ed_outrider-2026-10-04.sqlite",
                         "notes.txt"):
                open(os.path.join(d, name), "w").close()
            with contextlib.redirect_stdout(io.StringIO()):
                removed = ed_outrider.sweep_backup_leftovers(d)
            self.assertEqual(sorted(removed), [".db-ed_outrider-2026-10-04.sqlite", "ed_outrider-2026-10-04.zip.part"])
            self.assertEqual(sorted(os.listdir(d)), ["ed_outrider-2026-10-01.zip", "notes.txt"])
        self.assertEqual(ed_outrider.sweep_backup_leftovers("/nonexistent/backups"), [])


if __name__ == "__main__":
    unittest.main()
