"""Parser for the wallet-tracker alert family.

Two layouts share the same `[CHAIN] ... — S: N` header, so one parser detects
and handles both rather than guessing which bot sent what.

Layout A — explicit swap legs:

    [SOL] [BUY] - (FOMO BUY) @loganlim_x — S: 1
    Fomo: @loganlim_x
    Method: DF1o...7QBH
    ➡️ SENT: 993.40 USD Coin (USDC)
    ⬅️ RECEIVED: 689224.24 SelfMade by SP3ND (MADE) 0.07%
    📊 MC: $1.38M - Age: 4 days ago

Layout B — swap-to with PnL:

    [BSC] dimiNew — S: 1
    🔴Swap 31.63M CHOUCHOU (CHOUCHOU) 3.16%
       to: 0.23 BNB (~$160.32)
    📊 Exit (CHOUCHOU) ▼
    📉 PnL (0.58x): -0.17 BNB (-$117.56) | ⏱️ 23h

Side is decided by which leg is the quote asset (SOL/ETH/BNB/USDC/...), not by
the header tag: the Base sample above is tagged "(OUT)" yet is a buy — ETH went
out, BITBANK came in. Trusting the tag would invert every such alert.

The trailing "0.07%" / "3.16%" is the share of supply that ONE trade moved, not
a running balance. positions.py accumulates it (buys add, sells subtract),
which is valid because supply is fixed.
"""

from __future__ import annotations

import re

from .base import (
    BUY,
    SELL,
    Event,
    Leg,
    ParseContext,
    chain_from_tag,
    classify_who,
    find_number_after,
    find_usd_in,
    parse_header,
    parse_leg,
    to_float,
    token_addr_from_urls,
    token_key_for,
    tx_hash_from_urls,
    wallet_addr_from_urls,
    RE_TRUNC,
    STABLES,
    register,
)

