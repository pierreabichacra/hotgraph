"""Pull bot alerts out of Telegram into raw_messages.

    python -m hotgraph.capture --list                 # show your bot chats + ids
    python -m hotgraph.capture --backfill             # full history of every enabled source
    python -m hotgraph.capture --backfill --limit 500 # just the recent tail
    python -m hotgraph.capture --live                 # stay connected, append new alerts
    python -m hotgraph.capture --samples bot_a -n 5   # print raw text, for writing parsers

Capture never parses. It stores the message text verbatim plus a JSON blob of
the full message, so a parser rewrite later re-reads history from SQLite
instead of re-hitting Telegram.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from telethon import events
from telethon.tl.types import User

from .config import Source, load_sources
from .db import session as db_session, set_meta
from .tg_client import make_client, session_exists


def _msg_text(msg) -> str:
    """Alerts sometimes carry their body in a caption rather than .message."""
    return (getattr(msg, "message", None) or getattr(msg, "raw_text", None) or "").strip()


def _msg_json(msg) -> str:
    try:
        return json.dumps(msg.to_dict(), default=str, ensure_ascii=False)
    except Exception:
        return "{}"


def _store(conn, source_id: str, msg) -> int | None:
    """Insert one message. Returns its raw_messages id if new, else None."""
    text = _msg_text(msg)
    if not text:
        return None
    cur = conn.execute(
        """INSERT OR IGNORE INTO raw_messages
               (source, tg_msg_id, ts, text, raw_json, captured_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            msg.id,
            int(msg.date.timestamp()),
            text,
            _msg_json(msg),
            int(time.time()),
        ),
    )
    return cur.lastrowid if cur.rowcount > 0 else None


async def cmd_list(client) -> None:
    """Print bot conversations so you can copy exact @usernames into sources.yaml."""
    print(f"{'title':<38} {'@username':<28} {'chat id':>16}")
    print("-" * 84)
    async for dialog in client.iter_dialogs():
        ent = dialog.entity
        if isinstance(ent, User) and ent.bot:
            uname = f"@{ent.username}" if ent.username else "-"
            print(f"{(dialog.name or '')[:37]:<38} {uname:<28} {dialog.id:>16}")
    print("\nCopy the @username (or chat id) of your 3 bots into config/sources.yaml,")
    print("and set `enabled: true` on each.")


async def backfill_one(
    client, conn, src: Source, limit: int | None, since_ts: float | None = None
) -> tuple[int, int]:
    """Walk a chat's history newest-first. Returns (new, seen).

    since_ts bounds how far back we go — iteration is newest-first, so the
    first message older than the cutoff ends that chat's scan.
    """
    entity = await client.get_entity(src.chat)
    new = seen = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if since_ts is not None and msg.date.timestamp() < since_ts:
            break
        seen += 1
        if _store(conn, src.id, msg):
            new += 1
        if seen % 500 == 0:
            conn.commit()
            print(f"  {src.id}: {seen} scanned, {new} new...", flush=True)
    conn.commit()
    return new, seen


async def cmd_backfill(
    client, sources: list[Source], limit: int | None,
    days: int | None = None, wipe: bool = False,
) -> None:
    since_ts = time.time() - days * 86400 if days else None
    with db_session() as conn:
        total_new = 0
        for src in sources:
            print(f"\n[{src.id}] {src.chat}")
            if wipe:
                n = conn.execute(
                    "DELETE FROM raw_messages WHERE source = ?", (src.id,)
                ).rowcount
                print(f"  wiped {n} previously captured messages")
            try:
                new, seen = await backfill_one(client, conn, src, limit, since_ts)
            except Exception as exc:
                print(f"  ! failed: {exc}")
                continue
            total_new += new
            print(f"  done: {seen} scanned, {new} new")

        print("\nraw_messages by source:")
        for row in conn.execute(
            """SELECT source, COUNT(*) n, MIN(ts) lo, MAX(ts) hi
                 FROM raw_messages GROUP BY source ORDER BY n DESC"""
        ):
            span = ""
            if row["lo"]:
                lo = time.strftime("%Y-%m-%d", time.gmtime(row["lo"]))
                hi = time.strftime("%Y-%m-%d", time.gmtime(row["hi"]))
                span = f"  {lo} -> {hi}"
            print(f"  {row['source']:<12} {row['n']:>7}{span}")
        print(f"\n{total_new} new messages stored.")


