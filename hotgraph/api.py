"""FastAPI app: serves the graph JSON and the static page.

    uvicorn hotgraph.api:app --reload    ->  http://localhost:8000
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import positions as positions_mod
from .config import person_colors
from .db import counts, session as db_session
from .paths import WEB_DIR

app = FastAPI(title="HotGraph")


@app.get("/api/graph")
def graph(
    chain: str | None = None,
    include_sold: bool = True,
    min_mcap: float = 0.0,
    min_pct: float = 0.0,
    top: int = 150,
    sort: str = "mcap",       # 'mcap' | 'latest' | 'holders'
    since_hours: float = 0,   # 0 = no window; else only tokens with action in it
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

        tok_rows = conn.execute(
            """SELECT t.chain, t.chain_tag, t.token_key, t.symbol, t.name,
                      t.last_mcap_usd, t.mcap_as_of, t.n_events
                 FROM tokens t
                WHERE (? IS NULL OR t.chain = ?)
                  AND COALESCE(t.last_mcap_usd, 0) >= ?""",
            (chain, chain, min_mcap),
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

        # Fully-exited tokens (nobody tracked holds anymore) are not drawn at
        # all. Sold positions on still-held tokens keep their grey bubbles.
        # A time window keeps only tokens someone traded within it — their
        # full current holder picture stays visible for context.
        tok_rows = sorted(
            (t for t in tok_rows if _alive(t) and _in_window(t)),
            key=lambda t: -_metric(t),
        )

        # 31 days of alerts covers ~2000 tokens — far more than a readable
        # graph. Keep the top-N (0 = no cap); the rest stay queryable, just
        # not drawn.
        if top and top > 0:
            tok_rows = tok_rows[:top]
        allowed = {(t["chain"], t["token_key"]) for t in tok_rows}

        pos_rows = conn.execute(
            """SELECT chain, token_key, trader_key, person, trader_handle,
                      pct_supply, peak_pct, bought_pct, sold_pct, status, confidence,
                      invested_usd, realized_usd, pnl_usd, entry_mcap_usd,
                      n_events, first_seen, last_seen
                 FROM positions
                WHERE (? IS NULL OR chain = ?)""",
            (chain, chain),
        ).fetchall()

        stats = counts(conn)

    nodes: list[dict] = []
    links: list[dict] = []
    live_tokens: set[tuple[str, str]] = set()

    for p in pos_rows:
        if (p["chain"], p["token_key"]) not in allowed:
            continue
        if not include_sold and p["status"] == "SOLD":
            continue
        # Sold bubbles size off their peak so they don't collapse to nothing.
        size_pct = p["peak_pct"] if p["status"] == "SOLD" else p["pct_supply"]
        size_pct = size_pct or 0.0
        if size_pct < min_pct:
            continue

        tkey = (p["chain"], p["token_key"])
        token_id = f"token:{p['chain']}:{p['token_key']}"
        node_id = f"pos:{p['chain']}:{p['token_key']}:{p['trader_key']}"

        nodes.append({
            "id": node_id,
            "kind": "person",
            "token_id": token_id,
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
            "n_events": p["n_events"],
            "first_seen": p["first_seen"],
            "last_seen": p["last_seen"],
        })
        links.append({"source": node_id, "target": token_id, "status": p["status"]})
        live_tokens.add(tkey)

    for t in tok_rows:
        tkey = (t["chain"], t["token_key"])
        if tkey not in live_tokens:
            continue  # a token with no drawable positions isn't worth a bubble
        st = tstats.get(tkey)
        n_holding = st["n_holding"] if st else 0
        nodes.append({
            "id": f"token:{t['chain']}:{t['token_key']}",
            "kind": "token",
            "symbol": t["symbol"] or str(t["token_key"]).replace("sym:", ""),
            "name": t["name"],
            "chain": t["chain"],
            "chain_tag": t["chain_tag"],
            "token_key": t["token_key"],
            "value": t["last_mcap_usd"] or 0.0,
            "mcap_usd": t["last_mcap_usd"],
            "mcap_as_of": t["mcap_as_of"],
            "resolved": not str(t["token_key"]).startswith("sym:"),
            "n_events": t["n_events"],
            "n_holders": n_holding,
            "n_positions": st["n_positions"] if st else 0,
            "last_action": st["last_action"] if st else None,
            # Everyone we track has exited — the token is history, not book.
            "dead": n_holding == 0,
        })

    return JSONResponse({
        "nodes": nodes,
        "links": links,
        "stats": stats,
        "generated_at": int(time.time()),
    })


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
        if kind in ("buys", "sells", "swaps", "all"):
            side_clause = {
                "buys": "e.side = 'BUY'",
                "sells": "e.side = 'SELL'",
            }.get(kind, "1=1")
            for r in conn.execute(
                f"""SELECT e.ts, e.side, e.is_exit, e.token_symbol, e.token_key,
                           e.chain_tag, e.trader_handle, e.trader_key,
                           e.pct_supply, e.amount_usd, e.mcap_usd, e.source
                      FROM events e
                     WHERE {side_clause}
                     ORDER BY e.ts DESC LIMIT ?""",
                (limit,),
            ):
                items.append({
                    "ts": r["ts"],
                    "type": r["side"],
                    "is_exit": bool(r["is_exit"]),
                    "symbol": r["token_symbol"] or str(r["token_key"]).replace("sym:", ""),
                    "chain_tag": r["chain_tag"],
                    "who": r["trader_handle"] or r["trader_key"],
                    "pct_supply": r["pct_supply"],
                    "amount_usd": r["amount_usd"],
                    "mcap_usd": r["mcap_usd"],
                    "source": r["source"],
                })

        if kind in ("other", "all"):
            # Captured messages that produced no trade event. Leading-slash
            # messages are your own bot commands, not notifications.
            for r in conn.execute(
                """SELECT r.ts, r.source, r.text
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


class VerifyRequest(BaseModel):
    chain: str
    token_key: str


@app.post("/api/verify")
def verify(req: VerifyRequest):
    """Check every tracked holder's REAL share of this token against the
    chain, via a public RPC. Fresh numbers override the alert-derived ones
    (until a newer trade lands), and positions rebuild immediately."""
    import re as _re
    from .verify import verify_holdings

    with db_session() as conn:
        tok = conn.execute(
            "SELECT chain_tag, symbol FROM tokens WHERE chain = ? AND token_key = ?",
            (req.chain, req.token_key),
        ).fetchone()
        if tok is None:
            raise HTTPException(404, "unknown token")
        if str(req.token_key).startswith("sym:"):
            raise HTTPException(400, "no contract address known for this token")

        wallets = [
            r["trader_key"]
            for r in conn.execute(
                """SELECT DISTINCT trader_key FROM positions
                    WHERE chain = ? AND token_key = ?""",
                (req.chain, req.token_key),
            )
            if _re.fullmatch(r"0x[a-fA-F0-9]{40}", r["trader_key"])
            or _re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", r["trader_key"])
        ]
    if not wallets:
        raise HTTPException(400, "no full wallet addresses to check for this token")

    checks, fatal = verify_holdings(req.chain, tok["chain_tag"], req.token_key, wallets)
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
                (req.chain, req.token_key, c.trader_key, c.pct, c.balance, now),
            )
    if ok:
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


@app.post("/api/rebuild")
def rebuild():
    """Re-parse everything and rebuild positions (after a parser fix)."""
    from . import ingest as ingest_mod
    ingest_mod.run()
    summary = positions_mod.run()
    return {"ok": True, **summary}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
