"""
核心模块 - 持仓持久化存储
持仓数据保存到 JSON 文件，支持程序重启恢复
"""
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from src.strategy.executor import ArbitragePosition
from src.utils import logger

# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
POSITIONS_FILE = DATA_DIR / "positions.json"


class DecimalEncoder(json.JSONEncoder):
    """支持 Decimal 的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def decimal_decoder(dct: dict) -> dict:
    """JSON 解码时转换 Decimal 字段"""
    decimal_fields = [
        "spot_qty", "spot_avg_price", "spot_value",
        "perp_qty", "perp_avg_price", "perp_value",
        "funding_earned"
    ]
    for field in decimal_fields:
        if field in dct and dct[field] is not None:
            dct[field] = Decimal(dct[field])
    
    if "opened_at" in dct and dct["opened_at"]:
        dct["opened_at"] = datetime.fromisoformat(dct["opened_at"])
    
    return dct


class PositionStore:
    """
    持仓持久化存储
    使用 JSON 文件保存持仓状态
    """
    
    def __init__(self, file_path: Path = POSITIONS_FILE):
        self.file_path = file_path
        self._ensure_data_dir()
    
    def _ensure_data_dir(self) -> None:
        """确保数据目录存在"""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def save(self, position: ArbitragePosition) -> None:
        """
        保存单个持仓
        
        Args:
            position: 持仓对象
        """
        positions = self._load_raw()
        
        # 转换为可序列化格式
        pos_dict = {
            "symbol": position.symbol,
            "base_currency": position.base_currency,
            "spot_qty": str(position.spot_qty),
            "spot_avg_price": str(position.spot_avg_price),
            "spot_value": str(position.spot_value),
            "perp_qty": str(position.perp_qty),
            "perp_avg_price": str(position.perp_avg_price),
            "perp_value": str(position.perp_value),
            "funding_earned": str(position.funding_earned),
            "leverage": position.leverage,
            "opened_at": position.opened_at.isoformat() if position.opened_at else None,
            "funding_periods": position.funding_periods,
        }
        
        positions[position.symbol] = pos_dict
        self._save_raw(positions)
        
        logger.debug(f"持仓已保存: {position.symbol}")
    
    def save_all(self, positions: dict[str, ArbitragePosition]) -> None:
        """保存所有持仓"""
        for position in positions.values():
            self.save(position)
    
    def load_all(self) -> dict[str, ArbitragePosition]:
        """
        加载所有持仓
        
        Returns:
            持仓字典 {symbol: ArbitragePosition}
        """
        raw = self._load_raw()
        positions = {}
        
        for symbol, data in raw.items():
            try:
                positions[symbol] = ArbitragePosition(
                    symbol=data["symbol"],
                    base_currency=data["base_currency"],
                    spot_qty=Decimal(data["spot_qty"]),
                    spot_avg_price=Decimal(data["spot_avg_price"]),
                    spot_value=Decimal(data["spot_value"]),
                    perp_qty=Decimal(data["perp_qty"]),
                    perp_avg_price=Decimal(data["perp_avg_price"]),
                    perp_value=Decimal(data["perp_value"]),
                    funding_earned=Decimal(data["funding_earned"]),
                    leverage=data["leverage"],
                    opened_at=datetime.fromisoformat(data["opened_at"]) if data.get("opened_at") else None,
                    funding_periods=data.get("funding_periods", 0),
                )
            except Exception as e:
                logger.error(f"加载持仓失败 {symbol}: {e}")
                continue
        
        logger.info(f"从文件加载 {len(positions)} 个持仓")
        return positions
    
    def remove(self, symbol: str) -> bool:
        """
        删除持仓
        
        Args:
            symbol: 交易对
            
        Returns:
            是否删除成功
        """
        positions = self._load_raw()
        
        if symbol in positions:
            del positions[symbol]
            self._save_raw(positions)
            logger.debug(f"持仓已删除: {symbol}")
            return True
        
        return False
    
    def update_funding_income(self, symbol: str, income: Decimal) -> bool:
        """
        更新费率收入
        
        Args:
            symbol: 交易对
            income: 收入金额
            
        Returns:
            是否更新成功
        """
        positions = self._load_raw()
        
        if symbol not in positions:
            return False
        
        current = Decimal(positions[symbol]["funding_earned"])
        positions[symbol]["funding_earned"] = str(current + income)
        positions[symbol]["funding_periods"] = positions[symbol].get("funding_periods", 0) + 1
        
        self._save_raw(positions)
        logger.info(f"费率收入更新 {symbol}: +{income:.4f} USDT")
        
        return True
    
    def get_total_funding_income(self) -> Decimal:
        """获取总费率收入"""
        positions = self._load_raw()
        return sum(Decimal(p.get("funding_earned", "0")) for p in positions.values())
    
    def _load_raw(self) -> dict:
        """加载原始 JSON 数据"""
        if not self.file_path.exists():
            return {}
        
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取持仓文件失败: {e}")
            return {}
    
    def _save_raw(self, data: dict) -> None:
        """保存原始 JSON 数据"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存持仓文件失败: {e}")


# 全局实例
position_store = PositionStore()
