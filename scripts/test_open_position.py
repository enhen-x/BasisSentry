"""
测试脚本 - 手动开仓测试
小额测试套利开仓流程
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.strategy.executor import Executor
from src.strategy.selector import Pool
from src.exchange.base import FundingRate, Ticker, OrderBook
from src.utils import setup_logger, logger, format_usdt, format_rate
from datetime import datetime


async def main():
    setup_logger()
    
    logger.info("=" * 70)
    logger.info("🧪 套利开仓测试")
    logger.info("=" * 70)
    logger.info("")
    
    # 测试参数
    TEST_SYMBOL = "AVNT/USDT:USDT"
    TEST_SIZE = Decimal("15")  # 15 USDT
    
    logger.info(f"测试参数:")
    logger.info(f"  交易对: {TEST_SYMBOL}")
    logger.info(f"  仓位大小: {format_usdt(TEST_SIZE)}")
    logger.info("")
    
    # 初始化交易所
    exchange = create_exchange("binance", testnet=False)
    executor = Executor(exchange, load_positions=True)
    
    try:
        # 1. 获取当前数据
        logger.info("📊 获取市场数据...")
        rate = await exchange.get_funding_rate(TEST_SYMBOL)
        ticker = await exchange.get_ticker(TEST_SYMBOL)
        orderbook = await exchange.get_orderbook(TEST_SYMBOL)
        
        logger.info(f"  当前价格: ${ticker.last_price}")
        logger.info(f"  资金费率: {format_rate(rate.rate)}")
        logger.info(f"  买一价: ${orderbook.bids[0][0]}")
        logger.info(f"  卖一价: ${orderbook.asks[0][0]}")
        logger.info("")
        
        # 2. 构建 Pool
        pool = Pool.from_data(rate, ticker, orderbook)
        
        logger.info(f"📈 套利评估:")
        logger.info(f"  价差: {pool.spread:.4%}")
        logger.info(f"  深度: {format_usdt(pool.depth_05pct)}")
        logger.info("")
        
        # 3. 确认开仓
        logger.warning("⚠️  即将执行真实交易!")
        logger.warning(f"   现货买入: ~{TEST_SIZE/2} USDT 的 {pool.base_currency}")
        logger.warning(f"   合约开多: ~{TEST_SIZE/2} USDT 的 {TEST_SYMBOL}")
        logger.warning("")
        
        confirm = input("确认开仓? (输入 YES 继续): ")
        if confirm != "YES":
            logger.info("❌ 取消开仓")
            return
        
        logger.info("")
        logger.info("🚀 开始开仓...")
        
        # 4. 执行开仓
        position = await executor.open_arbitrage(pool, TEST_SIZE)
        
        if position:
            logger.info("")
            logger.info("=" * 70)
            logger.info("✅ 开仓成功!")
            logger.info("=" * 70)
            logger.info(f"  现货: {position.spot_qty:.6f} @ ${position.spot_avg_price:.4f}")
            logger.info(f"  合约: {position.perp_qty:.6f} @ ${position.perp_avg_price:.4f}")
            logger.info(f"  Delta: {position.delta:.6f}")
            logger.info(f"  名义价值: {format_usdt(position.notional_value)}")
            logger.info("=" * 70)
            
            # 5. 显示持仓信息
            logger.info("")
            logger.info("📋 持仓已保存到 data/positions.json")
            logger.info("   运行 'python scripts/run_position_report.py' 查看详情")
        else:
            logger.error("")
            logger.error("❌ 开仓失败，请查看日志")
    
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
