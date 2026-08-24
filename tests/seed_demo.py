"""Load the real sample alerts (plus a few synthetic follow-ups) into the DB so
the pipeline and the graph can be exercised before Telegram is connected.

    python -m tests.seed_demo

The synthetic messages are written in the bots' exact formats and exist to give
the graph multiple traders per token and at least one full exit. Everything
here lands in raw_messages just like a captured message, so ingest/positions
treat it identically. Re-running replaces the demo rows only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hotgraph.db import session as db_session  # noqa: E402
from tests.samples import SAMPLES  # noqa: E402

DAY = 86400
NOW = 1_724_500_000  # fixed so re-runs are deterministic


def _tx_json(host: str, tx64: str) -> str:
    """Minimal raw_json carrying a TX link, the way Telethon entities do.

    urls_from_raw_json() walks any nesting for 'url' keys, so a flat entities
    list is enough to exercise tx-hash extraction and cross-bot dedup.
    """
    return json.dumps({"entities": [{"url": f"https://{host}/tx/0x{tx64}"}]})


# Same layouts as the real alerts, so they exercise the same parser paths.
# Entries are (text, ts) or (text, ts, raw_json).
EXTRA = [
    # A second trader entering MADE, then adding again.
    ("""[SOL] [BUY] - (FOMO BUY) joswe — S: 1
Fomo: joswe
Method: 9xQe...4KtP
➡️ SENT: 4200.00 USD Coin (USDC)
⬅️ RECEIVED: 2913000.00 SelfMade by SP3ND (MADE) 0.30%
📊 MC: $1.42M - Age: 4 days ago""", NOW - 3 * DAY),

    ("""[SOL] [BUY] - (FOMO BUY) @loganlim_x — S: 1
Fomo: @loganlim_x
Method: DF1o...7QBH
➡️ SENT: 2500.00 USD Coin (USDC)
⬅️ RECEIVED: 1650000.00 SelfMade by SP3ND (MADE) 0.17%
📊 MC: $2.10M - Age: 5 days ago""", NOW - 2 * DAY),

    # Logan trims part of MADE but stays in.
    ("""[SOL] dimiNew — S: 1
🟢Swap 0.9 SOL (~$210.00)
   to: 980000.00 SelfMade by SP3ND (MADE) 0.10%
📊 MC: $2.30M - Age: 5 days ago""", NOW - 2 * DAY + 3600),

    ("""[SOL] [SELL] - (FOMO SELL) @loganlim_x — S: 1
Fomo: @loganlim_x
Method: DF1o...7QBH
➡️ SENT: 800000.00 SelfMade by SP3ND (MADE) 0.08%
⬅️ RECEIVED: 1900.00 USD Coin (USDC)
📊 MC: $2.25M - Age: 6 days ago""", NOW - DAY),

    # Joswe fully exits BITBANK — should render grayed out.
    ("""[BASE] joswe — S: 1
🔴Swap 879688538.89 Bitbank (BITBANK) 0.88%
   to: 1.4 ETH (~$4620.00)
📊 Exit (BITBANK) ▼
📈 PnL (1.62x): 0.4 ETH ($1320.00) | ⏱️ 4d
MC: $412,900 - Age: 1 month ago""", NOW - 6 * 3600),

    # A third token with two holders, so the graph has more than two clusters.
    ("""[BSC] dimiNew — S: 1
🟢Swap 1.1 BNB (~$742.00)
   to: 12400000.00 ChouChou (CHOUCHOU) 1.24%
📊 MC: $61,200 - Age: 2 days ago""", NOW - 5 * DAY),

    ("""[BSC] [BUY] - (FOMO BUY) joswe — S: 1
Fomo: joswe
Method: swap
➡️ SENT: 320.00 USD Coin (USDC)
⬅️ RECEIVED: 5100000.00 ChouChou (CHOUCHOU) 0.51%
📊 MC: $64,000 - Age: 2 days ago""", NOW - 4 * DAY),

    # ---- cross-bot merge + dedup scenario ----------------------------------
    # Logan is configured with BOTH the handle @loganlim_x and the wallet
    # 0x1111...aaaa (people.yaml). The same NEWT buy is reported by bot A
    # (handle) and a bot C-style alert (truncated address) with the SAME tx
    # link — it must count once. A second, distinct buy then accumulates.
    # Expected: one Logan/NEWT position at 0.50 + 0.25 = 0.75%.
    ("""[BASE] [BUY] - (FOMO BUY) @loganlim_x — S: 1
Fomo: @loganlim_x
Method: swap
➡️ SENT: 1500.00 USD Coin (USDC)
⬅️ RECEIVED: 50000000.00 Newton (NEWT) 0.50%
📊 MC: $310,000 - Age: 1 day ago
🔗 TX — DEXSCR""", NOW - 12 * 3600,
     _tx_json("basescan.org", "aa11" * 16)),

    ("""[BASE] 0x1111...aaaa — S: 1
Method: swap
➡️ SENT: 1500.00 USD Coin (USDC)
⬅️ RECEIVED: 50000000.00 Newton (NEWT) 0.50%
📊 MC: $310,000 - Age: 1 day ago
TX — DEXT""", NOW - 12 * 3600 + 30,
     _tx_json("basescan.org", "aa11" * 16)),

    ("""[BASE] 0x1111111111111111111111111111111111aaaaaa — S: 1
Method: swap
➡️ SENT: 800.00 USD Coin (USDC)
⬅️ RECEIVED: 25000000.00 Newton (NEWT) 0.25%
📊 MC: $325,000 - Age: 1 day ago
TX — DEXT""", NOW - 6 * 3600,
     _tx_json("basescan.org", "bb22" * 16)),
]


def main() -> None:
    rows: list[tuple[int, str, int, str | None]] = []
    for i, s in enumerate(SAMPLES):
        rows.append((9_000_000 + i, s["text"], NOW - (10 - i) * DAY, None))
    for j, entry in enumerate(EXTRA):
        text, ts = entry[0], entry[1]
        raw_json = entry[2] if len(entry) > 2 else None
        rows.append((9_100_000 + j, text, ts, raw_json))

    with db_session() as conn:
        conn.execute("DELETE FROM raw_messages WHERE source = 'demo'")
        for msg_id, text, ts, raw_json in rows:
            conn.execute(
                """INSERT OR REPLACE INTO raw_messages
                     (source, tg_msg_id, ts, text, raw_json, captured_at)
                   VALUES ('demo', ?, ?, ?, ?, ?)""",
                (msg_id, ts, text, raw_json, int(time.time())),
            )
        n = conn.execute(
            "SELECT COUNT(*) FROM raw_messages WHERE source='demo'"
        ).fetchone()[0]

    print(f"Seeded {n} demo messages into raw_messages (source='demo').")
    print("Next:")
    print("  python -m hotgraph.ingest")
    print("  python -m hotgraph.positions")


if __name__ == "__main__":
    main()
