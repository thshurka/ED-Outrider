"""Auto honk: hold Primary Fire on arriving in a system, so the Discovery Scanner fires (optional, Linux).

Outrider presses keys on a virtual keyboard (the kernel's uinput, the same route Steam Input uses), so the
game sees ordinary key presses, under Wayland or X and through Proton alike. For it to work:

1. The Discovery Scanner must be on PRIMARY FIRE in the fire group that is active when you jump.
2. Primary Fire needs a keyboard binding (as its first or second binding) in Elite's controls. With
   key = "auto" (the default) Outrider reads it from your active controls preset -- modifiers too, such
   as the Alt+Alt+K that VoiceAttack profiles use -- so whatever is bound there is what gets pressed.
3. The python evdev package (in requirements.txt) and write access to /dev/uinput: Steam's controller
   rule already grants that to the logged-in user on most distributions.

The keys go to whichever window has focus: if you alt-tab away during a jump they land there instead,
so the page's alerts dialog has a quick on/off.

    python3 -m outrider.honk --test 10     count down 10 s (click into the game), then press Primary Fire once
    python3 -m outrider.honk --show        print the binding it would press
"""
import glob
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET

from . import ROOT   # the repository: ed_outrider.toml and .venv are there

DEFAULT_KEY = "auto"   # read Primary Fire's keyboard binding from the active controls preset

# Elite's key names -> evdev's, where they differ by more than the prefix
ELITE_KEYS = {
    "LeftAlt": "LEFTALT", "RightAlt": "RIGHTALT", "LeftControl": "LEFTCTRL", "RightControl": "RIGHTCTRL",
    "LeftShift": "LEFTSHIFT", "RightShift": "RIGHTSHIFT", "LeftWin": "LEFTMETA", "RightWin": "RIGHTMETA",
    "Return": "ENTER", "Enter": "ENTER", "Equals": "EQUAL", "LeftBracket": "LEFTBRACE", "RightBracket": "RIGHTBRACE",
    "SemiColon": "SEMICOLON", "Period": "DOT", "BackSlash": "BACKSLASH", "Grave": "GRAVE", "Apostrophe": "APOSTROPHE",
    "UpArrow": "UP", "DownArrow": "DOWN", "LeftArrow": "LEFT", "RightArrow": "RIGHT", "PageUp": "PAGEUP",
    "PageDown": "PAGEDOWN", "Numpad_Add": "KPPLUS", "Numpad_Subtract": "KPMINUS", "Numpad_Multiply": "KPASTERISK",
    "Numpad_Divide": "KPSLASH", "Numpad_Decimal": "KPDOT", "Numpad_Enter": "KPENTER", "CapsLock": "CAPSLOCK",
    "ScrollLock": "SCROLLLOCK", "NumLock": "NUMLOCK", "Backspace": "BACKSPACE", "Space": "SPACE", "Tab": "TAB",
    "Escape": "ESC", "Insert": "INSERT", "Delete": "DELETE", "Home": "HOME", "End": "END", "Minus": "MINUS",
    "Comma": "COMMA", "Slash": "SLASH", "Pause": "PAUSE",
    # names with no same-named evdev key (upper-casing them gives a code evdev does not have)
    "Apps": "COMPOSE", "Numpad_Equals": "KPEQUAL", "Numpad_Comma": "KPCOMMA", "OEM_102": "102ND",
    "Hash": "BACKSLASH", "PrintScreen": "SYSRQ", "PrevTrack": "PREVIOUSSONG", "NextTrack": "NEXTSONG",
    "MediaStop": "STOPCD", "Calculator": "CALC", "WebHome": "HOMEPAGE",
}


