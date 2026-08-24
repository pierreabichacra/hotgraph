"""On-chain verification of tracked holdings, via public RPCs (no API keys).

pct-of-supply needs no decimals handling: balanceOf / totalSupply in raw
units cancels them out.

RPC endpoints come from config/rpc.yaml when present, with defaults for the
majors below. Chains without an endpoint fail soft with a clear message.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

import yaml

from .paths import CONFIG_DIR

RPC_DEFAULTS = {
    "BSC": "https://bsc-dataseed.binance.org",
    "ETH": "https://eth.llamarpc.com",
    "BASE": "https://mainnet.base.org",
    "ARB": "https://arb1.arbitrum.io/rpc",
    "HYPE": "https://rpc.hyperliquid.xyz/evm",
    "SOL": "https://api.mainnet-beta.solana.com",
    "SOLANA": "https://api.mainnet-beta.solana.com",
}

_SIG_BALANCE_OF = "0x70a08231"    # balanceOf(address)
_SIG_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()


def rpc_url_for(chain_tag: str | None, chain: str | None = None) -> str | None:
    tag = (chain_tag or "").upper()
    overrides = {}
    path = CONFIG_DIR / "rpc.yaml"
    if path.exists():
        with open(path) as fh:
            overrides = {
                str(k).upper(): v
                for k, v in ((yaml.safe_load(fh) or {}).get("rpc") or {}).items()
            }
    url = overrides.get(tag) or RPC_DEFAULTS.get(tag)
    if not url and (chain or "").lower() == "solana":
        url = overrides.get("SOL") or RPC_DEFAULTS["SOL"]
    return url


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "HotGraph/0.1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


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


def _verify_evm(url: str, token: str, wallets: list[str]) -> list[HolderCheck]:
    supply = _evm_call(url, token, _SIG_TOTAL_SUPPLY)
    checks = []
    for w in wallets:
        c = HolderCheck(trader_key=w)
        try:
            bal = _evm_call(url, token, _SIG_BALANCE_OF + w.lower().replace("0x", "").rjust(64, "0"))
            c.balance = float(bal)
            c.pct = round(bal / supply * 100, 6) if supply else None
        except Exception as exc:
            c.error = str(exc)[:120]
        checks.append(c)
    return checks


def _verify_sol(url: str, mint: str, wallets: list[str]) -> list[HolderCheck]:
    out = _post_json(url, {
        "jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint],
    })
    if "error" in out:
        raise RuntimeError(out["error"].get("message", "getTokenSupply failed"))
    supply = int(out["result"]["value"]["amount"])

    checks = []
    for w in wallets:
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
    return checks


def verify_holdings(
    chain: str, chain_tag: str | None, token_key: str, wallets: list[str]
) -> tuple[list[HolderCheck], str | None]:
    """Check each wallet's real share of supply. Returns (checks, fatal_error)."""
    url = rpc_url_for(chain_tag, chain)
    if not url:
        return [], (
            f"No RPC configured for chain '{chain_tag or chain}'. "
            f"Add one under 'rpc:' in config/rpc.yaml."
        )
    try:
        if chain == "solana":
            return _verify_sol(url, token_key, wallets), None
        return _verify_evm(url, token_key, wallets), None
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"[:200]
