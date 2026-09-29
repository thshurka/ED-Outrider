#!/usr/bin/env python3
"""ED Outrider voice lab: hear the spoken alerts in different voices before you pick one.

    python3 voice_lab.py        (or .venv/bin/python voice_lab.py)

A small window, separate from Outrider (it does not need the server running):

- Voice: any Piper voice installed in piper-voices/, with its speaker (for voices that have several)
  and a speed control.
- Download: browse every Piper voice (the catalogue on Hugging Face), filter by language or name, and
  download one into piper-voices/. Outrider's voice picker lists it too from then on.
- Lines: play a random line from speech.json, from one alert and personality or any, filled in with
  made-up values and the names you want to be called, exactly as Outrider would say it (in the personality's
  own voice and pace when speech.json gives it one). Audition plays eight key alerts in a row per personality.
  Cut this line bans the line just played (speech_banned.json, the same file the page's 👎 writes): Outrider
  and the lab never say it again.
- Your own text: type anything and hear it; Save WAV keeps the audio.

Needs Piper (pip install piper-tts, or install.sh); tkinter comes with Python on Windows and macOS, and is
the python3-tk package on some Linux distributions. Audio plays through pw-play, paplay, aplay or ffplay on
Linux, afplay on macOS and winsound on Windows.
"""
import io
import json
import os
import platform
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from collections import OrderedDict

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    sys.exit("The voice lab needs tkinter: install your distribution's python3-tk package.")

import ed_speech
import ed_tts

VOICES_DIR = ed_tts.VOICES_DIR
SPEECH_FILE = os.path.join(ed_tts.HERE, "speech.json")
CATALOGUE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
CATALOGUE_CACHE = os.path.join(VOICES_DIR, "voices.json")
CATALOGUE_MAX_AGE = 7 * 86400
# {cmdr}, {ship} and {here} for trying lines out (the lines themselves use {name}, from "Call me")
ALWAYS = {"cmdr": "Jameson", "ship": "Out There", "here": "Drojau LL-O b26-3"}
ANY_ALERT, ANY_STYLE = "any alert", "any personality"


def _config():
    """ed_outrider.toml as a dict ({} without one, without tomllib (Python before 3.11) or when it is broken)."""
    try:
        import tomllib
        with open(os.path.join(ed_tts.HERE, "ed_outrider.toml"), "rb") as f:
            cfg = tomllib.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def configured_speed():
    """speech_speed from ed_outrider.toml, so the lab starts at the pace your alerts use."""
    try:
        v = float(_config().get("defaults", {}).get("speech_speed", 1.0))
        return min(2.0, max(0.5, v))
    except Exception:   # a bad value: the voice's own pace
        return 1.0


def configured_speech_file():
    """The lines file Outrider speaks from: [server] speech_file in ed_outrider.toml, resolved as the server
    does (~ expanded, relative to the script folder), else the shipped speech.json."""
    sv = _config().get("server")
    name = sv.get("speech_file") if isinstance(sv, dict) else None
    return os.path.join(ed_tts.HERE, os.path.expanduser(str(name))) if name else SPEECH_FILE


class Player:
    """Plays a WAV file with whatever this system has; stop() cuts it short."""

    def __init__(self):
        self.proc = None
        self.path = None   # the WAV playing (or last played): removed once it is done with, see stop()
        system = platform.system()
        if system == "Windows":
            self.cmd = "winsound"
        elif system == "Darwin" and shutil.which("afplay"):
            self.cmd = ["afplay"]
        else:   # the same players, in the same order, as Outrider's "Play speech and sounds on this PC"
            found = ed_tts.find_player()
            self.cmd = found[1] if found else None

    @property
    def name(self):
        return self.cmd if isinstance(self.cmd, str) else self.cmd[0] if self.cmd else None

    def play(self, path):
        self.stop()
        self.path = path
        if self.cmd == "winsound":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif self.cmd:
            self.proc = subprocess.Popen(self.cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.cmd == "winsound":
            import winsound
            winsound.PlaySound(None, 0)
        elif self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)   # the player lets go of the file before it is removed
            except subprocess.TimeoutExpired:
                pass
        self.proc = None
        # every line is a new file: drop the previous one so a long session does not fill the temp folder
        if self.path:
            try:
                os.remove(self.path)
            except OSError:   # Windows: winsound may still hold it; the folder goes on close()
                pass
            self.path = None


