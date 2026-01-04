"""
策略模块 - 池子筛选器
核心竞争力：精准筛选中低流动性池，避开大资金竞争
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from src.exchange import FundingRate, Ticker, OrderBook
from src.utils import config, logger, format_rate, format_usdt, estimate_profit


@dataclass
class Pool:
    """
    交易池数据结构
    整合资金费率、行情、深度信息
    """
    symbol: str
    # 资金费率
    funding_rate: Decimal
    predicted_rate: Decimal
    # 行情
    price: Decimal
    volume_24h: Decimal
    # 深度
    depth_05pct: Decimal
    spread: Decimal
    # 计算指标
    expected_profit: Optional[Decimal] = None
    breakeven_periods: Optional[int] = None
    score: Optional[Decimal] = None
    
    @classmethod
    def from_data(
        cls,
        rate: FundingRate,
        ticker: Ticker,
        orderbook: OrderBook,
    ) -> "Pool":
        """从原始数据构建 Pool"""
        return cls(
            symbol=rate.symbol,
            funding_rate=rate.rate,
            predicted_rate=rate.predicted_rate,
            price=ticker.last_price,
            volume_24h=ticker.volume_24h,
            depth_05pct=orderbook.depth_at_pct(Decimal("0.005")),
            spread=orderbook.spread,
        )
    
    @property
    def base_currency(self) -> str:
        """获取基础货币"""
        # BTC/USDT:USDT -> BTC
        return self.symbol.split("/")[0]
    
    @property
    def is_positive_rate(self) -> bool:
        """是否正费率"""
        return self.funding_rate > 0


class PoolSelector:
    """
    池子筛选器
    筛选符合条件的中低流动性池
    """
    
    def __init__(self):
        self.filter_cfg = config.filter_config
        self.filter_mode = config.filter_mode
        
        # 从配置加载筛选参数
        self.min_volume = Decimal(str(
            self.filter_cfg.get("volume_24h", {}).get("min", 500000)
        ))
        self.max_volume = Decimal(str(
            self.filter_cfg.get("volume_24h", {}).get("max", 5000000)
        ))
        self.min_depth = Decimal(str(
            self.filter_cfg.get("depth_05pct", {}).get("min", 10000)
        ))
        self.min_rate = Decimal(str(
            self.filter_cfg.get("funding_rate", {}).get("min_abs", 0.0003)
        ))
        self.max_spread = Decimal(str(
            self.filter_cfg.get("spread", {}).get("max", 0.001)
        ))
        self.blacklist = set(self.filter_cfg.get("blacklist", []))
        
        mode_tag = "🔓 宽松模式" if self.filter_mode == "relaxed" else "🔒 严格模式"
        logger.info(
            f"筛选器初始化 [{mode_tag}]: 交易量 {format_usdt(self.min_volume)}-{format_usdt(self.max_volume)}, "
            f"费率 >= {format_rate(self.min_rate)}, 价差 <= {self.max_spread:.2%}"
        )
    
    def filter(self, pools: list[Pool]) -> list[Pool]:
        """
        筛选符合条件的池子
        
        Returns:
            按预期收益排序的候选池列表
        """
        candidates = []
        
        for pool in pools:
            # 1. 黑名单检查
            if pool.base_currency in self.blacklist:
                continue
            
            # 2. 负费率检查
            if not config.allow_negative_rates and pool.funding_rate < 0:
                continue
            
            # 3. 流动性窗口检查 (核心筛选)
            if not (self.min_volume <= pool.volume_24h <= self.max_volume):
                continue
            
            # 3. 深度检查
            if pool.depth_05pct < self.min_depth:
                continue
            
            # 4. 费率门槛
            if abs(pool.funding_rate) < self.min_rate:
                continue
            
            # 5. 价差检查
            if pool.spread > self.max_spread:
                continue
            
            # 计算预期收益
            self._calc_metrics(pool)
            candidates.append(pool)
        
        # 按综合评分排序
        candidates.sort(key=lambda x: x.score or Decimal(0), reverse=True)
        
        logger.info(f"筛选结果: {len(candidates)}/{len(pools)} 个池子通过筛选")
        return candidates
    
    def _calc_metrics(self, pool: Pool) -> None:
        """计算评估指标"""
        # 假设持仓 3 期
        position_value = Decimal("1000")  # 假设 1000 USDT
        
        profit_info = estimate_profit(
            position_value=position_value,
            funding_rate=pool.funding_rate,
            periods=3,
        )
        
        pool.expected_profit = profit_info["net_profit"]
        
        # 盈亏平衡期数
        from src.utils.helpers import breakeven_periods
        pool.breakeven_periods = breakeven_periods(pool.funding_rate)
        
        # 综合评分 (费率 * 流动性因子 * 价差因子)
        rate_score = abs(pool.funding_rate) * 1000  # 放大费率
        liquidity_score = min(pool.depth_05pct / self.min_depth, Decimal(5)) / 5
        spread_score = 1 - (pool.spread / self.max_spread)
        
        pool.score = rate_score * liquidity_score * spread_score
    
    def top_n(self, pools: list[Pool], n: int = 5) -> list[Pool]:
        """获取 Top N 候选池"""
        filtered = self.filter(pools)
        return filtered[:n]
    
    def format_pool(self, pool: Pool) -> str:
        """格式化池子信息"""
        return (
            f"{pool.symbol}: "
            f"费率={format_rate(pool.funding_rate)}, "
            f"交易量={format_usdt(pool.volume_24h)}, "
            f"深度={format_usdt(pool.depth_05pct)}, "
            f"价差={pool.spread:.4%}, "
            f"评分={float(pool.score or 0):.4f}"
        )
