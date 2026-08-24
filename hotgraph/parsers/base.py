"""Event model, parser registry, and text-extraction helpers.

A parser is `fn(text: str, ctx: ParseContext) -> list[Event]`. Anything the bot
didn't state stays None — the positions engine copes with partial data.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Callable

BUY, SELL = "BUY", "SELL"

# --------------------------------------------------------------------------
# Chains
# --------------------------------------------------------------------------

# The alerts lead with a bracket tag: [SOL], [BASE], [BSC], [RH]...
# Tags observed in the real bot feeds map to a chain family; family decides
# address normalization (EVM addresses are case-insensitive).
CHAIN_TAGS = {
    "SOL": "solana",
    "SOLANA": "solana",
    "ETH": "evm",
    "BASE": "evm",
    "BSC": "evm",
    "BNB": "evm",
    "ARB": "evm",
    "ARBITRUM": "evm",
    "POLY": "evm",
    "MATIC": "evm",
    "AVAX": "evm",
    "OP": "evm",
    "BLAST": "evm",
    "RH": "evm",          # Robinhood chain
    "ROBINHOOD": "evm",
    "ARC": "evm",
    "STBL": "evm",
    "ABS": "evm",         # Abstract
    "HYPE": "evm",        # HyperEVM
    "TRON": "tron",
}

# Currencies traders pay WITH. Whichever leg of a swap is not one of these is
# the token we care about — this is how side is determined, rather than
# trusting the header tag (an alert tagged "(OUT)" can still be a buy).
QUOTE_SYMBOLS = {
    "SOL", "WSOL", "ETH", "WETH", "BNB", "WBNB", "MATIC", "WMATIC", "AVAX",
    "USDC", "USDT", "DAI", "BUSD", "USDE", "FDUSD", "USD COIN", "TETHER",
    "USDC.E", "WBTC", "CBBTC",
}

STABLES = {"USDC", "USDT", "DAI", "BUSD", "FDUSD", "USD COIN", "TETHER", "USDC.E"}


def chain_from_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    return CHAIN_TAGS.get(tag.strip().upper())


def is_quote(symbol: str | None, name: str | None = None) -> bool:
    for cand in (symbol, name):
        if cand and cand.strip().upper() in QUOTE_SYMBOLS:
            return True
    return False


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass
class Event:
    chain: str
    token_key: str          # mint/contract when known, else 'sym:TICKER'
    trader_key: str         # handle (lowercased) or wallet address
    side: str
    ts: int = 0
    chain_tag: str | None = None
    token_symbol: str | None = None
    token_name: str | None = None
    trader_handle: str | None = None
    wallet_addr: str | None = None
    is_exit: bool = False
    amount_tokens: float | None = None
    amount_usd: float | None = None
    pct_supply: float | None = None   # share of supply this single trade moved
    holds_pct: float | None = None    # bot-stated TOTAL holding after the trade
    holds_amount: float | None = None
    mcap_usd: float | None = None
    pnl_usd: float | None = None
    pnl_x: float | None = None
    tx_hash: str | None = None        # from the TX link; used for cross-bot dedup

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParseContext:
    """What the parser knows beyond the message text itself."""

    source_id: str
    ts: int
    chain_hint: str | None = None
    raw_json: str | None = None
    meta: dict = field(default_factory=dict)

    def urls(self) -> list[str]:
        # Cached — called for both the token address and the tx hash, and
        # parsing the raw JSON twice per message adds up over a backfill.
        cached = self.meta.get("_urls")
        if cached is None:
            cached = urls_from_raw_json(self.raw_json)
            self.meta["_urls"] = cached
        return cached


Parser = Callable[[str, ParseContext], list[Event]]
registry: dict[str, Parser] = {}


def register(parser_id: str) -> Callable[[Parser], Parser]:
    def deco(fn: Parser) -> Parser:
        registry[parser_id] = fn
        return fn

    return deco


def get_parser(parser_id: str) -> Parser | None:
    return registry.get(parser_id)


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}

NUM = r"\d[\d,]*(?:\.\d+)?"


def to_float(raw: str | None, suffix: str | None = None) -> float | None:
    """'31.63' + 'M' -> 31630000.0 ; '$1,380,000' -> 1380000.0"""
    if raw is None:
        return None
    try:
        val = float(str(raw).replace(",", "").replace("$", "").replace("~", "").strip())
    except (ValueError, TypeError):
        return None
    if suffix:
        val *= _SUFFIX.get(suffix.lower(), 1)
    return val


def find_number_after(text: str, *labels: str) -> float | None:
    """First number following any label. 'MC: $1.38M' -> 1380000.0"""
    for label in labels:
        m = re.search(
            re.escape(label) + r"\s*[:=]?\s*~?\$?\s*(" + NUM + r")\s*([kKmMbBtT])?",
            text,
            re.IGNORECASE,
        )
        if m:
            val = to_float(m.group(1), m.group(2))
            if val is not None:
                return val
    return None


def find_usd_in(text: str) -> float | None:
    """First dollar figure anywhere.

    '(~$160.32)' -> 160.32 ; '$5.4K' -> 5400.0 ; '(-$117.56)' -> -117.56

    The sign can sit on either side of the '$', so both positions are captured.
    """
    m = re.search(r"(-)?\s*~?\$\s*(-)?\s*(" + NUM + r")\s*([kKmMbBtT])?", text)
    if not m:
        return None
    val = to_float(m.group(3), m.group(4))
    if val is not None and (m.group(1) or m.group(2)):
        val = -abs(val)
    return val


# --------------------------------------------------------------------------
# Addresses and URLs
# --------------------------------------------------------------------------

RE_EVM = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
RE_SOL = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
# Truncated forms the alerts print for wallets: DF1o...7QBH
RE_TRUNC = re.compile(r"\b([A-Za-z0-9]{3,8})\.{2,4}([A-Za-z0-9]{3,8})\b")


def urls_from_raw_json(raw_json: str | None) -> list[str]:
    """Pull hyperlink targets out of a stored Telethon message.

    The alerts hide the full mint behind link text ("DEXSCR", "BIRDEYE"), so
    the address only exists in the message entities — never in the visible
    text. This is why capture stores raw_json.
    """
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except (ValueError, TypeError):
        return []

    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            url = node.get("url")
            if isinstance(url, str) and url.startswith("http"):
                out.append(url)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return out


_ADDR = r"(0x[a-fA-F0-9]{40}|[1-9A-HJ-NP-Za-km-z]{32,44})"

# Block-explorer token pages. The scanner host varies per chain (etherscan,
# bscscan, basescan, rh-scan, arbiscan...) so match on the "scan" stem.
_RE_SCANNER_TOKEN = re.compile(r"[a-z0-9-]*scan[a-z0-9.-]*/token/" + _ADDR, re.I)
# Chart sites whose path id is the traded token (dextools is excluded — its
# pair-explorer ids are PAIR addresses, not the token).
_RE_CHART_TOKEN = [
    re.compile(r"dexscreener\.com/[a-z-]+/" + _ADDR, re.I),
    re.compile(r"defined\.fi/[a-z-]+/" + _ADDR, re.I),
    re.compile(r"gmgn\.ai/\S*?/(?:token/)?" + _ADDR, re.I),
    re.compile(r"birdeye\.so/(?:token/)?(?:[a-z]+/)?([1-9A-HJ-NP-Za-km-z]{32,44})", re.I),
]
# Trader wallet pages: first /address/ or /account/ link in an alert is the
# wallet that made the trade — every one of the three bots includes it.
_RE_WALLET_URL = re.compile(r"/(?:address|account)/" + _ADDR, re.I)

_URL_SKIP = re.compile(r"/(tx|account|address)/|/portfolio|t\.me/", re.I)


def token_addr_from_urls(urls: list[str]) -> str | None:
    """The traded token's address, from the message's hyperlinks.

    Alerts link EVERY token in the swap (quote legs like USDC/WETH included),
    so "first token link" would often key events to the quote asset. The
    traded token is the one the chart links point at — prefer a scanner token
    that a chart URL confirms, then fall back to the last-linked token (the
    traded leg is linked last in every observed layout), then to a bare chart
    id.
    """
    scanner: list[str] = []
    chart: list[str] = []
    for url in urls:
        m = _RE_SCANNER_TOKEN.search(url)
        if m and m.group(1) not in scanner:
            scanner.append(m.group(1))
        if _URL_SKIP.search(url):
            continue
        for pat in _RE_CHART_TOKEN:
            m = pat.search(url)
            if m and m.group(1) not in chart:
                chart.append(m.group(1))

    chart_l = {c.lower() for c in chart}
    for cand in scanner:
        if cand.lower() in chart_l:
            return cand
    if scanner:
        return scanner[-1]
    return chart[0] if chart else None


def wallet_addr_from_urls(urls: list[str]) -> str | None:
    """The trader's full wallet address, from the first /address|/account link."""
    for url in urls:
        m = _RE_WALLET_URL.search(url)
        if m:
            return m.group(1)
    return None


