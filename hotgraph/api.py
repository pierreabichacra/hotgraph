"""FastAPI app: serves the graph JSON and the static page.

    uvicorn hotgraph.api:app --reload    ->  http://localhost:8000
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chains as chains_mod
from . import positions as positions_mod
from .config import person_colors
from .db import counts, session as db_session
from .paths import WEB_DIR

app = FastAPI(title="HotGraph")


def _person_node(p, colors, size_pct: float) -> dict:
    token_id = f"token:{p['chain']}:{p['token_key']}"
    return {
        "id": f"pos:{p['chain']}:{p['token_key']}:{p['trader_key']}",
        "kind": "person",
        "token_id": token_id,
        "trader_key": p["trader_key"],
        "person": p["person"],
        "handle": p["trader_handle"],
        "color": colors.get(p["person"]),
        "value": size_pct,
        "pct_supply": p["pct_supply"],
        "peak_pct": p["peak_pct"],
        "bought_pct": p["bought_pct"],
        "sold_pct": p["sold_pct"],
        "status": p["status"],
        "confidence": p["confidence"],
        "invested_usd": p["invested_usd"],
        "realized_usd": p["realized_usd"],
        "pnl_usd": p["pnl_usd"],
        "entry_mcap_usd": p["entry_mcap_usd"],
        "avg_entry_mcap_usd": p["avg_entry_mcap_usd"],
        "n_events": p["n_events"],
        "first_seen": p["first_seen"],
        "last_seen": p["last_seen"],
    }


def _token_node(t, st) -> dict:
    n_holding = st["n_holding"] if st else 0
    return {
        "id": f"token:{t['chain']}:{t['token_key']}",
        "kind": "token",
        "symbol": t["symbol"] or str(t["token_key"]).replace("sym:", ""),
        "name": t["name"],
        "chain": t["chain"],
        "chain_tag": t["chain_tag"],
        "token_key": t["token_key"],
        "value": t["last_mcap_usd"] or 0.0,
        "mcap_usd": t["last_mcap_usd"],
        "fdv_usd": t["fdv_usd"],
        "mcap_as_of": t["mcap_as_of"],
        "resolved": not str(t["token_key"]).startswith("sym:"),
        "n_events": t["n_events"],
        "n_holders": n_holding,
        "n_positions": st["n_positions"] if st else 0,
        "last_action": st["last_action"] if st else None,
        # Everyone we track has exited — the token is history, not book.
        "dead": n_holding == 0,
    }


# Sold bubbles size off their peak so they don't collapse to nothing.
def _size_pct(p) -> float:
    return (p["peak_pct"] if p["status"] == "SOLD" else p["pct_supply"]) or 0.0


@app.get("/api/graph")
def graph(
    chain: str | None = None,  # comma-separated chain tags (BASE,RH...) or a family (evm)
    include_sold: bool = True,
    min_mcap: float = 0.0,
    max_mcap: float = 0.0,    # 0 = no cap
    min_pct: float = 0.0,
    top: int = 150,
    sort: str = "mcap",       # 'mcap' | 'latest' | 'holders'
    since_hours: float = 0,   # 0 = no window; else only tokens with action in it
    persons: str | None = None,  # comma-separated person labels; None = everyone
):
    """Token bubbles with their holder bubbles attached.

    A person node exists per (person, token) pair, because its size is a share
    of that specific token's supply. Sold positions are kept and sized by
    peak_pct so the history stays visible on the graph.
    """
    colors = person_colors()

    with db_session() as conn:
        # Per-token position stats drive both the "dead token" flag (nobody
        # holds anymore) and the sort modes.
        tstats = {
            (r["chain"], r["token_key"]): r
            for r in conn.execute(
                """SELECT chain, token_key,
                          SUM(status = 'HOLDING')     AS n_holding,
                          COUNT(*)                    AS n_positions,
                          MAX(last_seen)              AS last_action
                     FROM positions GROUP BY chain, token_key"""
            )
        }

        chain_sql, chain_params = chains_mod.sql_clause(chain, "t.chain", "t.chain_tag")
        tok_rows = conn.execute(
            f"""SELECT t.chain, t.chain_tag, t.token_key, t.symbol, t.name,
                      t.last_mcap_usd, t.fdv_usd, t.mcap_as_of, t.n_events
                 FROM tokens t
                WHERE COALESCE(t.last_mcap_usd, 0) >= ?
                  AND (? <= 0 OR COALESCE(t.last_mcap_usd, 0) <= ?){chain_sql}""",
            (min_mcap, max_mcap, max_mcap, *chain_params),
        ).fetchall()

        def _metric(t) -> float:
            st = tstats.get((t["chain"], t["token_key"]))
            if sort == "latest":
                return st["last_action"] if st and st["last_action"] else 0
            if sort == "holders":
                return st["n_holding"] if st else 0
            return t["last_mcap_usd"] or 0

        def _alive(t) -> bool:
            st = tstats.get((t["chain"], t["token_key"]))
            return bool(st and st["n_holding"])

        def _in_window(t) -> bool:
            if not since_hours:
                return True
            st = tstats.get((t["chain"], t["token_key"]))
            cutoff = time.time() - since_hours * 3600
            return bool(st and st["last_action"] and st["last_action"] >= cutoff)

        blocked = {
            (r["chain"], r["token_key"])
            for r in conn.execute("SELECT chain, token_key FROM token_blacklist")
        }

        # Fully-exited tokens (nobody tracked holds anymore) are not drawn at
        # all, nor are blacklisted ones — filtered before the top-N cut so
        # hiding a token frees its slot for the next one. Sold positions on
        # still-held tokens keep their grey bubbles. A time window keeps only
        # tokens someone traded within it — their full current holder picture
        # stays visible for context.
        tok_rows = sorted(
            (t for t in tok_rows
             if (t["chain"], t["token_key"]) not in blocked
             and _alive(t) and _in_window(t)),
            key=lambda t: -_metric(t),
        )

        # 31 days of alerts covers ~2000 tokens — far more than a readable
        # graph. Keep the top-N (0 = no cap); the rest stay queryable, just
        # not drawn.
        if top and top > 0:
            tok_rows = tok_rows[:top]
        allowed = {(t["chain"], t["token_key"]) for t in tok_rows}

        # Positions carry no chain_tag; narrowing by family is enough here
        # since every row is checked against the drawn tokens below anyway.
        fam_sql, fam_params = chains_mod.sql_clause(chain, "chain", None)
        pos_rows = conn.execute(
            f"""SELECT chain, token_key, trader_key, person, trader_handle,
                      pct_supply, peak_pct, bought_pct, sold_pct, status, confidence,
                      invested_usd, realized_usd, pnl_usd, entry_mcap_usd,
                      avg_entry_mcap_usd, n_events, first_seen, last_seen
                 FROM positions
                WHERE 1 = 1{fam_sql}""",
            fam_params,
        ).fetchall()

        stats = counts(conn)

    nodes: list[dict] = []
    links: list[dict] = []
    live_tokens: set[tuple[str, str]] = set()

    # Multi-user filter: only these people's bubbles are drawn, and tokens
    # none of them touched disappear with them (via live_tokens below).
    sel_persons = {s.strip().lower() for s in (persons or "").split(",") if s.strip()}

    for p in pos_rows:
        if (p["chain"], p["token_key"]) not in allowed:
            continue
        if sel_persons and (p["person"] or "").lower() not in sel_persons:
            continue
        if not include_sold and p["status"] == "SOLD":
            continue
        size_pct = _size_pct(p)
        if size_pct < min_pct:
            continue

        tkey = (p["chain"], p["token_key"])
        node = _person_node(p, colors, size_pct)
        nodes.append(node)
        links.append({"source": node["id"], "target": node["token_id"], "status": p["status"]})
        live_tokens.add(tkey)

    for t in tok_rows:
        tkey = (t["chain"], t["token_key"])
        if tkey not in live_tokens:
            continue  # a token with no drawable positions isn't worth a bubble
        nodes.append(_token_node(t, tstats.get(tkey)))

    return JSONResponse({
        "nodes": nodes,
        "links": links,
        "stats": stats,
        "generated_at": int(time.time()),
    })


ACT_BASE = 1800                        # snapshot resolution: 30 minutes
ACT_BUCKETS = (1800, 3600, 7200, 10800, 21600, 28800, 43200)


def _dedup_cte(chain: str | None, start: int, end: int) -> tuple[str, list]:
    """Trades deduplicated by tx hash — two bots reporting the same swap
    must count as one transaction and one lot of dollars. Returns the CTE
    and its bound parameters."""
    chain_sql, chain_params = chains_mod.sql_clause(chain)
    return (f"""WITH dedup AS (
                  SELECT MIN(id) AS id FROM events
                   WHERE ts >= ? AND ts < ?{chain_sql}
                     AND side IN ('BUY', 'SELL')
                   GROUP BY COALESCE(tx_hash, 'id:' || id)
              )""", [start, end, *chain_params])


@app.get("/api/activity")
def activity(start: int, bucket: int = ACT_BASE, chain: str | None = None):
    """Alert activity over one day: transactions and USD volume per bucket,
    from `start` (the client's local midnight, epoch seconds) for 24 hours.

    Always computed at 30-minute resolution, merged with the stored snapshot
    (per slot the larger figure wins — alerts only ever add, while a
    windowed rebuild can only remove), stored back, and then summed up to
    the requested bucket size. Any day ever viewed stays viewable.
    """
    if bucket not in ACT_BUCKETS:
        bucket = min(ACT_BUCKETS, key=lambda b: abs(b - bucket))
    end = start + 86400
    n = 86400 // ACT_BASE
    chain_key = chains_mod.filter_key(chain)
    cte, cte_params = _dedup_cte(chain, start, end)
    with db_session() as conn:
        rows = conn.execute(
            cte + """
               SELECT (e.ts - ?) / ? AS b,
                      COUNT(*)                       AS tx,
                      SUM(e.side = 'BUY')            AS buys,
                      SUM(COALESCE(e.amount_usd, 0)) AS usd
                 FROM events e JOIN dedup d ON d.id = e.id
                GROUP BY b""",
            (*cte_params, start, ACT_BASE),
        ).fetchall()

        base = [{"tx": 0, "buys": 0, "usd": 0.0} for _ in range(n)]
        for r in rows:
            b = int(r["b"])
            if 0 <= b < n:
                base[b] = {"tx": r["tx"], "buys": r["buys"] or 0, "usd": round(r["usd"] or 0.0, 2)}

        for r in conn.execute(
            "SELECT slot, tx, buys, usd FROM activity_buckets WHERE day_start = ? AND chain = ?",
            (start, chain_key),
        ):
            i = r["slot"]
            if 0 <= i < n:
                cur = base[i]
                base[i] = {"tx": max(cur["tx"], r["tx"]), "buys": max(cur["buys"], r["buys"]),
                           "usd": max(cur["usd"], r["usd"])}

        conn.executemany(
            """INSERT INTO activity_buckets (day_start, chain, slot, tx, buys, usd)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(day_start, chain, slot)
               DO UPDATE SET tx = excluded.tx, buys = excluded.buys, usd = excluded.usd""",
            [(start, chain_key, i, b["tx"], b["buys"], b["usd"]) for i, b in enumerate(base) if b["tx"]],
        )

        span = conn.execute(
            "SELECT MIN(day_start), MAX(day_start) FROM activity_buckets WHERE chain = ?",
            (chain_key,),
        ).fetchone()

    k = bucket // ACT_BASE
    buckets = []
    for i in range(0, n, k):
        grp = base[i:i + k]
        buckets.append({
            "tx": sum(b["tx"] for b in grp),
            "buys": sum(b["buys"] for b in grp),
            "usd": round(sum(b["usd"] for b in grp), 2),
        })

    return {
        "start": start,
        "bucket": bucket,
        "buckets": buckets,
        "tx": sum(b["tx"] for b in buckets),
        "usd": round(sum(b["usd"] for b in buckets), 2),
        "history": {"first": span[0], "last": span[1]},
    }


@app.get("/api/activity/txs")
def activity_txs(start: int, end: int, chain: str | None = None, limit: int = 400):
    """The individual trades inside one bucket of the activity strip, newest
    first, in the feed's item shape so the page draws them the same way."""
    limit = max(1, min(limit, 1000))
    cte, cte_params = _dedup_cte(chain, start, end)
    with db_session() as conn:
        rows = conn.execute(
            cte + """
               SELECT e.ts, e.side, e.is_exit, e.token_symbol, e.token_key,
                      e.chain, e.chain_tag, e.trader_handle, e.trader_key,
                      e.pct_supply, e.amount_usd, e.mcap_usd, e.source, e.tx_hash, e.raw_id
                 FROM events e JOIN dedup d ON d.id = e.id
                ORDER BY e.ts DESC LIMIT ?""",
            (*cte_params, limit),
        ).fetchall()
    items = [{
        "ts": r["ts"],
        "type": r["side"],
        "is_exit": bool(r["is_exit"]),
        "symbol": r["token_symbol"] or str(r["token_key"]).replace("sym:", ""),
        "chain": r["chain"],
        "token_key": r["token_key"],
        "chain_tag": r["chain_tag"],
        "who": r["trader_handle"] or r["trader_key"],
        "pct_supply": r["pct_supply"],
        "amount_usd": r["amount_usd"],
        "mcap_usd": r["mcap_usd"],
        "source": r["source"],
        "tx_hash": r["tx_hash"],
        "raw_id": r["raw_id"],
    } for r in rows]
    return {"items": items, "start": start, "end": end}


# The hyperlinks inside one captured alert, as (label, url) — the labels are
# the link texts the bot used ("TX", "GMGN", "DXS", a wallet nickname...).
_RE_BARE_URL = re.compile(r"https?://[^\s()<>\]]+")


def _link_kind(url: str) -> str:
    u = url.lower()
    if "/tx/" in u:
        return "tx"
    if "/address/" in u or "/account/" in u:
        return "wallet"
    if "/block/" in u:
        return "block"
    if "/token/" in u and "scan" in u:
        return "token"
    if any(h in u for h in ("dexscreener", "gmgn", "defined.fi", "basedbot", "dextools", "birdeye", "photon", "bullx", "axiom")):
        return "chart"
    if "t.me/" in u:
        return "telegram"
    return "other"


@app.get("/api/message/{raw_id}/links")
def message_links(raw_id: int):
    from urllib.parse import urlparse
    from .parsers.base import linked_urls_from_raw_json

    with db_session() as conn:
        row = conn.execute("SELECT text, raw_json FROM raw_messages WHERE id = ?", (raw_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "no such message")
    text = row["text"] or ""
    text16 = text.encode("utf-16-le")

    links: list[dict] = []
    seen: set[str] = set()

    def add(label: str, url: str) -> None:
        if url in seen:
            return
        seen.add(url)
        host = urlparse(url).netloc.replace("www.", "")
        label = (label or "").strip()
        if not label or label.startswith("http"):
            label = host
        links.append({"label": label[:40], "url": url, "host": host, "kind": _link_kind(url)})

    # Telegram entities: offsets are UTF-16 code units, hence the byte slicing.
    for off, ln, url in linked_urls_from_raw_json(row["raw_json"]):
        label = text16[off * 2:(off + ln) * 2].decode("utf-16-le", "ignore")
        add(label, url)
    # Bare URLs typed into the text itself.
    for m in _RE_BARE_URL.finditer(text):
        add("", m.group(0).rstrip(".,"))

    return {"raw_id": raw_id, "links": links}


# ---------------------------------------------------------------- live push
# Every open page holds a /api/stream connection. The moment the listener has
# stored a Telegram alert (and rebuilt positions), notify_change() wakes each
# of them with a fresh /api/health payload, so the graph moves within the
# rebuild time instead of waiting for the page's next poll. The poll stays as
# a fallback for browsers/proxies that drop the stream.
_STREAM_SUBS: set[asyncio.Queue] = set()


def notify_change() -> None:
    """Wake every /api/stream subscriber. Coalesces: a burst of alerts while a
    page is still catching up becomes one wake-up, not a queue of them."""
    for q in list(_STREAM_SUBS):
        if q.empty():
            q.put_nowait(True)


@app.get("/api/stream")
async def stream():
    async def gen():
        q: asyncio.Queue = asyncio.Queue()
        _STREAM_SUBS.add(q)
        try:
            # First payload straight away, so a reconnecting page catches up
            # on anything it missed while the stream was down.
            yield f"event: change\ndata: {json.dumps(health())}\n\n"
            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=20)
                    yield f"event: change\ndata: {json.dumps(health())}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keeps proxies from timing the stream out
        finally:
            _STREAM_SUBS.discard(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health():
    from .db import get_meta
    with db_session() as conn:
        out = counts(conn)
        lf = get_meta(conn, "last_fetch_ts")
        out["last_fetch"] = int(lf) if lf else None
        # Bumped on every positions rebuild — the page treats any change as
        # "data moved, refetch", closing the gap between event insert and
        # rebuild completing.
        out["built_at"] = get_meta(conn, "positions_built_at")
        # Unseen suspected-wallet suggestions — the top-bar button pulses.
        out["wallet_suggestions_new"] = _new_suggestion_count(conn)
        # Recent full-exit removals, oldest first — the page toasts the ones
        # with ids it hasn't seen yet.
        out["eliminations"] = [
            dict(r)
            for r in reversed(conn.execute(
                """SELECT id, chain, token_key, symbol, ts FROM eliminations
                    ORDER BY id DESC LIMIT 10"""
            ).fetchall())
        ]
        return out


@app.get("/api/feed")
def feed(kind: str = "all", limit: int = 100):
    """Chronological notification feed for the left drawer.

    kind: 'buys' | 'sells' | 'swaps' (both) | 'other' (alerts that produced no
    trade: transfers, approvals, tracking confirmations) | 'all'.
    """
    limit = max(1, min(limit, 300))
    items: list[dict] = []

    with db_session() as conn:
        if kind in ("buys", "sells", "swaps", "transfers", "all"):
            side_clause = {
                "buys": "e.side = 'BUY'",
                "sells": "e.side = 'SELL'",
                "swaps": "e.side IN ('BUY', 'SELL')",
                "transfers": "e.side IN ('TRANSFER_OUT', 'TRANSFER_IN')",
            }.get(kind, "1=1")
            for r in conn.execute(
                f"""SELECT e.ts, e.side, e.is_exit, e.token_symbol, e.token_key,
                           e.chain, e.chain_tag, e.trader_handle, e.trader_key,
                           e.pct_supply, e.amount_usd, e.mcap_usd, e.source, e.raw_id,
                           e.counterparty, e.sold_frac, e.remaining_pct
                      FROM events e
                     WHERE {side_clause}
                       AND NOT EXISTS (SELECT 1 FROM token_blacklist b
                                        WHERE b.chain = e.chain
                                          AND b.token_key = e.token_key)
                     ORDER BY e.ts DESC LIMIT ?""",
                (limit,),
            ):
                # A sell is an EXIT when the bot said so OR the replayed
                # position hit zero after it (bots A/B never print Exit);
                # otherwise it's partial when we know what share of the bag
                # moved, and just "a sell" when the history is too thin to say.
                exit_kind = None
                if r["side"] == "SELL":
                    rem = r["remaining_pct"]
                    if r["is_exit"] or (rem is not None and rem <= positions_mod.DUST_PCT):
                        exit_kind = "full"
                    elif r["sold_frac"] is not None:
                        exit_kind = "partial"
                items.append({
                    "ts": r["ts"],
                    "type": r["side"],
                    "is_exit": bool(r["is_exit"]),
                    "exit_kind": exit_kind,
                    "sold_frac": r["sold_frac"],
                    "remaining_pct": r["remaining_pct"],
                    "symbol": r["token_symbol"] or str(r["token_key"]).replace("sym:", ""),
                    "chain": r["chain"],
                    "token_key": r["token_key"],
                    "chain_tag": r["chain_tag"],
                    "who": r["trader_handle"] or r["trader_key"],
                    "pct_supply": r["pct_supply"],
                    "amount_usd": r["amount_usd"],
                    "mcap_usd": r["mcap_usd"],
                    "source": r["source"],
                    "raw_id": r["raw_id"],
                    "counterparty": r["counterparty"],
                })

        if kind in ("other", "all"):
            # Captured messages that produced no trade event. Leading-slash
            # messages are your own bot commands, not notifications.
            for r in conn.execute(
                """SELECT r.id, r.ts, r.source, r.text
                     FROM raw_messages r
                    WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.raw_id = r.id)
                      AND r.text NOT LIKE '/%'
                    ORDER BY r.ts DESC LIMIT ?""",
                (limit,),
            ):
                lines = [ln.strip() for ln in r["text"].splitlines() if ln.strip()]
                items.append({
                    "ts": r["ts"],
                    "type": "OTHER",
                    "title": lines[0][:90] if lines else "",
                    "detail": " · ".join(lines[1:3])[:120],
                    "source": r["source"],
                    "raw_id": r["id"],
                })

    items.sort(key=lambda x: -x["ts"])
    return {"items": items[:limit], "kind": kind}


# ---------------------------------------------------------------------------
# Identity merging
#
# The bots use different identity schemes — bot A prints handles, bots B/C
# print wallet addresses — so the same human shows up under several
# trader_keys. Merges map any set of keys (2 bots or all 3) onto one person
# name, stored in person_map; positions are rebuilt so their events combine
# into a single bubble per token.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Suspected new wallets
#
# A tracked wallet sending tokens somewhere with nothing coming back is a
# transfer (parsers.base TRANSFER_OUT), and the recipient is very often
# another wallet of the same person. When that recipient is not tracked —
# no bot alerts on it, no merge maps it — it is suggested here, derived from
# the events themselves so it survives rebuilds. Merging (existing
# /api/merge) or dismissing makes it go away; "seen" only stops the pulse.
# ---------------------------------------------------------------------------

_SUGGEST_WHERE = """
      e.side = 'TRANSFER_OUT'
      AND e.counterparty IS NOT NULL
      AND e.counterparty NOT LIKE 'trunc:%'
      AND NOT EXISTS (SELECT 1 FROM person_map p WHERE p.trader_key = e.counterparty)
      AND NOT EXISTS (SELECT 1 FROM wallet_dismissed d WHERE d.trader_key = e.counterparty)
      AND NOT EXISTS (SELECT 1 FROM events t
                       WHERE t.trader_key = e.counterparty AND t.side IN ('BUY', 'SELL'))
"""


def _suggestions_seen_id(conn) -> int:
    from .db import get_meta
    v = get_meta(conn, "wallet_suggestions_seen_id")
    return int(v) if v else 0


def _new_suggestion_count(conn) -> int:
    return conn.execute(
        f"SELECT COUNT(DISTINCT e.counterparty) FROM events e WHERE e.id > ? AND {_SUGGEST_WHERE}",
        (_suggestions_seen_id(conn),),
    ).fetchone()[0]


@app.get("/api/wallet_suggestions")
def wallet_suggestions():
    """Untracked wallets that tracked people moved tokens to, newest first,
    one entry per wallet with every transfer into it."""
    with db_session() as conn:
        seen = _suggestions_seen_id(conn)
        rows = conn.execute(
            f"""SELECT e.id, e.ts, e.chain, e.chain_tag, e.counterparty, e.trader_key,
                       e.trader_handle, e.token_key, e.token_symbol, e.pct_supply,
                       e.amount_tokens, e.mcap_usd, e.raw_id
                  FROM events e
                 WHERE {_SUGGEST_WHERE}
                 ORDER BY e.ts DESC"""
        ).fetchall()
        mapped = {r["trader_key"]: r["person"] for r in conn.execute("SELECT trader_key, person FROM person_map")}
        pos_person = {
            r["trader_key"]: r["person"]
            for r in conn.execute("SELECT DISTINCT trader_key, person FROM positions WHERE person IS NOT NULL")
        }
        colors = person_colors()

    groups: dict[str, dict] = {}
    for r in rows:
        w = r["counterparty"]
        sender = r["trader_key"]
        person = mapped.get(sender) or pos_person.get(sender) or r["trader_handle"] or sender
        g = groups.get(w)
        if g is None:
            g = groups[w] = {
                "wallet": w, "chain": r["chain"], "chain_tags": [], "senders": [],
                "tokens": [], "first_ts": r["ts"], "last_ts": r["ts"], "max_id": r["id"], "n": 0,
            }
        g["n"] += 1
        g["first_ts"] = min(g["first_ts"], r["ts"])
        g["last_ts"] = max(g["last_ts"], r["ts"])
        g["max_id"] = max(g["max_id"], r["id"])
        tag = chains_mod.canonical_tag(r["chain_tag"])
        if tag and tag not in g["chain_tags"]:
            g["chain_tags"].append(tag)
        if not any(s["key"] == sender for s in g["senders"]):
            g["senders"].append({
                "key": sender, "person": person, "handle": r["trader_handle"],
                "color": colors.get(person),
            })
        g["tokens"].append({
            "chain": r["chain"], "chain_tag": r["chain_tag"], "token_key": r["token_key"],
            "symbol": r["token_symbol"] or str(r["token_key"]).replace("sym:", ""),
            "pct": r["pct_supply"], "amount": r["amount_tokens"], "mcap_usd": r["mcap_usd"],
            "ts": r["ts"], "raw_id": r["raw_id"],
        })
    out = sorted(groups.values(), key=lambda g: -g["last_ts"])
    for g in out:
        g["new"] = g["max_id"] > seen
    return {"suggestions": out, "new": sum(1 for g in out if g["new"]), "seen_id": seen}


@app.post("/api/wallet_suggestions/seen")
def wallet_suggestions_seen():
    """The user opened the list: everything up to now stops counting as new."""
    from .db import set_meta
    with db_session() as conn:
        top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
        set_meta(conn, "wallet_suggestions_seen_id", int(top))
    return {"ok": True, "seen_id": int(top)}


class DismissRequest(BaseModel):
    trader_key: str


@app.post("/api/wallet_suggestions/dismiss")
def wallet_suggestions_dismiss(req: DismissRequest):
    """Not their wallet (an exchange deposit, a friend): hide it for good."""
    key = req.trader_key.strip()
    if not key:
        raise HTTPException(400, "trader_key is required")
    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO wallet_dismissed (trader_key, ts) VALUES (?, ?)",
            (key, int(time.time())),
        )
    return {"ok": True, "trader_key": key}


_TOKEN_COLS = """t.chain, t.chain_tag, t.token_key, t.symbol, t.name,
                 t.last_mcap_usd, t.fdv_usd, t.mcap_as_of, t.n_events"""


@app.get("/api/token")
def token_lookup(q: str):
    """One token by contract address (or ticker), with every position ever
    taken in it — no filters, no top-N, hidden or not. Feeds the search
    box when the token isn't among the drawn bubbles."""
    key = q.strip()
    if not key:
        raise HTTPException(400, "empty query")
    colors = person_colors()
    with db_session() as conn:
        # Address first (EVM keys are stored lower-case), then ticker; the
        # busiest match wins when a ticker is reused across chains.
        tok = conn.execute(
            f"""SELECT {_TOKEN_COLS} FROM tokens t
                 WHERE t.token_key IN (?, ?)
                 ORDER BY t.n_events DESC LIMIT 1""",
            (key, key.lower()),
        ).fetchone()
        if tok is None:
            tok = conn.execute(
                f"""SELECT {_TOKEN_COLS} FROM tokens t
                     WHERE LOWER(t.symbol) = LOWER(?) OR LOWER(t.token_key) = LOWER(?)
                     ORDER BY t.n_events DESC LIMIT 1""",
                (key, f"sym:{key}"),
            ).fetchone()
        if tok is None:
            raise HTTPException(404, f"no token matches {key!r}")

        tkey = (tok["chain"], tok["token_key"])
        st = conn.execute(
            """SELECT SUM(status = 'HOLDING') AS n_holding,
                      COUNT(*)                AS n_positions,
                      MAX(last_seen)          AS last_action,
                      MIN(first_seen)         AS first_seen
                 FROM positions WHERE chain = ? AND token_key = ?""",
            tkey,
        ).fetchone()
        pos_rows = conn.execute(
            """SELECT chain, token_key, trader_key, person, trader_handle,
                      pct_supply, peak_pct, bought_pct, sold_pct, status, confidence,
                      invested_usd, realized_usd, pnl_usd, entry_mcap_usd,
                      avg_entry_mcap_usd, n_events, first_seen, last_seen
                 FROM positions
                WHERE chain = ? AND token_key = ?
                ORDER BY (status = 'HOLDING') DESC, COALESCE(pct_supply, 0) DESC""",
            tkey,
        ).fetchall()
        hidden = conn.execute(
            "SELECT 1 FROM token_blacklist WHERE chain = ? AND token_key = ?", tkey
        ).fetchone() is not None

    token = _token_node(tok, st if st and st["n_positions"] else None)
    token["first_seen"] = st["first_seen"] if st else None
    token["hidden"] = hidden
    nodes = [token]
    links = []
    for p in pos_rows:
        node = _person_node(p, colors, _size_pct(p))
        nodes.append(node)
        links.append({"source": node["id"], "target": node["token_id"], "status": p["status"]})
    return {"token": token, "nodes": nodes, "links": links}


_WALLET_RE = r"0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}"


@app.get("/api/holder")
def holder_lookup(trader_key: str, chain: str | None = None, token_key: str | None = None):
    """Everything about one tracked wallet: the position it was clicked on
    (`chain` + `token_key`), and every token it has ever taken a position
    in, current holdings first. On-chain verifications ride along."""
    import re as _re
    colors = person_colors()
    with db_session() as conn:
        pos_rows = conn.execute(
            """SELECT chain, token_key, trader_key, person, trader_handle,
                      pct_supply, peak_pct, bought_pct, sold_pct, status, confidence,
                      invested_usd, realized_usd, pnl_usd, entry_mcap_usd,
                      avg_entry_mcap_usd, n_events, first_seen, last_seen
                 FROM positions
                WHERE trader_key = ?
                ORDER BY (status = 'HOLDING') DESC, last_seen DESC""",
            (trader_key,),
        ).fetchall()
        if not pos_rows:
            raise HTTPException(404, "no positions for this trader")
        keys = {(p["chain"], p["token_key"]) for p in pos_rows}
        toks = {}
        stats = {}
        for c, k in keys:
            t = conn.execute(f"SELECT {_TOKEN_COLS} FROM tokens t WHERE t.chain = ? AND t.token_key = ?", (c, k)).fetchone()
            if t is not None:
                toks[(c, k)] = t
            stats[(c, k)] = conn.execute(
                """SELECT SUM(status = 'HOLDING') AS n_holding, COUNT(*) AS n_positions,
                          MAX(last_seen) AS last_action
                     FROM positions WHERE chain = ? AND token_key = ?""",
                (c, k),
            ).fetchone()
        verified = {
            (r["chain"], r["token_key"]): {"pct": r["pct"], "ts": r["ts"]}
            for r in conn.execute(
                "SELECT chain, token_key, pct, ts FROM verifications WHERE trader_key = ?",
                (trader_key,),
            )
        }

    entries = []
    for p in pos_rows:
        k = (p["chain"], p["token_key"])
        t = toks.get(k)
        entry = _person_node(p, colors, _size_pct(p))
        entry["token"] = _token_node(t, stats.get(k)) if t is not None else {
            "id": f"token:{k[0]}:{k[1]}", "kind": "token", "symbol": str(k[1]).replace("sym:", ""),
            "chain": k[0], "chain_tag": None, "token_key": k[1], "resolved": not str(k[1]).startswith("sym:"),
            "mcap_usd": None, "fdv_usd": None, "n_holders": 0, "n_positions": 0, "last_action": None, "dead": True,
        }
        entry["verified"] = verified.get(k)
        entries.append(entry)

    focus = next((e for e in entries if e["token"]["chain"] == chain and str(e["token"]["token_key"]) == str(token_key)), None)
    first = pos_rows[0]
    return {
        "trader_key": trader_key,
        "person": first["person"],
        "handle": first["trader_handle"],
        "color": colors.get(first["person"]),
        "is_wallet": bool(_re.fullmatch(_WALLET_RE, trader_key)),
        "focus": focus,
        "positions": entries,
        "n_holding": sum(1 for e in entries if e["status"] == "HOLDING"),
        "n_sold": sum(1 for e in entries if e["status"] != "HOLDING"),
    }


@app.get("/api/chains")
def chains_list():
    """Every supported chain, plus any tag in the data the registry doesn't
    know, with how many tokens sit on it — feeds the Chain filter. Alias
    tags (ROBINHOOD vs RH) are folded into one entry."""
    with db_session() as conn:
        rows = conn.execute(
            """SELECT t.chain, t.chain_tag, COUNT(*) AS n_tokens,
                      SUM(EXISTS (SELECT 1 FROM positions p
                                   WHERE p.chain = t.chain AND p.token_key = t.token_key
                                     AND p.status = 'HOLDING')) AS n_live
                 FROM tokens t
                GROUP BY t.chain, t.chain_tag"""
        ).fetchall()
    counts: dict[str, dict] = {}
    for r in rows:
        tag = chains_mod.canonical_tag(r["chain_tag"]) or (
            "SOL" if r["chain"] == "solana" else None)
        if not tag:
            continue  # untagged EVM rows can't be told apart by chain
        c = counts.setdefault(tag, {"n_tokens": 0, "n_live": 0})
        c["n_tokens"] += r["n_tokens"]
        c["n_live"] += r["n_live"] or 0
    out = [
        {"tag": c.tag, "name": c.name, "family": c.family,
         **counts.pop(c.tag, {"n_tokens": 0, "n_live": 0})}
        for c in chains_mod.CHAINS
    ]
    for tag, n in sorted(counts.items()):
        out.append({"tag": tag, "name": tag,
                    "family": chains_mod.chain_from_tag(tag) or "evm", **n})
    return {"chains": out}


@app.get("/api/persons")
def persons_list():
    """Distinct drawable people with position counts — feeds the Users filter."""
    with db_session() as conn:
        rows = conn.execute(
            """SELECT person,
                      COUNT(*)                AS n_positions,
                      SUM(status = 'HOLDING') AS n_holding,
                      MAX(last_seen)          AS last_seen
                 FROM positions
                WHERE person IS NOT NULL AND person != ''
                GROUP BY person
                ORDER BY n_holding DESC, n_positions DESC"""
        ).fetchall()
    return {"persons": [dict(r) for r in rows]}


@app.get("/api/traders")
def traders(q: str = "", limit: int = 100):
    """Distinct trader identities seen in events, with their current person
    assignment (from a merge or from people.yaml). `q` filters by substring
    over key, handle, and person."""
    like = f"%{q.strip()}%" if q.strip() else None
    with db_session() as conn:
        rows = conn.execute(
            """SELECT e.trader_key,
                      MAX(e.trader_handle)                    AS handle,
                      GROUP_CONCAT(DISTINCT e.source)         AS sources,
                      COUNT(*)                                AS n_events,
                      COUNT(DISTINCT e.chain || ':' || e.token_key) AS n_tokens,
                      MAX(e.ts)                               AS last_seen,
                      pm.person                               AS mapped_person
                 FROM events e
                 LEFT JOIN person_map pm ON pm.trader_key = e.trader_key
                GROUP BY e.trader_key
                ORDER BY n_events DESC"""
        ).fetchall()

        from .config import PersonResolver
        resolver = PersonResolver(conn=conn)

        out = []
        for r in rows:
            person = r["mapped_person"] or resolver.resolve(r["trader_key"])
            item = {
                "trader_key": r["trader_key"],
                "handle": r["handle"],
                "sources": (r["sources"] or "").split(","),
                "n_events": r["n_events"],
                "n_tokens": r["n_tokens"],
                "last_seen": r["last_seen"],
                "person": person,
            }
            if like:
                hay = " ".join(
                    filter(None, [r["trader_key"], r["handle"], person])
                ).lower()
                if q.strip().lower() not in hay:
                    continue
            out.append(item)
        return {"traders": out[:limit], "total": len(out)}


class MergeRequest(BaseModel):
    person: str
    keys: list[str]
    color: str | None = None


@app.post("/api/merge")
def merge(req: MergeRequest):
    """Assign 1+ trader keys to one person. Keys already mapped elsewhere are
    reassigned. Positions are rebuilt immediately."""
    person = req.person.strip()
    keys = [k.strip() for k in req.keys if k.strip()]
    if not person:
        raise HTTPException(400, "person name is required")
    if not keys:
        raise HTTPException(400, "at least one trader key is required")

    now = int(time.time())
    with db_session() as conn:
        for key in keys:
            conn.execute(
                """INSERT INTO person_map (trader_key, person, color, updated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(trader_key)
                   DO UPDATE SET person=excluded.person,
                                 color=COALESCE(excluded.color, person_map.color),
                                 updated_at=excluded.updated_at""",
                (key, person, req.color, now),
            )
    summary = positions_mod.run()
    return {"ok": True, "person": person, "keys": keys, "positions": summary["positions"]}


class UnmergeRequest(BaseModel):
    keys: list[str]


@app.post("/api/unmerge")
def unmerge(req: UnmergeRequest):
    """Remove keys from their person; they fall back to standalone identities
    (or to a people.yaml match, if one exists)."""
    keys = [k.strip() for k in req.keys if k.strip()]
    if not keys:
        raise HTTPException(400, "at least one trader key is required")
    with db_session() as conn:
        for key in keys:
            conn.execute("DELETE FROM person_map WHERE trader_key = ?", (key,))
    summary = positions_mod.run()
    return {"ok": True, "keys": keys, "positions": summary["positions"]}


@app.get("/api/people")
def people_list():
    """Current merge groups (person_map only — yaml seeds aren't editable here)."""
    with db_session() as conn:
        rows = conn.execute(
            """SELECT person, GROUP_CONCAT(trader_key) AS keys, MAX(color) AS color
                 FROM person_map GROUP BY person ORDER BY person"""
        ).fetchall()
    return {
        "people": [
            {"person": r["person"], "keys": (r["keys"] or "").split(","), "color": r["color"]}
            for r in rows
        ]
    }


class BlacklistRequest(BaseModel):
    chain: str
    token_key: str


@app.post("/api/blacklist")
def blacklist_add(req: BlacklistRequest):
    """Hide a token from the graph and feed until restored."""
    with db_session() as conn:
        tok = conn.execute(
            "SELECT symbol FROM tokens WHERE chain = ? AND token_key = ?",
            (req.chain, req.token_key),
        ).fetchone()
        conn.execute(
            """INSERT INTO token_blacklist (chain, token_key, symbol, ts)
               VALUES (?,?,?,?)
               ON CONFLICT(chain, token_key) DO UPDATE SET ts=excluded.ts""",
            (req.chain, req.token_key, tok["symbol"] if tok else None, int(time.time())),
        )
    return {"ok": True, "symbol": tok["symbol"] if tok else None}


@app.post("/api/blacklist/remove")
def blacklist_remove(req: BlacklistRequest):
    with db_session() as conn:
        n = conn.execute(
            "DELETE FROM token_blacklist WHERE chain = ? AND token_key = ?",
            (req.chain, req.token_key),
        ).rowcount
    return {"ok": True, "removed": n}


@app.get("/api/blacklist")
def blacklist_list():
    with db_session() as conn:
        rows = conn.execute(
            """SELECT b.chain, b.token_key,
                      COALESCE(t.symbol, b.symbol) AS symbol, b.ts
                 FROM token_blacklist b
                 LEFT JOIN tokens t
                   ON t.chain = b.chain AND t.token_key = b.token_key
                ORDER BY b.ts DESC"""
        ).fetchall()
    return {"tokens": [dict(r) for r in rows]}


class VerifyRequest(BaseModel):
    chain: str
    token_key: str


# In-process progress for the running holder verification (single token or
# the whole drawer), polled by the page's bar. done/total count tokens;
# wallets_done/wallets_total count wallets within the current token.
VERIFY_STATE = {
    "active": False, "done": 0, "total": 0, "symbol": "",
    "wallets_done": 0, "wallets_total": 0,
}


def _wallet_progress(done, total):
    VERIFY_STATE["wallets_done"], VERIFY_STATE["wallets_total"] = done, total


def _verify_token(chain: str, token_key: str, *, rebuild: bool = True) -> dict:
    """Check every tracked holder's REAL share of one token against the
    chain and store the fresh numbers. Raises HTTPException on a problem
    that applies to the whole token (unknown, no address, RPC down)."""
    import re as _re
    from .verify import verify_holdings

    with db_session() as conn:
        tok = conn.execute(
            "SELECT chain_tag, symbol FROM tokens WHERE chain = ? AND token_key = ?",
            (chain, token_key),
        ).fetchone()
        if tok is None:
            raise HTTPException(404, "unknown token")
        if str(token_key).startswith("sym:"):
            raise HTTPException(400, "no contract address known for this token")

        wallets = [
            r["trader_key"]
            for r in conn.execute(
                """SELECT DISTINCT trader_key FROM positions
                    WHERE chain = ? AND token_key = ?""",
                (chain, token_key),
            )
            if _re.fullmatch(r"0x[a-fA-F0-9]{40}", r["trader_key"])
            or _re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", r["trader_key"])
        ]
    if not wallets:
        raise HTTPException(400, "no full wallet addresses to check for this token")

    VERIFY_STATE.update(symbol=tok["symbol"] or "", wallets_done=0, wallets_total=len(wallets))
    checks, fatal = verify_holdings(
        chain, tok["chain_tag"], token_key, wallets, progress=_wallet_progress)
    if fatal:
        raise HTTPException(502, fatal)

    now = int(time.time())
    ok = 0
    with db_session() as conn:
        for c in checks:
            if c.pct is None:
                continue
            ok += 1
            conn.execute(
                """INSERT INTO verifications (chain, token_key, trader_key, pct, balance, ts)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(chain, token_key, trader_key)
                   DO UPDATE SET pct=excluded.pct, balance=excluded.balance, ts=excluded.ts""",
                (chain, token_key, c.trader_key, c.pct, c.balance, now),
            )
    if ok and rebuild:
        positions_mod.run()

    return {
        "ok": True,
        "symbol": tok["symbol"],
        "checked": len(checks),
        "verified": ok,
        "results": [
            {"trader_key": c.trader_key, "pct": c.pct, "error": c.error}
            for c in checks
        ],
    }


@app.post("/api/verify")
def verify(req: VerifyRequest):
    """Check every tracked holder's REAL share of this token against the
    chain, via a public RPC. Fresh numbers override the alert-derived ones
    (until a newer trade lands), and positions rebuild immediately."""
    if VERIFY_STATE["active"]:
        raise HTTPException(409, "a holder verification is already running")
    VERIFY_STATE.update(active=True, done=0, total=1, symbol="",
                        wallets_done=0, wallets_total=0)
    try:
        return _verify_token(req.chain, req.token_key)
    finally:
        VERIFY_STATE.update(active=False)


class VerifyWalletRequest(BaseModel):
    trader_key: str
    tokens: list[dict]   # [{chain, token_key}, ...] — address-keyed only


@app.post("/api/verify_wallet")
def verify_wallet(req: VerifyWalletRequest):
    """One wallet's real share of each given token, straight from the
    chain. Per-token problems (unknown token, RPC down) are reported in
    the results, not fatal. Sync route so the RPC work happens off the
    event loop; positions are rebuilt once at the end."""
    import re as _re
    from .verify import verify_holdings

    wallet = req.trader_key.strip()
    if not _re.fullmatch(_WALLET_RE, wallet):
        raise HTTPException(400, "not a full wallet address — nothing to check on-chain")
    wanted = list(dict.fromkeys(
        (t.get("chain"), str(t.get("token_key")))
        for t in req.tokens
        if t.get("chain") and t.get("token_key") and not str(t.get("token_key")).startswith("sym:")
    ))
    if not wanted:
        raise HTTPException(400, "no address-keyed tokens to check")
    if VERIFY_STATE["active"]:
        raise HTTPException(409, "a verification is already running")

    VERIFY_STATE.update(active=True, done=0, total=len(wanted), symbol="",
                        wallets_done=0, wallets_total=1)
    results = []
    ok = 0
    now = int(time.time())
    try:
        for i, (chain, key) in enumerate(wanted):
            VERIFY_STATE.update(done=i, wallets_done=0, wallets_total=1)
            with db_session() as conn:
                tok = conn.execute(
                    "SELECT chain_tag, symbol FROM tokens WHERE chain = ? AND token_key = ?",
                    (chain, key),
                ).fetchone()
            base = {"chain": chain, "token_key": key,
                    "symbol": tok["symbol"] if tok else None, "pct": None, "error": None}
            if tok is None:
                results.append({**base, "error": "unknown token"})
                continue
            VERIFY_STATE["symbol"] = tok["symbol"] or ""
            checks, fatal = verify_holdings(
                chain, tok["chain_tag"], key, [wallet], progress=_wallet_progress)
            c = checks[0] if checks else None
            if fatal or c is None or c.pct is None:
                results.append({**base, "error": fatal or (c.error if c else "no result")})
                continue
            ok += 1
            with db_session() as conn:
                conn.execute(
                    """INSERT INTO verifications (chain, token_key, trader_key, pct, balance, ts)
                       VALUES (?,?,?,?,?,?)
                       ON CONFLICT(chain, token_key, trader_key)
                       DO UPDATE SET pct=excluded.pct, balance=excluded.balance, ts=excluded.ts""",
                    (chain, key, wallet, c.pct, c.balance, now),
                )
            results.append({**base, "pct": c.pct, "balance": c.balance})
        VERIFY_STATE["done"] = len(wanted)
    finally:
        VERIFY_STATE.update(active=False, done=0, total=0, symbol="",
                            wallets_done=0, wallets_total=0)
    if ok:
        positions_mod.run()
    return {"ok": True, "checked": len(wanted), "verified": ok, "results": results}


class VerifyAllRequest(BaseModel):
    tokens: list[dict]   # [{chain, token_key}, ...] — address-keyed only


@app.get("/api/verify/status")
def verify_status():
    return VERIFY_STATE


@app.post("/api/verify/all")
def verify_all(req: VerifyAllRequest):
    """Verify every holder of every given token on-chain, one token after
    another, then rebuild positions once at the end. Per-token failures
    (no wallets, RPC down) are reported, not fatal. Sync route so the RPC
    calls run in a worker thread and the status endpoint stays live."""
    if VERIFY_STATE["active"]:
        raise HTTPException(409, "a holder verification is already running")

    wanted = [
        (t.get("chain"), str(t.get("token_key")))
        for t in req.tokens
        if t.get("chain") and t.get("token_key")
        and not str(t.get("token_key")).startswith("sym:")
    ]
    if not wanted:
        raise HTTPException(400, "no address-keyed tokens to verify")

    VERIFY_STATE.update(active=True, done=0, total=len(wanted), symbol="",
                        wallets_done=0, wallets_total=0)
    results, verified_any = [], False
    try:
        for i, (chain, key) in enumerate(wanted):
            try:
                out = _verify_token(chain, key, rebuild=False)
                verified_any = verified_any or out["verified"] > 0
                results.append({
                    "chain": chain, "token_key": key, "symbol": out["symbol"],
                    "checked": out["checked"], "verified": out["verified"],
                })
            except HTTPException as e:
                results.append({
                    "chain": chain, "token_key": key, "symbol": None,
                    "checked": 0, "verified": 0, "error": str(e.detail),
                })
            VERIFY_STATE["done"] = i + 1
    finally:
        VERIFY_STATE.update(active=False)

    if verified_any:
        positions_mod.run()

    return {
        "ok": True,
        "requested": len(wanted),
        "tokens_verified": sum(1 for r in results if r["verified"]),
        "wallets_checked": sum(r["checked"] for r in results),
        "wallets_verified": sum(r["verified"] for r in results),
        "failed": sum(1 for r in results if r.get("error")),
        "results": results,
    }


# Set by hotgraph.run so API-triggered backfills reuse the one live Telethon
# client. Opening a second client on the same session file here would trigger
# AUTH_KEY_DUPLICATED — never do that. Stays None under standalone uvicorn.
tg_client = None


@app.post("/api/logout")
async def logout():
    """Sign this HotGraph device out of Telegram and destroy its session.

    Telethon's log_out() revokes the authorization server-side, disconnects,
    and deletes data/hotgraph.session. The disconnect ends hotgraph.run's
    listener, which takes the server down with it (exit code 3) — start.py
    sees that and asks for a fresh login. Alerts and positions in the DB are
    untouched; only the Telegram login goes.
    """
    import asyncio

    if tg_client is None:
        raise HTTPException(
            400,
            "no live Telegram session in this process — start HotGraph with "
            "python start.py (or python -m hotgraph.run) to sign out",
        )
    if REBUILD_STATE["active"]:
        raise HTTPException(409, "a rebuild is running — wait for it to finish")

    async def _later():
        await asyncio.sleep(0.3)  # let this response reach the page first
        await tg_client.log_out()

    asyncio.create_task(_later())
    return {"ok": True}

# In-process progress for the running rebuild, polled by /api/rebuild/status.
# fetch: done = messages scanned on Telegram (total unknown -> indeterminate);
# parse: done/total = messages parsed; positions: quick final phase.
REBUILD_STATE = {"active": False, "phase": None, "done": 0, "total": None, "detail": ""}


class RebuildRequest(BaseModel):
    days: float | None = None   # None or 0 = all captured history


@app.get("/api/rebuild/status")
def rebuild_status():
    return REBUILD_STATE


class McapRequest(BaseModel):
    tokens: list[dict]   # [{chain, token_key}, ...] — address-keyed only


# In-process progress for the running mcap refresh, polled by the page's bar.
MCAP_STATE = {"active": False, "done": 0, "total": 0}


@app.get("/api/mcaps/status")
def mcaps_status():
    return MCAP_STATE


@app.post("/api/mcaps")
def refresh_mcaps(req: McapRequest):
    """Fetch current market caps for the given tokens from DexScreener and
    store them (mcap_checks + tokens), freshest-wins across rebuilds.
    Sync route: FastAPI runs it in a worker thread, so the retry backoff and
    pacing sleeps inside fetch_mcaps never block the event loop (and the
    status endpoint stays answerable while this runs)."""
    from .mcap import fetch_mcaps

    if MCAP_STATE["active"]:
        raise HTTPException(409, "a market-cap refresh is already running")

    wanted = [
        (t.get("chain"), str(t.get("token_key")))
        for t in req.tokens
        if t.get("chain") and t.get("token_key")
        and not str(t.get("token_key")).startswith("sym:")
    ]
    if not wanted:
        raise HTTPException(400, "no address-keyed tokens to refresh")

    MCAP_STATE.update(active=True, done=0, total=len(wanted))
    try:
        def prog(done, total):
            MCAP_STATE["done"], MCAP_STATE["total"] = done, total

        caps, failed = fetch_mcaps([k for _, k in wanted], progress=prog)
    finally:
        MCAP_STATE.update(active=False)

    now = int(time.time())
    updated = 0
    with db_session() as conn:
        for chain, key in wanted:
            hit = caps.get(key)
            if hit is None:
                continue
            cap, fdv = hit
            updated += 1
            conn.execute(
                """INSERT INTO mcap_checks (chain, token_key, mcap_usd, fdv_usd, ts)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(chain, token_key)
                   DO UPDATE SET mcap_usd=excluded.mcap_usd, fdv_usd=excluded.fdv_usd,
                                 ts=excluded.ts""",
                (chain, key, cap, fdv, now),
            )
            conn.execute(
                "UPDATE tokens SET last_mcap_usd=?, fdv_usd=?, mcap_as_of=? WHERE chain=? AND token_key=?",
                (cap, fdv, now, chain, key),
            )

    return {
        "ok": True,
        "requested": len(wanted),
        "updated": updated,
        "unknown": len(wanted) - updated - len(failed),
        "failed": len(failed),
    }


@app.post("/api/rebuild")
async def rebuild(req: RebuildRequest | None = None):
    """Rebuild events + positions, optionally bounded to the last N days.

    With a timeframe and a connected Telegram client, first backfills any
    alerts in that window that were never captured (dedup makes this cheap),
    then re-parses just that window so the whole graph reflects it.
    """
    import asyncio
    from . import ingest as ingest_mod
    from .config import load_sources

    if REBUILD_STATE["active"]:
        raise HTTPException(409, "a rebuild is already running")

    days = req.days if req and req.days and req.days > 0 else None
    since_ts = time.time() - days * 86400 if days else None

    REBUILD_STATE.update(active=True, phase="fetch", done=0, total=None, detail="")
    try:
        fetched = scanned = 0
        if tg_client is not None and since_ts is not None:
            from .capture import backfill_one
            with db_session() as conn:
                for src in (s for s in load_sources() if s.enabled):
                    REBUILD_STATE["detail"] = src.id

                    def prog(seen, _new, base=scanned):
                        REBUILD_STATE["done"] = base + seen

                    try:
                        new, seen = await backfill_one(
                            tg_client, conn, src, None, since_ts, progress=prog
                        )
                    except Exception:
                        continue
                    fetched += new
                    scanned += seen

        REBUILD_STATE.update(phase="parse", done=0, total=None, detail="")

        def iprog(done, total):
            REBUILD_STATE["done"] = done
            REBUILD_STATE["total"] = total

        # Threads so the event loop stays free to answer the progress polls
        # (and live Telegram updates) while SQLite churns.
        await asyncio.to_thread(ingest_mod.run, None, 0, since_ts, iprog)
        REBUILD_STATE.update(phase="positions", done=0, total=None)
        summary = await asyncio.to_thread(positions_mod.run)
        notify_change()  # other open tabs redraw too
        return {"ok": True, "fetched": fetched, "days": days, **summary}
    finally:
        REBUILD_STATE.update(active=False, phase=None, done=0, total=None, detail="")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.middleware("http")
async def _no_stale_frontend(request, call_next):
    """The page and its script are edited in place. Without this a normal
    reload (F5) revalidates only index.html and keeps app.js from the
    heuristic cache — new buttons appear with no handlers behind them.
    ETags make the forced revalidation a cheap 304."""
    resp = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
