"""events -> positions. Rebuilt from scratch every run.

    python -m hotgraph.positions
    python -m hotgraph.positions --explain loganlim_x

How a position is computed
--------------------------
The alerts report the share of supply that ONE trade moved ("0.07%", "3.16%"),
not a running balance. Since total supply is fixed, those shares accumulate:

    pct_supply = sum(pct on buys) - sum(pct on sells)

clamped at zero, because a sell we saw whose matching buy predates our history
would otherwise drive the total negative.

An explicit "Exit (TICKER)" line beats the arithmetic outright — it is the bot
stating the position is fully closed, so status becomes SOLD regardless of what
the percentages sum to.

confidence
----------
  high  every event carried a percentage and the maths is self-consistent
  low   some event lacked a percentage, the running total went negative
        (a sell with no matching buy in our window), or the token is keyed by
        ticker rather than a real mint address
"""

from __future__ import annotations

import argparse
import time

from .config import PersonResolver, load_mode, load_people
from .db import session as db_session, set_meta

DUST_PCT = 0.02  # below this a position reads as closed rather than a dust remainder

HOLDING, SOLD, UNKNOWN = "HOLDING", "SOLD", "UNKNOWN"


def _rebuild_tokens(conn) -> None:
    """Latest-known symbol/name and most recent stated mcap per token."""
    conn.execute("DELETE FROM tokens")
    conn.execute(
        """
        INSERT INTO tokens (chain, token_key, chain_tag, symbol, name, last_mcap_usd,
                            mcap_as_of, n_events, first_seen, last_seen)
        SELECT
            e.chain,
            e.token_key,
            (SELECT chain_tag FROM events s
              WHERE s.chain = e.chain AND s.token_key = e.token_key
                AND s.chain_tag IS NOT NULL
              ORDER BY s.ts DESC LIMIT 1),
            (SELECT token_symbol FROM events s
              WHERE s.chain = e.chain AND s.token_key = e.token_key
                AND s.token_symbol IS NOT NULL
              ORDER BY s.ts DESC LIMIT 1),
            (SELECT token_name FROM events s
              WHERE s.chain = e.chain AND s.token_key = e.token_key
                AND s.token_name IS NOT NULL
              ORDER BY s.ts DESC LIMIT 1),
            (SELECT mcap_usd FROM events s
              WHERE s.chain = e.chain AND s.token_key = e.token_key
                AND s.mcap_usd IS NOT NULL
              ORDER BY s.ts DESC LIMIT 1),
            (SELECT ts FROM events s
              WHERE s.chain = e.chain AND s.token_key = e.token_key
                AND s.mcap_usd IS NOT NULL
              ORDER BY s.ts DESC LIMIT 1),
            COUNT(*), MIN(e.ts), MAX(e.ts)
        FROM events e
        GROUP BY e.chain, e.token_key
        """
    )
    # DexScreener-fetched caps (the drawer's "refresh mcaps" button) override
    # the alert-stated figure when fresher — otherwise every rebuild would
    # silently roll tokens back to their last-alert cap.
    conn.execute(
        """
        UPDATE tokens
           SET last_mcap_usd = (SELECT m.mcap_usd FROM mcap_checks m
                                 WHERE m.chain = tokens.chain
                                   AND m.token_key = tokens.token_key),
               fdv_usd       = (SELECT m.fdv_usd FROM mcap_checks m
                                 WHERE m.chain = tokens.chain
                                   AND m.token_key = tokens.token_key),
               mcap_as_of    = (SELECT m.ts FROM mcap_checks m
                                 WHERE m.chain = tokens.chain
                                   AND m.token_key = tokens.token_key)
         WHERE EXISTS (SELECT 1 FROM mcap_checks m
                        WHERE m.chain = tokens.chain
                          AND m.token_key = tokens.token_key
                          AND m.ts > COALESCE(tokens.mcap_as_of, 0))
        """
    )


