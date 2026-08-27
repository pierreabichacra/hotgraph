"""HotGraph, one command.

    python start.py            # Windows: double-click start.bat
    ./start.sh                 # macOS / Linux

First run: creates .venv, installs requirements, asks for your Telegram
api_id / api_hash (-> .env), logs you in to Telegram (-> data/hotgraph.session),
then starts HotGraph and opens the browser. Every run after that goes straight
to the server. Ctrl-C stops everything.

Standard library only: this file runs on the system Python before anything is
installed. It must never import hotgraph.* (that needs PyYAML / Telethon).
"""

import sys

if sys.version_info < (3, 10):
    print(
        "HotGraph needs Python 3.10 or newer (found %d.%d).\n"
        "  Windows: winget install Python.Python.3.12   or https://python.org\n"
        "  macOS:   brew install python\n"
        "  Linux:   sudo apt install python3 python3-venv"
        % (sys.version_info[0], sys.version_info[1])
    )
    sys.exit(1)

import argparse
import hashlib
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
ENV_FILE = ROOT / ".env"
DATA = ROOT / "data"
SESSION = DATA / "hotgraph.session"
STAMP = VENV / ".requirements.sha256"
SOURCES = ROOT / "config" / "sources.yaml"
IS_WIN = os.name == "nt"

# hotgraph.run exits with this after the Sign out button removed the session.
SIGNED_OUT = 3


def say(msg):
    print(msg, flush=True)


def venv_python():
    if IS_WIN:
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd, **kw):
    """Run a child in the repo root (python -m hotgraph.* needs it on sys.path)."""
    return subprocess.call([str(c) for c in cmd], cwd=str(ROOT), **kw)


def quiet(cmd, timeout=60):
    try:
        return run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout) == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------- 1. venv

def ensure_venv():
    vp = venv_python()
    if vp.exists() and quiet([vp, "-c", "import sys"]):
        return vp
    if VENV.exists():
        # Left over from a Python that has since moved or been uninstalled.
        say("  .venv is broken - recreating it")
        try:
            shutil.rmtree(VENV)
        except OSError as e:
            say("  Could not remove .venv (%s). Close other HotGraph windows and rerun." % e)
            sys.exit(1)
    say("  Creating .venv with %s" % sys.executable)
    if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
        say(
            "Could not create a virtual environment.\n"
            "  Debian/Ubuntu: sudo apt install python3-venv\n"
            "  Otherwise reinstall Python from https://python.org"
        )
        sys.exit(1)
    if not quiet([vp, "-m", "pip", "--version"]):
        run([vp, "-m", "ensurepip", "--upgrade"])
    return vp


# ---------------------------------------------------------------- 2. deps

def ensure_deps(vp, force=False):
    want = hashlib.sha256(REQ.read_bytes()).hexdigest()
    have = STAMP.read_text().strip() if STAMP.exists() else ""
    if (
        not force
        and have == want
        and quiet([vp, "-c", "import telethon, fastapi, uvicorn, yaml"])
    ):
        return
    say("  Installing dependencies (first run, about a minute)...")
    rc = run([vp, "-m", "pip", "install", "-q", "--disable-pip-version-check",
              "-r", str(REQ)])
    if rc != 0:
        say("pip failed - see the error above (network? proxy?). Rerun start when fixed.\n"
            "  If it says 'Microsoft Visual C++ 14.0 or greater is required', a package\n"
            "  has no prebuilt wheel for this Python version. Update requirements.txt\n"
            "  or install a Python release the packages support (3.12 is safest):\n"
            "    winget install Python.Python.3.12")
        sys.exit(1)
    STAMP.write_text(want)


# ---------------------------------------------------------------- 3. .env

def read_env():
    """Same rules as hotgraph/config.py _load_dotenv (reimplemented on purpose)."""
    out = {}
    if not ENV_FILE.exists():
        return out
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip("'\"")
    return out


def write_env(updates):
    """Fill empty KEY= lines in place, append the rest; keep everything else."""
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [
        "# HotGraph - Telegram API credentials (this file is gitignored).",
        "# Get them at https://my.telegram.org -> API development tools.",
        "",
    ]
    pending = dict(updates)
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key = s.partition("=")[0].strip()
        if key in pending:
            lines[i] = "%s=%s" % (key, pending.pop(key))
    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        for key, val in pending.items():
            lines.append("%s=%s" % (key, val))
    ENV_FILE.write_text("\n".join(lines) + "\n")


