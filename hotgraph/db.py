"""SQLite schema and connection helper.

Three tiers, each derivable from the one before it:

    raw_messages   append-only, never rewritten. The source of truth.
    events         normalized parse output. Dropped and rebuilt on re-parse.
    positions      current state per (chain, token, trader). Rebuilt from events.

Because raw_messages is permanent, fixing a bad parser is a re-run of
`ingest.py`, not a re-scrape of Telegram.

A "trader" is keyed by `trader_key`: the bot's handle for that person when it
prints one (@trader_one, alice, EveTest), otherwise a wallet address. The real
alerts identify people by handle, and the wallet addresses they show are
truncated ("DF1o...7QBH") and so unusable as keys on their own.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .paths import DB_PATH, ensure_dirs

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Tier 1: immutable capture ------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    tg_msg_id   INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    raw_json    TEXT,
    captured_at INTEGER NOT NULL,
    UNIQUE (source, tg_msg_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_source_ts ON raw_messages (source, ts);

-- Tier 2: normalized events ------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_id        INTEGER NOT NULL REFERENCES raw_messages (id) ON DELETE CASCADE,
    source        TEXT    NOT NULL,
    chain         TEXT    NOT NULL,        -- 'solana' | 'evm'
    chain_tag     TEXT,                    -- original tag: SOL, BASE, BSC, ETH...
    token_key     TEXT    NOT NULL,        -- mint/contract if known, else 'sym:TICKER'
    token_symbol  TEXT,
    token_name    TEXT,
    trader_key    TEXT    NOT NULL,        -- handle (lowercased) or wallet address
    trader_handle TEXT,                    -- as printed by the bot
    wallet_addr   TEXT,                    -- often truncated, kept for reference
    side          TEXT    NOT NULL,        -- 'BUY' | 'SELL'
    is_exit       INTEGER NOT NULL DEFAULT 0,
    amount_tokens REAL,
    amount_usd    REAL,
    pct_supply    REAL,                    -- 0..100, share of supply THIS trade moved
    holds_pct     REAL,                    -- bot-stated TOTAL holding after the trade
    holds_amount  REAL,
    mcap_usd      REAL,
    pnl_usd       REAL,
    pnl_x         REAL,
    tx_hash       TEXT,                    -- from the TX link; enables cross-bot dedup
    counterparty  TEXT,                    -- transfers: the other wallet (see parsers.base)
    ts            INTEGER NOT NULL,
    UNIQUE (raw_id, trader_key, token_key, side)
);
CREATE INDEX IF NOT EXISTS idx_events_key ON events (chain, token_key, trader_key, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts  ON events (ts);
-- idx_events_side (side, counterparty) is created in _migrate(): on a database
-- from before the counterparty column existed, the column must be added first.

-- Suspected-wallet suggestions the user waved away (a transfer recipient
-- that is NOT one of the sender's wallets — an exchange deposit, a friend).
CREATE TABLE IF NOT EXISTS wallet_dismissed (
    trader_key  TEXT PRIMARY KEY,
    ts          INTEGER NOT NULL
);

-- Tier 3: derived state ----------------------------------------------------
CREATE TABLE IF NOT EXISTS tokens (
    chain          TEXT NOT NULL,
    token_key      TEXT NOT NULL,
    chain_tag      TEXT,               -- BSC / ETH / RH / SOL... for links & RPC
    symbol         TEXT,
    name           TEXT,
    last_mcap_usd  REAL,
    fdv_usd        REAL,               -- fully diluted valuation (DexScreener); NULL when unknown
    mcap_as_of     INTEGER,
    n_events       INTEGER NOT NULL DEFAULT 0,
    first_seen     INTEGER,
    last_seen      INTEGER,
    PRIMARY KEY (chain, token_key)
);

-- On-chain balance checks (the "verify holders" button). The freshest row
-- per (token, wallet) overrides computed positions until a newer event lands.
CREATE TABLE IF NOT EXISTS verifications (
    chain      TEXT NOT NULL,
    token_key  TEXT NOT NULL,
    trader_key TEXT NOT NULL,
    pct        REAL,               -- 0..100 share of supply, from the chain
    balance    REAL,
    ts         INTEGER NOT NULL,
    PRIMARY KEY (chain, token_key, trader_key)
);

-- Market caps fetched on demand from DexScreener (the drawer's "refresh
-- mcaps" button). The freshest row per token overrides the alert-derived
-- figure across position rebuilds, until a newer alert states one.
CREATE TABLE IF NOT EXISTS mcap_checks (
    chain     TEXT NOT NULL,
    token_key TEXT NOT NULL,
    mcap_usd  REAL,
    fdv_usd   REAL,
    ts        INTEGER NOT NULL,
    PRIMARY KEY (chain, token_key)
);

-- Tokens the user chose to hide (the bubble's 🚫 button). Blacklisted tokens
-- are excluded from the graph and feed until restored from the Tokens panel.
CREATE TABLE IF NOT EXISTS token_blacklist (
    chain     TEXT NOT NULL,
    token_key TEXT NOT NULL,
    symbol    TEXT,
    ts        INTEGER NOT NULL,
    PRIMARY KEY (chain, token_key)
);

-- Tokens whose last holder sold out — the page toasts these as they happen.
CREATE TABLE IF NOT EXISTS eliminations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chain     TEXT    NOT NULL,
    token_key TEXT    NOT NULL,
    symbol    TEXT,
    ts        INTEGER NOT NULL
);

-- Small key-value store: last_fetch_ts and similar bookkeeping.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Identity merges made from the UI: trader_key -> person. Rows here beat
-- people.yaml (which acts only as an initial seed), so unmerging is deleting
-- the row. A person exists simply by having keys mapped to them.
CREATE TABLE IF NOT EXISTS person_map (
    trader_key  TEXT PRIMARY KEY,
    person      TEXT NOT NULL,
    color       TEXT,
    updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_person_map_person ON person_map (person);

CREATE TABLE IF NOT EXISTS positions (
    chain          TEXT NOT NULL,
    token_key      TEXT NOT NULL,
    trader_key     TEXT NOT NULL,
    person         TEXT,                   -- resolved via people.yaml, else the handle
    trader_handle  TEXT,
    pct_supply     REAL,                   -- current running share of supply, 0..100
    peak_pct       REAL,                   -- max ever held; sold bubbles size off this
    bought_pct     REAL NOT NULL DEFAULT 0,
    sold_pct       REAL NOT NULL DEFAULT 0,
    status         TEXT NOT NULL,          -- 'HOLDING' | 'SOLD' | 'UNKNOWN'
    confidence     TEXT NOT NULL,          -- 'high' | 'low'
    invested_usd   REAL NOT NULL DEFAULT 0,
    realized_usd   REAL NOT NULL DEFAULT 0,
    pnl_usd        REAL,
    entry_mcap_usd REAL,                   -- mcap at the first buy
    avg_entry_mcap_usd REAL,               -- buy-weighted average mcap across all buys
    n_events       INTEGER NOT NULL DEFAULT 0,
    first_seen     INTEGER,
    last_seen      INTEGER,
    PRIMARY KEY (chain, token_key, trader_key)
);
CREATE INDEX IF NOT EXISTS idx_positions_person ON positions (person);

-- Activity strip history, always at 30-minute resolution (coarser views are
-- summed from it). events is a derivation that a windowed rebuild trims, so
-- the per-bucket totals the chart shows are snapshotted here and merged on
-- every read; a past day stays viewable after its events are gone.
CREATE TABLE IF NOT EXISTS activity_buckets (
    day_start INTEGER NOT NULL,        -- epoch of the (client-local) midnight
    chain     TEXT NOT NULL,           -- 'all' | 'evm' | 'solana' | ...
    slot      INTEGER NOT NULL,        -- 0..47, half hour within the day
    tx        INTEGER NOT NULL DEFAULT 0,
    buys      INTEGER NOT NULL DEFAULT 0,
    usd       REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (day_start, chain, slot)
);
"""


