from web3 import Web3
from web3.exceptions import ContractLogicError
from decimal import Decimal, getcontext
import requests
import csv
import os
from datetime import datetime, timezone
from collections import defaultdict


def load_local_env_file(path=".env"):
    """Load KEY=VALUE pairs from a local .env file into process env.
    Existing environment variables are preserved.
    """
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ.setdefault(key, value)
    except Exception:
        # Non-fatal: fall back to existing OS environment.
        pass


# Load .env before reading configuration constants.
load_local_env_file()


RPC_URL = os.getenv("RPC_URL", "https://mainnet.base.org")
# Official Base deployment from aerodrome-finance/slipstream README.
NFT_MANAGER_ADDRESS = "0x827922686190790b37229fd06084350E74485b72"
Q96 = Decimal(2) ** 96

# Improve precision for tick math and USD valuation.
getcontext().prec = 80

# Minimal ABI: positions + ownerOf so we can validate token ID existence.
NFT_MANAGER_ABI = [
    {
        "inputs": [],
        "name": "factory",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"internalType": "uint96", "name": "nonce", "type": "uint96"},
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
            {"internalType": "int24", "name": "tickLower", "type": "int24"},
            {"internalType": "int24", "name": "tickUpper", "type": "int24"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
            {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint128", "name": "amount0Max", "type": "uint128"},
                    {"internalType": "uint128", "name": "amount1Max", "type": "uint128"},
                ],
                "internalType": "struct INonfungiblePositionManager.CollectParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "collect",
        "outputs": [
            {"internalType": "uint256", "name": "amount0", "type": "uint256"},
            {"internalType": "uint256", "name": "amount1", "type": "uint256"},
        ],
        "stateMutability": "payable",
        "type": "function",
    },
]

ERC20_METADATA_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

CL_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

CL_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]

STABLE_SYMBOLS = {"USDC", "USDT", "DAI", "USDBC"}
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "WBTC": "wrapped-bitcoin",
    # Most UIs value cbBTC using BTC spot price.
    "CBBTC": "bitcoin",
    "ETH": "ethereum",
    "WETH": "ethereum",
    "AERO": "aerodrome-finance",
}

USDC_ADDRESS = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
CBBTC_ADDRESS = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
# Canonical CL pool for USDC/cbBTC (tick spacing 100).
USDC_CBBTC_POOL_ADDRESS = "0x4e962BB3889Bf030368F56810A9c96B83CB3E778"

TOKEN_ADDRESS_TO_COINGECKO = {
    CBBTC_ADDRESS.lower(): "bitcoin",
}

HISTORY_CSV_PATH = os.getenv("LP_HISTORY_CSV", "lp_history.csv")
WALLET_ADDRESSES = []

# Optional wallet token watchlist (ERC20 balances held directly in wallet).
# You can override via WALLET_TOKEN_ADDRESSES env var (comma-separated).
WALLET_TOKEN_ADDRESSES = [
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
    "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",  # cbBTC
    "0x4200000000000000000000000000000000000006",  # WETH
]

ERC20_BALANCE_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    }
]

PRICE_CACHE = {}


def human_amount(raw_amount, decimals):
    return Decimal(raw_amount) / (Decimal(10) ** Decimal(decimals))


def get_token_meta(w3, token_address):
    token = w3.eth.contract(address=token_address, abi=ERC20_METADATA_ABI)
    try:
        symbol = token.functions.symbol().call()
    except Exception:
        symbol = "UNKNOWN"

    try:
        decimals = int(token.functions.decimals().call())
    except Exception:
        decimals = 18

    return symbol, decimals


def tick_to_sqrt_price_x96(tick):
    return (Decimal("1.0001") ** (Decimal(tick) / Decimal(2))) * Q96


def amount0_delta(sqrt_a_x96, sqrt_b_x96, liquidity):
    lower, upper = sorted([Decimal(sqrt_a_x96), Decimal(sqrt_b_x96)])
    liq = Decimal(liquidity)
    return (liq * (upper - lower) * Q96) / (upper * lower)


