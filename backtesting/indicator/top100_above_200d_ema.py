# Top 100 Crypto 200D EMA Analyzer
# --------------------------------
# This script fetches the top 100 cryptocurrencies by market cap, retrieves their historical price data,
# calculates the 200-day Exponential Moving Average (EMA), and determines what percentage are trading above their 200D EMA.
# It uses caching, robust retry logic, and exports results to a CSV for easy analysis.
#
# NEW FEATURE: Historical Date Analysis - You can now specify a target date to analyze historical performance
# instead of just current data. Use --date YYYY-MM-DD to analyze any past date.
#
# DEMO/WALKTHROUGH: Detailed comments are provided throughout to explain each step and function.

import os
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json
import argparse

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


def get_historical_prices(coin_id, use_cache=True, max_retries=5, target_date=None, days_needed=400):
    """
    Fetch historical daily prices for a coin from CoinGecko, using cache if available.
    If not cached, fetch from API with retry logic for rate limits (429 errors).
    
    Args:
        coin_id: CoinGecko coin ID
        use_cache: Whether to use cached data
        max_retries: Maximum number of API retry attempts
        target_date: Target date for analysis (datetime object). If None, uses current date.
        days_needed: Number of days of historical data needed (default 400 to ensure 200+ days for EMA)
    
    Returns a pandas DataFrame with 'date' and 'close' columns, or None if unavailable.
    """
    # Determine the date range needed
    if target_date is None:
        target_date = datetime.now()
    
    # Calculate how many days we need to fetch to ensure we have enough data up to target_date
    end_date = target_date
    start_date = target_date - timedelta(days=days_needed)
    
    # Create cache filename that includes the date range
    cache_filename = f'{coin_id}_usd_{start_date.strftime("%Y%m%d")}_{end_date.strftime("%Y%m%d")}.json'
    cache_path = os.path.join(CACHE_DIR, cache_filename)
    
    # For backward compatibility, also check the old cache format
    old_cache_path = os.path.join(CACHE_DIR, f'{coin_id}_usd_365d.json')
    
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
        # Filter data up to target_date
        df = df[df['date'] <= target_date]
        return df
    elif use_cache and os.path.exists(old_cache_path) and target_date.date() >= (datetime.now() - timedelta(days=365)).date():
        # Use old cache if target date is recent enough
        with open(old_cache_path, 'r') as f:
            data = json.load(f)
        prices = data.get('prices', [])
        if not prices:
            return None
        df = pd.DataFrame(prices, columns=['timestamp', 'close'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['date', 'close']]
        # Filter data up to target_date
        df = df[df['date'] <= target_date]
        return df
    
    # Otherwise, fetch from API with retry logic
    # For historical analysis, we need to use the range endpoint
    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())
    
    url = f'https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range?vs_currency=usd&from={start_timestamp}&to={end_timestamp}'
    
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
            # Filter data up to target_date
            df = df[df['date'] <= target_date]
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


# Add a helper to check if a coin is a stablecoin using CoinGecko's /coins/{id} endpoint
def is_stablecoin(coingecko_id):
    """
    Check if a coin is a stablecoin by inspecting its categories or tags from CoinGecko.
    Returns True if the coin is a stablecoin, False otherwise.
    """
    url = f'https://api.coingecko.com/api/v3/coins/{coingecko_id}'
    try:
        response = requests.get(url)
        if response.status_code != 200:
            return False  # If we can't fetch, assume not a stablecoin
        data = response.json()
        # Check categories and tags for 'stablecoin'
        categories = data.get('categories', [])
        tags = data.get('tags', [])
        if any('stablecoin' in c.lower() for c in categories):
            return True
        if any('stablecoin' in t.lower() for t in tags):
            return True
        return False
    except Exception as e:
        print(f"Error checking stablecoin status for {coingecko_id}: {e}")
        return False


def get_top_n_coins(n=100, max_batches=10):
    """
    Fetch at least n coins from CoinMarketCap, handling pagination and allowing for more batches if needed.
    Returns a list of dicts with 'symbol', 'name', and 'slug'.
    """
    coins = []
    start = 1
    batch_size = 100
    batch_count = 0
    while len(coins) < n * 2 and batch_count < max_batches:
        headers = {
            'Accepts': 'application/json',
            'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
        }
        params = {
            'start': str(start),
            'limit': str(batch_size),
            'convert': 'USD'
        }
        response = requests.get(COINMARKETCAP_URL, headers=headers, params=params)
        data = response.json()
        batch = [
            {
                'symbol': coin['symbol'],
                'name': coin['name'],
                'slug': coin['slug']
            }
            for coin in data['data']
        ]
        if not batch:
            break  # No more coins available
        coins.extend(batch)
        start += batch_size
        batch_count += 1
    return coins


def parse_arguments():
    """
    Parse command line arguments for the script.
    """
    parser = argparse.ArgumentParser(description='Analyze top 100 cryptocurrencies against their 200-day EMA')
    parser.add_argument('--date', type=str, help='Target date for analysis (YYYY-MM-DD). If not provided, uses current date.')
    parser.add_argument('--top-n', type=int, default=100, help='Number of top coins to analyze (default: 100)')
    return parser.parse_args()


def validate_date(date_string):
    """
    Validate and parse the date string.
    Returns a datetime object or None if invalid.
    """
    try:
        parsed_date = datetime.strptime(date_string, '%Y-%m-%d')
        if parsed_date.date() > datetime.now().date():
            print(f"Error: Target date {date_string} is in the future.")
            return None
        if parsed_date.date() < datetime(2013, 1, 1).date():
            print(f"Error: Target date {date_string} is too far in the past. CoinGecko data may not be available.")
            return None
        return parsed_date
    except ValueError:
        print(f"Error: Invalid date format '{date_string}'. Please use YYYY-MM-DD format.")
        return None


