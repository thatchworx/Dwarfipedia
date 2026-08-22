#!/usr/bin/env bash
# DwarfWiki launcher for macOS/Linux — mirrors DwarfWiki.bat's logic:
# check for Python, install Flask+lxml once if missing, import any new
# worlds, then start the server and open the browser once it answers.
set -e
cd "$(dirname "$0")/server"

echo ""
echo "  =========================================="
echo "    D W A R F W I K I"
echo "    a local legends viewer"
echo "  =========================================="
echo ""

# --- find a python3 ---
PYTHON=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PYTHON="$cand"; break; fi
done
if [ -z "$PYTHON" ]; then
  echo "  Python 3 was not found on your PATH."
  echo "  Install it from https://www.python.org/downloads/ (or via your"
  echo "  system package manager), then run this again."
  echo ""
  read -p "Press Enter to close..." _
  exit 1
fi

# --- check Flask + lxml, install once if missing ---
if ! "$PYTHON" -c "import flask, lxml" >/dev/null 2>&1; then
  echo "  Installing required libraries (one-time setup)..."
  "$PYTHON" -m pip install flask lxml
  echo ""
fi

# --- import any new worlds (prints progress; skips ones already done) ---
"$PYTHON" parser.py

# --- wait for the server to answer, then open the browser, in the background ---
(
  for _ in $(seq 1 30); do
    if curl -s -o /dev/null "http://localhost:5000/"; then
      if command -v open >/dev/null 2>&1; then open "http://localhost:5000"
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open "http://localhost:5000"
      else echo "  Open this address manually: http://localhost:5000"
      fi
      exit 0
    fi
    sleep 1
  done
  echo "  Couldn't confirm the server started in time."
  echo "  Open this address manually: http://localhost:5000"
) &

echo ""
echo "  Starting server... your browser will open automatically once it's ready."
echo "  (Keep this window open while you use DwarfWiki. Press Ctrl+C to stop.)"
echo ""

# --- run the server (this shell stays open) ---
"$PYTHON" server.py
