"""Real alert layouts. These are the contract the parser must satisfy —
add every new format variant here before changing parser code.

Identities are placeholders: every handle, wallet address, tx hash and
referral code from the original alerts has been swapped for a fake of the
SAME LENGTH (the raw_json entity offsets are UTF-16 exact, so lengths must
not change). Keep it that way — this file ships with the project."""

SAMPLES = [
    {
        "id": "sol_fomo_buy",
        "chain_hint": None,
        "text": """[SOL] [BUY] - (FOMO BUY) @trader_one — S: 1
Fomo: @trader_one
Method: DF1o...7QBH
➡️ SENT: 993.40 USD Coin (USDC)
⬅️ RECEIVED: 689224.24 SelfMade by SP3ND (MADE) 0.07%
📊 MC: $1.38M - Age: 4 days ago
🔗 TX — DEXSCR — BIRDEYE — DFI
Fee: 0.000963 SOL ($0.0908)""",
        "expect": {
            "chain": "solana",
            "side": "BUY",
            "trader_key": "trader_one",
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
        "text": """[BASE] [PRI] - (OUT) alice — S: 1
Method: swap
➡️ SENT: 1 ETH
⬅️ RECEIVED: 879688538.89 Bitbank (BITBANK) 0.88%
TX — DEXT — DFI — DEXSCR
MC: $276,295 - Age: 1 month ago""",
        "expect": {
            "chain": "evm",
            # Tagged "(OUT)" but ETH went out and BITBANK came in: a BUY.
            "side": "BUY",
            "trader_key": "alice",
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
        "text": """[RH] DaveMover — S: 1
🟢Swap 0.5 ETH (~$939.08)
   to: 2.93M Market Maker (MM) 0.31%
📊 Holds 14.27M MM (1.52%) ▲ | $15.9K in (13 buys) | 6d
TX | DFI | GMGN | DXS | $223.1K | 6d""",
        "expect": {
            "chain": "evm",
            "side": "BUY",
            "trader_key": "davemover",
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
        "text": """[RH] bob — S: 1
🔴Swap 2.75M Vladhood (VLAD) 0.27%
   to: 2.27 ETH (~$4.3K)
📊 Exit (VLAD) ▼
📉 PnL (-24.7%): -0.73 ETH ($-1.4K) | ⏱️ 17h
TX | DFI | GMGN | DXS | $1.65M | 19h""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "bob",
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
        "text": """[BSC] EveTest — S: 1
🔴Swap 31.63M CHOUCHOU (CHOUCHOU) 3.16%
   to: 0.23 BNB (~$160.32)
📊 Exit (CHOUCHOU) ▼
📉 PnL (0.58x): -0.17 BNB (-$117.56) | ⏱️ 23h
TX | BSD | DFI | GMGN | DXS | $5.4K | 23h""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "evetest",
            "token_symbol": "CHOUCHOU",
            "pct_supply": 3.16,
            "amount_tokens": 31_630_000.0,
            "amount_usd": 160.32,
            "is_exit": True,
            "pnl_usd": -117.56,
            "pnl_x": 0.58,
        },
    },
    # ---- must produce NOTHING (expect=None) ---------------------------------
    # These all carry a USDC link, and used to become trades of a token called
    # "OUT"/"IN" keyed to USDC's contract — the header tag read as a ticker.
    {
        "id": "eth_quote_swap_none",
        "chain_hint": None,
        "text": """[ETH] [PRI] - (OUT) pnl — S: 1
Method: execute
➡️ SENT: 0.5 ETH
⬅️ RECEIVED: 1965.45 USD Coin (USDC)
TX""",
        "expect": None,
    },
    {
        "id": "eth_stable_swap_none",
        "chain_hint": None,
        "text": """[ETH] [PRI] - (IN) ethFoundation — S: 1
From: 0x2...Ec8
Method: execTransaction
➡️ SENT: 6008547.99 Dai Stablecoin (DAI) 0.13%
⬅️ RECEIVED: 6008547.99 USD Coin (USDC) 0.01%
TX""",
        "expect": None,
    },
    {
        "id": "eth_transfer_none",
        "chain_hint": None,
        # Plain transfers: "ETH To: 0xe...B66" is still ETH, not a token sale.
        "text": """[ETH] [PRI] - (OUT) qerr — S: 1
Method: 0xb9303701
➡️ SENT: 0.001 ETH To: 0xe...B66
➡️ SENT: 46052.55 USD Coin (USDC) To: 0xe...B66
TX""",
        "expect": None,
    },
    {
        "id": "bsc_fee_only_none",
        "chain_hint": None,
        "text": """[BSC] - (OUT) pnl — S: 1
➡️ SENT: 0.14 BNB To: Maestro: Fees
TX""",
        "expect": None,
    },
    {
        "id": "eth_bridge_route_none",
        "chain_hint": None,
        # Every hop is a quote/stable asset — a bridge, not a token trade.
        "text": """[ETH] grace_nin — S: 1
🌉 Bridge (deBridge)
➡️ SENT: 4 ETH (~$7.7K) To: 🌉 deBridge: Crosschain Forwarder
0xB...973 ➡️ SENT: 12.00 Wrapped Ether (WETH) To: 0x9...3E3
0x6...F86 ➡️ SENT: 23.1K Tether USD (USDT) To: 0x9...3E3
0x0...A90 ➡️ SENT: 23.1K USDS Stablecoin (USDS) To: 0x1...f32
DEAD Address ➡️ SENT: 15.4K Dai Stablecoin (DAI) To: 0xA...98c
0x3...341 ➡️ SENT: 15.4K USD Coin (USDC) To: 🌉 deBridge: Crosschain Forwarder
TX | $6.53B | 6mo""",
        "expect": None,
    },
    # ---- multi-leg: fee/hops first, the real token later --------------------
    {
        "id": "bsc_multileg_sell",
        "chain_hint": None,
        "text": """[BSC] - (OUT) frank6 — S: 1
Method: 0xb2ee847c
➡️ SENT: 0.005 BNB To: 0xc...4f8
0x1...24E ➡️ SENT: 0.00 Wrapped BNB (WBNB) To: 0xE...A9c
0xE...A9c ➡️ SENT: 1334.98 潜龙勿用 (潜龙勿用) To: 0xc...4f8
TX — DEXT — DFI — DEXSCR
MC: $2,294,959 - Age: 15 hours ago""",
        "expect": {
            "chain": "evm",
            "side": "SELL",
            "trader_key": "frank6",
            "token_symbol": "潜龙勿用",
            "token_name": "潜龙勿用",
            "amount_tokens": 1334.98,
            "mcap_usd": 2_294_959.0,
        },
    },
    {
        "id": "bsc_from_counterparty_buy",
        "chain_hint": None,
        # "From: 0x6...c5b" after the leg must not eat the "8.19%".
        "text": """[BSC] - (OUT) grace_nin — S: 1
Method: 0xaa5d82c3
⬅️ RECEIVED: 81940498.93 WAGMI (GMI) 8.19% From: 0x6...c5b
➡️ SENT: NFT #4563198 Pancake V3 Positions NFT-V1 (PCS-V3-POS) To: 0x6...c5b
TX — DEXT — DFI — DEXSCR
MC: $82,786 - Age: 8 months ago""",
        "expect": {
            "chain": "evm",
            "side": "BUY",
            "token_symbol": "GMI",
            "token_name": "WAGMI",
            "pct_supply": 8.19,
            "amount_tokens": 81940498.93,
            "mcap_usd": 82_786.0,
        },
    },
    # ---- Layout C: several wallets in one alert -----------------------------
    # As pasted from Telegram with "copy with links": the URLs sit inline.
    {
        "id": "bsc_multi_wallet_sold_inline_links",
        "chain_hint": None,
        "text": """🔴 [BSC] 2 wallets sold 豆豆 (https://bscscan.com/token/0xE5f60718293A4b5C6d7E8f9012345601b803D005) in #118002792 (https://bscscan.com/block/118002792)

1. NickA (https://bscscan.com/address/0xA1b2C3d4E5f60718293A4b5C6d7E8f9012345601) | TX (https://bscscan.com/tx/0x5e6f708192a3b4c55e6f708192a3b4c55e6f708192a3b4c55e6f708192a3b4c5)
├ 🔴 10.01M 酸奶豆糕 (豆豆) (https://bscscan.com/token/0xE5f60718293A4b5C6d7E8f9012345601b803D005) 1.00%
├ to: 0.08 BNB (~$55.50)
└ 📉 PnL -0.12 BNB (0.39x) | ⏱️ 3h

2. P (https://bscscan.com/address/0xB2c3D4e5F60718293a4B5c6D7e8F90123456A702) | TX (https://bscscan.com/tx/0x4d5e6f708192a3b44d5e6f708192a3b44d5e6f708192a3b44d5e6f708192a3b4)
├ 🔴 9.95M 酸奶豆糕 (豆豆) (https://bscscan.com/token/0xE5f60718293A4b5C6d7E8f9012345601b803D005) 0.99%
├ to: 0.078 BNB (~$53.94)
└ 📉 PnL -0.12 BNB (0.38x) | ⏱️ 3h

Σ 0.16 BNB (~$109.44) ← 19.96M (2.00%)
BSD (https://basedbot.app/r/refrewards/token/bsc/0xe5f60718293a4b5c6d7e8f9012345601b803d005) | DFI (https://www.defined.fi/bsc/0xe5f60718293a4b5c6d7e8f9012345601b803d005) | GMGN (https://gmgn.ai/bsc/token/0xe5f60718293a4b5c6d7e8f9012345601b803d005?ref=xxxxxxxx) | DXS (https://dexscreener.com/bsc/0xe5f60718293a4b5c6d7e8f9012345601b803d005) | $5.8K | 3h""",
        "expect_all": [
            {
                "chain": "evm",
                "chain_tag": "BSC",
                "side": "SELL",
                "trader_key": "0xa1b2c3d4e5f60718293a4b5c6d7e8f9012345601",
                "trader_handle": "nicka",
                "wallet_addr": "0xA1b2C3d4E5f60718293A4b5C6d7E8f9012345601",
                "token_key": "0xE5f60718293A4b5C6d7E8f9012345601b803D005",
                "token_symbol": "豆豆",
                "token_name": "酸奶豆糕",
                "amount_tokens": 10_010_000.0,
                "pct_supply": 1.00,
                "amount_usd": 55.50,
                "pnl_x": 0.39,
                "mcap_usd": 5_800.0,
                "tx_hash": "0x5e6f708192a3b4c55e6f708192a3b4c55e6f708192a3b4c55e6f708192a3b4c5",
            },
            {
                "side": "SELL",
                "trader_key": "0xb2c3d4e5f60718293a4b5c6d7e8f90123456a702",
                "trader_handle": "p",
                "token_key": "0xE5f60718293A4b5C6d7E8f9012345601b803D005",
                "amount_tokens": 9_950_000.0,
                "pct_supply": 0.99,
                "amount_usd": 53.94,
                "pnl_x": 0.38,
                "mcap_usd": 5_800.0,
                "tx_hash": "0x4d5e6f708192a3b44d5e6f708192a3b44d5e6f708192a3b44d5e6f708192a3b4",
            },
        ],
    },
    # As captured live: link targets live in the message entities (UTF-16
    # offsets — the leading emoji counts as 2), never in the visible text.
    {
        "id": "bsc_multi_wallet_bought_entities",
        "chain_hint": None,
        "text": """🟢 [BSC] 2 wallets bought 大圣 in #118000583

1. NickA | TX
├ 🟢 0.05 BNB (~$34.75)
└ to: 4.12M What if (大圣) 0.41%

2. P | TX
├ 🟢 0.05 BNB (~$34.75)
└ to: 4.07M What if (大圣) 0.41%

Σ 0.1 BNB (~$69.51) → 8.19M (0.82%)
BSD | DFI | GMGN | DXS | $10.9K | 1m""",
        "raw_json": {
            "entities": [
                {"_": "MessageEntityTextUrl", "offset": 26, "length": 2, "url": "https://bscscan.com/token/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
                {"_": "MessageEntityTextUrl", "offset": 32, "length": 10, "url": "https://bscscan.com/block/118000583"},
                {"_": "MessageEntityTextUrl", "offset": 47, "length": 5, "url": "https://bscscan.com/address/0xA1b2C3d4E5f60718293A4b5C6d7E8f9012345601"},
                {"_": "MessageEntityTextUrl", "offset": 55, "length": 2, "url": "https://bscscan.com/tx/0x2b3c4d5e6f7081922b3c4d5e6f7081922b3c4d5e6f7081922b3c4d5e6f708192"},
                {"_": "MessageEntityTextUrl", "offset": 94, "length": 12, "url": "https://bscscan.com/token/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
                {"_": "MessageEntityTextUrl", "offset": 117, "length": 1, "url": "https://bscscan.com/address/0xB2c3D4e5F60718293a4B5c6D7e8F90123456A702"},
                {"_": "MessageEntityTextUrl", "offset": 121, "length": 2, "url": "https://bscscan.com/tx/0x1a2b3c4d5e6f70811a2b3c4d5e6f70811a2b3c4d5e6f70811a2b3c4d5e6f7081"},
                {"_": "MessageEntityTextUrl", "offset": 160, "length": 12, "url": "https://bscscan.com/token/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
                {"_": "MessageEntityTextUrl", "offset": 216, "length": 3, "url": "https://basedbot.app/r/refrewards/token/bsc/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
                {"_": "MessageEntityTextUrl", "offset": 222, "length": 3, "url": "https://www.defined.fi/bsc/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
                {"_": "MessageEntityTextUrl", "offset": 228, "length": 4, "url": "https://gmgn.ai/bsc/token/0xF60718293a4B5c6D7e8F90123456A702c904E106?ref=xxxxxxxx"},
                {"_": "MessageEntityTextUrl", "offset": 235, "length": 3, "url": "https://dexscreener.com/bsc/0xF60718293a4B5c6D7e8F90123456A702c904E106"},
            ]
        },
        "expect_all": [
            {
                "chain": "evm",
                "side": "BUY",
                "trader_key": "0xa1b2c3d4e5f60718293a4b5c6d7e8f9012345601",
                "trader_handle": "nicka",
                "token_key": "0xF60718293a4B5c6D7e8F90123456A702c904E106",
                "token_symbol": "大圣",
                "token_name": "What if",
                "amount_tokens": 4_120_000.0,
                "pct_supply": 0.41,
                "amount_usd": 34.75,
                "mcap_usd": 10_900.0,
                "tx_hash": "0x2b3c4d5e6f7081922b3c4d5e6f7081922b3c4d5e6f7081922b3c4d5e6f708192",
            },
            {
                "side": "BUY",
                "trader_key": "0xb2c3d4e5f60718293a4b5c6d7e8f90123456a702",
                "trader_handle": "p",
                "amount_tokens": 4_070_000.0,
                "pct_supply": 0.41,
                "amount_usd": 34.75,
                "tx_hash": "0x1a2b3c4d5e6f70811a2b3c4d5e6f70811a2b3c4d5e6f70811a2b3c4d5e6f7081",
            },
        ],
    },
    {
        # Tokens sent to a plain wallet with nothing received: a move between
        # the person's wallets, not a sale. The sender's side is TRANSFER_OUT
        # (Exit: that wallet is empty now) and the linked recipient gets a
        # mirrored TRANSFER_IN so the holding follows the tokens.
        "id": "base_transfer_to_own_wallet",
        "chain_hint": None,
        "text": """[BASE] DaveMover — S: 1
Method: transfer
➡️ SENT: 13.2K Agent Zero Token (A0T) 1.32% To: 0xf...31E
📊 Exit (A0T) ▼
TX | BSD | DFI | GMGN | DXS | $2.28M | 1y""",
        "raw_json": {
            "entities": [
                {"_": "MessageEntityTextUrl", "offset": 7, "length": 9, "url": "https://basescan.org/address/0xC3d4E5f60718293A4b5C6d7E8f9012345601B803"},
                {"_": "MessageEntityTextUrl", "offset": 74, "length": 3, "url": "https://basescan.org/token/0x0718293A4b5C6d7E8f9012345601B803d005F207"},
                {"_": "MessageEntityTextUrl", "offset": 89, "length": 9, "url": "https://basescan.org/address/0xD4e5F60718293a4B5c6D7e8F90123456a702C904"},
                {"_": "MessageEntityTextUrl", "offset": 108, "length": 3, "url": "https://basescan.org/token/0x0718293A4b5C6d7E8f9012345601B803d005F207"},
                {"_": "MessageEntityTextUrl", "offset": 115, "length": 2, "url": "https://basescan.org/tx/0x3c4d5e6f708192a33c4d5e6f708192a33c4d5e6f708192a33c4d5e6f708192a3"},
                {"_": "MessageEntityTextUrl", "offset": 120, "length": 3, "url": "https://basedbot.app/r/refrewards/token/base/0x0718293A4b5C6d7E8f9012345601B803d005F207"},
                {"_": "MessageEntityTextUrl", "offset": 126, "length": 3, "url": "https://www.defined.fi/base/0x0718293A4b5C6d7E8f9012345601B803d005F207"},
                {"_": "MessageEntityTextUrl", "offset": 132, "length": 4, "url": "https://gmgn.ai/base/token/0x0718293A4b5C6d7E8f9012345601B803d005F207?ref=xxxxxxxx"},
                {"_": "MessageEntityTextUrl", "offset": 139, "length": 3, "url": "https://dexscreener.com/base/0x0718293A4b5C6d7E8f9012345601B803d005F207"},
            ]
        },
        "expect_all": [
            {
                "chain": "evm",
                "side": "TRANSFER_OUT",
                "trader_key": "0xc3d4e5f60718293a4b5c6d7e8f9012345601b803",
                "counterparty": "0xd4e5f60718293a4b5c6d7e8f90123456a702c904",
                "token_symbol": "A0T",
                "token_name": "Agent Zero Token",
                "amount_tokens": 13_200.0,
                "pct_supply": 1.32,
                "amount_usd": None,
                "mcap_usd": 2_280_000.0,
                "is_exit": True,
                "tx_hash": "0x3c4d5e6f708192a33c4d5e6f708192a33c4d5e6f708192a33c4d5e6f708192a3",
            },
            {
                "side": "TRANSFER_IN",
                "trader_key": "0xd4e5f60718293a4b5c6d7e8f90123456a702c904",
                "counterparty": "0xc3d4e5f60718293a4b5c6d7e8f9012345601b803",
                "token_symbol": "A0T",
                "pct_supply": 1.32,
                "amount_usd": None,
                "is_exit": False,
            },
        ],
    },
]
