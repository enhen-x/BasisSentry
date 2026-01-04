"""
回测运行脚本
"""
import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.backtest.data_loader import DataLoader
from src.backtest.engine import BacktestEngine
from src.utils import setup_logger, logger, format_usdt

async def main():
    parser = argparse.ArgumentParser(description="资金费率套利回测")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="交易对")
    parser.add_argument("--days", type=int, default=30, help="回测天数")
    parser.add_argument("--threshold", type=float, default=0.0005, help="开仓阈值 (0.0005 = 0.05%)")
    parser.add_argument("--initial", type=float, default=1000.0, help="初始资金")
    
    args = parser.parse_args()
    
    setup_logger()
    logger.info("=" * 60)
    logger.info(f"📊 启动回测: {args.symbol}")
    logger.info("=" * 60)
    
    # 1. 获取数据
    loader = DataLoader()
    start_date = datetime.now() - timedelta(days=args.days)
    
    # 先尝试从文件加载
    history = loader.load_from_file(args.symbol)
    
    # 如果没有或者数据不够新，则重新获取
    # (简化逻辑：这里如果加载到了就用，加载不到就获取)
    if history is None or history.empty:
        history = await loader.fetch_funding_history(args.symbol, start_date)
    else:
        # 简单检查一下时间覆盖是否足够，这里略过复杂检查
        pass
        
    if history is None or history.empty:
        logger.error("❌ 无法获取数据，回测终止")
        return

    logger.info(f"📈 数据准备就绪: {len(history)} 条记录")
    
    # 2. 运行回测
    engine = BacktestEngine(initial_capital=args.initial)
    config = {
        'threshold': args.threshold,
        'leverage': 1
    }
    
    result = engine.run(history, config)
    
    # 3. 输出报告
    print()
    print("=" * 60)
    print("📋 回测报告")
    print("=" * 60)
    print(f"交易对: {args.symbol}")
    print(f"回测时间: {result.total_days} 天")
    print(f"初始资金: {format_usdt(args.initial)}")
    print(f"最终资金: {format_usdt(engine.capital)}")
    print("-" * 60)
    print(f"总收入: {format_usdt(result.total_income)}")
    print(f"净利润: {format_usdt(result.net_profit)}")
    print(f"总交易次数: {result.total_trades}")
    print("-" * 60)
    print(f"投资回报率 (ROI): {result.roi*100:.2f}%")
    print(f"年化回报率 (APY): {result.annual_roi*100:.2f}%")
    print(f"最大回撤: {result.max_drawdown*100:.2f}%")
    print("=" * 60)
    
    # 输出最近几笔交易详情
    print("\n🔍 最近 5 笔交易记录:")
    for trade in result.daily_logs[-5:]:
        ts = trade['time']
        type_str = trade['type'].upper()
        if trade['type'] == 'funding':
            print(f"  {ts}: [{type_str}] 费率 {trade['rate']*100:.4f}% -> 收入 {format_usdt(trade['amount'])}")
        elif trade['type'] == 'open':
            print(f"  {ts}: [{type_str}] {trade['side']} -> 成本 {format_usdt(trade['cost'])}")
        elif trade['type'] == 'close':
            print(f"  {ts}: [{type_str}] 平仓 -> 成本 {format_usdt(trade['cost'])}")

if __name__ == "__main__":
    asyncio.run(main())
