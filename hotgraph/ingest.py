"""raw_messages -> events. Idempotent and safe to re-run.

    python -m hotgraph.ingest                     # parse everything
    python -m hotgraph.ingest --source bot_a
    python -m hotgraph.ingest --show-unparsed 20  # tune a parser against misses

Re-running is how you fix a parser: edit the regex, run this, and the whole
stored history is re-derived without touching Telegram.
"""

from __future__ import annotations

import argparse

import re

from .config import load_sources, norm_addr
from .db import session as db_session
from .parsers import get_parser
from .parsers.base import ParseContext
from .parsers.tracker import is_multi_wallet

# Alerts with no token trade in them: plain transfers, approvals, raw method
# calls, and your own bot commands / the bot's replies to them. Expected not
# to parse — counted separately so the parse rate reflects real trades only.
RE_NON_TRADE = re.compile(
    r"^\s*/|^Already tracking|^EVM Wallet Tracker|Commands:|"
    r"^\s*Approved?\s*:|^\s*Approval\b",
    re.MULTILINE,
)


def is_non_trade(text: str) -> bool:
    if RE_NON_TRADE.search(text):
        return True
    # A trade alert always names both legs of a swap — or, for the grouped
    # "N wallets sold/bought" layout, says so in the header.
    has_swap = "Swap" in text or ("SENT" in text.upper() and "RECEIV" in text.upper())
    return not has_swap and not is_multi_wallet(text)


def _insert_event(conn, raw_id: int, source_id: str, ev) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO events
              (raw_id, source, chain, chain_tag, token_key, token_symbol, token_name,
               trader_key, trader_handle, wallet_addr, side, is_exit,
               amount_tokens, amount_usd, pct_supply, holds_pct, holds_amount,
               mcap_usd, pnl_usd, pnl_x, tx_hash, ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            raw_id,
            source_id,
            ev.chain,
            ev.chain_tag,
            # EVM addresses are case-insensitive; one bot links the checksummed
            # form and another lowercase, which must not split a token in two.
            norm_addr(ev.chain, ev.token_key),
            ev.token_symbol,
            ev.token_name,
            ev.trader_key,
            ev.trader_handle,
            norm_addr(ev.chain, ev.wallet_addr),
            ev.side,
            1 if ev.is_exit else 0,
            ev.amount_tokens,
            ev.amount_usd,
            ev.pct_supply,
            ev.holds_pct,
            ev.holds_amount,
            ev.mcap_usd,
            ev.pnl_usd,
            ev.pnl_x,
            ev.tx_hash,
            ev.ts,
        ),
    )
    return cur.rowcount > 0


def alias_symbol_tokens(conn) -> int:
    """Merge ticker-keyed tokens into their address-keyed sibling.

    The same trade reported by two bots can land under two token identities:
    one alert links the contract (address key), the other doesn't (sym:TICKER
    key) — drawing the same token twice. When exactly ONE address-keyed token
    with the same symbol exists on the same chain, the sym: events are
    rewritten onto it; with several candidates it stays split rather than
    guessing. Returns how many ticker keys were merged.
    """
    rows = conn.execute(
        """SELECT DISTINCT chain, token_key, UPPER(COALESCE(token_symbol, '')) AS sym
             FROM events
            WHERE token_key LIKE 'sym:%' AND token_symbol IS NOT NULL"""
    ).fetchall()
    merged = 0
    for r in rows:
        cands = conn.execute(
            """SELECT DISTINCT token_key FROM events
                WHERE chain = ? AND UPPER(COALESCE(token_symbol, '')) = ?
                  AND token_key NOT LIKE 'sym:%'""",
            (r["chain"], r["sym"]),
        ).fetchall()
        if len(cands) != 1:
            continue
        target = cands[0]["token_key"]
        # OR IGNORE: if the target already has an identical row (same raw,
        # trader, side) the rewrite would collide — drop the leftover dupe.
        conn.execute(
            "UPDATE OR IGNORE events SET token_key = ? WHERE chain = ? AND token_key = ?",
            (target, r["chain"], r["token_key"]),
        )
        conn.execute(
            "DELETE FROM events WHERE chain = ? AND token_key = ?",
            (r["chain"], r["token_key"]),
        )
        merged += 1
    return merged


def ingest_one(conn, raw_id: int) -> int:
    """Parse a single just-captured message into events. Returns events added.

    Used by live mode — re-parsing the whole history per incoming alert would
    be wasteful, and events are keyed by raw_id so this composes with full
    re-runs safely.
    """
    sources = {s.id: s for s in load_sources()}
    row = conn.execute(
        "SELECT id, source, ts, text, raw_json FROM raw_messages WHERE id = ?",
        (raw_id,),
    ).fetchone()
    if row is None:
        return 0

    src = sources.get(row["source"])
    parser_id = src.parser if src else "tracker"
    parser = get_parser(parser_id) or get_parser("tracker")
    ctx = ParseContext(
        source_id=row["source"],
        ts=row["ts"],
        chain_hint=src.chain_hint if src else None,
        raw_json=row["raw_json"],
    )
    try:
        evs = parser(row["text"], ctx) or []
    except Exception:
        evs = []
    if not evs and not is_non_trade(row["text"]):
        try:
            evs = get_parser("generic")(row["text"], ctx) or []
        except Exception:
            evs = []

    added = 0
    for ev in evs:
        if not ev.token_key or not ev.trader_key:
            continue
        if not ev.ts:
            ev.ts = row["ts"]
        if _insert_event(conn, row["id"], row["source"], ev):
            added += 1
    if added:
        alias_symbol_tokens(conn)
    return added


