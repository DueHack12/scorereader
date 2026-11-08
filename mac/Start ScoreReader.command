#!/bin/bash
# Double-click to start ScoreReader on a Mac. The first run sets up Python packages (about a minute).
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Return to close."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || {
    read -r -p "Setup failed. Press Return to close."; exit 1; }
fi
(sleep 3; open "http://localhost:8765/") &
.venv/bin/python scorereader.py "$@"
read -r -p "ScoreReader stopped. Press Return to close."