def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Validate and set target date
    target_date = None
    date_str = "current"
    if args.date:
        target_date = validate_date(args.date)
        if target_date is None:
            return
        date_str = args.date
    else:
        target_date = datetime.now()
        date_str = target_date.strftime('%Y-%m-%d')

    print(f"\n--- Top {args.top_n} Crypto EMA Analysis for {date_str} ---\n")
    print("If this is your first run, the script will take a long time as it caches data for each coin.\n" \
          "Subsequent runs will be much faster and offline-friendly.\n" \
          "If you want to pre-populate the cache, run the script once and let it finish, or download JSONs to the 'cache' folder.")
    
    # Step 1: Get a large enough list of coins from CoinMarketCap
    coins = []
    analyzed = 0
    idx = 0
    total_processed = 0
    results = []
    batch_size = 100
    fetch_start = 1
    max_batches = 20  # Allow up to 2000 coins if needed
    coingecko_coins = get_coingecko_coins_list()
    above_ema_count = 0
    total = 0
    
    while analyzed < args.top_n and fetch_start < batch_size * max_batches:
        # Fetch next batch if needed
        if idx >= len(coins):
            headers = {
                'Accepts': 'application/json',
                'X-CMC_PRO_API_KEY': COINMARKETCAP_API_KEY,
            }
            params = {
                'start': str(fetch_start),
                'limit': str(batch_size),
                'convert': 'USD'
            }
            response = requests.get(COINMARKETCAP_URL, headers=headers, params=params)
            data = response.json()
            batch = [
                {
                    'symbol': coin['symbol'],
                    'name': coin['name'],
                    'slug': coin['slug']
                }
                for coin in data['data']
            ]
            if not batch:
                break
            coins.extend(batch)
            fetch_start += batch_size
        
        coin = coins[idx]
        idx += 1
        total_processed += 1
        coingecko_id = map_cmc_to_coingecko(coin, coingecko_coins)
        if not coingecko_id:
            print(f"No CoinGecko id found for {coin['name']} ({coin['symbol']})")
            continue
        if is_stablecoin(coingecko_id):
            print(f"Skipping stablecoin: {coin['name']} ({coin['symbol']})")
            continue
        
        print(f"Processing {coin['name']} ({coin['symbol']}) as CoinGecko id '{coingecko_id}' for date {date_str}...")
        df = get_historical_prices(coingecko_id, use_cache=True, target_date=target_date)
        if df is None or len(df) < 2:
            print(f"Not enough data for {coin['name']}")
            continue
        if len(df) < 200:
            print(f"Warning: Only {len(df)} days of data for {coin['name']}, EMA will be less accurate.")
        
        df = calculate_ema(df, span=min(200, len(df)))
        
        # Get the price closest to our target date
        latest = df.iloc[-1]
        is_above = latest['close'] > latest['ema']
        
        if is_above:
            above_ema_count += 1
        total += 1
        analyzed += 1
        
        results.append({
            'Coin Name': coin['name'],
            'Analysis Date': latest['date'].strftime('%Y-%m-%d'),
            'Price on Date': latest['close'],
            '200D EMA': latest['ema'],
            'Above EMA': 'Yes' if is_above else 'No'
        })
        
        # Add delay for new data fetches (not from cache)
        cache_filename = f'{coingecko_id}_usd_{(target_date - timedelta(days=400)).strftime("%Y%m%d")}_{target_date.strftime("%Y%m%d")}.json'
        cache_path = os.path.join(CACHE_DIR, cache_filename)
        old_cache_path = os.path.join(CACHE_DIR, f'{coingecko_id}_usd_365d.json')
        if not os.path.exists(cache_path) and not os.path.exists(old_cache_path):
            time.sleep(15)
    
    if analyzed == 0:
        print("No coins processed.")
        return
    
    percent_above = (above_ema_count / analyzed) * 100
    print(f"\n{percent_above:.2f}% of Top {args.top_n} coins (excluding stablecoins) were trading above their 200D EMA on {date_str}.")
    print(f"Analyzed {analyzed} out of {args.top_n} coins successfully.")
    print(f"Total coins processed (including skipped): {total_processed}")

    # Step 6: Export results to CSV for further analysis or sharing
    df_results = pd.DataFrame(results)
    if args.date:
        output_filename = f'top{args.top_n}_above_200d_ema_results_{args.date}.csv'
    else:
        output_filename = f'top{args.top_n}_above_200d_ema_results_{datetime.now().strftime("%Y-%m-%d")}.csv'
    
    output_path = os.path.join(os.path.dirname(__file__), output_filename)
    df_results.to_csv(output_path, index=False, mode='w')
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
6. The results are exported to CSV files with timestamps for easy review in Excel or Google Sheets.

NEW FEATURES:
7. HISTORICAL ANALYSIS: Use --date YYYY-MM-DD to analyze any past date (e.g., --date 2023-12-31)
8. CUSTOM COUNT: Use --top-n NUMBER to analyze different numbers of top coins (e.g., --top-n 50)

Usage Examples:
- Current analysis: python top100_above_200d_ema.py
- Historical analysis: python top100_above_200d_ema.py --date 2023-06-15
- Top 50 coins on a specific date: python top100_above_200d_ema.py --date 2023-01-01 --top-n 50
- Current top 200 coins: python top100_above_200d_ema.py --top-n 200
""" 