def ensure_credentials():
    env = read_env()
    have = lambda k: bool(os.environ.get(k, "").strip() or env.get(k, "").strip())
    if have("TG_API_ID") and have("TG_API_HASH"):
        return
    say(
        "\n  HotGraph reads Telegram through your own account, which needs an API key.\n"
        "  1. Open https://my.telegram.org and log in\n"
        "  2. Click 'API development tools', create an app (any name)\n"
        "  3. Copy api_id and api_hash below (they are saved to .env)\n"
    )
    def ask(prompt, pattern, hint):
        while True:
            try:
                v = input(prompt).strip().strip("'\"")
            except EOFError:  # no terminal (isatty() lies on some Windows shells)
                say("\nNo terminal to ask on. Put TG_API_ID=... and TG_API_HASH=... "
                    "in .env and rerun.")
                sys.exit(1)
            if re.fullmatch(pattern, v):
                return v
            say("  " + hint)

    updates = {}
    if not have("TG_API_ID"):
        updates["TG_API_ID"] = ask(
            "  TG_API_ID (a number): ", r"\d+", "api_id is all digits, e.g. 1234567")
    if not have("TG_API_HASH"):
        updates["TG_API_HASH"] = ask(
            "  TG_API_HASH (32 hex characters): ", r"[0-9a-fA-F]{32}",
            "api_hash is 32 characters of 0-9 a-f")
    write_env(updates)
    say("  Saved to .env\n")


# ---------------------------------------------------------------- 4. login

def bot_handles():
    try:
        return re.findall(r'chat:\s*"(@\w+)"', SOURCES.read_text())
    except OSError:
        return []


def remove_session():
    for p in DATA.glob("hotgraph.session*"):
        try:
            p.unlink()
        except OSError:
            pass


def ensure_session(vp):
    if SESSION.exists():
        return
    bots = bot_handles()
    say("\n  Logging HotGraph in to Telegram (a new device on your account; revoke it")
    say("  any time from Telegram -> Settings -> Devices).")
    say("  Telegram will send a login code to your Telegram app; a 2FA password is")
    say("  asked for if you have one set.")
    if bots:
        say("\n  Before continuing, make sure your account has opened a chat with each")
        say("  tracker bot (search it in Telegram and press Start):")
        for b in bots:
            say("    " + b)
    say("")
    rc = run([vp, "-m", "hotgraph.tg_login"])
    if rc != 0 or not SESSION.exists():
        # Telethon writes the session file as soon as it connects, before the
        # code is entered; an aborted login must not look like a finished one.
        remove_session()
        say("\nLogin did not complete - run start again to retry.")
        sys.exit(1)
    say("")


# ---------------------------------------------------------------- 5. run

def port_free(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def open_when_ready(url, host, port, proc):
    """Open the browser once the server is actually listening. On a first run
    that's after the 31-day backfill, which can take minutes - no fixed delay."""
    def poll():
        while proc.poll() is None:
            try:
                socket.create_connection((host, port), timeout=0.5).close()
                webbrowser.open(url)
                return
            except OSError:
                time.sleep(0.5)
    threading.Thread(target=poll, daemon=True).start()


def launch(vp, host, port, browser):
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = "http://%s:%d" % (connect_host, port)
    was_free = port_free(host, port)
    proc = subprocess.Popen(
        [str(vp), "-m", "hotgraph.run", "--host", host, "--port", str(port)],
        cwd=str(ROOT),
    )
    if browser and was_free:
        open_when_ready(url, connect_host, port, proc)
    try:
        rc = proc.wait()
    except KeyboardInterrupt:
        # The console already delivered Ctrl-C to the child; give it time to
        # close the Telegram client and the server cleanly.
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        return 0
    if rc not in (0, SIGNED_OUT):
        say(
            "\nHotGraph stopped with an error (see above). Common causes:\n"
            "  - 'Port ... already in use'     -> another HotGraph is running; stop it first\n"
            "  - 'Could not find the input entity' / 'No user has ... as username'\n"
            "                                  -> open a chat with each tracker bot in Telegram\n"
            "  - AUTH_KEY_UNREGISTERED / revoked -> delete data/hotgraph.session and rerun"
        )
    return rc


def main():
    ap = argparse.ArgumentParser(description="Set up (if needed) and run HotGraph.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="don't open the page")
    ap.add_argument("--reinstall", action="store_true", help="reinstall dependencies")
    args = ap.parse_args()

    say("[1/4] Python environment")
    vp = ensure_venv()
    say("[2/4] Dependencies")
    ensure_deps(vp, force=args.reinstall)
    say("[3/4] Telegram credentials")
    ensure_credentials()
    while True:
        say("[4/4] Telegram login")
        ensure_session(vp)
        say("Starting HotGraph...\n")
        rc = launch(vp, args.host, args.port, not args.no_browser)
        if rc == SIGNED_OUT:
            remove_session()  # the .session-journal Telethon leaves behind
            say("\nSigned out of Telegram. Log in again, or Ctrl-C to quit.\n")
            continue
        sys.exit(rc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
