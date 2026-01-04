"""
测试 Binance API 连接 - 分别测试现货和合约
"""
import asyncio
import ccxt.async_support as ccxt
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
secret = os.getenv('BINANCE_SECRET')

print(f"API Key: {api_key[:20]}..." if api_key else "API Key: NOT SET")
print(f"Secret: {secret[:20]}..." if secret else "Secret: NOT SET")

async def test_spot():
    """测试现货 API"""
    print("\n--- Testing Spot API ---")
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
    })
    
    try:
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)
        print(f"SPOT OK: USDT balance = {usdt}")
    except Exception as e:
        print(f"SPOT ERROR: {e}")
    finally:
        await exchange.close()

async def test_futures():
    """测试合约 API"""
    print("\n--- Testing Futures API ---")
    exchange = ccxt.binanceusdm({
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
    })
    
    try:
        balance = await exchange.fetch_balance()
        usdt = balance.get("USDT", {}).get("free", 0)
        print(f"FUTURES OK: USDT balance = {usdt}")
    except Exception as e:
        print(f"FUTURES ERROR: {e}")
    finally:
        await exchange.close()

async def main():
    await test_spot()
    await test_futures()

if __name__ == "__main__":
    asyncio.run(main())
