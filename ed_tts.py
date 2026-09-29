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
import io
import os
import sys
import threading
import wave
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
VOICES_DIR = os.path.join(HERE, "piper-voices")
DEFAULT_VOICE = "en_GB-southern_english_female-low"
DEFAULT_FALLBACK = "en_GB-jenny_dioco-medium"
CACHE_PHRASES = 50


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

    def __init__(self, voice=DEFAULT_VOICE, fallback=DEFAULT_FALLBACK, voices_dir=VOICES_DIR, on_change=None):
        self.on_change = on_change or (lambda: None)   # called (from the thread) when status changes
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
        self.status = "Piper not installed" if not self.PiperVoice else "starting"

    @property
    def available(self):
        return self.PiperVoice is not None

    @property
    def ready(self):
        return self._voice is not None

    def installed(self):
        return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(self.dir, "*.onnx")))

    def info(self):
        return {"engine": "piper" if self.ready else None, "voice": self.voice_name, "status": self.status,
                "voices": self.installed() if self.available else [], "available": self.available}

    def start(self):
        if self.available:
            threading.Thread(target=self._prepare, args=(None,), daemon=True, name="piper").start()

    def use(self, name):
        """Switch voice (from the alerts dialog): loads, downloading first if it is not installed."""
        if self.available and name and name != self.voice_name:
            threading.Thread(target=self._prepare, args=(name,), daemon=True, name="piper").start()

    def _prepare(self, wanted):
        order = [wanted] if wanted else [self.preferred, self.fallback]
        installed = self.installed()
        # an installed voice first (preferred, then fallback), so speech works at once; only if neither
        # is there, download the preferred one (then the fallback if that fails)
        pick = next((v for v in order if v and v in installed), None)
        if not pick:
            for v in [x for x in order if x]:
                if self._download(v):
                    pick = v
                    break
        if not pick:
            self.status = "no voice available (download failed; browser speech is used)"
            self.on_change()
            return
        try:
            self.status = f"loading {pick}"
            voice = self.PiperVoice.load(os.path.join(self.dir, pick + ".onnx"))
        except Exception as e:   # a broken download, an onnxruntime problem
            self.status = f"could not load {pick}: {type(e).__name__}: {e}"
            print(f"spoken alerts: {self.status}", file=sys.stderr)
            return
        with self._lock:
            self._voice, self.voice_name = voice, pick
            self._cache.clear()
        self.status = "ready"
        print(f"spoken alerts: Piper voice {pick} ready")
        self.on_change()

    def _download(self, name):
        try:
            from pathlib import Path
            from piper.download_voices import download_voice
        except ImportError:
            return False
        self.status = f"downloading {name} (about 63 MB)"
        print(f"spoken alerts: downloading Piper voice {name} into {self.dir} (browser speech until it is ready)")
        try:
            os.makedirs(self.dir, exist_ok=True)
            download_voice(name, Path(self.dir))
            return os.path.exists(os.path.join(self.dir, name + ".onnx"))
        except Exception as e:
            print(f"spoken alerts: could not download {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return False

    def say(self, text, speed=1.0):
        """WAV bytes for `text` at `speed` (1 = the voice's own pace), or None if no voice is ready yet.
        Recent phrases are cached."""
        text = " ".join((text or "").split())[:400]
        if not text or not self.ready:
            return None
        speed = min(2.0, max(0.5, float(speed or 1.0)))
        key = (text, round(speed, 2))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            buf = io.BytesIO()
            cfg = self.SynthesisConfig(length_scale=1.0 / speed) if speed != 1.0 else None
            with wave.open(buf, "wb") as wf:
                self._voice.synthesize_wav(text, wf, syn_config=cfg)
            audio = buf.getvalue()
            self._cache[key] = audio
            while len(self._cache) > CACHE_PHRASES:
                self._cache.popitem(last=False)
            return audio
