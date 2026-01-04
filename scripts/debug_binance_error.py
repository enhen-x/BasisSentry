
import asyncio
import os
import sys
from pathlib import Path
from decimal import Decimal

# Set up path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange.binance import BinanceAdapter
from src.utils import logger, setup_logger

async def main():
    setup_logger()
    logger.info("Starting Debug Script...")

    # Initialize Exchange
    exchange = BinanceAdapter(testnet=False)
    
    try:
        # 1. Check Position Mode
        logger.info("Checking Position Mode...")
        # Access the private method or use implicit ccxt method if available
        # But generally we can just try to fetch position risk or account config
        
        # In ccxt, user_data usually contains info, or fapiPrivateGetPositionSideDual
        try:
            response = await exchange.perp.fapiPrivate_get_positionside_dual()
            logger.info(f"Current Position Mode (Dual Side): {response}")
        except Exception as e:
            logger.error(f"Failed to get position mode: {e}")

        # 2. Check Symbol Existence
        target_symbol_perp = "BULLA/USDT:USDT" # CCXT unified symbol for perp
        target_symbol_spot = "BULLA/USDT"
        
        logger.info(f"Checking symbols: {target_symbol_spot} and {target_symbol_perp}")
        
        # Load markets
        await exchange.spot.load_markets()
        await exchange.perp.load_markets()
        
        spot_exists = target_symbol_spot in exchange.spot.markets
        perp_exists = target_symbol_perp in exchange.perp.markets
        
        logger.info(f"Spot {target_symbol_spot} exists: {spot_exists}")
        logger.info(f"Perp {target_symbol_perp} exists: {perp_exists}")
        
        if not spot_exists:
            logger.warning(f"Spot pair {target_symbol_spot} NOT found!")
            
    finally:
        await exchange.close()

if __name__ == "__main__":
    asyncio.run(main())
