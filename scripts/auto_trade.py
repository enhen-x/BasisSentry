"""
自动交易脚本 - 高收益套利自动开仓
当发现费率 >= 阈值的机会时自动开仓并发送通知
"""
import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.exchange import create_exchange, OrderSide, OrderType
from src.strategy.scanner import Scanner
from src.strategy.executor import Executor
from src.core.funding_tracker import funding_tracker
from src.core.risk import RiskManager, RiskAction
from src.utils import setup_logger, logger, config, telegram, format_rate, format_usdt


# ==================== 配置参数 ====================
MIN_RATE_THRESHOLD = Decimal("0.0001")   # 0.01% (极低阈值，确保开仓)
EXIT_RATE_THRESHOLD = Decimal("0.0000") # 0.00% 离场阈值 (只要不亏就不走)
POSITION_SIZE = Decimal("12")          # 每次开仓金额 (USDT)
MAX_POSITIONS = 3                      # 最多同时持仓数量
SCAN_INTERVAL = 300                    # 扫描间隔（秒）5分钟

# 安全限制
MIN_DEPTH = Decimal("3000")            # 最小流动性深度 (5000U 适合小资金)
MAX_SPREAD = Decimal("0.005")          # 最大价差 0.5%
# ==================================================


class AutoTrader:
    """自动交易机器人"""
    
    def __init__(self):
        self.exchange = None
        self.scanner = None
        self.executor = None
        self.scanner = None
        self.scanner = None
        self.executor = None
        self.risk_manager = None
        self.running = True
        self.last_funding_check = datetime.now()

    async def sync_funding_history(self):
        """从交易所同步资金费流水到本地"""
        if not hasattr(self.exchange, "get_funding_history"):
            logger.warning("当前交易所未实现资金流水同步")
            return

        since_ms = int((datetime.utcnow() - timedelta(days=3)).timestamp() * 1000)
        try:
            payments = await self.exchange.get_funding_history(since=since_ms, limit=500)
            added = funding_tracker.sync_remote_payments(payments)
            logger.info(f"资金流水同步完成，新增 {added} 条记录")
        except Exception as e:
            logger.error(f"同步资金流水失败: {e}")
    
    async def _get_portfolio_status(self):
        """
        获取投资组合综合状态 (余额、收入、持仓价值、累计收益、回本周期)
        """
        # 1. 获取现货/合约余额并换算总权益
        spot_balances = await self.exchange.spot.fetch_balance()
        perp_balances = await self.exchange.perp.fetch_balance()

        spot_equity = Decimal("0")
        for asset, bal in spot_balances.items():
            if not isinstance(bal, dict):
                continue
            qty = Decimal(str(bal.get("total", 0)))
            if qty == 0:
                continue
            if asset == "USDT":
                spot_equity += qty
            else:
                try:
                    ticker = await self.exchange.spot.fetch_ticker(f"{asset}/USDT")
                    price = Decimal(str(ticker["last"]))
                    spot_equity += qty * price
                except Exception:
                    continue

        # 合约账户权益 (钱包余额 + 未实现盈亏更稳妥；若接口无该字段则退回 total)
        perp_wallet = Decimal(str(perp_balances.get("USDT", {}).get("total", 0)))
        perp_unrealized = Decimal("0")
        try:
            perp_positions = await self.exchange.perp.fetch_positions()
            for p in perp_positions:
                pnl = Decimal(str(p.get("unRealizedProfit") or p.get("info", {}).get("unRealizedProfit") or 0))
                perp_unrealized += pnl
        except Exception:
            pass
        perp_equity = perp_wallet + perp_unrealized

        spot_bal = Decimal(str(spot_balances.get("USDT", {}).get("free", 0)))
        perp_bal = Decimal(str(perp_balances.get("USDT", {}).get("free", 0)))
        total_bal = spot_equity + perp_equity
        
        # 2. 获取收入统计
        summary = funding_tracker.get_summary()
        funding_sum_positions = Decimal("0")
        
        # 3. 计算持仓信息
        total_net_pnl = Decimal("0")
        total_position_value = Decimal("0")
        details = []
        
        # 获取最新的合约持仓数据
        perp_map = {}
        try:
            positions = await self.exchange.perp.fetch_positions()
            for p in positions:
                perp_map[p['symbol']] = p
        except Exception as e:
            logger.warning(f"获取合约数据失败: {e}")
            
        # 遍历本地记录的套利持仓 (已托管)
        managed_symbols = set()
        
        for symbol, pos in self.executor.positions.items():
            managed_symbols.add(symbol)
            try:
                # A. 计算持仓价值（现货与合约分别）
                spot_symbol = f"{pos.base_currency}/USDT"
                ticker = await self.exchange.spot.fetch_ticker(spot_symbol)
                current_price = Decimal(str(ticker['last']))
                # 优先用交易所实际合约数量估算名义价值，避免本地记录不一致
                actual_perp_qty = pos.perp_qty
                if symbol in perp_map:
                    actual_perp_qty = Decimal(str(perp_map[symbol]['info']['positionAmt']))
                spot_total_qty = Decimal(str(spot_balances.get(pos.base_currency, {}).get('total', 0)))
                spot_value = spot_total_qty * current_price
                perp_value = abs(actual_perp_qty) * current_price
                position_value = perp_value
                total_position_value += position_value
                
                # B. 获取累计费率收益 (从 funding_tracker 获取)
                funding_earned = funding_tracker.get_total_income(symbol)
                funding_sum_positions += funding_earned

                # 手续费估算（现货0.1%*2 + 合约0.05%*2 ≈0.3%名义仓位）
                total_fees = position_value * Decimal("0.003")
                net_income_after_fee = funding_earned - total_fees
                
                # C. 获取当前费率
                rate_info = self.scanner.get_cached_rate(symbol)
                if not rate_info:
                    rate_info = await self.exchange.get_funding_rate(symbol)
                current_rate = rate_info.rate if rate_info else Decimal(0)
                
                # D. 计算每期净收益 (费率收入 - 手续费摊销)
                # 每期费率收入
                funding_income_per_period = position_value * abs(current_rate)
                # 估算开平仓总手续费 (现货 0.1% x2 + 合约 0.05% x2)
                total_fees = position_value * Decimal("0.003")  # 0.3% 总成本
                # 假设持仓 30 天 (90期) 后平仓，每期摊销的手续费
                fee_per_period = total_fees / 90
                # 每期净收益
                net_per_period = funding_income_per_period - fee_per_period
                
                # E. 基于累计收益计算回本周期
                # 需要回本的金额 = 手续费成本 - 已累计收益
                remaining_to_breakeven = total_fees - funding_earned
                
                if remaining_to_breakeven <= 0:
                    payback_text = "✅ 已回本"
                elif funding_income_per_period > 0:
                    # 使用当期费率收入估算 (不减去摊销，因为手续费是固定成本，不是每期产生)
                    periods_to_breakeven = remaining_to_breakeven / funding_income_per_period
                    days = periods_to_breakeven / 3  # 每天3期
                    if days > 100:
                        payback_text = ">100天"
                    elif days < 1:
                        payback_text = f"{periods_to_breakeven:.1f}期"
                    else:
                        payback_text = f"{days:.1f}天"
                else:
                    payback_text = "⚠️ 当期无收益"
                
                # F. 计算浮动盈亏 (用于参考)
                spot_pnl = (current_price - pos.spot_avg_price) * pos.spot_qty
                perp_pnl = Decimal("0")
                if symbol in perp_map:
                    perp_pnl = Decimal(str(perp_map[symbol]['info']['unRealizedProfit']))
                unrealized_net_pnl = spot_pnl + perp_pnl
                total_net_pnl += unrealized_net_pnl
                
                details.append({
                    'symbol': symbol,
                    'position_value': position_value,
                    'spot_value': spot_value,
                    'perp_value': perp_value,
                    'spot_qty': spot_total_qty,
                    'perp_qty': actual_perp_qty,
                    'funding_earned': funding_earned,
                    'net_income_after_fee': net_income_after_fee,
                    'current_rate': current_rate,
                    'net_per_period': net_per_period,
                    'payback_by_income': payback_text,
                    'managed': True,
                    # 保留旧字段兼容
                    'pnl': unrealized_net_pnl,
                    'amt': pos.perp_qty,
                    'entry_price': pos.spot_avg_price,
                })
                
            except Exception as e:
                logger.error(f"计算 {symbol} 状态失败: {e}")
        
        # 检查未托管的合约持仓 (Exchange has it, but Bot doesn't track it)
        for symbol, p_data in perp_map.items():
            if symbol not in managed_symbols and float(p_data['info']['positionAmt']) != 0:
                try:
                    pnl = Decimal(str(p_data['info']['unRealizedProfit']))
                    amt = Decimal(str(p_data['info']['positionAmt']))
                    entry_price = Decimal(str(p_data['info']['entryPrice']))
                    pos_value = abs(amt) * entry_price
                    total_position_value += pos_value
                    
                    details.append({
                        'symbol': symbol,
                        'position_value': pos_value,
                        'funding_earned': Decimal(0),
                        'current_rate': Decimal(0),
                        'net_per_period': Decimal(0),
                        'payback_by_income': "⚠️ 未托管",
                        'managed': False,
                        'pnl': pnl,
                        'amt': amt,
                        'entry_price': entry_price,
                    })
                    total_net_pnl += pnl
                except Exception as e:
                    logger.error(f"处理未托管持仓 {symbol} 失败: {e}")
                
        return {
            "spot_bal": spot_bal,
            "perp_bal": perp_bal,
            "spot_equity": spot_equity,
            "perp_equity": perp_equity,
            "total_bal": total_bal,
            "total_income": summary["total_income"],
            "today_income": summary["today_income"],
            "funding_sum_positions": funding_sum_positions,
            "total_pnl": total_net_pnl,
            "total_position_value": total_position_value,
            "details": details,
            "position_count": len(details)
        }

    async def check_funding_income(self):
        """检查并记录费率收入"""
        now = datetime.now()
        
        # 简单的资金费率结算时间检查 (UTC 00:00, 08:00, 16:00)
        # 对应东八区 08:00, 16:00, 00:00
        # 我们每小时检查一次，如果当前时间超过结算时间且未记录，则记录
        
        # 为了演示和简化，我们直接检查所有持仓的当前费率
        # 如果当前时间接近结算时间 (前后 5 分钟)，则记录
        # 注意: 实际应该通过交易所接口查询资金流水
        
        if not self.executor.positions:
            return

        try:
            # 遍历持仓更新费率
            for symbol, position in self.executor.positions.items():
                # 获取最新费率
                rate_info = self.scanner.get_cached_rate(symbol)
                current_rate = rate_info.rate if rate_info else Decimal(0)
                
                # 估算本期收入
                income = position.notional_value * abs(current_rate)
                
                # 记录到日志 (这里做了一个简单的模拟记录，实际应当判断时间)
                # 仅当分钟数为 0-5 分时记录 (模拟结算时刻)
                if now.minute < 5 and (now.hour % 8 == 0): # UTC 0, 8, 16
                   funding_tracker.record_funding(
                       symbol=symbol,
                       rate=current_rate,
                       position_value=position.notional_value
                   )
                   logger.info(f"💰 记录资金费收入: {symbol} +{income:.4f} U")
                   
        except Exception as e:
            logger.error(f"记录资金费出错: {e}")

    async def sync_orphan_positions(self):
        """
        同步/认领未托管的交易所持仓
        """
        try:
            logger.info("  🔄 检查未托管的持仓...")
            
            # 1. 获取所有通过API能看到的合约持仓
            perp_positions = await self.exchange.perp.fetch_positions()
            perp_map = {p['symbol']: p for p in perp_positions if float(p['info']['positionAmt']) != 0}
            
            if not perp_map:
                return

            # 2. 获取现货余额
            spot_balances = await self.exchange.spot.fetch_balance()
            
            from src.strategy.executor import ArbitragePosition, _get_position_store
            
            newly_adopted = []
            
            for symbol, p_data in perp_map.items():
                # 如果已经在托管列表中，跳过
                if symbol in self.executor.positions:
                    continue
                    
                # 解析基础币种 (e.g. BTC/USDT:USDT -> BTC)
                base = symbol.split('/')[0]
                perp_amt = Decimal(str(p_data['info']['positionAmt']))
                perp_entry_price = Decimal(str(p_data['info']['entryPrice']))
                
                # 检查现货余额是否足够对冲 (允许 10% 的误差/磨损)
                spot_free = Decimal(str(spot_balances.get(base, {}).get('free', 0)))
                target_spot_qty = abs(perp_amt)
                
                if spot_free >= target_spot_qty * Decimal("0.9"):
                    logger.info(f"  🔍 发现未托管持仓 {symbol}, 现货余额充足 ({spot_free}), 正在认领...")
                    
                    # 创建新的套利持仓对象
                    # 注意: 我们不知道真实的现货买入价，暂且用合约开仓价代替
                    # 这样显示的"净盈亏"会从 0 开始计算 (忽略之前的波动)
                    new_pos = ArbitragePosition(
                        symbol=symbol,
                        base_currency=base,
                        spot_qty=target_spot_qty, # 默认认为是完美对冲的
                        spot_avg_price=perp_entry_price, # 估算值
                        spot_value=target_spot_qty * perp_entry_price,
                        perp_qty=perp_amt,
                        perp_avg_price=perp_entry_price,
                        perp_value=perp_amt * perp_entry_price,
                        leverage=int(p_data['info']['leverage']),
                        opened_at=datetime.now() # 记录认领时间
                    )
                    
                    # 保存到内存和文件
                    self.executor.positions[symbol] = new_pos
                    _get_position_store().save(new_pos)
                    
                    newly_adopted.append(symbol)
                    
            if newly_adopted:
                msg = f"✅ 已自动认领 {len(newly_adopted)} 个未托管持仓: {', '.join(newly_adopted)}"
                logger.info(msg)
                if telegram.enabled:
                    await telegram.send_message(f"🔄 <b>同步持仓</b>\n{msg}\n(注: 现货成本已按合约开仓价估算)")
                    
        except Exception as e:
            logger.error(f"同步未托管持仓失败: {e}")

    async def send_periodic_status(self):
        """发送定期状态更新"""
        if not telegram.enabled:
            return

        try:
            status = await self._get_portfolio_status()
            
            await telegram.notify_status_update(
                total_balance=status["total_bal"],
                total_unrealized_pnl=status["total_pnl"],
                total_income=status["total_income"],
                today_income=status["today_income"],
                position_details=status["details"],
                total_position_value=status["total_position_value"]
            )
            
        except Exception as e:
            logger.error(f"发送定期报告失败: {e}")

    async def start(self):
        """启动自动交易"""
        logger.info("=" * 70)
        logger.info("🤖 自动套利交易机器人启动")
        logger.info("=" * 70)
        logger.info(f"  费率阈值: {format_rate(MIN_RATE_THRESHOLD)} (超过此值自动开仓)")
        logger.info(f"  离场阈值: {format_rate(EXIT_RATE_THRESHOLD)} (低于此值自动平仓)")
        logger.info(f"  单笔仓位: {format_usdt(POSITION_SIZE)}")
        logger.info(f"  最大持仓: 自动管理 (基于余额+2x安全边际)")
        logger.info(f"  扫描间隔: {SCAN_INTERVAL} 秒")
        logger.info(f"  Telegram: {'✅ 已启用' if telegram.enabled else '⚠️  未配置'}")
        logger.info("=" * 70)
        logger.info("")
        
        self.exchange = create_exchange("binance", testnet=False)
        self.scanner = Scanner(self.exchange)
        self.executor = Executor(self.exchange, load_positions=True)
        self.risk_manager = RiskManager()
        
        # 同步未托管的持仓
        await self.sync_orphan_positions()
        # 同步交易所资金流水到本地
        await self.sync_funding_history()
        
        # 检查账户状态并发送报告
        try:
            logger.info("正在获取账户权益报告...")
            status = await self._get_portfolio_status()

            if telegram.enabled:
                await telegram.notify_startup_status(
                    spot_balance=status["spot_bal"],
                    perp_balance=status["perp_bal"],
                    positions_count=status["position_count"],
                    estimated_pnl=status["total_pnl"],
                    position_details=status["details"],
                    total_income=status["total_income"]
                )
                
                # 发送参数配置
                await telegram.send_message(
                    f"⚙️ <b>运行参数配置</b>\n\n"
                    f"费率阈值: <code>{MIN_RATE_THRESHOLD*100:.2f}%</code>\n"
                    f"单笔仓位: <code>${POSITION_SIZE}</code>\n"
                    f"最大持仓: <code>自动管理 (基于资金)</code>\n"
                    f"扫描间隔: <code>{SCAN_INTERVAL} 秒</code>"
                )
        except Exception as e:
            logger.error(f"发送启动报告失败: {e}")
        
        try:
            while self.running:
                await self.scan_and_trade()
                await self.check_funding_income()
                
                # 发送定期状态报告
                await self.send_periodic_status()
                
                logger.info(f"⏳ 等待 {SCAN_INTERVAL} 秒后再次扫描...")
                logger.info("")
                await asyncio.sleep(SCAN_INTERVAL)
        
        except KeyboardInterrupt:
            logger.info("")
            logger.info("👋 机器人已停止")
            if telegram.enabled:
                await telegram.send_message("🛑 自动交易机器人已停止")
        finally:
            if self.exchange:
                await self.exchange.close()
    
    async def calculate_dynamic_capacity(self) -> int:
        """
        根据资金计算动态最大持仓数量 (自动仓位管理)
        """
        spot_bal = await self.exchange.get_spot_balance("USDT")
        perp_bal = await self.exchange.get_perp_balance("USDT")
        
        # 1. 现货能力：全额购买
        # 预留 1% 作为摩擦成本
        spot_capacity = int((spot_bal * Decimal("0.99")) // POSITION_SIZE)
        
        # 2. 合约能力：作为保证金
        # 假设杠杆 2x (LEVERAGE defined globally or defaulted to 2)
        # 安全系数 2.0 (即保留 1倍的缓冲: 2x杠杆只需要50%保证金，但我们按100%准备，相当于1x的安全性)
        # 这样即使币价翻倍也不会爆仓 -> 极其安全
        leverage = 2
        safety_ratio = Decimal("2.0") 
        margin_per_position = (POSITION_SIZE / leverage) * safety_ratio
        
        # 实际上 margin_per_position = POSITION_SIZE. 也就是1:1准备保证金。
        # 如果追求资金利用率，可以降到 1.5 (保留50%空闲)
        
        perp_capacity = int(perp_bal // margin_per_position)
        
        # 3. 最终能力
        max_pos = min(spot_capacity, perp_capacity)
        
        # 至少允许开一个(如果余额刚够的话)，但不能是负数
        return max(0, max_pos)

    async def verify_and_fix_positions(self):
        """
        验证持仓一致性并自动修复
        检查每个托管持仓是否在交易所端都有匹配的现货和合约
        """
        if not self.executor.positions:
            return
            
        logger.info("  🔍 验证持仓一致性...")
        
        try:
            # 获取交易所实际数据
            perp_positions = await self.exchange.perp.fetch_positions()
            perp_map = {p['symbol']: p for p in perp_positions}
            spot_balances = await self.exchange.spot.fetch_balance()
            
            from src.strategy.executor import _get_position_store
            
            issues_found = []
            
            for symbol, pos in list(self.executor.positions.items()):
                base = pos.base_currency
                
                # 检查合约端
                perp_data = perp_map.get(symbol)
                perp_amt = Decimal(str(perp_data['info']['positionAmt'])) if perp_data else Decimal(0)
                has_perp = abs(perp_amt) > Decimal("0.001")
                
                # 检查现货端
                spot_free = Decimal(str(spot_balances.get(base, {}).get('free', 0)))
                spot_total = Decimal(str(spot_balances.get(base, {}).get('total', 0)))
                has_spot = spot_total >= pos.spot_qty * Decimal("0.9")
                
                if has_perp and has_spot:
                    continue  # 正常
                
                # 发现不一致！
                issue = f"{symbol}: 合约{'✅' if has_perp else '❌'} 现货{'✅' if has_spot else '❌'}"
                issues_found.append(issue)
                logger.warning(f"  ⚠️ 持仓不一致: {issue}")
                
                # 自动修复
                try:
                    if has_perp and not has_spot:
                        # 有合约没现货 -> 平掉合约
                        logger.info(f"    🔧 正在平掉孤立合约 {symbol}...")
                        await self.exchange.place_perp_order(
                            symbol=symbol,
                            side=OrderSide.BUY if perp_amt < 0 else OrderSide.SELL,
                            amount=abs(perp_amt),
                            order_type=OrderType.MARKET,
                        )
                        logger.info(f"    ✅ 合约已平仓")
                        
                    elif has_spot and not has_perp:
                        # 有现货没合约 -> 卖掉现货
                        logger.info(f"    🔧 正在卖出孤立现货 {base}...")
                        spot_symbol = f"{base}/USDT"
                        await self.exchange.place_spot_order(
                            symbol=spot_symbol,
                            side=OrderSide.SELL,
                            amount=spot_total,
                            order_type=OrderType.MARKET,
                        )
                        logger.info(f"    ✅ 现货已卖出")
                    
                    # 从本地记录中删除
                    del self.executor.positions[symbol]
                    _get_position_store().delete(symbol)
                    logger.info(f"    ✅ 已从本地记录中移除 {symbol}")
                    
                except Exception as fix_err:
                    logger.error(f"    ❌ 修复失败: {fix_err}")
                    
            if issues_found:
                # 发送告警
                if telegram.enabled:
                    await telegram.send_message(
                        f"🚨 <b>持仓异常自动修复</b>\n\n"
                        f"发现 {len(issues_found)} 个不一致持仓:\n"
                        + "\n".join(f"  • {i}" for i in issues_found)
                        + "\n\n已尝试自动处理，请检查账户。"
                    )
                    
        except Exception as e:
            logger.error(f"验证持仓失败: {e}")

    async def scan_and_trade(self):
        """扫描并自动交易"""
        try:
            # 先验证持仓一致性
            await self.verify_and_fix_positions()
            
            # 监控现有持仓风险
            await self.monitor_risks()

            logger.info(f"🔄 扫描市场... ({datetime.now().strftime('%H:%M:%S')})")
            
            # 计算动态持仓能力
            max_dynamic_positions = await self.calculate_dynamic_capacity()
            current_positions = len(self.executor.positions)
            
            logger.info(f"  当前持仓: {current_positions}/{max_dynamic_positions} (自动仓位管理)")
            
            if current_positions >= max_dynamic_positions: 
                logger.info(f"  ⚠️  已达当前资金支持的最大持仓 ({max_dynamic_positions})")
                # 即使满仓也扫描市场寻找更好机会 (轮动逻辑保持不变)
                pools = await self.scanner.scan()
                if pools:
                    # 筛选高质量池子作为候选
                    candidates = [
                        p for p in pools 
                        if abs(p.funding_rate) >= MIN_RATE_THRESHOLD
                        and p.depth_05pct >= MIN_DEPTH
                        and p.symbol not in self.executor.positions
                        and (not config.allow_negative_rates and p.funding_rate < 0) == False
                    ]
                    candidates.sort(key=lambda x: abs(x.funding_rate), reverse=True)
                    
                    if candidates:
                        await self.optimize_positions(candidates)
                return
            
            # 扫描市场
            pools = await self.scanner.scan()
            
            if not pools:
                logger.info("  未发现符合条件的机会")
                return
            
            # 筛选高费率机会
            opportunities = [
                p for p in pools
                if abs(p.funding_rate) >= MIN_RATE_THRESHOLD
                and p.depth_05pct >= MIN_DEPTH
                and p.spread <= MAX_SPREAD
                and p.symbol not in self.executor.positions  # 避免重复开仓
            ]
            
            if not opportunities:
                logger.info(f"  扫描 {len(pools)} 个池子，无超过阈值的机会")
                return
            
            # 按费率排序，选择最高的
            opportunities.sort(key=lambda x: abs(x.funding_rate), reverse=True)
            best = opportunities[0]
            
            logger.info(f"  🎯 发现高费率机会: {best.symbol}")
            logger.info(f"     费率: {format_rate(best.funding_rate)}")
            logger.info(f"     深度: {format_usdt(best.depth_05pct)}")
            logger.info(f"     价差: {best.spread:.4%}")
            logger.info("")
            
            # 执行开仓
            await self.open_position(best)
        
        except Exception as e:
            logger.error(f"❌ 扫描异常: {e}")
            if telegram.enabled:
                await telegram.send_message(f"⚠️ 扫描异常:\n{str(e)[:200]}")
    
    async def optimize_positions(self, market_opportunities: list):
        """
        持仓优化 (资金轮动)
        检查是否有更好的机会值得换仓
        """
        if not config.rotation_config.get("enabled", False):
            return

        if not self.executor.positions:
            return

        logger.info("  🔄 检查持仓优化 (资金轮动)...")
        
        # 1. 获取最佳新机会
        if not market_opportunities:
            return
            
        best_new_opportunity = market_opportunities[0]
        new_rate = abs(best_new_opportunity.funding_rate)
        
        min_improvement = Decimal(str(config.rotation_config.get("min_rate_improvement", 0.0005)))
        min_profit_threshold = Decimal(str(config.rotation_config.get("min_profit_threshold", 0)))
        
        # 2. 遍历现有持仓
        for symbol, position in list(self.executor.positions.items()):
            # 获取当前持仓的最新费率
            current_rate_info = self.scanner.get_cached_rate(symbol)
            if not current_rate_info:
                continue
            current_rate = abs(current_rate_info.rate)
            
            # 检查是否值得换仓: 新费率 > 旧费率 + 阈值
            if new_rate <= current_rate + min_improvement:
                continue
                
            # 检查是否回本
            pnl = await self.executor.estimate_pnl(symbol)
            if pnl is None:
                continue
                
            logger.info(
                f"  🔍 发现轮动机会: {symbol} (费率 {format_rate(current_rate)}) -> "
                f"{best_new_opportunity.symbol} (费率 {format_rate(new_rate)})"
            )
            logger.info(f"     预估当前平仓盈亏: {format_usdt(pnl)}")
            
            if pnl >= min_profit_threshold:
                logger.info(f"  ✅ 满足换仓条件! 执行轮动...")
                
                # 平掉旧仓位
                close_pnl = await self.executor.close_arbitrage(symbol)
                
                if close_pnl is not None:
                    if telegram.enabled:
                        await telegram.send_message(
                            f"🔄 <b>执行资金轮动</b>\n\n"
                            f"卖出: {symbol} (盈亏 {format_usdt(close_pnl)})\n"
                            f"买入: {best_new_opportunity.symbol} (费率 {format_rate(new_rate)})\n"
                            f"原因: 费率提升 {format_rate(new_rate - current_rate)}"
                        )
                    
                    # 立即开新仓
                    await self.open_position(best_new_opportunity)
                    
                    # 轮动一次只换一个，避免并发问题
                    return
            else:
                logger.info(f"     ❌ 未满足最低盈利要求 ({format_usdt(min_profit_threshold)})，放弃轮动")

    async def monitor_risks(self):
        """
        监控持仓风险
        1. 费率过低离场
        2. 风险指标触发离场 (费率反转/保证金不足)
        """
        if not self.executor.positions:
            return

        logger.info("🔍 监控持仓风险...")
        
        # 需要平仓的列表
        to_close = []
        
        for symbol, position in self.executor.positions.items():
            # 获取最新费率
            rate_info = self.scanner.get_cached_rate(symbol)
            
            # 如果缓存没有，尝试重新获取（可选）
            if not rate_info:
                rate_info = await self.exchange.get_funding_rate(symbol)
            
            current_rate = rate_info.rate
            
            # 1. 检查费率是否低于离场阈值 (低收益离场)
            # 注意: 这里只处理正费率套利 (做空赚费率)，如果是负费率套利逻辑相反
            if abs(current_rate) < EXIT_RATE_THRESHOLD:
                logger.warning(f"📉 {symbol} 费率 {format_rate(current_rate)} 低于离场阈值 {format_rate(EXIT_RATE_THRESHOLD)}")
                to_close.append((symbol, "低费率离场"))
                continue
            
            # 2. 调用风险管理器检查 (安全离场)
            # 构造临时 FundingRate 对象用于检查
            check_result = self.risk_manager.check(
                position=position,
                current_rate=rate_info
            )
            
            if check_result.action in [RiskAction.CLOSE, RiskAction.REDUCE]:
                logger.warning(f"🛡️ {symbol} 触发风控: {check_result.reason}")
                to_close.append((symbol, f"风控触发: {check_result.reason}"))
                continue
        
        # 执行平仓
        for symbol, reason in to_close:
            logger.info(f"⛔ 正在执行平仓: {symbol} ({reason})")
            
            pnl = await self.executor.close_arbitrage(symbol)
            
            if pnl is not None:
                if telegram.enabled:
                    await telegram.send_message(
                        f"👋 <b>自动平仓通知</b>\n\n"
                        f"交易对: {symbol}\n"
                        f"原因: {reason}\n"
                        f"最终盈亏: <code>${pnl:.2f}</code>"
                    )

    
    async def can_open_position(self) -> bool:
        """
        检查账户资金是否支持开新仓
        """
        try:
            # 获取余额
            spot_free = await self.exchange.get_spot_balance("USDT")
            perp_free = await self.exchange.get_perp_balance("USDT")
            
            # 1. 检查现货余额 (需要全额)
            if spot_free < POSITION_SIZE:
                msg = f"现货余额不足: ${spot_free:.2f} < ${POSITION_SIZE}"
                logger.warning(f"⚠️ 无法开仓: {msg}")
                # if telegram.enabled:
                #    await telegram.send_message(f"⚠️ <b>无法开仓</b>\nReason: {msg}")
                return False
            
            # 2. 检查合约余额 (假设 2x 杠杆，需要 SIZE/2，预留一些 buffer 0.6)
            required_perp = POSITION_SIZE * Decimal("0.6")
            if perp_free < required_perp:
                msg = f"合约余额不足: ${perp_free:.2f} < ${required_perp:.2f}"
                logger.warning(f"⚠️ 无法开仓: {msg}")
                # if telegram.enabled:
                #    await telegram.send_message(f"⚠️ <b>无法开仓</b>\nReason: {msg}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"检查资金失败: {e}")
            return False

    async def open_position(self, pool):
        """执行开仓"""
        # 开仓前最后的资金检查
        if not await self.can_open_position():
            return

        try:
            logger.info(f"🚀 开始开仓: {pool.symbol}")
            
            # 执行开仓
            position = await self.executor.open_arbitrage(pool, POSITION_SIZE)
            
            if position:
                logger.info(f"✅ 开仓成功!")
                logger.info(f"   现货: {position.spot_qty:.6f} @ ${position.spot_avg_price:.4f}")
                logger.info(f"   合约: {position.perp_qty:.6f} @ ${position.perp_avg_price:.4f}")
                logger.info(f"   Delta: {position.delta:.6f}")
                
                # 发送 Telegram 通知
                if telegram.enabled:
                    await telegram.notify_trade(
                        action="开仓",
                        symbol=pool.symbol,
                        spot_qty=position.spot_qty,
                        spot_price=position.spot_avg_price,
                        perp_qty=position.perp_qty,
                        perp_price=position.perp_avg_price,
                    )
                    
                    # 额外发送机会详情
                    daily_income = POSITION_SIZE * abs(pool.funding_rate) * 3
                    await telegram.send_message(
                        f"📊 <b>开仓详情</b>\n\n"
                        f"费率: <code>{pool.funding_rate*100:+.4f}%</code>\n"
                        f"预计日收益: <code>${daily_income:.2f}</code>\n"
                        f"深度: <code>${pool.depth_05pct:.0f}</code>\n"
                        f"价差: <code>{pool.spread:.4%}</code>"
                    )
            else:
                logger.error(f"❌ 开仓失败: {pool.symbol}")
                if telegram.enabled:
                    await telegram.send_message(
                        f"❌ 开仓失败\n\n"
                        f"交易对: {pool.symbol}\n"
                        f"费率: {pool.funding_rate*100:+.4f}%"
                    )
        
        except Exception as e:
            logger.error(f"❌ 开仓异常: {e}")
            if telegram.enabled:
                await telegram.send_message(
                    f"⚠️ 开仓异常\n\n"
                    f"交易对: {pool.symbol}\n"
                    f"错误: {str(e)[:200]}"
                )


async def main():
    setup_logger()
    
    # 确认启动
    print("=" * 70)
    print("⚠️  即将启动自动交易机器人")
    print("=" * 70)
    print(f"费率阈值: {MIN_RATE_THRESHOLD*100:.2f}% (超过此值自动开仓)")
    print(f"单笔仓位: ${POSITION_SIZE}")
    print(f"最大持仓: {MAX_POSITIONS} 个")
    print(f"扫描间隔: {SCAN_INTERVAL} 秒")
    print()
    print("机器人将使用真实资金自动交易!")
    print("=" * 70)
    print()
    
    confirm = input("确认启动? (输入 YES 继续): ")
    if confirm != "YES":
        print("❌ 已取消")
        return
    
    trader = AutoTrader()
    await trader.start()


if __name__ == "__main__":
    asyncio.run(main())
