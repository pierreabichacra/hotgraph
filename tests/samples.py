"""Real alerts, verbatim. These are the contract the parser must satisfy —
add every new format variant here before changing parser code."""

SAMPLES = [
    {
        "id": "sol_fomo_buy",
        "chain_hint": None,
        "text": """[SOL] [BUY] - (FOMO BUY) @loganlim_x — S: 1
Fomo: @loganlim_x
Method: DF1o...7QBH
➡️ SENT: 993.40 USD Coin (USDC)
⬅️ RECEIVED: 689224.24 SelfMade by SP3ND (MADE) 0.07%
📊 MC: $1.38M - Age: 4 days ago
🔗 TX — DEXSCR — BIRDEYE — DFI
Fee: 0.000963 SOL ($0.0908)""",
        "expect": {
            "chain": "solana",
            "side": "BUY",
            "trader_key": "loganlim_x",
            "token_symbol": "MADE",
            "token_name": "SelfMade by SP3ND",
            "pct_supply": 0.07,
            "amount_tokens": 689224.24,
            "amount_usd": 993.40,
            "mcap_usd": 1_380_000.0,
            "is_exit": False,
        },
    },
    {
        "id": "base_pri_out_buy",
        "chain_hint": None,
        "text": """[BASE] [PRI] - (OUT) joswe — S: 1
Method: swap
➡️ SENT: 1 ETH
⬅️ RECEIVED: 879688538.89 Bitbank (BITBANK) 0.88%
TX — DEXT — DFI — DEXSCR
MC: $276,295 - Age: 1 month ago""",
        "expect": {
            "chain": "evm",
            # Tagged "(OUT)" but ETH went out and BITBANK came in: a BUY.
            "side": "BUY",
            "trader_key": "joswe",
            "token_symbol": "BITBANK",
            "token_name": "Bitbank",
            "pct_supply": 0.88,
            "amount_tokens": 879688538.89,
            "mcap_usd": 276_295.0,
            "is_exit": False,
        },
    },
    # ---- bot_c "Holds" variant (real, Robinhood chain) ----------------------
    {
        "id": "rh_holds_buy",
        "chain_hint": None,
        "text": """[RH] primeJdid — S: 1
🟢Swap 0.5 ETH (~$939.08)
   to: 2.93M Market Maker (MM) 0.31%
📊 Holds 14.27M MM (1.52%) ▲ | $15.9K in (13 buys) | 6d
TX | DFI | GMGN | DXS | $223.1K | 6d""",
        "expect": {
            "chain": "evm",
            "side": "BUY",
            "trader_key": "primejdid",
            "token_symbol": "MM",
            "pct_supply": 0.31,
            "holds_pct": 1.52,
            "holds_amount": 14_270_000.0,
            "mcap_usd": 223_100.0,   # from the TX footer
        },
    },
    {
        "id": "rh_exit_pnl_percent",
        "chain_hint": None,
        "text": """[RH] joz — S: 1
🔴Swap 2.75M Vladhood (VLAD) 0.27%
   to: 2.27 ETH (~$4.3K)
📊 Exit (VLAD) ▼
📉 PnL (-24.7%): -0.73 ETH ($-1.4K) | ⏱️ 17h
TX | DFI | GMGN | DXS | $1.65M | 19h""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "joz",
            "token_symbol": "VLAD",
            "pct_supply": 0.27,
            "is_exit": True,
            "pnl_usd": -1400.0,
            "pnl_x": 0.753,
            "mcap_usd": 1_650_000.0,
        },
    },
    # ---- address-identified traders (bots B/C) -------------------------------
    # Same layouts, but the "who" slot carries a wallet address instead of a
    # handle: full EVM, truncated, and full Solana forms. Synthetic until real
    # bot B/C messages are captured — replace with verbatim ones then.
    {
        "id": "addr_full_evm_buy",
        "chain_hint": None,
        "text": """[BASE] 0x1111111111111111111111111111111111aaaaaa — S: 1
Method: swap
➡️ SENT: 0.5 ETH
⬅️ RECEIVED: 120000000.00 Bitbank (BITBANK) 0.12%
TX — DEXT — DFI — DEXSCR
MC: $301,000 - Age: 1 month ago""",
        "expect": {
            "chain": "evm",
            "side": "BUY",
            "trader_key": "0x1111111111111111111111111111111111aaaaaa",
            "trader_handle": None,
            "token_symbol": "BITBANK",
            "pct_supply": 0.12,
        },
    },
    {
        "id": "addr_trunc_sell",
        "chain_hint": None,
        "text": """[BSC] 0x1111...aaaa — S: 1
🔴Swap 5.20M CHOUCHOU (CHOUCHOU) 0.52%
   to: 0.11 BNB (~$76.10)
📊 MC: $59,800 - Age: 3 days ago""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "trunc:0x1111...aaaa",
            "trader_handle": None,
            "token_symbol": "CHOUCHOU",
            "pct_supply": 0.52,
        },
    },
    {
        "id": "addr_full_sol_buy",
        "chain_hint": None,
        "text": """[SOL] DF1oLpqmr4kBrWXzFaGyQhJkMnPqRsTuVwXy7QBH — S: 1
Method: swap
➡️ SENT: 500.00 USD Coin (USDC)
⬅️ RECEIVED: 340000.00 SelfMade by SP3ND (MADE) 0.03%
📊 MC: $1.40M - Age: 4 days ago""",
        "expect": {
            "chain": "solana",
            "side": "BUY",
            "trader_key": "DF1oLpqmr4kBrWXzFaGyQhJkMnPqRsTuVwXy7QBH",
            "trader_handle": None,
            "token_symbol": "MADE",
            "pct_supply": 0.03,
        },
    },
    {
        "id": "bsc_exit_sell",
        "chain_hint": None,
        "text": """[BSC] dimiNew — S: 1
🔴Swap 31.63M CHOUCHOU (CHOUCHOU) 3.16%
   to: 0.23 BNB (~$160.32)
📊 Exit (CHOUCHOU) ▼
📉 PnL (0.58x): -0.17 BNB (-$117.56) | ⏱️ 23h
TX | BSD | DFI | GMGN | DXS | $5.4K | 23h""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "diminew",
            "token_symbol": "CHOUCHOU",
            "pct_supply": 3.16,
            "amount_tokens": 31_630_000.0,
            "amount_usd": 160.32,
            "is_exit": True,
            "pnl_usd": -117.56,
            "pnl_x": 0.58,
        },
    },
]