def _import_evdev():
    """evdev, from this interpreter or from the repository's .venv; None if neither has it."""
    try:
        import evdev
        return evdev
    except ImportError:
        pass
    venv = os.path.join(ROOT, ".venv", "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.isdir(venv) and venv not in sys.path:
        sys.path.append(venv)
        try:
            import evdev
            return evdev
        except ImportError:
            sys.path.remove(venv)
    return None


def elite_key(name):
    """'Key_K' -> 'KEY_K', 'Key_Numpad_0' -> 'KEY_KP0', 'Key_LeftAlt' -> 'KEY_LEFTALT'; None if not a key."""
    n = str(name or "")
    if not n.startswith("Key_"):
        return None
    n = n[4:]
    m = re.fullmatch(r"Numpad_(\d)", n)
    if m:
        return "KEY_KP" + m.group(1)
    return "KEY_" + ELITE_KEYS.get(n, n).upper()


def bindings_dir(journal_dirs=()):
    """Elite's Options/Bindings folder: next to the journals' user folder under Proton, or %LOCALAPPDATA%."""
    for d in journal_dirs or ():
        parts = os.path.normpath(d).split(os.sep)
        if "Saved Games" in parts:
            home = os.sep.join(parts[:parts.index("Saved Games")]) or os.sep
            cand = os.path.join(home, "AppData", "Local", "Frontier Developments", "Elite Dangerous", "Options", "Bindings")
            if os.path.isdir(cand):
                return cand
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = os.path.join(local, "Frontier Developments", "Elite Dangerous", "Options", "Bindings")
        if os.path.isdir(cand):
            return cand
    return None


_binding_cache = {}   # controls folder -> (its files' names and mtimes, primary_fire_binding's answer)


def primary_fire_binding(journal_dirs=()):
    """Primary Fire's keyboard binding in the active controls preset: (["KEY_LEFTALT", ..., "KEY_K"], text)
    with modifiers first, or (None, why not). Called for every page update, so the answer is kept until a
    file in the controls folder changes; a file Elite is rewriting at that moment is a reason, not an error."""
    d = bindings_dir(journal_dirs)
    if not d:
        return None, "Elite's controls folder was not found"
    try:
        stamp = tuple(sorted((p, os.path.getmtime(p)) for p in glob.glob(os.path.join(glob.escape(d), "*.start"))
                             + glob.glob(os.path.join(glob.escape(d), "*.binds"))))
        hit = _binding_cache.get(d)
        if hit and hit[0] == stamp:
            return hit[1]
        answer = _read_binding(d)
    except OSError as e:   # a file removed or rewritten between listing and reading it
        return None, f"Elite's controls could not be read ({e})"
    _binding_cache[d] = (stamp, answer)
    return answer


def _read_binding(d):
    """primary_fire_binding for the controls folder d, read from disk (OSError passes through)."""
    starts = sorted(glob.glob(os.path.join(glob.escape(d), "StartPreset*.start")), key=os.path.getmtime)
    preset = None
    if starts:
        with open(starts[-1], encoding="utf-8", errors="replace") as f:
            lines = [x.strip() for x in f.read().splitlines()]
        # Odyssey's StartPreset.4.start has one preset per line: General, Ship, SRV, On foot. Primary Fire
        # is a Ship control; an older file has a single line for everything
        preset = (lines[1] if len(lines) >= 4 and lines[1] else lines[0] if lines else "") or None
    if preset:
        files = sorted(glob.glob(os.path.join(glob.escape(d), glob.escape(preset) + ".*binds")), key=os.path.getmtime)
        if not files:   # the built-in presets live in the game's install folder, not here
            return None, (f"the controls preset {preset!r} is a built-in one (no .binds file in the controls folder): "
                          "bind Primary Fire in a custom preset, or set [autohonk] key")
    else:
        files = sorted(glob.glob(os.path.join(glob.escape(d), "Custom*.binds")), key=os.path.getmtime)
        if not files:
            return None, "no controls preset found"
    try:
        node = ET.parse(files[-1]).getroot().find("PrimaryFire")
    except ET.ParseError as e:
        return None, f"{os.path.basename(files[-1])} could not be read ({e})"
    mixed = False   # a keyboard key held with a joystick/HOTAS modifier: a virtual keyboard cannot press it
    for slot in ("Primary", "Secondary"):
        b = node.find(slot) if node is not None else None
        if b is None or b.get("Device") != "Keyboard":
            continue
        modifiers = b.findall("Modifier")
        if any(m.get("Device") != "Keyboard" for m in modifiers):
            mixed = True   # pressing the bare key would be some other control, not Primary Fire
            continue
        key = elite_key(b.get("Key"))
        mods = [elite_key(m.get("Key")) for m in modifiers]
        if key and all(mods):
            return mods + [key], f"{' + '.join(key_label(k) for k in mods + [key])} ({slot.lower()} binding of Primary Fire in {preset or 'your preset'})"
    return None, (f"Primary Fire has no keyboard binding in {preset or 'your preset'}"
                  + (" (a key with a joystick modifier cannot be pressed from here)" if mixed else "")
                  + ": give it one as its second binding in Elite's controls, or set [autohonk] key")


def key_label(name):
    """'KEY_LEFTALT' -> 'Left Alt', 'KEY_KP0' -> 'Numpad 0', 'KEY_K' -> 'K' (for messages)."""
    n = str(name)[4:] if str(name).startswith("KEY_") else str(name)
    special = {"LEFTALT": "Left Alt", "RIGHTALT": "Right Alt", "LEFTCTRL": "Left Ctrl", "RIGHTCTRL": "Right Ctrl",
               "LEFTSHIFT": "Left Shift", "RIGHTSHIFT": "Right Shift", "LEFTMETA": "Left Super", "RIGHTMETA": "Right Super",
               "COMPOSE": "Menu (Apps)", "KPPLUS": "Numpad +", "KPMINUS": "Numpad -", "KPASTERISK": "Numpad *",
               "KPSLASH": "Numpad /", "KPDOT": "Numpad .", "KPENTER": "Numpad Enter", "KPCOMMA": "Numpad ,",
               "KPEQUAL": "Numpad =", "SYSRQ": "Print Screen", "102ND": "OEM 102"}
    if n in special:
        return special[n]
    m = re.fullmatch(r"KP(\d)", n)
    return f"Numpad {m.group(1)}" if m else n.replace("_", " ").title() if len(n) > 1 else n


def parse_combo(text):
    """'KEY_LEFTALT+KEY_K' or 'alt+k' style text -> ['KEY_LEFTALT', 'KEY_K'] (names not yet checked)."""
    out = []
    for part in str(text or "").split("+"):
        p = part.strip().upper()
        if not p:
            continue
        p = {"ALT": "LEFTALT", "CTRL": "LEFTCTRL", "CONTROL": "LEFTCTRL", "SHIFT": "LEFTSHIFT"}.get(p, p)
        out.append(p if p.startswith("KEY_") else "KEY_" + p)
    return out


def key_code(evdev, name):
    """An evdev key code from a name: 'KEY_KP0', 'kp0' and 'KP0' all work. None if unknown."""
    n = str(name or "").strip().upper()
    if not n.startswith("KEY_"):
        n = "KEY_" + n
    code = evdev.ecodes.ecodes.get(n)
    return code if isinstance(code, int) else None


class Honker:
    """A virtual keyboard; press() holds Primary Fire's key (with its modifiers) for `hold` seconds."""

    def __init__(self, key=DEFAULT_KEY, hold=6.0, journal_dirs=()):
        self.key, self.hold, self.journal_dirs = key, hold, list(journal_dirs or ())
        self.evdev = _import_evdev() if sys.platform.startswith("linux") else None
        self.ui = None
        self.lock = threading.Lock()   # held by press() for the whole hold
        self.stop = threading.Event()  # close() during a hold: let go now, then close the device
        self.status = ("Linux only for now" if not sys.platform.startswith("linux")
                       else "needs the python evdev package (pip install evdev)" if not self.evdev else "off")

    @property
    def available(self):
        return self.evdev is not None

    @property
    def ready(self):
        return self.ui is not None and not self.stop.is_set()

    def combo(self):
        """(keys, description) to press now: read from the controls preset for "auto" (so a rebind is
        picked up without a restart), else the configured combination. keys is None when there is none."""
        if str(self.key).strip().lower() == "auto":
            keys, what = primary_fire_binding(self.journal_dirs)
            # checked here too, or the status says ready and every press fails on a key evdev lacks
            bad = [k for k in keys if key_code(self.evdev, k) is None] if keys and self.evdev else []
            if bad:
                return None, (f"no evdev equivalent for {', '.join(bad)} (Primary Fire's keyboard binding): "
                              "bind it to another key, or set [autohonk] key")
            return keys, what
        keys = parse_combo(self.key)
        bad = [k for k in keys if key_code(self.evdev, k) is None] if self.evdev else []
        if not keys or bad:
            return None, f"unknown key {', '.join(bad) or self.key!r} (use evdev names such as KEY_KP0, or KEY_LEFTALT+KEY_K)"
        return keys, " + ".join(key_label(k) for k in keys)

    def open(self):
        """Create the virtual keyboard (once, with every key, so a changed binding needs no restart)."""
        if self.ui or not self.evdev:
            if self.ui and self.stop.is_set():   # reopened while a press was still letting go: keep the device
                self.stop.clear()
            return bool(self.ui)
        keys, what = self.combo()
        e = self.evdev.ecodes
        try:
            all_keys = sorted(v for k, v in e.ecodes.items() if k.startswith("KEY_") and isinstance(v, int) and v < 0x2ff)
            self.ui = self.evdev.UInput({e.EV_KEY: all_keys}, name="ED Outrider auto honk")
        except (OSError, self.evdev.UInputError) as err:
            self.status = f"cannot create the virtual keyboard ({err}); /dev/uinput needs to be writable"
            return False
        self.status = f"ready: holds {what} for {self.hold:g} s" if keys else f"not ready: {what}"
        return True

    def close(self):
        """Close the virtual keyboard. Called on the event loop, so it never waits for a press: during a hold it
        cuts the hold short and press() closes the device once it has let go of the keys."""
        self.stop.set()
        if not self.lock.acquire(blocking=False):
            return   # press() is holding keys: it sees `stop` and closes after releasing them
        try:
            if self.stop.is_set():   # not reopened meanwhile
                self._close_now()
        finally:
            self.lock.release()

    def _close_now(self):
        """With self.lock held."""
        if self.ui:
            try:
                self.ui.close()
            except OSError:
                pass
        self.ui = None
        self.stop.clear()

    def press(self):
        """Hold Primary Fire's keys for `hold` seconds (blocking: run it on a worker thread). Returns the
        description of what was pressed, or None when close() cut the hold short; raises ValueError when there
        is nothing to press."""
        if not self.ready:
            raise ValueError("the virtual keyboard is not open")
        keys, what = self.combo()
        if not keys:
            self.status = f"not ready: {what}"
            raise ValueError(what)
        codes = [key_code(self.evdev, k) for k in keys]
        e = self.evdev.ecodes
        with self.lock:
            ui = self.ui   # a press queued behind another finds the device closed by then
            if ui is None or self.stop.is_set():
                if ui is not None:
                    self._close_now()
                raise ValueError("the virtual keyboard is not open")
            done = []
            try:
                for c in codes:            # modifiers first, the key last, as a person would
                    ui.write(e.EV_KEY, c, 1)
                    ui.syn()
                    done.append(c)
                    time.sleep(0.03)
                self.stop.wait(self.hold)  # close() ends the hold early
            finally:
                for c in reversed(done):   # always let go, whatever happened
                    ui.write(e.EV_KEY, c, 0)
                    ui.syn()
                stopped = self.stop.is_set()
                if stopped:
                    self._close_now()
        if stopped:
            return None
        if self.stop.is_set():   # close() came just after the check above, while the lock was still held
            self.close()
            return None
        self.status = f"ready: holds {what} for {self.hold:g} s"
        return what


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Auto honk helper: show or test Primary Fire's keyboard binding.")
    p.add_argument("--show", action="store_true", help="print the binding it would press")
    p.add_argument("--test", type=float, metavar="SECONDS", help="count down, then hold Primary Fire once")
    p.add_argument("--hold", type=float, default=6.0, help="seconds to hold (default 6)")
    p.add_argument("--key", help="'auto' or a combination such as KEY_LEFTALT+KEY_K (default: [autohonk] key "
                                 "in ed_outrider.toml, else auto)")
    p.add_argument("--journals", action="append", default=[], help="journal folder (to find the controls preset)")
    a = p.parse_args(argv)
    cfg = {}
    try:   # ed_outrider's config, when it can be read: the same folders and key the server uses
        import tomllib
        with open(os.path.join(ROOT, "ed_outrider.toml"), "rb") as f:
            cfg = tomllib.load(f)
    except Exception:   # no file, no tomllib (Python before 3.11), a broken file
        pass
    sec = lambda n: cfg.get(n) if isinstance(cfg.get(n), dict) else {}   # a section that is not a table: ignored
    dirs = a.journals
    if not dirs:
        live = sec("journals").get("live")
        dirs = [live] if isinstance(live, str) else [d for d in live if isinstance(d, str)] if isinstance(live, list) else []
    if not dirs and sec("journals").get("live") is None:   # as the server does: auto-detect
        try:
            from . import unsold
            dirs = unsold.find_journal_dirs()[0]
        except Exception:
            dirs = []
    dirs = [os.path.expanduser(d) for d in dirs]
    key = a.key or str(sec("autohonk").get("key") or DEFAULT_KEY)
    h = Honker(key, a.hold, dirs)
    keys, what = h.combo()
    print(f"Primary Fire: {what}" if keys else f"no key to press: {what}")
    if not keys or a.test is None:
        return 0 if keys else 1
    if not h.open():
        print(h.status)
        return 1
    time.sleep(0.5)   # let the desktop notice the new keyboard
    for n in range(int(a.test), 0, -1):
        print(f"  pressing in {n} s: click into the game now", flush=True)
        time.sleep(1)
    print(f"holding {what} for {a.hold:g} s", flush=True)
    h.press()
    h.close()
    print("released; the journal shows FSSDiscoveryScan if the Discovery Scanner fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
