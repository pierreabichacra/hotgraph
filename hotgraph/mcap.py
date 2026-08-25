"""Current market caps via the free DexScreener API — no key needed.

    GET https://api.dexscreener.com/latest/dex/tokens/<addr>,<addr>,...

accepts multiple addresses per call (any chain, EVM and Solana mixed) but
returns AT MOST ~30 pairs total — and busy tokens trade in several pairs, so
large batches silently starve the tail of the list ("unknown" tokens that are
actually listed). Hence small batches, plus a second pass that queries every
still-missing address individually before we call it unknown.

Fetched caps land in mcap_checks, which overrides the alert-derived figure
per token until a newer alert states one — the same freshest-wins pattern as
on-chain verifications.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/"

# Small enough that a batch's pairs fit the response cap even when every
# token trades in a few pairs.
BATCH = 8

# The endpoint allows 300 requests/min; pacing keeps a big refresh safely
# under it instead of slamming into 429s and burning the retry budget.
PACE = 0.25

_RETRIES = 5
_MAX_WAIT = 30.0


def _get_json(url: str, timeout: float = 12.0) -> dict:
    """GET with retries on 429/5xx (honoring Retry-After) and network blips."""
    delay = 1.0
    for attempt in range(_RETRIES + 1):
        wait = delay
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "HotGraph/0.1"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == _RETRIES:
                raise
            ra = (exc.headers.get("Retry-After") or "").strip()
            if ra.isdigit():
                wait = max(wait, float(ra))
        except urllib.error.URLError:
            # DNS hiccup / transient network error — worth another try.
            if attempt == _RETRIES:
                raise
        time.sleep(min(wait, _MAX_WAIT))
        delay *= 2
    raise RuntimeError("unreachable")


def _best_caps(data: dict) -> dict[str, tuple[float, float, float | None]]:
    """addr_lower -> (liquidity, mcap, fdv): each token's most liquid pair wins.

    Market cap counts circulating supply; FDV counts total supply. They match
    for fully-unlocked tokens and differ where supply is still locked or
    vesting — the page shows both when they diverge.
    """
    best: dict[str, tuple[float, float, float | None]] = {}
    for p in (data or {}).get("pairs") or []:
        base = ((p.get("baseToken") or {}).get("address") or "").strip()
        mcap = p.get("marketCap") or p.get("fdv")
        if not base or not mcap:
            continue
        fdv = p.get("fdv")
        liq = float(((p.get("liquidity") or {}).get("usd")) or 0)
        k = base.lower()
        if k not in best or liq > best[k][0]:
            best[k] = (liq, float(mcap), float(fdv) if fdv else None)
    return best


def fetch_mcaps(
    addresses: list[str], progress=None
) -> tuple[dict[str, float], list[str]]:
    """address -> (market cap USD, FDV USD or None), for every address DexScreener knows.

    Returns (caps, failed) where failed lists addresses whose requests still
    errored after retries. Addresses absent from both are genuinely unknown
    to DexScreener. progress, if given, is called as progress(done, total)
    after every request — total grows when the individual second pass starts.
    """
    caps: dict[str, tuple[float, float | None]] = {}
    failed: list[str] = []
    addrs = [a for a in addresses if a and not a.startswith("sym:")]
    done, total = 0, len(addrs)

    def _tick(n: int) -> None:
        nonlocal done
        done += n
        if progress:
            progress(done, total)

    for i in range(0, len(addrs), BATCH):
        batch = addrs[i : i + BATCH]
        try:
            best = _best_caps(_get_json(DEX_URL + ",".join(batch)))
        except Exception:
            failed.extend(batch)
            _tick(len(batch))
            continue
        for a in batch:
            hit = best.get(a.lower())
            if hit:
                caps[a] = (hit[1], hit[2])
        _tick(len(batch))
        time.sleep(PACE)

    # Second pass: whatever the batches didn't cover, asked for one by one —
    # a single-address call always fits the response cap, so anything still
    # missing after this is truly unlisted.
    missing = [a for a in addrs if a not in caps and a not in failed]
    total += len(missing)
    if progress and missing:
        progress(done, total)
    for a in missing:
        try:
            hit = _best_caps(_get_json(DEX_URL + a)).get(a.lower())
            if hit:
                caps[a] = (hit[1], hit[2])
        except Exception:
            failed.append(a)
        _tick(1)
        time.sleep(PACE)

    return caps, failed