def run(
    source_filter: str | None = None,
    show_unparsed: int = 0,
    since_ts: float | None = None,
    progress=None,
) -> dict:
    """since_ts limits the rebuild to messages at or after that time — events
    are dropped and re-derived from just that window, so positions reflect it.
    progress, if given, is called as progress(done, total) every few hundred
    messages (used by the web UI's rebuild bar)."""
    sources = {s.id: s for s in load_sources()}
    stats: dict[str, dict] = {}
    unparsed: list[tuple[str, str]] = []

    with db_session() as conn:
        # events/positions are pure derivations — rebuild rather than patch.
        if source_filter:
            conn.execute("DELETE FROM events WHERE source = ?", (source_filter,))
        else:
            conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM positions")
        conn.execute("DELETE FROM tokens")

        conds: list[str] = []
        params: list = []
        if source_filter:
            conds.append("source = ?")
            params.append(source_filter)
        if since_ts is not None:
            conds.append("ts >= ?")
            params.append(int(since_ts))
        where = f" WHERE {' AND '.join(conds)}" if conds else ""
        q = f"SELECT id, source, ts, text, raw_json FROM raw_messages{where} ORDER BY ts ASC"

        total = conn.execute(
            f"SELECT COUNT(*) FROM raw_messages{where}", params
        ).fetchone()[0]

        for i, row in enumerate(conn.execute(q, params)):
            if progress and i % 200 == 0:
                progress(i, total)
            src_id = row["source"]
            st = stats.setdefault(
                src_id,
                {"messages": 0, "parsed": 0, "events": 0, "errors": 0, "non_trade": 0},
            )
            st["messages"] += 1

            src = sources.get(src_id)
            parser_id = src.parser if src else "tracker"
            parser = get_parser(parser_id) or get_parser("tracker")

            ctx = ParseContext(
                source_id=src_id,
                ts=row["ts"],
                chain_hint=src.chain_hint if src else None,
                raw_json=row["raw_json"],
            )
            try:
                evs = parser(row["text"], ctx) or []
            except Exception as exc:
                st["errors"] += 1
                evs = []
                if len(unparsed) < show_unparsed:
                    unparsed.append((src_id, f"[parser error: {exc}]\n{row['text']}"))

            # Fall back to the loose parser before declaring a message a
            # miss — but never for transfers/approvals/commands, where a loose
            # regex would invent trades that don't exist.
            if not evs and parser_id != "generic" and not is_non_trade(row["text"]):
                try:
                    evs = get_parser("generic")(row["text"], ctx) or []
                except Exception:
                    evs = []

            if not evs:
                if is_non_trade(row["text"]):
                    st["non_trade"] += 1
                elif len(unparsed) < show_unparsed:
                    unparsed.append((src_id, row["text"]))
                continue

            st["parsed"] += 1
            for ev in evs:
                if not ev.token_key or not ev.trader_key:
                    continue
                if not ev.ts:
                    ev.ts = row["ts"]
                if _insert_event(conn, row["id"], src_id, ev):
                    st["events"] += 1

        merged = alias_symbol_tokens(conn)

    return {"stats": stats, "unparsed": unparsed, "sym_merged": merged}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--show-unparsed", type=int, default=0, metavar="N",
                    help="print N messages no parser matched")
    ap.add_argument("--days", type=float, default=None,
                    help="only rebuild from messages this many days back")
    args = ap.parse_args()

    import time as _time
    since_ts = _time.time() - args.days * 86400 if args.days else None
    result = run(args.source, args.show_unparsed, since_ts=since_ts)
    stats = result["stats"]

    if not stats:
        print("No raw messages. Run: python -m hotgraph.capture --backfill")
        return

    print(f"{'source':<12} {'messages':>9} {'trades':>7} {'parsed':>8} {'rate':>7} "
          f"{'non-trade':>10} {'errors':>7}")
    print("-" * 68)
    for src, st in sorted(stats.items()):
        trades = st["messages"] - st["non_trade"]
        rate = (st["parsed"] / trades * 100) if trades else 0
        print(f"{src:<12} {st['messages']:>9} {trades:>7} {st['parsed']:>8} {rate:>6.1f}% "
              f"{st['non_trade']:>10} {st['errors']:>7}")

    for src, text in result["unparsed"]:
        print(f"\n----- unparsed [{src}] -----\n{text}")

    print("\nNext: python -m hotgraph.positions")


if __name__ == "__main__":
    main()
