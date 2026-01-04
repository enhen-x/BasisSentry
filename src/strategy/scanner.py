"""
策略模块 - 机会扫描器
定时扫描所有交易对，获取资金费率和行情数据
"""
import asyncio
from typing import Optional

from src.exchange import ExchangeBase, FundingRate, Ticker, OrderBook
from src.strategy.selector import Pool, PoolSelector
from src.utils import logger, config, format_rate


class Scanner:
    """
    机会扫描器
    整合资金费率、行情、深度数据
    """
    
    def __init__(self, exchange: ExchangeBase):
        self.exchange = exchange
        self.selector = PoolSelector()
        
        # 缓存
        self._rates: dict[str, FundingRate] = {}
        self._tickers: dict[str, Ticker] = {}
        self._orderbooks: dict[str, OrderBook] = {}
    
    async def scan(self, symbols: Optional[list[str]] = None) -> list[Pool]:
        """
        扫描市场，返回候选池列表
        
        Args:
            symbols: 指定扫描的交易对，None 表示全部
            
        Returns:
            筛选后的候选池列表
        """
        logger.info("开始扫描市场...")
        
        # 1. 获取资金费率
        rates = await self.exchange.get_funding_rates()
        self._rates = {r.symbol: r for r in rates}
        logger.info(f"获取 {len(rates)} 个交易对的资金费率")
        
        # 找出高费率交易对
        high_rate_symbols = [
            r.symbol for r in rates
            if abs(r.rate) >= config.min_funding_rate
        ]
        logger.info(f"高费率交易对: {len(high_rate_symbols)} 个")
        
        if not high_rate_symbols:
            logger.warning("没有发现高费率机会")
            return []
        
        # 2. 获取行情数据
        tickers = await self.exchange.get_tickers()
        self._tickers = {t.symbol: t for t in tickers}
        
        # 确保现货市场已加载 (针对 Binance)
        if hasattr(self.exchange, "spot"):
            if not self.exchange.spot.markets:
                try:
                    await self.exchange.spot.load_markets()
                except Exception as e:
                    logger.warning(f"加载现货市场失败: {e}")

        # 3. 获取订单簿 (只获取高费率交易对)
        pools = []
        for symbol in high_rate_symbols:
            if symbol not in self._tickers:
                continue
            
            # 检查现货是否存在
            # 假设 symbol 格式为 "BTC/USDT:USDT"
            base = symbol.split("/")[0]
            spot_symbol = f"{base}/USDT"
            
            if hasattr(self.exchange, "spot"):
                if spot_symbol not in self.exchange.spot.markets:
                    # 记录一次警告即可，避免刷屏
                    # logger.warning(f"跳过 {symbol}: 现货 {spot_symbol} 不存在")
                    continue
            
            try:
                orderbook = await self.exchange.get_orderbook(symbol)
                self._orderbooks[symbol] = orderbook
                
                pool = Pool.from_data(
                    rate=self._rates[symbol],
                    ticker=self._tickers[symbol],
                    orderbook=orderbook,
                )
                pools.append(pool)
            except Exception as e:
                logger.warning(f"获取 {symbol} 订单簿失败: {e}")
                continue
            
            # 避免触发限流
            await asyncio.sleep(0.1)
        
        logger.info(f"构建 {len(pools)} 个池子数据")
        
        # 4. 筛选
        candidates = self.selector.filter(pools)
        
        # 打印 Top 5
        if candidates:
            logger.info("=" * 50)
            logger.info("Top 5 套利机会:")
            for i, pool in enumerate(candidates[:5], 1):
                logger.info(f"  {i}. {self.selector.format_pool(pool)}")
            logger.info("=" * 50)
        
        return candidates
    
    async def scan_single(self, symbol: str) -> Optional[Pool]:
        """扫描单个交易对"""
        try:
            rate = await self.exchange.get_funding_rate(symbol)
            ticker = await self.exchange.get_ticker(symbol)
            orderbook = await self.exchange.get_orderbook(symbol)
            
            pool = Pool.from_data(rate, ticker, orderbook)
            self.selector._calc_metrics(pool)
            
            return pool
        except Exception as e:
            logger.error(f"扫描 {symbol} 失败: {e}")
            return None
    
    def get_cached_rate(self, symbol: str) -> Optional[FundingRate]:
        """获取缓存的资金费率"""
        return self._rates.get(symbol)
    
    def get_top_rates(self, n: int = 10) -> list[FundingRate]:
        """获取费率最高的 N 个交易对"""
        rates = list(self._rates.values())
        rates.sort(key=lambda x: abs(x.rate), reverse=True)
        return rates[:n]
    
    def print_rate_summary(self) -> None:
        """打印费率摘要"""
        if not self._rates:
            logger.warning("无缓存数据")
            return
        
        rates = list(self._rates.values())
        positive = [r for r in rates if r.rate > 0]
        negative = [r for r in rates if r.rate < 0]
        
        logger.info(f"费率分布: 正费率 {len(positive)} 个, 负费率 {len(negative)} 个")
        
        if positive:
            max_pos = max(positive, key=lambda x: x.rate)
            logger.info(f"最高正费率: {max_pos.symbol} {format_rate(max_pos.rate)}")
        
        if negative:
            max_neg = min(negative, key=lambda x: x.rate)
            logger.info(f"最高负费率: {max_neg.symbol} {format_rate(max_neg.rate)}")
