
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.utils import logger, setup_logger

async def main():
    setup_logger()
    print("Connecting to Binance...")
    exchange = create_exchange("binance", testnet=False)
    
    try:
        print("\n=== Closing All Positions & Assets ===")
        
        # 1. Close Futures Positions
        print("\n[Futures] Checking positions...")
        positions = await exchange.perp.fetch_positions()
        active_positions = [p for p in positions if float(p['info']['positionAmt']) != 0]
        
        for p in active_positions:
            symbol = p['symbol']
            amt = float(p['info']['positionAmt'])
            side = "sell" if amt > 0 else "buy" # To close long, sell. To close short, buy.
            print(f"  Closing {symbol} (Size: {amt})...")
            try:
                await exchange.perp.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=abs(amt)
                )
                print(f"  ✅ Closed {symbol}")
            except Exception as e:
                print(f"  ❌ Failed to close {symbol}: {e}")

        # 2. Sell Spot Assets (USDC)
        # We only check USDC for now as that's what we traded
        print("\n[Spot] Checking USDC balance...")
        try:
            usdc_balance = await exchange.spot.fetch_balance()
            usdc_free = float(usdc_balance.get("USDC", {}).get("free", 0))
            if usdc_free > 5: # Min trade size usually 5-10
                print(f"  Found {usdc_free} USDC. Selling to USDT...")
                try:
                    await exchange.spot.create_order(
                        symbol="USDC/USDT",
                        type="market",
                        side="sell",
                        amount=usdc_free
                    )
                    print(f"  ✅ Sold {usdc_free} USDC")
                except Exception as e:
                    print(f"  ❌ Failed to sell USDC: {e}")
            else:
                print(f"  USDC balance {usdc_free} is too small to trade or empty.")
                
        except Exception as e:
             print(f"❌ Failed to check Spot assets: {e}")
             
        print("\nDone.")
            
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
