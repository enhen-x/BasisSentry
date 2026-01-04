
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.strategy.scanner import Scanner
from src.utils import config, format_rate, format_usdt

async def main():
    print("Connecting to Binance...")
    exchange = create_exchange("binance", testnet=False)
    
    try:
        print("Fetching rates...")
        rates = await exchange.get_funding_rates()
        # Filter for USDT perps only
        rates = [r for r in rates if r.symbol.endswith(":USDT")] 
        
        print(f"\n=== Searching for ANY Tradable Positive Opportunity ===")
        
        tradable_candidates = []
        
        # Ensure spot markets loaded
        if not exchange.spot.markets:
            await exchange.spot.load_markets()

        for r in rates:
            # Skip negative rates
            if r.rate <= 0:
                continue
                
            symbol = r.symbol
            base = symbol.split("/")[0]
            spot_symbol = f"{base}/USDT"
            
            if spot_symbol in exchange.spot.markets:
                tradable_candidates.append(r)
        
        print(f"Found {len(tradable_candidates)} tradable positive pairs.")
        
        # Sort by rate desc
        tradable_candidates.sort(key=lambda x: x.rate, reverse=True)
        
        print(f"\nTop 10 Tradable Positive Pairs:")
        print(f"{'Symbol':<20} {'Rate':<10} {'Spot':<10}")
        print("-" * 50)
        
        for r in tradable_candidates[:10]:
             base = r.symbol.split("/")[0]
             spot_symbol = f"{base}/USDT"
             print(f"{r.symbol:<20} {format_rate(r.rate):<10} {spot_symbol:<10}")

    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
