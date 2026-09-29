#!/usr/bin/env python3
"""ED Outrider voice lab: hear the spoken alerts in different voices before you pick one.

    python3 voice_lab.py        (or .venv/bin/python voice_lab.py)

A small window, separate from Outrider (it does not need the server running):

- Voice: any Piper voice installed in piper-voices/, with its speaker (for voices that have several)
  and a speed control.
- Download: browse every Piper voice (the catalogue on Hugging Face), filter by language or name, and
  download one into piper-voices/. Outrider's voice picker lists it too from then on.
- Lines: play a random line from speech.json, from one alert and personality or any, filled in with
  made-up values and the names you want to be called, exactly as Outrider would say it.
- Your own text: type anything and hear it; Save WAV keeps the audio.

Needs Piper (pip install piper-tts, or install.sh); tkinter comes with Python on Windows and macOS, and is
the python3-tk package on some Linux distributions. Audio plays through pw-play, paplay, aplay or ffplay on
Linux, afplay on macOS and winsound on Windows.
"""
import glob
import hashlib
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
FILE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{path}?download=true"
CATALOGUE_CACHE = os.path.join(VOICES_DIR, "voices.json")
CATALOGUE_MAX_AGE = 7 * 86400
# {cmdr}, {ship} and {here} for trying lines out (the lines themselves use {name}, from "Call me")
ALWAYS = {"cmdr": "Jameson", "ship": "Out There", "here": "Drojau LL-O b26-3"}
ANY_ALERT, ANY_STYLE = "any alert", "any personality"


def configured_speed():
    """speech_speed from ed_outrider.toml, so the lab starts at the pace your alerts use."""
    try:
        import tomllib
        with open(os.path.join(ed_tts.HERE, "ed_outrider.toml"), "rb") as f:
            v = float(tomllib.load(f).get("defaults", {}).get("speech_speed", 1.0))
        return min(2.0, max(0.5, v))
    except Exception:   # no config, no tomllib (Python before 3.11), a bad value: the voice's own pace
        return 1.0


class Player:
    """Plays a WAV file with whatever this system has; stop() cuts it short."""

    def __init__(self):
        self.proc = None
        system = platform.system()
        if system == "Windows":
            self.cmd = "winsound"
        elif system == "Darwin" and shutil.which("afplay"):
            self.cmd = ["afplay"]
        else:
            self.cmd = next((c for c in (["pw-play"], ["paplay"], ["aplay", "-q"],
                                         ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"])
                             if shutil.which(c[0])), None)

    @property
    def name(self):
        return self.cmd if isinstance(self.cmd, str) else self.cmd[0] if self.cmd else None

    def play(self, path):
        self.stop()
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
        self.proc = None


class Voices:
    """Installed Piper voices, loaded on first use and kept."""

    def __init__(self):
        self.PiperVoice = ed_tts._import_piper()
        self.loaded = {}
        self.lock = threading.Lock()

    def installed(self):
        return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(VOICES_DIR, "*.onnx")))

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
            return self.loaded[name]

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
        with open(CATALOGUE_CACHE, encoding="utf-8") as f:
            return json.load(f)
    with urllib.request.urlopen(CATALOGUE_URL, timeout=30) as r:
        data = r.read()
    doc = json.loads(data)
    os.makedirs(VOICES_DIR, exist_ok=True)
    with open(CATALOGUE_CACHE, "wb") as f:
        f.write(data)
    return doc


