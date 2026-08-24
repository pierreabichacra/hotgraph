# HotGraph

A bubble graph of what the people you track actually hold.

Each **token** is a bubble sized by market cap. Orbiting it are **person**
bubbles sized by the share of that token's supply they own. People who bought
and later sold stay attached, greyed out and sized by their peak holding, so
the graph shows history rather than only the current book.

Everything comes from alerts in your Telegram bot chats. No RPC, no price API,
no API keys beyond Telegram itself.

## How it fits together

```
Telegram (3 bots) ──capture──▶ raw_messages ──ingest──▶ events ──positions──▶ positions
                                (immutable)             (normalized)          (state)
                                                                                 │
                                                                    FastAPI /api/graph
                                                                                 │
                                                                       d3 force bubbles
```

`raw_messages` is append-only. `events` and `positions` are pure derivations,
dropped and rebuilt on every parse. So when a parser turns out to be wrong you
edit the regex and re-run `ingest` — the whole stored history is re-derived
without touching Telegram again.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Credentials live in `.env` (gitignored). `.env.example` is a template — never
put real values there, it is not ignored.

### 1. Log in

```bash
./.venv/bin/python -m hotgraph.tg_login
```

This creates `data/hotgraph.session`, a **new** authorized device on your
account. Telegram allows many concurrent sessions, so your oiltraderbot session
keeps running untouched — the failure people hit (`AUTH_KEY_DUPLICATED`) comes
from two processes sharing *one* session file, which a separate file avoids.
Revoke it any time from Telegram → Settings → Devices ("HotGraph").

### 2. Point it at your bots

```bash
./.venv/bin/python -m hotgraph.capture --list      # prints your bot chats + ids
```

Put the three `@usernames` into `config/sources.yaml` and set `enabled: true`.

### 3. Pull history

```bash
./.venv/bin/python -m hotgraph.capture --backfill
```

### 4. Parse and build positions

```bash
./.venv/bin/python -m hotgraph.ingest
./.venv/bin/python -m hotgraph.positions
```

### 5. Run it — one command

```bash
./.venv/bin/python -m hotgraph.run                 # http://localhost:8000
```

One process does everything: first it **catches up on alerts missed while the
app was off** (the cursor is the highest stored message id per bot, so the gap
fills exactly — no overlap, no misses), then it serves the page and keeps
listening live. New alerts appear on the page within ~10 s, no refresh needed;
the header shows "synced Xs ago". Ctrl-C stops all of it.

The pieces still run separately if you ever want them to
(`uvicorn hotgraph.api:app` / `python -m hotgraph.capture --live`).

## Who shows up, and identity

Every alert embeds the trader's **full wallet address** behind its
[wallet]/address link, and that address is the canonical identity — the same
wallet seen via different bots (labelled `joz` in one, `joswe` in another)
lands in one bubble automatically. Handles are display labels.

When one person trades from **several wallets**, link them in the web UI:
**Merge** button → select any identities (a handle from bot A, addresses from
bots B/C — any two bots or all three) → name the person. Merges are stored in
the DB (`person_map`), positions rebuild immediately, and Unmerge undoes it.
`config/people.yaml` can seed identities, but the UI is the main tool.

`mode: all` (default) draws every tracked trader — the bots only alert on
wallets you added, so everyone in the feed is someone you follow.
`mode: known_only` restricts to people named in yaml or merged in the UI.

If two bots report the SAME trade it counts once — deduped by the tx hash in
the alert's TX link.

## How a holding is computed

The alerts report the share of supply that **one trade** moved (`0.07%`,
`3.16%`), not a running balance. Supply is fixed, so those shares accumulate:

```
pct_supply = sum(pct on buys) - sum(pct on sells)      clamped at 0
```

Two bot statements override the arithmetic, because stated beats computed:

- `Holds 14.27M MM (1.52%)` — the bot's own figure for the total position
  after the trade; it corrects any drift from missed alerts.
- `Exit (TICKER)` — the position is closed. A later buy reopens it.

Clamping at zero matters because a sell whose matching buy predates your
history window would otherwise drive the total negative. When that happens the
position is flagged `confidence: low` and drawn with a dashed outline.

`confidence` is `low` when an alert lacked a percentage, the running total went
negative, or the token is keyed by ticker rather than a contract address.

Trace any bubble back to the alerts behind it:

```bash
./.venv/bin/python -m hotgraph.positions --explain loganlim_x
```

## Adding or fixing a parser

Alert formats are handled by `hotgraph/parsers/tracker.py`, which detects two
layouts sharing a `[CHAIN] ... — S: N` header (chain tags include SOL, ETH,
BSC, BASE, RH/Robinhood, ARC, ABS, HYPE...):

- **SENT / RECEIVED** legs (bots A and B)
- **`🔴Swap X to: Y`** with `Holds`, `Exit`, `PnL` (bot C)

Verified against one month of real traffic: bot_a 100 %, bot_b 100 %,
bot_c 99.9 % of trade alerts parsed. Transfers, approvals and bot commands are
recognized as non-trades and skipped, not counted as failures.

NOTE: bot_a alerts require **Telethon ≥ 1.44** — older versions return them as
`MessageMediaUnsupported` with empty text.

Side is decided by which leg is a quote asset (SOL/ETH/BNB/USDC/...), not by the
header tag — an alert tagged `(OUT)` can still be a buy.

When you meet a format that doesn't parse:

```bash
./.venv/bin/python -m hotgraph.ingest --show-unparsed 20   # see what's missing
./.venv/bin/python -m hotgraph.capture --samples bot_a -n 10
```

Add the message verbatim to `tests/samples.py` with its expected fields, then
make it pass:

```bash
./.venv/bin/python -m tests.test_parser
```

## Per-token actions

Click a token bubble and two buttons hover above it:

- **✓ verify holders** — queries a public RPC (no API key; endpoints in
  `config/rpc.yaml`, majors preconfigured) for each tracked wallet's real
  `balanceOf / totalSupply`. The chain's number overrides the alert-derived
  one until a newer trade lands, and the result shows as a toast.
- **📈 chart** — opens `gmgn.ai/<chain>/token/<address>` in a new tab.

Both need a contract address, so they don't appear on ticker-keyed tokens.

## Token identity

The full mint/contract is not in the alert text — it is hidden behind the
`DEXSCR` / `BIRDEYE` link labels, which is why `capture` stores each message's
full JSON. `token_addr_from_urls()` recovers it from the message entities.

When no address is found the token falls back to a ticker key (`sym:MADE`),
which is weaker: two different tokens sharing a ticker would merge. Those are
marked in the UI as ticker-keyed and count as low confidence.

## Demo data

To see the graph without connecting Telegram:

```bash
./.venv/bin/python -m tests.seed_demo
./.venv/bin/python -m hotgraph.ingest
./.venv/bin/python -m hotgraph.positions
```

Demo rows live under `source='demo'` and are replaced on each re-seed.

## Notes

- Node here is v16, too old for modern JS tooling, so the frontend has no build
  step: plain HTML/CSS/JS with d3 v7 vendored in `web/vendor/`. It works offline.
- Market cap is whatever the most recent alert said, with `mcap_as_of` recorded
  so the tooltip can show how stale it is.
