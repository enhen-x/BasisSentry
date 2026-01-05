"""
核心模块 - 资金费率收入追踪
记录每次费率结算的收入
"""
import json
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.utils import logger

# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
FUNDING_LOG_FILE = DATA_DIR / "funding_log.json"


@dataclass
class FundingRecord:
    """费率收入记录"""
    symbol: str
    rate: Decimal
    position_value: Decimal
    income: Decimal
    timestamp: datetime
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "rate": str(self.rate),
            "position_value": str(self.position_value),
            "income": str(self.income),
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FundingRecord":
        return cls(
            symbol=data["symbol"],
            rate=Decimal(data["rate"]),
            position_value=Decimal(data["position_value"]),
            income=Decimal(data["income"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


class FundingTracker:
    """
    资金费率收入追踪器
    记录每次费率结算的收入
    """
    
    def __init__(self, file_path: Path = FUNDING_LOG_FILE):
        self.file_path = file_path
        self._ensure_data_dir()
    
    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def record_funding(
        self,
        symbol: str,
        rate: Decimal,
        position_value: Decimal,
    ) -> FundingRecord:
        """
        记录费率收入
        
        Args:
            symbol: 交易对
            rate: 费率
            position_value: 持仓价值
            
        Returns:
            费率收入记录
        """
        # 计算收入 (正费率做空方收取)
        income = position_value * abs(rate)
        
        record = FundingRecord(
            symbol=symbol,
            rate=rate,
            position_value=position_value,
            income=income,
            timestamp=datetime.now(),
        )
        
        # 追加到日志
        records = self._load_records()
        records.append(record.to_dict())
        self._save_records(records)
        
        logger.info(
            f"记录费率收入 {symbol}: "
            f"费率={rate:.4%}, 仓位={position_value:.2f}, "
            f"收入={income:.4f} USDT"
        )
        
        return record
    
    def get_total_income(self, symbol: Optional[str] = None) -> Decimal:
        """
        获取总费率收入
        
        Args:
            symbol: 可选，指定交易对
            
        Returns:
            总收入
        """
        records = self._load_records()
        
        total = Decimal(0)
        for r in records:
            if symbol is None or r["symbol"] == symbol:
                total += Decimal(r["income"])
        
        return total
    
    def get_daily_income(self, day: Optional[date] = None) -> Decimal:
        """
        获取指定日期的费率收入
        
        Args:
            day: 日期，默认今天
            
        Returns:
            当日收入
        """
        if day is None:
            day = date.today()
        
        records = self._load_records()
        
        total = Decimal(0)
        for r in records:
            record_date = datetime.fromisoformat(r["timestamp"]).date()
            if record_date == day:
                total += Decimal(r["income"])
        
        return total
    
    def get_records_by_symbol(self, symbol: str) -> list[FundingRecord]:
        """获取指定交易对的所有记录"""
        records = self._load_records()
        return [
            FundingRecord.from_dict(r)
            for r in records
            if r["symbol"] == symbol
        ]
    
    def get_recent_records(self, limit: int = 20) -> list[FundingRecord]:
        """获取最近的记录"""
        records = self._load_records()
        return [
            FundingRecord.from_dict(r)
            for r in records[-limit:]
        ]
    
    def get_summary(self) -> dict:
        """
        获取收入统计摘要
        
        Returns:
            {
                "total_income": 总收入,
                "today_income": 今日收入,
                "total_records": 记录数,
                "by_symbol": {symbol: income},
            }
        """
        records = self._load_records()
        today = date.today()
        
        total = Decimal(0)
        today_income = Decimal(0)
        by_symbol: dict[str, Decimal] = {}
        
        for r in records:
            income = Decimal(r["income"])
            total += income
            
            symbol = r["symbol"]
            by_symbol[symbol] = by_symbol.get(symbol, Decimal(0)) + income
            
            record_date = datetime.fromisoformat(r["timestamp"]).date()
            if record_date == today:
                today_income += income
        
        return {
            "total_income": total,
            "today_income": today_income,
            "total_records": len(records),
            "by_symbol": by_symbol,
        }

    def sync_remote_payments(self, payments: list[dict]) -> int:
        """合并交易所资金流水到本地记录，避免重复"""
        if not payments:
            return 0

        records = self._load_records()
        existing_keys = {
            (r["symbol"], r.get("timestamp"), r.get("income")) for r in records
        }

        added = 0
        for p in payments:
            symbol = p.get("symbol")
            ts = p.get("timestamp")
            income = Decimal(str(p.get("income", 0)))
            rate = Decimal(str(p.get("rate", 0)))
            position_value = Decimal(str(p.get("position_value", 0)))

            # 支持 datetime 或 ISO 字符串
            if isinstance(ts, datetime):
                ts_iso = ts.isoformat()
            elif isinstance(ts, str):
                ts_iso = ts
            else:
                # 无效时间戳，跳过
                continue

            key = (symbol, ts_iso, str(income))
            if key in existing_keys:
                continue

            existing_keys.add(key)
            added += 1
            records.append(
                FundingRecord(
                    symbol=symbol,
                    rate=rate,
                    position_value=position_value,
                    income=income,
                    timestamp=datetime.fromisoformat(ts_iso)
                    if isinstance(ts_iso, str)
                    else ts,
                ).to_dict()
            )

        if added:
            self._save_records(records)
            logger.info(f"已从交易所资金流水同步 {added} 条记录")

        return added
    
    def _load_records(self) -> list[dict]:
        """加载记录"""
        if not self.file_path.exists():
            return []
        
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取费率日志失败: {e}")
            return []
    
    def _save_records(self, records: list[dict]) -> None:
        """保存记录"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存费率日志失败: {e}")


# 全局实例
funding_tracker = FundingTracker()
