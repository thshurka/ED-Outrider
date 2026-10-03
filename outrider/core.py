"""Small helpers shared by ed_outrider.py and the outrider modules (no dependencies of their own)."""
import time


def ts_seconds(ts):
    """Journal timestamp ('2026-09-28T02:06:56Z') -> seconds since the epoch (UTC)."""
    import calendar
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def iso_ts(t):
    """time.time() -> a journal-style UTC timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
