"""
多交易所机会扫描器
并行扫描 Binance/Bybit/OKX，筛选出预期收益最高的套利机会
"""
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime
from typing import Optional

from src.exchange import ExchangeBase, FundingRate, Ticker, OrderBook, create_exchange
from src.strategy.selector import Pool, PoolSelector
from src.utils import logger, config, format_rate, format_usdt


@dataclass
class ArbitrageOpportunity:
    """跨交易所套利机会"""
    exchange: str              # 交易所名称
    symbol: str                # 交易对
    funding_rate: Decimal      # 当前费率
    predicted_rate: Decimal    # 预测费率
    volume_24h: Decimal        # 24h交易量
    depth_05pct: Decimal       # ±0.5%深度
    spread: Decimal            # 现货-合约价差
    price: Decimal             # 当前价格
    expected_profit: Decimal   # 预期收益 (关键排序字段)
    breakeven_periods: int     # 盈亏平衡期数
    score: Decimal             # 综合评分
    next_funding_time: datetime = field(default_factory=datetime.now)
    
    @classmethod
    def from_pool(cls, pool: Pool, exchange_name: str, next_funding_time: datetime = None) -> "ArbitrageOpportunity":
        """从 Pool 构建 ArbitrageOpportunity"""
        return cls(
            exchange=exchange_name,
            symbol=pool.symbol,
            funding_rate=pool.funding_rate,
            predicted_rate=pool.predicted_rate,
            volume_24h=pool.volume_24h,
            depth_05pct=pool.depth_05pct,
            spread=pool.spread,
            price=pool.price,
            expected_profit=pool.expected_profit or Decimal(0),
            breakeven_periods=pool.breakeven_periods or 99,
            score=pool.score or Decimal(0),
            next_funding_time=next_funding_time or datetime.now(),
        )


