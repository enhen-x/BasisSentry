"""
策略模块 - 交易执行器
执行套利交易，管理对冲头寸
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from src.exchange import (
    ExchangeBase,
    OrderSide,
    OrderType,
    Order,
    Position as ExchangePosition,
)
from src.strategy.selector import Pool
from src.utils import logger, config, format_usdt, format_rate

# 延迟导入避免循环依赖
def _get_position_store():
    from src.core.position_store import position_store
    return position_store


@dataclass
class ArbitragePosition:
    """
    套利持仓
    包含现货和合约两边的头寸
    """
    symbol: str
    base_currency: str
    
    # 现货头寸
    spot_qty: Decimal = Decimal(0)
    spot_avg_price: Decimal = Decimal(0)
    spot_value: Decimal = Decimal(0)
    
    # 合约头寸 (负数为空头)
    perp_qty: Decimal = Decimal(0)
    perp_avg_price: Decimal = Decimal(0)
    perp_value: Decimal = Decimal(0)
    
    # 资金费率收益
    funding_earned: Decimal = Decimal(0)
    
    # 元数据
    leverage: int = 2
    opened_at: Optional[datetime] = None
    funding_periods: int = 0
    
    # 订单记录
    orders: list[Order] = field(default_factory=list)
    
    @property
    def notional_value(self) -> Decimal:
        """名义价值"""
        return max(abs(self.spot_value), abs(self.perp_value))
    
    @property
    def delta(self) -> Decimal:
        """Delta 值 (0 为完美中性)"""
        if self.notional_value == 0:
            return Decimal(0)
        return (self.spot_qty + self.perp_qty) / abs(self.spot_qty or self.perp_qty)
    
    @property
    def is_delta_neutral(self) -> bool:
        """是否 Delta 中性"""
        return abs(self.delta) < config.delta_tolerance
    
    @property
    def total_cost(self) -> Decimal:
        """总成本 (手续费)"""
        return sum(o.fee or Decimal(0) for o in self.orders)


class Executor:
    """
    交易执行器
    负责开仓、平仓、调仓
    """
    
    def __init__(self, exchange: ExchangeBase, load_positions: bool = True):
        self.exchange = exchange
        self.positions: dict[str, ArbitragePosition] = {}
        
        # 从持久化存储加载持仓
        if load_positions:
            try:
                self.positions = _get_position_store().load_all()
            except Exception as e:
                logger.warning(f"加载持仓失败: {e}")
    
    async def open_arbitrage(
        self,
        pool: Pool,
        size_usdt: Decimal,
    ) -> Optional[ArbitragePosition]:
        """
        开启套利头寸
        
        正费率: 买现货 + 开空合约 (收取资金费)
        负费率: 卖现货 + 开多合约 (收取资金费)
        
        Args:
            pool: 目标池子
            size_usdt: 头寸大小 (USDT)
            
        Returns:
            套利持仓对象
        """
        symbol = pool.symbol
        base = pool.base_currency
        spot_symbol = f"{base}/USDT"
        perp_symbol = symbol  # 已经是 BTC/USDT:USDT 格式
        
        # 计算下单数量
        qty = size_usdt / pool.price
        
        logger.info(
            f"开始开仓 {symbol}: "
            f"费率={format_rate(pool.funding_rate)}, "
            f"金额={format_usdt(size_usdt)}, "
            f"数量={qty:.6f}"
        )
        
        try:
            # 设置杠杆
            leverage = config.default_leverage
            await self.exchange.set_leverage(perp_symbol, leverage)
            
            # 正费率: 买现货 + 开空
            # 负费率: 暂不支持 (需要借币做空现货)
            if pool.funding_rate > 0:
                spot_side = OrderSide.BUY
                perp_side = OrderSide.SELL
            else:
                logger.warning("负费率套利需要借币，暂不支持")
                return None
            
            # 并行下单 (允许单独失败以便回滚)
            results = await asyncio.gather(
                self.exchange.place_spot_order(
                    symbol=spot_symbol,
                    side=spot_side,
                    amount=qty,
                    order_type=OrderType.MARKET,
                ),
                self.exchange.place_perp_order(
                    symbol=perp_symbol,
                    side=perp_side,
                    amount=qty,
                    order_type=OrderType.MARKET,
                ),
                return_exceptions=True,
            )
            
            spot_order, perp_order = results
            
            # 检查是否有一边失败
            spot_failed = isinstance(spot_order, Exception)
            perp_failed = isinstance(perp_order, Exception)
            
            if spot_failed and perp_failed:
                logger.error(f"开仓失败 {symbol}: 现货和合约都失败")
                logger.error(f"  现货错误: {spot_order}")
                logger.error(f"  合约错误: {perp_order}")
                return None
            
            if spot_failed:
                # 现货失败，需要回滚合约
                logger.error(f"⚠️ 开仓异常 {symbol}: 现货失败，正在回滚合约...")
                logger.error(f"  现货错误: {spot_order}")
                try:
                    await self.exchange.place_perp_order(
                        symbol=perp_symbol,
                        side=OrderSide.BUY,  # 平掉刚开的空单
                        amount=perp_order.filled,
                        order_type=OrderType.MARKET,
                    )
                    logger.info(f"  ✅ 合约回滚成功")
                except Exception as rollback_err:
                    logger.error(f"  ❌ 合约回滚失败: {rollback_err}")
                return None
            
            if perp_failed:
                # 合约失败，需要回滚现货
                logger.error(f"⚠️ 开仓异常 {symbol}: 合约失败，正在回滚现货...")
                logger.error(f"  合约错误: {perp_order}")
                try:
                    await self.exchange.place_spot_order(
                        symbol=spot_symbol,
                        side=OrderSide.SELL,  # 卖掉刚买的现货
                        amount=spot_order.filled,
                        order_type=OrderType.MARKET,
                    )
                    logger.info(f"  ✅ 现货回滚成功")
                except Exception as rollback_err:
                    logger.error(f"  ❌ 现货回滚失败: {rollback_err}")
                return None
            
            # 双边都成功，构建持仓对象
            position = ArbitragePosition(
                symbol=perp_symbol,
                base_currency=base,
                spot_qty=spot_order.filled,
                spot_avg_price=spot_order.price,
                spot_value=spot_order.filled * spot_order.price,
                perp_qty=-perp_order.filled,  # 空头为负
                perp_avg_price=perp_order.price,
                perp_value=perp_order.filled * perp_order.price,
                leverage=leverage,
                opened_at=datetime.now(),
                orders=[spot_order, perp_order],
            )
            
            self.positions[perp_symbol] = position
            
            # 持久化保存
            try:
                _get_position_store().save(position)
            except Exception as e:
                logger.warning(f"保存持仓失败: {e}")
            
            logger.info(
                f"开仓成功 {symbol}: "
                f"现货={position.spot_qty:.6f}@{position.spot_avg_price:.2f}, "
                f"合约={-position.perp_qty:.6f}@{position.perp_avg_price:.2f}, "
                f"Delta={position.delta:.4f}"
            )
            
            return position
            
        except Exception as e:
            logger.error(f"开仓失败 {symbol}: {e}")
            return None
    
    async def close_arbitrage(
        self,
        symbol: str,
    ) -> Optional[Decimal]:
        """
        平仓套利头寸
        
        Returns:
            平仓盈亏 (USDT)
        """
        position = self.positions.get(symbol)
        if not position:
            logger.warning(f"无持仓 {symbol}")
            return None
        
        base = position.base_currency
        spot_symbol = f"{base}/USDT"
        perp_symbol = symbol
        
        logger.info(f"开始平仓 {symbol}: 现货={position.spot_qty:.6f}, 合约={-position.perp_qty:.6f}")
        
        try:
            # 卖出现货 + 平空合约
            spot_order, perp_order = await asyncio.gather(
                self.exchange.place_spot_order(
                    symbol=spot_symbol,
                    side=OrderSide.SELL,
                    amount=position.spot_qty,
                    order_type=OrderType.MARKET,
                ),
                self.exchange.place_perp_order(
                    symbol=perp_symbol,
                    side=OrderSide.BUY,
                    amount=abs(position.perp_qty),
                    order_type=OrderType.MARKET,
                    reduce_only=True,
                ),
            )
            
            position.orders.extend([spot_order, perp_order])
            
            # 计算盈亏
            spot_pnl = (spot_order.price - position.spot_avg_price) * position.spot_qty
            perp_pnl = (position.perp_avg_price - perp_order.price) * abs(position.perp_qty)
            total_pnl = spot_pnl + perp_pnl + position.funding_earned - position.total_cost
            
            logger.info(
                f"平仓成功 {symbol}: "
                f"现货盈亏={format_usdt(spot_pnl)}, "
                f"合约盈亏={format_usdt(perp_pnl)}, "
                f"费率收益={format_usdt(position.funding_earned)}, "
                f"手续费={format_usdt(position.total_cost)}, "
                f"总盈亏={format_usdt(total_pnl)}"
            )
            
            # 移除持仓
            del self.positions[symbol]
            
            # 从持久化存储删除
            try:
                _get_position_store().remove(symbol)
            except Exception as e:
                logger.warning(f"删除持仓记录失败: {e}")
            
            return total_pnl
            
        except Exception as e:
            logger.error(f"平仓失败 {symbol}: {e}")
            return None
    
    async def rebalance(self, symbol: str) -> bool:
        """
        调整 Delta
        当 Delta 偏差过大时调仓
        """
        position = self.positions.get(symbol)
        if not position:
            return False
        
        if position.is_delta_neutral:
            return True
        
        delta = position.delta
        logger.info(f"调仓 {symbol}: Delta={delta:.4f}")
        
        # 计算调整量
        target_qty = abs(position.perp_qty)
        current_spot = position.spot_qty
        adjust_qty = target_qty - current_spot
        
        try:
            if adjust_qty > 0:
                # 需要买入更多现货
                order = await self.exchange.place_spot_order(
                    symbol=f"{position.base_currency}/USDT",
                    side=OrderSide.BUY,
                    amount=adjust_qty,
                    order_type=OrderType.MARKET,
                )
            else:
                # 需要卖出现货
                order = await self.exchange.place_spot_order(
                    symbol=f"{position.base_currency}/USDT",
                    side=OrderSide.SELL,
                    amount=abs(adjust_qty),
                    order_type=OrderType.MARKET,
                )
            
            position.orders.append(order)
            position.spot_qty += adjust_qty if adjust_qty > 0 else -abs(adjust_qty)
            
            logger.info(f"调仓完成 {symbol}: 新 Delta={position.delta:.4f}")
            return True
            
        except Exception as e:
            logger.error(f"调仓失败 {symbol}: {e}")
            return False
    
    def get_position(self, symbol: str) -> Optional[ArbitragePosition]:
        """获取持仓"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> list[ArbitragePosition]:
        """获取所有持仓"""
        return list(self.positions.values())
    
    def get_total_exposure(self) -> Decimal:
        """获取总风险敞口"""
        return sum(p.notional_value for p in self.positions.values())

    async def estimate_pnl(self, symbol: str) -> Optional[Decimal]:
        """
        估算当前平仓的净盈亏 (含手续费)
        用于轮动策略判断是否回本
        """
        position = self.positions.get(symbol)
        if not position:
            return None
        
        try:
            # 获取当前价格
            base = position.base_currency
            perp_symbol = symbol
            spot_symbol = f"{base}/USDT"
            
            # 这里简化处理：直接获取 Ticker 价格作为估算
            # 实际交易可能用盘口价格，但作为估算足够了
            spot_ticker = await self.exchange.get_ticker(spot_symbol)
            perp_ticker = await self.exchange.get_ticker(perp_symbol)
            
            current_spot_price = spot_ticker.last_price
            current_perp_price = perp_ticker.last_price
            
            # 计算盈亏
            # 现货盈亏: (当前价 - 均价) * 数量
            spot_pnl = (current_spot_price - position.spot_avg_price) * position.spot_qty
            
            # 合约盈亏: (均价 - 当前价) * 数量 (做空)
            # 注意: perp_qty 为负数，这里取绝对值
            perp_pnl = (position.perp_avg_price - current_perp_price) * abs(position.perp_qty)
            
            # 手续费估算 (假设平仓手续费与开仓时比例相似，或者直接按费率算)
            # 现货 0.1%, 合约 0.04%
            # 估算平仓价值
            close_value = (current_spot_price * position.spot_qty) + (current_perp_price * abs(position.perp_qty))
            est_close_fee = close_value * Decimal("0.0007") # 0.1% + 0.04% 平均一下，或者分开算
            
            # 准确计算应为:
            spot_fee_rate = Decimal("0.001")
            perp_fee_rate = Decimal("0.0004") 
            est_spot_fee = current_spot_price * position.spot_qty * spot_fee_rate
            est_perp_fee = current_perp_price * abs(position.perp_qty) * perp_fee_rate
            est_close_fee = est_spot_fee + est_perp_fee
            
            # 净盈亏 = 现货盈亏 + 合约盈亏 + 已收租金 - 开仓成本 - 预计平仓成本
            total_pnl = spot_pnl + perp_pnl + position.funding_earned - position.total_cost - est_close_fee
            
            return total_pnl
            
        except Exception as e:
            logger.error(f"估算盈亏失败 {symbol}: {e}")
            return None
