#!/bin/sh
# The container's start: on the first run (no config yet in /config) write one for a server: every network address,
# the journals at /journals, then run Outrider with it. Settings -> Server settings edits the same file.
set -e
CONFIG=/config/ed_outrider.toml
if [ ! -f "$CONFIG" ]; then
  python ed_outrider.py --config "$CONFIG" --write-config --host 0.0.0.0 --port 8025 --journals /journals >/dev/null
  echo "first run: wrote $CONFIG (host 0.0.0.0, journals /journals); set [server] password in it or in Settings"
fi
exec python ed_outrider.py --config "$CONFIG" "$@"
