#!/usr/bin/env bash
# Start ScoreReader (Linux / Raspberry Pi). Any options are passed through, e.g. ./linux/start.sh --demo
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python scorereader.py "$@"
fi
exec python3 scorereader.py "$@"
