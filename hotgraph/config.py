"""Loaders for config/sources.yaml and config/people.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from .paths import PEOPLE_YAML, ROOT, SOURCES_YAML


def norm_addr(chain: str | None, addr: str | None) -> str | None:
    """EVM addresses are case-insensitive; Solana base58 is not."""
    if not addr:
        return None
    addr = addr.strip()
    return addr.lower() if (chain or "").lower() == "evm" else addr


def norm_handle(handle: str | None) -> str | None:
    if not handle:
        return None
    h = handle.strip().lstrip("@").strip().lower()
    return h or None


@dataclass
class Source:
    id: str
    chat: str
    parser: str
    chain_hint: str | None = None
    enabled: bool = True


@dataclass
class Person:
    name: str
    color: str | None = None
    handles: list[str] = field(default_factory=list)       # normalized
    wallets: list[tuple[str, str]] = field(default_factory=list)  # (chain, addr)


def load_sources(path=None) -> list[Source]:
    with open(path or SOURCES_YAML) as fh:
        data = yaml.safe_load(fh) or {}
    return [
        Source(
            id=row["id"],
            chat=row["chat"],
            parser=row.get("parser") or "tracker",
            chain_hint=row.get("chain_hint"),
            enabled=bool(row.get("enabled", True)),
        )
        for row in (data.get("sources") or [])
    ]


def _people_doc(path=None) -> dict:
    with open(path or PEOPLE_YAML) as fh:
        return yaml.safe_load(fh) or {}


def load_people(path=None) -> list[Person]:
    data = _people_doc(path)
    out: list[Person] = []
    for row in data.get("people") or []:
        handles = [h for h in (norm_handle(x) for x in (row.get("handles") or [])) if h]
        wallets = []
        for w in row.get("wallets") or []:
            chain = (w.get("chain") or "").lower()
            addr = w.get("address") or ""
            if not addr or addr.upper().startswith(("REPLACE", "0XREPLACE", "FULL_ADDRESS")):
                continue
            wallets.append((chain, norm_addr(chain, addr)))
        out.append(Person(name=row["name"], color=row.get("color"), handles=handles, wallets=wallets))
    return out


def load_mode(path=None) -> str:
    """'known_only' (default) or 'all'."""
    mode = (_people_doc(path).get("mode") or "known_only").strip().lower()
    return mode if mode in ("known_only", "all") else "known_only"


class PersonResolver:
    """Maps a trader_key (handle, full address, or 'trunc:AB12...XY34') to a
    person.

    Two sources, DB first:
      - person_map rows created by merges in the UI (authoritative)
      - people.yaml (seed config)

    Bot A keys traders by handle; bots B/C key them by wallet address, often
    printed truncated. Truncated keys match a configured full address by
    prefix AND suffix — and only when exactly one wallet matches, because a
    short prefix/suffix pair colliding across two wallets must not silently
    attribute one person's trades to another.
    """

    def __init__(self, people: list[Person] | None = None, conn=None):
        people = people if people is not None else load_people()
        self._exact: dict[str, str] = {}
        self._wallets: list[tuple[str, str]] = []  # (address, person)
        for p in people:
            for h in p.handles:
                self._exact[h] = p.name
            for _chain, addr in p.wallets:
                if not addr:
                    continue
                self._exact[addr] = p.name
                self._exact[addr.lower()] = p.name
                self._wallets.append((addr, p.name))

        # UI merges override the yaml seed.
        if conn is not None:
            for row in conn.execute("SELECT trader_key, person FROM person_map"):
                key, person = row["trader_key"], row["person"]
                self._exact[key] = person
                self._exact[key.lower()] = person
                if not key.startswith("trunc:") and (key.startswith("0x") or len(key) >= 32):
                    self._wallets.append((key, person))
        self._trunc_cache: dict[str, str | None] = {}

    def resolve(self, trader_key: str | None) -> str | None:
        if not trader_key:
            return None
        hit = self._exact.get(trader_key) or self._exact.get(trader_key.lower())
        if hit:
            return hit
        if trader_key.startswith("trunc:"):
            return self._resolve_trunc(trader_key)
        return None

    def _resolve_trunc(self, key: str) -> str | None:
        if key in self._trunc_cache:
            return self._trunc_cache[key]
        raw = key.removeprefix("trunc:")
        prefix, _, suffix = raw.partition("...")
        if not prefix or not suffix:
            prefix, _, suffix = raw.partition("..")
        person = None
        if prefix and suffix:
            matches = {
                name
                for addr, name in self._wallets
                # EVM addresses compare case-insensitively; Solana base58 is
                # case-sensitive, so compare verbatim first, lowercase second.
                if (addr.startswith(prefix) and addr.endswith(suffix))
                or (addr.lower().startswith(prefix.lower()) and addr.lower().endswith(suffix.lower())
                    and addr.lower().startswith("0x"))
            }
            if len(matches) == 1:
                person = matches.pop()
        self._trunc_cache[key] = person
        return person


def trader_index(people: list[Person] | None = None) -> dict[str, str]:
    """Legacy exact-match view; prefer PersonResolver for new code."""
    return PersonResolver(people)._exact.copy()


def person_colors(people: list[Person] | None = None) -> dict[str, str]:
    people = people if people is not None else load_people()
    return {p.name: p.color for p in people if p.color}


def tg_credentials() -> tuple[int, str]:
    _load_dotenv()
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit(
            "Missing TG_API_ID / TG_API_HASH.\n"
            "  1. Go to https://my.telegram.org -> API development tools\n"
            "  2. Create an app, copy api_id and api_hash\n"
            "  3. cp .env.example .env  and fill them in\n"
        )
    return int(api_id), api_hash


def _load_dotenv() -> None:
    """Minimal .env reader — no hard dependency on python-dotenv."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))
