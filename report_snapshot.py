import csv
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import requests
from collections import deque

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRACKER_PATH = os.path.join(BASE_DIR, "tracker.py")
HISTORY_PATH = os.path.join(BASE_DIR, "portfolio_history.csv")


def d(val: str):
    try:
        return Decimal(val.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def fetch_btc():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin", "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=15,
        )
        r.raise_for_status()
        j = r.json().get("bitcoin", {})
        return Decimal(str(j.get("usd"))), Decimal(str(j.get("usd_24h_change")))
    except Exception:
        return None, None


def run_tracker():
    # Run from skill directory so tracker.py can load local .env reliably.
    res = subprocess.run(["python3", TRACKER_PATH], capture_output=True, text=True, cwd=BASE_DIR)
    if res.returncode != 0:
        raise RuntimeError(res.stderr or res.stdout or "tracker failed")
    return res.stdout


def parse_tracker_output(text: str):
    lp_total = spot = combined = None
    active_nft = None
    active_rewards = None
    active_total = None
    wallets = []

    current_wallet = None
    current_nft = None
    current_range = None
    current_price = None
    nft_rewards = {}
    nft_totals = {}
    nft_ranges = {}
    nft_prices = {}
    nft_wallets = {}

    wallet_combined_queue = deque()

    for raw in text.splitlines():
        line = raw.strip()

        m_wallet = re.match(r"^👛 Wallet:\s*(0x[a-fA-F0-9]{40})$", line)
        if m_wallet:
            current_wallet = m_wallet.group(1)
            current_nft = None
            continue

        m_nft = re.match(r"^📌 NFT #(\d+)$", line)
        if m_nft:
            current_nft = m_nft.group(1)
            current_range = None
            current_price = None
            if current_wallet:
                nft_wallets[current_nft] = current_wallet
            continue

        if current_nft:
            m_range = re.match(r"^Price Range \([^\)]+\): \$([\d,]+(?:\.\d+)?) to \$([\d,]+(?:\.\d+)?)$", line)
            if m_range:
                current_range = (d(m_range.group(1)), d(m_range.group(2)))
                nft_ranges[current_nft] = current_range

            m_price = re.match(r"^Current Price \([^\)]+\): \$([\d,]+(?:\.\d+)?)$", line)
            if m_price:
                current_price = d(m_price.group(1))
                nft_prices[current_nft] = current_price

            m_rewards = re.match(r"^Rewards USD:\s*\$([\d,]+(?:\.\d+)?)$", line)
            if m_rewards:
                nft_rewards[current_nft] = d(m_rewards.group(1))

            m_total = re.match(r"^Total USD:\s*\$([\d,]+(?:\.\d+)?)$", line)
            if m_total:
                nft_totals[current_nft] = d(m_total.group(1))

        m_lp = re.match(r"^LP Total USD:\s*\$([\d,]+(?:\.\d+)?)$", line)
        if m_lp:
            lp_total = d(m_lp.group(1))

        m_spot = re.match(r"^Spot USD\s*:\s*\$([\d,]+(?:\.\d+)?)$", line)
        if m_spot:
            spot = d(m_spot.group(1))

        m_combined = re.match(r"^Combined USD:\s*\$([\d,]+(?:\.\d+)?)$", line)
        if m_combined:
            value = d(m_combined.group(1))
            if current_wallet:
                wallet_combined_queue.append((current_wallet, value))
            combined = value

    seen_wallets = set()
    for wallet, value in wallet_combined_queue:
        if wallet not in seen_wallets:
            wallets.append((wallet, value))
            seen_wallets.add(wallet)

    if nft_totals:
        active_nft = max(nft_totals.items(), key=lambda x: x[1] or Decimal(0))[0]
        active_total = nft_totals.get(active_nft)
        active_rewards = nft_rewards.get(active_nft)

    lower = upper = current = lower_dist_pct = upper_dist_pct = None
    risk_level = "N/A"
    action = "monitor"
    if active_nft and active_nft in nft_ranges and active_nft in nft_prices:
        lower, upper = nft_ranges[active_nft]
        current = nft_prices[active_nft]
        if lower and upper and current:
            lower_dist_pct = ((current - lower) / current) * Decimal(100)
            upper_dist_pct = ((upper - current) / current) * Decimal(100)
            min_dist = min(lower_dist_pct, upper_dist_pct)
            if min_dist <= Decimal("1.0"):
                risk_level = "high"
                action = "prepare reposition"
            elif min_dist <= Decimal("2.5"):
                risk_level = "medium"
                action = "monitor closely"
            else:
                risk_level = "low"
                action = "hold"

    return {
        "lp_total_usd": lp_total,
        "spot_usd": spot,
        "combined_usd": combined,
        "active_nft_id": active_nft,
        "active_rewards_usd": active_rewards,
        "active_total_usd": active_total,
        "wallets": wallets[:2],
        "active_lower": lower,
        "active_upper": upper,
        "active_price": current,
        "lower_dist_pct": lower_dist_pct,
        "upper_dist_pct": upper_dist_pct,
        "oor_risk": risk_level,
        "suggested_action": action,
    }


