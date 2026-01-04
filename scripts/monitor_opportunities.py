"""
监控脚本 - 高收益套利机会监控
当发现费率 >= 0.5% 的机会时发送 Telegram 通知
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange
from src.strategy.scanner import Scanner
from src.utils import setup_logger, logger, config, telegram, format_rate, format_usdt


# 监控配置
MIN_RATE_THRESHOLD = Decimal("0.005")  # 0.5% 最低费率
SCAN_INTERVAL = 300  # 5分钟扫描一次
NOTIFY_COOLDOWN = 3600  # 同一交易对1小时内只通知一次


class OpportunityMonitor:
    """套利机会监控器"""
    
    def __init__(self):
        self.notified_symbols = {}  # {symbol: last_notify_time}
        self.exchange = None
        self.scanner = None
    
    async def start(self):
        """启动监控"""
        logger.info("=" * 70)
        logger.info("🔍 套利机会监控器启动")
        logger.info("=" * 70)
        logger.info(f"  最低费率门槛: {format_rate(MIN_RATE_THRESHOLD)}")
        logger.info(f"  扫描间隔: {SCAN_INTERVAL} 秒")
        logger.info(f"  Telegram 通知: {'✅ 已启用' if telegram.enabled else '❌ 未配置'}")
        logger.info("=" * 70)
        logger.info("")
        
        self.exchange = create_exchange("binance", testnet=False)
        self.scanner = Scanner(self.exchange)
        
        try:
            while True:
                await self.scan_and_notify()
                logger.info(f"⏳ 等待 {SCAN_INTERVAL} 秒后再次扫描...")
                logger.info("")
                await asyncio.sleep(SCAN_INTERVAL)
        
        except KeyboardInterrupt:
            logger.info("")
            logger.info("👋 监控已停止")
        finally:
            if self.exchange:
                await self.exchange.close()
    
    async def scan_and_notify(self):
        """扫描并通知"""
        try:
            logger.info(f"🔄 开始扫描... ({datetime.now().strftime('%H:%M:%S')})")
            
            # 扫描市场
            pools = await self.scanner.scan()
            
            if not pools:
                logger.info("  未发现符合条件的机会")
                return
            
            # 筛选高费率机会
            high_rate_pools = [
                p for p in pools
                if abs(p.funding_rate) >= MIN_RATE_THRESHOLD
            ]
            
            if not high_rate_pools:
                logger.info(f"  发现 {len(pools)} 个机会，但费率都低于 {format_rate(MIN_RATE_THRESHOLD)}")
                return
            
            # 按费率排序
            high_rate_pools.sort(key=lambda x: abs(x.funding_rate), reverse=True)
            
            logger.info(f"  🎯 发现 {len(high_rate_pools)} 个高费率机会!")
            
            # 通知前 3 个
            for pool in high_rate_pools[:3]:
                await self.notify_if_needed(pool)
        
        except Exception as e:
            logger.error(f"扫描异常: {e}")
    
    async def notify_if_needed(self, pool):
        """如果需要则发送通知"""
        symbol = pool.symbol
        now = datetime.now().timestamp()
        
        # 检查冷却时间
        last_notify = self.notified_symbols.get(symbol, 0)
        if now - last_notify < NOTIFY_COOLDOWN:
            logger.debug(f"  {symbol} 在冷却期内，跳过通知")
            return
        
        # 计算预期收益
        test_size = Decimal("50")  # 假设 50 USDT 仓位
        daily_income = test_size * abs(pool.funding_rate) * 3  # 每天 3 次
        
        logger.info(f"  📢 发送通知: {symbol} 费率={format_rate(pool.funding_rate)}")
        
        # 发送 Telegram 通知
        await telegram.notify_opportunity(
            exchange="Binance",
            symbol=symbol,
            funding_rate=pool.funding_rate,
            expected_profit=daily_income,
            position_size=test_size,
        )
        
        # 记录通知时间
        self.notified_symbols[symbol] = now


async def main():
    setup_logger()
    monitor = OpportunityMonitor()
    await monitor.start()


if __name__ == "__main__":
    asyncio.run(main())
