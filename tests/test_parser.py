"""Check the tracker parser against the real alerts in samples.py.

    python -m tests.test_parser
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hotgraph.ingest import is_non_trade  # noqa: E402
from hotgraph.parsers import get_parser  # noqa: E402
from hotgraph.parsers.base import ParseContext  # noqa: E402
from tests.samples import SAMPLES  # noqa: E402


def approx(a, b, tol=1e-6):
    if a is None or b is None:
        return a is b or a == b
    return abs(float(a) - float(b)) <= max(tol, abs(float(b)) * 1e-6)


def main() -> int:
    parser = get_parser("tracker")
    generic = get_parser("generic")
    failures = 0

    for s in SAMPLES:
        raw_json = json.dumps(s["raw_json"]) if s.get("raw_json") else None
        ctx = ParseContext(source_id="test", ts=1_700_000_000, chain_hint=s["chain_hint"],
                           raw_json=raw_json)
        evs = parser(s["text"], ctx)
        # Same fallback ingest applies, so a sample that must produce
        # nothing is checked against the loose parser too.
        if not evs and not is_non_trade(s["text"]):
            evs = generic(s["text"], ctx)

        print(f"\n=== {s['id']} ===")
        # Multi-event alerts: one expectation per event, in order.
        if "expect_all" in s:
            wants = s["expect_all"]
            if len(evs) != len(wants):
                print(f"  FAIL: expected {len(wants)} events, got {len(evs)}")
                failures += 1
                continue
            for i, (ev, want_all) in enumerate(zip(evs, wants)):
                print(f"  -- event {i + 1}: {ev.side} {ev.trader_handle} {ev.token_symbol!r}")
                for key, want in want_all.items():
                    got = getattr(ev, key)
                    ok = approx(got, want) if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
                    if not ok:
                        failures += 1
                    print(f"  {'ok  ' if ok else 'FAIL'} {key:<14} got={got!r:<28} want={want!r}")
            continue
        if s["expect"] is None:
            if evs:
                e = evs[0]
                print(f"  FAIL: expected no events, got {e.side} {e.token_symbol!r} {e.token_name!r}")
                failures += 1
            else:
                print("  ok   no events (as expected)")
            continue
        if not evs:
            print("  FAIL: no events parsed")
            failures += 1
            continue

        ev = evs[0]
        for key, want in s["expect"].items():
            got = getattr(ev, key)
            ok = approx(got, want) if isinstance(want, (int, float)) and not isinstance(want, bool) else got == want
            mark = "ok  " if ok else "FAIL"
            if not ok:
                failures += 1
            print(f"  {mark} {key:<14} got={got!r:<28} want={want!r}")

        extras = {
            "token_key": ev.token_key,
            "wallet_addr": ev.wallet_addr,
            "chain_tag": ev.chain_tag,
        }
        print(f"       (also: {extras})")

    print("\n" + ("ALL PASS" if failures == 0 else f"{failures} FAILURE(S)"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
