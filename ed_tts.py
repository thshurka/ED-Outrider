"""Spoken alerts with Piper, a neural text-to-speech engine that runs on the CPU (optional).

Piper is not required: without it the page falls back to the browser's own speech. To use it:

    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install piper-tts

Outrider finds Piper whether it is started with .venv/bin/python or plain python3 (a .venv next to
this script is searched when the system Python has no Piper). Voices live in piper-voices/ next to
the script; a configured voice that is missing is downloaded there in the background on first use
(about 63 MB each, from the Piper voices repository on Hugging Face). Installing them beforehand
with `python -m piper.download_voices --download-dir piper-voices <voice>` just skips that wait.
"""
import glob
import hashlib
import io
import os
import re
import sys
import tempfile
import threading
import urllib.request
import wave
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(HERE, "piper-voices")
DEFAULT_VOICE = "en_GB-southern_english_female-low"
DEFAULT_FALLBACK = "en_GB-jenny_dioco-medium"
CACHE_PHRASES = 50
# Personalities in speech.json may name a voice of their own ("sarcastic": {"label": ..., "voice": ...}). Up to
# this many of those stay loaded beside the main voice (each is some 60-100 MB in memory), least recently used
# dropped first: EXTRA_VOICES, or as many as speech.json's personalities name (Speaker.size_extra) up to
# EXTRA_VOICES_MAX, so three personalities with a voice each do not reload one before every other line.
# They are loaded on first use and never downloaded: a voice that is not installed is spoken in the main voice.
EXTRA_VOICES = 2
EXTRA_VOICES_MAX = 4
# A Piper voice name (language_REGION-name-quality). Piper's own pattern also lets '/' and '..' through,
# which would write the download outside piper-voices/.
VOICE_NAME = re.compile(r"^[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-(x_low|low|medium|high)$")
FILE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{path}?download=true"
# The longest line spoken (about a minute of speech): a cap on the synthesis work one request can ask for.
# A longer line is cut at a sentence or clause boundary, never mid-word (see clip_text).
SAY_MAX = 1000


