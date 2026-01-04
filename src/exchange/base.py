"""
交易所适配层 - 抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"


class PositionSide(Enum):
    """持仓方向"""
    LONG = "long"
    SHORT = "short"
    BOTH = "both"  # 对冲模式


@dataclass
class FundingRate:
    """资金费率数据"""
    symbol: str
    rate: Decimal              # 当前费率
    predicted_rate: Decimal    # 预测费率
    next_funding_time: datetime
    timestamp: datetime
    
    @property
    def is_positive(self) -> bool:
        return self.rate > 0
    
    @property
    def abs_rate(self) -> Decimal:
        return abs(self.rate)


@dataclass
class OrderBook:
    """订单簿数据"""
    symbol: str
    bids: list[tuple[Decimal, Decimal]]  # [(价格, 数量), ...]
    asks: list[tuple[Decimal, Decimal]]
    timestamp: datetime
    
    @property
    def best_bid(self) -> Decimal:
        return self.bids[0][0] if self.bids else Decimal(0)
    
    @property
    def best_ask(self) -> Decimal:
        return self.asks[0][0] if self.asks else Decimal(0)
    
    @property
    def spread(self) -> Decimal:
        """买卖价差"""
        if not self.bids or not self.asks:
            return Decimal(0)
        return (self.best_ask - self.best_bid) / self.best_bid
    
    def depth_at_pct(self, pct: Decimal = Decimal("0.005")) -> Decimal:
        """
        计算指定价格范围内的深度 (USD)
        
        Args:
            pct: 价格范围百分比，默认 0.5%
        """
        mid_price = (self.best_bid + self.best_ask) / 2
        lower_bound = mid_price * (1 - pct)
        upper_bound = mid_price * (1 + pct)
        
        bid_depth = sum(
            price * qty for price, qty in self.bids
            if price >= lower_bound
        )
        ask_depth = sum(
            price * qty for price, qty in self.asks
            if price <= upper_bound
        )
        
        return bid_depth + ask_depth


@dataclass
class Ticker:
    """行情数据"""
    symbol: str
    last_price: Decimal
    volume_24h: Decimal    # 24h 交易量 (USD)
    high_24h: Decimal
    low_24h: Decimal
    timestamp: datetime


@dataclass
class Order:
    """订单数据"""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    price: Decimal
    amount: Decimal
    filled: Decimal
    remaining: Decimal
    status: str
    timestamp: datetime
    fee: Optional[Decimal] = None
    fee_currency: Optional[str] = None


@dataclass
class Position:
    """持仓数据"""
    symbol: str
    side: PositionSide
    size: Decimal           # 持仓数量
    entry_price: Decimal    # 开仓均价
    mark_price: Decimal     # 标记价格
    unrealized_pnl: Decimal
    leverage: int
    margin: Decimal
    liquidation_price: Optional[Decimal] = None
    
    @property
    def notional_value(self) -> Decimal:
        """名义价值"""
        return self.size * self.mark_price
    
    @property
    def margin_ratio(self) -> Decimal:
        """保证金率"""
        if self.notional_value == 0:
            return Decimal(1)
        return self.margin / self.notional_value


class ExchangeBase(ABC):
    """交易所抽象基类"""
    
    def __init__(self, api_key: str = "", secret: str = "", testnet: bool = True):
        self.api_key = api_key
        self.secret = secret
        self.testnet = testnet
    
    @property
    @abstractmethod
    def name(self) -> str:
        """交易所名称"""
        pass
    
    # ==================== 数据获取 ====================
    
    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> FundingRate:
        """获取资金费率"""
        pass
    
    @abstractmethod
    async def get_funding_rates(self) -> list[FundingRate]:
        """获取所有交易对的资金费率"""
        pass
    
    @abstractmethod
    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        """获取订单簿"""
        pass
    
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """获取行情"""
        pass
    
    @abstractmethod
    async def get_tickers(self) -> list[Ticker]:
        """获取所有交易对行情"""
        pass
    
    # ==================== 现货交易 ====================
    
    @abstractmethod
    async def get_spot_balance(self, currency: str = "USDT") -> Decimal:
        """获取现货余额"""
        pass
    
    @abstractmethod
    async def place_spot_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[Decimal] = None,
    ) -> Order:
        """下现货单"""
        pass
    
    # ==================== 合约交易 ====================
    
    @abstractmethod
    async def get_perp_balance(self, currency: str = "USDT") -> Decimal:
        """获取合约账户余额"""
        pass
    
    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """设置杠杆"""
        pass
    
    @abstractmethod
    async def place_perp_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[Decimal] = None,
        reduce_only: bool = False,
    ) -> Order:
        """下永续合约单"""
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        pass
    
    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """获取所有持仓"""
        pass
    
    # ==================== 工具方法 ====================
    
    @abstractmethod
    async def close(self) -> None:
        """关闭连接"""
        pass
    
    def spot_symbol(self, base: str, quote: str = "USDT") -> str:
        """构建现货交易对名称"""
        return f"{base}/{quote}"
    
    def perp_symbol(self, base: str, quote: str = "USDT") -> str:
        """构建永续合约交易对名称"""
        return f"{base}/{quote}:USDT"
