"""
回测数据加载器
负责获取和加载历史资金费率数据
"""
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict
import ccxt.async_support as ccxt

from src.utils import logger, config

DATA_DIR = Path("data/historical")
DATA_DIR.mkdir(parents=True, exist_ok=True)


class DataLoader:
    """数据加载器"""
    
    def __init__(self, exchange_id: str = "binance"):
        self.exchange_id = exchange_id
        
    async def fetch_funding_history(
        self,
        symbol: str, # e.g. "BTC/USDT"
        start_date: datetime,
        end_date: datetime = None,
        save_to_file: bool = True
    ) -> pd.DataFrame:
        """
        获取历史资金费率数据
        
        Args:
            symbol: 交易对
            start_date: 开始时间
            end_date: 结束时间 (默认为当前时间)
            save_to_file: 是否保存到文件
            
        Returns:
            DataFrame: [timestamp, funding_rate, symbol]
        """
        if end_date is None:
            end_date = datetime.now()
            
        logger.info(f"📥 开始获取 {symbol} 资金费率历史数据 ({start_date.date()} - {end_date.date()})")
        
        # 转换 symbol 格式 (CCXT 格式)
        # 注意: ccxt fetchFundingRateHistory 使用的是 unified symbol
        
        exchange_class = getattr(ccxt, self.exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'} # 确保是合约
        })
        
        all_rates = []
        try:
            since = int(start_date.timestamp() * 1000)
            end_ts = int(end_date.timestamp() * 1000)
            
            while since < end_ts:
                # 获取数据
                rates = await exchange.fetch_funding_rate_history(symbol, since, limit=1000)
                
                if not rates:
                    break
                    
                all_rates.extend(rates)
                
                # 更新时间戳
                last_ts = rates[-1]['timestamp']
                if last_ts == since: # 防止死循环
                    break
                since = last_ts + 1
                
                logger.debug(f"  已获取 {len(all_rates)} 条数据...")
                await asyncio.sleep(0.5) # 限流
                
        except Exception as e:
            logger.error(f"❌ 获取数据失败: {e}")
        finally:
            await exchange.close()
            
        if not all_rates:
            logger.warning(f"⚠️ 未获取到 {symbol} 的数据")
            return pd.DataFrame()
            
        # 转换为 DataFrame
        df = pd.DataFrame(all_rates)
        df = df[['timestamp', 'fundingRate', 'symbol']]
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df.rename(columns={'fundingRate': 'rate'})
        
        # 过滤时间范围
        df = df[(df['timestamp'] >= int(start_date.timestamp() * 1000)) & 
                (df['timestamp'] <= end_ts)]
        
        logger.info(f"✅ 成功获取 {len(df)} 条记录")
        
        if save_to_file:
            self._save_to_csv(df, symbol)
            
        return df

    def _save_to_csv(self, df: pd.DataFrame, symbol: str):
        """保存数据到 CSV"""
        safe_symbol = symbol.replace("/", "_")
        filename = DATA_DIR / f"{self.exchange_id}_{safe_symbol}_funding.csv"
        df.to_csv(filename, index=False)
        logger.info(f"💾 数据已保存到: {filename}")

    def load_from_file(self, symbol: str) -> Optional[pd.DataFrame]:
        """从本地文件加载数据"""
        safe_symbol = symbol.replace("/", "_")
        filename = DATA_DIR / f"{self.exchange_id}_{safe_symbol}_funding.csv"
        
        if not filename.exists():
            logger.warning(f"⚠️ 文件不存在: {filename}")
            return None
            
        df = pd.read_csv(filename)
        df['datetime'] = pd.to_datetime(df['datetime'])
        logger.info(f"📖 从文件加载了 {len(df)} 条记录")
        return df


# 测试代码
if __name__ == "__main__":
    async def test():
        loader = DataLoader()
        start = datetime.now() - timedelta(days=30)
        await loader.fetch_funding_history("BTC/USDT", start)
        
    asyncio.run(test())
