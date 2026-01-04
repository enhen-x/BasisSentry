
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.utils import logger, setup_logger, format_usdt

async def main():
    # setup_logger() # Optional: minimal logging
    print("Connecting to Binance...")
    exchange = create_exchange("binance", testnet=False)
    
    try:
        print("\n=== Account Balance Check ===")
        
        # 1. Check Spot Balance
        try:
            spot_usdt = await exchange.get_spot_balance("USDT")
            print(f"💰 Spot Account (现货): {format_usdt(spot_usdt)}")
        except Exception as e:
            print(f"❌ Failed to fetch Spot balance: {e}")

        # 2. Check Perp Balance
        try:
            # Note: CCXT unified might store this differently, checking standard way first
            perp_usdt = await exchange.get_perp_balance("USDT")
            print(f"📈 Futures Account (合约): {format_usdt(perp_usdt)}")
        except Exception as e:
            print(f"❌ Failed to fetch Futures balance: {e}")
            
        # 3. Check Positions
        try:
            print("\n[Futures Positions]")
            positions = await exchange.perp.fetch_positions()
            active_positions = [p for p in positions if float(p['info']['positionAmt']) != 0]
            if not active_positions:
                 print("  No active positions.")
            else:
                 for p in active_positions:
                     symbol = p['symbol']
                     size = p['info']['positionAmt']
                     pnl = p['info']['unRealizedProfit']
                     print(f"  {symbol}: Size={size} PnL={pnl}")
        except Exception as e:
            print(f"❌ Failed to fetch positions: {e}")

        print("=============================")
        
        if spot_usdt < 20:
            print("\n⚠️  Warning: Spot balance is less than $20.")
            print("   Arbitrage requires Buying Spot + Shorting Futures.")
            print("   Please transfer USDT to your [Spot Account].")
            
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
