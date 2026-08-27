"""One-time interactive login that creates HotGraph's own Telegram session.

    python -m hotgraph.tg_login

This writes data/hotgraph.session — a NEW authorized device on your account.
Your existing sessions (your other b, Telegram Desktop, phone) keep running
untouched. Telegram allows many concurrent sessions; the error people hit
(AUTH_KEY_DUPLICATED) comes from two processes sharing ONE session file, which
is exactly what this separate file avoids.

You can revoke it any time from Telegram: Settings -> Devices.
"""

from __future__ import annotations

import asyncio

from telethon import TelegramClient

from .config import tg_credentials
from .paths import SESSION_PATH, ensure_dirs


async def main() -> None:
    ensure_dirs()
    api_id, api_hash = tg_credentials()

    # device_model is what shows up in Settings -> Devices, so this session is
    # easy to identify and revoke without disturbing the others.
    client = TelegramClient(
        str(SESSION_PATH),
        api_id,
        api_hash,
        device_model="HotGraph",
        app_version=__import__("hotgraph").__version__,
    )

    print(f"Session file: {SESSION_PATH}.session")
    await client.start()

    me = await client.get_me()
    name = " ".join(filter(None, [me.first_name, me.last_name])) or "(no name)"
    print(f"\nLogged in as {name}  @{me.username or '-'}  (id {me.id})")
    print("Check Telegram -> Settings -> Devices; a new device is now listed.")
    print("Your other sessions are unaffected.\n")
    print("Next: python start.py  (or python -m hotgraph.run) — it catches up on")
    print("the bots in config/sources.yaml and serves the page.")

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        # Aborted at a prompt — no traceback; the caller (start.py) removes
        # the half-written session file and says how to retry.
        raise SystemExit(130)
