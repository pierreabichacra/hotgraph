"""The chains HotGraph knows about — one registry feeding the parser (which
bracket tags mean which chain family), the chain filter in the UI and API,
and the RPC lookup for on-chain verification.

Alerts lead with a bracket tag: [SOL], [BASE], [BSC], [RH]... Bots are not
consistent — one writes [RH], another [ROBINHOOD] — so every chain has a
canonical tag plus aliases, and filtering/verifying goes through the
canonical one. The family decides address handling (EVM addresses are
case-insensitive; Solana base58 is not) and which verifier runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Chain:
    tag: str                 # canonical tag, as the majority of alerts write it
    name: str                # human label for the filter menu
    family: str = "evm"      # 'evm' | 'solana' | 'tron'
    aliases: tuple[str, ...] = ()


CHAINS: tuple[Chain, ...] = (
    Chain("SOL", "Solana", "solana", ("SOLANA",)),
    Chain("ETH", "Ethereum", aliases=("ETHEREUM", "MAINNET")),
    Chain("BSC", "BNB Chain", aliases=("BNB", "BNBCHAIN")),
    Chain("BASE", "Base"),
    Chain("ARB", "Arbitrum", aliases=("ARBITRUM",)),
    Chain("OP", "Optimism", aliases=("OPTIMISM",)),
    Chain("POLY", "Polygon", aliases=("MATIC", "POLYGON", "POL")),
    Chain("AVAX", "Avalanche", aliases=("AVALANCHE",)),
    Chain("BLAST", "Blast"),
    Chain("RH", "Robinhood", aliases=("ROBINHOOD",)),
    Chain("ARC", "Arc"),
    Chain("STBL", "Stable", aliases=("STABLE",)),
    Chain("ABS", "Abstract", aliases=("ABSTRACT",)),
    Chain("HYPE", "HyperEVM", aliases=("HYPEREVM", "HL", "HYPERLIQUID")),
    Chain("LINEA", "Linea"),
    Chain("SONIC", "Sonic"),
    Chain("MONAD", "Monad", aliases=("MON",)),
    Chain("UNI", "Unichain", aliases=("UNICHAIN",)),
    Chain("ZK", "zkSync Era", aliases=("ZKSYNC", "ERA")),
    Chain("SCROLL", "Scroll", aliases=("SCR",)),
    Chain("MANTLE", "Mantle", aliases=("MNT",)),
    Chain("BERA", "Berachain", aliases=("BERACHAIN",)),
    Chain("SEI", "Sei"),
    Chain("CRO", "Cronos", aliases=("CRONOS",)),
    Chain("XLAYER", "X Layer", aliases=("OKX", "X-LAYER")),
    Chain("WORLD", "World Chain", aliases=("WORLDCHAIN", "WLD")),
    Chain("INK", "Ink"),
    Chain("PLASMA", "Plasma", aliases=("XPL",)),
    Chain("GNOSIS", "Gnosis", aliases=("GNO", "XDAI")),
    Chain("CELO", "Celo"),
    Chain("TRON", "Tron", "tron", ("TRX",)),
)

BY_TAG: dict[str, Chain] = {}
for _c in CHAINS:
    BY_TAG[_c.tag] = _c
    for _a in _c.aliases:
        BY_TAG[_a] = _c

# tag (canonical or alias) -> family; what the parser uses.
CHAIN_TAGS: dict[str, str] = {tag: c.family for tag, c in BY_TAG.items()}

FAMILIES = {c.family for c in CHAINS}


def canonical_tag(tag: str | None) -> str | None:
    """'ROBINHOOD' -> 'RH'; unknown tags pass through upper-cased."""
    if not tag:
        return None
    t = tag.strip().upper()
    c = BY_TAG.get(t)
    return c.tag if c else t


def chain_from_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    return CHAIN_TAGS.get(tag.strip().upper())


def parse_filter(spec: str | None) -> tuple[set[str], set[str]]:
    """A filter string ('BASE,RH', 'evm', 'sol,tron') -> (tags, families).

    `tags` holds every raw tag that should match (aliases expanded, so 'RH'
    also matches rows tagged ROBINHOOD); `families` holds whole families to
    match by the `chain` column — asked for explicitly ('evm' keeps old links
    working), or implied when a family has a single chain (SOL is Solana, so
    an untagged solana row still counts).
    """
    tags: set[str] = set()
    families: set[str] = set()
    for part in (spec or "").split(","):
        p = part.strip()
        if not p:
            continue
        if p.lower() in FAMILIES:
            families.add(p.lower())
            continue
        c = BY_TAG.get(p.upper())
        if c is None:
            tags.add(p.upper())      # unknown tag: match it literally
            continue
        tags.add(c.tag)
        tags.update(c.aliases)
        if sum(1 for o in CHAINS if o.family == c.family) == 1:
            families.add(c.family)
    return tags, families


def filter_key(spec: str | None) -> str:
    """Stable cache key for a filter: what was asked for, canonicalised and
    sorted ('ROBINHOOD,base' -> 'BASE,RH'), or 'all'."""
    keys: set[str] = set()
    for part in (spec or "").split(","):
        p = part.strip()
        if p:
            keys.add(p.lower() if p.lower() in FAMILIES else canonical_tag(p))
    return ",".join(sorted(keys)) if keys else "all"


def sql_clause(spec: str | None, chain_col: str = "chain",
               tag_col: str | None = "chain_tag") -> tuple[str, list]:
    """SQL fragment (starts with ' AND ') + params restricting rows to the
    filter, or ('', []) for no filter. Pass tag_col=None for tables without
    a chain_tag column — they can only be narrowed by family."""
    tags, families = parse_filter(spec)
    if not tags and not families:
        return "", []
    ors: list[str] = []
    params: list = []
    if tags and tag_col:
        ors.append(f"UPPER(COALESCE({tag_col}, '')) IN ({','.join('?' * len(tags))})")
        params.extend(sorted(tags))
    if tag_col is None and tags:
        # No tag column: widen to the families the tags belong to.
        families = families | {chain_from_tag(t) or "" for t in tags}
        families.discard("")
    if families:
        ors.append(f"{chain_col} IN ({','.join('?' * len(families))})")
        params.extend(sorted(families))
    return f" AND ({' OR '.join(ors)})", params
