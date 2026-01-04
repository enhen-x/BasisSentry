"""
OKX 交易所适配器
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
from src.utils import logger


class OKXAdapter(ExchangeBase):
    """OKX 交易所适配器"""
    
    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        passphrase: str = "",
        testnet: bool = True,
    ):
        super().__init__(api_key, secret, testnet)
        self.passphrase = passphrase
        
        options = {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,
            "enableRateLimit": True,
        }
        
        if testnet:
            options["sandbox"] = True
            logger.info("OKX 测试网模式已启用")
        
        self.client = ccxt.okx(options)
    
    @property
    def name(self) -> str:
        return "okx"
    
    # ==================== 数据获取 ====================
    
    async def get_funding_rate(self, symbol: str) -> FundingRate:
        """获取单个交易对的资金费率"""
        try:
            result = await self.client.fetch_funding_rate(symbol)
            
            return FundingRate(
                symbol=symbol,
                rate=Decimal(str(result.get("fundingRate", 0))),
                predicted_rate=Decimal(str(result.get("fundingRate", 0))),
                next_funding_time=datetime.fromtimestamp(
                    result.get("fundingTimestamp", 0) / 1000
                ) if result.get("fundingTimestamp") else datetime.now(),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"[OKX] 获取资金费率失败 {symbol}: {e}")
            raise
    
    async def get_funding_rates(self) -> list[FundingRate]:
        """获取所有交易对的资金费率"""
        try:
            await self.client.load_markets()
            result = await self.client.fetch_funding_rates()
            
            rates = []
            for symbol, data in result.items():
                if "/USDT:USDT" in symbol:
                    try:
                        rates.append(FundingRate(
                            symbol=symbol,
                            rate=Decimal(str(data.get("fundingRate") or 0)),
                            predicted_rate=Decimal(str(data.get("fundingRate") or 0)),
                            next_funding_time=datetime.fromtimestamp(
                                data.get("fundingTimestamp", 0) / 1000
                            ) if data.get("fundingTimestamp") else datetime.now(),
                            timestamp=datetime.now(),
                        ))
                    except Exception:
                        continue
            
            return rates
        except Exception as e:
            logger.error(f"[OKX] 获取所有资金费率失败: {e}")
            raise
    
    async def get_orderbook(self, symbol: str, limit: int = 20) -> OrderBook:
        """获取订单簿"""
        try:
            result = await self.client.fetch_order_book(symbol, limit)
            
            return OrderBook(
                symbol=symbol,
                bids=[(Decimal(str(p)), Decimal(str(q))) for p, q in result["bids"]],
                asks=[(Decimal(str(p)), Decimal(str(q))) for p, q in result["asks"]],
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"[OKX] 获取订单簿失败 {symbol}: {e}")
            raise
    
    async def get_ticker(self, symbol: str) -> Ticker:
        """获取行情"""
        try:
            result = await self.client.fetch_ticker(symbol)
            
            return Ticker(
                symbol=symbol,
                last_price=Decimal(str(result.get("last", 0))),
                volume_24h=Decimal(str(result.get("quoteVolume", 0))),
                high_24h=Decimal(str(result.get("high", 0))),
                low_24h=Decimal(str(result.get("low", 0))),
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.error(f"[OKX] 获取行情失败 {symbol}: {e}")
            raise
    
    async def get_tickers(self) -> list[Ticker]:
        """获取所有交易对行情"""
        try:
            result = await self.client.fetch_tickers()
            
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
                        continue
            
            return tickers
        except Exception as e:
            logger.error(f"[OKX] 获取所有行情失败: {e}")
            raise
    
    # ==================== 现货交易 ====================
    
    async def get_spot_balance(self, currency: str = "USDT") -> Decimal:
        """获取现货余额"""
        try:
            balance = await self.client.fetch_balance({"type": "spot"})
            return Decimal(str(balance.get(currency, {}).get("free", 0)))
        except Exception as e:
            logger.error(f"[OKX] 获取现货余额失败: {e}")
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
            params = {"instType": "SPOT"}
            
            if order_type == OrderType.LIMIT and price:
                result = await self.client.create_order(
                    symbol=symbol,
                    type=order_type.value,
                    side=side.value,
                    amount=float(amount),
                    price=float(price),
                    params=params,
                )
            else:
                result = await self.client.create_order(
                    symbol=symbol,
                    type="market",
                    side=side.value,
                    amount=float(amount),
                    params=params,
                )
            
            return self._parse_order(result)
        except Exception as e:
            logger.error(f"[OKX] 下现货单失败 {symbol} {side.value} {amount}: {e}")
            raise
    
    # ==================== 合约交易 ====================
    
    async def get_perp_balance(self, currency: str = "USDT") -> Decimal:
        """获取合约账户余额"""
        try:
            balance = await self.client.fetch_balance({"type": "swap"})
            return Decimal(str(balance.get(currency, {}).get("free", 0)))
        except Exception as e:
            logger.error(f"[OKX] 获取合约余额失败: {e}")
            raise
    
    async def set_leverage(self, symbol: str, leverage: int) -> None:
        """设置杠杆"""
        try:
            await self.client.set_leverage(leverage, symbol)
            logger.info(f"[OKX] 设置杠杆 {symbol} -> {leverage}x")
        except Exception as e:
            logger.error(f"[OKX] 设置杠杆失败 {symbol}: {e}")
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
            params = {
                "instType": "SWAP",
                "reduceOnly": reduce_only,
            }
            
            if order_type == OrderType.LIMIT and price:
                result = await self.client.create_order(
                    symbol=symbol,
                    type=order_type.value,
                    side=side.value,
                    amount=float(amount),
                    price=float(price),
                    params=params,
                )
            else:
                result = await self.client.create_order(
                    symbol=symbol,
                    type="market",
                    side=side.value,
                    amount=float(amount),
                    params=params,
                )
            
            return self._parse_order(result)
        except Exception as e:
            logger.error(f"[OKX] 下合约单失败 {symbol} {side.value} {amount}: {e}")
            raise
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        """获取单个持仓"""
        try:
            positions = await self.client.fetch_positions([symbol])
            for pos in positions:
                if pos.get("contracts", 0) > 0:
                    return self._parse_position(pos)
            return None
        except Exception as e:
            logger.error(f"[OKX] 获取持仓失败 {symbol}: {e}")
            raise
    
    async def get_positions(self) -> list[Position]:
        """获取所有持仓"""
        try:
            positions = await self.client.fetch_positions()
            return [
                self._parse_position(pos)
                for pos in positions
                if pos.get("contracts", 0) > 0
            ]
        except Exception as e:
            logger.error(f"[OKX] 获取所有持仓失败: {e}")
            raise
    
    # ==================== 工具方法 ====================
    
    async def close(self) -> None:
        """关闭连接"""
        await self.client.close()
        logger.info("[OKX] 连接已关闭")
    
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
            fee_currency=data.get("fee", {}).get("currency"),
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
