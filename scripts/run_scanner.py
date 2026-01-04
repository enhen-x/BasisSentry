"""
运行脚本 - 扫描器
扫描当前市场资金费率机会
"""
import asyncio
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.strategy import Scanner
from src.utils import setup_logger, config, logger, format_rate, format_usdt


async def main():
    """扫描市场资金费率机会"""
    setup_logger()
    
    logger.info("=" * 60)
    logger.info("🔍 资金费率扫描器")
    logger.info("=" * 60)
    
    # 创建交易所连接
    exchange_cfg = config.get_exchange_config(config.default_exchange)
    exchange = create_exchange(
        config.default_exchange,
        api_key=exchange_cfg.get("api_key", ""),
        secret=exchange_cfg.get("secret", ""),
        testnet=exchange_cfg.get("testnet", True),
    )
    
    try:
        # 创建扫描器
        scanner = Scanner(exchange)
        
        # 执行扫描
        candidates = await scanner.scan()
        
        # 打印摘要
        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 费率摘要")
        scanner.print_rate_summary()
        
        # 打印 Top N
        logger.info("")
        logger.info("=" * 60)
        if candidates:
            logger.info(f"✅ 发现 {len(candidates)} 个套利机会:")
            logger.info("")
            for i, pool in enumerate(candidates[:10], 1):
                profit_info = f"预期收益={format_usdt(pool.expected_profit or 0)}" if pool.expected_profit else ""
                logger.info(
                    f"  #{i:2d} {pool.symbol:<20} "
                    f"费率={format_rate(pool.funding_rate):>10} | "
                    f"交易量={format_usdt(pool.volume_24h):>12} | "
                    f"深度={format_usdt(pool.depth_05pct):>10} | "
                    f"评分={float(pool.score or 0):>6.4f} {profit_info}"
                )
        else:
            logger.warning("❌ 未发现符合条件的套利机会")
        
        logger.info("=" * 60)
        
    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
