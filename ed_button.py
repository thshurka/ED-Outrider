"""The co-pilot button: one HOTAS or keyboard button that talks to Outrider's voice (optional, Linux).

    tap          a status report: fuel and jumps, the next stop, what is aboard, the nearest unvisited system
                 (on a body with a sample run under way: the sampling progress instead)
    double tap   say the last line again
    hold         hush the voice until the next jump (danger lines still speak); another hold ends it early

In the Rhino on a body every gesture marks a mining rig instead and does nothing else: a press places the next
rig (1-6) behind you, a press by a rig that is out picks it up (the game tells Outrider neither).

Read-only: Outrider reads the device's events the way any program reads a joystick. It never grabs the device
(the game still sees every press) and never creates a virtual one. So unbind the button in Elite's controls, or
it does its game action as well. On the X-56, keep off the latching toggles and the mode wheel: they report as
buttons held down for as long as they sit in a position.

Access: joysticks and throttles are readable by the logged-in user on most distributions (the uaccess tag);
a keyboard or a mouse needs membership of the input group, which also lets every program read your typing.

Turn it on in ed_outrider.toml ([copilot] enabled, device, button). To find the button:

    python3 ed_button.py --listen     list the input devices, then print the code of each button you press
"""
import asyncio
import os
import sys
import time

from ed_honk import _import_evdev

HOLD_MS, DOUBLE_MS = 600, 350
RETRY = 5.0   # s between tries to (re)open the device: unplugged, suspended, not there yet


class Gestures:
    """Tap, double tap and hold from one button's presses (EV_KEY value 1) and releases (0); the autorepeat
    (2) is ignored. A release after a hold of hold_ms or more is "hush"; a second tap whose press comes within
    double_ms of the first's release is "again"; a lone tap is "status" once double_ms has passed with no second
    (due() says so). A hold straight after a tap swallows the tap: the hold is what was meant."""

    def __init__(self, hold_ms=HOLD_MS, double_ms=DOUBLE_MS):
        self.hold_ms, self.double_ms = hold_ms, double_ms
        self.down = None   # ms the button went down, while it is down
        self.tap = None    # ms a lone tap was released, while it waits for a second

    def feed(self, t, value):
        """The button's event at t ms: the gestures it completes (a list, often empty)."""
        out = self.due(t)
        if value == 1:
            if self.down is None:
                self.down = t
        elif value == 0 and self.down is not None:
            start, self.down = self.down, None
            if t - start >= self.hold_ms:
                self.tap = None
                out.append("hush")
            elif self.tap is not None and start - self.tap <= self.double_ms:
                self.tap = None
                out.append("again")
            else:
                self.tap = t
        return out

    def due(self, t):
        """["status"] when a lone tap's wait for a second one has run out by t ms, else []."""
        if self.tap is not None and self.down is None and t - self.tap > self.double_ms:
            self.tap = None
            return ["status"]
        return []


def classify(events, hold_ms=HOLD_MS, double_ms=DOUBLE_MS, end=None):
    """The gestures in a list of (ms, value) events, with a tap still waiting at the end settled at `end` ms
    (None: long after)."""
    g, out = Gestures(hold_ms, double_ms), []
    for t, value in events:
        out += g.feed(t, value)
    return out + g.due(float("inf") if end is None else end)


def button_code(evdev, name):
    """[copilot] button as an evdev code: a name such as BTN_TRIGGER_HAPPY5 or KEY_F13, or the number --listen
    prints; None if it is neither."""
    text = str(name if name is not None else "").strip()
    if text.isdigit():
        return int(text)
    code = evdev.ecodes.ecodes.get(text.upper()) if text else None
    return code if isinstance(code, int) else None


def code_name(evdev, code):
    """An EV_KEY code's evdev name ("BTN_TRIGGER_HAPPY5"), the first when it has several."""
    n = evdev.ecodes.BTN.get(code) or evdev.ecodes.KEY.get(code)
    return (n[0] if isinstance(n, (list, tuple)) else n) or str(code)


def find_device(evdev, spec):
    """The input device `spec` names: a /dev/input path (a by-id link too) or a part of its name, case ignored.
    (device, None), or (None, why not)."""
    spec = str(spec or "").strip()
    if not spec:
        return None, "no [copilot] device set (python3 ed_button.py --listen lists them)"
    if spec.startswith("/dev/"):
        try:
            return evdev.InputDevice(spec), None
        except OSError as e:
            return None, f"{spec}: {e.strerror or e}"
    found, unreadable = None, 0
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            unreadable += 1
            continue
        if found is None and spec.lower() in (dev.name or "").lower():
            found = dev
        else:
            dev.close()
    if found:
        return found, None
    return None, f"no input device named like {spec!r}" + (
        f" ({unreadable} could not be opened: joysticks need the uaccess tag, keyboards the input group)" if unreadable else "")


