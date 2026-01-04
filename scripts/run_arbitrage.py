"""
运行脚本 - 套利引擎
启动完整套利流程
"""
import asyncio
import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.core import ArbitrageEngine
from src.utils import logger


async def main():
    """启动套利引擎"""
    logger.info("=" * 60)
    logger.info("🚀 资金费率套利系统")
    logger.info("=" * 60)
    
    engine = ArbitrageEngine()
    
    try:
        await engine.run()
    except KeyboardInterrupt:
        logger.info("👋 用户中断")
    finally:
        await engine.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
