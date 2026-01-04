"""
资金费率套利系统 - 配置管理模块
"""
import os
from pathlib import Path
from typing import Any
from decimal import Decimal

import yaml
from dotenv import load_dotenv


# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.parent
CONFIG_DIR = ROOT_DIR / "config"

# 加载环境变量
load_dotenv(ROOT_DIR / ".env")


class Config:
    """配置管理器 - 单例模式"""
    
    _instance = None
    _loaded = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._loaded:
            self._settings: dict = {}
            self._exchanges: dict = {}
            self._strategy: dict = {}
            self._load_all()
            Config._loaded = True
    
    def _load_yaml(self, filename: str) -> dict:
        """加载 YAML 配置文件"""
        filepath = CONFIG_DIR / filename
        if not filepath.exists():
            raise FileNotFoundError(f"配置文件不存在: {filepath}")
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    
    def _load_all(self) -> None:
        """加载所有配置"""
        self._settings = self._load_yaml("settings.yaml")
        self._exchanges = self._load_yaml("exchanges.yaml")
        self._strategy = self._load_yaml("strategy.yaml")
        
        # 用环境变量覆盖敏感信息
        self._override_from_env()
    
    def _override_from_env(self) -> None:
        """从环境变量覆盖配置"""
        exchanges = self._exchanges.get("exchanges", {})
        
        # Binance
        if "binance" in exchanges:
            if os.getenv("BINANCE_API_KEY"):
                exchanges["binance"]["api_key"] = os.getenv("BINANCE_API_KEY")
            if os.getenv("BINANCE_SECRET"):
                exchanges["binance"]["secret"] = os.getenv("BINANCE_SECRET")
        
        # Bybit
        if "bybit" in exchanges:
            if os.getenv("BYBIT_API_KEY"):
                exchanges["bybit"]["api_key"] = os.getenv("BYBIT_API_KEY")
            if os.getenv("BYBIT_SECRET"):
                exchanges["bybit"]["secret"] = os.getenv("BYBIT_SECRET")
        
        # OKX
        if "okx" in exchanges:
            if os.getenv("OKX_API_KEY"):
                exchanges["okx"]["api_key"] = os.getenv("OKX_API_KEY")
            if os.getenv("OKX_SECRET"):
                exchanges["okx"]["secret"] = os.getenv("OKX_SECRET")
            if os.getenv("OKX_PASSPHRASE"):
                exchanges["okx"]["passphrase"] = os.getenv("OKX_PASSPHRASE")
        
        # Telegram
        notification = self._settings.setdefault("notification", {})
        telegram = notification.setdefault("telegram", {})
        if os.getenv("TELEGRAM_BOT_TOKEN"):
            telegram["bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN")
        if os.getenv("TELEGRAM_CHAT_ID"):
            telegram["chat_id"] = os.getenv("TELEGRAM_CHAT_ID")
    
    # ==================== Settings ====================
    
    @property
    def initial_capital(self) -> Decimal:
        """初始资金"""
        return Decimal(str(self._settings.get("capital", {}).get("initial", 1000)))
    
    @property
    def max_position_ratio(self) -> Decimal:
        """最大仓位比例"""
        return Decimal(str(self._settings.get("capital", {}).get("max_position_ratio", 0.8)))
    
    @property
    def max_single_ratio(self) -> Decimal:
        """单币种最大占比"""
        return Decimal(str(self._settings.get("capital", {}).get("max_single_ratio", 0.3)))
    
    @property
    def trading_timezone(self) -> str:
        """交易时区"""
        return self._settings.get("trading_hours", {}).get("timezone", "Europe/Paris")
    
    @property
    def trading_start(self) -> str:
        """交易开始时间"""
        return self._settings.get("trading_hours", {}).get("start", "08:00")
    
    @property
    def trading_end(self) -> str:
        """交易结束时间"""
        return self._settings.get("trading_hours", {}).get("end", "22:00")
    
    @property
    def scan_interval(self) -> int:
        """扫描间隔(秒)"""
        return self._settings.get("execution", {}).get("scan_interval", 60)
    
    @property
    def log_level(self) -> str:
        """日志级别"""
        return self._settings.get("logging", {}).get("level", "INFO")
    
    @property
    def log_file(self) -> str:
        """日志文件路径"""
        return self._settings.get("logging", {}).get("file", "logs/arbitrage.log")
    
    # ==================== Exchange ====================
    
    @property
    def default_exchange(self) -> str:
        """默认交易所"""
        return self._exchanges.get("default_exchange", "binance")
    
    def get_exchange_config(self, name: str) -> dict:
        """获取交易所配置"""
        return self._exchanges.get("exchanges", {}).get(name, {})
    
    def get_enabled_exchanges(self) -> list[str]:
        """获取已启用的交易所列表"""
        exchanges = self._exchanges.get("exchanges", {})
        return [name for name, cfg in exchanges.items() if cfg.get("enabled", False)]
    
    # ==================== Strategy ====================
    
    @property
    def filter_mode(self) -> str:
        """筛选模式: strict / relaxed"""
        return self._strategy.get("filter_mode", "strict")
    
    @property
    def filter_config(self) -> dict:
        """筛选配置 (根据模式自动选择)"""
        mode = self.filter_mode
        if mode == "relaxed":
            # 宽松模式：合并默认配置和宽松配置
            base = self._strategy.get("filter", {}).copy()
            relaxed = self._strategy.get("filter_relaxed", {})
            # 用宽松配置覆盖
            for key, value in relaxed.items():
                if isinstance(value, dict) and key in base:
                    base[key].update(value)
                else:
                    base[key] = value
            return base
        return self._strategy.get("filter", {})
    
    @property
    def rotation_config(self) -> dict:
        """轮动策略配置"""
        return self._strategy.get("rotation", {})

    @property
    def position_config(self) -> dict:
        """仓位配置"""
        return self._strategy.get("position", {})
    
    @property
    def risk_config(self) -> dict:
        """风险配置"""
        return self._strategy.get("risk", {})
    
    @property
    def min_funding_rate(self) -> Decimal:
        """最小资金费率阈值"""
        rate = self.filter_config.get("funding_rate", {}).get("min_abs", 0.0003)
        return Decimal(str(rate))
    
    @property
    def min_volume(self) -> Decimal:
        """最小交易量"""
        vol = self.filter_config.get("volume_24h", {}).get("min", 500000)
        return Decimal(str(vol))
    
    @property
    def max_volume(self) -> Decimal:
        """最大交易量"""
        vol = self.filter_config.get("volume_24h", {}).get("max", 5000000)
        return Decimal(str(vol))
    
    @property
    def blacklist(self) -> list[str]:
        """黑名单币种"""
        return self.filter_config.get("blacklist", [])
    
    @property
    def allow_negative_rates(self) -> bool:
        """是否允许负费率套利"""
        return self.filter_config.get("allow_negative_rates", False)
    
    @property
    def default_leverage(self) -> int:
        """默认杠杆"""
        return self.position_config.get("leverage", {}).get("default", 2)
    
    @property
    def delta_tolerance(self) -> Decimal:
        """Delta 容忍度"""
        tol = self.position_config.get("delta_tolerance", 0.02)
        return Decimal(str(tol))
    
    # ==================== Notification ====================
    
    @property
    def telegram_token(self) -> str:
        """Telegram Bot Token"""
        return self._settings.get("notification", {}).get("telegram", {}).get("bot_token", "")
    
    @property
    def telegram_chat_id(self) -> str:
        """Telegram Chat ID"""
        return self._settings.get("notification", {}).get("telegram", {}).get("chat_id", "")
    
    # ==================== Utility ====================
    
    def reload(self) -> None:
        """重新加载配置"""
        Config._loaded = False
        self.__init__()
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        通过路径获取配置值
        示例: config.get("capital.initial", 1000)
        """
        keys = path.split(".")
        value = self._settings
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value


# 全局配置实例
config = Config()
