"""
交易所适配层
"""
from src.exchange.base import (
    ExchangeBase,
    FundingRate,
    OrderBook,
    Ticker,
    Order,
    Position,
    OrderSide,
    OrderType,
    PositionSide,
)
from src.exchange.binance import BinanceAdapter
from src.exchange.bybit import BybitAdapter
from src.exchange.okx import OKXAdapter

__all__ = [
    # Base
    "ExchangeBase",
    "FundingRate",
    "OrderBook",
    "Ticker",
    "Order",
    "Position",
    "OrderSide",
    "OrderType",
    "PositionSide",
    # Adapters
    "BinanceAdapter",
    "BybitAdapter",
    "OKXAdapter",
    # Factory
    "create_exchange",
]


def create_exchange(name: str, **kwargs) -> ExchangeBase:
    """
    工厂函数：创建交易所适配器
    
    Args:
        name: 交易所名称 (binance, bybit, okx)
        **kwargs: API 配置参数
    
    Returns:
        ExchangeBase 实例
    """
    adapters = {
        "binance": BinanceAdapter,
        "bybit": BybitAdapter,
        "okx": OKXAdapter,
    }
    
    adapter_cls = adapters.get(name.lower())
    if not adapter_cls:
        raise ValueError(f"不支持的交易所: {name}")
    
    return adapter_cls(**kwargs)

