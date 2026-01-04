"""
收益报表可视化脚本
生成交互式 HTML 报表，展示累计收益、每日收益和币种分布
"""
import sys
import json
import random
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# 添加项目根目录到 Python 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.utils import logger

# 数据文件路径
DATA_DIR = ROOT / "data"
LOG_FILE = DATA_DIR / "funding_log.json"
OUTPUT_DIR = ROOT / "reports"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_data():
    """加载数据，如果不存在则生成模拟数据"""
    if not LOG_FILE.exists():
        logger.warning("未找到真实交易数据，正在生成模拟演示数据...")
        return generate_dummy_data()
    
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        if not data:
            logger.warning("数据文件为空，使用模拟数据...")
            return generate_dummy_data()
            
        df = pd.DataFrame(data)
        # 类型转换
        df['income'] = df['income'].astype(float)
        df['rate'] = df['rate'].astype(float)
        df['position_value'] = df['position_value'].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
        
    except Exception as e:
        logger.error(f"加载数据失败: {e}")
        return generate_dummy_data()


def generate_dummy_data():
    """生成模拟演示数据"""
    records = []
    start_date = datetime.now() - timedelta(days=30)
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "ARB/USDT"]
    
    # 模拟30天的收益
    current_time = start_date
    while current_time < datetime.now():
        # 每天 3 次结算
        for _ in range(3):
            # 随机选取 1-3 个持仓
            active_symbols = random.sample(symbols, k=random.randint(1, 3))
            
            for symbol in active_symbols:
                # 模拟不同币种的费率波动
                base_rate = 0.0001 if symbol == "BTC/USDT" else 0.0005
                rate = abs(random.gauss(base_rate, 0.0002))
                rate = max(0.0001, rate) # 保证正数
                
                pos_value = 1000 # 假设 1000U 仓位
                profit = pos_value * rate
                
                records.append({
                    "symbol": symbol,
                    "timestamp": current_time,
                    "income": profit,
                    "rate": rate,
                    "position_value": pos_value
                })
        
        current_time += timedelta(hours=8)
    
    df = pd.DataFrame(records)
    logger.info(f"已生成 {len(df)} 条模拟数据用于演示")
    return df


def create_report(df):
    """创建可视化报表"""
    # 1. 数据预处理
    # 按天汇总
    daily_df = df.groupby(df['timestamp'].dt.date)['income'].sum().reset_index()
    daily_df['cumulative'] = daily_df['income'].cumsum()
    
    # 按币种汇总
    symbol_df = df.groupby('symbol')['income'].sum().reset_index()
    symbol_df = symbol_df.sort_values('income', ascending=True)

    # 2. 创建图表布局 (2行2列)
    fig = make_subplots(
        rows=2, cols=2,
        column_widths=[0.6, 0.4],
        row_heights=[0.6, 0.4],
        specs=[[{"colspan": 2}, None],
               [{"type": "bar"}, {"type": "pie"}]],
        subplot_titles=(
            '💰 累计收益曲线 (Cumulative Profit)',
            '📅每日收益分布 (Daily PnL)', 
            '🪙 币种贡献占比 (Profit by Symbol)'
        )
    )

    # 图表 1: 累计收益曲线 (面积图)
    fig.add_trace(
        go.Scatter(
            x=daily_df['timestamp'], 
            y=daily_df['cumulative'],
            mode='lines',
            name='累计收益',
            fill='tozeroy',
            line=dict(color='#00E396', width=3),
            hovertemplate='日期: %{x}<br>累计收益: $%{y:.2f}'
        ),
        row=1, col=1
    )

    # 图表 2: 每日收益 (柱状图)
    colors = ['#FF4560' if x < 0 else '#008FFB' for x in daily_df['income']]
    fig.add_trace(
        go.Bar(
            x=daily_df['timestamp'],
            y=daily_df['income'],
            name='每日收益',
            marker_color=colors,
            hovertemplate='日期: %{x}<br>当日收益: $%{y:.2f}'
        ),
        row=2, col=1
    )

    # 图表 3: 币种贡献 (甜甜圈图)
    fig.add_trace(
        go.Pie(
            labels=symbol_df['symbol'],
            values=symbol_df['income'],
            name='币种贡献',
            hole=0.4,
            marker=dict(colors=px.colors.qualitative.Pastel),
            textinfo='label+percent',
            hovertemplate='币种: %{label}<br>总贡献: $%{value:.2f}<br>占比: %{percent}'
        ),
        row=2, col=2
    )

    # 3. 样式美化
    total_profit = df['income'].sum()
    avg_daily = total_profit / len(daily_df) if len(daily_df) > 0 else 0
    max_drawdown = 0 # 简化处理，暂不计算回撤

    fig.update_layout(
        title_text=f"<b>资金费率套利收益分析报表</b><br>"
                   f"<span style='font-size: 14px; color: gray;'>"
                   f"总收益: ${total_profit:.2f} | 日均: ${avg_daily:.2f} | "
                   f"交易笔数: {len(df)} 笔"
                   f"</span>",
        template="plotly_white",
        height=800,
        showlegend=False,
        hovermode="x unified"
    )
    
    # 标记最大收益点
    fig.add_annotation(
        x=daily_df['timestamp'].iloc[-1],
        y=daily_df['cumulative'].iloc[-1],
        text=f"${total_profit:.2f}",
        showarrow=True,
        arrowhead=1,
        row=1, col=1
    )

    return fig


def main():
    logger.info("正在生成收益分析报表...")
    
    # 1. 加载数据
    df = load_data()
    
    if df.empty:
        logger.error("无数据可展示")
        return

    # 2. 创建图表
    fig = create_report(df)
    
    # 3. 保存文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 保存 HTML (交互式)
    html_file = OUTPUT_DIR / f"profit_report_{timestamp}.html"
    fig.write_html(str(html_file))
    logger.info(f"✅ HTML 报表已生成: {html_file}")
    
    # 保存 PNG (静态图片)
    # image_file = OUTPUT_DIR / f"profit_report_{timestamp}.png"
    # fig.write_image(str(image_file))
    # logger.info(f"✅ PNG 图片已生成: {image_file}")
    
    # 4. 尝试自动打开
    try:
        import webbrowser
        webbrowser.open(f"file://{html_file}")
    except:
        pass
    
    logger.info("完成!")


if __name__ == "__main__":
    main()
