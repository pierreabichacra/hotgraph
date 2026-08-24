"""Loose fallback for alert shapes `tracker` doesn't recognize.

It only fires when a message has a `[CHAIN]` header and a readable trader, and
it pulls whatever fields it can find. Anything it produces is worth reviewing —
if a real bot format keeps landing here, give it proper handling in tracker.py
and add a case to tests/samples.py.
"""

from __future__ import annotations

import re

from .base import (
    BUY,
    Event,
    ParseContext,
    chain_from_tag,
    find_number_after,
    guess_side,
    parse_header,
    token_addr_from_urls,
    token_key_for,
    trader_key_for,
    NUM,
    register,
)

RE_TICKER = re.compile(r"\(([A-Z0-9]{2,12})\)")
RE_PCT = re.compile(r"(" + NUM + r")\s*%")


@register("generic")
def parse(text: str, ctx: ParseContext) -> list[Event]:
    if not text:
        return []

    hdr = parse_header(text)
    chain = hdr.chain or chain_from_tag(hdr.chain_tag) or ctx.chain_hint
    tkey = trader_key_for(hdr.who)
    if not chain or not tkey:
        return []

    symbol = None
    m = RE_TICKER.search(text)
    if m:
        symbol = m.group(1).upper()

    token_key = token_key_for(token_addr_from_urls(ctx.urls()), symbol)
    if not token_key:
        return []

    pm = RE_PCT.search(text)

    return [
        Event(
            chain=chain,
            chain_tag=hdr.chain_tag,
            token_key=token_key,
            token_symbol=symbol,
            trader_key=tkey,
            trader_handle=(hdr.who or "").lstrip("@") or None,
            side=guess_side(text) or BUY,
            ts=ctx.ts,
            pct_supply=float(pm.group(1).replace(",", "")) if pm else None,
            mcap_usd=find_number_after(text, "MC", "Market Cap", "MCap", "FDV"),
        )
    ]
