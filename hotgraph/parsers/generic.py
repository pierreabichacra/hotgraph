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
    is_multi_wallet,
    is_quote,
    parse_header,
    token_addr_from_urls,
    token_key_for,
    trader_key_for,
    NUM,
    register,
)

RE_TICKER = re.compile(r"\(([A-Z0-9]{2,12})\)")
RE_PCT = re.compile(r"(" + NUM + r")\s*%")
# Header tags shaped like tickers: "[ETH] [PRI] - (OUT) pnl — S: 1".
NOT_TICKERS = {"IN", "OUT", "BUY", "SELL", "PRI", "FOMO", "SWAP", "TX", "MC"}


def _ticker(text: str) -> str | None:
    """First parenthesised ticker in the BODY. The header line is skipped:
    its "(OUT)" / "(IN)" is a direction, not a token — reading it as one
    keyed ETH->USDC swaps to USDC's contract under the symbol "OUT"."""
    body = text.split("\n", 1)[1] if "\n" in text else ""
    for m in RE_TICKER.finditer(body):
        if m.group(1) not in NOT_TICKERS:
            return m.group(1)
    return None


@register("generic")
def parse(text: str, ctx: ParseContext) -> list[Event]:
    if not text:
        return []
    # "N wallets bought X in #block": the header names no trader, so the
    # loose read would file the sentence itself as a holder. Only the
    # tracker parser understands the numbered sections; if it found nothing,
    # nothing is the answer.
    if is_multi_wallet(text):
        return []

    hdr = parse_header(text)
    chain = hdr.chain or chain_from_tag(hdr.chain_tag) or ctx.chain_hint
    tkey = trader_key_for(hdr.who)
    if not chain or not tkey:
        return []

    symbol = _ticker(text)
    # The only ticker is a quote asset (ETH->USDC, DAI->USDC): not a token
    # trade, whatever contract the links point at.
    if symbol and is_quote(symbol):
        return []
    # SENT/RECEIVED/Swap layouts are the tracker parser's. When it produced
    # nothing for one, every leg was a quote asset — don't invent a token
    # from the links.
    if symbol is None and ("SENT" in text.upper() or "SWAP" in text.upper()):
        return []

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