def amount1_delta(sqrt_a_x96, sqrt_b_x96, liquidity):
    lower, upper = sorted([Decimal(sqrt_a_x96), Decimal(sqrt_b_x96)])
    liq = Decimal(liquidity)
    return (liq * (upper - lower)) / Q96


def get_pool_from_position(w3, manager_contract, token0, token1, tick_spacing):
    factory_address = manager_contract.functions.factory().call()
    factory = w3.eth.contract(address=factory_address, abi=CL_FACTORY_ABI)
    pool_address = factory.functions.getPool(token0, token1, tick_spacing).call()
    return pool_address


def get_market_price_usd(symbol, token_address=None):
    market_id = None
    if token_address:
        market_id = TOKEN_ADDRESS_TO_COINGECKO.get(token_address.lower())
    if market_id is None:
        market_id = COINGECKO_IDS.get(symbol.upper())
    if not market_id:
        return None

    cache_key = f"coingecko:{market_id}"
    if cache_key in PRICE_CACHE:
        return PRICE_CACHE[cache_key]

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": market_id, "vs_currencies": "usd"}
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            value = Decimal(str(data[market_id]["usd"]))
            PRICE_CACHE[cache_key] = value
            return value
        except Exception:
            continue
    return None


def compute_position_token_amounts(liquidity, tick_lower, tick_upper, current_sqrt_price_x96):
    sqrt_lower = tick_to_sqrt_price_x96(tick_lower)
    sqrt_upper = tick_to_sqrt_price_x96(tick_upper)
    current = Decimal(current_sqrt_price_x96)

    if current <= sqrt_lower:
        amount0_raw = amount0_delta(sqrt_lower, sqrt_upper, liquidity)
        amount1_raw = Decimal(0)
    elif current < sqrt_upper:
        amount0_raw = amount0_delta(current, sqrt_upper, liquidity)
        amount1_raw = amount1_delta(sqrt_lower, current, liquidity)
    else:
        amount0_raw = Decimal(0)
        amount1_raw = amount1_delta(sqrt_lower, sqrt_upper, liquidity)

    return amount0_raw, amount1_raw


def get_live_unclaimed_fees(contract, token_id, owner_address):
    max_u128 = (2 ** 128) - 1
    params = (token_id, owner_address, max_u128, max_u128)
    amount0, amount1 = contract.functions.collect(params).call({"from": owner_address})
    return int(amount0), int(amount1)


def token0_per_token1_from_sqrt_price(sqrt_price_x96, decimals0, decimals1):
    ratio_token1_per_token0 = (Decimal(sqrt_price_x96) / Q96) ** 2
    token1_per_token0 = ratio_token1_per_token0 * (Decimal(10) ** Decimal(decimals0 - decimals1))
    if token1_per_token0 == 0:
        return None
    return Decimal(1) / token1_per_token0


def token0_per_token1_from_tick(tick, decimals0, decimals1):
    token1_per_token0 = (Decimal("1.0001") ** Decimal(tick)) * (Decimal(10) ** Decimal(decimals0 - decimals1))
    if token1_per_token0 == 0:
        return None
    return Decimal(1) / token1_per_token0


def get_cbbtc_price_from_onchain_pool(w3):
    try:
        pool = w3.eth.contract(address=w3.to_checksum_address(USDC_CBBTC_POOL_ADDRESS), abi=CL_POOL_ABI)
        slot0 = pool.functions.slot0().call()
        sqrt_price_x96 = int(slot0[0])
        # USDC per cbBTC (token0 decimals 6, token1 decimals 8)
        return token0_per_token1_from_sqrt_price(sqrt_price_x96, 6, 8)
    except Exception:
        return None


def decimal_to_str(value, places=8):
    if value is None:
        return ""
    quant = Decimal(10) ** -places
    return str(Decimal(value).quantize(quant))


