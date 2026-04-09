import json
import sys
from decimal import Decimal, InvalidOperation

import requests

POOL_ADDRESS = "0x4e962bb3889bf030368f56810a9c96b83cb3e778"
NETWORK = "base"
URL = f"https://api.geckoterminal.com/api/v2/networks/{NETWORK}/pools/{POOL_ADDRESS}"


def d(val):
    try:
        if val is None:
            return None
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return None


def main():
    try:
        r = requests.get(URL, timeout=20)
        r.raise_for_status()
        payload = r.json().get("data", {})
        attrs = payload.get("attributes", {})
    except Exception as e:
        print(f"ERROR={e}")
        sys.exit(1)

    name = attrs.get("name")
    address = payload.get("id", "").split("_")[-1] if payload.get("id") else POOL_ADDRESS
    price_usd = d(attrs.get("base_token_price_usd"))
    reserve_usd = d(attrs.get("reserve_in_usd"))
    volume_usd = d((attrs.get("volume_usd") or {}).get("h24"))
    transactions_h24 = (attrs.get("transactions") or {}).get("h24") or {}
    buys_h24 = transactions_h24.get("buys")
    sells_h24 = transactions_h24.get("sells")
    price_change_h24 = d((attrs.get("price_change_percentage") or {}).get("h24"))
    pool_created_at = attrs.get("pool_created_at")

    fee_rate = Decimal("0.0005")  # 0.05% for this SlipStream pool
    est_fees_h24 = volume_usd * fee_rate if volume_usd is not None else None
    volume_tvl_ratio = (volume_usd / reserve_usd) if volume_usd is not None and reserve_usd not in (None, 0) else None

    print("AERODROME_VOLUME_REPORT")
    print(f"POOL_NAME={name or 'N/A'}")
    print(f"POOL_ADDRESS={address}")
    print(f"BASE_TOKEN_PRICE_USD={price_usd if price_usd is not None else 'N/A'}")
    print(f"RESERVE_USD={reserve_usd if reserve_usd is not None else 'N/A'}")
    print(f"VOLUME_USD_24H={volume_usd if volume_usd is not None else 'N/A'}")
    print(f"EST_FEES_USD_24H={est_fees_h24 if est_fees_h24 is not None else 'N/A'}")
    print(f"VOLUME_TVL_RATIO_24H={volume_tvl_ratio if volume_tvl_ratio is not None else 'N/A'}")
    print(f"PRICE_CHANGE_PCT_24H={price_change_h24 if price_change_h24 is not None else 'N/A'}")
    print(f"TX_BUYS_24H={buys_h24 if buys_h24 is not None else 'N/A'}")
    print(f"TX_SELLS_24H={sells_h24 if sells_h24 is not None else 'N/A'}")
    print(f"POOL_CREATED_AT={pool_created_at or 'N/A'}")


if __name__ == "__main__":
    main()
