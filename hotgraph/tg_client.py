"""Shared Telethon client factory, so login/capture agree on session + identity."""

from __future__ import annotations

from telethon import TelegramClient

from . import __version__
from .config import tg_credentials
from .paths import SESSION_PATH, ensure_dirs


def make_client() -> TelegramClient:
    ensure_dirs()
    api_id, api_hash = tg_credentials()
    return TelegramClient(
        str(SESSION_PATH),
        api_id,
        api_hash,
        device_model="HotGraph",
        app_version=__version__,
        # After any reconnect (Wi-Fi blip, laptop sleep, Telegram DC hiccup)
        # ask Telegram for the updates that were sent meanwhile instead of
        # silently resuming from "now". Without this, every alert that landed
        # during the gap simply never reaches the NewMessage handler.
        catch_up=True,
    )


def session_exists() -> bool:
    return SESSION_PATH.with_suffix(".session").exists()