def download(entry, progress):
    """Download a catalogue entry's model and config into piper-voices/ (via .part files, checked against
    the catalogue's MD5, so an interrupted download never looks installed). progress(done, total)."""
    files = [(p, m) for p, m in entry["files"].items() if p.endswith((".onnx", ".onnx.json"))]
    total, done = sum(m.get("size_bytes") or 0 for _, m in files), 0
    os.makedirs(VOICES_DIR, exist_ok=True)
    for path, meta in sorted(files, key=lambda x: x[0].endswith(".onnx")):   # config first, model last
        dest = os.path.join(VOICES_DIR, os.path.basename(path))
        part, md5 = dest + ".part", hashlib.md5()
        with urllib.request.urlopen(FILE_URL.format(path=path), timeout=60) as r, open(part, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
                md5.update(chunk)
                done += len(chunk)
                progress(done, total)
        if meta.get("md5_digest") and md5.hexdigest() != meta["md5_digest"]:
            os.remove(part)
            raise IOError(f"{os.path.basename(path)} did not download correctly (checksum mismatch); try again")
        os.replace(part, dest)


def load_lines():
    with open(SPEECH_FILE, encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("styles") or {}, doc.get("lines") or {}


class Lab:
    def __init__(self, root):
        self.root, self.q = root, queue.Queue()
        self.player, self.voices = Player(), Voices()
        self.tmp = tempfile.mkdtemp(prefix="outrider-voice-")
        self.catalogue, self.last_line, self.busy = {}, None, False
        try:
            self.styles, self.lines = load_lines()
            self.lines_error = None
        except (OSError, ValueError) as e:
            self.styles, self.lines, self.lines_error = {}, {}, f"speech.json could not be read: {e}"
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
                self.q.get_nowait()()
        except queue.Empty:
            pass
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
        lf = ttk.LabelFrame(outer, text="Lines from speech.json", padding=8)
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
        ttk.Label(lf, text="Call me").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.names = ttk.Entry(lf)
        self.names.insert(0, ed_speech.DEFAULT_NAMES)
        self.names.grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Label(lf, text="comma separated; each {name} is a random one", foreground="#777").grid(row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self.when = ttk.Label(lf, text="", foreground="#777", wraplength=680)
        self.when.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Button(lf, text="▶ Random line", command=self.random_line).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
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
        self.text.bind("<Control-Return>", lambda e: (self.speak(), "break")[1])
        bf = ttk.Frame(tf)
        bf.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(bf, text="▶ Speak", command=self.speak).pack(side="left")
        ttk.Button(bf, text="■ Stop", command=self.player.stop).pack(side="left", padx=6)
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

    def alert_changed(self):
        a = self.alert.get()
        self.when.configure(text="" if a == ANY_ALERT else f"When: {ed_speech.KEYS.get(a, '')}")

    def random_line(self):
        if not self.lines:
            return
        alerts = [k for k in self.lines if isinstance(self.lines[k], dict)] if self.alert.get() == ANY_ALERT else [self.alert.get()]
        chosen = self.style_keys[self.style.current()] if self.style.current() > 0 else None
        pool = [(a, s, line) for a in alerts for s in ([chosen] if chosen else self.style_keys[1:])
                for line in (self.lines.get(a, {}).get(s) or []) if isinstance(line, str)]
        if not pool:
            self.picked.configure(text="no lines for that alert and personality", foreground="#c0392b")
            return
        fresh = [p for p in pool if p[2] != self.last_line] or pool
        alert, style, line = random.choice(fresh)
        self.last_line = line
        values = dict(ALWAYS, **ed_speech.SAMPLES.get(alert, {}))
        text = ed_speech.spoken_text(ed_speech.fill(line, values, self.names.get()))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.picked.configure(text=f"{alert} · {self.style_label(style)}", foreground="#777")
        self.speak()

    # ---- speaking ----
    def current_text(self):
        return ed_speech.spoken_text(self.text.get("1.0", "end"))

    def synth_args(self):
        name = self.voice.get()
        spk = self.speaker_ids[self.speaker.current()] if self.speaker_ids and self.speaker.current() >= 0 else None
        return name, spk, round(float(self.speed.get()), 2)

    def speak(self):
        text, (name, spk, speed) = self.current_text(), self.synth_args()
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
            self.set_status(f"speaking with {name}" + (f", speaker {spk}" if spk is not None else "") + f" at {speed:.2f}×")
        self.run(lambda: self.voices.synth(name, text, spk, speed), play, f"synthesising with {name}…")

    def save_wav(self):
        text, (name, spk, speed) = self.current_text(), self.synth_args()
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
