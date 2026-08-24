"""Filesystem layout. Everything resolves off the repo root so scripts work
regardless of the directory they're invoked from."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"

DB_PATH = DATA_DIR / "hotgraph.db"

# Deliberately its own session file. Sharing a session with another running
# process is what triggers AUTH_KEY_DUPLICATED — a separate file is just
# another authorized device on the account.
SESSION_PATH = DATA_DIR / "hotgraph"

SOURCES_YAML = CONFIG_DIR / "sources.yaml"
PEOPLE_YAML = CONFIG_DIR / "people.yaml"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