def append_history_snapshot(path, snapshot):
    headers = [
        "timestamp_utc",
        "nft_id",
        "block_number",
        "owner",
        "pool_address",
        "token0_symbol",
        "token1_symbol",
        "token0_address",
        "token1_address",
        "tick_spacing",
        "tick_lower",
        "tick_upper",
        "current_tick",
        "liquidity_raw",
        "principal_token0",
        "principal_token1",
        "fees_token0",
        "fees_token1",
        "total_token0",
        "total_token1",
        "token0_usd",
        "token1_usd",
        "balance_usd",
        "rewards_usd",
        "total_usd",
        "fees_source",
    ]

    file_exists = os.path.exists(path)
    is_empty = True
    if file_exists:
        is_empty = os.path.getsize(path) == 0

    with open(path, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if (not file_exists) or is_empty:
            writer.writeheader()
        writer.writerow(snapshot)


def parse_wallet_addresses():
    env_value = os.getenv("WALLET_ADDRESSES", "").strip()
    if not env_value:
        return WALLET_ADDRESSES

    return [addr.strip() for addr in env_value.split(",") if addr.strip()]


def parse_wallet_token_addresses(w3):
    env_value = os.getenv("WALLET_TOKEN_ADDRESSES", "").strip()
    raw = WALLET_TOKEN_ADDRESSES if not env_value else [a.strip() for a in env_value.split(",") if a.strip()]
    out = []
    for a in raw:
        try:
            out.append(w3.to_checksum_address(a))
        except Exception:
            pass
    # Deduplicate while preserving order
    return list(dict.fromkeys(out))


def get_token_price_usd(symbol, w3=None, token_address=None):
    if symbol.upper() in STABLE_SYMBOLS:
        return Decimal(1)
    price = get_market_price_usd(symbol, token_address)
    if price is not None:
        return price

    # Fallback: value cbBTC using on-chain USDC/cbBTC pool price.
    if w3 is not None and token_address and token_address.lower() == CBBTC_ADDRESS.lower():
        return get_cbbtc_price_from_onchain_pool(w3)

    return None


def get_wallet_spot_assets(w3, wallet, token_addresses):
    assets = []

    # Native ETH on Base
    eth_balance_raw = int(w3.eth.get_balance(wallet))
    eth_balance = human_amount(eth_balance_raw, 18)
    eth_usd = get_token_price_usd("ETH")
    eth_value_usd = eth_balance * eth_usd if eth_usd is not None else None
    if eth_balance > 0:
        assets.append({
            "symbol": "ETH",
            "address": "native",
            "balance": eth_balance,
            "price_usd": eth_usd,
            "value_usd": eth_value_usd,
        })

    for token_address in token_addresses:
        token = w3.eth.contract(address=token_address, abi=ERC20_BALANCE_ABI)
        try:
            bal_raw = int(token.functions.balanceOf(wallet).call())
        except Exception:
            continue

        if bal_raw == 0:
            continue

        symbol, decimals = get_token_meta(w3, token_address)
        bal_human = human_amount(bal_raw, decimals)
        price_usd = get_token_price_usd(symbol, w3=w3, token_address=token_address)
        value_usd = bal_human * price_usd if price_usd is not None else None

        assets.append({
            "symbol": symbol,
            "address": token_address,
            "balance": bal_human,
            "price_usd": price_usd,
            "value_usd": value_usd,
        })

    return assets


def get_wallet_position_ids(contract, wallet_address):
    abi = [
        {
            "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [
                {"internalType": "address", "name": "owner", "type": "address"},
                {"internalType": "uint256", "name": "index", "type": "uint256"},
            ],
            "name": "tokenOfOwnerByIndex",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]
    enumerable_contract = contract.w3.eth.contract(address=contract.address, abi=abi)
    balance = int(enumerable_contract.functions.balanceOf(wallet_address).call())
    token_ids = []
    for i in range(balance):
        token_ids.append(int(enumerable_contract.functions.tokenOfOwnerByIndex(wallet_address, i).call()))
    return token_ids


def evaluate_position(w3, contract, nft_id, expected_wallet=None):
    owner = contract.functions.ownerOf(nft_id).call()
    position_data = contract.functions.positions(nft_id).call()

    token0 = position_data[2]
    token1 = position_data[3]
    tick_spacing = position_data[4]
    tick_lower = position_data[5]
    tick_upper = position_data[6]
    liquidity = position_data[7]
    tokens_owed0_cached = int(position_data[10])
    tokens_owed1_cached = int(position_data[11])

    token0_symbol, token0_decimals = get_token_meta(w3, token0)
    token1_symbol, token1_decimals = get_token_meta(w3, token1)

    price_at_lower_tick = token0_per_token1_from_tick(tick_lower, token0_decimals, token1_decimals)
    price_at_upper_tick = token0_per_token1_from_tick(tick_upper, token0_decimals, token1_decimals)
    tick_price_min = min(price_at_lower_tick, price_at_upper_tick)
    tick_price_max = max(price_at_lower_tick, price_at_upper_tick)

    fees_source = "live_collect_call"
    try:
        tokens_owed0, tokens_owed1 = get_live_unclaimed_fees(contract, nft_id, owner)
    except Exception:
        fees_source = "cached_tokensOwed"
        tokens_owed0, tokens_owed1 = tokens_owed0_cached, tokens_owed1_cached

    owed0_human = human_amount(tokens_owed0, token0_decimals)
    owed1_human = human_amount(tokens_owed1, token1_decimals)

    pool_address = get_pool_from_position(w3, contract, token0, token1, tick_spacing)
    pool = w3.eth.contract(address=pool_address, abi=CL_POOL_ABI)
    slot0 = pool.functions.slot0().call()
    sqrt_price_x96 = int(slot0[0])
    current_tick = int(slot0[1])

    principal0_raw, principal1_raw = compute_position_token_amounts(
        liquidity,
        tick_lower,
        tick_upper,
        sqrt_price_x96,
    )

    principal0_human = principal0_raw / (Decimal(10) ** Decimal(token0_decimals))
    principal1_human = principal1_raw / (Decimal(10) ** Decimal(token1_decimals))

    token0_total = principal0_human + owed0_human
    token1_total = principal1_human + owed1_human

    token0_usd = get_token_price_usd(token0_symbol, w3=w3, token_address=token0)
    token1_usd = get_token_price_usd(token1_symbol, w3=w3, token_address=token1)

    if token1_usd is None:
        implied_t0_per_t1 = token0_per_token1_from_sqrt_price(sqrt_price_x96, token0_decimals, token1_decimals)
        if implied_t0_per_t1 is not None and token0_usd is not None:
            token1_usd = implied_t0_per_t1 * token0_usd

    current_pair_price = token0_per_token1_from_sqrt_price(sqrt_price_x96, token0_decimals, token1_decimals)

    principal_usd = None
    rewards_usd = None
    total_usd = None
    if token0_usd is not None and token1_usd is not None:
        principal_usd = (principal0_human * token0_usd) + (principal1_human * token1_usd)
        rewards_usd = (owed0_human * token0_usd) + (owed1_human * token1_usd)
        total_usd = (token0_total * token0_usd) + (token1_total * token1_usd)

    return {
        "wallet": expected_wallet or owner,
        "owner": owner,
        "nft_id": nft_id,
        "pool_address": pool_address,
        "token0_symbol": token0_symbol,
        "token1_symbol": token1_symbol,
        "token0": token0,
        "token1": token1,
        "tick_spacing": tick_spacing,
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "current_tick": current_tick,
        "liquidity": liquidity,
        "tokens_owed0": tokens_owed0,
        "tokens_owed1": tokens_owed1,
        "tokens_owed0_cached": tokens_owed0_cached,
        "tokens_owed1_cached": tokens_owed1_cached,
        "fees_source": fees_source,
        "principal0_human": principal0_human,
        "principal1_human": principal1_human,
        "owed0_human": owed0_human,
        "owed1_human": owed1_human,
        "token0_total": token0_total,
        "token1_total": token1_total,
        "token0_usd": token0_usd,
        "token1_usd": token1_usd,
        "principal_usd": principal_usd,
        "rewards_usd": rewards_usd,
        "total_usd": total_usd,
        "tick_price_min": tick_price_min,
        "tick_price_max": tick_price_max,
        "current_pair_price": current_pair_price,
    }


def track_wallet_portfolio(wallet_addresses):
    # 1. Direct connection to Base public RPC
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 20}))

    if not w3.is_connected():
        print("❌ Failed to connect to Base RPC.")
        print(f"   RPC URL: {RPC_URL}")
        return

    block_number = w3.eth.block_number
    print(f"✅ Connected to Base network (current block: {block_number})")

    # 2. Aerodrome Slipstream NonfungiblePositionManager contract address
    nft_manager_address = w3.to_checksum_address(NFT_MANAGER_ADDRESS)
    code = w3.eth.get_code(nft_manager_address)
    if len(code) == 0:
        print("❌ NonfungiblePositionManager address has no bytecode on Base.")
        print(f"   Address: {nft_manager_address}")
        return

    # 3. Initialize contract
    contract = w3.eth.contract(address=nft_manager_address, abi=NFT_MANAGER_ABI)

    try:
        if not wallet_addresses:
            print("⚠️ No wallet addresses provided.")
            return

        run_timestamp = datetime.now(timezone.utc).isoformat()
        watch_tokens = parse_wallet_token_addresses(w3)

        by_wallet_totals = defaultdict(lambda: {
            "principal_usd": Decimal(0),
            "rewards_usd": Decimal(0),
            "total_usd": Decimal(0),
            "wallet_assets_usd": Decimal(0),
            "combined_usd": Decimal(0),
            "positions": 0,
        })
        global_totals = {
            "principal_usd": Decimal(0),
            "rewards_usd": Decimal(0),
            "total_usd": Decimal(0),
            "wallet_assets_usd": Decimal(0),
            "combined_usd": Decimal(0),
            "positions": 0,
        }

        for raw_wallet in wallet_addresses:
            wallet = w3.to_checksum_address(raw_wallet)
            print("\n" + "=" * 50)
            print(f"👛 Wallet: {wallet}")
            print("=" * 50)

            wallet_assets = get_wallet_spot_assets(w3, wallet, watch_tokens)
            wallet_assets_usd = Decimal(0)
            print("💼 WALLET ASSETS (spot balances):")
            if wallet_assets:
                for a in wallet_assets:
                    if a["value_usd"] is not None:
                        wallet_assets_usd += a["value_usd"]
                        print(f"   {a['symbol']:<8} : {a['balance']:.8f} (${a['value_usd']:,.2f})")
                    else:
                        print(f"   {a['symbol']:<8} : {a['balance']:.8f} (price unavailable)")
            else:
                print("   No tracked spot assets found.")

            by_wallet_totals[wallet]["wallet_assets_usd"] = wallet_assets_usd
            global_totals["wallet_assets_usd"] += wallet_assets_usd

            token_ids = get_wallet_position_ids(contract, wallet)
            print(f"🔎 Found {len(token_ids)} LP position NFT(s)")

            for nft_id in token_ids:
                data = evaluate_position(w3, contract, nft_id, wallet)

                print("-" * 50)
                print(f"📌 NFT #{nft_id}")
                print(f"   Pool: {data['token0_symbol']}/{data['token1_symbol']}")
                print(f"   Tick: {data['tick_lower']} to {data['tick_upper']} | current {data['current_tick']}")
                print(
                    f"   Price Range ({data['token0_symbol']} per {data['token1_symbol']}): "
                    f"${data['tick_price_min']:,.2f} to ${data['tick_price_max']:,.2f}"
                )
                if data["current_pair_price"] is not None:
                    print(
                        f"   Current Price ({data['token0_symbol']} per {data['token1_symbol']}): "
                        f"${data['current_pair_price']:,.2f}"
                    )
                print(f"   Balance USD: ${data['principal_usd']:,.2f}" if data['principal_usd'] is not None else "   Balance USD: N/A")
                print(f"   Rewards USD: ${data['rewards_usd']:,.2f}" if data['rewards_usd'] is not None else "   Rewards USD: N/A")
                print(f"   Total USD: ${data['total_usd']:,.2f}" if data['total_usd'] is not None else "   Total USD: N/A")

                snapshot = {
                    "timestamp_utc": run_timestamp,
                    "nft_id": str(nft_id),
                    "block_number": str(block_number),
                    "owner": data["owner"],
                    "pool_address": data["pool_address"],
                    "token0_symbol": data["token0_symbol"],
                    "token1_symbol": data["token1_symbol"],
                    "token0_address": data["token0"],
                    "token1_address": data["token1"],
                    "tick_spacing": str(data["tick_spacing"]),
                    "tick_lower": str(data["tick_lower"]),
                    "tick_upper": str(data["tick_upper"]),
                    "current_tick": str(data["current_tick"]),
                    "liquidity_raw": str(data["liquidity"]),
                    "principal_token0": decimal_to_str(data["principal0_human"], 12),
                    "principal_token1": decimal_to_str(data["principal1_human"], 12),
                    "fees_token0": decimal_to_str(data["owed0_human"], 12),
                    "fees_token1": decimal_to_str(data["owed1_human"], 12),
                    "total_token0": decimal_to_str(data["token0_total"], 12),
                    "total_token1": decimal_to_str(data["token1_total"], 12),
                    "token0_usd": decimal_to_str(data["token0_usd"], 8),
                    "token1_usd": decimal_to_str(data["token1_usd"], 8),
                    "balance_usd": decimal_to_str(data["principal_usd"], 8),
                    "rewards_usd": decimal_to_str(data["rewards_usd"], 8),
                    "total_usd": decimal_to_str(data["total_usd"], 8),
                    "fees_source": data["fees_source"],
                }
                append_history_snapshot(HISTORY_CSV_PATH, snapshot)

                if data["principal_usd"] is not None and data["rewards_usd"] is not None and data["total_usd"] is not None:
                    by_wallet_totals[wallet]["principal_usd"] += data["principal_usd"]
                    by_wallet_totals[wallet]["rewards_usd"] += data["rewards_usd"]
                    by_wallet_totals[wallet]["total_usd"] += data["total_usd"]
                    by_wallet_totals[wallet]["positions"] += 1

                    global_totals["principal_usd"] += data["principal_usd"]
                    global_totals["rewards_usd"] += data["rewards_usd"]
                    global_totals["total_usd"] += data["total_usd"]
                    global_totals["positions"] += 1

                if data["liquidity"] == 0:
                    print("   ⚠️ Liquidity is 0. This LP is empty or already withdrawn.")

            wt = by_wallet_totals[wallet]
            wt["combined_usd"] = wt["total_usd"] + wt["wallet_assets_usd"]
            global_totals["combined_usd"] += wt["combined_usd"]
            if wt["positions"] > 0:
                print("-" * 50)
                print("📊 WALLET SUMMARY")
                print(f"   Positions   : {wt['positions']}")
                print(f"   Balance USD : ${wt['principal_usd']:,.2f}")
                print(f"   Rewards USD : ${wt['rewards_usd']:,.2f}")
                print(f"   LP Total USD: ${wt['total_usd']:,.2f}")
                print(f"   Spot USD    : ${wt['wallet_assets_usd']:,.2f}")
                print(f"   Combined USD: ${wt['combined_usd']:,.2f}")
            else:
                print("-" * 50)
                print("📊 WALLET SUMMARY")
                print("   Positions   : 0")
                print("   LP Total USD: $0.00")
                print(f"   Spot USD    : ${wt['wallet_assets_usd']:,.2f}")
                print(f"   Combined USD: ${wt['combined_usd']:,.2f}")

        print("\n" + "=" * 50)
        print("🏦 PORTFOLIO SUMMARY (ALL WALLETS)")
        print("=" * 50)
        print(f"Positions   : {global_totals['positions']}")
        print(f"Balance USD : ${global_totals['principal_usd']:,.2f}")
        print(f"Rewards USD : ${global_totals['rewards_usd']:,.2f}")
        print(f"LP Total USD: ${global_totals['total_usd']:,.2f}")
        print(f"Spot USD    : ${global_totals['wallet_assets_usd']:,.2f}")
        print(f"Combined USD: ${global_totals['combined_usd']:,.2f}")
        print(f"📝 Snapshots appended to CSV: {HISTORY_CSV_PATH}")

    except ContractLogicError:
        print("❌ A contract call reverted while loading one or more positions.")
    except Exception as e:
        print(f"🚨 Failed to read data from contract: {e}")


if __name__ == "__main__":
    wallets = parse_wallet_addresses()
    track_wallet_portfolio(wallets)