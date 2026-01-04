"""
资金费率套利系统 - 日志模块
"""
import sys
from pathlib import Path

from loguru import logger

from src.utils.config import config, ROOT_DIR


def setup_logger() -> None:
    """配置日志系统"""
    # 移除默认 handler
    logger.remove()
    
    # 日志格式
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # 控制台输出
    logger.add(
        sys.stdout,
        format=log_format,
        level=config.log_level,
        colorize=True,
    )
    
    # 文件输出
    log_file = ROOT_DIR / config.log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        str(log_file),
        format=log_format,
        level=config.log_level,
        rotation=config._settings.get("logging", {}).get("rotation", "10 MB"),
        retention=config._settings.get("logging", {}).get("retention", "7 days"),
        compression="zip",
        encoding="utf-8",
    )
    
    logger.info("日志系统初始化完成")


# 导出 logger 实例
__all__ = ["logger", "setup_logger"]
