"""
核心模块 - 套利引擎
主循环：扫描 → 筛选 → 执行 → 监控 → 风控
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.exchange import ExchangeBase, create_exchange
from src.strategy import Scanner, Executor, Pool
from src.core.risk import RiskManager, RiskAction
from src.utils import (
    logger,
    setup_logger,
    config,
    is_trading_time,
    time_to_next_funding,
    format_usdt,
    format_rate,
)


class ArbitrageEngine:
    """
    套利引擎
    主循环控制类
    """
    
    def __init__(self, exchange: Optional[ExchangeBase] = None):
        # 初始化日志
        setup_logger()
        
        # 交易所
        if exchange is None:
            exchange_cfg = config.get_exchange_config(config.default_exchange)
            self.exchange = create_exchange(
                config.default_exchange,
                api_key=exchange_cfg.get("api_key", ""),
                secret=exchange_cfg.get("secret", ""),
                testnet=exchange_cfg.get("testnet", True),
            )
        else:
            self.exchange = exchange
        
        # 核心组件
        self.scanner = Scanner(self.exchange)
        self.executor = Executor(self.exchange)
        self.risk_manager = RiskManager()
        
        # 状态
        self.running = False
        self.capital = config.initial_capital
        
        logger.info(
            f"套利引擎初始化: "
            f"交易所={config.default_exchange}, "
            f"资金={format_usdt(self.capital)}, "
            f"时区={config.trading_timezone}"
        )
    
    async def run(self) -> None:
        """
        主运行循环
        """
        self.running = True
        logger.info("🚀 套利引擎启动")
        
        try:
            while self.running:
                # 检查交易时间
                if not is_trading_time():
                    logger.info("⏰ 非交易时间，等待...")
                    await asyncio.sleep(60)
                    continue
                
                # 检查风险限制
                if self.risk_manager.is_daily_limit_reached(self.capital):
                    logger.warning("⚠️ 达到每日亏损上限，停止交易")
                    break
                
                if self.risk_manager.is_total_limit_reached(self.capital):
                    logger.error("🛑 达到总亏损上限，紧急停止")
                    break
                
                await self._run_cycle()
                
                # 等待下一轮
                await asyncio.sleep(config.scan_interval)
                
        except KeyboardInterrupt:
            logger.info("👋 收到中断信号，优雅退出...")
        except Exception as e:
            logger.exception(f"引擎异常: {e}")
        finally:
            await self.shutdown()
    
    async def _run_cycle(self) -> None:
        """
        执行一轮扫描-执行周期
        """
        logger.debug("=" * 50)
        logger.info(f"⏱️ 距下次结算: {time_to_next_funding() // 60} 分钟")
        
        # 1. 监控现有持仓
        await self._monitor_positions()
        
        # 2. 扫描新机会
        candidates = await self.scanner.scan()
        
        if not candidates:
            logger.info("📭 暂无套利机会")
            return
        
        # 3. 检查是否有可用资金
        available = await self._get_available_capital()
        if available < Decimal("100"):  # 最小 100 USDT
            logger.info(f"💰 可用资金不足: {format_usdt(available)}")
            return
        
        # 4. 执行套利
        best = candidates[0]
        await self._open_position(best, available)
    
    async def _monitor_positions(self) -> None:
        """
        监控现有持仓
        """
        positions = self.executor.get_all_positions()
        
        if not positions:
            return
        
        logger.info(f"📊 监控 {len(positions)} 个持仓")
        
        for pos in positions:
            # 获取当前费率
            rate = self.scanner.get_cached_rate(pos.symbol)
            
            # 获取合约持仓的保证金率
            exchange_pos = await self.exchange.get_position(pos.symbol)
            margin_ratio = exchange_pos.margin_ratio if exchange_pos else None
            
            # 风险检查
            result = self.risk_manager.check(
                position=pos,
                current_rate=rate,
                margin_ratio=margin_ratio,
            )
            
            if result.action == RiskAction.CLOSE:
                logger.warning(f"⚠️ 触发平仓: {pos.symbol} - {result.reason}")
                pnl = await self.executor.close_arbitrage(pos.symbol)
                if pnl and pnl < 0:
                    self.risk_manager.record_loss(pnl)
            
            elif result.action == RiskAction.REDUCE:
                logger.warning(f"⚠️ 触发减仓: {pos.symbol} - {result.reason}")
                # TODO: 实现减仓逻辑
            
            elif result.action == RiskAction.REBALANCE:
                logger.info(f"🔄 触发调仓: {pos.symbol} - {result.reason}")
                await self.executor.rebalance(pos.symbol)
    
    async def _get_available_capital(self) -> Decimal:
        """
        获取可用资金
        """
        # 现货 + 合约可用余额
        spot_balance = await self.exchange.get_spot_balance()
        perp_balance = await self.exchange.get_perp_balance()
        
        total = spot_balance + perp_balance
        
        # 减去已占用
        used = self.executor.get_total_exposure()
        
        # 最大仓位限制
        max_total = self.capital * config.max_position_ratio
        available = min(total, max_total - used)
        
        logger.debug(f"可用资金: {format_usdt(available)} (现货={format_usdt(spot_balance)}, 合约={format_usdt(perp_balance)})")
        
        return max(available, Decimal(0))
    
    async def _open_position(self, pool: Pool, available: Decimal) -> None:
        """
        开启新头寸
        """
        # 计算开仓金额
        max_single = self.capital * config.max_single_ratio
        size = min(available, max_single)
        
        if size < Decimal("100"):
            logger.info("开仓金额过小，跳过")
            return
        
        logger.info(
            f"🎯 准备开仓 {pool.symbol}: "
            f"费率={format_rate(pool.funding_rate)}, "
            f"金额={format_usdt(size)}"
        )
        
        # 执行开仓
        position = await self.executor.open_arbitrage(pool, size)
        
        if position:
            logger.info(f"✅ 开仓成功 {pool.symbol}")
        else:
            logger.error(f"❌ 开仓失败 {pool.symbol}")
    
    async def shutdown(self) -> None:
        """
        关闭引擎
        """
        self.running = False
        
        # 关闭所有持仓 (可选)
        positions = self.executor.get_all_positions()
        if positions:
            logger.warning(f"⚠️ 引擎关闭时有 {len(positions)} 个未平仓位")
            # 可选: 自动平仓
            # for pos in positions:
            #     await self.executor.close_arbitrage(pos.symbol)
        
        # 关闭交易所连接
        await self.exchange.close()
        
        logger.info("🛑 套利引擎已关闭")
    
    async def scan_once(self) -> list[Pool]:
        """
        单次扫描 (用于测试)
        """
        return await self.scanner.scan()
