"""
核心模块 - 风险控制
监控持仓风险，执行止损逻辑
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto
from typing import Optional

from src.strategy.executor import ArbitragePosition
from src.exchange import ExchangeBase, FundingRate
from src.utils import logger, config, format_rate


class RiskAction(Enum):
    """风险动作"""
    HOLD = auto()           # 保持
    REDUCE = auto()         # 减仓
    CLOSE = auto()          # 平仓
    REBALANCE = auto()      # 调仓


@dataclass
class RiskCheckResult:
    """风险检查结果"""
    action: RiskAction
    reason: str
    severity: int  # 1-10


class RiskManager:
    """
    风险管理器
    执行多维度风险检查
    """
    
    def __init__(self):
        self.risk_cfg = config.risk_config
        
        # 保证金率阈值
        margin_cfg = self.risk_cfg.get("margin_ratio", {})
        self.margin_warning = Decimal(str(margin_cfg.get("warning", 0.5)))
        self.margin_danger = Decimal(str(margin_cfg.get("danger", 0.35)))
        self.margin_close = Decimal(str(margin_cfg.get("close", 0.25)))
        
        # 亏损阈值
        loss_cfg = self.risk_cfg.get("max_loss", {})
        self.max_loss_per_trade = Decimal(str(loss_cfg.get("per_trade", 0.02)))
        self.max_loss_daily = Decimal(str(loss_cfg.get("daily", 0.05)))
        self.max_loss_total = Decimal(str(loss_cfg.get("total", 0.10)))
        
        # 费率反转
        rate_cfg = self.risk_cfg.get("rate_reversal", {})
        self.rate_reversal_periods = rate_cfg.get("watch_periods", 2)
        self.rate_reversal_threshold = Decimal(str(rate_cfg.get("threshold", 0.0001)))
        
        # Delta 容忍度
        self.delta_tolerance = config.delta_tolerance
        
        # 费率历史 (用于检测反转)
        self._rate_history: dict[str, list[Decimal]] = {}
        
        # 统计
        self.daily_loss = Decimal(0)
        self.total_loss = Decimal(0)
    
    def check(
        self,
        position: ArbitragePosition,
        current_rate: Optional[FundingRate] = None,
        margin_ratio: Optional[Decimal] = None,
    ) -> RiskCheckResult:
        """
        执行风险检查
        
        Returns:
            RiskCheckResult: 风险检查结果
        """
        # 1. 保证金率检查 (最高优先级)
        if margin_ratio is not None:
            result = self._check_margin_ratio(margin_ratio)
            if result.action != RiskAction.HOLD:
                return result
        
        # 2. Delta 偏差检查
        result = self._check_delta(position)
        if result.action != RiskAction.HOLD:
            return result
        
        # 3. 费率反转检查
        if current_rate is not None:
            result = self._check_rate_reversal(position.symbol, current_rate)
            if result.action != RiskAction.HOLD:
                return result
        
        # 4. 单笔亏损检查
        result = self._check_position_loss(position)
        if result.action != RiskAction.HOLD:
            return result
        
        return RiskCheckResult(
            action=RiskAction.HOLD,
            reason="All checks passed",
            severity=0,
        )
    
    def _check_margin_ratio(self, margin_ratio: Decimal) -> RiskCheckResult:
        """检查保证金率"""
        if margin_ratio < self.margin_close:
            return RiskCheckResult(
                action=RiskAction.CLOSE,
                reason=f"保证金率 {margin_ratio:.1%} 低于平仓线 {self.margin_close:.1%}",
                severity=10,
            )
        
        if margin_ratio < self.margin_danger:
            return RiskCheckResult(
                action=RiskAction.REDUCE,
                reason=f"保证金率 {margin_ratio:.1%} 低于危险线 {self.margin_danger:.1%}",
                severity=8,
            )
        
        if margin_ratio < self.margin_warning:
            logger.warning(f"保证金率 {margin_ratio:.1%} 低于警告线 {self.margin_warning:.1%}")
        
        return RiskCheckResult(RiskAction.HOLD, "", 0)
    
    def _check_delta(self, position: ArbitragePosition) -> RiskCheckResult:
        """检查 Delta 偏差"""
        delta = abs(position.delta)
        
        if delta > self.delta_tolerance * 2:
            return RiskCheckResult(
                action=RiskAction.REBALANCE,
                reason=f"Delta 偏差 {delta:.2%} 超过阈值 {self.delta_tolerance:.2%}",
                severity=6,
            )
        
        if delta > self.delta_tolerance:
            logger.warning(f"Delta 偏差 {delta:.2%} 接近阈值")
        
        return RiskCheckResult(RiskAction.HOLD, "", 0)
    
    def _check_rate_reversal(
        self,
        symbol: str,
        current_rate: FundingRate,
    ) -> RiskCheckResult:
        """检查费率反转"""
        history = self._rate_history.setdefault(symbol, [])
        history.append(current_rate.rate)
        
        # 保留最近 N 期
        if len(history) > self.rate_reversal_periods + 1:
            history.pop(0)
        
        if len(history) < self.rate_reversal_periods + 1:
            return RiskCheckResult(RiskAction.HOLD, "", 0)
        
        # 检测反转
        # 原来是正费率，现在连续 N 期为负
        initial_rate = history[0]
        recent_rates = history[1:]
        
        if initial_rate > 0:
            # 正费率套利头寸
            if all(r < -self.rate_reversal_threshold for r in recent_rates):
                return RiskCheckResult(
                    action=RiskAction.CLOSE,
                    reason=f"费率反转: {format_rate(initial_rate)} → {format_rate(recent_rates[-1])}",
                    severity=7,
                )
        else:
            # 负费率套利头寸
            if all(r > self.rate_reversal_threshold for r in recent_rates):
                return RiskCheckResult(
                    action=RiskAction.CLOSE,
                    reason=f"费率反转: {format_rate(initial_rate)} → {format_rate(recent_rates[-1])}",
                    severity=7,
                )
        
        return RiskCheckResult(RiskAction.HOLD, "", 0)
    
    def _check_position_loss(self, position: ArbitragePosition) -> RiskCheckResult:
        """检查持仓亏损"""
        # 简化: 假设无未实现盈亏
        # TODO: 实际计算未实现盈亏
        return RiskCheckResult(RiskAction.HOLD, "", 0)
    
    def record_loss(self, loss: Decimal) -> None:
        """记录亏损"""
        if loss < 0:
            self.daily_loss += abs(loss)
            self.total_loss += abs(loss)
    
    def reset_daily(self) -> None:
        """重置每日统计"""
        self.daily_loss = Decimal(0)
    
    def is_daily_limit_reached(self, initial_capital: Decimal) -> bool:
        """是否达到每日亏损上限"""
        return self.daily_loss >= initial_capital * self.max_loss_daily
    
    def is_total_limit_reached(self, initial_capital: Decimal) -> bool:
        """是否达到总亏损上限"""
        return self.total_loss >= initial_capital * self.max_loss_total
