"""
Binance 交易所适配器
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

import ccxt.async_support as ccxt

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
from src.utils import logger, config


class BinanceAdapter(ExchangeBase):
    """Binance 交易所适配器"""
    
    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        testnet: bool = True,
    ):
        # 如果未提供 API Key，尝试从配置加载
        if not api_key:
            conf = config.get_exchange_config("binance")
            api_key = conf.get("api_key", "")
            secret = conf.get("secret", "")
            # 注意：这里我们使用传入的 testnet 参数，或者是配置中的默认值
            # 如果调用者显式传入了 testnet，则优先使用调用者的
            # 如果没有，则可以考虑使用配置中的（这里保持简单，以参数为准，但要注意 create_exchange 调用时传了 testnet=False）
            
        super().__init__(api_key, secret, testnet)
        
        # 现货客户端
        self.spot = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })
        
        # 永续合约客户端 (USDT-M)
        self.perp = ccxt.binanceusdm({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
        })
        
        # 测试网配置
        if testnet:
            self.spot.set_sandbox_mode(True)
            self.perp.set_sandbox_mode(True)
            logger.info("Binance 测试网模式已启用")
        
        # 强制设置为单向持仓模式 (One-way Mode)
        # 避免 "Order's position side does not match user's setting" 错误
        try:
            # 注意: set_position_mode 需要 await，但 __init__ 是同步的
            # 我们将在首次调用时懒加载，或者使用 sync version (不受支持)
            # 更好的方式是在 create_exchange 后调用一个 init 方法，或者在首次下单前自动检查
            # 暂时: 我们不在这里调，而是修改 place_perp_order 如果报错则尝试切换
            pass
        except Exception as e:
            logger.warning(f"设置单向持仓模式失败: {e}")
    
    @property
    def name(self) -> str:
        return "binance"
    
    # ==================== 数据获取 ====================
    
    async def get_funding_rate(self, symbol: str) -> FundingRate:
        """获取单个交易对的资金费率"""
        try:
            # 获取资金费率
            result = await self.perp.fetch_funding_rate(symbol)
            
            return FundingRate(
                symbol=symbol,
                rate=Decimal(str(result.get("fundingRate", 0))),
                predicted_rate=Decimal(str(result.get("fundingRate", 0))),
                next_funding_time=datetime.fromtimestamp(
                    result.get("fundingTimestamp", 0) / 1000
                ),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"获取资金费率失败 {symbol}: {e}")
            raise
    
    async def get_funding_rates(self) -> list[FundingRate]:
        """获取所有交易对的资金费率"""
        try:
            # 加载市场信息
            await self.perp.load_markets()
            
            # 获取所有永续合约的资金费率
            result = await self.perp.fetch_funding_rates()
            
            rates = []
            for symbol, data in result.items():
                if "/USDT:USDT" in symbol:  # 只取 USDT 本位合约
                    rates.append(FundingRate(
                        symbol=symbol,
                        rate=Decimal(str(data.get("fundingRate", 0))),
                        predicted_rate=Decimal(str(data.get("fundingRate", 0))),
                        next_funding_time=datetime.fromtimestamp(
                            data.get("fundingTimestamp", 0) / 1000
                        ) if data.get("fundingTimestamp") else datetime.now(),
                        timestamp=datetime.now(),
                    ))
            
            return rates
        except Exception as e:
            logger.error(f"获取所有资金费率失败: {e}")
            raise

    async def get_funding_history(self, since: Optional[int] = None, limit: int = 200) -> list[dict]:
        """获取资金费流水 (资金费结算明细)"""
        try:
            rows = await self.perp.fetch_funding_history(symbol=None, since=since, limit=limit)
            payments = []
            for r in rows or []:
                ts = r.get("timestamp") or r.get("info", {}).get("time")
                ts_dt = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()

                raw_rate = (
                    r.get("info", {}).get("fundingRate")
                    if isinstance(r.get("info"), dict)
                    else None
                )
                rate = Decimal(str(raw_rate if raw_rate is not None else r.get("fundingRate", 0)))

                payments.append(
                    {
                        "symbol": r.get("symbol"),
                        "income": Decimal(str(r.get("amount", 0))),
                        "rate": rate,
                        "position_value": Decimal(0),
                        # 用 ISO 字符串方便去重
                        "timestamp": ts_dt.isoformat(),
                    }
                )

            return payments
        except Exception as e:
            logger.error(f"获取资金流水失败: {e}")
            return []
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        """获取订单簿"""
        try:
            result = await self.perp.fetch_order_book(symbol, limit)
            
            return OrderBook(
                symbol=symbol,
                bids=[(Decimal(str(p)), Decimal(str(q))) for p, q in result["bids"]],
                asks=[(Decimal(str(p)), Decimal(str(q))) for p, q in result["asks"]],
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"获取订单簿失败 {symbol}: {e}")
            raise
    
    async def get_ticker(self, symbol: str) -> Ticker:
        """获取行情"""
        try:
            result = await self.perp.fetch_ticker(symbol)
            
            return Ticker(
                symbol=symbol,
                last_price=Decimal(str(result.get("last", 0))),
                volume_24h=Decimal(str(result.get("quoteVolume", 0))),
                high_24h=Decimal(str(result.get("high", 0))),
                low_24h=Decimal(str(result.get("low", 0))),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"获取行情失败 {symbol}: {e}")
            raise
    
    async def get_tickers(self) -> list[Ticker]:
        """获取所有交易对行情"""
        try:
            result = await self.perp.fetch_tickers()
            
            tickers = []
            for symbol, data in result.items():
                if "/USDT:USDT" in symbol:
                    try:
                        tickers.append(Ticker(
                            symbol=symbol,
                            last_price=Decimal(str(data.get("last") or 0)),
                            volume_24h=Decimal(str(data.get("quoteVolume") or 0)),
                            high_24h=Decimal(str(data.get("high") or 0)),
                            low_24h=Decimal(str(data.get("low") or 0)),
                            timestamp=datetime.now(),
                        ))
                    except Exception:
                        # 跳过无效数据
                        continue
            
            return tickers
        except Exception as e:
            logger.error(f"获取所有行情失败: {e}")
            raise
    
    # ==================== 现货交易 ====================
    
    async def get_spot_balance(self, currency: str = "USDT") -> Decimal:
        """获取现货余额"""
        try:
            balance = await self.spot.fetch_balance()
            return Decimal(str(balance.get(currency, {}).get("free", 0)))
        except Exception as e:
            logger.error(f"获取现货余额失败: {e}")
            raise
    
    async def place_spot_order(
        self,
        symbol: str,
        side: OrderSide,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[Decimal] = None,
    ) -> Order:
        """下现货单"""
        try:
            params = {}
            if order_type == OrderType.LIMIT and price:
                result = await self.spot.create_order(
                    symbol=symbol,
                    type=order_type.value,
                    side=side.value,
                    amount=float(amount),
                    price=float(price),
                    params=params,
                )
            else:
                result = await self.spot.create_order(
                    symbol=symbol,
                    type="market",
                    side=side.value,
                    amount=float(amount),
                    params=params,
                )
            
            return self._parse_order(result)
        except Exception as e:
            logger.error(f"下现货单失败 {symbol} {side.value} {amount}: {e}")
            raise
    
    # ==================== 合约交易 ====================
    
    async def get_perp_balance(self, currency: str = "USDT") -> Decimal:
        """获取合约账户余额"""
        try:
            balance = await self.perp.fetch_balance()
            return Decimal(str(balance.get(currency, {}).get("free", 0)))
        except Exception as e:
            logger.error(f"获取合约余额失败: {e}")
            raise
    
    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """设置杠杆"""
        try:
            await self.perp.set_leverage(leverage, symbol)
            logger.info(f"设置杠杆 {symbol} -> {leverage}x")
        except Exception as e:
            logger.error(f"设置杠杆失败 {symbol}: {e}")
            raise
    
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
        try:
            params = {"reduceOnly": reduce_only}
            
            if order_type == OrderType.LIMIT and price:
                result = await self.perp.create_order(
                    symbol=symbol,
                    type=order_type.value,
                    side=side.value,
                    amount=float(amount),
                    price=float(price),
                    params=params,
                )
            else:
                result = await self.perp.create_order(
                    symbol=symbol,
                    type="market",
                    side=side.value,
                    amount=float(amount),
                    params=params,
                )
            
            return self._parse_order(result)
            
        except Exception as e:
            # 优先处理持仓模式错误: code -4061 "Order's position side does not match user's setting."
            if "-4061" in str(e):
                logger.warning(f"检测到持仓模式不匹配，尝试切换为单向模式... ({symbol})")
                try:
                    # 切换到单向模式 (One-way Mode)
                    await self.perp.set_position_mode(hedged=False, symbol=symbol)
                    logger.info(f"已切换为单向模式 {symbol}，重试下单...")
                    
                    # 重试下单
                    if order_type == OrderType.LIMIT and price:
                        result = await self.perp.create_order(
                            symbol=symbol,
                            type=order_type.value,
                            side=side.value,
                            amount=float(amount),
                            price=float(price),
                            params=params,
                        )
                    else:
                        result = await self.perp.create_order(
                            symbol=symbol,
                            type="market",
                            side=side.value,
                            amount=float(amount),
                            params=params,
                        )
                    return self._parse_order(result)
                except Exception as switch_e:
                    logger.error(f"切换持仓模式失败: {switch_e}")
                    # 切换失败，抛出原始错误
                    logger.error(f"下合约单失败 {symbol} {side.value} {amount}: {e}")
                    raise e
            
            # 其他错误
            logger.error(f"下合约单失败 {symbol} {side.value} {amount}: {e}")
            raise
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        """获取单个持仓"""
        try:
            positions = await self.perp.fetch_positions([symbol])
            for pos in positions:
                if pos.get("contracts", 0) > 0:
                    return self._parse_position(pos)
            return None
        except Exception as e:
            logger.error(f"获取持仓失败 {symbol}: {e}")
            raise
    
    async def get_positions(self) -> list[Position]:
        """获取所有持仓"""
        try:
            positions = await self.perp.fetch_positions()
            return [
                self._parse_position(pos)
                for pos in positions
                if pos.get("contracts", 0) > 0
            ]
        except Exception as e:
            logger.error(f"获取所有持仓失败: {e}")
            raise
    
    # ==================== 工具方法 ====================
    
    async def close(self) -> None:
        """关闭连接"""
        await self.spot.close()
        await self.perp.close()
        logger.info("Binance 连接已关闭")
    
    def _parse_order(self, data: dict) -> Order:
        """解析订单数据"""
        return Order(
            id=data.get("id", ""),
            symbol=data.get("symbol", ""),
            side=OrderSide(data.get("side", "buy")),
            type=OrderType(data.get("type", "market")),
            price=Decimal(str(data.get("price") or data.get("average", 0))),
            amount=Decimal(str(data.get("amount", 0))),
            filled=Decimal(str(data.get("filled", 0))),
            remaining=Decimal(str(data.get("remaining", 0))),
            status=data.get("status", ""),
            timestamp=datetime.now(),
            fee=Decimal(str(data.get("fee", {}).get("cost", 0))) if data.get("fee") else None,
            fee_currency=(data.get("fee") or {}).get("currency"),
        )
    
    def _parse_position(self, data: dict) -> Position:
        """解析持仓数据"""
        side_str = data.get("side", "long")
        side = PositionSide.LONG if side_str == "long" else PositionSide.SHORT
        
        return Position(
            symbol=data.get("symbol", ""),
            side=side,
            size=Decimal(str(data.get("contracts", 0))),
            entry_price=Decimal(str(data.get("entryPrice", 0))),
            mark_price=Decimal(str(data.get("markPrice", 0))),
            unrealized_pnl=Decimal(str(data.get("unrealizedPnl", 0))),
            leverage=int(data.get("leverage", 1)),
            margin=Decimal(str(data.get("initialMargin", 0))),
            liquidation_price=Decimal(str(data.get("liquidationPrice", 0)))
            if data.get("liquidationPrice") else None,
        )
