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

## Quick start

You need:

- **Python 3.10 or newer** — [python.org](https://python.org), or
  `winget install Python.Python.3.12` / `brew install python`.
- A **Telegram account** that has opened a chat (pressed *Start*) with each of
  the three tracker bots listed in `config/sources.yaml`.
- Your Telegram **api_id / api_hash** — free, from
  [my.telegram.org](https://my.telegram.org) → *API development tools*. The
  script asks for them the first time.

Then, one command:

| | |
|---|---|
| **Windows** | double-click `start.bat` (or `python start.py`) |
| **macOS / Linux** | `./start.sh` (or `bash start.sh`, or `python3 start.py`) |

The first run creates `.venv`, installs the requirements, asks for your
api_id/api_hash (saved to `.env`), logs you in to Telegram (a login code is
sent to your Telegram app; this creates `data/hotgraph.session`), pulls the
last 31 days of alerts, and opens the page. Every run after that goes straight
to the server — about a second, plus catching up on whatever was missed while
the app was off.

The page is at **http://127.0.0.1:8000**. New alerts appear within about a second, no
refresh needed; the header shows "synced Xs ago". **Ctrl-C stops all of it**
(in `start.bat`, answer *Y* to "Terminate batch job?").

Options: `--port 9000`, `--host 0.0.0.0` (reachable from other machines),
`--no-browser`, `--reinstall` (redo the dependency install).

**⏏ Sign out** (top bar) logs the HotGraph device out of Telegram and deletes
`data/hotgraph.session`; the app stops and `start` immediately asks for a new
login. Captured alerts and positions are kept. The same device can also be
revoked from Telegram → Settings → Devices ("HotGraph").

### Sharing it

Commit, then `git archive --format=zip -o hotgraph.zip HEAD` (or push and share
the URL). Never zip the working directory: it holds `.env`, a live login to
your Telegram account in `data/hotgraph.session`, the database, and `.venv`.

## Manual setup (what `start.py` does)

Interpreter paths below are POSIX; on Windows use `.venv\Scripts\python.exe`.

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

`.env` (gitignored) holds `TG_API_ID=…` and `TG_API_HASH=…`.

### 1. Log in

```bash
./.venv/bin/python -m hotgraph.tg_login
```

This creates `data/hotgraph.session`, a **new** authorized device on your
account. Telegram allows many concurrent sessions, so your other sessions keep
running untouched — the failure people hit (`AUTH_KEY_DUPLICATED`) comes from
two processes sharing *one* session file, which a separate file avoids.
Revoke it any time from Telegram → Settings → Devices ("HotGraph").

### 2. Run it

```bash
./.venv/bin/python -m hotgraph.run                 # http://localhost:8000
```

One process does everything: first it **catches up on alerts missed while the
app was off** (the cursor is the highest stored message id per bot, so the gap
fills exactly — no overlap, no misses; on a fresh database that is a 31-day
backfill), then it serves the page and keeps listening live. The same check repeats every minute while it runs, so an alert Telegram failed to deliver live is fetched a minute late rather than never.

### Optional pieces

`config/sources.yaml` already lists the three bots. To check your account sees
them, pull *all* history instead of 31 days, or re-derive positions by hand:

```bash
./.venv/bin/python -m hotgraph.capture --list      # prints your bot chats + ids
./.venv/bin/python -m hotgraph.capture --backfill  # every alert ever, not just 31 days
./.venv/bin/python -m hotgraph.ingest              # re-parse raw messages
./.venv/bin/python -m hotgraph.positions           # rebuild positions
```

The server and the listener still run separately if you ever want them to
(`uvicorn hotgraph.api:app` / `python -m hotgraph.capture --live`) — but never
alongside `hotgraph.run`, which would share the session file.

## Who shows up, and identity

Every alert embeds the trader's **full wallet address** behind its
[wallet]/address link, and that address is the canonical identity — the same
wallet seen via different bots (labelled `bob` in one, `alice` in another)
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
- Bots A and B never print `Exit`, so the feed tells a **partial sell** ("sold
  38% of bag") from an **EXIT** by replaying the position: a sell that
  leaves the wallet at zero is an exit, whatever the alert said.

Clamping at zero matters because a sell whose matching buy predates your
history window would otherwise drive the total negative. When that happens the
position is flagged `confidence: low` and drawn with a dashed outline.

`confidence` is `low` when an alert lacked a percentage, the running total went
negative, or the token is keyed by ticker rather than a contract address.

Trace any bubble back to the alerts behind it:

```bash
./.venv/bin/python -m hotgraph.positions --explain trader_one
```

## Adding or fixing a parser

Alert formats are handled by `hotgraph/parsers/tracker.py`, which detects two
layouts sharing a `[CHAIN] ... — S: N` header. The tags a bot can write
(SOL, ETH, BSC, BASE, RH/ROBINHOOD, ARC, ABS, HYPE, POLY/MATIC, MONAD...) live
in `hotgraph/chains.py`, one registry that also drives the Chain filter, the
chain badges and which RPC the verifier uses — add a chain there:

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

Add the message to `tests/samples.py` with its expected fields — keeping the
layout exact but **replacing every handle, wallet address, tx hash and
referral code with a placeholder of the same length** (the fixture's link
offsets depend on it; the file ships with the project, so nothing from your
tracker belongs in it) — then make it pass:

```bash
./.venv/bin/python -m tests.test_parser
```

## Finding a token

The search box beside the **Feed** button takes a contract address (or a
ticker). A
token the current filters draw is selected and zoomed to; anything else —
filtered out, outside the top-N, hidden, or fully exited — opens in its own
window: the same bubble with every holder attached, next to everything known
about it (address, market cap, FDV, first/last action, and per holder the
share held, bought/sold, invested/realised/PnL and entry market cap).

## Token window

Right-click a token bubble to open that same window for it: the bubble with
every holder attached in the middle, the token's details and the full holder
list beside it, plus **✓ verify holders** and **💲 verify market cap**.
Right-clicking a holder inside the window opens the holder window.

## Holder window

Right-click a holder bubble to open that wallet: the position it was opened from
in full (share, bought/sold, invested/realised/PnL, entry market cap, alert
count, on-chain check if any), then every token the wallet currently holds
(exited positions folded away underneath). **✓ verify holdings** asks the
chain for the wallet's real balance of each held token, stores the answers
and rebuilds positions — the same check as *verify holders*, from the
wallet's side.

## Arranging the bubbles

The toolbar at the top of the map rearranges the graph without reloading it;
holders travel with their token:

- **⊞ pack** — every token cluster packed as tightly as circles allow.
- **$ mcap**, **⏱ newest**, **⏱ oldest**, **👥 holders** — clusters laid out
  in reading order (left→right, top→bottom) by market cap, last action, or
  number of current holders.

Click the active mode again to release the bubbles back to the free layout.
Live updates keep the chosen arrangement.

## Per-token actions

Click a token bubble and two buttons hover above it:

- **✓ verify holders** — queries a public RPC (no API key; endpoints in
  `config/rpc.yaml`, majors preconfigured) for each tracked wallet's real
  `balanceOf / totalSupply`. The chain's number overrides the alert-derived
  one until a newer trade lands, and the result shows as a toast.
- **GMGN logo** — opens `gmgn.ai/<chain>/token/<address>` in a new tab.

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

- The frontend has no build step and needs no Node: plain HTML/CSS/JS with d3 v7
  vendored in `web/vendor/`. It works offline.
- Market cap is whatever the most recent alert said, with `mcap_as_of` recorded
  so the tooltip can show how stale it is.