def load_rows():
    if not os.path.exists(HISTORY_PATH):
        return []
    out = []
    with open(HISTORY_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(r)
    return out


def append_row(row):
    headers = [
        "timestamp_utc",
        "btc_usd",
        "btc_24h_change",
        "lp_total_usd",
        "spot_usd",
        "combined_usd",
        "active_nft_id",
        "active_rewards_usd",
    ]
    exists = os.path.exists(HISTORY_PATH) and os.path.getsize(HISTORY_PATH) > 0
    with open(HISTORY_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            w.writeheader()
        w.writerow(row)


def find_reference(rows, now_dt, hours=6):
    if not rows:
        return None
    target = now_dt - timedelta(hours=hours)

    parsed = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["timestamp_utc"])
            parsed.append((ts, r))
        except Exception:
            continue

    parsed.sort(key=lambda x: x[0])
    eligible = [r for ts, r in parsed if ts <= target]
    if eligible:
        return eligible[-1]
    return parsed[-2][1] if len(parsed) >= 2 else parsed[-1][1]


def pct_change(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / prev * Decimal(100)


def money(x):
    return f"${x:,.2f}" if x is not None else "N/A"


def pct(x):
    return f"{x:+.2f}%" if x is not None else "N/A"


def main():
    btc_usd, btc_chg = fetch_btc()
    out = run_tracker()
    parsed = parse_tracker_output(out)

    now_dt = datetime.now(timezone.utc)
    row = {
        "timestamp_utc": now_dt.isoformat(),
        "btc_usd": str(btc_usd) if btc_usd is not None else "",
        "btc_24h_change": str(btc_chg) if btc_chg is not None else "",
        "lp_total_usd": str(parsed["lp_total_usd"] or ""),
        "spot_usd": str(parsed["spot_usd"] or ""),
        "combined_usd": str(parsed["combined_usd"] or ""),
        "active_nft_id": parsed["active_nft_id"] or "",
        "active_rewards_usd": str(parsed["active_rewards_usd"] or ""),
    }

    rows = load_rows()
    ref = find_reference(rows, now_dt, hours=3) if rows else None
    append_row(row)

    ref_combined = d(ref.get("combined_usd")) if ref else None
    ref_rewards = d(ref.get("active_rewards_usd")) if ref and ref.get("active_nft_id") == (parsed["active_nft_id"] or "") else None

    combined_delta = (parsed["combined_usd"] - ref_combined) if parsed["combined_usd"] is not None and ref_combined is not None else None
    combined_delta_pct = pct_change(parsed["combined_usd"], ref_combined)

    fee_delta_6h = (parsed["active_rewards_usd"] - ref_rewards) if parsed["active_rewards_usd"] is not None and ref_rewards is not None else None

    fee_efficiency = None
    if fee_delta_6h is not None and combined_delta is not None:
        fee_efficiency = fee_delta_6h + combined_delta

    macro_tag = "mixed"
    advice = ""
    if btc_chg is not None and combined_delta_pct is not None:
        if btc_chg > 1 and combined_delta_pct >= 0:
            macro_tag = "bullish"
            advice = "Momentum is positive; hold discipline and avoid chasing spikes."
        elif btc_chg < -1 and combined_delta_pct < 0:
            macro_tag = "defensive"
            advice = "Market is soft; reduce overtrading and prioritize range protection."
        else:
            macro_tag = "mixed"
            advice = "Market is mixed; keep risk balanced and monitor LP range closely."
    else:
        advice = "Keep risk balanced and monitor LP range + fee accrual."

    print("REPORT")
    print(f"BTC_USD={btc_usd if btc_usd is not None else 'N/A'}")
    print(f"BTC_24H_PCT={btc_chg if btc_chg is not None else 'N/A'}")
    print(f"LP_TOTAL_USD={parsed['lp_total_usd'] if parsed['lp_total_usd'] is not None else 'N/A'}")
    print(f"SPOT_USD={parsed['spot_usd'] if parsed['spot_usd'] is not None else 'N/A'}")
    print(f"COMBINED_USD={parsed['combined_usd'] if parsed['combined_usd'] is not None else 'N/A'}")
    print(f"ACTIVE_NFT_ID={parsed['active_nft_id'] or 'N/A'}")
    print(f"ACTIVE_REWARDS_USD={parsed['active_rewards_usd'] if parsed['active_rewards_usd'] is not None else 'N/A'}")
    print(f"FEE_DELTA_3H_USD={fee_delta_6h if fee_delta_6h is not None else 'N/A'}")
    print(f"PORTFOLIO_DELTA_3H_USD={combined_delta if combined_delta is not None else 'N/A'}")
    print(f"PORTFOLIO_DELTA_3H_PCT={combined_delta_pct if combined_delta_pct is not None else 'N/A'}")
    print(f"FEE_EFFECTIVENESS_NET_USD={fee_efficiency if fee_efficiency is not None else 'N/A'}")
    print(f"ACTIVE_LOWER_BOUND={parsed['active_lower'] if parsed['active_lower'] is not None else 'N/A'}")
    print(f"ACTIVE_UPPER_BOUND={parsed['active_upper'] if parsed['active_upper'] is not None else 'N/A'}")
    print(f"ACTIVE_CURRENT_PRICE={parsed['active_price'] if parsed['active_price'] is not None else 'N/A'}")
    print(f"DIST_TO_LOWER_PCT={parsed['lower_dist_pct'] if parsed['lower_dist_pct'] is not None else 'N/A'}")
    print(f"DIST_TO_UPPER_PCT={parsed['upper_dist_pct'] if parsed['upper_dist_pct'] is not None else 'N/A'}")
    print(f"OOR_RISK={parsed['oor_risk']}")
    print(f"SUGGESTED_ACTION={parsed['suggested_action']}")
    print(f"MACRO_TAG={macro_tag}")
    print(f"WALLET_1_COMBINED={parsed['wallets'][0][1] if len(parsed['wallets']) > 0 else 'N/A'}")
    print(f"WALLET_2_COMBINED={parsed['wallets'][1][1] if len(parsed['wallets']) > 1 else 'N/A'}")
    print(f"ADVICE={advice}")


if __name__ == "__main__":
    main()
