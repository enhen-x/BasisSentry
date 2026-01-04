"""
年化收益率计算
基于 0.5% 费率阈值
"""

# ==================== 参数设置 ====================
FUNDING_RATE = 0.005  # 0.5% 每 8 小时
POSITION_SIZE = 60    # 总资金 (USDT)
HOLDING_DAYS = 7      # 平均持仓天数
TRADE_FREQUENCY = 12  # 一年交易次数

# ==================== 收益计算 ====================

# 1. 单笔交易收益
periods_per_day = 3  # 每天 3 次结算
total_periods = HOLDING_DAYS * periods_per_day
funding_income = POSITION_SIZE * FUNDING_RATE * total_periods

# 2. 交易成本
spot_fee = POSITION_SIZE * 0.5 * 0.001  # 现货买卖 0.1%
futures_fee = POSITION_SIZE * 0.5 * 0.0004 * 2  # 合约开平 0.04%
total_fee = spot_fee + futures_fee

# 3. 净收益
net_profit = funding_income - total_fee
roi_per_trade = net_profit / POSITION_SIZE

# 4. 年化收益
annual_profit = net_profit * TRADE_FREQUENCY
annual_roi = (annual_profit / POSITION_SIZE) * 100

print("=" * 60)
print("📊 资金费率套利年化收益测算 (0.5% 阈值)")
print("=" * 60)
print()
print(f"假设条件:")
print(f"  费率阈值: {FUNDING_RATE*100:.2f}% (每 8 小时)")
print(f"  总资金: ${POSITION_SIZE}")
print(f"  平均持仓: {HOLDING_DAYS} 天")
print(f"  年交易次数: {TRADE_FREQUENCY} 次")
print()
print("-" * 60)
print("单笔交易收益:")
print(f"  资金费收入: ${funding_income:.2f} ({total_periods} 个周期)")
print(f"  交易手续费: ${total_fee:.2f}")
print(f"  净收益: ${net_profit:.2f}")
print(f"  单次回报率: {roi_per_trade*100:.2f}%")
print()
print("-" * 60)
print(f"年化收益率: {annual_roi:.1f}% APY")
print(f"年预期利润: ${annual_profit:.2f}")
print("=" * 60)
print()
print("⚠️  注意:")
print("  1. 实际收益受市场波动影响")
print("  2. 费率可能随时反转")
print("  3. 此为理想状态测算")
print("  4. 保守预估: 20-40% APY")
print("=" * 60)