# The "TX" link in an alert points at the transaction on an explorer. Its hash
# is the one identifier shared by every bot reporting the same trade, which is
# what makes cross-bot dedup possible.
_URL_TX_PATTERNS = [
    re.compile(r"solscan\.io/tx/([1-9A-HJ-NP-Za-km-z]{43,88})", re.I),
    re.compile(r"solana\.fm/tx/([1-9A-HJ-NP-Za-km-z]{43,88})", re.I),
    re.compile(r"(?:etherscan|bscscan|basescan|arbiscan|polygonscan|snowtrace)\.\w+/tx/(0x[a-fA-F0-9]{64})", re.I),
    re.compile(r"/tx/(0x[a-fA-F0-9]{64}|[1-9A-HJ-NP-Za-km-z]{43,88})", re.I),
]


def tx_hash_from_urls(urls: list[str]) -> str | None:
    """Transaction hash/signature from the message's explorer links."""
    for url in urls:
        for pat in _URL_TX_PATTERNS:
            m = pat.search(url)
            if m:
                h = m.group(1)
                return h.lower() if h.startswith("0x") else h
    return None


def find_addresses(text: str, chain_hint: str | None = None) -> list[tuple[str, str]]:
    """All full addresses as (chain, address), in order of appearance."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for m in RE_EVM.finditer(text):
        a = m.group(0)
        if a.lower() not in seen:
            seen.add(a.lower())
            found.append(("evm", a))

    if chain_hint != "evm":
        stripped = re.sub(r"https?://\S+", " ", text)
        for m in RE_SOL.finditer(stripped):
            a = m.group(0)
            if a in seen or RE_EVM.fullmatch(a):
                continue
            seen.add(a)
            found.append(("solana", a))

    return found


def token_key_for(addr: str | None, symbol: str | None, name: str | None = None) -> str | None:
    """Stable identity for a token.

    A real mint/contract when we have one. Otherwise fall back to the ticker,
    which is a weaker key — two different tokens sharing a ticker would merge —
    so `ingest` flags symbol-keyed tokens as low confidence.
    """
    if addr:
        return addr
    sym = (symbol or "").strip().upper()
    if sym:
        return f"sym:{sym}"
    nm = (name or "").strip().upper()
    return f"sym:{nm}" if nm else None


# --------------------------------------------------------------------------
# Header: "[SOL] [BUY] - (FOMO BUY) @loganlim_x — S: 1"
# --------------------------------------------------------------------------

RE_CHAIN_TAG = re.compile(r"^\s*\[([A-Za-z]+)\]")
# Score can be a number or an emoji ("S: 1", "S: ❌").
RE_SCORE_TAIL = re.compile(r"[—–-]\s*S\s*:\s*\S+\s*$")


@dataclass
class Header:
    chain_tag: str | None = None
    chain: str | None = None
    tags: list[str] = field(default_factory=list)
    paren: str | None = None
    who: str | None = None


def parse_header(text: str) -> Header:
    """Read the first line of an alert.

    Handles all three observed shapes:
        [SOL] [BUY] - (FOMO BUY) @loganlim_x — S: 1
        [BASE] [PRI] - (OUT) joswe — S: 1
        [BSC] dimiNew — S: 1
    """
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    hdr = Header()

    m = RE_CHAIN_TAG.search(line)
    if m:
        hdr.chain_tag = m.group(1).upper()
        hdr.chain = chain_from_tag(hdr.chain_tag)

    hdr.tags = [t.upper() for t in re.findall(r"\[([A-Za-z]+)\]", line)]
    parens = re.findall(r"\(([^)]*)\)", line)
    hdr.paren = parens[0] if parens else None

    # Strip tags, parentheticals and the trailing score to leave the person.
    who = re.sub(r"\[[^\]]*\]", " ", line)
    who = re.sub(r"\([^)]*\)", " ", who)
    who = RE_SCORE_TAIL.sub("", who)
    who = who.strip().lstrip("-–—").strip()
    who = re.sub(r"\s{2,}", " ", who)
    hdr.who = who or None
    return hdr


def classify_who(s: str | None) -> tuple[str, str] | None:
    """What kind of identity is this string?

    Returns (kind, normalized) where kind is:
        'handle'        Telegram handle / bot label ("@loganlim_x", "dimiNew")
        'address'       full EVM or Solana address
        'trunc_address' truncated display form ("DF1o...7QBH")

    Bots A identifies people by handle; bots B/C print addresses in the same
    header slot, so this is what routes the two identity models apart. An
    explicit '@' always means handle — no address starts with '@'.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    if s.startswith("@"):
        h = s.lstrip("@").strip()
        return ("handle", h.lower()) if h else None
    if RE_EVM.fullmatch(s):
        return ("address", s.lower())
    if RE_TRUNC.fullmatch(s):
        # Keep the exact printed form — it is the only stable key we have, and
        # PersonResolver matches its prefix/suffix against configured wallets.
        return ("trunc_address", f"trunc:{s}")
    # Full Solana addresses are plain base58, which also matches ordinary
    # usernames of the same length — require address-typical length AND mixed
    # case to avoid swallowing a long lowercase handle.
    if RE_SOL.fullmatch(s) and len(s) >= 32 and s.lower() != s:
        return ("address", s)
    return ("handle", s.lower())


