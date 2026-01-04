"""
资金费率套利系统 - 辅助函数
"""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_DOWN
from typing import Optional

import pytz

from src.utils.config import config


def is_trading_time(now: Optional[datetime] = None) -> bool:
    """
    检查当前是否在交易时间内
    
    Args:
        now: 当前时间，默认为系统时间
        
    Returns:
        是否在交易时间内
    """
    tz = pytz.timezone(config.trading_timezone)
    
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = tz.localize(now)
    else:
        now = now.astimezone(tz)
    
    # 解析交易时间
    start_hour, start_min = map(int, config.trading_start.split(":"))
    end_hour, end_min = map(int, config.trading_end.split(":"))
    
    start = time(start_hour, start_min)
    end = time(end_hour, end_min)
    current = now.time()
    
    # 处理跨午夜的情况
    if start <= end:
        return start <= current <= end
    else:
        return current >= start or current <= end


def next_funding_time(now: Optional[datetime] = None) -> datetime:
    """
    获取下一次资金费率结算时间
    
    Funding times: 00:00, 08:00, 16:00 UTC
    
    Returns:
        下一次结算时间 (UTC)
    """
    utc = pytz.UTC
    
    if now is None:
        now = datetime.now(utc)
    elif now.tzinfo is None:
        now = utc.localize(now)
    else:
        now = now.astimezone(utc)
    
    funding_hours = [0, 8, 16]
    current_hour = now.hour
    
    # 找到下一个结算时间
    for hour in funding_hours:
        if current_hour < hour:
            return now.replace(hour=hour, minute=0, second=0, microsecond=0)
    
    # 如果当前时间已过 16:00，下一次是明天 00:00
    next_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return next_day + timedelta(days=1)


def time_to_next_funding(now: Optional[datetime] = None) -> int:
    """
    距离下一次资金费率结算的秒数
    """
    
    utc = pytz.UTC
    if now is None:
        now = datetime.now(utc)
    
    next_time = next_funding_time(now)
    delta = next_time - now
    return int(delta.total_seconds())


def format_usdt(amount: Decimal | float, decimals: int = 2) -> str:
    """格式化 USDT 金额"""
    if isinstance(amount, float):
        amount = Decimal(str(amount))
    return f"${amount.quantize(Decimal(10) ** -decimals, rounding=ROUND_DOWN):,}"


def format_rate(rate: Decimal | float) -> str:
    """格式化资金费率为百分比"""
    if isinstance(rate, float):
        rate = Decimal(str(rate))
    pct = rate * 100
    sign = "+" if rate > 0 else ""
    return f"{sign}{pct:.4f}%"


def format_delta(delta: Decimal) -> str:
    """格式化 Delta 值"""
    if abs(delta) < Decimal("0.001"):
        return "≈0"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.2%}"


def estimate_profit(
    position_value: Decimal,
    funding_rate: Decimal,
    periods: int = 1,
    spot_fee: Decimal = Decimal("0.001"),
    perp_fee: Decimal = Decimal("0.0004"),
) -> dict:
    """
    估算套利收益
    
    Args:
        position_value: 持仓价值
        funding_rate: 资金费率
        periods: 持仓期数
        spot_fee: 现货手续费
        perp_fee: 合约手续费
        
    Returns:
        dict: {
            "funding_income": 费率收入,
            "open_cost": 开仓成本,
            "close_cost": 平仓成本,
            "net_profit": 净利润,
            "roi": 收益率
        }
    """
    funding_income = position_value * abs(funding_rate) * periods
    open_cost = position_value * (spot_fee + perp_fee)
    close_cost = position_value * (spot_fee + perp_fee)
    net_profit = funding_income - open_cost - close_cost
    roi = net_profit / position_value if position_value else Decimal(0)
    
    return {
        "funding_income": funding_income,
        "open_cost": open_cost,
        "close_cost": close_cost,
        "net_profit": net_profit,
        "roi": roi,
    }


def breakeven_periods(
    funding_rate: Decimal,
    spot_fee: Decimal = Decimal("0.001"),
    perp_fee: Decimal = Decimal("0.0004"),
) -> int:
    """
    计算盈亏平衡所需期数
    """
    if abs(funding_rate) == 0:
        return float("inf")
    
    total_fee = (spot_fee + perp_fee) * 2  # 开仓 + 平仓
    periods = total_fee / abs(funding_rate)
    
    # 向上取整
    import math
    return math.ceil(float(periods))
