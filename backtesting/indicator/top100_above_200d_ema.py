# Top 100 Crypto 200D EMA Analyzer
# --------------------------------
# This script fetches the top 100 cryptocurrencies by market cap, retrieves their historical price data,
# calculates the 200-day Exponential Moving Average (EMA), and determines what percentage are trading above their 200D EMA.
# It uses caching, robust retry logic, and exports results to a CSV for easy analysis.
#
# DEMO/WALKTHROUGH: Detailed comments are provided throughout to explain each step and function.

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

# Ensure the indicator directory exists
os.makedirs(os.path.dirname(__file__), exist_ok=True)
# Create a cache directory for storing historical data to avoid repeated API calls
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

# --- API Constants ---
COINMARKETCAP_API_KEY = 'a54a6db0-cac1-44ea-a8ea-21a3ebe1e588'  # Replace with your own API key
COINMARKETCAP_URL = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'
COINGECKO_COINS_LIST_URL = 'https://api.coingecko.com/api/v3/coins/list'
HISTORICAL_PRICE_URL = 'https://api.coingecko.com/api/v3/coins/{id}/market_chart?vs_currency=usd&days=365'


def get_top_100_coins():
    """
    Fetch the top 100 cryptocurrencies by market cap from CoinMarketCap.
    Returns a list of dicts with 'symbol', 'name', and 'slug'.
    """
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
    }
    params = {
        'start': '1',
        'limit': '100',
        'convert': 'USD'
    }
    response = requests.get(COINMARKETCAP_URL, headers=headers, params=params)
    data = response.json()
    coins = [
        {
            'symbol': coin['symbol'],
            'name': coin['name'],
            'slug': coin['slug']
        }
        for coin in data['data']
    ]
    return coins


def get_coingecko_coins_list():
    """
    Fetch the list of all coins from CoinGecko.
    Returns a list of dicts with 'id', 'symbol', and 'name'.
    """
    response = requests.get(COINGECKO_COINS_LIST_URL)
    return response.json()


def map_cmc_to_coingecko(cmc_coin, coingecko_coins):
    """
    Map a CoinMarketCap coin to its CoinGecko id by matching symbol and name.
    Returns the CoinGecko id or None if not found.
    """
    # First, try to match by symbol (case-insensitive)
    symbol_matches = [c for c in coingecko_coins if c['symbol'].lower() == cmc_coin['symbol'].lower()]
    if len(symbol_matches) == 1:
        return symbol_matches[0]['id']
    # If multiple matches, try to match by name as well
    for c in symbol_matches:
        if c['name'].lower() == cmc_coin['name'].lower():
            return c['id']
    # As a fallback, try to match by name only
    name_matches = [c for c in coingecko_coins if c['name'].lower() == cmc_coin['name'].lower()]
    if name_matches:
        return name_matches[0]['id']
    return None