def trader_key_for(handle: str | None, wallet: str | None = None) -> str | None:
    """Stable trader key: classified handle-or-address, else the wallet."""
    who = classify_who(handle)
    if who:
        return who[1]
    if wallet:
        w = wallet.strip()
        if RE_TRUNC.fullmatch(w):
            return f"trunc:{w}"
        return w.lower() if RE_EVM.fullmatch(w) else w
    return None


# --------------------------------------------------------------------------
# Token legs: "689224.24 SelfMade by SP3ND (MADE) 0.07%"
# --------------------------------------------------------------------------


@dataclass
class Leg:
    amount: float | None = None
    name: str | None = None
    symbol: str | None = None
    pct_supply: float | None = None
    usd: float | None = None

    @property
    def is_quote(self) -> bool:
        return is_quote(self.symbol, self.name)


RE_LEG = re.compile(
    r"^\s*(?P<amt>" + NUM + r")\s*(?P<suf>[KMBTkmbt])?\s+"
    r"(?P<rest>.+?)\s*$"
)


def parse_leg(text: str) -> Leg | None:
    """Parse one side of a swap.

        '993.40 USD Coin (USDC)'                  -> 993.40, USD Coin, USDC
        '689224.24 SelfMade by SP3ND (MADE) 0.07%'-> ..., MADE, pct 0.07
        '1 ETH'                                   -> 1, ETH, ETH
        '31.63M CHOUCHOU (CHOUCHOU) 3.16%'        -> 31630000, CHOUCHOU, 3.16
        '0.23 BNB (~$160.32)'                     -> 0.23, BNB, usd 160.32
    """
    if not text:
        return None
    text = text.strip()
    m = RE_LEG.match(text)
    if not m:
        return None

    leg = Leg(amount=to_float(m.group("amt"), m.group("suf")))
    rest = m.group("rest").strip()

    # Trailing percentage is the share of supply this trade moved.
    pm = re.search(r"(" + NUM + r")\s*%\s*$", rest)
    if pm:
        leg.pct_supply = to_float(pm.group(1))
        rest = rest[: pm.start()].strip()

    # A parenthetical is either the ticker or a USD figure.
    sym = None
    for pm2 in re.finditer(r"\(([^)]*)\)", rest):
        inner = pm2.group(1).strip()
        if "$" in inner:
            leg.usd = find_usd_in(inner)
        elif inner and not sym:
            sym = inner
    rest = re.sub(r"\([^)]*\)", " ", rest).strip()
    rest = re.sub(r"\s{2,}", " ", rest)

    leg.name = rest or None
    # "1 ETH" has no parenthetical, so the name doubles as the ticker.
    leg.symbol = (sym or (rest if rest and len(rest) <= 12 and " " not in rest else None))
    if leg.symbol:
        leg.symbol = leg.symbol.strip().upper()
    return leg


def guess_side(text: str) -> str | None:
    """Fallback only — prefer deriving side from which leg is the quote asset."""
    low = text.lower()
    for w in ("sold", "sell", "sells", "dumped", "exited", "exit", "🔴", "🟥", "📉"):
        if w in low:
            return SELL
    for w in ("bought", "buy", "buys", "aped", "sniped", "🟢", "🟩", "📈"):
        if w in low:
            return BUY
    return None
