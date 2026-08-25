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

Layout C — several wallets in one alert (same bot as B, fired when tracked
wallets trade the same token in the same block):

    🔴 [BSC] 2 wallets sold 豆豆 in #118002792

    1. PGmgn | TX
    ├ 🔴 10.01M 酸奶豆糕 (豆豆) 1.00%
    ├ to: 0.08 BNB (~$55.50)
    └ 📉 PnL -0.12 BNB (0.39x) | ⏱️ 3h

    2. P | TX
    ├ 🔴 9.95M 酸奶豆糕 (豆豆) 0.99%
    ├ to: 0.078 BNB (~$53.94)
    └ 📉 PnL -0.12 BNB (0.38x) | ⏱️ 3h

    Σ 0.16 BNB (~$109.44) ← 19.96M (2.00%)
    BSD | DFI | GMGN | DXS | $5.8K | 3h

One Event per numbered section. Each section's wallet and TX come from the
links positioned inside it (see ParseContext.linked_urls); the token is the
one every section shares.

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
    utf16_offset,
    wallet_addr_from_urls,
    strip_inline_urls,
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
# Layout C puts the multiple after the amount: "PnL -0.12 BNB (0.39x)"
RE_PNL_C = re.compile(
    r"PnL\s+(-?[\d.,]+)\s*[A-Za-z]+\s*(?:\((-?\$[\d.,]+[KMBTkmbt]?)\)\s*)?\((-?[\d.]+)\s*(x|%)\)",
    re.IGNORECASE,
)
# "📊 Holds 14.27M MM (1.52%)" — the bot's own statement of the CURRENT total
# position after this trade. Authoritative over any accumulation we compute.
RE_HOLDS = re.compile(
    r"Holds\s+(" + r"\d[\d,]*(?:\.\d+)?" + r")\s*([KMBTkmbt])?\s+\S+\s*\((" +
    r"\d[\d,]*(?:\.\d+)?" + r")\s*%\)",
)
# Footer line: "TX | DFI | GMGN | DXS | $223.1K | 6d" — the $ figure is the
# token's market cap. Distinguished from the PnL line by starting with TX.
# Layout C's footer has no TX (each section has its own): "BSD | DFI | ...".
RE_FOOTER_MCAP = re.compile(
    r"^\s*(?:🔗\s*)?(?:TX|BSD|DFI|GMGN|DXS)\b[^\n$]*\|\s*\$\s*(\d[\d,]*(?:\.\d+)?)\s*([KMBTkmbt])?\s*\|",
    re.MULTILINE,
)
RE_HANDLE_LINE = re.compile(r"^\s*(?:Fomo|Trader|Wallet|Name)\s*:\s*(@?\S+)", re.IGNORECASE)
# MULTILINE matters: "Method:" is never on the first line.
RE_METHOD = re.compile(r"^\s*Method\s*:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def _legs(text: str) -> tuple[list[Leg], list[Leg]]:
    """(outgoing, incoming) legs, from whichever layout the alert uses.

    Multi-leg alerts list every transfer in the tx — a router fee first
    ("SENT: 0.14 BNB To: Maestro: Fees"), internal hops by other
    addresses, NFT positions — so both sides come back whole and `_pick`
    decides which pair is the trade. Taking just the first SENT line made
    the fee the "token" and keyed it to whatever contract the links held.
    """
    sent: list[Leg] = []
    received: list[Leg] = []
    lines = text.splitlines()

    for i, line in enumerate(lines):
        m = RE_SENT.search(line)
        if m:
            leg = parse_leg(m.group(1))
            if leg:
                sent.append(leg)
            continue
        m = RE_RECEIVED.search(line)
        if m:
            leg = parse_leg(m.group(1))
            if leg:
                received.append(leg)
            continue

        # Layout B: "🔴Swap <out>" followed by "   to: <in>"
        if not sent and not received:
            m = RE_SWAP.search(line)
            if m and "to:" not in line.lower():
                leg = parse_leg(m.group(1))
                if leg:
                    sent.append(leg)
                for nxt in lines[i + 1 : i + 3]:
                    mt = RE_TO.search(nxt)
                    if mt:
                        leg = parse_leg(mt.group(1))
                        if leg:
                            received.append(leg)
                        break

    return sent, received


def _best(legs: list[Leg]) -> Leg:
    """Among several legs of one kind, the one that represents the trade:
    a stated share of supply wins, then a USD figure, then the largest
    amount — a router fee is always the small one."""
    return max(legs, key=lambda l: (l.pct_supply is not None, l.usd is not None, l.amount or 0))


def _pick(sent: list[Leg], received: list[Leg]) -> tuple[Leg, Leg | None, str] | None:
    """(token_leg, counter_leg, side), or None when no leg is a real token.

    The leg that isn't a quote asset is the token being traded; an alert
    whose legs are all quote assets (ETH->USDC, a BNB fee transfer) is not
    a token trade and must produce nothing — not even for the fallback
    parser to guess at.
    """
    tokens_in = [l for l in received if not l.is_quote]
    tokens_out = [l for l in sent if not l.is_quote]
    if tokens_in:
        token, side = _best(tokens_in), BUY
        quotes = [l for l in sent if l.is_quote]
    elif tokens_out:
        token, side = _best(tokens_out), SELL
        quotes = [l for l in received if l.is_quote]
    else:
        return None
    return token, (_best(quotes) if quotes else None), side


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
    if m:
        usd = find_usd_in(m.group(3))
        val, unit = _safe_float(m.group(1)), m.group(2)
    else:
        m = RE_PNL_C.search(text)
        if not m:
            return None, None
        usd = find_usd_in(m.group(2)) if m.group(2) else None
        val, unit = _safe_float(m.group(3)), m.group(4)
    if unit == "x":
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


# ---------------------------------------------------------------------------
# Layout C: "N wallets sold/bought"
# ---------------------------------------------------------------------------

RE_MULTI_HEAD = re.compile(
    r"^[^\[\n]{0,8}\[[A-Za-z]+\]\s+(\d+)\s+wallets?\s+(sold|bought)\b", re.IGNORECASE
)
# "1. PGmgn | TX" — the label is a bot nickname for the wallet.
RE_SECTION = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*\|\s*TX\b", re.MULTILINE)
# Box-drawing prefixes and the status dot in front of each section line.
RE_TREE = re.compile(r"^\s*[├└│┌┐┘┬┴┼─]+\s*")
RE_STATUS_DOT = re.compile(r"^\s*[🔴🟢🟥🟩📉📈]+\s*")
RE_SIGMA = re.compile(r"^\s*Σ", re.MULTILINE)


def is_multi_wallet(text: str) -> bool:
    return bool(RE_MULTI_HEAD.search(text or ""))


def _sections(text: str) -> list[tuple[str, int, int]]:
    """(label, start, end) of every numbered section, as string indices."""
    starts = list(RE_SECTION.finditer(text))
    if not starts:
        return []
    sig = RE_SIGMA.search(text, starts[-1].end())
    tail = sig.start() if sig else len(text)
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else tail
        out.append((m.group(2), m.start(), end))
    return out


def _section_legs(body: str) -> tuple[list[Leg], list[Leg]]:
    """Legs of one section: the first amount line is what went out, the
    'to:' line is what came in (same convention as Layout B's Swap/to)."""
    sent: list[Leg] = []
    received: list[Leg] = []
    for line in body.splitlines()[1:]:
        line = RE_STATUS_DOT.sub("", RE_TREE.sub("", line)).strip()
        if not line or "pnl" in line.lower():
            continue
        mt = RE_TO.search(line)
        if mt:
            leg = parse_leg(mt.group(1))
            if leg:
                received.append(leg)
        elif not sent:
            leg = parse_leg(line)
            if leg:
                sent.append(leg)
    return sent, received


def _parse_multi(text: str, ctx: ParseContext) -> list[Event]:
    hdr = parse_header(text)
    chain = hdr.chain or chain_from_tag(hdr.chain_tag) or ctx.chain_hint
    if not chain:
        return []

    linked = ctx.linked_urls()
    _, inline_all = strip_inline_urls(text)
    token_addr = token_addr_from_urls(ctx.urls() + inline_all)
    mcap = _mcap(text)

    events: list[Event] = []
    for label, start, end in _sections(text):
        body, inline = strip_inline_urls(text[start:end])
        # Entity links that sit inside this section's span.
        lo, hi = utf16_offset(text, start), utf16_offset(text, end)
        span_urls = [u for off, _ln, u in linked if lo <= off < hi] + inline

        picked = _pick(*_section_legs(body))
        if picked is None:
            continue
        token_leg, counter_leg, side = picked

        label_clean, _ = strip_inline_urls(label)
        ev = _build_event(
            chain=chain, hdr=hdr, who_text=label_clean.strip(),
            wallet_url=wallet_addr_from_urls(span_urls),
            token_addr=token_addr, token_leg=token_leg, counter_leg=counter_leg,
            side=side, body=body, ctx=ctx, mcap=mcap,
            tx_hash=tx_hash_from_urls(span_urls),
        )
        if ev is not None:
            events.append(ev)
    return events


def _build_event(*, chain, hdr, who_text, wallet_url, token_addr, token_leg,
                 counter_leg, side, body, ctx, mcap, tx_hash) -> Event | None:
    # Identity. Every bot embeds the trader's FULL wallet as the first
    # /address/ link, and that address is the one identity shared across all
    # three bots — so it is the canonical trader_key whenever present. The
    # header's handle/label becomes the display name. Only when no wallet
    # link exists do we fall back to classifying the header string itself.
    who = classify_who(who_text)
    wallet = wallet_url or _wallet(body)

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
        return None

    token_key = token_key_for(token_addr, token_leg.symbol, token_leg.name)
    if not token_key:
        return None

    # USD size: prefer an explicit figure on the counter leg, else treat a
    # stablecoin amount as dollars. A SOL/ETH-denominated leg has no USD value
    # in the message, so it stays None rather than being guessed.
    amount_usd = None
    if counter_leg is not None:
        if counter_leg.usd is not None:
            amount_usd = counter_leg.usd
        elif (counter_leg.symbol or "").upper() in STABLES or (counter_leg.name or "").upper() in STABLES:
            amount_usd = counter_leg.amount

    pnl_usd, pnl_x = _pnl(body)
    holds_amount, holds_pct = _holds(body)

    return Event(
        chain=chain,
        chain_tag=hdr.chain_tag,
        token_key=token_key,
        token_symbol=token_leg.symbol,
        token_name=token_leg.name,
        trader_key=tkey,
        trader_handle=handle,
        wallet_addr=wallet,
        side=side,
        is_exit=bool(RE_EXIT.search(body)) and side == SELL,
        ts=ctx.ts,
        amount_tokens=token_leg.amount,
        amount_usd=amount_usd,
        pct_supply=token_leg.pct_supply,
        holds_pct=holds_pct,
        holds_amount=holds_amount,
        mcap_usd=mcap,
        pnl_usd=pnl_usd,
        pnl_x=pnl_x,
        tx_hash=tx_hash,
    )


@register("tracker")
def parse(text: str, ctx: ParseContext) -> list[Event]:
    if not text:
        return []

    if is_multi_wallet(text):
        return _parse_multi(text, ctx)

    hdr = parse_header(text)
    chain = hdr.chain or chain_from_tag(hdr.chain_tag) or ctx.chain_hint
    if not chain:
        return []

    picked = _pick(*_legs(text))
    if picked is None:
        return []
    token_leg, counter_leg, side = picked

    ev = _build_event(
        chain=chain, hdr=hdr, who_text=_handle(text, hdr.who),
        wallet_url=wallet_addr_from_urls(ctx.urls()),
        token_addr=token_addr_from_urls(ctx.urls()),
        token_leg=token_leg, counter_leg=counter_leg, side=side,
        body=text, ctx=ctx, mcap=_mcap(text),
        tx_hash=tx_hash_from_urls(ctx.urls()),
    )
    return [ev] if ev is not None else []