def connect(path=None) -> sqlite3.Connection:
    """Open the database, creating it and its schema if needed."""
    ensure_dirs()
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a table already existed on disk.

    CREATE TABLE IF NOT EXISTS never alters an existing table, and raw_messages
    holds captured history worth keeping — so patch in place rather than asking
    users to delete the DB.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
    for col, decl in (
        ("tx_hash", "TEXT"),
        ("holds_pct", "REAL"),
        ("holds_amount", "REAL"),
        ("counterparty", "TEXT"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE events ADD COLUMN {col} {decl}")
    # Needs the counterparty column, so it cannot live in SCHEMA.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_side ON events (side, counterparty)")

    tcols = {r["name"] for r in conn.execute("PRAGMA table_info(tokens)")}
    if "chain_tag" not in tcols:
        conn.execute("ALTER TABLE tokens ADD COLUMN chain_tag TEXT")
    if "fdv_usd" not in tcols:
        conn.execute("ALTER TABLE tokens ADD COLUMN fdv_usd REAL")

    mcols = {r["name"] for r in conn.execute("PRAGMA table_info(mcap_checks)")}
    if "fdv_usd" not in mcols:
        conn.execute("ALTER TABLE mcap_checks ADD COLUMN fdv_usd REAL")

    pcols = {r["name"] for r in conn.execute("PRAGMA table_info(positions)")}
    if "avg_entry_mcap_usd" not in pcols:
        conn.execute("ALTER TABLE positions ADD COLUMN avg_entry_mcap_usd REAL")


@contextmanager
def session(path=None) -> Iterator[sqlite3.Connection]:
    """Connection that commits on clean exit and rolls back on error."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {}
    for table in ("raw_messages", "events", "tokens", "positions"):
        out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out