class ButtonWatch:
    """Reads the button and hands each gesture to on_gesture("status" | "again" | "hush"), on the event loop.
    A device that goes away (unplugged, suspend) is closed and looked for again every RETRY s; `status` says
    what it is doing, for the alerts dialog. Never grabs the device and never writes to it."""

    def __init__(self, device, button, on_gesture, hold_ms=HOLD_MS, double_ms=DOUBLE_MS, evdev=None):
        self.device, self.button, self.on_gesture = device, button, on_gesture
        self.hold_ms, self.double_ms = hold_ms, double_ms
        self.evdev = evdev   # tests hand in a stand-in; None imports the real one
        self.status = "starting"

    async def run(self):
        if self.evdev is None and not sys.platform.startswith("linux"):
            self.status = "Linux only"
            return
        ev = self.evdev or _import_evdev()
        if not ev:
            self.status = "the python evdev package is missing (see requirements.txt)"
            return
        code = button_code(ev, self.button)
        if code is None:
            self.status = (f"[copilot] button = {self.button!r} is not a button name or number "
                           "(python3 ed_button.py --listen prints them)")
            return
        while True:
            dev, why = find_device(ev, self.device)
            if dev is None:
                self.status = f"{why}; looking again every {RETRY:g} s"
            else:
                self.status = f"listening to {dev.name} for {code_name(ev, code)}"
                try:
                    await self._read(dev, ev, code)
                    self.status = f"{dev.name} stopped sending; looking again every {RETRY:g} s"
                except OSError as e:   # unplugged, or the machine slept
                    self.status = f"{dev.name}: {e.strerror or e}; looking again every {RETRY:g} s"
                finally:
                    try:
                        dev.close()
                    except OSError:
                        pass
            await asyncio.sleep(RETRY)

    async def _read(self, dev, ev, code):
        loop, g, timer = asyncio.get_running_loop(), Gestures(self.hold_ms, self.double_ms), None
        now = lambda: time.monotonic() * 1000

        def settle():   # a lone tap's wait for a second one has run out
            for x in g.due(now()):
                self.on_gesture(x)
        try:
            async for e in dev.async_read_loop():
                if e.type != ev.ecodes.EV_KEY or e.code != code:
                    continue
                for x in g.feed(now(), e.value):
                    self.on_gesture(x)
                if timer:
                    timer.cancel()
                timer = loop.call_later(self.double_ms / 1000 + 0.02, settle) if g.tap is not None else None
        finally:
            if timer:
                timer.cancel()


def listen(evdev):
    """--listen: every readable input device, then each button press on any of them (read-only)."""
    import selectors
    devices = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        if evdev.ecodes.EV_KEY not in dev.capabilities():
            dev.close()
            continue
        devices.append(dev)
        print(f"{path}  {dev.name}")
    byid = "/dev/input/by-id"
    if os.path.isdir(byid):
        links = sorted(n for n in os.listdir(byid) if n.endswith("-event-joystick") or n.endswith("-event-kbd"))
        if links:
            print("\nstable paths (usable as [copilot] device):")
            for n in links:
                print(f"  {os.path.join(byid, n)}")
    if not devices:
        print("no readable input devices with buttons: joysticks need the uaccess tag, keyboards the input group")
        return
    print("\npress the button you want (Ctrl-C to stop); put its name in [copilot] button and the device in device")
    sel = selectors.DefaultSelector()
    for dev in devices:
        sel.register(dev, selectors.EVENT_READ)
    while True:
        for key, _ in sel.select():
            dev = key.fileobj
            try:
                events = list(dev.read())
            except BlockingIOError:
                continue
            except OSError:   # unplugged
                sel.unregister(dev)
                continue
            for e in events:
                if e.type == evdev.ecodes.EV_KEY and e.value == 1:
                    print(f"{dev.name}: {code_name(evdev, e.code)}  ({e.code})")


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--listen", action="store_true", help="list input devices and print each button pressed")
    args = p.parse_args(argv)
    if not args.listen:
        p.print_help()
        return
    ev = _import_evdev()
    if not ev:
        raise SystemExit("the python evdev package is missing (pip install evdev, or see requirements.txt)")
    try:
        listen(ev)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
