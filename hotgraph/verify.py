"""On-chain verification of tracked holdings, via public RPCs (no API keys).

pct-of-supply needs no decimals handling: balanceOf / totalSupply in raw
units cancels them out.

RPC endpoints come from config/rpc.yaml when present, with defaults for the
majors below. Chains without an endpoint fail soft with a clear message.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import yaml

from .chains import canonical_tag
from .paths import CONFIG_DIR

# Several endpoints per chain, tried in order — public RPCs go down or
# rate-limit routinely, so one bad endpoint must not fail the whole check.
# Sourced from chainlist.org (keyless, no-tracking endpoints preferred).
RPC_DEFAULTS = {
    "ETH": [
        "https://ethereum-rpc.publicnode.com",
        "https://eth.drpc.org",
        "https://public.1rpc.io/eth",
        "https://eth.meowrpc.com",
    ],
    "BSC": [
        "https://bsc-rpc.publicnode.com",
        "https://bsc.drpc.org",
        "https://public.1rpc.io/bnb",
        "https://bsc-dataseed.bnbchain.org",
    ],
    "BASE": [
        "https://base-rpc.publicnode.com",
        "https://base.drpc.org",
        "https://public.1rpc.io/base",
        "https://mainnet.base.org",
    ],
    "ARB": [
        "https://arbitrum-one-rpc.publicnode.com",
        "https://arbitrum.drpc.org",
        "https://public.1rpc.io/arb",
        "https://arb1.arbitrum.io/rpc",
    ],
    "HYPE": [
        "https://rpc.hyperliquid.xyz/evm",
        "https://rpc.hypurrscan.io",
        "https://hyperevm.rpc.sentio.xyz",
        "https://hyperliquid-json-rpc.stakely.io",
    ],
    "RH": [
        "https://rpc.mainnet.chain.robinhood.com",
        "https://robinhood-rpc.publicnode.com",
        "https://robinhood.rpc.blxrbdn.com",
    ],
    "ABS": [
        "https://api.mainnet.abs.xyz",
        "https://abstract.drpc.org",
        "https://abstract.api.onfinality.io/public",
    ],
    "STBL": [
        "https://rpc.stable.xyz",
        "https://stable.drpc.org",
        "https://stable-mainnet.rpc.sentio.xyz",
    ],
    "OP": [
        "https://optimism-rpc.publicnode.com",
        "https://optimism.drpc.org",
        "https://public.1rpc.io/op",
        "https://mainnet.optimism.io",
    ],
    "POLY": [
        "https://polygon-bor-rpc.publicnode.com",
        "https://polygon.drpc.org",
        "https://public.1rpc.io/matic",
        "https://polygon-rpc.com",
    ],
    "AVAX": [
        "https://avalanche-c-chain-rpc.publicnode.com",
        "https://avalanche.drpc.org",
        "https://public.1rpc.io/avax/c",
        "https://api.avax.network/ext/bc/C/rpc",
    ],
    "BLAST": [
        "https://rpc.blast.io",
        "https://blast-rpc.publicnode.com",
        "https://blast.drpc.org",
    ],
    "LINEA": [
        "https://rpc.linea.build",
        "https://linea-rpc.publicnode.com",
        "https://linea.drpc.org",
    ],
    "SONIC": [
        "https://rpc.soniclabs.com",
        "https://sonic-rpc.publicnode.com",
        "https://sonic.drpc.org",
    ],
    "MONAD": [
        "https://rpc.monad.xyz",
        "https://monad.drpc.org",
    ],
    "UNI": [
        "https://mainnet.unichain.org",
        "https://unichain-rpc.publicnode.com",
        "https://unichain.drpc.org",
    ],
    "ZK": [
        "https://mainnet.era.zksync.io",
        "https://zksync.drpc.org",
        "https://public.1rpc.io/zksync2-era",
    ],
    "SCROLL": [
        "https://rpc.scroll.io",
        "https://scroll-rpc.publicnode.com",
        "https://scroll.drpc.org",
    ],
    "MANTLE": [
        "https://rpc.mantle.xyz",
        "https://mantle-rpc.publicnode.com",
        "https://mantle.drpc.org",
    ],
    "BERA": [
        "https://rpc.berachain.com",
        "https://berachain-rpc.publicnode.com",
        "https://berachain.drpc.org",
    ],
    "SEI": [
        "https://evm-rpc.sei-apis.com",
        "https://sei-evm-rpc.publicnode.com",
        "https://sei.drpc.org",
    ],
    "CRO": [
        "https://evm.cronos.org",
        "https://cronos-evm-rpc.publicnode.com",
        "https://cronos.drpc.org",
    ],
    "XLAYER": [
        "https://rpc.xlayer.tech",
        "https://xlayer.drpc.org",
    ],
    "WORLD": [
        "https://worldchain-mainnet.g.alchemy.com/public",
        "https://worldchain.drpc.org",
    ],
    "INK": [
        "https://rpc-gel.inkonchain.com",
        "https://ink.drpc.org",
    ],
    "PLASMA": [
        "https://rpc.plasma.to",
        "https://plasma.drpc.org",
    ],
    "GNOSIS": [
        "https://rpc.gnosischain.com",
        "https://gnosis-rpc.publicnode.com",
        "https://gnosis.drpc.org",
    ],
    "CELO": [
        "https://forno.celo.org",
        "https://celo.drpc.org",
    ],
    "SOL": [
        "https://api.mainnet-beta.solana.com",
        "https://solana-rpc.publicnode.com",
    ],
}

_SIG_BALANCE_OF = "0x70a08231"    # balanceOf(address)
_SIG_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [str(u) for u in v] if isinstance(v, (list, tuple)) else [str(v)]


def rpc_urls_for(chain_tag: str | None, chain: str | None = None) -> list[str]:
    """All endpoints to try for a chain, in order.

    config/rpc.yaml entries (a single URL or a list) come first, then the
    built-in defaults as fallbacks — so an override reorders, it doesn't
    remove the safety net.
    """
    # Aliases fold into the canonical tag, so an alert tagged [ROBINHOOD]
    # and a config entry under MATIC both land on the right list.
    tag = canonical_tag(chain_tag) or ""
    overrides = {}
    path = CONFIG_DIR / "rpc.yaml"
    if path.exists():
        with open(path) as fh:
            overrides = {
                canonical_tag(str(k)): v
                for k, v in ((yaml.safe_load(fh) or {}).get("rpc") or {}).items()
            }
    urls = _as_list(overrides.get(tag)) + _as_list(RPC_DEFAULTS.get(tag))
    if not urls and (chain or "").lower() == "solana":
        urls = _as_list(overrides.get("SOL")) + RPC_DEFAULTS["SOL"]
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


# Public RPCs rate-limit aggressively, and verifying a token fires one call
# per wallet — bursts trip the limit routinely, so retrying is not optional.
# Kept short per endpoint: a persistently limited endpoint is better handled
# by failing over to the next URL in rpc_urls_for than by waiting it out.
_RETRIES = 2
_MAX_WAIT = 15.0

# JSON-RPC rate-limit replies arrive as HTTP 200 with an error body; codes and
# wording vary per provider, so match both.
_RPC_LIMIT_CODES = {429, -32005, -32029, -32097}


def _is_rate_limited(err: dict) -> bool:
    msg = str(err.get("message", "")).lower()
    return (
        err.get("code") in _RPC_LIMIT_CODES
        or "rate limit" in msg
        or "too many request" in msg
    )


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    """POST with retries on rate limiting (HTTP 429/503 or a JSON-RPC
    rate-limit error). Exponential backoff, honoring Retry-After when sent."""
    delay = 0.5
    for attempt in range(_RETRIES + 1):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "HotGraph/0.1"},
        )
        wait = delay
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read())
            if not (isinstance(out.get("error"), dict) and _is_rate_limited(out["error"])):
                return out
            if attempt == _RETRIES:
                return out  # let the caller surface the rpc error message
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempt == _RETRIES:
                raise
            ra = (exc.headers.get("Retry-After") or "").strip()
            if ra.isdigit():
                wait = max(wait, float(ra))
        time.sleep(min(wait, _MAX_WAIT))
        delay *= 2
    raise RuntimeError("unreachable")


@dataclass
class HolderCheck:
    trader_key: str
    balance: float | None = None
    pct: float | None = None       # 0..100
    error: str | None = None


def _evm_call(url: str, to: str, data: str) -> int:
    out = _post_json(url, {
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    })
    if "error" in out:
        raise RuntimeError(out["error"].get("message", "rpc error"))
    return int(out.get("result") or "0x0", 16)


def _verify_evm(url: str, token: str, wallets: list[str], progress=None) -> list[HolderCheck]:
    supply = _evm_call(url, token, _SIG_TOTAL_SUPPLY)
    checks = []
    for i, w in enumerate(wallets):
        c = HolderCheck(trader_key=w)
        try:
            bal = _evm_call(url, token, _SIG_BALANCE_OF + w.lower().replace("0x", "").rjust(64, "0"))
            c.balance = float(bal)
            c.pct = round(bal / supply * 100, 6) if supply else None
        except Exception as exc:
            c.error = str(exc)[:120]
        checks.append(c)
        if progress:
            progress(i + 1, len(wallets))
    return checks


def _verify_sol(url: str, mint: str, wallets: list[str], progress=None) -> list[HolderCheck]:
    out = _post_json(url, {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint],
    })
    if "error" in out:
        raise RuntimeError(out["error"].get("message", "getTokenSupply failed"))
    supply = int(out["result"]["value"]["amount"])

    checks = []
    for i, w in enumerate(wallets):
        c = HolderCheck(trader_key=w)
        try:
            accounts = _post_json(url, {
                "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                "params": [w, {"mint": mint}, {"encoding": "jsonParsed"}],
            })
            if "error" in accounts:
                raise RuntimeError(accounts["error"].get("message", "rpc error"))
            bal = sum(
                int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"])
                for a in accounts["result"]["value"]
            )
            c.balance = float(bal)
            c.pct = round(bal / supply * 100, 6) if supply else None
        except Exception as exc:
            c.error = str(exc)[:120]
        checks.append(c)
        if progress:
            progress(i + 1, len(wallets))
    return checks


def verify_holdings(
    chain: str, chain_tag: str | None, token_key: str, wallets: list[str],
    progress=None,
) -> tuple[list[HolderCheck], str | None]:
    """Check each wallet's real share of supply. Returns (checks, fatal_error).

    `progress(done, total)` is called after each wallet (restarting from 0
    if the check fails over to another endpoint).

    Endpoints are tried in order; the next one is used when an endpoint dies
    outright (supply call fails) or errors on every single wallet. A partial
    result (some wallets checked) is accepted as-is.
    """
    urls = rpc_urls_for(chain_tag, chain)
    if not urls:
        return [], (
            f"No RPC configured for chain '{chain_tag or chain}'. "
            f"Add one under 'rpc:' in config/rpc.yaml."
        )
    last_err = None
    for url in urls:
        if progress:
            progress(0, len(wallets))
        try:
            if chain == "solana":
                checks = _verify_sol(url, token_key, wallets, progress)
            else:
                checks = _verify_evm(url, token_key, wallets, progress)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"[:200]
            continue
        if checks and all(c.error for c in checks):
            last_err = checks[0].error
            continue
        return checks, None
    return [], f"all {len(urls)} RPC endpoint(s) failed — last error: {last_err}"[:250]