class Voices:
    """Installed Piper voices, loaded on first use. Only the last MAX_LOADED stay loaded (each high-quality model
    is 100 MB or more in memory, so trying a dozen would otherwise grow the lab past 2 GB); the voice selected
    above (`current`) is never the one let go."""

    MAX_LOADED = 2

    def __init__(self):
        self.PiperVoice = ed_tts._import_piper()
        self.loaded = OrderedDict()   # least recently used first
        self.current = None
        self.lock = threading.Lock()

    def installed(self):
        return ed_tts.installed_voices(VOICES_DIR)

    @staticmethod
    def speakers(name):
        """[(label, id)] for a voice with several speakers, else []."""
        try:
            with open(os.path.join(VOICES_DIR, name + ".onnx.json"), encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            return []
        n = cfg.get("num_speakers") or 1
        if n <= 1:
            return []
        by_id = {v: k for k, v in (cfg.get("speaker_id_map") or {}).items()}
        return [(f"{i}: {by_id[i]}" if i in by_id and by_id[i] != str(i) else str(i), i) for i in range(n)]

    def load(self, name):
        with self.lock:
            if name not in self.loaded:
                self.loaded[name] = self.PiperVoice.load(os.path.join(VOICES_DIR, name + ".onnx"))
            self.loaded.move_to_end(name)
            voice = self.loaded[name]
            # let go of the least recently used ones, never the one just asked for or the selected one
            for old in [n for n in self.loaded if n not in (name, self.current)][:max(0, len(self.loaded) - self.MAX_LOADED)]:
                del self.loaded[old]
            return voice

    def synth(self, name, text, speaker=None, speed=1.0):
        from piper import SynthesisConfig   # importable once _import_piper found Piper
        voice = self.load(name)
        cfg = SynthesisConfig(speaker_id=speaker, length_scale=1.0 / speed if speed else None)
        buf = io.BytesIO()
        with self.lock, wave.open(buf, "wb") as wf:
            voice.synthesize_wav(text, wf, syn_config=cfg)
        return buf.getvalue()


def fetch_catalogue(force=False):
    """Piper's voices.json: {voice: {language, quality, num_speakers, files: {path: {size_bytes, md5_digest}}}}.
    Kept in piper-voices/ for a week."""
    if not force and os.path.exists(CATALOGUE_CACHE) and time.time() - os.path.getmtime(CATALOGUE_CACHE) < CATALOGUE_MAX_AGE:
        try:
            with open(CATALOGUE_CACHE, encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict):
                return doc
        except (OSError, ValueError):   # a cut-short copy: fetch it again rather than trust it for a week
            pass
    with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as r:
        data = r.read()
    doc = json.loads(data)
    os.makedirs(VOICES_DIR, exist_ok=True)
    # a temp file moved into place: an interrupted write never leaves a truncated catalogue behind
    fd, part = tempfile.mkstemp(dir=VOICES_DIR, prefix="voices.json.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(part, 0o644)
        os.replace(part, CATALOGUE_CACHE)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return doc


def download(entry, progress):
    """Download a catalogue entry's model and config into piper-voices/ (via .part files, checked against
    the catalogue's MD5 and moved into place only when both are complete, so an interrupted download never
    looks installed or leaves anything behind: see ed_tts.download_voice_files). progress(done, total)."""
    files = [(p, m) for p, m in entry["files"].items() if p.endswith((".onnx", ".onnx.json"))]
    ed_tts.download_voice_files(files, VOICES_DIR, progress)


def load_lines(path=None):
    """(styles, lines) from the speech file, less the lines banned in speech_banned.json (as Outrider sees them)."""
    path = path or configured_speech_file()
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    lines, _ = ed_speech.apply_bans(doc.get("lines") or {}, ed_speech.read_bans(ed_speech.banned_path(path)))
    return doc.get("styles") or {}, lines


class Lab:
    def __init__(self, root):
        self.root, self.q = root, queue.Queue()
        self.player, self.voices = Player(), Voices()
        self.tmp = tempfile.mkdtemp(prefix="outrider-voice-")
        self.catalogue, self.last_line, self.busy = {}, None, False
        self.last_pick = None   # (alert, personality, line) of the random line on show: what "Cut this line" bans
        self.line_pace = None   # (text, personality speed) of the last random line: see speak()
        self.line_voice = None  # (text, personality's own voice, personality) of the last random line: see synth_args()
        self.audition_run = None   # the audition playing (a fresh object per run): Stop, Speak and the rest end it
        self.speech_file = configured_speech_file()   # [server] speech_file: the lines Outrider speaks
        try:
            self.styles, self.lines = load_lines(self.speech_file)
            self.lines_error = None
        except (OSError, ValueError) as e:
            self.styles, self.lines, self.lines_error = {}, {}, \
                f"{os.path.basename(self.speech_file)} could not be read: {e}"
        root.title("ED Outrider voice lab")
        root.minsize(760, 640)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.build()
        self.refresh_installed()
        self.root.after(100, self.pump)
        self.run(lambda: fetch_catalogue(), self.show_catalogue, "reading the voice catalogue…")

    # ---- background work: threads hand results back to the Tk thread through a queue ----
    def pump(self):
        try:
            while True:
                try:
                    callback = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    callback()
                except Exception as e:   # e.g. a WAV saved to a read-only folder: say so, keep the queue running
                    self.set_status(f"{type(e).__name__}: {e}", error=True)
        finally:
            self.root.after(80, self.pump)

    def run(self, work, done=None, status=None):
        if status:
            self.set_status(status)

        def go():
            try:
                result = work()
                self.q.put(lambda: done(result) if done else None)
            except Exception as e:   # shown in the status line, never a silent failure
                msg = f"{type(e).__name__}: {e}"
                self.q.put(lambda: self.set_status(msg, error=True))
        threading.Thread(target=go, daemon=True).start()

    def set_status(self, text, error=False):
        self.status.configure(text=text, foreground="#c0392b" if error else "")

    # ---- layout ----
    def build(self):
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        # voice
        vf = ttk.LabelFrame(outer, text="Voice", padding=8)
        vf.grid(row=0, column=0, sticky="ew", **pad)
        vf.columnconfigure(1, weight=1)
        ttk.Label(vf, text="Voice").grid(row=0, column=0, sticky="w")
        self.voice = ttk.Combobox(vf, state="readonly", width=40)
        self.voice.grid(row=0, column=1, sticky="ew", padx=6)
        self.voice.bind("<<ComboboxSelected>>", lambda e: self.voice_changed())
        ttk.Label(vf, text="Speaker").grid(row=0, column=2, sticky="w")
        self.speaker = ttk.Combobox(vf, state="disabled", width=22)
        self.speaker.grid(row=0, column=3, padx=6)
        ttk.Label(vf, text="Speed").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.default_speed = configured_speed()
        self.speed = tk.DoubleVar(value=self.default_speed)
        sc = ttk.Scale(vf, from_=0.5, to=2.0, variable=self.speed)
        sc.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        self.speed_label = ttk.Label(vf, text=f"{self.default_speed:.2f}×", width=6)
        self.speed_label.grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.speed.trace_add("write", lambda *_: self.speed_label.configure(text=f"{self.speed.get():.2f}×"))
        ttk.Button(vf, text="Reset speed", command=lambda: self.speed.set(self.default_speed)).grid(row=1, column=3, sticky="w", padx=6, pady=(6, 0))

        # lines
        lf = ttk.LabelFrame(outer, text=f"Lines from {os.path.basename(self.speech_file)}", padding=8)
        lf.grid(row=1, column=0, sticky="ew", **pad)
        lf.columnconfigure(1, weight=1)
        lf.columnconfigure(3, weight=1)
        ttk.Label(lf, text="Alert").grid(row=0, column=0, sticky="w")
        self.alert = ttk.Combobox(lf, state="readonly", values=[ANY_ALERT] + list(ed_speech.KEYS))
        self.alert.set(ANY_ALERT)
        self.alert.grid(row=0, column=1, sticky="ew", padx=6)
        self.alert.bind("<<ComboboxSelected>>", lambda e: self.alert_changed())
        ttk.Label(lf, text="Personality").grid(row=0, column=2, sticky="w")
        self.style_keys = [ANY_STYLE] + [x for s in self.styles for x in (s, s + "_profane")
                                         if any(isinstance(e, dict) and e.get(x) for e in self.lines.values())]
        self.style = ttk.Combobox(lf, state="readonly", values=[self.style_label(x) for x in self.style_keys])
        self.style.current(0)
        self.style.grid(row=0, column=3, sticky="ew", padx=6)
        self.style.bind("<<ComboboxSelected>>", lambda e: self.style_changed())
        ttk.Label(lf, text="Call me").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.names = ttk.Entry(lf)
        self.names.insert(0, ed_speech.DEFAULT_NAMES)
        self.names.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Label(lf, text="comma separated; each {name} is a random one", foreground="#777").grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.when = ttk.Label(lf, text="", foreground="#777", wraplength=680)
        self.when.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        lb = ttk.Frame(lf)
        lb.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(lb, text="▶ Random line", command=self.random_line).pack(side="left")
        ttk.Button(lb, text="▶ Audition", command=self.audition).pack(side="left", padx=6)
        ttk.Button(lb, text="✂ Cut this line", command=self.cut_line).pack(side="left")
        self.picked = ttk.Label(lf, text=self.lines_error or "", foreground="#c0392b" if self.lines_error else "#777")
        self.picked.grid(row=3, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.alert_changed()

        # text
        tf = ttk.LabelFrame(outer, text="Text to speak (a random line lands here; type your own too)", padding=8)
        tf.grid(row=2, column=0, sticky="nsew", **pad)
        outer.rowconfigure(2, weight=1)
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        self.text = tk.Text(tf, height=4, wrap="word")
        self.text.grid(row=0, column=0, columnspan=4, sticky="nsew")
        self.text.insert("1.0", "Welcome aboard. This is how I sound.")
        self.text.bind("<Control-Return>", lambda e: (self.end_audition(), self.speak(), "break")[2])
        bf = ttk.Frame(tf)
        bf.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(bf, text="▶ Speak", command=lambda: (self.end_audition(), self.speak())).pack(side="left")
        ttk.Button(bf, text="■ Stop", command=self.stop).pack(side="left", padx=6)
        ttk.Button(bf, text="Save WAV…", command=self.save_wav).pack(side="left")
        ttk.Label(bf, text="Ctrl+Enter speaks", foreground="#777").pack(side="left", padx=10)

        # download
        df = ttk.LabelFrame(outer, text="Download a voice (Piper voices on Hugging Face)", padding=8)
        df.grid(row=3, column=0, sticky="nsew", **pad)
        outer.rowconfigure(3, weight=2)
        df.columnconfigure(1, weight=1)
        df.rowconfigure(1, weight=1)
        ttk.Label(df, text="Filter").grid(row=0, column=0, sticky="w")   # a language, or part of a voice's name
        self.filter = ttk.Entry(df)
        self.filter.insert(0, "English")
        self.filter.grid(row=0, column=1, sticky="ew", padx=6)
        self.filter.bind("<KeyRelease>", lambda e: self.show_catalogue(self.catalogue))
        ttk.Button(df, text="Refresh list", command=lambda: self.run(lambda: fetch_catalogue(force=True), self.show_catalogue, "fetching the voice catalogue…")).grid(row=0, column=2)
        cols = ("language", "quality", "speakers", "size", "installed")
        self.tree = ttk.Treeview(df, columns=cols, height=7, selectmode="browse")
        self.tree.heading("#0", text="voice")
        self.tree.column("#0", width=280)
        for c, w in zip(cols, (170, 70, 70, 70, 70)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c == "language" else "center")
        self.tree.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        sb = ttk.Scrollbar(df, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=3, sticky="ns", pady=(6, 0))
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self.download_selected())
        af = ttk.Frame(df)
        af.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        af.columnconfigure(1, weight=1)
        self.dl_btn = ttk.Button(af, text="Download selected", command=self.download_selected)
        self.dl_btn.grid(row=0, column=0)
        self.bar = ttk.Progressbar(af, maximum=1.0)
        self.bar.grid(row=0, column=1, sticky="ew", padx=8)

        self.status = ttk.Label(outer, text="", anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", **pad)
        if not self.voices.PiperVoice:
            self.set_status("Piper is not installed, so nothing can be spoken: pip install piper-tts (or run install.sh). Lines can still be browsed.", error=True)
        elif not self.player.cmd:
            self.set_status("No audio player found (pw-play, paplay, aplay or ffplay): Save WAV still works.", error=True)

    # ---- voices ----
    def refresh_installed(self, select=None):
        names = self.voices.installed()
        self.voice.configure(values=names)
        want = select or self.voice.get() or (ed_tts.DEFAULT_VOICE if ed_tts.DEFAULT_VOICE in names else names[0] if names else "")
        self.voice.set(want if want in names else "")
        self.voice_changed()

    def voice_changed(self):
        name = self.voice.get()
        self.voices.current = name or None
        spk = self.voices.speakers(name) if name else []
        self.speaker_ids = [i for _, i in spk]
        self.speaker.configure(values=[l for l, _ in spk], state="readonly" if spk else "disabled")
        self.speaker.set(spk[0][0] if spk else "")
        if name and self.voices.PiperVoice:   # load now, so the first Speak is quick
            self.run(lambda: self.voices.load(name), lambda _: self.set_status(f"{name} ready" + (f" · {len(spk)} speakers" if spk else "")),
                     f"loading {name}…")
        elif not name:
            self.set_status("No voice installed yet: download one below.")

    def show_catalogue(self, cat):
        self.catalogue = cat or {}
        want = self.filter.get().strip().lower()
        installed = set(self.voices.installed())
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for key in sorted(self.catalogue):
            v = self.catalogue[key]
            lang = v.get("language") or {}
            language = f"{lang.get('name_english', '')} ({lang.get('country_english', '')})"
            if want and want not in key.lower() and want not in language.lower():
                continue
            size = sum(m.get("size_bytes") or 0 for p, m in (v.get("files") or {}).items() if p.endswith(".onnx"))
            self.tree.insert("", "end", iid=key, text=key, values=(language, v.get("quality", ""), v.get("num_speakers", 1),
                                                                    f"{size / 1e6:.0f} MB", "✓" if key in installed else ""))
            shown += 1
        if self.catalogue:
            self.set_status(f"{shown} of {len(self.catalogue)} voices shown · double-click one to download it")

    def download_selected(self):
        sel = self.tree.selection()
        if not sel or self.busy:
            return
        key = sel[0]
        if key in self.voices.installed():
            self.refresh_installed(select=key)
            self.set_status(f"{key} is already installed: selected it above")
            return
        self.busy = True
        self.dl_btn.configure(state="disabled")
        self.bar["value"] = 0

        def progress(done, total):
            self.q.put(lambda: (self.bar.configure(value=done / total if total else 0),
                                self.set_status(f"downloading {key}: {done / 1e6:.0f} of {total / 1e6:.0f} MB")))

        def finished(_):
            self.busy = False
            self.dl_btn.configure(state="normal")
            self.show_catalogue(self.catalogue)
            self.refresh_installed(select=key)

        def work():
            try:
                download(self.catalogue[key], progress)
            finally:
                self.q.put(lambda: (setattr(self, "busy", False), self.dl_btn.configure(state="normal")))
        self.run(work, finished, f"downloading {key}…")

    # ---- lines ----
    @staticmethod
    def style_label(key):
        return key if key == ANY_STYLE else key.replace("_profane", ", with profanity").capitalize()

    def style_changed(self):
        """A personality with a voice of its own in speech.json (see ed_speech.style_voice): preselect it."""
        chosen = self.style_keys[self.style.current()] if self.style.current() > 0 else None
        voice, _ = ed_speech.style_voice(self.styles, chosen)
        if voice and voice != self.voice.get() and voice in self.voices.installed():
            self.refresh_installed(select=voice)

    def alert_changed(self):
        a = self.alert.get()
        self.when.configure(text="" if a == ANY_ALERT else f"When: {ed_speech.KEYS.get(a, '')}")

    def chosen_style(self):
        return self.style_keys[self.style.current()] if self.style.current() > 0 else None

    def pick_line(self, alerts, styles):
        """A random (alert, personality, line) from those alerts and personalities, not the last one heard."""
        pool = [(a, s, line) for a in alerts for s in styles
                for line in (self.lines.get(a, {}).get(s) or []) if isinstance(line, str)]
        if not pool:
            return None
        pick = random.choice([p for p in pool if p[2] != self.last_line] or pool)
        self.last_line = pick[2]
        return pick

    def show_line(self, alert, style, line):
        """A line filled in and put in the text box, as Outrider would say it."""
        values = dict(ALWAYS, **ed_speech.SAMPLES.get(alert, {}))
        text = ed_speech.spoken_text(ed_speech.fill(line, values, self.names.get()))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.picked.configure(text=f"{alert} · {self.style_label(style)}", foreground="#777")
        self.last_pick = (alert, style, line)
        # a personality's own voice and pace in speech.json, as in Outrider (kept while this line is the text):
        # its voice wins over the lab's, its pace multiplies yours
        voice, pace = ed_speech.style_voice(self.styles, style)
        self.line_pace = (self.current_text(), pace) if pace else None
        self.line_voice = (self.current_text(), voice, style.removesuffix("_profane")) if voice else None

    def random_line(self):
        self.end_audition()
        if not self.lines:
            return
        alerts = [k for k in self.lines if isinstance(self.lines[k], dict)] if self.alert.get() == ANY_ALERT else [self.alert.get()]
        chosen = self.chosen_style()
        pick = self.pick_line(alerts, [chosen] if chosen else self.style_keys[1:])
        if not pick:
            self.picked.configure(text="no lines for that alert and personality", foreground="#c0392b")
            return
        self.show_line(*pick)
        self.speak()

    def cut_line(self):
        """Ban the random line on show, in speech_banned.json next to the speech file (the page's 👎 writes the same
        file), and drop it from the lab's lists. The last line of a list stays, so no alert ever goes quiet."""
        if not self.last_pick:
            self.picked.configure(text="play a random line first, then cut it", foreground="#c0392b")
            return
        alert, style, line = self.last_pick
        status, out = ed_speech.ban_line(self.speech_file, alert, line)
        if status != 200:
            self.picked.configure(text=f"not cut: {out.get('error')}", foreground="#c0392b")
            return
        self.last_pick = None
        entry = self.lines.get(alert) or {}
        for k, versions in entry.items():   # a ban covers the wording in every list of the alert
            if isinstance(versions, list) and line in versions and len(versions) > 1:
                entry[k] = [x for x in versions if x != line]
        self.picked.configure(text=f"cut from {alert} · {self.style_label(style)} ({out['banned']} banned in all)", foreground="#777")

    # ---- audition: eight key alerts in a row, per personality, each in its own voice ----
    def audition(self):
        """The alerts in ed_speech.AUDITION for the chosen personality (or each one in turn, clean lines only),
        grouped by personality so each voice loads once, with a two-second gap between lines."""
        self.end_audition()
        chosen = self.chosen_style()
        styles = [chosen] if chosen else [s for s in self.style_keys[1:] if not s.endswith("_profane")]
        steps = [(s, k) for s in styles for k in ed_speech.AUDITION
                 if any(isinstance(x, str) for x in (self.lines.get(k, {}).get(s) or []))]   # a pair without lines is skipped
        if not steps:
            self.picked.configure(text="no lines to audition", foreground="#c0392b")
            return
        run = self.audition_run = object()
        self.audition_step(run, steps, 0)

    def audition_step(self, run, steps, i):
        if self.audition_run is not run:
            return   # stopped, or another run began
        if i >= len(steps):
            self.audition_run = None
            self.set_status("audition finished")
            return
        style, key = steps[i]
        self.show_line(*self.pick_line([key], [style]))
        # the gap after this line loads the next personality's own voice, so the switch does not pause
        nxt = steps[i + 1][0] if i + 1 < len(steps) else None
        if nxt and nxt != style:
            voice, _ = ed_speech.style_voice(self.styles, nxt)
            if voice and voice in self.voices.installed() and self.voices.PiperVoice:
                self.run(lambda: self.voices.load(voice))
        self.speak(note=f"audition {i + 1} of {len(steps)}: {self.style_label(style)} · {key}",
                   then=lambda secs: self.root.after(int(secs * 1000) + 2000, lambda: self.audition_step(run, steps, i + 1)))

    def end_audition(self):
        if self.audition_run is not None:
            self.audition_run = None
            self.player.stop()

    def stop(self):
        self.audition_run = None
        self.player.stop()

    # ---- speaking ----
    def current_text(self):
        return ed_speech.spoken_text(self.text.get("1.0", "end"))

    def synth_args(self):
        """(voice, speaker, speed, personality pace, personality whose own voice it is): the speed is the slider
        times the pace of the personality whose line is in the text box (1.0 for anything else), within Piper's
        0.5-2. That personality's own voice (speech.json) replaces the lab's when it is installed, with its first
        speaker as in Outrider; with "any personality" too, not only when one is chosen."""
        name = self.voice.get()
        spk = self.speaker_ids[self.speaker.current()] if self.speaker_ids and self.speaker.current() >= 0 else None
        speed = float(self.speed.get())
        text = self.current_text()
        pace = self.line_pace[1] if self.line_pace and self.line_pace[0] == text else None
        own = None
        if self.line_voice and self.line_voice[0] == text and self.line_voice[1] in self.voices.installed():
            if self.line_voice[1] != name:
                name, spk = self.line_voice[1], None
            own = self.line_voice[2]
        return name, spk, round(min(2.0, max(0.5, speed * (pace or 1.0))), 2), pace, own

    def speak(self, note=None, then=None):
        """Say the text box. `then(seconds)` is called once it starts playing, with its length (the audition's
        next step); `note` leads the status line."""
        text, (name, spk, speed, pace, own) = self.current_text(), self.synth_args()
        if not text:
            return
        if not self.voices.PiperVoice or not name:
            self.set_status("No voice to speak with: install Piper and download a voice below.", error=True)
            return

        def play(audio):
            path = os.path.join(self.tmp, f"say-{time.time_ns()}.wav")
            with open(path, "wb") as f:
                f.write(audio)
            self.player.play(path)
            self.set_status((f"{note} · " if note else "") + f"speaking with {name}" + (f", speaker {spk}" if spk is not None else "")
                            + (f" ({own}'s own voice)" if own else "") + f" at {speed:.2f}×"
                            + (f" (the personality's {pace:g}× pace)" if pace else ""))
            if then:
                with wave.open(io.BytesIO(audio)) as wf:   # its length from the header: winsound cannot be polled
                    then(wf.getnframes() / (wf.getframerate() or 22050))
        self.run(lambda: self.voices.synth(name, text, spk, speed), play, f"synthesising with {name}…")

    def save_wav(self):
        text, (name, spk, speed, _, _) = self.current_text(), self.synth_args()
        if not text or not name or not self.voices.PiperVoice:
            return
        path = filedialog.asksaveasfilename(defaultextension=".wav", filetypes=[("WAV audio", "*.wav")],
                                            initialfile=f"{name}.wav")
        if not path:
            return

        def write(audio):
            with open(path, "wb") as f:
                f.write(audio)
            self.set_status(f"saved {path}")
        self.run(lambda: self.voices.synth(name, text, spk, speed), write, "synthesising…")

    def close(self):
        self.audition_run = None
        self.player.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        Lab(root)
    except Exception as e:
        messagebox.showerror("ED Outrider voice lab", f"{type(e).__name__}: {e}")
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
