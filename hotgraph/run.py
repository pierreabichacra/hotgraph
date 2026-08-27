"""The one command that runs everything:

    python -m hotgraph.run            # -> http://localhost:8000
    python -m hotgraph.run --port 9000

One process, four jobs:
  1. listen    — live Telegram alerts, parsed and graphed as they arrive
                 (registered first, so nothing slips past during catch-up)
  2. catch-up  — fetch every alert missed while the app was off (cursor =
                 highest stored message id per bot; no overlap, no gaps)
  3. serve     — the web page + API
  4. reconcile — repeat the catch-up every minute as a safety net under the
                 live handler, so a dropped update is late, never lost

Ctrl-C stops all of it.
"""

from __future__ import annotations

import argparse
import asyncio
import time

import uvicorn

from .capture import catch_up, reconcile_forever, setup_live
from .config import load_sources
from .db import get_meta, session as db_session
from .positions import run as rebuild_positions
from .tg_client import make_client, session_exists


def _fmt_ago(ts: int | None) -> str:
    if not ts:
        return "never"
    s = int(time.time()) - int(ts)
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60}m ago"
    if s < 129600:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _assert_single_instance(host: str, port: int) -> None:
    """Refuse to start next to an already-running instance.

    Two copies would fight over the port AND over the Telethon session file
    (sqlite 'database is locked' — and, worse, concurrent use of one session
    is what triggers AUTH_KEY_DUPLICATED). A clear message beats a traceback.
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
    except OSError:
        raise SystemExit(
            f"Port {port} is already in use — HotGraph (or something else) is "
            f"already running.\nStop it first (Ctrl-C in its terminal, or "
            f"`kill $(lsof -ti :{port})`), then rerun."
        )
    finally:
        probe.close()


async def amain(host: str, port: int) -> None:
    sources = [s for s in load_sources() if s.enabled]
    if not sources:
        raise SystemExit("No enabled sources in config/sources.yaml.")
    if not session_exists():
        raise SystemExit("No Telegram session yet. Run: python -m hotgraph.tg_login")
    _assert_single_instance(host, port)

    with db_session() as conn:
        last = get_meta(conn, "last_fetch_ts")
    print(f"Last fetch: {_fmt_ago(int(last) if last else None)} — catching up...", flush=True)

    client = make_client()
    await client.start()

    # Hand the API the live client so the Rebuild button can backfill through
    # it instead of opening a second session (-> AUTH_KEY_DUPLICATED).
    from . import api as api_mod
    api_mod.tg_client = client

    # Handler first, catch-up second: an alert arriving mid-catch-up is then
    # seen by both, and the (source, message id) key makes that harmless —
    # the other order left a window whose messages were never fetched, since
    # the next catch-up starts from the newest id the handler had stored.
    n = await setup_live(client, sources)

    _, events_added = await catch_up(client, sources)
    if events_added:
        print(f"  {events_added} new event(s) — rebuilding positions", flush=True)
        rebuild_positions()

    server = uvicorn.Server(
        uvicorn.Config(
            "hotgraph.api:app", host=host, port=port, log_level="warning",
            # Ctrl-C must not wait on a browser that keeps its /api/stream
            # open: streams are told to end (below) and, whatever is still
            # hanging on after this many seconds, the server stops anyway.
            timeout_graceful_shutdown=3,
        )
    )

    async def end_streams_on_exit():
        # uvicorn owns the SIGINT handler; the first thing it does is flip
        # should_exit. Watch for that and close the streams right away, so
        # the graceful shutdown has nothing to wait for.
        while not server.should_exit:
            await asyncio.sleep(0.2)
        api_mod.close_streams()

    print(f"\nHotGraph up: http://{host}:{port}  (watching {n} bot chats live)", flush=True)
    print("Ctrl-C to stop.", flush=True)

    # Whichever half stops first (Ctrl-C hits the uvicorn server, a Telegram
    # drop ends the client) takes the other down with it — one process, one
    # lifetime.
    serve_task = asyncio.create_task(server.serve())
    tg_task = asyncio.create_task(client.run_until_disconnected())
    reconcile_task = asyncio.create_task(reconcile_forever(client, sources))
    streams_task = asyncio.create_task(end_streams_on_exit())
    try:
        await asyncio.wait({serve_task, tg_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        print("\nStopping HotGraph...", flush=True)
        api_mod.close_streams()
        server.should_exit = True
        for t in (serve_task, tg_task, reconcile_task, streams_task):
            t.cancel()
        await client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    try:
        asyncio.run(amain(args.host, args.port))
    except KeyboardInterrupt:
        return
    if not session_exists():
        # The Sign out button logged the device out and deleted the session;
        # the listener's disconnect is what ended the run. start.py treats
        # exit code 3 as "ask for a new login".
        print("Signed out — Telegram session removed. Run again to log in.", flush=True)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