RE_SENT = re.compile(r"SENT\s*:\s*(.+)", re.IGNORECASE)
RE_RECEIVED = re.compile(r"RECEIV(?:ED)?\s*:\s*(.+)", re.IGNORECASE)
RE_SWAP = re.compile(r"Swap\s+(.+)", re.IGNORECASE)
RE_TO = re.compile(r"^\s*to\s*:\s*(.+)", re.IGNORECASE)
RE_EXIT = re.compile(r"\bExit\b", re.IGNORECASE)
# Two PnL spellings: "PnL (0.58x): ..." and "PnL (-24.7%): ..."
RE_PNL = re.compile(r"PnL\s*\((-?[\d.]+)\s*(x|%)\)\s*:\s*(.+)", re.IGNORECASE)
# "📊 Holds 14.27M MM (1.52%)" — the bot's own statement of the CURRENT total
# position after this trade. Authoritative over any accumulation we compute.
RE_HOLDS = re.compile(
    r"Holds\s+(" + r"\d[\d,]*(?:\.\d+)?" + r")\s*([KMBTkmbt])?\s+\S+\s*\((" +
    r"\d[\d,]*(?:\.\d+)?" + r")\s*%\)",
)
# Footer line: "TX | DFI | GMGN | DXS | $223.1K | 6d" — the $ figure is the
# token's market cap. Distinguished from the PnL line by starting with TX.
RE_FOOTER_MCAP = re.compile(
    r"^\s*(?:🔗\s*)?TX\b[^\n$]*\|\s*\$\s*(\d[\d,]*(?:\.\d+)?)\s*([KMBTkmbt])?\s*\|",
    re.MULTILINE,
)
RE_HANDLE_LINE = re.compile(r"^\s*(?:Fomo|Trader|Wallet|Name)\s*:\s*(@?\S+)", re.IGNORECASE)
# MULTILINE matters: "Method:" is never on the first line.
RE_METHOD = re.compile(r"^\s*Method\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def _legs(text: str) -> tuple[Leg | None, Leg | None]:
    """(outgoing, incoming) legs, from whichever layout the alert uses."""
    sent = received = None
    lines = text.splitlines()

    for i, line in enumerate(lines):
        if sent is None:
            m = RE_SENT.search(line)
            if m:
                sent = parse_leg(m.group(1))
                continue
        if received is None:
            m = RE_RECEIVED.search(line)
            if m:
                received = parse_leg(m.group(1))
                continue

        # Layout B: "🔴Swap <out>" followed by "   to: <in>"
        if sent is None and received is None:
            m = RE_SWAP.search(line)
            if m and "to:" not in line.lower():
                sent = parse_leg(m.group(1))
                for nxt in lines[i + 1 : i + 3]:
                    mt = RE_TO.search(nxt)
                    if mt:
                        received = parse_leg(mt.group(1))
                        break

    return sent, received


def _wallet(text: str) -> str | None:
    m = RE_METHOD.search(text)
    if m:
        val = m.group(1).strip()
        # Only address shapes count — "Method: swap" is a mode and
        # "Method: permit2TransferAndMulticall" is a contract call name.
        if RE_TRUNC.fullmatch(val):
            return val
    return None


def _handle(text: str, header_who: str | None) -> str | None:
    for line in text.splitlines()[1:]:
        m = RE_HANDLE_LINE.search(line)
        if m:
            return m.group(1)
    return header_who


def _pnl(text: str) -> tuple[float | None, float | None]:
    m = RE_PNL.search(text)
    if not m:
        return None, None
    usd = find_usd_in(m.group(3))
    val = _safe_float(m.group(1))
    if m.group(2) == "x":
        x = val
    else:
        # "-24.7%" -> 0.753x, so both spellings land in the same field.
        x = round(1 + val / 100, 4) if val is not None else None
    return usd, x


def _holds(text: str) -> tuple[float | None, float | None]:
    """(holds_amount, holds_pct) from a 'Holds 14.27M MM (1.52%)' line."""
    m = RE_HOLDS.search(text)
    if not m:
        return None, None
    return to_float(m.group(1), m.group(2)), to_float(m.group(3))


def _mcap(text: str) -> float | None:
    """Market cap from an explicit label, else from the TX footer line."""
    v = find_number_after(text, "MC", "Market Cap", "MCap", "FDV")
    if v is not None:
        return v
    m = RE_FOOTER_MCAP.search(text)
    if m:
        return to_float(m.group(1), m.group(2))
    return None


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@register("tracker")
def parse(text: str, ctx: ParseContext) -> list[Event]:
    if not text:
        return []

    hdr = parse_header(text)
    chain = hdr.chain or chain_from_tag(hdr.chain_tag) or ctx.chain_hint
    if not chain:
        return []

    out_leg, in_leg = _legs(text)
    if out_leg is None and in_leg is None:
        return []

    # The leg that isn't a quote asset is the token being traded.
    if in_leg is not None and not in_leg.is_quote:
        token_leg, counter_leg, side = in_leg, out_leg, BUY
    elif out_leg is not None and not out_leg.is_quote:
        token_leg, counter_leg, side = out_leg, in_leg, SELL
    else:
        # Both legs look like quote assets (e.g. a plain SOL->USDC swap).
        return []

    # Identity. Every bot embeds the trader's FULL wallet as the first
    # /address/ link, and that address is the one identity shared across all
    # three bots — so it is the canonical trader_key whenever present. The
    # header's handle/label becomes the display name. Only when no wallet
    # link exists do we fall back to classifying the header string itself.
    who = classify_who(_handle(text, hdr.who))
    wallet = wallet_addr_from_urls(ctx.urls()) or _wallet(text)

    handle = who[1] if who and who[0] == "handle" else None

    if wallet and not RE_TRUNC.fullmatch(wallet):
        tkey = wallet.lower() if wallet.startswith("0x") else wallet
    elif who is not None:
        tkey = who[1]
        if who[0] != "handle":
            wallet = wallet or (tkey.removeprefix("trunc:") if tkey.startswith("trunc:") else tkey)
    elif wallet:
        tkey = f"trunc:{wallet}"
    else:
        return []

    token_addr = token_addr_from_urls(ctx.urls())
    token_key = token_key_for(token_addr, token_leg.symbol, token_leg.name)
    if not token_key:
        return []

    # USD size: prefer an explicit figure on the counter leg, else treat a
    # stablecoin amount as dollars. A SOL/ETH-denominated leg has no USD value
    # in the message, so it stays None rather than being guessed.
    amount_usd = None
    if counter_leg is not None:
        if counter_leg.usd is not None:
            amount_usd = counter_leg.usd
        elif (counter_leg.symbol or "").upper() in STABLES or (counter_leg.name or "").upper() in STABLES:
            amount_usd = counter_leg.amount

    pnl_usd, pnl_x = _pnl(text)
    holds_amount, holds_pct = _holds(text)

    return [
        Event(
            chain=chain,
            chain_tag=hdr.chain_tag,
            token_key=token_key,
            token_symbol=token_leg.symbol,
            token_name=token_leg.name,
            trader_key=tkey,
            trader_handle=handle,
            wallet_addr=wallet,
            side=side,
            is_exit=bool(RE_EXIT.search(text)) and side == SELL,
            ts=ctx.ts,
            amount_tokens=token_leg.amount,
            amount_usd=amount_usd,
            pct_supply=token_leg.pct_supply,
            holds_pct=holds_pct,
            holds_amount=holds_amount,
            mcap_usd=_mcap(text),
            pnl_usd=pnl_usd,
            pnl_x=pnl_x,
            tx_hash=tx_hash_from_urls(ctx.urls()),
        )
    ]
