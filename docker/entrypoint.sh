#!/bin/sh
# The container's start: on the first run (no config yet in /config) write one for a server: every network address,
# the journals at /journals, then run Outrider with it. Settings -> Server settings edits the same file.
set -e
CONFIG=/config/ed_outrider.toml
# the folders compose mounts must be writable by this user; Docker makes a missing one owned by root (review R1): say
# what to do and wait, rather than fail and be restarted into the same failure over and over
for d in /config /app/data; do
  if ! ( touch "$d/.write-test" && rm -f "$d/.write-test" ) 2>/dev/null; then
    echo "ED Outrider cannot write $d (it runs as uid $(id -u)). On the host, in the folder with docker-compose.yml:"
    echo "  sudo chown -R $(id -u):$(id -g) docker/   then: docker compose restart"
    exec sleep infinity
  fi
done
if [ ! -f "$CONFIG" ]; then
  python ed_outrider.py --config "$CONFIG" --write-config --host 0.0.0.0 --port 8025 --journals /journals >/dev/null
  echo "first run: wrote $CONFIG (host 0.0.0.0, journals /journals); set [server] password in it or in Settings"
fi
exec python ed_outrider.py --config "$CONFIG" "$@"
