
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
        print("\n=== Canceling All Open Orders ===")
        
        # 1. Spot
        print("\n[Spot] Checking open orders...")
        try:
            # cancel_all_orders isn't always supported on all pairs globally in CCXT simple call,
            # but we can try to fetch open orders and cancel them one by one if needed.
            # For simplicity, let's try to fetch open orders for relevant symbols if possible, 
            # OR just use the 'cancelAllOrders' if supported. 
            # Binance supports cancel all for a symbol. 
            # Iterating all symbols is expensive.
            # Let's just user CCXT's cancel_all_orders if possible, or warns.
            
            # Since we don't know exactly which symbol has orders, we might need to check 'USDC/USDT' specifically 
            # as that was the one failing.
            target_symbols = ["USDC/USDT", "GTC/USDT"] 
            
            for symbol in target_symbols:
                open_orders = await exchange.spot.fetch_open_orders(symbol)
                print(f"  {symbol}: Found {len(open_orders)} open orders.")
                for order in open_orders:
                    await exchange.spot.cancel_order(order['id'], symbol)
                    print(f"    Cancelled Spot Order {order['id']}")
                    
        except Exception as e:
            print(f"❌ Failed to cancel Spot orders: {e}")

        # 2. Perp
        print("\n[Futures] Checking open orders...")
        try:
            # Similar for perps
            target_symbols_perp = ["USDC/USDT:USDT", "GTC/USDT:USDT"]
            
            for symbol in target_symbols_perp:
                open_orders = await exchange.perp.fetch_open_orders(symbol)
                print(f"  {symbol}: Found {len(open_orders)} open orders.")
                for order in open_orders:
                    await exchange.perp.cancel_order(order['id'], symbol)
                    print(f"    Cancelled Perp Order {order['id']}")
                    
        except Exception as e:
             print(f"❌ Failed to cancel Futures orders: {e}")
             
        print("\nDone.")
            
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