async def catch_up(client, sources: list[Source], first_run_days: int = 31) -> int:
    """Fetch every alert that arrived while we were offline.

    The cursor is the highest tg_msg_id already stored per source — Telegram
    message ids are monotonic per chat, so `min_id` fetches exactly the gap:
    no overlap, no misses, regardless of how long the process was down. A
    source with no history at all gets a first_run_days backfill instead.

    New messages are parsed immediately; returns how many events were added.
    """
    from .ingest import ingest_one

    events_added = 0
    since_ts = time.time() - first_run_days * 86400
    with db_session() as conn:
        for src in sources:
            last_id = conn.execute(
                "SELECT MAX(tg_msg_id) FROM raw_messages WHERE source = ?",
                (src.id,),
            ).fetchone()[0]
            try:
                entity = await client.get_entity(src.chat)
            except Exception as exc:
                print(f"  ! {src.id}: {exc}")
                continue

            new = 0
            async for msg in client.iter_messages(entity, min_id=last_id or 0):
                if not last_id and msg.date.timestamp() < since_ts:
                    break
                raw_id = _store(conn, src.id, msg)
                if raw_id:
                    new += 1
                    events_added += ingest_one(conn, raw_id)
            print(f"  {src.id}: {new} missed message(s) fetched"
                  + ("" if last_id else f" (first run, last {first_run_days}d)"))
        set_meta(conn, "last_fetch_ts", int(time.time()))
    return events_added


async def setup_live(client, sources: list[Source]) -> int:
    """Register the new-message handler. Returns how many chats it watches."""
    by_chat = {}
    for src in sources:
        entity = await client.get_entity(src.chat)
        by_chat[entity.id] = src

    @client.on(events.NewMessage(chats=list(by_chat.keys())))
    async def handler(event):  # pragma: no cover - runtime path
        src = by_chat.get(event.chat_id) or by_chat.get(abs(event.chat_id))
        if src is None:
            return
        added = 0
        with db_session() as conn:
            raw_id = _store(conn, src.id, event.message)
            if raw_id is None:
                return
            # Parse just this message; the page's polling picks the change up
            # without any re-scan of history.
            from .ingest import ingest_one
            added = ingest_one(conn, raw_id)
            set_meta(conn, "last_fetch_ts", int(time.time()))

        if added:
            from .positions import run as rebuild_positions
            rebuild_positions()

        stamp = time.strftime("%H:%M:%S")
        preview = _msg_text(event.message).replace("\n", " ")[:90]
        note = f" -> {added} event(s), positions rebuilt" if added else ""
        print(f"[{stamp}] {src.id}: {preview}{note}", flush=True)

    return len(by_chat)


async def cmd_live(client, sources: list[Source]) -> None:
    n = await setup_live(client, sources)
    print(f"Listening on {n} chat(s). Ctrl-C to stop.", flush=True)
    await client.run_until_disconnected()


def cmd_samples(source_id: str, n: int) -> None:
    """Print stored message bodies — the raw material for writing a parser."""
    with db_session() as conn:
        rows = conn.execute(
            """SELECT tg_msg_id, ts, text FROM raw_messages
                WHERE source = ? ORDER BY ts DESC LIMIT ?""",
            (source_id, n),
        ).fetchall()
    if not rows:
        print(f"No messages stored for source '{source_id}'. Run --backfill first.")
        return
    for row in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(row["ts"]))
        print(f"\n===== {source_id} msg {row['tg_msg_id']}  {stamp} =====")
        print(row["text"])


async def amain(args) -> None:
    sources = [s for s in load_sources() if s.enabled or args.list]
    if args.source:
        sources = [s for s in sources if s.id == args.source]
        if not sources and not args.list:
            raise SystemExit(f"No enabled source with id '{args.source}'.")
    if not args.list and not sources:
        raise SystemExit(
            "No enabled sources. Edit config/sources.yaml — set the real bot "
            "@usernames and `enabled: true`.\n"
            "Tip: `python -m hotgraph.capture --list` prints your bot chats."
        )

    if not session_exists():
        raise SystemExit("No session yet. Run: python -m hotgraph.tg_login")

    client = make_client()
    await client.start()
    try:
        if args.list:
            await cmd_list(client)
        elif args.backfill:
            await cmd_backfill(client, sources, args.limit, args.days, args.wipe)
        elif args.live:
            await cmd_live(client, sources)
    finally:
        await client.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="list bot chats and their ids")
    mode.add_argument("--backfill", action="store_true", help="pull chat history")
    mode.add_argument("--live", action="store_true", help="stream new messages")
    mode.add_argument("--samples", metavar="SOURCE_ID", help="print stored messages (no network)")
    ap.add_argument("--limit", type=int, default=None, help="max messages per chat for --backfill")
    ap.add_argument("--source", default=None, help="only this source id")
    ap.add_argument("--days", type=int, default=None, help="only backfill this many days into the past")
    ap.add_argument("--wipe", action="store_true", help="delete each source's stored messages before backfilling")
    ap.add_argument("-n", type=int, default=5, help="how many samples to print")
    args = ap.parse_args()

    if args.samples:
        cmd_samples(args.samples, args.n)
        return
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
