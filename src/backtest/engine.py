"""
回测引擎
模拟资金费率套利策略在历史数据上的表现
"""
import pandas as pd
from decimal import Decimal
from typing import Dict, List, Any
from dataclasses import dataclass

from src.utils import logger, format_usdt, format_rate

@dataclass
class BacktestResult:
    """回测结果"""
    total_days: float
    total_trades: int
    total_income: float
    net_profit: float
    roi: float           # 投资回报率
    annual_roi: float    # 年化回报率
    max_drawdown: float  # 最大回撤
    sharpe_ratio: float  # 夏普比率
    daily_logs: List[Dict] # 每日记录

class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 1000.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions = {} # symbol -> position_info
        
        # 费率设置
        self.spot_fee = 0.001       # 0.1%
        self.futures_fee = 0.0004   # 0.04%
        
    def run(self, data: pd.DataFrame, config: Dict[str, Any]) -> BacktestResult:
        """
        运行回测
        
        Args:
            data: 历史数据 DataFrame [datetime, rate, symbol]
            config: 策略配置 {threshold: 0.0005, leverage: 1}
            
        Returns:
            BacktestResult
        """
        logger.info("🎬 开始回测...")
        
        # 配置参数
        threshold = config.get('threshold', 0.0005) # 开仓阈值 0.05%
        leverage = config.get('leverage', 1)
        
        # 按时间排序
        data = data.sort_values('datetime')
        
        # 初始化记录
        daily_pnl = []
        equity_curve = [self.initial_capital]
        trades = []
        
        total_income = 0.0
        
        # 遍历每个时间点 (资金费率结算点)
        for _, row in data.iterrows():
            rate = float(row['rate'])
            timestamp = row['datetime']
            symbol = row['symbol']
            
            current_equity = self.capital
            
            # --- 1. 结算现有持仓 ---
            if symbol in self.positions:
                pos = self.positions[symbol]
                
                # 计算资金费收入
                # 正费率: 空头收钱 (我们做空) -> 收益 = 仓位 * 费率
                # 负费率: 多头收钱 (我们做多) -> 收益 = 仓位 * 绝对值费率
                # 策略: 
                #   rate > 0: 做空 (Spot Buy + Perp Sell) -> 赚 rate
                #   rate < 0: 做多 (Spot Sell + Perp Buy) -> 赚 abs(rate)
                # 简而言之，只要方向做对，收入就是 position_value * abs(rate)
                
                # 检查方向是否正确
                # 如果持仓是正向套利(做空期货)，且 rate > 0 => 赚钱
                # 如果持仓是反向套利(做多期货)，且 rate < 0 => 赚钱
                
                income = 0
                if pos['side'] == 'short_perp' and rate > 0:
                    income = pos['size'] * rate
                elif pos['side'] == 'long_perp' and rate < 0:
                    income = pos['size'] * abs(rate)
                else:
                    # 费率反转，支出资金费
                    income = -pos['size'] * abs(rate)
                
                self.capital += income
                total_income += income
                
                # 记录日志
                if abs(income) > 0:
                    trades.append({
                        'time': timestamp,
                        'type': 'funding',
                        'symbol': symbol,
                        'amount': income,
                        'rate': rate
                    })
                
                # --- 2. 检查是否平仓 ---
                # 如果费率低于平仓阈值(例如 0)，或者是负收益
                if (pos['side'] == 'short_perp' and rate < 0) or \
                   (pos['side'] == 'long_perp' and rate > 0):
                    
                    # 平仓
                    cost = pos['size'] * (self.spot_fee + self.futures_fee)
                    self.capital -= cost
                    
                    del self.positions[symbol]
                    trades.append({
                        'time': timestamp,
                        'type': 'close',
                        'symbol': symbol,
                        'cost': cost
                    })
            
            # --- 3. 检查是否开仓 ---
            elif abs(rate) >= threshold:
                # 计算可用资金
                # 简单起见，假设全仓单利模式，或者固定金额
                position_size = self.capital * 0.9 # 90% 仓位
                
                side = 'short_perp' if rate > 0 else 'long_perp'
                
                # 开仓成本
                cost = position_size * (self.spot_fee + self.futures_fee)
                self.capital -= cost
                
                self.positions[symbol] = {
                    'size': position_size,
                    'side': side,
                    'entry_time': timestamp
                }
                
                trades.append({
                    'time': timestamp,
                    'type': 'open',
                    'symbol': symbol,
                    'side': side,
                    'rate': rate,
                    'cost': cost
                })
            
            equity_curve.append(self.capital)
        
        # 强制平仓所有头寸(为了计算最终净值)
        for symbol, pos in list(self.positions.items()):
            cost = pos['size'] * (self.spot_fee + self.futures_fee)
            self.capital -= cost
            del self.positions[symbol]
        
        # 计算指标
        total_days = (data['datetime'].max() - data['datetime'].min()).days
        if total_days < 1: total_days = 1
        
        net_profit = self.capital - self.initial_capital
        roi = net_profit / self.initial_capital
        annual_roi = roi * (365 / total_days)
        
        # 最大回撤
        max_eq = equity_curve[0]
        max_drawdown = 0
        for eq in equity_curve:
            if eq > max_eq:
                max_eq = eq
            dd = (max_eq - eq) / max_eq
            if dd > max_drawdown:
                max_drawdown = dd
                
        return BacktestResult(
            total_days=total_days,
            total_trades=len([t for t in trades if t['type'] == 'open']),
            total_income=total_income,
            net_profit=net_profit,
            roi=roi,
            annual_roi=annual_roi,
            max_drawdown=max_drawdown,
            sharpe_ratio=0.0, # 简化处理
            daily_logs=trades
        )