def run() -> dict:
    people = load_people()
    mode = load_mode()

    with db_session() as conn:
        resolver = PersonResolver(people, conn=conn)

        # Which tokens were held BEFORE this rebuild — diffed afterwards to
        # detect "the last holder just sold out", which the page announces.
        prev_held = {
            (r["chain"], r["token_key"]): r["symbol"]
            for r in conn.execute(
                """SELECT p.chain, p.token_key, MAX(t.symbol) AS symbol
                     FROM positions p
                     LEFT JOIN tokens t
                       ON t.chain = p.chain AND t.token_key = p.token_key
                    WHERE p.status = 'HOLDING'
                    GROUP BY p.chain, p.token_key"""
            )
        }

        _rebuild_tokens(conn)
        conn.execute("DELETE FROM positions")

        # Ordered by ts only within each token: one person's events may arrive
        # under several trader_keys (handle via bot A, address via bots B/C),
        # so grouping by trader_key would destroy the temporal order the
        # running-balance math depends on.
        rows = conn.execute(
            """SELECT chain, token_key, trader_key, trader_handle, side, is_exit,
                      amount_usd, pct_supply, holds_pct, mcap_usd, pnl_usd,
                      tx_hash, ts
                 FROM events
                ORDER BY chain, token_key, ts ASC"""
        ).fetchall()

        def _is_address_key(k: str) -> bool:
            return k.startswith("0x") or k.startswith("trunc:") or len(k) >= 32

        # Alerts without a wallet link fall back to handle keys. When that
        # handle appears with exactly ONE wallet elsewhere in the data, its
        # handle-keyed events belong to that wallet's group; with several
        # wallets it stays separate (the UI merge can settle it).
        handle_wallets: dict[str, set] = {}
        for r in rows:
            h = (r["trader_handle"] or "").lower()
            k = r["trader_key"] or ""
            if h and _is_address_key(k) and not k.startswith("trunc:"):
                handle_wallets.setdefault(h, set()).add(k)
        alias = {h: next(iter(ws)) for h, ws in handle_wallets.items() if len(ws) == 1}

        acc: dict[tuple, dict] = {}
        seen_tx: set[tuple] = set()
        dup_window: dict[tuple, int] = {}
        for r in rows:
            tkey = r["trader_key"]
            canon = tkey if _is_address_key(tkey) else alias.get(tkey.lower(), tkey)
            person = resolver.resolve(canon) or resolver.resolve(tkey)
            if mode == "known_only" and person is None:
                continue

            # Merge all of one person's identities into a single position.
            who = person or canon
            key = (r["chain"], r["token_key"], who)

            # Cross-bot dedup: two bots reporting the same trade must not
            # count it twice. The tx hash is authoritative; without one, an
            # identical (side, pct) within 3 minutes is treated as the same
            # trade seen through a second bot.
            if r["tx_hash"]:
                tx_id = key + (r["side"], r["tx_hash"])
                if tx_id in seen_tx:
                    continue
                seen_tx.add(tx_id)
            elif r["pct_supply"] is not None:
                near_id = key + (r["side"], round(r["pct_supply"], 6))
                last = dup_window.get(near_id)
                if last is not None and abs(r["ts"] - last) <= 180:
                    continue
                dup_window[near_id] = r["ts"]

            st = acc.get(key)
            if st is None:
                st = acc[key] = {
                    "person": who if person else (r["trader_handle"] or r["trader_key"]),
                    "trader_key": r["trader_key"],
                    "trader_handle": r["trader_handle"],
                    "bought": 0.0,
                    "sold": 0.0,
                    "running": 0.0,
                    "peak": 0.0,
                    "invested": 0.0,
                    "realized": 0.0,
                    "pnl": None,
                    "entry_mcap": None,
                    # Buy-weighted average market cap: weight is the share of
                    # supply each buy took, so a big buy at $50K counts for
                    # more than a nibble at $5M. Falls back to a plain mean
                    # of buy mcaps when the alerts carried no supply %.
                    "mcap_w": 0.0,
                    "mcap_wsum": 0.0,
                    "mcap_n": 0,
                    "mcap_sum": 0.0,
                    "exited": False,
                    "n": 0,
                    "missing_pct": False,
                    "went_negative": False,
                    "stated": False,
                    "first": r["ts"],
                    "last": r["ts"],
                }

            st["n"] += 1
            st["last"] = r["ts"]
            st.setdefault("keys", set()).add(r["trader_key"])
            # Prefer a real handle for display over an address key.
            if r["trader_handle"]:
                if not st["trader_handle"]:
                    st["trader_handle"] = r["trader_handle"]
                if _is_address_key(str(st["person"])):
                    st["person"] = r["trader_handle"]

            # An earlier Exit closed the position, but buying again reopens it.
            if r["side"] == "BUY":
                st["exited"] = False

            pct = r["pct_supply"]
            if pct is None:
                st["missing_pct"] = True
            else:
                if r["side"] == "BUY":
                    st["bought"] += pct
                    st["running"] += pct
                else:
                    st["sold"] += pct
                    st["running"] -= pct
                if st["running"] < -DUST_PCT:
                    st["went_negative"] = True
                st["running"] = max(0.0, st["running"])
                st["peak"] = max(st["peak"], st["running"], pct)

            # "Holds 14.27M MM (1.52%)" — the bot's own statement of the total
            # position after this trade. Stated beats computed: it corrects any
            # drift from missed alerts or buys before our history window.
            if r["holds_pct"] is not None:
                st["running"] = r["holds_pct"]
                st["peak"] = max(st["peak"], r["holds_pct"])
                st["stated"] = True
                st["went_negative"] = False

            usd = r["amount_usd"]
            if usd is not None:
                if r["side"] == "BUY":
                    st["invested"] += usd
                else:
                    st["realized"] += usd

            if r["side"] == "BUY" and r["mcap_usd"]:
                if st["entry_mcap"] is None:
                    st["entry_mcap"] = r["mcap_usd"]
                st["mcap_n"] += 1
                st["mcap_sum"] += r["mcap_usd"]
                if pct:
                    st["mcap_w"] += pct
                    st["mcap_wsum"] += pct * r["mcap_usd"]

            if r["pnl_usd"] is not None:
                st["pnl"] = (st["pnl"] or 0.0) + r["pnl_usd"]

            if r["is_exit"]:
                # The bot said the position is closed. Trust it over the sums.
                st["exited"] = True
                st["running"] = 0.0

        symbol_keyed = {
            (row["chain"], row["token_key"])
            for row in conn.execute("SELECT chain, token_key FROM tokens")
            if str(row["token_key"]).startswith("sym:")
        }

        # On-chain verifications: the chain's own number for a wallet's share.
        # Applied per wallet when fresher than that group's last event —
        # a newer trade invalidates the snapshot.
        verif = {
            (r["chain"], r["token_key"], r["trader_key"]): r
            for r in conn.execute(
                "SELECT chain, token_key, trader_key, pct, ts FROM verifications"
            )
        }

        now_held: set[tuple] = set()
        for (chain, token_key, _who), st in acc.items():
            trader_key = st["trader_key"]  # representative key for the row

            vs = [
                verif[k] for key in st.get("keys", ())
                if (k := (chain, token_key, key)) in verif and verif[k]["ts"] >= st["last"]
            ]
            if vs and all(v["pct"] is not None for v in vs):
                # Chain truth wins over accumulated alerts.
                st["running"] = sum(v["pct"] for v in vs)
                st["peak"] = max(st["peak"], st["running"])
                st["stated"] = True
                st["went_negative"] = False
                st["exited"] = st["running"] <= DUST_PCT and st["exited"]

            if st["exited"] or st["running"] <= DUST_PCT:
                status = SOLD if (st["exited"] or st["bought"] > 0 or st["sold"] > 0) else UNKNOWN
            else:
                status = HOLDING
                now_held.add((chain, token_key))

            confidence = "high"
            if st["missing_pct"] or st["went_negative"] or (chain, token_key) in symbol_keyed:
                confidence = "low"
            if st["stated"]:
                # The bot told us the total outright — accumulation gaps and
                # weak token keys no longer make the number itself uncertain.
                confidence = "high"

            pnl = st["pnl"]
            if pnl is None and status == SOLD and st["invested"] and st["realized"]:
                pnl = st["realized"] - st["invested"]

            if st["mcap_w"] > 0:
                avg_entry = st["mcap_wsum"] / st["mcap_w"]
            elif st["mcap_n"]:
                avg_entry = st["mcap_sum"] / st["mcap_n"]
            else:
                avg_entry = None

            conn.execute(
                """INSERT INTO positions
                     (chain, token_key, trader_key, person, trader_handle,
                      pct_supply, peak_pct, bought_pct, sold_pct, status, confidence,
                      invested_usd, realized_usd, pnl_usd, entry_mcap_usd,
                      avg_entry_mcap_usd, n_events, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    chain, token_key, trader_key, st["person"], st["trader_handle"],
                    round(st["running"], 6), round(st["peak"], 6),
                    round(st["bought"], 6), round(st["sold"], 6),
                    status, confidence,
                    round(st["invested"], 2), round(st["realized"], 2),
                    round(pnl, 2) if pnl is not None else None,
                    st["entry_mcap"],
                    round(avg_entry, 2) if avg_entry is not None else None,
                    st["n"], st["first"], st["last"],
                ),
            )

        # Tokens whose last holder just sold out — recorded so the page can
        # announce the removal. A full-history rebuild that starts from empty
        # positions has an empty prev_held and records nothing spurious.
        for key, sym in prev_held.items():
            if key not in now_held:
                conn.execute(
                    "INSERT INTO eliminations (chain, token_key, symbol, ts) VALUES (?,?,?,?)",
                    (key[0], key[1], sym, int(time.time())),
                )

        # Monotonic rebuild stamp. The page's change-detection includes it, so
        # an update is never missed even when row counts happen to stay equal
        # (e.g. a new sell on an existing position).
        set_meta(conn, "positions_built_at", int(time.time() * 1000))

        summary = {
            "positions": conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
            "holding": conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='HOLDING'").fetchone()[0],
            "sold": conn.execute(
                "SELECT COUNT(*) FROM positions WHERE status='SOLD'").fetchone()[0],
            "low_conf": conn.execute(
                "SELECT COUNT(*) FROM positions WHERE confidence='low'").fetchone()[0],
            "tokens": conn.execute("SELECT COUNT(*) FROM tokens").fetchone()[0],
            "people": len(people),
            "mode": mode,
        }
    return summary


def explain(who: str) -> None:
    """Print every event behind a bubble. Accepts a person name from
    people.yaml, a handle, or a wallet address — all of a person's identities
    (handle via bot A, addresses via bots B/C) are merged into one trail."""
    arg = who.strip().lstrip("@")

    with db_session() as conn:
        resolver = PersonResolver(conn=conn)
        # The person this argument denotes: resolve it as a trader key, or
        # accept it verbatim as a configured person name.
        target = resolver.resolve(arg) or resolver.resolve(arg.lower()) or arg
        all_rows = conn.execute(
            """SELECT chain, token_key, token_symbol, trader_key, side, is_exit,
                      pct_supply, amount_usd, mcap_usd, tx_hash, ts
                 FROM events ORDER BY chain, token_key, ts ASC"""
        ).fetchall()

        def belongs(r) -> bool:
            tk = r["trader_key"] or ""
            if tk.lower() == arg.lower():
                return True
            return resolver.resolve(tk) == target

        rows = [r for r in all_rows if belongs(r)]
        if not rows:
            print(f"No events for '{who}'.")
            return

        keys = sorted({r["trader_key"] for r in rows})
        print(f"Person: {target}   identities: {', '.join(keys)}")

        current = None
        running = 0.0
        seen_tx: set[tuple] = set()
        for r in rows:
            key = (r["chain"], r["token_key"])
            if key != current:
                current, running = key, 0.0
                seen_tx.clear()
                sym = r["token_symbol"] or r["token_key"]
                print(f"\n=== {sym}  [{r['chain']}]  {r['token_key']} ===")
                print(f"{'date':<17} {'side':<5} {'pct':>8} {'running':>9} {'usd':>10}  note")

            # Same dedup as run(): a trade reported by two bots counts once.
            is_dup = False
            if r["tx_hash"]:
                tx_id = (r["side"], r["tx_hash"])
                is_dup = tx_id in seen_tx
                seen_tx.add(tx_id)

            pct = r["pct_supply"]
            if pct is not None and not is_dup:
                running += pct if r["side"] == "BUY" else -pct
                running = max(0.0, running)
            if r["is_exit"] and not is_dup:
                running = 0.0

            stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(r["ts"]))
            pct_s = f"{pct:.4f}" if pct is not None else "  -   "
            usd_s = f"{r['amount_usd']:.2f}" if r["amount_usd"] is not None else "-"
            if is_dup:
                note = "DUP - same tx via another bot, not counted"
            elif r["is_exit"]:
                note = "EXIT"
            else:
                note = "no pct in alert" if pct is None else ""
            print(f"{stamp:<17} {r['side']:<5} {pct_s:>8} {running:>9.4f} {usd_s:>10}  {note}")

        print("\nFinal positions:")
        for p in conn.execute(
            """SELECT COALESCE(t.symbol, p.token_key) AS sym,
                      p.pct_supply, p.peak_pct, p.status, p.confidence
                 FROM positions p
                 LEFT JOIN tokens t
                   ON t.chain = p.chain AND t.token_key = p.token_key
                WHERE p.person = ? OR LOWER(p.trader_key) = ?
                ORDER BY p.pct_supply DESC""",
            (target, arg.lower()),
        ):
            print(f"  {p['sym']:<14} {p['pct_supply']:>8.4f}%  peak {p['peak_pct']:>7.4f}%  "
                  f"{p['status']:<8} {p['confidence']}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--explain", metavar="TRADER", help="trace one trader's events")
    args = ap.parse_args()

    if args.explain:
        explain(args.explain)
        return

    s = run()
    if s["positions"] == 0:
        print("No positions built.")
        print(f"  mode={s['mode']}, people configured={s['people']}")
        print("  If mode is 'known_only', check the handles in config/people.yaml")
        print("  match what the bots print. Try: python -m hotgraph.ingest --show-unparsed 5")
        return

    print(f"tokens     {s['tokens']}")
    print(f"positions  {s['positions']}  ({s['holding']} holding, {s['sold']} sold)")
    print(f"low conf   {s['low_conf']}")
    print(f"mode       {s['mode']}")
    print("\nNext: uvicorn hotgraph.api:app --reload  ->  http://localhost:8000")


if __name__ == "__main__":
    main()
