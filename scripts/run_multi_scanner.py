"""
运行脚本 - 多交易所扫描器
跨交易所扫描资金费率，筛选最优套利机会
"""
import asyncio
import argparse
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.strategy.multi_scanner import MultiExchangeScanner
from src.utils import setup_logger, logger


async def main(
    exchanges: list[str] = None,
    testnet: bool = True,
    top_n: int = 10,
):
    """
    跨交易所扫描最优套利机会
    
    Args:
        exchanges: 要扫描的交易所列表
        testnet: 是否使用测试网
        top_n: 显示 Top N 机会
    """
    setup_logger()
    
    logger.info("=" * 70)
    logger.info("🌐 多交易所资金费率扫描器")
    logger.info("=" * 70)
    
    # 创建多交易所扫描器
    scanner = MultiExchangeScanner(
        exchanges=exchanges,
        testnet=testnet,
    )
    
    try:
        # 执行扫描
        opportunities = await scanner.scan_all()
        
        # 打印结果
        scanner.print_summary(opportunities, top_n=top_n)
        
        # 返回最优机会
        if opportunities:
            best = opportunities[0]
            logger.info("")
            logger.info("=" * 70)
            logger.info(f"✅ 推荐操作: 在 {best.exchange.upper()} 对 {best.symbol} 建立套利头寸")
            logger.info("=" * 70)
            
            return best
        else:
            logger.warning("❌ 未发现符合条件的套利机会")
            return None
        
    finally:
        await scanner.close()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="跨交易所资金费率扫描器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_multi_scanner.py                    # 扫描所有交易所
  python run_multi_scanner.py -e binance bybit   # 只扫描 Binance 和 Bybit
  python run_multi_scanner.py --live             # 使用正式网络
  python run_multi_scanner.py --top 20           # 显示 Top 20
        """
    )
    
    parser.add_argument(
        "-e", "--exchanges",
        nargs="+",
        choices=["binance", "bybit", "okx"],
        default=None,
        help="要扫描的交易所 (默认: 全部)",
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="使用正式网络 (默认: 测试网)",
    )
    
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="显示 Top N 机会 (默认: 10)",
    )
    
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    
    asyncio.run(main(
        exchanges=args.exchanges,
        testnet=not args.live,
        top_n=args.top,
    ))
