"""
运行脚本 - 持仓报表
显示当前持仓状态和累计收益
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# 将项目根目录添加到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.core.position_store import position_store
from src.core.funding_tracker import funding_tracker
from src.exchange import create_exchange
from src.utils import setup_logger, logger, config, format_usdt, format_rate


async def main():
    """显示持仓报表"""
    setup_logger()
    
    logger.info("=" * 70)
    logger.info("📊 持仓报表")
    logger.info("=" * 70)
    
    # 加载持仓
    positions = position_store.load_all()
    
    if not positions:
        logger.info("暂无持仓")
        logger.info("")
        
        # 显示历史收益
        summary = funding_tracker.get_summary()
        if summary["total_records"] > 0:
            logger.info("-" * 70)
            logger.info("📈 历史费率收入统计")
            logger.info("-" * 70)
            logger.info(f"  总收入: {format_usdt(summary['total_income'])}")
            logger.info(f"  今日收入: {format_usdt(summary['today_income'])}")
            logger.info(f"  结算次数: {summary['total_records']}")
        
        logger.info("=" * 70)
        return
    
    # 显示持仓列表
    logger.info("")
    logger.info("-" * 70)
    logger.info("当前持仓")
    logger.info("-" * 70)
    
    total_value = Decimal(0)
    total_funding = Decimal(0)
    
    for i, (symbol, pos) in enumerate(positions.items(), 1):
        value = pos.notional_value
        total_value += value
        total_funding += pos.funding_earned
        
        # 计算持仓天数
        if pos.opened_at:
            from datetime import datetime
            days = (datetime.now() - pos.opened_at).days
            days_str = f"{days}天"
        else:
            days_str = "-"
        
        logger.info(
            f"  #{i:2d} {symbol:20} | "
            f"仓位: {format_usdt(value):>12} | "
            f"费率收入: {format_usdt(pos.funding_earned):>10} | "
            f"结算期: {pos.funding_periods:>3} | "
            f"持仓: {days_str}"
        )
        logger.info(
            f"      现货: {pos.spot_qty:.6f} @ {pos.spot_avg_price:.2f} | "
            f"合约: {pos.perp_qty:.6f} @ {pos.perp_avg_price:.2f} | "
            f"Delta: {pos.delta:.4f}"
        )
    
    # 显示汇总
    logger.info("")
    logger.info("-" * 70)
    logger.info("汇总")
    logger.info("-" * 70)
    logger.info(f"  持仓数量: {len(positions)}")
    logger.info(f"  总仓位价值: {format_usdt(total_value)}")
    logger.info(f"  累计费率收入: {format_usdt(total_funding)}")
    
    if total_value > 0:
        roi = (total_funding / total_value) * 100
        logger.info(f"  累计收益率: {roi:.4f}%")
    
    # 显示费率收入统计
    logger.info("")
    logger.info("-" * 70)
    logger.info("📈 费率收入统计")
    logger.info("-" * 70)
    
    summary = funding_tracker.get_summary()
    logger.info(f"  总收入: {format_usdt(summary['total_income'])}")
    logger.info(f"  今日收入: {format_usdt(summary['today_income'])}")
    logger.info(f"  结算次数: {summary['total_records']}")
    
    if summary["by_symbol"]:
        logger.info("")
        logger.info("  按交易对统计:")
        for s, income in sorted(summary["by_symbol"].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"    {s:20} {format_usdt(income):>12}")
    
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
