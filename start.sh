#!/usr/bin/env bash
# HotGraph, one command:  ./start.sh   (or: bash start.sh)
set -e
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python 3.10+ not found."
    echo "  macOS: brew install python      Linux: sudo apt install python3 python3-venv"
    exit 1
fi

exec "$PY" start.py "$@"
