"""
通知模块 - Telegram 机器人
发送套利机会提醒和交易通知
"""
import asyncio
import aiohttp
from decimal import Decimal
from typing import Optional
from datetime import datetime

from src.utils import logger, config


class TelegramNotifier:
    """
    Telegram 通知器
    发送消息到 Telegram Bot
    """
    
    def __init__(self, token: str = None, chat_id: str = None):
        """
        Args:
            token: Bot Token (从 @BotFather 获取)
            chat_id: 接收消息的 Chat ID
        """
        self.token = token or config.telegram_token
        self.chat_id = chat_id or config.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)
        
        if not self.enabled:
            logger.warning("Telegram 通知未配置，请设置 TELEGRAM_TOKEN 和 TELEGRAM_CHAT_ID")
    
    @property
    def api_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        发送消息
        
        Args:
            text: 消息内容 (支持 HTML/Markdown)
            parse_mode: 解析模式 (HTML 或 Markdown)
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug(f"[Telegram] 未启用，消息: {text[:50]}...")
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}/sendMessage"
                data = {
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                }
                
                async with session.post(url, json=data) as resp:
                    if resp.status == 200:
                        logger.debug(f"[Telegram] 消息发送成功")
                        return True
                    else:
                        error = await resp.text()
                        logger.error(f"[Telegram] 发送失败: {error}")
                        return False
                        
        except Exception as e:
            logger.error(f"[Telegram] 发送异常: {e}")
            return False
    
    async def notify_opportunity(
        self,
        exchange: str,
        symbol: str,
        funding_rate: Decimal,
        expected_profit: Decimal,
        position_size: Decimal = None,
    ) -> bool:
        """
        发送套利机会通知
        """
        rate_pct = funding_rate * 100
        direction = "📈 正费率 (做空收息)" if funding_rate > 0 else "📉 负费率 (做多收息)"
        
        text = (
            f"🎯 <b>发现套利机会</b>\n\n"
            f"交易所: <code>{exchange.upper()}</code>\n"
            f"交易对: <code>{symbol}</code>\n"
            f"费率: <code>{rate_pct:+.4f}%</code>\n"
            f"方向: {direction}\n"
            f"预期收益: <code>${expected_profit:.2f}</code>\n"
        )
        
        if position_size:
            text += f"建议仓位: <code>${position_size:.0f}</code>\n"
        
        text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return await self.send_message(text)
    
    async def notify_trade(
        self,
        action: str,  # "开仓" 或 "平仓"
        symbol: str,
        spot_qty: Decimal,
        spot_price: Decimal,
        perp_qty: Decimal,
        perp_price: Decimal,
        pnl: Decimal = None,
    ) -> bool:
        """
        发送交易通知
        """
        emoji = "🟢" if action == "开仓" else "🔴"
        
        text = (
            f"{emoji} <b>交易{action}</b>\n\n"
            f"交易对: <code>{symbol}</code>\n"
            f"现货: <code>{spot_qty:.6f} @ {spot_price:.2f}</code>\n"
            f"合约: <code>{perp_qty:.6f} @ {perp_price:.2f}</code>\n"
        )
        
        if pnl is not None:
            pnl_emoji = "💰" if pnl >= 0 else "💸"
            text += f"盈亏: {pnl_emoji} <code>${pnl:+.2f}</code>\n"
        
        text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return await self.send_message(text)
    
    async def notify_funding_income(
        self,
        symbol: str,
        rate: Decimal,
        income: Decimal,
        total_income: Decimal,
    ) -> bool:
        """
        发送费率收入通知
        """
        rate_pct = rate * 100
        
        text = (
            f"💵 <b>资金费率结算</b>\n\n"
            f"交易对: <code>{symbol}</code>\n"
            f"费率: <code>{rate_pct:+.4f}%</code>\n"
            f"本次收入: <code>${income:.4f}</code>\n"
            f"累计收入: <code>${total_income:.4f}</code>\n"
            f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        return await self.send_message(text)
    
    async def notify_risk_alert(
        self,
        symbol: str,
        reason: str,
        severity: int,
    ) -> bool:
        """
        发送风险告警
        """
        if severity >= 8:
            emoji = "🚨"
            level = "严重"
        elif severity >= 5:
            emoji = "⚠️"
            level = "警告"
        else:
            emoji = "ℹ️"
            level = "提醒"
        
        text = (
            f"{emoji} <b>风险{level}</b>\n\n"
            f"交易对: <code>{symbol}</code>\n"
            f"原因: {reason}\n"
            f"严重程度: {severity}/10\n"
            f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        return await self.send_message(text)
    
    async def notify_startup_status(
        self,
        spot_balance: Decimal,
        perp_balance: Decimal,
        positions_count: int,
        estimated_pnl: Decimal = Decimal("0"),
        position_details: list = None,
        total_income: Decimal = Decimal("0"),
    ) -> bool:
        """
        发送启动状态报告
        """
        total_balance = spot_balance + perp_balance
        # 简单估算收益率: 总收入 / 总权益 (注意: 这不是严谨的 ROI，仅供参考)
        yield_rate = (total_income / total_balance * 100) if total_balance > 0 else Decimal(0)
        
        text = (
            f"🚀 <b>机器人启动报告</b>\n\n"
            f"💰 <b>账户资产</b>\n"
            f"  • 总权益: <code>${total_balance:.2f}</code>\n"
            f"  • 累计收益: <code>${total_income:.4f}</code>\n"
            f"  • 收益率: <code>{yield_rate:.2f}%</code>\n\n"
            f"📊 <b>持仓概览</b>\n"
            f"  • 持仓数量: <code>{positions_count}</code>\n"
        )
        
        if estimated_pnl != 0:
            pnl_emoji = "💰" if estimated_pnl >= 0 else "💸"
            text += f"  • 浮动盈亏: {pnl_emoji} <code>${estimated_pnl:+.4f}</code>\n"
            
        if position_details:
            text += f"\n📝 <b>持仓明细</b>\n"
            for p in position_details:
                # p = {'symbol', 'pnl', 'net_profit', 'managed', ...}
                payback = p.get('payback', 'N/A')
                net_profit = p.get('net_profit', p['pnl']) # fallback
                status_emoji = "🟢" if net_profit >= 0 else "⏳"
                
                # 未托管警告
                if not p.get('managed', True):
                    status_emoji = "⚠️"
                    payback = "未托管(仅合约)"
                
                text += (
                    f"  • <b>{p['symbol']}</b> {status_emoji}\n"
                    f"    净赚: <code>${net_profit:+.4f}</code> (含费/息)\n"
                    f"    回本: {payback}\n"
                )

        text += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return await self.send_message(text)

    async def notify_status_update(
        self,
        total_balance: Decimal,
        total_unrealized_pnl: Decimal,
        total_income: Decimal,
        today_income: Decimal,
        position_details: list,
        total_position_value: Decimal = Decimal("0"),
    ) -> bool:
        """
        发送定期状态更新
        """
        yield_rate = (total_income / total_balance * 100) if total_balance > 0 else Decimal(0)
        
        text = (
            f"📈 <b>定期状态播报</b>\n\n"
            f"💰 <b>资产状况</b>\n"
            f"  • 总金额: <code>${total_balance:.2f}</code>\n"
            f"  • 持仓价值: <code>${total_position_value:.2f}</code>\n"
            f"  • 累计收益: <code>${total_income:.4f}</code> ({yield_rate:.2f}%)\n"
            f"  • 今日收入: <code>${today_income:.4f}</code>\n\n"
            f"📝 <b>持仓详情</b> (共 {len(position_details)} 个)\n"
        )
        
        if not position_details:
            text += "  (无持仓)\n"
        else:
            for p in position_details:
                # 累计费率收益
                funding_earned = p.get('funding_earned', Decimal(0))
                # 持仓价值
                pos_value = p.get('position_value', Decimal(0))
                # 回本周期 (基于累计收益计算)
                payback = p.get('payback_by_income', 'N/A')
                # 当前费率
                current_rate = p.get('current_rate', Decimal(0))
                # 每期净收益 (费率收入 - 估算手续费摊销)
                net_per_period = p.get('net_per_period', Decimal(0))
                
                # 费率状态: 正数有利可图用绿色，否则黄色
                rate_emoji = "✅" if net_per_period > 0 else "⚠️"
                
                # 状态判定 (基于累计收益)
                status_emoji = "🟢" if funding_earned >= 0 else "⏳"
                note = ""
                
                if not p.get('managed', True):
                    status_emoji = "⚠️"
                    note = "(未托管)"
                
                text += (
                    f"  • <b>{p['symbol']}</b> {status_emoji} {note}\n"
                    f"    价值: <code>${pos_value:.2f}</code>\n"
                    f"    当前费率: <code>{current_rate*100:+.4f}%</code> {rate_emoji}\n"
                    f"    累计收益: <code>${funding_earned:+.4f}</code>\n"
                    f"    回本周期: {payback}\n"
                )
                
        text += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        return await self.send_message(text)

    async def notify_daily_report(
        self,
        total_positions: int,
        total_value: Decimal,
        daily_income: Decimal,
        total_income: Decimal,
    ) -> bool:
        """
        发送每日报告
        """
        text = (
            f"📊 <b>每日报告</b>\n\n"
            f"持仓数量: <code>{total_positions}</code>\n"
            f"总仓位: <code>${total_value:.2f}</code>\n"
            f"今日收入: <code>${daily_income:.4f}</code>\n"
            f"累计收入: <code>${total_income:.4f}</code>\n"
            f"\n📅 {datetime.now().strftime('%Y-%m-%d')}"
        )
        
        return await self.send_message(text)


# 全局实例
telegram = TelegramNotifier()


async def test_telegram():
    """测试 Telegram 连接"""
    if not telegram.enabled:
        print("❌ Telegram 未配置")
        print("请在 .env 文件中设置:")
        print("  TELEGRAM_TOKEN=your_bot_token")
        print("  TELEGRAM_CHAT_ID=your_chat_id")
        return
    
    success = await telegram.send_message("🤖 套利机器人连接测试成功!")
    if success:
        print("✅ Telegram 测试消息发送成功")
    else:
        print("❌ Telegram 发送失败")


if __name__ == "__main__":
    asyncio.run(test_telegram())
