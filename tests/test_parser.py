"""Check the tracker parser against the real alerts in samples.py.

    python -m tests.test_parser
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hotgraph.parsers import get_parser  # noqa: E402
from hotgraph.parsers.base import ParseContext  # noqa: E402
from tests.samples import SAMPLES  # noqa: E402


def approx(a, b, tol=1e-6):
    if a is None or b is None:
        return a is b or a == b
    return abs(float(a) - float(b)) <= max(tol, abs(float(b)) * 1e-6)


def main() -> int:
    parser = get_parser("tracker")
    failures = 0

    for s in SAMPLES:
        ctx = ParseContext(source_id="test", ts=1_700_000_000, chain_hint=s["chain_hint"])
        evs = parser(s["text"], ctx)

        print(f"\n=== {s['id']} ===")
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