def clip_text(text, limit=SAY_MAX):
    """`text` with its whitespace collapsed, and if longer than `limit`, cut back to the last sentence end
    ('. ', '! ', '? '), else the last clause (', ', '; ', ': ', ending the line with '.'), else the last word,
    so the voice never stops mid-word. A boundary in the first half is not used: that would drop too much."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    head = text[:limit + 1]   # one more: a boundary right at the limit counts
    for pattern, keep in ((r"[.!?](?= )", 1), (r"[,;:](?= )", 0)):
        ends = [m.start() for m in re.finditer(pattern, head) if m.start() < limit]
        if ends and ends[-1] >= limit // 2:
            return head[:ends[-1] + keep] + ("" if keep else ".")
    space = head.rfind(" ")
    return head[:space] if space >= limit // 2 else text[:limit]


def installed_voices(voices_dir):
    """Voices in voices_dir that have both files (the model and its .onnx.json config): Piper needs both."""
    return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(glob.escape(voices_dir), "*.onnx"))
                  if os.path.exists(p + ".json"))


def voice_paths(name):
    """A voice's config and model in the Piper voices repository:
    'en_GB-alan-low' -> ['en/en_GB/alan/low/en_GB-alan-low.onnx.json', '.../en_GB-alan-low.onnx']."""
    if not VOICE_NAME.fullmatch(name or ""):
        raise ValueError(f"{name!r} is not a Piper voice name (language_REGION-name-quality)")
    lang, voice, quality = name.split("-")
    base = f"{lang.split('_')[0]}/{lang}/{voice}/{quality}/{name}"
    return [base + ".onnx.json", base + ".onnx"]


def download_voice_files(files, voices_dir, progress=None, timeout=60):
    """Download [(repository path, {"size_bytes", "md5_digest"} or {})] into voices_dir. Each file goes to a
    .part first, and they are moved into place only once every one has arrived complete (length and, when
    given, MD5 checked), the model last: an interrupted download never leaves a voice that looks installed,
    or stray .part files. `timeout` is per read, so a stalled connection fails instead of hanging.
    progress(done, total) after each chunk (total is 0 when the sizes are not known)."""
    total, done, parts = sum((m or {}).get("size_bytes") or 0 for _, m in files), 0, []
    os.makedirs(voices_dir, exist_ok=True)
    try:
        for path, meta in sorted(files, key=lambda x: x[0].endswith(".onnx")):   # the small config first
            dest = os.path.join(voices_dir, os.path.basename(path))
            # a .part of its own: two downloads of the same voice at once (Outrider starting while the voice lab
            # fetches it) must not write into one file, or one installs a mix and the other finds its file gone
            fd, part = tempfile.mkstemp(dir=voices_dir, prefix=os.path.basename(path) + ".", suffix=".part")
            parts.append((part, dest))
            md5, got = hashlib.md5(), 0
            os.chmod(part, 0o644)   # mkstemp's 0600 would carry over to the installed voice
            with os.fdopen(fd, "wb") as f, urllib.request.urlopen(FILE_URL.format(path=path), timeout=timeout) as r:
                size = r.headers.get("Content-Length") if getattr(r, "headers", None) else None
                while chunk := r.read(1 << 16):
                    f.write(chunk)
                    md5.update(chunk)
                    got += len(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            name = os.path.basename(path)
            if not got or (size and size.isdigit() and got != int(size)):
                raise IOError(f"{name} did not download completely ({got} bytes); try again")
            if (meta or {}).get("md5_digest") and md5.hexdigest() != meta["md5_digest"]:
                raise IOError(f"{name} did not download correctly (checksum mismatch); try again")
    except BaseException:   # a network error, a full disk, Ctrl-C: nothing half-written stays behind
        for part, _ in parts:
            try:
                os.remove(part)
            except OSError:
                pass
        raise
    for part, dest in sorted(parts, key=lambda x: x[1].endswith(".onnx")):   # config first, model last
        os.replace(part, dest)


def _import_piper():
    """PiperVoice, from this interpreter or from a .venv next to the script; None if neither has it."""
    try:
        from piper import PiperVoice
        return PiperVoice
    except ImportError:
        pass
    venv = os.path.join(HERE, ".venv", "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.isdir(venv) and venv not in sys.path:
        sys.path.append(venv)
        try:
            from piper import PiperVoice
            return PiperVoice
        except ImportError:
            sys.path.remove(venv)
    return None


class Speaker:
    """Turns short alert phrases into WAV audio. Loading and downloading happen on a background thread;
    `say()` returns None until a voice is ready, and the page uses browser speech meanwhile."""

    def __init__(self, voice=DEFAULT_VOICE, fallback=DEFAULT_FALLBACK, voices_dir=VOICES_DIR, on_change=None,
                 on_switched=None):
        self.on_change = on_change or (lambda: None)   # called (from the thread) when status changes
        # called (from the thread) with the voice name once a use() switch has it speaking: the place to
        # remember the choice (a choice that never loads must not be tried again at the next start)
        self.on_switched = on_switched or (lambda name: None)
        self.PiperVoice = _import_piper()
        self.SynthesisConfig = None
        if self.PiperVoice:
            from piper import SynthesisConfig   # importable once _import_piper found Piper
            self.SynthesisConfig = SynthesisConfig
        self.preferred, self.fallback, self.dir = voice, fallback, voices_dir
        self.voice_name = None
        self._voice = None
        self._lock = threading.Lock()
        self._cache = OrderedDict()
        self._switch_lock = threading.Lock()
        self._switch_to = None      # the voice use() asked for last
        self.wanted = None          # the voice last asked for by use(): a load of any other is dropped
        self._switching = False     # a use() thread is running: it picks up _switch_to when done
        self._extra = OrderedDict()  # personality voices: name -> (PiperVoice, its own lock), oldest use first
        self._extra_lock = threading.Lock()
        self._extra_bad = set()     # voices that failed to load (not tried again this run)
        self._extra_slots = EXTRA_VOICES
        self.status = "Piper not installed" if not self.PiperVoice else "starting"

    @property
    def available(self):
        return self.PiperVoice is not None

    @property
    def ready(self):
        return self._voice is not None

    def installed(self):
        return installed_voices(self.dir)

    def _set_status(self, text):
        """Change the status and tell the page (the worker thread runs outside the event loop, and a
        waiting long poll only answers when something bumps it)."""
        self.status = text
        self.on_change()

    def info(self):
        return {"engine": "piper" if self.ready else None, "voice": self.voice_name, "status": self.status,
                "voices": self.installed() if self.available else [], "available": self.available}

    def start(self):
        if self.available:
            threading.Thread(target=self._prepare, args=(None,), daemon=True, name="piper").start()

    def valid_name(self, name):
        """An installed voice, or a well-formed Piper voice name (so a download stays inside piper-voices/)."""
        return bool(name) and (name in self.installed() or bool(VOICE_NAME.fullmatch(name)))

    def use(self, name):
        """Switch voice (from the alerts dialog): loads, downloading first if it is not installed. One
        switch runs at a time; asking again meanwhile only changes which voice it ends on. False for a
        name that is not a voice."""
        if not (self.available and self.valid_name(name)):
            return False
        with self._switch_lock:
            self._switch_to = self.wanted = name
            if self._switching:
                return True
            self._switching = True
        threading.Thread(target=self._switch_loop, daemon=True, name="piper").start()
        return True

    def _switch_loop(self):
        while True:
            with self._switch_lock:
                name, self._switch_to = self._switch_to, None
                if name is None:
                    self._switching = False
                    return
            if name == self.voice_name:
                self.on_switched(name)   # already speaking: still the choice to remember
                continue
            try:
                self._prepare(name)
            except Exception as e:  # noqa: BLE001 -- keep the loop's flag honest
                print(f"spoken alerts: could not switch to {name}: {type(e).__name__}: {e}", file=sys.stderr)

    def _prepare(self, wanted, remember=True):
        order = [v for v in ([wanted] if wanted else [self.preferred, self.fallback]) if v]
        installed = self.installed()
        # an installed voice first (preferred, then fallback), so speech works at once; only if none of
        # them loads, download the others in the same order
        failed = None   # the last load failure, for the status when nothing works
        for pick in [v for v in order if v in installed] + [v for v in order if v not in installed]:
            if pick not in installed and not self._download(pick):
                continue
            self._set_status(f"loading {pick}")
            try:
                voice = self.PiperVoice.load(os.path.join(self.dir, pick + ".onnx"))
                break
            except Exception as e:   # a damaged file, an onnxruntime problem: try the next voice
                failed = f"could not load {pick}: {type(e).__name__}: {e}"
                print(f"spoken alerts: {failed} (delete {pick}.onnx in {self.dir} to download it again)",
                      file=sys.stderr)
        else:
            if self._voice is not None:   # a switch that failed: the voice already loaded keeps speaking
                self._set_status(f"could not switch to {wanted}"
                                 f" ({failed or 'download failed'}); still using {self.voice_name}")
            else:
                self._set_status(f"{failed} (browser speech is used)" if failed
                                 else "no voice available (download failed; browser speech is used)")
            return
        with self._lock:
            if self.wanted and self.voice_name == self.wanted and pick != self.wanted:
                # the start-up load finished after the voice picked in the dialog was already in use:
                # keep the one asked for (a load that finishes before it is simply replaced by it)
                stale = True
            else:
                stale = False
                self._voice, self.voice_name = voice, pick
                self._cache.clear()
        if not stale:
            print(f"spoken alerts: Piper voice {pick} ready")
        self._set_status("ready")
        if wanted and not stale and remember:
            self.on_switched(pick)
        if not wanted and pick != order[0] and order[0] not in installed and VOICE_NAME.fullmatch(order[0]):
            # the configured (or remembered) voice is not installed: the installed fallback speaks now, and
            # the one asked for is downloaded behind it and takes over once it loads
            threading.Thread(target=self._fetch_preferred, args=(order[0], pick), daemon=True,
                             name="piper-download").start()

    def _fetch_preferred(self, name, speaking):
        """Download the start-up's preferred voice while `speaking` (the fallback) is in use, then switch."""
        if not self._download(name, f"using {speaking}; downloading {name} (about 63 MB), "
                                    "switching to it when it is ready"):
            if self.voice_name == speaking:
                self._set_status(f"using {speaking}; could not download {name}")
            return
        if self.wanted and self.wanted != name:   # another voice was picked in the dialog meanwhile: it wins
            return
        # not remembered as a dialog choice: it is the configured voice (or already the remembered one)
        self._prepare(name, remember=False)

    def _download(self, name, status=None):
        """Download a voice into the voices folder (see download_voice_files); True once it is there."""
        try:
            paths = voice_paths(name)
        except ValueError as e:
            print(f"spoken alerts: {e}", file=sys.stderr)
            return False
        self._set_status(status or f"downloading {name} (about 63 MB)")
        print(f"spoken alerts: downloading Piper voice {name} into {self.dir} (browser speech until it is ready)")
        try:
            download_voice_files([(p, {}) for p in paths], self.dir)
            return True
        except Exception as e:
            print(f"spoken alerts: could not download {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def size_extra(self, names):
        """Keep room for every personality voice speech.json names now (`names`), between EXTRA_VOICES and
        EXTRA_VOICES_MAX; the main voice needs no slot."""
        want = len({n for n in names if n and n != self.voice_name})
        self._extra_slots = max(EXTRA_VOICES, min(EXTRA_VOICES_MAX, want))

    def extra_voice(self, name):
        """(PiperVoice, lock) for a personality's own voice, loading it now if it is installed; None for the
        main voice, a voice that is not installed (never downloaded from here) or one that will not load."""
        if not name or name == self.voice_name or name in self._extra_bad or name not in self.installed():
            return None
        with self._extra_lock:
            if name in self._extra:
                self._extra.move_to_end(name)
                return self._extra[name]
        try:
            voice = self.PiperVoice.load(os.path.join(self.dir, name + ".onnx"))
        except Exception as e:  # noqa: BLE001 -- a damaged file: the main voice speaks those lines instead
            self._extra_bad.add(name)
            print(f"spoken alerts: could not load {name} for a personality: {type(e).__name__}: {e}", file=sys.stderr)
            return None
        with self._extra_lock:
            if name not in self._extra:
                self._extra[name] = (voice, threading.Lock())
                while len(self._extra) > self._extra_slots:
                    self._extra.popitem(last=False)
            return self._extra[name]

    def _synth(self, voice, text, speed):
        """WAV bytes, or None for a line with nothing to pronounce ('...', a lone dash): Piper skips a
        sentence without phonemes, writes no audio and the WAV header is never set (wave.Error)."""
        buf = io.BytesIO()
        cfg = self.SynthesisConfig(length_scale=1.0 / speed) if speed != 1.0 else None
        try:
            with wave.open(buf, "wb") as wf:
                voice.synthesize_wav(text, wf, syn_config=cfg)
        except wave.Error:
            return None
        return buf.getvalue() or None

    def _keep(self, key, audio):
        self._cache[key] = audio
        while len(self._cache) > CACHE_PHRASES:
            self._cache.popitem(last=False)

    def say(self, text, speed=1.0, voice=None):
        """WAV bytes for `text` at `speed` (1 = the voice's own pace), or None if no voice is ready yet.
        `voice`: a personality's own voice, when it is installed (else the main voice). Recent phrases are cached."""
        text = clip_text(text)
        if not text or not self.ready:
            return None
        speed = min(2.0, max(0.5, float(speed or 1.0)))
        extra = self.extra_voice(voice)
        key = (text, round(speed, 2), voice if extra else None)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            if not extra:
                audio = self._synth(self._voice, text, speed)
                self._keep(key, audio)
                return audio
        with extra[1]:   # its own lock: the main voice keeps speaking meanwhile
            audio = self._synth(extra[0], text, speed)
        with self._lock:
            self._keep(key, audio)
        return audio
