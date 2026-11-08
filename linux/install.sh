#!/usr/bin/env bash
# ScoreReader installer for Linux and Raspberry Pi OS.
#
#   ./linux/install.sh             install Python packages and USB permissions for the ScoreBot
#   ./linux/install.sh --service   ...and start ScoreReader automatically at boot (systemd)
#
# Safe to run again. Needs sudo for the system parts.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)"
SERVICE=0
[ "${1:-}" = "--service" ] && SERVICE=1
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"

echo "== Python packages"
if command -v apt-get >/dev/null 2>&1; then
  # Debian / Ubuntu / Raspberry Pi OS: use the distribution's packages (no compiler needed)
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq python3 python3-serial python3-hid
  PY=/usr/bin/python3
else
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  PY="$DIR/.venv/bin/python"
fi
"$PY" -c "import serial, hid" || { echo "Python packages are missing; see README (Linux)"; exit 1; }

echo "== USB permissions for the ScoreBot (Microchip MCP2221, 04d8:00dd)"
$SUDO install -D -m 644 linux/99-scorebot.rules /etc/udev/rules.d/99-scorebot.rules
# The kernel's hid_mcp2221 driver can take over the chip's GPIO interface, which ScoreReader needs
# to switch the bot between command and data mode. Nothing else on a ScoreReader machine uses it.
$SUDO install -D -m 644 linux/scorebot-blacklist.conf /etc/modprobe.d/scorebot-blacklist.conf
$SUDO udevadm control --reload-rules 2>/dev/null || true
$SUDO udevadm trigger 2>/dev/null || true
for g in dialout plugdev; do
  if getent group "$g" >/dev/null; then $SUDO usermod -aG "$g" "$RUN_USER"; fi
done

if [ "$SERVICE" = 1 ]; then
  echo "== Auto-start at boot (systemd service 'scorereader')"
  sed -e "s|@DIR@|$DIR|g" -e "s|@PY@|$PY|g" -e "s|@USER@|$RUN_USER|g" linux/scorereader.service \
    | $SUDO tee /etc/systemd/system/scorereader.service >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now scorereader
  echo "Logs: journalctl -u scorereader -f"
fi

echo
echo "Done. Unplug and replug the ScoreBot (or reboot) so the new permissions apply."
echo "Start it with:  ./linux/start.sh      then open http://<this-machine>:8765/"