class MultiExchangeScanner:
    """
    多交易所扫描器
    并行扫描多个交易所，汇总并筛选最优套利机会
    """
    
    # 交易所费率配置
    EXCHANGE_FEES = {
        "binance": {"spot": Decimal("0.001"), "perp": Decimal("0.0004")},
        "bybit": {"spot": Decimal("0.001"), "perp": Decimal("0.00055")},
        "okx": {"spot": Decimal("0.001"), "perp": Decimal("0.0005")},
    }
    
    def __init__(
        self,
        exchanges: list[str] = None,
        testnet: bool = True,
    ):
        """
        Args:
            exchanges: 要扫描的交易所列表，默认全部
            testnet: 是否使用测试网
        """
        self.exchange_names = exchanges or ["binance", "bybit", "okx"]
        self.testnet = testnet
        self.selector = PoolSelector()
        
        # 交易所适配器 (延迟初始化)
        self._exchanges: dict[str, ExchangeBase] = {}
        
        logger.info(f"多交易所扫描器初始化: {self.exchange_names}")
    
    async def _get_exchange(self, name: str) -> ExchangeBase:
        """获取或创建交易所适配器"""
        if name not in self._exchanges:
            self._exchanges[name] = create_exchange(name, testnet=self.testnet)
        return self._exchanges[name]
    
    async def scan_exchange(self, name: str) -> list[ArbitrageOpportunity]:
        """
        扫描单个交易所
        
        Returns:
            该交易所的套利机会列表
        """
        try:
            exchange = await self._get_exchange(name)
            logger.info(f"[{name.upper()}] 开始扫描...")
            
            # 1. 获取资金费率
            rates = await exchange.get_funding_rates()
            rate_map = {r.symbol: r for r in rates}
            
            # 找出高费率交易对
            min_rate = config.min_funding_rate
            high_rate_symbols = [
                r.symbol for r in rates
                if abs(r.rate) >= min_rate
            ]
            
            if not high_rate_symbols:
                logger.info(f"[{name.upper()}] 无高费率机会")
                return []
            
            logger.info(f"[{name.upper()}] 高费率交易对: {len(high_rate_symbols)} 个")
            
            # 2. 获取行情数据
            tickers = await exchange.get_tickers()
            ticker_map = {t.symbol: t for t in tickers}
            
            # 3. 获取订单簿并构建 Pool
            opportunities = []
            for symbol in high_rate_symbols[:50]:  # 限制数量避免过多请求
                if symbol not in ticker_map:
                    continue
                
                try:
                    orderbook = await exchange.get_orderbook(symbol)
                    
                    pool = Pool.from_data(
                        rate=rate_map[symbol],
                        ticker=ticker_map[symbol],
                        orderbook=orderbook,
                    )
                    
                    # 应用筛选条件
                    if self._filter_pool(pool):
                        self.selector._calc_metrics(pool)
                        opp = ArbitrageOpportunity.from_pool(
                            pool, 
                            name,
                            rate_map[symbol].next_funding_time,
                        )
                        opportunities.append(opp)
                    
                    await asyncio.sleep(0.05)  # 避免限流
                    
                except Exception as e:
                    logger.debug(f"[{name.upper()}] {symbol} 获取失败: {e}")
                    continue
            
            logger.info(f"[{name.upper()}] 发现 {len(opportunities)} 个符合条件的机会")
            return opportunities
            
        except Exception as e:
            logger.error(f"[{name.upper()}] 扫描失败: {e}")
            return []
    
    def _filter_pool(self, pool: Pool) -> bool:
        """应用筛选条件"""
        # 黑名单检查
        blacklist = set(config.filter_config.get("blacklist", []))
        if pool.base_currency in blacklist:
            return False
        
        # 流动性窗口
        min_vol = Decimal(str(config.filter_config.get("volume_24h", {}).get("min", 500000)))
        max_vol = Decimal(str(config.filter_config.get("volume_24h", {}).get("max", 5000000)))
        if not (min_vol <= pool.volume_24h <= max_vol):
            return False
        
        # 深度检查
        min_depth = Decimal(str(config.filter_config.get("depth_05pct", {}).get("min", 10000)))
        if pool.depth_05pct < min_depth:
            return False
        
        # 费率门槛
        min_rate = Decimal(str(config.filter_config.get("funding_rate", {}).get("min_abs", 0.0003)))
        if abs(pool.funding_rate) < min_rate:
            return False
        
        # 价差检查
        max_spread = Decimal(str(config.filter_config.get("spread", {}).get("max", 0.001)))
        if pool.spread > max_spread:
            return False
        
        return True
    
    async def scan_all(self) -> list[ArbitrageOpportunity]:
        """
        并行扫描所有交易所
        
        Returns:
            按预期收益排序的套利机会列表
        """
        logger.info("=" * 60)
        logger.info(f"开始跨交易所扫描: {self.exchange_names}")
        logger.info("=" * 60)
        
        # 并行扫描所有交易所
        tasks = [self.scan_exchange(name) for name in self.exchange_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 汇总结果
        all_opportunities = []
        for name, result in zip(self.exchange_names, results):
            if isinstance(result, Exception):
                logger.error(f"[{name.upper()}] 扫描异常: {result}")
            elif result:
                all_opportunities.extend(result)
        
        # 按预期收益排序
        all_opportunities.sort(key=lambda x: x.expected_profit, reverse=True)
        
        logger.info(f"共发现 {len(all_opportunities)} 个套利机会")
        
        return all_opportunities
    
    def select_best(
        self, 
        opportunities: list[ArbitrageOpportunity],
        n: int = 1,
    ) -> list[ArbitrageOpportunity]:
        """
        筛选最优机会
        
        Args:
            opportunities: 机会列表
            n: 返回 Top N
            
        Returns:
            最优的 N 个机会
        """
        if not opportunities:
            return []
        
        # 按综合评分排序
        sorted_opps = sorted(opportunities, key=lambda x: x.score, reverse=True)
        return sorted_opps[:n]
    
    def format_opportunity(self, opp: ArbitrageOpportunity) -> str:
        """格式化机会信息"""
        time_to_funding = opp.next_funding_time - datetime.now()
        hours = max(0, time_to_funding.total_seconds() / 3600)
        
        return (
            f"[{opp.exchange.upper():8}] {opp.symbol:15} | "
            f"费率: {format_rate(opp.funding_rate):>8} | "
            f"预期收益: {format_usdt(opp.expected_profit):>10} | "
            f"下次结算: {hours:.1f}h"
        )
    
    def print_summary(self, opportunities: list[ArbitrageOpportunity], top_n: int = 10) -> None:
        """打印扫描摘要"""
        if not opportunities:
            logger.warning("未发现套利机会")
            return
        
        # 按交易所统计
        by_exchange = {}
        for opp in opportunities:
            by_exchange.setdefault(opp.exchange, []).append(opp)
        
        logger.info("\n" + "=" * 70)
        logger.info("跨交易所套利机会扫描结果")
        logger.info("=" * 70)
        
        for name in self.exchange_names:
            count = len(by_exchange.get(name, []))
            logger.info(f"  [{name.upper():8}] {count:3} 个符合条件")
        
        logger.info("-" * 70)
        logger.info(f"预期收益 TOP {top_n}:")
        logger.info("-" * 70)
        
        for i, opp in enumerate(opportunities[:top_n], 1):
            logger.info(f"  {i:2}. {self.format_opportunity(opp)}")
        
        logger.info("=" * 70)
        
        # 推荐最优机会
        best = opportunities[0]
        logger.info(f"\n🎯 推荐最优机会:")
        logger.info(f"   交易所: {best.exchange.upper()}")
        logger.info(f"   交易对: {best.symbol}")
        logger.info(f"   资金费率: {format_rate(best.funding_rate)}")
        logger.info(f"   预期收益: {format_usdt(best.expected_profit)} (持仓3期)")
        logger.info(f"   盈亏平衡: {best.breakeven_periods} 期")
    
    async def close(self) -> None:
        """关闭所有交易所连接"""
        for name, exchange in self._exchanges.items():
            try:
                await exchange.close()
            except Exception as e:
                logger.warning(f"关闭 {name} 连接失败: {e}")
        self._exchanges.clear()