def get_historical_prices(coin_id, use_cache=True, max_retries=5):
    """
    Fetch historical daily prices for a coin from CoinGecko, using cache if available.
    If not cached, fetch from API with retry logic for rate limits (429 errors).
    Returns a pandas DataFrame with 'date' and 'close' columns, or None if unavailable.
    """
    cache_path = os.path.join(CACHE_DIR, f'{coin_id}_usd_365d.json')
    # Try to load from cache first
    if use_cache and os.path.exists(cache_path):
        with open(cache_path, 'r') as f:
            data = json.load(f)
        prices = data.get('prices', [])
        if not prices:
            return None
        df = pd.DataFrame(prices, columns=['timestamp', 'close'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['date', 'close']]
        return df
    # Otherwise, fetch from API with retry logic
    url = HISTORICAL_PRICE_URL.format(id=coin_id)
    retries = 0
    while retries < max_retries:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            prices = data.get('prices', [])
            if not prices:
                return None
            # Save to cache for future runs
            with open(cache_path, 'w') as f:
                json.dump(data, f)
            df = pd.DataFrame(prices, columns=['timestamp', 'close'])
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df[['date', 'close']]
            return df
        elif response.status_code == 429:
            # Exponential backoff for rate limits
            wait_time = 30 * (2 ** retries)  # 30s, 60s, 120s, ...
            print(f"429 Rate Limit for {coin_id}, retrying in {wait_time} seconds...")
            time.sleep(wait_time)
            retries += 1
        else:
            print(f"Failed to fetch data for {coin_id} (status {response.status_code})")
            return None
    print(f"Max retries exceeded for {coin_id}")
    return None


def calculate_ema(df, span=200):
    """
    Calculate the Exponential Moving Average (EMA) for the given DataFrame.
    Adds a new 'ema' column to the DataFrame.
    """
    df['ema'] = df['close'].ewm(span=span, adjust=False).mean()
    return df


def main():
    print("\n--- Top 100 Crypto EMA Analysis ---\n")
    print("If this is your first run, the script will take a long time as it caches data for each coin.\n" \
          "Subsequent runs will be much faster and offline-friendly.\n" \
          "If you want to pre-populate the cache, run the script once and let it finish, or download JSONs to the 'cache' folder.")
    # Step 1: Get the top 100 coins from CoinMarketCap
    coins = get_top_100_coins()
    # Step 2: Get the full CoinGecko coins list for mapping
    coingecko_coins = get_coingecko_coins_list()
    above_ema_count = 0  # Counter for coins above their 200D EMA
    total = 0            # Counter for successfully analyzed coins
    results = []         # List to store results for CSV export
    for coin in coins:
        # Step 3: Map CoinMarketCap coin to CoinGecko id
        coingecko_id = map_cmc_to_coingecko(coin, coingecko_coins)
        if not coingecko_id:
            print(f"No CoinGecko id found for {coin['name']} ({coin['symbol']})")
            continue
        print(f"Processing {coin['name']} ({coin['symbol']}) as CoinGecko id '{coingecko_id}'...")
        # Step 4: Get historical prices (from cache or API)
        df = get_historical_prices(coingecko_id, use_cache=True)
        if df is None or len(df) < 2:
            print(f"Not enough data for {coin['name']}")
            continue
        if len(df) < 200:
            print(f"Warning: Only {len(df)} days of data for {coin['name']}, EMA will be less accurate.")
        # Step 5: Calculate the 200D EMA (or as many days as available)
        df = calculate_ema(df, span=min(200, len(df)))
        latest = df.iloc[-1]
        is_above = latest['close'] > latest['ema']
        if is_above:
            above_ema_count += 1
        total += 1
        # Store results for CSV export
        results.append({
            'Coin Name': coin['name'],
            'Current Price': latest['close'],
            '200D EMA': latest['ema'],
            'Above EMA': 'Yes' if is_above else 'No'
        })
        # Large delay to avoid rate limits, but skip if using cache
        if not os.path.exists(os.path.join(CACHE_DIR, f'{coingecko_id}_usd_365d.json')):
            time.sleep(15)
    if total == 0:
        print("No coins processed.")
        return
    percent_above = (above_ema_count / total) * 100
    print(f"\n{percent_above:.2f}% of Top 100 coins are trading above their 200D EMA.")
    print(f"Analyzed {total} out of 100 coins successfully.")

    # Step 6: Export results to CSV for further analysis or sharing
    df_results = pd.DataFrame(results)
    output_path = os.path.join(os.path.dirname(__file__), 'top100_above_200d_ema_results.csv')
    df_results.to_csv(output_path, index=False)
    print(f"Results exported to {output_path}")

if __name__ == "__main__":
    main()

"""
Instructions:
1. The script caches historical price data for each coin in the 'cache' folder. On first run, it will take a long time (15s per coin) due to rate limits. Subsequent runs are fast and offline.
2. If you want to pre-populate the cache, run the script once and let it finish, or manually download JSONs from CoinGecko and place them in the 'cache' folder as '{coingecko_id}_usd_365d.json'.
3. If you hit rate limits, the script will automatically retry with exponential backoff.
4. You can run this script weekly for up-to-date results with minimal API calls.
5. Install dependencies: pip install requests pandas
6. The results are exported to 'top100_above_200d_ema_results.csv' for easy review in Excel or Google Sheets.
""" 